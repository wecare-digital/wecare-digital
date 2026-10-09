"""Official history chunks/media enrichment must never enter live automation.

Meta history reference documents a media-enrichment envelope with value.messages
and field=history. Its resemblance to live messages must not cause welcome,
receipt, contact creation, invoice work or customer message writes.
"""
from pathlib import Path
import importlib.util
import os
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(os.environ.get("WECARE_TEST_REPO_ROOT", Path(__file__).resolve().parents[1]))
HANDLER_PATH = Path(os.environ.get("WECARE_INBOUND_HANDLER_PATH", ROOT /
    "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"))


def _harness():
    path = ROOT / "tests/test_coexistence_and_partner_webhooks.py"
    spec = importlib.util.spec_from_file_location("_history_replay_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness_and_handler():
    harness = _harness()
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        handler = harness._load_by_path("history_replay_handler", str(HANDLER_PATH),
            (harness.INBOUND_HANDLER_DIR, os.path.join(harness.INBOUND_HANDLER_DIR, "modules")))
    return harness, handler


def _entry(kind):
    value = {"messaging_product": "whatsapp", "metadata": {
        "display_phone_number": "15550000001", "phone_number_id": "phone-history-fixture"}}
    message = {"from": "15550000002", "id": "wamid.history-fixture",
               "timestamp": "1738796547", "type": "image",
               "image": {"id": "media-fixture", "mime_type": "image/jpeg"}}
    if kind == "media_enrichment":
        value["messages"] = [message]
    elif kind == "canonical_chunk":
        value["history"] = [{"metadata": {"phase": 0, "chunk_order": 1, "progress": 55},
            "threads": [{"id": "15550000002", "messages": [message]}]}]
    else:
        value["history"] = [{"errors": [{"code": 2593109}]}]
    # Adversarial adjacent fields must not make a replay into live traffic.
    value["statuses"] = [{"id": "wamid.history-fixture", "status": "read"}]
    return {"id": "messaging-account-history-fixture",
            "changes": [{"field": "history", "value": value}]}


@pytest.mark.parametrize("kind", ["media_enrichment", "canonical_chunk", "sharing_declined"])
@pytest.mark.parametrize("requested_ingest", ["false", "true"])
def test_history_is_audited_once_without_processing_writes_or_sends(
        harness_and_handler, kind, requested_ingest):
    harness, handler = harness_and_handler
    with patch.object(handler, "_process_message", MagicMock()) as process_message, \
            patch.object(handler, "_process_status", MagicMock()) as process_status, \
            patch.object(handler, "_get_aws_phone_number_id", MagicMock()) as phone_lookup:
        run = harness._drive(handler, _entry(kind),
            env={"COEXISTENCE_INGEST_ENABLED": requested_ingest})
    process_message.assert_not_called()
    process_status.assert_not_called()
    phone_lookup.assert_not_called()
    assert harness._message_table_writes(handler, run) == []
    run["put_message"].assert_not_called()
    run["urlopen"].assert_not_called()
    run["lambda_client"].invoke.assert_not_called()
    tables = run["dynamo"].tables
    assert all(not t.update_calls and not t.delete_calls for t in tables.values())
    audit = run["dynamo"].writes(handler.SYSTEM_CONFIG_TABLE)
    assert len(audit) == 1
    assert len(run["logs"].named("webhook_history_stored")) == 1
    assert run["result"]["statusCode"] == 200
