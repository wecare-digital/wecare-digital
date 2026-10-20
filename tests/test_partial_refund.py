"""Partial refunds share the full-refund boundary: one gated, non-retrying provider POST.

create_partial_refund is a thin, explicit sibling of create_full_refund. These tests prove it
keeps every money invariant: the flag gate, exactly one non-retried POST, the payment-id and
exact-amount echo check, and ambiguous-on-5xx/timeout. The server-side cap derivation lives in
invoice-engine (asserted structurally below), not in this provider boundary.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.integrations import razorpay_refund as rr  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _enabled(monkeypatch):
    monkeypatch.setenv("REFUND_INITIATION_ENABLED", "true")
    monkeypatch.setattr(
        rr,
        "_credentials",
        lambda: {"key_id": "fixture-id", "key_secret": "fixture-secret"},
    )


def test_partial_refund_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("REFUND_INITIATION_ENABLED", raising=False)
    monkeypatch.setattr(
        rr,
        "_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("credentials must not be read")),
    )
    with pytest.raises(rr.RefundDisabled):
        rr.create_partial_refund(
            payment_id="pay_ABC123",
            amount_paise=5000,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )


def test_partial_refund_posts_requested_amount_once(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        return _Response(
            {
                "id": "rfnd_PART1",
                "payment_id": "pay_ABC123",
                "amount": 5000,
                "status": "processed",
            }
        )

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    result = rr.create_partial_refund(
        payment_id="pay_ABC123",
        amount_paise=5000,
        return_submission_id="WD-SR-1",
        order_id="WD-ORD-1",
        request_id="req-1",
    )

    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://api.razorpay.com/v1/payments/pay_ABC123/refund"
    assert request.method == "POST"
    assert timeout == 15
    body = json.loads(request.data)
    assert body["amount"] == 5000
    assert result.refund_id == "rfnd_PART1"
    assert result.amount_paise == 5000


def test_partial_refund_rejects_non_positive_amount(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(
        rr.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            AssertionError("no POST may happen for an invalid amount")
        ),
    )
    for bad in (0, -1):
        with pytest.raises(ValueError):
            rr.create_partial_refund(
                payment_id="pay_ABC123",
                amount_paise=bad,
                return_submission_id="WD-SR-1",
                order_id="WD-ORD-1",
                request_id="req-1",
            )


def test_partial_refund_5xx_is_ambiguous_and_never_retried(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        raise urllib.error.HTTPError(
            request.full_url, 503, "provider unavailable", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    with pytest.raises(rr.RefundAmbiguous):
        rr.create_partial_refund(
            payment_id="pay_ABC123",
            amount_paise=5000,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )
    assert len(calls) == 1


def test_partial_refund_timeout_is_ambiguous_and_never_retried(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        raise TimeoutError("read timed out")

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    with pytest.raises(rr.RefundAmbiguous):
        rr.create_partial_refund(
            payment_id="pay_ABC123",
            amount_paise=5000,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )
    assert len(calls) == 1


def test_partial_refund_amount_mismatch_is_ambiguous(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(
        rr.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(
            {
                "id": "rfnd_PART1",
                "payment_id": "pay_ABC123",
                "amount": 4999,  # provider echoed a different amount than requested
                "status": "processed",
            }
        ),
    )
    with pytest.raises(rr.RefundAmbiguous):
        rr.create_partial_refund(
            payment_id="pay_ABC123",
            amount_paise=5000,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )


def test_invoice_engine_partial_refund_caps_amount_server_side():
    """The partial entry point derives the cap server-side and never trusts a browser amount."""
    source = (
        ROOT / "amplify/functions/payments/invoice-engine/handler.py"
    ).read_text(encoding="utf-8")

    # The POST route for a partial refund exists alongside the full one and carries the actor.
    route = source[source.index("body.get('_action') == 'initiate-partial-refund'"):source.index(
        "body.get('_action') == 'clear-all'"
    )]
    assert "event.get('_auth')" in route
    assert "initiate_partial_refund" in route

    block = source[source.index("def initiate_partial_refund"):source.index(
        "def _execute_refund"
    )]
    # Server authority: eligibility is resolved by the shared resolver, the browser amount is
    # validated against the server cap, and over-cap / non-positive amounts are rejected.
    assert "_resolve_refund_context" in block
    assert "max_refundable_paise" in block
    assert "REFUND_AMOUNT_OVER_CAP" in block
    assert "REFUND_AMOUNT_INVALID" in block
    assert "partial=True" in block

    # The cap is captured total minus what the webhook already recorded refunded — not a body value.
    resolver = source[source.index("def _resolve_refund_context"):source.index(
        "def initiate_partial_refund"
    )]
    assert "already_refunded_paise" in resolver
    assert "refundAmountPaise" in resolver
    assert "captured_paise - self.already_refunded_paise" in source


def test_execute_refund_never_marks_payment_refunded():
    """Refund execution writes case state only; the webhook stays the sole refunded-state setter."""
    source = (
        ROOT / "amplify/functions/payments/invoice-engine/handler.py"
    ).read_text(encoding="utf-8")
    block = source[source.index("def _execute_refund"):source.index(
        "# ─── Add Remark / Refund / Credit Note"
    )]
    assert "payment_table.update_item" not in block
    assert "create_partial_refund" in block
    assert "create_full_refund" in block
    assert "provider_outcome_unknown" in block
    assert "'retryable': False" in block


def test_resolver_documents_single_refund_per_payment():
    """The single-refund-per-payment reality is documented where the REFUNDED branch resolves.

    The webhook is the sole setter of refunded state and overwrites (not sums) refundAmountPaise,
    so the behaviour must be stated honestly rather than worked around by widening the money core.
    """
    source = (
        ROOT / "amplify/functions/payments/invoice-engine/handler.py"
    ).read_text(encoding="utf-8")
    resolver = source[source.index("def _resolve_refund_context"):source.index(
        "def initiate_partial_refund"
    )]
    assert "SINGLE REFUND PER PAYMENT" in resolver
    assert "sole authoritative setter" in resolver


# ───────────────────────────────────────────────────────────────────────────
# Runtime: the operator refund REASON is validated and persisted on the audit record.
# The reason is operator metadata, never a money input — the server stays authoritative on the
# cap and eligibility — but the UI promises it is the audit record, so it must actually be stored.
# ───────────────────────────────────────────────────────────────────────────

import importlib  # noqa: E402

sys.path.insert(0, str(ROOT / "amplify/functions/payments/invoice-engine"))
engine = importlib.import_module("handler")  # type: ignore[assignment]


class _FakeCaseTable:
    """Captures the durable return-case claim write so the reason can be asserted."""

    def __init__(self):
        self.updates = []

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def get_item(self, **_kwargs):  # pragma: no cover - not exercised on the happy path
        return {"Item": {}}


def _context(monkeypatch):
    return engine._RefundContext(
        actor="admin@example.test",
        invoice_id="INV-1",
        submission_id="WD-SR-1",
        payment_id="pay_ABC123",
        internal_order_id="WD-ORD-1",
        captured_paise=10000,
        already_refunded_paise=0,
    )


def _wire_execute(monkeypatch):
    """Point _execute_refund at a fake case table, a successful provider call and a capturing audit."""
    fake = _FakeCaseTable()
    monkeypatch.setattr(engine.dynamodb, "Table", lambda _name: fake)
    monkeypatch.setattr(
        engine.razorpay_refund,
        "create_partial_refund",
        lambda **_kw: engine.razorpay_refund.RefundResult(
            refund_id="rfnd_X", payment_id="pay_ABC123",
            amount_paise=_kw["amount_paise"], status="processed"),
    )
    monkeypatch.setattr(
        engine.razorpay_refund,
        "create_full_refund",
        lambda **_kw: engine.razorpay_refund.RefundResult(
            refund_id="rfnd_X", payment_id="pay_ABC123",
            amount_paise=_kw["amount_paise"], status="processed"),
    )
    audits = []
    monkeypatch.setattr(engine, "record_audit", lambda **kw: audits.append(kw))
    return fake, audits


def test_execute_refund_persists_reason_on_case_and_audit(monkeypatch):
    fake, audits = _wire_execute(monkeypatch)
    resp = engine._execute_refund(
        context=_context(monkeypatch), amount_paise=5000, partial=True,
        request_id="req-1", reason="Damaged on arrival",
    )
    assert resp["statusCode"] == 202
    # The durable case claim (the first update) carries the reason.
    claim = next(u for u in fake.updates
                 if "refundInitiationReason = :reason" in u["UpdateExpression"])
    assert claim["ExpressionAttributeValues"][":reason"] == "Damaged on arrival"
    # The audit record carries the operator justification the UI promised.
    submitted = [a for a in audits if a["details"].get("outcome") == "provider_submitted"]
    assert submitted and submitted[0]["details"]["reason"] == "Damaged on arrival"


def test_initiate_refund_rejects_missing_or_bad_reason(monkeypatch):
    # The provider must never be reached when the reason is missing or malformed.
    monkeypatch.setattr(
        engine, "_resolve_refund_context",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("eligibility must not be resolved before the reason is validated")),
    )
    for bad in ("", "   ", "ok\x00bad", "x" * 501):
        full = engine.initiate_full_refund("INV-1", {"returnSubmissionId": "WD-SR-1", "reason": bad},
                                           "req-1", auth={"username": "admin"})
        assert full["statusCode"] == 400
        body = json.loads(full["body"])
        assert body["errorCode"] in ("REFUND_REASON_REQUIRED", "REFUND_REASON_INVALID")
