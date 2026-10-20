"""Consent modelled as EVIDENCE, not a boolean.

THE ANTI-PATTERN THIS EXISTS TO RETIRE
--------------------------------------
A Contact row carried `optInWhatsApp` / `optInSms` / `optInEmail` as plain booleans, and the
engage settings page computed an "opted in %" by counting the `True`s. Three things are wrong
with that, and each has a regulator attached:

  * **A boolean has no provenance.** "opted in" cannot answer *who said so, when, through which
    form, for what purpose, with what proof*. When a customer disputes a message, a `True` is
    not evidence - it is an assertion with nothing behind it.
  * **A boolean is overwritable.** A bulk import writing `optInWhatsApp = True` MANUFACTURES
    permission to message someone from an address book that never had it. `provenance.py`
    already forbids a sync touching those flags for exactly this reason (`NEVER_SYNCED`); this
    module is the positive half of the same rule.
  * **OPTED_OUT is not the absence of opt-in.** `False` conflates "never asked" with "asked and
    said no". A withdrawn consent is a first-class, load-bearing state: it must survive and must
    be respected even when a later weaker signal would otherwise flip it.

THE MODEL
---------
Consent is a per-(customer, channel) ledger of EVIDENCE RECORDS. Each record is immutable and
carries::

    channel     WHATSAPP | SMS | EMAIL | RCS | VOICE | PUSH   the routing channel
    state       OPTED_IN | OPTED_OUT | PENDING                what the customer expressed
    source      a declared source name (see SOURCES)          how we learned it
    at          epoch seconds                                 when
    purpose     MARKETING | TRANSACTIONAL | SERVICE | ...      what it covers
    reference   a free-form evidence pointer (form id, ...)   the proof we can produce
    expiry      epoch seconds, optional                       when it lapses

A write APPENDS a record; it never rewrites or deletes a prior one. The CURRENT state of a
channel is the most recent non-expired record for it. History is therefore the full ledger and
is never collapsed to the current boolean - the boolean is derived FROM the ledger, never the
other way round.

WHY THIS IS A PURE MODULE
-------------------------
Like `customer_uuid.py` and `provenance.py`, this holds no AWS client and reads no database. It
decides what a valid record is, how a ledger resolves to a current state, and which imports are
legitimate. The handler owns storage; this owns the rules, so five handlers cannot each invent a
slightly different definition of "opted in".
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence

# ── vocabulary ───────────────────────────────────────────────────────────────

#: The routing channels a consent record can cover. A closed set: an unknown channel is refused
#: rather than stored, because a typo'd channel is a record nobody will ever query.
CHANNELS: FrozenSet[str] = frozenset({
    "WHATSAPP", "SMS", "EMAIL", "RCS", "VOICE", "PUSH",
})

OPTED_IN = "OPTED_IN"
OPTED_OUT = "OPTED_OUT"
#: We asked and are awaiting a reply (double opt-in in flight). Not permission to send.
PENDING = "PENDING"

#: Every state a record may carry. OPTED_OUT is first-class here, not the absence of OPTED_IN.
STATES: FrozenSet[str] = frozenset({OPTED_IN, OPTED_OUT, PENDING})

#: Only this state is permission to send. Stated as a set so the rule is one edit, not a literal
#: scattered across callers.
SENDABLE_STATES: FrozenSet[str] = frozenset({OPTED_IN})

MARKETING = "MARKETING"
TRANSACTIONAL = "TRANSACTIONAL"
SERVICE = "SERVICE"
#: What a consent record covers. Marketing is the one the law cares most about; transactional
#: and service are narrower. Defaulting is deliberate (MARKETING) because the strictest purpose
#: is the safe default when a caller does not say.
PURPOSES: FrozenSet[str] = frozenset({MARKETING, TRANSACTIONAL, SERVICE})

#: Where a consent signal came from, and whether that source is allowed to assert OPT-IN at all.
#:
#: The distinction is the whole safety property of the import path: a source that merely found a
#: number in an address book (`CSV_IMPORT`, `ADDRESS_BOOK`) may record EXISTING evidence of a
#: prior opt-in, but may NEVER be the thing that creates the opt-in. Only a source where the
#: customer themselves acted (a form, a reply, a double-opt-in confirmation, a verified checkout)
#: may ORIGINATE an opt-in.
SOURCES: Dict[str, bool] = {
    # source name              : may originate an OPT_IN
    "WEB_FORM": True,
    "FLOW_SUBMISSION": True,
    "WHATSAPP_REPLY": True,
    "DOUBLE_OPT_IN": True,
    "CHECKOUT_VERIFIED": True,
    "DASHBOARD": True,          # a human on our side recording a consent a customer gave offline
    "CUSTOMER_REQUEST": True,   # an unsubscribe/opt-out the customer asked for
    # Imports carry evidence of consent that happened ELSEWHERE; they never originate one.
    "CSV_IMPORT": False,
    "ADDRESS_BOOK": False,
    "MIGRATION": False,
}

#: The contact-row attribute the append-only ledger is stored under. One spelling.
ATTRIBUTE = "consentLedger"


class InvalidConsentRecord(ValueError):
    """A record that is not a storable consent evidence record. Refused, never coerced."""


class ConsentImportRefused(ValueError):
    """An import that would manufacture opt-in rather than carry existing evidence."""


# ── building and validating a record ───────────────────────────────────────────

def _norm(value: Optional[str]) -> str:
    return (value or "").strip().upper().replace("-", "_").replace(" ", "_")


def normalize_channel(channel: Optional[str]) -> str:
    key = _norm(channel)
    if key not in CHANNELS:
        raise InvalidConsentRecord(f"unknown consent channel {channel!r}")
    return key


def normalize_state(state: Optional[str]) -> str:
    key = _norm(state)
    if key not in STATES:
        raise InvalidConsentRecord(f"unknown consent state {state!r}")
    return key


def normalize_source(source: Optional[str]) -> str:
    key = _norm(source)
    if key not in SOURCES:
        raise InvalidConsentRecord(f"unknown consent source {source!r}")
    return key


def normalize_purpose(purpose: Optional[str]) -> str:
    if purpose in (None, ""):
        # The strictest purpose is the safe default: a record that does not say what it covers
        # must not be treated as covering the narrowest, most-permissive thing.
        return MARKETING
    key = _norm(purpose)
    if key not in PURPOSES:
        raise InvalidConsentRecord(f"unknown consent purpose {purpose!r}")
    return key


def may_originate_opt_in(source: str) -> bool:
    """True when this source is allowed to CREATE an opt-in, not merely carry existing evidence.

    An address book cannot consent on a customer's behalf, so the import sources answer False.
    """
    return SOURCES.get(normalize_source(source), False)


def build_record(*, channel: str, state: str, source: str, at: int,
                 purpose: Optional[str] = None, reference: Optional[str] = None,
                 expiry: Optional[int] = None) -> Dict[str, Any]:
    """One immutable consent evidence record, fully validated, or raise.

    Validation is strict rather than lenient on purpose: this value is the evidence we would
    produce in a dispute, so a half-formed record is worse than a refused one.
    """
    channel = normalize_channel(channel)
    state = normalize_state(state)
    source = normalize_source(source)
    purpose = normalize_purpose(purpose)

    try:
        at_int = int(at)
    except (TypeError, ValueError):
        raise InvalidConsentRecord(f"consent timestamp is not an epoch int: {at!r}")
    if at_int <= 0:
        raise InvalidConsentRecord("consent timestamp must be a positive epoch")

    record: Dict[str, Any] = {
        "channel": channel,
        "state": state,
        "source": source,
        "at": at_int,
        "purpose": purpose,
    }
    if reference not in (None, ""):
        record["reference"] = str(reference)[:500]
    if expiry not in (None, ""):
        try:
            expiry_int = int(expiry)
        except (TypeError, ValueError):
            raise InvalidConsentRecord(f"consent expiry is not an epoch int: {expiry!r}")
        if expiry_int <= 0:
            raise InvalidConsentRecord("consent expiry must be a positive epoch")
        record["expiry"] = expiry_int
    return record


def is_record(value: Any) -> bool:
    """True for a stored dict that re-validates as a consent record. Never raises."""
    if not isinstance(value, Mapping):
        return False
    try:
        build_record(
            channel=value.get("channel"),
            state=value.get("state"),
            source=value.get("source"),
            at=value.get("at"),
            purpose=value.get("purpose"),
            reference=value.get("reference"),
            expiry=value.get("expiry"),
        )
    except InvalidConsentRecord:
        return False
    return True


# ── the ledger ─────────────────────────────────────────────────────────────────

def ledger_of(contact: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The stored append-only ledger on a row, or `[]`. Only valid records survive the read.

    A junk entry is dropped rather than raising, because a renderer reading a customer's consent
    history must degrade to "the records we can trust" rather than failing the whole page.
    """
    if not contact:
        return []
    raw = contact.get(ATTRIBUTE)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [dict(entry) for entry in raw if is_record(entry)]


def append(contact: Optional[Mapping[str, Any]], record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The ledger with `record` appended. Never mutates the input, never drops prior history.

    This is the whole append-only guarantee in one function: a new state does not overwrite an
    earlier record, it is layered on top of it, and `current_state` reads the latest. An
    identical consecutive record (same channel/state/source/at) is collapsed so a replayed write
    does not duplicate the ledger - but a genuine state change is always a new row.
    """
    if not is_record(record):
        raise InvalidConsentRecord("refusing to append an invalid consent record")
    existing = ledger_of(contact)
    normalized = build_record(
        channel=record.get("channel"), state=record.get("state"),
        source=record.get("source"), at=record.get("at"),
        purpose=record.get("purpose"), reference=record.get("reference"),
        expiry=record.get("expiry"),
    )
    if existing and existing[-1] == normalized:
        return existing
    return [*existing, normalized]


def _active(record: Mapping[str, Any], now: int) -> bool:
    expiry = record.get("expiry")
    if expiry in (None, ""):
        return True
    try:
        return int(expiry) > now
    except (TypeError, ValueError):
        return True


def current_state(contact: Optional[Mapping[str, Any]], channel: str, *,
                  now: int, purpose: Optional[str] = None) -> str:
    """The channel's current consent state, derived from the ledger. PENDING/absent -> that.

    The most recent non-expired record for the channel wins. A purpose filter is honoured when
    given, so a MARKETING query does not see a TRANSACTIONAL-only consent. When no record exists
    the answer is PENDING - never OPTED_IN - because the floor for sending is explicit evidence,
    not the absence of a refusal.
    """
    channel = normalize_channel(channel)
    want_purpose = normalize_purpose(purpose) if purpose else None
    best: Optional[Dict[str, Any]] = None
    for record in ledger_of(contact):
        if record["channel"] != channel:
            continue
        if want_purpose and record["purpose"] != want_purpose:
            continue
        if not _active(record, now):
            continue
        if best is None or record["at"] >= best["at"]:
            best = record
    if best is None:
        return PENDING
    return best["state"]


def is_sendable(contact: Optional[Mapping[str, Any]], channel: str, *,
                now: int, purpose: Optional[str] = None) -> bool:
    """True only when the channel's current state is explicit permission to send.

    OPTED_OUT and PENDING are both False - the difference between them matters for the UI, not
    for whether we may send.
    """
    return current_state(contact, channel, now=now, purpose=purpose) in SENDABLE_STATES


def summarize(contact: Optional[Mapping[str, Any]], *, now: int) -> Dict[str, Dict[str, Any]]:
    """Per-channel current state plus evidence depth, for a consent surface. No raw values.

    Returns `{channel: {state, source, at, purpose, reference, expiry, history}}` for every
    channel that has at least one record. `history` is the count, so the UI can show "3 records"
    without the module deciding how to render them.
    """
    summary: Dict[str, Dict[str, Any]] = {}
    ledger = ledger_of(contact)
    for channel in sorted(CHANNELS):
        channel_records = [r for r in ledger if r["channel"] == channel]
        if not channel_records:
            continue
        latest = max(channel_records, key=lambda r: r["at"])
        summary[channel] = {
            "state": current_state(contact, channel, now=now),
            "latestRecordState": latest["state"],
            "source": latest["source"],
            "at": latest["at"],
            "purpose": latest["purpose"],
            "reference": latest.get("reference", ""),
            "expiry": latest.get("expiry"),
            "history": len(channel_records),
            "sendable": is_sendable(contact, channel, now=now),
        }
    return summary


# ── import ───────────────────────────────────────────────────────────────────

def record_from_import(row: Mapping[str, Any], *, now: int) -> Dict[str, Any]:
    """Build a consent record from an imported row, or refuse. NEVER manufactures opt-in.

    The rule the import path exists to enforce: an imported row carries EXISTING evidence of a
    consent that happened elsewhere, with its own source, timestamp and reference. An import
    source (`CSV_IMPORT`, `ADDRESS_BOOK`, `MIGRATION`) is not permitted to ORIGINATE an opt-in,
    so a row that claims `state=OPTED_IN` from such a source is refused unless it also names a
    timestamped, referenced prior evidence AND an originating source that is allowed to opt in.

    An imported row with no evidence does not become opted-in: a row missing a usable source/state
    is refused rather than defaulted to OPTED_IN. The one state an import may always carry is
    OPTED_OUT - honouring a prior unsubscribe can never over-permission anyone.
    """
    state = normalize_state(row.get("state"))
    channel = normalize_channel(row.get("channel"))

    import_source = row.get("importSource") or row.get("source") or "CSV_IMPORT"
    import_source = normalize_source(import_source)

    at = row.get("at") or row.get("timestamp")
    if at in (None, ""):
        raise ConsentImportRefused(
            "imported consent evidence must carry the timestamp it was originally captured")

    # OPTED_OUT is always safe to import: it only ever removes permission.
    if state == OPTED_OUT:
        return build_record(channel=channel, state=OPTED_OUT, source=import_source, at=at,
                             purpose=row.get("purpose"),
                             reference=row.get("reference") or row.get("evidence"),
                             expiry=row.get("expiry"))

    if state == PENDING:
        # Importing "we were waiting for a reply" grants no permission, so it is allowed to carry
        # the import source directly.
        return build_record(channel=channel, state=PENDING, source=import_source, at=at,
                             purpose=row.get("purpose"),
                             reference=row.get("reference") or row.get("evidence"),
                             expiry=row.get("expiry"))

    # state == OPTED_IN: this is the dangerous one. It is only allowed when the row names the
    # ORIGINAL source that captured the opt-in (which must itself be allowed to originate one)
    # AND a reference/evidence pointer we could produce in a dispute.
    origin = row.get("evidenceSource") or row.get("originalSource")
    reference = row.get("reference") or row.get("evidence")
    if not origin or not reference:
        raise ConsentImportRefused(
            "an imported OPT_IN must name the original opt-in source and an evidence reference; "
            "an address book cannot manufacture consent")
    origin = normalize_source(origin)
    if not may_originate_opt_in(origin):
        raise ConsentImportRefused(
            f"source {origin} is not permitted to originate an opt-in")
    return build_record(channel=channel, state=OPTED_IN, source=origin, at=at,
                         purpose=row.get("purpose"), reference=reference,
                         expiry=row.get("expiry"))


__all__ = [
    "CHANNELS", "STATES", "PURPOSES", "SOURCES", "SENDABLE_STATES",
    "OPTED_IN", "OPTED_OUT", "PENDING",
    "MARKETING", "TRANSACTIONAL", "SERVICE",
    "ATTRIBUTE",
    "InvalidConsentRecord", "ConsentImportRefused",
    "normalize_channel", "normalize_state", "normalize_source", "normalize_purpose",
    "may_originate_opt_in", "build_record", "is_record",
    "ledger_of", "append", "current_state", "is_sendable", "summarize",
    "record_from_import",
]
