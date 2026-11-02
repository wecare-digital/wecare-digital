"""WECARE Shop Express policy, in integer paise.

A customer basket pays ONE Express amount, not one amount per line:
* Contribute: ₹15 within its existing exact ₹300 gross contract.
* Request · Vault: ₹25. All other customer items: ₹45, including Drop Docs.
The unlisted ₹2 commerce verification SKU is internal QA, not a customer item.

Customer payment amounts are now calculated by unified_pricing.py using
these shared Express constants. The older with_standard_express helper is
retained only for compatible legacy clients; it is NOT the customer checkout
calculation and must not be wired back into the new GST-exclusive quote.
Neither a browser price nor a display string can change the money.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CONTRIBUTE_EXPRESS_PAISE = 1_500
VAULT_EXPRESS_PAISE = 2_500
VAULT_PRODUCT_ID = "d4cfc6e8-10b3-5c47-94c8-3c69f4c03907"
VAULT_VARIANT_ID = "RVT6K4Q8"
STANDARD_EXPRESS_PAISE = 4_500
STANDARD_EXPRESS_POLICY = "shop-express-noncontribute-2026-11-02"

# Internal verification only; absent from all public shop and Meta catalog lists.
INTERNAL_QA_PRODUCT_ID = "native:commerce-test-2"
INTERNAL_QA_VARIANT_ID = "WCTEST2R26"


def is_internal_qa_cart(canonical: Sequence[tuple[str, str, int]]) -> bool:
    """Only the unlisted internal test SKU bypasses the customer Express fee."""
    return (
        len(canonical) == 1
        and canonical[0][0] == INTERNAL_QA_PRODUCT_ID
        and canonical[0][1] == INTERNAL_QA_VARIANT_ID
    )


def with_standard_express(base: Any) -> Any:
    """Freeze one ₹45 Express charge into a server-priced ordinary cart.

    The input quote already includes the correct existing catalog/discount policy.
    The shipping resolver is currently free; refuse a future nonzero shipment
    rather than quietly double-charge or replace a real delivery amount.
    Rebuild the immutable quote/snapshot so Razorpay, Meta and invoice readback
    all observe the SAME exact payable amount, not a UI-only surcharge.
    """
    from lambda_utils.ecommerce import checkout_pricing

    frozen = base.frozen_data
    if not isinstance(frozen, Mapping):
        raise checkout_pricing.PricingError("missing frozen cart")
    original_delivery = frozen.get("delivery")
    if (not isinstance(original_delivery, Mapping)
            or type(original_delivery.get("paise")) is not int
            or original_delivery["paise"] != 0):
        raise checkout_pricing.PricingError("unexpected existing delivery in Express quote")
    original_quote = base.quote
    if original_quote.currency != "INR":
        raise checkout_pricing.PricingError("Express requires INR")

    collection = (
        original_quote.collection_before_convenience_paise + STANDARD_EXPRESS_PAISE
    )
    priced = checkout_pricing.compute_quote(
        collection, currency=original_quote.currency,
        buyer_gstin=original_quote.buyer_gstin,
        intra_state=original_quote.convenience_gst_split.intra_state,
    )
    return checkout_pricing.build_snapshot(
        customer_id=base.customer_id,
        cart_id=base.cart_id,
        cart_revision=base.cart_revision,
        quote=priced,
        created_at=base.created_at,
        ttl_seconds=base.expires_at - base.created_at,
        site=frozen.get("site"),
        items=frozen.get("items"),
        address=frozen.get("address"),
        delivery={"paise": STANDARD_EXPRESS_PAISE, "optionId": "express"},
        pricing_metadata={
            "policy": STANDARD_EXPRESS_POLICY,
            "expressPaise": STANDARD_EXPRESS_PAISE,
        },
    )


__all__ = [
    "CONTRIBUTE_EXPRESS_PAISE", "STANDARD_EXPRESS_PAISE", "VAULT_EXPRESS_PAISE",
    "STANDARD_EXPRESS_POLICY", "INTERNAL_QA_PRODUCT_ID",
    "INTERNAL_QA_VARIANT_ID", "is_internal_qa_cart",
    "with_standard_express",
]
