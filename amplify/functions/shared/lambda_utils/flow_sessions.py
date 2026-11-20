"""Server-bound WhatsApp Flow sessions: proof that a Flow token is one WECARE.DIGITAL issued.

PURPOSE. A Flow data-exchange request carries one identity input, the `flow_token` we put in
the Flow message, and Flow handlers read the customer's phone out of it. The `/flow-data`
endpoint is public by necessity. Decrypting a request proves only that it was encrypted to
our PUBLIC key, and a Flow on data API 3.0 receives no Meta `flow_token_signature`. On its
own, the phone inside a token is a claim, not an identity: a hand-built or edited token
(a different phone spliced into a real one) would read or overwrite someone else's profile.

AUTHORITY. A session row turns the claim into an identity. The token is minted here with
128 random bits, and a row keyed by the token's SHA-256 digest is written to FlowDraftTable
(the same `{phone}#{code}` store the review door already uses to hand context from the
inbound Lambda to the data-exchange Lambda) BEFORE the Flow message is sent. A data-exchange
handler accepts the token only when that row exists, names the same capability and phone,
and has not expired. Anything else is refused with HTTP 427, which WhatsApp defines as
"Flow token is no longer valid": the handset shows our message and disables the CTA.

The row stores the digest, never the token, and no customer field. Reads and writes fail
closed: a session-store error is `FlowSessionUnavailable`, never an accepted session.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from lambda_utils import contact_store, shared_tables

#: FlowDraftTable code segment for a session row: `{digits}#WD_FLOW_SESSION#{digest}`.
SESSION_CODE = 'WD_FLOW_SESSION'
#: How long a sent Flow message stays openable: one sitting or the next day. After that the
#: customer asks again and receives a fresh token.
SESSION_TTL_SECONDS = 24 * 3600
#: Rows outlive their expiry briefly so an operator can still see why a late tap failed.
#: DynamoDB TTL deletion is best effort; `expiresAt` is what actually bounds a session.
_ROW_RETENTION_SECONDS = 7 * 86400

LAUNCH_KEYWORD = 'keyword'
LAUNCH_STAFF = 'staff_send'
LAUNCH_PAYMENT = 'payment'
LAUNCH_WEB = 'website'
LAUNCH_CHANNELS = frozenset({LAUNCH_KEYWORD, LAUNCH_STAFF, LAUNCH_PAYMENT, LAUNCH_WEB})


class FlowSessionRejected(Exception):
    """The token is not a live server-issued session. Answer the handset with HTTP 427.

    `reason` is a stable token that is safe to log. `customer_message` is what WhatsApp shows
    the customer (the 427 `error_msg`), so it must be plain, branded copy.
    """

    def __init__(self, reason: str, customer_message: str):
        super().__init__(reason)
        self.reason = reason
        self.customer_message = customer_message


class FlowSessionUnavailable(Exception):
    """The session store could not be read or written. Never treated as a valid session."""


@dataclass(frozen=True)
class FlowSession:
    capability: str
    phone: str
    waba: str
    launch_channel: str
    initiated_by: str
    created_at: int
    expires_at: int
    consumed_at: int
    service_request_key: str = ""
    payment_attempt_id: str = ""
    order_id: str = ""
    order_number: str = ""
    service_code: str = ""


def table_name() -> str:
    """FlowDraftTable for this execution environment."""
    return shared_tables.flow_drafts_table_name()


def token_digest(token: str) -> str:
    """Hex SHA-256 of a whole token. Stored and compared instead of the token itself."""
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def phone_from_token(token: str) -> str:
    """The digits after `-ph-`, or '' when the token carries no plausible phone."""
    text = str(token or '')
    if '-ph-' not in text:
        return ''
    return contact_store.digits(text.split('-ph-', 1)[1])


def waba_from_token(token: str) -> str:
    """The `-waba-{n}-` slot of a token, or ''."""
    text = str(token or '')
    if '-waba-' not in text:
        return ''
    return text.split('-waba-', 1)[1].split('-', 1)[0]


def session_key(phone: Any, token: str) -> str:
    """FlowDraftTable `draftKey` for one session."""
    return f'{contact_store.digits(phone)}#{SESSION_CODE}#{token_digest(token)}'


def mint_token(prefix: str, phone: Any, waba: str = '1') -> str:
    """A fresh unguessable token in the router's `{prefix}-{hex}-waba-{n}-ph-{digits}` shape."""
    digits = contact_store.digits(phone)
    if not digits:
        raise ValueError('a phone-backed customer is required for a Flow session')
    if waba not in ('1', '2'):
        raise ValueError('unknown WABA slot')
    if not prefix or '-' in prefix:
        raise ValueError('token prefix must be one routing segment')
    return f'{prefix}-{uuid.uuid4().hex}-waba-{waba}-ph-{digits}'


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, ArithmeticError):
        return 0


def record_session(table: Any, *, capability: str, token: str, launch_channel: str,
                   initiated_by: str, service_request_key: str = "",
                   payment_attempt_id: str = "", order_id: str = "",
                   order_number: str = "", service_code: str = "",
                   now: Optional[int] = None) -> FlowSession:
    """Persist the proof of issue BEFORE the Flow message is sent. Raises on any failure.

    The write is conditional, so a token can never be re-issued over an existing row. A uuid4
    collision is not expected; the condition makes the guarantee structural instead.
    """
    if launch_channel not in LAUNCH_CHANNELS:
        raise ValueError(f'unknown launch channel {launch_channel!r}')
    phone = phone_from_token(token)
    waba = waba_from_token(token)
    actor = str(initiated_by or '').strip()[:200]
    if not capability or not phone or waba not in ('1', '2') or not actor:
        raise ValueError('a session needs a capability, a WABA slot, a phone and an initiator')
    issued = int(time.time() if now is None else now)
    service_key = str(service_request_key or "").strip()[:200]
    attempt_id = str(payment_attempt_id or "").strip()[:200]
    paid_order_id = str(order_id or "").strip()[:200]
    paid_order_number = str(order_number or "").strip().upper()[:200]
    paid_service_code = str(service_code or "").strip().upper()[:80]

    # Legacy paid Flows bind to a ServiceRequests row. The new single-order contract deliberately
    # creates no WD-REQ row, so it binds the session to the verified PaymentAttempt + existing
    # Order instead. Exactly one of those two authorities must be present for a payment launch.
    has_single_order_payment = bool(
        attempt_id and paid_order_id and paid_order_number and paid_service_code)
    if launch_channel == LAUNCH_PAYMENT and not (service_key or has_single_order_payment):
        raise ValueError(
            'a payment Flow session needs a paid service request or single-order payment context')
    session = FlowSession(
        capability=capability, phone=phone, waba=waba,
        launch_channel=launch_channel, initiated_by=actor,
        created_at=issued, expires_at=issued + SESSION_TTL_SECONDS,
        consumed_at=0, service_request_key=service_key,
        payment_attempt_id=attempt_id, order_id=paid_order_id,
        order_number=paid_order_number, service_code=paid_service_code)
    try:
        table.put_item(Item={
            'draftKey': session_key(phone, token),
            'phone': phone,
            'flowCode': SESSION_CODE,
            'capability': capability,
            'waba': waba,
            'launchChannel': launch_channel,
            'initiatedBy': actor,
            'createdAt': issued,
            'expiresAt': session.expires_at,
            **({'serviceRequestKey': service_key} if service_key else {}),
            **({'paymentAttemptId': attempt_id} if attempt_id else {}),
            **({'orderId': paid_order_id} if paid_order_id else {}),
            **({'orderNumber': paid_order_number} if paid_order_number else {}),
            **({'serviceCode': paid_service_code} if paid_service_code else {}),
            'ttl': session.expires_at + _ROW_RETENTION_SECONDS,
        }, ConditionExpression='attribute_not_exists(draftKey)')
    except Exception as exc:  # noqa: BLE001 - every failure means "not issued"
        raise FlowSessionUnavailable(type(exc).__name__) from exc
    return session


def verify_session(table: Any, *, capability: str, token: str, rejected_message: str,
                   now: Optional[int] = None) -> FlowSession:
    """The live session behind `token`, or raise. Never returns an unverified session."""
    phone = phone_from_token(token)
    if not phone:
        raise FlowSessionRejected('token_unparseable', rejected_message)
    try:
        item = table.get_item(Key={'draftKey': session_key(phone, token)},
                              ConsistentRead=True).get('Item')
    except Exception as exc:  # noqa: BLE001 - an unreadable store is not a valid session
        raise FlowSessionUnavailable(type(exc).__name__) from exc
    if not item:
        raise FlowSessionRejected('session_missing', rejected_message)
    if str(item.get('capability') or '') != capability:
        raise FlowSessionRejected('session_capability_mismatch', rejected_message)
    if contact_store.digits(item.get('phone')) != phone:
        raise FlowSessionRejected('session_phone_mismatch', rejected_message)
    checked = int(time.time() if now is None else now)
    expires_at = _int(item.get('expiresAt'))
    if expires_at <= checked:
        raise FlowSessionRejected('session_expired', rejected_message)
    return FlowSession(
        capability=capability, phone=phone,
        waba=str(item.get('waba') or waba_from_token(token)),
        launch_channel=str(item.get('launchChannel') or ''),
        initiated_by=str(item.get('initiatedBy') or ''),
        created_at=_int(item.get('createdAt')), expires_at=expires_at,
        consumed_at=_int(item.get('consumedAt')),
        service_request_key=str(item.get('serviceRequestKey') or ''),
        payment_attempt_id=str(item.get('paymentAttemptId') or ''),
        order_id=str(item.get('orderId') or ''),
        order_number=str(item.get('orderNumber') or ''),
        service_code=str(item.get('serviceCode') or ''))


def mark_consumed(table: Any, *, token: str, now: Optional[int] = None) -> bool:
    """Record that this session completed its one save. Best effort; never raises.

    A consumed session can no longer open its Flow (INIT answers 427), and REVIEW accepts it
    only as an identical retry of the save it already made.
    """
    phone = phone_from_token(token)
    if not phone:
        return False
    try:
        table.update_item(
            Key={'draftKey': session_key(phone, token)},
            UpdateExpression='SET #consumed = if_not_exists(#consumed, :now)',
            ConditionExpression='attribute_exists(draftKey)',
            ExpressionAttributeNames={'#consumed': 'consumedAt'},
            ExpressionAttributeValues={':now': int(time.time() if now is None else now)},
        )
        return True
    except Exception:  # noqa: BLE001 - the retry rule still guards a missed mark
        return False
