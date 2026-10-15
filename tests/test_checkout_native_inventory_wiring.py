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


@pytest.mark.parametrize("frozen", [{}, {"items": []}, {"items": "not-a-list"}])
def test_stock_is_reserved_only_against_the_server_frozen_basket(native, frozen):
    """Stock is reserved against the lines the server priced and froze, never anything else. A
    snapshot with no frozen basket is refused before a reservation or a gateway call is built."""
    h, patch = native
    patch.setattr(h.native_inventory_txn, "reserve_basket",
                  lambda *a, **k: pytest.fail("stock reserved"))
    patch.setattr(h.razorpay_orders, "create_order", lambda **kw: pytest.fail("gateway called"))
    with pytest.raises(ValueError, match="frozen basket"):
        h._website_order_creator(SimpleNamespace(frozen_data=frozen))
