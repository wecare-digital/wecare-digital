"""A payment attempt, which is not an order and must never be mistaken for one.

The distinction this file exists to hold
----------------------------------------
Most payment attempts never become orders, and that is normal rather than exceptional. A customer
opens checkout and abandons it; a UPI mandate times out; a card is declined. Every one of those
leaves a record that has to be visible to the customer and to staff — and none of them may carry
an order number, appear in order history, or produce a receipt.

So the attempt is the *only* entity that exists before money moves, and it deliberately has no
field to put an order number in. `order_keys` holds the order identity separately and only mints it
after a provider readback confirms capture.

Why payment history and order history are different views
---------------------------------------------------------
The temptation is one "orders" list with a status column, because it is one query. It is wrong
here for a specific reason: a failed attempt with a status of `FAILED` still *looks* like an order
to everyone who skims a table, and it invites a support agent to quote a number that means
nothing. Order history contains orders. Payment history contains attempts. A failed attempt says
`Payment failed — no order created` and has nothing that resembles an order number.

Retry lineage
-------------
A genuine retry after a definite failure is a **new** attempt with a **new** reference, linked by
`retryOf`. A retry of the *message delivery* is neither — it reuses the attempt and the reference,
because Meta and Razorpay both key on that reference and a fresh one would produce a second
payable request for one basket.

`attemptNumber` is derived from the chain rather than stored independently, so it cannot disagree
with `retryOf`.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from lambda_utils.identifiers import new_uuid7

logger = logging.getLogger(__name__)

#: The provisioned store for these records, created by
#: `scripts/provision_payment_attempts_table.py`. Indirected through an env var for the same reason
#: `order_keys.commerce_keys_table_name` is, but note this module never reads it itself: every
#: function here takes an injected `table`, so the module holds no AWS client, needs no credential
#: and is fully testable offline. This exists so the handlers that DO need a client all resolve the
#: same name instead of each embedding a literal.
DEFAULT_TABLE_NAME = "stack-wecare-digital-PaymentAttemptsTable"


def table_name() -> str:
    """The payment attempts table. TTL must stay disabled on it.

    A failed attempt is the record proving no order was created, so expiring one destroys the
    evidence that a customer was not charged twice. `provision_payment_attempts_table.py --verify`
    asserts TTL is DISABLED rather than merely leaving it unset.
    """
    return os.environ.get("PAYMENT_ATTEMPTS_TABLE", DEFAULT_TABLE_NAME)

# ── states (section 38) ────────────────────────────────────────────────────────
CREATED = "CREATED"
PAYMENT_READINESS_CHECKED = "PAYMENT_READINESS_CHECKED"
PAYMENT_REQUEST_SENT = "PAYMENT_REQUEST_SENT"
PAYMENT_PENDING = "PAYMENT_PENDING"
PAYMENT_PAID = "PAYMENT_PAID"
PAYMENT_FAILED = "PAYMENT_FAILED"
PAYMENT_CANCELLED = "PAYMENT_CANCELLED"
PAYMENT_EXPIRED = "PAYMENT_EXPIRED"

#: The only state from which an order may be created. A single-element set rather than a
#: comparison, so the rule is greppable and cannot be widened by editing an `or`.
ORDER_ELIGIBLE_STATES = frozenset({PAYMENT_PAID})

#: Definitely over, and safe to retry with a NEW attempt.
RETRYABLE_STATES = frozenset({PAYMENT_FAILED, PAYMENT_CANCELLED, PAYMENT_EXPIRED})

#: Still in flight. A retry here would produce a second payable request for one basket, so the
#: caller must keep verifying the existing attempt instead.
IN_FLIGHT_STATES = frozenset({
    CREATED, PAYMENT_READINESS_CHECKED, PAYMENT_REQUEST_SENT, PAYMENT_PENDING,
})

TERMINAL_STATES = ORDER_ELIGIBLE_STATES | RETRYABLE_STATES

ALL_STATES = IN_FLIGHT_STATES | TERMINAL_STATES

#: Monotonic ranking, so an out-of-order or redelivered provider event cannot move an attempt
#: backwards. Same mechanism as `payment_status`, `wa_status` and `rcs_status`.
#:
#: `PAYMENT_PAID` outranks every failure deliberately: a failed first attempt followed by a
#: successful second on the same attempt id must end paid. The reverse — a late `failed` landing
#: after a capture — is the transition that would tell a paying customer their payment did not
#: work, and it is refused.
_RANK: Dict[str, int] = {
    CREATED: 10,
    PAYMENT_READINESS_CHECKED: 20,
    PAYMENT_REQUEST_SENT: 30,
    PAYMENT_PENDING: 40,
    PAYMENT_EXPIRED: 50,
    PAYMENT_CANCELLED: 55,
    PAYMENT_FAILED: 60,
    PAYMENT_PAID: 100,
}

#: Persisted so the guard is a ConditionExpression rather than a read-then-write race.
RANK_ATTRIBUTE = "attemptRank"


class IllegalTransition(ValueError):
    """The requested state change is not allowed."""


def rank(state: str) -> int:
    """The monotonic rank of a state. Unknown states rank 0 and can overwrite nothing."""
    return _RANK.get(str(state or ""), 0)


def condition_expression() -> str:
    """Refuse any write that would move an attempt backwards."""
    return (f"attribute_not_exists({RANK_ATTRIBUTE}) OR "
            f"{RANK_ATTRIBUTE} <= :rank")


def new_payment_attempt_id() -> str:
    """Internal identifier. UUIDv7, never shown to a customer."""
    return new_uuid7()


def build(*,
          customer_id: str,
          reference_id: str,
          amount_paise: int,
          configuration_name: str,
          currency: str = "INR",
          cart_id: str = "",
          wix_checkout_id: str = "",
          retry_of: str = "",
          customer_uuid: str = "",
          attempt_number: int = 1,
          payment_attempt_id: Optional[str] = None,
          now: Optional[int] = None) -> Dict[str, Any]:
    """Build a payment-attempt record.

    `amount_paise` must be an `int`. Floats are refused rather than coerced: a one-paise
    difference against the authoritative checkout total has to fail the payment closed, and
    `0.1 + 0.2 != 0.3` in binary floating point, so a rounding artefact would refuse a
    legitimate order. Rejecting the type at the boundary is cheaper than finding out later.

    `customer_uuid` is ATTRIBUTION, not money: the public customer id this attempt belongs to,
    read off the contact row by the caller and threaded here so `finalization.accept_paid` can
    copy it onto the order row without a second contacts read on the money path. It is PASSED IN
    and never derived - this module mints nothing public - and it is emitted only when non-empty,
    so an attempt built without one is byte-identical to one built before this parameter existed.
    """
    if not customer_id:
        raise ValueError("customer_id is required")
    if not reference_id:
        raise ValueError("reference_id is required")
    if not configuration_name:
        raise ValueError("configuration_name is required; there is no default")
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
        raise TypeError(
            f"amount_paise must be an int of minor units, got {type(amount_paise).__name__}"
        )
    if amount_paise <= 0:
        raise ValueError("amount_paise must be positive")
    if currency != "INR":
        # Compared explicitly, never inferred from the amount.
        raise ValueError(f"only INR is supported, got {currency!r}")

    moment = int(time.time()) if now is None else int(now)
    record = {
        "paymentAttemptId": payment_attempt_id or new_payment_attempt_id(),
        "customerId": customer_id,
        "referenceId": reference_id,
        "amountPaise": amount_paise,
        "currency": currency,
        "configurationName": configuration_name,
        "provider": "razorpay",
        "status": CREATED,
        RANK_ATTRIBUTE: rank(CREATED),
        "attemptNumber": attempt_number,
        "createdAt": moment,
        "updatedAt": moment,
    }
    for key, value in (("cartId", cart_id), ("wixCheckoutId", wix_checkout_id),
                       ("retryOf", retry_of), ("customerUuid", customer_uuid)):
        if value:
            record[key] = value
    return record


def next_retry(previous: Dict[str, Any], *, reference_id: str,
               amount_paise: int, configuration_name: str,
               wix_checkout_id: str = "",
               now: Optional[int] = None) -> Dict[str, Any]:
    """Build the successor attempt for a definitely-failed one.

    Refuses when the previous attempt is still in flight or already paid. That refusal is the
    point: a retry offered on a pending payment produces a second charge for one basket, and a
    retry offered on a paid one asks a customer to pay twice.

    The amount is a parameter rather than copied from `previous`, because a retry must
    recalculate the authoritative checkout — prices, stock and shipping may all have moved, and
    reusing a stale total is how a customer pays yesterday's price for today's basket.
    """
    state = str(previous.get("status") or "")
    if state not in RETRYABLE_STATES:
        raise IllegalTransition(
            f"cannot retry an attempt in state {state!r}; only "
            f"{sorted(RETRYABLE_STATES)} may be retried"
        )
    if reference_id == previous.get("referenceId"):
        raise ValueError(
            "a genuine retry needs a NEW reference_id; reusing one would make the two "
            "attempts indistinguishable to Meta and Razorpay"
        )

    return build(
        customer_id=str(previous.get("customerId") or ""),
        reference_id=reference_id,
        amount_paise=amount_paise,
        configuration_name=configuration_name,
        cart_id=str(previous.get("cartId") or ""),
        wix_checkout_id=wix_checkout_id,
        retry_of=str(previous.get("paymentAttemptId") or ""),
        # CARRIED, unlike the amount. The amount is recalculated because prices move; the
        # customer does not change between a failed attempt and its retry, and minting a second
        # public id for one customer is exactly what the `if_not_exists` discipline at the write
        # sites exists to prevent.
        customer_uuid=str(previous.get("customerUuid") or ""),
        attempt_number=int(previous.get("attemptNumber") or 1) + 1,
        now=now,
    )


def may_create_order(attempt: Dict[str, Any]) -> bool:
    """Whether this attempt is in the one state that permits order creation."""
    return str(attempt.get("status") or "") in ORDER_ELIGIBLE_STATES


def may_retry(attempt: Dict[str, Any]) -> bool:
    """Whether a retry CTA may be shown. False while in flight and false once paid."""
    return str(attempt.get("status") or "") in RETRYABLE_STATES


def is_in_flight(attempt: Dict[str, Any]) -> bool:
    return str(attempt.get("status") or "") in IN_FLIGHT_STATES


def transition(attempt: Dict[str, Any], to_state: str, *,
               now: Optional[int] = None,
               failure_code: str = "",
               failure_reason: str = "",
               provider_payment_id: str = "",
               provider_order_id: str = "") -> Dict[str, Any]:
    """Return the attempt advanced to `to_state`, or raise `IllegalTransition`.

    Pure: it returns a new dict rather than writing, so the caller performs the conditional write
    with `condition_expression()` and cannot accidentally apply a backward transition locally and
    then persist it.
    """
    if to_state not in ALL_STATES:
        raise IllegalTransition(f"unknown state {to_state!r}")

    current = str(attempt.get("status") or "")
    if rank(to_state) < rank(current):
        raise IllegalTransition(
            f"{current} -> {to_state} moves the attempt backwards and is refused"
        )

    moment = int(time.time()) if now is None else int(now)
    out = dict(attempt)
    out["status"] = to_state
    out[RANK_ATTRIBUTE] = rank(to_state)
    out["updatedAt"] = moment

    if to_state == PAYMENT_PAID:
        out["paidAt"] = moment
    elif to_state in RETRYABLE_STATES:
        out["failedAt"] = moment
        # Codes only, and a reason the caller constructed. A provider error string can echo
        # request content, so it is never passed through verbatim.
        if failure_code:
            out["failureCode"] = failure_code
        if failure_reason:
            out["failureReason"] = failure_reason

    if provider_payment_id:
        out["providerPaymentId"] = provider_payment_id
    if provider_order_id:
        out["providerOrderId"] = provider_order_id
    return out


# ── the customer-facing views (section 51) ─────────────────────────────────────

FAILED_LABEL = "Payment failed \u2014 no order created"


def payment_history_entry(attempt: Dict[str, Any], *,
                          order_number: str = "") -> Dict[str, Any]:
    """One row for the customer's **payment** history.

    A failed, cancelled or expired attempt gets `orderNumber: None` and an explicit label, so a
    reader cannot mistake it for a purchase. `order_number` is only ever populated by the caller
    for an attempt that actually produced an order, and it is dropped here if the state does not
    permit one — belt and braces, because this is the row a customer reads.
    """
    state = str(attempt.get("status") or "")
    settled = state in ORDER_ELIGIBLE_STATES

    entry = {
        "paymentAttemptId": attempt.get("paymentAttemptId"),
        "referenceId": attempt.get("referenceId"),
        "amountPaise": attempt.get("amountPaise"),
        "currency": attempt.get("currency", "INR"),
        "status": state,
        "attemptNumber": attempt.get("attemptNumber", 1),
        "createdAt": attempt.get("createdAt"),
        "retryOf": attempt.get("retryOf"),
        "orderNumber": order_number if (settled and order_number) else None,
        "label": None if settled else FAILED_LABEL if state in RETRYABLE_STATES else None,
        "canRetry": may_retry(attempt),
    }
    if not settled:
        # Defensive: an order number on a non-paid row is the exact confusion this view exists
        # to prevent, so it is stripped even if a caller passed one.
        entry["orderNumber"] = None
    return entry


def order_history_contains(attempt: Dict[str, Any]) -> bool:
    """Whether this attempt belongs in **order** history. Only a paid one does."""
    return may_create_order(attempt)


def filter_order_history(attempts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The attempts that represent real orders. Everything else belongs in payment history."""
    return [a for a in attempts if order_history_contains(a)]


__all__ = [
    "DEFAULT_TABLE_NAME",
    "table_name",
    "CREATED",
    "PAYMENT_READINESS_CHECKED",
    "PAYMENT_REQUEST_SENT",
    "PAYMENT_PENDING",
    "PAYMENT_PAID",
    "PAYMENT_FAILED",
    "PAYMENT_CANCELLED",
    "PAYMENT_EXPIRED",
    "ORDER_ELIGIBLE_STATES",
    "RETRYABLE_STATES",
    "IN_FLIGHT_STATES",
    "TERMINAL_STATES",
    "ALL_STATES",
    "RANK_ATTRIBUTE",
    "FAILED_LABEL",
    "IllegalTransition",
    "rank",
    "condition_expression",
    "new_payment_attempt_id",
    "build",
    "next_retry",
    "transition",
    "may_create_order",
    "may_retry",
    "is_in_flight",
    "payment_history_entry",
    "order_history_contains",
    "filter_order_history",
]
