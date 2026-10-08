"""The ONE concrete `redemption.RedemptionProvider`: our own stores, bound to the money authority.

What this module is
-------------------
`redemption.py` holds the money arithmetic, the apply order (coupon first as a price change, gift
card last as tender) and an ABSTRACT provider seam. `coupon_store` / `gift_card_store` hold the
definitions, the balances, the Wix mirror and the holds. Until this module existed the two halves
had never been joined: nothing under `amplify/` implemented the Protocol, so no discount reached
real money on any surface.

This is that join, and nothing else. It is the ONLY concrete implementation of the Protocol, which
is what makes "one coupon system, one gift-card system" a structural fact rather than a claim -
there is no second place a discount can come from, because there is no second provider.

Why the class is almost empty, and why that emptiness is the point
-----------------------------------------------------------------
Read the methods below and notice what is absent: there is no arithmetic. Not one multiplication,
not one percentage, not one subtraction of a discount from a total. Every figure that leaves this
module came from exactly one of two places:

  * a coupon amount, from `coupon_store.discount_paise` - the module that owns the definition;
  * a gift-card balance, read from the stored `balancePaise` attribute and only CONVERTED here.

A conversion is not a computation. `_balance_paise` turns the `Decimal` DynamoDB hands back into
an `int` and refuses a fractional one; it never derives a value. If a future change needs a number
this module does not already have, the right place for it is the store that owns the data, not
here. A provider that computes is a second discount engine wearing the Protocol's clothes.

Everything is injected, nothing is ambient
------------------------------------------
Both tables, the secret reader and the clock arrive through the constructor. There is no `boto3`
anywhere in this file - not at module scope and not inside a method - so it cannot read a secret
or reach a table by accident, and it tests offline against the in-memory fake the rest of the
coupon/gift-card suite already uses.

The pepper is read through `gift_card_store.read_pepper` at REQUEST time, inside
`read_gift_card`, never at import and never cached on the instance. A module-scope secret read is
frozen into a warm Lambda sandbox and survives a rotation, so the rotated value would not take
effect until every warm environment recycled. That failure has already happened once in this
repository, in `payments/razorpay-webhook`.

A gift-card code never reaches a log line
-----------------------------------------
Not reduced, not hashed, not shortened: a gift-card code appears in no logging expression in this
file at all. CodeQL's `py/clear-text-logging-sensitive-data` tracks taint across function
boundaries and has already failed this build twice on expressions that could not leak anything, so
the rule here is the strict one - the gift-card log lines carry a `reason` and a `cart_ref` and
nothing derived from the code. A COUPON code is different and is logged in full: it is broadcast
marketing material, and it is the only correlation id that path has.

What raises, and what returns a typed reason
--------------------------------------------
The distinction is deliberate and is the fail-closed boundary:

  * a code the customer got WRONG - malformed, unknown, expired, already used, held elsewhere, a
    disabled or empty card - returns a typed reason from `redemption`'s closed vocabulary. The
    caller renders it; nothing is refused outright.
  * a coupon that genuinely EXISTS and was promised but cannot be priced on this surface
    (`FREE_SHIPPING`, `BUY_X_GET_Y`, an unmet `minimumSubtotalPaise`, a corrupt stored amount)
    RAISES `coupon_store.CouponValidationError`. The caller must refuse the whole operation with
    that code rather than quietly discounting nothing - the customer was promised something and
    silently collecting the full amount is the one outcome worse than an error.
  * a STORAGE failure (`CouponStoreUnavailable`, `GiftCardStoreUnavailable`) raises and is never
    converted into "invalid". Both stores document why: a throttle reported as absence refuses a
    live coupon, and absence is a decision input here.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from lambda_utils.ecommerce import coupon_store, gift_card_store, redemption

logger = logging.getLogger(__name__)

#: Every `coupon_store` verdict other than `ELIGIBLE`, mapped onto `redemption`'s typed reasons.
#: Written as a complete table rather than an `if` chain with a fallback, so a NEW verdict is a
#: `KeyError` in a test rather than a silent `INELIGIBLE` in production.
#:
#: `NOT_STARTED` joins `EXPIRED` because both are the same fact to a customer - the coupon is not
#: usable at this moment - and `redemption`'s vocabulary has one reason for a timing refusal. The
#: precise verdict is still logged.
COUPON_REASON_BY_VERDICT: Dict[str, str] = {
    coupon_store.UNKNOWN_CODE: redemption.COUPON_INVALID,
    coupon_store.EXPIRED: redemption.COUPON_EXPIRED,
    coupon_store.NOT_STARTED: redemption.COUPON_EXPIRED,
    coupon_store.NOT_ACTIVE: redemption.COUPON_INELIGIBLE,
    coupon_store.USAGE_LIMIT_REACHED: redemption.COUPON_INELIGIBLE,
    coupon_store.CUSTOMER_LIMIT_REACHED: redemption.COUPON_INELIGIBLE,
    coupon_store.HELD_BY_ANOTHER_CART: redemption.COUPON_INELIGIBLE,
    coupon_store.WIX_MIRROR_INCOMPLETE: redemption.COUPON_INELIGIBLE,
}

#: Which gift-card refusal is which typed reason. `GiftCardDisabled` is `INELIGIBLE` rather than
#: `INVALID` because the card is real and the holder may be able to get it re-enabled, whereas
#: `GiftCardNotFound` must answer exactly as a malformed code does so the path cannot be ground
#: into a code oracle - which is why `gift_card_store.normalise_code` raises `GiftCardNotFound`
#: for a badly shaped code rather than a validation error.
GIFT_CARD_REASON_BY_ERROR = (
    (gift_card_store.GiftCardNotFound, redemption.GIFT_CARD_INVALID),
    (gift_card_store.GiftCardExpired, redemption.GIFT_CARD_EXPIRED),
    (gift_card_store.GiftCardDisabled, redemption.GIFT_CARD_INELIGIBLE),
    (gift_card_store.MissingCurrency, redemption.GIFT_CARD_INELIGIBLE),
    (gift_card_store.CurrencyNotSupported, redemption.GIFT_CARD_INELIGIBLE),
)

#: The same classes as a tuple, built once, so the `except` clause is a constant rather than a
#: tuple reassembled on every request.
_GIFT_CARD_REFUSALS = tuple(error for error, _ in GIFT_CARD_REASON_BY_ERROR)

Clock = Callable[[], int]
SecretReader = Callable[[str], Dict[str, Any]]


def _default_clock() -> int:
    """Epoch SECONDS as an `int`, matching both stores' clock contract.

    An `int` rather than `time.time()`'s native type, so nothing on this path is inexact - the
    same reason `coupon_store._default_clock` is written this way.
    """
    return int(time.time())


class StoreRedemptionProvider:
    """`redemption.RedemptionProvider` over the coupon and gift-card tables.

    Satisfies the Protocol structurally (it is a `typing.Protocol`, so no inheritance is needed
    and none is declared - `tests/test_store_redemption_provider.py` asserts the structural
    match instead, which is the thing that actually has to hold).

    Constructor arguments, all injected:

    * ``coupons_table`` / ``gift_cards_table`` - DynamoDB table resources, or the in-memory fake.
    * ``secret_reader`` - a callable taking a secret id and returning the parsed mapping. Only
      `read_gift_card` uses it, and only at the moment it needs the pepper.
    * ``customer_id`` - optional. When present, the per-customer usage counter is read and fed to
      `coupon_store.evaluate`, which is what makes `limitPerCustomer` enforceable. When absent
      the counter is NOT read and `CUSTOMER_LIMIT_REACHED` cannot be reported: a staff-raised
      invoice may genuinely have no customer identity yet, and inventing one would attribute a
      use to the wrong person. Stated here because it is a real narrowing, not an oversight.
    * ``clock`` - epoch seconds, injected so expiry is testable without waiting.
    """

    def __init__(self, *, coupons_table: Any, gift_cards_table: Any,
                 secret_reader: SecretReader, customer_id: Optional[str] = None,
                 clock: Clock = _default_clock) -> None:
        self._coupons_table = coupons_table
        self._gift_cards_table = gift_cards_table
        self._secret_reader = secret_reader
        self._customer_id = customer_id
        self._clock = clock

    # ── coupon: a verdict from our store, an amount from the module that owns it ──
    def validate_coupon(self, *, code: str, collection_before_discount_paise: int,
                        cart_ref: str) -> redemption.CouponAuthority:
        """Resolve one coupon code against our own definitions and price it.

        Order: normalise, read the definition by exact key, read this customer's usage counter
        when there is a customer, then `evaluate`. Only an `ELIGIBLE` verdict is priced, so a
        usage-limited or unmirrored coupon never reaches the arithmetic at all.

        The amount is `coupon_store.discount_paise`, not a figure computed here. That is the
        whole binding: `redemption.apply_coupon` then clamps it to the collection and returns the
        discounted collection that feeds the convenience-fee calculator.
        """
        try:
            normalised = coupon_store.normalise_code(code)
        except coupon_store.CouponValidationError:
            # A badly shaped code is a customer input error, and `INVALID` is exactly the typed
            # reason for it. Raising would turn a typo into a failed invoice.
            return redemption.CouponAuthority(valid=False, reason=redemption.COUPON_INVALID)

        definition = coupon_store.get_definition(self._coupons_table, normalised)
        uses = 0
        if definition is not None and self._customer_id is not None:
            uses = coupon_store.customer_uses(self._coupons_table, normalised,
                                              self._customer_id)
        verdict = coupon_store.evaluate(definition, cart_id=cart_ref,
                                        customer_uses_count=uses, clock=self._clock)

        if verdict != coupon_store.ELIGIBLE:
            # A coupon code is NOT bearer value - it is broadcast marketing material - so it is
            # logged in full deliberately. It is the one correlation id this path has.
            logger.info("coupon refused: code=%s verdict=%s cart=%s",
                        normalised, verdict, cart_ref)
            return redemption.CouponAuthority(
                valid=False, reason=COUPON_REASON_BY_VERDICT[verdict])

        # Raises `CouponValidationError` on a kind this surface cannot price, on an unmet
        # minimum subtotal, and on a stored amount that is not integer paise. Deliberately NOT
        # caught: see the module docstring - the coupon exists and was promised, so refusing is
        # correct and discounting nothing is not.
        amount = coupon_store.discount_paise(
            definition, collection_paise=collection_before_discount_paise)
        logger.info("coupon applied: code=%s discountPaise=%s cart=%s",
                    normalised, amount, cart_ref)
        return redemption.CouponAuthority(valid=True, reason=redemption.COUPON_APPLIED,
                                          discount_paise=amount)

    # ── gift card: a balance from our ledger, converted and never computed ───────
    def read_gift_card(self, *, code: str, cart_ref: str) -> redemption.GiftCardAuthority:
        """Resolve one gift-card code to its authoritative balance. Reads only; never debits.

        The code is normalised, peppered into an HMAC and used to read ONE row by exact key, so
        the raw code is never a storage key and never leaves this method. `assert_spendable`
        refuses an unknown, disabled or expired card in that order; the currency is then compared
        EXPLICITLY against `INR` rather than inferred from the amount.

        A usable card with a ZERO balance is reported as usable with `balance_paise=0` on
        purpose: `redemption.verify_gift_card` already turns that into
        `INSUFFICIENT_BALANCE`, and duplicating the test here would be a second place that
        decides whether a balance is spendable.

        This method takes no hold and moves no balance. An invoice is not the producer that mints
        the payment attempt, and a hold taken outside that request skips the `GC_HELD` stage and
        lets `gift_card_settlement.is_fully_settled` settle a gift-card order on the Razorpay leg
        alone - which is why `POST /gift-cards/hold` does not exist either.
        """
        try:
            # Normalised BEFORE the pepper is read, so a malformed code never causes a secret
            # read. `normalise_code` raises `GiftCardNotFound` rather than a validation error,
            # which is what makes a bad shape and an unknown card answer identically.
            normalised = gift_card_store.normalise_code(code)
            pepper = gift_card_store.read_pepper(self._secret_reader)
            digest = gift_card_store.code_hash(normalised, pepper=pepper)
            card = gift_card_store.get_card(self._gift_cards_table, code_hash=digest)
            spendable = gift_card_store.assert_spendable(card, now_ms=self._clock() * 1000)
            gift_card_store.assert_currency(spendable.get("currency"))
        except _GIFT_CARD_REFUSALS as refusal:
            reason = next(mapped for error, mapped in GIFT_CARD_REASON_BY_ERROR
                          if isinstance(refusal, error))
            # No code-derived value in this expression. Not the code, not its last four, not a
            # hash: the reason and the reference are enough to trace, and a bearer secret in a
            # logging expression is what the taint analysis is for.
            logger.info("gift card refused: reason=%s cart=%s", reason, cart_ref)
            return redemption.GiftCardAuthority(usable=False, reason=reason)

        balance = _balance_paise(spendable.get("balancePaise"))
        logger.info("gift card read: reason=%s balancePaise=%s cart=%s",
                    redemption.GIFT_CARD_APPLIED, balance, cart_ref)
        return redemption.GiftCardAuthority(usable=True, reason=redemption.GIFT_CARD_APPLIED,
                                            balance_paise=balance)


def _balance_paise(value: Any) -> int:
    """CONVERT a stored balance to `int` paise. Never derive one.

    DynamoDB returns every number as `Decimal`, so refusing `Decimal` outright would make this
    unusable against a real row. An integral `Decimal` converts through
    `int(Decimal(str(value)))`; a fractional one, a bool, a negative or anything else RAISES
    `GiftCardValidationError` rather than being rounded into something chargeable. A balance we
    cannot represent exactly is a balance we must not spend, and a sub-paise remainder is below
    what any gateway can collect.

    Zero is permitted and is NOT an error here - it is reported upwards as a usable card with no
    balance, and `redemption.verify_gift_card` owns the `INSUFFICIENT_BALANCE` verdict.
    """
    if isinstance(value, bool):
        raise gift_card_store.GiftCardValidationError(
            "INVALID_BALANCE", "a balance must be integer paise, not a bool")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise gift_card_store.GiftCardValidationError(
                "INVALID_BALANCE", "a balance must be an exact integer number of paise")
        value = int(Decimal(str(value)))
    if type(value) is not int or value < 0 or value > gift_card_store.MONEY_CEILING_PAISE:
        raise gift_card_store.GiftCardValidationError(
            "INVALID_BALANCE", "a balance must be nonnegative integer paise")
    return value


__all__ = [
    "COUPON_REASON_BY_VERDICT",
    "GIFT_CARD_REASON_BY_ERROR",
    "SecretReader",
    "StoreRedemptionProvider",
]
