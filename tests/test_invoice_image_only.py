from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_post_payment_webhook_generates_image_only():
    source = read('amplify/functions/payments/razorpay-webhook/handler.py')
    assert "generate-image" in source
    fn = source[source.index('def _generate_invoice_assets'):source.index('_RECEIPT_DELIVERY_MAX_ATTEMPTS')]
    assert 'generate-pdf' not in fn
    assert 'invoice_pdf_triggered' not in fn


def test_invoice_engine_retires_pdf_route_fail_closed():
    source = read('amplify/functions/payments/invoice-engine/handler.py')
    route = source[source.index("if method == 'POST' and 'generate-pdf' in path:"):][:500]
    assert 'INVOICE_IMAGE_ONLY' in route
    assert 'generate_invoice_pdf(inv_id' not in route


def test_payments_ui_and_client_do_not_offer_pdf_generation():
    client = read('src/api/client.ts')
    payflow = read('src/components/workspace/pay/PayFlow.tsx')
    assert 'generateInvoicePdf' not in client
    assert 'Generate PDF' not in payflow
    assert 'doGeneratePdf' not in payflow


def test_customer_invoice_surface_is_png_only():
    api = read('amplify/functions/ecommerce/customer-invoice/handler.py')
    flow = read('amplify/functions/messaging/whatsapp-business-api/flows/customer_invoice.py')
    assert 'ASSET_TYPE = {"png": "image"}' in api
    assert '"pdf": "pdf"' not in api
    assert 'PDF downloads remain available' not in flow
    assert 'invoice image was accepted' in flow
