from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
CLIENT = ROOT / "src/api/client.ts"
UI = ROOT / "src/components/workspace/platform/WaGraphTools.tsx"


class WhatsAppMarketingPolicyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = HANDLER.read_text(encoding="utf-8")
        cls.client = CLIENT.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")

    def test_backend_accepts_only_meta_documented_policy_values(self):
        self.assertIn("'CLOUD_API_FALLBACK', 'STRICT'", self.handler)
        self.assertIn("payload['product_policy'] = product_policy", self.handler)

    def test_client_exposes_product_policy(self):
        self.assertIn("productPolicy?: 'CLOUD_API_FALLBACK' | 'STRICT'", self.client)

    def test_workspace_has_operator_policy_selector(self):
        self.assertIn('value="CLOUD_API_FALLBACK"', self.ui)
        self.assertIn('value="STRICT"', self.ui)
        self.assertIn('productPolicy }', self.ui)
