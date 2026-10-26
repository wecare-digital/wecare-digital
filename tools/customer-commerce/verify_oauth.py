"""Synthetic end-to-end OAuth checks; never connects to AWS or sends a message."""
from __future__ import annotations
import base64
import copy
import hashlib
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'amplify/functions/ai/customer-commerce-mcp'))
import customer_oauth as auth

BASE = 'https://commerce.example.com'
REDIRECT = 'https://client.example/callback'
VERIFIER = 'a' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')
SUBJECT = '11111111-1111-4111-8111-111111111111'


def jwt(issuer=None, client=None):
    claims = {'iss': issuer or f'https://cognito-idp.us-east-1.amazonaws.com/{auth.CUSTOMER_POOL}',
              'client_id': client or auth.CUSTOMER_CLIENT, 'sub': SUBJECT, 'token_use': 'access'}
    return 'synthetic.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.signature'


class FakeStore:
    def __init__(self): self.rows = {}
    def put(self, row):
        if row['sidHash'] in self.rows: raise ValueError('Duplicate session')
        self.rows[row['sidHash']] = copy.deepcopy(row)
    def get(self, key):
        row = self.rows.get(key)
        return copy.deepcopy(row) if row and row['absoluteExpiresAt'] > int(time.time()) else None
    def take(self, key):
        value = self.get(key)
        if value: del self.rows[key]
        return value


class FakeCognito:
    def __init__(self):
        self.registered = True
        self.revoked = False
        self.sends = 0
        self.refreshes = 0
        self.access = jwt()
    def initiate_auth(self, **kwargs):
        if kwargs['AuthFlow'] == 'REFRESH_TOKEN_AUTH':
            self.refreshes += 1
            return {'AuthenticationResult': {'AccessToken': self.access, 'ExpiresIn': 3600}}
        self.sends += 1
        return {'Session': 'synthetic-challenge', 'ChallengeParameters': {'registered': str(self.registered).lower()}}
    def respond_to_auth_challenge(self, **kwargs):
        if kwargs['ChallengeResponses']['ANSWER'] != '123456': return {'Session': 'rotated-synthetic-challenge'}
        return {'AuthenticationResult': {'AccessToken': self.access, 'RefreshToken': 'synthetic-refresh', 'ExpiresIn': 3600}}
    def get_user(self, **kwargs):
        if self.revoked: raise auth.AuthError('Revoked')
        return {'UserAttributes': [{'Name': 'sub', 'Value': SUBJECT}]}


class OAuthContract(unittest.TestCase):
    def setUp(self):
        self.store, self.cognito = FakeStore(), FakeCognito()
        env = patch.dict(os.environ, {'CUSTOMER_COMMERCE_ORIGIN': BASE,
            'CUSTOMER_OAUTH_CLIENTS': json.dumps([{'client_id': 'test-client', 'name': 'Test client', 'redirect_uris': [REDIRECT]}]),
            'CUSTOMER_REGISTRATION_ENABLED': 'false'})
        env.start(); self.addCleanup(env.stop)
        for name, value in [('STORE', self.store), ('capsule', lambda data, c, k: json.dumps(data)),
                            ('uncapsule', lambda data, c, k: json.loads(data)), ('aws', lambda service: self.cognito)]:
            p = patch.object(auth, name, value); p.start(); self.addCleanup(p.stop)
        self.params = {'client_id': 'test-client', 'redirect_uri': REDIRECT, 'response_type': 'code',
                       'scope': 'commerce:read commerce:write', 'state': 'synthetic-state-123456789',
                       'resource': BASE + '/mcp', 'code_challenge': CHALLENGE, 'code_challenge_method': 'S256'}

    def begin(self):
        result = auth.authorize_get(self.params)
        cookie = SimpleCookie(); cookie.load(result['cookies'][0])
        cookie_value = cookie[auth.COOKIE].value
        csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
        return cookie_value, csrf

    def post(self, cookie, fields, origin=BASE):
        return auth.authorize_post(fields, {'headers': {'origin': origin}, 'cookies': [f'{auth.COOKIE}={cookie}'],
                                           'requestContext': {'http': {'sourceIp': '127.0.0.1'}}})

    def connect(self):
        cookie, csrf = self.begin()
        result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
        result = self.post(cookie, {'csrf': csrf, 'code': '123456'})
        self.assertEqual(result['statusCode'], 302)
        parsed = parse_qs(urlparse(result['headers']['Location']).query)
        self.assertEqual(parsed['state'], [self.params['state']])
        return {'grant_type': 'authorization_code', 'client_id': 'test-client', 'resource': BASE + '/mcp',
                'code': parsed['code'][0], 'redirect_uri': REDIRECT, 'code_verifier': VERIFIER}

    def session(self): return auth.token_exchange(self.connect())

    def customer(self, token, scope='commerce:read'):
        return auth.customer_event({'headers': {'authorization': 'Bearer ' + token}}, scope)

    def test_registered_customer_connects_with_opaque_tokens(self):
        result = self.session()
        self.assertTrue(result['access_token'].startswith('wca_'))
        self.assertTrue(result['refresh_token'].startswith('wcr_'))
        self.assertNotIn('synthetic-refresh', json.dumps(result))
        self.assertEqual(self.customer(result['access_token'])['headers']['authorization'], 'Bearer ' + jwt())

    def test_authorization_requires_registered_exact_redirect(self):
        for change in [{'redirect_uri': REDIRECT + '/other'}, {'client_id': 'unknown'},
                       {'resource': BASE + '/staff'}, {'code_challenge_method': 'plain'}, {'scope': 'admin'}]:
            with self.assertRaises(auth.AuthError): auth.authorize_get({**self.params, **change})

    def test_duplicate_parameters_refused(self):
        with self.assertRaises(auth.AuthError): auth.parse('client_id=a&client_id=b')

    def test_connection_form_allows_only_its_registered_callback_origin(self):
        page = auth.authorize_get(self.params)
        policy = page['headers']['Content-Security-Policy']
        self.assertIn("form-action 'self' https://client.example;", policy)
        self.assertNotIn('*', policy)

    def test_csrf_required_before_any_message(self):
        cookie, _ = self.begin()
        with self.assertRaises(auth.AuthError): self.post(cookie, {'csrf': 'wrong', 'phone': '+447700900123'})
        self.assertEqual(self.cognito.sends, 0)

    def test_cross_origin_form_refused(self):
        cookie, csrf = self.begin()
        with self.assertRaises(auth.AuthError): self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'}, 'https://untrusted.example')
        self.assertEqual(self.cognito.sends, 0)

    def test_code_is_not_reflected_in_page(self):
        cookie, csrf = self.begin()
        result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        self.assertNotIn('+447700900123', result['body'])
        csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
        result = self.post(cookie, {'csrf': csrf, 'code': '000000'})
        self.assertNotIn('000000', result['body'])
        self.assertNotIn('rotated-synthetic-challenge', result['body'])

    def test_wrong_code_preserves_rotated_session_privately(self):
        cookie, csrf = self.begin()
        result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
        self.post(cookie, {'csrf': csrf, 'code': '000000'})
        row = self.store.get(auth.row_key('auth', cookie))
        self.assertEqual(json.loads(row['cipher'])['session'], 'rotated-synthetic-challenge')
        with self.assertRaises(auth.AuthError): self.post(cookie, {'csrf': csrf, 'code': '123456'})

    def test_wrong_pkce_does_not_consume_correct_code(self):
        exchange = self.connect()
        with self.assertRaises(auth.AuthError): auth.token_exchange({**exchange, 'code_verifier': 'b' * 64})
        self.assertIn('access_token', auth.token_exchange(exchange))

    def test_authorization_code_cannot_be_replayed(self):
        exchange = self.connect(); auth.token_exchange(exchange)
        with self.assertRaises(auth.AuthError): auth.token_exchange(exchange)

    def test_wrong_resource_and_redirect_refused_at_exchange(self):
        exchange = self.connect()
        for changed in [{'resource': BASE + '/other'}, {'redirect_uri': REDIRECT + '/other'}]:
            with self.assertRaises(auth.AuthError): auth.token_exchange({**exchange, **changed})

    def test_opaque_tokens_bound_to_resource(self):
        result = self.session()
        with patch.dict(os.environ, {'CUSTOMER_COMMERCE_ORIGIN': 'https://other.example.com'}):
            with self.assertRaises(auth.AuthError): self.customer(result['access_token'])

    def test_scope_enforced(self):
        self.params['scope'] = 'commerce:read'
        result = self.session()
        with self.assertRaises(auth.AuthError): self.customer(result['access_token'], 'commerce:write')

    def test_cognito_token_cannot_bypass_resource_binding(self):
        with self.assertRaises(auth.AuthError): self.customer(jwt())

    def test_staff_pool_or_other_client_refused(self):
        for value in [jwt(issuer='https://staff.example'), jwt(client='another-client')]:
            self.cognito.access = value
            cookie, csrf = self.begin()
            page = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
            csrf = re.search(r'name="csrf" value="([^"]+)"', page['body']).group(1)
            page = self.post(cookie, {'csrf': csrf, 'code': '123456'})
            self.assertEqual(page['statusCode'], 200)
            self.assertNotIn('Location', page['headers'])
            self.assertFalse(any(row['kind'] == 'grant' for row in self.store.rows.values()))

    def test_revoked_cognito_access_fails_closed(self):
        result = self.session(); self.cognito.revoked = True
        with self.assertRaises(auth.AuthError): self.customer(result['access_token'])

    def test_refresh_rotation_and_replay(self):
        result = self.session()
        request = {'grant_type': 'refresh_token', 'client_id': 'test-client', 'resource': BASE + '/mcp',
                   'refresh_token': result['refresh_token']}
        fresh = auth.token_exchange(request)
        self.assertNotEqual(fresh['refresh_token'], result['refresh_token'])
        self.assertEqual(self.cognito.refreshes, 1)
        with self.assertRaises(auth.AuthError): auth.token_exchange(request)
        self.assertEqual(self.customer(fresh['access_token'])['headers']['authorization'], 'Bearer ' + jwt())

    def test_revocation_ends_whole_grant(self):
        result = self.session()
        request = {'rawPath': '/oauth/revoke', 'requestContext': {'http': {'method': 'POST'}},
                   'headers': {'content-type': 'application/x-www-form-urlencoded'},
                   'body': urlencode({'client_id': 'test-client', 'resource': BASE + '/mcp', 'token': result['refresh_token']})}
        self.assertEqual(auth.route(request)['statusCode'], 200)
        with self.assertRaises(auth.AuthError): self.customer(result['access_token'])

    def test_metadata_has_pkce_and_no_dynamic_registration(self):
        data = auth.auth_metadata()
        self.assertEqual(data['code_challenge_methods_supported'], ['S256'])
        self.assertEqual(data['token_endpoint_auth_methods_supported'], ['none'])
        self.assertNotIn('registration_endpoint', data)

    def test_registration_reuses_existing_service_and_requires_second_code(self):
        self.cognito.registered = False
        cookie, csrf = self.begin()
        def registration(action, phone, event, code=''):
            if action == 'verify': self.cognito.registered = True
            return True
        with patch.object(auth, 'registration_call', side_effect=registration) as delegate:
            result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
            self.assertIn('create your account', result['body'])
            csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
            result = self.post(cookie, {'csrf': csrf, 'code': '123456'})
            self.assertEqual(result['statusCode'], 200)
            self.assertIn('new WhatsApp code', result['body'])
            self.assertEqual(delegate.call_args.args[0], 'verify')
            self.assertEqual(self.cognito.sends, 2)

    def test_disabled_registration_does_not_claim_account_created(self):
        self.cognito.registered = False
        cookie, csrf = self.begin()
        result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        self.assertNotIn('Your account is created', result['body'])

    def test_expired_access_refused(self):
        result = self.session()
        self.store.rows[auth.row_key('access', result['access_token'])]['absoluteExpiresAt'] = 1
        with self.assertRaises(auth.AuthError): self.customer(result['access_token'])


if __name__ == '__main__': unittest.main(verbosity=2)
