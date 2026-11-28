"""MSG-2: endpoint Flows take the customer from a server-issued session, never the token.

A token's `-ph-` text is only a claim. These tests drive the real router and Flow
modules with in-memory stores: a forged token is refused (FlowSessionRejected, which
the /flow-data handler answers with HTTP 427), and an order or request id that the
session's customer does not own is refused the same way, before any read or write.
"""
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BUSINESS_API = (Path(__file__).resolve().parents[2]
                / "amplify/functions/messaging/whatsapp-business-api")

VICTIM = "919800000001"
OWNER = "919800000002"


@pytest.fixture(scope="module")
def flows():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    sys.path.insert(0, str(BUSINESS_API))
    try:
        from flows import (router, common, orders, submit_request, track_request,
                           amend_request, order_notes)
        from lambda_utils import flow_sessions
        yield SimpleNamespace(router=router, common=common, orders=orders,
                              submit_request=submit_request, track_request=track_request,
                              amend_request=amend_request, order_notes=order_notes,
                              flow_sessions=flow_sessions)
    finally:
        sys.path.remove(str(BUSINESS_API))


class FakeTable:
    """FlowDraftTable (sessions) plus no-op log/draft writes."""

    def __init__(self):
        self.rows = {}
        self.writes = []

    def get_item(self, Key, ConsistentRead=False, **_):
        item = self.rows.get(Key.get("draftKey"))
        return {"Item": item} if item else {}

    def put_item(self, Item, **_):
        self.writes.append(("put", Item))

    def update_item(self, **kwargs):
        self.writes.append(("update", kwargs))

    def delete_item(self, **kwargs):
        self.writes.append(("delete", kwargs))

    def query(self, **kwargs):
        return {"Items": []}


@pytest.fixture
def store(flows, monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(flows.common, "dynamodb", SimpleNamespace(Table=lambda _n: table))
    orders = {
        "ord-victim": {"orderId": "ord-victim", "customerPhone": "+" + VICTIM,
                       "shortId": "VICTIM01", "totalAmount": 500},
        "ord-owner": {"orderId": "ord-owner", "customerPhone": "+" + OWNER,
                      "shortId": "OWNER001", "totalAmount": 100},
    }
    fetched = []

    def fetch(phone, email):
        fetched.append(phone)
        return [{"id": o["orderId"], "title": o["shortId"]} for o in orders.values()
                if o["customerPhone"].lstrip("+") == phone]

    monkeypatch.setattr(flows.orders, "get_order", lambda oid: dict(orders.get(oid) or {}))
    for module in (flows.track_request, flows.amend_request, flows.order_notes):
        monkeypatch.setattr(module, "fetch_orders_for_flow", fetch)
    monkeypatch.setattr(flows.orders, "fetch_orders_for_flow", fetch)
    monkeypatch.setattr(flows.track_request, "get_order", lambda oid: dict(orders.get(oid) or {}))
    monkeypatch.setattr(flows.track_request, "get_submissions_for_order", lambda oid: [])
    monkeypatch.setattr(flows.order_notes, "get_order", lambda oid: dict(orders.get(oid) or {}))
    return SimpleNamespace(table=table, fetched=fetched)


def token(prefix, phone):
    return f"{prefix}-{uuid.uuid4().hex}-waba-1-ph-{phone}"


def issue(flows, store, capability, tok):
    phone = flows.flow_sessions.phone_from_token(tok)
    now = int(time.time())
    store.table.rows[flows.flow_sessions.session_key(phone, tok)] = {
        "phone": phone, "capability": capability, "waba": "1",
        "launchChannel": "staff_send", "initiatedBy": "test",
        "createdAt": now, "expiresAt": now + 3600,
    }
    return tok


def route(flows, action, screen, data, tok):
    return flows.router.route_flow(action=action, screen=screen, data=data,
                                   flow_token=tok, request_id="req")


@pytest.mark.parametrize("prefix", [
    "sr", "track_requ", "amend_requ", "order_note", "schedule_a", "sehat", "enterprise",
    "anything",  # the router's retired generic INIT order fetch
])
def test_forged_token_init_is_refused_and_lists_no_orders(flows, store, prefix):
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "INIT", "", {}, token(prefix, VICTIM))
    assert store.fetched == []


def test_spliced_phone_on_a_real_session_is_refused(flows, store):
    real = issue(flows, store, "track_request", token("track_requ", OWNER))
    spliced = real.replace(f"-ph-{OWNER}", f"-ph-{VICTIM}")
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "INIT", "", {}, spliced)


def test_session_customer_sees_only_their_own_orders(flows, store):
    tok = issue(flows, store, "track_request", token("track_requ", OWNER))
    result = route(flows, "INIT", "", {"email": "victim@example.com"}, tok)
    assert [o["id"] for o in result["data"]["orders"]] == ["ord-owner"]
    assert store.fetched == [OWNER]


def test_session_for_another_capability_is_refused(flows, store):
    tok = issue(flows, store, "order_notes", token("track_requ", OWNER))
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "INIT", "", {}, tok)


def test_track_status_of_another_customers_order_is_refused(flows, store):
    tok = issue(flows, store, "track_request", token("track_requ", OWNER))
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "data_exchange", "ORDER_SELECT", {"order_id": "ord-victim"}, tok)
    status = route(flows, "data_exchange", "ORDER_SELECT", {"order_id": "ord-owner"}, tok)
    assert status["screen"] == "STATUS" and "OWNER001" in status["data"]["order_ref"]


def test_submit_request_review_cannot_file_as_another_customer(flows, store, monkeypatch):
    saved = []
    monkeypatch.setattr(flows.submit_request, "record_completion",
                        lambda **kw: saved.append(kw) or SimpleNamespace(
                            reference="WD-SR-1", should_fire_side_effects=False,
                            status="duplicate", submission_id="s", duplicate=True, error=""))
    monkeypatch.setattr(flows.submit_request, "find_contact_by_phone", lambda p: "")
    monkeypatch.setattr(flows.submit_request, "get_contact_name", lambda c: "")
    data = {"order_id": "ord-owner", "subject": "help", "description": "text"}
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "data_exchange", "REVIEW", data, token("sr", VICTIM))
    tok = issue(flows, store, "submit_request", token("sr", OWNER))
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "data_exchange", "REVIEW", {**data, "order_id": "ord-victim"}, tok)
    assert saved == []
    route(flows, "data_exchange", "REVIEW", data, tok)
    assert saved and saved[0]["phone"] == OWNER


def test_order_notes_cannot_write_to_another_customers_order(flows, store, monkeypatch):
    monkeypatch.setattr(flows.order_notes, "record_completion", lambda **kw: pytest.fail("saved"))
    monkeypatch.setattr(flows.order_notes, "find_contact_by_phone", lambda p: "")
    tok = issue(flows, store, "order_notes", token("order_note", OWNER))
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "data_exchange", "NOTES_FORM",
              {"order_id": "ord-victim", "notes": "attacker text"}, tok)
    assert not [w for w in store.table.writes if w[0] == "update"]


def test_amendment_cannot_touch_another_customers_request(flows, store, monkeypatch):
    victim_request = {"submissionId": "sub-1", "submissionNumber": "WD-SR-9",
                      "phone": VICTIM, "orderId": "ord-victim"}
    store.table.query = lambda **kw: {"Items": [dict(victim_request)]}
    monkeypatch.setattr(flows.amend_request, "dynamodb",
                        SimpleNamespace(Table=lambda _n: store.table))
    tok = issue(flows, store, "amend_request", token("amend_requ", OWNER))
    for screen, data in (("SELECT_REQUEST", {"request_id": "WD-SR-9"}),
                         ("AMEND_FORM", {"request_id": "WD-SR-9", "amendment": "x"})):
        with pytest.raises(flows.flow_sessions.FlowSessionRejected):
            route(flows, "data_exchange", screen, data, tok)
    assert not [w for w in store.table.writes if w[0] == "update"]
    with pytest.raises(flows.flow_sessions.FlowSessionRejected):
        route(flows, "data_exchange", "SELECT_ORDER", {"parent_order": "ord-victim"}, tok)
