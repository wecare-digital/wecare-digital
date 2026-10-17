"""Drop Docs (Rs.350) and Vault (Rs.49) end to end, in integer paise, on the ONE checkout.

The two new fixed-price lines reuse the Phase O-1 money path verbatim: `POST
/ecommerce/prepare-checkout` -> the native ProductsTable quote -> ONE Razorpay order ->
verify-callback / razorpay-webhook reconciliation -> ONE activation. Nothing here adds a payment
implementation, so what has to be pinned is that the SAME guards hold at the two new amounts.

What is pinned, and why each is a property rather than a shape:

* **(a)(b) The payable is ordinary order pricing, to the paise.** 35000 -> fee 875 + GST 158 =
  36033; 4900 -> 123 + 22 = 5045. Asserted against the real `compute_quote`, as `int`s, and
  against what the gateway was actually asked for -- so a services-only basket that acquired
  delivery or supply tax would fail here.
* **(c) The per-line guard reads THIS variant's price from the frozen native quote**, charges a
  catalogue price edit inside the catastrophe rail, and fails closed outside it or on a
  sibling's line.
* **(d) Currency is compared explicitly.** `'inr'` and `'USD'` are both CURRENCY_MISMATCH at
  activation -- never inferred from the amount, never case-folded into agreement.
* **(e) Replay safety.** One captured payment delivered three times by the webhook plus once by
  verify-callback yields exactly one `PAYMENTATTEMPT#` claim, one `ORDER#` pointer and one `REQ#`
  for each new kind.

NO FLOAT ANYWHERE, including in the test arithmetic: every figure below is an integer paise
literal or an integer expression. Offline: FakeDynamo, the native catalogue descriptor, a
recording Razorpay stub at the HTTP seam. No AWS, no network, no credential.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import contribution_catalog  # noqa: E402
from contribution_catalog import NativeCatalog  # noqa: E402
from contribution_env import ATTEMPTS_TABLE, KEYS_TABLE, body_of, make_env, prepare_event  # noqa
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from service_requests_fake_dynamo import RequestTable  # noqa: E402
from test_one_service_money_path import LambdaToReceiver, RecordingRazorpay  # noqa: E402

from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import order_creation, order_keys  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402
from synthetic_service_catalog import configure as configure_services  # noqa: E402

configure_services(sr)
from lambda_utils.integrations import razorpay_verify  # noqa: E402

PRODUCT = "11111111-1111-4111-8111-111111111111"
SUBMIT = "22222222-2222-4222-8222-222222222222"
DROP_DOCS = "44444444-4444-4444-8444-444444444444"
VAULT = "55555555-5555-4555-8555-555555555555"
INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
OWNER = "sub-1"

#: `{variant: (kind, line paise, fee, GST on fee, payable)}` -- the figures plan.md measured with
#: the real `compute_quote`, re-asserted against it below rather than trusted.
NEW_SERVICES = {
    DROP_DOCS: ("DROP_DOCS", 35000, 875, 158, 36033),
    VAULT: ("VAULT", 4900, 123, 22, 5045),
}


def service(variant=DROP_DOCS, quantity=1):
    return {"catalogReference": {"catalogItemId": PRODUCT,
                                 "options": {"variantId": variant}}, "quantity": quantity}


def services_env(monkeypatch, *, rupees):
    """`make_env`, with ProductsTable taught the services product at one unit price.

    PHYSICAL, three variants. The handler's `_native_product_reader` is re-bound to this
    catalogue after `make_env` has bound its default one.
    """
    h, fake, _default = make_env(monkeypatch)
    catalog = NativeCatalog()
    monkeypatch.setitem(contribution_catalog.UNIT_RUPEES, PRODUCT, rupees)
    catalog.variants[PRODUCT] = [SUBMIT, DROP_DOCS, VAULT]
    catalog.product_type[PRODUCT] = "PHYSICAL"
    monkeypatch.setattr(h, "_native_product_reader", catalog.reader)
    return h, fake


def payrefs(fake):
    return [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]


def prepare(h, basket, **over):
    over.setdefault("serviceIntentId", INTENT)
    return h.handler(prepare_event(basket, **over), None)


# ── (a) and (b): the payable, to the paise ───────────────────────────────────

@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_payable_is_ordinary_order_pricing_to_the_paise(monkeypatch, variant):
    kind, line_paise, fee, gst, payable = NEW_SERVICES[variant]
    quote = cp.compute_quote(line_paise)
    assert quote.collection_before_convenience_paise == line_paise
    assert quote.convenience_fee_paise == fee
    assert quote.convenience_gst_paise == gst
    assert quote.total_payable_paise == payable == line_paise + fee + gst
    assert all(type(value) is int for value in (
        quote.collection_before_convenience_paise, quote.convenience_fee_paise,
        quote.convenience_gst_paise, quote.total_payable_paise))

    h, fake = services_env(monkeypatch, rupees=line_paise // 100)
    response = prepare(h, [service(variant)])
    assert response["statusCode"] == 200, body_of(response)
    assert body_of(response)["status"] == "CHECKOUT_OPTIONS_READY"
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == payable
    # The gateway is asked for the payable, once, and nothing else.
    assert [order["amount"] for order in h.gateway_orders] == [payable]
    [row] = payrefs(fake)
    assert row["serviceLine"] == {"kind": kind, "variantId": variant, "paise": line_paise,
                                  "intentId": INTENT}
    assert type(row["serviceLine"]["paise"]) is int


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_a_service_is_not_fee_exempt(monkeypatch, variant):
    """A contribution is fee-exempt; a service is not. Pinned by refusing the exempt path."""
    _kind, line_paise, _fee, _gst, payable = NEW_SERVICES[variant]
    h, fake = services_env(monkeypatch, rupees=line_paise // 100)

    def exempt_must_not_run(*_a, **_k):
        raise AssertionError("a service is NOT fee-exempt")

    monkeypatch.setattr(h.checkout_pricing, "exempt_quote", exempt_must_not_run)
    assert prepare(h, [service(variant)])["statusCode"] == 200
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == payable > line_paise


# ── (c) the per-line guard reads this variant from the frozen native quote ───

def frozen_quote(variant, unit_paise, *, quantity=1):
    """The `frozen_data['items']` shape `native_checkout.quote_native_cart` freezes."""
    return SimpleNamespace(frozen_data={"items": [{
        "productId": PRODUCT, "variantId": variant,
        "quantity": quantity, "unitPricePaise": unit_paise}]})


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_guard_returns_exactly_the_frozen_line_price(variant):
    _kind, line_paise, _f, _g, _p = NEW_SERVICES[variant]
    assert sr.native_service_line_paise(frozen_quote(variant, line_paise),
                                        [service(variant)]) == line_paise


@pytest.mark.parametrize("variant,priced", [(DROP_DOCS, 34999), (DROP_DOCS, 35001),
                                            (VAULT, 4899), (VAULT, 4901)])
def test_a_one_paise_catalogue_edit_in_either_direction_is_charged(variant, priced):
    """ProductsTable owns the price, so an edited figure inside the rail is charged, not refused.

    The structural checks (quantity 1, the right variant, one matching line) are what still
    protect this basket; see the module docstring in `service_requests`.
    """
    assert sr.native_service_line_paise(frozen_quote(variant, priced),
                                        [service(variant)]) == priced


@pytest.mark.parametrize("variant,priced", [(DROP_DOCS, 5_000_001), (VAULT, 0)])
def test_a_figure_outside_the_catastrophe_rail_still_fails_closed(variant, priced):
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen_quote(variant, priced), [service(variant)])


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_a_frozen_quantity_other_than_one_fails_closed(variant):
    _kind, line_paise, _f, _g, _p = NEW_SERVICES[variant]
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen_quote(variant, line_paise, quantity=2),
                                     [service(variant)])


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_line_read_is_this_variants_own_line_and_not_a_siblings(variant):
    """Several services share ONE catalogue product, so the guard has to be variant-scoped.

    It cannot be demonstrated by pricing this variant at its sibling's figure -- ProductsTable
    owns the price, so any figure inside the rail is legitimate for any variant, and refusing one
    would be refusing a price edit. What is demonstrable, and is the property that matters, is
    that the guard reads THIS variant's line: a quote carrying only the sibling's variant id is
    refused outright rather than silently priced.
    """
    other = next(key for key in NEW_SERVICES if key != variant)
    sibling_paise = NEW_SERVICES[other][1]
    # Same figure, right variant: accepted, and returned.
    assert sr.native_service_line_paise(frozen_quote(variant, sibling_paise),
                                        [service(variant)]) == sibling_paise
    # The quote holds the SIBLING's line for a basket that asked for this variant.
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen_quote(other, sibling_paise), [service(variant)])


# ── (d) currency is compared explicitly ──────────────────────────────────────

def _seed_target(requests, *, owner=OWNER, public="WD-REQ-TARGET22"):
    """A paid, activated SUBMIT_REQUEST to hang the new services off."""
    internal = "REQ#01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e01"
    requests.seed({"requestId": internal, "kind": "SUBMIT_REQUEST", "publicRequestId": public,
                   "customerId": owner, "status": "SUBMITTED", "statusRank": 10,
                   "serviceVariantId": SUBMIT, "amountPaise": 9900, "currency": "INR",
                   "createdAt": 1, "updatedAt": 1})
    requests.seed({"requestId": "REQNO#" + public, "ownerCustomerId": owner,
                   "targetRequestId": internal, "reservedAt": 1})
    return public


def _identity(owner=OWNER):
    return customer_auth.CustomerIdentity(customer_id=owner, phone="+910000000000",
                                          subject=owner)


def _keys_table():
    return FakeDynamo(keys={KEYS_TABLE: "orderId"}).Table(KEYS_TABLE)


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
@pytest.mark.parametrize("currency", ["inr", "USD", "", "Inr"])
def test_a_currency_other_than_the_exact_string_inr_is_unmatched(variant, currency):
    kind, line_paise, _f, _g, payable = NEW_SERVICES[variant]
    requests, keys = RequestTable(), _keys_table()
    target = _seed_target(requests)
    intent = store.request_intent(requests, _identity(), kind, target)
    # The one field under test, overwritten after the store wrote 'INR'.
    requests.rows["INTENT#" + intent["intentId"]]["currency"] = currency
    reference = order_keys.allocate_payment_reference(
        keys, payment_attempt_id="att-1",
        extra={"customerId": OWNER, "amountPaise": payable, "currency": "INR",
               "serviceLine": {"kind": kind, "variantId": variant, "paise": line_paise,
                               "intentId": intent["intentId"]}})
    keys.put_item(Item={"orderId": "PAYMENTATTEMPT#att-1", "orderIdRef": "order-1",
                        "orderNumber": "WD-ORD-ABCDEFGH", "referenceId": reference,
                        "paymentAttemptId": "att-1"})
    outcome = store.activate(requests, keys, reference_id=reference)
    assert outcome.outcome == store.UNMATCHED
    assert [key for key in requests.rows if str(key).startswith("REQ#")] == \
        ["REQ#01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e01"]      # only the seeded target
    assert not [key for key in requests.rows if str(key).startswith("ORDER#")]


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_store_records_the_exact_string_inr(variant):
    kind, _line_paise, _f, _g, _p = NEW_SERVICES[variant]
    requests = RequestTable()
    target = _seed_target(requests)
    intent = store.request_intent(requests, _identity(), kind, target)
    assert intent["currency"] == "INR" == sr.SERVICE_CURRENCY
    # NO `amountPaise` ON THE STORED INTENT, since 2026-10-08. An intent is pre-payment and the
    # native quote prices the line at checkout, so a figure here would be a stored guess -- and a
    # stored guess on a money row is what later gets compared against reality and refuses an
    # honest payment.
    # The currency IS recorded, because it is not a guess: INR is the only currency offered.
    row = requests.rows["INTENT#" + intent["intentId"]]
    assert "amountPaise" not in row
    assert row["currency"] == "INR"
    assert intent["amountPaise"] is None


# ── (e) replay safety: four deliveries, one of everything ────────────────────

def _webhook_module():
    webhook_dir = str(ROOT / "amplify/functions/payments/razorpay-webhook")
    for stale in [m for m in sys.modules if m == "handler" or m.startswith("handler.")]:
        del sys.modules[stale]
    sys.path.insert(0, webhook_dir)
    try:
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch("boto3.resource"), patch("boto3.client"):
                return importlib.import_module("handler")
    finally:
        sys.path.remove(webhook_dir)


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_a_capture_delivered_four_times_makes_one_claim_one_order_one_request(monkeypatch,
                                                                             variant):
    kind, line_paise, _f, _g, payable = NEW_SERVICES[variant]
    keys = _keys_table()
    requests = RequestTable()
    target = _seed_target(requests)
    intent = store.request_intent(requests, _identity(), kind, target)
    reference = order_keys.allocate_payment_reference(
        keys, payment_attempt_id="att-1",
        extra={"customerId": OWNER, "amountPaise": payable, "currency": "INR",
               # The binding a real prepare records, which the REAL verifier requires.
               "providerOrderId": "order_ABC",
               "serviceLine": {"kind": kind, "variantId": variant, "paise": line_paise,
                               "intentId": intent["intentId"]}})

    spec = importlib.util.spec_from_file_location(
        f"service_requests_receiver_{kind.lower()}",
        ROOT / "amplify/functions/ecommerce/service-requests/handler.py")
    receiver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receiver)
    tables = {receiver.SERVICE_REQUESTS_TABLE: requests, receiver.COMMERCE_KEYS_TABLE: keys}
    monkeypatch.setattr(receiver, "_table", lambda name: tables[name])

    webhook = _webhook_module()
    razorpay = RecordingRazorpay(payable)
    lam = LambdaToReceiver(receiver)
    payload = {"id": "pay_LIVE0000000001", "order_id": "order_ABC", "amount": payable,
               "currency": "INR"}
    outcomes = []
    load = lambda ref: order_keys.resolve_payment_reference(keys, ref)  # noqa: E731
    with patch.object(razorpay_verify, "_credentials",
                      return_value={"key_id": "test", "key_secret": "test"}), \
            patch("urllib.request.urlopen", razorpay):
        with patch.object(webhook, "dynamodb") as ddb, \
                patch.object(webhook, "lambda_client", lam):
            ddb.Table.return_value = keys
            for delivery in range(3):
                outcomes.append(webhook._create_order_for_captured_payment(
                    payload, reference, f"req-{delivery}"))
        verify = order_creation.reconcile_payment(
            table=keys, reference_id=reference,
            verify_payment=razorpay_verify.verifier_for_event(
                payment_id="pay_LIVE0000000001", load_attempt=load),
            load_attempt=load)
        store.activate(requests, keys, reference_id=reference, caller_customer_id=OWNER)

    assert [o["outcome"] for o in outcomes] == ["ORDER_CREATED", "ORDER_ALREADY_EXISTS",
                                                "ORDER_ALREADY_EXISTS"]
    assert verify.outcome == "ORDER_ALREADY_EXISTS"
    assert len([k for k in keys.rows if str(k).startswith("PAYMENTATTEMPT#")]) == 1
    # One REQ# beyond the seeded target, one ORDER# pointer, and it names the new kind.
    created = [row for key, row in requests.rows.items()
               if str(key).startswith("REQ#") and row.get("kind") == kind]
    assert len(created) == 1
    assert len([k for k in requests.rows if str(k).startswith("ORDER#")]) == 1
    [request] = created
    assert request["amountPaise"] == line_paise and type(request["amountPaise"]) is int
    assert request["currency"] == "INR"
    assert request["targetPublicRequestId"] == target
    # SIX hints across three deliveries: `dispatch_activation` fires TWO per reconciled order -
    # `activateServiceRequest` and, since the paid Submit Request form landed,
    # `preparePaidSubmitRequest`. Enumerated by target rather than as a bare total, so a third
    # hint on a money-path dispatcher fails here until somebody names it. Three deliveries still
    # produce ONE claim, ONE order and ONE request above: the hints are idempotent because the
    # receiver re-reads every id, not because the webhook sends fewer of them.
    assert lam.targets() == ["wecare-service-requests:live",
                             "wecare-whatsapp-business-api:live"] * 3, lam.targets()
    # Every provider request the path made, at the HTTP seam: reads of the one payment only.
    assert set(razorpay.calls) == {("GET", "/payments/pay_LIVE0000000001")}, razorpay.calls


def test_the_test_arithmetic_uses_no_float():
    """Structural: this file holds no float literal and calls no `float()`."""
    import ast
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
