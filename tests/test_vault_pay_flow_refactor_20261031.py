"""Fail-closed source contracts for the Vault -> Pay & Flow transition.

Offline only: no AWS credentials, customer data, money movement or WhatsApp sends.
The integration/runtime tests must still run before any production deployment.
"""

from pathlib import Path
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
        self.assertIn("{ id: 'timing', label: 'Access delay' }", payments)
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

    def test_only_access_delay_is_editable_and_status_messages_have_no_sleep(self):
        editor = source("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        ai_config = source("amplify/functions/ai/ai-config-management/handler.py")
        webhook = source("amplify/functions/payments/razorpay-webhook/handler.py")
        access = source("amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py")
        for text in (editor, ai_config, access):
            self.assertIn("vault_delivery_timing_v1", text)
            self.assertIn("postReceiptAccessGapSeconds", text)
        self.assertNotIn("vault_delivery_timing_v1", webhook)
        self.assertIn("value <= 5", editor)
        self.assertIn("required = {'postReceiptAccessGapSeconds'}", ai_config)
        self.assertNotIn("required = {'orderStatusGapSeconds',", ai_config)
        self.assertIn("not 0 <= proposed['postReceiptAccessGapSeconds'] <= 5", ai_config)
        self.assertIn("0 <= gap <= 5", access)
        self.assertIn("_post_receipt_access_gap_seconds()", access)
        self.assertIn("vaultNotificationStatus", access)
        self.assertNotIn("_vault_status_gap_seconds", webhook)
        self.assertNotIn("_VAULT_STATUS_GAP_SECONDS", webhook)
        fulfilment = webhook.split("def _start_native_fulfilment(")[1].split(
            "_FULFILMENT_INVOKE_READ_TIMEOUT_SECONDS", 1
        )[0]
        self.assertIn("invoice_id, 'processing'", fulfilment)
        self.assertIn("invoice_id, 'completed'", fulfilment)
        # Exactly one fixed second for Vault after accepted Processing,
        # never an additional wait before paid invoice or for other services.
        self.assertIn("if processing_status == 200 and _is_paid_vault_checkout(reference_id):", fulfilment)
        self.assertEqual(fulfilment.count("time.sleep(1)"), 1)
        self.assertEqual(fulfilment.count("time.sleep("), 1)
        self.assertNotIn(
            "time.sleep(", fulfilment.split("invoice_id, 'completed'", 1)[1]
        )
        preview = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        timeline = source("src/components/workspace/service/VaultMessageTimeline.tsx")
        self.assertIn("Fixed 1s", preview)
        self.assertIn("1s Processing", timeline)
        self.assertNotIn("record.defaultDelaySeconds", timeline)

    def test_approved_meta_ids_and_dynamic_download_url(self):
        templates = source("amplify/functions/shared/lambda_utils/whatsapp_templates.py")
        for template_id in (
            "2714938845570815",  # native Review & Pay
            "1754227779211208",  # Processing and Completed
            "1782246473079550",  # invoice image
            "1410998911012572",  # Access Vault
        ):
            self.assertIn(template_id, templates)
        ui = source("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        self.assertIn("templates?.templateIds?.nativePay", ui)
        self.assertIn("templates?.templateIds?.orderStatus", ui)
        self.assertIn("templates?.templateIds?.receipt", ui)
        self.assertIn("templates?.templateIds?.delivery", ui)
        self.assertIn("https://wecare.digital/vault/?file={{1}}", ui)

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

    def test_single_49_vault_invoice_description_only_is_staff_editable(self):
        ui = source("src/components/workspace/service/VaultJourneyPreview.tsx")
        workbench = source("src/components/workspace/service/SecureFiles.tsx")
        service = source("amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py")
        checkout = source("amplify/functions/ecommerce/checkout/handler.py")
        webhook = source("amplify/functions/payments/razorpay-webhook/handler.py")
        secure = source("amplify/functions/core/secure-files/handler.py")
        catalog = source("amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py")
        invoice = source("amplify/functions/payments/invoice-engine/handler.py")
        self.assertIn("pricePaise === 4900", ui)
        self.assertIn('id="sf-vault-item-description"', ui)
        self.assertIn("onPaymentItemDescriptionChange", ui)
        self.assertIn("props.breakdown?.totalPayablePaise", ui)
        self.assertIn("vaultPricePaise === VAULT_BASE_ITEM_PAISE", workbench)
        self.assertIn("VAULT_EDITABLE_ITEM_PAISE = 4900", service)
        self.assertIn("VAULT_ITEM_DESCRIPTION_DEFAULT = 'Vault Access", service)
        self.assertIn("len(lines) == 1 and quantity == 1", service)
        self.assertIn("is_single_49_vault", checkout)
        self.assertIn('requested != VAULT_ITEM_DESCRIPTION_DEFAULT and not is_single_49_vault', checkout)
        self.assertIn('attempt["invoiceLines"] = invoice_lines', checkout)
        self.assertIn('attempt["vaultItemDescription"] = label', checkout)
        self.assertIn("vaultItemDescription", webhook)
        self.assertIn("inclusiveItemization", invoice)
        self.assertIn("paymentItemDescription", catalog)
        self.assertIn("_vault_offer_catalog_price_valid()", secure)
        staff = secure.split("def _admin_request_payment(")[1].split("def _admin_send_access(")[0]
        customer = secure.split("def _customer_request_payment(")[1].split("def _admin_send_vault_offer(")[0]
        self.assertIn('description = body.get(', staff)
        self.assertNotIn('paymentItemDescription', customer)
        self.assertNotIn('payment_description=description', customer)

    def test_missing_or_inactive_vault_link_uses_404_home_without_payment(self):
        page = source("src/pages/vault.tsx")
        get = source("src/components/get/GetPage.tsx")
        not_found = source("src/pages/404.tsx")
        self.assertIn("router.replace( '/404' )", page)
        self.assertIn("window.location.replace( '/404' )", get)
        self.assertIn("file.status === 'active'", get)
        self.assertIn("router.replace( '/' )", not_found)
        self.assertIn("targetFileId", get)
        self.assertIn("redirectToAuth()", get)
        self.assertIn("result.failure.status === 401", get)

    def test_no_usable_file_or_expired_whatsapp_purchase_single_new_request_reply(self):
        catalog = source("amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py")
        self.assertIn("SUBMIT_NEW_REQUEST_MESSAGE", catalog)
        self.assertIn("Submit a New Request: open https://wecare.digital/orders/", catalog)
        self.assertIn("if state in ('UNPAID', 'OPEN', 'READY'):", catalog)
        self.assertIn("_send(client, row, content=SUBMIT_NEW_REQUEST_MESSAGE)", catalog)
        self.assertIn("return {'outcome': 'VAULT_FILE_NOT_READY'}", catalog)
        self.assertIn("if state != 'UNPAID':", catalog)
        self.assertIn("return _send_access(client, row, file['fileId'])", catalog)

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
