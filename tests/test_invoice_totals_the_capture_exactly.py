"""An invoice raised from a captured payment totals EXACTLY the capture, in integer paise.

WHAT THIS FILE IS FOR
---------------------
`create_invoice_from_payment` used to read `payment['amountInRupees']` - a display STRING - put it
in as a single line item, and let `create_invoice` apply the default 18% GST on top. So a 100.00
capture produced a 118.00 invoice stamped PAID: eighteen rupees the customer was never charged,
on a GST document, with the webhook caller deliberately sending neither items nor a `gstRate` so
the default always applied.

D3 is the decision these tests pin: a captured amount is GST-INCLUSIVE. The rate decides the
SPLIT and never the total, the taxable value is back-calculated, the tax is the REMAINDER, and
the final figure is compared to the capture with exact integer equality before a GST number is
consumed. "Exact" is the whole property: a capture is compared with integer equality elsewhere on
this path, so a one-paise drift is not cosmetic - it refuses a payment that actually settled.

TECHNIQUE
---------
Same handler-loading fixture as `tests/test_invoice_number_reservation.py`: the real module under
`patch('boto3.resource')`, pointed at in-memory tables. The commerce-keys table is
`crm_fake_dynamo` because `create_invoice` now reserves the invoice number there (FEAT-001) and
that fake genuinely evaluates `attribute_not_exists`. The counter is a purpose-built fake that
exposes `advances`, so "no GST number was consumed" is MEASURED rather than inferred - that is
what makes the refusal tests mean anything.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import boto3.dynamodb.conditions  # real Dynamo resource loads this; the fixture mocks construction

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
sys.path.insert(0, str(Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402

FY = "2026-2027"
#: A placeholder, never a real customer number.
PHONE = "+919999999999"
PAYMENT_ID = "pay_EXAMPLE0000001"


class _CounterTable:
    """The GST counter row, keyed `fy`, with `advances` exposed.

    `advances` is the measurement every refusal test below depends on: a refusal must leave the
    consecutive series untouched, because a number cannot be reassigned once it has gone out.
    """

    def __init__(self) -> None:
        self.rows: dict = {}
        self.advances = 0

    def update_item(self, Key=None, **_):
        self.advances += 1
        fy = (Key or {})["fy"]
        row = self.rows.setdefault(fy, {"fy": fy, "last_seq": 0, "prefix": "WD"})
        row["last_seq"] = int(row["last_seq"]) + 1
        return {"Attributes": dict(row)}

    def get_item(self, Key=None, **_):
        row = self.rows.get((Key or {})["fy"])
        return {"Item": dict(row)} if row else {}


class _InvoicesTable:
    """Key `invoiceId`. Enough of the table for `create_invoice` to run end to end."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def scan(self, FilterExpression="", ExpressionAttributeValues=None, **_):
        values = ExpressionAttributeValues or {}
        matched = [dict(row) for row in self.rows.values()
                   if (":ref" in values and row.get("referenceId") == values[":ref"])
                   or (":pid" in values and row.get("paymentId") == values[":pid"])]
        return {"Items": matched}

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        self.rows[item["invoiceId"]] = item
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
    """Composite `(invoiceId, itemIndex)`, so the stored lines can be reconciled."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        self.rows[(item["invoiceId"], int(item["itemIndex"]))] = item
        return {}

    def query(self, **_):
        return {"Items": []}

    def lines_for(self, invoice_id: str) -> list:
        return [row for (inv, _idx), row in sorted(self.rows.items()) if inv == invoice_id]


class _PaymentsTable:
    """The captured-payment row the webhook wrote. One row, returned to the engine's scan."""

    def __init__(self) -> None:
        self.rows: list = []

    def scan(self, **_):
        return {"Items": [dict(row) for row in self.rows]}


class _ContactsTable:
    """No contact. The engine's lookup is wrapped in its own try/except, so empty is a valid
    answer and keeps these tests about money rather than about the CRM."""

    def query(self, **_):
        return {"Items": []}

    def scan(self, **_):
        return {"Items": []}


@pytest.fixture
def engine(monkeypatch):
    """The real handler module, imported with no AWS, pointed at in-memory tables."""
    monkeypatch.syspath_prepend(str(ROOT / "amplify/functions/shared"))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    name = "_invoice_exact_total_engine"
    spec = importlib.util.spec_from_file_location(name, FUNCTION)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)

    keys = FakeDynamo({module.COMMERCE_KEYS_TABLE: "orderId"})
    counter = _CounterTable()
    invoices = _InvoicesTable()
    items = _ItemsTable()
    payments = _PaymentsTable()
    by_name = {
        module.COMMERCE_KEYS_TABLE: keys.Table(module.COMMERCE_KEYS_TABLE),
        module.INVOICE_SEQ_TABLE: counter,
        module.INVOICES_TABLE: invoices,
        module.INVOICE_ITEMS_TABLE: items,
        module.PAYMENTS_TABLE: payments,
        module.CONTACTS_TABLE: _ContactsTable(),
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
    return module, keys, counter, invoices, items, payments


def _inclusive_body(total_paise: int, **overrides) -> dict:
    body = {
        "referenceId": "WD-PAY-EXACT001",
        "customerPhone": PHONE,
        "entryPoint": "pay_flow",
        "items": [{"name": "Payment", "amount": 1.0, "quantity": 1}],
        "gstRate": 18,
        "currency": "INR",
        "fy": FY,
        "amountIsTaxInclusive": True,
        "expectedTotalPaise": total_paise,
    }
    body.update(overrides)
    return body


def _created(module, body, request_id="req-exact"):
    """`create_invoice` plus the stored row, so every assertion reads what was PERSISTED."""
    response = module.create_invoice(body, request_id)
    payload = json.loads(response["body"])
    return response["statusCode"], payload


def _stored(invoices, invoice_id: str) -> dict:
    return invoices.rows[invoice_id]


def _paise(value) -> int:
    """The stored rupee figure as exact integer paise. No float, no tolerance."""
    return int(Decimal(str(value)) * 100)


# ══════════════════════════════════════════════════════════════════════════════
# the helpers, as arithmetic
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("total_paise", [
    1, 2, 99, 100, 101, 10000, 10001, 33333, 59900, 123457, 999999999,
])
@pytest.mark.parametrize("rate", ["0", "5", "12", "18", "28", "0.5", "18.5", "100"])
def test_the_inclusive_split_always_sums_back_to_the_total(engine, total_paise, rate):
    """The remainder rule, swept. `taxable + tax == total` for every rate and every amount."""
    module = engine[0]
    taxable, tax = module._back_calculate_inclusive(total_paise, Decimal(rate))
    assert isinstance(taxable, int) and isinstance(tax, int)
    assert taxable + tax == total_paise
    assert 0 <= tax <= total_paise


def test_a_zero_rate_leaves_the_whole_amount_taxable_and_no_tax(engine):
    module = engine[0]
    assert module._back_calculate_inclusive(10000, Decimal("0")) == (10000, 0)


def test_the_eighteen_percent_split_of_ten_thousand_paise_is_the_textbook_figure(engine):
    """100.00 inclusive of 18% is 84.75 taxable and 15.25 tax - not 100.00 plus 18.00."""
    module = engine[0]
    assert module._back_calculate_inclusive(10000, Decimal("18")) == (8475, 1525)


@pytest.mark.parametrize("tax_paise", [0, 1, 2, 45, 46, 1525, 33333])
def test_the_tax_halves_sum_to_the_tax_with_the_odd_paise_on_cgst(engine, tax_paise):
    module = engine[0]
    cgst, sgst = module._split_tax_halves(tax_paise)
    assert cgst + sgst == tax_paise
    assert cgst >= sgst           # the odd paise is always on CGST, never on whichever is nearer
    assert cgst - sgst == tax_paise % 2


def test_the_rendered_tax_halves_sum_to_the_rendered_tax(engine):
    """What the two printed GST lines are: `tax / 2` twice would print 0.22 and 0.22 for 0.45."""
    module = engine[0]
    cgst, sgst = module._tax_halves_rupees("0.45")
    assert (cgst, sgst) == (Decimal("0.23"), Decimal("0.22"))
    assert cgst + sgst == Decimal("0.45")


def test_a_stored_tax_that_is_not_whole_paise_still_renders_a_breakdown_that_adds_up(engine):
    """A legacy row is DISPLAYED, not refused - but the two halves still sum to the printed tax."""
    module = engine[0]
    cgst, sgst = module._tax_halves_rupees("0.455")
    assert cgst + sgst == Decimal("0.455")


# ══════════════════════════════════════════════════════════════════════════════
# the brief's named case, and the amounts whose split is not a whole paise
# ══════════════════════════════════════════════════════════════════════════════

def test_a_ten_thousand_paise_capture_is_stored_as_exactly_ten_thousand_paise(engine):
    """The defect, inverted: 100.00 captured is a 100.00 invoice, not a 118.00 one."""
    module, keys, counter, invoices, items, _payments = engine

    status, payload = _created(module, _inclusive_body(10000))

    assert status == 201
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row["total"]) == 10000
    assert _paise(row["subtotal"]) == 8475
    assert _paise(row["tax"]) == 1525
    assert _paise(row["subtotal"]) + _paise(row["tax"]) == _paise(row["total"])
    assert _paise(row["convenienceFee"]) == 0
    cgst, sgst = module._split_tax_halves(_paise(row["tax"]))
    assert cgst + sgst == _paise(row["tax"])
    assert counter.advances == 1


@pytest.mark.parametrize("total_paise", [1, 2, 10000, 10001, 33333, 99999, 123457])
def test_every_capture_is_totalled_to_the_paise_with_no_drift(engine, total_paise):
    """The amounts whose 18%-inclusive split is not a whole paise. The remainder rule holds."""
    module, _keys, _counter, invoices, items, _payments = engine

    status, payload = _created(module, _inclusive_body(total_paise))

    assert status == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    subtotal_paise = _paise(row["subtotal"])
    tax_paise = _paise(row.get("tax", 0))
    assert _paise(row["total"]) == total_paise
    assert subtotal_paise + tax_paise == total_paise
    cgst, sgst = module._split_tax_halves(tax_paise)
    assert cgst + sgst == tax_paise
    # The stored LINE reconciles to the stored subtotal, which is what makes the document
    # internally consistent rather than merely correct in its total.
    lines = items.lines_for(payload["invoiceId"])
    assert len(lines) == 1
    assert _paise(lines[0]["amount"]) * int(lines[0]["quantity"]) == subtotal_paise


def test_a_zero_gst_rate_leaves_no_tax_and_a_total_equal_to_the_capture(engine):
    module, _keys, _counter, invoices, _items, _payments = engine

    status, payload = _created(module, _inclusive_body(10000, gstRate=0))

    assert status == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row.get("tax", 0)) == 0
    assert _paise(row["subtotal"]) == 10000
    assert _paise(row["total"]) == 10000


def test_a_captured_amount_grows_no_fee_charge_or_shipping_line(engine):
    """`entryPoint='pay_flow'` is the branch that auto-adds 2.5% + GST. Money already taken
    cannot grow a charge, so every additive component is forced to zero and the total still
    equals the capture."""
    module, _keys, _counter, invoices, items, _payments = engine

    status, payload = _created(module, _inclusive_body(
        10000, convenienceFee=25, shipping=50, handling=10, discount=5,
        greenPacking=15, notificationFee=7))

    assert status == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row["total"]) == 10000
    for field in ("convenienceFee", "shipping", "handling", "discount"):
        assert _paise(row.get(field, 0)) == 0, field
    # and no Green Packing / Notification Fee line was appended behind the total's back
    assert len(items.lines_for(payload["invoiceId"])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# the refusals, every one of them before a GST number is consumed
# ══════════════════════════════════════════════════════════════════════════════

def test_the_mode_requires_the_expected_total_and_never_falls_back(engine):
    """Absent `expectedTotalPaise` is a 400. A silent fall back to the additive path would
    reintroduce the 118-for-100 defect on exactly the caller that asked not to have it."""
    module, keys, counter, invoices, items, _payments = engine
    body = _inclusive_body(10000)
    del body["expectedTotalPaise"]

    status, payload = _created(module, body)

    assert status == 400
    assert payload["errorCode"] == "EXPECTED_TOTAL_PAISE_REQUIRED"
    assert counter.advances == 0
    assert invoices.numbered == []
    assert items.rows == {}


@pytest.mark.parametrize("bad", [0, -1, "10000.5", "nonsense", True])
def test_an_unusable_expected_total_refuses_before_any_number_is_consumed(engine, bad):
    module, _keys, counter, invoices, items, _payments = engine

    status, payload = _created(module, _inclusive_body(10000, expectedTotalPaise=bad))

    assert status == 400
    assert payload["errorCode"] == "EXPECTED_TOTAL_PAISE_INVALID"
    assert counter.advances == 0
    assert invoices.numbered == []


def test_a_total_that_disagrees_with_the_capture_refuses_and_burns_no_number(engine,
                                                                            monkeypatch):
    """The invariant is a BACKSTOP, so it is tested by breaking the split it guards.

    In the shipped code the split is a remainder of the same figure the comparison uses, so the
    two cannot disagree - which is the design. This test substitutes a split that sums to one
    paise more, i.e. exactly the regression a future edit could reintroduce, and asserts the
    refusal happens with no document written and the GST counter untouched.
    """
    module, keys, counter, invoices, items, _payments = engine
    monkeypatch.setattr(module, "_back_calculate_inclusive",
                        lambda total_paise, gst_rate: (int(total_paise), 1))

    status, payload = _created(module, _inclusive_body(10000))

    assert status == 400
    assert payload["errorCode"] == "INVOICE_TOTAL_MISMATCH"
    assert payload["expectedTotalPaise"] == 10000
    assert payload["computedTotalPaise"] == 10001
    # The sequence table was never updated: a refusal issues no number, and a number cannot be
    # reassigned once it has gone out.
    assert counter.advances == 0
    assert counter.rows == {}
    assert invoices.numbered == []
    assert items.rows == {}
    assert [row for row in keys.all_rows(module.COMMERCE_KEYS_TABLE)
            if str(row.get("orderId", "")).startswith(
                module.order_keys.INVOICE_NUMBER_PREFIX)] == []
    assert any("invoice_total_mismatch" in str(call)
               for call in module.logger.error.mock_calls)


@pytest.mark.parametrize("code_field", ["couponCode", "giftCardCode"])
def test_a_coupon_or_gift_card_cannot_be_applied_to_money_already_captured(engine, code_field):
    module, _keys, counter, invoices, _items, _payments = engine

    status, payload = _created(module, _inclusive_body(10000, **{code_field: "SAVE10"}))

    assert status == 400
    assert payload["errorCode"] == "AMOUNT_ALREADY_CAPTURED"
    assert counter.advances == 0
    assert invoices.numbered == []


# ══════════════════════════════════════════════════════════════════════════════
# the additive path, unchanged when the flag is absent
# ══════════════════════════════════════════════════════════════════════════════

def test_the_additive_path_still_produces_its_previous_figures(engine):
    """The one property this change must not break: with no flag, the tax goes ON TOP and the
    2.5% + GST convenience fee is still added, to the same figures as before.
    1000.00 + 180.00 tax = 1180.00 collection; 2.5% = 29.50; 18% of that = 5.31; total 1214.81.
    """
    module, _keys, counter, invoices, items, _payments = engine
    body = {
        "referenceId": "WD-PAY-ADDITIVE1",
        "customerPhone": PHONE,
        "entryPoint": "pay_flow",
        "items": [{"name": "Service", "amount": 1000.0, "quantity": 1}],
        "gstRate": 18,
        "currency": "INR",
        "fy": FY,
    }

    status, payload = _created(module, body)

    assert status == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row["subtotal"]) == 100000
    assert _paise(row["tax"]) == 18000
    assert _paise(row["convenienceFee"]) == 3481
    assert _paise(row["total"]) == 121481
    # The additive line is stored at the GROSS item amount, as it always was.
    lines = items.lines_for(payload["invoiceId"])
    assert _paise(lines[0]["amount"]) == 100000
    assert counter.advances == 1


def test_the_additive_path_is_untouched_by_an_expected_total_it_did_not_ask_for(engine):
    """`expectedTotalPaise` alone does nothing. The mode is the flag, and only the flag."""
    module, _keys, _counter, invoices, _items, _payments = engine
    body = {
        "referenceId": "WD-PAY-ADDITIVE2",
        "customerPhone": PHONE,
        "entryPoint": "pay_flow",
        "items": [{"name": "Service", "amount": 1000.0, "quantity": 1}],
        "gstRate": 18,
        "currency": "INR",
        "fy": FY,
        "expectedTotalPaise": 100000,
    }

    status, payload = _created(module, body)

    assert status == 201, payload
    assert _paise(_stored(invoices, payload["invoiceId"])["total"]) == 121481


# ══════════════════════════════════════════════════════════════════════════════
# create_invoice_from_payment: the integer, not the display string
# ══════════════════════════════════════════════════════════════════════════════

def _payment_row(**overrides) -> dict:
    row = {
        "paymentId": PAYMENT_ID,
        "id": PAYMENT_ID,
        "orderId": "order_EXAMPLE00001",
        "referenceId": "WD-PAY-CAPTURE1",
        "status": "captured",
        # PAISE, as `razorpay-webhook` writes it.
        "amount": Decimal(10000),
        # The display string beside it, which is what the old code read.
        "amountInRupees": "100.00",
        "currency": "INR",
        "contact": PHONE,
        "createdAt": Decimal(1791374820),
    }
    row.update(overrides)
    return row


def test_a_hundred_rupee_capture_becomes_a_hundred_rupee_invoice(engine):
    """The C-level defect, as a regression: this used to come out at 118.00, marked PAID."""
    module, _keys, counter, invoices, items, payments = engine
    payments.rows.append(_payment_row())

    response = module.create_invoice_from_payment({"paymentId": PAYMENT_ID}, "req-capture")
    payload = json.loads(response["body"])

    assert response["statusCode"] == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row["total"]) == 10000
    assert _paise(row["subtotal"]) == 8475
    assert _paise(row["tax"]) == 1525
    assert _paise(row["subtotal"]) + _paise(row["tax"]) == _paise(row["total"])
    # The document still records that the money arrived.
    assert row["status"] == "paid"
    assert row["paymentStatus"] == "captured"
    assert counter.advances == 1


def test_the_captured_integer_wins_over_a_disagreeing_display_string(engine):
    """`amount` is the authority. A stale or wrong `amountInRupees` must not reach the total."""
    module, _keys, _counter, invoices, _items, payments = engine
    payments.rows.append(_payment_row(amount=Decimal(59900), amountInRupees="1.00"))

    response = module.create_invoice_from_payment({"paymentId": PAYMENT_ID}, "req-authority")
    payload = json.loads(response["body"])

    assert response["statusCode"] == 201, payload
    assert _paise(_stored(invoices, payload["invoiceId"])["total"]) == 59900


def test_a_configurable_rate_changes_the_split_and_never_the_total(engine):
    module, _keys, _counter, invoices, _items, payments = engine
    payments.rows.append(_payment_row())

    response = module.create_invoice_from_payment(
        {"paymentId": PAYMENT_ID, "gstRate": 5}, "req-rate")
    payload = json.loads(response["body"])

    assert response["statusCode"] == 201, payload
    row = _stored(invoices, payload["invoiceId"])
    assert _paise(row["total"]) == 10000
    assert _paise(row["subtotal"]) + _paise(row["tax"]) == 10000
    assert _paise(row["tax"]) != 1525  # the rate moved the split, not the total


@pytest.mark.parametrize("amount", [None, "", 0, "nonsense", Decimal("0.5")])
def test_a_payment_with_no_usable_integer_amount_refuses_rather_than_invoicing_zero(engine,
                                                                                   amount):
    """A zero-rupee tax invoice against a real capture, with a GST number burned on it, is worse
    than no invoice - the number cannot be reassigned."""
    module, _keys, counter, invoices, items, payments = engine
    payments.rows.append(_payment_row(amount=amount))

    response = module.create_invoice_from_payment({"paymentId": PAYMENT_ID}, "req-unusable")
    payload = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert payload["errorCode"] == "PAYMENT_AMOUNT_UNUSABLE"
    assert counter.advances == 0
    assert invoices.rows == {}
    assert items.rows == {}
