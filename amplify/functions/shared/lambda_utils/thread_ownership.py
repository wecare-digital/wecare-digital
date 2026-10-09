"""WhatsApp Conversation Routing: parse `messaging_handovers` payloads.

Why a parser is needed before anything acts on one
--------------------------------------------------
Meta's Conversation Routing has no ownership API. The docs are explicit that an
integration must *derive* ownership rather than query it, from four signals: messages
we receive, `messaging_handovers` events, standby events, and Service messages we send.
This module owns the first piece of that — turning a `messaging_handovers` webhook into
a normalised record — and deliberately takes no decision from it.

Three payload shapes are in evidence, and none of them is the documented one
-----------------------------------------------------------------------------
Ten real handover events are stored in `SystemConfigTable`'s audit ring buffer from
2026-07-29 to 2026-08-01, back when routing was live on both WABAs. Read directly, they
carry either a bare JSON-**string** `metadata` holding a `reason`, or the intermediate
`previous_owner_app_id` / `previous_owner_app_role` pair. Meta's current
[Thread control](https://developers.facebook.com/documentation/business-messaging/whatsapp/conversation-routing/thread-control/)
docs specify `previous_owner_role` / `new_owner_role` instead.

So a parser written from the stored samples would be wrong the moment routing resumes,
and a parser written only from the docs would fail on everything we have actually seen.
This one is written from the docs and *tolerates* the two legacy shapes, recording which
one matched in `shape` — so retiring a legacy arm later is a measurement rather than a
guess.

`conversation_context` is documented as conditional. It is never assumed present; the
default is `None`, and a caller must treat "absent" as normal rather than as an error.

Parsing must never raise
------------------------
Every return path is a dict. An unreadable payload yields `shape='unknown'` with
whatever fields were legible, because the caller is an audit arm on the inbound webhook
path: a malformed handover must not be able to change what happens to the customer
message arriving beside it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: The two control-change events. `control_passed` means a responder handed the thread
#: on; `control_taken` means one claimed it. Which of the two *we* are on either side of
#: is decided by the roles, not by the event name.
CONTROL_PASSED = "control_passed"
CONTROL_TAKEN = "control_taken"

#: Values `shape` can take, so a caller can count them rather than string-match.
SHAPE_DOCUMENTED = "documented"
SHAPE_LEGACY_METADATA_STRING = "legacy_metadata_string"
SHAPE_LEGACY_APP_ROLE = "legacy_app_role"
SHAPE_UNKNOWN = "unknown"


def _as_dict(raw: Any) -> Dict[str, Any]:
    """A dict from either a dict or a JSON string, else `{}`.

    The legacy `metadata` arrives as a bare JSON **string** carrying a `reason`
    (`'{"reason": "MARKETING_MESSAGE"}'`), which is shape (a) in the module docstring.
    Passing a dict straight through is what keeps the documented shape on the same code
    path instead of a second branch.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _first_contact(value: Dict[str, Any]) -> Dict[str, Any]:
    contacts = value.get("contacts")
    if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict):
        return contacts[0]
    return {}


def parse_handover(value: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a `messaging_handovers` webhook `value` into a flat record.

    Returns, always:

        control               'control_passed' | 'control_taken' | ''
        previous_owner_role   str  (documented field, or the legacy *_app_role)
        new_owner_role        str
        previous_owner_app_id str  ('' unless the legacy shape carried one)
        metadata              dict (JSON-decoded when it arrived as a string)
        reason                str  (lifted out of metadata, which is where every
                                    stored sample actually put it)
        conversation_context  dict | None  -- CONDITIONAL, never assume present
        phone_number_id       str
        wa_id                 str  (a phone number: mask it before logging)
        bsuid                 str  (business-scoped, not a phone number)
        shape                 one of the SHAPE_* constants

    Never raises.
    """
    record: Dict[str, Any] = {
        "control": "",
        "previous_owner_role": "",
        "new_owner_role": "",
        "previous_owner_app_id": "",
        "metadata": {},
        "reason": "",
        "conversation_context": None,
        "phone_number_id": "",
        "wa_id": "",
        "bsuid": "",
        "shape": SHAPE_UNKNOWN,
    }
    if not isinstance(value, dict):
        return record

    try:
        # Canonical handovers identify the business in recipient and peer in sender.
        # Retain metadata/contacts and nested-block fallbacks for older payloads.
        canonical_recipient = _as_dict(value.get("recipient"))
        canonical_sender = _as_dict(value.get("sender"))
        record["phone_number_id"] = str(
            canonical_recipient.get("phone_number_id")
            or _as_dict(value.get("metadata")).get("phone_number_id") or ""
        )
        contact = _first_contact(value)
        record["wa_id"] = str(canonical_sender.get("phone_number") or contact.get("wa_id") or "")
        # BSUID is spelled `user_id` on a contact and `from_user_id` on a message.
        record["bsuid"] = str(
            contact.get("user_id") or contact.get("from_user_id") or ""
        )

        # The control block. Documented position is a nested key named after the event;
        # the legacy samples put the same fields flat on `value` with a `type`. Try the
        # nested form first so the documented shape never has to go through a fallback.
        block: Dict[str, Any] = {}
        for name in (CONTROL_PASSED, CONTROL_TAKEN):
            candidate = value.get(name)
            if isinstance(candidate, dict):
                record["control"] = name
                block = candidate
                break
        if not record["control"]:
            flat = str(value.get("type") or value.get("event") or "")
            if flat in (CONTROL_PASSED, CONTROL_TAKEN):
                record["control"] = flat
                block = value

        if not record["control"]:
            return record

        # A nested block may carry its own recipient identifiers; prefer them, because
        # under routing the control change is per-thread and the thread is identified by
        # BSUID rather than by the contacts array.
        recipient = _as_dict(block.get("recipient"))
        record["bsuid"] = str(
            recipient.get("user_id") or block.get("user_id") or record["bsuid"] or ""
        )
        record["wa_id"] = str(
            recipient.get("wa_id") or block.get("wa_id") or record["wa_id"] or ""
        )
        if not record["phone_number_id"]:
            record["phone_number_id"] = str(block.get("phone_number_id") or "")

        record["metadata"] = _as_dict(block.get("metadata"))
        record["reason"] = str(
            record["metadata"].get("reason")
            or block.get("reason")
            or ""
        )

        context = block.get("conversation_context")
        if isinstance(context, dict) and context:
            record["conversation_context"] = context

        documented_previous = block.get("previous_owner_role")
        legacy_previous = block.get("previous_owner_app_role")
        record["previous_owner_role"] = str(documented_previous or legacy_previous or "")
        record["new_owner_role"] = str(
            block.get("new_owner_role") or block.get("new_owner_app_role") or ""
        )
        record["previous_owner_app_id"] = str(block.get("previous_owner_app_id") or "")

        # Shape is decided by which role spelling arrived, then by whether `metadata`
        # needed decoding. Ordered that way because the app-role pair is the more
        # specific signal: a payload can carry both a string metadata and the legacy
        # roles, and the roles are what a reader has to know about.
        if documented_previous or block.get("new_owner_role"):
            record["shape"] = SHAPE_DOCUMENTED
        elif legacy_previous or record["previous_owner_app_id"]:
            record["shape"] = SHAPE_LEGACY_APP_ROLE
        elif isinstance(block.get("metadata"), str) and record["metadata"]:
            record["shape"] = SHAPE_LEGACY_METADATA_STRING
        else:
            record["shape"] = SHAPE_UNKNOWN
    except Exception:  # noqa: BLE001 - see the module docstring: parsing cannot raise
        return record

    return record


# ──────────────────────────────────────────────────────────────────────────────
# Derived ownership state
#
# Everything below WRITES AND LOGS ONLY. Nothing in the fleet gates a send on it in
# this release, deliberately: the docs say to derive ownership, and derived state has
# to be observed to be right before it is allowed to refuse a customer a reply.
# ──────────────────────────────────────────────────────────────────────────────

TABLE_NAME_DEFAULT = "stack-wecare-digital-ThreadOwnershipTable"
TABLE_HASH_KEY = "threadKey"
TABLE_RANGE_KEY = "recordType"

#: The one ownership row per thread.
RECORD_OWNER = "OWNER"
#: Prefix for the per-message standby context rows: `SB#<epoch>#<wamid>`.
RECORD_STANDBY_PREFIX = "SB#"

#: Meta's documented idle reset: a thread returns to idle on its own after 24 hours of
#: USER inactivity, and the docs require reconciling local state against that. Note it is
#: user inactivity, not our activity — sending does not hold a thread open.
IDLE_RESET_SECONDS = 86400

#: Rows self-clean after a week. Deliberately much longer than the 24h idle reset: state
#: that expired at exactly the reset boundary could not be *reconciled against* that
#: reset, because you have to still be holding the stale value to notice it went idle.
RECORD_TTL_SECONDS = 7 * 86400

#: The four documented signals, plus the one we generate ourselves.
#:
#:   message_received      a message arrived on the `messages` field, not `standby`. The
#:                         docs are explicit that RECEIVING is what makes you the owner —
#:                         "you do not have to reply to claim the thread".
#:   handover_gained       a `control_passed` naming us.
#:   handover_lost         a `control_taken` taking the thread from us.
#:   standby_observed      a `standby` copy arrived, so somebody else owns it.
#:   service_message_sent  a Service message we sent was accepted, which can only happen
#:                         if we owned the thread at that moment.
SIGNAL_MESSAGE_RECEIVED = "message_received"
SIGNAL_HANDOVER_GAINED = "handover_gained"
SIGNAL_HANDOVER_LOST = "handover_lost"
SIGNAL_STANDBY_OBSERVED = "standby_observed"
SIGNAL_SERVICE_MESSAGE_SENT = "service_message_sent"

#: What each signal asserts about ownership.
_SIGNAL_OWNERSHIP: Dict[str, bool] = {
    SIGNAL_MESSAGE_RECEIVED: True,
    SIGNAL_HANDOVER_GAINED: True,
    SIGNAL_SERVICE_MESSAGE_SENT: True,
    SIGNAL_HANDOVER_LOST: False,
    SIGNAL_STANDBY_OBSERVED: False,
}

#: Signals that represent the USER doing something. Only these move the idle clock —
#: `service_message_sent` is us, and a business send does not keep a thread alive.
_USER_ACTIVITY_SIGNALS = frozenset({SIGNAL_MESSAGE_RECEIVED, SIGNAL_STANDBY_OBSERVED})

_table_override: Any = None
_dynamodb: Any = None


def table_name() -> str:
    return os.environ.get("THREAD_OWNERSHIP_TABLE", TABLE_NAME_DEFAULT)


def set_table(table: Any) -> None:
    """Inject a table handle. For tests; pass `None` to restore the real resource."""
    global _table_override
    _table_override = table


def _get_table() -> Any:
    """The DynamoDB table handle, resolved lazily.

    Lazy on purpose. A module-scope resource is built at import, which for a Lambda means
    at cold start — and that is the shape that caused a real outage class here before
    (a value read at import is cached for the life of the execution environment). It also
    makes the module unimportable in a test that has no AWS credentials.
    """
    if _table_override is not None:
        return _table_override
    global _dynamodb
    if _dynamodb is None:
        import boto3
        _dynamodb = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _dynamodb.Table(table_name())


def thread_key(phone_number_id: str, bsuid: str = "", wa_id: str = "") -> str:
    """`{phone_number_id}#{bsuid or wa_id}`, or `''` when the thread cannot be identified.

    **BSUID-preferred, `wa_id` fallback.** Meta's guidance is to index standby events by
    business-scoped user ID, and a BSUID is the more stable of the two: a `wa_id` changes
    when a customer changes their phone number, which arrives as a
    `user_changed_user_id` system message this handler already processes.

    The phone id is in the key because **one contact can hold two independent threads** —
    the same person talks to both WABA numbers, and those two threads can have different
    owners at the same moment.

    Returns `''` rather than a partial key when either half is missing. A caller must
    treat `''` as "cannot track this thread" and do nothing, because a key missing its
    identifier would collide every untrackable thread onto one row.
    """
    pid = str(phone_number_id or "").strip()
    identifier = str(bsuid or "").strip() or str(wa_id or "").strip()
    if not pid or not identifier:
        return ""
    return f"{pid}#{identifier}"


def record_signal(phone_number_id: str, *, bsuid: str = "", wa_id: str = "",
                  signal: str, now: Optional[int] = None,
                  conversation_context: Optional[Dict[str, Any]] = None,
                  detail: str = "") -> Dict[str, Any]:
    """Fold one signal into the thread's ownership row. Write-and-log only.

    Returns the derived state (same shape as `get_state`), or a record with
    `tracked=False` when the thread cannot be keyed or the write failed. **Never raises** —
    ownership bookkeeping must not be able to break inbound message processing, which is
    the path this runs on.

    `conversation_context` is persisted only when present. It carries the previous
    responder's summary of the conversation and arrives only on `control_passed`, and only
    sometimes; overwriting a stored one with `None` would discard the single most useful
    thing a handover ever gives us.
    """
    moment = int(time.time()) if now is None else int(now)
    key = thread_key(phone_number_id, bsuid=bsuid, wa_id=wa_id)
    if not key or signal not in _SIGNAL_OWNERSHIP:
        return {"tracked": False, "owned": False, "idle": False,
                "lastSignal": signal, "updatedAt": moment}

    owned = _SIGNAL_OWNERSHIP[signal]
    names = {"#owned": "owned", "#last": "lastSignal", "#upd": "updatedAt",
             "#exp": "expiresAt", "#act": "lastUserActivityAt", "#det": "lastSignalDetail"}
    values = {":owned": owned, ":last": signal, ":now": moment,
              ":exp": moment + RECORD_TTL_SECONDS, ":det": str(detail or "")[:200]}
    sets = ["#owned = :owned", "#last = :last", "#upd = :now", "#exp = :exp",
            "#det = :det"]

    if signal in _USER_ACTIVITY_SIGNALS:
        sets.append("#act = :now")
    else:
        # Seed it on first write so a thread whose only signal is a handover does not read
        # as idle-since-the-epoch, but never move it forward: only the user moves this
        # clock, and the 24h reset is defined on user inactivity.
        sets.append("#act = if_not_exists(#act, :now)")

    if conversation_context:
        names["#ctx"] = "conversationContext"
        values[":ctx"] = conversation_context
        sets.append("#ctx = :ctx")

    try:
        result = _get_table().update_item(
            Key={TABLE_HASH_KEY: key, TABLE_RANGE_KEY: RECORD_OWNER},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning('{"event":"thread_ownership_write_failed","error":"%s"}',
                       type(exc).__name__)
        return {"tracked": False, "owned": owned, "idle": False,
                "lastSignal": signal, "updatedAt": moment}

    return _derive(result.get("Attributes") or {}, moment)


def _derive(item: Dict[str, Any], moment: int) -> Dict[str, Any]:
    """Turn a stored row into the derived answer, applying the idle reset."""
    last_activity = int(item.get("lastUserActivityAt") or item.get("updatedAt") or moment)
    idle = (moment - last_activity) >= IDLE_RESET_SECONDS
    stored_owned = bool(item.get("owned"))
    return {
        "tracked": True,
        # An idle thread reports NOT owned. The docs say a thread returns to idle on its
        # own after 24h of user inactivity, so a stored `owned=True` older than that is a
        # belief about a thread that no longer exists in that state.
        "owned": stored_owned and not idle,
        "storedOwned": stored_owned,
        "idle": idle,
        "lastSignal": str(item.get("lastSignal") or ""),
        "updatedAt": int(item.get("updatedAt") or 0),
        "lastUserActivityAt": last_activity,
        "conversationContext": item.get("conversationContext") or None,
    }


def get_state(phone_number_id: str, *, bsuid: str = "", wa_id: str = "",
              now: Optional[int] = None) -> Dict[str, Any]:
    """The derived ownership state for a thread. Never raises.

    `tracked` is False when the thread cannot be keyed, when no row exists yet, or when
    the read failed — three different reasons that a caller must not conflate with
    "we do not own it".
    """
    moment = int(time.time()) if now is None else int(now)
    key = thread_key(phone_number_id, bsuid=bsuid, wa_id=wa_id)
    unknown = {"tracked": False, "owned": False, "idle": False,
               "lastSignal": "", "updatedAt": 0}
    if not key:
        return unknown
    try:
        item = _get_table().get_item(
            Key={TABLE_HASH_KEY: key, TABLE_RANGE_KEY: RECORD_OWNER}).get("Item")
    except Exception as exc:  # noqa: BLE001
        logger.warning('{"event":"thread_ownership_read_failed","error":"%s"}',
                       type(exc).__name__)
        return unknown
    if not item:
        return unknown
    return _derive(item, moment)


def may_send(phone_number_id: str, *, bsuid: str = "", wa_id: str = "",
             now: Optional[int] = None) -> bool:
    """May we send a Service message on this thread?

    **Returns `True` when the state is unknown or unreadable.** That is deliberate, and it
    is the opposite of `lambda_utils/otp_throttle.py`'s fail-closed stance — worth stating
    plainly, because the two modules sit next to each other and look similar.

    `otp_throttle` guards a path that spends money and rings a stranger's handset, so an
    unreadable counter must refuse. This guards a path that ANSWERS A CUSTOMER, so an
    unreadable row must not be the reason somebody is left without a reply. Ownership here
    is *derived* state, newly written, never yet observed against real delivery; refusing
    on it would be trusting a belief this release exists to validate.

    The fail-closed decision belongs with the flag flip that starts enforcing this, which
    is deferred until an owner confirms a routing configuration exists.
    """
    state = get_state(phone_number_id, bsuid=bsuid, wa_id=wa_id, now=now)
    if not state.get("tracked"):
        return True
    return bool(state.get("owned"))


def store_standby_message(phone_number_id: str, *, bsuid: str = "", wa_id: str = "",
                          message: Dict[str, Any], content: str = "",
                          now: Optional[int] = None) -> bool:
    """Persist one standby message as standby-MARKED context. Returns True if stored.

    Why every standby message and not just the ones we act on: the docs direct you to
    store incoming standby events locally so you can retrieve them quickly if you receive
    control, indexed by BSUID. The free-form ones are precisely the conversation the OTHER
    responder is handling, which is the context a later handover would need — and they
    were the ones being discarded.

    These rows go **nowhere near** `MessagesTable` or the Unified Inbox. Marking inbox rows
    is a separate, deferred change; keeping standby context in its own table is what keeps
    it deferrable, because no UI reads this.

    Never raises.
    """
    moment = int(time.time()) if now is None else int(now)
    key = thread_key(phone_number_id, bsuid=bsuid, wa_id=wa_id)
    if not key:
        return False
    message = message or {}
    wamid = str(message.get("id") or "")[:128] or f"nowamid-{moment}"
    try:
        _get_table().put_item(Item={
            TABLE_HASH_KEY: key,
            TABLE_RANGE_KEY: f"{RECORD_STANDBY_PREFIX}{moment}#{wamid}",
            # The marker is the point of the row: a standby copy is NOT a message
            # addressed to us, and anything reading this must be able to tell.
            "standbySourced": True,
            "whatsappMessageId": wamid,
            "messageType": str(message.get("type") or ""),
            "content": str(content or "")[:4000],
            "messageTimestamp": int(message.get("timestamp") or moment),
            "observedAt": moment,
            "expiresAt": moment + RECORD_TTL_SECONDS,
        })
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('{"event":"standby_context_write_failed","error":"%s"}',
                       type(exc).__name__)
        return False


def signal_for_control(record: Dict[str, Any]) -> str:
    """The ownership signal a parsed handover implies, or `''`.

    Thin on purpose, and separate from `parse_handover` so the parser stays pure: the
    mapping from a control event to an ownership claim is a *decision*, and it belongs
    where decisions are, not in the thing that reads bytes.
    """
    control = (record or {}).get("control")
    if control == CONTROL_PASSED:
        return SIGNAL_HANDOVER_GAINED
    if control == CONTROL_TAKEN:
        return SIGNAL_HANDOVER_LOST
    return ""


__all__ = [
    "CONTROL_PASSED",
    "CONTROL_TAKEN",
    "SHAPE_DOCUMENTED",
    "SHAPE_LEGACY_APP_ROLE",
    "SHAPE_LEGACY_METADATA_STRING",
    "SHAPE_UNKNOWN",
    "parse_handover",
    "TABLE_NAME_DEFAULT",
    "TABLE_HASH_KEY",
    "TABLE_RANGE_KEY",
    "RECORD_OWNER",
    "RECORD_STANDBY_PREFIX",
    "IDLE_RESET_SECONDS",
    "RECORD_TTL_SECONDS",
    "SIGNAL_MESSAGE_RECEIVED",
    "SIGNAL_HANDOVER_GAINED",
    "SIGNAL_HANDOVER_LOST",
    "SIGNAL_STANDBY_OBSERVED",
    "SIGNAL_SERVICE_MESSAGE_SENT",
    "table_name",
    "set_table",
    "thread_key",
    "record_signal",
    "get_state",
    "may_send",
    "store_standby_message",
    "signal_for_control",
]
