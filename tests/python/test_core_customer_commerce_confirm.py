"""Customer commerce MCP: honest write hints, and update_my_account saves only on a second
call carrying the single-use confirmationId from the first. Fake store, session and
delegated handlers; no AWS calls."""
import base64
import importlib.util
import json
import time
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "amplify/functions/ai/customer-commerce-mcp"


@pytest.fixture
def mcp(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE))
    monkeypatch.setenv("CUSTOMER_COMMERCE_ORIGIN", "https://example.execute-api.us-east-1.amazonaws.com")
    spec = importlib.util.spec_from_file_location("customer_commerce_handler_under_test",
                                                  SOURCE / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jwt(sub):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return "eyJhbGciOiJSUzI1NiJ9." + payload + ".signature"


class Store:
    """Same contract as customer_oauth_store.Store: expiry on read, conditional take."""

    def __init__(self):
        self.rows = {}

    def get(self, key):
        row = self.rows.get(key)
        return dict(row) if row and row["absoluteExpiresAt"] > int(time.time()) else None

    def put(self, row):
        assert row["sidHash"].startswith("mcp:commerce:") and row["sidHash"] not in self.rows
        self.rows[row["sidHash"]] = dict(row)

    def take(self, key):
        row = self.get(key)
        self.rows.pop(key, None)
        return row


@pytest.fixture
def account(mcp, monkeypatch):
    state = {"sub": "customer-sub-1", "writes": [], "store": Store()}
    monkeypatch.setattr(mcp.customer_oauth, "STORE", state["store"])
    monkeypatch.setattr(mcp.customer_oauth, "customer_event", lambda event, scope: {
        **event, "headers": {"authorization": "Bearer " + jwt(state["sub"])}})

    def delegate(function, body, event, path):
        if function == "wecare-commerce:live":
            assert body == {"action": "profile"}
            return mcp.reply(200, {"status": "PROFILE_READY", "email": "old@example.test",
                                   "firstName": "Asha", "address": None})
        assert function == "wecare-customer-profile:live" and path == "/customer/profile"
        state["writes"].append(body)
        return mcp.reply(200, {"status": "PROFILE_READY", **body})

    monkeypatch.setattr(mcp, "delegate", delegate)
    event = {"headers": {"authorization": "Bearer wca_session"}, "rawPath": "/mcp"}

    def update(args):
        return mcp.call_tool("update_my_account", args, event)

    return state, update


def annotations(mcp):
    return {t["name"]: t["annotations"] for t in mcp.tools()}


def test_update_my_account_is_destructive_and_not_idempotent(mcp):
    hints = annotations(mcp)
    assert hints["update_my_account"] == {"readOnlyHint": False, "destructiveHint": True,
                                          "idempotentHint": False, "openWorldHint": False}
    assert hints["get_my_account"] == mcp.READ_ANNOTATIONS
    assert hints["check_my_payment"] == mcp.WRITE_ANNOTATIONS


def test_whatsapp_payment_request_is_open_world(mcp, monkeypatch):
    monkeypatch.setenv("WHATSAPP_PAYMENT_REQUESTS_ENABLED", "true")
    assert annotations(mcp)["request_whatsapp_payment"] == {
        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


def test_first_call_returns_the_diff_and_saves_nothing(account):
    state, update = account
    result = update({"email": "new@example.test"})
    data = result["structuredContent"]
    assert result["isError"] is False and data["status"] == "CONFIRMATION_REQUIRED"
    assert data["saved"] is False and state["writes"] == []
    assert data["changes"] == [{"field": "email", "current": "old@example.test",
                                "proposed": "new@example.test"}]
    assert data["confirmationId"] in result["content"][0]["text"]
    (row,) = state["store"].rows.values()
    assert row["subject"] == "customer-sub-1" and row["kind"] == "account-change"
    assert 0 < row["absoluteExpiresAt"] - time.time() <= 600
    assert "new@example.test" not in json.dumps(row)


def test_second_call_with_the_id_applies_the_same_change_once(account):
    state, update = account
    confirmation = update({"email": "new@example.test"})["structuredContent"]["confirmationId"]
    saved = update({"email": "new@example.test", "confirmationId": confirmation})
    assert saved["isError"] is False and state["writes"] == [{"email": "new@example.test"}]
    replay = update({"email": "new@example.test", "confirmationId": confirmation})
    assert replay["structuredContent"] == {"status": "CONFIRMATION_INVALID", "saved": False}
    assert len(state["writes"]) == 1 and state["store"].rows == {}


def test_the_id_is_bound_to_the_previewed_fields(account):
    state, update = account
    confirmation = update({"email": "new@example.test"})["structuredContent"]["confirmationId"]
    changed = update({"email": "attacker@example.test", "confirmationId": confirmation})
    assert changed["isError"] is True and state["writes"] == []
    # A mismatch does not burn the id; the previewed change can still be confirmed.
    assert update({"email": "new@example.test", "confirmationId": confirmation})["isError"] is False


def test_the_id_is_bound_to_the_customer(account):
    state, update = account
    confirmation = update({"email": "new@example.test"})["structuredContent"]["confirmationId"]
    state["sub"] = "customer-sub-2"
    result = update({"email": "new@example.test", "confirmationId": confirmation})
    assert result["isError"] is True and state["writes"] == []


def test_expired_or_unknown_ids_are_refused(account):
    state, update = account
    confirmation = update({"email": "new@example.test"})["structuredContent"]["confirmationId"]
    for row in state["store"].rows.values():
        row["absoluteExpiresAt"] = int(time.time()) - 1
    assert update({"email": "new@example.test", "confirmationId": confirmation})["isError"] is True
    assert update({"email": "new@example.test", "confirmationId": "x" * 32})["isError"] is True
    assert state["writes"] == []


def test_a_bare_confirmation_id_is_not_a_change(account):
    _, update = account
    with pytest.raises(ValueError):
        update({"confirmationId": "x" * 32})
