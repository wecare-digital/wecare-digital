"""A gift card is a PAYMENT METHOD, not a discount: the fee basis, the cap, and the six identities.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md`
sections 2 (DECISION 2 and the worked example), 4.1 (the split and the cap), 4.2 (the six
reconciliation identities), 4.4 (full cover is refused) and 4.5 (only `giftCards` is opened), and the
test list in section 9.1 (tests 87-100, including 95, 96, 97, 97a, 97b, 97c and 98).

Under GST a voucher is CONSIDERATION, not a reduction in the value of supply. The customer paid real
money for the card; redeeming it is tendering that money. So the taxable supply stays at its full
value and the 2.5% convenience fee and its 18% GST are computed on the FULL collection total - never
on the post-gift-card remainder. The worked example is `2500` and `450`; the wrong version is `1574`
and `283`, and it is recorded here so it is recognisable in review.

TWO TESTS ARE `xfail(strict=True)`, AND ONE THE BRIEF NAMED IS DELIBERATELY NOT
-------------------------------------------------------------------------------
Tests 87 and 99 are marked against SEAM-G1: `cart_v2.calculate` refuses `giftCards` today, in the
same check that refuses `memberships` and `subscriptionCharges`, and that module belongs to the
cart_v2 workstream. DECISION 8: marked, never weakened, so each converts from pending to passing the
moment the seam lands and fails loudly if somebody satisfies it by lowering the bar. Both have an
UNCONDITIONAL companion asserting the half that does not depend on the seam.

Test 100 is NOT marked, and the reason is the same one that left the coupon suite's test 52a
unmarked. It asserts that `memberships` and `subscriptionCharges` are STILL refused - a property
that holds today and must never break. Marking it `strict=True` would make it xpass immediately,
which is a failure under this feature's own acceptance criterion, and worse it would switch off the
one assertion that fires if SEAM-G1 opens the gate for all three instead of narrowing it to one. The
design says as much in its own words: that refusal "must keep passing unchanged".
"""

from __future__ import annotations

import ast
import copy
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402
from lambda_utils.ecommerce import money  # noqa: E402

STORE_MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_store.py"
STORE_TREE = ast.parse(STORE_MODULE.read_text(encoding="utf-8"), filename=str(STORE_MODULE))

PEPPER = "pepper-for-tests-only"
CODE = "WDGC0000TEST0001"
NOW = 1_700_000_000

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

SEAM_G1 = ("SEAM-G1: cart_v2.calculate refuses giftCards in the same check that refuses "
           "memberships and subscriptionCharges, and cart_v2.py belongs to the cart_v2 "
           "workstream. Marked rather than weakened per DECISION 8, so it converts from pending "
           "to passing the moment the seam lands and fails loudly if somebody satisfies it by "
           "lowering the bar.")


class Spy:
    """A Wix request callable that records every call. Zero calls is the assertion in 97a / 97b."""

    def __init__(self, response=None):
        self.response = response
        self.calls: list = []

    def __call__(self, path, method="GET", body=None, **kwargs):
        self.calls.append((path, method, body))
        return self.response


#: The section-2 worked example as a cart SUMMARY, inlined rather than read from the retired Wix
#: Cart V2 fixture. `gc.reconcile_with_wix` reads `cart["summary"]` (priceSummary + paymentSummary),
#: and that is all these native gift-card tests consume — a 1000.00 collection, a 400.00 gift card,
#: no discount, no tax, and `requiresPaymentAfterGiftCard` present and True.
_PARTIAL_CART = {
    "cart": {"id": "7a1cfeed-0000-4000-8000-00000000ca01"},
    "summary": {
        "priceSummary": {
            "subtotal": {"amount": "1000.00"},
            "discount": {"amount": "0"},
            "delivery": {"amount": "0"},
            "additionalFees": {"amount": "0"},
            "tax": {"amount": "0.00"},
            "total": {"amount": "1000.00"},
        },
        "paymentSummary": {
            "giftCards": [
                {"giftCardId": "bd000000-0000-4000-8000-0000000000c1",
                 "redeemAmount": {"amount": "400.00", "convertedAmount": "400.00"}},
            ],
            "memberships": [],
            "subscriptionCharges": [],
            "requiresPaymentAfterGiftCard": True,
            "totalAfterGiftCards": {"amount": "600.00"},
            "payNow": {"amount": "600.00"},
            "payLater": {"amount": "0.00"},
        },
    },
}


def partial_cart() -> dict:
    return copy.deepcopy(_PARTIAL_CART)


def quote(collection: int = COLLECTION):
    return checkout_pricing.compute_quote(collection)


def cards_table() -> FakeTable:
    return FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                    indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})


def digest() -> str:
    return gc.code_hash(CODE, pepper=PEPPER)


# ── 87: the fee basis ─────────────────────────────────────────────────────────

# The Wix-cart driver of the worked example (`CartV2(...).calculate`) was retired with the Wix cart
# model. The fee-basis money property it asserted is pinned natively, with no Wix cart, by its
# unconditional companion below.
def test_the_fee_basis_is_the_full_collection_and_the_worked_example_is_exact():
    """87's unconditional companion. The arithmetic needs no seam, and it is the half that matters:
    the fee basis is a GST question against seller GSTIN 19AAFFW7196L1Z8, not an implementation
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
    split = gc.split_payment(balance_paise=REDEEM, wix_collection_paise=COLLECTION,
                             total_payable_paise=computed.total_payable_paise,
                             requested_paise=REDEEM)
    unchanged = quote()
    assert computed == unchanged
    assert split["giftCardRedeemPaise"] == REDEEM
    # Nothing in the quote mentions a gift card, which is what makes it re-derivable.
    assert not [field for field in vars(computed) if "gift" in field.lower()]


def test_pay_now_plus_gift_card_equals_the_total_payable():
    """Exactly, in paise. The one new identity DECISION 2 introduces."""
    computed = quote()
    split = gc.split_payment(balance_paise=REDEEM, wix_collection_paise=COLLECTION,
                             total_payable_paise=computed.total_payable_paise,
                             requested_paise=REDEEM)
    assert split["payNowPaise"] + split["giftCardRedeemPaise"] == computed.total_payable_paise
    assert split["payNowPaise"] == PAY_NOW
    assert type(split["payNowPaise"]) is int


def test_the_quote_still_reconciles():
    """`collection + fee + gst == total`, re-checked in `CheckoutQuote.__post_init__`, holds
    UNTOUCHED - because a gift card never enters the quote."""
    computed = quote()
    assert (computed.collection_before_convenience_paise + computed.convenience_fee_paise
            + computed.convenience_gst_paise) == computed.total_payable_paise
    assert computed.convenience_gst_split.total_paise == computed.convenience_gst_paise


def test_a_gift_card_is_a_tender_line_not_a_discount_line():
    """The distinction decides the tax, and it is visible in WHERE the figure is read from.

    A coupon lands in `summary.priceSummary.discount` and lowers the collection, which legitimately
    lowers the fee basis. A gift card lands in `summary.paymentSummary.giftCards` and lowers nothing:
    the collection total is identical with and without it. A gift card appearing as a discount would
    understate the taxable value on a document that has to be defensible.
    """
    cart = partial_cart()
    prices = cart["summary"]["priceSummary"]
    payment = cart["summary"]["paymentSummary"]

    assert money.Money.from_wix(prices["total"]["amount"]).paise == COLLECTION
    assert money.Money.from_wix(prices["discount"]["amount"]).paise == 0, (
        "the gift card has been recorded as a discount, which understates the taxable value")
    assert money.Money.from_wix(
        payment["giftCards"][0]["redeemAmount"]["amount"]).paise == REDEEM

    # And our reconciliation reads the card from the PAYMENT summary, never from the price summary.
    reconcile = next(node for node in ast.walk(STORE_TREE)
                     if isinstance(node, ast.FunctionDef) and node.name == "reconcile_with_wix")
    rendered = ast.unparse(reconcile)
    assert '"giftCards"' in rendered or "'giftCards'" in rendered
    assert "discount" not in rendered


# ── 92 / 93: fail closed, and both totals ─────────────────────────────────────

def test_a_one_paise_disagreement_with_wix_fails_closed():
    """R6.2. A one-paise mismatch against the authoritative total must REFUSE the order rather than
    charge an amount nobody computed - so this is a refusal, and nothing is charged."""
    cart = partial_cart()
    computed = quote()
    for drift in (1, -1):
        with pytest.raises(gc.GiftCardValidationError) as refusal:
            gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM + drift,
                                  pay_now_paise=PAY_NOW - drift, quote=computed)
        assert refusal.value.code == "WIX_APPLIED_MISMATCH"

    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW + 1, quote=computed)
    assert refusal.value.code == "PAYABLE_MISMATCH"


def test_wix_pay_now_is_reconciled_against_both_totals():
    """Identities 2 and 4 use DIFFERENT totals and both are correct: Wix's `payNow` is against Wix's
    collection total, which excludes our convenience fee, while our `payNowPaise` is against the full
    payable, which includes it. Identity 6 pins the difference to exactly the fee and its GST."""
    cart = partial_cart()
    computed = quote()
    reconciled = gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                                       pay_now_paise=PAY_NOW, quote=computed)

    assert reconciled["wixAppliedPaise"] == REDEEM                              # 1
    assert reconciled["wixPayNowPaise"] + REDEEM == reconciled["wixCollectionPaise"]  # 2
    assert reconciled["wixPayNowPaise"] == COLLECTION - REDEEM                  # 3
    assert reconciled["payNowPaise"] + REDEEM == computed.total_payable_paise    # 4
    assert reconciled["payNowPaise"] >= gc.RAZORPAY_MIN_LEG_PAISE               # 5
    assert reconciled["payNowPaise"] - reconciled["wixPayNowPaise"] == FEE + GST  # 6
    assert reconciled["wixCollectionPaise"] != computed.total_payable_paise, (
        "the two totals must differ by the fee, or identity 6 is vacuous")


def test_every_wix_amount_goes_through_the_converter():
    """MEDIUM-11. Revision 2 compared a `ConvertedMoney` OBJECT against an `int` twice -
    always-false, so it would have failed ALWAYS rather than failing closed. Applying
    `Money.from_wix` is also what proves the field was a decimal STRING."""
    cart = partial_cart()
    payment = cart["summary"]["paymentSummary"]
    for raw in (payment["payNow"]["amount"], payment["giftCards"][0]["redeemAmount"]["amount"],
                cart["summary"]["priceSummary"]["total"]["amount"]):
        assert isinstance(raw, str), "a Wix money field is not a decimal string"
        assert type(money.Money.from_wix(raw).paise) is int

    # A numeric field is refused by `Money.from_wix` itself, which is the structural half.
    broken = partial_cart()
    broken["summary"]["paymentSummary"]["payNow"]["amount"] = 600.00
    with pytest.raises(ValueError):
        gc.reconcile_with_wix(broken["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW, quote=quote())


# ── 94 / 95: full cover is refused, and absence is False ──────────────────────

def test_requires_payment_after_gift_card_false_refuses_the_checkout():
    """Section 4.4. With no Razorpay capture there is NO provider readback at all - the entire
    authoritative verification path this system has is Razorpay's - so an order settled wholly on our
    own ledger, verified only by our own write, is a different trust model and is out of scope."""
    cart = partial_cart()
    cart["summary"]["paymentSummary"]["requiresPaymentAfterGiftCard"] = False
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW, quote=quote())
    assert refusal.value.code == "GIFT_CARD_COVERS_FULL_TOTAL"


def test_an_absent_requires_payment_after_gift_card_also_refuses():
    """MEDIUM-9's third part, and it is why the existing cart_v2 fixture that does not set the field
    still refuses after SEAM-G1.

    A cart summary that does not carry the field has not TOLD us there is a Razorpay leg, and
    inferring one from `payNow` alone would be exactly the guess R6.2 forbids.
    """
    cart = partial_cart()
    cart["summary"]["paymentSummary"].pop("requiresPaymentAfterGiftCard")
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW, quote=quote())
    assert refusal.value.code == "GIFT_CARD_COVERS_FULL_TOTAL"

    # A truthy non-True value refuses too: `is not True`, not a truthiness test.
    for sloppy in ("true", 1, "yes"):
        cart["summary"]["paymentSummary"]["requiresPaymentAfterGiftCard"] = sloppy
        with pytest.raises(gc.GiftCardValidationError):
            gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                                  pay_now_paise=PAY_NOW, quote=quote())


def test_a_request_covering_the_whole_payable_is_refused_before_wix_is_consulted():
    """The first of section 4.4's two independent triggers, and the redundancy is the point."""
    spy = Spy(partial_cart())
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.validate_redeem_request(requested_paise=PAYABLE, balance_paise=PAYABLE * 2,
                                   wix_collection_paise=COLLECTION,
                                   total_payable_paise=PAYABLE)
    assert refusal.value.code == "GIFT_CARD_COVERS_FULL_TOTAL"
    assert spy.calls == []


# ── 96 / 97 / 97a / 97b / 97c: the cap, which is defined exactly once ──────────

def test_a_redeem_at_the_cap_is_accepted():
    """`redeemCap = min(balance, wixCollectionPaise - 100)`, the HIGH-4 cap."""
    cap = gc.redeem_cap(balance_paise=COLLECTION * 2, wix_collection_paise=COLLECTION)
    assert cap == COLLECTION - gc.RAZORPAY_MIN_LEG_PAISE == 99900
    accepted = gc.validate_redeem_request(requested_paise=cap, balance_paise=COLLECTION * 2,
                                          wix_collection_paise=COLLECTION,
                                          total_payable_paise=PAYABLE)
    assert accepted == cap
    split = gc.split_payment(balance_paise=COLLECTION * 2, wix_collection_paise=COLLECTION,
                             total_payable_paise=PAYABLE, requested_paise=cap)
    assert split["payNowPaise"] == PAYABLE - cap == 3050
    assert split["payNowPaise"] >= gc.RAZORPAY_MIN_LEG_PAISE


def test_a_redeem_above_the_cap_is_refused_not_clamped():
    """Refused, never silently clamped: clamping means the figure the customer agreed to is not the
    figure applied."""
    cap = gc.redeem_cap(balance_paise=COLLECTION * 2, wix_collection_paise=COLLECTION)
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.validate_redeem_request(requested_paise=cap + 1, balance_paise=COLLECTION * 2,
                                   wix_collection_paise=COLLECTION,
                                   total_payable_paise=PAYABLE)
    assert refusal.value.code == "GIFT_CARD_REDEEM_ABOVE_CAP"


def test_a_redeem_equal_to_the_wix_collection_total_is_refused_before_wix_is_consulted():
    """97a - one of the two boundaries HIGH-4 asked for by name, with the Wix adapter a SPY asserting
    ZERO calls.

    Under revision 2's cap (`total_payable_paise - 100` = 102850) this value was INSIDE the cap and
    ABOVE what Wix could apply, so the section 4.2 identity would have refused it only AFTER the
    request reached Wix. Now our own cap refuses it first, and nothing is sent.
    """
    spy = Spy(partial_cart())
    revision_two_cap = PAYABLE - gc.RAZORPAY_MIN_LEG_PAISE
    assert COLLECTION < revision_two_cap, "the two caps must differ, or the boundary is vacuous"

    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.validate_redeem_request(requested_paise=COLLECTION, balance_paise=COLLECTION * 2,
                                   wix_collection_paise=COLLECTION,
                                   total_payable_paise=PAYABLE)
    assert refusal.value.code == "GIFT_CARD_REDEEM_ABOVE_CAP"
    assert spy.calls == [], "Wix was consulted before our own cap refused the request"


def test_a_redeem_above_the_wix_collection_total_is_refused():
    """97b - the other boundary, also with zero Wix calls."""
    spy = Spy(partial_cart())
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.validate_redeem_request(requested_paise=COLLECTION + 1, balance_paise=COLLECTION * 2,
                                   wix_collection_paise=COLLECTION,
                                   total_payable_paise=PAYABLE)
    assert refusal.value.code == "GIFT_CARD_REDEEM_ABOVE_CAP"
    assert spy.calls == []


@pytest.mark.parametrize("balance", [100, 5000, REDEEM, 99900, COLLECTION, PAYABLE,
                                     COLLECTION * 10])
def test_the_convenience_fee_is_never_funded_by_the_gift_card(balance):
    """97c. HIGH-4's decision as a PROPERTY rather than a cap, across a range of balances including
    ones far exceeding the cart total:

        payNowPaise - wixPayNowPaise == convenience_fee_paise + convenience_gst_paise

    Under HIGH-4 the gift card never funds the fee, so that difference is a CONSTANT of the quote
    rather than something that varies with the redemption. Revision 2 said the fee was "funded by
    whichever leg has room", which is the sentence HIGH-4 removes.
    """
    computed = quote()
    cap = gc.redeem_cap(balance_paise=balance, wix_collection_paise=COLLECTION)
    if cap <= 0:
        with pytest.raises(gc.GiftCardValidationError):
            gc.split_payment(balance_paise=balance, wix_collection_paise=COLLECTION,
                             total_payable_paise=PAYABLE)
        return

    split = gc.split_payment(balance_paise=balance, wix_collection_paise=COLLECTION,
                             total_payable_paise=computed.total_payable_paise)
    redeemed = split["giftCardRedeemPaise"]
    wix_pay_now = COLLECTION - redeemed
    assert split["payNowPaise"] - wix_pay_now == (computed.convenience_fee_paise
                                                 + computed.convenience_gst_paise)
    assert redeemed <= COLLECTION - gc.RAZORPAY_MIN_LEG_PAISE
    assert split["payNowPaise"] >= gc.RAZORPAY_MIN_LEG_PAISE + FEE + GST


def test_redeem_cap_is_defined_exactly_once_and_both_callers_use_it():
    """HIGH-4's structural resolution. Revision 2 had the cap written twice against two DIFFERENT
    totals, and the second copy admitted a request the reconciliation identity then refused - so the
    two could not both be satisfied and section 12.2 asserted the opposite of what the code did."""
    definitions = [node for node in ast.walk(STORE_TREE)
                   if isinstance(node, ast.FunctionDef) and node.name == "redeem_cap"]
    assert len(definitions) == 1

    # No second site re-derives it. `min(balance, ... - 100)` appears once, inside `redeem_cap`.
    owners = []
    for node in ast.walk(STORE_TREE):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) \
                or node.func.id != "min":
            continue
        owner = next(parent.name for parent in ast.walk(STORE_TREE)
                     if isinstance(parent, ast.FunctionDef)
                     and any(child is node for child in ast.walk(parent)))
        owners.append(owner)
    assert owners == ["redeem_cap"], f"the cap is re-derived in {owners}"

    # And both named callers reach the one function.
    for caller in ("validate_redeem_request", "split_payment"):
        function = next(node for node in ast.walk(STORE_TREE)
                        if isinstance(node, ast.FunctionDef) and node.name == caller)
        assert "redeem_cap(" in ast.unparse(function), f"{caller} does not call redeem_cap"
    # `split_payment` goes through the validator too, so one expression governs both.
    split = next(node for node in ast.walk(STORE_TREE)
                 if isinstance(node, ast.FunctionDef) and node.name == "split_payment")
    assert "validate_redeem_request(" in ast.unparse(split)


# ── 98: the Razorpay floor ────────────────────────────────────────────────────

def test_a_remainder_below_the_razorpay_minimum_is_refused_before_the_hold():
    """MEDIUM-13. Razorpay's Orders Create answers `BAD_REQUEST_ERROR` / "The amount must be at
    least INR 1.00" below 100 paise, at `step: payment_initiation` - AFTER a hold would have been
    taken and the quote frozen, which is the worst place for it.

    Two things are asserted, and the second is the stronger one:

    * the check EXISTS and fires, driven with a collection larger than the payable - an inconsistent
      input that could only come from a producer bug, which is exactly what a backstop is for;
    * under a well-formed quote the cap makes a sub-100 remainder UNREPRESENTABLE, because
      `remainder >= payable - (collection - 100) == fee + gst + 100`. Section 4.1 says the same of
      full cover: unrepresentable by construction rather than merely refused. The explicit check is
      retained anyway, as the backstop against a Wix view we did not predict.

    In both cases the table is a spy and records ZERO calls: the refusal precedes the hold.
    """
    cards = cards_table()
    gc.issue(cards, initial_value_paise=COLLECTION * 2, pepper=PEPPER, code=CODE,
             clock=lambda: NOW)
    cards.calls.clear()

    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.validate_redeem_request(requested_paise=PAYABLE - 50,
                                   balance_paise=COLLECTION * 2,
                                   wix_collection_paise=PAYABLE + 1000,
                                   total_payable_paise=PAYABLE)
    assert refusal.value.code == "GIFT_CARD_LEAVES_UNCHARGEABLE_REMAINDER"
    assert cards.calls == [], "the hold was taken before the remainder was checked"

    # The structural half: with the cap against the WIX collection, every accepted redemption leaves
    # at least the floor plus the whole fee leg.
    for collection in (300, 1000, COLLECTION, 2_000_000):
        computed = quote(collection)
        cap = gc.redeem_cap(balance_paise=10 ** 9, wix_collection_paise=collection)
        if cap <= 0:
            continue
        remainder = computed.total_payable_paise - cap
        assert remainder >= gc.RAZORPAY_MIN_LEG_PAISE
        assert remainder == (gc.RAZORPAY_MIN_LEG_PAISE + computed.convenience_fee_paise
                             + computed.convenience_gst_paise)

    assert gc.RAZORPAY_MIN_LEG_PAISE == 100


def test_a_cart_too_small_for_a_gift_card_refuses_rather_than_redeeming_nothing():
    """At a collection of 100 paise the cap is zero, so there is nothing a card could fund. Refused
    with a reason rather than silently redeeming zero, which would record a gift-card leg of no
    value on an order."""
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.split_payment(balance_paise=50000, wix_collection_paise=100,
                         total_payable_paise=103)
    assert refusal.value.code == "GIFT_CARD_LEAVES_UNCHARGEABLE_REMAINDER"


# ── 99 / 100: one card, and the other two rails stay shut ──────────────────────

# The one-card rule's Wix-cart half (one card ACCEPTED via `CartV2(...).calculate`) was retired with
# the Wix cart model. The rule that matters for money — exactly one card, enforced in our own
# reconciliation before anything is charged — is pinned natively below.
def test_a_second_gift_card_is_refused_by_our_own_reconciliation():
    """The half that does not depend on any Wix cart: exactly one card, enforced in our own code
    before anything is charged."""
    cart = partial_cart()
    cart["summary"]["paymentSummary"]["giftCards"].append(
        {"giftCardId": "bd000000-0000-4000-8000-0000000000c2",
         "redeemAmount": {"amount": "100.00", "convertedAmount": "100.00"}})
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.reconcile_with_wix(cart["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW, quote=quote())
    assert refusal.value.code == "GIFT_CARD_COUNT_UNSUPPORTED"

    none_at_all = partial_cart()
    none_at_all["summary"]["paymentSummary"]["giftCards"] = []
    with pytest.raises(gc.GiftCardValidationError):
        gc.reconcile_with_wix(none_at_all["summary"], gift_card_redeem_paise=REDEEM,
                              pay_now_paise=PAY_NOW, quote=quote())


# `test_memberships_and_subscription_charges_are_still_refused` was retired with the Wix cart model:
# it drove `CartV2(...).calculate` and read `cart_v2.py` source, both of which are gone. The native
# gift-card path never opened a membership or subscription rail, so there is no live gate to narrow.
