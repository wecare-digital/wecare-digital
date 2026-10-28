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
    def test_cached_host_authorization_link_redirects_only_to_configured_brand_origin(self):
        # Since v12 the sign-in page is wecare.digital/auth (Amplify rewrite to this API). A host
        # that cached the old discovery document still opens /oauth/authorize: that GET redirects
        # to the main-site /auth page before any session exists, and /auth itself never redirects.
        with patch.dict(os.environ, {'CUSTOMER_AUTH_ORIGIN': 'https://wecare.digital'}):
            event = {'rawPath': '/oauth/authorize', 'rawQueryString': urlencode(self.params),
                     'requestContext': {'domainName': 'commerce.example.com', 'http': {'method': 'GET'}}}
            result = auth.route(event)
            self.assertEqual(result['statusCode'], 302)
            self.assertEqual(result['headers']['Location'], 'https://wecare.digital/auth?' + urlencode(self.params))
            self.assertEqual(self.store.rows, {})
            event['rawPath'] = '/auth'
            self.assertEqual(auth.route(event)['statusCode'], 200)
        with patch.dict(os.environ, {'CUSTOMER_AUTH_ORIGIN': 'https://connect.wecare.digital'}):
            with self.assertRaises(auth.AuthError):
                auth.connect_origin()

    def test_plain_auth_is_the_canonical_website_sign_in(self):
        with patch.dict(os.environ, {'CUSTOMER_AUTH_ORIGIN': 'https://wecare.digital'}):
            event = {'rawPath': '/auth', 'rawQueryString': 'return=%2Forders%2F',
                     'requestContext': {'domainName': 'wecare.digital', 'http': {'method': 'GET'}}}
            result = auth.route(event)
        self.assertEqual(result['statusCode'], 200)
        self.assertIn('class="hdr"', result['body'])
        self.assertIn('class="nav-menu"', result['body'])
        self.assertIn('class="home-shell"', result['body'])
        self.assertIn('One&nbsp;account. Anywhere&nbsp;you need&nbsp;it.', result['body'])
        self.assertIn('Sign in once with WhatsApp.<br>Continue across WECARE.DIGITAL and connected apps.', result['body'])
        self.assertIn('WECARE.DIGITAL, WhatsApp, Android, iOS, ChatGPT, Claude, Gemini', result['body'])
        self.assertNotIn('One&nbsp;account, built&nbsp;for', result['body'])
        self.assertIn('class="home-connect"', result['body'])
        self.assertIn('class="connect-panel"', result['body'])
        self.assertIn('class="connect-eyebrow"', result['body'])
        self.assertIn('>Access</span>', result['body'])
        self.assertIn('class="country-trigger"', result['body'])
        self.assertIn('>+91</button>', result['body'])
        self.assertIn('class="country-panel"', result['body'])
        self.assertNotIn('<select id="country"', result['body'])
        self.assertIn('>Get Code</button>', result['body'])
        # The "Verification code" note beside Get Code is gone; the button stands on its own.
        self.assertNotIn('class="auth-action-note"', result['body'])
        self.assertIn('id="wc-auth-widget"', result['body'])
        self.assertIn('id="wc-lang-panel"', result['body'])
        self.assertIn("connect-src 'self'", result['headers']['Content-Security-Policy'])
        self.assertIn('width:min(100%,420px)', result['body'])
        self.assertNotIn('Sign in to WECARE.DIGITAL.', result['body'])
        self.assertNotIn('Use your WhatsApp number to continue with your WECARE account.', result['body'])
        self.assertNotIn('Enter your number without the country code or a leading zero.', result['body'])
        self.assertNotIn('Sign in to your WECARE account. Verification messages arrive on WhatsApp.', result['body'])
        self.assertNotIn('class="connect-rule"', result['body'])
        self.assertNotIn('class="sign-card"', result['body'])
        self.assertIn('class="public-share has-contribute"', result['body'])
        self.assertIn('Contribute ₹250', result['body'])
        self.assertIn('Subscribe on WhatsApp', result['body'])
        self.assertIn('Share this page', result['body'])
        self.assertIn('class="ft-footer"', result['body'])
        self.assertIn('>Extras</span>', result['body'])
        self.assertIn('>With AI</span>', result['body'])
        self.assertNotIn('Visit our website', result['body'])
        self.assertNotIn('class="auth-hero"', result['body'])
        self.assertNotIn('class="site-footer"', result['body'])
        self.assertNotIn('Connecting to <strong>', result['body'])
        cookie = SimpleCookie(); cookie.load(result['cookies'][0])
        row = self.store.get(auth.row_key('auth', cookie[auth.COOKIE].value))
        self.assertEqual(row['kind'], 'web-auth')
        self.assertEqual(row['return'], '/orders/')

    def test_code_phase_renders_and_accepts_resend_action(self):
        cookie, csrf = self.begin()
        first = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        self.assertEqual(first['statusCode'], 200)
        self.assertIn('>Resend code</button>', first['body'])
        csrf = re.search(r'name="csrf" value="([^"]+)"', first['body']).group(1)
        second = self.post(cookie, {'csrf': csrf, 'action': 'resend'})
        self.assertEqual(second['statusCode'], 200)
        self.assertIn('>Resend code</button>', second['body'])
        self.assertIn('class="single-field"', second['body'])
        self.assertEqual(self.cognito.sends, 2)

    def test_plain_auth_rejects_unknown_parameters_and_external_returns(self):
        with patch.dict(os.environ, {'CUSTOMER_AUTH_ORIGIN': 'https://wecare.digital'}):
            bad = {'rawPath': '/auth', 'rawQueryString': 'unexpected=1',
                   'requestContext': {'domainName': 'wecare.digital', 'http': {'method': 'GET'}}}
            self.assertEqual(auth.route(bad)['statusCode'], 400)
            event = {'rawPath': '/auth', 'rawQueryString': 'return=https%3A%2F%2Fevil.example',
                     'requestContext': {'domainName': 'wecare.digital', 'http': {'method': 'GET'}}}
            result = auth.route(event)
        cookie = SimpleCookie(); cookie.load(result['cookies'][0])
        row = self.store.get(auth.row_key('auth', cookie[auth.COOKIE].value))
        self.assertEqual(row['return'], '/cart/')

    def test_country_selection_normalizes_before_cognito(self):
        cookie, csrf = self.begin()
        with patch.object(self.cognito, 'initiate_auth', wraps=self.cognito.initiate_auth) as call:
            result = self.post(cookie, {'csrf': csrf, 'country': '+91', 'phone': '9876543210'})
        self.assertIn('for="code">Code</label>', result['body'])
        self.assertEqual(call.call_args.kwargs['AuthParameters']['USERNAME'], '+919876543210')

    def test_invalid_country_or_national_length_never_sends(self):
        for country, number in [('+999', '9876543210'), ('+91', '12345'), ('+91', '+919876543210')]:
            cookie, csrf = self.begin()
            result = self.post(cookie, {'csrf': csrf, 'country': country, 'phone': number})
            self.assertIn('Check the number and try again.', result['body'])
        self.assertEqual(self.cognito.sends, 0)

    def test_branded_authorization_origin_keeps_resource_binding(self):
        with patch.dict(os.environ, {'CUSTOMER_AUTH_ORIGIN': 'https://wecare.digital'}):
            self.assertEqual(auth.auth_metadata()['authorization_endpoint'], 'https://wecare.digital/auth')
            self.assertEqual(auth.auth_metadata()['issuer'], BASE)
            cookie, csrf = self.begin()
            result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'}, 'https://wecare.digital')
            self.assertIn('for="code">Code</label>', result['body'])
        # Without a main-site origin the API host keeps its own authorization endpoint.
        self.assertEqual(auth.auth_metadata()['authorization_endpoint'], BASE + '/oauth/authorize')

    def test_host_language_hint_does_not_change_authorization(self):
        params = {**self.params, 'ui_locales': 'en-US'}
        self.assertEqual(auth.validate_authorize(params), self.params)
        with self.assertRaises(auth.AuthError):
            auth.validate_authorize({**self.params, 'untrusted_option': 'ignored'})

    def test_connection_page_preserves_browser_origin_without_referrer_path(self):
        # Chromium sends Origin: null on navigation POSTs under no-referrer.
        # The connection form must retain its origin for the existing CSRF check.
        self.assertEqual(auth.response(200, '', page=True)['headers']['Referrer-Policy'], 'strict-origin')
        self.assertEqual(auth.response(200, {})['headers']['Referrer-Policy'], 'no-referrer')

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
            self.assertIn('>Verify</button>', result['body'])
            self.assertIn('>Resend code</button>', result['body'])
            self.assertNotIn('create your account', result['body'])
            csrf = re.search(r'name="csrf" value="([^"]+)"', result['body']).group(1)
            result = self.post(cookie, {'csrf': csrf, 'code': '123456'})
            self.assertEqual(result['statusCode'], 200)
            self.assertIn('Account ready. Enter the new code.', result['body'])
            self.assertEqual(delegate.call_args.args[0], 'verify')
            self.assertEqual(self.cognito.sends, 2)

    def test_customer_failure_copy_stays_short(self):
        cookie, csrf = self.begin()
        with patch.object(self.cognito, 'initiate_auth', side_effect=RuntimeError('provider unavailable')):
            result = self.post(cookie, {'csrf': csrf, 'phone': '+447700900123'})
        self.assertNotIn('Couldn’t verify. Try again.', result['body'])
        self.assertNotIn('We could not complete verification. Please try again shortly.', result['body'])

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
