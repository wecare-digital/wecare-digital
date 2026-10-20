"""Paid orders expose review exactly once: through the invoice template Flow button."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SENDERS = [
    ROOT / "amplify/functions/payments/razorpay-webhook/handler.py",
    ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py",
    ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py",
]


def test_no_standalone_review_template_sender_remains():
    for path in ACTIVE_SENDERS:
        source = path.read_text(encoding="utf-8")
        assert "wecare_leave_review" not in source, path
        assert "WA_REVIEW_TEMPLATE" not in source, path


def test_invoice_template_is_the_single_review_entrypoint():
    source = (ROOT / "amplify/functions/payments/invoice-engine/handler.py").read_text(
        encoding="utf-8")
    assert "wecare_default_invoice_image_template" in source
    assert "'flowButton': {'index': 0, 'flowKey': 'leave_review'}" in source


def test_legacy_review_actions_are_safe_noop_sinks():
    source = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text(
        encoding="utf-8")
    assert "'serviceReview'" in source
    assert "'vaultReview'" in source
    assert "REVIEW_INCLUDED_IN_INVOICE_TEMPLATE" in source
    assert "from flows.paid_vault import send_review" not in source
    assert "from flows.paid_submit_request import send_review" not in source
