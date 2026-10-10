"""A GST invoice number is issued once and never again.

WHAT THIS FILE IS FOR
---------------------
`invoice-engine._get_next_invoice_number` used to be an atomic counter and nothing else. Atomic
is not the same as durable: the counter is one row on `InvoiceSequenceTable`, that table is wiped
by `clear_all_invoice_data`, and a wiped counter restarts at 1 - which is how `WD/2627/00001`
reached two different customers eight days apart while `00002`-`00004` were erased with it. Under
Rule 46(b) an invoice number belongs to a consecutive series for the financial year and cannot be
reassigned once it has gone out, so the defect is not "the counter was wrong", it is "nothing
recorded what was issued".

Every test below is about that record: the `INVOICENO#` reservation row on the commerce-keys
table, written with a conditional `attribute_not_exists` put as the LAST thing before a number is
handed out.

TECHNIQUE
---------
The keys table is `crm_fake_dynamo`, because it genuinely evaluates `attribute_not_exists` and
raises `ConditionalCheckFailedException` - that behaviour is the subject here, not scaffolding.
The counter is a purpose-built fake for the same reason `test_invoice_coupon_and_gift_card` uses
one: the engine's `if_not_exists(last_seq, :zero) + :inc` is a shape the shared fake deliberately
refuses, and it exposes `advances` so "the counter walked past the collision" is measured rather
than inferred.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import boto3.dynamodb.conditions  # real Dynamo resource loads this; the fixture mocks construction

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
sys.path.insert(0, str(Path(__file__).parent))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402

FY = "2026-2027"
#: The reservation key format every later surface depends on. Written out in full rather than
#: composed from the constant, so a change to either has to be deliberate.
FIRST_KEY = "INVOICENO#WD/2627/00001"
#: A placeholder, never a real customer number.
PHONE = "+919999999999"


class _CounterTable:
    """The GST counter row, keyed `fy`, with `advances` exposed.

    The engine's expression is a single `if_not_exists(last_seq, :zero) + :inc`. Modelled as a
    plain increment because what these tests ask is whether it RAN and how far it walked, not how
    it races - the race is settled by the conditional write on the keys table, which is real here.
    """

    def __init__(self) -> None:
        self.rows: dict = {}
        self.advances = 0
        self.fail_with: Exception | None = None

    def update_item(self, Key=None, **_):
        self.advances += 1
        if self.fail_with is not None:
            raise self.fail_with
        fy = (Key or {})["fy"]
        row = self.rows.setdefault(fy, {"fy": fy, "last_seq": 0, "prefix": "WD"})
        row["last_seq"] = int(row["last_seq"]) + 1
        return {"Attributes": dict(row)}

    def get_item(self, Key=None, **_):
        row = self.rows.get((Key or {})["fy"])
        return {"Item": dict(row)} if row else {}


class _InvoicesTable:
    """Key `invoiceId`. Enough of the table for `create_invoice` to reach the numbering step.

    The dedup scan's filter is `referenceId = :ref OR paymentId = :pid`, evaluated against the
    two placeholders directly so an unexpected filter shape fails loudly instead of matching
    everything.
    """

    def __init__(self) -> None:
        self.rows: dict = {}

    def scan(self, FilterExpression="", ExpressionAttributeValues=None, **_):
        values = ExpressionAttributeValues or {}
        if set(values) - {":ref", ":pid"}:
            raise AssertionError(f"unexpected scan filter {FilterExpression!r}")
        matched = [dict(row) for row in self.rows.values()
                   if (":ref" in values and row.get("referenceId") == values[":ref"])
                   or (":pid" in values and row.get("paymentId") == values[":pid"])]
        return {"Items": matched}

    def put_item(self, Item=None, ConditionExpression=None, **_):
        item = dict(Item or {})
        key = item["invoiceId"]
        if ConditionExpression and "attribute_not_exists(invoiceId)" in str(ConditionExpression) \
                and key in self.rows:
            raise FakeClientError("ConditionalCheckFailedException")
        self.rows[key] = item
        return {}

    def get_item(self, Key=None, **_):
        row = self.rows.get((Key or {})["invoiceId"])
        return {"Item": dict(row)} if row else {}

    def update_item(self, Key=None, **_):
        key = (Key or {})["invoiceId"]
        return {"Attributes": dict(self.rows.get(key, {"invoiceId": key}))}

    @property
    def numbered(self) -> list:
        return [row for row in self.rows.values() if row.get("invoiceNumber")]


class _ItemsTable:
    """Composite `(invoiceId, itemIndex)`. Present only so "no line was written" is measurable."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        self.rows[(item["invoiceId"], int(item["itemIndex"]))] = item
        return {}

    def query(self, **_):
        return {"Items": []}


@pytest.fixture
def engine(monkeypatch):
    """The real handler module, imported with no AWS, pointed at in-memory tables."""
    monkeypatch.syspath_prepend(str(ROOT / "amplify/functions/shared"))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    name = "_invoice_number_reservation_engine"
    spec = importlib.util.spec_from_file_location(name, FUNCTION)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)

    keys = FakeDynamo({module.COMMERCE_KEYS_TABLE: "orderId"})
    counter = _CounterTable()
    invoices = _InvoicesTable()
    items = _ItemsTable()
    by_name = {
        module.COMMERCE_KEYS_TABLE: keys.Table(module.COMMERCE_KEYS_TABLE),
        module.INVOICE_SEQ_TABLE: counter,
        module.INVOICES_TABLE: invoices,
        module.INVOICE_ITEMS_TABLE: items,
    }

    class _Resource:
        def Table(self, table_name):  # noqa: N802 - the boto3 resource spelling
            try:
                return by_name[table_name]
            except KeyError:
                raise AssertionError(
                    f"the engine opened an unexpected table {table_name!r}") from None

    module.dynamodb = _Resource()
    module.logger = MagicMock()
    return module, keys, counter, invoices, items


def _reservations(module, keys) -> list:
    return [row for row in keys.all_rows(module.COMMERCE_KEYS_TABLE)
            if str(row.get("orderId", "")).startswith(module.order_keys.INVOICE_NUMBER_PREFIX)]


def _body(**overrides) -> dict:
    body = {
        "referenceId": "WD-PAY-RESERVE01",
        "customerPhone": PHONE,
        "entryPoint": "pay_flow",
        "items": [{"name": "Service", "amount": 1000.0, "quantity": 1}],
        "gstRate": 18,
        "currency": "INR",
    }
    body.update(overrides)
    return body


# ══════════════════════════════════════════════════════════════════════════════
# (a) a fresh financial year
# ══════════════════════════════════════════════════════════════════════════════

def test_a_fresh_financial_year_issues_00001_and_records_it_once(engine):
    module, keys, counter, _invoices, _items = engine

    number = module._get_next_invoice_number(FY)

    assert number == "WD/2627/00001"
    rows = _reservations(module, keys)
    assert len(rows) == 1, rows
    assert rows[0]["orderId"] == FIRST_KEY
    assert rows[0]["invoiceNumber"] == number
    assert rows[0]["fy"] == FY
    assert rows[0]["kind"] == module.order_keys.INVOICE_NUMBER_KIND
    # No TTL on an identity reservation, ever: one that expires is one that gets reissued.
    assert "ttl" not in rows[0] and "expiresAt" not in rows[0]
    assert counter.advances == 1


def test_the_number_is_returned_only_after_the_reservation_is_committed(engine):
    """The ordering is the contract, so it is asserted rather than assumed.

    If a future edit returned the candidate before the conditional write, every other test here
    would still pass - the number would be right, it would simply be unrecorded, which is exactly
    the state the duplicate came from.
    """
    module, keys, _counter, _invoices, _items = engine
    observed: list = []
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    real_put = table.put_item

    def _watch(**kwargs):
        observed.append("reserved")
        return real_put(**kwargs)

    table.put_item = _watch

    number = module._get_next_invoice_number(FY)

    assert observed == ["reserved"]
    assert module.order_keys.resolve_invoice_number(table, number) is not None


# ══════════════════════════════════════════════════════════════════════════════
# (b) concurrency
# ══════════════════════════════════════════════════════════════════════════════

def test_two_interleaved_callers_never_receive_the_same_number(engine):
    """A second caller runs to completion INSIDE the first caller's reservation window."""
    module, keys, counter, _invoices, _items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    real_put = table.put_item
    second: list = []
    switched: list = []

    def _interleave(**kwargs):
        if not switched:
            # The second caller takes its own number and commits it while the first is still
            # mid-write. Re-entrant on purpose: this is the shape two concurrent Lambdas have.
            # The flag is set BEFORE the nested call so the switch happens exactly once.
            switched.append(True)
            second.append(module._get_next_invoice_number(FY))
        return real_put(**kwargs)

    table.put_item = _interleave

    first = module._get_next_invoice_number(FY)

    assert second, "the interleaved caller never ran"
    assert first != second[0]
    assert sorted([first, second[0]]) == ["WD/2627/00001", "WD/2627/00002"]
    rows = _reservations(module, keys)
    assert sorted(row["invoiceNumber"] for row in rows) == sorted([first, second[0]])
    assert len(rows) == 2, rows
    assert counter.advances == 2


# ══════════════════════════════════════════════════════════════════════════════
# (c) the C2 regression: a counter reset below the issued series
# ══════════════════════════════════════════════════════════════════════════════

def test_a_reset_counter_advances_past_an_issued_number_instead_of_reusing_it(engine):
    """The duplicate, reproduced: counter back at 0, `WD/2627/00001` already out."""
    module, keys, counter, _invoices, _items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    assert module.order_keys.reserve_invoice_number(
        table, invoice_number="WD/2627/00001", fy=FY)
    before = dict(keys.all_rows(module.COMMERCE_KEYS_TABLE)[0])
    counter.rows[FY] = {"fy": FY, "last_seq": 0, "prefix": "WD"}

    number = module._get_next_invoice_number(FY)

    assert number == "WD/2627/00002"
    rows = {row["orderId"]: row for row in _reservations(module, keys)}
    assert sorted(rows) == [FIRST_KEY, "INVOICENO#WD/2627/00002"]
    # The first reservation is immutable: the row that proves 00001 went out is not rewritten.
    assert rows[FIRST_KEY] == before
    assert counter.advances == 2
    logged = [str(call) for call in module.logger.warning.mock_calls]
    assert any("invoice_number_already_reserved" in line for line in logged), logged


def test_a_counter_far_behind_the_series_still_lands_on_the_first_free_number(engine):
    module, keys, counter, _invoices, _items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    for seq in range(1, 5):  # 00001-00004, the four numbers the reset erased
        module.order_keys.reserve_invoice_number(
            table, invoice_number=f"WD/2627/{seq:05d}", fy=FY)
    counter.rows[FY] = {"fy": FY, "last_seq": 0, "prefix": "WD"}

    assert module._get_next_invoice_number(FY) == "WD/2627/00005"
    assert len(_reservations(module, keys)) == 5


# ══════════════════════════════════════════════════════════════════════════════
# (d) exhausting the attempt cap
# ══════════════════════════════════════════════════════════════════════════════

def test_exhausting_the_attempt_cap_refuses_rather_than_reusing_a_number(engine):
    module, keys, counter, _invoices, _items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    reserved = module._INVOICE_NUMBER_ATTEMPTS
    for seq in range(1, reserved + 1):
        module.order_keys.reserve_invoice_number(
            table, invoice_number=f"WD/2627/{seq:05d}", fy=FY)
    counter.rows[FY] = {"fy": FY, "last_seq": 0, "prefix": "WD"}

    with pytest.raises(module.InvoiceSequenceUnavailable):
        module._get_next_invoice_number(FY)

    assert counter.advances == reserved
    # Not one extra row: a refusal records no issuance.
    assert len(_reservations(module, keys)) == reserved


def test_create_invoice_answers_503_and_writes_no_document_when_the_cap_is_exhausted(engine):
    module, keys, counter, invoices, items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    for seq in range(1, module._INVOICE_NUMBER_ATTEMPTS + 1):
        module.order_keys.reserve_invoice_number(
            table, invoice_number=f"WD/2627/{seq:05d}", fy=FY)
    counter.rows[FY] = {"fy": FY, "last_seq": 0, "prefix": "WD"}

    response = module.create_invoice(_body(fy=FY), "req-cap")

    assert response["statusCode"] == 503
    payload = json.loads(response["body"])
    assert payload["errorCode"] == "INVOICE_SEQUENCE_UNAVAILABLE"
    assert payload["retryable"] is True
    assert invoices.numbered == []
    assert items.rows == {}
    assert len(_reservations(module, keys)) == module._INVOICE_NUMBER_ATTEMPTS


# ══════════════════════════════════════════════════════════════════════════════
# (e) a storage error is not a lost race
# ══════════════════════════════════════════════════════════════════════════════

def test_a_storage_error_on_the_reservation_refuses_and_records_nothing(engine):
    """A throttle must not be read as "already issued", and must not hand a number out either."""
    module, keys, counter, _invoices, _items = engine
    keys.arm_failure(module.COMMERCE_KEYS_TABLE, "put_item",
                     FakeClientError("ProvisionedThroughputExceededException"))

    with pytest.raises(module.InvoiceSequenceUnavailable):
        module._get_next_invoice_number(FY)

    assert _reservations(module, keys) == []
    # One advance, not a walk: a storage error is not a collision, so nothing is retried.
    assert counter.advances == 1
    logged = [str(call) for call in module.logger.error.mock_calls]
    assert any("invoice_number_reservation_unavailable" in line for line in logged), logged
    assert not any("invoice_number_already_reserved" in str(call)
                   for call in module.logger.warning.mock_calls)


def test_create_invoice_answers_503_on_a_reservation_storage_error(engine):
    module, keys, counter, invoices, items = engine
    keys.arm_failure(module.COMMERCE_KEYS_TABLE, "put_item",
                     FakeClientError("ProvisionedThroughputExceededException"))

    response = module.create_invoice(_body(fy=FY), "req-storage")

    assert response["statusCode"] == 503
    payload = json.loads(response["body"])
    assert payload["errorCode"] == "INVOICE_SEQUENCE_UNAVAILABLE"
    assert invoices.numbered == []
    assert items.rows == {}
    assert _reservations(module, keys) == []


def test_a_counter_storage_error_still_refuses_and_reserves_nothing(engine):
    module, keys, counter, _invoices, _items = engine
    counter.fail_with = FakeClientError("ProvisionedThroughputExceededException")

    with pytest.raises(module.InvoiceSequenceUnavailable):
        module._get_next_invoice_number(FY)

    assert _reservations(module, keys) == []


# ══════════════════════════════════════════════════════════════════════════════
# the admin preview cannot show a number that is already issued
# ══════════════════════════════════════════════════════════════════════════════

def test_the_preview_reports_the_reservation_floor_and_writes_nothing(engine):
    module, keys, counter, _invoices, _items = engine
    table = module.dynamodb.Table(module.COMMERCE_KEYS_TABLE)
    for seq in (1, 2):
        module.order_keys.reserve_invoice_number(
            table, invoice_number=f"WD/2627/{seq:05d}", fy=FY)
    counter.rows[FY] = {"fy": FY, "last_seq": 0, "prefix": "WD"}

    response = module.get_next_sequence_preview({"fy": FY}, "req-preview")

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["nextInvoiceNumber"] == "WD/2627/00003"
    # `lastSeq` still reports the raw counter, so the drift is visible rather than papered over.
    assert payload["lastSeq"] == 0
    assert payload["reservedFloorSeq"] == 2
    assert payload["reservationProbeExhausted"] is False
    assert counter.advances == 0
    assert len(_reservations(module, keys)) == 2


def test_the_preview_agrees_with_the_counter_when_nothing_has_drifted(engine):
    module, keys, counter, _invoices, _items = engine
    counter.rows[FY] = {"fy": FY, "last_seq": 7, "prefix": "WD"}

    payload = json.loads(module.get_next_sequence_preview({"fy": FY}, "req")["body"])

    assert payload["nextInvoiceNumber"] == "WD/2627/00008"
    assert payload["lastSeq"] == 7
    assert payload["reservedFloorSeq"] == 7
