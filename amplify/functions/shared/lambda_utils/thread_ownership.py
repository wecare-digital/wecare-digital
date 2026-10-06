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
from typing import Any, Dict, Optional

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
        record["phone_number_id"] = str(
            (value.get("metadata") or {}).get("phone_number_id") or ""
        )
        contact = _first_contact(value)
        record["wa_id"] = str(contact.get("wa_id") or "")
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


__all__ = [
    "CONTROL_PASSED",
    "CONTROL_TAKEN",
    "SHAPE_DOCUMENTED",
    "SHAPE_LEGACY_APP_ROLE",
    "SHAPE_LEGACY_METADATA_STRING",
    "SHAPE_UNKNOWN",
    "parse_handover",
]
