"""The Wix write-back path RECORDS a payment and can never collect one (R7.4).

The test R7.4 asks for, verbatim from the requirement: "an explicit test enumerating the Wix
calls the reconciliation path can make", proving none can charge. Plus: the path is inert by
default (disabled until both the capability probe and the flag are set), it creates the Wix order
once and records the payment once across retries, and no float arithmetic touches the amount.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import wix_writeback as wb  # noqa: E402

TABLE = "stack-wecare-digital-CommerceKeys"
ORDER = "01J8Z9Q9W9EXAMPLEORDERID000000"
TXN = "pay_ABC123"
#: A real-shaped Cart V2 cart id. `mark_cart_completed` validates it as a UUID through
#: `cart_v2.identifier`, so a placeholder string would be refused before any call.
CART = "7f3a2b1c-4d5e-4f60-8a71-9b2c3d4e5f60"


@pytest.fixture
def table():
    return FakeDynamo(keys={TABLE: "orderId"}).Table(TABLE)


class _RecordingWix:
    """Captures every Wix call so a test can enumerate exactly what the path did."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, method="GET", body=None):
        self.calls.append((method.upper(), path))
        if path == "/ecom/v1/orders":
            return {"order": {"id": "wix-order-1"}}
        if "/add-payment" in path:
            return {"orderTransactions": {"orderId": "wix-order-1", "payments": body["payments"]}}
        if path.endswith("/mark-as-completed"):
            return {"cart": {"id": CART, "revision": "5", "orderPlaced": True,
                             "orderId": body["orderId"]}}
        raise AssertionError(f"unexpected Wix call: {method} {path}")


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("WIX_WRITEBACK_ENABLED", "true")
    monkeypatch.setenv("WIX_ECOM_WRITE_CONFIRMED", "true")
    monkeypatch.setenv("WIX_SITE_ID", wb.CONFIRMED_SITE_ID)
    monkeypatch.setenv("WIX_CART_V2_WRITE_CONTRACT", wb.WRITE_CONTRACT)


# ── R7.4: enumerate the calls, none can charge ──────────────────────────────────

def test_the_only_allowed_endpoints_are_create_order_record_payment_and_complete_cart():
    # The complete, static set. If someone adds an endpoint, this fails until they update the
    # test — which forces a human to look at whether the new endpoint can charge.
    #
    # Mark Cart As Completed joined on 2026-10-01. It is the third step of the external-order
    # sequence D7 specifies (Orders Create Order -> Order Transactions Add Payments -> Cart V2
    # Mark Cart As Completed); without it a paid cart is never closed. It sets `orderPlaced` and
    # attaches the order id, and moves no money. Its neighbour Cart V2 **Place Order** CAN enter
    # Wix payment collection, which is why that one is absent here and absent from
    # `cart_v2.CartV2` entirely.
    assert wb.ALLOWED_ENDPOINTS == frozenset({
        ("POST", "/ecom/v1/orders"),
        ("POST", "/ecom/v1/payments/orders/{orderId}/add-payment"),
        ("POST", "/ecom/v2/carts/{cartId}/mark-as-completed"),
    })


def test_no_allowed_endpoint_is_a_charging_endpoint():
    # Every allowlisted path, checked against the charging markers. None may match.
    for _method, template in wb.ALLOWED_ENDPOINTS:
        concrete = re.sub(r"\{[A-Za-z][A-Za-z0-9]*\}", "wix-order-1", template)
        assert not wb._endpoint_would_charge(concrete), \
            f"{template} matches a charging marker"


def test_place_order_is_not_reachable_even_though_it_is_the_v2_create_order():
    """The one Cart V2 call that could collect, refused at the guard as well as being off-list.

    Cart V2's Place Order is the documented replacement for Checkout V1's Create Order, so the
    migration makes reaching for it the natural mistake. It must fail closed.
    """
    wix = _RecordingWix()
    for path in ("/ecom/v2/carts/cart-1/place-order",
                 "/ecom/v2/carts/cart-1/create-order",
                 "/ecom/v2/carts/cart-1/checkout-url"):
        with pytest.raises((wb.WixWouldCharge, wb.WixEndpointNotAllowed)):
            wb._guarded_call(wix, method="POST", path=path)
    assert wix.calls == []


def test_the_cart_slot_cannot_smuggle_an_extra_path_segment():
    """The generalised `{name}` slot accepts only an id, so it cannot land on a neighbour.

    Worth asserting because the slot matcher was widened from a hard-coded `{orderId}` to support
    `{cartId}`, and a sloppy widening is how an allowlist stops being one.
    """
    wix = _RecordingWix()
    for path in ("/ecom/v2/carts/cart-1/extra/mark-as-completed",
                 "/ecom/v2/carts/../orders/mark-as-completed",
                 "/ecom/v2/carts//mark-as-completed",
                 "/ecom/v2/carts/cart-1?x=1/mark-as-completed"):
        with pytest.raises((wb.WixWouldCharge, wb.WixEndpointNotAllowed)):
            wb._guarded_call(wix, method="POST", path=path)
    assert wix.calls == []


@pytest.mark.parametrize("charging_path", [
    "/ecom/v1/payments/create-transaction",
    "/ecom/v1/orders/wix-order-1/charge",
    "/ecom/v1/orders/wix-order-1/capture",
    "/ecom/v1/orders/wix-order-1/payment-requests",
    "/ecom/v1/checkout/wix-order-1",
])
def test_a_charging_call_is_refused_before_any_request(charging_path):
    wix = _RecordingWix()
    with pytest.raises(wb.WixWouldCharge):
        wb._guarded_call(wix, method="POST", path=charging_path)
    # Nothing was sent.
    assert wix.calls == []


def test_an_off_allowlist_call_is_refused():
    wix = _RecordingWix()
    with pytest.raises(wb.WixEndpointNotAllowed):
        wb._guarded_call(wix, method="DELETE", path="/ecom/v1/orders/wix-order-1")
    assert wix.calls == []


def test_a_full_reconciliation_writeback_makes_only_non_charging_calls(table, enabled):
    wix = _RecordingWix()
    wb.create_wix_order(table, wix, order_id=ORDER, order_payload={"lineItems": []})
    wb.record_external_payment(table, wix, order_id=ORDER, wix_order_id="wix-order-1",
                               provider_transaction_id=TXN, amount_paise=59900)
    wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART, wix_order_id="wix-order-1")
    # Enumerate the WHOLE sequence: create-order, add-payment, mark-as-completed. R7.4 wants this
    # spelled out so "it cannot charge again" is demonstrated rather than asserted.
    assert wix.calls == [
        ("POST", "/ecom/v1/orders"),
        ("POST", "/ecom/v1/payments/orders/wix-order-1/add-payment"),
        (f"POST", f"/ecom/v2/carts/{CART}/mark-as-completed"),
    ]
    for _method, path in wix.calls:
        assert not wb._endpoint_would_charge(path)


# ── Mark Cart As Completed ──────────────────────────────────────────────────────

def test_completing_a_cart_is_idempotent(table, enabled):
    """A second call returns `completed: False` and makes no further request.

    The cart is closed once. A repeat must not re-call Wix, for the same reason order creation
    must not: a duplicate is indistinguishable from a retry at the provider.
    """
    wix = _RecordingWix()
    first = wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART,
                                   wix_order_id="wix-order-1")
    second = wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART,
                                    wix_order_id="wix-order-1")
    assert first == {"completed": True}
    assert second == {"completed": False}
    assert len(wix.calls) == 1


def test_an_ambiguous_completion_is_not_repeated(table, enabled):
    """A timeout leaves a pending marker, and a pending marker is never permission to retry.

    Its own effect rather than sharing `WIX_ORDER`: a timeout here is ambiguous about the CART, and
    folding the two together would make an unresolved completion look like an unresolved order and
    invite a second order.
    """
    def timing_out(path, method="POST", body=None):
        raise TimeoutError("uncertain write")

    with pytest.raises(TimeoutError):
        wb.mark_cart_completed(table, timing_out, order_id=ORDER, cart_id=CART,
                               wix_order_id="wix-order-1")
    wix = _RecordingWix()
    with pytest.raises(wb.WixWritebackPending):
        wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART,
                               wix_order_id="wix-order-1")
    assert wix.calls == []


def test_a_cart_completion_needs_an_order_to_attach(table, enabled):
    """Completing with no order id would lose the link, and the cart is where Wix records it."""
    wix = _RecordingWix()
    with pytest.raises(ValueError):
        wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART, wix_order_id="")
    assert wix.calls == []


@pytest.mark.parametrize("bad_cart", ["", "not-a-uuid", "../orders", None, 1])
def test_a_malformed_cart_id_never_reaches_the_provider(table, enabled, bad_cart):
    wix = _RecordingWix()
    with pytest.raises(ValueError):
        wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=bad_cart,
                               wix_order_id="wix-order-1")
    assert wix.calls == []


def test_cart_completion_is_disabled_with_the_rest_of_the_writeback(table, monkeypatch):
    """No new flag. It is inert by exactly the same four gates as the other two calls."""
    monkeypatch.delenv("WIX_WRITEBACK_ENABLED", raising=False)
    wix = _RecordingWix()
    with pytest.raises(wb.WixWritebackDisabled):
        wb.mark_cart_completed(table, wix, order_id=ORDER, cart_id=CART,
                               wix_order_id="wix-order-1")
    assert wix.calls == []


# ── inert by default ────────────────────────────────────────────────────────────

def test_disabled_by_default_even_with_the_flag_alone(monkeypatch, table):
    monkeypatch.setenv("WIX_WRITEBACK_ENABLED", "true")   # flag on
    monkeypatch.delenv("WIX_ECOM_WRITE_CONFIRMED", raising=False)  # probe NOT confirmed
    assert wb.is_enabled() is False
    with pytest.raises(wb.WixWritebackDisabled):
        wb.create_wix_order(table, _RecordingWix(), order_id=ORDER, order_payload={})


def test_disabled_with_the_probe_alone(monkeypatch, table):
    monkeypatch.delenv("WIX_WRITEBACK_ENABLED", raising=False)
    monkeypatch.setenv("WIX_ECOM_WRITE_CONFIRMED", "true")
    assert wb.is_enabled() is False


# ── idempotency: order once, payment once ───────────────────────────────────────

def test_create_order_is_idempotent(table, enabled):
    wix = _RecordingWix()
    first = wb.create_wix_order(table, wix, order_id=ORDER, order_payload={})
    second = wb.create_wix_order(table, wix, order_id=ORDER, order_payload={})
    assert first["created"] is True
    assert second["created"] is False
    assert second["wixOrderId"] == "wix-order-1"
    # Only ONE create call was made across two invocations.
    assert [c for c in wix.calls if c == ("POST", "/ecom/v1/orders")] == \
        [("POST", "/ecom/v1/orders")]


def test_record_payment_is_idempotent(table, enabled):
    wix = _RecordingWix()
    first = wb.record_external_payment(table, wix, order_id=ORDER, wix_order_id="wix-order-1",
                                       provider_transaction_id=TXN, amount_paise=59900)
    second = wb.record_external_payment(table, wix, order_id=ORDER, wix_order_id="wix-order-1",
                                        provider_transaction_id=TXN, amount_paise=59900)
    assert first["recorded"] is True
    assert second["recorded"] is False
    add_calls = [c for c in wix.calls if "/add-payment" in c[1]]
    assert len(add_calls) == 1


# ── money is integer paise, no float ────────────────────────────────────────────

@pytest.mark.parametrize("paise,expected", [
    (59900, "599.00"), (1, "0.01"), (100, "1.00"), (349900, "3499.00"), (10, "0.10")])
def test_paise_renders_without_float(paise, expected):
    assert wb._paise_to_decimal_string(paise) == expected


def test_record_payment_rejects_non_integer_amount(table, enabled):
    with pytest.raises(TypeError):
        wb.record_external_payment(table, _RecordingWix(), order_id=ORDER,
                                   wix_order_id="wix-order-1", provider_transaction_id=TXN,
                                   amount_paise=599.0)  # float refused


@pytest.mark.parametrize('field,value', [
    ('WIX_SITE_ID', 'wrong-site'), ('WIX_SITE_ID', ''),
    ('WIX_CART_V2_WRITE_CONTRACT', ''), ('WIX_CART_V2_WRITE_CONTRACT', 'v1')])
def test_site_and_contract_gates_block_all_order_writes(table, enabled, monkeypatch, field, value):
    monkeypatch.setenv(field, value)
    wix = _RecordingWix()
    with pytest.raises(wb.WixWritebackDisabled):
        wb.create_wix_order(table, wix, order_id=ORDER, order_payload={})
    assert wix.calls == []


def test_timeout_cannot_create_a_second_wix_order(table, enabled):
    calls = []
    def uncertain(*args, **kwargs):
        calls.append(args)
        raise TimeoutError('could have succeeded')
    with pytest.raises(TimeoutError):
        wb.create_wix_order(table, uncertain, order_id=ORDER, order_payload={})
    with pytest.raises(wb.WixWritebackPending):
        wb.create_wix_order(table, uncertain, order_id=ORDER, order_payload={})
    assert len(calls) == 1


def test_incomplete_wix_response_is_not_recorded_as_success(table, enabled):
    with pytest.raises(wb.WixWritebackPending):
        wb.create_wix_order(table, lambda *a, **k: {}, order_id=ORDER, order_payload={})
    with pytest.raises(wb.WixWritebackPending):
        wb.create_wix_order(table, _RecordingWix(), order_id=ORDER, order_payload={})


def test_confirmed_payment_cannot_be_reused_with_different_amount(table, enabled):
    wix = _RecordingWix()
    kwargs = dict(order_id=ORDER, wix_order_id='wix-order-1', provider_transaction_id=TXN)
    wb.record_external_payment(table, wix, amount_paise=59900, **kwargs)
    with pytest.raises(wb.WixWritebackPending):
        wb.record_external_payment(table, wix, amount_paise=59901, **kwargs)
    assert len(wix.calls) == 1


def test_created_order_total_mismatch_never_creates_a_second_order(table, enabled):
    calls = []
    def wix(path, method='GET', body=None):
        calls.append(path)
        return {'order': {'id': 'created-order', 'currency': 'INR',
                          'priceSummary': {'total': {'amount': '98.00'}}}}
    payload = {'currency': 'INR', 'priceSummary': {'total': {'amount': '99.00'}}}
    for _ in range(2):
        with pytest.raises(wb.WixWritebackPending):
            wb.create_wix_order(table, wix, order_id=ORDER, order_payload=payload)
    assert calls == ['/ecom/v1/orders']
