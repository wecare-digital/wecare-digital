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
    assert "No stage-specific timestamp recorded" in timeline
    assert "full" not in timeline.lower() or "full evidence" in timeline.lower()
    assert "<VaultMessageTimeline file={ row } journey={ journey } />" in logs
    assert "<VaultMessageTimeline file={ currentFile } journey={ props.journey } />" in preview
