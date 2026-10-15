"""AWS-native supply pricing — the checkout's collection total, from ProductsTable.

WHAT THIS COMPUTES, EXACTLY.
The checkout's "collection total" (subtotal − discount + delivery + additionalFees +
supply tax) is computed here from the authoritative ProductsTable prices.
`authoritative_total_paise` returns that single integer,
`collection_before_convenience_paise`, which `native_checkout.quote_native_cart`
hands to `checkout_pricing.compute_quote`; that adds the convenience fee +
GST-on-fee and produces the amount Razorpay charges. Everything downstream
(`compute_quote`, `website_checkout`, `order_creation`, `finalization`) reads the
frozen quote built from it.

INVARIANTS:
    sum(line.total_paise)            == subtotal_paise
    subtotal - discount + delivery + additional_fees + tax == total
    every amount is a nonnegative integer number of paise (never float)
    prices are authoritative server-side; a client-supplied price is ignored.

This module is PURE and has NO I/O: it takes already-resolved catalog lines
(price + quantity from the authoritative ProductsTable read, done by the caller)
and a tax/discount/delivery input, and returns a `PriceSummary`. That keeps it
unit-testable with synthetic fixtures and keeps the catalog read, which is I/O,
in one place. `native_checkout` is the production caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence

from lambda_utils.ecommerce.money import positive_paise


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
    the per-line bound the checkout's native quote enforces."""

    product_id: str
    variant_id: str
    quantity: int
    unit_price_paise: int
    requires_delivery: bool = True  # fail-closed to physical

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
    """The supply price summary, in integer paise. `authoritative_total_paise`
    reads its `total_paise`."""

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
        # The total identity, computed once and asserted by construction.
        return (self.subtotal_paise - self.discount_paise + self.delivery_paise
                + self.additional_fees_paise + self.tax_paise)


def build_price_summary(
    lines: Sequence[CatalogLine],
    *,
    discount_paise: int = 0,
    delivery_paise: int = 0,
    additional_fees_paise: int = 0,
    tax_paise: int = 0,
) -> PriceSummary:
    """Compute the authoritative supply priceSummary from resolved catalog lines.

    `subtotal = sum(line.total_paise)` — the per-line identity every summary carries.
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


def supply_tax_paise(
    taxable_paise: int,
    *,
    gst_bps: int,
    intra_state: bool,
) -> "SupplyTax":
    """Compute supply GST on a GST-EXCLUSIVE taxable base, split CGST/SGST or IGST.

    REUSES the existing `checkout_pricing` primitives — `round_half_up` for the
    exact integer-paise GST and `split_gst` for the CGST/SGST-vs-IGST
    reconciliation — so the supply tax and the fee tax share one arithmetic and
    one rounding rule. No float.

    THE TAX BASIS IS EXPLICIT AND MATTERS. The current ProductsTable catalog
    prices are GST-INCLUSIVE. So the native path must NOT add GST on top of an
    inclusive price —
    that is the double-tax defect `checkout_pricing` already refuses for the fee.
    This helper assumes a GST-EXCLUSIVE `taxable_paise`; a caller holding
    inclusive prices passes `gst_bps=0` (tax already in the line price) and the
    result is a zero tax line. Choosing the basis is a deliberate wiring decision,
    not a default, which is why `price_cart` defaults `tax_paise=0`.
    """
    from lambda_utils.ecommerce import checkout_pricing
    base = _nonneg_paise(taxable_paise, "taxable_paise")
    if type(gst_bps) is not int or not 0 <= gst_bps <= 10000:
        raise CatalogPricingError("gst_bps must be an integer in 0..10000 basis points")
    gst = checkout_pricing.round_half_up(base, gst_bps)
    split = checkout_pricing.split_gst(gst, intra_state=intra_state)
    return SupplyTax(
        gst_paise=gst,
        cgst_paise=split.cgst_paise,
        sgst_paise=split.sgst_paise,
        igst_paise=split.igst_paise,
        intra_state=intra_state,
    )


@dataclass(frozen=True)
class SupplyTax:
    """Supply GST split, reconciling exactly to gst_paise (reuses checkout_pricing.TaxSplit's
    invariant). Separate from the convenience-fee GST, which stays in checkout_pricing."""

    gst_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    intra_state: bool

    def __post_init__(self) -> None:
        for name in ("gst_paise", "cgst_paise", "sgst_paise", "igst_paise"):
            _nonneg_paise(getattr(self, name), name)
        if self.cgst_paise + self.sgst_paise + self.igst_paise != self.gst_paise:
            raise CatalogPricingError("supply GST split does not reconcile to gst_paise")


def coupon_discount_paise(
    coupon_definition: Optional[Mapping[str, Any]],
    *,
    subtotal_paise: int,
) -> int:
    """Native coupon discount for a cart, from the AWS-authoritative definition.

    The AWS-authoritative coupon *definition* lives in `coupon_store`, and
    `coupon_store.discount_paise` renders a discount from it (Pay Flow invoices use
    the same renderer). This function is the single bridge that lets the native
    checkout path render that SAME discount against the native subtotal — so the
    discount is decided by the AWS definition, never by the browser, preserving
    the "validate returns a verdict, pricing is server-side" boundary.

    `coupon_definition` is the already-loaded, already-ELIGIBLE definition row
    (eligibility is `coupon_store.evaluate`'s separate job; this is arithmetic
    only). A None definition means no coupon → zero discount. The discount is
    clamped at the subtotal by `coupon_store.discount_paise` itself, so it can
    never make the collection negative.

    Imported lazily so this pure pricing module carries no hard dependency on the
    coupon store for callers that never apply a coupon, and so the two modules do
    not form an import cycle.
    """
    _nonneg_paise(subtotal_paise, "subtotal_paise")
    if coupon_definition is None:
        return 0
    from lambda_utils.ecommerce import coupon_store
    discount = coupon_store.discount_paise(
        dict(coupon_definition), collection_paise=subtotal_paise
    )
    # Defensive: coupon_store already clamps, but the pricing identity depends on
    # discount <= subtotal, so assert it here too rather than trust the caller.
    return _nonneg_paise(min(int(discount), subtotal_paise), "coupon_discount_paise")


def price_cart(
    lines: Sequence[CatalogLine],
    *,
    coupon_definition: Optional[Mapping[str, Any]] = None,
    delivery_paise: int = 0,
    additional_fees_paise: int = 0,
    tax_paise: int = 0,
) -> PriceSummary:
    """End-to-end native cart pricing: subtotal from lines, discount from the AWS
    coupon definition, plus delivery/fees/tax → the authoritative supply summary.

    This is the full native cart calculation. The resulting `total_paise` is the
    exact integer `checkout_pricing.compute_quote` expects, so the native checkout
    path is:

        summary = price_cart(lines, coupon_definition=..., delivery_paise=...)
        collection = authoritative_total_paise(summary)
        quote = checkout_pricing.compute_quote(collection)   # fee + GST unchanged
    """
    subtotal = sum(line.total_paise for line in lines) if lines else 0
    discount = coupon_discount_paise(coupon_definition, subtotal_paise=subtotal)
    return build_price_summary(
        lines,
        discount_paise=discount,
        delivery_paise=delivery_paise,
        additional_fees_paise=additional_fees_paise,
        tax_paise=tax_paise,
    )


def authoritative_total_paise(summary: PriceSummary) -> int:
    """The authoritative supply total: the single integer
    `checkout_pricing.compute_quote` consumes as
    `collection_before_convenience_paise`. Validated as a clean whole paise; a
    fractional-paise total is refused."""
    return _nonneg_paise(summary.total_paise, "total_paise")
