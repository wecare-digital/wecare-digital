"""R7.4: a WhatsApp-origin order cannot be charged twice, and the proof is an ENUMERATION.

HOW THIS TEST IS BUILT, AND WHY IT IS BUILT THAT WAY
----------------------------------------------------
"It cannot charge again" is usually asserted as an absence - no `capture` call, no second
`create_order` - and an absence is exactly what a NEW call slips past. A test that says "capture
was not called" keeps passing when somebody adds `razorpay_orders.transfer` or a second Wix write.

So this file RECORDS every outbound provider call made while driving the whole path - hand-off ->
claim -> prepare -> verify -> reconcile - and then asserts the recorded set EQUAL to a written-out
permitted list. Adding any provider call to this path fails this test until the list is edited,
which is the point: editing it is a decision somebody has to make on purpose.

Then it replays the claim, the prepare and the webhook delivery and asserts not one count moves.

WHAT IS DELIBERATELY ABSENT FROM THE PATH AT ALL
------------------------------------------------
`razorpay_orders` has no capture function and no refund function - not a disabled one, not a gated
one. `test_the_razorpay_module_has_no_capture_or_refund_function_to_call` asserts that over the
module's public surface, because a path cannot be proven free of a call whose existence it never
checked.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys
import time
from collections import Counter

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import (  # noqa: E402
    cart_v2, contact_address, order_creation, whatsapp_basket as wb)
from lambda_utils.ecommerce.checkout_pricing import compute_quote  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402
from lambda_utils.integrations import razorpay_orders  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"

ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"

CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"
SESSION_PHONE = "+918100640044"
STORED_PHONE = customer_identity.normalize_phone_preserving_country(SESSION_PHONE)
OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}
COLLECTION_PAISE = 2549900
GATEWAY_ORDER_ID = "order_R7_4_fixture"
GATEWAY_PAYMENT_ID = "pay_R7_4_fixture"

#: EVERY Razorpay call this whole path is permitted to make, written out and asserted by EQUALITY.
#:
#: Four names. `create_order` mints the gateway order (once, on the website leg);
#: `find_order_by_receipt` is the idempotency read that makes a retried prepare resolve instead of
#: minting a second order; `account_mode` refuses a test key against live money;
#: `verify_checkout_signature` and `verifier_for_event` are the two halves of the capture readback
#: that is the ONLY thing allowed to assert the money moved.
#:
#: NOT HERE, AND THAT IS THE ASSERTION: no capture, no refund, no transfer, no settlement, no
#: payment-configuration read. Payment is taken by Razorpay Standard Checkout in the customer's
#: browser; nothing in this repo captures.
PERMITTED_RAZORPAY_CALLS = {
    "razorpay_orders.create_order",
    "razorpay_orders.account_mode",
    "razorpay_orders.verify_checkout_signature",
    "razorpay_verify.verifier_for_event",
}

#: PERMITTED BUT NOT REACHED, recorded so the equality above is not read as "this function is
#: forbidden". `find_order_by_receipt` is `prepare_checkout`'s resolve-before-generate read: it
#: finds an existing gateway order for a repeated request key instead of minting a second one. It
#: does not fire on this path because the SECOND prepare never gets that far - the
#: one-live-payment-per-basket guard answers `CART_ALREADY_PAID` first, which is a stronger
#: outcome than resolving the receipt. If it ever starts firing, the equality fails and somebody
#: reads this note.
PERMITTED_BUT_UNREACHED = {"razorpay_orders.find_order_by_receipt"}

#: Every Wix call the path is permitted to make, with cart and product ids normalised out so the
#: list is about SHAPE. One Create Cart, one product readback per line, one Get Cart, the delivery
#: address and method writes, and Calculate. No Create Order and no Create Checkout: a Wix order is
#: written back after the money is proven, by a different function, not from here.
#: `PATCH .../{id}` writes the owned delivery ADDRESS (the place of supply, loaded server-side and
#: never from a request body); `set-delivery-method` selects the shipping option Wix then prices;
#: `calculate` is the authoritative total. All three are reads-and-writes on a CART, none of them
#: places an order or moves money.
PERMITTED_WIX_CALLS = {
    "POST /ecom/v2/carts",
    "GET /ecom/v2/carts/{id}",
    "PATCH /ecom/v2/carts/{id}",
    "POST /ecom/v2/carts/{id}/set-delivery-method",
    "POST /ecom/v2/carts/{id}/calculate",
    "GET /stores/v3/products/{id}",
}

#: What must NEVER appear in the Wix set. A Wix ORDER is written back after the money is proven, by
#: `wix_writeback` from the webhook leg - not from a checkout - and a Wix CHECKOUT is the V1 path
#: this phase does not use. `create-order` here would be an order placed before a verified capture.
FORBIDDEN_WIX_FRAGMENTS = ("create-order", "orders", "checkout", "payments", "/v1/")


def delivery_complete():
    return json.loads((FIXTURES / "wix_cart_v2_delivery_complete.json").read_text())


def fixture_reference():
    return delivery_complete()["cart"]["lineItems"][0]["source"]["catalogReference"]


def handoff_lines():
    reference = fixture_reference()
    return [{"productId": reference["catalogItemId"],
             "variantId": reference["options"]["variantId"], "quantity": 1}]


def website_line_items():
    reference = fixture_reference()
    return [{"catalogReference": {"appId": reference["appId"],
                                  "catalogItemId": reference["catalogItemId"],
                                  "options": {"variantId": reference["options"]["variantId"]}},
             "quantity": 1}]


class _Identity:
    def __init__(self, customer_id=CUSTOMER, phone=SESSION_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "subject-1"

    def owns(self, cid):
        return bool(cid) and cid == self.customer_id


class ProviderLog:
    """Every outbound provider call, by name, with its count. The whole point of this file."""

    def __init__(self):
        self.calls = Counter()

    def record(self, name):
        self.calls[name] += 1

    def names(self):
        return set(self.calls)

    def snapshot(self):
        return dict(self.calls)


class RecordingWix:
    """The Wix transport, logging a NORMALISED path so the permitted list is about shape."""

    def __init__(self, log: ProviderLog):
        self.log = log
        self.response = delivery_complete()

    def __call__(self, endpoint, method="GET", body=None):
        self.log.record(f"{method.upper()} {self._shape(endpoint)}")
        if endpoint.startswith("/stores/v3/products/"):
            reference = fixture_reference()
            return {"product": {
                "id": reference["catalogItemId"], "visible": True,
                "variantsInfo": {"variants": [{
                    "id": reference["options"]["variantId"], "visible": True,
                    "inventoryStatus": {"inStock": True}}]}}}
        return copy.deepcopy(self.response)

    @staticmethod
    def _shape(endpoint: str) -> str:
        if endpoint.startswith("/stores/v3/products/"):
            return "GET /stores/v3/products/{id}".split(" ", 1)[1]
        if endpoint == cart_v2.BASE:
            return cart_v2.BASE
        rest = endpoint[len(cart_v2.BASE) + 1:] if endpoint.startswith(cart_v2.BASE + "/") else ""
        tail = rest.split("/", 1)[1] if "/" in rest else ""
        return f"{cart_v2.BASE}/{{id}}" + (f"/{tail}" if tail else "")


class _Payload:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw


class _TripwireLambda:
    """Any Lambda invoke from this path is a payment-configuration read or an in-chat send.

    Both are forbidden here: payment stays on the website, and `_build_payment_settings` - the
    per-WABA payment-configuration resolver - must never be reached by a catalogue order.
    """

    def invoke(self, **kwargs):
        raise AssertionError(
            "a WhatsApp-origin website checkout must invoke no Lambda: "
            f"{kwargs.get('FunctionName')}")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS_TABLE)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("ORDERS_TABLE", ORDERS_TABLE)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WIX_CART_V2_ENABLED", "true")
    monkeypatch.delenv("WIX_CART_V2_DISABLED", raising=False)

    spec = importlib.util.spec_from_file_location("checkout_r74_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(keys={ATTEMPTS_TABLE: "paymentAttemptId", KEYS_TABLE: "orderId",
                            CONTACTS_TABLE: "id", ORDERS_TABLE: "orderId"},
                      indexes={CONTACTS_TABLE: {"phone-index": ("phone", None)}})
    log = ProviderLog()
    wix = RecordingWix(log)
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_lambda_client", lambda: _TripwireLambda())
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)
    monkeypatch.setattr(h, "INITIATION_ENABLED", True)
    monkeypatch.setattr(h.customer_auth, "authenticate", lambda event: _Identity())
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", lambda customer_id: dict(OWNED))

    payable = compute_quote(COLLECTION_PAISE).total_payable_paise

    def create_order(*, amount_paise, receipt, notes):
        log.record("razorpay_orders.create_order")
        return {"id": GATEWAY_ORDER_ID, "amount": amount_paise, "currency": "INR",
                "status": "created", "receipt": receipt, "key_id": "fixture-live-publishable"}

    def find_order_by_receipt(receipt):
        log.record("razorpay_orders.find_order_by_receipt")
        return None

    def account_mode(key_id):
        log.record("razorpay_orders.account_mode")
        return "live"

    def verify_checkout_signature(*, stored_order_id, payment_id, signature):
        log.record("razorpay_orders.verify_checkout_signature")
        return True

    def verifier_for_event(**kwargs):
        log.record("razorpay_verify.verifier_for_event")
        # `(paid, provider_payment_id, amount_paise, currency)` - the authoritative capture
        # readback, which is the ONLY thing allowed to assert the money moved.
        return lambda reference: (True, GATEWAY_PAYMENT_ID, payable, "INR")

    monkeypatch.setattr(h.razorpay_orders, "create_order", create_order)
    monkeypatch.setattr(h.razorpay_orders, "find_order_by_receipt", find_order_by_receipt)
    monkeypatch.setattr(h.razorpay_orders, "account_mode", account_mode)
    monkeypatch.setattr(h.razorpay_orders, "verify_checkout_signature", verify_checkout_signature)
    monkeypatch.setattr(h.razorpay_verify, "verifier_for_event", verifier_for_event)

    seed_contact(fake)
    return h, fake, log, monkeypatch


def seed_contact(fake):
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-r74", "contactId": "contact-r74", "phone": STORED_PHONE,
        "email": "asha@example.com", "name": "Asha Sen", "firstName": "Asha", "lastName": "Sen",
        "checkoutCustomerId": CUSTOMER, "emailVerifiedAt": 1, "deletedAt": None,
        contact_address.ATTRIBUTE: dict(OWNED)})


def seed_handoff(fake, token="tok-r74"):
    """The hand-off the inbound Lambda would have written, through the same builder it uses."""
    basket = wb.Basket(lines=handoff_lines(), catalog_id="catalog-1", message_id="wamid.R74")
    row = wb.build_handoff(basket, SESSION_PHONE, token=token, now=int(time.time()))
    fake.Table(KEYS_TABLE).put_item(Item=row)
    return row


def event(action, **body):
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.8"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"action": action, **body}),
    }


def rows_with(fake, table, prefix):
    return [row for row in fake.all_rows(table)
            if str(row.get("orderId", "")).startswith(prefix)]


def drive(h, fake, *, request_key):
    """hand-off -> claim -> prepare -> verify. Returns the verify body."""
    claim = json.loads(h.handler(event("claim-basket", basket="tok-r74"), None)["body"])
    assert claim["status"] == "BASKET_CLAIMED", claim
    prepared = json.loads(h.handler(
        event("prepare", lineItems=website_line_items(), requestKey=request_key), None)["body"])
    assert prepared["status"] == "CHECKOUT_OPTIONS_READY", prepared
    verified = json.loads(h.handler(event(
        "verify", razorpay_order_id=GATEWAY_ORDER_ID, razorpay_payment_id=GATEWAY_PAYMENT_ID,
        razorpay_signature="fixture-signature"), None)["body"])
    return prepared, verified


def webhook_reconcile(h, fake):
    """The razorpay-webhook's own leg, driven directly: resolve the reference, reconcile.

    This is what a redelivered `payment.captured` does. It is included because the browser callback
    and the webhook are two independent triggers for one capture, and "cannot charge twice" has to
    hold across both rather than within either.
    """
    keys = fake.Table(KEYS_TABLE)
    payref = rows_with(fake, KEYS_TABLE, "PAYREF#")
    assert len(payref) == 1
    reference_id = str(payref[0]["referenceId"])
    loader = h._load_attempt_via(keys, provider_order_id=GATEWAY_ORDER_ID)
    return order_creation.reconcile_payment(
        table=keys, reference_id=reference_id,
        verify_payment=h.razorpay_verify.verifier_for_event(
            payment_id=GATEWAY_PAYMENT_ID, order_id=GATEWAY_ORDER_ID, load_attempt=loader),
        load_attempt=loader, expected_customer_id=CUSTOMER)


# ── the enumeration ───────────────────────────────────────────────────────────


def test_the_whole_path_makes_exactly_the_permitted_provider_calls(env):
    h, fake, log, _ = env
    seed_handoff(fake)
    _prepared, verified = drive(h, fake, request_key="request-r74-1")
    assert verified["status"] == "VERIFIED_PAID", verified

    razorpay = {name for name in log.names() if name.startswith("razorpay_")}
    # EQUALITY, not a subset. A newly added provider call fails here rather than slipping through.
    assert razorpay == PERMITTED_RAZORPAY_CALLS

    wix = {name for name in log.names() if not name.startswith("razorpay_")}
    assert wix == PERMITTED_WIX_CALLS
    # Over the CONSTANT as well as the observation, so widening the permitted list to admit an
    # order-placing call fails here rather than being accepted by the equality above.
    for fragment in FORBIDDEN_WIX_FRAGMENTS:
        assert not [name for name in wix | PERMITTED_WIX_CALLS if fragment in name], \
            f"a Wix {fragment} call reached a checkout that has not proven a capture"

    assert log.calls["razorpay_orders.create_order"] == 1
    assert len(rows_with(fake, ORDERS_TABLE, "")) == 1


def test_no_capture_no_refund_and_no_payment_configuration_read(env):
    h, fake, log, _ = env
    seed_handoff(fake)
    drive(h, fake, request_key="request-r74-2")

    forbidden = ("capture", "refund", "transfer", "settlement", "payout",
                 "payment_config", "payment_configuration")
    for word in forbidden:
        offenders = [name for name in log.names() if word in name.lower()]
        assert offenders == [], f"{word} reached the provider on a WhatsApp-origin order"
    # The Lambda tripwire is the other half: a payment-configuration read goes through
    # `_fetch_payment_configurations`, which invokes the WhatsApp business Lambda, and
    # `_TripwireLambda` raises on any invoke at all. Reaching this line means none happened.


def test_the_razorpay_module_has_no_capture_or_refund_function_to_call():
    """The strongest form of the claim: the function does not exist.

    A path cannot be proven free of a call whose existence it never checked, so this asserts the
    module's public surface rather than the path's behaviour. Razorpay Standard Checkout captures
    in the customer's browser; nothing in this repo captures, refunds or transfers.
    """
    public = {name for name in dir(razorpay_orders) if not name.startswith("_")}
    for forbidden in ("capture", "refund", "transfer", "payout", "settle"):
        assert not [name for name in public if forbidden in name.lower()], \
            f"razorpay_orders grew a {forbidden} function"


# ── replay ────────────────────────────────────────────────────────────────────


def test_replaying_the_claim_the_prepare_and_the_webhook_moves_nothing(env):
    h, fake, log, _ = env
    seed_handoff(fake)
    _prepared, verified = drive(h, fake, request_key="request-r74-3")
    assert verified["status"] == "VERIFIED_PAID"

    before = log.snapshot()
    orders_before = len(rows_with(fake, ORDERS_TABLE, ""))
    attempts_before = len(fake.all_rows(ATTEMPTS_TABLE))
    assert orders_before == 1 and attempts_before == 1

    # 1. THE CLAIM, REPLAYED. Refused: the row is already claimed.
    again = json.loads(h.handler(event("claim-basket", basket="tok-r74"), None)["body"])
    assert again["status"] == "BASKET_UNAVAILABLE"

    # 2. THE PREPARE, REPLAYED with the same request key.
    #
    # `CHECKOUT_AMBIGUOUS` / `CART_ALREADY_PAID` is the one-live-payment-per-basket guard, and it
    # is a BETTER outcome than a resolved receipt: the second prepare is refused before Razorpay is
    # contacted at all, so there is no path to a second gateway order for a paid cart. The copy the
    # page shows for it deliberately does not invite a retry.
    repeated = json.loads(h.handler(
        event("prepare", lineItems=website_line_items(),
              requestKey="request-r74-3"), None)["body"])
    assert repeated["status"] == "CHECKOUT_AMBIGUOUS", repeated
    assert repeated["reason"] == "CART_ALREADY_PAID"

    # 3. THE WEBHOOK, DELIVERED, then REDELIVERED. Both must resolve to the existing order.
    first = webhook_reconcile(h, fake)
    second = webhook_reconcile(h, fake)
    assert first.outcome == order_creation.ORDER_ALREADY_EXISTS, first
    assert second.outcome == order_creation.ORDER_ALREADY_EXISTS, second
    assert first.order_number == second.order_number

    assert len(rows_with(fake, ORDERS_TABLE, "")) == orders_before, "a second order row appeared"
    assert len(fake.all_rows(ATTEMPTS_TABLE)) == attempts_before
    assert log.calls["razorpay_orders.create_order"] == \
        before["razorpay_orders.create_order"] == 1
    # No provider call NAME appeared that was not already permitted, however many times the
    # replay ran.
    assert {name for name in log.names() if name.startswith("razorpay_")} \
        == PERMITTED_RAZORPAY_CALLS


def test_the_order_row_carries_the_whatsapp_channel_and_the_website_checkout_mode(env):
    """Attribution travels; mechanics do not. A WhatsApp-origin order settles exactly like a
    website one, which is why there is no second payment path to charge twice through."""
    h, fake, _log, _ = env
    seed_handoff(fake)
    _prepared, verified = drive(h, fake, request_key="request-r74-4")
    assert verified["status"] == "VERIFIED_PAID"

    orders = rows_with(fake, ORDERS_TABLE, "")
    assert len(orders) == 1
    assert orders[0]["channel"] == "whatsapp"
    assert orders[0]["checkoutMode"] == "WEBSITE_RAZORPAY_STANDARD"
    assert orders[0]["currency"] == "INR"
    assert orders[0]["amountPaise"] == compute_quote(COLLECTION_PAISE).total_payable_paise
    assert type(orders[0]["amountPaise"]) is int
