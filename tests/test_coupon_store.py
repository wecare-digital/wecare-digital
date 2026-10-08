"""The coupon issuance store: uniqueness, validation, limits, holds and redemption.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` sections 4,
5.2, 5.4 and 5.5, and the test list in section 7 (tests 1-21).

Three tests here are not in that list and are the reason the HIGH findings stay closed rather
than merely answered in prose:

* `test_every_dynamodb_access_is_an_exact_key_operation_or_the_status_index_query` enumerates the
  module's call sites, which is what pins HIGH-3 / DECISION 5. A sentence saying "no scan" is not
  a gate; an enumeration is.
* `test_hold_is_one_conditional_update_with_no_preceding_read` pins the shape of the hold gate.
  A `get_item` in front of it would turn an atomic guard into a read-modify-write, and two carts
  reading "free" in the same moment would both proceed - which is precisely the race the
  condition exists to lose.
* `test_a_coupon_with_no_per_customer_limit_still_counts_the_use` pins NIT-5's branch, so
  "unlimited" and "never used" stay distinguishable in the data.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from decimal import Decimal

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeClientError, FakeTable  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/coupon_store.py"
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(MODULE))

NOW = 1_700_000_000
START_MS = 1_700_000_000_000


def clock(value: int = NOW):
    return lambda: value


def table() -> FakeTable:
    return FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                     indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})


def payload(**overrides):
    base = {
        "code": "SAVE10",
        "name": "Ten rupees off",
        "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 100000,
        "startTimeMs": START_MS,
        "minimumSubtotalPaise": 500000,
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


def issue(store: FakeTable, **overrides):
    """A coupon that has been created AND mirrored, which is the only applicable state."""
    definition = cs.create(store, payload(**overrides), created_by="staff-1", clock=clock())
    return cs.mark_mirrored(store, definition["code"], "wix-" + definition["code"].lower(),
                            clock=clock())


# ── 1-2: the code is the key ──────────────────────────────────────────────────

def test_the_code_is_the_partition_key_so_a_duplicate_is_refused_by_the_database():
    """Concurrency serialises in DynamoDB, not in our code. One winner, keyed on the code."""
    store = table()
    first = cs.create(store, payload(), clock=clock())
    assert first[cs.KEY_ATTRIBUTE] == "COUPON#SAVE10"

    with pytest.raises(cs.CouponConflict) as refusal:
        cs.create(store, payload(name="a second attempt"), clock=clock())
    assert refusal.value.code == "CODE_ALREADY_EXISTS"
    assert refusal.value.status == 409
    # The winner's row is untouched: the loser never got to overwrite it.
    assert store.rows["COUPON#SAVE10"]["name"] == "Ten rupees off"

    claims = [call for call in store.calls if call[0] == "put_item"]
    assert len(claims) == 2
    for _, kwargs in claims:
        assert kwargs["ConditionExpression"] == f"attribute_not_exists({cs.KEY_ATTRIBUTE})"


@pytest.mark.parametrize("spelling", ["SAVE10", "save10", "Save10", "ＳＡＶＥ１０", " save10 "])
def test_case_and_unicode_variants_normalise_to_one_coupon(spelling):
    """A fullwidth or lower-case variant is the SAME coupon, because a customer reads it that
    way. Wix does not document its code uniqueness as case-insensitive, so normalising is ours
    to do."""
    assert cs.normalise_code(spelling) == "SAVE10"
    assert cs.definition_key(spelling) == "COUPON#SAVE10"

    store = table()
    cs.create(store, payload(code="SAVE10"), clock=clock())
    with pytest.raises(cs.CouponConflict):
        cs.create(store, payload(code=spelling), clock=clock())
    assert len(store.rows) == 1


# ── 3-5: exactly one kind, and the free-shipping exception ────────────────────

def test_exactly_one_discount_kind_is_accepted():
    """Refused HERE rather than at Wix, because Wix's `type` is read-only and derived from
    whichever discount field was set - so two fields would mean something nobody chose."""
    with pytest.raises(cs.CouponValidationError) as none_at_all:
        cs.validate_definition(payload(discountKind=None, moneyOffPaise=None), clock=clock())
    assert none_at_all.value.code == "INVALID_DISCOUNT_KIND"

    with pytest.raises(cs.CouponValidationError) as two:
        cs.validate_definition(payload(percentOffBps=500), clock=clock())
    assert two.value.code == "INVALID_DISCOUNT_KIND"


def test_free_shipping_may_not_carry_a_scope_and_needs_no_minimum_subtotal():
    """The documented exception, both directions."""
    free = cs.validate_definition(
        payload(discountKind=cs.FREE_SHIPPING, moneyOffPaise=None,
                minimumSubtotalPaise=None), clock=clock())
    assert free["discountKind"] == cs.FREE_SHIPPING
    assert "minimumSubtotalPaise" not in free

    with pytest.raises(cs.CouponValidationError) as scoped:
        cs.validate_definition(
            payload(discountKind=cs.FREE_SHIPPING, moneyOffPaise=None,
                    minimumSubtotalPaise=None, scopeNamespace="stores",
                    scopeGroupName="product",
                    scopeEntityId="11111111-1111-4111-8111-111111111111"), clock=clock())
    assert scoped.value.code == "FREE_SHIPPING_CANNOT_CARRY_SCOPE"


@pytest.mark.parametrize("kind,extra", [
    (cs.MONEY_OFF, {"moneyOffPaise": 100000}),
    (cs.PERCENT_OFF, {"percentOffBps": 500}),
    (cs.FIXED_PRICE, {"fixedPricePaise": 100000}),
    (cs.BUY_X_GET_Y, {"buyX": 2, "buyY": 1}),
])
def test_every_other_kind_requires_scope_or_minimum_subtotal(kind, extra):
    body = payload(discountKind=kind, moneyOffPaise=None, minimumSubtotalPaise=None)
    body.update(extra)
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition(body, clock=clock())
    assert refusal.value.code == "SCOPE_OR_MINIMUM_SUBTOTAL_REQUIRED"

    body["scopeNamespace"] = cs.SCOPE_NAMESPACE
    assert cs.validate_definition(body, clock=clock())["scopeNamespace"] == cs.SCOPE_NAMESPACE


# ── 6-8: money is integer paise, refused by type and by modulus ───────────────

@pytest.mark.parametrize("amount", [12.34, 1234.0, Decimal("12.34"), True, "100000", None])
def test_a_float_amount_is_refused_rather_than_rounded(amount):
    """By TYPE, never coerced. `0.1 + 0.2 != 0.3` in binary floating point, and a one-paise
    mismatch against the checkout total must fail closed - so a rounding artefact here becomes
    a refused order later."""
    with pytest.raises(cs.CouponValidationError):
        cs.validate_definition(payload(moneyOffPaise=amount), clock=clock())


def test_no_float_is_constructed_on_the_coupon_money_path(monkeypatch):
    """Patches `float` to raise, then runs the whole validation and conversion path."""
    def explode(*_args, **_kwargs):
        raise AssertionError("a float was constructed on the coupon money path")

    monkeypatch.setitem(cs.__builtins__ if isinstance(cs.__builtins__, dict)
                        else cs.__builtins__.__dict__, "float", explode)
    definition = cs.validate_definition(payload(), clock=clock())
    assert definition["moneyOffPaise"] == 100000


def test_money_is_stored_as_integer_paise_and_rates_as_basis_points():
    money_off = cs.validate_definition(payload(), clock=clock())
    assert type(money_off["moneyOffPaise"]) is int
    assert type(money_off["minimumSubtotalPaise"]) is int

    percent = cs.validate_definition(
        payload(discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=500),
        clock=clock())
    # 500 basis points IS 5%. Stored as bps so no fractional percent can be represented.
    assert percent["percentOffBps"] == 500
    assert type(percent["percentOffBps"]) is int
    assert percent["currency"] == "INR"
    assert percent["policyVersion"] == cs.POLICY_VERSION


@pytest.mark.parametrize("field,value", [
    ("moneyOffPaise", 12345),
    ("fixedPricePaise", 12345),
    ("minimumSubtotalPaise", 12345),
    ("percentOffBps", 250),
])
def test_a_sub_rupee_amount_is_refused_at_creation(field, value):
    """Pins section 4.2's whole-rupee restriction as DELIBERATE rather than a bug.

    The Wix coupon service's money fields are JSON numbers in decimal rupees and nothing
    documents a string being accepted, so this release emits `paise // 100`. Rounding a
    discount silently changes what a customer was promised, and `2500` bps rounded to `25`
    is a different coupon from 2.5%.
    """
    body = payload(moneyOffPaise=None if field != "moneyOffPaise" else value)
    if field == "fixedPricePaise":
        body = payload(discountKind=cs.FIXED_PRICE, moneyOffPaise=None, fixedPricePaise=value)
    elif field == "percentOffBps":
        body = payload(discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=value)
    elif field == "minimumSubtotalPaise":
        body = payload(minimumSubtotalPaise=value)
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition(body, clock=clock())
    assert refusal.value.code == "SUB_RUPEE_DISCOUNT_NOT_SUPPORTED"


# ── 9-11: times and the code bound ────────────────────────────────────────────

@pytest.mark.parametrize("start", [0, 1, 999_999_999_999, -1700000000000])
def test_a_start_time_below_the_wix_minimum_is_refused(start):
    """Wix's own documented `minimum: 1000000000000` on `startTime`."""
    assert cs.WIX_MIN_TIME_MS == 1_000_000_000_000
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition(payload(startTimeMs=start), clock=clock())
    assert refusal.value.code == "INVALID_START_TIME"


@pytest.mark.parametrize("expiry", [START_MS, START_MS - 1])
def test_an_expiry_not_after_the_start_is_refused(expiry):
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition(payload(expirationTimeMs=expiry), clock=clock())
    assert refusal.value.code == "INVALID_EXPIRATION_TIME"


def test_a_code_longer_than_twenty_characters_never_reaches_wix():
    """Wix documents `Specification.code` as "Max: 20 characters"."""
    assert cs.MAX_CODE_LENGTH == 20
    assert cs.normalise_code("A" * 20) == "A" * 20
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.normalise_code("A" * 21)
    assert refusal.value.code == "INVALID_CODE"


@pytest.mark.parametrize("code", ["", "   ", None, 123, True, "x" * 21, b"code",
                                  "SAVE 10", "SAVE#10", "SAVE/10", "SAVE%10"])
def test_a_malformed_code_never_reaches_the_provider(code):
    """The provider is a spy, and it records ZERO calls - the refusal happens before any I/O."""
    calls = []

    def spy(*args, **kwargs):  # pragma: no cover - must never run
        calls.append((args, kwargs))
        return {}

    store = table()
    with pytest.raises(cs.CouponValidationError):
        cs.create(store, payload(code=code), clock=clock())
    assert calls == []
    assert store.rows == {}


# ── 13-14: limits are conditional writes, not reads ───────────────────────────

def test_usage_limit_is_enforced_by_a_conditional_write_not_a_read():
    """A read-then-write loses a concurrent race, and a usage limit whose whole purpose is to
    hold under concurrency cannot be implemented that way."""
    store = table()
    issue(store, usageLimit=1)

    first = cs.commit_redemption(store, code="SAVE10", cart_id="cart-1", order_id="order-1",
                                customer_id="cus-1", clock=clock())
    assert first["committed"] and first["usageCounted"]
    assert store.rows["COUPON#SAVE10"]["usageCount"] == 1

    second = cs.commit_redemption(store, code="SAVE10", cart_id="cart-2", order_id="order-2",
                                 customer_id="cus-2", clock=clock())
    # The claim is honoured because capture is already verified for that order; the COUNTER is
    # what refuses, and it refuses in the database rather than in our arithmetic.
    assert second["committed"] and second["usageCounted"] is False
    assert store.rows["COUPON#SAVE10"]["usageCount"] == 1

    counter_updates = [kwargs for name, kwargs in store.calls
                       if name == "update_item"
                       and kwargs["ExpressionAttributeNames"].get("#counter") == "usageCount"]
    assert counter_updates, "the global counter never moved through an UpdateItem"
    for kwargs in counter_updates:
        assert "ADD #counter :one" in kwargs["UpdateExpression"]
        assert kwargs["ConditionExpression"] == ("attribute_not_exists(#counter) "
                                                "OR #counter < :limit")
        assert kwargs["ExpressionAttributeValues"][":limit"] == 1


def test_the_per_customer_limit_is_enforced_independently_of_the_global_limit():
    store = table()
    issue(store, usageLimit=5, limitPerCustomer=1)

    first = cs.commit_redemption(store, code="SAVE10", cart_id="c1", order_id="o1",
                                customer_id="cus-1", clock=clock())
    assert first["usageCounted"] and first["customerUsageCounted"]

    again = cs.commit_redemption(store, code="SAVE10", cart_id="c2", order_id="o2",
                                customer_id="cus-1", clock=clock())
    # Global room remains, so the global counter moves; the per-customer counter refuses.
    assert again["usageCounted"] is True
    assert again["customerUsageCounted"] is False
    assert store.rows["COUPON#SAVE10"]["usageCount"] == 2
    assert store.rows["COUPONUSE#SAVE10#cus-1"]["uses"] == 1

    other = cs.commit_redemption(store, code="SAVE10", cart_id="c3", order_id="o3",
                                customer_id="cus-2", clock=clock())
    assert other["customerUsageCounted"] is True
    assert cs.customer_uses(store, "save10", "cus-2") == 1


def test_a_coupon_with_no_per_customer_limit_still_counts_the_use():
    """NIT-5. No `limitPerCustomer` means NO condition is applied - and the row is still
    incremented, so "unlimited" and "never used" stay distinguishable in the data."""
    store = table()
    issue(store)
    assert "limitPerCustomer" not in store.rows["COUPON#SAVE10"]

    for index in range(3):
        cs.commit_redemption(store, code="SAVE10", cart_id=f"c{index}", order_id=f"o{index}",
                            customer_id="cus-1", clock=clock())
    assert store.rows["COUPONUSE#SAVE10#cus-1"]["uses"] == 3

    use_updates = [kwargs for name, kwargs in store.calls
                   if name == "update_item"
                   and kwargs["ExpressionAttributeNames"].get("#counter") == "uses"]
    assert use_updates
    for kwargs in use_updates:
        assert kwargs["ConditionExpression"] is None, \
            "a coupon with no per-customer limit must apply no per-customer condition"


# ── 15-17: redemption is idempotent, and ordered ──────────────────────────────

def test_a_second_redemption_for_the_same_order_is_idempotent():
    store = table()
    issue(store, usageLimit=5, limitPerCustomer=5)
    cs.commit_redemption(store, code="SAVE10", cart_id="c1", order_id="order-1",
                        customer_id="cus-1", clock=clock())
    before = dict(store.rows["COUPON#SAVE10"])

    replay = cs.commit_redemption(store, code="SAVE10", cart_id="c1", order_id="order-1",
                                 customer_id="cus-1", clock=clock())
    assert replay == {"committed": False, "code": "SAVE10", "orderId": "order-1"}
    assert store.rows["COUPON#SAVE10"] == before
    assert store.rows["COUPONUSE#SAVE10#cus-1"]["uses"] == 1


def test_two_different_orders_each_consume_one_use():
    """Keyed on ORDER, not attempt: a retry of one basket must not consume a second use, and
    `order_keys` only mints an orderId after capture is verified."""
    store = table()
    issue(store, usageLimit=5, limitPerCustomer=5)
    for order in ("order-1", "order-2"):
        assert cs.commit_redemption(store, code="SAVE10", cart_id="c", order_id=order,
                                   customer_id="cus-1", clock=clock())["committed"]
    assert store.rows["COUPON#SAVE10"]["usageCount"] == 2
    assert cs.redemption(store, "SAVE10", "order-1")["orderId"] == "order-1"
    assert cs.redemption(store, "SAVE10", "order-3") is None


def test_the_claim_is_taken_before_the_counters():
    """Order is load-bearing. The claim is irreversible and the counters are not, so a crash
    between them undercounts a correctly-marked coupon - which a replay repairs, because the
    claim is idempotent and the ADDs only run when the claim was newly won. The reverse order
    would double-count on every replay."""
    store = table()
    issue(store, usageLimit=5)
    store.calls.clear()
    cs.commit_redemption(store, code="SAVE10", cart_id="c1", order_id="order-1",
                        customer_id="cus-1", clock=clock())

    operations = store.operations()
    claim_index = next(index for index, (name, kwargs) in enumerate(store.calls)
                       if name == "put_item"
                       and str(kwargs["Item"][cs.KEY_ATTRIBUTE]).startswith(cs.PREFIX_REDEEM))
    first_counter = operations.index("update_item")
    last_delete = operations.index("delete_item")
    assert claim_index < first_counter < last_delete


def test_the_claim_is_a_conditional_put_that_cannot_be_overwritten():
    store = table()
    issue(store)
    cs.commit_redemption(store, code="SAVE10", cart_id="c1", order_id="order-1",
                        customer_id="cus-1", clock=clock())
    claims = [kwargs for name, kwargs in store.calls
              if name == "put_item"
              and str(kwargs["Item"][cs.KEY_ATTRIBUTE]).startswith(cs.PREFIX_REDEEM)]
    assert claims
    for kwargs in claims:
        assert kwargs["ConditionExpression"] == f"attribute_not_exists({cs.KEY_ATTRIBUTE})"


def test_a_storage_failure_on_the_claim_is_never_read_as_already_redeemed():
    """A throttle answering "already claimed" would silently skip a redemption. Its own
    exception type is what keeps the two apart."""
    store = table()
    issue(store)
    store.arm_failure("put_item", FakeClientError("ProvisionedThroughputExceededException"))
    with pytest.raises(cs.CouponStoreUnavailable):
        cs.commit_redemption(store, code="SAVE10", cart_id="c", order_id="o",
                            customer_id="cus", clock=clock())


# ── 18: holds ─────────────────────────────────────────────────────────────────

def test_a_hold_past_its_expiry_does_not_block_another_cart():
    """A crashed checkout must not hold a single-use coupon forever."""
    store = table()
    issue(store)
    cs.hold(store, code="SAVE10", cart_id="cart-a", ttl_seconds=60, clock=clock(NOW))

    with pytest.raises(cs.CouponHeldByAnotherCart):
        cs.hold(store, code="SAVE10", cart_id="cart-b", clock=clock(NOW + 30))

    taken = cs.hold(store, code="SAVE10", cart_id="cart-b", clock=clock(NOW + 61))
    assert taken["held"] and taken["cartId"] == "cart-b"
    assert store.rows["COUPON#SAVE10"][cs.HOLD_CART_ATTRIBUTE] == "cart-b"


def test_re_taking_a_hold_for_the_same_cart_is_idempotent_not_a_conflict():
    store = table()
    issue(store)
    cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())
    assert cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())["held"]


def test_release_clears_the_hold_and_deletes_the_audit_row():
    store = table()
    issue(store)
    cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())
    assert "COUPONHOLD#SAVE10#cart-a" in store.rows

    cs.release(store, code="SAVE10", cart_id="cart-a", clock=clock())
    assert cs.HOLD_CART_ATTRIBUTE not in store.rows["COUPON#SAVE10"]
    assert "COUPONHOLD#SAVE10#cart-a" not in store.rows
    # The definition itself survives a release, which is the whole point of the row split.
    assert store.rows["COUPON#SAVE10"]["code"] == "SAVE10"


def test_another_cart_cannot_release_a_live_hold():
    store = table()
    issue(store)
    cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())
    with pytest.raises(cs.CouponHeldByAnotherCart):
        cs.release(store, code="SAVE10", cart_id="cart-b", clock=clock())


def test_hold_is_one_conditional_update_with_no_preceding_read():
    """DECISION 5, asserted on the AST so it cannot regress into a read-modify-write.

    `hold()` performs exactly ONE `update_item` and NO `get_item`. The `put_item` that follows
    writes the `COUPONHOLD#` audit row, which is never read to make a decision and is written
    second on purpose: if it fails, the authoritative hold still stands.
    """
    function = next(node for node in ast.walk(TREE)
                    if isinstance(node, ast.FunctionDef) and node.name == "hold")
    # Sorted by line, because `ast.walk` is breadth-first and would report the calls in an
    # order that has nothing to do with the order they run in.
    attributes = [node.func.attr for node in sorted(
        (node for node in ast.walk(function)
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
         and isinstance(node.func.value, ast.Name) and node.func.value.id == "table"),
        key=lambda node: node.lineno)]
    assert attributes == ["update_item", "put_item"], \
        "hold() must be one conditional UpdateItem, then the audit row, and nothing else"

    # The three clauses of the condition, each with the reason it is there.
    assert "attribute_not_exists(activeHoldCartId)" in cs.HOLD_CONDITION   # nobody holds it
    assert "activeHoldCartId = :me" in cs.HOLD_CONDITION                   # I already do
    assert "activeHoldExpiresAtMs < :now" in cs.HOLD_CONDITION             # it lapsed
    assert " OR " in cs.HOLD_CONDITION

    store = table()
    issue(store)
    store.calls.clear()
    cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())
    assert store.operations() == ["update_item", "put_item"]
    assert store.calls[0][1]["ConditionExpression"].count("OR") == 2


# ── 19-21: what the store cannot do ───────────────────────────────────────────

def test_nothing_in_the_store_can_delete_a_definition_or_a_redemption_record():
    """Enumerates the delete call sites. A definition is what a settled order cites, and a
    redemption record is the single-use proof; both must be undeletable by construction rather
    than by convention."""
    deletes = [node for node in ast.walk(TREE)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "delete_item"]
    assert len(deletes) == 1, "a second delete call site needs its own justification"

    owner = next(node for node in ast.walk(TREE)
                 if isinstance(node, ast.FunctionDef)
                 and any(call is deletes[0] for call in ast.walk(node)))
    assert owner.name == "_delete_hold"

    key = next(kw.value for kw in deletes[0].keywords if kw.arg == "Key")
    assert "PREFIX_HOLD" in ast.unparse(key)
    for forbidden in ("PREFIX_DEFINITION", "PREFIX_REDEEM", "PREFIX_USE"):
        assert forbidden not in ast.unparse(key)


def test_a_coupon_definition_row_carries_no_ttl_attribute():
    """TTL is disabled on this table and the row must not invite someone to enable it.

    `expirationTimeMs` is a POLICY field - it decides applicability - and is deliberately not
    named like a DynamoDB TTL attribute, because expiry here must never be a deletion.
    """
    definition = cs.validate_definition(payload(expirationTimeMs=START_MS + 86_400_000),
                                        clock=clock())
    ttl_shapes = {"ttl", "TTL", "expiresAt", "expireAt", "expiry", "lastUpdatedAt",
                  "expiresAtEpoch", "deleteAt"}
    assert not (set(definition) & ttl_shapes)
    assert definition["expirationTimeMs"] == START_MS + 86_400_000


def test_discounted_cycle_count_is_refused_because_the_scope_is_stores():
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition({**payload(), "discountedCycleCount": 3}, clock=clock())
    assert refusal.value.code == "DISCOUNTED_CYCLE_COUNT_NOT_SUPPORTED"


def test_an_unsupported_field_is_refused_rather_than_dropped():
    """A misspelled `expirationTimeMS` must not issue a coupon that never expires."""
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.validate_definition({**payload(), "expirationTimeMS": START_MS + 1}, clock=clock())
    assert refusal.value.code == "UNSUPPORTED_FIELD"


# ── the access-pattern enumeration (HIGH-3 / DECISION 5) ──────────────────────

EXACT_KEY_OPERATIONS = {"get_item", "put_item", "update_item", "delete_item"}


def _store_calls():
    """Every call this module makes on its injected `table`."""
    return [node for node in ast.walk(TREE)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "table"]


def test_every_dynamodb_access_is_an_exact_key_operation_or_the_status_index_query():
    """Pins HIGH-3. Prose saying "no scan" is not a gate; this enumeration is.

    Every access is either keyed on a fully specified `couponKey` or is the single staff
    `status-index` Query. There is no scan, no prefix query and no second index - which is what
    makes DECISION 5 (the hold fact living on the definition row) necessary rather than merely
    tidy.
    """
    calls = _store_calls()
    assert calls, "the enumeration found no table access at all; the receiver was renamed"

    assert not [node for node in ast.walk(TREE)
                if isinstance(node, ast.Attribute) and node.attr == "scan"], \
        "a scan call site appeared in the coupon store"

    queries = 0
    for node in calls:
        operation = node.func.attr
        kwargs = {kw.arg for kw in node.keywords}
        assert operation in EXACT_KEY_OPERATIONS | {"query"}, \
            f"line {node.lineno}: unexpected table operation {operation!r}"
        if operation == "query":
            queries += 1
            continue
        if operation == "put_item" and "Item" in kwargs:
            continue
        if "Key" in kwargs:
            continue
        # A `**request` expansion. The key still has to be an exact `couponKey`, so look at the
        # dict the enclosing function builds rather than treating the expansion as unknown.
        assert None in kwargs, f"line {node.lineno}: {operation} with no exact Key"
        owner = next(parent for parent in ast.walk(TREE)
                     if isinstance(parent, ast.FunctionDef)
                     and any(child is node for child in ast.walk(parent)))
        body = ast.unparse(owner)
        assert "'Key': {KEY_ATTRIBUTE:" in body, \
            f"{owner.name} expands a request whose Key is not an exact couponKey"

    # The one Query, and it names the index rather than reading the base table.
    assert queries == 1
    query_call = next(node for node in calls if node.func.attr == "query")
    request = ast.unparse(query_call)
    assert "**request" in request or "IndexName" in request
    assert '"IndexName": STATUS_INDEX' in SOURCE or "'IndexName': STATUS_INDEX" in SOURCE


def test_the_status_index_query_is_sparse_and_bounded():
    store = table()
    issue(store, code="SAVE10")
    issue(store, code="SAVE20")
    cs.hold(store, code="SAVE10", cart_id="cart-a", clock=clock())
    cs.commit_redemption(store, code="SAVE20", cart_id="c", order_id="o", customer_id="cus",
                         clock=clock())

    page = cs.list_by_status(store, cs.STATUS_ACTIVE)
    keys = sorted(row[cs.KEY_ATTRIBUTE] for row in page["Items"])
    # Only definition rows carry `status`, so counters, holds and redemption records never
    # enter the index. That sparseness is why a low-cardinality partition key is affordable.
    assert keys == ["COUPON#SAVE10", "COUPON#SAVE20"]
    assert any(name == "query" for name, _ in store.calls)

    with pytest.raises(cs.CouponValidationError):
        cs.list_by_status(store, "NOT_A_STATUS")


# ── the module's shape ────────────────────────────────────────────────────────

def test_the_store_holds_no_boto3_client_and_reads_no_secret():
    """Injected table resource and injected clock, so there is nothing ambient to mock and
    nothing to leak. Asserted over the AST rather than by inspection."""
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("boto3", "botocore", "os"):
        assert not any(name == forbidden or name.startswith(forbidden + ".")
                       for name in imported), f"coupon_store imports {forbidden}"

    for marker in ("get_secret_value", "secretsmanager", "SecretId", "boto3"):
        assert marker not in SOURCE, f"coupon_store mentions {marker}"


def test_the_store_reuses_money_and_identifiers_rather_than_reimplementing_them():
    assert "positive_paise" in SOURCE
    assert "new_uuid7" in SOURCE
    assert cs.MAX_PAISE == 9007199254740991  # money.py's ceiling, not a second constant


def test_the_store_exposes_no_function_that_returns_a_discount_amount():
    """Our table records what was PROMISED; on the WEBSITE it never computes what was DEDUCTED,
    because there the amount is Wix's answer to Calculate Cart.

    `discount_paise` is the one deliberate narrowing of that rule and it is why this test checks
    NAMES rather than counting functions: the invoice surface has no Wix cart to ask, so one
    reading of our own definition is unavoidable there. What must stay absent is a general
    discount ENGINE - a `compute_*` / `calculate_*` / `*discount_amount*` entry point that
    invites a second arithmetic to grow beside Wix's. `discount_paise` is named for what it
    returns, takes no cart and no network, and is pinned attribute-for-attribute against
    `wix_coupons.specification` by `tests/test_wix_coupons_contract.py`."""
    public = [name for name in dir(cs) if not name.startswith("_") and callable(getattr(cs, name))]
    for name in public:
        assert "discount_amount" not in name
        assert not name.startswith("compute_")
        assert not name.startswith("calculate_")


def test_the_verdict_vocabulary_is_closed_and_carries_no_amount():
    assert set(cs.VERDICTS) == {
        "ELIGIBLE", "UNKNOWN_CODE", "NOT_ACTIVE", "NOT_STARTED", "EXPIRED",
        "USAGE_LIMIT_REACHED", "CUSTOMER_LIMIT_REACHED", "HELD_BY_ANOTHER_CART",
        "WIX_MIRROR_INCOMPLETE"}


@pytest.mark.parametrize("definition,expected", [
    (None, cs.UNKNOWN_CODE),
    ({cs.STATUS_ATTRIBUTE: cs.STATUS_INACTIVE}, cs.NOT_ACTIVE),
    ({cs.STATUS_ATTRIBUTE: cs.STATUS_ACTIVE, "wixMirrorState": cs.MIRROR_PENDING},
     cs.WIX_MIRROR_INCOMPLETE),
])
def test_evaluate_fails_closed_on_every_incomplete_state(definition, expected):
    """A `PENDING_WIX` coupon is refused rather than attempted: Wix would reject `Add Coupon`
    and the customer would watch a discount appear and then vanish."""
    assert cs.evaluate(definition, clock=clock()) == expected


def test_evaluate_answers_the_time_and_limit_verdicts():
    store = table()
    row = issue(store, usageLimit=1, limitPerCustomer=1,
                expirationTimeMs=START_MS + 86_400_000)
    assert cs.evaluate(row, clock=clock(START_MS // 1000 - 10)) == cs.NOT_STARTED
    assert cs.evaluate(row, clock=clock(START_MS // 1000 + 86_401)) == cs.EXPIRED
    assert cs.evaluate(row, clock=clock(START_MS // 1000 + 10)) == cs.ELIGIBLE
    assert cs.evaluate({**row, "usageCount": 1},
                       clock=clock(START_MS // 1000 + 10)) == cs.USAGE_LIMIT_REACHED
    assert cs.evaluate(row, customer_uses_count=1,
                       clock=clock(START_MS // 1000 + 10)) == cs.CUSTOMER_LIMIT_REACHED

    held = cs.hold(store, code="SAVE10", cart_id="cart-a",
                   clock=clock(START_MS // 1000 + 10))["coupon"]
    assert cs.evaluate(held, cart_id="cart-b",
                       clock=clock(START_MS // 1000 + 10)) == cs.HELD_BY_ANOTHER_CART
    assert cs.evaluate(held, cart_id="cart-a",
                       clock=clock(START_MS // 1000 + 10)) == cs.ELIGIBLE


def test_deactivate_marks_inactive_and_never_deletes():
    store = table()
    issue(store)
    row = cs.deactivate(store, "save10", clock=clock())
    assert row[cs.STATUS_ATTRIBUTE] == cs.STATUS_INACTIVE
    assert "COUPON#SAVE10" in store.rows
    assert cs.evaluate(row, clock=clock()) == cs.NOT_ACTIVE

    with pytest.raises(cs.CouponError) as unknown:
        cs.deactivate(store, "NOSUCHCODE", clock=clock())
    assert unknown.value.code == "UNKNOWN_CODE"


# ── discount_paise: the one amount this module answers, and only for an invoice ──

def definition(kind, **extra):
    """A bare definition row, built by hand.

    `discount_paise` is pure and reads only the discount attributes, so a hand-built row is the
    honest input here - going through `create` would additionally impose the whole-rupee and
    scope rules, which are issuance concerns and would hide which attribute the arithmetic
    actually reads.
    """
    row = {"discountKind": kind}
    row.update(extra)
    return row


def test_money_off_is_the_stored_amount_and_percent_off_is_round_half_up():
    assert cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=100000),
                             collection_paise=500000) == 100000
    assert cs.discount_paise(definition(cs.PERCENT_OFF, percentOffBps=1000),
                             collection_paise=500000) == 50000
    assert cs.discount_paise(definition(cs.FIXED_PRICE, fixedPricePaise=100000),
                             collection_paise=250000) == 150000


def test_percent_off_rounds_half_up_rather_than_truncating():
    """`12345 paise * 1500 bps` is `1851.75`, so half-up gives `1852` where truncation gives
    `1851`. One paise, and `redemption` fails closed on a one-paise mismatch - so the rounding
    rule has to be the same one `checkout_pricing` uses for the convenience fee, not a second
    one. That is why this calls `round_half_up` instead of doing its own division."""
    assert cs.discount_paise(definition(cs.PERCENT_OFF, percentOffBps=1500),
                             collection_paise=12345) == 1852
    # The plan's worked example, kept because it pins the exact-half boundary from the other
    # side: `1543.125` rounds DOWN, so half-up is not "always round up".
    assert cs.discount_paise(definition(cs.PERCENT_OFF, percentOffBps=1250),
                             collection_paise=12345) == 1543


def test_a_hundred_percent_coupon_discounts_exactly_the_collection():
    """Exactly, not approximately. `10000 bps` must leave zero payable rather than one paise,
    because a one-paise remainder is below `RAZORPAY_MIN_LEG_PAISE` and therefore uncollectable:
    the order would be neither free nor chargeable."""
    assert cs.discount_paise(definition(cs.PERCENT_OFF, percentOffBps=10000),
                             collection_paise=12345) == 12345


def test_an_oversized_money_off_is_clamped_to_the_collection():
    """`₹5000 off` on a `₹300` invoice is `₹300` off. A coupon cannot make a total negative, and
    it is not a credit note for the difference."""
    assert cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=500000),
                             collection_paise=30000) == 30000


def test_a_fixed_price_above_the_collection_discounts_nothing():
    """`FIXED_PRICE` names the price that REMAINS, so the discount is the difference - and a
    fixed price larger than the collection must not inflate the invoice."""
    assert cs.discount_paise(definition(cs.FIXED_PRICE, fixedPricePaise=500000),
                             collection_paise=30000) == 0


@pytest.mark.parametrize("kind", [cs.FREE_SHIPPING, cs.BUY_X_GET_Y])
def test_a_kind_that_needs_line_items_is_refused_rather_than_discounted_to_zero(kind):
    """Refusing is the fail-closed answer. Returning zero would report success for a coupon the
    customer was promised and the invoice did not honour - the staff member sees it accepted and
    the full amount is still collected."""
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.discount_paise(definition(kind, buyX=1, buyY=1), collection_paise=500000)
    assert refusal.value.code == "COUPON_KIND_UNSUPPORTED"


def test_an_unmet_minimum_subtotal_is_refused_rather_than_discounting_nothing():
    row = definition(cs.MONEY_OFF, moneyOffPaise=100000, minimumSubtotalPaise=500000)
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.discount_paise(row, collection_paise=499999)
    assert refusal.value.code == "MINIMUM_SUBTOTAL"
    # Exactly at the floor is met, not missed.
    assert cs.discount_paise(row, collection_paise=500000) == 100000


@pytest.mark.parametrize("amount", [True, "100", Decimal("1.5"), 12.5, None, 100.0])
def test_a_collection_that_is_not_integer_paise_is_refused_by_type(amount):
    """`True == 1`, so a bool would otherwise be read as one paise. A float is refused rather
    than rounded, for the reason R6.1 states: `0.1 + 0.2` is not `0.3` in binary floating
    point."""
    with pytest.raises(cs.CouponValidationError):
        cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=100000),
                          collection_paise=amount)


@pytest.mark.parametrize("stored", [True, "100", Decimal("1.5"), 12.5, 0, -1])
def test_a_stored_amount_that_is_not_integer_paise_is_refused_by_type(stored):
    with pytest.raises(cs.CouponValidationError):
        cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=stored),
                          collection_paise=500000)


def test_an_integral_dynamodb_decimal_is_accepted_and_a_fractional_one_is_not():
    """DynamoDB hands every number back as `Decimal`, so refusing `Decimal` outright would make
    the function unusable against a real row. An integral one converts; a fractional one is a
    sub-paise amount that cannot be charged and is refused."""
    assert cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=Decimal("100000")),
                             collection_paise=Decimal("500000")) == 100000
    with pytest.raises(cs.CouponValidationError):
        cs.discount_paise(definition(cs.MONEY_OFF, moneyOffPaise=Decimal("100000.5")),
                          collection_paise=500000)


def test_discount_paise_returns_an_int_and_constructs_no_float(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("a float was constructed on the coupon amount path")

    monkeypatch.setitem(cs.__builtins__ if isinstance(cs.__builtins__, dict)
                        else cs.__builtins__.__dict__, "float", explode)
    for row, collection in ((definition(cs.MONEY_OFF, moneyOffPaise=100000), 500000),
                            (definition(cs.PERCENT_OFF, percentOffBps=1500), 12345),
                            (definition(cs.FIXED_PRICE, fixedPricePaise=100000), 250000)):
        assert type(cs.discount_paise(row, collection_paise=collection)) is int


def test_discount_paise_is_pure_so_it_takes_no_table_and_no_clock():
    """Asserted on the signature rather than in prose: a table parameter is how a network call
    gets into the GST invoice-numbering path, and a clock parameter would mean expiry was being
    decided twice - `evaluate` already owns that question."""
    function = next(node for node in ast.walk(TREE)
                    if isinstance(node, ast.FunctionDef) and node.name == "discount_paise")
    arguments = ([argument.arg for argument in function.args.args]
                 + [argument.arg for argument in function.args.kwonlyargs])
    assert arguments == ["definition", "collection_paise"]


def test_an_unknown_discount_kind_is_refused():
    with pytest.raises(cs.CouponValidationError) as refusal:
        cs.discount_paise(definition("SOMETHING_ELSE"), collection_paise=500000)
    assert refusal.value.code == "INVALID_DISCOUNT_KIND"
    with pytest.raises(cs.CouponValidationError) as missing:
        cs.discount_paise(None, collection_paise=500000)
    assert missing.value.code == "UNKNOWN_CODE"
