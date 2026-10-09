"""
WhatsApp Business API Lambda
Handles: Business Profile, Flows, Webhooks, Groups, Payment Config
Uses Meta Graph API directly

Routes:
  GET/POST  /wa-business/profile       → Business profile (read/update)
  GET       /wa-business/flows         → List flows
  POST      /wa-business/flows         → Create flow
  GET       /wa-business/flows?flowId= → Get flow details
  PUT       /wa-business/flows         → Update flow
  DELETE    /wa-business/flows         → Delete flow
  POST      /wa-business/flows/publish → Publish flow
  POST      /wa-business/flows/deprecate → Deprecate flow
  POST      /wa-business/flows/preview → Get flow preview URL
  GET       /wa-business/template-ttl/rules    → TTL rules per category
  POST      /wa-business/template-ttl/validate → Validate category/TTL pair
  POST      /wa-business/templates/{id}/ttl    → Update a template's TTL
  POST      /wa-business/media                 → Upload media (returns mediaId)
  GET       /wa-business/media/{mediaId}       → Media info (masked URL + expiry)
  DELETE    /wa-business/media/{mediaId}       → Delete media
  POST      /wa-business/media/resumable/session            → Start resumable upload
  POST      /wa-business/media/resumable/{sessionId}/chunk  → Append chunk
  POST      /wa-business/media/resumable/{sessionId}/finish → Assemble + upload (handle/media)
  POST      /wa-business/messages/send/text|template|media|flow → Send test messages
  POST      /wa-business/messages/send/interactive → REMOVED 2026-10-02, answers 410
  GET       /wa-business/webhooks      → Get webhook subscriptions
  POST      /wa-business/webhooks      → Subscribe to webhook fields
  DELETE    /wa-business/webhooks      → Unsubscribe webhook fields
  GET       /wa-business/groups        → List groups
  POST      /wa-business/groups        → Create group
  GET       /wa-business/groups?groupId= → Get group details
  PUT       /wa-business/groups        → Update group
  DELETE    /wa-business/groups        → Delete group
  POST      /wa-business/groups/participants → Remove participants
  POST      /wa-business/groups/send   → Send group message
  GET       /wa-business/groups/invite-link → Get invite link
  POST      /wa-business/groups/invite-link → Reset invite link
  GET       /wa-business/groups/join-requests → List pending join requests
  POST      /wa-business/groups/join-requests → Approve join requests
  DELETE    /wa-business/groups/join-requests → Reject join requests
  GET       /wa-business/payment-config → Get payment configuration for phone
  GET       /wa-business/payment-config/check → Check payment gateway status via Meta API
  GET       /wa-business/payment-lookup → Meta Payment Lookup API (verify payment status)
  POST      /wa-business/payment-refund → Meta Refund API (initiate refund via WhatsApp)
  POST      /wa-business/flow-data     → WhatsApp Flow data_exchange endpoint
  POST      /wa-business/checkout-data → Checkout Button Template data_exchange (coupons + address)
"""
import os
import json
import logging
import base64
import hmac
import hashlib
import time
import uuid
import boto3
from boto3.dynamodb.conditions import Attr
import urllib.request
import urllib.parse
import urllib.error
from decimal import Decimal
from typing import Dict, Any, Optional

from lambda_utils.meta_client import MetaGraphClient  # shared Meta Graph client (Part 2 pilot)

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
# Aliased to leave the many local `payment_status` / `ps` variables alone; this is the module that
# says `paid` and `captured` are one state.
from lambda_utils import payment_status as pay_status
from lambda_utils.middleware import require_auth
from lambda_utils import meta_signature  # X-Hub-Signature-256, fails closed
from lambda_utils.privacy import mask_flow_token  # a Flow token ends in the customer's number
from lambda_utils.privacy import mask_phone  # never log a recipient in cleartext
from lambda_utils import live_smoke  # WA_LIVE_SMOKE_TEST recipient lockdown
# Direct Send facts (flag, WABA map, ttl_seconds bounds, error classification) live in one
# shared module so this admin surface and the production sender cannot disagree. Module-scope
# import is correct: it reads no secret and touches no AWS resource, so the lazy-secret rule
# in lambda-snapstart-deploy does not apply.
from lambda_utils import direct_send as direct_send_util

logger = get_logger(__name__)

secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
META_TOKEN_SECRET = os.environ.get('META_TOKEN_SECRET', 'wecare/meta-system-user-token')
GRAPH_BASE = f'https://graph.facebook.com/{META_API_VERSION}'

# CORS headers provided by lambda_utils.response.cors_headers(origin)

_token_cache = {}

WABA1_ID = os.environ.get('WABA1_ID', '2094615664435155')  # WECARE.DIGITAL (Direct API)
WABA2_ID = os.environ.get('WABA2_ID', '2513394156072604')  # Manish Agarwal (Direct API)
PHONE1_META_ID = os.environ.get('PHONE1_META_ID', '1016149501586345')  # +919330994400 (Direct API)
PHONE2_META_ID = os.environ.get('PHONE2_META_ID', '1055232054343117')  # +919903300044 (Direct API)

# All IDs that belong to WABA2 — now uses WECARE.DIGITAL app (token1), no separate token needed
WABA2_IDS = set()

# DynamoDB tables for order lookups (flow-data endpoint)
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
ORDER_IDS_TABLE = os.environ.get('WIX_ORDER_IDS_TABLE', 'stack-wecare-digital-WixOrderIds')

# Lambda client for invoking outbound WhatsApp (payment after flow)
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
OUTBOUND_WHATSAPP_FUNCTION = os.environ.get('OUTBOUND_WHATSAPP_FUNCTION', 'wecare-outbound-whatsapp')

# Media handling (Part 4 D)
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
MEDIA_RESUMABLE_PREFIX = os.environ.get(
    'MEDIA_RESUMABLE_PREFIX', media_paths.public('stack/whatsapp-media/resumable/'))
MEDIA_DOWNLOAD_PREFIX = os.environ.get(
    'MEDIA_DOWNLOAD_PREFIX', media_paths.public('stack/whatsapp-media/downloads/'))
META_APP_ID = os.environ.get('META_APP_ID', '2238810740192680')
# Meta media URLs are short-lived; treat as ~5 min for expiry tracking.
MEDIA_URL_TTL_SECONDS = int(os.environ.get('MEDIA_URL_TTL_SECONDS', '300'))
# MIME → category for size limits (per WhatsApp Cloud API)
MEDIA_SIZE_LIMITS = {
    'image': 5 * 1024 * 1024,
    'video': 16 * 1024 * 1024,
    'audio': 16 * 1024 * 1024,
    'document': 100 * 1024 * 1024,
    'sticker': 500 * 1024,
}
MEDIA_ALLOWED_MIME = {
    'image/jpeg', 'image/png', 'image/webp',
    'video/mp4', 'video/3gpp',
    'audio/aac', 'audio/amr', 'audio/mpeg', 'audio/mp4', 'audio/ogg',
    'application/pdf', 'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain',
}
INVOICE_ENGINE_FUNCTION = os.environ.get('INVOICE_ENGINE_FUNCTION', 'wecare-invoice-engine')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
SUBMIT_REQUESTS_TABLE = os.environ.get('SUBMIT_REQUESTS_TABLE', 'stack-wecare-digital-SubmitRequestsTable')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
CATALOG_FLOW_MAP_ID = 'catalog_flow_map'  # SystemConfigTable key for product→flow mapping
AI_ROUTING_ID = 'ai_hybrid_routing'  # SystemConfigTable key for AI-vs-bot routing rules
DEFAULT_AI_ROUTING = {
    'enabled': True,
    'keywords': ['hi', 'hello', 'hey', 'menu', 'main menu', 'show menu', 'browse menu',
                 '/menu', 'start', 'get started', 'need help!', 'subscribe', 'help',
                 # Our own QR / widget prefills. Must stay in step with
                 # inbound-whatsapp-handler's _DETERMINISTIC_KEYWORDS, or a dashboard
                 # save of this config would silently drop them again.
                 'get help', 'hi 👋'],
    'contains': ['get started', 'main menu', 'subscribe', 'track request', 'track',
                 'submit request', 'amend request', 'appointment', 'rx slot', 'drop docs',
                 'enterprise', 'leave review', 'catalog', 'catalogue', 'pay', 'payment',
                 'invoice', 'faq'],
    'types': ['button', 'interactive', 'order'],
    'commandPrefix': '/',
}

# Flow management tables
FLOW_REGISTRY_TABLE = os.environ.get('FLOW_REGISTRY_TABLE', 'stack-wecare-digital-FlowRegistryTable')
FLOW_SUBMISSIONS_TABLE = os.environ.get('FLOW_SUBMISSIONS_TABLE', 'stack-wecare-digital-FlowSubmissionTable')
FLOW_LOGS_TABLE = os.environ.get('FLOW_LOGS_TABLE', 'stack-wecare-digital-FlowLogTable')

# Flow registry cache (in-memory, refreshed every 5 min)
_flow_registry_cache: Dict = {}
_flow_registry_cache_ts: float = 0
FLOW_REGISTRY_CACHE_TTL = 300  # 5 minutes

# Phone number IDs (for outbound Lambda)
PHONE1_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE2_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')


def _get_meta_token(waba_id: str = None, phone_id: str = None) -> str:
    """Get the correct token based on WABA or phone ID."""
    use_waba2 = (waba_id in WABA2_IDS) or (phone_id in WABA2_IDS)
    
    cache_key = 'token2' if use_waba2 else 'token1'
    if cache_key in _token_cache:
        return _token_cache[cache_key]
    
    # Load both tokens from secret
    if 'loaded' not in _token_cache:
        resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
        raw = resp['SecretString']
        try:
            secret = json.loads(raw)
            _token_cache['token1'] = (secret.get('access_token') or '').strip()
            _token_cache['token2'] = (secret.get('access_token_waba2') or secret.get('access_token') or '').strip()
            _token_cache['app_secret'] = (secret.get('app_secret') or '').strip()
            _token_cache['app_secret_waba2'] = (secret.get('app_secret_waba2') or secret.get('app_secret') or '').strip()
        except json.JSONDecodeError:
            import re
            m = re.search(r'access_token\s*:\s*([^,}]+)', raw)
            token = m.group(1).strip() if m else raw.strip()
            _token_cache['token1'] = token
            _token_cache['token2'] = token
        _token_cache['loaded'] = True
    
    return _token_cache.get(cache_key, _token_cache.get('token1', ''))


def _get_app_secret(waba_id: str = None, phone_id: str = None) -> str:
    """Get the correct app secret based on WABA or phone ID."""
    use_waba2 = (waba_id in WABA2_IDS) or (phone_id in WABA2_IDS)
    cache_key = 'app_secret_waba2' if use_waba2 else 'app_secret'
    if cache_key in _token_cache:
        return _token_cache[cache_key]
    # Secrets are loaded in _get_meta_token — ensure loaded
    _get_meta_token(waba_id=waba_id, phone_id=phone_id)
    return _token_cache.get(cache_key, '')


def _graph_api(endpoint: str, method: str = 'GET', payload: Dict = None, params: Dict = None, waba_id: str = None, phone_id: str = None) -> Dict:
    token = _get_meta_token(waba_id=waba_id, phone_id=phone_id)
    app_secret = _get_app_secret(waba_id=waba_id, phone_id=phone_id)
    url = f'{GRAPH_BASE}/{endpoint}'
    # Compute appsecret_proof
    proof_params = {}
    if app_secret:
        proof = hmac.new(app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256).hexdigest()
        proof_params['appsecret_proof'] = proof
    if params:
        qs = {k: v for k, v in params.items() if v is not None}
        qs.update(proof_params)
        if qs:
            url += '?' + urllib.parse.urlencode(qs)
    elif proof_params:
        url += '?' + urllib.parse.urlencode(proof_params)
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    data = json.dumps(payload).encode('utf-8') if payload else None
    if method == 'GET':
        req = urllib.request.Request(url, headers=headers, method='GET')
    elif method == 'DELETE':
        # Several Meta DELETE edges require a JSON body: /{phone-number-id}/block_users
        # (unblock), /{waba-id}/assigned_users (unassign) and /{group-id}/join_requests
        # (reject). This branch previously never sent one, so those payloads were
        # silently dropped and the calls could not do what they claimed.
        # `data` is None when no payload was supplied, so payload-less DELETE callers
        # are unaffected.
        req = urllib.request.Request(url, data=data, headers=headers, method='DELETE')
    else:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.error(f'Graph API error {e.code}: {error_body}')
        try:
            return {'error': json.loads(error_body)}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {'error': {'message': error_body, 'code': e.code}}

def _resp(code: int, body: Dict, resp_origin: str = '') -> Dict:
    return {'statusCode': code, 'headers': cors_headers(resp_origin or origin), 'body': json.dumps(body, default=str)}


def _emit_event(event_type: str, severity: str = 'info', waba_id: str = None,
                phone_id: str = None, data: Dict = None) -> None:
    """Fail-open wrapper around the shared SystemEvent recorder."""
    try:
        from lambda_utils.system_events import record_system_event
        record_system_event(event_type, waba_id=waba_id, phone_number_id=phone_id,
                            severity=severity, data=data or {})
    except Exception as e:  # never let telemetry break a request
        logger.warning(f'system_event emit failed ({event_type}): {e}')

# ============================================================================
# BUSINESS PROFILE
# ============================================================================
def _get_business_profile(phone_id: str) -> Dict:
    fields = 'about,address,description,email,profile_picture_url,websites,vertical'
    result = _graph_api(f'{phone_id}/whatsapp_business_profile', params={'fields': fields}, phone_id=phone_id)
    if 'error' in result:
        # Retry once — Meta Graph API can be flaky
        logger.warning(f'Profile fetch failed for {phone_id}, retrying: {result}')
        time.sleep(1)
        result = _graph_api(f'{phone_id}/whatsapp_business_profile', params={'fields': fields}, phone_id=phone_id)
        if 'error' in result:
            logger.error(f'Profile fetch failed after retry for {phone_id}: {result}')
            # Return 200 with error info so frontend can display the error message
            error_msg = result.get('error', {})
            if isinstance(error_msg, dict):
                error_msg = error_msg.get('message', str(error_msg))
            return _resp(200, {'profile': None, 'error': str(error_msg), 'phoneId': phone_id})
    data = result.get('data', [{}])
    profile = data[0] if data else {}
    return _resp(200, {'profile': profile})

def _update_business_profile(phone_id: str, body: Dict) -> Dict:
    allowed = ['about', 'address', 'description', 'email', 'websites', 'vertical', 'profile_picture_url']
    payload = {k: v for k, v in body.items() if k in allowed and v is not None and v != ''}
    if not payload:
        return _resp(400, {'error': 'No valid fields to update'})
    payload['messaging_product'] = 'whatsapp'
    result = _graph_api(f'{phone_id}/whatsapp_business_profile', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'updated': list(payload.keys())})

# ============================================================================
# FLOWS
# ============================================================================
def _list_flows(waba_id: str) -> Dict:
    if not waba_id:
        return _resp(400, {'error': 'wabaId required'})
    rows, after, seen = [], None, set()
    while True:
        params = {'fields': 'id,name,status,categories,validation_errors', 'limit': 100}
        if after:
            params['after'] = after
        result = _graph_api(f'{waba_id}/flows', params=params, waba_id=waba_id)
        if 'error' in result:
            return _resp(400, result)
        rows.extend(result.get('data') or [])
        paging = result.get('paging') or {}
        if not paging.get('next'):
            return _resp(200, {'flows': rows})
        after = (paging.get('cursors') or {}).get('after')
        if not after or after in seen or len(rows) >= 1000:
            return _resp(502, {'error': 'Incomplete Flow inventory'})
        seen.add(after)


def _get_flow(flow_id: str) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    result = _graph_api(flow_id, params={'fields': 'id,name,status,categories,validation_errors,json_version,data_api_version,endpoint_uri,preview,application'})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'flow': result})

def _create_flow(waba_id: str, body: Dict) -> Dict:
    name = body.get('name')
    if not name:
        return _resp(400, {'error': 'name required'})
    payload = {'name': name}
    if body.get('categories'):
        payload['categories'] = body['categories']
    if body.get('clone_flow_id'):
        payload['clone_flow_id'] = body['clone_flow_id']
    result = _graph_api(f'{waba_id}/flows', method='POST', payload=payload, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'flow': result})

def _update_flow(flow_id: str, body: Dict) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    payload = {}
    if body.get('application_id'):
        application_id = str(body['application_id'])
        if application_id != str(META_APP_ID):
            return _resp(400, {'error': 'Flow application must be the configured WECARE Meta app'})
        payload['application_id'] = application_id
    if body.get('name'):
        payload['name'] = body['name']
    if body.get('categories'):
        payload['categories'] = body['categories']
    if body.get('endpoint_uri'):
        payload['endpoint_uri'] = body['endpoint_uri']
    if body.get('json'):
        payload['json'] = body['json']
    result = _graph_api(flow_id, method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

def _delete_flow(flow_id: str) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    result = _graph_api(flow_id, method='DELETE')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

def _publish_flow(flow_id: str) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    result = _graph_api(f'{flow_id}/publish', method='POST')
    if 'error' in result:
        _emit_event('flow_publish_failed', severity='error', data={'flowId': flow_id, 'error': result.get('error')})
        return _resp(400, result)
    _emit_event('flow_published', severity='info', data={'flowId': flow_id})
    return _resp(200, {'success': True})

def _deprecate_flow(flow_id: str, waba_id: str = None) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    result = _graph_api(f'{flow_id}/deprecate', method='POST', waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    _emit_event('flow_deprecated', severity='warning', data={'flowId': flow_id})
    return _resp(200, {'success': True})

def _get_flow_preview(flow_id: str) -> Dict:
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    result = _graph_api(flow_id, params={'fields': 'preview.invalidate(false)'})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'preview': result.get('preview', {})})


# ============================================================================
# WEBHOOKS
# ============================================================================
def _get_webhook_subscriptions(waba_id: str) -> Dict:
    result = _graph_api(f'{waba_id}/subscribed_apps', waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'subscriptions': result.get('data', [])})

def _subscribe_webhook(waba_id: str, body: Dict) -> Dict:
    payload = {}
    if body.get('override_callback_uri'):
        payload['override_callback_uri'] = body['override_callback_uri']
    if body.get('verify_token'):
        payload['verify_token'] = body['verify_token']
    if body.get('subscribed_fields'):
        fields = body['subscribed_fields']
        # Meta expects subscribed_fields as comma-separated string
        if isinstance(fields, list):
            payload['subscribed_fields'] = ','.join(fields)
        else:
            payload['subscribed_fields'] = fields
    result = _graph_api(f'{waba_id}/subscribed_apps', method='POST', payload=payload or None, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'result': result})

def _unsubscribe_webhook(waba_id: str, body: Dict) -> Dict:
    result = _graph_api(f'{waba_id}/subscribed_apps', method='DELETE', waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

# ============================================================================
# ASSIGNED USERS
# ============================================================================
def _list_assigned_users(waba_id: str, params: Dict) -> Dict:
    """GET /{WABA-ID}/assigned_users — list users assigned to WABA."""
    business_id = params.get('business')
    if not business_id:
        return _resp(400, {'error': 'business parameter required'})
    query = {'business': business_id}
    if params.get('fields'):
        query['fields'] = params['fields']
    if params.get('limit'):
        query['limit'] = params['limit']
    if params.get('after'):
        query['after'] = params['after']
    if params.get('before'):
        query['before'] = params['before']
    result = _graph_api(f'{waba_id}/assigned_users', params=query, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {
        'users': result.get('data', []),
        'paging': result.get('paging', {}),
        'summary': result.get('summary', {}),
    })

def _add_assigned_user(waba_id: str, body: Dict) -> Dict:
    """POST /{WABA-ID}/assigned_users — add user with permission tasks."""
    user_id = body.get('user')
    tasks = body.get('tasks', [])
    if not user_id:
        return _resp(400, {'error': 'user (user ID) required'})
    if not tasks:
        return _resp(400, {'error': 'tasks array required'})
    result = _graph_api(
        f'{waba_id}/assigned_users', method='POST',
        payload={'user': user_id, 'tasks': tasks}, waba_id=waba_id,
    )
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

def _remove_assigned_user(waba_id: str, body: Dict) -> Dict:
    """DELETE /{WABA-ID}/assigned_users — revoke user access."""
    user_id = body.get('user')
    if not user_id:
        return _resp(400, {'error': 'user (user ID) required'})
    result = _graph_api(
        f'{waba_id}/assigned_users', method='DELETE',
        payload={'user': user_id}, waba_id=waba_id,
    )
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

# ============================================================================
# BOT DETAILS
# ============================================================================
def _get_bot_details(bot_id: str, params: Dict) -> Dict:
    """GET /{WABA-Bot-ID} — retrieve bot prompts, commands, welcome message config.
    Pilot: uses the shared MetaGraphClient (Part 2)."""
    if not bot_id:
        return _resp(400, {'error': 'botId required'})
    fields = params.get('fields', 'id,prompts,commands,enable_welcome_message')
    result = MetaGraphClient().get(bot_id, params={'fields': fields})
    if MetaGraphClient.is_error(result):
        return _resp(400, result)
    return _resp(200, {'bot': result})


# ============================================================================
# ASSIGNED WHATSAPP BUSINESS ACCOUNTS (for a user)
# GET /{User-ID}/assigned_whatsapp_business_accounts
# ============================================================================
def _list_assigned_wabas(user_id: str, params: Dict) -> Dict:
    """List WABAs assigned to a user, with pagination."""
    if not user_id:
        return _resp(400, {'error': 'userId required'})
    query = {'fields': params.get('fields', 'id,name')}
    if params.get('limit'):
        query['limit'] = params['limit']
    if params.get('after'):
        query['after'] = params['after']
    if params.get('before'):
        query['before'] = params['before']
    result = _graph_api(f'{user_id}/assigned_whatsapp_business_accounts', params=query)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {
        'wabas': result.get('data', []),
        'paging': result.get('paging', {}),
    })


# ============================================================================
# CAMPAIGN SCHEDULES
# GET/POST /{WABA-ID}/schedules
# ============================================================================
_SCHEDULE_STATUSES = {'COMPLETED', 'FAILED', 'SCHEDULED', 'SENDING'}


def _list_schedules(waba_id: str, params: Dict) -> Dict:
    """List campaign schedules for a WABA."""
    query = {'fields': params.get('fields', 'id,name,description,delivery_time,status')}
    if params.get('limit'):
        query['limit'] = params['limit']
    if params.get('after'):
        query['after'] = params['after']
    if params.get('before'):
        query['before'] = params['before']
    result = _graph_api(f'{waba_id}/schedules', params=query, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'schedules': result.get('data', []), 'paging': result.get('paging', {})})


def _create_schedule(waba_id: str, body: Dict) -> Dict:
    """Create a campaign schedule. Requires hsm_id, audience_id, waba_cs_id, name, description, delivery_time."""
    required = ['hsm_id', 'audience_id', 'waba_cs_id', 'name', 'description', 'delivery_time']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return _resp(400, {'error': f'Missing required fields: {", ".join(missing)}'})
    try:
        delivery_time = int(body['delivery_time'])
    except (ValueError, TypeError):
        return _resp(400, {'error': 'delivery_time must be a Unix timestamp (integer)'})
    if delivery_time <= int(time.time()):
        return _resp(400, {'error': 'delivery_time must be in the future'})
    payload = {
        'hsm_id': body['hsm_id'],
        'audience_id': body['audience_id'],
        'waba_cs_id': body['waba_cs_id'],
        'name': body['name'],
        'description': body['description'],
        'delivery_time': delivery_time,
    }
    result = _graph_api(f'{waba_id}/schedules', method='POST', payload=payload, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'id': result.get('id', ''), 'result': result})


# ============================================================================
# WHATSAPP COMMERCE SETTINGS
# GET/POST /{Phone-Number-ID}/whatsapp_commerce_settings
# ============================================================================
def _get_commerce_settings(phone_id: str) -> Dict:
    """Get cart/catalog visibility settings for a phone number."""
    result = _graph_api(f'{phone_id}/whatsapp_commerce_settings', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    data = result.get('data', [])
    return _resp(200, {'commerceSettings': data[0] if data else {}, 'raw': result})


def _update_commerce_settings(phone_id: str, body: Dict) -> Dict:
    """Update cart enabled / catalog visible. Meta expects these as query params on POST."""
    query = {}
    if 'is_cart_enabled' in body:
        query['is_cart_enabled'] = 'true' if body['is_cart_enabled'] in (True, 'true', 'True', 1) else 'false'
    if 'is_catalog_visible' in body:
        query['is_catalog_visible'] = 'true' if body['is_catalog_visible'] in (True, 'true', 'True', 1) else 'false'
    if not query:
        return _resp(400, {'error': 'Provide is_cart_enabled and/or is_catalog_visible'})
    result = _graph_api(f'{phone_id}/whatsapp_commerce_settings', method='POST', params=query, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': result.get('success', True), 'result': result})


def _list_catalog_products(catalog_id: str, params: Dict) -> Dict:
    """List products in a Meta commerce catalog (for the admin product browser).
    GET /wa-business/catalog-products?catalogId=<id>&search=<q>&limit=<n>
    Returns normalized products: id, retailer_id, name, price, availability, image_url.

    `id` is the Meta product id and is required by the update and delete paths, which
    address a product as POST/DELETE /{product_id}. It used to be omitted here, so the
    admin UI had to re-resolve it through a second endpoint that is not routed at all
    (/catalog/products returns 404), which left delete permanently broken. Carrying the
    id on the list row removes that round trip.

    `description` is here for the same reason: the admin edit form loads its fields from
    this row, and without it the description input opened blank over a stored value the
    user could not see."""
    if not catalog_id:
        return _resp(400, {'error': 'catalogId is required'})
    limit = str(params.get('limit', '100'))
    fields = 'id,name,retailer_id,price,currency,availability,description,image_url,url'
    gp: Dict = {'fields': fields, 'limit': limit}
    search = params.get('search')
    if search:
        gp['filter'] = json.dumps({'name': {'i_contains': search}})
    result = _graph_api(f'{catalog_id}/products', params=gp)
    if 'error' in result:
        return _resp(400, result)
    products = []
    for it in result.get('data', []):
        products.append({
            'id': it.get('id', ''),
            'retailerId': it.get('retailer_id', ''),
            'name': it.get('name', ''),
            'price': it.get('price', ''),
            'currency': it.get('currency', 'INR'),
            'availability': it.get('availability', ''),
            'description': it.get('description', ''),
            'imageUrl': it.get('image_url', ''),
            'url': it.get('url', ''),
        })
    return _resp(200, {'products': products, 'count': len(products)})


def _create_catalog_product(body: Dict) -> Dict:
    """Create a product in a Meta commerce catalog.
    POST /wa-business/catalog-products
    Body: { catalogId, retailerId, name, price (rupees), description?, imageUrl?, url?,
            currency?, availability?, brand?, condition?, salePrice? }
    Price is accepted in RUPEES from the UI and converted to the minor unit (paise)
    that the Graph API expects. Returns the new product id and its image_fetch_status."""
    catalog_id = body.get('catalogId') or body.get('catalog_id')
    retailer_id = (body.get('retailerId') or body.get('retailer_id') or '').strip()
    name = (body.get('name') or '').strip()
    if not catalog_id or not retailer_id or not name:
        return _resp(400, {'error': 'catalogId, retailerId and name are required'})
    try:
        price_rupees = float(body.get('price', 0) or 0)
    except (TypeError, ValueError):
        return _resp(400, {'error': 'price must be a number'})
    if price_rupees <= 0:
        return _resp(400, {'error': 'price must be greater than 0'})
    currency = (body.get('currency') or 'INR').upper()
    payload = {
        'retailer_id': retailer_id,
        'name': name[:200],
        'price': int(round(price_rupees * 100)),   # rupees -> paise (minor unit)
        'currency': currency,
        'availability': (body.get('availability') or 'in stock'),
        'condition': (body.get('condition') or 'new'),
        'url': (body.get('url') or 'https://wecare.digital/'),
        'image_url': (body.get('imageUrl') or body.get('image_url')
                      or 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png'),
    }
    if body.get('description'):
        payload['description'] = str(body['description'])[:1000]
    if body.get('brand'):
        payload['brand'] = str(body['brand'])[:100]
    if body.get('salePrice'):
        try:
            payload['sale_price'] = int(round(float(body['salePrice']) * 100))
        except (TypeError, ValueError):
            pass
    result = _graph_api(f'{catalog_id}/products', method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    product_id = result.get('id', '')
    # Best-effort read-back of image fetch status so the UI can warn on FETCH_FAILED.
    fetch_status = ''
    if product_id:
        chk = _graph_api(product_id, params={'fields': 'image_fetch_status'})
        if isinstance(chk, dict) and 'error' not in chk:
            fetch_status = chk.get('image_fetch_status', '')
    return _resp(200, {'success': True, 'productId': product_id,
                       'retailerId': retailer_id, 'imageFetchStatus': fetch_status})


def _update_catalog_product(product_id: str, body: Dict) -> Dict:
    """Update fields on an existing Meta catalog product.
    PUT /wa-business/catalog-products?productId=<id>   (productId may also be in the body)
    Body: { productId, name?, price (rupees)?, currency?, availability?, description?,
            imageUrl?/image_url?, url? }

    Graph addresses a product edit as POST /{product_id} and accepts only the keys
    filtered for below; anything else is dropped rather than sent, so a stray field
    cannot fail the whole call.

    Price is accepted in RUPEES from the UI and converted with the same
    int(round(rupees * 100)) used by _create_catalog_product, so create and update share
    one unit contract. They must not diverge: the UI posts the same Number(form.price)
    to both, and a mismatch here would silently rewrite a price by a factor of 100."""
    if not product_id:
        return _resp(400, {'error': 'productId is required'})
    payload: Dict = {}
    if body.get('name'):
        payload['name'] = str(body['name']).strip()[:200]
    if body.get('price') is not None and body.get('price') != '':
        try:
            price_rupees = float(body['price'])
        except (TypeError, ValueError):
            return _resp(400, {'error': 'price must be a number'})
        if price_rupees <= 0:
            return _resp(400, {'error': 'price must be greater than 0'})
        payload['price'] = int(round(price_rupees * 100))   # rupees -> paise (minor unit)
        payload['currency'] = (body.get('currency') or 'INR').upper()
    if body.get('availability'):
        payload['availability'] = str(body['availability'])
    if body.get('description'):
        payload['description'] = str(body['description'])[:1000]
    image_url = body.get('imageUrl') or body.get('image_url')
    if image_url:
        payload['image_url'] = str(image_url)
    if body.get('url'):
        payload['url'] = str(body['url'])
    if not payload:
        return _resp(400, {'error': 'No updatable fields provided'})
    result = _graph_api(product_id, method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'productId': product_id,
                       'updated': sorted(payload.keys())})


def _delete_catalog_product(product_id: str) -> Dict:
    """Delete a product from a Meta commerce catalog by its product id.
    DELETE /wa-business/catalog-products?productId=<id>"""
    if not product_id:
        return _resp(400, {'error': 'productId is required'})
    result = _graph_api(product_id, method='DELETE')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})


def _list_catalog_feeds(catalog_id: str) -> Dict:
    """List scheduled product feeds (data sources) on a catalog.
    GET /wa-business/catalog-feed?catalogId=<id>"""
    if not catalog_id:
        return _resp(400, {'error': 'catalogId is required'})
    result = _graph_api(f'{catalog_id}/product_feeds',
                        params={'fields': 'id,name,schedule,latest_upload{end_time,error_count,warning_count,num_detected_items}'})
    if 'error' in result:
        return _resp(400, result)
    feeds = []
    for f in result.get('data', []):
        sched = f.get('schedule', {}) or {}
        up = f.get('latest_upload', {}) or {}
        feeds.append({
            'feedId': f.get('id', ''),
            'name': f.get('name', ''),
            'interval': sched.get('interval', ''),
            'url': sched.get('url', ''),
            'hour': sched.get('hour', ''),
            'lastUploadEnd': up.get('end_time', ''),
            'lastItems': up.get('num_detected_items', ''),
            'lastErrors': up.get('error_count', ''),
        })
    return _resp(200, {'feeds': feeds, 'count': len(feeds)})


def _upsert_catalog_feed(body: Dict) -> Dict:
    """Create or update a scheduled product feed (data source) on a catalog so Meta
    auto-fetches the Wix TSV on a schedule and keeps the WhatsApp catalog in sync.
    POST /wa-business/catalog-feed
    Body: { catalogId, url, name?, interval(HOURLY|DAILY|WEEKLY)?, hour?, feedId? }
    - If feedId or a feed with the same name exists -> update its schedule (url/interval).
    - Else -> create a new scheduled feed.
    The feed URL may embed a secret token; it is stored by Meta, not logged here."""
    catalog_id = body.get('catalogId') or body.get('catalog_id')
    url = (body.get('url') or '').strip()
    if not catalog_id or not url:
        return _resp(400, {'error': 'catalogId and url are required'})
    if not url.lower().startswith('https://'):
        return _resp(400, {'error': 'url must be https'})
    name = (body.get('name') or 'WECARE Scheduled Feed').strip()
    interval = (body.get('interval') or 'DAILY').upper()
    if interval not in ('HOURLY', 'DAILY', 'WEEKLY'):
        interval = 'DAILY'
    schedule = {'interval': interval, 'url': url, 'hour': str(body.get('hour', 4))}
    if body.get('intervalCount'):
        schedule['interval_count'] = str(body['intervalCount'])

    # Locate existing feed (by explicit feedId or matching name) to update in place.
    feed_id = body.get('feedId', '')
    if not feed_id:
        existing = _graph_api(f'{catalog_id}/product_feeds', params={'fields': 'id,name'})
        for f in existing.get('data', []) if isinstance(existing, dict) else []:
            if f.get('name') == name:
                feed_id = f.get('id', '')
                break

    if feed_id:
        result = _graph_api(feed_id, method='POST', payload={'schedule': schedule})
        if 'error' in result:
            return _resp(400, result)
        return _resp(200, {'success': True, 'action': 'updated', 'feedId': feed_id, 'interval': interval})

    result = _graph_api(f'{catalog_id}/product_feeds', method='POST',
                        payload={'name': name, 'schedule': schedule})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'action': 'created', 'feedId': result.get('id', ''), 'interval': interval})


def _trigger_catalog_feed_fetch(feed_id: str, url: str = '') -> Dict:
    """Force an immediate feed upload (outside the schedule). Meta's uploads edge
    requires the feed url, so we read it from the feed's schedule when not provided.
    POST /wa-business/catalog-feed/fetch  Body: { feedId, url? }"""
    if not feed_id:
        return _resp(400, {'error': 'feedId is required'})
    fetch_url = (url or '').strip()
    if not fetch_url:
        info = _graph_api(feed_id, params={'fields': 'schedule'})
        fetch_url = ((info.get('schedule') or {}).get('url') or '') if isinstance(info, dict) else ''
    if not fetch_url:
        return _resp(400, {'error': 'No feed url available; pass url or configure a scheduled feed first'})
    result = _graph_api(f'{feed_id}/uploads', method='POST', params={'url': fetch_url})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'uploadId': result.get('id', ''), 'feedId': feed_id})


# ============================================================================
# MESSAGE QR CODES
# GET/DELETE /{Phone-Number-ID}/message_qrdls/{QR-Code-ID}
# ============================================================================
def _is_valid_qr_id(qr_id: str) -> bool:
    """QR code IDs are 14-character alphanumeric strings."""
    return bool(qr_id) and len(qr_id) == 14 and qr_id.isalnum()


def _get_qr_code(phone_id: str, qr_id: str, params: Dict) -> Dict:
    """Retrieve a single QR code (or list all when qr_id omitted)."""
    if qr_id and not _is_valid_qr_id(qr_id):
        return _resp(400, {'error': 'Invalid QR code ID format. Expected 14-character alphanumeric string'})
    fields = params.get('fields', 'code,prefilled_message,deep_link_url,qr_image_url.format(PNG)')
    endpoint = f'{phone_id}/message_qrdls/{qr_id}' if qr_id else f'{phone_id}/message_qrdls'
    result = _graph_api(endpoint, params={'fields': fields}, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'qrCodes': result.get('data', []), 'raw': result})


def _delete_qr_code(phone_id: str, qr_id: str) -> Dict:
    """Permanently delete a QR code."""
    if not _is_valid_qr_id(qr_id):
        return _resp(400, {'error': 'Invalid QR code ID format. Expected 14-character alphanumeric string'})
    result = _graph_api(f'{phone_id}/message_qrdls/{qr_id}', method='DELETE', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': result.get('success', True)})


def _create_qr_code(phone_id: str, body: Dict) -> Dict:
    """Create a QR code / deep link. Body: { prefilled_message, generate_qr_image: SVG|PNG }."""
    prefilled = (body.get('prefilled_message') or '').strip()
    if not prefilled:
        return _resp(400, {'error': 'prefilled_message is required'})
    payload = {
        'prefilled_message': prefilled,
        'generate_qr_image': (body.get('generate_qr_image') or 'PNG').upper(),
    }
    result = _graph_api(f'{phone_id}/message_qrdls', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'qrCode': result})


# ============================================================================
# CONVERSATIONAL AUTOMATION (welcome message, ice-breaker prompts, bot commands)
# POST /{Phone-Number-ID}/conversational_automation
# ============================================================================
# WhatsApp limits (documented): up to 4 ice-breaker prompts, up to 30 commands.
_MAX_PROMPTS = 4
_MAX_COMMANDS = 30


def _configure_conversational_automation(phone_id: str, body: Dict) -> Dict:
    """Configure welcome message, ice-breaker prompts and bot commands with validation."""
    prompts = body.get('prompts', [])
    commands = body.get('commands', [])
    enable_welcome = body.get('enable_welcome_message')

    if not isinstance(prompts, list) or not isinstance(commands, list):
        return _resp(400, {'error': 'prompts and commands must be arrays'})
    if len(prompts) > _MAX_PROMPTS:
        return _resp(400, {'error': f'Maximum {_MAX_PROMPTS} prompts (ice breakers) allowed'})
    if len(commands) > _MAX_COMMANDS:
        return _resp(400, {'error': f'Maximum {_MAX_COMMANDS} commands allowed'})

    seen_names = set()
    norm_commands = []
    for cmd in commands:
        name = (cmd.get('command_name') or '').strip()
        desc = (cmd.get('command_description') or '').strip()
        if not name or not desc:
            return _resp(400, {'error': 'Each command requires command_name and command_description'})
        key = name.lower().lstrip('/')
        if key in seen_names:
            return _resp(400, {'error': f'Duplicate command name: {name}. Command names must be unique'})
        seen_names.add(key)
        norm_commands.append({'command_name': key, 'command_description': desc})

    payload = {'commands': norm_commands, 'prompts': prompts}
    if enable_welcome is not None:
        payload['enable_welcome_message'] = bool(enable_welcome)

    result = _graph_api(f'{phone_id}/conversational_automation', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': result.get('success', True), 'result': result})


def _get_conversational_automation(phone_id: str) -> Dict:
    """Read the currently-configured ice-breaker prompts + slash commands.
    GET /{phone_id}?fields=conversational_automation"""
    result = _graph_api(phone_id, method='GET',
                        params={'fields': 'conversational_automation'}, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    ca = result.get('conversational_automation', {}) or {}
    return _resp(200, {
        'phoneId': phone_id,
        'prompts': ca.get('prompts', []),
        'commands': ca.get('commands', []),
        'enable_welcome_message': ca.get('enable_welcome_message', False),
    })


# ============================================================================
# THROUGHPUT (WhatsApp Cloud API messages-per-second level for a phone number)
# GET /{phone_id}?fields=throughput
# ============================================================================
def _get_throughput(phone_id: str) -> Dict:
    """Read the phone number's current throughput level + quality rating.
    Throughput.level is STANDARD (80 mps), HIGH (1,000 mps) or NOT_APPLICABLE
    (WhatsApp Business app numbers, fixed 20 mps). Auto-upgrades are Meta-managed."""
    result = _graph_api(phone_id, method='GET', params={
        'fields': 'throughput,quality_rating,display_phone_number,verified_name,status,platform_type'
    }, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    throughput = result.get('throughput', {}) or {}
    level = throughput.get('level', '')
    mps = {'STANDARD': 80, 'HIGH': 1000, 'NOT_APPLICABLE': 20}.get(level)
    return _resp(200, {
        'phoneId': phone_id,
        'displayPhoneNumber': result.get('display_phone_number', ''),
        'verifiedName': result.get('verified_name', ''),
        'status': result.get('status', ''),
        'platformType': result.get('platform_type', ''),
        'qualityRating': result.get('quality_rating', ''),
        'throughputLevel': level,
        'messagesPerSecond': mps,
    })


# ============================================================================
# DIRECT SEND API (BETA) — send utility/authentication messages WITHOUT
# pre-creating a template. Meta auto-generates/matches a template from the
# message body. POST /{phone_id}/messages with a top-level `category` field.
#
# THE BETA GATE IS CODE 100, NOT 139200. This comment used to say the opposite,
# and it is where the defect came from, so the correction is recorded here
# rather than quietly applied:
#
#   * NOT ONBOARDED -> synchronous **100** (OAuthException) whose
#     `error_data.details` explains that `category` requires Direct Send and to
#     use an approved template instead. This is the error an eligible-but-not-
#     yet-onboarded WABA actually returns, and the one this whole surface exists
#     to explain.
#   * 139200 / 131064 -> access was granted and then **restricted or capped** by
#     Meta's category-misclassification enforcement. A different condition, with
#     a different fix, so it is reported as a separate `restricted` signal.
#
# Eligibility is per WABA and is granted by Meta in WhatsApp Manager; there is
# no documented Graph call that onboards a WABA from code.
# ============================================================================
_DIRECT_SEND_CATEGORIES = {'utility', 'authentication'}
# One table, in the shared module, so this surface and outbound-whatsapp cannot
# describe the same Meta code two different ways.
_DIRECT_SEND_ERROR_HINTS = direct_send_util.ERROR_HINTS


def _direct_send(phone_id: str, body: Dict) -> Dict:
    """Direct Send API (beta). Supports text (+ optional interactive buttons),
    category utility|authentication, optional business-named template, optional TTL."""
    import re as _re
    to = (body.get('to') or body.get('recipientPhone') or '').strip()
    category = (body.get('category') or 'utility').lower()
    text = body.get('text') or body.get('content') or ''
    template_name = (body.get('templateName') or '').strip()
    ttl_seconds = body.get('ttlSeconds')
    buttons = body.get('buttons') or []  # [{type:'reply'|'url', text, id?, url?}]

    if not to:
        return _resp(400, {'error': 'to (recipient phone, digits or +E.164) is required'})
    if category not in _DIRECT_SEND_CATEGORIES:
        return _resp(400, {'error': "category must be 'utility' or 'authentication'"})
    if not text:
        return _resp(400, {'error': 'text (message body) is required'})
    # 1024 is OURS, not a verified Meta limit. The docs say Direct Send matches the
    # limits for business-initiated template messages, but that table does not render
    # in text extraction, so the specific number is unverified. The documented 1024s
    # are the voice-call body and the CTA/reply interactive body — plausible here and
    # deliberately conservative. Kept rather than raised, because refusing locally is
    # a clear error and Meta's refusal would not be.
    if len(text) > 1024:
        return _resp(400, {'error': 'Body text exceeds 1024 characters (our conservative cap; Meta\'s documented limit for plain text is unverified)'})

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'category': category,
    }

    # Interactive buttons are utility-only in the beta (max 10 reply, max 2 CTA URL).
    reply_btns = [b for b in buttons if (b.get('type') or 'reply') == 'reply']
    url_btns = [b for b in buttons if b.get('type') == 'url']
    if buttons and category == 'utility':
        if len(reply_btns) > 10:
            return _resp(400, {'error': 'Max 10 quick-reply buttons'})
        if len(url_btns) > 2:
            return _resp(400, {'error': 'Max 2 call-to-action URL buttons'})
        action_buttons = []
        for i, b in enumerate(reply_btns):
            action_buttons.append({'type': 'reply', 'reply': {
                'id': b.get('id') or f'btn_{i}', 'title': (b.get('text') or '')[:20]}})
        if url_btns and not action_buttons:
            # Pure CTA URL button → cta_url interactive
            b = url_btns[0]
            payload['type'] = 'interactive'
            payload['interactive'] = {
                'type': 'cta_url',
                'body': {'text': text},
                'action': {'name': 'cta_url', 'parameters': {
                    'display_text': (b.get('text') or 'Open')[:20], 'url': b.get('url') or ''}},
            }
        else:
            payload['type'] = 'interactive'
            payload['interactive'] = {
                'type': 'button',
                'body': {'text': text},
                'action': {'buttons': action_buttons},
            }
    else:
        payload['type'] = 'text'
        payload['text'] = {'body': text}

    if template_name:
        if not _re.match(r'^[a-z0-9_]+$', template_name) or len(template_name) > 512:
            return _resp(400, {'error': 'templateName must match ^[a-z0-9_]+$ and be <= 512 chars'})
        if category != 'utility':
            return _resp(400, {'error': 'Business-named templates are supported only for category "utility"'})
        payload['direct_send_config'] = {'template_name': template_name}

    if ttl_seconds is not None and ttl_seconds != '':
        # The field is `ttl_seconds`, not `ttl` — phase 1 sent `ttl` and every TTL
        # send therefore failed with an unexplained 100 (an unsupported parameter is
        # itself a 100). Bounds are PER CATEGORY: authentication caps at 900, so the
        # old single 30..43200 check accepted values Meta refuses. Both live in
        # lambda_utils.direct_send, which also explains why they are not
        # template_ttl's numbers.
        ttl_error = direct_send_util.validate_ttl_seconds(category, ttl_seconds)
        if ttl_error:
            return _resp(400, {'error': ttl_error})
        payload['ttl_seconds'] = int(ttl_seconds)

    # Smoke-test lockdown, at the wire and unconditional.
    #
    # This is the LAST thing before the Graph call, after every validation, so no
    # branch added later can reach a recipient while WA_LIVE_SMOKE_TEST is on. It is
    # the same guard outbound-whatsapp enforces in _send_direct_api; this surface had
    # none, which left a hole in a guarantee stated as absolute. A latent hole in a
    # lockdown is still a hole: the guarantee is "no branch reaches a customer", and
    # one did.
    #
    # The QA number is never hard-coded here — live_smoke reads WA_QA_RECIPIENT.
    _allowed, _reason = live_smoke.check_recipient(to)
    if not _allowed:
        logger.error(json.dumps({
            'event': 'smoke_mode_send_blocked',
            'where': 'direct_send',
            'reason': _reason,
            'to': mask_phone(to),
            **live_smoke.describe(),
        }))
        return _resp(403, {
            'error': 'Live smoke-test mode is active — sends are limited to the QA recipient',
            'reason': _reason,
        })

    result = _graph_api(f'{phone_id}/messages', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        err = result.get('error', {})
        # Meta errors can arrive nested ({'error': {'error': {...}}}), so read the
        # inner envelope when there is one before pulling code/details out.
        inner = err.get('error') if isinstance(err, dict) and isinstance(err.get('error'), dict) else err
        code = inner.get('code') if isinstance(inner, dict) else None
        details = ''
        if isinstance(inner, dict):
            details = (inner.get('error_data', {}) or {}).get('details', '') or ''
        kind = direct_send_util.classify_error(code, details)
        hint = _DIRECT_SEND_ERROR_HINTS.get(str(code))
        return _resp(400, {
            'error': err,
            'directSendHint': hint,
            # Not onboarded: the account is not (yet) in the programme. Code 100 with
            # category/Direct-Send details.
            'betaGated': kind == direct_send_util.NOT_ONBOARDED,
            # Restricted/capped: access existed and Meta enforcement took it away or
            # limited it. A SEPARATE signal — conflating the two is what made the
            # not-onboarded case unexplainable.
            'restricted': kind == direct_send_util.RESTRICTED,
        })
    return _resp(200, {'success': True, 'category': category,
                      'templateName': template_name or None, 'result': result})


# REMOVED 2026-10-06: `_direct_send_upload_sample`, which POSTed to
# `/{waba_id}/message_samples` as a Direct Send onboarding step.
#
# That endpoint appears in NONE of the ten Direct Send documentation pages read for
# the phase-2 design, and a targeted search produced no Meta corroboration. It was
# either a private-beta affordance that has since gone, or it was inferred. Meta
# performs Direct Send onboarding itself and adds the fallback templates; there is no
# documented self-serve sample-upload call.
#
# Phase 2 must not be built on an endpoint we cannot evidence, so the function, its
# API client wrapper and its dashboard panel are gone. The live API Gateway route is
# retained (its integration is shared with two routes that are still wanted) and now
# answers an explicit 410 — see the dispatch branch and
# docs/execution/snapshots/apigw-direct-send-samples-route-before-delete-20261006.json.


def _list_generated_templates(waba_id: str) -> Dict:
    """List Direct Send auto-generated templates (content-based + business-named).
    GET /{waba_id}/message_templates?source=AUTO_GENERATED"""
    result = _graph_api(f'{waba_id}/message_templates', method='GET',
                        params={'source': 'AUTO_GENERATED', 'limit': 200,
                                'fields': 'name,status,category,correct_category,source,language,components'},
                        waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    data = result.get('data', []) or []
    return _resp(200, {'wabaId': waba_id, 'total': len(data), 'templates': data})


# ============================================================================
# CATALOG → FLOW MAPPING
# Maps a catalog product (retailer_id) to the WhatsApp Flow that should open
# after the customer pays for it. Lets each product open its OWN flow, on either
# WABA. Read at payment capture by the razorpay-webhook resolution chain.
# ============================================================================
def _get_catalog_flow_map() -> Dict:
    """Return the full product→flow mapping dict (retailer_id → config)."""
    try:
        t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        item = t.get_item(Key={'id': CATALOG_FLOW_MAP_ID}).get('Item') or {}
        raw = item.get('configValue') or item.get('value') or '{}'
        mapping = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return mapping if isinstance(mapping, dict) else {}
    except Exception as e:
        logger.warning(json.dumps({'event': 'catalog_flow_map_read_error', 'error': str(e)}))
        return {}


def _list_catalog_flow_map(params: Dict) -> Dict:
    return _resp(200, {'map': _get_catalog_flow_map()})


def _upsert_catalog_flow_map(body: Dict) -> Dict:
    """Create/update one product→flow mapping entry.
    Body: retailerId (required), flowIdWaba1, flowIdWaba2, flowCode, cta, body.
    If 'delete' is true, removes the entry."""
    retailer_id = (body.get('retailerId') or body.get('retailer_id') or '').strip()
    if not retailer_id:
        return _resp(400, {'error': 'retailerId is required'})
    mapping = _get_catalog_flow_map()
    if body.get('delete'):
        mapping.pop(retailer_id, None)
    else:
        entry = {
            'flowIdWaba1': (body.get('flowIdWaba1') or '').strip(),
            'flowIdWaba2': (body.get('flowIdWaba2') or '').strip(),
            'flowCode': (body.get('flowCode') or '').strip(),
            'cta': (body.get('cta') or 'Complete details')[:20],
            'body': (body.get('body') or 'Payment received! Tap below to complete your request.')[:1024],
        }
        if not entry['flowIdWaba1'] and not entry['flowIdWaba2']:
            return _resp(400, {'error': 'At least one of flowIdWaba1 / flowIdWaba2 is required'})
        mapping[retailer_id] = entry
    try:
        t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        t.put_item(Item={'id': CATALOG_FLOW_MAP_ID, 'configValue': json.dumps(mapping),
                         'updatedAt': int(time.time())})
    except Exception as e:
        return _resp(500, {'error': f'Failed to save mapping: {e}'})
    logger.info(json.dumps({'event': 'catalog_flow_map_upserted', 'retailerId': retailer_id,
                            'deleted': bool(body.get('delete'))}))
    return _resp(200, {'success': True, 'map': mapping})


# ============================================================================
# AI Hybrid Routing — which triggers the bot handles vs the Meta AI agent.
# Read by the inbound handler (id='ai_hybrid_routing') to decide, on standby,
# whether to take control (deterministic keyword/command/type) or let the AI reply.
# ============================================================================
def _get_ai_routing() -> Dict:
    try:
        t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        item = t.get_item(Key={'id': AI_ROUTING_ID}).get('Item') or {}
        raw = item.get('configValue') or '{}'
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        cfg = dict(DEFAULT_AI_ROUTING)
        cfg.update({k: v for k, v in data.items() if v is not None})
        return cfg
    except Exception as e:
        logger.warning(json.dumps({'event': 'ai_routing_read_error', 'error': str(e)}))
        return dict(DEFAULT_AI_ROUTING)


def _list_ai_routing(params: Dict) -> Dict:
    return _resp(200, {'routing': _get_ai_routing(), 'defaults': DEFAULT_AI_ROUTING})


def _update_ai_routing(body: Dict) -> Dict:
    """Update AI routing rules. Body may include: enabled(bool), keywords[list],
    contains[list], types[list], commandPrefix(str). Missing keys keep current values."""
    cfg = _get_ai_routing()
    for k in ('enabled', 'keywords', 'contains', 'types', 'commandPrefix'):
        if k in body and body[k] is not None:
            cfg[k] = body[k]
    try:
        dynamodb.Table(SYSTEM_CONFIG_TABLE).put_item(Item={
            'id': AI_ROUTING_ID, 'configValue': json.dumps(cfg), 'updatedAt': int(time.time())})
    except Exception as e:
        return _resp(500, {'error': f'Failed to save routing: {e}'})
    logger.info(json.dumps({'event': 'ai_routing_updated', 'enabled': cfg.get('enabled')}))
    return _resp(200, {'success': True, 'routing': cfg})


# ============================================================================
# CONVERSIONS API for Business Messaging (Click-to-WhatsApp)
# Uses the whatsapp_business_manage_events permission. Logs conversion events
# (Purchase, LeadSubmitted, etc.) that happen INSIDE the WhatsApp thread back to
# Meta so Click-to-WhatsApp ad campaigns can optimize & measure.
#   Dataset:  fixed CONFIGURATION, one dataset shared by BOTH WABAs (see
#             CAPI_FIXED_DATASET_ID). The per-WABA GET/POST /{waba_id}/dataset
#             create path is still here, reachable by clearing that variable.
#   Log:      POST     /{dataset_id}/events          -> event ingested
#   ctwa_clid captured from the inbound `referral` object (ad-originated msgs).
# Docs: developers.facebook.com/docs/marketing-api/conversions-api/business-messaging
# ============================================================================
CAPI_DATASET_PREFIX = 'capi_dataset_'   # SystemConfigTable id: capi_dataset_<wabaId>
CAPI_CLID_PREFIX = 'capi_clid_'         # SystemConfigTable id: capi_clid_<phone>
CAPI_EVENT_LOG_ID = 'capi_event_log'    # SystemConfigTable id: bounded recent-events list
CAPI_PARTNER_AGENT = os.environ.get('CAPI_PARTNER_AGENT', 'wecare-digital')

# The ONE Conversions API dataset both WABAs report into. No waba_id appears in the lookup
# because the dataset is deliberately shared -- one Events Manager destination for WABA1 and
# WABA2, matching the single shared `wecare_shop` catalog. Per-WABA attribution is NOT lost:
# user_data.whatsapp_business_account_id still carries the resolved WABA on every event.
#
# Setting this variable to the EMPTY STRING re-enables the per-WABA
# `POST /{waba_id}/dataset` create-and-cache path below, so nothing is removed. Note what that
# RESUMES rather than recreates: the `capi_dataset_<wabaId>` rows written by the old path are
# still in SystemConfigTable and are NOT deleted here, so the status read (create=False) hands
# back those RETIRED per-WABA dataset ids from cache. Only an explicit re-check (create=True,
# which skips the cache) calls Graph for a dataset. To get genuinely fresh per-WABA datasets,
# delete the `capi_dataset_<wabaId>` rows as well -- a data change, so it is left to the owner.
#
# Read at MODULE scope, which is correct here: this is CONFIGURATION, not a credential, so the
# lazy-read rule in lambda-snapstart-deploy.md and secret-handling.md does not apply -- the same
# justification MM_METRICS_EDGE records below. Per that same rule the variable is NOT added to
# config/lambda-env-manifest.json while nothing sets it live; the day it is set, add
# "META_CAPI_DATASET_ID": "4554612361454941" under functions."wecare-whatsapp-business-api"
# and bump "_variables" in the same change.
CAPI_FIXED_DATASET_ID = os.environ.get('META_CAPI_DATASET_ID', '4554612361454941')
CAPI_EVENT_TYPES = {
    'Purchase', 'LeadSubmitted', 'InitiateCheckout', 'AddToCart', 'ViewContent',
    'OrderCreated', 'OrderShipped', 'OrderDelivered', 'OrderCanceled', 'OrderReturned',
    'CartAbandoned', 'QualifiedLead', 'RatingProvided', 'ReviewProvided',
}


def _capi_resolve_waba(src: Dict) -> str:
    wid = str(src.get('wabaId') or src.get('waba_id') or '').strip()
    u = wid.upper()
    if u in ('WABA1', '1'):
        return WABA1_ID
    if u in ('WABA2', 'WABA-T', '2'):
        return WABA2_ID
    return wid or WABA1_ID


def _capi_get_dataset(waba_id: str, create: bool = False) -> Dict:
    """Resolve the Conversions API dataset for a WABA.

    Normally a constant: both WABAs share CAPI_FIXED_DATASET_ID, so there is nothing to look up,
    nothing to cache and no Graph create call to make -- `create` is honoured as a no-op re-check.
    Only when that variable is explicitly cleared does the per-WABA get-or-create path run, and
    then `create=False` answers from the surviving `capi_dataset_<wabaId>` cache rows (the
    retired per-WABA ids) before any Graph call -- see the note on CAPI_FIXED_DATASET_ID.
    """
    if CAPI_FIXED_DATASET_ID:
        return {'datasetId': CAPI_FIXED_DATASET_ID, 'wabaId': waba_id, 'fixed': True}
    t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    cache_id = CAPI_DATASET_PREFIX + waba_id
    if not create:
        try:
            item = t.get_item(Key={'id': cache_id}).get('Item') or {}
            if item.get('configValue'):
                return {'datasetId': item['configValue'], 'wabaId': waba_id, 'cached': True}
        except Exception:
            pass
    # POST returns the existing dataset_id if one is already linked, else creates it.
    result = _graph_api(f'{waba_id}/dataset', method='POST', waba_id=waba_id)
    if 'error' in result:
        return {'error': result['error']}
    dataset_id = str(result.get('id') or '')
    if dataset_id:
        try:
            t.put_item(Item={'id': cache_id, 'configValue': dataset_id,
                             'updatedAt': int(time.time())})
        except Exception:
            pass
    return {'datasetId': dataset_id, 'wabaId': waba_id, 'cached': False}


def _capi_lookup_clid(phone: str) -> Dict:
    """Return the stored ctwa_clid capture for a customer phone (if any)."""
    if not phone:
        return {}
    digits = ''.join(ch for ch in phone if ch.isdigit())
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': CAPI_CLID_PREFIX + digits}).get('Item') or {}
        raw = item.get('configValue')
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def _capi_append_log(entry: Dict) -> None:
    t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    try:
        item = t.get_item(Key={'id': CAPI_EVENT_LOG_ID}).get('Item') or {}
        raw = item.get('configValue') or '[]'
        log = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        log = []
    log.insert(0, entry)
    log = log[:100]
    try:
        t.put_item(Item={'id': CAPI_EVENT_LOG_ID, 'configValue': json.dumps(log),
                         'updatedAt': int(time.time())})
    except Exception:
        pass


def _capi_list_clids(limit: int = 50) -> list:
    try:
        t = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        resp = t.scan(FilterExpression=Attr('id').begins_with(CAPI_CLID_PREFIX), Limit=200)
        out = []
        for it in resp.get('Items', []):
            raw = it.get('configValue')
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            out.append(data)
        out.sort(key=lambda x: x.get('ts', 0), reverse=True)
        return out[:limit]
    except Exception as e:
        logger.warning(json.dumps({'event': 'capi_clids_scan_error', 'error': str(e)}))
        return []


def _capi_status(params: Dict) -> Dict:
    """Console overview: dataset id per WABA + recent captured click ids + event log."""
    waba_id = _capi_resolve_waba(params)
    ds = _capi_get_dataset(waba_id, create=False)
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': CAPI_EVENT_LOG_ID}).get('Item') or {}
        raw = item.get('configValue') or '[]'
        log = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        log = []
    return _resp(200, {
        'wabaId': waba_id,
        'partnerAgent': CAPI_PARTNER_AGENT,
        'dataset': ds,
        'supportedEvents': sorted(CAPI_EVENT_TYPES),
        'capturedClicks': _capi_list_clids(),
        'recentEvents': log[:50],
    })


def _capi_create_dataset(body: Dict) -> Dict:
    waba_id = _capi_resolve_waba(body)
    ds = _capi_get_dataset(waba_id, create=True)
    if 'error' in ds:
        return _resp(400, ds)
    return _resp(200, {'success': True, **ds})


def _capi_log_event(body: Dict) -> Dict:
    """Log a business-messaging conversion event to Meta via the Conversions API."""
    explicit_waba = bool(str(body.get('wabaId') or body.get('waba_id') or '').strip())
    waba_id = _capi_resolve_waba(body)
    event_name = (body.get('eventName') or 'Purchase').strip()
    if event_name not in CAPI_EVENT_TYPES:
        return _resp(400, {'error': f'Invalid eventName. Allowed: {sorted(CAPI_EVENT_TYPES)}'})

    ctwa_clid = (body.get('ctwaClid') or body.get('ctwa_clid') or '').strip()
    phone = (body.get('phone') or body.get('to') or '').strip()
    capture = {}
    if not ctwa_clid and phone:
        capture = _capi_lookup_clid(phone)
        ctwa_clid = (capture.get('ctwaClid') or '').strip()
        # Attribute to the WABA the click was captured on unless caller was explicit.
        if not explicit_waba and capture.get('wabaId'):
            waba_id = capture['wabaId']
    if not ctwa_clid:
        return _resp(400, {'error': 'No ctwa_clid available. Conversion events only apply to '
                                    'conversations that started from a Click-to-WhatsApp ad.'})

    ds = _capi_get_dataset(waba_id, create=False)
    if 'error' in ds:
        return _resp(400, ds)
    dataset_id = ds.get('datasetId')
    if not dataset_id:
        return _resp(400, {'error': 'Could not resolve dataset_id for this WABA. Create the dataset first.'})

    event = {
        'event_name': event_name,
        'event_time': int(body.get('eventTime') or time.time()),
        'action_source': 'business_messaging',
        'messaging_channel': 'whatsapp',
        'user_data': {
            'whatsapp_business_account_id': waba_id,
            'ctwa_clid': ctwa_clid,
        },
    }
    custom: Dict = {}
    if body.get('value') is not None:
        try:
            custom['value'] = float(body['value'])
            custom['currency'] = (body.get('currency') or 'INR').upper()
        except (TypeError, ValueError):
            pass
    if body.get('orderId'):
        custom['order_id'] = str(body['orderId'])
    if custom:
        event['custom_data'] = custom

    payload = {'data': [event], 'partner_agent': CAPI_PARTNER_AGENT}
    result = _graph_api(f'{dataset_id}/events', method='POST', payload=payload, waba_id=waba_id)
    ok = 'error' not in result
    _capi_append_log({
        'ts': int(time.time()), 'wabaId': waba_id, 'event': event_name,
        'ctwaClid': ctwa_clid[:16] + '…', 'phone': phone,
        'value': custom.get('value'), 'currency': custom.get('currency'),
        'ok': ok, 'response': result,
    })
    if not ok:
        return _resp(400, {'success': False, 'datasetId': dataset_id, 'error': result.get('error')})
    return _resp(200, {'success': True, 'datasetId': dataset_id, 'eventName': event_name,
                       'eventsReceived': result.get('events_received'), 'result': result})


def _send_marketing_message(phone_id: str, body: Dict) -> Dict:
    """Marketing Messages (MM Lite) API — send an OPTIMIZED marketing template
    message over the same phone number as Cloud API. Both WABAs are ONBOARDED.
    POST /{phone_id}/marketing_messages with a standard template payload.

    Body: to, templateName, language(default en/en_US), params(list, body vars),
    messageActivitySharing(bool, optional per-message override)."""
    to = (body.get('to') or body.get('recipientPhone') or '').strip()
    template_name = (body.get('templateName') or '').strip()
    language = body.get('language') or 'en'
    params = body.get('params') or []
    activity_sharing = body.get('messageActivitySharing')

    if not to:
        return _resp(400, {'error': 'to (recipient phone) is required'})
    if not template_name:
        return _resp(400, {'error': 'templateName is required (must be an APPROVED marketing template)'})

    template_obj = {'name': template_name, 'language': {'code': language}}
    if params:
        template_obj['components'] = [{
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(p)} for p in params],
        }]

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'template',
        'template': template_obj,
    }
    if activity_sharing is not None:
        payload['message_activity_sharing'] = bool(activity_sharing)

    result = _graph_api(f'{phone_id}/marketing_messages', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'result': result})


def _get_mm_onboarding_status(waba_id: str) -> Dict:
    """Marketing Messages (MM Lite) API onboarding/eligibility for a WABA.
    GET /{waba_id}?fields=marketing_messages_onboarding_status
    Values include ELIGIBLE, ONBOARDED, NOT_ELIGIBLE, etc."""
    result = _graph_api(waba_id, method='GET',
                        params={'fields': 'marketing_messages_onboarding_status'}, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    status = result.get('marketing_messages_onboarding_status', '')
    # Field may be a plain string or an object {status, time}
    if isinstance(status, dict):
        status_val = status.get('status', '')
        status_time = status.get('time', '')
    else:
        status_val = status
        status_time = ''
    return _resp(200, {'wabaId': waba_id, 'onboardingStatus': status_val, 'time': status_time})


# The MM API conversion-metrics edge. UNVERIFIED -- no local documentation names it and
# it has never been called on this account. This constant is the single place to correct
# it; _get_mm_conversion_metrics reports the value it used in every response, including
# the unavailable one, so a wrong name is diagnosable from the dashboard rather than
# from CloudWatch.
#
# Read at MODULE scope, which is correct here and only here: this is CONFIGURATION, not a
# credential, so the lazy-read rule in lambda-snapstart-deploy.md and secret-handling.md
# does not apply, and the same module already reads SYSTEM_CONFIG_TABLE this way. If the
# variable is ever actually set on the function it must be added to
# config/lambda-env-manifest.json in the same change -- nothing sets it today.
MM_METRICS_EDGE = os.environ.get('MM_METRICS_EDGE', 'marketing_messages_insights')
MM_METRICS_CACHE_PREFIX = 'mm_metrics_'


def _mm_metrics_cached(waba_id: str) -> Dict:
    """Last good metrics read for a WABA, or {} if there is none. Fail-open.

    The empty answer is `{}` and NOT {'metrics': [], 'readAt': 0}, because the only
    log line item 7 ships reports `hasCached: bool(cached)` -- and a truthy dict for a
    row that does not exist makes that field say True on every unavailable read, which
    distinguishes nothing at the exact moment the edge name is suspect.
    """
    try:
        item = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(
            Key={'id': MM_METRICS_CACHE_PREFIX + waba_id}).get('Item')
        if not item:
            return {}
        raw = item.get('configValue')
        return {'metrics': json.loads(raw) if isinstance(raw, str) else (raw or []),
                'readAt': int(item.get('updatedAt') or 0)}
    except Exception:
        return {}


def _mm_metrics_cache_put(waba_id: str, rows: list) -> None:
    """Cache the last good metrics read. Fail-open: a cache write must never break the
    request -- test_cache_failure_does_not_break_the_read pins that. `default=str` is
    there because the row shape is unverified and a Decimal or a date in Meta's payload
    must not raise inside a telemetry write.

    updatedAt is Decimal(str(int(...))) rather than the bare int _capi_get_dataset writes:
    both serialize to the same DynamoDB N, and Decimal(str(...)) is this project's rule for
    every number reaching DynamoDB. A convention alignment, not a copy of the neighbour.
    """
    try:
        dynamodb.Table(SYSTEM_CONFIG_TABLE).put_item(Item={
            'id': MM_METRICS_CACHE_PREFIX + waba_id,
            'configValue': json.dumps(rows, default=str),
            'updatedAt': Decimal(str(int(time.time()))),
        })
    except Exception as e:
        logger.warning(json.dumps({'event': 'mm_metrics_cache_write_failed',
                                   'wabaId': waba_id, 'error': type(e).__name__}))


def _get_mm_conversion_metrics(waba_id: str, params: Dict) -> Dict:
    """Read MM API conversion metrics for a WABA and cache the last good answer.

    Closes the read half of the conversion loop: _capi_log_event writes AddToCart /
    InitiateCheckout / Purchase out to the dataset, and until now nothing read anything
    back, so nothing could inform the next campaign.

    Answers 200 with available:false -- never 400 -- when Meta says the edge is not
    available for this account. That is the same honest-refusal contract
    whatsapp-template-management._list_template_library uses, and it is what lets the
    panel render "not available" instead of an error toast.

    The rows are returned UNRESHAPED: their shape has never been observed on this
    account, so any local projection would be as unverified as the edge name while
    looking like a settled mapping.
    """
    since = (params or {}).get('since') or ''
    until = (params or {}).get('until') or ''
    # No `fields` is sent: the edge's own field names are unverified, and a wrong
    # `fields` value makes Graph reject the whole request. Take the default projection.
    q: Dict[str, Any] = {}
    if since:
        q['since'] = since
    if until:
        q['until'] = until
    result = _graph_api(f'{waba_id}/{MM_METRICS_EDGE}', params=q or None, waba_id=waba_id)
    if 'error' in result:
        cached = _mm_metrics_cached(waba_id)
        logger.info(json.dumps({
            'event': 'mm_conversion_metrics_unavailable', 'wabaId': waba_id,
            'edge': MM_METRICS_EDGE, 'hasCached': bool(cached)}))
        return _resp(200, {
            'wabaId': waba_id, 'available': False, 'edge': MM_METRICS_EDGE,
            'reason': (result.get('error') or {}).get('message') if isinstance(
                result.get('error'), dict) else str(result.get('error')),
            'cached': cached,
            'note': ('MM API conversion metrics could not be read for this WABA. The edge '
                     'name is unverified in this account; correct MM_METRICS_EDGE if Meta '
                     'documents a different path, or confirm MM onboarding status first.'),
        })
    rows = result.get('data') if isinstance(result.get('data'), list) else [result]
    _mm_metrics_cache_put(waba_id, rows)
    logger.info(json.dumps({
        'event': 'mm_conversion_metrics_read', 'wabaId': waba_id,
        'edge': MM_METRICS_EDGE, 'rowCount': len(rows),
        'events': sorted({str(r.get('event_name') or r.get('name') or '')
                          for r in rows if isinstance(r, dict)})}))
    return _resp(200, {'wabaId': waba_id, 'available': True, 'edge': MM_METRICS_EDGE,
                       'metrics': rows, 'readAt': int(time.time())})


# ============================================================================
# LINK PREVIEW VALIDATOR (Open Graph requirements for WhatsApp link previews)
# ============================================================================
def _is_ssrf_safe_url(url: str) -> bool:
    """SSRF guard for link-preview: only allow public http(s) hosts.
    Blocks loopback, private, link-local (incl. 169.254.169.254 metadata),
    reserved, multicast and unspecified addresses after DNS resolution."""
    import ipaddress
    import socket
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme not in ('http', 'https') or not p.hostname:
        return False
    h = p.hostname.lower()
    if h == 'localhost' or h.endswith('.localhost') or h.endswith('.internal') or h.endswith('.local'):
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except Exception:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def _check_link_preview(url: str) -> Dict:
    """Fetch a URL and check whether it meets WhatsApp link-preview (Open Graph) requirements.
    Returns warnings (best-effort) rather than hard failures, per WhatsApp behavior."""
    if not url or not url.startswith('http'):
        return _resp(400, {'error': 'A valid http(s) url is required'})
    if not _is_ssrf_safe_url(url):
        return _resp(400, {'error': 'URL host is not allowed (private, loopback, link-local, or non-public addresses are blocked).'})
    warnings = []
    found = {'og:title': '', 'og:description': '', 'og:url': '', 'og:image': ''}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WhatsApp/2.25.0.0 A'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(300 * 1024)  # only first 300KB matters for OG tags
        html = raw.decode('utf-8', errors='ignore')
        head = html.split('</head>', 1)[0] if '</head>' in html else html
        if '</head>' not in html:
            warnings.append('No closing </head> found within the first 300KB; Open Graph tags must be inside <head>.')
        import re as _re
        for prop in found:
            m = _re.search(
                r'<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']*)["\']' % _re.escape(prop),
                head, _re.IGNORECASE)
            if not m:
                m = _re.search(
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']%s["\']' % _re.escape(prop),
                    head, _re.IGNORECASE)
            found[prop] = (m.group(1).strip() if m else '')

        if not found['og:title']:
            warnings.append('og:title is missing or empty (shown as the bold preview title).')
        if not found['og:description']:
            warnings.append('og:description is missing or empty (shown under the title).')
        if not found['og:url']:
            warnings.append('og:url is missing or empty (should be the canonical, undecorated URL).')
        if not found['og:image']:
            warnings.append('og:image is missing (no thumbnail will be shown).')
        elif not found['og:image'].startswith('http'):
            warnings.append('og:image must be an absolute URL (starting with http/https).')
    except urllib.error.HTTPError as e:
        return _resp(200, {'url': url, 'ok': False, 'warnings': [f'HTTP {e.code} fetching the page.'], 'og': found})
    except Exception as e:
        return _resp(200, {'url': url, 'ok': False, 'warnings': [f'Could not fetch/parse the page: {e}'], 'og': found})

    return _resp(200, {
        'url': url,
        'ok': len(warnings) == 0,
        'og': found,
        'warnings': warnings,
        'note': 'WhatsApp link previews are best-effort. Image should be <600KB, width >=300px, aspect ratio <=4:1.',
        'crawlerUserAgents': ['WhatsApp/2.x.x.x A', 'WhatsApp/2.x.x.x I', 'WhatsApp/2.x.x.x N'],
    })


# ============================================================================
# TEMPLATE VALIDATION HELPERS (TTL by category + button grouping rules)
# Reusable validators per WhatsApp template docs.
# ============================================================================
def _validate_ttl(category: str, seconds) -> Optional[str]:
    """Validate message_send_ttl_seconds against the template category. Returns error string or None.

    Delegates to the consolidated TTL service (lambda_utils.template_ttl).
    """
    from lambda_utils.template_ttl import validate_ttl_error
    return validate_ttl_error(category, seconds)


def _validate_template_buttons(buttons: list) -> Optional[str]:
    """Validate WhatsApp template button counts and quick-reply grouping. Returns error string or None."""
    if not buttons:
        return None
    if len(buttons) > 10:
        return 'A template may have at most 10 buttons'
    counts = {}
    for b in buttons:
        t = (b.get('type') or '').upper()
        counts[t] = counts.get(t, 0) + 1
        text = b.get('text', '')
        if t in ('QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'VOICE_CALL') and len(text) > 25:
            return f'{t} button text must be <= 25 characters'
        if t == 'COPY_CODE' and len(str(b.get('example', ''))) > 20:
            return 'COPY_CODE example must be <= 20 characters'
        if t == 'PHONE_NUMBER' and len(str(b.get('phone_number', ''))) > 20:
            return 'PHONE_NUMBER must be <= 20 characters'
        if t == 'URL' and len(str(b.get('url', ''))) > 2000:
            return 'URL must be <= 2000 characters'
    if counts.get('COPY_CODE', 0) > 1:
        return 'At most 1 COPY_CODE button allowed'
    if counts.get('PHONE_NUMBER', 0) > 1:
        return 'At most 1 PHONE_NUMBER button allowed'
    if counts.get('URL', 0) > 2:
        return 'At most 2 URL buttons allowed'
    if counts.get('QUICK_REPLY', 0) > 10:
        return 'At most 10 QUICK_REPLY buttons allowed'
    # Quick-reply grouping: all quick replies must be contiguous (one group)
    types = [(b.get('type') or '').upper() for b in buttons]
    qr_positions = [i for i, t in enumerate(types) if t == 'QUICK_REPLY']
    if qr_positions and (max(qr_positions) - min(qr_positions) + 1) != len(qr_positions):
        return 'Quick reply buttons must be grouped together (contiguous), not interleaved with other button types'
    return None


# ============================================================================
# TEMPLATE TTL ROUTES
#   GET  /wa-business/template-ttl/rules         → human-readable rule set
#   POST /wa-business/template-ttl/validate      → validate a (category, ttl)
#   POST /wa-business/templates/{templateId}/ttl → update a template's TTL
# Backed by the consolidated lambda_utils.template_ttl service.
# ============================================================================
def _get_ttl_rules() -> Dict:
    """Return the full TTL rule set (bounds + human-readable descriptions)."""
    from lambda_utils.template_ttl import ttl_rules
    return _resp(200, {'rules': ttl_rules()})


def _get_cost_flags() -> Dict:
    """Return all cost-control feature flags and their effective on/off state."""
    try:
        from lambda_utils.cost_flags import all_flags
        flags = all_flags()
    except Exception as e:
        logger.error(f'cost_flags read failed: {e}')
        flags = {}
    # Static cost-risk metadata for the UI (kept here so the page needs no second call).
    meta = {
        # No ENABLE_WAF entry: WAF was deleted from the account on 2026-09-28 and the
        # flag was removed from lambda_utils.cost_flags.FLAGS with it.
        'ENABLE_CLOUDFRONT': {'risk': 'medium', 'service': 'CloudFront'},
        'ENABLE_STEP_FUNCTIONS': {'risk': 'medium', 'service': 'Step Functions'},
        'ENABLE_ATHENA_ANALYTICS': {'risk': 'high', 'service': 'Athena'},
        'ENABLE_GLUE': {'risk': 'high', 'service': 'Glue'},
        'ENABLE_TEXTRACT_IMPORT': {'risk': 'high', 'service': 'Textract'},
        'ENABLE_BEDROCK_ASSIST': {'risk': 'high', 'service': 'Bedrock'},
        'ENABLE_XRAY': {'risk': 'medium', 'service': 'X-Ray'},
        'ENABLE_ADVANCED_CLOUDWATCH_DASHBOARD': {'risk': 'medium', 'service': 'CloudWatch dashboards'},
        'ENABLE_RAW_WEBHOOK_ARCHIVE': {'risk': 'medium', 'service': 'S3 raw archive'},
    }
    return _resp(200, {'flags': flags, 'meta': meta})


def _validate_template_ttl_route(body: Dict) -> Dict:
    """Validate a category/TTL pair. Body: { category, ttl | message_send_ttl_seconds }."""
    from lambda_utils.template_ttl import validate_ttl
    category = body.get('category')
    if not category:
        return _resp(400, {'error': 'category is required'})
    seconds = body.get('ttl', body.get('message_send_ttl_seconds'))
    result = validate_ttl(category, seconds)
    return _resp(200, result)


def _update_template_ttl(template_id: str, body: Dict, waba_id: str = None) -> Dict:
    """Update a template's message_send_ttl_seconds via Meta after validation.

    Fetches the template's current category so the TTL is validated against the
    correct bounds, then warns if a category change has cleared the TTL.
    """
    from lambda_utils.template_ttl import validate_ttl, detect_null_ttl_after_category_change
    if not template_id:
        return _resp(400, {'error': 'templateId required'})
    seconds = body.get('ttl', body.get('message_send_ttl_seconds'))
    if seconds is None:
        return _resp(400, {'error': 'ttl (message_send_ttl_seconds) is required'})

    # Resolve category: prefer the live template category over any client-supplied value.
    detail = _graph_api(template_id, params={'fields': 'name,category,message_send_ttl_seconds'}, waba_id=waba_id)
    if 'error' in detail:
        return _resp(400, detail)
    category = detail.get('category') or body.get('category')

    result = validate_ttl(category, seconds)
    if not result['ok']:
        return _resp(400, {'error': result['error'], 'validation': result})

    update = _graph_api(template_id, method='POST', payload={'message_send_ttl_seconds': int(seconds)}, waba_id=waba_id)
    if 'error' in update:
        return _resp(400, update)

    warning = detect_null_ttl_after_category_change(
        body.get('previousCategory'), category, seconds if seconds is not None else None
    )
    resp_body = {
        'success': True,
        'templateId': template_id,
        'category': category,
        'ttl': int(seconds),
        'human': result.get('human'),
    }
    if warning:
        resp_body['warning'] = warning
        _emit_event('template_ttl_cleared', severity='warning', waba_id=waba_id,
                    data={'templateId': template_id, 'category': category, 'warning': warning})
    return _resp(200, resp_body)


# ============================================================================
# MEDIA (Part 4 D)
#   POST   /wa-business/media                              → upload media
#   GET    /wa-business/media/{mediaId}                    → media info (masked URL + expiry)
#   DELETE /wa-business/media/{mediaId}                    → delete media
#   POST   /wa-business/media/resumable/session           → start resumable session
#   POST   /wa-business/media/resumable/{sessionId}/chunk  → append a chunk
#   POST   /wa-business/media/resumable/{sessionId}/finish → assemble + upload, return handle
# ============================================================================
def _media_category(content_type: str) -> str:
    ct = (content_type or '').lower()
    if ct == 'image/webp':
        return 'sticker'
    if ct.startswith('image/'):
        return 'image'
    if ct.startswith('video/'):
        return 'video'
    if ct.startswith('audio/'):
        return 'audio'
    return 'document'


def _validate_media(content_type: str, size: int) -> Optional[str]:
    """Validate MIME type and size against WhatsApp Cloud API limits."""
    ct = (content_type or '').lower()
    if ct not in MEDIA_ALLOWED_MIME:
        return f'Unsupported media MIME type: {content_type}'
    limit = MEDIA_SIZE_LIMITS.get(_media_category(ct))
    if limit and size > limit:
        return f'{content_type} exceeds the {limit} byte limit for its category'
    return None


def _mask_media_url(url: str) -> str:
    """Drop the query string (temporary token) from a Meta media URL."""
    if not url:
        return url
    base = url.split('?', 1)[0]
    return base + ('?***' if '?' in url else '')


def _graph_media_multipart(phone_id: str, file_bytes: bytes, content_type: str, filename: str) -> Dict:
    """POST /{phone_id}/media as multipart/form-data. Returns Meta JSON ({id} or {error})."""
    token = _get_meta_token(phone_id=phone_id)
    app_secret = _get_app_secret(phone_id=phone_id)
    boundary = uuid.uuid4().hex
    parts = []
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(b'Content-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n')
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(f'Content-Disposition: form-data; name="type"\r\n\r\n{content_type}\r\n'.encode())
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    parts.append(f'Content-Type: {content_type}\r\n\r\n'.encode())
    parts.append(file_bytes)
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    multipart_body = b''.join(parts)

    url = f'{GRAPH_BASE}/{phone_id}/media'
    if app_secret:
        proof = hmac.new(app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256).hexdigest()
        url += '?' + urllib.parse.urlencode({'appsecret_proof': proof})
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    }
    req = urllib.request.Request(url, data=multipart_body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.error(f'Media upload error {e.code}: {error_body}')
        try:
            return {'error': json.loads(error_body)}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {'error': {'message': error_body, 'code': e.code}}


# Buckets `_upload_media` may read from, by name. An ALLOWLIST rather than an open
# `s3Bucket` parameter on purpose: this function is invoked by several other Lambdas,
# so honouring an arbitrary caller-supplied bucket would hand every one of them a
# read-any-object primitive. Adding a bucket here is a deliberate act; passing one is
# not enough.
MEDIA_SOURCE_BUCKETS = {
    MEDIA_BUCKET,
    os.environ.get('SECURE_FILES_BUCKET', media_paths.BUCKET),
}


def _upload_media(body: Dict) -> Dict:
    """Upload media for sending.

    Body: { phoneId, fileData(base64) | s3Key [+ s3Bucket], contentType, filename }

    Prefer `s3Key`. `fileData` has to fit inside a synchronous Lambda invoke payload
    and base64 inflates bytes by about a third, so it caps out near 4.4MB - which
    would make the 100MB document limit in MEDIA_LIMITS a fiction for any caller
    whose file is already in S3.
    """
    phone_id = body.get('phoneId') or PHONE1_META_ID
    content_type = body.get('contentType', 'application/octet-stream')
    filename = body.get('filename', 'upload.bin')
    file_data_b64 = body.get('fileData')
    s3_key = body.get('s3Key')
    s3_bucket = body.get('s3Bucket') or MEDIA_BUCKET

    if not file_data_b64 and not s3_key:
        return _resp(400, {'error': 'fileData (base64) or s3Key required'})
    if s3_key and s3_bucket not in MEDIA_SOURCE_BUCKETS:
        return _resp(400, {'error': 's3Bucket is not an allowed media source'})
    try:
        if s3_key:
            obj = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            file_bytes = obj['Body'].read()
            content_type = obj.get('ContentType', content_type)
        else:
            file_bytes = base64.b64decode(file_data_b64)
    except Exception as e:
        return _resp(400, {'error': f'Failed to read media bytes: {e}'})

    err = _validate_media(content_type, len(file_bytes))
    if err:
        return _resp(400, {'error': err})

    result = _graph_media_multipart(phone_id, file_bytes, content_type, filename)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'mediaId': result.get('id', ''), 'contentType': content_type, 'size': len(file_bytes)})


def _get_media(media_id: str, phone_id: str, params: Dict) -> Dict:
    """GET /{media_id} → media metadata with masked URL + expiry. download=true stages to S3."""
    if not media_id:
        return _resp(400, {'error': 'mediaId required'})
    info = _graph_api(media_id, phone_id=phone_id or None)
    if 'error' in info:
        return _resp(400, info)
    media_url = info.get('url', '')
    result = {
        'mediaId': media_id,
        'mimeType': info.get('mime_type', ''),
        'fileSize': info.get('file_size', 0),
        'sha256': info.get('sha256', ''),
        'url': _mask_media_url(media_url),
        'urlExpiresAt': int(time.time()) + MEDIA_URL_TTL_SECONDS,
        'urlExpiresInSeconds': MEDIA_URL_TTL_SECONDS,
    }
    if (params.get('download', 'false') or '').lower() == 'true' and media_url:
        try:
            token = _get_meta_token(phone_id=phone_id or None)
            req = urllib.request.Request(media_url, headers={'Authorization': f'Bearer {token}'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                media_bytes = resp.read()
            s3_key = f'{MEDIA_DOWNLOAD_PREFIX}wecare-digital-{media_id}'
            s3_client.put_object(Bucket=MEDIA_BUCKET, Key=s3_key, Body=media_bytes,
                                 ContentType=info.get('mime_type', 'application/octet-stream'))
            result['s3Key'] = s3_key
            result['downloadUrl'] = s3_client.generate_presigned_url(
                'get_object', Params={'Bucket': MEDIA_BUCKET, 'Key': s3_key}, ExpiresIn=3600)
        except Exception as e:
            logger.error(f'Media download failed for {media_id}: {e}')
            result['downloadError'] = str(e)
    return _resp(200, result)


def _delete_media(media_id: str, phone_id: str) -> Dict:
    """DELETE /{media_id}."""
    if not media_id:
        return _resp(400, {'error': 'mediaId required'})
    result = _graph_api(media_id, method='DELETE', phone_id=phone_id or None)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': result.get('success', True), 'mediaId': media_id})


def _resumable_session(body: Dict) -> Dict:
    """Start a resumable upload session. Body: { fileName, fileType, fileLength }."""
    file_type = body.get('fileType', 'application/octet-stream')
    file_length = body.get('fileLength')
    file_name = body.get('fileName', 'upload.bin')
    if file_length is None:
        return _resp(400, {'error': 'fileLength (bytes) required'})
    try:
        file_length = int(file_length)
    except (ValueError, TypeError):
        return _resp(400, {'error': 'fileLength must be an integer'})
    err = _validate_media(file_type, file_length)
    if err:
        return _resp(400, {'error': err})

    session_id = uuid.uuid4().hex
    manifest = {
        'sessionId': session_id,
        'fileName': file_name,
        'fileType': file_type,
        'fileLength': file_length,
        'received': 0,
        'createdAt': int(time.time()),
    }
    s3_client.put_object(
        Bucket=MEDIA_BUCKET, Key=f'{MEDIA_RESUMABLE_PREFIX}{session_id}.json',
        Body=json.dumps(manifest).encode('utf-8'), ContentType='application/json')
    return _resp(200, {'sessionId': session_id, 'received': 0, 'fileLength': file_length})


def _resumable_load_manifest(session_id: str) -> Optional[Dict]:
    try:
        obj = s3_client.get_object(Bucket=MEDIA_BUCKET, Key=f'{MEDIA_RESUMABLE_PREFIX}{session_id}.json')
        return json.loads(obj['Body'].read().decode('utf-8'))
    except Exception:
        return None


def _resumable_chunk(session_id: str, body: Dict) -> Dict:
    """Append a chunk. Body: { data (base64) }. Chunks are appended in order."""
    manifest = _resumable_load_manifest(session_id)
    if not manifest:
        return _resp(404, {'error': 'Unknown or expired session'})
    data_b64 = body.get('data')
    if not data_b64:
        return _resp(400, {'error': 'data (base64 chunk) required'})
    try:
        chunk = base64.b64decode(data_b64)
    except Exception as e:
        return _resp(400, {'error': f'Invalid base64 chunk: {e}'})

    bin_key = f'{MEDIA_RESUMABLE_PREFIX}{session_id}.bin'
    existing = b''
    if manifest['received'] > 0:
        try:
            existing = s3_client.get_object(Bucket=MEDIA_BUCKET, Key=bin_key)['Body'].read()
        except Exception:
            existing = b''
    combined = existing + chunk
    if len(combined) > manifest['fileLength']:
        return _resp(400, {'error': 'Received more bytes than declared fileLength'})
    s3_client.put_object(Bucket=MEDIA_BUCKET, Key=bin_key, Body=combined,
                         ContentType=manifest['fileType'])
    manifest['received'] = len(combined)
    s3_client.put_object(Bucket=MEDIA_BUCKET, Key=f'{MEDIA_RESUMABLE_PREFIX}{session_id}.json',
                         Body=json.dumps(manifest).encode('utf-8'), ContentType='application/json')
    return _resp(200, {
        'sessionId': session_id,
        'received': manifest['received'],
        'fileLength': manifest['fileLength'],
        'complete': manifest['received'] >= manifest['fileLength'],
    })


def _meta_resumable_upload(file_bytes: bytes, file_name: str, file_type: str) -> Dict:
    """Meta App-level Resumable Upload → returns {h: handle} for template header media."""
    token = _get_meta_token()
    # Step 1: open a session on the app.
    #
    # appsecret_proof is REQUIRED here and was missing, so this whole path could never
    # have succeeded - Meta answers:
    #   "API calls from the server require an appsecret_proof argument" (code 100)
    # Every other Graph call in this file computes it; this one did not, which is why
    # no template with a media header could ever be created through this route.
    open_params = {
        'file_name': file_name, 'file_length': len(file_bytes), 'file_type': file_type,
        'access_token': token,
    }
    app_secret = _get_app_secret()
    if app_secret:
        open_params['appsecret_proof'] = hmac.new(
            app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256
        ).hexdigest()
    params = urllib.parse.urlencode(open_params)
    open_url = f'{GRAPH_BASE}/{META_APP_ID}/uploads?{params}'
    try:
        req = urllib.request.Request(open_url, data=b'', method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            session = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': {'message': e.read().decode('utf-8') if e.fp else str(e), 'code': e.code}}
    upload_session_id = session.get('id', '')
    if not upload_session_id:
        return {'error': {'message': 'No upload session id returned', 'raw': session}}

    # Step 2: upload the bytes at offset 0.
    up_url = f'{GRAPH_BASE}/{upload_session_id}'
    headers = {'Authorization': f'OAuth {token}', 'file_offset': '0'}
    try:
        req = urllib.request.Request(up_url, data=file_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': {'message': e.read().decode('utf-8') if e.fp else str(e), 'code': e.code}}


def _resumable_finish(session_id: str, body: Dict) -> Dict:
    """Assemble the session and upload.

    target='handle' (default) → Meta resumable upload, returns header handle (for templates).
    target='media'            → upload to phone media endpoint, returns mediaId.
    """
    manifest = _resumable_load_manifest(session_id)
    if not manifest:
        return _resp(404, {'error': 'Unknown or expired session'})
    if manifest['received'] < manifest['fileLength']:
        return _resp(400, {
            'error': 'Upload incomplete',
            'received': manifest['received'],
            'fileLength': manifest['fileLength'],
        })
    bin_key = f'{MEDIA_RESUMABLE_PREFIX}{session_id}.bin'
    try:
        file_bytes = s3_client.get_object(Bucket=MEDIA_BUCKET, Key=bin_key)['Body'].read()
    except Exception as e:
        return _resp(400, {'error': f'Failed to read assembled bytes: {e}'})

    target = (body.get('target') or 'handle').lower()
    if target == 'media':
        phone_id = body.get('phoneId') or PHONE1_META_ID
        result = _graph_media_multipart(phone_id, file_bytes, manifest['fileType'], manifest['fileName'])
        if 'error' in result:
            return _resp(400, result)
        out = {'mediaId': result.get('id', '')}
    else:
        result = _meta_resumable_upload(file_bytes, manifest['fileName'], manifest['fileType'])
        if 'error' in result:
            return _resp(400, result)
        out = {'headerHandle': result.get('h', '')}

    # Best-effort cleanup of session artifacts.
    for key in (bin_key, f'{MEDIA_RESUMABLE_PREFIX}{session_id}.json'):
        try:
            s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=key)
        except Exception:
            pass
    out['sessionId'] = session_id
    return _resp(200, out)


# ============================================================================
# SEND TEST MESSAGES (Part 4 E)
#   POST /wa-business/messages/send/text        → text
#   POST /wa-business/messages/send/template    → template (incl. flow template)
#   POST /wa-business/messages/send/media       → image/video/document/audio/sticker
#   POST /wa-business/messages/send/interactive → REMOVED 2026-10-02, answers 410
#   POST /wa-business/messages/send/flow        → flow message by id or name (draft/published)
# All post to {phone_id}/messages via the Graph API.
# ============================================================================
def _send_message(phone_id: str, message: Dict, body: Dict = None) -> Dict:
    """POST a fully-formed message to {phone_id}/messages and normalize the response.

    Destination: pass `body` to resolve `to` (phone) and/or `recipient` (BSUID or
    parent BSUID) per Meta's BSUID API. If both are given, Meta uses `to`.
    """
    message.setdefault('messaging_product', 'whatsapp')
    message.setdefault('recipient_type', 'individual')
    if body is not None:
        to = (body.get('to') or '').strip()
        recipient = (body.get('recipient') or '').strip()  # BSUID / parent BSUID
        if not to and not recipient:
            return _resp(400, {'error': 'to (phone number) or recipient (BSUID) is required'})
        if to:
            message['to'] = to
        if recipient:
            message['recipient'] = recipient
    result = _graph_api(f'{phone_id}/messages', method='POST', payload=message, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    msg_id = ''
    msgs = result.get('messages', []) if isinstance(result, dict) else []
    if msgs:
        msg_id = msgs[0].get('id', '')
    contacts = result.get('contacts', []) if isinstance(result, dict) else []
    user_id = contacts[0].get('user_id', '') if contacts else ''
    return _resp(200, {'success': True, 'messageId': msg_id, 'to': message.get('to', ''), 'recipient': message.get('recipient', ''), 'userId': user_id})


def _send_text(body: Dict) -> Dict:
    text = body.get('text') or body.get('body')
    if not text:
        return _resp(400, {'error': 'text is required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    message = {'type': 'text', 'text': {'body': text, 'preview_url': bool(body.get('previewUrl', False))}}
    return _send_message(phone_id, message, body)


def _send_template_msg(body: Dict) -> Dict:
    name = body.get('templateName') or body.get('name')
    if not name:
        return _resp(400, {'error': 'templateName is required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    template = {'name': name, 'language': {'code': body.get('language', 'en')}}
    if body.get('components'):
        template['components'] = body['components']
    return _send_message(phone_id, {'type': 'template', 'template': template}, body)


def _send_media_msg(body: Dict) -> Dict:
    media_type = (body.get('mediaType') or body.get('type') or '').lower()
    if media_type not in ('image', 'video', 'document', 'audio', 'sticker'):
        return _resp(400, {'error': 'a valid mediaType (image|video|document|audio|sticker) is required'})
    media_id = body.get('mediaId')
    media_url = body.get('mediaUrl') or body.get('link')
    if not media_id and not media_url:
        return _resp(400, {'error': 'mediaId or mediaUrl required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    obj: Dict[str, Any] = {}
    if media_id:
        obj['id'] = media_id
    else:
        obj['link'] = media_url
    if body.get('caption') and media_type in ('image', 'video', 'document'):
        obj['caption'] = body['caption']
    if body.get('filename') and media_type == 'document':
        obj['filename'] = body['filename']
    return _send_message(phone_id, {'type': media_type, media_type: obj}, body)


def _send_request_contact_info(body: Dict) -> Dict:
    """Send a request_contact_info interactive message to collect a user's phone
    number (useful for username-adopters whose phone is hidden). BSUID-friendly."""
    phone_id = body.get('phoneId') or PHONE1_META_ID
    interactive = {
        'type': 'request_contact_info',
        'body': {'text': body.get('bodyText', 'Please share your contact info so we can assist you.')},
        'action': {'name': 'request_contact_info'},
    }
    return _send_message(phone_id, {'type': 'interactive', 'interactive': interactive}, body)


def _send_flow_msg(body: Dict) -> Dict:
    """Send an interactive Flow message by flow_id or flow_name.

    Body: { to|recipient, flowId|flowName, flowToken?, flowCta, bodyText, headerText?, footerText?,
            screen, flowAction(navigate|data_exchange), flowActionPayload?, mode(draft|published), phoneId }
    """
    flow_id = body.get('flowId')
    flow_name = body.get('flowName')
    if not flow_id and not flow_name:
        return _resp(400, {'error': 'one of flowId/flowName is required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID

    parameters: Dict[str, Any] = {
        'flow_message_version': '3',
        'flow_token': body.get('flowToken') or f'test-{uuid.uuid4().hex[:12]}',
        'flow_cta': body.get('flowCta', 'Open'),
        'flow_action': body.get('flowAction', 'navigate'),
    }
    if flow_id:
        parameters['flow_id'] = flow_id
    else:
        parameters['flow_name'] = flow_name
    if (body.get('mode') or '').lower() == 'draft':
        parameters['mode'] = 'draft'
    if parameters['flow_action'] == 'navigate':
        parameters['flow_action_payload'] = body.get('flowActionPayload') or {
            'screen': body.get('screen', 'WELCOME'),
            'data': body.get('data', {}),
        }

    interactive: Dict[str, Any] = {
        'type': 'flow',
        'body': {'text': body.get('bodyText', 'Tap below to continue')},
        'action': {'name': 'flow', 'parameters': parameters},
    }
    if body.get('headerText'):
        interactive['header'] = {'type': 'text', 'text': body['headerText']}
    if body.get('footerText'):
        interactive['footer'] = {'text': body['footerText']}

    return _send_message(phone_id, {'type': 'interactive', 'interactive': interactive}, body)


def _send_contacts_msg(body: Dict) -> Dict:
    contacts = body.get('contacts')
    if not contacts:
        return _resp(400, {'error': 'contacts[] is required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    return _send_message(phone_id, {'type': 'contacts', 'contacts': contacts}, body)


def _send_location_msg(body: Dict) -> Dict:
    lat = body.get('latitude')
    lng = body.get('longitude')
    if lat is None or lng is None:
        return _resp(400, {'error': 'latitude and longitude are required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    location: Dict[str, Any] = {'latitude': lat, 'longitude': lng}
    if body.get('name'):
        location['name'] = body['name']
    if body.get('address'):
        location['address'] = body['address']
    return _send_message(phone_id, {'type': 'location', 'location': location}, body)


_PRODUCT_CAROUSEL_MIN_CARDS = 2
_PRODUCT_CAROUSEL_MAX_CARDS = 10
# The action key that carries the cards. Unverified against a live send -- this is the
# single place to correct it, and the payload test reads the constant rather than a
# literal so a correction here does not touch the test.
_PRODUCT_CAROUSEL_ITEMS_KEY = 'product_carousel_items'


def _send_product_msg(body: Dict) -> Dict:
    """Single product (interactive 'product') or multi-product ('product_list').

    Precedence: carouselCards > catalogMessage|viewCatalog > sections > single
    product. The most specific body shape wins; a caller supplying two is served the
    most specific one, and the superseded shape is named in the product_carousel_built
    log line.
    """
    catalog_id = body.get('catalogId')
    if not catalog_id:
        return _resp(400, {'error': 'catalogId is required'})
    phone_id = body.get('phoneId') or PHONE1_META_ID
    sections = body.get('sections')
    cards = body.get('carouselCards') or body.get('cards')
    if cards:
        # A product carousel is a CATALOG PRESENTATION. It must never accept or emit an
        # order_details component, a payment configuration name or an amount -- pinned by
        # tests/test_product_carousel_send.py::test_carousel_carries_no_order_details.
        #
        # Which more-general shape this carousel is superseding, so an override is visible
        # in CloudWatch rather than inferred from the absence of a catalog_message.
        superseded = ('catalog_message' if (body.get('catalogMessage') or body.get('viewCatalog'))
                      else ('sections' if sections else ''))
        if not isinstance(cards, list):
            return _resp(400, {'error': 'carouselCards must be a list'})
        if not (_PRODUCT_CAROUSEL_MIN_CARDS <= len(cards) <= _PRODUCT_CAROUSEL_MAX_CARDS):
            return _resp(400, {'error': f'product_carousel needs {_PRODUCT_CAROUSEL_MIN_CARDS}-'
                                        f'{_PRODUCT_CAROUSEL_MAX_CARDS} cards'})
        items = []
        for i, c in enumerate(cards):
            rid = (c.get('productRetailerId') or c.get('product_retailer_id') or '') \
                if isinstance(c, dict) else str(c or '')
            if not rid:
                return _resp(400, {'error': f'card {i} is missing productRetailerId'})
            items.append({'product_retailer_id': str(rid)})
        body_text = body.get('bodyText')
        if not body_text:
            return _resp(400, {'error': 'bodyText is required for a product carousel'})
        interactive = {
            'type': 'product_carousel',
            'body': {'text': str(body_text)[:1024]},
            'action': {'catalog_id': catalog_id, _PRODUCT_CAROUSEL_ITEMS_KEY: items},
        }
        if body.get('headerText'):
            interactive['header'] = {'type': 'text', 'text': str(body['headerText'])[:60]}
        if body.get('footerText'):
            interactive['footer'] = {'text': str(body['footerText'])[:60]}
        logger.info(json.dumps({'event': 'product_carousel_built', 'catalogId': catalog_id,
                                'cardCount': len(items), 'supersededShape': superseded}))
        return _send_message(phone_id, {'type': 'interactive', 'interactive': interactive}, body)
    if body.get('catalogMessage') or body.get('viewCatalog'):
        # Full catalog message — opens the whole catalog with a "View catalog"
        # button so the customer browses ALL products, adds to cart, and checks out.
        interactive = {
            'type': 'catalog_message',
            'body': {'text': body.get('bodyText', 'Browse our catalog and add items to your cart.')},
            'action': {'name': 'catalog_message'},
        }
        thumb = body.get('productRetailerId') or body.get('thumbnailProductRetailerId')
        if thumb:
            interactive['action']['parameters'] = {'thumbnail_product_retailer_id': thumb}
        if body.get('footerText'):
            interactive['footer'] = {'text': body['footerText']}
        return _send_message(phone_id, {'type': 'interactive', 'interactive': interactive}, body)
    if sections:
        # Multi-product message
        interactive = {
            'type': 'product_list',
            'header': {'type': 'text', 'text': body.get('headerText', 'Products')},
            'body': {'text': body.get('bodyText', 'Browse our products')},
            'action': {'catalog_id': catalog_id, 'sections': sections},
        }
        if body.get('footerText'):
            interactive['footer'] = {'text': body['footerText']}
    else:
        retailer_id = body.get('productRetailerId')
        if not retailer_id:
            return _resp(400, {'error': 'productRetailerId required for a single product (or provide sections[] for multi-product)'})
        interactive = {
            'type': 'product',
            'body': {'text': body.get('bodyText', '')} if body.get('bodyText') else {'text': ' '},
            'action': {'catalog_id': catalog_id, 'product_retailer_id': retailer_id},
        }
        if not body.get('bodyText'):
            interactive.pop('body', None)
    return _send_message(phone_id, {'type': 'interactive', 'interactive': interactive}, body)


def _route_send_message(path: str, body: Dict) -> Dict:
    """Dispatch /messages/send/{type}."""
    if path.rstrip('/').endswith('/text'):
        return _send_text(body)
    if path.rstrip('/').endswith('/template'):
        return _send_template_msg(body)
    if path.rstrip('/').endswith('/media'):
        return _send_media_msg(body)
    if path.rstrip('/').endswith('/interactive'):
        # The generic interactive pass-through was deleted with every WhatsApp
        # menu on 2026-10-02. 410 rather than the 404 below, because the route
        # still exists - it was withdrawn, it is not unknown.
        return _resp(410, {'error': 'interactive messaging removed',
                           'detail': 'generic interactive sends were deleted on '
                                     '2026-10-02; use /text, /template, /media or /flow'})
    if path.rstrip('/').endswith('/flow'):
        return _send_flow_msg(body)
    if path.rstrip('/').endswith('/contacts'):
        return _send_contacts_msg(body)
    if path.rstrip('/').endswith('/location'):
        return _send_location_msg(body)
    if path.rstrip('/').endswith('/product') or path.rstrip('/').endswith('/products'):
        return _send_product_msg(body)
    if path.rstrip('/').endswith('/request-contact-info'):
        return _send_request_contact_info(body)
    return _resp(404, {'error': f'Unknown send path: {path}'})


# ============================================================================
# AI PROVIDER PRICING POLICY (table-driven markets + effective dates)
# Backed by DynamoDB so markets/dates are editable without code changes.
# Analytics pricing_category for AI-Provider traffic: AI_BOT
# Webhook pricing.category for these non-template messages: general_purpose_ai
# Rates are NOT hardcoded — import rate cards (CSV/PDF) separately.
# ============================================================================
AI_POLICY_TABLE = os.environ.get('AI_PROVIDER_POLICY_TABLE', 'stack-wecare-digital-AIProviderPolicyTable')
AI_ANALYTICS_PRICING_CATEGORY = 'AI_BOT'
AI_WEBHOOK_PRICING_CATEGORY = 'general_purpose_ai'


def _list_ai_policy_markets() -> Dict:
    """List all AI-Provider pricing-policy markets (country + effective date + active flag)."""
    try:
        table = dynamodb.Table(AI_POLICY_TABLE)
        items = []
        resp = table.scan()
        items.extend(resp.get('Items', []))
        while 'LastEvaluatedKey' in resp:
            resp = table.scan(ExclusiveStartKey=resp['LastEvaluatedKey'])
            items.extend(resp.get('Items', []))
        items.sort(key=lambda x: (not x.get('active', False), x.get('country', '')))
        return _resp(200, {
            'markets': items,
            'count': len(items),
            'activeCount': sum(1 for i in items if i.get('active')),
            'analyticsPricingCategory': AI_ANALYTICS_PRICING_CATEGORY,
            'webhookPricingCategory': AI_WEBHOOK_PRICING_CATEGORY,
            'note': 'Applies only to AI Providers per Meta ToS. Non-template messages to ACTIVE markets are billable. Rates are imported separately (CSV/PDF), not stored here.',
        })
    except Exception as e:
        return _resp(500, {'error': f'Failed to list AI policy markets: {e}'})


def _upsert_ai_policy_market(body: Dict) -> Dict:
    """Create/update a market. Body: { countryCode, country, effectiveDate, active, note }."""
    country_code = (body.get('countryCode') or '').strip()
    if not country_code:
        return _resp(400, {'error': 'countryCode is required (e.g. +55)'})
    if not country_code.startswith('+'):
        country_code = '+' + country_code.lstrip('+')
    item = {
        'countryCode': country_code,
        'country': (body.get('country') or '').strip(),
        'effectiveDate': (body.get('effectiveDate') or '').strip(),
        'active': bool(body.get('active', False)),
        'note': (body.get('note') or '').strip(),
        'updatedAt': int(time.time()),
    }
    try:
        dynamodb.Table(AI_POLICY_TABLE).put_item(Item=item)
        return _resp(200, {'success': True, 'market': item})
    except Exception as e:
        return _resp(500, {'error': f'Failed to save market: {e}'})


def _delete_ai_policy_market(country_code: str) -> Dict:
    """Delete a market by countryCode."""
    if not country_code:
        return _resp(400, {'error': 'countryCode is required'})
    if not country_code.startswith('+'):
        country_code = '+' + country_code.lstrip('+')
    try:
        dynamodb.Table(AI_POLICY_TABLE).delete_item(Key={'countryCode': country_code})
        return _resp(200, {'success': True})
    except Exception as e:
        return _resp(500, {'error': f'Failed to delete market: {e}'})


# ============================================================================
# GROUPS
# ============================================================================
def _list_groups(waba_id: str, phone_id: str = None) -> Dict:
    """List groups. Uses phone_id if provided, falls back to WABA phone mapping."""
    # Groups API uses phone_number_id, not waba_id
    if not phone_id:
        # Map WABA to its primary phone
        waba_phone_map = {
            WABA1_ID: PHONE1_META_ID,
            WABA2_ID: PHONE2_META_ID,
        }
        phone_id = waba_phone_map.get(waba_id, '')
    if not phone_id:
        return _resp(400, {'error': 'Could not resolve phone for WABA'})
    result = _graph_api(f'{phone_id}/groups', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'groups': result.get('data', [])})

def _get_group(group_id: str) -> Dict:
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    result = _graph_api(group_id, params={
        'fields': 'id,subject,description,creation_timestamp,participants,total_participant_count,join_approval_mode,suspended,messaging_permission,member_visibility'
    })
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'group': result})

def _create_group(phone_id: str, body: Dict) -> Dict:
    if not phone_id:
        return _resp(400, {'error': 'phoneId required'})
    subject = body.get('subject')
    if not subject:
        return _resp(400, {'error': 'subject required'})
    payload = {'subject': subject, 'messaging_product': 'whatsapp'}
    if body.get('description'):
        payload['description'] = body['description']
    if body.get('participants'):
        payload['participants'] = body['participants']
    if body.get('join_approval_mode'):
        payload['join_approval_mode'] = body['join_approval_mode']
    result = _graph_api(f'{phone_id}/groups', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'group': result})

def _update_group(group_id: str, body: Dict) -> Dict:
    """Update group settings: subject, description, join_approval_mode, messaging_permission, member_visibility."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    payload = {'messaging_product': 'whatsapp'}
    if body.get('subject'):
        payload['subject'] = body['subject']
    if body.get('description'):
        payload['description'] = body['description']
    # Privacy: who can send messages — 'all' (everyone) or 'admins' (admin-only)
    if body.get('messaging_permission'):
        payload['messaging_permission'] = body['messaging_permission']
    # Privacy: whether non-admin members can see other participants
    if body.get('member_visibility'):
        payload['member_visibility'] = body['member_visibility']
    # Join approval mode
    if body.get('join_approval_mode'):
        payload['join_approval_mode'] = body['join_approval_mode']
    result = _graph_api(group_id, method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

def _delete_group(group_id: str) -> Dict:
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    result = _graph_api(group_id, method='DELETE')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})

def _manage_group_participants(group_id: str, body: Dict) -> Dict:
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    action = body.get('action', 'add')  # add or remove
    participants = body.get('participants', [])
    if not participants:
        return _resp(400, {'error': 'participants required'})
    payload = {'messaging_product': 'whatsapp', 'participants': participants}
    endpoint = f'{group_id}/participants'
    method = 'POST' if action == 'add' else 'DELETE'
    result = _graph_api(endpoint, method=method, payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'action': action, 'count': len(participants)})

def _send_group_message(phone_id: str, group_id: str, body: Dict) -> Dict:
    """Send message to a group. Supports text, image, video, document, audio, template.
    Body: { content: str (for text), type: 'text'|'image'|'video'|'document'|'audio'|'template',
            mediaUrl/mediaId: str, caption: str, templateName: str, templateLanguage: str, templateComponents: [] }
    """
    if not phone_id or not group_id:
        return _resp(400, {'error': 'phoneId and groupId required'})

    msg_type = body.get('type', 'text')
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'group',
        'to': group_id,
        'type': msg_type,
    }

    if msg_type == 'text':
        content = body.get('content', '')
        if not content:
            return _resp(400, {'error': 'content required for text messages'})
        payload['text'] = {'body': content, 'preview_url': body.get('preview_url', True)}

    elif msg_type in ('image', 'video', 'document', 'audio'):
        media_obj = {}
        if body.get('mediaId'):
            media_obj['id'] = body['mediaId']
        elif body.get('mediaUrl'):
            media_obj['link'] = body['mediaUrl']
        else:
            return _resp(400, {'error': f'mediaId or mediaUrl required for {msg_type}'})
        if body.get('caption') and msg_type in ('image', 'video', 'document'):
            media_obj['caption'] = body['caption']
        if body.get('filename') and msg_type == 'document':
            media_obj['filename'] = body['filename']
        payload[msg_type] = media_obj

    elif msg_type == 'template':
        template_name = body.get('templateName', '')
        template_lang = body.get('templateLanguage', 'en')
        if not template_name:
            return _resp(400, {'error': 'templateName required for template messages'})
        template_obj = {'name': template_name, 'language': {'code': template_lang}}
        if body.get('templateComponents'):
            template_obj['components'] = body['templateComponents']
        payload['template'] = template_obj

    else:
        return _resp(400, {'error': f'Unsupported message type: {msg_type}. Use text, image, video, document, audio, or template.'})

    result = _graph_api(f'{phone_id}/messages', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    msg_id = ''
    msgs = result.get('messages', [])
    if msgs:
        msg_id = msgs[0].get('id', '')
    return _resp(200, {'success': True, 'messageId': msg_id, 'type': msg_type})

def _set_group_image(group_id: str, image_url: str) -> Dict:
    """Set group profile picture from a URL. Downloads the image then uploads via multipart form."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    if not image_url:
        return _resp(400, {'error': 'imageUrl required'})
    # Download image
    try:
        img_req = urllib.request.Request(image_url)
        with urllib.request.urlopen(img_req, timeout=10) as img_resp:
            image_bytes = img_resp.read()
    except Exception as e:
        return _resp(400, {'error': f'Failed to download image: {str(e)}'})
    # Determine content type
    ct = 'image/png' if image_url.lower().endswith('.png') else 'image/jpeg'
    ext = 'png' if 'png' in ct else 'jpg'
    # Upload via multipart
    token = _get_meta_token()
    app_secret = _get_app_secret()
    proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest() if app_secret else ''
    url = f'{GRAPH_BASE}/{group_id}?appsecret_proof={proof}'
    boundary = '----WecareGroupImage'
    body = b''
    body += f'--{boundary}\r\n'.encode()
    body += b'Content-Disposition: form-data; name="messaging_product"\r\n\r\n'
    body += b'whatsapp\r\n'
    body += f'--{boundary}\r\n'.encode()
    body += f'Content-Disposition: form-data; name="file"; filename="group.{ext}"\r\n'.encode()
    body += f'Content-Type: {ct}\r\n\r\n'.encode()
    body += image_bytes
    body += b'\r\n'
    body += f'--{boundary}--\r\n'.encode()
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        return _resp(200, {'success': True, 'result': result})
    except urllib.error.HTTPError as e:
        err = e.read().decode() if e.fp else str(e)
        logger.error(f'Group image upload error: {err}')
        try:
            return _resp(400, json.loads(err))
        except:
            return _resp(400, {'error': err})

def _get_group_invite_link(group_id: str) -> Dict:
    """Get the current invite link for a group."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    result = _graph_api(f'{group_id}/invite_link')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'invite_link': result.get('invite_link', '')})

def _reset_group_invite_link(group_id: str) -> Dict:
    """Reset (regenerate) the invite link for a group. Previous links become invalid."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    result = _graph_api(f'{group_id}/invite_link', method='POST', payload={'messaging_product': 'whatsapp'})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'invite_link': result.get('invite_link', '')})

def _get_group_join_requests(group_id: str) -> Dict:
    """Get pending join requests for a group (when join_approval_mode=approval_required)."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    result = _graph_api(f'{group_id}/join_requests')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'join_requests': result.get('data', [])})

def _approve_group_join_requests(group_id: str, body: Dict) -> Dict:
    """Approve pending join requests."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    join_requests = body.get('join_requests', [])
    if not join_requests:
        return _resp(400, {'error': 'join_requests (array of IDs) required'})
    payload = {'messaging_product': 'whatsapp', 'join_requests': join_requests}
    result = _graph_api(f'{group_id}/join_requests', method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, result)

def _reject_group_join_requests(group_id: str, body: Dict) -> Dict:
    """Reject pending join requests."""
    if not group_id:
        return _resp(400, {'error': 'groupId required'})
    join_requests = body.get('join_requests', [])
    if not join_requests:
        return _resp(400, {'error': 'join_requests (array of IDs) required'})
    payload = {'messaging_product': 'whatsapp', 'join_requests': join_requests}
    result = _graph_api(f'{group_id}/join_requests', method='DELETE', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, result)

# ============================================================================
# CALLING SETTINGS (Enable/Disable calling on a phone number)
# ============================================================================
def _get_calling_settings(phone_id: str) -> Dict:
    """Get current calling settings for a phone number. SIP password is REDACTED.

    include_sip_credentials=true makes Meta return the SIP user password. This
    endpoint used to pass that straight through to the caller, so every request
    put a live SIP trunk credential into the response body — and from there into
    browser devtools, any intermediate log, and (on 2026-09-19) a session
    transcript. Nothing in the frontend reads the field; a repo-wide search for
    sip_user_password / sipUserPassword found no consumer outside this function.

    The password is replaced with a presence flag and a truncated SHA-256
    fingerprint, which is enough to confirm two systems hold the same string
    without disclosing it. If a human genuinely needs the value (to configure a
    PBX or a SIP trunk), read it from WhatsApp Manager or call the Graph endpoint
    directly with the WABA token — deliberately not through this API.
    """
    result = _graph_api(f'{phone_id}/settings', params={
        'fields': 'calling',
        'include_sip_credentials': 'true',
    }, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'settings': _redact_sip_credentials(result)})


def _redact_sip_credentials(payload: Any) -> Any:
    """Replace every sip_user_password with a presence flag + fingerprint.

    Walks the whole structure rather than indexing a fixed path, because Meta
    returns the servers list nested under calling.sip.servers[] and has changed
    that shape before. Returns a copy; the input is not mutated.
    """
    import copy as _copy
    import hashlib as _hashlib

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: Dict[str, Any] = {}
            for key, value in node.items():
                if key == 'sip_user_password':
                    secret = str(value or '')
                    out['sip_user_password_set'] = bool(secret)
                    if secret:
                        out['sip_user_password_fingerprint'] = (
                            'sha256:' + _hashlib.sha256(secret.encode()).hexdigest()[:12]
                        )
                    continue
                out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(_copy.deepcopy(payload))


def _validate_call_hours(call_hours: Dict) -> Optional[str]:
    """Validate call_hours per Meta Calling API rules (Configure Call Settings doc).
    Returns an error string if invalid, or None if valid.
    Rules:
      - timezone required when enabled
      - weekly_operating_hours cannot be empty when enabled
      - times must be HHMM (e.g. 0900); open_time < close_time
      - max 2 entries per day_of_week; no overlapping schedule per day
      - holiday_schedule dates must be valid YYYY-MM-DD and not in the past
    """
    import re as _re
    from datetime import datetime as _dt, timezone as _tz
    if not isinstance(call_hours, dict):
        return 'call_hours must be an object'

    status = (call_hours.get('status') or '').upper()
    tz = call_hours.get('timezone_id') or call_hours.get('timezone')
    if status == 'ENABLED' and not tz:
        return 'call_hours.timezone_id is required when call hours are enabled'

    weekly = call_hours.get('weekly_operating_hours')
    if status == 'ENABLED' and not weekly:
        return 'weekly_operating_hours in call_hours cannot be empty'

    if weekly is not None:
        if not isinstance(weekly, list):
            return 'weekly_operating_hours must be an array'
        per_day: Dict[str, list] = {}
        for slot in weekly:
            if not isinstance(slot, dict):
                return 'Each weekly_operating_hours entry must be an object'
            day = (slot.get('day_of_week') or '').upper()
            if not day:
                return 'Each weekly_operating_hours entry requires day_of_week'
            open_t = str(slot.get('open_time', ''))
            close_t = str(slot.get('close_time', ''))
            if not _re.fullmatch(r'\d{4}', open_t) or not _re.fullmatch(r'\d{4}', close_t):
                return f'open_time/close_time must be HHMM (e.g. 0900) for {day}'
            if int(open_t) >= int(close_t):
                return f'open_time must be earlier than close_time for {day}'
            per_day.setdefault(day, []).append((int(open_t), int(close_t)))
        for day, slots in per_day.items():
            if len(slots) > 2:
                return f'More than 2 entries not allowed in weekly_operating_hours for {day}'
            ordered = sorted(slots)
            for i in range(1, len(ordered)):
                if ordered[i][0] < ordered[i - 1][1]:
                    return f'Overlapping schedule in call_hours is not allowed for {day}'

    holidays = call_hours.get('holiday_schedule')
    if holidays is not None:
        if not isinstance(holidays, list):
            return 'holiday_schedule must be an array'
        today = _dt.now(_tz.utc).date()
        for h in holidays:
            date_str = (h or {}).get('date', '') if isinstance(h, dict) else ''
            try:
                d = _dt.strptime(date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return f'Invalid date format in holiday_schedule for call_hours: {date_str} (expected YYYY-MM-DD)'
            if d < today:
                return f'Holiday given in call_hours is a past date: {date_str}'
    return None


def _update_calling_settings(phone_id: str, body: Dict) -> Dict:
    """
    Enable or update calling settings on a phone number.
    Supports full Meta Calling API settings including SIP configuration.
    Body: {
      callIconVisibility: 'default' | 'disable_all',
      restrictToCountries: ['IN', 'AE'],
      callIcons: ['IN','AE'] | { restrict_to_user_countries: [...] },
      audioCodecs: ['PCMA','PCMU'],   # G.711 codecs (Opus is always default)
      callHours: { status, timezone_id, weekly_operating_hours: [{day_of_week, open_time, close_time}], holiday_schedule },
      voicemail: { status, triggers, audio, timeout_seconds },
      callbackRequest: { enabled: bool, bodyText: str },
      sip: { status: 'ENABLED'|'DISABLED', servers: [{ hostname, port?, request_uri_user_params? }] },
      srtpKeyExchangeProtocol: 'DTLS' | 'SDES',
      status: 'ENABLED' | 'DISABLED',
      callbackPermissionStatus: 'ENABLED' | 'DISABLED',
    }
    """
    calling: Dict = {}

    # Basic calling settings
    visibility = body.get('callIconVisibility')
    if visibility:
        calling['call_icon_visibility'] = visibility

    status = body.get('status')
    if status:
        calling['status'] = status

    callback_perm = body.get('callbackPermissionStatus')
    if callback_perm:
        calling['callback_permission_status'] = callback_perm

    countries = body.get('restrictToCountries')
    if countries:
        calling['restrict_to_user_countries'] = countries

    # call_icons: per Meta doc, restrict which countries see the call icon.
    # Accept either a full object or a list of country codes.
    call_icons = body.get('callIcons')
    if call_icons is not None:
        if isinstance(call_icons, list):
            calling['call_icons'] = {'restrict_to_user_countries': call_icons}
        elif isinstance(call_icons, dict):
            calling['call_icons'] = call_icons

    # Audio codecs: Opus is default. Optionally enable G.711 (PCMA/PCMU) for
    # interoperability with legacy telephony / PSTN gateways.
    audio_codecs = body.get('audioCodecs') or body.get('additionalCodecs')
    if audio_codecs:
        valid = [c.upper() for c in audio_codecs if str(c).upper() in ('PCMA', 'PCMU')]
        if valid:
            calling['audio'] = {'additional_codecs': valid}

    call_hours = body.get('callHours') or body.get('call_hours')
    if call_hours:
        err = _validate_call_hours(call_hours)
        if err:
            return _resp(400, {'error': err})
        calling['call_hours'] = call_hours

    # Voicemail config (advanced / not yet in the public Calling API reference as of
    # Nov 2025 — passed through to Meta as-is when provided). Structural check only:
    # must be a JSON object. No field-level rules are invented here.
    voicemail = body.get('voicemail')
    if voicemail is not None:
        if not isinstance(voicemail, dict):
            return _resp(400, {'error': 'voicemail must be a JSON object'})
        if voicemail:
            calling['voicemail'] = voicemail

    callback = body.get('callbackRequest')
    if callback:
        calling['callback_request'] = callback

    # SIP configuration (per Meta SIP Configuration Guide)
    sip = body.get('sip')
    if sip:
        sip_config: Dict = {}
        if 'status' in sip:
            sip_config['status'] = sip['status']  # ENABLED or DISABLED
        if 'servers' in sip:
            sip_config['servers'] = sip['servers']  # [{ hostname, port?, request_uri_user_params? }]
        if sip_config:
            calling['sip'] = sip_config

    # SRTP key exchange protocol (DTLS default, SDES for shorter call setup)
    srtp = body.get('srtpKeyExchangeProtocol')
    if srtp and srtp in ('DTLS', 'SDES'):
        calling['srtp_key_exchange_protocol'] = srtp

    if not calling:
        return _resp(400, {'error': 'No calling settings provided'})

    result = _graph_api(f'{phone_id}/settings', method='POST', payload={
        'calling': calling
    }, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'calling': calling})


# ============================================================================
# PHONE SETTINGS
# ============================================================================
def _get_phone_settings(phone_id: str) -> Dict:
    result = _graph_api(phone_id, params={'fields': 'display_phone_number,verified_name,quality_rating,messaging_limit_tier,is_official_business_account,name_status'}, phone_id=phone_id)
    if 'error' in result:
        # Retry once
        logger.warning(f'Phone settings fetch failed for {phone_id}, retrying: {result}')
        time.sleep(1)
        result = _graph_api(phone_id, params={'fields': 'display_phone_number,verified_name,quality_rating,messaging_limit_tier,is_official_business_account,name_status'}, phone_id=phone_id)
        if 'error' in result:
            logger.error(f'Phone settings fetch failed after retry for {phone_id}: {result}')
            return _resp(200, {'settings': None, 'error': str(result.get('error', '')), 'phoneId': phone_id})
    return _resp(200, {'settings': result})


# Fields restricted to the set already proven to resolve on this account -- the same
# selection _get_phone_settings, meta-analytics:192 and waba-management:454 already
# request. Nothing speculative is added here: an unknown field name makes Graph reject
# the whole request, taking the fields that do work with it.
_OBA_PHONE_FIELDS = ('id,display_phone_number,verified_name,quality_rating,'
                     'code_verification_status,is_official_business_account,name_status')


def _get_oba_status(waba_id: str) -> Dict:
    """GET /{waba_id}/phone_numbers -- Official Business Account state per number,
    rolled up per WABA. The per-phone boolean is already read in three other places;
    this is the one route that NAMES it, so a dashboard can answer "are we an OBA?"
    without an operator reading a phone-settings blob.

    Read-only. Nothing here requests, applies for or mutates OBA status: the green tick
    is granted by a Meta review initiated from Business Suite and there is no API for it.
    """
    result = _graph_api(f'{waba_id}/phone_numbers',
                        params={'fields': _OBA_PHONE_FIELDS}, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    phones = []
    for p in (result.get('data') or []):
        phones.append({
            'phoneId': str(p.get('id') or ''),
            'displayPhoneNumber': p.get('display_phone_number', ''),
            'verifiedName': p.get('verified_name', ''),
            'qualityRating': p.get('quality_rating', ''),
            'codeVerificationStatus': p.get('code_verification_status', ''),
            'nameStatus': p.get('name_status', ''),
            'isOfficialBusinessAccount': bool(p.get('is_official_business_account', False)),
        })
    # Four-valued, deliberately. UNKNOWN is NOT NOT_OFFICIAL: an empty data[] means the
    # read did not tell us, which is a different fact. PARTIAL exists because two WABAs
    # with four numbers between them can legitimately be half-verified, and a boolean
    # would have to pick a lie.
    if not phones:
        rollup = 'UNKNOWN'
    elif all(p['isOfficialBusinessAccount'] for p in phones):
        rollup = 'OFFICIAL'
    elif any(p['isOfficialBusinessAccount'] for p in phones):
        rollup = 'PARTIAL'
    else:
        rollup = 'NOT_OFFICIAL'
    logger.info(json.dumps({'event': 'oba_status_read', 'wabaId': waba_id,
                            'obaStatus': rollup, 'phoneCount': len(phones)}))
    return _resp(200, {'wabaId': waba_id, 'obaStatus': rollup, 'phones': phones,
                       'note': 'Official Business Account (green tick) is granted by Meta '
                               'review and cannot be requested through the Graph API.'})


def _update_phone_settings(phone_id: str, body: Dict) -> Dict:
    payload = {}
    if 'calling' in body:
        payload['calling'] = body['calling']
    if not payload:
        return _resp(400, {'error': 'No settings to update'})
    result = _graph_api(f'{phone_id}/settings', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})


# ============================================================================
# USERNAME MANAGEMENT (Meta Username API — official, Jun 2026)
# GET    /<phone_id>/username             — current username + status
# GET    /<phone_id>/username_suggestions — reserved username suggestions
# POST   /<phone_id>/username             — claim/adopt (transfer_action: none|force_transfer)
# DELETE /<phone_id>/username             — delete username
# Uses the Phone Number ID (not WABA ID). Requires whatsapp_business_management.
# ============================================================================

def _get_username(phone_id: str) -> Dict:
    """Get current business username for a phone number."""
    result = _graph_api(f'{phone_id}/username', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, result)


def _get_username_suggestions(phone_id: str) -> Dict:
    """Get reserved username suggestions for a phone number."""
    result = _graph_api(f'{phone_id}/username_suggestions', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    suggestions = []
    for item in result.get('data', []):
        suggestions.extend(item.get('username_suggestions', []))
    return _resp(200, {'suggestions': suggestions, 'raw': result})


def _validate_wa_username(username: str) -> Optional[str]:
    """Meta business-username format rules (official doc, Jun 2026).
    Lowercased by caller. 3-35 chars; [a-z0-9._]; >=1 letter; no leading/trailing
    period; no '..'; not start with www; not end with a domain suffix."""
    import re as _re
    u = username or ''
    if not (3 <= len(u) <= 35):
        return 'Username must be 3-35 characters'
    if not _re.fullmatch(r'[a-z0-9._]+', u):
        return 'Username may only contain lowercase letters, numbers, periods, and underscores'
    if not _re.search(r'[a-z]', u):
        return 'Username must contain at least one letter'
    if u.startswith('.') or u.endswith('.'):
        return 'Username must not start or end with a period'
    if '..' in u:
        return 'Username must not contain two consecutive periods'
    if u.startswith('www'):
        return 'Username must not start with www'
    if _re.search(r'\.(com|org|net|int|edu|gov|mil|us|in|html)$', u):
        return 'Username must not end with a domain suffix (.com, .org, etc.)'
    return None


def _claim_username(phone_id: str, body: Dict) -> Dict:
    """Claim/adopt a business username via Meta's Username API.

    Official endpoint: POST /{phone-number-id}/username with
    { username, transfer_action }. Success returns { status: approved|reserved }.
    Body: { username, transferAction(none|force_transfer), autoForceTransfer }
    Uses the Phone Number ID (not WABA ID); requires whatsapp_business_management.
    """
    username = (body.get('username') or '').strip().lower()
    if not username:
        return _resp(400, {'error': 'username is required'})
    fmt_err = _validate_wa_username(username)
    if fmt_err:
        return _resp(400, {'error': fmt_err})

    transfer_action = (body.get('transferAction') or body.get('transfer_action') or 'none').lower()
    if transfer_action not in ('none', 'force_transfer'):
        transfer_action = 'none'

    def _set(action: str) -> Dict:
        return _graph_api(f'{phone_id}/username', method='POST',
                          payload={'username': username, 'transfer_action': action}, phone_id=phone_id)

    result = _set(transfer_action)
    if 'error' in result:
        err_obj = result.get('error', {}) if isinstance(result.get('error'), dict) else {}
        code = err_obj.get('code')
        if code == 147005 and transfer_action == 'none' and body.get('autoForceTransfer'):
            retry = _set('force_transfer')
            if 'error' not in retry:
                return _resp(200, {'success': True, 'username': username, 'transferAction': 'force_transfer', 'status': retry.get('status'), 'result': retry})
            return _resp(400, retry)
        hints = {
            147005: 'Username is on another phone in your portfolio. Retry with transferAction=force_transfer (or autoForceTransfer=true).',
            147001: 'Username not available (claimed/failed checks). Try a different username.',
            147002: 'Account not eligible — the business portfolio needs a higher messaging limit.',
            147003: 'Link the phone number to the Facebook Page that already uses this username.',
            147004: 'Link the phone number to the Instagram account that already uses this username.',
            133010: 'Register the phone number for API use before claiming a username.',
            33: 'Token lacks whatsapp_business_management or is not assigned to this asset.',
            100: 'Invalid username format.',
        }
        if code in hints:
            result['hint'] = hints[code]
        return _resp(400, result)
    return _resp(200, {'success': True, 'username': username, 'transferAction': transfer_action, 'status': result.get('status'), 'result': result})


def _delete_username(phone_id: str) -> Dict:
    """Delete the business username (official: DELETE /{phone-number-id}/username)."""
    result = _graph_api(f'{phone_id}/username', method='DELETE', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': result.get('success', True), 'result': result})


# ============================================================================
# INSTAGRAM LINKING
# Check Instagram account linked to WABA for username reservation
# ============================================================================

def _get_instagram_accounts(business_id: str) -> Dict:
    """Get Instagram accounts linked to a Meta Business Portfolio."""
    if not business_id:
        return _resp(400, {'error': 'businessId required'})
    result = _graph_api(f'{business_id}/instagram_accounts',
                        params={'fields': 'id,name,username,profile_picture_url,ig_id'})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'accounts': result.get('data', [])})


def _get_waba_instagram_link(waba_id: str) -> Dict:
    """Check if an Instagram account is linked to a WABA for username reservation."""
    if not waba_id:
        return _resp(400, {'error': 'wabaId required'})
    result = _graph_api(f'{waba_id}',
                        params={'fields': 'id,name,instagram_business_account'},
                        waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    ig_account = result.get('instagram_business_account')
    return _resp(200, {
        'wabaId': waba_id,
        'wabaName': result.get('name', ''),
        'instagramLinked': ig_account is not None,
        'instagramAccount': ig_account,
    })


# ============================================================================
# BLOCK USERS API
#
# The Block API hangs off the PHONE NUMBER node, not the WABA node:
#   GET    /{phone-number-id}/block_users   list blocked users
#   POST   /{phone-number-id}/block_users   block
#   DELETE /{phone-number-id}/block_users   unblock
#
# Verified live against both WABAs on 2026-08-25 (v25.0/v26.0/v27.0 all agree):
#   GET /{phone-number-id}/block_users -> 200 {"data":[]}
#   GET /{waba-id}/block_users         -> 400 "nonexisting field (block_users)"
#   GET /{waba-id}/unblock_users       -> 400 "Unknown path components"
# These functions previously used the WABA node and a POST /unblock_users edge
# that does not exist, so /block-users and /unblock-users always failed.
#
# Meta only permits blocking a user who messaged the business in the last 24h.
# ============================================================================

# Each WABA's primary phone number, used to resolve the Block API node.
_WABA_TO_PHONE = {
    WABA1_ID: PHONE1_META_ID,
    WABA2_ID: PHONE2_META_ID,
}


def _resolve_block_phone_id(waba_id: str, body: Dict = None, params: Dict = None) -> str:
    """Resolve the phone-number ID that the Block API must be addressed on.

    Accepts an explicit phoneNumberId/phoneId override, otherwise maps the WABA
    to its primary phone number.
    """
    for src in (body or {}, params or {}):
        for key in ('phoneNumberId', 'phoneId', 'phone_number_id'):
            val = (src.get(key) or '').strip() if isinstance(src.get(key), str) else src.get(key)
            if val:
                return str(val)
    return _WABA_TO_PHONE.get(waba_id, '')


def _normalize_block_users(users) -> list:
    """Coerce caller input into Meta's block_users schema.

    Meta expects: {"block_users": [{"user": "<phone or BSUID>"}]}
    Callers have historically sent {"phone": ...} or {"user_id": ...} instead,
    so accept those shapes and plain strings too.
    """
    out = []
    for u in users or []:
        if isinstance(u, str):
            ident = u.strip()
        elif isinstance(u, dict):
            ident = (u.get('user') or u.get('phone') or u.get('user_id') or '')
            ident = ident.strip() if isinstance(ident, str) else ident
        else:
            continue
        if ident:
            out.append({'user': str(ident)})
    return out


def _block_users(waba_id: str, body: Dict) -> Dict:
    """Block users on the WABA's phone number. Accepts phone numbers or BSUIDs."""
    phone_id = _resolve_block_phone_id(waba_id, body)
    if not phone_id:
        return _resp(400, {'error': 'Could not resolve a phone number ID for this WABA'})
    users = _normalize_block_users(body.get('users') or body.get('block_users'))
    if not users:
        return _resp(400, {'error': 'users array required'})
    payload = {'messaging_product': 'whatsapp', 'block_users': users}
    result = _graph_api(f'{phone_id}/block_users', method='POST', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'phoneNumberId': phone_id, 'result': result})


def _unblock_users(waba_id: str, body: Dict) -> Dict:
    """Unblock users. Meta models unblock as DELETE on the same block_users edge."""
    phone_id = _resolve_block_phone_id(waba_id, body)
    if not phone_id:
        return _resp(400, {'error': 'Could not resolve a phone number ID for this WABA'})
    users = _normalize_block_users(body.get('users') or body.get('block_users'))
    if not users:
        return _resp(400, {'error': 'users array required'})
    payload = {'messaging_product': 'whatsapp', 'block_users': users}
    result = _graph_api(f'{phone_id}/block_users', method='DELETE', payload=payload, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'phoneNumberId': phone_id, 'result': result})


def _get_blocked_users(waba_id: str, params: Dict = None) -> Dict:
    """List blocked users for the WABA's phone number."""
    phone_id = _resolve_block_phone_id(waba_id, None, params)
    if not phone_id:
        return _resp(400, {'error': 'Could not resolve a phone number ID for this WABA'})
    result = _graph_api(f'{phone_id}/block_users', method='GET', phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, result)


# ============================================================================
# BSUID — Contact Book + Parent BSUID accounts (Meta usernames/BSUID rollout)
# ============================================================================
_BSUID_RE = None


def _is_valid_bsuid(bsuid: str) -> bool:
    """BSUID format: <CC>.<alnum> or parent <CC>.ENT.<alnum> (e.g. US.13491208655302741918)."""
    import re as _re
    global _BSUID_RE
    if _BSUID_RE is None:
        _BSUID_RE = _re.compile(r'^[A-Za-z]{2}\.(ENT\.)?[0-9A-Za-z]+$')
    return bool(bsuid) and bool(_BSUID_RE.match(bsuid))


def _delete_contact_book(phone_id: str, bsuid: str) -> Dict:
    """DELETE /{phone-number-id}/contact_book?messaging_product=whatsapp&bsuid=<BSUID>.
    Removes a user's phone+BSUID from the portfolio contact book."""
    if not phone_id:
        return _resp(400, {'error': 'phoneId required'})
    if not _is_valid_bsuid(bsuid):
        return _resp(400, {'error': 'A valid BSUID is required (e.g. US.13491208655302741918). Parent BSUIDs are not supported here.'})
    result = _graph_api(f'{phone_id}/contact_book', method='DELETE',
                        params={'messaging_product': 'whatsapp', 'bsuid': bsuid}, phone_id=phone_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {
        'success': result.get('success', True),
        'deleted': result.get('deleted', False),
        'bsuid': bsuid,
    })


def _api_facebook_get(path: str, business_id: str = None) -> Dict:
    """GET against api.facebook.com (used by Parent BSUID Accounts API, per Meta doc)."""
    token = _get_meta_token()
    app_secret = _get_app_secret()
    params = {'access_token': token}
    if app_secret:
        params['appsecret_proof'] = hmac.new(app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256).hexdigest()
    url = f'https://api.facebook.com/{path}?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'}, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8') if e.fp else str(e)
        try:
            return {'error': json.loads(body).get('error', json.loads(body))}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {'error': {'message': body, 'code': e.code}}


def _get_parent_bsuid_accounts(business_id: str) -> Dict:
    """GET /{business_id}/parent-bsuid-accounts — parent BSUID account + enrolled portfolios."""
    if not business_id:
        return _resp(400, {'error': 'businessId required'})
    result = _api_facebook_get(f'{business_id}/parent-bsuid-accounts')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {
        'parentBsuidAccountId': result.get('parent_bsuid_account_id', ''),
        'enrolledBusinessPortfolios': result.get('enrolled_business_portfolios', []),
        'raw': result,
    })


# ============================================================================
# PAYMENT CONFIGURATION
# Razorpay MID and UPI ID loaded from environment variables (not hardcoded).
# MCC: 7392 | Purpose Code: 03  (verified via Graph API 2026-08-23)
# ============================================================================
_RAZORPAY_MID = os.environ.get('RAZORPAY_MID', '')
_RAZORPAY_UPI_ID = os.environ.get('RAZORPAY_UPI_ID', '')
# PAYU_MID / PAYU_UPI_ID removed 2026-08-23 - no PayU payment configuration
# exists on either WABA, so these were dead reads.
_PAYMENT_WABA_ID = os.environ.get('PAYMENT_WABA_ID', '')

# These are the configuration names this repository DECLARES. They are not a mirror of Meta.
#
# This block used to say "Mirrors the live Meta state, verified via Graph API
# /{waba}/payment_configurations on 2026-08-23" and marked both entries `status: 'active'`.
# Re-measured **2026-09-30**: that WABA returns **ZERO** payment configurations. So the comment
# was a year-stale claim and the status was a constant asserting a live fact.
#
# The cost was not theoretical - the two routes in this file disagreed with each other.
# `/wa-business/payment-config/check`, which actually calls Meta, reported both as
# `local_only` with `canReceivePayments: false` and `activeConfigs: 0`; this one reported
# `status: 'active'`. Anyone reading the second would conclude payments were configured.
#
# `status` is now `local_only`, matching the route that asks. The live verdict comes from
# `lambda_utils.payment_readiness`, which is built to answer this and blocks on
# PAYMENT_CONFIG_MISSING when Meta reports none.
#
# There are deliberately NO hardcoded MID / VPA fallbacks any more. The previous ones were
# `acc_TTFSyolquKEZEy` and `wecaredigitalbh511413.rzp@rxairtel`, and both disagreed with the
# live Lambda environment (`[retired Razorpay account]`, `[retired UPI VPA]`) - a different
# account and a different PSP handle. A wrong merchant id is worse than an absent one: absent
# yields CONFIGURATION_UNVERIFIED and blocks, whereas wrong could match a configuration
# pointing at an account nobody here reconciles against. Empty is the fail-closed value.
_DECLARED_CONFIGS = [
    {'name': 'WECAREDIGITAL', 'status': 'local_only', 'type': 'payment_gateway',
     'gateway': 'razorpay', 'mid': _RAZORPAY_MID},
    {'name': 'WECAREUPI', 'status': 'local_only', 'type': 'upi',
     'gateway': 'razorpay', 'upiId': _RAZORPAY_UPI_ID},
]

PAYMENT_CONFIGS = {
    PHONE1_META_ID: {
        'phone': '+91 9330994400',
        'wabaId': WABA1_ID,
        'configs': list(_DECLARED_CONFIGS),
        'mcc': '7392',
        'purposeCode': '03',
    },
    PHONE2_META_ID: {
        'phone': '+91 9903300044',
        'wabaId': WABA2_ID,
        'configs': list(_DECLARED_CONFIGS),
        'mcc': '7392',
        'purposeCode': '03',
    },
}


def _flatten_payment_configurations(raw: Dict) -> Dict:
    """Normalise Meta's `GET /{waba}/payment_configurations` response into the flat
    `{"data": [ {configuration_name, status, provider_name, provider_mid, ...}, ... ]}`
    shape `payment_readiness.evaluate` consumes.

    Measured 2026-10-08: the live edge nests the real list one level down as
    `data[0].payment_configurations[]`, and ONLY when no `fields` filter is sent (sending
    `fields=configuration_name,status,payment_gateway,...` makes Meta return `data: []`,
    which is the false-negative that blocked every payment). An `error` object or an already
    flat list is passed through unchanged so a future shape change degrades to the honest
    META_UNAVAILABLE / direct-parse path rather than silently dropping configs.
    """
    if not isinstance(raw, dict) or raw.get("error"):
        return raw if isinstance(raw, dict) else {"error": {"message": "non-dict response"}}
    data = raw.get("data")
    if not isinstance(data, list):
        return raw
    flat = []
    for element in data:
        if isinstance(element, dict) and isinstance(element.get("payment_configurations"), list):
            flat.extend(c for c in element["payment_configurations"] if isinstance(c, dict))
        elif isinstance(element, dict):
            # Already a flat configuration object (older shape or a named-lookup result).
            flat.append(element)
    return {"data": flat}


def _read_payment_configurations(waba_id: str) -> Dict:
    """One complete unfiltered provider read for checkout and operator diagnostics.

    Meta's fields filter returns an empty collection for this edge. Follow bounded
    cursor pages using the fixed edge; never follow a provider-supplied absolute URL.
    Incomplete or repeating pagination fails closed instead of certifying a subset.
    """
    configurations = []
    cursor = None
    seen = set()
    for _ in range(20):
        raw = _graph_api(f'{waba_id}/payment_configurations', waba_id=waba_id,
                         **({'params': {'after': cursor}} if cursor else {}))
        flat = _flatten_payment_configurations(raw)
        if not isinstance(flat, dict) or flat.get('error'):
            return flat
        if not isinstance(flat.get('data'), list):
            return {'error': {'message': 'Payment configuration response is incomplete'}}
        configurations.extend(flat['data'])
        paging = raw.get('paging') or {}
        if not paging.get('next'):
            return {'data': configurations}
        cursor = (paging.get('cursors') or {}).get('after')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            break
        seen.add(cursor)
    return {'error': {'message': 'Payment configuration pagination is incomplete'}}


def _payment_readiness_for(waba_id: str, configuration_name: str) -> Dict:
    """The live verdict on whether a payment could actually be taken, or a reason it cannot.

    Separated from the declared-config view above so a caller cannot mistake one for the other.
    The declaration says what we intend to use; this says what Meta will accept. On 2026-09-30
    those differ completely - zero configurations exist - and the whole point of returning both
    is that the difference is visible rather than hidden behind a constant reading `active`.

    Never raises: this is a diagnostic route, and a readiness check that 500s tells the reader
    less than one that reports why it could not decide.
    """
    try:
        from lambda_utils import payment_readiness

        verdict = payment_readiness.evaluate(
            expected_waba_id=waba_id,
            expected_configuration_name=configuration_name,
            expected_provider_mid=_RAZORPAY_MID,
            fetch_configurations=_read_payment_configurations,
        )
        return {
            'ready': verdict.ready,
            'state': verdict.state,
            'reason': verdict.reason,
            'configurationsMetaReports': verdict.checked_configurations,
        }
    except Exception as exc:  # noqa: BLE001
        return {'ready': False, 'state': 'READINESS_CHECK_FAILED',
                'reason': type(exc).__name__}


def _get_payment_config(phone_id: str) -> Dict:
    """Get payment configuration for a phone number.

    Returns the DECLARED configuration and, beside it, the LIVE readiness verdict. The two used
    to be conflated: this route reported `status: 'active'` for configurations that do not exist
    at Meta, contradicting `/payment-config/check` in the same file.
    """
    config = PAYMENT_CONFIGS.get(phone_id)
    if config:
        declared_name = (config['configs'][0]['name'] if config.get('configs') else '')
        return _resp(200, {
            'paymentConfig': config,
            # Named to be impossible to misread as part of the declaration above.
            'liveReadiness': _payment_readiness_for(config.get('wabaId', ''), declared_name),
            'note': ("`configs[].status` is `local_only`: it is what this repository declares, "
                     "not what Meta reports. `liveReadiness` is the live readback and is the "
                     "only field that says whether a payment can be taken."),
        })
    # Try commerce settings from Meta Graph API
    result = _graph_api(f'{phone_id}/whatsapp_commerce_settings', phone_id=phone_id)
    if 'error' in result:
        return _resp(200, {'paymentConfig': None, 'note': 'No payment config found for this phone'})
    return _resp(200, {'paymentConfig': result})


def _check_payment_gateway(waba_id: str = None) -> Dict:
    """Check payment gateway configurations via Meta Graph API for all WABAs or a specific one."""
    results = []
    waba_ids = [waba_id] if waba_id else [WABA1_ID, WABA2_ID]
    waba_phone_map = {
        WABA1_ID: {'phone': '+91 9330994400', 'phoneId': PHONE1_META_ID},
        WABA2_ID: {'phone': '+91 9903300044', 'phoneId': PHONE2_META_ID},
    }

    for wid in waba_ids:
        phone_info = waba_phone_map.get(wid, {})
        local_config = PAYMENT_CONFIGS.get(phone_info.get('phoneId', ''), {})

        # Query Meta Graph API for payment configurations on this WABA
        api_result = _read_payment_configurations(wid)

        meta_configs = []
        if 'data' in api_result:
            meta_configs = api_result['data']
        elif 'error' not in api_result and isinstance(api_result, list):
            meta_configs = api_result

        # Build check result for each config
        config_checks = []
        for cfg in meta_configs:
            config_checks.append({
                'name': cfg.get('configuration_name', 'unknown'),
                'status': cfg.get('status', 'unknown'),
                'gateway': cfg.get('provider_name') or (cfg.get('payment_gateway', {}).get('type', 'unknown') if isinstance(cfg.get('payment_gateway'), dict) else str(cfg.get('payment_gateway', 'unknown'))),
                'mid': cfg.get('provider_mid') or (cfg.get('payment_gateway', {}).get('merchant_id', '') if isinstance(cfg.get('payment_gateway'), dict) else ''),
                'mcc': cfg.get('merchant_category_code', ''),
                'purposeCode': cfg.get('purpose_code', ''),
                'canReceivePayments': str(cfg.get('status') or '').lower() == 'active',
            })

        # Also include local configs not found in Meta API (for comparison)
        meta_names = {c['name'] for c in config_checks}
        for lc in local_config.get('configs', []):
            if lc['name'] not in meta_names:
                config_checks.append({
                    'name': lc['name'],
                    'status': 'local_only',
                    'gateway': lc.get('gateway', ''),
                    'mid': lc.get('mid', ''),
                    'mcc': local_config.get('mcc', ''),
                    'purposeCode': local_config.get('purposeCode', ''),
                    'canReceivePayments': False,
                    'note': 'Config exists locally but not found in Meta API',
                })

        results.append({
            'wabaId': wid,
            'phone': phone_info.get('phone', ''),
            'configurations': config_checks,
            'metaApiResponse': api_result if 'error' in api_result else None,
            'totalConfigs': len(config_checks),
            'activeConfigs': sum(1 for c in config_checks if c.get('canReceivePayments')),
        })

    return _resp(200, {'gatewayChecks': results})


def _payment_lookup(phone_number_id: str, config_name: str, reference_id: str) -> Dict:
    """Meta Payment Lookup API — verify payment status directly from WhatsApp.
    GET /<PHONE_NUMBER_ID>/payments/<PAYMENT_CONFIGURATION>/<REFERENCE_ID>
    SECURITY: Must not rely solely on webhooks. Always verify via this API."""
    if not phone_number_id or not config_name or not reference_id:
        return _resp(400, {'error': 'phone_number_id, config_name, and reference_id are required'})

    result = _graph_api(
        f'{phone_number_id}/payments/{config_name}/{reference_id}',
        phone_id=phone_number_id,
    )
    if 'error' in result:
        return _resp(result.get('error', {}).get('code', 500), {'error': result['error']})
    return _resp(200, {'paymentLookup': result})


def _payment_refund(phone_number_id: str, reference_id: str, config_name: str,
                    amount_paise: int, speed: str = 'normal') -> Dict:
    """Meta Refund API — initiate refund via WhatsApp.
    POST /<PHONE_NUMBER_ID>/payments_refund"""
    if not phone_number_id or not reference_id or not config_name:
        return _resp(400, {'error': 'phone_number_id, reference_id, and config_name are required'})
    if amount_paise <= 0:
        return _resp(400, {'error': 'amount must be positive'})
    if speed not in ('normal', 'instant'):
        speed = 'normal'

    payload = {
        'reference_id': reference_id,
        'speed': speed,
        'payment_config_id': config_name,
        'amount': {
            'currency': 'INR',
            'value': str(amount_paise),
            'offset': '100',
        },
    }
    result = _graph_api(
        f'{phone_number_id}/payments_refund',
        method='POST',
        payload=payload,
        phone_id=phone_number_id,
    )
    if 'error' in result:
        return _resp(result.get('error', {}).get('code', 500), {'error': result['error']})
    return _resp(200, {'refund': result})


# ============================================================================
# FLOW ENCRYPTION / DECRYPTION (WhatsApp Flows require E2E encryption)
# ============================================================================
from base64 import b64decode, b64encode
from cryptography.hazmat.primitives.asymmetric.padding import OAEP, MGF1
from cryptography.hazmat.primitives.asymmetric.padding import hashes as asym_hashes
from cryptography.hazmat.primitives.ciphers import Cipher as AESCipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_pem_private_key

FLOW_PRIVATE_KEY_SECRET = os.environ.get('FLOW_PRIVATE_KEY_SECRET', 'wecare/flow-private-key')
FLOW_PRIVATE_KEY_PASSPHRASE = os.environ.get('FLOW_PRIVATE_KEY_PASSPHRASE', '')
_flow_private_key = None


def _get_flow_private_key():
    """Load RSA private key from Secrets Manager (cached)."""
    global _flow_private_key
    if _flow_private_key:
        return _flow_private_key
    try:
        resp = secrets_client.get_secret_value(SecretId=FLOW_PRIVATE_KEY_SECRET)
        pem = resp['SecretString']
        passphrase = FLOW_PRIVATE_KEY_PASSPHRASE.encode('utf-8') if FLOW_PRIVATE_KEY_PASSPHRASE else None
        _flow_private_key = load_pem_private_key(pem.encode('utf-8'), password=passphrase)
        return _flow_private_key
    except Exception as e:
        logger.error(f'Failed to load flow private key: {e}')
        return None


def _decrypt_flow_request(encrypted_flow_data_b64: str, encrypted_aes_key_b64: str, initial_vector_b64: str):
    """Decrypt WhatsApp Flow data_exchange request."""
    private_key = _get_flow_private_key()
    if not private_key:
        raise ValueError('Flow private key not available')

    flow_data = b64decode(encrypted_flow_data_b64)
    iv = b64decode(initial_vector_b64)
    encrypted_aes_key = b64decode(encrypted_aes_key_b64)

    # Decrypt AES key with RSA private key
    aes_key = private_key.decrypt(
        encrypted_aes_key,
        OAEP(mgf=MGF1(algorithm=asym_hashes.SHA256()), algorithm=asym_hashes.SHA256(), label=None)
    )

    # Decrypt flow data with AES-GCM
    encrypted_body = flow_data[:-16]
    tag = flow_data[-16:]
    decryptor = AESCipher(algorithms.AES(aes_key), modes.GCM(iv, tag)).decryptor()
    decrypted = decryptor.update(encrypted_body) + decryptor.finalize()
    return json.loads(decrypted.decode('utf-8')), aes_key, iv


def _encrypt_flow_response(response_data: dict, aes_key: bytes, iv: bytes) -> str:
    """Encrypt WhatsApp Flow response. Returns base64 string."""
    # Flip IV
    flipped_iv = bytearray(b ^ 0xFF for b in iv)
    encryptor = AESCipher(algorithms.AES(aes_key), modes.GCM(bytes(flipped_iv))).encryptor()
    encrypted = encryptor.update(json.dumps(response_data).encode('utf-8')) + encryptor.finalize()
    return b64encode(encrypted + encryptor.tag).decode('utf-8')


# ============================================================================
# FLOW MANAGEMENT ENGINE
# ============================================================================

def _get_flow_registry(flow_id: str) -> Dict:
    """Get flow config from registry, with in-memory caching.
    Only returns PUBLISHED flows — DEPRECATED/DRAFT flows are ignored."""
    global _flow_registry_cache, _flow_registry_cache_ts
    now = time.time()
    cache_key = f'id:{flow_id}'
    if cache_key in _flow_registry_cache and (now - _flow_registry_cache_ts) < FLOW_REGISTRY_CACHE_TTL:
        return _flow_registry_cache[cache_key]
    try:
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        resp = table.get_item(Key={'flowId': flow_id})
        item = resp.get('Item', {})
        if item:
            # Reject DEPRECATED flows — they must never be used for routing/payment
            if item.get('status') == 'DEPRECATED':
                logger.warning(json.dumps({
                    'event': 'flow_registry_deprecated_rejected',
                    'flowId': flow_id,
                    'flowCode': item.get('flowCode', ''),
                    'status': item.get('status'),
                }))
                return {}
            _flow_registry_cache[cache_key] = item
            _flow_registry_cache_ts = now
            return item
    except Exception as e:
        logger.warning(f'Flow registry lookup failed for {flow_id}: {e}')
    return {}


def _get_flow_registry_by_code(flow_code: str) -> Dict:
    """Look up flow config by flowCode (e.g. '01.WD_SR').
    Only returns PUBLISHED flows — DEPRECATED/DRAFT flows are ignored."""
    # Check cache first
    global _flow_registry_cache, _flow_registry_cache_ts
    now = time.time()
    cache_key = f'code:{flow_code}'
    if cache_key in _flow_registry_cache and (now - _flow_registry_cache_ts) < FLOW_REGISTRY_CACHE_TTL:
        return _flow_registry_cache[cache_key]
    try:
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        resp = table.query(
            IndexName='flowCode',
            KeyConditionExpression='flowCode = :c',
            ExpressionAttributeValues={':c': flow_code},
        )
        items = resp.get('Items', [])
        # Filter: only return PUBLISHED flows (never DEPRECATED or DRAFT)
        published = [i for i in items if i.get('status') == 'PUBLISHED']
        if published:
            _flow_registry_cache[cache_key] = published[0]
            _flow_registry_cache_ts = now
            return published[0]
        # If no PUBLISHED flow, log warning and return empty
        if items:
            logger.warning(json.dumps({
                'event': 'flow_registry_no_published_flow',
                'flowCode': flow_code,
                'foundStatuses': [i.get('status') for i in items],
            }))
        return {}
    except Exception as e:
        logger.warning(f'Flow registry code lookup failed for {flow_code}: {e}')
        return {}


# _save_flow_submission REMOVED 2026-09-24.
#
# It was the FOURTH writer into FlowSubmissionTable and the only one left with no
# duplicate guard - a bare put_item with a random submissionId, so every call
# created a new row. lambda_utils/flow_completion exists precisely to stop that:
# one duplicated paid submit_request completion previously produced 2 submissions,
# 2 invoices and 2 payment links sent to the customer, which is money, and nothing
# in the system reported it.
#
# It had ZERO callers. Verified across amplify/, scripts/ and tests/, including
# dynamic dispatch - the only other mentions of the name are flow_completion's own
# audit docstring and references to the DIFFERENT function
# flows/common.save_flow_submission, which is guarded via
# flow_completion.claim_completion and is what the nine live flows use.
#
# Deleted rather than guarded. Wiring it up would have been a two-line change that
# reintroduced the exact bug flow_completion was written to prevent, and a dead
# unsafe writer beside a live safe one is an invitation. Recovering it, if a
# non-flow submission path is ever wanted, means calling
# flow_completion.claim_completion first and branching on the result - not
# restoring this function. Prior text is in git history at 956e3e6a.


def _enrich_contact_from_flow(contact_id: str, form_data: Dict, contact_mapping: Dict):
    """Update Contact record with data collected from a flow."""
    if not contact_id or not contact_mapping:
        return
    try:
        update_parts = []
        expr_values = {}
        expr_names = {}
        now_ts = int(time.time())

        for flow_field, contact_field in contact_mapping.items():
            val = form_data.get(flow_field, '')
            if val:
                safe_key = contact_field.replace('.', '_')
                update_parts.append(f'#{safe_key} = :{safe_key}')
                expr_values[f':{safe_key}'] = str(val)
                expr_names[f'#{safe_key}'] = contact_field

        # Always update lastFlowInteractionAt and updatedAt (epoch seconds for consistency)
        update_parts.append('#lfia = :lfia')
        expr_values[':lfia'] = Decimal(str(now_ts))
        expr_names['#lfia'] = 'lastFlowInteractionAt'
        update_parts.append('#ua = :ua')
        expr_values[':ua'] = Decimal(str(now_ts))
        expr_names['#ua'] = 'updatedAt'

        if update_parts:
            table = dynamodb.Table(CONTACTS_TABLE)
            table.update_item(
                Key={'id': contact_id},
                UpdateExpression='SET ' + ', '.join(update_parts),
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names,
            )
            logger.info(f'Contact {contact_id} enriched with {len(update_parts) - 2} flow fields')
    except Exception as e:
        logger.warning(f'Contact enrichment failed for {contact_id}: {e}')


def _log_flow_interaction(flow_config: Dict, flow_token: str, phone: str,
                          action: str, screen: str, data: Dict, request_id: str,
                          is_error: bool = False, error_type: str = '', error_message: str = ''):
    """Log a flow interaction to FlowLogsTable."""
    try:
        now = int(time.time())
        table = dynamodb.Table(FLOW_LOGS_TABLE)
        item = {
            'logId': f'flog-{uuid.uuid4().hex[:12]}',
            'flowId': flow_config.get('flowId', ''),
            'flowCode': flow_config.get('flowCode', ''),
            'flowToken': flow_token,
            'phone': phone,
            'action': action,
            'screen': screen,
            'requestId': request_id,
            'createdAt': Decimal(str(now)),
            'ttl': now + (90 * 86400),  # 90 days
        }
        if data:
            try:
                item['dataSnapshot'] = json.dumps(data, default=str)[:4000]  # Cap at 4KB
            except Exception:
                pass
        if is_error:
            item['isError'] = True
            item['errorType'] = error_type
            item['errorMessage'] = error_message
        table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
    except Exception as e:
        logger.warning(f'Flow log write failed: {e}')


def _update_submission_status(body: Dict) -> Dict:
    """Update a flow submission's status. Logs history for audit trail."""
    submission_id = body.get('submissionId', '')
    new_status = body.get('status', '')
    notes = body.get('notes', '')
    changed_by = body.get('changedBy', 'admin')

    if not submission_id or not new_status:
        return _resp(400, {'error': 'submissionId and status required'})

    valid_statuses = {'open', 'in_progress', 'resolved', 'closed', 'cancelled', 'awaiting_order_verification'}
    if new_status not in valid_statuses:
        return _resp(400, {'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'})

    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        # Get current submission
        resp = table.get_item(Key={'submissionId': submission_id})
        item = resp.get('Item')
        if not item:
            return _resp(404, {'error': 'Submission not found'})

        old_status = item.get('status', 'open')
        now = int(time.time())

        # Update status
        update_expr = 'SET #st = :st, updatedAt = :u'
        expr_names = {'#st': 'status'}
        expr_vals = {':st': new_status, ':u': Decimal(str(now))}

        if notes:
            old_notes = item.get('notes', '') or ''
            ts = time.strftime('%d %b %Y %H:%M', time.gmtime(now + 19800))
            new_notes = f'{old_notes}\n[{ts} by {changed_by}] Status: {old_status} → {new_status}. {notes}'.strip()
            update_expr += ', notes = :n'
            expr_vals[':n'] = new_notes[:2000]

        if new_status == 'resolved':
            update_expr += ', resolvedAt = :ra'
            expr_vals[':ra'] = Decimal(str(now))

        table.update_item(
            Key={'submissionId': submission_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
        )

        # Log to RequestStatusHistoryTable
        try:
            hist_table = dynamodb.Table('stack-wecare-digital-RequestStatusHistoryTable')
            hist_table.put_item(Item={
                'historyId': str(uuid.uuid4()),
                'submissionId': submission_id,
                'orderId': item.get('orderId', ''),
                'oldStatus': old_status,
                'newStatus': new_status,
                'changedBy': changed_by,
                'notes': notes[:500] if notes else '',
                'changedAt': Decimal(str(now)),
            })
        except Exception as he:
            logger.warning(f'Status history log failed: {he}')

        logger.info(json.dumps({
            'event': 'submission_status_updated',
            'submissionId': submission_id,
            'oldStatus': old_status,
            'newStatus': new_status,
            'changedBy': changed_by,
        }))

        return _resp(200, {
            'submissionId': submission_id,
            'oldStatus': old_status,
            'newStatus': new_status,
            'updated': True,
        })
    except Exception as e:
        logger.error(f'Status update failed: {e}')
        return _resp(500, {'error': str(e)})


def _project_submission_attachments(attachments):
    """Sign private staff downloads on read; never persist bearer URLs."""
    if not isinstance(attachments, list):
        return attachments
    projected = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            projected.append(attachment)
            continue
        entry = dict(attachment)
        key = entry.get('key')
        if isinstance(key, str) and media_paths.is_gated(key):
            entry.pop('url', None)
            entry.pop('link', None)
            allowed = key.startswith(('secure/u/service-requests/', 'secure/u/whatsapp/incoming/'))
            if allowed and not any(part in ('', '.', '..') for part in key.split('/')) and '\\' not in key:
                try:
                    entry['url'] = s3_client.generate_presigned_url(
                        'get_object', Params={'Bucket': MEDIA_BUCKET, 'Key': key}, ExpiresIn=300)
                except Exception as error:
                    logger.warning(json.dumps({'event': 'submission_download_unavailable',
                                               'errorType': type(error).__name__}))
        projected.append(entry)
    return projected


def _list_flow_submissions(params: Dict) -> Dict:
    """List flow submissions with filtering."""
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        limit = min(int(params.get('limit', '100')), 500)
        flow_code = params.get('flowCode', '')
        payment_status = params.get('paymentStatus', '')
        status_filter = params.get('status', '')
        phone_filter = params.get('phone', '')

        if flow_code:
            resp = table.query(
                IndexName='flowCode', KeyConditionExpression='flowCode = :c',
                ExpressionAttributeValues={':c': flow_code},
                ScanIndexForward=False, Limit=limit,
            )
        elif payment_status:
            resp = table.query(
                IndexName='paymentStatus', KeyConditionExpression='paymentStatus = :s',
                ExpressionAttributeValues={':s': payment_status},
                ScanIndexForward=False, Limit=limit,
            )
        elif status_filter:
            resp = table.query(
                IndexName='status', KeyConditionExpression='#st = :s',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':s': status_filter},
                ScanIndexForward=False, Limit=limit,
            )
        elif phone_filter:
            resp = table.query(
                IndexName='phone', KeyConditionExpression='phone = :p',
                ExpressionAttributeValues={':p': phone_filter},
                ScanIndexForward=False, Limit=limit,
            )
        else:
            resp = table.scan(Limit=limit)

        items = [dict(item) for item in resp.get('Items', [])]
        for item in items:
            if 'attachments' in item:
                item['attachments'] = _project_submission_attachments(item['attachments'])
        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = int(v) if v == int(v) else float(v)
        items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        return _resp(200, {'submissions': items, 'count': len(items)})
    except Exception as e:
        logger.error(f'List flow submissions error: {e}')
        return _resp(500, {'error': str(e)})


def _list_flow_registry(params: Dict) -> Dict:
    """List all registered flows."""
    try:
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        resp = table.scan()
        items = resp.get('Items', [])
        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = int(v) if v == int(v) else float(v)
        items.sort(key=lambda x: x.get('flowCode', ''))
        return _resp(200, {'flows': items, 'count': len(items)})
    except Exception as e:
        logger.error(f'List flow registry error: {e}')
        return _resp(500, {'error': str(e)})


def _upsert_flow_registry(body: Dict) -> Dict:
    """Create or update a flow registry entry."""
    try:
        flow_id = body.get('flowId', '')
        if not flow_id:
            return _resp(400, {'error': 'flowId required'})
        
        status = body.get('status', 'DRAFT')
        valid_statuses = ('DRAFT', 'PUBLISHED', 'DEPRECATED')
        if status not in valid_statuses:
            return _resp(400, {'error': f'Invalid status: {status}. Must be one of {valid_statuses}'})
        
        now = int(time.time())
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        item = {
            'flowId': flow_id,
            'flowCode': body.get('flowCode', ''),
            'flowName': body.get('flowName', ''),
            'flowType': body.get('flowType', 'form_submit'),
            'flowVersion': body.get('flowVersion', '7.3'),
            'dataApiVersion': body.get('dataApiVersion', '4.0'),
            'wabaId': body.get('wabaId', ''),
            'status': status,
            'category': body.get('category', ''),
            'requiresPayment': body.get('requiresPayment', False),
            'paymentAmount': int(body.get('paymentAmount', 0)),
            'paymentDescription': body.get('paymentDescription', ''),
            'preferredGateway': body.get('preferredGateway', ''),
            'paymentConfigName': body.get('paymentConfigName', ''),
            'screenConfig': body.get('screenConfig', '{}'),
            'contactMapping': body.get('contactMapping', '{}'),
            'dataFetchers': body.get('dataFetchers', '{}'),
            'submissionPrefix': body.get('submissionPrefix', 'WD'),
            # apex `/api` path since 2026-09-26; `api.wecare.digital` is retired.
            'endpointUri': body.get('endpointUri', 'https://wecare.digital/api/wa-business/flow-data'),
            'createdAt': Decimal(str(body.get('createdAt', now))),
            'updatedAt': Decimal(str(now)),
        }
        if body.get('publishedAt'):
            item['publishedAt'] = Decimal(str(body['publishedAt']))
        # Optional extended metadata (Part 4 A) — only persisted when provided.
        for opt_key in ('preferredGateway', 'abTestConfig', 'healthStatusJson', 'validationErrorsJson',
                        'previewUrl', 'clonedFromFlowId', 'migrationBatchId', 'dataChannelUri',
                        'jsonVersion', 'applicationId', 'categories'):
            if body.get(opt_key):
                item[opt_key] = body[opt_key]
        for opt_ts in ('previewExpiresAt', 'lastSyncedAt', 'lastPublishedAt', 'lastDeprecatedAt'):
            if body.get(opt_ts):
                item[opt_ts] = Decimal(str(body[opt_ts]))
        table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
        # Invalidate cache
        global _flow_registry_cache, _flow_registry_cache_ts
        _flow_registry_cache = {}
        _flow_registry_cache_ts = 0
        
        logger.info(json.dumps({
            'event': 'flow_registry_upserted',
            'flowId': flow_id,
            'flowCode': body.get('flowCode', ''),
            'status': status,
            'requiresPayment': body.get('requiresPayment', False),
        }))
        return _resp(200, {'success': True, 'flowId': flow_id})
    except Exception as e:
        logger.error(f'Upsert flow registry error: {e}')
        return _resp(500, {'error': str(e)})


# ============================================================================
# FLOW ASSETS / MIGRATE / SYNC (Part 4 A)
# ============================================================================
def _upload_flow_asset(flow_id: str, body: Dict) -> Dict:
    """POST /{FLOW-ID}/assets — upload a FLOW_JSON asset (multipart).

    Validates the flow JSON locally first, then parses Meta validation_errors.
    Published flows/assets are immutable; Meta will reject edits to them.
    """
    if not flow_id:
        return _resp(400, {'error': 'flowId required'})
    flow_json = body.get('flowJson')
    if flow_json is None:
        return _resp(400, {'error': 'flowJson required'})

    # Validate JSON locally before upload.
    if isinstance(flow_json, str):
        try:
            parsed = json.loads(flow_json)
        except json.JSONDecodeError as e:
            return _resp(400, {'error': f'flowJson is not valid JSON: {e}'})
        json_bytes = flow_json.encode('utf-8')
    elif isinstance(flow_json, dict):
        parsed = flow_json
        json_bytes = json.dumps(flow_json).encode('utf-8')
    else:
        return _resp(400, {'error': 'flowJson must be a JSON object or string'})
    if 'screens' not in parsed and 'version' not in parsed:
        return _resp(400, {'error': 'flowJson missing required keys (version/screens)'})

    asset_type = body.get('assetType', 'FLOW_JSON')
    asset_name = body.get('name', 'flow.json')
    waba_id = body.get('wabaId')

    token = _get_meta_token(waba_id=waba_id)
    app_secret = _get_app_secret(waba_id=waba_id)
    boundary = uuid.uuid4().hex
    parts = []
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(f'Content-Disposition: form-data; name="name"\r\n\r\n{asset_name}\r\n'.encode())
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(f'Content-Disposition: form-data; name="asset_type"\r\n\r\n{asset_type}\r\n'.encode())
    parts.append(f'--{boundary}\r\n'.encode())
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{asset_name}"\r\n'.encode())
    parts.append(b'Content-Type: application/json\r\n\r\n')
    parts.append(json_bytes)
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    multipart_body = b''.join(parts)

    url = f'{GRAPH_BASE}/{flow_id}/assets'
    if app_secret:
        proof = hmac.new(app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256).hexdigest()
        url += '?' + urllib.parse.urlencode({'appsecret_proof': proof})
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    }
    req = urllib.request.Request(url, data=multipart_body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.error(f'Flow asset upload error {e.code}: {error_body}')
        try:
            return _resp(400, {'error': json.loads(error_body)})
        except (json.JSONDecodeError, TypeError, ValueError):
            return _resp(400, {'error': {'message': error_body, 'code': e.code}})

    validation_errors = result.get('validation_errors', [])
    if validation_errors:
        _emit_event('flow_validation_error', severity='warning', waba_id=waba_id,
                    data={'flowId': flow_id, 'validationErrors': validation_errors})
    return _resp(200, {
        'success': result.get('success', True),
        'flowId': flow_id,
        'validationErrors': validation_errors,
        'hasErrors': bool(validation_errors),
    })


def _migrate_flows(body: Dict) -> Dict:
    """POST /{DEST-WABA-ID}/migrate_flows — migrate flows between WABAs."""
    dest_waba_id = body.get('destWabaId') or body.get('wabaId')
    source_waba_id = body.get('sourceWabaId')
    if not dest_waba_id or not source_waba_id:
        return _resp(400, {'error': 'sourceWabaId and destWabaId are required'})
    payload = {'source_waba_id': source_waba_id}
    if body.get('sourceFlowNames'):
        names = body['sourceFlowNames']
        payload['source_flow_names'] = names if isinstance(names, str) else ','.join(names)
    result = _graph_api(f'{dest_waba_id}/migrate_flows', method='POST', payload=payload, waba_id=dest_waba_id)
    if 'error' in result:
        return _resp(400, result)
    batch_id = body.get('migrationBatchId', uuid.uuid4().hex)
    _emit_event('flow_migrated', severity='info', waba_id=dest_waba_id, data={
        'sourceWabaId': source_waba_id, 'destWabaId': dest_waba_id,
        'migrated': len(result.get('migrated_flows', [])),
        'failed': len(result.get('failed_flows', [])),
        'migrationBatchId': batch_id,
    })
    return _resp(200, {
        'migratedFlows': result.get('migrated_flows', []),
        'failedFlows': result.get('failed_flows', []),
        'migrationBatchId': batch_id,
    })


def _sync_flows(params: Dict, body: Dict) -> Dict:
    """POST /wa-business/flows/sync — reconcile Meta flows into FlowRegistry.

    Lists flows from Meta for a WABA and upserts live status/category/validation
    metadata into the registry (preserving existing config fields).
    """
    waba_id = params.get('wabaId') or body.get('wabaId')
    if not waba_id:
        return _resp(400, {'error': 'wabaId required'})
    fields = ('id,name,status,categories,validation_errors,json_version,'
              'data_api_version,health_status,preview')
    result = _graph_api(f'{waba_id}/flows', params={'fields': fields}, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)

    flows = result.get('data', [])
    now = int(time.time())
    table = dynamodb.Table(FLOW_REGISTRY_TABLE)
    synced = 0
    for f in flows:
        flow_id = f.get('id')
        if not flow_id:
            continue
        try:
            existing = table.get_item(Key={'flowId': flow_id}).get('Item', {})
        except Exception:
            existing = {}
        categories = f.get('categories', [])
        validation_errors = f.get('validation_errors', [])
        health = f.get('health_status', {})
        preview = f.get('preview', {})
        if validation_errors:
            _emit_event('flow_validation_error', severity='warning', waba_id=waba_id,
                        data={'flowId': flow_id, 'validationErrors': validation_errors})
        if isinstance(health, dict) and str(health.get('can_send_message', 'AVAILABLE')).upper() == 'BLOCKED':
            _emit_event('flow_health_blocked', severity='error', waba_id=waba_id,
                        data={'flowId': flow_id, 'health': health})
        update = {
            'flowId': flow_id,
            'flowName': f.get('name', existing.get('flowName', '')),
            'status': f.get('status', existing.get('status', 'DRAFT')),
            'category': categories[0] if categories else existing.get('category', ''),
            'categories': json.dumps(categories) if categories else existing.get('categories', '[]'),
            'wabaId': waba_id,
            'jsonVersion': str(f.get('json_version', existing.get('jsonVersion', ''))),
            'dataApiVersion': str(f.get('data_api_version', existing.get('dataApiVersion', ''))),
            'validationErrorsJson': json.dumps(validation_errors) if validation_errors else '[]',
            'healthStatusJson': json.dumps(health) if health else '{}',
            'lastSyncedAt': Decimal(str(now)),
            'updatedAt': Decimal(str(now)),
        }
        if preview.get('preview_url'):
            update['previewUrl'] = preview['preview_url']
            update['previewExpiresAt'] = Decimal(str(now + 600))
        # Preserve config-only fields already present.
        for keep in ('flowCode', 'flowType', 'flowVersion', 'requiresPayment', 'paymentAmount',
                     'paymentConfigName', 'screenConfig', 'contactMapping', 'dataFetchers',
                     'submissionPrefix', 'endpointUri', 'createdAt'):
            if keep in existing and keep not in update:
                update[keep] = existing[keep]
        update.setdefault('createdAt', Decimal(str(now)))
        table.put_item(Item={k: v for k, v in update.items() if v is not None and v != ''})
        synced += 1

    global _flow_registry_cache, _flow_registry_cache_ts
    _flow_registry_cache = {}
    _flow_registry_cache_ts = 0
    return _resp(200, {'success': True, 'synced': synced, 'total': len(flows), 'wabaId': waba_id})


def _get_flow_submission_stats(params: Dict) -> Dict:
    """Get aggregated stats for flow submissions — payment totals, status counts."""
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        flow_code = params.get('flowCode', '')
        if flow_code:
            resp = table.query(
                IndexName='flowCode', KeyConditionExpression='flowCode = :c',
                ExpressionAttributeValues={':c': flow_code},
                Limit=500,
            )
        else:
            resp = table.scan(Limit=500)
        items = resp.get('Items', [])
        stats = {
            'total': len(items),
            'byStatus': {}, 'byPaymentStatus': {},
            'totalPaymentAmount': 0, 'capturedAmount': 0, 'pendingAmount': 0,
        }
        for item in items:
            s = item.get('status', 'open')
            ps = item.get('paymentStatus', 'none')
            amt = int(item.get('paymentAmount', 0))
            stats['byStatus'][s] = stats['byStatus'].get(s, 0) + 1
            # Bucketed on the raw value, deliberately: this breakdown is for spotting which
            # spellings are actually in the table, and canonicalising it here would hide that.
            stats['byPaymentStatus'][ps] = stats['byPaymentStatus'].get(ps, 0) + 1
            # The money totals are canonical, because they are sums rather than a breakdown. A row
            # stored as `paid` was counted in neither bucket while still landing in
            # `totalPaymentAmount`, so captured + pending did not reconcile to the total and the
            # shortfall looked like missing data rather than a vocabulary mismatch.
            payment_state = pay_status.canonical(ps)
            if payment_state == pay_status.CAPTURED:
                stats['capturedAmount'] += amt
            elif payment_state == pay_status.PENDING:
                stats['pendingAmount'] += amt
            stats['totalPaymentAmount'] += amt
        return _resp(200, stats)
    except Exception as e:
        logger.error(f'Flow submission stats error: {e}')
        return _resp(500, {'error': str(e)})


# ============================================================================
# FLOW A/B TESTING
# ============================================================================

def _get_ab_test_flow_id(flow_code: str, phone: str) -> str:
    """For A/B testing: return flow ID based on deterministic phone hash split."""
    config = _get_flow_registry_by_code(flow_code)
    if not config:
        return ''
    ab_str = config.get('abTestConfig', '')
    if not ab_str:
        return config.get('flowId', '')
    try:
        ab = json.loads(ab_str)
        if not ab.get('enabled'):
            return config.get('flowId', '')
        split = ab.get('splitPercent', 50)
        phone_hash = int(hashlib.md5(phone.encode()).hexdigest()[:8], 16) % 100
        if phone_hash < split:
            return config.get('flowId', '')
        return ab.get('variantB_flowId', config.get('flowId', ''))
    except Exception:
        return config.get('flowId', '')


# ============================================================================
# SLA TRACKING & AUTO-ESCALATION
# ============================================================================

def _check_sla_and_escalate(params: Dict) -> Dict:
    """Check open submissions for SLA breaches. Auto-assign after 3d, escalate after 7d."""
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        now = int(time.time())
        sla_days = int(params.get('slaDays', '7'))
        reminder_days = int(params.get('reminderDays', '3'))
        default_assignee = params.get('defaultAssignee', 'support@wecare.digital')
        resp = table.query(
            IndexName='status', KeyConditionExpression='#st = :s',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={':s': 'open'}, Limit=500,
        )
        items = resp.get('Items', [])
        actions = {'reminded': 0, 'auto_assigned': 0, 'escalated': 0, 'overdue_payments': 0}
        for item in items:
            created = int(item.get('createdAt', 0))
            if not created:
                continue
            days_old = (now - created) // 86400
            sub_id = item.get('submissionId', '')
            # Canonical, so `pending_payment`, `payment_pending`, `initiated` and `in_progress`
            # are all recognised as still-owing. The raw comparison only matched one of the five
            # spellings, so a genuinely overdue payment stored under any other never raised an SLA
            # action - it silently aged out instead of being chased.
            if (pay_status.canonical(item.get('paymentStatus')) == pay_status.PENDING
                    and days_old > sla_days):
                actions['overdue_payments'] += 1
                try:
                    table.update_item(Key={'submissionId': sub_id},
                        UpdateExpression='SET notes = :n, updatedAt = :u',
                        ExpressionAttributeValues={':n': f'OVERDUE: Payment pending {days_old}d', ':u': Decimal(str(now))})
                except Exception:
                    pass
            if days_old >= reminder_days and not item.get('assignedTo'):
                actions['auto_assigned'] += 1
                try:
                    table.update_item(Key={'submissionId': sub_id},
                        UpdateExpression='SET assignedTo = :a, #st = :s, updatedAt = :u',
                        ExpressionAttributeNames={'#st': 'status'},
                        ExpressionAttributeValues={':a': default_assignee, ':s': 'in_progress', ':u': Decimal(str(now))})
                except Exception:
                    pass
            if days_old >= sla_days and item.get('assignedTo') and item.get('status') != 'escalated':
                actions['escalated'] += 1
                try:
                    table.update_item(Key={'submissionId': sub_id},
                        UpdateExpression='SET notes = :n, #st = :s, updatedAt = :u',
                        ExpressionAttributeNames={'#st': 'status'},
                        ExpressionAttributeValues={':n': f'ESCALATED: Open for {days_old}d', ':s': 'in_progress', ':u': Decimal(str(now))})
                except Exception:
                    pass
        return _resp(200, {'actions': actions, 'checked': len(items)})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# CUSTOMER JOURNEY VIEW
# ============================================================================

def _get_customer_journey(params: Dict) -> Dict:
    """Get all flow submissions + logs for a phone number — full journey view."""
    phone = params.get('phone', '')
    if not phone:
        return _resp(400, {'error': 'phone required'})
    try:
        fs_table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        fs_resp = fs_table.query(IndexName='phone', KeyConditionExpression='phone = :p',
            ExpressionAttributeValues={':p': phone}, Limit=100)
        submissions = fs_resp.get('Items', [])
        fl_table = dynamodb.Table(FLOW_LOGS_TABLE)
        fl_resp = fl_table.query(IndexName='phone', KeyConditionExpression='phone = :p',
            ExpressionAttributeValues={':p': phone}, Limit=200)
        logs = fl_resp.get('Items', [])
        contact_id = _find_contact_by_phone(phone)
        contact = {}
        if contact_id:
            try:
                ct = dynamodb.Table(CONTACTS_TABLE)
                cr = ct.get_item(Key={'id': contact_id})
                contact = cr.get('Item', {})
            except Exception:
                pass
        for lst in [submissions, logs]:
            for item in lst:
                for k, v in item.items():
                    if isinstance(v, Decimal):
                        item[k] = int(v) if v == int(v) else float(v)
        for k, v in contact.items():
            if isinstance(v, Decimal):
                contact[k] = int(v) if v == int(v) else float(v)
        submissions.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        logs.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        flows_completed = list(set(s.get('flowCode', '') for s in submissions))
        # Canonical: a submission stored as `paid` is money this customer has paid, and the raw
        # comparison left it out of their own total.
        total_paid = sum(int(s.get('paymentAmount', 0)) for s in submissions
                         if pay_status.canonical(s.get('paymentStatus')) == pay_status.CAPTURED)
        return _resp(200, {
            'phone': phone, 'contactId': contact_id, 'contact': contact,
            'submissions': submissions, 'logs': logs,
            'summary': {'flowsCompleted': flows_completed, 'totalSubmissions': len(submissions),
                        'totalPaid': total_paid, 'totalInteractions': len(logs)},
        })
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# FLOW TEMPLATE CLONING BETWEEN WABAs
# ============================================================================

def _clone_flow_to_waba(body: Dict) -> Dict:
    """Clone a flow registry config to a different WABA with a new Meta flow ID."""
    source_flow_code = body.get('sourceFlowCode', '')
    target_waba_id = body.get('targetWabaId', '')
    target_flow_id = body.get('targetFlowId', '')
    if not source_flow_code or not target_waba_id or not target_flow_id:
        return _resp(400, {'error': 'sourceFlowCode, targetWabaId, targetFlowId required'})
    source = _get_flow_registry_by_code(source_flow_code)
    if not source:
        return _resp(404, {'error': f'Source flow {source_flow_code} not found'})
    now = int(time.time())
    clone = dict(source)
    clone['flowId'] = target_flow_id
    clone['wabaId'] = target_waba_id
    clone['status'] = 'DRAFT'
    clone['createdAt'] = Decimal(str(now))
    clone['updatedAt'] = Decimal(str(now))
    if 'publishedAt' in clone:
        del clone['publishedAt']
    try:
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        table.put_item(Item={k: v for k, v in clone.items() if v is not None and v != ''})
        global _flow_registry_cache_ts
        _flow_registry_cache_ts = 0
        _emit_event('flow_cloned', severity='info', data={
            'sourceFlowCode': source_flow_code, 'clonedFlowId': target_flow_id})
        return _resp(200, {'success': True, 'clonedFlowId': target_flow_id, 'sourceFlowCode': source_flow_code})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# WEBHOOK ALERTS (Slack/Email via SNS)
# ============================================================================

def _send_flow_alert(alert_type: str, flow_id: str, message: str, details: Dict = None):
    """Send alert via SNS topic (fans out to Slack/email subscriptions)."""
    try:
        sns = boto3.client('sns', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        topic_arn = os.environ.get('FLOW_ALERTS_SNS_TOPIC', '')
        if not topic_arn:
            logger.info(f'Flow alert (no SNS): {alert_type} - {message}')
            return
        sns.publish(TopicArn=topic_arn, Subject=f'Flow Alert: {alert_type}',
            Message=json.dumps({'alertType': alert_type, 'flowId': flow_id,
                'message': message, 'details': details or {}, 'timestamp': int(time.time())}, default=str))
    except Exception as e:
        logger.warning(f'Flow alert failed: {e}')


# ============================================================================
# CSV EXPORT FOR ACCOUNTING
# ============================================================================

def _export_submissions_csv(params: Dict) -> Dict:
    """Export flow submissions as CSV for accounting reconciliation."""
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        flow_code = params.get('flowCode', '')
        payment_status = params.get('paymentStatus', '')
        if flow_code:
            resp = table.query(IndexName='flowCode', KeyConditionExpression='flowCode = :c',
                ExpressionAttributeValues={':c': flow_code}, Limit=1000)
        elif payment_status:
            resp = table.query(IndexName='paymentStatus', KeyConditionExpression='paymentStatus = :s',
                ExpressionAttributeValues={':s': payment_status}, Limit=1000)
        else:
            resp = table.scan(Limit=1000)
        items = resp.get('Items', [])
        items.sort(key=lambda x: int(x.get('createdAt', 0)), reverse=True)
        headers = ['submissionNumber', 'flowCode', 'phone', 'senderName', 'orderId',
                    'requestType', 'subject', 'paymentStatus', 'paymentAmount', 'paymentRefId',
                    'invoiceId', 'transactionId', 'status', 'assignedTo', 'createdAt', 'paidAt']
        lines = [','.join(headers)]
        for item in items:
            row = []
            for h in headers:
                val = item.get(h, '')
                if isinstance(val, Decimal):
                    val = int(val) if val == int(val) else float(val)
                if h == 'paymentAmount' and val:
                    val = f'{int(val) / 100:.2f}'
                if h in ('createdAt', 'paidAt') and val:
                    try:
                        val = time.strftime('%Y-%m-%d %H:%M', time.gmtime(int(val)))
                    except Exception:
                        pass
                s = str(val).replace('"', '""')
                row.append(f'"{s}"' if ',' in s or '"' in s else str(s))
            lines.append(','.join(row))
        return _resp(200, {'csv': '\n'.join(lines), 'count': len(items)})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# FLOW VERSION FREEZE MONITORING
# ============================================================================

def _check_flow_version_health(params: Dict) -> Dict:
    """Check all registered flows for version freeze/expiry risks."""
    FROZEN = {'2.1', '3.0', '3.1', '4.0', '5.0'}
    RECOMMENDED = '7.3'
    SUPPORTED = {'5.1', '6.0', '6.1', '6.2', '6.3', '7.0', '7.1', '7.2', '7.3'}
    try:
        table = dynamodb.Table(FLOW_REGISTRY_TABLE)
        resp = table.scan()
        items = resp.get('Items', [])
        results = []
        for item in items:
            v = item.get('flowVersion', '')
            if v in FROZEN:
                st, msg = 'frozen', f'Version {v} is FROZEN. Upgrade to {RECOMMENDED} immediately.'
            elif v and v not in SUPPORTED:
                st, msg = 'unknown', f'Version {v} not in known supported list.'
            elif v != RECOMMENDED:
                st, msg = 'outdated', f'Version {v} supported but not recommended. Upgrade to {RECOMMENDED}.'
            else:
                st, msg = 'ok', ''
            results.append({'flowCode': item.get('flowCode', ''), 'flowName': item.get('flowName', ''),
                'flowId': item.get('flowId', ''), 'flowVersion': v,
                'dataApiVersion': item.get('dataApiVersion', ''), 'versionStatus': st, 'message': msg})
            if st == 'frozen':
                _send_flow_alert('VERSION_FROZEN', item.get('flowId', ''), msg, {'flowCode': item.get('flowCode', '')})
        return _resp(200, {'flows': results, 'recommendedVersion': RECOMMENDED})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# FLOW DATA EXCHANGE (WhatsApp Flows)
# ============================================================================
def _handle_flow_data(body: Dict, request_id: str, origin: str = '') -> Dict:
    """
    Handle WhatsApp Flow data_exchange requests with E2E encryption.
    1. Decrypt incoming encrypted payload
    2. Route to the correct flow module via flows.router
    3. Encrypt the response and return as base64 string
    
    All flow-specific logic lives in flows/ modules.
    This function is ONLY the decrypt → route → encrypt wrapper.
    """
    # Step 1: Decrypt
    encrypted_flow_data = body.get('encrypted_flow_data', '')
    encrypted_aes_key = body.get('encrypted_aes_key', '')
    initial_vector = body.get('initial_vector', '')

    if not encrypted_flow_data or not encrypted_aes_key or not initial_vector:
        return _resp(400, {'error': 'Missing encrypted flow data fields'})

    try:
        decrypted_data, aes_key, iv = _decrypt_flow_request(
            encrypted_flow_data, encrypted_aes_key, initial_vector)
    except Exception as e:
        logger.error(f'[{request_id}] Flow decryption failed: {e}')
        return _resp(421, {'error': 'Decryption failed'})

    action = decrypted_data.get('action', '')
    screen = decrypted_data.get('screen', '')
    data = decrypted_data.get('data', {})
    flow_token = decrypted_data.get('flow_token', '')

    logger.info(json.dumps({
        'flow_data': True, 'action': action, 'screen': screen,
        'data_keys': list(data.keys()), 'flow_token': mask_flow_token(flow_token),
        'requestId': request_id,
    }))

    # Step 2: Route to flow module
    # Checkout sub_actions bypass the flow router
    routing_failed = False
    sub_action = decrypted_data.get('sub_action', '')
    if sub_action and data.get('order_details'):
        response_payload = _handle_checkout_data_exchange(
            sub_action=sub_action, data=data,
            version=decrypted_data.get('version', '1.0'),
            request_id=request_id,
        )
    else:
        try:
            from flows.router import route_flow
            response_payload = route_flow(
                action=action, screen=screen, data=data,
                flow_token=flow_token, request_id=request_id,
                get_flow_registry_fn=_get_flow_registry_by_code,
                fetch_orders_fn=_fetch_orders_for_flow,
            )
        except Exception as e:
            logger.error(json.dumps({
                'event': 'flow_route_error', 'error': str(e),
                'action': action, 'screen': screen, 'requestId': request_id,
            }))
            # The exception text used to go straight into `data.error`, which is
            # rendered on the customer's handset. A Python traceback message is not
            # a message for a customer, and it discloses internals to anyone who
            # can open the flow. The detail stays in the log line above, keyed by
            # requestId; the handset gets a stable code it can bind a message to.
            routing_failed = True
            response_payload = {'data': {
                'error': 'Something went wrong. Please try again.',
                'error_code': 'FLOW_ROUTING_FAILED',
            }}

    if not response_payload:
        routing_failed = True
        response_payload = {'data': {
            'error': 'Something went wrong. Please try again.',
            'error_code': 'FLOW_NO_RESPONSE',
        }}
        logger.error(json.dumps({
            'event': 'flow_no_response_payload',
            'action': action, 'screen': screen, 'requestId': request_id,
        }))

    # A failed route used to fall through into `flow_response_full` at info level,
    # so a dropped submission read as an ordinary response in the logs. Say it
    # plainly instead, at a level an alarm can be built on.
    #
    # STILL OPEN, deliberately not guessed at: this returns HTTP 200 even when
    # routing failed, so if Meta retries only on a non-200 then a failed
    # data_exchange is never retried and the submission is silently lost. Changing
    # the status is a live behaviour change on an encrypted customer-facing
    # endpoint, and Meta's retry semantics for data_exchange are not documented
    # clearly enough to act on - the observable symptom of a non-200 is the handset
    # showing "Endpoint did not return a successful response", which suggests the
    # user sees an error rather than a retry happening. Settling it needs one
    # deliberate live test on the QA recipient. Note that retrying is now SAFE for
    # the nine flows that go through flow_completion.claim_completion, so the
    # change is available once the semantics are confirmed.
    if routing_failed:
        logger.error(json.dumps({
            'event': 'flow_data_exchange_failed_returning_200',
            'action': action, 'screen': screen,
            'errorCode': response_payload.get('data', {}).get('error_code', ''),
            'requestId': request_id,
        }))

    # Log full response for debugging
    try:
        log_payload = json.loads(json.dumps(response_payload, default=str))
        # Truncate any large values for logging
        log_data = log_payload.get('data', {})
        for k, v in log_data.items():
            if isinstance(v, str) and len(v) > 200:
                log_data[k] = v[:200] + '...(truncated)'
        logger.info(json.dumps({
            'event': 'flow_response_full', 'action': action,
            'screen': log_payload.get('screen', ''),
            'data_keys': sorted(log_data.keys()),
            'requestId': request_id,
        }))
    except Exception:
        logger.info(json.dumps({
            'event': 'flow_response', 'action': action,
            'screen': response_payload.get('screen', ''),
            'data_keys': list(response_payload.get('data', {}).keys()),
            'requestId': request_id,
        }))

    # Step 3: Encrypt
    try:
        encrypted_response = _encrypt_flow_response(response_payload, aes_key, iv)
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': encrypted_response,
        }
    except Exception as e:
        logger.error(f'[{request_id}] Flow encryption failed: {e}')
        return _resp(500, {'error': 'Encryption failed'})




def _save_submit_request(phone: str, order_id: str, subject: str, description: str,
                         flow_token: str, request_id: str, request_number: str = '',
                         payment_ref_id: str = '',
                         requires_payment: bool = False,
                         payment_amount: int = 0,
                         phone_number_id: str = '') -> str:
    """Save flow submission to SubmitRequests DynamoDB table.
    
    CRITICAL: requires_payment and payment_amount MUST come from the flow registry.
    Do NOT hardcode payment values — each flow defines its own payment config.
    phone_number_id is resolved from flow_token by the caller.
    """
    try:
        now = int(time.time())
        submission_id = str(uuid.uuid4())
        ref_id = payment_ref_id if requires_payment else ''

        # Look up contact info
        contact_id = _find_contact_by_phone(phone)
        sender_name = ''
        if contact_id:
            try:
                table = dynamodb.Table(CONTACTS_TABLE)
                resp = table.get_item(Key={'id': contact_id}, ProjectionExpression='#n', ExpressionAttributeNames={'#n': 'name'})
                sender_name = resp.get('Item', {}).get('name', '')
            except Exception as e:
                logger.warning(f'Contact name lookup failed for {contact_id}: {e}')

        # Payment fields are flow-specific — only set if flow requires payment
        pay_status = 'pending' if requires_payment else 'none'
        pay_amount = payment_amount if requires_payment else 0

        item = {
            'id': submission_id,
            'requestId': request_id,
            'requestNumber': request_number,
            'flowToken': flow_token,
            'phone': phone,
            'senderName': sender_name,
            'contactId': contact_id,
            'orderId': order_id,
            'subject': subject,
            'description': description,
            'paymentStatus': pay_status,
            'paymentReferenceId': ref_id,
            'paymentAmount': pay_amount,
            'phoneNumberId': phone_number_id,
            'createdAt': Decimal(str(now)),
            'updatedAt': Decimal(str(now)),
        }

        table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
        table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})

        logger.info(json.dumps({
            'event': 'submit_request_saved',
            'submissionId': submission_id,
            'orderId': order_id,
            'phone': phone[:6] + '***' if phone else '',
            'referenceId': ref_id,
            'requiresPayment': requires_payment,
            'paymentAmount': pay_amount,
            'phoneNumberId': phone_number_id,
            'requestId': request_id,
        }))
        return submission_id
    except Exception as e:
        logger.error(json.dumps({
            'event': 'submit_request_save_error',
            'error': str(e),
            'orderId': order_id,
            'requestId': request_id,
        }))
        return ''


# ═══════════════════════════════════════════════════════════════════════════
# CHECKOUT BUTTON TEMPLATE — data_exchange sub-action handlers
# Per Meta docs: https://developers.facebook.com/docs/whatsapp/cloud-api/
#   payments-api/payments-in/checkout-button-templates
# Handles: get_coupons, apply_coupon, remove_coupon, apply_shipping
# Uses same E2E encryption as WhatsApp Flows (shared /flow-data endpoint).
# ═══════════════════════════════════════════════════════════════════════════

# Coupon pricing is owned by the cart/invoice redemption authority. The legacy
# checkout-button callbacks have no reservation or settlement linkage, so they
# cannot issue offers or change an already-created payment's coupon amount.

# ── Pin-code based shipping rates (paise) ──
# Zone → base rate. Kolkata (700xxx) is local, rest of WB is regional, others are national.
# Override per pin prefix for granular control.
SHIPPING_RATES_PAISE = {
    'local': 4900,       # ₹49 — Kolkata (700xxx)
    'regional': 7900,    # ₹79 — West Bengal (71x-74x)
    'metro': 9900,       # ₹99 — Delhi, Mumbai, Bangalore, Chennai, Hyderabad
    'national': 14900,   # ₹149 — Rest of India
    'remote': 24900,     # ₹249 — NE states, J&K, Ladakh, A&N
}

# Pin prefix → zone mapping
_PIN_ZONE_MAP = {
    '700': 'local', '711': 'regional', '712': 'regional', '713': 'regional',
    '721': 'regional', '722': 'regional', '723': 'regional', '731': 'regional',
    '732': 'regional', '733': 'regional', '734': 'regional', '735': 'regional',
    '736': 'regional', '741': 'regional', '742': 'regional', '743': 'regional',
    # Metros
    '110': 'metro', '400': 'metro', '560': 'metro', '600': 'metro', '500': 'metro',
    # Remote / NE
    '781': 'remote', '782': 'remote', '783': 'remote', '784': 'remote', '785': 'remote',
    '786': 'remote', '787': 'remote', '788': 'remote', '790': 'remote', '791': 'remote',
    '792': 'remote', '793': 'remote', '794': 'remote', '795': 'remote', '796': 'remote',
    '797': 'remote', '798': 'remote', '799': 'remote',
    '180': 'remote', '181': 'remote', '190': 'remote', '191': 'remote', '192': 'remote',
    '193': 'remote', '194': 'remote', '744': 'remote',
}


def _get_shipping_zone(pin_code: str) -> str:
    """Determine shipping zone from 6-digit Indian pin code."""
    pin = (pin_code or '').strip()[:6]
    if len(pin) < 3:
        return 'national'
    prefix3 = pin[:3]
    if prefix3 in _PIN_ZONE_MAP:
        return _PIN_ZONE_MAP[prefix3]
    # Fallback: check 2-digit prefix for broad state mapping
    prefix2 = pin[:2]
    if prefix2 in ('70', '71', '72', '73', '74'):
        return 'regional'  # West Bengal
    return 'national'


def _calculate_shipping_paise(pin_code: str) -> int:
    """Calculate shipping cost in paise based on pin code zone."""
    zone = _get_shipping_zone(pin_code)
    return SHIPPING_RATES_PAISE.get(zone, SHIPPING_RATES_PAISE['national'])


def _recalculate_order_total(order_details: dict, coupon_discount_paise: int = 0) -> int:
    """Recalculate total_amount from order components + optional coupon discount.
    total = subtotal + shipping + tax - discount - coupon_discount
    All values in paise."""
    order = order_details.get('order', {})
    subtotal = order.get('subtotal', {}).get('value', 0)
    shipping = order.get('shipping', {}).get('value', 0)
    tax = order.get('tax', {}).get('value', 0)
    discount = order.get('discount', {}).get('value', 0)
    total = subtotal + shipping + tax - discount - coupon_discount_paise
    return max(total, 0)


def _handle_checkout_data_exchange(sub_action: str, data: dict,
                                   version: str, request_id: str) -> dict:
    """Route checkout button template data_exchange sub-actions.
    Per Meta Payments API: the decrypted payload has sub_action + data.order_details.
    Response must match Meta's expected schema per sub_action."""

    order_details = data.get('order_details', {})
    input_data = data.get('input', {})
    user_id = input_data.get('user_id', '')

    logger.info(json.dumps({
        'event': 'checkout_data_exchange',
        'sub_action': sub_action,
        'reference_id': order_details.get('reference_id', ''),
        'user_id': user_id,
        'version': version,
        'requestId': request_id,
    }))

    if sub_action == 'get_coupons':
        return _checkout_get_coupons(order_details, input_data, version, request_id)
    elif sub_action == 'apply_coupon':
        return _checkout_apply_coupon(order_details, input_data, version, request_id)
    elif sub_action == 'remove_coupon':
        return _checkout_remove_coupon(order_details, input_data, version, request_id)
    elif sub_action == 'apply_shipping':
        return _checkout_apply_shipping(order_details, input_data, version, request_id)
    else:
        logger.warning(json.dumps({
            'event': 'checkout_unknown_sub_action',
            'sub_action': sub_action, 'requestId': request_id,
        }))
        return {'data': {'error': f'Unknown sub_action: {sub_action}'}}


def _checkout_get_coupons(order_details: dict, input_data: dict,
                          version: str, request_id: str) -> dict:
    """Do not advertise unbacked discounts on an already-created payment."""
    return {'version': version, 'sub_action': 'get_coupons',
            'data': {'coupons': []}}


def _checkout_coupon_refusal(sub_action: str, version: str) -> dict:
    """Refuse before repricing: this callback cannot reserve or settle a coupon."""
    return {'version': version, 'sub_action': sub_action, 'data': {
        'error': 'Apply or remove the coupon in checkout before requesting payment.',
        'error_code': 'COUPON_REQUIRES_CHECKOUT',
    }}


def _checkout_apply_coupon(order_details: dict, input_data: dict,
                           version: str, request_id: str) -> dict:
    return _checkout_coupon_refusal('apply_coupon', version)


def _checkout_remove_coupon(order_details: dict, input_data: dict,
                            version: str, request_id: str) -> dict:
    return _checkout_coupon_refusal('remove_coupon', version)


def _checkout_apply_shipping(order_details: dict, input_data: dict,
                             version: str, request_id: str) -> dict:
    """Apply shipping address. Calculate shipping cost by pin code and update order."""
    selected_address = input_data.get('selected_address', {})
    pin_code = selected_address.get('in_pin_code', '')

    # Calculate shipping based on pin code zone
    shipping_paise = _calculate_shipping_paise(pin_code)

    # An embedded coupon amount is not an authority. Refuse before changing the
    # order rather than carrying a caller-supplied discount into a new total.
    if order_details.get('coupon'):
        return _checkout_coupon_refusal('apply_shipping', version)

    # Update shipping in order
    order_details['order']['shipping'] = {'offset': 100, 'value': shipping_paise}

    # Update shipping_info with selected_address
    if 'shipping_info' not in order_details:
        order_details['shipping_info'] = {'country': 'IN', 'addresses': []}
    order_details['shipping_info']['selected_address'] = selected_address

    # Recalculate total (with coupon discount if present)
    total = _recalculate_order_total(order_details)
    order_details['total_amount'] = {'offset': 100, 'value': total}

    zone = _get_shipping_zone(pin_code)
    logger.info(json.dumps({
        'event': 'checkout_shipping_applied',
        'pin_code': pin_code,
        'zone': zone,
        'shipping_paise': shipping_paise,
        'new_total_paise': total,
        'has_coupon': False,
        'requestId': request_id,
    }))

    return {
        'version': version,
        'sub_action': 'apply_shipping',
        'data': {'order_details': order_details},
    }


# ═══════════════════════════════════════════════════════════════════════════
# END CHECKOUT BUTTON TEMPLATE HANDLERS
# ═══════════════════════════════════════════════════════════════════════════


def _send_payment_after_flow(phone: str, order_id: str, subject: str, request_id: str,
                             request_number: str = '', payment_ref_id: str = '',
                             preferred_gateway: str = '', payment_config_name: str = '',
                             phone_number_id: str = '',
                             payment_amount_paise: int = 0,
                             flow_name: str = 'Service Request') -> str:
    """
    Create an invoice via invoice-engine, then send payment link through that invoice.
    This integrates Submit Request payments into the common invoice infrastructure
    so they appear in the Pay Flow / Invoices tab alongside all other invoices.
    
    CRITICAL: payment_amount_paise MUST be passed by the caller from flow registry.
    Do NOT hardcode any amount — each flow defines its own payment config.
    
    preferred_gateway: 'razorpay' (only supported value) — passed to invoice-engine
    payment_config_name: specific Meta PG config name ('WECAREDIGITAL' or 'WECAREUPI')
    
    Returns the invoice number (or empty string on failure).
    """
    if not payment_amount_paise:
        logger.error(json.dumps({
            'event': 'flow_payment_no_amount',
            'phone': phone[:6] + '***' if phone else 'none',
            'requestId': request_id,
            'reason': 'payment_amount_paise is 0 — caller must pass flow-specific amount',
        }))
        return ''

    logger.info(json.dumps({
        'event': 'flow_payment_start',
        'phone': phone[:6] + '***' if phone else 'none',
        'orderId': order_id,
        'subject': subject,
        'requestNumber': request_number,
        'paymentRefId': payment_ref_id,
        'paymentAmountPaise': payment_amount_paise,
        'flowName': flow_name,
        'requestId': request_id,
    }))

    if not phone:
        logger.warning(f'[{request_id}] No phone for payment — skipping')
        return ''

    ref_id = payment_ref_id or f'WD-PAY-{uuid.uuid4().hex[:8].upper()}'

    # Look up contactId from DynamoDB
    contact_id = _find_contact_by_phone(phone)
    sender_name = ''
    if contact_id:
        try:
            table = dynamodb.Table(CONTACTS_TABLE)
            resp = table.get_item(Key={'id': contact_id}, ProjectionExpression='#n', ExpressionAttributeNames={'#n': 'name'})
            sender_name = resp.get('Item', {}).get('name', '')
        except Exception as e:
            logger.warning(f'Contact name lookup failed for {contact_id}: {e}')

    # Step 1: Create invoice via invoice-engine Lambda
    # Amount comes from flow registry — convert paise to rupees for invoice
    amount_rupees = payment_amount_paise / 100
    invoice_body = {
        'referenceId': ref_id,
        'customerPhone': phone,
        'customerName': sender_name,
        'contactId': contact_id or '',
        'orderId': order_id,
        'entryPoint': 'submit_request_flow',
        'purpose': f'{flow_name}: {subject}' if subject else flow_name,
        'notes': f'Request #{request_number}' if request_number else '',
        'gstin': '19AAFFW7196L1Z8',
        'gstRate': 18,
        'items': [{
            'name': flow_name,
            'amount': amount_rupees,
            'quantity': 1,
            'gstRate': 18,
        }],
    }
    # Add gateway preference from flow registry config
    if preferred_gateway:
        invoice_body['preferredGateway'] = preferred_gateway
    if payment_config_name:
        invoice_body['paymentConfiguration'] = payment_config_name

    try:
        create_resp = lambda_client.invoke(
            FunctionName=INVOICE_ENGINE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'requestContext': {'http': {'method': 'POST'}},
                'rawPath': '/invoices',
                'body': json.dumps(invoice_body),
            })
        )
        create_result = json.loads(create_resp['Payload'].read())
        create_body = json.loads(create_result.get('body', '{}'))
        invoice_id = create_body.get('invoiceId', '')
        invoice_number = create_body.get('invoiceNumber', '')
        is_dedup = create_body.get('deduplicated', False)

        logger.info(json.dumps({
            'event': 'flow_invoice_created',
            'invoiceId': invoice_id,
            'invoiceNumber': invoice_number,
            'referenceId': ref_id,
            'deduplicated': is_dedup,
            'phone': phone[:6] + '***',
            'requestId': request_id,
        }))

        if not invoice_id:
            logger.error(json.dumps({
                'event': 'flow_invoice_create_failed',
                'response': create_body,
                'requestId': request_id,
            }))
            # Fallback: send payment directly via outbound (old behavior)
            _send_payment_direct_fallback(phone, order_id, subject, ref_id, contact_id, request_id,
                                          phone_number_id=phone_number_id,
                                          payment_amount_paise=payment_amount_paise)
            return ''

        # Store invoiceId on the SubmitRequest record
        try:
            sr_table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
            sr_resp = sr_table.query(
                IndexName='paymentReferenceId',
                KeyConditionExpression='paymentReferenceId = :ref',
                ExpressionAttributeValues={':ref': ref_id},
                Limit=1,
            )
            sr_items = sr_resp.get('Items', [])
            if sr_items:
                sr_table.update_item(
                    Key={'id': sr_items[0]['id']},
                    UpdateExpression='SET invoiceId = :inv, invoiceNumber = :inum, updatedAt = :u',
                    ExpressionAttributeValues={
                        ':inv': invoice_id,
                        ':inum': invoice_number,
                        ':u': Decimal(str(int(time.time()))),
                    },
                )
        except Exception as link_err:
            logger.warning(json.dumps({
                'event': 'flow_invoice_link_error',
                'error': str(link_err),
                'requestId': request_id,
            }))

        # Step 2: Send payment link via invoice-engine (uses common infrastructure)
        # phone_number_id is already resolved from flow_token by the caller
        send_phone_id = phone_number_id or PHONE1_ID
        if not phone_number_id:
            logger.warning(json.dumps({
                'event': 'flow_payment_no_phone_id',
                'phone_suffix': phone[-4:] if phone else '',
                'defaulting_to': PHONE1_ID,
                'requestId': request_id,
            }))
        send_resp = lambda_client.invoke(
            FunctionName=INVOICE_ENGINE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'requestContext': {'http': {'method': 'POST'}},
                'rawPath': '/invoices/send-payment-link',
                'body': json.dumps({
                    'invoiceId': invoice_id,
                    'phoneNumberId': send_phone_id,
                }),
            })
        )
        send_result = json.loads(send_resp['Payload'].read())
        send_status = send_result.get('statusCode', 0)

        logger.info(json.dumps({
            'event': 'flow_payment_link_sent',
            'invoiceId': invoice_id,
            'invoiceNumber': invoice_number,
            'referenceId': ref_id,
            'phone': phone[:6] + '***',
            'statusCode': send_status,
            'requestId': request_id,
        }))

        return invoice_number

    except Exception as e:
        logger.error(json.dumps({
            'event': 'flow_invoice_payment_error',
            'phone': phone[:6] + '***',
            'error': str(e),
            'requestId': request_id,
        }))
        # Fallback: send payment directly via outbound (old behavior)
        try:
            _send_payment_direct_fallback(phone, order_id, subject, ref_id, contact_id, request_id,
                                          phone_number_id=phone_number_id,
                                          payment_amount_paise=payment_amount_paise)
        except Exception as fb_err:
            logger.error(json.dumps({
                'event': 'flow_payment_fallback_error',
                'error': str(fb_err),
                'requestId': request_id,
            }))
        return ''


def _send_payment_direct_fallback(phone: str, order_id: str, subject: str,
                                   ref_id: str, contact_id: str, request_id: str,
                                   phone_number_id: str = '', payment_amount_paise: int = 0):
    """Fallback: send payment directly via outbound-whatsapp if invoice-engine fails.
    
    CRITICAL: payment_amount_paise MUST be passed by the caller from flow registry.
    Do NOT default to any hardcoded amount.
    """
    # Use the explicitly passed phone_number_id — do NOT guess from customer phone
    send_phone_id = phone_number_id or PHONE1_ID
    if not phone_number_id:
        logger.warning(json.dumps({
            'event': 'flow_payment_fallback_no_phone_id',
            'phone_suffix': phone[-4:] if phone else '',
            'defaulting_to': PHONE1_ID,
        }))
    if not payment_amount_paise:
        logger.error(json.dumps({
            'event': 'flow_payment_fallback_no_amount',
            'phone_suffix': phone[-4:] if phone else '',
            'requestId': request_id,
            'reason': 'payment_amount_paise is 0 — caller must pass flow-specific amount',
        }))
        return
    amount_paise = payment_amount_paise
    gst_rate = 18
    gst_paise = round(amount_paise * gst_rate / 100)

    payload = {
        'body': json.dumps({
            'contactId': contact_id or '',
            'recipientPhone': phone if not contact_id else '',
            'phoneNumberId': send_phone_id,
            'isInteractivePayment': True,
            'orderDetails': {
                'reference_id': ref_id,
                'type': 'digital-goods',
                'currency': 'INR',
                'itemName': 'Service Request',
                'quantity': 1,
                'gstRate': gst_rate,
                'gstin': '19AAFFW7196L1Z8',
                'orderId': order_id,
                'order': {
                    'status': 'pending',
                    'items': [{
                        'retailer_id': 'SR-REQUEST',
                        'name': 'Service Request',
                        'amount': {'value': amount_paise, 'offset': 100},
                        'quantity': 1,
                        'gstRate': gst_rate,
                    }],
                    'subtotal': {'value': amount_paise, 'offset': 100},
                    'discount': {'value': 0, 'offset': 100, 'description': 'None'},
                    'shipping': {'value': 0, 'offset': 100, 'description': 'N/A'},
                    'tax': {'value': gst_paise, 'offset': 100, 'description': f'GST {gst_rate}%'},
                },
            }
        })
    }

    response = lambda_client.invoke(
        FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
        InvocationType='Event',
        Payload=json.dumps(payload)
    )

    logger.info(json.dumps({
        'event': 'flow_payment_fallback_sent',
        'phone': phone[:6] + '***',
        'referenceId': ref_id,
        'lambdaStatus': response.get('StatusCode'),
        'requestId': request_id,
    }))


def _send_flow_confirmation(phone: str, order_id: str, subject: str, request_id: str,
                            request_number: str = '', payment_ref_id: str = '',
                            invoice_number: str = '', phone_number_id: str = '',
                            flow_config: Dict = None):
    """Send a WhatsApp text confirmation after a flow completes.
    Uses flow_config to determine if payment is required and customize the message.
    
    CRITICAL: phone_number_id MUST be passed by the caller (resolved from flow_token).
    Do NOT fall back to _get_phone_number_id_for_phone — that causes wrong routing.
    """
    if not phone:
        return
    try:
        # Use the explicitly passed phone_number_id — do NOT guess from customer phone
        send_phone_id = phone_number_id or PHONE1_ID
        if not phone_number_id:
            logger.error(json.dumps({
                'event': 'flow_confirmation_no_phone_id_CRITICAL',
                'phone_suffix': phone[-4:] if phone else '',
                'defaulting_to': PHONE1_ID,
                'requestId': request_id,
                'reason': 'phone_number_id was not passed — this causes wrong routing',
            }))

        # Build confirmation based on flow config
        requires_payment = (flow_config or {}).get('requiresPayment', False)
        payment_amount = (flow_config or {}).get('paymentAmount', 0)
        flow_name = (flow_config or {}).get('flowName', 'Request')
        flow_code = (flow_config or {}).get('flowCode', '')

        if requires_payment and payment_amount:
            amount_display = f'₹{payment_amount / 100:.0f}' if payment_amount >= 100 else f'₹{payment_amount}'
            inv_line = f'*Invoice:* {invoice_number}\n' if invoice_number else ''
            msg = (
                '\u2705 *{flow_name} Submitted Successfully*\n\n'
                f'*Request No:* {request_number}\n'
                f'{inv_line}'
                f'*Payment Ref:* {payment_ref_id}\n'
                f'*Amount:* {amount_display}\n'
                f'*Order:* {order_id}\n'
                f'*Subject:* {subject}\n\n'
                'Please complete the payment using the payment link sent above \u2b06\ufe0f\n'
                'Our team will review your request within 24 hours.\n\n'
                '_Thank you for choosing WECARE.DIGITAL_'
            ).replace('{flow_name}', flow_name)
        else:
            msg = (
                '\u2705 *{flow_name} Submitted Successfully*\n\n'
                f'*Reference:* {request_number}\n'
                f'*Subject:* {subject}\n\n'
                'Our team will review your submission within 24 hours.\n\n'
                '_Thank you for choosing WECARE.DIGITAL_'
            ).replace('{flow_name}', flow_name)

        payload = {
            'body': json.dumps({
                'recipientPhone': phone,
                'phoneNumberId': send_phone_id,
                'content': msg,
            })
        }
        lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )
        logger.info(json.dumps({
            'event': 'flow_confirmation_sent',
            'phone': phone[:6] + '***',
            'phoneNumberId': send_phone_id,
            'flowName': flow_name,
            'flowCode': flow_code,
            'requiresPayment': requires_payment,
            'paymentAmount': payment_amount,
            'requestId': request_id,
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'flow_confirmation_error',
            'error': str(e),
            'requestId': request_id,
        }))


def _get_phone_number_id_for_flow(flow_token: str) -> str:
    """Determine which WABA phone number ID to use based on flow_token context.
    
    New token format: {prefix}-{uuid}-waba-{1|2}-ph-{customer_phone}
    Legacy format:    {prefix}-{uuid}-ph-{customer_phone}
    
    The waba segment explicitly encodes which business phone sent the flow.
    This eliminates the guessing that caused Phone 2 messages to go to Phone 1.
    """
    if not flow_token:
        logger.warning(json.dumps({
            'event': 'flow_phone_resolution_no_token',
            'defaulting_to': PHONE1_ID,
        }))
        return PHONE1_ID

    # New format: extract waba-{1|2} segment
    if '-waba-' in flow_token:
        try:
            waba_part = flow_token.split('-waba-')[1].split('-')[0]
            resolved = PHONE2_ID if waba_part == '2' else PHONE1_ID
            logger.info(json.dumps({
                'event': 'flow_phone_resolved_from_waba_segment',
                'waba_segment': waba_part,
                'resolved_phone_id': resolved,
                'flow_token_prefix': mask_flow_token(flow_token),
            }))
            return resolved
        except (IndexError, ValueError):
            pass

    # Legacy format fallback: no waba segment, use PHONE1_ID (old tokens)
    logger.warning(json.dumps({
        'event': 'flow_phone_resolution_legacy_token',
        'flow_token_prefix': mask_flow_token(flow_token),
        'defaulting_to': PHONE1_ID,
        'reason': 'no -waba- segment found (legacy token)',
    }))
    return PHONE1_ID


# ── Phone-to-WABA mapping ──
# Maps customer phone prefixes to the WABA phone that serves them.
# This is used to determine which business phone should send confirmations.
PHONE_TO_WABA_MAP = {
    '919903300044': PHONE2_ID,  # Phone 2's own number
    '919330994400': PHONE1_ID,  # Phone 1's own number
}


def _get_phone_number_id_for_phone(phone: str) -> str:
    """Determine which WABA phone number ID to use for sending messages to this phone.
    
    This resolves which business phone (Phone 1 or Phone 2) should be used
    to send outbound messages. The logic:
    1. Check if the phone is one of our own business phones (direct match)
    2. Default to PHONE1_ID only as last resort with warning
    
    NOTE: The customer's phone number does NOT determine which WABA to use.
    The WABA is determined by which phone RECEIVED the original inbound message.
    Callers should use _get_phone_number_id_for_flow(flow_token) instead when possible.
    """
    if not phone:
        logger.warning(json.dumps({
            'event': 'phone_resolution_no_phone',
            'defaulting_to': PHONE1_ID,
        }))
        return PHONE1_ID
    
    clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    
    # Direct match: is this phone one of our business numbers?
    if clean in PHONE_TO_WABA_MAP:
        return PHONE_TO_WABA_MAP[clean]
    
    # Default — caller should prefer _get_phone_number_id_for_flow() instead
    return PHONE1_ID


def _find_contact_by_phone(phone: str) -> str:
    """Look up contactId from DynamoDB Contacts table by phone number using GSI."""
    if not phone:
        return ''
    try:
        # Normalize: strip + and spaces
        clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        with_plus = f'+{clean}'
        table = dynamodb.Table(CONTACTS_TABLE)
        # Try with + prefix first (contacts are stored as +91XXXXXXXXXX), then without
        for variant in [with_plus, clean]:
            try:
                resp = table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :p',
                    ExpressionAttributeValues={':p': variant},
                    Limit=1,
                    ProjectionExpression='id'
                )
                items = resp.get('Items', [])
                if items:
                    return items[0].get('id', '')
            except Exception as e:
                logger.debug(f'Contact query variant failed: {e}')
    except Exception as e:
        logger.warning(f'Contact lookup failed for {phone[:6]}***: {e}')
    return ''



def _fetch_orders_for_flow(phone: str, email: str) -> list:
    """Thin wrapper — delegates to flows.orders module (order-centric)."""
    from flows.orders import fetch_orders_for_flow
    return fetch_orders_for_flow(phone, email)


def _list_submit_requests(params: Dict) -> Dict:
    """List submit request submissions from DynamoDB."""
    try:
        table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
        limit = min(int(params.get('limit', '100')), 500)
        payment_status = params.get('paymentStatus', '')

        if payment_status:
            resp = table.query(
                IndexName='paymentStatus',
                KeyConditionExpression='paymentStatus = :s',
                ExpressionAttributeValues={':s': payment_status},
                ScanIndexForward=False,
                Limit=limit,
            )
        else:
            resp = table.scan(Limit=limit)

        items = resp.get('Items', [])
        now = int(time.time())
        # Convert Decimal to int/float for JSON + add computed fields
        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = int(v) if v == int(v) else float(v)
            # Add days old + expiry flag for pending payments
            created = item.get('createdAt', 0)
            if created:
                days_old = (now - created) // 86400
                item['daysOld'] = days_old
                # Mark as expired if pending for more than 7 days. Canonical for the same reason as
                # the SLA sweep above: four other spellings mean the same "still owing".
                if (pay_status.canonical(item.get('paymentStatus')) == pay_status.PENDING
                        and days_old > 7):
                    item['isExpired'] = True

        # Sort by createdAt descending
        items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)

        return _resp(200, {'requests': items, 'count': len(items)})
    except Exception as e:
        logger.error(f'List submit requests error: {e}')
        return _resp(500, {'error': str(e)})


def _log_flow_event(flow_token: str, phone: str, action: str, screen: str,
                    data_keys: list, request_id: str, data: dict = None):
    """
    Log a flow interaction event to SubmitRequestsTable for audit trail.
    Uses type='flow_log' to distinguish from actual submissions.
    Captures full submitted data for comprehensive logging.
    """
    try:
        now = int(time.time())
        table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
        item = {
            'id': f'flog-{uuid.uuid4().hex[:12]}',
            'type': 'flow_log',
            'flowToken': flow_token,
            'phone': phone,
            'action': action,
            'screen': screen,
            'dataKeys': data_keys,
            'requestId': request_id,
            'createdAt': Decimal(str(now)),
        }

        # Capture full submitted data for comprehensive flow logs
        if data and isinstance(data, dict):
            # Store individual known fields for easy querying
            for field in ('order_id', 'subject', 'description', 'email'):
                if data.get(field):
                    item[field] = str(data[field])
            # Store full data snapshot as JSON string (for any extra fields)
            try:
                item['flowData'] = json.dumps(data, default=str)
            except Exception as e:
                logger.debug(f'Flow data serialization failed: {e}')

        table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
    except Exception as e:
        logger.warning(f'Flow log write failed: {e}')


def _list_flow_logs(params: Dict) -> Dict:
    """List flow interaction logs from SubmitRequestsTable (type=flow_log)."""
    try:
        table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
        limit = min(int(params.get('limit', '200')), 500)
        phone_filter = params.get('phone', '')

        # Scan for flow_log type records with full pagination
        filter_expr = '#t = :t'
        expr_names = {'#t': 'type'}
        expr_values = {':t': 'flow_log'}

        if phone_filter:
            filter_expr += ' AND contains(phone, :ph)'
            expr_values[':ph'] = phone_filter.replace('+', '').replace(' ', '')

        items = []
        scan_kwargs = {
            'FilterExpression': filter_expr,
            'ExpressionAttributeNames': expr_names,
            'ExpressionAttributeValues': expr_values,
        }
        while len(items) < limit:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get('Items', []))
            if 'LastEvaluatedKey' not in resp:
                break
            scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

        # Trim to limit
        items = items[:limit]

        for item in items:
            for k, v in item.items():
                if isinstance(v, Decimal):
                    item[k] = int(v) if v == int(v) else float(v)

        items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
        return _resp(200, {'logs': items, 'count': len(items)})
    except Exception as e:
        logger.error(f'List flow logs error: {e}')
        return _resp(500, {'error': str(e)})


def _handle_async_post_submit(event: Dict, request_id: str) -> Dict:
    """
    Handle async post-submit actions: optionally create invoice + send payment link,
    then send confirmation. Payment is ONLY sent if requires_payment is True.
    Called via async Lambda invocation from the REVIEW screen handler.
    
    CRITICAL: phone_number_id is passed from the REVIEW handler which resolved it
    from the flow_token's waba segment. This ensures confirmations go to the correct phone.
    """
    phone = event.get('phone', '')
    phone_number_id = event.get('phone_number_id', '')
    if not phone_number_id:
        # Fallback: should not happen, but log warning
        logger.warning(json.dumps({
            'event': 'async_post_submit_no_phone_id',
            'phone_suffix': phone[-4:] if phone else '',
            'requestId': request_id,
        }))
        phone_number_id = PHONE1_ID
    order_id = event.get('order_id', '')
    subject = event.get('subject', '')
    request_number = event.get('request_number', '')
    payment_ref_id = event.get('payment_ref_id', '')
    preferred_gateway = event.get('preferred_gateway', '')
    payment_config_name = event.get('payment_config_name', '')
    requires_payment = event.get('requires_payment', False)
    payment_amount = event.get('payment_amount', 0)
    flow_name = event.get('flow_name', 'Request')
    flow_code = event.get('flow_code', '')

    # Build a minimal flow_config dict for confirmation message
    flow_config = {
        'requiresPayment': requires_payment,
        'paymentAmount': payment_amount,
        'flowName': flow_name,
        'flowCode': flow_code,
    }

    logger.info(json.dumps({
        'event': 'async_post_submit_start',
        'phone': phone[:6] + '***' if phone else '',
        'phoneNumberId': phone_number_id,
        'requestNumber': request_number,
        'requiresPayment': requires_payment,
        'paymentAmount': payment_amount,
        'flowCode': flow_code,
        'requestId': request_id,
    }))

    # Step 1: Create invoice + send payment link ONLY if flow requires payment
    invoice_number = ''
    if requires_payment and payment_ref_id:
        if not payment_amount:
            logger.error(json.dumps({
                'event': 'async_payment_no_amount',
                'reason': 'requires_payment=True but payment_amount=0',
                'flowCode': flow_code,
                'requestId': request_id,
            }))
        else:
            try:
                invoice_number = _send_payment_after_flow(
                    phone=phone, order_id=order_id,
                    subject=subject, request_id=request_id,
                    request_number=request_number,
                    payment_ref_id=payment_ref_id,
                    preferred_gateway=preferred_gateway,
                    payment_config_name=payment_config_name,
                    phone_number_id=phone_number_id,
                    payment_amount_paise=payment_amount,
                    flow_name=flow_name,
                ) or ''
            except Exception as pay_err:
                logger.error(json.dumps({
                    'event': 'async_payment_error',
                    'error': str(pay_err),
                    'requestId': request_id,
                }))
    else:
        logger.info(json.dumps({
            'event': 'async_post_submit_no_payment',
            'reason': 'flow does not require payment',
            'flowCode': flow_code,
            'requestId': request_id,
        }))

    # Step 2: Send confirmation text (always, for all flows)
    try:
        _send_flow_confirmation(
            phone=phone, order_id=order_id, subject=subject,
            request_id=request_id, request_number=request_number,
            payment_ref_id=payment_ref_id,
            invoice_number=invoice_number,
            phone_number_id=phone_number_id,
            flow_config=flow_config,
        )
    except Exception as conf_err:
        logger.error(json.dumps({
            'event': 'async_confirmation_error',
            'error': str(conf_err),
            'requestId': request_id,
        }))

    # Step 3: Update FlowSubmissionsTable with invoiceId (if invoice was created)
    if invoice_number and payment_ref_id:
        try:
            fs_table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
            fs_resp = fs_table.query(
                IndexName='paymentRefId',
                KeyConditionExpression='paymentRefId = :ref',
                ExpressionAttributeValues={':ref': payment_ref_id},
                Limit=1,
            )
            fs_items = fs_resp.get('Items', [])
            if fs_items:
                fs_table.update_item(
                    Key={'submissionId': fs_items[0]['submissionId']},
                    UpdateExpression='SET invoiceId = :inv, updatedAt = :u',
                    ExpressionAttributeValues={
                        ':inv': invoice_number,
                        ':u': Decimal(str(int(time.time()))),
                    },
                )
                logger.info(f'FlowSubmission updated with invoiceId for paymentRefId={payment_ref_id}')
        except Exception as fs_err:
            logger.warning(f'FlowSubmission invoice link failed: {fs_err}')

    # Step 4: Update OrdersTable — increment requestCount, set has_open_request
    if order_id and order_id.startswith('WD-ORD'):
        try:
            orders_table_name = os.environ.get('ORDERS_TABLE', 'stack-wecare-digital-OrderTable')
            ot = dynamodb.Table(orders_table_name)
            now = Decimal(str(int(time.time())))
            ot.update_item(
                Key={'orderId': order_id},
                UpdateExpression='SET updatedAt = :u ADD requestCount :one',
                ExpressionAttributeValues={
                    ':u': now,
                    ':one': 1,
                },
            )
            logger.info(json.dumps({
                'event': 'order_request_count_incremented',
                'orderId': order_id,
                'requestId': request_id,
            }))
        except Exception as ot_err:
            logger.warning(f'OrdersTable requestCount update failed: {ot_err}')

    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'status': 'ok'})}


# ============================================================================
# HANDLER
# ============================================================================
# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def _verify_webhook_signature(event: Dict[str, Any], request_id: str) -> bool:
    """Verify Meta's `X-Hub-Signature-256` against either WABA app secret.

    Delegates to `lambda_utils.meta_signature`, the same implementation the
    `/whatsapp` ingress and `POST /whatsapp/inbound` use.

    Replaced a local copy that returned **True** when no app secret was
    configured, commented "fail open only if secret not configured (dev/test)".
    Nothing in this function ever called it, which is the only reason that was not
    a live hole - but a fail-open verifier sitting in the file is a trap for
    whoever wires it up next, and it was already cited in
    `docs/SECURITY_AND_SECRETS.md` as evidence that webhooks are verified.

    Retained rather than deleted because `_verify_webhook_signature` is named in
    the security checklist and is the correct guard for any Meta callback added to
    this function later. It now fails closed: no secret means no trust.
    """
    # Both app secrets are offered, because a callback may be signed by either
    # WABA's app. Note `WABA2_IDS` is an empty set in this function, so
    # `_get_app_secret(waba_id=...)` can never select the WABA2 key - reading the
    # cache directly is the only way to actually try it.
    primary = _get_app_secret()  # also forces the secret to load into _token_cache
    secondary = _token_cache.get('app_secret_waba2', '')
    ok, reason = meta_signature.verify(event, [primary, secondary])
    if not ok:
        logger.warning(json.dumps({
            'event': 'webhook_signature_rejected',
            'reason': reason,
            'requestId': request_id,
        }))
    return ok


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE MODULE HANDLERS — Orders, Documents, FAQ, Appointments, RX Slots,
# Enterprise Assist, Reviews, Service (submit/amend/track/drafts)
# Imported from service_api module (bundled with this Lambda)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from service_api import (
        _list_orders as _svc_list_orders, _get_order as _svc_get_order,
        _create_order as _svc_create_order, _update_order as _svc_update_order,
        _get_order_submissions as _svc_get_order_submissions, _sync_orders as _svc_sync_orders,
        _submit_request as _svc_submit_request, _amend_request as _svc_amend_request,
        _track_order as _svc_track_order, _get_status_history as _svc_get_status_history,
        _save_draft as _svc_save_draft, _get_draft as _svc_get_draft, _delete_draft as _svc_delete_draft,
        _list_documents as _svc_list_documents, _get_document as _svc_get_document,
        _update_document as _svc_update_document, _get_document_download_url as _svc_get_document_download,
        _create_document as _svc_create_document,
        _list_faqs as _svc_list_faqs, _create_faq as _svc_create_faq,
        _update_faq as _svc_update_faq, _delete_faq as _svc_delete_faq,
        _list_appointments as _svc_list_appointments, _create_appointment as _svc_create_appointment,
        _update_appointment as _svc_update_appointment,
        _list_rx_slots as _svc_list_rx_slots, _create_rx_slot as _svc_create_rx_slot,
        _update_rx_slot as _svc_update_rx_slot,
        _list_enterprise_cases as _svc_list_enterprise_cases, _create_enterprise_case as _svc_create_enterprise_case,
        _update_enterprise_case as _svc_update_enterprise_case,
        _list_reviews as _svc_list_reviews, _create_review as _svc_create_review,
        _update_review as _svc_update_review,
        _extract_path_param as _svc_path_param,
    )
    _SVC_AVAILABLE = True
    logger.info('Service module loaded successfully')
except ImportError as _svc_err:
    _SVC_AVAILABLE = False
    logger.warning(f'Service module not available: {_svc_err}')

    def _svc_unavailable(*args, **kwargs):
        return _resp(501, {'error': 'Service module not deployed. Bundle service_api.py with this Lambda.'})

    _svc_list_orders = _svc_get_order = _svc_create_order = _svc_update_order = _svc_unavailable
    _svc_get_order_submissions = _svc_sync_orders = _svc_submit_request = _svc_unavailable
    _svc_amend_request = _svc_track_order = _svc_get_status_history = _svc_unavailable
    _svc_save_draft = _svc_get_draft = _svc_delete_draft = _svc_unavailable
    _svc_list_documents = _svc_get_document = _svc_update_document = _svc_unavailable
    _svc_get_document_download = _svc_create_document = _svc_unavailable
    _svc_list_faqs = _svc_create_faq = _svc_update_faq = _svc_delete_faq = _svc_unavailable
    _svc_list_appointments = _svc_create_appointment = _svc_update_appointment = _svc_unavailable
    _svc_list_rx_slots = _svc_create_rx_slot = _svc_update_rx_slot = _svc_unavailable
    _svc_list_enterprise_cases = _svc_create_enterprise_case = _svc_update_enterprise_case = _svc_unavailable
    _svc_list_reviews = _svc_create_review = _svc_update_review = _svc_unavailable
    _svc_path_param = lambda path, resource: path.split(f'/{resource}/')[-1].split('/')[0].split('?')[0] if f'/{resource}/' in path else ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    if event.get('internalAction') == 'customerInvoiceCopy':
        from flows.customer_invoice import handle
        return handle(event, lambda name: _graph_api('2094615664435155/message_templates',
            params={'name': name, 'fields': 'name,status,language,components', 'limit': 100}, waba_id='2094615664435155'),
            lambda_client, s3_client)

    if event.get('internalAction') == 'prepareCustomerOrdersFlow':
        from flows.customer_orders import prepare
        return prepare(event)

    if event.get('internalAction') == 'serviceDesignDrafts':
        from flows.service_design_drafts import handle
        return handle(event, _graph_api, _create_flow, _upload_flow_asset, _get_flow, _update_flow)

    if event.get('internalAction') in ('catalogServiceReadiness', 'serviceReview'):
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return _resp(403, {'error': 'Internal invocation required'})
        if event['internalAction'] == 'catalogServiceReadiness':
            from flows.catalog_services import readiness
            return readiness(_get_flow, _graph_api)
        from flows.paid_submit_request import send_review
        return send_review(event, lambda_client)

    if event.get('internalAction') == 'catalogLifecycle':
        from flows.catalog_lifecycle import handle
        return handle(event, _graph_api)

    if event.get('internalAction') == 'customerCommand':
        from flows.customer_commands import handle
        return handle(event, lambda_client)

    if event.get('internalAction') == 'catalogService':
        from flows.catalog_services import handle
        return handle(event, lambda_client)

    if event.get('internalAction') == 'preparePaidSubmitRequest':
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return _resp(403, {'error': 'Internal invocation required'})
        from flows.paid_submit_request import prepare_and_send
        return prepare_and_send(event, lambda_client, _get_flow)

    # Handle async post-submit actions (invoked by REVIEW screen handler)
    if event.get('_async_action') == 'flow_post_submit':
        return _handle_async_post_submit(event, request_id)

    rc = event.get('requestContext', {})
    http = rc.get('http', {})
    method = http.get('method', event.get('httpMethod', 'GET'))
    path = http.get('path', '') or event.get('rawPath', '') or event.get('path', '')
    params = event.get('queryStringParameters') or {}

    if method == 'OPTIONS':
        return _resp(200, {})

    # Enforce auth for every route except the one genuinely self-authenticating
    # endpoint: `/wa-business/flow-data`, the Meta Flows data-exchange callback,
    # which proves authenticity by RSA+AES-GCM decryption (only the holder of our
    # private key can produce a payload we can decrypt). That single path is the
    # entire contents of AUTH_SKIP_PATHS. Internal Lambda invokes are auto-exempt.
    #
    # `/wa-business/webhooks` used to be exempt too, on the stated grounds that it
    # "authenticates via verify token". It does not. It is not a Meta callback at
    # all - it is the management surface for Meta's `subscribed_apps` API, and
    # nothing authenticated it:
    #
    #   DELETE  unsubscribes the WABA from every webhook field, which silently
    #           stops all inbound WhatsApp message delivery
    #   POST    forwards `override_callback_uri` straight to Meta, which would
    #           repoint production inbound webhooks at a caller-chosen URL
    #
    # Measured unauthenticated against production on 2026-09-21:
    # `GET /wa-business/webhooks` returned 400 "wabaId required" - past auth and
    # inside the handler - while `GET /wa-business/profile` returned 401.
    auth_result = require_auth(event)
    if auth_result is not None:
        return auth_result

    # Note: WhatsApp Flows data_exchange uses E2E encryption (RSA + AES-GCM)
    # for authentication — NOT x-hub-signature-256. The encrypted payload itself
    # proves authenticity because only the holder of the private key can decrypt it.
    # Signature verification is only for regular webhooks, not flow-data.

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    logger.info(f'[{request_id}] {method} {path}')

    try:
        if '/profile' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_business_profile(phone_id)
            return _update_business_profile(phone_id, body)

        elif '/messages/send/' in path:
            if method == 'POST':
                return _route_send_message(path, body)
            return _resp(405, {'error': 'POST only'})

        elif '/template-ttl/rules' in path:
            return _get_ttl_rules()

        elif '/cost-flags' in path:
            return _get_cost_flags()

        elif '/template-ttl/validate' in path:
            if method == 'POST':
                return _validate_template_ttl_route(body)
            return _resp(405, {'error': 'POST only'})

        elif '/templates/' in path and path.rstrip('/').endswith('/ttl'):
            if method == 'POST':
                template_id = _svc_path_param(path, 'templates')
                waba_id = params.get('wabaId') or body.get('wabaId')
                return _update_template_ttl(template_id, body, waba_id)
            return _resp(405, {'error': 'POST only'})

        elif '/media/resumable' in path:
            phone_id = params.get('phoneId') or body.get('phoneId') or ''
            if method != 'POST':
                return _resp(405, {'error': 'POST only'})
            if path.rstrip('/').endswith('/session'):
                return _resumable_session(body)
            session_id = _svc_path_param(path, 'resumable')
            if path.rstrip('/').endswith('/chunk'):
                return _resumable_chunk(session_id, body)
            if path.rstrip('/').endswith('/finish'):
                return _resumable_finish(session_id, body)
            return _resp(404, {'error': f'Unknown media resumable path: {path}'})

        elif '/media' in path:
            phone_id = params.get('phoneId') or body.get('phoneId') or ''
            media_id = _svc_path_param(path, 'media')
            if method == 'POST':
                return _upload_media(body)
            elif method == 'GET':
                return _get_media(media_id, phone_id, params)
            elif method == 'DELETE':
                return _delete_media(media_id, phone_id)
            return _resp(405, {'error': 'GET/POST/DELETE only'})

        elif '/flows/publish' in path:
            return _publish_flow(params.get('flowId') or body.get('flowId'))
        elif '/flows/deprecate' in path:
            return _deprecate_flow(params.get('flowId') or body.get('flowId'),
                                   params.get('wabaId') or body.get('wabaId'))
        elif '/flows/preview' in path:
            return _get_flow_preview(params.get('flowId') or body.get('flowId'))
        elif '/flows/assets' in path:
            if method == 'POST':
                return _upload_flow_asset(params.get('flowId') or body.get('flowId') or '', body)
            return _resp(405, {'error': 'POST only'})
        elif '/flows/migrate' in path:
            if method == 'POST':
                return _migrate_flows(body)
            return _resp(405, {'error': 'POST only'})
        elif '/flows/sync' in path:
            if method == 'POST':
                return _sync_flows(params, body)
            return _resp(405, {'error': 'POST only'})
        elif '/flows' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            flow_id = params.get('flowId') or body.get('flowId')
            if method == 'GET':
                return _get_flow(flow_id) if flow_id else _list_flows(waba_id or '')
            elif method == 'POST':
                return _create_flow(waba_id or '', body)
            elif method == 'PUT':
                return _update_flow(flow_id or '', body)
            elif method == 'DELETE':
                return _delete_flow(flow_id or '')

        elif '/webhooks' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            if method == 'GET':
                return _get_webhook_subscriptions(waba_id)
            elif method == 'POST':
                return _subscribe_webhook(waba_id, body)
            elif method == 'DELETE':
                return _unsubscribe_webhook(waba_id, body)

        elif '/assigned-users' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            if method == 'GET':
                return _list_assigned_users(waba_id, params)
            elif method == 'POST':
                return _add_assigned_user(waba_id, body)
            elif method == 'DELETE':
                return _remove_assigned_user(waba_id, body)

        elif '/bot' in path:
            bot_id = params.get('botId') or body.get('botId')
            if not bot_id:
                return _resp(400, {'error': 'botId required'})
            if method == 'GET':
                return _get_bot_details(bot_id, params)

        elif '/assigned-wabas' in path:
            user_id = params.get('userId') or body.get('userId')
            if not user_id:
                return _resp(400, {'error': 'userId required'})
            return _list_assigned_wabas(user_id, params)

        elif '/schedules' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            if method == 'GET':
                return _list_schedules(waba_id, params)
            elif method == 'POST':
                return _create_schedule(waba_id, body)

        elif '/commerce-settings' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_commerce_settings(phone_id)
            return _update_commerce_settings(phone_id, body)

        elif '/catalog-products' in path:
            if method == 'GET':
                return _list_catalog_products(params.get('catalogId') or params.get('catalog_id'), params)
            elif method == 'POST':
                return _create_catalog_product(body)
            elif method == 'PUT':
                return _update_catalog_product(params.get('productId') or params.get('product_id') or body.get('productId') or '', body)
            elif method == 'DELETE':
                return _delete_catalog_product(params.get('productId') or params.get('product_id') or body.get('productId') or '')
            return _resp(405, {'error': 'GET/POST/PUT/DELETE only'})

        elif '/catalog-feed/fetch' in path:
            if method == 'POST':
                return _trigger_catalog_feed_fetch(body.get('feedId') or params.get('feedId'), body.get('url', ''))
            return _resp(405, {'error': 'POST only'})

        elif '/catalog-feed' in path:
            if method == 'GET':
                return _list_catalog_feeds(params.get('catalogId') or params.get('catalog_id'))
            elif method == 'POST':
                return _upsert_catalog_feed(body)
            return _resp(405, {'error': 'GET or POST'})

        elif '/qr-codes' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            qr_id = params.get('qrId') or body.get('qrId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'DELETE':
                return _delete_qr_code(phone_id, qr_id or '')
            if method == 'POST':
                return _create_qr_code(phone_id, body)
            return _get_qr_code(phone_id, qr_id or '', params)

        elif '/conversational-automation' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_conversational_automation(phone_id)
            return _configure_conversational_automation(phone_id, body)

        elif '/throughput' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            return _get_throughput(phone_id)

        elif '/direct-send/samples' in path:
            # 410, not a deleted branch. Dispatch matches on `'/direct-send' in path`,
            # so removing this branch would let the path fall through to `_direct_send`
            # and answer `400 phoneId required` — a silent misroute that looks like a
            # caller bug. An explicit gone-with-a-reason is correct whether or not the
            # API Gateway route is ever deleted.
            return _resp(410, {
                'error': ('Direct Send sample upload was removed — '
                          '/{waba_id}/message_samples is not a documented Meta endpoint'),
                'removed': '2026-10-06',
            })

        elif '/direct-send/templates' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            return _list_generated_templates(waba_id)

        elif '/direct-send' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'POST':
                return _direct_send(phone_id, body)
            return _resp(405, {'error': 'POST only'})

        elif '/mm-onboarding-status' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            return _get_mm_onboarding_status(waba_id)

        elif '/mm-conversion-metrics' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            return _get_mm_conversion_metrics(waba_id, params)

        elif '/marketing-message' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'POST':
                return _send_marketing_message(phone_id, body)
            return _resp(405, {'error': 'POST only'})

        elif '/catalog-flow-map' in path:
            if method == 'GET':
                return _list_catalog_flow_map(params)
            elif method in ('POST', 'PUT'):
                return _upsert_catalog_flow_map(body)
            return _resp(405, {'error': 'GET/POST only'})

        elif '/ai-routing' in path:
            if method == 'GET':
                return _list_ai_routing(params)
            elif method in ('POST', 'PUT'):
                return _update_ai_routing(body)
            return _resp(405, {'error': 'GET/POST only'})

        elif '/capi' in path:
            # Conversions API for Business Messaging (whatsapp_business_manage_events)
            if '/capi/event' in path:
                if method == 'POST':
                    return _capi_log_event(body)
                return _resp(405, {'error': 'POST only'})
            elif '/capi/dataset' in path:
                if method == 'POST':
                    return _capi_create_dataset(body)
                return _resp(405, {'error': 'POST only'})
            else:
                if method == 'GET':
                    return _capi_status(params)
                return _resp(405, {'error': 'GET only'})

        elif '/link-preview' in path:
            return _check_link_preview(params.get('url') or body.get('url') or '')

        elif '/ai-pricing-policy' in path:
            if method == 'GET':
                return _list_ai_policy_markets()
            elif method in ('POST', 'PUT'):
                return _upsert_ai_policy_market(body)
            elif method == 'DELETE':
                return _delete_ai_policy_market(params.get('countryCode') or body.get('countryCode') or '')

        elif '/oba-status' in path:
            # READ-ONLY. '/oba-status' shares no substring with any existing matched
            # fragment, so placement is free; it sits with the other account reads.
            waba_id = params.get('wabaId') or body.get('wabaId')
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            return _get_oba_status(waba_id)

        elif '/groups/participants' in path:
            return _manage_group_participants(params.get('groupId') or body.get('groupId') or '', body)
        elif '/groups/send' in path:
            return _send_group_message(
                params.get('phoneId') or body.get('phoneId') or '',
                params.get('groupId') or body.get('groupId') or '', body)
        elif '/groups/image' in path:
            group_id = params.get('groupId') or body.get('groupId') or ''
            image_url = body.get('imageUrl', '')
            return _set_group_image(group_id, image_url)
        elif '/groups/invite-link' in path:
            group_id = params.get('groupId') or body.get('groupId') or ''
            if method == 'GET':
                return _get_group_invite_link(group_id)
            elif method == 'POST':
                return _reset_group_invite_link(group_id)
        elif '/groups/join-requests' in path:
            group_id = params.get('groupId') or body.get('groupId') or ''
            if method == 'GET':
                return _get_group_join_requests(group_id)
            elif method == 'POST':
                return _approve_group_join_requests(group_id, body)
            elif method == 'DELETE':
                return _reject_group_join_requests(group_id, body)
        elif '/groups' in path:
            waba_id = params.get('wabaId') or body.get('wabaId') or ''
            group_id = params.get('groupId') or body.get('groupId')
            phone_id = params.get('phoneId') or body.get('phoneId')
            if method == 'GET':
                return _get_group(group_id) if group_id else _list_groups(waba_id, phone_id)
            elif method == 'POST':
                return _create_group(phone_id or '', body)
            elif method == 'PUT':
                return _update_group(group_id or '', body)
            elif method == 'DELETE':
                return _delete_group(group_id or '')

        elif '/interactive-list' in path:
            # The route stays declared so it answers honestly rather than 404ing.
            return _resp(410, {'error': 'interactive messaging removed',
                               'detail': 'the interactive-list sender was deleted on 2026-10-02'})

        elif '/calling-settings' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_calling_settings(phone_id)
            return _update_calling_settings(phone_id, body)

        elif '/payment-config/check' in path:
            waba_id = params.get('wabaId') or body.get('wabaId')
            return _check_payment_gateway(waba_id)

        elif '/payment-lookup' in path:
            phone_id = params.get('phoneId') or body.get('phoneId', '')
            config_name = params.get('configName') or body.get('configName', '')
            reference_id = params.get('referenceId') or body.get('referenceId', '')
            return _payment_lookup(phone_id, config_name, reference_id)

        elif '/payment-refund' in path:
            phone_id = body.get('phoneId', '')
            reference_id = body.get('referenceId', '')
            config_name = body.get('configName', '')
            amount_paise = int(body.get('amountPaise', 0))
            speed = body.get('speed', 'normal')
            return _payment_refund(phone_id, reference_id, config_name, amount_paise, speed)

        elif path.rstrip('/').endswith('/payment-config/raw'):
            # Retired diagnostics must not fall through to phone-level settings.
            # Native readiness consumes the normalized list; this route never writes.
            return _resp(410, {'error': 'Payment configuration raw endpoint retired',
                'replacement': '/wa-business/payment-config/list',
                'diagnostic': '/wa-business/payment-config/check'})

        elif '/payment-config/list' in path:
            # Flattened live `{data:[config,...]}` for payment_readiness.evaluate. checkout's
            # readiness fetch calls this; it needs the normalised list, not the human
            # paymentConfig/liveReadiness view that /payment-config returns.
            wid = params.get('wabaId') or body.get('wabaId') or WABA1_ID
            return _resp(200, _read_payment_configurations(wid))

        elif '/payment-config' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_payment_config(phone_id)

        elif '/phone-settings' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_phone_settings(phone_id)
            return _update_phone_settings(phone_id, body)

        elif '/username/suggestions' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            return _get_username_suggestions(phone_id)

        elif '/username' in path:
            phone_id = params.get('phoneId') or body.get('phoneId')
            if not phone_id:
                return _resp(400, {'error': 'phoneId required'})
            if method == 'GET':
                return _get_username(phone_id)
            elif method == 'POST':
                return _claim_username(phone_id, body)
            elif method == 'DELETE':
                return _delete_username(phone_id)

        elif '/instagram' in path:
            if '/instagram/accounts' in path:
                business_id = params.get('businessId') or body.get('businessId') or ''
                if not business_id:
                    return _resp(400, {'error': 'businessId required'})
                return _get_instagram_accounts(business_id)
            else:
                waba_id = params.get('wabaId') or body.get('wabaId') or ''
                if not waba_id:
                    return _resp(400, {'error': 'wabaId required'})
                return _get_waba_instagram_link(waba_id)

        elif '/block-users' in path:
            waba_id = params.get('wabaId') or body.get('wabaId') or ''
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            if method == 'GET':
                return _get_blocked_users(waba_id, params)
            elif method == 'POST':
                return _block_users(waba_id, body)

        elif '/unblock-users' in path:
            waba_id = params.get('wabaId') or body.get('wabaId') or ''
            if not waba_id:
                return _resp(400, {'error': 'wabaId required'})
            if method == 'POST':
                return _unblock_users(waba_id, body)

        elif '/contact-book' in path:
            phone_id = params.get('phoneId') or body.get('phoneId') or ''
            if method == 'DELETE':
                return _delete_contact_book(phone_id, params.get('bsuid') or body.get('bsuid') or '')
            return _resp(405, {'error': 'DELETE only'})

        elif '/parent-bsuid-accounts' in path:
            if method == 'GET':
                return _get_parent_bsuid_accounts(params.get('businessId') or body.get('businessId') or '')
            return _resp(405, {'error': 'GET only'})

        elif '/flow-data' in path:
            if method == 'POST':
                return _handle_flow_data(body, request_id, origin)
            return _resp(405, {'error': 'POST only'})

        # Dedicated checkout endpoint (same handler, separate URL for Meta linking)
        # Link this URL with payment configuration via Meta support:
        # https://api.wecare.digital/wa-business/checkout-data
        elif '/checkout-data' in path:
            if method == 'POST':
                return _handle_flow_data(body, request_id, origin)
            return _resp(405, {'error': 'POST only'})

        # Flow Management Engine routes
        elif '/flow-registry' in path:
            if method == 'GET':
                return _list_flow_registry(params)
            elif method == 'POST' or method == 'PUT':
                return _upsert_flow_registry(body)
            return _resp(405, {'error': 'GET/POST/PUT only'})

        elif '/flow-submissions/update-status' in path:
            if method == 'POST' or method == 'PATCH':
                return _update_submission_status(body)
            return _resp(405, {'error': 'POST/PATCH only'})

        elif '/flow-submissions/stats' in path:
            if method == 'GET':
                return _get_flow_submission_stats(params)
            return _resp(405, {'error': 'GET only'})

        elif '/flow-submissions/export' in path:
            if method == 'GET':
                return _export_submissions_csv(params)
            return _resp(405, {'error': 'GET only'})

        elif '/flow-submissions' in path:
            if method == 'GET':
                return _list_flow_submissions(params)
            return _resp(405, {'error': 'GET only'})

        elif '/flow-sla-check' in path:
            if method == 'POST':
                return _check_sla_and_escalate(body)
            return _resp(405, {'error': 'POST only'})

        elif '/flow-customer-journey' in path:
            if method == 'GET':
                return _get_customer_journey(params)
            return _resp(405, {'error': 'GET only'})

        elif '/flow-clone' in path:
            if method == 'POST':
                return _clone_flow_to_waba(body)
            return _resp(405, {'error': 'POST only'})

        elif '/flow-version-health' in path:
            if method == 'GET':
                return _check_flow_version_health(params)
            return _resp(405, {'error': 'GET only'})

        elif '/submit-requests' in path:
            if method == 'GET':
                return _list_submit_requests(params)
            return _resp(405, {'error': 'GET only'})

        elif '/flow-logs' in path:
            if method == 'GET':
                return _list_flow_logs(params)
            return _resp(405, {'error': 'GET only'})

        # ══════════════════════════════════════════════════════════════
        # SERVICE MODULE ROUTES (orders, documents, faq, appointments,
        # rx-slots, enterprise-assist, reviews, service/*)
        # ══════════════════════════════════════════════════════════════

        # ── ORDERS ──
        elif '/orders/sync' in path and method == 'POST':
            return _svc_sync_orders()
        elif '/orders/' in path and '/submissions' in path:
            oid = _svc_path_param(path, 'orders')
            return _svc_get_order_submissions(oid)
        elif '/orders/' in path:
            oid = _svc_path_param(path, 'orders')
            if method == 'GET':
                return _svc_get_order(oid)
            elif method in ('PATCH', 'PUT'):
                return _svc_update_order(oid, body)
        elif '/orders' in path:
            if method == 'GET':
                return _svc_list_orders(params)
            elif method == 'POST':
                return _svc_create_order(body)

        # ── SERVICE (submit/amend/track/drafts) ──
        elif '/service/submit' in path and method == 'POST':
            return _svc_submit_request(body)
        elif '/service/amend' in path and method == 'POST':
            return _svc_amend_request(body)
        elif '/service/track/' in path:
            oid = path.split('/service/track/')[-1].split('?')[0]
            return _svc_track_order(oid)
        elif '/service/history' in path:
            return _svc_get_status_history(params)
        elif '/service/drafts' in path:
            if method == 'POST':
                return _svc_save_draft(body)
            elif method == 'GET':
                fc = params.get('flowCode', path.split('/service/drafts/')[-1].split('?')[0])
                return _svc_get_draft(fc)
            elif method == 'DELETE':
                fc = path.split('/service/drafts/')[-1].split('?')[0]
                return _svc_delete_draft(fc)

        # ── DOCUMENTS ──
        elif '/documents/' in path and '/download' in path:
            did = _svc_path_param(path, 'documents')
            return _svc_get_document_download(did)
        elif '/documents/' in path:
            did = _svc_path_param(path, 'documents')
            if method == 'GET':
                return _svc_get_document(did)
            elif method in ('PUT', 'PATCH'):
                return _svc_update_document(did, body)
        elif '/documents' in path:
            if method == 'GET':
                return _svc_list_documents(params)
            elif method == 'POST':
                return _svc_create_document(body)

        # ── FAQ ──
        elif '/faq/' in path:
            fid = _svc_path_param(path, 'faq')
            if method in ('PUT', 'PATCH'):
                return _svc_update_faq(fid, body)
            elif method == 'DELETE':
                return _svc_delete_faq(fid)
        elif '/faq' in path:
            if method == 'GET':
                return _svc_list_faqs(params)
            elif method == 'POST':
                return _svc_create_faq(body)

        # ── APPOINTMENTS ──
        elif '/appointments/' in path:
            aid = _svc_path_param(path, 'appointments')
            if method in ('PUT', 'PATCH'):
                return _svc_update_appointment(aid, body)
        elif '/appointments' in path:
            if method == 'GET':
                return _svc_list_appointments(params)
            elif method == 'POST':
                return _svc_create_appointment(body)

        # ── RX SLOTS ──
        elif '/rx-slots/' in path:
            sid = _svc_path_param(path, 'rx-slots')
            if method in ('PUT', 'PATCH'):
                return _svc_update_rx_slot(sid, body)
        elif '/rx-slots' in path:
            if method == 'GET':
                return _svc_list_rx_slots(params)
            elif method == 'POST':
                return _svc_create_rx_slot(body)

        # ── ENTERPRISE ASSIST ──
        elif '/enterprise-assist/' in path:
            cid = _svc_path_param(path, 'enterprise-assist')
            if method in ('PUT', 'PATCH'):
                return _svc_update_enterprise_case(cid, body)
        elif '/enterprise-assist' in path:
            if method == 'GET':
                return _svc_list_enterprise_cases(params)
            elif method == 'POST':
                return _svc_create_enterprise_case(body)

        # ── REVIEWS ──
        elif '/reviews/' in path:
            rid = _svc_path_param(path, 'reviews')
            if method in ('PUT', 'PATCH'):
                return _svc_update_review(rid, body)
        elif '/reviews' in path:
            if method == 'GET':
                return _svc_list_reviews(params)
            elif method == 'POST':
                return _svc_create_review(body)

        return _resp(404, {'error': f'Unknown path: {path}'})
    except Exception as e:
        logger.exception(f'[{request_id}] Error')
        return _resp(500, {'error': str(e)})
