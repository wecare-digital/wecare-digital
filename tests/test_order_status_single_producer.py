"""Static guards for the disabled WhatsApp order-status rail. Standard library only.

Product policy (#1650): structured WhatsApp order-status messages are disabled and fulfilment
status stays internal. These checks read source, so they also run in CI jobs that install
nothing:

* no runtime code builds an outbound `orderStatusDetails` payload (the inbound webhook's
  kill-switched `canceled` sender, the last producer, is gone);
* outbound-whatsapp refuses an order-status request with 410 before any template lookup or send;
* the invoice engine's order-status route refuses without calling another Lambda;
* the Razorpay webhook keeps none of the retired automatic or retried order-status machinery;
* no code builds an interactive `order_status` message.
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
INBOUND = FUNCTIONS / "messaging" / "inbound-whatsapp-handler" / "handler.py"
WEBHOOK = FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py"
WA_ORDER_STATUS = FUNCTIONS / "shared" / "lambda_utils" / "ecommerce" / "wa_order_status.py"

#: `'orderStatusDetails': {...}` written as a dict key is a payload being BUILT for outbound.
_PRODUCER = re.compile(r"""["']orderStatusDetails["']\s*:""")


def _function(path: Path, name: str) -> tuple[ast.FunctionDef, str]:
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node, ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in {path}")


class NoProducerTests(unittest.TestCase):
    def test_no_runtime_code_builds_an_order_status_payload(self):
        producers = sorted(
            str(path.relative_to(ROOT))
            for path in FUNCTIONS.rglob("*.py")
            if _PRODUCER.search(path.read_text(encoding="utf-8", errors="replace"))
        )
        self.assertEqual(producers, [])

    def test_inbound_has_no_order_status_sender(self):
        source = INBOUND.read_text(encoding="utf-8")
        for retired in ("_send_order_status_message", "_inbound_order_status_enabled",
                        "whatsapp_inbound_order_status", "isOrderStatus"):
            self.assertNotIn(retired, source)

    def test_webhook_keeps_no_order_status_machinery(self):
        source = WEBHOOK.read_text(encoding="utf-8")
        for retired in ("def _send_order_status_processing", "def _start_native_fulfilment",
                        "def _invoke_order_status", "/order-status"):
            self.assertNotIn(retired, source)


class DisabledChokepointTests(unittest.TestCase):
    def test_outbound_refuses_order_status_before_any_lookup_or_send(self):
        _node, source = _function(OUTBOUND, "handler")
        refusal = source.find("'ORDER_STATUS_DISABLED'")
        self.assertGreater(refusal, 0)
        self.assertIn("410", source[max(0, refusal - 80):refusal])
        for later in ("_approved_order_status_template(", "_handle_order_status_send("):
            position = source.find(later)
            if position != -1:
                self.assertLess(refusal, position, later)

    def test_invoice_engine_order_status_route_refuses_without_invoking(self):
        _node, source = _function(INVOICE_ENGINE, "send_order_status")
        self.assertIn("ORDER_STATUS_DISABLED", source)
        self.assertIn("410", source)
        self.assertNotIn(".invoke(", source)

    def test_no_interactive_order_status_builder_exists(self):
        source = WA_ORDER_STATUS.read_text(encoding="utf-8")
        self.assertNotIn("build_interactive_payload", source)
        self.assertNotIn("review_order", source)


if __name__ == "__main__":
    unittest.main()
