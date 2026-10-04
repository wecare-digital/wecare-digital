"""Monotonic payment status, a shared vocabulary, and a correct webhook dedup key.

Measured, 2026-09-23
--------------------
Live account, read-only:

    RazorpayWebhookLogTable    607 rows, ALL payment.downtime.started/resolved
    PaymentsTable                0 rows
    InvoicesTable                0 rows
    OrderTable                   0 rows

So no payment has ever been captured through this webhook. Every defect below is
therefore latent on the money paths and **proven** on the one path that does carry live
traffic. That the tables are empty is why these fixes ship with no migration.

Defect 1 - the dedup key drops real events. PROVEN, 4 days of CloudWatch:

    events received                                       3030
    skipped as duplicates                                 1495
    dedup keys delivered more than once                    1347
      of those, keys whose deliveries had DIFFERENT bodies   19
    distinct events silently dropped (lower bound)          59

The key was ``account_id:event_type:created_at``, with an entity id substituted **only
when `payload.payment.entity` exists**. Downtime, refund, dispute, settlement, payout,
order.paid, invoice.* and payment_link.* events carry their entity under a different key,
so they all fell back to the coarse form. Razorpay emits one downtime per bank, and two
banks going down in the same second share a `created_at` - so the second was claimed as a
duplicate of the first and thrown away. Nineteen keys, at least 59 events, in four days.

Defect 2 - payment status was not monotonic. `_store_payment_record` was an unconditional
`put_item` of a freshly built record. A redelivered `payment.authorized` arriving after
`payment.captured` rewrote status backwards, **and** erased `refundId`/`refundAmount`,
because the record it writes does not contain those fields and the put replaces the whole
item. This is the identical defect already fixed for WhatsApp in `wa_status` and for RCS
in `rcs_status`, on the one domain where it costs money.

The ladder
----------
::

    created      10   an intent exists, nothing attempted
    pending      20   attempted, outcome unknown
    authorized   30   funds held, NOT yet ours
    failed       40   terminal for this attempt
    captured     50   money received
    refunded     60   money returned
    disputed     70   contested; outranks everything

Four placements are judgements, so they are written here rather than implied by numbers.

``authorized`` (30) is below ``captured`` (50) and below ``failed`` (40). An authorisation
is a hold, not a receipt. Ranking it above `failed` would let a stale authorisation mask a
failed capture, which is how a customer gets treated as paid when nothing settled.

``failed`` (40) is below ``captured`` (50), the opposite of the choice in `wa_status`,
where `failed` sits below `delivered` for the same underlying reason: positive evidence of
the money arriving outranks an earlier failure report. A `payment.failed` for attempt 1
followed by `payment.captured` for attempt 2 on the same order must end `captured`. Note
these are separate Razorpay payment ids, so in practice they are separate rows - but the
invoice-level status derived from them must not regress, and this is the ranking that
stops it.

``refunded`` (60) outranks ``captured``. A refund strictly follows a capture, so a
redelivered `payment.captured` after `refund.processed` must not un-refund the payment.
This is the specific regression the old unconditional put allowed, and it is the one with
a real-world consequence: the row would read `captured` with the refund fields erased,
so the money looks kept when it has been returned.

``disputed`` (70) is highest and is deliberately not terminal in the transition sense: a
dispute can be won or lost afterwards, but nothing about the *payment* should overwrite
the fact that it is contested. Dispute outcome belongs in its own attribute, not in this
one.

An unknown status gets rank 0 and can never overwrite a known one, matching `wa_status`.
A status Razorpay adds later must not silently outrank `refunded` before a human has
decided what it means.

One vocabulary, because there were five
---------------------------------------
Measured across the tree, the same real-world state was spelled differently per table:

    PaymentsTable.status           authorized pending captured failed refunded
    InvoicesTable.status           created pending_payment sent paid cancelled
    InvoicesTable.paymentStatus    pending captured failed refunded
    FlowSubmission.paymentStatus   captured pending failed paid none   (Meta's word, raw)
    OrderTable.paymentStatus       pending none paid  + arbitrary admin input

`paid` and `captured` denote one state. `canonical()` maps every observed spelling onto
this ladder so a reader does not have to know which table it came from. It deliberately
does **not** rewrite what is stored in `InvoicesTable.status`, which is a document
lifecycle (created -> sent -> paid -> cancelled) and a different axis from whether money
moved.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

CREATED = "created"
PENDING = "pending"
AUTHORIZED = "authorized"
FAILED = "failed"
CAPTURED = "captured"
REFUNDED = "refunded"
DISPUTED = "disputed"

STATUS_RANK: Dict[str, int] = {
    CREATED: 10,
    PENDING: 20,
    AUTHORIZED: 30,
    FAILED: 40,
    CAPTURED: 50,
    REFUNDED: 60,
    DISPUTED: 70,
}

#: Persisted so the guard is a ConditionExpression rather than a read-then-write race.
#: Named to match `wa_status.RANK_ATTRIBUTE`'s convention without colliding with it, since
#: a PaymentsTable row and a message row are different things.
RANK_ATTRIBUTE = "paymentStatusRank"

#: Every spelling observed in this codebase, mapped onto the ladder. `paid` is the common
#: one: InvoicesTable and OrderTable say `paid` where PaymentsTable says `captured`.
_ALIASES: Dict[str, str] = {
    "paid": CAPTURED,
    "capture": CAPTURED,
    "success": CAPTURED,
    "successful": CAPTURED,
    "completed": CAPTURED,
    # `OrderTable.paymentStatus` and `PaymentAttemptsTable.status` speak the PaymentAttempt
    # vocabulary. `payment_pending` and `payment_failed` were already mapped and `payment_paid`
    # was not, which left the ladder half mapped - and missing the half that matters:
    # `ecommerce/finalization.accept_paid` writes 'PAYMENT_PAID' onto every order it creates, so
    # `canonical()` answered '' and `rank()` answered 0 for a CONFIRMED CAPTURE. Any reader
    # comparing ranks would have let a later 'pending' overwrite a paid order.
    #
    # ACCEPTED CONSEQUENCE: this also widens `for_storage('PAYMENT_PAID')` from "raises" to
    # 'captured'. That is sound because PAYMENT_PAID and `captured` are the SAME state on one
    # ladder, so nothing is collapsed. It is NOT a licence to map the rest of the attempt
    # vocabulary for symmetry: `payment_attempt._RANK` separates PAYMENT_EXPIRED (50),
    # PAYMENT_CANCELLED (55) and PAYMENT_FAILED (60), so mapping those onto FAILED would flatten
    # three distinct attempt states into one AND let `for_storage` write 'failed' for an expiry.
    # `payment_cancelled` and `payment_expired` are therefore deliberately absent; a row holding
    # either degrades honestly to '' / rank 0, which a reader renders as "status unavailable"
    # rather than as "not paid".
    "payment_paid": CAPTURED,
    "pending_payment": PENDING,
    "payment_pending": PENDING,
    "initiated": PENDING,
    "in_progress": PENDING,
    "authorised": AUTHORIZED,           # Razorpay's own British spelling appears in docs
    "payment_failed": FAILED,
    "failure": FAILED,
    "error": FAILED,
    "cancelled": FAILED,
    "canceled": FAILED,
    "refund": REFUNDED,
    "refund_processed": REFUNDED,
    "partially_refunded": REFUNDED,
    "dispute": DISPUTED,
    "chargeback": DISPUTED,
    # Deliberately NOT mapped: `none` and `''`. Absence of a payment is not a payment
    # state, and giving it a rank would let "no payment attempted" overwrite a capture.
}

#: States after which no ordinary payment event is expected. `failed` is absent: a failed
#: attempt is routinely followed by a successful one.
_TERMINAL = frozenset({REFUNDED, DISPUTED})


def canonical(status: Optional[str]) -> str:
    """Map any observed spelling onto the ladder. `''` when it is not a payment state.

    Returns `''` rather than raising, because this runs on provider input and an unknown
    word must degrade to "do not apply" rather than break webhook processing.
    """
    if not status:
        return ""
    value = str(status).strip().lower().replace("-", "_").replace(" ", "_")
    if value in STATUS_RANK:
        return value
    return _ALIASES.get(value, "")


def for_storage(status: Optional[str]) -> str:
    """Canonical form for a value about to be WRITTEN. Raises if unmappable.

    Deliberately stricter than `canonical()`, and the asymmetry is the point.

    Reads are lenient because they run on provider input: an unknown word must
    degrade to "do not apply" rather than break webhook processing, and history
    already contains spellings nobody chose. Writes are the opposite case - we
    control the value, and letting an unrecognised one through is how a sixth
    vocabulary gets into storage. Every alias in `_ALIASES` exists because that
    already happened five times.

    Use this on any new write of a *payment* state. Note it does NOT apply to an
    invoice or order *lifecycle* field: `InvoicesTable` legitimately carries both
    `status` ("created" -> "sent" -> "paid", where the document is in its
    lifecycle) and `paymentStatus` ("captured", what the money did). Those are two
    different facts about one row and collapsing them onto one vocabulary would
    lose information - which is why the audit's "five vocabularies" is really two
    deliberate ones plus three that drifted.

    The existing rows are not rewritten here. That migration touches the admin
    surface and the frontend and is tracked for Phase 4f; `canonical()` keeps
    reading what is already stored. This stops the problem growing meanwhile.
    """
    value = canonical(status)
    if not value:
        raise ValueError(
            f"refusing to store {status!r} as a payment status: it maps to no "
            f"known state. Add an alias to payment_status._ALIASES if this is a "
            f"real provider spelling, rather than storing a sixth vocabulary."
        )
    return value


def rank(status: Optional[str]) -> int:
    """Rank of a status; 0 for unknown, missing, or `none`."""
    return STATUS_RANK.get(canonical(status), 0)


def is_known(status: Optional[str]) -> bool:
    return rank(status) > 0


def is_terminal(status: Optional[str]) -> bool:
    return canonical(status) in _TERMINAL


def should_apply(current: Optional[str], incoming: Optional[str]) -> bool:
    """Would `incoming` be a forward move from `current`?

    For in-memory decisions and tests. The authority is `condition_expression()`, because
    two webhook deliveries can be processed concurrently and a read-then-write lets both
    through - which is exactly how a redelivered `authorized` overwrote a `captured`.
    """
    incoming_rank = rank(incoming)
    if incoming_rank == 0:
        return False
    return incoming_rank > rank(current)


def condition_expression(attribute: str = RANK_ATTRIBUTE) -> str:
    """Atomic guard: apply only when this rank beats the stored one.

    The `attribute_not_exists` arm lets the first write after deployment through and
    establishes the rank from then on. PaymentsTable holds 0 rows, so in practice every
    row will carry a rank from its first write.
    """
    return f"attribute_not_exists({attribute}) OR {attribute} < :rank"


def describe(status: Optional[str]) -> str:
    """Short explanation, safe for logs. Never includes an amount or a customer id."""
    resolved = canonical(status)
    if not resolved:
        return f"unknown payment status {status!r}, rank 0, will not overwrite"
    if resolved != (status or "").strip().lower():
        return f"{status} -> {resolved} (rank {STATUS_RANK[resolved]})"
    return f"{resolved} (rank {STATUS_RANK[resolved]})"


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def paise(value: Any) -> int:
    """Coerce a minor-unit amount to int paise. Raises on anything unusable.

    Exists because the payment tree mixes units: `_store_payment_record` wrote `amount` in
    paise and `amountInRupees` alongside it, while `_handle_refund` wrote `refundAmount` in
    **rupees** on that same row. One item, two units, no field name saying which.

    Raises rather than returning 0. A silent 0 on a refund amount is a reconciliation
    error that looks like a successful write.
    """
    if value is None:
        raise ValueError("amount is required")
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    try:
        as_int = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a minor-unit amount: {value!r}") from exc
    if as_int < 0:
        raise ValueError(f"amount cannot be negative: {as_int}")
    return as_int


def rupees_str(amount_paise: Any) -> str:
    """Display-only rupee rendering of an integer paise amount.

    Returns a string, deliberately. Every float rupee value in this tree began as a
    display conversion that then got compared, summed or stored - including an invoice
    match on `abs(inv_total - amount_rupees) < 0.02`. A string cannot be arithmetic'd by
    accident, which is the point.
    """
    value = paise(amount_paise)
    return f"{value // 100}.{value % 100:02d}"


# ---------------------------------------------------------------------------
# Webhook dedup key
# ---------------------------------------------------------------------------

#: Every entity container Razorpay puts in `payload.payload`, in the order we prefer them.
#: The keys really do contain dots for the nested ones: a downtime arrives as
#: ``{"payment.downtime": {"entity": {...}}}``, which is why
#: ``event_data.get('downtime')`` never matched and every downtime was processed with an
#: empty entity.
ENTITY_KEYS: Tuple[str, ...] = (
    "payment",
    "refund",
    "order",
    "invoice",
    "payment.downtime",
    "payment.dispute",
    "dispute",
    "downtime",
    "settlement",
    "subscription",
    "payment_link",
    "fund_account",
    "payout",
    "token",
    "account",
    "virtual_account",
    "transfer",
)


def extract_entity(event_data: Optional[Mapping[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """`(container_key, entity)` for a Razorpay `payload.payload`. `('', {})` if none.

    Tries every known container rather than only `payment`, which is what makes the dedup
    key below unique per event instead of per second.
    """
    if not isinstance(event_data, Mapping):
        return "", {}
    for key in ENTITY_KEYS:
        container = event_data.get(key)
        if isinstance(container, Mapping):
            entity = container.get("entity")
            if isinstance(entity, Mapping) and entity:
                return key, dict(entity)
    return "", {}


def dedup_key(payload: Optional[Mapping[str, Any]]) -> str:
    """The idempotency key for a Razorpay webhook delivery.

    ``{entity_id}:{event_type}`` whenever any entity carries an id - which, with
    `ENTITY_KEYS` above, is every event type Razorpay actually sends us. That is unique
    per real event, so a retry collapses and two distinct events never do.

    Falls back to ``{account_id}:{event}:{created_at}`` only when no entity id exists at
    all. That fallback is what was previously used for every non-payment event, and it
    dropped at least 59 real events in four days: Razorpay emits one downtime per bank and
    banks fail together, so `created_at` is not a discriminator.

    Returns `''` when there is nothing to key on, which callers must treat as "process it"
    rather than "duplicate" - dropping an unkeyable payment event is worse than handling it
    twice, and the downstream writes are now monotonic anyway.
    """
    if not isinstance(payload, Mapping):
        return ""
    event_type = str(payload.get("event") or "").strip()
    _, entity = extract_entity(payload.get("payload"))
    entity_id = str(entity.get("id") or "").strip()
    if entity_id and event_type:
        return f"{entity_id}:{event_type}"
    if entity_id:
        return entity_id

    account_id = str(payload.get("account_id") or "").strip()
    created_at = str(payload.get("created_at") or "").strip()
    if not (account_id or event_type or created_at):
        return ""
    return f"{account_id}:{event_type}:{created_at}"


def entity_summary(event_data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Log-safe summary of whatever entity an event carries.

    Deliberately excludes `email`, `contact`, `vpa`, `card_id` and `notes`: those are
    customer identifiers and payment instrument detail, and this output goes to CloudWatch.
    Amounts are included as integer minor units, which is not a disclosure and is needed to
    reconcile.
    """
    container, entity = extract_entity(event_data)
    if not entity:
        return {"entity": None}
    summary: Dict[str, Any] = {
        "entityKey": container,
        "entityId": entity.get("id", ""),
        "status": entity.get("status", ""),
    }
    for field in ("method", "severity", "scheduled", "currency", "payment_id",
                  "order_id", "invoice_id", "reason_code", "speed", "error_code"):
        if entity.get(field) not in (None, ""):
            summary[field] = entity[field]
    instrument = entity.get("instrument")
    if isinstance(instrument, Mapping) and instrument:
        # Bank / issuer codes only. This is the actionable content of a downtime event and
        # all 607 live downtime events discarded it.
        summary["instrument"] = {k: v for k, v in instrument.items()
                                 if k in ("bank", "issuer", "psp", "wallet", "vpa_handle")}
    if entity.get("amount") is not None:
        try:
            summary["amountPaise"] = paise(entity["amount"])
        except ValueError:
            summary["amountPaise"] = None
    return summary
