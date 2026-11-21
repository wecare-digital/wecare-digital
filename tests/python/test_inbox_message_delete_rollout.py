"""Runtime proof: canonical inbox deletion cannot hit legacy unprefixed IDs."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "amplify/functions/core/messages-delete/handler.py"
SPEC = importlib.util.spec_from_file_location("messages_delete_safe_rollout", SOURCE)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)

MARKER = "__canonical_inbox_v1__:"


def request(message_id):
    return {
        "requestContext": {"http": {
            "method": "DELETE",
            "path": "/messages/" + message_id,
        }},
        "queryStringParameters": {"scope": "inbox"},
        "pathParameters": {"messageId": message_id},
    }


def body(response):
    return int(response["statusCode"]), json.loads(response["body"])


@pytest.fixture
def invoke(monkeypatch):
    import lambda_utils.middleware as middleware
    import lambda_utils.erasure.inbox_delete as delete_module

    auth = {"role": "Admin", "mfaEnrolled": True, "username": "synthetic-admin"}
    calls = []

    def permit(event, required_role=None):
        event["_auth"] = dict(auth)
        return None

    class Db:
        def Table(self, name):
            return object()

    def fake_delete(**kwargs):
        calls.append(kwargs)
        return delete_module.DeleteDecision(
            200, {"success": True, "rowDeleted": True,
                  "erasureComplete": False, "auditId": "synthetic-audit"}
        )

    monkeypatch.setattr(middleware, "require_auth", permit)
    monkeypatch.setattr(delete_module, "delete_visible_message", fake_delete)
    monkeypatch.setattr(HANDLER, "dynamodb", Db())
    return auth, calls


def test_unmarked_id_rejected_without_any_delete(invoke):
    _, calls = invoke
    status, result = body(HANDLER.handler(request("msg-one"), None))
    assert status == 400
    assert result["errorCode"] == "MESSAGE_DELETE_MARKER_REQUIRED"
    assert calls == []


def test_correct_marker_reaches_exact_id_only(invoke):
    _, calls = invoke
    status, result = body(HANDLER.handler(request(MARKER + "msg-one"), None))
    assert status == 200
    assert result["rowDeleted"] is True
    assert len(calls) == 1
    assert calls[0]["message_id"] == "msg-one"


def test_double_marker_refused(invoke):
    _, calls = invoke
    status, _ = body(HANDLER.handler(request(MARKER + MARKER + "msg-one"), None))
    assert status == 400
    assert calls == []


def test_unattributable_admin_cannot_delete(invoke):
    auth, calls = invoke
    auth.pop("username")
    status, result = body(HANDLER.handler(request(MARKER + "msg-one"), None))
    assert status == 403
    assert result["errorCode"] == "MESSAGE_DELETE_ACTOR_REQUIRED"
    assert calls == []


def test_content_only_scope_uses_separate_audited_operation(invoke, monkeypatch):
    import lambda_utils.erasure.inbox_delete as delete_module
    _, delete_calls = invoke
    redact_calls = []

    def fake_redact(**kwargs):
        redact_calls.append(kwargs)
        return delete_module.DeleteDecision(
            200, {"success": True, "contentDeleted": True,
                  "rowDeleted": False, "erasureComplete": False}
        )

    monkeypatch.setattr(delete_module, "redact_visible_message_content", fake_redact)
    scoped = request(MARKER + "msg-one")
    scoped["queryStringParameters"] = {"scope": "content-only"}
    status, payload = body(HANDLER.handler(scoped, None))
    assert status == 200
    assert payload["contentDeleted"] is True
    assert payload["rowDeleted"] is False
    assert [call["message_id"] for call in redact_calls] == ["msg-one"]
    assert delete_calls == []


def test_content_only_unmarked_id_is_rejected(invoke):
    _, delete_calls = invoke
    scoped = request("msg-one")
    scoped["queryStringParameters"] = {"scope": "content-only"}
    status, payload = body(HANDLER.handler(scoped, None))
    assert status == 400
    assert payload["errorCode"] == "MESSAGE_DELETE_MARKER_REQUIRED"
    assert delete_calls == []
