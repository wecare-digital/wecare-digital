"""`ecommerce/checkout` prices through Cart V2, and the amount it charges is the calculator's.

What this covers that `tests/test_checkout_handler.py` does not
--------------------------------------------------------------
That file exercises the Checkout V1 price authority, which became the opt-out path on 2026-10-01
and is pinned off there. This file is the default path: Cart V2.

The behavioural difference is not the version, it is the amount. The V1 branch charged
`priceSummary.total` straight from Wix. The V2 branch runs Wix's collection total through
`checkout_pricing.compute_quote`, which adds our convenience fee and the GST on that fee, and
charges `total_payable_paise`. That is the contract section 8 of the handler's own docstring states
for the website path — "amountPaise is the FEAT-001 calculator total (collection+fee+GST), never
the raw Wix total" — and before the Cart V2 producer existed, no code path honoured it.

Two refusals are asserted as hard as the success is, because both are the point:

* **No address, no price.** Cart V2 answers an address-less cart with `ERROR`-severity
  `MISSING_DELIVERY_ADDRESS` / `MISSING_DELIVERY_METHOD`, and the handler returns
  `DELIVERY_DETAILS_REQUIRED` rather than substituting a default. Delivery is a component of the
  total and the delivery address is the place of supply, so a fabricated address yields a real
  number with the wrong CGST/SGST-versus-IGST split against seller GSTIN 19AAFFW7196L1Z8 — and
  that number would be charged.
* **No order, ever, here.** This handler reserves an intent. An order exists only after an
  authoritative capture, so no call it makes may create or place one.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402

from lambda_utils.ecommerce import contact_address  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"

OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}

#: The QA recipient, as a session may spell it and as the WRITER stores it. The contact row is
#: seeded under the second one, never the first: `auth/customer-profile` normalises before it
#: writes, so a test that seeded the session's spelling would assume the read key instead of
#: testing it.
SESSION_PHONE = "+918100640044"
STORED_PHONE = customer_identity.normalize_phone_preserving_country(SESSION_PHONE)
#: The same number, differently spaced, for the §3.0 pin on the PRICING path.
RAW_SESSION_PHONE = "+91 81006 40044"

#: What the stored address becomes on the Wix cart. Written out rather than derived, so a change
#: to the mapping has to be acknowledged here.
EXPECTED_WIX_ADDRESS = {"country": "IN", "subdivision": "IN-WB", "city": "Kolkata",
                        "postalCode": "700001", "addressLine": "12 Dalhousie Square"}

#: Expected figures, re-derived here rather than copied from the implementation:
#: Wix collection 25499.00 = items 24999.00 + delivery 500.00.
COLLECTION_PAISE = 2549900
#: 2.5% convenience fee, then 18% GST on the fee, both half-up on integer paise.
FEE_PAISE = 63748
FEE_GST_PAISE = 11475
TOTAL_PAYABLE_PAISE = COLLECTION_PAISE + FEE_PAISE + FEE_GST_PAISE


def delivery_complete():
    return json.loads((FIXTURES / "wix_cart_v2_delivery_complete.json").read_text())


def live():
    return json.loads((FIXTURES / "wix_cart_v2_live_demo.json").read_text())


class _Identity:
    def __init__(self, customer_id=CUSTOMER, phone=SESSION_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "subject-1"

    def owns(self, cid):
        return bool(cid) and cid == self.customer_id


class _FakeLambda:
    """Stands in for the WhatsApp sender and the payment-config readback."""

    def __init__(self):
        self.send_ok = True

    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        event = json.loads(Payload.decode("utf-8"))
        if "payment-config" in str(event.get("path") or ""):
            # A ready-looking raw payment_configurations readback for the WABA. Readiness is a
            # live provider readback in production; this makes it pass so the PRICE is what the
            # test is measuring. `tests/test_checkout_handler.py` covers the blocked states.
            inner = {"statusCode": 200, "body": json.dumps({"data": [{
                "configuration_name": "WECAREDIGITAL", "status": "active",
                "payment_gateway": {"type": "razorpay", "merchant_id": "acc_TESTMID"}}]})}
        else:
            inner = {"statusCode": 200 if self.send_ok else 502, "body": "{}"}
        return {"Payload": _Payload(json.dumps(inner).encode("utf-8"))}


class _Payload:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw


class RecordingWix:
    """Replays a Cart V2 response and records every call, so a test can enumerate them."""

    def __init__(self, response=None):
        self.response = delivery_complete() if response is None else response
        self.calls = []
        #: `(method, endpoint, body)`, so a test can assert on what was SENT and not only on
        #: which endpoints were touched.
        self.requests = []

    def __call__(self, endpoint, method="GET", body=None):
        self.calls.append((method.upper(), endpoint))
        self.requests.append((method.upper(), endpoint, copy.deepcopy(body)))
        if endpoint.startswith("/stores/v3/products/"):
            # `normalized_catalog_items` resolves the live variant before pricing.
            reference = self.response["cart"]["lineItems"][0]["source"]["catalogReference"]
            return {"product": {
                "id": reference["catalogItemId"], "visible": True,
                "variantsInfo": {"variants": [{
                    "id": reference["options"]["variantId"], "visible": True,
                    "inventoryStatus": {"inStock": True}}]}}}
        return copy.deepcopy(self.response)

    def paths(self):
        return [path for _method, path in self.calls]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS_TABLE)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setenv("EXPECTED_CONFIGURATION_NAME", "WECAREDIGITAL")
    monkeypatch.setenv("EXPECTED_PROVIDER_MID", "acc_TESTMID")
    monkeypatch.setenv("PAYMENT_WABA_ID", "2094615664435155")
    monkeypatch.setenv("APP_ENV", "development")
    # Cart V2 is OPT-IN, so this file has to turn it on explicitly. That is the point rather than
    # test scaffolding: no deployed function carries the key, so V2 does not serve anywhere until
    # an operator sets it, and a test that passed with no key set would be measuring the wrong
    # default. `test_with_no_gate_key_set_the_handler_stays_on_checkout_v1` holds the other side.
    monkeypatch.setenv("WIX_CART_V2_ENABLED", "true")
    monkeypatch.delenv("WIX_CART_V2_DISABLED", raising=False)

    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)

    spec = importlib.util.spec_from_file_location("checkout_cart_v2_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    # `FakeDynamo.Table` raises for an undeclared table and `FakeTable.query` for an undeclared
    # index, so the contacts table and its `phone-index` have to be declared before the real
    # `_load_owned_address` -- which goes through `_checkout_profile` -- can run at all.
    fake = FakeDynamo(keys={ATTEMPTS_TABLE: "paymentAttemptId", KEYS_TABLE: "orderId",
                            CONTACTS_TABLE: "id"},
                      indexes={CONTACTS_TABLE: {"phone-index": ("phone", None)}})
    lam = _FakeLambda()
    wix = RecordingWix()

    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_lambda_client", lambda: lam)
    monkeypatch.setattr(h, "INITIATION_ENABLED", False)
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)
    monkeypatch.setattr(h.customer_auth, "authenticate", lambda event: _Identity())
    seed_contact(fake)
    # The owned-address loader seam, stubbed for the money tests so they measure the PRICE and
    # not the profile read. The tests that are about the read restore the real loader with
    # `monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)`. It is NEVER taken
    # from the request body.
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", lambda customer_id: dict(OWNED))
    return h, fake, lam, wix, monkeypatch


def seed_contact(fake, *, phone=STORED_PHONE, address=OWNED, customer=CUSTOMER):
    """A CRM contact row exactly as `auth/customer-profile` writes one.

    Carries `checkoutCustomerId`, `email` and `emailVerifiedAt` because `_checkout_profile` is
    the ready-to-pay predicate and refuses a row missing any of them, plus
    `checkoutDeliveryAddress`, which is what `_load_owned_address` reads.
    """
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-v2-1",
        "contactId": "contact-v2-1",
        "phone": phone,
        "email": "asha@example.com",
        "name": "Asha Sen",
        "firstName": "Asha",
        "lastName": "Sen",
        "checkoutCustomerId": customer,
        "emailVerifiedAt": 1,
        "deletedAt": None,
        contact_address.ATTRIBUTE: dict(address),
        contact_address.UPDATED_ATTRIBUTE: 1,
    })


def contacts_queries(fake):
    return [call for call in fake.calls if call == (CONTACTS_TABLE, "query:phone-index")]


def _delivery_address_bodies(wix):
    """Every `deliveryInfo.address` payload this run sent to Wix."""
    return [(body["cart"]["deliveryInfo"]["address"])
            for method, endpoint, body in wix.requests
            if method == "PATCH" and isinstance(body, dict)
            and "deliveryInfo" in (body.get("cart") or {})]


def _create_event(**over):
    reference = delivery_complete()["cart"]["lineItems"][0]["source"]["catalogReference"]
    body = {"lineItems": [{
        "catalogReference": {"appId": reference["appId"],
                             "catalogItemId": reference["catalogItemId"],
                             "options": {"variantId": reference["options"]["variantId"]}},
        "quantity": 1}]}
    body.update(over)
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.5"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer tok"},
        "body": json.dumps({"action": "create", **body}),
    }


# ── with the opt-in set, the path is Cart V2 ─────────────────────────────────────

def test_with_the_gate_opted_in_the_handler_prices_through_cart_v2(env):
    h, _fake, _lam, wix, _mp = env
    response = h.handler(_create_event(), None)
    assert response["statusCode"] == 200
    assert all("/ecom/v1/checkouts" not in path for path in wix.paths()), \
        "the V2 path must not touch Checkout V1"
    assert any(path.startswith("/ecom/v2/carts") for path in wix.paths())


def test_the_charged_amount_is_the_calculator_total_not_the_raw_wix_total(env):
    """The behavioural change the migration exists to make.

    V1 charged Wix's `priceSummary.total`. V2 charges collection + convenience fee + GST on the
    fee, which is what `website_checkout` and `customer_receipt` have always expected and what
    nothing produced.
    """
    h, fake, _lam, _wix, _mp = env
    body = json.loads(h.handler(_create_event(), None)["body"])

    assert body["amountPaise"] == TOTAL_PAYABLE_PAISE
    assert body["amountPaise"] != COLLECTION_PAISE
    assert body["currency"] == "INR"
    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    assert attempts[0]["amountPaise"] == TOTAL_PAYABLE_PAISE


def test_the_reserved_reference_records_both_the_collection_and_the_payable_amount(env):
    """So the fee and its GST stay auditable instead of being inferred from a difference."""
    h, fake, _lam, _wix, _mp = env
    h.handler(_create_event(), None)

    rows = [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]
    assert len(rows) == 1
    reserved = rows[0]
    assert int(reserved["amountPaise"]) == TOTAL_PAYABLE_PAISE
    assert int(reserved["collectionPaise"]) == COLLECTION_PAISE
    assert reserved["wixCartId"] == delivery_complete()["cart"]["id"]
    assert int(reserved["cartRevision"]) == 4
    assert reserved["quoteHash"]


def test_the_v2_path_stores_no_wix_checkout_id(env):
    """In Cart V2 the cart id IS the checkout id, so a separate field identifies nothing.

    Still written as an empty string rather than removed: the field exists on a deployed Amplify
    data model and on stored rows, and dropping it is a separate, non-inert change.
    """
    h, fake, _lam, _wix, _mp = env
    h.handler(_create_event(), None)
    rows = [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]
    assert rows[0]["wixCheckoutId"] == ""


def test_money_in_the_response_is_an_integer_number_of_paise(env):
    h, _fake, _lam, _wix, _mp = env
    body = json.loads(h.handler(_create_event(), None)["body"])
    assert type(body["amountPaise"]) is int
    assert "." not in json.dumps(body["amountPaise"])


# ── no address means no price, and no invented address ───────────────────────────

def test_without_an_owned_address_the_handler_refuses_before_touching_wix(env):
    """The loader seam returns nothing, which in production now means the customer has saved no
    usable address -- the seam itself reads the CRM contact row and is no longer `None`.

    The response is a recoverable 409 naming what the customer must do, not a 500 and not a total
    computed from a placeholder. The stronger assertion is the second one: **no Wix call that can
    LEAVE ANYTHING BEHIND is made**. An earlier revision created the cart first and read the
    address afterwards, so every attempt left a real, never-completed cart on the live site with
    nothing to clean it up. A request that cannot be priced has to be refused before it can leave
    anything behind.

    Asserted as "no Wix WRITE", not "no Wix call at all", because Phase 2 moved the address
    REQUIREMENT (not the address load) below `_v2_catalog_items`: the basket's delivery need is
    now read from Wix's own `productType`, so the refusal has to know what is in the basket before
    it can know whether an address was required. `_v2_catalog_items` performs
    `GET /stores/v3/products/{id}` only -- it creates nothing, and it already ran before
    `CustomerCart.ensure` on every request -- so the leave-nothing-behind property is preserved
    exactly while the proxy for it ("zero calls") is not. The property is what this asserts.
    """
    h, fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", None)
    response = h.handler(_create_event(), None)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert all(method == "GET" for method, *_ in wix.calls), (
        "no Wix call that writes may precede the address check")
    # Nothing was reserved and no attempt exists: a refused price creates no intent.
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_an_empty_profile_address_is_not_coerced_into_a_default(env):
    h, fake, _lam, wix, monkeypatch = env
    for empty in ({}, None, ""):
        monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", lambda cid, value=empty: value)
        response = h.handler(_create_event(), None)
        assert response["statusCode"] == 409
        assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    # Read-only product reads are permitted; a write is not. See the test above for why the
    # assertion is the property rather than a zero-call count.
    assert all(method == "GET" for method, *_ in wix.calls)
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_a_cart_wix_still_refuses_to_price_yields_no_attempt(env):
    """The unmodified live response: real `ERROR` violations, so no quote.

    Asserted end to end through the handler, not just at the adapter, because the failure that
    matters is a customer being charged — and that can only happen here.
    """
    h, fake, _lam, _wix, monkeypatch = env
    monkeypatch.setattr(h, "_wix_request", RecordingWix(live()))
    monkeypatch.setattr(h.wix_ecom, "_request", RecordingWix(live()))
    response = h.handler(_create_event(), None)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_the_browser_cannot_supply_an_address_or_an_amount(env):
    """Authority comes from the session and the catalogue, never the request body.

    An address a browser can set is an address an attacker can set, and here that would move the
    place of supply and so the tax.
    """
    h, fake, _lam, _wix, _mp = env
    hostile = _create_event(deliveryAddress={"state": "Maharashtra", "city": "Mumbai"},
                            amountPaise=1, amount=1, collectionPaise=1)
    body = json.loads(h.handler(hostile, None)["body"])

    assert body["amountPaise"] == TOTAL_PAYABLE_PAISE
    rows = [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]
    # The frozen address is the owned West Bengal one, so the fee GST stayed intra-state.
    assert rows[0]["quoteHash"]
    assert int(rows[0]["collectionPaise"]) == COLLECTION_PAISE


# ── the gate: absence keeps V1, and the kill switch beats a deployed opt-in ──────

def _stub_v1(h, monkeypatch):
    monkeypatch.setattr(h.wix_ecom, "create_checkout", lambda items, **k: {
        "id": "wix-checkout-1", "currency": "INR",
        "priceSummary": {"total": {"amount": "599.00"}},
        "lineItems": [{"productName": {"original": "Viveka"}, "quantity": 1}]})


def test_with_no_gate_key_set_the_handler_stays_on_checkout_v1(env):
    """Absence is off. This is the configuration of every deployed function.

    V2 must not become the live price authority because a deploy happened; it becomes the price
    authority because an operator set `WIX_CART_V2_ENABLED`. So with the key removed the handler
    answers from the retained V1 authority and makes no Cart V2 call at all.
    """
    h, _fake, _lam, wix, monkeypatch = env
    monkeypatch.delenv("WIX_CART_V2_ENABLED", raising=False)
    _stub_v1(h, monkeypatch)

    body = json.loads(h.handler(_create_event(), None)["body"])
    # The raw Wix total, as the retained V1 contract specifies.
    assert body["amountPaise"] == 59900
    assert not any(path.startswith("/ecom/v2/carts") for path in wix.paths())


def test_the_disable_key_overrides_a_deployed_opt_in(env):
    """The rollback lever: one environment variable, without having to find and unset the opt-in."""
    h, _fake, _lam, wix, monkeypatch = env
    monkeypatch.setenv("WIX_CART_V2_DISABLED", "true")
    _stub_v1(h, monkeypatch)

    body = json.loads(h.handler(_create_event(), None)["body"])
    assert body["amountPaise"] == 59900
    assert not any(path.startswith("/ecom/v2/carts") for path in wix.paths())


# ── one purchase, one cart: resolve before generate ──────────────────────────────

def test_a_repeated_checkout_reuses_the_saved_cart_instead_of_minting_another(env):
    """The cart is persisted and identity-keyed, so a retry must land on the one that exists.

    `customer_cart` already owns cart identity and its lock protocol. An earlier revision called
    Create Cart unconditionally on every checkout attempt, which gave one purchase two cart
    lifecycles -- the persisted one the `/wix-store/cart` route maintains and a throwaway one per
    attempt -- and turned a single abandoned cart into unbounded accumulation on the live site.
    """
    h, _fake, _lam, wix, _mp = env
    assert h.handler(_create_event(), None)["statusCode"] == 200
    creates = [path for method, path in wix.calls
               if method == "POST" and path == "/ecom/v2/carts"]
    assert len(creates) == 1

    assert h.handler(_create_event(), None)["statusCode"] == 200
    creates = [path for method, path in wix.calls
               if method == "POST" and path == "/ecom/v2/carts"]
    assert len(creates) == 1, "the second attempt created a second cart"


def test_a_saved_cart_holding_something_else_is_refused_rather_than_priced(env):
    """Reuse is correct; silently pricing a different basket is not.

    The saved cart belongs to the `/wix-store/cart` route, so it can legitimately diverge from what
    this request asked to price -- a second tab, another device, an edit after the page loaded.
    Charging for a basket the customer is not looking at is the failure worth refusing.
    """
    h, fake, _lam, _wix, _mp = env
    assert h.handler(_create_event(), None)["statusCode"] == 200
    before = len([r for r in fake.all_rows(KEYS_TABLE) if str(r["orderId"]).startswith("PAYREF#")])

    other = copy.deepcopy(_create_event())
    body = json.loads(other["body"])
    body["lineItems"][0]["quantity"] = 2
    other["body"] = json.dumps(body)
    response = h.handler(other, None)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "CART_NOT_PAYABLE"
    after = [r for r in fake.all_rows(KEYS_TABLE) if str(r["orderId"]).startswith("PAYREF#")]
    assert len(after) == before, "a mismatched basket must reserve nothing"


def test_the_create_route_does_not_reconcile_and_that_is_the_default(env):
    """`reconcile=False` is `_v2_snapshot`'s default, and only `_website_snapshot` overrides it.

    The test above is the behavioural proof; this is the structural one, because the default is
    what keeps the WhatsApp payment path unchanged. Reconciling unconditionally would silently
    alter a live payment path that has no contribution entry point and gains nothing from it.
    """
    h, _fake, _lam, _wix, _mp = env
    import inspect
    signature = inspect.signature(h._v2_snapshot)
    assert signature.parameters["reconcile"].default is False
    assert signature.parameters["reset"].default is False
    assert signature.parameters["reconcile"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["reset"].kind is inspect.Parameter.KEYWORD_ONLY

    website = inspect.signature(h._website_snapshot)
    assert website.parameters["reset"].default is False
    assert website.parameters["reset"].kind is inspect.Parameter.KEYWORD_ONLY
    # Positional call still works, which `tests/test_graft_money_correctness.py` relies on.
    assert [name for name, p in website.parameters.items()
            if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD] == [
        "identity", "line_items", "now"]


def test_the_website_route_reconciles_the_same_mismatch_the_create_route_refuses(env):
    """The asymmetry, driven through the handler on the prepare route.

    The website request comes from the cart page the customer is looking at, so making the Wix
    cart match it is "asking them to review it" carried out rather than bypassed. The refusal that
    stands on `_create` has no equivalent surface there -- and before this, it answered
    `503 TEMPORARILY_UNAVAILABLE` on the website route, a transient code for a condition no retry
    clears, for up to thirty days.
    """
    h, _fake, _lam, wix, _mp = env
    assert h.handler(_create_event(), None)["statusCode"] == 200

    reference = delivery_complete()["cart"]["lineItems"][0]["source"]["catalogReference"]
    event = {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.5"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer tok"},
        "rawPath": "/ecommerce/prepare-checkout",
        "body": json.dumps({"lineItems": [{
            "catalogReference": {"appId": reference["appId"],
                                 "catalogItemId": reference["catalogItemId"],
                                 "options": {"variantId": reference["options"]["variantId"]}},
            "quantity": 2}], "requestKey": "rk-reconcile-1"}),
    }
    before = len([path for method, path in wix.calls
                  if method == "POST" and path.endswith("/update-line-items")])
    response = h.handler(event, None)
    # The canned fixture always replays quantity 1, so the backstop still refuses after the
    # reconcile -- which is the point worth asserting here: it is a 409 in the Cart V2 vocabulary
    # rather than the 503 dead end, AND a reconcile command was actually issued.
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "CART_NOT_PAYABLE"
    after = len([path for method, path in wix.calls
                 if method == "POST" and path.endswith("/update-line-items")])
    assert after > before, "the website route must attempt a reconcile before refusing"


def test_a_physical_create_basket_with_no_stored_address_still_demands_one(env):
    """Sec 3.7's property, not the absence of a diff.

    `_create` gained a CONDITIONAL address requirement because it shares `_v2_snapshot`. That is
    behaviourally inert today -- every one of the seven catalogue products is PHYSICAL, so
    `any(requiresDelivery)` is True for every basket that exists -- but it is still a change to a
    live payment path, so the property is pinned rather than left to be discovered.
    """
    h, fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", lambda customer_id: None)
    response = h.handler(_create_event(), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert all(method == "GET" for method, *_ in wix.calls)
    assert fake.all_rows(ATTEMPTS_TABLE) == []


# ── nothing here can create or place an order ───────────────────────────────────

def test_the_whole_create_path_makes_no_order_or_charging_call(env):
    """Enumerated, so "no second charge" is demonstrated rather than asserted."""
    h, _fake, _lam, wix, _mp = env
    h.handler(_create_event(), None)

    for path in wix.paths():
        lowered = path.lower()
        for forbidden in ("/ecom/v1/orders", "/ecom/v2/carts/place-order", "place-order",
                          "mark-as-completed", "add-payment", "/checkout", "capture",
                          "charge", "redirect-session"):
            assert forbidden not in lowered, f"create path reached {path}"


def test_no_customer_is_routed_to_a_wix_hosted_checkout(env):
    """This is a headless architecture: Wix prices, Razorpay collects on our own site.

    A Get Checkout URL or a redirect session would hand the customer to a Wix payment surface,
    which is explicitly not the design.
    """
    h, _fake, _lam, wix, _mp = env
    response = h.handler(_create_event(), None)
    serialized = json.dumps(response)

    for marker in ("wixapis.com/_api/redirects", "checkoutUrl", "redirectSession",
                   "wix.com/checkout"):
        assert marker not in serialized
    assert all("redirect" not in path.lower() for path in wix.paths())


def test_initiation_stays_disabled_so_no_payable_message_goes_out(env):
    h, _fake, lam, _wix, _mp = env
    body = json.loads(h.handler(_create_event(), None)["body"])
    assert body["status"] == "PAYMENT_INITIATION_DISABLED"


# ── the two V1 behaviours, surfaced distinguishably through the handler ──────────

def _fixture(name):
    return json.loads((FIXTURES / f"wix_cart_v2_{name}.json").read_text())


@pytest.mark.parametrize("name,error", [
    ("out_of_stock", "ITEMS_UNAVAILABLE"),
    ("removed_from_catalog", "ITEMS_UNAVAILABLE"),
    ("quantity_reduced", "QUANTITY_REDUCED"),
])
def test_stock_problems_get_their_own_actionable_response(env, name, error):
    """Three distinct customer situations, three distinct answers, and no attempt in any of them.

    Checkout V1 would have priced around the first two and silently accepted the third. Each needs
    something different from the customer, so collapsing them into one generic 409 would be a
    usability loss on top of a correctness one.
    """
    h, fake, _lam, _wix, monkeypatch = env
    wix = RecordingWix(_fixture(name))
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)

    response = h.handler(_create_event(), None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 409
    assert body["error"] == error
    assert body["items"], "the response must name what to fix"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_a_silently_reduced_quantity_does_not_become_a_charge(env):
    """The fixture's money reconciles perfectly; only requested-vs-confirmed reveals the problem."""
    h, fake, _lam, _wix, monkeypatch = env
    wix = RecordingWix(_fixture("quantity_reduced"))
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)

    body = json.loads(h.handler(_create_event(), None)["body"])
    assert body["items"][0]["requestedQuantity"] == 3
    assert body["items"][0]["confirmedQuantity"] == 1
    assert "amountPaise" not in body
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_a_coupon_discounted_cart_prices_and_reconciles_through_the_handler(env):
    """End to end with a coupon: the charged amount is the discounted collection plus fee and GST."""
    h, fake, _lam, _wix, monkeypatch = env
    wix = RecordingWix(_fixture("coupon_applied"))
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)

    body = json.loads(h.handler(_create_event(), None)["body"])
    rows = [row for row in fake.all_rows(KEYS_TABLE) if str(row["orderId"]).startswith("PAYREF#")]
    collection = int(rows[0]["collectionPaise"])

    assert collection == 2299900                      # 24999.00 - 2500.00 + 500.00
    assert collection < COLLECTION_PAISE              # the coupon really did reduce it
    assert body["amountPaise"] > collection           # fee and its GST were added on top
    assert body["amountPaise"] == int(rows[0]["amountPaise"])


# ── the server loads the address itself: LOAD_OWNED_ADDRESS is no longer None ────
#
# Every test below restores the REAL loader over the fixture's stub, because the behaviour under
# test is the profile read rather than the price. Until this phase the production default was
# `None`, so a V2 checkout answered `DELIVERY_DETAILS_REQUIRED` forever -- silently, with no log
# line, for a customer who had saved an address.


def _prepare_event(**over):
    event = _create_event(**over)
    body = json.loads(event["body"])
    body["action"] = "prepare"
    body.setdefault("requestKey", "request-cart-v2-prepare-1")
    event["body"] = json.dumps(body)
    return event


def test_prepare_sends_the_stored_address_to_wix_without_a_second_contacts_query(env):
    """The threaded-profile branch: `_website_prepare` already holds the row.

    Two assertions, and the second is the one that justifies the threading -- `_website_prepare`
    loads the contact row to build the Razorpay prefill, so re-reading it inside `_v2_snapshot`
    would double a DynamoDB Query on the happy path of every checkout.
    """
    h, fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)

    response = h.handler(_prepare_event(), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "PAYMENT_INITIATION_DISABLED"

    assert _delivery_address_bodies(wix) == [EXPECTED_WIX_ADDRESS]
    assert len(contacts_queries(fake)) == 1, \
        "the threaded profile must not be re-read inside _v2_snapshot"


def test_a_physical_checkout_selects_the_delivery_method_wix_offered(env):
    """THE BLOCKER. Setting the address was never enough, and this is the assertion that says so.

    Cart V2 needs `deliveryInfo.address` AND `deliveryInfo.method`. Every website checkout of a
    physical product set the address and stopped, so Calculate Cart answered
    `MISSING_DELIVERY_METHOD` and nothing could be priced -- the live logs for 2026-10-04
    15:00-15:01 UTC are one `website_checkout_delivery_blocked` per attempt.

    Two things are asserted, and the second is the one a shape change would break silently:
    the method is selected at all, and it is selected with the body the provider accepts.
    `{"deliveryMethodId": ...}` returns HTTP 400 `deliveryMethod / must not be empty`, which no
    fake would have caught on its own.
    """
    h, _fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)

    assert h.handler(_prepare_event(), None)["statusCode"] == 200

    selections = [body for method, endpoint, body in wix.requests
                  if endpoint.endswith("/set-delivery-method")]
    assert selections, "a physical cart must have a delivery method selected"
    offered = delivery_complete()["summary"]["deliverySummary"]["method"]["code"]
    assert selections == [{"deliveryMethod": {"code": offered}}]

    # And the selection happens AFTER the address, because Wix cannot resolve an option without
    # one. Order, not just presence.
    sequence = [endpoint.rsplit("/", 1)[-1] for method, endpoint in wix.calls
                if endpoint.endswith("/set-delivery-method")
                or (method == "PATCH" and "/carts/" in endpoint)]
    assert sequence[0] != "set-delivery-method"


def test_create_loads_the_stored_address_through_the_loader_itself(env):
    """`_create` threads no profile, so this exercises `_load_owned_address` end to end."""
    h, fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)

    response = h.handler(_create_event(), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["amountPaise"] == TOTAL_PAYABLE_PAISE
    assert _delivery_address_bodies(wix) == [EXPECTED_WIX_ADDRESS]
    assert len(contacts_queries(fake)) == 1


def test_a_raw_session_phone_still_resolves_the_address_on_the_pricing_path(env):
    """The §3.0 pin on the PRICING path, asserted where the path can actually be measured.

    The contact row is keyed on the phone, the writer stores
    `normalize_phone_preserving_country`'s output, and this session carries the same number
    differently spaced. A read key that is right for `action:"profile"` and wrong here would
    refuse a payable customer with `409 DELIVERY_DETAILS_REQUIRED` -- the failure this phase
    exists to remove, arriving one layer down. Both assertions below fail on the raw lookup:
    `_load_owned_address` returns `None`, and the prepare answers that 409.

    MEASURED, PRE-EXISTING, AND NOT THIS PHASE'S TO FIX: a differently-spaced session phone
    cannot reach pricing at all. `customer_cart._cart_key` (`customer_cart.py:46`) requires
    `identity.phone` to match `\\+[1-9][0-9]{7,14}` exactly, because the raw session value IS the
    `CUSTOMERCART#` partition key, so the request fails there with a `ValueError` and
    `_website_prepare`'s generic arm answers `503`. That check sits after the address
    resolution, which is why the address is still provably resolved. Re-keying the saved cart
    onto the normaliser would move every existing `CUSTOMERCART#` row -- a data-model change
    outside design §9's file list -- so it is recorded rather than attempted. In practice this
    is unreachable anyway: Cognito stores `phone_number` in E.164.
    """
    h, fake, _lam, _wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)
    monkeypatch.setattr(h.customer_auth, "authenticate",
                        lambda event: _Identity(phone=RAW_SESSION_PHONE))
    assert RAW_SESSION_PHONE != STORED_PHONE

    # The read key under test, directly: the seeded row is found despite the spelling.
    resolved = h._load_owned_address(_Identity(phone=RAW_SESSION_PHONE))
    assert resolved is not None
    assert resolved["city"] == "Kolkata"

    # And through the handler: the request gets PAST the address check.
    response = h.handler(_prepare_event(), None)
    assert json.loads(response["body"]).get("error") != "DELIVERY_DETAILS_REQUIRED"


def test_a_stored_address_wix_cannot_map_is_refused_before_any_wix_write(env):
    """`from_contact` re-validates, so an unmappable stored address is a recoverable 409.

    Not a 503, which no retry fixes, and not a priced cart with the wrong CGST/SGST-versus-IGST
    split. And nothing is left behind on the live site: no Wix WRITE. The read-only product GET
    that resolves whether this basket needs delivery at all is permitted and creates nothing --
    see `test_without_an_owned_address_the_handler_refuses_before_touching_wix` for why the
    assertion is the property rather than a zero-call count.
    """
    h, fake, _lam, wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)
    fake.tables[CONTACTS_TABLE].clear()
    seed_contact(fake, address={"addressLine1": "12 MG Road", "city": "Bengaluru",
                                "state": "Nowhere Pradesh", "postalCode": "560001"})

    response = h.handler(_prepare_event(), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert all(method == "GET" for method, *_ in wix.calls)
    assert fake.all_rows(ATTEMPTS_TABLE) == []


# ── a missing delivery METHOD is its own answer ──────────────────────────────────

class _ScriptedCalculateWix(RecordingWix):
    """Replays a different response for each successive Calculate Cart call.

    `calculate` and `preview` are the same Wix endpoint, so the only way to make one answer
    differ from the next is to script by call order. On the website path that order is now:
    1 = `preview` for the delivery OPTIONS read inside `prepare_delivery`, 2 = `calculate`
    (raises inside `purchase_intent`), 3 = `preview` from `_delivery_is_missing`, 4 = `preview`
    from `_blocking_codes`. An entry that is an exception instance is raised instead of returned,
    and the last entry repeats for any further call.
    """

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.calculate_calls = 0

    def __call__(self, endpoint, method="GET", body=None):
        if endpoint.endswith("/calculate"):
            self.calls.append((method.upper(), endpoint))
            self.requests.append((method.upper(), endpoint, copy.deepcopy(body)))
            index = min(self.calculate_calls, len(self.script) - 1)
            self.calculate_calls += 1
            reply = self.script[index]
            if isinstance(reply, Exception):
                raise reply
            return copy.deepcopy(reply)
        return super().__call__(endpoint, method=method, body=body)


def _method_only():
    """The live unpriceable response with the ADDRESS violation removed.

    `demo: true` is what makes `calculate` refuse; the remaining violation is what makes the
    refusal a delivery-method problem rather than an address one.
    """
    response = live()
    response["summary"]["violations"] = [
        violation for violation in response["summary"]["violations"]
        if violation["code"] != "MISSING_DELIVERY_ADDRESS"]
    return response


def _method_only_with_an_offered_option():
    """`_method_only`, plus the `summary.deliverySummary` the LIVE site really sends.

    Measured 2026-10-04: Wix populates `deliverySummary.method` for a cart whose
    `deliveryInfo.method` is still null and whose summary still carries
    `MISSING_DELIVERY_METHOD`. So "Wix offered an option" and "Wix refuses to price this cart"
    are the same response, and this is the shape in which `prepare_delivery` reads the option.

    Needed because `_method_only` alone now stops the run one step earlier -- no offered option
    means `prepare_delivery` refuses before `calculate` is ever reached, which is a DIFFERENT
    path from the one these tests were written to exercise.
    """
    response = _method_only()
    response["summary"]["deliverySummary"] = {
        "method": {"code": "11111111-2222-3333-4444-555555555555",
                   "appId": "45c44b27-ca7b-4891-8c0d-1747d588b835",
                   "title": {"original": "Standard delivery",
                             "translated": "Standard delivery"},
                   "pickup": False},
        "price": {"amount": "500.00", "convertedAmount": "500.00"},
    }
    return response


def test_a_method_only_refusal_is_distinguishable_from_a_missing_address(env):
    """Wix has the address and offers no way to deliver to it.

    Collapsing this into `DELIVERY_DETAILS_REQUIRED` tells a customer to enter an address they
    already saved, forever, and no retry helps -- it needs a shipping rule on the Wix site.

    This now also covers the ZERO-OPTIONS route in: `_method_only` carries no
    `summary.deliverySummary`, so `prepare_delivery` finds nothing to select, refuses, and the
    handler's arm reads Wix's own `MISSING_DELIVERY_METHOD` and answers the narrow code. Same
    answer, reached one step earlier than before, which is the point of raising there.
    """
    h, fake, _lam, _wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)
    wix = _ScriptedCalculateWix([_method_only()])
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)

    response = h.handler(_prepare_event(), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_METHOD_UNAVAILABLE"
    # The address really did reach Wix, which is what makes "method, not address" honest.
    assert _delivery_address_bodies(wix) == [EXPECTED_WIX_ADDRESS]
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_a_preview_that_fails_is_no_evidence_and_the_refusal_stays_generic(env):
    """Fail-closed on no evidence, mirroring `purchase_intent._delivery_is_missing`.

    The violation read behind `DELIVERY_METHOD_UNAVAILABLE` is a second Calculate Cart call, and
    it can fail on its own. An unexplained failure must not be reported to a customer as
    "Wix offers no delivery method here", so the parent refusal re-raises unchanged.

    FOUR scripted Calculate Cart calls now, not three, and the first one is new: 1 = the delivery
    OPTIONS read inside `prepare_delivery`, 2 = `calculate` (raises inside `purchase_intent`),
    3 = `preview` from `_delivery_is_missing`, 4 = `preview` from `_blocking_codes`. The first
    entry must offer an option, or the run refuses at step 1 and never reaches the no-evidence
    case this test is about.
    """
    h, fake, _lam, _wix, monkeypatch = env
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)
    wix = _ScriptedCalculateWix([_method_only_with_an_offered_option(),
                                 _method_only(), _method_only(),
                                 RuntimeError("wix is unreachable")])
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)

    response = h.handler(_prepare_event(), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_the_in_whatsapp_create_path_still_answers_a_recoverable_409(env):
    """`DeliveryMethodUnavailable` subclasses `DeliveryDetailsRequired`, and that is deliberate.

    `_create` is the retained in-WhatsApp path. Its existing first arm catches the parent, so
    the subclass needs no edit there: the answer stays `409 DELIVERY_DETAILS_REQUIRED` rather
    than becoming `500 INTERNAL_ERROR` (a plain `Exception`) or `409 AMOUNT_NOT_SETTLED` (a plain
    `ValueError`, via `_create`'s trailing arm).
    """
    h, fake, _lam, _wix, monkeypatch = env

    def refuse(identity, line_items, *, profile=None):
        raise h.DeliveryMethodUnavailable("wix offered no usable delivery method")

    monkeypatch.setattr(h, "_v2_snapshot", refuse)

    response = h.handler(_create_event(), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert fake.all_rows(ATTEMPTS_TABLE) == []
