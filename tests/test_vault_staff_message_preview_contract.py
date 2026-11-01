"""Non-network regression checks for the staff Vault message preview.

These are source-contract checks; they do not replace Meta, AWS or handset QA.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "src/components/workspace/pay/PaymentTemplateMedia.tsx"
PREVIEW = ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx"
STAFF = ROOT / "src/components/workspace/service/SecureFiles.tsx"


class VaultPreviewContractTest(unittest.TestCase):
    def test_readonly_approved_media_references_are_exact(self):
        source = MEDIA.read_text(encoding="utf-8")
        self.assertIn(
            "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png",
            source,
        )
        self.assertIn(
            "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/"
            "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png",
            source,
        )
        self.assertIn('rel="noopener noreferrer"', source)
        self.assertIn("These links do not send WhatsApp or create payment", source)

    def test_payment_timing_is_explained_without_adding_fake_waits(self):
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("Verified capture → Processing", source)
        self.assertIn("No artificial wait", source)
        self.assertIn("Processing → Completed", source)
        self.assertIn("1s fixed · Vault only", source)
        self.assertIn("Completed → paid invoice", source)
        self.assertIn("0s added · required conditions still apply", source)
        self.assertIn("Paid invoice accepted → Access Vault", source)
        self.assertIn("Access delay (0–5s)", source)

    def test_meta_lookup_uses_readonly_registry_id_fallback(self):
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("paidTemplateRows.map(", source)
        self.assertIn("getTemplateDetails( item.id, '2094615664435155' )", source)
        self.assertIn("data?.name === item.name", source)
        self.assertIn("data.category === 'UTILITY'", source)

    def test_no_file_cannot_be_presented_as_paid_delivery(self):
        source = STAFF.read_text(encoding="utf-8")
        self.assertIn("no WhatsApp message, invoice or customer download", source)
        self.assertIn("No saved Vault file is available for this customer", source)
        preview = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("Payment, paid invoice and Access Vault cannot start", preview)


if __name__ == "__main__":
    unittest.main()
