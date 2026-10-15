"""Two-leg settlement: a verified Razorpay capture is necessary and NOT sufficient.

MEDIUM-7's rename is applied: test 80 was `..._after_the_reference_is_minted_...`, and revision 3
re-keyed the hold onto `paymentAttemptId` precisely BECAUSE the reference is not available in time
on the website path - `attempt["referenceId"]` there is the Razorpay order id, which does not exist
until after the gateway is addressed. A test named for the reference would assert the ordering the
design rejected.

The headline is test 69. An attempt carrying ONLY the Razorpay attributes and no gift-card key at
all must be FULLY SETTLED, because that is the ordinary path and the common path must need no write.
Revision 1 read `stage_rank(attempt) >= GC_NOT_REQUIRED_RANK` there, which is `0 >= 10` for an
ordinary attempt - so every non-gift-card order would have been not-fully-settled and the whole
checkout would have halted once wired.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import gift_card_settlement as gcs  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402
from lambda_utils.ecommerce import payment_attempt  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_settlement.py"
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(MODULE))

PEPPER = "pepper-for-tests-only"
NOW = 1_700_000_000
CODE = "WDGC0000TEST0001"

PAYABLE = 102950          # the section 2 worked example: 100000 + 2500 + 450
REDEEMED = 40000
CHARGED = PAYABLE - REDEEMED


def clock(value: int = NOW):
    return lambda: value


def attempts_table() -> FakeTable:
    return FakeTable(key_attr="paymentAttemptId")


def cards_table() -> FakeTable:
    return FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                    indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})


def digest() -> str:
    return gc.code_hash(CODE, pepper=PEPPER)


def razorpay_only(*, payable: int = PAYABLE, verified: int = PAYABLE) -> dict:
    """An ordinary attempt: paid, verified, and carrying NO gift-card attribute at all."""
    return {
        "paymentAttemptId": "attempt-1",
        "status": payment_attempt.PAYMENT_PAID,
        gcs.RAZORPAY_EVIDENCE_ATTR: "pay_RAZORPAYID00001",
        gcs.RAZORPAY_VERIFIED_PAISE_ATTR: verified,
        "amountPaise": payable,
        # What we ASKED the gateway for. An audit record; no settlement decision reads it.
        gcs.CHECKOUT_INTENDED_PAISE_ATTR: payable,
    }


def two_leg(**overrides) -> dict:
    attempt = razorpay_only(verified=CHARGED)
    attempt.update({
        gcs.RANK_ATTRIBUTE: gcs.STAGE_RANK[gcs.GC_REDEEMED],
        gcs.REQUIRED_PAISE_ATTR: REDEEMED,
        gcs.REDEEMED_PAISE_ATTR: REDEEMED,
        gcs.TRANSACTION_ID_ATTR: "01JTESTTRANSACTION00000001",
        gcs.CODE_HASH_ATTR: digest(),
        gcs.CHECKOUT_INTENDED_PAISE_ATTR: CHARGED,
    })
    attempt.update(overrides)
    return attempt


# ── 65-68: both legs, and what each one contributes ───────────────────────────

def test_a_verified_razorpay_capture_alone_is_not_fully_settled():
    """THE headline property, and the one this module exists to make structural.

    `giftCardRequiredPaise > 0`, the Razorpay leg `PAYMENT_PAID` with a verified provider id, and
    the gift-card stage only `GC_HELD`. A hold is a reservation, not a receipt: treating one as
    settlement is how an order gets marked paid against money that was never deducted.
    """
    attempt = two_leg(**{gcs.RANK_ATTRIBUTE: gcs.STAGE_RANK[gcs.GC_HELD]})
    attempt.pop(gcs.REDEEMED_PAISE_ATTR)
    attempt.pop(gcs.TRANSACTION_ID_ATTR)
    assert gcs.stage(attempt) == gcs.GC_HELD
    assert payment_attempt.may_create_order(attempt) is True
    assert gcs.is_fully_settled(attempt) is False


def test_fully_settled_needs_our_own_redemption_transaction_id():
    """Stage `GC_REDEEMED` with no `giftCardTransactionId` is a label with no receipt behind it.

    The second condition cannot be satisfied without OUR OWN redemption transaction id existing in
    OUR OWN table, which is what makes a verified Razorpay capture insufficient rather than merely
    incomplete.
    """
    attempt = two_leg()
    attempt.pop(gcs.TRANSACTION_ID_ATTR)
    assert gcs.is_fully_settled(attempt) is False


def test_a_short_redeemed_amount_is_not_fully_settled():
    """A stage of `GC_REDEEMED` with a short `giftCardRedeemedPaise` is a partially-settled order
    wearing a settled label. The amount checks matter as much as the stage check."""
    assert gcs.is_fully_settled(two_leg(**{gcs.REDEEMED_PAISE_ATTR: REDEEMED - 1})) is False
    assert gcs.is_fully_settled(two_leg(**{gcs.REDEEMED_PAISE_ATTR: REDEEMED + 1})) is False


def test_both_legs_present_is_fully_settled():
    attempt = two_leg()
    assert gcs.is_fully_settled(attempt) is True
    assert attempt[gcs.RAZORPAY_VERIFIED_PAISE_ATTR] + attempt[gcs.REDEEMED_PAISE_ATTR] \
        == attempt["amountPaise"]


# ── 69-71: absence means not-required ─────────────────────────────────────────

def test_an_attempt_with_only_razorpay_attributes_is_fully_settled():
    """HIGH-1, and this is the test that would have caught it.

    The dict carries `status`, `verifiedProviderPaymentId`, `verifiedCapturedPaise`, `amountPaise`
    and `razorpayChargedPaise` - and NO gift-card key whatsoever. `stage_rank` is 0 and the
    `required == 0` branch is a MEMBERSHIP test including `GC_UNKNOWN`, so the common path needs no
    write at all. Revision 1 compared `0 >= 10` here and would have halted every ordinary checkout
    once SEAM-G5 gated order completion on this function.
    """
    attempt = razorpay_only()
    assert not [key for key in attempt if key.startswith("giftCard")]
    assert gcs.stage(attempt) == gcs.GC_UNKNOWN
    assert gcs.stage_rank(attempt) == 0
    assert gcs.is_fully_settled(attempt) is True


def test_an_explicit_gc_not_required_stage_is_also_fully_settled():
    """The other half of the `required == 0` branch: a row that says so explicitly."""
    attempt = razorpay_only()
    attempt[gcs.RANK_ATTRIBUTE] = gcs.STAGE_RANK[gcs.GC_NOT_REQUIRED]
    assert gcs.stage(attempt) == gcs.GC_NOT_REQUIRED
    assert gcs.is_fully_settled(attempt) is True


def test_a_held_stage_with_nothing_required_fails_closed():
    """The contradiction case. A `GC_HELD` or `GC_REDEEMED` stage with `required == 0` means two
    writers disagree about whether a gift card is on this purchase, and an ambiguous verification
    answers "not settled" rather than "settled no-op"."""
    for stage_name in (gcs.GC_HELD, gcs.GC_REDEEMED, gcs.GC_VOIDED):
        attempt = razorpay_only()
        attempt[gcs.RANK_ATTRIBUTE] = gcs.STAGE_RANK[stage_name]
        assert gcs.is_fully_settled(attempt) is False, stage_name


def test_the_gift_card_leg_alone_is_never_fully_settled():
    """No Razorpay evidence, so no settlement - whatever the gift-card leg says."""
    attempt = two_leg()
    attempt.pop(gcs.RAZORPAY_EVIDENCE_ATTR)
    assert gcs.is_fully_settled(attempt) is False

    unpaid = two_leg()
    unpaid["status"] = payment_attempt.PAYMENT_PENDING
    assert gcs.is_fully_settled(unpaid) is False


# ── 73-76: the ladder ─────────────────────────────────────────────────────────

def test_the_stage_ladder_is_forward_only():
    """Every backward transition is refused by the DATABASE, not by a comparison we made."""
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1"})
    gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_HELD,
                giftCardRequiredPaise=REDEEMED, giftCardCodeHash=digest())
    gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_REDEEMED,
                giftCardRedeemedPaise=REDEEMED, giftCardTransactionId="01JTXN")

    for backward in (gcs.GC_HELD, gcs.GC_NOT_REQUIRED, gcs.GC_REDEEMED):
        with pytest.raises(gcs.StageRegressed):
            gcs.advance(store, attempt_id="attempt-1", stage=backward)
    assert store.rows["attempt-1"][gcs.RANK_ATTRIBUTE] == gcs.STAGE_RANK[gcs.GC_REDEEMED]


def test_a_void_outranks_a_redeem_so_a_replayed_redeem_cannot_unvoid():
    """`GC_VOIDED` (60) above `GC_REDEEMED` (50), for exactly the reason `payment_status` ranks
    `refunded` (60) above `captured` (50): a void strictly follows a redemption. The reverse
    ranking is how a customer's balance silently disappears."""
    assert gcs.STAGE_RANK[gcs.GC_VOIDED] > gcs.STAGE_RANK[gcs.GC_REDEEMED]

    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1",
                gcs.RANK_ATTRIBUTE: gcs.STAGE_RANK[gcs.GC_REDEEMED]})
    gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_VOIDED)
    with pytest.raises(gcs.StageRegressed):
        gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_REDEEMED,
                    giftCardRedeemedPaise=REDEEMED, giftCardTransactionId="01JTXN")
    assert store.rows["attempt-1"][gcs.RANK_ATTRIBUTE] == gcs.STAGE_RANK[gcs.GC_VOIDED]


def test_a_hold_carries_no_evidence_and_never_counts_as_settlement():
    """`GC_HELD` is below `GC_REDEEMED` and carries NO evidence, deliberately - the same judgement
    that puts `authorized` (30) below `captured` (50)."""
    assert gcs.STAGE_RANK[gcs.GC_HELD] < gcs.STAGE_RANK[gcs.GC_REDEEMED]
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1"})
    gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_HELD,
                giftCardRequiredPaise=REDEEMED, giftCardCodeHash=digest())
    row = dict(store.rows["attempt-1"])
    assert gcs.TRANSACTION_ID_ATTR not in row
    assert gcs.REDEEMED_PAISE_ATTR not in row

    row.update({"status": payment_attempt.PAYMENT_PAID,
                gcs.RAZORPAY_EVIDENCE_ATTR: "pay_X", gcs.RAZORPAY_VERIFIED_PAISE_ATTR: CHARGED,
                "amountPaise": PAYABLE})
    assert gcs.is_fully_settled(row) is False


def test_an_unknown_stage_ranks_zero_and_overwrites_nothing():
    """`GC_UNKNOWN` is deliberately ABSENT from `STAGE_RANK`, so `stage_rank` returns 0 through the
    `.get` default - the same construction and the same reason as `payment_status.rank`. That is
    what makes the ladder safe across a deploy that adds a stage."""
    assert gcs.GC_UNKNOWN not in gcs.STAGE_RANK
    assert gcs.stage_rank({}) == 0
    assert gcs.stage_rank(None) == 0
    assert gcs.stage({gcs.RANK_ATTRIBUTE: 999}) == gcs.GC_UNKNOWN
    assert gcs.stage({gcs.RANK_ATTRIBUTE: "nonsense"}) == gcs.GC_UNKNOWN
    assert gcs.stage({gcs.RANK_ATTRIBUTE: True}) == gcs.GC_UNKNOWN
    assert gcs.rank_of(gcs.GC_UNKNOWN) == 0

    # And `GC_UNKNOWN` is not WRITABLE: a rank of zero could not satisfy its own guard.
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1"})
    with pytest.raises(gcs.EvidenceRefused):
        gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_UNKNOWN)


def test_the_stage_values_are_strings_and_the_ranks_are_a_separate_map():
    """MEDIUM-12. Revision 2 bound the names to integers and then compared a string against one,
    which is silently always-true - the same shape of defect as the HIGH-1 bug it had just fixed.
    `payment_status` separates `CAPTURED = "captured"` from `STATUS_RANK`, and this mirrors it."""
    for value in gcs.STAGES:
        assert isinstance(value, str)
    assert gcs.GC_REDEEMED == "GC_REDEEMED"
    assert isinstance(gcs.STAGE_RANK, dict)
    assert all(isinstance(key, str) and isinstance(value, int)
               for key, value in gcs.STAGE_RANK.items())
    assert sorted(gcs.STAGE_RANK.values()) == [10, 20, 50, 60]


# ── 77-79: advance() is the writer HIGH-2 found missing ────────────────────────

def test_advance_is_a_conditional_update_not_a_read_then_write():
    """The guard is `condition_expression()` and no `get_item` precedes it. Two concurrent writers
    cannot both advance the stage, and a late `GC_REDEEMED` cannot overwrite a `GC_VOIDED`."""
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1"})
    gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_HELD,
                giftCardRequiredPaise=REDEEMED)

    assert store.operations() == ["update_item"]
    call = store.calls[0][1]
    assert call["ConditionExpression"] == gcs.condition_expression()
    assert call["ConditionExpression"] == (
        f"attribute_not_exists({gcs.RANK_ATTRIBUTE}) OR {gcs.RANK_ATTRIBUTE} < :rank")
    assert call["ExpressionAttributeValues"][":rank"] == gcs.STAGE_RANK[gcs.GC_HELD]
    assert call["Key"] == {"paymentAttemptId": "attempt-1"}
    # The RANK is persisted, never the name: that is what lets the guard be one numeric comparison
    # inside DynamoDB.
    assert store.rows["attempt-1"][gcs.RANK_ATTRIBUTE] == 20
    assert gcs.GC_HELD not in store.rows["attempt-1"].values()


def test_advance_refuses_an_evidence_key_outside_the_closed_set():
    """An open `**fields` writer on a payment attempt row is how an unrelated attribute gets
    written by accident. `advance` is called from two functions, so the set is enumerated.

    `verifiedCapturedPaise` is the interesting refusal: it is the RAZORPAY leg's evidence, written
    by `finalization.record_paid` in the same conditional expression as `verifiedProviderPaymentId`
    because the two are the same fact at the same instant. Splitting them across two writes would
    admit a row carrying one without the other.
    """
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1"})
    assert gcs.EVIDENCE_KEYS == {"giftCardRequiredPaise", "giftCardCodeHash",
                                 "giftCardRedeemedPaise", "giftCardTransactionId"}
    assert gcs.RAZORPAY_VERIFIED_PAISE_ATTR not in gcs.EVIDENCE_KEYS
    assert gcs.CHECKOUT_INTENDED_PAISE_ATTR not in gcs.EVIDENCE_KEYS

    for forbidden in (gcs.RAZORPAY_VERIFIED_PAISE_ATTR, gcs.CHECKOUT_INTENDED_PAISE_ATTR,
                      "status", "amountPaise", "giftCardRequiredPaize"):
        with pytest.raises(gcs.EvidenceRefused):
            gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_HELD, **{forbidden: 1})
    assert store.operations() == [], "a refused evidence key still reached the table"


def test_advance_raises_stage_regressed_on_a_conditional_failure():
    """A backward move is an error to SURFACE, not a no-op to swallow: it means two writers
    disagree about what happened to a customer's money."""
    store = attempts_table()
    store.seed({"paymentAttemptId": "attempt-1",
                gcs.RANK_ATTRIBUTE: gcs.STAGE_RANK[gcs.GC_VOIDED]})
    with pytest.raises(gcs.StageRegressed) as refusal:
        gcs.advance(store, attempt_id="attempt-1", stage=gcs.GC_HELD)
    assert "attempt-1" in str(refusal.value)
    assert gcs.GC_HELD in str(refusal.value)


def test_advance_needs_a_payment_attempt_id():
    store = attempts_table()
    for bad in ("", None, 7):
        with pytest.raises(gcs.EvidenceRefused):
            gcs.advance(store, attempt_id=bad, stage=gcs.GC_HELD)


# ── 80-82: ordering against the Razorpay leg ───────────────────────────────────

def test_the_hold_is_taken_after_the_attempt_id_is_minted_and_before_the_gateway():
    """Section 3.3 step 1, and the whole reason DECISION 9 re-keyed the claim.

    A hold is reversible; a capture is not. Holding first means a card whose balance has since been
    spent elsewhere refuses the checkout BEFORE the customer is charged for the remainder. That
    ordering is only possible because the key is `paymentAttemptId`, which both producers mint
    before any external call - `attempt["referenceId"]` on the website path IS the Razorpay order
    id and does not exist until after.

    Simulated here against our own modules rather than against a producer, because both producers
    are cross-workstream seams (SEAM-G4 / SEAM-G14). What is asserted is the property this module
    makes available: the hold needs nothing the gateway has not yet provided.
    """
    cards = cards_table()
    attempts = attempts_table()
    gc.issue(cards, initial_value_paise=100000, pepper=PEPPER, code=CODE, clock=clock())
    gateway_calls: list = []

    # Step 1: mint the attempt id. Nothing external has happened.
    attempt_id = payment_attempt.new_payment_attempt_id()
    assert attempt_id and gateway_calls == []

    # Step 2: hold, using only the attempt id.
    held = gc.hold(cards, code_hash=digest(), attempt_id=attempt_id, amount_paise=REDEEMED,
                   clock=clock())
    attempts.seed({"paymentAttemptId": attempt_id})
    gcs.advance(attempts, attempt_id=attempt_id, stage=gcs.GC_HELD,
                giftCardRequiredPaise=REDEEMED, giftCardCodeHash=digest())
    assert held["held"] is True
    assert gateway_calls == [], "the gateway was addressed before the hold"

    # Step 3: only now the gateway.
    gateway_calls.append({"amountPaise": CHARGED})
    assert gcs.stage(attempts.rows[attempt_id]) == gcs.GC_HELD


def test_a_failed_gateway_releases_the_hold_and_deducts_nothing():
    cards = cards_table()
    gc.issue(cards, initial_value_paise=100000, pepper=PEPPER, code=CODE, clock=clock())
    gc.hold(cards, code_hash=digest(), attempt_id="attempt-1", amount_paise=REDEEMED,
            clock=clock())
    gc.release(cards, code_hash=digest(), attempt_id="attempt-1", clock=clock())

    card = cards.rows[gc.PREFIX_CARD + digest()]
    assert card["balancePaise"] == 100000
    assert gc.HOLD_ATTEMPT_ATTRIBUTE not in card
    # And the card is free for the next purchase immediately, not after an expiry.
    assert gc.hold(cards, code_hash=digest(), attempt_id="attempt-2", amount_paise=REDEEMED,
                   clock=clock())["held"] is True


# ── 83 / 83a / 83b / 83c / 83d: the closure compares a VERIFIED capture ─────────

def test_a_tampered_redeem_amount_cannot_reach_a_settled_order():
    """`is_fully_settled` closes both legs against the VERIFIED capture, so a split altered after
    the fact cannot settle.

    Asserted against `verifiedCapturedPaise`, the provider-confirmed figure, never the intended
    `razorpayChargedPaise` (HIGH-3). The two are written by the same code in the same request from
    the same split, so their sum re-deriving the payable proves the split was internally consistent
    when written - arithmetic, not evidence.
    """
    # Honest split: 40000 redeemed, 62950 charged and verified.
    assert gcs.is_fully_settled(two_leg()) is True

    # Reduce `razorpayChargedPaise` and nothing reads it; inflate the gift-card leg and the sum
    # fails against the capture.
    tampered = two_leg(**{gcs.REDEEMED_PAISE_ATTR: 50000, gcs.REQUIRED_PAISE_ATTR: 50000})
    assert gcs.is_fully_settled(tampered) is False
    shrunk = two_leg(**{gcs.CHECKOUT_INTENDED_PAISE_ATTR: 1})
    assert gcs.is_fully_settled(shrunk) is True, (
        "the intended gateway figure must not participate in the settlement decision")


def test_an_absent_verified_capture_amount_is_not_settled_and_does_not_raise():
    """HIGH-2's unspecified failure mode. Revision 2 read this attribute with a bracket subscript,
    so a gift-card attempt missing it raised `KeyError` INSIDE finalization, AFTER a verified
    capture - an unhandled failure in the one function that decides whether an order is paid."""
    attempt = two_leg()
    attempt.pop(gcs.RAZORPAY_VERIFIED_PAISE_ATTR)
    assert gcs.is_fully_settled(attempt) is False


def test_an_absent_amount_paise_is_not_settled_and_does_not_raise():
    attempt = two_leg()
    attempt.pop("amountPaise")
    assert gcs.is_fully_settled(attempt) is False


@pytest.mark.parametrize("attempt", [
    None, {}, {"status": payment_attempt.PAYMENT_PAID},
    {"status": payment_attempt.PAYMENT_PENDING, gcs.RAZORPAY_EVIDENCE_ATTR: "pay_X"},
    {"status": payment_attempt.PAYMENT_PAID, gcs.RAZORPAY_EVIDENCE_ATTR: "pay_X",
     gcs.REQUIRED_PAISE_ATTR: REDEEMED},
])
def test_is_fully_settled_never_raises_on_a_sparse_attempt(attempt):
    """It gates order completion, so an absent key must ANSWER rather than throw.

    Note what is NOT in this list: a Razorpay-only attempt with no `verifiedCapturedPaise` and no
    `amountPaise` is SETTLED, not unsettled, because the `required == 0` branch returns before the
    closure. That is section 3.2 verbatim and it is the point of the branch - the common path must
    need no gift-card write and no gift-card arithmetic. The closure guards the TWO-LEG case, which
    the last parameter here enters and fails.
    """
    assert gcs.is_fully_settled(attempt) is False


def test_a_short_verified_capture_is_not_settled_even_when_both_stages_look_right():
    """The property revision 2's closure could not detect.

    The Razorpay readback reports less than `payNowPaise`; both legs' stages and ids are present
    and correct. Revision 2 compared `razorpayChargedPaise + required == payable`, which holds here
    because both of those were written by the same code in the same request - so a gateway that
    captured less would have been settled.
    """
    attempt = two_leg(**{gcs.RAZORPAY_VERIFIED_PAISE_ATTR: CHARGED - 1})
    assert attempt[gcs.CHECKOUT_INTENDED_PAISE_ATTR] + attempt[gcs.REQUIRED_PAISE_ATTR] \
        == attempt["amountPaise"], "the revision-2 identity still holds, which is the point"
    assert gcs.is_fully_settled(attempt) is False


def test_the_settlement_decision_never_reads_the_intended_gateway_figure():
    """AST: no reference to `razorpayChargedPaise` inside `is_fully_settled`.

    Pins section 6.5's division of the two attributes so a later "simplification" cannot put the
    intended figure back into the closure. The constant is declared in this module precisely so a
    reader can see it is named and never read.
    """
    function = next(node for node in ast.walk(TREE)
                    if isinstance(node, ast.FunctionDef) and node.name == "is_fully_settled")
    rendered = ast.unparse(function)
    assert "razorpayChargedPaise" not in rendered
    assert "CHECKOUT_INTENDED_PAISE_ATTR" not in rendered
    assert "RAZORPAY_VERIFIED_PAISE_ATTR" in rendered
    assert "may_create_order" in rendered


# ── 84-86 ─────────────────────────────────────────────────────────────────────


def test_nothing_here_writes_the_razorpay_machinery():
    """AST. The Razorpay leg is CONSULTED through `payment_attempt.may_create_order` and never
    written, which is what keeps the existing verification path untouched.

    Over the AST rather than the text, because the paragraphs explaining the division necessarily
    name `record_paid` and `verifiedCapturedPaise`.
    """
    docstrings = {id(node.body[0].value) for node in ast.walk(TREE)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)
                  and isinstance(node.body[0].value.value, str)}

    forbidden = ("PROVIDERPAYMENT#", "record_paid", "razorpay_verify", "verify_capture")
    offenders = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            for name in forbidden:
                if name in node.value:
                    offenders.append(f"line {node.lineno}: a literal names {name}")
        if isinstance(node, ast.Attribute) and node.attr in ("transition", "record_paid",
                                                             "accept_paid"):
            offenders.append(f"line {node.lineno}: calls {node.attr}")
    assert not offenders, "\n  ".join(offenders)

    # `payment_attempt` is imported and ONLY its predicates are used.
    used = {node.attr for node in ast.walk(TREE) if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "payment_attempt"}
    assert used == {"may_create_order"}


def test_the_attempt_keeps_the_full_payable_as_amount_paise():
    """Section 8 point 3, and getting it backwards is a silent under-charge.

    `attempt["amountPaise"]` is what `is_fully_settled` closes both legs against and what the
    order record must show - the FULL taxable value, because under GST a voucher is consideration
    rather than a reduction in the value of supply. The gateway amount is a DIFFERENT number.
    """
    attempt = two_leg()
    assert attempt["amountPaise"] == PAYABLE
    assert attempt[gcs.CHECKOUT_INTENDED_PAISE_ATTR] == CHARGED < PAYABLE
    assert gcs.is_fully_settled(attempt) is True

    # Reduce the attempt's own amount to the charged figure - the obvious wrong resolution - and
    # the closure has nothing left to close against: the order reads as settled on a payable that
    # is not the payable.
    understated = two_leg(**{"amountPaise": CHARGED})
    assert gcs.is_fully_settled(understated) is False


def test_no_decision_in_this_module_compares_a_raw_payment_word():
    """`captured` is AST-banned at decision points across the fleet. This module has no payment
    decision of its own - it consults `payment_attempt.may_create_order`, which is exactly
    `status in {PAYMENT_PAID}`."""
    offenders = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        literals = {operand.value for operand in operands
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str)}
        if "captured" in literals:
            offenders.append(f"line {node.lineno}: compares 'captured' raw")
    assert not offenders, "\n  ".join(offenders)


def test_the_module_holds_no_boto3_client_and_takes_an_injected_table():
    imports = {alias.name.split(".")[0] for node in ast.walk(TREE)
               if isinstance(node, ast.Import) for alias in node.names}
    imports |= {(node.module or "").split(".")[0] for node in ast.walk(TREE)
                if isinstance(node, ast.ImportFrom)}
    assert "boto3" not in imports
    assert "os" not in imports


def test_describe_is_log_safe():
    """Paise and a stage, never a code, a hash or a customer identifier."""
    rendered = gcs.describe(two_leg())
    assert gcs.GC_REDEEMED in rendered
    assert str(REDEEMED) in rendered
    assert digest() not in rendered
    assert "pay_RAZORPAYID00001" not in rendered
    assert gcs.describe(None)
