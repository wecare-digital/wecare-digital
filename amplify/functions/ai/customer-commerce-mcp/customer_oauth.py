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
from connection_assets import BRAND_LOGO, DIAL_COUNTRIES

PREFIX = 'mcp:commerce:'
COOKIE = '__Host-wecare-connect'
CUSTOMER_POOL = 'us-east-1_46ULYuukt'
CUSTOMER_CLIENT = '4avmt9n4gpmkvkdk88qbtit33o'
SCOPES = {'commerce:read', 'commerce:write'}
WEBSITE_CLIENT = 'wecare-website'
WEBSITE_RETURNS = {'/', '/cart/', '/checkout/', '/orders/', '/blog/', '/submit-request/', '/request-amendment/', '/drop-docs/', '/vault/', '/request-pickup/'}
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


def form(row: dict, csrf: str, message: str = '') -> dict:
    login = uncapsule(row['cipher'], row['client'], row['sidHash'])
    phase = login.get('phase', 'phone')
    website = row.get('kind') == 'web-auth'
    country_rows = ''.join(
        '<button class="country-row" type="button" role="option" data-country-code="' +
        html.escape(code, quote=True) + '" data-country-search="' +
        html.escape((country + ' ' + code).lower(), quote=True) + '">' +
        '<span class="country-name">' + html.escape(country) + '</span>' +
        '<span class="country-code">' + html.escape(code) + '</span></button>'
        for code, country, _ in DIAL_COUNTRIES
    )
    if phase == 'phone':
        field = (
            '<label class="field-label" for="phone">WhatsApp number</label>'
            '<div class="phone-field">'
            '<div class="country-picker" data-wc-no-translate="true">'
            '<input id="country" name="country" type="hidden" value="+91">'
            '<button class="country-trigger" id="country-trigger" type="button" aria-haspopup="listbox" '
            'aria-expanded="false" aria-controls="country-panel" aria-label="Calling code">+91</button>'
            '<div class="country-panel" id="country-panel" hidden>'
            '<div class="country-search"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4.2-4.2"/></svg>'
            '<input id="country-search" type="search" autocomplete="off" spellcheck="false" '
            'placeholder="Search country" aria-label="Search country"></div>'
            '<div class="country-rows" id="country-list" role="listbox" aria-label="Calling codes">' +
            country_rows + '</div></div></div>'
            '<input id="phone" name="phone" type="tel" inputmode="numeric" autocomplete="tel-national" '
            'pattern="[0-9]{5,14}" maxlength="14" required placeholder="WhatsApp number">'
            '</div>'
        )
    else:
        field = (
            '<label class="field-label" for="code">Code</label>'
            '<input class="single-field" id="code" name="code" type="password" inputmode="numeric" '
            'autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required '
            'placeholder="6 digits">'
        )

    lockup = (
        '<img src="https://wecare.digital/get/o/stream/media/m/wecaredigital.png" alt="" aria-hidden="true" '
        'width="1080" height="1080" decoding="async">'
        '<span class="brand-copy"><span>WECARE<span class="brand-dot">.</span></span>'
        '<span class="brand-stack">DIGITAL</span></span>'
    )
    menu = (
        '<details class="nav-dropdown"><summary class="nav-trigger" aria-label="Open navigation">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z"/></svg></summary>'
        '<nav class="nav-menu" aria-label="Public navigation"><div class="nav-cols">'
        '<div class="nav-col">'
        '<a class="nav-item nav-primary" href="https://wecare.digital/">Home</a>'
        '<a class="nav-item nav-primary" href="https://wecare.digital/shop/">Shop</a>'
        '<span class="nav-group-label">Products</span>'
        '<a class="nav-item" href="https://wecare.digital/grahak-os/">Grahak OS</a>'
        '<a class="nav-item" href="https://wecare.digital/vayulok/">VayuLok</a>'
        '<a class="nav-item" href="https://wecare.digital/sehat/">Sehat</a>'
        '<span class="nav-family-label">Elsewhere</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/elsewhere/visa/">Visa</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/elsewhere/trip/">Trip</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/elsewhere/activities/">Activities</a>'
        '<a class="nav-item" href="https://wecare.digital/expo-week/">Expo Week</a>'
        '<span class="nav-family-label">Dastavez</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/dastavez/drafting/">Drafting</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/dastavez/registration/">Registration</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/dastavez/legal-reference/">Legal Reference</a>'
        '<span class="nav-family-label">Clear Closure</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shop/guided-resolution/">Guided Resolution</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shop/file-assist/">Case Submission</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shop/paperwork/">Paperwork</a>'
        '<span class="nav-family-label">Ritual Guru</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/ritual-guru/puja-guidance/">Puja Guidance</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/ritual-guru/diy-puja-kit/">DIY Puja Kit</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/ritual-guru/ritva/">Ritva</a>'
        '<a class="nav-item" href="https://wecare.digital/anew/">Anew</a>'
        '<span class="nav-family-label">Hunar</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/hunar/kaushal/">Kaushal</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/hunar/prastuti/">Prastuti</a>'
        '<a class="nav-item" href="https://wecare.digital/niji-setu/">Niji Setu</a>'
        '</div>'
        '<div class="nav-col">'
        '<span class="nav-group-label">Request</span>'
        '<a class="nav-item" href="https://wecare.digital/orders/">Orders</a>'
        '<a class="nav-item" href="https://wecare.digital/submit-request/">Submit Request</a>'
        '<a class="nav-item" href="https://wecare.digital/request-amendment/">Request Amendment</a>'
        '<a class="nav-item" href="https://wecare.digital/drop-docs/">Drop Docs</a>'
        '<a class="nav-item" href="https://wecare.digital/vault/">Vault</a>'
        '<span class="nav-family-label">Shipments</span>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shipments/track/">Track</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/request-pickup/">Pickup Request</a>'
        '<a class="nav-item" href="https://wa.me/message/ZM74K2H2BIFOA1">Leave Review</a>'
        '<a class="nav-item" href="https://wa.me/message/WUDPTMYSO6XII1">Subscribe</a>'
        '</div>'
        '<div class="nav-col">'
        '<span class="nav-group-label">Refer &amp; Earn</span>'
        '<span class="nav-family-label">Partner</span>'
        '<a class="nav-item nav-child" href="https://wa.me/message/S6A2QEXZSYXTG1">Referral</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shop/merchandise/">Merchandise</a>'
        '<a class="nav-item nav-child" href="https://wecare.digital/shop/kiosk/">Kiosk</a>'
        '<span class="nav-group-label">Extras</span>'
        '<a class="nav-item" href="https://wa.me/message/377GALDW4E26F1">Perks</a>'
        '<a class="nav-item" href="https://play.google.com/store/apps/dev?id=5505420420345648842">Google Play</a>'
        '<span class="nav-group-label">With AI</span>'
        '<a class="nav-item" href="https://chatgpt.com/">ChatGPT</a>'
        '<a class="nav-item" href="https://claude.ai/">Claude</a>'
        '<a class="nav-item" href="https://gemini.google.com/">Gemini</a>'
        '<span class="nav-group-label">Contact</span>'
        '<a class="nav-item" href="https://wecare.digital/contact/">Contact us</a>'
        '<span class="nav-group-label">Legal Stuff</span>'
        '<a class="nav-item" href="https://wecare.digital/terms/">Terms</a>'
        '<a class="nav-item" href="https://wecare.digital/privacy/">Privacy</a>'
        '</div>'
        '</div></nav></details>'
    )
    header = (
        '<header class="hdr"><div class="hdr-in"><div class="logo-nav">'
        '<a class="brand logo" data-wc-no-translate="true" href="https://wecare.digital/" aria-label="WECARE.DIGITAL home">' +
        lockup + '</a>' + menu + '</div>'
        '<a class="cart" href="https://wecare.digital/cart/" aria-label="Open cart">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M6 8h12l1 13H5L6 8Zm3 0V6a3 3 0 0 1 6 0v2"/></svg></a>'
        '</div></header>'
    )

    connect_note = (
        '' if website else
        '<p class="destination">Connecting to <strong>' +
        html.escape(client(row['client'])['name']) +
        '</strong></p>'
    )
    alert = '<p class="alert" role="alert">' + html.escape(message) + '</p>' if message else ''
    primary_text = 'Get Code' if phase == 'phone' else 'Verify'
    resend = (
        '' if phase == 'phone' else
        '<button class="auth-action" type="submit" name="action" value="resend" formnovalidate>Resend code</button>'
    )
    action_note = '<span class="auth-action-note">Verification code</span>'
    hero_words = [
        ('the website', '#fef3c7', '#f0a818'),
        ('ChatGPT', '#ede9fe', '#9849e8'),
        ('Claude', '#e0f7c8', '#3da35a'),
        ('Gemini', '#fee2e2', '#dc2626'),
    ]
    hero_nodes = ''.join(
        '<span class="home-cyc-word' + (' on' if i == 0 else '') + '" data-wc-translate="true" '
        'aria-hidden="true">' + html.escape(word) + '</span>'
        for i, (word, _, _) in enumerate(hero_words)
    )
    hero_pill = (
        '<span class="home-pill" id="auth-rotating-pill" style="background:' + hero_words[0][1] + '">'
        '<i class="home-pill-dot" aria-hidden="true" style="background:' + hero_words[0][2] + '"></i>'
        '<span class="home-cycle">'
        '<span class="home-sr-only">' + html.escape(', '.join(word for word, _, _ in hero_words)) + '</span>' +
        hero_nodes + '</span></span>'
    )
    nonce = secrets.token_urlsafe(24)
    rotation_script = (
        "(function(){"
        "const data=" + json.dumps([{'word': w, 'tint': t, 'dot': d} for w, t, d in hero_words], separators=(',', ':')) + ";"
        "const pill=document.getElementById('auth-rotating-pill');if(!pill)return;"
        "const dot=pill.querySelector('.home-pill-dot'),cycle=pill.querySelector('.home-cycle'),"
        "words=Array.from(pill.querySelectorAll('.home-cyc-word'));let i=0;"
        "const draw=()=>{words.forEach((n,j)=>n.classList.toggle('on',j===i));"
        "pill.style.background=data[i].tint;dot.style.background=data[i].dot;"
        "cycle.style.width=words[i].offsetWidth+'px'};"
        "draw();if(document.fonts&&document.fonts.ready)document.fonts.ready.then(draw);"
        "addEventListener('resize',draw,{passive:true});"
        "if(!(matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches))"
        "setInterval(()=>{i=(i+1)%words.length;draw()},2400);"
        "})();"
    )
    country_script = (
        "(function(){"
        "const trigger=document.getElementById('country-trigger'),panel=document.getElementById('country-panel'),"
        "search=document.getElementById('country-search'),hidden=document.getElementById('country');"
        "if(!trigger||!panel||!search||!hidden)return;"
        "const rows=Array.from(panel.querySelectorAll('.country-row'));"
        "const close=(focus)=>{panel.hidden=true;trigger.setAttribute('aria-expanded','false');search.value='';"
        "rows.forEach(r=>r.hidden=false);if(focus)trigger.focus()};"
        "const open=()=>{panel.hidden=false;trigger.setAttribute('aria-expanded','true');search.value='';"
        "rows.forEach(r=>r.hidden=false);requestAnimationFrame(()=>search.focus())};"
        "trigger.addEventListener('click',()=>panel.hidden?open():close(true));"
        "search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();"
        "rows.forEach(r=>{r.hidden=!!q&&!r.dataset.countrySearch.includes(q)})});"
        "rows.forEach(r=>r.addEventListener('click',()=>{const code=r.dataset.countryCode||'+91';hidden.value=code;"
        "trigger.textContent=code;close(true)}));"
        "document.addEventListener('pointerdown',e=>{if(!panel.hidden&&!panel.contains(e.target)&&e.target!==trigger)close(false)},true);"
        "document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();close(true)}});"
        "})();"
    )

    sign_in = (
        '<section class="home-connect" aria-label="WECARE account sign in"><div class="connect-panel">' +
        '<div class="connect-eyebrow">'
        '<span class="connect-eyebrow-icon" aria-hidden="true">'
        '<svg viewBox="0 0 24 24" focusable="false"><path d="M7 8h10l1 12H6L7 8Zm2.5 0V6.5a2.5 2.5 0 0 1 5 0V8"/>'
        '<path d="M9 13.2c1.1-1.3 2.1-1.3 3 0 1-1.3 2-1.3 3 0 0 2-3 3.8-3 3.8s-3-1.8-3-3.8Z"/></svg>'
        '</span><span>Access</span></div>' +
        connect_note + alert +
        '<form method="post" action="' + ('/auth' if connect_origin() != origin() else '/oauth/authorize') + '">'
        '<input type="hidden" name="csrf" value="' + html.escape(csrf, quote=True) + '">' +
        field +
        '<div class="auth-actions"><button class="auth-action" type="submit">' + primary_text + '</button>' +
        resend + action_note + '</div></form>'
        '</div></section>'
    )
    stay_connected = (
        '<section class="public-share has-contribute" aria-label="Contribute, subscribe and share">'
        '<span class="ps-kicker">Stay connected</span>'
        '<div class="ps-row">'
        '<details class="ps-details ps-contribute-details">'
        '<summary class="ps-action ps-contribute" aria-label="Contribute ₹250">'
        '<span class="ps-symbol" aria-hidden="true">₹</span><span class="ps-tip">Contribute</span></summary>'
        '<div class="ps-menu ps-contribute-menu"><div class="ps-menu-head">'
        '<div class="ps-menu-title">Contribute ₹250</div>'
        '<p class="ps-menu-sub">Review it in your cart, then choose how to pay.</p></div>'
        '<div class="ps-menu-list"><a class="ps-menu-item" href="https://wecare.digital/cart/">'
        '<span class="ps-menu-icon" aria-hidden="true">₹</span>'
        '<span class="ps-menu-copy"><span class="ps-menu-name">Checkout</span>'
        '<span class="ps-menu-note">Review contribution in cart</span></span>'
        '<span class="ps-chevron" aria-hidden="true">›</span></a></div></div></details>'
        '<a class="ps-action ps-subscribe" href="https://wa.me/message/WUDPTMYSO6XII1" '
        'target="_blank" rel="noopener noreferrer" aria-label="Subscribe on WhatsApp">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M12 21a2.5 2.5 0 0 0 2.4-2H9.6A2.5 2.5 0 0 0 12 21Zm6-5H6l1.5-2V9a4.5 4.5 0 0 1 9 0v5Z"/></svg>'
        '<span class="ps-tip">Subscribe</span></a>'
        '<details class="ps-details ps-share-details">'
        '<summary class="ps-action ps-share-trigger" aria-label="Share this page">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<circle cx="6" cy="12" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/>'
        '<path d="m8 11 8-4M8 13l8 4"/></svg><span class="ps-tip">Share</span></summary>'
        '<div class="ps-menu ps-share-menu"><div class="ps-menu-head">'
        '<div class="ps-menu-title">Share</div><p class="ps-menu-sub">Send this page.</p></div>'
        '<div class="ps-menu-list"><a class="ps-menu-item" '
        'href="https://wa.me/?text=Sign%20in%20to%20WECARE.DIGITAL%20https%3A%2F%2Fwecare.digital%2Fauth" '
        'target="_blank" rel="noopener noreferrer" aria-label="Share this page on WhatsApp">'
        '<span class="ps-menu-icon" aria-hidden="true">↗</span>'
        '<span class="ps-menu-copy"><span class="ps-menu-name">WhatsApp</span>'
        '<span class="ps-menu-note">Share on WhatsApp</span></span>'
        '<span class="ps-chevron" aria-hidden="true">›</span></a></div></div></details>'
        '</div></section>'
    )
    support_widget = (
        '<div class="wc-langbar" id="wc-auth-widget" data-wc-no-translate="true">'
        '<div class="wc-pill">'
        '<a class="wc-wa" href="https://wecare.digital/r/wa" target="_blank" rel="noopener noreferrer" '
        'aria-label="Chat with us on WhatsApp" title="Chat with us on WhatsApp">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" '
        'd="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.4-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.03 1.02-1.03 2.48 0 1.46 1.06 2.87 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2-1.41.25-.7.25-1.29.18-1.42-.08-.12-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 01-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 01-1.51-5.26C2.16 6.45 6.6 2.01 12.05 2.01c2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 012.89 6.99c0 5.45-4.44 9.89-9.88 9.89M20.46 3.49A11.82 11.82 0 0012.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 005.69 1.45c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.17-3.48-8.42z"/></svg></a>'
        '<span class="wc-sep" aria-hidden="true"></span>'
        '<button class="wc-chip" id="wc-lang-trigger" type="button" aria-expanded="false" aria-haspopup="listbox" '
        'aria-controls="wc-lang-panel" aria-label="Language: English. Choose another.">EN<span class="wc-arw" aria-hidden="true"></span></button>'
        '</div>'
        '<div class="wc-panel" id="wc-lang-panel" hidden>'
        '<div class="wc-search"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4.2-4.2"/></svg>'
        '<input id="wc-lang-search" type="text" role="combobox" aria-expanded="true" aria-controls="wc-lang-list" '
        'aria-autocomplete="list" aria-label="Search language" placeholder="Search language" autocomplete="off" spellcheck="false"></div>'
        '<div class="wc-rows" id="wc-lang-list" role="listbox" aria-label="Languages"></div>'
        '<p class="wc-more" id="wc-more" hidden></p></div>'
        '<div class="wc-sr" id="wc-status" role="status" aria-live="polite"></div>'
        '</div>'
    )
    support_script = (
        "(function(){"
        "const w=document.getElementById('wc-auth-widget'),trigger=document.getElementById('wc-lang-trigger'),"
        "panel=document.getElementById('wc-lang-panel'),search=document.getElementById('wc-lang-search'),"
        "list=document.getElementById('wc-lang-list'),more=document.getElementById('wc-more'),status=document.getElementById('wc-status');"
        "if(!w||!trigger||!panel||!search||!list||!more||!status)return;"
        "let langs=[],current='en',busy=false,originals=null,attrOriginals=null;"
        "const rtl=new Set(['ar','fa','he','ur','ps','sd']);"
        "const skip=new Set(['SCRIPT','STYLE','NOSCRIPT','IFRAME','SVG','CANVAS','VIDEO','AUDIO','INPUT','TEXTAREA','SELECT','OPTION','CODE','PRE','HEAD','META','LINK']);"
        "const eligible=el=>{for(let n=el;n&&n!==document.body;n=n.parentElement){if(n.dataset&&n.dataset.wcNoTranslate==='true')return false;if(skip.has(n.tagName))return false}return true};"
        "const restore=()=>{if(originals)originals.forEach(x=>{if(x.node.parentNode)x.node.nodeValue=x.value});"
        "if(attrOriginals)attrOriginals.forEach(x=>{if(x.el.isConnected)x.el.setAttribute(x.attr,x.value)})};"
        "const collect=()=>{const items=[];const root=document.body;const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){"
        "const v=(n.nodeValue||'').trim(),p=n.parentElement;if(v.length<2||!/[A-Za-z\\u0900-\\u0DFF\\u0600-\\u06FF]/.test(v)||!p||!eligible(p))return NodeFilter.FILTER_REJECT;"
        "return NodeFilter.FILTER_ACCEPT}});let n;while((n=walker.nextNode()))items.push({kind:'text',node:n,text:(n.nodeValue||'').trim()});"
        "['placeholder','aria-label','title'].forEach(a=>document.querySelectorAll('['+a+']').forEach(el=>{const v=(el.getAttribute(a)||'').trim();"
        "if(v.length>=2&&/[A-Za-z\\u0900-\\u0DFF\\u0600-\\u06FF]/.test(v)&&eligible(el))items.push({kind:'attr',el:el,attr:a,text:v})}));return items};"
        "const apply=async code=>{if(busy)return;busy=true;trigger.classList.add('is-busy');status.textContent='Translating…';"
        "try{restore();if(code==='en'){document.documentElement.lang='en';document.documentElement.dir='ltr';current='en';trigger.firstChild.nodeValue='EN';"
        "trigger.setAttribute('aria-label','Language: English. Choose another.');status.textContent='Showing English.';return}"
        "const items=collect();if(!originals){originals=items.filter(x=>x.kind==='text').map(x=>({node:x.node,value:x.node.nodeValue||''}));"
        "attrOriginals=items.filter(x=>x.kind==='attr').map(x=>({el:x.el,attr:x.attr,value:x.el.getAttribute(x.attr)||''}))}"
        "for(let i=0;i<items.length;i+=30){const batch=items.slice(i,i+30);const r=await fetch('/api/site-language/translate',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({texts:batch.map(x=>x.text),targetLanguage:code,sourceLanguage:'en'})});if(!r.ok)throw new Error('translate');"
        "const rows=(await r.json()).translations||[];if(rows.length!==batch.length)throw new Error('shape');rows.forEach((row,j)=>{const x=batch[j],v=row.translatedText;if(!v)return;"
        "if(x.kind==='text'&&x.node.parentNode)x.node.nodeValue=v;else if(x.kind==='attr'&&x.el.isConnected)x.el.setAttribute(x.attr,v)})}"
        "current=code;document.documentElement.lang=code;document.documentElement.dir=rtl.has(code.split('-')[0])?'rtl':'ltr';"
        "trigger.firstChild.nodeValue=(code.split('-')[0]||'en').toUpperCase();const label=(langs.find(x=>x.code===code)||{}).name||code;"
        "trigger.setAttribute('aria-label','Language: '+label+'. Choose another.');status.textContent='Page translated to '+label+'.'}"
        "catch(e){restore();current='en';document.documentElement.lang='en';document.documentElement.dir='ltr';trigger.firstChild.nodeValue='EN';"
        "status.textContent='Translation unavailable.'}finally{busy=false;trigger.classList.remove('is-busy')}};"
        "const matches=q=>{q=q.trim().toLowerCase();let rows=langs;if(q)rows=langs.map(x=>({x:x,rank:x.code.toLowerCase()===q?0:x.name.toLowerCase().startsWith(q)?1:x.code.toLowerCase().startsWith(q)?2:x.name.toLowerCase().includes(q)?3:9}))"
        ".filter(y=>y.rank<9).sort((a,b)=>a.rank-b.rank||a.x.name.localeCompare(b.x.name)).map(y=>y.x);return rows};"
        "const render=()=>{const rows=matches(search.value),shown=rows.slice(0,5);list.textContent='';shown.forEach(x=>{const b=document.createElement('button');b.type='button';b.className='wc-row'+(x.code===current?' is-on':'');"
        "b.setAttribute('role','option');b.setAttribute('aria-selected',String(x.code===current));const n=document.createElement('span');n.className='wc-row-name';n.textContent=x.name;"
        "const code=document.createElement('span');code.className='wc-row-code';code.textContent=x.code.toUpperCase();b.append(n,code);b.addEventListener('click',()=>{close(false);apply(x.code)});list.appendChild(b)});"
        "const extra=Math.max(rows.length-5,0);more.hidden=!extra;more.textContent=extra+' more — keep typing'};"
        "const close=focus=>{panel.hidden=true;trigger.setAttribute('aria-expanded','false');search.value='';if(focus)trigger.focus()};"
        "const open=()=>{panel.hidden=false;trigger.setAttribute('aria-expanded','true');render();requestAnimationFrame(()=>search.focus())};"
        "trigger.addEventListener('click',()=>{if(busy)return;panel.hidden?open():close(true)});search.addEventListener('input',render);"
        "search.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close(true)}else if(e.key==='Enter'){e.preventDefault();const b=list.querySelector('.wc-row');if(b)b.click()}});"
        "document.addEventListener('pointerdown',e=>{if(!panel.hidden&&!w.contains(e.target))close(false)},true);"
        "fetch('/api/site-language/languages').then(r=>r.ok?r.json():Promise.reject()).then(p=>{const drop=new Set(['auto','fr-CA','zh-TW','es-MX','pt-PT']);"
        "langs=(p.languages||[]).filter(x=>!drop.has(x.code)).map(x=>({code:x.code,name:x.code==='ht'?'Creole':x.name})).sort((a,b)=>a.code==='en'?-1:b.code==='en'?1:a.name.localeCompare(b.name));"
        "if(langs.length<2){trigger.hidden=true;w.querySelector('.wc-sep').hidden=true}}).catch(()=>{trigger.hidden=true;w.querySelector('.wc-sep').hidden=true});"
        "})();"
    )
    footer = (
        '<footer class="ft-footer"><div class="ft-in"><div class="ft-grid"><div class="ft-brand">'
        '<a class="ft-home" data-wc-no-translate="true" href="https://wecare.digital/" aria-label="WECARE.DIGITAL home">'
        '<span class="brand compact">' + lockup + '</span></a>'
        '<p class="ft-tagline">Trusted everyday services for Bharat</p>'
        '<span class="ft-dash" aria-hidden="true"></span>'
        '</div></div></div></footer>'
    )

    styles = (
        '*{box-sizing:border-box}:root{--green:#1a3a2a;--lime:#d1f470;--lime-tint:#f7fbe9;'
        '--hair:#e5e7eb;--text:#1a1a1a;--heading:rgba(0,0,0,.95);--body:rgba(0,0,0,.898);'
        '--muted:rgba(0,0,0,.54);--content:1300px;--copy:560px}html{background:#fff}body{margin:0;'
        "background:#fff;color:var(--text);font:16px/1.55 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}"
        'a{color:inherit}.hdr{position:fixed;top:0;inset-inline:0;z-index:1001;background:#fff}'
        '.hdr-in{max-width:var(--content);margin:0 auto;padding:18px 24px;display:flex;align-items:center;'
        'justify-content:space-between;box-sizing:border-box;height:108px;min-width:0;overflow-x:hidden;overflow-x:clip}'
        '.logo-nav{display:flex;align-items:center;gap:10px;min-width:0;max-width:100%}.brand{display:flex;align-items:center;'
        'gap:10px;text-decoration:none;min-width:0}.brand img{width:64px;height:64px;object-fit:contain;border-radius:12px;flex:0 0 auto}.brand-copy{display:flex;'
        'flex-direction:column;justify-content:center;line-height:1.08;font-size:24px;font-weight:800;letter-spacing:-.5px;color:#1a1a1a;white-space:nowrap}'
        '.brand-dot{color:#ff0040}.brand-stack{display:flex;align-items:center;gap:2px}.brand-copy>span+span{margin-top:0}.nav-dropdown{position:relative;min-width:0}'
        '.nav-dropdown summary{list-style:none}.nav-dropdown summary::-webkit-details-marker,.ps-details>summary::-webkit-details-marker{display:none}'
        '.nav-trigger{min-width:46px;min-height:46px;background:#f4f7ee;border:0;border-radius:10px;cursor:pointer;padding:8px;'
        'display:flex;align-items:center;justify-content:center}.nav-trigger svg{width:24px;height:24px;fill:var(--green);transition:transform .18s}'
        '.nav-dropdown[open] .nav-trigger{background:var(--lime)}.nav-dropdown[open] .nav-trigger svg{transform:rotate(180deg)}'
        '.nav-trigger:focus-visible,.cart:focus-visible,.nav-item:focus-visible,.ft-home:focus-visible,.ps-action:focus-visible,'
        '.ps-menu-item:focus-visible,input:focus-visible,select:focus-visible,button:focus-visible{outline:3px solid var(--green);outline-offset:3px}'
        '.nav-menu{display:none;position:absolute;top:58px;inset-inline-start:0;width:min(760px,calc(100vw - 48px));'
        'max-height:min(72vh,680px);overflow:auto;padding:20px;background:#fff;border:1px solid var(--hair);border-radius:18px;'
        'box-shadow:0 18px 46px rgba(26,58,42,.13)}.nav-dropdown[open] .nav-menu{display:block}.nav-cols{display:grid;'
        'grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}.nav-col{display:flex;flex-direction:column;min-width:0}'
        '.nav-group-label{margin:16px 10px 6px;color:var(--muted);font-size:12px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}'
        '.nav-family-label{display:block;padding:9px 10px 4px;color:var(--green);font-size:19px;font-weight:600;line-height:1.25}'
        '.nav-item{display:block;padding:9px 10px;border-radius:10px;color:var(--green);font-size:19px;font-weight:600;line-height:1.25;'
        'text-decoration:none}.nav-item:hover{background:var(--lime-tint)}.nav-primary{font-weight:700}.nav-child{padding-inline-start:28px;font-size:17px}'
        '.cart{width:46px;height:46px;border-radius:50%;border:2px solid var(--hair);display:flex;align-items:center;justify-content:center;'
        'text-decoration:none;background:#fff;flex:0 0 auto}.cart:hover{background:var(--lime);border-color:var(--green)}.cart svg{width:22px;'
        'height:22px;fill:none;stroke:var(--green);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}'
        '.home-shell{min-height:100vh;min-height:100dvh;padding-top:108px;box-sizing:border-box;background:#fff;color:var(--text)}'
        '.home-layout{width:100%;max-width:var(--content);margin:0 auto;padding:80px 24px 48px;box-sizing:border-box;display:flex;'
        'flex-direction:column;gap:96px;min-width:0;overflow-x:hidden;overflow-x:clip}.home-hero{display:flex;flex-direction:column;align-items:flex-start;'
        'min-width:0;max-width:100%;overflow-x:hidden;overflow-x:clip}.home-head{font-size:clamp(36px,4.3vw,60px);font-weight:600;line-height:1.04;'
        'letter-spacing:-.04em;color:var(--heading);margin:0;max-width:min(900px,100%);min-width:0}.home-head-line{display:block;text-wrap:balance}'
        '.home-pill{position:relative;display:inline-block;border-radius:9999px;padding:.02em .3em .02em .22em;margin-top:.08em;white-space:nowrap;'
        'max-width:100%;transition:background-color .52s cubic-bezier(.16,1,.3,1)}.home-pill-dot{position:relative;z-index:1;display:inline-block;'
        'width:.33em;height:.33em;border-radius:50%;margin-inline-end:.18em;vertical-align:.14em;transition:background-color .52s cubic-bezier(.16,1,.3,1)}'
        '.home-cycle{width:max-content;position:relative;z-index:1;display:inline-block;height:1.06em;line-height:1.06em;vertical-align:baseline;overflow:hidden;'
        'transition:width .52s cubic-bezier(.16,1,.3,1);will-change:width}.home-cyc-word{position:absolute;left:0;top:0;white-space:nowrap;opacity:0;'
        'transform:translateY(.42em);transition:opacity .42s cubic-bezier(.16,1,.3,1),transform .42s cubic-bezier(.16,1,.3,1)}'
        '.home-cyc-word.on{opacity:1;transform:translateY(0);position:static;display:inline-block}.home-sr-only{position:absolute;width:1px;height:1px;'
        'padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.home-sub{font-size:20px;font-weight:400;line-height:1.4;'
        'letter-spacing:-.125px;color:var(--body);margin:24px 0 0;max-width:var(--copy);text-wrap:balance}'
        '.home-connect{width:min(100%,420px);min-width:0;align-self:flex-start}.connect-panel{width:100%;padding:18px;'
        'border:0;border-radius:14px;background:#fcfdfa;box-shadow:0 8px 24px rgba(16,32,24,.06)}.connect-eyebrow{display:inline-flex;align-items:center;gap:9px;'
        'width:max-content;max-width:100%;min-height:42px;margin:0 0 18px;padding:0 15px;border-radius:9999px;background:var(--lime);'
        'color:var(--green);font-size:18px;font-weight:700;line-height:1.1;letter-spacing:0;text-transform:none}.connect-eyebrow-icon{'
        'width:23px;height:23px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}.connect-eyebrow-icon svg{'
        'width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}'
        '.destination{margin:0 0 14px;color:var(--muted);font-size:14px}.destination strong{color:var(--green)}'
        '.field-label{display:block;margin:0 0 7px;color:var(--text);font-size:15px;font-weight:700}.phone-field{display:flex;'
        'width:100%;min-height:48px;border:1px solid #eef0e6;border-radius:12px;background:#fff;position:relative}.country-picker{position:relative;'
        'flex:0 0 82px;display:flex}.country-trigger{width:82px;min-height:46px;border:0;border-radius:11px 0 0 11px;background:var(--lime-tint);'
        'color:var(--green);font:700 16px/1 inherit;cursor:pointer;padding:0 10px;text-align:center}.country-trigger:focus-visible{outline:3px solid var(--green);outline-offset:-3px}'
        '.country-panel{position:absolute;top:56px;inset-inline-start:0;z-index:1200;width:min(260px,calc(100vw - 40px));max-height:300px;'
        'display:flex;flex-direction:column;background:#fcfdfa;border:1px solid #e8ecdf;border-top:3px solid var(--lime);border-radius:14px;'
        'box-shadow:0 14px 40px rgba(16,32,24,.18);overflow:hidden}.country-panel[hidden]{display:none}.country-search{display:flex;align-items:center;gap:8px;'
        'padding:10px 12px;border-bottom:1px solid #f1f3ec;background:#fff}.country-search svg{width:17px;height:17px;fill:none;stroke:var(--green);'
        'stroke-width:2.2;stroke-linecap:round;opacity:.45}.country-search input{width:100%;min-width:0;min-height:0;height:auto;border:0;border-radius:0;'
        'outline:0;box-shadow:none;padding:0;margin:0;background:transparent;font:600 16px/1.3 inherit;color:var(--green)}.country-search input:focus{outline:0;box-shadow:none}'
        '.country-rows{overflow:auto;min-height:0}.country-row{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-height:48px;'
        'padding:10px 14px;border:0;border-radius:0;background:transparent;color:var(--green);font:600 16px/1.25 inherit;text-align:start;cursor:pointer}'
        '.country-row:hover,.country-row:focus-visible{background:rgba(209,244,112,.38)}.country-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
        '.country-code{flex:0 0 auto;font-size:13px;font-weight:700;color:rgba(26,58,42,.58)}.phone-field>input{flex:1 1 auto;width:0;min-width:0;border:0;'
        'border-radius:0 11px 11px 0;background:#fff;color:var(--text);padding:0 12px;font-family:inherit;font-size:16px;box-shadow:none}.phone-field:focus-within{'
        'border-color:var(--lime)}.phone-field>input:focus-visible{outline:3px solid var(--green);outline-offset:-3px}.single-field{width:100%;min-height:48px;'
        'border:1px solid #eef0e6;border-radius:12px;background:#fff;color:var(--text);padding:0 12px;font-family:inherit;font-size:16px;line-height:1.2;box-shadow:none}'
        '.single-field:focus-visible{border-color:var(--lime);outline:3px solid var(--green);outline-offset:2px}.auth-actions{display:flex;align-items:center;gap:9px;'
        'flex-wrap:wrap;margin-top:13px}.auth-action{display:inline-flex;align-items:center;width:max-content;max-width:100%;min-height:44px;box-sizing:border-box;'
        'margin:0;padding:6px 9px;border:0;border-radius:8px;background:var(--lime-tint);color:var(--green);font-family:inherit;font-size:17px;font-weight:600;'
        'line-height:1.4;letter-spacing:-.05px;white-space:normal;overflow-wrap:anywhere;text-align:start;text-decoration:underline;text-decoration-thickness:1.5px;'
        'text-underline-offset:3px;cursor:pointer;transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s}'
        '.auth-action:hover{background:var(--lime);text-decoration-color:transparent;transform:translateY(-1px);box-shadow:0 5px 14px rgba(26,58,42,.1)}'
        '.auth-action:focus-visible{background:var(--lime);text-decoration-color:transparent;outline:3px solid var(--green);outline-offset:3px}.auth-action-note{'
        'color:var(--muted);font-size:13px;font-weight:500;line-height:1.35}.alert{margin:0 0 12px;padding:8px 10px;border:0;background:#fff;border-radius:8px;'
        'color:var(--text);font-size:14px;line-height:1.4}'        '.public-action-tail{width:100%;max-width:var(--content);margin:0 auto;padding:0 24px;box-sizing:border-box}.public-share{position:relative;width:100%;'
        'margin-top:32px;padding:12px 0 28px}.ps-kicker{display:flex;width:max-content;max-width:100%;align-items:center;min-height:32px;padding:0 14px;'
        'margin:0 0 18px;border-radius:999px;background:var(--lime);color:var(--green);font-size:17px;font-weight:700;line-height:1}.ps-row{display:flex;'
        'flex-wrap:wrap;align-items:center;gap:12px;width:max-content;max-width:100%}.ps-details{position:relative}.ps-action{position:relative;width:48px;height:48px;'
        'box-sizing:border-box;border-radius:50%;border:2px solid var(--hair);background:#fff;color:var(--green);display:inline-flex;align-items:center;'
        'justify-content:center;padding:0;flex:0 0 auto;cursor:pointer;text-decoration:none;transition:background-color .18s,border-color .18s,transform .18s,box-shadow .18s}'
        '.ps-action:hover{border-color:var(--green);background:var(--lime);transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.10)}'
        '.ps-contribute{background:#eef7d6;border-color:var(--green)}.ps-subscribe{background:var(--lime);border-color:var(--green)}.ps-subscribe:hover{background:#fff}'
        '.ps-action svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.ps-symbol{font-size:25px;font-weight:500;line-height:1}'
        '.ps-tip{position:absolute;inset-inline-start:50%;bottom:calc(100% + 9px);transform:translateX(-50%) translateY(4px);padding:6px 9px;border-radius:8px;'
        'background:var(--green);color:#fff;white-space:nowrap;font-size:14px;font-weight:650;line-height:1.2;opacity:0;pointer-events:none;z-index:40;'
        'transition:opacity .15s,transform .15s}.ps-action:hover .ps-tip,.ps-action:focus-visible .ps-tip{opacity:1;transform:translateX(-50%) translateY(0)}'
        '.ps-menu{position:absolute;top:58px;inset-inline-start:0;z-index:30;width:min(340px,calc(100vw - 48px));padding:8px;background:#fff;border:1px solid var(--hair);'
        'border-radius:18px;box-shadow:0 18px 46px rgba(26,58,42,.13)}.ps-details:not([open]) .ps-menu{display:none}.ps-menu-head{padding:9px 11px 10px;'
        'border-bottom:1px solid #f0f1ed}.ps-menu-title{margin:0;color:var(--text);font-size:18px;font-weight:700;line-height:1.3}.ps-menu-sub{margin:4px 0 0;'
        'color:var(--muted);font-size:15px;font-weight:500;line-height:1.4}.ps-menu-list{padding-top:6px}.ps-menu-item{width:100%;min-height:56px;display:grid;'
        'grid-template-columns:38px minmax(0,1fr) 20px;gap:10px;align-items:center;padding:7px 10px;border:0;border-radius:12px;background:#fff;color:var(--green);'
        'text-decoration:none;cursor:pointer}.ps-menu-item:hover{background:var(--lime-tint)}.ps-menu-icon{width:38px;height:38px;border-radius:50%;display:inline-flex;'
        'align-items:center;justify-content:center;background:#eef7d6;color:var(--green);font-size:20px;font-weight:700}.ps-menu-name{display:block;color:var(--green);'
        'font-size:17px;font-weight:700;line-height:1.25}.ps-menu-note{display:block;margin-top:3px;color:var(--muted);font-size:15px;font-weight:500;line-height:1.35}'
        '.ps-chevron{font-size:24px;color:rgba(26,58,42,.55)}.ft-footer{background:#fff;border-top:1px solid #eef0e6;padding:56px 0 40px;'
        'padding-bottom:calc(40px + env(safe-area-inset-bottom))}.ft-in{max-width:var(--content);margin:0 auto;padding:0 24px}.ft-grid{display:flex;align-items:flex-end;'
        'justify-content:flex-start;gap:32px;flex-wrap:wrap}.ft-brand{display:flex;flex-direction:column;align-items:flex-start;gap:14px;min-width:0}.ft-home{display:inline-flex;'
        'align-items:center;min-height:44px;text-decoration:none;border-radius:10px}.compact svg{width:44px;height:44px}.compact .brand-copy{font-size:18px}.ft-tagline{font-size:16px;'
        'line-height:1.6;color:var(--muted);margin:0;max-width:340px}.ft-dash{display:block;width:56px;height:3px;border-radius:999px;background:var(--lime)}'
        '@media(max-width:767px){.hdr-in{height:96px;padding:18px 16px}.brand svg{width:52px;height:52px}.brand-copy{font-size:20px}.home-shell{padding-top:96px}'
        '.home-layout{padding:48px 16px 40px;gap:64px}.home-head{font-size:40px;line-height:1.1}.connect-panel{padding:16px}.home-connect{width:min(100%,400px)}.country-panel{width:min(260px,calc(100vw - 32px))}.nav-menu{position:fixed;top:96px;'
        'inset-inline:16px;width:auto;max-height:calc(100vh - 112px);border-radius:16px}.nav-cols{grid-template-columns:1fr}.public-action-tail{padding:0 16px}'
        '.ft-in{padding:0 16px}.ft-footer{padding-top:48px}.compact img{width:44px;height:44px}.compact .brand-copy{font-size:18px}.ft-tagline{font-size:16px}.cart{width:44px;height:44px}.brand img{width:58px;height:58px}.brand-copy{font-size:22px}.wc-langbar{--wc-inset:16px;bottom:calc(20px + env(safe-area-inset-bottom))}.wc-pill{padding:3px;gap:0}.wc-chip{min-width:44px;padding:0 8px}.wc-arw{display:none}.wc-sep{height:22px}}'
        '@media(min-width:280px) and (max-width:399px){.home-head{font-size:clamp(27px,9.4vw,32px)}.home-head-line{max-width:none;white-space:nowrap;text-wrap:nowrap}}'

        '.wc-langbar{--wc-inset:20px;position:fixed;right:max(var(--wc-inset),env(safe-area-inset-right));left:auto;bottom:20px;top:auto;z-index:1300;'
        'display:flex;flex-direction:column;align-items:flex-end;gap:10px;font-family:inherit}.wc-pill{position:relative;overflow:hidden;display:inline-flex;align-items:center;'
        'gap:2px;padding:4px;background:#fff;border:1.5px solid var(--lime);border-radius:9999px;box-shadow:0 6px 22px rgba(16,32,24,.14)}.wc-wa{width:44px;'
        'height:44px;min-width:44px;min-height:44px;border-radius:50%;background:var(--lime);color:var(--green);display:grid;place-items:center;text-decoration:none}'
        '.wc-wa svg{width:23px;height:23px;display:block}.wc-sep{width:1px;height:24px;background:#eef0e6;flex:0 0 auto}.wc-chip{position:relative;display:inline-flex;'
        'align-items:center;height:44px;min-width:56px;justify-content:center;padding:0 9px 0 11px;border:0;border-radius:9999px;background:transparent;color:var(--green);'
        'font-family:inherit;font-size:16px;font-weight:700;letter-spacing:.02em;cursor:pointer}.wc-chip:focus-visible{outline:3px solid var(--green);outline-offset:2px}'
        '.wc-arw{width:6px;height:6px;box-sizing:border-box;border-right:2px solid var(--green);border-bottom:2px solid var(--green);transform:translateY(-2px) rotate(45deg);'
        'margin-inline-start:7px;opacity:.7}.wc-chip[aria-expanded="true"] .wc-arw{transform:translateY(1px) rotate(225deg)}.wc-chip.is-busy{background:rgba(209,244,112,.38)}'
        '.wc-panel{order:-1;display:flex;flex-direction:column;width:232px;max-height:min(360px,calc(100dvh - 150px));background:#fcfdfa;border:1px solid #e8ecdf;'
        'border-top:3px solid var(--lime);border-radius:14px;box-shadow:0 14px 40px rgba(16,32,24,.18);overflow:hidden}.wc-panel[hidden]{display:none}.wc-search{display:flex;'
        'align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #f1f3ec;background:#fff}.wc-search svg{width:17px;height:17px;fill:none;stroke:var(--green);'
        'stroke-width:2.2;stroke-linecap:round;opacity:.45}.wc-search input{width:100%;min-width:0;min-height:0;height:auto;border:0;border-radius:0;outline:0;box-shadow:none;'
        'padding:0;margin:0;background:transparent;font-family:inherit;font-size:16px;font-weight:600;color:var(--green)}.wc-search input:focus{outline:0;box-shadow:none}.wc-rows{'
        'overflow:auto;min-height:0}.wc-row{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-height:48px;padding:10px 14px;border:0;'
        'border-radius:0;background:transparent;font-family:inherit;font-size:16px;font-weight:600;color:var(--green);text-align:start;cursor:pointer}.wc-row:hover{'
        'background:rgba(209,244,112,.38)}.wc-row.is-on{background:var(--lime)}.wc-row-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wc-row-code{'
        'flex:0 0 auto;font-size:12px;font-weight:700;letter-spacing:.05em;color:rgba(0,0,0,.34)}.wc-more{margin:0;padding:11px 14px;font-size:14px;font-weight:500;'
        'color:rgba(0,0,0,.45);background:#fcfdfa;border-top:1px solid #f1f3ec}.wc-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;'
        'clip:rect(0,0,0,0);white-space:nowrap;border:0}:root[dir="rtl"] .wc-langbar{right:auto;left:max(var(--wc-inset),env(safe-area-inset-left))}'        '@media(max-width:279px){.home-head-line{white-space:normal}}'
    )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="robots" content="noindex,nofollow,noarchive">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
        '<title>WECARE.DIGITAL · Sign in</title><style>' + styles + '</style></head><body>' +
        header +
        '<main class="home-shell"><div class="home-layout">'
        '<div class="home-hero"><h1 class="home-head">'
        '<span class="home-head-line">One&nbsp;account, built&nbsp;for</span>' +
        hero_pill +
        '</h1><p class="home-sub">Sign in with WhatsApp and continue securely wherever you started.</p></div>' +
        sign_in +
        '</div></main>'
        '<div class="public-action-tail">' + stay_connected + '</div>' +
        footer + support_widget + '<script nonce="' + html.escape(nonce, quote=True) + '">' + rotation_script + country_script + support_script + '</script></body></html>'
    )
    result = response(200, page, page=True)
    form_sources = "'self'"
    if not website:
        callback = urlparse(row['redirect'])
        form_sources += f" {callback.scheme}://{callback.netloc}"
    result['headers']['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'nonce-" + nonce + "'; "
        "style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self'; connect-src 'self'; "
        "form-action " + form_sources + "; frame-ancestors 'none'; base-uri 'none'"
    )
    return result

def save_pending(row: dict, login: dict, message: str = '') -> dict:
    csrf = secrets.token_urlsafe(32)
    row['csrfHash'] = digest(csrf)
    row['cipher'] = capsule(login, row['client'], row['sidHash'])
    STORE.put(row)
    return form(row, csrf, message)


def website_get(params: dict) -> dict:
    if set(params) - {'return'}:
        raise AuthError('Invalid website sign-in request')
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'web-auth', 'client': WEBSITE_CLIENT,
           'return': website_return(params.get('return', '')), 'absoluteExpiresAt': int(time.time()) + 600}
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result


def website_finish(row: dict, login: dict, auth: dict, event: dict) -> dict:
    """Create the established website session, then hydrate the browser without exposing refresh custody."""
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
    destination = website_return(row.get('return', ''))
    nonce = secrets.token_urlsafe(24)
    script = (
        "const hint={csrfToken:" + json.dumps(csrf) + ",expiresAt:" + str(int(expires_at)) + ",persistent:true};"
        "localStorage.setItem('wecare.customer.sessionHint',JSON.stringify(hint));"
        "fetch('/api/ecommerce/customer-session',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Customer-CSRF':hint.csrfToken},body:JSON.stringify({action:'refresh'})})"
        ".then(r=>{if(!r.ok)throw new Error('refresh');return r.json()})"
        ".then(async s=>{sessionStorage.setItem('wecare.customer.accessToken',s.accessToken);sessionStorage.setItem('wecare.customer.expiresAt',String(s.expiresAt));"
        "try{await fetch('/api/customer/profile',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+s.accessToken},body:'{}'})}catch(e){}"
        "location.replace(" + json.dumps(destination) + ")})"
        ".catch(()=>{document.getElementById('status').textContent='Signed in. Reopen the page to continue.'})"
    )
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<meta name="robots" content="noindex,nofollow,noarchive"><title>WECARE.DIGITAL · Signing in</title></head>'
            '<body><main id="status" style="max-width:520px;margin:15vh auto;padding:24px;font:16px/1.5 system-ui;color:#1a3a2a">Finishing sign-in…</main>'
            '<script nonce="' + html.escape(nonce, quote=True) + '">' + script + '</script></body></html>')
    result = response(200, page, page=True)
    result['cookies'] = list(reply.get('cookies') or []) + [f'{COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0']
    result['headers']['Content-Security-Policy'] = ("default-src 'none'; script-src 'nonce-" + nonce +
        "'; connect-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
    return result


def authorize_get(params: dict) -> dict:
    params = validate_authorize(params)
    cookie = secrets.token_urlsafe(32)
    key = row_key('auth', cookie)
    row = {'sidHash': key, 'kind': 'oauth-auth', 'client': params['client_id'], 'resource': resource(),
           'redirect': params['redirect_uri'], 'state': params['state'], 'scope': params['scope'],
           'challenge': params['code_challenge'], 'absoluteExpiresAt': int(time.time()) + 600}
    result = save_pending(row, {'phase': 'phone'})
    result['cookies'] = [f'{COOKIE}={cookie}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600']
    return result


def authorize_post(params: dict, event: dict) -> dict:
    headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
    if headers.get('origin') not in {origin(), connect_origin()}:
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
    website = row.get('kind') == 'web-auth'
    if STORE.take(key) is None:
        raise AuthError('Authorization step already used')
    # Which step failed, for the failure log line below. A step name and an exception class
    # only: never a number, code, session or provider message.
    stage = 'phone' if login.get('phase') == 'phone' else 'challenge'
    try:
        if params.get('action'):
            if (params.get('action') != 'resend' or set(params) != {'csrf', 'action'}
                    or login.get('phase') not in {'code', 'registration'}):
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
        return save_pending(row, login, 'Couldn’t verify. Try again.')


def route(event: dict) -> dict | None:
    path = str(event.get('rawPath') or '')
    # `/auth` is the main-site sign-in path (wecare.digital/auth, through the Amplify Hosting
    # rewrite); `/oauth/authorize` stays for hosts that cached the earlier discovery document.
    if path not in {'/.well-known/oauth-authorization-server', '/auth', '/oauth/authorize', '/oauth/token', '/oauth/revoke'}:
        return None
    method = str(((event.get('requestContext') or {}).get('http') or {}).get('method') or '').upper()
    try:
        if path == '/.well-known/oauth-authorization-server' and method == 'GET':
            return response(200, auth_metadata())
        if path in {'/auth', '/oauth/authorize'} and method == 'GET':
            params = parse(event.get('rawQueryString', ''))
            if path == '/auth' and not {'client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'resource', 'code_challenge', 'code_challenge_method'}.intersection(params):
                return website_get(params)
            target = connect_origin()
            # Hosts cache discovery. Redirect an initial GET on the legacy path before creating
            # a session, so cookies and the subsequent POST stay on the main-site `/auth` page.
            if target != origin() and path == '/oauth/authorize':
                validate_authorize(params)
                result = response(302, '')
                result['headers']['Location'] = target + '/auth?' + urlencode(params)
                return result
            return authorize_get(params)
        if method != 'POST':
            return response(405, {'error': 'invalid_request'})
        headers = {str(k).lower(): str(v) for k, v in (event.get('headers') or {}).items()}
        if headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            raise AuthError('Unsupported content type')
        raw = event.get('body') or ''
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode()
        params = parse(raw)
        if path in {'/auth', '/oauth/authorize'}:
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
