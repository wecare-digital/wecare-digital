"""Section 2 coupon + gift-card redemption authority, built-but-gated.

What this module is, and why it is NOT the gateway path
-------------------------------------------------------
Section 2 of the owner's specification adds a coupon field and a gift-card field to the website
checkout. Both must be SERVER/Wix-authoritative in integer paise: the browser value is only a
request, a browser-calculated discount is never trusted, and the browser never controls the
trusted amount. This module is the server authority for both. It is written handler-free - every
external dependency (the keys table, the coupon/gift-card provider readback) is injected - so it
is fully testable offline with the same ``FakeDynamo`` the other payment tests use, and it holds
NO vendor-specific code: the provider is an abstract seam (see ``RedemptionProvider``) so the
concrete binding (Wix Headless coupons / Wix gift cards OR a third-party system) can be chosen
later without touching the money arithmetic or the gate.

The two primitives, and where each applies relative to the fee/GST calculator
-----------------------------------------------------------------------------
A COUPON and a GIFT CARD are different kinds of thing and apply at different points of the
section 7 ``checkout_pricing`` calculator (convenience fee + GST-on-fee), which is deliberate:

  * A COUPON is a PRICE CHANGE. It reduces the authoritative *collection* total that FEEDS the
    calculator, so the convenience fee and its GST are computed on the DISCOUNTED collection - a
    smaller cart genuinely costs a smaller fee. ``apply_coupon`` returns the authoritative
    discounted collection paise; the caller passes THAT into ``checkout_pricing.compute_quote``.
    The discount itself is decided by the provider (Wix), never by the browser.

  * A GIFT CARD is TENDER, not a price change. It does not make the cart cheaper; it pays for part
    (or all) of the already-computed total. So a gift-card redemption is subtracted from the FINAL
    payable AFTER the calculator has run:

        authoritativeTotalPaise - verifiedRedemptionPaise = razorpayPayablePaise

    where ``authoritativeTotalPaise`` is the calculator's ``total_payable_paise`` (collection +
    fee + GST, after any coupon) and ``razorpayPayablePaise`` is what Standard Checkout collects.
    Every value is integer paise; a redemption is capped at the total (you cannot redeem more than
    is owed) and at the card's verified balance.

The split against cart_v2's blanket rejection
---------------------------------------------
``cart_v2.CartV2.calculate`` still RAISES ``CartContractError`` on any ``paymentSummary.giftCards``
/ split / deferred payment and still requires ``payNow == totalAfterGiftCards == total``. That
protection is RETAINED unchanged: the standalone cart contract keeps rejecting an UNVERIFIED
gift-card payment that Wix's own ``paymentSummary`` reports, because the cart boundary has no way
to verify it. The secure replacement does NOT weaken that contract - it computes the authoritative
Wix total through the retained cart path, and only THEN, server-side and after an authoritative
provider balance readback, subtracts a VERIFIED redemption to compute the Razorpay payable. Wix
never collects a gift card for us; our server does the verified subtraction. The two never
disagree because they answer different questions: cart_v2 rejects a gift card the cart tried to
self-apply; this module applies a gift card the SERVER verified.

Reservation, rollback, concurrency and reconciliation
-----------------------------------------------------
A verified redemption is an ATOMIC reservation (``order_keys.reserve_gift_card_redemption``) keyed
by (card fingerprint + payment attempt), so two rapid clicks or two concurrent prepare calls
cannot double-spend one balance - exactly one wins and the loser reads back the winner's figures.
A cross-attempt guard (``gift_card_is_reserved_elsewhere``) stops one card funding two different
live attempts. A failed Razorpay payment after the reservation, a shopper removing the card, or an
abandoned attempt RELEASES the reservation (``release_gift_card_redemption``) so the balance is not
stranded. A captured payment (or a zero-remaining verified order) COMMITS the redemption exactly
once via a payment-id-keyed claim (``claim_gift_card_commit`` + ``mark_gift_card_committed``). A
refund releases the committed redemption back. All of this lives in ``order_keys`` under the
``GIFTCARD#`` / ``GIFTCARDCOMMIT#`` namespaces and is reused here, never reinvented.

The gate, identical to website checkout
---------------------------------------
Nothing here creates a gateway order. The REDUCED Razorpay payable after a redemption, AND a
zero-remaining (fully gift-card-covered) order, both settle through the SAME governed
``website_checkout`` path behind authenticated ownership, authoritative pricing, idempotency and
live payment readiness. This module computes the authoritative payable; the gate decides whether a gateway
order is ever created. A zero-remaining order is still gated and still settles through the
authoritative verification path - it never auto-completes from browser state. ``build_payable``
makes the zero-remaining case explicit and refuses to pretend a zero total is a captured payment.

No third-party provider name
----------------------------
The provider seam is abstract and NO vendor name ('Gift Up'/'GiftUp'/etc.) appears here or in any
customer-facing surface. The seam returns provider-agnostic, server-authoritative results and
typed reasons only.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, Tuple

from lambda_utils.ecommerce import order_keys

logger = logging.getLogger(__name__)

#: The only currency redemptions are taken in, matching the rest of the checkout core.
REDEMPTION_CURRENCY = "INR"

#: The upper bound money.py enforces (2**53 - 1), reused so overflow is rejected identically.
_MAX_PAISE = 9007199254740991


# ── typed reasons (the stable UI contract) ─────────────────────────────────────────
#: A coupon/gift-card operation outcome the browser can branch on. These are the ONLY reason
#: strings surfaced; none of them names a provider. A new reason is an additive change here.
COUPON_APPLIED = "APPLIED"
COUPON_INVALID = "INVALID"
COUPON_EXPIRED = "EXPIRED"
COUPON_INELIGIBLE = "INELIGIBLE"

GIFT_CARD_APPLIED = "APPLIED"
GIFT_CARD_INVALID = "INVALID"
GIFT_CARD_EXPIRED = "EXPIRED"
GIFT_CARD_INELIGIBLE = "INELIGIBLE"
GIFT_CARD_INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
GIFT_CARD_DUPLICATE = "DUPLICATE"
GIFT_CARD_CONCURRENT = "CONCURRENT"
GIFT_CARD_UNAVAILABLE = "UNAVAILABLE"


class RedemptionError(ValueError):
    """A redemption could not be computed from the given inputs.

    A subclass of ValueError so existing callers that catch ValueError keep working, but a
    distinct type so the redemption path can be told apart from an unrelated bad argument. Carries
    a stable ``reason`` code; never a provider/body string.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── the abstract provider seam ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class CouponAuthority:
    """What a provider says about a coupon, in integer paise, server-authoritative.

    ``discount_paise`` is the authoritative discount the provider computed for THIS cart; it is
    never read from the browser. ``valid`` with a non-``APPLIED`` reason is how a provider reports
    an invalid/expired/ineligible coupon. A valid coupon has ``reason == APPLIED`` and a
    non-negative ``discount_paise`` no larger than the collection it applies to (checked here).
    """

    valid: bool
    reason: str
    discount_paise: int = 0


@dataclass(frozen=True)
class GiftCardAuthority:
    """What a provider says about a gift card, in integer paise, server-authoritative.

    ``balance_paise`` is the card's authoritative remaining balance; it is never read from the
    browser. ``usable`` with a non-``APPLIED`` reason reports an invalid/expired/ineligible card.
    A usable card has ``reason == APPLIED`` and a non-negative balance; a zero balance usable card
    is reported as ``INSUFFICIENT_BALANCE`` by this module rather than redeemed for nothing.
    """

    usable: bool
    reason: str
    balance_paise: int = 0


class RedemptionProvider(Protocol):
    """The abstract coupon/gift-card authority. Bound to a concrete provider later.

    Deliberately provider-agnostic: a Wix Headless implementation would call Wix's coupons /
    gift-cards REST APIs; a third-party implementation would call that system. Either returns the
    SAME ``CouponAuthority`` / ``GiftCardAuthority`` shapes in integer paise, so the money
    arithmetic, the gate and the UI never learn which vendor is behind the seam.

    Concrete binding, recorded for the live wiring (see docs/execution runbook): a Wix coupons
    binding resolves a coupon ``code`` against the cart/checkout and reads the applied discount
    amount; a Wix gift-cards binding resolves a card ``code``/``number`` to its remaining balance
    and currency. Both convert the provider's decimal amounts to integer paise via ``money.py``
    (never float) at the boundary, exactly as ``cart_v2`` already converts Wix amounts.
    """

    def validate_coupon(self, *, code: str, collection_before_discount_paise: int,
                        cart_ref: str) -> CouponAuthority:
        ...

    def read_gift_card(self, *, code: str, cart_ref: str) -> GiftCardAuthority:
        ...


# ── coupon: a PRICE CHANGE that feeds the calculator ────────────────────────────────
@dataclass(frozen=True)
class CouponResult:
    """The server-authoritative result of applying a coupon. Immutable.

    ``discounted_collection_paise`` is the collection that FEEDS ``checkout_pricing.compute_quote``
    after the coupon - the fee and GST are computed on it, so a coupon genuinely reduces the fee.
    """

    reason: str
    discount_paise: int
    collection_before_discount_paise: int
    discounted_collection_paise: int

    @property
    def applied(self) -> bool:
        return self.reason == COUPON_APPLIED


def _validate_paise(value: Any, name: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise RedemptionError("INVALID")
    if value < 0 or (value == 0 and not allow_zero):
        raise RedemptionError("INVALID")
    if value > _MAX_PAISE:
        raise RedemptionError("INVALID")
    return value


def apply_coupon(*,
                 code: str,
                 collection_before_discount_paise: int,
                 cart_ref: str,
                 provider: RedemptionProvider,
                 currency: str = REDEMPTION_CURRENCY) -> CouponResult:
    """Apply a coupon SERVER-authoritatively and return the discounted collection in integer paise.

    The browser value is ONLY a request: the code is sent to the provider, which decides whether it
    is valid/expired/ineligible and, if valid, what the discount is. A browser-calculated discount
    is never trusted - this function ignores any client-supplied amount and uses only the provider's
    authoritative ``discount_paise``.

    Returns a ``CouponResult`` whose ``reason`` is one of ``APPLIED`` / ``INVALID`` / ``EXPIRED`` /
    ``INELIGIBLE``. On a non-applied reason the discount is zero and the discounted collection
    equals the original collection, so the caller feeds the UNCHANGED collection to the calculator.
    A provider discount that exceeds the collection is clamped to the collection (a coupon cannot
    make a cart cost less than zero), and a negative/garbage provider amount is treated as INVALID.
    """
    if currency != REDEMPTION_CURRENCY:
        raise RedemptionError("UNSUPPORTED_CURRENCY")
    collection = _validate_paise(collection_before_discount_paise,
                                 "collection_before_discount_paise")
    if not code or not isinstance(code, str):
        return CouponResult(reason=COUPON_INVALID, discount_paise=0,
                            collection_before_discount_paise=collection,
                            discounted_collection_paise=collection)

    authority = provider.validate_coupon(
        code=code, collection_before_discount_paise=collection, cart_ref=cart_ref)
    if not authority.valid or authority.reason != COUPON_APPLIED:
        # A provider-reported invalid/expired/ineligible coupon. No discount; collection unchanged.
        reason = authority.reason if authority.reason in (
            COUPON_INVALID, COUPON_EXPIRED, COUPON_INELIGIBLE) else COUPON_INVALID
        return CouponResult(reason=reason, discount_paise=0,
                            collection_before_discount_paise=collection,
                            discounted_collection_paise=collection)

    # The discount is the PROVIDER's authoritative figure, never the browser's. A garbage amount is
    # treated as an invalid coupon rather than trusted.
    discount = authority.discount_paise
    if isinstance(discount, bool) or type(discount) is not int or discount < 0:
        return CouponResult(reason=COUPON_INVALID, discount_paise=0,
                            collection_before_discount_paise=collection,
                            discounted_collection_paise=collection)
    # A coupon cannot make the cart cost less than zero.
    discount = min(discount, collection)
    return CouponResult(reason=COUPON_APPLIED, discount_paise=discount,
                        collection_before_discount_paise=collection,
                        discounted_collection_paise=collection - discount)


# ── gift card: TENDER subtracted from the final payable ─────────────────────────────
@dataclass(frozen=True)
class GiftCardResult:
    """The server-authoritative result of verifying a gift card against a total. Immutable.

    ``redemption_paise`` is the verified amount the card will tender (min of balance and total);
    ``razorpay_payable_paise`` is ``authoritative_total_paise - redemption_paise`` and MAY be zero
    (a fully gift-card-covered order). ``balance_paise`` is the card's authoritative balance. The
    identity ``redemption_paise + razorpay_payable_paise == authoritative_total_paise`` always
    holds exactly, re-checked in ``__post_init__``.
    """

    reason: str
    authoritative_total_paise: int
    redemption_paise: int
    razorpay_payable_paise: int
    balance_paise: int = 0

    def __post_init__(self):
        if self.applied:
            if self.redemption_paise + self.razorpay_payable_paise != self.authoritative_total_paise:
                raise RedemptionError("INVALID")

    @property
    def applied(self) -> bool:
        return self.reason == GIFT_CARD_APPLIED

    @property
    def fully_covered(self) -> bool:
        """True when the gift card covers the whole total and nothing is left for Razorpay."""
        return self.applied and self.razorpay_payable_paise == 0


def verify_gift_card(*,
                     code: str,
                     authoritative_total_paise: int,
                     cart_ref: str,
                     provider: RedemptionProvider,
                     currency: str = REDEMPTION_CURRENCY) -> GiftCardResult:
    """Verify a gift card SERVER-authoritatively and compute the reduced Razorpay payable.

    The browser value is ONLY a request: the code is sent to the provider, which decides whether it
    is valid/expired/ineligible and reports its AUTHORITATIVE balance. The browser never controls
    the trusted amount - the redemption is ``min(balance, total)`` in integer paise, computed here.

    ``authoritative_total_paise`` is the calculator's ``total_payable_paise`` (collection + fee +
    GST, after any coupon). Returns a ``GiftCardResult`` whose ``reason`` is one of ``APPLIED`` /
    ``INVALID`` / ``EXPIRED`` / ``INELIGIBLE`` / ``INSUFFICIENT_BALANCE``:

      * partial redemption: balance < total -> redeem the balance, Razorpay collects the rest;
      * full redemption: balance >= total -> redeem the total, Razorpay payable is ZERO (still
        gated; see ``build_payable``);
      * invalid / expired / ineligible: the provider says so, no redemption;
      * insufficient balance: a usable card with a ZERO balance has nothing to tender.

    This computes the amount only; it does NOT reserve. ``reserve_redemption`` takes the atomic,
    double-spend-safe reservation keyed to an attempt.
    """
    if currency != REDEMPTION_CURRENCY:
        raise RedemptionError("UNSUPPORTED_CURRENCY")
    total = _validate_paise(authoritative_total_paise, "authoritative_total_paise",
                            allow_zero=False)
    if not code or not isinstance(code, str):
        return GiftCardResult(reason=GIFT_CARD_INVALID, authoritative_total_paise=total,
                              redemption_paise=0, razorpay_payable_paise=total)

    authority = provider.read_gift_card(code=code, cart_ref=cart_ref)
    if not authority.usable or authority.reason != GIFT_CARD_APPLIED:
        reason = authority.reason if authority.reason in (
            GIFT_CARD_INVALID, GIFT_CARD_EXPIRED, GIFT_CARD_INELIGIBLE,
            GIFT_CARD_INSUFFICIENT_BALANCE) else GIFT_CARD_INVALID
        return GiftCardResult(reason=reason, authoritative_total_paise=total,
                              redemption_paise=0, razorpay_payable_paise=total,
                              balance_paise=max(0, int(authority.balance_paise or 0)))

    balance = authority.balance_paise
    if isinstance(balance, bool) or type(balance) is not int or balance < 0:
        # A garbage balance is treated as an invalid card rather than trusted.
        return GiftCardResult(reason=GIFT_CARD_INVALID, authoritative_total_paise=total,
                              redemption_paise=0, razorpay_payable_paise=total)
    if balance == 0:
        # A usable card with no balance has nothing to tender.
        return GiftCardResult(reason=GIFT_CARD_INSUFFICIENT_BALANCE,
                              authoritative_total_paise=total,
                              redemption_paise=0, razorpay_payable_paise=total, balance_paise=0)

    # The redemption is the lesser of the card balance and the total - you cannot redeem more than
    # is owed, and you cannot redeem more than the card holds. Integer paise throughout.
    redemption = min(balance, total)
    return GiftCardResult(reason=GIFT_CARD_APPLIED, authoritative_total_paise=total,
                          redemption_paise=redemption,
                          razorpay_payable_paise=total - redemption, balance_paise=balance)


# ── the reduced/zero payable, still gated ───────────────────────────────────────────
@dataclass(frozen=True)
class RedeemedPayable:
    """The authoritative amount Razorpay should collect after a verified redemption. Immutable.

    ``razorpay_payable_paise`` is what Standard Checkout collects; it MAY be zero. ``requires_gateway``
    is True only for a strictly positive payable - a zero-remaining order creates NO gateway order
    but still settles through the authoritative verification path (never auto-complete from the
    browser). This mirrors ``checkout_pricing.CheckoutQuote.is_payable``: a zero amount must never
    reach the gateway, and a zero-remaining fully-gift-card-covered order is NOT a captured payment.
    """

    razorpay_payable_paise: int
    redemption_paise: int
    authoritative_total_paise: int

    def __post_init__(self):
        for name, v in (("razorpay_payable_paise", self.razorpay_payable_paise),
                        ("redemption_paise", self.redemption_paise),
                        ("authoritative_total_paise", self.authoritative_total_paise)):
            if isinstance(v, bool) or type(v) is not int or not 0 <= v <= _MAX_PAISE:
                raise RedemptionError("INVALID")
        if self.redemption_paise + self.razorpay_payable_paise != self.authoritative_total_paise:
            raise RedemptionError("INVALID")

    @property
    def requires_gateway(self) -> bool:
        """True only when there is a strictly positive amount to charge via Razorpay."""
        return self.razorpay_payable_paise > 0

    @property
    def fully_covered(self) -> bool:
        """True when the gift card covered the whole total (zero remaining)."""
        return self.razorpay_payable_paise == 0 and self.redemption_paise > 0


def build_payable(result: GiftCardResult) -> RedeemedPayable:
    """Turn a verified gift-card result into the authoritative payable the gated flow consumes.

    Refuses a non-applied result: only a verified redemption yields a payable. The returned
    ``RedeemedPayable`` reconciles exactly and makes the zero-remaining case explicit so the caller
    gates it (no gateway order) yet still settles it through the authoritative verification path.
    """
    if not result.applied:
        raise RedemptionError(result.reason)
    return RedeemedPayable(
        razorpay_payable_paise=result.razorpay_payable_paise,
        redemption_paise=result.redemption_paise,
        authoritative_total_paise=result.authoritative_total_paise,
    )


# ── fingerprint, reservation, rollback, commit, refund (reuse order_keys) ───────────
def card_fingerprint(code: str) -> str:
    """A stable, non-reversible fingerprint of a gift-card code for keying a reservation.

    The raw code is a bearer secret and must never be a storage key. A SHA-256 of the code gives a
    stable key that cannot be reversed to the code, so two clicks of the SAME card collide on the
    SAME reservation key (which is what makes the atomic claim stop a double-spend) without the key
    revealing the card.
    """
    if not code or not isinstance(code, str):
        raise RedemptionError("INVALID")
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def reserve_redemption(*,
                       keys_table: Any,
                       code: str,
                       payment_attempt_id: str,
                       result: GiftCardResult,
                       currency: str = REDEMPTION_CURRENCY) -> Tuple[dict, str]:
    """Atomically reserve a verified gift-card redemption for one attempt. Double-spend safe.

    Returns ``(row, reason)`` where ``reason`` is ``APPLIED`` on success, ``CONCURRENT`` when the
    SAME card already holds a live reservation for a DIFFERENT attempt (one card funds at most one
    in-flight checkout), or ``DUPLICATE`` when this exact (card, attempt) already has a reservation
    (a retried click resumes onto the SAME figures rather than subtracting twice).

    The cross-attempt guard runs BEFORE the claim so a second card use is refused rather than
    reserved and immediately rolled back. The claim itself is the atomic race winner: two concurrent
    clicks for one attempt race on the conditional write and exactly one wins.
    """
    if not result.applied:
        raise RedemptionError(result.reason)
    fingerprint = card_fingerprint(code)

    # Cross-attempt guard: this card must not already fund a DIFFERENT live attempt.
    if order_keys.gift_card_is_reserved_elsewhere(
            keys_table, card_fingerprint=fingerprint, payment_attempt_id=payment_attempt_id):
        return {}, GIFT_CARD_CONCURRENT

    row, won = order_keys.reserve_gift_card_redemption(
        keys_table, card_fingerprint=fingerprint, payment_attempt_id=payment_attempt_id,
        authoritative_total_paise=result.authoritative_total_paise,
        redemption_paise=result.redemption_paise,
        razorpay_payable_paise=result.razorpay_payable_paise, currency=currency)
    if not won:
        # order_keys enforces the cross-attempt lock atomically too: a card locked by a DIFFERENT
        # live attempt returns a LOCKED_ELSEWHERE marker rather than a reservation.
        if str(row.get("state") or "") == "LOCKED_ELSEWHERE":
            return {}, GIFT_CARD_CONCURRENT
        # A reservation for this exact (card, attempt) already exists: a retried/concurrent click
        # for the SAME attempt resumes onto the winner's figures, not a second subtraction.
        return row, GIFT_CARD_DUPLICATE
    return row, GIFT_CARD_APPLIED


def release_redemption(*, keys_table: Any, code: str, payment_attempt_id: str,
                       reason: str = "RELEASED") -> bool:
    """Release a reservation so the balance is not stranded. The rollback for a failed Razorpay leg.

    Called when the shopper removes the card, the Razorpay payment fails AFTER the reservation was
    taken, or the attempt is abandoned. Conditional on the row still being RESERVED, so a committed
    redemption is never undone and a double release is a harmless no-op (returns False).
    """
    fingerprint = card_fingerprint(code)
    return order_keys.release_gift_card_redemption(
        keys_table, card_fingerprint=fingerprint, payment_attempt_id=payment_attempt_id,
        reason=reason)


def commit_redemption(*,
                      keys_table: Any,
                      code: str,
                      payment_attempt_id: str,
                      provider_payment_id: str = "",
                      redemption_paise: int = 0) -> bool:
    """Commit a reserved redemption exactly once for a captured payment (or zero-remaining order).

    Returns True on the first commit (the caller may apply it), False on every redelivery (already
    committed). Keyed by the Razorpay payment id so one capture commits a redemption exactly once;
    for a ZERO-remaining order there is no payment id, so the attempt-derived marker is used and the
    same conditional-write exactly-once guarantee holds. Advances the reservation row to COMMITTED.
    """
    fingerprint = card_fingerprint(code)
    claimed = order_keys.claim_gift_card_commit(
        keys_table, payment_id=provider_payment_id, card_fingerprint=fingerprint,
        payment_attempt_id=payment_attempt_id, redemption_paise=redemption_paise)
    if not claimed:
        return False
    order_keys.mark_gift_card_committed(
        keys_table, card_fingerprint=fingerprint, payment_attempt_id=payment_attempt_id,
        provider_payment_id=provider_payment_id)
    return True


def refund_redemption(*, keys_table: Any, code: str, payment_attempt_id: str) -> bool:
    """Release a COMMITTED redemption back to the card on a refund, so the balance is restored.

    A refund reverses a committed redemption: the reservation is marked RELEASED with a REFUNDED
    reason so reconciliation can see the balance was returned. Idempotent via the conditional write
    in ``order_keys`` (a second refund is a no-op). The actual provider-side balance credit is the
    concrete binding's job (see the runbook); this records the authoritative intent to restore.
    """
    return release_redemption(
        keys_table=keys_table, code=code, payment_attempt_id=payment_attempt_id,
        reason="REFUNDED")


def reconcile_reservation(*, keys_table: Any, code: str, payment_attempt_id: str) -> Optional[dict]:
    """The current reservation row for one (card, attempt), for payment/order reconciliation.

    Returns the stored row (``state`` RESERVED / RELEASED / COMMITTED and the authoritative paise
    figures) or None when none exists. Reconciliation re-derives the redemption/payable from THIS
    stored row, never from anything the browser relayed.
    """
    fingerprint = card_fingerprint(code)
    return order_keys.resolve_gift_card_redemption(
        keys_table, card_fingerprint=fingerprint, payment_attempt_id=payment_attempt_id)


__all__ = [
    "REDEMPTION_CURRENCY",
    "COUPON_APPLIED",
    "COUPON_INVALID",
    "COUPON_EXPIRED",
    "COUPON_INELIGIBLE",
    "GIFT_CARD_APPLIED",
    "GIFT_CARD_INVALID",
    "GIFT_CARD_EXPIRED",
    "GIFT_CARD_INELIGIBLE",
    "GIFT_CARD_INSUFFICIENT_BALANCE",
    "GIFT_CARD_DUPLICATE",
    "GIFT_CARD_CONCURRENT",
    "GIFT_CARD_UNAVAILABLE",
    "RedemptionError",
    "CouponAuthority",
    "GiftCardAuthority",
    "RedemptionProvider",
    "CouponResult",
    "GiftCardResult",
    "RedeemedPayable",
    "apply_coupon",
    "verify_gift_card",
    "build_payable",
    "card_fingerprint",
    "reserve_redemption",
    "release_redemption",
    "commit_redemption",
    "refund_redemption",
    "reconcile_reservation",
]
