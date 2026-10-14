"""AWS-native cart CRUD on CartTable — the native replacement for Wix Cart V2.

`cart_v2.py` creates/mutates a cart inside Wix. This module keeps the cart in the
AWS `CartTable` and resolves every line's price SERVER-SIDE from `ProductsTable`
at add time, so a client-supplied price is never trusted (the same guarantee the
Wix path had, where Wix priced the cart). It produces lines that convert directly
to `catalog_pricing.CatalogLine`, so `price_cart` can quote the cart without any
Wix round-trip.

Operations mirror the Cart V2 surface the checkout uses:
    create(items)            -> new cart row
    add(cart_id, item)       -> add/merge a line
    set_quantity(cart_id, variant_id, qty)
    remove(cart_id, variant_id)
    get(cart_id)             -> cart row (CartGone-equivalent: returns None)
    to_catalog_lines(cart)   -> [CatalogLine] for pricing

Design, consistent with the rest of the library:
  - integer paise only (prices from ProductsTable `priceMinor`); no float,
  - quantity 1..100000 per line (same bound as cart_v2 / catalog_pricing),
  - the table + product reader are INJECTED (no boto3, no secret here),
  - cart is a short-lived working doc with a TTL (CartTable reaps abandoned carts);
    the ORDER is the durable artifact, never the cart.

NOT WIRED until CHECKOUT_MODE=AWS_NATIVE. The checkout handler keeps using Wix
Cart V2 until the owner-gated cutover.
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from lambda_utils.ecommerce.catalog_pricing import CatalogLine

#: Abandoned carts expire; the CartTable has a TTL attribute (catalog-resources.ts).
CART_TTL_SECONDS = 7 * 24 * 3600

ProductReader = Callable[[str], Optional[Mapping[str, Any]]]


class NativeCartError(RuntimeError):
    """A cart operation failed for a storage reason (not a validation error)."""


class CartNotFound(LookupError):
    """The cart id does not exist (the native equivalent of cart_v2.CartGone)."""


def _int_qty(value: Any) -> int:
    if isinstance(value, bool) or type(value) is not int or not 1 <= value <= 100000:
        raise ValueError("quantity must be an integer in 1..100000")
    return value


def _unit_price_paise(product_reader: ProductReader, product_id: str, variant_id: str) -> int:
    """The authoritative per-unit price for a variant, from ProductsTable. Raises if the
    variant is absent, archived, or has no positive integer price — never guesses."""
    row = product_reader(product_id)
    if not isinstance(row, Mapping):
        raise ValueError(f"product {product_id} not found")
    if str(row.get("status") or "active") == "archived":
        raise ValueError(f"product {product_id} is archived")
    price = None
    for v in row.get("variants", []) or []:
        if str(v.get("sku") or v.get("id") or "") == variant_id:
            price = v.get("priceMinor", row.get("priceMinor"))
            break
    else:
        # no variants / single-variant product: product-level price
        if not row.get("variants") or str(row.get("id") or "") == variant_id:
            price = row.get("priceMinor")
    if isinstance(price, Decimal):
        price = int(price)
    if type(price) is not int or price < 0:
        raise ValueError(f"variant {variant_id} has no usable priceMinor")
    return price


def _now() -> int:
    return int(time.time())


def create(table: Any, product_reader: ProductReader, items: Sequence[Mapping[str, Any]],
           *, customer_id: Optional[str] = None, clock: Callable[[], int] = _now) -> Dict[str, Any]:
    """Create a cart from 1..100 items. Prices resolved server-side at creation."""
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 100:
        raise ValueError("create requires 1 to 100 items")
    now = clock()
    cart = {
        "cartId": uuid.uuid4().hex,
        "customerId": customer_id or "",
        "status": "open",
        "lineItems": [],
        "createdAt": now,
        "updatedAt": now,
        "expiresTtl": now + CART_TTL_SECONDS,
    }
    for item in items:
        _merge_line(cart, product_reader, item)
    _put(table, cart)
    return cart


def get(table: Any, cart_id: str) -> Dict[str, Any]:
    row = _get(table, cart_id)
    if row is None:
        raise CartNotFound(cart_id)
    return row


def add(table: Any, product_reader: ProductReader, cart_id: str, item: Mapping[str, Any],
        *, clock: Callable[[], int] = _now) -> Dict[str, Any]:
    cart = get(table, cart_id)
    _merge_line(cart, product_reader, item)
    cart["updatedAt"] = clock()
    _put(table, cart)
    return cart


def set_quantity(table: Any, cart_id: str, variant_id: str, quantity: int,
                 *, clock: Callable[[], int] = _now) -> Dict[str, Any]:
    cart = get(table, cart_id)
    qty = _int_qty(quantity)
    for line in cart["lineItems"]:
        if line["variantId"] == variant_id:
            line["quantity"] = qty
            cart["updatedAt"] = clock()
            _put(table, cart)
            return cart
    raise ValueError(f"variant {variant_id} is not in the cart")


def remove(table: Any, cart_id: str, variant_id: str,
           *, clock: Callable[[], int] = _now) -> Dict[str, Any]:
    cart = get(table, cart_id)
    before = len(cart["lineItems"])
    cart["lineItems"] = [ln for ln in cart["lineItems"] if ln["variantId"] != variant_id]
    if len(cart["lineItems"]) == before:
        raise ValueError(f"variant {variant_id} is not in the cart")
    cart["updatedAt"] = clock()
    _put(table, cart)
    return cart


def to_catalog_lines(cart: Mapping[str, Any]) -> List[CatalogLine]:
    """Convert the cart's stored lines to CatalogLine for `catalog_pricing.price_cart`.
    Prices are the ones captured server-side at add-time (re-validated at checkout)."""
    return [
        CatalogLine(
            product_id=ln["productId"],
            variant_id=ln["variantId"],
            quantity=int(ln["quantity"]),
            unit_price_paise=int(ln["unitPricePaise"]),
            requires_delivery=bool(ln.get("requiresDelivery", True)),
        )
        for ln in cart.get("lineItems", [])
    ]


# ── internals ───────────────────────────────────────────────────────────────

def _merge_line(cart: Dict[str, Any], product_reader: ProductReader,
                item: Mapping[str, Any]) -> None:
    product_id = str(item.get("product_id") or item.get("productId") or "")
    variant_id = str(item.get("variant_id") or item.get("variantId") or "")
    if not product_id or not variant_id:
        raise ValueError("a cart item needs a product id and a variant id")
    qty = _int_qty(int(item.get("quantity", 1)))
    unit = _unit_price_paise(product_reader, product_id, variant_id)
    for line in cart["lineItems"]:
        if line["variantId"] == variant_id:
            line["quantity"] = _int_qty(line["quantity"] + qty)
            line["unitPricePaise"] = unit  # re-resolve price on merge
            return
    cart["lineItems"].append({
        "productId": product_id,
        "variantId": variant_id,
        "quantity": qty,
        "unitPricePaise": unit,
        "requiresDelivery": bool(item.get("requires_delivery", item.get("requiresDelivery", True))),
    })


def _put(table: Any, cart: Dict[str, Any]) -> None:
    try:
        table.put_item(Item=cart)
    except Exception as error:  # noqa: BLE001
        raise NativeCartError("could not persist cart: %s" % type(error).__name__) from error


def _get(table: Any, cart_id: str) -> Optional[Dict[str, Any]]:
    try:
        return table.get_item(Key={"cartId": cart_id}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise NativeCartError("could not read cart: %s" % type(error).__name__) from error


__all__ = [
    "CART_TTL_SECONDS", "NativeCartError", "CartNotFound",
    "create", "get", "add", "set_quantity", "remove", "to_catalog_lines",
]
