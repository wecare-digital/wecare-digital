"""Which source may overwrite which Contact field.

The problem this exists to stop
-------------------------------
A Contact's `phone` can arrive from an inbound WhatsApp message, where Meta has told us the
number the message genuinely came from. It can also arrive from a Google contact card,
where it is whatever the *account owner* typed into their address book.

Those are not the same quality of fact. One is a delivery-verified identifier; the other is
a note someone made. A naive sync that writes every field it receives will let a stale
address-book entry overwrite a number we have proof of - and the failure is silent, because
the row still looks perfectly well formed. The next message goes to the wrong person.

So each source carries a **trust level per field**, and a write only lands when the
incoming source is at least as trusted as the one already recorded.

The levels
----------
::

    VERIFIED   4   the provider proved it: a wamid's sender, a Truecaller consent assertion
    DECLARED   3   the customer typed it themselves, in our own Flow
    OPERATOR   2   a human on our side entered it in the dashboard
    IMPORTED   1   a third-party address book or bulk upload
    INFERRED   0   derived by us, e.g. a name guessed from a profile string

`VERIFIED` beats everything and equal beats equal, which matters: a second inbound message
must be able to update a contact's own profile name, or the record freezes at whatever the
first message happened to carry.

Why `phone` is special
----------------------
`phone` is the routing key. Every outbound message resolves to it, and `phone-index` is how
the RCS and WhatsApp readers find a contact at all. An import overwriting it does not just
corrupt a field - it redirects a conversation to a different human being.

So `phone` is additionally protected by `LOCKED_FIELDS`: once recorded at `VERIFIED`, no
later source may change it, not even another `VERIFIED` one. Two verified numbers mean two
people, or a number that genuinely changed - and both of those need a human decision, not a
silent overwrite. `needs_review` is how that decision gets queued.

Why the provenance is stored per field, not per row
---------------------------------------------------
A single contact legitimately mixes sources: the phone is VERIFIED from WhatsApp, the
company name is IMPORTED from Google, the address is DECLARED from a Flow. A row-level
"source: google" would either block the import entirely or let it through wholesale.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

VERIFIED = "VERIFIED"
DECLARED = "DECLARED"
OPERATOR = "OPERATOR"
IMPORTED = "IMPORTED"
INFERRED = "INFERRED"

TRUST: Dict[str, int] = {
    VERIFIED: 4,
    DECLARED: 3,
    OPERATOR: 2,
    IMPORTED: 1,
    INFERRED: 0,
}

#: Where a value came from, mapped to how much we trust it. A closed set: an unrecognised
#: source is refused rather than defaulted, because defaulting it would silently pick a
#: trust level nobody chose.
SOURCE_TRUST: Dict[str, str] = {
    # Meta told us the message came from this number. As strong as it gets.
    "WHATSAPP_INBOUND": VERIFIED,
    # A Truecaller consent assertion for the person holding the handset.
    "TRUECALLER": VERIFIED,
    # An OTP or payment we verified end to end.
    "PAYMENT_VERIFIED": VERIFIED,
    # The customer filled our own Flow form.
    "FLOW_SUBMISSION": DECLARED,
    "WEB_FORM": DECLARED,
    # A human on our side.
    "DASHBOARD": OPERATOR,
    "OPERATOR": OPERATOR,
    # Somebody else's address book.
    "GOOGLE_PEOPLE": IMPORTED,
    "CSV_IMPORT": IMPORTED,
    # Our own guesswork.
    "DERIVED": INFERRED,
}

#: Fields where a change is a routing change, so a second verified value queues a review
#: instead of overwriting. `phone` is the routing key for every channel; `bsuid` is Meta's
#: per-portfolio identity and a change there means a different WhatsApp account.
LOCKED_FIELDS: FrozenSet[str] = frozenset({"phone", "bsuid"})

#: Fields a sync may never touch, whatever its trust level.
#:
#: The opt-in and allowlist flags are consent records. An address book cannot consent on a
#: customer's behalf, and letting an import set them would manufacture permission to
#: message someone - which is the one mistake in this file with a regulator attached.
#: `id`/`contactId` are the identity itself (see contact_key).
NEVER_SYNCED: FrozenSet[str] = frozenset({
    "id", "contactId",
    "optInWhatsApp", "optInSms", "optInEmail",
    "allowlistWhatsApp", "allowlistSms", "allowlistEmail",
    "createdAt", "deletedAt",
})

#: The attribute a contact row stores its per-field provenance under.
PROVENANCE_ATTRIBUTE = "fieldSources"


class UnknownSource(ValueError):
    """A source with no declared trust level. Refused rather than defaulted."""


def trust_of(source: Optional[str]) -> int:
    """Trust level for a source name. Raises on anything undeclared."""
    key = (source or "").strip().upper().replace("-", "_").replace(" ", "_")
    if key not in SOURCE_TRUST:
        raise UnknownSource(
            f"unknown contact field source {source!r}; declare it in SOURCE_TRUST with a "
            "deliberate trust level")
    return TRUST[SOURCE_TRUST[key]]


def normalize_source(source: Optional[str]) -> str:
    key = (source or "").strip().upper().replace("-", "_").replace(" ", "_")
    if key not in SOURCE_TRUST:
        raise UnknownSource(f"unknown contact field source {source!r}")
    return key


def existing_source(contact: Optional[Mapping[str, Any]], field: str) -> Optional[str]:
    """The source currently recorded for a field, if any.

    A row written before provenance existed has no `fieldSources`, so this returns None and
    `may_write` treats the field as unclaimed. That is the right default: refusing to write
    would freeze every legacy row, and claiming VERIFIED would let an import inherit a
    trust level it never earned.
    """
    if not contact:
        return None
    sources = contact.get(PROVENANCE_ATTRIBUTE)
    if not isinstance(sources, Mapping):
        return None
    value = sources.get(field)
    return str(value) if value else None


def may_write(contact: Optional[Mapping[str, Any]], field: str, source: str,
              *, incoming_value: Any = None) -> Tuple[bool, str]:
    """`(allowed, reason)` for writing one field from one source.

    Order of checks is deliberate. `NEVER_SYNCED` comes first because it is absolute and
    cheap. The no-op check comes before the lock check so that re-syncing an identical
    value is never reported as a conflict needing review - otherwise a daily incremental
    sync would queue the same review every day.
    """
    normalized = normalize_source(source)

    if field in NEVER_SYNCED:
        return False, f"{field} is never written by a sync"

    current_source = existing_source(contact, field)
    current_value = (contact or {}).get(field)

    if current_value is not None and _same(current_value, incoming_value):
        # Nothing changes. Not a conflict, and not worth a review.
        return False, "value unchanged"

    if field in LOCKED_FIELDS and current_value:
        if current_source and TRUST[SOURCE_TRUST[current_source]] >= TRUST[VERIFIED]:
            return False, (f"{field} is locked at {current_source}; a change needs human "
                           "review, not an overwrite")

    if current_source is None:
        return True, "field unclaimed"

    if trust_of(normalized) >= trust_of(current_source):
        return True, f"{normalized} >= {current_source}"
    return False, f"{normalized} is less trusted than {current_source}"


def needs_review(contact: Optional[Mapping[str, Any]], field: str, source: str,
                 *, incoming_value: Any = None) -> bool:
    """Should a human adjudicate this instead of the sync deciding?

    True only for a locked field whose verified value would change. Everything else the
    trust ladder can settle on its own; this is the narrow case where two sources both have
    a legitimate claim and picking one automatically would be guessing about a person's
    phone number.
    """
    if field not in LOCKED_FIELDS:
        return False
    current_value = (contact or {}).get(field)
    if not current_value or _same(current_value, incoming_value):
        return False
    if incoming_value in (None, ""):
        return False
    current_source = existing_source(contact, field)
    if not current_source:
        return False
    return TRUST[SOURCE_TRUST[current_source]] >= TRUST[VERIFIED]


def _same(a: Any, b: Any) -> bool:
    """Loose equality for comparing a stored value with an incoming one.

    Compares as trimmed strings because DynamoDB hands back `Decimal` where the caller has
    an `int`, and a whitespace difference is not a change worth a write.
    """
    if a is None or b is None:
        return a is b
    return str(a).strip() == str(b).strip()


def apply_fields(contact: Optional[Mapping[str, Any]], incoming: Mapping[str, Any],
                 source: str) -> Dict[str, Any]:
    """Decide a whole sync payload against one contact.

    Returns::

        {
          "updates":  {field: value}    # safe to write
          "sources":  {field: SOURCE}   # provenance to merge into fieldSources
          "skipped":  {field: reason}
          "review":   {field: {"current": ..., "incoming": ...}}
        }

    `review` carries both values so the manual-review surface can show the conflict without
    re-reading the row. It deliberately does not include the field in `updates`: a conflict
    on a routing key must not be applied while it waits for a human.
    """
    normalized = normalize_source(source)
    updates: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    skipped: Dict[str, str] = {}
    review: Dict[str, Dict[str, Any]] = {}

    for field, value in incoming.items():
        if value in (None, ""):
            # An absent value is not an instruction to clear a field. A Google contact with
            # no company must not wipe a company we learned from a Flow.
            skipped[field] = "empty incoming value"
            continue

        if needs_review(contact, field, normalized, incoming_value=value):
            review[field] = {"current": (contact or {}).get(field), "incoming": value}
            skipped[field] = "queued for review"
            continue

        allowed, reason = may_write(contact, field, normalized, incoming_value=value)
        if allowed:
            updates[field] = value
            sources[field] = normalized
        else:
            skipped[field] = reason

    return {"updates": updates, "sources": sources, "skipped": skipped,
            "review": review}


def merged_provenance(contact: Optional[Mapping[str, Any]],
                      sources: Mapping[str, str]) -> Dict[str, str]:
    """`fieldSources` with the new claims merged in.

    Merged rather than replaced, so a partial sync does not erase the provenance of fields
    it did not touch - which would silently demote every untouched field to unclaimed and
    let the next import overwrite it.
    """
    existing = (contact or {}).get(PROVENANCE_ATTRIBUTE)
    merged: Dict[str, str] = dict(existing) if isinstance(existing, Mapping) else {}
    merged.update({k: str(v) for k, v in sources.items()})
    return merged


def describe(contact: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Provenance summary for an audit view. Contains no field *values*."""
    sources = (contact or {}).get(PROVENANCE_ATTRIBUTE)
    sources = dict(sources) if isinstance(sources, Mapping) else {}
    by_trust: Dict[str, int] = {}
    for field_source in sources.values():
        key = SOURCE_TRUST.get(str(field_source), "UNKNOWN")
        by_trust[key] = by_trust.get(key, 0) + 1
    return {
        "fieldsWithProvenance": len(sources),
        "byTrustLevel": by_trust,
        "lockedFieldsClaimed": sorted(f for f in LOCKED_FIELDS if f in sources),
    }
