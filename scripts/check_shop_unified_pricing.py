"""Pinned 29-item owner-approved unified price contract, all amounts in paise.

This is a pure, read-only regression suite. It never creates payment attempts,
modifies ProductsTable, talks to Razorpay or sends a WhatsApp template.

Run manually with boto3 installed:
     PYTHONPATH=amplify/functions/shared python3 scripts/check_shop_unified_pricing.py -v

The target branch intentionally removed tests/ and .github/workflows/;
keep this validation script in scripts/ rather than recreating retired directories.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from lambda_utils.ecommerce import (
    checkout_pricing, contribute_taxable, express_policy, service_pricing_native,
    service_requests, unified_pricing,
)

# name, taxable base, supply GST, Delight, Express, convenience, GST on
# convenience, final total. Values supplied by the WECARE.DIGITAL owner.
# Contribute's base is a breakdown of its unchanged Rs300 catalog gross target.
APPROVED_PAIRS = [
    ("Grahak OS", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("VayuLok", 9900, 1782, 58, 4500, 403, 73, 16600),
    ("Sehat", 85000, 15300, 501, 4500, 2607, 469, 107375),
    ("Elsewhere · Visa", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Elsewhere · Trip", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Activities", 9900, 1782, 58, 4500, 403, 73, 16600),
    ("Expo Week", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Dastavez · Drafting", 149900, 26982, 884, 4500, 4512, 812, 185822),
    ("Dastavez · Registration", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Dastavez · Legal Reference", 59900, 10782, 353, 4500, 1871, 337, 77037),
    ("Clear Closure · Guided Resolution", 199900, 35982, 1179, 4500, 5980, 1076, 246259),
    ("Clear Closure · Case Submission", 149900, 26982, 884, 4500, 4512, 812, 185822),
    ("Clear Closure · Paperwork", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Ritual Guru · Puja Guidance", 39900, 7182, 235, 4500, 1284, 231, 52862),
    ("Ritual Guru · DIY Puja Kit", 89900, 16182, 530, 4500, 2751, 495, 113298),
    ("Ritva", 9900, 1782, 58, 4500, 403, 73, 16600),
    ("Anew", 59900, 10782, 353, 4500, 1871, 337, 77037),
    ("Hunar · Kaushal", 9900, 1782, 58, 4500, 403, 73, 16600),
    ("Hunar · Prastuti", 29900, 5382, 176, 4500, 990, 178, 40774),
    ("Niji Setu", 29900, 5382, 176, 4500, 990, 178, 40774),
    ("Partner · Merchandise", 199900, 35982, 1179, 4500, 5980, 1076, 246259),
    ("Partner · Kiosk", 2699900, 485982, 5000, 4500, 79635, 14334, 3279351),
    ("Contribute", 23541, 4237, 138, 1500, 729, 131, 30000),
    ("Request · Submit Request", 9900, 1782, 58, 4500, 403, 73, 16600),
    ("Request · Amendment", 19900, 3582, 117, 4500, 697, 125, 28687),
    ("Request · Drop Docs", 19900, 3582, 117, 4500, 697, 125, 28687),
    ("Request · Vault", 4900, 882, 28, 2500, 206, 37, 8497),
    ("Shipment · Track", 4900, 882, 28, 4500, 256, 46, 10556),
    ("Shipment · Pickup", 65000, 11700, 383, 4500, 2020, 364, 83201),
]


class UnifiedShopPricingTests(unittest.TestCase):
    def test_every_approved_product_matches_exactly_to_the_paise(self):
        self.assertEqual(len(APPROVED_PAIRS), 29)
        self.assertEqual(sum(name == "Contribute" for name, *_ in APPROVED_PAIRS), 1)
        for name, base, gst, delight, express, fee, fee_gst, total in APPROVED_PAIRS:
            with self.subTest(item=name):
                if name == "Contribute":
                    terms = contribute_taxable.breakdown(30_000)
                else:
                    terms = unified_pricing.price_components(base, express_paise=express)
                self.assertEqual(terms["itemSubtotalPaise"], base)
                self.assertEqual(terms["supplyGstPaise"], gst)
                self.assertEqual(terms["delightPaise"], delight)
                self.assertEqual(terms["expressPaise"], express)
                self.assertEqual(terms["convenienceFeePaise"], fee)
                self.assertEqual(terms["convenienceGstPaise"], fee_gst)
                self.assertEqual(terms["totalPayablePaise"], total)
                self.assertEqual(
                    base + gst - delight + express + fee + fee_gst, total)
                self.assertEqual(
                    fee, checkout_pricing.round_half_up(
                        base + gst - delight + express, 250))
                self.assertEqual(
                    fee_gst, checkout_pricing.round_half_up(fee, 1800))

    def base_snapshot(self, items=None, *, collection=None):
        items = items or [{
            "lineItemId": "sku-one",
            "productId": "product-one",
            "variantId": "sku-one",
            "quantity": 1,
            "unitPricePaise": 9_900,
        }]
        # A frozen quote only carries backend-registered amounts. All synthetic
        # ordinary test lines use the Rs45 policy unless explicitly Vault.
        items = [dict(row, expressPaise=row.get("expressPaise", 4500)) for row in items]
        subtotal = sum(row["quantity"] * row["unitPricePaise"] for row in items)
        quote = checkout_pricing.compute_quote(
            collection if collection is not None else subtotal)
        return checkout_pricing.build_snapshot(
            customer_id="TEST-SHOP-CUSTOMER",
            cart_id="native:cart-basket",
            cart_revision=0,
            quote=quote,
            created_at=1_800_000_000,
            ttl_seconds=900,
            site="aws-native",
            items=items,
            address=None,
            delivery={"paise": 0, "optionId": "resolved"},
        )

    def test_server_priced_snapshot_carries_all_checkout_invoice_components(self):
        base = self.base_snapshot()
        frozen_before = dict(base.frozen_data)
        priced = unified_pricing.quote_from_base_snapshot(base)
        data = priced.frozen_data
        self.assertEqual(data["items"], frozen_before["items"])
        self.assertEqual(data["pricingMetadata"]["policy"], unified_pricing.POLICY)
        self.assertEqual(data["pricingMetadata"]["supplyGstPaise"], 1782)
        self.assertEqual(data["pricingMetadata"]["discountPaise"], 58)
        self.assertEqual(data["delivery"], {
            "paise": 4500, "optionId": "express",
        })
        self.assertEqual(priced.quote.total_payable_paise, 16600)
        self.assertNotEqual(priced.snapshot_hash, base.snapshot_hash)
        self.assertEqual(base.frozen_data["delivery"]["paise"], 0)

    def test_two_item_cart_has_one_express_and_one_delight(self):
        items = [
            {"lineItemId": "sku-one", "productId": "one", "variantId": "sku-one",
             "quantity": 1, "unitPricePaise": 89_900},
            {"lineItemId": "sku-two", "productId": "two", "variantId": "sku-two",
             "quantity": 2, "unitPricePaise": 9_900},
        ]
        subtotal = 89_900 + 2 * 9_900
        terms = unified_pricing.price_components(subtotal)
        self.assertEqual(terms["expressPaise"], 4_500)
        self.assertEqual(terms["supplyGstPaise"],
                         checkout_pricing.round_half_up(subtotal, 1800))
        self.assertEqual(terms["delightPaise"],
                         (subtotal + terms["supplyGstPaise"]) * 50 // 10000)
        self.assertEqual(
            unified_pricing.quote_from_base_snapshot(
                self.base_snapshot(items)).quote.total_payable_paise,
            terms["totalPayablePaise"],
        )

    def test_delight_capped_once_for_high_value_cart(self):
        terms = unified_pricing.price_components(26_999 * 100)
        self.assertEqual(terms["delightPaise"], 5_000)
        self.assertEqual(terms["totalPayablePaise"], 3_279_351)

    def test_invalid_or_double_adjusted_base_fails_closed(self):
        for invalid in (0, -1, True, 9.5, "9900", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(checkout_pricing.PricingError):
                    unified_pricing.price_components(invalid)
        with self.assertRaises(checkout_pricing.PricingError):
            unified_pricing.quote_from_base_snapshot(
                self.base_snapshot(collection=9_841))
        with self.assertRaises(checkout_pricing.PricingError):
            unified_pricing.quote_from_base_snapshot(
                unified_pricing.quote_from_base_snapshot(self.base_snapshot()))

    def test_five_request_services_and_shipment_preview_use_same_formula(self):
        for kind in service_requests.SERVICE_KIND_BY_SLUG.values():
            with self.subTest(service=kind):
                expected = (express_policy.VAULT_EXPRESS_PAISE
                            if kind == service_requests.VAULT
                            else express_policy.STANDARD_EXPRESS_PAISE)
                self.assertEqual(
                    service_pricing_native._collect_breakdown(kind, 9_900),
                    unified_pricing.price_components(9_900, express_paise=expected),
                )
        self.assertIsNone(service_pricing_native._collect_breakdown("bad-kind", 9_900))

    def test_contribute_gross_contract_unchanged(self):
        terms = contribute_taxable.breakdown(30_000)
        self.assertEqual(terms["expressPaise"], express_policy.CONTRIBUTE_EXPRESS_PAISE)
        self.assertEqual(terms["totalPayablePaise"], 30_000)

    def test_vault_registry_rate_and_mixed_cart_fail_closed(self):
        vault = {
            "lineItemId": express_policy.VAULT_VARIANT_ID,
            "productId": express_policy.VAULT_PRODUCT_ID,
            "variantId": express_policy.VAULT_VARIANT_ID,
            "quantity": 1,
            "unitPricePaise": 4_900,
            "expressPaise": 2_500,
        }
        quote = unified_pricing.quote_from_base_snapshot(self.base_snapshot([vault]))
        self.assertEqual(quote.quote.total_payable_paise, 8_497)
        self.assertEqual(quote.frozen_data["delivery"]["paise"], 2_500)
        self.assertEqual(quote.frozen_data["pricingMetadata"]["expressPaise"], 2_500)
        self.assertEqual(
            express_policy.expected_express_paise(
                express_policy.CONTRIBUTE_PRODUCT_ID,
                express_policy.CONTRIBUTE_VARIANT_ID), 1_500)
        self.assertEqual(
            express_policy.expected_express_paise(
                express_policy.VAULT_PRODUCT_ID,
                express_policy.VAULT_VARIANT_ID), 2_500)
        # A missing or stale backend register is not a reason to guess fees.
        for bad_fee in (None, 4_500, 1_500, 25.0, True):
            with self.subTest(bad_fee=bad_fee):
                with self.assertRaises(checkout_pricing.PricingError):
                    unified_pricing.quote_from_base_snapshot(
                        self.base_snapshot([dict(vault, expressPaise=bad_fee)]))
        other = {
            "lineItemId": "sku-ordinary", "productId": "product-ordinary",
            "variantId": "sku-ordinary", "quantity": 2,
            "unitPricePaise": 9_900, "expressPaise": 4_500,
        }
        with self.assertRaises(checkout_pricing.PricingError):
            unified_pricing.quote_from_base_snapshot(
                self.base_snapshot([vault, other]))

    def test_backend_manifest_contains_29_approved_skus_without_test_product(self):
        import json
        from collections import Counter
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "scripts/shop_express_register_20261102.json").read_text(encoding="utf-8"))
        records = manifest["items"]
        self.assertEqual(len(records), 29)
        self.assertEqual(len({x["productId"] for x in records}), 29)
        self.assertEqual(len({x["variantId"] for x in records}), 29)
        self.assertNotIn("native:commerce-test-2", {x["productId"] for x in records})
        self.assertEqual(Counter(x["expressPaise"] for x in records),
                         Counter({1500: 1, 2500: 1, 4500: 27}))
        vault = next(x for x in records if x["slug"] == "vault")
        self.assertEqual((vault["productId"], vault["variantId"], vault["basePricePaise"]),
                         (express_policy.VAULT_PRODUCT_ID, express_policy.VAULT_VARIANT_ID, 4900))
        contribute = next(x for x in records if x["slug"] == "contribute")
        self.assertEqual(contribute["basePricePaise"], 30000)
        prices = Counter(base for name,base,*_ in APPROVED_PAIRS if name != "Contribute")
        self.assertEqual(prices,
                         Counter(x["basePricePaise"] for x in records if x["slug"] != "contribute"))
        for x in records:
            self.assertEqual(
                express_policy.expected_express_paise(x["productId"], x["variantId"]),
                x["expressPaise"])

    def test_public_price_register_rejects_stale_vault_fee(self):
        from lambda_utils.ecommerce import blog_contribution
        lookup = {}
        for kind,sku in service_requests.SERVICE_VARIANT_BY_KIND.items():
            lookup[sku] = {"priceMinor": 4900 if kind == service_requests.VAULT else 9900,
                           "expressPaise": (2500 if kind == service_requests.VAULT else 4500),
                           "currency": "INR", "status": "active"}
        lookup[service_pricing_native.SHIPMENT_TRACK_SKU] = {
            "priceMinor": 4900, "expressPaise": 4500, "currency": "INR",
            "status": "active"}
        for variant in blog_contribution.CONTRIBUTION_VARIANT_IDS:
            lookup[variant] = {"priceMinor": 30000, "expressPaise": 1500,
                               "currency": "INR", "status": "active"}
        priced = service_pricing_native.resolve_all(lambda sku: lookup.get(sku))
        self.assertTrue(priced["prices"]["vault"]["available"])
        self.assertEqual(priced["prices"]["vault"]["breakdown"]["totalPayablePaise"], 8497)
        self.assertEqual(priced["prices"]["vault"]["breakdown"]["expressPaise"], 2500)
        self.assertEqual(priced["prices"]["drop-docs"]["breakdown"]["expressPaise"], 4500)
        self.assertEqual(priced["prices"]["contribute"]["breakdown"]["expressPaise"], 1500)
        lookup[express_policy.VAULT_VARIANT_ID]["expressPaise"] = 4500
        bad = service_pricing_native.resolve_all(lambda sku: lookup.get(sku))
        self.assertFalse(bad["prices"]["vault"]["available"])
        self.assertTrue(bad["prices"]["drop-docs"]["available"])

    def test_invoice_preset_register_has_all_three_rate_tiers(self):
        path = (Path(__file__).resolve().parents[1] /
                "src/content/invoicePresets.json")
        import json
        rows = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 29)
        fees = {
            r["name"]: r["expressPaise"] for r in rows
        }
        self.assertEqual(fees["Request · Vault"], 2500)
        self.assertEqual(fees["Contribute"], 1500)
        self.assertEqual(sum(v == 4500 for v in fees.values()), 27)
        self.assertEqual(
            next(r for r in rows if r["name"] == "Request · Vault")["totalPayablePaise"],
            8497)

    def test_meta_single_sku_multiple_quantity_reconciles_exact_subtotal(self):
        import ast
        from typing import Dict, Any
        path=Path(__file__).resolve().parents[1]/'amplify/functions/ecommerce/checkout/handler.py'
        node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_cart_order_details')
        env={'Dict':Dict,'Any':Any,'_native_product_reader':lambda:lambda pid:{'title':'Sample'},'EXPECTED_CONFIGURATION_NAME':'offline'}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env)
        for quantity in (1,2,3):
            items=[{'lineItemId':'sku-one','productId':'one','variantId':'sku-one','quantity':quantity,'unitPricePaise':9900}]
            snapshot=unified_pricing.quote_from_base_snapshot(self.base_snapshot(items))
            details=env['_cart_order_details'](snapshot,'offline',{}, {},1800000000,requires_delivery=False)
            order=details['order']
            self.assertEqual(sum(line['amount']['value']*line['quantity'] for line in order['items']),order['subtotal']['value'])
            self.assertEqual(order['subtotal']['value']+order['shipping']['value']+order['tax']['value']-order['discount']['value'],details['total_amount']['value'])

    def test_payment_handler_preserves_one_source_and_meta_itemization(self):
        path = (Path(__file__).resolve().parents[1]
                / "amplify/functions/ecommerce/checkout/handler.py")
        body = path.read_text(encoding="utf-8")
        self.assertIn("unified_pricing.quote_from_base_snapshot(base)", body)
        self.assertIn('"name": "Supply GST (18%)"', body)
        self.assertIn("contribute_taxable.breakdown", body)
        self.assertIn("expectedTotalPaise", body)
        self.assertIn("if internal_qa:", body)


if __name__ == "__main__":
    unittest.main()
