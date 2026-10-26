from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIZ = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
WABA = ROOT / "amplify/functions/messaging/waba-management/handler.py"
INBOUND = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"
COMPOSER = ROOT / "src/components/ProductMessageComposer.tsx"


class WhatsAppAuditCloseoutContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.biz = BIZ.read_text(encoding="utf-8")
        cls.waba = WABA.read_text(encoding="utf-8")
        cls.inbound = INBOUND.read_text(encoding="utf-8")
        cls.composer = COMPOSER.read_text(encoding="utf-8")

    def test_product_carousel_matches_current_meta_contract(self):
        self.assertIn("_PRODUCT_CAROUSEL_TYPE = 'carousel'", self.biz)
        self.assertIn("'action': {'cards': built_cards}", self.biz)
        self.assertIn("'card_index': i", self.biz)
        self.assertIn("'catalog_id': str(catalog_id)", self.biz)
        self.assertNotIn("product_carousel_items", self.biz)
        self.assertNotIn("'type': 'product_carousel'", self.biz)
        self.assertIn("header, footer and buttons are not allowed", self.biz)
        self.assertNotIn("headerText: headerText || undefined", self.composer)

    def test_two_step_pin_is_admin_route_and_never_persisted(self):
        self.assertIn("elif '/two-step-pin' in path:", self.waba)
        self.assertIn("def _set_two_step_pin", self.waba)
        self.assertIn("len(pin) != 6 or not pin.isdigit()", self.waba)
        self.assertIn("payload={'pin': pin}", self.waba)
        self.assertIn("action='phone.two_step_pin_set'", self.waba)
        self.assertNotIn("'metaPhoneId': meta_phone_id, 'pin': pin", self.waba)

    def test_manisha_waba_reports_shared_wecare_app(self):
        self.assertIn("WECARE_META_APP_ID = os.environ.get('WECARE_META_APP_ID', '2238810740192680')", self.waba)
        self.assertIn("'2513394156072604': {", self.waba)
        self.assertIn("'businessId': '125951953587391'", self.waba)
        self.assertIn("'businessName': 'Manish Agarwal'", self.waba)
        self.assertIn("'integrationMode': 'SHARED'", self.waba)
        self.assertIn("'integrationStatus': 'CONNECTED'", self.waba)
        self.assertIn("'developerAppConnected': True", self.waba)

    def test_history_replay_never_enters_live_message_loop(self):
        self.assertIn("_AUDIT_ONLY_REPLAY_FIELDS = _COEXISTENCE_FIELDS | {'history'}", self.inbound)
        self.assertIn("_inbound_messages = [] if _coexistence_change", self.inbound)
        self.assertIn("def _ingest_replay_message", self.inbound)
        self.assertIn("whatsappMessageId-index", self.inbound)
        self.assertIn("replayOnly=True", self.inbound)
        self.assertNotIn("coexistence_ingest_requested_but_absent", self.inbound)


if __name__ == "__main__":
    unittest.main()
