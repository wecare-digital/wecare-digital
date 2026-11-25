"""Pure parsing and routing policy for one normalized inbound webhook change.

The transport envelopes are still owned by lambda_utils.wa_internal_event.
This module never calls providers, persists data or triggers customer automation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection

COEXISTENCE_FIELDS = frozenset({"smb_app_state_sync", "smb_message_echoes"})
# These changes can carry `value.messages`, but belong to separate replay
# handling. Neither messages nor statuses from them belong to the live lane.
AUDIT_ONLY_REPLAY_FIELDS = COEXISTENCE_FIELDS | {"history"}
RETIRED_ROUTING_FIELDS = frozenset({"standby", "messaging_handovers"})
IGNORED_ROUTING_EVENT = "webhook_field_ignored"


@dataclass(frozen=True)
class InboundChange:
    field: str
    value: dict
    metadata: dict

    @property
    def retired_routing(self) -> bool:
        return self.field in RETIRED_ROUTING_FIELDS

    @property
    def live_messages(self) -> list:
        if self.retired_routing or self.field in AUDIT_ONLY_REPLAY_FIELDS:
            return []
        return self.value.get("messages", [])

    @property
    def live_statuses(self) -> list:
        if self.retired_routing or self.field in AUDIT_ONLY_REPLAY_FIELDS:
            return []
        return self.value.get("statuses", [])


def parse_change(change: dict) -> InboundChange:
    # Keep malformed record handling in the worker's existing bounded DLQ path.
    value = change.get("value", {})
    return InboundChange(change.get("field", ""), value, value.get("metadata", {}))


def ignored_account_label(entry_id: Any, envelope_id: Any, known_wabas: Collection[str]) -> str:
    """Log only an owned WABA ID, never an arbitrary value from an envelope."""
    entry_id = str(entry_id or "").strip()
    envelope_id = str(envelope_id or "").strip()
    if entry_id and envelope_id and entry_id != envelope_id:
        return "unknown-or-partner"
    candidate = entry_id or envelope_id
    return candidate if candidate in known_wabas else "unknown-or-partner"


def contacts_by_identity(value: dict) -> dict:
    """Index Meta's contact profile by either phone or business-scoped identity."""
    contacts = {}
    for contact_info in value.get("contacts", []):
        phone = contact_info.get("wa_id", "")
        bsuid = contact_info.get("user_id", "")
        profile = contact_info.get("profile", {})
        entry = {
            "name": profile.get("name", ""),
            "bsuid": bsuid,
            "parent_bsuid": contact_info.get("parent_user_id", ""),
            "username": profile.get("username", ""),
            "contact_book_name": profile.get("contact_book_name", ""),
            "wa_id": phone,
        }
        if phone:
            contacts[phone] = entry
        if bsuid:
            contacts[bsuid] = entry
    return contacts


def sender_profile(message: dict, contacts: dict) -> dict:
    """Prefer the message's identity; use its profile record only as a fallback."""
    bsuid = message.get("from_user_id", "")
    parent_bsuid = message.get("from_parent_user_id", "")
    entry = contacts.get(message.get("from", "")) or contacts.get(bsuid) or {}
    if not isinstance(entry, dict):
        return {"sender_profile_name": entry, "sender_bsuid": bsuid,
                "sender_parent_bsuid": parent_bsuid, "sender_username": "",
                "sender_contact_book_name": ""}
    return {
        "sender_profile_name": entry.get("name", ""),
        "sender_bsuid": bsuid or entry.get("bsuid", ""),
        "sender_parent_bsuid": parent_bsuid or entry.get("parent_bsuid", ""),
        "sender_username": entry.get("username", ""),
        "sender_contact_book_name": entry.get("contact_book_name", ""),
    }
