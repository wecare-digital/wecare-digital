"""AWS-native supply pricing — the one integer Wix still owns, computed natively.

WHAT THIS REPLACES, EXACTLY.
Today the checkout's "collection total" (subtotal − discount + delivery +
additionalFees + supply tax) is computed by Wix: `cart_v2.calculate` returns a
`priceSummary` and `wix_ecom.authoritative_total_paise` reads
`priceSummary.total.amount`. That single integer, `collection_before_convenience
_paise`, is then handed to the ALREADY-NATIVE `checkout_pricing.compute_quote`,
which adds the convenience fee + GST-on-fee and produces the amount Razorpay
charges. So the only thing Wix still owns on the money path is the supply total.

This module computes that supply total from an AWS product catalog, producing the
SAME `priceSummary` shape and enforcing the SAME identity Wix's `calculate`
asserts, so the output is a drop-in for `authoritative_total_paise` and nothing
downstream (`compute_quote`, `website_checkout`, `order_creation`, `finalization`)
has to change.

INVARIANTS (identical to the Wix contract cart_v2.calculate re-validates):
    sum(line.total_paise)            == subtotal_paise
    subtotal - discount + delivery + additional_fees + tax == total
    every amount is a nonnegative integer number of paise (never float)
    prices are authoritative server-side; a client-supplied price is ignored.

This module is PURE and has NO AWS/Wix I/O: it takes already-resolved catalog
lines (price + quantity from the authoritative ProductsTable read, done by the
caller) and a tax/discount/delivery input, and returns a priceSummary. That keeps
it unit-testable with synthetic fixtures and keeps the catalog read, which is
I/O, in one place. It is NOT wired into any handler yet — flipping checkout to use
it is CHECKOUT_MODE=AWS_NATIVE, an owner-gated production change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from lambda_utils.ecommerce.money import Money, positive_paise


class CatalogPricingError(ValueError):
    """Supply pricing could not be computed. A subclass of ValueError so existing
    callers that catch ValueError keep working, but a distinct type for this path."""


def _nonneg_paise(value: Any, what: str) -> int:
    """A nonnegative integer paise (0 allowed — a free line / no discount is valid).

    `positive_paise` rejects zero; discount/delivery/tax and a zero-price line are
    legitimately zero, so this is the zero-tolerant sibling with the same float and
    fractional-paise rejection.
    """
    if isinstance(value, bool):
        raise CatalogPricingError(f"{what} must be integer paise, not a bool")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise CatalogPricingError(f"{what} must be a whole number of paise")
        value = int(value)
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise CatalogPricingError(f"{what} must be a nonnegative integer paise")
    return value


@dataclass(frozen=True)
class CatalogLine:
    """One resolved, authoritative line. `unit_price_paise` comes from the
    ProductsTable read, NEVER from the client. `quantity` is 1..100000, matching
    the bound `cart_v2.resolved_catalog_lines` enforces."""

    product_id: str
    variant_id: str
    quantity: int
    unit_price_paise: int
    requires_delivery: bool = True  # fail-closed to physical, like Cart V2

    def __post_init__(self) -> None:
        if not self.product_id or not self.variant_id:
            raise CatalogPricingError("a catalog line needs a product id and a variant id")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 100000:
            raise CatalogPricingError("quantity must be an integer in 1..100000")
        _nonneg_paise(self.unit_price_paise, "unit_price_paise")

    @property
    def total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


@dataclass(frozen=True)
class PriceSummary:
    """The same shape Wix's priceSummary carries, in integer paise. `as_wix_shape`
    renders the exact decimal-string envelope `authoritative_total_paise` reads, so
    the native path can feed the identical downstream code."""

    subtotal_paise: int
    discount_paise: int
    delivery_paise: int
    additional_fees_paise: int
    tax_paise: int

    def __post_init__(self) -> None:
        for name in ("subtotal_paise", "discount_paise", "delivery_paise",
                     "additional_fees_paise", "tax_paise"):
            _nonneg_paise(getattr(self, name), name)
        if self.discount_paise > self.subtotal_paise:
            raise CatalogPricingError("discount cannot exceed subtotal")

    @property
    def total_paise(self) -> int:
        # The Wix identity, computed once and asserted by construction.
        return (self.subtotal_paise - self.discount_paise + self.delivery_paise
                + self.additional_fees_paise + self.tax_paise)

    def as_wix_shape(self) -> Dict[str, Dict[str, str]]:
        """Render as Wix's `priceSummary` so `wix_ecom.authoritative_total_paise`
        and any `priceSummary`-shaped consumer accept it unchanged."""
        def amt(p: int) -> Dict[str, str]:
            return {"amount": Money(p).to_wix()}
        return {
            "subtotal": amt(self.subtotal_paise),
            "discount": amt(self.discount_paise),
            "shipping": amt(self.delivery_paise),
            "additionalFees": amt(self.additional_fees_paise),
            "tax": amt(self.tax_paise),
            "total": amt(self.total_paise),
        }


def build_price_summary(
    lines: Sequence[CatalogLine],
    *,
    discount_paise: int = 0,
    delivery_paise: int = 0,
    additional_fees_paise: int = 0,
    tax_paise: int = 0,
) -> PriceSummary:
    """Compute the authoritative supply priceSummary from resolved catalog lines.

    `subtotal = sum(line.total_paise)` — the same per-line identity Cart V2 checks.
    All adjustments are inputs (resolved upstream: coupon via
    `coupon_store.discount_paise`, delivery via the shipping resolver, tax via the
    place-of-supply GST build). This function owns the ARITHMETIC and the
    invariants, not the policy of how each component was derived.
    """
    if not lines:
        raise CatalogPricingError("cannot price an empty cart")
    subtotal = 0
    for line in lines:
        subtotal += line.total_paise
    summary = PriceSummary(
        subtotal_paise=subtotal,
        discount_paise=_nonneg_paise(discount_paise, "discount_paise"),
        delivery_paise=_nonneg_paise(delivery_paise, "delivery_paise"),
        additional_fees_paise=_nonneg_paise(additional_fees_paise, "additional_fees_paise"),
        tax_paise=_nonneg_paise(tax_paise, "tax_paise"),
    )
    # Positivity of the final total is the caller's concern (a zero-total quote is
    # legitimate, mirroring checkout_pricing); but a negative total is impossible
    # by construction because discount <= subtotal and every other term >= 0.
    return summary


def authoritative_total_paise(summary: PriceSummary) -> int:
    """The native counterpart of `wix_ecom.authoritative_total_paise`: the single
    integer `checkout_pricing.compute_quote` consumes as
    `collection_before_convenience_paise`. Validated as a clean whole paise, same
    as the Wix path refuses a fractional-paise total."""
    return _nonneg_paise(summary.total_paise, "total_paise")
