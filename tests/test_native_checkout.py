"""native_checkout.quote_native_cart composes the whole native supply chain into a
QuoteSnapshot with no Wix. Offline fakes; proves the payable amount and stock gate.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import native_cart as nc  # noqa: E402
from lambda_utils.ecommerce import native_checkout as ncheck  # noqa: E402
from lambda_utils.ecommerce import native_shipping as sh  # noqa: E402
from lambda_utils.ecommerce import native_inventory as inv  # noqa: E402


PRODUCTS = {
    "prod-1": {"id": "prod-1", "status": "active",
               "variants": [{"sku": "V1", "priceMinor": 50000, "inventory": 5}]},
}


def reader(pid):
    return PRODUCTS.get(pid)


class FakeCartTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["cartId"]] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get(Key["cartId"])
        return {"Item": dict(it)} if it else {}


def _cart(qty=2):
    t = FakeCartTable()
    return nc.create(t, reader, [{"product_id": "prod-1", "variant_id": "V1", "quantity": qty}],
                     customer_id="cust-1", clock=lambda: 1000)


def test_quote_native_cart_produces_payable_snapshot():
    cart = _cart(qty=2)  # subtotal 100000
    snap = ncheck.quote_native_cart(
        cart, product_reader=reader, customer_id="cust-1",
        created_at=1000, ttl_seconds=900,
        shipping_policy=sh.ShippingPolicy(flat_rate_paise=0),  # free
        gst_bps=0,  # inclusive prices
    )
    # collection = 100000 (no discount, free delivery, inclusive tax); + fee + GST
    assert snap.quote.collection_before_convenience_paise == 100000
    assert snap.quote.total_payable_paise > 100000
    # the native site tag is carried in the frozen snapshot data
    assert "aws-native" in str(snap.frozen_data)


def test_quote_applies_coupon_and_shipping():
    cart = _cart(qty=2)  # subtotal 100000
    coupon = {"discountKind": "PERCENT_OFF", "percentOffBps": 1000}  # 10% -> 10000
    snap = ncheck.quote_native_cart(
        cart, product_reader=reader, customer_id="cust-1",
        created_at=1000, ttl_seconds=900,
        shipping_policy=sh.ShippingPolicy(flat_rate_paise=9900, free_above_paise=200000),
        coupon_definition=coupon, gst_bps=0,
    )
    # collection = 100000 - 10000 + 9900 = 99900
    assert snap.quote.collection_before_convenience_paise == 99900


def test_quote_fails_closed_on_insufficient_stock():
    cart = _cart(qty=2)
    PRODUCTS["prod-1"]["variants"][0]["inventory"] = 1  # less than requested
    try:
        with pytest.raises(inv.OutOfStock):
            ncheck.quote_native_cart(
                cart, product_reader=reader, customer_id="cust-1",
                created_at=1000, ttl_seconds=900,
                shipping_policy=sh.ShippingPolicy(flat_rate_paise=0))
    finally:
        PRODUCTS["prod-1"]["variants"][0]["inventory"] = 5  # restore


def test_empty_cart_rejected():
    cart = {"cartId": "c1", "lineItems": [], "updatedAt": 1}
    with pytest.raises(Exception):
        ncheck.quote_native_cart(
            cart, product_reader=reader, customer_id="c", created_at=1, ttl_seconds=1,
            shipping_policy=sh.ShippingPolicy())
