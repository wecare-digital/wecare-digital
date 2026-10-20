"""Regression contract for customer transaction WhatsApp messaging."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

WABA1 = "2094615664435155"
PHONE1 = "1016149501586345"
OTP = "wecare_otp"
PAYMENT = "wecare_whatapp_native_pay_template"
INVOICE = "wecare_default_invoice_image_template"


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_transaction_template_allowlist():
    auth = _read("amplify/functions/auth/customer-whatsapp-auth/handler.py")
    engine = _read("amplify/functions/payments/invoice-engine/handler.py")
    webhook = _read("amplify/functions/payments/razorpay-webhook/handler.py")

    assert OTP in auth
    assert PAYMENT in engine
    assert INVOICE in engine
    for forbidden in ("postpay_request_v1", "wecare_leave_review", "isInteractive"):
        assert forbidden not in webhook


def test_otp_manifest_has_only_waba1_sender():
    manifest = json.loads(_read("config/lambda-env-manifest.json"))["functions"]
    otp = manifest["wecare-customer-whatsapp-auth"]
    routes = json.loads(otp["OTP_WABA_MAP"])

    assert set(routes) == {WABA1}
    assert routes[WABA1]["phone_number_id"] == PHONE1
    assert routes[WABA1]["template_name"] == OTP


def test_webhook_has_no_extra_post_payment_template_configuration():
    webhook = json.loads(_read("config/lambda-env-manifest.json"))["functions"]["wecare-razorpay-webhook"]
    assert "POST_PAYMENT_FLOW_WABA1" not in webhook
    assert "POST_PAYMENT_FLOW_WABA2" not in webhook
    assert "POST_PAYMENT_REQUEST_TEMPLATE" not in webhook
    assert "WA_REVIEW_TEMPLATE" not in webhook
