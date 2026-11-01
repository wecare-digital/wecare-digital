"""Pure staff Contribute guard tests: no actual payment or message is sent."""
import copy
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import contribute_taxable, staff_contribution  # noqa: E402

PRODUCT_ID = "24fa0f39-330b-5365-b7eb-9caf27ad37f1"
VARIANT_ID = "CNT5Q2M8"


def catalog():
    return {
        "id": PRODUCT_ID,
        "status": "active",
        "currency": "INR",
        "websiteEnabled": True,
        "variants": [{"sku": VARIANT_ID, "priceMinor": Decimal("30000")}],
    }


def snapshot():
    t = contribute_taxable.breakdown(30000)
    return SimpleNamespace(
        quote=SimpleNamespace(
            total_payable_paise=t["totalPayablePaise"],
            collection_before_convenience_paise=t["collectionBeforeConveniencePaise"],
            convenience_fee_paise=t["convenienceFeePaise"],
            convenience_gst_paise=t["convenienceGstPaise"],
            currency="INR",
        ),
        frozen_data={
            "items": [{"productId": PRODUCT_ID, "variantId": VARIANT_ID,
                       "quantity": 1, "unitPricePaise": t["itemSubtotalPaise"]}],
            "delivery": {"paise": t["expressPaise"]},
            "pricingMetadata": {
                "policy": staff_contribution.STAFF_CONTRIBUTION_POLICY,
                "catalogGrossPaise": 30000,
                "discountPaise": t["delightPaise"],
                "supplyGstPaise": t["supplyGstPaise"],
            },
        },
    )


class StaffContributeGuardTests(unittest.TestCase):
    def good_catalog(self, product):
        return staff_contribution.valid_staff_contribution_catalog_record(
            product, product_id=PRODUCT_ID, variant_id=VARIANT_ID)

    def good_snapshot(self, frozen):
        return staff_contribution.valid_staff_contribution_snapshot(
            frozen, product_id=PRODUCT_ID, variant_id=VARIANT_ID)

    def test_current_canonical_product_is_accepted(self):
        self.assertTrue(self.good_catalog(catalog()))
        modified = catalog()
        modified["variants"][0]["priceMinor"] = 30000
        self.assertTrue(self.good_catalog(modified))

    def test_catalog_rejects_price_variant_identity_and_status_drift(self):
        variants = [
            ("id", "other"), ("status", "inactive"),
            ("currency", "USD"), ("websiteEnabled", False),
            ("websiteEnabled", "true"), ("variants", []),
            ("variants", [{"sku": VARIANT_ID, "priceMinor": Decimal("29999")}]),
            ("variants", [{"sku": VARIANT_ID, "priceMinor": 30000.0}]),
            ("variants", [{"sku": VARIANT_ID, "priceMinor": True}]),
            ("variants", [{"sku": VARIANT_ID, "priceMinor": "30000"}]),
            ("variants", [{"sku": VARIANT_ID, "priceMinor": Decimal("30000")} for _ in range(2)]),
        ]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                row = catalog()
                row[key] = value
                self.assertFalse(self.good_catalog(row))
        self.assertFalse(self.good_catalog(None))
        self.assertFalse(staff_contribution.valid_staff_contribution_catalog_record(
            catalog(), product_id=PRODUCT_ID, variant_id="different"))

    def test_exact_frozen_snapshot_is_accepted(self):
        self.assertTrue(self.good_snapshot(snapshot()))

    def test_frozen_snapshot_rejects_changed_money_identity_or_policy(self):
        mutations = [
            ("total", lambda x: setattr(x.quote, "total_payable_paise", 29999)),
            ("currency", lambda x: setattr(x.quote, "currency", "USD")),
            ("fee", lambda x: setattr(x.quote, "convenience_fee_paise", 730)),
            ("fee_gst", lambda x: setattr(x.quote, "convenience_gst_paise", 132)),
            ("collection", lambda x: setattr(x.quote, "collection_before_convenience_paise", 29141)),
            ("product", lambda x: x.frozen_data["items"][0].__setitem__("productId", "other")),
            ("variant", lambda x: x.frozen_data["items"][0].__setitem__("variantId", "other")),
            ("quantity", lambda x: x.frozen_data["items"][0].__setitem__("quantity", 2)),
            ("item_price", lambda x: x.frozen_data["items"][0].__setitem__("unitPricePaise", 23542)),
            ("extra_item", lambda x: x.frozen_data["items"].append(x.frozen_data["items"][0].copy())),
            ("express", lambda x: x.frozen_data["delivery"].__setitem__("paise", 1499)),
            ("policy", lambda x: x.frozen_data["pricingMetadata"].__setitem__("policy", "unapproved")),
            ("discount", lambda x: x.frozen_data["pricingMetadata"].__setitem__("discountPaise", 137)),
            ("supply_gst", lambda x: x.frozen_data["pricingMetadata"].__setitem__("supplyGstPaise", 4236)),
            ("gross", lambda x: x.frozen_data["pricingMetadata"].__setitem__("catalogGrossPaise", 29999)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                row = copy.deepcopy(snapshot())
                mutate(row)
                self.assertFalse(self.good_snapshot(row))

    def test_missing_snapshot_is_rejected(self):
        self.assertFalse(self.good_snapshot(None))
        self.assertFalse(self.good_snapshot(SimpleNamespace(quote=None, frozen_data={})))
        self.assertFalse(self.good_snapshot(SimpleNamespace(quote=snapshot().quote, frozen_data=None)))


if __name__ == "__main__":
    unittest.main()
