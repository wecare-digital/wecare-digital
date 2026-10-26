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
        self.assertIn("_record_meta_system_event(", self.source)
        self.assertIn("record_system_event(", self.source)

    def test_meta_events_are_archived_for_analytics(self):
        self.assertIn("analytics/whatsapp/meta-events/date=", self.source)
        self.assertIn("ServerSideEncryption='AES256'", self.source)

    def test_history_is_structured_and_never_replayed_as_live_traffic(self):
        self.assertIn("def _process_history_event(", self.source)
        self.assertIn("'whatsapp_history_chunk'", self.source)
        self.assertIn("_AUDIT_ONLY_REPLAY_FIELDS", self.source)

    def test_partner_solution_changes_are_structured(self):
        self.assertIn("def _process_partner_solution_event(", self.source)
        self.assertIn("'whatsapp_partner_solution_change'", self.source)
