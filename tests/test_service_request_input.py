"""Service requests are order-linked cases, never money-state operations."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import service_request_input  # noqa: E402


def test_return_request_is_cleaned_as_a_non_financial_case():
    cleaned, error = service_request_input.validate({
        "orderId": "  WD-ORD-ABC123  ",
        "requestType": "Return / Refund",
        "subject": "  Return unopened item  ",
        "description": "  Customer requested a return after delivery.  ",
    })
    assert error is None
    assert cleaned == {
        "orderId": "WD-ORD-ABC123",
        "requestType": "Return / Refund",
        "subject": "Return unopened item",
        "description": "Customer requested a return after delivery.",
    }


def test_service_request_rejects_browser_money_and_refund_fields():
    for field, value in (
        ("paymentRequired", True),
        ("paymentStatus", "refunded"),
        ("paymentAmount", 100),
        ("paymentRefId", "pay_123"),
        ("refundId", "rfnd_123"),
        ("refundAmount", 1),
        ("refundAmountPaise", 100),
    ):
        cleaned, error = service_request_input.validate({
            "orderId": "WD-ORD-ABC123",
            "requestType": "Return / Refund",
            "subject": "Return",
            "description": "Please review this return.",
            field: value,
        })
        assert cleaned is None
        assert error["errorCode"] == "SERVICE_REQUEST_FINANCIAL_FIELDS_READ_ONLY"


def test_service_request_type_and_text_are_bounded():
    cleaned, error = service_request_input.validate({
        "orderId": "WD-ORD-ABC123",
        "requestType": "Make money disappear",
        "subject": "Return",
        "description": "Please review this return.",
    })
    assert cleaned is None
    assert error["errorCode"] == "SERVICE_REQUEST_TYPE_INVALID"

    for field, value in (
        ("subject", "x" * 201),
        ("description", "bad\x0bcontrol"),
        ("orderId", ""),
    ):
        body = {
            "orderId": "WD-ORD-ABC123",
            "requestType": "Return / Refund",
            "subject": "Return",
            "description": "Please review this return.",
        }
        body[field] = value
        cleaned, error = service_request_input.validate(body)
        assert cleaned is None
        assert error["errorCode"] == "SERVICE_REQUEST_INPUT_INVALID"



def test_service_request_description_can_be_multiline():
    cleaned, error = service_request_input.validate({
        "orderId": "WD-ORD-ABC123",
        "requestType": "Damaged / Defective",
        "subject": "Damage details",
        "description": "Outer box crushed.\nItem has a visible dent.\tPhoto attached.",
    })
    assert error is None
    assert "\n" in cleaned["description"]

def test_service_api_verifies_real_order_and_forces_non_financial_case():
    path = ROOT / "amplify/functions/core/service-api/handler.py"
    source = path.read_text()
    block = source[source.index("def _submit_request"):source.index("def _amend_request")]
    assert "service_request_input.validate(body)" in block
    assert "ConsistentRead=True" in block
    assert "SERVICE_ORDER_LOOKUP_FAILED" in block
    assert "SERVICE_ORDER_NOT_FOUND" in block
    assert "'paymentRequired': False" in block
    assert "no refund or cancellation initiated" in block
    assert "body.get('paymentRequired'" not in block
