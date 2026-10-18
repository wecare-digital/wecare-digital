"""Coupon-store binding for the shared redemption authority.

Gift-card storage and redemption were retired. This provider now binds only the
coupon definition store to the coupon-only redemption module.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

from lambda_utils.ecommerce import coupon_store, redemption

logger = logging.getLogger(__name__)

COUPON_REASON_BY_VERDICT: Dict[str, str] = {
    coupon_store.UNKNOWN_CODE: redemption.COUPON_INVALID,
    coupon_store.EXPIRED: redemption.COUPON_EXPIRED,
    coupon_store.NOT_STARTED: redemption.COUPON_EXPIRED,
    coupon_store.NOT_ACTIVE: redemption.COUPON_INELIGIBLE,
    coupon_store.USAGE_LIMIT_REACHED: redemption.COUPON_INELIGIBLE,
    coupon_store.CUSTOMER_LIMIT_REACHED: redemption.COUPON_INELIGIBLE,
    coupon_store.HELD_BY_ANOTHER_CART: redemption.COUPON_INELIGIBLE,
}

Clock = Callable[[], int]


def _default_clock() -> int:
    return int(time.time())


class StoreRedemptionProvider:
    """redemption.RedemptionProvider over the coupon table."""

    def __init__(self, *, coupons_table: Any, customer_id: Optional[str] = None,
                 clock: Clock = _default_clock) -> None:
        self._coupons_table = coupons_table
        self._customer_id = customer_id
        self._clock = clock

    def validate_coupon(self, *, code: str, collection_before_discount_paise: int,
                        cart_ref: str) -> redemption.CouponAuthority:
        try:
            normalised = coupon_store.normalise_code(code)
        except coupon_store.CouponValidationError:
            return redemption.CouponAuthority(valid=False, reason=redemption.COUPON_INVALID)

        definition = coupon_store.get_definition(self._coupons_table, normalised)
        uses = 0
        if definition is not None and self._customer_id is not None:
            uses = coupon_store.customer_uses(
                self._coupons_table, normalised, self._customer_id)
        verdict = coupon_store.evaluate(
            definition, cart_id=cart_ref, customer_uses_count=uses, clock=self._clock)

        if verdict != coupon_store.ELIGIBLE:
            logger.info("coupon refused: code=%s verdict=%s cart=%s",
                        normalised, verdict, cart_ref)
            return redemption.CouponAuthority(
                valid=False, reason=COUPON_REASON_BY_VERDICT[verdict])

        amount = coupon_store.discount_paise(
            definition, collection_paise=collection_before_discount_paise)
        logger.info("coupon applied: code=%s discountPaise=%s cart=%s",
                    normalised, amount, cart_ref)
        return redemption.CouponAuthority(
            valid=True, reason=redemption.COUPON_APPLIED, discount_paise=amount)


__all__ = [
    "COUPON_REASON_BY_VERDICT",
    "StoreRedemptionProvider",
]
