"""Audited order cancellation is a separate, fail-closed workflow."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import order_patch  # noqa: E402


def test_pending_unpaid_order_can_enter_explicit_cancellation_workflow():
    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "pending", "orderStatus": "pending"},
        "Customer asked to cancel before fulfilment.",
    )
    assert error is None
    assert decision == {
        "reason": "Customer asked to cancel before fulfilment.",
        "currentStatus": "pending",
        "idempotent": False,
    }


def test_legacy_unpaid_active_is_treated_as_pending():
    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "pending", "status": "active"},
        "Duplicate manual order",
    )
    assert error is None
    assert decision["currentStatus"] == "pending"


def test_any_money_at_or_beyond_capture_blocks_order_cancellation():
    for payment in ("captured", "paid", "PAYMENT_PAID", "refunded", "disputed"):
        decision, error = order_patch.validate_order_cancellation(
            {"paymentStatus": payment, "orderStatus": "processing"},
            "Customer requested cancellation",
        )
        assert decision is None
        assert error["errorCode"] == "ORDER_CANCEL_MONEY_MOVED"


def test_unknown_payment_or_fulfilment_state_fails_closed():
    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "provider-mystery", "orderStatus": "pending"},
        "Review required",
    )
    assert decision is None
    assert error["errorCode"] == "ORDER_CANCEL_PAYMENT_REVIEW_REQUIRED"

    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "pending", "orderStatus": "provider-mystery"},
        "Review required",
    )
    assert decision is None
    assert error["errorCode"] == "ORDER_STATUS_REVIEW_REQUIRED"


def test_fulfilment_started_cannot_be_cancelled_even_if_payment_word_is_unpaid():
    for status in ("processing", "partially-shipped", "shipped", "completed"):
        decision, error = order_patch.validate_order_cancellation(
            {"paymentStatus": "pending", "orderStatus": status},
            "Too late",
        )
        assert decision is None
        assert error["errorCode"] == "ORDER_CANCEL_STATE_INVALID"


def test_already_cancelled_is_an_idempotent_retry():
    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "pending", "orderStatus": "canceled"},
        "Duplicate order",
    )
    assert error is None
    assert decision["idempotent"] is True


def test_cancellation_reason_is_required_bounded_and_multiline_safe():
    for reason in (None, "", "   "):
        decision, error = order_patch.validate_order_cancellation(
            {"paymentStatus": "pending", "orderStatus": "pending"}, reason
        )
        assert decision is None
        assert error["errorCode"] == "ORDER_CANCEL_REASON_REQUIRED"

    for reason in ("x" * 501, "bad\x0bcontrol"):
        decision, error = order_patch.validate_order_cancellation(
            {"paymentStatus": "pending", "orderStatus": "pending"}, reason
        )
        assert decision is None
        assert error["errorCode"] == "ORDER_CANCEL_REASON_INVALID"

    decision, error = order_patch.validate_order_cancellation(
        {"paymentStatus": "pending", "orderStatus": "pending"},
        "Customer requested cancellation.\nConfirmed before fulfilment.",
    )
    assert error is None
    assert decision["reason"].startswith("Customer requested")


def test_service_api_wires_cancellation_as_admin_command_not_generic_status_patch():
    source = (ROOT / "amplify/functions/core/service-api/handler.py").read_text()

    assert "body.get('action')" in source
    assert "required_role='Admin' if is_cancel_command else None" in source
    assert "return _cancel_order(order_id, body, auth, request_id)" in source

    cancel = source[source.index("def _cancel_order"):source.index("def _update_order")]
    assert "validate_order_cancellation(current, body.get('reason'))" in cancel
    assert "current.get('invoiceId')" in cancel
    assert "_cancel_linked_invoice" in cancel
    assert "ORDER_CANCEL_STALE" in cancel
    assert "ORDER_CANCEL_AUDIT_RETRY" in cancel
    assert "ORDER_CANCEL#" in cancel
    assert "actor_info.get('username')" in cancel
    assert "body.get('actor')" not in cancel

    patch = source[source.index("def _update_order"):source.index("def _get_order_submissions")]
    assert "ORDER_CANCEL_REQUIRES_WORKFLOW" in patch


def test_cancellation_write_guards_status_aliases_and_payment():
    source = (ROOT / "amplify/functions/core/service-api/handler.py").read_text()
    cancel = source[source.index("def _cancel_order"):source.index("def _update_order")]
    assert "('order_status', 'orderStatus')" in cancel
    assert "('status_alias', 'status')" in cancel
    assert "('fulfillment_status', 'fulfillmentStatus')" in cancel
    assert "('payment', 'paymentStatus')" in cancel
    assert "ConditionExpression=' AND '.join(conditions)" in cancel
