from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIZ = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text(encoding="utf-8")
CHECKOUT = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "src/api/client.ts").read_text(encoding="utf-8")
PROFILE = (ROOT / "src/components/workspace/whatsapp/business-profile.tsx").read_text(encoding="utf-8")
MIGRATION = (ROOT / "src/components/workspace/whatsapp/migration.tsx").read_text(encoding="utf-8")


class WhatsAppRemainingSafeContracts(unittest.TestCase):
    def test_flow_encryption_status_is_read_only_and_redacted(self):
        self.assertIn("def _get_flow_encryption_status", BIZ)
        self.assertIn("/whatsapp_business_encryption", BIZ)
        self.assertIn("'configured': bool(result.get('business_public_key'))", BIZ)
        self.assertIn("'signatureStatus': result.get('business_public_key_signature_status')", BIZ)
        self.assertIn("'/flow-encryption-status' in path", BIZ)
        self.assertIn("return _resp(405, {'error': 'GET only'})", BIZ)

    def test_preverified_inventory_is_read_only(self):
        self.assertIn("def _list_preverified_numbers", BIZ)
        self.assertIn("/preverified_numbers", BIZ)
        self.assertIn("'/preverified-numbers' in path", BIZ)
        self.assertIn("Read-only Meta inventory", MIGRATION)
        self.assertIn("listWhatsAppPreverifiedNumbers", CLIENT)

    def test_profile_surfaces_live_username_and_flow_crypto_readiness(self):
        self.assertIn("getBusinessUsername( phone.metaId )", PROFILE)
        self.assertIn("getWhatsAppFlowEncryptionStatus( phone.metaId )", PROFILE)
        self.assertIn("Username Status:", PROFILE)
        self.assertIn("Flow Encryption:", PROFILE)

    def test_primary_flow_encryption_binding_is_internal_and_scoped(self):
        self.assertIn("internalAction') == 'ensurePrimaryFlowEncryption'", BIZ)
        self.assertIn("if phone_id != PHONE1_META_ID", BIZ)
        self.assertIn("Content-Type': 'application/x-www-form-urlencoded'", BIZ)
        self.assertIn("FLOW_ENCRYPTION_BINDING_NOT_APPROVED_FOR_PHONE", BIZ)
        self.assertIn("private_key.public_key().public_bytes", BIZ)
        self.assertNotIn("'publicKey': public_pem", BIZ)

    def test_checkout_no_longer_claims_retired_initiation_gate(self):
        header = CHECKOUT.split('"""', 2)[1]
        self.assertIn("Initiation is live but provider-readiness gated", header)
        self.assertIn("historical `CHECKOUT_INITIATION_ENABLED` switch is retired", header)
        self.assertNotIn("Initiation is disabled by default", header)
        self.assertNotIn("gate off, the default", header)


if __name__ == "__main__":
    unittest.main()
