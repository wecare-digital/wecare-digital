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
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
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
DEFAULT_WABA_ID = 'waba-e47d916f3c7a47e1a34a19653893dd4b'

from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
META_GRAPH_URL = f'https://graph.facebook.com/{META_API_VERSION}'
META_APP_ID = '2238810740192680'
DEFAULT_PHONE_ID = '1016149501586345'

AWS_TO_META_WABA = {
    'waba-e47d916f3c7a47e1a34a19653893dd4b': '2094615664435155',   # WABA1
    'waba-dbe343f210204752b74c80a0a59631a6': '2513394156072604',   # WABA2/WABA-T
}
DEFAULT_META_WABA_ID = '2094615664435155'  # WABA1

# Meta WABA id -> phone-number-id. Media for a template header MUST be uploaded
# to a phone number that belongs to the SAME WABA the template is created on,
# otherwise the header handle is invalid for that WABA (breaks WABA2 templates).
META_WABA_TO_PHONE = {
    '2094615664435155': '1016149501586345',  # WABA1
    '2513394156072604': '1055232054343117',  # WABA2/WABA-T
}


def _resolve_phone_id(waba_id) -> str:
    """Resolve the phone-number-id for the given WABA (AWS or Meta id)."""
    meta_waba = _resolve_meta_waba_id(str(waba_id or ''))
    return META_WABA_TO_PHONE.get(meta_waba, DEFAULT_PHONE_ID)

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


# ── Google Maps Places proxy (location templates) ──────────────────────────
#
# ONE GOOGLE KEY, ONE SECRET ID. This read 'wecare/google-maps'; site-language reads
# 'wecare/google/cloud'. Both secrets hold the SAME key - docs/CREDENTIAL-ROTATION-RUNBOOK.md
# records one key, `WECARE Unified Google API Key`, with fingerprint sha256:0bd4beb6... present
# in wecare/google/cloud, wecare/google-api-key AND wecare/google-maps. Three copies of one
# value, read through two different ids.
#
# site-language's own comment already stated the rule this violated: "Do NOT point this at a new
# secret: a parallel id means rotation updates one copy and consumers keep reading the other."
# The owner has said they will rotate and update AWS themselves once the project is complete, and
# with three ids in play that rotation updates one copy and leaves the other consumers on a dead
# key. So the id is consolidated here BEFORE the rotation rather than after it, which is the only
# ordering that makes the rotation safe.
#
# wecare/google-api-key and wecare/google-maps are now read by NO code. They are not deleted from
# AWS here - that is an owner action, and deleting a secret is not something a code change should
# do - but nothing in this repository depends on them any more.
#
# THE COMMENT THAT USED TO BE HERE SAID THE KEY IS "never exposed to the browser", AND THAT IS
# BACKWARDS. The key is a browser key with referrer restrictions, and Google refuses referrer-
# restricted keys for server-side calls: measured as
# `REQUEST_DENIED: API keys with referer restrictions cannot be used with this API`. So these
# Places calls have been failing, not succeeding secretly. The runbook's step 3 is the fix and it
# needs a SERVER key, which is the one thing "use only one key" cannot satisfy - a referrer-
# restricted key cannot serve a Lambda, and an unrestricted key must not ship in a public bundle.
# Repointing the id does not fix that and is not pretending to; it makes the single rotation the
# owner is planning reach every consumer.
GOOGLE_SECRET_NAME = os.environ.get('WHATSAPP_TEMPLATES_GOOGLE_SECRET', 'wecare/google/cloud')
# Same two candidates, and the same reason, as site-language: store_provider_secret.py declares
# this secret's field as `api_key` while check_secrets_live.py probes it for
# `unified_google_api_key`. One of them is wrong and the repository cannot settle which, so both
# are tried. Kept identical to site-language's list on purpose - a test asserts they match.
GOOGLE_SECRET_FIELDS = tuple(
    part.strip() for part in os.environ.get(
        'WHATSAPP_TEMPLATES_GOOGLE_SECRET_FIELD', 'api_key,unified_google_api_key'
    ).split(',') if part.strip()
)
_gmaps_key_cache = {}


def _get_gmaps_key() -> str:
    if 'key' in _gmaps_key_cache:
        return _gmaps_key_cache['key']
    key = ''
    resolved_from = ''
    failure = ''
    try:
        resp = secrets_client.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        data = json.loads(resp['SecretString'])
        if isinstance(data, dict):
            for candidate in GOOGLE_SECRET_FIELDS:
                value = (data.get(candidate) or '').strip()
                if value:
                    key = value
                    resolved_from = candidate
                    break
        if not key:
            failure = 'no_candidate_field'
    except Exception as e:
        failure = type(e).__name__
        logger.error(json.dumps({'event': 'gmaps_key_load_error', 'error': str(e)}))
    # The failure CLASS, and which field answered, so a miss is diagnosable. Field names are not
    # secrets; `resolved_from` is a literal from the constant tuple above and the key value never
    # appears in a log expression. AccessDeniedException here is most likely kms:Decrypt on the
    # CMK rather than GetSecretValue - iam-policies.ts grants GetSecretValue on the wildcard
    # wecare/*, and no kms:Decrypt grant appears in that file at all.
    if failure == 'no_candidate_field':
        logger.error(json.dumps({
            'event': 'gmaps_key_no_field', 'secret': GOOGLE_SECRET_NAME,
            'candidates': list(GOOGLE_SECRET_FIELDS)}))
    elif not failure and resolved_from:
        logger.info(json.dumps({'event': 'gmaps_key_loaded', 'field': resolved_from}))
    _gmaps_key_cache['key'] = key
    return key


def _places_new_json(url: str, *, method: str = 'GET', body: dict | None = None,
                     field_mask: str = '') -> dict:
    """Call Places API (New) with the credential in a HEADER, never in the URL.

    REPLACES a keyless `_http_get_json(url)` that had exactly two callers, both of
    which appended `&key={key}` to the URL they passed in. A URL-borne key reaches
    Google's access logs, any request tracing, and - via the `except Exception as e`
    paths below - a 502 response body and a CloudWatch log line. The key is now
    unreachable from the URL by construction, so no caller can reintroduce that:
    there is no keyless GET helper left to reuse.

    `X-Goog-FieldMask` is sent only when asked for. Place Details (New) requires one;
    Autocomplete (New) is the documented exception and must not carry it.
    """
    key = _get_gmaps_key()
    headers = {'Accept': 'application/json', 'X-Goog-Api-Key': key}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    if field_mask:
        headers['X-Goog-FieldMask'] = field_mask
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _legacy_shape_from_http_error(exc: urllib.error.HTTPError) -> dict:
    """Map a Places API (New) error body onto the legacy `status` vocabulary.

    `_google_status_problem` below, and the test that pins it, both speak the legacy
    `status`/`error_message` dialect. A refused credential has to keep arriving in
    that dialect or the referrer-specific diagnosis stops firing and a refusal looks
    like an empty result again - the exact regression that function exists to prevent.
    """
    try:
        error = json.loads(exc.read() or b'{}').get('error', {})
    except (json.JSONDecodeError, OSError, ValueError):
        error = {}
    message = str(error.get('message') or '')
    reasons = [str(d.get('reason') or '') for d in (error.get('details') or [])]
    if 'API_KEY_HTTP_REFERRER_BLOCKED' in reasons:
        # Places API (New)'s spelling of the measured refusal. Carry the word
        # "referer" so _google_status_problem's referrer branch still matches.
        return {'status': 'REQUEST_DENIED',
                'error_message': message or ('API keys with referer restrictions cannot be '
                                             'used with this API')}
    if exc.code in (401, 403):
        return {'status': 'REQUEST_DENIED', 'error_message': message}
    return {'status': 'UNKNOWN_ERROR', 'error_message': message}


def _legacy_shape_from_autocomplete(data: dict) -> dict:
    """Places API (New) `suggestions[]` -> the legacy `predictions[]` dict."""
    predictions = []
    for suggestion in data.get('suggestions') or []:
        prediction = (suggestion or {}).get('placePrediction') or {}
        predictions.append({
            'description': ((prediction.get('text') or {}).get('text') or ''),
            'place_id': prediction.get('placeId') or '',
        })
    return {'status': 'OK' if predictions else 'ZERO_RESULTS',
            'predictions': predictions}


def _legacy_shape_from_place_details(data: dict) -> dict:
    """Places API (New) place resource -> the legacy `result` dict."""
    location = data.get('location') or {}
    return {
        'status': 'OK',
        'result': {
            'geometry': {'location': {'lat': location.get('latitude'),
                                      'lng': location.get('longitude')}},
            'name': ((data.get('displayName') or {}).get('text') or ''),
            'formatted_address': data.get('formattedAddress') or '',
        },
    }


def _google_status_problem(data: dict) -> str:
    """'' when Google answered normally, else a diagnosis naming the cause.

    WHY THIS EXISTS. Both Places proxies returned HTTP 200 with Google's `status` echoed in the
    body and an empty result list. So `REQUEST_DENIED` - a refused credential - reached the
    caller looking exactly like "no matching addresses", and the feature appeared to work badly
    rather than to be broken. docs/CREDENTIAL-ROTATION-RUNBOOK.md records this as measured:
    the key these calls use is referrer-restricted, and Google refuses referrer-restricted keys
    for server-side calls, so REQUEST_DENIED is the EXPECTED answer here until a server key
    exists. An expected failure that is indistinguishable from an empty result is the worst of
    both - nobody investigates it and nobody fixes it.

    ZERO_RESULTS stays a success: it is a real, correct answer to a query that matched nothing.
    """
    status = str(data.get('status') or '')
    if status in ('OK', 'ZERO_RESULTS', ''):
        return ''
    detail = str(data.get('error_message') or '')
    if status == 'REQUEST_DENIED' and 'referer' in detail.lower():
        return ('Google refused the credential: this is a referrer-restricted BROWSER key being '
                'used server-side, which Google does not allow. A server key is required - see '
                'step 3 in docs/CREDENTIAL-ROTATION-RUNBOOK.md.')
    return f'Google returned {status}' + (f': {detail}' if detail else '')


def _places_autocomplete(q: str, session_token: str = ''):
    """Proxy Google Places Autocomplete. Returns [{description, placeId}].
    A session token bundles autocomplete keystrokes + the final details call
    into one billable session (cheaper than per-request pricing)."""
    if not q or len(q.strip()) < 3:
        return {'statusCode': 200, 'headers': cors_headers(origin), 'body': json.dumps({'predictions': []})}
    key = _get_gmaps_key()
    if not key:
        return _error_response(500, 'Maps key not configured')
    # Places API (New), POST, key in X-Goog-Api-Key only. Autocomplete (New) takes the
    # session token in the request BODY, not a query parameter. No regionCode and no
    # locationBias: the legacy call had neither, and adding one would change which
    # suggestions a user sees.
    url = 'https://places.googleapis.com/v1/places:autocomplete'
    request_body = {'input': q}
    if session_token:
        request_body['sessionToken'] = session_token
    try:
        try:
            data = _legacy_shape_from_autocomplete(
                _places_new_json(url, method='POST', body=request_body))
        except urllib.error.HTTPError as http_exc:
            data = _legacy_shape_from_http_error(http_exc)
        problem = _google_status_problem(data)
        if problem:
            logger.error(json.dumps({'event': 'places_autocomplete_denied',
                                     'status': data.get('status'), 'diagnosis': problem}))
            return _error_response(502, problem)
        preds = [{'description': p.get('description'), 'placeId': p.get('place_id')}
                 for p in data.get('predictions', [])]
        return {'statusCode': 200, 'headers': cors_headers(origin),
                'body': json.dumps({'predictions': preds, 'status': data.get('status')})}
    except Exception as e:
        logger.error(json.dumps({'event': 'places_autocomplete_error', 'error': str(e)}))
        return _error_response(502, f'Places autocomplete failed: {e}')


def _place_details(place_id: str, session_token: str = ''):
    """Proxy Google Place Details. Returns {latitude, longitude, name, address}.
    Pass the same session token used for autocomplete to close the session."""
    if not place_id:
        return _error_response(400, 'placeId required')
    key = _get_gmaps_key()
    if not key:
        return _error_response(500, 'Maps key not configured')
    # Places API (New), GET, key in X-Goog-Api-Key only. A field mask IS required here,
    # and the session token IS a query parameter on Place Details (New) - it is a
    # billing-session identifier, not a credential, so it is safe in the URL.
    url = f'https://places.googleapis.com/v1/places/{urllib.parse.quote(place_id)}'
    if session_token:
        url += f'?sessionToken={urllib.parse.quote(session_token)}'
    try:
        try:
            data = _legacy_shape_from_place_details(
                _places_new_json(url, field_mask='location,displayName,formattedAddress'))
        except urllib.error.HTTPError as http_exc:
            data = _legacy_shape_from_http_error(http_exc)
        problem = _google_status_problem(data)
        if problem:
            logger.error(json.dumps({'event': 'place_details_denied',
                                     'status': data.get('status'), 'diagnosis': problem}))
            return _error_response(502, problem)
        r = data.get('result', {})
        loc = r.get('geometry', {}).get('location', {})
        place = {
            'latitude': loc.get('lat'),
            'longitude': loc.get('lng'),
            'name': r.get('name', ''),
            'address': r.get('formatted_address', ''),
        }
        if place['latitude'] is None or place['longitude'] is None:
            # A 200 with no `location` is degenerate rather than an error: Places API (New)
            # answers HTTP 4xx for a place that does not exist, so this means the resource
            # came back without the field the mask asked for. The response body keeps
            # `status: OK` deliberately - it is part of the contract the caller already
            # reads, and ZERO_RESULTS would not change the HTTP outcome anyway, because
            # _google_status_problem treats it as success. Make it diagnosable in the log
            # instead, so a silently coordinate-less location template can be traced.
            logger.warning(json.dumps({'event': 'place_details_no_location',
                                       'status': data.get('status')}))
        return {'statusCode': 200, 'headers': cors_headers(origin),
                'body': json.dumps({'place': place, 'status': data.get('status')})}
    except Exception as e:
        logger.error(json.dumps({'event': 'place_details_error', 'error': str(e)}))
        return _error_response(502, f'Place details failed: {e}')


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
            # Google Maps Places proxy (for location-template coordinate picking)
            action = query_params.get('action', '')
            if action == 'places-autocomplete':
                return _places_autocomplete(query_params.get('q', ''), query_params.get('sessiontoken', ''))
            if action == 'place-details':
                return _place_details(query_params.get('placeId', ''), query_params.get('sessiontoken', ''))
            if '/templates/library' in path:
                return _list_template_library(waba_id, query_params)
            template_id = _extract_path_param(path, '/templates/')
            if template_id and template_id not in ('library', 'analytics', 'carousel', 'carousel-media', 'media', 'from-library'):
                return _get_template_details(waba_id, template_id, query_params)
            return _list_templates(waba_id, query_params)

        elif http_method == 'POST':
            if '/templates/from-library' in path:
                return _create_from_library(waba_id, body)
            if '/templates/carousel-media' in path:
                return _upload_carousel_media(waba_id, body, query_params)
            if '/templates/carousel' in path:
                return _create_carousel_template(waba_id, body)
            if '/templates/media' in path:
                return _upload_template_media(waba_id, body)
            return _create_template(waba_id, body)

        elif http_method == 'PUT':
            return _update_template(waba_id, body, query_params, path)

        elif http_method == 'DELETE':
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
            # Return both Meta-native keys (id/name/status/components) and the
            # legacy *metaTemplateId/templateName/templateStatus* aliases so the
            # frontend normalizer can resolve every field. Previously only the
            # three aliases were returned, which dropped `components`, `language`
            # and `category` — causing template text/preview to render blank and
            # sends to fail (language defaulted to en_US instead of the real code).
            templates.append({
                'id': t.get('id'),
                'metaTemplateId': t.get('id'),
                'name': t.get('name'),
                'templateName': t.get('name'),
                'status': t.get('status'),
                'templateStatus': t.get('status'),
                'category': t.get('category'),
                'language': t.get('language'),
                'components': t.get('components', []),
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
                    'components': data.get('components', []),
                    'language': data.get('language', ''),
                    'category': data.get('category', ''),
                }
            })
        }
    except Exception as e:
        return _error_response(500, str(e))


# ── CREATE ──

def _create_template(waba_id, body):
    try:
        template_def = body.get('templateDefinition')
        if not template_def:
            return _error_response(400, 'templateDefinition required')
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
            })
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

        # Upload to Meta — use a phone number that belongs to the SAME WABA
        phone_id = _resolve_phone_id(waba_id)
        header_handle = _upload_media_to_meta(file_bytes, content_type, filename, phone_id=phone_id)

        logger.info(json.dumps({
            'event': 'template_media_uploaded',
            'headerHandle': header_handle,
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
