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


def test_order_cancellation_requires_audited_workflow_regardless_of_payment_state():
    for current in (
        {"paymentStatus": "captured", "orderStatus": "processing"},
        {"paymentStatus": "pending", "orderStatus": "pending"},
    ):
        updates, error = _validate(current, {"status": "canceled"})
        assert updates is None
        assert error["errorCode"] == "ORDER_CANCEL_REQUIRES_WORKFLOW"


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


def test_service_api_uses_the_shared_patch_guard_and_stale_write_condition():
    path = ROOT / "amplify/functions/core/service-api/handler.py"
    source = path.read_text()
    block = source[source.index("def _update_order"):source.index("def _get_order_submissions")]
    assert "order_patch.validate_order_patch(current, body)" in block
    assert "ConsistentRead=True" in block
    assert "ORDER_PATCH_STALE" in block
    assert "('order_status', 'orderStatus')" in block
    assert "('fulfilment_status', 'fulfillmentStatus')" in block
    assert "('status_alias', 'status')" in block
    assert "('payment', 'paymentStatus')" in block
    assert "updates['paymentStatus']" not in block
    assert 'updates["paymentStatus"]' not in block



def test_manual_tracking_metadata_is_trimmed_and_marked_manual():
    updates, error = _validate(
        {"paymentStatus": "captured", "orderStatus": "processing"},
        {
            "carrierName": "  Blue Dart  ",
            "trackingNumber": "  AWB-123  ",
            "trackingUrl": "  https://example.com/track/AWB-123  ",
        },
    )
    assert error is None
    assert updates == {
        "carrierName": "Blue Dart",
        "trackingNumber": "AWB-123",
        "trackingUrl": "https://example.com/track/AWB-123",
        "trackingSource": "manual",
    }


def test_tracking_url_must_be_safe_https_and_never_raise_on_malformed_input():
    for value in (
        "http://example.com/track/123",
        "https://user:secret@example.com/track/123",
        "https://exa mple.com/track/123",
        r"https://example.com\@evil.example/track/123",
        "https://[broken",
        "https://example.com:notaport/track/123",
    ):
        updates, error = _validate(
            {"paymentStatus": "captured", "orderStatus": "processing"},
            {"trackingUrl": value},
        )
        assert updates is None
        assert error["errorCode"] == "ORDER_TRACKING_URL_INVALID"


def test_tracking_provenance_and_timestamp_are_server_owned():
    for field, value in (("trackingSource", "provider"), ("trackingUpdatedAt", 123)):
        updates, error = _validate(
            {"paymentStatus": "captured", "orderStatus": "processing"},
            {field: value},
        )
        assert updates is None
        assert error["errorCode"] == "ORDER_TRACKING_SYSTEM_FIELD_READ_ONLY"


def test_tracking_text_is_bounded_and_control_character_free():
    for body in (
        {"carrierName": "x" * 121},
        {"trackingNumber": "abc\n123"},
        {"trackingUrl": "https://example.com/" + "x" * 2040},
    ):
        updates, error = _validate(
            {"paymentStatus": "captured", "orderStatus": "processing"},
            body,
        )
        assert updates is None
        assert error["errorCode"] in {"ORDER_TRACKING_INVALID", "ORDER_TRACKING_URL_INVALID"}


def test_service_api_stamps_and_guards_manual_tracking_writes():
    path = ROOT / "amplify/functions/core/service-api/handler.py"
    source = path.read_text()
    block = source[source.index("def _update_order"):source.index("def _get_order_submissions")]
    assert "tracking_mutation = 'trackingSource' in updates" in block
    assert "updates['trackingUpdatedAt'] = now" in block
    assert "('carrier_name', 'carrierName')" in block
    assert "('tracking_number', 'trackingNumber')" in block
    assert "('tracking_url', 'trackingUrl')" in block
    assert "('tracking_source', 'trackingSource')" in block
    assert "('tracking_updated_at', 'trackingUpdatedAt')" in block
