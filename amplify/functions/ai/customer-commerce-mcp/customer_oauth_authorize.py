"""JSON-only OAuth and OTP authorization routes."""
from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

from customer_oauth_config import *
from customer_oauth_store import *
from customer_oauth_web import *
from customer_oauth_web import _cookie_row


def authorize_get(params: dict) -> dict:
    params = validate_authorize(params)
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {
        'sidHash': key,
        'kind': 'oauth-auth',
        'client': params['client_id'],
        'resource': resource(),
        'redirect': params['redirect_uri'],
        'state': params['state'],
        'scope': params['scope'],
        'challenge': params['code_challenge'],
        'absoluteExpiresAt': int(time.time()) + 600,
        'transport': 'json',
    }
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [
        f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600'
    ]
    return result


def _headers(event: dict) -> dict:
    return {
        str(key).lower(): str(value)
        for key, value in (event.get('headers') or {}).items()
    }


def authorize_post(params: dict, event: dict) -> dict:
    params = dict(params)
    flow = params.pop('_flow', None)
    return_hint = params.pop('_return', '')
    website_form = flow == 'website'
    if flow not in {None, 'website'} or (return_hint and not website_form):
        raise AuthError('Invalid authorization session')

    if _headers(event).get('origin') not in {origin(), connect_origin()}:
        raise AuthError('Authorization origin required')

    found = _cookie_row(event)
    if not found:
        if website_form:
            return website_recovery(return_hint)
        raise AuthError('Authorization session required')

    key, row = found
    if not hmac.compare_digest(
        row.get('csrfHash', ''), digest(params.get('csrf', ''))
    ):
        if website_form:
            return website_recovery(return_hint)
        raise AuthError('Invalid authorization session')

    login = uncapsule(row['cipher'], row['client'], key)
    website = row.get('kind') == 'web-auth'
    if website != website_form:
        raise AuthError('Invalid authorization session')
    if STORE.take(key) is None:
        raise AuthError('Authorization step already used')

    stage = 'phone' if login.get('phase') == 'phone' else 'challenge'
    try:
        action = params.get('action')
        if action:
            if (
                set(params) - {'csrf', 'action', 'code'}
                or login.get('phase') not in {'code', 'registration'}
            ):
                raise AuthError('Invalid authorization action')
            if action == 'edit_phone':
                return save_pending(row, {'phase': 'phone'})
            if action != 'resend':
                raise AuthError('Invalid resend request')
            if login.get('phase') == 'registration':
                if not registration_call('request', login['phone'], event):
                    return save_pending(row, login)
                return save_pending(row, login, 'New code sent.')
            started = aws('cognito-idp').initiate_auth(
                ClientId=CUSTOMER_CLIENT,
                AuthFlow='CUSTOM_AUTH',
                AuthParameters={'USERNAME': login['phone']},
            )
            if (
                not started.get('Session')
                or started.get('ChallengeParameters', {}).get('registered') == 'false'
            ):
                return save_pending(
                    row, login, 'Could not resend the code. Try again.'
                )
            return save_pending(
                row,
                {
                    'phase': 'code',
                    'phone': login['phone'],
                    'session': started['Session'],
                },
                'New code sent.',
            )

        if login.get('phase') == 'phone':
            try:
                phone = normalized_phone(params)
            except (AuthError, KeyError):
                return save_pending(
                    row, {'phase': 'phone'}, 'Check the number and try again.'
                )
            started = aws('cognito-idp').initiate_auth(
                ClientId=CUSTOMER_CLIENT,
                AuthFlow='CUSTOM_AUTH',
                AuthParameters={'USERNAME': phone},
            )
            challenge = started.get('ChallengeParameters', {})
            if challenge.get('registered') == 'false':
                if registration_call('request', phone, event):
                    return save_pending(
                        row, {'phase': 'registration', 'phone': phone}
                    )
                return save_pending(
                    row, {'phase': 'phone'}, 'Could not start sign-in. Try again.'
                )
            if not started.get('Session'):
                return save_pending(
                    row, {'phase': 'phone'}, 'Could not start sign-in. Try again.'
                )
            return save_pending(
                row,
                {
                    'phase': 'code',
                    'phone': phone,
                    'session': started['Session'],
                },
            )

        if set(params) != {'csrf', 'code'} or not re.fullmatch(
            '[0-9]{6}', params['code']
        ):
            return save_pending(row, login, 'Enter the 6-digit code.')

        if login.get('phase') == 'registration':
            if not registration_call(
                'verify', login['phone'], event, params['code']
            ):
                return save_pending(row, login, 'Code not verified. Try again.')
            started = aws('cognito-idp').initiate_auth(
                ClientId=CUSTOMER_CLIENT,
                AuthFlow='CUSTOM_AUTH',
                AuthParameters={'USERNAME': login['phone']},
            )
            if (
                not started.get('Session')
                or started.get('ChallengeParameters', {}).get('registered') == 'false'
            ):
                return save_pending(
                    row,
                    {'phase': 'phone'},
                    'Number verified. Get a new code.',
                )
            return save_pending(
                row,
                {
                    'phase': 'code',
                    'phone': login['phone'],
                    'session': started['Session'],
                },
                'Account ready. Enter the new code.',
            )

        challenged = aws('cognito-idp').respond_to_auth_challenge(
            ClientId=CUSTOMER_CLIENT,
            ChallengeName='CUSTOM_CHALLENGE',
            Session=login['session'],
            ChallengeResponses={
                'USERNAME': login['phone'],
                'ANSWER': params['code'],
            },
        )
        if not challenged.get('AuthenticationResult'):
            if not challenged.get('Session'):
                return save_pending(
                    row, {'phase': 'phone'}, 'Code expired. Get a new one.'
                )
            login['session'] = challenged['Session']
            return save_pending(row, login, 'Wrong code. Try again.')

        cognito = challenged['AuthenticationResult']
        stage = 'identity_check'
        _, subject = checked_cognito(cognito)
        if website:
            return website_finish(row, cognito, event)

        now = int(time.time())
        stage = 'custody'
        grant_key = PREFIX + 'grant:' + secrets.token_urlsafe(32)
        grant = {
            'sidHash': grant_key,
            'kind': 'grant',
            'client': row['client'],
            'resource': resource(),
            'scope': row['scope'],
            'subject': subject,
            'absoluteExpiresAt': now + 30 * 86400,
            'cipher': capsule(cognito, row['client'], grant_key),
        }
        STORE.put(grant)

        stage = 'authorization_code'
        code = 'wcc_' + secrets.token_urlsafe(32)
        STORE.put(
            {
                'sidHash': row_key('code', code),
                'kind': 'code',
                'client': row['client'],
                'resource': resource(),
                'redirect': row['redirect'],
                'challenge': row['challenge'],
                'grant': grant_key,
                'absoluteExpiresAt': now + 120,
            }
        )
        separator = '&' if urlparse(row['redirect']).query else '?'
        result = redirect(
            row['redirect']
            + separator
            + urlencode({'code': code, 'state': row['state']}),
            302,
        )
        result['cookies'] = [
            f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'
        ]
        return result
    except AuthError:
        # Protocol, identity and custody failures are terminal for this step. They
        # must reach route(), which maps them to a non-recoverable 400 response.
        raise
    except Exception as error:
        category = re.sub(
            '[^A-Za-z0-9_]', '', type(error).__name__
        )[:64]
        print(
            json.dumps(
                {
                    'event': 'customer_authorization_failed',
                    'stage': stage,
                    'category': category,
                }
            )
        )
        return save_pending(row, login)


def _form_params(event: dict) -> dict:
    headers = _headers(event)
    if (
        headers.get('content-type', '').split(';')[0].strip()
        != 'application/x-www-form-urlencoded'
    ):
        raise AuthError('Unsupported content type')
    raw = event.get('body') or ''
    if event.get('isBase64Encoded'):
        raw = base64.b64decode(raw, validate=True).decode()
    return parse(raw)


def route(event: dict) -> dict | None:
    path = str(event.get('rawPath') or '')
    allowed = {
        '/.well-known/oauth-authorization-server',
        '/auth/state',
        '/auth/step',
        '/oauth/authorize',
        '/oauth/token',
        '/oauth/revoke',
    }
    if path not in allowed:
        return None
    method = str(
        ((event.get('requestContext') or {}).get('http') or {}).get('method')
        or ''
    ).upper()
    try:
        if path == '/.well-known/oauth-authorization-server' and method == 'GET':
            return response(200, auth_metadata())
        if path == '/oauth/authorize' and method == 'GET':
            params = validate_authorize(parse(event.get('rawQueryString', '')))
            return redirect(connect_origin() + '/auth?' + urlencode(params), 302)
        if path == '/auth/state' and method == 'GET':
            params = parse(event.get('rawQueryString', ''))
            pending = resume_authorization(event, params)
            if pending is not None:
                return pending
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
            if oauth_fields.intersection(params):
                return authorize_get(params)
            return website_get(params)
        if method != 'POST':
            return response(405, {'error': 'invalid_request'})

        params = _form_params(event)
        if path == '/auth/step':
            result = authorize_post(params, event)
            if result.get('statusCode') in {302, 303}:
                json_result = response(
                    200,
                    {
                        'redirect': (result.get('headers') or {}).get(
                            'Location', '/'
                        )
                    },
                )
                if result.get('cookies'):
                    json_result['cookies'] = list(result['cookies'])
                return json_result
            return result
        if path == '/oauth/token':
            return response(200, token_exchange(params))
        if path == '/oauth/revoke':
            if set(params) != {'client_id', 'resource', 'token'}:
                raise AuthError('Invalid revoke request')
            client(params['client_id'])
            if params['resource'] != resource():
                raise AuthError('Invalid resource')
            kind = 'refresh' if params['token'].startswith('wcr_') else 'access'
            row = STORE.get(row_key(kind, params['token']))
            if (
                row
                and row.get('client') == params['client_id']
                and row.get('resource') == resource()
            ):
                STORE.take(row['grant'])
                STORE.take(row['sidHash'])
            return response(200, {})
        return response(404, {'error': 'invalid_request'})
    except (AuthError, ValueError, TypeError, UnicodeError):
        return response(
            400,
            {
                'error': (
                    'invalid_grant'
                    if path == '/oauth/token'
                    else 'invalid_request'
                )
            },
        )
    except Exception:
        return response(503, {'error': 'temporarily_unavailable'})
