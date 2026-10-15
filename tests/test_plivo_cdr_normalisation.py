"""Plivo CDR rows must be readable by the CDR dashboard, not just present.

Regression guard for a silent failure. `plivo-answer._persist_cdr` had been
writing rows into VoiceCDRTable since the Plivo migration, in snake_case only.
Every read path (voice-cdr-read._format_record, _calculate_stats, and Call
History) binds to camelCase names, so those rows were in the table and
invisible in the product:

  * blank caller / destination / status cells
  * no date at all - there was no `createdAt`, which is BOTH the sort key for the
    read paths and the fallback the date renderer uses when `timestamp` is absent,
    so every Plivo row sorted to 0 and fell off the bottom of a limited page
  * they inflated `stats.total` while counting as neither inbound nor outbound
    and neither answered nor missed

Nothing raised. The tests below assert the reader-facing contract rather than the
storage call, because "put_item was called" was already true while the feature
was broken.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from decimal import Decimal

import pytest

SHARED = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"
FN = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/messaging/plivo-answer"
for p in (SHARED, FN):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load_plivo_answer():
    """Load plivo-answer's handler by path, under a name of its own.

    This was `import handler as plivo` at module scope, and it was the one binding in
    tests/ that `conftest.isolate_handler_imports` could not protect. That fixture is
    function-scoped, so it clears `sys.modules["handler"]` between tests - but a
    module-level import runs at COLLECTION time, before any fixture, and binds whichever
    of this repo's 64 `handler.py` files happened to get there first. The name it resolved
    to therefore depended on pytest's collection order, and nothing would have reported
    the mistake: the tests would simply have exercised a different Lambda.

    A unique module name removes the shared `sys.modules` key entirely, so this file
    neither depends on nor affects collection order.
    """
    spec = importlib.util.spec_from_file_location(
        "wecare_plivo_answer_handler", FN / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["wecare_plivo_answer_handler"] = module
    spec.loader.exec_module(module)
    return module


plivo = _load_plivo_answer()


class ConditionalCheckFailed(Exception):
    """Stands in for botocore's ClientError with that error code.

    Shaped like the real thing - `.response['Error']['Code']` - because
    `_persist_cdr` branches on the code string rather than importing botocore at
    module scope.
    """

    def __init__(self):
        super().__init__("ConditionalCheckFailedException")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _FakeTable:
    """A merging fake, not a recorder.

    `_persist_cdr` writes with `update_item` rather than `put_item`, because
    `put_item` REPLACES the item: a later non-terminal callback for the same
    CallUUID stripped `hangupCause`, `durationSec` and the rest off a completed
    call. A fake that only appends the outgoing payload cannot show that, so this
    one keeps per-id state and evaluates the rank condition.
    """

    def __init__(self):
        self.items = []          # the merged row after each write, newest last
        self.rows = {}           # id -> merged row
        self.writes = []         # ('put'|'update', id)

    def put_item(self, Item):  # noqa: N803 - boto3 kwarg name
        self.rows[Item["id"]] = dict(Item)
        self.items.append(dict(Item))
        self.writes.append(("put", Item["id"]))

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,  # noqa: N803
                    ExpressionAttributeValues, ConditionExpression=None):
        row_id = Key["id"]
        existing = self.rows.get(row_id, {})

        # Resolve `SET #n0 = :v0, #n3 = if_not_exists(#n3, :v3), ...`
        # Split on top-level commas only: `if_not_exists(a, b)` contains one too.
        assert UpdateExpression.startswith("SET ")
        clauses, depth, buf = [], 0, ""
        for ch in UpdateExpression[4:]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                clauses.append(buf)
                buf = ""
                continue
            buf += ch
        if buf.strip():
            clauses.append(buf)

        merged = dict(existing)
        for clause in clauses:
            lhs, rhs = clause.split(" = ", 1)
            name = ExpressionAttributeNames[lhs.strip()]
            rhs = rhs.strip()
            if rhs.startswith("if_not_exists("):
                inner = rhs[len("if_not_exists("):-1]
                _existing_ref, default_ref = [p.strip() for p in inner.split(",")]
                if name not in existing:
                    merged[name] = ExpressionAttributeValues[default_ref]
            else:
                merged[name] = ExpressionAttributeValues[rhs]

        # Enforce the rank condition the same way DynamoDB would. Placeholders are
        # resolved first: the handler writes `#rank <= :rank`, so looking for the
        # literal attribute name in the expression finds nothing and silently
        # skips the check - which is how this fake passed a broken fix once.
        if ConditionExpression:
            resolved = ConditionExpression
            for ph, name in ExpressionAttributeNames.items():
                resolved = resolved.replace(ph, name)
            if "cdrRank" in resolved:
                incoming = ExpressionAttributeValues[":rank"]
                current = existing.get("cdrRank")
                if current is not None and \
                        Decimal(str(incoming)) < Decimal(str(current)):
                    raise ConditionalCheckFailed()

        merged["id"] = row_id
        self.rows[row_id] = merged
        self.items.append(dict(merged))
        self.writes.append(("update", row_id))


@pytest.fixture()
def captured(monkeypatch):
    table = _FakeTable()
    monkeypatch.setattr(plivo, "_table", lambda: table)
    # The breadcrumb writes to a different table; capture it instead of reaching out.
    calls = []
    import lambda_utils.message_store as ms

    monkeypatch.setattr(ms, "put_call_breadcrumb", lambda **kw: calls.append(kw))
    table.breadcrumbs = calls
    return table


def _persist(captured, **params):
    assert plivo._persist_cdr(params, "hangup", "req-1") is True
    return captured.items[-1]


# --------------------------------------------------------------------------
# the fields that made Plivo rows invisible
# --------------------------------------------------------------------------

def test_createdAt_is_written_so_the_row_can_sort_and_render_a_date(captured):
    """createdAt is the sort key AND the date fallback. Missing it hid the row twice."""
    item = _persist(captured, CallUUID="u1", From="+919876543210",
                    To="+918031830030", Direction="inbound",
                    CallStatus="completed", Duration="42")
    assert "createdAt" in item
    assert float(item["createdAt"]) > 0
    # the reader parses `timestamp` with '%Y-%m-%d %H:%M:%S'
    import datetime
    datetime.datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")


def test_camelcase_number_fields_are_populated(captured):
    item = _persist(captured, CallUUID="u2", From="+919876543210",
                    To="+918031830030", Direction="inbound",
                    CallStatus="completed", Duration="10")
    assert item["callerNumber"] == "+919876543210"
    assert item["destinationNumber"] == "+918031830030"


def test_callType_is_the_uppercase_vocabulary_the_readers_filter_on(captured):
    """Plivo says 'inbound'; _calculate_stats compares against 'INBOUND'."""
    inbound = _persist(captured, CallUUID="u3", Direction="inbound",
                       CallStatus="completed", Duration="5")
    assert inbound["callType"] == "INBOUND"
    outbound = _persist(captured, CallUUID="u4", Direction="outbound",
                        CallStatus="completed", Duration="5")
    assert outbound["callType"] == "OUTBOUND"


def test_outbound_api_direction_still_maps_to_OUTBOUND(captured):
    """Plivo reports 'outbound-api' for API-originated calls."""
    item = _persist(captured, CallUUID="u5", Direction="outbound-api",
                    CallStatus="completed", Duration="5")
    assert item["callType"] == "OUTBOUND"


def test_unknown_direction_does_not_invent_a_call_type(captured):
    item = _persist(captured, CallUUID="u6", Direction="", CallStatus="completed",
                    Duration="5")
    assert "callType" not in item  # empty values are stripped, not guessed


# --------------------------------------------------------------------------
# status mapping
# --------------------------------------------------------------------------

@pytest.mark.parametrize("plivo_status,expected", [
    ("busy", "Busy"),
    ("no-answer", "Missed"),
    ("failed", "Missed"),
    ("cancel", "Missed"),
    ("timeout", "Missed"),
])
def test_unsuccessful_statuses_map_to_the_reader_vocabulary(captured, plivo_status,
                                                            expected):
    item = _persist(captured, CallUUID=f"s-{plivo_status}", Direction="inbound",
                    CallStatus=plivo_status)
    assert item["overallCallStatus"] == expected


def test_completed_with_talk_time_is_answered(captured):
    item = _persist(captured, CallUUID="u7", Direction="inbound",
                    CallStatus="completed", Duration="37")
    assert item["overallCallStatus"] == "Answered"


def test_completed_with_zero_duration_is_missed_not_answered(captured):
    """Plivo reports `completed` on a normal teardown whether or not anyone
    picked up. Trusting it blindly overstates the answer rate."""
    item = _persist(captured, CallUUID="u8", Direction="inbound",
                    CallStatus="completed", Duration="0")
    assert item["overallCallStatus"] == "Missed"


# --------------------------------------------------------------------------
# durations
# --------------------------------------------------------------------------

def test_duration_strings_become_numeric_seconds_and_millis(captured):
    """Plivo sends Duration as a string; the UI does float maths on durationSec."""
    item = _persist(captured, CallUUID="u9", Direction="inbound",
                    CallStatus="completed", Duration="90")
    assert item["durationSec"] == Decimal("90")
    assert item["durationMs"] == Decimal("90000")
    assert item["conversationDurationSec"] == Decimal("90")
    assert item["billableDurationSec"] == Decimal("90")


def test_billduration_is_used_when_duration_is_absent(captured):
    item = _persist(captured, CallUUID="u10", Direction="inbound",
                    CallStatus="completed", BillDuration="60")
    assert item["durationSec"] == Decimal("60")


def test_nonnumeric_duration_does_not_raise(captured):
    item = _persist(captured, CallUUID="u11", Direction="inbound",
                    CallStatus="completed", Duration="not-a-number")
    assert item["durationSec"] == Decimal("0")


# --------------------------------------------------------------------------
# invariants that must not regress
# --------------------------------------------------------------------------

def test_source_names_plivo_as_the_writer(captured):
    """plivo-answer is VoiceCDRTable's only writer; `source` and the id prefix say so."""
    item = _persist(captured, CallUUID="u12", Direction="inbound",
                    CallStatus="completed", Duration="5")
    assert item["source"] == "plivo"
    assert item["id"] == "plivo#u12"


def test_snake_case_keys_are_retained_for_preexisting_rows(captured):
    """Rows written before normalisation carry these. A later callback for the
    same call must not strip them."""
    item = _persist(captured, CallUUID="u13", From="+911", To="+912",
                    Direction="inbound", CallStatus="completed", Duration="5")
    for key in ("call_uuid", "from_number", "to_number", "call_status",
                "received_at"):
        assert key in item


def test_missing_call_uuid_is_refused(captured):
    assert plivo._persist_cdr({"CallStatus": "completed"}, "hangup", "r") is False
    assert captured.items == []


def test_breadcrumb_is_written_with_the_plivo_call_type(captured):
    """src/pages/workspace/engage/calls keys its provider badge on this value."""
    _persist(captured, CallUUID="u14", From="+919876543210", To="+918031830030",
             Direction="inbound", CallStatus="completed", Duration="12")
    assert captured.breadcrumbs, "no breadcrumb written"
    assert captured.breadcrumbs[-1]["call_type"] == "plivo"


def test_breadcrumb_failure_does_not_lose_the_cdr(captured, monkeypatch):
    """The CDR is the record of record; a timeline nicety must not discard it."""
    import lambda_utils.message_store as ms

    def _boom(**kw):
        raise RuntimeError("messages table unavailable")

    monkeypatch.setattr(ms, "put_call_breadcrumb", _boom)
    assert plivo._persist_cdr(
        {"CallUUID": "u15", "Direction": "inbound", "CallStatus": "completed",
         "Duration": "5"}, "hangup", "r") is True
    assert captured.items[-1]["id"] == "plivo#u15"


def test_persist_returns_false_when_the_table_write_fails(captured, monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("throughput exceeded")

    monkeypatch.setattr(captured, "update_item", _boom)
    assert plivo._persist_cdr(
        {"CallUUID": "u16", "Direction": "inbound", "CallStatus": "completed"},
        "hangup", "r") is False


# --------------------------------------------------------------------------
# monotonic lifecycle — five routes, one row id
# --------------------------------------------------------------------------
# All five call sites write `id = f'plivo#{CallUUID}'`, so they share one row.
# With `put_item` that means last-writer-wins on the whole item, regardless of
# where in the call's life the callback belongs.
#
# Measured before the fix: 56 of 56 live rows were won by `route='hangup'`, so
# this had not yet fired in production - `dial-events` has never been invoked
# because PSTN_BROWSER_ROUTING_ENABLED is false, and `events` is not configured
# on the Plivo application. It is reachable by design though, not by accident:
# `_route_dial_events` returns 503 on purpose when the notification store is
# unreachable so that Plivo REDELIVERS, and a redelivery can land after hangup.
#
# The consequence is not a cosmetic field: a mid-call payload carries no
# Duration, `_plivo_overall_status` downgrades a zero-duration `completed` to
# 'Missed', and `_calculate_stats` counts answered/missed off exactly that field.
# An answered call would be reported as missed.

TERMINAL = {"CallUUID": "m1", "From": "+919876543210", "To": "+918031830030",
            "Direction": "inbound", "CallStatus": "completed", "Duration": "42",
            "HangupCause": "NORMAL_CLEARING", "HangupSource": "callee",
            "EndTime": "2026-09-23 06:00:00"}

MIDCALL = {"CallUUID": "m1", "From": "+919876543210", "To": "+918031830030",
           "Direction": "inbound", "CallStatus": "ringing"}


def test_a_late_midcall_callback_does_not_downgrade_a_completed_call(captured):
    assert plivo._persist_cdr(TERMINAL, "hangup", "r1") is True
    assert captured.rows["plivo#m1"]["overallCallStatus"] == "Answered"

    # The redelivery, arriving after the terminal state was recorded.
    assert plivo._persist_cdr(MIDCALL, "dial-events", "r2") is True

    row = captured.rows["plivo#m1"]
    assert row["overallCallStatus"] == "Answered", \
        "a mid-call redelivery rewrote a completed call as Missed"
    assert row["durationSec"] == Decimal("42")


def test_a_late_midcall_callback_does_not_strip_the_terminal_fields(captured):
    """`put_item` replaces the item, so absent fields were DELETED, not preserved."""
    plivo._persist_cdr(TERMINAL, "hangup", "r1")
    plivo._persist_cdr(MIDCALL, "events", "r2")

    row = captured.rows["plivo#m1"]
    for field in ("hangupCause", "hangup_cause", "hangupStatus", "end_time",
                  "durationSec", "duration_seconds", "billableDurationSec"):
        assert field in row, f"{field} was stripped by a later non-terminal write"
    assert row["hangupCause"] == "NORMAL_CLEARING"


def test_an_earlier_callback_still_creates_the_row(captured):
    """Ordering is not guaranteed in the other direction either: a mid-call event
    may legitimately arrive first, and it must create the row rather than wait."""
    assert plivo._persist_cdr(MIDCALL, "events", "r1") is True
    assert "plivo#m1" in captured.rows
    assert captured.rows["plivo#m1"]["cdrRank"] == Decimal("10")


def test_a_terminal_callback_overwrites_an_earlier_midcall_row(captured):
    plivo._persist_cdr(MIDCALL, "events", "r1")
    plivo._persist_cdr(TERMINAL, "hangup", "r2")
    row = captured.rows["plivo#m1"]
    assert row["overallCallStatus"] == "Answered"
    assert row["durationSec"] == Decimal("42")
    assert row["cdrRank"] == Decimal("40")


def test_a_retried_hangup_is_allowed_to_refresh_the_row(captured):
    """Equal rank must pass. Plivo retries callbacks, and a retry carrying a
    corrected BillDuration should land - refusing it would pin the first value."""
    plivo._persist_cdr(TERMINAL, "hangup", "r1")
    corrected = dict(TERMINAL, Duration="47")
    assert plivo._persist_cdr(corrected, "hangup", "r2") is True
    assert captured.rows["plivo#m1"]["durationSec"] == Decimal("47")


def test_the_two_terminal_routes_share_a_rank(captured):
    """During the transition the completed pass arrives on /plivo/answer too. It
    is the same lifecycle position, so it must neither lose to nor be refused by
    a hangup callback."""
    assert plivo._CDR_ROUTE_RANK["answer-hangup-pass"] == \
        plivo._CDR_ROUTE_RANK["hangup"]


def test_a_superseded_write_reports_success_not_failure(captured):
    """The row is already at a higher state, so nothing is wrong. Returning False
    would make `_route_hangup` log cdrPersisted=false on a healthy call."""
    plivo._persist_cdr(TERMINAL, "hangup", "r1")
    assert plivo._persist_cdr(MIDCALL, "events", "r2") is True


def test_created_at_is_stamped_once_and_not_restamped(captured, monkeypatch):
    """createdAt is the sort key for both read paths and the date fallback the
    renderer uses. A later callback must not move the row's place in history."""
    monkeypatch.setattr(plivo.time, "time", lambda: 1_000_000)
    plivo._persist_cdr(MIDCALL, "events", "r1")
    first = captured.rows["plivo#m1"]["createdAt"]

    monkeypatch.setattr(plivo.time, "time", lambda: 1_000_900)
    plivo._persist_cdr(TERMINAL, "hangup", "r2")
    row = captured.rows["plivo#m1"]
    assert row["createdAt"] == first, "createdAt was restamped by a later callback"
    assert row["received_at"] == 1_000_900, "received_at should track the latest write"


def test_every_persist_call_site_has_a_rank(captured):
    """A route missing from the table would rank 0 and lose to everything,
    including the row it is supposed to create."""
    import inspect
    src = inspect.getsource(plivo)
    called = set()
    for line in src.splitlines():
        if "_persist_cdr(params, '" in line:
            called.add(line.split("_persist_cdr(params, '")[1].split("'")[0])
    assert called, "no _persist_cdr call sites found - has the call shape changed?"
    assert called <= set(plivo._CDR_ROUTE_RANK), \
        f"routes with no rank: {sorted(called - set(plivo._CDR_ROUTE_RANK))}"


def test_the_write_is_conditional_not_a_blind_put(captured):
    plivo._persist_cdr(TERMINAL, "hangup", "r1")
    assert captured.writes == [("update", "plivo#m1")], \
        "a blind put_item cannot preserve a higher lifecycle state"
