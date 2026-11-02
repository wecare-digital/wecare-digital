"""Unified WECARE Shop checkout pricing: GST-exclusive catalog bases.

This module is the one money policy for all customer shop SKUs except Contribute:
    ProductsTable base -> 18% supply GST -> Delight (0.5%, max Rs50)
    -> Rs25 Vault / Rs45 other Express ONCE per basket -> 2.5% convenience -> 18% GST on fee.

Contribute retains its exact Rs300 gross-target policy, including Rs15 Express,
in contribute_taxable.py. Internal Rs2 commerce QA bypasses this customer policy.

All computation uses integer paise. The browser never supplies monetary terms.
The immutable quote is shared across Razorpay, Meta native ORDER_DETAILS,
the payment attempt, final order and invoice.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict

from lambda_utils.ecommerce import (
    checkout_pricing, default_coupon, express_policy,
)

SUPPLY_GST_BPS = 1800
POLICY = "shop-gst-exclusive-vault-25-2026-11-02"


def price_components(item_subtotal_paise: int, *,
                     express_paise: int = express_policy.STANDARD_EXPRESS_PAISE) -> Dict[str, int]:
    """All six customer-visible money components from a GST-exclusive subtotal.

    Per-basket, NOT per-line: Delight cap and Express are applied exactly once.
    GST uses the checkout's ROUND_HALF_UP paise policy; Delight's existing
    integer floor and Rs50 cap are preserved.
    """
    if type(item_subtotal_paise) is not int or item_subtotal_paise <= 0:
        raise checkout_pricing.PricingError(
            "shop GST-exclusive subtotal must be positive integer paise")
    if type(express_paise) is not int or express_paise not in (
            express_policy.VAULT_EXPRESS_PAISE,
            express_policy.STANDARD_EXPRESS_PAISE):
        raise checkout_pricing.PricingError("unverified ordinary cart Express rate")
    gst = checkout_pricing.round_half_up(item_subtotal_paise, SUPPLY_GST_BPS)
    eligible_for_delight = item_subtotal_paise + gst
    delight = default_coupon.delight_paise(eligible_for_delight)
    express = express_paise
    collection = eligible_for_delight - delight + express
    quote = checkout_pricing.compute_quote(collection, currency="INR")
    return {
        "itemSubtotalPaise": item_subtotal_paise,
        "supplyGstPaise": gst,
        "supplyGstBps": SUPPLY_GST_BPS,
        "delightPaise": delight,
        "expressPaise": express,
        "collectionBeforeConveniencePaise": quote.collection_before_convenience_paise,
        "convenienceFeePaise": quote.convenience_fee_paise,
        "convenienceGstPaise": quote.convenience_gst_paise,
        "convenienceGstBps": checkout_pricing.CONVENIENCE_GST_BPS,
        "totalPayablePaise": quote.total_payable_paise,
    }


def quote_from_base_snapshot(base: Any) -> checkout_pricing.QuoteSnapshot:
    """Price a server-read cart and freeze its authoritative unified breakdown.

    Caller MUST first resolve live variant prices from ProductsTable using
    native_checkout.quote_native_cart(gst_bps=0, coupon_definition=None).
    It is a read-only source snapshot: any prior fee/tax/shipping is refused,
    rather than compounded or mistaken for taxable merchandise.
    """
    frozen = base.frozen_data
    if not isinstance(frozen, Mapping):
        raise checkout_pricing.PricingError("missing frozen catalog snapshot")
    rows = frozen.get("items")
    delivery = frozen.get("delivery")
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise checkout_pricing.PricingError("invalid frozen checkout items")
    if (not isinstance(delivery, Mapping)
            or type(delivery.get("paise")) is not int
            or delivery["paise"] != 0):
        raise checkout_pricing.PricingError("checkout base already includes delivery")
    if base.quote.currency != "INR":
        raise checkout_pricing.PricingError("shop prices require INR")

    subtotal = 0
    for line in rows:
        if not isinstance(line, Mapping):
            raise checkout_pricing.PricingError("invalid frozen cart line")
        qty = line.get("quantity")
        amount = line.get("unitPricePaise")
        if (type(qty) is not int or qty <= 0
                or type(amount) is not int or amount <= 0
                or not line.get("productId") or not line.get("variantId")):
            raise checkout_pricing.PricingError("invalid frozen line price or identity")
        subtotal += qty * amount
    if (base.quote.collection_before_convenience_paise != subtotal
            or subtotal <= 0):
        raise checkout_pricing.PricingError(
            "source snapshot is not an unadjusted catalog base")

    try:
        express = express_policy.frozen_customer_cart_express_paise(rows)
    except ValueError as exc:
        raise checkout_pricing.PricingError(str(exc)) from exc
    parts = price_components(subtotal, express_paise=express)
    collection = parts["collectionBeforeConveniencePaise"]
    quote = checkout_pricing.compute_quote(
        collection, currency="INR",
        buyer_gstin=base.quote.buyer_gstin,
        intra_state=base.quote.convenience_gst_split.intra_state,
    )
    if quote.total_payable_paise != parts["totalPayablePaise"]:
        raise checkout_pricing.PricingError("unified quote failed to reconcile")

    return checkout_pricing.build_snapshot(
        customer_id=base.customer_id,
        cart_id=base.cart_id,
        cart_revision=base.cart_revision,
        quote=quote,
        created_at=base.created_at,
        ttl_seconds=base.expires_at - base.created_at,
        site=frozen.get("site"),
        items=rows,
        address=frozen.get("address"),
        delivery={"paise": parts["expressPaise"], "optionId": "express"},
        pricing_metadata={
            "policy": POLICY,
            "supplyGstPaise": parts["supplyGstPaise"],
            "supplyGstBps": SUPPLY_GST_BPS,
            "discountPaise": parts["delightPaise"],
            "expressPaise": parts["expressPaise"],
        },
    )


__all__ = ["POLICY", "SUPPLY_GST_BPS", "price_components", "quote_from_base_snapshot"]
