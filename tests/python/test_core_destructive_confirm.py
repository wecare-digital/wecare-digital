"""Destructive confirmation tokens are bound to the Admin who previewed. In-memory
SystemConfigTable and message tables; no AWS calls."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from lambda_utils import destructive_confirm

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
ROOT = Path(__file__).resolve().parents[2]
SCOPE = "test_scope"


class FakeConfig:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, **_):
        self.rows[Item["id"]] = dict(Item)

    def get_item(self, Key, **_):
        row = self.rows.get(Key["id"])
        return {"Item": dict(row)} if row else {}

    def delete_item(self, Key, **_):
        if Key["id"] not in self.rows:
            raise RuntimeError("ConditionalCheckFailedException")
        del self.rows[Key["id"]]


@pytest.fixture
def config(monkeypatch):
    table = FakeConfig()
    monkeypatch.setattr(destructive_confirm, "_table", lambda: table)
    return table


def test_same_actor_redeems_and_gets_the_previewing_actor(config):
    token = destructive_confirm.mint(SCOPE, ["a", "b"], {"a": 1}, "admin-a")
    result = destructive_confirm.consume(SCOPE, token, ["b", "a"], actor="admin-a")
    assert result["ok"] is True and result["actor"] == "admin-a" and config.rows == {}


def test_another_actor_is_refused_and_the_token_stays_usable(config):
    token = destructive_confirm.mint(SCOPE, ["a"], {}, "admin-a")
    refused = destructive_confirm.consume(SCOPE, token, ["a"], actor="admin-b")
    assert refused == {"error": "Confirmation token belongs to another user — preview again",
                       "status": 403}
    assert len(config.rows) == 1
    assert destructive_confirm.consume(SCOPE, token, ["a"], actor="admin-a")["ok"] is True


@pytest.mark.parametrize("stored", ["", None])
def test_a_token_without_a_stored_actor_cannot_be_redeemed_by_a_named_actor(config, stored):
    token = destructive_confirm.mint(SCOPE, ["a"], {}, stored)
    assert destructive_confirm.consume(SCOPE, token, ["a"], actor="admin-a")["status"] == 403


def test_callers_that_do_not_pass_an_actor_keep_working(config):
    token = destructive_confirm.mint(SCOPE, ["a"], {}, "admin-a")
    assert destructive_confirm.consume(SCOPE, token, ["a"])["ok"] is True


@pytest.fixture
def clear_all(monkeypatch, config):
    import lambda_utils.middleware as middleware
    spec = importlib.util.spec_from_file_location(
        "messages_delete_confirm_binding", ROOT / "amplify/functions/core/messages-delete/handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = {"sub": "sub-admin-a", "audits": [], "deleted": []}

    def require_auth(event, required_role=None):
        event["_auth"] = {"username": "u-" + state["sub"], "role": "Admin", "mfaEnrolled": True,
                          "attributes": {"sub": state["sub"]}}
        return None

    class Batch:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def delete_item(self, Key):
            state["deleted"].append(Key)

    class Messages:
        def __init__(self):
            self.items = [{"id": "m1"}]

        def scan(self, **kwargs):
            if kwargs.get("Select") == "COUNT":
                return {"Count": len(self.items)}
            items, self.items = self.items, []
            return {"Items": items}

        def batch_writer(self):
            return Batch()

    tables = {}
    monkeypatch.setattr(middleware, "require_auth", require_auth)
    monkeypatch.setenv("ALLOW_MESSAGE_CLEAR_ALL", "true")
    monkeypatch.setattr(module, "record_audit",
                        lambda **kw: state["audits"].append(kw) or "log-1")
    monkeypatch.setattr(module, "_get_key_schema", lambda name: [{"AttributeName": "id"}])
    monkeypatch.setattr(module, "dynamodb", type("D", (), {
        "Table": lambda self, name: tables.setdefault(name, Messages())})())

    def call(body):
        response = module._handle_clear_all({"body": json.dumps(body)}, "origin")
        return response["statusCode"], json.loads(response["body"])

    return state, call


def test_clear_all_token_cannot_be_redeemed_by_another_admin(clear_all):
    state, call = clear_all
    status, preview = call({"preview": True})
    assert status == 200 and preview["confirmationToken"]
    state["sub"] = "sub-admin-b"
    status, body = call({"confirmationToken": preview["confirmationToken"]})
    assert status == 403 and state["audits"] == [] and state["deleted"] == []


def test_clear_all_audit_records_the_previewing_actor(clear_all):
    state, call = clear_all
    token = call({"preview": True})[1]["confirmationToken"]
    status, body = call({"confirmationToken": token})
    assert status == 200 and body["totalDeleted"] == 2
    audit = state["audits"][0]
    assert audit["action"] == "messages.clear_all" and audit["actor"] == "sub-admin-a"
    assert audit["details"]["previewActor"] == "sub-admin-a"
