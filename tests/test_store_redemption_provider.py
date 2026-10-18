"""Coupon-store binding for the shared redemption authority.

The retired gift-card backend is deliberately absent here. These tests keep the
surviving coupon binding honest: protocol shape, verdict mapping, store-owned
discount amounts, unsupported kinds, minimums, outages, and no duplicate money math.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import redemption  # noqa: E402
from lambda_utils.ecommerce import store_redemption_provider as srp  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/store_redemption_provider.py"
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(MODULE))

NOW = 1_700_000_000
START_MS = 1_700_000_000_000
CART_REF = "WD-PAY-TEST-REF-ALPHA"

#: ₹10,000. Above the coupon fixture's minimum subtotal, so the floor is never the reason a
#: probe refuses, and large enough that the convenience fee is not lost to rounding.
COLLECTION_PAISE = 1_000_000


def clock(value: int = NOW + 10):
    return lambda: value


def coupons_table() -> FakeTable:
    return FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                     indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})



def coupon_payload(**overrides):
    base = {
        "code": "SAVE1000",
        "name": "A thousand paise off",
        "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 100000,
        "startTimeMs": START_MS,
        "minimumSubtotalPaise": 500000,
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


def issue_coupon(store: FakeTable, **overrides):
    """A created coupon. Creation alone makes it applicable: the row is the sole authority."""
    return cs.create(store, coupon_payload(**overrides), created_by="staff-1", clock=clock(NOW))



def provider(coupons: FakeTable, *, customer_id=None, now: int = NOW + 10):
    return srp.StoreRedemptionProvider(coupons_table=coupons, customer_id=customer_id,
                                       clock=clock(now))


# ── the Protocol is satisfied, and it is the only implementation ───────────────

def test_the_provider_matches_the_protocol_signatures_exactly():
    """`RedemptionProvider` is a plain `Protocol`, not `runtime_checkable`, so `isinstance`
    cannot answer this. Comparing the signatures is what actually has to hold: a keyword
    renamed on one side and not the other is a `TypeError` at the first real call, which on this
    path means at invoice create."""
    for name in ("validate_coupon",):
        expected = inspect.signature(getattr(redemption.RedemptionProvider, name))
        actual = inspect.signature(getattr(srp.StoreRedemptionProvider, name))
        assert list(actual.parameters) == list(expected.parameters), name
        for parameter in expected.parameters.values():
            assert actual.parameters[parameter.name].kind == parameter.kind, \
                f"{name}.{parameter.name}"


def test_every_coupon_verdict_other_than_eligible_maps_to_a_typed_reason():
    """A complete table, asserted complete. A new verdict with no mapping must fail here rather
    than become a silent `INELIGIBLE` in production."""
    assert set(srp.COUPON_REASON_BY_VERDICT) == set(cs.VERDICTS) - {cs.ELIGIBLE}
    assert set(srp.COUPON_REASON_BY_VERDICT.values()) <= {
        redemption.COUPON_INVALID, redemption.COUPON_EXPIRED, redemption.COUPON_INELIGIBLE}


# ── coupons ───────────────────────────────────────────────────────────────────

def test_an_eligible_coupon_yields_the_amount_the_store_computed():
    coupons = coupons_table()
    issue_coupon(coupons)
    authority = provider(coupons).validate_coupon(
        code="save1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert authority.valid is True
    assert authority.reason == redemption.COUPON_APPLIED
    assert authority.discount_paise == 100000
    assert type(authority.discount_paise) is int
    # The figure is the store's, not the provider's: the same definition priced directly agrees.
    definition = cs.get_definition(coupons, "SAVE1000")
    assert authority.discount_paise == cs.discount_paise(
        definition, collection_paise=COLLECTION_PAISE)


def test_a_percent_off_coupon_is_priced_with_the_same_rounding_as_the_convenience_fee():
    """`12345 paise * 1500 bps` is `1851.75`: half-up gives `1852`, truncation `1851`. One paise,
    and `redemption` fails closed on a one-paise mismatch - so the coupon must round the same way
    `checkout_pricing` rounds the convenience fee, not a second way."""
    coupons = coupons_table()
    issue_coupon(coupons, discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=1500,
                 minimumSubtotalPaise=0)
    authority = provider(coupons).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=12345, cart_ref=CART_REF)
    assert authority.valid is True
    assert authority.discount_paise == 1852
    assert authority.discount_paise == cp.round_half_up(12345, 1500)


def test_a_freshly_created_coupon_applies_with_no_further_write():
    """The CouponsTable row is the sole authority, so `create` alone makes a coupon priceable:
    nothing is written between creating a coupon and applying it, and applying it is
    exact-key reads only."""
    coupons = coupons_table()
    issue_coupon(coupons)
    coupons.calls.clear()
    authority = provider(coupons).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert authority.valid is True
    assert authority.reason == redemption.COUPON_APPLIED
    assert authority.discount_paise == 100000
    assert set(coupons.operations()) == {"get_item"}


def test_an_unknown_code_and_a_malformed_code_answer_alike():
    coupons = coupons_table()
    bound = provider(coupons)
    for code in ("NOSUCHCODE", "not a code at all", "", None):
        authority = bound.validate_coupon(
            code=code, collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
        assert authority.valid is False
        assert authority.reason == redemption.COUPON_INVALID
        assert authority.discount_paise == 0


def test_an_expired_coupon_reports_expired_and_a_not_started_one_reports_the_same():
    coupons = coupons_table()
    issue_coupon(coupons, expirationTimeMs=START_MS + 86_400_000)
    after = provider(coupons, now=START_MS // 1000 + 86_401).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (after.valid, after.reason) == (False, redemption.COUPON_EXPIRED)
    before = provider(coupons, now=START_MS // 1000 - 10).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (before.valid, before.reason) == (False, redemption.COUPON_EXPIRED)


def test_a_usage_limited_coupon_is_refused_once_its_limit_is_reached():
    coupons = coupons_table()
    issue_coupon(coupons, usageLimit=1)
    cs.commit_redemption(coupons, code="SAVE1000", cart_id="cart-a", order_id="order-a",
                         customer_id="customer-a", clock=clock(NOW))
    authority = provider(coupons).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert authority.valid is False
    assert authority.reason == redemption.COUPON_INELIGIBLE


def test_a_per_customer_limit_is_only_enforceable_when_a_customer_was_injected():
    """A real narrowing, pinned rather than left to be rediscovered: a staff-raised invoice may
    have no customer identity, and inventing one would attribute a use to the wrong person."""
    coupons = coupons_table()
    issue_coupon(coupons, limitPerCustomer=1)
    cs.commit_redemption(coupons, code="SAVE1000", cart_id="cart-a", order_id="order-a",
                         customer_id="customer-a", clock=clock(NOW))
    with_customer = provider(coupons, customer_id="customer-a").validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (with_customer.valid, with_customer.reason) == (False, redemption.COUPON_INELIGIBLE)
    anonymous = provider(coupons).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert anonymous.valid is True


def test_a_coupon_held_by_another_cart_is_refused_and_the_same_cart_is_not():
    coupons = coupons_table()
    issue_coupon(coupons)
    cs.hold(coupons, code="SAVE1000", cart_id="another-cart", clock=clock(NOW + 10))
    bound = provider(coupons)
    other = bound.validate_coupon(code="SAVE1000",
                                  collection_before_discount_paise=COLLECTION_PAISE,
                                  cart_ref=CART_REF)
    assert (other.valid, other.reason) == (False, redemption.COUPON_INELIGIBLE)
    mine = bound.validate_coupon(code="SAVE1000",
                                 collection_before_discount_paise=COLLECTION_PAISE,
                                 cart_ref="another-cart")
    assert mine.valid is True


@pytest.mark.parametrize("overrides", [
    {"discountKind": cs.FREE_SHIPPING, "moneyOffPaise": None, "minimumSubtotalPaise": None},
    {"discountKind": cs.BUY_X_GET_Y, "moneyOffPaise": None, "buyX": 2, "buyY": 1},
])
def test_a_kind_this_surface_cannot_price_raises_rather_than_discounting_nothing(overrides):
    """The coupon EXISTS and was promised, so the operation must be refused with a typed code.
    Returning `INELIGIBLE` here would look like a customer error, and returning zero would
    collect the full amount while reporting success."""
    coupons = coupons_table()
    issue_coupon(coupons, **overrides)
    with pytest.raises(cs.CouponValidationError) as refusal:
        provider(coupons).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE,
            cart_ref=CART_REF)
    assert refusal.value.code == "COUPON_KIND_UNSUPPORTED"


def test_an_unmet_minimum_subtotal_raises_rather_than_reporting_a_customer_error():
    coupons = coupons_table()
    issue_coupon(coupons)
    with pytest.raises(cs.CouponValidationError) as refusal:
        provider(coupons).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=499999, cart_ref=CART_REF)
    assert refusal.value.code == "MINIMUM_SUBTOTAL"


def test_a_coupon_store_outage_raises_rather_than_reporting_an_invalid_coupon():
    """A throttle reported as absence refuses a live coupon. `coupon_store` gives the outage its
    own type precisely so it cannot be mistaken for `UNKNOWN_CODE`, and the provider must not
    undo that by catching it."""
    coupons = coupons_table()
    issue_coupon(coupons)
    coupons.arm_failure("get_item", RuntimeError("throttled"))
    with pytest.raises(cs.CouponStoreUnavailable):
        provider(coupons).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE,
            cart_ref=CART_REF)
