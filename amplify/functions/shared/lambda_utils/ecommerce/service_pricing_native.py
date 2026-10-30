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
from typing import Any, Callable, Dict, Mapping, Optional

from lambda_utils import whatsapp_templates
from lambda_utils.ecommerce import blog_contribution, checkout_pricing, default_coupon, service_requests
from lambda_utils.ecommerce.money import positive_paise

logger = logging.getLogger(__name__)

SERVICE_CURRENCY = service_requests.SERVICE_CURRENCY

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


def _contribution_breakdown(item_subtotal_paise: int) -> Dict[str, int]:
    """A voluntary contribution is exactly the chosen catalog amount.

    It has no supply GST adjustment, Delight, Express charge, convenience fee or GST-on-fee.
    The ProductsTable variant price remains the amount authority; this is only the fee policy.
    """
    quote = checkout_pricing.exempt_quote(item_subtotal_paise, currency=SERVICE_CURRENCY)
    return {
        "itemSubtotalPaise": item_subtotal_paise,
        "supplyGstPaise": 0,
        "supplyGstBps": 0,
        "delightPaise": 0,
        "expressPaise": 0,
        "collectionBeforeConveniencePaise": quote.collection_before_convenience_paise,
        "convenienceFeePaise": 0,
        "convenienceGstPaise": 0,
        "convenienceGstBps": checkout_pricing.CONVENIENCE_GST_BPS,
        "totalPayablePaise": quote.total_payable_paise,
    }


def _payment_templates(kind: str) -> Optional[Dict[str, Any]]:
    """The exact shared outbound defaults Workspace should preview.

    Names come from the same registry used by checkout/outbound. Vault and Drop Docs deliberately
    share PAY, ORDER_STATUS and INVOICE; only the paid delivery step differs.
    """
    if kind not in (service_requests.VAULT, service_requests.DROP_DOCS):
        return None
    delivery = (
        whatsapp_templates.DOWNLOAD
        if kind == service_requests.VAULT
        else whatsapp_templates.DROP_DOCS_FLOW
    )
    return {
        "nativePay": whatsapp_templates.PAY.name,
        "orderStatus": whatsapp_templates.ORDER_STATUS.name,
        "orderStatusStates": ["processing", "completed"],
        "delivery": delivery.name,
        "receipt": whatsapp_templates.INVOICE.name,
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
    # Contribute is not a request service, but Workspace needs the same anonymous,
    # server-authoritative price read. Keep it as a separate row rather than adding it to
    # SERVICE_KIND_BY_SLUG, because it has no service fulfilment / Meta Flow contract.
    contribution_variants = sorted(blog_contribution.CONTRIBUTION_VARIANT_IDS)
    if len(contribution_variants) == 1:
        variant = contribution_variants[0]
        try:
            paise = _variant_paise(product_reader(variant))
            prices["contribute"] = {
                "available": True,
                "paise": paise,
                "breakdown": _contribution_breakdown(paise),
            }
        except Exception as error:  # noqa: BLE001 - fail closed like service rows
            logger.warning(json.dumps({"event": "contribution_price_unavailable_native",
                                       "error": type(error).__name__}))
            prices["contribute"] = {"available": False}
    else:
        prices["contribute"] = {"available": False}

    return {"currency": SERVICE_CURRENCY, "prices": prices}


__all__ = ["SERVICE_CURRENCY", "_collect_breakdown", "_contribution_breakdown", "_payment_templates", "resolve_all"]
