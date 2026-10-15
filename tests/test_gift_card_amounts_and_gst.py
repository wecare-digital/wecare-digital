"""A gift card is a PAYMENT METHOD, not a discount: the fee basis and the two-leg split.

Under GST a voucher is CONSIDERATION, not a reduction in the value of supply. The customer paid real
money for the card; redeeming it is tendering that money. So the taxable supply stays at its full
value and the 2.5% convenience fee and its 18% GST are computed on the FULL collection total - never
on the post-gift-card remainder. The worked example is `2500` and `450`; the wrong version is `1574`
and `283`, and it is recorded here so it is recognisable in review.

The gift card is applied strictly AFTER `checkout_pricing.compute_quote`, by
`redemption.verify_gift_card` against our own ledger (`store_redemption_provider` over
`gift_card_store`), which splits the quote's `total_payable_paise` into a gift-card leg and a
Razorpay leg.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402
from lambda_utils.ecommerce import redemption  # noqa: E402
from lambda_utils.ecommerce import store_redemption_provider as srp  # noqa: E402

PEPPER = "pepper-for-tests-only"
CODE = "WDGC0000TEST0001"
NOW = 1_700_000_000
CART_REF = "WD-PAY-TEST-REF-GST"

#: The section 2 worked example, in integer paise throughout.
COLLECTION = 100000          # a 1000.00 collection
FEE = 2500                   # round_half_up(100000 * 250 / 10000)
GST = 450                    # round_half_up(  2500 * 1800 / 10000)
PAYABLE = 102950             # 100000 + 2500 + 450
REDEEM = 40000               # a 400.00 card
PAY_NOW = 62950              # 102950 - 40000

#: The figures the WRONG basis produces - the fee on `102950 - 40000` rather than on the full
#: collection. Recorded so a review can recognise them rather than having to re-derive them.
WRONG_FEE = 1574
WRONG_GST = 283


def quote(collection: int = COLLECTION):
    return checkout_pricing.compute_quote(collection)


def verified_redemption(total_payable_paise: int, *, balance_paise: int = REDEEM):
    """A card issued on our own ledger, verified through the one concrete provider."""
    cards = FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                      indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})
    coupons = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                        indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    gc.issue(cards, initial_value_paise=balance_paise, pepper=PEPPER, code=CODE,
             clock=lambda: NOW)
    provider = srp.StoreRedemptionProvider(
        coupons_table=coupons, gift_cards_table=cards,
        secret_reader=lambda _secret_id: {gc.PEPPER_FIELD: PEPPER}, clock=lambda: NOW + 10)
    return redemption.verify_gift_card(code=CODE, authoritative_total_paise=total_payable_paise,
                                       cart_ref=CART_REF, provider=provider)


# ── 87: the fee basis ─────────────────────────────────────────────────────────

def test_the_fee_basis_is_the_full_collection_and_the_worked_example_is_exact():
    """The fee basis is a GST question against seller GSTIN 19AAFFW7196L1Z8, not an implementation
    detail, and it is settled here as the FULL collection total."""
    computed = quote()
    assert computed.collection_before_convenience_paise == COLLECTION
    assert computed.convenience_fee_paise == FEE
    assert computed.convenience_gst_paise == GST
    assert computed.total_payable_paise == PAYABLE

    # The wrong basis, computed explicitly, so the two are not confusable in review.
    wrong = quote(PAYABLE - REDEEM)
    assert wrong.convenience_fee_paise == WRONG_FEE
    assert wrong.convenience_gst_paise == WRONG_GST
    assert (wrong.convenience_fee_paise, wrong.convenience_gst_paise) != (FEE, GST)
    assert checkout_pricing.SELLER_GSTIN == "19AAFFW7196L1Z8"


# ── 88 / 89 / 90: the quote is untouched ──────────────────────────────────────

def test_the_gift_card_does_not_enter_the_quote():
    """`compute_quote` receives the full collection and is NOT changed. The gift card is applied
    strictly AFTER the quote, by splitting `total_payable_paise` into two legs."""
    computed = quote()
    result = verified_redemption(computed.total_payable_paise)
    assert result.applied
    assert result.redemption_paise == REDEEM
    assert quote() == computed
    # Nothing in the quote mentions a gift card, which is what makes it re-derivable.
    assert not [field for field in vars(computed) if "gift" in field.lower()]


def test_the_two_legs_sum_exactly_to_the_total_payable():
    """Exactly, in paise. The one new identity DECISION 2 introduces."""
    computed = quote()
    payable = redemption.build_payable(verified_redemption(computed.total_payable_paise))
    assert payable.redemption_paise + payable.razorpay_payable_paise == computed.total_payable_paise
    assert payable.razorpay_payable_paise == PAY_NOW
    assert type(payable.razorpay_payable_paise) is int
    assert payable.requires_gateway is True


def test_the_quote_still_reconciles():
    """`collection + fee + gst == total`, re-checked in `CheckoutQuote.__post_init__`, holds
    UNTOUCHED - because a gift card never enters the quote."""
    computed = quote()
    assert (computed.collection_before_convenience_paise + computed.convenience_fee_paise
            + computed.convenience_gst_paise) == computed.total_payable_paise
    assert computed.convenience_gst_split.total_paise == computed.convenience_gst_paise


def test_a_gift_card_is_tender_and_a_coupon_of_the_same_value_is_a_price_change():
    """The distinction decides the tax.

    A coupon lowers the collection BEFORE the quote, which legitimately lowers the fee basis. A gift
    card of the same face value lowers nothing in the quote: the collection, the fee and its GST are
    the full-basis figures, and the card only reduces what Razorpay collects. Treating the card as a
    discount would understate the taxable value on a document that has to be defensible.
    """
    as_price_change = quote(COLLECTION - REDEEM)
    assert as_price_change.convenience_fee_paise < FEE

    computed = quote()
    payable = redemption.build_payable(verified_redemption(computed.total_payable_paise))
    assert computed.collection_before_convenience_paise == COLLECTION
    assert (computed.convenience_fee_paise, computed.convenience_gst_paise) == (FEE, GST)
    assert payable.authoritative_total_paise == PAYABLE
    assert payable.razorpay_payable_paise == PAYABLE - REDEEM
