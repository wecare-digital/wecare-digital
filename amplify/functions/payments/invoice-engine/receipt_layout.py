"""WECARE.DIGITAL customer PAYMENT RECEIPT v10.

Fresh fixed-coordinate renderer for the owner-approved 1024 x 1536 reference; no legacy visual fallback.
Presentation only: it renders persisted invoice facts and never recalculates pricing.
"""
from __future__ import annotations

import io
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

LIME = (209, 244, 112)
LIME_STRONG = (190, 247, 25)
FOREST = (26, 58, 42)
INK = (17, 23, 29)
MUTED = (86, 93, 99)
PAPER = (253, 253, 251)
PALE = (239, 246, 240)
LINE = (210, 219, 213)
PAID_GREEN = (8, 133, 55)
RED = (255, 0, 64)  # brand dot, #ff0040 as in BrandLockup

BASE_W = 1024
BASE_H = 1536
PAPER_X0 = 108
PAPER_X1 = 916
INNER_X0 = 158
INNER_X1 = 866


def _money(value, symbol="₹"):
    amount = Decimal(str(value if value is not None else 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return symbol + format(amount, ",.2f")


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


def _draws(font, char):
    try:
        return bytes(font.getmask(char)) != bytes(font.getmask("\uffff"))
    except Exception:
        return False


def _fit(draw, value, font, max_width, max_lines=1):
    value = str(value or "").strip()
    if not value:
        return []
    out, cur = [], ""
    for word in value.split():
        cand = (cur + " " + word).strip()
        if cur and draw.textbbox((0, 0), cand, font=font)[2] > max_width:
            out.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        out.append(cur)
    if max_lines and len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out


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
    return structured or str(invoice.get("shippingAddress") or invoice.get("billingAddress") or "").strip()


def _place(invoice):
    state = str(invoice.get("state") or invoice.get("shippingState") or "").strip()
    if state.casefold() in {"west bengal", "wb"}:
        return "West Bengal (19)"
    return state


def _logo(canvas, logo_bytes, box):
    if not logo_bytes:
        return False
    try:
        im = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        mw, mh = box[2] - box[0], box[3] - box[1]
        ratio = min(mw / im.width, mh / im.height)
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.LANCZOS)
        canvas.alpha_composite(im, (box[0] + (mw - im.width) // 2, box[1] + (mh - im.height) // 2))
        return True
    except Exception:
        return False


def _center(draw, value, font, y, fill=INK):
    bb = draw.textbbox((0, 0), value, font=font)
    draw.text(((BASE_W - (bb[2] - bb[0])) // 2, y), value, font=font, fill=fill)


def _scalloped_frame(canvas, y_bottom):
    """Draw the approved narrow white receipt with a thin neon-lime scalloped edge."""
    top = 24
    outer = Image.new("L", canvas.size, 0)
    od = ImageDraw.Draw(outer)

    # Base body, then outward scallop lobes on all four sides.
    od.rectangle((PAPER_X0 + 10, top + 10, PAPER_X1 - 10, y_bottom - 10), fill=255)
    lobe_r = 11
    step = 27
    for x in range(PAPER_X0 + 18, PAPER_X1 - 16, step):
        od.ellipse((x-lobe_r, top-lobe_r, x+lobe_r, top+lobe_r), fill=255)
        od.ellipse((x-lobe_r, y_bottom-lobe_r, x+lobe_r, y_bottom+lobe_r), fill=255)
    for y in range(top + 18, y_bottom - 16, step):
        od.ellipse((PAPER_X0-lobe_r, y-lobe_r, PAPER_X0+lobe_r, y+lobe_r), fill=255)
        od.ellipse((PAPER_X1-lobe_r, y-lobe_r, PAPER_X1+lobe_r, y+lobe_r), fill=255)

    # Restrained neon halo; the previous renderer blurred too broadly and became a thick block.
    broad = outer.filter(ImageFilter.GaussianBlur(10)).point(lambda a: int(a * .18))
    tight = outer.filter(ImageFilter.GaussianBlur(3)).point(lambda a: int(a * .34))
    glow_alpha = ImageChops.lighter(broad, tight)
    glow = Image.new("RGBA", canvas.size, LIME_STRONG + (0,))
    glow.putalpha(glow_alpha)
    canvas.alpha_composite(glow)

    lime = Image.new("RGBA", canvas.size, LIME_STRONG + (0,))
    lime.putalpha(outer)
    canvas.alpha_composite(lime)

    # White paper inset with its own scalloped boundary, leaving a thin lime edge.
    inset = 15
    inner = Image.new("L", canvas.size, 0)
    idraw = ImageDraw.Draw(inner)
    ix0, ix1 = PAPER_X0 + inset, PAPER_X1 - inset
    iy0, iy1 = top + inset, y_bottom - inset
    idraw.rectangle((ix0 + 8, iy0 + 8, ix1 - 8, iy1 - 8), fill=255)
    inner_r = 10
    for x in range(ix0 + 17, ix1 - 15, step):
        idraw.ellipse((x-inner_r, iy0-inner_r, x+inner_r, iy0+inner_r), fill=255)
        idraw.ellipse((x-inner_r, iy1-inner_r, x+inner_r, iy1+inner_r), fill=255)
    for y in range(iy0 + 17, iy1 - 15, step):
        idraw.ellipse((ix0-inner_r, y-inner_r, ix0+inner_r, y+inner_r), fill=255)
        idraw.ellipse((ix1-inner_r, y-inner_r, ix1+inner_r, y+inner_r), fill=255)

    paper = Image.new("RGBA", canvas.size, PAPER + (0,))
    paper.putalpha(inner)
    canvas.alpha_composite(paper)


def render(invoice, items, *, company, font_paths, logo_bytes, ist_strftime,
           canonical_status, amount_in_words, source_label, customer_id=""):
    extra_rows = max(0, len(items) - 2)
    height = BASE_H + extra_rows * 58
    paper_bottom = height - 60

    canvas = Image.new("RGBA", (BASE_W, height), (255, 255, 255, 0))
    _scalloped_frame(canvas, paper_bottom)
    draw = ImageDraw.Draw(canvas)

    regular = _font(font_paths, "regular", 20)
    semibold = _font(font_paths, "semibold", 20)
    bold = _font(font_paths, "bold", 24)
    small = _font(font_paths, "regular", 18)
    small_bold = _font(font_paths, "semibold", 18)
    fact_regular = _font(font_paths, "regular", 18)
    fact_semibold = _font(font_paths, "semibold", 15)
    trace_ref_font = _font(font_paths, "semibold", 13)
    title = _font(font_paths, "bold", 40)
    brand = _font(font_paths, "bold", 38)
    legal = _font(font_paths, "bold", 27)
    total_font = _font(font_paths, "bold", 42)
    footer_font = _font(font_paths, "bold", 38)
    symbol = "₹" if _draws(regular, "₹") else "Rs."

    raw_status = str(canonical_status(invoice.get("paymentStatus", "pending")) or "pending").upper()
    status = "PAID" if raw_status == "CAPTURED" else raw_status
    epoch = ((invoice.get("paidAt") if status == "PAID" else None)
             or invoice.get("createdAt") or invoice.get("invoiceDate") or 0)
    date_str = ist_strftime("%d-%m-%Y", epoch) if epoch else ""
    time_str = ist_strftime("%H:%M IST", epoch) if epoch else ""
    ref = str(invoice.get("referenceId") or "").strip()
    txn = str(invoice.get("providerPaymentId") or invoice.get("paymentId") or "").strip()
    buyer_gstin = _buyer_gstin(invoice, company.get("gstin"))
    address = _address(invoice)
    place = _place(invoice)
    customer_id = str(customer_id or "").strip()

    subtotal = Decimal(str(invoice.get("subtotal") or 0))
    discount = Decimal(str(invoice.get("discount") or 0))
    shipping = Decimal(str(invoice.get("shipping") or 0))
    handling = Decimal(str(invoice.get("handling") or 0))
    supply_tax = Decimal(str(invoice.get("tax") or 0))
    convenience_net = Decimal(str(invoice.get("convenienceFeeNet")
                                  if invoice.get("convenienceFeeNet") is not None
                                  else invoice.get("convenienceFee") or 0))
    convenience_gst = Decimal(str(invoice.get("convenienceFeeGst") or 0))
    total_gst = supply_tax + convenience_gst
    total = Decimal(str(invoice.get("total") or 0))

    # Brand lockup.
    _logo(canvas, logo_bytes, (355, 65, 465, 166))
    draw.text((472, 76), "WECARE", font=brand, fill=INK)
    wbb = draw.textbbox((0, 0), "WECARE", font=brand)
    draw.text((472 + wbb[2] - wbb[0], 76), ".", font=brand, fill=RED)
    draw.text((472, 116), "DIGITAL", font=brand, fill=INK)

    _center(draw, company.get("legal_name", "WECARE.DIGITAL BHARATWORKS"), legal, 178, INK)
    _center(draw, "W  E  C  A  R  E  .  D  I  G  I  T  A  L", small_bold, 207, INK)
    draw.line((248, 230, 777, 230), fill=LIME_STRONG, width=5)

    _center(draw, f"GSTIN: {company.get('gstin','')}   |   PAN: {company.get('pan','')}", small, 248)
    _center(draw, "The W.B.S.I.D.C. Building, Unit No. 1/20", small, 274)
    _center(draw, "81/2/7 Phears Lane, Kolkata, West Bengal - 700012, India", small, 299)
    _center(draw, f"{company.get('email','')}  •  {company.get('phone','')}  •  {company.get('website','')}",
            small, 324)

    draw.rounded_rectangle((157, 352, 867, 410), radius=12, fill=LIME_STRONG)
    _center(draw, "PAYMENT RECEIPT", title, 359, (0, 0, 0))

    # Receipt facts.
    fy = 430
    lx, lv = 164, 309
    rx, rv = 558, 682
    for label, value, yy, strong in (
        ("Receipt Ref:", ref, fy, True),
        ("Date:", date_str, fy + 32, False),
        ("Time:", time_str, fy + 64, False),
    ):
        draw.text((lx, yy), label, font=regular, fill=INK)
        value_font = fact_semibold if strong else fact_regular
        draw.text((lv, yy), value, font=value_font, fill=INK)

    draw.line((531, 429, 531, 510), fill=MUTED, width=2)
    draw.text((rx, fy), "Status:", font=regular, fill=INK)
    draw.rounded_rectangle((681, fy - 4, 778, fy + 27), radius=10,
                           fill=LIME_STRONG if status == "PAID" else PALE)
    sb = draw.textbbox((0, 0), status, font=semibold)
    draw.text((729 - (sb[2]-sb[0])//2, fy), status, font=semibold, fill=(0,0,0))
    draw.text((rx, fy + 32), "Channel:", font=regular, fill=INK)
    draw.text((rv, fy + 32), source_label, font=regular, fill=INK)
    draw.text((rx, fy + 64), "Txn:", font=regular, fill=INK)
    draw.text((rv, fy + 64), txn, font=regular, fill=INK)

    # Bill-to section.
    bill_y = 527
    draw.rounded_rectangle((157, bill_y, 867, bill_y + 36), radius=8, fill=PALE)
    draw.text((168, bill_y + 5), "BILL TO", font=bold, fill=INK)

    body_y = bill_y + 49
    draw.line((531, body_y - 3, 531, body_y + 126), fill=MUTED, width=2)
    ly = body_y
    for value, font in (
        (invoice.get("customerName") or "Customer", bold),
        (invoice.get("customerPhone") or "", regular),
        (invoice.get("customerEmail") or "", regular),
    ):
        if value:
            draw.text((164, ly), str(value), font=font, fill=INK)
            ly += 29

    if customer_id:
        draw.rounded_rectangle((158, ly - 2, 505, ly + 28), radius=9, fill=PALE)
        draw.text((166, ly + 2), "Customer ID:", font=small_bold, fill=INK)
        draw.text((309, ly + 2), customer_id, font=small_bold, fill=INK)
        ly += 34
    if buyer_gstin:
        draw.text((164, ly), f"Buyer GSTIN: {buyer_gstin}", font=small_bold, fill=INK)

    ay = body_y
    for line in _fit(draw, address, regular, 300, 3):
        draw.text((558, ay), line, font=regular, fill=INK)
        ay += 28
    if place:
        ptxt = f"Place of Supply: {place}"
        bb = draw.textbbox((0,0), ptxt, font=small_bold)
        draw.text((855-(bb[2]-bb[0]), bill_y + 130), ptxt, font=small_bold, fill=INK)

    # Item table.
    table_y = 738
    draw.rounded_rectangle((157, table_y, 867, table_y + 40), radius=8, fill=PALE)
    draw.text((173, table_y + 8), "#", font=small_bold, fill=INK)
    draw.text((238, table_y + 8), "DESCRIPTION", font=small_bold, fill=INK)
    draw.text((548, table_y + 8), "QTY", font=small_bold, fill=INK)
    draw.text((653, table_y + 8), "RATE", font=small_bold, fill=INK)
    draw.text((777, table_y + 8), "AMOUNT", font=small_bold, fill=INK)

    row_y = table_y + 54
    for idx, item in enumerate(items, 1):
        qty = int(item.get("quantity") or 1)
        unit = Decimal(str(item.get("amount") or 0))
        amount = unit * qty
        draw.text((177, row_y), str(idx), font=regular, fill=INK)
        name = str(item.get("name") or "Item")
        for line in _fit(draw, name, regular, 275, 1):
            draw.text((238, row_y), line, font=regular, fill=INK)
        draw.text((560, row_y), str(qty), font=regular, fill=INK)
        rate = _money(unit, symbol)
        amount_s = _money(amount, symbol)
        rb = draw.textbbox((0,0), rate, font=regular)
        ab = draw.textbbox((0,0), amount_s, font=regular)
        draw.text((710-(rb[2]-rb[0]), row_y), rate, font=regular, fill=INK)
        draw.text((854-(ab[2]-ab[0]), row_y), amount_s, font=regular, fill=INK)
        row_y += 42
        draw.line((168, row_y-8, 856, row_y-8), fill=LINE, width=1)

    totals_y = max(882, row_y + 2)
    val_x = 856

    def total_row(label, value, *, strong=False, band=False, green=False):
        nonlocal totals_y
        if band:
            draw.rounded_rectangle((158, totals_y-3, 866, totals_y+31), radius=7, fill=PALE)
        f = semibold if strong else regular
        draw.text((166, totals_y), label, font=f, fill=PAID_GREEN if green else INK)
        s = _money(value, symbol)
        bb = draw.textbbox((0,0), s, font=f)
        draw.text((val_x-(bb[2]-bb[0]), totals_y), s, font=f, fill=PAID_GREEN if green else INK)
        totals_y += 35

    total_row("Items Subtotal", subtotal)
    if discount:
        total_row("Delight", -discount)
    if shipping:
        total_row("Express", shipping)
    if handling:
        total_row("Handling", handling)
    if convenience_net:
        total_row("Convenience Fee", convenience_net)
    if total_gst:
        total_row("GST", total_gst, strong=True, band=True)

    hero_y = max(1068, totals_y + 1)
    draw.rounded_rectangle((157, hero_y, 867, hero_y + 65), radius=10, fill=LIME_STRONG)
    draw.text((169, hero_y + 12), "AMOUNT PAID" if status == "PAID" else "AMOUNT PAYABLE",
              font=bold, fill=(0,0,0))
    total_s = _money(total, symbol)
    tb = draw.textbbox((0,0), total_s, font=total_font)
    draw.text((853-(tb[2]-tb[0]), hero_y + 5), total_s, font=total_font, fill=(0,0,0))

    words_y = hero_y + 82
    words = amount_in_words(total)
    draw.text((166, words_y), words, font=regular, fill=INK)

    trace_y = words_y + 66
    if status == "PAID":
        stamp = Image.new("RGBA", (330, 126), (0,0,0,0))
        sd = ImageDraw.Draw(stamp)
        sd.rounded_rectangle((4, 4, 324, 120), radius=12, outline=PAID_GREEN, width=8)
        sd.ellipse((20, 34, 82, 96), fill=PAID_GREEN)
        sd.line((35, 64, 47, 78, 69, 50), fill=(255,255,255), width=7)
        stamp_word = _font(font_paths, "bold", 50)
        sd.text((100, 31), "PAID", font=stamp_word, fill=PAID_GREEN)
        stamp = stamp.rotate(7, resample=Image.Resampling.BICUBIC, expand=True)
        canvas.alpha_composite(stamp, (157, trace_y - 14))

    tx = 550
    ty = trace_y + 6
    for label, value in (
        ("Txn ID:", txn),
        ("Receipt Ref:", ref),
        ("Paid On:", (date_str + " " + time_str).strip()),
    ):
        if value:
            draw.text((tx, ty), label, font=small, fill=MUTED)
            value_font = trace_ref_font if label == "Receipt Ref:" else small_bold
            draw.text((684, ty), value, font=value_font, fill=INK)
            ty += 30

    footer_line_y = 1323 + extra_rows * 58
    draw.line((158, footer_line_y, 866, footer_line_y), fill=LIME_STRONG, width=5)
    ray_y = footer_line_y + 72
    for dx in (-145, 145):
        sign = -1 if dx < 0 else 1
        draw.line((BASE_W//2 + dx, ray_y, BASE_W//2 + dx + sign*18, ray_y-9),
                  fill=LIME_STRONG, width=4)
        draw.line((BASE_W//2 + dx + sign*3, ray_y+12,
                   BASE_W//2 + dx + sign*23, ray_y+12), fill=LIME_STRONG, width=4)
        draw.line((BASE_W//2 + dx + sign*2, ray_y+25,
                   BASE_W//2 + dx + sign*17, ray_y+34), fill=LIME_STRONG, width=4)
    _center(draw, "Thank You!", footer_font, footer_line_y + 22, (0,0,0))
    _center(draw, "V I S I T   A G A I N", small_bold, footer_line_y + 61, (0,0,0))
    _center(draw, company.get("website", "https://wecare.digital"), semibold,
            footer_line_y + 94, PAID_GREEN)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
