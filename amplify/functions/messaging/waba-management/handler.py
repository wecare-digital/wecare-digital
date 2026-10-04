"""
WABA Management Lambda Function

Purpose: Manage WhatsApp Business Accounts via Direct Meta Graph API.

Part 3 / Module 1 migration:
- All Meta Graph calls go through the shared MetaGraphClient (token caching,
  per-WABA token routing, appsecret_proof, retries on transient errors, and a
  normalized error envelope).
- State-changing operations are recorded to the audit log (fail-open).
- Meta errors are surfaced as a normalized envelope instead of raw exceptions.

Implements:
- GetLinkedWhatsAppBusinessAccount - Get WABA details (phone quality, limits)
- GetLinkedWhatsAppBusinessAccountPhoneNumber - Get phone details
- ListLinkedWhatsAppBusinessAccounts - List all WABAs
- DeleteWhatsAppMessageMedia - Delete uploaded media
- GetWhatsAppMessageMedia - Download media from WhatsApp
- PostWhatsAppMessageMedia - Upload media to WhatsApp for sending
- PutWhatsAppBusinessAccountEventDestinations - Subscribe/unsubscribe app to WABA
- ListTagsForResource / TagResource / UntagResource - (No Meta equivalent)

Meta Graph API Reference:
https://developers.facebook.com/docs/whatsapp/business-management-api
"""

import os
import json
import boto3
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timezone

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.middleware import require_auth
from lambda_utils.meta_client import MetaGraphClient
from lambda_utils.audit import record_audit
from lambda_utils.logging import get_logger
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sns_client = boto3.client('sns', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
apigw_client = boto3.client('apigatewayv2', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Shared Meta Graph client (handles token caching, appsecret_proof, retries,
# per-WABA token routing and normalized error envelopes).
_meta = MetaGraphClient()

# CORS management — the HTTP APIs whose CorsConfiguration this admin UI controls.
#
# `79g3bbufdh` ("wecare-api") was removed from this default on 2026-09-21 when the
# API itself was deleted. It was a dead duplicate: no custom domain mapped to it,
# it recorded zero requests in 30 days while the live API served 84,301, and its
# single route POST /ai/generate duplicated the live API's route while pointing at
# unqualified $LATEST rather than the `live` alias. It also carried
# AllowOrigins ["*"]. Listing a deleted api id here would make every CORS save
# attempt fail on a NotFoundException.
CORS_API_IDS = [s.strip() for s in os.environ.get('CORS_API_IDS', 'zllr9lrg7j').split(',') if s.strip()]
# Core origins always kept in the allowlist so the dashboard/native app can never
# be locked out, even if an admin saves a bad list.
CORS_CORE_ORIGINS = [
    # The apex, not retired-legacy-host.invalid: that subdomain was retired and only ever
    # 301'd here, and a redirecting host is useless as an allowed origin because the
    # browser matches the request origin literally.
    # app.wecare.digital removed 2026-09-28 for the same reason as stack: the host is
    # retired and NXDOMAIN, so the entry is a standing offer rather than an allowance.
    'https://wecare.digital',
    'https://www.wecare.digital',
    'https://d22dm4b0jn71jw.amplifyapp.com',
    'capacitor://localhost',   # iOS native app
    'https://localhost',       # Android native app
]
CORS_RECOMMENDED_ORIGINS = CORS_CORE_ORIGINS + [
    'https://wecare.digital',
    'https://www.wecare.digital',
    'ionic://localhost',
    'http://localhost:3000',
]
CORS_ALLOW_HEADERS = ['content-type', 'authorization', 'x-amz-date', 'x-api-key', 'x-amz-security-token']
CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']

# Environment variables
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:us-east-1:775261844268:stack-wecare-digital')

# AWS WABA ID → Meta WABA ID mapping
AWS_TO_META_WABA = {
    'waba-e47d916f3c7a47e1a34a19653893dd4b': '2094615664435155',
    'waba-dbe343f210204752b74c80a0a59631a6': '2513394156072604',
}
META_WABA_DEFAULT = '2094615664435155'

# AWS phone-number-id → Meta phone ID mapping
AWS_PHONE_TO_META = {
    'phone-number-id-waba1-direct-1016149501586345': '1016149501586345',
    'phone-number-id-waba-t-direct-1055232054343117': '1055232054343117',
}


def _resolve_meta_waba_id(aws_waba_id: str) -> str:
    """Map AWS WABA ID to Meta WABA ID.
    Accepts either AWS format (waba-xxx) or Meta numeric ID directly.
    """
    # If it's already a numeric Meta WABA ID, return as-is
    if aws_waba_id.replace('-', '').isdigit() and not aws_waba_id.startswith('waba-'):
        if aws_waba_id in AWS_TO_META_WABA.values():
            return aws_waba_id
        return aws_waba_id
    if not aws_waba_id.startswith('waba-'):
        aws_waba_id = f'waba-{aws_waba_id}'
    return AWS_TO_META_WABA.get(aws_waba_id, META_WABA_DEFAULT)


def _resolve_meta_phone_id(aws_phone_id: str) -> str:
    """
    Map AWS phone-number-id to Meta phone ID.
    For 'direct' format IDs, extract the Meta ID from the suffix.
    For old format, use the mapping dict.
    """
    if not aws_phone_id.startswith('phone-number-id-'):
        aws_phone_id = f'phone-number-id-{aws_phone_id}'

    if '-direct-' in aws_phone_id:
        return aws_phone_id.split('-direct-')[-1]

    if aws_phone_id in AWS_PHONE_TO_META:
        return AWS_PHONE_TO_META[aws_phone_id]

    return aws_phone_id.replace('phone-number-id-', '')


def _serialize_value(val):
    """Convert datetime and other non-JSON-serializable types to strings."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


def _serialize_dict(d: Dict) -> Dict:
    """Recursively serialize a dictionary for JSON."""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _serialize_dict(v)
        elif isinstance(v, list):
            result[k] = [_serialize_dict(i) if isinstance(i, dict) else _serialize_value(i) for i in v]
        else:
            result[k] = _serialize_value(v)
    return result


# Module-level per-invocation context (set in handler)
origin = ''
_actor = 'system'


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    WABA Management API Handler

    Routes:
    - GET /waba - List all linked WABAs
    - GET /waba/{wabaId} - Get WABA details
    - GET /waba/phone/{phoneNumberId} - Get phone number details
    - GET /waba/events - Get system events (template status, phone quality, account updates)
    - GET /waba/media/{mediaId} - Download media from WhatsApp
    - POST /waba/media - Upload media to WhatsApp for sending
    - DELETE /waba/media/{mediaId} - Delete WhatsApp media
    - GET /waba/{wabaId}/tags - List tags for WABA
    - POST /waba/{wabaId}/tags - Add tags to WABA
    - DELETE /waba/{wabaId}/tags - Remove tags from WABA
    - PUT /waba/{wabaId}/events - Configure event destinations
    - POST /waba/{wabaId}/subscribe-sns - Subscribe WABA to SNS topic for events
    - DELETE /waba/{wabaId}/subscribe-sns - Unsubscribe WABA from SNS topic
    - GET /waba/{wabaId}/subscribe-sns - Get current SNS subscription status
    """
    request_id = context.aws_request_id if context else 'local'
    global origin, _actor
    origin = extract_origin(event)

    request_context = event.get('requestContext', {})

    if 'http' in request_context:
        http_method = request_context.get('http', {}).get('method', 'GET')
        path = request_context.get('http', {}).get('path', '')
    else:
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '')

    if not path:
        path = event.get('rawPath', '')

    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'waba_management_request',
        'method': http_method,
        'path': path,
        'pathParams': path_params,
        'queryParams': query_params,
        'requestId': request_id
    }))

    if http_method == 'OPTIONS':
        return options_response(origin)

    # Enforce auth. All /waba/* routes are admin-only (no public Meta webhooks
    # here). Internal Lambda-to-Lambda invokes are auto-exempt by require_auth.
    auth_result = require_auth(event, required_role='Admin')
    if auth_result is not None:
        return auth_result

    _actor = (event.get('_auth') or {}).get('username') or 'system'

    try:
        body = {}
        if event.get('body'):
            body = json.loads(event.get('body', '{}'))

        if http_method == 'GET':
            if query_params.get('action') == 'cors-status':
                return _get_cors_status(request_id)
            if '/waba/events' in path:
                return _get_system_events(query_params, request_id)
            elif '/subscribe-sns' in path:
                waba_id = path_params.get('wabaId') or path.split('/waba/')[-1].split('/')[0]
                return _get_sns_subscription_status(waba_id, request_id)
            elif '/waba/media/' in path:
                media_id = path_params.get('mediaId') or path.split('/media/')[-1]
                phone_id = query_params.get('phoneNumberId', '')
                return _get_media(media_id, phone_id, query_params, request_id)
            elif '/waba/phone/' in path:
                phone_id = path_params.get('phoneNumberId') or path.split('/phone/')[-1]
                return _get_phone_number_details(phone_id, request_id)
            elif '/tags' in path:
                resource_arn = query_params.get('resourceArn', '')
                return _list_tags(resource_arn, request_id)
            elif path_params.get('wabaId') or '/waba/' in path:
                waba_id = path_params.get('wabaId') or path.split('/waba/')[-1].split('/')[0]
                if waba_id and waba_id != 'waba':
                    return _get_waba_details(waba_id, request_id)
            return _list_wabas(request_id)

        elif http_method == 'POST':
            if body.get('action') == 'cors-apply':
                return _apply_cors(body, request_id)
            if '/subscribe-sns' in path:
                waba_id = path_params.get('wabaId') or path.split('/waba/')[-1].split('/')[0]
                return _subscribe_waba_to_sns(waba_id, body, request_id)
            elif '/conversational-components' in path:
                return _push_conversational_components(body, request_id)
            elif '/waba/media' in path:
                return _post_media(body, request_id)
            elif '/tags' in path:
                return _tag_resource(body, request_id)
            elif '/migrate' in path:
                return _error_response(501, 'Phone migration is not exposed until target-WABA transfer is implemented and verified')
            elif '/request-otp' in path:
                return _request_otp(body, request_id)
            elif '/verify-otp' in path:
                return _verify_otp(body, request_id)
            elif '/register-phone' in path:
                return _register_phone(body, request_id)

        elif http_method == 'PUT':
            if '/events' in path:
                waba_id = path_params.get('wabaId') or body.get('wabaId', '')
                return _put_event_destinations(waba_id, body, request_id)

        elif http_method == 'DELETE':
            if '/subscribe-sns' in path:
                waba_id = path_params.get('wabaId') or path.split('/waba/')[-1].split('/')[0]
                return _unsubscribe_waba_from_sns(waba_id, body, request_id)
            elif '/waba/media/' in path:
                media_id = path_params.get('mediaId') or path.split('/media/')[-1]
                phone_id = query_params.get('phoneNumberId', '')
                return _delete_media(media_id, phone_id, request_id)
            elif '/tags' in path:
                return _untag_resource(body, request_id)

        return _error_response(400, 'Invalid request')

    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'waba_management_error',
            'error': str(e),
            'errorType': type(e).__name__,
            'requestId': request_id
        }))
        return _error_response(500, str(e))


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }


def _meta_error_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized Meta error envelope with an appropriate HTTP status.

    `result` is the normalized envelope returned by MetaGraphClient (i.e. it has
    an 'error' key). We map the Meta http_status through where available.
    """
    err = result.get('error', {}) if isinstance(result, dict) else {}
    status = err.get('http_status') or 502
    if status not in (400, 401, 403, 404, 422, 429, 500, 502, 503, 504):
        status = 502
    return {
        'statusCode': int(status),
        'headers': cors_headers(origin),
        'body': json.dumps(result)
    }


# ─── CORS Management (admin) ────────────────────────────────────────────────

def _get_cors_status(request_id: str) -> Dict[str, Any]:
    """Return the live CorsConfiguration for each managed HTTP API plus the
    recommended allowlist, for the admin CORS Manager UI."""
    apis = []
    for api_id in CORS_API_IDS:
        try:
            api = apigw_client.get_api(ApiId=api_id)
            cors = api.get('CorsConfiguration', {}) or {}
            apis.append({
                'apiId': api_id,
                'name': api.get('Name', ''),
                'endpoint': api.get('ApiEndpoint', ''),
                'allowOrigins': cors.get('AllowOrigins', []),
                'allowMethods': cors.get('AllowMethods', []),
                'allowHeaders': cors.get('AllowHeaders', []),
                'allowAll': cors.get('AllowOrigins', []) == ['*'],
            })
        except Exception as e:
            apis.append({'apiId': api_id, 'error': str(e)})
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({
            'apis': apis,
            'recommendedOrigins': CORS_RECOMMENDED_ORIGINS,
            'coreOrigins': CORS_CORE_ORIGINS,
        })
    }


def _apply_cors(body: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """Apply a CORS allowlist to all managed HTTP APIs.

    body: { allowAll?: bool, origins?: [str] }
    - allowAll=True  → AllowOrigins=['*']
    - otherwise      → the provided origins, with CORE origins force-merged so an
      admin can never lock the dashboard/native app out.
    """
    allow_all = bool(body.get('allowAll'))
    if allow_all:
        allow_origins = ['*']
    else:
        provided = [o.strip() for o in (body.get('origins') or []) if isinstance(o, str) and o.strip()]
        merged = CORS_CORE_ORIGINS + [o for o in provided if o not in CORS_CORE_ORIGINS]
        seen = set()
        allow_origins = [o for o in merged if not (o in seen or seen.add(o))]

    cors_cfg = {
        'AllowOrigins': allow_origins,
        'AllowMethods': CORS_ALLOW_METHODS,
        'AllowHeaders': CORS_ALLOW_HEADERS,
        'AllowCredentials': False,
        'MaxAge': 600,
    }

    results = []
    for api_id in CORS_API_IDS:
        try:
            apigw_client.update_api(ApiId=api_id, CorsConfiguration=cors_cfg)
            results.append({'apiId': api_id, 'applied': True})
        except Exception as e:
            logger.error(json.dumps({'event': 'cors_apply_error', 'apiId': api_id, 'error': str(e), 'requestId': request_id}))
            results.append({'apiId': api_id, 'applied': False, 'error': str(e)})

    logger.info(json.dumps({'event': 'cors_applied', 'allowAll': allow_all, 'originCount': len(allow_origins), 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': all(r.get('applied') for r in results), 'allowOrigins': allow_origins, 'results': results})
    }


# ─── WABA read endpoints ────────────────────────────────────────────────────

def _list_wabas(request_id: str) -> Dict[str, Any]:
    """List all linked WhatsApp Business Accounts via Meta Graph API."""
    fields = 'id,name,currency,timezone_id,message_template_namespace'
    wabas = []

    for aws_id, meta_id in AWS_TO_META_WABA.items():
        response = _meta.get(meta_id, params={'fields': fields}, token_context={'waba_id': meta_id})
        if MetaGraphClient.is_error(response):
            logger.warning(json.dumps({
                'event': 'waba_fetch_error',
                'metaWabaId': meta_id,
                'error': response.get('error', {}).get('message'),
                'requestId': request_id
            }))
            continue
        wabas.append({
            'id': response.get('id', meta_id),
            'wabaId': aws_id,
            'metaWabaId': response.get('id', meta_id),
            'wabaName': response.get('name', ''),
            'currency': response.get('currency', ''),
            'timezoneId': response.get('timezone_id', ''),
            'messageTemplateNamespace': response.get('message_template_namespace', ''),
            'arn': '',
            'registrationStatus': 'COMPLETE',
            'linkDate': '',
            'enableSending': True,
            'enableReceiving': True,
            'eventDestinations': []
        })

    logger.info(json.dumps({'event': 'wabas_listed', 'count': len(wabas), 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'wabas': wabas, 'count': len(wabas)})
    }


def _get_waba_details(waba_id: str, request_id: str) -> Dict[str, Any]:
    """Get details of a specific WABA including phone numbers with quality ratings."""
    meta_waba_id = _resolve_meta_waba_id(waba_id)
    ctx = {'waba_id': meta_waba_id}

    fields = 'id,name,currency,timezone_id,message_template_namespace,account_review_status,on_behalf_of_business_info'
    account = _meta.get(meta_waba_id, params={'fields': fields}, token_context=ctx)
    if MetaGraphClient.is_error(account):
        return _meta_error_response(account)

    phone_fields = 'id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status,is_official_business_account'
    phones_resp = _meta.get(f'{meta_waba_id}/phone_numbers', params={'fields': phone_fields}, token_context=ctx)
    if MetaGraphClient.is_error(phones_resp):
        return _meta_error_response(phones_resp)

    phone_numbers = []
    for phone in phones_resp.get('data', []):
        phone_numbers.append({
            'phoneNumberId': phone.get('id', ''),
            'phoneNumber': phone.get('display_phone_number', ''),
            'displayPhoneNumber': phone.get('display_phone_number', ''),
            'displayPhoneNumberName': phone.get('verified_name', ''),
            'qualityRating': phone.get('quality_rating', 'UNKNOWN'),
            'metaPhoneNumberId': phone.get('id', ''),
            'dataLocalizationRegion': '',
            'arn': '',
            'platformType': phone.get('platform_type', ''),
            'codeVerificationStatus': phone.get('code_verification_status', ''),
            'isOfficialBusinessAccount': phone.get('is_official_business_account', False),
        })

    waba_details = {
        'id': waba_id,
        'wabaId': account.get('id', ''),
        'wabaName': account.get('name', ''),
        'currency': account.get('currency', ''),
        'timezoneId': account.get('timezone_id', ''),
        'messageTemplateNamespace': account.get('message_template_namespace', ''),
        'accountReviewStatus': account.get('account_review_status', ''),
        'onBehalfOfBusinessInfo': account.get('on_behalf_of_business_info', {}),
        'arn': '',
        'registrationStatus': 'COMPLETE',
        'linkDate': '',
        'enableSending': True,
        'enableReceiving': True,
        'eventDestinations': [],
        'phoneNumbers': phone_numbers
    }

    logger.info(json.dumps({
        'event': 'waba_details_fetched',
        'wabaId': waba_id,
        'metaWabaId': meta_waba_id,
        'phoneCount': len(phone_numbers),
        'requestId': request_id
    }))
    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(waba_details)}


def _get_phone_number_details(phone_id: str, request_id: str) -> Dict[str, Any]:
    """Get details of a specific phone number including quality rating."""
    if not phone_id.startswith('phone-number-id-'):
        phone_id = f'phone-number-id-{phone_id}'

    meta_phone_id = _resolve_meta_phone_id(phone_id)

    fields = 'id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status,is_official_business_account'
    phone = _meta.get(meta_phone_id, params={'fields': fields}, token_context={'phone_id': meta_phone_id})
    if MetaGraphClient.is_error(phone):
        return _meta_error_response(phone)

    phone_details = {
        'phoneNumberId': phone_id,
        'phoneNumber': phone.get('display_phone_number', ''),
        'displayPhoneNumber': phone.get('display_phone_number', ''),
        'displayPhoneNumberName': phone.get('verified_name', ''),
        'qualityRating': phone.get('quality_rating', 'UNKNOWN'),
        'metaPhoneNumberId': phone.get('id', ''),
        'dataLocalizationRegion': '',
        'arn': '',
        'linkedWabaId': '',
        'platformType': phone.get('platform_type', ''),
        'codeVerificationStatus': phone.get('code_verification_status', ''),
        'isOfficialBusinessAccount': phone.get('is_official_business_account', False),
    }

    logger.info(json.dumps({
        'event': 'phone_details_fetched',
        'phoneNumberId': phone_id,
        'metaPhoneId': meta_phone_id,
        'qualityRating': phone_details['qualityRating'],
        'requestId': request_id
    }))
    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(phone_details)}


def _get_system_events(query_params: Dict, request_id: str) -> Dict[str, Any]:
    """Get system events from SystemConfig table (template status / phone quality / account updates)."""
    try:
        event_type = query_params.get('type', 'all')
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        events = {'templateStatus': [], 'phoneQuality': [], 'accountUpdates': []}

        mapping = [
            ('template_status', 'templateStatus', 'whatsapp_events_template_status'),
            ('phone_quality', 'phoneQuality', 'whatsapp_events_phone_quality'),
            ('account_update', 'accountUpdates', 'whatsapp_events_account_update'),
        ]
        for type_key, out_key, config_id in mapping:
            if event_type in ('all', type_key):
                try:
                    response = config_table.get_item(Key={'id': config_id})
                    if 'Item' in response:
                        events[out_key] = json.loads(response['Item'].get('configValue', '[]'))
                except Exception as e:
                    logger.warning(f'Failed to fetch {type_key} events: {str(e)}')

        logger.info(json.dumps({
            'event': 'system_events_fetched',
            'templateStatusCount': len(events['templateStatus']),
            'phoneQualityCount': len(events['phoneQuality']),
            'accountUpdatesCount': len(events['accountUpdates']),
            'requestId': request_id
        }))
        return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(events)}
    except Exception as e:
        # Surface total failures instead of masking them as an empty 200.
        # (Per-event-type failures are already handled gracefully above.)
        logger.error(json.dumps({'event': 'get_system_events_error', 'error': str(e), 'requestId': request_id}))
        return {
            'statusCode': 500,
            'headers': cors_headers(origin),
            'body': json.dumps({'error': 'Failed to fetch system events'})
        }


# ─── Media ──────────────────────────────────────────────────────────────────

def _delete_media(media_id: str, phone_number_id: str, request_id: str) -> Dict[str, Any]:
    """Delete media from WhatsApp. Meta Graph API: DELETE /{media_id}."""
    if not media_id:
        return _error_response(400, 'mediaId is required')
    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    response = _meta.delete(media_id, token_context={'phone_id': meta_phone_id})
    if MetaGraphClient.is_error(response):
        return _meta_error_response(response)

    success = response.get('success', False)
    record_audit(action='media.delete', actor=_actor, resource_type='media',
                 resource_id=media_id, details={'phoneNumberId': phone_number_id})
    logger.info(json.dumps({
        'event': 'media_deleted', 'mediaId': media_id,
        'phoneNumberId': phone_number_id, 'success': success, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': success, 'mediaId': media_id})
    }


def _get_media(media_id: str, phone_number_id: str, query_params: Dict, request_id: str) -> Dict[str, Any]:
    """Download media from WhatsApp. GET /{media_id} for URL, then download the binary to S3."""
    if not media_id:
        return _error_response(400, 'mediaId is required')
    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)
    ctx = {'phone_id': meta_phone_id}

    metadata_only = query_params.get('metadataOnly', 'false').lower() == 'true'

    media_info = _meta.get(media_id, token_context=ctx)
    if MetaGraphClient.is_error(media_info):
        return _meta_error_response(media_info)

    result = {
        'mediaId': media_id,
        'mimeType': media_info.get('mime_type', ''),
        'fileSize': media_info.get('file_size', 0),
    }

    if not metadata_only:
        media_url = media_info.get('url', '')
        if media_url:
            try:
                media_bytes = _meta.download_file(media_url, token_context=ctx)
            except Exception as e:
                logger.error(json.dumps({'event': 'get_media_download_error', 'mediaId': media_id,
                                         'error': str(e), 'requestId': request_id}))
                return _error_response(502, f'Failed to download media binary: {str(e)}')

            s3_key = media_paths.public(
                f'stack/whatsapp-media/downloads/wecare-digital-{media_id}')
            s3.put_object(
                Bucket=MEDIA_BUCKET, Key=s3_key, Body=media_bytes,
                ContentType=media_info.get('mime_type', 'application/octet-stream')
            )
            result['s3Key'] = s3_key
            result['downloadUrl'] = s3.generate_presigned_url(
                'get_object', Params={'Bucket': MEDIA_BUCKET, 'Key': s3_key}, ExpiresIn=3600
            )

    logger.info(json.dumps({
        'event': 'media_downloaded', 'mediaId': media_id,
        'metadataOnly': metadata_only, 'requestId': request_id
    }))
    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(result)}


def _post_media(body: Dict, request_id: str) -> Dict[str, Any]:
    """Upload media to WhatsApp for sending. POST /{phone_id}/media (multipart)."""
    phone_number_id = body.get('phoneNumberId', '')
    s3_key = body.get('s3Key', '')

    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')
    if not s3_key:
        return _error_response(400, 's3Key is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    try:
        s3_obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
        file_bytes = s3_obj['Body'].read()
        content_type = s3_obj.get('ContentType', 'application/octet-stream')
    except Exception as e:
        logger.error(json.dumps({'event': 'post_media_s3_error', 's3Key': s3_key,
                                 'error': str(e), 'requestId': request_id}))
        return _error_response(400, f'Failed to read S3 object: {str(e)}')

    response = _meta.upload_multipart(
        f'{meta_phone_id}/media',
        files={'file': file_bytes},
        data={'messaging_product': 'whatsapp', 'type': content_type},
        token_context={'phone_id': meta_phone_id},
    )
    if MetaGraphClient.is_error(response):
        return _meta_error_response(response)

    result = {'mediaId': response.get('id', ''), 's3Key': s3_key}
    record_audit(action='media.upload', actor=_actor, resource_type='media',
                 resource_id=result['mediaId'], details={'phoneNumberId': phone_number_id, 's3Key': s3_key})
    logger.info(json.dumps({
        'event': 'media_uploaded', 'mediaId': result['mediaId'],
        's3Key': s3_key, 'requestId': request_id
    }))
    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(result)}


# ─── Event destinations & tags ──────────────────────────────────────────────

def _put_event_destinations(waba_id: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """Configure event destinations for WABA via /{waba_id}/subscribed_apps."""
    if not waba_id:
        return _error_response(400, 'wabaId is required')

    event_destinations = body.get('eventDestinations', [])
    meta_waba_id = _resolve_meta_waba_id(waba_id)
    ctx = {'waba_id': meta_waba_id}

    formatted_destinations = [
        {'eventDestinationArn': d.get('eventDestinationArn', ''), 'roleArn': d.get('roleArn', '')}
        for d in event_destinations
    ]

    if event_destinations:
        result = _meta.post(f'{meta_waba_id}/subscribed_apps', token_context=ctx)
    else:
        result = _meta.delete(f'{meta_waba_id}/subscribed_apps', token_context=ctx)
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    record_audit(action='event_destination.update', actor=_actor, resource_type='waba',
                 resource_id=meta_waba_id, details={'destinationCount': len(formatted_destinations)})
    logger.info(json.dumps({
        'event': 'event_destinations_updated', 'wabaId': waba_id, 'metaWabaId': meta_waba_id,
        'destinationCount': len(formatted_destinations), 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'wabaId': waba_id, 'eventDestinations': formatted_destinations})
    }


def _list_tags(resource_arn: str, request_id: str) -> Dict[str, Any]:
    """List tags for a resource. No Meta Graph API equivalent — returns empty."""
    if not resource_arn:
        return _error_response(400, 'resourceArn is required')
    logger.info(json.dumps({'event': 'tags_listed', 'resourceArn': resource_arn,
                            'tagCount': 0, 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'resourceArn': resource_arn, 'tags': [],
                            'note': 'Tagging is not supported via Meta Graph API. '})
    }


def _tag_resource(body: Dict, request_id: str) -> Dict[str, Any]:
    """Add tags to a resource. No Meta Graph API equivalent — no-op success."""
    resource_arn = body.get('resourceArn', '')
    tags = body.get('tags', [])
    if not resource_arn:
        return _error_response(400, 'resourceArn is required')
    if not tags:
        return _error_response(400, 'tags is required')

    formatted_tags = [{'key': t.get('key', ''), 'value': t.get('value', '')} for t in tags]
    logger.info(json.dumps({'event': 'resource_tagged', 'resourceArn': resource_arn,
                            'tagCount': len(formatted_tags), 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'resourceArn': resource_arn, 'tags': formatted_tags,
                            'note': 'Tagging is not supported via Meta Graph API. '})
    }


def _untag_resource(body: Dict, request_id: str) -> Dict[str, Any]:
    """Remove tags from a resource. No Meta Graph API equivalent — no-op success."""
    resource_arn = body.get('resourceArn', '')
    tag_keys = body.get('tagKeys', [])
    if not resource_arn:
        return _error_response(400, 'resourceArn is required')
    if not tag_keys:
        return _error_response(400, 'tagKeys is required')

    logger.info(json.dumps({'event': 'resource_untagged', 'resourceArn': resource_arn,
                            'tagKeysRemoved': tag_keys, 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'resourceArn': resource_arn, 'tagKeysRemoved': tag_keys,
                            'note': 'Tagging is not supported via Meta Graph API. '})
    }


# ─── SNS subscription for WABA events ───────────────────────────────────────

def _subscribe_waba_to_sns(waba_id: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """Subscribe a WABA to receive WhatsApp events. POST /{waba_id}/subscribed_apps."""
    if not waba_id:
        return _error_response(400, 'wabaId is required')

    if not waba_id.startswith('waba-') and not waba_id.replace('-', '').isdigit():
        waba_id = f'waba-{waba_id}'
    meta_waba_id = _resolve_meta_waba_id(waba_id)
    topic_arn = body.get('snsTopicArn', SNS_TOPIC_ARN)
    role_arn = body.get('roleArn', '')

    result = _meta.post(f'{meta_waba_id}/subscribed_apps', token_context={'waba_id': meta_waba_id})
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    config_table.put_item(Item={
        'id': f'waba_sns_subscription_{waba_id}',
        'configValue': json.dumps({
            'wabaId': waba_id, 'metaWabaId': meta_waba_id, 'snsTopicArn': topic_arn,
            'roleArn': role_arn, 'subscribedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), 'status': 'ACTIVE'
        }),
        'updatedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    })

    record_audit(action='webhook.subscribe', actor=_actor, resource_type='waba',
                 resource_id=meta_waba_id, details={'wabaId': waba_id, 'snsTopicArn': topic_arn})
    logger.info(json.dumps({
        'event': 'waba_subscribed_to_sns', 'wabaId': waba_id, 'metaWabaId': meta_waba_id,
        'snsTopicArn': topic_arn, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'wabaId': waba_id, 'snsTopicArn': topic_arn, 'status': 'ACTIVE'})
    }


def _unsubscribe_waba_from_sns(waba_id: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """Unsubscribe a WABA from events. DELETE /{waba_id}/subscribed_apps."""
    if not waba_id:
        return _error_response(400, 'wabaId is required')

    if not waba_id.startswith('waba-') and not waba_id.replace('-', '').isdigit():
        waba_id = f'waba-{waba_id}'
    meta_waba_id = _resolve_meta_waba_id(waba_id)

    result = _meta.delete(f'{meta_waba_id}/subscribed_apps', token_context={'waba_id': meta_waba_id})
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    config_table.put_item(Item={
        'id': f'waba_sns_subscription_{waba_id}',
        'configValue': json.dumps({
            'wabaId': waba_id, 'metaWabaId': meta_waba_id, 'snsTopicArn': '', 'roleArn': '',
            'unsubscribedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), 'status': 'INACTIVE'
        }),
        'updatedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    })

    record_audit(action='webhook.unsubscribe', actor=_actor, resource_type='waba',
                 resource_id=meta_waba_id, details={'wabaId': waba_id})
    logger.info(json.dumps({
        'event': 'waba_unsubscribed_from_sns', 'wabaId': waba_id,
        'metaWabaId': meta_waba_id, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'wabaId': waba_id, 'status': 'INACTIVE'})
    }


def _get_sns_subscription_status(waba_id: str, request_id: str) -> Dict[str, Any]:
    """Get the current SNS subscription status for a WABA (stored config + live subscribed apps)."""
    if not waba_id:
        return _error_response(400, 'wabaId is required')

    if not waba_id.startswith('waba-') and not waba_id.replace('-', '').isdigit():
        waba_id = f'waba-{waba_id}'
    meta_waba_id = _resolve_meta_waba_id(waba_id)

    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    stored_config = {}
    try:
        response = config_table.get_item(Key={'id': f'waba_sns_subscription_{waba_id}'})
        if 'Item' in response:
            stored_config = json.loads(response['Item'].get('configValue', '{}'))
    except Exception:
        pass

    live_destinations = []
    subs_resp = _meta.get(f'{meta_waba_id}/subscribed_apps', token_context={'waba_id': meta_waba_id})
    if not MetaGraphClient.is_error(subs_resp):
        live_destinations = subs_resp.get('data', []) or []

    serialized_destinations = [
        _serialize_dict(dest) if isinstance(dest, dict) else dest for dest in live_destinations
    ]

    result = {
        'wabaId': waba_id,
        'metaWabaId': meta_waba_id,
        'storedConfig': stored_config,
        'liveEventDestinations': serialized_destinations,
        'isSubscribed': len(serialized_destinations) > 0,
        'defaultTopicArn': SNS_TOPIC_ARN
    }
    logger.info(json.dumps({
        'event': 'sns_subscription_status_fetched', 'wabaId': waba_id,
        'isSubscribed': result['isSubscribed'], 'requestId': request_id
    }))
    return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps(result)}


# ─── Phone registration & migration ─────────────────────────────────────────

def _request_otp(body: Dict, request_id: str) -> Dict[str, Any]:
    """Request OTP/PIN for phone number verification. POST /{phone_id}/request_code."""
    phone_number_id = body.get('phoneNumberId', '')
    method = body.get('method', 'SMS').upper()
    language = body.get('language', 'en_US')

    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    result = _meta.post(f'{meta_phone_id}/request_code',
                        payload={'code_method': method, 'language': language},
                        token_context={'phone_id': meta_phone_id})
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    record_audit(action='phone.request_otp', actor=_actor, resource_type='phone',
                 resource_id=meta_phone_id, details={'method': method, 'language': language})
    logger.info(json.dumps({
        'event': 'otp_requested', 'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id,
        'method': method, 'language': language, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'phoneNumberId': phone_number_id, 'method': method,
                            'message': f'Verification code sent via {method}'})
    }


def _verify_otp(body: Dict, request_id: str) -> Dict[str, Any]:
    """Verify OTP/PIN code for phone number verification. POST /{phone_id}/verify_code."""
    phone_number_id = body.get('phoneNumberId', '')
    code = body.get('code', '')

    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')
    if not code:
        return _error_response(400, 'code is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    response = _meta.post(f'{meta_phone_id}/verify_code', payload={'code': str(code)},
                          token_context={'phone_id': meta_phone_id})
    if MetaGraphClient.is_error(response):
        return _meta_error_response(response)

    verified = response.get('success', False)
    record_audit(action='phone.verify_otp', actor=_actor, resource_type='phone',
                 resource_id=meta_phone_id, details={'verified': verified})
    logger.info(json.dumps({
        'event': 'otp_verified', 'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id,
        'verified': verified, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': verified, 'phoneNumberId': phone_number_id, 'verified': verified})
    }


def _register_phone(body: Dict, request_id: str) -> Dict[str, Any]:
    """Register a phone number with a WABA. POST /{phone_id}/register."""
    phone_number_id = body.get('phoneNumberId', '')
    pin = body.get('pin', '')

    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)

    register_payload = {'messaging_product': 'whatsapp'}
    if pin:
        register_payload['pin'] = str(pin)

    result = _meta.post(f'{meta_phone_id}/register', payload=register_payload,
                        token_context={'phone_id': meta_phone_id})
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    config_table.put_item(Item={
        'id': f'phone_registration_{phone_number_id}',
        'configValue': json.dumps({
            'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id, 'pin': pin,
            'registeredAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), 'status': 'REGISTERED'
        }),
        'updatedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    })

    record_audit(action='phone.register', actor=_actor, resource_type='phone',
                 resource_id=meta_phone_id, details={'hasPin': bool(pin)})
    logger.info(json.dumps({
        'event': 'phone_registered', 'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id,
        'hasPin': bool(pin), 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'phoneNumberId': phone_number_id,
                            'status': 'REGISTERED', 'hasPin': bool(pin)})
    }


def _migrate_phone(body: Dict, request_id: str) -> Dict[str, Any]:
    """Migrate a phone number between WABAs. Optionally send PIN, then register on target."""
    phone_number_id = body.get('phoneNumberId', '')
    source_waba_id = body.get('sourceWabaId', '')
    target_waba_id = body.get('targetWabaId', '')
    pin = body.get('pin', '')
    send_pin = body.get('sendPin', False)
    pin_method = body.get('pinMethod', 'SMS').upper()

    if not phone_number_id:
        return _error_response(400, 'phoneNumberId is required')
    if not target_waba_id:
        return _error_response(400, 'targetWabaId is required')

    if not phone_number_id.startswith('phone-number-id-'):
        phone_number_id = f'phone-number-id-{phone_number_id}'
    meta_phone_id = _resolve_meta_phone_id(phone_number_id)
    ctx = {'phone_id': meta_phone_id}

    # Step 1: Optionally send PIN before migration
    if send_pin:
        otp_result = _meta.post(f'{meta_phone_id}/request_code',
                                payload={'code_method': pin_method, 'language': 'en_US'},
                                token_context=ctx)
        if MetaGraphClient.is_error(otp_result):
            logger.warning(json.dumps({'event': 'migration_pin_error', 'phoneNumberId': phone_number_id,
                                       'error': otp_result.get('error', {}).get('message'), 'requestId': request_id}))
            return _meta_error_response(otp_result)
        logger.info(json.dumps({
            'event': 'migration_pin_sent', 'phoneNumberId': phone_number_id,
            'metaPhoneId': meta_phone_id, 'method': pin_method, 'requestId': request_id
        }))

    # Step 2: Register phone on target WABA
    register_payload = {'messaging_product': 'whatsapp'}
    if pin:
        register_payload['pin'] = str(pin)

    result = _meta.post(f'{meta_phone_id}/register', payload=register_payload, token_context=ctx)
    if MetaGraphClient.is_error(result):
        return _meta_error_response(result)

    # Step 3: Store migration record
    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    config_table.put_item(Item={
        'id': f'phone_migration_{phone_number_id}_{int(datetime.now(timezone.utc).replace(tzinfo=None).timestamp())}',
        'configValue': json.dumps({
            'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id,
            'sourceWabaId': source_waba_id, 'targetWabaId': target_waba_id, 'pin': pin,
            'pinSent': send_pin, 'pinMethod': pin_method,
            'migratedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), 'status': 'INITIATED'
        }),
        'updatedAt': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    })

    record_audit(action='phone.migrate', actor=_actor, resource_type='phone', resource_id=meta_phone_id,
                 details={'sourceWabaId': source_waba_id, 'targetWabaId': target_waba_id, 'pinSent': send_pin})
    logger.info(json.dumps({
        'event': 'phone_migration_initiated', 'phoneNumberId': phone_number_id, 'metaPhoneId': meta_phone_id,
        'sourceWabaId': source_waba_id, 'targetWabaId': target_waba_id, 'pinSent': send_pin, 'requestId': request_id
    }))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'phoneNumberId': phone_number_id,
                            'sourceWabaId': source_waba_id, 'targetWabaId': target_waba_id,
                            'pinSent': send_pin, 'status': 'INITIATED'})
    }


# ─── Conversational components (ice breakers + slash commands) ──────────────

# Both phone number Meta IDs
_CONV_PHONE_IDS = ['1016149501586345', '1055232054343117']


def _push_conversational_components(body: Dict, request_id: str) -> Dict[str, Any]:
    """Push ice breakers (prompts) and slash commands to both phone numbers.

    POST /{phone_id}/conversational_automation
    """
    prompts = body.get('prompts', [])
    commands = body.get('commands', [])

    if not prompts and not commands:
        return _error_response(400, 'prompts or commands required')

    payload = {}
    if prompts:
        payload['prompts'] = prompts
    if commands:
        payload['commands'] = commands

    results = []
    for phone_id in _CONV_PHONE_IDS:
        result = _meta.post(f'{phone_id}/conversational_automation', payload=payload,
                            token_context={'phone_id': phone_id})
        if MetaGraphClient.is_error(result):
            results.append({'phoneId': phone_id, 'success': False, 'error': result.get('error')})
            logger.error(json.dumps({
                'event': 'conversational_components_push_error', 'phoneId': phone_id,
                'error': result.get('error', {}).get('message'), 'requestId': request_id
            }))
        else:
            results.append({'phoneId': phone_id, 'success': True, 'result': result})
            logger.info(json.dumps({
                'event': 'conversational_components_pushed', 'phoneId': phone_id,
                'promptCount': len(prompts), 'commandCount': len(commands), 'requestId': request_id
            }))

    all_success = all(r['success'] for r in results)
    if any(r['success'] for r in results):
        record_audit(action='conversational.update', actor=_actor, resource_type='phone',
                     resource_id=','.join(_CONV_PHONE_IDS),
                     details={'promptCount': len(prompts), 'commandCount': len(commands),
                              'allSuccess': all_success})
    return {
        'statusCode': 200 if all_success else 207,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': all_success, 'results': results}),
    }
