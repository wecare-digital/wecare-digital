"""The always-on "Delight" discount: 0.5% of the collection, capped at ₹100, rate never shown.

Why this module exists
----------------------
The owner's rule is that EVERY order carries a small goodwill discount by default -- 0.5% off,
never more than ₹100 -- auto-applied on both the website and the WhatsApp paths, unless the
customer has a better explicit coupon. This module is the ONE runtime home for that definition and
the precedence rule. It holds no state, reads no table, and renders no amount itself: the amount is
computed by `coupon_store.discount_paise` (the single discount renderer) so there is never a second
discount engine to drift from the first.

`scripts/seed_delight_coupon.py` writes the matching durable `CouponsTable` row (for the staff
coupon list, the audit trail, and so `DELIGHT` resolves if ever typed as an explicit code). The
seed payload is produced HERE (`seed_payload`) so the durable row and the runtime default cannot
disagree.

The rate is NEVER shown to the customer
---------------------------------------
`DISPLAY_LABEL` is the only customer-facing string. The 0.5% rate and the ₹100 cap are internal
mechanics; every surface prints "Delight discount" and the rupee amount, never the percent.

Auto-apply vs a better explicit coupon
--------------------------------------
`choose_definition(explicit, collection_paise=...)` returns the single definition a path should
price: the explicit coupon when it discounts at least as much at this collection, otherwise the
Delight default. It never stacks the two -- a path applies exactly one coupon definition, so the
customer gets the better of the two, never both summed.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from . import coupon_store

#: The customer-facing label. The ONLY string any surface prints for this discount; the rate and
#: the cap are internal and must never appear next to it.
DISPLAY_LABEL = "Delight discount"

#: Issued code. `coupon_store.normalise_code` upper-cases it, so the durable row's key is
#: `COUPON#DELIGHT` whether seeded as "Delight" or "DELIGHT".
DELIGHT_CODE = "Delight"

#: 0.5% == 50 basis points. (An earlier revision stored 5 bps == 0.05%, a tenfold
#: under-discount.) Permitted as a sub-percent rate because the cap below bounds the payout.
DELIGHT_PERCENT_OFF_BPS = 50

#: ₹100 ceiling, in whole-rupee paise.
DELIGHT_MAXIMUM_DISCOUNT_PAISE = 100 * coupon_store.PAISE_PER_RUPEE

#: 17 Oct 2026 00:00 IST, matching the durable seed row. A goodwill default is active from the
#: start; a seeder may override it.
DELIGHT_START_TIME_MS = 1792175400000


def delight_definition() -> Dict[str, Any]:
    """The in-memory Delight definition row the pricing path prices against.

    Returned fresh each call (never a shared mutable) so a caller that mutates its copy cannot
    poison the next quote. Shaped exactly as `coupon_store.discount_paise` reads: a `PERCENT_OFF`
    kind carrying `percentOffBps` and `maximumDiscountPaise`.

    Deliberately NOT loaded from the CouponsTable on the hot path: the default must price an order
    even if the table read fails, and it is a fixed owner policy rather than a staff-edited
    campaign. `seed_payload` writes the matching durable row; a test pins the two equal.
    """
    return {
        "code": DELIGHT_CODE,
        "name": DISPLAY_LABEL,
        "discountKind": coupon_store.PERCENT_OFF,
        "percentOffBps": DELIGHT_PERCENT_OFF_BPS,
        "maximumDiscountPaise": DELIGHT_MAXIMUM_DISCOUNT_PAISE,
        "currency": coupon_store.CURRENCY,
    }


def seed_payload() -> Dict[str, Any]:
    """The create payload that seeds the durable Delight row in the CouponsTable.

    Carries `scopeNamespace: "stores"` so the create passes the `SCOPE_OR_MINIMUM_SUBTOTAL_REQUIRED`
    rule (the discount is site-wide), and the start time the policy began. Idempotent at the store
    layer: a second create raises `CouponConflict`, which the seeder treats as "already present".
    """
    return {
        "code": DELIGHT_CODE,
        "name": DISPLAY_LABEL,
        "discountKind": coupon_store.PERCENT_OFF,
        "percentOffBps": DELIGHT_PERCENT_OFF_BPS,
        "maximumDiscountPaise": DELIGHT_MAXIMUM_DISCOUNT_PAISE,
        "scopeNamespace": "stores",
        "startTimeMs": DELIGHT_START_TIME_MS,
        "currency": coupon_store.CURRENCY,
    }


def delight_paise(collection_paise: int) -> int:
    """The Delight discount for a collection, through the ONE renderer. Zero for a zero collection.

    A thin DELEGATING wrapper over `coupon_store.discount_paise(delight_definition(), ...)` so
    callers do not re-read the definition shape; it performs no coupon arithmetic of its own.
    Named `delight_paise` rather than `discount_paise` precisely because it is not a second
    discount authority -- `coupon_store.discount_paise` remains the one place a coupon is priced.
    Clamped at the collection and capped at ₹100 inside that renderer.
    """
    return coupon_store.discount_paise(delight_definition(), collection_paise=collection_paise)


def choose_definition(
    explicit_definition: Optional[Mapping[str, Any]],
    *,
    collection_paise: int,
) -> Dict[str, Any]:
    """The single coupon definition a path should price, given the customer's explicit coupon.

    Returns the Delight default when no explicit coupon is in play; otherwise returns whichever of
    the two discounts MORE at `collection_paise`, so the default never leaves a customer worse off
    than the coupon they chose and a chosen coupon that beats the default is honoured. Never stacks
    them -- the caller prices exactly ONE returned definition.

    `collection_paise` is required: "which coupon is better" has no answer without the amount both
    are measured against.
    """
    default = delight_definition()
    if explicit_definition is None:
        return default
    explicit = dict(explicit_definition)
    try:
        explicit_discount = coupon_store.discount_paise(
            explicit, collection_paise=collection_paise)
    except coupon_store.CouponError:
        # An explicit coupon that cannot be priced against this collection (unmet minimum,
        # unsupported kind) is not better than the default; fall back rather than refuse the
        # whole order over an inapplicable code.
        return default
    default_discount = coupon_store.discount_paise(default, collection_paise=collection_paise)
    return explicit if explicit_discount >= default_discount else default


__all__ = [
    "DELIGHT_CODE",
    "DELIGHT_MAXIMUM_DISCOUNT_PAISE",
    "DELIGHT_PERCENT_OFF_BPS",
    "DELIGHT_START_TIME_MS",
    "DISPLAY_LABEL",
    "choose_definition",
    "delight_definition",
    "delight_paise",
    "seed_payload",
]
