"""Phase O-1 services on the ONE live checkout path: priced like any order, asserted per line.

Drives `checkout/handler.py` end to end through `_website_prepare` and `_create` with the
contribution harness (tests/contribution_env.py + the stateful Cart V2 fake), so what is pinned is
the shipped handler, not a copy. Offline: FakeDynamo, a recording Razorpay stub, no network.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import contribution_wix  # noqa: E402
from contribution_env import (  # noqa: E402
    ATTEMPTS_TABLE, KEYS_TABLE, WIX_ADDRESS, body_of, create_event, make_env, prepare_event)
from contribution_wix import (  # noqa: E402
    STORES_APP_ID, ContributionWix, contribution_line, kiosk_line)

from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
AMEND = "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b"
DROP_DOCS = "db166bc8-a763-41ec-9f65-0f718f18155a"
VAULT = "dcff995e-448c-493a-9259-f6a82ccdc2b4"
INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
PAYABLE_ONE_SERVICE = 10193         # 9900 + fee 248 + GST-on-fee 45


def service(variant=SUBMIT, quantity=1):
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": PRODUCT,
                                 "options": {"variantId": variant}}, "quantity": quantity}


def services_wix(monkeypatch, *, rupees=99, **kwargs):
    """The fake taught the services product: four visible variants, PHYSICAL, Rs.99 each."""
    wix = ContributionWix(**kwargs)
    monkeypatch.setitem(contribution_wix.UNIT_RUPEES, PRODUCT, rupees)
    wix.variants[PRODUCT] = [SUBMIT, AMEND, DROP_DOCS, VAULT]
    wix.product_type[PRODUCT] = "PHYSICAL"
    return wix


def payrefs(fake):
    return [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]


def prepare(h, basket, **over):
    over.setdefault("serviceIntentId", INTENT)
    return h.handler(prepare_event(basket, **over), None)


# ── the happy path ────────────────────────────────────────────────────────────

def test_a_services_only_basket_is_payable_at_ordinary_order_pricing(monkeypatch):
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))

    def exempt_must_not_run(*_a, **_k):
        raise AssertionError("a service is NOT fee-exempt")

    monkeypatch.setattr(h.checkout_pricing, "exempt_quote", exempt_must_not_run)
    response = prepare(h, [service()])
    assert response["statusCode"] == 200, body_of(response)
    assert body_of(response)["status"] == "CHECKOUT_OPTIONS_READY"
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == PAYABLE_ONE_SERVICE == cp.compute_quote(9900) \
        .total_payable_paise
    assert [order["amount"] for order in h.gateway_orders] == [PAYABLE_ONE_SERVICE]
    # No address is written onto a request's cart; the one Wix-resolved method is selected.
    assert not any(method == "PATCH" for method, _path in wix.calls)
    assert any(path.endswith("/set-delivery-method") for _m, path in wix.calls)


def test_the_payref_carries_exactly_the_service_join(monkeypatch):
    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    assert prepare(h, [service(AMEND)])["statusCode"] == 200
    [row] = payrefs(fake)
    assert row["serviceLine"] == {"kind": "REQUEST_AMENDMENT", "variantId": AMEND,
                                  "paise": 9900, "intentId": INTENT}


def test_a_non_service_payref_is_unchanged(monkeypatch):
    wix = ContributionWix(delivery_address=dict(WIX_ADDRESS))
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    assert h.handler(prepare_event([kiosk_line(1)]), None)["statusCode"] == 200
    [row] = payrefs(fake)
    assert "serviceLine" not in row
    assert set(row) == {"orderId", "kind", "referenceId", "paymentAttemptId", "reservedAt",
                        "customerId", "amountPaise", "payablePaise", "giftCardRedeemPaise",
                        "currency", "checkoutMode", "wixCartId", "cartRevision", "quoteHash",
                        "collectionPaise", "quoteExpiresAt", "policyVersion",
                        "providerOrderId"}


def test_a_mixed_basket_is_priced_like_any_order_and_the_line_assertion_holds(monkeypatch):
    wix = services_wix(monkeypatch, delivery_address=dict(WIX_ADDRESS))
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = prepare(h, [kiosk_line(1), service()])
    assert response["statusCode"] == 200, body_of(response)
    collection = 2499900 + 9900
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == cp.compute_quote(collection).total_payable_paise


def test_a_service_beside_a_contribution_is_priced_like_any_order(monkeypatch):
    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    response = prepare(h, [contribution_line(), service()])
    assert response["statusCode"] == 200, body_of(response)
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == cp.compute_quote(10000 + 9900).total_payable_paise


def test_a_coupon_on_a_service_basket_is_accepted(monkeypatch):
    wix = services_wix(monkeypatch, discount_rupees=10,
                       coupons=[{"id": "c1", "code": "TENOFF"}])
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = prepare(h, [service()])
    assert response["statusCode"] == 200, body_of(response)
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == cp.compute_quote(8900).total_payable_paise


# ── fail closed, before money moves ───────────────────────────────────────────

def _nothing_reserved(h, fake):
    assert h.gateway_orders == []
    assert fake.all_rows(ATTEMPTS_TABLE) == []
    assert payrefs(fake) == []


@pytest.mark.parametrize("rupees", [98, 100])
def test_a_wix_price_edit_refuses_with_nothing_reserved(monkeypatch, rupees):
    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch, rupees=rupees))
    response = prepare(h, [service()])
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_PRICE_CHANGED")
    assert body_of(response)["message"].endswith("Nothing has been charged.")
    _nothing_reserved(h, fake)


def test_a_delivery_charge_on_a_services_only_basket_refuses(monkeypatch):
    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch, delivery_rupees=40))
    response = prepare(h, [service()])
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_PRICE_CHANGED")
    _nothing_reserved(h, fake)


def test_wix_demanding_delivery_for_a_services_basket_is_not_payable(monkeypatch):
    wix = services_wix(monkeypatch, require_delivery_on_calculate=True,
                       offered_delivery_options=[])
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = prepare(h, [service()])
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_NOT_PAYABLE")
    _nothing_reserved(h, fake)


@pytest.mark.parametrize("variant", [DROP_DOCS, VAULT])
def test_drop_docs_and_vault_are_refused_before_any_wix_call(monkeypatch, variant):
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    response = prepare(h, [service(variant)])
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_NOT_OFFERED")
    assert wix.calls == []
    _nothing_reserved(h, fake)


def test_a_missing_intent_is_refused_before_any_wix_call(monkeypatch):
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    response = h.handler(prepare_event([service()]), None)
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_INTENT_REQUIRED")
    assert wix.calls == []
    _nothing_reserved(h, fake)


def test_cart_v2_disabled_refuses_with_503(monkeypatch):
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    monkeypatch.setenv("WIX_CART_V2_ENABLED", "false")
    response = prepare(h, [service()])
    assert (response["statusCode"], body_of(response)["error"]) == (503, "SERVICE_UNAVAILABLE")
    assert wix.calls == []


@pytest.mark.parametrize("basket,code", [
    ([service(quantity=2)], "SERVICE_INVALID_QUANTITY"),
    ([service(SUBMIT), service(AMEND)], "SERVICE_ONE_PER_ORDER"),
])
def test_quantity_and_one_per_order(monkeypatch, basket, code):
    h, _fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    response = prepare(h, basket)
    assert (response["statusCode"], body_of(response)["error"]) == (409, code)
    assert wix.calls == []


# ── the retained in-WhatsApp route ────────────────────────────────────────────

@pytest.mark.parametrize("basket", [[service()], [kiosk_line(1), service(AMEND)],
                                    [service(DROP_DOCS)]])
def test_create_refuses_a_services_basket_with_zero_wix_calls(monkeypatch, basket):
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    response = h.handler(create_event(basket), None)
    assert (response["statusCode"], body_of(response)["error"]) == (409, "SERVICE_WEBSITE_ONLY")
    assert wix.calls == [] and fake.all_rows(ATTEMPTS_TABLE) == [] and payrefs(fake) == []


def test_create_refuses_before_any_io_at_the_top_of_the_function():
    """Structural: the refusal is the first thing after the LINE_ITEMS check, and it RETURNS."""
    tree = ast.parse((ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text())
    create = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_create")
    statements = [s for s in create.body
                  if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    guard = statements[2]
    assert isinstance(guard, ast.If)
    assert "has_service_line" in ast.unparse(guard.test)
    assert isinstance(guard.body[-1], ast.Return)
    assert "SERVICE_WEBSITE_ONLY" in ast.unparse(guard.body[-1])


def test_the_service_arms_precede_the_cart_contract_parent_arm():
    tree = ast.parse((ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text())
    prepare_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == "_website_prepare")
    handlers = [ast.unparse(h.type) for n in ast.walk(prepare_fn) if isinstance(n, ast.Try)
                for h in n.handlers if h.type is not None]
    parent = handlers.index("cart_v2.CartContractError")
    assert handlers.index("ServicePriceChanged") < parent
    assert handlers.index("ServiceNotPayable") < parent


# ── a second request after the first was paid ─────────────────────────────────

def test_a_second_submit_request_after_the_first_was_paid_is_payable(monkeypatch):
    """The repeat case. Measured live (purchase_intent.select_offered_delivery_method's docstring):
    Wix populates `deliveryInfo.address` itself, from the site location, on a cart it created --
    so the reused services cart carries an address and `_settle_saved_cart`'s no-delivery abandon
    mints a FRESH cart. A fresh cart is a different basket identity, so the windowless
    `CARTBASKET#` paid-basket guard does not see the first purchase. The guard is untouched."""
    wix = services_wix(monkeypatch)
    h, fake, wix = make_env(monkeypatch, wix=wix)
    first = prepare(h, [service()], requestKey="rk-service-1")
    assert first["statusCode"] == 200, body_of(first)
    attempts = fake.Table(ATTEMPTS_TABLE)
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    attempts.put_item(Item={**attempt, "status": "PAYMENT_PAID", "paidAt": 1})
    first_cart = wix.cart_id
    wix.delivery_address = dict(WIX_ADDRESS)          # what Wix leaves on the cart it created
    second = prepare(h, [service()], requestKey="rk-service-2",
                     serviceIntentId="01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60")
    assert second["statusCode"] == 200, body_of(second)
    assert body_of(second)["status"] == "CHECKOUT_OPTIONS_READY"
    assert wix.cart_id != first_cart
    assert len(h.gateway_orders) == 2


def test_the_paid_basket_guard_still_refuses_the_identical_basket_on_the_identical_cart(
        monkeypatch):
    """FINDING, recorded rather than worked around: with NO address on the reused cart (not the
    measured live shape) the same basket on the same cart is the guard's own case and it refuses
    with CART_ALREADY_PAID -- the same answer an ordinary repeat basket gets. Not weakened."""
    h, fake, wix = make_env(monkeypatch, wix=services_wix(monkeypatch))
    assert prepare(h, [service()], requestKey="rk-service-1")["statusCode"] == 200
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    fake.Table(ATTEMPTS_TABLE).put_item(Item={**attempt, "status": "PAYMENT_PAID", "paidAt": 1})
    second = prepare(h, [service()], requestKey="rk-service-2")
    assert second["statusCode"] == 409
    assert body_of(second)["reason"] == "CART_ALREADY_PAID"
    assert len(h.gateway_orders) == 1
