"""ChatGPT OAuth boundary backed by the existing staff Cognito authority.

No new token issuer or credential custody. Cognito issues and revokes tokens;
each MCP call rechecks the staff subject and current Admin membership. This
adapter is activated only for its separately configured API Gateway identifier.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.parse
from collections.abc import Callable

from botocore.exceptions import ClientError

ISSUER = 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_cSx0RHCIR'
POOL = 'us-east-1_cSx0RHCIR'
LOGIN = 'https://wecare-digital-auth.auth.us-east-1.amazoncognito.com'
SCOPE = 'aws.cognito.signin.user.admin'
MAX_FORM = 16384


class InvalidRequest(Exception):
    """A bounded OAuth request failed validation without exposing its contents."""


def reply(status: int, body: dict, headers: dict | None = None) -> dict:
    return {'statusCode': status, 'headers': {'Content-Type': 'application/json',
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        **(headers or {})}, 'body': json.dumps(body)}


def pairs(raw: str) -> dict[str, str]:
    if not isinstance(raw, str) or len(raw.encode()) > MAX_FORM:
        raise InvalidRequest()
    values = urllib.parse.parse_qsl(raw, keep_blank_values=True, max_num_fields=16)
    if len({key for key, _ in values}) != len(values):
        raise InvalidRequest()
    return dict(values)


def claims(token: str) -> dict:
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_FORM:
        raise InvalidRequest()
    parts = token.split('.')
    if len(parts) != 3:
        raise InvalidRequest()
    try:
        value = json.loads(base64.b64decode(parts[1] + '=' * (-len(parts[1]) % 4),
            altchars=b'-_', validate=True))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InvalidRequest() from exc
    if not isinstance(value, dict):
        raise InvalidRequest()
    return value


def bound_claims(token: str, client_id: str, resource: str) -> dict:
    # These claim checks do not replace signature/revocation validation. Resource
    # access always calls Cognito GetUser before it can reach the MCP dispatcher.
    value = claims(token)
    expiry = value.get('exp')
    if (value.get('iss') != ISSUER or value.get('client_id') != client_id
            or value.get('aud') != resource or value.get('token_use') != 'access'
            or type(expiry) is not int or expiry <= time.time()
            or not isinstance(value.get('sub'), str) or not value['sub']
            or not isinstance(value.get('scope'), str)
            or SCOPE not in value['scope'].split()):
        raise InvalidRequest()
    return value


def owner(token: str, client_id: str, resource: str, cognito) -> str:
    value = bound_claims(token, client_id, resource)
    user = cognito.get_user(AccessToken=token)
    attributes = {item['Name']: item['Value'] for item in user.get('UserAttributes', [])}
    if attributes.get('sub') != value['sub'] or not user.get('Username'):
        raise InvalidRequest()
    memberships = cognito.admin_list_groups_for_user(UserPoolId=POOL, Username=user['Username'])
    if 'Admin' not in {item['GroupName'] for item in memberships.get('Groups', [])}:
        raise PermissionError()
    # Same namespace as the existing staff route: no provider tokens are copied.
    return hashlib.sha256((ISSUER + ':' + value['sub']).encode()).hexdigest()


def authorization(query: dict, client_id: str, callback: str, resource: str) -> dict:
    allowed = {'response_type', 'client_id', 'redirect_uri', 'scope', 'state',
        'resource', 'code_challenge', 'code_challenge_method', 'response_mode', 'ui_locales'}
    if (set(query) - allowed or query.get('response_type') != 'code'
            or query.get('client_id') != client_id or query.get('redirect_uri') != callback
            or query.get('resource') != resource or query.get('scope', SCOPE) != SCOPE
            or query.get('code_challenge_method') != 'S256'
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', query.get('code_challenge', ''))
            or not 1 <= len(query.get('state', '')) <= 2048
            or query.get('response_mode', 'query') != 'query'):
        raise InvalidRequest()
    if 'ui_locales' in query and (len(query['ui_locales']) > 128 or not re.fullmatch(
            r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*(?: [A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*){0,7}', query['ui_locales'])):
        raise InvalidRequest()
    # ChatGPT supplies this optional presentation hint. Cognito uses its own lang
    # parameter; omit the hint without altering validated OAuth authority or PKCE.
    delegated = {key: value for key, value in query.items() if key != 'ui_locales'}
    return reply(302, {}, {'Location': LOGIN + '/oauth2/authorize?' +
        urllib.parse.urlencode({**delegated, 'scope': SCOPE})})


def token_exchange(event: dict, headers: dict, client_id: str, callback: str,
        resource: str, exchange: Callable) -> dict:
    if (headers.get('content-type', '').split(';')[0].strip().lower()
            != 'application/x-www-form-urlencoded' or headers.get('authorization')):
        raise InvalidRequest()
    raw = event.get('body') or ''
    if event.get('isBase64Encoded'):
        if len(raw) > MAX_FORM * 2:
            raise InvalidRequest()
        raw = base64.b64decode(raw, validate=True).decode()
    form = pairs(raw)
    allowed = {'grant_type', 'client_id', 'redirect_uri', 'resource', 'code',
        'code_verifier', 'refresh_token', 'scope'}
    grant = form.get('grant_type')
    if (set(form) - allowed or form.get('client_id') != client_id
            or form.get('resource', resource) != resource
            or form.get('scope', SCOPE) != SCOPE
            or grant not in {'authorization_code', 'refresh_token'}):
        raise InvalidRequest()
    if grant == 'authorization_code':
        if (form.get('resource') != resource or form.get('redirect_uri') != callback
                or not 1 <= len(form.get('code', '')) <= 4096
                or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', form.get('code_verifier', ''))
                or 'refresh_token' in form):
            raise InvalidRequest()
    elif (not 1 <= len(form.get('refresh_token', '')) <= 8192
            or 'code' in form or 'code_verifier' in form
            or ('redirect_uri' in form and form['redirect_uri'] != callback)):
        raise InvalidRequest()
    try:
        data, _ = exchange(LOGIN + '/oauth2/token', form, form=True)
        bound_claims(data.get('access_token', ''), client_id, resource)
    except Exception:
        # The upstream body can echo codes, verifiers and refresh tokens.
        return reply(400, {'error': 'invalid_grant',
            'error_description': 'Cognito did not issue a valid resource-bound access token.'})
    # This is the OAuth response to the host, never a model-visible MCP result.
    fields = {'access_token', 'refresh_token', 'token_type', 'expires_in', 'scope'}
    return reply(200, {key: value for key, value in data.items() if key in fields})


def dispatch(event: dict, client: Callable, rpc: Callable, exchange: Callable) -> dict | None:
    api_id = os.environ.get('CHAT_API_ID', '')
    base = os.environ.get('CHAT_API_BASE', '').rstrip('/')
    client_id = os.environ.get('CHAT_CLIENT_ID', '')
    callback = os.environ.get('CHAT_REDIRECT_URI', '')
    rc = event.get('requestContext') or {}
    if not api_id or rc.get('apiId') != api_id:
        return None
    if not base:
        return reply(503, {'error': 'Chat connection configuration is incomplete'})
    resource = base + '/mcp'
    path = rc.get('http', {}).get('path', '')
    method = rc.get('http', {}).get('method', '')
    route = rc.get('routeKey')
    headers = {key.lower(): value for key, value in (event.get('headers') or {}).items()}
    try:
        if (method, path, route) == ('GET', '/.well-known/oauth-protected-resource',
                'GET /.well-known/oauth-protected-resource'):
            return reply(200, {'resource': resource, 'authorization_servers': [base],
                'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header']})
        if (method, path, route) == ('GET', '/.well-known/oauth-authorization-server',
                'GET /.well-known/oauth-authorization-server'):
            return reply(200, {'issuer': base, 'authorization_endpoint': base + '/authorize',
                'token_endpoint': base + '/token', 'response_types_supported': ['code'],
                'grant_types_supported': ['authorization_code', 'refresh_token'],
                'token_endpoint_auth_methods_supported': ['none'],
                'code_challenge_methods_supported': ['S256'], 'scopes_supported': [SCOPE],
                'authorization_response_iss_parameter_supported': False})
        if (method, path, route) == ('GET', '/authorize', 'GET /authorize'):
            if not client_id or not callback:
                return reply(503, {'error': 'Chat OAuth client is not configured'})
            return authorization(pairs(event.get('rawQueryString', '')), client_id, callback, resource)
        if (method, path, route) == ('POST', '/token', 'POST /token'):
            if not client_id or not callback:
                return reply(503, {'error': 'Chat OAuth client is not configured'})
            return token_exchange(event, headers, client_id, callback, resource, exchange)
        if path != '/mcp' or route != 'ANY /mcp':
            return reply(404, {'error': 'Not found'})
        challenge = {'WWW-Authenticate': 'Bearer resource_metadata="' +
            base + '/.well-known/oauth-protected-resource", scope="' + SCOPE + '"'}
        bearer = headers.get('authorization', '')
        if not bearer.startswith('Bearer '):
            return reply(401, {'error': 'Staff OAuth authorization required'}, challenge)
        if not client_id or not callback:
            return reply(503, {'error': 'Chat OAuth client is not configured'})
        try:
            principal = owner(bearer[7:], client_id, resource, client('cognito-idp'))
        except PermissionError:
            return reply(403, {'error': 'Current staff administrator membership required'})
        except (InvalidRequest, ClientError, ValueError, KeyError, TypeError):
            return reply(401, {'error': 'Staff OAuth authorization required'}, challenge)
        return rpc(event, principal)
    except (InvalidRequest, ValueError, TypeError, UnicodeError):
        return reply(400, {'error': 'invalid_request'})
    except Exception:
        return reply(503, {'error': 'Chat authorization service unavailable'})
