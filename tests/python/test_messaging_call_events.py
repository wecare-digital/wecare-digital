"""MSG-6: a call event is acted on once, and the webhook request never sleeps.

The calling handler is loaded with fake AWS credentials; every Meta, SMS and DynamoDB
side effect is replaced by a recorder.
"""
import ast
import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/messaging/whatsapp-calling/handler.py")


@pytest.fixture(scope="module")
def calling():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    spec = importlib.util.spec_from_file_location("whatsapp_calling_under_test", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SIDE_EFFECTS = ("_store_call_log", "_auto_pickup_and_play", "put_call_breadcrumb")


def deliver(calling, event_type, claimed):
    call = {"id": "wacid.1", "event": event_type, "from": "919800000004",
            "to": "919330994400", "duration": 12, "reason": "completed"}
    patches = [mock.patch.object(calling, name) for name in SIDE_EFFECTS]
    with mock.patch.object(calling.webhook_dedup, "claim_event", return_value=claimed) as claim, \
            mock.patch.object(calling, "_is_auto_pickup_enabled", return_value=True):
        mocks = [p.start() for p in patches]
        try:
            calling._handle_call_event("waba-1", call, {"phone_number_id": "1016149501586345"},
                                       [], "req")
        finally:
            for p in patches:
                p.stop()
    return claim, dict(zip(SIDE_EFFECTS, mocks))


@pytest.mark.parametrize("event_type", ["connect", "terminate"])
def test_redelivered_call_event_has_no_side_effects(calling, event_type):
    claim, effects = deliver(calling, event_type, claimed=False)
    claim.assert_called_once_with(f"call:wacid.1:{event_type}", source="whatsapp_call")
    assert not any(m.called for m in effects.values())


def test_first_connect_claims_before_acting(calling):
    claim, effects = deliver(calling, "connect", claimed=True)
    claim.assert_called_once_with("call:wacid.1:connect", source="whatsapp_call")
    assert effects["_store_call_log"].called
    assert effects["_auto_pickup_and_play"].call_count == 1


def test_first_terminate_records_the_call_and_sends_nothing(calling):
    _, effects = deliver(calling, "terminate", claimed=True)
    assert effects["put_call_breadcrumb"].call_count == 1
    for name in ("_send_post_call_reaction", "_send_disconnect_sms", "_send_call_whatsapp_notification",
                 "_send_call_followup_text", "_send_incoming_call_sms"):
        assert not hasattr(calling, name), name


def test_handler_source_has_no_sleep_and_no_dead_cooldown():
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    sleeps = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "sleep"]
    assert sleeps == []
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_sms_sent_recently" not in names


def test_auto_pickup_terminates_without_holding_the_line(calling):
    actions = []

    def meta(path, method, payload, phone_number_id=None):
        actions.append(payload.get("action"))
        return {}

    with mock.patch.object(calling, "_meta_api_call", side_effect=meta), \
            mock.patch.object(calling, "_update_call_status"), \
            mock.patch.object(calling, "_get_auto_pickup_audio_url", return_value=None), \
            mock.patch.object(calling.time, "sleep", side_effect=AssertionError("slept")):
        calling._auto_pickup_and_play("wacid.1", "1016149501586345", "919800000004", "")
    assert actions == ["pre_accept", "accept", "terminate"]
