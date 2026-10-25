"""
Sinch RCS DLR (Delivery Report) Webhook Handler

Endpoint: POST /webhook/sinch-rcs
Receives delivery status callbacks from Sinch India Conversation API.

DLR Events:
- MESSAGE_DELIVERY: Message delivery status (QUEUED, DELIVERED, FAILED, READ)
- EVENT_DELIVERY: Event delivery status
- MESSAGE_INBOUND: Inbound message from user
- EVENT_INBOUND: Inbound event from user
- CONVERSATION_START / CONVERSATION_STOP
- CONTACT_CREATE / CONTACT_DELETE / CONTACT_MERGE / CONTACT_UPDATE
- OPT_IN / OPT_OUT
- CAPABILITY
- UNSUPPORTED
"""

import os
import json
import time
import boto3
import boto3.dynamodb.conditions
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_headers, extract_origin
from lambda_utils.privacy import mask_contact_id  # contactId is `wa` + the customer's digits
from lambda_utils.message_store import put_message  # canonical MessagesTable writer
from lambda_utils.automation import evaluate_rules  # cross-channel auto-reply rules
from lambda_utils import sinch_signature  # raw-body HMAC on the public callback
from lambda_utils import rcs_status  # monotonic status ordering + failure classification
from lambda_utils import contact_key  # `id` is the physical key; `contactId` is its alias

logger = get_logger(__name__)

# Webhook signing secret, cached for the life of the execution environment.
# Loaded lazily on first request, never at import: a module-scope read is frozen
# into every warm sandbox, so a rotation would not take effect until each one
# recycles.
_webhook_secret_cache: Dict[str, Any] = {'loaded': False, 'value': ''}


def _load_webhook_secret() -> str:
    """Read the Sinch webhook signing secret from Secrets Manager.

    Returns '' when no secret is configured, which the caller must treat as
    "cannot verify" rather than "no verification needed".
    """
    if _webhook_secret_cache['loaded']:
        return _webhook_secret_cache['value']

    value = ''
    try:
        client = boto3.client(
            'secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1')
        )
        resp = client.get_secret_value(SecretId=SINCH_RCS_SECRET_ID)
        data = json.loads(resp.get('SecretString') or '{}')
        value = data.get('webhook_secret') or ''
    except Exception as e:  # noqa: BLE001 - never leak the secret or crash on absence
        logger.error(json.dumps({
            'event': 'rcs_dlr_secret_load_failed',
            'error': type(e).__name__,
        }))
        # Do not cache a failed load: a transient Secrets Manager error must not
        # pin this sandbox into permanent 503s.
        return ''

    _webhook_secret_cache['value'] = value
    _webhook_secret_cache['loaded'] = True
    return value

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
# RCS_TABLE removed 2026-09-21. It defaulted to
# stack-wecare-digital-RcsMessagesTable, which does not exist in the account, and
# the constant was never read: the Phase 4 migration stopped every write to the
# legacy RCS store and made the canonical MessagesTable the sole store. Kept out of
# the code rather than pointed at a real table, so nobody reintroduces a
# second store by wiring the constant back up.
SINCH_RCS_SECRET_ID = os.environ.get('SINCH_RCS_SECRET_ID', 'wecare/sinch/rcs')

# Event types still processed when the callback could not be authenticated,
# because no webhook secret is configured at Sinch yet. Deliberately the one type
# that real traffic consists of, and deliberately NOT the ones that write into the
# canonical message store or trigger an outbound send. See the rationale at the
# point of use in handler().
_UNVERIFIED_ALLOWED_EVENTS = frozenset({'MESSAGE_DELIVERY'})
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')

# Sinch RCS status mapping
RCS_STATUS_MAP = {
    'QUEUED': 'sent',
    'DELIVERED': 'delivered',
    'FAILED': 'failed',
    'READ': 'read',
    'DELETED': 'deleted',
}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Sinch RCS DLR webhook callbacks."""
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    if http_method == 'GET':
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'status': 'ok', 'service': 'sinch-rcs-webhook'}),
        }

    # ── Authenticate the caller BEFORE any parsing or side effect ──
    # This route is public at the gateway (AuthorizationType=NONE) because a
    # provider callback cannot present a Cognito token. Trust therefore has to
    # come from the Sinch HMAC signature, verified over the raw body.
    via_http = sinch_signature.is_http_request(event)
    verified = not via_http  # an internal invoke is already past the boundary

    if via_http:
        secret = _load_webhook_secret()
        if secret:
            ok, reason = sinch_signature.verify(event, secret)
            if not ok:
                logger.warning(json.dumps({
                    'event': 'rcs_dlr_signature_rejected',
                    'reason': reason,
                    'requestId': request_id,
                }))
                # 401: a permanent rejection, which Sinch does not retry. Correct
                # for a forged request.
                return {
                    'statusCode': 401,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'success': False, 'error': 'invalid_signature'}),
                }
            verified = True
        else:
            # No secret is configured on the Sinch webhook yet, so nothing that
            # arrives here can be authenticated. See _UNVERIFIED_ALLOWED_EVENTS
            # for what is still processed in that state and why.
            logger.error(json.dumps({
                'event': 'rcs_dlr_unverified_callback',
                'detail': 'no webhook_secret in wecare/sinch/rcs',
                'requestId': request_id,
            }))

    try:
        body = event.get('body', '{}')
        if isinstance(body, str):
            data = json.loads(body)
        else:
            data = body or {}
    except Exception as e:
        logger.error(f'Failed to parse RCS DLR body: {e}')
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': False, 'error': 'parse_error'}),
        }

    event_type = _get_event_type(data)
    logger.info(json.dumps({
        'event': 'rcs_dlr_received',
        'type': event_type,
        'verified': verified,
        'requestId': request_id,
    }))

    # ── Interim posture while no webhook secret exists ──
    # Measured over the 7 days to 2026-09-21: 313 of 313 callbacks on this route
    # were MESSAGE_DELIVERY. Zero MESSAGE_INBOUND, zero OPT_IN/OPT_OUT. So the
    # dangerous paths - _process_inbound writing forged messages into the
    # canonical MessagesTable, and evaluate_rules invoking wecare-rcs-send with a
    # phone number from the request body - have never carried legitimate traffic,
    # while delivery receipts demonstrably have.
    #
    # Refusing everything unverified would therefore trade a live exploit for a
    # live outage of the only feature actually in use. Refusing only the unused
    # high-risk event types closes the exploit and costs nothing real.
    #
    # 503 rather than 401: Sinch retries 5xx with exponential backoff, so if those
    # event types ever do start arriving they queue rather than vanish, and the
    # error is visible in the logs. No flag to forget either - the moment a
    # webhook_secret is configured, `verified` is true and this branch is dead.
    if not verified and event_type not in _UNVERIFIED_ALLOWED_EVENTS:
        logger.error(json.dumps({
            'event': 'rcs_dlr_unverified_event_refused',
            'type': event_type,
            'detail': 'configure webhook_secret in wecare/sinch/rcs to enable',
            'requestId': request_id,
        }))
        return {
            'statusCode': 503,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': False, 'error': 'verification_unavailable'}),
        }

    if event_type == 'MESSAGE_DELIVERY':
        _process_delivery(data, request_id)
    elif event_type == 'MESSAGE_INBOUND':
        _process_inbound(data, request_id)
    elif event_type in ('OPT_IN', 'OPT_OUT'):
        _process_opt(data, event_type, request_id)

    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'event': event_type}),
    }


def _get_event_type(data: Dict) -> str:
    if 'message_delivery_report' in data:
        return 'MESSAGE_DELIVERY'
    elif 'contact_message' in data:
        # Sinch sends inbound messages with 'contact_message' at top level
        return 'MESSAGE_INBOUND'
    elif 'message' in data and data.get('direction') == 'TO_APP':
        return 'MESSAGE_INBOUND'
    elif 'message' in data and 'contact_message' in data.get('message', {}):
        # Alternate format: message.contact_message
        return 'MESSAGE_INBOUND'
    elif 'event_delivery_report' in data:
        return 'EVENT_DELIVERY'
    elif 'event' in data and data.get('direction') == 'TO_APP':
        return 'EVENT_INBOUND'
    elif 'conversation_start_notification' in data:
        return 'CONVERSATION_START'
    elif 'conversation_stop_notification' in data:
        return 'CONVERSATION_STOP'
    elif 'opt_in_notification' in data:
        return 'OPT_IN'
    elif 'opt_out_notification' in data:
        return 'OPT_OUT'
    elif 'capability_notification' in data:
        return 'CAPABILITY'
    elif 'contact_create_notification' in data:
        return 'CONTACT_CREATE'
    elif 'contact_delete_notification' in data:
        return 'CONTACT_DELETE'
    return data.get('event_type', 'UNKNOWN')


def _process_delivery(data: Dict, request_id: str):
    """Process delivery report and UPDATE message status in DynamoDB."""
    report = data.get('message_delivery_report', {})
    message_id = report.get('message_id', '')
    sinch_status = report.get('status', '')
    channel = report.get('channel_identity', {}).get('channel', 'RCS')
    identity = report.get('channel_identity', {}).get('identity', '')
    reason = report.get('reason', {})
    metadata = data.get('message_metadata', '')

    # Canonical status and its rank come from lambda_utils.rcs_status, which is now the
    # single definition. RCS_STATUS_MAP below is retained only as a fallback for a
    # status that module does not recognise, so an unknown value still gets logged
    # rather than dropped.
    status = rcs_status.canonical(sinch_status) or (
        RCS_STATUS_MAP.get(sinch_status, sinch_status.lower() if sinch_status else 'unknown'))
    now = int(time.time())
    reason_text = reason.get('description', '') if isinstance(reason, dict) else str(reason or '')

    # Classify the failure so a permanently unreachable recipient is visible. Measured
    # over 30 days to 2026-09-22: 559 of 559 failures were the same terminal class -
    # "Number is RCS disabled or Bot is not launched with the number's provider" - and
    # one recipient was sent 90 messages, failing all 90, because nothing learned from it.
    unreachable = False
    failure_category = ''
    if status == 'failed':
        disposition, failure_category = rcs_status.classify_failure(reason_text)
        unreachable = rcs_status.is_rcs_unreachable(reason_text)

    logger.info(json.dumps({
        'event': 'rcs_delivery_update',
        'messageId': message_id,
        'status': status,
        'sinchStatus': sinch_status,
        'channel': channel,
        'identity': identity[-4:] if identity else '',
        'reason': reason_text,
        'failureCategory': failure_category or None,
        'rcsUnreachable': unreachable or None,
        'requestId': request_id,
    }))

    # A dedicated line for the terminal class, so the volume is alarmable without
    # parsing prose out of the generic update line.
    if unreachable:
        logger.warning(json.dumps({
            'event': 'rcs_recipient_unreachable',
            'messageId': message_id,
            'identity': identity[-4:] if identity else '',
            'category': failure_category,
            'detail': 'recipient has RCS disabled, or the agent is not launched with '
                      'their operator; retrying cannot succeed until that changes',
            'requestId': request_id,
        }))

    if not message_id:
        return

    # Monotonic guard. Previously an unconditional SET, so a QUEUED_ON_CHANNEL arriving
    # after DELIVERED rewrote a delivered message back to `sent`, and a re-delivered
    # FAILED rewrote `delivered`. With 728 QUEUED_ON_CHANNEL against 166 DELIVERED in
    # the measured window that is not a theoretical race - it means the delivered count
    # is a floor rather than a measurement.
    incoming_rank = rcs_status.rank(status)
    try:
        dynamodb.Table(MESSAGES_TABLE).update_item(
            Key={'id': message_id},
            UpdateExpression=(
                'SET #s = :status, dlrTime = :dlr, updatedAt = :now, '
                f'{rcs_status.RANK_ATTRIBUTE} = :rank'
            ),
            ConditionExpression=rcs_status.condition_expression(),
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': status,
                ':dlr': data.get('event_time', ''),
                ':now': now,
                ':rank': incoming_rank,
            },
        )
    except Exception as e:
        # A ConditionalCheckFailedException here is the guard working, not a fault: it
        # means a later status already won. Logged distinctly so the two cases are not
        # conflated in triage.
        if 'ConditionalCheckFailed' in str(e):
            logger.info(json.dumps({
                'event': 'rcs_delivery_out_of_order_skipped',
                'messageId': message_id,
                'incomingStatus': status,
                'incomingRank': incoming_rank,
                'requestId': request_id,
            }))
        else:
            logger.debug(f'MessagesTable RCS DLR update skipped for {message_id}: {e}')


def _process_inbound(data: Dict, request_id: str):
    """Process inbound RCS message and store in DB.
    
    Sinch sends inbound in this format:
    {
        "app_id": "...",
        "accepted_time": "...",
        "event_time": "...",
        "project_id": "...",
        "contact_message": {
            "text_message": {"text": "user reply"},
            "channel_identity": {"channel": "RCS", "identity": "919903300044", "app_id": "..."},
            "contact_id": "",
            "conversation_id": ""
        },
        "message_metadata": ""
    }
    
    OR alternate format:
    {
        "message": {
            "id": "...",
            "direction": "TO_APP",
            "contact_message": {"text_message": {"text": "..."}},
            "channel_identity": {"channel": "RCS", "identity": "..."}
        }
    }
    """
    # Handle both Sinch inbound formats
    contact_msg = data.get('contact_message', {})
    message = data.get('message', {})
    
    if contact_msg:
        # Primary format: contact_message at top level
        channel_identity = contact_msg.get('channel_identity', {})
        identity = channel_identity.get('identity', '')
        contact_id = contact_msg.get('contact_id', '') or data.get('contact_id', '')
        conversation_id = contact_msg.get('conversation_id', '') or data.get('conversation_id', '')
        
        # Extract text content
        text_msg = contact_msg.get('text_message', {})
        content = text_msg.get('text', '')
        
        # Check for postback (button click)
        if not content and contact_msg.get('postback_data'):
            content = f"[postback:{contact_msg.get('postback_data')}]"
        
        # Check for media message
        if not content and contact_msg.get('media_message'):
            media = contact_msg.get('media_message', {})
            content = f"[media:{media.get('url', 'unknown')}]"
        
        # Check for location
        if not content and contact_msg.get('location_message'):
            loc = contact_msg.get('location_message', {})
            coords = loc.get('coordinates', {})
            content = f"[location:{coords.get('latitude', '?')},{coords.get('longitude', '?')}]"
        
        if not content:
            content = json.dumps(contact_msg)[:500]
        
        msg_id = data.get('message_id', f'rcs-in-{int(time.time())}')
        
    elif message and message.get('contact_message'):
        # Alternate format: message.contact_message
        inner = message.get('contact_message', {})
        channel_identity = message.get('channel_identity', data.get('channel_identity', {}))
        identity = channel_identity.get('identity', '')
        contact_id = data.get('contact_id', '')
        conversation_id = data.get('conversation_id', '')
        
        text_msg = inner.get('text_message', {})
        content = text_msg.get('text', '')
        if not content:
            content = json.dumps(inner)[:500]
        
        msg_id = message.get('id', data.get('message_id', f'rcs-in-{int(time.time())}'))
    else:
        # Fallback: try to extract whatever we can
        identity = data.get('channel_identity', {}).get('identity', '')
        contact_id = data.get('contact_id', '')
        conversation_id = data.get('conversation_id', '')
        content = json.dumps(data)[:500]
        msg_id = data.get('message_id', f'rcs-in-{int(time.time())}')

    accepted_time = data.get('accepted_time', '')
    now = int(time.time())

    # Look up contactId by phone number
    if not contact_id and identity:
        contact_id = _lookup_contact_by_phone(identity)

    logger.info(json.dumps({
        'event': 'rcs_inbound_stored',
        'messageId': msg_id,
        'identity': identity[-4:] if identity else '',
        'contactId': mask_contact_id(contact_id),
        'content': content[:50],
        'contentLen': len(content),
        'requestId': request_id,
    }))

    # Store inbound message — Phase 4: legacy RcsMessagesTable write STOPPED.
    # Canonical MessagesTable is the sole store (via put_message below).
    put_message(
        channel='rcs',
        direction='inbound',
        contact_id=contact_id or '',
        content=content[:2000],
        status='received',
        message_id=msg_id,
        message_type='text',
        sender_phone=identity.replace('+', '') if identity else None,
        timestamp=now,
    )
    logger.info(f'Inbound RCS stored (canonical): {msg_id} from {identity[-4:] if identity else "?"}')

    # Automation — auto-reply if a rule matches (guarded, async via rcs-send).
    try:
        if content and identity:
            _auto = evaluate_rules(content, 'rcs')
            if _auto:
                boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1')).invoke(
                    FunctionName='wecare-rcs-send:live',  # never $LATEST's unpublished code
                    InvocationType='Event',
                    Payload=json.dumps({
                        'requestContext': {'http': {'method': 'POST'}},
                        'body': json.dumps({'action': 'send', 'phoneNumber': identity.replace('+', ''), 'text': _auto}),
                    }),
                )
                logger.info(json.dumps({'event': 'automation_auto_reply', 'channel': 'rcs', 'messageId': msg_id}))
    except Exception as _ae:
        logger.warning(f'rcs automation auto-reply skipped: {_ae}')


def _process_opt(data: Dict, event_type: str, request_id: str):
    """Process opt-in/opt-out and log."""
    notification = data.get(f'{event_type.lower()}_notification', {})
    identity = notification.get('identity', '')
    logger.info(json.dumps({
        'event': f'rcs_{event_type.lower()}',
        'identity': identity[-4:] if identity else '',
        'requestId': request_id,
    }))


def _lookup_contact_by_phone(phone: str) -> str:
    """The contact's canonical id for this phone number, or `''` if there is none.

    See the matching function in `rcs-send`: resolution goes through `contact_key` so a
    row carrying only `id`, or one whose `contactId` alias has drifted, still yields the
    key that actually works against the table.
    """
    if not phone:
        return ''
    clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    variants = [clean]
    if clean.startswith('91') and len(clean) == 12:
        variants.append(clean[2:])
        variants.append(f'+{clean}')
    elif len(clean) == 10:
        variants.append(f'91{clean}')
        variants.append(f'+91{clean}')

    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        for variant in variants:
            resp = table.query(
                IndexName='phone-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('phone').eq(variant),
                Limit=1,
            )
            items = resp.get('Items', [])
            if items:
                item = items[0]
                try:
                    contact_key.assert_consistent(item)
                except contact_key.ContactKeyMismatch as exc:
                    logger.warning(json.dumps({
                        'event': 'contact_key_mismatch',
                        'source': 'rcs-dlr._lookup_contact_by_phone',
                        'reason': str(exc),
                    }))
                return contact_key.resolve(item)
    except Exception as e:
        logger.debug(f"Contact lookup by phone failed: {e}")
    return ''
