"""Pickup Request: verified paid-session completion for the shared three-screen Flow.

The published Pickup template may still send the old F004 marker. We accept that
marker ONLY when the payload includes all four pickup fields and carries an
issued request_pickup token. The legacy generic note-only completion is never
misfiled as a pickup or Submit Request.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Optional

from lambda_utils import canonical_flows, contact_store, flow_completion, flow_sessions, shared_tables
from lambda_utils.ecommerce import single_order_flow

CAPABILITY = "request_pickup"
SERVICE_CODE = "REQUEST_PICKUP"
FLOW_CODE = "WD-F005-Pick-Up-Request"
FLOW_ID = canonical_flows.canonical_flow_id(CAPABILITY)
FLOW_NAME = "Pickup Request"
FLOW_KEY = "wd_f005_request_pickup"
CLONED_FLOW_KEY = "wd_f004_submit_request"
TOKEN_PREFIX = "request_pickup-"
WINDOWS = frozenset({"morning", "afternoon", "evening", "flexible"})
REJECTED = "This Pickup Request session is no longer available."


def _text(data: Dict, key: str, *, required: bool = False, limit: int = 2000) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        value = ""
    value = value.strip()
    if required and not value:
        raise ValueError("Pickup Request: missing " + key)
    if len(value) > limit:
        raise ValueError("Pickup Request: invalid " + key)
    return value


def pickup_payload(message: Dict[str, Any]) -> Optional[Dict]:
    """Recognize a Pickup completion without stealing any F004/other Flow."""
    if not isinstance(message, dict) or message.get("type") != "interactive":
        return None
    interactive = message.get("interactive") or {}
    if interactive.get("type") != "nfm_reply":
        return None
    raw = (interactive.get("nfm_reply") or {}).get("response_json", "{}")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("flow_token")
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX):
        return None
    if data.get("flow_key") not in (FLOW_KEY, CLONED_FLOW_KEY):
        return None
    # A cloned F004 payload contained only reference_number and note. Do not
    # interpret that as a paid pickup; refuse it until the Meta asset is fixed.
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in
               ("pickup_address", "preferred_date", "pickup_window",
                "package_description", "reference_number")):
        return None
    return data


def response_answers(data: Dict, result: flow_completion.CompletionResult) -> list:
    fields = (
        ("Order", "reference_number"),
        ("Pickup address", "pickup_address"),
        ("Preferred date", "preferred_date"),
        ("Preferred time", "pickup_window"),
        ("Items to collect", "package_description"),
        ("Notes", "notes"),
    )
    rows = [
        {"question": label, "answer": value.strip()}
        for label, key in fields
        if isinstance((value := data.get(key)), str) and value.strip()
    ]
    if result and result.submission_id:
        rows.append({"question": "Pickup reference", "answer": result.submission_id})
    return rows


def save_pickup(data: Dict, *, contact_id: str, phone: str, sender_name: str,
                message_id: str, dynamodb: Any, request_id: str = ""):
    """Save one pickup per paid attempt, owned by the verified customer/order."""
    if not contact_id or not phone or not message_id:
        raise ValueError("Pickup Request requires a verified sender and Meta message id")
    token = _text(data, "flow_token", required=True, limit=512)
    if not token.startswith(TOKEN_PREFIX):
        raise ValueError(REJECTED)

    session = flow_sessions.verify_session(
        dynamodb.Table(shared_tables.flow_drafts_table_name()),
        capability=CAPABILITY, token=token, rejected_message=REJECTED,
    )
    if contact_store.digits(phone) != session.phone:
        raise ValueError(REJECTED)
    binding = single_order_flow.verify_paid_session(
        session=session,
        attempts=dynamodb.Table(shared_tables.payment_attempts_table_name()),
        orders=dynamodb.Table(shared_tables.orders_table_name()),
        capability=CAPABILITY, service_code=SERVICE_CODE, phone=phone,
    )
    target = _text(data, "reference_number", required=True, limit=240)
    # The customer can only complete the one order bound at payment time.
    if target.upper() not in (
        "ORDER:" + binding.order_number.upper(), binding.order_number.upper()
    ):
        raise ValueError("Pickup order does not match the paid order")

    pickup_address = _text(data, "pickup_address", required=True, limit=2000)
    preferred_date = _text(data, "preferred_date", required=True, limit=30)
    try:
        date.fromisoformat(preferred_date)
    except (ValueError, TypeError) as exc:
        raise ValueError("Pickup Request: invalid preferred date") from exc
    pickup_window = _text(data, "pickup_window", required=True, limit=24)
    if pickup_window not in WINDOWS:
        raise ValueError("Pickup Request: invalid time window")
    package = _text(data, "package_description", required=True, limit=500)
    notes = _text(data, "notes", limit=2000)

    form = {
        "selected_target": "order:" + binding.order_number,
        "order_id": binding.order_id,
        "subject": "Pickup Request",
        "description": package,
        "pickup_address": pickup_address,
        "preferred_date": preferred_date,
        "pickup_window": pickup_window,
        "package_description": package,
        "notes": notes,
    }
    # The paid-attempt ID is the idempotency anchor: two Meta webhook messages
    # from the same purchase must never make two pickup business records.
    result = flow_completion.claim_completion(
        flow_token=binding.payment_attempt_id,
        screen="CONFIRMATION",
        flow_code=FLOW_CODE,
        flow_type="pickup_request",
        phone=contact_store.digits(phone),
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        reference_prefix="WD-PU",
        requires_payment=False,  # payment was captured BEFORE opening this Flow
        status="pending_confirmation",  # not a booked courier
        extra={
            "flowId": FLOW_ID,
            "flowName": FLOW_NAME,
            "schemaVersion": _text(data, "schema_version", limit=20) or "2",
            "source": "whatsapp",
            "paymentStatus": "paid",
            "paymentAttemptId": binding.payment_attempt_id,
            "orderId": binding.order_id,
            "orderNumber": binding.order_number,
            "serviceCode": SERVICE_CODE,
            "customerId": binding.customer_id,
            "whatsappMessageId": message_id,
        },
        ttl_seconds=0, request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
    )
    if result.status == "error":
        raise RuntimeError("Pickup completion could not be saved")

    flow_sessions.mark_consumed(
        dynamodb.Table(shared_tables.flow_drafts_table_name()), token=token)
    return result
