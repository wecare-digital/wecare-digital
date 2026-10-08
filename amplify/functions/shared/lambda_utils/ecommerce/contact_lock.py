"""Lock a contact as a paying customer, for legal retention. Pure, injected, idempotent.

WHY A SEPARATE MODULE
---------------------
`contact_payment_links` answers "is this contact tied to money" (a READ used by the delete
guard). This module performs the WRITE that marks a contact locked+tagged when a payment is
captured. They are deliberately split: the read guard must never write, and the write path
must be callable from the settle/webhook path WITHOUT importing the whole contacts handler.

Like `contact_payment_links`, this takes the DynamoDB table INJECTED and imports no boto3, so
`test_the_module_imports_no_boto3` can keep it dependency-free and the money-path caller owns
the client.

TWO INVARIANTS, both because this runs AFTER the money has been taken
---------------------------------------------------------------------
1. **Fail-OPEN.** `lock_as_customer` never raises. A capture has already succeeded and the order
   row is the source of truth; the lock flag is a derived convenience, and the paid-contact
   hard-delete guard (`contact_payment_links`) already protects the record even if this write
   never lands. Raising here would turn a cosmetic lock failure into a PAID-BUT-ERRORED capture.
2. **Idempotent / replay-safe.** Re-processing a capture (a redelivered webhook) must not error
   on an already-locked contact nor duplicate the `customer` tag. A conditional-free update that
   sets the lock fields and folds the tag into a set achieves both.
"""

from __future__ import annotations

import time
from typing import Any, Optional

#: Row attributes this module owns. Not in the contacts handler's ALLOWED_UPDATE_FIELDS — only
#: the dedicated lock/unlock endpoints and this payment hook write them.
LOCKED_ATTRIBUTE = "locked"
LOCKED_REASON_ATTRIBUTE = "lockedReason"
LOCKED_AT_ATTRIBUTE = "lockedAt"

#: The tag applied to a contact that has paid. Lower-case to match the handler's tag casing.
CUSTOMER_TAG = "customer"

#: The reason stamped by the automatic payment lock (distinct from a manual "legal-hold").
REASON_PAID = "paid"


def lock_as_customer(contacts_table: Any, contact_id: str,
                     *, now: Optional[int] = None, logger: Any = None) -> bool:
    """Mark `contact_id` locked+"customer"-tagged because a payment was captured.

    Returns True on a successful write, False on any failure (fail-OPEN: never raises).
    Idempotent: safe to call again for a redelivered capture — the lock fields are set
    unconditionally and the `customer` tag is folded into the existing list without duplication.

    `contacts_table` is an injected boto3 Table (or a fake in tests). `now` defaults to the
    current epoch seconds. `logger`, if given, records the outcome; it is never required.
    """
    if not contact_id:
        return False
    ts = int(now if now is not None else time.time())
    try:
        contacts_table.update_item(
            Key={"id": contact_id},
            UpdateExpression=(
                "SET #locked = :true, #reason = :paid, #at = :ts, "
                "#tags = list_append(if_not_exists(#tags, :empty), :maybe_tag)"
            ),
            # list_append would duplicate the tag on a replay, so we gate the append on the tag
            # being absent. A conditional that is already-satisfied raises
            # ConditionalCheckFailedException, which we treat as "already a customer" = success.
            ConditionExpression="attribute_not_exists(#tags) OR NOT contains(#tags, :tag)",
            ExpressionAttributeNames={
                "#locked": LOCKED_ATTRIBUTE,
                "#reason": LOCKED_REASON_ATTRIBUTE,
                "#at": LOCKED_AT_ATTRIBUTE,
                "#tags": "tags",
            },
            ExpressionAttributeValues={
                ":true": True,
                ":paid": REASON_PAID,
                ":ts": ts,
                ":empty": [],
                ":maybe_tag": [CUSTOMER_TAG],
                ":tag": CUSTOMER_TAG,
            },
        )
        if logger is not None:
            logger.info({"event": "contact_locked_as_customer", "locked": True, "tagged": True})
        return True
    except Exception as exc:  # noqa: BLE001 - fail-OPEN is the contract
        # The common already-a-customer case lands here via ConditionalCheckFailedException: the
        # tag was already present, so this is a replay and the contact is already locked+tagged.
        # Set the lock fields unconditionally (without the tag append) so a lock that somehow
        # lagged still catches up, and still never raise.
        try:
            contacts_table.update_item(
                Key={"id": contact_id},
                UpdateExpression="SET #locked = :true, #reason = :paid, #at = :ts",
                ExpressionAttributeNames={
                    "#locked": LOCKED_ATTRIBUTE,
                    "#reason": LOCKED_REASON_ATTRIBUTE,
                    "#at": LOCKED_AT_ATTRIBUTE,
                },
                ExpressionAttributeValues={":true": True, ":paid": REASON_PAID, ":ts": ts},
            )
            if logger is not None:
                logger.info({"event": "contact_lock_idempotent_replay", "locked": True})
            return True
        except Exception as exc2:  # noqa: BLE001 - still fail-OPEN
            if logger is not None:
                logger.info({"event": "contact_lock_failed_open",
                             "error": type(exc2).__name__, "firstError": type(exc).__name__})
            return False


def is_locked(row: Any) -> bool:
    """True when a contact row carries a truthy lock flag. Total; never raises."""
    if not isinstance(row, dict):
        return False
    return bool(row.get(LOCKED_ATTRIBUTE))


__all__ = [
    "LOCKED_ATTRIBUTE",
    "LOCKED_REASON_ATTRIBUTE",
    "LOCKED_AT_ATTRIBUTE",
    "CUSTOMER_TAG",
    "REASON_PAID",
    "lock_as_customer",
    "is_locked",
]
