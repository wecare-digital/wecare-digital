from __future__ import annotations

import importlib.util
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify" / "functions" / "operations" / "whatsapp-analytics-export" / "handler.py"


def _load():
    spec = importlib.util.spec_from_file_location("whatsapp_analytics_export_under_test", HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WhatsAppOperationalAnalyticsPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_delivery_projection_drops_customer_content(self):
        row = self.mod._delivery({
            "id": "m1", "status": "delivered", "templateName": "receipt",
            "to": "+919999999999", "phone": "+919999999999", "body": "secret body",
            "content": "secret", "contactId": "wa919999999999", "customerId": "cust-1",
        })
        blob = json.dumps(row)
        for forbidden in ("+919999999999", "secret body", "wa919999999999", "cust-1"):
            self.assertNotIn(forbidden, blob)

    def test_flow_projection_drops_answers_and_phone(self):
        row = self.mod._flow({
            "submissionId": "s1", "flowCode": "request", "phone": "+919999999999",
            "contactId": "c1", "answers": [{"field": "private"}],
            "formData": {"name": "Private"},
        })
        blob = json.dumps(row)
        self.assertNotIn("+919999999999", blob)
        self.assertNotIn("Private", blob)
        self.assertNotIn("answers", blob)

    def test_order_projection_drops_customer_identity_and_items(self):
        row = self.mod._order({
            "orderId": "o1", "amountPaise": Decimal("1250"), "customerId": "cust-1",
            "customerPhone": "+919999999999", "items": [{"name": "Private item"}],
            "shippingAddress": {"line1": "Private"},
        })
        self.assertEqual(row["amount_paise"], 1250)
        blob = json.dumps(row)
        self.assertNotIn("cust-1", blob)
        self.assertNotIn("+919999999999", blob)
        self.assertNotIn("Private", blob)

    def test_template_lifecycle_allows_only_structured_fields(self):
        row = self.mod._template_lifecycle({
            "id": "e1", "eventType": "template_rejected", "createdAt": Decimal("123"),
            "eventData": json.dumps({
                "templateName": "order_status", "status": "REJECTED", "reasonCode": "POLICY",
                "freeformReason": "may contain customer text", "phone": "+919999999999",
            }),
        })
        self.assertIsNotNone(row)
        self.assertEqual(row["template_name"], "order_status")
        blob = json.dumps(row)
        self.assertNotIn("customer text", blob)
        self.assertNotIn("+919999999999", blob)
        self.assertNotIn("freeformReason", blob)

    def test_non_template_system_event_is_not_exported(self):
        self.assertIsNone(self.mod._template_lifecycle({"eventType": "flow_published"}))


if __name__ == "__main__":
    unittest.main()
