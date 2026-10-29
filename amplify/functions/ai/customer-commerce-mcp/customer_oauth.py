"""Customer OAuth adapter over existing WhatsApp Cognito CUSTOM_AUTH.

No shopping UI is served. The small authorization form is only the secure host connection
step. Opaque resource-bound host tokens reference KMS-encrypted Cognito custody in the
existing session table. Codes/refresh tokens are one-use; no credential enters tool results.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from connection_assets import DIAL_COUNTRIES

PREFIX = 'mcp:commerce:'
COOKIE = '__Host-wecare-connect'
SESSION_HINT_COOKIE = 'wc_customer_session_hint'
CUSTOMER_POOL = 'us-east-1_46ULYuukt'
CUSTOMER_CLIENT = '4avmt9n4gpmkvkdk88qbtit33o'
SCOPES = {'commerce:read', 'commerce:write'}
WEBSITE_CLIENT = 'wecare-website'
WEBSITE_RETURNS = {'/', '/cart/', '/checkout/', '/orders/', '/get/', '/blog/', '/submit-request/', '/request-amendment/', '/drop-docs/', '/vault/', '/request-pickup/'}
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


def connect_origin() -> str:
    value = os.environ.get('CUSTOMER_AUTH_ORIGIN', '').rstrip('/')
    # Only the main site is permitted: wecare.digital/auth reaches this API through the
    # existing Amplify Hosting rewrite, so no sign-in subdomain is needed. The issuer and
    # token audience remain stable for existing host registrations.
    if value and value != 'https://wecare.digital':
        raise AuthError('Connection origin unavailable')
    return value or origin()


def normalized_phone(params: dict) -> str:
    if set(params) == {'csrf', 'phone'}:
        number = params['phone']  # Existing secure forms may still be open.
    elif set(params) == {'csrf', 'country', 'phone'}:
        country, national = params['country'], params['phone']
        rule = next((lengths for code, _, lengths in DIAL_COUNTRIES if code == country), None)
        if rule is None or not re.fullmatch(r'[0-9]+', national) or (rule and len(national) not in rule):
            raise AuthError('Invalid national number')
        number = country + national
    else:
        raise AuthError('Invalid phone fields')
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', number):
        raise AuthError('Invalid international number')
    return number


def website_return(value: str) -> str:
    """Allow only the same customer destinations the website sign-in flow already accepted."""
    if not value:
        return '/'
    normalized = value if value.endswith('/') else value + '/'
    if normalized not in WEBSITE_RETURNS or any(ch in value for ch in ('%', '?', '#', '\\')) or value.startswith('//'):
        return '/cart/'
    return normalized


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
    plain = json.dumps(data).encode()
    if len(plain) > 32768:
        raise AuthError('Custody payload too large')
    # KMS Encrypt accepts at most 4,096 bytes of plaintext. A larger record is split into
    # 3,000-byte parts, each bound to its index and the part count, and stored as `kms2:`
    # followed by the JSON list of ciphertexts.
    if len(plain) > 4096:
        parts = [plain[i:i + 3000] for i in range(0, len(plain), 3000)]
        encrypted = [base64.b64encode(aws('kms').encrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
            EncryptionContext={**context, 'part': str(i), 'parts': str(len(parts))},
            Plaintext=part)['CiphertextBlob']).decode() for i, part in enumerate(parts)]
        return 'kms2:' + json.dumps(encrypted, separators=(',', ':'))
    result = aws('kms').encrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
        EncryptionContext=context, Plaintext=plain)
    return base64.b64encode(result['CiphertextBlob']).decode()


def uncapsule(cipher: str, client_id: str, key: str) -> dict:
    context = {'app': 'wecare-customer-commerce', 'resource': resource(), 'client': client_id, 'record': key}
    if cipher.startswith('kms2:'):
        parts = json.loads(cipher[5:])
        if not isinstance(parts, list) or not 2 <= len(parts) <= 11 or any(
                (not isinstance(p, str) or len(p) > 12000 for p in parts)):
            raise AuthError('Invalid custody parts')
        plain = b''.join((aws('kms').decrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
            EncryptionContext={**context, 'part': str(i), 'parts': str(len(parts))},
            CiphertextBlob=base64.b64decode(part, validate=True))['Plaintext'] for i, part in enumerate(parts)))
        if len(plain) > 32768:
            raise AuthError('Custody payload too large')
    else:
        plain = aws('kms').decrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'],
            EncryptionContext=context, CiphertextBlob=base64.b64decode(cipher, validate=True))['Plaintext']
    value = json.loads(plain)
    if not isinstance(value, dict):
        raise AuthError('Invalid custody')
    return value


def response(status: int, data, *, page: bool = False) -> dict:
    return {'statusCode': status, 'headers': {
        'Content-Type': 'text/html; charset=utf-8' if page else 'application/json',
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        # Navigation POSTs under no-referrer lose Origin in Chromium and fail CSRF.
        'Referrer-Policy': 'strict-origin' if page else 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        # The sign-in page is served on the main site, so it must never be indexed.
        'X-Robots-Tag': 'noindex, nofollow, noarchive',
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
    # Hosts may send this display hint; it must not affect authorization or be reflected.
    params = {k: v for k, v in params.items() if k != 'ui_locales'}
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
    # On the main site the sign-in page is `/auth`; directly on the API it stays `/oauth/authorize`.
    return {'issuer': base, 'authorization_endpoint': connect_origin() + ('/auth' if connect_origin() != base else '/oauth/authorize'),
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


def auth_state(row: dict, csrf: str, message: str = '') -> dict:
    login = uncapsule(row['cipher'], row['client'], row['sidHash'])
    website = row.get('kind') == 'web-auth'
    return response(200, {
        'phase': login.get('phase', 'phone'),
        'csrf': csrf,
        'message': message,
        'website': website,
        'returnPath': str(row.get('return') or '/'),
        'clientName': '' if website else client(row['client'])['name'],
        'destination': website_return(row.get('return', '')) if website else str(row.get('redirect') or ''),
    })


def save_pending(row: dict, login: dict, message: str = '') -> dict:
    csrf = secrets.token_urlsafe(32)
    row['csrfHash'] = digest(csrf)
    row['notice'] = message
    row['cipher'] = capsule(login, row['client'], row['sidHash'])
    STORE.put(row)
    return auth_state(row, csrf, message)


def resume_authorization(event: dict) -> dict | None:
    """Resume a one-use auth step after a safe GET refresh without sending another code."""
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
    cookies = SimpleCookie()
    cookies.load('; '.join(event.get('cookies') or [headers.get('cookie', '')]))
    if COOKIE not in cookies:
        return None
    key = row_key('auth', cookies[COOKIE].value)
    row = STORE.get(key)
    if not row or row.get('kind') not in {'web-auth', 'oauth-auth'}:
        return None
    if row.get('kind') == 'oauth-auth':
        client(row['client'])
        if row.get('resource') != resource():
            raise AuthError('Invalid authorization resource')
    login = uncapsule(row['cipher'], row['client'], key)
    if STORE.take(key) is None:
        return website_recovery()
    return save_pending(row, login, row.get('notice', ''))


def website_get(params: dict, *, json_transport: bool = False) -> dict:
    if set(params) - {'return'}:
        raise AuthError('Invalid website sign-in request')
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'web-auth', 'client': WEBSITE_CLIENT,
           'return': website_return(params.get('return', '')), 'absoluteExpiresAt': int(time.time()) + 600}
    if json_transport:
        row['transport'] = 'json'
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result


def website_recovery(return_hint: str = '') -> dict:
    """Recover stale browser history with a fresh one-use website auth step."""
    destination = website_return(return_hint)
    result = response(303, '')
    result['headers']['Location'] = '/auth' + (('?' + urlencode({'return': destination})) if destination != '/' else '')
    result['cookies'] = [f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
    return result


def website_finish(row: dict, login: dict, auth: dict, event: dict) -> dict:
    """Establish the server-owned website session and redirect without an intermediate page."""
    http = (event.get('requestContext') or {}).get('http') or {}
    payload = {'rawPath': '/ecommerce/customer-session', 'httpMethod': 'POST',
               'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}},
               'headers': {'origin': 'https://wecare.digital', 'content-type': 'application/json',
                           'authorization': 'Bearer ' + auth['AccessToken']},
               'body': json.dumps({'action': 'exchange', 'refreshToken': auth['RefreshToken'], 'persistent': True})}
    invoked = aws('lambda').invoke(FunctionName='wecare-customer-session:live', InvocationType='RequestResponse',
                                   Payload=json.dumps(payload).encode())
    if invoked.get('FunctionError'):
        raise AuthError('Website session unavailable')
    reply = json.loads(invoked['Payload'].read())
    if not isinstance(reply.get('statusCode'), int) or not 200 <= reply['statusCode'] < 300:
        raise AuthError('Website session unavailable')
    body = json.loads(reply.get('body') or '{}')
    csrf, expires_at = body.get('csrfToken'), body.get('expiresAt')
    if not isinstance(csrf, str) or not csrf or not isinstance(expires_at, (int, float)):
        raise AuthError('Website session unavailable')

    # Preserve the existing best-effort contact/order claim without exposing the access token
    # to an intermediate browser document.
    try:
        profile_payload = {'rawPath': '/customer/profile', 'httpMethod': 'POST',
                           'requestContext': {'http': {'method': 'POST', 'sourceIp': str(http.get('sourceIp') or '')}},
                           'headers': {'origin': 'https://wecare.digital', 'content-type': 'application/json',
                                       'authorization': 'Bearer ' + auth['AccessToken']},
                           'body': '{}'}
        aws('lambda').invoke(FunctionName='wecare-customer-profile:live', InvocationType='RequestResponse',
                             Payload=json.dumps(profile_payload).encode())
    except Exception:
        pass

    hint = quote(json.dumps({'csrfToken': csrf, 'expiresAt': int(expires_at), 'persistent': True},
                            separators=(',', ':')), safe='')
    result = response(303, '')
    result['headers']['Location'] = website_return(row.get('return', ''))
    result['cookies'] = list(reply.get('cookies') or []) + [
        f'{SESSION_HINT_COOKIE}={hint}; Secure; SameSite=Lax; Path=/; Max-Age=1800',
        f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0',
    ]
    return result


def authorize_get(params: dict, *, json_transport: bool = False) -> dict:
    params = validate_authorize(params)
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'oauth-auth', 'client': params['client_id'], 'resource': resource(),
           'redirect': params['redirect_uri'], 'state': params['state'], 'scope': params['scope'],
           'challenge': params['code_challenge'], 'absoluteExpiresAt': int(time.time()) + 600}
    if json_transport:
        row['transport'] = 'json'
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result


def authorize_post(params: dict, event: dict) -> dict:
    params = dict(params)
    flow = params.pop('_flow', None)
    return_hint = params.pop('_return', '')
    website_form = flow == 'website'
    if flow not in {None, 'website'} or (return_hint and not website_form):
        raise AuthError('Invalid authorization session')
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
    if headers.get('origin') not in {origin(), connect_origin()}:
        raise AuthError('Authorization origin required')
    cookies = SimpleCookie()
    cookies.load('; '.join(event.get('cookies') or [headers.get('cookie', '')]))
    if COOKIE not in cookies:
        if website_form:
            return website_recovery(return_hint)
        raise AuthError('Authorization session required')
    key = row_key('auth', cookies[COOKIE].value)
    row = STORE.get(key)
    if not row or not hmac.compare_digest(row['csrfHash'], digest(params.get('csrf', ''))):
        if website_form:
            return website_recovery(return_hint)
        raise AuthError('Invalid authorization session')
    login = uncapsule(row['cipher'], row['client'], key)
    website = row.get('kind') == 'web-auth'
    if website != website_form:
        raise AuthError('Invalid authorization session')
    if STORE.take(key) is None:
        raise AuthError('Authorization step already used')
    # Which step failed, for the failure log line below. A step name and an exception class
    # only: never a number, code, session or provider message.
    stage = 'phone' if login.get('phase') == 'phone' else 'challenge'
    try:
        if params.get('action'):
            action = params.get('action')
            allowed_action_fields = {'csrf', 'action', 'code'}
            if set(params) - allowed_action_fields or login.get('phase') not in {'code', 'registration'}:
                raise AuthError('Invalid authorization action')
            if action == 'edit_phone':
                return save_pending(row, {'phase': 'phone'})
            if action != 'resend':
                raise AuthError('Invalid resend request')
            if login.get('phase') == 'registration':
                if not registration_call('request', login['phone'], event):
                    return save_pending(row, login)
                return save_pending(row, login, 'New code sent.')
            result = aws('cognito-idp').initiate_auth(
                ClientId=CUSTOMER_CLIENT, AuthFlow='CUSTOM_AUTH',
                AuthParameters={'USERNAME': login['phone']})
            if (not result.get('Session')
                    or result.get('ChallengeParameters', {}).get('registered') == 'false'):
                return save_pending(row, login)
            return save_pending(row, {'phase': 'code', 'phone': login['phone'], 'session': result['Session']},
                                'New code sent.')
        if login.get('phase') == 'phone':
            try:
                params = {'csrf': params['csrf'], 'phone': normalized_phone(params)}
            except (AuthError, KeyError):
                return save_pending(row, {'phase': 'phone'}, 'Check the number and try again.')
            result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='CUSTOM_AUTH', AuthParameters={'USERNAME': params['phone']})
            challenge = result.get('ChallengeParameters', {})
            if challenge.get('registered') == 'false':
                if registration_call('request', params['phone'], event):
                    return save_pending(row, {'phase': 'registration', 'phone': params['phone']})
                return save_pending(row, {'phase': 'phone'}, 'Couldn’t start sign-in. Try again.')
            return save_pending(row, {'phase': 'code', 'phone': params['phone'], 'session': result['Session']})
        if set(params) != {'csrf', 'code'} or not re.fullmatch(r'[0-9]{6}', params['code']):
            return save_pending(row, login, 'Enter the 6-digit code.')
        if login.get('phase') == 'registration':
            if not registration_call('verify', login['phone'], event, params['code']):
                return save_pending(row, login, 'Code not verified. Try again.')
            result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='CUSTOM_AUTH',
                                                    AuthParameters={'USERNAME': login['phone']})
            if not result.get('Session') or result.get('ChallengeParameters', {}).get('registered') == 'false':
                return save_pending(row, {'phase': 'phone'}, 'Number verified. Get a new code.')
            return save_pending(row, {'phase': 'code', 'phone': login['phone'], 'session': result['Session']},
                                'Account ready. Enter the new code.')
        result = aws('cognito-idp').respond_to_auth_challenge(ClientId=CUSTOMER_CLIENT, ChallengeName='CUSTOM_CHALLENGE',
                    Session=login['session'], ChallengeResponses={'USERNAME': login['phone'], 'ANSWER': params['code']})
        if not result.get('AuthenticationResult'):
            if not result.get('Session'):
                return save_pending(row, {'phase': 'phone'}, 'Code expired. Get a new one.')
            login['session'] = result['Session']
            return save_pending(row, login, 'Wrong code. Try again.')
        auth = result['AuthenticationResult']
        stage = 'identity_check'
        _, subject = checked_cognito(auth)
        if website:
            return website_finish(row, login, auth, event)
        now = int(time.time())
        stage = 'custody'
        grant_key = PREFIX + 'grant:' + secrets.token_urlsafe(32)
        grant = {'sidHash': grant_key, 'kind': 'grant', 'client': row['client'], 'resource': resource(),
                 'scope': row['scope'], 'subject': subject, 'absoluteExpiresAt': now + 30 * 86400,
                 'cipher': capsule(auth, row['client'], grant_key)}
        STORE.put(grant)
        stage = 'authorization_code'
        code = 'wcc_' + secrets.token_urlsafe(32)
        STORE.put({'sidHash': row_key('code', code), 'kind': 'code', 'client': row['client'], 'resource': resource(),
                   'redirect': row['redirect'], 'challenge': row['challenge'], 'grant': grant_key, 'absoluteExpiresAt': now + 120})
        separator = '&' if urlparse(row['redirect']).query else '?'
        result = response(302, {})
        result['headers']['Location'] = row['redirect'] + separator + urlencode({'code': code, 'state': row['state']})
        result['cookies'] = [f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
        return result
    except Exception as error:
        # Never reflect provider error strings, session credentials, numbers or codes. The log
        # line carries the step and a sanitised exception class name only.
        category = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:64]
        print(json.dumps({'event': 'customer_authorization_failed', 'stage': stage, 'category': category}))
        return save_pending(row, login)


def route(event: dict) -> dict | None:
    path = str(event.get('rawPath') or '')
    # The website owns /auth presentation. This backend exposes state/step plus OAuth protocol
    # endpoints; legacy /oauth/authorize GET only redirects into the website flow.
    if path not in {'/.well-known/oauth-authorization-server', '/auth/state', '/auth/step',
                    '/oauth/authorize', '/oauth/token', '/oauth/revoke'}:
        return None
    method = str(((event.get('requestContext') or {}).get('http') or {}).get('method') or '').upper()
    try:
        if path == '/.well-known/oauth-authorization-server' and method == 'GET':
            return response(200, auth_metadata())
        if path in {'/auth/state', '/oauth/authorize'} and method == 'GET':
            params = parse(event.get('rawQueryString', ''))
            target = connect_origin()

            if path == '/oauth/authorize':
                if target == origin():
                    return response(503, {'error': 'authorization_ui_unavailable'})
                validate_authorize(params)
                result = response(302, '')
                result['headers']['Location'] = target + '/auth?' + urlencode(params)
                return result

            # /auth/state is the only state-creation/read endpoint used by the website page.
            if not {'client_id', 'redirect_uri', 'response_type', 'scope', 'state',
                    'resource', 'code_challenge', 'code_challenge_method'}.intersection(params):
                if not params:
                    pending = resume_authorization(event)
                    if pending is not None:
                        return pending
                return website_get(params, json_transport=True)
            return authorize_get(params, json_transport=True)
        if method != 'POST':
            return response(405, {'error': 'invalid_request'})
        headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
        if headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            raise AuthError('Unsupported content type')
        raw = event.get('body') or ''
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode()
        params = parse(raw)
        if path == '/auth/step':
            page = authorize_post(params, event)
            if page.get('statusCode') in {302, 303}:
                result = response(200, {'redirect': (page.get('headers') or {}).get('Location', '/')})
                if page.get('cookies'):
                    result['cookies'] = list(page['cookies'])
                return result
            return page
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
