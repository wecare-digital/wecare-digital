"""Staff-native Contribute guard: EXACT six-part taxable ₹300 checkout.

This is a pure validation module. It has no network, IAM or payment-side effects.
Both the preclaim check and _create's last-before-write gate MUST call the same
validator, because the live ProductsTable price can change between reads.
"""
from __future__ import annotations

from typing import Any, Mapping
from decimal import Decimal

from lambda_utils.ecommerce import contribute_taxable

STAFF_CONTRIBUTION_TOTAL_PAISE = contribute_taxable.CATALOG_TOTAL_PAISE
STAFF_CONTRIBUTION_POLICY = contribute_taxable.POLICY


def valid_staff_contribution_snapshot(
    snapshot: Any, *, product_id: str, variant_id: str
) -> bool:
    """True only for one frozen ₹300 Contribute order with every amount reconciled."""
    try:
        terms = contribute_taxable.breakdown(STAFF_CONTRIBUTION_TOTAL_PAISE)
        quote = snapshot.quote
        if (
            type(quote.total_payable_paise) is not int
            or quote.total_payable_paise != terms["totalPayablePaise"]
            or type(quote.collection_before_convenience_paise) is not int
            or quote.collection_before_convenience_paise != terms["collectionBeforeConveniencePaise"]
            or quote.convenience_fee_paise != terms["convenienceFeePaise"]
            or quote.convenience_gst_paise != terms["convenienceGstPaise"]
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
            or item["unitPricePaise"] != terms["itemSubtotalPaise"]
        ):
            return False
        delivery = frozen.get("delivery")
        if not isinstance(delivery, Mapping) or delivery.get("paise") != terms["expressPaise"]:
            return False
        metadata = frozen.get("pricingMetadata")
        if not isinstance(metadata, Mapping) or (
            metadata.get("policy") != STAFF_CONTRIBUTION_POLICY
            or metadata.get("catalogGrossPaise") != terms["catalogGrossPaise"]
            or metadata.get("discountPaise") != terms["delightPaise"]
            or metadata.get("supplyGstPaise") != terms["supplyGstPaise"]
        ):
            return False
        return True
    except (TypeError, ValueError, AttributeError, KeyError):
        return False


def valid_staff_contribution_catalog_record(
    product: Any, *, product_id: str, variant_id: str,
) -> bool:
    """Validate an authoritative, strongly-consistent ProductsTable GetItem.

    A quote assembled from eventually-consistent reads is NOT sufficient for
    an Admin-initiated payment. Call this with GetItem(ConsistentRead=True)
    immediately before allocating a PAYREF or a payment attempt. No fallback.
    Accept DynamoDB's integer Decimal, never float, bool or string prices.
    """
    if not isinstance(product, Mapping):
        return False
    if (
        str(product.get("id") or "").lower() != product_id.lower()
        or product.get("status") != "active"
        or product.get("currency") != "INR"
        or product.get("websiteEnabled") is not True
    ):
        return False
    variants = product.get("variants")
    if not isinstance(variants, list):
        return False
    candidates = [
        item for item in variants
        if isinstance(item, Mapping)
        and (str(item.get("sku") or item.get("id") or "") == variant_id)
    ]
    if len(candidates) != 1:
        return False
    row = candidates[0]
    price = row.get("priceMinor")
    if type(price) is int:
        return price == STAFF_CONTRIBUTION_TOTAL_PAISE
    if type(price) is Decimal and price.is_finite():
        return price == Decimal(STAFF_CONTRIBUTION_TOTAL_PAISE)
    return False


__all__ = [
    "STAFF_CONTRIBUTION_TOTAL_PAISE",
    "STAFF_CONTRIBUTION_POLICY",
    "valid_staff_contribution_snapshot",
    "valid_staff_contribution_catalog_record",
]
