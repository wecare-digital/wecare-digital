"""Exercise the authenticated stats route through fake DynamoDB, never AWS."""

import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from lambda_utils import message_stats

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
SOURCE = (Path(__file__).resolve().parents[2] / "amplify/functions/core/messages-read/handler.py")
SPEC = importlib.util.spec_from_file_location("messages_read_stats_test", SOURCE)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)

MIDNIGHT = 20_000 * message_stats.DAY_SECONDS


class FakeTable:
    def __init__(self):
        self.calls = []
        self.pages = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


@pytest.fixture
def route(monkeypatch):
    from lambda_utils import middleware

    table = FakeTable()
    clock = [MIDNIGHT + 60]

    def authorize(event):
        return None

    def invoke():
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/messages"}},
            "queryStringParameters": {"stats": "count"},
        }
        response = HANDLER.handler(event, None)
        assert response["headers"]["Cache-Control"] == "private, no-store"
        return response["statusCode"], json.loads(response["body"])

    monkeypatch.setattr(middleware, "require_auth", authorize)
    monkeypatch.setattr(HANDLER, "_message_stats_reader", message_stats.CachedMessageStats(
        lambda: table, wall_time=lambda: clock[0], monotonic=lambda: clock[0],
    ))
    return table, clock, invoke


def test_delivery_uses_only_acknowledged_outbound_and_paginates_once(route):
    table, clock, invoke = route
    table.pages = [
        {"Items": [
            {"direction": "inbound", "status": "read", "timestamp": MIDNIGHT},
            {"direction": "outbound", "status": "sent", "timestamp": Decimal(MIDNIGHT)},
            {"direction": "outbound", "status": "delivered", "timestamp": MIDNIGHT - 1},
        ], "LastEvaluatedKey": {"id": "page-one"}},
        {"Items": [
            {"direction": "outbound", "status": "read", "timestamp": MIDNIGHT - 604800},
            {"direction": "outbound", "status": "failed", "timestamp": MIDNIGHT - 604801},
            {"direction": "outbound", "status": "pending", "timestamp": MIDNIGHT + 5},
        ]},
    ]
    code, payload = invoke()
    assert code == 200 and payload == {
        "status": "ok", "asOf": clock[0], "messagesToday": 3, "messagesWeek": 5,
        "totalMessages": 6, "deliveryRate": 40, "outboundMessages": 5,
        "sentMessages": 1, "deliveredMessages": 2,
    }
    assert len(table.calls) == 2
    assert table.calls[1]["ExclusiveStartKey"] == {"id": "page-one"}
    assert set(table.calls[0]["ExpressionAttributeNames"].values()) == {"direction", "status", "timestamp"}
    assert invoke() == (code, payload)
    assert len(table.calls) == 2


def test_empty_and_no_outbound_never_claim_delivery(route):
    table, clock, invoke = route
    table.pages = [{"Items": []}]
    code, payload = invoke()
    assert code == 200 and payload["status"] == "no_data"
    assert payload["totalMessages"] == 0 and payload["deliveryRate"] is None

    clock[0] += message_stats.CACHE_SECONDS
    table.pages = [{"Items": [{"direction": "inbound", "timestamp": MIDNIGHT}]}]
    code, payload = invoke()
    assert code == 200 and payload["status"] == "ok"
    assert payload["totalMessages"] == 1 and payload["deliveryRate"] is None


def test_sent_only_is_zero_confirmed_delivery(route):
    table, _, invoke = route
    table.pages = [{"Items": [{"direction": "outbound", "status": "sent", "timestamp": MIDNIGHT}]}]
    code, payload = invoke()
    assert code == 200 and payload["sentMessages"] == 1
    assert payload["deliveryRate"] == 0 and payload["deliveredMessages"] == 0


def test_outage_never_publishes_partial_results_and_cools_down(route):
    table, clock, invoke = route
    table.pages = [
        {"Items": [{"direction": "outbound", "status": "read"}], "LastEvaluatedKey": {"id": "1"}},
        RuntimeError("mock database unavailable"),
    ]
    code, payload = invoke()
    assert code == 503 and payload["status"] == "unavailable"
    assert payload["totalMessages"] is None and payload["deliveryRate"] is None
    clock[0] += message_stats.RETRY_SECONDS - 1
    assert invoke() == (code, payload)
    assert len(table.calls) == 2

    clock[0] += 1
    table.pages = [{"Items": []}]
    assert invoke()[1]["status"] == "no_data"
    assert len(table.calls) == 3


def test_failed_refresh_marks_stale_then_expires_last_success(route):
    table, clock, invoke = route
    table.pages = [
        {"Items": [{"direction": "outbound", "status": "delivered", "timestamp": MIDNIGHT}]},
        RuntimeError("mock scan failed"),
        RuntimeError("mock scan still failing"),
    ]
    _, first = invoke()
    clock[0] += message_stats.CACHE_SECONDS
    code, payload = invoke()
    assert code == 200 and payload["status"] == "stale"
    assert payload["asOf"] == first["asOf"] and payload["totalMessages"] == 1
    clock[0] += message_stats.MAX_STALE_SECONDS
    assert invoke()[0] == 503


def test_scan_hard_page_limit_and_nonadvancing_cursor(route):
    table, clock, invoke = route
    table.pages = [
        {"Items": [], "LastEvaluatedKey": {"id": str(idx)}}
        for idx in range(message_stats.MAX_PAGES + 1)
    ]
    assert invoke()[0] == 503
    assert len(table.calls) == message_stats.MAX_PAGES and len(table.pages) == 1
    assert all(call["Limit"] == message_stats.SCAN_LIMIT for call in table.calls)

    clock[0] += message_stats.RETRY_SECONDS
    table.pages = [{"Items": [], "LastEvaluatedKey": {"id": "same"}}] * 3
    assert invoke()[0] == 503
    assert len(table.pages) == 1


def test_cache_refreshes_on_new_utc_day(route):
    table, clock, invoke = route
    clock[0] = MIDNIGHT - 1
    table.pages = [
        {"Items": [{"direction": "inbound", "timestamp": MIDNIGHT - 1}]},
        {"Items": [{"direction": "inbound", "timestamp": MIDNIGHT - 1}]},
    ]
    assert invoke()[1]["messagesToday"] == 1
    clock[0] = MIDNIGHT
    assert invoke()[1]["messagesToday"] == 0
    assert len(table.calls) == 2


def test_time_budget_does_not_fetch_another_page():
    table = FakeTable()
    table.pages = [
        {"Items": [], "LastEvaluatedKey": {"id": "first"}},
        {"Items": []},
    ]
    timer = iter([0, 0, 0, message_stats.MAX_SCAN_SECONDS, message_stats.MAX_SCAN_SECONDS])
    reader = message_stats.CachedMessageStats(
        lambda: table, wall_time=lambda: MIDNIGHT, monotonic=lambda: next(timer),
    )
    assert reader.read()[0] == 503
    assert len(table.calls) == 1
