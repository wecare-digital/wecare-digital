"""Exercise the approved renderer and document delivery with real PIL and inert providers."""
import io
import json
from unittest.mock import MagicMock

from tests.test_receipt_transparent_background import invoice_engine  # noqa: F401


def _invoice():
    return {
        'invoiceId': 'inv-approved-fixture', 'invoiceNumber': 'WD/2627/00001',
        'orderId': 'WD-ORD-EXAMPLE1', 'paymentStatus': 'captured',
        'createdAt': 1791374820, 'paidAt': 1791374820,
        'customerName': 'A. Customer', 'customerPhone': '+919812345678',
        'customerEmail': 'customer@example.com',
        'customerUuid': '7f3b1c9a-4e21-4d8b-ae55-112233445566',
        'shippingAddress': '12 Example Road, Kolkata, West Bengal 700012',
        'subtotal': '101.00', 'tax': '.46', 'gstRate': '18',
        'convenienceFee': '2.99', 'total': '104.45',
    }


def test_approved_layout_renders_stored_money_identity_and_verified_paid_status(invoice_engine, monkeypatch):
    from PIL import Image, ImageDraw

    monkeypatch.delenv('RECEIPT_TRANSPARENT_BG', raising=False)
    drawn = []
    original = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    raw = invoice_engine._generate_receipt_png(_invoice(), [
        {'name': 'Rs1 test product', 'amount': '1.00', 'quantity': 1},
        {'name': 'Contribute Rs100', 'amount': '100.00', 'quantity': 1}])
    image = Image.open(io.BytesIO(raw))
    assert image.mode == 'RGBA'
    assert image.width == 1153  # same font and column width as the approved specimen
    assert image.getpixel((0, 0))[3] == 0
    assert '*  *  *   PAID   *  *  *' in drawn
    assert 'PAID' in drawn
    assert 'WD/2627/00001' in drawn
    assert 'WD-ORD-EXAMPLE1' in drawn
    assert _invoice()['customerUuid'] in drawn
    assert _invoice()['customerEmail'] in drawn
    assert 'Rs104.45' in drawn
    assert 'Rs2.99' in drawn
    assert 'Rs0.23' in drawn
    assert drawn.index('Invoice No:') < drawn.index('Date:')


def test_pending_invoice_is_never_printed_as_paid(invoice_engine, monkeypatch):
    from PIL import ImageDraw

    monkeypatch.delenv('RECEIPT_TRANSPARENT_BG', raising=False)
    drawn = []
    original = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    invoice_engine._generate_receipt_png({**_invoice(), 'paymentStatus': 'pending'}, [])
    assert 'PAYMENT PENDING' in drawn
    assert '*  *  *   PAID   *  *  *' not in drawn
    assert not any(text.startswith('Paid on:') for text in drawn)


def test_approved_receipt_is_delivered_as_same_engine_pdf_document(invoice_engine, monkeypatch):
    monkeypatch.delenv('RECEIPT_TRANSPARENT_BG', raising=False)
    table = MagicMock()
    table.get_item.return_value = {'Item': _invoice()}
    dynamodb = MagicMock()
    dynamodb.Table.return_value = table
    monkeypatch.setattr(invoice_engine, 'dynamodb', dynamodb)
    pdf = MagicMock(return_value={'statusCode': 200, 'body': json.dumps({
        'pdfUrl': 'https://example.invalid/private.pdf',
        's3Key': 'secure/stack/invoices/fixture.pdf'})})
    image = MagicMock()
    monkeypatch.setattr(invoice_engine, 'generate_invoice_pdf', pdf)
    monkeypatch.setattr(invoice_engine, 'generate_invoice_image', image)
    monkeypatch.setattr(invoice_engine, '_lookup_contact_by_phone', lambda _: None)
    sender = MagicMock()
    sender.invoke.return_value = {'Payload': io.BytesIO(json.dumps({
        'statusCode': 200, 'body': json.dumps({'status': 'sent', 'messageId': 'fixture-only'})
    }).encode())}
    monkeypatch.setattr(invoice_engine, 'lambda_client', sender)
    response = invoice_engine.send_invoice_whatsapp('inv-approved-fixture', '+919812345678', '',
                                                    'test-only', force=True)
    assert response['statusCode'] == 200
    pdf.assert_called_once_with('inv-approved-fixture', 'test-only')
    image.assert_not_called()
    payload = json.loads(json.loads(sender.invoke.call_args.kwargs['Payload'])['body'])
    assert payload['mediaType'] == 'document'
    assert payload['mediaFile'] == 'secure/stack/invoices/fixture.pdf'
    assert payload['mediaFileName'].endswith('.pdf')
