"""Turning a verified payment into exactly one order. The step the payment path never had.

What this replaces
------------------
Nothing. That is the point. Measured across the tree, the WhatsApp/Razorpay payment path creates
payment records, invoice state, GST invoices and notifications — but **no commerce order**. So this
is a new capability rather than a refactor, and `PaymentsTable`, `InvoicesTable` and `OrderTable`
all held zero rows when it was written, so there is nothing to migrate.

The ordered pipeline, and why the order is the design
-----------------------------------------------------
1. **Verify with the provider.** A webhook is a trigger, never proof. `razorpay-webhook` currently
   trusts the webhook body on `payment.captured`; the correct pattern already exists in
   `secure-files._confirm_with_razorpay` + `razorpay_orders.order_is_paid`, whose docstring records
   *why*: the webhook signing secret is in this repository's public git history, so a valid
   signature proves only that someone read the history. Razorpay's own API is the only thing that
   can say money moved.
2. **Compare currency, then amount, then customer.** Currency first because it is a single
   equality and a mismatch makes the amount comparison meaningless. Integer paise throughout — a
   one-paise difference fails closed, and `0.1 + 0.2 != 0.3` in binary floating point, so a float
   anywhere here would refuse legitimate orders.
3. **Claim the right to create.** `PROVIDERPAYMENT#<txn>` before `PAYMENTATTEMPT#<id>`, both
   conditional. This is what makes a duplicate webhook, a concurrent worker and a staff retry
   converge on one order.
4. **Reserve the public order number** — only the claim winner does, so a loser never burns one.
5. **Record it on the claim**, so a crash between 4 and 5 is recoverable on re-entry.

Steps 3-5 live in `order_keys`. This module is the ordering and the comparisons.

What it deliberately does not do
--------------------------------
It does not write the order record, finalize the payment attempt, generate the receipt or send the
confirmation. Those are separate, individually guarded side effects, and folding them in here would
mean a failure in the fifth one re-runs the first. This function's single job is: *may an order
exist, and if so under which identifiers*. Everything downstream keys off the claim it returns and
can be retried independently.

Failure after capture is never the customer's problem
-----------------------------------------------------
Once Razorpay says captured, the money is ours and the order must not be lost. Every failure past
that point returns a recoverable outcome rather than raising past the caller, and none of them may
produce a message telling the customer to pay again.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from lambda_utils.ecommerce import order_keys, payment_attempt
from lambda_utils.ecommerce.money import positive_paise

logger = logging.getLogger(__name__)

# ── outcomes ───────────────────────────────────────────────────────────────────
ORDER_CREATED = "ORDER_CREATED"
ORDER_ALREADY_EXISTS = "ORDER_ALREADY_EXISTS"
NOT_PAID = "NOT_PAID"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
ATTEMPT_NOT_PAYABLE = "ATTEMPT_NOT_PAYABLE"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
PROVIDER_PAYMENT_CONFLICT = "PROVIDER_PAYMENT_CONFLICT"

# ── webhook-caller outcomes ──────────────────────────────────────────────────────
# These are not produced by reconcile_payment itself; they are emitted by the
# razorpay-webhook wrapper (_create_order_for_captured_payment) so the callback can
# reason about a capture that never reached reconciliation. Named here so the vocabulary
# stays in one place and the handler does not invent ad-hoc strings.
NO_PROVIDER_ID = "NO_PROVIDER_ID"
RECONCILIATION_ERROR = "RECONCILIATION_ERROR"

#: A capture the callback could neither confirm as a commerce order nor prove is a genuine
#: legacy invoice, or one whose storage/verification failed. It is parked for a human: no
#: invoice is marked paid, no receipt runs, no confirmation is sent, and nothing is
#: double-written. Money may or may not have moved, so the customer is never told to pay again.
NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"

#: Outcomes where the money did NOT move, so nothing was created and nothing is owed.
NO_ORDER_OUTCOMES = frozenset({
    NOT_PAID, UNKNOWN_REFERENCE, ATTEMPT_NOT_PAYABLE, PROVIDER_UNAVAILABLE,
})

#: Outcomes where the money DID move but we refused to proceed. These are the ones that must
#: reach a human: the customer has paid and has no order, which is recoverable only by staff.
#: Separated from the set above because the operational response is completely different.
PAID_BUT_BLOCKED_OUTCOMES = frozenset({
    AMOUNT_MISMATCH, CURRENCY_MISMATCH, CUSTOMER_MISMATCH, IDENTITY_UNAVAILABLE,
    PROVIDER_PAYMENT_CONFLICT,
})


class ReconciliationOutcome:
    """The verdict, plus the identifiers when an order exists."""

    __slots__ = ("outcome", "reason", "order_id", "order_number",
                 "payment_attempt_id", "provider_payment_id", "verified_captured_paise")

    def __init__(self, outcome: str, reason: str = "", *,
                 order_id: str = "", order_number: str = "",
                 payment_attempt_id: str = "",
                 provider_payment_id: str = "",
                 verified_captured_paise: int = 0) -> None:
        self.outcome = outcome
        self.reason = reason
        self.order_id = order_id
        self.order_number = order_number
        self.payment_attempt_id = payment_attempt_id
        self.provider_payment_id = provider_payment_id
        self.verified_captured_paise = int(verified_captured_paise or 0)

    @property
    def has_order(self) -> bool:
        """True when an order exists — whether this call created it or found it."""
        return self.outcome in (ORDER_CREATED, ORDER_ALREADY_EXISTS)

    @property
    def needs_human(self) -> bool:
        """True when money moved but no order followed. The alarm condition."""
        return self.outcome in PAID_BUT_BLOCKED_OUTCOMES

    @property
    def customer_may_retry(self) -> bool:
        """Whether it is safe to offer the customer another payment attempt.

        False for every paid-but-blocked outcome. The money is already taken, so a retry CTA
        there would charge twice — and false for `PROVIDER_UNAVAILABLE` too, because an
        unreachable provider means we do not know whether it was taken.
        """
        # This verifier reports only captured/not captured. Not captured includes
        # authorized and pending, so it cannot establish a definitive failure.
        return False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "hasOrder": self.has_order,
            "needsHuman": self.needs_human,
            "orderId": self.order_id or None,
            "orderNumber": self.order_number or None,
            "paymentAttemptId": self.payment_attempt_id or None,
            "verifiedCapturedPaise": self.verified_captured_paise or None,
        }

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"ReconciliationOutcome({self.outcome})"


def _blocked(outcome: str, reason: str, **detail: Any) -> ReconciliationOutcome:
    level = logger.error if outcome in PAID_BUT_BLOCKED_OUTCOMES else logger.warning
    level('{"event":"reconciliation_blocked","outcome":"%s","reason":"%s"}',
          outcome, reason)
    return ReconciliationOutcome(outcome, reason, **detail)


def reconcile_payment(*,
                      table: Any,
                      reference_id: str,
                      verify_payment: Callable[[str], Tuple[bool, str, int, str]],
                      load_attempt: Callable[[str], Optional[Dict[str, Any]]],
                      expected_customer_id: str = "",
                      key_attr: str = "orderId") -> ReconciliationOutcome:
    """Create at most one order for a payment, or explain why not. Idempotent.

    `verify_payment(reference_id)` must ask the **provider** — not a webhook body — and return
    `(paid, provider_payment_id, amount_paise, currency)`. Injected so this module holds no
    Razorpay client and reads no credential, and so the tests can drive every branch without
    network access.

    `load_attempt(reference_id)` resolves the stored payment attempt. Returning None means no
    attempt exists for this reference, and the correct response is to refuse: a payment event
    naming an unknown reference is either a forgery or a lost write, and inventing an order from
    it is how a forged webhook becomes a free order.

    `expected_customer_id`, when supplied, must match the attempt's owner. Optional because the
    provider does not always tell us who paid; when it is known, it is checked.
    """
    if not reference_id:
        return _blocked(UNKNOWN_REFERENCE, "no reference_id on the event")

    # ── resolve the attempt first: cheapest check, and it bounds everything after it ──
    try:
        attempt = load_attempt(reference_id)
    except Exception as error:  # noqa: BLE001
        return _blocked(PROVIDER_UNAVAILABLE,
                        f"could not load the payment attempt: {type(error).__name__}")

    if not attempt:
        return _blocked(
            UNKNOWN_REFERENCE,
            "no payment attempt exists for this reference; refusing to create an order from "
            "a payment event alone",
        )

    attempt_id = str(attempt.get("paymentAttemptId") or "")
    if not attempt_id:
        return _blocked(UNKNOWN_REFERENCE, "the stored attempt carries no id")

    # Authorization precedes the idempotent shortcut: an existing order does not
    # give a different customer permission to read it.
    if expected_customer_id and str(attempt.get("customerId") or "") != expected_customer_id:
        return _blocked(CUSTOMER_MISMATCH, "the attempt belongs to another customer")

    # ── has this already produced an order? Answered BEFORE contacting the provider ──
    #
    # Deliberate: a redelivered webhook is the common case, and a provider round trip per
    # redelivery is both slow and a way to get rate limited during exactly the incident that
    # caused the redeliveries.
    try:
        existing = order_keys.resolve_order_for_payment(
            table, attempt_id, key_attr=key_attr)
    except order_keys.OrderIdentityUnavailable as error:
        return _blocked(IDENTITY_UNAVAILABLE, str(error),
                        payment_attempt_id=attempt_id)

    if existing and existing.get("orderIdRef"):
        order_number = str(existing.get("orderNumber") or "")
        if order_number:
            logger.info('{"event":"reconciliation_idempotent_hit"}')
            return ReconciliationOutcome(
                ORDER_ALREADY_EXISTS, "an order already exists for this payment attempt",
                order_id=str(existing["orderIdRef"]), order_number=order_number,
                payment_attempt_id=attempt_id,
                provider_payment_id=str(existing.get("providerTransactionId") or ""),
            )
        # Claimed but unnumbered: a previous run died between claiming and reserving. Finish it
        # rather than starting again — the order id is already committed.
        return _finish_numbering(
            table, attempt_id=attempt_id,
            order_id=str(existing["orderIdRef"]), key_attr=key_attr,
            provider_payment_id=str(existing.get("providerTransactionId") or ""),
        )

    # ── ask the provider. This is the only thing that may assert the money moved ──
    try:
        paid, provider_payment_id, provider_amount, provider_currency = verify_payment(
            reference_id)
    except Exception as error:  # noqa: BLE001
        # Availability traded for integrity, the same way `_confirm_with_razorpay` does it. An
        # unreachable provider means we do not know, and "do not know" must not create an order.
        # Recoverable: the sweep re-runs this path.
        return _blocked(PROVIDER_UNAVAILABLE,
                        f"could not verify with the provider: {type(error).__name__}",
                        payment_attempt_id=attempt_id)

    if not paid:
        # Not paid yet, or a forged event. Indistinguishable here, and it does not matter:
        # both mean no order.
        return _blocked(NOT_PAID, "the provider reports no captured payment",
                        payment_attempt_id=attempt_id)

    # Everything past this point: THE MONEY IS OURS. No outcome below may tell the customer to
    # pay again, and every refusal has to reach a human.

    # Currency before amount. A single equality, and a mismatch makes comparing the numbers
    # meaningless rather than merely wrong.
    expected_currency = str(attempt.get("currency") or "")
    if expected_currency != "INR" or str(provider_currency or "") != expected_currency:
        return _blocked(CURRENCY_MISMATCH,
                        "the captured currency does not match the attempt",
                        payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)

    try:
        # A redeemed gift card funds part of the FULL order total, so the amount Razorpay
        # is expected to capture can be smaller than amountPaise. Old attempts have no split field
        # and intentionally fall back to the full amount.
        expected_amount = positive_paise(
            attempt.get("razorpayChargedPaise") or attempt.get("amountPaise"))
        provider_amount = positive_paise(provider_amount)
    except ValueError:
        return _blocked(AMOUNT_MISMATCH,
                        "the stored amount is not integer paise and cannot be compared exactly",
                        payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)
    if provider_amount != expected_amount:
        # Exact equality, both sides integers. One paise is a mismatch.
        return _blocked(AMOUNT_MISMATCH,
                        "the captured amount does not equal the authoritative total",
                        payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)

    if not payment_attempt.may_create_order(
            {**attempt, "status": payment_attempt.PAYMENT_PAID}):
        # Defensive: `may_create_order` is the single place that decides, so this cannot drift
        # from `ORDER_ELIGIBLE_STATES` even if that set changes.
        return _blocked(ATTEMPT_NOT_PAYABLE,
                        "a verified capture did not satisfy the order-eligibility rule",
                        payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)

    if not isinstance(provider_payment_id, str) or not provider_payment_id:
        return _blocked(PROVIDER_PAYMENT_CONFLICT, "verified payment has no provider id",
                        payment_attempt_id=attempt_id)

    # ── claim, then number. Only the winner numbers, so a loser burns nothing ──
    order_id = order_keys.new_order_id()
    try:
        claimed_id, won = order_keys.claim_order_for_payment(
            table, payment_attempt_id=attempt_id, order_id=order_id,
            provider_transaction_id=provider_payment_id, key_attr=key_attr,
            extra={"referenceId": reference_id},
        )
    except order_keys.OrderIdentityUnavailable as error:
        return _blocked(IDENTITY_UNAVAILABLE, str(error),
                        payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)

    if not won:
        # A concurrent worker, an earlier delivery, or a different attempt funded by the same
        # provider payment got there first. Adopt its order.
        #
        # Resolved by BOTH keys, and the provider one first. If the losing claim was the
        # PROVIDERPAYMENT# row, the order belongs to whichever attempt won — not to this one —
        # so looking it up by our own attempt id returns nothing, and treating that as "needs
        # numbering" would reserve a second order number for an order that already has one.
        adopted = (
            order_keys.resolve_order_for_provider_payment(
                table, provider_payment_id, key_attr=key_attr)
            or order_keys.resolve_order_for_payment(
                table, attempt_id, key_attr=key_attr)
            or {}
        )
        if adopted.get("paymentAttemptId") != attempt_id:
            return _blocked(PROVIDER_PAYMENT_CONFLICT,
                            "provider payment is already bound to another attempt",
                            payment_attempt_id=attempt_id,
                            provider_payment_id=provider_payment_id)
        number = str(adopted.get("orderNumber") or "")
        if number:
            return ReconciliationOutcome(
                ORDER_ALREADY_EXISTS, "another worker created the order first",
                order_id=claimed_id, order_number=number,
                payment_attempt_id=attempt_id,
                provider_payment_id=provider_payment_id,
                verified_captured_paise=provider_amount,
            )
        # Claimed by someone who has not numbered it yet. Finish the job rather than racing:
        # the order id is committed either way.
        return _finish_numbering(table, attempt_id=attempt_id, order_id=claimed_id,
                                key_attr=key_attr,
                                provider_payment_id=provider_payment_id)

    outcome = _finish_numbering(table, attempt_id=attempt_id, order_id=claimed_id,
                                key_attr=key_attr,
                                provider_payment_id=provider_payment_id)
    if outcome.has_order:
        logger.info(
            '{"event":"order_created","paymentAttemptId":"%s","orderNumber":"%s"}',
            attempt_id, outcome.order_number,
        )
        return ReconciliationOutcome(
            ORDER_CREATED, "verified capture produced exactly one order",
            order_id=outcome.order_id, order_number=outcome.order_number,
            payment_attempt_id=attempt_id, provider_payment_id=provider_payment_id,
            verified_captured_paise=provider_amount,
        )
    return outcome


def _finish_numbering(table: Any, *, attempt_id: str, order_id: str,
                      key_attr: str,
                      provider_payment_id: str = "") -> ReconciliationOutcome:
    """Reserve and record the public order number for an already-claimed order.

    Separate so the crash-recovery path and the first-run path use identical code. The order id is
    already committed by the claim, so this is safe to re-enter: it reserves a *new* number only
    when none was recorded, and the abandoned one stays reserved and unused — burning a number is
    invisible, reissuing one is not.
    """
    try:
        number = order_keys.reserve_public_order_number(
            table, order_id=order_id, key_attr=key_attr,
            extra={"paymentAttemptId": attempt_id},
        )
        number = order_keys.record_order_number_on_claim(
            table, payment_attempt_id=attempt_id, order_number=number,
            key_attr=key_attr,
        )
    except order_keys.OrderIdentityUnavailable as error:
        # Money is ours, the claim exists, the number is not issued. Recoverable on re-entry and
        # it must reach a human, because the customer has paid and has no order number yet.
        return _blocked(IDENTITY_UNAVAILABLE, str(error),
                        order_id=order_id, payment_attempt_id=attempt_id,
                        provider_payment_id=provider_payment_id)

    return ReconciliationOutcome(
        ORDER_CREATED, "order identity reserved",
        order_id=order_id, order_number=number,
        payment_attempt_id=attempt_id, provider_payment_id=provider_payment_id,
    )


__all__ = [
    "ORDER_CREATED",
    "ORDER_ALREADY_EXISTS",
    "NOT_PAID",
    "AMOUNT_MISMATCH",
    "CURRENCY_MISMATCH",
    "CUSTOMER_MISMATCH",
    "UNKNOWN_REFERENCE",
    "ATTEMPT_NOT_PAYABLE",
    "PROVIDER_UNAVAILABLE",
    "IDENTITY_UNAVAILABLE",
    "PROVIDER_PAYMENT_CONFLICT",
    "NO_PROVIDER_ID",
    "RECONCILIATION_ERROR",
    "NEEDS_RECONCILIATION",
    "NO_ORDER_OUTCOMES",
    "PAID_BUT_BLOCKED_OUTCOMES",
    "ReconciliationOutcome",
    "reconcile_payment",
]
