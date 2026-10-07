"""Drop Docs (Rs.350) and Vault (Rs.49) end to end, in integer paise, on the ONE checkout.

The two new fixed-price lines reuse the Phase O-1 money path verbatim: `POST
/ecommerce/prepare-checkout` -> `cart_v2.calculate` -> ONE Razorpay order -> verify-callback /
razorpay-webhook reconciliation -> ONE activation. Nothing here adds a payment implementation, so
what has to be pinned is that the SAME guards hold at the two new amounts.

What is pinned, and why each is a property rather than a shape:

* **(a)(b) The payable is ordinary order pricing, to the paise.** 35000 -> fee 875 + GST 158 =
  36033; 4900 -> 123 + 22 = 5045. Asserted against the real `compute_quote`, as `int`s, and
  against what the gateway was actually asked for.
* **(c) A one-paise disagreement fails closed in BOTH directions**, and a services-only basket
  that acquires delivery, tax or an additional fee is refused. A Wix price edit must refuse the
  purchase, not charge a figure the page did not promise.
* **(d) Currency is compared explicitly.** `'inr'` and `'USD'` are both CURRENCY_MISMATCH at
  activation -- never inferred from the amount, never case-folded into agreement.
* **(e) Replay safety.** One captured payment delivered three times by the webhook plus once by
  verify-callback yields exactly one `PAYMENTATTEMPT#` claim, one `ORDER#` pointer and one `REQ#`
  for each new kind.

NO FLOAT ANYWHERE, including in the test arithmetic: every figure below is an integer paise
literal or an integer expression. Offline: FakeDynamo, the Cart V2 fake, a recording Razorpay
stub at the HTTP seam. No AWS, no network, no credential.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import contribution_wix  # noqa: E402
from contribution_env import ATTEMPTS_TABLE, KEYS_TABLE, body_of, make_env, prepare_event  # noqa
from contribution_wix import STORES_APP_ID, ContributionWix  # noqa: E402
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from service_requests_fake_dynamo import RequestTable  # noqa: E402
from test_one_service_money_path import LambdaToReceiver, RecordingRazorpay  # noqa: E402

from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import order_creation, order_keys  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402
from lambda_utils.integrations import razorpay_verify  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
DROP_DOCS = "db166bc8-a763-41ec-9f65-0f718f18155a"
VAULT = "dcff995e-448c-493a-9259-f6a82ccdc2b4"
INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
OWNER = "sub-1"

#: `{variant: (kind, line paise, fee, GST on fee, payable)}` -- the figures plan.md measured with
#: the real `compute_quote`, re-asserted against it below rather than trusted.
NEW_SERVICES = {
    DROP_DOCS: ("DROP_DOCS", 35000, 875, 158, 36033),
    VAULT: ("VAULT", 4900, 123, 22, 5045),
}


def service(variant=DROP_DOCS, quantity=1):
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": PRODUCT,
                                 "options": {"variantId": variant}}, "quantity": quantity}


def services_wix(monkeypatch, *, rupees, **kwargs):
    """The Cart V2 fake taught the services product at one unit price, PHYSICAL, four variants."""
    wix = ContributionWix(**kwargs)
    monkeypatch.setitem(contribution_wix.UNIT_RUPEES, PRODUCT, rupees)
    wix.variants[PRODUCT] = [SUBMIT, DROP_DOCS, VAULT]
    wix.product_type[PRODUCT] = "PHYSICAL"
    return wix


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

    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch,
                                                           rupees=line_paise // 100))
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
    h, fake, _wix = make_env(monkeypatch, wix=services_wix(monkeypatch,
                                                           rupees=line_paise // 100))

    def exempt_must_not_run(*_a, **_k):
        raise AssertionError("a service is NOT fee-exempt")

    monkeypatch.setattr(h.checkout_pricing, "exempt_quote", exempt_must_not_run)
    assert prepare(h, [service(variant)])["statusCode"] == 200
    [attempt] = fake.all_rows(ATTEMPTS_TABLE)
    assert int(attempt["amountPaise"]) == payable > line_paise


# ── (c) the per-line assertion fails closed in both directions ───────────────

def _rupees(paise: int) -> dict:
    return {"amount": f"{paise // 100}.{paise % 100:02d}"}


def calculated(variant, line_paise, *, delivery=0, tax=0, fees=0):
    cart_lines = [{"id": "L1", "quantityInfo": {"confirmedQuantity": 1},
                   "source": {"catalogReference": {"catalogItemId": PRODUCT,
                                                   "options": {"variantId": variant}}}}]
    summary = [{"lineItemId": "L1", "totalPrice": _rupees(line_paise)}]
    return {"cart": {"lineItems": cart_lines}, "summary": {"lineItems": summary},
            "componentsPaise": {"subtotal": line_paise, "discount": 0, "delivery": delivery,
                                "additionalFees": fees, "tax": tax,
                                "total": line_paise + delivery + tax + fees}}


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_assertion_passes_at_exactly_the_committed_paise(variant):
    _kind, line_paise, _f, _g, _p = NEW_SERVICES[variant]
    sr.assert_service_line_price(calculated(variant, line_paise), [service(variant)],
                                 delivery_required=False)


@pytest.mark.parametrize("variant,priced", [(DROP_DOCS, 34999), (DROP_DOCS, 35001),
                                            (VAULT, 4899), (VAULT, 4901)])
def test_a_one_paise_disagreement_in_either_direction_fails_closed(variant, priced):
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(variant, priced), [service(variant)],
                                     delivery_required=False)


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
@pytest.mark.parametrize("component", ["delivery", "tax", "fees"])
def test_any_non_zero_component_on_a_services_only_basket_fails_closed(variant, component):
    _kind, line_paise, _f, _g, _p = NEW_SERVICES[variant]
    calc = calculated(variant, line_paise, **{component: 1})
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calc, [service(variant)], delivery_required=False)


@pytest.mark.parametrize("variant", list(NEW_SERVICES))
def test_the_other_variants_price_is_not_accepted_for_this_one(variant):
    """Four services share one product, so a line priced as its SIBLING must refuse."""
    other = next(key for key in NEW_SERVICES if key != variant)
    _kind, _paise, _f, _g, _p = NEW_SERVICES[variant]
    sibling_paise = NEW_SERVICES[other][1]
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(variant, sibling_paise), [service(variant)],
                                     delivery_required=False)


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
    return FakeDynamo(keys={"stack-wecare-digital-WixOrderIds": "orderId"}).Table(
        "stack-wecare-digital-WixOrderIds")


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
    kind, line_paise, _f, _g, _p = NEW_SERVICES[variant]
    requests = RequestTable()
    target = _seed_target(requests)
    intent = store.request_intent(requests, _identity(), kind, target)
    assert intent["currency"] == "INR" == sr.SERVICE_CURRENCY
    assert requests.rows["INTENT#" + intent["intentId"]]["amountPaise"] == line_paise


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
    assert len(lam.calls) == 3
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
