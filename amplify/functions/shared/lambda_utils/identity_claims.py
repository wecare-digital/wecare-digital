"""Database-enforced ownership for strong customer identities.

DynamoDB secondary indexes are eventually consistent and cannot enforce uniqueness. This registry
is the serialization point for phone/email ownership across every ContactsTable writer.

Rollout contract:
1. provision/backfill IdentityClaimsTable while ContactsTable is clean;
2. grant writers access;
3. deploy writers that call claim_identities BEFORE contact mutation.

Claims are idempotent for the same contact and fail closed for a different contact. A writer can
crash after claiming but before updating ContactsTable; that leaves a conservative stale claim
(false conflict, never duplicate identity). The provisioning repair mode can reconcile such rows.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional, Tuple

from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get(
    "IDENTITY_CLAIMS_TABLE", "stack-wecare-digital-IdentityClaimsTable"
)


class IdentityClaimConflict(RuntimeError):
    """A strong identity is already owned by a different canonical contact."""

    def __init__(self, claim_key: str):
        self.claim_key = claim_key
        super().__init__("strong customer identity is already claimed")


def _conditional(exc: Exception) -> bool:
    return (
        isinstance(exc, ClientError)
        and exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    )


def normalize_phone(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not 7 <= len(digits) <= 15:
        return ""
    return "+" + digits


def normalize_email(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or "@" not in text or len(text) > 320:
        return ""
    return text


def key(kind: str, value: Any) -> str:
    kind = str(kind or "").strip().upper()
    if kind == "PHONE":
        normalized = normalize_phone(value)
    elif kind == "EMAIL":
        normalized = normalize_email(value)
    else:
        raise ValueError("unsupported identity claim kind")
    return f"{kind}#{normalized}" if normalized else ""


def _claim(table: Any, claim_key: str, contact_id: str, now: int) -> bool:
    """Claim one key. Return True only if this call created the registry row."""
    if not claim_key or not contact_id:
        return False
    try:
        response = table.update_item(
            Key={"claimKey": claim_key},
            UpdateExpression=(
                "SET contactId=:cid, identityType=:kind, updatedAt=:now, "
                "claimedAt=if_not_exists(claimedAt,:now)"
            ),
            ConditionExpression="attribute_not_exists(claimKey) OR contactId=:cid",
            ExpressionAttributeValues={
                ":cid": contact_id,
                ":kind": claim_key.split("#", 1)[0],
                ":now": now,
            },
            ReturnValues="ALL_OLD",
        )
        return not bool(response.get("Attributes"))
    except Exception as exc:
        if _conditional(exc):
            raise IdentityClaimConflict(claim_key) from exc
        raise


def release(table: Any, claim_key: str, contact_id: str) -> bool:
    """Release only a claim still owned by contact_id."""
    if not claim_key or not contact_id:
        return False
    try:
        table.delete_item(
            Key={"claimKey": claim_key},
            ConditionExpression="contactId=:cid",
            ExpressionAttributeValues={":cid": contact_id},
        )
        return True
    except Exception as exc:
        if _conditional(exc):
            return False
        raise


def claim_identities(
    table: Any,
    *,
    contact_id: str,
    phone: Any = "",
    email: Any = "",
    now: Optional[int] = None,
) -> Tuple[str, ...]:
    """Claim phone/email for one contact; roll back only claims newly acquired in this call."""
    timestamp = int(now if now is not None else time.time())
    keys = tuple(k for k in (key("PHONE", phone), key("EMAIL", email)) if k)
    acquired = []
    try:
        for claim_key in keys:
            if _claim(table, claim_key, contact_id, timestamp):
                acquired.append(claim_key)
        return keys
    except Exception:
        for claim_key in reversed(acquired):
            try:
                release(table, claim_key, contact_id)
            except Exception:
                pass
        raise


def release_changed(
    table: Any,
    *,
    contact_id: str,
    old_phone: Any = "",
    new_phone: Any = "",
    old_email: Any = "",
    new_email: Any = "",
) -> None:
    """Release old strong identities after the ContactsTable mutation committed."""
    old_phone_key = key("PHONE", old_phone)
    new_phone_key = key("PHONE", new_phone)
    old_email_key = key("EMAIL", old_email)
    new_email_key = key("EMAIL", new_email)
    if old_phone_key and old_phone_key != new_phone_key:
        release(table, old_phone_key, contact_id)
    if old_email_key and old_email_key != new_email_key:
        release(table, old_email_key, contact_id)


def owner(table: Any, kind: str, value: Any) -> str:
    claim_key = key(kind, value)
    if not claim_key:
        return ""
    item = table.get_item(Key={"claimKey": claim_key}, ConsistentRead=True).get("Item") or {}
    return str(item.get("contactId") or "")
