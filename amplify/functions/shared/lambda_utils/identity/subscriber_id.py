"""Canonical workspace-scoped Subscriber ID and new-contact retention defaults.

`contactId` is the internal row key (sometimes phone-derived or Cognito-derived),
`customerUuid` is the public billing identifier, and a WhatsApp `WD-SUB` flow
reference identifies a *submission*. None is the permanent Subscriber ID.

Subscriber IDs are opaque UUIDv4 values prefixed with a server-owned workspace
slug. They are never accepted from request bodies. A newly created contact is
locked by default; existing contacts are not silently locked during edits.
The Contacts API's dedicated Admin unlock and delete guards own enforcement.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, Optional

SUBSCRIBER_ID_ATTRIBUTE = "subscriberId"
WORKSPACE_ID_ATTRIBUTE = "workspaceId"
DEFAULT_WORKSPACE_ID = "wecare-digital"
CREATION_LOCK_REASON = "created"

_WORKSPACE_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})\Z")


def current_workspace_id() -> str:
    """Return the trusted workspace slug, never a value supplied by a contact."""
    value = str(os.environ.get("WORKSPACE_ID", DEFAULT_WORKSPACE_ID)).strip().lower()
    if not _WORKSPACE_RE.fullmatch(value) or value.endswith("-"):
        raise ValueError("WORKSPACE_ID must be a non-empty lowercase slug")
    return value


def new_subscriber_id(*, workspace_id: Optional[str] = None) -> str:
    """Mint a public, unguessable Subscriber ID with no PII or creation timestamp."""
    workspace = workspace_id if workspace_id is not None else current_workspace_id()
    if not isinstance(workspace, str) or not _WORKSPACE_RE.fullmatch(workspace) or workspace.endswith("-"):
        raise ValueError("Invalid workspace ID")
    return f"WD-{workspace}-{uuid.uuid4()}"


def is_subscriber_id(value: Any, *, workspace_id: Optional[str] = None) -> bool:
    """Only accept canonical workspace-prefixed UUIDv4 strings."""
    if not isinstance(value, str):
        return False
    workspace = workspace_id if workspace_id is not None else current_workspace_id()
    prefix = f"WD-{workspace}-"
    if not value.startswith(prefix):
        return False
    suffix = value[len(prefix):]
    try:
        parsed = uuid.UUID(suffix)
    except (ValueError, TypeError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == suffix


def new_contact_fields(*, now: Optional[int] = None,
                       workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Fields to spread into a NEW ContactsTable row, in the original PutItem."""
    workspace = workspace_id if workspace_id is not None else current_workspace_id()
    ts = int(time.time()) if now is None else int(now)
    return {
        WORKSPACE_ID_ATTRIBUTE: workspace,
        SUBSCRIBER_ID_ATTRIBUTE: new_subscriber_id(workspace_id=workspace),
        "locked": True,
        "lockedReason": CREATION_LOCK_REASON,
        "lockedAt": ts,
    }


__all__ = [
    "SUBSCRIBER_ID_ATTRIBUTE", "WORKSPACE_ID_ATTRIBUTE",
    "DEFAULT_WORKSPACE_ID", "CREATION_LOCK_REASON",
    "current_workspace_id", "new_subscriber_id", "is_subscriber_id",
    "new_contact_fields",
]
