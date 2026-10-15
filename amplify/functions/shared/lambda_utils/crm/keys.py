"""Deterministic CRM identifiers. Two kinds of duplicate, two different mechanisms.

The distinction this module exists to keep
------------------------------------------
**Technical duplicate.** The same Flow webhook delivered twice. Meta retries, SQS
redrives, a Lambda times out after writing. There is exactly one real enquiry and any
second row is corruption. Defence: a deterministic `leadId` derived from the source and
its reference, so the second write is the *same row* and a conditional put rejects it.

**Business duplicate.** The same person enquiring twice in a week about two different
things. Two real enquiries. Collapsing them loses one, and the sales team never learns
about the second product.

These get confused constantly, in both directions, and both directions are damaging: a
hash over the phone number alone silently discards genuine second enquiries, while a
random uuid per webhook delivery fills the funnel with replay noise that inflates every
conversion denominator.

So `lead_id` is keyed on **(source, source reference)** - what arrived - and never on
the person. Person-level grouping is a *query* (`open_lead_index_key`), answered at read
time from the phone-number index, where a human or a policy can decide. It is not
baked into the identity of the row.

Why a hash and not a compound string key
----------------------------------------
A source reference can be a Meta `flow_token`, a Razorpay order id, a `wamid`, or a click
id - arbitrary length, arbitrary characters, and in the WhatsApp case it can embed a phone
number. A hash gives a fixed-width opaque id that is safe to log and safe to put in a URL,
and it cannot accidentally disclose a customer identifier through a lead id appearing in
a browser address bar or an access log.

SHA-256 truncated to 32 hex characters (128 bits). Not for cryptographic strength - these
are not secrets - but so that the collision probability across any plausible volume is
irrelevant. At 10 million leads the chance of any collision is on the order of 1e-24.

The namespace prefix is not decoration
--------------------------------------
`lead_`, `opp_`, `act_`, `pl_`, `stg_` prefixes make a mis-wired id obvious at the point
of failure rather than three tables later. An `opp_` value passed where a `lead_` belongs
fails a cheap assertion instead of silently querying for a row that cannot exist and
returning "not found", which is indistinguishable from a legitimately absent lead.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from typing import Optional

#: 128 bits of a SHA-256 digest, hex encoded.
_DIGEST_CHARS = 32

LEAD_PREFIX = "lead_"
OPPORTUNITY_PREFIX = "opp_"
ACTIVITY_PREFIX = "act_"
PIPELINE_PREFIX = "pl_"
STAGE_PREFIX = "stg_"

#: Sources a lead can arrive from. Closed set, because an open one becomes forty spellings
#: and then no report can group by source - the single most useful CRM dimension there is.
SOURCE_FLOW = "FLOW_SUBMISSION"
SOURCE_AD_CLICK = "AD_CLICK"
SOURCE_INBOUND_WHATSAPP = "INBOUND_WHATSAPP"
SOURCE_INBOUND_RCS = "INBOUND_RCS"
SOURCE_INBOUND_SMS = "INBOUND_SMS"
SOURCE_INBOUND_CALL = "INBOUND_CALL"
SOURCE_WEB_FORM = "WEB_FORM"
SOURCE_MANUAL = "MANUAL"
SOURCE_IMPORT = "IMPORT"

LEAD_SOURCES = (
    SOURCE_FLOW, SOURCE_AD_CLICK, SOURCE_INBOUND_WHATSAPP, SOURCE_INBOUND_RCS,
    SOURCE_INBOUND_SMS, SOURCE_INBOUND_CALL, SOURCE_WEB_FORM,
    SOURCE_MANUAL, SOURCE_IMPORT,
)

#: Sources whose reference is genuinely unique per real-world enquiry, so a deterministic
#: id is correct. A Flow token, a wamid and a Razorpay order id are all single-use.
_DETERMINISTIC_SOURCES = frozenset({
    SOURCE_FLOW, SOURCE_AD_CLICK, SOURCE_INBOUND_WHATSAPP, SOURCE_INBOUND_RCS,
    SOURCE_INBOUND_SMS, SOURCE_INBOUND_CALL, SOURCE_WEB_FORM,
})

_SAFE_ID = re.compile(r"^[a-z]+_[0-9a-f]{32}$")


class InvalidSource(ValueError):
    """An unrecognised lead source. Refused rather than recorded as-is."""


def _digest(*parts: str) -> str:
    """Stable digest over parts, with a separator that cannot appear in a hex digest.

    The `\\x1f` unit separator matters: joining with `:` would make
    ``('a:b', 'c')`` and ``('a', 'b:c')`` hash identically, which is a real collision
    between a Flow token containing a colon and a differently-split pair. Rare, but free
    to prevent.
    """
    joined = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def normalize_source(source: Optional[str]) -> str:
    """Uppercase a source and refuse anything outside the closed set."""
    value = (source or "").strip().upper().replace("-", "_").replace(" ", "_")
    if value not in LEAD_SOURCES:
        raise InvalidSource(
            f"unknown lead source {source!r}; expected one of {', '.join(LEAD_SOURCES)}")
    return value


def source_is_deterministic(source: str) -> bool:
    """Does this source carry a reference unique per real enquiry?

    `MANUAL` and `IMPORT` do not: a human creating two leads for the same contact means
    two leads, and an importer's row number is not a durable reference. Those get random
    ids, so a deliberate duplicate stays a duplicate rather than overwriting the first.
    """
    return normalize_source(source) in _DETERMINISTIC_SOURCES


def lead_id(source: str, source_ref: Optional[str] = None) -> str:
    """The lead id for an arrival.

    Deterministic when the source provides a unique reference, so a replay lands on the
    same row; random otherwise. Falls back to random when a deterministic source arrives
    with an empty reference - a missing flow_token is a provider bug, and hashing `''`
    would make *every* such arrival the same lead, merging unrelated enquiries into one
    row. Losing idempotency for a malformed event is much cheaper than that.
    """
    source = normalize_source(source)
    ref = (source_ref or "").strip()
    if source_is_deterministic(source) and ref:
        return f"{LEAD_PREFIX}{_digest(source, ref)}"
    return f"{LEAD_PREFIX}{uuid.uuid4().hex}"


def opportunity_id_for_lead(lead: str) -> str:
    """The opportunity id a given lead converts into.

    Derived from the lead rather than random, which is what makes conversion idempotent
    *without* a read: a second `convert_lead` computes the same id, and the conditional
    put fails. A random id would need a read-then-write, and two concurrent invocations
    both reading "not converted" would create two opportunities for one lead - the exact
    race this fleet's traffic produces.
    """
    if not lead:
        raise ValueError("lead id is required")
    return f"{OPPORTUNITY_PREFIX}{_digest('convert', lead)}"


def opportunity_id() -> str:
    """A standalone opportunity, created directly rather than from a lead."""
    return f"{OPPORTUNITY_PREFIX}{uuid.uuid4().hex}"


def activity_id(*, at: Optional[int] = None) -> str:
    """An append-only timeline entry id.

    Random, not derived. Two identical notes a second apart are two notes, and a
    content hash would silently drop the second. `at` is accepted and mixed in so that
    ids created in the same microsecond still differ, without making the id *depend* on
    content.
    """
    seed = f"{at if at is not None else time.time_ns()}"
    return f"{ACTIVITY_PREFIX}{_digest('activity', seed, uuid.uuid4().hex)}"


def pipeline_id(name: str) -> str:
    """Deterministic on name, so provisioning the default pipeline twice is a no-op.

    This is the one place a name-derived id is right: a pipeline is configuration, it is
    created by a setup script or an admin screen, and running that script again must not
    produce a second pipeline with the same name and a different id - which would split
    the board in two with no visible cause.
    """
    value = (name or "").strip().lower()
    if not value:
        raise ValueError("pipeline name is required")
    return f"{PIPELINE_PREFIX}{_digest('pipeline', value)}"


def stage_id(pipeline: str, name: str) -> str:
    """Deterministic on (pipeline, name), for the same reason as `pipeline_id`.

    Keyed on the pipeline too, so two pipelines may both have a stage called "Qualified"
    without colliding - and so a stage id can never be valid in the wrong pipeline, which
    `states.stage_move_is_legal` then refuses structurally.
    """
    if not pipeline:
        raise ValueError("pipeline id is required")
    value = (name or "").strip().lower()
    if not value:
        raise ValueError("stage name is required")
    return f"{STAGE_PREFIX}{_digest('stage', pipeline, value)}"


def looks_like(kind_prefix: str, value: Optional[str]) -> bool:
    """Is this a well-formed id of the given kind?

    Used at service boundaries so an `opp_` passed where a `lead_` belongs fails loudly
    instead of querying for a row that cannot exist and returning a "not found" that reads
    exactly like a legitimately absent lead.
    """
    if not value or not isinstance(value, str):
        return False
    if not value.startswith(kind_prefix):
        return False
    return bool(_SAFE_ID.match(value))


def open_lead_index_key(contact_id: str, pipeline: str) -> str:
    """The grouping key for "does this contact already have an open lead here?".

    A *query* key, not an identity. It deliberately does not appear in any row's primary
    key, because business-level dedup is a policy decision that belongs at read time -
    baking it into the id would make a second genuine enquiry impossible to record.
    """
    if not contact_id:
        raise ValueError("contact id is required")
    if not pipeline:
        raise ValueError("pipeline id is required")
    return f"{contact_id}#{pipeline}"
