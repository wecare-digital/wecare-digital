"""native_cart: CartTable CRUD with server-authoritative prices, feeding price_cart.
Offline fake table; proves client prices are ignored and the cart quotes natively.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import native_cart as nc  # noqa: E402
from lambda_utils.ecommerce import catalog_pricing as cp  # noqa: E402


class FakeCartTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["cartId"]] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get(Key["cartId"])
        return {"Item": dict(it)} if it else {}


PRODUCTS = {
    "prod-1": {"id": "prod-1", "status": "active",
               "variants": [{"sku": "V1", "priceMinor": 59900, "inventory": 5},
                            {"sku": "V2", "priceMinor": 10000, "inventory": 2}]},
    "prod-archived": {"id": "prod-archived", "status": "archived",
                      "variants": [{"sku": "VA", "priceMinor": 100}]},
}


def reader(pid):
    return PRODUCTS.get(pid)


def test_create_resolves_price_server_side_ignoring_client_price():
    t = FakeCartTable()
    cart = nc.create(t, reader, [
        {"product_id": "prod-1", "variant_id": "V1", "quantity": 2, "unitPricePaise": 1}])
    # client sent 1 paise; server price is authoritative
    assert cart["lineItems"][0]["unitPricePaise"] == 59900
    assert cart["lineItems"][0]["quantity"] == 2


def test_add_merges_same_variant_and_requotes_price():
    t = FakeCartTable()
    cart = nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 1}])
    cart = nc.add(t, reader, cart["cartId"], {"product_id": "prod-1", "variant_id": "V1",
                                              "quantity": 2})
    assert len(cart["lineItems"]) == 1
    assert cart["lineItems"][0]["quantity"] == 3


def test_set_quantity_and_remove():
    t = FakeCartTable()
    cart = nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 1},
                                 {"product_id": "prod-1", "variant_id": "V2", "quantity": 1}])
    cid = cart["cartId"]
    nc.set_quantity(t, cid, "V1", 4)
    cart = nc.get(t, cid)
    assert next(l for l in cart["lineItems"] if l["variantId"] == "V1")["quantity"] == 4
    cart = nc.remove(t, cid, "V2")
    assert [l["variantId"] for l in cart["lineItems"]] == ["V1"]


def test_archived_product_refused():
    t = FakeCartTable()
    with pytest.raises(ValueError):
        nc.create(t, reader, [{"product_id": "prod-archived", "variant_id": "VA", "quantity": 1}])


def test_missing_cart_raises_cart_not_found():
    t = FakeCartTable()
    with pytest.raises(nc.CartNotFound):
        nc.get(t, "nope")


def test_cart_quotes_through_price_cart():
    """The cart's native lines feed catalog_pricing.price_cart end to end."""
    t = FakeCartTable()
    cart = nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 2},
                                 {"product_id": "prod-1", "variant_id": "V2", "quantity": 1}])
    lines = nc.to_catalog_lines(cart)
    summary = cp.price_cart(lines)
    assert summary.subtotal_paise == 2 * 59900 + 10000 == 129800
    assert summary.total_paise == 129800


def test_quantity_bounds_enforced():
    t = FakeCartTable()
    with pytest.raises(ValueError):
        nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 0}])
    with pytest.raises(ValueError):
        nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 100001}])


def test_ttl_set_on_create():
    t = FakeCartTable()
    cart = nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": 1}],
                     clock=lambda: 1000)
    assert cart["expiresTtl"] == 1000 + nc.CART_TTL_SECONDS
