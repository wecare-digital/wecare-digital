"""Approved v6 receipt appearance. Renders stored invoice figures; never prices a payment."""
from __future__ import annotations

import io
import random
import textwrap
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


def render(invoice, items, *, company, font_path, ist_strftime, canonical_status,
           amount_in_words, customer_id, source_label):
    scale = 3
    font_path = Path(font_path)
    fonts = [ImageFont.truetype(str(font_path), size * scale) for size in (19, 16, 26, 20)]
    body, small, title, heading = fonts
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    width = 46 * measure.textbbox((0, 0), 'M', font=body)[2] + 156
    pad, line, tear, margin = 26 * scale, 34 * scale, 20 * scale, 40 * scale
    black = (18, 18, 18)
    rows = []

    def fit(value, font, max_width):
        value = str(value or '')
        if value and measure.textbbox((0, 0), value, font=font)[2] <= max_width:
            yield value
            return
        words = str(value or '').split()
        current = ''
        for word in words:
            # Bound even a single long email, identifier or product name.
            for part in textwrap.wrap(word, 46, break_long_words=True, break_on_hyphens=False) or ['']:
                candidate = (current + ' ' + part).strip()
                if current and measure.textbbox((0, 0), candidate, font=font)[2] > max_width:
                    yield current
                    current = part
                else:
                    current = candidate
        if current:
            yield current

    def text(value, font=body, align='left'):
        for value in fit(value, font, width - 2 * pad):
            rows.append(('text', value, '', font, align))

    def pair(label, value, font=body):
        value = str(value or '')
        remaining = width - 2 * pad - measure.textbbox((0, 0), label, font=font)[2] - 20
        if measure.textbbox((0, 0), value, font=font)[2] <= remaining:
            rows.append(('pair', label, value, font, 'left'))
        else:
            text(label, font)
            text(value, font)

    def sep(double=False):
        rows.append(('double' if double else 'line', '', '', body, 'left'))

    def money(value):
        return 'Rs' + format(Decimal(str(value or 0)), ',.2f')

    status = str(canonical_status(invoice.get('paymentStatus', 'pending'))).upper()
    epoch = invoice.get('createdAt') or invoice.get('invoiceDate') or 0
    text(company['legal_name'], title, 'center')
    text('Brand: ' + company['name'], heading, 'center')
    text('GSTIN: ' + company['gstin'], small, 'center')
    text('PAN: ' + company['pan'], small, 'center')
    text('The W.B.S.I.D.C. Building, Unit 1/20,', small, 'center')
    text('81/2/7, Phears Ln, Kolkata, WB 700012', small, 'center')
    text('one@wecare.digital  |  +91 93309 94400', small, 'center')
    sep(True)
    text('TAX INVOICE', title, 'center')
    sep()
    if invoice.get('invoiceNumber'):
        pair('Invoice No:', invoice['invoiceNumber'])
    pair('Order ID:', invoice.get('orderId') or invoice.get('referenceId') or '')
    pair('Date:', ist_strftime('%d-%m-%Y', epoch))
    pair('Time:', ist_strftime('%H:%M IST', epoch))
    pair('Status:', 'PAID' if status == 'CAPTURED' else status or 'PENDING', heading)
    if customer_id:
        pair('Customer ID:', customer_id, small)
    pair('Source:', source_label, small)
    sep()
    text('BILL TO:', heading)
    text(invoice.get('customerName') or 'Customer')
    text(invoice.get('customerPhone') or '')
    text(invoice.get('customerEmail') or '')
    address = invoice.get('shippingAddress') or invoice.get('billingAddress') or ''
    if invoice.get('addressLine1'):
        address = ', '.join(str(invoice.get(k) or '').strip() for k in
                            ('addressLine1', 'addressLine2', 'city', 'state', 'postalCode')
                            if invoice.get(k))
    text(address)
    sep()
    pair('#  ITEM             QTY  RATE', 'AMOUNT', small)
    quantity = 0
    for index, item in enumerate(items, 1):
        qty = int(item.get('quantity') or 1)
        quantity += qty
        name = str(item.get('name') or 'Item')
        label = f'{index}  {name[:18]:<18} {qty}  {money(item.get("amount", 0))}'
        if len(name) <= 18:
            pair(label, money(Decimal(str(item.get('amount') or 0)) * qty), small)
        else:
            text(f'{index}  {name}', small)
            pair(f'   {qty} x {money(item.get("amount", 0))}',
                 money(Decimal(str(item.get('amount') or 0)) * qty), small)
    sep()
    pair('Subtotal', money(invoice.get('subtotal')))
    discount = Decimal(str(invoice.get('discount') or 0))
    if discount:
        pair('Coupon / adjustment', '-' + money(discount))
    tax = Decimal(str(invoice.get('tax') or 0))
    rate = Decimal(str(invoice.get('gstRate') or 0))
    # The stored invoice owns tax. The renderer only displays its existing split.
    cgst = (tax / 2).quantize(Decimal('.01'))
    sgst = tax - cgst
    if tax or rate:
        pair(f'CGST @ {rate / 2:g}%', money(cgst))
        pair(f'SGST @ {rate / 2:g}%', money(sgst))
    for key, label in [('shipping', 'Shipping'), ('handling', 'Handling'),
                       ('convenienceFee', 'Convenience Fee')]:
        if invoice.get(key):
            pair(label, money(invoice[key]))
    sep(True)
    pair(f'TOTAL ({quantity} ITEMS)', money(invoice.get('total')), title)
    if invoice.get('giftCardRequiredPaise'):
        pair('Gift card ' + str(invoice.get('giftCardLast4') or '').rjust(8, '*'),
             money(Decimal(str(invoice['giftCardRequiredPaise'])) / 100))
        pair('AMOUNT PAYABLE', money(invoice.get('amountPayable')), heading)
    for words in textwrap.wrap(amount_in_words(Decimal(str(invoice.get('total') or 0))), 38):
        text(words, small)
    sep(True)
    text('GST SUMMARY', heading, 'center')
    pair('Taxable Amount', money(Decimal(str(invoice.get('subtotal') or 0)) - discount))
    pair(f'CGST @ {rate / 2:g}%', money(cgst))
    pair(f'SGST @ {rate / 2:g}%', money(sgst))
    pair('Total Tax', money(tax), heading)
    sep()
    if status == 'CAPTURED':
        text('*  *  *   PAID   *  *  *', heading, 'center')
        if invoice.get('paidAt'):
            text('Paid on: ' + ist_strftime('%d-%m-%Y %H:%M IST', invoice['paidAt']), small, 'center')
    else:
        text('PAYMENT ' + (status or 'PENDING'), heading, 'center')
    sep()
    text('Thank You!', heading, 'center')
    text('Visit Again!', body, 'center')
    text('https://wecare.digital', small, 'center')

    height = 2 * (pad + tear) + len(rows) * line
    paper = Image.new('RGB', (width, height), (252, 252, 250))
    draw = ImageDraw.Draw(paper)
    y = pad + tear
    for kind, left, right, font, align in rows:
        if kind in ('line', 'double'):
            draw.line([(pad, y + 30), (width - pad, y + 30)], fill=black, width=3 if kind == 'line' else 6)
            if kind == 'double':
                draw.line([(pad, y + 45), (width - pad, y + 45)], fill=black, width=6)
        else:
            x = (width - draw.textbbox((0, 0), left, font=font)[2]) // 2 if align == 'center' else pad
            draw.text((x, y), left, fill=black, font=font)
            if kind == 'pair':
                draw.text((width - pad - draw.textbbox((0, 0), right, font=font)[2], y), right, fill=black, font=font)
        y += line
    rng = random.Random(7)

    def edge(base):
        points, x = [], 0
        while x <= width:
            points.append((x, base + rng.randint(-tear + 12, tear - 12) + rng.randint(-6, 6)))
            x += 21 + rng.randint(-6, 9)
        points.append((width, base))
        return points

    mask = Image.new('L', paper.size, 0)
    ImageDraw.Draw(mask).polygon(edge(tear) + list(reversed(edge(height - tear))), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.8))
    canvas = Image.new('RGBA', (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    shadow_alpha = Image.new('L', canvas.size, 0)
    shadow_alpha.paste(mask, (margin + 12, margin + 21))
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(18)).point(lambda value: int(value * .35))
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas = Image.alpha_composite(canvas, shadow)
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    layer.paste(paper, (margin, margin), mask)
    canvas = Image.alpha_composite(canvas, layer)
    canvas = canvas.resize((canvas.width * 2 // scale, canvas.height * 2 // scale), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()
