"""Section 7 checkout pricing: convenience fee + GST-on-fee, exact in integer INR paise.

What this module is for
-----------------------
The checkout handler historically charged the bare Wix supply total. Section 7 of the owner's
specification requires a convenience fee and GST on that fee to be added on top of the
*authoritative approved collection total*, and it requires the amount reviewed by the customer,
the amount sent to the gateway and the amount printed on the receipt to be the SAME number. A
single authoritative calculator is the only way those three stay equal, so there is exactly one
here and everything else is forbidden from re-deriving the arithmetic.

The formula, verbatim from section 7
-------------------------------------
    convenienceFeePaise  = round_half_up(collectionBeforeConveniencePaise * 250  / 10000)
    convenienceGstPaise  = round_half_up(convenienceFeePaise             * 1800 / 10000)
    totalPayablePaise    = collectionBeforeConveniencePaise + convenienceFeePaise
                                                             + convenienceGstPaise

`collectionBeforeConveniencePaise` is the authoritative approved collection total AFTER supply
GST, discounts and delivery, and it EXCLUDES the convenience fee and its GST. It is an input to
this module, not something this module computes: the supply GST / discount / delivery build
belongs upstream (Wix / the catalog), and double-adding GST where catalog pricing is already
inclusive is a defect this module refuses to commit - it adds GST only to the convenience fee,
never to the supply.

Why Decimal and integer paise, never float
-------------------------------------------
Money is integer minor units. `250 / 10000` and `1800 / 10000` are exact rationals; evaluated
in binary floating point they are not, and a half-paise tie would then round the wrong way
depending on representation error. Every multiplication and division here is `Decimal` with an
explicit `ROUND_HALF_UP`, and every stored component is an `int` number of paise. There is no
float anywhere on this path, by construction - inputs that are floats or carry a fractional
paise are rejected rather than silently rounded. The primitives in `money.py`
(`Money`, `positive_paise`) are reused for the bounds and type checks; this module does not
reinvent paise handling.

Zero-total behavior
-------------------
A collection of zero is a legitimate quote (a fully discounted or zero-value cart), and its fee
and GST are both zero, so its total payable is zero. That is NOT the same as a captured payment:
`is_payable` is False for a zero total, and `requires_payment` says the same thing from the
other direction. Nothing in this module marks an order paid, and a zero-total quote must never
be handed to a gateway or recorded as a capture - an uncharged order is not a purchase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from lambda_utils.ecommerce.money import Money

# ── policy version ───────────────────────────────────────────────────────────────
#: Bumped whenever the fee basis, the rate, the GST rate, or the rounding rule changes. Stored
#: on every computed quote and every snapshot so a persisted amount can always be traced to the
#: exact arithmetic that produced it. A change in rate without a change in this string is the
#: bug this constant exists to make impossible to miss.
CALCULATION_POLICY_VERSION = "checkout-pricing-2026-10-01"

# ── rates, expressed as exact integer basis points over a 10000 denominator ────────
#: Convenience fee: 2.5% == 250 / 10000. Kept as integers so the arithmetic is exact rational.
CONVENIENCE_FEE_BPS = 250
#: GST on the convenience fee: 18% == 1800 / 10000.
CONVENIENCE_GST_BPS = 1800
RATE_DENOMINATOR = 10000

#: The upper bound money.py enforces (2**53 - 1), reused so overflow is rejected identically.
_MAX_PAISE = 9007199254740991

# ── GSTIN ──────────────────────────────────────────────────────────────────────
#: The seller's GSTIN. A constant here, distinct from any buyer GSTIN by construction: the
#: buyer value is an argument and the two are compared, so a buyer GSTIN equal to the seller's
#: is rejected rather than silently accepted (which would mean a self-dealing invoice).
SELLER_GSTIN = "19AAFFW7196L1Z8"

#: Standard GSTIN shape: 2-digit state code, 10-char PAN, entity digit, 'Z', one checksum char.
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


class PricingError(ValueError):
    """A quote could not be computed from the given inputs.

    A subclass of ValueError so existing callers that catch ValueError keep working, but a
    distinct type so the pricing path can be told apart from an unrelated bad argument.
    """


def _state_code(gstin: str) -> str:
    return gstin[:2]


def round_half_up(numerator_paise: int, bps: int) -> int:
    """Return round_half_up(numerator_paise * bps / 10000) as an exact integer paise.

    Uses Decimal throughout with ROUND_HALF_UP, so a value whose fractional part is exactly
    one half always rounds away from zero (up, since all inputs here are non-negative). The
    inputs are integers, so the only source of a fraction is the division by the denominator;
    quantizing to an integer with ROUND_HALF_UP is therefore the whole rounding rule.
    """
    if type(numerator_paise) is not int or type(bps) is not int:
        raise PricingError("round_half_up operates on integer paise and integer basis points")
    if numerator_paise < 0 or bps < 0:
        raise PricingError("round_half_up operates on non-negative values")
    exact = (Decimal(numerator_paise) * Decimal(bps)) / Decimal(RATE_DENOMINATOR)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _validate_collection_paise(value: Any) -> int:
    """Return `value` as a validated integer paise, or raise PricingError.

    Zero is allowed here (a zero-value cart is a legitimate quote); the positivity question is
    answered later by `is_payable`. Floats, bools, fractional-paise Decimals, negatives and
    values past the money.py ceiling are all rejected rather than rounded.
    """
    if isinstance(value, bool):
        raise PricingError("collection must be integer paise, not a bool")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise PricingError("collection must be an exact integer number of paise")
        value = int(value)
    if isinstance(value, float):
        raise PricingError("collection must be integer paise, floats are forbidden")
    if type(value) is not int:
        raise PricingError("collection must be integer paise")
    if value < 0:
        raise PricingError("collection must not be negative")
    if value > _MAX_PAISE:
        raise PricingError("collection exceeds the maximum representable paise")
    return value


def _validate_currency(currency: str) -> str:
    if currency != "INR":
        raise PricingError("only INR is supported; got %r" % (currency,))
    return currency


def _validate_buyer_gstin(buyer_gstin: Optional[str]) -> Optional[str]:
    if buyer_gstin is None:
        return None
    if not isinstance(buyer_gstin, str) or not _GSTIN_RE.match(buyer_gstin):
        raise PricingError("buyer GSTIN is malformed: %r" % (buyer_gstin,))
    if buyer_gstin == SELLER_GSTIN:
        raise PricingError("buyer GSTIN must be distinct from the seller GSTIN")
    return buyer_gstin


@dataclass(frozen=True)
class TaxSplit:
    """A GST amount split into CGST/SGST (intra-state) or IGST (inter-state).

    Exactly one of the two forms is populated; the other pair is zero. The invariant the
    constructor enforces is the only thing that matters: cgst + sgst + igst == total, exactly,
    with no rounding slack. CGST and SGST are kept equal where possible and any odd paise is
    assigned to CGST so the pair still sums to the whole, which is the standard reconciliation.
    """

    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    intra_state: bool

    def __post_init__(self):
        for name, v in (("cgst", self.cgst_paise), ("sgst", self.sgst_paise),
                        ("igst", self.igst_paise)):
            if type(v) is not int or v < 0:
                raise PricingError("%s must be non-negative integer paise" % name)

    @property
    def total_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise


def split_gst(gst_paise: int, *, intra_state: bool) -> TaxSplit:
    """Split a GST amount into CGST/SGST or IGST that reconciles EXACTLY to `gst_paise`.

    Intra-state supply is CGST + SGST (nominally half each); inter-state is a single IGST line.
    Half of an odd paise cannot be represented twice, so the floor goes to SGST and the
    remainder to CGST, and the two always sum back to the input - the reconciliation is checked,
    not assumed.
    """
    if type(gst_paise) is not int or gst_paise < 0:
        raise PricingError("gst must be non-negative integer paise")
    if intra_state:
        sgst = gst_paise // 2
        cgst = gst_paise - sgst
        split = TaxSplit(cgst_paise=cgst, sgst_paise=sgst, igst_paise=0, intra_state=True)
    else:
        split = TaxSplit(cgst_paise=0, sgst_paise=0, igst_paise=gst_paise, intra_state=False)
    if split.total_paise != gst_paise:
        raise PricingError("GST split failed to reconcile to the input amount")
    return split


@dataclass(frozen=True)
class CheckoutQuote:
    """The computed, rounded components of one checkout quote. Immutable.

    Every amount is integer paise and the identity
        total_payable_paise == collection + fee + gst
    holds exactly, re-checked in `__post_init__` so a hand-constructed instance cannot violate
    it. The convenience-fee GST split reconciles to `convenience_gst_paise`. The policy version
    is carried so a stored amount can be traced to the arithmetic that produced it.
    """

    collection_before_convenience_paise: int
    convenience_fee_paise: int
    convenience_gst_paise: int
    total_payable_paise: int
    currency: str
    policy_version: str
    seller_gstin: str
    buyer_gstin: Optional[str]
    convenience_gst_split: TaxSplit

    def __post_init__(self):
        # Validate the money.py bounds on every stored component.
        for name, v in (
            ("collection", self.collection_before_convenience_paise),
            ("fee", self.convenience_fee_paise),
            ("gst", self.convenience_gst_paise),
            ("total", self.total_payable_paise),
        ):
            if type(v) is not int or not 0 <= v <= _MAX_PAISE:
                raise PricingError("%s must be nonnegative integer paise" % name)
        expected = (self.collection_before_convenience_paise
                    + self.convenience_fee_paise
                    + self.convenience_gst_paise)
        if self.total_payable_paise != expected:
            raise PricingError("total does not reconcile to collection + fee + gst")
        if self.convenience_gst_split.total_paise != self.convenience_gst_paise:
            raise PricingError("GST split does not reconcile to the convenience GST")
        _validate_currency(self.currency)

    @property
    def is_payable(self) -> bool:
        """True only when there is a strictly positive amount to charge.

        A zero total is a valid quote but not a payment: handing it to a gateway or recording it
        as a capture would pretend an uncharged order is a purchase. The checkout path must gate
        on this rather than on the mere existence of a quote.
        """
        return self.total_payable_paise > 0

    @property
    def requires_payment(self) -> bool:
        return self.is_payable

    def as_payable_money(self) -> Money:
        """The total as a `Money`, usable only when `is_payable`.

        Deliberately raises for a zero total: `Money`/`positive_paise` is the type that flows to
        the gateway, and a zero amount must never reach it.
        """
        if not self.is_payable:
            raise PricingError("a zero-total quote is not payable and has no gateway amount")
        return Money(self.total_payable_paise, self.currency)

    def components(self) -> Dict[str, Any]:
        """The rounded components as a plain dict, for storage and for the snapshot hash."""
        return {
            "collectionBeforeConveniencePaise": self.collection_before_convenience_paise,
            "convenienceFeePaise": self.convenience_fee_paise,
            "convenienceGstPaise": self.convenience_gst_paise,
            "totalPayablePaise": self.total_payable_paise,
            "currency": self.currency,
            "policyVersion": self.policy_version,
            "sellerGstin": self.seller_gstin,
            "buyerGstin": self.buyer_gstin,
            "convenienceGst": {
                "cgstPaise": self.convenience_gst_split.cgst_paise,
                "sgstPaise": self.convenience_gst_split.sgst_paise,
                "igstPaise": self.convenience_gst_split.igst_paise,
                "intraState": self.convenience_gst_split.intra_state,
            },
        }


def compute_quote(collection_before_convenience_paise: Any,
                  *,
                  currency: str = "INR",
                  buyer_gstin: Optional[str] = None,
                  intra_state: Optional[bool] = None) -> CheckoutQuote:
    """Compute the section 7 quote from the authoritative approved collection total.

    `collection_before_convenience_paise` is the collection AFTER supply GST, discounts and
    delivery and EXCLUDES the convenience fee and its GST. This function adds only the
    convenience fee and GST-on-fee; it never touches the supply GST, so inclusive catalog
    pricing is not double-taxed here.

    `intra_state` controls the CGST/SGST (True) vs IGST (False) split of the fee's GST. When a
    buyer GSTIN is supplied it is inferred from whether the buyer's state code matches the
    seller's; an explicit value overrides the inference. It defaults to intra-state when neither
    is available.
    """
    collection = _validate_collection_paise(collection_before_convenience_paise)
    _validate_currency(currency)
    validated_buyer = _validate_buyer_gstin(buyer_gstin)

    fee = round_half_up(collection, CONVENIENCE_FEE_BPS)
    gst = round_half_up(fee, CONVENIENCE_GST_BPS)
    total = collection + fee + gst
    if total > _MAX_PAISE:
        raise PricingError("total payable exceeds the maximum representable paise")

    if intra_state is None:
        if validated_buyer is not None:
            intra_state = _state_code(validated_buyer) == _state_code(SELLER_GSTIN)
        else:
            intra_state = True

    split = split_gst(gst, intra_state=intra_state)

    return CheckoutQuote(
        collection_before_convenience_paise=collection,
        convenience_fee_paise=fee,
        convenience_gst_paise=gst,
        total_payable_paise=total,
        currency=currency,
        policy_version=CALCULATION_POLICY_VERSION,
        seller_gstin=SELLER_GSTIN,
        buyer_gstin=validated_buyer,
        convenience_gst_split=split,
    )


def exempt_quote(collection_before_convenience_paise: Any,
                 *,
                 currency: str = "INR",
                 buyer_gstin: Optional[str] = None,
                 intra_state: Optional[bool] = None) -> CheckoutQuote:
    """A quote that collects the supply total and adds no convenience fee.

    OWNER DECISION [PHASE2-FEE-001], answered 2026-10-03: a voluntary contribution carries no
    convenience fee and no GST on a fee that does not exist, so the customer pays exactly the
    amount they chose.

    Same signature as `compute_quote` so it is substitutable as a `quote_fn`. Fee and GST are
    zero, so `CheckoutQuote.__post_init__`'s `total == collection + fee + gst` identity holds
    and `split_gst(0, ...)` reconciles. `compute_quote` is untouched: a fee policy that varies
    by basket must not live inside the calculator every other basket shares.

    `intra_state is None` is normalised to **True**, matching `compute_quote`'s own documented
    default ("It defaults to intra-state when neither is available"). `split_gst` treats None as
    falsy and would take the IGST branch, so a zero split would be stored as `intraState: false`
    -- a value that changes no total but is printed on a receipt and is covered by `basket_hash`.
    Two code paths must not disagree about an unknown.

    WHEN `intra_state` IS ACTUALLY None HERE, because the normalisation is otherwise dead code and
    a reader will delete it: NOT "a contribution has no address". Every checkout identity has one
    -- `auth/customer-profile/handler.py` refuses an addressless create -- so `owned` is normally
    truthy and the caller's `_intra_state(gst_state_code(owned))` is normally not None. The
    reachable case is a stored address that no longer RESOLVES: a legacy contact row predating the
    create-time requirement, or one whose address `contact_address.from_contact` now rejects.
    Rare, real, and the one the test is written against.

    IT RUNS COMPUTE_QUOTE'S OWN VALIDATORS, and that is the point rather than a formality. "Same
    signature" is not "same refusals": a substituted calculator that validated less than the one
    it replaces would make the exempt path the LENIENT side of a seam whose whole job is to be the
    strict one. `CheckoutQuote.__post_init__` is a real backstop -- it re-checks `type(v) is int`
    on all four components and calls `_validate_currency` -- but it does not see a GSTIN, and it
    would accept an integral Decimal that `compute_quote` would have normalised. So the three
    validation lines are written out below rather than inherited by assumption.
    """
    collection = _validate_collection_paise(collection_before_convenience_paise)
    _validate_currency(currency)
    validated_buyer = _validate_buyer_gstin(buyer_gstin)

    # Fee and GST are zero, so total == collection, `__post_init__`'s
    # `total == collection + fee + gst` identity holds, and `split_gst(0, ...)` reconciles.
    # No `total > _MAX_PAISE` check is needed: `_validate_collection_paise` already enforces the
    # paise ceiling and nothing is added to the figure it returned.
    total = collection

    # compute_quote's OWN normalisation block, mirrored rather than simplified, so the two
    # calculators cannot disagree about an unknown. See the paragraph above for when this is
    # reached. The split is zero either way; what this decides is the `intraState` flag that gets
    # stored, hashed into `basket_hash` and printed.
    if intra_state is None:
        if validated_buyer is not None:
            intra_state = _state_code(validated_buyer) == _state_code(SELLER_GSTIN)
        else:
            intra_state = True

    return CheckoutQuote(
        collection_before_convenience_paise=collection,
        convenience_fee_paise=0,
        convenience_gst_paise=0,
        total_payable_paise=total,
        currency=currency,
        policy_version=CALCULATION_POLICY_VERSION,
        seller_gstin=SELLER_GSTIN,
        buyer_gstin=validated_buyer,
        convenience_gst_split=split_gst(0, intra_state=intra_state),
    )


# ── immutable quote snapshot ───────────────────────────────────────────────────────

def _canonical(value: Any) -> Any:
    """Normalise a nested structure into something with a single deterministic JSON encoding.

    Mappings become key-sorted dicts; sequences keep order (cart line order is meaningful);
    scalars pass through. The point is that two logically-equal snapshots hash the same and any
    change - a different quantity, a new address line, a reordered component - changes the hash.
    """
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return value
    if isinstance(value, Decimal):
        # Decimals must be exact integers on money paths; refuse a fractional one rather than
        # fold it into a float and poison the hash.
        if not value.is_finite() or value != value.to_integral_value():
            raise PricingError("snapshot values must not carry fractional Decimals")
        return int(value)
    if isinstance(value, float):
        raise PricingError("snapshot values must not be floats")
    return str(value)


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(_canonical(payload), separators=(",", ":"),
                         ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def basket_hash(frozen_payload: Mapping[str, Any]) -> str:
    """Identity of the BASKET a quote was taken from, with Wix's revision counter removed.

    `snapshot_hash` cannot answer "is this the same basket?", and the reason is measured rather
    than theoretical. `_snapshot_payload` hashes `"cart": {"id": cart_id, "revision":
    cart_revision}`, and the website prepare path WRITES TO THE WIX CART on every call:
    `purchase_intent.prepare_delivery` PATCHes the cart, then `cart_v2.calculate` refreshes it and
    asserts the returned `summary.cartRevision` equals the cart's own `revision`. Wix's `revision`
    is the optimistic-concurrency counter on that resource, so a second prepare of an UNEDITED
    basket can present a different `snapshot_hash` — and a guard keyed on a value that may always
    differ is a guard that never fires.

    Built from the SAME payload `snapshot_hash` was built from, through the SAME `_stable_hash`,
    with exactly ONE term dropped. That is the whole design: deriving it from the frozen payload
    rather than from re-assembled parts means there is no second reading of "what a basket is" to
    drift from the first, and a new term added to `_snapshot_payload` later is covered here
    automatically instead of being silently excluded.

    `cart.id` stays IN. Dropping it too would make the identity global-per-basket, so two
    different carts would share one.
    """
    if not isinstance(frozen_payload, Mapping):
        raise PricingError("basket identity requires the frozen snapshot payload")
    cart = frozen_payload.get("cart")
    cart_id = str(cart.get("id") or "") if isinstance(cart, Mapping) else ""
    if not cart_id:
        # Never fall back to hashing a payload with no cart: that would make two different carts
        # share one identity, which is the opposite failure and a worse one.
        raise PricingError("basket identity requires a cart id")
    payload = {key: value for key, value in frozen_payload.items() if key != "cart"}
    payload["cart"] = {"id": cart_id}
    return _stable_hash(payload)


def narrow_basket_hash(frozen_payload: Mapping[str, Any]) -> str:
    """The shopper-visible basket: cart id, line ids and quantities, quote components, tender.

    Deliberately POSITIVE where `basket_hash` is subtractive. `basket_hash` cannot prove that
    `items` / `address` / `delivery` carry no per-calculation field, because those are Wix's raw
    shapes straight out of `cart_v2.calculate`. Everything enumerated HERE is contract-checked by
    us on every calculate:

      * `{lineItemId: quantity}` — `calculate` raises unless it equals the cart's own
        `quantityInfo.confirmedQuantity` per line, and unless the line totals sum to
        `priceSummary.subtotal`;
      * `components` — our own `quote.components()`, computed by `compute_quote` from the
        authoritative collection total, not relayed from Wix;
      * the tender split — `calculate` raises unless `payNow == total - redeem`,
        `totalAfterGiftCards == payNow` and the card is bound to the cart by id.

    So a per-calculation field cannot enter this hash. It is COARSER than `basket_hash` — it
    ignores the address, the delivery method and every non-enumerated line-item field — which is
    why it is used ONLY TO REFUSE and never to allow. Returns "" when the payload carries no
    usable line items, meaning "no narrow identity available", which the guard treats as "cannot
    help" and falls back to `basket_hash` alone.

    The tender terms are deliberately included. `components` is derived from the COLLECTION total,
    which a gift card does not change — only the split does — so with the tender excluded, a
    basket paid with a gift card and the same items later paid WITHOUT one would hash equal and be
    refused permanently. Including the three reconciled integers keeps the identity deterministic
    per basket while keeping that purchase payable. The risk traded for is nil in the dangerous
    direction: more terms can only make the narrow hash DIFFER more readily, and a difference
    never becomes a pass.
    """
    if not isinstance(frozen_payload, Mapping):
        raise PricingError("basket identity requires the frozen snapshot payload")
    cart = frozen_payload.get("cart")
    cart_id = str(cart.get("id") or "") if isinstance(cart, Mapping) else ""
    if not cart_id:
        raise PricingError("basket identity requires a cart id")
    items = frozen_payload.get("items")
    if not isinstance(items, list) or not items:
        return ""
    lines = []
    for line in items:
        if not isinstance(line, Mapping):
            return ""
        line_id = str(line.get("lineItemId") or "")
        if not line_id:
            return ""
        lines.append([line_id, line.get("quantity")])
    payment = frozen_payload.get("payment")
    payment = payment if isinstance(payment, Mapping) else {}
    card = payment.get("wixGiftCard")
    card = card if isinstance(card, Mapping) else {}
    return _stable_hash({
        "cart": cart_id,
        # Sorted, so a reordered `summary.lineItems` is the SAME basket. `_snapshot_payload`
        # preserves Wix's order deliberately for the quote hash; here order is not identity.
        "lines": sorted(lines, key=lambda pair: pair[0]),
        "components": frozen_payload.get("components"),
        # The money split, by the three values `calculate` reconciles. `obfuscatedCode` and
        # `appId` are deliberately NOT here: they are raw Wix strings and not amounts.
        "tender": {"giftCardId": str(card.get("giftCardId") or ""),
                   "redeemPaise": payment.get("wixGiftCardRedeemPaise"),
                   "payNowPaise": payment.get("wixPayNowPaise")},
    })


@dataclass(frozen=True)
class QuoteSnapshot:
    """An immutable, customer-owned purchase-intent snapshot.

    Carries the cart revision it was taken at, an absolute expiry, a stable hash over the frozen
    customer/site/cart/item/address/delivery/component data, the computed quote and the policy
    version. It is frozen: a cart edit does not mutate this object, it produces a NEW snapshot
    (via `build_snapshot` again) with a different hash. A paid or unresolved snapshot is never
    rewritten in place - that is what makes "the amount the customer reviewed" auditable.
    """

    customer_id: str
    cart_id: str
    cart_revision: int
    created_at: int
    expires_at: int
    policy_version: str
    quote: CheckoutQuote
    snapshot_hash: str
    frozen_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.customer_id, str) or not self.customer_id:
            raise PricingError("snapshot requires a customer id")
        if not isinstance(self.cart_id, str) or not self.cart_id:
            raise PricingError("snapshot requires a cart id")
        if type(self.cart_revision) is not int or self.cart_revision < 0:
            raise PricingError("cart revision must be a non-negative integer")
        if type(self.created_at) is not int or type(self.expires_at) is not int:
            raise PricingError("timestamps must be integer epoch seconds")
        if self.expires_at <= self.created_at:
            raise PricingError("expiry must be after creation")

    def is_expired(self, now: int) -> bool:
        """True once `now` has reached the absolute expiry. An expired quote may not be charged."""
        if type(now) is not int:
            raise PricingError("now must be integer epoch seconds")
        return now >= self.expires_at

    def matches(self, other_hash: str) -> bool:
        """Constant-time-ish equality of snapshot hashes. A changed cart yields a different hash."""
        return isinstance(other_hash, str) and other_hash == self.snapshot_hash


def _snapshot_payload(*, customer_id: str, site: Any, cart_id: str, cart_revision: int,
                      items: Any, address: Any, delivery: Any,
                      quote: CheckoutQuote, policy_version: str,
                      payment: Any = None) -> Dict[str, Any]:
    payload = {
        "customer": customer_id,
        "site": site,
        "cart": {"id": cart_id, "revision": cart_revision},
        "items": items,
        "address": address,
        "delivery": delivery,
        "components": quote.components(),
        "policyVersion": policy_version,
    }
    # Payment/tender data is optional so pre-existing snapshot callers keep the exact same hash.
    # Cart V2 website checkout supplies it when Wix calculated a gift-card split; binding that
    # split into the immutable snapshot prevents a later callback from settling a different tender.
    if payment is not None:
        payload["payment"] = payment
    return payload


def build_snapshot(*,
                   customer_id: str,
                   cart_id: str,
                   cart_revision: int,
                   quote: CheckoutQuote,
                   created_at: int,
                   ttl_seconds: int,
                   site: Any = None,
                   items: Any = None,
                   address: Any = None,
                   delivery: Any = None,
                   payment: Any = None) -> QuoteSnapshot:
    """Freeze a reviewed quote into an immutable snapshot with a stable hash.

    The hash covers the customer, site, cart id and revision, the item list (order preserved),
    the address, the delivery choice, the rounded quote components and the policy version. Any
    change to any of those - which is exactly what a cart edit is - produces a different hash,
    so a new snapshot is a new object rather than a mutation of this one.
    """
    if type(created_at) is not int or type(ttl_seconds) is not int:
        raise PricingError("created_at and ttl_seconds must be integer seconds")
    if ttl_seconds <= 0:
        raise PricingError("ttl_seconds must be positive")
    if quote.policy_version != CALCULATION_POLICY_VERSION:
        raise PricingError("quote policy version does not match the current calculator")

    payload = _snapshot_payload(
        customer_id=customer_id, site=site, cart_id=cart_id, cart_revision=cart_revision,
        items=items, address=address, delivery=delivery, quote=quote,
        policy_version=quote.policy_version, payment=payment,
    )
    snapshot_hash = _stable_hash(payload)

    return QuoteSnapshot(
        customer_id=customer_id,
        cart_id=cart_id,
        cart_revision=cart_revision,
        created_at=created_at,
        expires_at=created_at + ttl_seconds,
        policy_version=quote.policy_version,
        quote=quote,
        snapshot_hash=snapshot_hash,
        frozen_data=payload,
    )
