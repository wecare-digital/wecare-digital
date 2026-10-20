"""Short-link lifecycle and attachment policy, as pure data with no AWS in it.

WHY THIS IS A MODULE AND NOT AN `active` BOOLEAN
------------------------------------------------
A short link is not a database row that can be deleted when it stops being useful. By the time
it reaches this function it has already been printed on a card, embedded in a WhatsApp/SMS/RCS
message, rendered into an email, burned into a QR code on an invoice, and shared externally. A
hard `DELETE` makes every one of those copies resolve to a 404-shaped dead end for the one
visitor who already trusted the link. `operations/system-cleanup` protects ShortLinksTable for
exactly this reason.

So the everyday verb is DEACTIVATE, not delete, and the record carries a three-state lifecycle:

    ACTIVE    -> redirects to its destination.
    INACTIVE  -> resolves to a safe fallback message/destination; fully reversible.
    RETIRED   -> terminal. The code is permanently spent: it never redirects again and can
                 never be reactivated, but the row and its click history survive as audit.

RETIRED is the only one-way door. ACTIVE <-> INACTIVE is reversible so an operator can take a
link down and bring it back without minting a new code (which would orphan the printed copies).
Click analytics are retained across every transition, because the whole point of keeping the
row is that the history is the audit.

WHY THE TRANSITIONS LIVE HERE
-----------------------------
The handler should not decide "can this link move from X to Y" by comparing strings in three
places. The vocabulary and the legal edges live in one file, the same discipline
`lambda_utils.payment_status` and `order_channel` apply to their words. The module is injectable
and imports no boto3, so the lifecycle can be pinned by a pytest that constructs states directly
rather than standing up DynamoDB.
"""

from __future__ import annotations

#: A link that redirects to its destination.
STATE_ACTIVE = "ACTIVE"

#: A link that has been taken down. It resolves to the safe fallback, not its destination, but
#: can be brought back to ACTIVE. Reversible on purpose.
STATE_INACTIVE = "INACTIVE"

#: A permanently spent link. Terminal: it never redirects again and cannot be reactivated. The
#: row and clicks are kept as audit history.
STATE_RETIRED = "RETIRED"

#: Every lifecycle state that exists. Frozen so a caller cannot extend it in place and a test
#: can assert the vocabulary is exactly these three.
STATES = frozenset({STATE_ACTIVE, STATE_INACTIVE, STATE_RETIRED})

#: The legal moves. ACTIVE <-> INACTIVE is reversible; RETIRED is a sink with no outgoing edge.
#: A state may always be "moved" to itself (a no-op), handled in `can_transition` rather than
#: listed here so the edges read as the real decisions.
_TRANSITIONS = {
    STATE_ACTIVE: frozenset({STATE_INACTIVE, STATE_RETIRED}),
    STATE_INACTIVE: frozenset({STATE_ACTIVE, STATE_RETIRED}),
    STATE_RETIRED: frozenset(),
}

#: Related-record kinds a link may optionally be attached to. "general" is the unattached
#: default, not the absence of a value, so a filter can tell "deliberately general" from a row
#: written before attachments existed (which has no field at all).
RELATED_GENERAL = "general"
RELATED_CUSTOMER = "customer"
RELATED_CAMPAIGN = "campaign"
RELATED_ORDER = "order"
RELATED_INVOICE = "invoice"
RELATED_SERVICE = "service"

#: Every attachment kind. Frozen for the same reason as STATES.
RELATED_TYPES = frozenset(
    {
        RELATED_GENERAL,
        RELATED_CUSTOMER,
        RELATED_CAMPAIGN,
        RELATED_ORDER,
        RELATED_INVOICE,
        RELATED_SERVICE,
    }
)


def canonical_state(value) -> str:
    """One of the three states, for any input. Never raises.

    A legacy row carries only an `active` boolean and no explicit state; callers resolve that
    through `state_from_record` instead. This coercion is for a value that is already meant to
    be a state word: it upper-cases and strips, and anything it does not recognise falls to
    ACTIVE, because a redirect path that cannot read its own state must not silently stop
    resolving a link that was working.
    """
    try:
        word = str(value).strip().upper()
    except Exception:
        return STATE_ACTIVE
    return word if word in STATES else STATE_ACTIVE


def canonical_related_type(value) -> str:
    """One of the attachment kinds, defaulting to `general`. Never raises."""
    try:
        word = str(value).strip().lower()
    except Exception:
        return RELATED_GENERAL
    return word if word in RELATED_TYPES else RELATED_GENERAL


def state_from_record(item) -> str:
    """Resolve the lifecycle state of a stored link row.

    New rows carry an explicit `lifecycleState`. Rows written before the lifecycle existed carry
    only `active`; a missing or truthy `active` is ACTIVE and an explicit `active == False` is
    INACTIVE. A row can never be inferred as RETIRED from a bare boolean, because RETIRED is a
    deliberate terminal decision and nothing legacy ever recorded it.
    """
    if not isinstance(item, dict):
        return STATE_ACTIVE
    explicit = item.get("lifecycleState")
    if explicit is not None:
        return canonical_state(explicit)
    return STATE_ACTIVE if item.get("active", True) else STATE_INACTIVE


def can_transition(current, target) -> bool:
    """True when a link may move from `current` to `target`.

    Moving a state to itself is always allowed (an idempotent no-op). Every other move must be a
    listed edge, so RETIRED -> anything and an edge that was never drawn both return False.
    """
    cur = canonical_state(current)
    tgt = canonical_state(target)
    if cur == tgt:
        return True
    return tgt in _TRANSITIONS.get(cur, frozenset())


def is_resolvable(item) -> bool:
    """True when a link should redirect to its own destination.

    Only ACTIVE resolves. INACTIVE and RETIRED both fall to the safe fallback, which is why the
    redirect path asks this one question rather than reading `active` directly: an INACTIVE link
    that someone forgot to also set `active=False` on must still stop resolving.
    """
    return state_from_record(item) == STATE_ACTIVE


def active_flag_for(state) -> bool:
    """The legacy `active` boolean to persist alongside a lifecycle state.

    Kept in sync so an older reader (or the redirect fast-path) that still consults `active`
    agrees with the lifecycle: only ACTIVE is `active=True`.
    """
    return canonical_state(state) == STATE_ACTIVE
