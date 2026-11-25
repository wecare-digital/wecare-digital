"""Exercise the actual payment webhook entry point with only synthetic I/O."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError


_FUNCTIONS = Path(__file__).resolve().parents[2] / "amplify/functions"
_SOURCE = _FUNCTIONS / "payments/razorpay-webhook/handler.py"
_DEDUP_SOURCE = _FUNCTIONS / "shared/lambda_utils/webhook_dedup.py"
_SECRET = "test-only-webhook-signing-key"


def _condition_failed():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


class FakeLeaseTable:
    """Model just the conditional DynamoDB operations used by the real lease code."""

    def __init__(self):
        self.rows = {}
        self.completions = []

    def put_item(self, *, Item, ConditionExpression, ExpressionAttributeValues=None):
        event_id = Item["eventId"]
        row = self.rows.get(event_id)
        if ConditionExpression == "attribute_not_exists(eventId)":
            if row is not None:
                raise _condition_failed()
        else:
            assert ConditionExpression == "leaseExpiresAt = :seen"
            if row is None or row.get("leaseExpiresAt") != ExpressionAttributeValues[":seen"]:
                raise _condition_failed()
        self.rows[event_id] = dict(Item)

    def get_item(self, *, Key):
        row = self.rows.get(Key["eventId"])
        return {"Item": dict(row)} if row is not None else {}

    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeValues):
        assert UpdateExpression == "SET completedAt = :now"
        event_id = Key["eventId"]
        self.completions.append(event_id)
        self.rows[event_id]["completedAt"] = ExpressionAttributeValues[":now"]


@pytest.fixture
def webhook(monkeypatch):
    """Install a no-network boundary before executing handler imports."""
    def unexpected_aws(*_args, **_kwargs):
        raise AssertionError("The synthetic webhook must never call AWS")

    class NoAws:
        def __getattr__(self, _name):
            return unexpected_aws

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_kw: NoAws())
    monkeypatch.setattr(boto3, "client", lambda *_a, **_kw: NoAws())
    spec = importlib.util.spec_from_file_location("razorpay_webhook_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Use a fresh instance so importing with fake boto3 cannot leave a fake
    # client cached inside a shared module used by the rest of the test suite.
    dedup_spec = importlib.util.spec_from_file_location("lambda_utils.webhook_dedup", _DEDUP_SOURCE)
    webhook_dedup = importlib.util.module_from_spec(dedup_spec)
    dedup_spec.loader.exec_module(webhook_dedup)
    monkeypatch.setitem(sys.modules, dedup_spec.name, webhook_dedup)
    table = FakeLeaseTable()
    clock = SimpleNamespace(now=1000)
    monkeypatch.setattr(webhook_dedup, "_table", lambda: table)
    monkeypatch.setattr(webhook_dedup, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(module, "_get_webhook_secret", lambda: _SECRET)
    audits = []
    monkeypatch.setattr(module, "_log_webhook_event", lambda *args: audits.append(args))
    return module, table, clock, audits, webhook_dedup.DEFAULT_LEASE_SECONDS


def _event(kind="payment.captured", entity_kind="payment", entity_id="pay_synthetic"):
    body = json.dumps({
        "account_id": "acc_synthetic",
        "created_at": 1000,
        "event": kind,
        "payload": {entity_kind: {"entity": {"id": entity_id, "amount": 12345}}},
    })
    return {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-razorpay-signature": hmac.new(
            _SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()},
        "body": body,
    }


def _payload(response):
    return response["statusCode"], json.loads(response["body"])


def test_completed_capture_is_not_dispatched_again(monkeypatch, webhook):
    module, leases, clock, audits, duration = webhook
    calls = []

    def capture(payload, _request_id):
        assert not leases.completions, "success must not be recorded before the work finishes"
        calls.append(payload["payment"]["entity"]["id"])

    monkeypatch.setattr(module, "_handle_payment_captured", capture)
    event = _event()
    assert _payload(module.handler(event, None)) == (200, {"status": "ok", "event": "payment.captured"})
    clock.now += duration + 1
    assert _payload(module.handler(event, None)) == (200, {"status": "already_processed"})
    assert calls == ["pay_synthetic"]
    assert len(audits) == len(leases.completions) == 1
    assert audits[0][3] == leases.completions[0]


def test_failed_capture_stays_uncompleted_and_expired_lease_allows_recovery(monkeypatch, webhook):
    module, leases, clock, audits, duration = webhook
    calls = []

    def capture(payload, _request_id):
        calls.append(payload["payment"]["entity"]["id"])
        if len(calls) == 1:
            raise RuntimeError("synthetic downstream failure")

    monkeypatch.setattr(module, "_handle_payment_captured", capture)
    event = _event()
    assert _payload(module.handler(event, None)) == (500, {"error": "Internal server error"})
    assert len(leases.rows) == 1
    assert all("completedAt" not in row for row in leases.rows.values())
    assert leases.completions == []

    clock.now += duration + 1
    assert _payload(module.handler(event, None)) == (200, {"status": "ok", "event": "payment.captured"})
    assert _payload(module.handler(event, None)) == (200, {"status": "already_processed"})
    assert calls == ["pay_synthetic", "pay_synthetic"]
    assert len(audits) == 2
    assert audits[0][3] == audits[1][3] == leases.completions[0]
    assert len(leases.completions) == 1


def test_distinct_same_second_refunds_do_not_share_a_dedup_key(monkeypatch, webhook):
    module, leases, _clock, audits, _duration = webhook
    calls = []
    monkeypatch.setattr(module, "_handle_refund", lambda kind, payload, _request_id:
                        calls.append((kind, payload["refund"]["entity"]["id"])))

    for refund_id in ("rfnd_one", "rfnd_two"):
        event = _event("refund.processed", "refund", refund_id)
        assert _payload(module.handler(event, None)) == (
            200, {"status": "ok", "event": "refund.processed"})
    assert calls == [("refund.processed", "rfnd_one"), ("refund.processed", "rfnd_two")]
    assert len({audit[3] for audit in audits}) == 2
    assert len(leases.completions) == 2


def test_reconciliation_waits_for_provider_capture_evidence(monkeypatch, webhook):
    from lambda_utils.ecommerce import website_checkout
    from lambda_utils.integrations import razorpay_verify

    module, _leases, _clock, _audits, _duration = webhook
    reference = "WD-PAY-TEST001"
    order_id = "order_test"
    payment_id = "pay_test"
    attempt = {
        "status": "PAYMENT_PENDING", "referenceId": reference,
        "checkoutMode": website_checkout.CHECKOUT_MODE_WEBSITE,
        "providerOrderId": order_id,
    }
    key_table = object()
    attempts = SimpleNamespace(get_item=lambda **request: {
        "Item": attempt if request == {
            "Key": {"paymentAttemptId": "attempt_test"}, "ConsistentRead": True,
        } else {},
    })
    tables = {module.COMMERCE_KEYS_TABLE: key_table, module.PAYMENT_ATTEMPTS_TABLE: attempts}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=tables.__getitem__))
    monkeypatch.setattr(module.order_keys, "resolve_payment_reference", lambda table, ref: (
        {"paymentAttemptId": "attempt_test"} if (table, ref) == (key_table, reference) else {}))
    monkeypatch.setattr(razorpay_verify, "order_is_paid",
                        lambda _order_id: (True, payment_id, 12500, "INR"))
    attempts_read = []

    def read_capture(payment):
        attempts_read.append(payment)
        if len(attempts_read) == 1:
            raise razorpay_verify.RazorpayUnavailable("synthetic outage")
        return True, 12500, "INR", order_id

    monkeypatch.setattr(razorpay_verify, "payment_capture_details", read_capture)
    captures = []
    monkeypatch.setattr(module, "_handle_payment_captured",
                        lambda payload, _request_id: captures.append(payload))
    event = {"internalAction": "reconcileReference", "referenceId": reference}
    assert module.handler(event, None) == {"outcome": "provider_unavailable"}
    assert captures == []

    assert module.handler(event, None) == {"outcome": "reconciled"}
    assert attempts_read == [payment_id, payment_id]
    assert captures == [{"payment": {"entity": {
        "id": payment_id, "order_id": order_id, "status": "captured",
        "amount": 12500, "currency": "INR", "notes": {"referenceId": reference},
    }}}]
