"""Exercise the authenticated messages handler against an in-memory Query adapter."""
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from lambda_utils import middleware


PATH = Path(__file__).resolve().parents[2] / "amplify/functions/core/messages-read/handler.py"
SPEC = importlib.util.spec_from_file_location("inbox_messages_read", PATH)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)


class FakeTable:
    def __init__(self, rows, fail_channels=()):
        self.rows = rows
        self.fail_channels = set(fail_channels)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        key, value = kwargs["KeyConditionExpression"].get_expression()["values"]
        if value in self.fail_channels:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Query")
        rows = sorted((row for row in self.rows if row[key.name] == value),
                      key=lambda row: (row["timestamp"], row["id"]), reverse=True)
        if start := kwargs.get("ExclusiveStartKey"):
            assert isinstance(start["timestamp"], Decimal)
            n = next(i for i, row in enumerate(rows) if row["id"] == start["id"])
            rows = rows[n + 1:]
        limit = kwargs["Limit"]
        page = rows[:limit]
        result = {"Items": page}
        if len(rows) > limit:
            item = page[-1]
            result["LastEvaluatedKey"] = {k: item[k] for k in ("timestamp", "id", key.name)}
        return result


def row(mid, ts, channel="whatsapp", contact="a"):
    return {"id": str(mid), "timestamp": Decimal(ts), "contactId": contact,
            "channel": channel, "content": "synthetic", "direction": "inbound"}


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(middleware, "require_auth", lambda *_: None)

    def request(table, **params):
        monkeypatch.setattr(HANDLER.dynamodb, "Table", lambda *_: table)
        event = {
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {"view": "inbox", **params},
        }
        result = HANDLER.handler(event, None)
        return result["statusCode"], json.loads(result["body"])

    return request


def test_thread_has_no_2000_row_ceiling_and_preserves_native_cursor(run):
    table = FakeTable([row(i, i) for i in range(2117)] + [row("other", 2200, contact="b")])
    cursor, seen = None, []
    while True:
        params = {"contactId": "a", "limit": "80"}
        if cursor:
            params["cursor"] = cursor
        status, page = run(table, **params)
        assert status == 200 and not page["unavailableChannels"]
        assert len(page["messages"]) <= 80
        seen.extend(int(item["id"]) for item in page["messages"])
        cursor = page["nextCursor"]
        if not cursor:
            break
        assert len(seen) <= 2117
    assert seen == list(range(2116, -1, -1))
    assert all(call["IndexName"] == "contactId-index" for call in table.calls)


def test_overview_reports_failed_partition_and_continues_without_skips(run):
    table = FakeTable([row(f"w{i}", i) for i in range(22)] + [row("s1", 51, "sms")], {"sms"})
    status, first = run(table, limit="50")
    assert status == 200 and first["unavailableChannels"] == ["sms"]
    assert len(first["messages"]) == 10 and first["nextCursor"]
    table.fail_channels.clear()
    seen = [msg["id"] for msg in first["messages"]]
    cursor = first["nextCursor"]
    for _ in range(3):
        if not cursor:
            break
        status, page = run(table, limit="50", cursor=cursor)
        assert status == 200 and not page["unavailableChannels"]
        seen.extend(msg["id"] for msg in page["messages"])
        cursor = page["nextCursor"]
    assert len(seen) == 23 and set(seen) == {"s1", *(f"w{i}" for i in range(22))}
    assert not cursor
    assert all(call["IndexName"] == "channel-index" for call in table.calls)


def test_scope_mismatch_and_bad_cursor_refused_before_query(run):
    table = FakeTable([row(i, i) for i in range(3)])
    _, first = run(table, contactId="a", limit="1")
    assert run(table, contactId="b", cursor=first["nextCursor"])[0] == 400
    assert run(table, cursor="not-a-cursor")[0] == 400
    assert len(table.calls) == 1


def test_full_unavailability_is_not_empty_success(run):
    table = FakeTable([], {"whatsapp", "sms", "rcs", "email", "voice"})
    assert run(table)[0] == 503
    assert run(table, channel="sms")[0] == 503


def test_overview_does_not_resolve_saved_contact_media_and_limits_preview(run, monkeypatch):
    item = {**row("media", 10), "content": "x" * 400, "s3Key": "synthetic",
            "flowAnswers": [{"question": "not for previews", "answer": "synthetic"}]}
    monkeypatch.setattr(HANDLER, "_find_actual_s3_key", lambda *args: pytest.fail("preview resolved S3"))
    status, page = run(FakeTable([item]))
    assert status == 200
    preview = page["messages"][0]
    assert preview["content"] == "x" * 240
    assert "s3Key" not in preview and "flowAnswers" not in preview
