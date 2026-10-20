import os
import json
import base64
import uuid
import hashlib
import hmac
import boto3
import urllib.request
import urllib.parse
import urllib.error
from lambda_utils import media_paths, template_status  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.response import cors_headers, options_response, extract_origin
from lambda_utils.logging import get_logger
from lambda_utils.middleware import require_auth

logger = get_logger(__name__)

origin = ''

s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
TEMPLATE_MEDIA_PREFIX = os.environ.get(
    'TEMPLATE_MEDIA_PREFIX',
    media_paths.public('stack/whatsapp-media/template-headers/'))
# The `o/` root is load-bearing: the 61 objects already in o/public/wa-tpl/ are
# referenced by Meta-APPROVED templates whose URLs are on the app.wecare.digital
# host, and that host serves this bucket through origin path `/o`.
PUBLIC_MEDIA_PREFIX = os.environ.get('PUBLIC_MEDIA_PREFIX',
                                     media_paths.public('public/wa-tpl/'))
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', 'wecare.digital/get')
DEFAULT_WABA_ID = 'waba-e47d916f3c7a47e1a34a19653893dd4b'

from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
META_GRAPH_URL = f'https://graph.facebook.com/{META_API_VERSION}'
META_APP_ID = '2238810740192680'
DEFAULT_PHONE_ID = '1016149501586345'

# WhatsApp media type → public folder mapping (short names for clean URLs)
WA_MEDIA_FOLDERS = {
    # Documents
    'application/pdf': 'docs',
    'application/msword': 'docs',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docs',
    'application/vnd.ms-excel': 'docs',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'docs',
    'application/vnd.ms-powerpoint': 'docs',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'docs',
    'text/plain': 'docs',
    # Images
    'image/jpeg': 'img',
    'image/png': 'img',
    # Videos
    'video/mp4': 'vid',
    'video/3gpp': 'vid',
    # Audio
    'audio/aac': 'aud',
    'audio/amr': 'aud',
    'audio/mpeg': 'aud',
    'audio/mp4': 'aud',
    'audio/ogg': 'aud',
    # Stickers
    'image/webp': 'stk',
}

# Max sizes per WhatsApp Cloud API
WA_MEDIA_MAX_SIZES = {
    'docs': 100 * 1024 * 1024,
    'img': 5 * 1024 * 1024,
    'vid': 16 * 1024 * 1024,
    'aud': 16 * 1024 * 1024,
    'stk': 500 * 1024,
}

AWS_TO_META_WABA = {
    'waba-e47d916f3c7a47e1a34a19653893dd4b': '2094615664435155',   # WABA1
    'waba-dbe343f210204752b74c80a0a59631a6': '2513394156072604',   # WABA2/WABA-T
}
DEFAULT_META_WABA_ID = '2094615664435155'  # WABA1

# Cached token/secret
_meta_creds = {}


def _get_meta_creds():
    """Load Meta access_token and app_secret from Secrets Manager (cached)."""
    if _meta_creds:
        return _meta_creds
    resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
    secret = json.loads(resp['SecretString'])
    _meta_creds['access_token'] = secret['access_token']
    _meta_creds['app_secret'] = secret['app_secret']
    return _meta_creds


def _appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


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
    return AWS_TO_META_WABA.get(aws_waba_id, DEFAULT_META_WABA_ID)


# Meta WABA id -> phone-number-id. Template header media MUST be uploaded to a
# phone that belongs to the SAME WABA the template is created on (WABA2 fix).
META_WABA_TO_PHONE = {
    '2094615664435155': '1016149501586345',  # WABA1
    '2513394156072604': '1055232054343117',  # WABA2/WABA-T
}


def _resolve_phone_id(waba_id) -> str:
    """Resolve the phone-number-id for the given WABA (AWS or Meta id)."""
    meta_waba = _resolve_meta_waba_id(str(waba_id or ''))
    return META_WABA_TO_PHONE.get(meta_waba, DEFAULT_PHONE_ID)


def _meta_request(url: str, method: str = 'GET', data: bytes = None, headers: dict = None) -> dict:
    """Make an authenticated request to the Meta Graph API."""
    creds = _get_meta_creds()
    token = creds['access_token']
    proof = _appsecret_proof(token, creds['app_secret'])

    sep = '&' if '?' in url else '?'
    url = f'{url}{sep}access_token={token}&appsecret_proof={proof}'

    req_headers = headers or {}
    if data and 'Content-Type' not in req_headers:
        req_headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logger.error(json.dumps({'event': 'meta_api_error', 'status': e.code, 'body': error_body}))
        try:
            err = json.loads(error_body)
            msg = err.get('error', {}).get('message', error_body)
        except Exception:
            msg = error_body
        raise RuntimeError(f'Meta API {e.code}: {msg}')


def handler(event, context):
    global origin
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        http_method = request_context.get('http', {}).get('method', 'GET')
        path = request_context.get('http', {}).get('path', '') or event.get('rawPath', '')
    else:
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '')

    query_params = event.get('queryStringParameters') or {}

    if http_method == 'OPTIONS':
        return options_response(origin)

    # Enforce auth
    auth_result = require_auth(event)
    if auth_result is not None:
        return auth_result

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
        waba_id = query_params.get('wabaId', DEFAULT_WABA_ID)
        # Don't prepend waba- to numeric Meta WABA IDs
        if not waba_id.startswith('waba-') and not waba_id.replace('-', '').isdigit():
            waba_id = f'waba-{waba_id}'

        # Route requests
        if http_method == 'GET':
            if '/templates/library' in path:
                return _list_template_library(waba_id, query_params)
            if '/templates/send-media' in path:
                return _list_send_media(query_params)
            if '/templates/presets' in path:
                preset_name = _extract_path_param(path, '/templates/presets/')
                if preset_name:
                    return _get_preset(preset_name)
                return _list_presets()
            template_id = _extract_path_param(path, '/templates/')
            if template_id and template_id not in ('library', 'analytics', 'carousel', 'carousel-media', 'media', 'from-library', 'send-media', 'presets', 'validate'):
                return _get_template_details(waba_id, template_id, query_params)
            return _list_templates(waba_id, query_params)

        elif http_method == 'POST':
            if '/templates/validate' in path:
                return _validate_template_route(body)
            if '/templates/from-library' in path:
                return _create_from_library(waba_id, body)
            if '/templates/carousel-media' in path:
                return _upload_carousel_media(waba_id, body, query_params)
            if '/templates/carousel' in path:
                return _create_carousel_template(waba_id, body)
            if '/templates/send-media' in path:
                return _upload_send_media(body)
            if '/templates/media' in path:
                return _upload_template_media(waba_id, body)
            if path.rstrip('/').endswith('/send-test'):
                template_id = _extract_path_param(path, '/templates/')
                return _send_test_template(waba_id, template_id, body)
            if path.rstrip('/').endswith('/refresh'):
                template_id = _extract_path_param(path, '/templates/')
                return _refresh_template(waba_id, template_id)
            return _create_template(waba_id, body)

        elif http_method == 'PUT':
            return _update_template(waba_id, body, query_params, path)

        elif http_method == 'DELETE':
            if '/templates/send-media' in path:
                return _delete_send_media(query_params, body)
            return _delete_template(waba_id, query_params.get('templateName', ''), query_params)

        return _error_response(400, 'Invalid request')
    except Exception as e:
        logger.error(json.dumps({'event': 'template_handler_error', 'error': str(e), 'requestId': request_id}))
        return _error_response(500, str(e))


def _extract_path_param(path: str, prefix: str) -> str:
    idx = path.find(prefix)
    if idx == -1:
        return ''
    remainder = path[idx + len(prefix):]
    return remainder.split('/')[0].split('?')[0]


# ── LIST ──

def _list_templates(waba_id, query_params):
    try:
        meta_waba_id = _resolve_meta_waba_id(waba_id)
        url = f'{META_GRAPH_URL}/{meta_waba_id}/message_templates?fields=name,status,category,language,components,id'
        limit = query_params.get('maxResults', '100')
        url += f'&limit={limit}'
        data = _meta_request(url)
        templates = []
        for t in data.get('data', []):
            templates.append({
                'metaTemplateId': t.get('id'),
                'templateName': t.get('name'),
                'templateStatus': t.get('status'),
                'templateState': template_status.canonical(t.get('status')),
                'sendable': template_status.is_sendable(t.get('status')),
            })
        return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'templates': templates})}
    except Exception as e:
        return _error_response(500, str(e))


def _list_template_library(waba_id, query_params):
    """AWS-specific list_whatsapp_template_library has no Meta Graph API equivalent."""
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({
            'templates': [],
            'note': 'Template library listing is not available via Meta Graph API. Use Meta Business Suite to browse the template library.',
        })
    }


# ── GET SINGLE TEMPLATE ──

def _get_template_details(waba_id, template_id, query_params):
    try:
        url = f'{META_GRAPH_URL}/{template_id}?fields=name,status,category,language,components,id'
        data = _meta_request(url)
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'template': {
                    'metaTemplateId': data.get('id'),
                    'templateName': data.get('name'),
                    'templateStatus': data.get('status'),
                    'templateState': template_status.canonical(data.get('status')),
                    'sendable': template_status.is_sendable(data.get('status')),
                    'components': data.get('components', []),
                    'language': data.get('language', ''),
                    'category': data.get('category', ''),
                }
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


# ── CREATE ──

def _validate_template_ttl(category, seconds):
    """Validate message_send_ttl_seconds against category. Returns error string or None."""
    if seconds is None:
        return None
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return 'message_send_ttl_seconds must be an integer'
    cat = (category or '').upper()
    if cat == 'AUTHENTICATION':
        return None if (s == -1 or 30 <= s <= 900) else 'AUTHENTICATION TTL must be 30-900 seconds (or -1 for 30 days)'
    if cat == 'UTILITY':
        return None if (s == -1 or 30 <= s <= 43200) else 'UTILITY TTL must be 30-43200 seconds (or -1 for 30 days)'
    if cat == 'MARKETING':
        return None if (43200 <= s <= 2592000) else 'MARKETING TTL must be 43200-2592000 seconds (-1 not allowed)'
    return f'Unknown template category: {category}'


def _validate_template_button_group(buttons):
    """Validate button counts and quick-reply grouping. Returns error string or None."""
    if not buttons:
        return None
    if len(buttons) > 10:
        return 'A template may have at most 10 buttons'
    counts = {}
    for b in buttons:
        t = (b.get('type') or '').upper()
        counts[t] = counts.get(t, 0) + 1
        if t in ('QUICK_REPLY', 'URL', 'PHONE_NUMBER', 'VOICE_CALL') and len(b.get('text', '')) > 25:
            return f'{t} button text must be <= 25 characters'
        if t == 'COPY_CODE' and len(str(b.get('example', ''))) > 20:
            return 'COPY_CODE example must be <= 20 characters'
        if t == 'PHONE_NUMBER' and len(str(b.get('phone_number', ''))) > 20:
            return 'PHONE_NUMBER must be <= 20 characters'
        if t == 'URL' and len(str(b.get('url', ''))) > 2000:
            return 'URL must be <= 2000 characters'
        if t == 'ORDER_DETAILS':
            if b.get('text') != 'Review and Pay':
                return 'ORDER_DETAILS button text must be exactly "Review and Pay"'
    if counts.get('COPY_CODE', 0) > 1:
        return 'At most 1 COPY_CODE button allowed'
    if counts.get('PHONE_NUMBER', 0) > 1:
        return 'At most 1 PHONE_NUMBER button allowed'
    if counts.get('URL', 0) > 2:
        return 'At most 2 URL buttons allowed'
    if counts.get('ORDER_DETAILS', 0) > 1:
        return 'At most 1 ORDER_DETAILS button allowed'
    if counts.get('QUICK_REPLY', 0) > 10:
        return 'At most 10 QUICK_REPLY buttons allowed'
    types = [(b.get('type') or '').upper() for b in buttons]
    qr = [i for i, t in enumerate(types) if t == 'QUICK_REPLY']
    if qr and (max(qr) - min(qr) + 1) != len(qr):
        return 'Quick reply buttons must be grouped together (contiguous)'
    return None


def _validate_template_definition(template_def):
    """Validate a Meta template definition (category, TTL, components, buttons). Returns error string or None."""
    category = template_def.get('category', '')
    if category and category.upper() not in ('MARKETING', 'UTILITY', 'AUTHENTICATION'):
        return f'Invalid category: {category}. Must be MARKETING, UTILITY, or AUTHENTICATION'
    ttl_err = _validate_template_ttl(category, template_def.get('message_send_ttl_seconds'))
    if ttl_err:
        return ttl_err
    has_body = False
    for comp in template_def.get('components', []):
        ctype = (comp.get('type') or '').upper()
        if ctype == 'BODY':
            has_body = True
            if len(comp.get('text', '')) > 1024:
                return 'BODY text must be <= 1024 characters'
        elif ctype == 'HEADER':
            fmt = (comp.get('format') or '').upper()
            if fmt == 'TEXT' and len(comp.get('text', '')) > 60:
                return 'TEXT header must be <= 60 characters'
            if fmt == 'LOCATION' and category.upper() == 'AUTHENTICATION':
                return 'LOCATION header is only allowed for UTILITY or MARKETING templates'
        elif ctype == 'FOOTER':
            if len(comp.get('text', '')) > 60:
                return 'FOOTER text must be <= 60 characters'
        elif ctype == 'BUTTONS':
            btn_err = _validate_template_button_group(comp.get('buttons', []))
            if btn_err:
                return btn_err
    if not has_body:
        return 'Template must include a BODY component'
    return None


def _create_template(waba_id, body):
    try:
        template_def = body.get('templateDefinition')
        if not template_def:
            return _error_response(400, 'templateDefinition required')
        # Local validation before hitting Meta (clear errors, fewer rejected submissions)
        from lambda_utils import template_validation as tv
        result = tv.validate_template(template_def)
        if not result['ok']:
            return _error_response(400, '; '.join(result['errors']))
        meta_waba_id = _resolve_meta_waba_id(waba_id)
        url = f'{META_GRAPH_URL}/{meta_waba_id}/message_templates'
        data = _meta_request(url, method='POST', data=json.dumps(template_def).encode())
        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'metaTemplateId': data.get('id', ''),
                'category': data.get('category', ''),
                'templateStatus': data.get('status', 'PENDING'),
                'warnings': result.get('warnings', []),
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


def _validate_template_route(body):
    """POST /templates/validate — validate a template definition without creating it."""
    from lambda_utils import template_validation as tv
    template_def = body.get('templateDefinition') or body
    result = tv.validate_template(template_def)
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps(result),
    }


def _list_presets():
    """GET /templates/presets — list available preset template definitions."""
    from lambda_utils import template_presets as tp
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'presets': tp.list_presets()}),
    }


def _get_preset(name):
    """GET /templates/presets/{name} — return a single preset definition."""
    from lambda_utils import template_presets as tp
    preset = tp.get_preset(name)
    if not preset:
        return _error_response(404, f'Unknown preset: {name}')
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'preset': preset}),
    }


def _refresh_template(waba_id, template_id):
    """POST /templates/{id}/refresh — re-fetch a template's live status/category/quality from Meta."""
    try:
        if not template_id:
            return _error_response(400, 'Template ID required')
        url = (f'{META_GRAPH_URL}/{template_id}'
               '?fields=name,status,category,language,components,id,quality_score,'
               'message_send_ttl_seconds,rejected_reason')
        data = _meta_request(url)
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'template': {
                    'metaTemplateId': data.get('id'),
                    'templateName': data.get('name'),
                    'templateStatus': data.get('status'),
                    'templateState': template_status.canonical(data.get('status')),
                    'sendable': template_status.is_sendable(data.get('status')),
                    'category': data.get('category', ''),
                    'language': data.get('language', ''),
                    'qualityScore': data.get('quality_score', {}),
                    'messageSendTtlSeconds': data.get('message_send_ttl_seconds'),
                    'rejectedReason': data.get('rejected_reason', ''),
                    'components': data.get('components', []),
                }
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


def _send_test_template(waba_id, template_id, body):
    """POST /templates/{id}/send-test — send a template message to a test recipient.

    Body: { to, templateName, language, components?, phoneId? }
    Fetches the template by id to resolve name/language when not supplied.
    """
    try:
        to = (body.get('to') or '').strip()
        if not to:
            return _error_response(400, 'to (recipient phone in E.164 without +) is required')

        template_name = body.get('templateName')
        language = body.get('language')
        if (not template_name or not language) and template_id:
            detail = _meta_request(f'{META_GRAPH_URL}/{template_id}?fields=name,language')
            template_name = template_name or detail.get('name')
            language = language or detail.get('language')
        if not template_name:
            return _error_response(400, 'templateName is required (or a resolvable templateId)')

        template_payload = {
            'name': template_name,
            'language': {'code': language or 'en'},
        }
        if body.get('components'):
            template_payload['components'] = body['components']

        message = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'template',
            'template': template_payload,
        }
        phone_id = body.get('phoneId') or _resolve_phone_id(waba_id)
        url = f'{META_GRAPH_URL}/{phone_id}/messages'
        data = _meta_request(url, method='POST', data=json.dumps(message).encode())
        msg_id = ''
        if isinstance(data, dict):
            msgs = data.get('messages', [])
            if msgs:
                msg_id = msgs[0].get('id', '')
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'messageId': msg_id, 'to': to}),
        }
    except Exception as e:
        return _error_response(500, str(e))


def _create_from_library(waba_id, body):
    """AWS create_whatsapp_message_template_from_library has no Meta Graph API equivalent."""
    return _error_response(
        501,
        'Creating templates from the Meta template library is not supported via the Graph API. '
        'Use Meta Business Suite or create the template directly with _create_template.'
    )


# ── UPDATE ──

def _update_template(waba_id, body, query_params, path):
    try:
        template_id = _extract_path_param(path, '/templates/')
        if not template_id:
            template_id = body.get('metaTemplateId', '')
        if not template_id:
            return _error_response(400, 'Template ID required (in path or body)')

        template_def = body.get('templateDefinition')
        if not template_def:
            return _error_response(400, 'templateDefinition required')

        url = f'{META_GRAPH_URL}/{template_id}'
        data = _meta_request(url, method='POST', data=json.dumps(template_def).encode())

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'success': True,
                'metaTemplateId': data.get('id', template_id),
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


# ── DELETE ──

def _delete_template(waba_id, template_name, query_params):
    try:
        if not template_name:
            return _error_response(400, 'templateName required')
        meta_waba_id = _resolve_meta_waba_id(waba_id)
        encoded_name = urllib.parse.quote(template_name)
        url = f'{META_GRAPH_URL}/{meta_waba_id}/message_templates?name={encoded_name}'
        _meta_request(url, method='DELETE')
        return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'success': True})}
    except Exception as e:
        return _error_response(500, str(e))


# ── MEDIA UPLOAD ──

def _upload_media_to_meta(file_bytes: bytes, content_type: str, filename: str, phone_id: str = None) -> str:
    """Upload media to Meta via the phone media endpoint. Returns the media ID (header handle).

    phone_id MUST belong to the same WABA the template will be created on.
    """
    phone_id = phone_id or DEFAULT_PHONE_ID
    boundary = uuid.uuid4().hex
    body_parts = []
    body_parts.append(f'--{boundary}\r\n'.encode())
    body_parts.append(f'Content-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'.encode())
    body_parts.append(f'--{boundary}\r\n'.encode())
    body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body_parts.append(f'Content-Type: {content_type}\r\n\r\n'.encode())
    body_parts.append(file_bytes)
    body_parts.append(f'\r\n--{boundary}--\r\n'.encode())
    multipart_body = b''.join(body_parts)

    url = f'{META_GRAPH_URL}/{phone_id}/media'
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    data = _meta_request(url, method='POST', data=multipart_body, headers=headers)
    return data.get('id', '')


def _upload_template_media(waba_id, body):
    try:
        file_data_b64 = body.get('fileData')
        s3_key = body.get('s3Key')
        content_type = body.get('contentType', 'image/jpeg')
        filename = body.get('filename', 'header.jpg')

        if not file_data_b64 and not s3_key:
            return _error_response(400, 'fileData (base64) or s3Key required')

        if s3_key:
            obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
            file_bytes = obj['Body'].read()
        else:
            file_bytes = base64.b64decode(file_data_b64)

        # Upload to S3 for reference
        upload_key = f'{TEMPLATE_MEDIA_PREFIX}wecare-digital-{uuid.uuid4().hex[:8]}_{filename}'
        s3.put_object(Bucket=MEDIA_BUCKET, Key=upload_key, Body=file_bytes, ContentType=content_type)

        # Upload to Meta — use a phone that belongs to the SAME WABA
        phone_id = _resolve_phone_id(waba_id)
        header_handle = _upload_media_to_meta(file_bytes, content_type, filename, phone_id=phone_id)

        logger.info(json.dumps({
            'event': 'template_media_uploaded',
            'headerHandle': header_handle,
            'phoneId': phone_id,
            's3Key': upload_key,
            'contentType': content_type,
        }))

        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'metaHeaderHandle': header_handle,
                's3Key': upload_key,
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


# ── SEND-TIME MEDIA UPLOAD (Public URL for WhatsApp to fetch) ──

def _upload_send_media(body):
    """Upload media that will be sent in a template message.
    
    WhatsApp fetches the URL to deliver media to the recipient.
    Files go to the public/wa-tpl/ prefix in wecare-digital-get so they're
    publicly accessible via CloudFront.
    
    Request body:
        fileData: base64-encoded file content (required)
        contentType: MIME type (required, e.g. application/pdf)
        filename: original filename (required)
    
    Returns:
        mediaUrl: https://{CDN_DOMAIN}/public/wa-tpl/{folder}/wecare-digital-{id}_{file}
                  i.e. https://wecare.digital/get/public/wa-tpl/... by default.

        NOTE the 61 objects backing already-approved templates live at
        o/public/wa-tpl/ and are served on app.wecare.digital, because that host is
        rebuilt with OriginPath=/o. New uploads land at the bucket root instead, so
        they are reachable on wecare.digital/get but NOT on app.wecare.digital. Both
        work; they are simply different locations. Do not "fix" one to match the
        other without resubmitting the approved templates that name the old URLs.
        s3Key: full S3 key
        folder: short folder name (docs/img/vid/aud/stk)
        category: WhatsApp media category
    """
    try:
        file_data_b64 = body.get('fileData')
        content_type = body.get('contentType', '')
        filename = body.get('filename', '')

        if not file_data_b64:
            return _error_response(400, 'fileData (base64) required')
        if not content_type:
            return _error_response(400, 'contentType required')
        if not filename:
            return _error_response(400, 'filename required')

        # Validate MIME type is supported by WhatsApp
        folder = WA_MEDIA_FOLDERS.get(content_type)
        if not folder:
            return _error_response(
                400,
                f'Unsupported media type: {content_type}. '
                f'Supported: {", ".join(sorted(set(WA_MEDIA_FOLDERS.keys())))}'
            )

        file_bytes = base64.b64decode(file_data_b64)

        # Validate size against WhatsApp limits
        max_size = WA_MEDIA_MAX_SIZES.get(folder, 100 * 1024 * 1024)
        if len(file_bytes) > max_size:
            max_mb = max_size / (1024 * 1024)
            return _error_response(
                400,
                f'File too large ({len(file_bytes)} bytes). Max for {folder}: {max_mb:.0f}MB'
            )

        # Sanitize filename and build key
        safe_filename = ''.join(
            c if c.isalnum() or c in '._-' else '_'
            for c in filename
        )
        short_id = uuid.uuid4().hex[:8]
        s3_key = f'{PUBLIC_MEDIA_PREFIX}{folder}/wecare-digital-{short_id}_{safe_filename}'

        # Upload to S3 with public-read ACL via Amplify storage policy
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=s3_key,
            Body=file_bytes,
            ContentType=content_type,
            CacheControl='public, max-age=31536000',
            Metadata={
                'original-filename': filename,
                'media-category': folder,
            }
        )

        # Public CDN URL (CDN_DOMAIN, not the bucket name)
        media_url = f'https://{CDN_DOMAIN}/{s3_key}'

        category_map = {'docs': 'document', 'img': 'image', 'vid': 'video', 'aud': 'audio', 'stk': 'sticker'}

        logger.info(json.dumps({
            'event': 'send_media_uploaded',
            's3Key': s3_key,
            'mediaUrl': media_url,
            'folder': folder,
            'sizeBytes': len(file_bytes),
        }))

        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'mediaUrl': media_url,
                's3Key': s3_key,
                'folder': folder,
                'category': category_map.get(folder, 'document'),
                'filename': safe_filename,
                'sizeBytes': len(file_bytes),
            })
        }
    except Exception as e:
        logger.error(json.dumps({'event': 'send_media_upload_error', 'error': str(e)}))
        return _error_response(500, str(e))


def _list_send_media(query_params):
    """List reusable template-send media in the public wa-tpl/ folder.

    Query params:
        folder: optional — one of docs/img/vid/aud/stk to filter by type
        category: optional — document/image/video/audio/sticker (mapped to folder)
        search: optional — case-insensitive filename substring filter

    Returns: { items: [{ s3Key, mediaUrl, filename, folder, category, sizeBytes, lastModified }], count }
    """
    try:
        folder = (query_params.get('folder') or '').strip().lower()
        category = (query_params.get('category') or '').strip().lower()
        search = (query_params.get('search') or '').strip().lower()

        cat_to_folder = {'document': 'docs', 'image': 'img', 'video': 'vid', 'audio': 'aud', 'sticker': 'stk'}
        if not folder and category in cat_to_folder:
            folder = cat_to_folder[category]

        folder_to_cat = {'docs': 'document', 'img': 'image', 'vid': 'video', 'aud': 'audio', 'stk': 'sticker'}
        prefixes = [f'{PUBLIC_MEDIA_PREFIX}{folder}/'] if folder in folder_to_cat else [PUBLIC_MEDIA_PREFIX]

        items = []
        for prefix in prefixes:
            token = None
            while True:
                kwargs = {'Bucket': MEDIA_BUCKET, 'Prefix': prefix, 'MaxKeys': 1000}
                if token:
                    kwargs['ContinuationToken'] = token
                resp = s3.list_objects_v2(**kwargs)
                for obj in resp.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('/'):
                        continue
                    parts = key.split('/')
                    fld = parts[2] if len(parts) > 2 else ''
                    raw_name = parts[-1]
                    # Strip the wecare-digital-{8hex}_ prefix for display
                    display = raw_name
                    if display.startswith('wecare-digital-'):
                        rest = display[len('wecare-digital-'):]
                        if '_' in rest:
                            display = rest.split('_', 1)[1]
                        elif '.' in rest and len(rest.split('.', 1)[0]) <= 12:
                            display = rest  # generated name, keep as-is
                    fname_l = raw_name.lower()
                    if search and search not in fname_l and search not in display.lower():
                        continue
                    items.append({
                        's3Key': key,
                        'mediaUrl': f'https://{CDN_DOMAIN}/{key}',
                        'filename': display,
                        'folder': fld,
                        'category': folder_to_cat.get(fld, 'document'),
                        'sizeBytes': int(obj.get('Size', 0)),
                        'lastModified': obj['LastModified'].isoformat() if obj.get('LastModified') else None,
                    })
                if resp.get('IsTruncated'):
                    token = resp.get('NextContinuationToken')
                else:
                    break

        # Newest first
        items.sort(key=lambda x: x.get('lastModified') or '', reverse=True)

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'items': items, 'count': len(items)})
        }
    except Exception as e:
        logger.error(json.dumps({'event': 'send_media_list_error', 'error': str(e)}))
        return _error_response(500, str(e))


def _delete_send_media(query_params, body=None):
    """Permanently delete a reusable template-send media file from wa-tpl/.

    Accepts s3Key via query param or body. For safety the key MUST be under the
    public template-media prefix — no other bucket paths can be deleted here.
    """
    try:
        s3_key = (query_params.get('s3Key') or '').strip()
        if not s3_key and body:
            s3_key = (body.get('s3Key') or '').strip()
        # Allow passing a full CDN URL — normalise to the S3 key
        if s3_key.startswith('http'):
            s3_key = s3_key.split(f'{CDN_DOMAIN}/', 1)[-1]
        s3_key = s3_key.lstrip('/')

        if not s3_key:
            return _error_response(400, 's3Key (or mediaUrl) required')
        # Safety guard: only allow deleting within the public template-media folder
        if not s3_key.startswith(PUBLIC_MEDIA_PREFIX):
            return _error_response(403, f'Refusing to delete outside {PUBLIC_MEDIA_PREFIX}')

        s3.delete_object(Bucket=MEDIA_BUCKET, Key=s3_key)
        logger.info(json.dumps({'event': 'send_media_deleted', 's3Key': s3_key}))
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 's3Key': s3_key, 'message': 'Media permanently deleted'})
        }
    except Exception as e:
        logger.error(json.dumps({'event': 'send_media_delete_error', 'error': str(e)}))
        return _error_response(500, str(e))


# ── CAROUSEL TEMPLATE ──

def _upload_carousel_media(waba_id, body, query_params):
    try:
        file_data_b64 = body.get('fileData')
        s3_key = body.get('s3Key')
        content_type = body.get('contentType', 'image/jpeg')
        card_index = int(body.get('cardIndex', 0))

        if not file_data_b64 and not s3_key:
            return _error_response(400, 'fileData (base64) or s3Key required')

        if s3_key:
            obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
            file_bytes = obj['Body'].read()
        else:
            file_bytes = base64.b64decode(file_data_b64)

        upload_key = f'{TEMPLATE_MEDIA_PREFIX}wecare-digital-{uuid.uuid4().hex[:8]}_card{card_index}'
        s3.put_object(Bucket=MEDIA_BUCKET, Key=upload_key, Body=file_bytes, ContentType=content_type)

        # Upload to a phone that belongs to the SAME WABA (WABA2 carousel fix)
        phone_id = _resolve_phone_id(waba_id)
        header_handle = _upload_media_to_meta(file_bytes, content_type, f'card{card_index}', phone_id=phone_id)

        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'headerHandle': header_handle,
                's3Key': upload_key,
                'cardIndex': card_index,
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


def _create_carousel_template(waba_id, body):
    try:
        name = body.get('name')
        language = body.get('language', 'en_US')
        category = body.get('category', 'MARKETING')
        body_text = body.get('bodyText', '')
        cards = body.get('cards', [])

        if not name:
            return _error_response(400, 'name required')
        if not cards or len(cards) < 2:
            return _error_response(400, 'At least 2 cards required for carousel')
        if len(cards) > 10:
            return _error_response(400, 'Maximum 10 cards allowed')

        components = []
        if body_text:
            components.append({'type': 'BODY', 'text': body_text})

        carousel_cards = []
        for i, card in enumerate(cards):
            card_components = []
            header_type = card.get('headerType', 'image').upper()
            header_handle = card.get('headerHandle', '')
            if header_handle:
                card_components.append({
                    'type': 'HEADER',
                    'format': header_type,
                    'example': {'header_handle': [header_handle]},
                })
            card_body = card.get('bodyText', '')
            if card_body:
                card_components.append({'type': 'BODY', 'text': card_body})
            card_buttons = card.get('buttons', [])
            if card_buttons:
                card_components.append({'type': 'BUTTONS', 'buttons': card_buttons})
            carousel_cards.append({'components': card_components})

        components.append({'type': 'CAROUSEL', 'cards': carousel_cards})

        template_def = {
            'name': name,
            'language': language,
            'category': category,
            'components': components,
        }

        meta_waba_id = _resolve_meta_waba_id(waba_id)
        url = f'{META_GRAPH_URL}/{meta_waba_id}/message_templates'
        data = _meta_request(url, method='POST', data=json.dumps(template_def).encode())

        logger.info(json.dumps({
            'event': 'carousel_template_created',
            'name': name,
            'cardCount': len(cards),
            'metaTemplateId': data.get('id', ''),
        }))

        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'metaTemplateId': data.get('id', ''),
                'templateStatus': data.get('status', 'PENDING'),
                'templateType': 'CAROUSEL',
                'cardCount': len(cards),
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


# ── ERROR HELPER ──

def _error_response(status_code, message):
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }
