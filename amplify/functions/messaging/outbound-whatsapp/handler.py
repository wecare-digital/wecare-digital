"""
Outbound WhatsApp Lambda Function

Purpose: Send WhatsApp text/media messages
Requirements: 3.1, 3.2, 5.2-5.11, 14.4, 16.2-16.6

Validates opt-in and allowlist, checks customer service window,
calls Meta Graph API (Direct API) for all phones.
Emits CloudWatch metrics for delivery success/failure.
"""

import os
import json
import secrets
import uuid
import time
import logging
import hashlib
import boto3
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal, InvalidOperation
from botocore.exceptions import ClientError

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_headers, extract_origin
from lambda_utils.privacy import mask_phone, mask_contact_id, redact_pii  # contactId is `wa` + the customer's digits
# Aliased for the same reason as in the inbound handler: `payment_status` is a local variable
# holding a provider's raw word, and this is the module that says what the word means.
from lambda_utils import payment_status as pay_status
from lambda_utils.middleware import require_auth
from lambda_utils.message_store import put_message  # unified MessagesTable dual-write
from lambda_utils import graph_errors  # Meta error subcode + transient classification
from lambda_utils import live_smoke  # WA_LIVE_SMOKE_TEST recipient lockdown
from lambda_utils import direct_send  # Direct Send flag + WABA map, fails closed
from lambda_utils import contact_key, contact_store, identity_claims
from lambda_utils import template_status
from lambda_utils.template_media import fixed_image_header, ORDER_CATALOG_HEADER_IMAGE, DEFAULT_ORDER_ITEM_THUMBNAIL
from lambda_utils.identity import subscriber_id, consent as consent_evidence  # canonical identity + evidence ledger
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
# One source for Meta's reference_id contract, so the send path and the minter cannot disagree.
from lambda_utils.ecommerce import order_keys
REFERENCE_ID_MAX_LENGTH = order_keys.META_REFERENCE_ID_MAX_LENGTH
# A0 — the readiness gate at the payment-request chokepoint. `payment_readiness` proves the
# configuration and the approved template against a LIVE provider read; `wa_payment_request` is
# imported for `PAYMENT_SENDERS`, so the gate and the caller-side module cannot disagree about
# which sender may collect.
#
# On the note at wa_payment_request.py:74-79 ("a literal rather than an import because the
# resolver must not depend on the `ecommerce` package"): that scopes to `_build_payment_settings`,
# which keeps its own literal `PAYMENT_SENDERS` and gains no import. This module already imports
# `lambda_utils.ecommerce.order_keys` above, and
# tests/test_whatsapp_payments_are_template_only.py already imports both modules together to pin
# the two sets equal, so the import direction is established practice.
from lambda_utils import payment_readiness
from lambda_utils.ecommerce import wa_payment_request, business_identity, checkout_pricing
# The one home for approved template names/languages. Reading PAY/ORDER_STATUS from here means
# the gate, the sender and the registry cannot name different templates; env overrides still win.
from lambda_utils import whatsapp_templates
# The one discount: the fixed "Delight" policy. Imported for its CANONICAL label only — this
# handler never computes the figure, it only labels the amount the authoritative checkout already
# computed server-side. `DELIGHT_CODE`/`DISPLAY_LABEL` are the single source for the code the
# invoice/order row stores and the string the sheet must print, so the two cannot drift.
from lambda_utils.ecommerce import default_coupon

logger = get_logger(__name__)


def _discount_description(order_data: dict) -> str:
    """The customer-facing label for the `order_details` discount row.

    Only the fixed DELIGHT policy is named "Delight", and it is named from the ONE canonical
    string (`default_coupon.DISPLAY_LABEL`) rather than a literal here, so the sheet, the receipt
    and the stored row cannot disagree. The gate is the stored `couponCode` the authoritative
    checkout wrote (`DELIGHT`), never the amount: a non-zero discount is not proof it was Delight.

    Any other discounted order — a legacy invoice whose discount predates this policy — keeps the
    description it carried, or a generic "Discount" if it carried none. It is deliberately NOT
    labelled "Delight", because calling an unknown legacy discount by the policy's name would be a
    false statement on a payment sheet.
    """
    if str(order_data.get('couponCode') or '').strip().upper() == default_coupon.DELIGHT_CODE:
        return default_coupon.DISPLAY_LABEL
    return str((order_data.get('discount') or {}).get('description') or '').strip() or 'Discount'

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
cloudwatch = boto3.client('cloudwatch', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
SEND_MODE = os.environ.get('SEND_MODE', 'LIVE')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
MEDIA_FILES_TABLE = os.environ.get('MEDIA_FILES_TABLE', 'stack-wecare-digital-MediaFilesTable')
RATE_LIMIT_TABLE = os.environ.get('RATE_LIMIT_TABLE', 'stack-wecare-digital-RateLimitTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
MEDIA_PREFIX = os.environ.get('MEDIA_OUTBOUND_PREFIX',
                              media_paths.WHATSAPP_OUTGOING_PREFIX)
# Public, reusable template-attachment folder (same bucket). Files here are served
# via CloudFront so WhatsApp can fetch them by URL and the same attachment can be
# re-sent across many template messages without re-uploading to Meta each time.
#
# Canonical home: `secure/d/public/whatsapp/wa-tpl/{img,docs,vid,aud,stk}/`, the subtree
# the edge serves publicly. The old default composed `o/public/wa-tpl/`, a retired tree with
# no current objects, so reusable uploads landed outside the layout and outside the library
# whatsapp-template-management lists. Keep this equal to that handler's PUBLIC_MEDIA_PREFIX.
PUBLIC_MEDIA_PREFIX = os.environ.get('PUBLIC_MEDIA_PREFIX',
                                     media_paths.WHATSAPP_TEMPLATE_ASSET_ROOT)
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)

# WhatsApp Phone Number IDs (Allowlist) - Requirement 3.2
PHONE_NUMBER_ID_1 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE_NUMBER_ID_2 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')
ALLOWLIST = {PHONE_NUMBER_ID_1, PHONE_NUMBER_ID_2}

# All phones use Direct Meta Graph API
DIRECT_API_PHONE_IDS = {PHONE_NUMBER_ID_1, PHONE_NUMBER_ID_2}
# Meta phone ID for Direct API sending
DIRECT_API_META_PHONE_MAP = {
    'phone-number-id-waba1-direct-1016149501586345': '1016149501586345',  # +91 93309 94400 (WABA1)
    'phone-number-id-waba-t-direct-1055232054343117': '1055232054343117',  # +91 99033 00044 (WABA-T)
}
# Meta phone-number id -> WABA id. Bound to the shared module rather than copied,
# because Direct Send eligibility is granted per WABA and a second copy of this
# mapping is a second thing to get wrong. The data lives in
# lambda_utils/direct_send.py; this is the briefed name at the briefed place.
META_PHONE_TO_WABA = direct_send.META_PHONE_TO_WABA

# Secrets Manager for Direct API tokens
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
_direct_api_cache = {}

def _is_direct_api_phone(phone_number_id: str) -> bool:
    """Check if phone uses Direct API. All phones are now Direct API."""
    return phone_number_id in DIRECT_API_PHONE_IDS


# Known template -> flow-key map so template-launched Flows get a *routable*
# flow_token. The flow-data endpoint routes by the token prefix and extracts the
# recipient phone from the "-ph-" segment; a bare "unused" token is unroutable
# and silently breaks flow submission (e.g. the subscribe REVIEW step).
_TEMPLATE_FLOW_KEYS = {
    '01_wecare_doc': 'subscribe', '02_wecare_video': 'subscribe', '03_wecare_images_': 'subscribe',
    '01_manish_doc': 'subscribe', '02_manish_video': 'subscribe', '03_manish_image': 'subscribe',
    # F002's manual template is approved with DATA_EXCHANGE. It uses a static
    # FEEDBACK INIT; the server-authenticated sender owns the later nfm_reply.
    # The paid invoice instead supplies its own opaque review-* attribution token.
    'wecare_leave_review': 'leave',
}


def _infer_flow_key_from_template(template_name: str) -> str:
    """Best-effort flow-key for a template's Flow button, used to build a routable
    flow_token when the caller doesn't supply one."""
    if not template_name:
        return ''
    name = str(template_name).strip().lower()
    if name in _TEMPLATE_FLOW_KEYS:
        return _TEMPLATE_FLOW_KEYS[name]
    if 'subscribe' in name or 'profile' in name:
        return 'subscribe'
    return ''

# Auto 👍 reaction: when enabled, every outbound message/template gets a thumbs-up
# reaction from the same phone that sent it. Resolved at runtime from SystemConfig
# (id='whatsapp_auto_thumb', cached) with the env var as the default. Default ON.
AUTO_THUMB_REACTION_ENABLED = os.environ.get('AUTO_THUMB_REACTION_ENABLED', 'true').strip().lower() in ('true', '1', 'yes', 'on')
AUTO_THUMB_EMOJI = os.environ.get('AUTO_THUMB_EMOJI', '\U0001F44D')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
_auto_thumb_cache = {'value': None, 'ts': 0.0}
_AUTO_THUMB_CACHE_TTL = 300  # seconds — admin toggles propagate within 5 min


def _auto_thumb_enabled() -> bool:
    """Runtime auto 👍 toggle. Reads SystemConfig 'whatsapp_auto_thumb' at most once
    per _AUTO_THUMB_CACHE_TTL seconds (cached to avoid per-message latency); falls
    back to the AUTO_THUMB_REACTION_ENABLED env default if unset/unreadable."""
    now = time.time()
    if _auto_thumb_cache['value'] is not None and (now - _auto_thumb_cache['ts']) < _AUTO_THUMB_CACHE_TTL:
        return _auto_thumb_cache['value']
    val = AUTO_THUMB_REACTION_ENABLED
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': 'whatsapp_auto_thumb'}).get('Item')
        if item and 'configValue' in item:
            val = str(item.get('configValue')).lower() in ('true', '1', 'yes', 'on')
    except Exception as e:
        logger.warning(f"auto_thumb config read failed (using default {val}): {e}")
    _auto_thumb_cache['value'] = val
    _auto_thumb_cache['ts'] = now
    return val


def _post_reaction_direct(meta_phone_id: str, token: str, app_secret: str,
                          to: str, message_id: str) -> None:
    """Low-level 👍 reaction POST to the Graph API, reusing an already-resolved
    meta_phone_id + token. Sent from the SAME phone that owns message_id (required
    for the wamid to resolve). Best-effort; never raises."""
    if not (meta_phone_id and to and message_id):
        return
    import hmac as _hmac, hashlib as _hashlib
    import urllib.request, urllib.error
    payload = json.dumps({
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'reaction',
        'reaction': {'message_id': message_id, 'emoji': AUTO_THUMB_EMOJI},
    })
    url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/messages"
    if app_secret:
        proof = _hmac.new(app_secret.encode(), token.encode(), _hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    req = urllib.request.Request(url, data=payload.encode(), headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        logger.info(json.dumps({'event': 'auto_thumb_reaction_sent',
                                'metaPhoneId': meta_phone_id, 'wamid': message_id}))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8') if e.fp else ''
        logger.warning(json.dumps({'event': 'auto_thumb_reaction_failed',
                                   'wamid': message_id, 'code': e.code, 'error': body[:200]}))
    except Exception as e:
        logger.warning(json.dumps({'event': 'auto_thumb_reaction_error',
                                   'wamid': message_id, 'error': str(e)[:200]}))


class SmokeTestRecipientBlocked(RuntimeError):
    """WA_LIVE_SMOKE_TEST is on and the recipient is not WA_QA_RECIPIENT.

    Raised at the wire, immediately before the Graph call, so that no branch -
    including one added later - can reach a customer while smoke mode is on. The
    handler checks the same rule earlier and returns a clean 403; this is the
    backstop that makes the earlier check an optimisation rather than the
    guarantee.
    """


def _assert_smoke_recipient_allowed(to: Optional[str], where: str) -> None:
    """Refuse a Graph send to anyone but the QA recipient while in smoke mode.

    `to` absent means the payload carries no recipient phone (a BSUID-only send,
    or an endpoint like block_users/typing that addresses something else). Those
    are still refused in smoke mode, because "we could not tell who this reaches"
    is not a reason to let a live test through.
    """
    allowed, reason = live_smoke.check_recipient(to)
    if allowed:
        return
    logger.error(json.dumps({
        'event': 'smoke_mode_send_blocked',
        'where': where,
        'reason': reason,
        'to': mask_phone(to or ''),
        **live_smoke.describe(),
    }))
    raise SmokeTestRecipientBlocked(reason)


def _send_direct_api(phone_number_id: str, message_json: str) -> Dict:
    """Send message via Meta Graph API for Direct API phones."""
    import hmac as _hmac, hashlib as _hashlib
    if live_smoke.is_smoke_mode():
        try:
            _payload = json.loads(message_json) if isinstance(message_json, str) else (message_json or {})
        except (TypeError, ValueError):
            _payload = {}
        _assert_smoke_recipient_allowed(
            (_payload.get('to') if isinstance(_payload, dict) else None),
            'send_direct_api',
        )
    if 'token' not in _direct_api_cache:
        resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
        data = json.loads(resp['SecretString'])
        _direct_api_cache['token'] = (data.get('access_token') or '').strip()
        _direct_api_cache['app_secret'] = (data.get('app_secret') or '').strip()
    
    token = _direct_api_cache['token']
    app_secret = _direct_api_cache['app_secret']
    meta_phone_id = DIRECT_API_META_PHONE_MAP.get(phone_number_id, '')
    
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/messages"
    if app_secret:
        proof = _hmac.new(app_secret.encode(), token.encode(), _hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    
    import urllib.request, urllib.error
    req = urllib.request.Request(url, data=message_json.encode() if isinstance(message_json, str) else message_json, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read().decode())
        msg_id = result.get('messages', [{}])[0].get('id', '')
        wa_id = ( result.get('contacts') or [ {} ] )[0].get('wa_id', '')
        # Auto 👍 reaction on every outbound message/template (best-effort, never
        # blocks the send). Skip reaction-type sends to prevent recursion/noise.
        if msg_id and _auto_thumb_enabled():
            try:
                _pj = json.loads(message_json) if isinstance(message_json, str) else (message_json or {})
                if isinstance(_pj, dict) and _pj.get('type') != 'reaction' and _pj.get('to'):
                    _post_reaction_direct(meta_phone_id, token, app_secret, _pj.get('to', ''), msg_id)
            except Exception:
                pass  # reaction is best-effort; never affect the primary send result
        return {'messageId': msg_id, 'waId': wa_id}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        # Classified, redacted fields only: Meta's details can echo the request.
        logger.error(json.dumps({'event': 'direct_api_send_failed', 'metaPhoneId': meta_phone_id,
                                 **graph_errors.log_fields(error_body, e.code)}))
        # The body can be read once. Callers that classify the failure (`_handle_live_send`)
        # read it from here; re-reading the exhausted stream gave them '' and no Meta code.
        e.meta_error_body = error_body
        raise


def _send_message(phone_number_id: str, payload, as_bytes=False) -> Dict:
    """Universal send — all phones use Direct Meta API."""
    msg = json.dumps(payload) if not isinstance(payload, str) else payload
    return _send_direct_api(phone_number_id, msg)

class UnresolvedSenderPhone(ValueError):
    """The sending phone could not be resolved, so nothing was sent.

    Raised instead of falling back to a default sender. See
    _resolve_meta_phone_id.
    """


def _resolve_meta_phone_id(phone_number_id: str) -> str:
    """Resolve our phone id to the Meta phone-number id used in Graph URLs.

    FAILS CLOSED. There used to be a last-resort default to WABA2's phone
    ('1055232054343117', commented "the working one"). That is a cross-WABA
    bypass with three consequences, none of them visible at the call site:

      1. A customer who messaged Phone 1 was answered by Phone 2 - a number they
         never contacted. From their side it is an unsolicited message from a
         stranger.
      2. It leaves the 24-hour customer service window. The window belongs to
         the conversation the customer opened on THAT number; a free-form reply
         from the other number has no open window and Meta rejects it, or bills
         it as a new conversation.
      3. It contradicts the "NEVER cross-WABA" rule asserted throughout this
         codebase, including in the payment handlers, while silently doing the
         opposite.

    Refusing to send is the safe failure. A message that does not go out is a
    visible bug someone fixes; a message that goes out from the wrong business
    number is a support incident and a billing surprise.
    """
    meta_phone_id = DIRECT_API_META_PHONE_MAP.get(phone_number_id, '')
    # The Direct API id embeds the Meta phone id, so deriving it is exact rather
    # than a guess - keep this, it is not a fallback.
    if not meta_phone_id and '-direct-' in phone_number_id:
        candidate = phone_number_id.split('-direct-')[-1]
        if candidate.isdigit():
            meta_phone_id = candidate
    if not meta_phone_id:
        raise UnresolvedSenderPhone(
            f'cannot resolve a Meta sender phone for {phone_number_id!r}; '
            'refusing to send rather than fall back to another WABA'
        )
    return meta_phone_id


def _waba_for_sender(phone_number_id: str) -> str:
    """Our phone id -> the WABA id that owns it, or `''` when it cannot be resolved.

    Reuses `_resolve_meta_phone_id` rather than re-deriving, so there is exactly
    one place that decides which Meta phone a send leaves from. That function
    already fails closed by raising, and this one converts the refusal to `''`
    because the caller's question is "is Direct Send enabled here", for which
    "we do not know" and "no" must have the same answer.

    Never guesses. An empty result means the caller logs
    `direct_send_waba_unresolved` and keeps today's behaviour.
    """
    try:
        meta_phone_id = _resolve_meta_phone_id(phone_number_id)
    except UnresolvedSenderPhone:
        return ''
    return direct_send.waba_for_meta_phone(meta_phone_id)

def _block_users_api(phone_number_id: str, users: list, action: str) -> Dict:
    """Block / unblock / list blocked users via the Meta block_users endpoint.

    action: 'block' (POST), 'unblock' (DELETE), 'list' (GET).
    Note (Meta): you can only block a user who messaged the business in the last 24h.
    """
    import hmac as _hmac, hashlib as _hashlib
    import urllib.request, urllib.error
    if 'token' not in _direct_api_cache:
        resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
        data = json.loads(resp['SecretString'])
        _direct_api_cache['token'] = (data.get('access_token') or '').strip()
        _direct_api_cache['app_secret'] = (data.get('app_secret') or '').strip()
    token = _direct_api_cache['token']
    app_secret = _direct_api_cache['app_secret']
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)
    url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/block_users"
    if app_secret:
        proof = _hmac.new(app_secret.encode(), token.encode(), _hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    method = 'GET' if action == 'list' else ('DELETE' if action == 'unblock' else 'POST')
    body = None
    if action in ('block', 'unblock'):
        body = json.dumps({
            'messaging_product': 'whatsapp',
            'block_users': [{'user': _normalize_phone_number(u)} for u in users if u],
        }).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        # A block_users error can echo the customer's number, so neither the log nor the
        # exception (which reaches the API response) carries the raw body.
        fields = graph_errors.log_fields(error_body, e.code)
        logger.error(json.dumps({'event': 'block_users_failed', 'action': action, **fields}))
        raise Exception(f"HTTP {e.code}: {fields['metaMessage'] or 'block_users failed'}")

# Constants
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
MAX_TEXT_LENGTH = 4096  # Requirement 5.4
MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
CUSTOMER_SERVICE_WINDOW_HOURS = 24  # Requirement 16.2

# The status a row gets the moment Meta's send response returns 200.
#
# It used to be 'sent'. That claimed something Meta had not said: the send
# response carries messages[0].id and, where present, message_status "accepted".
# Writing 'sent' at that point manufactures a delivery signal from an
# acknowledgement, and it also masked the ordering bug in _process_status,
# because the row was never in a state that a real 'sent' webhook would advance.
#
# The HTTP response body still reports 'sent', deliberately: three frontend call
# sites treat `result.status === 'sent'` as the success boolean
# (dm/inbox, dm/sms, dm/broadcast). Those mean "the API accepted it", which is
# true. Only the persisted lifecycle needed correcting.
WA_INITIAL_STATUS = 'accepted'

# A caller that owns a durable business idempotency claim can also pass a stable key down to the
# final Meta send boundary. We hash it before using it as a DynamoDB/message id: the raw key can
# contain invoice/reference identifiers and does not belong in logs or customer-facing records.
# This is defense-in-depth, not the primary lock: payment/invoice callers still claim their
# business action in CommerceKeys/PaymentAttempts before invoking outbound.
IDEMPOTENCY_KEY_MAX_LENGTH = 256

def _stable_outbound_message_id(idempotency_key: str) -> str:
    key = str(idempotency_key or '').strip()
    if not key:
        return str(uuid.uuid4())
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH or any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
        raise ValueError('invalid idempotency key')
    return 'wa-idem-' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:40]


def _claim_keyed_outbound_send(message_id: str, request_id: str) -> Tuple[str, str]:
    """Atomically reserve a keyed send before any provider side effect.

    A successful provider acknowledgement is immutable. Definite failures may be retried by the
    same key; sending/accepted/unknown rows stay blocked until reconciliation. There is no
    time-based auto-reclaim because an expired local lease does not prove Meta rejected the send.
    """
    now = int(time.time())
    table = dynamodb.Table(MESSAGES_TABLE)
    try:
        table.update_item(
            Key={'id': message_id},
            UpdateExpression=(
                'SET messageId = if_not_exists(messageId, :mid), #s = :sending, '
                'sendClaimOwner = :owner, sendClaimAt = :now, '
                'createdAt = if_not_exists(createdAt, :now), '
                'expiresAt = if_not_exists(expiresAt, :ttl)'
            ),
            ConditionExpression=(
                'attribute_not_exists(id) OR #s = :failed OR #s = :rejected'
            ),
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':mid': message_id,
                ':sending': 'sending',
                ':failed': 'failed',
                ':rejected': 'rejected',
                ':owner': request_id,
                ':now': Decimal(str(now)),
                ':ttl': Decimal(str(now + MESSAGE_TTL_SECONDS)),
            },
        )
        return 'CLAIMED', ''
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            logger.error(json.dumps({
                'event': 'idempotency_claim_failed',
                'messageId': message_id,
                'error': type(exc).__name__,
                'requestId': request_id,
            }))
            raise
        existing = table.get_item(
            Key={'id': message_id},
            ConsistentRead=True,
            ProjectionExpression='whatsappMessageId,#s',
            ExpressionAttributeNames={'#s': 'status'},
        ).get('Item') or {}
        wamid = str(existing.get('whatsappMessageId') or '')
        if wamid:
            return 'SENT', wamid
        return 'BLOCKED', str(existing.get('status') or '')

RATE_LIMIT_PER_SECOND = 80  # Requirement 5.9

# WhatsApp Payment Configurations
# +919330994400 (WECARE.DIGITAL) WABA: 2094615664435155 — Active, Direct API
# +919903300044 (Manish Agarwal) WABA: 2513394156072604 — active, Direct API
# Both use the same Razorpay MID acc_TTFSyolquKEZEy | MCC: 7392 | Purpose: 03
# Config names MUST match EXACTLY what is registered on Meta (WhatsApp Manager >
# Payments).
# Verified live via Graph API /{waba}/payment_configurations on 2026-08-23.
# The configs were rebuilt on Meta that same day (created_timestamp 1787629967-
# 1787630432) and every previously-used name was removed. Both WABAs now carry
# an IDENTICAL pair:
#   WECAREDIGITAL - Razorpay gateway, provider_mid acc_TTFSyolquKEZEy
#   WECAREUPI     - UPI VPA wecaredigitalbh511413.rzp@rxairtel
# MCC 7392, purpose code 03 on all four. No PayU config exists on either WABA.
VALID_PAYMENT_CONFIGS = {'WECAREDIGITAL'}
DEFAULT_PAYMENT_CONFIG = 'WECAREDIGITAL'
# Both WABAs share the same config names, so the mapping is uniform. It is kept
# per-phone so a future divergence needs only a value change here.
#
# WABA1 ONLY for payments, by owner decision 2026-10-07: WABA2 is NEVER used for any
# form of payment, anywhere. WABA2 (PHONE_NUMBER_ID_2) is deliberately ABSENT from both
# maps below. Because _build_payment_settings resolves the config name from these maps and
# raises PaymentConfigurationUnresolved on a miss, a payment attempt on WABA2 fails closed
# at this one chokepoint rather than sending a prompt the customer cannot complete
# (wecare_whatapp_native_pay_template is only approved on WABA1, verified live 2026-10-07). Do NOT re-add
# PHONE_NUMBER_ID_2 here without the owner reversing that decision.
PHONE_PAYMENT_CONFIG = {
    PHONE_NUMBER_ID_1: 'WECAREDIGITAL',                  # +919330994400 (WABA1) — the only payment WABA
}

# Razorpay is the only gateway. PayU was removed from both WABAs on Meta.
#
# WABA2 is REMOVED from this map. It is not the control - see `PAYMENT_SENDERS` below and the
# guard inside `_build_payment_settings` - but the map and the guard must agree, or the next
# reader concludes WABA2 is a permitted payment sender because the map says so.
PHONE_PAYMENT_GATEWAYS = {
    PHONE_NUMBER_ID_1: {'razorpay': 'WECAREDIGITAL'},     # +919330994400 (WABA1) — the only payment WABA
}

#: The ONLY sender permitted to take a payment.
#:
#: Removing WABA2 from `PHONE_PAYMENT_GATEWAYS` alone does NOT close the hole, which is why this
#: exists as a separate check: `explicit_config` is read BEFORE `config_name` is computed, and
#: `'WECAREDIGITAL'` is a valid name on both WABAs - so a caller naming one would otherwise
#: resolve for either sender regardless of the map.
#:
#: Pinned equal to `wa_payment_request.PAYMENT_SENDERS` by test. A literal rather than an import
#: because the resolver must not depend on the `ecommerce` package, and because this is the layer
#: no caller can bypass.
PAYMENT_SENDERS = frozenset({PHONE_NUMBER_ID_1})

# ══ A0: the readiness gate's expectations and vocabulary ═════════════════════════════════════
#
#: Expectations, compared against a live Meta read. EMPTY BY DEFAULT: an empty value makes
#: `payment_readiness.evaluate` answer CONFIGURATION_UNVERIFIED, which blocks. Neither can
#: enable a payment - only a successful live readback can. There is deliberately no default
#: that could read as "ready", which is the same rule `checkout/handler.py:159-160` follows.
EXPECTED_CONFIGURATION_NAME = os.environ.get('EXPECTED_CONFIGURATION_NAME', '')
EXPECTED_PROVIDER_MID = os.environ.get('EXPECTED_PROVIDER_MID', '')

#: The ONE payload key that REQUESTS a payment. `orderStatusDetails` is deliberately absent
#: because fulfilment is not a payment request. `payment_action` in `handler` stays as it is - it
#: answers a different question (does this need Admin?) and order_status does.
_PAYMENT_REQUEST_KEYS = ('isCheckoutTemplate',)
_REMOVED_PAYMENT_REQUEST_KEYS = ('isPaymentTemplate', 'isInteractivePayment')

#: Removed payment envelopes. They are rejected at the public handler boundary and have no
#: payload-building implementation. WhatsApp collection is template ORDER_DETAILS only.

#: THE single approved Meta payment template (UTILITY / ORDER_DETAILS / `en`, WABA1). Pinned
#: here, at the boundary, rather than trusted from each caller: an `isCheckoutTemplate` request
#: naming any other template is refused before any provider read, so a second payable template
#: cannot become a second payment rail even if Meta later approves one. Env-read with the same
#: key and default as the invoice engine (`WA_PAY_TEMPLATE`), so the two cannot name different
#: templates without the boundary refusing every payment.
WA_PAY_TEMPLATE = whatsapp_templates.PAY.name
WA_PAY_TEMPLATE_LANGUAGE = 'en'
WA_PAY_TEMPLATE_NOT_PERMITTED = 'WA_PAY_TEMPLATE_NOT_PERMITTED'
#: The only settlement currency and the only goods types Meta accepts for an India
#: ORDER_DETAILS payment. Server-pinned so a caller cannot change what the provider settles.
WA_PAY_CURRENCY = 'INR'
WA_PAY_GOODS_TYPES = frozenset({'physical-goods', 'digital-goods'})

#: The two states that mean "ask again later". Everything else means a human must act.
_READINESS_TRANSIENT = frozenset({payment_readiness.META_UNAVAILABLE,
                                  payment_readiness.RAZORPAY_UNAVAILABLE})

#: One customer- and operator-safe string. It ends "Nothing has been charged." because that
#: assurance is the one thing every refusal on this path must carry; `readiness.customer_message()`
#: does not carry it and is deliberately not used here.
_NOT_READY_MESSAGE = 'WhatsApp payment is not ready. Nothing has been charged.'

#: The function that holds the Meta token and owns the Graph reads. A LITERAL, not an env var:
#: it is a function name rather than a Meta-registered string, so the "one home, env-read"
#: argument that justifies `WA_PAY_TEMPLATE` does not transfer, and a stale env value would
#: surface as META_UNAVAILABLE - the hardest state on this path to tell from a real outage.
_PAYMENT_READ_FUNCTION = 'wecare-whatsapp-business-api:live'

#: The single approved Meta Order Status template used for EVERY payment/order-status update.
#: The 24-hour service window never selects a different transport. Name/language come from the
#: shared registry so the gate and sender read one value; the registry preserves env override.
WA_ORDER_STATUS_TEMPLATE = whatsapp_templates.ORDER_STATUS.name
WA_ORDER_STATUS_TEMPLATE_LANGUAGE = whatsapp_templates.ORDER_STATUS.language


#: Refusal codes this gate owns. Deliberately NOT added to
#: `wa_payment_request.REFUSAL_MESSAGES`: none of them is a `PaymentRequestRefused`, and putting
#: them there would pull readiness vocabulary into the reservation module, which holds none.
WA_PAY_NOT_READY = 'WA_PAY_NOT_READY'
WA_PAY_CONFIG_NOT_PROVABLE = 'WA_PAY_CONFIG_NOT_PROVABLE'
WA_PAY_ENVELOPE_NOT_PERMITTED = 'WA_PAY_ENVELOPE_NOT_PERMITTED'


class PaymentConfigurationUnresolved(ValueError):
    """No recognised Meta payment configuration for this sender.

    Raised instead of substituting a default. A payment request naming a configuration Meta
    does not hold still reaches the customer, and then fails when they tap Pay — the most
    expensive possible place to discover it.
    """


def _resolve_payment_config_name(phone_number_id: str, order_details: dict) -> str:
    """Return the single server-owned WhatsApp payment configuration.

    Callers cannot select a payment configuration. The only supported rail is WABA1 +
    WECAREDIGITAL + Razorpay through the approved ORDER_DETAILS template.
    """
    if phone_number_id not in PAYMENT_SENDERS:
        raise PaymentConfigurationUnresolved(
            f'sender {phone_number_id!r} may not take payments')

    removed_keys = (
        'payment_link_uri', 'upi_intent_link', 'payment_link', 'payment_settings',
        'preferred_upi_app', 'enabled_payment_options',
    )
    present = [key for key in removed_keys if order_details.get(key)]
    if present:
        raise PaymentConfigurationUnresolved(
            'unsupported WhatsApp payment option: ' + ','.join(sorted(present)))

    config_name = (PHONE_PAYMENT_GATEWAYS.get(phone_number_id) or {}).get('razorpay', '')
    supplied = str(order_details.get('payment_configuration') or '').strip()
    if supplied and supplied != config_name:
        raise PaymentConfigurationUnresolved(
            'caller-selected payment configuration is not permitted')
    if config_name != 'WECAREDIGITAL':
        raise PaymentConfigurationUnresolved(
            'the server payment configuration is not WECAREDIGITAL')
    return config_name


def _build_payment_settings(phone_number_id: str, order_details: dict) -> list:
    """Build the one supported WhatsApp payment setting.

    WECARE.DIGITAL uses only the approved ORDER_DETAILS template backed by the Razorpay
    payment-gateway configuration. Payment links, raw UPI intents, alternate gateways and
    caller-selected payment settings are deliberately unsupported.
    """
    if phone_number_id not in PAYMENT_SENDERS:
        raise PaymentConfigurationUnresolved(
            f'sender {phone_number_id!r} may not take payments')

    config_name = _resolve_payment_config_name(phone_number_id, order_details)
    ref_id = order_details.get('reference_id', '')
    return [{
        'type': 'payment_gateway',
        'payment_gateway': {
            'type': 'razorpay',
            'configuration_name': config_name,
            'razorpay': {
                'receipt': ref_id[:40] if ref_id else '',
                'notes': {
                    'referenceId': ref_id,
                    'source': 'wecare_invoice_engine',
                },
            },
        },
    }]


# ══ A0: one readiness gate at the boundary every payment send must cross ═════════════════════
#
# This function is the only one in the repository that composes a Meta `review_and_pay` message,
# so every in-WhatsApp payment surface reaches Meta through here. Measured callers of
# `isCheckoutTemplate`: `ecommerce/checkout` `_send_order_details` (WhatsApp catalog cart,
# catalog service, authenticated website "pay on WhatsApp" create) and the invoice engine's
# `send_payment_link` (staff invoices, Submit Request payments) - all server-side. No browser
# code composes a payment any more. Gating at the boundary rather than at each caller is
# deliberate: callers can be added by anyone, the Meta boundary cannot.
#
# After this gate, no in-WhatsApp payment send in the system reaches Meta without a live
# readiness proof. Before it, that was false.


_payment_read_lambda = None


def _payment_read_client():
    """The Lambda client the two readiness reads use. A MODULE-LEVEL SEAM, deliberately.

    Built lazily and held here rather than constructed inline at the call site, so an offline test
    can patch one name and reach every branch of the gate with no network access. That is the
    property that makes a gate testable: without a seam, a test cannot distinguish "verified" from
    "defaulted".
    """
    global _payment_read_lambda
    if _payment_read_lambda is None:
        _payment_read_lambda = boto3.client(
            'lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return _payment_read_lambda


def _invoke_payment_read(path: str, query: Dict[str, str]) -> Dict[str, Any]:
    """One synchronous read against the business-API Lambda, parsed. Raises on any failure.

    Modelled on `checkout/handler.py`'s working `_fetch_payment_configurations`. Raising is
    correct: `payment_readiness.evaluate` catches every exception from an injected fetch and
    reports META_UNAVAILABLE, because an unreachable provider and a misconfigured one are
    indistinguishable from its position and both must block.
    """
    response = _payment_read_client().invoke(
        FunctionName=_PAYMENT_READ_FUNCTION,
        InvocationType='RequestResponse',
        Payload=json.dumps({'httpMethod': 'GET', 'path': path,
                            'queryStringParameters': query}).encode('utf-8'),
    )
    raw = response['Payload'].read()
    if response.get('FunctionError'):
        raise RuntimeError('payment read Lambda failed')
    result = json.loads(raw.decode('utf-8')) if raw else {}
    # A non-2xx is raised rather than parsed. The template route answers 502 when Meta errors,
    # and an unparsed 502 body would reach `_approved_template_names` as "no templates" -
    # PAYMENT_TEMPLATE_MISSING instead of META_UNAVAILABLE. Both block, but only one is true.
    if not 200 <= int(result.get('statusCode') or 500) < 300:
        raise RuntimeError('payment read returned a non-success status')
    body = result.get('body')
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            body = {}
    return body if isinstance(body, dict) else {}


def _fetch_payment_configurations(waba_id: str) -> Dict[str, Any]:
    """Live `GET /{waba}/payment_configurations`, through the business-API token holder.

    The read must stay UNFILTERED: a `fields` filter makes Meta return `data: []`, the measured
    false negative that once blocked every payment. `/payment-config/list` returns the flattened
    `{data:[config,...]}` shape `evaluate` consumes.

    Returning `{}` is not a pass - `evaluate` reads an absent `data` key as META_UNAVAILABLE.

    No caching. Requirements statement 9 requires a live readback, and a cached verdict is a
    constant with a timestamp.
    """
    return _invoke_payment_read('/wa-business/payment-config/list', {'wabaId': waba_id})


def _fetch_approved_templates(waba_id: str) -> Dict[str, Any]:
    """Live WABA-scoped template list, so the APPROVED template is proven and not assumed.

    Uses `/wa-business/payment-templates/list`, which is an UNFILTERED
    `GET /{waba_id}/message_templates`. Deliberately NOT `/direct-send/templates`: that route
    filters `source=AUTO_GENERATED`, and `wecare_whatapp_native_pay_template` is manually created and manually
    approved, so it can never appear there - every payment send would block on
    PAYMENT_TEMPLATE_MISSING. Deliberately NOT the `catalogServiceReadiness` action either: it
    takes no `wabaId` and reads three hardcoded template ids, so it would prove one WABA's
    templates for a request from another - over-permissive on a money path.
    """
    return _invoke_payment_read('/wa-business/payment-templates/list', {'wabaId': waba_id})



_TEMPLATE_CATEGORY_CACHE_TTL = 300
_template_category_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


class TemplateCategoryUnavailable(RuntimeError):
    """The server could not prove a template's live Meta category, so it must not guess."""


def _template_category_for_send(phone_number_id: str, template_name: str,
                                request_id: str) -> str:
    """Return the live APPROVED Meta category for one template, cached briefly per WABA.

    Marketing classification is a server-side decision. The browser may tell us that a send is
    marketing, but it may never downgrade a Meta MARKETING template to utility/service. The first
    send on a warm Lambda reads the unfiltered WABA template list; subsequent recipients in the
    same campaign reuse that proof for five minutes.
    """
    name = str(template_name or '').strip()
    if not name:
        raise TemplateCategoryUnavailable('template name is empty')
    waba_id = _waba_for_sender(phone_number_id)
    if not waba_id:
        raise TemplateCategoryUnavailable('sender WABA cannot be resolved')

    key = (waba_id, name.lower())
    now = time.time()
    cached = _template_category_cache.get(key)
    if cached and (now - cached[1]) < _TEMPLATE_CATEGORY_CACHE_TTL:
        return cached[0]

    try:
        rows = _fetch_approved_templates(waba_id).get('data', [])
    except Exception as error:  # noqa: BLE001 - classification fails closed
        logger.warning(json.dumps({
            'event': 'template_category_read_failed',
            'templateName': name,
            'wabaId': waba_id,
            'error': type(error).__name__,
            'requestId': request_id,
        }))
        raise TemplateCategoryUnavailable('template category read failed') from None

    categories = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        row_name = str(row.get('name') or '').strip()
        if not row_name or not template_status.is_sendable(row.get('status')):
            continue
        category = str(row.get('category') or '').strip().upper()
        if category:
            _template_category_cache[(waba_id, row_name.lower())] = (category, now)
        if row_name.lower() == name.lower() and category:
            categories.add(category)

    if len(categories) != 1:
        logger.warning(json.dumps({
            'event': 'template_category_unresolved',
            'templateName': name,
            'wabaId': waba_id,
            'categories': sorted(categories),
            'requestId': request_id,
        }))
        raise TemplateCategoryUnavailable('template category is not uniquely provable')

    category = next(iter(categories))
    _template_category_cache[key] = (category, now)
    return category


def _resolve_whatsapp_message_purpose(body: Dict[str, Any], phone_number_id: str,
                                      is_template: bool, template_name: Optional[str],
                                      is_lto_template: bool, is_otp_template: bool,
                                      request_id: str) -> str:
    """Resolve the consent purpose without trusting a caller to downgrade marketing.

    Explicit MARKETING is always honoured. Campaign/LTO traffic is marketing by definition.
    For every ordinary template, Meta's live category is authoritative: MARKETING upgrades the
    purpose even if a caller supplied SERVICE/TRANSACTIONAL. Utility/authentication templates do
    not require marketing consent. Free-form replies default to SERVICE.
    """
    raw = str(body.get('messagePurpose') or body.get('consentPurpose') or '').strip()
    purpose = consent_evidence.SERVICE
    if raw:
        purpose = consent_evidence.normalize_purpose(raw)

    # These envelopes already prove their purpose without a provider read.
    # LTO/campaign is marketing by construction; OTP authentication is service/authentication.
    # Avoiding a live template-list read here keeps authentication and campaign construction
    # independent of Meta template-list availability while preserving the stricter ordinary
    # template path below.
    if is_lto_template or body.get('campaignId') or body.get('campaignName'):
        return consent_evidence.MARKETING
    if is_otp_template:
        return consent_evidence.SERVICE

    if is_template:
        category = _template_category_for_send(
            phone_number_id, str(template_name or ''), request_id)
        if category == 'MARKETING':
            purpose = consent_evidence.MARKETING
        elif category == 'UTILITY' and purpose != consent_evidence.MARKETING:
            purpose = consent_evidence.TRANSACTIONAL
        elif category == 'AUTHENTICATION' and purpose != consent_evidence.MARKETING:
            purpose = consent_evidence.SERVICE

    return purpose


def _marketing_consent_refusal(contact: Optional[Dict[str, Any]], purpose: str,
                               contact_id: str, request_id: str
                               ) -> Optional[Dict[str, Any]]:
    """Block a marketing send unless the canonical ledger currently proves WhatsApp opt-in."""
    if purpose != consent_evidence.MARKETING:
        return None

    now = int(time.time())
    state = consent_evidence.current_state(
        contact, 'WHATSAPP', now=now, purpose=consent_evidence.MARKETING)
    if state == consent_evidence.OPTED_IN:
        return None

    logger.warning(json.dumps({
        'event': 'whatsapp_marketing_consent_refused',
        'contactId': mask_contact_id(contact_id),
        'consentState': state,
        'purpose': consent_evidence.MARKETING,
        'requestId': request_id,
    }))
    return _error_response(
        403,
        'WHATSAPP_MARKETING_CONSENT_REQUIRED',
        'This customer has no current WhatsApp marketing opt-in. Nothing was sent.',
    )



def _approved_order_status_template(phone_number_id: str, request_id: str) -> str:
    """Return the single Order Status template only after a live APPROVED readback."""
    waba_id = _waba_for_sender(phone_number_id)
    if not waba_id:
        logger.warning(json.dumps({
            'event': 'order_status_template_waba_unresolved',
            'phoneNumberId': phone_number_id,
            'requestId': request_id,
        }))
        return ''
    try:
        rows = _fetch_approved_templates(waba_id).get('data', [])
        approved = {
            row.get('name') for row in rows if isinstance(row, dict)
            and row.get('status') == 'APPROVED'
            and row.get('category') == 'UTILITY'
            and row.get('sub_category') == 'ORDER_STATUS'
            and row.get('language') == WA_ORDER_STATUS_TEMPLATE_LANGUAGE
        }
    except Exception as error:  # noqa: BLE001 - fail closed on provider/read errors
        logger.warning(json.dumps({
            'event': 'order_status_template_read_failed',
            'error': type(error).__name__,
            'wabaId': waba_id,
            'requestId': request_id,
        }))
        return ''
    if WA_ORDER_STATUS_TEMPLATE not in approved:
        logger.warning(json.dumps({
            'event': 'order_status_template_not_approved',
            'templateName': WA_ORDER_STATUS_TEMPLATE,
            'wabaId': waba_id,
            'requestId': request_id,
        }))
        return ''
    return WA_ORDER_STATUS_TEMPLATE


def _refuse_unless_payment_ready(body: Dict[str, Any], phone_number_id: str,
                                 request_id: str) -> Optional[Dict[str, Any]]:
    """Refuse a payment REQUEST unless a live provider readback proves it can be collected.

    Returns None to proceed. Ordered so the cheapest and most authoritative refusals come
    first; steps 1-6 make NO provider call. Never raises - and the call site wraps it anyway, so
    the promise is enforced rather than asserted.
    """
    # 1. Arming. `orderStatusDetails` is absent from the payment keys, so a post-payment notification is
    #    never gated: refusing one would leave a paid customer without a confirmation.
    if not any(body.get(key) for key in _PAYMENT_REQUEST_KEYS):
        return None

    # 2. Only WABA1 may take a payment (owner decision 2026-10-07). This is NOT redundant with
    #    `_build_payment_settings`'s own check: `_waba_for_sender` resolves WABA2 SUCCESSFULLY
    #    (direct_send.META_PHONE_TO_WABA holds both), and both WABAs carry an identical
    #    WECAREDIGITAL configuration with the same provider_mid - so without this the gate could
    #    report PAYMENT_READY, and log `payment_readiness_ready`, for a sender that may never
    #    collect. First and by itself, because it is the cheapest and most authoritative refusal
    #    on the path: one set membership, and no provider read can make a forbidden sender valid.
    if phone_number_id not in wa_payment_request.PAYMENT_SENDERS:
        logger.error(json.dumps({'event': 'wa_payment_sender_not_permitted',
                                 'code': wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED,
                                 'requestId': request_id}))
        return _error_response(409, wa_payment_request.WA_PAY_SENDER_NOT_PERMITTED,
                               _NOT_READY_MESSAGE)

    # 4. Shape. An EMPTY dict is refused too: it would fall through to the phone map and let the
    #    gate prove a configuration for a payment request that names no order at all.
    order_details = body.get('checkoutOrderDetails') or {}
    if not isinstance(order_details, dict) or not order_details:
        logger.error(json.dumps({'event': 'wa_payment_order_details_invalid',
                                 'requestId': request_id}))
        return _error_response(400, 'ORDER_DETAILS_INVALID', 'Nothing has been charged.')

    # 4b. One template, one currency, Meta's goods types. No provider read can make another
    #     template, a non-INR settlement or an unknown goods type acceptable, so these refuse
    #     first. Absent currency/type keep their INR / physical-goods defaults in the sender.
    template_name = str(body.get('templateName') or '')
    if template_name != WA_PAY_TEMPLATE:
        logger.error(json.dumps({'event': 'wa_payment_template_not_permitted',
                                 'templateName': template_name[:80],
                                 'code': WA_PAY_TEMPLATE_NOT_PERMITTED,
                                 'requestId': request_id}))
        return _error_response(409, WA_PAY_TEMPLATE_NOT_PERMITTED, _NOT_READY_MESSAGE)
    if str(order_details.get('currency') or WA_PAY_CURRENCY) != WA_PAY_CURRENCY or \
            str(order_details.get('type') or 'physical-goods') not in WA_PAY_GOODS_TYPES:
        logger.error(json.dumps({'event': 'wa_payment_order_details_invalid',
                                 'reason': 'currency_or_type', 'requestId': request_id}))
        return _error_response(400, 'ORDER_DETAILS_INVALID', 'Nothing has been charged.')

    # 5. The configuration name, resolved ONCE by the extracted resolver the sender also uses.
    try:
        config_name = _resolve_payment_config_name(phone_number_id, order_details)
    except PaymentConfigurationUnresolved as unresolved:
        logger.error(json.dumps({'event': 'wa_payment_config_unresolved_refused',
                                 'reason': str(unresolved)[:200], 'requestId': request_id}))
        return _error_response(409, wa_payment_request.WA_PAY_CONFIG_UNRESOLVED,
                               _NOT_READY_MESSAGE)

    # 6. The only configuration permitted by this application is WECAREDIGITAL/Razorpay.
    if config_name != EXPECTED_CONFIGURATION_NAME:
        logger.error(json.dumps({'event': 'wa_payment_config_not_provable_refused',
                                 'configurationName': config_name,
                                 'code': WA_PAY_CONFIG_NOT_PROVABLE,
                                 'requestId': request_id}))
        return _error_response(409, WA_PAY_CONFIG_NOT_PROVABLE, _NOT_READY_MESSAGE)

    # 7. The live readback. The WABA id comes from the SENDER, through the function that already
    #    owns that derivation; never from the request body, because a caller-supplied WABA id on
    #    a money path is a caller-supplied routing decision. An unresolvable sender yields `''`,
    #    which `evaluate` reports as CONFIGURATION_UNVERIFIED - the fail-closed direction.
    #
    #    `evaluate_for_delivery`, not `evaluate`, so the APPROVED template is proven too:
    #      - `last_inbound_at=None` makes `template_required` answer True unconditionally, which
    #        is correct here because every payment this business sends travels in the approved
    #        template regardless of the 24-hour window. No inbound lookup is needed.
    #      - `payment_template_name` is the string the SEND will use, not a constant. A gate
    #        that checks a different string from the one the send uses can pass while the send
    #        fails. An empty name on a payment request yields PAYMENT_TEMPLATE_MISSING.
    readiness = payment_readiness.evaluate_for_delivery(
        last_inbound_at=None,
        payment_template_name=str(body.get('templateName') or ''),
        fetch_templates=_fetch_approved_templates,
        expected_waba_id=_waba_for_sender(phone_number_id),
        expected_configuration_name=config_name,
        expected_provider_mid=EXPECTED_PROVIDER_MID,
        fetch_configurations=_fetch_payment_configurations,
    )
    if readiness.state in payment_readiness.BLOCKING_STATES:
        logger.error(json.dumps({'event': 'wa_payment_readiness_refused',
                                 'readiness': readiness.state, 'code': WA_PAY_NOT_READY,
                                 'requestId': request_id, 'detail': readiness.as_dict()}))
        # 503 for the two availability states, 409 for the other eight. A 409 tells the staff UI
        # "this will not succeed"; META_UNAVAILABLE and RAZORPAY_UNAVAILABLE will.
        return _error_response(
            503 if readiness.state in _READINESS_TRANSIENT else 409,
            WA_PAY_NOT_READY, _NOT_READY_MESSAGE)
    return None


METRICS_NAMESPACE = 'WECARE.DIGITAL'

# Meta WhatsApp Cloud API error codes (from official error reference docs)
# Used for actionable error handling, retry logic, and frontend display
META_MESSAGE_ERRORS = {
    # Rate limiting
    130429: {'msg': 'Rate limit hit', 'action': 'Implement exponential backoff', 'retry': True},
    131045: {'msg': 'Message rate limit hit', 'action': 'Slow down message sending', 'retry': True},
    131056: {'msg': 'Pair rate limit hit (1 msg/6s per user)', 'action': 'Wait 4^X seconds before retry', 'retry': True},
    # Messaging window
    131047: {'msg': 'Re-engagement message outside 24h window', 'action': 'Send template message instead', 'retry': False},
    131051: {'msg': 'Unsupported message type', 'action': 'Check message type compatibility', 'retry': False},
    # Template errors
    132000: {'msg': 'Template param count mismatch', 'action': 'Verify template parameter count', 'retry': False},
    132001: {'msg': 'Template does not exist', 'action': 'Check template name and language', 'retry': False},
    132005: {'msg': 'Template hydrated text too long', 'action': 'Shorten parameter values', 'retry': False},
    132007: {'msg': 'Template format mismatch', 'action': 'Check component types match template', 'retry': False},
    132012: {'msg': 'Template paused', 'action': 'Template quality too low — fix or use another', 'retry': False},
    132015: {'msg': 'Template disabled', 'action': 'Template was disabled — create new one', 'retry': False},
    # Media errors
    131052: {'msg': 'Media download error', 'action': 'Check media URL accessibility', 'retry': True},
    131053: {'msg': 'Media upload error', 'action': 'Retry media upload', 'retry': True},
    # Account errors
    131031: {'msg': 'Account locked', 'action': 'Contact Meta support', 'retry': False},
    131048: {'msg': 'Spam rate limit', 'action': 'Improve message quality', 'retry': False},
    131049: {'msg': 'Message not sent — user not on WhatsApp', 'action': 'Verify recipient number', 'retry': False},
    # Generic
    100: {'msg': 'Invalid parameter', 'action': 'Check request payload', 'retry': False},
    131009: {'msg': 'Parameter missing or invalid', 'action': 'Check required fields', 'retry': False},
    131026: {'msg': 'Message undeliverable', 'action': 'Recipient may have blocked you', 'retry': False},
    131042: {'msg': 'Business eligibility payment issue', 'action': 'Check payment method on WABA', 'retry': False},
    # Additional codes from official Meta error reference (2025-2026)
    130472: {'msg': 'User part of experiment', 'action': 'User number is in a Meta experiment — retry later', 'retry': True},
    131000: {'msg': 'Something went wrong', 'action': 'Retry; if persists, open Direct Support ticket', 'retry': True},
    131008: {'msg': 'Required parameter missing', 'action': 'Check endpoint reference for required params', 'retry': False},
    131016: {'msg': 'Service unavailable', 'action': 'Service temporarily unavailable — retry', 'retry': True},
    131021: {'msg': 'Recipient cannot be sender', 'action': 'Cannot send message to yourself', 'retry': False},
    131037: {'msg': 'Display name approval needed', 'action': 'Approve display name before sending', 'retry': False},
    131050: {'msg': 'User stopped marketing messages', 'action': 'Do not retry — user opted out of marketing', 'retry': False},
    # ── Conversation Routing ──
    # Neither code appeared anywhere in this repo until now, so a routing refusal was
    # indistinguishable from a generic send failure — which is how a silent dead end
    # stays invisible for days. Both are ownership refusals, not transient faults:
    # retrying cannot succeed, because the thing that is wrong is WHO is sending, not
    # the request. Templates are unaffected by ownership and never produce these.
    2494191: {'msg': 'Thread take not permitted — not the designated escalation partner',
              'action': 'Conversation Routing: only the designated escalation partner may take a '
                        'thread. Check the routing configuration in Meta Business Suite; do not retry.',
              'retry': False},
    138038: {'msg': 'Not the Call primary for this entry point',
             'action': 'Conversation Routing: the Call entry point is mapped to another responder. '
                       'Owner must remap it in Meta Business Suite; retrying will not help.',
             'retry': False},
}

#: Codes that mean "you do not own this thread", as opposed to "this send was bad".
#: Kept as a named set so the alarm filter and the table cannot drift apart.
ROUTING_OWNERSHIP_ERRORS = (2494191, 138038)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Send WhatsApp message or reaction.
    Requirements: 3.1, 3.2, 5.2-5.11, 16.2-16.6
    Supports: text, media, template, and reaction messages
    """
    global origin
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)

    logger.info(json.dumps({
        'event': 'outbound_whatsapp_start',
        'sendMode': SEND_MODE,
        'requestId': request_id
    }))

    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _error_response(400, 'Invalid JSON in request body')

    for removed_key in _REMOVED_PAYMENT_REQUEST_KEYS:
        if body.get(removed_key):
            return _error_response(
                400, WA_PAY_ENVELOPE_NOT_PERMITTED,
                'This WhatsApp payment mode has been removed. Use the approved ORDER_DETAILS template.')
    if body.get('orderDetails') and not body.get('isCheckoutTemplate'):
        return _error_response(
            400, WA_PAY_ENVELOPE_NOT_PERMITTED,
            'Raw order_details payments have been removed. Use checkoutOrderDetails with the approved template.')

    payment_action = bool(body.get('isCheckoutTemplate')) or isinstance(body.get('orderStatusDetails'), dict)
    # Viewers read; they do not message customers. Every send, reaction, typing indicator, block
    # change and media-upload URL is an Operator action, and a payment request is Admin. Listing
    # blocked users is the one read this route serves. Internal invokes skip auth as before.
    read_only = body.get('blockAction') == 'list'
    required_role = 'Admin' if payment_action else (None if read_only else 'Operator')
    auth_result = require_auth(event, required_role=required_role)
    if auth_result is not None:
        return auth_result

    # Defense in depth for already-published commerce/invoice Lambda versions:
    # their obsolete post-invoice "View your order" CTA used this dedicated key.
    # Reject it BEFORE payment readiness, contact lookup, a send claim, or Meta.
    # Unrelated legitimate CTA messages have different idempotency keys.
    if str(body.get('idempotencyKey') or '').startswith('order-page-link:'):
        logger.warning(json.dumps({
            'event': 'retired_post_invoice_cta_refused', 'requestId': request_id,
        }))
        return _error_response(
            410, 'ORDER_PAGE_LINK_RETIRED',
            'The retired post-invoice Orders message cannot be sent.')

    # A0 — hoisted from inside the `try` below so the GATE and the SEND read the same value from
    # the same expression, rather than two copies of the same default. Nothing between the auth
    # block and the original position read or wrote it (the only early return in that span is the
    # `getUploadUrl` branch, which does not use it), so this is a pure move.
    phone_number_id = body.get('phoneNumberId', PHONE_NUMBER_ID_1)

    # A0 — the gate. Before contact resolution, before any media upload, before any `put_message`
    # write and before every send branch, so a refusal writes nothing and sends nothing. Ordinary
    # text, media, template, OTP and order_status sends pay nothing: the gate returns on its
    # first line.
    #
    # Wrapped, so "this function never raises" is enforced rather than argued. A gate that cannot
    # answer must refuse.
    try:
        refusal = _refuse_unless_payment_ready(body, phone_number_id, request_id)
    except Exception as unexpected:  # noqa: BLE001
        logger.error(json.dumps({'event': 'wa_payment_gate_error',
                                 'error': type(unexpected).__name__,
                                 'requestId': request_id}))
        refusal = _error_response(503, WA_PAY_NOT_READY, _NOT_READY_MESSAGE)
    if refusal is not None:
        return refusal

    # The payment template travels only in the checkout envelope above. Its ORDER_DETAILS button
    # needs the server-built `order_details` action, so Meta refuses a generic send of it with
    # 131008 ("'action' cannot be null for ORDER_DETAILS button type"), as two such sends did on
    # 2026-10-25. Refused here, before any contact write, media upload or provider call.
    if (body.get('isTemplate') and not body.get('isCheckoutTemplate')
            and str(body.get('templateName') or '').strip().lower() == WA_PAY_TEMPLATE.lower()):
        logger.warning(json.dumps({'event': 'wa_pay_template_generic_send_refused',
                                   'code': WA_PAY_TEMPLATE_NOT_PERMITTED,
                                   'requestId': request_id}))
        return _error_response(
            409, WA_PAY_TEMPLATE_NOT_PERMITTED,
            'The payment template is sent only with its order details, from Pay Flow, Inbox or '
            'Commerce. Nothing was sent.')

    # Bound before the try, so every path that reaches `_handle_live_send` passes
    # a defined value. Only the outside-window plain-text branch below ever sets
    # the category; everything else sends with it None, which is today's request
    # byte for byte.
    direct_send_category = None
    direct_send_waba = ''

    try:

        # ── Presigned media upload (Issue 2 fix): large media must NOT be sent as base64
        # through API Gateway/Lambda (10MB GW / 6MB Lambda limits). Frontend requests a
        # presigned PUT URL, uploads the file directly to S3, then sends the S3 key. ──
        if body.get('action') == 'getUploadUrl':
            return _get_media_upload_url(body, request_id)

        contact_id = body.get('contactId')
        content = body.get('content', '')
        # `phone_number_id` is read ABOVE, before the A0 gate, so the gate and the send cannot
        # disagree about which sender this is. Do not re-read it here.
        media_file = body.get('mediaFile')  # S3 key or base64
        media_type = body.get('mediaType')  # image, video, audio, document
        media_filename = body.get('mediaFileName')  # Original filename for documents
        is_template = body.get('isTemplate', False)
        template_name = body.get('templateName')
        template_params = body.get('templateParams', [])
        
        # Approved checkout ORDER_DETAILS template support.
        header_image_url = body.get('headerImageUrl')
        
        # OTP / Authentication template support
        is_otp_template = body.get('isOtpTemplate', False) or body.get('isAuthenticationTemplate', False)
        otp_code = body.get('otpCode', '')
        # 'url' by default: an AUTHENTICATION template's copy-code button is materialised as a URL
        # button, and Meta refuses `copy_code` for it (#132018, wecare_otp). 'copy_code' stays
        # available for a caller that names it.
        otp_button_type = body.get('otpButtonType', 'url')

        # Limited-time-offer (LTO) template support. The offer code is a Meta coupon
        # string, NOT a payment instrument: no amount, no discount arithmetic, no
        # gateway.
        #
        # Validated HERE, not in the builder. `_build_message_payload` returns a
        # message payload and has no path that returns an HTTP envelope, so a 400 has
        # to be decided while `_error_response` is still the correct return type --
        # returning one from the builder would POST the envelope to Meta as the
        # message. `ArithmeticError` is the base of decimal.InvalidOperation, so a
        # malformed Decimal is caught without widening the `from decimal import
        # Decimal` at the top of this module.
        is_lto_template = body.get('isLtoTemplate', False) or body.get('isLimitedTimeOffer', False)
        lto_offer_code = body.get('ltoOfferCode') or body.get('offerCode') or ''
        lto_copy_code_index = body.get('ltoCopyCodeIndex', 0)
        lto_expiration_ms = None
        if is_lto_template:
            try:
                lto_expiration_ms = int(Decimal(str(body.get('ltoExpirationTimeMs'))))
            except (TypeError, ValueError, ArithmeticError):
                return _error_response(400, 'ltoExpirationTimeMs must be an integer epoch '
                                            'milliseconds value')
            if lto_expiration_ms <= 0:
                return _error_response(400, 'ltoExpirationTimeMs must be positive')

        # Standard template media header support (IMAGE / VIDEO / DOCUMENT headers).
        # Templates like wecare_pdf (DOCUMENT) and wd_order (VIDEO) require a
        # header parameter at SEND time — the approval-time example handle is not
        # reusable. The inbox TemplateSender supplies a public link here.
        # (The wd_menu VIDEO template was the other example here; it was deleted
        # at Meta on 2026-10-02, so naming it as a live template was misleading.)
        template_header_media = body.get('headerMedia') or body.get('templateHeaderMedia')
        template_header_type = (body.get('headerType') or body.get('templateHeaderType') or '').lower()
        fixed_header = fixed_image_header(template_name) if is_template else ''
        if fixed_header:
            template_header_media, template_header_type = fixed_header, 'image'
        template_header_filename = body.get('headerFilename') or body.get('templateHeaderFilename')
        # Location header support (headerType == 'location').
        # Expects {latitude, longitude, name, address} supplied at send time.
        template_header_location = body.get('headerLocation') or body.get('templateHeaderLocation')
        # Flow button support: templates with a FLOW button require a button
        # component (sub_type 'flow') at send time, else Meta rejects with
        # error 131008/131009. The frontend detects the flow button from the
        # template definition and passes {index, flowToken?, flowActionData?}.
        template_flow_button = body.get('flowButton') or body.get('templateFlowButton')
        template_url_button = body.get('templateUrlButton')
        # The Vault offer's QUICK_REPLY payload ({index, payload}); the builder accepts it for that
        # one template only.
        template_quick_reply_button = body.get('templateQuickReplyButton')

        # Checkout button template support (order_details button with sale_amount + shipping_info)
        is_checkout_template = body.get('isCheckoutTemplate', False)
        checkout_order_details = body.get('checkoutOrderDetails')  # Full Meta order_details object
        
        # Interactive message support (list, buttons, location request)
        is_interactive = body.get('isInteractive', False)
        interactive_type = body.get('interactiveType')  # 'list', 'button', 'location_request'
        interactive_data = body.get('interactiveData', {})
        
        # Meta order_status is a post-payment fulfilment notification. It is NOT a payment
        # request and therefore is not blocked by the payment-readiness gate.
        order_status_details = body.get('orderStatusDetails')
        is_order_status = isinstance(order_status_details, dict) and bool(order_status_details)
        
        # Direct phone number (fallback when contactId not available)
        recipient_phone_direct = body.get('recipientPhone')
        
        # BSUID recipient (for sending to users without phone numbers)
        recipient_bsuid = body.get('recipientBsuid', '')
        
        # Reaction support
        is_reaction = body.get('isReaction', False)
        reaction_message_id = body.get('reactionMessageId')  # WhatsApp message ID to react to
        reaction_emoji = body.get('reactionEmoji', '\U0001F44D')  # Default: thumbs up
        
        # Native reply support — quote the WhatsApp message id being replied to.
        context_message_id = body.get('contextMessageId') or body.get('replyToMessageId')
        
        # Resolve message purpose BEFORE any send-side effect. Meta's live template category is
        # authoritative, so a caller cannot label a MARKETING template as utility/service.
        try:
            message_purpose = _resolve_whatsapp_message_purpose(
                body, phone_number_id, is_template, template_name,
                is_lto_template, is_otp_template, request_id)
        except consent_evidence.InvalidConsentRecord:
            return _error_response(
                400, 'INVALID_MESSAGE_PURPOSE',
                'messagePurpose must be MARKETING, TRANSACTIONAL or SERVICE.')
        except TemplateCategoryUnavailable:
            return _error_response(
                503, 'TEMPLATE_CATEGORY_UNAVAILABLE',
                'Template category could not be verified. Nothing was sent.')

        # An AUTHENTICATION template carries a one-time code in its body AND its copy-code URL
        # button, so only the OTP envelope builds it. Sent as an ordinary template it reaches Meta
        # without the button parameter and is refused, and a code typed by hand was never issued
        # by sign-in. The category comes from the cached live read the purpose check just made;
        # campaign sends skip that read by design (they are MARKETING by construction), so they
        # skip this check too rather than gain a provider dependency here.
        if (is_template and not is_otp_template and not is_lto_template
                and not (body.get('campaignId') or body.get('campaignName'))):
            try:
                live_category = _template_category_for_send(
                    phone_number_id, str(template_name or ''), request_id)
            except TemplateCategoryUnavailable:
                return _error_response(
                    503, 'TEMPLATE_CATEGORY_UNAVAILABLE',
                    'Template category could not be verified. Nothing was sent.')
            if live_category == 'AUTHENTICATION':
                logger.warning(json.dumps({'event': 'authentication_template_generic_send_refused',
                                           'templateName': str(template_name or '')[:80],
                                           'requestId': request_id}))
                return _error_response(
                    409, 'AUTHENTICATION_TEMPLATE_NOT_PERMITTED',
                    'Verification codes are sent by sign-in and registration, not by hand. '
                    'Nothing was sent.')

        # Allow sending without contactId if recipientPhone is provided (for order_status)
        if not contact_id and not recipient_phone_direct:
            return _error_response(400, 'contactId or recipientPhone is required')
        
        # Direct-phone sends normally auto-create an inbox contact. MARKETING is the exception:
        # permission has to pre-exist on a canonical customer, so an unknown number must be
        # refused without creating a row merely to record that refusal.
        if not contact_id and recipient_phone_direct:
            if message_purpose == consent_evidence.MARKETING:
                contact = contact_store.lookup(
                    dynamodb.Table(CONTACTS_TABLE), recipient_phone_direct) or {}
                if not contact:
                    return _error_response(
                        403, 'WHATSAPP_MARKETING_CONSENT_REQUIRED',
                        'This customer has no current WhatsApp marketing opt-in. Nothing was sent.')
                contact_id = contact.get('contactId') or contact.get('id', '')
            else:
                contact = _get_or_create_contact_by_phone(recipient_phone_direct)
                contact_id = contact.get('contactId') or contact.get('id', '')
            recipient_phone = recipient_phone_direct
        else:
            # Retrieve contact
            contact = _get_contact(contact_id)
            if not contact:
                return _error_response(404, 'Contact not found')
            recipient_phone = contact.get('phone')
            # Auto-resolve BSUID from contact if not explicitly provided
            if not recipient_bsuid and contact.get('bsuid'):
                recipient_bsuid = contact.get('bsuid', '')
        
        # The consent ledger is the single send-time authority for MARKETING. Legacy
        # optInWhatsApp/allowlistWhatsApp booleans are deliberately ignored here: a boolean without
        # evidence cannot grant permission, and an OPTED_OUT ledger entry must always win.
        consent_refusal = _marketing_consent_refusal(
            contact, message_purpose, contact_id, request_id)
        if consent_refusal is not None:
            return consent_refusal

        # ── Live-send smoke-test lockdown ────────────────────────────────────
        # Placed here, before the typing indicator, the block_users branch and
        # every send branch, so that in smoke mode nothing at all reaches a
        # handset other than WA_QA_RECIPIENT - not a message, not blue ticks, not
        # a "typing…" bubble. _send_direct_api repeats the check at the wire as
        # the actual guarantee; this one exists so a blocked test returns a clear
        # 403 instead of surfacing as a 500.
        _smoke_allowed, _smoke_reason = live_smoke.check_recipient(recipient_phone)
        if not _smoke_allowed:
            logger.warning(json.dumps({
                'event': 'smoke_mode_request_blocked',
                'reason': _smoke_reason,
                'recipientPhone': mask_phone(recipient_phone or ''),
                'contactId': mask_contact_id(contact_id),
                'requestId': request_id,
                **live_smoke.describe(),
            }))
            return _error_response(
                403,
                'Live smoke-test mode is active — only the configured QA recipient can be messaged',
                _smoke_reason,
            )
        
        # Validate reaction request
        if is_reaction and not reaction_message_id:
            return _error_response(400, 'reactionMessageId is required for reactions')
        
        # Handle typing indicator request (fire and forget)
        is_typing_indicator = body.get('isTypingIndicator', False)
        if is_typing_indicator:
            try:
                typing_msg_id = body.get('messageId') or body.get('typingMessageId') or ''
                _send_typing_indicator(phone_number_id, typing_msg_id)
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'success': True, 'action': 'typing_indicator'})
                }
            except Exception as e:
                logger.warning(f'Typing indicator failed: {e}')
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'success': False, 'action': 'typing_indicator', 'error': str(e)})
                }
        
        # Block / unblock / list blocked users (Meta block_users API).
        # Only users who messaged in the last 24h can be blocked (Meta rule).
        block_action = body.get('blockAction')  # 'block' | 'unblock' | 'list'
        if block_action:
            try:
                if block_action == 'list':
                    result = _block_users_api(phone_number_id, [], 'list')
                    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'success': True, 'action': 'list', 'result': result})}
                users = body.get('blockUsers') or []
                if not users and recipient_phone:
                    users = [recipient_phone]
                if not users:
                    return _error_response(400, 'No user phone provided to block/unblock')
                # blockUsers is an arbitrary list, not the resolved recipient, so
                # the check above does not cover it. Blocking a real customer is a
                # customer-visible side effect and has no place in a smoke test.
                for _u in users:
                    _ok, _why = live_smoke.check_recipient(_u)
                    if not _ok:
                        logger.warning(json.dumps({
                            'event': 'smoke_mode_block_action_refused',
                            'reason': _why, 'action': block_action,
                            'user': mask_phone(str(_u)), 'requestId': request_id,
                        }))
                        return _error_response(
                            403,
                            'Live smoke-test mode is active — block/unblock is limited to the QA recipient',
                            _why,
                        )
                result = _block_users_api(phone_number_id, users, block_action)
                return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'success': True, 'action': block_action, 'users': users, 'result': result})}
            except Exception as e:
                return _error_response(502, f'Block API error ({block_action}): {e}')
        
        # Marketing consent was enforced above from the evidence ledger. Service/transactional
        # traffic continues into the ordinary service-window/template policy below.
        # Service window check: outside 24h window, only templates are allowed (WhatsApp policy)
        #
        # This used to default `within_window = True` and only evaluate the window
        # when a contact row with an `id` existed, so a send to a bare phone number
        # with no contact record skipped the check entirely. That is the case most
        # likely to be outside the window - there is no record of the customer ever
        # messaging us - and Meta rejected it with 131047 after we had already
        # decided it was allowed. `_is_within_service_window` already fails closed
        # on a missing `lastInboundMessageAt`, so the honest default is False and
        # the absence of a contact is simply another way of having no open window.
        within_window = _is_within_service_window(contact) if contact else False

        # ── Direct Send: the outside-window utility fallback ────────────────
        #
        # `direct_send_category` is None in every case except one: the window is
        # closed, the send would be plain text, and Direct Send is explicitly
        # enabled for the WABA this sender belongs to. When it is set, the 403
        # below is skipped and the message goes out as `category: 'utility'`
        # instead of being refused.
        #
        # Window OPEN deliberately stays None. Today's free-form service message
        # is correct inside the window and cheaper than a utility message, so
        # there is nothing to gain and a billing category to lose.
        #
        # This pre-check is COARSE on purpose. It cannot see that a `content`
        # string beginning with `{` will be parsed into a contacts or location
        # message, so `_build_message_payload` re-decides on the built payload
        # and the handler re-checks afterwards. A disagreement falls back to the
        # 403 rather than sending a non-text message out of the window.
        if not within_window and not is_template:
            # The retired `isPaymentTemplate` / `isInteractivePayment` envelopes are refused at
            # the top of this handler and have no locals here. Naming them raised NameError,
            # which turned every outside-window non-template send (including staff ORDER_STATUS
            # fulfilment updates) into a 500 before the intended refusal/exemption could run.
            looks_plain_text = not any((
                is_reaction, media_type, media_file, is_interactive,
                is_checkout_template, is_order_status,
            )) and bool(content) and bool(recipient_phone)
            if looks_plain_text:
                direct_send_waba = _waba_for_sender(phone_number_id)
                if not direct_send_waba:
                    # Never guess a WABA. Unresolvable means not enabled.
                    logger.info(json.dumps({
                        'event': 'direct_send_waba_unresolved',
                        'phoneNumberId': phone_number_id,
                        'requestId': request_id,
                    }))
                elif direct_send.enabled_for_waba(direct_send_waba):
                    direct_send_category = 'utility'

        if not within_window and not is_template and not is_order_status:
            if direct_send_category:
                # A WABA id is not a secret and already appears in committed source.
                logger.info(json.dumps({
                    'event': 'direct_send_attempt',
                    'category': direct_send_category,
                    'wabaId': direct_send_waba,
                    'contactId': mask_contact_id(contact_id),
                    'requestId': request_id,
                }))
            else:
                return _outside_window_refusal(contact_id, bool(contact), request_id)
        
        # ── Order-status channel selection ──────────────────────────────────
        # PAYMENT RAIL INVARIANT: order_status always uses the single APPROVED
        # `wecare_order_status_v3` UTILITY/ORDER_STATUS template. Do not switch transport
        # based on the 24-hour customer-service window: the whole point of this template is
        # that payment confirmation remains deliverable outside that window and has one
        # customer-visible shape. If Meta cannot prove the template APPROVED, defer.
        order_status_template_name = ''
        if is_order_status:
            order_status_template_name = _approved_order_status_template(
                phone_number_id, request_id)
            if not order_status_template_name:
                return _error_response(
                    409, 'ORDER_STATUS_DEFERRED',
                    'The approved order-status template is unavailable. Nothing was sent.')

        # Requirement 5.4: Validate text length (skip for reactions)
        if not is_reaction and content and len(content) > MAX_TEXT_LENGTH:
            return _error_response(400, f'Content exceeds {MAX_TEXT_LENGTH} characters')
        
        # Requirement 5.9: Check rate limit
        if not _check_rate_limit(phone_number_id):
            return _error_response(429, 'Rate limit exceeded. Try again later.')

        # ── Typing indicator before send (default on) ──
        # Meta's typing_indicator API marks the customer's last received message as
        # read (blue ticks) and shows a "typing…" bubble for up to 25s or until we
        # send. It requires the WAMID of the customer's most recent inbound message,
        # which we store on the contact as lastInboundWamid. Works for ANY outgoing
        # type (text, media, template, interactive) as long as there is a recent
        # inbound message (i.e. within the 24h window). Skipped for reactions and
        # explicit typing-only requests.
        if body.get('showTyping', True) and not is_reaction and within_window:
            try:
                # Prefer a FRESH wamid straight from the InboundTable (the contact's
                # cached lastInboundWamid can be stale → Meta 400 "does not exist").
                # Meta only accepts read/typing markers on RECENT inbound messages, so
                # cap freshness tightly (15 min). Typing is only meaningful right after
                # the customer messages anyway; this avoids the stale-wamid 400 noise.
                _last_wamid = _get_latest_inbound_wamid(recipient_phone, max_age_seconds=900,
                                                        phone_number_id=phone_number_id)
                # None: the customer's latest message cannot carry a marker. The contact's
                # cached lastInboundWamid is that same message, so there is no fallback.
                if _last_wamid is None:
                    _last_wamid = ''
                # Only fall back to the cached contact wamid if it is also fresh.
                elif not _last_wamid:
                    _li = (contact or {}).get('lastInboundMessageAt')
                    try:
                        _fresh = _li and (int(time.time()) - int(_li)) <= 900
                    except (TypeError, ValueError):
                        _fresh = False
                    if _fresh:
                        _last_wamid = (contact or {}).get('lastInboundWamid') or ''
                if _last_wamid:
                    _send_typing_indicator(phone_number_id, _last_wamid)
            except Exception as _te:
                logger.warning(json.dumps({'event': 'pre_send_typing_error', 'error': str(_te), 'requestId': request_id}))

        # Generate the outbound row id. Payment/invoice callers supply a stable idempotencyKey,
        # so an ordinary retry resolves the same stored WAMID instead of creating a second Meta
        # message. Calls with no key preserve the historical random-id behaviour.
        idempotency_key = str(body.get('idempotencyKey') or '').strip()
        try:
            message_id = _stable_outbound_message_id(idempotency_key)
        except ValueError:
            return _error_response(
                400, 'IDEMPOTENCY_KEY_INVALID',
                'idempotencyKey is too long or contains control characters.')

        # Atomically reserve keyed sends before any provider side effect. A read-before-send check is
        # racy under concurrent retries, so the final send boundary owns a conditional write.
        if idempotency_key and SEND_MODE != 'DRY_RUN':
            try:
                claim_state, claim_value = _claim_keyed_outbound_send(message_id, request_id)
            except Exception:
                return _error_response(
                    503, 'IDEMPOTENCY_STATE_UNAVAILABLE',
                    'Message delivery state could not be reserved. Nothing was sent.')
            if claim_state == 'SENT':
                logger.info(json.dumps({
                    'event': 'idempotent_skip',
                    'messageId': message_id,
                    'requestId': request_id,
                }))
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({
                        'success': True,
                        'messageId': message_id,
                        'whatsappMessageId': claim_value,
                        'status': WA_INITIAL_STATUS,
                        'mode': 'LIVE',
                        'idempotent': True,
                    }),
                }
            if claim_state == 'BLOCKED':
                logger.warning(json.dumps({
                    'event': 'idempotent_send_blocked',
                    'messageId': message_id,
                    'status': claim_value or 'unknown',
                    'requestId': request_id,
                }))
                return _error_response(
                    409, 'MESSAGE_SEND_IN_FLIGHT',
                    'This message is already sending or awaiting reconciliation; no duplicate was sent.')
        
        # Requirement 5.3: DRY_RUN mode - log without API call
        if SEND_MODE == 'DRY_RUN':
            if is_reaction:
                return _handle_dry_run_reaction(message_id, contact_id, recipient_phone, reaction_message_id, reaction_emoji, request_id)
            return _handle_dry_run(message_id, contact_id, recipient_phone, content, is_template, request_id)
        
        # Handle reaction messages
        if is_reaction:
            return _handle_reaction_send(
                message_id, contact_id, recipient_phone, phone_number_id,
                reaction_message_id, reaction_emoji, request_id,
                recipient_bsuid=recipient_bsuid
            )
        
        # Handle order_status messages (payment confirmation)
        if is_order_status and order_status_details:
            return _handle_order_status_send(
                message_id, contact_id, recipient_phone, phone_number_id,
                order_status_details, request_id,
                recipient_bsuid=recipient_bsuid,
                template_name=order_status_template_name,
                within_window=within_window,
            )
        
        # Handle interactive messages (list, buttons, location request)
        if is_interactive and interactive_type:
            return _handle_interactive_send(
                message_id, contact_id, recipient_phone, phone_number_id,
                interactive_type, interactive_data, request_id,
                recipient_bsuid=recipient_bsuid
            )
        
        # THE payment send: the approved ORDER_DETAILS template (`WA_PAY_TEMPLATE`) whose button is
        # `sub_type: order_details` with server-built Razorpay `payment_settings`. The gate above
        # has already pinned the template, sender, configuration, currency and live readiness.
        if is_checkout_template and checkout_order_details:
            return _handle_order_details_template_send(
                message_id, contact_id, recipient_phone, phone_number_id,
                is_template, template_name, template_params,
                checkout_order_details, header_image_url,
                request_id, recipient_bsuid=recipient_bsuid
            )
        
        # Requirement 5.2: LIVE mode - call API
        return _handle_live_send(
            message_id, contact_id, recipient_phone, phone_number_id,
            content, media_file, media_type, media_filename, is_template, template_name,
            template_params, within_window, request_id, False, None,
            header_image_url, False, is_otp_template, otp_code, otp_button_type,
            recipient_bsuid=recipient_bsuid,
            template_header_media=template_header_media,
            template_header_type=template_header_type,
            template_header_filename=template_header_filename,
            template_header_location=template_header_location,
            template_flow_button=template_flow_button,
            template_url_button=template_url_button,
            template_quick_reply_button=template_quick_reply_button,
            context_message_id=context_message_id,
            direct_send_category=direct_send_category,
            direct_send_waba=direct_send_waba,
            has_contact_record=bool(contact),
            is_lto_template=is_lto_template,
            lto_expiration_ms=lto_expiration_ms,
            lto_offer_code=lto_offer_code,
            lto_copy_code_index=lto_copy_code_index
        )
        
    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'outbound_whatsapp_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _error_response(500, 'Internal server error')


def _handle_dry_run(message_id: str, contact_id: str, recipient_phone: str, 
                    content: str, is_template: bool, request_id: str) -> Dict[str, Any]:
    """Handle DRY_RUN mode - log without actual API call."""
    now = int(time.time())
    
    # Store message record with DRY_RUN status
    _store_message_record(
        message_id=message_id,
        contact_id=contact_id,
        content=content,
        status='dry_run',
        is_template=is_template,
        whatsapp_message_id=f'dry-run-{message_id}'
    )
    
    logger.info(json.dumps({
        'event': 'dry_run_message',
        'messageId': message_id,
        'contactId': mask_contact_id(contact_id),
        'recipientPhone': mask_phone(recipient_phone),
        'contentLength': len(content) if content else 0,
        'isTemplate': is_template,
        'requestId': request_id
    }))
    
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({
            'messageId': message_id,
            'status': 'dry_run',
            'mode': 'DRY_RUN',
            'message': 'Message logged but not sent (DRY_RUN mode)'
        })
    }


def _handle_dry_run_reaction(message_id: str, contact_id: str, recipient_phone: str,
                              reaction_message_id: str, reaction_emoji: str, request_id: str) -> Dict[str, Any]:
    """Handle DRY_RUN mode for reactions - log without actual API call."""
    logger.info(json.dumps({
        'event': 'dry_run_reaction',
        'messageId': message_id,
        'contactId': mask_contact_id(contact_id),
        'recipientPhone': mask_phone(recipient_phone),
        'reactionMessageId': reaction_message_id,
        'emoji': reaction_emoji,
        'requestId': request_id
    }))
    
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({
            'messageId': message_id,
            'status': 'dry_run',
            'mode': 'DRY_RUN',
            'type': 'reaction',
            'reactionMessageId': reaction_message_id,
            'emoji': reaction_emoji,
            'message': 'Reaction logged but not sent (DRY_RUN mode)'
        })
    }


def _handle_reaction_send(message_id: str, contact_id: str, recipient_phone: str,
                          phone_number_id: str, reaction_message_id: str, 
                          reaction_emoji: str, request_id: str,
                          recipient_bsuid: Optional[str] = None) -> Dict[str, Any]:
    """
    Send a reaction to a WhatsApp message.
    Uses Meta Graph API (Direct API) with reaction type.
    Per Meta docs: reaction payload requires message_id from the original message.
    """
    try:
        # Normalize phone number and add + prefix for reactions
        # AWS docs example: "to":"'{PHONE_NUMBER}'" - try with + prefix
        digits_only = _normalize_phone_number(recipient_phone)
        formatted_phone = f"+{digits_only}" if not digits_only.startswith('+') else digits_only
        
        # Build reaction payload per Meta WhatsApp Cloud API docs
        reaction_payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': formatted_phone,
            'type': 'reaction',
            'reaction': {
                'message_id': reaction_message_id,
                'emoji': reaction_emoji
            }
        }
        # Add BSUID recipient if available (per Meta BSUID docs)
        if recipient_bsuid:
            reaction_payload['recipient'] = recipient_bsuid
        
        logger.info(json.dumps({
            'event': 'reaction_payload',
            'to': mask_phone(formatted_phone),
            'reactionMessageId': reaction_message_id,
            'emoji': reaction_emoji,
            'payloadKeys': sorted(reaction_payload.keys()),
            'requestId': request_id
        }))
        
        # Call SendWhatsAppMessage API (Direct API)
        response = _send_message(phone_number_id, reaction_payload)
        
        whatsapp_message_id = response.get('messageId', '')
        
        logger.info(json.dumps({
            'event': 'reaction_sent',
            'messageId': message_id,
            'whatsappMessageId': whatsapp_message_id,
            'contactId': mask_contact_id(contact_id),
            'reactionMessageId': reaction_message_id,
            'emoji': reaction_emoji,
            'requestId': request_id
        }))
        
        # Emit success metric
        _emit_delivery_metric('success', is_template=False)
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messageId': message_id,
                'whatsappMessageId': whatsapp_message_id,
                'status': 'sent',
                'mode': 'LIVE',
                'type': 'reaction',
                'reactionMessageId': reaction_message_id,
                'emoji': reaction_emoji
            })
        }
        
    except Exception as e:
        error_msg = str(e)
        # Log detailed error for debugging
        logger.error(json.dumps({
            'event': 'reaction_send_error',
            'messageId': message_id,
            'reactionMessageId': reaction_message_id,
            'recipientPhone': mask_phone(recipient_phone),
            'formattedPhone': mask_phone(_normalize_phone_number(recipient_phone)),
            'phoneNumberId': phone_number_id,
            'error': error_msg,
            'requestId': request_id
        }))
        _emit_delivery_metric('failed', is_template=False)
        return _error_response(500, f'Failed to send reaction: {error_msg}')


def _handle_order_status_send(message_id: str, contact_id: str, recipient_phone: str,
                               phone_number_id: str, order_status_details: Dict,
                               request_id: str,
                               recipient_bsuid: Optional[str] = None,
                               template_name: str = '',
                               within_window: bool = False) -> Dict[str, Any]:
    """Send one Meta payment-order status update through the approved template only.

    Business semantics live in `wa_order_status`. The 24-hour customer-service window is
    observational only here; it never selects an interactive transport. Every processing/completed
    payment-order update uses the approved `wecare_order_status_v3` ORDER_STATUS template, and a
    missing approval is deferred before any provider send.
    """
    try:
        from lambda_utils.ecommerce import wa_order_status as _wa_os

        reference_id = _wa_os.canonical_reference(
            order_status_details.get('reference_id', ''))
        order_status = _wa_os.canonical_status(
            order_status_details.get('order_status', ''))
        description = (order_status_details.get('description') or '').strip() \
            or _wa_os.default_body(order_status)

        logger.info(json.dumps({
            'event': 'order_status_details_received',
            'referenceId': reference_id,
            'orderStatus': order_status,
            'withinWindow': within_window,
            'requestId': request_id,
        }))

        # Normalize phone number
        formatted_phone = _normalize_phone_number(recipient_phone)
        whatsapp_phone = f"+{formatted_phone}"

        # Payment/order status is TEMPLATE-ONLY. `within_window` is still logged for
        # observability and may drive typing indicators elsewhere, but it never changes this
        # transport. This prevents two customer experiences and removes the 24-hour dependency.
        channel = 'template'
        if not template_name:
            return _error_response(
                409, 'ORDER_STATUS_DEFERRED',
                'The approved order-status template is unavailable. Nothing was sent.')
        order_status_component = _wa_os.build_template_component(
            reference_id, order_status, description)
        order_status_payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': whatsapp_phone,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {
                    'policy': 'deterministic',
                    'code': WA_ORDER_STATUS_TEMPLATE_LANGUAGE,
                },
                'components': [order_status_component],
            },
        }
        is_template_send = channel == 'template'

        # Add BSUID recipient if available (per Meta BSUID docs)
        if recipient_bsuid:
            order_status_payload['recipient'] = recipient_bsuid

        logger.info(json.dumps({
            'event': 'order_status_payload',
            'to': mask_phone(whatsapp_phone),
            'referenceId': reference_id,
            'orderStatus': order_status,
            'channel': channel,
            'payloadKeys': sorted(order_status_payload.keys()),
            'requestId': request_id
        }))

        # Call SendWhatsAppMessage API (Direct API)
        response = _send_message(phone_number_id, order_status_payload)
        whatsapp_message_id = response.get('messageId', '')

        # Store message record
        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=f'Order Status: {order_status} - {description}',
            status=WA_INITIAL_STATUS,
            is_template=is_template_send,
            whatsapp_message_id=whatsapp_message_id,
            phone_number_id=phone_number_id,
            recipient_bsuid=recipient_bsuid,
        )

        logger.info(json.dumps({
            'event': 'order_status_sent',
            'messageId': message_id,
            'whatsappMessageId': whatsapp_message_id,
            'contactId': mask_contact_id(contact_id),
            'referenceId': reference_id,
            'orderStatus': order_status,
            'channel': channel,
            'requestId': request_id
        }))

        # Emit success metric
        _emit_delivery_metric('success', is_template=is_template_send)

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messageId': message_id,
                'whatsappMessageId': whatsapp_message_id,
                'status': 'sent',
                'mode': 'LIVE',
                'type': 'order_status',
                'referenceId': reference_id,
                'orderStatus': order_status,
                'orderStatusChannel': channel
            })
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(json.dumps({
            'event': 'order_status_send_error',
            'messageId': message_id,
            'referenceId': order_status_details.get('reference_id', ''),
            'withinWindow': within_window,
            'error': error_msg,
            'requestId': request_id
        }))
        _emit_delivery_metric('failed', is_template=True)
        return _error_response(500, f'Failed to send order status: {error_msg}')


# ═══════════════════════════════════════════════════════════════════════════
# APPROVED ORDER_DETAILS PAYMENT TEMPLATE — the ONE WhatsApp payment send
# Meta's docs call a template whose button is `sub_type: order_details` a
# "checkout button template"; here it is exactly one template, WA_PAY_TEMPLATE
# (wecare_whatapp_native_pay_template), collected through payment_gateway /
# Razorpay / WECAREDIGITAL. There is no data-exchange checkout: the
# /wa-business/checkout-data callback only answers refusals and never reprices.
# https://developers.facebook.com/docs/whatsapp/cloud-api/payments-api/
#   payments-in/checkout-button-templates
# ═══════════════════════════════════════════════════════════════════════════

def _handle_order_details_template_send(
        message_id: str, contact_id: str, recipient_phone: str,
        phone_number_id: str, is_template: bool, template_name: str,
        template_params: list, checkout_order_details: Dict,
        header_image_url: Optional[str], request_id: str,
        recipient_bsuid: Optional[str] = None) -> Dict[str, Any]:
    """
    Send the approved ORDER_DETAILS payment template (button `sub_type: order_details`).

    `checkout_order_details` is the caller's server-built order: reference_id, type
    (physical-goods/digital-goods), currency, shipping_info (physical goods only), order (items,
    subtotal, shipping, tax, discount, expiration) and total_amount. It must NOT carry
    `payment_settings`: those are built here, server-side, by `_build_payment_settings`
    (payment_gateway / razorpay / WECAREDIGITAL), and a caller-supplied block is refused.
    The template header is the fixed WECARE.DIGITAL image; no caller can substitute it.

    Reached only after `_refuse_unless_payment_ready` has pinned the template name, the WABA1
    sender, the configuration, INR and a live Meta/Razorpay readiness readback.
    """
    try:
        formatted_phone = _normalize_phone_number(recipient_phone)
        whatsapp_phone = f"+{formatted_phone}"

        # The pinned payment template is approved in exactly one language on WABA1 ('en'), so the
        # caller cannot choose another; a leading language-looking param is still stripped so a
        # legacy caller's params do not leak into the (variable-free) body.
        template_language = WA_PAY_TEMPLATE_LANGUAGE
        actual_params = list(template_params) if template_params else []
        if actual_params and isinstance(actual_params[0], str) and (
                len(actual_params[0]) == 2 or '_' in actual_params[0]):
            actual_params = actual_params[1:]

        # A3.8 — the RESOLVER owns Mode 3. This branch used to take the caller's
        # `payment_settings` when present and only build them when absent, which made the
        # resolver's three refusals optional for any caller that supplied its own block. No
        # caller supplies them any more; refusing closes the door so a future one cannot.
        #
        # It raises the EXISTING exception rather than inventing one, so every caller is
        # fail-closed on day one: a new type would need every caller updated before it refused
        # anything.
        if checkout_order_details.get('payment_settings'):
            raise PaymentConfigurationUnresolved(
                'payment_settings may not be supplied by a caller; the resolver owns Mode 3')

        # Sanitized BEFORE the payment settings are built, so the Razorpay `receipt` and
        # `notes.referenceId` carry exactly the reference Meta is sent (a minted reference
        # passes through byte-for-byte; only a legacy shape is rewritten).
        ref_id = _sanitize_reference_id(checkout_order_details.get('reference_id', ''))
        checkout_order_details['reference_id'] = ref_id
        payment_settings = _build_payment_settings(phone_number_id, checkout_order_details)

        # The order object; `payment_settings` is not part of it - it sits beside it inside the
        # order_details action built below.
        order_obj = checkout_order_details.get('order', {})

        # Ensure expiration has description (Meta requires it for templates)
        if 'expiration' not in order_obj:
            import time as _time
            order_obj['expiration'] = {
                'timestamp': str(int(_time.time()) + 86400),
                'description': 'Order expires in 24 hours',
            }
        elif not order_obj.get('expiration', {}).get('description'):
            order_obj['expiration']['description'] = 'Order expires in 24 hours'

        # Ensure discount has a description (Meta requires one), and name the fixed DELIGHT policy
        # "Delight" from the canonical label. A description the caller already set is preserved; a
        # legacy discount with none falls back to a generic "Discount" rather than being
        # mislabelled as the policy. The DELIGHT code is read off the order the authoritative
        # checkout built, never inferred from the amount.
        if 'discount' in order_obj:
            is_delight = (str(checkout_order_details.get('couponCode')
                              or order_obj.get('couponCode') or '').strip().upper()
                          == default_coupon.DELIGHT_CODE)
            if is_delight:
                order_obj['discount']['description'] = default_coupon.DISPLAY_LABEL
            elif not order_obj['discount'].get('description'):
                order_obj['discount']['description'] = 'Discount'
        # `couponCode` is our internal DELIGHT marker, read just above. Meta's `order` object
        # documents no such key and its order_details schema refuses unexpected keys (error 100,
        # as with the item keys sanitised below), so it never travels to Meta. The catalog cart
        # checkout writes it into `order` on every Delight-discounted cart.
        order_obj.pop('couponCode', None)

        # Calculate total_amount if not provided
        total_amount = checkout_order_details.get('total_amount', {})
        if not total_amount.get('value'):
            subtotal = order_obj.get('subtotal', {}).get('value', 0)
            shipping = order_obj.get('shipping', {}).get('value', 0)
            tax = order_obj.get('tax', {}).get('value', 0)
            discount = order_obj.get('discount', {}).get('value', 0)
            total_amount = {'offset': 100, 'value': subtotal + shipping + tax - discount}

        order_details_action = {
            'reference_id': ref_id,
            'type': checkout_order_details.get('type', 'physical-goods'),
            'currency': checkout_order_details.get('currency', 'INR'),
            'payment_settings': payment_settings,
            'order': order_obj,
            'total_amount': total_amount,
        }

        # Delivery must already be priced before the payment is reserved. An empty address
        # chooser advertises a callback that deliberately cannot reprice this payment.
        if order_details_action['type'] == 'physical-goods':
            shipping_info = checkout_order_details.get('shipping_info') or {}
            if not shipping_info.get('addresses'):
                return _error_response(400, 'Complete delivery details in checkout before requesting payment')
            order_details_action['shipping_info'] = shipping_info

        # Ensure all items have required India compliance fields
        WECARE_IMPORTER = business_identity.meta_importer_fields()
        # Meta's order_details item schema is strict — any extra key (e.g. our
        # per-item 'gstRate') causes error 100 "Unexpected key ...". Keep only the
        # keys Meta allows, then add India-compliance defaults.
        _ALLOWED_ITEM_KEYS = {
            'retailer_id', 'name', 'image', 'amount', 'sale_amount', 'quantity',
            'country_of_origin', 'importer_name', 'importer_address',
        }
        _sanitized_items = []
        for item in order_obj.get('items', []):
            clean_item = {k: v for k, v in item.items() if k in _ALLOWED_ITEM_KEYS}
            # Final-boundary guard: every Meta ORDER_DETAILS item gets the one owner-approved
            # default thumbnail, regardless of what an upstream caller supplied.
            if str(clean_item.get('name') or '').strip() == 'Convenience fee':
                clean_item.pop('image', None)
            else:
                clean_item['image'] = {'link': DEFAULT_ORDER_ITEM_THUMBNAIL}
            if not clean_item.get('importer_name'):
                clean_item.update(WECARE_IMPORTER)
            if not clean_item.get('country_of_origin'):
                clean_item['country_of_origin'] = 'India'
            _sanitized_items.append(clean_item)
        if 'items' in order_obj:
            order_obj['items'] = _sanitized_items

        # Build template components
        components = []

        # Header (image) — wecare_whatapp_native_pay_template template REQUIRES an image header.
        # FIXED company-logo header on EVERY payment, by owner decision 2026-10-07:
        # the same WECARE.DIGITAL logo on every payment message, never varied per order.
        # Neither the per-call `header_image_url` nor an order-level `header_image_id` is
        # honoured for the payment template, so no caller can substitute a different image.
        # (No caller sends `header_image_id`; it used to be accepted here despite this rule.)
        FIXED_CHECKOUT_HEADER = ORDER_CATALOG_HEADER_IMAGE
        components.append({
            'type': 'header',
            'parameters': [{
                'type': 'image',
                'image': {'link': FIXED_CHECKOUT_HEADER},
            }],
        })

        # Body parameters
        if actual_params:
            components.append({
                'type': 'body',
                'parameters': [{'type': 'text', 'text': str(p)} for p in actual_params],
            })

        # The ORDER_DETAILS button ("Review and Pay") — always index 0
        components.append({
            'type': 'button',
            'sub_type': 'order_details',
            'index': 0,
            'parameters': [{
                'type': 'action',
                'action': {
                    'order_details': order_details_action,
                },
            }],
        })

        # Build full payload
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': whatsapp_phone,
            'type': 'template',
            'template': {
                # The server constant, not the request field: the gate has already refused any
                # other name, and the wire value cannot drift from what the gate proved.
                'name': WA_PAY_TEMPLATE,
                'language': {
                    'policy': 'deterministic',
                    'code': template_language,
                },
                'components': components,
            },
        }

        if recipient_bsuid:
            payload['recipient'] = recipient_bsuid

        logger.info(json.dumps({
            'event': 'checkout_template_payload_built',
            'templateName': template_name,
            'language': template_language,
            'referenceId': ref_id,
            'goodsType': order_details_action.get('type'),
            'itemCount': len(order_details_action.get('order', {}).get('items', [])),
            'totalAmount': order_details_action.get('total_amount', {}).get('value', 0),
            'hasShippingInfo': 'shipping_info' in order_details_action,
            # Always the fixed header; caller header overrides are ignored on this template.
            'hasHeaderImage': True,
            'bodyParamCount': len(actual_params),
            'requestId': request_id,
        }))

        # Send via Meta API
        response = _send_message(phone_number_id, payload)
        whatsapp_message_id = response.get('messageId', '')

        # Store message record
        item_names = ', '.join(
            i.get('name', '') for i in order_details_action.get('order', {}).get('items', [])
        )
        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=f'[Checkout: {template_name}] {item_names} — Ref: {ref_id}',
            status=WA_INITIAL_STATUS,
            is_template=True,
            whatsapp_message_id=whatsapp_message_id,
            phone_number_id=phone_number_id,
            recipient_bsuid=recipient_bsuid,
            # ── the two fields that make this row RESOLVABLE by payment reference ──
            #
            # This branch used to pass nothing payment-shaped, so the outbound row for a
            # checkout-template send carried no `paymentReferenceId`. The consequence was not
            # cosmetic: `razorpay-webhook._resolve_originating_phone` queries
            # `paymentReferenceId-index` as its layer 2, and the InboundTable `payment_request`
            # row its layer 3 reads is written only in the interactive branch - so BOTH layers
            # missed for a native send, the resolution fell through to the WABA1 fallback, and
            # `razorpay_phone_unresolved_using_primary` would fire at WARNING on EVERY native
            # capture. That is noise on the exact signal that exists to catch a cross-WABA
            # mistake.
            #
            # `total_amount.value` is integer paise by construction on this path.
            payment_reference_id=ref_id,
            payment_amount_paise=order_details_action.get(
                'total_amount', {}).get('value') or None,
        )

        _emit_delivery_metric('success', is_template=True)

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messageId': message_id,
                'whatsappMessageId': whatsapp_message_id,
                'status': 'sent',
                'mode': 'LIVE',
                'type': 'checkout_template',
                'templateName': template_name,
                'referenceId': ref_id,
            }),
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(json.dumps({
            'event': 'checkout_template_send_error',
            'messageId': message_id,
            'templateName': template_name,
            'error': error_msg,
            'requestId': request_id,
        }))
        _emit_delivery_metric('failed', is_template=True)
        return _error_response(500, f'Failed to send checkout template: {error_msg}')


def _handle_interactive_send(message_id: str, contact_id: str, recipient_phone: str,
                              phone_number_id: str, interactive_type: str,
                              interactive_data: Dict, request_id: str,
                              recipient_bsuid: Optional[str] = None) -> Dict[str, Any]:
    """
    Send interactive messages (location request, CTA URL, flow, address, catalog).

    The menu-shaped types - list, button, product and product_list - were deleted
    on 2026-10-02 with every other WhatsApp menu. A request for one of them now
    gets the JSON error from the `else` arm below rather than a send.

    Interactive Types:
    - location_request: Request user's location
    - cta_url: Call-to-action URL button
    - flow: WhatsApp Flow trigger
    - address_message: India Address Message (checkout delivery address)
    - catalog_message: "View catalog" button onto the Meta product catalogue

    Per WhatsApp Business API docs:
    https://developers.facebook.com/docs/whatsapp/guides/interactive-messages/
    https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-cta-url-messages/
    """
    try:
        # Normalize phone number
        formatted_phone = _normalize_phone_number(recipient_phone)
        whatsapp_phone = f"+{formatted_phone}"
        
        # Base payload
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': whatsapp_phone,
            'type': 'interactive'
        }
        # Add BSUID recipient if available (per Meta BSUID docs)
        if recipient_bsuid:
            payload['recipient'] = recipient_bsuid
        
        # Build interactive payload based on type
        if interactive_type == 'location_request':
            # Location request message
            body_text = interactive_data.get('body', 'Please share your location')
            
            interactive_payload = {
                'type': 'location_request_message',
                'body': {'text': body_text},
                'action': {'name': 'send_location'}
            }
            
            payload['interactive'] = interactive_payload
        
        elif interactive_type == 'cta_url':
            # Call-to-action URL button message
            # Per Meta docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-cta-url-messages/
            header_text = interactive_data.get('header', '')
            header_type = interactive_data.get('headerType', 'text')
            body_text = interactive_data.get('body', 'Click the button below')
            footer_text = interactive_data.get('footer', '')
            button_text = interactive_data.get('buttonText', 'Visit')[:20]  # Max 20 chars
            url = interactive_data.get('url', '')
            
            if not url:
                return _error_response(400, 'url is required for cta_url type')
            
            interactive_payload = {
                'type': 'cta_url',
                'body': {'text': body_text},
                'action': {
                    'name': 'cta_url',
                    'parameters': {
                        'display_text': button_text,
                        'url': url
                    }
                }
            }
            
            # Add header if provided
            if header_text:
                if header_type == 'text':
                    interactive_payload['header'] = {'type': 'text', 'text': header_text}
                elif header_type == 'image':
                    interactive_payload['header'] = {
                        'type': 'image',
                        'image': {'link': interactive_data.get('headerMedia', '')}
                    }
                elif header_type == 'video':
                    interactive_payload['header'] = {
                        'type': 'video',
                        'video': {'link': interactive_data.get('headerMedia', '')}
                    }
            
            # Add footer if provided
            if footer_text:
                interactive_payload['footer'] = {'text': footer_text}
            
            payload['interactive'] = interactive_payload
        
        elif interactive_type == 'flow':
            # WhatsApp Flow trigger message
            # Per Meta docs: https://developers.facebook.com/docs/whatsapp/flows/
            header_text = interactive_data.get('header', '')
            body_text = interactive_data.get('body', 'Start the flow')
            footer_text = interactive_data.get('footer', '')
            flow_id = interactive_data.get('flowId', '')
            flow_cta = interactive_data.get('flowCta', 'Start')[:20]
            flow_action = interactive_data.get('flowAction', 'navigate')  # navigate or data_exchange
            flow_token = interactive_data.get('flowToken', str(uuid.uuid4()))
            screen_id = interactive_data.get('screenId', '')  # First screen to show
            flow_data = interactive_data.get('flowData', {})  # Data to pass to flow
            
            if not flow_id:
                return _error_response(400, 'flowId is required for flow type')
            
            interactive_payload = {
                'type': 'flow',
                'body': {'text': body_text},
                'action': {
                    'name': 'flow',
                    'parameters': {
                        'flow_message_version': '3',
                        'flow_token': flow_token,
                        'flow_id': flow_id,
                        'flow_cta': flow_cta,
                        'flow_action': flow_action
                    }
                }
            }
            
            # flow_action_payload is ONLY valid for "navigate" mode.
            # For "data_exchange", Meta sends INIT to the endpoint automatically —
            # do NOT include flow_action_payload or Meta returns error 131009.
            if flow_action == 'navigate' and screen_id:
                interactive_payload['action']['parameters']['flow_action_payload'] = {
                    'screen': screen_id
                }
                if flow_data:
                    interactive_payload['action']['parameters']['flow_action_payload']['data'] = flow_data
            
            # Add header if provided
            if header_text:
                interactive_payload['header'] = {'type': 'text', 'text': header_text}
            
            # Add footer if provided
            if footer_text:
                interactive_payload['footer'] = {'text': footer_text}
            
            payload['interactive'] = interactive_payload
            
        elif interactive_type == 'address_message':
            # Native India Address Message — collect a shipping address for physical
            # goods. Docs: interactive.type=address_message, action.name=address_message,
            # parameters.country (ISO code) is REQUIRED. India-only feature.
            body_text = interactive_data.get('body',
                "Thanks for your order! Please share the delivery address.")
            params = {'country': interactive_data.get('country', 'IN')}
            _vals = interactive_data.get('values')
            if _vals:
                params['values'] = _vals
            _saved = interactive_data.get('savedAddresses') or interactive_data.get('saved_addresses')
            if _saved:
                params['saved_addresses'] = _saved
            _verr = interactive_data.get('validationErrors') or interactive_data.get('validation_errors')
            if _verr:
                params['validation_errors'] = _verr
            interactive_payload = {
                'type': 'address_message',
                'body': {'text': str(body_text)[:1024]},
                'action': {'name': 'address_message', 'parameters': params},
            }
            if interactive_data.get('footer'):
                interactive_payload['footer'] = {'text': str(interactive_data['footer'])[:60]}
            if interactive_data.get('header'):
                interactive_payload['header'] = {'type': 'text', 'text': str(interactive_data['header'])[:60]}
            payload['interactive'] = interactive_payload

        elif interactive_type == 'catalog_message':
            # Full-catalog message — a "View catalog" button that opens the whole
            # product catalog in-chat (optional thumbnail via product_retailer_id).
            body_text = interactive_data.get('body', 'Browse our catalog and add items to your cart.')
            action = {'name': 'catalog_message'}
            thumb = interactive_data.get('thumbnailProductRetailerId') or interactive_data.get('thumbnail_product_retailer_id')
            if thumb:
                action['parameters'] = {'thumbnail_product_retailer_id': str(thumb)}
            interactive_payload = {
                'type': 'catalog_message',
                'body': {'text': str(body_text)[:1024]},
                'action': action,
            }
            if interactive_data.get('footer'):
                interactive_payload['footer'] = {'text': str(interactive_data['footer'])[:60]}
            payload['interactive'] = interactive_payload

        else:
            return _error_response(
                400, 'interactive messaging removed',
                f"'{interactive_type}' interactive sends were deleted on 2026-10-02; "
                "list, button, product and product_list are no longer supported")
        
        logger.info(json.dumps({
            'event': 'interactive_payload',
            'to': mask_phone(whatsapp_phone),
            'interactiveType': interactive_type,
            'payloadKeys': sorted(payload.keys()),
            'requestId': request_id
        }))
        
        # Call SendWhatsAppMessage API (Direct API)
        response = _send_message(phone_number_id, payload)
        
        whatsapp_message_id = response.get('messageId', '')
        
        # Store message record
        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=f'[Interactive: {interactive_type}] {interactive_data.get("body", "")}',
            status=WA_INITIAL_STATUS,
            is_template=False,
            whatsapp_message_id=whatsapp_message_id,
            phone_number_id=phone_number_id,
            recipient_bsuid=recipient_bsuid,
        )
        
        logger.info(json.dumps({
            'event': 'interactive_sent',
            'messageId': message_id,
            'whatsappMessageId': whatsapp_message_id,
            'contactId': mask_contact_id(contact_id),
            'interactiveType': interactive_type,
            'requestId': request_id
        }))
        
        # Emit success metric
        _emit_delivery_metric('success', is_template=False)
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messageId': message_id,
                'whatsappMessageId': whatsapp_message_id,
                'status': 'sent',
                'mode': 'LIVE',
                'type': 'interactive',
                'interactiveType': interactive_type
            })
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(json.dumps({
            'event': 'interactive_send_error',
            'messageId': message_id,
            'interactiveType': interactive_type,
            'error': error_msg,
            'requestId': request_id
        }))
        _emit_delivery_metric('failed', is_template=False)
        return _error_response(500, f'Failed to send interactive message: {error_msg}')


def _handle_live_send(message_id: str, contact_id: str, recipient_phone: str,
                      phone_number_id: str, content: str, media_file: Optional[str],
                      media_type: Optional[str], media_filename: Optional[str], is_template: bool, template_name: Optional[str],
                      template_params: list, within_window: bool, request_id: str,
                      is_payment_template: bool = False, order_details: Optional[Dict] = None,
                      header_image_url: Optional[str] = None, is_interactive_payment: bool = False,
                      is_otp_template: bool = False, otp_code: Optional[str] = None,
                      otp_button_type: Optional[str] = None,
                      recipient_bsuid: Optional[str] = None,
                      template_header_media: Optional[str] = None,
                      template_header_type: Optional[str] = None,
                      template_header_filename: Optional[str] = None,
                      template_header_location: Optional[Dict] = None,
                      template_flow_button: Optional[Dict] = None,
                      template_url_button: Optional[Dict] = None,
                      context_message_id: Optional[str] = None,
                      direct_send_category: Optional[str] = None,
                      direct_send_waba: str = '',
                      has_contact_record: bool = False,
                      is_lto_template: bool = False,
                      lto_expiration_ms: Optional[int] = None,
                      lto_offer_code: Optional[str] = None,
                      lto_copy_code_index: int = 0,
                      template_quick_reply_button: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Handle LIVE mode - call Meta Graph API (Direct API).
    Requirements: 5.2, 5.5, 5.6, 5.7, 5.8, 5.10, 5.11

    `direct_send_category` is set only when the caller decided this send is a
    Direct Send candidate: the service window is closed, the payload looks like
    plain text, and Direct Send is enabled for `direct_send_waba`. It defaults to
    None, so every other path through this function is unchanged.

    `has_contact_record` exists only so a fallback can reproduce the caller's
    refusal log exactly; it is not in the response body.
    """
    try:
        whatsapp_media_id = None
        s3_key = None
        stored_filename = None
        
        # Requirements 5.5, 5.6, 5.7: Handle media upload
        if media_file and media_type:
            # Use provided filename from frontend, or extract from path
            filename = media_filename
            if not filename and isinstance(media_file, str) and '/' in media_file:
                filename = media_file.split('/')[-1]
            
            s3_key, whatsapp_media_id, stored_filename = _upload_media(media_file, media_type, message_id, phone_number_id, request_id, filename)
            if not whatsapp_media_id:
                return _error_response(500, 'Failed to upload media')

        # Resolve a template media header (IMAGE/VIDEO/DOCUMENT) into a sendable
        # reference. A public https link, or a pre-resolved WhatsApp media id (digits
        # only), is passed through as-is; an S3 key is uploaded to the WhatsApp media API
        # and replaced with its media id so private-bucket files work without exposing a
        # public URL. The type check mirrors _build_message_payload, the only reader.
        #
        # A key that cannot be resolved is refused HERE. It used to fall through and reach
        # Meta as `image.id = "<s3 key>"`, so a paid invoice whose header upload failed was
        # rejected by Meta instead of locally, with nothing a caller could act on. The
        # invoice engine reads any status >= 400 from this function as definite
        # non-delivery and releases its one-delivery claim, so the send stays retryable.
        resolved_header_media = template_header_media
        header_ref = str(template_header_media or '')
        if (is_template and header_ref
                and template_header_type in ('image', 'video', 'document')
                and not header_ref.startswith('http') and not header_ref.isdigit()):
            _hdr_media_id = None
            try:
                _, _hdr_media_id, _ = _upload_media(
                    template_header_media, template_header_type, message_id,
                    phone_number_id, request_id, template_header_filename
                )
            except Exception as _he:  # noqa: BLE001 - any failure is a refusal below
                # The class only: an exception string from the media API can echo the request.
                logger.error(json.dumps({
                    'event': 'template_header_media_resolve_error',
                    'templateName': template_name,
                    'errorType': type(_he).__name__, 'requestId': request_id
                }))
            if not _hdr_media_id:
                logger.error(json.dumps({
                    'event': 'template_header_media_resolve_failed',
                    'templateName': template_name, 'requestId': request_id
                }))
                return _error_response(500, 'Failed to upload template header media')
            resolved_header_media = _hdr_media_id

        # Build WhatsApp message payload
        message_payload = _build_message_payload(
            recipient_phone, content, media_type, whatsapp_media_id,
            is_template, template_name, template_params, stored_filename,
            is_payment_template, order_details, header_image_url, is_interactive_payment,
            is_otp_template, otp_code, otp_button_type,
            phone_number_id=phone_number_id,
            recipient_bsuid=recipient_bsuid,
            template_header_media=resolved_header_media,
            template_header_type=template_header_type,
            template_header_filename=template_header_filename,
            template_header_location=template_header_location,
            template_flow_button=template_flow_button,
            template_url_button=template_url_button,
            template_quick_reply_button=template_quick_reply_button,
            context_message_id=context_message_id,
            direct_send_category=direct_send_category,
            is_lto_template=is_lto_template,
            lto_expiration_ms=lto_expiration_ms,
            lto_offer_code=lto_offer_code,
            lto_copy_code_index=lto_copy_code_index
        )

        # The builder is the arbiter, so believe it over the pre-check.
        #
        # If a Direct Send was requested and the built payload carries no
        # `category`, the request was not actually plain text — the likely cause
        # is a JSON `content` string that routed into contacts/location. Falling
        # back here means that send gets today's 403 instead of leaving the
        # service window as a free-form non-text message and collecting a 131047.
        # Fail closed to today's behaviour, every time the two disagree.
        if direct_send_category and 'category' not in message_payload:
            logger.info(json.dumps({
                'event': 'direct_send_not_eligible',
                'payloadType': message_payload.get('type'),
                'wabaId': direct_send_waba,
                'requestId': request_id,
            }))
            return _outside_window_refusal(contact_id, has_contact_record, request_id)

        logger.info(json.dumps({
            'event': 'message_payload_built',
            'messageId': message_id,
            'contactId': mask_contact_id(contact_id),
            'recipientPhone': mask_phone(recipient_phone),
            'normalizedPhone': mask_phone(message_payload.get('to')),
            'payloadType': message_payload.get('type'),
            'hasMedia': bool(whatsapp_media_id),
            'mediaId': whatsapp_media_id,
            # Not the payload itself. It carries an unmasked `to` and the message body,
            # and this same dict masks `recipientPhone` and `normalizedPhone` two lines
            # above -- so dumping the whole thing gave back exactly what the masking had
            # just removed. The keys are what a "was it built right" log needs.
            'payloadKeys': sorted(message_payload.keys()),
            'requestId': request_id
        }))
        
        # Requirement 5.8: Call SendWhatsAppMessage API.
        # For durable keyed sends, attach the stable internal id as Meta's opaque callback data.
        # Meta echoes this field on status webhooks, so an ambiguous local timeout can reconcile
        # the original row even when the HTTP response (and therefore WAMID) was never observed.
        keyed_send = message_id.startswith('wa-idem-')
        if keyed_send:
            message_payload['biz_opaque_callback_data'] = message_id
        # Note: message parameter should be a string, not bytes
        message_json = json.dumps(message_payload)
        
        logger.info(json.dumps({
            'event': 'calling_send_whatsapp_message_api',
            'messageId': message_id,
            'phoneNumberId': phone_number_id,
            'messageJsonBytes': len(message_json),
            'requestId': request_id
        }))
        
        # Retry only explicit HTTP throttling/service responses. Network timeouts and connection
        # loss are ambiguous: Meta may already have accepted the message, so retrying can duplicate
        # it. Keyed business sends never retry at this boundary; their caller must reconcile first.
        max_retries = 0 if keyed_send else 3
        last_error = None
        provider_call_started = False
        for attempt in range(max_retries + 1):
            try:
                provider_call_started = True
                response = _send_direct_api(phone_number_id, message_json)
                last_error = None
                break
            except Exception as e:
                retryable_http = (
                    isinstance(e, urllib.error.HTTPError)
                    and getattr(e, 'code', 0) in (429, 500, 502, 503, 504)
                )
                if retryable_http and attempt < max_retries:
                    wait_time = min(2 ** attempt, 8)
                    logger.warning(json.dumps({
                        'event': 'send_http_retry',
                        'attempt': attempt + 1,
                        'waitSeconds': wait_time,
                        'httpCode': getattr(e, 'code', None),
                        'messageId': message_id,
                        'requestId': request_id
                    }))
                    time.sleep(wait_time)
                    last_error = e
                else:
                    raise
        
        if last_error:
            raise last_error
        
        whatsapp_message_id = response.get('messageId', '')
        
        # Persist the canonical wa_id returned by Meta so the contact resolves
        # consistently in the inbox. (Profile name/BSUID arrive on the inbound reply.)
        try:
            if response.get('waId') and contact_id:
                _enrich_contact_identity(contact_id, response.get('waId'))
        except Exception:
            pass
        
        payment_ref_id = None
        payment_amount_paise = None
        stored_content = content
        # Templates: guarantee a displayable content string so the sent template
        # shows in the conversation thread (the empty-content guard below would
        # otherwise skip template sends, which carry no free-form `content`).
        if is_template and not stored_content:
            stored_content = f'[Template] {template_name}' if template_name else '[Template message]'
        if is_interactive_payment and order_details:
            payment_ref_id = _sanitize_reference_id(order_details.get('reference_id', ''))
            # Calculate total amount in rupees from order_details
            order_data = order_details.get('order', {})
            total_amt = order_data.get('total_amount', {})
            # INTEGER PAISE throughout, with no multiply and no divide. This value is PERSISTED
            # by `_store_message_record` and is read back on confirmation, so it is money of
            # record rather than a display figure - the two divisions that used to be here made
            # it a float on the way in and a float on the way out.
            if not total_amt:
                # total_amount may be at parameters level in built payload
                subtotal_val = int(order_data.get('subtotal', {}).get('value', 0) or 0)
                discount_val = int(order_data.get('discount', {}).get('value', 0) or 0)
                shipping_val = int(order_data.get('shipping', {}).get('value', 0) or 0)
                tax_val = int(order_data.get('tax', {}).get('value', 0) or 0)
                payment_amount_paise = subtotal_val - discount_val + shipping_val + tax_val
            else:
                # Refused rather than divided by `offset`. Meta's `order_details` amounts are
                # minor units with `offset: 100`, so the value IS paise; dividing it was what
                # introduced the float in the first place.
                raw_value = total_amt.get('value', 0)
                if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                    raise ValueError('order_details total_amount.value must be integer paise')
                payment_amount_paise = raw_value
            # Build rich content for inbox display
            item_name = order_details.get('itemName', 'Payment')
            stored_content = (f'[Payment: ₹{pay_status.rupees_str(payment_amount_paise)} | '
                              f'{item_name} | Ref: {payment_ref_id}]')
        
        # Keep the original S3 object key for a template header in the authenticated Inbox.
        # Meta requires an uploaded media ID for the send, but that ID is not a downloadable
        # Inbox image. Without the S3 key, an invoice PNG is saved as a text-only template.
        # Never persist a presigned URL: messages-read signs private objects on each read.
        inbox_template_header_key = None
        if (is_template and template_header_media
                and template_header_type in ('image', 'video', 'document')):
            header_source = str(template_header_media)
            if not header_source.startswith(('http://', 'https://')) and not header_source.isdigit():
                inbox_template_header_key = media_paths.canonical(header_source)

        # Requirement 5.11: Store message record
        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=stored_content,
            status=WA_INITIAL_STATUS,
            is_template=is_template,
            whatsapp_message_id=whatsapp_message_id,
            media_id=whatsapp_media_id,
            # The body media (if present) takes precedence over the template header.
            s3_key=s3_key or inbox_template_header_key,
            phone_number_id=phone_number_id,
            payment_reference_id=payment_ref_id,
            payment_amount_paise=payment_amount_paise,
            recipient_bsuid=recipient_bsuid,
            # Template header media (public link) → shows the attachment in the inbox
            media_url=(resolved_header_media if (is_template and template_header_media
                       and str(resolved_header_media or '').startswith('http')) else None),
            is_direct_send=bool(direct_send_category),
        )
        
        # Store payment_request record for invoice generator lookup
        # The invoice engine scans for messageType='payment_request' + paymentReferenceId
        if is_interactive_payment and order_details and payment_ref_id:
            try:
                order_data = order_details.get('order', {})
                items_list = order_data.get('items', [])
                first_item_name = items_list[0].get('name', 'Service Fee') if items_list else order_details.get('itemName', 'Service Fee')
                subtotal_val = order_data.get('subtotal', {}).get('value', 0)
                discount_val = order_data.get('discount', {}).get('value', 0)
                shipping_val = order_data.get('shipping', {}).get('value', 0)
                tax_val = order_data.get('tax', {}).get('value', 0)
                
                # Calculate per-item GST total for gstRate field. `Decimal` rather than a
                # `float()` round-trip: this value is persisted as `paymentGstRate` and a GST
                # rate on a tax record is not a display figure.
                total_gst_rate = Decimal('0')
                if items_list:
                    weighted_sum = Decimal('0')
                    total_value = 0
                    for it in items_list:
                        it_val = int(it.get('amount', {}).get('value', 0)) * int(it.get('quantity', 1))
                        it_rate = Decimal(str(it.get('gstRate', 0) or 0))
                        weighted_sum += it_val * it_rate
                        total_value += it_val
                    if total_value > 0:
                        total_gst_rate = weighted_sum / total_value  # Weighted average GST rate
                
                # Look up contact for customer details
                contact_info = _get_contact(contact_id) if contact_id else None
                c_name = (contact_info or {}).get('name', '')
                c_phone = (contact_info or {}).get('phone', recipient_phone or '')
                c_email = (contact_info or {}).get('email', '')
                c_ship = (contact_info or {}).get('shippingAddress', '')
                c_bill = (contact_info or {}).get('billingAddress', '')
                
                pay_req_record = {
                    'id': str(uuid.uuid4()),
                    'messageId': payment_ref_id,
                    'contactId': contact_id,
                    'channel': 'whatsapp',
                    'direction': 'outbound',
                    'messageType': 'payment_request',
                    'content': stored_content,
                    'paymentReferenceId': payment_ref_id,
                    'paymentAmount': Decimal(str(subtotal_val)),
                    'paymentOffset': Decimal('100'),
                    'paymentCurrency': 'INR',
                    'paymentItemName': first_item_name,
                    'paymentItemCount': len(items_list),
                    'paymentQuantity': int(items_list[0].get('quantity', 1)) if items_list else 1,
                    'paymentSubtotal': Decimal(str(subtotal_val)),
                    'paymentDiscount': Decimal(str(discount_val)),
                    'paymentGstRate': Decimal(str(total_gst_rate)),
                    'paymentGstAmount': Decimal(str(tax_val)),
                    'paymentShipping': Decimal(str(shipping_val)),
                    'paymentTotal': Decimal(payment_amount_paise or 0),
                    'paymentGstin': business_identity.GSTIN,
                    'paymentSource': 'inbox_ui',
                    'paymentOrderId': order_details.get('orderId', 'Offline'),
                    'paymentCustomerName': c_name,
                    'paymentCustomerPhone': c_phone,
                    'paymentCustomerEmail': c_email,
                    'paymentShippingAddress': c_ship,
                    'paymentBillingAddress': c_bill,
                    'paymentConfigName': order_details.get('payment_configuration', PHONE_PAYMENT_CONFIG.get(phone_number_id, DEFAULT_PAYMENT_CONFIG)),
                    'awsPhoneNumberId': phone_number_id or '',
                    'status': 'pending',
                    'senderPhone': recipient_phone or '',
                    'createdAt': Decimal(str(int(time.time()))),
                    'expiresAt': Decimal(str(int(time.time()) + 86400 * 30)),
                }
                # Store in INBOUND table — invoice generator scans WhatsAppInboundTable
                inbound_table_name = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
                inbound_table = dynamodb.Table(inbound_table_name)
                inbound_table.put_item(Item={k: v for k, v in pay_req_record.items() if v is not None and v != '' and v != Decimal('0') or k in ('paymentDiscount', 'paymentShipping')})
                # Unified Inbox dual-write — mirror the payment_request to the canonical
                # MessagesTable so the dashboard (which reads canonical) shows payments.
                # Add `timestamp` (GSI sort key) so it's queryable via channel/contactId index.
                try:
                    _canon = dict(pay_req_record)
                    _canon['timestamp'] = _canon.get('createdAt') or Decimal(str(int(time.time())))
                    dynamodb.Table(
                        os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
                    ).put_item(Item={k: v for k, v in _canon.items() if v is not None and v != '' and v != Decimal('0') or k in ('paymentDiscount', 'paymentShipping')})
                except Exception as _ce:
                    logger.warning(f'payment_request canonical mirror skipped: {_ce}')
                logger.info(json.dumps({
                    'event': 'payment_request_record_stored',
                    'referenceId': payment_ref_id,
                    'contactId': mask_contact_id(contact_id),
                    'requestId': request_id,
                }))
            except Exception as pr_err:
                logger.warning(json.dumps({
                    'event': 'payment_request_record_error',
                    'referenceId': payment_ref_id,
                    'error': str(pr_err),
                    'requestId': request_id,
                }))
        
        logger.info(json.dumps({
            'event': 'message_sent',
            'messageId': message_id,
            'whatsappMessageId': whatsapp_message_id,
            'contactId': mask_contact_id(contact_id),
            'isTemplate': is_template,
            'hasMedia': bool(whatsapp_media_id),
            'requestId': request_id
        }))
        
        # Requirement 14.4: Emit success metric
        _emit_delivery_metric('success', is_template)
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messageId': message_id,
                'whatsappMessageId': whatsapp_message_id,
                'status': 'sent',
                'mode': 'LIVE'
            })
        }
        
    except urllib.error.HTTPError as e:
        # Handle Meta API HTTP errors. Parse the Meta error envelope so we capture
        # the specific error CODE (e.g. 131047, 131026, 131009) + message and store
        # them on the failed message for a UI tooltip explaining the reason.
        error_body = getattr(e, 'meta_error_body', None)
        if error_body is None:
            error_body = e.read().decode('utf-8') if e.fp else ''
        http_code = e.code
        meta_code = None
        meta_message = ''
        meta_details = ''
        try:
            parsed = json.loads(error_body) if error_body else {}
            err_obj = parsed.get('error', {}) if isinstance(parsed, dict) else {}
            meta_code = err_obj.get('code')
            meta_message = err_obj.get('message', '') or ''
            meta_details = (err_obj.get('error_data', {}) or {}).get('details', '') or ''
        except (json.JSONDecodeError, AttributeError):
            pass

        # ── Direct Send fallback: never lose a message to a Direct Send error ──
        #
        # Returning HERE, before `_store_message_record(status='failed')` and
        # `_emit_delivery_metric('failed', ...)` below, is what makes the fallback
        # identical to flag-off in DynamoDB and in metrics, not merely on the wire.
        # No row is written before the send on this path, so an early return leaves
        # exactly the state a flag-off refusal leaves.
        #
        # NEVER auto-retry as a template. Choosing one would mean guessing which
        # template matches this body, and a wrong guess sends the customer a
        # different message. The 403 is what the caller already handles today.
        # The log-safe view of the same error: redacted and bounded free text.
        _meta_log = graph_errors.log_fields(error_body, http_code)
        if direct_send_category:
            _ds_kind = direct_send.classify_error(meta_code, meta_details)
            _ds_log = {
                'wabaId': direct_send_waba,
                'metaCode': meta_code,
                # Meta's description of OUR request: how the classifier gets tightened once a
                # real 100 has been seen. Redacted and bounded, because details can echo it.
                'metaDetails': _meta_log['metaDetails'],
                'requestId': request_id,
            }
            if _ds_kind == direct_send.NOT_ONBOARDED:
                logger.warning(json.dumps({
                    'event': 'direct_send_not_onboarded',
                    'note': 'WABA is not onboarded to Direct Send — clear it from '
                            'DIRECT_SEND_ENABLED_WABAS',
                    **_ds_log,
                }))
                return _outside_window_refusal(contact_id, has_contact_record, request_id)
            if _ds_kind == direct_send.RESTRICTED:
                # ERROR, and alarm-worthy. Meta's enforcement ladder escalates on a
                # timer, so an unmonitored first strike is how an account reaches a
                # 7-day restriction.
                logger.error(json.dumps({
                    'event': 'direct_send_restricted',
                    'note': 'Direct Send access restricted or capped by Meta '
                            'enforcement — investigate category misclassification',
                    **_ds_log,
                }))
                return _outside_window_refusal(contact_id, has_contact_record, request_id)
            if _ds_kind == direct_send.OTHER_100:
                # A 100 we did not predict is our bug, not Meta's gate.
                logger.error(json.dumps({
                    'event': 'direct_send_rejected',
                    'note': 'Direct Send request rejected for an unclassified reason '
                            '— treat as our defect',
                    'metaMessage': _meta_log['metaMessage'],
                    'metaSubcode': _meta_log['metaSubcode'],
                    'fbtraceId': _meta_log['fbtraceId'],
                    **_ds_log,
                }))
                return _outside_window_refusal(contact_id, has_contact_record, request_id)
            # Any non-Direct-Send error falls through to the existing handling,
            # untouched.

        is_throttled = http_code == 429 or meta_code in (4, 80007, 130429, 131056) or 'throttl' in error_body.lower()

        # lambda_utils.graph_errors already normalizes Meta's envelope and was
        # covered by tests, but no handler imported it: error_subcode was dropped
        # on the floor, and "permanent vs transient" was a narrow throttle string
        # match rather than a classification. Two codes with the same number can
        # differ only by subcode, so losing it loses the reason.
        # normalize() returns a NESTED envelope, {'error': {...}} - reading the
        # top level silently yields None for every field.
        try:
            normalized = graph_errors.normalize(error_body, http_code).get('error', {})
        except Exception:  # noqa: BLE001 - classification must never break the error path
            normalized = {}
        error_subcode = normalized.get('error_subcode')
        fbtrace_id = normalized.get('fbtrace_id')
        # Prefer the per-code retry flag the error table already carries; fall back
        # to the normalizer's status-based judgement.
        table_entry = META_MESSAGE_ERRORS.get(meta_code) if meta_code else None
        if table_entry is not None:
            is_transient = bool(table_entry.get('retry'))
        else:
            is_transient = bool(normalized.get('is_transient', is_throttled))

        logger.error(json.dumps({
            'event': 'send_meta_error',
            'messageId': message_id,
            'httpCode': http_code,
            'metaCode': meta_code,
            'metaSubcode': error_subcode,
            'fbtraceId': fbtrace_id,
            'classification': 'transient' if is_transient else 'permanent',
            'metaMessage': _meta_log['metaMessage'],
            'metaDetails': _meta_log['metaDetails'],
            'requestId': request_id,
        }))
        # A distinct event name, emitted ALONGSIDE the generic one above rather than
        # instead of it. An ownership refusal has a different remedy from every other
        # send failure — it is fixed in the Meta Business Suite routing configuration,
        # not in the payload — so it needs a metric filter that cannot be diluted by
        # the general failure stream.
        if meta_code in ROUTING_OWNERSHIP_ERRORS:
            logger.error(json.dumps({
                'event': 'routing_ownership_rejected',
                'metaCode': meta_code,
                'metaSubcode': error_subcode,
                'fbtraceId': fbtrace_id,
                'messageId': message_id,
                'requestId': request_id,
            }))

        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=content,
            status='failed',
            is_template=is_template,
            error_details={
                'type': 'throttling' if is_throttled else 'meta_error',
                'code': meta_code,
                'subcode': error_subcode,
                'classification': 'transient' if is_transient else 'permanent',
                'fbtraceId': fbtrace_id,
                'message': meta_message or error_body[:500],
                'details': meta_details,
            },
            error_code=meta_code,
            phone_number_id=phone_number_id,
            recipient_bsuid=recipient_bsuid,
        )
        _emit_delivery_metric('failed', is_template)
        if is_throttled:
            return _error_response(429, 'API rate limit exceeded')
        return _error_response(
            400,
            f'WhatsApp error {meta_code}: {meta_message}' if meta_code else f'Failed to send message: HTTP {http_code}',
            message=meta_details or None,
        )
        
    except Exception as e:
        # Requirement 5.10: Store error details
        error_msg = str(e)
        error_type = type(e).__name__
        
        # mask_phone was imported in this module and never called once. These two
        # fields were the only place the sender logged a customer's number in
        # cleartext, and CloudWatch retention on this function is indefinite.
        logger.error(json.dumps({
            'event': 'send_api_error',
            'messageId': message_id,
            'error': error_msg,
            'errorType': error_type,
            'recipientPhone': mask_phone(recipient_phone),
            'normalizedPhone': mask_phone(
                message_payload.get('to') if 'message_payload' in locals() else ''
            ) or 'unknown',
            'requestId': request_id
        }))
        
        ambiguous_keyed_send = bool(
            message_id.startswith('wa-idem-')
            and locals().get('provider_call_started')
        )
        stored_status = 'unknown' if ambiguous_keyed_send else 'failed'
        _store_message_record(
            message_id=message_id,
            contact_id=contact_id,
            content=content,
            status=stored_status,
            error_details={
                'type': 'ambiguous_delivery' if ambiguous_keyed_send else error_type,
                'message': error_msg,
            },
            phone_number_id=phone_number_id
        )
        # Unknown provider outcomes are alarm-worthy but must stay non-retryable until reconciled.
        _emit_delivery_metric('failed', is_template)
        if ambiguous_keyed_send:
            logger.error(json.dumps({
                'event': 'delivery_outcome_unknown',
                'messageId': message_id,
                'phoneNumberId': phone_number_id,
                'requestId': request_id,
            }))
            return _error_response(
                503,
                'DELIVERY_OUTCOME_UNKNOWN',
                'Provider outcome is unknown. Await the status webhook or reconcile before retrying.')
        return _error_response(500, f'Failed to send message: {error_msg}')


def _public_media_folder(media_type: str) -> str:
    """Map a media type/category to its public wa-tpl/ subfolder.

    Accepts either a generic category ('image'/'video'/'document'/'audio'/
    'sticker') or a full MIME ('application/pdf', 'image/png', ...).
    """
    folders = {
        'image': 'img', 'video': 'vid', 'document': 'docs',
        'audio': 'aud', 'sticker': 'stk',
    }
    mt = (media_type or '').lower()
    if mt in folders:
        return folders[mt]
    if mt == 'image/webp':
        return 'stk'
    prefix = mt.split('/')[0] if '/' in mt else mt
    return folders.get(prefix, 'docs')


# Meta WhatsApp Cloud API media size limits, by public folder (bytes).
# Source: WhatsApp Business Platform "Supported Media Types".
_WA_MEDIA_MAX_SIZES = {
    'docs': 100 * 1024 * 1024,  # 100 MB
    'img': 5 * 1024 * 1024,     # 5 MB
    'vid': 16 * 1024 * 1024,    # 16 MB
    'aud': 16 * 1024 * 1024,    # 16 MB
    'stk': 500 * 1024,          # 500 KB
}


def _wa_media_max_size(media_type: str) -> int:
    """Return Meta's max upload size (bytes) for the given media type/category."""
    return _WA_MEDIA_MAX_SIZES.get(_public_media_folder(media_type), 100 * 1024 * 1024)


def _get_media_upload_url(body: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """
    Generate a presigned S3 PUT URL so the browser can upload media directly to S3,
    bypassing the API Gateway (10MB) and Lambda (6MB) request-payload limits.

    Request body: { "action": "getUploadUrl", "mediaType": "<mime>", "filename": "<name>", "reuse": <bool> }
    Response:     { "uploadUrl": "<presigned PUT>", "s3Key": "<key>", "contentType": "<mime>", "publicUrl": "<cdn url>", "expiresIn": 300 }

    By default the s3Key is placed under MEDIA_PREFIX (private) so that _upload_media's
    is_s3_key detection picks it up when /whatsapp/send is subsequently called with
    mediaFile=s3Key.

    When reuse=True (or target="public"), the file is placed in the public, reusable
    template-attachment folder (PUBLIC_MEDIA_PREFIX/{folder}/) and a stable CloudFront
    URL is returned as publicUrl. Passing that URL as a template header link lets
    WhatsApp fetch the file directly (correct content type for every attachment type)
    and lets the same attachment be re-sent across many templates without re-uploading.
    """
    try:
        media_type = (body.get('mediaType') or '').strip()
        filename = (body.get('filename') or body.get('mediaFileName') or '').strip()
        reuse = bool(body.get('reuse')) or (body.get('target') == 'public')

        # Resolve a sane content type + extension
        content_type = _get_content_type(media_type) if media_type else 'application/octet-stream'
        extension = _get_media_extension(media_type) if media_type else ''
        if not extension and '.' in filename:
            extension = '.' + filename.rsplit('.', 1)[-1].lower()

        short_id = uuid.uuid4().hex[:8]
        if reuse:
            # Public reusable folder, keeping the original filename so document
            # headers show a meaningful name to the recipient.
            folder = _public_media_folder(media_type)
            safe_filename = ''.join(
                c if c.isalnum() or c in '._-' else '_' for c in filename
            ) if filename else ''
            if safe_filename:
                s3_key = f"{PUBLIC_MEDIA_PREFIX}{folder}/wecare-digital-{short_id}_{safe_filename}"
            else:
                s3_key = f"{PUBLIC_MEDIA_PREFIX}{folder}/wecare-digital-{short_id}{extension or '.bin'}"

            # Hard server-side size guard: a presigned POST with a
            # content-length-range condition makes S3 ITSELF reject any upload
            # over Meta's per-type limit (the browser uploads directly, so this
            # is the only place the size can be enforced server-side).
            max_size = _wa_media_max_size(media_type)
            presigned_post = s3.generate_presigned_post(
                Bucket=MEDIA_BUCKET,
                Key=s3_key,
                Fields={
                    'Content-Type': content_type,
                    'Cache-Control': 'public, max-age=31536000',
                },
                Conditions=[
                    {'Content-Type': content_type},
                    {'Cache-Control': 'public, max-age=31536000'},
                    ['content-length-range', 1, max_size],
                ],
                ExpiresIn=300,  # 5 minutes
            )

            logger.info(json.dumps({
                'event': 'media_upload_post_generated',
                's3Key': s3_key,
                'mediaType': media_type,
                'contentType': content_type,
                'maxSize': max_size,
                'requestId': request_id,
            }))

            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({
                    'uploadMethod': 'POST',
                    'uploadUrl': presigned_post['url'],
                    'fields': presigned_post['fields'],
                    's3Key': s3_key,
                    'contentType': content_type,
                    # Stable public CDN URL — pass as a template header link to
                    # send without re-uploading to Meta, and reuse across sends.
                    'publicUrl': f"https://{CDN_DOMAIN}/{s3_key}",
                    'maxSize': max_size,
                    'expiresIn': 300,
                })
            }

        # Private path (default): presigned PUT into MEDIA_PREFIX.
        s3_key = f"{MEDIA_PREFIX}wecare-digital-{short_id}{extension or '.bin'}"

        upload_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': MEDIA_BUCKET,
                'Key': s3_key,
                'ContentType': content_type,
            },
            ExpiresIn=300,  # 5 minutes
        )

        logger.info(json.dumps({
            'event': 'media_upload_url_generated',
            's3Key': s3_key,
            'mediaType': media_type,
            'contentType': content_type,
            'requestId': request_id,
        }))

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'uploadMethod': 'PUT',
                'uploadUrl': upload_url,
                's3Key': s3_key,
                'contentType': content_type,
                'publicUrl': None,
                'expiresIn': 300,
            })
        }
    except Exception as e:
        logger.error(json.dumps({
            'event': 'media_upload_url_error',
            'error': str(e),
            'errorType': type(e).__name__,
            'requestId': request_id,
        }))
        return _error_response(500, f'Failed to generate upload URL: {str(e)}')


# Warm-instance cache: input S3 key + phone → WhatsApp media id, so a bulk run
# re-uses a single upload instead of re-uploading the same file per recipient.
_media_id_cache: Dict[str, Tuple[str, str, str, float]] = {}
MEDIA_ID_CACHE_TTL = 600  # 10 minutes


def _media_trace_id(message_id: str) -> str:
    """Stable, non-empty short id for media filenames and S3 keys.

    Keyed payment sends use ids beginning with wa-idem-. Taking the first eight
    characters therefore collapsed every one of them to the literal wa-idem-,
    producing filenames such as wecare-digital-wa-idem-.png. Keep the useful
    tail when available and fall back to a deterministic hash so operational media
    records always carry a differentiating suffix without inventing randomness.
    """
    raw = ''.join(ch for ch in str(message_id or '') if ch.isalnum())
    if len(raw) >= 10:
        return raw[-10:].lower()
    if raw:
        return (raw + hashlib.sha256(raw.encode('utf-8')).hexdigest())[:10].lower()
    return hashlib.sha256(b'wecare-media').hexdigest()[:10]

def _upload_media(media_file: str, media_type: str, message_id: str, phone_number_id: str, request_id: str, filename: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Upload media to S3 and register with WhatsApp.
    Supports all WhatsApp media types per Meta documentation.
    Requirements 5.5, 5.6, 5.7
    
    Returns: (s3_key, whatsapp_media_id, display_filename)
    """
    import base64
    
    try:
        # Bulk optimization: reuse a previously-uploaded media id for the same
        # S3 key + phone within the TTL (skips re-download + re-upload per send).
        if media_file and len(media_file) < 512:
            _ck = f"{media_file}|{phone_number_id}"
            _hit = _media_id_cache.get(_ck)
            if _hit and (time.time() - _hit[3]) < MEDIA_ID_CACHE_TTL:
                logger.info(json.dumps({'event': 'media_id_cache_hit', 'requestId': request_id}))
                return _hit[0], _hit[1], _hit[2]
        # Generate S3 key with proper extension
        extension = _get_media_extension(media_type)
        
        # S3 key: short format wecare-digital-{8char_uuid}{ext}
        short_id = _media_trace_id(message_id)
        s3_key = f"{MEDIA_PREFIX}wecare-digital-{short_id}{extension}"
        
        # Display filename for WhatsApp (max 240 chars) - use original name if valid
        display_filename = None
        if filename and filename.strip() and filename not in ['undefined', 'null', 'File', 'Blob']:
            display_filename = _sanitize_filename(filename, max_length=240)
        
        # If no valid filename, generate one
        if not display_filename or display_filename == 'document':
            display_filename = f"wecare-digital-{short_id}{extension}"
        
        logger.info(json.dumps({
            'event': 'media_upload_start',
            'messageId': message_id,
            'mediaType': media_type,
            'providedFilename': filename,
            'displayFilename': display_filename,
            's3Key': s3_key,
            'requestId': request_id
        }))
        
        # If media_file is already an S3 key, use it directly
        # Detect S3 keys: s3:// prefix, media prefix, invoices/ prefix, or any path with / that isn't base64
        # 'stack/' and 'stream/' stay in this list alongside the rooted forms: a caller
        # may still hand us a key persisted before the bucket merge, and this only
        # CLASSIFIES the string as a key. canonical() below does the rooting.
        is_s3_key = (
            media_file.startswith('s3://') or
            media_file.startswith(MEDIA_PREFIX) or
            media_file.startswith((media_paths.PUBLIC_ROOT, media_paths.SECURE_ROOT)) or
            media_file.startswith('stack/') or
            media_file.startswith('stream/') or
            (('/' in media_file) and media_file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.pdf', '.ogg', '.mp3')))
        )
        if is_s3_key:
            s3_key = media_file.replace('s3://', '').replace(f'{MEDIA_BUCKET}/', '')
            s3_key = media_paths.canonical(s3_key)

            # A generic media category ("image") used to generate a .jpeg display filename before
            # we discovered that an existing S3 object was actually PNG. Keep the display name in
            # lockstep with the source object's extension so transparent invoice PNGs remain PNG
            # end-to-end in logs and Meta multipart metadata.
            if not (filename and filename.strip() and filename not in ['undefined', 'null', 'File', 'Blob']):
                actual_ext = os.path.splitext(s3_key)[1].lower()
                if actual_ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.pdf',
                                  '.ogg', '.mp3', '.m4a', '.aac', '.amr', '.3gp', '.txt',
                                  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'):
                    display_filename = f"wecare-digital-{short_id}{actual_ext}"
            
            # Get file size from S3 for validation
            try:
                head_response = s3.head_object(Bucket=MEDIA_BUCKET, Key=s3_key)
                file_size = head_response.get('ContentLength', 0)
                is_valid, error_msg = _validate_media_size(file_size, media_type)
                if not is_valid:
                    logger.error(json.dumps({
                        'event': 'media_size_validation_failed',
                        's3Key': s3_key,
                        'fileSize': file_size,
                        'error': error_msg,
                        'requestId': request_id
                    }))
                    return None, None, None
            except Exception as e:
                logger.warning(f"Could not validate S3 file size: {str(e)}")
        else:
            # Assume base64 encoded - decode and upload
            try:
                file_content = base64.b64decode(media_file)
            except Exception as e:
                logger.error(json.dumps({
                    'event': 'media_decode_error',
                    'error': str(e),
                    'mediaType': media_type,
                    'requestId': request_id
                }))
                return None, None, None
            
            # Validate file size
            file_size = len(file_content)
            is_valid, error_msg = _validate_media_size(file_size, media_type)
            if not is_valid:
                logger.error(json.dumps({
                    'event': 'media_size_validation_failed',
                    'fileSize': file_size,
                    'error': error_msg,
                    'requestId': request_id
                }))
                return None, None, None
            
            logger.info(json.dumps({
                'event': 'media_uploading_to_s3',
                's3Key': s3_key,
                'fileSize': file_size,
                'mediaType': media_type,
                'requestId': request_id
            }))
            
            # Upload to S3 using streaming for large files
            s3.put_object(
                Bucket=MEDIA_BUCKET,
                Key=s3_key,
                Body=file_content,
                ContentType=_get_content_type(media_type)
            )
        
        logger.info(json.dumps({
            'event': 'media_uploaded_to_s3',
            's3Key': s3_key,
            'mediaType': media_type,
            'displayFilename': display_filename,
            'requestId': request_id
        }))
        
        # Requirement 5.6: Call PostWhatsAppMessageMedia to get mediaId
        # All phones use Direct Meta API
        try:
            import hmac as _hmac, hashlib as _hashlib
            obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
            media_bytes = obj['Body'].read()
            # Resolve the MIME type Meta will see. Prefer the validated mapping derived
            # from media_type (prevents error 131053 "mismatched media type"); fall back to
            # the S3 object's stored ContentType, then to extension-based guess.
            validated_ct = _get_content_type(media_type)
            s3_ct = (obj.get('ContentType') or '').strip()
            # media_type may be a generic category ('document'/'image'/'video'/
            # 'audio') OR a full MIME ('application/pdf'). For a generic category
            # _get_content_type only yields a *default* (document→application/pdf,
            # image→image/jpeg, video→video/mp4), which is WRONG for non-default
            # files (DOCX/XLSX/PPTX/TXT documents, PNG images, 3GP videos) and
            # makes Meta reject the upload with error 131053 (mismatched media
            # type). In that case trust the file's real stored S3 ContentType,
            # which was set correctly when the file was uploaded.
            is_generic_type = '/' not in (media_type or '')
            if is_generic_type and s3_ct and s3_ct != 'application/octet-stream':
                content_type = s3_ct
            elif validated_ct and validated_ct != 'application/octet-stream':
                content_type = validated_ct
            elif s3_ct and s3_ct != 'application/octet-stream':
                content_type = s3_ct
            else:
                # Last resort: infer from the S3 key extension
                ext_ct = _get_content_type('image' if s3_key.lower().endswith(('.jpg', '.jpeg', '.png'))
                                           else s3_key.rsplit('.', 1)[-1] if '.' in s3_key else '')
                content_type = ext_ct if ext_ct != 'application/octet-stream' else (s3_ct or 'application/octet-stream')
            
            if 'token' not in _direct_api_cache:
                resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
                data = json.loads(resp['SecretString'])
                _direct_api_cache['token'] = (data.get('access_token') or '').strip()
                _direct_api_cache['app_secret'] = (data.get('app_secret') or '').strip()
            
            token = _direct_api_cache['token']
            app_secret = _direct_api_cache['app_secret']
            meta_phone_id = DIRECT_API_META_PHONE_MAP.get(phone_number_id, '')
            url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/media"
            if app_secret:
                proof = _hmac.new(app_secret.encode(), token.encode(), _hashlib.sha256).hexdigest()
                url = f"{url}?appsecret_proof={proof}"
            
            boundary = 'wecareupload'
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\n{content_type}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{display_filename or "file"}"\r\n'
                f'Content-Type: {content_type}\r\n\r\n'
            ).encode() + media_bytes + f'\r\n--{boundary}--\r\n'.encode()
            
            import urllib.request as _ur
            req = _ur.Request(url, data=body, headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': f'multipart/form-data; boundary={boundary}'
            }, method='POST')
            with _ur.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
            whatsapp_media_id = result.get('id', '')
            
            if not whatsapp_media_id:
                logger.error(json.dumps({
                    'event': 'media_registration_no_id',
                    's3Key': s3_key,
                    'response': str(result),
                    'requestId': request_id
                }))
                return None, None, None

            # Cache for bulk reuse (same S3 key + phone within TTL).
            if media_file and len(media_file) < 512:
                _media_id_cache[f"{media_file}|{phone_number_id}"] = (
                    s3_key, whatsapp_media_id, display_filename, time.time()
                )
            
            logger.info(json.dumps({
                'event': 'media_registered_with_whatsapp',
                's3Key': s3_key,
                'mediaId': whatsapp_media_id,
                'mediaType': media_type,
                'displayFilename': display_filename,
                'phoneNumberId': phone_number_id,
                'requestId': request_id
            }))
            
        except Exception as e:
            # This log used to carry `errorType` and nothing else - twice, as a
            # duplicated dict key. So an HTTPError read as `errorType: HTTPError`
            # with no status and no Meta code, and the three failures this path
            # actually produces were indistinguishable: 131053 (unsupported media
            # type or size), 131052 (media download/upload error) and 190 (expired
            # token). Those are the codes a human debugs from, so they go in.
            registration_error = {
                'event': 'media_registration_failed',
                'errorType': type(e).__name__,
                's3Key': s3_key,
                'phoneNumberId': phone_number_id,
                'requestId': request_id,
            }
            if isinstance(e, urllib.error.HTTPError):
                # Same shape as `send_meta_error` above: normalize() returns a NESTED
                # envelope, so read through 'error' or every field is silently None.
                error_body = e.read().decode('utf-8', errors='ignore') if e.fp else ''
                registration_error['httpCode'] = e.code
                try:
                    normalized = graph_errors.normalize(error_body, e.code).get('error', {})
                except Exception:  # noqa: BLE001 - diagnostics must not break the error path
                    normalized = {}
                registration_error['metaCode'] = normalized.get('code')
                registration_error['metaSubcode'] = normalized.get('error_subcode')
                registration_error['fbtraceId'] = normalized.get('fbtrace_id')
                # Meta's prose is deliberately NOT logged, only its presence: Meta
                # writes the recipient into the message text of several messaging
                # errors, and the token is in the request this response answers.
                # See the reasoning on `_META_ERROR_SAFE_FIELDS` in lambda_utils/masking.py.
                registration_error['metaMessagePresent'] = bool(normalized.get('message'))
            logger.error(json.dumps(registration_error))
            # Media registration failed - cannot send media without mediaId
            return None, None, None
        
        logger.info(json.dumps({
            'event': 'media_upload_complete',
            's3Key': s3_key,
            'mediaId': whatsapp_media_id,
            'mediaType': media_type,
            'displayFilename': display_filename,
            'requestId': request_id
        }))
        
        return s3_key, whatsapp_media_id, display_filename
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'media_upload_error',
            'error': str(e),
            'errorType': type(e).__name__,
            'mediaType': media_type,
            'requestId': request_id
        }))
        return None, None, None


def _sanitize_filename(filename: str, max_length: int = 240) -> str:
    """
    Sanitize filename for WhatsApp document messages.
    
    WhatsApp filename requirements:
    - Maximum 240 characters
    - Remove invalid characters but preserve common ones
    - Preserve file extension
    
    Args:
        filename: Original filename
        max_length: Maximum allowed length (default 240 for WhatsApp)
    
    Returns:
        Sanitized filename
    """
    if not filename or not isinstance(filename, str):
        return 'document'
    
    # Handle placeholder values
    if filename.strip() in ['undefined', 'null', 'File', 'Blob', '']:
        return 'document'
    
    # Remove path separators if present
    filename = filename.split('/')[-1].split('\\')[-1]
    
    # Remove only truly invalid characters for WhatsApp
    # Keep: alphanumeric, dots, hyphens, underscores, spaces, parentheses
    import re
    sanitized = re.sub(r'[^\w\s.\-()]+', '', filename, flags=re.UNICODE)
    
    # Replace multiple spaces with single space
    sanitized = re.sub(r'\s+', ' ', sanitized)
    
    # Strip leading/trailing spaces
    sanitized = sanitized.strip()
    
    # If filename is too long, truncate while preserving extension
    if len(sanitized) > max_length:
        # Split filename and extension
        if '.' in sanitized:
            name_parts = sanitized.rsplit('.', 1)
            name = name_parts[0]
            ext = '.' + name_parts[1]
        else:
            name = sanitized
            ext = ''
        
        # Calculate how much space we have for the name
        available_length = max_length - len(ext)
        
        # Truncate name and reconstruct
        sanitized = name[:available_length] + ext
    
    # Ensure we have a valid filename
    if not sanitized or sanitized.isspace():
        sanitized = 'document'
    
    logger.info(json.dumps({
        'event': 'filename_sanitized',
        'original': filename,
        'sanitized': sanitized,
        'length': len(sanitized),
        'maxLength': max_length,
        'changed': filename != sanitized
    }))
    
    return sanitized


def _normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number to WhatsApp-compatible E.164 format.
    WhatsApp requires: digits only, no + prefix, with country code.
    
    Examples:
    - "+919876543210" -> "919876543210"
    - "919876543210" -> "919876543210"
    - "+91 98765 43210" -> "919876543210"
    - "9876543210" -> "919876543210" (assumes India)
    - "447447840003" -> "447447840003"
    - "+44 7447 840003" -> "447447840003"
    """
    if not phone:
        return phone
    
    # Remove all non-digit characters (spaces, dashes, +, etc.)
    digits_only = ''.join(c for c in phone if c.isdigit())
    
    # If empty after removing non-digits, return original
    if not digits_only:
        return phone
    
    # If 10 digits and starts with 6-9, assume Indian number
    if len(digits_only) == 10 and digits_only[0] in '6789':
        digits_only = '91' + digits_only
    
    # If 11 digits starting with 0, remove leading 0 and add country code
    if len(digits_only) == 11 and digits_only[0] == '0':
        digits_only = '91' + digits_only[1:]
    
    # If 12 digits starting with 0091, remove leading 00
    if len(digits_only) == 12 and digits_only.startswith('0091'):
        digits_only = digits_only[2:]
    
    # Validate final format: should be 10-15 digits (E.164 format)
    if not digits_only.isdigit() or len(digits_only) < 10 or len(digits_only) > 15:
        logger.warning(f"Phone number after normalization is invalid: {mask_phone(phone or '')} "
                       f"-> {mask_phone(digits_only or '')} (length: {len(digits_only)}, "
                       f"digits: {digits_only.isdigit()})")
    
    return digits_only


def _paise_from_rupees(value) -> int:
    """Exact integer paise from a rupee figure. No `float()`, no `round()`, no epsilon.

    This is the LEGACY-KEY arm of the `orderStatusDetails` read: `inbound-whatsapp-handler`
    produces `amount` in rupees and is deliberately left untouched, so the rupee key is accepted
    here - but the rupee ARITHMETIC is not. `Decimal(str(x)) * 100` is exact where `float(x) * 100`
    is not, and this figure reaches a message that tells a paying customer their money arrived.

    Returns 0 for an absent or unreadable value, because a missing amount on a confirmation falls
    back to the caller's `description` rather than failing the send.
    """
    if value in (None, ''):
        return 0
    if isinstance(value, bool):
        return 0
    try:
        minor = Decimal(str(value)) * 100
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if minor != minor.to_integral_value() or minor < 0:
        return 0
    return int(minor)


class ReferenceIdTooLong(ValueError):
    """A reference_id exceeded Meta's 35-character limit and was NOT truncated.

    A distinct type because the correct response is to fail the send, never to shorten the
    value. See _sanitize_reference_id.
    """





def _sanitize_reference_id(reference_id: str) -> str:
    """
    Normalise reference_id to the WD-PAY-<ID> shape Meta and Razorpay both accept.

    Meta's Payments (India) reference requires reference_id to be at most 35 characters drawn
    from letters, numbers, underscores, dashes and dots.

    THIS FUNCTION NO LONGER TRUNCATES, and that is the point of it.

    It used to end with `if len(result) > 35: result = result[:35]`, which is the most
    dangerous line that can appear on a payment path: reference_id is the join key that ties a
    WhatsApp payment to an order, and truncation maps two distinct identifiers onto one string.
    Two orders then reconcile against a single payment, which is the one failure this domain
    cannot recover from after the fact.

    It was reachable. The legacy WD order number is 46 characters and contains spaces and
    colons, so passing one in produced `WD-PAY-ORD<hex><date><time>IST` at exactly 35
    characters - safe only by arithmetic accident, because the date and time are fixed-width.
    Any other over-long input silently collided.

    Over-long now raises. Callers on the payment path should mint a reference with
    `order_keys.mint_payment_reference()` rather than deriving one from a display string.

    Examples:
    - "WD-PAY-ABC12345"       -> "WD-PAY-ABC12345"   (unchanged)
    - "WD_ABC12345"           -> "WD-PAY-ABC12345"   (legacy shape upgraded)
    - "WD-PAY-WD-PAY-ABC"     -> "WD-PAY-ABC"        (duplicate prefix removed)
    - ""                      -> "WD-PAY-XXXXXXXX"   (minted)
    - 40 characters of input  -> raises ReferenceIdTooLong
    """
    import re

    if not reference_id or not reference_id.strip():
        # CSPRNG, not a sliced uuid4 hex: this value is a payment join key, and a SnapStart
        # snapshot would freeze a seeded PRNG across every restored sandbox.
        return f"WD-PAY-{secrets.token_hex(4).upper()}"

    raw = reference_id.strip()

    # An order number is not a payment reference, and must never be turned into one (R2.9).
    #
    # Checked BEFORE the byte-for-byte pass-through below, and the order matters: the compact
    # order id `WD-ORD-A1B2C3D4` is 15 characters of permitted charset, so it *is* a
    # Meta-valid string and a pass-through placed first would hand it straight to Meta as a
    # payment reference.
    #
    # Refused rather than converted, because the conversion looked safe by coincidence. The
    # legacy spaced number is 47 characters, and stripping its spaces, dashes and colons
    # produced `WD-PAY-ORD<8hex><8date><6time>IST` at exactly 35 - passing the length check only
    # because the date and time are fixed width. Change the format by one character and it
    # silently truncated instead.
    if order_keys.is_wd_order_number(reference_id):
        raise ReferenceIdTooLong(
            'an order number must not be used as a reference_id: the two identifiers have '
            'different consumers and different lifetimes, and an order does not exist until '
            'payment is verified. Mint one with order_keys.mint_payment_reference()'
        )

    # ── A canonical reference is sent BYTE-FOR-BYTE. ──
    #
    # A reference minted by `order_keys.mint_payment_reference` has already been reserved under
    # PAYREF# and bound to a payment attempt. At that point it is not a candidate to be tidied,
    # it is a stored fact that Meta, Razorpay and our reconciliation all key on. Any
    # transformation here - even one that looks harmless - desynchronises the message from the
    # row that owns it.
    #
    # `.upper()` below is the specific trap. It used to run on every value before the
    # pass-through checks, and Meta's reference_id is case SENSITIVE. It happens to be a no-op
    # for our current alphabet, which is entirely uppercase, and that is precisely why it
    # survived: a correctness bug that is currently invisible. Change the alphabet and it starts
    # breaking joins silently.
    #
    # A doubled prefix is excluded because it is a legacy double-prefixing artefact rather than
    # a minted reference - valid charset, but not a value we ever reserved.
    if (order_keys.is_valid_meta_reference_id(raw)
            and 'WD-PAY-WD-PAY-' not in raw.upper()):
        return raw

    stripped = raw.upper()

    # Remove duplicate WD-PAY- prefixes
    while 'WD-PAY-WD-PAY-' in stripped:
        stripped = stripped.replace('WD-PAY-WD-PAY-', 'WD-PAY-')

    # Already in new format
    if stripped.startswith('WD-PAY-'):
        result = stripped
    else:
        # Old format: strip old WD prefix and non-alnum, then add WD-PAY-
        cleaned = re.sub(r'[^A-Za-z0-9]', '', stripped)
        # Remove legacy WD prefix(es)
        while cleaned.startswith('WD'):
            cleaned = cleaned[2:]
        if not cleaned:
            cleaned = secrets.token_hex(4).upper()
        result = f"WD-PAY-{cleaned}"

    if len(result) > REFERENCE_ID_MAX_LENGTH:
        # Fail the send. Do not shorten: two truncated references are indistinguishable, and
        # the customer would pay against an order this payment is not joined to.
        raise ReferenceIdTooLong(
            f'reference_id is {len(result)} characters, over Meta\'s '
            f'{REFERENCE_ID_MAX_LENGTH}-character limit, and must not be truncated because it '
            'is the payment join key; mint one with order_keys.mint_payment_reference()'
        )

    return result


# All three OTP types deliver the code through the URL button sub_type at send time.
# ONE_TAP and ZERO_TAP differ from COPY_CODE in the TEMPLATE definition, not here --
# which is why there is no third branch in the OTP send path. The otpButtonType log
# field keeps the CALLER'S spelling, so a one-tap send and a url send stay separable
# in CloudWatch.
_OTP_URL_SUBTYPES = {'url', 'one_tap', 'zero_tap'}


def _copy_code_button_component(index: Any, code: Any) -> Dict[str, Any]:
    """The one spelling of a copy_code button component.

    Meta names the parameter `coupon_code` for both an authentication OTP and a
    limited-time-offer code; two literal copies of that shape is how a field name
    ends up corrected in one place and not the other.
    """
    return {'type': 'button', 'sub_type': 'copy_code', 'index': int(index or 0),
            'parameters': [{'type': 'coupon_code', 'coupon_code': str(code)}]}


def _build_message_payload(recipient_phone: str, content: str, media_type: Optional[str],
                           media_id: Optional[str], is_template: bool, template_name: Optional[str],
                           template_params: list, filename: Optional[str] = None,
                           is_payment_template: bool = False, order_details: Optional[Dict] = None,
                           header_image_url: Optional[str] = None,
                           is_interactive_payment: bool = False,
                           is_otp_template: bool = False, otp_code: Optional[str] = None,
                           otp_button_type: Optional[str] = None,
                           phone_number_id: Optional[str] = None,
                           recipient_bsuid: Optional[str] = None,
                           template_header_media: Optional[str] = None,
                           template_header_type: Optional[str] = None,
                           template_header_filename: Optional[str] = None,
                           template_header_location: Optional[Dict] = None,
                           template_flow_button: Optional[Dict] = None,
                      template_url_button: Optional[Dict] = None,
                           context_message_id: Optional[str] = None,
                           *,
                           direct_send_category: Optional[str] = None,
                           is_lto_template: bool = False,
                           lto_expiration_ms: Optional[int] = None,
                           lto_offer_code: Optional[str] = None,
                           lto_copy_code_index: int = 0,
                           template_quick_reply_button: Optional[Dict] = None) -> Dict[str, Any]:
    """Build WhatsApp Cloud API message payload. Supports BSUID recipient.

    `direct_send_category` is keyword-only and defaults to None, so every existing
    caller and test is unaffected. When set, this function is the **single arbiter**
    of whether a Direct Send `category` is actually injected — see the comment at the
    injection point. The handler's own pre-check is a coarse optimisation; this is
    the decision.
    """
    fixed_header = fixed_image_header(template_name) if is_template else ''
    if fixed_header:
        template_header_media, template_header_type = fixed_header, 'image'

    # Normalize phone number - WhatsApp API expects digits only without + prefix
    formatted_phone = _normalize_phone_number(recipient_phone) if recipient_phone else ''
    
    # Validate phone number format (skip if sending to BSUID only)
    if formatted_phone and (not formatted_phone.isdigit() or len(formatted_phone) < 10):
        logger.warning(f"Invalid phone number after normalization: {mask_phone(recipient_phone or '')} "
                       f"-> {mask_phone(formatted_phone or '')} (len={len(formatted_phone or '')}, "
                       f"digits={(formatted_phone or '').isdigit()})")
    
    # WhatsApp requires + prefix with country code in the message payload
    whatsapp_phone = f"+{formatted_phone}" if formatted_phone else ''
    
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
    }
    
    # Support both phone number and BSUID recipients (per Meta BSUID docs)
    # If both provided, 'to' (phone) takes precedence
    if whatsapp_phone:
        payload['to'] = whatsapp_phone
    if recipient_bsuid:
        payload['recipient'] = recipient_bsuid
    # Fallback: at least one must be set
    if not whatsapp_phone and not recipient_bsuid:
        payload['to'] = whatsapp_phone  # Will fail at API level with clear error
    
    if is_template and template_name:
        # Template message
        # Get language from template_params if provided, otherwise default to 'en'
        template_language = 'en'
        actual_params = list(template_params) if template_params else []
        
        if actual_params and len(actual_params) > 0:
            # Check if first param is a language code (2-5 chars like 'en', 'en_US')
            first_param = actual_params[0] if actual_params else ''
            if isinstance(first_param, str) and (len(first_param) == 2 or (2 <= len(first_param) <= 5 and '_' in first_param)):
                # Looks like a language code, use it
                template_language = first_param
                actual_params = actual_params[1:]  # Remove language from params
        
        payload['type'] = 'template'
        payload['template'] = {
            'name': template_name,
            'language': {'code': template_language},
            'components': []
        }

        # Media header for standard (non-payment) templates. Must be appended
        # first so the component order is header → body → button per Meta spec.
        # Accepts a public https link OR a pre-resolved WhatsApp media id.
        if (template_header_media
                and template_header_type in ('image', 'video', 'document')):
            _is_link = str(template_header_media).startswith('http')
            _ref = {'link': template_header_media} if _is_link else {'id': template_header_media}
            if template_header_type == 'document':
                if template_header_filename:
                    _ref['filename'] = template_header_filename
                _hp = {'type': 'document', 'document': _ref}
            elif template_header_type == 'video':
                _hp = {'type': 'video', 'video': _ref}
            else:
                _hp = {'type': 'image', 'image': _ref}
            payload['template']['components'].append({'type': 'header', 'parameters': [_hp]})
            logger.info(json.dumps({
                'event': 'template_media_header_added',
                'templateName': template_name,
                'headerType': template_header_type,
                'ref': 'link' if _is_link else 'id',
                'hasFilename': bool(template_header_filename),
            }))

        # Location header for standard (non-payment) templates. Coordinates are
        # supplied at send time (latitude/longitude required; name/address optional).
        if (template_header_type == 'location' and template_header_location
):
            _loc = {}
            for _k in ('latitude', 'longitude', 'name', 'address'):
                _v = template_header_location.get(_k)
                if _v not in (None, ''):
                    _loc[_k] = str(_v)
            if _loc.get('latitude') and _loc.get('longitude'):
                payload['template']['components'].append({
                    'type': 'header',
                    'parameters': [{'type': 'location', 'location': _loc}]
                })
                logger.info(json.dumps({
                    'event': 'template_location_header_added',
                    'templateName': template_name,
                    'hasName': bool(_loc.get('name')),
                }))
        # OTP / Authentication template support
        # WhatsApp authentication templates use a button component with:
        # - sub_type 'url' with {{1}} OTP code parameter (URL button with OTP appended)
        # - sub_type 'copy_code' with coupon_code parameter (one-tap copy button)
        elif is_otp_template and otp_code:
            # Body params (e.g. {{1}} = OTP code for display in message body)
            if actual_params:
                payload['template']['components'].append({
                    'type': 'body',
                    'parameters': [{'type': 'text', 'text': str(p)} for p in actual_params]
                })
            
            btn_type = (otp_button_type or 'url').lower()
            if btn_type in _OTP_URL_SUBTYPES:
                # URL button: OTP code appended to the template URL as {{1}}
                payload['template']['components'].append({
                    'type': 'button',
                    'sub_type': 'url',
                    'index': 0,
                    'parameters': [{'type': 'text', 'text': str(otp_code)}]
                })
            else:
                # One-tap / copy_code button: user taps to auto-fill OTP
                payload['template']['components'].append(
                    _copy_code_button_component(0, otp_code))
            
            logger.info(json.dumps({
                'event': 'otp_template_payload_built',
                'templateName': template_name,
                'language': template_language,
                'otpButtonType': btn_type,
                'bodyParamCount': len(actual_params)
            }))
        # Limited-time-offer template support. EMIT ONLY: validation and coercion
        # happened in handler(), because this function cannot return an HTTP response
        # and must not try. By the time this branch runs, lto_expiration_ms is a
        # positive int or the request already 400'd, so there is no failure path here.
        #
        # It appends body params itself rather than falling through, because the chain
        # is elif-ordered and an offer template can legitimately carry both.
        elif is_lto_template:
            if actual_params:
                payload['template']['components'].append({
                    'type': 'body',
                    'parameters': [{'type': 'text', 'text': str(p)} for p in actual_params]
                })
            payload['template']['components'].append({
                'type': 'limited_time_offer',
                'parameters': [{
                    'type': 'limited_time_offer',
                    'limited_time_offer': {'expiration_time_ms': lto_expiration_ms}
                }]
            })
            if lto_offer_code:
                payload['template']['components'].append(
                    _copy_code_button_component(lto_copy_code_index, lto_offer_code))

            logger.info(json.dumps({
                'event': 'lto_template_payload_built',
                'templateName': template_name,
                'expirationTimeMs': lto_expiration_ms,
                'hasOfferCode': bool(lto_offer_code),
                'bodyParamCount': len(actual_params)
            }))
        # Add body parameters if provided (for templates with variables like {{1}}, {{2}})
        # Supports both positional params (list of values) and named params (dict of name:value)
        elif actual_params and len(actual_params) > 0:
            # Check if params are named (dict) or positional (list of strings)
            if len(actual_params) == 1 and isinstance(actual_params[0], dict):
                # Named parameters: {"name": "John", "order_id": "WD-123"}
                # Convert to positional per Meta API (named params are for readability only)
                named = actual_params[0]
                payload['template']['components'].append({
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': str(v), 'parameter_name': str(k)}
                        for k, v in named.items()
                    ]
                })
            else:
                payload['template']['components'].append({
                    'type': 'body',
                    'parameters': [{'type': 'text', 'text': str(p)} for p in actual_params]
                })
        
        if template_url_button is not None:
            from lambda_utils.ecommerce.catalog_service_checkout import url_button_component
            if (is_otp_template or template_flow_button
                    or template_name != 'wecare_default_download'):
                raise ValueError('incompatible dynamic download template')
            payload['template']['components'].append(url_button_component(template_url_button))

        # The Vault offer's "Unlock Vault" QUICK_REPLY carries an opaque offer token, which Meta
        # returns with the tap. Accepted for that template only, so no other send can mint a
        # button the inbound worker would route to a payment.
        if template_quick_reply_button is not None:
            from lambda_utils.ecommerce.catalog_service_checkout import quick_reply_component
            if (is_otp_template or template_flow_button or template_url_button is not None
                    or template_name != whatsapp_templates.VAULT_OFFER.name):
                raise ValueError('incompatible quick reply template')
            payload['template']['components'].append(
                quick_reply_component(template_quick_reply_button))

        # Flow button component — REQUIRED by Meta when the template contains a
        # FLOW button, otherwise Meta rejects the send with error 131008/131009
        # ("specify a flow button component" / "Components sub_type invalid").
        # The frontend detects the flow button in the template definition and
        # passes {index, flowToken?, flowActionData?}. NAVIGATE flows default the
        # token to "unused"; flowActionData is only needed when the target screen
        # requires input data.
        if template_flow_button and not is_otp_template:
            try:
                _fb_index = template_flow_button.get('index', 0)
                _fb_token = (template_flow_button.get('flowToken')
                             or template_flow_button.get('flow_token'))
                if not _fb_token:
                    # No explicit token: generate a routable one so the flow-data
                    # endpoint can extract the recipient phone + WABA and route the
                    # data_exchange (e.g. subscribe REVIEW) correctly. A bare
                    # "unused" token cannot be routed and breaks flow submission.
                    _fb_key = (template_flow_button.get('flowKey')
                               or _infer_flow_key_from_template(template_name) or 'flow')
                    _fb_waba = '1' if phone_number_id == PHONE_NUMBER_ID_1 else '2'
                    _fb_ph = ''.join(c for c in str(recipient_phone or '') if c.isdigit())
                    _fb_token = f'{_fb_key[:10]}-{uuid.uuid4()}-waba-{_fb_waba}-ph-{_fb_ph}'
                _fb_action = {'flow_token': str(_fb_token)}
                _fb_data = (template_flow_button.get('flowActionData')
                            or template_flow_button.get('flow_action_data'))
                if _fb_data:
                    _fb_action['flow_action_data'] = _fb_data
                payload['template']['components'].append({
                    'type': 'button',
                    'sub_type': 'flow',
                    'index': str(_fb_index),
                    'parameters': [{'type': 'action', 'action': _fb_action}]
                })
                logger.info(json.dumps({
                    'event': 'template_flow_button_added',
                    'templateName': template_name,
                    'index': _fb_index,
                    'hasActionData': bool(_fb_data),
                }))
            except Exception as _fbe:
                # Fail closed. A template that declares a FLOW button is rejected by Meta
                # (131008/131009) when the button component is missing, so swallowing the
                # build error used to send a template that could never deliver. Refuse the
                # send here instead: the raise propagates to `_handle_live_send`, which turns
                # it into an `_error_response` and sends nothing. No PII in the message.
                logger.error(json.dumps({
                    'event': 'template_flow_button_error',
                    'error': str(_fbe), 'templateName': template_name,
                }))
                raise ValueError(
                    'flow button component could not be built; send refused') from _fbe

        # Counts only: body variables carry customer names, amounts and codes.
        logger.info(json.dumps({
            'event': 'template_payload_built',
            'templateName': template_name,
            'language': template_language,
            'paramCount': len(actual_params),
            'componentTypes': [c.get('sub_type') or c.get('type')
                               for c in payload['template']['components']],
            'isPaymentTemplate': is_payment_template
        }))
    elif media_id and media_type:
        # Media message - derive WhatsApp message type from the media MIME type.
        # media_type is like 'image/jpeg', 'video/mp4', 'audio/ogg', 'application/pdf', 'image/webp'.
        mt = (media_type or '').lower().strip()

        # WebP can ONLY be sent as a sticker — Meta rejects WebP sent as an image.
        if mt in ('sticker', 'image/webp', 'application/webp') or mt.endswith('/webp'):
            msg_type = 'sticker'
        elif '/' in mt:
            prefix = mt.split('/')[0]
            # Documents have many MIME prefixes (application/, text/) → map to 'document'.
            msg_type = prefix if prefix in ('image', 'video', 'audio') else 'document'
        else:
            msg_type = mt

        # Validate media type
        valid_types = ['image', 'video', 'audio', 'document', 'sticker']
        if msg_type not in valid_types:
            logger.warning(f"Invalid media type: {media_type} -> {msg_type}, using 'document' as fallback")
            msg_type = 'document'
        
        payload['type'] = msg_type
        payload[msg_type] = {'id': media_id}
        
        # Add caption if provided. Stickers and audio do NOT support captions (Meta rejects them).
        if content and msg_type in ('image', 'video', 'document'):
            payload[msg_type]['caption'] = content
        
        # For documents, add filename if available
        # WhatsApp filename limit: 240 characters
        if msg_type == 'document' and filename:
            # Sanitize and truncate filename to 240 characters
            sanitized_filename = _sanitize_filename(filename, max_length=240)
            payload[msg_type]['filename'] = sanitized_filename
            logger.info(json.dumps({
                'event': 'document_filename_added',
                'originalFilename': filename,
                'sanitizedFilename': sanitized_filename,
                'length': len(sanitized_filename)
            }))
    else:
        # Check for special message types passed via content JSON
        try:
            content_data = json.loads(content) if content and content.startswith('{') else None
        except (json.JSONDecodeError, TypeError):
            content_data = None

        if content_data and content_data.get('_type') == 'contacts':
            # Contact card message — per WhatsApp Cloud API contacts spec
            payload['type'] = 'contacts'
            payload['contacts'] = content_data.get('contacts', [])
        elif content_data and content_data.get('_type') == 'location':
            # Location message — per WhatsApp Cloud API location spec
            payload['type'] = 'location'
            payload['location'] = {
                'latitude': str(content_data.get('latitude', 0)),
                'longitude': str(content_data.get('longitude', 0)),
            }
            if content_data.get('name'):
                payload['location']['name'] = content_data['name']
            if content_data.get('address'):
                payload['location']['address'] = content_data['address']
        elif content_data and content_data.get('_type') == 'location_request':
            # Location request message — interactive type
            payload['type'] = 'interactive'
            payload['interactive'] = {
                'type': 'location_request_message',
                'body': {'text': content_data.get('body', 'Please share your location')},
                'action': {'name': 'send_location'},
            }
        elif content_data and content_data.get('_type') == 'address':
            # Address message — interactive type
            payload['type'] = 'interactive'
            payload['interactive'] = {
                'type': 'address_message',
                'body': {'text': content_data.get('body', 'Please provide your delivery address')},
                'action': {
                    'name': 'address_message',
                    'parameters': content_data.get('parameters', {}),
                },
            }
        else:
            # Text message — enable link preview when content contains a URL
            has_url = 'http://' in content or 'https://' in content
            payload['type'] = 'text'
            payload['text'] = {'body': content, 'preview_url': has_url}
    
    # Native reply: quote the message being replied to (Meta "context" object).
    # Applies to text/media/interactive/contacts/location — set last so it covers all.
    if context_message_id:
        payload['context'] = {'message_id': context_message_id}

    # ── Direct Send category injection ──────────────────────────────────────
    #
    # An ALLOWLIST OF ONE BRANCH, not a denylist, and the difference is the whole
    # safety argument. Three reasons:
    #
    #  1. Direct Send supports a narrow set of message types. Address, audio,
    #     contacts, location, sticker and reaction are documented as unsupported,
    #     so a `category` on any of those is a request Meta refuses — and the
    #     refusal would replace a message we deliver today.
    #  2. The type is not decidable at the call site. Above, a `content` string
    #     starting with `{` is parsed as JSON and `_type` can route a
    #     text-looking request into contacts / location / location_request /
    #     address. The handler cannot see that; this function can, because by
    #     here `payload['type']` is settled. Checking the BUILT type is the only
    #     check that cannot be fooled.
    #  3. `authentication` may not address a business-scoped user id, and
    #     utility-via-BSUID is untested here. A BSUID-only send has no `to`, so
    #     requiring `to` excludes it by the same condition.
    #
    # `category` is a TOP-LEVEL sibling of `type` — never nested inside `text`.
    # `preview_url` goes with it: Direct Send renders no URL preview, so sending
    # the key is sending an unsupported parameter.
    if direct_send_category and payload.get('type') == 'text' and payload.get('to'):
        payload['category'] = direct_send_category
        if isinstance(payload.get('text'), dict):
            payload['text'].pop('preview_url', None)

    return payload


def _get_contact(contact_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve contact from DynamoDB."""
    contacts_table = dynamodb.Table(CONTACTS_TABLE)
    
    # First try direct lookup by 'id' (primary key)
    try:
        response = contacts_table.get_item(Key={'id': contact_id})
        item = response.get('Item')
        if item and item.get('deletedAt') is None:
            return item
    except Exception as e:
        logger.warning(f"Direct lookup failed: {str(e)}")
    
    # Fallback: scan by contactId field
    try:
        response = contacts_table.scan(
            FilterExpression='contactId = :cid AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
            ExpressionAttributeValues={':cid': contact_id, ':null': None},
            Limit=1
        )
        items = response.get('Items', [])
        if items:
            return items[0]
    except Exception as e:
        logger.warning(f"Scan by contactId failed: {str(e)}")
    
    return None


def _get_or_create_contact_by_phone(phone: str) -> Dict[str, Any]:
    """Look up contact by phone number, or auto-create if not found.
    Uses a deterministic phone-derived id (wa<digits>) + strongly-consistent get_item
    so outbound never creates duplicate (churned) contacts for the same number."""
    contacts_table = dynamodb.Table(CONTACTS_TABLE)
    clean = ''.join(c for c in (phone or '') if c.isdigit())
    with_plus = f'+{clean}'
    det_id = f'wa{clean}' if clean else ''

    # 0) Strongly-consistent lookup by deterministic phone id (no GSI lag / no churn)
    if det_id:
        try:
            r = contacts_table.get_item(Key={'id': det_id}, ConsistentRead=True)
            existing = r.get('Item')
            if existing and not existing.get('deletedAt'):
                return existing
        except Exception as e:
            logger.warning(f"deterministic contact get failed for {det_id}: {e}")

    # Try GSI phone-index lookup (both formats)
    for variant in [with_plus, clean]:
        try:
            resp = contacts_table.query(
                IndexName='phone-index',
                KeyConditionExpression='phone = :p',
                ExpressionAttributeValues={':p': variant},
                Limit=5,
            )
            items = [i for i in resp.get('Items', []) if not i.get('deletedAt')]
            if items:
                contact = sorted(items, key=lambda x: x.get('createdAt', 0))[0]
                logger.info(json.dumps({
                    'event': 'contact_found_by_phone',
                    'contactId': mask_contact_id(contact.get('contactId', contact.get('id', ''))),
                    'phone': mask_phone(phone),
                }))
                return contact
        except Exception as e:
            logger.warning(f"Phone GSI lookup failed for {variant}: {e}")

    # Fallback scan
    try:
        resp = contacts_table.scan(
            FilterExpression='(phone = :p1 OR phone = :p2) AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
            ExpressionAttributeValues={':p1': clean, ':p2': with_plus, ':null': None},
            Limit=10,
        )
        items = resp.get('Items', [])
        if items:
            return sorted(items, key=lambda x: x.get('createdAt', 0))[0]
    except Exception:
        pass

    # Not found — create with DETERMINISTIC id (idempotent, no duplicates)
    contact_id = det_id or str(uuid.uuid4())
    now = int(time.time())
    contact = {
        **contact_key.contact_item_keys(contact_id),
        **subscriber_id.new_contact_fields(now=now),
        'name': '',
        'phone': with_plus,
        'optInWhatsApp': True,
        'optInSms': True,
        'optInEmail': True,
        'allowlistWhatsApp': True,
        'allowlistSms': True,
        'allowlistEmail': True,
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
    }
    claims_table = dynamodb.Table(identity_claims.TABLE_NAME)
    try:
        identity_claims.claim_identities(
            claims_table, contact_id=contact_id, phone=with_plus, now=now)
    except identity_claims.IdentityClaimConflict:
        owner_id = identity_claims.owner(claims_table, 'PHONE', with_plus)
        if owner_id:
            owner = contacts_table.get_item(
                Key={'id': owner_id}, ConsistentRead=True).get('Item')
            if owner and contact_store.is_live(owner):
                return owner
        raise

    try:
        contacts_table.put_item(Item=contact, ConditionExpression='attribute_not_exists(id)')
        logger.info(json.dumps({'event': 'contact_auto_created_outbound', 'contactId': mask_contact_id(contact_id), 'phone': mask_phone(with_plus)}))
        return contact
    except Exception as e:
        # Race / already exists — fetch and reuse (never create a duplicate)
        if 'ConditionalCheckFailedException' in str(e):
            try:
                r = contacts_table.get_item(Key={'id': contact_id}, ConsistentRead=True)
                if r.get('Item'):
                    return r['Item']
            except Exception:
                pass
        return contact


def _enrich_contact_identity(contact_id: str, wa_id: str) -> None:
    """Persist the canonical WhatsApp wa_id on the contact after a send (best-effort).

    Meta does NOT return a profile name on send (privacy) — the display name,
    BSUID and username auto-fill from the inbound webhook when the contact replies.
    Here we store the normalized wa_id so the contact resolves consistently and is
    inbox-ready. Never raises (sending must not fail on enrichment).
    """
    if not contact_id or not wa_id:
        return
    try:
        norm = _normalize_phone_number(wa_id)
        if not norm:
            return
        contacts_table = dynamodb.Table(CONTACTS_TABLE)
        contacts_table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET waId = :w, updatedAt = :u',
            ExpressionAttributeValues={':w': norm, ':u': Decimal(str(int(time.time())))},
        )
        logger.info(json.dumps({'event': 'contact_waid_enriched', 'contactId': mask_contact_id(contact_id), 'waId': mask_phone(norm)}))
    except Exception as e:
        logger.warning(f'contact wa_id enrich failed (non-blocking): {e}')


def _outside_window_refusal(contact_id: str, has_contact_record: bool,
                            request_id: str) -> Dict[str, Any]:
    """Today's outside-window refusal, byte for byte.

    ONE function, called from two places: the decision site in `handler`, and
    every Direct Send fallback path in `_handle_live_send`. That is the point.
    Enabling the Direct Send flag must never be able to make a failure look
    different from today's, so the fallback returns the exact same response this
    produces rather than a re-typed approximation of it. Two copies of this
    string would be two things to drift.
    """
    logger.info(json.dumps({
        'event': 'send_blocked_outside_window',
        'contactId': mask_contact_id(contact_id),
        'hasContactRecord': has_contact_record,
        'requestId': request_id,
    }))
    return _error_response(403, 'Outside 24h service window — only template messages allowed')


def _is_within_service_window(contact: Dict[str, Any]) -> bool:
    """
    Check if within 24-hour customer service window.
    Requirement 16.2: Calculate window as 24 hours from lastInboundMessageAt
    """
    last_inbound = contact.get('lastInboundMessageAt')
    if not last_inbound:
        return False
    
    # Convert to int if Decimal
    if isinstance(last_inbound, Decimal):
        last_inbound = int(last_inbound)
    elif isinstance(last_inbound, str):
        # Handle ISO format
        from datetime import datetime
        last_inbound = int(datetime.fromisoformat(last_inbound.replace('Z', '+00:00')).timestamp())
    
    window_end = last_inbound + (CUSTOMER_SERVICE_WINDOW_HOURS * 60 * 60)
    return int(time.time()) < window_end


def _check_rate_limit(phone_number_id: str) -> bool:
    """
    Check rate limit for phone number.
    Requirement 5.9: 80 messages per second per phone number
    """
    try:
        rate_table = dynamodb.Table(RATE_LIMIT_TABLE)
        now = int(time.time())
        window_key = f"whatsapp:{phone_number_id}"
        rate_id = f"{window_key}:{now}"
        
        # Atomic increment
        response = rate_table.update_item(
            Key={'id': rate_id},
            UpdateExpression='SET messageCount = if_not_exists(messageCount, :zero) + :inc, channel = :ch, windowStart = :ws, lastUpdatedAt = :now',
            ExpressionAttributeValues={
                ':zero': Decimal('0'),
                ':inc': Decimal('1'),
                ':ch': window_key,
                ':ws': str(now),
                ':now': Decimal(str(now + 86400))  # TTL: 24 hours
            },
            ReturnValues='UPDATED_NEW'
        )
        
        count = int(response.get('Attributes', {}).get('messageCount', 0))
        return count <= RATE_LIMIT_PER_SECOND
        
    except Exception:
        # Allow on error (fail open for rate limiting)
        return True


def _check_pair_rate_limit(phone_number_id: str, recipient_phone: str) -> Tuple[bool, int]:
    """
    Check per-recipient pair rate limit (Meta error 131056).
    Meta allows 1 message per 6 seconds per (sender, recipient) pair.
    Uses 4^X exponential backoff on repeated violations.
    
    Returns (allowed: bool, retry_after_seconds: int).
    """
    try:
        rate_table = dynamodb.Table(RATE_LIMIT_TABLE)
        now = int(time.time())
        pair_key = f"pair:{phone_number_id}:{recipient_phone}"
        
        response = rate_table.get_item(Key={'id': pair_key})
        item = response.get('Item')
        
        if item:
            last_sent = int(item.get('messageCount', 0))  # reuse field as last-sent timestamp
            violations = int(item.get('violations', 0))
            # Base cooldown: 6 seconds, exponential: 4^violations (capped at 4^4 = 256s)
            backoff = min(6 * (4 ** violations), 256)
            elapsed = now - last_sent
            
            if elapsed < backoff:
                retry_after = backoff - elapsed
                logger.warning(json.dumps({
                    'event': 'pair_rate_limit_hit',
                    'pair': pair_key,
                    'elapsed': elapsed,
                    'backoff': backoff,
                    'violations': violations,
                    'retryAfter': retry_after,
                }))
                return False, retry_after
        
        # Update last-sent timestamp, reset violations on success
        rate_table.put_item(Item={
            'id': pair_key,
            'channel': pair_key,
            'windowStart': 'pair',
            'messageCount': Decimal(str(now)),
            'violations': Decimal('0'),
            'lastUpdatedAt': Decimal(str(now + 86400)),
        })
        return True, 0
        
    except Exception as e:
        logger.warning(f'Pair rate limit check failed: {e}')
        return True, 0  # Fail open


def _record_pair_rate_violation(phone_number_id: str, recipient_phone: str) -> None:
    """Record a pair rate limit violation (called when Meta returns 131056)."""
    try:
        rate_table = dynamodb.Table(RATE_LIMIT_TABLE)
        now = int(time.time())
        pair_key = f"pair:{phone_number_id}:{recipient_phone}"
        
        rate_table.update_item(
            Key={'id': pair_key},
            UpdateExpression='SET violations = if_not_exists(violations, :zero) + :inc, messageCount = :now, channel = :ch, windowStart = :ws, lastUpdatedAt = :ttl',
            ExpressionAttributeValues={
                ':zero': Decimal('0'),
                ':inc': Decimal('1'),
                ':now': Decimal(str(now)),
                ':ch': pair_key,
                ':ws': 'pair',
                ':ttl': Decimal(str(now + 86400)),
            },
        )
    except Exception as e:
        logger.warning(f'Pair rate violation record failed: {e}')


def _store_message_record(message_id: str, contact_id: str, content: str, status: str,
                          is_template: bool = False, whatsapp_message_id: str = None,
                          media_id: str = None, s3_key: str = None,
                          error_details: Dict = None, phone_number_id: str = None,
                          payment_reference_id: str = None,
                          payment_amount_paise: Optional[int] = None,
                          recipient_bsuid: str = None, media_url: str = None,
                          error_code: int = None, is_direct_send: bool = False) -> None:
    """Store message record in DynamoDB with WABA tracking.

    Named `is_direct_send`, not `direct_send`, because this module imports the
    shared `direct_send` module at the top and a parameter of that name would
    shadow it inside this function — a trap for the next edit that needs
    `direct_send.classify_error` here.

    `is_direct_send` marks a row that went out with a Direct Send `category`. It
    writes `directSend: True` or nothing at all — `put_item` already strips None
    values, so a flag-off row is byte-identical to today's and no new attribute
    appears on existing traffic.

    The status webhook's `template_id` (naming the template Direct Send actually
    matched or generated) lands on this row through the existing webhook path when
    it arrives. It is deliberately not written here, because at send time we do
    not know it.
    """
    now = int(time.time())
    expires_at = now + MESSAGE_TTL_SECONDS
    
    # Guard: don't store messages with empty content (prevents blank inbox entries).
    # Templates are exempt — they carry no free-form content but must still appear
    # in the conversation thread.
    if not content and not media_id and not s3_key and not media_url and status != 'failed' and not is_template:
        logger.warning(json.dumps({
            'event': 'empty_content_skipped',
            'messageId': message_id,
            'contactId': mask_contact_id(contact_id),
            'status': status,
        }))
        return

    # Templates with no preview content fall back to a readable label.
    if is_template and not content:
        content = '[Template message]'
    
    # Determine messageType: image/video/audio/document if media present, else template/text.
    # media_url covers template header media (a public link) so sent attachments
    # render in the inbox thread, not just a generic "template" label.
    _media_ref = s3_key or media_url or ''
    if media_id or s3_key or media_url:
        ext = _media_ref.rsplit('.', 1)[-1].lower().split('?')[0] if '.' in _media_ref else ''
        if ext in ('jpg', 'jpeg', 'png', 'gif', 'bmp'):
            msg_type = 'image'
        elif ext in ('mp4', '3gp', '3gpp', 'mov'):
            msg_type = 'video'
        elif ext in ('ogg', 'opus', 'mp3', 'aac', 'amr', 'm4a'):
            msg_type = 'audio'
        elif ext == 'webp':
            msg_type = 'sticker'
        elif ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt'):
            msg_type = 'document'
        elif is_template:
            msg_type = 'template'
        else:
            msg_type = 'document'
    elif is_template:
        msg_type = 'template'
    else:
        msg_type = 'text'
    
    record = {
        'id': message_id,
        'messageId': message_id,
        'contactId': contact_id,
        'channel': 'whatsapp',
        'direction': 'outbound',
        'content': content,
        'messageType': msg_type,
        'timestamp': Decimal(str(now)),
        'status': status,
        'whatsappMessageId': whatsapp_message_id,
        'mediaId': media_id,
        's3Key': s3_key,
        'mediaUrl': media_url,
        'errorDetails': json.dumps(error_details) if error_details else None,
        # Meta error code (e.g. 131047) for failed messages → UI tooltip reason
        'errorCode': error_code if error_code else None,
        # WABA tracking - which phone number sent this message
        'awsPhoneNumberId': phone_number_id,
        'createdAt': Decimal(str(now)),
        'expiresAt': Decimal(str(expires_at)),
        # Payment tracking fields (for amount lookup on confirmation)
        'paymentReferenceId': payment_reference_id,
        # INTEGER PAISE, taken directly from the caller. The `Decimal(str(x * 100))` float
        # round-trip that used to be here is what made a persisted money field inexact.
        'paymentAmount': Decimal(payment_amount_paise) if payment_amount_paise else None,
        'paymentOffset': Decimal('100') if payment_amount_paise else None,
        # BSUID recipient tracking (for BSUID-only sends)
        'recipientBsuid': recipient_bsuid or None,
        # True only when the send carried a Direct Send `category`. None (and so
        # absent from the row entirely) on every other send, which is what keeps a
        # flag-off row byte-identical to today's.
        'directSend': True if is_direct_send else None,
    }
    
    try:
        messages_table = dynamodb.Table(MESSAGES_TABLE)
        messages_table.put_item(Item={k: v for k, v in record.items() if v is not None})
    except Exception as e:
        logger.error(f"Failed to store message record: {str(e)}")

    # Unified Inbox dual-write — mirror to the canonical MessagesTable (Phase 1).
    # Same messageId as the WhatsApp table row, so messages-read dedups by messageId.
    # Guarded inside put_message, so it can never break the WhatsApp store/send above.
    put_message(
        channel='whatsapp',
        direction='outbound',
        contact_id=contact_id,
        content=content,
        status=status,
        message_id=message_id,
        message_type=msg_type,
        whatsapp_message_id=whatsapp_message_id,
        media_id=media_id,
        s3_key=s3_key,
        media_url=media_url,
        error_code=error_code or None,
        aws_phone_number_id=phone_number_id,
        timestamp=now,
    )


def _log_validation_failure(contact_id: str, channel: str, reason: str, request_id: str) -> None:
    """Log validation failure - Requirement 3.6"""
    logger.warning(json.dumps({
        'event': 'validation_failure',
        'contactId': mask_contact_id(contact_id),
        'channel': channel,
        'reason': reason,
        'requestId': request_id,
        'timestamp': int(time.time())
    }))


def _get_media_extension(media_type: str) -> str:
    """
    Get file extension based on media type.
    Complete mapping per WhatsApp Business Platform supported media types.
    
    Supported types:
    - Audio: AAC, AMR, MP3, M4A, OGG (max 16MB)
    - Document: PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX (max 100MB)
    - Image: JPEG, PNG (max 5MB)
    - Sticker: WEBP (max 500KB animated, 100KB static)
    - Video: MP4, 3GPP (max 16MB)
    """
    extensions = {
        # Image formats (max 5MB)
        'image/jpeg': '.jpeg',
        'image/png': '.png',
        'image': '.jpeg',  # Default image

        # Sticker formats (max 500KB animated, 100KB static)
        'image/webp': '.webp',
        'sticker': '.webp',

        # Video formats (max 16MB)
        'video/mp4': '.mp4',
        'video/3gpp': '.3gp',
        'video': '.mp4',  # Default video

        # Audio formats (max 16MB)
        'audio/aac': '.aac',
        'audio/amr': '.amr',
        'audio/mpeg': '.mp3',
        'audio/mp4': '.m4a',
        'audio/ogg': '.ogg',
        'audio/opus': '.opus',
        'audio': '.ogg',  # Default audio

        # Document formats (max 100MB)
        'application/pdf': '.pdf',
        'text/plain': '.txt',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/vnd.ms-powerpoint': '.ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
        'document': '.pdf',  # Default document
    }
    
    # Try exact match first
    if media_type in extensions:
        return extensions[media_type]
    
    # Try prefix match (e.g., 'image' from 'image/jpeg')
    prefix = media_type.split('/')[0] if '/' in media_type else media_type
    return extensions.get(prefix, '.bin')


def _get_content_type(media_type: str) -> str:
    """
    Get MIME content type based on media type.
    Complete mapping per WhatsApp Business Platform supported media types.
    """
    content_types = {
        # Image formats (max 5MB)
        'image/jpeg': 'image/jpeg',
        'image/png': 'image/png',
        'image': 'image/jpeg',

        # Sticker formats (max 500KB animated, 100KB static)
        'image/webp': 'image/webp',
        'sticker': 'image/webp',

        # Video formats (max 16MB)
        'video/mp4': 'video/mp4',
        'video/3gpp': 'video/3gpp',
        'video': 'video/mp4',

        # Audio formats (max 16MB)
        'audio/aac': 'audio/aac',
        'audio/amr': 'audio/amr',
        'audio/mpeg': 'audio/mpeg',
        'audio/mp4': 'audio/mp4',
        'audio/ogg': 'audio/ogg',
        'audio/opus': 'audio/ogg',  # Opus → OGG container for WhatsApp
        'audio': 'audio/ogg',

        # Document formats (max 100MB)
        'application/pdf': 'application/pdf',
        'text/plain': 'text/plain',
        'application/msword': 'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel': 'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint': 'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'document': 'application/pdf',
    }
    
    # Try exact match first
    if media_type in content_types:
        return content_types[media_type]
    
    # Try prefix match
    prefix = media_type.split('/')[0] if '/' in media_type else media_type
    if prefix in content_types:
        return content_types[prefix]
    
    return 'application/octet-stream'


def _validate_media_size(file_size: int, media_type: str) -> Tuple[bool, str]:
    """
    Validate media file size per WhatsApp Business Platform supported media types.
    
    Limits:
    - Audio (AAC, AMR, MP3, M4A, OGG): 16 MB
    - Document (PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX): 100 MB
    - Image (JPEG, PNG): 5 MB
    - Sticker animated (WEBP): 500 KB
    - Sticker static (WEBP): 100 KB
    - Video (MP4, 3GPP): 16 MB
    
    Returns (is_valid, error_message)
    """
    if media_type.startswith('audio/') or media_type == 'audio':
        max_size = 16 * 1024 * 1024  # 16 MB
        category = 'Audio'
    elif media_type.startswith('video/') or media_type == 'video':
        max_size = 16 * 1024 * 1024  # 16 MB
        category = 'Video'
    elif media_type == 'sticker' or media_type == 'image/webp':
        max_size = 500 * 1024  # 500 KB (animated max; static is 100KB but we allow up to 500KB)
        category = 'Sticker'
    elif media_type.startswith('image/') or media_type == 'image':
        max_size = 5 * 1024 * 1024  # 5 MB
        category = 'Image'
    else:
        # Documents: PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX
        max_size = 100 * 1024 * 1024  # 100 MB
        category = 'Document'
    
    if file_size > max_size:
        max_display = f'{max_size / 1024:.0f}KB' if max_size < 1024 * 1024 else f'{max_size / (1024*1024):.0f}MB'
        return False, f'{category} file exceeds maximum size of {max_display}'
    
    return True, ''


def _error_response(status_code: int, error: str, message: str = None) -> Dict[str, Any]:
    """Return error response with CORS headers."""
    body = {'error': error}
    if message:
        body['message'] = message
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body)
    }


#: Inbound message types whose WAMID Meta refuses as the target of a read/typing marker. Meta
#: delivers a message the Cloud API cannot represent as `unsupported`, and answers a marker on
#: its id with 400 code 100 "Message ID ... does not exist". From 2026-10-12 to 2026-10-26 all
#: 6 refused typing indicators targeted an `unsupported` message received 1-3 s earlier; the 3
#: accepted ones targeted `order` messages.
_TYPING_UNMARKABLE_TYPES = frozenset({'unsupported', 'unknown'})


def _meta_phone_or_raw(phone_id: str) -> str:
    """The Meta phone id behind one of our phone ids, else the id itself (for comparing)."""
    try:
        return _resolve_meta_phone_id(phone_id)
    except UnresolvedSenderPhone:
        return phone_id


def _get_latest_inbound_wamid(recipient_phone: str, max_age_seconds: int = 86400,
                              phone_number_id: str = '') -> Optional[str]:
    """Fetch the freshest inbound WAMID for a recipient from the InboundTable.

    Meta's typing_indicator API requires the WAMID of the customer's MOST RECENT
    inbound message and returns HTTP 400 ("Message ID ... does not exist") if the
    WAMID is stale. The contact.lastInboundWamid field can go stale (contact churn,
    older sessions), so this queries the live InboundTable via the
    senderPhone-status-index GSI (senderPhone HASH + status RANGE) for
    status='received' messages, then returns the WAMID with the greatest timestamp
    that is still within the 24h window. Returns '' if none found (never raises).

    Returns None when that latest message cannot carry a marker: Meta delivered it as an
    unsupported type, or it reached a different phone than `phone_number_id` (a marker from
    the other number fails the same way, and would cross WABAs). The contact's cached
    lastInboundWamid is the same message, so None tells the caller not to fall back to it."""
    try:
        digits = _normalize_phone_number(recipient_phone or '')
        if not digits:
            return ''
        inbound_table_name = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
        inbound_table = dynamodb.Table(inbound_table_name)
        now = int(time.time())
        best_id = ''
        best_ts = 0
        best_type = ''
        # The senderPhone-status-index projects the base key (id) + createdAt +
        # messageType but NOT whatsappMessageId, so we pick the newest record here (by
        # createdAt) then fetch its whatsappMessageId from the base table with a single
        # get_item. senderPhone is stored as the Meta wa_id (digits only); also try the
        # +E.164 variant defensively in case older records used a different format.
        for sp in (digits, f'+{digits}'):
            resp = inbound_table.query(
                IndexName='senderPhone-status-index',
                KeyConditionExpression='senderPhone = :sp AND #st = :rcv',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':sp': sp, ':rcv': 'received'},
                ProjectionExpression='id, createdAt, messageType',
            )
            for it in resp.get('Items', []):
                rec_id = it.get('id') or ''
                try:
                    ts = int(it.get('createdAt') or 0)
                except (TypeError, ValueError):
                    ts = 0
                if rec_id and ts > best_ts:
                    best_ts = ts
                    best_id = rec_id
                    best_type = str(it.get('messageType') or '')
            if best_id:
                break
        # Freshness guard: only use it if within the typing-eligible window.
        if not best_id or (now - best_ts) > max_age_seconds:
            return ''
        if best_type in _TYPING_UNMARKABLE_TYPES:
            logger.info(json.dumps({'event': 'typing_indicator_skipped',
                                    'reason': 'latest_inbound_unsupported',
                                    'messageType': best_type}))
            return None
        rec = inbound_table.get_item(
            Key={'id': best_id},
            ProjectionExpression='whatsappMessageId, awsPhoneNumberId').get('Item') or {}
        received_on = str(rec.get('awsPhoneNumberId') or '')
        if (phone_number_id and received_on
                and _meta_phone_or_raw(received_on) != _meta_phone_or_raw(phone_number_id)):
            logger.info(json.dumps({'event': 'typing_indicator_skipped',
                                    'reason': 'latest_inbound_on_other_phone',
                                    'phoneNumberId': phone_number_id}))
            return None
        return rec.get('whatsappMessageId') or ''
    except Exception as e:
        logger.warning(json.dumps({'event': 'latest_inbound_wamid_error', 'error': str(e)}))
        return ''


def _send_typing_indicator(phone_number_id: str, message_id: str) -> None:
    """Send a native WhatsApp typing indicator.

    Per Meta Cloud API (2025+): POST /{PHONE_NUMBER_ID}/messages with
    status='read' + the inbound message_id + a typing_indicator object.
    This marks the customer's last message as read (blue ticks) AND shows a
    typing bubble for up to 25 seconds (or until the business sends a message).

    Requires the WAMID of the customer's most recent inbound message.
    """
    try:
        if not message_id:
            logger.info(json.dumps({
                'event': 'typing_indicator_skipped',
                'reason': 'no inbound message_id available',
                'phoneNumberId': phone_number_id,
            }))
            return

        payload = {
            'messaging_product': 'whatsapp',
            'status': 'read',
            'message_id': message_id,
            'typing_indicator': {'type': 'text'},
        }

        _send_message(phone_number_id, payload)

        logger.info(json.dumps({
            'event': 'typing_indicator_sent',
            'messageId': message_id,
            'phoneNumberId': phone_number_id,
        }))
    except Exception as e:
        # Non-critical — log and swallow so the caller can proceed
        logger.warning(json.dumps({
            'event': 'typing_indicator_error',
            'error': str(e),
            'messageId': message_id,
        }))


def _emit_delivery_metric(status: str, is_template: bool = False) -> None:
    """
    Emit message delivery metric to CloudWatch.
    Requirement 14.4: Emit CloudWatch metrics for message delivery success/failure
    """
    try:
        cloudwatch.put_metric_data(
            Namespace=METRICS_NAMESPACE,
            MetricData=[
                {
                    'MetricName': f'Messages{status.capitalize()}',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'Channel', 'Value': 'WHATSAPP'},
                        {'Name': 'Status', 'Value': status.upper()},
                        {'Name': 'MessageType', 'Value': 'TEMPLATE' if is_template else 'FREEFORM'}
                    ]
                },
                {
                    'MetricName': 'MessagesTotal',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'Channel', 'Value': 'WHATSAPP'}
                    ]
                }
            ]
        )
    except Exception as e:
        logger.warning(f"Failed to emit metric: {str(e)}")
