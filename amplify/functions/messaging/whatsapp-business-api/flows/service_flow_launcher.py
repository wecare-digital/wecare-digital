"""Exactly-once post-invoice launcher for paid customer-service WhatsApp Flows.

This module owns the common send seam:
    verified paid attempt -> confirmed invoice -> one server Flow session -> one UTILITY template.

The template body carries no order/customer variables. Authorization stays server-side in the
Flow session, which is recorded before the message can leave. A webhook replay therefore either
observes ACCEPTED, refuses an ambiguous SENDING/SEND_UNKNOWN state, or safely retries a known
SEND_REJECTED outcome with a fresh token.

Request Pickup deliberately remains disabled here. Its current published Flow is a cloned Submit
Request asset and does not carry the pickup-specific completion schema. Sending it would be worse
than failing closed because a successful customer completion could be filed as the wrong service.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

import boto3

from lambda_utils import (
    canonical_flows,
    contact_key,
    contact_store,
    customer_auth,
    flow_sessions,
    shared_tables,
    whatsapp_templates,
)

PRIMARY_SENDER = os.environ.get(
    "WHATSAPP_PHONE_NUMBER_ID_1",
    "phone-number-id-waba1-direct-1016149501586345",
)


@dataclass(frozen=True)
class LaunchSpec:
    service_code: str
    capability: str
    token_prefix: str
    enabled: bool = True
    blocked_outcome: str = ""


LAUNCH_SPECS: Mapping[str, LaunchSpec] = {
    "SUBMIT_REQUEST": LaunchSpec("SUBMIT_REQUEST", "submit_request", "srpaid"),
    "REQUEST_AMENDMENT": LaunchSpec("REQUEST_AMENDMENT", "amend_request", "amendpaid"),
    "DROP_DOCS": LaunchSpec("DROP_DOCS", "drop_docs", "drop_docs"),
    # Registered now so one source explains the intentional refusal. Enable only after the
    # published Pickup Flow is replaced with the pickup-specific asset and completion saver.
    "REQUEST_PICKUP": LaunchSpec(
        "REQUEST_PICKUP", "request_pickup", "request_pickup",
        enabled=False, blocked_outcome="PICKUP_FLOW_ASSET_MISMATCH",
    ),
    "TRACK_SHIPPING": LaunchSpec("TRACK_SHIPPING", "shipments", "shipments"),
}


def _send_outcome(response: Any) -> str:
    if not isinstance(response, dict):
        return "SEND_UNKNOWN"
    try:
        code = int(response.get("statusCode") or 0)
    except (TypeError, ValueError):
        return "SEND_UNKNOWN"
    if 200 <= code < 300:
        return "ACCEPTED"
    if code in (400, 401, 403, 404, 409, 413, 415, 422):
        return "SEND_REJECTED"
    return "SEND_UNKNOWN"


def _recipient(db: Any, customer_id: str):
    """Resolve the verified customer phone and canonical contact without trusting input."""
    if not customer_auth.is_cognito_subject(customer_id):
        return None
    users = boto3.client(
        "cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1")
    ).list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + customer_id + '"',
        Limit=2,
    ).get("Users") or []
    if len(users) != 1 or not users[0].get("Enabled", True):
        return None
    attrs = {a["Name"]: a["Value"] for a in users[0].get("Attributes", [])}
    phone = contact_store.canonical_phone(attrs.get("phone_number"))
    if attrs.get("phone_number_verified") != "true" or not phone:
        return None
    contacts = db.Table(shared_tables.contacts_table_name())
    try:
        contact = contact_store.find_by_phone(contacts, phone)
    except contact_store.IdentityConflict:
        return None
    if (not contact_store.is_live(contact)
            or str(contact.get("checkoutCustomerId") or "") != customer_id
            or contact_store.canonical_phone(contact.get("phone")) != phone):
        return None
    return contact, phone


def _paid_attempt(db: Any, *, payment_attempt_id: str, order_id: str,
                  order_number: str, service_code: str) -> dict:
    attempt = db.Table(shared_tables.payment_attempts_table_name()).get_item(
        Key={"paymentAttemptId": payment_attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    if (str(attempt.get("status") or "") != "PAYMENT_PAID"
            or str(attempt.get("finalizationStage") or "") != "ORDER_FINALIZED"
            or str(attempt.get("orderId") or "") != order_id
            or attempt.get("singleOrderService") is not True
            or str(attempt.get("serviceCode") or "").upper() != service_code
            or str(attempt.get("selectedOrderId") or "") != order_id
            or str(attempt.get("selectedOrderNumber") or "").upper() != order_number.upper()):
        return {}
    return attempt


def _track_purchase_attempt(db: Any, *, payment_attempt_id: str, order_id: str) -> dict:
    """A finalized ordinary order containing one Track Shipping product line, or {}."""
    attempt = db.Table(shared_tables.payment_attempts_table_name()).get_item(
        Key={"paymentAttemptId": payment_attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    if (str(attempt.get("status") or "") != "PAYMENT_PAID"
            or str(attempt.get("finalizationStage") or "") != "ORDER_FINALIZED"
            or str(attempt.get("orderId") or "") != order_id
            or attempt.get("singleOrderService") is True):
        return {}
    spec = attempt.get("invoiceLines") if isinstance(attempt.get("invoiceLines"), dict) else {}
    lines = spec.get("lines") if isinstance(spec.get("lines"), list) else []
    matches = [
        line for line in lines
        if isinstance(line, dict)
        and str(line.get("variantId") or "").strip().upper() == "SHT8M5P3"
        and type(line.get("quantity")) is int
        and line.get("quantity") == 1
    ]
    return attempt if len(matches) == 1 else {}


def _launch_verified_attempt(
    *,
    db: Any,
    attempts: Any,
    attempt: dict,
    spec: LaunchSpec,
    code: str,
    order_id: str,
    order_number: str,
    lambda_client: Any,
) -> dict:
    """Issue the session and send one launcher for an already-verified paid attempt."""
    flow = canonical_flows.published_flow(spec.capability)
    template = whatsapp_templates.service_flow_template(code)
    if (flow is None or template is None or template.category != "UTILITY"
            or template.buttons != ("flow",)):
        return {"outcome": "SERVICE_FLOW_LAUNCH_UNAVAILABLE", "serviceCode": code}

    payment_attempt_id = str(attempt.get("paymentAttemptId") or "").strip()
    if not payment_attempt_id or not order_id or not order_number:
        return {"outcome": "SERVICE_FLOW_PAYMENT_CONTEXT_MISSING", "serviceCode": code}

    current = str(attempt.get("serviceFlowNotificationStatus") or "")
    if current == "ACCEPTED":
        return {"outcome": "SERVICE_FLOW_ALREADY_SENT", "serviceCode": code}
    if current in ("SENDING", "SEND_UNKNOWN"):
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED", "serviceCode": code}

    resolved = _recipient(db, str(attempt.get("customerId") or ""))
    if not resolved:
        return {"outcome": "VERIFIED_RECIPIENT_UNAVAILABLE", "serviceCode": code}
    contact, phone = resolved

    token = flow_sessions.mint_token(spec.token_prefix, phone, "1")
    try:
        flow_sessions.record_session(
            db.Table(flow_sessions.table_name()),
            capability=spec.capability,
            token=token,
            launch_channel=flow_sessions.LAUNCH_PAYMENT,
            initiated_by="post_invoice_service_flow",
            payment_attempt_id=payment_attempt_id,
            order_id=order_id,
            order_number=order_number,
            service_code=code,
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_SESSION_UNAVAILABLE", "serviceCode": code}

    now = int(time.time())
    try:
        attempts.update_item(
            Key={"paymentAttemptId": payment_attempt_id},
            UpdateExpression=(
                "SET serviceFlowNotificationStatus=:sending, serviceFlowIssuedAt=:now, "
                "serviceFlowTemplateName=:template, serviceFlowId=:flow, updatedAt=:now"
            ),
            ConditionExpression=(
                "#status=:paid AND finalizationStage=:finalized "
                "AND (attribute_not_exists(serviceFlowNotificationStatus) "
                "OR serviceFlowNotificationStatus=:rejected)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":sending": "SENDING",
                ":rejected": "SEND_REJECTED",
                ":paid": "PAYMENT_PAID",
                ":finalized": "ORDER_FINALIZED",
                ":now": now,
                ":template": template.name,
                ":flow": flow["flowId"],
            },
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED", "serviceCode": code}

    body = {
        "contactId": contact_key.resolve(contact),
        "recipientPhone": phone,
        "phoneNumberId": str(attempt.get("phoneId") or PRIMARY_SENDER),
        **whatsapp_templates.service_flow_send_fields(code, token),
    }
    answer = None
    try:
        response = lambda_client.invoke(
            FunctionName="wecare-outbound-whatsapp:live",
            InvocationType="RequestResponse",
            Payload=json.dumps({"body": json.dumps(body)}).encode(),
        )
        raw = response["Payload"].read()
        answer = json.loads(raw or b"{}")
        if response.get("FunctionError"):
            answer = None
    except Exception:
        answer = None

    status = _send_outcome(answer)
    try:
        attempts.update_item(
            Key={"paymentAttemptId": payment_attempt_id},
            UpdateExpression=(
                "SET serviceFlowNotificationStatus=:status, "
                "serviceFlowNotificationUpdatedAt=:now, updatedAt=:now"
            ),
            ExpressionAttributeValues={":status": status, ":now": int(time.time())},
        )
    except Exception:
        # The wire result is more important than a projection write. Treat an unrecorded
        # accepted send as ambiguous so no caller automatically emits a duplicate.
        if status == "ACCEPTED":
            status = "SEND_UNKNOWN"

    return {
        "outcome": "SERVICE_FLOW_SENT" if status == "ACCEPTED" else "SERVICE_FLOW_PENDING",
        "serviceCode": code,
        "flowCapability": spec.capability,
        "sendStatus": status,
    }


def launch_single_order_service(
    *,
    event: dict,
    service_code: str,
    capability: str,
    order_id: str,
    order_number: str,
    lambda_client: Any,
) -> dict:
    """Send one post-invoice request-service launcher, or fail closed."""
    code = str(service_code or "").strip().upper()
    spec = LAUNCH_SPECS.get(code)
    if spec is None or spec.capability != str(capability or "").strip():
        return {"outcome": "SERVICE_FLOW_LAUNCH_CONTRACT_MISMATCH"}
    if not spec.enabled:
        return {"outcome": spec.blocked_outcome or "SERVICE_FLOW_LAUNCH_DISABLED",
                "serviceCode": code}

    payment_attempt_id = str(event.get("paymentAttemptId") or "").strip()
    if not payment_attempt_id or not order_id or not order_number:
        return {"outcome": "SERVICE_FLOW_PAYMENT_CONTEXT_MISSING", "serviceCode": code}

    db = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    attempts = db.Table(shared_tables.payment_attempts_table_name())
    attempt = _paid_attempt(
        db,
        payment_attempt_id=payment_attempt_id,
        order_id=order_id,
        order_number=order_number,
        service_code=code,
    )
    if not attempt:
        return {"outcome": "SERVICE_FLOW_PAYMENT_NOT_FINALIZED", "serviceCode": code}
    return _launch_verified_attempt(
        db=db,
        attempts=attempts,
        attempt=attempt,
        spec=spec,
        code=code,
        order_id=order_id,
        order_number=order_number,
        lambda_client=lambda_client,
    )


def launch_track_shipping_purchase(event: dict, lambda_client: Any):
    """Launch Track Shipping after a paid Shop/catalog order containing SKU SHT8M5P3.

    Returns None when the finalized order did not buy Track Shipping, allowing the legacy
    non-service post-invoice path to continue unchanged.
    """
    payment_attempt_id = str(event.get("paymentAttemptId") or "").strip()
    order_id = str(event.get("orderId") or "").strip()
    if not payment_attempt_id or not order_id:
        return None
    db = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    attempts = db.Table(shared_tables.payment_attempts_table_name())
    attempt = _track_purchase_attempt(
        db, payment_attempt_id=payment_attempt_id, order_id=order_id
    )
    if not attempt:
        return None
    order_number = str(attempt.get("orderNumber") or "").strip().upper()
    spec = LAUNCH_SPECS["TRACK_SHIPPING"]
    return _launch_verified_attempt(
        db=db,
        attempts=attempts,
        attempt=attempt,
        spec=spec,
        code="TRACK_SHIPPING",
        order_id=order_id,
        order_number=order_number,
        lambda_client=lambda_client,
    )


__all__ = [
    "LaunchSpec", "LAUNCH_SPECS", "launch_single_order_service",
    "launch_track_shipping_purchase",
]
