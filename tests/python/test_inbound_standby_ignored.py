"""A `standby` or `messaging_handovers` webhook is acknowledged and ignored.

Both fields only existed for the removed Meta Business AI agent. The inbound worker
must answer 200, write nothing and send nothing if Meta still delivers them.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py")


@pytest.fixture(scope="module")
def inbound():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    sys.path.insert(0, str(HANDLER.parent))  # the handler imports its sibling `modules` package
    spec = importlib.util.spec_from_file_location("inbound_whatsapp_handler_under_test", HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(HANDLER.parent))
        sys.modules.pop(spec.name, None)


def _context():
    ctx = mock.Mock()
    ctx.get_remaining_time_in_millis.return_value = 120000
    ctx.aws_request_id = "req-1"
    return ctx


def _event(field, waba="waba-1"):
    entry = {
        "id": waba,
        "changes": [{
            "field": field,
            "value": {
                "metadata": {"display_phone_number": "15550001111", "phone_number_id": "111"},
                "contacts": [{
                    "wa_id": "919999999999",
                    "user_id": "profile-bsuid", "parent_user_id": "profile-parent",
                    "profile": {"name": "Test", "username": "test-user", "contact_book_name": "Book"},
                }],
                "messages": [{"id": "wamid.X", "from": "919999999999",
                              "from_user_id": "message-bsuid",
                              "timestamp": "1700000000", "type": "text",
                              "text": {"body": "private-body-marker"}}],
                "statuses": [{"id": "wamid.X", "status": "delivered"}],
            },
        }],
    }
    return {
        "source": "meta-direct", "version": 1, "entry": entry, "wabaId": waba,
        "metaPhoneNumberIds": ["111"], "requestId": "req-1",
    }


@pytest.mark.parametrize("field", ["standby", "messaging_handovers"])
@pytest.mark.parametrize("case", [0, 1, "untrusted-value"])
def test_standby_webhook_returns_200_and_writes_nothing(inbound, caplog, field, case):
    owned = list(inbound.direct_send.META_PHONE_TO_WABA.values())
    waba = owned[case] if isinstance(case, int) else case
    with mock.patch.object(inbound, "dynamodb") as ddb, \
            mock.patch.object(inbound, "lambda_client") as lam, \
            mock.patch.object(inbound, "_process_message") as process, \
            mock.patch.object(inbound, "_process_status") as status, \
            mock.patch.object(inbound, "_send_to_dlq") as dlq:
        result = inbound.handler(_event(field, waba), _context())
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"errors": 0, "processed": 0}
    process.assert_not_called()
    status.assert_not_called()
    dlq.assert_not_called()
    assert ddb.mock_calls == []
    assert lam.mock_calls == []
    [signal] = [json.loads(r.message) for r in caplog.records
                if "webhook_field_ignored" in r.message]
    assert signal == {
        "event": "webhook_field_ignored",
        "field": field,
        "requestId": "req-1",
        "wabaId": waba if waba in owned else "unknown-or-partner",
    }
    assert "private-body-marker" not in caplog.text
    assert "919999999999" not in caplog.text
    assert "untrusted-value" not in caplog.text


@pytest.mark.parametrize("field, hook", [
    ("smb_app_state_sync", "_process_coexistence_event"),
    ("smb_message_echoes", "_process_coexistence_event"),
    ("history", "_process_history_event"),
])
def test_replay_fields_reach_only_the_replay_lane(inbound, field, hook):
    with mock.patch.object(inbound, "_process_message") as process, \
            mock.patch.object(inbound, "_process_status") as status, \
            mock.patch.object(inbound, "_get_aws_phone_number_id") as phone, \
            mock.patch.object(inbound, hook) as replay:
        result = inbound.handler(_event(field), _context())
    assert json.loads(result["body"]) == {"errors": 0, "processed": 0}
    process.assert_not_called()
    status.assert_not_called()
    phone.assert_not_called()
    replay.assert_called_once()


@pytest.mark.parametrize("succeeds", [True, False])
def test_real_worker_completes_message_lease_only_after_success(inbound, succeeds):
    from lambda_utils import webhook_dedup

    timeline = []

    def process(**kwargs):
        assert kwargs["sender_bsuid"] == "message-bsuid"
        assert kwargs["sender_parent_bsuid"] == "profile-parent"
        assert kwargs["sender_profile_name"] == "Test"
        assert kwargs["sender_username"] == "test-user"
        assert kwargs["sender_contact_book_name"] == "Book"
        kwargs["dedup_tracker"].append(kwargs["message"]["id"])
        timeline.append("processed")
        if not succeeds:
            raise RuntimeError("synthetic processing failure")

    def complete(message_id):
        assert message_id == "wamid.X"
        timeline.append("completed")

    with mock.patch.object(inbound, "_process_message", side_effect=process), \
            mock.patch.object(inbound, "_process_status") as status, \
            mock.patch.object(webhook_dedup, "complete_event", side_effect=complete):
        result = inbound.handler(_event("messages"), _context())
    assert json.loads(result["body"]) == {"errors": int(not succeeds), "processed": int(succeeds)}
    assert timeline == (["processed", "completed"] if succeeds else ["processed"])
    status.assert_called_once()


@pytest.mark.parametrize("lease, exists, skip, completed, tracked", [
    (True, False, False, False, True),
    (True, True, True, True, False),
    (False, False, True, False, False),
    (RuntimeError("unavailable"), False, False, False, False),
])
def test_duplicate_policy_keeps_lease_and_persisted_row_fallback(
        inbound, lease, exists, skip, completed, tracked):
    from lambda_utils import webhook_dedup

    tracker = []
    message_exists = mock.Mock(return_value=exists)
    kwargs = {"side_effect" if isinstance(lease, Exception) else "return_value": lease}
    with mock.patch.object(webhook_dedup, "claim_event_with_lease", **kwargs) as claim, \
            mock.patch.object(webhook_dedup, "complete_event") as complete:
        assert inbound.message_dedup.should_skip_duplicate(
            "wamid.X", message_exists=message_exists, dedup_tracker=tracker,
            logger=inbound.logger, request_id="req-1",
        ) is skip
    claim.assert_called_once_with("wamid.X", source="whatsapp_inbound")
    if lease is False:
        message_exists.assert_not_called()
    else:
        message_exists.assert_called_once_with("wamid.X")
    assert complete.call_args_list == ([mock.call("wamid.X")] if completed else [])
    assert tracker == (["wamid.X"] if tracked else [])
