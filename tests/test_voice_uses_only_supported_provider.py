"""Voice runs on the supported stack, and nothing else is declared or deployable.

The supported voice architecture:

    PSTN                Plivo           wecare-plivo-answer   answer/hangup/events, the only
                                                              VoiceCDRTable writer
                                        wecare-pstn-softphone browser softphone
    CDR reads                           wecare-voice-cdr-read GET/DELETE /voice-cdr-read
    AWS voice           End User        wecare-voice-aws      VoiceAwsTable
                        Messaging
    WhatsApp            Meta            wecare-whatsapp-calling, wecare-whatsapp-voice

These are positive invariants: each one states what the tree IS, so anything outside the
supported set fails by not being in it, whatever it is called.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
FUNCTIONS = ROOT / "amplify" / "functions"
MESSAGING = FUNCTIONS / "messaging"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

#: function directory under amplify/functions/messaging -> deployed Lambda name
SUPPORTED_VOICE_FUNCTIONS = {
    "plivo-answer": "wecare-plivo-answer",
    "pstn-softphone": "wecare-pstn-softphone",
    "voice-cdr-read": "wecare-voice-cdr-read",
    "voice-aws": "wecare-voice-aws",
    "whatsapp-calling": "wecare-whatsapp-calling",
    "whatsapp-voice": "wecare-whatsapp-voice",
}
SUPPORTED_LAMBDA_NAMES = set(SUPPORTED_VOICE_FUNCTIONS.values())

#: A name is voice-related when one of its hyphen/slash-separated tokens is one of these.
#: Token matching rather than substring, so `invoice` is not read as `voice`.
VOICE_TOKENS = {"voice", "call", "calls", "calling", "cdr", "pstn", "plivo", "dial",
                "dialer", "ivr", "softphone", "telephony"}

CDR_TABLE = "stack-wecare-digital-VoiceCDRTable"

#: The fields the Call History page (src/pages/workspace/engage/voice-in) reads.
UI_FIELDS = {
    "id", "callUuid", "callerNumber", "destinationNumber", "callerId", "from_number",
    "to_number", "direction", "callType", "overallCallStatus", "call_status",
    "hangupCause", "hangupStatus", "durationSec", "conversationDurationSec",
    "billableDurationSec", "duration_seconds", "createdAt", "timestamp",
}

SKIP_DIRS = {"node_modules", "__pycache__", ".venv"}
TEXT_SUFFIXES = (".py", ".ts", ".json", ".md", ".txt", ".yml", ".yaml", ".sh")
LAMBDA_NAME = re.compile(r"(?<![A-Za-z0-9_-])wecare-[a-z0-9]+(?:-[a-z0-9]+)*")


def _is_voice(name: str) -> bool:
    return bool(VOICE_TOKENS & set(re.split(r"[-/_]", name.lower())))


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _text_files(*bases: str):
    for base in bases:
        for dirpath, dirnames, filenames in os.walk(ROOT / base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                if filename.endswith(TEXT_SUFFIXES):
                    yield Path(dirpath) / filename


# --------------------------------------------------------------------------
# the writer, the reader, and a row that went through both
# --------------------------------------------------------------------------
class _MergingTable:
    """Applies plivo-answer's `update_item` the way DynamoDB would, minus the condition."""

    def __init__(self):
        self.rows = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,  # noqa: N803
                    ExpressionAttributeValues, ConditionExpression=None):
        row = self.rows.setdefault(Key["id"], {"id": Key["id"]})
        for placeholder, name in ExpressionAttributeNames.items():
            value_ref = ":rank" if placeholder == "#rank" else ":v" + placeholder[2:]
            row[name] = ExpressionAttributeValues[value_ref]


class _ScanTable:
    def __init__(self, items):
        self.items = list(items)

    def scan(self, **kwargs):
        return {"Items": [dict(i) for i in self.items]}


class _Dynamo:
    def __init__(self, table):
        self.table = table
        self.names = []

    def Table(self, name):  # noqa: N802 - boto3 spelling
        self.names.append(name)
        return self.table


#: A complete terminal Plivo callback, so every attribute the writer can store is stored.
TERMINAL = {"CallUUID": "u-1", "From": "+919876543210", "To": "+918031830030",
            "Direction": "inbound", "CallStatus": "completed", "Duration": "42",
            "HangupCause": "NORMAL_CLEARING", "HangupSource": "Callee",
            "EndTime": "2026-10-15 06:00:00"}


@pytest.fixture(scope="module")
def writer():
    return _load("voice_invariant_plivo_answer", MESSAGING / "plivo-answer" / "handler.py")


@pytest.fixture(scope="module")
def reader():
    return _load("voice_invariant_cdr_read", MESSAGING / "voice-cdr-read" / "handler.py")


@pytest.fixture
def stored_row(writer, monkeypatch):
    """The VoiceCDRTable row plivo-answer stores for TERMINAL."""
    table = _MergingTable()
    monkeypatch.setattr(writer, "_table", lambda: table)
    import lambda_utils.message_store as ms
    monkeypatch.setattr(ms, "put_call_breadcrumb", lambda **kw: None)
    assert writer._persist_cdr(dict(TERMINAL), "hangup", "req-1") is True
    return dict(table.rows["plivo#u-1"])


def _read(reader, monkeypatch, items, **query):
    dynamo = _Dynamo(_ScanTable(items))
    monkeypatch.setattr(reader, "dynamodb", dynamo)
    # An internal invoke: no API Gateway context, so require_auth admits it.
    response = reader.handler({"httpMethod": "GET", "queryStringParameters": query}, None)
    assert response["statusCode"] == 200, response
    return json.loads(response["body"]), dynamo


# --------------------------------------------------------------------------
# the set of voice Lambdas
# --------------------------------------------------------------------------
def test_the_voice_lambdas_are_exactly_the_supported_set():
    """Every voice handler in the tree is a supported one, and every supported one exists."""
    found = set()
    for handler in MESSAGING.rglob("handler.py"):
        if "__pycache__" in handler.parts:
            continue
        rel = handler.parent.relative_to(MESSAGING).as_posix()
        if _is_voice(rel):
            found.add(rel)
    assert found == set(SUPPORTED_VOICE_FUNCTIONS), (
        f"unexpected: {sorted(found - set(SUPPORTED_VOICE_FUNCTIONS))}, "
        f"missing: {sorted(set(SUPPORTED_VOICE_FUNCTIONS) - found)}")


def test_no_infrastructure_or_config_file_names_another_voice_function():
    """amplify/ and config/ name voice Lambdas from the supported set only."""
    offenders = {}
    for path in _text_files("amplify", "config"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in LAMBDA_NAME.finditer(text):
            name = match.group(0)
            if _is_voice(name[len("wecare-"):]) and name not in SUPPORTED_LAMBDA_NAMES:
                offenders.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    assert offenders == {}, offenders


def test_the_env_manifest_records_only_supported_voice_functions():
    manifest = json.loads((ROOT / "config" / "lambda-env-manifest.json").read_text())
    voice = {fn for fn in manifest["functions"] if _is_voice(fn[len("wecare-"):])}
    assert voice <= SUPPORTED_LAMBDA_NAMES, sorted(voice - SUPPORTED_LAMBDA_NAMES)
    assert manifest["_functions"] == len(manifest["functions"])
    assert manifest["_variables"] == sum(len(v) for v in manifest["functions"].values())


def test_iam_policy_keys_for_voice_functions_are_supported():
    text = (ROOT / "amplify" / "iam-policies.ts").read_text()
    block = text.split("export const FUNCTION_POLICIES", 1)[1]
    keys = set(re.findall(r"^\s*'(wecare-[a-z0-9-]+)':\s*\[", block, re.M))
    voice = {k for k in keys if _is_voice(k[len("wecare-"):])}
    assert voice <= SUPPORTED_LAMBDA_NAMES, sorted(voice - SUPPORTED_LAMBDA_NAMES)
    # The CDR writer and reader are both declared, so their grants are visible.
    assert {"wecare-plivo-answer", "wecare-voice-cdr-read"} <= voice


# --------------------------------------------------------------------------
# one CDR writer, one CDR reader
# --------------------------------------------------------------------------
def test_plivo_answer_is_the_only_cdr_writer():
    """Modules that address VoiceCDRTable, and which of them can write it."""
    addressing = set()
    for path in FUNCTIONS.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "VoiceCDRTable" in text or "VOICE_CDR_TABLE" in text:
            addressing.add(path.relative_to(FUNCTIONS).as_posix())
    assert addressing == {
        "messaging/plivo-answer/handler.py",       # the writer
        "messaging/voice-cdr-read/handler.py",     # the reader (DELETE clears)
        "operations/system-cleanup/handler.py",    # preview count only; protected
    }, sorted(addressing)

    writes = re.compile(r"\.(put_item|update_item)\(")
    for rel in sorted(addressing):
        source = (FUNCTIONS / rel).read_text()
        if rel == "messaging/plivo-answer/handler.py":
            assert writes.search(source), "the writer no longer writes"
        else:
            assert not writes.search(source), f"{rel} writes; plivo-answer is the only writer"


def test_system_cleanup_cannot_wipe_the_cdr_table():
    path = FUNCTIONS / "operations" / "system-cleanup" / "handler.py"
    with patch("boto3.resource", MagicMock()), patch("boto3.client", MagicMock()):
        cleanup = _load("voice_invariant_system_cleanup", path)
    assert CDR_TABLE not in cleanup.CLEANUP_ALLOWLIST
    assert cleanup._table_protected_reason(CDR_TABLE)


def test_the_writer_stores_plivo_rows(stored_row):
    assert stored_row["source"] == "plivo"
    assert stored_row["id"] == "plivo#u-1"
    assert stored_row["callUuid"] == "u-1"


def test_the_reader_addresses_only_the_cdr_table(reader, monkeypatch, stored_row):
    source = (MESSAGING / "voice-cdr-read" / "handler.py").read_text()
    assert set(re.findall(r"stack-wecare-digital-[A-Za-z0-9]+", source)) == {CDR_TABLE}
    assert set(re.findall(r"os\.environ\.get\('([A-Z_]+_TABLE)'", source)) == {"VOICE_CDR_TABLE"}

    _, dynamo = _read(reader, monkeypatch, [stored_row])
    assert dynamo.names and set(dynamo.names) == {CDR_TABLE}


def test_the_reader_emits_exactly_what_the_writer_stores(reader, monkeypatch, stored_row):
    """The record carries the writer's attribute set: nothing dropped, nothing invented."""
    foreign = dict(stored_row, someOtherWritersField="x", participantsJson="[]")
    body, _ = _read(reader, monkeypatch, [foreign])
    (record,) = body["records"]
    assert set(record) == set(stored_row)
    assert set(reader.CDR_FIELDS) == set(stored_row)


def test_the_call_history_fields_keep_their_names_and_values(reader, monkeypatch, stored_row):
    body, _ = _read(reader, monkeypatch, [stored_row])
    (record,) = body["records"]
    assert UI_FIELDS <= set(record)
    for name in UI_FIELDS - {"direction"}:
        expected = stored_row[name]
        if isinstance(expected, Decimal):
            assert record[name] == float(expected), name
        else:
            assert record[name] == expected, name
    # The UI's direction filter compares against INBOUND / OUTBOUND.
    assert record["direction"] == "INBOUND"


def test_hangup_cause_and_hangup_party_are_not_swapped(reader, monkeypatch, stored_row):
    body, _ = _read(reader, monkeypatch, [stored_row])
    (record,) = body["records"]
    assert record["hangupCause"] == "NORMAL_CLEARING"
    assert record["hangupStatus"] == "Callee"
    assert body["stats"]["byHangupCause"] == {"NORMAL_CLEARING": 1}
    assert body["stats"]["byHangupStatus"] == {"Callee": 1}


def test_outbound_api_calls_read_as_outbound(reader, monkeypatch, writer):
    table = _MergingTable()
    monkeypatch.setattr(writer, "_table", lambda: table)
    import lambda_utils.message_store as ms
    monkeypatch.setattr(ms, "put_call_breadcrumb", lambda **kw: None)
    writer._persist_cdr(dict(TERMINAL, CallUUID="u-2", Direction="outbound-api",
                             CallStatus="no-answer", Duration="0"), "hangup", "r")
    body, _ = _read(reader, monkeypatch, list(table.rows.values()))
    (record,) = body["records"]
    assert record["direction"] == "OUTBOUND"
    assert record["callType"] == "OUTBOUND"
    assert record["overallCallStatus"] == "Missed"


def test_response_is_records_count_and_stats_only(reader, monkeypatch, stored_row):
    body, _ = _read(reader, monkeypatch, [stored_row])
    assert set(body) == {"records", "count", "stats"}
    stats = body["stats"]
    assert stats["total"] == 1 and stats["inbound"] == 1 and stats["answered"] == 1
    assert stats["byCallType"] == {"INBOUND": 1}
    assert stats["byStatus"] == {"Answered": 1}
    assert stats["avgConversationDuration"] == 42.0
    assert stats["totalBillable"] == 42.0

    dashboard_body, _ = _read(reader, monkeypatch, [stored_row], dashboard="true")
    dashboard = dashboard_body["dashboard"]
    assert set(dashboard) == {"callTrend", "avgConversationDuration",
                              "avgConversationDurationSec", "callVolumeByCli"}
    assert dashboard["callVolumeByCli"][0]["callerId"] == stored_row["callerId"]


def test_delete_with_clear_all_still_clears(reader, monkeypatch):
    calls = []
    monkeypatch.setattr(reader, "_clear_cdr_logs", lambda rid: calls.append(rid) or {
        "statusCode": 200, "body": json.dumps({"success": True, "totalDeleted": 3})})
    response = reader.handler({"httpMethod": "DELETE", "body": json.dumps({"clearAll": True})},
                              None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["totalDeleted"] == 3
    assert len(calls) == 1


# --------------------------------------------------------------------------
# the declaration matches the writer
# --------------------------------------------------------------------------
def test_the_voice_cdr_model_declares_exactly_the_written_fields(stored_row):
    text = (ROOT / "amplify" / "data" / "resource.ts").read_text()
    block = text.split("\n  VoiceCDR: a\n", 1)[1].split("\n    } )", 1)[0]
    declared = set(re.findall(r"^      (\w+): a\.", block, re.M))
    assert declared == set(stored_row), (
        f"undeclared: {sorted(set(stored_row) - declared)}, "
        f"not written: {sorted(declared - set(stored_row))}")


def test_no_generic_voice_call_model_is_declared():
    """Voice records are VoiceCDR, VoiceAws and WhatsAppCalling; there is no fourth store."""
    text = (ROOT / "amplify" / "data" / "resource.ts").read_text()
    models = set(re.findall(r"^  ([A-Z][A-Za-z0-9]*): a$", text, re.M))
    voice_models = {m for m in models
                    if re.search(r"Voice|Call|Pstn|Cdr|CDR", m)}
    assert voice_models == {"VoiceCDR", "VoiceAws", "WhatsAppVoice", "WhatsAppCalling"}, \
        sorted(voice_models)
