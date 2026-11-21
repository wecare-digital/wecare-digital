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


def _event(field):
    entry = {
        "id": "waba-1",
        "changes": [{
            "field": field,
            "value": {
                "metadata": {"display_phone_number": "15550001111", "phone_number_id": "111"},
                "standby": {
                    "contacts": [{"wa_id": "919999999999", "profile": {"name": "Test"}}],
                    "messages": [{"id": "wamid.X", "from": "919999999999",
                                  "timestamp": "1700000000", "type": "text",
                                  "text": {"body": "hello"}}],
                },
            },
        }],
    }
    return {
        "source": "meta-direct", "version": 1, "entry": entry, "wabaId": "waba-1",
        "metaPhoneNumberIds": ["111"], "requestId": "req-1",
    }


@pytest.mark.parametrize("field", ["standby", "messaging_handovers"])
def test_standby_webhook_returns_200_and_writes_nothing(inbound, field):
    ctx = mock.Mock()
    ctx.get_remaining_time_in_millis.return_value = 120000
    ctx.aws_request_id = "req-1"
    item = {"waba_ids": ["waba-1"], "phone_number_ids": ["111"], "message_id": "m1",
            "entry": _event(field)["entry"], "shape": "typed"}
    with mock.patch.object(inbound.wa_internal_event, "parse", return_value=[item]), \
            mock.patch.object(inbound, "dynamodb") as ddb, \
            mock.patch.object(inbound, "lambda_client") as lam, \
            mock.patch.object(inbound, "_process_message") as process:
        result = inbound.handler(_event(field), ctx)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["errors"] == 0
    process.assert_not_called()
    assert ddb.mock_calls == []
    assert lam.mock_calls == []
