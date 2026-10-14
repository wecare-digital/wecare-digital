"""Compose the native supply pieces into a QuoteSnapshot — the AWS-native
counterpart of the Wix snapshot-building branch in checkout/handler.py.

This is the single orchestration seam the checkout handler calls when
CHECKOUT_MODE=AWS_NATIVE, so the handler's native branch stays a few lines and
all the composition is unit-testable here, off the live payment path.

The chain, with NO Wix anywhere:
    native_cart.to_catalog_lines(cart)                       # lines (server prices)
    native_inventory.validate_lines(...)                     # fail-closed stock check
    native_shipping.resolve_delivery_paise(...)              # delivery charge
    catalog_pricing.coupon_discount_paise(...)               # discount (AWS coupon def)
    catalog_pricing.supply_tax_paise(...)                    # supply GST (0 for inclusive)
    catalog_pricing.price_cart(...)                          # the priceSummary + total
    catalog_pricing.authoritative_total_paise(summary)       # collection_before_convenience
    checkout_pricing.compute_quote(collection)               # + convenience fee + GST
    checkout_pricing.build_snapshot(...)                     # the immutable QuoteSnapshot

The payment amount is the native quote's total (identical downstream handling to
the Wix path). Prices are server-authoritative; a client value never enters. The
snapshot's `site` is tagged `aws-native` so a persisted amount is traceable to the
native policy, not Wix.

Stock reservation is performed by the CALLER around payment initiation (reserve
before creating the gateway order, release on failure), not here — this function
only PRICES and VALIDATES, so it is side-effect-free and safe to call repeatedly.

NOT WIRED until the handler gates on CHECKOUT_MODE=AWS_NATIVE (owner-gated).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from lambda_utils.ecommerce import (
    catalog_pricing,
    checkout_pricing,
    native_cart,
    native_inventory,
    native_shipping,
)

SITE_TAG = "aws-native"


def quote_native_cart(
    cart: Mapping[str, Any],
    *,
    product_reader: Callable[[str], Optional[Mapping[str, Any]]],
    customer_id: str,
    created_at: int,
    ttl_seconds: int,
    shipping_policy: native_shipping.ShippingPolicy,
    coupon_definition: Optional[Mapping[str, Any]] = None,
    gst_bps: int = 0,
    intra_state: bool = True,
    delivery_option_id: Optional[str] = None,
    validate_stock: bool = True,
) -> checkout_pricing.QuoteSnapshot:
    """Price a native cart into a QuoteSnapshot. Side-effect-free (no reservation).

    `gst_bps=0` is the default because the catalog prices are GST-INCLUSIVE today
    (so supply GST is already in the line price and must not be added again). A
    future GST-exclusive catalog passes the real rate.
    """
    lines = native_cart.to_catalog_lines(cart)
    if not lines:
        raise catalog_pricing.CatalogPricingError("cannot quote an empty cart")

    if validate_stock:
        native_inventory.validate_lines(
            product_reader,
            [{"product_id": ln.product_id, "variant_id": ln.variant_id,
              "quantity": ln.quantity} for ln in lines],
        )

    subtotal = sum(ln.total_paise for ln in lines)
    delivery = native_shipping.resolve_delivery_paise(
        lines, subtotal, shipping_policy, option_id=delivery_option_id)
    discount = catalog_pricing.coupon_discount_paise(coupon_definition, subtotal_paise=subtotal)
    taxable = subtotal - discount
    tax = catalog_pricing.supply_tax_paise(taxable, gst_bps=gst_bps, intra_state=intra_state)

    summary = catalog_pricing.price_cart(
        lines,
        coupon_definition=coupon_definition,
        delivery_paise=delivery,
        tax_paise=tax.gst_paise,
    )
    collection = catalog_pricing.authoritative_total_paise(summary)
    quote = checkout_pricing.compute_quote(collection, currency="INR")

    return checkout_pricing.build_snapshot(
        customer_id=customer_id,
        cart_id=str(cart.get("cartId") or ""),
        cart_revision=int(cart.get("updatedAt") or 0),
        quote=quote,
        created_at=created_at,
        ttl_seconds=ttl_seconds,
        site=SITE_TAG,
        items=[{"productId": ln.product_id, "variantId": ln.variant_id,
                "quantity": ln.quantity, "unitPricePaise": ln.unit_price_paise}
               for ln in lines],
        address=None,
        delivery={"paise": delivery, "optionId": delivery_option_id or "resolved"},
    )


__all__ = ["SITE_TAG", "quote_native_cart"]
