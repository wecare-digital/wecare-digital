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

from lambda_utils.ecommerce import service_requests
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


def resolve_all(product_reader: ProductReader) -> Dict[str, Any]:
    """Every public service slug's native price. No warm-sandbox cache here: a
    DynamoDB point read per slug is cheap and avoids serving a stale price across a
    price edit."""
    prices: Dict[str, Dict[str, Any]] = {}
    for slug, kind in service_requests.SERVICE_KIND_BY_SLUG.items():
        variant = service_requests.SERVICE_VARIANT_BY_KIND.get(kind, "")
        try:
            paise = _variant_paise(product_reader(variant))
            prices[slug] = {"available": True, "paise": paise}
        except Exception as error:  # noqa: BLE001 - one slug must not blank the others
            logger.warning(json.dumps({"event": "service_price_unavailable_native",
                                       "slug": slug, "error": type(error).__name__}))
            prices[slug] = {"available": False}
    return {"currency": SERVICE_CURRENCY, "prices": prices}


__all__ = ["SERVICE_CURRENCY", "resolve_all"]
