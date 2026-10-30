"""Vault message sequencing and UI audit must not invent delivery evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vault_delivery_order_and_spacing_are_bounded_and_guarded():
    webhook = source("amplify/functions/payments/razorpay-webhook/handler.py")
    paid = source("amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py")
    assert "_VAULT_STATUS_GAP_SECONDS = 2" in webhook
    assert "if not (processing_status == 200 or processing_code == 'ORDER_STATUS_UNCHANGED'):" in webhook
    assert "if vault_spacing and processing_status == 200:" in webhook
    assert "if vault_spacing and completed_status == 200:" in webhook
    assert "_POST_RECEIPT_ACCESS_GAP_SECONDS = 4" in paid
    assert "if not delivered_before:" in paid
    assert "time.sleep(_POST_RECEIPT_ACCESS_GAP_SECONDS)" in paid
    assert "if not _send_once(requests, row, 'vaultNotificationStatus'" in paid
    assert "if not _send_once(requests, row, 'vaultDocumentStatus'" in paid
    assert "status = 'ACCEPTED' if whatsapp_message_id else 'SEND_UNKNOWN'" in paid
    assert "whatsapp_message_id" in paid
    assert "grant_access" in paid


def test_staff_offers_require_approval_and_safe_idempotency():
    ui = source("src/components/workspace/service/SecureFiles.tsx")
    secure = source("amplify/functions/core/secure-files/handler.py")
    catalog = source("amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py")
    upload = ui.split("const handleUpload = async () => {", 1)[1].split("const handleRevoke", 1)[0]
    assert "sendSecureFileOffer" not in upload
    assert "sendOfferAfterUpload" not in ui
    assert "Send Unlock Vault on WhatsApp?" in ui
    assert "if ( !approved ) return;" in ui
    assert "validOfferBodyText" in ui
    assert "vaultPricePaise !== 4900" in ui
    assert '"lastOfferMessageId"' in secure
    assert "whatsappMessageId" in catalog
    assert "OFFER_RESEND_GUARD_SECONDS" in catalog
    assert "idempotencyKey='vault-offer:' + token" in catalog


def test_five_stage_logs_show_timestamps_and_do_not_fake_delivery():
    timeline = source("src/components/workspace/service/VaultMessageTimeline.tsx")
    logs = source("src/components/workspace/service/VaultLogs.tsx")
    preview = source("src/components/workspace/service/VaultJourneyPreview.tsx")
    assert "const TITLE = [ 'Unlock Vault offer', 'Review & Pay', 'Order updates ×2', 'Paid invoice', 'Access Vault' ]" in timeline
    assert "timeZone: 'Asia/Kolkata'" in timeline
    assert "lastOfferRequestedAt" in timeline
    assert "lastAccessSentAt" in timeline
    assert "Meta accepted" in timeline
    assert "does not mean delivered or read" in timeline
    assert "log?.evidence.completed?.observedAt" in timeline
    assert "log?.evidence.processing?.observedAt" in timeline
    assert "log?.evidence.invoice?.observedAt" in timeline
    assert "Processing" in timeline and "Completed" in timeline
    assert "readVaultMessageDeliveryLog" in timeline
    assert "providerStatus" in timeline
    assert "READ" in timeline and "DELIVERED" in timeline and "FAILED" in timeline
    assert "full" not in timeline.lower() or "full evidence" in timeline.lower()
    assert "<VaultMessageTimeline file={ row } journey={ journey } />" in logs
    assert "<VaultMessageTimeline file={ currentFile } journey={ props.journey } />" in preview


def test_message_delivery_status_lookup_is_staff_scoped_and_provider_id_bound():
    handler = source("amplify/functions/core/secure-files/handler.py")
    provisioner = source("scripts/provision_secure_files_api.py")
    client = source("src/api/client.ts")
    assert 'tail[1] == "message-log" and method == "GET"' in handler
    assert handler.index('denied = require_auth(event, "Operator")') < handler.index('tail[1] == "message-log" and method == "GET"')
    message_log = handler.split('def _admin_message_log(', 1)[1].split('def _admin_revoke(', 1)[0]
    assert 'item = _table(FILES_TABLE).get_item(' in message_log
    assert '"UNKNOWN_FILE"' in message_log
    assert 'str(item.get("lastOfferMessageId") or "")' in handler
    assert 'out["lastOfferMessageId"]' not in handler
    assert 'out["lastAccessMessageId"]' not in handler
    assert 'str(item.get("lastAccessMessageId") or "")' in handler
    assert 'IndexName="whatsappMessageId-index"' in handler
    assert 'Limit=3' in handler
    assert 'row.get("direction")' in handler
    assert 'otherStages": "NO_GUESSED_WAMIDS_OR_DELIVERY"' in handler
    assert 'def _verified_vault_payment_evidence(' in handler
    assert 'entitlement.get("recordType") == "VAULT_ENTITLEMENT"' in handler
    assert 'grant.get("entitlementId") == entitlement_id' in handler
    assert 'row.get("referenceId") == ref' in handler
    assert 'IndexName="paymentReferenceId-index"' in handler
    assert 'IndexName="referenceId-index"' in handler
    assert 'ConsistentRead=True' in handler
    assert 'Limit=30' in handler
    assert '"Sid": "ReadPaidVaultJourneyLogs"' in provisioner
    assert '"Sid": "ReadNativeVaultPaymentSendId"' in provisioner
    assert "nativePay?: VaultMessageDeliveryEvidence" in client
    assert "processing?: VaultMessageDeliveryEvidence" in client
    assert "completed?: VaultMessageDeliveryEvidence" in client
    assert "invoice?: VaultMessageDeliveryEvidence" in client
    assert '("GET", "/secure-files/{fileId}/message-log")' in provisioner
    assert '"Sid": "ReadVerifiedWhatsAppMessageStatus"' in provisioner
    assert '"Action": ["dynamodb:Query"]' in provisioner
    assert "readVaultMessageDeliveryLog" in client
    assert "query(" in handler and "scan(" in handler  # legacy file listings only
    assert "scan(**" not in handler.split('def _message_status_for_verified_send', 1)[1].split('def _admin_message_log', 1)[0]


def test_customer_scope_replaces_stale_result_and_send_modal_is_single_flight():
    ui = source("src/components/workspace/service/SecureFiles.tsx")
    assert "latestFilesRead = useRef( 0 )" in ui
    assert "readId !== latestFilesRead.current" in ui
    assert "clearFileSelection();" in ui
    assert "setFiles( [] );" in ui
    assert "sendingAction.current = true" in ui
    assert "sendingAction.current = false" in ui
    assert "Send Unlock Vault now" in ui
    assert "Resend Unlock Vault" in ui
    assert "Send Unlock Vault on WhatsApp?" in ui
    assert "Save & publish to Vault" in ui
