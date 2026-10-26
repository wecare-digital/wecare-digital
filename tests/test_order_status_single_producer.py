"""Static guards for the automatic WhatsApp payment-order status rail.

The paid WhatsApp ORDER_DETAILS flow must emit exactly the payment-order lifecycle
pending -> processing -> completed through the approved template wecare_order_status_v3.
Shipment states are not part of this automatic payment rail.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
INVOICE_ENGINE = FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
OUTBOUND = FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py"
WEBHOOK = FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py"
WA_ORDER_STATUS = FUNCTIONS / "shared" / "lambda_utils" / "ecommerce" / "wa_order_status.py"
TEMPLATES = FUNCTIONS / "shared" / "lambda_utils" / "whatsapp_templates.py"


def _function(path: Path, name: str) -> tuple[ast.FunctionDef, str]:
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node, ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in {path}")


class AutomaticPaymentOrderStatusTests(unittest.TestCase):
    def test_webhook_runs_processing_then_completed(self):
        _node, source = _function(WEBHOOK, "_start_native_fulfilment")
        processing = source.find("'processing'")
        completed = source.find("'completed'")
        self.assertGreater(processing, 0)
        self.assertGreater(completed, processing)
        self.assertIn("Payment received.", source)
        self.assertIn("Payment complete.", source)

    def test_completed_is_blocked_until_processing_accepts(self):
        _node, source = _function(WEBHOOK, "_start_native_fulfilment")
        self.assertIn("processing_status == 200", source)
        self.assertIn("ORDER_STATUS_UNCHANGED", source)
        self.assertIn("order_status_completed_blocked", source)

    def test_invoice_engine_owns_payment_only_state_machine(self):
        _node, source = _function(INVOICE_ENGINE, "send_order_status")
        self.assertIn("PAYMENT_ORDER_TARGETS", source)
        self.assertIn("payment_can_transition", source)
        self.assertIn("waOrderStatus", source)
        self.assertIn("orderStatusRetry", source)
        self.assertNotIn("ORDER_STATUS_DISABLED", source)

    def test_outbound_uses_single_approved_template_sender(self):
        source = OUTBOUND.read_text(encoding="utf-8")
        self.assertIn("def _approved_order_status_template", source)
        self.assertIn("def _handle_order_status_send", source)
        self.assertIn("WA_ORDER_STATUS_TEMPLATE", source)
        self.assertIn("ORDER_STATUS_DEFERRED", source)
        self.assertNotIn("ORDER_STATUS_DISABLED", source)

    def test_registry_names_expected_template_once(self):
        source = TEMPLATES.read_text(encoding="utf-8")
        self.assertIn("wecare_order_status_v3", source)
        self.assertNotIn("wecare_order_status_v3wecare_order_status_v3", source)

    def test_no_interactive_fallback_builder(self):
        source = WA_ORDER_STATUS.read_text(encoding="utf-8")
        self.assertIn("build_template_component", source)
        self.assertNotIn("build_interactive_payload", source)


if __name__ == "__main__":
    unittest.main()
