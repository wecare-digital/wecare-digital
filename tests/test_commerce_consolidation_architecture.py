"""Source-level invariants for the staged commerce/WhatsApp consolidation.

These are intentionally cheap/static. The full Python suite supplies behavioural coverage; this
file keeps the architectural cut lines from silently regressing while live route migration is
staged.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_secure_files_no_longer_owns_a_payment_builder():
    delivery = source("amplify/functions/core/secure-files/whatsapp_delivery.py")
    handler = source("amplify/functions/core/secure-files/handler.py")
    assert "def send_payment_request" not in delivery
    assert "def reference_id" not in delivery
    assert "CHECKOUT_REQUIRED" in handler
    block = handler.split("def _send_whatsapp_payment", 1)[1].split("\ndef ", 1)[0]
    assert "send_payment_request(" not in block
    assert "checkoutOrderDetails" not in block


def test_verified_payment_sequence_is_order_status_then_invoice():
    webhook = source("amplify/functions/payments/razorpay-webhook/handler.py")
    assert "def _send_processing_order_status" in webhook
    paid = webhook.split("if verified_paid:", 1)[1]
    assert paid.index("_send_processing_order_status(") < paid.index("_post_payment_handler(")


def test_fulfilment_status_is_separate_from_invoice_delivery():
    invoice = source("amplify/functions/payments/invoice-engine/handler.py")
    body = invoice.split("def send_order_status", 1)[1].split("\ndef ", 1)[0]
    assert "isOrderStatus" in body
    assert "send_invoice_whatsapp(" not in body


def test_outbound_supports_meta_order_status_again():
    outbound = source("amplify/functions/messaging/outbound-whatsapp/handler.py")
    assert "def _handle_order_status_send" in outbound
    assert "ORDER_STATUS_INVOICE_TEMPLATE_ONLY" not in outbound
    assert "WA_ORDER_STATUS_TEMPLATE" in outbound


def test_template_management_is_ready_to_absorb_legacy_routes():
    templates = source(
        "amplify/functions/messaging/whatsapp-template-management/handler.py")
    assert "def _places_autocomplete" in templates
    assert "def _place_details" in templates
    assert "Repeated template pagination cursor" in templates
    assert "fixedHeaderMedia" in templates


def test_runtime_deploy_covers_consolidated_runtimes():
    workflow = source(".github/workflows/runtime-deploy.yml")
    for name in (
        "wecare-secure-files",
        "wecare-whatsapp-template-management",
        "wecare-outbound-whatsapp",
        "wecare-razorpay-webhook",
        "wecare-invoice-engine",
    ):
        assert name in workflow
