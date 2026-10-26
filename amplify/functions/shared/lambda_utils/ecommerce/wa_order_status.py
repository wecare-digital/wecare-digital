"""Meta WhatsApp order_status fulfilment vocabulary and the legal transitions between states.

What this module is for
-----------------------
A WhatsApp `order_details` payment carries an ORDER that has a fulfilment lifecycle SEPARATE from
the payment's money state. Meta's order_status message updates that lifecycle, and Meta enforces
the transitions: an illegal transition is rejected with webhook error 2046, and cancelling an
order that already has a successful or pending payment is rejected with 2047.

This is NOT the payment vocabulary. `payment_status` (captured/failed/…) is what the MONEY did;
`order_status` here is what the FULFILMENT did (the merchant shipped it, completed it, cancelled
it). They are deliberately different modules so a reader is never tempted to drive a shipment off
a capture word or vice versa.

One home for the rules
----------------------
The valid states and the legal forward transitions live here so the invoice-engine sender (which
validates a staff-requested transition before asking Meta) and the tests read the SAME table.
Meta remains the final authority — a transition this module permits can still be refused by Meta
(the order's real state lives on Meta's side) — but refusing locally what Meta would refuse keeps
a bad request off the wire and gives staff an immediate, named reason.
"""
from __future__ import annotations

import re
from typing import Dict, FrozenSet

# ── The Meta order_status fulfilment vocabulary (v25.0). ──────────────────────────────────────
#: Payment not completed yet. The state an order_details message opens in; never a staff target.
PENDING = "pending"
#: Payment authorised; the merchant is fulfilling. Emitted automatically at capture.
PROCESSING = "processing"
#: Some of the order's products have shipped.
PARTIALLY_SHIPPED = "partially-shipped"
#: All products have shipped.
SHIPPED = "shipped"
#: Done; no further action expected from the customer or the merchant.
COMPLETED = "completed"
#: The merchant cancelled the order_details message. Meta refuses this (2047) once a payment is
#: successful or pending, so it is only ever legal on an UNPAID order.
CANCELED = "canceled"

#: Every state Meta's order_status message accepts, as the exact wire spelling.
ALL_STATUSES: FrozenSet[str] = frozenset({
    PENDING, PROCESSING, PARTIALLY_SHIPPED, SHIPPED, COMPLETED, CANCELED,
})

#: Physical/service fulfilment statuses. These are deliberately NOT the payment-only WhatsApp
#: order lifecycle. Callers that manage a genuine shipment may use this broader vocabulary.
STAFF_FULFILMENT_TARGETS: FrozenSet[str] = frozenset({
    PROCESSING, PARTIALLY_SHIPPED, SHIPPED, COMPLETED,
})

#: The WhatsApp ORDER_DETAILS payment rail is intentionally collapsed. It proves payment progress,
#: not physical shipment: pending -> processing -> completed. The invoice engine MUST use this set
#: rather than STAFF_FULFILMENT_TARGETS so Workspace can never mark a payment-only order shipped.
PAYMENT_ORDER_TARGETS: FrozenSet[str] = frozenset({PROCESSING, COMPLETED})

_PAYMENT_ORDER_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    PENDING: frozenset({PROCESSING}),
    PROCESSING: frozenset({COMPLETED}),
    COMPLETED: frozenset(),
}

PAYMENT_DEFAULT_BODY_TEXT: Dict[str, str] = {
    PROCESSING: "Payment received.",
    COMPLETED: "Payment complete.",
}

# ── Legal forward transitions. ────────────────────────────────────────────────────────────────
#: Keyed on the CURRENT status, valued by the set of statuses it may move to. Meta's rules: an
#: order opens as `pending`, which may move to ANY other status; `processing`, `partially-shipped`
#: and `shipped` may move between one another or to a terminal status; `completed` and `canceled`
#: are terminal. An order with no status recorded yet is treated as `pending` by the caller.
#:
#: `pending` therefore reaches every status. It used to reach only `processing`, so a paid order
#: whose capture-time `processing` update never went out (skipped, failed, or deferred past its
#: retry window) could never be marked shipped or completed: both were refused as out of order.
#:
#: Between the in-fulfilment states this table is deliberately stricter than Meta: forward only.
#: A backward update would tell a customer whose order shipped that it is being prepared again,
#: and the invoice engine sends each status at most once per order (its per-status claim).
#:
#: `canceled` is intentionally NOT a destination from any paid state here: Meta refuses it (2047),
#: and the only legal cancel is on an unpaid order through the invoice cancel path.
_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    PENDING: frozenset({PROCESSING, PARTIALLY_SHIPPED, SHIPPED, COMPLETED, CANCELED}),
    PROCESSING: frozenset({PARTIALLY_SHIPPED, SHIPPED, COMPLETED}),
    PARTIALLY_SHIPPED: frozenset({SHIPPED, COMPLETED}),
    SHIPPED: frozenset({COMPLETED}),
    COMPLETED: frozenset(),
    CANCELED: frozenset(),
}


def normalise(status: str) -> str:
    """The wire spelling for a status, accepting the underscore form (`partially_shipped`).

    Meta's own docs show the hyphenated `partially-shipped` in the message payload and the
    underscore `partially_shipped` in the status-value table, so both are accepted and the
    hyphenated wire form is returned. An unrecognised value is returned lower-cased and stripped
    so the caller's membership check fails it rather than this function guessing.
    """
    value = str(status or "").strip().lower().replace("_", "-")
    return value


def is_valid(status: str) -> bool:
    """True when `status` is a recognised Meta order_status value."""
    return normalise(status) in ALL_STATUSES


def can_transition(current: str, target: str) -> bool:
    """True when moving a physical/service fulfilment order forward is legal.

    This is the broad Meta vocabulary. Payment-only ORDER_DETAILS callers must use
    payment_can_transition() instead.
    """
    cur = normalise(current) or PENDING
    tgt = normalise(target)
    if cur not in _TRANSITIONS or tgt not in ALL_STATUSES:
        return False
    return tgt in _TRANSITIONS[cur]


def payment_can_transition(current: str, target: str) -> bool:
    """True only for the frozen payment-order lifecycle: pending -> processing -> completed."""
    cur = normalise(current) or PENDING
    tgt = normalise(target)
    if cur not in _PAYMENT_ORDER_TRANSITIONS or tgt not in PAYMENT_ORDER_TARGETS:
        return False
    return tgt in _PAYMENT_ORDER_TRANSITIONS[cur]


#: Default customer-facing body text per fulfilment status, used when the caller supplies none.
#: Plain, factual, no marketing — an order_status message is a UTILITY notification.
DEFAULT_BODY_TEXT: Dict[str, str] = {
    PROCESSING: "Your order is being prepared.",
    PARTIALLY_SHIPPED: "Part of your order has shipped.",
    SHIPPED: "Your order has shipped.",
    COMPLETED: "Your order is complete. Thank you!",
    CANCELED: "Your order has been cancelled.",
}


def default_body(status: str) -> str:
    """The default customer-facing line for a physical/service fulfilment status."""
    return DEFAULT_BODY_TEXT.get(normalise(status), "Your order status has been updated.")


def payment_default_body(status: str) -> str:
    """Customer wording for the payment-only WhatsApp order lifecycle."""
    return PAYMENT_DEFAULT_BODY_TEXT.get(normalise(status), "Your payment status has been updated.")



_REFERENCE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,35}$")

#: Meta's hard ceiling for the order's `description`; longer text is rejected. The builders trim
#: to this rather than failing, so a verbose staff note never blocks a fulfilment update.
MAX_DESCRIPTION_LENGTH = 120


def canonical_reference(reference_id: str) -> str:
    """Return an exact Meta-safe order reference without rewriting the commerce identity."""
    ref = str(reference_id or "").strip()
    if not _REFERENCE_RE.fullmatch(ref):
        raise ValueError("invalid Meta order-status reference_id")
    return ref


def canonical_status(status: str) -> str:
    """Return the exact Meta fulfilment status, failing closed on payment/unknown vocabulary."""
    wire = normalise(status)
    if wire not in ALL_STATUSES:
        raise ValueError("invalid order status")
    return wire

def build_template_component(reference_id: str, status: str, description: str = "") -> dict:
    """Build the canonical Meta ORDER_STATUS template component.

    Business semantics live here; the outbound Lambda owns only transport/persistence.
    reference_id is already the canonical commerce reference owned by the payment/order
    core and is never rewritten here. Invalid or blank values fail closed.
    """
    ref = canonical_reference(reference_id)
    wire_status = canonical_status(status)
    text = (str(description or "").strip() or default_body(wire_status))[:MAX_DESCRIPTION_LENGTH]
    return {
        "type": "order_status",
        "parameters": [{
            "type": "order_status",
            "order_status": {
                "reference_id": ref,
                "order": {
                    "status": wire_status,
                    "description": text,
                },
            },
        }],
    }


__all__ = [
    "PENDING", "PROCESSING", "PARTIALLY_SHIPPED", "SHIPPED", "COMPLETED", "CANCELED",
    "ALL_STATUSES", "STAFF_FULFILMENT_TARGETS", "PAYMENT_ORDER_TARGETS",
    "DEFAULT_BODY_TEXT", "PAYMENT_DEFAULT_BODY_TEXT", "MAX_DESCRIPTION_LENGTH",
    "normalise", "is_valid", "can_transition", "payment_can_transition", "default_body",
    "payment_default_body", "canonical_reference", "canonical_status", "build_template_component",
]
