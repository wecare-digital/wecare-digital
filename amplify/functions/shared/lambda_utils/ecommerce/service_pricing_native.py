"""AWS-native service-page pricing for `GET /ecommerce/service-prices`.

The AWS-native catalog IS the price authority, so this reads each service variant's
`priceMinor` directly from `ProductsTable` — no cart and no third-party call. The
checkout handler serves its result as:

    {"currency": "INR", "prices": {slug: {"available": True, "paise": int}
                                         | {"available": False}}}

Guarantees:
  - integer paise only (never float), via `positive_paise`,
  - FAIL CLOSED PER SLUG: a slug whose price cannot be resolved is
    `{"available": False}` with NO `paise` key — never a zero, stale, or fallback,
  - one slug failing leaves the others priced.

The lookup is injected (`product_reader`) so this is unit-testable offline and the
module reads no secret and holds no boto3 client.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, Mapping, Optional

from lambda_utils import template_media, whatsapp_templates
from lambda_utils.ecommerce import blog_contribution, checkout_pricing, contribute_taxable, default_coupon, service_requests
from lambda_utils.ecommerce.money import positive_paise

logger = logging.getLogger(__name__)

SERVICE_CURRENCY = service_requests.SERVICE_CURRENCY
# A separate catalog product, NOT a sixth request-service kind. Viewing an
# owned order's shipment tracking remains distinct from buying this SKU.
SHIPMENT_TRACK_SKU = "SHT8M5P3"

#: A reader taking a service variant id and returning its ProductsTable price row, e.g.
#: {"priceMinor": 9900, "currency": "INR", "status": "active"} — or None if absent.
ProductReader = Callable[[str], Optional[Mapping[str, Any]]]


def _variant_paise(row: Optional[Mapping[str, Any]]) -> int:
    """The variant's price as positive integer paise, or raise. A missing,
    inactive, non-positive or non-INR price is a refusal, not a zero."""
    if not isinstance(row, Mapping):
        raise ValueError("service variant not found in catalog")
    if str(row.get("status") or "active") != "active":
        raise ValueError("service variant is not active")
    if str(row.get("currency") or SERVICE_CURRENCY) != SERVICE_CURRENCY:
        raise ValueError("service variant is not priced in INR")
    value = row.get("priceMinor")
    from decimal import Decimal
    if isinstance(value, Decimal):
        # DynamoDB numbers arrive as Decimal; never truncate fractional paise
        # (e.g. Decimal("8497.9") -> 8497 would silently undercharge).
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("service variant priceMinor must be integer paise")
        value = int(value)
    return positive_paise(value)


def _collect_breakdown(kind: str, item_subtotal_paise: int) -> Optional[Dict[str, int]]:
    """Collect-style server breakdown for Vault/Drop Docs only.

    ProductsTable carries the pre-GST service item price for these two services. Add 18% supply
    GST first, calculate Delight on item + supply GST, then add Express. The shared checkout
    calculator adds the 2.5% Convenience Fee and 18% GST on that fee.
    """
    if kind not in (service_requests.VAULT, service_requests.DROP_DOCS):
        return None
    supply_gst = checkout_pricing.round_half_up(item_subtotal_paise, 1800)
    delight = default_coupon.delight_paise(item_subtotal_paise + supply_gst)
    express = service_requests.VAULT_DROP_DOCS_EXPRESS_PAISE
    collection = item_subtotal_paise + supply_gst - delight + express
    quote = checkout_pricing.compute_quote(collection, currency=SERVICE_CURRENCY)
    return {
        "itemSubtotalPaise": item_subtotal_paise,
        "supplyGstPaise": supply_gst,
        "supplyGstBps": 1800,
        "delightPaise": delight,
        "expressPaise": express,
        "collectionBeforeConveniencePaise": quote.collection_before_convenience_paise,
        "convenienceFeePaise": quote.convenience_fee_paise,
        "convenienceGstPaise": quote.convenience_gst_paise,
        "convenienceGstBps": checkout_pricing.CONVENIENCE_GST_BPS,
        "totalPayablePaise": quote.total_payable_paise,
    }


def _contribution_breakdown(catalog_gross_paise: int) -> Dict[str, int]:
    """Exact 30000-paise Contribute quote under its own taxable policy.

    This does NOT borrow Vault/Drop Docs' service SKU or their Rs25 Express
    policy. Product catalog stores the gross 30000 paise while the mandatory
    native payment lines transparently reconcile back to that same total.
    A missing/drifting price fails closed instead of silently repricing.
    """
    return contribute_taxable.breakdown(catalog_gross_paise)


def _payment_templates(kind: str) -> Optional[Dict[str, Any]]:
    """Read-only preview of the approved, shared native payment template.

    All FIVE single-order service payments share their Meta PAY/ORDER_STATUS
    template, the same approved image header and item thumbnail, and one
    receipt template. After that the service-specific paid Flow/secure-download
    action is DIFFERENT. This merely describes the registered names; actual
    sends remain governed by the stored paid intent and outbound sender.
    """
    deliveries = {
        service_requests.SUBMIT_REQUEST: whatsapp_templates.SUBMIT_REQUEST_FLOW,
        service_requests.REQUEST_AMENDMENT: whatsapp_templates.REQUEST_AMENDMENT_FLOW,
        service_requests.DROP_DOCS: whatsapp_templates.DROP_DOCS_FLOW,
        service_requests.VAULT: whatsapp_templates.DOWNLOAD,
        service_requests.REQUEST_PICKUP: whatsapp_templates.REQUEST_PICKUP_FLOW,
    }
    delivery = deliveries.get(kind)
    # Contribute uses the same native payment and receipt templates, but has
    # no service-fulfilment/delivery Flow of its own.
    if delivery is None and kind != "contribute":
        return None
    delivery_name = delivery.name if delivery is not None else ""
    # Lookups from the SAME approved-name registry the payment sender and
    # invoice engine use. These ids are display/audit metadata, NOT Meta
    # approval status, customer-supplied pay parameters or new send choices.
    # The live sender still checks provider approval before any money-path
    # WhatsApp send. Exposing IDs here makes the read-only Vault workspace
    # display the real backend mapping, not duplicate editable browser strings.
    ids = whatsapp_templates.APPROVED_TEMPLATE_IDS
    template_ids = {
        "nativePay": ids.get(whatsapp_templates.PAY.name, ""),
        "orderStatus": ids.get(whatsapp_templates.ORDER_STATUS.name, ""),
        "receipt": ids.get(whatsapp_templates.INVOICE.name, ""),
        "delivery": ids.get(delivery_name, "") if delivery_name else "",
    }
    return {
        "nativePay": whatsapp_templates.PAY.name,
        "orderStatus": whatsapp_templates.ORDER_STATUS.name,
        "orderStatusStates": ["processing", "completed"],
        "delivery": delivery_name,
        "receipt": whatsapp_templates.INVOICE.name,
        "templateIds": template_ids,
        "headerImage": template_media.PAYMENT_TEMPLATE_HEADER,
        "itemThumbnail": template_media.DEFAULT_ORDER_ITEM_THUMBNAIL,
    }

def resolve_all(product_reader: ProductReader) -> Dict[str, Any]:
    """Every public service slug's native price. No warm-sandbox cache here: a
    DynamoDB point read per slug is cheap and avoids serving a stale price across a
    price edit."""
    prices: Dict[str, Dict[str, Any]] = {}
    for slug, kind in service_requests.SERVICE_KIND_BY_SLUG.items():
        variant = service_requests.SERVICE_VARIANT_BY_KIND.get(kind, "")
        try:
            paise = _variant_paise(product_reader(variant))
            row: Dict[str, Any] = {"available": True, "paise": paise}
            breakdown = _collect_breakdown(kind, paise)
            if breakdown is not None:
                row["breakdown"] = breakdown
            templates = _payment_templates(kind)
            if templates is not None:
                row["templates"] = templates
            prices[slug] = row
        except Exception as error:  # noqa: BLE001 - one slug must not blank the others
            logger.warning(json.dumps({"event": "service_price_unavailable_native",
                                       "slug": slug, "error": type(error).__name__}))
            prices[slug] = {"available": False}
    # Track Shipping is an ordinary priced catalog SKU, NOT a service intent.
    # Return a separate read-only item price for Workspace without inventing a
    # paid tracking Flow, an invoice, or a sixth service in SERVICE_KIND_BY_SLUG.
    try:
        paise = _variant_paise(product_reader(SHIPMENT_TRACK_SKU))
        prices["shipments-track"] = {"available": True, "paise": paise}
    except Exception as error:  # noqa: BLE001 - one product must not blank other prices
        logger.warning(json.dumps({"event": "shipment_track_price_unavailable_native",
                                   "error": type(error).__name__}))
        prices["shipments-track"] = {"available": False}

    # Contribute is not a request service, but Workspace needs the same anonymous,
    # server-authoritative price read. Keep it as a separate row rather than adding it to
    # SERVICE_KIND_BY_SLUG, because it has no service fulfilment / Meta Flow contract.
    contribution_variants = sorted(blog_contribution.CONTRIBUTION_VARIANT_IDS)
    # Do not advertise a payable taxable Contribute quote before the
    # independently reviewed tax/capture release is enabled.
    if os.environ.get("CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED", "") != "true":
        prices["contribute"] = {"available": False}
    elif len(contribution_variants) == 1:
        variant = contribution_variants[0]
        try:
            paise = _variant_paise(product_reader(variant))
            prices["contribute"] = {
                "available": True,
                "paise": paise,
                "breakdown": _contribution_breakdown(paise),
                "templates": _payment_templates("contribute"),
            }
        except Exception as error:  # noqa: BLE001 - fail closed like service rows
            logger.warning(json.dumps({"event": "contribution_price_unavailable_native",
                                       "error": type(error).__name__}))
            prices["contribute"] = {"available": False}
    else:
        prices["contribute"] = {"available": False}

    return {"currency": SERVICE_CURRENCY, "prices": prices}


__all__ = ["SERVICE_CURRENCY", "SHIPMENT_TRACK_SKU", "_collect_breakdown", "_contribution_breakdown", "_payment_templates", "resolve_all"]
