"""Customer-safe catalog analytics facts from an already authorized, paid attempt.

No event is sent here. Browser consent is separate, and unknown references are
omitted rather than manufacturing a catalog match from a product name.
"""
from collections.abc import Mapping
from decimal import Decimal

from . import meta_catalog_sync, payment_attempt


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    try:
        return int(value) if value == int(value) and value > 0 else None
    except (ValueError, OverflowError):
        return None


def purchase_facts(attempt):
    """Catalog analytics facts from a paid attempt, provider-neutral.

    Reads the frozen `catalogContents` list written by checkout before any payable request is
    sent. Each line is `{productId, variantId, quantity}`; the external content id is generated
    by `meta_catalog_sync.retailer_id`, the same function that publishes the Meta catalogue.

    Returns None unless the attempt is a clean paid INR order with an order number and every
    frozen line can be expressed as one of our valid retailer-id contracts. A malformed or mixed
    non-catalog basket therefore suppresses attribution rather than manufacturing a match.
    """
    if (attempt.get("status") != payment_attempt.PAYMENT_PAID
            or not attempt.get("orderNumber") or attempt.get("currency") != "INR"):
        return None

    amount = _integer(attempt.get("amountPaise"))
    lines = attempt.get("catalogContents")
    if not amount or not isinstance(lines, list) or not lines:
        return None

    contents = []
    for line in lines:
        if not isinstance(line, Mapping):
            return None
        product = str(line.get("productId") or "").strip()
        variant = str(line.get("variantId") or "").strip()
        quantity = _integer(line.get("quantity"))
        if not product or not variant or not quantity:
            return None
        try:
            retailer_id = meta_catalog_sync.retailer_id(product, variant)
        except meta_catalog_sync.RetailerIdError:
            return None
        contents.append({"id": retailer_id, "quantity": quantity})

    return {"contents": contents, "amountPaise": amount, "currency": "INR"}
