"""Safe staff patch contract for OrderTable rows.

This module deliberately keeps payment state provider-controlled. A browser or generic service
PATCH may update fulfilment or operator notes, but it cannot mark money captured/refunded.

Fulfilment uses the same Meta lifecycle as invoice-engine order_status updates. Legacy order words
are accepted only as CURRENT-state aliases; every new write is canonical.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse

from lambda_utils import payment_status as pay_status
from lambda_utils.ecommerce import wa_order_status

_STATUS_FIELDS = ("orderStatus", "status", "fulfillmentStatus")
_TRACKING_FIELDS = ("carrierName", "trackingNumber", "trackingUrl")
_TRACKING_SERVER_FIELDS = ("trackingSource", "trackingUpdatedAt")
_TRACKING_LIMITS = {"carrierName": 120, "trackingNumber": 160, "trackingUrl": 2048}


def _legacy_current(raw: str, payment_state: str) -> Tuple[str, bool]:
    value = wa_order_status.normalise(raw)
    if not value:
        return wa_order_status.PENDING, True
    if value == "active":
        return (
            wa_order_status.PROCESSING
            if payment_state == pay_status.CAPTURED
            else wa_order_status.PENDING,
            True,
        )
    if value == "fulfilled":
        return wa_order_status.COMPLETED, True
    if value == "cancelled":
        return wa_order_status.CANCELED, True
    if wa_order_status.is_valid(value):
        return value, True
    return value, False


def _tracking_updates(body: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validate manual shipment metadata without claiming a courier integration."""
    if any(field in body for field in _TRACKING_SERVER_FIELDS):
        return None, {
            "error": "Tracking provenance and timestamps are server-controlled",
            "errorCode": "ORDER_TRACKING_SYSTEM_FIELD_READ_ONLY",
        }

    if not any(field in body for field in _TRACKING_FIELDS):
        return {}, None

    updates: Dict[str, Any] = {}
    for field in _TRACKING_FIELDS:
        if field not in body:
            continue
        raw = body.get(field)
        if raw is None:
            value = ""
        elif isinstance(raw, str):
            value = raw.strip()
        else:
            return None, {
                "error": f"{field} must be text",
                "errorCode": "ORDER_TRACKING_INVALID",
            }
        if len(value) > _TRACKING_LIMITS[field] or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            return None, {
                "error": f"{field} contains invalid or overlong text",
                "errorCode": "ORDER_TRACKING_INVALID",
            }
        updates[field] = value

    tracking_url = updates.get("trackingUrl", "")
    if tracking_url:
        invalid_url = any(ch.isspace() for ch in tracking_url) or "\\" in tracking_url
        try:
            parsed = urlparse(tracking_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError:
            invalid_url = True
            hostname = None
            parsed = None
        if (
            invalid_url
            or parsed is None
            or parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None, {
                "error": "trackingUrl must be a valid HTTPS URL without embedded credentials",
                "errorCode": "ORDER_TRACKING_URL_INVALID",
            }

    updates["trackingSource"] = "manual"
    return updates, None


def validate_order_patch(
    current: Mapping[str, Any],
    body: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (updates, error). Callers choose the HTTP status for any error."""
    if "paymentStatus" in body:
        return None, {
            "error": "paymentStatus is provider-controlled and cannot be changed here",
            "errorCode": "PAYMENT_STATUS_READ_ONLY",
        }

    tracking_updates, tracking_error = _tracking_updates(body)
    if tracking_error:
        return None, tracking_error

    updates: Dict[str, Any] = dict(tracking_updates or {})

    if "adminNotes" in body or "notes" in body:
        updates["adminNotes"] = body.get("adminNotes", body.get("notes", ""))

    raw_targets = [body.get(field) for field in _STATUS_FIELDS if field in body]
    if raw_targets:
        normalized = [wa_order_status.normalise(value) for value in raw_targets]
        if any(not wa_order_status.is_valid(value) for value in normalized):
            return None, {
                "error": "Unrecognised fulfilment status",
                "errorCode": "ORDER_STATUS_INVALID",
            }
        if len(set(normalized)) != 1:
            return None, {
                "error": "Conflicting fulfilment status fields",
                "errorCode": "ORDER_STATUS_CONFLICT",
            }

        target = normalized[0]
        payment_state = pay_status.canonical(current.get("paymentStatus"))
        current_raw = str(
            current.get("orderStatus")
            or current.get("fulfillmentStatus")
            or current.get("status")
            or ""
        )
        current_status, known = _legacy_current(current_raw, payment_state)

        if not known:
            return None, {
                "error": "Existing fulfilment state is unknown and needs review",
                "errorCode": "ORDER_STATUS_REVIEW_REQUIRED",
            }

        if target == current_status:
            updates["orderStatus"] = target
            updates["status"] = target
        elif target == wa_order_status.CANCELED:
            return None, {
                "error": "Order cancellation requires the audited cancellation workflow",
                "errorCode": "ORDER_CANCEL_REQUIRES_WORKFLOW",
            }
        else:
            if payment_state != pay_status.CAPTURED:
                return None, {
                    "error": "Fulfilment cannot advance until payment is captured",
                    "errorCode": "ORDER_PAYMENT_NOT_CAPTURED",
                }
            if not wa_order_status.can_transition(current_status, target):
                return None, {
                    "error": f"Illegal fulfilment transition: {current_status} -> {target}",
                    "errorCode": "ORDER_STATUS_TRANSITION_INVALID",
                }
            updates["orderStatus"] = target
            updates["status"] = target

    if not updates:
        return None, {
            "error": "No supported order fields supplied",
            "errorCode": "ORDER_PATCH_EMPTY",
        }

    return updates, None


def validate_order_cancellation(
    current: Mapping[str, Any],
    reason: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validate the explicit audited cancellation command.

    This is intentionally separate from validate_order_patch: generic status updates are
    never allowed to cancel. An existing order can be cancelled here only while no money
    has moved and before fulfilment has started. The caller supplies actor/time/history.
    """
    if not isinstance(reason, str):
        return None, {
            "error": "Cancellation reason is required",
            "errorCode": "ORDER_CANCEL_REASON_REQUIRED",
        }
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        return None, {
            "error": "Cancellation reason is required",
            "errorCode": "ORDER_CANCEL_REASON_REQUIRED",
        }
    if len(cleaned_reason) > 500 or any(
        (ord(ch) < 32 and ch not in "\r\n\t") or ord(ch) == 127
        for ch in cleaned_reason
    ):
        return None, {
            "error": "Cancellation reason contains invalid or overlong text",
            "errorCode": "ORDER_CANCEL_REASON_INVALID",
        }

    payment_state = pay_status.canonical(current.get("paymentStatus"))
    if pay_status.rank(payment_state) >= pay_status.rank(pay_status.CAPTURED):
        return None, {
            "error": "Money has moved for this order; use the return/refund workflow",
            "errorCode": "ORDER_CANCEL_MONEY_MOVED",
        }
    if current.get("paymentStatus") and not payment_state:
        return None, {
            "error": "Existing payment state is unknown and needs review",
            "errorCode": "ORDER_CANCEL_PAYMENT_REVIEW_REQUIRED",
        }

    current_raw = str(
        current.get("orderStatus")
        or current.get("fulfillmentStatus")
        or current.get("status")
        or ""
    )
    current_status, known = _legacy_current(current_raw, payment_state)
    if not known:
        return None, {
            "error": "Existing fulfilment state is unknown and needs review",
            "errorCode": "ORDER_STATUS_REVIEW_REQUIRED",
        }

    if current_status == wa_order_status.CANCELED:
        return {
            "reason": cleaned_reason,
            "currentStatus": current_status,
            "idempotent": True,
        }, None

    if current_status != wa_order_status.PENDING:
        return None, {
            "error": f"Order cannot be cancelled after fulfilment started ({current_status})",
            "errorCode": "ORDER_CANCEL_STATE_INVALID",
        }

    return {
        "reason": cleaned_reason,
        "currentStatus": current_status,
        "idempotent": False,
    }, None


__all__ = ["validate_order_patch", "validate_order_cancellation"]
