"""MSG-7: an unsupported or new message type is logged by shape, never by content."""
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
    sys.path.insert(0, str(HANDLER.parent))
    spec = importlib.util.spec_from_file_location("inbound_unsupported_log_under_test", HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(HANDLER.parent))
        sys.modules.pop(spec.name, None)


def test_unsupported_type_logs_type_keys_and_masked_sender_only(inbound, caplog):
    message = {
        "id": "wamid.NEW", "from": "919812345678", "timestamp": "1700000000",
        "type": "brand_new_type",
        "brand_new_type": {"secret_field": "private-value-marker"},
        "text": {"body": "private-body-marker"},
    }
    # Stop right after the type check: nothing is stored or sent.
    with mock.patch.object(inbound.message_dedup, "should_skip_duplicate", return_value=True):
        inbound._process_message(
            message=message, metadata={"phone_number_id": "1016149501586345"},
            request_id="req", receiving_phone="", aws_phone_number_id="",
            meta_waba_ids=["2094615664435155"])
    [line] = [json.loads(r.message) for r in caplog.records
              if "unsupported_or_new_message_type" in r.message]
    assert line["messageType"] == "brand_new_type"
    assert line["typeKeys"] == ["secret_field"]
    assert "fullMessage" not in line
    assert "private-value-marker" not in caplog.text
    assert "private-body-marker" not in caplog.text
    assert "919812345678" not in caplog.text
