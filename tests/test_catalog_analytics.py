import sys
from pathlib import Path
from decimal import Decimal

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync  # noqa: E402
from lambda_utils.ecommerce import catalog_analytics as analytics  # noqa: E402

PRODUCT_ID = "11111111-1111-4111-8111-111111111111"
VARIANT = "22222222-2222-4222-8222-222222222222"
OTHER_PRODUCT = "99999999-9999-4999-8999-999999999999"

analytics.PRODUCT_ID = PRODUCT_ID
analytics.VARIANTS = frozenset({VARIANT})


def paid():
    return {
        "status": "PAYMENT_PAID",
        "orderNumber": "WD-ORD-QATEST01",
        "amountPaise": Decimal(5300),
        "currency": "INR",
        "catalogContents": [{
            "productId": PRODUCT_ID,
            "variantId": VARIANT,
            "quantity": Decimal(1),
        }],
    }


def test_paid_facts_use_frozen_variant_and_captured_total_without_customer_data():
    row = paid()
    row.update(customerPhone="+919999999999", customerId="private-customer")
    facts = analytics.purchase_facts(row)
    content_id = meta_catalog_sync.retailer_id(PRODUCT_ID, VARIANT)
    assert facts == {
        "contents": [{"id": content_id, "quantity": 1}],
        "amountPaise": 5300,
        "currency": "INR",
    }


@pytest.mark.parametrize("status", [
    "PAYMENT_PENDING", "PAYMENT_FAILED", "CREATED", "PAYMENT_EXPIRED",
])
def test_not_paid_cannot_be_a_purchase(status):
    row = paid()
    row["status"] = status
    assert analytics.purchase_facts(row) is None


def test_no_catalog_contents_is_omitted_rather_than_guessed():
    row = paid()
    del row["catalogContents"]
    assert analytics.purchase_facts(row) is None


@pytest.mark.parametrize("field,value", [
    ("orderNumber", ""),
    ("amountPaise", True),
    ("amountPaise", Decimal("1.1")),
    ("amountPaise", Decimal("NaN")),
    ("currency", "USD"),
])
def test_incomplete_or_invalid_paid_evidence_is_omitted(field, value):
    row = paid()
    row[field] = value
    assert analytics.purchase_facts(row) is None


@pytest.mark.parametrize("line", [
    {"productId": OTHER_PRODUCT, "variantId": VARIANT, "quantity": 1},
    {"productId": PRODUCT_ID, "variantId": "unknown-variant", "quantity": 1},
    {"productId": PRODUCT_ID, "variantId": VARIANT, "quantity": 0},
    "malformed",
])
def test_unknown_references_do_not_emit_or_break_status(line):
    row = paid()
    row["catalogContents"] = [line]
    assert analytics.purchase_facts(row) is None


def test_mixed_basket_does_not_attribute_all_payment_to_one_service():
    row = paid()
    row["catalogContents"].append({"productId": OTHER_PRODUCT, "quantity": 1})
    assert analytics.purchase_facts(row) is None
