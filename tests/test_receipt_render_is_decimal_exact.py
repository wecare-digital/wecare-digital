"""The receipt renders money from Decimal, so the printed breakdown cannot drift a paise.

Why this is its own regression, and not covered by the layout specimen
----------------------------------------------------------------------
The receipt/HTML/PDF builders used to read every money figure with `float()` and compute line
totals and summed breakdowns in binary floating point. `0.1 + 0.2` is `0.30000000000000004` in a
float, and a line total of `unit * qty` summed across several items can land a paise away from the
stored `total`. On a customer-visible TAX INVOICE that is a document whose own line breakdown does
not add up to its grand total - exactly the arithmetic a GST reader cannot follow.

The fix renders every figure through `_render_money` (an exact rupee `Decimal` quantized to 2dp,
read off the STORED row) and derives the printed grand total from the stored `total` field, so the
printed breakdown and the printed grand total are both the authoritative figures. This file pins
that on an invoice built from a classic float-drift case.

Nothing here touches the authoritative/validation path: the stored totals remain the authority and
no figure is compared against a provider capture. This is rendering only.
"""
from __future__ import annotations

import re
from decimal import Decimal

# Reuse the by-path, boto3-patched handler loader the neighbouring invoice-engine tests use.
from tests.test_receipt_transparent_background import invoice_engine  # noqa: F401


def _html_money(label: str, html: str) -> Decimal:
    """The rupee figure printed next to `label` in the receipt HTML, as a Decimal."""
    # Rows render as `<span>Label</span><span>[-][&#8377; ]1,234.56</span>`. The grand-total row
    # carries the rupee entity `&#8377; ` before the figure, so skip up to the last `; ` or `>`.
    match = re.search(re.escape(label) + r'</span><span>(?:.*?[>;] ?)?(-?[\d,]+\.\d{2})</span>',
                      html)
    assert match, f'label {label!r} not found in rendered HTML'
    return Decimal(match.group(1).replace(',', ''))


def _drift_invoice() -> dict:
    """An invoice whose stored total is the EXACT Decimal sum of a float-drift-prone breakdown.

    `0.10 + 0.10 + 0.10 + 0.20` sums to `0.30000000000000004` as a float; the stored subtotal and
    total are the exact `0.50`. gstRate 0 keeps the identity `subtotal == total` so the printed
    grand total must equal the printed line-breakdown sum to the paise.
    """
    return {
        'invoiceId': 'inv-drift-fixture',
        'invoiceNumber': 'WD/2627/09999',
        'referenceId': 'WD-PAY-DRIFTONLY',
        'orderId': 'WD-ORD-DRIFT1',
        'createdAt': 1760000000,
        'customerName': 'A. Customer',
        'customerPhone': '+919812345678',
        'shippingAddress': 'Kolkata, WB 700012',
        'subtotal': '0.50', 'tax': '0', 'gstRate': '0',
        'discount': '0', 'convenienceFee': '0', 'total': '0.50',
        'paymentStatus': 'pending',
    }


def _drift_items() -> list[dict]:
    return [
        {'itemIndex': 0, 'name': 'Paise item A', 'quantity': 3, 'amount': '0.10'},
        {'itemIndex': 1, 'name': 'Paise item B', 'quantity': 1, 'amount': '0.20'},
    ]


def test_render_money_helper_quantizes_stored_field_without_float(invoice_engine):
    """`_render_money` coerces a stored money field to an exact 2dp rupee Decimal.

    `1.005` is `1.00499999...` as a float, so a float render prints `1.00`; the Decimal path
    rounds HALF_UP to `1.01`. Proving the type and the rounding here is what the renderers rely on.
    """
    assert invoice_engine._render_money('0.50') == Decimal('0.50')
    assert isinstance(invoice_engine._render_money('0.50'), Decimal)
    assert invoice_engine._render_money('1.005') == Decimal('1.01')
    assert invoice_engine._render_money(None) == Decimal('0.00')


def test_printed_line_breakdown_sums_to_stored_total_with_no_paise_drift(invoice_engine):
    """The receipt HTML prints line totals whose sum equals the stored total string exactly."""
    html = invoice_engine._build_invoice_html(_drift_invoice(), _drift_items())

    # Every line total in the items table, in print order.
    line_totals = [Decimal(m.replace(',', ''))
                   for m in re.findall(r'<td class="r">(-?[\d,]+\.\d{2})</td>', html)]
    # Rate and line-total columns alternate; the line totals are the even-indexed amounts, but
    # for this fixture (qty>1 only on the 0.10 item) assert on the known expected set instead.
    assert Decimal('0.30') in line_totals  # 0.10 * 3, not 0.30000000000000004
    assert Decimal('0.20') in line_totals

    subtotal = _html_money('Subtotal', html)
    grand = _html_money('items)', html)  # `Total (4 items)` grand-total row

    assert subtotal == Decimal('0.50')
    # The printed grand total equals the STORED authoritative total exactly.
    assert grand == Decimal(_drift_invoice()['total'])
    # And it equals the sum of the printed line breakdown - no one-paise drift.
    assert grand == Decimal('0.30') + Decimal('0.20')


def test_png_renderer_prints_decimal_line_totals_and_stored_grand_total(invoice_engine, monkeypatch):
    """The PNG receipt draws the same Decimal figures: line totals and the stored grand total."""
    from PIL import ImageDraw

    monkeypatch.setattr(invoice_engine, '_load_logo_bytes', lambda: None)
    monkeypatch.setattr(invoice_engine, '_load_s3_image', lambda _k: None)
    monkeypatch.setattr(invoice_engine.s3, 'get_object',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no S3')))
    # Force the legacy inline renderer (the code this feature converted to Decimal); the
    # transparent path delegates to the separate receipt_layout module, out of scope here.
    monkeypatch.setenv('RECEIPT_TRANSPARENT_BG', 'false')

    drawn: list[str] = []
    original = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    invoice_engine._generate_receipt_png(_drift_invoice(), _drift_items())

    blob = '\n'.join(drawn)
    # The 0.10 x3 line total prints as the exact 0.30, never 0.30000000000000004.
    assert any('0.30' in line for line in drawn)
    # The grand total row carries the stored total figure, derived from the authoritative field.
    assert '\u20b9 0.50' in blob
    # A float render of 0.1*3 formatted to 2dp would still read 0.30 here, so the stronger guard
    # is that no raw float artefact leaked into any drawn string.
    assert not any('0000000' in line or '9999999' in line for line in drawn)


def test_amount_in_words_matches_the_stored_total_decimal(invoice_engine):
    """The words line is derived from the stored total Decimal, so it names the printed figure."""
    assert invoice_engine._amount_in_words(Decimal('0.50')) == 'Rupees Zero and Fifty Paise Only'
    assert invoice_engine._amount_in_words(Decimal('104.45')) == (
        'Rupees One Hundred Four and Forty-Five Paise Only')
