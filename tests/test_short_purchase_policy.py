"""Offline contract checks for the opt-in Short Commerce server-side guard.

Run: python -m unittest discover -s tests -p test_short_purchase_policy.py
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

    def test_direct_whatsapp_create_guard_precedes_any_payment_write(self):
        # The browser sends action=create for Pay on WhatsApp; this route
        # bypasses _website_prepare and must be independently guarded.
        checkout = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(
            encoding="utf-8")
        self.assertIn('return _create(identity, body, origin)', checkout)
        create = checkout.split("def _create(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn(
            "short_purchase.enabled() and not short_purchase.one_unit_lines(line_items)",
            create)
        self.assertIn('"error": "SHORT_CHECKOUT_ONE_ITEM"', create)
        guard = create.index("short_purchase.enabled()")
        self.assertLess(guard, create.index("service_guard = service_requests.checkout_preflight"))
        self.assertLess(guard, create.index("snapshot = _native_quote"))
        self.assertLess(guard, create.index("attempt_id = payment_attempt.new_payment_attempt_id()"))

    def test_website_native_and_claim_preflight_integration(self):
        checkout = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
        inbound = (ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py").read_text(encoding="utf-8")
        website = checkout.split("def _website_prepare(", 1)[1].split("\ndef ", 1)[0]
        claim = checkout.split("def _claim_basket(", 1)[1].split("\ndef ", 1)[0]
        native = checkout.split("def _native_cart(", 1)[1]
        incoming = inbound.split("def _handle_cart_order(", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("short_purchase.one_unit_lines(line_items)", website)
        self.assertLess(website.index("service_requests.checkout_preflight"),
                        website.index("profile = _checkout_profile(identity)"))
        self.assertLess(claim.index("BASKET_SHORT_ONLY"), claim.index("carts.ensure("))
        self.assertLess(native.index("NATIVE_CART_SHORT_ONLY"), native.index("_wa_cart_live_key("))
        self.assertLess(incoming.index("cart_order_short_only_refused"), incoming.index("service_from_lines"))
        self.assertIn("CART_REPLY_SHORT_ONLY", inbound)

    def test_website_checkout_does_not_autopay_after_sign_in(self):
        page = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
        self.assertIn("takePendingAction()", page)
        self.assertNotIn("void proceed( pending.channel )", page)
        self.assertIn("const chosenChannel: CheckoutChannel = 'website'", page)
        self.assertIn("options.amountPaise !== expectedTotalPaise", page)


    def test_website_payment_requires_reviewed_server_quote(self):
        page = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
        self.assertIn("parseCheckoutQuote( body )", page)
        self.assertIn("quoteFor !== basketFingerprint( lineItems )", page)
        self.assertIn("options.amountPaise !== expectedTotalPaise", page)
        self.assertIn("return { kind: 'QUOTE_CHANGED' };", page)
        self.assertIn("disabled={ busy || !quoteReady }", page)
        # Native multi-unit refusal remains server-side, not a website cart limit.
        backend = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
        self.assertIn('"error": "SHORT_CHECKOUT_ONE_ITEM"', backend)

    def test_claim_failure_keeps_catalog_snapshot_refusal_distinct(self):
        page = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
        basket = (ROOT / "src/lib/whatsappBasket.ts").read_text(encoding="utf-8")
        # Preserve PR #1964's correct fallback; do not blame customers for a stale
        # website catalogue when they sent a valid one-unit WhatsApp item.
        self.assertIn("CLAIM_NOT_SHOWN_MESSAGE : null", page)
        self.assertNotIn("notShortBasket", page)
        self.assertIn("status === 'BASKET_SHORT_ONLY'", basket)
        self.assertIn("case 'SHORT_ONLY':", basket)
        self.assertIn("Nothing has been", (ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py").read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
