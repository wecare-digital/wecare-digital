"""PAY-1 / PAY-7: a failed post-capture step is retried, not acknowledged, and finished later."""
import hashlib
import hmac
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError

_FUNCTIONS = Path(__file__).resolve().parents[2] / "amplify/functions"
_SOURCE = _FUNCTIONS / "payments/razorpay-webhook/handler.py"
_DEDUP_SOURCE = _FUNCTIONS / "shared/lambda_utils/webhook_dedup.py"
_SECRET = "test-only-webhook-signing-key"
REF = "WD-PAY-ABCDEF12"


def _conditional():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "Op")


class Table:
    """In-memory rows keyed by one attribute, with the conditions these paths use."""

    def __init__(self, key="orderId", items=None):
        self.key = key
        self.rows = {}
        self.queries = []
        self.items = list(items or [])
        self.updates = []

    def put_item(self, *, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        exists = Item[self.key] in self.rows
        if ConditionExpression and ConditionExpression.startswith("attribute_not_exists") and exists:
            raise _conditional()
        if ConditionExpression == "leaseExpiresAt = :seen":
            row = self.rows.get(Item[self.key])
            if row is None or row.get("leaseExpiresAt") != ExpressionAttributeValues[":seen"]:
                raise _conditional()
        self.rows[Item[self.key]] = dict(Item)

    def get_item(self, *, Key, ConsistentRead=False):
        row = self.rows.get(Key[self.key])
        return {"Item": dict(row)} if row is not None else {}

    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeValues=None,
                    ConditionExpression=None, ExpressionAttributeNames=None, ReturnValues=None):
        self.updates.append((Key[self.key], UpdateExpression, ConditionExpression,
                             dict(ExpressionAttributeValues or {})))
        row = self.rows.get(Key[self.key])
        values = ExpressionAttributeValues or {}
        if UpdateExpression == "SET completedAt = :now":
            row["completedAt"] = values[":now"]
            return {}
        if ConditionExpression == "leaseExpiresAt = :mine AND attribute_not_exists(completedAt)":
            if row is None or row.get("leaseExpiresAt") != values[":mine"] or "completedAt" in row:
                raise _conditional()
            row["leaseExpiresAt"] = values[":released"]
            return {}
        if ConditionExpression and ConditionExpression.startswith("attribute_exists") and row is None:
            raise _conditional()
        if "deliveryStatus = :done" in UpdateExpression:
            row["deliveryStatus"] = values[":done"]
        return {}

    def delete_item(self, *, Key, ConditionExpression=None, ExpressionAttributeValues=None):
        row = self.rows.get(Key[self.key])
        if row is None or row.get("deliveryStatus") != ExpressionAttributeValues[":claimed"]:
            raise _conditional()
        del self.rows[Key[self.key]]

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.items and isinstance(self.items[0], list):
            page = self.items.pop(0)
            return {"Items": page, **({"LastEvaluatedKey": {"k": 1}} if self.items else {})}
        return {"Items": list(self.items)}


@pytest.fixture
def webhook(monkeypatch):
    def unexpected_aws(*_args, **_kwargs):
        raise AssertionError("The synthetic webhook must never call AWS")

    class NoAws:
        def __getattr__(self, _name):
            return unexpected_aws

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_kw: NoAws())
    monkeypatch.setattr(boto3, "client", lambda *_a, **_kw: NoAws())
    spec = importlib.util.spec_from_file_location("razorpay_webhook_retry_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dedup_spec = importlib.util.spec_from_file_location("lambda_utils.webhook_dedup", _DEDUP_SOURCE)
    dedup = importlib.util.module_from_spec(dedup_spec)
    dedup_spec.loader.exec_module(dedup)
    monkeypatch.setitem(sys.modules, dedup_spec.name, dedup)
    leases = Table(key="eventId")
    clock = SimpleNamespace(now=1000)
    monkeypatch.setattr(dedup, "_table", lambda: leases)
    monkeypatch.setattr(dedup, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(module, "_get_webhook_secret", lambda: _SECRET)
    monkeypatch.setattr(module, "_log_webhook_event", lambda *args: None)
    return module, leases, clock


def _event(kind="payment.captured", entity_id="pay_synthetic"):
    body = json.dumps({"account_id": "acc", "created_at": 1000, "event": kind,
                       "payload": {"payment": {"entity": {"id": entity_id, "amount": 100}}}})
    return {"requestContext": {"http": {"method": "POST"}},
            "headers": {"x-razorpay-signature": hmac.new(
                _SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()},
            "body": body}


def _answer(response):
    return response["statusCode"], json.loads(response["body"])


# ── the webhook answer ───────────────────────────────────────────────────────────

def test_a_lease_held_by_an_unfinished_attempt_is_answered_409(monkeypatch, webhook):
    module, leases, _clock = webhook
    calls = []
    monkeypatch.setattr(module, "_handle_payment_captured", lambda *a, **k: calls.append(a))
    leases.rows["pay_synthetic:payment.captured"] = {
        "eventId": "pay_synthetic:payment.captured", "leaseExpiresAt": 1900}
    assert _answer(module.handler(_event(), None)) == (409, {"status": "in_progress"})
    assert calls == []
    leases.rows["pay_synthetic:payment.captured"]["completedAt"] = 999
    assert _answer(module.handler(_event(), None)) == (200, {"status": "already_processed"})


def test_a_failed_capture_releases_its_lease_for_the_next_retry(monkeypatch, webhook):
    module, leases, _clock = webhook
    calls = []

    def capture(payload, _request_id, **_kw):
        calls.append(payload["payment"]["entity"]["id"])
        if len(calls) == 1:
            raise RuntimeError("Invoice receipt delivery is pending")

    monkeypatch.setattr(module, "_handle_payment_captured", capture)
    assert _answer(module.handler(_event(), None))[0] == 500
    row = leases.rows["pay_synthetic:payment.captured"]
    assert "completedAt" not in row and row["leaseExpiresAt"] == 1000
    # Same second, no lease expiry needed: Razorpay's retry is processed.
    assert _answer(module.handler(_event(), None)) == (200, {"status": "ok", "event": "payment.captured"})
    assert calls == ["pay_synthetic", "pay_synthetic"]


def test_error_log_carries_an_alert(monkeypatch, webhook, caplog):
    module, _leases, _clock = webhook
    monkeypatch.setattr(module, "_handle_payment_captured",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    records = []
    monkeypatch.setattr(module.logger, "error", lambda line, *a: records.append(line))
    module.handler(_event(), None)
    errors = [json.loads(line) for line in records if '"webhook_error"' in line]
    assert errors and errors[0]["alert"] == "NEEDS_RECONCILIATION"


# ── projection failure quarantine ────────────────────────────────────────────────

def test_projection_failure_quarantines_under_the_payment_id(monkeypatch, webhook):
    module, _leases, _clock = webhook
    from lambda_utils.ecommerce import paid_invoice_order, wa_payment_request
    tables = {}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(
        Table=lambda name: tables.setdefault(name, Table())))
    monkeypatch.setattr(paid_invoice_order, "materialize",
                        lambda **_kw: (_ for _ in ()).throw(ValueError("evidence")))
    parked = []
    monkeypatch.setattr(module.order_keys, "record_capture_quarantine",
                        lambda _t, **kw: parked.append(kw))
    outcome = {"hasOrder": True, "checkoutMode": wa_payment_request.WA_NATIVE_CHECKOUT_MODE}
    with pytest.raises(RuntimeError):
        module._materialize_paid_invoice_order(REF, outcome, "req", payment_id="pay_9")
    assert parked == [{"payment_id": "pay_9", "reference_id": REF,
                       "outcome": "PAID_ORDER_PROJECTION_FAILED",
                       "extra": {"stage": "ORDER_PROJECTION"}}]


# ── post-payment ordering ────────────────────────────────────────────────────────

def _post_payment_fixture(monkeypatch, module, *, delivered):
    order = []
    invoices = Table(key="invoiceId")
    invoices.rows["inv-1"] = {"invoiceId": "inv-1", "vaultFileId": "file-1",
                              "vaultCustomerId": "cust-1"}
    attempts = Table(key="paymentAttemptId")
    attempts.rows["pa_1"] = {"paymentAttemptId": "pa_1", "providerOrderId": "order_1"}
    tables = {module.INVOICES_TABLE: invoices, module.PAYMENT_ATTEMPTS_TABLE: attempts,
              module.COMMERCE_KEYS_TABLE: Table()}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=tables.__getitem__))

    class Lambda:
        def invoke(self, **_kw):
            body = {"invoiceId": "inv-1", "invoiceNumber": "WD/2627/A/00009"}
            return {"Payload": io.BytesIO(json.dumps({"body": json.dumps(body)}).encode())}

    monkeypatch.setattr(module, "lambda_client", Lambda())
    monkeypatch.setattr(module, "_ensure_invoice_asset", lambda *_a: None)
    monkeypatch.setattr(module, "_start_native_fulfilment",
                        lambda *a, **k: order.append("order_status"))
    monkeypatch.setattr(module, "_deliver_invoice_on_whatsapp",
                        lambda *a: order.append("receipt") or delivered)
    monkeypatch.setattr(module, "_receipt_delivery_should_retry", lambda *a: True)
    monkeypatch.setattr(module.order_keys, "resolve_payment_reference",
                        lambda _t, _r: {"paymentAttemptId": "pa_1"})
    monkeypatch.setattr(module, "_dispatch_vault_settlement",
                        lambda **kw: order.append(("vault", kw["razorpay_order_id"])) or True)
    return order


def test_vault_dispatch_runs_before_the_receipt_retry_raise(monkeypatch, webhook):
    module, _leases, _clock = webhook
    order = _post_payment_fixture(monkeypatch, module, delivered=False)
    state = {}
    with pytest.raises(RuntimeError, match="receipt delivery is pending"):
        module._post_payment_handler("pay_1", "+919000000001", "", "", {}, "req",
                                     reference_id=REF, state=state)
    assert order == ["order_status", "receipt", ("vault", "order_1")]
    assert state["pending"] == ["receipt"] and state["step"] == "receipt"


def test_resume_sends_no_order_status_and_does_not_raise(monkeypatch, webhook):
    module, _leases, _clock = webhook
    order = _post_payment_fixture(monkeypatch, module, delivered=False)
    state = {}
    assert module._post_payment_handler("pay_1", "+919000000001", "", "", {}, "req",
                                        reference_id=REF, resume=True, state=state) is False
    assert order == ["receipt", ("vault", "order_1")]
    assert state["pending"] == ["receipt"]


# ── claim-guarded hand-offs ──────────────────────────────────────────────────────

def test_vault_settlement_is_dispatched_once_and_retried_after_a_refused_invoke(monkeypatch, webhook):
    module, _leases, _clock = webhook
    keys = Table()
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=lambda _n: keys))
    invokes = []

    class Lambda:
        fail = True

        def invoke(self, **kw):
            invokes.append(json.loads(kw["Payload"])["internalAction"])
            if Lambda.fail:
                Lambda.fail = False
                raise RuntimeError("throttled")

    monkeypatch.setattr(module, "lambda_client", Lambda())
    args = dict(invoice_id="inv-1", file_id="file-1", customer_id="c", razorpay_order_id="order_1",
                payment_id="pay_1", reference_id=REF, request_id="req")
    assert module._dispatch_vault_settlement(**args) is False      # refused: released
    assert module._dispatch_vault_settlement(**args) is True       # dispatched
    assert module._dispatch_vault_settlement(**args) is True       # already dispatched
    assert invokes == ["vaultSettleFromInvoice", "vaultSettleFromInvoice"]


def test_service_flow_dispatch_is_claim_guarded_per_invoice(monkeypatch, webhook):
    module, _leases, _clock = webhook
    keys = Table()
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=lambda _n: keys))
    invokes = []
    monkeypatch.setattr(module, "lambda_client", SimpleNamespace(invoke=lambda **kw: invokes.append(1)))
    args = dict(reference_id=REF, payment_attempt_id="pa_1", order_id="ord_1", request_id="req",
                invoice_id="inv-1")
    assert module._dispatch_post_invoice_service_flow(**args) is True
    assert module._dispatch_post_invoice_service_flow(**args) is True
    assert invokes == [1]


# ── the captured path's marker and ledger ────────────────────────────────────────

VERIFIED = {"id": "pay_1", "status": "captured", "amount": 4900, "currency": "INR",
            "order_id": "order_1", "contact": "+919000000002", "email": "payer@example.com",
            "description": "Verified", "notes": {"referenceId": REF, "wabaId": "w1"}}


def _captured_fixture(monkeypatch, module, *, post_payment):
    calls = {"ledger": [], "pending": [], "settled": [], "ctwa": []}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=lambda _n: Table()))
    monkeypatch.setattr(module, "_create_order_for_captured_payment", lambda *_a: {
        "outcome": "ORDER_ALREADY_EXISTS", "hasOrder": True, "paymentAttemptId": "pa_1",
        "orderId": "ord_1", "checkoutMode": "", "providerPaymentId": "pay_1",
        "verifiedPayment": dict(VERIFIED)})
    monkeypatch.setattr(module, "_store_payment_record",
                        lambda payment, status, _r: calls["ledger"].append((payment, status)))
    monkeypatch.setattr(module, "_mark_invoice_paid_by_reference", lambda *a: True)
    monkeypatch.setattr(module, "_materialize_paid_invoice_order", lambda *a, **k: None)
    monkeypatch.setattr(module, "_notification_recipient", lambda *_a: "+919000000001")
    monkeypatch.setattr(module, "_resolve_originating_phone", lambda *a: "")
    monkeypatch.setattr(module, "_post_payment_handler", post_payment)
    monkeypatch.setattr(module, "_dispatch_post_invoice_service_flow", lambda **kw: True)
    monkeypatch.setattr(module, "_mark_post_capture_pending",
                        lambda *a: calls["pending"].append(a))
    monkeypatch.setattr(module, "_post_capture_settled",
                        lambda *a, **k: calls["settled"].append((a, k)))
    monkeypatch.setattr(module, "_log_ctwa_purchase", lambda *a, **k: calls["ctwa"].append(a))
    return calls


def _forged_body_event():
    return {"payment": {"entity": {"id": "pay_1", "amount": 1, "contact": "+910000000000",
                                   "description": "forged", "notes": {"referenceId": REF}}}}


def test_ledger_is_built_from_the_readback_not_the_event(monkeypatch, webhook):
    module, _leases, _clock = webhook

    def post_payment(*args, state=None, **kw):
        state["invoiceId"] = "inv-1"
        return True

    calls = _captured_fixture(monkeypatch, module, post_payment=post_payment)
    module._handle_payment_captured(_forged_body_event(), "req")
    (ledgered, status), = calls["ledger"]
    assert status == "captured" and ledgered["amount"] == 4900
    assert ledgered["contact"] == "+919000000002" and ledgered["description"] == "Verified"
    assert ledgered["notes"]["referenceId"] == REF
    assert calls["pending"] == [] and len(calls["settled"]) == 1
    assert calls["ctwa"][0][1] == 4900                     # verified amount reported


def test_a_failed_step_leaves_a_marker_and_reraises(monkeypatch, webhook):
    module, _leases, _clock = webhook

    def post_payment(*args, state=None, **kw):
        state["pending"].append("receipt")
        state["step"] = "receipt"
        raise RuntimeError("Invoice receipt delivery is pending")

    calls = _captured_fixture(monkeypatch, module, post_payment=post_payment)
    with pytest.raises(RuntimeError):
        module._handle_payment_captured(_forged_body_event(), "req")
    assert calls["pending"] == [("pa_1", REF, "pay_1", "receipt", "req")]
    assert calls["settled"] == [] and calls["ctwa"] == []


def test_resume_never_sends_the_ctwa_event(monkeypatch, webhook):
    module, _leases, _clock = webhook
    seen = {}

    def post_payment(*args, state=None, resume=False, **kw):
        seen["resume"] = resume
        return True

    calls = _captured_fixture(monkeypatch, module, post_payment=post_payment)
    module._handle_payment_captured(_forged_body_event(), "req", resume=True)
    assert seen == {"resume": True} and calls["ctwa"] == []
    assert len(calls["settled"]) == 1


def test_resume_trigger_names_only_the_verified_payment(monkeypatch, webhook):
    module, _leases, _clock = webhook
    triggered = []
    monkeypatch.setattr(module, "_handle_payment_captured",
                        lambda event, _r, **kw: triggered.append((event, kw)))
    attempt = {"referenceId": REF, "verifiedProviderPaymentId": "pay_1",
               "postCapturePaymentId": "pay_1", "postCapturePending": "PENDING"}
    assert module._resume_post_capture(attempt, "req") == "resumed"
    assert triggered == [({"payment": {"entity": {"id": "pay_1", "status": "captured",
                                                  "notes": {"referenceId": REF}}}},
                          {"resume": True})]
    assert module._resume_post_capture({**attempt, "postCapturePaymentId": "pay_2"}, "req") == "skipped"


# ── sweep ────────────────────────────────────────────────────────────────────────

def test_paid_sweep_resumes_only_marked_attempts_newest_first(monkeypatch, webhook):
    module, _leases, _clock = webhook
    now = 100000
    marked = {"referenceId": REF, "paidAt": now - 3600, "postCapturePending": "PENDING",
              "paymentAttemptId": "pa_1"}
    plain = {"referenceId": "WD-PAY-ZZZZZZ99", "paidAt": now - 3600, "paymentAttemptId": "pa_2"}
    attempts = Table(key="paymentAttemptId", items=[marked, plain])
    monkeypatch.setattr(module, "_invoice_exists_for_reference", lambda _ref: True)
    resumed = []
    monkeypatch.setattr(module, "_resume_post_capture",
                        lambda attempt, _r: resumed.append(attempt["referenceId"]) or "resumed")
    monkeypatch.setattr(module, "_reconcile_in_flight_attempt",
                        lambda *a, **k: pytest.fail("an invoiced attempt must not re-run capture"))
    counts = {"scanned": 0, "errors": 0, "deferred": 0}
    module._sweep_paid_without_invoice(attempts, Table(), now, float("inf"), counts, "req")
    assert resumed == [REF] and counts["resumed"] == 1
    assert attempts.queries[0]["ScanIndexForward"] is False


def test_in_flight_sweep_reads_newest_first_across_pages(monkeypatch, webhook):
    module, _leases, _clock = webhook
    pages = [[{"referenceId": "WD-PAY-AAAAAA01"}], [{"referenceId": "WD-PAY-AAAAAA02"}]]
    attempts = Table(key="paymentAttemptId", items=[list(p) for p in pages])
    tables = {module.PAYMENT_ATTEMPTS_TABLE: attempts, module.COMMERCE_KEYS_TABLE: Table()}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=tables.__getitem__))
    seen = []
    monkeypatch.setattr(module, "_reconcile_in_flight_attempt",
                        lambda attempt, *_a, **_k: seen.append(attempt["referenceId"]) or "no_capture")
    monkeypatch.setattr(module, "_sweep_paid_without_invoice", lambda *a: None)
    monkeypatch.setattr(module, "_emit_sweep_metrics", lambda *a: None)
    counts = module._sweep_stale_attempts("req")
    assert seen == ["WD-PAY-AAAAAA01", "WD-PAY-AAAAAA02"]
    assert counts["no_capture"] == 2
    assert all(q["ScanIndexForward"] is False for q in attempts.queries)


# ── settlement clears the marker and resolves the quarantine ─────────────────────

def test_settled_capture_clears_marker_and_resolves_quarantine(monkeypatch, webhook):
    module, _leases, _clock = webhook
    keys, attempts = Table(), Table(key="paymentAttemptId")
    attempts.rows["pa_1"] = {"paymentAttemptId": "pa_1", "postCapturePending": "PENDING",
                             "postCapturePaymentId": "pay_1"}
    keys.rows["CAPTUREQUARANTINE#pay_1"] = {"orderId": "CAPTUREQUARANTINE#pay_1",
                                            "status": "UNRESOLVED",
                                            "outcome": "INVOICE_CREATE_FAILED"}
    keys.rows["CAPTUREQUARANTINE#pay_2"] = {"orderId": "CAPTUREQUARANTINE#pay_2",
                                            "status": "UNRESOLVED", "outcome": "DUPLICATE_CAPTURE"}
    tables = {module.PAYMENT_ATTEMPTS_TABLE: attempts, module.COMMERCE_KEYS_TABLE: keys}
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=tables.__getitem__))
    module._post_capture_settled("pa_1", "pay_1", "ord_1", "req")
    marker_update = attempts.updates[0]
    assert marker_update[1].startswith("REMOVE postCapturePending")
    assert marker_update[3][":pid"] == "pay_1"
    resolved = [u for u in keys.updates if u[0] == "CAPTUREQUARANTINE#pay_1"]
    assert resolved and resolved[0][3][":resolved"] == "RESOLVED"
    module._post_capture_settled("", "pay_2", "", "req")
    assert not [u for u in keys.updates if u[0] == "CAPTUREQUARANTINE#pay_2"]


def test_audit_payload_stays_parseable(webhook):
    module, _leases, _clock = webhook
    small = {"payment": {"entity": {"id": "pay_1", "notes": {"referenceId": REF}}}}
    assert json.loads(module._audit_payload(small, "payment", small["payment"]["entity"])) == small
    entity = {"id": "pay_1", "status": "captured", "notes": {"referenceId": REF},
              "acquirer_data": {"blob": "x" * (module._AUDIT_PAYLOAD_MAX_CHARS + 10)}}
    compact = json.loads(module._audit_payload({"payment": {"entity": entity}}, "payment", entity))
    assert compact == {"payment": {"entity": {"id": "pay_1", "status": "captured",
                                              "notes": {"referenceId": REF}}}}
