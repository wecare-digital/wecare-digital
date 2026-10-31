"""Fail-closed source contracts for the Vault -> Pay & Flow transition.

Offline only: no AWS credentials, customer data, money movement or WhatsApp sends.
The integration/runtime tests must still run before any production deployment.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class VaultPayFlowMigrationTests(unittest.TestCase):
    def test_vault_has_one_staff_payment_rail_and_no_offer_ui(self):
        workbench = source("src/components/workspace/service/SecureFiles.tsx")
        documents = source("src/components/workspace/service/Documents.tsx")
        self.assertIn("api.requestSecureFilePayment(", workbench)
        self.assertIn("api.requestSecureFilePayment(", documents)
        self.assertNotIn("api.sendSecureFileOffer(", workbench)
        self.assertNotIn("api.sendSecureFileOffer(", documents)
        self.assertNotIn("setScheduledAction( 'offer' )", workbench)
        self.assertNotIn("Send Unlock Vault now", workbench)
        self.assertNotIn("WhatsApp Unlock Vault · body", workbench)

    def test_pay_flow_owns_vault_tab_and_legacy_service_route(self):
        payments = source("src/pages/workspace/payments/index.tsx")
        service = source("src/pages/workspace/service/index.tsx")
        self.assertIn("{ id: 'vault', label: 'Vault · Review & Pay' }", payments)
        self.assertIn("{ id: 'timing', label: 'Delivery timing' }", payments)
        self.assertIn("view=vault", service)
        self.assertIn("router.replace(destination)", service)
        self.assertIn("view !== 'vault'", service)
        nav = source("src/config/navigation.ts")
        self.assertIn("label: 'Pay & Flow'", nav)

    def test_vault_invoice_amount_is_server_locked(self):
        ui = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        self.assertIn("read-only", ui)
        self.assertIn("props.breakdown?.totalPayablePaise", ui)
        self.assertIn("props.pricePaise", ui)
        self.assertNotIn("priceMismatch", ui)
        self.assertNotIn("₹49 offer", ui)
        backend = source("amplify/functions/core/secure-files/handler.py")
        self.assertIn('"action": "sendPayment"', backend)
        self.assertIn("if not _vault_file_storage_ready(item):", backend)

    def test_retired_offer_has_no_new_send_route_but_old_taps_survive(self):
        secure = source("amplify/functions/core/secure-files/handler.py")
        catalog = source("amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py")
        routes = source("scripts/provision_secure_files_api.py")
        self.assertIn('"VAULT_OFFER_RETIRED"', secure)
        self.assertIn("'VAULT_OFFER_RETIRED'", catalog)
        self.assertIn('"POST /secure-files/{fileId}/send-offer"', routes)
        self.assertIn("RETIRED_ROUTES", routes)
        self.assertIn("'unlock'", catalog)
        self.assertIn('VAULT_SCHEDULE_ACTIONS = {"payment", "access"}', secure)

    def test_messaging_preview_excludes_removed_template(self):
        preview = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        timeline = source("src/components/workspace/service/VaultMessageTimeline.tsx")
        self.assertIn("step.role !== 'ready_offer'", preview)
        self.assertNotIn("Unlock Vault offer", timeline)
        self.assertIn("Four-stage Vault payment and access", timeline)

    def test_bounded_timing_has_backend_validation_and_payment_gates(self):
        editor = source("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        ai_config = source("amplify/functions/ai/ai-config-management/handler.py")
        webhook = source("amplify/functions/payments/razorpay-webhook/handler.py")
        access = source("amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py")
        for text in (editor, ai_config, webhook, access):
            self.assertIn("vault_delivery_timing_v1", text)
        self.assertIn("value <= 5", editor)
        self.assertIn("proposed[key] > 5", ai_config)
        self.assertIn("0 <= value <= 5", webhook)
        self.assertIn("0 <= gap <= 5", access)
        self.assertIn("_is_paid_vault_checkout(reference_id)", webhook)
        self.assertIn("vaultNotificationStatus", access)

    def test_media_endpoint_is_fixed_and_staff_only(self):
        handler = source("amplify/functions/core/secure-files/handler.py")
        self.assertIn('tail == ["payment-media-preview"]', handler)
        self.assertIn("require_auth(event, \"Operator\")", handler)
        self.assertIn('ExpiresIn=60', handler)
        self.assertIn("template_media.RETAINED_MEDIA_KEYS", handler)
        self.assertIn('"headerPreviewUrl"', handler)
        self.assertIn('"itemPreviewUrl"', handler)
        self.assertNotIn('event.get("s3Key")', handler.split("def _admin_payment_media_preview")[1].split("def _admin_request_payment")[0])
        frontend = source("src/components/workspace/pay/PaymentTemplateMedia.tsx")
        self.assertIn("getVaultPaymentMediaPreview()", frontend)
        self.assertIn("X-Amz-Signature", frontend)

    def test_no_prepaid_invoice_send_from_vault_workbench(self):
        workbench = source("src/components/workspace/service/SecureFiles.tsx")
        self.assertNotIn("createInvoiceEngine", workbench)
        self.assertNotIn("sendPaymentLinkResult", workbench)
        self.assertIn("requestSecureFilePayment", workbench)
        # Accepted capture governs the canonical renderer and Access Vault.
        lifecycle = source("docs/operations/service-specific-post-payment-journeys-20261031.md")
        self.assertIn("after the invoice's accepted send", lifecycle.lower())


if __name__ == "__main__":
    unittest.main()
