"""Customer OAuth configuration, validation and protocol response helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse

from connection_assets import DIAL_COUNTRIES

PREFIX = 'mcp:commerce:'
COOKIE = '__Host-wecare-connect'
SESSION_HINT_COOKIE = 'wc_customer_session_hint'
WEBSITE_SESSION_COOKIE = 'wd_csid'
CUSTOMER_POOL = 'us-east-1_46ULYuukt'
CUSTOMER_CLIENT = '4avmt9n4gpmkvkdk88qbtit33o'
SCOPES = {'commerce:read', 'commerce:write'}
WEBSITE_CLIENT = 'wecare-website'
WEBSITE_ORIGIN = 'https://wecare.digital'
WEBSITE_RETURNS = {
    '/',
    '/checkout/',
    '/orders/',
    '/blog/',
    '/submit-request/',
    '/request-amendment/',
    '/drop-docs/',
    '/vault/',
    '/request-pickup/',
}
_CLIENTS: dict[str, object] = {}


class AuthError(ValueError):
    pass


def origin() -> str:
    value = os.environ.get('CUSTOMER_COMMERCE_ORIGIN', '').rstrip('/')
    parsed = urlparse(value)
    if (
        parsed.scheme != 'https'
        or not re.fullmatch(
            '[A-Za-z0-9.-]+(?::[0-9]{1,5})?', parsed.netloc
        )
        or parsed.username
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise AuthError('Server origin unavailable')
    return value


def resource() -> str:
    return origin() + '/mcp'


def connect_origin() -> str:
    value = os.environ.get(
        'CUSTOMER_AUTH_ORIGIN', WEBSITE_ORIGIN
    ).rstrip('/')
    if value != WEBSITE_ORIGIN:
        raise AuthError('Connection origin unavailable')
    return value


def normalized_phone(params: dict) -> str:
    if set(params) == {'csrf', 'phone'}:
        number = params['phone']
    elif set(params) == {'csrf', 'country', 'phone'}:
        country, national = params['country'], params['phone']
        lengths = next(
            (
                allowed
                for code, _, allowed in DIAL_COUNTRIES
                if code == country
            ),
            None,
        )
        if (
            lengths is None
            or not re.fullmatch('[0-9]+', national)
            or (lengths and len(national) not in lengths)
        ):
            raise AuthError('Invalid national number')
        number = country + national
    else:
        raise AuthError('Invalid phone fields')
    if not re.fullmatch('\\+[1-9][0-9]{7,14}', number):
        raise AuthError('Invalid international number')
    return number


def website_return(value: str) -> str:
    if not value:
        return '/'
    # /get was the old customer file entry. Keep old auth URLs working, but collapse them to
    # the canonical Vault destination so there is only one customer download route.
    if value in {'/get', '/get/'}:
        return '/vault/'
    normalized = value if value.endswith('/') else value + '/'
    if (
        normalized not in WEBSITE_RETURNS
        or any(char in value for char in ('%', '?', '#', '\\'))
        or value.startswith('//')
    ):
        return '/checkout/'
    return normalized


def digest(opaque_token: str) -> str:
    """Return a lookup key for a high-entropy opaque token.

    The inputs are CSPRNG-generated session, authorization, access, refresh, or
    CSRF tokens. They are not passwords and do not come from a limited human
    input space, so a fast SHA-256 one-way lookup is the intended construction.
    Existing records also depend on this stable digest format.
    """
    return hashlib.sha256(  # lgtm[py/weak-sensitive-data-hashing]
        opaque_token.encode()
    ).hexdigest()


def row_key(kind: str, token: str) -> str:
    return PREFIX + kind + ':' + digest(token)


def clients() -> dict:
    values = json.loads(os.environ.get('CUSTOMER_OAUTH_CLIENTS', '[]'))
    if not isinstance(values, list) or len(values) > 20:
        raise AuthError('Invalid client configuration')
    result = {}
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) - {'client_id', 'name', 'redirect_uris'}
        ):
            raise AuthError('Invalid client configuration')
        client_id = value.get('client_id')
        redirects = value.get('redirect_uris')
        if (
            not isinstance(client_id, str)
            or not re.fullmatch('[A-Za-z0-9_-]{3,100}', client_id)
            or client_id in result
        ):
            raise AuthError('Invalid client configuration')
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 10:
            raise AuthError('Invalid redirects')
        for uri in redirects:
            if not isinstance(uri, str):
                raise AuthError('Invalid redirect')
            parsed = urlparse(uri)
            if (
                parsed.scheme != 'https'
                or not re.fullmatch(
                    '[A-Za-z0-9.-]+(?::[0-9]{1,5})?', parsed.netloc
                )
                or parsed.username
                or parsed.fragment
                or len(uri) > 1024
            ):
                raise AuthError('Invalid redirect')
        result[client_id] = {
            'name': str(value.get('name') or client_id)[:100],
            'redirect_uris': redirects,
        }
    return result


def client(name: str) -> dict:
    value = clients().get(name)
    if value is None:
        raise AuthError('Unknown client')
    return value


def response(status: int, data, *, page: bool = False) -> dict:
    return {
        'statusCode': status,
        'headers': {
            'Content-Type': (
                'text/html; charset=utf-8'
                if page
                else 'application/json'
            ),
            'Cache-Control': 'no-store',
            'Pragma': 'no-cache',
            'Referrer-Policy': 'strict-origin' if page else 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-Robots-Tag': 'noindex, nofollow, noarchive',
            'Content-Security-Policy': (
                "default-src 'none'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'"
            ),
        },
        'body': data if page or isinstance(data, str) else json.dumps(data),
    }


def redirect(location: str, status: int = 302) -> dict:
    result = response(status, '')
    result['headers']['Location'] = location
    return result


def parse(value: str) -> dict:
    if not isinstance(value, str) or len(value.encode()) > 8192:
        raise AuthError('Invalid request')
    # API Gateway represents a request with no query parameters as the empty
    # string. Python 3.10 rejects that value under strict parsing, while newer
    # versions accept it as an empty query.
    if value == '':
        return {}
    pairs = parse_qsl(
        value, keep_blank_values=True, strict_parsing=True
    )
    if len(pairs) != len({key for key, _ in pairs}) or len(pairs) > 20:
        raise AuthError('Ambiguous request')
    return dict(pairs)


def validate_authorize(params: dict) -> dict:
    params = {
        key: value
        for key, value in params.items()
        if key != 'ui_locales'
    }
    required = {
        'client_id',
        'redirect_uri',
        'response_type',
        'scope',
        'state',
        'resource',
        'code_challenge',
        'code_challenge_method',
    }
    if (
        set(params) != required
        or params['response_type'] != 'code'
        or params['code_challenge_method'] != 'S256'
    ):
        raise AuthError('Invalid authorization request')
    registered = client(params['client_id'])
    if (
        params['redirect_uri'] not in registered['redirect_uris']
        or params['resource'] != resource()
    ):
        raise AuthError('Invalid resource or redirect')
    scopes = params['scope'].split()
    if (
        not scopes
        or len(set(scopes)) != len(scopes)
        or set(scopes) - SCOPES
    ):
        raise AuthError('Invalid scope')
    if (
        not 1 <= len(params['state']) <= 512
        or not re.fullmatch(
            '[A-Za-z0-9_-]{43}', params['code_challenge']
        )
    ):
        raise AuthError('Invalid state or challenge')
    return params


def auth_metadata() -> dict:
    base = origin()
    return {
        'issuer': base,
        'authorization_endpoint': connect_origin() + '/auth',
        'token_endpoint': base + '/oauth/token',
        'revocation_endpoint': base + '/oauth/revoke',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'],
        'code_challenge_methods_supported': ['S256'],
        'scopes_supported': sorted(SCOPES),
    }
