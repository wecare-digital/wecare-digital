"""Static guards for the WhatsApp payment-order status rail. Standard library only.

The ORDER_DETAILS rail is payment-only (`pending -> processing -> completed`) and template-only.
These checks read source, so they also run in CI jobs that install nothing:

* the invoice engine is the only producer of an outbound `orderStatusDetails` payload;
* the inbound webhook has no order-status sender (its kill-switched `canceled` sender is gone);
* the Razorpay webhook keeps no dead single-status helper beside the chained lifecycle;
* no code builds an interactive `order_status` message, so the 24-hour window cannot pick one.
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


def _function_source(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def _string_constants(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


class SingleProducerTests(unittest.TestCase):
    def test_invoice_engine_is_the_only_order_status_producer(self):
        producers = sorted(
            str(path.relative_to(ROOT))
            for path in FUNCTIONS.rglob("*.py")
            if _PRODUCER.search(path.read_text(encoding="utf-8", errors="replace"))
        )
        self.assertEqual(producers, [str(INVOICE_ENGINE.relative_to(ROOT))])

    def test_inbound_has_no_order_status_sender(self):
        source = INBOUND.read_text(encoding="utf-8")
        for retired in ("_send_order_status_message", "_inbound_order_status_enabled",
                        "whatsapp_inbound_order_status", "isOrderStatus"):
            self.assertNotIn(retired, source)

    def test_webhook_keeps_only_the_chained_lifecycle(self):
        source = WEBHOOK.read_text(encoding="utf-8")
        self.assertNotIn("def _send_order_status_processing", source)
        self.assertIn("def _start_native_fulfilment", source)


class TemplateOnlyTransportTests(unittest.TestCase):
    def test_no_interactive_order_status_builder_exists(self):
        source = WA_ORDER_STATUS.read_text(encoding="utf-8")
        self.assertNotIn("build_interactive_payload", source)
        self.assertNotIn("review_order", source)

    def test_outbound_order_status_send_builds_only_a_template(self):
        node = _function_source(OUTBOUND, "_handle_order_status_send")
        constants = _string_constants(node)
        self.assertIn("template", constants)
        self.assertNotIn("interactive", constants)
        self.assertNotIn("review_order", constants)
        # The window is an argument for logging only: no branch may test it.
        for branch in (n for n in ast.walk(node) if isinstance(n, (ast.If, ast.IfExp))):
            names = {n.id for n in ast.walk(branch.test) if isinstance(n, ast.Name)}
            self.assertNotIn("within_window", names)

    def test_outbound_refuses_states_outside_the_payment_lifecycle(self):
        node = _function_source(OUTBOUND, "_handle_order_status_send")
        self.assertIn("ORDER_STATUS_NOT_ALLOWED", _string_constants(node))
        attributes = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        self.assertIn("PAYMENT_ORDER_TARGETS", attributes)
        self.assertIn("payment_default_body", attributes)


if __name__ == "__main__":
    unittest.main()
