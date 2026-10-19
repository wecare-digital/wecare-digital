"""Validation for staff/web service requests linked to Commerce orders.

A service request is a case record, not a payment/refund/cancellation operation. This module
keeps that boundary explicit and shared by both deployed service handler copies.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

REQUEST_TYPES = frozenset({
    "Return / Refund",
    "Exchange",
    "Damaged / Defective",
    "Missing Item",
    "Wrong Item Received",
    "Delivery Issue",
    "Payment Issue",
    "General Inquiry",
    "Other",
})

_FINANCIAL_FIELDS = frozenset({
    "paymentRequired",
    "paymentStatus",
    "paymentAmount",
    "paymentRefId",
    "refundId",
    "refundAmount",
    "refundAmountPaise",
})


def _text(body: Mapping[str, Any], field: str, limit: int) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    raw = body.get(field)
    if not isinstance(raw, str):
        return None, {
            "error": f"{field} is required and must be text",
            "errorCode": "SERVICE_REQUEST_INPUT_INVALID",
        }
    value = raw.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None, {
            "error": f"{field} is missing, overlong, or contains control characters",
            "errorCode": "SERVICE_REQUEST_INPUT_INVALID",
        }
    return value, None


def validate(body: Mapping[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    """Return a cleaned case payload, or a stable validation error.

    Money/refund fields are deliberately rejected. Creating this record must never be confused
    with charging, cancelling, or refunding the linked order.
    """
    if not isinstance(body, Mapping):
        return None, {
            "error": "Request body must be an object",
            "errorCode": "SERVICE_REQUEST_INPUT_INVALID",
        }

    if any(field in body for field in _FINANCIAL_FIELDS):
        return None, {
            "error": "Service requests cannot change payment or refund state",
            "errorCode": "SERVICE_REQUEST_FINANCIAL_FIELDS_READ_ONLY",
        }

    order_id, error = _text(body, "orderId", 256)
    if error:
        return None, error
    request_type, error = _text(body, "requestType", 80)
    if error:
        return None, error
    if request_type not in REQUEST_TYPES:
        return None, {
            "error": "Unknown requestType",
            "errorCode": "SERVICE_REQUEST_TYPE_INVALID",
        }
    subject, error = _text(body, "subject", 200)
    if error:
        return None, error
    description, error = _text(body, "description", 2000)
    if error:
        return None, error

    return {
        "orderId": order_id,
        "requestType": request_type,
        "subject": subject,
        "description": description,
    }, None


__all__ = ["REQUEST_TYPES", "validate"]
