"""Generic staff OrderTable PATCH must never become a money-state backdoor."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import order_patch  # noqa: E402


def _validate(current=None, body=None):
    return order_patch.validate_order_patch(current or {}, body or {})


def test_payment_status_is_provider_controlled():
    updates, error = _validate(
        {"paymentStatus": "pending", "orderStatus": "pending"},
        {"paymentStatus": "captured"},
    )
    assert updates is None
    assert error["errorCode"] == "PAYMENT_STATUS_READ_ONLY"


def test_paid_legacy_active_order_can_move_to_a_legal_fulfilment_state():
    updates, error = _validate(
        {"paymentStatus": "PAYMENT_PAID", "orderStatus": "active"},
        {"status": "shipped"},
    )
    assert error is None
    assert updates["orderStatus"] == updates["status"] == "shipped"


def test_unpaid_order_cannot_enter_fulfilment():
    updates, error = _validate(
        {"paymentStatus": "pending", "orderStatus": "pending"},
        {"status": "processing"},
    )
    assert updates is None
    assert error["errorCode"] == "ORDER_PAYMENT_NOT_CAPTURED"


def test_paid_order_cannot_be_cancelled_through_generic_patch():
    updates, error = _validate(
        {"paymentStatus": "captured", "orderStatus": "processing"},
        {"status": "canceled"},
    )
    assert updates is None
    assert error["errorCode"] == "PAID_ORDER_CANCEL_REQUIRES_WORKFLOW"


def test_unknown_existing_status_fails_closed_even_when_paid():
    updates, error = _validate(
        {"paymentStatus": "captured", "orderStatus": "provider-mystery"},
        {"status": "shipped"},
    )
    assert updates is None
    assert error["errorCode"] == "ORDER_STATUS_REVIEW_REQUIRED"


def test_conflicting_status_aliases_are_refused():
    updates, error = _validate(
        {"paymentStatus": "captured", "orderStatus": "processing"},
        {"status": "shipped", "fulfillmentStatus": "completed"},
    )
    assert updates is None
    assert error["errorCode"] == "ORDER_STATUS_CONFLICT"


def test_notes_remain_editable_without_touching_money_or_fulfilment():
    updates, error = _validate(
        {"paymentStatus": "refunded", "orderStatus": "completed"},
        {"notes": "Customer collected parcel."},
    )
    assert error is None
    assert updates == {"adminNotes": "Customer collected parcel."}


def test_same_canonical_status_is_an_idempotent_retry():
    updates, error = _validate(
        {"paymentStatus": "captured", "orderStatus": "shipped"},
        {"status": "shipped"},
    )
    assert error is None
    assert updates["orderStatus"] == updates["status"] == "shipped"


def test_both_service_handlers_use_the_shared_patch_guard_and_stale_write_condition():
    paths = [
        ROOT / "amplify/functions/core/service-api/handler.py",
        ROOT / "amplify/functions/messaging/whatsapp-business-api/service_api.py",
    ]
    for path in paths:
        source = path.read_text()
        block = source[source.index("def _update_order"):source.index("def _get_order_submissions")]
        assert "order_patch.validate_order_patch(current, body)" in block
        assert "ConsistentRead=True" in block
        assert "ORDER_PATCH_STALE" in block
        # paymentStatus is legitimately referenced by the optimistic stale-write guard.
        # What must never return is a handler-side write that bypasses the shared validator.
        assert "updates['paymentStatus']" not in block
        assert 'updates["paymentStatus"]' not in block
