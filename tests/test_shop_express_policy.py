"""Regression contract for the shop's fixed Express amounts (no network, no charges).

Run: PYTHONPATH=amplify/functions/shared python3 -m unittest
     discover -s tests -p 'test_shop_express_policy.py' -v
"""
from __future__ import annotations

import unittest

from lambda_utils.ecommerce import (
    checkout_pricing,
    contribute_taxable,
    express_policy,
    request_service_contracts,
    service_pricing_native,
    service_requests,
)


class ShopExpressPolicyTests(unittest.TestCase):
    def sample_snapshot(self, collection_paise=9_851, delivery_paise=0):
        quote = checkout_pricing.compute_quote(collection_paise, currency="INR")
        return checkout_pricing.build_snapshot(
            customer_id="QA-SNAPSHOT",
            cart_id="native:sample",
            cart_revision=0,
            quote=quote,
            created_at=1_800_000_000,
            ttl_seconds=900,
            site="aws-native",
            items=[{
                "lineItemId": "sku-one",
                "productId": "example-product",
                "variantId": "sku-one",
                "quantity": 1,
                "unitPricePaise": 9_900,
            }],
            address=None,
            delivery={"paise": delivery_paise, "optionId": "resolved"},
        )

    def test_standard_is_one_45_rupee_fee_before_convenience_and_fee_gst(self):
        original = self.sample_snapshot()
        priced = express_policy.with_standard_express(original)
        self.assertEqual(priced.quote.collection_before_convenience_paise, 14_351)
        self.assertEqual(priced.quote.convenience_fee_paise, 359)
        self.assertEqual(priced.quote.convenience_gst_paise, 65)
        self.assertEqual(priced.quote.total_payable_paise, 14_775)
        self.assertEqual(priced.frozen_data["delivery"], {
            "paise": 4_500, "optionId": "express",
        })
        self.assertEqual(priced.frozen_data["pricingMetadata"]["expressPaise"], 4_500)
        self.assertNotEqual(priced.snapshot_hash, original.snapshot_hash)
        # A quote is immutable; an Express recomputation must never mutate the
        # original native cart or change its stored/previously reviewed amount.
        self.assertEqual(original.frozen_data["delivery"]["paise"], 0)

    def test_nonzero_existing_delivery_refuses_instead_of_double_charging(self):
        with self.assertRaises(checkout_pricing.PricingError):
            express_policy.with_standard_express(
                self.sample_snapshot(delivery_paise=1_000))
        with self.assertRaises(checkout_pricing.PricingError):
            express_policy.with_standard_express(
                express_policy.with_standard_express(self.sample_snapshot()))

    def test_contribute_keeps_15_rupees_and_exact_300_total(self):
        terms = contribute_taxable.breakdown(30_000)
        self.assertEqual(express_policy.CONTRIBUTE_EXPRESS_PAISE, 1_500)
        self.assertEqual(contribute_taxable.EXPRESS_PAISE, 1_500)
        self.assertEqual(terms["expressPaise"], 1_500)
        self.assertEqual(terms["totalPayablePaise"], 30_000)

    def test_vault_49_becomes_105_56(self):
        terms = service_pricing_native._collect_breakdown(service_requests.VAULT, 4_900)
        self.assertIsNotNone(terms)
        self.assertEqual(terms["supplyGstPaise"], 882)
        self.assertEqual(terms["delightPaise"], 28)
        self.assertEqual(terms["expressPaise"], 4_500)
        self.assertEqual(terms["convenienceFeePaise"], 256)
        self.assertEqual(terms["convenienceGstPaise"], 46)
        self.assertEqual(terms["totalPayablePaise"], 10_556)

    def test_drop_docs_and_all_other_request_services_have_45_express(self):
        drop_docs = service_pricing_native._collect_breakdown(service_requests.DROP_DOCS, 19_900)
        self.assertIsNotNone(drop_docs)
        self.assertEqual(drop_docs["expressPaise"], 4_500)
        for name, contract in request_service_contracts.REQUEST_SERVICE_CONTRACTS.items():
            with self.subTest(service=name):
                self.assertEqual(contract.express_paise, 4_500)

    def test_internal_qa_item_is_not_a_customer_express_purchase(self):
        product_id = express_policy.INTERNAL_QA_PRODUCT_ID
        variant_id = express_policy.INTERNAL_QA_VARIANT_ID
        self.assertTrue(express_policy.is_internal_qa_cart([
            (product_id, variant_id, 1),
        ]))
        self.assertFalse(express_policy.is_internal_qa_cart([
            ("another-product", "any-variant", 1),
        ]))
        self.assertFalse(express_policy.is_internal_qa_cart([
            (product_id, variant_id, 1),
            ("another-product", "any-variant", 1),
        ]))


if __name__ == "__main__":
    unittest.main()
