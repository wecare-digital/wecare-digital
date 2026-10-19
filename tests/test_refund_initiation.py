"""Refund initiation has one gated, non-retrying provider boundary."""
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


def test_refund_executor_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("REFUND_INITIATION_ENABLED", raising=False)
    monkeypatch.setattr(
        rr,
        "_credentials",
        lambda: (_ for _ in ()).throw(AssertionError("credentials must not be read")),
    )
    with pytest.raises(rr.RefundDisabled):
        rr.create_full_refund(
            payment_id="pay_ABC123",
            amount_paise=12345,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )


def test_full_refund_posts_derived_integer_amount_once(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        return _Response(
            {
                "id": "rfnd_ABC123",
                "payment_id": "pay_ABC123",
                "amount": 12345,
                "status": "processed",
            }
        )

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    result = rr.create_full_refund(
        payment_id="pay_ABC123",
        amount_paise=12345,
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
    assert body["amount"] == 12345
    assert body["notes"]["wecare_return"] == "WD-SR-1"
    assert body["notes"]["wecare_order"] == "WD-ORD-1"
    assert result.refund_id == "rfnd_ABC123"
    assert result.payment_id == "pay_ABC123"
    assert result.amount_paise == 12345


def test_provider_5xx_is_ambiguous_and_never_retried(monkeypatch):
    _enabled(monkeypatch)
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        raise urllib.error.HTTPError(
            request.full_url, 503, "provider unavailable", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    with pytest.raises(rr.RefundAmbiguous):
        rr.create_full_refund(
            payment_id="pay_ABC123",
            amount_paise=12345,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )
    assert len(calls) == 1


def test_provider_4xx_is_terminal_rejection(monkeypatch):
    _enabled(monkeypatch)

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 400, "bad request", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(rr.urllib.request, "urlopen", urlopen)
    with pytest.raises(rr.RefundRejected) as exc:
        rr.create_full_refund(
            payment_id="pay_ABC123",
            amount_paise=12345,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )
    assert exc.value.status == 400


def test_unusable_provider_success_is_ambiguous(monkeypatch):
    _enabled(monkeypatch)
    monkeypatch.setattr(
        rr.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(
            {
                "id": "rfnd_ABC123",
                "payment_id": "pay_OTHER",
                "amount": 12345,
                "status": "processed",
            }
        ),
    )
    with pytest.raises(rr.RefundAmbiguous):
        rr.create_full_refund(
            payment_id="pay_ABC123",
            amount_paise=12345,
            return_submission_id="WD-SR-1",
            order_id="WD-ORD-1",
            request_id="req-1",
        )


def test_invoice_engine_refund_command_derives_money_and_payment_server_side():
    source = (
        ROOT / "amplify/functions/payments/invoice-engine/handler.py"
    ).read_text(encoding="utf-8")

    route = source[source.index("body.get('_action') == 'initiate-refund'"):source.index(
        "body.get('_action') == 'clear-all'"
    )]
    assert "event.get('_auth')" in route

    block = source[source.index("def initiate_full_refund"):source.index(
        "# ─── Add Remark / Refund / Credit Note"
    )]
    assert "razorpay_refund.enabled()" in block
    assert "body.get('returnSubmissionId')" in block
    assert "body.get('paymentId')" not in block
    assert "body.get('amount')" not in block
    assert "invoice.get('paymentId')" in block
    assert "invoice.get('internalOrderId')" in block
    assert "returnStage" in block and "refund_eligible" in block
    assert "return_case.get('orderId')" in block
    assert "pay_status.CAPTURED" in block
    assert "attribute_not_exists(refundInitiationState)" in block
    assert "provider_outcome_unknown" in block
    assert "'retryable': False" in block
    assert "payment_table.update_item" not in block, (
        "refund initiation must not mark the payment refunded; webhook evidence owns that"
    )


def test_refund_feature_flag_is_pinned_off_in_deployment_manifest():
    manifest = json.loads(
        (ROOT / "config/lambda-env-manifest.json").read_text(encoding="utf-8")
    )
    env = manifest["functions"]["wecare-invoice-engine"]
    assert env["REFUND_INITIATION_ENABLED"] == "false"
    assert env["RAZORPAY_API_SECRET_ID"] == "wecare/razorpay/api"
