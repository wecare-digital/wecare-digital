"""Stock must be reserved before gateway creation; ambiguity must not restock."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))


@pytest.fixture
def native(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "checkout_inventory_wiring", ROOT / "amplify/functions/ecommerce/checkout/handler.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
    monkeypatch.setenv("NATIVE_STOCK_RESERVATION_ENABLED", "true")
    monkeypatch.setattr(h.boto3, "client", lambda *a, **k: object())
    monkeypatch.setattr(h, "_native_product_reader", lambda: lambda _id: None)
    monkeypatch.setattr(h, "_keys_table", lambda: SimpleNamespace(get_item=lambda **k: {}))
    return h, monkeypatch


def snapshot():
    return SimpleNamespace(frozen_data={"items": [
        {"productId": "p", "variantId": "v", "quantity": 2, "unitPricePaise": 9900}]})


def test_reserves_server_frozen_lines_before_gateway_call(native):
    h, patch = native
    calls = []
    def reserve(*args, **kwargs):
        calls.append("stock")
        assert kwargs["items"] == snapshot().frozen_data["items"]
        assert kwargs["attempt_id"] == "attempt-1"
    patch.setattr(h.native_inventory_txn, "reserve_basket", reserve)
    patch.setattr(h.razorpay_orders, "create_order", lambda **kw: calls.append("gateway") or {"id": "order-1"})
    assert h._website_order_creator(snapshot())(
        amount_paise=19800, receipt="receipt-1", notes={"paymentAttemptId": "attempt-1"}) == {"id": "order-1"}
    assert calls == ["stock", "gateway"]


def test_stock_failure_prevents_gateway_creation(native):
    h, patch = native
    def fail(*a, **k):
        raise h.native_inventory_txn.ReservationUnavailable("unconfirmed")
    patch.setattr(h.native_inventory_txn, "reserve_basket", fail)
    patch.setattr(h.razorpay_orders, "create_order", lambda **kw: pytest.fail("gateway called"))
    with pytest.raises(h.native_inventory_txn.ReservationUnavailable):
        h._website_order_creator(snapshot())(
            amount_paise=19800, receipt="receipt-1", notes={"paymentAttemptId": "attempt-1"})


def test_ambiguous_gateway_failure_does_not_release_stock(native):
    h, patch = native
    calls = []
    patch.setattr(h.native_inventory_txn, "reserve_basket", lambda *a, **kw: calls.append("stock"))
    patch.setattr(h.native_inventory_txn, "release_basket", lambda *a, **kw: pytest.fail("unsafe release"))
    def timeout(**kw):
        raise TimeoutError("synthetic ambiguity")
    patch.setattr(h.razorpay_orders, "create_order", timeout)
    with pytest.raises(TimeoutError):
        h._website_order_creator(snapshot())(
            amount_paise=19800, receipt="receipt-1", notes={"paymentAttemptId": "attempt-1"})
    assert calls == ["stock"]


def test_stock_activation_is_explicit(native):
    h, patch = native
    patch.delenv("NATIVE_STOCK_RESERVATION_ENABLED")
    assert h._website_order_creator(snapshot()) is h.razorpay_orders.create_order


def test_stock_gate_refuses_legacy_pricing(native):
    """The reservation guard still refuses to run against anything but AWS-native pricing.

    Native is now UNCONDITIONAL: `_supply_mode()` returns AWS_NATIVE regardless of CHECKOUT_MODE,
    so setting the legacy CHECKOUT_MODE=WIX_HEADLESS env no longer flips the mode. The money
    invariant the test guards — reserving stock only under native pricing — is kept by exercising
    the guard directly: if `_supply_mode()` were ever non-native, `_website_order_creator` must
    raise rather than reserve against a price it did not compute.
    """
    h, patch = native
    patch.setattr(h, "_supply_mode", lambda: "WIX_HEADLESS")
    with pytest.raises(ValueError, match="AWS-native"):
        h._website_order_creator(snapshot())
