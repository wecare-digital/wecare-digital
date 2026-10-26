from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
INBOUND = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"


class WhatsAppNewWebhookFieldCaptureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INBOUND.read_text(encoding="utf-8")

    def test_new_meta_system_fields_are_durably_captured(self):
        for field in (
            "automatic_events",
            "business_status_update",
            "tracking_events",
        ):
            self.assertIn(f"'{field}'", self.source)

    def test_system_events_use_existing_durable_store(self):
        self.assertIn("if field in _SYSTEM_EVENT_FIELDS:", self.source)
        self.assertIn("_store_system_event(field, value, request_id)", self.source)

    def test_history_remains_captured_for_coexistence_sync(self):
        self.assertIn("'history'", self.source)
