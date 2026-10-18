"""Coupon redemption authority.

Gift cards are retired. These tests cover the surviving server-authoritative
coupon path only: provider-owned discounts, integer-paise clamping, invalid
states, and the rule that browser input never supplies the discount amount.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))

from lambda_utils.ecommerce import redemption as rd  # noqa: E402

CART_REF = 'cart-abc'


# ── a stub provider implementing the abstract seam ─────────────────────────────────

class StubProvider:
    """A test double for the coupon RedemptionProvider."""

    def __init__(self, *, coupon=None):
        self._coupon = coupon
        self.coupon_calls = []

    def validate_coupon(self, *, code, collection_before_discount_paise, cart_ref):
        self.coupon_calls.append((code, collection_before_discount_paise, cart_ref))
        return self._coupon


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
