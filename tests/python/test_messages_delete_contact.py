"""Delete selected / all messages of a contact; payment messages are protected.

Synthetic data only. Tables and the confirmation store are in-memory fakes.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
shared = str(ROOT / "amplify/functions/shared")
if shared not in sys.path:
    sys.path.insert(0, shared)
os.environ.setdefault("AWS_REGION", "us-east-1")

_spec = importlib.util.spec_from_file_location(
    "messages_delete_handler", ROOT / "amplify/functions/core/messages-delete/handler.py")
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)

from lambda_utils import destructive_confirm  # noqa: E402


class FakeTable:
    def __init__(self, items):
        self.items = list(items)
        self.deleted = []

    def scan(self, **kw):
        cid = kw["ExpressionAttributeValues"][":cid"]
        return {"Items": [dict(i) for i in self.items if i.get("contactId") == cid]}

    def delete_item(self, Key, **kw):
        self.items = [i for i in self.items if i["id"] != Key["id"]]
        self.deleted.append(Key["id"])


class FakeConfig:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, **kw):
        self.rows[Item["id"]] = Item

    def get_item(self, Key, **kw):
        r = self.rows.get(Key["id"])
        return {"Item": dict(r)} if r else {}

    def delete_item(self, Key, **kw):
        if Key["id"] not in self.rows:
            raise RuntimeError("gone")
        del self.rows[Key["id"]]


@pytest.fixture
def env(monkeypatch):
    inbound = FakeTable([
        {"id": "m1", "contactId": "c1", "content": "hello"},
        {"id": "m2", "contactId": "c1", "content": "thanks"},
        {"id": "other", "contactId": "c2", "content": "hi"},
    ])
    outbound = FakeTable([
        {"id": "pay1", "contactId": "c1", "content": "Payment received", "paymentId": "pay_ABCDEF123"},
        {"id": "m3", "contactId": "c1", "content": "see you"},
    ])
    tables = {md.INBOUND_TABLE: inbound, md.OUTBOUND_TABLE: outbound}
    monkeypatch.setattr(md, "dynamodb", type("D", (), {"Table": lambda self, n: tables[n]})())
    monkeypatch.setattr(md, "_get_key_schema", lambda n: [{"AttributeName": "id", "KeyType": "HASH"}])
    cfg = FakeConfig()
    monkeypatch.setattr(destructive_confirm, "_table", lambda: cfg)
    monkeypatch.setattr(md, "record_audit", lambda **kw: "audit-1")
    from lambda_utils import middleware
    monkeypatch.setattr(middleware, "require_auth", lambda event, required_role=None: None)
    return type("E", (), {"inbound": inbound, "outbound": outbound})


def call(body, mfa=True):
    event = {"httpMethod": "DELETE", "path": "/messages", "body": json.dumps(body),
             "_auth": {"role": "Admin", "mfaEnrolled": mfa, "username": "admin-1"}}
    resp = md._handle_contact_messages(event, "")
    return resp["statusCode"], json.loads(resp["body"])


def test_selected_deletes_only_owned_non_payment_messages(env):
    status, out = call({"contactId": "c1", "messageIds": ["m1", "pay1", "other", "ghost"]})
    assert status == 200
    assert out["deleted"] == 1 and out["protected"] == 1
    assert out["protectedMessages"][0]["id"] == "pay1"
    assert sorted(out["notFound"]) == ["ghost", "other"]
    assert env.inbound.deleted == ["m1"] and env.outbound.deleted == []


def test_delete_all_needs_preview_token_and_skips_payment(env):
    status, preview = call({"contactId": "c1", "all": True, "preview": True})
    assert status == 200
    assert preview["counts"] == {"deletable": 3, "protected": 1}
    assert env.inbound.deleted == [] and env.outbound.deleted == []

    status, refused = call({"contactId": "c1", "all": True})
    assert status == 400 and not (env.inbound.deleted or env.outbound.deleted)

    status, out = call({"contactId": "c1", "all": True, "confirmationToken": preview["confirmationToken"]})
    assert status == 200 and out["deleted"] == 3 and out["protected"] == 1
    assert [i["id"] for i in env.outbound.items] == ["pay1"]
    assert [i["id"] for i in env.inbound.items] == ["other"]

    # Token is single use.
    status, _ = call({"contactId": "c1", "all": True, "confirmationToken": preview["confirmationToken"]})
    assert status != 200


def test_token_is_bound_to_the_contact(env):
    _, preview = call({"contactId": "c1", "all": True, "preview": True})
    status, _ = call({"contactId": "c2", "all": True, "confirmationToken": preview["confirmationToken"]})
    assert status != 200 and env.inbound.deleted == []


def test_delete_all_requires_mfa(env):
    status, out = call({"contactId": "c1", "all": True, "preview": True}, mfa=False)
    assert status == 403 and out["errorCode"] == "ADMIN_MFA_REQUIRED"


def test_body_validation(env):
    assert call({"messageIds": ["m1"]})[0] == 400
    assert call({"contactId": "c1"})[0] == 400
    assert call({"contactId": "c1", "all": True, "messageIds": ["m1"]})[0] == 400


def test_single_delete_refuses_payment_message(env, monkeypatch):
    class Tbl(FakeTable):
        def get_item(self, Key):
            return {"Item": next((dict(i) for i in self.items if i["id"] == Key["id"]), None)}
    out_t = Tbl(env.outbound.items)
    monkeypatch.setattr(md, "dynamodb", type("D", (), {"Table": lambda self, n: out_t})())
    event = {"httpMethod": "DELETE", "path": "/messages/pay1", "pathParameters": {"messageId": "pay1"},
             "queryStringParameters": {"direction": "OUTBOUND"}, "_auth": {"role": "Operator"}}
    from lambda_utils import middleware
    monkeypatch.setattr(middleware, "require_auth", lambda e, required_role=None: None)
    resp = md.handler(event, None)
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error"] == md.PAYMENT_PROTECTED
    assert out_t.deleted == []


def test_selected_delete_is_audited_and_fails_closed(env, monkeypatch):
    audits = []
    monkeypatch.setattr(md, "record_audit", lambda **kw: audits.append(kw) or "audit-1")
    monkeypatch.setattr(md, "record_audit", lambda **kw: None)
    status, _ = call({"contactId": "c1", "messageIds": ["m1"]})
    assert status == 503 and env.inbound.deleted == []
    monkeypatch.setattr(md, "record_audit", lambda **kw: audits.append(kw) or "audit-1")
    status, _ = call({"contactId": "c1", "messageIds": ["m1"]})
    assert status == 200 and audits[0]["action"] == "messages.delete_contact_selected"
