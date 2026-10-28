"""WECARE.DIGITAL customer payment receipt v8.

Presentation only: renders persisted invoice figures; never prices a payment.
The visual hierarchy follows the owner-approved 1024px receipt mock while the money rows follow
the v8 accounting contract (Items Subtotal / Delight / Express / Convenience Fee / seller GSTIN).
Internal statutory invoice numbers, order IDs and raw customer UUIDs stay stored and are omitted
from this customer-facing WhatsApp receipt. The canonical compact customer display code may be shown.
"""
from __future__ import annotations

import io
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

LIME = (209, 244, 112)       # #d1f470
FOREST = (26, 58, 42)        # #1a3a2a
INK = (20, 31, 38)
MUTED = (83, 97, 105)
PAPER = (252, 252, 250)
PALE = (238, 245, 239)
LINE = (210, 221, 214)
PAID_GREEN = (13, 132, 58)


def _money(value, symbol="₹"):
    amount = Decimal(str(value if value is not None else 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return symbol + format(amount, ",.2f")


def _draws(font, char):
    """True when `font` has a glyph for `char` instead of drawing its missing-glyph box.

    A missing character renders as the font's .notdef glyph, the same mask as U+FFFF, a
    permanent noncharacter that no font maps.
    """
    try:
        return bytes(font.getmask(char)) != bytes(font.getmask("\uffff"))
    except Exception:
        return False


def _font(font_paths, role, size):
    for choice in (font_paths.get(role), font_paths.get("regular")):
        if not choice:
            continue
        try:
            if isinstance(choice, (bytes, bytearray)):
                return ImageFont.truetype(io.BytesIO(choice), size)
            return ImageFont.truetype(str(Path(choice)), size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit(draw, value, font, max_width, max_lines=None):
    value = str(value or "").strip()
    if not value:
        return []
    lines, current = [], ""
    for word in value.split():
        candidate = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _strip_ref(value):
    value = str(value or "").strip()
    return value[7:] if value.startswith("WD-PAY-") else value


def _buyer_gstin(invoice, seller_gstin):
    value = str(invoice.get("buyerGstin") or invoice.get("gstin") or "").strip().upper()
    seller = str(seller_gstin or "").strip().upper()
    return "" if not value or value == seller else value


def _address(invoice):
    structured = ", ".join(
        str(invoice.get(k) or "").strip()
        for k in ("addressLine1", "addressLine2", "city", "state", "postalCode")
        if invoice.get(k)
    )
    return structured or str(
        invoice.get("shippingAddress") or invoice.get("billingAddress") or "").strip()


def _place(invoice):
    state = str(invoice.get("state") or invoice.get("shippingState") or "").strip()
    if state.casefold() in {"west bengal", "wb"}:
        return "West Bengal (19)"
    return state


def _scalloped_mask(size, inset, radius, step):
    """Return a deterministic four-sided receipt edge mask.

    The approved mock has a lime scallop around all four sides, not only a torn top/bottom.
    Build the paper body as a rectangle and bite identical semicircular notches out of every
    edge.  Keeping it deterministic makes a re-render of one issued invoice visually stable.
    """
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((inset, inset, width - inset, height - inset), fill=255)
    d = radius * 2
    x = inset + radius
    while x <= width - inset - radius:
        draw.ellipse((x - radius, inset - radius, x + radius, inset + radius), fill=0)
        draw.ellipse((x - radius, height - inset - radius,
                      x + radius, height - inset + radius), fill=0)
        x += step
    y = inset + radius
    while y <= height - inset - radius:
        draw.ellipse((inset - radius, y - radius, inset + radius, y + radius), fill=0)
        draw.ellipse((width - inset - radius, y - radius,
                      width - inset + radius, y + radius), fill=0)
        y += step
    return mask


def _logo(canvas, logo_bytes, box):
    if not logo_bytes:
        return False
    try:
        image = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        max_w, max_h = box[2] - box[0], box[3] - box[1]
        ratio = min(max_w / image.width, max_h / image.height)
        image = image.resize(
            (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS)
        canvas.alpha_composite(
            image,
            (box[0] + (max_w - image.width) // 2,
             box[1] + (max_h - image.height) // 2))
        return True
    except Exception:
        return False


def _gradient_roundrect(canvas, box, left, right, radius):
    """Draw a horizontal brand gradient clipped to a rounded rectangle.

    Pillow's native gradient/colorize path replaces the former Python nested pixel loop.
    On Lambda that loop ran hundreds of thousands of Python assignments per receipt and was
    a disproportionate part of the ~5 second render path.
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    ramp = Image.linear_gradient("L").rotate(90, expand=True).resize((w, h))
    band = ImageOps.colorize(ramp, black=left, white=right).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    band.putalpha(mask)
    canvas.alpha_composite(band, (x0, y0))


def render(invoice, items, *, company, font_paths, logo_bytes, ist_strftime,
           canonical_status, amount_in_words, source_label, customer_id=""):
    """Render the approved branded WhatsApp PAYMENT RECEIPT."""
    scale = 2
    # 956 + 2*34 => 1024 px after the 2x antialiasing downsample. This matches the approved
    # reference width exactly while still rendering internally at 2x for clean WhatsApp text.
    width = 956 * scale
    margin = 34 * scale
    inner = 58 * scale
    content_w = width - 2 * inner
    paper_h = (1580 + max(0, len(items) - 2) * 90) * scale

    regular = _font(font_paths, "regular", 17 * scale)
    semibold = _font(font_paths, "semibold", 17 * scale)
    bold = _font(font_paths, "bold", 20 * scale)
    title = _font(font_paths, "bold", 30 * scale)
    brand = _font(font_paths, "bold", 25 * scale)
    legal = _font(font_paths, "bold", 22 * scale)
    small = _font(font_paths, "regular", 14 * scale)
    small_bold = _font(font_paths, "semibold", 14 * scale)
    total_font = _font(font_paths, "bold", 29 * scale)
    footer_font = _font(font_paths, "bold", 24 * scale)
    # Inter (the S3 font prefix) has ₹; the packaged fallback does not, and would print its
    # missing-glyph box in every amount. Say "Rs." in that case instead.
    symbol = "₹" if _draws(regular, "₹") else "Rs."

    paper = Image.new("RGBA", (width, paper_h), PAPER + (255,))
    draw = ImageDraw.Draw(paper)
    y = 38 * scale

    raw_status = str(canonical_status(invoice.get("paymentStatus", "pending")) or "pending").upper()
    status = "PAID" if raw_status == "CAPTURED" else raw_status
    epoch = ((invoice.get("paidAt") if status == "PAID" else None)
             or invoice.get("createdAt") or invoice.get("invoiceDate") or 0)
    date_str = ist_strftime("%d-%m-%Y", epoch) if epoch else ""
    time_str = ist_strftime("%H:%M IST", epoch) if epoch else ""
    ref = _strip_ref(invoice.get("referenceId"))
    txn = str(invoice.get("providerPaymentId") or invoice.get("paymentId") or "").strip()
    buyer_gstin = _buyer_gstin(invoice, company.get("gstin"))
    place = _place(invoice)
    address = _address(invoice)
    customer_id = str(customer_id or "").strip()

    subtotal = Decimal(str(invoice.get("subtotal") or 0))
    discount = Decimal(str(invoice.get("discount") or 0))
    shipping = Decimal(str(invoice.get("shipping") or 0))
    handling = Decimal(str(invoice.get("handling") or 0))
    supply_tax = Decimal(str(invoice.get("tax") or 0))
    convenience_net = Decimal(str(
        invoice.get("convenienceFeeNet")
        if invoice.get("convenienceFeeNet") is not None
        else invoice.get("convenienceFee") or 0))
    convenience_gst = Decimal(str(invoice.get("convenienceFeeGst") or 0))
    total_gst = supply_tax + convenience_gst
    total = Decimal(str(invoice.get("total") or 0))

    def centered(value, font, fill=INK, gap=5, clear_ink=False):
        nonlocal y
        for line in _fit(draw, value, font, content_w, 2):
            bb = draw.textbbox((0, 0), line, font=font)
            draw.text(((width - (bb[2] - bb[0])) // 2, y), line, font=font, fill=fill)
            # The ink starts bb[1] below `y`, so advancing by ink height alone leaves the next
            # line bb[1] too high. `clear_ink` advances past the real bottom of the ink.
            y += (bb[3] if clear_ink else bb[3] - bb[1]) + gap * scale

    def bar(value, font):
        nonlocal y
        h = 58 * scale
        _gradient_roundrect(paper, (inner, y, width - inner, y + h),
                            (196, 244, 71), (170, 239, 45), 12 * scale)
        bb = draw.textbbox((0, 0), value, font=font)
        draw.text(((width - (bb[2] - bb[0])) // 2, y + (h - (bb[3] - bb[1])) // 2 - 3 * scale),
                  value, font=font, fill=FOREST)
        y += h + 15 * scale

    # Canonical receipt lockup: the immutable official transparent bag mark plus the same
    # WECARE./DIGITAL wordmark construction used by src/components/BrandLockup.tsx.
    mark_size = 88 * scale
    brand_gap = 16 * scale
    wecare_text, digital_text = "WECARE", "DIGITAL"
    wecare_bb = draw.textbbox((0, 0), wecare_text, font=brand)
    digital_bb = draw.textbbox((0, 0), digital_text, font=brand)
    dot_bb = draw.textbbox((0, 0), ".", font=brand)
    text_w = max(
        (wecare_bb[2] - wecare_bb[0]) + (dot_bb[2] - dot_bb[0]),
        digital_bb[2] - digital_bb[0],
    )
    lockup_w = mark_size + brand_gap + text_w
    lockup_x = (width - lockup_w) // 2
    mark_drawn = _logo(
        paper, logo_bytes,
        (lockup_x, y, lockup_x + mark_size, y + mark_size),
    )
    word_x = lockup_x + (mark_size + brand_gap if mark_drawn else 0)
    word_y = y + 7 * scale
    draw.text((word_x, word_y), wecare_text, font=brand, fill=INK)
    draw.text(
        (word_x + (wecare_bb[2] - wecare_bb[0]), word_y),
        ".", font=brand, fill=(255, 0, 64),
    )
    draw.text((word_x, word_y + 31 * scale), digital_text, font=brand, fill=INK)
    y += 101 * scale

    centered(company.get("legal_name", "WECARE.DIGITAL BHARATWORKS"), legal, FOREST, 2, True)
    draw.line((width * .27, y + 2 * scale, width * .73, y + 2 * scale),
              fill=LIME, width=4 * scale)
    y += 16 * scale
    centered(f"GSTIN: {company.get('gstin','')}   |   PAN: {company.get('pan','')}", small, INK, 2)
    centered("The W.B.S.I.D.C. Building, Unit No. 1/20,", small, INK, 1)
    centered("81/2/7 Phears Lane, Kolkata, West Bengal - 700012, India", small, INK, 1)
    centered(f"{company.get('email','')}  |  {company.get('phone','')}  |  {company.get('website','')}",
             small, INK, 1)
    y += 9 * scale
    bar("PAYMENT RECEIPT", title)

    left_x = inner + 8 * scale
    split_x = width // 2
    right_x = split_x + 26 * scale
    fact_line = 31 * scale
    def fact(x, yy, label, value, strong=False):
        draw.text((x, yy), label, font=small_bold, fill=MUTED)
        draw.text((x + 132 * scale, yy), str(value or ""),
                  font=semibold if strong else small, fill=INK)
    facts_y = y
    fact(left_x, facts_y, "Receipt Ref:", ref, True)
    fact(left_x, facts_y + fact_line, "Date:", date_str)
    fact(left_x, facts_y + 2 * fact_line, "Time:", time_str)
    draw.text((right_x, facts_y), "Status:", font=small_bold, fill=MUTED)
    status_x = right_x + 132 * scale
    status_w = 118 * scale
    status_h = 28 * scale
    draw.rounded_rectangle(
        (status_x, facts_y - 2 * scale, status_x + status_w, facts_y + status_h),
        radius=12 * scale, fill=LIME if status == "PAID" else PALE)
    sb = draw.textbbox((0, 0), status, font=semibold)
    draw.text((status_x + (status_w - (sb[2] - sb[0])) // 2, facts_y),
              status, font=semibold, fill=FOREST)
    fact(right_x, facts_y + fact_line, "Channel:", source_label)
    fact(right_x, facts_y + 2 * fact_line, "Txn:", txn)
    draw.line((split_x, facts_y - 4 * scale, split_x, facts_y + 3 * fact_line),
              fill=LINE, width=2 * scale)
    y = facts_y + 3 * fact_line + 15 * scale

    # The approved mock uses a slim pale BILL TO band and white customer/address columns below,
    # separated by a vertical rule. Keep that hierarchy instead of tinting the whole customer card.
    card_top = y
    header_card_h = 38 * scale
    body_card_h = (
        92
        + (28 if customer_id else 0)
        + (28 if buyer_gstin or place else 0)
    ) * scale
    draw.rounded_rectangle((inner, card_top, width - inner, card_top + header_card_h),
                           radius=9 * scale, fill=PALE)
    draw.text((inner + 14 * scale, card_top + 6 * scale), "BILL TO",
              font=semibold, fill=FOREST)
    y = card_top + header_card_h + 13 * scale
    ly = y
    for value, font in (
        (invoice.get("customerName") or "Customer", semibold),
        (invoice.get("customerPhone") or "", regular),
        (invoice.get("customerEmail") or "", regular),
    ):
        if value:
            for line in _fit(draw, value, font, int(content_w * .45), 1):
                draw.text((inner + 16 * scale, ly), line, font=font, fill=INK)
                ly += 27 * scale

    divider_x = width // 2
    if customer_id:
        # Customer-visible support label only. The canonical UUID remains internal; the engine
        # passes customer_uuid.display_code(invoice), which is the established C-XXXXXXXXXXXX
        # presentation contract and never an authentication or join key.
        pill_top = ly - 3 * scale
        pill_bottom = ly + 25 * scale
        draw.rounded_rectangle(
            (inner + 10 * scale, pill_top, divider_x - 18 * scale, pill_bottom),
            radius=8 * scale, fill=PALE,
        )
        label = "Customer ID:"
        draw.text((inner + 16 * scale, ly), label, font=small_bold, fill=FOREST)
        label_bb = draw.textbbox((0, 0), label, font=small_bold)
        draw.text(
            (inner + 24 * scale + (label_bb[2] - label_bb[0]), ly),
            customer_id, font=small_bold, fill=INK,
        )
        ly += 28 * scale

    draw.line((divider_x, y - 4 * scale, divider_x,
               card_top + header_card_h + body_card_h - 10 * scale),
              fill=LINE, width=2 * scale)
    ax, ay = divider_x + 28 * scale, y
    for line in _fit(draw, address, regular, width - inner - ax - 15 * scale, 3):
        draw.text((ax, ay), line, font=regular, fill=INK)
        ay += 27 * scale
    info_y = card_top + header_card_h + body_card_h - 30 * scale
    if buyer_gstin:
        draw.text((inner + 16 * scale, info_y),
                  f"Buyer GSTIN: {buyer_gstin}", font=small_bold, fill=INK)
    if place:
        value = f"Place of Supply: {place}"
        bb = draw.textbbox((0, 0), value, font=small_bold)
        draw.text((width - inner - 16 * scale - (bb[2] - bb[0]),
                   info_y), value, font=small_bold, fill=INK)
    y = card_top + header_card_h + body_card_h + 18 * scale

    header_h = 42 * scale
    _gradient_roundrect(paper, (inner, y, width - inner, y + header_h),
                        (237, 246, 236), (221, 239, 221), 9 * scale)
    x_no = inner + 14 * scale
    x_desc = inner + 55 * scale
    x_qty = width - inner - 315 * scale
    x_rate = width - inner - 205 * scale
    x_amount = width - inner - 12 * scale
    for x, value in ((x_no, "#"), (x_desc, "DESCRIPTION"), (x_qty, "QTY"), (x_rate, "RATE")):
        draw.text((x, y + 8 * scale), value, font=small_bold, fill=FOREST)
    bb = draw.textbbox((0, 0), "AMOUNT", font=small_bold)
    draw.text((x_amount - (bb[2] - bb[0]), y + 8 * scale),
              "AMOUNT", font=small_bold, fill=FOREST)
    y += header_h + 5 * scale

    for index, item in enumerate(items, 1):
        row_top = y
        qty = int(item.get("quantity") or 1)
        unit = Decimal(str(item.get("amount") or 0))
        amount = unit * qty
        draw.text((x_no, y + 9 * scale), str(index), font=regular, fill=INK)
        name_lines = _fit(draw, item.get("name") or "Item", semibold,
                          x_qty - x_desc - 20 * scale, 2)
        for line in name_lines:
            draw.text((x_desc, y + 4 * scale), line, font=semibold, fill=INK)
            y += 24 * scale
        if not name_lines:
            y += 24 * scale
        description = str(item.get("description") or item.get("variantName") or "").strip()
        if description:
            for line in _fit(draw, description, small, x_qty - x_desc - 20 * scale, 1):
                draw.text((x_desc, y + scale), line, font=small, fill=MUTED)
                y += 22 * scale
        row_y = row_top + 10 * scale
        draw.text((x_qty + 10 * scale, row_y), str(qty), font=regular, fill=INK)
        rate_s = _money(unit, symbol)
        rb = draw.textbbox((0, 0), rate_s, font=regular)
        draw.text((x_rate + 60 * scale - (rb[2] - rb[0]), row_y),
                  rate_s, font=regular, fill=INK)
        amount_s = _money(amount, symbol)
        ab = draw.textbbox((0, 0), amount_s, font=regular)
        draw.text((x_amount - (ab[2] - ab[0]), row_y), amount_s, font=regular, fill=INK)
        y = max(y + 7 * scale, row_top + 58 * scale)
        draw.line((inner + 10 * scale, y, width - inner - 10 * scale, y),
                  fill=LINE, width=scale)
        y += 6 * scale

    y += 5 * scale
    totals_x, val_x = inner + 10 * scale, width - inner - 12 * scale
    def total_row(label, value, font=regular, value_font=None, fill=INK, band=False, top_pad=0):
        nonlocal y
        y += top_pad * scale
        if band:
            draw.rounded_rectangle((inner, y - 3 * scale, width - inner, y + 31 * scale),
                                   radius=8 * scale, fill=PALE)
        draw.text((totals_x, y), label, font=font, fill=fill)
        text_value = _money(value, symbol)
        vf = value_font or font
        bb = draw.textbbox((0, 0), text_value, font=vf)
        draw.text((val_x - (bb[2] - bb[0]), y), text_value, font=vf, fill=fill)
        y += 34 * scale

    total_row("Items Subtotal", subtotal)
    if discount:
        total_row("Delight", -discount, fill=PAID_GREEN)
    if shipping:
        total_row("Express", shipping)
    if handling:
        total_row("Handling", handling)
    if convenience_net:
        total_row("Convenience Fee", convenience_net)
    if total_gst:
        total_row(str(company.get("gstin") or ""), total_gst, semibold, semibold, band=True)

    hero_label = "AMOUNT PAID" if status == "PAID" else "AMOUNT PAYABLE"
    hero_h = 62 * scale
    _gradient_roundrect(paper, (inner, y, width - inner, y + hero_h),
                        (196, 244, 71), (170, 239, 45), 11 * scale)
    draw.text((inner + 16 * scale, y + 10 * scale), hero_label, font=bold, fill=FOREST)
    total_s = _money(total, symbol)
    tb = draw.textbbox((0, 0), total_s, font=total_font)
    draw.text((width - inner - 14 * scale - (tb[2] - tb[0]), y + 4 * scale),
              total_s, font=total_font, fill=FOREST)
    y += hero_h + 12 * scale

    for line in _fit(draw, amount_in_words(total), regular, content_w - 12 * scale, 2):
        draw.text((inner + 10 * scale, y), line, font=regular, fill=INK)
        y += 27 * scale
    y += 10 * scale

    if status == "PAID":
        stamp_w, stamp_h = 265 * scale, 92 * scale
        stamp = Image.new("RGBA", (stamp_w, stamp_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        sd.rounded_rectangle((3 * scale, 3 * scale, stamp_w - 3 * scale, stamp_h - 3 * scale),
                             radius=9 * scale, outline=PAID_GREEN, width=6 * scale)
        cx, cy = 35 * scale, stamp_h // 2
        sd.ellipse((cx - 22 * scale, cy - 22 * scale, cx + 22 * scale, cy + 22 * scale),
                   fill=PAID_GREEN)
        sd.line((cx - 10 * scale, cy, cx - 2 * scale, cy + 9 * scale,
                 cx + 14 * scale, cy - 12 * scale), fill=(255, 255, 255), width=5 * scale)
        sd.text((72 * scale, 20 * scale), "PAID", font=total_font, fill=PAID_GREEN)
        paper.alpha_composite(
            stamp.rotate(7, resample=Image.Resampling.BICUBIC, expand=True),
            (inner + 50 * scale, y))

    trace_x, trace_y = width // 2 + 18 * scale, y + 10 * scale
    for label, value in (
        ("Txn ID:", txn),
        ("Receipt Ref:", ref),
        ("Paid On:", (date_str + " " + time_str).strip()),
    ):
        if value:
            draw.text((trace_x, trace_y), label, font=small, fill=MUTED)
            draw.text((trace_x + 112 * scale, trace_y), value, font=small_bold, fill=INK)
            trace_y += 28 * scale

    y += 112 * scale
    draw.line((inner, y, width - inner, y), fill=LIME, width=4 * scale)
    y += 18 * scale
    centered("Thank You!", footer_font, INK, 5)
    y += 5 * scale
    centered("VISIT AGAIN", small_bold, INK, 3)
    y += 2 * scale
    centered(company.get("website", "https://wecare.digital"), semibold, PAID_GREEN, 1)
    y += 14 * scale

    paper = paper.crop((0, 0, width, min(paper_h, y + 40 * scale)))

    # Four-sided lime scallop from the approved final mock.  The outer silhouette and the
    # inset paper use the same rhythm, leaving a continuous lime frame rather than a straight
    # side with only top/bottom tears.
    frame_inset = 4 * scale
    frame_radius = 10 * scale
    frame_step = 27 * scale
    outer_mask = _scalloped_mask(paper.size, frame_inset, frame_radius, frame_step)
    inner_mask = _scalloped_mask(
        paper.size, frame_inset + 9 * scale, frame_radius, frame_step)

    framed = Image.new("RGBA", paper.size, LIME + (255,))
    framed.putalpha(outer_mask)
    inner_paper = paper.copy()
    inner_paper.putalpha(inner_mask)
    framed.alpha_composite(inner_paper)
    frame_draw = ImageDraw.Draw(framed)
    frame_draw.line((inner, 22 * scale, width - inner, 22 * scale),
                    fill=LIME, width=2 * scale)

    canvas = Image.new("RGBA", (framed.width + 2 * margin, framed.height + 2 * margin),
                       (255, 255, 255, 0))
    canvas.alpha_composite(framed, (margin, margin))
    canvas = canvas.resize((canvas.width // scale, canvas.height // scale),
                           Image.Resampling.LANCZOS)
    # The resize works on premultiplied alpha and leaves black under every fully transparent
    # pixel. Keep them transparent but white, so a viewer that drops alpha (a JPEG conversion)
    # shows white around the torn edge instead of a black frame.
    clear = canvas.getchannel("A").point(lambda alpha: 255 if alpha else 0)
    canvas = Image.composite(canvas, Image.new("RGBA", canvas.size, (255, 255, 255, 0)), clear)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
