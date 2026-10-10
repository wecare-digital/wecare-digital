"""Server-side confirmation for an irreversible bulk delete. Single-use, selection-bound.

Why this exists in the shared layer
-----------------------------------
Three routes can empty a table in one call — `operations/system-cleanup`,
`core/messages-delete`'s `clear-all`, and `payments/invoice-engine`'s `clear-all` — and
all three were gated by nothing more than a dialog in the admin UI. A dialog is a
client-side courtesy: `curl` skips it. Each route needed the same handshake, so the
handshake lives here once rather than as three copies that drift.

The design, and why each part is load-bearing
---------------------------------------------
**A row in `SystemConfigTable`, not an HMAC over an env secret.** A per-container secret
does not survive a cold start, and minting one would need an env change that the Phase-0
safety fix is not allowed to make. `SystemConfigTable` already exists, is already in
`system-cleanup`'s `PROTECTED_TABLES`, and is already read and written by a dozen
handlers.

**Bound to the exact selection.** `GET` records what it counted; `POST` must name the
same set. So a caller cannot read a preview of four cache tables and then post
`ContactsTable` under the token that preview issued. Comparison is order-insensitive but
otherwise exact — one extra id is a different request.

**Single-use, consumed before the first delete.** This is what makes a retry safe: a
replayed `POST` finds no row and is refused, so a timeout followed by a retry cannot
delete twice. Two concurrent posts cannot both proceed either, because the delete is
conditional on the row still existing.

**Short TTL.** A token left open in a browser tab is not a standing authorisation.

What this is NOT
----------------
Not authentication and not authorisation. It proves the caller saw a server-computed
preview of this exact selection moments ago; it says nothing about who they are. The
Admin role, the staff-pool pin and the MFA check are separate and all still required.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, Iterable, List, Optional

import boto3

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

SYSTEM_CONFIG_TABLE = os.environ.get(
    'SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
#: Long enough to read the counts and decide, short enough not to be a standing grant.
DEFAULT_TTL_SECONDS = 15 * 60

_dynamodb = None


def _table():
    """Lazily built, so importing this module needs no AWS configuration."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource(
            'dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return _dynamodb.Table(SYSTEM_CONFIG_TABLE)


def _row_id(scope: str, token: str) -> str:
    return f'{scope}_confirm_{token}'


def mint(scope: str, selection: Iterable[str], counts: Dict[str, int], actor: str,
         ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[str]:
    """Record a token for this exact selection. Returns the token, or None if unstorable.

    None rather than raising, because the preview that calls this is still worth showing:
    the operator sees live counts and `POST` then refuses for want of a token. The failure
    direction is "cannot delete", never "delete unconfirmed".
    """
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    try:
        _table().put_item(Item={
            'id': _row_id(scope, token),
            'scope': scope,
            'selection': sorted(str(s) for s in selection),
            'counts': {str(k): int(v) for k, v in (counts or {}).items()},
            'actor': actor,
            'createdAt': now,
            'expiresAt': now + ttl_seconds,
        })
        return token
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({
            'event': 'confirm_token_write_failed', 'scope': scope, 'error': str(e)[:160],
        }))
        return None


def consume(scope: str, token: str, selection: List[str]) -> Dict[str, Any]:
    """Verify and DELETE the token row.

    Returns `{'ok': True, 'counts': {...}, 'actor': str}` on success, or
    `{'error': str, 'status': int}` on refusal. The row is consumed BEFORE the caller
    deletes anything, so a replay or a concurrent request is refused rather than
    duplicated.
    """
    if not token:
        return {'error': 'confirmationToken required — preview first', 'status': 400}

    key = {'id': _row_id(scope, token)}
    wanted = sorted(str(s) for s in selection)
    table = _table()

    try:
        row = table.get_item(Key=key).get('Item')
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'confirm_token_read_failed', 'scope': scope, 'error': str(e)[:160],
        }))
        return {'error': 'Confirmation store unavailable', 'status': 503}

    if not row:
        # "Never existed" and "already used" deliberately give the same message, so a
        # caller probing tokens learns nothing from the difference.
        return {'error': 'Confirmation token is invalid or already used', 'status': 409}

    if int(row.get('expiresAt') or 0) < int(time.time()):
        return {'error': 'Confirmation token has expired — preview again', 'status': 409}

    if sorted(str(s) for s in (row.get('selection') or [])) != wanted:
        logger.warning(json.dumps({'event': 'confirm_selection_mismatch', 'scope': scope}))
        return {'error': 'Selection does not match the confirmed preview', 'status': 409}

    try:
        table.delete_item(Key=key, ConditionExpression='attribute_exists(id)')
    except Exception as e:  # noqa: BLE001
        # Includes ConditionalCheckFailedException: somebody else consumed it first.
        logger.warning(json.dumps({
            'event': 'confirm_token_consume_failed', 'scope': scope, 'error': str(e)[:160],
        }))
        return {'error': 'Confirmation token is invalid or already used', 'status': 409}

    return {
        'ok': True,
        'counts': {str(k): int(v) for k, v in (row.get('counts') or {}).items()},
        'actor': str(row.get('actor') or ''),
    }
