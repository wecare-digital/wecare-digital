"""The assistant's `get_voice_cdr` tool reads what wecare-voice-cdr-read actually returns.

It used to read `status`, `conversationDuration`, `startTime` and `stats.totalCalls`.
The reader emits none of those, so every summary row said N/A and the call total was
always 0 while the tool reported success.

The tool is exercised against the REAL reader handler: the fake Lambda client runs
voice-cdr-read over a fake VoiceCDRTable holding rows in the shape plivo-answer writes,
so the contract is checked end to end rather than against a hand-written response.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

AI_HANDLER = ROOT / "amplify" / "functions" / "ai" / "ai-generate-response" / "handler.py"
READER = ROOT / "amplify" / "functions" / "messaging" / "voice-cdr-read" / "handler.py"


def _plivo_row(uuid, *, direction, status, overall, seconds, created_at,
               caller="+919876543210", destination="+918031830030"):
    """A VoiceCDRTable row as plivo-answer._persist_cdr stores it."""
    call_type = "INBOUND" if direction.startswith("in") else "OUTBOUND"
    return {
        "id": f"plivo#{uuid}", "source": "plivo", "route": "hangup",
        "cdrRank": Decimal("40"), "callUuid": uuid, "call_uuid": uuid,
        "from_number": caller, "to_number": destination, "direction": direction,
        "call_status": status, "hangup_cause": "NORMAL_CLEARING",
        "hangup_source": "Callee", "duration_seconds": str(seconds),
        "end_time": "2026-10-15 06:00:00", "received_at": created_at,
        "createdAt": Decimal(str(created_at)), "timestamp": "2026-10-15 05:59:18",
        "callerNumber": caller, "destinationNumber": destination,
        "callerId": destination if call_type == "INBOUND" else caller,
        "callType": call_type, "overallCallStatus": overall,
        "hangupCause": "NORMAL_CLEARING", "hangupStatus": "Callee",
        "durationSec": Decimal(str(seconds)), "durationMs": Decimal(str(seconds * 1000)),
        "conversationDurationSec": Decimal(str(seconds)),
        "conversationDurationMs": Decimal(str(seconds * 1000)),
        "billableDurationSec": Decimal(str(seconds)),
        "billableDurationMs": Decimal(str(seconds * 1000)),
        "expiresAt": Decimal(str(created_at + 90 * 86400)),
    }


ROWS = [
    _plivo_row("u-answered", direction="inbound", status="completed", overall="Answered",
               seconds=42, created_at=1_760_500_000),
    _plivo_row("u-missed", direction="outbound-api", status="no-answer", overall="Missed",
               seconds=0, created_at=1_760_400_000),
]


class _Table:
    def scan(self, **kwargs):
        return {"Items": [dict(r) for r in ROWS]}


class _Dynamo:
    def Table(self, name):  # noqa: N802 - boto3 spelling
        assert name == "stack-wecare-digital-VoiceCDRTable"
        return _Table()


@pytest.fixture
def reader(monkeypatch):
    spec = importlib.util.spec_from_file_location("ai_tool_voice_cdr_read", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "dynamodb", _Dynamo())
    return module


class _LambdaRunningTheReader:
    """`lambda_client.invoke` that runs voice-cdr-read in-process."""

    def __init__(self, reader, override=None):
        self.reader = reader
        self.override = override
        self.calls = []

    def invoke(self, FunctionName, InvocationType, Payload):  # noqa: N803
        self.calls.append((FunctionName, InvocationType, json.loads(Payload)))
        result = self.override or self.reader.handler(json.loads(Payload), None)
        return {"Payload": io.BytesIO(json.dumps(result).encode())}


def _tool(lambda_client):
    """`_tool_get_voice_cdr` compiled on its own, with only the names it uses."""
    tree = ast.parse(AI_HANDLER.read_text())
    (fn,) = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "_tool_get_voice_cdr"]
    scope = {"Dict": dict, "json": json, "lambda_client": lambda_client}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(AI_HANDLER), "exec"), scope)
    return scope["_tool_get_voice_cdr"]


def test_the_tool_invokes_the_cdr_reader_as_an_internal_get(reader):
    client = _LambdaRunningTheReader(reader)
    _tool(client)({"callType": "INBOUND", "limit": 5}, "req-1")
    (name, invocation, payload), = client.calls
    assert name == "wecare-voice-cdr-read"
    assert invocation == "RequestResponse"
    assert payload["httpMethod"] == "GET"
    assert payload["queryStringParameters"] == {"callType": "INBOUND", "limit": "5"}
    assert "requestContext" not in payload  # internal invoke, admitted by require_auth


def test_status_and_total_come_from_fields_the_reader_emits(reader):
    result = _tool(_LambdaRunningTheReader(reader))({}, "req-1")
    assert result["success"] is True
    assert result["totalRecords"] == 2
    assert result["stats"] == {"totalCalls": 2, "answered": 1, "missed": 1}

    answered, missed = result["records"]   # newest first
    assert answered["status"] == "Answered"
    assert missed["status"] == "Missed"
    assert answered["duration"] == "00:42"
    assert missed["duration"] == "00:00"
    assert answered["direction"] == "INBOUND"
    assert missed["direction"] == "OUTBOUND"
    assert answered["caller"] == "+919876543210"
    assert answered["destination"] == "+918031830030"
    assert answered["time"] == "2026-10-15 05:59:18 UTC"
    for row in result["records"]:
        assert "N/A" not in row.values(), row


def test_raw_call_status_is_the_fallback_when_no_overall_status_was_mapped(reader, monkeypatch):
    row = dict(ROWS[0])
    del row["overallCallStatus"]
    monkeypatch.setattr(sys.modules[__name__], "ROWS", [row])
    result = _tool(_LambdaRunningTheReader(reader))({}, "req-1")
    assert result["records"][0]["status"] == "completed"


def test_a_failed_read_is_reported_as_a_failure(reader):
    failing = {"statusCode": 500, "body": json.dumps({"error": "boom"})}
    result = _tool(_LambdaRunningTheReader(reader, override=failing))({}, "req-1")
    assert result == {"success": False, "error": "boom"}


def test_the_tool_description_uses_the_readers_status_vocabulary():
    source = AI_HANDLER.read_text()
    spec = source.split("'name': 'get_voice_cdr'", 1)[1].split("'toolSpec'", 1)[0]
    assert "Answered, Missed or Busy" in spec
    assert "Disconnected" not in spec
