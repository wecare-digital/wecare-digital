"""
Unified Message Store — canonical write/read contract for the shared MessagesTable.

This is the single source of truth for how every channel (WhatsApp / SMS / Email / RCS)
persists a message row. Instead of each Lambda hand-rolling its own put_item with a
slightly different shape, they all call `put_message(...)` here so rows are always
identical and the Unified Inbox (`messages-read`) can read them with no extra mapping.

Canonical table: stack-wecare-digital-MessagesTable  (the `Message` model in
amplify/data/resource.ts) — already has a `channel` enum, `direction`, TTL (`expiresAt`)
and a `contactId-index` GSI.

Design doc: docs/UNIFIED_MESSAGE_TABLE_DESIGN.md

USAGE (dual-write, Phase 1 — additive, non-breaking):
    from lambda_utils.message_store import put_message
    put_message(channel='sms', direction='outbound', contact_id=cid,
                content=text, status='sent', provider_message_id=pmid)

This module changes NO existing behavior on its own — it only takes effect where a handler
chooses to call it. Failures are swallowed + logged so a dual-write can never break a send.
"""

import os
import time
import uuid
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)

_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Canonical unified table. Uses a DEDICATED env name so it can't be hijacked by a
# per-Lambda MESSAGES_TABLE (several handlers repurpose MESSAGES_TABLE for their own
# legacy table — reading that here would send writes to the wrong place).
MESSAGES_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days — matches the Message model TTL

VALID_CHANNELS = ('whatsapp', 'sms', 'email', 'rcs', 'voice')
VALID_DIRECTIONS = ('inbound', 'outbound')
VALID_STATUSES = ('pending', 'sent', 'delivered', 'read', 'failed', 'received')


def _dec(value: Any) -> Decimal:
    """DynamoDB needs Decimal for numbers."""
    return Decimal(str(value))


def build_message_item(
    *,
    channel: str,
    direction: str,
    contact_id: str,
    content: str = '',
    status: str = 'sent',
    message_id: Optional[str] = None,
    timestamp: Optional[int] = None,
    **extras: Any,
) -> Dict[str, Any]:
    """Build a canonical MessagesTable item (does not write). Returns the dict.

    `extras` (any non-None) are passed through verbatim so channel-specific fields are
    preserved, e.g.: provider_message_id, media_url, s3_key, error_code, error_details,
    sender_phone, sender_name, receiving_phone, subject, message_type, whatsapp_message_id,
    transcription, detected_language, duration, call_type.
    """
    ch = (channel or '').lower()
    if ch not in VALID_CHANNELS:
        raise ValueError(f"invalid channel '{channel}' (expected one of {VALID_CHANNELS})")
    dir_ = (direction or '').lower()
    if dir_ not in VALID_DIRECTIONS:
        raise ValueError(f"invalid direction '{direction}' (expected one of {VALID_DIRECTIONS})")
    st = (status or 'sent').lower()

    mid = message_id or str(uuid.uuid4())
    now = int(timestamp if timestamp is not None else time.time())

    item: Dict[str, Any] = {
        'id': mid,
        'messageId': mid,
        'channel': ch,
        'direction': dir_,
        'content': content or '',
        'status': st,
        'timestamp': _dec(now),
        'createdAt': _dec(now),
        'expiresAt': _dec(now + MESSAGE_TTL_SECONDS),
    }
    # contactId is a GSI key (contactId-index) — DynamoDB rejects an empty-string key
    # value. Only include it when non-empty so unmatched messages still store (sparse).
    if contact_id:
        item['contactId'] = contact_id

    # Map snake_case extras → the camelCase attribute names the rest of the system uses.
    alias = {
        'provider_message_id': 'providerMessageId',
        'whatsapp_message_id': 'whatsappMessageId',
        'media_url': 'mediaUrl',
        'media_id': 'mediaId',
        's3_key': 's3Key',
        'error_code': 'errorCode',
        'error_details': 'errorDetails',
        'sender_phone': 'senderPhone',
        'sender_name': 'senderName',
        'receiving_phone': 'receivingPhone',
        'aws_phone_number_id': 'awsPhoneNumberId',
        'partner_waba_id': 'partnerWabaId',
        'message_type': 'messageType',
        # A shared contact card's sanitised name/phones/emails/org, as stored by the
        # inbound WhatsApp handler. The extras loop passes a list of dicts through
        # verbatim; this entry is what stops it landing under the snake_case key the
        # UI does not read.
        'contacts_payload': 'contactsPayload',
        'detected_language': 'detectedLanguage',
        'call_type': 'callType',
        'call_id': 'callId',
        'recording_url': 'recordingUrl',
        'ses_message_id': 'sesMessageId',
    }
    for key, value in extras.items():
        if value is None:
            continue
        attr = alias.get(key, key)
        # numbers (e.g. duration) → Decimal
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            item[attr] = _dec(value)
        else:
            item[attr] = value
    return item


def put_message(
    *,
    channel: str,
    direction: str,
    contact_id: str,
    content: str = '',
    status: str = 'sent',
    message_id: Optional[str] = None,
    timestamp: Optional[int] = None,
    table_name: Optional[str] = None,
    raise_on_error: bool = False,
    **extras: Any,
) -> Optional[str]:
    """Write a canonical message row to MessagesTable.

    Returns the messageId on success, or None on failure. By default failures are
    swallowed + logged (`raise_on_error=False`) so a dual-write can never break a send.
    Set raise_on_error=True when the write is the primary store (not a dual-write).
    """
    try:
        item = build_message_item(
            channel=channel, direction=direction, contact_id=contact_id,
            content=content, status=status, message_id=message_id,
            timestamp=timestamp, **extras,
        )
        table = _dynamodb.Table(table_name or MESSAGES_TABLE)
        table.put_item(Item=item)
        logger.info('{"event":"message_store_put","channel":"%s","direction":"%s","messageId":"%s"}'
                    % (item['channel'], item['direction'], item['messageId']))
        return item['messageId']
    except Exception as e:  # noqa: BLE001 — dual-write must not break the caller
        logger.warning('{"event":"message_store_put_failed","channel":"%s","error":"%s"}'
                       % (channel, str(e)))
        if raise_on_error:
            raise
        return None


def query_by_contact(contact_id: str, limit: int = 1000,
                      table_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read a conversation via the contactId-index GSI (efficient — no scan)."""
    if not contact_id:
        return []
    try:
        table = _dynamodb.Table(table_name or MESSAGES_TABLE)
        resp = table.query(
            IndexName='contactId-index',
            KeyConditionExpression='contactId = :c',
            ExpressionAttributeValues={':c': contact_id},
            Limit=limit,
        )
        return resp.get('Items', [])
    except Exception as e:  # noqa: BLE001
        logger.warning('{"event":"message_store_query_failed","error":"%s"}' % str(e))
        return []


def scan_channel(channel: Optional[str] = None, limit: int = 1000,
                 table_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Bounded scan of MessagesTable, optionally filtered to one channel.

    Phase-1 helper. For scale, add a `channel-index` GSI and query instead
    (see docs/UNIFIED_MESSAGE_TABLE_DESIGN.md §5).
    """
    try:
        table = _dynamodb.Table(table_name or MESSAGES_TABLE)
        kwargs: Dict[str, Any] = {'Limit': limit}
        if channel:
            kwargs['FilterExpression'] = '#ch = :ch'
            kwargs['ExpressionAttributeNames'] = {'#ch': 'channel'}
            kwargs['ExpressionAttributeValues'] = {':ch': channel.lower()}
        resp = table.scan(**kwargs)
        return resp.get('Items', [])
    except Exception as e:  # noqa: BLE001
        logger.warning('{"event":"message_store_scan_failed","error":"%s"}' % str(e))
        return []


def _call_label(direction: str, status: str, duration: Optional[int]) -> str:
    """Human one-line label for a call breadcrumb in the unified timeline."""
    st = (status or '').lower().replace('_', '-')
    icon = '\U0001F4DE'  # 📞
    if st in ('missed', 'no-answer', 'noanswer', 'unanswered'):
        return f'{icon} Missed call'
    if st == 'busy':
        return f'{icon} Busy'
    if st in ('failed', 'error', 'rejected'):
        return f'{icon} Failed call'
    label = 'Incoming call' if direction == 'inbound' else 'Outgoing call'
    if duration:
        try:
            m, s = divmod(int(duration), 60)
            return f'{icon} {label} \u00b7 {m}:{s:02d}'
        except Exception:
            pass
    return f'{icon} {label}'


def put_call_breadcrumb(
    *,
    call_id: str,
    direction: str = 'outbound',
    contact_id: str = '',
    status: str = '',
    duration: Optional[int] = None,
    call_type: Optional[str] = None,
    phone: Optional[str] = None,
    recording_url: Optional[str] = None,
    timestamp: Optional[int] = None,
    table_name: Optional[str] = None,
) -> Optional[str]:
    """Write a thin 'call' breadcrumb row to MessagesTable so calls appear inline in
    the unified per-contact timeline. The FULL call record stays in the voice table —
    this row just points at it via callId (channel='voice', messageType='call').

    Idempotent: uses call_id as the row id, so a status update overwrites the same
    breadcrumb instead of duplicating. Error-swallowed — never breaks call logging.
    """
    direction = (direction or 'outbound').lower()
    if direction not in VALID_DIRECTIONS:
        direction = 'outbound'
    content = _call_label(direction, status, duration)
    return put_message(
        channel='voice',
        direction=direction,
        contact_id=contact_id or '',
        content=content,
        status=(status or 'completed').lower(),
        message_id=call_id,
        message_type='call',
        timestamp=timestamp,
        table_name=table_name,
        call_id=call_id,
        duration=duration,
        call_type=call_type,
        recording_url=recording_url,
        sender_phone=phone if direction == 'inbound' else None,
        receiving_phone=phone if direction != 'inbound' else None,
    )
