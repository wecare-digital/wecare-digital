"""The money-correctness invariants this graft exists to hold, as executable assertions.

Why one file rather than rows spread across the existing suites
---------------------------------------------------------------
Every assertion here is about a property that spans more than one module: "a payable modal always
has paid memory behind it" touches `website_checkout`, `order_keys` and `checkout_pricing`; "only
the verified Razorpay leg is recorded as the capture" touches `finalization` and the handler.
Filing each row under the module it happens to call first would scatter one invariant across
several files and make a regression look like several unrelated failures.

The fake is `coupon_fake_dynamo.FakeTable` throughout, deliberately: it evaluates `OR` and
parenthesised conditions, which every conditional claim in this change depends on.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import time
from decimal import Decimal

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(ROOT / "tests"))

from coupon_fake_dynamo import FakeClientError, FakeTable  # noqa: E402
from crm_fake_dynamo import FakeDynamo as CrmFakeDynamo  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import default_coupon  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce import payment_attempt  # noqa: E402
from lambda_utils.ecommerce import website_checkout  # noqa: E402

KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
CUSTOMER = "CUS_graft_001"
CART = "11111111-2222-3333-4444-555555555555"
COLLECTION_PAISE = 100000


#: "remove this attribute", distinct from `None`, which several of these rows need to STORE.
_ABSENT = object()


def _keys():
    """The commerce-keys table, whose partition attribute is `orderId` for every prefix."""
    return FakeTable(key_attr="orderId")


def _frozen(*, cart_id=CART, revision=1, line_quantity=1, collection_paise=COLLECTION_PAISE,
            extra_line_field=None, items=None):
    """A frozen snapshot payload in `_snapshot_payload`'s exact shape."""
    quote = cp.compute_quote(collection_paise)
    if items is None:
        line = {"lineItemId": "line-1", "quantity": line_quantity,
                "totalPrice": {"amount": "1000.00"}}
        if extra_line_field is not None:
            # A field this build does NOT enumerate, standing in for any term `basket_hash`
            # covers and `narrow_basket_hash` deliberately does not.
            line["physicalProperties"] = extra_line_field
        items = [line]
    payload = {
        "customer": CUSTOMER,
        "site": "site-1",
        "cart": {"id": cart_id, "revision": revision},
        "items": items,
        "address": {"city": "Kolkata"},
        "delivery": {"title": "Standard"},
        "components": quote.components(),
        "policyVersion": quote.policy_version,
    }
    return payload


# ── step 3: the three cart row families ────────────────────────────────────────

def test_the_cart_pointer_upsert_cannot_erase_a_paid_basket():
    """The single-slot pointer is upserted; the per-basket row is not reachable from that write.

    This is the iteration-5 hole in one assertion: paying basket B1 and then opening a different
    basket B2 on the same 30-day cart re-points `CARTPAYMENT#`, and the only surviving record that
    B1 was paid must be its own `CARTBASKET#` row.
    """
    table = _keys()
    b1, b2 = "hash_b1", "hash_b2"
    order_keys.record_cart_payment(table, customer_id=CUSTOMER, cart_id=CART,
                                   payment_attempt_id="A1", basket_hash=b1)
    order_keys.record_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                  basket_hash=b1, payment_attempt_id="A1")
    # A later, genuinely different basket takes the single slot.
    order_keys.record_cart_payment(table, customer_id=CUSTOMER, cart_id=CART,
                                   payment_attempt_id="A2", basket_hash=b2)
    order_keys.record_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                  basket_hash=b2, payment_attempt_id="A2")

    pointer = order_keys.resolve_cart_payment(table, customer_id=CUSTOMER, cart_id=CART)
    assert pointer["paymentAttemptId"] == "A2", "the pointer is last-writer-wins, by design"
    survived = order_keys.resolve_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                              basket_hash=b1)
    assert survived is not None and survived["paymentAttemptId"] == "A1", (
        "the paid memory for B1 must survive a later attempt on the same cart")


def test_the_narrow_paid_row_resolves_when_the_fine_one_cannot():
    """Keyed on two identities, so a `basket_hash` that moved is still refused by the narrow key."""
    table = _keys()
    order_keys.record_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                  basket_hash="fine_v1", payment_attempt_id="A1",
                                  narrow_basket_hash="narrow_stable")
    order_keys.record_cart_narrow_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                         narrow_hash="narrow_stable", payment_attempt_id="A1",
                                         basket_hash="fine_v1")
    # A non-enumerated term moved, so the fine identity composes a different key.
    assert order_keys.resolve_cart_basket(
        table, customer_id=CUSTOMER, cart_id=CART, basket_hash="fine_v2") is None
    found = order_keys.resolve_cart_narrow_basket(
        table, customer_id=CUSTOMER, cart_id=CART, narrow_hash="narrow_stable")
    assert found is not None and found["paymentAttemptId"] == "A1"


def test_a_recorded_basket_row_is_never_taken_over_by_a_stale_claim():
    """A RECORDED row cannot be claimed however old it is. Its failure mode is a second charge."""
    table = _keys()
    long_ago = int(time.time()) - 10 * 365 * 24 * 3600
    order_keys.record_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                  basket_hash="b1", payment_attempt_id="A_PAID", now=long_ago)
    won = order_keys.claim_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                       basket_hash="b1", payment_attempt_id="A_NEW")
    assert won is False, "a recorded row has an attempt behind it and is never stale"
    row = order_keys.resolve_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                         basket_hash="b1")
    assert row["paymentAttemptId"] == "A_PAID"


@pytest.mark.parametrize("prefix", ["basket", "narrow"])
def test_a_stale_create_claim_releases_after_the_create_horizon(prefix):
    """Both halves: inside the horizon the claim holds; past it a later click may take it."""
    table = _keys()
    now = int(time.time())
    claim = (order_keys.claim_cart_basket if prefix == "basket"
             else order_keys.claim_cart_narrow_basket)
    kwargs = ({"basket_hash": "b1"} if prefix == "basket" else {"narrow_hash": "n1"})

    assert claim(table, customer_id=CUSTOMER, cart_id=CART,
                 payment_attempt_id="A1", now=now, **kwargs) is True
    # Inside the horizon, with no CAS basis: the first claimer still holds it.
    assert claim(table, customer_id=CUSTOMER, cart_id=CART,
                 payment_attempt_id="A2", now=now + 10, **kwargs) is False
    # Past it, a dead claimer's slot is available again.
    assert claim(table, customer_id=CUSTOMER, cart_id=CART, payment_attempt_id="A3",
                 now=now + order_keys.CART_CREATE_CLAIM_STALE_SECONDS + 1,
                 **kwargs) is True


def test_a_claim_with_a_matching_cas_basis_repoints_a_failed_attempt():
    """The legitimate retry: the guard read A1 off the row, so A1 is the condition."""
    table = _keys()
    assert order_keys.claim_cart_basket(table, customer_id=CUSTOMER, cart_id=CART,
                                        basket_hash="b1", payment_attempt_id="A1") is True
    assert order_keys.claim_cart_basket(
        table, customer_id=CUSTOMER, cart_id=CART, basket_hash="b1",
        payment_attempt_id="A2", prior_payment_attempt_id="A1") is True
    assert order_keys.claim_cart_basket(
        table, customer_id=CUSTOMER, cart_id=CART, basket_hash="b1",
        payment_attempt_id="A3", prior_payment_attempt_id="A1") is False, (
        "the row moved, so the compare-and-swap must fail")


@pytest.mark.parametrize("builder,kwargs", [
    (order_keys.record_cart_basket, {"basket_hash": ""}),
    (order_keys.record_cart_narrow_basket, {"narrow_hash": ""}),
])
def test_an_empty_key_part_raises_rather_than_composing_a_colliding_key(builder, kwargs):
    with pytest.raises(ValueError):
        builder(_keys(), customer_id=CUSTOMER, cart_id=CART,
                payment_attempt_id="A1", **kwargs)


def test_a_read_failure_is_never_reported_as_absence():
    """Absence is the dangerous answer: the caller acts on it by creating a payable order."""
    class Raising:
        def get_item(self, **_):
            raise FakeClientError("ProvisionedThroughputExceededException")

    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.resolve_cart_basket(Raising(), customer_id=CUSTOMER, cart_id=CART,
                                       basket_hash="b1")
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.resolve_cart_narrow_basket(Raising(), customer_id=CUSTOMER,
                                              cart_id=CART, narrow_hash="n1")
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.resolve_cart_payment(Raising(), customer_id=CUSTOMER, cart_id=CART)


def test_a_throttled_claim_is_never_mistaken_for_a_free_slot():
    class Raising:
        def put_item(self, **_):
            raise FakeClientError("ThrottlingException")

    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.claim_cart_narrow_basket(Raising(), customer_id=CUSTOMER, cart_id=CART,
                                            narrow_hash="n1", payment_attempt_id="A1")


def test_no_cart_row_writer_ever_deletes():
    """The rows are evidence that money moved for a basket. No `DeleteItem`, and none granted."""
    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/order_keys.py"
              ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if "cart" not in node.name:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Attribute) and inner.attr == "delete_item"):
                offenders.append(node.name)
    assert offenders == [], f"a cart row writer calls delete_item: {offenders}"


def test_is_conditional_failure_is_public_and_classifies():
    assert "is_conditional_failure" in order_keys.__all__
    assert order_keys.is_conditional_failure(
        FakeClientError("ConditionalCheckFailedException")) is True
    assert order_keys.is_conditional_failure(FakeClientError("ThrottlingException")) is False
    assert order_keys.is_conditional_failure(RuntimeError("no response attribute")) is False
    # The private alias is kept for the six internal call sites.
    assert order_keys._is_conditional_failure is order_keys.is_conditional_failure


def test_resolve_checkout_request_key_reads_the_row_reserve_wrote():
    table = _keys()
    order_keys.reserve_checkout_request_key(
        table, customer_id=CUSTOMER, request_key="K1",
        intent_fingerprint="fp", payment_attempt_id="A1")
    row = order_keys.resolve_checkout_request_key(
        table, customer_id=CUSTOMER, request_key="K1")
    assert row is not None and row["paymentAttemptId"] == "A1"
    assert order_keys.resolve_checkout_request_key(
        table, customer_id=CUSTOMER, request_key="K_absent") is None


def test_every_new_cart_surface_is_exported():
    for name in ("CART_PAYMENT_PREFIX", "CART_PAYMENT_KIND", "CART_BASKET_PREFIX",
                 "CART_BASKET_KIND", "CART_NARROW_BASKET_PREFIX", "CART_NARROW_BASKET_KIND",
                 "resolve_cart_payment", "record_cart_payment", "resolve_cart_basket",
                 "record_cart_basket", "claim_cart_basket", "resolve_cart_narrow_basket",
                 "record_cart_narrow_basket", "claim_cart_narrow_basket",
                 "resolve_checkout_request_key"):
        assert name in order_keys.__all__, name


# ── step 4: the two basket identities ──────────────────────────────────────────

def test_the_basket_hash_ignores_only_the_revision():
    """Both halves. The negative row matters more: a hash that dropped too much refuses forever."""
    base = _frozen(revision=1)
    bumped = _frozen(revision=7)
    assert cp._stable_hash(base) != cp._stable_hash(bumped), (
        "anti-vacuity: the quote hash MUST move when the revision moves")
    assert cp.basket_hash(base) == cp.basket_hash(bumped), "the revision is the one term dropped"

    # Negative half: everything else still changes the identity.
    for different in (_frozen(line_quantity=2), _frozen(collection_paise=COLLECTION_PAISE + 100),
                      _frozen(cart_id="99999999-2222-3333-4444-555555555555")):
        assert cp.basket_hash(base) != cp.basket_hash(different)
    moved_address = _frozen()
    moved_address["address"] = {"city": "Delhi"}
    assert cp.basket_hash(base) != cp.basket_hash(moved_address), (
        "the address is part of the FINE identity; changing it changes what is paid")


def test_the_basket_hash_refuses_a_cartless_payload():
    with pytest.raises(cp.PricingError):
        cp.basket_hash({"items": []})
    with pytest.raises(cp.PricingError):
        cp.basket_hash("not a mapping")
    with pytest.raises(cp.PricingError):
        cp.basket_hash({"cart": {"id": ""}})


def test_the_narrow_basket_hash_covers_only_contract_checked_terms():
    base = _frozen()
    # POSITIVE half: a field nobody enumerated moved, and the narrow identity is unchanged.
    residue = _frozen(extra_line_field={"weight": 1.5 and "1.5"})
    assert cp.basket_hash(base) != cp.basket_hash(residue), (
        "anti-vacuity: the FINE identity must move, or this test proves nothing")
    assert cp.narrow_basket_hash(base) == cp.narrow_basket_hash(residue)
    moved_address = _frozen()
    moved_address["address"] = {"city": "Delhi"}
    assert cp.narrow_basket_hash(base) == cp.narrow_basket_hash(moved_address), (
        "the narrow identity deliberately ignores the address")

    # NEGATIVE half: every enumerated term still changes it.
    for different in (_frozen(line_quantity=2),
                      _frozen(collection_paise=COLLECTION_PAISE + 100),
                      _frozen(cart_id="99999999-2222-3333-4444-555555555555")):
        assert cp.narrow_basket_hash(base) != cp.narrow_basket_hash(different)


def test_the_narrow_basket_hash_ignores_line_order_but_not_line_identity():
    one = _frozen(items=[{"lineItemId": "a", "quantity": 1},
                         {"lineItemId": "b", "quantity": 2}])
    reordered = _frozen(items=[{"lineItemId": "b", "quantity": 2},
                               {"lineItemId": "a", "quantity": 1}])
    assert cp.narrow_basket_hash(one) == cp.narrow_basket_hash(reordered)
    requantified = _frozen(items=[{"lineItemId": "a", "quantity": 1},
                                  {"lineItemId": "b", "quantity": 3}])
    assert cp.narrow_basket_hash(one) != cp.narrow_basket_hash(requantified)


@pytest.mark.parametrize("items", [None, [], "not a list", [{"quantity": 1}], [42]])
def test_the_narrow_basket_hash_answers_empty_when_it_cannot_name_the_lines(items):
    payload = _frozen()
    payload["items"] = items
    assert cp.narrow_basket_hash(payload) == "", (
        "an empty narrow hash means 'no narrow identity available', which the guard falls back on")


def test_both_identities_survive_a_dynamodb_round_trip():
    """Ints come back as integral `Decimal`s. `_canonical` folds them, so the hashes must match."""
    payload = _frozen()
    round_tripped = json.loads(json.dumps(payload))

    def decimalise(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, dict):
            return {key: decimalise(inner) for key, inner in value.items()}
        if isinstance(value, list):
            return [decimalise(inner) for inner in value]
        return value

    stored = decimalise(round_tripped)
    assert cp.basket_hash(payload) == cp.basket_hash(stored)
    assert cp.narrow_basket_hash(payload) == cp.narrow_basket_hash(stored)


def test_the_existing_snapshot_hash_is_unchanged_by_the_additions():
    """`_snapshot_payload` and `build_snapshot` must be byte-identical in behaviour."""
    quote = cp.compute_quote(COLLECTION_PAISE)
    snapshot = cp.build_snapshot(
        customer_id=CUSTOMER, cart_id=CART, cart_revision=1, quote=quote,
        created_at=1_700_000_000, ttl_seconds=900, items=[{"lineItemId": "line-1",
                                                           "quantity": 1}])
    assert snapshot.snapshot_hash == cp._stable_hash(snapshot.frozen_data)
    # Exactly the documented terms, and `_frozen` mirrors them: a new term moves every stored hash.
    assert set(snapshot.frozen_data) == {"customer", "site", "cart", "items", "address",
                                         "delivery", "components", "policyVersion"}
    assert set(snapshot.frozen_data) == set(_frozen())


# ══ GRAFT 1a — the double-charge guard, driven through the real handler ═════════
#
# Every row below calls `_website_prepare` through `handler.handler`, not `prepare_checkout`
# directly. A test that calls the guard itself cannot detect that its only production caller
# never reaches it, which is the failure mode this whole section exists to rule out.

import importlib.util  # noqa: E402

HANDLER_PATH = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CART_TABLE = "stack-wecare-digital-CartTable"
PRODUCTS_TABLE = "stack-wecare-digital-ProductsTable"
PHONE = "+919330994400"
#: AWS-native single-unit collection: the product price (native shipping is FREE by default). A
#: PRODUCT order carries the always-on Delight goodwill discount (0.5% up to ₹100), applied to the
#: collection SERVER-SIDE before the convenience fee and GST, so money assertions derive the
#: payable through `compute_quote(NATIVE_PAYABLE_COLLECTION_PAISE)` — the discounted collection,
#: computed the same way the handler does.
NATIVE_COLLECTION_PAISE = 2499900
NATIVE_PAYABLE_COLLECTION_PAISE = (
    NATIVE_COLLECTION_PAISE - default_coupon.delight_paise(NATIVE_COLLECTION_PAISE)
)
OWNED_ADDRESS = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
                 "state": "West Bengal", "postalCode": "700001"}

#: A PUBLIC Razorpay key id for the stub, ASSEMBLED AT RUNTIME so this file contains no
#: issuer-shaped literal. `scripts/block_inline_secrets.py` refuses an `rzp_live_` token on a
#: command line and `scripts/scan_repo_secrets.py` must keep reporting real values, so a fixture
#: that merely LOOKS like a credential is worth avoiding even when it is not one. Only the public
#: key id is ever publishable; no `key_secret` appears anywhere in this file, and a test below
#: asserts that no response or log can carry one.
FIXTURE_PUBLIC_KEY_ID = "rzp_" + "live_" + "FIXTUREPUBLICID"
#: A sentinel standing in for the secret half, used ONLY to assert it never leaves the module
#: that reads it. It is not issuer-shaped and is not a credential.
FIXTURE_SECRET_SENTINEL = "SECRET-HALF-MUST-NEVER-APPEAR"


#: The ProductsTable product and variant every rig basket names.
PRODUCT_ID = "00d4c72b-f694-441a-a192-e16f4b192440"
VARIANT_ID = "2d072962-37c0-4821-9c02-2cc223448711"


def _native_product_row():
    """ProductsTable item the native engine prices from, so `line_items()` resolves to one native
    cart line. Priced at the native single-unit collection (free shipping)."""
    return {"id": PRODUCT_ID, "status": "active",
            "variants": [{"sku": VARIANT_ID,
                          "priceMinor": NATIVE_COLLECTION_PAISE, "inventory": 50}]}


NATIVE_PRODUCT_ROW = _native_product_row()


class _Identity:
    def __init__(self, customer_id=CUSTOMER, phone=PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-graft"

    def owns(self, value):
        return bool(value) and value == self.customer_id


class _MultiTable:
    """One `boto3.resource('dynamodb')` stand-in over several `coupon_fake_dynamo.FakeTable`s.

    `coupon_fake_dynamo` is the fake used here rather than `crm_fake_dynamo` because every
    conditional claim in this change is a parenthesised `OR`, and a fake that cannot evaluate one
    cannot exercise the claim.
    """

    def __init__(self, keys):
        self.tables = {name: FakeTable(key_attr=key) for name, key in keys.items()}
        # The Contacts table is the ONE table reached with a boto3 `Key('phone').eq(...)`
        # condition object rather than an expression string, which `coupon_fake_dynamo.query`
        # does not parse. `crm_fake_dynamo` reads that object's own attributes, so the profile
        # lookup gets the fake that understands it while every conditional claim keeps the fake
        # that understands a parenthesised OR.
        self._crm = CrmFakeDynamo(keys={CONTACTS_TABLE: keys[CONTACTS_TABLE]},
                                  indexes={CONTACTS_TABLE: {"phone-index": ("phone", None)}})
        self.tables[CONTACTS_TABLE] = self._crm.Table(CONTACTS_TABLE)

    def Table(self, name):  # noqa: N802 - boto3's own spelling
        if name not in self.tables:
            raise AssertionError(f"the handler reached an unprovisioned table {name!r}")
        return self.tables[name]

    def rows(self, name):
        return [dict(row) for row in self.tables[name].rows.values()]

    def keys_with_prefix(self, prefix):
        return [key for key in self.tables[KEYS_TABLE].rows if str(key).startswith(prefix)]

    def count_prefix(self, prefix):
        return len(self.keys_with_prefix(prefix))


class _Rig:
    """A loaded handler module plus its fakes, with the Razorpay client fully stubbed."""

    def __init__(self, monkeypatch, *, initiation_enabled=True, keys_table=None):
        monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS_TABLE)
        monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
        monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
        monkeypatch.setenv("ORDERS_TABLE", ORDERS_TABLE)
        monkeypatch.setenv("APP_ENV", "development")
        # AWS-NATIVE is the only supply path: the website prepare prices from ProductsTable via
        # native_checkout.
        monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
        monkeypatch.setenv("CART_TABLE", CART_TABLE)
        monkeypatch.setenv("PRODUCTS_TABLE", PRODUCTS_TABLE)
        monkeypatch.delenv("CHECKOUT_INITIATION_ENABLED", raising=False)

        spec = importlib.util.spec_from_file_location(
            "graft_handler_under_test", HANDLER_PATH)
        self.h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.h)

        self.db = _MultiTable({ATTEMPTS_TABLE: "paymentAttemptId", KEYS_TABLE: "orderId",
                               CONTACTS_TABLE: "id", ORDERS_TABLE: "orderId",
                               CART_TABLE: "cartId", PRODUCTS_TABLE: "id"})
        if keys_table is not None:
            self.db.tables[KEYS_TABLE] = keys_table
        self.creates = []
        self.identity = _Identity()
        self.quantity = 1
        self.mp = monkeypatch

        monkeypatch.setattr(self.h, "_dynamodb", self.db)
        monkeypatch.setattr(self.h, "INITIATION_ENABLED", initiation_enabled)
        # The native supply engine prices from ProductsTable. Stub the reader to the fixture
        # product/variant, priced at the native single-unit collection (free shipping).
        monkeypatch.setattr(self.h, "_native_product_reader",
                            lambda: (lambda pid: dict(NATIVE_PRODUCT_ROW)))
        monkeypatch.setattr(self.h, "LOAD_OWNED_ADDRESS",
                            lambda customer_id: dict(OWNED_ADDRESS))
        monkeypatch.setattr(self.h.customer_auth, "require_customer",
                            lambda event: (self.identity, None))
        monkeypatch.setattr(self.h.razorpay_orders, "create_order", self._create_order)
        monkeypatch.setattr(self.h.razorpay_orders, "find_order_by_receipt",
                            lambda receipt: None)
        monkeypatch.setattr(self.h.razorpay_orders, "account_mode", lambda key_id: "live")
        monkeypatch.setattr(self.h, "_lambda_client", self._no_lambda)
        self._profile()

    # -- stubs -----------------------------------------------------------------
    def _no_lambda(self):
        raise AssertionError("the website prepare path must make no Lambda invoke")

    def _create_order(self, *, amount_paise, receipt, notes):
        self.creates.append({"amount_paise": amount_paise, "receipt": receipt,
                             "notes": dict(notes)})
        return {"id": f"order_GRAFT_{len(self.creates)}", "amount": amount_paise,
                "currency": "INR", "status": "created", "receipt": receipt,
                "key_id": FIXTURE_PUBLIC_KEY_ID}

    def _profile(self):
        self.db.Table(CONTACTS_TABLE).put_item(Item={
            "id": "contact-1", "contactId": "contact-1", "phone": PHONE,
            "email": "asha@example.com", "name": "Asha Sen",
            "checkoutCustomerId": CUSTOMER, "emailVerifiedAt": 1, "deletedAt": None})

    # -- driving ---------------------------------------------------------------
    def line_items(self):
        return [{"catalogReference": {
            "catalogItemId": PRODUCT_ID, "options": {"variantId": VARIANT_ID}},
            "quantity": self.quantity}]

    def set_quantity(self, units):
        """Change the basket the browser sends. ProductsTable prices it on the next prepare, so
        the quantity is the guard's subject and nothing else moves."""
        self.quantity = units

    def prepare(self, request_key):
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
            "headers": {"origin": "http://localhost:3000", "authorization": "Bearer t"},
            "body": json.dumps({"action": "prepare", "lineItems": self.line_items(),
                                "requestKey": request_key}),
        }
        response = self.h.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def verify(self, *, order_id, payment_id="pay_GRAFT_1", signature="sig"):
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
            "headers": {"origin": "http://localhost:3000", "authorization": "Bearer t"},
            "body": json.dumps({"action": "verify", "razorpay_order_id": order_id,
                                "razorpay_payment_id": payment_id,
                                "razorpay_signature": signature}),
        }
        response = self.h.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def status(self, attempt_id):
        """Drive `/checkout/status/`, which is the CLOSED-TAB finalization path.

        The same front door as `prepare` and `verify`: `_status` is reached through `handler`,
        so `require_customer` and `authorize_resource` run exactly as they do in production.
        """
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
            "headers": {"origin": "http://localhost:3000", "authorization": "Bearer t"},
            "body": json.dumps({"action": "status", "paymentAttemptId": attempt_id}),
        }
        response = self.h.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    # -- the provider stubs the verify/status legs need ------------------------
    def stub_capture(self, *, paid=True, payment_id="pay_GRAFT_1", amount_paise=0,
                     currency="INR", raises=None):
        """Stub the authenticated capture readback. No Razorpay SDK, no charge, ever.

        `raises` makes `verifier_for_event`'s closure raise, which is how the provider-unavailable
        arms are reached without a network call.
        """
        self.mp.setattr(self.h.razorpay_orders, "verify_checkout_signature",
                        lambda **kwargs: True)

        def verifier(**_kwargs):
            def _verify(_reference):
                if raises is not None:
                    raise raises
                return (paid, payment_id, amount_paise, currency)
            return _verify

        self.mp.setattr(self.h.razorpay_verify, "verifier_for_event", verifier)

    # -- post-prepare row surgery, for shapes the fixtures cannot produce -----
    def attempt_row(self):
        rows = self.db.rows(ATTEMPTS_TABLE)
        assert len(rows) == 1, f"expected exactly one attempt row, got {len(rows)}"
        return rows[0]

    def patch_attempt(self, **fields):
        table = self.db.Table(ATTEMPTS_TABLE)
        key = self.attempt_row()["paymentAttemptId"]
        row = dict(table.rows[key])
        for name, value in fields.items():
            if value is _ABSENT:
                row.pop(name, None)
            else:
                row[name] = value
        table.rows[key] = row
        return row

    def patch_row(self, prefix, **fields):
        """Patch the single commerce-keys row under `prefix`."""
        table = self.db.Table(KEYS_TABLE)
        matching = [key for key in table.rows if str(key).startswith(prefix)]
        assert len(matching) == 1, f"expected one {prefix} row, got {len(matching)}"
        row = dict(table.rows[matching[0]])
        for name, value in fields.items():
            if value is _ABSENT:
                row.pop(name, None)
            else:
                row[name] = value
        table.rows[matching[0]] = row
        return row

    def make_gift_card_split(self, redeem_paise):
        """Rewrite the stored rows into a SPLIT TENDER part-funded by a settled WECARE gift card,
        and return the Razorpay leg.

        WHY SURGERY AND NOT A FIXTURE. The website prepare takes no second tender, so the basket is
        priced for real, the gateway order is created for real, and only the STORED figures are
        rewritten afterwards into the row shape a settled card leaves:

          attempt.amountPaise            the FULL payable, unchanged (section 8 requires it)
          attempt.razorpayChargedPaise   the leg
          attempt.giftCardRedeemedPaise  the other tender (`finalization.OTHER_TENDER_PAISE_ATTRS`)
          attempt card-ladder evidence   required paise, transaction id, GC_REDEEMED rank
          PAYREF#.amountPaise            the leg (what `reconcile_payment` compares a capture to)
          GATEWAYORDER#.amountPaise      the leg (what `verify_callback` compares it to)

        Everything downstream of the capture -- the second-tender gate, `_tenders_reconcile` and
        the recorded verified capture -- then runs on real code reading real rows.
        """
        from lambda_utils.ecommerce import gift_card_settlement as gcs
        payable = int(self.attempt_row()["amountPaise"])
        leg = payable - int(redeem_paise)
        assert leg > 0, "a split tender still needs a positive Razorpay leg"
        self.patch_attempt(**{
            "razorpayChargedPaise": leg,
            gcs.REQUIRED_PAISE_ATTR: int(redeem_paise),
            gcs.REDEEMED_PAISE_ATTR: int(redeem_paise),
            gcs.TRANSACTION_ID_ATTR: "gc-txn-fixture",
            # The stage is derived from the RANK attribute and from nothing else.
            gcs.RANK_ATTRIBUTE: gcs.STAGE_RANK[gcs.GC_REDEEMED],
        })
        self.patch_row(order_keys.PAYMENT_REFERENCE_PREFIX, amountPaise=leg)
        self.patch_row(order_keys.GATEWAY_ORDER_PREFIX, amountPaise=leg)
        return leg

    def age_everything(self, seconds):
        """Push every timestamp on every row back by `seconds`, to cross a window deliberately."""
        for name in (KEYS_TABLE, ATTEMPTS_TABLE):
            table = self.db.Table(name)
            for key, row in list(table.rows.items()):
                row = dict(row)
                for field in ("recordedAt", "claimedAt", "paidAt", "updatedAt", "createdAt",
                              "reservedAt", "boundAt", "createClaimedAt"):
                    if field in row and isinstance(row[field], int):
                        row[field] = row[field] - seconds
                table.rows[key] = row

    def mark_paid(self):
        """Advance every stored attempt to PAYMENT_PAID, as a verified capture would."""
        table = self.db.Table(ATTEMPTS_TABLE)
        for key, row in list(table.rows.items()):
            row = dict(row)
            row["status"] = payment_attempt.PAYMENT_PAID
            row["attemptRank"] = payment_attempt.rank(payment_attempt.PAYMENT_PAID)
            row["paidAt"] = int(time.time())
            table.rows[key] = row

    def mark_failed(self):
        """Move every UNPAID attempt into a retryable state.

        `RETRYABLE_STATES` is where `may_create_order` and `is_in_flight` are BOTH false, which is
        the state that left the pre-graft guard with no window at all.
        """
        table = self.db.Table(ATTEMPTS_TABLE)
        for key, row in list(table.rows.items()):
            if row.get("status") == payment_attempt.PAYMENT_PAID:
                continue
            row = dict(row)
            row["status"] = payment_attempt.PAYMENT_FAILED
            row["attemptRank"] = payment_attempt.rank(payment_attempt.PAYMENT_FAILED)
            table.rows[key] = row


@pytest.fixture
def rig(monkeypatch):
    def build(**kwargs):
        return _Rig(monkeypatch, **kwargs)
    return build


def _rows_with(rig_instance, prefix):
    return [row for row in rig_instance.db.rows(KEYS_TABLE)
            if str(row["orderId"]).startswith(prefix)]


# ── (a) the revision-bumped two-prepare row ────────────────────────────────────

def test_a_revision_bump_does_not_unblock_a_paid_basket(rig):
    """The row the whole guard turns on: a paid basket must not become payable again.

    AWS-NATIVE ANTI-VACUITY. The native cart id is a DETERMINISTIC sha256 of the reviewed basket,
    so two prepares of the same basket produce the SAME snapshot hash and the SAME basket identity
    by design. That makes the guard-keyed-on-basket the ONLY thing that can refuse the second
    prepare (a guard keyed on a per-prepare quote hash could not, because the hashes are equal) —
    which assertions 2-3 pin.
    """
    r = rig()
    code_1, body_1 = r.prepare("K1")
    assert code_1 == 200 and body_1["status"] == "CHECKOUT_OPTIONS_READY"
    assert len(r.creates) == 1

    paid_attempt = r.db.rows(ATTEMPTS_TABLE)[0]["paymentAttemptId"]
    first_hash = _rows_with(r, order_keys.REQUEST_KEY_PREFIX)[0]["snapshotHash"]
    r.mark_paid()

    pointer = _rows_with(r, order_keys.CART_PAYMENT_PREFIX)[0]
    basket_row = _rows_with(r, order_keys.CART_BASKET_PREFIX)[0]

    code_2, body_2 = r.prepare("K2_fresh")

    # 1. The native basket identity is STABLE across prepares and matches the paid pointer, so the
    #    guard keys on it (not on a per-prepare quote hash, which is identical here by design).
    second_snapshot = r.h._website_snapshot(
        r.identity, r.line_items(), int(time.time()))
    assert second_snapshot.snapshot_hash == first_hash, (
        "native cart identity is deterministic, so the two prepares of one basket must hash equal")
    assert cp.basket_hash(second_snapshot.frozen_data) == pointer["basketHash"]
    assert pointer["basketHash"] == basket_row["basketHash"]
    # 3. The second prepare is refused, naming the PAID attempt.
    assert code_2 == 409
    assert body_2["status"] == website_checkout.CHECKOUT_AMBIGUOUS
    assert body_2["reason"] == website_checkout.CART_ALREADY_PAID
    assert body_2["paymentAttemptId"] == paid_attempt
    assert "options" not in body_2
    # 4. Exactly one provider create across the whole run.
    assert len(r.creates) == 1
    # 5. Exactly one row of each prefix, and NO second request key: step 2a sits above step 3, so
    #    a refusal writes nothing at all.
    assert r.db.count_prefix(order_keys.CART_PAYMENT_PREFIX) == 1
    assert r.db.count_prefix(order_keys.CART_BASKET_PREFIX) == 1
    assert r.db.count_prefix(order_keys.CART_NARROW_BASKET_PREFIX) == 1
    assert r.db.count_prefix(order_keys.GATEWAY_ORDER_PREFIX) == 1
    assert r.db.count_prefix(order_keys.PAYMENT_REFERENCE_PREFIX) == 1
    assert r.db.count_prefix(order_keys.REQUEST_KEY_PREFIX) == 1, (
        "a step-2a refusal must write NOTHING AT ALL, including its own request key")


# ── (b) the pointer-overwrite durability row ───────────────────────────────────

def test_a_paid_basket_survives_a_pointer_overwrite(rig):
    """Four stages, and stage (b) must be ALLOWED or the guard refuses legitimate purchases.

    (a) pay basket B1.  (b) past the window, a DIFFERENT basket B2 is allowed and upserts the
    single-slot pointer, destroying the pointer's record that B1 was paid.  (c) B2 is abandoned
    into a retryable state, where `may_create_order` and `is_in_flight` are both false.
    (d) re-present the unedited B1: its deterministic identity still names the paid attempt
    through the per-basket rows, so it is refused even though the live pointer names B2.

    The case where `basket_hash` moves and `narrow_basket_hash` does not -- the reason the narrow
    row exists -- is pinned at the row level by
    `test_the_narrow_paid_row_resolves_when_the_fine_one_cannot`.
    """
    r = rig()

    # (a) B1 is paid.
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_paid()
    b1_narrow = _rows_with(r, order_keys.CART_NARROW_BASKET_PREFIX)[0]
    b1_fine = b1_narrow["basketHash"]
    assert b1_fine, "the fixture must have produced a fine identity to begin with"
    b1_snapshot = r.h._website_snapshot(r.identity, r.line_items(), int(time.time()))

    # (b) Past the in-flight window a genuinely different basket (B2) is allowed — it overwrites
    #     the single-slot CART_PAYMENT pointer, which is the condition that could unblock B1.
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    r.set_quantity(2)
    code_b, body_b = r.prepare("K2")
    assert code_b == 200 and body_b["status"] == "CHECKOUT_OPTIONS_READY", (
        "a genuinely different basket past the window is the legitimate repeat purchase and must "
        "be ALLOWED; refusing it is the over-block this guard must not have")
    assert len(r.creates) == 2
    # B2's identity genuinely differs from B1's (anti-vacuity: the quantity change moved it).
    assert cp.narrow_basket_hash(
        r.h._website_snapshot(r.identity, r.line_items(), int(time.time())).frozen_data
    ) != b1_narrow["narrowBasketHash"]

    # (c) B2 is abandoned.
    r.mark_failed()

    # (d) Re-present the UNEDITED B1. Its deterministic identity is unchanged and still names the
    #     paid attempt, even though the live payment pointer now points at B2's row.
    r.set_quantity(1)
    presented = r.h._website_snapshot(
        r.identity, r.line_items(), int(time.time()))
    assert cp.narrow_basket_hash(presented.frozen_data) == b1_narrow["narrowBasketHash"]
    assert cp.basket_hash(presented.frozen_data) == b1_fine

    code_d, body_d = r.prepare("K3_fresh")
    # (d1) The paid-basket guard refuses the re-presented B1, naming CART_ALREADY_PAID.
    assert code_d == 409, body_d
    assert body_d["reason"] == website_checkout.CART_ALREADY_PAID
    assert "options" not in body_d
    # (d2) Exactly two creates across the whole run: B1's and B2's, never a third.
    assert len(r.creates) == 2, (
        f"a third provider create means B1 was charged twice: "
        f"{[c['receipt'] for c in r.creates]}")


# ── (c) the NEW resumed-request-key-after-a-lost-pointer-write row ─────────────

class _PointerHostileTable(FakeTable):
    """A keys table that refuses ONE named cart-row write, once, and otherwise behaves.

    Parametrised over all three writers, because `_record_cart_pointer` treats every one of them
    as must-succeed and a divergence between them would be invisible.
    """

    def __init__(self, refuse_prefix):
        super().__init__(key_attr="orderId")
        self.refuse_prefix = refuse_prefix
        self.armed = True

    def put_item(self, Item=None, **kwargs):
        item = Item or {}
        key = str(item.get("orderId") or "")
        # Only a RECORD write, never a step-4b CLAIM: a claim carries `claimStage` and no
        # `recordedAt`, and refusing one raises OrderIdentityUnavailable out of step 4b as a 503.
        # That is correct behaviour and a different row; it is not the resume exit this exercises.
        if self.armed and key.startswith(self.refuse_prefix) and "recordedAt" in item:
            self.armed = False
            raise FakeClientError("ProvisionedThroughputExceededException")
        return super().put_item(Item=Item, **kwargs)


@pytest.mark.parametrize("refuse_prefix", [
    order_keys.CART_PAYMENT_PREFIX,
    order_keys.CART_BASKET_PREFIX,
    order_keys.CART_NARROW_BASKET_PREFIX,
])
def test_a_resumed_request_key_after_a_lost_pointer_write_still_guards_the_basket(
        rig, refuse_prefix):
    """The iteration-7 hole, closed: a payable modal reached through the RESUME exit.

    Prepare #1 loses one cart-row write, so it answers CART_POINTER_SAVE_FAILED with NO options
    and ZERO cart rows -- while `_link_request_key_to_order` has ALREADY written `gatewayOrderId`
    onto the REQUESTKEY# row. That is the anti-vacuity anchor: without it, prepare #2 would not
    reach `_resume_lost_request_key`'s `gatewayOrderId` branch at all and the row would prove
    nothing.

    Prepare #2 presents the SAME key against a healthy table, takes that branch, and must write
    all three rows before it may hand back a modal. Prepare #3, with a FRESH key after the
    payment, must then be refused 409 CART_ALREADY_PAID -- which it can only be because #2 wrote
    them.

    The native quote is deterministic per basket, so prepare #2 presents prepare #1's
    `intent_fingerprint` and the resume is reachable.
    """
    hostile = _PointerHostileTable(refuse_prefix)
    r = rig(keys_table=hostile)

    # Prepare #1: one cart-row write is lost.
    code_1, body_1 = r.prepare("K")
    assert code_1 == 200, "CART_POINTER_SAVE_FAILED is uncertainty, not refusal"
    assert body_1["status"] == website_checkout.CHECKOUT_AMBIGUOUS
    assert body_1["reason"] == website_checkout.CART_POINTER_SAVE_FAILED
    assert "options" not in body_1, "no modal may open with the basket unguarded"
    assert len(r.creates) == 1
    # ANTI-VACUITY ANCHOR: a resumable request key exists, with no cart rows behind it.
    request_rows = _rows_with(r, order_keys.REQUEST_KEY_PREFIX)
    assert len(request_rows) == 1
    assert request_rows[0].get("gatewayOrderId"), (
        "without a stored gatewayOrderId prepare #2 cannot reach the resume branch, so this row "
        "would not exercise the exit it exists for")
    # No RECORDED row exists for the refused prefix. The distinction from "no row" is
    # load-bearing: step 4b's CLAIM has already written a `CARTNARROW#` row carrying `claimedAt`
    # and deliberately NO `recordedAt`, which is what puts it on the 120s create horizon instead
    # of the settling one. A paid-memory row is one with `recordedAt`.
    def _recorded(prefix):
        return [row for row in _rows_with(r, prefix) if row.get("recordedAt")]

    assert _recorded(refuse_prefix) == []
    if refuse_prefix == order_keys.CART_PAYMENT_PREFIX:
        # The fully non-vacuous parametrisation: the FIRST write failed, so none of the three
        # recorded rows exists and the basket has no paid memory at all.
        assert _recorded(order_keys.CART_BASKET_PREFIX) == []
        assert _recorded(order_keys.CART_NARROW_BASKET_PREFIX) == []

    # Prepare #2: the SAME key, healthy table. The resume exit must write the rows.
    code_2, body_2 = r.prepare("K")
    assert code_2 == 200
    assert body_2["status"] == "CHECKOUT_OPTIONS_READY", body_2
    assert len(r.creates) == 1, "the resume must not create a second payable order"
    assert r.db.count_prefix(order_keys.CART_PAYMENT_PREFIX) == 1
    assert r.db.count_prefix(order_keys.CART_BASKET_PREFIX) == 1
    assert r.db.count_prefix(order_keys.CART_NARROW_BASKET_PREFIX) == 1
    stored_binding = _rows_with(r, order_keys.GATEWAY_ORDER_PREFIX)[0]
    pointer = _rows_with(r, order_keys.CART_PAYMENT_PREFIX)[0]
    assert pointer["paymentAttemptId"] == stored_binding["paymentAttemptId"], (
        "the pointer must name the attempt that OWNS the payable order, not this invocation's")

    # The payment lands.
    r.mark_paid()

    # Prepare #3: a FRESH key for the same basket must be refused.
    code_3, body_3 = r.prepare("K_fresh")
    assert code_3 == 409, body_3
    assert body_3["reason"] == website_checkout.CART_ALREADY_PAID
    assert len(r.creates) == 1, (
        "a second provider create here is the double charge this whole graft exists to prevent")


@pytest.mark.parametrize("refuse_prefix", [
    order_keys.CART_PAYMENT_PREFIX,
    order_keys.CART_BASKET_PREFIX,
    order_keys.CART_NARROW_BASKET_PREFIX,
])
def test_a_prepare_onto_an_already_bound_order_still_writes_the_pointer(rig, refuse_prefix):
    """The behavioural half of the module-wide invariant, over the resume exit x all three writers.

    Whichever of the three writes fails, the answer is the same: CART_POINTER_SAVE_FAILED, 200,
    and NO options. A divergence between the three would mean one of them was best-effort after
    all.
    """
    hostile = _PointerHostileTable(refuse_prefix)
    r = rig(keys_table=hostile)
    assert r.prepare("K")[1]["reason"] == website_checkout.CART_POINTER_SAVE_FAILED
    # Re-arm against the resume exit specifically, so the SECOND prepare is the one that fails.
    hostile.armed = True
    code, body = r.prepare("K")
    assert code == 200
    assert body["reason"] == website_checkout.CART_POINTER_SAVE_FAILED
    assert "options" not in body
    assert len(r.creates) == 1


# ── per-defect regression rows ─────────────────────────────────────────────────

def test_a_fresh_request_key_cannot_open_a_second_order_for_one_cart(rig):
    """The headline defect: the reservation is keyed on the request key, the guard on the basket."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    code, body = r.prepare("K2_fresh")
    assert code == 409
    assert body["reason"] == website_checkout.CART_PAYMENT_IN_FLIGHT
    assert len(r.creates) == 1


def test_a_paid_cart_with_an_edited_basket_past_the_window_is_not_refused(rig):
    """Tier 2's window, from the permissive side. The repeat purchase must survive."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_paid()
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    r.set_quantity(3)
    code, body = r.prepare("K2_fresh")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body
    assert len(r.creates) == 2


def test_a_paid_basket_with_one_more_unit_past_the_window_is_not_refused(rig):
    """The fix from the permissive side: a real edit past the settling interval is payable."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_paid()
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    r.set_quantity(2)
    assert r.prepare("K2_fresh")[0] == 200
    assert len(r.creates) == 2


def test_a_paid_basket_reordered_to_a_different_address_is_refused_past_the_window(rig,
                                                                                  monkeypatch):
    """The designed COST, pinned so it is a decision rather than a surprise.

    `narrow_basket_hash` ignores the address, so an address-only re-order of a paid basket
    matches narrowly FOREVER and is refused with no self-release. The two cases it cannot
    distinguish -- "a term the narrow identity does not name moved" and "the shopper re-ordered
    the same items to a different address" -- are observationally identical, and only one of them
    may pass.
    """
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_paid()
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    # Same items, same tender, a different delivery address IN THE SAME STATE. The state matters:
    # an inter-state address flips `intra_state`, which changes the convenience-fee GST split,
    # which changes `quote.components()` -- and `components` IS a narrow term, so an inter-state
    # re-order hashes differently and is correctly ALLOWED. The cost documented here is the
    # intra-state case, where nothing the narrow identity names has moved.
    monkeypatch.setattr(r.h, "LOAD_OWNED_ADDRESS", lambda customer_id: {
        "addressLine1": "7 Park Street", "city": "Kolkata",
        "state": "West Bengal", "postalCode": "700016"})
    code, body = r.prepare("K2_fresh")
    assert code == 409, body
    assert body["reason"] == website_checkout.CART_ALREADY_PAID
    assert len(r.creates) == 1


def test_a_reload_in_the_paying_tab_is_refused_not_resumed(rig):
    """The paid arm sits ABOVE the same-request-key exemption, deliberately.

    `cart.tsx` never clears CHECKOUT_REQUEST_KEY, so the tab that just paid still holds its key.
    With the exemption first, a Proceed click would be handed a payable modal for a captured
    basket, and "no second charge" would rest entirely on Razorpay refusing a payment against an
    order already marked paid -- an external behaviour nothing here verifies.
    """
    r = rig()
    assert r.prepare("K")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_paid()
    code, body = r.prepare("K")
    assert code == 409, body
    assert body["reason"] == website_checkout.CART_ALREADY_PAID
    assert "options" not in body
    assert len(r.creates) == 1


def test_a_reload_on_an_unpaid_attempt_still_resumes(rig):
    """The other half, and the reason the exemption exists at all."""
    r = rig()
    first = r.prepare("K")[1]
    assert first["status"] == "CHECKOUT_OPTIONS_READY"
    code, body = r.prepare("K")
    assert code == 200, body
    assert body["status"] == "CHECKOUT_OPTIONS_READY"
    assert body["options"]["orderId"] == first["options"]["orderId"]
    assert len(r.creates) == 1


def test_a_same_key_prepare_on_an_unchanged_native_basket_is_an_idempotent_resume(rig):
    """AWS-native: a second prepare with the SAME request key on the SAME basket is a resume, not
    an intent change. The native cart id and the intent fingerprint are deterministic over the
    basket, so re-pressing with an unchanged cart resolves onto the one in-flight attempt and
    mints no second gateway order — 200 CHECKOUT_OPTIONS_READY."""
    r = rig()
    assert r.prepare("K")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    code, body = r.prepare("K")
    assert code == 200
    assert body["status"] == "CHECKOUT_OPTIONS_READY"
    # The one invariant that must hold either way: no second gateway order was minted.
    assert len(r.creates) == 1


def test_a_legitimate_retry_after_a_failed_attempt_still_wins_the_claim(rig):
    """Arm 0 passes a retryable attempt, so the CAS basis names it and the claim re-points."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    r.mark_failed()
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    code, body = r.prepare("K2_fresh")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body
    assert len(r.creates) == 2


def test_two_overlapping_prepares_on_one_basket_open_one_payable_order(rig):
    """The interleaved row: a `create_order` stub that re-enters prepare before returning.

    MEASURED, and it is not where the design predicted. Step 4b's claim is written BEFORE
    `create_order`, so by the time the inner prepare runs, a `CARTNARROW#` row already exists
    carrying `claimedAt`, the winner's `paymentAttemptId` and the winner's `requestKey` -- while
    the winner's ATTEMPT row does not exist yet, because that is written after the create returns.
    The inner prepare therefore presents a different request key, fails the resume exemption,
    finds a claim with no readable attempt, and is refused by arm 0's bounded create-horizon
    window -- at step 2a, before its own reservation.

    That is strictly better than being refused at step 4b: it writes nothing at all, and it names
    the holder's attempt, which comes to exist moments later and which `/checkout/status/` can
    then resolve. The step-4b loser path -- where the refusal deliberately names NO attempt,
    because the holder's may not exist -- is exercised directly by
    `test_a_held_basket_claim_refuses_without_naming_an_attempt`.

    What is asserted here is the invariant, not the arm: ONE create, ONE gateway order, ONE
    reference, ONE modal.
    """
    r = rig()
    inner = {}
    original = r._create_order

    def reentrant(*, amount_paise, receipt, notes):
        if not inner:
            inner["code"], inner["body"] = r.prepare("K2")
        return original(amount_paise=amount_paise, receipt=receipt, notes=notes)

    r.h.razorpay_orders.create_order = reentrant
    code_1, body_1 = r.prepare("K1")

    assert len(r.creates) == 1, (
        f"two payable gateway orders for one basket: {[c['receipt'] for c in r.creates]}")
    assert r.db.count_prefix(order_keys.GATEWAY_ORDER_PREFIX) == 1
    assert r.db.count_prefix(order_keys.PAYMENT_REFERENCE_PREFIX) == 1
    # Exactly one modal, and it is the winner's.
    assert code_1 == 200 and body_1["status"] == "CHECKOUT_OPTIONS_READY"
    assert inner["code"] == 409
    assert inner["body"]["status"] == website_checkout.CHECKOUT_AMBIGUOUS
    assert inner["body"]["reason"] == website_checkout.CART_PAYMENT_IN_FLIGHT
    assert "options" not in inner["body"]
    # The loser wrote NOTHING: it was excluded at step 2a, above its own reservation.
    assert r.db.count_prefix(order_keys.REQUEST_KEY_PREFIX) == 1, (
        "the overlapping prepare is refused before step 3, so only the winner's key exists")
    # ...and it names the attempt that holds the basket, not its own.
    assert inner["body"]["paymentAttemptId"] == body_1["paymentAttemptId"]


def test_the_gate_off_path_claims_nothing(rig):
    """Step 4b is AFTER the gate, so a dormant prepare writes no claim and blocks nothing."""
    r = rig(initiation_enabled=False)
    code, body = r.prepare("K1")
    assert code == 200
    assert body["status"] == website_checkout.PAYMENT_INITIATION_DISABLED
    assert r.creates == []
    for prefix in (order_keys.CART_PAYMENT_PREFIX, order_keys.CART_BASKET_PREFIX,
                   order_keys.CART_NARROW_BASKET_PREFIX, order_keys.PAYMENT_REFERENCE_PREFIX,
                   order_keys.GATEWAY_ORDER_PREFIX, order_keys.ORDER_NUMBER_PREFIX):
        assert r.db.count_prefix(prefix) == 0, prefix
    assert r.db.rows(ATTEMPTS_TABLE) == []
    # A second gate-off prepare is not blocked by the first.
    assert r.prepare("K2")[1]["status"] == website_checkout.PAYMENT_INITIATION_DISABLED


def test_the_gate_off_prepare_leaves_no_payable_residue(rig):
    """The same property as the absence of anything payable: one reservation row, nothing else."""
    r = rig(initiation_enabled=False)
    r.prepare("K1")
    assert r.db.rows(ORDERS_TABLE) == []
    request_rows = _rows_with(r, order_keys.REQUEST_KEY_PREFIX)
    assert len(request_rows) == 1, "the reservation is the ONLY row a dormant prepare writes"
    assert not request_rows[0].get("referenceId")
    assert not request_rows[0].get("gatewayOrderId")
    assert not request_rows[0].get("createClaimedAt")


def test_a_snapshot_with_no_frozen_payload_is_rejected_as_basket_identity_required():
    """A guard that could not run is a different fact from a quote that will not settle."""
    quote = cp.compute_quote(COLLECTION_PAISE)
    snapshot = cp.QuoteSnapshot(
        customer_id=CUSTOMER, cart_id=CART, cart_revision=1, created_at=1_700_000_000,
        expires_at=1_700_000_900, policy_version=quote.policy_version, quote=quote,
        snapshot_hash="deadbeef", frozen_data={})
    with pytest.raises(website_checkout.CheckoutRejected) as raised:
        website_checkout.prepare_checkout(
            customer_id=CUSTOMER, snapshot=snapshot,
            presented_snapshot_hash="deadbeef", request_key="K", now=1_700_000_100,
            keys_table=_keys(),
            create_order=lambda **_: pytest.fail("nothing may be created"),
            find_order_by_receipt=lambda _: None, account_mode_of=lambda _: "live",
            initiation_enabled=True)
    assert raised.value.reason == website_checkout.BASKET_IDENTITY_REQUIRED
    assert raised.value.reason != "AMOUNT_NOT_SETTLED"


@pytest.mark.parametrize("resolver", ["resolve_cart_basket", "resolve_cart_narrow_basket",
                                      "resolve_cart_payment"])
@pytest.mark.parametrize("initiation_enabled", [True, False],
                         ids=["gate_on", "gate_off"])
def test_a_guard_read_failure_is_a_503_and_never_a_pass(rig, monkeypatch, resolver,
                                                        initiation_enabled):
    """A throttle must never read as "no live payment": the caller acts on that by charging.

    PARAMETRISED OVER THE GATE, so the answer on the path that is LIVE TODAY is a decision
    rather than a side effect. Step 2a's three consistent reads run BEFORE the initiation gate --
    deliberately, because a guard that only runs when the gate is on is a guard with no history
    to resume onto -- so a DynamoDB throttle during a gate-off prepare now answers 503
    TEMPORARILY_UNAVAILABLE where the pre-graft code answered 200 PAYMENT_INITIATION_DISABLED.

    That is the fail-closed direction and it is the right one: "we could not check" must not be
    reported as "nothing is live". It is pinned here in both worlds so neither answer can drift
    unnoticed, and because the gate-off answer is the one a customer can actually reach.
    """
    r = rig(initiation_enabled=initiation_enabled)

    def raising(*_args, **_kwargs):
        raise order_keys.OrderIdentityUnavailable("simulated throttle")

    monkeypatch.setattr(r.h.website_checkout.order_keys, resolver, raising)
    code, body = r.prepare("K1")
    assert code == 503
    assert body["error"] == "TEMPORARILY_UNAVAILABLE"
    assert r.creates == []
    # Nothing was written on either path: the refusal is above step 3's reservation.
    assert r.db.count_prefix(order_keys.REQUEST_KEY_PREFIX) == 0
    assert r.db.rows(ATTEMPTS_TABLE) == []


def test_a_held_basket_claim_refuses_without_naming_an_attempt(rig, monkeypatch):
    """A lost claim carries NO attempt id: the holder's attempt may not exist yet."""
    r = rig()
    monkeypatch.setattr(r.h.website_checkout.order_keys, "claim_cart_narrow_basket",
                        lambda *a, **k: False)
    monkeypatch.setattr(r.h.website_checkout.order_keys, "claim_cart_basket",
                        lambda *a, **k: False)
    code, body = r.prepare("K1")
    assert code == 409
    assert body["reason"] == website_checkout.CART_PAYMENT_IN_FLIGHT
    assert not body.get("paymentAttemptId"), (
        "an unresolvable attempt id would point /checkout/status/ at nothing, which is worse "
        "than none")
    assert r.creates == [], "a lost claim must create nothing"
    assert r.db.count_prefix(order_keys.PAYMENT_REFERENCE_PREFIX) == 0, (
        "the claim is BEFORE the mint, so a loser leaves no orphan PAYREF# row")


def test_a_throttled_basket_claim_is_a_503(rig, monkeypatch):
    r = rig()

    def raising(*_a, **_k):
        raise order_keys.OrderIdentityUnavailable("simulated throttle")

    monkeypatch.setattr(r.h.website_checkout.order_keys, "claim_cart_narrow_basket", raising)
    code, body = r.prepare("K1")
    assert code == 503 and body["error"] == "TEMPORARILY_UNAVAILABLE"
    assert r.creates == []


def test_a_basket_row_naming_another_customers_attempt_does_not_block(rig):
    """The rows are indexes, not authorities."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    table = r.db.Table(ATTEMPTS_TABLE)
    for key, row in list(table.rows.items()):
        row = dict(row)
        row["customerId"] = "CUS_someone_else"
        table.rows[key] = row
    code, body = r.prepare("K2_fresh")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body


def test_a_dangling_basket_row_blocks_for_one_window_then_releases(rig):
    """Fail closed, but BOUNDED: blocking forever would brick a basket on an anomaly."""
    r = rig()
    assert r.prepare("K1")[1]["status"] == "CHECKOUT_OPTIONS_READY"
    # The attempt row vanishes; the cart rows remain. An anomaly, not a race.
    r.db.Table(ATTEMPTS_TABLE).rows.clear()
    assert r.prepare("K2_fresh")[0] == 409
    r.age_everything(website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS + 60)
    code, body = r.prepare("K3_fresh")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", (
        "a dangling row must release after one window rather than bricking the basket")


def test_the_in_flight_horizon_outlasts_every_quote_ttl():
    """The block outlasts the quote: one EQUAL to the website snapshot TTL would expire with it."""
    spec = importlib.util.spec_from_file_location("graft_ttl_handler", HANDLER_PATH)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    assert (website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS
            > handler.WEBSITE_SNAPSHOT_TTL_SECONDS)
    assert (website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS
            > website_checkout.CREATE_CLAIM_STALE_SECONDS)
    assert (website_checkout.CREATE_CLAIM_STALE_SECONDS
            == order_keys.CART_CREATE_CLAIM_STALE_SECONDS)



# ── the module-wide invariant, by AST ──────────────────────────────────────────

WEBSITE_CHECKOUT_SOURCE = (
    ROOT / "amplify/functions/shared/lambda_utils/ecommerce/website_checkout.py")


def _enclosing_function(tree, target):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if inner is target:
                    return node.name
    return "<module>"


def test_only_the_choke_point_can_emit_a_payable_modal():
    """An AST walk, not a text scan: the comments in that module contain the strings searched for.

    Three assertions, and together they make "every payable modal has paid memory behind it" a
    property of the CALL GRAPH rather than a list of exits somebody has to keep up to date. This
    row is RED on the pre-graft module, which has two construction sites and two
    `_browser_options` call sites.
    """
    tree = ast.parse(WEBSITE_CHECKOUT_SOURCE.read_text(encoding="utf-8"))

    # (1) Exactly ONE `PreparedCheckout(...)` carrying `options=` or the ready status.
    ready_sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "PreparedCheckout"):
            continue
        payable = any(keyword.arg == "options" for keyword in node.keywords)
        payable = payable or any(
            keyword.arg == "status"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "CHECKOUT_OPTIONS_READY"
            for keyword in node.keywords)
        if payable:
            ready_sites.append(_enclosing_function(tree, node))
    assert ready_sites == ["_emit_payable_modal"], (
        f"a payable PreparedCheckout is constructed in {ready_sites}; it may only be constructed "
        f"in _emit_payable_modal, which is what writes the three cart rows first")

    # (2) Exactly ONE `_browser_options` call site, in the same function.
    browser_sites = [_enclosing_function(tree, node) for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "_browser_options"]
    assert browser_sites == ["_emit_payable_modal"], (
        f"_browser_options is called from {browser_sites}; a second call site is a second way a "
        f"browser can receive payable options")

    # (3) The write precedes the construction, by line number, inside that one function.
    choke = [node for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name == "_emit_payable_modal"][0]
    writes = [node.lineno for node in ast.walk(choke)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "_record_cart_pointer"]
    constructions = [node.lineno for node in ast.walk(choke)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "_browser_options"]
    assert writes and constructions
    assert min(writes) < min(constructions), (
        "_record_cart_pointer must run BEFORE the options are built, or a failed write still "
        "yields a payable modal")


def test_the_browser_amount_and_the_attempt_amount_are_different_expressions():
    """The split, re-pinned here because the choke point moved it out of one function.

    `tests/test_gift_cards_iam_and_table.py`'s SEAM-G14 row asserts this by requiring
    `_browser_options` and `payment_attempt.build` to appear in the SAME function with different
    `amount_paise` expressions. The choke point deliberately separates them -- there is now
    exactly one `_browser_options` call site and it is not in the function that builds the attempt
    -- so that row's SCOPING no longer matches the structure. The PROPERTY is unchanged and is
    asserted here instead: the browser is shown the pay-now leg and the attempt records the full
    payable. That marked test is another workstream's and is left untouched.
    """
    tree = ast.parse(WEBSITE_CHECKOUT_SOURCE.read_text(encoding="utf-8"))
    binder = [node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "_bind_and_ready"][0]

    def _amounts(predicate):
        found = []
        for node in ast.walk(binder):
            if isinstance(node, ast.Call) and predicate(node.func):
                found += [ast.unparse(keyword.value) for keyword in node.keywords
                          if keyword.arg == "amount_paise"]
        return found

    built = set(_amounts(lambda f: isinstance(f, ast.Attribute) and f.attr == "build"))
    emitted = set(_amounts(lambda f: isinstance(f, ast.Name)
                           and f.id == "_emit_payable_modal"))
    assert built and emitted
    assert not (built & emitted), (
        f"the attempt and the modal are handed the same amount expression "
        f"{sorted(built & emitted)}, so the browser is shown a price that is not being charged")
    assert all("pay_now" in argument for argument in emitted), (
        f"the browser amount comes from {sorted(emitted)} rather than from the pay-now leg")
    assert all("full_amount" in argument for argument in built), (
        f"the attempt records {sorted(built)} rather than the full payable")


# ══ the protect-what-must-not-regress set ══════════════════════════════════════
#
# These bind the whole change rather than one graft. Every one of them is an assertion about a
# property that a future edit could remove without failing any other test.

#: Every Python file this build modifies. Enumerated rather than globbed, so adding a file to the
#: change means adding it here and having the gates below apply to it.
TOUCHED_PYTHON = (
    "amplify/functions/shared/lambda_utils/ecommerce/order_keys.py",
    "amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py",
    "amplify/functions/shared/lambda_utils/ecommerce/purchase_intent.py",
    "amplify/functions/shared/lambda_utils/ecommerce/website_checkout.py",
    "amplify/functions/shared/lambda_utils/ecommerce/finalization.py",
    "amplify/functions/ecommerce/checkout/handler.py",
    # Contribution as a product. `blog_contribution` carries the committed recognition set and a
    # re-based exception; `customer_cart` carries `abandon`.
    "amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py",
    "amplify/functions/shared/lambda_utils/ecommerce/customer_cart.py",
    # The provider-neutral cart contract: delivery option helpers + the exception vocabulary the
    # native path reuses. `available_delivery_options` converts an amount to paise, so the
    # no-float and no-PII gates below cover it.
    "amplify/functions/shared/lambda_utils/ecommerce/cart_contract.py",
)


def _touched_trees():
    for relative in TOUCHED_PYTHON:
        path = ROOT / relative
        yield relative, ast.parse(path.read_text(encoding="utf-8"))


def test_no_raw_captured_comparison_is_introduced():
    """The payment vocabulary gate, extended to the files this build touches.

    `tests/test_payment_vocabulary_at_decision_points.py` bans the raw literal `captured` at every
    decision point it knows about -- and its `CONSULTING_FILES` and `RAW_SCAN_ONLY_FILES` cover
    NONE of the files here, so keeping that suite green is necessary and not sufficient.

    AST, not text: the comments explaining the rule necessarily contain the forbidden literal, so
    a text scan makes the explanation indistinguishable from the offence.
    """
    offenders = []
    for relative, tree in _touched_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for operator, comparator in zip(node.ops, node.comparators):
                if not isinstance(operator, (ast.Eq, ast.NotEq)):
                    continue
                for side in (node.left, comparator):
                    if isinstance(side, ast.Constant) and side.value == "captured":
                        offenders.append(f"{relative}:{node.lineno}")
    assert offenders == [], (
        f"a raw 'captured' comparison was introduced at {offenders}; `captured` belongs "
        f"exclusively to the payment vocabulary, and `== 'captured'` is the comparison that "
        f"silently misses `paid`")


def test_the_vocabulary_gate_itself_is_unchanged():
    """A dependency marker: the module-level contract this build must not have moved."""
    spec = importlib.util.spec_from_file_location(
        "payment_vocabulary_gate", ROOT / "tests/test_payment_vocabulary_at_decision_points.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.FORBIDDEN_RAW == {"captured"}, (
        "banning `paid` too would fail on the CORRECT invoice-lifecycle comparisons; banning "
        "only `captured` catches the dangerous direction")


def test_no_pii_appears_in_any_log_expression():
    """An AST assertion rather than a review habit.

    Reducing a sensitive value to a bool or a ternary does not launder it -- CodeQL's
    `py/clear-text-logging-sensitive-data` failed this repo's build twice on exactly that shape --
    so the test is "no logging expression REFERENCES the name", not "no value reaches the output".
    """
    sensitive = ("email", "address", "pin", "phone", "prefill", "customer_name",
                 "addressLine", "postalCode")
    offenders = []
    for relative, tree in _touched_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "logger"):
                continue
            rendered = " ".join(ast.unparse(argument) for argument in node.args)
            rendered += " " + " ".join(ast.unparse(k.value) for k in node.keywords)
            for name in sensitive:
                if name in rendered:
                    offenders.append(f"{relative}:{node.lineno} mentions {name!r}")
    assert offenders == [], f"a logging expression references PII: {offenders}"


def test_every_logged_exception_is_logged_by_type_name():
    """`type(exc).__name__` only. An exception's text can echo request content."""
    offenders = []
    for relative, tree in _touched_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "logger"):
                continue
            rendered = ast.unparse(node)
            # The bound names this build uses for a caught exception.
            for bound in ("error", "exc", "lookup_error", "raised"):
                bare = f"({bound})" in rendered or f" {bound}," in rendered \
                    or f"{{{bound}}}" in rendered or f"%s\" % {bound}" in rendered
                typed = f"type({bound}).__name__" in rendered
                if bare and not typed:
                    offenders.append(f"{relative}:{node.lineno} logs {bound} directly")
    assert offenders == [], f"an exception is logged by value rather than by type: {offenders}"


def test_no_changed_file_reads_a_secret_value():
    """`get-secret-value` in any spelling, and `key_secret` anywhere, are both refusals.

    Only the PUBLIC key id is publishable, and it is read lazily at request time from
    `wecare/razorpay/api` by `integrations/razorpay_orders.py`, which this build does not touch.
    """
    for relative in TOUCHED_PYTHON:
        source = (ROOT / relative).read_text(encoding="utf-8")
        for forbidden in ("get-secret-value", "batch-get-secret-value", "key_secret"):
            assert forbidden not in source, f"{relative} mentions {forbidden!r}"


def test_an_unsigned_webhook_body_is_still_401():
    """The standing test of the property, as opposed to a byte-identity check.

    A byte-identity assertion over `amplify/functions/payments/` would be a permanent false alarm
    on the first unrelated change there, so it stays a per-commit review command
    (`git diff --numstat <merge-base>..HEAD -- amplify/functions/payments/` must be empty) and
    the PROPERTY is tested here.
    """
    handler_path = ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"
    spec = importlib.util.spec_from_file_location("razorpay_webhook_under_test", handler_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = module.handler(
        {"headers": {}, "body": json.dumps({"event": "payment.captured"}),
         "requestContext": {"http": {"method": "POST"}}}, None)
    assert int(response["statusCode"]) == 401, (
        "an unsigned webhook body must be refused; HMAC verification is the only thing standing "
        "between a forged capture and an order")


def test_website_prepare_makes_no_lambda_invoke(rig):
    """The readiness severance, pinned by behaviour rather than by a code change.

    Measured: `_website_prepare` never calls `_readiness()`, so the website leg has no dependency
    on the retired `/wa-business/payment-config/raw` Meta readback. `_create` and `_readiness()`
    are deliberately left alone -- the in-WhatsApp path is retained -- so the severance is a TEST,
    and this is it. The rig's `_lambda_client` raises on any call.
    """
    r = rig()
    code, body = r.prepare("K1")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body


def test_the_constants_match_the_modules_they_mirror():
    """Every literal that mirrors another module's constant, pinned pair by pair.

    Each of these is a cross-module literal rather than an import, and each has a reason: an
    import cycle between sibling `ecommerce` modules, or the handler's import-closure assertion.
    A divergence in any of them produces NO error -- only a silently disabled check.
    """
    from lambda_utils.ecommerce import gift_card_settlement
    from lambda_utils.integrations import razorpay_orders

    # The verified-capture attribute, declared as an obligation by the gift-card ladder and
    # written only by finalization.
    from lambda_utils.ecommerce import finalization
    assert (finalization.VERIFIED_CAPTURED_PAISE_ATTR
            == gift_card_settlement.RAZORPAY_VERIFIED_PAISE_ATTR)
    # The one other tender finalization reconciles, by the gift-card ladder's own name.
    assert finalization.OTHER_TENDER_PAISE_ATTRS == (gift_card_settlement.REDEEMED_PAISE_ATTR,)
    # The checkout mode the finalizer accepts.
    assert website_checkout.CHECKOUT_MODE_WEBSITE in finalization.ACCEPTED_CHECKOUT_MODES
    assert "AWS_NATIVE" in finalization.ACCEPTED_CHECKOUT_MODES
    # The receipt length both sides slice/compare on. A divergence produces no error, only a
    # correlation that silently stops matching.
    assert (order_keys.RAZORPAY_RECEIPT_MAX_LENGTH
            == razorpay_orders.RECEIPT_MAX_LENGTH)
    # The create horizon, shared by the request-key claim and the basket claim.
    assert (website_checkout.CREATE_CLAIM_STALE_SECONDS
            == order_keys.CART_CREATE_CLAIM_STALE_SECONDS)


def test_the_promoted_helpers_are_public_with_no_underscore_aliases():
    """`finalization` exposes them because the handler asks the same questions.

    No `_`-prefixed alias is kept, deliberately: on this tree there is no caller of the private
    names, so an alias would preserve a compatibility surface with zero consumers -- and reaching
    across modules for a `_`-prefixed function is how two readings of one question start to drift.
    """
    from lambda_utils.ecommerce import finalization
    for name in ("integer_paise", "other_tender_paise", "cart_id", "record_paid",
                 "accept_paid"):
        assert hasattr(finalization, name), name
    for alias in ("_integer_paise", "_cart_id", "_other_tender_paise"):
        assert not hasattr(finalization, alias), (
            f"{alias} preserves a private surface with no consumer on this tree")


# ══ the stubbed full-flow exercise — no real charge, no real SDK, no deploy ═════

def test_the_stubbed_browser_flow_yields_one_order(rig, monkeypatch):
    """cart -> profile -> address+method -> prepare -> modal -> verify-callback -> ONE order.

    The Razorpay SDK is not involved at all: `create_order`, `verify_checkout_signature` and the
    authenticated capture readback are stubbed, so no provider call and no charge is possible.
    `initiation_enabled` is injected as a module attribute rather than set in the environment --
    `CHECKOUT_INITIATION_ENABLED` stays absent, so this is not a flag enable.

    The modal payload is asserted as an ALLOW-LIST, so a new field cannot leak by omission.
    """
    r = rig()
    code, body = r.prepare("K_flow")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body

    options = body["options"]
    # 1. EXACTLY these keys. An allow-list, never a deny-list.
    assert set(options) == {"keyId", "orderId", "amountPaise", "currency", "prefill",
                            "paymentAttemptId"}
    # 2. Integer paise, and no float anywhere in the payload.
    assert isinstance(options["amountPaise"], int)
    assert not isinstance(options["amountPaise"], bool)

    def _no_floats(value, path="options"):
        if isinstance(value, bool):
            return
        if isinstance(value, float):
            raise AssertionError(f"a float reached the browser payload at {path}")
        if isinstance(value, dict):
            for key, inner in value.items():
                _no_floats(inner, f"{path}.{key}")
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                _no_floats(inner, f"{path}[{index}]")

    _no_floats(options)
    # 3. INR, compared explicitly and never inferred from the amount.
    assert options["currency"] == "INR"
    # 4. The PUBLIC key id, and nothing else from the credential.
    assert options["keyId"] == FIXTURE_PUBLIC_KEY_ID
    rendered = json.dumps(body)
    assert FIXTURE_SECRET_SENTINEL not in rendered
    assert "key_secret" not in rendered
    assert "keySecret" not in rendered
    # 5. The amount is the CALCULATOR total over the DISCOUNTED collection (Delight applied
    #    server-side), not the raw collection.
    expected = cp.compute_quote(NATIVE_PAYABLE_COLLECTION_PAISE).total_payable_paise
    assert options["amountPaise"] == expected
    assert options["amountPaise"] != NATIVE_COLLECTION_PAISE

    # ── the verify leg, with the signature and the capture readback both stubbed ──
    gateway_order_id = options["orderId"]
    monkeypatch.setattr(r.h.razorpay_orders, "verify_checkout_signature",
                        lambda **kwargs: True)
    monkeypatch.setattr(
        r.h.razorpay_verify, "verifier_for_event",
        lambda **kwargs: (lambda reference: (True, "pay_flow_1", expected, "INR")))

    code_v, body_v = r.verify(order_id=gateway_order_id, payment_id="pay_flow_1")
    assert code_v == 200, body_v
    assert body_v["status"] == "VERIFIED_PAID"

    # Exactly ONE of everything that represents an order.
    orders = r.db.rows(ORDERS_TABLE)
    assert len(orders) == 1, f"expected one order record, got {len(orders)}"
    assert r.db.count_prefix(order_keys.ORDER_NUMBER_PREFIX) == 1
    numbers = {str(row.get("orderNumber") or "") for row in orders
               if row.get("orderNumber")}
    assert len(numbers) == 1
    assert order_keys.is_current_public_order_number(next(iter(numbers)))
    attempt = r.db.rows(ATTEMPTS_TABLE)[0]
    assert attempt["status"] == payment_attempt.PAYMENT_PAID
    assert attempt[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == expected
    assert attempt["providerPaymentId"] == "pay_flow_1"
    # ...and no second order on a redelivered verify.
    code_again, _ = r.verify(order_id=gateway_order_id, payment_id="pay_flow_1")
    assert code_again == 200
    assert len(r.db.rows(ORDERS_TABLE)) == 1, "a replayed verify must converge on one order"
    assert r.db.count_prefix(order_keys.ORDER_NUMBER_PREFIX) == 1


def finalization_module():
    from lambda_utils.ecommerce import finalization
    return finalization


def test_no_response_or_log_can_carry_the_key_secret(rig, caplog):
    """The secret half must appear in no response body and in no captured log record."""
    import logging
    r = rig()
    with caplog.at_level(logging.DEBUG):
        _code, body = r.prepare("K_secret")
    rendered = json.dumps(body)
    for forbidden in (FIXTURE_SECRET_SENTINEL, "key_secret", "keySecret"):
        assert forbidden not in rendered
        for record in caplog.records:
            assert forbidden not in record.getMessage()
    # And no PII beyond the prefill the owner approved reaches a log line.
    for record in caplog.records:
        message = record.getMessage()
        assert "asha@example.com" not in message
        assert PHONE not in message
        assert "Asha Sen" not in message


# ══ steps 9 and 10: finalization, and the handler wiring that reaches it ════════
#
# Everything below drives `accept_paid` through `_website_verify` or `_status` and NEVER by
# calling it directly. The reason is the plan's, and it is the repository's own "correct and
# unconsulted" failure mode: a test that calls `accept_paid` itself cannot detect that its only
# production caller refuses to reach it, which is exactly the defect the split two-leg gate
# exists to avoid re-introducing.
#
# The Razorpay SDK is absent from all of it. `create_order`, `verify_checkout_signature` and the
# authenticated capture readback are stubs; no provider call and no charge is possible.

GATEWAY_ORDER_ID = "order_GRAFT_1"


def _paid_flow(r, *, request_key="K_final", redeem_paise=0, payment_id="pay_final_1"):
    """prepare -> (optional split surgery) -> stubbed capture. Returns `(leg, options)`.

    One helper so every row below starts from the SAME prepared state and differs only in the
    one thing it is about.
    """
    code, body = r.prepare(request_key)
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body
    options = body["options"]
    leg = int(options["amountPaise"])
    if redeem_paise:
        leg = r.make_gift_card_split(redeem_paise)
    r.stub_capture(payment_id=payment_id, amount_paise=leg)
    return leg, options


def _webhook_reconcile(r, *, payment_id="pay_webhook_1", amount_paise=0):
    """What the razorpay-webhook does, with its own verifier stubbed: claim and number an order.

    Deliberately does NOT touch the attempt row -- measured, the webhook references neither
    `payment_attempt` nor `finalization` -- so this leaves the exact closed-tab shape: a claim
    with a public number, and an attempt still PAYMENT_PENDING with no stored capture.
    """
    keys = r.h._keys_table()
    reference_id = r.creates[-1]["notes"]["referenceId"]
    assert reference_id, "the create carried no referenceId, so the webhook has nothing to resolve"
    return r.h.order_creation.reconcile_payment(
        table=keys, reference_id=reference_id,
        verify_payment=lambda _ref: (True, payment_id, amount_paise, "INR"),
        load_attempt=r.h._load_attempt_via(keys))


def _stage_of(r):
    attempt = r.attempt_row()
    return attempt.get("finalizationStage", ""), attempt.get("finalizationReason", "")


# ── the baseline: the wiring reaches finalization at all ───────────────────────

def test_a_website_attempt_can_be_finalized_at_all(rig):
    """A paid website attempt runs `accept_paid` to its terminal stage.

    The internal order record IS the authoritative artifact: after it commits and the tenders
    reconcile, `accept_paid` stages `ORDER_FINALIZED` on the attempt and mirrors it on the order.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_fin_1")

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert body["orderNumber"], "a finalized order must return its public number"

    # ONE internal order record, and the stage ladder ran to its native terminal.
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    stage, reason = _stage_of(r)
    assert (stage, reason) == ("ORDER_FINALIZED", ""), (stage, reason)
    assert r.db.rows(ORDERS_TABLE)[0]["finalizationStage"] == "ORDER_FINALIZED"
    # The attempt carries the provider's own confirmed figure, not a derived one.
    assert r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg


def test_the_verified_razorpay_leg_is_recorded_not_the_order_total(rig):
    """Under split tender the recorded verified capture is the provider's leg, never the total.

    `verified_captured_paise` is the Razorpay leg's own confirmed figure, and recording the full
    payable instead would over-report the capture. The anti-vacuity anchor is that the leg and
    the payable are DIFFERENT numbers; the evidence lives on the attempt row.
    """
    r = rig()
    redeem = 40000
    leg, options = _paid_flow(r, request_key="K_fin_2", redeem_paise=redeem)
    payable = int(r.attempt_row()["amountPaise"])
    assert leg != payable, "the fixture produced no split, so this row would prove nothing"

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body

    # The provider's confirmed capture is stored as SEAM-G13 evidence — the leg, not the payable.
    recorded = int(r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR])
    assert recorded == leg
    assert recorded != payable
    assert _stage_of(r)[0] == "ORDER_FINALIZED"


def test_a_one_paise_tender_disagreement_fails_closed(rig):
    """One paise is a mismatch. Exact integers, no tolerance, and the order is not finalized.

    The internal order record IS created -- it is evidence that money moved and must survive --
    but `_tenders_reconcile` refuses before the terminal stage, so the order rests at
    NEEDS_RECONCILIATION and never reaches ORDER_FINALIZED.
    """
    r = rig()
    redeem = 40000
    leg, options = _paid_flow(r, request_key="K_fin_3", redeem_paise=redeem)
    # The other tender now claims ONE PAISE MORE than the split actually was.
    from lambda_utils.ecommerce import gift_card_settlement
    r.patch_attempt(**{gift_card_settlement.REDEEMED_PAISE_ATTR: redeem + 1})

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body

    assert len(r.db.rows(ORDERS_TABLE)) == 1, "the paid evidence must still be recorded"
    assert _stage_of(r) == ("NEEDS_RECONCILIATION", "TENDER_SUM_MISMATCH")
    assert r.db.rows(ORDERS_TABLE)[0]["finalizationStage"] == "INTERNAL_ORDER_CREATED"


def test_an_ordinary_card_free_order_with_a_zero_leg_is_not_refused(rig):
    """The second-tender gate tests the VALUE and never the key.

    An ordinary website attempt carries no tender attribute at all, and tender evidence recorded
    as 0 -- a card noted before anything is debited -- is still not a second leg. A presence test
    would refuse such an order; it must finalize.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_fin_5")
    fin = finalization_module()
    assert not [name for name in fin.OTHER_TENDER_PAISE_ATTRS if name in r.attempt_row()], (
        "the website prepare takes no second tender, so it writes no tender attribute")
    r.patch_attempt(**{name: 0 for name in fin.OTHER_TENDER_PAISE_ATTRS})

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    assert _stage_of(r)[0] == "ORDER_FINALIZED"


def test_an_unreadable_tender_leg_is_refused(rig, caplog):
    """An amount we cannot read is not the same as no amount. Refused BEFORE `accept_paid`."""
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_fin_6")
    r.patch_attempt(**{finalization_module().OTHER_TENDER_PAISE_ATTRS[0]: "not-a-number"})

    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    # No order record at all: the gate is above `accept_paid`, so `record_paid` never ran.
    assert r.db.rows(ORDERS_TABLE) == []
    assert not r.attempt_row().get("finalizationStage")
    events = [json.loads(record.getMessage()).get("event")
              for record in caplog.records if record.getMessage().startswith("{")]
    assert "checkout_finalize_unreadable_tender" in events, events
    # The capture is still recorded, because that happens first and unconditionally.
    assert r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg


def test_an_unsettled_wecare_gift_card_is_refused(rig, caplog):
    """Leg A: the WECARE store card has its own ladder, and `accept_paid` consults none of it."""
    import logging
    from lambda_utils.ecommerce import gift_card_settlement
    r = rig()
    leg, options = _paid_flow(r, request_key="K_fin_7")
    # A required redemption with no evidence that it happened.
    r.patch_attempt(**{gift_card_settlement.REQUIRED_PAISE_ATTR: 30000})

    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert r.db.rows(ORDERS_TABLE) == []
    events = [json.loads(record.getMessage()).get("event")
              for record in caplog.records if record.getMessage().startswith("{")]
    assert "checkout_finalize_gift_card_unsettled" in events, events


def test_a_settled_wecare_gift_card_is_not_refused_by_the_ladder_gate(rig):
    """The other side of leg A: a card with its stage AND its transaction id passes the gate.

    It then meets `_tenders_reconcile`, which is a fact about money rather than about the ladder,
    so a settled card whose legs sum correctly finalizes and one whose legs do not fails closed
    there. Asserted as "not refused BY THE LADDER", which is what this gate decides.
    """
    from lambda_utils.ecommerce import gift_card_settlement
    r = rig()
    redeem = 30000
    leg, options = _paid_flow(r, request_key="K_fin_8")
    # A WECARE card, settled, funding part of the basket. `giftCardRedeemedPaise` is the tender
    # `OTHER_TENDER_PAISE_ATTRS` names, so the sum closes against the payable.
    r.patch_attempt(**{
        gift_card_settlement.REQUIRED_PAISE_ATTR: redeem,
        gift_card_settlement.REDEEMED_PAISE_ATTR: redeem,
        gift_card_settlement.TRANSACTION_ID_ATTR: "gc-txn-fixture",
        # The stage is derived from the RANK attribute and from nothing else, so the rank is what
        # a settled card actually carries on the row.
        gift_card_settlement.RANK_ATTRIBUTE:
            gift_card_settlement.STAGE_RANK[gift_card_settlement.GC_REDEEMED],
        "razorpayChargedPaise": leg - redeem,
    })
    r.patch_row(order_keys.PAYMENT_REFERENCE_PREFIX, amountPaise=leg - redeem)
    r.patch_row(order_keys.GATEWAY_ORDER_PREFIX, amountPaise=leg - redeem)
    r.stub_capture(payment_id="pay_final_1", amount_paise=leg - redeem)

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert len(r.db.rows(ORDERS_TABLE)) == 1, "a settled card must not be refused by the ladder gate"
    # The verified capture recorded is the Razorpay leg, not the payable and not the card's.
    assert int(r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR]) == leg - redeem
    assert _stage_of(r)[0] == "ORDER_FINALIZED"


# ── convergence, the loader, and the paths where identity is missing ───────────

def test_webhook_and_browser_return_converge_on_one_order(rig):
    """Two independent finalizers, one order. The webhook claims first; the browser adopts it.

    The webhook reconciles from `notes.referenceId` without touching the attempt row, so the
    browser's `reconcile_payment` meets an existing claim and returns ORDER_ALREADY_EXISTS. That
    is resolve-before-generate across two processes: the second arrival resolves onto the order
    that exists rather than minting a second one.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_fin_9", payment_id="pay_conv_1")
    webhook = _webhook_reconcile(r, payment_id="pay_conv_1", amount_paise=leg)
    assert webhook.outcome == r.h.order_creation.ORDER_CREATED, webhook.reason
    assert r.db.count_prefix(order_keys.ORDER_NUMBER_PREFIX) == 1
    # The webhook wrote no order RECORD and did not touch the attempt row.
    assert r.db.rows(ORDERS_TABLE) == []
    assert r.attempt_row()["status"] == payment_attempt.PAYMENT_PENDING

    r.stub_capture(payment_id="pay_conv_1", amount_paise=leg)
    code, body = r.verify(order_id=options["orderId"], payment_id="pay_conv_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert body["orderNumber"] == webhook.order_number, (
        "the browser must return the number the webhook already reserved, not a second one")
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    assert r.db.count_prefix(order_keys.ORDER_NUMBER_PREFIX) == 1


def test_the_reconcile_verifier_resolves_a_payref_reference(rig):
    """`_load_attempt_via` resolves BOTH identifier kinds onto the same six-field projection.

    One loader, two kinds, because `verify_callback` calls its verifier with the stored GATEWAY
    ORDER id while `reconcile_payment` calls its verifier with the REFERENCE. A loader that
    resolved only one of them would make every website payment end with a verified capture and
    no order record.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_1")
    keys = r.h._keys_table()
    reference_id = r.creates[-1]["notes"]["referenceId"]

    by_reference = r.h._load_attempt_via(keys)(reference_id)
    assert by_reference["paymentAttemptId"] == options["paymentAttemptId"]
    assert by_reference["amountPaise"] == leg
    assert by_reference["customerId"] == CUSTOMER
    assert by_reference["currency"] == "INR"
    assert by_reference["providerOrderId"] == options["orderId"]
    # Exactly the webhook's projection, no more.
    assert set(by_reference) == {"paymentAttemptId", "customerId", "amountPaise",
                                 "providerPaymentId", "providerOrderId", "currency"}

    by_gateway_order = r.h._load_attempt_via(keys)(options["orderId"])
    assert by_gateway_order == by_reference, (
        "the two identifier kinds must resolve onto the same stored authority")


def test_a_lost_provider_order_link_still_verifies(rig):
    """The one best-effort write on the path, and the server-stored fallback that replaces it.

    `_link_reference_to_provider_order` is deliberately best-effort, so the `PAYREF#` row can
    legitimately carry no `providerOrderId`. `verifier_for_event` raises unless the loaded row has
    one, so without the fallback a lost link would make the payment unverifiable.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_2")
    keys = r.h._keys_table()
    reference_id = r.creates[-1]["notes"]["referenceId"]
    # The best-effort link never landed.
    r.patch_row(order_keys.PAYMENT_REFERENCE_PREFIX, providerOrderId=_ABSENT)

    assert r.h._load_attempt_via(keys)(reference_id)["providerOrderId"] == "", (
        "the fixture still carries the link, so the fallback below is not what is being tested")
    recovered = r.h._load_attempt_via(
        keys, provider_order_id=options["orderId"])(reference_id)
    assert recovered["providerOrderId"] == options["orderId"]

    code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert len(r.db.rows(ORDERS_TABLE)) == 1


def test_a_binding_with_no_reference_still_verifies_and_alarms(rig, caplog):
    """A pre-graft binding carries no reference. The capture is still recorded; the order alarms.

    Deliberately NOT a 503 and not a failure verdict: the money moved, the webhook reconciles
    from `notes.referenceId` independently, and telling a payer the payment failed after it
    succeeded is the one answer that cannot be taken back.
    """
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_3")
    r.patch_row(order_keys.GATEWAY_ORDER_PREFIX, referenceId="")

    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert body["orderNumber"] is None
    assert r.db.rows(ORDERS_TABLE) == []
    # The capture is recorded regardless, because that is step 1 and it is unconditional.
    attempt = r.attempt_row()
    assert attempt["status"] == payment_attempt.PAYMENT_PAID
    assert attempt[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg
    alarms = [json.loads(record.getMessage()) for record in caplog.records
              if record.getMessage().startswith("{")]
    assert any(entry.get("event") == "website_checkout_verify_reference_unresolved"
               and entry.get("alert") == "PAID_BUT_NO_ORDER" for entry in alarms), alarms


def test_a_verified_capture_is_recorded_even_when_reconciliation_fails(rig, caplog):
    """Five reconciliation outcomes return without order identity, so recording comes FIRST.

    Driven through the real failure rather than by stubbing the outcome: the order claim's
    durable write fails, which is `IDENTITY_UNAVAILABLE` -- money ours, no order, needs a human.
    """
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_4")

    def _unavailable(*_args, **_kwargs):
        raise order_keys.OrderIdentityUnavailable("the claim could not be written")

    r.mp.setattr(r.h.order_keys, "claim_order_for_payment", _unavailable)
    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert body["orderNumber"] is None
    assert r.db.rows(ORDERS_TABLE) == []
    attempt = r.attempt_row()
    assert attempt["status"] == payment_attempt.PAYMENT_PAID
    assert attempt[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg
    assert attempt["providerPaymentId"] == "pay_final_1"
    alarms = [json.loads(record.getMessage()) for record in caplog.records
              if record.getMessage().startswith("{")]
    assert any(entry.get("alert") == "PAID_BUT_NO_ORDER" for entry in alarms), alarms


def test_a_finalization_fault_is_still_a_200(rig, caplog):
    """A finalization fault must not make a paying customer think the payment failed."""
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_5")

    def _boom(**_kwargs):
        raise RuntimeError("finalization exploded")

    r.mp.setattr(r.h.finalization, "accept_paid", _boom)
    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=options["orderId"], payment_id="pay_final_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    # The reserved public number still reaches the shopper.
    assert body["orderNumber"], "a finalization fault must not withhold a reserved order number"
    assert r.db.rows(ORDERS_TABLE) == []
    alarms = [json.loads(record.getMessage()) for record in caplog.records
              if record.getMessage().startswith("{")]
    assert any(entry.get("event") == "website_checkout_finalize_failed"
               and entry.get("alert") == "PAID_BUT_NO_ORDER_RECORD" for entry in alarms), alarms
    # And no exception text reached the log; only the type name.
    assert not any("finalization exploded" in record.getMessage() for record in caplog.records)


def test_two_readbacks_disagreeing_on_the_capture_write_nothing(rig, caplog):
    """Two authenticated readbacks, two stored authorities, and a disagreement writes nothing.

    `verify_callback` compares the capture against `GATEWAYORDER#.amountPaise`;
    `reconcile_payment` compares it against `PAYREF#.amountPaise`. For a design whose discipline
    is "fail closed on one paise", silently preferring one of two provider-derived figures is the
    wrong shape -- so they are compared, and a disagreement records the capture and writes no
    order record.
    """
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_load_6")
    gateway_order_id = options["orderId"]
    reference_id = r.creates[-1]["notes"]["referenceId"]
    # The two stored authorities disagree by one paise, which is the only way both comparisons
    # can pass and still produce two different provider figures.
    r.patch_row(order_keys.PAYMENT_REFERENCE_PREFIX, amountPaise=leg + 1)

    r.mp.setattr(r.h.razorpay_orders, "verify_checkout_signature", lambda **kwargs: True)

    def verifier(**_kwargs):
        def _verify(identifier):
            # Each readback answers the figure its own caller will compare against.
            if identifier == gateway_order_id:
                return (True, "pay_split_1", leg, "INR")
            return (True, "pay_split_1", leg + 1, "INR")
        return _verify

    r.mp.setattr(r.h.razorpay_verify, "verifier_for_event", verifier)

    with caplog.at_level(logging.ERROR):
        code, body = r.verify(order_id=gateway_order_id, payment_id="pay_split_1")
    assert code == 200 and body["status"] == "VERIFIED_PAID", body
    assert r.db.rows(ORDERS_TABLE) == [], "a capture disagreement must write no order record"
    assert r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg
    alarms = [json.loads(record.getMessage()) for record in caplog.records
              if record.getMessage().startswith("{")]
    assert any(entry.get("event") == "checkout_verify_capture_disagreement"
               and entry.get("alert") == "PAID_BUT_NO_ORDER_RECORD" for entry in alarms), alarms
    assert reference_id, "the reference is what the second readback was keyed on"


# ── the closed-tab path: `_status` and `_finalize_from_claim` ──────────────────

def test_the_closed_tab_poll_writes_exactly_one_order_record(rig):
    """The shape this wiring exists for: the webhook numbered the order, the browser never returned.

    The gate is the CLAIM, not the attempt's status, because the webhook does not touch the
    attempt row -- so on this path the status is still PAYMENT_PENDING when the claim already
    exists, and gating on `may_create_order` could never be satisfied.
    """
    r = rig()
    leg, options = _paid_flow(r, request_key="K_status_1", payment_id="pay_tab_1")
    webhook = _webhook_reconcile(r, payment_id="pay_tab_1", amount_paise=leg)
    assert webhook.outcome == r.h.order_creation.ORDER_CREATED
    assert not r.attempt_row().get("finalizationStage")

    r.stub_capture(payment_id="pay_tab_1", amount_paise=leg)
    code, body = r.status(options["paymentAttemptId"])
    assert code == 200, body
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    assert _stage_of(r)[0] == "ORDER_FINALIZED"
    assert r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR] == leg

    # A second poll finds `finalizationStage` set and does not run again.
    code_again, _ = r.status(options["paymentAttemptId"])
    assert code_again == 200
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    assert _stage_of(r)[0] == "ORDER_FINALIZED"
    assert r.db.count_prefix(order_keys.ORDER_NUMBER_PREFIX) == 1


def test_the_status_leg_refuses_rather_than_substituting_the_payable(rig):
    """With no stored capture the status leg ASKS THE PROVIDER. It never substitutes the payable.

    Under split tender the payable is a different number, and substituting it is exactly the
    full-amount-instead-of-leg defect this graft removes. Two halves: an unavailable provider
    writes nothing at all, and an available one stores the LEG.
    """
    r = rig()
    redeem = 35000
    leg, options = _paid_flow(r, request_key="K_status_2", redeem_paise=redeem,
                              payment_id="pay_tab_2")
    payable = int(r.attempt_row()["amountPaise"])
    assert leg != payable, "no split, so this row would prove nothing"
    _webhook_reconcile(r, payment_id="pay_tab_2", amount_paise=leg)

    # 1. The provider cannot be reached: nothing is written and nothing is substituted.
    r.stub_capture(raises=RuntimeError("provider unavailable"))
    code, _body = r.status(options["paymentAttemptId"])
    assert code == 200
    assert r.db.rows(ORDERS_TABLE) == []
    assert finalization_module().VERIFIED_CAPTURED_PAISE_ATTR not in r.attempt_row()

    # 2. The provider answers: the stored figure is the LEG, never the payable.
    r.stub_capture(payment_id="pay_tab_2", amount_paise=leg)
    code, _body = r.status(options["paymentAttemptId"])
    assert code == 200
    assert len(r.db.rows(ORDERS_TABLE)) == 1
    stored = r.attempt_row()[finalization_module().VERIFIED_CAPTURED_PAISE_ATTR]
    assert stored == leg and stored != payable


def test_a_claim_without_a_reference_alarms_once_instead_of_polling_forever(rig, caplog):
    """An empty reference makes every resolver answer None, so a readback could never succeed.

    The claim exists, so money moved; nothing here can resolve it and repeated polls will not
    change that. Alarm at ERROR so a human reconciles, and stop -- rather than asking the
    provider on this poll and on every future poll.
    """
    import logging
    r = rig()
    leg, options = _paid_flow(r, request_key="K_status_3", payment_id="pay_tab_3")
    _webhook_reconcile(r, payment_id="pay_tab_3", amount_paise=leg)
    r.patch_attempt(referenceId="")

    def _never(**_kwargs):
        raise AssertionError("a claim with no reference must not reach the provider at all")

    r.mp.setattr(r.h.razorpay_verify, "verifier_for_event", _never)
    with caplog.at_level(logging.ERROR):
        code, _body = r.status(options["paymentAttemptId"])
        assert code == 200
        first = [json.loads(record.getMessage()) for record in caplog.records
                 if record.getMessage().startswith("{")]
        assert [entry for entry in first
                if entry.get("event") == "checkout_status_claim_without_reference"
                and entry.get("alert") == "PAID_BUT_NO_ORDER_RECORD"], first
        assert r.db.rows(ORDERS_TABLE) == []


def test_claim_outcome_satisfies_accept_paid(rig):
    """`_ClaimOutcome` maps the claim row's MEASURED field names onto one argument contract.

    `orderIdRef`, not `orderId`: on the commerce-keys table `orderId` IS the partition attribute,
    so a business field of the same name would be overwritten by the key. `accept_paid` reads
    `orderId` twice, so omitting it from the dict would `KeyError` after `record_paid` had
    already written PAYMENT_PAID.
    """
    r = rig()
    claim = {"orderIdRef": "ORD-fixture", "orderNumber": "WD-ORD-FIXTURE1",
             "providerTransactionId": "pay_claim_1"}
    outcome = r.h._ClaimOutcome(claim, {"paymentAttemptId": "pa-fixture"})
    assert outcome.has_order
    assert outcome.order_id == "ORD-fixture"
    assert outcome.order_number == "WD-ORD-FIXTURE1"
    assert outcome.provider_payment_id == "pay_claim_1"
    rendered = outcome.as_dict()
    # EXACTLY the keys `accept_paid` reads off an outcome, by name.
    for key in ("hasOrder", "orderId", "orderNumber"):
        assert key in rendered, key
    assert rendered["hasOrder"] is True
    # A claim with no number is NOT an order: the numbering step is mid-flight or crashed, and
    # inventing a number would burn or duplicate one.
    unnumbered = r.h._ClaimOutcome({"orderIdRef": "ORD-x"}, {"paymentAttemptId": "pa"})
    assert not unnumbered.has_order


# ══ the money boundaries, as a table ═══════════════════════════════════════════
#
# R6.1 forbids float arithmetic anywhere in the payment path, and the reason is specific rather
# than stylistic: `0.1 + 0.2` is not `0.3` in binary floating point, and a one-paise mismatch
# against the checkout total must FAIL CLOSED (R6.2) -- so a rounding artefact becomes a refused
# order. These rows walk the five boundaries every stored amount passes through.

#: The canonical float that is not the number it looks like. Written as the SUM, not as the
#: literal, so the row fails if Python's arithmetic ever stops being the point.
_FLOAT_SUM = 0.1 + 0.2


def _attempts_fake():
    table = FakeTable(key_attr="paymentAttemptId")
    attempt = {"paymentAttemptId": "pa_money_1", "referenceId": "ref_money_1",
               "customerId": CUSTOMER, "amountPaise": 100, "currency": "INR",
               "checkoutMode": website_checkout.CHECKOUT_MODE_WEBSITE,
               "status": payment_attempt.PAYMENT_PENDING,
               "purchasedSnapshot": {"cart": {"id": CART}}, "snapshotHash": "hash-money"}
    table.put_item(Item=dict(attempt))
    return table, attempt


@pytest.mark.parametrize("value", [_FLOAT_SUM, 100.0, True, Decimal("1.5"), "abc", None],
                         ids=["float_sum", "whole_float", "bool", "fractional_decimal",
                              "non_numeric_string", "none"])
def test_a_float_amount_is_refused_at_every_money_boundary(value):
    """Every boundary a stored amount crosses refuses the same six values.

    `bool` is in the table because a `bool` IS an `int` in Python and `True` would read as one
    paise; `100.0` is in it because a float that happens to be whole is still a float and
    accepting it would be the crack the discipline exists to close. The two values that must
    STILL work are in `test_an_exact_integer_amount_is_still_accepted_everywhere`.
    """
    fin = finalization_module()
    # 1. `integer_paise` -- the function every stored amount passes through.
    assert fin.integer_paise(value) is None, value

    # 2. `record_paid` -- refuses before it writes anything at all.
    table, attempt = _attempts_fake()
    with pytest.raises(ValueError):
        fin.record_paid(table, attempt, "pay_money_1", value)
    assert table.rows["pa_money_1"].get("status") == payment_attempt.PAYMENT_PENDING, (
        "record_paid wrote a paid state for an amount it then refused")

    # 3. `accept_paid` -- validated BEFORE `record_paid` runs, so nothing is staged.
    table, attempt = _attempts_fake()
    with pytest.raises(ValueError):
        fin.accept_paid(attempts=table, orders=FakeTable(key_attr="orderId"),
                        keys=_keys(), attempt=attempt,
                        outcome={"hasOrder": True, "orderId": "ORD-money",
                                 "orderNumber": "WD-ORD-MONEY01",
                                 "providerPaymentId": "pay_money_1"},
                        verified_captured_paise=value)
    assert not table.rows["pa_money_1"].get("finalizationStage")

    # 4. `payment_attempt.build` -- the producer boundary. TypeError, not a coercion.
    with pytest.raises((TypeError, ValueError)):
        payment_attempt.build(customer_id=CUSTOMER, reference_id="ref_money_1",
                              amount_paise=value, configuration_name="WEBSITE_RAZORPAY_STANDARD")

    # 5. `money.positive_paise` -- the money boundary. A float or bool is refused rather than
    #    coerced.
    from lambda_utils.ecommerce import money as _money
    with pytest.raises((TypeError, ValueError)):
        _money.positive_paise(value)


@pytest.mark.parametrize("value", [100, Decimal("100"), "100"],
                         ids=["int", "integral_decimal", "integer_string"])
def test_an_exact_integer_amount_is_still_accepted_everywhere(value):
    """The must-still-work half. A guard that refuses everything is not a guard.

    `Decimal('100')` is the shape DynamoDB hands a number back as, and `'100'` is the shape a
    hand-written fixture can produce; both are exactly 100 paise and both must pass.
    """
    fin = finalization_module()
    assert fin.integer_paise(value) == 100

    table, attempt = _attempts_fake()
    fin.record_paid(table, attempt, "pay_money_ok", value)
    stored = table.rows["pa_money_1"]
    assert stored["status"] == payment_attempt.PAYMENT_PAID
    # Stored as an INT, whatever shape it arrived in.
    assert stored[fin.VERIFIED_CAPTURED_PAISE_ATTR] == 100
    assert type(stored[fin.VERIFIED_CAPTURED_PAISE_ATTR]) is int

    # A redelivery agreeing on BOTH the provider id and the amount is idempotent...
    fin.record_paid(table, attempt, "pay_money_ok", value)
    assert table.rows["pa_money_1"][fin.VERIFIED_CAPTURED_PAISE_ATTR] == 100
    # ...and one agreeing on the provider id but NOT the amount is refused by the DATABASE,
    # rather than overwriting the evidence. This is what the nested condition group buys, and it
    # is what two sibling OR groups would get wrong.
    with pytest.raises(Exception) as refused:
        fin.record_paid(table, attempt, "pay_money_ok", 101)
    assert order_keys.is_conditional_failure(refused.value), refused.value
    assert table.rows["pa_money_1"][fin.VERIFIED_CAPTURED_PAISE_ATTR] == 100


# ══ the joint attempt-row blob budget ══════════════════════════════════════════

#: DynamoDB's hard per-item ceiling. Not imported from anywhere because nothing in this repo
#: declares it; it is the provider's number and it is what the budget exists to stay under.
_DYNAMODB_ITEM_LIMIT_BYTES = 400_000


def test_the_attempt_row_fits_one_dynamodb_item():
    """The stored snapshot is bounded, because it is an attribute on ONE 400 KB item.

    If the arithmetic is wrong the failure is specific and bad: `reserve_attempt`'s conditional
    put raises an item-size validation error AFTER `bind_gateway_order` has committed and
    `create_order` has landed a PAYABLE gateway order, so the handler answers 503 leaving a bound
    payable order with no attempt row and no cart rows behind it. A same-key retry resumes onto
    it through the choke point, so it is not a double-charge path -- but it is the exact "payable
    order with nothing behind it" shape this change exists to eliminate, reached through a size
    bug rather than a logic bug.
    """
    ceiling = website_checkout._ATTEMPT_BLOB_BUDGET_BYTES
    assert ceiling < _DYNAMODB_ITEM_LIMIT_BYTES, (
        "the budget must leave room for the rest of the row")

    # An oversized snapshot: many lines, each carrying detail the reduced projection drops.
    oversized_snapshot = _frozen(items=[
        {"lineItemId": f"line-{index}", "quantity": 1, "name": f"Item {index}",
         "totalPrice": {"amount": "1000.00"},
         "descriptionLines": ["x" * 400, "y" * 400]}
        for index in range(400)])
    assert len(json.dumps(oversized_snapshot, default=str)) > ceiling, (
        "the fixture is not oversized, so nothing below exercises a reduction")

    snapshot_blob = website_checkout._bounded_snapshot(oversized_snapshot, ceiling)

    # THE PROPERTY. Bounded, so the row fits one item with room for every other field.
    assert len(json.dumps(snapshot_blob, default=str)) <= ceiling
    # The reduction is FLAGGED, so the evidence is never mistaken for the whole record...
    assert snapshot_blob["purchasedSnapshotReduced"] is True
    # ...and the money and the identity survive it. `cart` is retained deliberately:
    # `accept_paid`'s own guard is `snapshot.get('cart')`, so dropping it would REFUSE the order
    # rather than shrink it.
    assert snapshot_blob["cart"] == oversized_snapshot["cart"]
    assert snapshot_blob["components"] == oversized_snapshot["components"]
    # A snapshot inside the budget is stored whole.
    assert website_checkout._bounded_snapshot(_frozen(), ceiling) == _frozen()


def test_an_ordinary_prepare_stores_a_row_far_inside_the_item_limit(rig):
    """The same property measured on the row production actually writes, end to end."""
    r = rig()
    code, body = r.prepare("K_blob_1")
    assert code == 200 and body["status"] == "CHECKOUT_OPTIONS_READY", body
    row_bytes = len(json.dumps(r.attempt_row(), default=str))
    assert row_bytes <= _DYNAMODB_ITEM_LIMIT_BYTES
    assert not r.attempt_row()["purchasedSnapshot"].get("purchasedSnapshotReduced")
    # ONE blob on the row: the reviewed snapshot is the only structured attribute stored.
    assert [name for name, value in r.attempt_row().items()
            if isinstance(value, (dict, list))] == ["purchasedSnapshot"]


# ══ the two residues the review named, each now pinned ═════════════════════════

def test_a_pointer_with_no_cart_identity_refuses_rather_than_passing():
    """`_record_cart_pointer` must REFUSE a missing identity, not return "written, carry on".

    Driven at the choke point rather than through a prepare, because the path is UNREACHABLE from
    a prepare today and that is the point: `build_snapshot` derives `frozen_data['cart']['id']`
    from the same `cart_id` it puts on `QuoteSnapshot.cart_id`, and step 2a converts a cartless
    payload into `CheckoutRejected(BASKET_IDENTITY_REQUIRED)` before anything is created. The
    invariant is stronger as a refusal than as a pass that depends on a precondition two modules
    away, so the refusal is asserted directly.

    Both arms, because either identity empty means the three keys cannot be composed.
    """
    # A STAND-IN rather than a real `QuoteSnapshot`, and the reason is itself worth recording:
    # `QuoteSnapshot.__post_init__` raises `PricingError('snapshot requires a cart id')`, so an
    # identity-less snapshot CANNOT BE CONSTRUCTED. That is a third layer above the two named in
    # the docstring, which is why this arm is unreachable in production -- and why the only
    # honest way to test the refusal is to hand the function the shape it defends against.
    class _IdentitylessSnapshot:
        cart_id = ""
        snapshot_hash = "hash-identityless"
        frozen_data = {"customer": CUSTOMER, "items": []}

    empty = _IdentitylessSnapshot()

    class _CustomerlessSnapshot(_IdentitylessSnapshot):
        cart_id = CART

    for customer_id, cart_snapshot in ((CUSTOMER, empty), ("", _CustomerlessSnapshot())):
        keys = _keys()
        refusal = website_checkout._emit_payable_modal(
            keys_table=keys, customer_id=customer_id, snapshot=cart_snapshot,
            request_key="K_identity_1", attempt_id="pa_identity", gateway_order_id="order_identity",
            amount_paise=100000, currency="INR", key_id=FIXTURE_PUBLIC_KEY_ID, prefill={})
        assert refusal.status == website_checkout.CHECKOUT_AMBIGUOUS
        assert refusal.reason == website_checkout.CART_POINTER_SAVE_FAILED
        # NO options, so the modal cannot open and the unused Razorpay order expires.
        assert refusal.options is None
        # And no cart row was written, so nothing claims a basket it could not name.
        assert keys.rows == {}


class _CreateRightHostileTable(FakeTable):
    """Refuses the create-right claim EXACTLY ONCE, as a concurrent click would.

    It then stores the holder's reference on the row, which is the state the loser must read: the
    holder won the right and `if_not_exists` kept THEIR reference, not ours.
    """

    HOLDER_REFERENCE = "ref_HOLDER_0001"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refused = 0

    def update_item(self, **kwargs):
        expression = str(kwargs.get("UpdateExpression") or "")
        if "createClaimedAt" in expression and not self.refused:
            self.refused += 1
            key = list(kwargs["Key"].values())[0]
            row = dict(self.rows.get(key) or {})
            row["referenceId"] = self.HOLDER_REFERENCE
            row["createClaimedAt"] = int(time.time())
            self.rows[key] = row
            raise FakeClientError("ConditionalCheckFailedException")
        return super().update_item(**kwargs)


def test_a_lost_create_right_correlates_on_the_stored_reference(rig):
    """A create-right loser correlates on the HOLDER's reference and creates no second order.

    `allocate_payment_reference` mints and durably reserves on EVERY call, and the mint cannot
    move below the create right -- `_reference_and_create_right` claims the right and writes the
    reference in ONE conditional round trip, so it has to be handed a value. The documented
    consequence is an orphan `PAYREF#` row, and this row pins both halves of it:

      * the correlation uses the reference read BACK off the row, never the one we minted, so a
        receipt lookup can find the holder's order;
      * the orphan exists, carries no provider link, and is garbage rather than a correctness
        problem -- the webhook resolves on `notes.referenceId`, which only ever carries the
        winner's value.
    """
    hostile = _CreateRightHostileTable(key_attr="orderId")
    r = rig(keys_table=hostile)
    receipts = []
    r.mp.setattr(r.h.razorpay_orders, "find_order_by_receipt",
                 lambda receipt: receipts.append(receipt) or None)

    code, body = r.prepare("K_right_1")
    assert hostile.refused == 1, "the create right was never contested, so nothing was tested"
    # 200 for provider ambiguity: we genuinely do not know whether the holder's create landed.
    assert code == 200, body
    assert body["status"] == website_checkout.CHECKOUT_AMBIGUOUS
    assert body["reason"] == website_checkout.CREATE_IN_FLIGHT
    assert "options" not in body, "a loser must never be handed a payable modal"
    # NO second gateway order, which is the whole point.
    assert r.creates == []

    # The correlation was performed against the HOLDER's reference, not ours.
    expected = website_checkout._receipt_for(
        _CreateRightHostileTable.HOLDER_REFERENCE, "K_right_1")
    assert receipts == [expected], receipts

    # The orphan: exactly one `PAYREF#` row, ours, with no provider link on it.
    orphans = _rows_with(r, order_keys.PAYMENT_REFERENCE_PREFIX)
    assert len(orphans) == 1
    assert not orphans[0].get("providerOrderId"), (
        "the orphan acquired a provider link, so it is no longer harmless garbage")
    minted = str(orphans[0]["orderId"])[len(order_keys.PAYMENT_REFERENCE_PREFIX):]
    assert minted != _CreateRightHostileTable.HOLDER_REFERENCE, (
        "the loser's mint collided with the holder's reference, so this row proves nothing")
    # And no cart rows, because the loser never reached the choke point.
    assert r.db.count_prefix(order_keys.CART_PAYMENT_PREFIX) == 0
    assert r.db.count_prefix(order_keys.CART_BASKET_PREFIX) == 0
