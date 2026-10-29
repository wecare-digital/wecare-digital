"""Website session and pending authorization state helpers."""
from __future__ import annotations
from http.cookies import SimpleCookie
import json
import os
import secrets
import time
from urllib.parse import quote, urlencode
from customer_oauth_config import *
from customer_oauth_store import *

def registration_call(action: str, phone: str, event: dict, code: str='') -> bool:
    if os.environ.get('CUSTOMER_REGISTRATION_ENABLED') != 'true':
        return False
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {'rawPath': '/auth/customer-registration', 'httpMethod': 'POST', 'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}}, 'headers': {'origin': WEBSITE_ORIGIN, 'content-type': 'application/json'}, 'body': json.dumps({'action': action, 'phone': phone, **({'code': code} if code else {})})}
    result = aws('lambda').invoke(FunctionName='wecare-customer-registration:live', InvocationType='RequestResponse', Payload=json.dumps(payload).encode())
    if result.get('FunctionError'):
        return False
    reply = json.loads(result['Payload'].read())
    return isinstance(reply.get('statusCode'), int) and 200 <= reply['statusCode'] < 300

def auth_state(row: dict, csrf: str, message: str='') -> dict:
    login = uncapsule(row['cipher'], row['client'], row['sidHash'])
    website = row.get('kind') == 'web-auth'
    return response(200, {'phase': login.get('phase', 'phone'), 'csrf': csrf, 'message': message, 'website': website, 'returnPath': str(row.get('return') or '/'), 'clientName': '' if website else client(row['client'])['name'], 'destination': website_return(row.get('return', '')) if website else str(row.get('redirect') or '')})

def save_pending(row: dict, login: dict, message: str='') -> dict:
    csrf = secrets.token_urlsafe(32)
    row['csrfHash'] = digest(csrf)
    row['notice'] = message
    row['cipher'] = capsule(login, row['client'], row['sidHash'])
    STORE.put(row)
    if row.get('transport') == 'json':
        return auth_state(row, csrf, message)
    return redirect(connect_origin() + '/auth', 303)

def _cookie_row(event: dict) -> tuple[str, dict] | None:
    headers = {str(key).lower(): str(value) for key, value in (event.get('headers') or {}).items()}
    cookies = SimpleCookie()
    cookies.load('; '.join(event.get('cookies') or [headers.get('cookie', '')]))
    if COOKIE not in cookies:
        return None
    key = row_key('auth', cookies[COOKIE].value)
    row = STORE.get(key)
    return (key, row) if row else None

def resume_authorization(event: dict, params: dict | None=None) -> dict | None:
    found = _cookie_row(event)
    if not found:
        return None
    key, row = found
    if row.get('kind') not in {'web-auth', 'oauth-auth'}:
        return None
    requested = params or {}
    oauth_fields = {
        'client_id', 'redirect_uri', 'response_type', 'scope', 'state',
        'resource', 'code_challenge', 'code_challenge_method',
    }
    if row.get('kind') == 'oauth-auth':
        client(row['client'])
        if row.get('resource') != resource():
            raise AuthError('Invalid authorization resource')
        if requested:
            if not oauth_fields.intersection(requested):
                return None
            expected = validate_authorize(requested)
            if any((row.get('client') != expected['client_id'], row.get('redirect') != expected['redirect_uri'], row.get('state') != expected['state'], row.get('scope') != expected['scope'], row.get('challenge') != expected['code_challenge'])):
                return None
    else:
        # A website sign-in cookie must never satisfy a host OAuth request. Likewise, unknown
        # website query fields are not silently discarded; the caller starts a fresh validated
        # flow (or receives an invalid-request response) instead of inheriting unrelated state.
        if set(requested) - {'return'}:
            return None
        if requested and website_return(requested.get('return', '')) != row.get('return'):
            return None
    login = uncapsule(row['cipher'], row['client'], key)
    if STORE.take(key) is None:
        return website_recovery()
    row['transport'] = 'json'
    return save_pending(row, login, row.get('notice', ''))

def website_get(params: dict) -> dict:
    if set(params) - {'return'}:
        raise AuthError('Invalid website sign-in request')
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'web-auth', 'client': WEBSITE_CLIENT, 'return': website_return(params.get('return', '')), 'absoluteExpiresAt': int(time.time()) + 600, 'transport': 'json'}
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result

def website_recovery(return_hint: str='') -> dict:
    destination = website_return(return_hint)
    location = '/auth' + ('?' + urlencode({'return': destination}) if destination != '/' else '')
    result = redirect(location, 303)
    result['cookies'] = [f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
    return result

def website_finish(row: dict, cognito: dict, event: dict) -> dict:
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {'rawPath': '/ecommerce/customer-session', 'httpMethod': 'POST', 'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}}, 'headers': {'origin': WEBSITE_ORIGIN, 'content-type': 'application/json', 'authorization': 'Bearer ' + cognito['AccessToken']}, 'body': json.dumps({'action': 'exchange', 'refreshToken': cognito['RefreshToken'], 'persistent': True})}
    invoked = aws('lambda').invoke(FunctionName='wecare-customer-session:live', InvocationType='RequestResponse', Payload=json.dumps(payload).encode())
    if invoked.get('FunctionError'):
        raise AuthError('Website session unavailable')
    reply = json.loads(invoked['Payload'].read())
    if not isinstance(reply.get('statusCode'), int) or not 200 <= reply['statusCode'] < 300:
        raise AuthError('Website session unavailable')
    body = json.loads(reply.get('body') or '{}')
    csrf = body.get('csrfToken')
    expires_at = body.get('expiresAt')
    if not isinstance(csrf, str) or not csrf or (not isinstance(expires_at, (int, float))):
        raise AuthError('Website session unavailable')
    try:
        profile_payload = {'rawPath': '/customer/profile', 'httpMethod': 'POST', 'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}}, 'headers': {'origin': WEBSITE_ORIGIN, 'content-type': 'application/json', 'authorization': 'Bearer ' + cognito['AccessToken']}, 'body': '{}'}
        aws('lambda').invoke(FunctionName='wecare-customer-profile:live', InvocationType='RequestResponse', Payload=json.dumps(profile_payload).encode())
    except Exception:
        pass
    hint = quote(json.dumps({'csrfToken': csrf, 'expiresAt': int(expires_at), 'persistent': True}, separators=(',', ':')), safe='')
    result = redirect(website_return(row.get('return', '')), 303)
    result['cookies'] = list(reply.get('cookies') or []) + [f'{SESSION_HINT_COOKIE}={hint}; Secure; SameSite=Lax; Path=/; Max-Age=1800', f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
    return result
