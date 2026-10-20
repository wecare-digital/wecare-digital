"""Canonical WhatsApp template-status vocabulary.

Meta exposes more states than APPROVED/PENDING/REJECTED. Send eligibility must
never be inferred from "not rejected": PAUSED, DISABLED, FLAGGED and unknown
states are not sendable. Keep raw provider status for diagnostics; use these
helpers for decisions.
"""

from __future__ import annotations

APPROVED = "approved"
PENDING = "pending"
BLOCKED = "blocked"
UNKNOWN = "unknown"

_APPROVED = frozenset({"APPROVED"})
_PENDING = frozenset({"PENDING", "IN_APPEAL"})
_BLOCKED = frozenset({"REJECTED", "PAUSED", "DISABLED", "FLAGGED", "PENDING_DELETION"})


def canonical(raw) -> str:
    word = str(raw or "").strip().upper()
    if word in _APPROVED:
        return APPROVED
    if word in _PENDING:
        return PENDING
    if word in _BLOCKED:
        return BLOCKED
    return UNKNOWN


def is_sendable(raw) -> bool:
    """Only explicit Meta APPROVED is sendable."""
    return canonical(raw) == APPROVED


__all__ = ["APPROVED", "PENDING", "BLOCKED", "UNKNOWN", "canonical", "is_sendable"]
