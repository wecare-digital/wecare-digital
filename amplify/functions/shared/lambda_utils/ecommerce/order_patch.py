"""Safe staff patch contract for OrderTable rows.

This module deliberately keeps payment state provider-controlled. A browser or generic service
PATCH may update fulfilment or operator notes, but it cannot mark money captured/refunded.

Fulfilment uses the same Meta lifecycle as invoice-engine order_status updates. Legacy order words
are accepted only as CURRENT-state aliases; every new write is canonical.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from lambda_utils import payment_status as pay_status
from lambda_utils.ecommerce import wa_order_status

_STATUS_FIELDS = ("orderStatus", "status", "fulfillmentStatus")


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

    updates: Dict[str, Any] = {}

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
            # Idempotent retry after an unknown network outcome: writing the same canonical
            # state again is safe and avoids turning a successful first PATCH into a 400.
            updates["orderStatus"] = target
            updates["status"] = target
        elif target == wa_order_status.CANCELED:
            if payment_state == pay_status.CAPTURED:
                return None, {
                    "error": "A paid order cannot be cancelled through the generic order patch",
                    "errorCode": "PAID_ORDER_CANCEL_REQUIRES_WORKFLOW",
                }
            if not wa_order_status.can_transition(current_status, target):
                return None, {
                    "error": f"Illegal fulfilment transition: {current_status} -> {target}",
                    "errorCode": "ORDER_STATUS_TRANSITION_INVALID",
                }
            updates["orderStatus"] = target
            updates["status"] = target
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


__all__ = ["validate_order_patch"]
