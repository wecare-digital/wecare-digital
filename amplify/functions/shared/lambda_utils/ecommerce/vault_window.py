"""Vault 24-hour access-window math — pure, no I/O.

THE RULE (owner): ₹49 buys ONE access window of VAULT_ACCESS_WINDOW_HOURS (default 24) for one
file. Inside the window every download is free. When it closes it is ₹49 again for a NEW window
on the SAME durable entitlement — no second entitlement row, `accessWindowCount` increments.

Why a window and not permanent access: the durable VAULT_ENTITLEMENT already survives forever as
the paid record. The WINDOW is a separate, time-bounded grant of transport ON TOP of it. Keeping
the two apart means a failed delivery or a rollback never destroys the proof of payment, and a
renewal never duplicates the entitlement.

Design points this module encodes:
  * The window opens AT DELIVERY, not at payment. `open_window` stamps `accessWindowStartedAt`
    now and `accessWindowEndsAt = now + hours*3600`. A grace of
    VAULT_ACCESS_WINDOW_GRACE_SECONDS (default 300) is added to the OPEN check only, so a
    customer mid-download at the boundary is not cut off by clock skew.
  * `window_open` is the single predicate the redeem path and the workspace status both read, so
    "ends in Xh" on screen and "free re-download" in the backend can never disagree.
  * Opening is idempotent: if a window is already open, `open_window` returns the entitlement
    unchanged (same count) — this is what stops a duplicate tap / webhook replay from charging or
    double-incrementing.
  * Windows are paid for one at a time. `paidWindowCount` counts the ₹49 purchases on the
    entitlement (a missing counter means the one original purchase) and `accessWindowCount`
    counts the windows opened; a window opens only against an unused paid one. A renewal
    payment adds one to `paidWindowCount`, so it can never be lost by arriving while a window
    is still open, and a re-delivery can never open a window nobody paid for.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

DEFAULT_WINDOW_HOURS = 24
DEFAULT_GRACE_SECONDS = 300


def window_hours() -> int:
    """Configured window length in hours (>=1). Read per call so a config change is live."""
    try:
        return max(1, int(os.environ.get("VAULT_ACCESS_WINDOW_HOURS", str(DEFAULT_WINDOW_HOURS))))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_HOURS


def window_grace_seconds() -> int:
    """Grace added to the OPEN check only (>=0)."""
    try:
        return max(0, int(os.environ.get("VAULT_ACCESS_WINDOW_GRACE_SECONDS", str(DEFAULT_GRACE_SECONDS))))
    except (TypeError, ValueError):
        return DEFAULT_GRACE_SECONDS


def window_ends_at(entitlement: Optional[Dict[str, Any]]) -> int:
    """The entitlement's window end epoch-seconds, or 0 if no window has ever opened."""
    if not entitlement:
        return 0
    try:
        return int(entitlement.get("accessWindowEndsAt") or 0)
    except (TypeError, ValueError):
        return 0


def window_count(entitlement: Optional[Dict[str, Any]]) -> int:
    """How many windows have been opened on this entitlement (0 before the first)."""
    if not entitlement:
        return 0
    try:
        return int(entitlement.get("accessWindowCount") or 0)
    except (TypeError, ValueError):
        return 0


def paid_window_count(entitlement: Optional[Dict[str, Any]]) -> int:
    """How many ₹49 windows this entitlement has been paid for (0 without an entitlement).

    A renewal adds one to `paidWindowCount` on the SAME entitlement. An entitlement written
    before renewals existed has no counter and stands for its one original purchase, so a
    missing value reads as 1, never 0: reading it as 0 would lock out every customer who paid
    before this counter existed.
    """
    if not entitlement:
        return 0
    raw = entitlement.get("paidWindowCount")
    if raw in (None, ""):
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def unused_paid_windows(entitlement: Optional[Dict[str, Any]]) -> int:
    """Paid windows not yet opened. A window opens on first download, so this is usually 0 or 1."""
    return max(0, paid_window_count(entitlement) - window_count(entitlement))


def window_open(entitlement: Optional[Dict[str, Any]], now: int,
                grace: Optional[int] = None) -> bool:
    """True strictly before entitlement expiry (optional explicit grace only)."""
    ends = window_ends_at(entitlement)
    if ends <= 0:
        return False
    # A new download or resend must never extend the purchased 24-hour window.
    # An already-issued S3 GET can finish within its separately bounded URL TTL.
    # A historical config grace is opt-in only, never the authorization default.
    g = 0 if grace is None else max(0, int(grace))
    return int(now) < ends + g


def seconds_remaining(entitlement: Optional[Dict[str, Any]], now: int) -> int:
    """Seconds until the window closes (0 once closed). Excludes grace — the honest number."""
    ends = window_ends_at(entitlement)
    return max(0, ends - int(now)) if ends > 0 else 0


def access_state(entitlement: Optional[Dict[str, Any]], now: int) -> str:
    """One word for what the customer can do with this file right now.

    * ``UNPAID``  - no entitlement: ₹49 buys the first window.
    * ``OPEN``    - a window is open: downloads are free until it closes.
    * ``READY``   - a paid window has not been opened yet: the next download opens it.
    * ``EXPIRED`` - purchased access has ended; no new payment is offered.

    Read by customer and staff owner-bound file guards. No new Vault payment
    may be requested for an expired paid window.
    """
    if not entitlement:
        return "UNPAID"
    if window_open(entitlement, now):
        return "OPEN"
    if unused_paid_windows(entitlement) > 0:
        return "READY"
    return "EXPIRED"


def open_window(entitlement: Dict[str, Any], now: int,
                hours: Optional[int] = None) -> Tuple[Dict[str, Any], bool]:
    """Open a paid window on the entitlement, starting NOW.

    Returns (fields_to_persist, opened). `opened` is False — and the dict carries no changes —
    when a window is ALREADY open, so a duplicate tap / webhook replay neither re-charges nor
    double-increments, and also when every paid window has already been used: a closed window
    cannot be reopened by redelivery or retries. Historical paid-window
    counts are kept to reconcile prior purchases. Otherwise it returns the new window fields with `accessWindowCount` incremented.

    This returns only the attributes to write; the caller owns the conditional DynamoDB update.
    """
    if window_open(entitlement, now) or unused_paid_windows(entitlement) <= 0:
        return {}, False
    h = window_hours() if hours is None else max(1, int(hours))
    ends = int(now) + h * 3600
    fields = {
        "accessWindowStartedAt": int(now),
        "accessWindowEndsAt": ends,
        "accessWindowCount": window_count(entitlement) + 1,
    }
    return fields, True


def status_label(entitlement: Optional[Dict[str, Any]], now: int) -> str:
    """Human status: 'Awaiting purchase' / 'Active · ends in Xh' / 'Paid · opens on first
    download' / 'Expired · no further payment'."""
    if not entitlement:
        return "Awaiting purchase"
    if window_open(entitlement, now, grace=0):
        rem = seconds_remaining(entitlement, now)
        hrs = (rem + 3599) // 3600  # round up: "ends in 1h" until the last hour elapses
        return f"Active \u00b7 ends in {hrs}h"
    if unused_paid_windows(entitlement) > 0:
        return "Paid \u00b7 opens on first download"
    return "Expired \u00b7 no further payment"
