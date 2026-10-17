"""Delight default coupon policy.

The customer-facing surface may show only the coupon name and rupee saving. The rate is stored
server-side as integer basis points so no browser arithmetic can change the payable amount.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402


def _delight():
    return cs.validate_definition({
        "code": "Delight",
        "name": "Delight",
        "discountKind": cs.PERCENT_OFF,
        "percentOffBps": 5,          # 0.05%, represented exactly as basis points
        "maximumDiscountPaise": 10000,
        "scopeNamespace": "stores",  # Rs 100
        "currency": "INR",
    }, created_by="system", clock=lambda: 1792230000)


def test_delight_accepts_sub_percent_basis_points_and_caps_at_100_rupees():
    d = _delight()
    assert d["percentOffBps"] == 5
    assert d["maximumDiscountPaise"] == 10000
    assert cs.discount_paise(d, collection_paise=100000) == 50
    assert cs.discount_paise(d, collection_paise=50000000) == 10000


def test_delight_never_discounts_more_than_collection():
    d = _delight()
    assert cs.discount_paise(d, collection_paise=1) <= 1
