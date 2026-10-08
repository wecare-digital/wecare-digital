"""The ONE binding between the money authority and the stores, driven end to end offline.

`redemption.py` held the arithmetic and an abstract seam; `coupon_store` / `gift_card_store` held
the definitions and the balances. Before `store_redemption_provider` existed nothing under
`amplify/` implemented the seam, so no discount reached real money on any surface. These tests
drive the join against the in-memory DynamoDB fake the rest of the coupon/gift-card suite uses.

Three of them are the ones worth reading twice:

* `test_the_provider_computes_no_amount_of_its_own` is an AST ban on arithmetic inside the
  provider. The emptiness of that class IS the "one coupon system" guarantee - a provider that
  computes is a second discount engine wearing the Protocol's clothes, and prose would not stop
  someone adding one.
* `test_an_unmirrored_coupon_is_refused_and_yields_no_discount` pins the fail-closed direction.
  A coupon Wix does not know about must not discount an invoice, because the same code applied on
  the website would be rejected by `Add Coupon` and the two surfaces would disagree about what the
  customer was promised.
* `test_the_composed_order_is_coupon_then_fee_then_gift_card` asserts D1 and M6 together: the
  convenience fee is computed on the DISCOUNTED collection, the gift card is subtracted from the
  FINAL total, and `redemption_paise + razorpay_payable_paise == authoritative_total_paise`
  exactly. A gift card must never reduce taxable value, which is only true in that order.
"""

from __future__ import annotations

import ast
import inspect
import logging
import pathlib
import sys
from decimal import Decimal

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402
from lambda_utils.ecommerce import redemption  # noqa: E402
from lambda_utils.ecommerce import store_redemption_provider as srp  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/store_redemption_provider.py"
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(MODULE))

#: Not a credential: a test-only string that exists so the HMAC has a key. The real pepper lives
#: in Secrets Manager, is read by reference at request time, and never reaches a command line.
PEPPER = "pepper-for-tests-only"
CARD_CODE = "WDGC0000TEST0001"

NOW = 1_700_000_000
START_MS = 1_700_000_000_000
#: Deliberately shares no trailing digits with `CARD_CODE`, so the log assertion below cannot
#: pass or fail by coincidence: `reference_id` may be logged in full, and if it ended in the same
#: four characters as the card, "the last four are absent" would be untestable.
CART_REF = "WD-PAY-TEST-REF-ALPHA"

#: ₹10,000. Above the coupon fixture's minimum subtotal, so the floor is never the reason a
#: probe refuses, and large enough that the convenience fee is not lost to rounding.
COLLECTION_PAISE = 1_000_000


def clock(value: int = NOW + 10):
    return lambda: value


def secret_reader(_secret_id):
    """The injected reader. A mapping, by reference, at the moment it is asked for."""
    return {gc.PEPPER_FIELD: PEPPER}


def coupons_table() -> FakeTable:
    return FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                     indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})


def gift_cards_table() -> FakeTable:
    return FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                     indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})


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


def issue_coupon(store: FakeTable, *, mirrored: bool = True, **overrides):
    """A created coupon, mirrored unless the test is about an unmirrored one."""
    definition = cs.create(store, coupon_payload(**overrides), created_by="staff-1",
                           clock=clock(NOW))
    if mirrored:
        return cs.mark_mirrored(store, definition["code"],
                                "wix-" + definition["code"].lower(), clock=clock(NOW))
    return definition


def issue_card(store: FakeTable, *, value_paise: int = 300000, code: str = CARD_CODE, **extra):
    issued = gc.issue(store, initial_value_paise=value_paise, pepper=PEPPER, code=code,
                      clock=clock(NOW), **extra)
    store.calls.clear()
    return issued


def provider(coupons: FakeTable, cards: FakeTable, *, customer_id=None, now: int = NOW + 10):
    return srp.StoreRedemptionProvider(coupons_table=coupons, gift_cards_table=cards,
                                       secret_reader=secret_reader, customer_id=customer_id,
                                       clock=clock(now))


# ── the Protocol is satisfied, and it is the only implementation ───────────────

def test_the_provider_matches_the_protocol_signatures_exactly():
    """`RedemptionProvider` is a plain `Protocol`, not `runtime_checkable`, so `isinstance`
    cannot answer this. Comparing the signatures is what actually has to hold: a keyword
    renamed on one side and not the other is a `TypeError` at the first real call, which on this
    path means at invoice create."""
    for name in ("validate_coupon", "read_gift_card"):
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

def test_an_eligible_mirrored_coupon_yields_the_amount_the_store_computed():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons)
    authority = provider(coupons, cards).validate_coupon(
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
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=1500,
                 minimumSubtotalPaise=0)
    authority = provider(coupons, cards).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=12345, cart_ref=CART_REF)
    assert authority.valid is True
    assert authority.discount_paise == 1852
    assert authority.discount_paise == cp.round_half_up(12345, 1500)


def test_an_unmirrored_coupon_is_refused_and_yields_no_discount():
    """Fail closed. The same code on the website would be rejected by Wix's `Add Coupon`, so
    honouring it on an invoice would make the two surfaces disagree about what was promised."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, mirrored=False)
    assert cs.get_definition(coupons, "SAVE1000")["wixMirrorState"] == cs.MIRROR_PENDING
    authority = provider(coupons, cards).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert authority.valid is False
    assert authority.reason == redemption.COUPON_INELIGIBLE
    assert authority.discount_paise == 0


def test_an_unknown_code_and_a_malformed_code_answer_alike():
    coupons, cards = coupons_table(), gift_cards_table()
    bound = provider(coupons, cards)
    for code in ("NOSUCHCODE", "not a code at all", "", None):
        authority = bound.validate_coupon(
            code=code, collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
        assert authority.valid is False
        assert authority.reason == redemption.COUPON_INVALID
        assert authority.discount_paise == 0


def test_an_expired_coupon_reports_expired_and_a_not_started_one_reports_the_same():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, expirationTimeMs=START_MS + 86_400_000)
    after = provider(coupons, cards, now=START_MS // 1000 + 86_401).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (after.valid, after.reason) == (False, redemption.COUPON_EXPIRED)
    before = provider(coupons, cards, now=START_MS // 1000 - 10).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (before.valid, before.reason) == (False, redemption.COUPON_EXPIRED)


def test_a_usage_limited_coupon_is_refused_once_its_limit_is_reached():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, usageLimit=1)
    cs.commit_redemption(coupons, code="SAVE1000", cart_id="cart-a", order_id="order-a",
                         customer_id="customer-a", clock=clock(NOW))
    authority = provider(coupons, cards).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert authority.valid is False
    assert authority.reason == redemption.COUPON_INELIGIBLE


def test_a_per_customer_limit_is_only_enforceable_when_a_customer_was_injected():
    """A real narrowing, pinned rather than left to be rediscovered: a staff-raised invoice may
    have no customer identity, and inventing one would attribute a use to the wrong person."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, limitPerCustomer=1)
    cs.commit_redemption(coupons, code="SAVE1000", cart_id="cart-a", order_id="order-a",
                         customer_id="customer-a", clock=clock(NOW))
    with_customer = provider(coupons, cards, customer_id="customer-a").validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert (with_customer.valid, with_customer.reason) == (False, redemption.COUPON_INELIGIBLE)
    anonymous = provider(coupons, cards).validate_coupon(
        code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE, cart_ref=CART_REF)
    assert anonymous.valid is True


def test_a_coupon_held_by_another_cart_is_refused_and_the_same_cart_is_not():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons)
    cs.hold(coupons, code="SAVE1000", cart_id="another-cart", clock=clock(NOW + 10))
    bound = provider(coupons, cards)
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
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons, **overrides)
    with pytest.raises(cs.CouponValidationError) as refusal:
        provider(coupons, cards).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE,
            cart_ref=CART_REF)
    assert refusal.value.code == "COUPON_KIND_UNSUPPORTED"


def test_an_unmet_minimum_subtotal_raises_rather_than_reporting_a_customer_error():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons)
    with pytest.raises(cs.CouponValidationError) as refusal:
        provider(coupons, cards).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=499999, cart_ref=CART_REF)
    assert refusal.value.code == "MINIMUM_SUBTOTAL"


def test_a_coupon_store_outage_raises_rather_than_reporting_an_invalid_coupon():
    """A throttle reported as absence refuses a live coupon. `coupon_store` gives the outage its
    own type precisely so it cannot be mistaken for `UNKNOWN_CODE`, and the provider must not
    undo that by catching it."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons)
    coupons.arm_failure("get_item", RuntimeError("throttled"))
    with pytest.raises(cs.CouponStoreUnavailable):
        provider(coupons, cards).validate_coupon(
            code="SAVE1000", collection_before_discount_paise=COLLECTION_PAISE,
            cart_ref=CART_REF)


# ── gift cards ────────────────────────────────────────────────────────────────

def test_a_live_card_reports_its_stored_balance():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_card(cards, value_paise=300000)
    authority = provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    assert authority.usable is True
    assert authority.reason == redemption.GIFT_CARD_APPLIED
    assert authority.balance_paise == 300000
    assert type(authority.balance_paise) is int


def test_the_card_is_read_by_hmac_so_the_code_is_never_a_key():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_card(cards)
    provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    reads = [kwargs["Key"][gc.KEY_ATTRIBUTE] for name, kwargs in cards.calls
             if name == "get_item"]
    assert reads == [gc.PREFIX_CARD + gc.code_hash(CARD_CODE, pepper=PEPPER)]
    assert all(CARD_CODE not in key for key in reads)


def test_an_unknown_card_and_a_malformed_code_both_report_invalid():
    coupons, cards = coupons_table(), gift_cards_table()
    bound = provider(coupons, cards)
    for code in ("WDGC9999NOSUCH99", "short", "", None):
        authority = bound.read_gift_card(code=code, cart_ref=CART_REF)
        assert (authority.usable, authority.reason) == (False, redemption.GIFT_CARD_INVALID)
        assert authority.balance_paise == 0


def test_a_disabled_card_is_ineligible_and_an_expired_one_is_expired():
    coupons, cards = coupons_table(), gift_cards_table()
    issued = issue_card(cards)
    gc.disable(cards, code_hash=issued["codeHash"], clock=clock(NOW))
    disabled = provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    assert (disabled.usable, disabled.reason) == (False, redemption.GIFT_CARD_INELIGIBLE)

    expiring = gift_cards_table()
    issue_card(expiring, code="WDGC0000TEST0002",
               expires_at_ms=(NOW + 100) * 1000)
    past = provider(coupons, expiring, now=NOW + 200).read_gift_card(
        code="WDGC0000TEST0002", cart_ref=CART_REF)
    assert (past.usable, past.reason) == (False, redemption.GIFT_CARD_EXPIRED)


def test_a_zero_balance_card_is_reported_usable_so_redemption_owns_the_verdict():
    """`verify_gift_card` already answers `INSUFFICIENT_BALANCE` for a usable card with nothing
    on it. Deciding it here as well would be a second place that rules on whether a balance is
    spendable, and the two would eventually disagree."""
    coupons, cards = coupons_table(), gift_cards_table()
    issued = issue_card(cards, value_paise=300000)
    # A fully spent card, constructed directly on the fake: `issue` cannot mint a zero balance,
    # and driving a real redemption here would test the ledger rather than the binding.
    cards.rows[issued["card"][gc.KEY_ATTRIBUTE]]["balancePaise"] = 0

    authority = provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    assert (authority.usable, authority.balance_paise) == (True, 0)
    result = redemption.verify_gift_card(code=CARD_CODE, authoritative_total_paise=500000,
                                         cart_ref=CART_REF,
                                         provider=provider(coupons, cards))
    assert result.reason == redemption.GIFT_CARD_INSUFFICIENT_BALANCE
    assert result.redemption_paise == 0
    assert result.razorpay_payable_paise == 500000


def test_a_non_inr_card_is_refused_by_an_explicit_currency_comparison():
    """Compared explicitly, never inferred from the amount. An amount tells you a magnitude."""
    coupons, cards = coupons_table(), gift_cards_table()
    issued = issue_card(cards)
    cards.rows[issued["card"][gc.KEY_ATTRIBUTE]]["currency"] = "USD"
    authority = provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    assert (authority.usable, authority.reason) == (False, redemption.GIFT_CARD_INELIGIBLE)


def test_an_integral_decimal_balance_converts_and_a_fractional_one_is_refused():
    coupons, cards = coupons_table(), gift_cards_table()
    issued = issue_card(cards)
    key = issued["card"][gc.KEY_ATTRIBUTE]
    cards.rows[key]["balancePaise"] = Decimal("300000")
    assert provider(coupons, cards).read_gift_card(
        code=CARD_CODE, cart_ref=CART_REF).balance_paise == 300000
    cards.rows[key]["balancePaise"] = Decimal("300000.5")
    with pytest.raises(gc.GiftCardValidationError):
        provider(coupons, cards).read_gift_card(code=CARD_CODE, cart_ref=CART_REF)


def test_the_pepper_is_read_at_request_time_and_not_cached_on_the_instance():
    """A module-scope or constructor-time secret read is frozen into a warm Lambda sandbox and
    survives a rotation. So the reader must be called on EVERY request, and the count is the
    only honest way to assert it."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_card(cards)
    reads = []

    def counting_reader(secret_id):
        reads.append(secret_id)
        return {gc.PEPPER_FIELD: PEPPER}

    bound = srp.StoreRedemptionProvider(coupons_table=coupons, gift_cards_table=cards,
                                        secret_reader=counting_reader, clock=clock())
    assert reads == []  # constructing it reads nothing
    bound.read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    bound.read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
    assert reads == [gc.SECRET_ID, gc.SECRET_ID]


def test_no_gift_card_code_reaches_a_log_record(caplog):
    """Asserted against captured records, not by reading the source. A card is a bearer secret;
    a coupon code is broadcast marketing material and is logged in full on purpose."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_card(cards)
    issue_coupon(coupons)
    bound = provider(coupons, cards)
    with caplog.at_level(logging.DEBUG):
        bound.read_gift_card(code=CARD_CODE, cart_ref=CART_REF)
        bound.read_gift_card(code="WDGC9999NOSUCH99", cart_ref=CART_REF)
        bound.validate_coupon(code="SAVE1000",
                              collection_before_discount_paise=COLLECTION_PAISE,
                              cart_ref=CART_REF)
    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert CARD_CODE not in emitted
    assert CARD_CODE[-4:] not in emitted
    assert gc.code_hash(CARD_CODE, pepper=PEPPER) not in emitted
    assert PEPPER not in emitted
    # And the coupon code IS there, so the one correlation id this path has was not masked away.
    assert "SAVE1000" in emitted


# ── the composed order: D1 and M6 ─────────────────────────────────────────────

def test_the_composed_order_is_coupon_then_fee_then_gift_card():
    """Coupon first (a price change feeding the fee calculator), gift card last (tender off the
    final total). In that order the gift card cannot reduce taxable value, which is the whole
    reason the order is not negotiable."""
    coupons, cards = coupons_table(), gift_cards_table()
    issue_coupon(coupons)
    issue_card(cards, value_paise=300000)
    bound = provider(coupons, cards)

    applied = redemption.apply_coupon(code="SAVE1000",
                                      collection_before_discount_paise=COLLECTION_PAISE,
                                      cart_ref=CART_REF, provider=bound)
    assert applied.applied is True
    assert applied.discount_paise == 100000
    assert applied.discounted_collection_paise == COLLECTION_PAISE - 100000

    # The fee and its GST are computed on the DISCOUNTED collection, so a smaller cart genuinely
    # costs a smaller fee. Compared against the undiscounted quote to make that visible.
    quote = cp.compute_quote(applied.discounted_collection_paise)
    gross = cp.compute_quote(COLLECTION_PAISE)
    assert quote.convenience_fee_paise < gross.convenience_fee_paise
    assert quote.convenience_gst_paise < gross.convenience_gst_paise
    assert quote.total_payable_paise == (applied.discounted_collection_paise
                                         + quote.convenience_fee_paise
                                         + quote.convenience_gst_paise)

    verified = redemption.verify_gift_card(
        code=CARD_CODE, authoritative_total_paise=quote.total_payable_paise,
        cart_ref=CART_REF, provider=bound)
    assert verified.applied is True
    assert verified.redemption_paise == 300000
    payable = redemption.build_payable(verified)

    # M6, exactly.
    assert (payable.redemption_paise + payable.razorpay_payable_paise
            == payable.authoritative_total_paise == quote.total_payable_paise)
    assert payable.requires_gateway is True
    # The gift card did NOT reduce the taxable value: the GST on the fee is the one computed
    # before the card was considered.
    assert quote.convenience_gst_paise == cp.compute_quote(
        applied.discounted_collection_paise).convenience_gst_paise

    for value in (applied.discount_paise, applied.discounted_collection_paise,
                  quote.convenience_fee_paise, quote.convenience_gst_paise,
                  quote.total_payable_paise, verified.redemption_paise,
                  verified.razorpay_payable_paise, payable.razorpay_payable_paise,
                  payable.redemption_paise, payable.authoritative_total_paise):
        assert type(value) is int


def test_a_card_that_covers_the_whole_total_leaves_nothing_for_the_gateway():
    coupons, cards = coupons_table(), gift_cards_table()
    issue_card(cards, value_paise=9_000_000)
    quote = cp.compute_quote(COLLECTION_PAISE)
    verified = redemption.verify_gift_card(
        code=CARD_CODE, authoritative_total_paise=quote.total_payable_paise,
        cart_ref=CART_REF, provider=provider(coupons, cards))
    payable = redemption.build_payable(verified)
    assert payable.razorpay_payable_paise == 0
    assert payable.fully_covered is True
    assert payable.requires_gateway is False
    assert payable.redemption_paise == quote.total_payable_paise


# ── the provider's emptiness is the guarantee ─────────────────────────────────

def _provider_class() -> ast.ClassDef:
    return next(node for node in ast.walk(TREE)
                if isinstance(node, ast.ClassDef) and node.name == "StoreRedemptionProvider")


def test_the_provider_computes_no_amount_of_its_own():
    """No arithmetic inside the class, asserted over the AST.

    The one permitted operator is the `* 1000` that converts the injected epoch SECONDS clock to
    the milliseconds `assert_spendable` compares against. That is a unit conversion on a
    timestamp, not money, so it is allowed by name rather than by accident - any other
    `BinOp` fails here.
    """
    operations = [node for node in ast.walk(_provider_class())
                  if isinstance(node, (ast.BinOp, ast.AugAssign))]
    for node in operations:
        assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult), ast.dump(node)
        assert isinstance(node.right, ast.Constant) and node.right.value == 1000, \
            ast.dump(node)


def test_the_provider_module_constructs_no_float():
    assert "float(" not in SOURCE
    assert not [node for node in ast.walk(TREE)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "float"]


def test_the_provider_holds_no_boto3_client_and_builds_no_table():
    """Both tables and the secret reader are injected, so there is nothing ambient to mock and
    nothing that can read a secret at import."""
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("boto3", "botocore", "os"):
        assert not any(name == forbidden or name.startswith(forbidden + ".")
                       for name in imported), f"the provider imports {forbidden}"
    # The import ban above is the gate; these catch a direct call written without an import.
    # `boto3` is not in this list because the module docstring says the word while explaining
    # why there is none, and a text ban would make that explanation unwriteable.
    for marker in ("get_secret_value", "SecretId", "boto3.client", "boto3.resource",
                   ".Table("):
        assert marker not in SOURCE, f"the provider mentions {marker}"


def test_the_provider_is_the_only_concrete_redemption_provider_under_amplify():
    """One system means one implementation. A second provider is how two discount answers start
    disagreeing, so its absence is a gate rather than a convention."""
    implementations = []
    for path in sorted((ROOT / "amplify").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "def validate_coupon" not in text or "def read_gift_card" not in text:
            continue
        if path.name == "redemption.py":
            continue  # the Protocol itself
        implementations.append(path.relative_to(ROOT).as_posix())
    assert implementations == [
        "amplify/functions/shared/lambda_utils/ecommerce/store_redemption_provider.py"]
