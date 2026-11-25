"""Exercise the authenticated messages handler against an in-memory Query adapter."""
from base64 import urlsafe_b64encode
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from lambda_utils import middleware
from lambda_utils.inbox_timeline_indexes import INDEXES, LEGACY_INDEXES, index_definition


PATH = Path(__file__).resolve().parents[2] / "amplify/functions/core/messages-read/handler.py"
SPEC = importlib.util.spec_from_file_location("inbox_messages_read", PATH)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)


def describe(*, active=("channel", "contactId"), backfilling=()):
    timeline = [
        {**index_definition(key), "IndexStatus": "ACTIVE",
         **({"Backfilling": True} if key in backfilling else {})}
        for key in active
    ]
    return {
        "TableStatus": "ACTIVE",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in (("id", "S"), ("channel", "S"), ("contactId", "S"), ("timestamp", "N"))
        ],
        "GlobalSecondaryIndexes": timeline,
    }


class FakeTable:
    name = "canonical-test"

    def __init__(self, rows, fail_channels=(), schema=None):
        self.rows = rows
        self.fail_channels = set(fail_channels)
        self.calls, self.scans, self.describes = [], [], []
        self.schema = schema if schema is not None else describe()
        self.meta = SimpleNamespace(client=SimpleNamespace(describe_table=self._describe))

    def _describe(self, **kwargs):
        self.describes.append(kwargs)
        return {"Table": self.schema}

    @staticmethod
    def _matches(row, condition):
        if condition is None:
            return True
        expression = condition.get_expression()
        if expression["operator"] == "AND":
            return all(FakeTable._matches(row, term) for term in expression["values"])
        key, value = expression["values"]
        return row.get(key.name) == value

    def scan(self, **kwargs):
        self.scans.append(kwargs)
        rows = self.rows[:kwargs["Limit"]]
        return {"Items": [row for row in rows if self._matches(row, kwargs.get("FilterExpression"))]}

    def query(self, **kwargs):
        self.calls.append(kwargs)
        index = kwargs["IndexName"]
        key, value = kwargs["KeyConditionExpression"].get_expression()["values"]
        if value in self.fail_channels:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Query")
        rows = [row for row in self.rows if row.get(key.name) == value]
        if index in INDEXES.values() or (
            index in LEGACY_INDEXES.values() and kwargs.get("ScanIndexForward") is False
        ):
            assert kwargs["ScanIndexForward"] is False
            rows.sort(key=lambda row: (row["timestamp"], row["id"]), reverse=True)
        elif index == "contactId-index":
            # A legacy HASH-only index need not return chronological data.
            assert "ScanIndexForward" not in kwargs
            if not any(g["IndexName"] == index for g in self.schema.get("GlobalSecondaryIndexes", [])):
                raise ClientError({"Error": {"Code": "ValidationException",
                                             "Message": f"The table does not have the specified index: {index}"}}, "Query")
        else:
            pytest.fail(f"Unexpected index {index}")
        if start := kwargs.get("ExclusiveStartKey"):
            assert isinstance(start["timestamp"], Decimal)
            n = next(i for i, row in enumerate(rows) if row["id"] == start["id"])
            rows = rows[n + 1:]
        limit = kwargs["Limit"]
        page = rows[:limit]
        result = {"Items": [row for row in page if self._matches(row, kwargs.get("FilterExpression"))]}
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
    monkeypatch.setenv("INBOX_TIMELINE_INDEXES_ENABLED", "true")
    monkeypatch.setattr(HANDLER, "_TIMELINE_STATUS", {})

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
    assert all(call["IndexName"] == INDEXES["contactId"] for call in table.calls)


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
    assert all(call["IndexName"] == INDEXES["channel"] for call in table.calls)


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


def test_cross_channel_thread_pages_globally_ordered_including_equal_timestamps(run):
    table = FakeTable([
        row("first", 1), row("tied-sms", 98, "sms"), row("tied-rcs", 98, "rcs"),
        row("old-rcs", 12, "rcs"), row("new-sms", 100, "sms"), row("recent-wa", 82),
    ])
    cursor, received = None, []
    for _ in range(6):
        params = {"contactId": "a", "limit": "2"}
        if cursor:
            params["cursor"] = cursor
        status, page = run(table, **params)
        assert status == 200 and page["historyMode"] == "paged"
        received.extend((m["id"], m["timestamp"]) for m in page["messages"])
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert [ts for _, ts in received] == [100, 98, 98, 82, 12, 1]
    assert len({mid for mid, _ in received}) == 6
    assert len(table.describes) == 1


def test_fresh_environment_missing_indexes_uses_bounded_sample_without_cursor(run):
    table = FakeTable([row("visible", 1), *[row(i, i, contact="b") for i in range(301)]],
                      schema=describe(active=()))
    status, page = run(table, limit="20")
    assert status == 200 and page["historyMode"] == "sampled"
    assert page["nextCursor"] is None and len(page["messages"]) == 20
    assert not table.calls and len(table.scans) == 1 and table.scans[0]["Limit"] == 300
    assert run(table, cursor="stale")[0] == 409
    assert len(table.scans) == 1

    status, page = run(table, contactId="a")
    assert status == 200 and page["historyMode"] == "sampled"
    assert [m["id"] for m in page["messages"]] == ["visible"]
    assert len(table.scans) == 2 and len(table.calls) == 1


def test_legacy_environment_uses_hash_only_contact_sample_when_opted_out(run, monkeypatch):
    monkeypatch.setenv("INBOX_TIMELINE_INDEXES_ENABLED", "false")
    schema = describe(active=())
    schema["GlobalSecondaryIndexes"] = [{
        "IndexName": "contactId-index",
        "KeySchema": [{"AttributeName": "contactId", "KeyType": "HASH"}],
        "IndexStatus": "ACTIVE",
    }]
    table = FakeTable([row("old", 1), row("new", 10), row("other", 11, contact="b")],
                      schema=schema)
    status, page = run(table, contactId="a")
    assert status == 200 and page["historyMode"] == "sampled" and page["nextCursor"] is None
    assert [m["id"] for m in page["messages"]] == ["new", "old"]
    assert not table.scans and len(table.describes) == 1
    assert table.calls[0]["IndexName"] == "contactId-index"


@pytest.mark.parametrize("schema", [
    describe(active=("channel",)), describe(backfilling=("contactId",)),
    {**describe(), "GlobalSecondaryIndexes": [
        {**index_definition("channel"), "KeySchema": [{"AttributeName": "channel", "KeyType": "HASH"}]},
        index_definition("contactId"),
    ]},
])
def test_not_ready_or_schema_drift_never_claims_ordered_history(run, schema):
    table = FakeTable([row("sample", 5)], schema=schema)
    status, page = run(table)
    assert status == 200 and page["historyMode"] == "sampled" and page["nextCursor"] is None
    assert not table.calls


def test_readiness_permission_error_falls_back_without_masking_sample_read_failure(run):
    table = FakeTable([row("sample", 5)])

    def denied(**_):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "DescribeTable")

    table.meta.client.describe_table = denied
    status, page = run(table)
    assert status == 200 and page["historyMode"] == "sampled" and page["nextCursor"] is None
    assert not table.calls and len(table.scans) == 1

    def throttled(**_):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Scan")

    table.scan = throttled
    assert run(table)[0] == 503


@pytest.mark.parametrize("key", [
    {"id": {"S": "row"}, "contactId": {"S": "a"}},
    {"id": {"S": "row"}, "timestamp": {"S": "10"}, "contactId": {"S": "a"}},
    {"id": {"S": "row"}, "timestamp": {"N": "10"}, "contactId": {"S": "a"}, "other": {"S": "x"}},
    {"id": {"S": "row"}, "timestamp": {"N": "10"}, "contactId": {"S": "b"}},
])
def test_invalid_native_key_is_rejected_before_query(run, key):
    table = FakeTable([row("row", 10)])
    cursor = urlsafe_b64encode(json.dumps([2, ["a", "all", ""], {"a": key}]).encode()).decode()
    assert run(table, contactId="a", cursor=cursor)[0] == 400
    assert not table.calls


def legacy_schema():
    schema = describe(active=())
    schema["GlobalSecondaryIndexes"] = [
        {**index_definition(key), "IndexName": name, "IndexStatus": "ACTIVE"}
        for key, name in LEGACY_INDEXES.items()
    ]
    return schema


def test_legacy_ordered_indexes_return_latest_inbound_outside_scan_sample(run, monkeypatch):
    monkeypatch.delenv("INBOX_TIMELINE_INDEXES_ENABLED", raising=False)
    rows = [row(f"older-{i}", i) for i in range(400)]
    newest = row("recent-secondary", 10000)
    newest["awsPhoneNumberId"] = "synthetic-secondary"
    table = FakeTable([*rows, newest], schema=legacy_schema())
    status, page = run(table, channel="whatsapp", limit="20")
    assert status == 200 and page["historyMode"] == "sampled"
    assert page["nextCursor"] is None and page["messages"][0]["id"] == "recent-secondary"
    assert page["messages"][0]["awsPhoneNumberId"] == "synthetic-secondary"
    assert not table.scans and table.calls[0]["IndexName"] == LEGACY_INDEXES["channel"]
    assert table.calls[0]["ScanIndexForward"] is False
    status, page = run(table, contactId="a", limit="20")
    assert status == 200 and page["messages"][0]["id"] == "recent-secondary"
    assert table.calls[-1]["IndexName"] == LEGACY_INDEXES["contactId"]
    assert not table.scans


def test_unproven_legacy_index_is_not_assumed_ordered(run, monkeypatch):
    monkeypatch.delenv("INBOX_TIMELINE_INDEXES_ENABLED", raising=False)
    schema = legacy_schema()
    schema["GlobalSecondaryIndexes"][0]["Projection"] = {"ProjectionType": "KEYS_ONLY"}
    table = FakeTable([row("sample", 5)], schema=schema)
    status, page = run(table, channel="whatsapp")
    assert status == 200 and page["historyMode"] == "sampled"
    assert not table.calls and len(table.scans) == 1
