"""Pure money-guard regressions. No AWS/Meta/payments are contacted."""
from __future__ import annotations

import copy
from decimal import Decimal
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "amplify" / "functions" / "shared"))
from lambda_utils.ecommerce.staff_contribution import (
    STAFF_CONTRIBUTION_TOTAL_PAISE,
    valid_staff_contribution_snapshot,
    valid_staff_contribution_catalog_record,
)

PRODUCT = "24fa0f39-330b-5365-b7eb-9caf27ad37f1"
VARIANT = "CNT5Q2M8"


def good():
    q = SimpleNamespace(
        total_payable_paise=30000, collection_before_convenience_paise=30000,
        convenience_fee_paise=0, convenience_gst_paise=0, currency="INR")
    frozen = {
        "items": [{"productId": PRODUCT, "variantId": VARIANT,
                   "quantity": 1, "unitPricePaise": 30000}],
        "delivery": {"paise": 0, "optionId": "resolved"},
        "pricingMetadata": {"policy": "contribution-exempt-2026-10-30"},
    }
    return SimpleNamespace(quote=q, frozen_data=frozen)


def accepts(quote):
    return valid_staff_contribution_snapshot(quote, product_id=PRODUCT, variant_id=VARIANT)


class StaffContributionGuardTests(unittest.TestCase):
    def test_exact_300_fee_exempt_single_sku(self):
        self.assertEqual(STAFF_CONTRIBUTION_TOTAL_PAISE, 30000)
        self.assertTrue(accepts(good()))

    def test_total_or_collection_drift_denied(self):
        for field in ("total_payable_paise", "collection_before_convenience_paise"):
            with self.subTest(field=field):
                q = good()
                setattr(q.quote, field, 29999)
                self.assertFalse(accepts(q))

    def test_fee_gst_and_currency_denied(self):
        for key, value in (("convenience_fee_paise", 1), ("convenience_gst_paise", 1),
                           ("currency", "USD")):
            with self.subTest(field=key):
                q = good()
                setattr(q.quote, key, value)
                self.assertFalse(accepts(q))

    def test_wrong_or_forged_item_refused(self):
        for key, value in (("productId", "another-product"), ("variantId", "OTHER"),
                           ("quantity", 2), ("quantity", True),
                           ("unitPricePaise", 25000), ("unitPricePaise", 30000.0)):
            with self.subTest(field=key):
                q = good()
                q.frozen_data["items"][0][key] = value
                self.assertFalse(accepts(q))

    def test_more_than_one_item_rejected(self):
        q = good()
        q.frozen_data["items"].append(copy.deepcopy(q.frozen_data["items"][0]))
        self.assertFalse(accepts(q))

    def test_no_shipping_no_discounts_no_supply_gst(self):
        for key, value in (("paise", 1500),):
            q = good()
            q.frozen_data["delivery"][key] = value
            self.assertFalse(accepts(q))
        for key, value in (("discountPaise", 138), ("supplyGstPaise", 4237),
                           ("policy", "vault-dropdocs-explicit-gst-2026-10-28")):
            with self.subTest(key=key):
                q = good()
                q.frozen_data["pricingMetadata"][key] = value
                self.assertFalse(accepts(q))

    def test_missing_or_corrupt_snapshot_refused(self):
        for x in [None, {}, object(), SimpleNamespace(quote=None, frozen_data={})]:
            with self.subTest(value=type(x)):
                self.assertFalse(accepts(x))
        q = good()
        q.frozen_data.pop("pricingMetadata")
        self.assertFalse(accepts(q))

    def test_expected_identity_not_taken_from_browser(self):
        q = good()
        self.assertFalse(valid_staff_contribution_snapshot(
            q, product_id="another-product", variant_id=VARIANT))
        self.assertFalse(valid_staff_contribution_snapshot(
            q, product_id=PRODUCT, variant_id="another-variant"))



class StaffContributionCatalogFraudTests(unittest.TestCase):
    def record(self):
        return {
            "id": PRODUCT, "status": "active", "currency": "INR",
            "websiteEnabled": True, "metaEnabled": False,
            "variants": [{"id": VARIANT, "sku": VARIANT,
                          "priceMinor": Decimal("30000")}],
        }

    def accepts(self, row):
        return valid_staff_contribution_catalog_record(
            row, product_id=PRODUCT, variant_id=VARIANT)

    def test_exact_strong_catalog_record(self):
        self.assertTrue(self.accepts(self.record()))
        row = self.record()
        row["variants"][0]["priceMinor"] = 30000
        self.assertTrue(self.accepts(row))

    def test_price_250_and_30001_refused(self):
        for value in [25000, 30001, Decimal("29999"), Decimal("30000.01")]:
            with self.subTest(amount=value):
                row = self.record()
                row["variants"][0]["priceMinor"] = value
                self.assertFalse(self.accepts(row))

    def test_forged_or_non_integer_price_refused(self):
        for value in [True, 30000.0, "30000", None, Decimal("NaN")]:
            with self.subTest(kind=str(value)):
                row = self.record()
                row["variants"][0]["priceMinor"] = value
                self.assertFalse(self.accepts(row))

    def test_inactive_hidden_foreign_currency_or_product_refused(self):
        for field, value in [
            ("id", "another-product"), ("status", "inactive"),
            ("currency", "USD"), ("websiteEnabled", False),
            ("websiteEnabled", "true"),
        ]:
            with self.subTest(field=field):
                row = self.record()
                row[field] = value
                self.assertFalse(self.accepts(row))

    def test_variant_substitution_and_ambiguity_refused(self):
        row = self.record()
        row["variants"][0]["id"] = "OTHER"
        row["variants"][0]["sku"] = "OTHER"
        self.assertFalse(self.accepts(row))
        row = self.record()
        row["variants"].append(copy.deepcopy(row["variants"][0]))
        self.assertFalse(self.accepts(row))
        self.assertFalse(self.accepts(None))



if __name__ == "__main__":
    unittest.main()
