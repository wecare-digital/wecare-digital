"""Website session and pending authorization state helpers."""
from __future__ import annotations

from http.cookies import SimpleCookie
import json
import os
import re
import secrets
import time
from urllib.parse import quote, urlencode

from customer_oauth_config import *
from customer_oauth_store import *


def registration_call(
    action: str,
    phone: str,
    event: dict,
    code: str = '',
) -> bool:
    if os.environ.get('CUSTOMER_REGISTRATION_ENABLED') != 'true':
        return False
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {
        'rawPath': '/auth/customer-registration',
        'httpMethod': 'POST',
        'requestContext': {
            'http': {
                'method': 'POST',
                'sourceIp': str(http.get('sourceIp') or ''),
            }
        },
        'headers': {
            'origin': WEBSITE_ORIGIN,
            'content-type': 'application/json',
        },
        'body': json.dumps(
            {
                'action': action,
                'phone': phone,
                **({'code': code} if code else {}),
            }
        ),
    }
    result = aws('lambda').invoke(
        FunctionName='wecare-customer-registration:live',
        InvocationType='RequestResponse',
        Payload=json.dumps(payload).encode(),
    )
    if result.get('FunctionError'):
        return False
    reply = json.loads(result['Payload'].read())
    return (
        isinstance(reply.get('statusCode'), int)
        and 200 <= reply['statusCode'] < 300
    )


def auth_state(row: dict, csrf: str, message: str = '') -> dict:
    login = uncapsule(row['cipher'], row['client'], row['sidHash'], row.get('resource'))
    website = row.get('kind') == 'web-auth'
    return response(
        200,
        {
            'phase': login.get('phase', 'phone'),
            'csrf': csrf,
            'message': message,
            'website': website,
            'returnPath': str(row.get('return') or '/'),
            'clientName': '' if website else client(row['client'])['name'],
            'destination': (
                website_return(row.get('return', ''))
                if website
                else str(row.get('redirect') or '')
            ),
        },
    )


def save_pending(row: dict, login: dict, message: str = '') -> dict:
    csrf = secrets.token_urlsafe(32)
    row['csrfHash'] = digest(csrf)
    row['notice'] = message
    row['cipher'] = capsule(login, row['client'], row['sidHash'], row.get('resource'))
    STORE.put(row)
    if row.get('transport') == 'json':
        return auth_state(row, csrf, message)
    return redirect(connect_origin() + '/auth', 303)


def _cookie_row(event: dict) -> tuple[str, dict] | None:
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get('headers') or {}).items()
    }
    cookies = SimpleCookie()
    cookies.load('; '.join(event.get('cookies') or [headers.get('cookie', '')]))
    if COOKIE not in cookies:
        return None
    key = row_key('auth', cookies[COOKIE].value)
    row = STORE.get(key)
    return (key, row) if row else None


def resume_authorization(
    event: dict,
    params: dict | None = None,
) -> dict | None:
    found = _cookie_row(event)
    if not found:
        return None
    key, row = found
    if row.get('kind') not in {'web-auth', 'oauth-auth'}:
        return None
    requested = params or {}
    oauth_fields = {
        'client_id',
        'redirect_uri',
        'response_type',
        'scope',
        'state',
        'resource',
        'code_challenge',
        'code_challenge_method',
    }
    if row.get('kind') == 'oauth-auth':
        client(row['client'])
        if row.get('resource') not in accepted_resources():
            raise AuthError('Invalid authorization resource')
        if requested:
            if not oauth_fields.intersection(requested):
                return None
            expected = validate_authorize(requested)
            # A pending grant must never be resumed under a different MCP
            # audience. The caller must restart explicitly, rather than the
            # server silently turning an old-resource cookie into a new flow.
            if row.get('resource') != expected['resource']:
                raise AuthError('Authorization resource changed')
            if any(
                (
                    row.get('client') != expected['client_id'],
                    row.get('resource') != expected['resource'],
                    row.get('redirect') != expected['redirect_uri'],
                    row.get('state') != expected['state'],
                    row.get('scope') != expected['scope'],
                    row.get('challenge') != expected['code_challenge'],
                )
            ):
                return None
    else:
        if set(requested) - {'return'}:
            return None
        if (
            requested
            and website_return(requested.get('return', ''))
            != row.get('return')
        ):
            return None
    login = uncapsule(row['cipher'], row['client'], key, row.get('resource'))
    if STORE.take(key) is None:
        return website_recovery()
    row['transport'] = 'json'
    return save_pending(row, login, row.get('notice', ''))


def website_get(params: dict) -> dict:
    if set(params) - {'return'}:
        raise AuthError('Invalid website sign-in request')
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {
        'sidHash': key,
        'kind': 'web-auth',
        'client': WEBSITE_CLIENT,
        'return': website_return(params.get('return', '')),
        'absoluteExpiresAt': int(time.time()) + 600,
        'transport': 'json',
    }
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [
        f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600'
    ]
    return result


def website_recovery(return_hint: str = '') -> dict:
    destination = website_return(return_hint)
    location = '/auth' + (
        '?' + urlencode({'return': destination})
        if destination != '/'
        else ''
    )
    result = redirect(location, 303)
    result['cookies'] = [
        f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'
    ]
    return result


def _validated_session_cookies(raw_cookies) -> list[str]:
    """Accept only the exact host-only customer-session cookie contract.

    The downstream Lambda is internal but remains a separate trust boundary. A
    malformed cookie response must not be able to inject response headers, set a
    sibling-domain cookie, or overwrite this adapter's own auth cookie.
    """
    if not isinstance(raw_cookies, list) or len(raw_cookies) != 1:
        raise AuthError('Website session unavailable')
    raw = raw_cookies[0]
    if (
        not isinstance(raw, str)
        or not raw
        or any(character in raw for character in ('\r', '\n', '\x00'))
    ):
        raise AuthError('Website session unavailable')

    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception as error:
        raise AuthError('Website session unavailable') from error
    if set(jar) != {WEBSITE_SESSION_COOKIE}:
        raise AuthError('Website session unavailable')

    morsel = jar[WEBSITE_SESSION_COOKIE]
    if not re.fullmatch('[A-Za-z0-9_-]{32,256}', morsel.value):
        raise AuthError('Website session unavailable')
    if (
        morsel['domain']
        or morsel['path'] != '/'
        or not morsel['secure']
        or not morsel['httponly']
        or morsel['samesite'].lower() != 'lax'
        or morsel['expires']
    ):
        raise AuthError('Website session unavailable')

    max_age = morsel['max-age']
    if max_age and (
        not re.fullmatch('[0-9]{1,10}', max_age)
        or int(max_age) > 31 * 24 * 60 * 60
    ):
        raise AuthError('Website session unavailable')
    return [raw]


def website_finish(row: dict, cognito: dict, event: dict) -> dict:
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {
        'rawPath': '/ecommerce/customer-session',
        'httpMethod': 'POST',
        'requestContext': {
            'http': {
                'method': 'POST',
                'sourceIp': str(http.get('sourceIp') or ''),
            }
        },
        'headers': {
            'origin': WEBSITE_ORIGIN,
            'content-type': 'application/json',
            'authorization': 'Bearer ' + cognito['AccessToken'],
        },
        'body': json.dumps(
            {
                'action': 'exchange',
                'refreshToken': cognito['RefreshToken'],
                'persistent': True,
            }
        ),
    }
    invoked = aws('lambda').invoke(
        FunctionName='wecare-customer-session:live',
        InvocationType='RequestResponse',
        Payload=json.dumps(payload).encode(),
    )
    if invoked.get('FunctionError'):
        raise AuthError('Website session unavailable')
    reply = json.loads(invoked['Payload'].read())
    if (
        not isinstance(reply.get('statusCode'), int)
        or not 200 <= reply['statusCode'] < 300
    ):
        raise AuthError('Website session unavailable')

    body = json.loads(reply.get('body') or '{}')
    csrf = body.get('csrfToken')
    expires_at = body.get('expiresAt')
    if (
        not isinstance(csrf, str)
        or not csrf
        or not isinstance(expires_at, (int, float))
    ):
        raise AuthError('Website session unavailable')
    session_cookies = _validated_session_cookies(reply.get('cookies'))

    try:
        profile_payload = {
            'rawPath': '/customer/profile',
            'httpMethod': 'POST',
            'requestContext': {
                'http': {
                    'method': 'POST',
                    'sourceIp': str(http.get('sourceIp') or ''),
                }
            },
            'headers': {
                'origin': WEBSITE_ORIGIN,
                'content-type': 'application/json',
                'authorization': 'Bearer ' + cognito['AccessToken'],
            },
            'body': '{}',
        }
        aws('lambda').invoke(
            FunctionName='wecare-customer-profile:live',
            InvocationType='RequestResponse',
            Payload=json.dumps(profile_payload).encode(),
        )
    except Exception:
        pass

    hint = quote(
        json.dumps(
            {
                'csrfToken': csrf,
                'expiresAt': int(expires_at),
                'persistent': True,
            },
            separators=(',', ':'),
        ),
        safe='',
    )
    result = redirect(website_return(row.get('return', '')), 303)
    result['cookies'] = session_cookies + [
        (
            f'{SESSION_HINT_COOKIE}={hint}; Secure; SameSite=Lax; '
            'Path=/; Max-Age=1800'
        ),
        (
            f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; '
            'Path=/; Max-Age=0'
        ),
    ]
    return result
