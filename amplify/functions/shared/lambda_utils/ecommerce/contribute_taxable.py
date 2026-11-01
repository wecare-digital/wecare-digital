"""Contribute: one server-owned ₹300 native-payment breakdown.

The public SKU keeps its ₹300 gross price. The amount is NOT read from the
browser's illustrative lines. The breakdown is purpose-specific and cannot
change Vault, Drop Docs, general carts, or the Meta-approved template body.

Activation is separately release-gated until finance/tax treatment and
invoice/capture consistency have been approved and checked.
"""
from __future__ import annotations

from lambda_utils.ecommerce import checkout_pricing, default_coupon

CATALOG_TOTAL_PAISE = 30000
ITEM_BASE_PAISE = 23541
EXPRESS_PAISE = 1500
SUPPLY_GST_BPS = 1800
POLICY = "contribute-taxable-review-2026-11-01"


def breakdown(catalog_price_paise: int) -> dict:
    """Calculate and prove every line in integer paise; reject catalog drift."""
    if type(catalog_price_paise) is not int or catalog_price_paise != CATALOG_TOTAL_PAISE:
        raise ValueError("Contribute catalog gross price is not exactly 30000 paise")
    supply_gst = checkout_pricing.round_half_up(ITEM_BASE_PAISE, SUPPLY_GST_BPS)
    gst_inclusive = ITEM_BASE_PAISE + supply_gst
    delight = default_coupon.delight_paise(gst_inclusive)
    collection = gst_inclusive - delight + EXPRESS_PAISE
    quote = checkout_pricing.compute_quote(collection, currency="INR")
    result = {
        "itemSubtotalPaise": ITEM_BASE_PAISE,
        "catalogGrossPaise": CATALOG_TOTAL_PAISE,
        "supplyGstPaise": supply_gst,
        "supplyGstBps": SUPPLY_GST_BPS,
        "delightPaise": delight,
        "expressPaise": EXPRESS_PAISE,
        "collectionBeforeConveniencePaise": quote.collection_before_convenience_paise,
        "convenienceFeePaise": quote.convenience_fee_paise,
        "convenienceGstPaise": quote.convenience_gst_paise,
        "convenienceGstBps": checkout_pricing.CONVENIENCE_GST_BPS,
        "totalPayablePaise": quote.total_payable_paise,
    }
    expected = (23541, 4237, 138, 1500, 29140, 729, 131, 30000)
    measured = (result["itemSubtotalPaise"], result["supplyGstPaise"],
                result["delightPaise"], result["expressPaise"],
                result["collectionBeforeConveniencePaise"],
                result["convenienceFeePaise"], result["convenienceGstPaise"],
                result["totalPayablePaise"])
    if measured != expected:
        raise ValueError("Contribute policy arithmetic changed; refusing to send")
    return result


__all__ = [
    "CATALOG_TOTAL_PAISE", "ITEM_BASE_PAISE", "EXPRESS_PAISE",
    "SUPPLY_GST_BPS", "POLICY", "breakdown",
]
