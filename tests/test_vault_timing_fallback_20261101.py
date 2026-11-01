"""Read-only regression contracts for Vault settings recovery and Meta ID preview.

These tests do not call AWS, access customer data, send WhatsApp, or charge money.
The actual authenticated settings GET/PUT and Meta approval require post-release QA.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class VaultTimingFallbackTests(unittest.TestCase):
    def test_missing_settings_read_remains_fail_closed_with_retry(self):
        ui = source("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        api = source("src/api/client.ts")
        self.assertIn("setCanSave( false )", ui)
        self.assertIn("result.failure.status", ui)
        self.assertIn("Retry settings read", ui)
        self.assertIn("setRetryRead( n => n + 1 )", ui)
        self.assertIn("if ( !result.ok )", ui)
        self.assertIn("setValue( configured || { ...DEFAULTS } )", ui)
        self.assertIn("getSystemConfigResult ( configKey: string )", api)
        self.assertIn("validVaultDelay( value.postReceiptAccessGapSeconds )", ui)
        self.assertIn("updateSystemConfig( CONFIG_KEY, value )", ui)

    def test_saved_journey_ids_are_read_only_and_name_matched(self):
        ui = source("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        preview = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        self.assertIn("parseVaultJourney( result.data.config )", ui)
        self.assertIn("getSystemConfigResult( 'vault_whatsapp_template_journey_v1' )", ui)
        self.assertIn("recorded?.templateName === expectedName", ui)
        self.assertIn("/^[0-9]{10,25}$/.test( recorded.templateId )", ui)
        self.assertIn("Service-pricing registry", ui)
        self.assertIn("Saved journey reference · verify with Meta", ui)
        self.assertIn("steps: steps.filter( step => step.role !== 'ready_offer' )", preview)
        self.assertNotIn("updateSystemConfig( 'vault_whatsapp_template_journey_v1'", ui)
        for name in (
            "wecare_whatapp_native_pay_template",
            "wecare_order_status_v3",
            "wecare_default_invoice_image_template",
            "wecare_default_download",
        ):
            self.assertIn(name, ui)

    def test_only_item_name_editor_moved_but_price_stays_locked(self):
        workbench = source("src/components/workspace/service/SecureFiles.tsx")
        preview = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        self.assertEqual(workbench.count('id="sf-vault-item-description"'), 1)
        self.assertNotIn('id="sf-vault-item-description"', preview)
        self.assertIn("VAULT_BASE_ITEM_PAISE = 4900", workbench)
        self.assertIn("maxLength={ 60 }", workbench)
        self.assertIn("focusInvalidDescription()", workbench)
        self.assertIn("props.breakdown?.totalPayablePaise", preview)


if __name__ == "__main__":
    unittest.main()
