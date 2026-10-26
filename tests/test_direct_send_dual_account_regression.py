import importlib.util
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIRECT_SEND_PATH = ROOT / "amplify/functions/shared/lambda_utils/direct_send.py"
OUTBOUND_PATH = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"
ENV_MANIFEST_PATH = ROOT / "config/lambda-env-manifest.json"

PRIMARY_PHONE_ID = "1016149501586345"
SECONDARY_PHONE_ID = "1055232054343117"
PRIMARY_ACCOUNT_ID = "2094615664435155"
SECONDARY_ACCOUNT_ID = "2513394156072604"
ENABLED_BOTH = f"{PRIMARY_ACCOUNT_ID},{SECONDARY_ACCOUNT_ID}"
PRODUCTION_ENABLED = ""


def _load_direct_send():
    spec = importlib.util.spec_from_file_location("direct_send_under_test", DIRECT_SEND_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class DirectSendDualAccountRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.direct_send = _load_direct_send()
        cls.outbound_source = OUTBOUND_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(ENV_MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_registered_phone_mappings_are_exact(self):
        self.assertEqual(
            self.direct_send.META_PHONE_TO_WABA,
            {
                PRIMARY_PHONE_ID: PRIMARY_ACCOUNT_ID,
                SECONDARY_PHONE_ID: SECONDARY_ACCOUNT_ID,
            },
        )
        self.assertEqual(self.direct_send.waba_for_meta_phone(PRIMARY_PHONE_ID), PRIMARY_ACCOUNT_ID)
        self.assertEqual(self.direct_send.waba_for_meta_phone(SECONDARY_PHONE_ID), SECONDARY_ACCOUNT_ID)

    def test_unknown_phone_fails_closed(self):
        self.assertEqual(self.direct_send.waba_for_meta_phone("598491183351723"), "")
        self.assertEqual(self.direct_send.waba_for_meta_phone("unknown"), "")
        self.assertEqual(self.direct_send.waba_for_meta_phone(None), "")

    def test_both_accounts_enable_independently(self):
        with patch.dict(os.environ, {"DIRECT_SEND_ENABLED_WABAS": ENABLED_BOTH}, clear=False):
            self.assertTrue(self.direct_send.enabled_for_waba(PRIMARY_ACCOUNT_ID))
            self.assertTrue(self.direct_send.enabled_for_waba(SECONDARY_ACCOUNT_ID))
            self.assertFalse(self.direct_send.enabled_for_waba("9999999999999999"))

    def test_empty_flag_disables_every_account(self):
        with patch.dict(os.environ, {"DIRECT_SEND_ENABLED_WABAS": ""}, clear=False):
            self.assertFalse(self.direct_send.enabled_for_waba(PRIMARY_ACCOUNT_ID))
            self.assertFalse(self.direct_send.enabled_for_waba(SECONDARY_ACCOUNT_ID))

    def test_outbound_utility_category_is_gated_by_account_allowlist(self):
        source = self.outbound_source
        gate = "elif direct_send.enabled_for_waba(direct_send_waba):"
        assignment = "direct_send_category = 'utility'"
        self.assertIn(gate, source)
        self.assertIn(assignment, source)
        self.assertLess(source.index(gate), source.index(assignment))

    def test_category_is_only_added_when_direct_send_category_exists(self):
        source = self.outbound_source
        self.assertIn("if direct_send_category:", source)
        self.assertIn("payload['category'] = direct_send_category", source)

    def test_admin_direct_send_uses_same_fail_closed_account_gate(self):
        admin_source = (
            ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "direct_send_waba = direct_send_util.waba_for_meta_phone(phone_id)",
            admin_source,
        )
        self.assertIn(
            "if not direct_send_util.enabled_for_waba(direct_send_waba):",
            admin_source,
        )
        self.assertIn("return _resp(403", admin_source)

    def test_live_env_manifest_fails_closed_until_meta_onboarding(self):
        functions = self.manifest["functions"]
        for function_name in ("wecare-outbound-whatsapp", "wecare-whatsapp-business-api"):
            self.assertEqual(
                functions[function_name]["DIRECT_SEND_ENABLED_WABAS"],
                PRODUCTION_ENABLED,
                function_name,
            )
