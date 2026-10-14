"""CHECKOUT_MODE=AWS_NATIVE routes _website_snapshot through the native supply
engine (ProductsTable), with NO Wix call. Default (WIX_HEADLESS) is unchanged.

The handler is loaded BY PATH under a unique module name (the repo has dozens of
handler.py files).
"""
import importlib.util
import json
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


def test_service_prices_use_native_catalog_even_without_cutover_flags(monkeypatch):
    h = _load()
    monkeypatch.delenv("CHECKOUT_MODE", raising=False)
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    monkeypatch.setattr(h, "_native_variant_reader", lambda: lambda _id: {
        "priceMinor": 9900, "currency": "INR", "status": "active",
    })
    monkeypatch.setattr(h, "_wix_request", lambda *a, **k: pytest.fail("Wix called"))
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 200
    assert all(p["paise"] == 9900 for p in json.loads(response["body"])["prices"].values())


def test_service_prices_fail_closed_when_native_catalog_has_no_prices(monkeypatch):
    h = _load()
    monkeypatch.setattr(h, "_native_variant_reader", lambda: lambda _id: None)
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"] == h.SERVICE_PRICES_UNAVAILABLE


def test_service_prices_do_not_expose_catalog_failure_details(monkeypatch):
    h = _load()
    def unavailable():
        raise RuntimeError("synthetic-private-diagnostic")
    monkeypatch.setattr(h, "_native_variant_reader", unavailable)
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 503
    assert "synthetic-private-diagnostic" not in response["body"]


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



def test_native_quote_accepts_the_actual_storefront_catalog_reference(monkeypatch):
    """The browser sends nested catalogReference, not top-level productId fields."""
    h = _load()
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
    monkeypatch.setattr(
        h.wix_ecom, "create_checkout",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no Wix call")),
    )
    monkeypatch.setattr(
        h, "_native_product_reader", lambda: (lambda pid: _product_row()),
    )
    items = [{
        "catalogReference": {
            "catalogItemId": PRODUCT_UUID,
            "appId": "storefront-compatibility-identifier",
            "options": {"variantId": VARIANT_UUID},
        },
        "quantity": 2,
        "unitPricePaise": 1,  # client tampering must be ignored
    }]
    snapshot, calculated = h._website_snapshot(_Identity(), items, now=1000)
    assert calculated is None
    assert snapshot.quote.collection_before_convenience_paise == 119800
    assert snapshot.frozen_data["items"] == [{
        "productId": PRODUCT_UUID,
        "variantId": VARIANT_UUID,
        "quantity": 2,
        "unitPricePaise": 59900,
    }]



def _native_env(monkeypatch, row=None):
    h = _load()
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
    monkeypatch.setattr(
        h, "_native_product_reader",
        lambda: (lambda pid: row if pid == PRODUCT_UUID else None),
    )
    return h


def _line(qty=1, *, product=PRODUCT_UUID, variant=VARIANT_UUID,
          client_price=1, claims_digital=True):
    return {
        "catalogReference": {
            "catalogItemId": product, "options": {"variantId": variant},
        },
        "quantity": qty,
        "unitPricePaise": client_price,
        "requiresDelivery": not claims_digital,
    }


def test_same_native_basket_has_stable_cart_id_for_multiple_requests(monkeypatch):
    h = _native_env(monkeypatch, _product_row())
    lines = [_line()]
    first, _ = h._website_snapshot(_Identity(), lines, now=1000)
    second, _ = h._website_snapshot(_Identity(), lines, now=1018)
    assert first.cart_id == second.cart_id
    assert first.cart_revision == second.cart_revision == 0


def test_line_order_does_not_create_a_second_payment_identity(monkeypatch):
    h = _native_env(monkeypatch, _product_row())
    lines_a = [_line(qty=1), _line(qty=2)]
    a, _ = h._website_snapshot(_Identity(), lines_a, now=1000)
    b, _ = h._website_snapshot(_Identity(), [_line(qty=3)], now=1001)
    assert a.cart_id == b.cart_id
    assert a.quote.collection_before_convenience_paise == 3 * 59900
    assert a.frozen_data["items"] == [{
        "productId": PRODUCT_UUID, "variantId": VARIANT_UUID,
        "quantity": 3, "unitPricePaise": 59900,
    }]


def test_separate_baskets_or_customers_cannot_share_payment_identity(monkeypatch):
    h = _native_env(monkeypatch, _product_row())
    a, _ = h._website_snapshot(_Identity(), [_line(qty=1)], now=1000)
    b, _ = h._website_snapshot(_Identity(), [_line(qty=2)], now=1001)
    c, _ = h._website_snapshot(_Identity(customer_id="cust-2"), [_line(qty=1)], now=1002)
    assert len({a.cart_id, b.cart_id, c.cart_id}) == 3


def test_browser_cannot_force_no_delivery_or_override_aws_price(monkeypatch):
    h = _native_env(monkeypatch, _product_row())
    snap, _ = h._website_snapshot(
        _Identity(), [_line(client_price=1, claims_digital=True)], now=1000,
    )
    assert snap.frozen_data["items"][0]["unitPricePaise"] == 59900


@pytest.mark.parametrize("quantity", [None, 0, -1, True, 1.5, "1", 100001])
def test_native_checkout_refuses_bad_quantities_without_pricing(monkeypatch, quantity):
    h = _native_env(monkeypatch, _product_row())
    with pytest.raises(ValueError):
        h._website_snapshot(_Identity(), [_line(qty=quantity)], now=1000)


def test_native_checkout_refuses_unknown_variant_instead_of_base_price(monkeypatch):
    h = _native_env(monkeypatch, _product_row())
    with pytest.raises(ValueError):
        h._website_snapshot(
            _Identity(), [_line(variant="missing-variant")], now=1000,
        )


@pytest.mark.parametrize("status", ["draft", "archived"])
def test_unpublished_products_are_unpurchaseable(monkeypatch, status):
    row = _product_row()
    row["status"] = status
    h = _native_env(monkeypatch, row)
    with pytest.raises(ValueError):
        h._website_snapshot(_Identity(), [_line()], now=1000)


def test_aggregate_quantity_cannot_evade_stock_validation(monkeypatch):
    row = _product_row()
    row["variants"][0]["inventory"] = 1
    h = _native_env(monkeypatch, row)
    from lambda_utils.ecommerce.native_inventory import OutOfStock
    with pytest.raises(OutOfStock):
        h._website_snapshot(_Identity(), [_line(qty=1), _line(qty=1)], now=1000)
