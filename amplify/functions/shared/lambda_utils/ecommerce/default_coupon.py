"""The always-on "Delight" discount: 0.5% of the collection, capped at ₹50. Hard-coded, standalone.

Why this module exists
----------------------
The owner's rule is that EVERY order carries one small goodwill discount by default -- 0.5% off,
never more than ₹50 -- auto-applied on BOTH the website and the WhatsApp checkout paths. There is
no coupon system and no gift-card system any more: Delight is a FIXED policy baked into code, not a
row in any table, not something a customer types, and not something staff can edit. This module is
its ONE home: the single integer-paise computation and the one definition both pricing paths read.

Standalone by design
--------------------
This module reads no table and imports no coupon engine. The discount is pure integer arithmetic
(basis points over the collection, clamped by the cap and by the collection itself), so there is
exactly one place the figure is decided and nothing it can drift from.

The rate is NEVER shown to the customer
---------------------------------------
`DISPLAY_LABEL` is the only customer-facing string. The 0.5% rate and the ₹50 cap are internal
mechanics; every surface prints "Delight" and the rupee amount, never the percent.
"""
from __future__ import annotations

from typing import Any, Dict

#: The customer-facing label. The ONLY string any surface prints for this discount; the rate and
#: the cap are internal and must never appear next to it.
DISPLAY_LABEL = "Delight"

#: Stored on the invoice/order row so a receipt can name the discount line. Upper-cased on write.
DELIGHT_CODE = "DELIGHT"

#: GST/accounting treatment for the fixed goodwill reduction.
#:
#: Delight is computed from the GST-inclusive eligible-goods value so the CUSTOMER saving is the
#: same on every channel. It is then applied AFTER supply GST for accounting: it reduces the
#: collection and therefore the convenience-fee base, but it does not silently rewrite the supply
#: GST that was computed from the item tax rates. This makes mixed-rate invoices deterministic
#: and keeps the customer-visible Delight figure equal to the actual reduction in amount payable.
#: Internal invoice/tax snapshots persist this literal so filing/review code never has to infer the
#: treatment from arithmetic.
DELIGHT_TAX_TREATMENT = "POST_TAX_COMMERCIAL_DISCOUNT"

#: 100 paise to the rupee. Local, so this module depends on nothing else for its arithmetic.
PAISE_PER_RUPEE = 100

#: 0.5% == 50 basis points. (An earlier revision stored 5 bps == 0.05%, a tenfold under-discount.)
#: A sub-percent rate is fine because the cap below bounds the payout.
DELIGHT_PERCENT_OFF_BPS = 50

#: Basis-point denominator: 10000 bps == 100%. `bps / 10000` is the fraction of the collection.
_BPS_DENOMINATOR = 10000

#: ₹50 ceiling, in whole-rupee paise. The discount is never more than this however large the cart.
DELIGHT_MAXIMUM_DISCOUNT_PAISE = 50 * PAISE_PER_RUPEE


def delight_paise(collection_paise: int) -> int:
    """The Delight discount in integer paise for a collection. Zero only for zero/empty collection.

    THE ONE PLACE THIS FIGURE IS DECIDED. Pure integer arithmetic, no float, no table, no coupon
    engine:

        0.5% of the collection  ==  collection_paise * 50 // 10000

    then clamped by the ₹50 cap AND by the collection itself (a discount can never exceed what is
    being bought, so it can never make a total negative). Integer floor division matches how the
    retired `coupon_store` priced a PERCENT_OFF coupon, so the figure is identical to the one the
    old path produced for the same rate -- only the cap changed (₹100 -> ₹50) and the dependency
    on the coupon store is gone.
    """
    collection = int(collection_paise)
    if collection <= 0:
        return 0
    raw = collection * DELIGHT_PERCENT_OFF_BPS // _BPS_DENOMINATOR
    # "Every order carries Delight" must remain true even for a tiny controlled QA/payment.
    # Integer flooring makes 0.5% of values below ₹2 become zero paise, which silently removes
    # the customer-visible Delight row. Keep the percentage/cap policy but guarantee one paise
    # whenever the eligible collection is positive.
    effective = max(1, raw)
    return min(effective, DELIGHT_MAXIMUM_DISCOUNT_PAISE, collection)


def delight_definition() -> Dict[str, Any]:
    """The in-memory Delight definition the native checkout pricing path passes through.

    A small descriptor the native cart (`catalog_pricing.coupon_discount_paise` →
    `native_checkout.quote_native_cart`) reads to signal "apply Delight". It carries the code, the
    label and the policy figures; `catalog_pricing` applies `delight_paise` to the collection, so
    both the website/WhatsApp native path and the invoice path price the SAME figure from the SAME
    computation. Returned fresh each call so a caller that mutates its copy cannot poison the next
    quote.
    """
    return {
        "code": DELIGHT_CODE,
        "name": DISPLAY_LABEL,
        "percentOffBps": DELIGHT_PERCENT_OFF_BPS,
        "maximumDiscountPaise": DELIGHT_MAXIMUM_DISCOUNT_PAISE,
    }


__all__ = [
    "DELIGHT_CODE",
    "DELIGHT_TAX_TREATMENT",
    "DELIGHT_MAXIMUM_DISCOUNT_PAISE",
    "DELIGHT_PERCENT_OFF_BPS",
    "DISPLAY_LABEL",
    "PAISE_PER_RUPEE",
    "delight_definition",
    "delight_paise",
]
