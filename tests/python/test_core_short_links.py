"""Short-link codes: new generated codes are 10 characters, vanity and existing 6-character
codes keep working. In-memory tables; no AWS calls."""
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "url_shortener_under_test", ROOT / "amplify/functions/core/url-shortener/handler.py")
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)


class Links:
    def __init__(self, rows=()):
        self.rows = {r["shortCode"]: dict(r) for r in rows}

    def put_item(self, Item, ConditionExpression=None):
        self.rows[Item["shortCode"]] = dict(Item)

    def get_item(self, Key):
        row = self.rows.get(Key["shortCode"])
        return {"Item": dict(row)} if row else {}

    def update_item(self, **_):
        return {}


class Clicks:
    def put_item(self, Item):
        return {}


@pytest.fixture
def tables(monkeypatch):
    links = Links()
    monkeypatch.setattr(H, "links_table", links)
    monkeypatch.setattr(H, "clicks_table", Clicks())
    monkeypatch.setattr(H, "_link_cache", {})
    return links


def test_generated_codes_are_ten_lowercase_alphanumerics():
    codes = {H.generate_code() for _ in range(200)}
    assert all(re.fullmatch(r"[a-z0-9]{10}", c) for c in codes)
    assert len(codes) == 200


def test_new_link_without_a_code_gets_a_ten_character_code(tables):
    response = H.create_link({"originalUrl": "https://wecare.digital/orders/"}, actor="staff")
    link = json.loads(response["body"])["link"]
    assert response["statusCode"] == 200 and len(link["shortCode"]) == 10
    assert link["shortUrl"].endswith("/" + link["shortCode"])


def test_vanity_code_is_unchanged(tables):
    response = H.create_link({"originalUrl": "https://wecare.digital/", "shortCode": "wa"},
                             actor="staff")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["link"]["shortCode"] == "wa"


def test_existing_six_character_code_still_redirects(tables):
    tables.rows["abc123"] = {"shortCode": "abc123", "originalUrl": "https://wecare.digital/blog/",
                             "lifecycleState": "ACTIVE", "active": True}
    event = {"requestContext": {"http": {"method": "GET", "path": "/r/abc123"}},
             "rawPath": "/r/abc123", "headers": {}}
    response = H.handler(event, None)
    assert response["statusCode"] == 302
    assert response["headers"]["Location"] == "https://wecare.digital/blog/"
