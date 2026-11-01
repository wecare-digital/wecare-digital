"""Staff-native Contribute guard: EXACT single-item, fee-exempt ₹300 checkout.

This is a pure validation module. It has no network, IAM or payment-side effects.
Both the preclaim check and _create's last-before-write gate MUST call the same
validator, because the live ProductsTable price can change between reads.
"""
from __future__ import annotations

from typing import Any, Mapping

STAFF_CONTRIBUTION_TOTAL_PAISE = 30000
STAFF_CONTRIBUTION_POLICY = "contribution-exempt-2026-10-30"


def valid_staff_contribution_snapshot(
    snapshot: Any, *, product_id: str, variant_id: str
) -> bool:
    """True only if the frozen native quote is the single ₹300 exempt SKU.

    Fail closed on absent/inconsistent fields, floats, price drift, GST,
    Delight, Express, shipping or fee. Never accept the UI's amount.
    """
    try:
        quote = snapshot.quote
        if (
            type(quote.total_payable_paise) is not int
            or quote.total_payable_paise != STAFF_CONTRIBUTION_TOTAL_PAISE
            or type(quote.collection_before_convenience_paise) is not int
            or quote.collection_before_convenience_paise != STAFF_CONTRIBUTION_TOTAL_PAISE
            or quote.convenience_fee_paise != 0
            or quote.convenience_gst_paise != 0
            or quote.currency != "INR"
        ):
            return False
        frozen = snapshot.frozen_data
        if not isinstance(frozen, Mapping):
            return False
        items = frozen.get("items")
        if not isinstance(items, list) or len(items) != 1:
            return False
        item = items[0]
        if not isinstance(item, Mapping) or (
            str(item.get("productId") or "").lower() != product_id.lower()
            or item.get("variantId") != variant_id
            or type(item.get("quantity")) is not int or item["quantity"] != 1
            or type(item.get("unitPricePaise")) is not int
            or item["unitPricePaise"] != STAFF_CONTRIBUTION_TOTAL_PAISE
        ):
            return False
        delivery = frozen.get("delivery")
        if not isinstance(delivery, Mapping) or delivery.get("paise") != 0:
            return False
        metadata = frozen.get("pricingMetadata")
        if not isinstance(metadata, Mapping) or (
            metadata.get("policy") != STAFF_CONTRIBUTION_POLICY
            or int(metadata.get("discountPaise") or 0) != 0
            or int(metadata.get("supplyGstPaise") or 0) != 0
        ):
            return False
        return True
    except (TypeError, ValueError, AttributeError, KeyError):
        return False


__all__ = [
    "STAFF_CONTRIBUTION_TOTAL_PAISE",
    "STAFF_CONTRIBUTION_POLICY",
    "valid_staff_contribution_snapshot",
]
