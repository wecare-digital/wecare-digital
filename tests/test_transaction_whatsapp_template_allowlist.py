"""Hard contract for customer transaction WhatsApp messaging.

The purchase/money path has exactly three customer-facing templates, all from
WECARE.DIGITAL WABA1. Interactive/Flow messages and extra post-payment templates
must not re-enter this chain.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"

WABA1_ID = "2094615664435155"
WABA1_PHONE_ID = "1016149501586345"

OTP = "wecare_otp"
PAYMENT = "wecare_whatapp_native_pay_template"
INVOICE = "wecare_default_invoice_image_template"
ALLOWED = {OTP, PAYMENT, INVOICE}


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_transaction_templates_are_exactly_the_owner_allowlist():
    auth = _text("amplify/functions/auth/customer-whatsapp-auth/handler.py")
    registration = _text("amplify/functions/auth/customer-registration/handler.py")
    invoice = _text("amplify/functions/payments/invoice-engine/handler.py")
    webhook = _text("amplify/functions/payments/razorpay-webhook/handler.py")

    assert OTP in auth and OTP in registration
    assert PAYMENT in invoice
    assert INVOICE in invoice

    forbidden = {
        "postpay_request_v1",
        "wecare_leave_review",
    }
    for name in forbidden:
        assert name not in webhook


def test_transaction_chain_has_no_interactive_or_flow_send_after_capture():
    webhook = _text("amplify/functions/payments/razorpay-webhook/handler.py")
    assert "'isInteractive': True" not in webhook
    assert '"isInteractive": True' not in webhook
    assert "interactiveType" not in webhook
    assert "_trigger_post_payment_flow" not in webhook
    assert "_request_review_on_whatsapp" not in webhook


def test_otp_is_hard_pinned_to_waba1_only():
    auth = _text("amplify/functions/auth/customer-whatsapp-auth/handler.py")
    manifest = _text("config/lambda-env-manifest.json")
    assert f'PRIMARY_WABA_ID = "{WABA1_ID}"' in auth
    assert f'PRIMARY_PHONE_NUMBER_ID = "{WABA1_PHONE_ID}"' in auth
    assert "2513394156072604" not in manifest.split('"wecare-customer-whatsapp-auth"', 1)[1].split("},", 1)[0]


def test_payment_sender_is_waba1_only():
    payment = _text("amplify/functions/shared/lambda_utils/ecommerce/wa_payment_request.py")
    assert "PAYMENT_SENDERS = frozenset({PHONE_NUMBER_ID_1})" in payment
    assert "phone-number-id-waba1-direct-1016149501586345" in payment
