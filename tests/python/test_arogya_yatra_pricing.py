"""Arogya Yatra uses the shared checkout policy, not a page-specific calculator."""
from lambda_utils.ecommerce import express_policy, unified_pricing


def test_arogya_550_base_reconciles_with_the_existing_invoice_rules():
    express = express_policy.expected_express_paise(
        "032039ce-c4ec-5d44-8fdb-d4d9ffb91f02", "BRX5N8Q3")
    result = unified_pricing.price_components(55000, express_paise=express)
    assert result == {
        "itemSubtotalPaise": 55000,
        "supplyGstPaise": 9900,
        "supplyGstBps": 1800,
        "delightPaise": 324,
        "expressPaise": 4500,
        "collectionBeforeConveniencePaise": 69076,
        "convenienceFeePaise": 1727,
        "convenienceGstPaise": 311,
        "convenienceGstBps": 1800,
        "totalPayablePaise": 71114,
    }


def test_two_arogya_units_pay_express_once_per_basket():
    result = unified_pricing.price_components(2 * 55000)
    assert result["expressPaise"] == 4500
    assert result["itemSubtotalPaise"] == 110000
    assert result["collectionBeforeConveniencePaise"] == (
        result["itemSubtotalPaise"] + result["supplyGstPaise"]
        - result["delightPaise"] + result["expressPaise"])
