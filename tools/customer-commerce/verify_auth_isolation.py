"""Focused regression checks for the shared website/host authentication boundary."""
from __future__ import annotations

from http.cookies import SimpleCookie
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'amplify/functions/ai/customer-commerce-mcp'
sys.path.insert(0, str(SOURCE))

import customer_oauth as auth
from verify_oauth import OAuthContract


class AuthFlowIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = OAuthContract(methodName='runTest')
        self.contract.setUp()

    def tearDown(self) -> None:
        self.contract.tearDown()

    @staticmethod
    def cookie(result: dict) -> str:
        jar = SimpleCookie()
        jar.load(result['cookies'][0])
        return jar[auth.COOKIE].value

    def test_website_cookie_cannot_resume_host_oauth(self) -> None:
        website_cookie, _ = self.contract.begin_website('/')
        result = auth.route({
            'rawPath': '/auth/state',
            'rawQueryString': urlencode(self.contract.params),
            'cookies': [f'{auth.COOKIE}={website_cookie}'],
            'requestContext': {'http': {'method': 'GET'}},
        })
        state = json.loads(result['body'])
        self.assertFalse(state['website'])
        self.assertEqual(state['clientName'], 'Test host')
        self.assertNotEqual(self.cookie(result), website_cookie)
        self.assertIsNotNone(
            self.contract.store.get(auth.row_key('auth', website_cookie))
        )

    def test_oauth_cookie_cannot_resume_website_sign_in(self) -> None:
        oauth_cookie, _ = self.contract.begin_oauth()
        result = auth.route({
            'rawPath': '/auth/state',
            'rawQueryString': urlencode({'return': '/orders/'}),
            'cookies': [f'{auth.COOKIE}={oauth_cookie}'],
            'requestContext': {'http': {'method': 'GET'}},
        })
        state = json.loads(result['body'])
        self.assertTrue(state['website'])
        self.assertEqual(state['returnPath'], '/orders/')
        self.assertNotEqual(self.cookie(result), oauth_cookie)
        self.assertIsNotNone(
            self.contract.store.get(auth.row_key('auth', oauth_cookie))
        )

    def test_get_collection_returns_to_get_after_sign_in(self) -> None:
        result = auth.route({
            'rawPath': '/auth/state',
            'rawQueryString': urlencode({'return': '/get/'}),
            'requestContext': {'http': {'method': 'GET'}},
        })
        state = json.loads(result['body'])
        self.assertTrue(state['website'])
        self.assertEqual(state['returnPath'], '/get/')
        self.assertEqual(state['destination'], '/get/')


if __name__ == '__main__':
    unittest.main(verbosity=2)
