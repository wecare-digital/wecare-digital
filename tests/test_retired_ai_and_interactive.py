"""Regression guard for retiring the legacy AI and standalone WhatsApp interactive transport.

This suite is intentionally static: no production sends, AWS permissions or Meta
network access are required. Run: python -m unittest tests.test_retired_ai_and_interactive
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def source(path):
    return (ROOT / path).read_text(encoding="utf-8")

class LegacyRetirementTests(unittest.TestCase):
    def test_legacy_ai_implementation_and_ui_are_removed(self):
        for path in (
            "amplify/functions/ai/ai-generate-response/handler.py",
            "src/components/FloatingAgent.tsx",
            "src/components/dashboard/tabs/InternalChatTab.tsx",
            "src/components/InteractiveMessageComposer.tsx",
            "src/components/workspace/whatsapp/interactive-lists.tsx",
            "src/components/workspace/whatsapp/bot-menu.tsx",
            "scripts/provision_agent_approval_routes.py",
        ):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists(), path)
        client = source("src/api/client.ts")
        self.assertNotIn("/ai/generate", client)
        self.assertNotIn("sendWhatsAppInteractive", client)
        self.assertNotIn("generateAIResponse", client)

    def test_all_three_legacy_ai_routes_removed_from_inventory(self):
        routes = json.loads(source("_routes.json"))
        flattened = json.dumps(routes)
        for route in ("POST /ai/generate", "POST /ai/approvals",
                      "POST /ai/approvals/status"):
            self.assertNotIn(route + '"', flattened)

    def test_outbound_rejects_standalone_interactive_at_both_boundaries(self):
        code = source("amplify/functions/messaging/outbound-whatsapp/handler.py")
        self.assertIn("DIRECT_INTERACTIVE_RETIRED", code)
        self.assertIn("_outbound_payload.get('type') == 'interactive'", code)
        self.assertIn("body.get('isInteractive')", code)
        self.assertNotIn("def _handle_interactive_send(", code)
        self.assertNotIn("payload['type'] = 'interactive'", code)
        self.assertNotIn("'type': 'interactive'", code)
        # These are approved template sends; they must not be retired.
        self.assertIn("isCheckoutTemplate", code)
        self.assertIn("WA_PAY_TEMPLATE", code)
        self.assertIn("template_flow_button", code)
        self.assertIn("template_url_button", code)

    def test_inbound_menus_and_direct_flow_implementation_removed(self):
        code = source("amplify/functions/messaging/inbound-whatsapp-handler/handler.py")
        self.assertNotIn("WD_LISTS", code)
        self.assertNotIn("def _send_wd_list(", code)
        self.assertNotIn("'isInteractive': True", code)
        self.assertNotIn("'type': 'interactive'", code)
        self.assertIn("retired_list_reply", code)
        self.assertIn("DIRECT_INTERACTIVE_RETIRED", code)
        self.assertIn("def _send_menu_placeholder(", code)

    def test_calling_permission_prompt_removed(self):
        code = source("amplify/functions/messaging/whatsapp-calling/handler.py")
        self.assertIn("DIRECT_INTERACTIVE_RETIRED", code)
        self.assertNotIn("'type': 'interactive'", code)

if __name__ == "__main__":
    unittest.main()
