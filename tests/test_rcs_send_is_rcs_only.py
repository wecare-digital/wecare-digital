"""rcs-send asks Sinch for RCS and nothing else.

A `fallback` flag used to add `channel_priority_order: ["RCS", "SMS"]` to the Conversation
API payload, which hands an undeliverable RCS message to Sinch's SMS channel. SMS is sent
only through AWS End User Messaging (`lambda_utils.comms`), so every payload this function
builds names exactly one channel, RCS, with or without the flag.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

HANDLER = ROOT / "amplify" / "functions" / "messaging" / "rcs-send" / "handler.py"

VARIANTS = {
    "template": {"templateId": "rcsmenu"},
    "text": {"text": "hello"},
    "choices": {"text": "pick one", "choices": [{"text_message": {"text": "a"}}]},
    "card": {"card": {"title": "t"}},
    "carousel": {"carousel": {"cards": []}},
}


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Payloads `_send_rcs` posts, captured instead of sent."""
    spec = importlib.util.spec_from_file_location("rcs_send_rcs_only_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_get_token", lambda: "token")
    monkeypatch.setattr(module, "_store_rcs_message", lambda *a, **k: None)
    payloads = []

    def urlopen(request, timeout=None):
        payloads.append(json.loads(request.data.decode()))
        return _Response(b'{"message_id": "m-1"}')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    return module, payloads


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_every_payload_names_rcs_as_the_only_channel(sent, variant, fallback):
    module, payloads = sent
    body = dict(VARIANTS[variant], phoneNumber="+919903300044", fallback=fallback)
    response = module._send_rcs(body, "req-1", "https://wecare.digital")
    assert response["statusCode"] == 200
    (payload,) = payloads
    assert "channel_priority_order" not in payload
    identities = payload["recipient"]["identified_by"]["channel_identities"]
    assert identities == [{"channel": "RCS", "identity": "919903300044"}]
    assert "SMS" not in json.dumps(payload)


def test_the_response_reports_rcs_through_sinch(sent):
    module, _ = sent
    response = module._send_rcs({"phoneNumber": "+919903300044", "text": "hi",
                                 "fallback": True}, "req-1", "https://wecare.digital")
    body = json.loads(response["body"])
    assert body["channel"] == "RCS"
    assert body["provider"] == "sinch-rcs"


def test_no_channel_other_than_rcs_is_expressible_in_the_source():
    """Structural: no string constant in the module names a second channel."""
    tree = ast.parse(HANDLER.read_text())
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "channel_priority_order" not in constants
    assert "SMS" not in constants
