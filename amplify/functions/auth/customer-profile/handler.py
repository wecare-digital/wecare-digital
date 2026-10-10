"""Authenticated checkout profile -> Workspace Contacts.

The customer's phone and customer id come only from customer_auth.require_customer(event).
The browser may submit first/last name, email, a short-lived email verification proof, and one
structured delivery address. The proof is bound to the normalized email by the public
email-verification Lambda and stored in the shared OTP table. This endpoint validates that proof
server-side before any CRM write.

PRESENCE-DRIVEN, NOT MODE-DRIVEN
--------------------------------
There is no `mode` field and one is never sent. The frontend's mode decides which fields it
posts; this handler decides what is *required* from what is present in the body and what is
already stored on the row this session owns. Presence means the key is there with a non-empty
value: a blank field is treated as ABSENT, never as a request to clear, because nothing in this
flow can clear a saved field — a profile with a blank verified email or a blank address is a
profile that cannot pay.

Consequently a first-time customer emerges from ONE save ready to pay (name + email + proof +
address are all required when this session owns no row), while a returning customer can save a
new address, or correct a name, without re-proving an email they already proved.

No marketing consent is inferred from making a purchase. New rows default opt-in/allowlist fields
to False; an existing contact's explicit choices are preserved.
"""

from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from hashlib import sha256
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, customer_auth, customer_session
from lambda_utils.audit import record_audit
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer as identity
from lambda_utils.identity import customer_uuid
from lambda_utils.identity import provenance
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response
from lambda_utils.validation import sanitize_html

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
OTP_TABLE = os.environ.get("OTP_TABLE", "stack-wecare-digital-DownloadGrantsTable")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
OTP_PEPPER_SECRET_ID = os.environ.get("OTP_PEPPER_SECRET_ID", "wecare/otp/pepper")

PROOF_PURPOSE = "email_verification_proof"
PROOF_PREFIX = "email-proof#"
CUSTOMER_TAG = "Customer"

#: Stamped on a row this session linked to itself, as the reason the link was allowed. A code,
#: so the row never stores a second copy of the customer's identity.
CLAIM_EVIDENCE_INBOUND = "WHATSAPP_INBOUND"

#: The staff-visible marker on a refused link. `/workspace/contacts` renders arbitrary tags as
#: chips and already searches them, so this literal is both the badge and the filter.
CONFLICT_TAG = "Identity Conflict"

#: Refusal reasons that describe the CALLER'S SESSION rather than the contact row, so they must
#: never leave a marker on the row. `UNVERIFIED_PHONE` is the whole set today: it says the Cognito
#: pool has not confirmed this session's number, which is nothing at all about the contact — and
#: stamping a conflict on a customer's own legitimate row, on every save, pollutes the exact CRM
#: surface staff are meant to reconcile from. The audit record is still written, because the
#: attempt happened and is worth reading.
SESSION_SIDE_REFUSALS = frozenset({"UNVERIFIED_PHONE"})

#: One page size for both phone-index reads. `_owned_contact` and the claim MUST agree: if the
#: owned row falls outside the smaller page the claim runs on a view that is missing it, sees the
#: remaining rows as a duplicate pair and refuses `AMBIGUOUS_PHONE` — tagging the customer's own
#: row for a conflict that does not exist. DynamoDB applies `Limit` before the live filter, so
#: beyond this many rows on one number the count can be short; under-counting only happens in a
#: state that already refuses (two or more live rows), so the error direction is safe.
PHONE_PAGE_LIMIT = 10

_dynamodb = None
_secrets = None
_pepper_cache: Dict[str, str] = {}


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _table(name: str):
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _pepper() -> str:
    global _secrets
    if "pepper" in _pepper_cache:
        return _pepper_cache["pepper"]
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    raw = _secrets.get_secret_value(SecretId=OTP_PEPPER_SECRET_ID).get("SecretString", "") or ""
    try:
        parsed = json.loads(raw)
        value = str(parsed.get("pepper") or parsed.get("value") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise RuntimeError("OTP pepper is not configured")
    _pepper_cache["pepper"] = value
    return value


def _proof_digest(email: str) -> str:
    return hmac.new(
        _pepper().encode("utf-8"),
        ("email-proof\x1f" + email).encode("utf-8"),
        sha256,
    ).hexdigest()


def _proof_valid(proof_id: Any, email: str) -> bool:
    proof = str(proof_id or "").strip()
    if not proof or len(proof) > 128:
        return False
    item = _table(OTP_TABLE).get_item(
        Key={"grantId": PROOF_PREFIX + proof}
    ).get("Item") or {}
    if item.get("purpose") != PROOF_PURPOSE:
        return False
    if int(item.get("expiresAt") or 0) < int(time.time()):
        return False
    stored = str(item.get("subjectDigest") or "")
    wanted = _proof_digest(email)
    return bool(stored) and hmac.compare_digest(stored, wanted)


def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _active_match(index: str, field: str, value: str) -> Optional[Dict[str, Any]]:
    result = _table(CONTACTS_TABLE).query(
        IndexName=index,
        KeyConditionExpression=Key(field).eq(value),
        Limit=5,
    )
    for item in result.get("Items") or []:
        if item.get("deletedAt") is None:
            return item
    return None


def _row_deleted(row: Dict[str, Any]) -> bool:
    """The live/deleted convention this table is written with, in one place.

    Two spellings exist and both have to be honoured: `deletedAt` is the soft-delete timestamp
    the CRM writes, `isDeleted` is the archive flag the WhatsApp flows check
    (`flows/customer_orders.py:157`). Reading only one of them would make an archived row look
    live to the claim.
    """
    return row.get("deletedAt") is not None or bool(row.get("isDeleted"))


def _claim_evidence(row: Dict[str, Any]) -> str:
    """The provenance code proving this number's holder reached us, or `''` for none.

    `lastInboundMessageAt` is the signal, and it is chosen because it cleanly separates the two
    writers of a WhatsApp contact. `inbound-whatsapp-handler` stamps it when it creates a row and
    refreshes it on every inbound message, while outbound's `_get_or_create_contact_by_phone`
    creates a row without it and `core/contacts` writes it as `None` (stripped before storage).
    So a truthy value means "this number messaged us", which is the fact a claim needs.

    `fieldSources` is the second arm and the forward path: a `VERIFIED`-trust phone provenance —
    `WHATSAPP_INBOUND`, `TRUECALLER`, or `PAYMENT_VERIFIED` for a completed verified checkout —
    is evidence of the same quality. It is dormant today because nothing on the WhatsApp path
    writes provenance yet (only `core/crm` does), and it costs nothing to honour now.

    Two attributes are deliberately NOT evidence. `bsuid` is written by
    `outbound-whatsapp::_enrich_contact_identity` after a *staff* send, so it proves only that we
    messaged the number. `emailVerifiedAt` is written onto unowned rows by `auth/blog-subscribe`,
    and accepting it would be an email-only claim, which this design forbids outright.
    """
    try:
        if int(row.get("lastInboundMessageAt") or 0) > 0:
            return CLAIM_EVIDENCE_INBOUND
    except (TypeError, ValueError):
        # A poisoned or non-numeric timestamp is not evidence; fall through to provenance.
        pass
    source = provenance.existing_source(row, "phone")
    if not source:
        return ""
    try:
        if provenance.trust_of(source) >= provenance.TRUST[provenance.VERIFIED]:
            return provenance.normalize_source(source)
    except provenance.UnknownSource:
        # An undeclared source has no trust level, so it cannot clear a VERIFIED bar.
        return ""
    return ""


def _claim_candidate(rows: Any, phone: str,
                     phone_verified: bool) -> tuple[Optional[Dict[str, Any]], str]:
    """`(row, '')` when this session may claim that row, `(None, reason)` when it may not.

    `(None, '')` is the third answer and it is not a refusal: there is nothing on this number at
    all, so the caller creates a row the ordinary way.

    WHY A CLAIM IS DEFENSIBLE, stated because it is the security trade. **The phone is not
    browser-supplied.** It comes from a Cognito session that only a WhatsApp OTP can mint, and
    the lookup keys on the normalised form of that proven number. So "a row bearing my verified
    phone, belonging to nobody, which messaged us from that number" is a row about me.

    Every one of these must hold, and each refusal names itself so staff can reconcile it. The
    session check comes FIRST and the order is load-bearing: an unverified session must not be
    able to earn a refusal reason that reads as a statement about the contact data
    (`AMBIGUOUS_PHONE`, `DELETED_CONTACT`), because those reasons are the ones that mark the row.

    - the session's phone is Cognito-verified and non-empty, else `UNVERIFIED_PHONE`;
    - exactly one LIVE row carries that exact phone string — two or more is `AMBIGUOUS_PHONE`,
      because one number held by two records is a question only a human can answer, and all
      tombstones is `DELETED_CONTACT`;
    - the row has no owner at all, else `FOREIGN_OWNER`. This is never an ownership transfer;
    - the row shows inbound evidence, else `NO_INBOUND_EVIDENCE` — a contact typed by staff or
      created by an outbound send proves nothing about who holds the handset.

    Pure: no I/O, so the predicate can be read and tested on its own. Claiming is also NOT
    verifying — the caller writes `checkoutCustomerId` and never `emailVerifiedAt`, so a claimed
    row with an unverified email still cannot pay.
    """
    exact = [row for row in rows if str(row.get("phone") or "").strip() == phone]
    if not exact:
        return None, ""
    if not phone_verified or not phone:
        return None, "UNVERIFIED_PHONE"
    live = [row for row in exact if not _row_deleted(row)]
    if not live:
        return None, "DELETED_CONTACT"
    if len(live) > 1:
        return None, "AMBIGUOUS_PHONE"
    row = live[0]
    if str(row.get("checkoutCustomerId") or "").strip():
        return None, "FOREIGN_OWNER"
    if not _claim_evidence(row):
        return None, "NO_INBOUND_EVIDENCE"
    return row, ""


def _audit_claim(action: str, identity_session: Any, contact_id: str, phone: str,
                 details: Dict[str, Any]) -> None:
    """One audit record per claim outcome, and it carries no identifier anyone could use.

    `phoneLast4` rather than the number, no email and no name: an audit row is read by staff and
    retained for 180 days, so the reason code plus a four-digit tail is what makes a conflict
    reconcilable without copying the customer's identity into a second table.

    `record_audit` already fails open, and this wrapper keeps that property true even for a test
    double or a future sink that does not: an audit failure must not change the HTTP outcome.
    """
    try:
        record_audit(action, actor=identity_session.customer_id, resource_type="contact",
                     resource_id=contact_id,
                     details={**details, "phoneLast4": str(phone or "")[-4:]})
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({"event": "identity_claim_audit_failed",
                                   "error": type(exc).__name__}))


def _refuse_claim(rows: Any, phone: str, reason: str, identity_session: Any) -> None:
    """Record a refused claim and leave staff something to reconcile it from.

    The HTTP answer to the customer stays the existing generic `409 CONTACT_IDENTITY_CONFLICT`,
    which names no reason and discloses no PII — a per-reason code would turn the refusal into an
    oracle for "is this number already owned by somebody". The reason lives here instead: an
    audit record, plus `identityConflictAt`, `identityConflictReason` (a code, never a value) and
    the `Identity Conflict` tag on every live row on that number.

    The tag is the whole of the staff surface and needs no frontend change:
    `/workspace/contacts` renders arbitrary tags as chips and already searches them, so the badge
    and the filter come for free. Ambiguity marks every row involved, because with two records on
    one number either could be the one that is wrong.

    WHICH rows are marked follows one rule: mark the rows the UPSERT can still collide with.
    `_upsert_contact`'s `_active_match` reads only `deletedAt`, so a `deletedAt` tombstone is
    invisible to it — the customer simply gets a fresh row, there is no conflict, and marking a
    tombstone would be noise nobody can act on. An `isDeleted`-only archived row is the opposite:
    `_row_deleted` refuses to claim it while `_active_match` still sees it as live and unowned, so
    it is exactly what earns the permanent 409. It therefore gets the marker, which is the only
    thing that gives staff a row to find. A session-side reason marks nothing at all.

    The audit record names the contact even when nothing is marked, so a refusal is never a
    record with an empty `resource_id`.

    Nothing in here may change the HTTP outcome, so every write is wrapped: a refusal must still
    be a 409 even when the marker write fails.
    """
    exact = [row for row in rows if str(row.get("phone") or "").strip() == phone]
    owned_by_other = any(str(row.get("checkoutCustomerId") or "").strip()
                         for row in exact if not _row_deleted(row))
    _audit_claim("identity.claim_refused", identity_session,
                 contact_key.resolve(exact[0]) if exact else "", phone,
                 {"reason": reason, "ownedByOther": owned_by_other})
    if reason in SESSION_SIDE_REFUSALS:
        return
    now = int(time.time())
    for row in exact:
        contact_id = contact_key.resolve(row)
        if not contact_id or row.get("deletedAt") is not None:
            continue
        _mark_conflict(contact_id, row.get("tags"), reason, now)


def _mark_conflict(contact_id: str, tags: Any, reason: str, now: int, *, retry: bool = True) -> None:
    """One conflict marker write, conditioned on the tag list it merged.

    `tags` is a read-modify-write rather than a `list_append` — the tag must not be duplicated on
    a second refusal, and neither this handler nor `FakeDynamo` uses `list_append` anywhere. The
    cost of read-modify-write is a lost concurrent tag edit, so the write is conditioned on the
    exact list it read and retried once against a consistent re-read. This path fires on refusals
    the customer never asked for, so it is the one read-modify-write in this file that cannot be
    left unguarded.
    """
    values: Dict[str, Any] = {":now": now, ":reason": reason,
                              ":tags": _merge_tags(tags, tag=CONFLICT_TAG)}
    if isinstance(tags, list):
        # The list this merge was computed from, so a tag added in between is not overwritten.
        condition = "attribute_exists(id) AND tags=:expected"
        values[":expected"] = tags
    else:
        # No stored list means there is no tag to lose. `attribute_not_exists` for the absent
        # case; a present non-list is discarded by `_merge_tags` either way, so guarding it would
        # only refuse the marker on a row that is already malformed.
        condition = ("attribute_exists(id) AND attribute_not_exists(tags)"
                     if tags is None else "attribute_exists(id)")
    try:
        _table(CONTACTS_TABLE).update_item(
            Key=contact_key.key(contact_id),
            UpdateExpression=("SET identityConflictAt=:now, identityConflictReason=:reason, "
                              "tags=:tags"),
            ConditionExpression=condition,
            ExpressionAttributeValues=values,
        )
    except Exception as exc:  # noqa: BLE001
        code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code")
        if retry and code == "ConditionalCheckFailedException":
            try:
                fresh = _table(CONTACTS_TABLE).get_item(
                    Key=contact_key.key(contact_id), ConsistentRead=True).get("Item")
            except Exception:  # noqa: BLE001
                fresh = None
            if fresh:
                _mark_conflict(contact_id, fresh.get("tags"), reason, now, retry=False)
                return
        logger.warning(json.dumps({"event": "identity_conflict_marker_failed",
                                   "error": type(exc).__name__}))


def _attempt_claim(phone: str, identity_session: Any) -> Optional[Dict[str, Any]]:
    """Link one unowned WhatsApp-first contact to this session, or return None.

    Runs ONLY when `_owned_contact` found nothing, which is what keeps it a separate step rather
    than a widening: `_owned_contact` still means `checkoutCustomerId == sub` and nothing else,
    so a read never quietly turns into a write.

    The write is one conditional `update_item` and it sets FOUR attributes — the owner, the claim
    timestamp, the evidence code and `updatedAt`. Not the email, not `emailVerifiedAt`, not the
    name, not the address, not `tags`, not the public customer uuid: `_upsert_contact` writes all
    of those immediately afterwards through `_set_fragments`, so repeating them here would be a
    second, unconditioned clobber.

    The condition re-states the predicate at the storage layer, so two concurrent requests cannot
    both win. `attribute_not_exists(checkoutCustomerId) OR checkoutCustomerId=:empty` is
    load-bearing: `_claim_candidate` treats an empty string as unowned, and a bare
    `attribute_not_exists` would refuse exactly those rows.

    Idempotency needs no extra store. A replayed save finds the row already owned, so
    `_owned_contact` returns it and this function never runs. The only remaining case is a
    genuinely concurrent duplicate, which the `ConditionalCheckFailedException` re-read settles:
    if the owner is now this same customer the claim already landed, so the replay returns it.
    """
    table = _table(CONTACTS_TABLE)
    # The SAME page size `_owned_contact` reads, for the reason stated on `PHONE_PAGE_LIMIT`: a
    # claim run on a narrower view than the ownership read would refuse rows that are in fact
    # owned by the caller.
    rows = table.query(IndexName="phone-index",
                       KeyConditionExpression=Key("phone").eq(phone),
                       Limit=PHONE_PAGE_LIMIT).get("Items") or []
    phone_verified = bool(getattr(identity_session, "phone_verified", False))
    candidate, reason = _claim_candidate(rows, phone, phone_verified)
    if candidate is None:
        if reason:
            _refuse_claim(rows, phone, reason, identity_session)
        return None

    contact_id = contact_key.resolve(candidate)
    evidence = _claim_evidence(candidate)
    now = int(time.time())
    try:
        table.update_item(
            Key=contact_key.key(contact_id),
            UpdateExpression=("SET checkoutCustomerId=:customer, identityClaimedAt=:now, "
                              "identityClaimEvidence=:evidence, updatedAt=:now"),
            ConditionExpression=(
                "attribute_exists(id) "
                "AND (attribute_not_exists(checkoutCustomerId) OR checkoutCustomerId=:empty) "
                "AND (attribute_not_exists(deletedAt) OR attribute_type(deletedAt, :nulltype)) "
                "AND (attribute_not_exists(isDeleted) OR isDeleted=:false "
                "OR attribute_type(isDeleted, :nulltype))"),
            ExpressionAttributeValues={
                ":customer": identity_session.customer_id, ":now": now,
                # The CODE, never a phone or an email: this value is stored on the row and read
                # by staff.
                ":evidence": evidence, ":empty": "", ":false": False,
                # `attribute_type(x, 'NULL')` rather than `x=:null`. Comparing an attribute to a
                # NULL-typed operand has no precedent in this codebase and DynamoDB's operand
                # rules for it are not something a test fake can settle; a rejection would arrive
                # as `ValidationException`, which is NOT `ConditionalCheckFailedException`, so it
                # would re-raise and hand a 500 to exactly the customers this claim unblocks.
                # `attribute_type` is the documented way to ask "is this attribute NULL", and
                # both arms are needed because the writers spell "live" two ways: the attribute
                # absent (`core/contacts` strips `None` before storage) or stored as NULL (the
                # CRM writes `deletedAt: None` outright). `_row_deleted` treats an `isDeleted` of
                # None as live too, so the condition has to agree or it would refuse a row the
                # predicate just accepted.
                ":nulltype": "NULL",
            },
        )
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", None) or {}
        if response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        current = table.get_item(Key=contact_key.key(contact_id),
                                 ConsistentRead=True).get("Item") or {}
        if current.get("checkoutCustomerId") == identity_session.customer_id:
            # One winner. The loser of the race is this same customer, so the claim it wanted
            # already exists and re-stamping `identityClaimedAt` would falsify when it happened.
            return current
        _, race_reason = _claim_candidate([current] if current else [], phone, phone_verified)
        if race_reason:
            _refuse_claim([current], phone, race_reason, identity_session)
        return None

    _audit_claim("identity.claim", identity_session, contact_id, phone,
                 {"evidence": evidence})
    logger.info(json.dumps({"event": "identity_claim_linked", "evidence": evidence}))
    # The caller builds its merged response from this row, so the three attributes just written
    # are reflected locally rather than re-read.
    claimed = dict(candidate)
    claimed["checkoutCustomerId"] = identity_session.customer_id
    claimed["identityClaimedAt"] = now
    claimed["identityClaimEvidence"] = evidence
    return claimed


def _owned_contact(phone: str, customer_id: str) -> Optional[Dict[str, Any]]:
    """Locate an editable contact without adopting a legacy or another owner's row.

    The meaning is unchanged and deliberately strict: `checkoutCustomerId == customer_id`, which
    is what makes the claim a separate step rather than a widening of this read. Only the page
    size moved, to the shared `PHONE_PAGE_LIMIT` the claim reads, so the two cannot disagree
    about which rows exist on a number.
    """
    if not customer_id:
        return None
    result = _table(CONTACTS_TABLE).query(
        IndexName="phone-index",
        KeyConditionExpression=Key("phone").eq(phone),
        Limit=PHONE_PAGE_LIMIT,
    )
    return next((item for item in result.get("Items") or []
                 if item.get("deletedAt") is None
                 and item.get("checkoutCustomerId") == customer_id), None)

def _merge_tags(existing: Any, *, tag: str = CUSTOMER_TAG) -> list[str]:
    """`existing` with `tag` added once, case-insensitively, and blanks dropped.

    `tag` is a keyword with the `Customer` default so the three upsert sites read unchanged; the
    conflict marker passes `CONFLICT_TAG`. One implementation, because "add a tag without
    duplicating it" is the same operation either way.
    """
    values = existing if isinstance(existing, list) else []
    out = [str(value).strip() for value in values if str(value).strip()]
    if tag.lower() not in {value.lower() for value in out}:
        out.append(tag)
    return out


def _present(value: Any) -> bool:
    """Whether the browser supplied this field at all.

    A key present with an empty or whitespace-only value counts as **absent**. That is what keeps
    `{"email": ""}` on an address edit from becoming a `400 INVALID_EMAIL` on a request that was
    never trying to change the email, and it is why nothing in this handler can clear a field.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (dict, list)):
        return bool(value)
    return bool(str(value if value is not None else "").strip())


def _stored_email(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """The row's email, normalised, or `None` when there is nothing comparable.

    `normalize_email` raises, and a row written by a CRM import or a People sync may hold a value
    that will not normalise. A failure here returns `None`, which the caller reads as "changed"
    and therefore requires a proof — fail-closed, and it never 500s on legacy data.
    """
    try:
        return identity.normalize_email((row or {}).get("email"))
    except identity.InvalidEmailAddress:
        return None


def _set_fragments(*, name: Optional[str], first_name: Optional[str], last_name: Optional[str],
                   phone: str, email: Optional[str], address: Optional[Dict[str, Any]],
                   proof_validated: bool, tags: Optional[list], tags_if_absent: bool = False,
                   customer_id: str, now: int) -> tuple:
    """`(update_expression, names, values)` for one contact mutation. Only supplied fields appear.

    Always written: `phone`, `phoneVerifiedAt=if_not_exists(...)`, `checkoutProfileUpdatedAt`,
    `updatedAt`. Conditionally: the `name`/`firstName`/`lastName` trio (only when BOTH name parts
    were supplied), `email`, `emailVerifiedAt=:now` (**only** when `proof_validated`), the
    address pair, `tags`, `checkoutCustomerId`.

    `tags_if_absent=True` emits `tags=if_not_exists(tags,:tags)` instead of `tags=:tags`. Site (1)
    passes `False`: it holds the existing row, so `_merge_tags(existing.get("tags"))` is a real
    read-modify-write merge and must win — collapsing it toward `if_not_exists` would stop
    `Customer` ever being added to an existing contact that lacks it, which is the one thing
    `_merge_tags` exists for. Site (3) passes `True`: it is the `ConditionalCheckFailedException`
    race fallback and has NOT read the row, so it must not overwrite tags another writer merged.
    Safe because the racing writer is the same `customer_id` by construction — the id is
    `uuid5(... customer_id)`.
    """
    assignments: list[str] = []
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {":phone": phone, ":now": now}

    if name is not None:
        assignments += ["#name=:name", "firstName=:first", "lastName=:last"]
        names["#name"] = "name"
        values.update({":name": name, ":first": first_name, ":last": last_name})
    assignments.append("phone=:phone")
    if email:
        assignments.append("email=:email")
        values[":email"] = email
    if proof_validated:
        assignments.append("emailVerifiedAt=:now")
    if address is not None:
        # A supplied address overwrites the stored one wholesale. There is no partial-field
        # merge, because a half-merged address is a wrong place of supply.
        assignments += [f"{contact_address.ATTRIBUTE}=:address",
                        f"{contact_address.UPDATED_ATTRIBUTE}=:now"]
        values[":address"] = address
    if tags is not None:
        assignments.append("tags=if_not_exists(tags,:tags)" if tags_if_absent else "tags=:tags")
        values[":tags"] = tags
    if customer_id:
        assignments.append("checkoutCustomerId=:customer")
        values[":customer"] = customer_id
    assignments += ["phoneVerifiedAt=if_not_exists(phoneVerifiedAt,:now)",
                    # The PUBLIC customer id, on exactly the same `if_not_exists` footing as
                    # `phoneVerifiedAt` beside it: minted locally every time and discarded by
                    # DynamoDB when the row already has one, so an existing customer keeps the id
                    # already printed on their invoices. Note it is NOT the row `id` - that is
                    # `uuid5(NAMESPACE_URL, "wecare:checkout-customer:<cognito sub>")` a few lines
                    # down, a hash of the Cognito subject, and therefore not publishable.
                    f"{customer_uuid.ATTRIBUTE}="
                    f"if_not_exists({customer_uuid.ATTRIBUTE},:custuuid)",
                    "checkoutProfileUpdatedAt=:now", "updatedAt=:now"]
    values[":custuuid"] = customer_uuid.new_customer_uuid()

    return "SET " + ", ".join(assignments), names, values


def _upsert_contact(*, customer_id: str, phone: str, email: Optional[str] = None,
                    first_name: Optional[str] = None, last_name: Optional[str] = None,
                    address: Optional[Dict[str, Any]] = None,
                    proof_validated: bool = False) -> Dict[str, Any]:
    phone_match = _active_match("phone-index", "phone", phone)
    # The email index is consulted ONLY when an email was supplied. Without this guard an
    # address-only or name-only save issues `Key("email").eq(None)`, DynamoDB answers
    # `ValidationException`, and the `except Exception` arm turns it into `500 INTERNAL_ERROR` —
    # i.e. every save this flow adds would fail.
    #
    # Consequence, stated as a decision rather than left as a surprise: CONTACT_IDENTITY_CONFLICT
    # cannot fire on an email-less save. That is correct — the conflict exists to stop a phone row
    # and a DIFFERENT email row being merged, and with no email in the body there is no second
    # identity to reconcile. The row being written is the one the phone index resolved, which is
    # the one `_owned_contact` already authorised.
    email_match = _active_match("email-index", "email", email) if email else None
    phone_id = contact_key.resolve(phone_match) if phone_match else ""
    email_id = contact_key.resolve(email_match) if email_match else ""
    if phone_id and email_id and phone_id != email_id:
        raise ValueError("CONTACT_IDENTITY_CONFLICT")

    now = int(time.time())
    # The name trio is recomputed and written only when BOTH parts were supplied.
    name = f"{first_name} {last_name}".strip() if (first_name and last_name) else None
    existing = phone_match or email_match
    table = _table(CONTACTS_TABLE)

    if existing:
        if not customer_id or existing.get("checkoutCustomerId") != customer_id:
            raise ValueError("CONTACT_IDENTITY_CONFLICT")
        # Site (1): the edit path. It holds the row, so tags are a real merge.
        contact_id = contact_key.resolve(existing)
        expression, names, values = _set_fragments(
            name=name, first_name=first_name, last_name=last_name, phone=phone,
            email=email, address=address, proof_validated=proof_validated,
            tags=_merge_tags(existing.get("tags")), tags_if_absent=False,
            customer_id=customer_id, now=now,
        )
        try:
            table.update_item(Key={"id": contact_id}, UpdateExpression=expression,
                              ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer",
                              ExpressionAttributeValues=values,
                              **({"ExpressionAttributeNames": names} if names else {}))
        except Exception as exc:  # noqa: BLE001
            response = getattr(exc, "response", None) or {}
            if response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ValueError("CONTACT_IDENTITY_CONFLICT") from exc
            raise
        return {"contactId": contact_id, "created": False}

    # Site (2): one signed-in customer converges onto one deterministic CRM id when no prior
    # phone/email row exists. Reachable only on creation, where every field is required and
    # therefore present.
    contact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wecare:checkout-customer:{customer_id}"))
    item = {
        **contact_key.contact_item_keys(contact_id),
        # Minted on the create branch for the same reason `_create` in `core/contacts` does: this
        # branch runs only when neither the phone index nor the email index resolved a row, so
        # there is no existing id to preserve. Site (3) below - the race on the deterministic id -
        # goes through `_set_fragments`, which assigns it with `if_not_exists`, so the loser of
        # the race does not replace the winner's id.
        customer_uuid.ATTRIBUTE: customer_uuid.new_customer_uuid(),
        "name": name or "",
        "firstName": first_name or "",
        "lastName": last_name or "",
        "phone": phone,
        "email": email or "",
        "tags": [CUSTOMER_TAG],
        "checkoutCustomerId": customer_id,
        "phoneVerifiedAt": now,
        "checkoutProfileUpdatedAt": now,
        # Purchase/transactional identity is not marketing consent.
        "optInWhatsApp": False,
        "optInEmail": False,
        "optInSms": False,
        "allowlistWhatsApp": False,
        "allowlistEmail": False,
        "allowlistSms": False,
        "createdAt": now,
        "updatedAt": now,
        "deletedAt": None,
    }
    if proof_validated:
        item["emailVerifiedAt"] = now
    if address is not None:
        item[contact_address.ATTRIBUTE] = address
        item[contact_address.UPDATED_ATTRIBUTE] = now
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        return {"contactId": contact_id, "created": True}
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", None) or {}
        if response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        # Site (3): the race on the deterministic id. It shares the composer with site (1), so
        # it can no longer silently drop the address or the proof semantics, and it gains
        # `tags=if_not_exists(...)` plus `checkoutCustomerId`.
        expression, names, values = _set_fragments(
            name=name, first_name=first_name, last_name=last_name, phone=phone,
            email=email, address=address, proof_validated=proof_validated,
            tags=[CUSTOMER_TAG], tags_if_absent=True,
            customer_id=customer_id, now=now,
        )
        try:
            table.update_item(Key={"id": contact_id}, UpdateExpression=expression,
                              ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer",
                              ExpressionAttributeValues=values,
                              **({"ExpressionAttributeNames": names} if names else {}))
        except Exception as exc:  # noqa: BLE001
            response = getattr(exc, "response", None) or {}
            if response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ValueError("CONTACT_IDENTITY_CONFLICT") from exc
            raise
        return {"contactId": contact_id, "created": False}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    identity_session, denied = customer_auth.require_customer(event)
    if denied:
        return _no_store(denied)

    # (1) Shape of the request. `mode` is not accepted and is never sent.
    body = _body(event)
    allowed = {"firstName", "lastName", "email", "emailProof", "address"}
    if set(body) - allowed:
        return _no_store(cors_response(400, {"error": "UNEXPECTED_FIELD"}, origin))

    # (2) The session phone, because the owned-row lookup and every write key on it.
    try:
        phone = identity.normalize_phone_preserving_country(identity_session.phone)
    except identity.InvalidPhoneNumber:
        # MissingCountryCode subclasses InvalidPhoneNumber, so one arm covers both.
        return _no_store(cors_response(400, {"error": "INVALID_SESSION_PHONE"}, origin))

    # (3) The address, BEFORE the main try, and that placement is not stylistic.
    # `UnusableAddress` subclasses `ValueError`, and the main try's `except ValueError` arm ends
    # in a bare `raise` while its `except Exception` arm is a SIBLING on the same try — so an
    # UnusableAddress raised in there escapes handler() as an unhandled Lambda invocation error:
    # no field, no 500 body, and no CORS headers, leaving the browser a network-class failure it
    # cannot read a message out of. A mistyped PIN is the most common error in this form.
    address = None
    if isinstance(body.get("address"), dict) and body["address"]:
        try:
            address = contact_address.normalize_for_storage(body["address"])
        except contact_address.UnusableAddress as bad:
            payload = {"error": "INVALID_ADDRESS", "code": bad.code}
            if bad.field:
                payload["field"] = bad.field
            # No echo of the submitted value: an address in a response body is an address an
            # error-logging layer might capture.
            return _no_store(cors_response(400, payload, origin))

    # (4) The row this session owns, which decides what the rest of the body must carry.
    try:
        owned = _owned_contact(phone, identity_session.customer_id)
        if owned is None:
            # The WhatsApp-first link, and it runs here for two reasons. It is AFTER
            # `_owned_contact` because an existing owned row always wins, and it is BEFORE
            # validation because a claimed row makes this a presence-driven edit rather than a
            # creation — which is the defect: a customer who had been messaging us for months was
            # asked for a name, an email, a fresh email code and an address they had already
            # given. A refusal returns None, so `creating` stays True and `_upsert_contact`
            # produces the same generic 409 it always did.
            owned = _attempt_claim(phone, identity_session)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_profile_error", "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
    creating = owned is None

    # (5) Presence-driven validation, driven by that row.
    first_name = sanitize_html(body.get("firstName"), max_length=100).strip()
    last_name = sanitize_html(body.get("lastName"), max_length=100).strip()
    if creating:
        if not first_name or not last_name:
            return _no_store(cors_response(400, {"error": "NAME_REQUIRED"}, origin))
    elif bool(first_name) != bool(last_name):
        # Half a name is a mistake, not an edit: `name` is recomputed from both parts.
        return _no_store(cors_response(400, {"error": "NAME_REQUIRED"}, origin))

    email = None
    if _present(body.get("email")):
        try:
            email = identity.normalize_email(body.get("email"))
        except identity.InvalidEmailAddress:
            return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))
    elif creating:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))

    if creating and address is None:
        return _no_store(cors_response(
            400, {"error": "INVALID_ADDRESS", "code": "ADDRESS_REQUIRED"}, origin))

    # The email-proof rules are an ORDERED decision list and the first match wins, because two
    # of the cases deliberately overlap.
    if creating:
        # Row 1: a new row needs a proof bound to the submitted email before it can be stamped.
        #
        proof_required = True
    elif _present(body.get("emailProof")) and email is None:
        # Row 2, and it beats row 3: a proof is a claim about an ADDRESS. Binding it to the
        # stored value would let a proof minted in one request verify another, which is the one
        # outcome the verification invariant forbids. Refuse, and leave the row untouched.
        return _no_store(cors_response(400, {"error": "EMAIL_VERIFICATION_REQUIRED"}, origin))
    elif email is None:
        # Row 3, and it beats row 6: an edit that submits no email requires no proof and never
        # writes emailVerifiedAt. A row with an unverified email already cannot pay, so refusing
        # its address save removes the customer's only way forward and adds no protection.
        proof_required = False
    elif email == _stored_email(owned) and owned.get("emailVerifiedAt"):
        # Row 4: re-proving an address that is already proven, from a session that owns the row.
        proof_required = False
    else:
        # Rows 5 and 6: a changed email, or a stored email that was never verified.
        proof_required = True

    # (6) The proof check and the write.
    try:
        if proof_required and not _proof_valid(body.get("emailProof"), email or ""):
            return _no_store(cors_response(400, {"error": "EMAIL_VERIFICATION_REQUIRED"}, origin))
        result = _upsert_contact(
            customer_id=identity_session.customer_id,
            phone=phone,
            email=email,
            first_name=first_name,
            last_name=last_name,
            address=address,
            proof_validated=proof_required,
        )
    except ValueError as exc:
        if str(exc) == "CONTACT_IDENTITY_CONFLICT":
            return _no_store(cors_response(409, {"error": "CONTACT_IDENTITY_CONFLICT"}, origin))
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_profile_error", "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))

    logger.info(json.dumps({"event": "checkout_customer_profile_saved",
                            "created": bool(result.get("created"))}))

    # The POST-WRITE merged view, not an echo. The frontend feeds this reply straight into
    # `setProfile` and `deriveStatus`, so an echo-only response would be a live bug: an
    # address-only save would blank the identity card's name and email, and a name-only save
    # would report addressComplete:false and send a returning customer back to a form they never
    # opened. Each field is the submitted value when one was supplied, otherwise the value on the
    # owned row — built from the row `_owned_contact` already returned, so there is no extra read.
    merged = dict(owned or {})
    if address is not None:
        merged[contact_address.ATTRIBUTE] = address
    if email:
        merged["email"] = email
    if first_name and last_name:
        merged["firstName"] = first_name
        merged["lastName"] = last_name
        merged["name"] = f"{first_name} {last_name}".strip()

    merged_first = str(merged.get("firstName") or "")
    merged_last = str(merged.get("lastName") or "")
    stored_address = contact_address.from_contact(merged)
    return _no_store(cors_response(200, {
        "status": "PROFILE_READY",
        "contactId": result["contactId"],
        "name": (str(merged.get("name") or "").strip()
                 or f"{merged_first} {merged_last}".strip()),
        "firstName": merged_first,
        "lastName": merged_last,
        "email": str(merged.get("email") or ""),
        # The normalised value this handler wrote, which is the same string the read side
        # resolves the row on.
        "phone": phone,
        "addressComplete": stored_address is not None,
        "address": stored_address,
    }, origin))
