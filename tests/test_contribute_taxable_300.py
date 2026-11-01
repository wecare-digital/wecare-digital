"""Read-only executable contract for the proposed taxable INR 300 Contribute quote.

No network, payment attempts, customer data, gateway calls or AWS mutations.
These tests verify code arithmetic; they do not approve tax classification.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import contribute_taxable  # noqa: E402


class ContributeTaxableQuoteTests(unittest.TestCase):
    def test_exhaustive_quote_reconciles_in_integer_paise(self):
        terms = contribute_taxable.breakdown(30000)
        expected = {
            "itemSubtotalPaise": 23541,
            "catalogGrossPaise": 30000,
            "supplyGstPaise": 4237,
            "supplyGstBps": 1800,
            "delightPaise": 138,
            "expressPaise": 1500,
            "collectionBeforeConveniencePaise": 29140,
            "convenienceFeePaise": 729,
            "convenienceGstPaise": 131,
            "convenienceGstBps": 1800,
            "totalPayablePaise": 30000,
        }
        self.assertEqual(terms, expected)
        self.assertEqual(
            terms["itemSubtotalPaise"] + terms["supplyGstPaise"]
            - terms["delightPaise"] + terms["expressPaise"]
            + terms["convenienceFeePaise"] + terms["convenienceGstPaise"],
            terms["totalPayablePaise"],
        )
        self.assertTrue(all(type(value) is int for value in terms.values()))

    def test_rejects_catalog_drift_and_non_integer_money(self):
        for invalid in (29999, 30001, 0, -1, True, 30000.0, "30000", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                contribute_taxable.breakdown(invalid)

    def test_policy_is_pinned_to_reviewable_revision(self):
        self.assertEqual(contribute_taxable.CATALOG_TOTAL_PAISE, 30000)
        self.assertEqual(contribute_taxable.ITEM_BASE_PAISE, 23541)
        self.assertEqual(contribute_taxable.EXPRESS_PAISE, 1500)
        self.assertEqual(contribute_taxable.POLICY, "contribute-taxable-review-2026-11-01")


if __name__ == "__main__":
    unittest.main()
