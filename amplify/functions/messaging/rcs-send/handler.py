"""
Sinch RCS Send Lambda Function

Purpose: Send RCS messages via Sinch India Conversation API
Enterprise: WECARE.DIGITAL
BOT Type: Transactional

Configuration, as confirmed against the live account on 2026-09-23. The first three are
NON-SECRET and are supplied as environment variables; the credential pair is not:

  Username        wecaretrans                            (secret field, NOT an env var)
  Project ID      c8114d03-eeb2-401d-a8f1-abb93594cb33    RCS_PROJECT_ID
  Conv App ID     01KQSB792X3R148D8ZGHQYW3SP              RCS_APP_ID
  Bot ID          69e0b2c980cbf50614ffa5fd                (secret field)

This header previously read "App ID: wecaretrans", which conflated the Sinch *username*
with the Conversation App id. They are different values addressing different things -
the username authenticates the password grant and keys the v2 template endpoints, while
the app id identifies the Conversation App in the send payload.

Authentication:
- Token endpoint: POST https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token
- Grant type: password
- Client ID: ipmessaging-client
- Username/Password from Secrets Manager: wecare/sinch/rcs

Send API:
- POST https://convapi.aclwhatsapp.com/v1/projects/{projectId}/messages:send
- Authorization: Bearer <token>

DLR Webhook: POST https://wecare.digital/api/webhook/sinch-rcs
DLR Events: MESSAGE_DELIVERY, EVENT_DELIVERY, MESSAGE_INBOUND, etc.

Templates:
- "rcsmenu" (Rich Card, approved, Jio, MEDIUM) — IVR/call disconnect notifications
- "rcsorder" (Rich Card, approved, Jio, MEDIUM) — order confirmation notifications
- "waalert" (Rich Card, approved, Jio, MEDIUM) — WhatsApp alert notifications
- Template creation: POST https://api.aclwhatsapp.com/access-api/v1/rcs/{botId}/templates

Secrets: wecare/sinch/rcs
Expected keys: username, password, project_id, app_id, bot_id

Credentials come from Secrets Manager and nowhere else. There are deliberately no literal
defaults for `username` or `bot_id`: a default username puts half of the password-grant
credential pair into source control, and it also masks a real fault - a secret missing its
username would otherwise authenticate as the literal with an empty password and return a
401 that reads like a provider outage rather than a configuration error.

Do NOT migrate this to auth.sinch.com or a KEY_ID/KEY_SECRET pair. Live traffic
authenticates with the username/password grant against auth.aclwhatsapp.com; the global
Sinch credentials are a different account and would not carry this project.
"""

import os
import json
import uuid
import time
import logging
import boto3
import boto3.dynamodb.conditions
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.message_store import put_message  # canonical MessagesTable writer
from lambda_utils import contact_key  # `id` is the physical key; `contactId` is its alias

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Configuration
RCS_AUTH_URL = "https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token"
RCS_API_BASE = "https://convapi.aclwhatsapp.com/v1/projects"
RCS_PROJECT_ID = os.environ.get('RCS_PROJECT_ID', 'c8114d03-eeb2-401d-a8f1-abb93594cb33')
RCS_APP_ID = os.environ.get('RCS_APP_ID', '01KQSB792X3R148D8ZGHQYW3SP')
RCS_SECRET_NAME = os.environ.get('RCS_SECRET_NAME', 'wecare/sinch/rcs')
# RCS_TABLE removed 2026-09-21: unused constant naming a table that does not
# exist. The Phase 4 migration stopped the legacy dual-write and the canonical
# MessagesTable is the sole store.
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
# Canonical unified table — inbox list now reads this (channel=rcs).
UNIFIED_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')

# Token cache (reuse within Lambda warm start)
_token_cache = {'token': '', 'expires_at': 0, 'refresh_token': '', 'refresh_expires_at': 0}
_secrets_cache = None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle RCS send requests."""
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    if http_method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    if http_method == 'GET':
        return cors_response(200, {'status': 'ok', 'service': 'sinch-rcs'}, origin)

    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError):
        return cors_response(400, {'error': 'Invalid JSON body'}, origin)

    action = body.get('action', 'send')

    if action == 'send':
        return _send_rcs(body, request_id, origin)
    elif action == 'list':
        return _list_messages(body, request_id, origin)
    elif action == 'templates':
        return _list_templates(body, request_id, origin)
    elif action == 'create_template':
        return _create_template(body, request_id, origin)
    elif action == 'delete_template':
        return _delete_template(body, request_id, origin)
    elif action == 'diagnostics':
        return _diagnostics(body, request_id, origin)
    else:
        return cors_response(400, {'error': f'Unknown action: {action}'}, origin)


# ── Read-only control-plane discovery ────────────────────────────────────────
#
# Why this exists here rather than in a script or over MCP.
#
# The official Sinch MCP server authenticates against the GLOBAL Sinch Build
# platform with KEY_ID/KEY_SECRET. This integration runs on the Sinch INDIA
# platform inherited from the ACL Mobile acquisition, authenticated by a Keycloak
# password grant. An exhaustive search on 2026-09-22 found no key_id or key_secret
# in any of the 31 secrets, the single SSM parameter, any S3 object, or the
# environment of any of 59 Lambdas. So MCP cannot introspect this account at all.
#
# This function already holds the India credential and already authenticates. A
# read-only probe from inside it is therefore the only way to discover the RCS
# sender, agent, channel status and capabilities - and it keeps the password inside
# the Lambda, which is the point: the credential never reaches an operator's
# terminal, a log, or an agent's context.
#
# GET only. Every candidate path is enumerated explicitly rather than accepted from
# the request, so this cannot be turned into a general-purpose proxy for the Sinch
# credential by a caller who controls `body`.

_DIAG_PATHS = [
    # Conversation API shape - convapi mirrors Sinch's own, so these are the ones
    # most likely to carry `channelStatus`, which the audit specifically needs.
    ('convapi', '/v1/projects/{project_id}/apps'),
    ('convapi', '/v1/projects/{project_id}/apps/{app_id}'),
    ('convapi', '/v1/projects/{project_id}/webhooks'),
    # Access API shape - the template endpoints live here and work, so sibling
    # agent/capability resources plausibly do too. v2 keys on the app name, v1 on
    # the bot id; both spellings are tried because the template code uses both.
    ('accessapi', '/access-api/v2/rcs/{username}'),
    ('accessapi', '/access-api/v2/rcs/{username}/agent'),
    ('accessapi', '/access-api/v2/rcs/{username}/capabilities'),
    ('accessapi', '/access-api/v2/rcs/{username}/testers'),
    ('accessapi', '/access-api/v1/rcs/{bot_id}'),
    ('accessapi', '/access-api/v1/rcs/{bot_id}/agent'),
    ('accessapi', '/access-api/v1/rcs/{bot_id}/capabilities'),
    ('accessapi', '/access-api/v1/rcs/{bot_id}/testers'),
]

_DIAG_HOSTS = {
    'convapi': 'https://convapi.aclwhatsapp.com',
    'accessapi': 'https://api.aclwhatsapp.com',
}

# Response keys worth reporting because the audit asks for them by name.
_DIAG_INTERESTING = (
    'channelStatus', 'channel_status', 'state', 'status', 'region', 'countries',
    'countryStatus', 'country_status', 'testNumberStates', 'test_numbers',
    'testers', 'capabilities', 'features', 'agent', 'agentId', 'bot', 'botId',
    'senderId', 'sender_id', 'authName', 'auth_name', 'displayName', 'brand',
    'webhooks', 'target', 'triggers', 'apps', 'id', 'name', 'conversation_app',
)


def _diag_shape(value, depth: int = 0):
    """Describe a response by SHAPE and interesting keys, never verbatim.

    A control-plane response can contain a bearer token, an auth token or a
    customer number. Reporting the key set plus scalar values for an allowlist of
    non-sensitive fields gives the audit what it needs without copying the payload.
    """
    if depth > 3:
        return '...'
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            lowered = str(k).lower()
            if any(t in lowered for t in ('token', 'secret', 'password', 'key',
                                          'credential', 'authorization')):
                out[k] = '<redacted>'
            elif isinstance(v, (dict, list)):
                out[k] = _diag_shape(v, depth + 1)
            elif k in _DIAG_INTERESTING or depth <= 1:
                out[k] = v if not isinstance(v, str) else v[:120]
            else:
                out[k] = f'<{type(v).__name__}>'
        return out
    if isinstance(value, list):
        return [_diag_shape(v, depth + 1) for v in value[:5]] + (
            [f'...{len(value) - 5} more'] if len(value) > 5 else [])
    if isinstance(value, str):
        return value[:120]
    return value


def _diagnostics(body: Dict, request_id: str, origin: str) -> Dict:
    """Probe the India control plane read-only and report what answers.

    Returns per-path HTTP status and a redacted shape. Nothing is mutated and no
    message is sent.
    """
    token = _get_token()
    if not token:
        return cors_response(500, {'error': 'Auth failed — cannot probe'}, origin)

    creds = _get_secrets()
    substitutions = {
        'project_id': RCS_PROJECT_ID,
        'app_id': RCS_APP_ID,
        'username': creds.get('username') or '',
        'bot_id': creds.get('bot_id', ''),
    }

    results = []
    for host_key, template in _DIAG_PATHS:
        try:
            path = template.format(**substitutions)
        except KeyError as exc:
            results.append({'path': template, 'skipped': f'missing {exc}'})
            continue
        if '{' in path or path.endswith('/'):
            results.append({'path': template, 'skipped': 'unresolved substitution'})
            continue

        url = f'{_DIAG_HOSTS[host_key]}{path}'
        entry = {'host': host_key, 'path': path}
        try:
            req = urllib.request.Request(url, headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            }, method='GET')
            with urllib.request.urlopen(req, timeout=12) as resp:
                entry['status'] = resp.status
                raw = resp.read().decode('utf-8', 'replace')
                entry['bytes'] = len(raw)
                try:
                    entry['shape'] = _diag_shape(json.loads(raw))
                except (ValueError, json.JSONDecodeError):
                    entry['shape'] = f'<non-json {raw[:80]}>'
        except urllib.error.HTTPError as e:
            entry['status'] = e.code
            detail = e.read().decode('utf-8', 'replace')[:200] if e.fp else ''
            entry['error'] = detail
        except Exception as e:  # noqa: BLE001
            entry['status'] = None
            entry['error'] = f'{type(e).__name__}: {str(e)[:120]}'
        results.append(entry)

    logger.info(json.dumps({
        'event': 'rcs_diagnostics',
        'probed': len(results),
        'answered': sum(1 for r in results if r.get('status') == 200),
        'requestId': request_id,
    }))

    return cors_response(200, {
        'platform': 'sinch-india (ex-ACL)',
        'authHost': RCS_AUTH_URL.split('/realms')[0],
        'convapiHost': _DIAG_HOSTS['convapi'],
        'accessApiHost': _DIAG_HOSTS['accessapi'],
        'identifiersConfigured': {
            'project_id': bool(RCS_PROJECT_ID),
            'app_id': bool(RCS_APP_ID),
            'username': bool(substitutions['username']),
            'bot_id': bool(substitutions['bot_id']),
        },
        'probes': results,
    }, origin)


def _send_rcs(body: Dict, request_id: str, origin: str) -> Dict:
    """Send RCS message via Sinch Conversation API."""
    phone = body.get('phoneNumber', body.get('to', ''))
    template_id = body.get('templateId', body.get('template', 'rcsmenu'))
    parameters = body.get('parameters', {})
    text = body.get('text', '')  # For direct text messages (no template)
    language = body.get('language', 'en')
    metadata = body.get('metadata', '')

    if not phone:
        return cors_response(400, {'error': 'phoneNumber is required'}, origin)

    # Identity must be digits WITHOUT a + prefix per the Sinch Conversation API.
    #
    # This used to be `if not clean.startswith('91'): clean = '91' + clean[-10:]`, which
    # fabricates an Indian number out of a foreign one. Several countries are exactly 10
    # digits in full E.164 - +6581234567 (Singapore), +85212345678 (Hong Kong),
    # +4512345678 (Denmark) - so that rule turned a Singapore number into
    # +916581234567: a different, real Indian subscriber. That is misdelivery, not
    # misrouting, and `lambda_utils.comms.numbers` exists because it has happened here
    # before; its docstring records the incident.
    #
    # `to_e164` honours an explicit country code and only assumes India for a bare
    # 10-digit number. Sinch India RCS can only reach Indian recipients anyway, so a
    # non-India destination is refused explicitly rather than silently rewritten.
    from lambda_utils.comms import numbers as _numbers

    e164 = _numbers.to_e164(phone)
    if not e164:
        return cors_response(400, {'error': 'phoneNumber is not a usable number'}, origin)
    if not _numbers.is_india(e164):
        logger.warning(json.dumps({
            'event': 'rcs_send_refused_non_india',
            'phone': _numbers.last4(e164),
            'reason': 'Sinch India RCS serves Indian destinations only; refusing rather '
                      'than rewriting the number',
            'requestId': request_id,
        }))
        return cors_response(400, {
            'error': 'RCS is available for Indian destinations only',
            'success': False,
        }, origin)
    clean = e164.lstrip('+')
    identity = clean

    # Get auth token
    token = _get_token()
    if not token:
        return cors_response(500, {'error': 'Failed to authenticate with Sinch RCS'}, origin)

    # Build message payload
    send_url = f"{RCS_API_BASE}/{RCS_PROJECT_ID}/messages:send"

    if text:
        # Direct text message (no template)
        payload = {
            "app_id": RCS_APP_ID,
            "recipient": {
                "identified_by": {
                    "channel_identities": [
                        {"channel": "RCS", "identity": identity}
                    ]
                }
            },
            "message": {
                "text_message": {
                    "text": text
                }
            }
        }

        # If choices provided, use choice_message (text with buttons)
        choices = body.get('choices', [])
        if choices:
            payload["message"] = {
                "choice_message": {
                    "text_message": {"text": text},
                    "choices": choices
                }
            }

    elif body.get('card'):
        # Rich card message
        payload = {
            "app_id": RCS_APP_ID,
            "recipient": {
                "identified_by": {
                    "channel_identities": [
                        {"channel": "RCS", "identity": identity}
                    ]
                }
            },
            "message": {
                "card_message": body.get('card')
            }
        }

    elif body.get('carousel'):
        # Carousel message
        payload = {
            "app_id": RCS_APP_ID,
            "recipient": {
                "identified_by": {
                    "channel_identities": [
                        {"channel": "RCS", "identity": identity}
                    ]
                }
            },
            "message": {
                "carousel_message": body.get('carousel')
            }
        }

    else:
        # Template message
        payload = {
            "app_id": RCS_APP_ID,
            "recipient": {
                "identified_by": {
                    "channel_identities": [
                        {"channel": "RCS", "identity": identity}
                    ]
                }
            },
            "message": {
                "template_message": {
                    "channel_template": {
                        "RCS": {
                            "template_id": template_id,
                            "language_code": language,
                            "parameters": parameters
                        }
                    }
                }
            }
        }

    # RCS is the only channel this function asks Sinch for: the payload carries no
    # `channel_priority_order`, so Sinch can never deliver it as SMS. SMS goes only
    # through AWS End User Messaging (lambda_utils.comms). A `fallback` flag from an
    # older caller is therefore not honoured here; it is logged so it is visible.
    if body.get('fallback'):
        logger.warning(json.dumps({
            'event': 'rcs_send_fallback_ignored',
            'detail': 'RCS only; send SMS through the AWS SMS service instead',
            'requestId': request_id,
        }))

    if metadata:
        payload["message_metadata"] = metadata[:1024]

    logger.info(json.dumps({
        'event': 'rcs_send_request',
        'phone': clean[-4:],
        'template': template_id if not text else '(text)',
        'requestId': request_id,
    }))

    # Send
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(send_url, data=data, headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }, method='POST')

        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode()
            result = json.loads(resp_body)

            message_id = result.get('message_id', str(uuid.uuid4()))
            logger.info(json.dumps({
                'event': 'rcs_send_success',
                'messageId': message_id,
                'phone': clean[-4:],
                'requestId': request_id,
            }))

            # Persist message to RCS table
            _store_rcs_message(message_id, clean, text or f'[template:{template_id}]', 'sent', template_id, metadata)

            return cors_response(200, {
                'success': True,
                'messageId': message_id,
                'channel': 'RCS',
                'provider': 'sinch-rcs',
                'status': 'sent',
            }, origin)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300] if e.fp else ''
        logger.error(f"RCS send error: HTTP {e.code} - {error_body}")
        return cors_response(e.code, {
            'error': f'RCS API error: {error_body[:200]}',
            'success': False,
        }, origin)
    except Exception as e:
        logger.error(f"RCS send error: {e}")
        return cors_response(500, {'error': str(e), 'success': False}, origin)


def _get_token() -> str:
    """Get valid RCS auth token (cached, auto-refresh)."""
    now = int(time.time())

    # Return cached token if still valid (with 30s buffer)
    if _token_cache['token'] and _token_cache['expires_at'] > now + 30:
        return _token_cache['token']

    # Try refresh token if available
    if _token_cache['refresh_token'] and _token_cache['refresh_expires_at'] > now + 30:
        token = _refresh_token()
        if token:
            return token

    # Full auth
    return _authenticate()


def _authenticate() -> str:
    """Authenticate with Sinch RCS using username/password."""
    creds = _get_secrets()
    username = creds.get('username') or ''
    password = creds.get('password', '')

    if not password:
        logger.error("RCS password not configured in secrets")
        return ''

    body = urllib.parse.urlencode({
        'grant_type': 'password',
        'client_id': 'ipmessaging-client',
        'username': username,
        'password': password,
    }).encode()

    # Try both URL variants
    urls = [
        RCS_AUTH_URL,  # Without /auth/ prefix
        "https://auth.aclwhatsapp.com/auth/realms/ipmessaging/protocol/openid-connect/token",  # With /auth/
    ]

    for url in urls:
        try:
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'cache-control': 'no-cache',
            }, method='POST')

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                token = data.get('access_token', '')
                if token:
                    now = int(time.time())
                    _token_cache['token'] = token
                    _token_cache['expires_at'] = now + data.get('expires_in', 300)
                    _token_cache['refresh_token'] = data.get('refresh_token', '')
                    _token_cache['refresh_expires_at'] = now + data.get('refresh_expires_in', 1800)
                    logger.info(f"RCS auth success, expires_in={data.get('expires_in')}s")
                    return token
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:100] if e.fp else ''
            logger.warning(f"RCS auth failed ({url}): HTTP {e.code} - {err}")
        except Exception as e:
            logger.warning(f"RCS auth error ({url}): {e}")

    return ''


def _refresh_token() -> str:
    """Refresh the RCS auth token."""
    body = urllib.parse.urlencode({
        'grant_type': 'refresh_token',
        'client_id': 'ipmessaging-client',
        'refresh_token': _token_cache['refresh_token'],
    }).encode()

    try:
        req = urllib.request.Request(RCS_AUTH_URL, data=body, headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'cache-control': 'no-cache',
        }, method='POST')

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            token = data.get('access_token', '')
            if token:
                now = int(time.time())
                _token_cache['token'] = token
                _token_cache['expires_at'] = now + data.get('expires_in', 300)
                _token_cache['refresh_token'] = data.get('refresh_token', '')
                _token_cache['refresh_expires_at'] = now + data.get('refresh_expires_in', 1800)
                return token
    except Exception as e:
        logger.warning(f"RCS token refresh failed: {e}")

    return ''


def _list_messages(body: Dict, request_id: str, origin: str) -> Dict:
    """List RCS messages from the canonical MessagesTable (channel=rcs).
    Reads via channel-index (bounded Query). Response shape preserved for the inbox."""
    from decimal import Decimal
    phone_filter = body.get('phoneNumber', '')
    limit = min(body.get('limit', 200), 1000)

    try:
        table = dynamodb.Table(UNIFIED_TABLE)
        resp = table.query(
            IndexName='channel-index',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('channel').eq('rcs'),
            ScanIndexForward=False,  # newest first
            Limit=max(limit, 200),
        )
        items = resp.get('Items', [])

        messages = []
        for item in items:
            msg = {}
            for k, v in item.items():
                msg[k] = int(v) if isinstance(v, Decimal) else v
            # Map canonical fields back to the inbox's expected shape.
            if not msg.get('phoneNumber'):
                msg['phoneNumber'] = msg.get('receivingPhone') or msg.get('senderPhone') or ''
            messages.append(msg)

        if phone_filter:
            clean = phone_filter.replace('+', '').replace(' ', '').replace('-', '')
            messages = [m for m in messages
                        if str(m.get('phoneNumber', '')).replace('+', '') == clean]

        messages.sort(key=lambda m: m.get('timestamp', m.get('createdAt', 0)) or 0, reverse=True)
        messages = messages[:limit]

        return cors_response(200, {'messages': messages, 'count': len(messages)}, origin)
    except Exception as e:
        logger.error(f"List RCS messages error: {e}")
        return cors_response(200, {'messages': [], 'count': 0}, origin)


def _list_templates(body: Dict, request_id: str, origin: str) -> Dict:
    """List RCS templates via v2 API (includes status)."""
    token = _get_token()
    if not token:
        return cors_response(500, {'error': 'Auth failed'}, origin)

    creds = _get_secrets()
    username = creds.get('username') or ''

    # v2 API uses username as appId
    url = f"https://api.aclwhatsapp.com/access-api/v2/rcs/{username}/templates"

    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Normalize: ensure response is always a list
            templates = data if isinstance(data, list) else data.get('templates', [data] if data else [])
            return cors_response(200, {'templates': templates}, origin)
    except Exception as e:
        return cors_response(500, {'error': str(e)}, origin)


def _create_template(body: Dict, request_id: str, origin: str) -> Dict:
    """Create a new RCS template via v2 API."""
    token = _get_token()
    if not token:
        return cors_response(500, {'error': 'Auth failed'}, origin)

    name = body.get('name', '')
    text = body.get('text', '')
    template_type = body.get('type', 'text_message')

    if not name or not text:
        return cors_response(400, {'error': 'name and text are required'}, origin)

    creds = _get_secrets()
    username = creds.get('username') or ''

    # v2 API uses username as appId
    url = f"https://api.aclwhatsapp.com/access-api/v2/rcs/{username}/templates"

    # Build v2 payload format
    if template_type == 'text_message':
        payload_data = {
            "name": name,
            "type": "text_message",
            "component": {
                "text": text
            }
        }
    elif template_type == 'rich_card':
        # text field should be JSON with title, description, media
        try:
            card_data = json.loads(text) if text.startswith('{') else {"title": name, "description": text}
        except:
            card_data = {"title": name, "description": text}
        payload_data = {
            "name": name,
            "type": "rich_card",
            "component": card_data if 'richCard' in card_data else {
                "richCard": {
                    "standaloneCard": {
                        "cardOrientation": "VERTICAL",
                        "thumbnailImageAlignment": "LEFT",
                        "cardContent": {
                            "title": card_data.get('title', name),
                            "description": card_data.get('description', text),
                        }
                    }
                }
            }
        }
    else:
        payload_data = {
            "name": name,
            "type": template_type,
            "component": {"text": text}
        }

    payload = json.dumps(payload_data).encode()

    try:
        req = urllib.request.Request(url, data=payload, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return cors_response(200, {'success': True, 'template': data}, origin)
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:200] if e.fp else ''
        return cors_response(e.code, {'error': err}, origin)
    except Exception as e:
        return cors_response(500, {'error': str(e)}, origin)


def _delete_template(body: Dict, request_id: str, origin: str) -> Dict:
    """Delete an RCS template."""
    token = _get_token()
    if not token:
        return cors_response(500, {'error': 'Auth failed'}, origin)

    name = body.get('name', '')
    if not name:
        return cors_response(400, {'error': 'Template name is required'}, origin)

    # Secrets Manager only, with no literal fallbacks. `username` is half of the
    # password-grant credential pair, so a default put it in source control; and a default
    # `bot_id` silently addresses whichever bot that literal names, which after a bot change
    # would query the wrong agent and report its templates as ours.
    creds = _get_secrets()
    bot_id = str(creds.get('bot_id') or '').strip()
    username = str(creds.get('username') or '').strip()
    if not username:
        logger.error(json.dumps({
            'event': 'rcs_template_lookup_no_credentials',
            'secretId': RCS_SECRET_NAME,
            'missingFields': [f for f in ('username', 'bot_id')
                              if not str(creds.get(f) or '').strip()],
            'requestId': request_id,
        }))
        return cors_response(500, {
            'error': 'RCS credentials unavailable',
            'detail': f'{RCS_SECRET_NAME} is missing username',
        }, origin)

    # Try multiple endpoint formats (v2 with username, v1 with botId). The v1 forms are
    # skipped when bot_id is absent rather than sent with an empty path segment, which would
    # hit a different resource entirely.
    #
    # Each candidate carries a LITERAL label, and the log lines below print the label instead
    # of the URL. That is a security fix, not cosmetics:
    #
    #     https://api.aclwhatsapp.com/access-api/v2/rcs/{username}/templates/{name}
    #
    # embeds `username`, a field of the `wecare/sinch/rcs` secret, so logging the URL writes a
    # credential component to CloudWatch. `bot_id` in the v1 forms comes from the same secret.
    # `.kiro/steering/secret-handling.md` forbids a secret appearing in a logging expression at
    # all, and is explicit that routing the value through a redaction helper does not fix it -
    # CodeQL tracks taint across function boundaries, and a reviewer cannot verify the
    # laundering at a glance either. So the label is a constant chosen right here and has never
    # touched the secret. With `name` - a caller-supplied template name - it still says
    # everything a reader needs: which API variant was tried, and for which template.
    candidates = [('v2/username', f"https://api.aclwhatsapp.com/access-api/v2/rcs/{username}/templates/{name}")]
    if bot_id:
        candidates += [
            ('v1/botId/path', f"https://api.aclwhatsapp.com/access-api/v1/rcs/{bot_id}/templates/{name}"),
            ('v1/botId/query', f"https://api.aclwhatsapp.com/access-api/v1/rcs/{bot_id}/templates?name={name}"),
        ]

    for variant, url in candidates:
        try:
            req = urllib.request.Request(url, headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }, method='DELETE')
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_body = resp.read().decode()
                try:
                    data = json.loads(resp_body)
                except:
                    data = {'raw': resp_body[:200]}
                logger.info(f"Template deleted: {name} via {variant}")
                return cors_response(200, {'success': True, 'deleted': name, 'response': data}, origin)
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:200] if e.fp else ''
            if e.code == 404:
                continue  # Try next URL format
            logger.warning(f"Delete template error: HTTP {e.code} - {err} (variant: {variant})")
            return cors_response(e.code, {'error': err, 'name': name}, origin)
        except Exception as e:
            logger.warning(f"Delete template error: {type(e).__name__} (variant: {variant})")
            continue

    # All URLs failed with 404
    return cors_response(404, {
        'error': 'Template deletion not supported by Sinch API or template not found',
        'name': name,
        'note': 'Sinch RCS API may not support template deletion. Contact Sinch support.',
    }, origin)


# ── RCS Message Persistence ──
MESSAGE_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


def _store_rcs_message(message_id: str, phone: str, content: str, status: str,
                       template_id: str = '', metadata: str = ''):
    """Persist RCS message to the canonical MessagesTable (channel='rcs').

    That table is the only RCS store: the RCS list and the DLR handler both read it.
    """
    now = int(time.time())
    contact_id = _lookup_contact_by_phone(phone)

    # Canonical write (single source of truth for the unified inbox).
    put_message(
        channel='rcs',
        direction='outbound',
        contact_id=contact_id or '',
        content=content[:2000],
        status=status,
        message_id=message_id,
        message_type='text',
        receiving_phone=phone,
        timestamp=now,
    )


def _lookup_contact_by_phone(phone: str) -> str:
    """The contact's canonical id for this phone number, or `''` if there is none.

    Resolution goes through `contact_key`, which prefers `id` - the table's actual
    partition key - over the `contactId` alias. This used to read
    ``items[0].get('contactId', '')`` directly, which had two failure modes: a row
    carrying only `id` yielded `''` and silently detached the message from its contact,
    and a row whose alias had drifted yielded a value that resolves to nothing.
    """
    if not phone:
        return ''
    # Normalize: try with and without 91 prefix
    clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    variants = [clean]
    if clean.startswith('91') and len(clean) == 12:
        variants.append(clean[2:])  # 10-digit
        variants.append(f'+{clean}')  # +91...
    elif len(clean) == 10:
        variants.append(f'91{clean}')  # 91...
        variants.append(f'+91{clean}')  # +91...

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
                    # Surfaced rather than swallowed: a diverged row means some writer has
                    # broken the invariant, and staying quiet here is what would let a
                    # wrong contact id spread into MessagesTable. `resolve` still returns
                    # the usable key, so the send itself is not blocked.
                    logger.warning(json.dumps({
                        'event': 'contact_key_mismatch',
                        'source': 'rcs-send._lookup_contact_by_phone',
                        'reason': str(exc),
                    }))
                return contact_key.resolve(item)
    except Exception as e:
        logger.debug(f"Contact lookup by phone failed: {e}")
    return ''


def _get_secrets() -> dict:
    """Load RCS secrets from Secrets Manager (cached)."""
    global _secrets_cache
    if _secrets_cache:
        return _secrets_cache
    try:
        resp = secrets_client.get_secret_value(SecretId=RCS_SECRET_NAME)
        _secrets_cache = json.loads(resp['SecretString'])
        return _secrets_cache
    except Exception as e:
        logger.error(f"Failed to load RCS secrets: {e}")
        return {}
