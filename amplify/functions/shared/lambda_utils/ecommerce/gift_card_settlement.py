"""The gift-card settlement stage, and the two-leg definition of "fully paid".

Why a second ladder exists at all
---------------------------------
A gift card settles a leg that is NOT a Razorpay capture. The existing verification machinery - the
authoritative Razorpay captured-payment readback, `razorpay_verify`, and the `PROVIDERPAYMENT#`
one-time claim in `order_keys` - can only verify a Razorpay capture, and it is left completely
untouched here. The gift-card leg gets its own forward-only stage, its own evidence and its own
idempotency claim.

Constructed exactly like `payment_status`
-----------------------------------------
String stage VALUES and a SEPARATE `STAGE_RANK` map, mirroring `payment_status`'s `CAPTURED =
"captured"` plus `STATUS_RANK` read through `rank()`. The reason is a measured defect class, not
style: revision 2 of the design presented the ladder as `GC_REDEEMED  50` - a name bound to an int -
and then wrote `stage(attempt) != GC_REDEEMED`, comparing a string against an integer. That is
silently always-true.

`GC_UNKNOWN` is deliberately ABSENT from `STAGE_RANK`, so `stage_rank` returns 0 for it through the
`.get` default - the same construction and the same reason as `payment_status.rank`'s "0 for
unknown, missing, or `none`". An unknown stage can overwrite nothing, which is what makes a
forward-only ladder safe across a deploy that adds a stage.

`GC_VOIDED` (60) OUTRANKS `GC_REDEEMED` (50), for exactly the reason `payment_status` ranks
`refunded` (60) above `captured` (50): a void strictly follows a redemption, so a replayed or late
redeem must not un-void a card. The reverse ranking is how a customer's balance silently disappears.

`GC_HELD` (20) sits below `GC_REDEEMED` and carries NO evidence, deliberately - the same judgement
that puts `authorized` (30) below `captured` (50). A hold is a reservation, not a receipt. Treating
one as settlement is how an order gets marked paid against money that was never deducted.

The persisted attribute holds the RANK, never the name, so the guard is a single numeric comparison
inside DynamoDB. The name is derived from it, which is why the two never both appear in one
expression.

This module writes NOTHING of the Razorpay leg
----------------------------------------------
It reads that leg only through `payment_attempt.may_create_order` and through the two module
constants below, and it never references `record_paid`, `PROVIDERPAYMENT#`,
`payment_attempt.transition` or `razorpay_verify`. `tests/test_gift_card_two_leg_finalization.py`
asserts that by AST rather than trusting it. No decision here compares a raw `'captured'`.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from . import payment_attempt

# ── the stage VALUES, which are what is compared ───────────────────────────────

#: The attribute is absent, or carries a value this build knows not.
GC_UNKNOWN = "GC_UNKNOWN"
#: No gift card on this purchase; Razorpay is the whole payment.
GC_NOT_REQUIRED = "GC_NOT_REQUIRED"
#: Balance reserved against `(codeHash, paymentAttemptId)`. A reservation, not a receipt.
GC_HELD = "GC_HELD"
#: Our redemption exists. Evidence: our own `giftCardTransactionId`.
GC_REDEEMED = "GC_REDEEMED"
#: The redemption was reversed.
GC_VOIDED = "GC_VOIDED"

STAGES = (GC_UNKNOWN, GC_NOT_REQUIRED, GC_HELD, GC_REDEEMED, GC_VOIDED)

# ── the RANKS, which are what is persisted and what the ConditionExpression orders ──

#: `GC_UNKNOWN` is deliberately absent, so `stage_rank` returns 0 for it through `.get`.
STAGE_RANK: Dict[str, int] = {
    GC_NOT_REQUIRED: 10,
    GC_HELD: 20,
    GC_REDEEMED: 50,
    GC_VOIDED: 60,
}

#: Persisted on the PAYMENT ATTEMPT row, holding the rank and never the name. Named to match
#: `payment_attempt.RANK_ATTRIBUTE`'s convention without colliding with it: an attempt's own
#: lifecycle rank and its gift-card stage rank are two different facts about one row.
RANK_ATTRIBUTE = "giftCardStageRank"

#: Derived once rather than at every call, and asserted injective by construction below.
_STAGE_BY_RANK: Dict[int, str] = {rank: name for name, rank in STAGE_RANK.items()}
if len(_STAGE_BY_RANK) != len(STAGE_RANK):  # pragma: no cover - a typo guard, not a branch
    raise RuntimeError("two gift-card stages share a rank, so a rank cannot name a stage")

#: The Razorpay leg's two evidence attributes, read through constants so a rename decided in
#: another session (design section 11) is ONE line here rather than a scatter of literals.
#: `verifiedProviderPaymentId` is written by `finalization.record_paid`; `verifiedCapturedPaise`
#: is SEAM-G13, the amount Razorpay's own readback confirmed.
RAZORPAY_EVIDENCE_ATTR = "verifiedProviderPaymentId"
RAZORPAY_VERIFIED_PAISE_ATTR = "verifiedCapturedPaise"

#: Our own evidence, and the attempt's frozen payable the two legs must close against.
REQUIRED_PAISE_ATTR = "giftCardRequiredPaise"
CODE_HASH_ATTR = "giftCardCodeHash"
REDEEMED_PAISE_ATTR = "giftCardRedeemedPaise"
TRANSACTION_ID_ATTR = "giftCardTransactionId"
PAYABLE_ATTR = "amountPaise"

#: The CLOSED evidence set `advance()` may write. Anything else raises.
#:
#: Closed rather than an open `**fields` writer because `advance` is called from two different
#: functions, and an open writer on a payment attempt row is how an unrelated attribute gets
#: written by accident. `finalization._stage` takes arbitrary fields and is trusted because it is
#: one module; this is not that situation.
#:
#: `verifiedCapturedPaise` is EXCLUDED on purpose, and the exclusion is load-bearing rather than an
#: oversight: it is the Razorpay leg's evidence, written by `finalization.record_paid` in the same
#: conditional expression as `verifiedProviderPaymentId` because the two are the same fact recorded
#: at the same instant. `razorpayChargedPaise` is excluded too - it is written at checkout by the
#: producer and is an audit record that no settlement decision reads.
EVIDENCE_KEYS = frozenset({REQUIRED_PAISE_ATTR, CODE_HASH_ATTR, REDEEMED_PAISE_ATTR,
                           TRANSACTION_ID_ATTR})

#: What we ASKED the gateway for, as opposed to what it gave. Declared so a reader can see it is
#: named here and read nowhere in this module.
CHECKOUT_INTENDED_PAISE_ATTR = "razorpayChargedPaise"


class StageRegressed(RuntimeError):
    """A write would have moved the gift-card stage backwards, and the database refused it.

    Raised rather than swallowed. A backward move means two writers disagree about what happened
    to a customer's money, which is a fault to surface, not a no-op to absorb.
    """


class EvidenceRefused(ValueError):
    """An evidence key outside the closed set was offered to `advance`."""


def stage(attempt: Optional[Mapping[str, Any]]) -> str:
    """The stage VALUE for an attempt, or `GC_UNKNOWN`. Never raises on a missing attribute."""
    if not attempt:
        return GC_UNKNOWN
    raw = attempt.get(RANK_ATTRIBUTE)
    if raw is None or isinstance(raw, bool):
        return GC_UNKNOWN
    try:
        return _STAGE_BY_RANK.get(int(raw), GC_UNKNOWN)
    except (TypeError, ValueError):
        return GC_UNKNOWN


def stage_rank(attempt: Optional[Mapping[str, Any]]) -> int:
    """`STAGE_RANK.get(stage(attempt), 0)`. Zero for unknown, so it can overwrite nothing."""
    return STAGE_RANK.get(stage(attempt), 0)


def rank_of(value: str) -> int:
    """The rank of a stage NAME. Zero for one this build does not know."""
    return STAGE_RANK.get(str(value or ""), 0)


def condition_expression(attribute: str = RANK_ATTRIBUTE) -> str:
    """The forward-only guard, shaped exactly like `payment_status.condition_expression`.

    The `attribute_not_exists` arm lets the first write through and establishes the rank from then
    on. Strictly `<`, so re-applying the same stage is refused as well as a backward one: a second
    `GC_REDEEMED` means a caller is redeeming twice, and the redeeming caller's own idempotency is
    where that is supposed to be absorbed.
    """
    return f"attribute_not_exists({attribute}) OR {attribute} < :rank"


def advance(attempts: Any, *, attempt_id: str, stage: str, **evidence: Any) -> Dict[str, Any]:
    """ONE conditional `UpdateItem` on PaymentAttemptsTable. The writer the ladder rests on.

    Never a read-then-write. The guard is `condition_expression()`, so two concurrent writers
    cannot both advance the stage and a late `GC_REDEEMED` cannot overwrite a `GC_VOIDED`.

    `stage` must be one of the four ranked values - `GC_UNKNOWN` is not writable, because a rank of
    zero would be a write that could not satisfy its own guard. Evidence keys are the closed set
    in `EVIDENCE_KEYS`; anything else raises `EvidenceRefused` rather than being dropped, so a
    misspelling fails loudly instead of writing nothing.

    Raises `StageRegressed` on a conditional failure.
    """
    target = str(stage or "")
    if target not in STAGE_RANK:
        raise EvidenceRefused(
            f"{target!r} is not a writable gift-card stage; expected one of "
            f"{sorted(STAGE_RANK)}")
    unknown = sorted(set(evidence) - EVIDENCE_KEYS)
    if unknown:
        raise EvidenceRefused(
            f"gift-card evidence keys are a closed set; refusing {unknown}. "
            f"{RAZORPAY_VERIFIED_PAISE_ATTR} belongs to the Razorpay leg's own writer, not here.")
    if not attempt_id or not isinstance(attempt_id, str):
        raise EvidenceRefused("a paymentAttemptId is required")

    rank = STAGE_RANK[target]
    assignments = [f"{RANK_ATTRIBUTE} = :rank"]
    values: Dict[str, Any] = {":rank": rank}
    for key in sorted(evidence):
        assignments.append(f"{key} = :{key}")
        values[f":{key}"] = evidence[key]

    try:
        updated = attempts.update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression=condition_expression(),
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001 - re-raised below unless it is the guard
        if _is_conditional_failure(error):
            raise StageRegressed(
                f"refusing to move the gift-card stage to {target} (rank {rank}) on "
                f"{attempt_id}: the stored rank is not lower") from None
        raise
    return updated


def _is_conditional_failure(error: BaseException) -> bool:
    if type(error).__name__ == "ConditionalCheckFailedException":
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    return False


def is_fully_settled(attempt: Optional[Mapping[str, Any]]) -> bool:
    """True only when every leg of the payable total has its own VERIFIED evidence.

    NEVER raises on a missing attribute. This function gates order completion, so an absent key
    must answer "not settled" rather than propagate a `KeyError` out of finalization AFTER a
    capture has already been verified - an exception there would strand a paid customer in an
    unhandled failure instead of a recoverable `NEEDS_RECONCILIATION`.

    A partially-settled order can never be marked fully paid on the Razorpay leg alone. When
    `giftCardRequiredPaise > 0`, a verified Razorpay capture is necessary and NOT SUFFICIENT, and
    the second condition cannot be satisfied without our own redemption transaction id existing in
    our own table.
    """
    if not attempt:
        return False

    # Leg 1 -- Razorpay. Existing machinery, CONSULTED and not reimplemented. `may_create_order`
    # is exactly `status in {PAYMENT_PAID}`, so no raw payment word is compared here.
    if not payment_attempt.may_create_order(attempt):
        return False
    if not attempt.get(RAZORPAY_EVIDENCE_ATTR):
        return False

    # Leg 2 -- the gift card. Its own stage, its own evidence.
    required = _as_int(attempt.get(REQUIRED_PAISE_ATTR))
    if required == 0:
        # ABSENCE IS THE NORMAL CASE. An ordinary Razorpay-only attempt carries no gift-card
        # attribute at all, so there is no second leg and nothing has to have been written. A
        # GC_HELD / GC_REDEEMED stage with required == 0 is a contradiction, and it fails CLOSED
        # rather than being treated as a settled no-op.
        return stage(attempt) in (GC_NOT_REQUIRED, GC_UNKNOWN)
    if stage(attempt) != GC_REDEEMED:
        return False
    if not attempt.get(TRANSACTION_ID_ATTR):          # OUR transaction id
        return False
    redeemed = _as_int(attempt.get(REDEEMED_PAISE_ATTR))
    if redeemed != required:
        # A stage of GC_REDEEMED with a short redeemed amount is a partially-settled order
        # wearing a settled label.
        return False

    # The closure: the two legs must account for the whole frozen payable, and the Razorpay term
    # is the amount the PROVIDER confirmed -- not the amount we asked for. Comparing two numbers
    # written by the same code in the same request would prove the split was internally
    # consistent, which is arithmetic rather than evidence.
    verified = attempt.get(RAZORPAY_VERIFIED_PAISE_ATTR)
    if verified is None:
        return False          # unverifiable, therefore not settled. Never an exception.
    payable = attempt.get(PAYABLE_ATTR)
    if payable is None:
        return False
    try:
        return int(verified) + redeemed == int(payable)
    except (TypeError, ValueError):
        return False


def _as_int(value: Any) -> int:
    """Integer paise from a stored value, or 0. Tolerant because this must never raise."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def describe(attempt: Optional[Mapping[str, Any]]) -> str:
    """A short, log-safe summary. Carries paise and no code, no hash and no customer identifier.

    Amounts in paise are not a disclosure and are what makes the line useful -
    `payment_status.entity_summary` already draws that line the same way.
    """
    name = stage(attempt)
    return (f"{name} (rank {stage_rank(attempt)}), "
            f"required {_as_int((attempt or {}).get(REQUIRED_PAISE_ATTR))} paise, "
            f"redeemed {_as_int((attempt or {}).get(REDEEMED_PAISE_ATTR))} paise")


__all__ = [
    "CHECKOUT_INTENDED_PAISE_ATTR", "CODE_HASH_ATTR", "EVIDENCE_KEYS", "EvidenceRefused",
    "GC_HELD", "GC_NOT_REQUIRED", "GC_REDEEMED", "GC_UNKNOWN", "GC_VOIDED", "PAYABLE_ATTR",
    "RANK_ATTRIBUTE", "RAZORPAY_EVIDENCE_ATTR", "RAZORPAY_VERIFIED_PAISE_ATTR",
    "REDEEMED_PAISE_ATTR", "REQUIRED_PAISE_ATTR", "STAGES", "STAGE_RANK", "StageRegressed",
    "TRANSACTION_ID_ATTR", "advance", "condition_expression", "describe", "is_fully_settled",
    "rank_of", "stage", "stage_rank",
]
