"""F008 Referral: one private, sender-owned WhatsApp Flow completion.

The published endpointless F008 sends a terminal `nfm_reply` with
`flow_key=wd_f008_referral`. This module saves it in the canonical
FlowSubmissionTable, which is the source for staff Flow Responses.

The person submitting the referral is the authenticated WhatsApp *sender*.
A referral never creates a contact for the third party, opts anyone into
marketing, sends a message, creates an invoice, or charges a payment.
Consent on this form is only an attestation that the referred person agreed
to have their number shared with WECARE.DIGITAL.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from lambda_utils import canonical_flows, flow_completion

logger = logging.getLogger(__name__)

CAPABILITY = "referral"
FLOW_ID = canonical_flows.canonical_flow_id(CAPABILITY)
FLOW_CODE = "WD-F008-REFERRAL"
FLOW_NAME = "WD-F008- Referal"
FLOW_KEY = "wd_f008_referral"
FLOW_VERSION = "7.3"
REFERENCE_PREFIX = "WD-REF"

_PHONE = re.compile(r"^\+?[1-9][0-9]{6,14}$")


def referral_payload(message: Any) -> Optional[Dict[str, Any]]:
    """Recognize only the published F008 terminal reply, not CTWA ad referrals."""
    if not isinstance(message, dict) or message.get("type") != "interactive":
        return None
    interactive = message.get("interactive") or {}
    if not isinstance(interactive, dict) or interactive.get("type") != "nfm_reply":
        return None
    reply = interactive.get("nfm_reply") or {}
    if not isinstance(reply, dict) or reply.get("name") == "address_message":
        return None
    raw = reply.get("response_json")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("flow_key") != FLOW_KEY:
        return None
    return data


def _text(data: Dict[str, Any], key: str, *, max_length: int, multiline: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    cleaned = value.strip() if multiline else " ".join(value.split())
    if not cleaned or len(cleaned) > max_length:
        raise ValueError(f"{key} is required and must be at most {max_length} characters")
    return cleaned


def clean_referral(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate submitted fields; never trust marketing consent or sender identity in payload."""
    name = _text(data, "referred_name", max_length=120)
    whatsapp = _text(data, "referred_whatsapp", max_length=30)
    whatsapp = re.sub(r"[ ()-]", "", whatsapp)
    if not _PHONE.fullmatch(whatsapp):
        raise ValueError("referred_whatsapp must be a valid international number")
    details = _text(data, "referral_details", max_length=300, multiline=True)
    agreed = data.get("permission_confirmed")
    if agreed is not True and not (isinstance(agreed, str) and agreed.strip().lower() == "true"):
        raise ValueError("Explicit sharing attestation is required")
    return {
        "referred_name": name,
        "referred_whatsapp": whatsapp,
        "referral_details": details,
        "permission_confirmed": True,
    }


def response_answers(form: Dict[str, Any]) -> list:
    return [
        {"question": "Their name", "answer": form["referred_name"]},
        {"question": "Their WhatsApp number", "answer": form["referred_whatsapp"]},
        {"question": "Anything we should know?", "answer": form["referral_details"]},
        {"question": "Permission to share their number", "answer": "Confirmed"},
    ]


def save_referral(data: Dict[str, Any], *, contact_id: str, phone: str,
                  sender_name: str, message_id: str, request_id: str = "",
                  customer_uuid_value: str = ""):
    """Durable, idempotent F008 submission owned by the WhatsApp sender.

    The stable Meta message ID is the completion key, so webhook retries return
    the same FlowSubmission and cannot create duplicate referrals.
    """
    if not contact_id or not phone or not message_id:
        raise ValueError("Referral requires authenticated sender, contact and Meta message id")
    form = clean_referral(data)
    form["subject"] = "Referral: " + form["referred_name"]
    form["description"] = form["referral_details"]
    result = flow_completion.claim_completion(
        flow_token=message_id,
        screen="CONFIRMATION",
        flow_code=FLOW_CODE,
        flow_type="referral",
        phone=phone,
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        reference_prefix=REFERENCE_PREFIX,
        requires_payment=False,
        status="open",
        request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
        extra={
            "flowId": FLOW_ID,
            "flowName": FLOW_NAME,
            "flowVersion": FLOW_VERSION,
            "schemaVersion": str(data.get("schema_version") or "1")[:12],
            "whatsappMessageId": message_id,
            "subject": form["subject"],
            "description": form["description"],
            "customerName": sender_name,
            "whatsappDisplayName": sender_name,
            "source": "whatsapp",
            "referralConsentScope": "number_shared_for_referral",
            "marketingOptIn": False,
            **({"customerUuid": customer_uuid_value} if customer_uuid_value else {}),
        },
    )
    if result.status == "error":
        logger.error('{"event":"f008_referral_submission_failed"}')
        raise RuntimeError("F008 referral submission could not be saved")
    return result
