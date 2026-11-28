"""PAY-6 / PAY-9: refund, failed and dispute state is written only from Razorpay's readback."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest

from lambda_utils import payment_status

_FUNCTIONS = Path(__file__).resolve().parents[2] / "amplify/functions"
_WEBHOOK = _FUNCTIONS / "payments/razorpay-webhook/handler.py"
_ENGINE = _FUNCTIONS / "payments/invoice-engine/handler.py"
REF = "WD-PAY-REFUND01"


class Recorder:
    def __init__(self, items=None):
        self.updates = []
        self.items = list(items or [])
        self.queries = []

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": list(self.items)}


@pytest.fixture
def hook(monkeypatch):
    def unexpected_aws(*_args, **_kwargs):
        raise AssertionError("no AWS in this test")

    class NoAws:
        def __getattr__(self, _name):
            return unexpected_aws

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_kw: NoAws())
    monkeypatch.setattr(boto3, "client", lambda *_a, **_kw: NoAws())
    spec = importlib.util.spec_from_file_location("razorpay_webhook_refund_under_test", _WEBHOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from lambda_utils import shared_tables
    tables = {module.PAYMENTS_TABLE: Recorder(),
              module.INVOICES_TABLE: Recorder(items=[
                  {"invoiceId": "inv-1", "providerPaymentId": "pay_1"},
                  {"invoiceId": "inv-other", "paymentId": "pay_9"}]),
              shared_tables.orders_table_name(): Recorder(),
              module.COMMERCE_KEYS_TABLE: Recorder()}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=tables.__getitem__))
    monkeypatch.setattr(module.order_keys, "resolve_order_for_provider_payment",
                        lambda _t, pid: {"orderIdRef": "ord_1", "referenceId": REF}
                        if pid == "pay_1" else None)
    from lambda_utils.integrations import razorpay_verify
    provider = {"refund": {"id": "rfnd_1", "status": "processed", "payment_id": "pay_1",
                           "amount": 3000},
                "payment": {"id": "pay_1", "status": "captured", "amount": 10000,
                            "amount_refunded": 3000, "refund_status": "partial",
                            "notes": {"referenceId": REF}},
                "dispute": {"id": "disp_1", "payment_id": "pay_1", "status": "open",
                            "phase": "chargeback", "amount": 10000, "amount_deducted": 0},
                "down": False}

    def read(key):
        def reader(entity_id):
            if provider["down"]:
                raise razorpay_verify.RazorpayUnavailable("down")
            return dict(provider[key])
        return reader

    monkeypatch.setattr(razorpay_verify, "refund_entity", read("refund"))
    monkeypatch.setattr(razorpay_verify, "payment_entity", read("payment"))
    monkeypatch.setattr(razorpay_verify, "dispute_entity", read("dispute"))
    errors = []
    monkeypatch.setattr(module.logger, "error", lambda line, *a: errors.append(line))
    return module, tables, provider, errors


def _refund_event(payment_id="pay_1"):
    return {"refund": {"entity": {"id": "rfnd_1", "payment_id": payment_id, "amount": 999999}}}


def _fields(update):
    names, values = update["ExpressionAttributeNames"], update["ExpressionAttributeValues"]
    return {names[k]: values[":" + k[1:].replace("f", "v", 1)] for k in names if k.startswith("#f")}


def test_partial_refund_records_the_sum_and_keeps_the_payment_captured(hook):
    module, tables, _provider, _errors = hook
    module._handle_refund("refund.processed", _refund_event(), "req")
    (payment_update,) = tables[module.PAYMENTS_TABLE].updates
    assert "#st" not in payment_update["ExpressionAttributeNames"]
    assert payment_update["ExpressionAttributeValues"][":sum"] == 3000
    assert payment_update["ExpressionAttributeValues"][":rs"] == "partially_refunded"
    assert payment_update["ExpressionAttributeValues"][":rids"] == {"rfnd_1"}
    (invoice_update,) = tables[module.INVOICES_TABLE].updates
    assert invoice_update["Key"] == {"invoiceId": "inv-1"}
    assert _fields(invoice_update) == {"refundStatus": "partially_refunded",
                                       "refundAmountPaise": 3000, "lastRefundId": "rfnd_1",
                                       "refundUpdatedAt": _fields(invoice_update)["refundUpdatedAt"]}
    assert "providerPaymentId = :pid" in invoice_update["ConditionExpression"]
    from lambda_utils import shared_tables
    (order_update,) = tables[shared_tables.orders_table_name()].updates
    assert order_update["Key"] == {"orderId": "ord_1"}
    assert order_update["ConditionExpression"].startswith("providerPaymentId = :pid AND")


def test_full_refund_moves_payment_invoice_and_order_to_refunded(hook):
    module, tables, provider, _errors = hook
    provider["payment"].update(amount_refunded=10000, refund_status="full", status="refunded")
    module._handle_refund("refund.processed", _refund_event(), "req")
    (payment_update,) = tables[module.PAYMENTS_TABLE].updates
    values = payment_update["ExpressionAttributeValues"]
    assert values[":st"] == payment_status.REFUNDED and values[":rs"] == "refunded"
    assert "#rank <= :rank" in payment_update["ConditionExpression"]
    assert _fields(tables[module.INVOICES_TABLE].updates[0])["paymentStatus"] == "refunded"


@pytest.mark.parametrize("change", ["pending", "mismatch"])
def test_unconfirmed_refund_writes_nothing(hook, change):
    module, tables, provider, errors = hook
    if change == "pending":
        provider["refund"]["status"] = "pending"
        module._handle_refund("refund.processed", _refund_event(), "req")
    else:
        module._handle_refund("refund.processed", _refund_event("pay_forged"), "req")
    assert all(not table.updates for table in tables.values())
    assert any('"PAYMENT_EVENT_UNVERIFIED"' in line for line in errors)


def test_refund_with_razorpay_down_raises_and_writes_nothing(hook):
    module, tables, provider, errors = hook
    provider["down"] = True
    with pytest.raises(RuntimeError):
        module._handle_refund("refund.processed", _refund_event(), "req")
    assert all(not table.updates for table in tables.values())
    assert any('"refund_unverified"' in line for line in errors)


def test_failed_state_needs_razorpay_to_say_failed(hook, monkeypatch):
    module, tables, provider, _errors = hook
    stored = []
    monkeypatch.setattr(module, "_store_payment_record",
                        lambda payment, status, _r: stored.append((payment["status"], status)))
    body = {"payment": {"entity": {"id": "pay_1", "notes": {"referenceId": "WD-PAY-FORGED01"}}}}
    module._handle_payment_failed(body, "req")          # Razorpay says captured
    assert stored == [] and not tables[module.INVOICES_TABLE].queries
    provider["payment"].update(status="failed")
    tables[module.INVOICES_TABLE].items = []
    module._handle_payment_failed(body, "req")
    assert stored == [("failed", "failed")]
    (query,) = tables[module.INVOICES_TABLE].queries
    assert query["ExpressionAttributeValues"] == {":ref": REF}   # Razorpay's reference, not the body's
    provider["down"] = True
    with pytest.raises(RuntimeError):
        module._handle_payment_failed(body, "req")
    assert stored == [("failed", "failed")]


def test_dispute_is_confirmed_recorded_and_alerted(hook):
    module, tables, provider, errors = hook
    event = {"payment.dispute": {"entity": {"id": "disp_1", "payment_id": "pay_1"}}}
    module._handle_dispute("payment.dispute.created", event, "req")
    (payment_update,) = tables[module.PAYMENTS_TABLE].updates
    recorded = {payment_update["ExpressionAttributeNames"][k]: payment_update["ExpressionAttributeValues"][":d" + k[2:]]
                for k in payment_update["ExpressionAttributeNames"]}
    assert recorded["disputeStatus"] == "open" and recorded["disputeAmountPaise"] == 10000
    assert "#st" not in payment_update["ExpressionAttributeNames"]      # rank untouched
    assert _fields(tables[module.INVOICES_TABLE].updates[0])["disputeStatus"] == "open"
    assert any('"PAYMENT_DISPUTED"' in line for line in errors)
    provider["down"] = True
    with pytest.raises(RuntimeError):
        module._handle_dispute("payment.dispute.lost", event, "req")


# ── invoice-engine: refund evidence accepts the rows the webhook now writes ──────

def _evidence_function(payment_row):
    tree = ast.parse(_ENGINE.read_text())
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_resolve_refund_evidence")
    namespace = {
        "json": json, "Dict": dict, "Optional": lambda *_: None, "pay_status": payment_status,
        "PAYMENTS_TABLE": "payments", "logger": SimpleNamespace(warning=lambda *_: None,
                                                                error=lambda *_: None),
        "dynamodb": SimpleNamespace(Table=lambda _n: SimpleNamespace(
            get_item=lambda **_kw: {"Item": payment_row})),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(_ENGINE), "exec"), namespace)
    return namespace["_resolve_refund_evidence"]


@pytest.mark.parametrize("row,expected", [
    ({"refundId": "rfnd_2", "refundIds": {"rfnd_1", "rfnd_2"}, "status": "refunded"}, "rfnd_1"),
    ({"refundId": "rfnd_1", "status": "captured", "refundStatus": "partially_refunded"}, "rfnd_1"),
    ({"refundId": "rfnd_1", "status": "captured"}, None),
    ({"refundId": "rfnd_9", "status": "refunded"}, None),
])
def test_refund_evidence_accepts_every_recorded_refund(row, expected):
    resolve = _evidence_function(row)
    got = resolve(invoice={"paymentId": "pay_1"}, body={"refundId": "rfnd_1"}, request_id="req")
    assert got == expected
