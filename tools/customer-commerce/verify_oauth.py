"""Focused synthetic checks for the JSON-only customer OAuth boundary."""
from __future__ import annotations

import base64
import copy
import hashlib
from http.cookies import SimpleCookie
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'amplify/functions/ai/customer-commerce-mcp'
sys.path.insert(0, str(SOURCE))
import customer_oauth as auth
import customer_oauth_config as auth_config
import customer_oauth_store as auth_store
import customer_oauth_web as auth_web
import customer_oauth_authorize as auth_authorize

BASE = 'https://commerce.example.com'
REDIRECT = 'https://client.example/callback'
VERIFIER = 'a' * 64
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).decode().rstrip('=')
SUBJECT = '11111111-1111-4111-8111-111111111111'


def jwt() -> str:
    claims = {
        'iss': (
            'https://cognito-idp.us-east-1.amazonaws.com/'
            + auth.CUSTOMER_POOL
        ),
        'client_id': auth.CUSTOMER_CLIENT,
        'sub': SUBJECT,
        'token_use': 'access',
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).decode().rstrip('=')
    return 'synthetic.' + payload + '.signature'


class FakeStore:
    def __init__(self):
        self.rows = {}

    def put(self, row):
        if row['sidHash'] in self.rows:
            raise ValueError('Duplicate session')
        self.rows[row['sidHash']] = copy.deepcopy(row)

    def get(self, key):
        row = self.rows.get(key)
        if row and row['absoluteExpiresAt'] > int(time.time()):
            return copy.deepcopy(row)
        return None

    def take(self, key):
        value = self.get(key)
        if value:
            del self.rows[key]
        return value


class FakeCognito:
    def __init__(self):
        self.registered = True
        self.sends = 0
        self.access = jwt()

    def initiate_auth(self, **kwargs):
        if kwargs['AuthFlow'] == 'REFRESH_TOKEN_AUTH':
            return {
                'AuthenticationResult': {
                    'AccessToken': self.access,
                    'ExpiresIn': 3600,
                }
            }
        self.sends += 1
        return {
            'Session': f'synthetic-challenge-{self.sends}',
            'ChallengeParameters': {
                'registered': str(self.registered).lower()
            },
        }

    def respond_to_auth_challenge(self, **kwargs):
        if kwargs['ChallengeResponses']['ANSWER'] != '123456':
            return {'Session': 'rotated-challenge'}
        return {
            'AuthenticationResult': {
                'AccessToken': self.access,
                'RefreshToken': 'synthetic-refresh',
                'ExpiresIn': 3600,
            }
        }

    def get_user(self, **kwargs):
        return {
            'UserAttributes': [{'Name': 'sub', 'Value': SUBJECT}]
        }


class FakeLambda:
    def __init__(self):
        self.calls = []
        self.session_cookies = [
            (
                f'{auth.WEBSITE_SESSION_COOKIE}='
                'synthetic_customer_session_1234567890; '
                'Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=3600'
            )
        ]

    def invoke(self, **kwargs):
        self.calls.append(kwargs['FunctionName'])
        if kwargs['FunctionName'] == 'wecare-customer-session:live':
            body = {
                'csrfToken': 'website-csrf',
                'expiresAt': int(time.time()) + 3600,
            }
            payload = {
                'statusCode': 200,
                'body': json.dumps(body),
                'cookies': list(self.session_cookies),
            }
        else:
            payload = {'statusCode': 200, 'body': '{}'}
        return {'Payload': io.BytesIO(json.dumps(payload).encode())}


class OAuthContract(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.cognito = FakeCognito()
        self.lambda_client = FakeLambda()
        for module in (auth, auth_store, auth_web, auth_authorize):
            module.STORE = self.store
            module.capsule = (
                lambda value, client_id, key, token_resource=None: json.dumps(value)
            )
            module.uncapsule = (
                lambda value, client_id, key, token_resource=None: json.loads(value)
            )
        auth_config._CLIENTS.clear()
        self.aws_patches = [
            patch.object(
                module,
                'aws',
                side_effect=lambda service: (
                    self.cognito
                    if service == 'cognito-idp'
                    else self.lambda_client
                ),
            )
            for module in (
                auth,
                auth_store,
                auth_web,
                auth_authorize,
            )
        ]
        for aws_patch in self.aws_patches:
            aws_patch.start()
        self.env = patch.dict(
            os.environ,
            {
                'CUSTOMER_COMMERCE_ORIGIN': BASE,
                'CUSTOMER_AUTH_ORIGIN': auth.WEBSITE_ORIGIN,
                'CUSTOMER_OAUTH_CLIENTS': json.dumps(
                    [
                        {
                            'client_id': 'client',
                            'name': 'Test host',
                            'redirect_uris': [REDIRECT],
                        }
                    ]
                ),
                'CUSTOMER_REGISTRATION_ENABLED': 'true',
            },
            clear=False,
        )
        self.env.start()
        self.params = {
            'client_id': 'client',
            'redirect_uri': REDIRECT,
            'response_type': 'code',
            'scope': 'commerce:read commerce:write',
            'state': 'state-value',
            'resource': BASE + '/mcp',
            'code_challenge': CHALLENGE,
            'code_challenge_method': 'S256',
        }

    def tearDown(self):
        self.env.stop()
        for aws_patch in reversed(self.aws_patches):
            aws_patch.stop()

    @staticmethod
    def cookie(result):
        jar = SimpleCookie()
        jar.load(result['cookies'][0])
        return jar[auth.COOKIE].value

    def begin_website(self, return_path='/orders/'):
        result = auth.route(
            {
                'rawPath': '/auth/state',
                'rawQueryString': urlencode({'return': return_path}),
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        return self.cookie(result), json.loads(result['body'])

    def begin_oauth(self):
        result = auth.route(
            {
                'rawPath': '/auth/state',
                'rawQueryString': urlencode(self.params),
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        return self.cookie(result), json.loads(result['body'])

    def step(self, cookie, values, origin=auth.WEBSITE_ORIGIN):
        result = auth.route(
            {
                'rawPath': '/auth/step',
                'headers': {
                    'origin': origin,
                    'content-type': (
                        'application/x-www-form-urlencoded; charset=UTF-8'
                    ),
                },
                'cookies': [f'{auth.COOKIE}={cookie}'],
                'requestContext': {
                    'http': {
                        'method': 'POST',
                        'sourceIp': '127.0.0.1',
                    }
                },
                'body': urlencode(values),
            }
        )
        return (
            result,
            json.loads(result['body']) if result.get('body') else {},
        )

    def begin_website_code(self, return_path='/orders/'):
        cookie, state = self.begin_website(return_path)
        _, code_state = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                '_flow': 'website',
                '_return': return_path,
                'country': '+91',
                'phone': '9876543210',
            },
        )
        return cookie, code_state

    def test_backend_no_longer_serves_auth_page(self):
        self.assertIsNone(
            auth.route(
                {
                    'rawPath': '/auth',
                    'requestContext': {'http': {'method': 'GET'}},
                }
            )
        )
        source = Path(auth.__file__).read_text()
        self.assertNotIn('def form(', source)
        self.assertNotIn('class="nav-menu"', source)
        self.assertNotIn('BRAND_LOGO', source)

    def test_metadata_points_to_shared_next_page(self):
        self.assertEqual(
            auth.auth_metadata()['authorization_endpoint'],
            'https://wecare.digital/auth',
        )
        with patch.dict(
            os.environ,
            {'CUSTOMER_AUTH_ORIGIN': 'https://other.example'},
        ):
            with self.assertRaises(auth.AuthError):
                auth.connect_origin()

    def test_legacy_authorize_get_redirects_without_session(self):
        result = auth.route(
            {
                'rawPath': '/oauth/authorize',
                'rawQueryString': urlencode(self.params),
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        self.assertEqual(result['statusCode'], 302)
        self.assertEqual(
            result['headers']['Location'],
            auth.WEBSITE_ORIGIN + '/auth?' + urlencode(self.params),
        )
        self.assertEqual(self.store.rows, {})

    def test_website_state_is_json_and_return_is_allowlisted(self):
        cookie, state = self.begin_website('/orders/')
        self.assertEqual(state['phase'], 'phone')
        self.assertTrue(state['website'])
        self.assertEqual(state['returnPath'], '/orders/')
        self.assertTrue(cookie)
        _, fallback = self.begin_website('https://evil.example/')
        self.assertEqual(fallback['returnPath'], '/checkout/')

    def test_oauth_state_is_bound_to_registered_client(self):
        _, state = self.begin_oauth()
        self.assertEqual(state['phase'], 'phone')
        self.assertFalse(state['website'])
        self.assertEqual(state['clientName'], 'Test host')
        bad = dict(
            self.params,
            redirect_uri='https://evil.example/callback',
        )
        result = auth.route(
            {
                'rawPath': '/auth/state',
                'rawQueryString': urlencode(bad),
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        self.assertEqual(result['statusCode'], 400)

    def test_resend_and_edit_contract(self):
        cookie, state = self.begin_website()
        _, code_state = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'country': '+91',
                'phone': '9876543210',
            },
        )
        self.assertEqual(code_state['phase'], 'code')
        self.assertEqual(self.cognito.sends, 1)
        _, resent = self.step(
            cookie,
            {
                'csrf': code_state['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'action': 'resend',
                'code': '',
            },
        )
        self.assertEqual(resent['phase'], 'code')
        self.assertEqual(resent['message'], 'New code sent.')
        self.assertEqual(self.cognito.sends, 2)
        sends = self.cognito.sends
        _, edited = self.step(
            cookie,
            {
                'csrf': resent['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'action': 'edit_phone',
                'code': '',
            },
        )
        self.assertEqual(edited['phase'], 'phone')
        self.assertEqual(self.cognito.sends, sends)

    def test_website_refresh_resumes_without_resending(self):
        cookie, state = self.begin_website('/')
        _, code_state = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                '_flow': 'website',
                '_return': '/',
                'country': '+44',
                'phone': '7700900123',
            },
        )
        sends = self.cognito.sends
        result = auth.route(
            {
                'rawPath': '/auth/state',
                'rawQueryString': '',
                'cookies': [f'{auth.COOKIE}={cookie}'],
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        resumed = json.loads(result['body'])
        self.assertEqual(resumed['phase'], 'code')
        self.assertNotEqual(resumed['csrf'], code_state['csrf'])
        self.assertEqual(self.cognito.sends, sends)

    def test_oauth_refresh_with_query_resumes_same_step(self):
        cookie, state = self.begin_oauth()
        _, code_state = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                'country': '+44',
                'phone': '7700900123',
            },
        )
        sends = self.cognito.sends
        result = auth.route(
            {
                'rawPath': '/auth/state',
                'rawQueryString': urlencode(self.params),
                'cookies': [f'{auth.COOKIE}={cookie}'],
                'requestContext': {'http': {'method': 'GET'}},
            }
        )
        resumed = json.loads(result['body'])
        self.assertEqual(resumed['phase'], 'code')
        self.assertNotEqual(resumed['csrf'], code_state['csrf'])
        self.assertEqual(self.cognito.sends, sends)

    def test_stale_website_step_recovers_to_auth(self):
        _, state = self.begin_website('/orders/')
        result = auth.route(
            {
                'rawPath': '/auth/step',
                'headers': {
                    'origin': auth.WEBSITE_ORIGIN,
                    'content-type': 'application/x-www-form-urlencoded',
                },
                'requestContext': {'http': {'method': 'POST'}},
                'body': urlencode(
                    {
                        'csrf': state['csrf'],
                        '_flow': 'website',
                        '_return': '/orders/',
                        'country': '+91',
                        'phone': '9876543210',
                    }
                ),
            }
        )
        payload = json.loads(result['body'])
        self.assertEqual(
            payload['redirect'], '/auth?return=%2Forders%2F'
        )

    def test_wrong_origin_fails_closed(self):
        cookie, state = self.begin_website()
        result, payload = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'country': '+91',
                'phone': '9876543210',
            },
            origin='https://evil.example',
        )
        self.assertEqual(result['statusCode'], 400)
        self.assertEqual(payload['error'], 'invalid_request')
        self.assertEqual(self.cognito.sends, 0)

    def test_website_success_exchanges_server_session(self):
        cookie, code_state = self.begin_website_code()
        result, payload = self.step(
            cookie,
            {
                'csrf': code_state['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'code': '123456',
            },
        )
        self.assertEqual(payload['redirect'], '/orders/')
        self.assertIn(
            'wecare-customer-session:live', self.lambda_client.calls
        )
        self.assertTrue(
            any(
                value.startswith(
                    auth.WEBSITE_SESSION_COOKIE + '='
                )
                for value in result['cookies']
            )
        )

    def test_auth_errors_after_code_verification_fail_closed(self):
        cookie, code_state = self.begin_website_code()
        with patch.object(
            auth_authorize,
            'checked_cognito',
            side_effect=auth.AuthError('invalid identity'),
        ):
            result, payload = self.step(
                cookie,
                {
                    'csrf': code_state['csrf'],
                    '_flow': 'website',
                    '_return': '/orders/',
                    'code': '123456',
                },
            )
        self.assertEqual(result['statusCode'], 400)
        self.assertEqual(payload, {'error': 'invalid_request'})
        self.assertNotIn('phase', payload)

    def test_downstream_session_cookie_contract_is_strict(self):
        valid = self.lambda_client.session_cookies[0]
        self.assertEqual(
            auth_web._validated_session_cookies([valid]), [valid]
        )
        bad_values = [
            None,
            [],
            [valid, valid],
            [''],
            ['wd_csid=value\r\nX-Injected: yes'],
            ['other=value; Path=/; HttpOnly; Secure; SameSite=Lax'],
            ['wd_csid=value; Domain=.wecare.digital; Path=/; HttpOnly; Secure; SameSite=Lax'],
            ['wd_csid=value; Path=/; Secure; SameSite=Lax'],
            ['wd_csid=value; Path=/; HttpOnly; SameSite=Lax'],
            ['wd_csid=value; Path=/; HttpOnly; Secure; SameSite=None'],
        ]
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(auth.AuthError):
                    auth_web._validated_session_cookies(value)

    def test_invalid_downstream_cookie_aborts_website_sign_in(self):
        cookie, code_state = self.begin_website_code()
        self.lambda_client.session_cookies = [
            'wd_csid=validvaluebutbad\r\nSet-Cookie: admin=true'
        ]
        result, payload = self.step(
            cookie,
            {
                'csrf': code_state['csrf'],
                '_flow': 'website',
                '_return': '/orders/',
                'code': '123456',
            },
        )
        self.assertEqual(result['statusCode'], 400)
        self.assertEqual(payload, {'error': 'invalid_request'})

    def test_oauth_pkce_code_is_one_use(self):
        cookie, state = self.begin_oauth()
        _, code_state = self.step(
            cookie,
            {
                'csrf': state['csrf'],
                'country': '+44',
                'phone': '7700900123',
            },
        )
        _, payload = self.step(
            cookie,
            {'csrf': code_state['csrf'], 'code': '123456'},
        )
        values = parse_qs(urlparse(payload['redirect']).query)
        request = {
            'grant_type': 'authorization_code',
            'client_id': 'client',
            'resource': BASE + '/mcp',
            'code': values['code'][0],
            'redirect_uri': REDIRECT,
            'code_verifier': VERIFIER,
        }
        issued = auth.token_exchange(request)
        self.assertTrue(issued['access_token'].startswith('wca_'))
        with self.assertRaises(auth.AuthError):
            auth.token_exchange(request)

    def test_branded_mcp_authorization_and_access_are_resource_bound(self):
        self.params['resource'] = auth.BRANDED_RESOURCE
        cookie, state = self.begin_oauth()
        self.assertFalse(state['website'])
        _, code_state = self.step(
            cookie, {'csrf': state['csrf'], 'country': '+44',
                     'phone': '7700900123'},
        )
        _, payload = self.step(
            cookie, {'csrf': code_state['csrf'], 'code': '123456'},
        )
        code = parse_qs(urlparse(payload['redirect']).query)['code'][0]
        request = {
            'grant_type': 'authorization_code', 'client_id': 'client',
            'resource': auth.BRANDED_RESOURCE, 'code': code,
            'redirect_uri': REDIRECT, 'code_verifier': VERIFIER,
        }
        with self.assertRaises(auth.AuthError):
            auth.token_exchange({**request, 'resource': BASE + '/mcp'})
        issued = auth.token_exchange(request)
        branded = {
            'rawPath': '/mcp-branded',
            'headers': {'authorization': 'Bearer ' + issued['access_token']},
        }
        delegated = auth.customer_event(branded, 'commerce:read')
        self.assertEqual(
            delegated['headers']['authorization'],
            'Bearer ' + self.cognito.access,
        )
        with self.assertRaises(auth.AuthError):
            auth.customer_event({**branded, 'rawPath': '/mcp'}, 'commerce:read')
        with self.assertRaises(auth.AuthError):
            auth.token_exchange(request)

    def test_original_mcp_token_cannot_authorize_branded_route(self):
        cookie, state = self.begin_oauth()
        _, code_state = self.step(
            cookie, {'csrf': state['csrf'], 'country': '+44',
                     'phone': '7700900123'},
        )
        _, payload = self.step(
            cookie, {'csrf': code_state['csrf'], 'code': '123456'},
        )
        code = parse_qs(urlparse(payload['redirect']).query)['code'][0]
        issued = auth.token_exchange({
            'grant_type': 'authorization_code', 'client_id': 'client',
            'resource': BASE + '/mcp', 'code': code,
            'redirect_uri': REDIRECT, 'code_verifier': VERIFIER,
        })
        with self.assertRaises(auth.AuthError):
            auth.customer_event({
                'rawPath': '/mcp-branded',
                'headers': {'authorization': 'Bearer ' + issued['access_token']},
            }, 'commerce:read')
        result = auth.customer_event({
            'rawPath': '/mcp',
            'headers': {'authorization': 'Bearer ' + issued['access_token']},
        }, 'commerce:read')
        self.assertEqual(
            result['headers']['authorization'],
            'Bearer ' + self.cognito.access,
        )

    def test_unrecognized_resource_still_fails_closed(self):
        params = {**self.params, 'resource': 'https://other.example/mcp'}
        result = auth.route({
            'rawPath': '/auth/state', 'rawQueryString': urlencode(params),
            'requestContext': {'http': {'method': 'GET'}},
        })
        self.assertEqual(result['statusCode'], 400)

    def test_invalid_content_type_is_rejected(self):
        result = auth.route(
            {
                'rawPath': '/auth/step',
                'headers': {'content-type': 'application/json'},
                'requestContext': {'http': {'method': 'POST'}},
                'body': '{}',
            }
        )
        self.assertEqual(result['statusCode'], 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
