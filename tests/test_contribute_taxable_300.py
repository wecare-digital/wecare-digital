"""Contribute ₹300 native payment cannot silently drift or reuse Vault fees.

Run with PYTHONPATH=amplify/functions/shared:
    python3 -m unittest discover -s tests -p test_contribute_taxable_300.py
"""
from __future__ import annotations

import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lambda_utils.ecommerce import (
    checkout_pricing, contribute_taxable, service_pricing_native,
    staff_contribution,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCT = "24fa0f39-330b-5365-b7eb-9caf27ad37f1"
VARIANT = "CNT5Q2M8"


def frozen_snapshot():
    terms = contribute_taxable.breakdown(30000)
    return SimpleNamespace(
        quote=checkout_pricing.compute_quote(29140, currency="INR"),
        frozen_data={
            "items": [
                {"productId": PRODUCT, "variantId": VARIANT, "quantity": 1,
                 "unitPricePaise": 23541}
            ],
            "delivery": {"paise": 1500, "optionId": "contribute-express"},
            "pricingMetadata": {
                "policy": contribute_taxable.POLICY,
                "catalogGrossPaise": 30000,
                "supplyGstPaise": 4237,
                "discountPaise": 138,
            },
        },
    )


class ContributeTaxable300Tests(unittest.TestCase):
    def test_every_paise_exact_and_300_total(self):
        terms = contribute_taxable.breakdown(30000)
        self.assertEqual((
            terms["itemSubtotalPaise"], terms["supplyGstPaise"],
            terms["delightPaise"], terms["expressPaise"],
            terms["collectionBeforeConveniencePaise"],
            terms["convenienceFeePaise"], terms["convenienceGstPaise"],
            terms["totalPayablePaise"],
        ), (23541, 4237, 138, 1500, 29140, 729, 131, 30000))
        self.assertEqual(
            23541 + 4237 - 138 + 1500 + 729 + 131, 30000)

    def test_discount_is_canonical_not_balancing_plug(self):
        with patch.object(contribute_taxable.default_coupon, "delight_paise", return_value=137):
            with self.assertRaises(ValueError):
                contribute_taxable.breakdown(30000)

    def test_catalog_gross_drift_fails_closed(self):
        for value in (None, True, 23541, 29999, 30001, 30000.0, "30000", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                contribute_taxable.breakdown(value)

    def test_service_price_uses_same_calculation(self):
        self.assertEqual(
            service_pricing_native._contribution_breakdown(30000),
            contribute_taxable.breakdown(30000))

    def test_staff_quote_matches_exact_frozen_terms(self):
        snapshot = frozen_snapshot()
        self.assertTrue(staff_contribution.valid_staff_contribution_snapshot(
            snapshot, product_id=PRODUCT, variant_id=VARIANT))

    def test_staff_refuses_each_tampered_tax_fee_and_identity(self):
        snapshot = frozen_snapshot()
        changes = (
            ("fee", lambda s: setattr(
                s, "quote", checkout_pricing.exempt_quote(30000, currency="INR"))),
            ("supplyGST", lambda s: s.frozen_data["pricingMetadata"].update(
                supplyGstPaise=4236)),
            ("discount", lambda s: s.frozen_data["pricingMetadata"].update(
                discountPaise=137)),
            ("Express", lambda s: s.frozen_data["delivery"].update(paise=0)),
            ("item", lambda s: s.frozen_data["items"][0].update(
                unitPricePaise=30000)),
            ("gross", lambda s: s.frozen_data["pricingMetadata"].update(
                catalogGrossPaise=29999)),
        )
        for name, mutate in changes:
            with self.subTest(name=name):
                case = frozen_snapshot()
                mutate(case)
                self.assertFalse(staff_contribution.valid_staff_contribution_snapshot(
                    case, product_id=PRODUCT, variant_id=VARIANT))
        self.assertFalse(staff_contribution.valid_staff_contribution_snapshot(
            snapshot, product_id=PRODUCT, variant_id="OTHER"))

    def test_flags_default_off_and_frozen_server_owned_money(self):
        checkout = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
        self.assertIn('CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED', checkout)
        self.assertIn('CONTRIBUTION_TAXABLE_NOT_RELEASED', checkout)
        self.assertIn('STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED', checkout)
        self.assertIn('contribute_taxable.breakdown(source["unitPricePaise"])', checkout)
        self.assertIn('invoiceLines', checkout)
        self.assertIn('supplyGstPaise', checkout)

    def test_fixed_template_and_popup_unmodified_by_new_flow(self):
        sender = (ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py").read_text()
        menu = (ROOT / "src/components/PublicShare.tsx").read_text()
        frontend = (ROOT / "src/lib/customerMenuActions.ts").read_text()
        self.assertIn("wecare_whatapp_native_pay_template", sender)
        self.assertIn("'sub_type': 'order_details'", sender)
        self.assertIn("clean_item.pop('image', None)", sender)
        self.assertIn("Stay connected", menu)
        self.assertIn("Review, then pay on WhatsApp", menu)
        self.assertIn("Give back", menu)
        self.assertIn("'contribute'", frontend)
        self.assertIn("/ecommerce/checkout", frontend)


if __name__ == "__main__":
    unittest.main()
