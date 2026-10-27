"""Short-link destination safety: the stored-XSS / open-redirect / overwrite fixes of 2026-10-27.

Authority: offline. The handler module is imported with its DynamoDB tables replaced by in-memory
fakes, so no AWS call is made. Pins three properties that used to be absent:

* only https destinations redirect, and only app schemes that cannot run script deep-link;
* the deep-link page encodes values for the JS and attribute contexts they land in;
* POST /links never replaces an existing code, and the creator comes from the session.

    python -m unittest tests/test_url_shortener_destinations.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
sys.path.insert(0, str(FUNCTIONS / "shared"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def _load():
    spec = importlib.util.spec_from_file_location(
        "url_shortener_handler", FUNCTIONS / "core" / "url-shortener" / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shortener = _load()


class _FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 - boto3 shape
        if ConditionExpression and Item["shortCode"] in self.items:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[Item["shortCode"]] = dict(Item)

    def get_item(self, Key):  # noqa: N803
        item = self.items.get(Key["shortCode"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, **kwargs):
        return {}


class DestinationRules(unittest.TestCase):
    def test_web_destination_refuses_unsafe(self):
        for url in ("javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,<script>x</script>",
                    "http://example.com/", "//example.com/", "/relative", "https://",
                    "java\tscript:alert(1)", "https://example.com/\nSet-Cookie: x", "", None, 42):
            with self.subTest(url=url):
                self.assertIsNone(shortener.web_destination(url))

    def test_web_destination_accepts_https(self):
        self.assertEqual(shortener.web_destination(" https://wa.me/919330994400 "),
                         "https://wa.me/919330994400")

    def test_app_destination(self):
        for url, ok in (("myapp://open/item/7", True), ("intent://scan/#Intent;scheme=zxing;end", True),
                        ("https://apps.apple.com/app/id1", True), ("javascript:alert(1)", False),
                        ("vbscript:msgbox", False), ("data:text/html,x", False),
                        ("http://x.test/", False), ("not a url", False)):
            with self.subTest(url=url):
                self.assertIs(shortener.app_destination(url) is not None, ok)


class LinkWrites(unittest.TestCase):
    def setUp(self):
        self.links, self.clicks = _FakeTable(), _FakeTable()
        self._saved = (shortener.links_table, shortener.clicks_table)
        shortener.links_table, shortener.clicks_table = self.links, self.clicks
        shortener._link_cache.clear()

    def tearDown(self):
        shortener.links_table, shortener.clicks_table = self._saved
        shortener._link_cache.clear()

    def test_create_refuses_script_destinations(self):
        for body in ({"originalUrl": "javascript:alert(1)"},
                     {"originalUrl": "https://ok.test/", "iosUrl": "javascript:alert(document.cookie)"},
                     {"originalUrl": "https://ok.test/", "shortCode": "../admin"}):
            with self.subTest(body=body):
                self.assertEqual(shortener.create_link(body, actor="staff@example.test")["statusCode"], 400)
        self.assertEqual(self.links.items, {})

    def test_create_never_overwrites_and_records_session_actor(self):
        first = shortener.create_link({"originalUrl": "https://ok.test/a", "shortCode": "wa",
                                       "userId": "spoofed"}, actor="staff@example.test")
        self.assertEqual(first["statusCode"], 200)
        self.assertEqual(self.links.items["wa"]["createdBy"], "staff@example.test")
        second = shortener.create_link({"originalUrl": "https://evil.test/", "shortCode": "wa"},
                                       actor="other@example.test")
        self.assertEqual(second["statusCode"], 409)
        self.assertEqual(self.links.items["wa"]["originalUrl"], "https://ok.test/a")

    def test_redirect_ignores_unsafe_legacy_row(self):
        self.links.items["old"] = {"shortCode": "old", "originalUrl": "javascript:alert(1)",
                                   "lifecycleState": "ACTIVE", "active": True}
        response = shortener.redirect("old", {"headers": {}})
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], shortener.FALLBACK_URL)


class DeepLinkPage(unittest.TestCase):
    def test_deep_link_page_encodes_both_contexts(self):
        hostile = 'myapp://x";alert(1);//</script><script>alert(2)</script>'
        page = shortener.deep_link_html(hostile, 'https://ok.test/?a="><img src=x onerror=alert(3)>', "ios")
        body = page["body"]
        self.assertEqual(page["statusCode"], 200)
        self.assertNotIn("</script><script>", body)
        self.assertIn("\\u003c/script\\u003e", body)
        self.assertNotIn("onerror=alert(3)>", body)
        self.assertIn("&quot;&gt;&lt;img", body)
        self.assertIn("default-src 'none'", page["headers"]["Content-Security-Policy"])
        # The JS literal round-trips to exactly the stored value.
        literal = body.split("var appUrl = ", 1)[1].split(";\n", 1)[0]
        self.assertEqual(json.loads(literal), hostile)

    def test_deep_link_with_script_scheme_degrades_to_redirect(self):
        page = shortener.deep_link_html("javascript:alert(1)", "https://ok.test/", "android")
        self.assertEqual(page["statusCode"], 302)
        self.assertEqual(page["headers"]["Location"], "https://ok.test/")


if __name__ == "__main__":
    unittest.main()
