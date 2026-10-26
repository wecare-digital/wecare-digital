"""Customer OAuth adapter over existing WhatsApp Cognito CUSTOM_AUTH.

No shopping UI is served. The small authorization form is only the secure host connection
step. Opaque resource-bound host tokens reference KMS-encrypted Cognito custody in the
existing session table. Codes/refresh tokens are one-use; no credential enters tool results.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
from http.cookies import SimpleCookie
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlparse

PREFIX = 'mcp:commerce:'
COOKIE = '__Host-wecare-connect'
CUSTOMER_POOL = 'us-east-1_46ULYuukt'
CUSTOMER_CLIENT = '4avmt9n4gpmkvkdk88qbtit33o'
SCOPES = {'commerce:read', 'commerce:write'}
_CLIENTS = {}


class AuthError(ValueError):
    pass


def origin() -> str:
    value = os.environ.get('CUSTOMER_COMMERCE_ORIGIN', '').rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', parsed.netloc) or parsed.path or parsed.query or parsed.fragment:
        raise AuthError('Server origin unavailable')
    return value


def resource() -> str:
    return origin() + '/mcp'


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def row_key(kind: str, token: str) -> str:
    return PREFIX + kind + ':' + digest(token)


def clients() -> dict:
    values = json.loads(os.environ.get('CUSTOMER_OAUTH_CLIENTS', '[]'))
    if not isinstance(values, list) or len(values) > 20:
        raise AuthError('Invalid client configuration')
    result = {}
    for value in values:
        if not isinstance(value, dict) or set(value) - {'client_id', 'name', 'redirect_uris'}:
            raise AuthError('Invalid client configuration')
        client_id = value.get('client_id')
        redirects = value.get('redirect_uris')
        if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,100}', client_id) or client_id in result:
            raise AuthError('Invalid client configuration')
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 10:
            raise AuthError('Invalid redirects')
        for uri in redirects:
            parsed = urlparse(uri)
            if parsed.scheme != 'https' or not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', parsed.netloc) or parsed.username or parsed.fragment or len(uri) > 1024:
                raise AuthError('Invalid redirect')
        result[client_id] = {'name': str(value.get('name') or client_id)[:100], 'redirect_uris': redirects}
    return result


def client(name: str) -> dict:
    value = clients().get(name)
    if value is None:
        raise AuthError('Unknown client')
    return value


def aws(service: str):
    if service not in _CLIENTS:
        import boto3
        _CLIENTS[service] = boto3.resource('dynamodb', region_name='us-east-1') if service == 'dynamodb' else boto3.client(service, region_name='us-east-1')
    return _CLIENTS[service]


class Store:
    """IAM restricts all keys to mcp:commerce:*; the existing website sessions are unreachable."""
    def table(self):
        return aws('dynamodb').Table(os.environ.get('CUSTOMER_SESSIONS_TABLE', 'stack-wecare-digital-CustomerSessionsTable'))

    def get(self, key: str) -> dict | None:
        if not key.startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        row = self.table().get_item(Key={'sidHash': key}, ConsistentRead=True).get('Item')
        return row if row and row.get('absoluteExpiresAt', 0) > int(time.time()) else None

    def put(self, row: dict) -> None:
        from boto3.dynamodb.conditions import Attr
        if not row.get('sidHash', '').startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        self.table().put_item(Item=row, ConditionExpression=Attr('sidHash').not_exists())

    def take(self, key: str) -> dict | None:
        from boto3.dynamodb.conditions import Attr
        if not key.startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        try:
            row = self.table().delete_item(Key={'sidHash': key}, ReturnValues='ALL_OLD',
                ConditionExpression=Attr('sidHash').exists() & Attr('absoluteExpiresAt').gt(int(time.time()))).get('Attributes')
        except self.table().meta.client.exceptions.ConditionalCheckFailedException:
            return None
        return row


STORE = Store()


def capsule(data: dict, client_id: str, key: str) -> str:
    context = {'app': 'wecare-customer-commerce', 'resource': resource(), 'client': client_id, 'record': key}
    result = aws('kms').encrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
        EncryptionContext=context, Plaintext=json.dumps(data).encode())
    return base64.b64encode(result['CiphertextBlob']).decode()


def uncapsule(cipher: str, client_id: str, key: str) -> dict:
    context = {'app': 'wecare-customer-commerce', 'resource': resource(), 'client': client_id, 'record': key}
    result = aws('kms').decrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
        EncryptionContext=context, CiphertextBlob=base64.b64decode(cipher, validate=True))
    value = json.loads(result['Plaintext'])
    if not isinstance(value, dict):
        raise AuthError('Invalid custody')
    return value


def response(status: int, data, *, page: bool = False) -> dict:
    return {'statusCode': status, 'headers': {
        'Content-Type': 'text/html; charset=utf-8' if page else 'application/json',
        'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    }, 'body': data if page or isinstance(data, str) else json.dumps(data)}


def parse(value: str) -> dict:
    if not isinstance(value, str) or len(value.encode()) > 8192:
        raise AuthError('Invalid request')
    pairs = parse_qsl(value, keep_blank_values=True, strict_parsing=True)
    if len(pairs) != len({k for k, _ in pairs}) or len(pairs) > 20:
        raise AuthError('Ambiguous request')
    return dict(pairs)


def validate_authorize(params: dict) -> dict:
    required = {'client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'resource', 'code_challenge', 'code_challenge_method'}
    if set(params) != required or params['response_type'] != 'code' or params['code_challenge_method'] != 'S256':
        raise AuthError('Invalid authorization request')
    registered = client(params['client_id'])
    if params['redirect_uri'] not in registered['redirect_uris'] or params['resource'] != resource():
        raise AuthError('Invalid resource or redirect')
    scopes = params['scope'].split()
    if not scopes or len(set(scopes)) != len(scopes) or set(scopes) - SCOPES:
        raise AuthError('Invalid scope')
    if not 1 <= len(params['state']) <= 512 or not re.fullmatch(r'[A-Za-z0-9_-]{43}', params['code_challenge']):
        raise AuthError('Invalid state or challenge')
    return params


def auth_metadata() -> dict:
    base = origin()
    return {'issuer': base, 'authorization_endpoint': base + '/oauth/authorize',
            'token_endpoint': base + '/oauth/token', 'revocation_endpoint': base + '/oauth/revoke',
            'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256'],
            'scopes_supported': sorted(SCOPES)}


def registration_call(action: str, phone: str, event: dict, code: str = '') -> bool:
    """Reuse the established registration service; never provision a customer in this adapter."""
    if os.environ.get('CUSTOMER_REGISTRATION_ENABLED') != 'true':
        return False
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {'rawPath': '/auth/customer-registration', 'httpMethod': 'POST',
               'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}},
               'headers': {'origin': 'https://wecare.digital', 'content-type': 'application/json'},
               'body': json.dumps({'action': action, 'phone': phone, **({'code': code} if code else {})})}
    result = aws('lambda').invoke(FunctionName='wecare-customer-registration:live', InvocationType='RequestResponse',
                                  Payload=json.dumps(payload).encode())
    if result.get('FunctionError'):
        return False
    reply = json.loads(result['Payload'].read())
    return isinstance(reply.get('statusCode'), int) and 200 <= reply['statusCode'] < 300


def checked_cognito(auth: dict) -> tuple[dict, str]:
    token = auth.get('AccessToken', '')
    if not isinstance(token, str) or not token or not auth.get('RefreshToken'):
        raise AuthError('Incomplete authentication')
    try:
        user = aws('cognito-idp').get_user(AccessToken=token)
    except Exception as error:
        code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        if code in {'NotAuthorizedException', 'UserNotFoundException'}:
            raise AuthError('Customer session expired or revoked') from None
        raise
    attributes = {a['Name']: a['Value'] for a in user.get('UserAttributes', [])}
    try:
        encoded = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, IndexError):
        raise AuthError('Invalid customer token') from None
    # GetUser proves the token; unverified claims only narrow that proof, never grant authority.
    if (claims.get('iss') != f'https://cognito-idp.us-east-1.amazonaws.com/{CUSTOMER_POOL}'
            or claims.get('client_id') != CUSTOMER_CLIENT or claims.get('token_use') != 'access'
            or not attributes.get('sub') or claims.get('sub') != attributes['sub']):
        raise AuthError('Customer authentication required')
    return attributes, attributes['sub']


def bound(row: dict | None, params: dict) -> dict:
    if not row or row.get('client') != params.get('client_id') or row.get('resource') != params.get('resource'):
        raise AuthError('Invalid grant')
    client(row['client'])
    return row


def issue(grant: dict, auth: dict) -> dict:
    now = int(time.time())
    lifetime = min(int(auth.get('ExpiresIn', 3600)), 3600, grant['absoluteExpiresAt'] - now)
    if lifetime <= 0:
        raise AuthError('Expired session')
    access, refresh = 'wca_' + secrets.token_urlsafe(32), 'wcr_' + secrets.token_urlsafe(32)
    for kind, token, expiry in [('access', access, now + lifetime), ('refresh', refresh, grant['absoluteExpiresAt'])]:
        STORE.put({'sidHash': row_key(kind, token), 'kind': kind, 'client': grant['client'],
                   'resource': resource(), 'grant': grant['sidHash'], 'scope': grant['scope'], 'absoluteExpiresAt': expiry})
    return {'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer',
            'expires_in': lifetime, 'scope': grant['scope']}


def token_exchange(params: dict) -> dict:
    client(params.get('client_id', ''))
    if params.get('resource') != resource():
        raise AuthError('Invalid resource')
    if params.get('grant_type') == 'authorization_code':
        if set(params) != {'grant_type', 'client_id', 'resource', 'code', 'redirect_uri', 'code_verifier'}:
            raise AuthError('Invalid token request')
        verifier = params['code_verifier']
        if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
            raise AuthError('Invalid PKCE')
        key = row_key('code', params['code'])
        row = bound(STORE.get(key), params)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        if row.get('redirect') != params['redirect_uri'] or not hmac.compare_digest(row['challenge'], challenge):
            raise AuthError('Invalid grant')
        if STORE.take(key) is None:
            raise AuthError('Authorization code already used')
        grant = STORE.get(row['grant'])
        if not grant:
            raise AuthError('Expired session')
        auth = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
        checked_cognito(auth)
        return issue(grant, auth)
    if params.get('grant_type') == 'refresh_token':
        if set(params) != {'grant_type', 'client_id', 'resource', 'refresh_token'}:
            raise AuthError('Invalid refresh request')
        key = row_key('refresh', params['refresh_token'])
        row = bound(STORE.get(key), params)
        if STORE.take(key) is None:
            raise AuthError('Refresh token already used')
        grant = STORE.take(row['grant'])
        if not grant:
            raise AuthError('Expired session')
        previous = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
        result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='REFRESH_TOKEN_AUTH',
                                               AuthParameters={'REFRESH_TOKEN': previous['RefreshToken']})
        auth = {**result.get('AuthenticationResult', {}), 'RefreshToken': previous['RefreshToken']}
        _, subject = checked_cognito(auth)
        if subject != grant['subject']:
            raise AuthError('Customer changed')
        grant['cipher'] = capsule(auth, grant['client'], grant['sidHash'])
        STORE.put(grant)
        return issue(grant, auth)
    raise AuthError('Unsupported grant')


def customer_event(event: dict, scope: str) -> dict:
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
    authorization = headers.get('authorization', '')
    if not authorization.startswith('Bearer wca_'):
        raise AuthError('Resource-bound customer session required')
    row = STORE.get(row_key('access', authorization[7:]))
    if not row or row.get('resource') != resource() or scope not in row.get('scope', '').split():
        raise AuthError('Customer scope required')
    client(row['client'])
    grant = STORE.get(row['grant'])
    if not grant or grant.get('resource') != resource() or grant.get('client') != row['client']:
        raise AuthError('Revoked customer session')
    auth = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
    _, subject = checked_cognito(auth)
    if subject != grant['subject']:
        raise AuthError('Customer changed')
    return {**event, 'headers': {**headers, 'authorization': 'Bearer ' + auth['AccessToken']}}


def form(row: dict, csrf: str, message: str = '') -> dict:
    login = uncapsule(row['cipher'], row['client'], row['sidHash'])
    phase = login.get('phase', 'phone')
    title = 'Connect your WECARE account'
    field = '<label>WhatsApp number, including country code<input name="phone" type="tel" autocomplete="tel" required placeholder="+91…"></label>' if phase == 'phone' else '<label>WhatsApp verification code<input name="code" type="password" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></label>'
    description = ('Enter your WhatsApp number to receive a verification code.' if phase == 'phone' else
                   'Enter the code delivered to WhatsApp. This code stays out of the chat conversation.')
    if phase == 'registration':
        description = 'Verify your WhatsApp number to create your account. A separate sign-in code will follow.'
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect WECARE</title>'
            '<style>body{font:16px system-ui;max-width:420px;margin:48px auto;padding:20px;color:#1a1a1a}h1{font-size:24px}p{line-height:1.6}input,button{display:block;box-sizing:border-box;width:100%;padding:14px;margin:12px 0 24px;font:inherit}button{background:#1a3a2a;color:white;border:0;border-radius:8px}small{line-height:1.6;display:block}a{color:inherit}</style>'
            '<h1>' + title + '</h1><p>Connect to ' + html.escape(client(row['client'])['name']) + '.</p><p>' + html.escape(description) + '</p>'
            + ('<p role="alert">' + html.escape(message) + '</p>' if message else '')
            + '<form method="post" action="/oauth/authorize"><input type="hidden" name="csrf" value="' + html.escape(csrf, quote=True) + '">' + field
            + '<small>Connecting allows this client to access the WECARE account and order information you authorize, and make requested changes. '
              'Verification messages are delivered through WhatsApp. <a href="https://wecare.digital/privacy/">Privacy</a> · <a href="https://wecare.digital/terms/">Terms</a></small>'
            + '<button type="submit">' + ('Send code' if phase == 'phone' else 'Verify and connect') + '</button></form></html>')
    result = response(200, page, page=True)
    # Browsers apply form-action to the post-login redirect chain too. Permit only
    # this registered client's callback origin, never a caller-selected destination.
    callback = urlparse(row['redirect'])
    result['headers']['Content-Security-Policy'] = result['headers']['Content-Security-Policy'].replace(
        "form-action 'self';", f"form-action 'self' {callback.scheme}://{callback.netloc};")
    return result


def save_pending(row: dict, login: dict, message: str = '') -> dict:
    csrf = secrets.token_urlsafe(32)
    row['csrfHash'] = digest(csrf)
    row['cipher'] = capsule(login, row['client'], row['sidHash'])
    STORE.put(row)
    return form(row, csrf, message)


def authorize_get(params: dict) -> dict:
    params = validate_authorize(params)
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'auth', 'client': params['client_id'], 'resource': resource(),
           'redirect': params['redirect_uri'], 'state': params['state'], 'scope': params['scope'],
           'challenge': params['code_challenge'], 'absoluteExpiresAt': int(time.time()) + 600}
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result


def authorize_post(params: dict, event: dict) -> dict:
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
    if headers.get('origin') != origin():
        raise AuthError('Authorization origin required')
    cookies = SimpleCookie()
    cookies.load('; '.join(event.get('cookies') or [headers.get('cookie', '')]))
    if COOKIE not in cookies:
        raise AuthError('Authorization session required')
    key = row_key('auth', cookies[COOKIE].value)
    row = STORE.get(key)
    if not row or not hmac.compare_digest(row['csrfHash'], digest(params.get('csrf', ''))):
        raise AuthError('Invalid authorization session')
    login = uncapsule(row['cipher'], row['client'], key)
    if STORE.take(key) is None:
        raise AuthError('Authorization step already used')
    try:
        if login.get('phase') == 'phone':
            if set(params) != {'csrf', 'phone'} or not re.fullmatch(r'\+[1-9][0-9]{7,14}', params['phone']):
                return save_pending(row, {'phase': 'phone'}, 'Enter a valid number with its country code.')
            result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='CUSTOM_AUTH', AuthParameters={'USERNAME': params['phone']})
            challenge = result.get('ChallengeParameters', {})
            if challenge.get('registered') == 'false':
                if registration_call('request', params['phone'], event):
                    return save_pending(row, {'phase': 'registration', 'phone': params['phone']})
                return save_pending(row, {'phase': 'phone'}, 'We could not start new-account registration. Existing customers can sign in; please try again shortly.')
            return save_pending(row, {'phase': 'code', 'phone': params['phone'], 'session': result['Session']})
        if set(params) != {'csrf', 'code'} or not re.fullmatch(r'[0-9]{6}', params['code']):
            return save_pending(row, login, 'Enter the six-digit verification code.')
        if login.get('phase') == 'registration':
            if not registration_call('verify', login['phone'], event, params['code']):
                return save_pending(row, login, 'We could not verify that code. Check it and try again, or restart sign-in.')
            result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='CUSTOM_AUTH',
                                                    AuthParameters={'USERNAME': login['phone']})
            if not result.get('Session') or result.get('ChallengeParameters', {}).get('registered') == 'false':
                return save_pending(row, {'phase': 'phone'}, 'Your number was verified. Please restart sign-in.')
            return save_pending(row, {'phase': 'code', 'phone': login['phone'], 'session': result['Session']},
                                'Your account is created. Enter the new WhatsApp code to finish connecting.')
        result = aws('cognito-idp').respond_to_auth_challenge(ClientId=CUSTOMER_CLIENT, ChallengeName='CUSTOM_CHALLENGE',
                    Session=login['session'], ChallengeResponses={'USERNAME': login['phone'], 'ANSWER': params['code']})
        if not result.get('AuthenticationResult'):
            if not result.get('Session'):
                return save_pending(row, {'phase': 'phone'}, 'The verification session expired. Request a new code.')
            login['session'] = result['Session']
            return save_pending(row, login, 'Check the code and try again.')
        auth = result['AuthenticationResult']
        _, subject = checked_cognito(auth)
        now = int(time.time())
        grant_key = PREFIX + 'grant:' + secrets.token_urlsafe(32)
        grant = {'sidHash': grant_key, 'kind': 'grant', 'client': row['client'], 'resource': resource(),
                 'scope': row['scope'], 'subject': subject, 'absoluteExpiresAt': now + 30 * 86400,
                 'cipher': capsule(auth, row['client'], grant_key)}
        STORE.put(grant)
        code = 'wcc_' + secrets.token_urlsafe(32)
        STORE.put({'sidHash': row_key('code', code), 'kind': 'code', 'client': row['client'], 'resource': resource(),
                   'redirect': row['redirect'], 'challenge': row['challenge'], 'grant': grant_key, 'absoluteExpiresAt': now + 120})
        separator = '&' if urlparse(row['redirect']).query else '?'
        result = response(302, {})
        result['headers']['Location'] = row['redirect'] + separator + urlencode({'code': code, 'state': row['state']})
        result['cookies'] = [f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
        return result
    except Exception:
        # Never reflect provider error strings, session credentials, numbers or codes.
        return save_pending(row, {'phase': 'phone'}, 'We could not complete verification. Please try again shortly.')


def route(event: dict) -> dict | None:
    path = str(event.get('rawPath') or '')
    if path not in {'/.well-known/oauth-authorization-server', '/oauth/authorize', '/oauth/token', '/oauth/revoke'}:
        return None
    method = str(((event.get('requestContext') or {}).get('http') or {}).get('method') or '').upper()
    try:
        if path == '/.well-known/oauth-authorization-server' and method == 'GET':
            return response(200, auth_metadata())
        if path == '/oauth/authorize' and method == 'GET':
            return authorize_get(parse(event.get('rawQueryString', '')))
        if method != 'POST':
            return response(405, {'error': 'invalid_request'})
        headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
        if headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            raise AuthError('Unsupported content type')
        raw = event.get('body') or ''
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode()
        params = parse(raw)
        if path == '/oauth/authorize':
            return authorize_post(params, event)
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
            if row and row.get('client') == params['client_id'] and row.get('resource') == resource():
                STORE.take(row['grant'])
                STORE.take(row['sidHash'])
            return response(200, {})
        return response(404, {'error': 'invalid_request'})
    except (AuthError, ValueError, TypeError, UnicodeError):
        return response(400, {'error': 'invalid_grant' if path == '/oauth/token' else 'invalid_request'})
    except Exception:
        return response(503, {'error': 'temporarily_unavailable'})
