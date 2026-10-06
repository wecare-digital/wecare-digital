"""
WhatsApp Unified Webhook + Call Control Handler (IVR Auto-Pickup Only)

Purpose: Handle WhatsApp Business Calling API webhooks + IVR auto-pickup + message forwarding
UNIFIED ENDPOINT: https://api.wecare.digital/whatsapp

Routes (all under /whatsapp):
- GET  /whatsapp                   → Webhook verification (hub.challenge)
- POST /whatsapp                   → Webhook events (calls + messages from Meta)
- GET  /whatsapp/logs              → List call event logs
- GET  /whatsapp/active            → Get active/pending calls (for frontend polling)
- POST /whatsapp/reject            → Reject/terminate a call
- POST /whatsapp/hangup            → Hang up an active call
- POST /whatsapp/outbound          → Initiate outbound call
- GET  /whatsapp/config            → Get auto-pickup config
- POST /whatsapp/config            → Update auto-pickup config
- DELETE /whatsapp                 → Clear call logs

Meta Webhook Fields: messages, calls, account_update, account_settings_update, ...
Verification token: server-side configuration only

IVR Audio Playback:
  Graph API mode: pre_accept with SDP → accept → send audio message → terminate
  SIP mode (Asterisk): True in-call IVR audio via RTP/SRTP
  For true in-call audio, enable SIP on the phone number.

Mode: IVR auto-pickup ONLY (manual/browser WebRTC mode removed).
AI Respond endpoint removed — AI is handled by inbound WhatsApp handler via voice notes.
"""

import os
import json
import time
import logging
import uuid
import hmac
import hashlib
import boto3
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Dict, Any, Optional

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.privacy import mask_phone, mask_contact_id, redact_pii  # contactId is `wa` + the customer's digits
from lambda_utils.masking import meta_error_summary  # Meta writes recipients into error prose
from lambda_utils.message_store import put_call_breadcrumb
from lambda_utils.middleware import require_auth  # unified timeline breadcrumb
from lambda_utils import wa_internal_event  # typed ingress -> worker contract

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=REGION)
secrets_client = boto3.client('secretsmanager', region_name=REGION)

CALL_LOG_TABLE = os.environ.get('CALL_LOG_TABLE', 'stack-wecare-digital-WhatsAppCallingTable')
META_TOKEN_SECRET = os.environ.get('META_TOKEN_SECRET', 'wecare/meta-system-user-token')
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days

# Meta WhatsApp Calling error codes (from Meta Troubleshooting docs)
# Used for actionable error logging and frontend display
META_CALLING_ERRORS = {
    138000: {'msg': 'Calling not enabled', 'action': 'Enable calling on this phone number via POST /{phone_id}/settings'},
    138001: {'msg': 'Receiver uncallable', 'action': 'User not on WhatsApp, old ToS, or unsupported client'},
    138002: {'msg': 'Concurrent calls limit reached (max 1000)', 'action': 'Wait for active calls to end'},
    138005: {'msg': 'Call rate limit exceeded', 'action': 'Reduce call frequency'},
    138006: {'msg': 'No approved call permission', 'action': 'Send call_permission_request first'},
    138007: {'msg': 'Connect timeout (SDP not applied in time)', 'action': 'Check SDP answer generation speed'},
    138009: {'msg': 'Call permission request limit hit', 'action': 'Wait before sending more permission requests'},
    138012: {'msg': 'Business-initiated calls limit (100 connected/24h)', 'action': 'Daily outbound call limit reached'},
    138013: {'msg': 'Business-initiated calling not available', 'action': 'Feature not enabled for this WABA'},
    138014: {'msg': 'Calling temporarily disabled (low quality)', 'action': 'Improve call quality metrics'},
    138017: {'msg': 'Permanent permission already exists', 'action': 'User already granted permanent call permission'},
    138018: {'msg': 'Technical prerequisites not met', 'action': 'Configure SIP or subscribe to calls webhook field'},
    138019: {'msg': 'WhatsApp client failed to set up call', 'action': 'Retry — client-side issue'},
    138020: {'msg': 'Relay connection failed', 'action': 'Check network/firewall — media relay unreachable'},
    138021: {'msg': 'Media receive timeout', 'action': 'Check media pipeline — no audio received from caller'},
    138022: {'msg': 'Media transmit timeout', 'action': 'Check media pipeline — no audio sent to caller'},
    138023: {'msg': 'Call accepted but no media signals', 'action': 'SDP answer may be invalid or media path broken'},
    # ── Conversation Routing ──
    # Only the Call primary may use the Calling API; every other responder gets 138038.
    # If the owner maps the Call entry point to a different responder, every call
    # action starts failing with a code this 19-entry table did not contain, so the
    # failure would have read as a generic Meta error. Note the Call primary never
    # becomes a thread owner, so this is the one routing concern calling has.
    138038: {'msg': 'Not the Call primary — Conversation Routing',
             'action': 'The Call entry point is mapped to another responder. Owner must remap it '
                       'in Meta Business Suite; retrying will not help.'},
}

#: Routing refusals, named so the alarm filter and the table cannot drift apart.
ROUTING_OWNERSHIP_ERRORS = (138038,)

# Dual WABA token support
WABA1_ID = '2094615664435155'
WABA2_ID = '2513394156072604'  # Migrated — now Direct API, uses token1 (WECARE.DIGITAL app)
PHONE1_META_ID = '1016149501586345'
PHONE2_META_ID = '1055232054343117'  # New Meta phone ID after migration
# WABA2 now uses WECARE.DIGITAL app (token1), not Manish app
WABA2_IDS = set()  # No longer need separate token routing for WABA2

# Inbound handler Lambda for forwarding non-call webhook events (messages, statuses)
INBOUND_HANDLER_FUNCTION = os.environ.get('INBOUND_HANDLER_FUNCTION', 'wecare-inbound-whatsapp')
lambda_client = boto3.client('lambda', region_name=REGION)

# Cache Meta tokens (dual)
_token_cache = {}

# CORS headers provided by lambda_utils.response.cors_headers(origin)


def _get_meta_token(phone_number_id: str = None) -> str:
    """Get the Meta token for calling operations.
    
    WABA1 uses token1 (Meta App: WECARE.DIGITAL / 2238810740192680).
    WABA-T also uses token1 (Meta App: WECARE.DIGITAL / 2238810740192680).
    
    All WABAs now use Direct Meta API for calling and messaging.
    """
    _load_meta_secrets()
    if phone_number_id and phone_number_id in WABA2_IDS:
        logger.info(f"Using token2 for WABA2 phone_number_id={phone_number_id}")
        return _token_cache.get('token2', '')
    token = _token_cache.get('token1', '')
    logger.info(f"Using token1 for calling (phone_number_id={phone_number_id})")
    return token


def _get_app_secret(phone_number_id: str = None) -> str:
    """Get the app secret for appsecret_proof. Routes to correct app secret."""
    _load_meta_secrets()
    if phone_number_id and phone_number_id in WABA2_IDS:
        return _token_cache.get('app_secret2', '')
    return _token_cache.get('app_secret1', '')


def _get_verify_token() -> str:
    """The Meta webhook verify token, read from Secrets Manager on first use.

    It used to come from a VERIFY_TOKEN environment variable, which put the live
    value in the function configuration, in the console, in deploy logs and in
    every `get-function-configuration` response. It lives in the same secret this
    handler already loads, so reading it there costs no extra API call.
    """
    _load_meta_secrets()
    return _token_cache.get('verify_token', '')


def _load_meta_secrets():
    """Load tokens + app secrets from Secrets Manager (cached)."""
    if 'loaded' in _token_cache:
        return
    try:
        resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
        secret = resp.get('SecretString', '')
        try:
            data = json.loads(secret)
            _token_cache['token1'] = (data.get('access_token') or '').strip()
            _token_cache['token2'] = (data.get('access_token_waba2') or data.get('access_token') or '').strip()
            _token_cache['app_secret1'] = (data.get('app_secret') or '').strip()
            _token_cache['app_secret2'] = (data.get('app_secret_waba2') or '').strip()
            _token_cache['verify_token'] = (data.get('waba_t_verify_token') or '').strip()
        except (json.JSONDecodeError, TypeError):
            _token_cache['token1'] = secret.strip()
            _token_cache['token2'] = secret.strip()
        _token_cache['loaded'] = True
        logger.info(f"Loaded dual tokens: token1={len(_token_cache.get('token1',''))}chars, token2={len(_token_cache.get('token2',''))}chars, has_app_secrets={bool(_token_cache.get('app_secret1'))}")
    except Exception as e:
        logger.error(f"Failed to get Meta token: {e}")
        raise


def _meta_api_call(endpoint: str, method: str = 'POST', payload: Dict = None, phone_number_id: str = None) -> Dict:
    """Make a call to Meta Graph API with dual-token support and appsecret_proof."""
    token = _get_meta_token(phone_number_id=phone_number_id)
    app_secret = _get_app_secret(phone_number_id=phone_number_id)

    # Build URL with appsecret_proof if app secret is available
    url = f"https://graph.facebook.com/{META_API_VERSION}/{endpoint}"
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}appsecret_proof={proof}"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {'success': True}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        # Parse Meta error code for actionable logging
        error_code = None
        error_msg = ''
        try:
            err_data = json.loads(error_body)
            error_obj = err_data.get('error', {})
            error_code = error_obj.get('code')
            error_msg = error_obj.get('message', '')
        except (json.JSONDecodeError, TypeError):
            pass
        if error_code and error_code in META_CALLING_ERRORS:
            meta_err = META_CALLING_ERRORS[error_code]
            logger.error(f"Meta API error {e.code} — Code {error_code}: {meta_err['msg']} | Action: {meta_err['action']} | Detail: {error_msg}")
        else:
            logger.error(f"Meta API error {e.code}: {error_body}")
        # Emitted in addition to the line above, never instead of it: a routing refusal
        # is remedied in the Meta Business Suite rather than in the request, so it needs
        # its own alarmable event name.
        if error_code in ROUTING_OWNERSHIP_ERRORS:
            logger.error(json.dumps({
                'event': 'routing_ownership_rejected',
                'metaCode': error_code,
                'httpCode': e.code,
                'surface': 'calling_api',
            }))
        return {'error': True, 'status': e.code, 'detail': error_body, 'errorCode': error_code, 'errorMessage': error_msg}
    except Exception as e:
        logger.error(f"Meta API call failed: {e}")
        return {'error': True, 'detail': str(e)}


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route the exact public Meta callback separately from Admin management routes."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    if event.get('action') == 'post_call_sip':
        return _handle_post_call_sip(event, request_id)
    if event.get('action') == 'cert_check':
        return _handle_cert_check(event, request_id)

    rc = event.get('requestContext', {})
    http_method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()
    path = rc.get('http', {}).get('path', '') or event.get('rawPath', '') or event.get('path', '')

    # Strip the API Gateway stage prefix BEFORE routing.
    #
    # Measured in production: Meta posts to https://api.wecare.digital/whatsapp
    # and the event arrives with path "/prod/whatsapp", because the custom domain
    # mapping puts the stage in the path. "/prod/whatsapp" != "/whatsapp", so the
    # public webhook branch below was skipped and execution fell through to
    # require_auth(required_role='Admin'), which answered 401 to Meta.
    #
    # That rejected EVERY inbound WhatsApp message and call webhook: 532 x 401 in
    # a 12-hour window, with wecare-inbound-whatsapp receiving zero invocations
    # because nothing forwarded to it.
    #
    # Reusing the already-tested helper rather than re-deriving the logic here:
    # this is the second place this exact bug appeared (plivo-answer was the
    # first, fixed in ea570bcd), and a third copy is how it would return.
    from lambda_utils.http_path import normalize_path as _strip_stage_prefix
    path = _strip_stage_prefix(event) or path
    normalized_path = path.rstrip('/') or '/'
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({'event': 'whatsapp_calling_request', 'method': http_method,
                            'path': path, 'requestId': request_id}))

    if http_method == 'OPTIONS':
        return _response(200, {'ok': True})

    try:
        if normalized_path == '/whatsapp' and http_method == 'GET':
            return _verify_webhook(query_params, request_id)

        if normalized_path == '/whatsapp' and http_method == 'POST':
            if not _verify_webhook_signature(event, request_id):
                logger.warning(json.dumps({'event': 'webhook_signature_rejected', 'requestId': request_id}))
                return _response(401, {'error': 'Invalid webhook signature'})
            body_str = event.get('body', '{}')
            if event.get('isBase64Encoded'):
                import base64
                body_str = base64.b64decode(body_str).decode('utf-8')
            try:
                return _handle_webhook_event(json.loads(body_str), request_id)
            except (json.JSONDecodeError, TypeError, ValueError):
                return _response(400, {'error': 'Invalid JSON in webhook body'})

        auth_result = require_auth(event, required_role='Admin')
        if auth_result is not None:
            return auth_result

        if http_method == 'GET' and normalized_path == '/whatsapp/config':
            return _get_config(request_id)
        if http_method == 'GET' and normalized_path == '/whatsapp/active':
            return _get_active_calls(query_params, request_id)
        if http_method == 'GET' and normalized_path == '/whatsapp/logs':
            return _list_logs(query_params, request_id)
        if http_method == 'POST' and normalized_path == '/whatsapp/config':
            return _update_config(event, request_id)
        if http_method == 'POST' and normalized_path in ('/whatsapp/reject', '/whatsapp/hangup'):
            return _terminate_call(event, request_id)
        if http_method == 'POST' and normalized_path == '/whatsapp/outbound':
            return _outbound_call(event, request_id)
        if http_method == 'DELETE' and normalized_path == '/whatsapp':
            return _clear_logs(request_id)
        return _response(404, {'error': 'Route not found'})
    except Exception as e:
        logger.error(json.dumps({'event': 'handler_error', 'error': str(e), 'method': http_method,
                                 'path': path, 'requestId': request_id}), exc_info=True)
        return _response(500, {'error': 'Internal server error'})


def _verify_webhook(params: Dict, request_id: str) -> Dict[str, Any]:
    """Handle Meta webhook verification (GET with hub.challenge)."""
    mode = params.get('hub.mode', '')
    token = params.get('hub.verify_token', '')
    challenge = params.get('hub.challenge', '')

    expected = _get_verify_token()
    if not expected:
        # Fail closed. The previous form compared against a possibly-empty
        # constant, so a missing token made `token == VERIFY_TOKEN` true for a
        # request that simply omitted hub.verify_token, and the challenge was
        # echoed to anyone who asked.
        logger.error('No verify token available from Secrets Manager; refusing')
        return _response(403, {'error': 'Verification unavailable'})

    if mode == 'subscribe' and hmac.compare_digest(token, expected):
        logger.info(f"Webhook verified. Challenge: {challenge}")
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/plain', 'Access-Control-Allow-Origin': '*'},
            'body': challenge,
        }
    logger.warning(f"Webhook verification failed. Mode={mode}")
    return _response(403, {'error': 'Verification failed'})


# ─── Webhook Event Processing ───────────────────────────────────────

def _verify_webhook_signature(event: Dict[str, Any], request_id: str) -> bool:
    """
    Verify X-Hub-Signature-256 header on incoming Meta webhooks.
    Meta signs every webhook POST with HMAC-SHA256 using the app secret.
    Returns True if valid, False if invalid.
    Fails open (returns True) only if app_secret is not configured.
    """
    headers = event.get('headers', {})
    signature_header = (
        headers.get('x-hub-signature-256')
        or headers.get('X-Hub-Signature-256')
        or ''
    )
    if not signature_header:
        logger.warning(json.dumps({'event': 'webhook_no_signature', 'requestId': request_id}))
        return False

    # Load both app secrets (dual WABA support — webhook may be signed by either app)
    _load_meta_secrets()
    app_secret_1 = _token_cache.get('app_secret1', '')
    app_secret_2 = _token_cache.get('app_secret2', '')

    if not app_secret_1 and not app_secret_2:
        logger.error(json.dumps({'event': 'webhook_no_app_secret', 'requestId': request_id}))
        # P0 Security: Never fail open — reject if no secrets configured
        return False

    raw_body = event.get('body', '')
    if event.get('isBase64Encoded') and raw_body:
        import base64
        raw_body = base64.b64decode(raw_body).decode('utf-8')

    body_bytes = (raw_body or '').encode('utf-8')

    # Try both app secrets — webhook may come from either WABA's app
    for label, secret in [('app_secret1', app_secret_1), ('app_secret2', app_secret_2)]:
        if not secret:
            continue
        expected_sig = 'sha256=' + hmac.new(
            secret.encode('utf-8'),
            body_bytes,
            hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(expected_sig, signature_header):
            return True

    # Neither secret matched — log for debugging
    # Compute expected with primary secret for the log
    primary_secret = app_secret_1 or app_secret_2
    expected_sig = 'sha256=' + hmac.new(
        primary_secret.encode('utf-8'),
        body_bytes,
        hashlib.sha256
    ).hexdigest()
    logger.warning(json.dumps({
        'event': 'webhook_signature_mismatch',
        'expectedPrefix': expected_sig[:20],
        'receivedPrefix': signature_header[:20],
        'bodyLen': len(raw_body or ''),
        'isBase64': event.get('isBase64Encoded', False),
        'requestId': request_id,
    }))
    return False


# Maximum age for webhook events (replay protection)
WEBHOOK_MAX_AGE_SECONDS = 300  # 5 minutes


class _Unreadable:
    """A container the traversal could not walk.

    Needed because "unreadable" and "absent" must not collapse into each other. An
    earlier draft signalled an unreadable container by yielding the container
    itself as a pseudo-timestamp and relying on `int()` to raise - which worked for
    a dict or a string, but a body of `None` was then classified `'absent'` and
    allowed. Wrapping makes the distinction explicit instead of incidental.
    """

    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value

    def __str__(self) -> str:
        return f'<unreadable {type(self.value).__name__}>'


def _timestamp_verdict(raw, now: int) -> str:
    """Classify one timestamp: `'absent' | 'ok' | 'stale' | 'unparsable' | 'future'`.

    Split out so each timestamp is judged independently. The previous version
    wrapped the whole traversal in a single try/except, which had two effects
    beyond the intended one: a malformed value anywhere aborted the traversal, so
    a genuinely stale timestamp later in the same payload was never examined, and
    the except returned True.
    """
    if isinstance(raw, _Unreadable):
        return 'unparsable'
    if raw is None or raw == '':
        return 'absent'
    try:
        ts = int(raw)
    except (ValueError, TypeError):
        return 'unparsable'
    age = now - ts
    if age > WEBHOOK_MAX_AGE_SECONDS:
        return 'stale'
    # A far-future timestamp never expires, so a single captured event could be
    # replayed indefinitely. Allow one window of clock skew, no more.
    if age < -WEBHOOK_MAX_AGE_SECONDS:
        return 'future'
    return 'ok'


def _iter_webhook_timestamps(body: Dict):
    """Yield `(label, raw_value)` for every timestamp position in the payload.

    Unexpected container shapes are yielded as the raw container. `int({...})`
    raises TypeError, so `_timestamp_verdict` classifies them `'unparsable'` and
    the event is rejected. That is deliberate and it is the same rule as an
    unreadable timestamp: a container we cannot walk may be hiding a stale
    timestamp, so it is not evidence of freshness.

    Skipping them instead would be the quiet version of the original bug. A first
    draft of this function did exactly that - it fell back to `[value]` whenever
    `calls` was not a list, so a payload with `calls` as an *object* wrapping a
    stale timestamp was accepted. The old code at least raised AttributeError and
    failed closed with a 500 (badly - Meta retries a 500 indefinitely - but
    closed). Trading a noisy 500 for a silent accept would have made this change a
    net regression.

    `absent` is the one shape that stays allowed, at every level: Meta genuinely
    omits `time`, `changes` and `calls` on some event types.
    """
    if not isinstance(body, dict):
        yield 'body', _Unreadable(body)
        return

    entries = body.get('entry')
    if entries is None:
        return
    if not isinstance(entries, list):
        yield 'entry', _Unreadable(entries)
        return

    for entry in entries:
        if not isinstance(entry, dict):
            yield 'entry[]', _Unreadable(entry)
            continue
        yield 'entry.time', entry.get('time')

        changes = entry.get('changes')
        if changes is None:
            continue
        if not isinstance(changes, list):
            yield 'entry.changes', _Unreadable(changes)
            continue

        for change in changes:
            if not isinstance(change, dict):
                yield 'changes[]', _Unreadable(change)
                continue
            value = change.get('value')
            if value is None:
                continue
            if not isinstance(value, dict):
                yield 'change.value', _Unreadable(value)
                continue

            calls = value.get('calls')
            if calls is None:
                # No calls envelope: the timestamp, if any, sits on `value`.
                calls = [value]
            elif isinstance(calls, dict):
                # A single call object rather than a list. Read it as one call -
                # the plausible shape change, and reading it is strictly safer
                # than ignoring it.
                calls = [calls]
            elif not isinstance(calls, list):
                yield 'value.calls', _Unreadable(calls)
                continue

            for call in calls:
                if not isinstance(call, dict):
                    yield 'calls[]', _Unreadable(call)
                    continue
                yield 'call.timestamp', call.get('timestamp')


def _validate_webhook_timestamp(body: Dict, request_id: str) -> bool:
    """Replay protection. True if the event may be processed.

    Absent timestamp -> allowed. Meta does omit `time`/`timestamp` on some event
    shapes, and rejecting those would drop legitimate traffic, so absence cannot
    be treated as a failure.

    Present but unparsable -> REJECTED. This is the case that used to fail open.
    `int('not-a-number')` raised inside the one enclosing try/except, the handler
    logged a warning and returned True, so anyone replaying a captured
    signature-valid payload only had to corrupt the timestamp field to defeat the
    5-minute window entirely. Replay protection that can be switched off by the
    replayer is not replay protection. A value we cannot read is not evidence of
    freshness, and the only safe reading of it is "too old".
    """
    now = int(time.time())
    for label, raw in _iter_webhook_timestamps(body):
        verdict = _timestamp_verdict(raw, now)
        if verdict in ('absent', 'ok'):
            continue
        logger.warning(json.dumps({
            'event': 'webhook_timestamp_rejected',
            'position': label,
            'verdict': verdict,
            # The raw value is attacker-controlled, so cap it rather than logging
            # an unbounded string.
            'raw': str(raw)[:64],
            'maxAge': WEBHOOK_MAX_AGE_SECONDS,
            'requestId': request_id,
        }))
        return False
    return True


def _handle_webhook_event(body: Dict, request_id: str) -> Dict[str, Any]:
    """Process incoming WhatsApp webhook events."""
    # Replay protection: reject events older than 5 minutes
    if not _validate_webhook_timestamp(body, request_id):
        logger.warning(json.dumps({'event': 'webhook_replay_rejected', 'requestId': request_id}))
        return _response(200, {'status': 'rejected', 'reason': 'stale_timestamp'})

    logger.info(json.dumps({
        'event': 'webhook_received', 'requestId': request_id,
        'body_preview': json.dumps(body)[:2000],
    }))

    obj = body.get('object', '')
    entries = body.get('entry', [])

    if obj != 'whatsapp_business_account':
        return _response(200, {'status': 'ignored', 'object': obj})

    for entry in entries:
        waba_id = entry.get('id', '')
        changes = entry.get('changes', [])
        for change in changes:
            field = change.get('field', '')
            value = change.get('value', {})

            if field == 'calls':
                # New Meta webhook format: calls is an array inside value
                calls = value.get('calls', [value])
                metadata = value.get('metadata', {})
                contacts = value.get('contacts', [])
                logger.info(f"Processing {len(calls)} call event(s) for waba_id={waba_id}, "
                            f"phone_number_id={metadata.get('phone_number_id', 'N/A')}, "
                            f"display_phone={mask_phone(metadata.get('display_phone_number') or '')}")
                for call in calls:
                    _handle_call_event(waba_id, call, metadata, contacts, request_id)
            elif field == 'messages':
                # Forward message events to inbound handler (Direct API)
                _forward_to_inbound_handler(entry, waba_id, request_id)
            elif field == 'account_settings_update':
                # Calling settings update webhook (status, call_icon_visibility, sip.status, etc.)
                logger.info(json.dumps({
                    'event': 'account_settings_update',
                    'wabaId': waba_id,
                    'value_preview': json.dumps(value)[:500],
                    'requestId': request_id,
                }))
                try:
                    _process_account_settings_update(waba_id, value, request_id)
                except Exception as e:
                    logger.error(f"account_settings_update processing error: {e}", exc_info=True)
            elif field in ('account_update', 'account_alerts', 'account_review_update',
                           'business_capability_update', 'message_template_status_update',
                           'message_template_quality_update', 'message_template_components_update',
                           'phone_number_quality_update', 'phone_number_name_update',
                           'security', 'template_category_update', 'user_id_update',
                           'user_preferences', 'group_participant_change',
                           'group_membership_approval_request', 'business_username_update',
                           'payment_configuration_update', 'history', 'flows'):
                # Forward all non-call webhook fields to inbound handler for processing
                # The inbound handler has full logic for template status, account updates, etc.
                _forward_to_inbound_handler(entry, waba_id, request_id)
            elif field in ('standby', 'messaging_handovers'):
                # ── Conversation Routing ──
                # These two forwarded identically to the tuple above via the catch-all
                # `else` below, so the ONLY change here is which log line is emitted.
                # They kept landing in "Unhandled webhook field", which reads as a defect
                # during triage and, worse, made this branch list the wrong answer to
                # "do we receive routing webhooks?" — we do, and a named event is what
                # lets a metric filter see one arrive. Routing is dormant (0 of either
                # field in 30 days) but WAS live on both WABAs in Jul-Aug 2026, so the
                # first arrival after an owner flips the console toggle is exactly the
                # moment somebody needs to know.
                logger.info(json.dumps({
                    'event': 'conversation_routing_webhook',
                    'field': field,
                    'wabaId': waba_id,
                    'requestId': request_id,
                }))
                _forward_to_inbound_handler(entry, waba_id, request_id)
            else:
                logger.info(f"Unhandled webhook field: {field} — forwarding to inbound handler")
                _forward_to_inbound_handler(entry, waba_id, request_id)

    return _response(200, {'status': 'processed', 'entries': len(entries)})


def _forward_to_inbound_handler(entry: Dict, waba_id: str, request_id: str) -> None:
    """
    Forward non-call webhook events (messages, statuses) to the inbound handler.
    Direct API uses override_callback_uri, so messages arrive here
    instead of via the standard webhook. We wrap them in the expected format the
    inbound handler expects and invoke it asynchronously.
    """
    try:
        # Extract metadata for context
        changes = entry.get('changes', [])
        meta_phone_ids = []
        for change in changes:
            value = change.get('value', {})
            metadata = value.get('metadata', {})
            pid = metadata.get('phone_number_id', '')
            if pid and pid not in meta_phone_ids:
                meta_phone_ids.append(pid)

        # A flat, typed, self-describing event — see lambda_utils/wa_internal_event.
        #
        # This used to be a synthetic SNS envelope,
        # {"Records":[{"Sns":{"Message": "<json string containing another json
        # string>"}}]}, left over from an architecture where Meta delivered through
        # AWS End User Messaging Social into a topic. No such subscription exists
        # anywhere in IaC or in the live event-source mappings, and the AWS account
        # has no linked WABA, so the shape described nothing while costing a double
        # JSON encode and sending every reader looking for a topic.
        inbound_event = wa_internal_event.build(
            entry=entry,
            waba_id=waba_id,
            meta_phone_number_ids=meta_phone_ids,
            request_id=request_id,
        )

        result = lambda_client.invoke(
            FunctionName=INBOUND_HANDLER_FUNCTION,
            InvocationType='Event',  # async — don't wait
            Payload=json.dumps(inbound_event),
        )

        logger.info(json.dumps({
            'event': 'forwarded_to_inbound_handler',
            'wabaId': waba_id,
            'phoneNumberIds': meta_phone_ids,
            'contractVersion': wa_internal_event.CONTRACT_VERSION,
            'statusCode': result.get('StatusCode'),
            'requestId': request_id,
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'forward_to_inbound_handler_failed',
            'wabaId': waba_id,
            'error': str(e),
            'requestId': request_id,
        }), exc_info=True)


def _handle_call_event(waba_id: str, call: Dict, metadata: Dict, contacts: list, request_id: str) -> None:
    """Handle a single call event from webhook. Extracts BSUID and username."""
    event_type = call.get('event', '')
    call_id = call.get('id', call.get('call_id', ''))
    from_number = call.get('from', '')
    to_number = call.get('to', '')
    direction = call.get('direction', 'USER_INITIATED')
    phone_number_id = metadata.get('phone_number_id', '')
    display_phone = metadata.get('display_phone_number', '')
    timestamp = call.get('timestamp', str(int(time.time())))

    # Extract BSUID from call event (from_user_id for user-initiated, to_user_id for biz-initiated)
    from_bsuid = call.get('from_user_id', '')
    to_bsuid = call.get('to_user_id', '')
    from_parent_bsuid = call.get('from_parent_user_id', '')
    to_parent_bsuid = call.get('to_parent_user_id', '')
    caller_bsuid = from_bsuid if direction == 'USER_INITIATED' else to_bsuid
    caller_parent_bsuid = from_parent_bsuid if direction == 'USER_INITIATED' else to_parent_bsuid

    # Extract caller name and username from contacts array
    caller_name = ''
    caller_username = ''
    if contacts:
        contact_info = contacts[0]
        caller_name = contact_info.get('profile', {}).get('name', '')
        caller_username = contact_info.get('profile', {}).get('username', '')
        # Also get BSUID from contacts if not in call event
        if not caller_bsuid:
            caller_bsuid = contact_info.get('user_id', '')

    now = int(time.time())

    logger.info(json.dumps({
        'event': 'call_event', 'type': event_type, 'call_id': call_id,
        'from': mask_phone(from_number), 'to': mask_phone(to_number), 'direction': direction,
        'phone_number_id': phone_number_id, 'has_caller_name': bool(caller_name),
        'caller_bsuid': caller_bsuid, 'has_caller_username': bool(caller_username),
    }))

    if event_type == 'connect':
        # Inbound call — extract SDP offer
        session = call.get('session', {})
        sdp_offer = session.get('sdp', call.get('sdp_offer', ''))
        sdp_type = session.get('sdp_type', 'offer')

        _store_call_log({
            'callId': call_id,
            'wabaId': waba_id,
            'phoneNumberId': phone_number_id,
            'displayPhone': display_phone,
            'fromNumber': from_number,
            'toNumber': to_number,
            'callerName': caller_name,
            'fromBsuid': caller_bsuid or None,
            'fromParentBsuid': caller_parent_bsuid or None,
            'callerUsername': caller_username or None,
            'direction': direction,
            'eventType': 'connect',
            'status': 'ringing',
            'sdpOffer': sdp_offer,
            'sdpType': sdp_type,
            'timestamp': timestamp,
            'createdAt': Decimal(str(now)),
            'ttl': Decimal(str(now + TTL_SECONDS)),
        })
        # `caller_name` is the customer's own WhatsApp profile name, so its presence is
        # logged rather than its value - the same rule `inbound-whatsapp-handler` follows.
        # The masked number plus `call_id` is enough to correlate.
        logger.info(f"INBOUND CALL from {mask_phone(from_number or '')} (has_caller_name: {bool(caller_name)}, BSUID: {caller_bsuid or 'N/A'}) — call_id: {call_id}, has_sdp: {bool(sdp_offer)}, sdp_len: {len(sdp_offer) if sdp_offer else 0}, phone_number_id: {phone_number_id}")

        # ── Pre-call auto-grant permission on connect ──
        # As soon as a call connects (any direction), auto-store permission as GRANTED.
        # This ensures outbound calls can proceed without interactive permission messages.
        if from_number:
            _store_call_log({
                'callId': f"pre_perm_{from_number}_{now}",
                'wabaId': waba_id,
                'phoneNumberId': phone_number_id,
                'fromNumber': from_number,
                'toNumber': to_number,
                'direction': direction,
                'eventType': 'permission_response',
                'status': 'permission_granted',
                'permission': 'GRANTED',
                'timestamp': timestamp,
                'createdAt': Decimal(str(now)),
                'ttl': Decimal(str(now + TTL_SECONDS)),
            })
            logger.info(f"Pre-call auto-granted permission for {mask_phone(from_number or '')} on connect (call {call_id})")

        # ── SMS moved to disconnect only — no SMS on connect to avoid duplicates ──
        # SMS is sent in the terminate handler (_send_disconnect_sms) instead
        # This prevents the user from receiving 2 identical SMS per call
        # But the WhatsApp follow-up IS still sent on connect (not a duplicate)
        _send_call_whatsapp_notification(from_number, call_id, phone_number_id, request_id)

        # Auto-pickup: IVR mode only — pre_accept → send IVR menu → terminate
        if _is_auto_pickup_enabled() and phone_number_id:
            logger.info(f"AUTO-PICKUP IVR — call {call_id} from {mask_phone(from_number or '')} (has_caller_name: {bool(caller_name)})")
            _auto_pickup_and_play(call_id, phone_number_id, from_number, sdp_offer)

    elif event_type == 'terminate':
        reason = call.get('reason', 'unknown')
        duration = call.get('duration', 0)
        # Extract Meta error code from terminate event if present
        error_code = call.get('error_code', call.get('code', ''))
        if error_code and int(error_code) in META_CALLING_ERRORS:
            meta_err = META_CALLING_ERRORS[int(error_code)]
            logger.warning(f"Call {call_id} terminated with Meta error {error_code}: "
                           f"{meta_err['msg']} | Action: {meta_err['action']}")
            if int(error_code) in ROUTING_OWNERSHIP_ERRORS:
                logger.error(json.dumps({
                    'event': 'routing_ownership_rejected',
                    'metaCode': int(error_code),
                    'callId': call_id,
                    'surface': 'calling_terminate',
                    'requestId': request_id,
                }))
        _store_call_log({
            'callId': call_id,
            'wabaId': waba_id,
            'phoneNumberId': phone_number_id,
            'fromNumber': from_number,
            'toNumber': to_number,
            'fromBsuid': caller_bsuid or None,
            'fromParentBsuid': caller_parent_bsuid or None,
            'callerUsername': caller_username or None,
            'direction': direction,
            'eventType': 'terminate',
            'status': 'ended',
            'terminateReason': reason,
            'errorCode': str(error_code) if error_code else None,
            'duration': duration,
            'timestamp': timestamp,
            'createdAt': Decimal(str(now)),
            'ttl': Decimal(str(now + TTL_SECONDS)),
        })

        # Unified timeline breadcrumb — one 'call' row in MessagesTable per ended call
        # (full record stays in WhatsAppCallingTable). Idempotent on callId.
        try:
            _dur = int(duration) if duration not in (None, '') else 0
            _bc_status = 'answered' if _dur > 0 else (reason or 'missed')
            put_call_breadcrumb(
                call_id=call_id,
                direction='inbound' if direction == 'USER_INITIATED' else 'outbound',
                status=str(_bc_status),
                duration=_dur or None,
                call_type='whatsapp',
                phone=from_number or to_number,
                timestamp=int(now),
            )
        except Exception as _bce:
            logger.warning(f"call breadcrumb skipped: {_bce}")

        # Send post-call reaction to the caller via WhatsApp message
        # ✅ for completed calls (duration > 0), ❌ for missed/rejected
        _send_post_call_reaction(
            phone_number_id=phone_number_id,
            from_number=from_number,
            call_id=call_id,
            reason=reason,
            duration=duration,
            direction=direction,
        )

        # ── Auto-grant call permission after any completed call ──
        # This removes the need for interactive call_permission_request messages.
        # Once a user has had a call (any direction), permission is auto-stored as GRANTED.
        if from_number and duration and int(duration) > 0:
            _store_call_log({
                'callId': f"auto_perm_{from_number}_{now}",
                'wabaId': waba_id,
                'phoneNumberId': phone_number_id,
                'fromNumber': from_number,
                'toNumber': to_number,
                'direction': direction,
                'eventType': 'permission_response',
                'status': 'permission_granted',
                'permission': 'GRANTED',
                'timestamp': timestamp,
                'createdAt': Decimal(str(now)),
                'ttl': Decimal(str(now + TTL_SECONDS)),
            })
            logger.info(f"Auto-granted call permission for {mask_phone(from_number or '')} after completed call {call_id} (duration={duration}s)")

        # ── Send the IVR follow-up SMS on every call disconnect (phone 1 & 2) ──
        # ivr-default DLT template, through AWS End User Messaging.
        if _is_sms_on_call_enabled() and from_number:
            _send_disconnect_sms(from_number, call_id, phone_number_id, reason, request_id)
        
        # ── Send RCS notification via Sinch (if enabled) ──
        if from_number:
            try:
                from lambda_utils.sinch_rcs import is_rcs_enabled, send_rcs_ivr_notification
                if is_rcs_enabled():
                    rcs_result = send_rcs_ivr_notification(from_number, request_id)
                    logger.info(json.dumps({
                        'event': 'wa_call_rcs_notification',
                        'callId': call_id,
                        'rcs_sent': rcs_result.get('success', False),
                        'rcs_message_id': rcs_result.get('message_id', ''),
                        'rcs_error': rcs_result.get('error', '') if not rcs_result.get('success') else '',
                        'requestId': request_id,
                    }))
                else:
                    logger.info(f'RCS disabled — skipping for call {call_id}')
            except Exception as rcs_err:
                logger.error(f'RCS notification EXCEPTION (non-blocking): {rcs_err}', exc_info=True)

    elif event_type in ('call_permission_response', 'call_permission_status'):
        # Legacy: Meta sends call_permission_status — no longer used for gating.
        # Permission is auto-granted post-call. Just log for audit.
        permission = call.get('status', call.get('permission', ''))
        recipient = call.get('recipient', call.get('to', to_number))
        logger.info(f"Call permission webhook (ignored): {permission} from {mask_phone(from_number or recipient or '')} on {phone_number_id}")

    else:
        _store_call_log({
            'callId': call_id or str(uuid.uuid4()),
            'wabaId': waba_id,
            'phoneNumberId': phone_number_id,
            'fromNumber': from_number,
            'eventType': event_type or 'unknown',
            'status': 'logged',
            'rawEvent': json.dumps(call)[:1000],
            'timestamp': timestamp,
            'createdAt': Decimal(str(now)),
            'ttl': Decimal(str(now + TTL_SECONDS)),
        })


def _handle_cert_check(event: Dict, request_id: str) -> Dict[str, Any]:
    """
    SIP TLS certificate expiry monitor (belt-and-suspenders on top of certbot auto-renew).

    Invoked daily by a cron on the Lightsail Asterisk box, which computes the days
    remaining on the live SIP cert and passes them here. This handler:
      - logs the result (INFO normally, ERROR when critical — easy to alarm on / grep),
      - publishes a CloudWatch metric Wecare/SIP -> CertDaysToExpiry
        (the alarm wecare-sip-cert-expiry-<host> on this metric emails the
         wecare-alarm-notifications SNS topic when it breaches <= warn days).

    Expected event: {action:'cert_check', daysRemaining:int, notAfter:str, host:str}
    All side effects are best-effort and never raise — a monitor must not page itself.
    """
    CERT_WARN_DAYS = int(os.environ.get('CERT_WARN_DAYS', '10'))
    try:
        days = int(event.get('daysRemaining'))
    except (TypeError, ValueError):
        logger.error(json.dumps({'event': 'cert_check_bad_payload', 'payload': str(event)[:300], 'requestId': request_id}))
        return {'statusCode': 400, 'body': 'daysRemaining required (int)'}

    host = event.get('host', 'sip.wecare.digital')
    not_after = event.get('notAfter', '')
    critical = days <= CERT_WARN_DAYS

    log_payload = {
        'event': 'sip_cert_check',
        'host': host,
        'daysRemaining': days,
        'notAfter': not_after,
        'warnThreshold': CERT_WARN_DAYS,
        'critical': critical,
        'requestId': request_id,
    }
    if critical:
        logger.error(json.dumps({**log_payload, 'alert': 'SIP_CERT_EXPIRING_SOON'}))
    else:
        logger.info(json.dumps(log_payload))

    # ── Publish CloudWatch metric (best-effort). The alarm
    #    'wecare-sip-cert-expiry-<host>' on this metric is provisioned once out-of-band
    #    and notifies the wecare-alarm-notifications SNS topic. ──
    try:
        cw = boto3.client('cloudwatch', region_name=REGION)
        cw.put_metric_data(
            Namespace='Wecare/SIP',
            MetricData=[{
                'MetricName': 'CertDaysToExpiry',
                'Dimensions': [{'Name': 'Host', 'Value': host}],
                'Value': float(days),
                'Unit': 'Count',
            }],
        )
    except Exception as e:
        logger.warning(json.dumps({'event': 'cert_check_cloudwatch_failed', 'error': str(e), 'requestId': request_id}))

    return {'statusCode': 200, 'body': json.dumps({'daysRemaining': days, 'critical': critical, 'warnThreshold': CERT_WARN_DAYS})}


def _is_auto_thumb_reaction_enabled() -> bool:
    """Whether to auto-send a 👍 reaction alongside call-related WhatsApp
    messages. Unified runtime toggle (controls call + message reactions across all
    handlers). Default: True. Toggle via SystemConfig id='whatsapp_auto_thumb'."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': 'whatsapp_auto_thumb'})
        item = result.get('Item')
        if item and 'configValue' in item:
            return str(item.get('configValue')).lower() in ('true', '1', 'yes', 'on')
    except Exception as e:
        logger.warning(f"auto_thumb config check failed (default True): {e}")
    return True


def _react_thumbs_up(meta_id: str, to_phone: str, message_id: str,
                     request_id: str = '', emoji: str = '\U0001F44D') -> bool:
    """Send an auto 👍 reaction to a message that THIS WABA (meta_id) just sent.

    CRITICAL: a reaction's message_id must belong to meta_id's own conversation.
    Reacting via a different WABA phone returns a Meta 'message not found' error,
    so callers MUST pass the same meta_id that produced message_id. This is what
    makes the auto-thumb work on BOTH WABA numbers — each WABA reacts to its own
    template message. Best-effort; never raises.
    """
    if not (meta_id and to_phone and message_id):
        return False
    if not _is_auto_thumb_reaction_enabled():
        return False
    try:
        result = _meta_api_call(f"{meta_id}/messages", 'POST', {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to_phone.lstrip('+'),
            'type': 'reaction',
            'reaction': {'message_id': message_id, 'emoji': emoji},
        }, phone_number_id=meta_id)
        if isinstance(result, dict) and result.get('error'):
            logger.warning(json.dumps({
                'event': 'auto_thumb_reaction_failed',
                'waba': meta_id, 'messageId': message_id,
                'error': str(result.get('error'))[:300], 'requestId': request_id,
            }))
            return False
        logger.info(json.dumps({
            'event': 'auto_thumb_reaction_sent',
            'waba': meta_id, 'messageId': message_id, 'requestId': request_id,
        }))
        return True
    except Exception as e:
        logger.warning(f"auto thumb reaction error via {meta_id}: {e}")
        return False


def _send_menu_placeholder_text(meta_id: str, to_phone: str,
                                request_id: str = '') -> str:
    """Send MENU_PLACEHOLDER_TEXT as a plain WhatsApp text from meta_id.

    This is a TEXT send, so it needs an open 24-hour customer-service window.
    The WhatsApp menu template this replaced was deleted at Meta, and a template
    was what allowed a post-call message outside that window, so a follow-up to
    someone who has never messaged the business now fails. That is expected: the
    failure is logged and both call sites treat this send as non-blocking.

    Uses _meta_api_call rather than _send_via_aws on purpose — the returned
    wamid must belong to meta_id's own conversation, which is the precondition
    _react_thumbs_up documents. Returns the Meta message id, or '' on failure.
    """
    if not (meta_id and to_phone):
        return ''
    try:
        result = _meta_api_call(f"{meta_id}/messages", 'POST', {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to_phone.lstrip('+'),
            'type': 'text',
            'text': {'body': MENU_PLACEHOLDER_TEXT},
        }, phone_number_id=meta_id)
        if isinstance(result, dict):
            msgs = result.get('messages', [])
            if msgs:
                return msgs[0].get('id', '')
        return ''
    except Exception as e:
        logger.warning(f"menu placeholder text send failed via {meta_id}: "
                       f"{type(e).__name__}")
        return ''


def _handle_post_call_sip(event: Dict, request_id: str) -> Dict[str, Any]:
    """
    Handle post-call actions from Asterisk AGI (SIP mode).
    Called via Lambda invoke after a WhatsApp call ends on Asterisk.
    Sends the plain-text menu placeholder from the WABA that received the call
    + WABA1 if different. Text, not a template, so it needs an open 24-hour
    window — see _send_menu_placeholder_text.
    """
    caller_phone = event.get('callerPhone', '')
    # No default sender. This used to fall back to WABA2's phone, which meant a
    # call received on WABA1 was followed up from a number the caller never
    # dialled - cross-WABA, and outside the 24-hour window belonging to the
    # conversation they actually opened. Refuse instead: a missing follow-up is a
    # visible bug, a follow-up from the wrong business number is an incident.
    phone_number_id = event.get('phoneNumberId', '')

    if not caller_phone:
        logger.warning("post_call_sip: no callerPhone")
        return {'statusCode': 200, 'body': 'no caller'}

    if not phone_number_id:
        logger.error(json.dumps({
            'event': 'post_call_sip_no_phone_number_id',
            'alert': 'WHATSAPP_SENDER_UNRESOLVED',
            'note': 'refusing to pick a WABA; the caller would receive a message '
                    'from a number they never contacted',
            'requestId': request_id,
        }))
        return {'statusCode': 200, 'body': 'sender unresolved; nothing sent'}

    # Clean phone number
    if not caller_phone.startswith('+'):
        caller_phone = f'+{caller_phone}'

    # Unified-timeline breadcrumb — makes the SIP call show in [retired public path]/calls,
    # the unified inbox (channel=voice), and Contact 360. Non-blocking.
    try:
        _bc_contact = _lookup_contact_id_for_inbox(caller_phone)
        put_call_breadcrumb(
            call_id=event.get('callId') or f"sipcall_{caller_phone.lstrip('+')}_{int(time.time())}",
            direction='inbound',
            contact_id=_bc_contact or '',
            status='completed',
            call_type='whatsapp',
            phone=caller_phone,
            duration=(int(event['duration']) if str(event.get('duration') or '').isdigit() else None),
            recording_url=(event.get('recordingUrl') or None),
        )
    except Exception as _bce:
        logger.warning(f"post_call_sip breadcrumb failed (non-blocking): {_bce}")

    # Determine which WABAs to send from based on receiving phone
    is_waba2_call = str(phone_number_id) == PHONE2_META_ID
    if is_waba2_call:
        send_from = [(WABA1_META_ID, 'WABA1'), (WABA2_META_ID, 'WABA2')]
    else:
        send_from = [(WABA1_META_ID, 'WABA1')]

    logger.info(f"POST-CALL SIP: sending menu placeholder text to {mask_phone(caller_phone or '')} via {', '.join(l for _, l in send_from)}")

    # Send from each WABA (gated by the post-call WhatsApp toggle)
    wa_enabled = _is_postcall_wa_enabled()
    first_msg_id = ''
    for meta_id, label in (send_from if wa_enabled else []):
        msg_id = _send_menu_placeholder_text(meta_id, caller_phone, request_id)
        if msg_id:
            logger.info(f"Post-call SIP menu placeholder sent via {label}: {msg_id}")
            # Auto 👍 from the SAME WABA that sent this message (works on both WABAs).
            _react_thumbs_up(meta_id, caller_phone, msg_id, request_id)
            if not first_msg_id:
                first_msg_id = msg_id
        else:
            # Most likely cause is a closed 24-hour window: this is a text send
            # and there is no longer a template to reach outside it.
            logger.warning(f"Post-call SIP menu placeholder FAILED via {label}")

    msg_id = first_msg_id

    # Store in outbound table so it shows in dashboard inbox
    if msg_id:
        try:
            outbound_table = dynamodb.Table('stack-wecare-digital-WhatsAppOutboundTable')
            now = int(time.time())
            store_id = msg_id or f"postcall_{caller_phone}_{now}"
            contact_id = _lookup_contact_id_for_inbox(caller_phone)

            # Fix: ensure whatsappMessageId is never empty (DynamoDB GSI rejects empty strings)
            wa_msg_id = msg_id if msg_id else store_id

            outbound_table.put_item(Item={
                'id': store_id,
                'messageId': store_id,
                'contactId': contact_id,
                'contactPhone': caller_phone,
                'content': MENU_PLACEHOLDER_TEXT,
                'channel': 'whatsapp',
                'direction': 'outbound',
                'status': 'sent',
                'messageType': 'post_call',
                'whatsappMessageId': wa_msg_id,
                'phoneNumberId': phone_number_id,
                'awsPhoneNumberId': phone_number_id,
                'timestamp': Decimal(str(now)),
                'createdAt': Decimal(str(now)),
                'expiresAt': Decimal(str(now + 30 * 24 * 60 * 60)),
            })
            logger.info(f"Post-call message stored in outbound table: id={store_id}")
        except Exception as e:
            logger.error(f"Failed to store post-call message: {e}", exc_info=True)

    # Step 4: Call permission request removed — not sending interactive permission_response after calls

    # Step 5: Post-call SMS — ivr-default template, via AWS End User Messaging
    if caller_phone and _is_sms_on_call_enabled():
        _send_disconnect_sms(caller_phone, f'sip_{caller_phone}', phone_number_id, 'sip_hangup', 'sip_post_call')
    
    # Step 6: Post-call RCS — send Sinch RCS notification on disconnect
    if caller_phone:
        try:
            from lambda_utils.sinch_rcs import is_rcs_enabled, send_rcs_ivr_notification
            if is_rcs_enabled():
                send_rcs_ivr_notification(caller_phone, 'sip_post_call')
        except Exception:
            pass  # Non-blocking

    return {'statusCode': 200, 'body': 'post_call_sent'}


def _send_post_call_reaction(phone_number_id: str, from_number: str, call_id: str,
                              reason: str, duration: int, direction: str) -> None:
    """
    Send a post-call summary message to the caller/callee after a call ends.
    Uses Direct Meta API to send a text message with call details.
    - Completed calls (duration > 0): ✅ with duration
    - Missed/rejected/no-answer: ❌ with reason
    - AI-redirected calls: skip (redirect message already sent)
    
    Note: Requires an open 24-hour messaging window. If the window is closed
    (e.g. caller never messaged this business number), the send will fail silently.
    """
    try:
        # Skip post-call reaction if the call was AI-redirected
        try:
            table = dynamodb.Table(CALL_LOG_TABLE)
            from boto3.dynamodb.conditions import Key as DDBKey
            # Indexed lookup on callId-index (GSI exists) instead of a full-table scan.
            result_check = table.query(
                IndexName='callId-index',
                KeyConditionExpression=DDBKey('callId').eq(call_id),
                Limit=10,
            )
            ai_handled = any(
                i.get('status') in ('ai_redirected',)
                for i in result_check.get('Items', [])
            )
            if ai_handled:
                logger.info(f"Post-call reaction skipped: call {call_id} was AI-handled")
                return
        except Exception:
            pass  # If check fails, send the reaction anyway

        aws_phone_id = _get_aws_phone_id(phone_number_id)
        # Determine the recipient — for inbound calls, reply to the caller (from_number)
        to_number = from_number

        if not to_number:
            logger.warning(f"Post-call reaction skipped: no from_number for call {call_id}")
            return

        logger.info(f"Post-call reaction: phone_number_id={phone_number_id}, "
                     f"aws_phone_id={aws_phone_id}, to={mask_phone(to_number or '')}, "
                     f"direction={direction}, reason={reason}, duration={duration}")

        if duration and int(duration) > 0:
            mins = int(duration) // 60
            secs = int(duration) % 60
            duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            text = f"📞 ✅ Call completed — {duration_str}"
        else:
            reason_map = {
                'no_answer': 'No answer',
                'busy': 'Busy',
                'rejected': 'Rejected',
                'timeout': 'Timed out',
                'caller_hangup': 'Caller hung up',
                'callee_hangup': 'Call ended',
            }
            reason_text = reason_map.get(reason, reason.replace('_', ' ').title() if reason else 'Unknown')
            text = f"📞 ❌ Call ended — {reason_text}"

        result = _send_via_aws(aws_phone_id, to_number, {
            'type': 'text',
            'text': {'body': text},
        })

        if result.get('error'):
            error_detail = result.get('detail', '')
            # Check if it's a 24-hour window issue
            if 'outside' in error_detail.lower() or 'window' in error_detail.lower() or '131047' in error_detail:
                logger.warning(f"Post-call reaction skipped (no 24h window): "
                               f"to={mask_phone(to_number or '')}, via={aws_phone_id}, call={call_id}")
            else:
                # `result` on this branch is the RAW Meta response (`_send_via_aws` returns
                # it unchanged when Meta reports an error), and Meta writes the recipient
                # into the prose of several messaging errors. Dumping it whole masked the
                # number on the left of this line and reprinted it on the right.
                logger.error(f"Post-call reaction FAILED for {mask_phone(to_number or '')} via {aws_phone_id}: "
                             f"{meta_error_summary(result)}")
        else:
            logger.info(f"Post-call reaction sent to {mask_phone(to_number or '')}: {text} — "
                        f"messageId={result.get('messageId')}")
    except Exception as e:
        logger.error(f"Failed to send post-call reaction: {e}", exc_info=True)


# ─── Call Control (Reject / Hangup) ──────────────────────────────────

def _terminate_call(event: Dict, request_id: str) -> Dict[str, Any]:
    """Reject or hang up a call."""
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _response(400, {'error': 'Invalid JSON in request body'})
    call_id = body.get('callId', '')
    phone_number_id = body.get('phoneNumberId', '')

    if not call_id or not phone_number_id:
        return _response(400, {'error': 'callId and phoneNumberId required'})

    logger.info(f"Terminating call {call_id} on {phone_number_id}")

    result = _meta_api_call(f"{phone_number_id}/calls", 'POST', {
        'messaging_product': 'whatsapp',
        'call_id': call_id,
        'action': 'terminate',
    }, phone_number_id=phone_number_id)

    _update_call_status(call_id, 'terminated')

    return _response(200, {
        'success': not result.get('error'),
        'callId': call_id,
        'result': result,
    })


def _outbound_call(event: Dict, request_id: str) -> Dict[str, Any]:
    """
    Initiate outbound call directly (no interactive permission request).
    Body: { phoneNumberId, to, action: 'create', sdpOffer, recipientBsuid? }

    Permission is auto-granted after any completed call (see terminate handler).
    The old 'permission_request' action is removed — no interactive messages sent.
    """
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _response(400, {'error': 'Invalid JSON in request body'})
    phone_number_id = body.get('phoneNumberId', '')
    to_number = body.get('to', '')
    action = body.get('action', 'create')
    recipient_bsuid = body.get('recipientBsuid', '')

    if not phone_number_id or (not to_number and not recipient_bsuid):
        return _response(400, {'error': 'phoneNumberId and to (or recipientBsuid) required'})

    # Send a free-form call permission request (interactive). Per Meta docs this is only
    # valid inside an open 24h customer service window; outside it, a pre-approved
    # call_permission_request *template* is required instead.
    if action == 'permission_request':
        body_text = (body.get('bodyText') or 'May we call you on WhatsApp to help with your query?').strip()
        perm_interactive = {
            'type': 'call_permission_request',
            'action': {'name': 'call_permission_request'},
        }
        if body_text:
            perm_interactive['body'] = {'text': body_text[:1024]}
        perm_payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to_number,
            'type': 'interactive',
            'interactive': perm_interactive,
        }
        if recipient_bsuid:
            perm_payload['recipient'] = recipient_bsuid
        result = _meta_api_call(f"{phone_number_id}/messages", 'POST', perm_payload, phone_number_id=phone_number_id)
        ok = not result.get('error')
        if ok:
            logger.info(f"call_permission_request sent to {mask_phone(to_number)} via {phone_number_id}")
        else:
            logger.error(f"call_permission_request failed to {mask_phone(to_number)}: {json.dumps(result)[:500]}")
        return _response(200, {'success': ok, 'action': 'permission_request', 'result': result})

    # Check the current call-permission state for a business+user pair (GET /call_permissions).
    if action == 'check_permission':
        if not to_number and not recipient_bsuid:
            return _response(400, {'error': 'to or recipientBsuid required'})
        q = f"recipient={recipient_bsuid}" if (recipient_bsuid and not to_number) else f"user_wa_id={to_number.lstrip('+')}"
        result = _meta_api_call(f"{phone_number_id}/call_permissions?{q}", 'GET', None, phone_number_id=phone_number_id)
        status = ''
        can_call = False
        if isinstance(result, dict) and not result.get('error'):
            status = (result.get('permission') or {}).get('status', '')
            for a in result.get('actions', []):
                if a.get('action_name') == 'start_call':
                    can_call = bool(a.get('can_perform_action'))
        return _response(200, {'success': not result.get('error'), 'action': 'check_permission',
                               'permissionStatus': status, 'canCall': can_call, 'result': result})

    # Create a call_permission_request TEMPLATE (one-time; requires Meta approval).
    # Once approved it can be sent to brand-new numbers outside the 24h customer service window.
    if action == 'create_permission_template':
        waba_id = WABA2_ID if str(phone_number_id) == PHONE2_META_ID else WABA1_ID
        tmpl_name = (body.get('templateName') or 'wd_call_permission').strip()
        tmpl_body = (body.get('bodyText') or 'May we call you on WhatsApp to help with your request?').strip()
        category = (body.get('category') or 'UTILITY').upper()
        payload = {
            'name': tmpl_name,
            'language': 'en',
            'category': category,
            'components': [
                {'type': 'BODY', 'text': tmpl_body},
                {'type': 'call_permission_request'},
            ],
        }
        result = _meta_api_call(f"{waba_id}/message_templates", 'POST', payload, phone_number_id=phone_number_id)
        ok = not result.get('error')
        if ok:
            logger.info(f"call_permission_request template '{tmpl_name}' created on WABA {waba_id}: {json.dumps(result)[:300]}")
        else:
            logger.error(f"create_permission_template failed: {json.dumps(result)[:500]}")
        return _response(200, {'success': ok, 'action': 'create_permission_template', 'wabaId': waba_id, 'result': result})

    # Send an approved call_permission_request TEMPLATE (works outside the 24h window).
    if action == 'send_permission_template':
        tmpl_name = (body.get('templateName') or 'wd_call_permission').strip()
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to_number,
            'type': 'template',
            'template': {'name': tmpl_name, 'language': {'code': 'en'}},
        }
        if recipient_bsuid:
            payload['recipient'] = recipient_bsuid
        result = _meta_api_call(f"{phone_number_id}/messages", 'POST', payload, phone_number_id=phone_number_id)
        ok = not result.get('error')
        if ok:
            logger.info(f"call_permission_request template '{tmpl_name}' sent to {mask_phone(to_number)}")
        else:
            logger.error(f"send_permission_template failed to {mask_phone(to_number)}: {json.dumps(result)[:500]}")
        return _response(200, {'success': ok, 'action': 'send_permission_template', 'result': result})

    # Initiate outbound (business-initiated) call.
    # Meta's /calls 'action' enum is [accept, connect, media_update, pre_accept, reject, terminate].
    # Business-initiated calls use action='connect' with the SDP offer inside a 'session' object.
    # We accept the legacy 'create' alias from the frontend and map it to 'connect'.
    if action in ('create', 'connect'):
        sdp_offer = body.get('sdpOffer', '')
        if not sdp_offer:
            return _response(400, {'error': 'sdpOffer required for outbound call'})
        payload = {
            'messaging_product': 'whatsapp',
            'action': 'connect',
            'to': to_number,
            'session': {
                'sdp_type': 'offer',
                'sdp': sdp_offer,
            },
        }
        # Add BSUID recipient if available (per Meta Calling API BSUID docs)
        if recipient_bsuid:
            payload['recipient'] = recipient_bsuid
        result = _meta_api_call(f"{phone_number_id}/calls", 'POST', payload, phone_number_id=phone_number_id)
        return _response(200, {'success': not result.get('error'), 'action': 'connect', 'result': result})

    return _response(400, {'error': f'Unknown action: {action}'})


# ─── Auto-Pickup Configuration ──────────────────────────────────────
# When enabled, incoming calls are automatically answered and a pre-recorded
# IVR greeting is sent as a WhatsApp audio message to the caller, then call disconnects.
# Default: ON — auto-pickup is enabled by default.
# Toggle via SystemConfig table or environment variable.

SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
# The PUBLIC host for media this function uploads, kept separate from the bucket.
# The IVR greeting URL below was a HARDCODED 'https://app.wecare.digital/{key}',
# which broke twice over on 2026-09-28: that host was deleted, and once it was
# rebuilt it served with OriginPath=/o while this function writes to the bucket
# root, so the old literal would have resolved to o/{key} and 404ed.
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)
# ── LOCKED CONFIGURATION — DO NOT CHANGE WITHOUT TESTING ──
# IVR audio: incoming_welcome.ogg (OGG/OPUS — WhatsApp supported format)
# .sln16 is Asterisk-only format, WhatsApp rejects it (wrong MIME type)
DEFAULT_IVR_URL = os.environ.get('AUTO_PICKUP_IVR_URL', 'https://wecare.digital/get/o/stream/media/ivr/incoming_welcome.ogg')
AUTO_PICKUP_DEFAULT = os.environ.get('AUTO_PICKUP_ENABLED', 'true').lower() == 'true'

# The IVR audio greeting text. Was read from the deleted IVR button menu's
# 'greeting' key; it is a plain constant now because there is no menu to
# configure. Markdown-free on purpose: the caller below strips formatting for
# Polly anyway, and there are no buttons for it to introduce.
IVR_GREETING_TEXT = "Thanks for calling WECARE.DIGITAL. How can we help you today?"

s3 = boto3.client('s3', region_name=REGION)
polly_client = boto3.client('polly', region_name=REGION)

# IVR TTS voice config (used by _generate_ivr_tts_audio for Polly)
AI_VOICE_ID = os.environ.get('AI_VOICE_ID', 'Kajal')

# Phone number ID mapping for outbound audio via Direct API
PHONE_NUMBER_ID_1 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE_NUMBER_ID_2 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')

# All phones use Direct Meta API — full call control supported on all WABAs


# ── SMS on incoming call ─────────────────────────────────────────────
# Sent through AWS End User Messaging via lambda_utils.comms.notify.
#
# The BODY below is load-bearing. It must match the approved TRAI DLT content
# template character for character, including the \n\n between sections: the
# operator silently drops mismatched content even though the API call succeeds.
# Do not "improve" this copy.
#
# The template id, registered entity and sender id are NOT repeated here. They
# live in lambda_utils.comms.dlt, keyed by IVR_SMS_DLT_TEMPLATE_KEY below.
# Template KEYS, not ids. lambda_utils.comms.dlt maps a key to the approved
# template id and attaches the registered entity and sender. Holding raw ids here
# was one of five copies of the same regulatory facts.
IVR_SMS_DLT_TEMPLATE_KEY = 'ivr-default'
ORDER_SMS_DLT_TEMPLATE_KEY = 'wd_order'
IVR_SMS_CONTENT = (
    "Thanks for contacting WECARE.DIGITAL!\n\n"
    "Submit your request here: https://wecare.digital/submit-request/ "
    "or send us a message / voice note on WhatsApp: "
    "https://wecare.digital/r/wa.\n\n"
    "We'll review it and follow up if needed."
)

# Stand-in for the WhatsApp menu, which has been deleted. Every call-related
# WhatsApp follow-up sends this plain text instead of an interactive menu. The
# wording is shared verbatim with the inbound handler's MENU_PLACEHOLDER_TEXT,
# as a separate module-level copy because the two Lambdas share no module.
MENU_PLACEHOLDER_TEXT = "We're refreshing our menu - please type *menu* and we'll help you."

# Order SMS. Body must match approved DLT template wd_order character for
# character; the key is ORDER_SMS_DLT_TEMPLATE_KEY above.
ORDER_SMS_CONTENT = (
    "Thanks for placing your order with WECARE.DIGITAL!\n\n"
    "Your order has been received. We'll review it and share updates shortly.\n\n"
    "Need help? Submit a request here: https://wecare.digital/submit-request/ "
    "or message / voice note us on WhatsApp: https://wecare.digital/r/wa."
)

# WhatsApp template video URL (CloudFront — publicly accessible)
WA_TEMPLATE_VIDEO_URL = 'https://wecare.digital/get/o/stream/media/m/customerservice.mp4'

# WABA phone IDs for sending templates
WABA1_META_ID = '1016149501586345'   # +91 93309 94400
WABA2_META_ID = '1055232054343117'   # +91 99033 00044

# SMS routing: there is none to do here any more.
#
# Every destination, every country, goes to AWS End User Messaging through
# lambda_utils.comms.notify. Region selection (ap-south-1 for +91, us-east-1
# otherwise) and the TRAI DLT gate live in lambda_utils.comms, not in this file.
#
# Removed 2026-09-19: the previous "LOCKED SMS ROUTING" block, which sent +91
# through an Indian operator's API via a static-IP proxy with a synchronous
# two-attempt retry, then fell back to AWS. That retry ran inside a webhook
# handler and could stall it for ~4 seconds before the fallback even started.
# See docs/provider-retirement-inventory.md.


def _send_incoming_call_sms(caller_phone: str, call_id: str, receiving_phone_id: str, request_id: str) -> None:
    """Send default IVR SMS + the WhatsApp menu placeholder when a call comes in.
    
    WhatsApp logic:
    - Call on WABA1 → send from WABA1 only
    - Call on WABA2 → send from BOTH WABA1 AND WABA2
    
    All sent notifications are stored in WhatsAppOutboundTable for inbox visibility.
    """
    try:
        if not caller_phone:
            return
        clean_phone = caller_phone.lstrip('+')

        # One call, every country. comms.notify picks the region and applies the
        # DLT gate; this handler no longer decides either.
        from lambda_utils.comms.notify import send_notification_sms
        outcome = send_notification_sms(
            caller_phone, IVR_SMS_CONTENT,
            dlt_template_key=IVR_SMS_DLT_TEMPLATE_KEY,
            campaign='whatsapp-incoming-call',
            request_id=request_id)
        sms_sent = outcome.queued
        if not sms_sent:
            logger.warning(json.dumps({
                'event': 'incoming_call_sms_not_queued',
                'callId': call_id,
                'callerPhone': caller_phone[-4:],
                'reason': outcome.skipped_reason or outcome.error,
                'requestId': request_id,
            }))

        # ── Store SMS in inbox ──
        if sms_sent:
            contact_id = _lookup_contact_id_for_inbox(caller_phone)
            _store_notification_to_inbox(
                message_id=f"sms_call_{call_id}_{int(time.time())}",
                contact_id=contact_id,
                contact_phone=caller_phone,
                content=IVR_SMS_CONTENT,
                channel='sms',
                status='sent',
                message_type='incoming_call',
                request_id=request_id,
            )

        _mark_sms_sent(clean_phone)

        # ── WhatsApp follow-up: depends on which WABA received the call ──
        _send_call_whatsapp_notification(caller_phone, call_id, receiving_phone_id, request_id)

    except Exception as e:
        logger.warning(f"Incoming call SMS failed (non-blocking): {e}")


def _send_disconnect_sms(caller_phone: str, call_id: str, phone_number_id: str,
                         reason: str, request_id: str) -> None:
    """Send the IVR follow-up SMS on every call disconnect — no dedup.
    Stores to WhatsAppOutboundTable for inbox visibility.
    """
    try:
        if not caller_phone:
            return
        clean_phone = caller_phone.lstrip('+')

        from lambda_utils.comms.notify import send_notification_sms
        outcome = send_notification_sms(
            caller_phone, IVR_SMS_CONTENT,
            dlt_template_key=IVR_SMS_DLT_TEMPLATE_KEY,
            campaign='whatsapp-call-disconnect',
            request_id=request_id)
        sms_sent = outcome.queued
        logger.info(json.dumps({
            'event': 'disconnect_sms_triggered' if sms_sent
                     else 'disconnect_sms_not_queued',
            'callId': call_id,
            'callerPhone': caller_phone[-4:],
            'phoneNumberId': phone_number_id,
            'provider': 'aws-end-user-messaging',
            'reason': reason,
            'notQueuedReason': (outcome.skipped_reason or outcome.error) or None,
            'requestId': request_id,
        }))

        # ── Store disconnect SMS in inbox ──
        if sms_sent:
            contact_id = _lookup_contact_id_for_inbox(caller_phone)
            _store_notification_to_inbox(
                message_id=f"sms_disc_{call_id}_{int(time.time())}",
                contact_id=contact_id,
                contact_phone=caller_phone,
                content=IVR_SMS_CONTENT,
                channel='sms',
                status='sent',
                message_type='disconnect',
                request_id=request_id,
            )

        # Mark SMS as sent for dedup
        _mark_sms_sent(clean_phone)

    except Exception as e:
        logger.warning(f"Disconnect SMS failed (non-blocking): {e}")


DIRECT_API_META_PHONE_IDS = {PHONE1_META_ID, PHONE2_META_ID}


def _is_auto_pickup_enabled() -> bool:
    """Check if auto-pickup is enabled via SystemConfig table."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': 'whatsapp_calling_auto_pickup'})
        item = result.get('Item')
        if item:
            return str(item.get('configValue', 'false')).lower() == 'true'
    except Exception as e:
        logger.warning(f"Failed to read auto-pickup config: {e}")
    return AUTO_PICKUP_DEFAULT


def _get_auto_pickup_audio_url() -> Optional[str]:
    """Get the IVR audio URL for auto-pickup greeting.
    Uses direct URL by default: https://wecare.digital/get/o/stream/media/ivr/incoming_welcome.ogg
    """
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': 'whatsapp_calling_ivr_url'})
        item = result.get('Item')
        if item and item.get('configValue'):
            return str(item['configValue']).strip()
    except Exception as e:
        logger.warning(f"Failed to read IVR URL config: {e}")
    return DEFAULT_IVR_URL


def _is_sms_on_call_enabled() -> bool:
    """Check if SMS-on-incoming-call is enabled via SystemConfig table. Default: True."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': 'whatsapp_calling_sms_on_call'})
        item = result.get('Item')
        if item:
            return str(item.get('configValue', 'true')).lower() == 'true'
    except Exception as e:
        logger.warning(f"Failed to read sms_on_call config: {e}")
    return True  # Default: enabled


def _is_postcall_wa_enabled() -> bool:
    """Check if the post-call WhatsApp message is enabled. Default: True."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': 'whatsapp_calling_postcall_wa'})
        item = result.get('Item')
        if item:
            return str(item.get('configValue', 'true')).lower() == 'true'
    except Exception as e:
        logger.warning(f"Failed to read postcall_wa config: {e}")
    return True  # Default: enabled


# ── SMS Dedup: prevent duplicate SMS to the same number within a cooldown window ──
SMS_DEDUP_WINDOW_SECONDS = 600  # 10 minutes — one SMS per phone per window


def _sms_sent_recently(phone_digits: str) -> bool:
    """Check if we already sent an IVR SMS to this phone number within the dedup window."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        result = table.get_item(Key={'id': f'sms_dedup_{phone_digits}'})
        item = result.get('Item')
        if item:
            last_sent = float(item.get('configValue', 0))
            if time.time() - last_sent < SMS_DEDUP_WINDOW_SECONDS:
                return True
    except Exception as e:
        logger.warning(f"SMS dedup check failed (allowing send): {e}")
    return False


def _mark_sms_sent(phone_digits: str) -> None:
    """Record that we just sent an IVR SMS to this phone number (for dedup)."""
    try:
        table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        now = int(time.time())
        table.put_item(Item={
            'id': f'sms_dedup_{phone_digits}',
            'configValue': str(now),
            'ttl': Decimal(str(now + SMS_DEDUP_WINDOW_SECONDS + 60)),  # auto-cleanup
        })
    except Exception as e:
        logger.warning(f"SMS dedup mark failed: {e}")


def _auto_pickup_and_play(call_id: str, phone_number_id: str, from_number: str, sdp_offer: str) -> None:
    """
    IVR mode: Accept the call with SDP answer to establish WebRTC media,
    send IVR audio greeting as WhatsApp audio message, then terminate the call.

    WhatsApp Calling API flow (per Meta docs):
      1. pre_accept (with SDP answer) — establishes WebRTC connection, stops ringing
      2. accept (with SDP answer) — starts media flow so caller hears audio
      3. Send IVR audio greeting via WhatsApp audio message
      4. Terminate call after delay — caller continues via chat

    Note: WhatsApp Calling API uses WebRTC for media. To play IVR audio
    IN the call (not as a chat message), you need either:
      a) SIP mode with Asterisk (plays audio via RTP/SRTP)
      b) WebRTC media server generating SDP answer with audio stream
    
    Current approach: pre_accept + accept to connect the call, send IVR
    audio as WhatsApp message (caller sees it in chat), then terminate.
    For true in-call IVR audio, enable SIP mode on the phone number and
    route through Asterisk which has IVR audio playback support.

    All phones use Direct API — full call control supported.
    """

    logger.info(json.dumps({
        'event': 'ivr_start',
        'call_id': call_id,
        'from': mask_phone(from_number),
        'phone_number_id': phone_number_id,
        'has_sdp_offer': bool(sdp_offer),
        'sdp_offer_len': len(sdp_offer) if sdp_offer else 0,
    }))

    # ── Step 1: Pre-accept with SDP answer to establish WebRTC connection ──
    # Per Meta docs: pre_accept with SDP answer pre-establishes the WebRTC
    # connection to prevent audio clipping when the call is accepted.
    pre_payload = {
        'messaging_product': 'whatsapp',
        'call_id': call_id,
        'action': 'pre_accept',
    }
    # If we have an SDP offer, generate a minimal SDP answer
    # This establishes the media path so the caller's audio is connected
    if sdp_offer:
        sdp_answer = _generate_sdp_answer(sdp_offer)
        if sdp_answer:
            pre_payload['session'] = {
                'sdp_type': 'answer',
                'sdp': sdp_answer,
            }
            logger.info(f"IVR pre_accept with SDP answer (len={len(sdp_answer)})")

    pre_result = _meta_api_call(f"{phone_number_id}/calls", 'POST',
                                pre_payload, phone_number_id=phone_number_id)
    logger.info(f"IVR pre_accept: {json.dumps(pre_result)}")

    if pre_result.get('error'):
        logger.error(f"IVR pre_accept failed: {json.dumps(pre_result)}")
        _update_call_status(call_id, 'ivr_failed', {'failStep': 'pre_accept', 'error': pre_result})
        # Carry on to accept anyway — the audio greeting is still worth attempting.
    else:
        _update_call_status(call_id, 'ivr_pre_accepted')

    # ── Step 2: Accept the call to start media flow ──
    # Per Meta docs: accept with SDP answer starts actual media flow.
    # Business has 30-60 seconds to accept after pre_accept.
    accept_payload = {
        'messaging_product': 'whatsapp',
        'call_id': call_id,
        'action': 'accept',
    }
    if sdp_offer:
        sdp_answer = _generate_sdp_answer(sdp_offer)
        if sdp_answer:
            accept_payload['session'] = {
                'sdp_type': 'answer',
                'sdp': sdp_answer,
            }

    accept_result = _meta_api_call(f"{phone_number_id}/calls", 'POST',
                                   accept_payload, phone_number_id=phone_number_id)
    logger.info(f"IVR accept: {json.dumps(accept_result)}")

    if accept_result.get('error'):
        logger.warning(f"IVR accept failed (call may still be pre_accepted): {json.dumps(accept_result)}")
        _update_call_status(call_id, 'ivr_accept_failed', {'error': accept_result})
    else:
        _update_call_status(call_id, 'ivr_active')

    # ── Step 3: Send IVR audio greeting as WhatsApp audio message ──
    audio_url = _get_auto_pickup_audio_url()
    if audio_url:
        _send_audio_to_caller(phone_number_id, from_number, audio_url, call_id)
        logger.info(f"IVR audio sent to {mask_phone(from_number or '')}: {audio_url}")

    # ── Step 4: Keep call connected briefly, then terminate ──
    # 3s is enough for caller to hear the connection tone and the audio greeting
    # Reduced from 5s to minimize Lambda execution time
    time.sleep(3)
    try:
        term_result = _meta_api_call(f"{phone_number_id}/calls", 'POST', {
            'messaging_product': 'whatsapp',
            'call_id': call_id,
            'action': 'terminate',
        }, phone_number_id=phone_number_id)
        logger.info(f"IVR terminate: {json.dumps(term_result)}")
    except Exception as e:
        logger.info(f"IVR terminate skipped (call may have ended): {e}")

    _update_call_status(call_id, 'ivr_completed')


def _generate_sdp_answer(sdp_offer: str) -> Optional[str]:
    """
    Generate a minimal SDP answer from the SDP offer.
    
    Per Meta WhatsApp Calling API docs:
    - Audio codec: OPUS (default, always supported)
    - Additional codecs: PCMA, PCMU (G.711) if configured
    - Media encryption: WebRTC (ICE + DTLS + SRTP) or SDES
    
    This generates a basic SDP answer that accepts the OPUS codec
    from the offer. For full WebRTC media handling (actual audio
    streaming), use SIP mode with Asterisk.
    
    The SDP answer tells Meta's servers we're ready to receive media,
    which is required for the call to be properly connected.
    """
    if not sdp_offer:
        return None

    try:
        # Parse the offer to extract key parameters
        lines = sdp_offer.strip().split('\n')
        
        # Extract ICE credentials and fingerprint from offer
        ice_ufrag = ''
        ice_pwd = ''
        fingerprint = ''
        ssrc = ''
        
        for line in lines:
            line = line.strip()
            if line.startswith('a=ice-ufrag:'):
                ice_ufrag = line.split(':', 1)[1]
            elif line.startswith('a=ice-pwd:'):
                ice_pwd = line.split(':', 1)[1]
            elif line.startswith('a=fingerprint:'):
                fingerprint = line
            elif line.startswith('a=ssrc:') and not ssrc:
                ssrc = line.split(':')[1].split(' ')[0]

        # Generate our own ICE credentials for the answer.
        # secrets (not random) so creds stay unique under Lambda SnapStart, where
        # a restored snapshot would otherwise share the random PRNG state.
        import secrets
        import string
        our_ufrag = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        our_pwd = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))

        # Build minimal SDP answer accepting OPUS codec (payload type 111)
        answer_lines = [
            'v=0',
            f'o=- {int(time.time())} 2 IN IP4 0.0.0.0',
            's=-',
            't=0 0',
            # Audio media line — accept OPUS (111)
            'm=audio 9 UDP/TLS/RTP/SAVPF 111',
            'c=IN IP4 0.0.0.0',
            'a=rtcp:9 IN IP4 0.0.0.0',
            f'a=ice-ufrag:{our_ufrag}',
            f'a=ice-pwd:{our_pwd}',
            'a=ice-options:trickle',
            'a=setup:active',
            'a=mid:0',
            'a=recvonly',  # We only receive audio (IVR doesn't send audio via WebRTC)
            'a=rtcp-mux',
            'a=rtpmap:111 opus/48000/2',
            'a=fmtp:111 minptime=10;useinbandfec=1',
        ]

        # Add fingerprint if present in offer (required for DTLS)
        if fingerprint:
            answer_lines.insert(-3, fingerprint)

        sdp_answer = '\r\n'.join(answer_lines) + '\r\n'
        logger.info(f"Generated SDP answer: {len(sdp_answer)} bytes, "
                     f"ice_ufrag={our_ufrag[:4]}..., has_fingerprint={bool(fingerprint)}")
        return sdp_answer

    except Exception as e:
        logger.error(f"SDP answer generation failed: {e}", exc_info=True)
        return None


def _get_aws_phone_id(meta_phone_number_id: str) -> str:
    """Map Meta phone_number_id to internal phone-number-id for routing."""
    META_TO_AWS = {
        PHONE1_META_ID: PHONE_NUMBER_ID_1,
        PHONE2_META_ID: PHONE_NUMBER_ID_2,
    }
    return META_TO_AWS.get(meta_phone_number_id, PHONE_NUMBER_ID_1)


def _send_via_aws(aws_phone_id: str, to_number: str, message_payload: Dict) -> Dict:
    """Send a WhatsApp message via Direct Meta API."""
    # AWS requires '+' prefix on phone numbers
    if not to_number.startswith('+'):
        to_number = f'+{to_number}'
    message_payload['to'] = to_number
    message_payload['messaging_product'] = 'whatsapp'

    # All phones use Direct API — send via Meta Graph API
    DIRECT_API_PHONES = {
        PHONE_NUMBER_ID_1: PHONE1_META_ID,             # WABA1: +91 93309 94400
        PHONE_NUMBER_ID_2: PHONE2_META_ID,             # WABA-T: +91 99033 00044
    }
    meta_phone_id = DIRECT_API_PHONES.get(aws_phone_id)
    if not meta_phone_id:
        logger.error(f"No Direct API mapping for phone {aws_phone_id}")
        return {'error': True, 'detail': f'No Direct API mapping for {aws_phone_id}'}
    try:
        result = _meta_api_call(
            f"{meta_phone_id}/messages", 'POST',
            message_payload, phone_number_id=meta_phone_id
        )
        if result.get('error'):
            # This is where the raw Meta error enters the rest of the function: it is
            # returned unchanged, so every caller that logs the return value logs Meta's
            # prose. The return is deliberately left as-is -- callers branch on its
            # fields -- but nothing here or downstream may print it whole.
            logger.error(f"Direct API send failed for {meta_phone_id}: {meta_error_summary(result)}")
            return result
        msg_id = ''
        messages = result.get('messages', [])
        if messages:
            msg_id = messages[0].get('id', '')
        logger.info(f"Direct API send success ({meta_phone_id}): messageId={msg_id}")
        return {'success': True, 'messageId': msg_id}
    except Exception as e:
        logger.error(f"Direct API send failed for {meta_phone_id}: {e}")
        return {'error': True, 'detail': str(e)}


def _send_audio_to_caller(phone_number_id: str, to_number: str, audio_url: str, call_id: str) -> None:
    """
    Send IVR greeting audio as a WhatsApp audio message via Direct API.
    
    Sends the configured IVR audio URL only. No fallbacks.
    """
    try:
        aws_phone_id = _get_aws_phone_id(phone_number_id)

        result = _send_via_aws(aws_phone_id, to_number, {
            'type': 'audio',
            'audio': {'link': audio_url},
        })

        if result.get('error'):
            # Raw Meta response on this branch, same as the post-call reaction site above.
            logger.warning(f"IVR audio URL failed ({audio_url}): {meta_error_summary(result)}")
        else:
            # Success shape is only `{'success': True, 'messageId': ...}`, so the whole
            # dict was in fact safe here -- but naming the one field it contains says that,
            # where `json.dumps(result)` relied on the reader knowing the success path.
            logger.info(f"IVR audio sent to {mask_phone(to_number or '')}: "
                        f"messageId={result.get('messageId')}")
    except Exception as e:
        logger.error(f"Failed to send auto-pickup audio: {e}", exc_info=True)


def _generate_ivr_tts_audio(phone_number_id: str, call_id: str) -> Optional[str]:
    """
    Generate IVR greeting audio via Amazon Polly TTS → OGG/OPUS → S3 → public URL.
    
    WhatsApp requires OGG with OPUS codec for audio messages.
    Polly supports ogg_vorbis output, but WhatsApp needs OPUS.
    Polly also supports mp3 which WhatsApp accepts.
    
    Returns a public S3 URL for the generated audio, or None on failure.
    """
    try:
        greeting_text = IVR_GREETING_TEXT
        # Strip markdown formatting for TTS
        clean_text = greeting_text.replace('*', '').replace('📞', '').replace('\n\n', '. ').replace('\n', '. ').strip()

        # Generate MP3 via Polly (WhatsApp accepts audio/mpeg)
        voice_id = AI_VOICE_ID or 'Kajal'
        engine = 'neural'

        polly_resp = polly_client.synthesize_speech(
            Text=clean_text,
            OutputFormat='mp3',
            VoiceId=voice_id,
            Engine=engine,
            SampleRate='24000',
        )

        audio_stream = polly_resp.get('AudioStream')
        if not audio_stream:
            logger.error("Polly returned no audio stream")
            return None

        audio_bytes = audio_stream.read()
        if len(audio_bytes) < 100:
            logger.error(f"Polly audio too small: {len(audio_bytes)} bytes")
            return None

        # Upload to S3 with public-read ACL
        s3_key = media_paths.public(
            f'whatsapp-media/whatsapp-calling/ivr-greeting-{call_id[:8]}.mp3')
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=s3_key,
            Body=audio_bytes,
            ContentType='audio/mpeg',
        )

        # Generate a public URL via the CDN host, not the bucket name
        public_url = f'https://{CDN_DOMAIN}/{s3_key}'
        logger.info(f"IVR TTS audio generated: {public_url} ({len(audio_bytes)} bytes, voice={voice_id})")
        return public_url

    except Exception as e:
        logger.error(f"IVR TTS generation failed: {e}", exc_info=True)
        return None


# ─── Active Calls (for frontend polling) ────────────────────────────

def _get_active_calls(params: Dict, request_id: str) -> Dict[str, Any]:
    """Get calls with status 'ringing', 'pre_accepted', or 'connected' for the frontend."""
    try:
        table = dynamodb.Table(CALL_LOG_TABLE)
        result = table.scan(
            FilterExpression='#s IN (:r, :c, :a, :p)',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':r': 'ringing',
                ':c': 'connected',
                ':a': 'auto_answered',
                ':p': 'pre_accepted',
            },
        )
        items = result.get('Items', [])
        # Convert Decimal for JSON
        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = float(v)
        items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        return _response(200, {'calls': items, 'count': len(items)})
    except Exception as e:
        logger.error(f"Get active calls error: {e}")
        return _response(200, {'calls': [], 'count': 0, 'error': str(e)})


# ─── Auto-Pickup Config API ─────────────────────────────────────────
# GET  /whatsapp/config  → Get auto-pickup config
# POST /whatsapp/config  → Update auto-pickup config

def _get_config(request_id: str) -> Dict[str, Any]:
    """Get auto-pickup configuration."""
    enabled = _is_auto_pickup_enabled()
    audio_url = _get_auto_pickup_audio_url()
    sms_on_call = _is_sms_on_call_enabled()
    return _response(200, {
        'autoPickup': enabled,
        'ivrUrl': audio_url,
        'defaultIvrUrl': DEFAULT_IVR_URL,
        'autoPickupMode': 'ivr',
        'smsOnCall': sms_on_call,
        'postCallWa': _is_postcall_wa_enabled(),
        'autoThumb': _is_auto_thumb_reaction_enabled(),
    })


def _update_config(event: Dict, request_id: str) -> Dict[str, Any]:
    """Update auto-pickup configuration (toggle + IVR URL)."""
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _response(400, {'error': 'Invalid JSON in request body'})
    enabled = body.get('autoPickup')
    ivr_url = body.get('ivrUrl')

    table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

    if enabled is not None:
        try:
            table.put_item(Item={
                'id': 'whatsapp_calling_auto_pickup',
                'configValue': str(enabled).lower(),
                'updatedAt': Decimal(str(int(time.time()))),
            })
            logger.info(f"Auto-pickup set to: {enabled}")
        except Exception as e:
            logger.error(f"Failed to update auto-pickup config: {e}")
            return _response(500, {'error': str(e)})

    if ivr_url is not None:
        try:
            table.put_item(Item={
                'id': 'whatsapp_calling_ivr_url',
                'configValue': ivr_url.strip(),
                'updatedAt': Decimal(str(int(time.time()))),
            })
            logger.info(f"IVR URL set to: {ivr_url}")
        except Exception as e:
            logger.error(f"Failed to update IVR URL config: {e}")
            return _response(500, {'error': str(e)})

    sms_on_call = body.get('smsOnCall')
    if sms_on_call is not None:
        try:
            table.put_item(Item={
                'id': 'whatsapp_calling_sms_on_call',
                'configValue': str(sms_on_call).lower(),
                'updatedAt': Decimal(str(int(time.time()))),
            })
            logger.info(f"SMS-on-call set to: {sms_on_call}")
        except Exception as e:
            logger.error(f"Failed to update sms_on_call config: {e}")
            return _response(500, {'error': str(e)})

    post_call_wa = body.get('postCallWa')
    if post_call_wa is not None:
        try:
            table.put_item(Item={
                'id': 'whatsapp_calling_postcall_wa',
                'configValue': str(post_call_wa).lower(),
                'updatedAt': Decimal(str(int(time.time()))),
            })
            logger.info(f"Post-call WhatsApp set to: {post_call_wa}")
        except Exception as e:
            logger.error(f"Failed to update postcall_wa config: {e}")
            return _response(500, {'error': str(e)})

    auto_thumb = body.get('autoThumb')
    if auto_thumb is not None:
        try:
            table.put_item(Item={
                'id': 'whatsapp_auto_thumb',
                'configValue': str(auto_thumb).lower(),
                'updatedAt': Decimal(str(int(time.time()))),
            })
            logger.info(f"Auto 👍 reaction set to: {auto_thumb}")
        except Exception as e:
            logger.error(f"Failed to update auto_thumb config: {e}")
            return _response(500, {'error': str(e)})

    return _response(200, {'success': True, 'autoPickup': enabled, 'ivrUrl': ivr_url, 'autoPickupMode': 'ivr', 'smsOnCall': sms_on_call, 'postCallWa': post_call_wa, 'autoThumb': auto_thumb})

# ─── Storage Helpers ─────────────────────────────────────────────────

def _process_account_settings_update(waba_id: str, value: Dict, request_id: str) -> None:
    """Persist calling settings / restriction webhook events for audit + admin visibility.

    Handles the `account_settings_update` field which Meta sends when calling
    configuration changes (status, call_icon_visibility, sip.status) OR when the
    phone number's calling functionality is restricted/paused due to negative user
    feedback or low pickup rates.
    """
    if not isinstance(value, dict):
        return
    now = int(time.time())
    calling = value.get('calling', {}) if isinstance(value.get('calling'), dict) else {}
    metadata = value.get('metadata', {}) if isinstance(value.get('metadata'), dict) else {}
    phone_id = value.get('phone_number_id') or metadata.get('phone_number_id', '')
    status = (calling.get('status') or value.get('status') or '').upper()

    # Detect calling-restriction signals (pause / violation / low pickup)
    restrictions = (
        calling.get('restrictions')
        or value.get('restrictions')
        or calling.get('calling_restrictions')
        or []
    )

    _store_call_log({
        'callId': f"settings_{waba_id}_{now}",
        'wabaId': waba_id,
        'phoneNumberId': phone_id,
        'eventType': 'settings_update',
        'status': status or 'updated',
        'apiResponse': json.dumps(value, default=str)[:1000],
        'timestamp': Decimal(str(now)),
        'ttl': Decimal(str(now + TTL_SECONDS)),
    })

    if restrictions:
        logger.warning(json.dumps({
            'event': 'calling_restriction_detected',
            'wabaId': waba_id,
            'phoneNumberId': mask_phone(phone_id) if phone_id else '',
            'restrictions': restrictions,
            'requestId': request_id,
        }))
        _store_call_log({
            'callId': f"restriction_{waba_id}_{now}",
            'wabaId': waba_id,
            'phoneNumberId': phone_id,
            'eventType': 'calling_restriction',
            'status': 'restricted',
            'apiResponse': json.dumps(restrictions, default=str)[:1000],
            'timestamp': Decimal(str(now)),
            'ttl': Decimal(str(now + TTL_SECONDS)),
        })


def _store_call_log(item: Dict) -> None:
    """Store call event in DynamoDB."""
    try:
        table = dynamodb.Table(CALL_LOG_TABLE)
        item['id'] = f"{item.get('callId', 'unknown')}_{item.get('eventType', 'unknown')}_{int(time.time())}"
        clean = {k: v for k, v in item.items() if v is not None and v != ''}
        table.put_item(Item=clean)
        logger.info(f"Stored call log: {item.get('id')}")
    except Exception as e:
        logger.error(f"Store call log error: {e}")


def _update_call_status(call_id: str, new_status: str, extra: Dict = None) -> None:
    """Update the status of the most recent log entry for a call."""
    try:
        table = dynamodb.Table(CALL_LOG_TABLE)
        # Indexed query on callId-index (GSI exists) + eventType filter, replacing
        # the previous full-table scan. Also more correct: the old scan(Limit=10)
        # only inspected the first 10 rows table-wide and could miss the target row.
        from boto3.dynamodb.conditions import Key, Attr
        result = table.query(
            IndexName='callId-index',
            KeyConditionExpression=Key('callId').eq(call_id),
            FilterExpression=Attr('eventType').eq('connect'),
            Limit=10,
        )
        items = result.get('Items', [])
        if items:
            item = items[0]
            update_expr = 'SET #s = :s, #ua = :ua'
            expr_names = {'#s': 'status', '#ua': 'updatedAt'}
            expr_values = {':s': new_status, ':ua': Decimal(str(int(time.time())))}
            if extra:
                update_expr += ', #ex = :ex'
                expr_names['#ex'] = 'apiResponse'
                expr_values[':ex'] = json.dumps(extra, default=str)[:500]
            table.update_item(
                Key={'id': item['id']},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            logger.info(f"Updated call {call_id} status to {new_status}")
    except Exception as e:
        logger.error(f"Update call status error: {e}")


def _list_logs(params: Dict, request_id: str) -> Dict[str, Any]:
    """List call event logs."""
    try:
        table = dynamodb.Table(CALL_LOG_TABLE)
        result = table.scan(Limit=int(params.get('limit', 100)))
        items = result.get('Items', [])
        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = float(v)
        items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        return _response(200, {'logs': items, 'count': len(items)})
    except Exception as e:
        logger.error(f"List logs error: {e}")
        return _response(200, {'logs': [], 'count': 0, 'error': str(e)})


def _clear_logs(request_id: str) -> Dict[str, Any]:
    """Clear all call logs (paginated to handle large tables)."""
    try:
        table = dynamodb.Table(CALL_LOG_TABLE)
        deleted = 0
        scan_kwargs = {'ProjectionExpression': 'id'}
        while True:
            result = table.scan(**scan_kwargs)
            items = result.get('Items', [])
            if not items:
                break
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'id': item['id']})
                    deleted += 1
            if 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return _response(200, {'success': True, 'deletedCount': deleted})
    except Exception as e:
        return _response(200, {'success': False, 'error': str(e)})


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """HTTP response with CORS."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, default=str),
    }



# ── WhatsApp notification to both WABAs on incoming call ──
_WABA_PHONE_IDS = [
    'phone-number-id-waba1-direct-1016149501586345',   # +91 93309 94400
    'phone-number-id-waba-t-direct-1055232054343117',  # +91 99033 00044
]


def _lookup_contact_id_for_inbox(phone: str) -> str:
    """Look up contactId from ContactsTable by phone number for inbox storage.
    Returns the OLDEST contact (same logic as inbound handler) to avoid mismatch.
    Falls back to phone digits if no contact found.
    """
    clean = phone.replace('+', '').replace(' ', '').lstrip('+')
    contacts_table = dynamodb.Table('stack-wecare-digital-ContactsTable')
    for variant in ['+' + clean, clean, phone]:
        try:
            resp = contacts_table.query(
                IndexName='phone-index',
                KeyConditionExpression='phone = :phone',
                ExpressionAttributeValues={':phone': variant},
                Limit=10
            )
            items = [i for i in resp.get('Items', []) if not i.get('deletedAt')]
            if items:
                # Pick oldest contact (same as inbound handler) to avoid mismatch
                contact = sorted(items, key=lambda x: x.get('createdAt', 0))[0]
                return contact.get('contactId') or contact.get('id') or clean
        except Exception:
            pass
    return clean


def _store_notification_to_inbox(message_id: str, contact_id: str, contact_phone: str,
                                  content: str, channel: str, status: str,
                                  message_type: str, phone_number_id: str = '',
                                  wamid: str = '', request_id: str = '') -> None:
    """Store a sent notification in WhatsAppOutboundTable so it appears in the dashboard inbox."""
    try:
        now = int(time.time())
        store_id = message_id or f"notif_{contact_phone}_{now}"
        outbound_table = dynamodb.Table('stack-wecare-digital-WhatsAppOutboundTable')
        item = {
            'id': store_id,
            'messageId': store_id,
            'contactId': contact_id,
            'contactPhone': contact_phone,
            'content': content,
            'channel': channel,
            'direction': 'outbound',
            'status': status,
            'messageType': message_type,
            'timestamp': Decimal(str(now)),
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + 30 * 24 * 60 * 60)),
            'requestId': request_id,
        }
        # Only set GSI key fields if non-empty (DynamoDB rejects empty strings on GSI keys)
        if wamid:
            item['whatsappMessageId'] = wamid
        else:
            item['whatsappMessageId'] = store_id
        if phone_number_id:
            item['phoneNumberId'] = phone_number_id
            item['awsPhoneNumberId'] = phone_number_id
        outbound_table.put_item(Item=item)
        logger.info(json.dumps({
            'event': 'notification_stored_in_inbox',
            'id': store_id,
            'channel': channel,
            'contactId': mask_contact_id(contact_id),
            'requestId': request_id,
        }))
    except Exception as e:
        logger.warning(f'Failed to store notification in inbox: {e}')


def _send_call_whatsapp_notification(caller_phone: str, call_id: str, receiving_phone_id: str, request_id: str) -> None:
    """Send the plain-text menu placeholder to the CALLER.

    Logic:
    - Call on WABA1 (+919330994400) → send from WABA1 only
    - Call on WABA2 (+919903300044) → send from BOTH WABA1 AND WABA2

    This is a TEXT send and therefore needs an open 24-hour window — see
    _send_menu_placeholder_text. Both WABAs use the same token
    (WECARE.DIGITAL app / token1).

    DELIVERY TROUBLESHOOTING:
    - A closed 24-hour window is the expected failure now that the template is gone
    - If delivery fails: check Meta message status webhooks for error codes
    - Other causes: recipient blocked the business, rate limit
    """
    try:
        import time as _time
        call_time = _time.strftime('%d %b %Y %I:%M %p IST', _time.gmtime(int(_time.time()) + 19800))

        # Determine which WABAs to send from based on receiving phone
        is_waba2 = WABA2_META_ID in str(receiving_phone_id)
        if is_waba2:
            send_from = [(WABA1_META_ID, 'WABA1'), (WABA2_META_ID, 'WABA2')]
        else:
            send_from = [(WABA1_META_ID, 'WABA1')]

        for meta_id, label in send_from:
            try:
                # Try sending with 1 retry on failure (2s delay)
                msg_id = _send_menu_placeholder_text(meta_id, caller_phone, request_id)

                # Retry once on failure (Meta API can have transient errors)
                if not msg_id:
                    time.sleep(2)
                    logger.info(f'{label} menu placeholder retry after 2s...')
                    msg_id = _send_menu_placeholder_text(meta_id, caller_phone, request_id)

                if msg_id:
                    logger.info(json.dumps({
                        'event': 'call_wa_template_sent',
                        'messageType': 'text',
                        'waba': label,
                        'meta_phone_id': meta_id,
                        'caller': caller_phone[-4:],
                        'messageId': msg_id,
                        'requestId': request_id,
                    }))
                    # ── Store WhatsApp notification in inbox ──
                    contact_id = _lookup_contact_id_for_inbox(caller_phone)
                    _store_notification_to_inbox(
                        message_id=msg_id,
                        contact_id=contact_id,
                        contact_phone=caller_phone,
                        content=MENU_PLACEHOLDER_TEXT,
                        channel='whatsapp',
                        status='sent',
                        message_type='incoming_call',
                        phone_number_id=meta_id,
                        wamid=msg_id,
                        request_id=request_id,
                    )
                    # Auto 👍 from the SAME WABA that sent this message (both WABAs).
                    _react_thumbs_up(meta_id, caller_phone, msg_id, request_id)
                else:
                    logger.error(json.dumps({
                        'event': 'call_wa_template_FAILED',
                        'messageType': 'text',
                        'waba': label,
                        'meta_phone_id': meta_id,
                        'caller': caller_phone[-4:],
                        'requestId': request_id,
                        'troubleshoot': (
                            'This is a plain text send and needs an open 24-hour '
                            'window, so a caller who has never messaged the '
                            'business cannot be reached. Also check: 1) recipient '
                            'has not blocked this business, 2) rate limit, '
                            '3) Meta status webhook for delivery status'
                        ),
                    }))
            except Exception as e:
                logger.error(f'{label} menu placeholder EXCEPTION: {e}', exc_info=True)

        # Log to CallNotifications table
        try:
            call_notif_table = dynamodb.Table(
                os.environ.get('CALL_NOTIFICATIONS_TABLE', 'stack-wecare-digital-CallNotificationsTable')
            )
            call_notif_table.put_item(Item={
                'callId': call_id,
                'callerPhone': caller_phone,
                'callTime': call_time,
                'receivingPhone': receiving_phone_id,
                'whatsappTemplate': 'none',
                'whatsappWaba1': 'sent',
                'whatsappWaba2': 'sent' if is_waba2 else 'not_applicable',
                'smsStatus': 'sent_separately',
                'requestId': request_id,
                'createdAt': int(_time.time()),
                'ttl': int(_time.time()) + 90 * 86400,
            })
        except Exception as e:
            logger.warning(f'CallNotifications log failed: {e}')

    except Exception as e:
        logger.warning(f'Call WA notification error (non-blocking): {e}')
