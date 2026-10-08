"""`action: "claim-basket"` adopts a WhatsApp hand-off, and the price that follows is the website's.

The last test in this file is the one the whole feature exists for. The replaced inbound path
computed a total from Meta's `item_price` with a float, 18% GST on goods Wix had already taxed and
a 2% fee; here the payable for a WhatsApp-origin basket is asserted to equal
`checkout_pricing.compute_quote` over the Wix-calculated collection EXACTLY, in integer paise. That
equality is what replaces the deleted reprice - not a corrected second calculator, but the absence
of one.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import contact_address, whatsapp_basket as wb  # noqa: E402
from lambda_utils.ecommerce.checkout_pricing import compute_quote  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"

ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
#: Needed only by the tests that carry a claim all the way to a verified capture, because
#: `finalization.accept_paid` is the single writer of the order row - and the pointer release this
#: file asserts happens immediately after it.
ORDERS_TABLE = "stack-wecare-digital-OrderTable"

#: The ids `_prepare`'s stubbed `create_order` mints, reused by `_verify`.
GATEWAY_ORDER_ID = "order-claim-1"
GATEWAY_PAYMENT_ID = "pay-claim-1"

CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"
OTHER_CUSTOMER = "CUS_01J8Z9SOMEBODYELSE00"
#: The owner-nominated QA recipient, which is what the Cart V2 fixtures in this repo already use
#: as a customer phone. It is NOT a business number.
SESSION_PHONE = "+918100640044"
STORED_PHONE = customer_identity.normalize_phone_preserving_country(SESSION_PHONE)
OTHER_PHONE = "+919812345678"

OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}

#: Wix collection 25499.00 = items 24999.00 + delivery 500.00, from the shared fixture. Stated
#: here and re-derived through `compute_quote` below rather than copied from the implementation.
COLLECTION_PAISE = 2549900


def delivery_complete():
    return json.loads((FIXTURES / "wix_cart_v2_delivery_complete.json").read_text())


def fixture_reference():
    return delivery_complete()["cart"]["lineItems"][0]["source"]["catalogReference"]


def handoff_lines(quantity=1):
    """The hand-off's lines, naming the SAME Wix variant the fixture cart holds.

    Deliberately the fixture's own variant: the point of `retailer_id = wix:<product>:<variant>`
    is that a WhatsApp line and a website line resolve to one Wix cart line, and a test using a
    different id would prove the plumbing while hiding that.
    """
    reference = fixture_reference()
    return [{"productId": reference["catalogItemId"],
             "variantId": reference["options"]["variantId"],
             "quantity": quantity}]


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


class _Payload:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw


class _FakeLambda:
    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        event = json.loads(Payload.decode("utf-8"))
        if "payment-config" in str(event.get("path") or ""):
            inner = {"statusCode": 200, "body": json.dumps({"data": [{
                "configuration_name": "WECAREDIGITAL", "status": "active",
                "payment_gateway": {"type": "razorpay", "merchant_id": "acc_TESTMID"}}]})}
        else:
            inner = {"statusCode": 200, "body": "{}"}
        return {"Payload": _Payload(json.dumps(inner).encode("utf-8"))}


class RecordingWix:
    """Replays a Cart V2 response and records every call, so a test can enumerate them."""

    def __init__(self):
        self.response = delivery_complete()
        self.requests = []

    def __call__(self, endpoint, method="GET", body=None):
        self.requests.append((method.upper(), endpoint, copy.deepcopy(body)))
        if endpoint.startswith("/stores/v3/products/"):
            reference = fixture_reference()
            return {"product": {
                "id": reference["catalogItemId"], "visible": True,
                "variantsInfo": {"variants": [{
                    "id": reference["options"]["variantId"], "visible": True,
                    "inventoryStatus": {"inStock": True}}]}}}
        return copy.deepcopy(self.response)

    def paths(self):
        return [path for _method, path, _body in self.requests]

    def creates(self):
        """Every Create Cart call. `cart_v2.BASE` rather than a typed path, so a base change
        cannot make this quietly count zero and pass."""
        from lambda_utils.ecommerce import cart_v2
        return [body for method, path, body in self.requests
                if method == "POST" and path == cart_v2.BASE]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS_TABLE)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("ORDERS_TABLE", ORDERS_TABLE)
    monkeypatch.setenv("EXPECTED_CONFIGURATION_NAME", "WECAREDIGITAL")
    monkeypatch.setenv("EXPECTED_PROVIDER_MID", "acc_TESTMID")
    monkeypatch.setenv("PAYMENT_WABA_ID", "2094615664435155")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WIX_CART_V2_ENABLED", "true")
    monkeypatch.delenv("WIX_CART_V2_DISABLED", raising=False)

    spec = importlib.util.spec_from_file_location("checkout_claim_basket_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(keys={ATTEMPTS_TABLE: "paymentAttemptId", KEYS_TABLE: "orderId",
                            CONTACTS_TABLE: "id", ORDERS_TABLE: "orderId"},
                      indexes={CONTACTS_TABLE: {"phone-index": ("phone", None)}})
    wix = RecordingWix()
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_lambda_client", lambda: _FakeLambda())
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)
    monkeypatch.setattr(h, "INITIATION_ENABLED", False)
    monkeypatch.setattr(h.customer_auth, "authenticate", lambda event: _Identity())
    monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", lambda customer_id: dict(OWNED))
    seed_contact(fake)
    return h, fake, wix, monkeypatch


def seed_contact(fake, *, phone=STORED_PHONE, customer=CUSTOMER):
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-claim-1", "contactId": "contact-claim-1", "phone": phone,
        "email": "asha@example.com", "name": "Asha Sen", "firstName": "Asha", "lastName": "Sen",
        "checkoutCustomerId": customer, "emailVerifiedAt": 1, "deletedAt": None,
        contact_address.ATTRIBUTE: dict(OWNED),
    })


def seed_handoff(fake, *, phone=SESSION_PHONE, token="tok-claim-1", quantity=1,
                 now=None, claimed=False):
    """A hand-off row exactly as the inbound handler writes one, through the same builder.

    `now` defaults to the REAL clock because the handler compares `expiresAt` against
    `time.time()`: a fixed timestamp would be an expired basket the moment the lifetime elapsed in
    wall-clock terms, and the test would fail for a reason that has nothing to do with claiming.
    """
    now = int(time.time()) if now is None else now
    basket = wb.Basket(lines=handoff_lines(quantity), catalog_id="catalog-1",
                       message_id="wamid.CLAIM")
    row = wb.build_handoff(basket, phone, token=token, now=now)
    if claimed:
        row = dict(row, claimedAt=now + 1, claimedBy=CUSTOMER)
    fake.Table(KEYS_TABLE).put_item(Item=row)
    return row


def event(action, **body):
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.8"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"action": action, **body}),
    }


def carts_in(fake):
    return [row for row in fake.all_rows(KEYS_TABLE)
            if str(row.get("orderId", "")).startswith("CUSTOMERCART#")]


def handoff_row(fake, token="tok-claim-1"):
    return fake.Table(KEYS_TABLE).get_item(Key={"orderId": wb.handoff_key(token)}).get("Item")


def saved_cart(fake):
    """The `CUSTOMERCART#<phone>` pointer row. One per identity, so there is exactly one."""
    rows = carts_in(fake)
    assert len(rows) == 1, rows
    return rows[0]


def claim_pointer(fake, customer=CUSTOMER):
    return fake.Table(KEYS_TABLE).get_item(
        Key={"orderId": wb.claim_pointer_key(customer)}).get("Item")


def line_items_from(lines):
    """The browser's `toLineItems()`, applied to the lines the CLAIM returned.

    Deliberately NOT `website_line_items()`: driving the prepare from a fixture proves the pricing
    while hiding whether the claim's own lines can reach it at all, which is the defect this
    conversion exists to close. The `appId` is supplied here because `src/lib/cart.ts::toLineItems`
    supplies it too - it is a constant of the Wix Stores app, not part of the hand-off.
    """
    app_id = fixture_reference()["appId"]
    return [{"catalogReference": {"appId": app_id,
                                  "catalogItemId": line["productId"],
                                  "options": {"variantId": line["variantId"]}},
             "quantity": line["quantity"]}
            for line in lines]


# ── the happy path ────────────────────────────────────────────────────────────


def test_a_claim_by_the_owning_phone_merges_the_lines_and_marks_the_row_claimed(env):
    h, fake, wix, _ = env
    seed_handoff(fake)

    response = h.handler(event("claim-basket", basket="tok-claim-1"), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "BASKET_CLAIMED"
    assert body["channel"] == "whatsapp"
    assert body["mergedLines"] == 1
    # No money field in the reply. This action quotes nothing.
    assert not [key for key in body if "paise" in key.lower() or "amount" in key.lower()
                or "total" in key.lower()]

    # The lines reached Wix, as a catalog reference rather than as anything of ours.
    created = wix.creates()
    assert len(created) == 1
    reference = created[0]["catalogItems"][0]["catalogReference"]
    assert reference["catalogItemId"] == fixture_reference()["catalogItemId"]
    assert reference["options"]["variantId"] == fixture_reference()["options"]["variantId"]
    assert created[0]["catalogItems"][0]["quantity"] == 1

    row = handoff_row(fake)
    assert row["claimedAt"] > 0
    assert row["claimedBy"] == CUSTOMER
    assert len(carts_in(fake)) == 1


def test_the_claim_writes_the_channel_pointer_the_prepare_reads(env):
    h, fake, _wix, _ = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)

    pointer = fake.Table(KEYS_TABLE).get_item(
        Key={"orderId": wb.claim_pointer_key(CUSTOMER)}).get("Item")
    assert pointer["channel"] == "whatsapp"
    assert pointer["customerId"] == CUSTOMER
    assert pointer["handoffId"] == "WABASKET#tok-claim-1"
    # BOUND TO THE CART the lines were merged into, not just to the customer. See
    # `test_a_prepare_for_a_different_cart_than_the_claimed_one_is_attributed_website`.
    assert pointer["wixCartId"] == saved_cart(fake)["wixCartId"]
    # And the seam itself answers with it.
    assert h._claimed_handoff(_Identity(), {})["channel"] == "whatsapp"


def test_the_claim_returns_the_lines_so_the_browser_cart_can_hold_the_same_basket(env):
    """THE HAND-OFF HAS TO REACH THE CART THE CUSTOMER PAYS FROM, which is the browser's.

    The claim merges the lines into the SERVER-side Wix cart, but /cart/ renders `readCart()` from
    localStorage and `proceed` posts `toLineItems()` built from that same storage. A reply carrying
    only `mergedLines` left that cart untouched, so a successful claim showed no new items - and
    the next checkout reconciled the claimed lines straight back OUT of the Wix cart, because
    `_reconcile_saved_cart` makes the Wix cart match the REQUEST.

    STILL NO MONEY FIELD. The lines are catalogue references and quantities; the payable is
    produced once, by `compute_quote`, on the prepare that follows.
    """
    h, fake, _wix, _ = env
    seed_handoff(fake, quantity=2)

    body = json.loads(h.handler(event("claim-basket", basket="tok-claim-1"), None)["body"])
    assert body["status"] == "BASKET_CLAIMED"
    assert body["lines"] == handoff_lines(quantity=2)
    assert body["mergedLines"] == len(body["lines"])

    # Exactly the three keys `cart_v2.catalog_item` accepts, and nothing resembling a price.
    for line in body["lines"]:
        assert set(line) == {"productId", "variantId", "quantity"}
        assert type(line["quantity"]) is int
    rendered = json.dumps(body).lower()
    for forbidden in ("paise", "amount", "price", "total", "currency", "phone"):
        assert forbidden not in rendered


# ── the refusals, all identical ───────────────────────────────────────────────


def test_a_claim_by_a_different_phone_merges_nothing_and_is_refused(env):
    h, fake, wix, monkeypatch = env
    seed_handoff(fake, phone=OTHER_PHONE)

    response = h.handler(event("claim-basket", basket="tok-claim-1"), None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["status"] == "BASKET_UNAVAILABLE"
    assert wix.creates() == []
    assert carts_in(fake) == []
    assert "claimedAt" not in handoff_row(fake)


def test_every_refusal_is_byte_identical_so_the_endpoint_is_not_an_existence_oracle(env):
    """Four different facts, one answer: no such token, somebody else's, already claimed, expired.

    Distinguishing them would let a caller holding a guessed token learn that it names a real
    basket, and a caller holding a real token learn whose it is.
    """
    h, fake, _wix, _ = env
    answers = set()

    answers.add(h.handler(event("claim-basket", basket="never-issued"), None)["body"])

    seed_handoff(fake, phone=OTHER_PHONE, token="tok-other")
    answers.add(h.handler(event("claim-basket", basket="tok-other"), None)["body"])

    seed_handoff(fake, token="tok-claimed", claimed=True)
    answers.add(h.handler(event("claim-basket", basket="tok-claimed"), None)["body"])

    seed_handoff(fake, token="tok-expired", now=1)      # expired long ago against a real clock
    answers.add(h.handler(event("claim-basket", basket="tok-expired"), None)["body"])

    answers.add(h.handler(event("claim-basket", basket=""), None)["body"])

    assert len(answers) == 1
    assert json.loads(answers.pop())["status"] == "BASKET_UNAVAILABLE"


def test_a_second_claim_of_the_same_row_is_refused_and_leaves_one_cart(env):
    h, fake, wix, _ = env
    seed_handoff(fake)

    first = h.handler(event("claim-basket", basket="tok-claim-1"), None)
    second = h.handler(event("claim-basket", basket="tok-claim-1"), None)

    assert json.loads(first["body"])["status"] == "BASKET_CLAIMED"
    assert second["statusCode"] == 404
    assert json.loads(second["body"])["status"] == "BASKET_UNAVAILABLE"
    assert len(carts_in(fake)) == 1
    assert len(wix.creates()) == 1, "a second claim must not mint a second Wix cart"


def test_a_token_naming_a_row_of_another_kind_is_refused(env):
    """CommerceKeys shares one partition key, so `PAYREF#` and `CUSTOMERCART#` rows live beside the
    baskets. The `WABASKET#` prefix in the key, plus `claimable`'s own prefix check, is what stops
    a token addressing one of them."""
    h, fake, _wix, _ = env
    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "WABASKET#WD-PAY-1", "customerId": CUSTOMER, "amountPaise": 100})
    response = h.handler(event("claim-basket", basket="WD-PAY-1"), None)
    assert response["statusCode"] == 404
    assert carts_in(fake) == []


def test_an_unauthenticated_call_is_refused_before_any_read(env):
    h, fake, wix, monkeypatch = env
    seed_handoff(fake)

    def refuse(event_):
        # `CustomerNotAuthenticated`, which is what `require_customer` converts into the 401.
        raise h.customer_auth.CustomerNotAuthenticated("no session")

    monkeypatch.setattr(h.customer_auth, "authenticate", refuse)
    monkeypatch.setattr(fake, "Table",
                        lambda name: pytest.fail("an unauthenticated claim must read nothing"))

    response = h.handler(event("claim-basket", basket="tok-claim-1"), None)
    assert response["statusCode"] == 401
    assert wix.creates() == []


# ── the website cart already in use ───────────────────────────────────────────


def test_an_existing_website_cart_is_reported_and_the_basket_stays_claimable(env):
    """`ensure` is resolve-before-generate: it returns the live cart and does not add to it.

    So the honest answer is to say the lines did not land and LEAVE THE ROW UNCLAIMED, rather than
    report success for a merge that did not happen or discard lines the customer added on the
    website. Nothing is lost: the same link works again once the website cart is empty.
    """
    h, fake, wix, _ = env
    seed_handoff(fake)
    # A live cart for this identity, exactly as the `/wix-store/cart` route leaves one.
    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "CUSTOMERCART#" + SESSION_PHONE, "customerId": CUSTOMER, "version": 1,
        "wixCartId": delivery_complete()["cart"]["id"], "expiresAt": 9_999_999_999})

    response = h.handler(event("claim-basket", basket="tok-claim-1"), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "BASKET_CART_IN_USE"
    assert body["handoffLines"] == 1
    assert wix.creates() == [], "no second Wix cart"
    assert "claimedAt" not in handoff_row(fake), "the basket must stay claimable"
    assert h._claimed_handoff(_Identity(), {}) is None, "an unclaimed basket is not an attribution"


def test_a_stale_saved_cart_is_released_by_the_one_retry_rather_than_dead_ending(env):
    """`BASKET_CART_IN_USE` USED TO BE A DEAD END, AND THIS IS THE WAY OUT.

    The condition is the SERVER-side `CUSTOMERCART#<phone>` pointer, which lives thirty days and
    SURVIVES the payment that consumed its cart - nothing in this repository abandons it at
    payment. `clearCart()` empties localStorage only. So a customer who had paid once on the
    website, then sent a WhatsApp cart, was told to "empty your website cart" with no way to do
    it, and the link kept returning the same answer until the pointer expired.

    `src/pages/cart.tsx` retries ONCE with `resetCart: true` when its OWN cart is empty, which is
    the case where there is nothing of the customer's to lose. This is the server half: the saved
    pointer is released and `ensure` then creates a fresh cart holding the hand-off lines.
    """
    h, fake, wix, _ = env
    seed_handoff(fake)
    stale = delivery_complete()["cart"]["id"]
    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "CUSTOMERCART#" + SESSION_PHONE, "customerId": CUSTOMER, "version": 1,
        "wixCartId": stale, "expiresAt": 9_999_999_999})

    first = json.loads(h.handler(event("claim-basket", basket="tok-claim-1"), None)["body"])
    assert first["status"] == "BASKET_CART_IN_USE"
    assert wix.creates() == []

    retried = json.loads(h.handler(
        event("claim-basket", basket="tok-claim-1", resetCart=True), None)["body"])
    assert retried["status"] == "BASKET_CLAIMED"
    assert retried["lines"] == handoff_lines()
    assert len(wix.creates()) == 1, "the released pointer let a fresh cart be created"
    assert handoff_row(fake)["claimedAt"] > 0
    # And the pointer names the NEW cart, so attribution follows the basket that was claimed.
    assert claim_pointer(fake)["wixCartId"] == saved_cart(fake)["wixCartId"]
    assert h._claimed_handoff(_Identity(), {})["channel"] == "whatsapp"


def test_reset_cart_is_an_identity_comparison_so_a_truthy_string_does_not_release_anything(env):
    """`is True`, the same reading `_website_prepare` uses. A typo must not be destructive."""
    h, fake, wix, _ = env
    seed_handoff(fake)
    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "CUSTOMERCART#" + SESSION_PHONE, "customerId": CUSTOMER, "version": 1,
        "wixCartId": delivery_complete()["cart"]["id"], "expiresAt": 9_999_999_999})

    for value in ("true", 1, "yes", [], {}):
        body = json.loads(h.handler(
            event("claim-basket", basket="tok-claim-1", resetCart=value), None)["body"])
        assert body["status"] == "BASKET_CART_IN_USE", value
    assert wix.creates() == []
    assert "claimedAt" not in handoff_row(fake)


def test_the_cart_in_use_sentence_is_the_same_on_both_sides(env):
    """One sentence, two files, pinned equal so they cannot drift.

    The handler returns the copy and `src/lib/whatsappBasket.ts::claimMessage` repeats it, because
    the browser shows it without a round trip when it already knows the outcome. Two copies of a
    customer-facing instruction is two things to get wrong; this is the cheaper half of sharing it.
    """
    h, fake, _wix, _ = env
    seed_handoff(fake)
    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "CUSTOMERCART#" + SESSION_PHONE, "customerId": CUSTOMER, "version": 1,
        "wixCartId": delivery_complete()["cart"]["id"], "expiresAt": 9_999_999_999})
    served = json.loads(h.handler(
        event("claim-basket", basket="tok-claim-1"), None)["body"])["message"]

    source = (ROOT / "src/lib/whatsappBasket.ts").read_text(encoding="utf-8")
    arm = source.split("case 'CART_IN_USE':", 1)[1].split("case '", 1)[0]
    # COMMENT LINES ARE DROPPED FIRST, and that is not fussiness: the comment above the literal
    # explains the rule and contains an apostrophe, which a bare quote-matching regex reads as the
    # start of a string and then mangles the whole arm.
    statement = "\n".join(line for line in arm.splitlines()
                          if not line.strip().startswith("//"))
    statement = statement.split("return", 1)[1].split(";", 1)[0]
    # The literal is written as two concatenated single-quoted parts, so the parts are joined
    # rather than matched one at a time - a drift in either half has to fail.
    browser = "".join(re.findall(r"'([^']*)'", statement))

    assert browser == served, f"browser: {browser!r}\nserver : {served!r}"


# ── the channel reaches the money, and the money is compute_quote's ───────────


def _prepare(h, monkeypatch, *, request_key, line_items=None):
    """A real website prepare with the initiation gate on and Razorpay stubbed.

    Returns `(response_body, created_order)`. Razorpay's `create_order` is RECORDED rather than
    asserted here so the amount it was handed can be compared against `compute_quote` directly -
    the thing that was wrong before this feature.

    `line_items` defaults to the fixture basket for the tests that are not about the hand-off; the
    claimed-basket tests pass `line_items_from(claim["lines"])`, which is what the browser sends
    after merging a claim into its cart.
    """
    created = {}

    def create_order(*, amount_paise, receipt, notes):
        created.update(amount=amount_paise, receipt=receipt, notes=dict(notes))
        return {"id": "order-claim-1", "amount": amount_paise, "currency": "INR",
                "status": "created", "receipt": receipt, "key_id": "fixture-live-publishable"}

    monkeypatch.setattr(h, "INITIATION_ENABLED", True)
    monkeypatch.setattr(h.razorpay_orders, "create_order", create_order)
    monkeypatch.setattr(h.razorpay_orders, "find_order_by_receipt", lambda receipt: None)
    monkeypatch.setattr(h.razorpay_orders, "account_mode", lambda key_id: "live")
    response = h.handler(event(
        "prepare",
        lineItems=website_line_items() if line_items is None else line_items,
        requestKey=request_key), None)
    return json.loads(response["body"]), created


def _verify(h, monkeypatch):
    """The browser callback, with the signature check and the capture readback stubbed TRUE.

    The readback is the only thing allowed to assert that money moved, so it is stubbed at
    `razorpay_verify.verifier_for_event` rather than anywhere further down - and it returns the
    `compute_quote` payable, in integer paise, with the currency compared explicitly as INR by the
    code under test. Nothing here captures, refunds or reads a payment configuration.
    """
    payable = compute_quote(COLLECTION_PAISE).total_payable_paise
    monkeypatch.setattr(h.razorpay_orders, "verify_checkout_signature", lambda **_: True)
    monkeypatch.setattr(
        h.razorpay_verify, "verifier_for_event",
        lambda **_: (lambda reference: (True, GATEWAY_PAYMENT_ID, payable, "INR")))
    response = h.handler(event("verify", razorpay_order_id=GATEWAY_ORDER_ID,
                               razorpay_payment_id=GATEWAY_PAYMENT_ID,
                               razorpay_signature="fixture-signature"), None)
    return json.loads(response["body"])


def test_the_claimed_channel_reaches_the_attempt_and_the_payref_row(env):
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)

    body, _created = _prepare(h, monkeypatch, request_key="request-claim-1")
    assert body["status"] == "CHECKOUT_OPTIONS_READY"

    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    assert attempts[0]["channel"] == "whatsapp"
    # `checkoutMode` is MECHANICS and is unchanged. Channel is attribution; conflating them would
    # open a second finalisation path.
    assert attempts[0]["checkoutMode"] == "WEBSITE_RAZORPAY_STANDARD"

    payref = [row for row in fake.all_rows(KEYS_TABLE)
              if str(row.get("orderId", "")).startswith("PAYREF#")]
    assert len(payref) == 1
    assert payref[0]["channel"] == "whatsapp"
    assert payref[0]["checkoutMode"] == "WEBSITE_RAZORPAY_STANDARD"


def test_a_prepare_with_no_claim_is_attributed_to_the_website(env):
    h, fake, _wix, monkeypatch = env
    body, _created = _prepare(h, monkeypatch, request_key="request-website-1")
    assert body["status"] == "CHECKOUT_OPTIONS_READY"
    assert fake.all_rows(ATTEMPTS_TABLE)[0]["channel"] == "website"


def test_a_prepare_for_a_different_cart_than_the_claimed_one_is_attributed_website(env):
    """THE POINTER DESCRIBES A BASKET, NOT A CUSTOMER, and this is what makes that true.

    `WABASKETCLAIM#<customerId>` is keyed on the customer and lives thirty days, and nothing
    releases it. So a claim followed - days later, on a different cart - by an ordinary website
    order used to stamp `whatsapp` on that order's attempt, its `PAYREF#` row, the order row, the
    `/orders` tag and the `Source:` line of a GST tax invoice.

    A mismatch degrades to `website` exactly as a malformed pointer does: the asymmetric default
    that under-claims the WhatsApp channel rather than mislabelling a website order.
    """
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)
    assert h._claimed_handoff(_Identity(), {})["channel"] == "whatsapp"

    # The pointer still names the cart it was claimed for, and the customer is now on a different
    # one - which is what the CartGone recovery and the stale-delivery abandon both leave behind,
    # and what a consumed cart becomes. Written from the pointer's side so the rest of the prepare
    # runs against the fixture cart exactly as it does for any other basket.
    pointer = claim_pointer(fake)
    assert pointer["expiresAt"] > int(time.time()), "still inside the pointer lifetime"
    assert pointer["wixCartId"] == saved_cart(fake)["wixCartId"]
    fake.Table(KEYS_TABLE).put_item(Item={**pointer,
                                          "wixCartId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"})

    assert h._claimed_handoff(_Identity(), {}) is None
    body, _created = _prepare(h, monkeypatch, request_key="request-other-cart-1")
    assert body["status"] == "CHECKOUT_OPTIONS_READY"
    assert fake.all_rows(ATTEMPTS_TABLE)[0]["channel"] == "website"


def test_no_cart_at_all_is_not_an_attribution_either(env):
    """An expired or absent `CUSTOMERCART#` row means there is no basket for the label to describe.

    `resolve` answers `None` for both, and `None` is a mismatch rather than a wildcard - the
    fail-closed direction, and the one a pointer written before `wixCartId` existed also takes.
    """
    h, fake, _wix, _ = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)

    saved = saved_cart(fake)
    fake.Table(KEYS_TABLE).put_item(Item={**saved, "expiresAt": 1})
    assert h._claimed_handoff(_Identity(), {}) is None


def test_a_locked_cart_degrades_to_no_claim_rather_than_failing_the_prepare(env):
    """`CustomerCart.resolve` raises `CartBusy` on a locked row, and this read is on the money path.

    A DynamoDB blip or a concurrent cart operation must not turn a checkout into a 500 over a
    LABEL, so the cart read is inside the same never-raises contract as the pointer read.
    """
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)

    saved = saved_cart(fake)
    fake.Table(KEYS_TABLE).put_item(Item={**saved, "busy": "a-lock-held-elsewhere"})
    assert h._claimed_handoff(_Identity(), {}) is None


def test_the_pointer_is_released_when_the_basket_it_names_is_paid(env):
    """A PAID BASKET IS NO LONGER "the basket this customer is about to pay for".

    Binding the pointer to the cart is necessary and NOT sufficient on its own, which is measured
    rather than assumed: nothing in this repository abandons `CUSTOMERCART#<phone>` at payment, so
    the next website prepare resolves the very same Wix cart id and the pointer would still match
    it. `_finalize` therefore expires the pointer after `accept_paid` has written the order - the
    order row already carries `channel`, so releasing the label changes nothing about what was
    just recorded.

    Expired rather than deleted, because this function's IAM grants no `DeleteItem` on
    CommerceKeys; `active_claim` reads `expiresAt > now`, so the two are the same answer.
    """
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    h.handler(event("claim-basket", basket="tok-claim-1"), None)
    _body, _created = _prepare(h, monkeypatch, request_key="request-paid-1")
    assert fake.all_rows(ATTEMPTS_TABLE)[0]["channel"] == "whatsapp"

    verified = _verify(h, monkeypatch)
    assert verified["status"] == "VERIFIED_PAID", verified

    assert claim_pointer(fake)["expiresAt"] == 0
    # Which is what the next website order reads, on the same cart, inside the same thirty days.
    assert h._claimed_handoff(_Identity(), {}) is None


def test_paying_without_ever_claiming_does_not_create_a_pointer_row(env):
    """The release is conditional on the row existing, so an ordinary website order is unchanged.

    A blind put would hand every paying customer a `WABASKETCLAIM#` row they never earned.
    """
    h, fake, _wix, monkeypatch = env
    _body, _created = _prepare(h, monkeypatch, request_key="request-plain-website-1")
    assert _verify(h, monkeypatch)["status"] == "VERIFIED_PAID"
    assert claim_pointer(fake) is None


def test_the_payable_for_a_whatsapp_basket_is_compute_quote_exactly_in_integer_paise(env):
    """THE TEST THAT REPLACES THE DELETED FLOAT/2% REPRICE.

    The old inbound path produced its own number from Meta's `item_price`. There is now exactly
    one number, it comes from `compute_quote` over the collection WIX calculated, and it is what
    Razorpay is asked to charge. Asserted by equality against a freshly computed quote - not
    against a copied constant - so a change to the fee or its GST has to be a change to
    `checkout_pricing` and shows up here as a matching move on both sides.
    """
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    claim = json.loads(h.handler(event("claim-basket", basket="tok-claim-1"), None)["body"])
    # DRIVEN FROM THE CLAIM, NOT FROM A FIXTURE. The prepare is given exactly the lines the claim
    # handed back, converted the way the browser's `toLineItems()` converts its cart - so this
    # asserts the journey rather than the arithmetic alone. A reply that returned no lines cannot
    # reach this assertion at all.
    body, created = _prepare(h, monkeypatch, request_key="request-claim-money-1",
                             line_items=line_items_from(claim["lines"]))

    quote = compute_quote(COLLECTION_PAISE)
    assert created["amount"] == quote.total_payable_paise
    assert body["options"]["amountPaise"] == quote.total_payable_paise
    assert body["options"]["currency"] == "INR"
    # Integers, not Decimals and certainly not floats, all the way out.
    assert type(created["amount"]) is int
    # The collection is Wix's and the only things added are the convenience fee and its GST.
    assert quote.total_payable_paise == (COLLECTION_PAISE
                                         + quote.convenience_fee_paise
                                         + quote.convenience_gst_paise)
    # The goods GST is NOT re-added, which is what the replaced path did with `gst_rate: 18.0`.
    assert quote.collection_before_convenience_paise == COLLECTION_PAISE


def test_the_same_basket_claimed_on_either_channel_costs_the_same(env):
    """Two channels, one catalogue, one price. The hand-off changes attribution and nothing else."""
    h, fake, _wix, monkeypatch = env
    _website, website_order = _prepare(h, monkeypatch, request_key="request-parity-website")

    # A second identity, so the two legs do not share a cart or an attempt.
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-claim-2", "contactId": "contact-claim-2", "phone":
            customer_identity.normalize_phone_preserving_country(OTHER_PHONE),
        "email": "bina@example.com", "name": "Bina Roy", "firstName": "Bina", "lastName": "Roy",
        "checkoutCustomerId": OTHER_CUSTOMER, "emailVerifiedAt": 1, "deletedAt": None,
        contact_address.ATTRIBUTE: dict(OWNED)})
    other = _Identity(customer_id=OTHER_CUSTOMER, phone=OTHER_PHONE)
    monkeypatch.setattr(h.customer_auth, "authenticate", lambda event_: other)
    seed_handoff(fake, phone=OTHER_PHONE, token="tok-parity")
    assert json.loads(h.handler(event("claim-basket", basket="tok-parity"),
                                None)["body"])["status"] == "BASKET_CLAIMED"
    _whatsapp, whatsapp_order = _prepare(h, monkeypatch, request_key="request-parity-whatsapp")

    assert whatsapp_order["amount"] == website_order["amount"]
    assert whatsapp_order["amount"] == compute_quote(COLLECTION_PAISE).total_payable_paise


# ── the action wiring ─────────────────────────────────────────────────────────


def test_claim_basket_is_an_explicit_action_and_not_the_create_fallback(env):
    h, _fake, _wix, _ = env
    assert h._action({}, {"action": "claim-basket"}) == "claim-basket"
    assert h._action({}, {"action": "CLAIM-BASKET"}) == "claim-basket"
    # And an unrecognised action still falls through to `create`, unchanged.
    assert h._action({}, {"action": "nonsense"}) == "create"


def test_the_claim_action_reads_no_meta_payment_configuration(env):
    """Payment stays on the website through Razorpay. A claim must not touch the in-chat payment
    surface at all - no readiness read, no sender invoke, no `order_details`."""
    h, fake, _wix, monkeypatch = env
    seed_handoff(fake)
    monkeypatch.setattr(h, "_lambda_client",
                        lambda: pytest.fail("a claim must not invoke the WhatsApp sender"))
    monkeypatch.setattr(h, "_readiness",
                        lambda: pytest.fail("a claim must not read a payment configuration"))
    assert json.loads(h.handler(event("claim-basket", basket="tok-claim-1"),
                                None)["body"])["status"] == "BASKET_CLAIMED"
