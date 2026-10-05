"""A small, customer-facing Wix eCom client for carts and checkouts.

Why this is separate from `ecommerce/wix-store`
-----------------------------------------------
`wix-store` is the STAFF surface. Every route in it goes through `middleware.require_auth` against
the staff pool (Admin for any write), and it exposes products, orders, inventory and fulfilments —
never carts or checkouts. A walk-up customer cannot call it, and must not: a customer building a
cart is not an admin operation.

This module is the customer-side counterpart, and it holds exactly the two Wix eCom capabilities a
checkout needs and nothing else:

- **create a checkout** from a set of catalogue line items, so Wix owns the cart/checkout record;
- **read its authoritative totals**, so the amount a customer is asked to pay is computed by Wix
  from the catalogue and never trusted from the browser.

It deliberately does NOT create Wix orders. Under the headless WhatsApp/Razorpay flow the order is
materialised only after a provider-verified capture, by the reconciliation path — not here.

The credential
--------------
The Wix admin API key is read by reference from Secrets Manager (`WIX_API_KEY_SECRET`), lazily and
cached per execution environment, exactly as `wix-store` does. It is never logged and never placed
on a command line. The site id travels in the `wix-site-id` header.

Money
-----
Wix returns amounts as decimal strings in major units (e.g. `"599.00"`). This module converts to
**integer paise** with `Decimal`, never float, because the paise value is compared for exact
equality against the captured amount downstream and `0.1 + 0.2 != 0.3` in binary floating point. A
value that is not a clean whole number of paise is refused rather than rounded — a fractional paise
in a total is a data error, not something to silently absorb.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

WIX_API_BASE = os.environ.get("WIX_API_BASE", "https://www.wixapis.com")
WIX_SITE_ID = os.environ.get("WIX_SITE_ID", "c993128b-26be-41cd-9fcd-904abe23462f")
WIX_API_KEY_SECRET = os.environ.get("WIX_API_KEY_SECRET", "wecare/wix/headless-api-key")
REGION = os.environ.get("AWS_REGION", "us-east-1")

_secrets = None
_key_cache: Dict[str, str] = {}


class WixEcomError(RuntimeError):
    """A Wix eCom call failed. Carries no response body, which can echo customer data."""


class AmountNotWhole(ValueError):
    """A Wix total was not a clean whole number of paise, so it cannot be trusted as an amount."""


def http_error(method: str, endpoint: str, status: int) -> WixEcomError:
    """The exception a non-2xx produces, with the status attached STRUCTURALLY as `.status`.

    THE STATUS HAS TO BE READABLE WITHOUT PARSING THE MESSAGE, and that is the whole reason this
    constructor exists. The message is still the same status-only string it always was -- no
    response body, which can echo buyer detail -- but a 404 on a CART resource means something a
    caller must act on differently from every other failure: the cart is gone and has to be
    recreated, rather than an item being unavailable. Branching on an `in str(error)` substring
    would make that decision depend on an exception's prose, which is not acceptable on a path
    that ends in a charge.

    One constructor rather than two, so `_request` and any fake transport in the tests produce
    the identical shape; a fake that forgot `.status` would make the recovery untestable.
    """
    failure = WixEcomError(f"Wix eCom {method} {endpoint} returned HTTP {status}")
    failure.status = int(status)
    return failure


def _api_key() -> str:
    """The Wix admin API key, read by reference and cached per environment.

    Lazy on purpose: a module-scope read is frozen into a warm sandbox, so a rotation would keep
    using the old key until every sandbox recycled. Never logged, never returned to a caller.
    """
    global _secrets
    if "key" in _key_cache:
        return _key_cache["key"]
    import boto3
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    raw = _secrets.get_secret_value(SecretId=WIX_API_KEY_SECRET).get("SecretString", "") or ""
    value = ""
    try:
        data = json.loads(raw)
        value = (data.get("apiKey") or data.get("api_key")
                 or data.get("value") or data.get("key") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise WixEcomError("Wix API key is not configured")
    _key_cache["key"] = value
    return value


def _request(endpoint: str, *, method: str = "POST",
             body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One authenticated Wix eCom call. Raises `WixEcomError` on any non-2xx.

    Uses urllib rather than a third-party HTTP client so the function package stays dependency-free,
    matching the rest of the fleet.
    """
    import urllib.error
    import urllib.request

    url = f"{WIX_API_BASE}{endpoint}"
    headers = {
        "Authorization": _api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "wix-site-id": WIX_SITE_ID,
    }
    data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        # Status only. The body can carry buyer detail and is not logged or surfaced. The message
        # is unchanged; `http_error` additionally carries the status as `.status` so a caller can
        # tell a 404 from the other fourteen refusals without reading the prose.
        raise http_error(method, endpoint, error.code) from None
    except Exception as error:  # noqa: BLE001
        raise WixEcomError(
            f"Wix eCom {method} {endpoint} failed: {type(error).__name__}") from error
    try:
        return json.loads(payload) if payload else {}
    except (ValueError, TypeError) as error:
        raise WixEcomError("Wix eCom response was not JSON") from error


def to_paise(major_units: Any) -> int:
    """Convert a Wix decimal-string amount in major units to integer paise, or raise.

    `Decimal(str(value))`, never float. A value that is not an exact whole number of paise (e.g.
    `599.005`) raises `AmountNotWhole` rather than rounding, because a total that does not land on a
    paise boundary is a data error and rounding it would create the one-paise mismatch the whole
    payment path is built to fail closed on.
    """
    try:
        rupees = Decimal(str(major_units))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise AmountNotWhole(f"not a decimal amount: {major_units!r}") from error
    paise = rupees * 100
    if paise != paise.to_integral_value():
        raise AmountNotWhole(f"amount {major_units!r} is not a whole number of paise")
    value = int(paise)
    if value <= 0:
        raise AmountNotWhole(f"amount {major_units!r} is not positive")
    return value


def create_checkout(line_items: List[Dict[str, Any]], *,
                    channel_type: str = "OTHER_PLATFORM") -> Dict[str, Any]:
    """Create a Wix eCom checkout from catalogue line items. Returns the raw checkout object.

    `line_items` are `{catalogReference, quantity}` entries — a reference into the Wix catalogue,
    never a price. The price is whatever Wix computes; the browser cannot influence it, which is the
    point of resolving the total server-side.
    """
    if not line_items:
        raise WixEcomError("a checkout needs at least one line item")
    body = {
        "checkoutInfo": {"channelType": channel_type},
        "lineItems": normalized_catalog_items(line_items),
    }
    result = _request("/ecom/v1/checkouts", method="POST", body=body)
    checkout = result.get("checkout")
    if not isinstance(checkout, dict) or not checkout.get("id"):
        raise WixEcomError("Wix did not return a checkout id")
    return checkout


def resolved_catalog_lines(line_items):
    """Resolve live V3 variants before pricing, and report whether each line needs delivery.

    -> [{'productId', 'variantId', 'quantity', 'requiresDelivery'}]

    Same validation, same product cache, same refusals and the same number of HTTP calls as
    `normalized_catalog_items`, which is now a projection of this function; one extra field.

    `requiresDelivery` is `str(product.get('productType') or '').upper() != 'DIGITAL'`, so an
    absent, empty, lowercase or unrecognised `productType` FAILS CLOSED to "needs an address"
    rather than silently skipping the one gate that sets the place of supply. Asking for an
    address unnecessarily annoys a customer; not asking ships a physical order nowhere with the
    wrong GST split.

Get Product: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/get-product
Stores' catalogue reference contract is shared with our existing Cart V2 adapter.
"""
    from lambda_utils.ecommerce.cart_v2 import STORES_APP_ID, identifier
    if not isinstance(line_items, list) or not 1 <= len(line_items) <= 100:
        raise WixEcomError('1 to 100 catalogue items required')
    resolved = []
    products = {}
    for line in line_items:
        if not isinstance(line, dict) or set(line) != {'catalogReference', 'quantity'}:
            raise WixEcomError('catalogue references and quantities required')
        ref = line['catalogReference']
        quantity = line['quantity']
        if (not isinstance(ref, dict) or ref.get('appId') != STORES_APP_ID
                or set(ref) - {'appId', 'catalogItemId', 'options'}
                or type(quantity) is not int or not 1 <= quantity <= 100000):
            raise WixEcomError('invalid catalogue reference')
        try:
            product_id = identifier(ref.get('catalogItemId'))
        except (ValueError, TypeError):
            raise WixEcomError('invalid product identifier') from None
        if product_id not in products:
            products[product_id] = _request(f'/stores/v3/products/{product_id}', method='GET').get('product') or {}
        product = products[product_id]
        if product.get('id') != product_id or product.get('visible') is False:
            raise WixEcomError('product unavailable')
        variants = [v for v in (product.get('variantsInfo') or {}).get('variants', [])
                    if v.get('visible') and (v.get('inventoryStatus') or {}).get('inStock')]
        options = ref.get('options') or {}
        if not isinstance(options, dict) or set(options) - {'variantId'}:
            raise WixEcomError('invalid variant options')
        variant_id = options.get('variantId')
        # Only a genuinely single-variant product can resume a cart predating variant capture.
        all_variants = (product.get('variantsInfo') or {}).get('variants', [])
        if not variant_id and len(all_variants) == 1 and len(variants) == 1:
            variant_id = variants[0].get('id')
        if not variant_id or not any(v.get('id') == variant_id for v in variants):
            raise WixEcomError('choose an available product option')
        resolved.append({'productId': product_id, 'variantId': variant_id,
                         'quantity': quantity,
                         'requiresDelivery': str(product.get('productType') or '').upper() != 'DIGITAL'})
    return resolved


def normalized_catalog_items(line_items):
    """Unchanged contract and unchanged return shape, now a projection of
    `resolved_catalog_lines`.

Get Product: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/get-product
Stores' catalogue reference contract is shared with our existing Cart V2 adapter.
"""
    from lambda_utils.ecommerce.cart_v2 import STORES_APP_ID
    return [{'catalogReference': {'appId': STORES_APP_ID,
                                  'catalogItemId': line['productId'],
                                  'options': {'variantId': line['variantId']}},
             'quantity': line['quantity']}
            for line in resolved_catalog_lines(line_items)]


def get_checkout(checkout_id: str) -> Dict[str, Any]:
    """Read a Wix checkout by id. Returns the raw checkout object."""
    if not checkout_id:
        raise WixEcomError("checkout id is required")
    result = _request(f"/ecom/v1/checkouts/{checkout_id}", method="GET")
    checkout = result.get("checkout")
    if not isinstance(checkout, dict):
        raise WixEcomError("Wix returned no checkout")
    return checkout


def authoritative_total_paise(checkout: Dict[str, Any]) -> int:
    """The amount to charge, in integer paise, taken only from Wix's price summary.

    Reads `priceSummary.total.amount` — the figure Wix computed from the catalogue, discounts,
    shipping and tax. Never a value that originated in the request. Raises if it is missing or not
    a whole number of paise.
    """
    summary = checkout.get("priceSummary") or {}
    total = (summary.get("total") or {}).get("amount")
    if total is None:
        raise WixEcomError("Wix checkout carried no total")
    return to_paise(total)


def checkout_currency(checkout: Dict[str, Any]) -> str:
    """The checkout currency. Compared explicitly against INR by the caller, never inferred."""
    return str(checkout.get("currency") or "")


def line_item_summary(checkout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A compact, price-free-per-line item list for the payment request and the receipt.

    Names and quantities only. The authoritative money is the checkout total, computed once.
    """
    out: List[Dict[str, Any]] = []
    for item in checkout.get("lineItems") or []:
        name = item.get("productName") or {}
        out.append({
            "name": (name.get("original") or name.get("translated") or "")
            if isinstance(name, dict) else str(name),
            "quantity": int(item.get("quantity") or 1),
        })
    return out


__all__ = [
    "WIX_SITE_ID",
    "WixEcomError",
    "AmountNotWhole",
    "to_paise",
    "create_checkout",
    "get_checkout",
    "authoritative_total_paise",
    "checkout_currency",
    "line_item_summary",
]
