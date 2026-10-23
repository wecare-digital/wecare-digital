from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAID = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py"
OUTBOUND = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"
ROUTE = ROOT / "scripts/provision_invoice_order_status_route.py"


def test_paid_submit_request_uses_the_one_flow_completion_writer():
    source = PAID.read_text(encoding="utf-8")
    assert "flow_completion.claim_completion(" in source
    assert "table.put_item(" not in source


def test_paid_submit_request_sends_no_post_payment_interactive_flow():
    source = PAID.read_text(encoding="utf-8")
    assert "'isInteractive': True" not in source
    assert '"isInteractive": True' not in source
    assert "Payment received. Complete the details" not in source
    assert "SERVICE_ACTIVATED_NO_POSTPAY_FLOW" in source


def test_order_status_is_template_only():
    source = OUTBOUND.read_text(encoding="utf-8")
    assert "wecare_order_status_v2" in source
    assert "'type': 'interactive',\n                'interactive': {\n                    'type': 'order_status'" not in source
    assert "ORDER_STATUS_TEMPLATE_NOT_READY" in source


def test_invoice_order_status_route_is_declared():
    source = ROUTE.read_text(encoding="utf-8")
    assert 'POST /invoices/{invoiceId}/order-status' in source
    assert 'wecare-invoice-engine:live' in source


def test_commerce_callers_pin_the_outbound_live_alias():
    callers = [
        ROOT / "amplify/functions/payments/invoice-engine/handler.py",
        ROOT / "amplify/functions/ecommerce/checkout/invoice_engine.py",
        ROOT / "amplify/functions/payments/razorpay-webhook/handler.py",
    ]
    for path in callers:
        source = path.read_text(encoding="utf-8")
        assert "os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp:live')" in source
        assert "os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp')" not in source
