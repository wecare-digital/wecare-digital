"""
Inbound WhatsApp Handler Lambda Function

Purpose: Process SNS notifications for WhatsApp messages
Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.12, 15.4, 15.7

Parses Meta webhook event format, stores messages, downloads media,
updates contact timestamps for 24-hour customer service window.
Tracks which WABA/phone number received the message.
"""

import os
import re
import json
import uuid
import time
import hmac
import hashlib
import boto3
import urllib.request
import urllib.error
import urllib.parse  # explicit: `_handoff_url` quotes a token into a link
from typing import Dict, Any, Optional
from decimal import Decimal

# Configure logging
from lambda_utils.logging import get_logger, log_event
from lambda_utils.response import extract_origin
from lambda_utils.privacy import mask_phone, mask_contact_id  # contactId is `wa` + the customer's digits
# Aliased because `payment_status` is a local variable throughout the payment handlers below,
# holding Meta's raw word. `pay_status` is the module that says what that word means.
from lambda_utils import payment_status as pay_status
from lambda_utils.validation import normalize_phone
from lambda_utils.message_store import put_message, query_by_contact  # unified MessagesTable: dual-write + contactId-index read
from lambda_utils import meta_signature  # raw-body X-Hub-Signature-256 on the public route
from lambda_utils import graph_errors  # log-safe fields of a Meta error, never the raw body
from lambda_utils import whatsapp_templates  # which templates automation depends on
from lambda_utils import wa_status  # monotonic status ordering (no backward transitions)
from lambda_utils import wa_internal_event  # typed ingress -> worker contract
from lambda_utils import contact_key, identity_claims
from lambda_utils import contact_store  # one contact row per person, whichever channel minted it
from lambda_utils import direct_send  # trusted Meta sender-phone-ID -> messaging-account mapping
from lambda_utils import shared_tables  # one name per shared store (contacts, orders, flows)
from lambda_utils.identity import subscriber_id
from lambda_utils.identity import consent as consent_evidence  # marketing consent ledger
from lambda_utils import customer_ideas, request_amendment_response, submit_request_response, track_shipping_response, pickup_request_response, referral_response
from lambda_utils.canonical_flows import published_flow_by_id  # one source of truth for WABA 1 flow ids
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.ecommerce import order_keys  # reference_id contract; never truncate a join key
from lambda_utils.system_events import record_system_event
from botocore.exceptions import ClientError
try:
    from lambda_utils import partner_billing  # per-tenant prepaid metering (optional)
except Exception:  # noqa: BLE001
    partner_billing = None

# Sub-modules (monolith decomposition)
from modules import message_dedup, webhook_routing
from modules.content import extract_content as _extract_content_v2
from modules.content import extract_contacts_payload as _extract_contacts_payload
from modules.content import KNOWN_TYPES as _KNOWN_TYPES

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables - use actual table names. The shared stores (contacts, flow
# responses, drafts) resolve through `lambda_utils.shared_tables`, so the inbox writes the same
# contact and flow-response rows the WhatsApp Flows, catalog orders and website checkout use.
CONTACTS_TABLE = shared_tables.contacts_table_name()
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
# Canonical unified message table (status mirror target).
UNIFIED_MESSAGES_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
MEDIA_FILES_TABLE = os.environ.get('MEDIA_FILES_TABLE', 'stack-wecare-digital-MediaFilesTable')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()
INBOUND_DLQ_URL = wa_internal_event.inbound_dlq_url()  # was '' when unset, so nothing was parked
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
# Customer uploads are private from their first S3 write. Existing public media
# remains readable through its persisted key; no migration or public fallback here.
MEDIA_PREFIX = media_paths.WHATSAPP_INCOMING_PREFIX

# Every Lambda invoke target below is the `live` alias: an unqualified name runs
# $LATEST, which an upload reaches before it is published and verified.

# WhatsApp Voice Lambda function name (TTS via Amazon Polly)
WHATSAPP_VOICE_FUNCTION = os.environ.get('WHATSAPP_VOICE_FUNCTION', 'wecare-whatsapp-voice:live')


# The commerce-keys table, read to link a post-payment Flow submission to its order through
# the PAYREF# chain. Defaulted through `order_keys` so it matches `ecommerce/checkout`.
COMMERCE_KEYS_TABLE = os.environ.get('COMMERCE_KEYS_TABLE',
                                     order_keys.commerce_keys_table_name())


# WhatsApp Phone Number IDs - Map Meta phone number IDs to phone number IDs
PHONE_NUMBER_ID_1 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE_NUMBER_ID_2 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')

# Map display phone numbers to phone number IDs for reference
PHONE_NUMBER_MAP = {
    '919330994400': PHONE_NUMBER_ID_1,  # +91 93309 94400 (WABA1, Direct API)
    '919903300044': PHONE_NUMBER_ID_2,  # +91 99033 00044 (WABA-T, Direct API)
}

# Meta phone number ID to phone number ID mapping
META_PHONE_ID_MAP = {
    '1016149501586345': PHONE_NUMBER_ID_1,  # +91 93309 94400 (Direct API)
    '1055232054343117': PHONE_NUMBER_ID_2,  # +91 99033 00044 (Direct API)
}

# All phones use Direct API
DIRECT_API_PHONE_IDS = {PHONE_NUMBER_ID_1, PHONE_NUMBER_ID_2}

# Platform-owned Meta WABA ids. Any OTHER WABA hitting our webhook is an
# Embedded-Signup partner tenant — tag its messages with partnerWabaId so the
# tenant-scoped customer inbox can query the partnerWabaId GSI.
PLATFORM_WABAS = {'2094615664435155', '2513394156072604'}

# How far back a revoke may be inferred to reach. A revoke payload carries no reference
# to the message it deleted (see _apply_revoke), so outside an exact id the join is a
# recency inference, and an inference across days would mis-mark. One hour covers the
# overwhelming majority of real deletions — people delete what they just sent — and
# keeps a false positive near zero. WhatsApp permits delete-for-everyone well beyond an
# hour, so this deliberately UNDER-covers rather than over-claims: widening it trades
# correctness for coverage, and the `revoke_target_unresolved` log line is the evidence
# for whether it should be.
REVOKE_CORRELATION_WINDOW_SECONDS = 3600
# Keys Meta might one day populate with the revoked message's id, in preference order.
# All three are checked because the exact join is strictly better than the inference and
# costs one dict lookup; today none of them is present in a measured payload.
_REVOKE_TARGET_ID_KEYS = ('revoked_message_id', 'id', 'message_id')


def _is_direct_api_phone(phone_number_id: str) -> bool:
    """Check if a phone number ID belongs to a Direct API WABA."""
    return phone_number_id in DIRECT_API_PHONE_IDS


# ── Direct API support ──────────────────────────────────────────────
# All WABAs use Direct Meta Graph API for messaging.
# Token loaded from Secrets Manager (same secret as calling handler).
META_TOKEN_SECRET = os.environ.get('META_TOKEN_SECRET', 'wecare/meta-system-user-token')
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
PHONE1_META_ID = '1016149501586345'  # +91 93309 94400 (WABA1, Direct API)
_direct_api_token_cache = {}
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def _load_direct_api_token() -> str:
    """Load Meta access token for Direct API calls (cached)."""
    if 'token' in _direct_api_token_cache:
        return _direct_api_token_cache['token']
    try:
        resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
        secret = resp.get('SecretString', '')
        try:
            data = json.loads(secret)
            _direct_api_token_cache['token'] = (data.get('access_token') or '').strip()
            _direct_api_token_cache['app_secret'] = (data.get('app_secret') or '').strip()
            # WABA2's app has its own secret; a webhook may be signed by either.
            _direct_api_token_cache['app_secret_waba2'] = (
                data.get('app_secret_waba2') or ''
            ).strip()
        except (json.JSONDecodeError, TypeError):
            _direct_api_token_cache['token'] = secret.strip()
            _direct_api_token_cache['app_secret'] = ''
            _direct_api_token_cache['app_secret_waba2'] = ''
        return _direct_api_token_cache.get('token', '')
    except Exception as e:
        logger.error(f"Failed to load Direct API token: {e}")
        return ''


def _meta_app_secrets() -> list:
    """Candidate Meta app secrets for webhook signature verification."""
    if 'app_secret' not in _direct_api_token_cache:
        _load_direct_api_token()
    return [
        _direct_api_token_cache.get('app_secret', ''),
        _direct_api_token_cache.get('app_secret_waba2', ''),
    ]


def _get_meta_phone_id_for_direct_api(aws_phone_id: str) -> str:
    """Get the Meta phone ID for a Direct API phone number."""
    DIRECT_API_META_MAP = {
        PHONE_NUMBER_ID_1: '1016149501586345',  # +91 93309 94400 (WABA1)
        PHONE_NUMBER_ID_2: '1055232054343117',  # +91 99033 00044 (WABA-T)
    }
    meta_id = DIRECT_API_META_MAP.get(aws_phone_id)
    if meta_id:
        return meta_id
    # Fallback: extract from direct format phone-number-id-*-direct-{meta_id}
    if '-direct-' in aws_phone_id:
        return aws_phone_id.split('-direct-')[-1]
    # Last resort: use WABA-T phone (confirmed working)
    return '1055232054343117'


# Track current phone context for Direct API calls
_current_direct_api_phone = None


def _send_direct_api_read_receipt(whatsapp_message_id: str, meta_phone_id: str = None, show_typing: bool = False) -> Dict:
    """Send a read receipt via Meta Graph API for Direct API phones.
    When show_typing=True, also displays the in-app typing indicator (auto-dismisses
    when you reply or after 25s) — per Meta's typing_indicator API. Only use when a
    reply will follow."""
    token = _load_direct_api_token()
    if not token:
        return {'error': True, 'detail': 'No Direct API token available'}
    payload = {
        'messaging_product': 'whatsapp',
        'status': 'read',
        'message_id': whatsapp_message_id
    }
    if show_typing:
        payload['typing_indicator'] = {'type': 'text'}
    phone_id = meta_phone_id or _current_direct_api_phone or PHONE1_META_ID
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    app_secret = _direct_api_token_cache.get('app_secret', '')
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {'success': True}
    except urllib.error.HTTPError as e:
        # Meta's own response body, so it carries no credential of ours. `url`,
        # `req` and `headers` must never be logged: the URL carries
        # appsecret_proof and the headers carry the bearer token.
        error_body = e.read().decode('utf-8') if e.fp else ''
        logger.warning(json.dumps({'event': 'direct_api_read_receipt_failed',
                                   **graph_errors.log_fields(error_body, e.code)}))
        return {'error': True, 'status': e.code, 'detail': error_body}
    except Exception as e:
        # Only the class name: a URLError's text embeds the request URL.
        logger.warning(f"Direct API read receipt failed: {type(e).__name__}")
        return {'error': True, 'detail': str(e)}


def _graph_error_code(detail) -> str:
    """Meta's numeric error code from a Graph error body, or '' if unparseable.
    Returns the code only — the body can echo request parameters."""
    try:
        return str((json.loads(detail or '{}').get('error') or {}).get('code') or '')
    except Exception:
        return ''


# NOTE: a second `_download_media_direct_api` used to be defined here, taking 5
# positional parameters and no `phone_number_id`. It was dead code: Python binds the
# name to whichever definition executes last, so the 6-parameter definition further
# down in this file always won, and the logs prove it (`media_download_direct_api`
# from that one, never `direct_api_media_downloaded` from this one). It was removed
# on 2026-10-06 together with the two call sites that still passed 5 positional
# arguments to the 6-parameter signature, which silently bound `request_id` to
# `phone_number_id` and the mime hint to `request_id`. Harmless in effect - the
# download does not send `phone_number_id` - but it made the request id in those log
# lines wrong, and it would have become a real defect the moment anything started
# reading that parameter. The surviving call sites pass keyword arguments.


# Stamped as `expiresAt` (30 days). DynamoDB TTL is disabled on the message tables
# (scripts/disable_dynamodb_ttl.py), so nothing deletes these rows; retention is open.
MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60


# ── Coexistence: the owner running the WhatsApp Business APP on the same number as the
# Cloud API. NOT adopted on this deployment. Both fields are audited and counted and
# nothing else: structured parse, NO decision taken from them. `smb_message_echoes`
# carries copies of messages the owner sent from the app, so writing them to the inbox
# would duplicate the owner's own messages into the CRM timeline on a deployment that has
# no coexistence configured. `COEXISTENCE_INGEST_ENABLED` is the seam a future adoption
# would open; it defaults false, and false means audit-only.
#
# The routing module keeps replay payloads out of the live message/status lane.


def _coexistence_ingest_enabled() -> bool:
    """Whether history/app-echo replay is projected into the canonical Inbox.

    SystemConfig `whatsapp_coexistence_ingest` overrides the environment default so an owner
    can enable/disable ingestion without a deploy. The replay lane never calls live-message
    automation and never advances lastInboundMessageAt.
    """
    default = os.environ.get('COEXISTENCE_INGEST_ENABLED', 'false').strip().lower() \
        in ('1', 'true', 'yes', 'on')
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': 'whatsapp_coexistence_ingest'}, ConsistentRead=True).get('Item') or {}
        if 'configValue' in item:
            return str(item.get('configValue') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'coexistence_ingest_config_read_failed',
            'error': type(e).__name__,
        }))
    return default


def _replay_message_content(message: Dict) -> str:
    """Best-effort Inbox text for a Meta history/echo message, without side effects."""
    try:
        msg_type = str(message.get('type') or 'unknown')
        content = _extract_content_v2(message, msg_type)
        if isinstance(content, str):
            return content
    except Exception:
        pass
    msg_type = str(message.get('type') or 'unknown')
    if msg_type == 'media_placeholder':
        return '[Historical media]'
    return f'[Historical {msg_type} message]'


def _ingest_replay_message(message: Dict, user_phone: str, business_phone: str,
                           phone_number_id: str, request_id: str, source: str,
                           *, phase: Any = None, chunk_order: Any = None) -> bool:
    """Project one history/Business-App echo into MessagesTable only.

    This intentionally does NOT call `_process_message`: no keyword/welcome/payment action,
    no media download, no consent mutation, and no 24-hour service-window timestamp update.
    The Meta wamid is the row id, so webhook replay overwrites the same row instead of duplicating.
    """
    user_digits = contact_store.digits(user_phone)
    if not user_digits or not isinstance(message, dict):
        return False
    wamid = str(message.get('id') or '').strip()
    if not wamid:
        return False

    # A history chunk can include messages already received live before coexistence was
    # enabled. Deduplicate on Meta's global message id before choosing a new row id.
    try:
        existing = dynamodb.Table(UNIFIED_MESSAGES_TABLE).query(
            IndexName='whatsappMessageId-index',
            KeyConditionExpression='whatsappMessageId = :w',
            ExpressionAttributeValues={':w': wamid},
            Limit=1,
        ).get('Items') or []
        if existing:
            logger.info(json.dumps({
                'event': 'coexistence_replay_message_already_present',
                'source': source,
                'requestId': request_id,
            }))
            return True
    except Exception as e:
        # Fail closed on a dedup read failure: importing a duplicate is worse than deferring
        # this historical projection, while the raw webhook remains archived for redrive.
        logger.warning(json.dumps({
            'event': 'coexistence_replay_dedup_failed',
            'source': source,
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return False

    try:
        contact = _get_or_create_contact(user_digits)
        contact_id = contact_key.resolve(contact)
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'coexistence_replay_contact_failed',
            'source': source,
            'phone': mask_phone(user_phone),
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return False
    if not contact_id:
        return False

    from_digits = contact_store.digits(message.get('from'))
    business_digits = contact_store.digits(business_phone)
    direction = 'outbound' if from_digits and business_digits and from_digits == business_digits else 'inbound'
    history_context = message.get('history_context') or {}
    raw_status = str(history_context.get('status') or ('sent' if direction == 'outbound' else 'received')).lower()
    status = raw_status if raw_status in ('pending', 'sent', 'delivered', 'read', 'failed', 'received') \
        else ('sent' if direction == 'outbound' else 'received')
    try:
        timestamp = int(message.get('timestamp') or time.time())
    except (TypeError, ValueError):
        timestamp = int(time.time())

    stored = put_message(
        channel='whatsapp',
        direction=direction,
        contact_id=contact_id,
        content=_replay_message_content(message),
        status=status,
        message_id=wamid,
        timestamp=timestamp,
        whatsapp_message_id=wamid,
        message_type=str(message.get('type') or 'unknown'),
        aws_phone_number_id=_get_aws_phone_number_id(
            str(business_phone or ''), str(phone_number_id or ''), [str(phone_number_id or '')]),
        replaySource=source,
        replayOnly=True,
        historyPhase=phase,
        historyChunkOrder=chunk_order,
        raise_on_error=False,
    )
    logger.info(json.dumps({
        'event': 'coexistence_replay_message_ingested' if stored else 'coexistence_replay_message_skipped',
        'source': source,
        'direction': direction,
        'contactId': mask_contact_id(contact_id),
        'wamidPresent': bool(wamid),
        'requestId': request_id,
    }))
    return bool(stored)


def _archive_meta_event(event_type: str, value: Dict, request_id: str,
                        waba_id: str = '', phone_number_id: str = '') -> str:
    """Archive one Meta webhook payload to partitioned JSON in the existing media bucket.

    This is analytics/audit storage only. It never feeds the Inbox, automation, or sends.
    Fail-open so an S3 outage cannot make Meta retry a webhook that was otherwise processed.
    """
    try:
        day = time.strftime('%Y-%m-%d', time.gmtime())
        key = (
            f'secure/d/public/whatsapp/analytics/meta-events/date={day}/event_type={event_type}/'
            f'{int(time.time() * 1000)}-{uuid.uuid4().hex}.json'
        )
        payload = {
            'eventType': event_type,
            'receivedAt': int(time.time()),
            'requestId': request_id,
            'wabaId': waba_id,
            'phoneNumberId': phone_number_id,
            'payload': value,
        }
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=key,
            Body=(json.dumps(payload, default=str, separators=(',', ':')) + '\n').encode('utf-8'),
            ContentType='application/json',
            ServerSideEncryption='AES256',
        )
        return key
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'meta_event_archive_failed',
            'eventType': event_type,
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        return ''


def _record_meta_system_event(event_type: str, value: Dict, request_id: str,
                              waba_id: str = '', phone_number_id: str = '') -> None:
    """Persist a Meta system webhook in both dashboard ring-buffer and durable audit stores."""
    _store_system_event(event_type, value, request_id)
    archive_key = _archive_meta_event(
        event_type, value, request_id, waba_id=waba_id,
        phone_number_id=phone_number_id)
    record_system_event(
        f'whatsapp_{event_type}',
        waba_id=waba_id or None,
        phone_number_id=phone_number_id or None,
        severity='info',
        data={
            'requestId': request_id,
            'archiveKey': archive_key,
            'payload': value,
        },
    )


def _process_history_event(value: Dict, request_id: str, waba_id: str = '') -> None:
    """Persist coexistence history chunks without replaying them as live customer traffic."""
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    history = value.get('history') or []
    if not isinstance(history, list):
        history = []
    _record_meta_system_event('history', value, request_id, waba_id, phone_id)
    for chunk in history:
        if not isinstance(chunk, dict):
            continue
        meta = chunk.get('metadata') or {}
        threads = chunk.get('threads') or []
        if not isinstance(threads, list):
            threads = []
        message_count = sum(
            len((thread or {}).get('messages') or [])
            for thread in threads if isinstance(thread, dict)
        )
        record_system_event(
            'whatsapp_history_chunk',
            waba_id=waba_id or None,
            phone_number_id=phone_id or None,
            severity='info',
            data={
                'requestId': request_id,
                'phase': meta.get('phase'),
                'chunkOrder': meta.get('chunk_order'),
                'progress': meta.get('progress'),
                'threadCount': len(threads),
                'messageCount': message_count,
            },
        )
        if _coexistence_ingest_enabled():
            business_phone = str((value.get('metadata') or {}).get('display_phone_number') or '')
            imported = 0
            for thread in threads:
                if not isinstance(thread, dict):
                    continue
                user_phone = str(thread.get('id') or '')
                for message in (thread.get('messages') or []):
                    if _ingest_replay_message(
                            message, user_phone, business_phone, phone_id, request_id, 'history',
                            phase=meta.get('phase'), chunk_order=meta.get('chunk_order')):
                        imported += 1
            record_system_event(
                'whatsapp_history_chunk_ingested',
                waba_id=waba_id or None,
                phone_number_id=phone_id or None,
                severity='info',
                data={
                    'requestId': request_id,
                    'phase': meta.get('phase'),
                    'chunkOrder': meta.get('chunk_order'),
                    'imported': imported,
                },
            )


def _process_partner_solution_event(value: Dict, request_id: str, waba_id: str = '') -> None:
    """Persist Multi-Partner Solution lifecycle changes as structured audit events."""
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    _record_meta_system_event('partner_solutions', value, request_id, waba_id, phone_id)
    solution = value.get('partner_solution') or value.get('solution') or value
    if not isinstance(solution, dict):
        solution = {}
    record_system_event(
        'whatsapp_partner_solution_change',
        waba_id=waba_id or None,
        phone_number_id=phone_id or None,
        severity='info',
        data={
            'requestId': request_id,
            'solutionId': solution.get('id') or solution.get('solution_id'),
            'partnerId': solution.get('partner_id') or solution.get('partner_business_id'),
            'status': solution.get('status') or solution.get('event'),
        },
    )


def _process_coexistence_event(field: str, value: Dict, request_id: str) -> None:
    """Audit and count a coexistence webhook. Writes NO message row and sends nothing.

    `_store_system_event` is used exactly as the nine informational fields use it, so the
    raw envelope is inspectable in SystemConfigTable without any inbox change.
    `phone_number_id` is NOT a phone number and is logged in full; recipient phones go
    through `mask_phone`.
    """
    phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
    _record_meta_system_event(field, value, request_id, phone_number_id=phone_id)
    if field == 'smb_message_echoes':
        echoes = value.get('message_echoes') or value.get('messages') or []
        if not isinstance(echoes, list):
            echoes = []
        logger.info(json.dumps({
            'event': 'smb_message_echoes_received',
            'echoCount': len(echoes),
            'types': sorted({str((e or {}).get('type', '')) for e in echoes if isinstance(e, dict)}),
            'phoneNumberId': str((value.get('metadata') or {}).get('phone_number_id') or ''),
            'recipients': [mask_phone(str((e or {}).get('to') or '')) for e in echoes
                           if isinstance(e, dict)][:10],
            'ingested': False,
            'requestId': request_id,
        }))
    else:
        state = value.get('state') or value.get(field) or {}
        logger.info(json.dumps({
            'event': 'smb_app_state_sync_received',
            'contactCount': len(state.get('contacts') or []) if isinstance(state, dict) else 0,
            'chatCount': len(state.get('chats') or []) if isinstance(state, dict) else 0,
            'phoneNumberId': str((value.get('metadata') or {}).get('phone_number_id') or ''),
            'ingested': False,
            'requestId': request_id,
        }))
    if _coexistence_ingest_enabled() and field == 'smb_message_echoes':
        business_phone = str((value.get('metadata') or {}).get('display_phone_number') or '')
        phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
        echoes = value.get('message_echoes') or value.get('messages') or []
        imported = 0
        for message in echoes if isinstance(echoes, list) else []:
            if not isinstance(message, dict):
                continue
            user_phone = str(message.get('to') or '')
            if _ingest_replay_message(
                    message, user_phone, business_phone, phone_id, request_id, 'smb_message_echoes'):
                imported += 1
        logger.info(json.dumps({
            'event': 'smb_message_echoes_ingested',
            'imported': imported,
            'phoneNumberId': phone_id,
            'requestId': request_id,
        }))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process inbound WhatsApp messages from SNS.
    
    Meta Webhook Event Format:
    {
        "context": { "MetaWabaIds": [...], "MetaPhoneNumberIds": [...] },
        "whatsAppWebhookEntry": "{...JSON STRING...}",
        "aws_account_id": "775261844268",
        "message_timestamp": "2026-01-17T12:00:00.000Z",
        "messageId": "uuid"
    }
    """
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    processed_count = 0
    error_count = 0
    
    # Timeout guard: reserve 15s for cleanup/response to avoid Lambda timeout
    _lambda_deadline_ms = (context.get_remaining_time_in_millis() if context else 120000)
    _start_time = time.time()

    # ── Authenticate anything arriving over HTTP, before any side effect ──
    # The production path is an internal `lambda_client.invoke` from
    # wecare-whatsapp-calling, which has already verified Meta's
    # X-Hub-Signature-256 on the canonical /whatsapp ingress. But this function
    # also sits behind a public `POST /whatsapp/inbound` route with
    # AuthorizationType=NONE, and until 2026-09-21 that door required no
    # signature, no token and no Cognito identity - so an anonymous caller could
    # inject forged messages into the inbox and reach create_invoice.
    #
    # An internally invoked event carries no API Gateway envelope, so this guard
    # applies only to the public door and leaves the verified path untouched.
    _via_http = meta_signature.is_http_request(event)
    if _via_http:
        _ok, _reason = meta_signature.verify(event, _meta_app_secrets())
        if not _ok:
            logger.warning(json.dumps({
                'event': 'inbound_http_signature_rejected',
                'reason': _reason,
                'requestId': request_id,
            }))
            return {
                'statusCode': 401,
                'body': json.dumps({'success': False, 'error': 'invalid_signature'}),
            }

    # ── Direct invoke: create_invoice from dashboard ──
    # Internal callers only (core/messages-delete invokes this). A signed Meta
    # webhook never carries `action`, so honouring it over HTTP would only ever
    # serve a forged request.
    if event.get('action') == 'create_invoice':
        if _via_http:
            logger.warning(json.dumps({
                'event': 'inbound_http_action_rejected',
                'action': 'create_invoice',
                'requestId': request_id,
            }))
            return {
                'statusCode': 401,
                'body': json.dumps({'success': False, 'error': 'internal_invocation_only'}),
            }
        # The legacy free-form invoice path (own PNG, float maths, 2% fee, WD-PAY-<hex>) is
        # retired: it rendered outside the GST series. Callers must use the invoice engine's GST
        # series instead; the action is answered with a terminal 410 rather than silently dropped.
        logger.info(json.dumps({
            'event': 'create_invoice_gone',
            'requestId': request_id,
        }))
        return {'statusCode': 410, 'success': False, 'error': 'INVOICE_CREATION_MOVED'}
    
    # Accept the typed contract from the ingress AND the legacy synthetic SNS
    # envelope. Both arms are load-bearing: the ingress and this worker deploy
    # separately and the invoke is asynchronous, so in-flight events can carry the
    # old shape, and dlq-replay may hold stored payloads in it for its retention
    # period. `shape` is logged so the legacy arm's retirement can be measured
    # rather than guessed. See lambda_utils/wa_internal_event.
    _work_items = wa_internal_event.parse(event)

    logger.info(json.dumps({
        'event': 'inbound_processing_start',
        'itemCount': len(_work_items),
        'shapes': sorted({i['shape'] for i in _work_items}),
        'requestId': request_id
    }))

    if not _work_items:
        logger.warning(json.dumps({
            'event': 'inbound_unrecognised_event',
            'topLevelKeys': sorted(k for k in event.keys())[:12],
            'requestId': request_id,
        }))

    for _item in _work_items:
        try:
            meta_waba_ids = _item['waba_ids']
            meta_phone_number_ids = _item['phone_number_ids']
            aws_message_id = _item['message_id'] or str(uuid.uuid4())
            webhook_entry = _item['entry']
            
            # Process each change in the webhook entry
            for change in webhook_entry.get('changes', []):
                routed = webhook_routing.parse_change(change)
                value = routed.value
                metadata = routed.metadata

                # Keep acknowledging these retired routing changes without storage
                # or replies. The alarm catches a provider-side rollout mismatch.
                if routed.retired_routing:
                    log_event(
                        logger, webhook_routing.IGNORED_ROUTING_EVENT, level='warning',
                        field=routed.field, requestId=request_id,
                        wabaId=webhook_routing.ignored_account_label(
                            webhook_entry.get('id'),
                            _item.get('waba_id') if _item.get('shape') != 'legacy-sns' else '',
                            direct_send.META_PHONE_TO_WABA.values()),
                    )
                    continue

                display_phone_number = metadata.get('display_phone_number', '')
                phone_number_id = metadata.get('phone_number_id', '')
                _inbound_messages = routed.live_messages
                # Status and replay changes do not need an AWS number lookup.
                aws_phone_number_id = (
                    _get_aws_phone_number_id(display_phone_number, phone_number_id,
                                             meta_phone_number_ids)
                    if _inbound_messages else ''
                )
                contacts_map = webhook_routing.contacts_by_identity(value)

                # Process incoming messages
                for _message_index, message in enumerate(_inbound_messages):
                    # Timeout guard: skip remaining messages if <15s left. It sits outside the
                    # per-message try, so its failure is never handled as one message's error.
                    if context and context.get_remaining_time_in_millis() < 15000:
                        logger.warning(json.dumps({
                            'event': 'timeout_guard_triggered',
                            'remainingMs': context.get_remaining_time_in_millis(),
                            'processedCount': processed_count,
                            'requestId': request_id
                        }))
                        # Park the unprocessed rest as the typed event dlq-replay hands back
                        # to this worker. The old `{'messages': [...]}` record matched no
                        # shape wa_internal_event.parse accepts, so a replay reproduced
                        # nothing; and slicing by the request-wide processed_count dropped
                        # messages once an earlier change had any. Statuses stay out: this
                        # run still processes them below.
                        _remaining_value = {k: v for k, v in value.items() if k != 'statuses'}
                        _remaining_value['messages'] = _inbound_messages[_message_index:]
                        parked = _send_to_dlq(
                            wa_internal_event.build(
                                entry={**webhook_entry,
                                       'changes': [{**change, 'value': _remaining_value}]},
                                waba_id=_item.get('waba_id') or '',
                                meta_phone_number_ids=meta_phone_number_ids,
                                request_id=request_id,
                            ),
                            'timeout_guard', request_id)
                        if not parked:
                            # Nothing durable holds these messages. The record-level handler
                            # parks the work item or fails the invocation; never acknowledge.
                            raise RuntimeError('timeout_guard_park_failed')
                        break
                    try:
                        message_dedup.process_tracked_message(
                            _process_message,
                            message=message,
                            metadata=metadata,
                            request_id=request_id,
                            receiving_phone=display_phone_number,
                            aws_phone_number_id=aws_phone_number_id,
                            meta_waba_ids=meta_waba_ids,
                            **webhook_routing.sender_profile(message, contacts_map),
                        )
                        processed_count += 1
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'message_processing_error',
                            'messageId': message.get('id'),
                            'error': ('IdentityConflict' if isinstance(e, contact_store.IdentityConflict)
                                      else str(e)),
                            'requestId': request_id
                        }))
                        error_count += 1
                        if not isinstance(e, ValueError):
                            # ValueError is bad input and is acknowledged. Anything else (an
                            # ambiguous identity, a store or provider error) parks a copy of
                            # THIS message (not the other messages/statuses in the webhook
                            # batch) for durable retry, so it is never acknowledged and lost.
                            conflict_value = {k: v for k, v in value.items() if k != 'statuses'}
                            conflict_value['messages'] = [message]
                            parked_event = wa_internal_event.build(
                                entry={**webhook_entry,
                                       'changes': [{**change, 'value': conflict_value}]},
                                waba_id=_item.get('waba_id') or '',
                                meta_phone_number_ids=meta_phone_number_ids,
                                request_id=request_id,
                            )
                            if isinstance(e, contact_store.IdentityConflict):
                                parked = _send_to_dlq(parked_event, 'customer_identity_conflict', request_id)
                            else:
                                parked = _send_to_dlq(parked_event, f'message_processing_error:{type(e).__name__}',
                                                      request_id)
                            if not parked:
                                raise  # force upstream retry rather than acknowledging a lost message
                            logger.error(json.dumps({
                                'event': 'inbound_message_parked', 'alert': 'INBOUND_PARKED_IN_DLQ',
                                'scope': 'message', 'messageId': message.get('id'),
                                'errorType': type(e).__name__, 'requestId': request_id,
                            }))
                
                # Process status updates
                # Same coexistence guard, same reason: `_process_status` writes to both
                # message tables, and a coexistence envelope must reach neither.
                _status_waba_id = (meta_waba_ids[0] if meta_waba_ids else '')
                for status in routed.live_statuses:
                    try:
                        _process_status(status, request_id, contacts_map=contacts_map, waba_id=_status_waba_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'status_processing_error',
                            'statusId': status.get('id'),
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process template status updates (APPROVED, REJECTED, PAUSED, etc.)
                field = routed.field
                if field == 'message_template_status_update':
                    try:
                        _process_template_status(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'template_status_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))

                # Flow lifecycle and endpoint-health webhooks. The ingress has always forwarded
                # this field; until 2026-10-25 nothing here read it, so a BLOCKED Flow or a failing
                # endpoint was silent.
                if field == 'flows':
                    try:
                        _process_flow_event(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'flow_event_processing_error',
                            'error': type(e).__name__,
                            'requestId': request_id
                        }))
                
                # Process phone number quality updates
                if field == 'phone_number_quality_update':
                    try:
                        _process_phone_quality_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'phone_quality_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process account updates (messaging limits, etc.)
                if field == 'account_update':
                    try:
                        _process_account_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'account_update_processing_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # `user_id_update` is NOT a real Meta webhook field (confirmed by the
                # Aug 11 2026 BSUID changelog: "There is no user_id_update webhook field").
                # BSUID changes arrive as a `system` MESSAGE and are handled in
                # `_process_message` (system.type user_changed_number / user_changed_user_id).
                # This arm is kept only as a forward-compatible audit sink: if Meta ever does
                # emit such a field, we record it rather than drop it silently. No contact is
                # mutated here — that is the system-message path's job.
                if field == 'user_id_update':
                    _store_system_event('user_id_update', value, request_id)  # audit trail only
                
                # Process business_username_updates webhook (Meta field is plural;
                # accept singular too for forward/backward compatibility)
                if field in ('business_username_updates', 'business_username_update'):
                    try:
                        _process_business_username_update(value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'business_username_updates_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # Process user_preferences webhook (marketing message opt-in/out with BSUID)
                if field == 'user_preferences':
                    try:
                        _store_system_event('user_preferences', value, request_id)
                        # Also enrich contact BSUID from user_preferences contacts array
                        for pref in value.get('user_preferences', []):
                            pref_bsuid = pref.get('user_id', '')
                            pref_phone = pref.get('wa_id', '')
                            if pref_bsuid and pref_phone:
                                try:
                                    contact = _get_contact_by_phone(pref_phone)
                                    if contact:
                                        ct = dynamodb.Table(CONTACTS_TABLE)
                                        _update_contact_bsuid_fields(ct, contact, '', '', phone=pref_phone, bsuid=pref_bsuid)
                                except Exception as e:
                                    logger.warning(json.dumps({
                                        'event': 'bsuid_enrichment_failed',
                                        'phone': mask_phone(pref_phone),
                                        'error': type(e).__name__}))
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'user_preferences_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                    # Marketing stop/resume is consent evidence for the ledger outbound
                    # MARKETING sends read. A failed write is parked, never dropped.
                    try:
                        _record_marketing_preferences(value, metadata, meta_waba_ids, request_id)
                    except Exception as e:
                        parked = _send_to_dlq(
                            wa_internal_event.build(
                                entry={**webhook_entry, 'changes': [change]},
                                waba_id=_item.get('waba_id') or '',
                                meta_phone_number_ids=meta_phone_number_ids,
                                request_id=request_id,
                            ), f'user_preferences_consent:{type(e).__name__}', request_id)
                        if not parked:
                            raise
                        logger.error(json.dumps({
                            'event': 'user_preferences_consent_parked', 'alert': 'INBOUND_PARKED_IN_DLQ',
                            'scope': 'user_preferences', 'errorType': type(e).__name__,
                            'requestId': request_id,
                        }))
                
                # Process group webhook events (group_participant_change, group_membership_approval_request)
                if field == 'group_participant_change':
                    try:
                        _store_system_event('group_participant_change', value, request_id)
                        _process_group_event(value, 'participant_change', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_participant_change_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_membership_approval_request':
                    try:
                        _store_system_event('group_membership_approval_request', value, request_id)
                        _process_group_event(value, 'membership_approval', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_membership_approval_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_lifecycle_update':
                    try:
                        _store_system_event('group_lifecycle_update', value, request_id)
                        _process_group_event(value, 'lifecycle', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_lifecycle_update_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                if field == 'group_settings_update':
                    try:
                        _store_system_event('group_settings_update', value, request_id)
                        _process_group_event(value, 'settings_update', request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'group_settings_update_error',
                            'error': str(e),
                            'requestId': request_id
                        }))
                
                # ── Coexistence (WhatsApp Business app on a Cloud API number) ──
                # Audited and counted, never acted on — see `_process_coexistence_event`.
                # NO `continue` here, matching the four group arms above: they are
                # sequential `if field == '...'` blocks that fall through to the
                # `_SYSTEM_EVENT_FIELDS` membership test below. Falling through is safe
                # because neither coexistence field is in that set, so the fall-through
                # reaches no second handler.
                if field in webhook_routing.COEXISTENCE_FIELDS:
                    try:
                        _process_coexistence_event(field, value, request_id)
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'coexistence_event_error',
                            'field': field,
                            'error': type(e).__name__,
                            'requestId': request_id
                        }))

                # ── Additional Meta webhook fields (per official docs) ──
                # These are informational/system-level events that we log to SystemEvent
                # for audit trail and operational awareness.
                # Ref: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
                if field == 'history':
                    try:
                        _process_history_event(
                            value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '')
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'webhook_history_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))

                if field == 'partner_solutions':
                    try:
                        _process_partner_solution_event(
                            value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '')
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': 'webhook_partner_solutions_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))

                _SYSTEM_EVENT_FIELDS = {
                    'account_alerts', 'account_review_update',
                    'automatic_events',
                    'business_capability_update', 'business_status_update',
                    'message_template_components_update',
                    'message_template_quality_update',
                    'payment_configuration_update',
                    'phone_number_name_update', 'security',
                    'template_category_update',
                    'tracking_events',
                }
                if field in _SYSTEM_EVENT_FIELDS:
                    try:
                        phone_id = str((value.get('metadata') or {}).get('phone_number_id') or '')
                        _record_meta_system_event(
                            field, value, request_id,
                            meta_waba_ids[0] if meta_waba_ids else '',
                            phone_id)
                        logger.info(json.dumps({
                            'event': f'webhook_{field}_stored',
                            'field': field,
                            'requestId': request_id,
                        }))
                    except Exception as e:
                        logger.error(json.dumps({
                            'event': f'webhook_{field}_error',
                            'error': type(e).__name__,
                            'requestId': request_id,
                        }))
                        
        except Exception as e:
            logger.error(json.dumps({
                'event': 'record_processing_error',
                'error': str(e),
                'shape': _item.get('shape'),
                'requestId': request_id
            }))
            # DLQ the normalized work item, not the raw envelope. dlq-replay
            # invokes the stored payload directly, and wa_internal_event.parse
            # accepts this shape, so a replay now actually reproduces the work -
            # which it could not do when the stored record was half of an SNS
            # envelope the worker no longer looked at.
            parked = _send_to_dlq(
                wa_internal_event.build(
                    entry=_item.get('entry') or {},
                    waba_id=_item.get('waba_id') or '',
                    meta_phone_number_ids=_item.get('phone_number_ids') or [],
                    request_id=request_id,
                ),
                str(e), request_id,
            )
            error_count += 1
            if not parked:
                raise  # nothing durable holds this work item: fail the invoke so it is retried
            logger.error(json.dumps({
                'event': 'inbound_record_parked', 'alert': 'INBOUND_PARKED_IN_DLQ',
                'scope': 'record', 'errorType': type(e).__name__, 'requestId': request_id,
            }))
    
    logger.info(json.dumps({
        'event': 'inbound_processing_complete',
        'processedCount': processed_count,
        'errorCount': error_count,
        'requestId': request_id
    }))
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': processed_count,
            'errors': error_count
        })
    }


def _get_aws_phone_number_id(display_phone: str, meta_phone_id: str,
                             entry_phone_ids: Optional[list] = None) -> str:
    """
    Map display phone number or Meta phone ID to phone number ID.
    Returns the appropriate AWS phone number ID for sending reactions.
    For Direct API phones, returns a synthetic ID for tracking purposes.
    `entry_phone_ids` is the webhook entry's own phone-id list, used when
    `value.metadata` is absent.
    """
    # Clean display phone number (remove + and spaces)
    clean_phone = display_phone.replace('+', '').replace(' ', '').replace('-', '')
    
    # Check if we have a mapping for this phone number
    if clean_phone in PHONE_NUMBER_MAP:
        return PHONE_NUMBER_MAP[clean_phone]
    
    # Check Meta phone number ID mapping (for Direct API WABAs)
    if meta_phone_id in META_PHONE_ID_MAP:
        return META_PHONE_ID_MAP[meta_phone_id]

    # The entry names the phone even when `value.metadata` does not. Prefer a real
    # id over a default; only then fall back.
    for pid in (entry_phone_ids or []):
        if pid in META_PHONE_ID_MAP:
            return META_PHONE_ID_MAP[pid]

    # Default to first phone number ID if no mapping found
    logger.warning(json.dumps({
        'event': 'phone_number_mapping_not_found',
        'displayPhone': mask_phone(display_phone),
        'metaPhoneId': meta_phone_id,
        'usingDefault': PHONE_NUMBER_ID_1
    }))
    return PHONE_NUMBER_ID_1


def _epoch_or_zero(value) -> int:
    """Read a stored `timestamp` as epoch seconds, scoring anything unreadable as 0.

    build_message_item in lambda_utils/message_store.py writes Decimal epoch seconds
    (message_store.py:88), but the unified Message model DECLARES `timestamp: a.datetime()`
    (amplify/data/resource.ts:161) — an ISO-8601 string. DynamoDB is schemaless, so both
    shapes can coexist in one table and any producer or backfill honouring the declared
    model type puts a string there. A bare int() on one such row raises ValueError inside
    a list comprehension, which would break _apply_revoke's "never raises" contract and
    surface as `revoke_apply_error` — indistinguishable in the logs from "no candidate".

    Scoring 0 puts the row OUTSIDE the window rather than throwing, so one malformed row
    costs that row and not the whole resolution.
    """
    try:
        return int(Decimal(str(value)))
    except (TypeError, ValueError, ArithmeticError):
        return 0


def _apply_revoke(message: Dict, contact_id: str, revoke_message_id: str,
                  revoke_wamid: str, sender_phone: str, timestamp: int,
                  request_id: str) -> None:
    """Mark the inbound message a revoke deleted. Audit-only on failure; never raises.

    Resolution is two-tier, and BOTH tiers resolve against the unified MessagesTable so
    they can only ever produce the same primary key:
      exact    -- Meta supplied the revoked message's wamid; resolve it through
                  UNIFIED_MESSAGES_TABLE's whatsappMessageId-index, the same lookup
                  shape _process_status uses.
      inferred -- no id available, so take the single most recent inbound WhatsApp
                  message from this contact that is older than the revoke and inside
                  REVOKE_CORRELATION_WINDOW_SECONDS. EXACTLY ONE candidate, or nothing
                  is marked.

    `sender_phone` is used only in the declined-resolution log line, masked, so a
    decline is traceable to a conversation. The inferred tier keys on `contact_id`,
    which is what contactId-index is built on.

    The original content is NOT deleted or redacted — the row is the provenance record
    for a conversation, and `isRevoked` is what the inbox renders. Deleting it would
    destroy an audit trail to satisfy a presentation concern.
    """
    # Step 1 — read whatever id the payload might carry.
    target_wamid = ''
    rv = message.get('revoke')
    for src in (rv if isinstance(rv, dict) else {}, message.get('context') or {}, message):
        for k in _REVOKE_TARGET_ID_KEYS:
            cand = str((src or {}).get(k) or '')
            if cand and cand != revoke_wamid:
                target_wamid = cand
                break
        if target_wamid:
            break

    target_id = ''
    resolution = ''

    if target_wamid:
        # Exact tier. The UNIFIED table, deliberately: the inferred tier reads it and
        # messages-read serves it to the inbox, so both tiers must key on the same
        # store or the same revoke would mark different rows depending on which tier
        # fired. Index: amplify/data/resource.ts:184.
        try:
            resp = dynamodb.Table(UNIFIED_MESSAGES_TABLE).query(
                IndexName='whatsappMessageId-index',
                KeyConditionExpression='whatsappMessageId = :w',
                ExpressionAttributeValues={':w': target_wamid}, Limit=1)
            items = resp.get('Items') or []
        except Exception as e:  # noqa: BLE001 — degrade, never fail the revoke
            # A missing or not-yet-active index degrades to the inferred tier rather
            # than failing the revoke. No scan fallback: _process_status has one for a
            # path that must not lose a delivery receipt, whereas a revoke that cannot
            # be resolved is already a defined outcome here.
            logger.warning(json.dumps({'event': 'revoke_exact_lookup_failed',
                                       'error': type(e).__name__,
                                       'requestId': request_id}))
            items = []
        if items:
            target_id = str(items[0].get('id') or items[0].get('messageId') or '')
            resolution = 'exact'

    if not target_id:
        # Inferred tier. It also runs when an exact id matched nothing, so a supplied
        # id that resolves to no row FALLS THROUGH rather than declining.
        #
        # query_by_contact reads the UNIFIED MessagesTable on its default —
        # message_store's own module-level MESSAGES_TABLE is
        # os.environ['UNIFIED_MESSAGES_TABLE'] (message_store.py:40), which is the
        # OPPOSITE of this handler's MESSAGES_TABLE (the inbound table). No
        # table_name is passed, deliberately: the default is the table both tiers and
        # the inbox agree on, and "clarifying" it later by passing MESSAGES_TABLE
        # through reads like a tightening and is the bug.
        #
        # Then filter in memory: contactId-index returns index order, NOT
        # newest-first, and carries no sort-key condition, so element 0 is not the
        # most recent and the window predicate does the selection.
        candidates = [
            m for m in query_by_contact(contact_id, limit=50)
            if str(m.get('channel', '')) == 'whatsapp'
            and str(m.get('direction', '')) == 'inbound'
            and not m.get('isRevoked')
            and not m.get('paymentReferenceId')      # a payment row is never a revoke target
            and str(m.get('messageType', '')) not in ('revoke', 'edit')
            and str(m.get('whatsappMessageId', '')) != revoke_wamid
            and 0 < (timestamp - _epoch_or_zero(m.get('timestamp')))
                  <= REVOKE_CORRELATION_WINDOW_SECONDS
        ]
        if len(candidates) == 1:
            target_id = str(candidates[0].get('id') or candidates[0].get('messageId') or '')
            resolution = 'inferred'
        if not target_id:
            # Two candidates means we do not know which was deleted, and marking the
            # newer one would be a coin flip presented as an answer. `hadExactId` is
            # what distinguishes "no id" from "id that matched nothing".
            logger.info(json.dumps({
                'event': 'revoke_target_unresolved',
                'candidateCount': len(candidates),
                'reason': 'no_candidate' if not candidates else 'ambiguous',
                'hadExactId': bool(target_wamid),
                # mask_contact_id, not the raw value: a WhatsApp contactId is `wa` plus
                # the customer's E.164 digits (privacy.py), so logging it whole is a
                # disclosure. It passes a uuid-form contactId through untouched, so the
                # correlation key survives where it discloses nothing.
                'contactId': mask_contact_id(contact_id),
                'senderPhone': mask_phone(sender_phone),
                'requestId': request_id}))
            return

    update_expr = ('SET isRevoked = :t, revokedAt = :ts, '
                   'revokedByWhatsappMessageId = :rw, revokeResolution = :res')
    values = {':t': True, ':ts': Decimal(str(timestamp)),
              ':rw': revoke_wamid, ':res': resolution}
    # dict.fromkeys de-duplicates while preserving order: if the two env vars are ever
    # pointed at one table, writing twice would make the second write fail its own
    # attribute_not_exists(isRevoked) condition against the write the loop just made.
    # _process_status:3594 guards the same hazard with an explicit table comparison.
    for table_name in dict.fromkeys((MESSAGES_TABLE, UNIFIED_MESSAGES_TABLE)):
        try:
            dynamodb.Table(table_name).update_item(
                Key={'id': target_id}, UpdateExpression=update_expr,
                ConditionExpression='attribute_exists(id) AND attribute_not_exists(isRevoked)',
                ExpressionAttributeValues=values)
        except ClientError as ce:
            if ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
            # A redelivered revoke, or a row this table does not hold. Not an error:
            # the guard did its job.
            logger.info(json.dumps({'event': 'revoke_already_applied',
                                    'messageId': target_id, 'table': table_name,
                                    'requestId': request_id}))
        except Exception as e:  # noqa: BLE001 — audit-only
            logger.warning(json.dumps({'event': 'revoke_mark_failed',
                                       'table': table_name, 'error': type(e).__name__,
                                       'requestId': request_id}))

    # Back-link the revoke's own row, so the relationship is navigable from either end.
    # BOTH tables, not just MESSAGES_TABLE: the inbox reads the unified MessagesTable and
    # only that (messages-read/handler.py:44-45), so a back-link written only to
    # WhatsAppInboundTable could never reach the frontend and the revoke bubble would
    # never stop rendering — the exact double render this exists to remove.
    #
    # `attribute_exists(id)` ONLY, with no attribute_not_exists: unlike the target mark a
    # back-link is idempotent, so a redelivered revoke rewriting the same two values is
    # harmless and must not log a spurious conditional failure.
    for table_name in dict.fromkeys((MESSAGES_TABLE, UNIFIED_MESSAGES_TABLE)):
        try:
            dynamodb.Table(table_name).update_item(
                Key={'id': revoke_message_id},
                UpdateExpression='SET revokesMessageId = :t, revokeResolution = :res',
                ConditionExpression='attribute_exists(id)',
                ExpressionAttributeValues={':t': target_id, ':res': resolution})
        except ClientError as ce:
            # The revoke row is missing from this table — the mirror must not create
            # one. Same reading as the target write: the condition did its job.
            if ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
        except Exception as e:  # noqa: BLE001 — audit-only
            logger.warning(json.dumps({'event': 'revoke_backlink_failed',
                                       'table': table_name, 'error': type(e).__name__,
                                       'requestId': request_id}))


def _process_message(
    message: Dict,
    metadata: Dict,
    request_id: str,
    receiving_phone: str,
    aws_phone_number_id: str,
    meta_waba_ids: list,
    sender_profile_name: str = '',
    sender_bsuid: str = '',
    sender_parent_bsuid: str = '',
    sender_username: str = '',
    sender_contact_book_name: str = '',
    dedup_tracker: Optional[list] = None,
) -> None:
    """
    Process a single inbound message.
    Stores which WABA/phone number received the message.
    Supports BSUID (Business-Scoped User ID), parent BSUID, and username from webhook.
    """
    whatsapp_message_id = message.get('id')
    sender_phone = message.get('from', '')
    # BSUID: from_user_id in message takes precedence over contacts array
    msg_bsuid = message.get('from_user_id', '') or sender_bsuid
    # Parent BSUID: from_parent_user_id in message takes precedence over contacts array
    msg_parent_bsuid = message.get('from_parent_user_id', '') or sender_parent_bsuid
    source_waba_id = _message_account_id(metadata, meta_waba_ids,
                                         needs_bsuid=bool(msg_bsuid))
    msg_type = message.get('type', 'text')
    timestamp = int(message.get('timestamp', time.time()))

    # ── Detect real content type for "unsupported" messages ──
    # Meta marks many messages as 'unsupported' but they still carry media/text
    # data. Detect the actual type so the inbox can render them properly.
    if msg_type == 'unsupported':
        # Meta names the real type in `unsupported.type` / `unsupported.raw_type`.
        # Reading it is what makes the `revoke` and `edit` extractors reachable at
        # all; before this they were dispatch-table entries nothing could ever hit.
        # Membership is tested against KNOWN_TYPES (the dispatch table itself) rather
        # than a second hand-copied list. `unknown` is not in it, so the measured
        # 125-of-128 case falls through to extract_unsupported_content unchanged.
        # A revoke stores its own row AND marks the message it deleted — see
        # `_apply_revoke`, called from the bottom of this function. The measured payload
        # carries no `context` key, so there is no `context.id` to join on; resolution is
        # therefore two-tier (an exact wamid when Meta ever supplies one, else a
        # single-candidate recency inference inside REVOKE_CORRELATION_WINDOW_SECONDS)
        # and it is allowed to decline. Nothing is deleted or redacted.
        _u = message.get('unsupported')
        if not isinstance(_u, dict):
            _u = {}
        _recovered = _u.get('type') or _u.get('raw_type')
        if _recovered and _recovered != 'unsupported' and _recovered in _KNOWN_TYPES:
            msg_type = _recovered
            logger.info(json.dumps({
                'event': 'unsupported_type_recovered',
                'source': 'unsupported.type',
                'recoveredType': _recovered,
                'whatsappMessageId': whatsapp_message_id,
                'requestId': request_id
            }))
        # The media five are the only types this probe can ever match: the guard
        # below needs a dict carrying an `id`, and `contacts` is a list while
        # `location`/`reaction`/`poll` carry no id. They were listed anyway, which
        # read as coverage that did not exist.
        for probe_type in ('image', 'video', 'audio', 'document', 'sticker'):
            if msg_type != 'unsupported':
                break
            probe_data = message.get(probe_type)
            if isinstance(probe_data, dict) and probe_data.get('id'):
                # Has a media ID  -  this is a real media message wrapped as unsupported
                # (common for view-once, multi-image bundles)
                msg_type = probe_type
                logger.info(json.dumps({
                    'event': 'unsupported_type_recovered',
                    'recoveredType': probe_type,
                    'whatsappMessageId': whatsapp_message_id,
                    'requestId': request_id
                }))
                break
        # Check for text body in unsupported wrapper
        if msg_type == 'unsupported':
            text_data = message.get('text', {})
            if isinstance(text_data, dict) and text_data.get('body'):
                msg_type = 'text'
                logger.info(json.dumps({
                    'event': 'unsupported_type_recovered',
                    'recoveredType': 'text',
                    'whatsappMessageId': whatsapp_message_id,
                    'requestId': request_id
                }))
    
    # Log the shape of an unsupported or unrecognized type to help debug: type, key names
    # and a masked sender only. The message itself carries text, names, numbers, places.
    if msg_type in ('unsupported', 'unknown') or msg_type not in (
        'text', 'image', 'video', 'audio', 'document', 'sticker',
        'location', 'contacts', 'reaction', 'interactive', 'button',
        'order', 'system', 'request_welcome', 'ephemeral',
        'referral', 'ad_click', 'product', 'product_inquiry', 'poll',
        'edit', 'revoke',
    ):
        _typed = message.get(str(message.get('type') or ''))
        logger.warning(json.dumps({
            'event': 'unsupported_or_new_message_type',
            'senderPhone': mask_phone(sender_phone),
            'whatsappMessageId': whatsapp_message_id,
            'messageType': msg_type,
            'messageKeys': list(message.keys()),
            'typeKeys': sorted(str(k) for k in _typed.keys())[:30] if isinstance(_typed, dict) else [],
            'requestId': request_id
        }))
    
    # Use sender profile name from contacts array (passed in)
    # Fall back to checking message.profile if not provided
    sender_name = sender_profile_name
    if not sender_name and 'profile' in message:
        sender_name = message.get('profile', {}).get('name', '')
    
    # Save endpointless Flow business records before inbox dedup. A retry must repair a
    # failed contact/activity projection even when the transport message already exists.
    _referral_data = referral_response.referral_payload(message)
    _referral_contact = None
    _referral_result = None
    if _referral_data is not None:
        _referral_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _referral_result = referral_response.save_referral(
            _referral_data,
            contact_id=_referral_contact.get('contactId') or _referral_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, request_id=request_id,
            customer_uuid_value=str(_referral_contact.get('customerUuid') or ''))

    _idea_data = customer_ideas.idea_payload(message)
    _idea_contact = None
    _idea_result = None
    if _idea_data is not None:
        _idea_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _idea_result = customer_ideas.save_idea(
            _idea_data, contact_id=_idea_contact.get('contactId') or _idea_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id,
            customer_uuid_value=str(_idea_contact.get('customerUuid') or ''))

    _track_shipping_data = track_shipping_response.tracking_payload(message)
    _track_shipping_contact = None
    _track_shipping_result = None
    if _track_shipping_data is not None:
        _track_shipping_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _track_shipping_result = track_shipping_response.save_tracking(
            _track_shipping_data,
            contact_id=_track_shipping_contact.get('contactId')
                or _track_shipping_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    # Pickup has its own service code and paid-order contract. Parse before the
    # F004 Submit Request fallback so a cloned marker can never be filed as SR.
    _pickup_data = pickup_request_response.pickup_payload(message)
    _pickup_contact = None
    _pickup_result = None
    if _pickup_data is not None:
        _pickup_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _pickup_result = pickup_request_response.save_pickup(
            _pickup_data,
            contact_id=_pickup_contact.get('contactId') or _pickup_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    _submit_request_data = submit_request_response.request_payload(message)
    _submit_request_contact = None
    _submit_request_result = None
    if _submit_request_data is not None:
        _submit_request_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _submit_request_result = submit_request_response.save_request(
            _submit_request_data,
            contact_id=_submit_request_contact.get('contactId') or _submit_request_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    _request_amendment_data = request_amendment_response.amendment_payload(message)
    _request_amendment_contact = None
    _request_amendment_result = None
    if _request_amendment_data is not None:
        _request_amendment_contact = _get_or_create_contact(
            sender_phone, sender_name, bsuid=msg_bsuid, username=sender_username,
            contact_book_name=sender_contact_book_name, parent_bsuid=msg_parent_bsuid,
            waba_id=source_waba_id)
        _request_amendment_result = request_amendment_response.save_amendment(
            _request_amendment_data,
            contact_id=_request_amendment_contact.get('contactId')
                or _request_amendment_contact.get('id'),
            phone=sender_phone, sender_name=sender_name,
            message_id=whatsapp_message_id, dynamodb=dynamodb,
            request_id=request_id)

    if message_dedup.should_skip_duplicate(
            whatsapp_message_id, message_exists=_message_exists,
            dedup_tracker=dedup_tracker, logger=logger, request_id=request_id):
        return

    # A Meta BSUID change must rejoin the PREVIOUS canonical contact before
    # resolving the new BSUID. Otherwise a phone-hidden system event auto-creates
    # a second customer and strands the original history.
    previous_system_contact = None
    if msg_type == 'system':
        system_change = message.get('system') or {}
        if system_change.get('type') in ('user_changed_user_id', 'user_changed_number'):
            previous_system_bsuid = str(system_change.get('previous_user_id') or '')
            if previous_system_bsuid:
                previous_system_contact = _find_scoped_bsuid(
                    dynamodb.Table(CONTACTS_TABLE), previous_system_bsuid,
                    source_waba_id, sender_phone=sender_phone)
                if previous_system_contact is None and not sender_phone:
                    raise contact_store.IdentityConflict('unresolved-previous-bsuid', ())
            elif not sender_phone:
                raise contact_store.IdentityConflict('unresolvable-system-identity', ())

    # Lookup or create contact with sender name, BSUID, parent BSUID, and username
    contact = (previous_system_contact or _referral_contact or _idea_contact or _track_shipping_contact or _pickup_contact
               or _submit_request_contact or _request_amendment_contact
               or _get_or_create_contact(sender_phone, sender_name, bsuid=msg_bsuid,
                                         username=sender_username,
                                         contact_book_name=sender_contact_book_name,
                                         parent_bsuid=msg_parent_bsuid,
                                         waba_id=source_waba_id))
    contact_id = contact.get('contactId') or contact.get('id')
    
    # Extract message content based on type.
    # Leave Review is stored as ONE structured Inbox item, not the old truncated raw
    # `[Flow Response: {...}]` transport preview. The FlowSubmission row remains the
    # durable business record; these fields are the Inbox projection of that same row.
    content = _extract_content(message, msg_type)
    _referral_inbox = None
    if _referral_data is not None and _referral_result is not None:
        _referral_form = referral_response.clean_referral(_referral_data)
        _referral_inbox = {
            'flowId': referral_response.FLOW_ID,
            'flowCode': referral_response.FLOW_CODE,
            'flowType': 'referral',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _referral_result.submission_id,
            'flowReference': _referral_result.reference,
            'flowAnswers': referral_response.response_answers(_referral_form),
            'flowAttachments': [],
        }
        msg_type = 'flow_response'
        content = 'Flow response — Referral'

    _idea_inbox = None
    if _idea_data is not None and _idea_result is not None:
        _topic = str(_idea_data.get('topic') or 'other')
        _idea_inbox = {
            'flowCode': customer_ideas.FLOW_CODE,
            'flowType': 'customer_idea',
            'flowScreen': 'REVIEW',
            'flowSubmissionId': _idea_result.submission_id,
            'flowReference': _idea_result.reference,
            'flowAnswers': customer_ideas.response_answers(_idea_data),
            'flowAttachments': [],
            'reviewId': _idea_result.submission_id,
            'reviewStatus': 'pending',
            'reviewCategory': _topic,
        }
        msg_type = 'flow_response'
        content = 'Flow response — Customer Idea'

    _track_shipping_inbox = None
    if _track_shipping_data is not None and _track_shipping_result is not None:
        _track_shipping_item = _track_shipping_result.item or {}
        _track_shipping_inbox = {
            'flowCode': track_shipping_response.FLOW_CODE,
            'flowType': 'form_submit',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _track_shipping_result.submission_id,
            'flowReference': _track_shipping_result.reference,
            'flowAnswers': track_shipping_response.response_answers(
                _track_shipping_data, _track_shipping_result),
            'flowAttachments': [],
            'trackingRequestId': _track_shipping_result.submission_id,
            'trackingRequestStatus': _track_shipping_item.get('status', 'open'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Track Shipping'

    _pickup_inbox = None
    if _pickup_data is not None and _pickup_result is not None:
        _pickup_item = _pickup_result.item or {}
        _pickup_inbox = {
            'flowCode': pickup_request_response.FLOW_CODE,
            'flowType': 'pickup_request',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _pickup_result.submission_id,
            'flowReference': _pickup_result.reference,
            'flowAnswers': pickup_request_response.response_answers(
                _pickup_data, _pickup_result),
            'flowAttachments': [],
            'pickupRequestId': _pickup_result.submission_id,
            'pickupRequestStatus': _pickup_item.get('status', 'pending_confirmation'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Pickup Request'

    _submit_request_inbox = None
    if _submit_request_data is not None and _submit_request_result is not None:
        _submit_request_inbox = {
            'flowCode': submit_request_response.FLOW_CODE,
            'flowType': 'form_submit',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _submit_request_result.submission_id,
            'flowReference': _submit_request_result.reference,
            'flowAnswers': submit_request_response.response_answers(
                _submit_request_data, _submit_request_result),
            'flowAttachments': [],
            'serviceRequestId': _submit_request_result.submission_id,
            'serviceRequestStatus': _submit_request_result.item.get('status', 'open')
                if _submit_request_result.item else 'open',
        }
        msg_type = 'flow_response'
        content = 'Flow response — Submit Request'

    _request_amendment_inbox = None
    if _request_amendment_data is not None and _request_amendment_result is not None:
        _amendment_item = _request_amendment_result.item or {}
        _request_amendment_inbox = {
            'flowCode': request_amendment_response.FLOW_CODE,
            'flowType': 'amendment',
            'flowScreen': 'CONFIRMATION',
            'flowSubmissionId': _request_amendment_result.submission_id,
            'flowReference': _request_amendment_result.reference,
            'flowAnswers': request_amendment_response.response_answers(
                _request_amendment_data, _request_amendment_result),
            'flowAttachments': [],
            # Keep the service context on the original request when ownership verification
            # succeeded; the amendment itself remains addressable via flowSubmissionId.
            'serviceRequestId': (
                _amendment_item.get('parentSubmissionId')
                or _request_amendment_result.submission_id),
            'serviceRequestStatus': _amendment_item.get(
                'status', 'awaiting_order_verification'),
        }
        msg_type = 'flow_response'
        content = 'Flow response — Request Amendment'

    # A shared contact card carried a name and a number that the old extractor threw
    # away, leaving an agent to ask the customer to retype it. Keep the sanitised
    # payload so the inbox can render a real card. Guarded: a malformed vCard must
    # cost the card, never the message. Never log the payload itself — it holds a
    # third party's phone number.
    _contacts_payload = None
    if msg_type == 'contacts' or message.get('contacts'):
        try:
            _contacts_payload = _extract_contacts_payload(message)
        except Exception as _ce:  # noqa: BLE001
            logger.warning(json.dumps({
                'event': 'contacts_payload_extract_failed',
                'error': type(_ce).__name__,
                'whatsappMessageId': whatsapp_message_id,
                'requestId': request_id
            }))
    
    # Generate message ID and the `expiresAt` stamp (not enforced: TTL is disabled)
    message_id = str(uuid.uuid4())
    now = int(time.time())
    expires_at = now + MESSAGE_TTL_SECONDS
    
    # Handle media messages (including stickers)
    # All phones use Direct API
    media_id = None
    s3_key = None
    if msg_type in ['image', 'video', 'audio', 'document', 'sticker']:
        media_data = message.get(msg_type, {})
        whatsapp_media_id = media_data.get('id')
        mime_type_hint = media_data.get('mime_type', '')
        if whatsapp_media_id:
            if _is_direct_api_phone(aws_phone_number_id):
                s3_key = _download_media_direct_api(
                    whatsapp_media_id, message_id, msg_type,
                    phone_number_id=aws_phone_number_id,
                    request_id=request_id,
                    mime_type_hint=mime_type_hint,
                )
            else:
                s3_key = _download_media(whatsapp_media_id, message_id, msg_type, aws_phone_number_id, request_id, mime_type_hint)
            if s3_key:
                media_id = _store_media_record(message_id, s3_key, media_data, whatsapp_media_id)
                # Ordinary Inbox media stays in the conversation. Only an explicit,
                # recent Drop Docs request may bind this media into DocumentTable.
                if msg_type in ('document', 'image'):
                    _attach_whatsapp_document_to_pending_dropdocs(
                        sender_phone, sender_name, contact_id, message_id,
                        whatsapp_media_id, s3_key, msg_type,
                        media_data.get('mime_type', ''),
                        media_data.get('filename', ''),
                        media_data.get('file_size', 0),
                        request_id,
                    )
                # Attach media to the customer's OPEN service request (photos/files
                # sent after the flow are saved under the request's folder + linked).
                try:
                    _link_media_to_service_request(contact_id, s3_key, msg_type,
                                                   media_data.get('filename', ''),
                                                   media_data.get('mime_type', ''), request_id)
                except Exception as _le:
                    logger.warning(json.dumps({'event': 'attach_link_error', 'error': str(_le), 'requestId': request_id}))
    
    # Ephemeral messages may carry media nested inside  -  try to extract
    if msg_type == 'ephemeral' and not s3_key:
        ephemeral_data = message.get('ephemeral', {})
        if isinstance(ephemeral_data, dict):
            for etype in ('image', 'video', 'audio', 'document', 'sticker'):
                edata = ephemeral_data.get(etype, {})
                if isinstance(edata, dict) and edata.get('id'):
                    mime_hint = edata.get('mime_type', '')
                    if _is_direct_api_phone(aws_phone_number_id):
                        s3_key = _download_media_direct_api(
                            edata['id'], message_id, etype,
                            phone_number_id=aws_phone_number_id,
                            request_id=request_id,
                            mime_type_hint=mime_hint,
                        )
                    else:
                        s3_key = _download_media(edata['id'], message_id, etype, aws_phone_number_id, request_id, mime_hint)
                    if s3_key:
                        media_id = _store_media_record(message_id, s3_key, edata, edata['id'])
                    break
    
    # Store message in DynamoDB with WABA info and sender name
    message_record = {
        'id': message_id,
        'messageId': message_id,
        'contactId': contact_id,
        'channel': 'whatsapp',
        'direction': 'inbound',
        'content': content,
        'messageType': msg_type,
        'timestamp': Decimal(str(timestamp)),
        'status': 'received',
        'whatsappMessageId': whatsapp_message_id,
        'mediaId': media_id,
        's3Key': s3_key,
        'senderPhone': sender_phone,
        'senderName': sender_name,  # Sender's WhatsApp profile name
        'senderBsuid': msg_bsuid or None,  # Sender's BSUID (Business-Scoped User ID)
        'senderParentBsuid': msg_parent_bsuid or None,  # Sender's parent BSUID (linked account)
        'senderUsername': sender_username or None,  # Sender's WhatsApp username
        # WABA tracking - which number received this message
        'receivingPhone': receiving_phone,
        'awsPhoneNumberId': aws_phone_number_id,
        'metaWabaIds': meta_waba_ids if meta_waba_ids else None,
        'createdAt': Decimal(str(now)),
        'expiresAt': Decimal(str(expires_at)),
        # None when this is not a contacts message; the put_item below filters
        # None values out, so no attribute is added.
        'contactsPayload': _contacts_payload,
    }
    if _referral_inbox:
        message_record.update(_referral_inbox)
    if _idea_inbox:
        message_record.update(_idea_inbox)
    if _track_shipping_inbox:
        message_record.update(_track_shipping_inbox)
    if _pickup_inbox:
        message_record.update(_pickup_inbox)
    if _submit_request_inbox:
        message_record.update(_submit_request_inbox)
    if _request_amendment_inbox:
        message_record.update(_request_amendment_inbox)
    
    # Keep the complete structured completion; a truncated transport label cannot
    # be reconstructed by the inbox. Both inbox stores must carry the same fields.
    from lambda_utils.flow_inbox import from_message as project_flow_message
    _flow_card = (
        project_flow_message(message)
        if (_referral_data is None and _idea_data is None and _track_shipping_data is None
            and _pickup_data is None and _submit_request_data is None
            and _request_amendment_data is None)
        else {})
    if _flow_card:
        message_record.update(_flow_card)
        content = _flow_card['content']

    # Capture referral context (click-to-WhatsApp ads, product catalogs, social posts)
    # Referral can be attached to ANY message type, not just 'referral' type
    referral = message.get('referral')
    if referral:
        message_record['referralSource'] = referral.get('source_type', '')
        message_record['referralSourceId'] = referral.get('source_id', '')
        message_record['referralSourceUrl'] = referral.get('source_url', '')
        message_record['referralHeadline'] = referral.get('headline', '')
        message_record['referralBody'] = referral.get('body', '')
        # Click-to-WhatsApp Click ID — required by the Conversions API to attribute
        # in-thread conversions (Purchase/Lead) back to the ad. Persist it against the
        # customer's phone so wecare-whatsapp-business-api can log events later.
        ctwa_clid = referral.get('ctwa_clid', '')
        if ctwa_clid:
            message_record['ctwaClid'] = ctwa_clid
            try:
                _digits = ''.join(ch for ch in sender_phone if ch.isdigit())
                _waba = meta_waba_ids[0] if meta_waba_ids else ''
                dynamodb.Table(SYSTEM_CONFIG_TABLE).put_item(Item={
                    'id': 'capi_clid_' + _digits,
                    'configValue': json.dumps({
                        'ctwaClid': ctwa_clid,
                        'phone': _digits,
                        'wabaId': _waba,
                        'sourceType': referral.get('source_type', ''),
                        'sourceId': referral.get('source_id', ''),
                        'headline': referral.get('headline', ''),
                        'ts': int(time.time()),
                    }),
                    'updatedAt': int(time.time()),
                })
            except Exception as _e:
                logger.warning(f'ctwa_clid capture failed (non-blocking): {_e}')
        logger.info(json.dumps({
            'event': 'referral_context',
            'senderPhone': mask_phone(sender_phone),
            'sourceType': referral.get('source_type', ''),
            'sourceUrl': referral.get('source_url', ''),
            'ctwaClid': bool(ctwa_clid),
            'requestId': request_id
        }))
        
        # The referral stays on the message record and the click id in `capi_clid_*` above. The
        # fire-and-forget invoke of `wecare-ad-attribution` that followed went with that function
        # (retired 2026-10-24, 8709d5fdd): every ad click posted the customer's number to a
        # function that no longer existed.
    
    # Capture message context (reply-to, forwarded)
    msg_context = message.get('context')
    if msg_context:
        message_record['replyToMessageId'] = msg_context.get('id', '')
        if msg_context.get('forwarded'):
            message_record['isForwarded'] = True
        if msg_context.get('frequently_forwarded'):
            message_record['isFrequentlyForwarded'] = True
        if msg_context.get('referred_product'):
            message_record['referredProduct'] = msg_context['referred_product']
    
    messages_table = dynamodb.Table(MESSAGES_TABLE)
    messages_table.put_item(Item={k: v for k, v in message_record.items() if v is not None})
    
    # Unified Inbox dual-write — mirror inbound WhatsApp to the canonical MessagesTable
    # (Phase 1). Same messageId as the WhatsApp inbound row, so messages-read dedups by
    # messageId. Guarded inside put_message — can never break inbound processing.
    _partner_waba = next((str(w) for w in (meta_waba_ids or []) if str(w) not in PLATFORM_WABAS), None)
    put_message(
        channel='whatsapp',
        direction='inbound',
        contact_id=contact_id,
        content=content,
        status='received',
        message_id=message_id,
        message_type=_flow_card.get('messageType', msg_type),
        whatsapp_message_id=whatsapp_message_id,
        media_id=media_id,
        s3_key=s3_key,
        sender_phone=sender_phone,
        sender_name=sender_name,
        receiving_phone=receiving_phone,
        aws_phone_number_id=aws_phone_number_id,
        partner_waba_id=_partner_waba,
        contacts_payload=_contacts_payload,
        **{k: v for k, v in _flow_card.items() if k not in ('content', 'messageType')},
        timestamp=timestamp,
        **(_referral_inbox or {}),
        **(_idea_inbox or {}),
        **(_track_shipping_inbox or {}),
        **(_pickup_inbox or {}),
        **(_submit_request_inbox or {}),
        **(_request_amendment_inbox or {}),
    )

    # ── A revoke marks the message it deleted ──
    # Runs AFTER both stores so the revoke's own row exists to be back-linked, and
    # guarded so resolution can never break inbound processing.
    if msg_type == 'revoke':
        try:
            _apply_revoke(message, contact_id, message_id, whatsapp_message_id,
                          sender_phone, timestamp, request_id)
        except Exception as e:
            logger.warning(json.dumps({'event': 'revoke_apply_error',
                                       'error': type(e).__name__, 'requestId': request_id}))

    # call_permission_reply interactive messages are no longer processed.
    # Permission is auto-granted post-call in the whatsapp-calling handler.
    if msg_type == 'interactive':
        interactive = message.get('interactive', {})
        interactive_type = interactive.get('type', '')
        if interactive_type == 'call_permission_reply':
            logger.info(f"Ignoring call_permission_reply from {mask_phone(sender_phone or '')} — permission auto-granted post-call")
            return  # Discard — no longer forwarded or stored
        # Approved template form submissions are processed below.
        elif interactive_type == 'nfm_reply':
            if _referral_data is not None:
                # F008 was durably saved and projected into both inbox stores.
                # Consent to share a number is NOT consent to contact or market to that person.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _idea_data is not None:
                return  # Persisted above; never route a private idea into auto-replies.
            if _track_shipping_data is not None:
                # F006 was persisted above. Keep the customer service window current and
                # stop before the cloned Submit Request/post-payment paths can reinterpret it.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _pickup_data is not None:
                # Dedicated paid Pickup completion has been stored before transport dedup.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _submit_request_data is not None:
                # The completion is already one FlowSubmission + one Inbox card above.
                # It is a customer message, so keep the 24-hour service window current,
                # then stop before generic/post-payment routing can reinterpret it.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            if _request_amendment_data is not None:
                # Same completion contract as Submit Request: durable business row and
                # structured Inbox card were saved above before transport dedup.
                _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
                return
            nfm = interactive.get('nfm_reply', {})
            # Post-payment (endpointless) flow completion: the DETAILS screen's
            # "complete" action returns a payload with reference_id + order details.
            try:
                _raw = nfm.get('response_json', '{}')
                _rj = json.loads(_raw) if isinstance(_raw, str) else (_raw or {})
                if isinstance(_rj, dict) and (_rj.get('reference_id') or _rj.get('request_id')) and (
                    'delivery_note' in _rj or 'preferred_time' in _rj or 'order_number' in _rj
                    or 'description' in _rj or 'request_id' in _rj):
                    _handle_postpay_submission(_rj, contact_id, sender_phone, aws_phone_number_id, request_id)
                    return  # Stop processing — post-payment submission handled
            except Exception as _pp_err:
                logger.warning(json.dumps({'event': 'postpay_nfm_parse_error', 'error': str(_pp_err), 'requestId': request_id}))

    # Handle system status messages with user_changed_user_id
    # Per Meta BSUID docs (system messages webhooks): an identity change arrives as a
    # system MESSAGE, in one of two shapes — there is NO `user_id_update` webhook field:
    #
    #   system.type == 'user_changed_number'   the user changed their phone number, which
    #                                           ALSO regenerates their BSUID. This is the
    #                                           common case and was previously unhandled.
    #   system.type == 'user_changed_user_id'  only the BSUID changed and no phone number
    #                                           can be shared.
    #
    # Both carry the NEW identity in `system.user_id` / `system.parent_user_id` / `system.wa_id`,
    # and the PREVIOUS BSUID in `system.previous_user_id` — the join back to the row we already
    # hold, since a number change mints a new BSUID. We locate the contact by `contact_id`
    # (resolved from the sender) first, then fall back to the previous BSUID on `bsuid-index`.
    if msg_type == 'system':
        system_data = message.get('system', {})
        system_type = system_data.get('type', '')
        if system_type in ('user_changed_number', 'user_changed_user_id'):
            new_bsuid = system_data.get('user_id', '')
            new_parent_bsuid = system_data.get('parent_user_id', '')
            new_wa_id = system_data.get('wa_id', '')
            previous_bsuid = system_data.get('previous_user_id', '')
            logger.info(json.dumps({
                'event': 'system_identity_change',
                'systemType': system_type,
                'senderPhone': mask_phone(sender_phone),
                'newBsuid': new_bsuid,
                'newParentBsuid': new_parent_bsuid,
                'hasPreviousBsuid': bool(previous_bsuid),
                # The new number masked, and the system text (which quotes both numbers) only
                # by presence. The full values are stored on the system event below.
                'newWaId': mask_phone(new_wa_id),
                'hasSystemBody': bool(system_data.get('body')),
                'requestId': request_id
            }))
            # Resolve the row to update. Prefer the contact already resolved for this
            # message; if that is missing (a number change regenerates the BSUID, so the
            # per-message resolve by new phone/BSUID may have found nothing), fall back to
            # the PREVIOUS BSUID, which is the identity we had on file before the change.
            target_id = contact_id
            if not target_id and previous_bsuid:
                try:
                    prior = _find_scoped_bsuid(
                        dynamodb.Table(CONTACTS_TABLE), previous_bsuid,
                        source_waba_id, sender_phone=sender_phone)
                    target_id = contact_key.resolve(prior) if prior else ''
                except Exception as find_err:
                    logger.warning(f'previous-BSUID contact lookup failed: {type(find_err).__name__}')
                    target_id = ''
            # Only the signed sender's exact business portfolio may change its
            # Meta identity. Previous ID is proof of continuity; a new phone is
            # NEVER permission to replace a different claimed routing number.
            if new_bsuid and target_id:
                try:
                    ct = dynamodb.Table(CONTACTS_TABLE)
                    current = ct.get_item(Key={'id': target_id}, ConsistentRead=True).get('Item')
                    if not current or not contact_store.is_live(current):
                        raise contact_store.IdentityConflict('system-contact-not-live', (target_id,))
                    new_owner = _find_scoped_bsuid(
                        ct, new_bsuid, source_waba_id,
                        sender_phone=(new_wa_id or sender_phone))
                    if new_owner and contact_key.resolve(new_owner) != target_id:
                        raise contact_store.IdentityConflict(
                            'system-bsuid-already-owned', (target_id,))
                    new_phone = contact_store.canonical_phone(new_wa_id)
                    current_phone = contact_store.canonical_phone(current.get('phone'))
                    if new_phone and current_phone and new_phone != current_phone:
                        logger.warning(json.dumps({
                            'event': 'system_phone_change_requires_review',
                            'contactId': mask_contact_id(target_id),
                        }))
                        raise contact_store.IdentityConflict('system-phone-change', (target_id,))

                    # Install the previous claim on old rows before rotating. A
                    # partially completed transition can be retried idempotently.
                    portfolio_id = _portfolio_scope(source_waba_id)
                    old_profile = ((current.get('whatsappIdentities') or {})
                                   .get(portfolio_id) or {})
                    profile_bsuid = str(old_profile.get('bsuid') or '')
                    if previous_bsuid and not profile_bsuid:
                        _attach_scoped_bsuid(
                            ct, current, waba_id=source_waba_id,
                            bsuid=previous_bsuid)
                        profile_bsuid = previous_bsuid
                    if profile_bsuid != new_bsuid:
                        _attach_scoped_bsuid(
                            ct, current, waba_id=source_waba_id,
                            bsuid=new_bsuid, parent_bsuid=new_parent_bsuid,
                            previous_bsuid=previous_bsuid)
                    if source_waba_id == '2094615664435155':
                        # Legacy single-account readers still use bsuid. Change it
                        # only when it equals Meta's previous ID, never a foreign ID.
                        try:
                            ct.update_item(
                                Key={'id': target_id},
                                UpdateExpression='SET bsuid = :new',
                                ConditionExpression=('attribute_exists(id) AND '
                                                     '(attribute_not_exists(bsuid) OR bsuid = :old OR bsuid = :new)'),
                                ExpressionAttributeValues={
                                    ':old': previous_bsuid, ':new': new_bsuid},
                            )
                        except ClientError as exc:
                            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                                raise contact_store.IdentityConflict(
                                    'legacy-business-identity-change', (target_id,)) from exc
                            raise
                    if new_phone and not current_phone:
                        _update_contact_bsuid_fields(
                            ct, current, '', '', phone=new_phone,
                            waba_id=source_waba_id)
                except contact_store.IdentityConflict:
                    raise
                except Exception as exc:
                    logger.warning(json.dumps({
                        'event': 'system_identity_store_unavailable',
                        'errorType': type(exc).__name__,
                        'contactId': mask_contact_id(target_id),
                    }))
                    raise contact_store.IdentityConflict('system-identity-store-unavailable', ()) from exc
            _store_system_event(system_type, {
                'senderPhone': sender_phone,
                'contactId': target_id,
                'newBsuid': new_bsuid,
                'newParentBsuid': new_parent_bsuid,
                'previousBsuid': previous_bsuid,
                'newWaId': new_wa_id,
                'body': system_data.get('body', ''),
            }, request_id)
    
    # Meta puts `origin` on each contact card, not on the enclosing message.
    # Only contact_request represents the sender sharing THEIR OWN phone; an
    # ordinary shared vCard may describe a third party and must never rewrite
    # the sender's primary identity.
    if msg_type == 'contacts':
        for shared_card in message.get('contacts', []) or []:
            if not isinstance(shared_card, dict) or shared_card.get('origin') != 'contact_request':
                continue
            phones = shared_card.get('phones') or []
            if len(phones) != 1 or not isinstance(phones[0], dict):
                continue
            shared_phone = contact_store.canonical_phone(
                phones[0].get('phone') or phones[0].get('wa_id') or '')
            if shared_phone and contact_id:
                _update_contact_bsuid_fields(
                    dynamodb.Table(CONTACTS_TABLE), contact,
                    sender_name='', username='', phone=shared_phone,
                    waba_id=source_waba_id)
                if contact_store.canonical_phone(contact.get('phone')) == shared_phone:
                    logger.info(json.dumps({
                        'event': 'contact_request_phone_linked',
                        'contactId': mask_contact_id(contact_id),
                        'sharedPhone': mask_phone(shared_phone),
                        'requestId': request_id,
                    }))

    # Update Contact.lastInboundMessageAt for 24-hour window (+ WAMID for typing)
    _update_contact_timestamp(contact_id, now, wamid=whatsapp_message_id or '')
    
    logger.info(json.dumps({
        'event': 'message_stored',
        'messageId': message_id,
        'contactId': mask_contact_id(contact_id),
        'senderPhone': mask_phone(sender_phone),
        # A WhatsApp profile name is the customer's own name. contactId already
        # identifies them for correlation, so only its presence is logged.
        'hasSenderName': bool(sender_name),
        'whatsappMessageId': whatsapp_message_id,
        'type': msg_type,
        'hasMedia': bool(media_id),
        'receivingPhone': mask_phone(receiving_phone),
        'awsPhoneNumberId': aws_phone_number_id,
        'requestId': request_id
    }))
    
    # Mark the message read. A read receipt is not a message to the customer; no reaction,
    # typing indicator, reply or other message is sent automatically.
    if msg_type != 'reaction' and msg_type != 'unsupported':
        global _current_direct_api_phone
        _current_direct_api_phone = _get_meta_phone_id_for_direct_api(aws_phone_number_id)
        if _is_direct_api_phone(aws_phone_number_id):
            try:
                _rr = _send_direct_api_read_receipt(whatsapp_message_id, show_typing=False)
                if _rr.get('error'):
                    logger.warning(json.dumps({
                        'event': 'read_receipt_failed',
                        'whatsappMessageId': whatsapp_message_id,
                        'messageType': msg_type,
                        'status': _rr.get('status'),
                        'graphError': _graph_error_code(_rr.get('detail')),
                        'requestId': request_id
                    }))
            except Exception as e:
                logger.warning(f"Direct API read receipt failed: {type(e).__name__}")
        else:
            _send_read_receipt(
                whatsapp_message_id=whatsapp_message_id,
                phone_number_id=aws_phone_number_id,
                request_id=request_id
            )

    # Auto-transcribe voice notes (audio messages) for English transcription display
    if msg_type == 'audio' and s3_key:
        _auto_transcribe_voice_note(message_id, s3_key, request_id)

    # No automatic reply is sent to any inbound message. Staff reply from the inbox.


def _extract_content(message: Dict, msg_type: str) -> str:
    """Extract message content based on type. Delegates to modules.content."""
    return _extract_content_v2(message, msg_type)


def _message_exists(whatsapp_message_id: str) -> bool:
    """Check if message already exists (deduplication) using GSI query."""
    if not whatsapp_message_id:
        return False
    try:
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        response = messages_table.query(
            IndexName='whatsappMessageId-index',
            KeyConditionExpression='whatsappMessageId = :wmid',
            ExpressionAttributeValues={':wmid': whatsapp_message_id},
            Limit=1
        )
        return len(response.get('Items', [])) > 0
    except Exception as e:
        # Fallback to scan if GSI not ready yet
        logger.warning(f"GSI query failed, falling back to scan: {str(e)}")
        try:
            response = messages_table.scan(
                FilterExpression='whatsappMessageId = :wmid',
                ExpressionAttributeValues={':wmid': whatsapp_message_id},
                Limit=1
            )
            return len(response.get('Items', [])) > 0
        except Exception:
            return False


def _deterministic_contact_id(phone: str) -> str:
    """Stable, phone-derived contact id so ONE phone always maps to ONE contact
    (eliminates churn/duplicates from GSI eventual-consistency). Digits only."""
    digits = normalize_phone(phone) if phone else ''
    if not digits:
        digits = ''.join(c for c in (phone or '') if c.isdigit())
    return f'wa{digits}' if digits else ''


# Two verified Meta business portfolios. A BSUID is only an identity WITHIN its
# portfolio: the same customer phone can legitimately carry two different BSUIDs.
# Never use the old unscoped bsuid-index as a global person identifier.
_WABA_PORTFOLIOS = {
    '2094615664435155': '382642103987922',  # WECARE.DIGITAL
    '2513394156072604': '125951953587391',  # Manish Agarwal
}


def _portfolio_scope(waba_id: str) -> str:
    """Known businesses share a portfolio; other signed partner IDs are WABA-isolated.

    A partner WABA must not inherit an unrelated business identity. For unknown
    accounts the stricter one-WABA scope prevents collisions while preserving
    phone-hidden inbound traffic; cross-WABA continuity needs verified portfolio
    metadata and is not silently inferred.
    """
    value = str(waba_id or '').strip()
    known = _WABA_PORTFOLIOS.get(value)
    if known:
        return known
    if 15 <= len(value) <= 20 and all(c in '0123456789' for c in value):
        return 'WABA_' + value
    raise contact_store.IdentityConflict('invalid-business-identity', ())


def _message_account_id(metadata: Dict, meta_waba_ids: list, *, needs_bsuid: bool) -> str:
    """Use the known sender number and the webhook account together, never a default."""
    phone_id = str((metadata or {}).get('phone_number_id') or '').strip()
    mapped = direct_send.waba_for_meta_phone(phone_id)
    declared = {str(v) for v in (meta_waba_ids or []) if v}
    if mapped and (not declared or mapped in declared):
        return mapped
    if not mapped and len(declared) == 1:
        only = next(iter(declared))
        # Other signed Embedded-Signup partner accounts must still receive
        # messages. Give them a unique WABA-local scope, not either portfolio.
        _portfolio_scope(only)
        return only
    if needs_bsuid:
        raise contact_store.IdentityConflict('unknown-business-identity-scope', ())
    return ''


def _scoped_bsuid_key(waba_id: str, bsuid: str) -> str:
    portfolio_id = _portfolio_scope(waba_id)
    value = str(bsuid or '').strip()
    if not value or len(value) > 128:
        raise contact_store.IdentityConflict('invalid-business-identity', ())
    return f'WHATSAPP_BSUID#{portfolio_id}#{value}'


def _find_scoped_bsuid(contacts_table, bsuid: str, waba_id: str,
                       *, sender_phone: str = '') -> Optional[Dict]:
    """Read exact (business portfolio,BSUID) owner. Legacy match needs phone evidence."""
    if not bsuid:
        return None
    scoped_key = _scoped_bsuid_key(waba_id, bsuid)
    try:
        item = dynamodb.Table(identity_claims.TABLE_NAME).get_item(
            Key={'claimKey': scoped_key}, ConsistentRead=True).get('Item') or {}
    except Exception as exc:
        raise contact_store.IdentityConflict('business-identity-lookup-unavailable', ()) from exc
    owner_id = str(item.get('contactId') or '')
    if owner_id:
        owner = contact_store.lookup(contacts_table, contact_id=owner_id)
        if owner is None:
            raise contact_store.IdentityConflict('orphan-business-identity-claim', (owner_id,))
        return owner

    # A legacy unscoped identity is not proof of portfolio membership. Only a
    # matching verified sender phone can reconnect it; otherwise quarantine for
    # explicit reconciliation rather than minting a duplicate or guessing WABA.
    legacy = contact_store.find_by_bsuid(contacts_table, bsuid)
    if legacy:
        legacy_phone = contact_store.canonical_phone(legacy.get('phone'))
        new_phone = contact_store.canonical_phone(sender_phone)
        if legacy_phone and new_phone and legacy_phone == new_phone:
            return legacy
        raise contact_store.IdentityConflict('unscoped-bsuid-reconciliation', ())
    return None


def _attach_scoped_bsuid(contacts_table, contact: Dict, *, waba_id: str,
                         bsuid: str, username: str = '', parent_bsuid: str = '',
                         contact_book_name: str = '',
                         previous_bsuid: str = '') -> None:
    """Idempotently claim one Meta identity and record it under its business.

    Deliberately refuses cross-contact claims and unexplained changes. Separate
    DynamoDB writes may leave a claim awaiting profile projection; the next
    webhook can repair it without granting access to a different contact.
    """
    if not bsuid:
        return
    scoped_key = _scoped_bsuid_key(waba_id, bsuid)
    portfolio_id = _portfolio_scope(waba_id)
    contact_id = contact_key.resolve(contact)
    if not contact_id:
        raise contact_store.IdentityConflict('missing-canonical-contact', ())
    current_profiles = contact.get('whatsappIdentities') or {}
    if not isinstance(current_profiles, dict):
        raise contact_store.IdentityConflict('invalid-portfolio-identity-map', ())
    prior_profile = current_profiles.get(portfolio_id) or {}
    if not isinstance(prior_profile, dict):
        raise contact_store.IdentityConflict('invalid-portfolio-identity-profile', ())
    old_bsuid = str(prior_profile.get('bsuid') or '')
    legacy_bsuid = str(contact.get('bsuid') or '')
    if waba_id == '2094615664435155' and legacy_bsuid and legacy_bsuid != bsuid:
        if not previous_bsuid or previous_bsuid != legacy_bsuid:
            raise contact_store.IdentityConflict('legacy-wecare-bsuid-mismatch', ())
    if old_bsuid and old_bsuid != bsuid:
        if not previous_bsuid or old_bsuid != previous_bsuid:
            raise contact_store.IdentityConflict('business-identity-change-needs-review', ())
    elif previous_bsuid and old_bsuid and old_bsuid != previous_bsuid:
        raise contact_store.IdentityConflict('business-identity-transition-race', ())

    table = dynamodb.Table(identity_claims.TABLE_NAME)
    try:
        claim = table.get_item(Key={'claimKey': scoped_key}, ConsistentRead=True).get('Item') or {}
    except Exception as exc:
        raise contact_store.IdentityConflict('business-identity-claim-unavailable', ()) from exc
    claimant = str(claim.get('contactId') or '')
    if claimant and claimant != contact_id:
        raise contact_store.IdentityConflict('business-identity-already-claimed', ())
    now = int(time.time())
    if not claimant:
        try:
            table.update_item(
                Key={'claimKey': scoped_key},
                UpdateExpression=('SET contactId=:cid, identityType=:kind, updatedAt=:now, '
                                  'claimedAt=if_not_exists(claimedAt,:now)'),
                ConditionExpression='attribute_not_exists(claimKey) OR contactId=:cid',
                ExpressionAttributeValues={
                    ':cid': contact_id, ':kind': 'WHATSAPP_BSUID', ':now': now,
                },
            )
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                raise contact_store.IdentityConflict('business-identity-race', ()) from exc
            raise contact_store.IdentityConflict('business-identity-write-unavailable', ()) from exc
        except Exception as exc:
            raise contact_store.IdentityConflict('business-identity-write-unavailable', ()) from exc

    profile = dict(prior_profile)
    profile['bsuid'] = bsuid
    for field, value in (('username', username), ('parentBsuid', parent_bsuid),
                         ('contactBookName', contact_book_name)):
        if value:
            profile[field] = str(value)
    if profile == prior_profile:
        return
    # Nested DynamoDB map attributes require the parent to exist before a
    # separately conditional leaf write. Neither step replaces another business.
    try:
        contacts_table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET #profiles = if_not_exists(#profiles, :empty)',
            ExpressionAttributeNames={'#profiles': 'whatsappIdentities'},
            ExpressionAttributeValues={':empty': {}},
            ConditionExpression='attribute_exists(id)',
        )
    except Exception as exc:
        raise contact_store.IdentityConflict('business-profile-map-unavailable', ()) from exc
    names = {'#profiles': 'whatsappIdentities', '#business': portfolio_id,
             '#bsuid': 'bsuid'}
    values = {':entry': profile, ':bsuid': bsuid, ':now': Decimal(str(now))}
    if previous_bsuid:
        condition = '#profiles.#business.#bsuid = :previous'
        values[':previous'] = previous_bsuid
    else:
        condition = ('attribute_not_exists(#profiles.#business) '
                     'OR #profiles.#business.#bsuid = :bsuid')
    try:
        contacts_table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET #profiles.#business = :entry, updatedAt = :now',
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            raise contact_store.IdentityConflict('business-identity-write-conflict', ()) from exc
        raise contact_store.IdentityConflict('business-identity-write-unavailable', ()) from exc
    except Exception as exc:
        raise contact_store.IdentityConflict('business-identity-write-unavailable', ()) from exc
    contact['whatsappIdentities'] = {**current_profiles, portfolio_id: profile}


def _get_or_create_contact(phone: str, sender_name: str = '', bsuid: str = '', username: str = '', contact_book_name: str = '', parent_bsuid: str = '', waba_id: str = '') -> Dict[str, Any]:
    """Get existing contact or create new one. Supports BSUID and parent BSUID lookup and storage.
    Uses a deterministic phone-derived id + strongly-consistent get_item so repeated
    inbound/outbound events never create duplicate (churned) contacts."""
    contacts_table = dynamodb.Table(CONTACTS_TABLE)

    # Resolve only the exact portfolio's BSUID claim before any phone lookup.
    if bsuid:
        if not waba_id:
            if not phone:
                raise contact_store.IdentityConflict('unscoped-phone-hidden-contact', ())
            # A signed phone can still resolve canonically; do not attach an
            # unscoped Meta user ID to a cross-business customer.
            bsuid = ''
        else:
            matched_bsuid = _find_scoped_bsuid(
                contacts_table, bsuid, waba_id, sender_phone=phone)
            if matched_bsuid:
                _update_contact_bsuid_fields(
                    contacts_table, matched_bsuid, sender_name, username, phone,
                    bsuid, contact_book_name, parent_bsuid, waba_id=waba_id)
                return matched_bsuid

    # 1) Strongly-consistent lookup by deterministic phone id (no GSI lag / no churn)
    det_id = _deterministic_contact_id(phone)
    if det_id:
        try:
            r = contacts_table.get_item(Key={'id': det_id}, ConsistentRead=True)
            existing = r.get('Item')
            if existing and not existing.get('deletedAt'):
                _update_contact_bsuid_fields(contacts_table, existing, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid, waba_id=waba_id)
                return existing
        except Exception as e:
            # `det_id` is `wa` + the customer's digits, so it is masked like any contact id.
            logger.warning(f"deterministic contact get failed for {mask_contact_id(det_id)}: "
                           f"{type(e).__name__}")

    # Canonical resolver follows merge aliases and refuses duplicate LIVE phone owners.
    # On conflict the caller parks the webhook for reconciliation; never route a
    # customer's inbound message to the oldest of two competing identity claims.
    try:
        resolved = contact_store.lookup(contacts_table, phone)
    except contact_store.IdentityConflict:
        logger.warning(json.dumps({
            'event': 'contact_identity_conflict',
            'phone': mask_phone(phone),
            'hasBsuid': bool(bsuid),
        }))
        raise
    except Exception as e:
        logger.warning(f"contact_store.lookup failed for {mask_phone(phone)}: {type(e).__name__}")
        raise contact_store.IdentityConflict('contact-lookup-unavailable', ()) from e
    if resolved and not resolved.get('deletedAt'):
        _update_contact_bsuid_fields(contacts_table, resolved, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid, waba_id=waba_id)
        return resolved

    # Clean phone for search - normalize to digits-only E.164
    clean_phone = normalize_phone(phone) if phone else ''
    if not clean_phone:
        clean_phone = phone.lstrip('+') if phone else ''
    phone_with_plus = f'+{clean_phone}' if clean_phone else ''
    
    # Use GSI query on phone-index for O(1) lookup (try both formats)
    items = []
    if clean_phone:
        for phone_variant in [phone_with_plus, clean_phone]:
            try:
                response = contacts_table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :phone',
                    ExpressionAttributeValues={':phone': phone_variant},
                    Limit=10
                )
                variant_items = response.get('Items', [])
                # Filter out deleted contacts
                variant_items = [i for i in variant_items if not i.get('deletedAt')]
                items.extend(variant_items)
            except Exception as e:
                logger.warning(f"GSI phone-index query failed for {mask_phone(phone_variant)}: "
                               f"{type(e).__name__}")
    
    # Fallback to scan if GSI not ready
    if not items and clean_phone:
        try:
            response = contacts_table.scan(
                FilterExpression='(phone = :phone1 OR phone = :phone2) AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
                ExpressionAttributeValues={
                    ':phone1': clean_phone,
                    ':phone2': phone_with_plus,
                    ':null': None
                },
                Limit=100
            )
            items = response.get('Items', [])
        except Exception:
            items = []
    
    if items:
        # Deduplicate by id in case both phone formats matched the same contact
        seen_ids = set()
        unique_items = []
        for item in items:
            item_id = item.get('id', '')
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                unique_items.append(item)
        items = unique_items
        
        # Legacy GSI/scan fallback must also fail closed: selecting the oldest
        # of two live phone owners can attach payments or messages to a stranger.
        if len(items) > 1:
            raise contact_store.IdentityConflict('phone',
                                                 (i.get('id', '') for i in items))
        contact = items[0]
        # Update name/BSUID/username if available
        _update_contact_bsuid_fields(contacts_table, contact, sender_name, username, phone, bsuid, contact_book_name, parent_bsuid, waba_id=waba_id)
        return contact
    
    # Create new contact with a DETERMINISTIC phone-derived id (idempotent).
    # Prefer a deterministic id so concurrent webhooks never mint two rows for one person:
    #   1. phone-derived `wa{digits}` when we have a phone (the established convention);
    #   2. BSUID-derived `wab{sanitized}` when the sender is phone-absent (a username
    #      adopter) but carries a BSUID — otherwise two webhooks arriving before the
    #      bsuid-index GSI is consistent would each fall through to a random UUID and
    #      create duplicate rows for the same BSUID;
    #   3. a random UUID only when we have neither identifier.
    # The BSUID-derived id (`wab{sanitized}`) is minted by `contact_store`, next to the
    # phone-derived `wa{digits}` rule, so both id conventions live in one place.
    # Portfolio-scoped deterministic ID prevents two businesses sharing the same
    # opaque Meta user ID from minting the same provisional customer.
    portfolio = _portfolio_scope(waba_id) if bsuid else ''
    scoped_identity = f'{portfolio}.{bsuid}' if portfolio and bsuid else ''
    bsuid_det_id = contact_store.deterministic_bsuid_id(scoped_identity)
    contact_id = det_id or bsuid_det_id
    if not contact_id:
        # A sender without a phone AND scoped BSUID has no stable ownership.
        # Quarantine rather than creating an unresolvable anonymous customer.
        raise contact_store.IdentityConflict('sender-identity-missing', ())
    now = int(time.time())

    # Ensure phone has + prefix for international format (easier for SMS)
    formatted_phone = ''
    if phone:
        formatted_phone = phone if phone.startswith('+') else f'+{phone}'

    contact = {
        **contact_key.contact_item_keys(contact_id),
        **subscriber_id.new_contact_fields(now=now),
        'name': sender_name or '',
        'phone': formatted_phone or None,
        'email': None,
        # The old unscoped fields stay populated only by the existing WECARE
        # portfolio; a Manish identity must NEVER replace those values.
        'bsuid': (bsuid if waba_id == '2094615664435155' else None),
        'parentBsuid': (parent_bsuid if waba_id == '2094615664435155' else None),
        'username': (username if waba_id == '2094615664435155' else None),
        'contactBookName': (contact_book_name if waba_id == '2094615664435155' else None),
        'optInWhatsApp': False,
        'optInSms': False,
        'optInEmail': False,
        'allowlistWhatsApp': False,
        'allowlistSms': False,
        'allowlistEmail': False,
        'lastInboundMessageAt': Decimal(str(now)),
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
    }

    claims_table = dynamodb.Table(identity_claims.TABLE_NAME)
    try:
        identity_claims.claim_identities(
            claims_table, contact_id=contact_id, phone=formatted_phone, now=now)
    except identity_claims.IdentityClaimConflict:
        owner_id = identity_claims.owner(claims_table, 'PHONE', formatted_phone)
        if owner_id:
            owner = contacts_table.get_item(
                Key={'id': owner_id}, ConsistentRead=True).get('Item')
            if owner and contact_store.is_live(owner):
                _update_contact_bsuid_fields(
                    contacts_table, owner, sender_name, username, phone, bsuid,
                    contact_book_name, parent_bsuid, waba_id=waba_id)
                return owner
        raise

    try:
        contacts_table.put_item(
            Item={k: v for k, v in contact.items() if v is not None},
            ConditionExpression='attribute_not_exists(id)',
        )
        if waba_id and bsuid:
            _attach_scoped_bsuid(
                contacts_table, contact, waba_id=waba_id, bsuid=bsuid,
                username=username, parent_bsuid=parent_bsuid,
                contact_book_name=contact_book_name)
        logger.info(json.dumps({
            'event': 'contact_auto_created', 'contactId': mask_contact_id(contact_id),
            'phone': mask_phone(phone), 'hasName': bool(sender_name), 'hasBsuid': bool(bsuid), 'hasUsername': bool(username),
        }))
        return contact
    except Exception as e:
        # A conditional collision can be a concurrent successful creator; re-read
        # and attach to THAT row. Other write failures must not return a phantom
        # customer ID which would orphan messages and payment history.
        if isinstance(e, ClientError) and e.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            current = contacts_table.get_item(
                Key={'id': contact_id}, ConsistentRead=True).get('Item')
            if current and contact_store.is_live(current):
                _update_contact_bsuid_fields(
                    contacts_table, current, sender_name, username, phone, bsuid,
                    contact_book_name, parent_bsuid, waba_id=waba_id)
                return current
        logger.warning(json.dumps({
            'event': 'contact_create_failed', 'errorType': type(e).__name__,
            'contactId': mask_contact_id(contact_id),
        }))
        raise contact_store.IdentityConflict('contact-create-failed', ()) from e


def _update_contact_bsuid_fields(contacts_table, contact: Dict, sender_name: str, username: str, phone: str = '', bsuid: str = '', contact_book_name: str = '', parent_bsuid: str = '', waba_id: str = '') -> None:
    """Update canonical contact plus exact-portfolio WhatsApp identity, if signed."""
    if bsuid and waba_id:
        _attach_scoped_bsuid(
            contacts_table, contact, waba_id=waba_id, bsuid=bsuid,
            username=username, parent_bsuid=parent_bsuid,
            contact_book_name=contact_book_name)
    # Old single identity fields belong to the existing WECARE business only.
    # WABA2 data is exclusively in whatsappIdentities, never copied globally.
    if waba_id != '2094615664435155':
        bsuid = ''
        username = ''
        parent_bsuid = ''
        contact_book_name = ''
    updates = {}
    names = {}
    values = {}
    idx = 0
    
    current_name = contact.get('name', '')
    if sender_name and (not current_name or current_name in ['', '~', 'Unknown']):
        updates[f'#n{idx}'] = 'name'
        names[f'#n{idx}'] = 'name'
        values[f':v{idx}'] = sender_name
        contact['name'] = sender_name
        idx += 1
    
    if bsuid and not contact.get('bsuid'):
        names[f'#n{idx}'] = 'bsuid'
        values[f':v{idx}'] = bsuid
        contact['bsuid'] = bsuid
        idx += 1
    
    # Store parent BSUID if provided and different from current
    if parent_bsuid and contact.get('parentBsuid') != parent_bsuid:
        names[f'#n{idx}'] = 'parentBsuid'
        values[f':v{idx}'] = parent_bsuid
        contact['parentBsuid'] = parent_bsuid
        idx += 1
    
    if username and contact.get('username') != username:
        names[f'#n{idx}'] = 'username'
        values[f':v{idx}'] = username
        contact['username'] = username
        idx += 1
    
    # A phone arriving after a BSUID-only contact must claim its strong identity
    # BEFORE updating ContactsTable. Refuse ambiguous/claimed numbers rather than
    # silently linking this WhatsApp ID to another customer's phone.
    pending_phone = ''
    phone_param = ''
    if phone and contact.get('phone') and (
        contact_store.canonical_phone(phone) != contact_store.canonical_phone(contact.get('phone'))
    ):
        # A new phone for the same BSUID can mean a number change or a recycled
        # number. Never silently redirect a confirmed customer's messages.
        logger.warning(json.dumps({'event': 'inbound_phone_change_requires_review',
                                   'contactId': mask_contact_id(contact.get('id', ''))}))
    if phone and not contact.get('phone'):
        formatted = contact_store.canonical_phone(phone)
        if formatted:
            try:
                prior = contact_store.find_by_phone(contacts_table, formatted)
                if prior and contact_key.resolve(prior) != contact_key.resolve(contact):
                    raise contact_store.IdentityConflict('phone',
                                                         (contact_key.resolve(prior),
                                                          contact_key.resolve(contact)))
                identity_claims.claim_identities(
                    dynamodb.Table(identity_claims.TABLE_NAME),
                    contact_id=contact_key.resolve(contact), phone=formatted)
            except (identity_claims.IdentityClaimConflict, contact_store.IdentityConflict):
                logger.warning(json.dumps({'event': 'inbound_phone_link_refused',
                                           'contactId': mask_contact_id(contact.get('id', ''))}))
            except Exception as phone_link_error:
                # An unavailable identity registry must not lose a valid inbound
                # message; skip ONLY the optional phone link and store the thread.
                logger.warning(json.dumps({'event': 'inbound_phone_link_unavailable',
                                           'contactId': mask_contact_id(contact.get('id', '')),
                                           'errorType': type(phone_link_error).__name__}))
            else:
                names[f'#n{idx}'] = 'phone'
                phone_param = f':v{idx}'
                values[phone_param] = formatted
                pending_phone = formatted
                idx += 1

    # Update contactBookName if provided and different
    if contact_book_name and contact.get('contactBookName') != contact_book_name:
        names[f'#n{idx}'] = 'contactBookName'
        values[f':v{idx}'] = contact_book_name
        contact['contactBookName'] = contact_book_name
        idx += 1
    
    if not names:
        return
    
    values[':now'] = Decimal(str(int(time.time())))
    if pending_phone:
        values[':empty_phone'] = ''
        values[':pending_phone'] = pending_phone
    names['#updatedAt'] = 'updatedAt'
    set_parts = [f'{k} = :v{i}' for i, k in enumerate(names.keys()) if k != '#updatedAt']
    set_parts.append('#updatedAt = :now')
    
    try:
        contacts_table.update_item(
            Key={'id': contact.get('id')},
            UpdateExpression='SET ' + ', '.join(set_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            # A concurrent phone change must not be overwritten by this webhook.
            ConditionExpression=('attribute_exists(id) AND '
                                 '(attribute_not_exists(phone) OR phone = :empty_phone OR '
                                 'phone = :pending_phone)') if pending_phone else 'attribute_exists(id)',
        )
        if pending_phone:
            contact['phone'] = pending_phone
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'contact_bsuid_update_failed',
            'contactId': mask_contact_id(contact.get('id', '')),
            'error': str(e),
        }))


def _process_business_username_update(value: Dict, request_id: str) -> None:
    """Handle business_username_updates webhook — our business username status changed.

    Payload (per Meta BSUID doc): { display_phone_number, username, status }
    status: approved | reserved | deleted. Stores a SystemEvent and logs the
    status so the username claim lifecycle is observable end-to-end.
    """
    display_phone = value.get('display_phone_number', '')
    username = value.get('username', '')
    status = (value.get('status') or '').lower()

    # Audit trail (kept for the dashboard).
    _store_system_event('business_username_updates', value, request_id)

    logger.info(json.dumps({
        'event': 'business_username_update',
        'displayPhoneNumber': display_phone[:6] + '***' if display_phone else '',
        'username': username,
        'status': status,
        'requestId': request_id,
    }))

    # Best-effort: reflect the live username/status onto the FlowRegistry-adjacent
    # phone config if a WhatsAppPhone record exists (non-fatal if table absent).
    try:
        if status in ('approved', 'reserved', 'deleted') and display_phone:
            phones_table = dynamodb.Table(os.environ.get('WHATSAPP_PHONES_TABLE', 'stack-wecare-digital-WhatsAppPhonesTable'))
            phones_table.update_item(
                Key={'displayPhoneNumber': display_phone},
                UpdateExpression='SET businessUsername = :u, businessUsernameStatus = :s, updatedAt = :now',
                ExpressionAttributeValues={
                    ':u': '' if status == 'deleted' else username,
                    ':s': status,
                    ':now': Decimal(str(int(time.time()))),
                },
            )
    except Exception as e:
        # Table/record may not exist — the SystemEvent above is the source of truth.
        logger.info(json.dumps({
            'event': 'business_username_phone_update_skipped',
            'reason': str(e)[:160],
            'requestId': request_id,
        }))


def _update_contact_timestamp(contact_id: str, timestamp: int, wamid: str = '') -> None:
    """Update contact's lastInboundMessageAt for 24-hour window tracking.
    Also stores the latest inbound WAMID so outbound can show a typing indicator
    (Meta's typing_indicator API requires the customer's last received message_id)."""
    try:
        contacts_table = dynamodb.Table(CONTACTS_TABLE)
        # Conditional on the row already existing: an unconditional update_item would UPSERT a
        # stub contact (id + timestamps, no phone/opt-in fields) for any id that no longer exists,
        # e.g. after a merge. A missing row means there is nothing to touch, so we let the
        # condition fail and swallow it rather than minting a ghost.
        if wamid:
            contacts_table.update_item(
                Key={'id': contact_id},
                UpdateExpression='SET lastInboundMessageAt = :ts, updatedAt = :ts, lastInboundWamid = :w',
                ExpressionAttributeValues={':ts': Decimal(str(timestamp)), ':w': wamid},
                ConditionExpression='attribute_exists(id)',
            )
        else:
            contacts_table.update_item(
                Key={'id': contact_id},
                UpdateExpression='SET lastInboundMessageAt = :ts, updatedAt = :ts',
                ExpressionAttributeValues={':ts': Decimal(str(timestamp))},
                ConditionExpression='attribute_exists(id)',
            )
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            # No such contact row (merged/deleted). Nothing to update; not an error.
            return
        logger.error(f"Failed to update contact timestamp: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to update contact timestamp: {str(e)}")


def _download_media_direct_api(whatsapp_media_id: str, message_id: str, media_type: str,
                               phone_number_id: str, request_id: str,
                               mime_type_hint: str = '') -> Optional[str]:
    """Download media via Meta Graph API for Direct API phones."""
    token = _load_direct_api_token()
    if not token:
        logger.error("No Direct API token for media download")
        return None
    app_secret = _direct_api_token_cache.get('app_secret', '')
    
    try:
        # Step 1: Get media URL from Meta
        url = f"https://graph.facebook.com/{META_API_VERSION}/{whatsapp_media_id}"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            url = f"{url}?appsecret_proof={proof}"
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            media_info = json.loads(resp.read().decode())
        
        media_url = media_info.get('url', '')
        mime_type = media_info.get('mime_type', mime_type_hint)
        if not media_url:
            logger.error(f"No media URL returned for {whatsapp_media_id}")
            return None
        
        # Step 2: Download the actual media file
        req2 = urllib.request.Request(media_url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            media_bytes = resp2.read()
        
        # Step 3: Upload to S3
        ext = _get_media_extension_from_mime(mime_type)
        s3_key = f"{MEDIA_PREFIX}wecare-digital-{message_id}{ext}"
        s3.put_object(Bucket=MEDIA_BUCKET, Key=s3_key, Body=media_bytes, ContentType=mime_type)
        
        logger.info(json.dumps({
            'event': 'media_download_direct_api',
            'mediaId': whatsapp_media_id,
            's3Key': s3_key,
            'size': len(media_bytes),
            'mimeType': mime_type,
            'requestId': request_id
        }))
        return s3_key
    except Exception as e:
        logger.error(f"Direct API media download failed: {e}")
        return None


def _get_media_extension_from_mime(mime_type: str) -> str:
    """Get file extension from MIME type.

    Delegates to `_get_extension_from_mime` so there is one inbound MIME→ext table
    rather than three that drift. This wrapper previously carried a shorter copy that
    dropped audio/amr, audio/mp4, text/plain, ppt and pptx to '.bin' (a .bin landed a
    wrong display filename and broke the inbox's extension-driven document link).
    """
    return _get_extension_from_mime(mime_type)


def _download_media(whatsapp_media_id: str, message_id: str, media_type: str, 
                    phone_number_id: str, request_id: str,
                    mime_type_hint: str = '') -> Optional[str]:
    """
    Download media file from WhatsApp.
    Routes to Direct API for all phones.
    
    Per AWS docs (S3File.key): The key is a PREFIX  -  AWS appends the WhatsApp
    mediaId to create the final file path. For example:
      key = "audio/"             → final = "audio/{mediaId}.ogg"
    
    Strategy: Use MEDIA_PREFIX directly (ending with "/") so files land flat
    under secure/d/public/whatsapp/incoming/{mediaId}.{ext}, then rename to
    wecare-digital-{uuid}.{ext} format.
    
    Returns the actual S3 key of the downloaded file.
    """
    # Route Direct API phones to Meta Graph API download
    if _is_direct_api_phone(phone_number_id):
        return _download_media_direct_api(
            whatsapp_media_id, message_id, media_type,
            phone_number_id=phone_number_id,
            request_id=request_id,
            mime_type_hint=mime_type_hint,
        )
    
    try:
        # Use MEDIA_PREFIX directly  -  files land flat, no subfolders
        s3_key_prefix = MEDIA_PREFIX  # media_paths.WHATSAPP_INCOMING_PREFIX
        
        logger.info(json.dumps({
            'event': 'media_download_start',
            'mediaId': whatsapp_media_id,
            's3KeyPrefix': s3_key_prefix,
            'mediaType': media_type,
            'mimeTypeHint': mime_type_hint,
            'phoneNumberId': phone_number_id,
            'requestId': request_id
        }))
        
        # Download media via Meta Graph API: GET /{media_id} → get URL → download → upload to S3
        meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
        token = _load_direct_api_token()
        app_secret = _direct_api_token_cache.get('app_secret', '')

        # Step 1: Get media URL from Meta
        media_url_endpoint = f"https://graph.facebook.com/{META_API_VERSION}/{whatsapp_media_id}"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            media_url_endpoint = f"{media_url_endpoint}?appsecret_proof={proof}"
        media_req = urllib.request.Request(media_url_endpoint, headers={
            'Authorization': f'Bearer {token}',
        })
        with urllib.request.urlopen(media_req, timeout=15) as media_resp:
            media_info = json.loads(media_resp.read().decode())
        media_download_url = media_info.get('url', '')
        mime_type = media_info.get('mime_type', mime_type_hint or '')
        file_size = media_info.get('file_size', 0)

        # Step 2: Download the actual media file
        dl_req = urllib.request.Request(media_download_url, headers={
            'Authorization': f'Bearer {token}',
        })
        with urllib.request.urlopen(dl_req, timeout=60) as dl_resp:
            media_bytes = dl_resp.read()

        # Step 3: Determine extension and upload to S3. Use the one shared inbound
        # MIME→ext table (full Meta set) rather than a short inline copy that dropped
        # 3gp/amr/m4a/txt/doc/xls/xlsx/ppt/pptx to no-extension. '' only when the MIME
        # is genuinely unknown; the rename below then re-derives from the type.
        ext = _get_extension_from_mime(mime_type) if mime_type else ''
        actual_s3_key = f"{s3_key_prefix}{whatsapp_media_id}{ext}"
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=actual_s3_key,
            Body=media_bytes,
            ContentType=mime_type or 'application/octet-stream',
        )
        
        # Rename to wecare-digital-{uuid}.{ext} format (flat, no nesting)
        ext = _get_extension_from_mime(mime_type) if mime_type else _get_extension_from_type(media_type)
        short_id = uuid.uuid4().hex[:8]
        renamed_key = f"{MEDIA_PREFIX}wecare-digital-{short_id}{ext}"
        try:
            s3.copy_object(
                Bucket=MEDIA_BUCKET,
                CopySource={'Bucket': MEDIA_BUCKET, 'Key': actual_s3_key},
                Key=renamed_key
            )
            s3.delete_object(Bucket=MEDIA_BUCKET, Key=actual_s3_key)
            logger.info(json.dumps({
                'event': 'media_renamed',
                'originalKey': actual_s3_key,
                'renamedKey': renamed_key,
                'requestId': request_id
            }))
            actual_s3_key = renamed_key
        except Exception as rename_err:
            logger.warning(json.dumps({
                'event': 'media_rename_failed',
                'originalKey': actual_s3_key,
                'targetKey': renamed_key,
                'error': str(rename_err),
                'requestId': request_id
            }))
        
        logger.info(json.dumps({
            'event': 'media_downloaded',
            'mediaId': whatsapp_media_id,
            's3KeyPrefix': s3_key_prefix,
            'actualS3Key': actual_s3_key,
            'mimeType': mime_type,
            'fileSize': file_size,
            'phoneNumberId': phone_number_id,
            'requestId': request_id
        }))
        
        return actual_s3_key
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'media_download_error',
            'mediaId': whatsapp_media_id,
            'error': str(e),
            'requestId': request_id
        }))
        return None


def _get_extension_from_type(media_type: str) -> str:
    """
    Get file extension based on WhatsApp message type.
    Used as fallback when mime_type is not available.
    
    Supported types per WhatsApp Business Platform Cloud API:
    - image: JPEG (5MB), PNG (5MB)
    - video: MP4 (16MB), 3GPP (16MB)
    - audio: AAC (16MB), AMR (16MB), MP3 (16MB), M4A (16MB), OGG (16MB)
    - document: PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX (100MB)
    - sticker: WEBP (500KB animated, 100KB static)
    """
    type_extensions = {
        'image': '.jpeg',
        'video': '.mp4',
        'audio': '.ogg',
        'document': '.pdf',
        'sticker': '.webp'
    }
    return type_extensions.get(media_type, '.bin')


def _get_extension_from_mime(mime_type: str) -> str:
    """
    Get file extension based on MIME type.
    Complete mapping per WhatsApp Business Platform supported media types.
    """
    mime_extensions = {
        # Image formats (max 5MB)
        'image/jpeg': '.jpeg',
        'image/png': '.png',
        
        # Sticker formats (max 500KB animated, 100KB static)
        'image/webp': '.webp',
        
        # Video formats (max 16MB)
        'video/mp4': '.mp4',
        'video/3gpp': '.3gp',
        
        # Audio formats (max 16MB)
        'audio/aac': '.aac',
        'audio/amr': '.amr',
        'audio/mpeg': '.mp3',
        'audio/mp4': '.m4a',
        'audio/ogg': '.ogg',
        'audio/opus': '.opus',
        
        # Document formats (max 100MB)
        'application/pdf': '.pdf',
        'text/plain': '.txt',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/vnd.ms-powerpoint': '.ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    }
    return mime_extensions.get(mime_type, '.bin')


def _store_media_record(message_id: str, s3_key: str, media_data: Dict, whatsapp_media_id: str) -> Optional[str]:
    """
    Store media file record in MediaFiles table.
    Returns file_id if successful, None if table doesn't exist or write fails.
    This is optional - the s3Key is stored directly in the message record.
    """
    try:
        file_id = str(uuid.uuid4())
        now = int(time.time())
        
        media_record = {
            # MediaFilesTable's hash key is `id`, not `fileId`. Without it every
            # put_item failed with `ValidationException: Missing the key id` - 17 out
            # of 17 writes in the seven days to 2026-10-06 - and the failure was
            # swallowed by the except below as "the table may not exist", so nothing
            # ever surfaced. The visible consequence was downstream: `mediaId` stayed
            # null on the message, and the daily Meta media-DELETE cron
            # (`wecare-media-cleanup`) scanned an empty table and deleted nothing,
            # every day, reporting success. `fileId` is kept alongside for any reader
            # written against the old shape.
            'id': file_id,
            'fileId': file_id,
            'messageId': message_id,
            's3Key': s3_key,
            'contentType': media_data.get('mime_type', ''),
            'size': Decimal(str(media_data.get('file_size', 0))) if media_data.get('file_size') else None,
            'whatsappMediaId': whatsapp_media_id,
            'uploadedAt': Decimal(str(now)),
        }
        
        media_table = dynamodb.Table(MEDIA_FILES_TABLE)
        media_table.put_item(Item={k: v for k, v in media_record.items() if v is not None})
        
        logger.info(json.dumps({
            'event': 'media_record_stored',
            'fileId': file_id,
            'messageId': message_id,
            's3Key': s3_key
        }))
        
        return file_id
    except Exception as e:
        # MediaFile table may not exist - this is OK, s3Key is stored in message record
        logger.warning(json.dumps({
            'event': 'media_record_store_skipped',
            'messageId': message_id,
            's3Key': s3_key,
            'error': str(e),
            'note': 'MediaFile table write failed, but s3Key is stored in message record'
        }))
        return None


def _attach_whatsapp_document_to_pending_dropdocs(
    sender_phone: str, sender_name: str, contact_id: str, message_id: str,
    whatsapp_media_id: str, s3_key: str, msg_type: str,
    mime_type: str, filename: str, file_size: int, request_id: str,
) -> bool:
    """Bind WhatsApp media only to an explicit, recent Drop Docs upload target.

    Ordinary Inbox images/documents remain conversation media. They must not become
    business DocumentTable rows merely because their MIME type looks document-like.
    The Drop Docs flow places a two-hour target on the contact; this consumes it once.
    """
    if not contact_id or not s3_key:
        return False

    now = int(time.time())
    try:
        contact = dynamodb.Table(CONTACTS_TABLE).get_item(
            Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
        doc_id = str(contact.get('pendingDocumentSubmissionId') or '').strip()
        try:
            opened = int(contact.get('pendingDocumentSubmissionAt') or 0)
        except (TypeError, ValueError):
            opened = 0
        if not doc_id or opened <= 0 or now - opened < 0 or now - opened > 2 * 3600:
            return False

        doc_table = dynamodb.Table(
            os.environ.get('DOCUMENTS_TABLE', 'stack-wecare-digital-DocumentTable'))
        doc = doc_table.get_item(Key={'documentId': doc_id}, ConsistentRead=True).get('Item') or {}
        if not doc:
            return False
        if str(doc.get('contactId') or '') != str(contact_id):
            logger.warning(json.dumps({
                'event': 'dropdocs_media_owner_mismatch',
                'documentId': doc_id, 'requestId': request_id,
            }))
            return False
        if str(doc.get('sourceType') or '') != 'flow':
            return False

        existing_key = str(doc.get('storageKey') or '')
        existing_ref = str(doc.get('sourceReferenceId') or '')
        if existing_key:
            return existing_ref == whatsapp_media_id

        doc_table.update_item(
            Key={'documentId': doc_id},
            UpdateExpression=(
                'SET storageKey=:key, sourceReferenceId=:ref, fileName=:name, '
                'mimeType=:mime, fileSize=:size, verificationStatus=:uploaded, '
                'uploadedAt=:now, updatedAt=:now'
            ),
            ConditionExpression=(
                'contactId=:cid AND sourceType=:flow AND attribute_not_exists(storageKey)'
            ),
            ExpressionAttributeValues={
                ':key': s3_key,
                ':ref': whatsapp_media_id,
                ':name': filename or f'{msg_type}_{message_id[:8]}',
                ':mime': mime_type or '',
                ':size': int(file_size or 0),
                ':uploaded': 'uploaded',
                ':now': now,
                ':cid': contact_id,
                ':flow': 'flow',
            },
        )

        try:
            dynamodb.Table(CONTACTS_TABLE).update_item(
                Key={'id': contact_id},
                UpdateExpression='REMOVE pendingDocumentSubmissionId, pendingDocumentSubmissionAt',
                ConditionExpression='pendingDocumentSubmissionId=:doc',
                ExpressionAttributeValues={':doc': doc_id},
            )
        except Exception:
            pass

        logger.info(json.dumps({
            'event': 'dropdocs_media_attached',
            'documentId': doc_id,
            'messageId': message_id,
            'requestId': request_id,
        }))
        return True
    except ClientError as exc:
        code = str((exc.response.get('Error') or {}).get('Code') or '')
        if code != 'ConditionalCheckFailedException':
            logger.warning(json.dumps({
                'event': 'dropdocs_media_attach_failed',
                'errorType': type(exc).__name__, 'requestId': request_id,
            }))
        return False
    except Exception as exc:
        logger.warning(json.dumps({
            'event': 'dropdocs_media_attach_failed',
            'errorType': type(exc).__name__, 'requestId': request_id,
        }))
        return False

def _meter_partner_usage(status: Dict, waba_id: str, request_id: str) -> None:
    """Charge a partner (Embedded-Signup) tenant's prepaid wallet for a billable
    message. No-op for platform-owned numbers (no wallet). Never raises."""
    if not partner_billing or not waba_id:
        return
    try:
        pricing = status.get('pricing', {}) or {}
        billable = pricing.get('billable', False)
        # Charge once per message on the 'sent' status (which carries pricing).
        if status.get('status') != 'sent' or not billable:
            return
        category = pricing.get('category', '') or ''
        msg_id = status.get('id', '')
        # Idempotency: charge once per message even if the 'sent' webhook is redelivered.
        try:
            from lambda_utils.webhook_dedup import claim_event
            if msg_id and not claim_event(f'meter_{msg_id}', source='partner_meter'):
                return
        except Exception:  # noqa: BLE001 — dedup must never block real metering
            pass
        res = partner_billing.charge(waba_id, category=category, message_id=msg_id,
                                     note='wa message', to_number=status.get('recipient_id', ''))
        if res.get('charged'):
            logger.info(json.dumps({'event': 'partner_usage_charged', 'wabaId': waba_id,
                                    'category': category, 'amount': res.get('amount'),
                                    'balance': res.get('balance'), 'requestId': request_id}))
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'partner_metering_error', 'wabaId': waba_id, 'error': str(e)}))


def _process_status(status: Dict, request_id: str, contacts_map: Dict = None, waba_id: str = '') -> None:
    """
    Process message status update (sent|delivered|read|failed|payment).
    Checks BOTH InboundTable and OutboundTable using GSI for O(1) lookup.
    Extracts BSUID (recipient_user_id) and parent_recipient_user_id from status webhooks.
    
    Per Meta BSUID docs (Mar 2026): status webhooks now include a contacts array
    with user_id, username, wa_id, parent_user_id for sent/delivered/read statuses.
    
    Payment status webhooks have type='payment' with payment object containing:
    - reference_id: Order/invoice reference
    - amount: {value, offset}
    - currency: INR
    - status: pending|captured|failed
    """
    whatsapp_message_id = status.get('id')
    status_value = status.get('status')
    status_type = status.get('type', '')  # 'payment' for payment webhooks
    timestamp = int(status.get('timestamp', time.time()))
    recipient_id = status.get('recipient_id', '')
    recipient_user_id = status.get('recipient_user_id', '')  # BSUID
    parent_recipient_user_id = status.get('recipient_parent_user_id', '')  # Parent BSUID
    opaque_message_id = str(status.get('biz_opaque_callback_data') or '').strip()
    if not (opaque_message_id.startswith('wa-idem-') and len(opaque_message_id) <= 96
            and all(32 <= ord(ch) < 127 for ch in opaque_message_id)):
        opaque_message_id = ''
    
    # Log all status updates for debugging. The SHAPE of the status, never its values:
    # `recipient_id` is the customer's phone number, and the full object also carries the BSUID,
    # Meta's error details and the payment object. Error codes are enough to debug a failure.
    logger.info(json.dumps({
        'event': 'status_update_received',
        'statusType': status_type,
        'statusValue': status_value,
        'whatsappMessageId': whatsapp_message_id,
        'recipientId': mask_phone(recipient_id),
        'hasPaymentData': 'payment' in status,
        'hasOpaqueCorrelation': bool(opaque_message_id),
        'statusKeys': sorted(status) if isinstance(status, dict) else [],
        'errorCodes': [e.get('code') for e in (status.get('errors') or [])
                       if isinstance(e, dict)],
        'requestId': request_id
    }))
    
    # Handle payment status webhooks FIRST (before other checks)
    if status_type == 'payment' or 'payment' in status:
        _process_payment_status(status, request_id)
        return
    
    if not whatsapp_message_id or not status_value:
        return

    # Meter partner (Embedded-Signup) tenant usage against their prepaid wallet.
    # No-op for platform-owned numbers. Guarded — never breaks status processing.
    _meter_partner_usage(status, waba_id, request_id)
    
    # Search BOTH tables for the message using GSI
    OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
    tables_to_check = [
        ('inbound', MESSAGES_TABLE),
        ('outbound', OUTBOUND_TABLE),
    ]
    
    updated = False
    for direction, table_name in tables_to_check:
        try:
            table = dynamodb.Table(table_name)
            
            # A keyed send may time out after Meta accepts it, so the sender can miss the
            # WAMID. Meta echoes biz_opaque_callback_data on status webhooks; use that stable
            # internal id first, then fall back to the WAMID GSI for all ordinary sends.
            items = []
            if opaque_message_id:
                direct = table.get_item(Key={'id': opaque_message_id}, ConsistentRead=True).get('Item')
                if direct:
                    items = [direct]
            if not items:
                try:
                    response = table.query(
                        IndexName='whatsappMessageId-index',
                        KeyConditionExpression='whatsappMessageId = :wmid',
                        ExpressionAttributeValues={':wmid': whatsapp_message_id},
                        Limit=1
                    )
                except Exception:
                    # Fallback to scan if GSI not ready.
                    response = table.scan(
                        FilterExpression='whatsappMessageId = :wmid',
                        ExpressionAttributeValues={':wmid': whatsapp_message_id},
                        Limit=1
                    )
                items = response.get('Items', [])
            if items:
                message_id = items[0].get('id') or items[0].get('messageId')
                # Build update expression  -  include recipientBsuid and parentRecipientBsuid if available
                #
                # statusRank makes the write MONOTONIC. Meta guarantees neither
                # order nor exactly-once delivery of status webhooks, and this
                # used to be an unconditional SET, so the last webhook to arrive
                # won whatever it said: a late `sent` overwrote `read`, and a
                # re-delivered `failed` overwrote `delivered`. The rank plus the
                # ConditionExpression below refuse any backward transition, which
                # also makes duplicate deliveries harmless. See lambda_utils/wa_status.py
                # for the ranking and why `failed` sits between sent and delivered.
                update_expr = ('SET #status = :status, statusUpdatedAt = :ts, '
                               f'{wa_status.RANK_ATTRIBUTE} = :rank')
                expr_values = {
                    ':status': status_value,
                    ':ts': Decimal(str(timestamp)),
                    ':rank': Decimal(str(wa_status.rank(status_value))),
                }
                if opaque_message_id and whatsapp_message_id:
                    update_expr += ', whatsappMessageId = :wmid'
                    expr_values[':wmid'] = whatsapp_message_id
                if recipient_user_id:
                    update_expr += ', recipientBsuid = :rbsuid'
                    expr_values[':rbsuid'] = recipient_user_id
                if parent_recipient_user_id:
                    update_expr += ', parentRecipientBsuid = :prbsuid'
                    expr_values[':prbsuid'] = parent_recipient_user_id

                # Delivery-time failure: capture Meta error code + reason so the
                # inbox can show a tooltip explaining why the message wasn't
                # delivered (e.g. 131026 undeliverable, 131047 re-engagement).
                if status_value == 'failed':
                    status_errors = status.get('errors', []) or []
                    if status_errors:
                        e0 = status_errors[0]
                        err_code = e0.get('code')
                        err_reason = (e0.get('title') or e0.get('message')
                                      or (e0.get('error_data', {}) or {}).get('details', '') or '')
                        if err_code is not None:
                            update_expr += ', errorCode = :ec'
                            expr_values[':ec'] = int(err_code)
                        if err_reason:
                            update_expr += ', errorDetails = :ed'
                            expr_values[':ed'] = json.dumps({'code': err_code, 'message': err_reason})

                try:
                    table.update_item(
                        Key={'id': message_id},
                        UpdateExpression=update_expr,
                        ConditionExpression=wa_status.condition_expression(),
                        ExpressionAttributeNames={'#status': 'status'},
                        ExpressionAttributeValues=expr_values
                    )
                except ClientError as _ce:
                    if _ce.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                        raise
                    # A backward or duplicate transition. Not an error: it is the
                    # guard doing its job. Recorded so out-of-order delivery is
                    # observable rather than invisible.
                    logger.info(json.dumps({
                        'event': 'status_out_of_order_skipped',
                        'messageId': message_id,
                        'whatsappMessageId': whatsapp_message_id,
                        'incomingStatus': status_value,
                        'incomingRank': wa_status.rank(status_value),
                        'table': direction,
                        'requestId': request_id,
                    }))
                    updated = True
                    break

                # Mirror the same status onto the canonical MessagesTable (same id,
                # written by the dual-write). Guarded — never breaks status processing.
                # The rank guard is ANDed with the existence check so the mirror
                # cannot regress either.
                if table_name != UNIFIED_MESSAGES_TABLE:
                    try:
                        dynamodb.Table(UNIFIED_MESSAGES_TABLE).update_item(
                            Key={'id': message_id},
                            UpdateExpression=update_expr,
                            ConditionExpression=(
                                'attribute_exists(id) AND ('
                                + wa_status.condition_expression() + ')'
                            ),
                            ExpressionAttributeNames={'#status': 'status'},
                            ExpressionAttributeValues=expr_values
                        )
                    except Exception as _ue:
                        logger.debug(f'canonical status mirror skipped for {message_id}: {_ue}')
                
                logger.info(json.dumps({
                    'event': 'status_updated',
                    'messageId': message_id,
                    'whatsappMessageId': whatsapp_message_id,
                    'status': status_value,
                    'statusRank': wa_status.rank(status_value),
                    'table': direction,
                    'requestId': request_id
                }))
                updated = True
                break  # Found and updated, no need to check other table
                
        except Exception as e:
            logger.error(json.dumps({
                'event': 'status_update_error',
                'whatsappMessageId': whatsapp_message_id,
                'table': direction,
                'error': str(e),
                'requestId': request_id
            }))
    
    if not updated:
        # Downgrade to debug  -  this is normal for auto-reaction/read-receipt messages
        # which are not stored in the outbound table
        logger.debug(json.dumps({
            'event': 'status_update_message_not_found',
            'whatsappMessageId': whatsapp_message_id,
            'status': status_value,
            'requestId': request_id
        }))
    
    # Enrich contact records from status webhook contacts array
    # Per Meta BSUID docs: sent/delivered/read status webhooks include a contacts
    # array with user_id (BSUID), username, wa_id, parent_user_id
    if contacts_map and status_value in ('sent', 'delivered', 'read'):
        for ckey, centry in contacts_map.items():
            if not isinstance(centry, dict):
                continue
            c_bsuid = centry.get('bsuid', '')
            c_username = centry.get('username', '')
            c_phone = centry.get('wa_id', '') if 'wa_id' in centry else ''
            c_parent_bsuid = centry.get('parent_bsuid', '')
            if not c_bsuid:
                continue
            try:
                # Status contacts are scoped to the sender business just like
                # inbound messages. Never query the global unscoped bsuid-index.
                contacts_table = dynamodb.Table(CONTACTS_TABLE)
                existing = _find_scoped_bsuid(
                    contacts_table, c_bsuid, waba_id, sender_phone=c_phone)
                if existing is None and c_phone:
                    existing = contact_store.lookup(contacts_table, c_phone)
                if existing:
                    _update_contact_bsuid_fields(
                        contacts_table, existing,
                        sender_name=centry.get('name', ''),
                        username=c_username,
                        phone=c_phone,
                        bsuid=c_bsuid,
                        parent_bsuid=c_parent_bsuid,
                        waba_id=waba_id,
                    )
            except Exception as enrich_err:
                logger.debug(f'Status contact enrichment skipped: {enrich_err}')


def _sanitize_reference_id(reference_id: str) -> str:
    """
    Normalise an INBOUND reference_id for lookup and display.

    This is the read side: the value arrives from Meta or Razorpay and is used to resolve a
    payment attempt we created. So the safest possible behaviour is to change it as little as
    possible, and the first branch below now does exactly nothing to a value that is already
    valid.

    That ordering is the fix. Previously every value was upper-cased and stripped of
    non-alphanumerics before the pass-through checks, so a reference containing a dot - which
    Meta explicitly permits - was rewritten into a different string, and the lookup for the
    attempt that owns it then missed. Meta's reference_id is case SENSITIVE, so upper-casing
    is itself a mutation that can break a join.

    Legacy upgrades still run, but only for values that are not already acceptable, which is
    the only situation they were ever meant for.

    Examples:
    - "WD-PAY-ABC12345"    -> "WD-PAY-ABC12345"  (untouched, valid)
    - "WD-PAY-a.b_c"       -> "WD-PAY-a.b_c"     (untouched: dots and case preserved)
    - "WD_41BA3534"        -> "WD-PAY-41BA3534"  (legacy shape upgraded)
    - "WD+41BA3534"        -> "WD-PAY-41BA3534"  (plus is outside Meta's charset)
    """
    import re

    if not reference_id:
        return reference_id

    raw = reference_id.strip()

    # Already something Meta would have accepted, so it is almost certainly the exact value we
    # minted. Return it byte-for-byte: any normalisation here is a chance to break the join.
    if order_keys.is_valid_meta_reference_id(raw) and 'WD-PAY-WD-PAY-' not in raw.upper():
        return raw

    stripped = raw.upper()

    # Remove duplicate WD-PAY- prefixes
    while 'WD-PAY-WD-PAY-' in stripped:
        stripped = stripped.replace('WD-PAY-WD-PAY-', 'WD-PAY-')

    if stripped.startswith('WD-PAY-') or stripped.startswith('WD-ORD-'):
        return stripped

    # Old format: strip non-alnum, remove legacy WD prefix(es), add WD-PAY-
    cleaned = re.sub(r'[^A-Za-z0-9]', '', stripped)
    while cleaned.startswith('WD'):
        cleaned = cleaned[2:]
    if not cleaned:
        return stripped  # Return original if nothing left

    upgraded = f'WD-PAY-{cleaned}'
    if len(upgraded) > order_keys.META_REFERENCE_ID_MAX_LENGTH:
        # Deliberately NOT truncated. Two truncated references are indistinguishable, and this
        # value is about to be used to resolve which order a payment belongs to. Returning it
        # over-length means the lookup misses and the event surfaces for staff, which is the
        # recoverable outcome; truncating means it silently matches the wrong order.
        logger.warning(json.dumps({
            'event': 'inbound_reference_id_over_length',
            'length': len(upgraded),
            'limit': order_keys.META_REFERENCE_ID_MAX_LENGTH,
            'note': 'not truncated; lookup will miss rather than match the wrong order',
        }))
    return upgraded


def _select_payment_transaction(payment_data: Dict) -> Dict:
    """Return the authoritative transaction object from either Meta payment shape.

    Meta has emitted both a legacy singular transaction object and the live
    ORDER_DETAILS transactions[] list. Prefer the plural list when present,
    because it is the shape that carries pg_transaction_id in current native
    payment captures. Among multiple rows, prefer one with a canonical terminal
    state (captured/failed); otherwise preserve Meta order and use the first dict.
    """
    rows = payment_data.get('transactions')
    if isinstance(rows, list):
        candidates = [row for row in rows if isinstance(row, dict)]
        if candidates:
            for row in candidates:
                state = pay_status.canonical(row.get('status', ''))
                if state in (pay_status.CAPTURED, pay_status.FAILED):
                    return row
            return candidates[0]

    legacy = payment_data.get('transaction')
    return legacy if isinstance(legacy, dict) else {}

def _process_payment_status(status: Dict, request_id: str) -> None:
    """
    Process payment status webhook from WhatsApp.
    
    Payment webhook format:
    {
        "id": "wamid.xxx",
        "recipient_id": "919876543210",
        "type": "payment",
        "status": "captured",  // pending, captured, failed
        "payment": {
            "reference_id": "ORDER_12345",
            "amount": {"value": 10000, "offset": 100},
            "currency": "INR",
            "transaction": {
                "id": "txn_xxx",
                "type": "upi",
                "status": "success"
            }
        },
        "timestamp": "1706140800"
    }
    """
    # Keys and masked ids only: the status object carries the payer's recipient_id and the full
    # payment payload (amount, transaction), none of which belong in an advisory log line.
    logger.info(json.dumps({
        'event': 'payment_status_processing',
        'statusKeys': sorted(status) if isinstance(status, dict) else [],
        'statusWord': status.get('status', ''),
        'recipientId': mask_phone(status.get('recipient_id', '')),
        'requestId': request_id
    }))
    
    payment_data = status.get('payment', {})
    raw_reference_id = payment_data.get('reference_id', '')
    # Sanitize reference_id - remove duplicate WD prefix and underscores
    reference_id = _sanitize_reference_id(raw_reference_id)
    payment_status = status.get('status', '')
    # Meta's raw word is kept for storage and logging - we must not lose what the provider
    # actually said - but every DECISION below goes through the canonical form. Meta's own
    # vocabulary is not ours: `payment_status` measured `FlowSubmission.paymentStatus` already
    # holding Meta's raw `paid`, and the branches below used to compare `== 'captured'`. So a
    # capture reported as `paid` took the else branch: no verification, no invoice, and no
    # confirmation to a customer who had paid.
    payment_state = pay_status.canonical(payment_status)
    recipient_id = status.get('recipient_id', '')
    timestamp = int(status.get('timestamp', time.time()))
    
    # Log payment data extraction
    logger.info(json.dumps({
        'event': 'payment_data_extracted',
        # Keys only: the payment object can carry the payer's details.
        'paymentDataKeys': sorted(payment_data) if isinstance(payment_data, dict) else [],
        'referenceId': reference_id,
        'paymentStatus': payment_status,
        'recipientId': mask_phone(recipient_id),
        'requestId': request_id
    }))
    
    amount = payment_data.get('amount', {})
    amount_value = amount.get('value', 0)
    amount_offset = amount.get('offset', 100)
    currency = payment_data.get('currency', 'INR')
    
    # Log amount extraction with full details
    logger.info(json.dumps({
        'event': 'payment_amount_extracted',
        'amountObject': amount,
        'amountValue': amount_value,
        'amountOffset': amount_offset,
        'paymentDataKeys': list(payment_data.keys()) if payment_data else [],
        'requestId': request_id
    }))
    
    # Calculate actual amount (value / offset)
    actual_amount = amount_value / amount_offset if amount_offset else amount_value
    
    # If amount is 0, try to look up from original payment request in DynamoDB
    if actual_amount == 0 and reference_id:
        logger.info(json.dumps({
            'event': 'payment_amount_zero_lookup',
            'referenceId': reference_id,
            'requestId': request_id
        }))
        actual_amount = _lookup_payment_amount(reference_id, request_id)
    
    transaction = _select_payment_transaction(payment_data)
    transaction_id = transaction.get('id', '')
    transaction_type = transaction.get('type', '')
    
    logger.info(json.dumps({
        'event': 'payment_status_received',
        'referenceId': reference_id,
        'paymentStatus': payment_status,
        'recipientId': mask_phone(recipient_id),
        'amount': actual_amount,
        'currency': currency,
        'transactionId': transaction_id,
        'transactionType': transaction_type,
        'requestId': request_id
    }))

    # Meta can redeliver the same payment status. This path is advisory only (the Razorpay
    # webhook is the paid-state authority), but a redelivery still re-stores the record and
    # re-emits the advisory log, so claim once per (reference, status, transaction). claim_event
    # fails open on a missing key or a DynamoDB error, so a real status is never dropped.
    from lambda_utils.webhook_dedup import claim_event
    _dedup_key = f'wa-payment:{reference_id}:{payment_status}:{transaction_id}'
    if not claim_event(_dedup_key, source='whatsapp_payment_status'):
        logger.info(json.dumps({
            'event': 'payment_status_duplicate_skipped',
            'referenceId': reference_id,
            'paymentStatus': payment_status,
            'requestId': request_id,
        }))
        return
    
    # Store payment record in DynamoDB
    _store_payment_record(
        reference_id=reference_id,
        recipient_id=recipient_id,
        payment_status=payment_status,
        amount_value=amount_value,
        amount_offset=amount_offset,
        currency=currency,
        transaction=transaction,
        timestamp=timestamp,
        request_id=request_id,
        full_payment_data=payment_data,
    )
    
    # Look up the phone_number_id from the original outbound payment request
    # so the confirmation goes back from the same business number
    originating_phone_id = None
    if reference_id:
        try:
            OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
            outbound_table = dynamodb.Table(OUTBOUND_TABLE)
            # Query GSI paymentReferenceId-index (falls back to scan if GSI missing)
            found = False
            try:
                resp = outbound_table.query(
                    IndexName='paymentReferenceId-index',
                    KeyConditionExpression='paymentReferenceId = :ref',
                    ExpressionAttributeValues={':ref': reference_id},
                    Limit=1,
                )
                items = resp.get('Items', [])
                if items:
                    originating_phone_id = items[0].get('awsPhoneNumberId') or items[0].get('phoneNumberId')
                    found = True
            except Exception:
                # Fallback to paginated scan if GSI not yet active
                scan_kwargs = {
                    'FilterExpression': 'paymentReferenceId = :ref',
                    'ExpressionAttributeValues': {':ref': reference_id},
                    'ProjectionExpression': 'awsPhoneNumberId, phoneNumberId',
                }
                while not found:
                    resp = outbound_table.scan(**scan_kwargs)
                    items = resp.get('Items', [])
                    if items:
                        originating_phone_id = items[0].get('awsPhoneNumberId') or items[0].get('phoneNumberId')
                        found = True
                    elif 'LastEvaluatedKey' in resp:
                        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                    else:
                        break
            
            logger.info(json.dumps({
                'event': 'payment_phone_id_resolved',
                'referenceId': reference_id,
                'phoneNumberId': originating_phone_id,
                'found': found,
                'requestId': request_id
            }))
        except Exception as e:
            logger.warning(json.dumps({
                'event': 'payment_phone_id_lookup_failed',
                'referenceId': reference_id,
                'error': str(e),
                'requestId': request_id
            }))

    # Detect effective failure: WhatsApp may send status="pending" but
    # transaction.status="failed" (e.g. insufficient funds / gateway error).
    transaction_status = transaction.get('status', '')
    effective_failed = (
        payment_state == pay_status.FAILED
        or (payment_state == pay_status.PENDING
            and pay_status.canonical(transaction_status) == pay_status.FAILED)
    )

    # Send order_status message based on payment status
    if payment_state == pay_status.CAPTURED:
        # ── Security: Verify payment via Meta Payment Lookup API ──
        # Meta docs: "must not rely solely on the status of the transaction provided in the webhook"
        #
        # There are four possible outcomes here and the code used to record only
        # two. `payment_verified` was a bool initialised True, so a capture that
        # was never checked - because the outbound row had no paymentConfigName, or
        # because the lookup call itself failed - was indistinguishable in the logs
        # and on the invoice from one Meta had confirmed. Asking "which captures did
        # we accept without verifying?" had no answer.
        #
        # ADVISORY ONLY: this lookup no longer gates any financial side effect — the branch
        # below creates NO paid state at all (see the advisory block). In-WhatsApp payments ARE
        # live, but the Razorpay webhook (payments/razorpay-webhook/handler.py, via razorpay_verify)
        # is the single authoritative payment producer: it re-derives the paid state from a provider
        # readback, so this Meta-webhook path must not mint a second, unverified one. The
        # verification is retained ONLY to compute an auditable `verification_outcome` for the
        # advisory log, so the historical fail-open exposure stays visible. PAYMENT_LOOKUP_REQUIRED
        # is intentionally LEFT DEFINED (its env-var contract is preserved) but is now dead on the
        # financial path: regardless of its value, no paid invoice/order/receipt can be created here.
        VERIFIED = 'verified'
        UNVERIFIED_NO_CONFIG = 'unverified_no_payment_config'
        UNVERIFIED_LOOKUP_FAILED = 'unverified_lookup_failed'
        REJECTED_MISMATCH = 'rejected_lookup_mismatch'

        lookup_required = str(
            os.environ.get('PAYMENT_LOOKUP_REQUIRED', '')
        ).strip().lower() in ('1', 'true', 'yes', 'on')

        verification_outcome = UNVERIFIED_NO_CONFIG
        if reference_id and originating_phone_id:
            try:
                # Look up payment config from the original outbound message
                OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
                outbound_table = dynamodb.Table(OUTBOUND_TABLE)
                config_name = ''
                try:
                    resp = outbound_table.query(
                        IndexName='paymentReferenceId-index',
                        KeyConditionExpression='paymentReferenceId = :ref',
                        ExpressionAttributeValues={':ref': reference_id},
                        Limit=1,
                    )
                    items = resp.get('Items', [])
                    if items:
                        config_name = items[0].get('paymentConfigName', '')
                except Exception:
                    pass

                if config_name:
                    import urllib.request, urllib.error
                    # Call Meta Payment Lookup API
                    meta_phone_id = originating_phone_id
                    # Extract Meta phone ID if in internal format
                    if '-direct-' in meta_phone_id:
                        meta_phone_id = meta_phone_id.split('-direct-')[-1]

                    token = _load_direct_api_token()
                    lookup_url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/payments/{config_name}/{reference_id}"
                    req = urllib.request.Request(lookup_url, headers={
                        'Authorization': f'Bearer {token}',
                    }, method='GET')
                    try:
                        with urllib.request.urlopen(req, timeout=10) as r:
                            lookup_result = json.loads(r.read().decode())
                        payments = lookup_result.get('payments', [])
                        if payments:
                            lookup_status = payments[0].get('status', '')
                            # Canonical, not raw. This branch decides whether to REJECT a payment
                            # the customer has already made, so a vocabulary mismatch here refuses
                            # real money: Meta answering `paid` against our `captured` would have
                            # been recorded as REJECTED_MISMATCH. An unrecognised word still
                            # rejects - `canonical` returns '' for anything unmappable, which is
                            # the correct direction for a verification step.
                            if pay_status.canonical(lookup_status) != pay_status.CAPTURED:
                                verification_outcome = REJECTED_MISMATCH
                                logger.warning(json.dumps({
                                    'event': 'payment_lookup_mismatch',
                                    'webhookStatus': 'captured',
                                    'lookupStatus': lookup_status,
                                    'lookupStatusCanonical': pay_status.canonical(lookup_status),
                                    'referenceId': reference_id,
                                    'requestId': request_id,
                                }))
                            else:
                                verification_outcome = VERIFIED
                                logger.info(json.dumps({
                                    'event': 'payment_lookup_verified',
                                    'referenceId': reference_id,
                                    'requestId': request_id,
                                }))
                        else:
                            # 200 with an empty payments array. Meta knows the
                            # reference and reports nothing for it, which is not a
                            # confirmation - previously this fell through leaving
                            # payment_verified True.
                            verification_outcome = UNVERIFIED_LOOKUP_FAILED
                            logger.warning(json.dumps({
                                'event': 'payment_lookup_empty',
                                'referenceId': reference_id,
                                'requestId': request_id,
                            }))
                    except Exception as lookup_err:
                        verification_outcome = UNVERIFIED_LOOKUP_FAILED
                        logger.warning(json.dumps({
                            'event': 'payment_lookup_failed',
                            'error': str(lookup_err)[:200],
                            'referenceId': reference_id,
                            'requestId': request_id,
                        }))
                else:
                    verification_outcome = UNVERIFIED_NO_CONFIG
                    logger.warning(json.dumps({
                        'event': 'payment_lookup_skipped_no_config',
                        'reason': ('no paymentConfigName on the outbound row for this '
                                   'referenceId, so the Payment Lookup API cannot be '
                                   'addressed'),
                        'referenceId': reference_id,
                        'requestId': request_id,
                    }))
            except Exception as e:
                verification_outcome = UNVERIFIED_LOOKUP_FAILED
                logger.warning(json.dumps({
                    'event': 'payment_verification_error',
                    'error': str(e)[:200],
                    'requestId': request_id,
                }))

        # ── ADVISORY: this Meta-webhook CAPTURED branch creates NO paid state ──
        # In-WhatsApp payments are live, but the Razorpay webhook is the authoritative payment
        # producer. This Meta payment-webhook path is advisory only, so this CAPTURED branch
        # deliberately creates no paid state — a second producer here, off an unverified webhook
        # body, could mint paid invoices/orders/receipts that disagree with the authority.
        #
        # Previously this path marked the invoice paid, sent a 'completed' order_status,
        # generated a GST invoice, and notified balance-due — all off a capture that was
        # accepted FAIL-OPEN (the Meta Payment Lookup is advisory here and defaults off
        # via PAYMENT_LOOKUP_REQUIRED). An unverified webhook body could therefore mint
        # paid invoices/orders/receipts. That financial fall-through is now retired.
        #
        # The single authoritative payment producer going forward is the Razorpay
        # webhook (amplify/functions/payments/razorpay-webhook/handler.py), which
        # re-derives every financial decision from an authoritative provider readback
        # via lambda_utils/integrations/razorpay_verify (payment_is_captured /
        # verifier_for_event) — never from the event body. No weaker parallel path may
        # create paid state.
        #
        # We still STORE the raw payment record above (non-financial, for audit) and we
        # emit a clearly-labelled, type-only SUPERSEDED audit record here so the event
        # stays visible to whoever reconciles it. We intentionally make NO financial
        # state mutation: no _mark_invoice_paid_by_reference, no _send_order_status
        # 'completed', no _generate_invoice_for_captured_payment, no balance-due notify.
        # `verification_outcome` and `lookup_required` are retained in the log purely for
        # audit; regardless of PAYMENT_LOOKUP_REQUIRED, no paid state can be created here.
        logger.error(json.dumps({
            'event': 'in_whatsapp_payment_capture_superseded',
            'note': ('advisory only; no financial side effects — in-WhatsApp payments '
                     'are live but the Razorpay webhook is the single authoritative '
                     'payment producer'),
            'verificationOutcome': verification_outcome,
            'lookupRequired': lookup_required,
            'referenceId': reference_id,
            'requestId': request_id,
        }))
        # Meta saying "captured" is a reason to LOOK, never evidence. Ask the Razorpay webhook,
        # the one paid-state producer, to settle this reference now from the provider readback,
        # instead of waiting for a late Razorpay delivery or the next 5-minute sweep. Async and
        # best-effort: this path still writes no paid state, and a failure here only means the
        # sweep finds it instead.
        _trigger_capture_reconcile(reference_id, request_id)
    elif effective_failed:
        # Log only. The WhatsApp payment-order lifecycle is pending -> processing -> completed,
        # sent solely by the invoice engine; a failed attempt leaves the order pending so the
        # customer can pay again. The retired kill-switched `canceled` sender lived here.
        logger.info(json.dumps({
            'event': 'payment_effective_failure',
            'paymentStatus': payment_status,
            'transactionStatus': transaction_status,
            'referenceId': reference_id,
            'requestId': request_id,
        }))
    elif payment_state == pay_status.PENDING:
        # Genuine pending (transaction still in progress)  -  log and wait
        logger.info(json.dumps({
            'event': 'payment_pending_waiting',
            'referenceId': reference_id,
            'transactionStatus': transaction_status,
            'requestId': request_id,
        }))


#: The one paid-state producer. Inbound only ever asks it to look (`reconcileReference`).
RAZORPAY_WEBHOOK_FUNCTION = os.environ.get('RAZORPAY_WEBHOOK_FUNCTION',
                                           'wecare-razorpay-webhook:live')


def _trigger_capture_reconcile(reference_id: str, request_id: str) -> None:
    """Fire-and-forget: ask the Razorpay webhook to settle `reference_id` from the provider.

    An `Event` invoke, so the inbound webhook answers Meta immediately. The webhook validates
    the reference shape, resolves the attempt from its own PAYREF# row and settles only on a
    Razorpay readback, so nothing in this request (beyond which reference to look at) is
    trusted. Never raises.
    """
    if not reference_id:
        return
    try:
        lambda_client.invoke(
            FunctionName=RAZORPAY_WEBHOOK_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'internalAction': 'reconcileReference',
                                'referenceId': reference_id}),
        )
        logger.info(json.dumps({'event': 'capture_reconcile_requested',
                                'referenceId': reference_id, 'requestId': request_id}))
    except Exception as error:  # noqa: BLE001 - the sweep is the backstop
        logger.warning(json.dumps({'event': 'capture_reconcile_request_failed',
                                   'referenceId': reference_id, 'error': type(error).__name__,
                                   'requestId': request_id}))


def _store_payment_record(reference_id: str, recipient_id: str, payment_status: str,
                          amount_value: int, amount_offset: int, currency: str,
                          transaction: Dict = None, timestamp: int = 0,
                          request_id: str = '', full_payment_data: Dict = None) -> None:
    """Store payment record in Messages table for tracking.
    Stores full transaction object: pg_transaction_id, method.type, error.code/reason.
    Also parses and stores refund data from Meta payment webhooks."""
    if transaction is None:
        transaction = {}
    if full_payment_data is None:
        full_payment_data = {}
    try:
        # Find contact by phone number
        contact = _get_contact_by_phone(recipient_id)
        contact_id = contact.get('id', '') if contact else ''
        
        payment_id = str(uuid.uuid4())
        now = int(time.time())
        expires_at = now + MESSAGE_TTL_SECONDS
        
        # Calculate actual amount
        actual_amount = amount_value / amount_offset if amount_offset else amount_value

        # Extract full transaction fields (Gap 5)
        transaction_id = transaction.get('id', '')
        transaction_type = transaction.get('type', '')
        pg_transaction_id = transaction.get('pg_transaction_id', '')
        transaction_status = transaction.get('status', '')
        txn_method = transaction.get('method', {})
        txn_method_type = txn_method.get('type', '') if isinstance(txn_method, dict) else str(txn_method)
        txn_error = transaction.get('error', {})
        txn_error_code = txn_error.get('code', '') if isinstance(txn_error, dict) else ''
        txn_error_reason = txn_error.get('reason', '') if isinstance(txn_error, dict) else ''
        txn_created = transaction.get('created_timestamp', 0)
        txn_updated = transaction.get('updated_timestamp', 0)

        # Parse refund data from Meta payment webhooks (Gap 6)
        refunds_raw = full_payment_data.get('refunds', [])
        refunds_json = ''
        if refunds_raw:
            refunds_json = json.dumps(refunds_raw, default=str)[:4000]

        # Parse PG-specific UDF/notes echoed back in webhook
        webhook_notes = full_payment_data.get('notes', {})
        webhook_receipt = full_payment_data.get('receipt', '')
        webhook_udf1 = full_payment_data.get('udf1', '')
        webhook_udf2 = full_payment_data.get('udf2', '')
        webhook_udf3 = full_payment_data.get('udf3', '')
        webhook_udf4 = full_payment_data.get('udf4', '')
        
        payment_record = {
            'id': payment_id,
            'messageId': payment_id,
            'contactId': contact_id,
            'channel': 'whatsapp',
            'direction': 'inbound',
            'messageType': 'payment',
            'content': f'Payment {payment_status}: ₹{actual_amount:.2f} ({currency})',
            'status': payment_status,
            'senderPhone': recipient_id,
            # Payment-specific fields
            'paymentReferenceId': reference_id,
            'paymentStatus': payment_status,
            'paymentAmount': Decimal(str(amount_value)),
            'paymentOffset': Decimal(str(amount_offset)),
            'paymentCurrency': currency,
            # Full transaction object (Gap 5)
            'transactionId': transaction_id,
            'transactionType': transaction_type,
            'pgTransactionId': pg_transaction_id,
            'transactionStatus': transaction_status,
            'paymentMethodType': txn_method_type,
            'errorCode': txn_error_code,
            'errorReason': txn_error_reason,
            'txnCreatedAt': Decimal(str(txn_created)) if txn_created else None,
            'txnUpdatedAt': Decimal(str(txn_updated)) if txn_updated else None,
            # Refund data (Gap 6)
            'refundsJson': refunds_json if refunds_json else None,
            # PG-specific fields echoed back
            'webhookNotes': json.dumps(webhook_notes, default=str)[:2000] if webhook_notes else None,
            'webhookReceipt': webhook_receipt if webhook_receipt else None,
            'webhookUdf1': webhook_udf1 if webhook_udf1 else None,
            'webhookUdf2': webhook_udf2 if webhook_udf2 else None,
            'webhookUdf3': webhook_udf3 if webhook_udf3 else None,
            'webhookUdf4': webhook_udf4 if webhook_udf4 else None,
            'timestamp': Decimal(str(timestamp)),
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(expires_at)),
        }
        
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        messages_table.put_item(Item={k: v for k, v in payment_record.items() if v is not None and v != ''})

        # Unified Inbox dual-write — mirror payment record to canonical MessagesTable so
        # the dashboard (reads canonical) shows payments. Guarded; sparse contactId.
        if MESSAGES_TABLE != UNIFIED_MESSAGES_TABLE:
            try:
                dynamodb.Table(UNIFIED_MESSAGES_TABLE).put_item(
                    Item={k: v for k, v in payment_record.items() if v is not None and v != ''}
                )
            except Exception as _ce:
                logger.warning(f'payment record canonical mirror skipped: {_ce}')
        
        # Link payment to the flow response it pays for (WD-PAY- or legacy SR- references)
        if reference_id and (reference_id.startswith('WD-PAY-') or reference_id.startswith('SR-')):
            _update_flow_submission_payment(reference_id, payment_status, transaction_id, request_id)
        
        logger.info(json.dumps({
            'event': 'payment_record_stored',
            'paymentId': payment_id,
            'referenceId': reference_id,
            'contactId': mask_contact_id(contact_id),
            'paymentStatus': payment_status,
            'amount': actual_amount,
            'pgTransactionId': pg_transaction_id,
            'methodType': txn_method_type,
            'hasRefunds': bool(refunds_raw),
            'requestId': request_id
        }))
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'payment_record_store_error',
            'referenceId': reference_id,
            'error': str(e),
            'requestId': request_id
        }))


def _update_flow_submission_payment(reference_id: str, payment_status: str,
                                    transaction_id: str, request_id: str) -> None:
    """Record a payment webhook on the flow response it pays for.

    The submission lives in the one flow-response table, keyed for payments by its
    `paymentRefId` GSI. (This used to update SubmitRequestsTable, which no live writer fills,
    so the paid state never reached the submission.)

    Monotonic: the status is written in the shared payment vocabulary and only when it is a
    forward move, so a redelivered `pending` cannot overwrite a `captured`.
    """
    word = pay_status.canonical(payment_status)
    if not word:
        logger.info(json.dumps({
            'event': 'flow_submission_payment_status_unmapped',
            'referenceId': reference_id, 'requestId': request_id,
        }))
        return
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        now = int(time.time())
        resp = table.query(
            IndexName='paymentRefId',
            KeyConditionExpression='paymentRefId = :ref',
            ExpressionAttributeValues={':ref': reference_id},
            Limit=1,
        )
        items = resp.get('Items', [])
        if not items:
            logger.warning(json.dumps({
                'event': 'flow_submission_not_found_for_payment',
                'referenceId': reference_id,
                'requestId': request_id,
            }))
            return
        submission_id = items[0]['submissionId']
        try:
            table.update_item(
                Key={'submissionId': submission_id},
                UpdateExpression=('SET paymentStatus = :s, transactionId = :t, updatedAt = :u, '
                                  + pay_status.RANK_ATTRIBUTE + ' = :rank'),
                ConditionExpression=('attribute_exists(submissionId) AND ('
                                     + pay_status.condition_expression() + ')'),
                ExpressionAttributeValues={
                    ':s': word,
                    ':t': transaction_id,
                    ':u': Decimal(str(now)),
                    ':rank': pay_status.rank(word),
                },
            )
        except Exception as cond:
            if 'ConditionalCheckFailedException' not in str(cond):
                raise
            logger.info(json.dumps({
                'event': 'flow_submission_payment_not_forward',
                'submissionId': submission_id, 'paymentStatus': word,
                'requestId': request_id,
            }))
            return
        logger.info(json.dumps({
            'event': 'flow_submission_payment_linked',
            'submissionId': submission_id,
            'referenceId': reference_id,
            'paymentStatus': word,
            'requestId': request_id,
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'flow_submission_payment_link_error',
            'referenceId': reference_id,
            'errorType': type(e).__name__,
            'requestId': request_id,
        }))


def _get_contact_by_phone(phone: str) -> Optional[Dict]:
    """Get contact by phone number using GSI for O(1) lookup."""
    try:
        contacts_table = dynamodb.Table(CONTACTS_TABLE)
        
        # Clean phone number - handle various formats
        clean_phone = phone.lstrip('+')
        phone_with_plus = f'+{clean_phone}'
        
        logger.info(json.dumps({
            'event': 'contact_lookup_by_phone',
            'cleanPhone': mask_phone(clean_phone),
        }))
        
        # Use GSI query on phone-index for O(1) lookup
        for phone_variant in [phone_with_plus, clean_phone, phone]:
            try:
                response = contacts_table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :phone',
                    ExpressionAttributeValues={':phone': phone_variant},
                    Limit=5
                )
                items = response.get('Items', [])
                # Filter out deleted contacts
                items = [i for i in items if not i.get('deletedAt')]
                if items:
                    logger.info(json.dumps({
                        'event': 'contact_lookup_result',
                        'phone': mask_phone(phone),
                        'foundCount': len(items),
                        'contactId': mask_contact_id(items[0].get('id', '')),
                        'method': 'gsi'
                    }))
                    return items[0]
            except Exception:
                pass  # GSI not ready, will fallback below
        
        # Fallback to scan if GSI not ready
        response = contacts_table.scan(
            FilterExpression='(phone = :phone1 OR phone = :phone2 OR phone = :phone3) AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
            ExpressionAttributeValues={
                ':phone1': clean_phone,
                ':phone2': phone_with_plus,
                ':phone3': phone,
                ':null': None
            },
            Limit=10
        )
        
        items = response.get('Items', [])
        
        logger.info(json.dumps({
            'event': 'contact_lookup_result',
            'phone': mask_phone(phone),
            'foundCount': len(items),
            'contactId': mask_contact_id(items[0].get('id', '') if items else None),
            'method': 'scan_fallback'
        }))
        
        return items[0] if items else None
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'contact_lookup_error',
            'phone': mask_phone(phone),
            'error': str(e)
        }))
        return None


def _lookup_payment_amount(reference_id: str, request_id: str) -> float:
    """
    Look up payment amount from original payment request in Messages table.
    This is a fallback when WhatsApp webhook doesn't include the amount.
    
    The original payment request message stores the amount in the content field
    or in a dedicated paymentAmount field.
    """
    try:
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        
        # Sanitize reference_id for lookup
        sanitized_ref = _sanitize_reference_id(reference_id)
        
        # Extract just the ID part (without WD-PAY- or legacy WD prefix) for broader search
        id_part = sanitized_ref
        for pfx in ('WD-PAY-', 'WD-ORD-', 'WD'):
            if id_part.startswith(pfx):
                id_part = id_part[len(pfx):]
                break
        
        # Look for the original payment request message by reference_id
        # Search with multiple variations to handle format differences
        response = messages_table.scan(
            FilterExpression='paymentReferenceId = :ref1 OR paymentReferenceId = :ref2 OR contains(content, :id_part)',
            ExpressionAttributeValues={
                ':ref1': sanitized_ref,
                ':ref2': reference_id,  # Also try original format
                ':id_part': id_part
            },
            Limit=10
        )
        
        items = response.get('Items', [])
        
        logger.info(json.dumps({
            'event': 'payment_amount_lookup_result',
            'referenceId': reference_id,
            'sanitizedRef': sanitized_ref,
            'idPart': id_part,
            'foundCount': len(items),
            'requestId': request_id
        }))
        
        # Look for amount in the found records
        for item in items:
            # Check for paymentAmount field (stored in paise)
            payment_amount = item.get('paymentAmount')
            if payment_amount:
                offset = item.get('paymentOffset', 100)
                amount = float(payment_amount) / float(offset)
                logger.info(json.dumps({
                    'event': 'payment_amount_found_in_record',
                    'referenceId': reference_id,
                    'amount': amount,
                    'requestId': request_id
                }))
                return amount
            
            # Try to extract from content (e.g., "Payment request: ₹500.00")
            content = item.get('content', '')
            if '₹' in content:
                import re
                match = re.search(r'₹([\d,]+\.?\d*)', content)
                if match:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    logger.info(json.dumps({
                        'event': 'payment_amount_extracted_from_content',
                        'referenceId': reference_id,
                        'amount': amount,
                        'content': content[:100],
                        'requestId': request_id
                    }))
                    return amount
        
        logger.warning(json.dumps({
            'event': 'payment_amount_not_found',
            'referenceId': reference_id,
            'requestId': request_id
        }))
        return 0.0
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'payment_amount_lookup_error',
            'referenceId': reference_id,
            'error': str(e),
            'requestId': request_id
        }))
        return 0.0


def _send_to_dlq(record: Dict, error: str, request_id: str) -> bool:
    """Park a replayable inbound envelope; False means it was NOT durably stored."""
    if not INBOUND_DLQ_URL:
        return False
    
    try:
        sqs.send_message(
            QueueUrl=INBOUND_DLQ_URL,
            MessageBody=json.dumps({
                'originalRecord': record,
                'error': error,
                'timestamp': int(time.time()),
                'requestId': request_id
            }, default=str)
        )
        return True
    except Exception as e:
        logger.error(json.dumps({
            'event': 'dlq_send_error',
            'alert': 'INBOUND_DLQ_WRITE_FAILED',
            'error': str(e),
            'requestId': request_id
        }))
        return False


# `_send_submit_request_flow` was removed on 2026-10-26. It had no caller (the keyword door uses
# the service-link router, and Submit Request answers with its website link), and its default Flow
# 1235100738173254 was an unused legacy draft.


# ── Attributed review door (Phase R) ──
#
# The website's "Leave a review" button opens `wa.me/<WABA1>?text=review <REF>`, so the
# CUSTOMER messages US with the order they want to review. This is the inbound half of
# that door: recognise the reference, park it, and send the review Flow the exact same
# way a bare `review` already does.


def _auto_transcribe_voice_note(message_id: str, s3_key: str, request_id: str) -> None:
    """
    Async-invoke the whatsapp-voice Lambda to transcribe a voice note.
    The transcription result is stored back in the message record.
    Non-blocking (InvocationType='Event').
    """
    try:
        # Check if auto-transcribe is enabled in system config
        config_table = dynamodb.Table(
            os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
        )
        try:
            cfg_result = config_table.get_item(Key={'id': 'voice_language_config'})
            cfg_value = cfg_result.get('Item', {}).get('configValue', '{}')
            voice_config = json.loads(cfg_value) if isinstance(cfg_value, str) else cfg_value
            if not voice_config.get('autoTranscribe', True):
                return  # Auto-transcribe disabled
        except Exception:
            pass  # Default: auto-transcribe enabled

        transcribe_payload = {
            'requestContext': {'http': {'method': 'POST'}},
            'rawPath': '/whatsapp-voice/transcribe',
            'body': json.dumps({
                'messageId': message_id,
                's3Key': s3_key,
                'direction': 'INBOUND',
            })
        }

        response = lambda_client.invoke(
            FunctionName=WHATSAPP_VOICE_FUNCTION,
            InvocationType='Event',  # Async  -  don't block inbound processing
            Payload=json.dumps(transcribe_payload)
        )

        logger.info(json.dumps({
            'event': 'auto_transcribe_triggered',
            'messageId': message_id,
            's3Key': s3_key,
            'statusCode': response.get('StatusCode'),
            'requestId': request_id,
        }))

    except Exception as e:
        logger.warning(json.dumps({
            'event': 'auto_transcribe_error',
            'messageId': message_id,
            'error': str(e),
            'requestId': request_id,
        }))


# ============================================================================
# BOT FLOW CONFIGS (loaded from SystemConfigTable, dashboard-manageable)
# ============================================================================


def _link_media_to_service_request(contact_id: str, s3_key: str, media_type: str,
                                   filename: str, mime: str, request_id: str) -> None:
    """If the contact has a recent OPEN service request, copy the media into the
    request's private upload folder under the media bucket and append
    it to the request's attachments list so the team can service it from the dashboard."""
    if not contact_id or not s3_key:
        return
    try:
        c = dynamodb.Table(CONTACTS_TABLE).get_item(Key={'id': contact_id}).get('Item') or {}
        from lambda_utils.flow_inbox import active_submission
        req = active_submission(c, int(time.time()))
        if not req:
            return
        base = s3_key.split('/')[-1]
        dest_key = media_paths.SERVICE_REQUEST_UPLOAD_PREFIX + f"{req}/{int(time.time())}-{base}"
        try:
            s3.copy_object(Bucket=MEDIA_BUCKET, CopySource={'Bucket': MEDIA_BUCKET, 'Key': s3_key}, Key=dest_key)
        except Exception:
            dest_key = s3_key  # fall back to the original key if copy fails
        attachment = {
            'key': dest_key,
            'private': True,
            'type': media_type,
            'filename': filename or base,
            'mime': mime or '',
            'ts': int(time.time()),
        }
        try:
            dynamodb.Table(FLOW_SUBMISSIONS_TABLE).update_item(
                Key={'submissionId': req},
                UpdateExpression='SET attachments = list_append(if_not_exists(attachments, :empty), :a), updatedAt = :u',
                ConditionExpression='contactId = :cid',
                ExpressionAttributeValues={':a': [attachment], ':empty': [], ':u': int(time.time()), ':cid': contact_id},
            )
            logger.info(json.dumps({'event': 'service_request_attachment_added', 'submissionId': req,
                                    'key': dest_key, 'requestId': request_id}))
        except Exception as e:
            logger.warning(json.dumps({'event': 'service_request_attachment_error', 'error': str(e),
                                       'requestId': request_id}))
    except Exception as e:
        logger.warning(json.dumps({'event': 'link_media_error', 'error': str(e), 'requestId': request_id}))


def _link_flow_submission_to_order(reference_id: str, submission_id: str,
                                   canonical_address: Optional[Dict], request_id: str) -> None:
    """Write the flow's info back onto the ONE OrderTable row it belongs to.

    THE JOIN, in the only direction that is safe. The flow echoes a `reference_id`
    (`WD-PAY-...`), not the canonical OrderTable `orderId` (`WD-ORD-...`), so this resolves the
    order through the immutable CommerceKeys chain the payment already wrote:
    `PAYREF#<ref>` -> paymentAttemptId -> `PAYMENTATTEMPT#<attempt>` -> orderIdRef. That chain is
    the one `paid_submit_request` and the webhook use, so no new index and no trust in a
    customer-supplied id. When the order does not exist yet (a pending/failed attempt resolves to
    None) this is a no-op, which is the correct answer, not an error.

    What it writes onto the order: the flow `submissionId` (so the Order<->FlowSubmission join
    exists in BOTH directions — the submission already carries the reference), and the delivery
    address the flow collected (the canonical `checkoutDeliveryAddress` Map + the declared
    `shippingAddress` string column the schema already has). It NEVER touches the five money /
    identity keys the finalization conflict guard compares (`customerId`, `paymentAttemptId`,
    `providerPaymentId`, `snapshotHash`, `orderNumber`) — this is attribution and fulfilment data
    added beside the frozen record, conditional on the order existing so a race cannot create one.
    """
    if not reference_id:
        return
    try:
        keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
        payref = order_keys.resolve_payment_reference(keys, reference_id)
        attempt_id = str((payref or {}).get('paymentAttemptId') or '')
        claim = order_keys.resolve_order_for_payment(keys, attempt_id) if attempt_id else None
        order_id = str((claim or {}).get('orderIdRef') or '')
        if not order_id:
            # No order yet (pending/failed/legacy reference). The submission still stands on its
            # own; there is simply nothing to link to.
            return
        now = int(time.time())
        expr_names = {}
        expr_vals = {':sid': submission_id, ':ua': now}
        set_parts = ['flowSubmissionId=:sid', 'updatedAt=:ua']
        if canonical_address is not None:
            from lambda_utils.ecommerce import contact_address
            wf = contact_address.contact_write_fields(canonical_address, now=now)
            # `shippingAddress` is the declared OrderTable column; `checkoutDeliveryAddress` is the
            # same canonical Map the contact carries, so an order and its contact describe one
            # address, not two that can drift.
            expr_names['#cda'] = contact_address.ATTRIBUTE
            set_parts += ['shippingAddress=:sa', '#cda=:cda']
            expr_vals.update({':sa': wf['shippingAddress'],
                              ':cda': wf[contact_address.ATTRIBUTE]})
        kwargs = {
            'Key': {'orderId': order_id},
            'UpdateExpression': 'SET ' + ', '.join(set_parts),
            # Only an existing order is updated — never create one here. Finalization owns order
            # creation; this adds fulfilment data to a row that already committed.
            'ConditionExpression': 'attribute_exists(orderId)',
            'ExpressionAttributeValues': expr_vals,
        }
        if expr_names:
            kwargs['ExpressionAttributeNames'] = expr_names
        dynamodb.Table(shared_tables.orders_table_name()).update_item(**kwargs)
        logger.info(json.dumps({'event': 'flow_submission_linked_to_order', 'orderId': order_id,
                                'submissionId': submission_id, 'requestId': request_id}))
    except Exception as link_error:  # noqa: BLE001
        # The submission and the contact are already saved; failing to decorate the order must not
        # fail the whole post-pay handling or send the customer a second confirmation. Logged for
        # staff, swallowed here — the order record is still authoritative without this label.
        logger.warning(json.dumps({'event': 'flow_order_link_failed', 'referenceId': reference_id,
                                    'error': str(link_error)[:300], 'requestId': request_id}))


def _handle_postpay_submission(data: Dict, contact_id: str, sender_phone: str,
                               phone_number_id: str, request_id: str) -> None:
    """Handle a post-payment (endpointless) flow completion. The flow's 'complete'
    action returns reference_id + order/payment ids + the customer's details.
    Saves ONE submission per payment (idempotent, keyed on reference_id), links that
    submission and its address back onto the matching OrderTable row, and sends a
    confirmation message."""
    try:
        # New multi-screen flow uses request_id + order_number (+ full address/details).
        # Stay backward-compatible with the old payload (reference_id/delivery_note).
        request_sr_id = str(data.get('request_id', '')).strip()
        reference_id = str(data.get('reference_id') or data.get('order_number') or '').strip()
        if not request_sr_id and not reference_id:
            return
        now = int(time.time())
        # Key on the unique Request ID (falls back to reference for old payloads).
        sub_id = request_sr_id or f'postpay-{reference_id}'
        from lambda_utils.ecommerce import contact_address
        # ONE address shape: validate the flow's address fields through `contact_address` so the
        # contact back-write below stores the canonical Map, not a parallel flat row. `canonical`
        # is None when the flow carried no usable address (a service with no delivery) — the
        # submission row is still saved, only the contact address back-write is skipped.
        try:
            canonical = contact_address.normalize_for_storage(
                contact_address.map_meta_address(data))
        except contact_address.UnusableAddress:
            canonical = None
        # The human one-liner for the submission record. From the canonical Map when we have one,
        # else composed from the raw flow fields so an address-less service still reads sensibly.
        if canonical is not None:
            address_str = str(canonical.get('fullAddress') or '')
        else:
            addr_parts = [data.get('address', ''), data.get('landmark', ''), data.get('city', ''),
                          data.get('state', ''), data.get('pin', '')]
            address_str = ', '.join(str(p).strip() for p in addr_parts if str(p).strip())
        form = {k: v for k, v in data.items() if k not in ('flow_token',)}
        # Through the ONE FlowSubmissionTable writer. The explicit id keeps one row per request
        # (or per payment for the old payload), and the id doubles as the persisted token, so no
        # live Flow token is written. `formData` rides in `extra`, serialised as before, rather
        # than as `form_data`, so the promoted orderId stays the referenceId and is never a
        # payload field. Default ttl is the 365 days this row always had.
        from lambda_utils import flow_completion
        result = flow_completion.claim_completion(
            flow_token=sub_id, screen='DETAILS', flow_code='03.WD_POSTPAY_REQUEST',
            flow_type='service_request', phone=sender_phone, contact_id=contact_id or '',
            submission_id=sub_id, status='open', request_id=request_id,
            channel=flow_completion.CHANNEL_WHATSAPP,
            extra={
                'formData': json.dumps(form),
                'requestId': request_sr_id,
                'orderId': reference_id,
                'referenceId': reference_id,
                'orderNumber': str(data.get('order_number', '')),
                'product': str(data.get('product', '')),
                'amount': str(data.get('amount', '')),
                'customerName': str(data.get('name', '')),
                'shippingAddress': address_str,
                'addressLine1': str(data.get('address', '')),
                'city': str(data.get('city', '')),
                'state': str(data.get('state', '')),
                'postalCode': str(data.get('pin', '')),
                'landmark': str(data.get('landmark', '')),
                'description': str(data.get('description', '')),
                'deliveryNote': str(data.get('delivery_note', '')),
                'preferredTime': str(data.get('preferred_time', '')),
                'paymentStatus': 'paid',
            })
        if result.duplicate:
            logger.info(json.dumps({'event': 'postpay_submission_duplicate', 'submissionId': sub_id,
                                    'requestId': request_id}))
            return  # already recorded — do not send a second confirmation
        if not result.created:
            raise RuntimeError('post-payment request could not be saved')
        logger.info(json.dumps({'event': 'postpay_submission_saved', 'submissionId': sub_id,
                                'requestId2': request_sr_id, 'referenceId': reference_id,
                                'requestId': request_id}))
        # Link this submission + its address back onto the ONE OrderTable row (resolved through
        # the immutable PAYREF chain). After the idempotent put above, so a redelivered flow does
        # not re-link; before the contact write so the order and contact get one consistent
        # address in the same handling.
        _link_flow_submission_to_order(reference_id, sub_id, canonical, request_id)
        # Update the customer's saved address from the flow so future orders pre-fill.
        try:
            if contact_id:
                # Tag the contact with the open request so any media they send next
                # gets attached to THIS request. Also save the address for reuse.
                _uexpr = 'SET openServiceRequestId=:rid, openServiceRequestAt=:ua, updatedAt=:ua'
                _names = {}
                _vals = {':rid': sub_id, ':ua': now}
                if canonical is not None:
                    # Canonical Map + flat columns from the SAME normalised address, matching
                    # `_handle_address_submission` so the Address-Message path and the post-pay flow
                    # path leave an identical shape on the contact.
                    wf = contact_address.contact_write_fields(canonical, now=now)
                    _uexpr += (', shippingAddress=:sa, addressLine1=:al, addressLine2=:a2, city=:cy, '
                               '#st=:st, postalCode=:pc, landmark=:lm, #co=:co, #cda=:cda, #cau=:cau')
                    _names.update({'#st': 'state', '#co': 'country',
                                   '#cda': contact_address.ATTRIBUTE,
                                   '#cau': contact_address.UPDATED_ATTRIBUTE})
                    _vals.update({':sa': wf['shippingAddress'], ':al': wf['addressLine1'],
                                  ':a2': wf['addressLine2'], ':cy': wf['city'], ':st': wf['state'],
                                  ':pc': wf['postalCode'], ':lm': wf['landmark'], ':co': wf['country'],
                                  ':cda': wf[contact_address.ATTRIBUTE],
                                  ':cau': wf[contact_address.UPDATED_ATTRIBUTE]})
                _kwargs = {'Key': {'id': contact_id}, 'UpdateExpression': _uexpr,
                           'ExpressionAttributeValues': _vals}
                if _names:
                    _kwargs['ExpressionAttributeNames'] = _names
                dynamodb.Table(CONTACTS_TABLE).update_item(**_kwargs)
        except Exception:
            pass
    except Exception as e:
        logger.error(json.dumps({'event': 'postpay_submission_error', 'error': str(e), 'requestId': request_id}))


def _send_read_receipt(whatsapp_message_id: str, phone_number_id: str, request_id: str) -> None:
    """
    Send read receipt to WhatsApp per AWS docs.
    Per AWS: send-whatsapp-message with status='read' shows two blue check marks.
    """
    if not whatsapp_message_id:
        return
    
    try:
        # Build read receipt payload per Meta WhatsApp API
        read_receipt_payload = {
            'messaging_product': 'whatsapp',
            'message_id': whatsapp_message_id,
            'status': 'read'
        }
        
        logger.info(json.dumps({
            'event': 'read_receipt_payload',
            'messageId': whatsapp_message_id,
            'status': 'read',
            'requestId': request_id
        }))
        
        # Send read receipt via Direct API
        if _is_direct_api_phone(phone_number_id):
            meta_pid = _get_meta_phone_id_for_direct_api(phone_number_id)
            _rr = _send_direct_api_read_receipt(whatsapp_message_id, meta_phone_id=meta_pid)
        else:
            # Fallback: try Direct API with default phone
            _rr = _send_direct_api_read_receipt(whatsapp_message_id)

        # The callee returns a dict rather than raising, so `read_receipt_sent` used
        # to be emitted even when Meta refused the receipt.
        if _rr.get('error'):
            logger.warning(json.dumps({
                'event': 'read_receipt_failed',
                'messageId': whatsapp_message_id,
                'phoneNumberId': phone_number_id,
                'status': _rr.get('status'),
                'graphError': _graph_error_code(_rr.get('detail')),
                'requestId': request_id
            }))
        else:
            logger.info(json.dumps({
                'event': 'read_receipt_sent',
                'messageId': whatsapp_message_id,
                'phoneNumberId': phone_number_id,
                'statusCode': 200,
                'requestId': request_id
            }))
        
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'read_receipt_error',
            'messageId': whatsapp_message_id,
            'error': str(e),
            'requestId': request_id
        }))


# ============================================================================
# WHATSAPP BUSINESS ACCOUNT WEBHOOKS
# Template Status, Phone Quality, Messaging Limits
# ============================================================================

def _process_template_status(value: Dict, request_id: str) -> None:
    """
    Process template status update webhook.
    
    Webhook format:
    {
        "event": "APPROVED" | "REJECTED" | "PENDING" | "PAUSED" | "DISABLED" | "FLAGGED",
        "message_template_id": 123456789,
        "message_template_name": "template_name",
        "message_template_language": "en_US",
        "reason": "NONE" | "ABUSIVE_CONTENT" | "INVALID_FORMAT" | ...
    }
    
    Events:
    - APPROVED: Template approved and ready to use
    - REJECTED: Template rejected (check reason)
    - PENDING: Template submitted for review
    - PAUSED: Template paused due to quality issues
    - DISABLED: Template disabled
    - FLAGGED: Template flagged for review
    """
    event = value.get('event', '')
    template_id = value.get('message_template_id', '')
    template_name = value.get('message_template_name', '')
    template_language = value.get('message_template_language', '')
    reason = value.get('reason', 'NONE')
    
    logger.info(json.dumps({
        'event': 'template_status_update',
        'templateEvent': event,
        'templateId': template_id,
        'templateName': template_name,
        'templateLanguage': template_language,
        'reason': reason,
        'requestId': request_id
    }))
    
    # Store template status in SystemConfig table for dashboard display
    _store_system_event(
        event_type='template_status',
        event_data={
            'event': event,
            'templateId': str(template_id),
            'templateName': template_name,
            'templateLanguage': template_language,
            'reason': reason
        },
        request_id=request_id
    )
    
    # A template that cannot be sent. `template_status_alert` drives the
    # `wecare-whatsapp-template-status-alert` CloudWatch alarm
    # (scripts/provision_template_flow_alarms.py); `registered` says whether automation (payment,
    # invoice, order status, OTP, Vault) sends it, which is what makes a PAUSED one urgent.
    if event in ['REJECTED', 'PAUSED', 'DISABLED', 'FLAGGED']:
        logger.warning(json.dumps({
            'event': 'template_status_alert',
            'templateEvent': event,
            'templateId': str(template_id),
            'templateName': template_name,
            'registered': whatsapp_templates.by_name(template_name) is not None,
            'reason': reason,
            'action': 'Review template in Meta Business Manager',
            'requestId': request_id
        }))


#: Flow states a customer cannot open. BLOCKED/THROTTLED always need a person; DEPRECATED only
#: when the runtime still names the Flow (a planned retirement is not an incident).
_FLOW_ALERT_STATUSES = frozenset({'BLOCKED', 'THROTTLED'})
#: Health events Meta sends with alert_state ACTIVATED on a breach and DEACTIVATED on recovery.
_FLOW_HEALTH_EVENTS = frozenset({'CLIENT_ERROR_RATE', 'ENDPOINT_ERROR_RATE', 'ENDPOINT_LATENCY',
                                 'ENDPOINT_AVAILABILITY'})


def _process_flow_event(value: Dict, request_id: str) -> None:
    """Record one `flows` webhook and raise `flow_status_alert` when it stops customers.

    Meta sends FLOW_STATUS_CHANGE (DRAFT/PUBLISHED/DEPRECATED/BLOCKED/THROTTLED, sometimes with a
    version-freeze `warning`), the four endpoint/client health events and
    FLOW_VERSION_EXPIRY_WARNING. Every one is stored in the `flows` ring buffer the Workspace event
    view reads (waba-management GET /waba/events). The alert drives the
    `wecare-whatsapp-flow-status-alert` alarm. The payload names a Flow and its metrics only;
    nothing in it identifies a customer.
    """
    event = str(value.get('event') or '')
    flow_id = str(value.get('flow_id') or '')
    new_status = str(value.get('new_status') or '')
    alert_state = str(value.get('alert_state') or '')
    data = {key: value.get(key) for key in (
        'event', 'flow_id', 'old_status', 'new_status', 'alert_state', 'threshold', 'error_rate',
        'p50_latency', 'p90_latency', 'availability', 'requests_count')
        if value.get(key) not in (None, '')}
    errors = value.get('errors')
    if isinstance(errors, list):
        data['errors'] = [{k: e.get(k) for k in ('error_type', 'error_rate', 'error_count')}
                          for e in errors[:10] if isinstance(e, dict)]
    if value.get('warning'):
        data['warning'] = str(value.get('warning'))[:300]
    in_use = published_flow_by_id(flow_id) is not None

    logger.info(json.dumps({'event': 'flow_webhook', 'flowEvent': event, 'flowId': flow_id,
                            'newStatus': new_status, 'alertState': alert_state,
                            'inUse': in_use, 'requestId': request_id}))
    _store_system_event(event_type='flows', event_data=data, request_id=request_id)

    alert = ((event == 'FLOW_STATUS_CHANGE'
              and (new_status in _FLOW_ALERT_STATUSES or (new_status == 'DEPRECATED' and in_use)))
             or (event in _FLOW_HEALTH_EVENTS and alert_state == 'ACTIVATED')
             or event == 'FLOW_VERSION_EXPIRY_WARNING' or bool(value.get('warning')))
    if alert:
        logger.warning(json.dumps({
            'event': 'flow_status_alert',
            'flowEvent': event,
            'flowId': flow_id,
            'newStatus': new_status,
            'alertState': alert_state,
            'inUse': in_use,
            'message': str(value.get('message') or '')[:200],
            'action': 'Review the Flow in WhatsApp Manager > Flows',
            'requestId': request_id,
        }))


def _process_phone_quality_update(value: Dict, request_id: str) -> None:
    """
    Process phone number quality update webhook.
    
    Webhook format:
    {
        "display_phone_number": "+1234567890",
        "current_limit": "TIER_1K" | "TIER_10K" | "TIER_100K" | "TIER_UNLIMITED",
        "event": "FLAGGED" | "UNFLAGGED",
        "quality_score": "GREEN" | "YELLOW" | "RED"
    }
    
    Quality scores:
    - GREEN: High quality, no issues
    - YELLOW: Medium quality, some issues
    - RED: Low quality, at risk of being blocked
    
    Events:
    - FLAGGED: Phone number flagged due to quality issues
    - UNFLAGGED: Phone number quality restored
    """
    display_phone = value.get('display_phone_number', '')
    current_limit = value.get('current_limit', '')
    event = value.get('event', '')
    quality_score = value.get('quality_score', '')
    
    logger.info(json.dumps({
        'event': 'phone_quality_update',
        'displayPhone': mask_phone(display_phone),
        'currentLimit': current_limit,
        'qualityEvent': event,
        'qualityScore': quality_score,
        'requestId': request_id
    }))
    
    # Store phone quality in SystemConfig table
    _store_system_event(
        event_type='phone_quality',
        event_data={
            'displayPhone': display_phone,
            'currentLimit': current_limit,
            'event': event,
            'qualityScore': quality_score
        },
        request_id=request_id
    )
    
    # Log warning for quality issues
    if quality_score in ['YELLOW', 'RED'] or event == 'FLAGGED':
        logger.warning(json.dumps({
            'event': 'phone_quality_alert',
            'displayPhone': mask_phone(display_phone),
            'qualityScore': quality_score,
            'qualityEvent': event,
            'action': 'Review message quality and reduce spam complaints',
            'requestId': request_id
        }))


def _process_account_update(value: Dict, request_id: str) -> None:
    """
    Process account update webhook (messaging limits, restrictions, etc.).
    
    Webhook format for messaging limit changes:
    {
        "phone_number": "+1234567890",
        "event": "PHONE_NUMBER_MESSAGING_LIMIT_CHANGED",
        "current_limit": "TIER_1K" | "TIER_10K" | "TIER_100K" | "TIER_UNLIMITED"
    }
    
    Webhook format for account restrictions:
    {
        "event": "ACCOUNT_RESTRICTION",
        "restriction_type": "RESTRICTED_ADD_PHONE_NUMBER_ACTION" | ...
    }
    
    Messaging limit tiers:
    - TIER_1K: 1,000 business-initiated conversations per 24 hours
    - TIER_10K: 10,000 business-initiated conversations per 24 hours
    - TIER_100K: 100,000 business-initiated conversations per 24 hours
    - TIER_UNLIMITED: Unlimited business-initiated conversations
    """
    event = value.get('event', '')
    phone_number = value.get('phone_number', '')
    current_limit = value.get('current_limit', '')
    restriction_type = value.get('restriction_type', '')
    ban_info = value.get('ban_info', {})
    
    logger.info(json.dumps({
        'event': 'account_update',
        'accountEvent': event,
        'phoneNumber': mask_phone(phone_number),
        'currentLimit': current_limit,
        'restrictionType': restriction_type,
        'banInfo': ban_info,
        'requestId': request_id
    }))
    
    # Store account update in SystemConfig table
    _store_system_event(
        event_type='account_update',
        event_data={
            'event': event,
            'phoneNumber': phone_number,
            'currentLimit': current_limit,
            'restrictionType': restriction_type,
            'banInfo': ban_info
        },
        request_id=request_id
    )
    
    # Log messaging limit changes
    if event == 'PHONE_NUMBER_MESSAGING_LIMIT_CHANGED':
        logger.info(json.dumps({
            'event': 'messaging_limit_changed',
            'phoneNumber': mask_phone(phone_number),
            'newLimit': current_limit,
            'requestId': request_id
        }))
    
    # Log warnings for restrictions
    if event == 'ACCOUNT_RESTRICTION' or restriction_type:
        logger.warning(json.dumps({
            'event': 'account_restriction_alert',
            'restrictionType': restriction_type,
            'action': 'Review account in Meta Business Manager',
            'requestId': request_id
        }))
    
    # Log ban info if present
    if ban_info:
        logger.error(json.dumps({
            'event': 'account_ban_alert',
            'banInfo': ban_info,
            'action': 'Contact Meta support immediately',
            'requestId': request_id
        }))


#: Meta `user_preferences` (category marketing_messages) value -> consent ledger state.
_MARKETING_PREFERENCE_STATES = {
    'stop': consent_evidence.OPTED_OUT,
    'resume': consent_evidence.OPTED_IN,
}


def _append_consent_record(table, contact: Dict, record: Dict) -> None:
    """Append one record to a contact's consent ledger without losing a concurrent append."""
    contact_id = contact_key.resolve(contact)
    for attempt in range(2):
        stored = contact.get(consent_evidence.ATTRIBUTE)
        ledger = consent_evidence.append(contact, record)
        if ledger == consent_evidence.ledger_of(contact):
            return  # a redelivery: this exact record is already the latest
        values = {':ledger': ledger, ':now': int(time.time())}
        if isinstance(stored, list):
            condition = 'attribute_exists(id) AND size(#ledger) = :n'
            values[':n'] = len(stored)
        else:
            condition = 'attribute_exists(id) AND attribute_not_exists(#ledger)'
        try:
            table.update_item(
                Key=contact_key.key(contact_id),
                UpdateExpression='SET #ledger = :ledger, updatedAt = :now',
                ConditionExpression=condition,
                ExpressionAttributeNames={'#ledger': consent_evidence.ATTRIBUTE},
                ExpressionAttributeValues=values,
            )
            return
        except ClientError as exc:
            if attempt or exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
        contact = table.get_item(Key=contact_key.key(contact_id), ConsistentRead=True).get('Item')
        if not contact:
            return


def _record_marketing_preferences(value: Dict, metadata: Dict, meta_waba_ids: list,
                                  request_id: str) -> None:
    """Write Meta's marketing stop/resume to the contact's consent ledger.

    `stop` appends OPTED_OUT and `resume` OPTED_IN (source CUSTOMER_REQUEST, at = Meta's
    timestamp), the records outbound MARKETING sends read. A preference for a number with no
    contact is skipped: a MARKETING send to it is refused anyway. Store errors and an
    ambiguous identity raise, so the caller parks the change for replay.
    """
    table = dynamodb.Table(CONTACTS_TABLE)
    for pref in value.get('user_preferences') or []:
        if not isinstance(pref, dict) or pref.get('category') != 'marketing_messages':
            continue
        choice = str(pref.get('value') or '').strip().lower()
        state = _MARKETING_PREFERENCE_STATES.get(choice)
        if not state:
            continue
        phone = str(pref.get('wa_id') or '').strip()
        bsuid = str(pref.get('user_id') or '').strip()
        if phone:
            contact = contact_store.lookup(table, phone)
        elif bsuid:
            contact = _find_scoped_bsuid(
                table, bsuid, _message_account_id(metadata, meta_waba_ids, needs_bsuid=True))
        else:
            contact = None
        if not contact:
            logger.info(json.dumps({'event': 'marketing_preference_no_contact', 'value': choice,
                                    'phone': mask_phone(phone), 'requestId': request_id}))
            continue
        try:
            at = int(pref.get('timestamp') or 0)
        except (TypeError, ValueError):
            at = 0
        record = consent_evidence.build_record(
            channel='WHATSAPP', state=state, source='CUSTOMER_REQUEST',
            at=at if at > 0 else int(time.time()), purpose=consent_evidence.MARKETING,
            reference=f'meta:user_preferences:{choice}')
        _append_consent_record(table, contact, record)
        logger.info(json.dumps({'event': 'marketing_preference_recorded', 'state': state,
                                'contactId': mask_contact_id(contact_key.resolve(contact)),
                                'requestId': request_id}))


def _store_system_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """
    Store system event in SystemConfig table for dashboard display.
    Uses a composite key: whatsapp_events_{event_type}
    Stores last 10 events of each type.
    
    Note: SystemConfigTable PK is 'id', we use id=configKey for compatibility.
    """
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        config_key = f'whatsapp_events_{event_type}'
        now = int(time.time())
        
        # Get existing events (PK is 'id')
        try:
            response = config_table.get_item(Key={'id': config_key})
            existing = response.get('Item', {})
            events_list = json.loads(existing.get('configValue', '[]'))
        except Exception:
            events_list = []
        
        # Add new event with timestamp
        new_event = {
            'timestamp': now,
            'data': event_data
        }
        events_list.insert(0, new_event)
        
        # Keep only last 10 events
        events_list = events_list[:10]
        
        # Store updated events (PK is 'id')
        config_table.put_item(Item={
            'id': config_key,
            'configKey': config_key,
            'configValue': json.dumps(events_list),
            'updatedAt': Decimal(str(now))
        })
        
        logger.info(json.dumps({
            'event': 'system_event_stored',
            'eventType': event_type,
            'configKey': config_key,
            'eventsCount': len(events_list),
            'requestId': request_id
        }))
        
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        # SystemConfig table doesn't exist - skip silently
        logger.warning(json.dumps({
            'event': 'system_event_store_skipped',
            'eventType': event_type,
            'reason': 'SystemConfig table not found',
            'requestId': request_id
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'system_event_store_error',
            'eventType': event_type,
            'error': str(e),
            'requestId': request_id
        }))


def _process_group_event(value: Dict, event_subtype: str, request_id: str) -> None:
    """
    Process group webhook events and update WhatsAppGroup table.
    Handles: group_participant_change, group_membership_approval_request.
    Per Meta Groups API docs.
    """
    try:
        GROUP_TABLE = os.environ.get('GROUP_TABLE', 'stack-wecare-digital-WhatsAppGroupTable')
        group_table = dynamodb.Table(GROUP_TABLE)
        now = int(time.time())

        # Extract group info from webhook value
        groups = value.get('groups', [value]) if isinstance(value.get('groups'), list) else [value]
        for group_data in groups:
            group_id = group_data.get('group_id', group_data.get('id', ''))
            if not group_id:
                continue

            subject = group_data.get('subject', '')
            participants = group_data.get('participants', [])
            action = group_data.get('action', event_subtype)

            # Upsert group record
            update_expr = 'SET updatedAt = :now'
            expr_vals: Dict[str, Any] = {':now': Decimal(str(now))}

            if subject:
                update_expr += ', subject = :subj'
                expr_vals[':subj'] = subject
            if participants:
                update_expr += ', lastParticipantEvent = :pe'
                expr_vals[':pe'] = json.dumps({
                    'action': action,
                    'participants': participants[:20],  # Limit stored participants
                    'timestamp': now,
                })

            try:
                group_table.update_item(
                    Key={'id': group_id},
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_vals,
                )
            except Exception:
                # Table may not exist yet  -  create item instead
                group_table.put_item(Item={
                    'id': group_id,
                    'groupId': group_id,
                    'subject': subject,
                    'lastParticipantEvent': json.dumps({
                        'action': action,
                        'participants': participants[:20],
                        'timestamp': now,
                    }),
                    'createdAt': Decimal(str(now)),
                    'updatedAt': Decimal(str(now)),
                })

            logger.info(json.dumps({
                'event': 'group_event_processed',
                'groupId': group_id,
                'action': action,
                'participantCount': len(participants),
                'requestId': request_id,
            }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'group_event_processing_error',
            'error': str(e),
            'requestId': request_id,
        }))
