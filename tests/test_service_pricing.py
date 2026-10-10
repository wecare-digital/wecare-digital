"""The live Wix price resolver: pointer reuse, CartGone recovery, explicit INR, fail closed.

Pure tests. The Wix cart adapter and the DynamoDB table are both fakes, so nothing here touches
a network, a credential or AWS -- which is the same property `service_pricing` itself has by
construction (no boto3 import, no HTTP client, no secret read).
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import cart_v2  # noqa: E402
from lambda_utils.ecommerce import service_pricing as sp  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
AMEND = "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b"
DROP_DOCS = "db166bc8-a763-41ec-9f65-0f718f18155a"
VAULT = "dcff995e-448c-493a-9259-f6a82ccdc2b4"
PICKUP = "8ee7e325-d772-4452-a993-5c79e927d42b"

#: Five DIFFERENT figures, none of them the figures live today, so a test that passes cannot be
#: passing because the old constants leaked back in somewhere.
PRICED = {SUBMIT: 14900, AMEND: 20100, DROP_DOCS: 45050, VAULT: 7700, PICKUP: 28800}

CART_IDS = {SUBMIT: "11111111-1111-4111-8111-111111111111",
            AMEND: "22222222-2222-4222-8222-222222222222",
            DROP_DOCS: "33333333-3333-4333-8333-333333333333",
            VAULT: "44444444-4444-4444-8444-444444444444",
            PICKUP: "55555555-5555-4555-8555-555555555555"}


class FakeTable:
    """A dict-backed `get_item`/`put_item`, recording every call."""

    def __init__(self, rows=None, fail_read=False, fail_write=False):
        self.rows = dict(rows or {})
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.reads = []
        self.writes = []

    def get_item(self, Key, ConsistentRead=False):  # noqa: N803 - boto3's own spelling
        self.reads.append(Key)
        if self.fail_read:
            raise RuntimeError("throttled")
        key = next(iter(Key.values()))
        item = self.rows.get(key)
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):  # noqa: N803
        self.writes.append(Item)
        if self.fail_write:
            raise RuntimeError("throttled")
        self.rows[next(iter(Item.values()))] = dict(Item)


def _line(variant, quantity=1):
    """One cart line in the shape `cart_v2.calculate` reads off `cart["lineItems"]`."""
    return {"id": "line-" + variant[:8],
            "source": {"catalogReference": {
                "appId": cart_v2.STORES_APP_ID, "catalogItemId": PRODUCT,
                "options": {"variantId": variant}}},
            "quantityInfo": {"requestedQuantity": quantity, "confirmedQuantity": quantity}}


def _cart(cart_id, currency="INR", lines=None):
    money = {"currencyCode": currency}
    return {"id": cart_id, "revision": "1", "businessInfo": dict(money),
            "customerInfo": dict(money), "paymentInfo": dict(money),
            "lineItems": list(lines) if lines is not None else []}


class FakeCart:
    """Records `get`/`create`/`estimate`, and can be made to fail in specific ways.

    `holds` overrides what a READ cart appears to contain, `{cart_id: [line, ...]}`. By default a
    read cart holds exactly the one variant its pointer was stored for, which is what the live
    carts this module creates actually hold.
    """

    def __init__(self, *, gone=(), currency="INR", subtotal=None, raise_on_create=False,
                 raise_on_get=False, holds=None):
        self.gone = set(gone)
        self.currency = currency
        self.subtotal = PRICED if subtotal is None else subtotal
        self.raise_on_create = raise_on_create
        self.raise_on_get = raise_on_get
        self.holds = dict(holds or {})
        self.gets, self.creates, self.estimates = [], [], []
        self._variant_of = {cart: variant for variant, cart in CART_IDS.items()}
        self._minted = 0

    def get(self, cart_id):
        self.gets.append(cart_id)
        if cart_id in self.gone:
            raise cart_v2.CartGone("gone", cart_id)
        if self.raise_on_get:
            raise RuntimeError("wix 500")
        if cart_id in self.holds:
            return _cart(cart_id, self.currency, self.holds[cart_id])
        variant = self._variant_of.get(cart_id)
        return _cart(cart_id, self.currency, [_line(variant)] if variant else [])

    def create(self, items):
        if self.raise_on_create:
            raise RuntimeError("wix 500")
        assert len(items) == 1
        # Validated through the REAL `catalog_item`, exactly as `CartV2.create` does. A fake that
        # accepted any shape here let a double-wrapped item through and hid a live ValueError.
        converted = cart_v2.catalog_item(items[0])
        variant = converted["catalogReference"]["options"]["variantId"]
        assert converted["quantity"] == 1
        self.creates.append(variant)
        self._minted += 1
        cart_id = CART_IDS[variant]
        return _cart(cart_id, self.currency, [_line(variant)])

    def estimate(self, cart_id):
        self.estimates.append(cart_id)
        variant = self._variant_of.get(cart_id)
        value = self.subtotal.get(variant) if isinstance(self.subtotal, dict) else self.subtotal
        return {"payable": False, "wixCartId": cart_id, "currency": "INR",
                "itemSubtotalPaise": value}


def _pointer_rows(*variants):
    return {sp.SERVICE_PRICE_CART_PREFIX + v: {"orderId": sp.SERVICE_PRICE_CART_PREFIX + v,
                                               "wixCartId": CART_IDS[v]} for v in variants}


@pytest.fixture(autouse=True)
def _clean_cache():
    sp.reset_cache()
    yield
    sp.reset_cache()


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


# ── the slug vocabulary has one owner ─────────────────────────────────────────

def test_the_five_public_slugs_map_to_the_five_kinds_and_variants():
    assert dict(sr.SERVICE_KIND_BY_SLUG) == {
        "submit-request": "SUBMIT_REQUEST", "request-amendment": "REQUEST_AMENDMENT",
        "drop-docs": "DROP_DOCS", "vault": "VAULT", "request-pickup": "REQUEST_PICKUP"}
    assert dict(sr.SERVICE_SLUG_BY_KIND) == {
        kind: slug for slug, kind in sr.SERVICE_KIND_BY_SLUG.items()}
    assert {sr.SERVICE_VARIANT_BY_KIND[k] for k in sr.SERVICE_KIND_BY_SLUG.values()} == \
        {SUBMIT, AMEND, DROP_DOCS, VAULT, PICKUP}
    assert dict(sp.SERVICE_SLUGS) == dict(sr.SERVICE_KIND_BY_SLUG)


def test_no_price_is_declared_anywhere_in_either_module():
    """The whole point: 9900/35000/4900 must not survive as a constant on the server."""
    for name in ("service_pricing.py", "service_requests.py"):
        source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce"
                  / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, int)}
        assert not literals & {9900, 35000, 4900}, name


# ── one variant ───────────────────────────────────────────────────────────────

def test_a_fresh_variant_creates_one_cart_and_remembers_it():
    table, adapter = FakeTable(), FakeCart()
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == [SUBMIT]
    assert adapter.estimates == [CART_IDS[SUBMIT]]
    assert table.writes == [{"orderId": sp.SERVICE_PRICE_CART_PREFIX + SUBMIT,
                             "wixCartId": CART_IDS[SUBMIT], "variantId": SUBMIT}]


def test_a_stored_pointer_is_reused_and_creates_nothing():
    table = FakeTable(_pointer_rows(SUBMIT))
    adapter = FakeCart()
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == []
    assert adapter.gets == [CART_IDS[SUBMIT]]
    assert table.writes == []


def test_a_second_read_in_a_cold_resolver_still_creates_nothing():
    """The cart bound is LIFETIME, not per invocation: the pointer is what bounds Wix writes."""
    table = FakeTable()
    first = FakeCart()
    sp.resolve_variant_paise(first, table, SUBMIT)
    second = FakeCart()
    assert sp.resolve_variant_paise(second, table, SUBMIT) == PRICED[SUBMIT]
    assert second.creates == []


def test_cart_gone_mints_a_fresh_cart_and_overwrites_the_pointer():
    stale = "99999999-9999-4999-8999-999999999999"
    table = FakeTable({sp.SERVICE_PRICE_CART_PREFIX + SUBMIT: {
        "orderId": sp.SERVICE_PRICE_CART_PREFIX + SUBMIT, "wixCartId": stale}})
    adapter = FakeCart(gone={stale})
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.gets == [stale]
    assert adapter.creates == [SUBMIT]
    assert table.rows[sp.SERVICE_PRICE_CART_PREFIX + SUBMIT]["wixCartId"] == CART_IDS[SUBMIT]


def test_an_unreadable_pointer_falls_back_to_creating_a_cart():
    """A throttled read must not wedge a price: the recovery for "no pointer" covers both."""
    table = FakeTable(_pointer_rows(SUBMIT), fail_read=True)
    adapter = FakeCart()
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == [SUBMIT]


@pytest.mark.parametrize("stored", ["", "not-a-uuid", None, 7])
def test_a_corrupt_pointer_value_is_ignored_rather_than_fatal(stored):
    table = FakeTable({sp.SERVICE_PRICE_CART_PREFIX + SUBMIT: {
        "orderId": sp.SERVICE_PRICE_CART_PREFIX + SUBMIT, "wixCartId": stored}})
    adapter = FakeCart()
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == [SUBMIT]


def test_a_failed_pointer_write_still_serves_the_price_it_already_resolved():
    table = FakeTable(fail_write=True)
    assert sp.resolve_variant_paise(FakeCart(), table, SUBMIT) == PRICED[SUBMIT]


@pytest.mark.parametrize("currency", ["USD", "inr", "", None])
def test_a_cart_wix_did_not_return_in_inr_is_refused(currency):
    """The currency is read from WIX'S OWN cart fields. `estimate()['currency']` is a literal."""
    with pytest.raises(sp.ServicePriceUnavailable):
        sp.resolve_variant_paise(FakeCart(currency=currency), FakeTable(), SUBMIT)


def test_the_inr_check_also_runs_on_the_reuse_path():
    table = FakeTable(_pointer_rows(SUBMIT))
    with pytest.raises(sp.ServicePriceUnavailable):
        sp.resolve_variant_paise(FakeCart(currency="USD"), table, SUBMIT)


# ── a reused cart has to hold the variant it is being priced for ──────────────
#
# `itemSubtotalPaise` is the CART's subtotal, not a named line's price. On the create path the two
# are the same figure because this module built the cart; on the reuse path nothing re-establishes
# that, so a pointer row carrying a valid cart id for the WRONG variant would publish one
# service's price under another slug -- the exact "each is a different item" fault -- and the
# checkout would then charge a figure the card never showed.

def test_a_stored_cart_holding_another_variant_is_not_priced_as_this_one():
    """The fault in its purest form: SUBMIT's pointer row points at VAULT's cart."""
    table = FakeTable({sp.SERVICE_PRICE_CART_PREFIX + SUBMIT: {
        "orderId": sp.SERVICE_PRICE_CART_PREFIX + SUBMIT, "wixCartId": CART_IDS[VAULT]}})
    adapter = FakeCart()
    paise = sp.resolve_variant_paise(adapter, table, SUBMIT)
    # VAULT's figure must NOT come back under SUBMIT.
    assert paise != PRICED[VAULT]
    assert paise == PRICED[SUBMIT]
    # The wrong cart was never estimated, and the pointer was repaired rather than left to
    # publish the wrong price again on the next read.
    assert adapter.estimates == [CART_IDS[SUBMIT]]
    assert adapter.creates == [SUBMIT]
    assert table.rows[sp.SERVICE_PRICE_CART_PREFIX + SUBMIT]["wixCartId"] == CART_IDS[SUBMIT]


@pytest.mark.parametrize("lines", [
    [],                                                      # emptied cart
    [_line(SUBMIT), _line(VAULT)],                           # a second line joined it
    [_line(SUBMIT), _line(SUBMIT)],                          # the same variant twice
    [_line(SUBMIT, quantity=2)],                             # right variant, wrong quantity
    [{"id": "x"}],                                           # no catalog reference at all
])
def test_a_stored_cart_that_is_not_one_unit_of_this_variant_is_discarded(lines):
    table = FakeTable(_pointer_rows(SUBMIT))
    adapter = FakeCart(holds={CART_IDS[SUBMIT]: lines})
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == [SUBMIT]
    assert adapter.estimates == [CART_IDS[SUBMIT]]


def test_a_cart_with_no_readable_quantity_is_still_reused():
    """The asymmetry is deliberate. The variant shape is proven live by the working checkout;
    which quantity field a plain cart READ carries is not measured in this repo, so refusing on
    an unreadable one would take all five services off sale instead of pricing them. A quantity
    that IS readable and is not 1 is refused -- the case above."""
    line = _line(SUBMIT)
    line.pop("quantityInfo")
    table = FakeTable(_pointer_rows(SUBMIT))
    adapter = FakeCart(holds={CART_IDS[SUBMIT]: [line]})
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == []


def test_the_variant_is_matched_case_insensitively():
    line = _line(SUBMIT)
    line["source"]["catalogReference"]["options"]["variantId"] = SUBMIT.upper()
    table = FakeTable(_pointer_rows(SUBMIT))
    adapter = FakeCart(holds={CART_IDS[SUBMIT]: [line]})
    assert sp.resolve_variant_paise(adapter, table, SUBMIT) == PRICED[SUBMIT]
    assert adapter.creates == []


def test_a_mismatched_pointer_cannot_cross_two_slugs_in_one_payload():
    """End to end: every pointer row points at the NEXT service's cart. All five must still
    publish their own figure rather than rotating by one."""
    rotated = [SUBMIT, AMEND, DROP_DOCS, VAULT, PICKUP]
    rows = {}
    for index, variant in enumerate(rotated):
        wrong = CART_IDS[rotated[(index + 1) % len(rotated)]]
        rows[sp.SERVICE_PRICE_CART_PREFIX + variant] = {
            "orderId": sp.SERVICE_PRICE_CART_PREFIX + variant, "wixCartId": wrong}
    payload = sp.resolve_all(FakeCart(), FakeTable(rows), clock=Clock())
    assert payload["prices"] == {
        "submit-request": {"available": True, "paise": PRICED[SUBMIT]},
        "request-amendment": {"available": True, "paise": PRICED[AMEND]},
        "drop-docs": {"available": True, "paise": PRICED[DROP_DOCS]},
        "vault": {"available": True, "paise": PRICED[VAULT]},
        "request-pickup": {"available": True, "paise": PRICED[PICKUP]},
    }


@pytest.mark.parametrize("subtotal", [None, 0, -1, "9900", 99.0, True, 99.5])
def test_a_subtotal_that_is_not_positive_integer_paise_is_refused(subtotal):
    with pytest.raises(sp.ServicePriceUnavailable):
        sp.resolve_variant_paise(FakeCart(subtotal={SUBMIT: subtotal}), FakeTable(), SUBMIT)


@pytest.mark.parametrize("kwargs", [{"raise_on_create": True}, {"raise_on_get": True}])
def test_a_wix_failure_raises_unavailable_rather_than_guessing(kwargs):
    rows = _pointer_rows(SUBMIT) if kwargs.get("raise_on_get") else {}
    with pytest.raises(sp.ServicePriceUnavailable):
        sp.resolve_variant_paise(FakeCart(**kwargs), FakeTable(rows), SUBMIT)


def test_an_unknown_variant_id_is_rejected_before_any_call():
    adapter = FakeCart()
    with pytest.raises(ValueError):
        sp.resolve_variant_paise(adapter, FakeTable(), "not-a-uuid")
    assert adapter.creates == [] and adapter.gets == []


# ── all five ──────────────────────────────────────────────────────────────────

def test_resolve_all_prices_every_slug_with_its_own_figure():
    payload = sp.resolve_all(FakeCart(), FakeTable(), clock=Clock())
    assert payload["currency"] == "INR"
    assert payload["prices"] == {
        "submit-request": {"available": True, "paise": PRICED[SUBMIT]},
        "request-amendment": {"available": True, "paise": PRICED[AMEND]},
        "drop-docs": {"available": True, "paise": PRICED[DROP_DOCS]},
        "vault": {"available": True, "paise": PRICED[VAULT]},
        "request-pickup": {"available": True, "paise": PRICED[PICKUP]},
    }
    assert all(type(price["paise"]) is int for price in payload["prices"].values())


def test_five_distinct_prices_stay_distinct():
    """"Each is a different item": the five slugs must not collapse onto one figure."""
    payload = sp.resolve_all(FakeCart(), FakeTable(), clock=Clock())
    assert len({price["paise"] for price in payload["prices"].values()}) == 5


def test_one_slug_failing_leaves_the_other_four_priced_and_carries_no_paise():
    broken = dict(PRICED)
    broken[VAULT] = None
    payload = sp.resolve_all(FakeCart(subtotal=broken), FakeTable(), clock=Clock())
    assert payload["prices"]["vault"] == {"available": False}
    assert "paise" not in payload["prices"]["vault"]
    for slug in ("submit-request", "request-amendment", "drop-docs", "request-pickup"):
        assert payload["prices"][slug]["available"] is True


def test_no_float_reaches_the_payload():
    payload = sp.resolve_all(FakeCart(), FakeTable(), clock=Clock())
    def walk(value):
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
    walk(payload)


# ── the cache ─────────────────────────────────────────────────────────────────

def test_a_second_call_inside_the_window_performs_no_adapter_call():
    clock = Clock()
    table = FakeTable()
    sp.resolve_all(FakeCart(), table, clock=clock)
    cold = FakeCart()
    clock.now += sp.CACHE_SECONDS - 1
    sp.resolve_all(cold, table, clock=clock)
    assert cold.creates == [] and cold.gets == [] and cold.estimates == []


def test_the_cache_expires_and_a_new_wix_price_is_then_served():
    clock = Clock()
    table = FakeTable()
    first = sp.resolve_all(FakeCart(), table, clock=clock)
    assert first["prices"]["vault"]["paise"] == PRICED[VAULT]
    clock.now += sp.CACHE_SECONDS
    raised = dict(PRICED)
    raised[VAULT] = 19900
    second = sp.resolve_all(FakeCart(subtotal=raised), table, clock=clock)
    assert second["prices"]["vault"]["paise"] == 19900


def test_an_all_unavailable_payload_is_not_cached():
    """A transient Wix outage must not pin five pages as unavailable for a whole minute."""
    clock = Clock()
    table = FakeTable()
    dead = sp.resolve_all(FakeCart(raise_on_create=True), table, clock=clock)
    assert all(price == {"available": False} for price in dead["prices"].values())
    alive = sp.resolve_all(FakeCart(), table, clock=clock)
    assert all(price["available"] for price in alive["prices"].values())


def test_the_window_is_sixty_seconds():
    assert sp.CACHE_SECONDS == 60


# ── the module's own shape ────────────────────────────────────────────────────

def test_the_module_does_no_float_arithmetic_and_owns_no_client():
    tree = ast.parse((ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                      "service_pricing.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("float", "open")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] + [getattr(node, "module", "") or ""]
            assert not any(n.split(".")[0] in ("boto3", "botocore", "urllib", "requests")
                           for n in names)
