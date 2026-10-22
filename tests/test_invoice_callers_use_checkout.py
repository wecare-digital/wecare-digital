"""No active runtime may call the legacy invoice Lambda after commerce consolidation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CALLERS = (
    "amplify/functions/payments/razorpay-webhook/handler.py",
    "amplify/functions/core/service-api/handler.py",
    "amplify/functions/messaging/whatsapp-business-api/handler.py",
    "amplify/functions/messaging/whatsapp-business-api/flows/common.py",
    "amplify/functions/ai/ai-generate-response/handler.py",
)


def test_active_invoice_callers_target_checkout_commerce_runtime():
    for rel in ACTIVE_CALLERS:
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "FunctionName='wecare-invoice-engine" not in source, rel
        assert '"wecare-invoice-engine:live"' not in source, rel
        assert "'wecare-invoice-engine:live'" not in source, rel


def test_checkout_strangler_accepts_invoice_http_envelopes():
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(
        encoding="utf-8")
    block = source.split("def handler(", 1)[1].split("if event.get('internalAction')", 1)[0]
    assert 'commerce_path.startswith("/invoices")' in block
    assert "commerce_invoice_engine.handler(event, context)" in block


def test_runtime_deploy_publishes_checkout_before_invoice_callers():
    source = (ROOT / ".github/workflows/runtime-deploy.yml").read_text(encoding="utf-8")
    deploy = source.split("- name: Deploy selected runtime functions", 1)[1]
    deploy = deploy.split("- name: Verify live aliases serve latest code", 1)[0]
    checkout = deploy.index("wecare-checkout")
    for caller in (
        "wecare-ai-generate-response",
        "wecare-service-api",
        "wecare-whatsapp-business-api",
        "wecare-razorpay-webhook",
    ):
        assert checkout < deploy.index(caller), caller
