"""Published Request Pickup completion -> one paid-order FlowSubmission + Inbox projection.

Pickup is a paid single-order service. The terminal nfm_reply is accepted only when its
server-issued pickuppaid-* Flow session proves the finalized PaymentAttempt and the existing
Order service activity. No ServiceRequests row and no WD-REQ identifier are created.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from lambda_utils import canonical_flows, contact_store, flow_completion, flow_sessions, shared_tables
from lambda_utils.ecommerce import single_order_flow

CAPABILITY = "request_pickup"
DESIGN_SERVICE = "request-pickup"
TOKEN_PREFIX = "pickuppaid-"
FLOW_ID = canonical_flows.canonical_flow_id(CAPABILITY) or "2988393421499259"
FLOW_CODE = "WD_PICKUP"
FLOW_NAME = "WD-F005-Pick-Up-Request"
FLOW_VERSION = "7.3"
SUBMISSION_PREFIX = "WD-PU"


def _text(data: Dict[str, Any], key: str, *, required: bool = False,
          limit: int = 2000) -> str:
    value = str(data.get(key) or "").strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    return value[:limit]


def pickup_payload(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recognise only the published paid Pickup terminal reply."""
    if not isinstance(message, dict) or message.get("type") != "interactive":
        return None
    interactive = message.get("interactive") or {}
    if interactive.get("type") != "nfm_reply":
        return None
    raw = (interactive.get("nfm_reply") or {}).get("response_json", "{}")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("design_service") or "").strip() != DESIGN_SERVICE:
        return None
    if not str(data.get("flow_token") or "").strip().startswith(TOKEN_PREFIX):
        return None
    required = (
        "parent_order", "pickup_address", "preferred_date",
        "pickup_window", "package_description",
    )
    if any(not str(data.get(key) or "").strip() for key in required):
        return None
    return data


def _paid_binding(db: Any, data: Dict[str, Any], *, phone: str):
    token = _text(data, "flow_token", required=True, limit=512)
    try:
        session = flow_sessions.verify_session(
            db.Table(shared_tables.flow_drafts_table_name()),
            capability=CAPABILITY,
            token=token,
            rejected_message="This Pickup Request form is no longer available.",
        )
        binding = single_order_flow.verify_paid_session(
            session=session,
            attempts=db.Table(shared_tables.payment_attempts_table_name()),
            orders=db.Table(shared_tables.orders_table_name()),
            capability=CAPABILITY,
            service_code="REQUEST_PICKUP",
            phone=phone,
        )
    except (flow_sessions.FlowSessionRejected, flow_sessions.FlowSessionUnavailable,
            single_order_flow.PaidFlowBindingError) as exc:
        raise ValueError("This Pickup Request payment could not be verified.") from exc

    parent = _text(data, "parent_order", required=True, limit=240)
    if parent.upper() != binding.order_number.upper():
        raise ValueError("Pickup Request order does not match the paid order.")
    return session, binding


def response_answers(data: Dict[str, Any], result: flow_completion.CompletionResult) -> list:
    rows = [
        {"question": "Order", "answer": _text(data, "parent_order", limit=240)},
        {"question": "Pickup address", "answer": _text(data, "pickup_address", limit=1000)},
        {"question": "Preferred date", "answer": _text(data, "preferred_date", limit=40)},
        {"question": "Pickup window", "answer": _text(data, "pickup_window", limit=80)},
        {"question": "Package", "answer": _text(data, "package_description", limit=500)},
    ]
    notes = _text(data, "notes", limit=1000)
    if notes:
        rows.append({"question": "Notes", "answer": notes})
    if result and result.reference:
        rows.append({"question": "Pickup Request ID", "answer": result.reference})
    return rows


def save_pickup(data: Dict[str, Any], *, contact_id: str, phone: str, sender_name: str,
                message_id: str, dynamodb: Any, request_id: str = ""):
    """Persist exactly one paid Pickup completion and close its one fulfilment entitlement."""
    if not contact_id or not phone or not message_id:
        raise ValueError("Pickup Request requires a sender and Meta message id")

    session, binding = _paid_binding(dynamodb, data, phone=phone)
    address = _text(data, "pickup_address", required=True, limit=1000)
    date = _text(data, "preferred_date", required=True, limit=40)
    window = _text(data, "pickup_window", required=True, limit=80)
    package = _text(data, "package_description", required=True, limit=500)
    notes = _text(data, "notes", limit=1000)

    form = {
        "order_id": binding.order_id,
        "order_number": binding.order_number,
        "pickup_address": address,
        "preferred_date": date,
        "pickup_window": window,
        "package_description": package,
        "notes": notes,
        "subject": "Pickup Request",
        "description": package,
    }
    result = flow_completion.claim_completion(
        flow_token=message_id,
        screen="REVIEW",
        flow_code=FLOW_CODE,
        flow_type="pickup_request",
        phone=contact_store.digits(phone),
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        reference_prefix=SUBMISSION_PREFIX,
        requires_payment=False,
        payment_amount=0,
        status="submitted",
        extra={
            "flowId": FLOW_ID,
            "flowName": FLOW_NAME,
            "flowVersion": FLOW_VERSION,
            "source": "whatsapp",
            "customerPhone": contact_store.digits(phone),
            "customerName": sender_name,
            "whatsappDisplayName": sender_name,
            "whatsappMessageId": message_id,
            "paymentAttemptId": binding.payment_attempt_id,
            "singleOrderService": True,
            "orderId": binding.order_id,
            "orderNumber": binding.order_number,
            "pickupAddress": address,
            "preferredDate": date,
            "pickupWindow": window,
            "packageDescription": package,
            "notes": notes,
        },
        ttl_seconds=0,
        request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
    )
    if result.status == "error":
        raise RuntimeError("Pickup Request completion could not be saved")

    now = int(time.time())
    attempts = dynamodb.Table(shared_tables.payment_attempts_table_name())
    try:
        attempts.update_item(
            Key={"paymentAttemptId": binding.payment_attempt_id},
            UpdateExpression=(
                "SET pickupCompletedAt=:now, pickupFlowSubmissionId=:sid, "
                "fulfillmentCompletedAt=:now, updatedAt=:now"
            ),
            ConditionExpression=(
                "#status=:paid AND singleOrderService=:true AND serviceCode=:service "
                "AND selectedOrderId=:order AND customerId=:owner AND "
                "(attribute_not_exists(pickupCompletedAt) OR pickupFlowSubmissionId=:sid)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":now": now,
                ":sid": result.submission_id,
                ":paid": "PAYMENT_PAID",
                ":true": True,
                ":service": "REQUEST_PICKUP",
                ":order": binding.order_id,
                ":owner": binding.customer_id,
            },
        )
    except Exception as exc:
        current = attempts.get_item(
            Key={"paymentAttemptId": binding.payment_attempt_id},
            ConsistentRead=True,
        ).get("Item") or {}
        if str(current.get("pickupFlowSubmissionId") or "") != result.submission_id:
            raise RuntimeError("Pickup Request could not be bound to the paid attempt") from exc

    flow_sessions.mark_consumed(
        dynamodb.Table(shared_tables.flow_drafts_table_name()),
        token=_text(data, "flow_token", required=True, limit=512),
    )
    return result
