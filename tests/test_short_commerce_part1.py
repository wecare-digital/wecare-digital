"""Offline contract checks for Short Commerce Part 1.

Run: python -m unittest discover -s tests -p test_short_commerce_part1.py
No AWS, Razorpay, Meta, or customer access is required.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/short_purchase.py"
spec = importlib.util.spec_from_file_location("wecare_short_purchase", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load Short Commerce policy")
short_purchase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(short_purchase)


def basket(lines, dropped=0, clamped=0):
    return SimpleNamespace(lines=lines, dropped=dropped, clamped=clamped)


def order(items):
    return {"order": {"product_items": items}}


class ShortPurchaseTests(unittest.TestCase):
    def test_flag_defaults_off_and_requires_explicit_enable(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(short_purchase.enabled())
        with patch.dict(os.environ, {"SHORT_COMMERCE_PART1_ENABLED": "true"}):
            self.assertTrue(short_purchase.enabled())
        with patch.dict(os.environ, {"SHORT_COMMERCE_PART1_ENABLED": "false"}):
            self.assertFalse(short_purchase.enabled())

    def test_exactly_one_integer_unit(self):
        self.assertTrue(short_purchase.one_unit_lines([{"quantity": 1}]))
        for lines in ([], [{"quantity": 2}], [{"quantity": 0}], [{"quantity": 1.0}],
                      [{"quantity": "1"}], [{"quantity": True}], [{"quantity": 1}, {"quantity": 1}],
                      [{"notQuantity": 1}], [None]):
            with self.subTest(lines=lines):
                self.assertFalse(short_purchase.one_unit_lines(lines))

    def test_whatsapp_native_single_item(self):
        valid = basket([{"productId": "p", "variantId": "v", "quantity": 1}])
        self.assertTrue(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 1}]), valid))
        self.assertTrue(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": "1"}]), valid))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 2}]), valid))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": True}]), valid))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 0}]), valid))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 1},
                                                                         {"quantity": 1}]), valid))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 1}]),
            basket([{"quantity": 1}], dropped=1)))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 1}]),
            basket([{"quantity": 1}], clamped=1)))
        self.assertFalse(short_purchase.whatsapp_order_is_one_unit(order([{"quantity": 1}]),
            basket([{"quantity": 2}])))

    def test_frontend_has_two_real_channels_and_no_pricing_authority(self):
        page = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
        cart = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
        self.assertIn("void proceed( 'website' );", page)
        self.assertIn("void proceed( 'whatsapp' );", page)
        self.assertNotIn("window.location.assign( CHECKOUT_METHOD_PATH )", page)
        self.assertIn("stashPendingAction( { kind: 'checkout', channel: chosenChannel } )", page)
        self.assertIn("writeCart( [ selected ] );", cart)
        self.assertIn("if ( items.length > 1 ) return [];", cart)
        self.assertIn("quantity: 1", cart)
        self.assertIn("catalogReference:", cart)


if __name__ == "__main__":
    unittest.main()
