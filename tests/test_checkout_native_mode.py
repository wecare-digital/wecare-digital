"""CHECKOUT_MODE=AWS_NATIVE routes _website_snapshot through the native supply
engine (ProductsTable), with NO Wix call. Default (WIX_HEADLESS) is unchanged.

The handler is loaded BY PATH under a unique module name (the repo has dozens of
handler.py files).
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
_HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"


class _Identity:
    def __init__(self, customer_id="cust-1", phone="+919330994400"):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-1"


def _load():
    spec = importlib.util.spec_from_file_location("checkout_native_under_test", _HANDLER)
    h = importlib.util.module_from_spec(spec)
    sys.modules["checkout_native_under_test"] = h
    spec.loader.exec_module(h)
    return h


PRODUCT_UUID = "11111111-1111-4111-8111-111111111111"
VARIANT_UUID = "22222222-2222-4222-8222-222222222222"


def _product_row():
    return {"id": PRODUCT_UUID, "status": "active",
            "variants": [{"sku": VARIANT_UUID, "priceMinor": 59900, "inventory": 5}]}


def test_default_mode_is_wix_headless(monkeypatch):
    h = _load()
    monkeypatch.delenv("CHECKOUT_MODE", raising=False)
    assert h._supply_mode() == "WIX_HEADLESS"


@pytest.mark.parametrize("val", ["AWS_NATIVE", "aws", "native"])
def test_aws_native_mode_resolves(monkeypatch, val):
    h = _load()
    monkeypatch.setenv("CHECKOUT_MODE", val)
    assert h._supply_mode() == "AWS_NATIVE"


def test_native_snapshot_prices_from_products_table_without_wix(monkeypatch):
    h = _load()
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")

    # If the native branch ever called Wix, this would raise.
    def _boom(*a, **k):
        raise AssertionError("native mode must not call wix_ecom.create_checkout")
    monkeypatch.setattr(h.wix_ecom, "create_checkout", _boom)

    # Stub the ProductsTable reader to avoid any AWS call.
    monkeypatch.setattr(h, "_native_product_reader", lambda: (lambda pid: _product_row()))

    line_items = [{"productId": PRODUCT_UUID, "variantId": VARIANT_UUID,
                   "quantity": 2, "requiresDelivery": True}]
    snapshot, calculated = h._website_snapshot(_Identity(), line_items, now=1000)

    assert calculated is None
    # subtotal 2 * 59900 = 119800; free delivery, inclusive tax -> collection 119800
    assert snapshot.quote.collection_before_convenience_paise == 119800
    assert snapshot.quote.total_payable_paise > 119800
    assert "aws-native" in str(snapshot.frozen_data)


def test_native_mode_ignores_client_supplied_price(monkeypatch):
    h = _load()
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
    monkeypatch.setattr(h.wix_ecom, "create_checkout",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no wix")))
    monkeypatch.setattr(h, "_native_product_reader", lambda: (lambda pid: _product_row()))

    # client tries to send a tiny price; server must price from ProductsTable (59900)
    line_items = [{"productId": PRODUCT_UUID, "variantId": VARIANT_UUID,
                   "quantity": 1, "unitPricePaise": 1, "requiresDelivery": True}]
    snapshot, _ = h._website_snapshot(_Identity(), line_items, now=1000)
    assert snapshot.quote.collection_before_convenience_paise == 59900
