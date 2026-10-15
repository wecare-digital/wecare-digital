"""Section 2 coupon + gift-card redemption authority, built but gated OFF.

These drive the ACTUAL redemption functions (``redemption.apply_coupon`` /
``redemption.verify_gift_card`` / ``redemption.reserve_redemption`` and the ``order_keys``
reservation primitives) against the honest in-memory DynamoDB fake the rest of the suite uses,
with the coupon/gift-card provider fully stubbed - no live provider call. They cover every
gift-card edge case Section 2 lists (partial / full / zero-remaining / invalid / expired /
insufficient / duplicate / concurrent / rollback / refund / reconciliation) and the coupon states,
and they prove the server-authoritative, never-trust-the-browser, integer-paise invariants.

REVERT-CHECKS (named in their docstrings):
  * ``test_revert_check_browser_discount_is_never_trusted`` fails if a browser-supplied coupon
    discount is ever used instead of the provider's authoritative figure.
  * ``test_revert_check_gift_card_zero_remaining_still_gated`` fails if a fully gift-card-covered
    order is treated as a captured payment / forced payable instead of staying gated.
  * ``test_revert_check_concurrent_card_cannot_double_spend`` fails if the atomic cross-attempt
    guard is reverted so one card can fund two live attempts.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import redemption as rd  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
CART_REF = 'cart-abc'


def _keys():
    return FakeDynamo({KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)


# ── a stub provider implementing the abstract seam ─────────────────────────────────

class StubProvider:
    """A test double for the abstract RedemptionProvider. Carries NO vendor name."""

    def __init__(self, *, coupon=None, gift_card=None):
        self._coupon = coupon
        self._gift_card = gift_card
        self.coupon_calls = []
        self.gift_card_calls = []

    def validate_coupon(self, *, code, collection_before_discount_paise, cart_ref):
        self.coupon_calls.append((code, collection_before_discount_paise, cart_ref))
        return self._coupon

    def read_gift_card(self, *, code, cart_ref):
        self.gift_card_calls.append((code, cart_ref))
        return self._gift_card


# ── COUPON: server-authoritative price change feeding the calculator ───────────────

def test_coupon_applies_provider_discount_and_reduces_the_collection():
    provider = StubProvider(coupon=rd.CouponAuthority(valid=True, reason=rd.COUPON_APPLIED,
                                                      discount_paise=10000))
    result = rd.apply_coupon(code='SAVE100', collection_before_discount_paise=100000,
                             cart_ref=CART_REF, provider=provider)
    assert result.applied
    assert result.reason == rd.COUPON_APPLIED
    assert result.discount_paise == 10000
    # The DISCOUNTED collection feeds checkout_pricing - fee + GST compute on 90000, not 100000.
    assert result.discounted_collection_paise == 90000


def test_coupon_invalid_expired_ineligible_states_leave_the_collection_unchanged():
    for reason in (rd.COUPON_INVALID, rd.COUPON_EXPIRED, rd.COUPON_INELIGIBLE):
        provider = StubProvider(coupon=rd.CouponAuthority(valid=False, reason=reason))
        result = rd.apply_coupon(code='X', collection_before_discount_paise=100000,
                                 cart_ref=CART_REF, provider=provider)
        assert not result.applied
        assert result.reason == reason
        assert result.discount_paise == 0
        assert result.discounted_collection_paise == 100000  # unchanged


def test_coupon_discount_cannot_make_the_cart_cost_less_than_zero():
    # A provider discount larger than the collection is clamped to the collection.
    provider = StubProvider(coupon=rd.CouponAuthority(valid=True, reason=rd.COUPON_APPLIED,
                                                      discount_paise=250000))
    result = rd.apply_coupon(code='HUGE', collection_before_discount_paise=100000,
                             cart_ref=CART_REF, provider=provider)
    assert result.discount_paise == 100000
    assert result.discounted_collection_paise == 0


def test_empty_coupon_code_is_invalid_without_calling_the_provider():
    provider = StubProvider(coupon=rd.CouponAuthority(valid=True, reason=rd.COUPON_APPLIED,
                                                      discount_paise=10000))
    result = rd.apply_coupon(code='', collection_before_discount_paise=100000,
                             cart_ref=CART_REF, provider=provider)
    assert result.reason == rd.COUPON_INVALID
    assert provider.coupon_calls == []


def test_revert_check_browser_discount_is_never_trusted():
    """REVERT-CHECK: fails if a browser-supplied discount is ever trusted over the provider's.

    apply_coupon takes NO browser discount argument - the only discount it can apply is the
    provider's authoritative ``discount_paise``. We prove it: a provider that reports a SMALL
    authoritative discount must win even though a caller might wish for a larger one. If someone
    reworked apply_coupon to accept and trust a client amount, this test's signature-level
    assertion (no client-discount parameter) and the value assertion would both have to be
    weakened, which is the regression this guards.
    """
    import inspect
    sig = inspect.signature(rd.apply_coupon)
    # No parameter through which the browser could inject a TRUSTED discount AMOUNT. The only
    # "discount" word allowed is the collection-BEFORE-discount input, which is a cart total, not a
    # discount figure. A parameter like ``discount_paise`` / ``client_discount`` would be the
    # regression this guards.
    banned = {'discount_paise', 'client_discount', 'discount', 'browser_discount',
              'applied_discount_paise'}
    assert not (set(sig.parameters) & banned), \
        'apply_coupon must not accept a browser-supplied discount amount'
    # The provider's authoritative figure is the only discount applied.
    provider = StubProvider(coupon=rd.CouponAuthority(valid=True, reason=rd.COUPON_APPLIED,
                                                      discount_paise=500))
    result = rd.apply_coupon(code='SAVE', collection_before_discount_paise=100000,
                             cart_ref=CART_REF, provider=provider)
    assert result.discount_paise == 500  # provider authority, never a browser figure
    assert result.discounted_collection_paise == 99500


def test_coupon_rejects_non_inr_currency():
    provider = StubProvider(coupon=rd.CouponAuthority(valid=True, reason=rd.COUPON_APPLIED))
    with pytest.raises(rd.RedemptionError) as exc:
        rd.apply_coupon(code='X', collection_before_discount_paise=100,
                        cart_ref=CART_REF, provider=provider, currency='USD')
    assert exc.value.reason == 'UNSUPPORTED_CURRENCY'


# ── GIFT CARD: verified tender subtracted from the final payable ────────────────────

def _gc(reason, balance=0):
    usable = reason == rd.GIFT_CARD_APPLIED
    return rd.GiftCardAuthority(usable=usable, reason=reason, balance_paise=balance)


def test_gift_card_partial_redemption_leaves_a_positive_razorpay_payable():
    # balance < total -> redeem the balance, Razorpay collects the rest. Integer paise.
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=40000))
    result = rd.verify_gift_card(code='GC1', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.applied
    assert result.redemption_paise == 40000
    assert result.razorpay_payable_paise == 121481 - 40000  # 81481
    assert not result.fully_covered


def test_gift_card_fixture_integer_paise_exactness_against_the_121481_total():
    # The checkout_pricing fixture total is 121481 paise. A gift card of 21481 paise leaves exactly
    # 100000 paise - an exact integer-paise subtraction, no float, no fractional paise.
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=21481))
    result = rd.verify_gift_card(code='GC', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.redemption_paise == 21481
    assert result.razorpay_payable_paise == 100000
    assert result.redemption_paise + result.razorpay_payable_paise == 121481


def test_gift_card_full_redemption_leaves_zero_remaining():
    # balance >= total -> redeem the total, Razorpay payable is ZERO.
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=200000))
    result = rd.verify_gift_card(code='BIG', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.applied
    assert result.redemption_paise == 121481  # capped at the total, not the balance
    assert result.razorpay_payable_paise == 0
    assert result.fully_covered


def test_gift_card_exact_balance_covers_the_total_exactly():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=121481))
    result = rd.verify_gift_card(code='EXACT', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.redemption_paise == 121481
    assert result.razorpay_payable_paise == 0


@pytest.mark.parametrize('reason', [rd.GIFT_CARD_INVALID, rd.GIFT_CARD_EXPIRED,
                                    rd.GIFT_CARD_INELIGIBLE])
def test_gift_card_invalid_expired_ineligible_redeem_nothing(reason):
    provider = StubProvider(gift_card=_gc(reason))
    result = rd.verify_gift_card(code='X', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert not result.applied
    assert result.reason == reason
    assert result.redemption_paise == 0
    assert result.razorpay_payable_paise == 121481  # full amount still owed


def test_gift_card_zero_balance_is_insufficient_balance():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=0))
    result = rd.verify_gift_card(code='EMPTY', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.reason == rd.GIFT_CARD_INSUFFICIENT_BALANCE
    assert result.redemption_paise == 0
    assert result.razorpay_payable_paise == 121481


def test_gift_card_empty_code_is_invalid_without_calling_the_provider():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=100))
    result = rd.verify_gift_card(code='', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    assert result.reason == rd.GIFT_CARD_INVALID
    assert provider.gift_card_calls == []


def test_gift_card_rejects_zero_total():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=100))
    with pytest.raises(rd.RedemptionError):
        rd.verify_gift_card(code='X', authoritative_total_paise=0,
                            cart_ref=CART_REF, provider=provider)


# ── build_payable: the reduced / zero-remaining payable, still gated ────────────────

def test_build_payable_for_a_partial_redemption_requires_a_gateway():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=40000))
    result = rd.verify_gift_card(code='GC', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    payable = rd.build_payable(result)
    assert payable.razorpay_payable_paise == 81481
    assert payable.requires_gateway
    assert not payable.fully_covered


def test_revert_check_gift_card_zero_remaining_still_gated():
    """REVERT-CHECK: fails if a fully gift-card-covered order is treated as payable/captured.

    A zero-remaining order must create NO gateway order (requires_gateway is False) yet is NOT a
    captured payment - it still has to settle through the authoritative verification path, never
    auto-complete from browser state. If someone made a zero payable "requires_gateway" True (to
    force a gateway order) OR made it look like a completed payment, this fails.
    """
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=500000))
    result = rd.verify_gift_card(code='FULL', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    payable = rd.build_payable(result)
    assert payable.razorpay_payable_paise == 0
    assert payable.requires_gateway is False       # no gateway order for a zero payable
    assert payable.fully_covered is True           # but it IS a real (gift-card-covered) order
    # And it reconciles exactly: a zero payable is still authoritative, never fabricated.
    assert payable.redemption_paise == 121481
    assert payable.redemption_paise + payable.razorpay_payable_paise == 121481


def test_build_payable_refuses_a_non_applied_result():
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_EXPIRED))
    result = rd.verify_gift_card(code='X', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    with pytest.raises(rd.RedemptionError):
        rd.build_payable(result)


# ── reservation / rollback / concurrency / reconciliation (atomic, double-spend-safe)

def _apply(total=121481, balance=40000):
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=balance))
    return rd.verify_gift_card(code='GC', authoritative_total_paise=total,
                               cart_ref=CART_REF, provider=provider)


def test_reserve_redemption_stores_authoritative_paise_for_an_attempt():
    table = _keys()
    result = _apply()
    row, reason = rd.reserve_redemption(keys_table=table, code='GC',
                                        payment_attempt_id='att-1', result=result)
    assert reason == rd.GIFT_CARD_APPLIED
    assert row['state'] == 'RESERVED'
    assert row['redemptionPaise'] == 40000
    assert row['razorpayPayablePaise'] == 81481
    assert row['authoritativeTotalPaise'] == 121481


def test_duplicate_reservation_for_same_attempt_resumes_without_double_spending():
    table = _keys()
    result = _apply()
    first, r1 = rd.reserve_redemption(keys_table=table, code='GC',
                                      payment_attempt_id='att-1', result=result)
    second, r2 = rd.reserve_redemption(keys_table=table, code='GC',
                                       payment_attempt_id='att-1', result=result)
    assert r1 == rd.GIFT_CARD_APPLIED
    assert r2 == rd.GIFT_CARD_DUPLICATE
    # Same figures resumed, NOT a second subtraction.
    assert second['redemptionPaise'] == first['redemptionPaise'] == 40000


def test_revert_check_concurrent_card_cannot_double_spend():
    """REVERT-CHECK: fails if the atomic cross-attempt guard is reverted.

    The SAME card is applied to TWO different live attempts. The first reserves; the second must be
    refused with CONCURRENT - one card funds at most one in-flight checkout. If the cross-attempt
    lock is removed, the second reservation succeeds and this fails.
    """
    table = _keys()
    result = _apply()
    _, r1 = rd.reserve_redemption(keys_table=table, code='GC',
                                  payment_attempt_id='att-A', result=result)
    _, r2 = rd.reserve_redemption(keys_table=table, code='GC',
                                  payment_attempt_id='att-B', result=result)
    assert r1 == rd.GIFT_CARD_APPLIED
    assert r2 == rd.GIFT_CARD_CONCURRENT
    # Only ONE live reservation exists for the card.
    assert order_keys.gift_card_is_reserved_elsewhere(
        table, card_fingerprint=rd.card_fingerprint('GC'), payment_attempt_id='att-B') is True


def test_release_rollback_frees_the_card_for_a_fresh_attempt():
    # A failed Razorpay leg after reservation releases it, so the balance is not stranded and the
    # card can be redeemed again on a new attempt.
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    released = rd.release_redemption(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert released is True
    # The card is free again: a different attempt can now reserve it.
    _, r2 = rd.reserve_redemption(keys_table=table, code='GC',
                                  payment_attempt_id='att-B', result=result)
    assert r2 == rd.GIFT_CARD_APPLIED


def test_double_release_is_a_harmless_no_op():
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    assert rd.release_redemption(keys_table=table, code='GC', payment_attempt_id='att-A') is True
    assert rd.release_redemption(keys_table=table, code='GC', payment_attempt_id='att-A') is False


def test_commit_redemption_is_exactly_once_per_payment():
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    first = rd.commit_redemption(keys_table=table, code='GC', payment_attempt_id='att-A',
                                 provider_payment_id='pay_123', redemption_paise=40000)
    # A redelivered webhook/callback for the SAME payment commits nothing twice.
    second = rd.commit_redemption(keys_table=table, code='GC', payment_attempt_id='att-A',
                                  provider_payment_id='pay_123', redemption_paise=40000)
    assert first is True
    assert second is False
    row = rd.reconcile_reservation(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert row['state'] == 'COMMITTED'
    assert row['providerPaymentId'] == 'pay_123'


def test_zero_remaining_commit_uses_the_attempt_marker():
    # A fully-covered order has no Razorpay payment id, so the commit is keyed on the attempt and is
    # still exactly-once.
    table = _keys()
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_APPLIED, balance=500000))
    result = rd.verify_gift_card(code='FULL', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    rd.reserve_redemption(keys_table=table, code='FULL', payment_attempt_id='att-Z', result=result)
    first = rd.commit_redemption(keys_table=table, code='FULL', payment_attempt_id='att-Z',
                                 provider_payment_id='', redemption_paise=121481)
    second = rd.commit_redemption(keys_table=table, code='FULL', payment_attempt_id='att-Z',
                                  provider_payment_id='', redemption_paise=121481)
    assert first is True
    assert second is False


def test_refund_releases_a_live_reserved_redemption_with_the_refunded_reason():
    # refund_redemption is release_redemption with reason=REFUNDED, and release is CONDITIONAL on
    # the row still being RESERVED. Against a LIVE (reserved, never committed) row it succeeds and
    # stamps releaseReason=REFUNDED. This is the only state the current refund path can act on; the
    # committed-row behaviour is asserted separately below.
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    refunded = rd.refund_redemption(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert refunded is True
    row = rd.reconcile_reservation(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert row['state'] == 'RELEASED'
    assert row['releaseReason'] == 'REFUNDED'


def test_refund_on_a_committed_redemption_is_a_conditional_no_op_and_leaves_it_committed():
    """The TRUE behaviour of refund_redemption against a COMMITTED row (the real refund path).

    This commits a reservation first (reserve -> commit_redemption) so the row is genuinely
    COMMITTED, then calls refund_redemption and asserts the actual code behaviour rather than an
    aspirational one. Because refund_redemption delegates to release_gift_card_redemption, whose
    DynamoDB write is CONDITIONAL on ``state == RESERVED``, a COMMITTED row cannot be released: the
    conditional write fails and the function returns False. The row stays COMMITTED, keeps its
    providerPaymentId, and is NEVER stamped RELEASED/REFUNDED.

    DOCUMENTED GAP (see findings and the coupon-giftcard runbook): the runbook describes a refund as
    "RELEASES a committed redemption back to the card", but the current code's refund path can only
    act on a still-RESERVED row, so a refund AFTER capture/commit is a no-op at this layer and does
    NOT record a REFUNDED release on the committed row. The actual provider-side balance credit is
    the concrete binding's job (deferred, BLOCKED-ON-ENVIRONMENT). This test pins the real behaviour
    so a future change that makes committed-row refund restore the card is a DELIBERATE, visible
    edit to money code, not a silent one. Money behaviour is NOT changed here to make a test green.
    """
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    committed = rd.commit_redemption(keys_table=table, code='GC', payment_attempt_id='att-A',
                                     provider_payment_id='pay_123', redemption_paise=40000)
    assert committed is True
    row = rd.reconcile_reservation(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert row['state'] == 'COMMITTED'  # the row really is committed before we try to refund it

    # The real refund-of-committed path: a conditional no-op, not a release back to the card.
    refunded = rd.refund_redemption(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert refunded is False  # the RESERVED-conditional write cannot touch a COMMITTED row

    # The committed row is untouched: still COMMITTED, still carrying its payment id, never REFUNDED.
    row = rd.reconcile_reservation(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert row['state'] == 'COMMITTED'
    assert row['providerPaymentId'] == 'pay_123'
    assert row.get('releaseReason') != 'REFUNDED'
    assert 'releaseReason' not in row or row['releaseReason'] != 'REFUNDED'


def test_reconcile_reservation_reads_the_stored_authoritative_row():
    table = _keys()
    result = _apply()
    rd.reserve_redemption(keys_table=table, code='GC', payment_attempt_id='att-A', result=result)
    row = rd.reconcile_reservation(keys_table=table, code='GC', payment_attempt_id='att-A')
    assert row is not None
    # Reconciliation re-derives the figures from the STORED row, never from the browser.
    assert row['redemptionPaise'] == 40000
    assert row['razorpayPayablePaise'] == 81481
    # No reservation for an unknown attempt.
    assert rd.reconcile_reservation(keys_table=table, code='GC',
                                    payment_attempt_id='nope') is None


def test_card_fingerprint_does_not_reveal_the_code():
    fp = rd.card_fingerprint('SECRET-CARD-1234')
    assert 'SECRET' not in fp
    assert '1234' not in fp
    assert len(fp) == 64  # sha256 hex
    # Stable: same code -> same fingerprint (so two clicks collide on the same reservation key).
    assert fp == rd.card_fingerprint('SECRET-CARD-1234')


def test_reserve_refuses_a_non_applied_result():
    table = _keys()
    provider = StubProvider(gift_card=_gc(rd.GIFT_CARD_EXPIRED))
    result = rd.verify_gift_card(code='X', authoritative_total_paise=121481,
                                 cart_ref=CART_REF, provider=provider)
    with pytest.raises(rd.RedemptionError):
        rd.reserve_redemption(keys_table=table, code='X', payment_attempt_id='att', result=result)
