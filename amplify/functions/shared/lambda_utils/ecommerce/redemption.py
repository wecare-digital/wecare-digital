"""Server-authoritative coupon redemption.

Gift cards were retired from WECARE.DIGITAL. This module now owns only coupon
validation and pricing. Coupon amounts remain integer paise and are never trusted
from browser input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

REDEMPTION_CURRENCY = "INR"
_MAX_PAISE = 9007199254740991

COUPON_APPLIED = "APPLIED"
COUPON_INVALID = "INVALID"
COUPON_EXPIRED = "EXPIRED"
COUPON_INELIGIBLE = "INELIGIBLE"


class RedemptionError(ValueError):
    """A coupon redemption could not be computed from the given inputs."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CouponAuthority:
    """Server-authoritative coupon verdict and discount in integer paise."""

    valid: bool
    reason: str
    discount_paise: int = 0


class RedemptionProvider(Protocol):
    """Abstract coupon authority."""

    def validate_coupon(self, *, code: str, collection_before_discount_paise: int,
                        cart_ref: str) -> CouponAuthority:
        ...


@dataclass(frozen=True)
class CouponResult:
    """Server-authoritative result of applying a coupon."""

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
    """Apply a coupon server-authoritatively and return the discounted collection."""
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
        reason = authority.reason if authority.reason in (
            COUPON_INVALID, COUPON_EXPIRED, COUPON_INELIGIBLE) else COUPON_INVALID
        return CouponResult(reason=reason, discount_paise=0,
                            collection_before_discount_paise=collection,
                            discounted_collection_paise=collection)

    discount = authority.discount_paise
    if isinstance(discount, bool) or type(discount) is not int or discount < 0:
        return CouponResult(reason=COUPON_INVALID, discount_paise=0,
                            collection_before_discount_paise=collection,
                            discounted_collection_paise=collection)

    discount = min(discount, collection)
    return CouponResult(reason=COUPON_APPLIED, discount_paise=discount,
                        collection_before_discount_paise=collection,
                        discounted_collection_paise=collection - discount)


__all__ = [
    "REDEMPTION_CURRENCY",
    "COUPON_APPLIED",
    "COUPON_INVALID",
    "COUPON_EXPIRED",
    "COUPON_INELIGIBLE",
    "RedemptionError",
    "CouponAuthority",
    "RedemptionProvider",
    "CouponResult",
    "apply_coupon",
]
