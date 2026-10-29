"""Post-invoice launcher for new single-order paid request services.

This path never creates a ServiceRequests row. The verified PaymentAttempt and the service activity
already appended to the customer's existing Order are the authority. One server-recorded Flow
session is issued before the approved Utility launcher template is sent.

Pickup is deliberately excluded until its corrected replacement Flow and dedicated completion
writer are published.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import boto3

from lambda_utils import (
    contact_key,
    contact_store,
    customer_auth,
    flow_sessions,
    shared_tables,
    whatsapp_templates,
)
from lambda_utils.ecommerce import request_service_contracts

WABA1_SENDER = os.environ.get(
    "WHATSAPP_PHONE_NUMBER_ID_1",
    "phone-number-id-waba1-direct-1016149501586345",
)
ROLLOUT_ENV = "REQUEST_SERVICE_FLOW_LAUNCH_ENABLED"

_SUPPORTED = {
    "SUBMIT_REQUEST": "srpaid",
    "REQUEST_AMENDMENT": "amendpaid",
    "DROP_DOCS": "droppaid",
}


def _enabled() -> bool:
    return str(os.environ.get(ROLLOUT_ENV, "false")).strip().lower() == "true"


def _outcome(response: Any) -> str:
    if not isinstance(response, dict):
        return "SEND_UNKNOWN"
    code = int(response.get("statusCode") or 0)
    if 200 <= code < 300:
        return "ACCEPTED"
    # These are deterministic pre-send/template/build/authorization refusals. They are safe to
    # retry after configuration/template repair. An invoke timeout remains SEND_UNKNOWN.
    if code in (400, 401, 403, 404, 409, 413, 415, 422, 503):
        return "SEND_REJECTED"
    return "SEND_UNKNOWN"


def _recipient(db: Any, attempt: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], str]]:
    customer_id = str(attempt.get("customerId") or "")
    if not customer_auth.is_cognito_subject(customer_id):
        return None
    users = boto3.client("cognito-idp").list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + customer_id + '"',
        Limit=2,
    ).get("Users") or []
    if len(users) != 1 or not users[0].get("Enabled", True):
        return None
    attrs = {a["Name"]: a["Value"] for a in users[0].get("Attributes", [])}
    phone = str(attrs.get("phone_number") or "")
    if attrs.get("phone_number_verified") != "true" or not phone:
        return None

    contacts = db.Table(shared_tables.contacts_table_name())
    try:
        contact = contact_store.find_by_phone(contacts, phone)
    except contact_store.IdentityConflict:
        return None
    if (
        not contact
        or str(contact.get("checkoutCustomerId") or "") != customer_id
        or contact.get("deletedAt") is not None
        or contact.get("isDeleted")
    ):
        return None
    return contact, phone


def _verified_context(db: Any, attempt: Dict[str, Any]) -> Optional[Dict[str, str]]:
    attempt_id = str(attempt.get("paymentAttemptId") or "")
    service_code = str(attempt.get("serviceCode") or "").strip().upper()
    order_id = str(attempt.get("selectedOrderId") or "")
    order_number = str(attempt.get("selectedOrderNumber") or "").strip().upper()
    capability = str(attempt.get("flowCapability") or "")
    customer_id = str(attempt.get("customerId") or "")

    contract = request_service_contracts.request_service_contract(service_code)
    if (
        not attempt_id
        or service_code not in _SUPPORTED
        or contract is None
        or not attempt.get("singleOrderService")
        or str(attempt.get("status") or "") != "PAYMENT_PAID"
        or str(attempt.get("finalizationStage") or "") != "ORDER_FINALIZED"
        or not order_id
        or not order_number.startswith("WD-ORD-")
        or capability != contract.flow_capability
        or str(attempt.get("serviceSku") or "").upper() != contract.sku
    ):
        return None

    order = db.Table(shared_tables.orders_table_name()).get_item(
        Key={"orderId": order_id}, ConsistentRead=True
    ).get("Item") or {}
    if (
        str(order.get("orderNumber") or "").upper() != order_number
        or str(order.get("customerId") or "") != customer_id
        or attempt_id not in [str(x) for x in (order.get("serviceActivityPaymentIds") or [])]
    ):
        return None
    matching = [
        row for row in (order.get("serviceActivities") or [])
        if isinstance(row, dict)
        and str(row.get("paymentAttemptId") or "") == attempt_id
        and str(row.get("serviceCode") or "").upper() == service_code
        and str(row.get("flowCapability") or "") == capability
    ]
    if len(matching) != 1:
        return None
    return {
        "paymentAttemptId": attempt_id,
        "serviceCode": service_code,
        "orderId": order_id,
        "orderNumber": order_number,
        "capability": capability,
        "customerId": customer_id,
        "tokenPrefix": _SUPPORTED[service_code],
    }


def prepare_and_send(event: Dict[str, Any], lambda_client: Any) -> Dict[str, Any]:
    """Send exactly one post-invoice Flow launcher for a supported single-order service."""
    if not _enabled():
        return {"outcome": "SERVICE_FLOW_LAUNCH_DISABLED"}

    db = boto3.resource("dynamodb")
    attempts = db.Table(shared_tables.payment_attempts_table_name())
    attempt_id = str(event.get("paymentAttemptId") or "")
    if not attempt_id:
        return {"outcome": "PAYMENT_ATTEMPT_REQUIRED"}
    attempt = attempts.get_item(
        Key={"paymentAttemptId": attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    context = _verified_context(db, attempt)
    if context is None:
        return {"outcome": "SINGLE_ORDER_FLOW_CONTEXT_INVALID"}

    service_code = context["serviceCode"]
    current = str(attempt.get("serviceFlowNotificationStatus") or "")
    if attempt.get("fulfillmentCompletedAt"):
        return {"outcome": "SERVICE_FLOW_ALREADY_COMPLETED"}
    if current == "ACCEPTED":
        return {"outcome": "SERVICE_FLOW_ALREADY_SENT", "serviceCode": service_code}
    if current in ("SENDING", "SEND_UNKNOWN"):
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED", "serviceCode": service_code}

    resolved = _recipient(db, attempt)
    if not resolved:
        return {"outcome": "VERIFIED_RECIPIENT_UNAVAILABLE", "serviceCode": service_code}
    contact, phone = resolved

    token = flow_sessions.mint_token(context["tokenPrefix"], phone, "1")
    try:
        send_fields = whatsapp_templates.paid_service_flow_send_fields(
            service_code, context["orderNumber"], token)
    except ValueError:
        return {"outcome": "SERVICE_FLOW_TEMPLATE_UNAVAILABLE", "serviceCode": service_code}

    try:
        flow_sessions.record_session(
            db.Table(flow_sessions.table_name()),
            capability=context["capability"],
            token=token,
            launch_channel=flow_sessions.LAUNCH_PAYMENT,
            initiated_by="single_order_post_invoice",
            payment_attempt_id=attempt_id,
            order_id=context["orderId"],
            order_number=context["orderNumber"],
            service_code=service_code,
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_SESSION_UNAVAILABLE", "serviceCode": service_code}

    now = int(time.time())
    try:
        attempts.update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression=(
                "SET serviceFlowNotificationStatus=:sending, serviceFlowIssuedAt=:now, "
                "serviceFlowTemplateName=:template, serviceFlowCapability=:cap, "
                "serviceFlowSendAttempts=if_not_exists(serviceFlowSendAttempts,:zero)+:one, "
                "updatedAt=:now"
            ),
            ConditionExpression=(
                "#status=:paid AND finalizationStage=:finalized "
                "AND attribute_not_exists(fulfillmentCompletedAt) "
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
                ":template": str(send_fields.get("templateName") or ""),
                ":cap": context["capability"],
                ":zero": 0,
                ":one": 1,
            },
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED", "serviceCode": service_code}

    body = {
        "contactId": contact_key.resolve(contact),
        "recipientPhone": phone,
        "phoneNumberId": WABA1_SENDER,
        **send_fields,
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

    send_status = _outcome(answer)
    try:
        attempts.update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression=(
                "SET serviceFlowNotificationStatus=:status, "
                "serviceFlowNotificationUpdatedAt=:now, updatedAt=:now"
            ),
            ConditionExpression="serviceFlowNotificationStatus=:sending",
            ExpressionAttributeValues={
                ":status": send_status,
                ":now": int(time.time()),
                ":sending": "SENDING",
            },
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED", "serviceCode": service_code}

    return {
        "outcome": "SERVICE_FLOW_SENT" if send_status == "ACCEPTED"
        else "SERVICE_FLOW_PENDING",
        "serviceCode": service_code,
        "orderNumber": context["orderNumber"],
        "sendStatus": send_status,
    }
