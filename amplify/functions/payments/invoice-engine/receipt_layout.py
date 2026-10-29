"""WECARE.DIGITAL customer PAYMENT RECEIPT v14.

Fixed-coordinate B2C renderer mapped to the owner-approved 1024 x 1536 reference receipt.
The final paper treatment is transparent outside the receipt, with a thin neutral border and
small receipt-cut zig-zags on all four sides, matching the approved owner mock.
Content the reference does not contain (more item lines, more or fewer totals rows, a second
amount-in-words line) moves everything below it instead of overlapping, so the canvas height
follows the content; the two-line specimen is exactly 1024 x 1536. Long values shrink to fit
their column before they are ellipsized.

Authority: presentation only. It renders the persisted invoice facts it is given and never
calculates, rounds or changes a charge; pricing belongs to ``checkout_pricing``. There is no
legacy or alternate layout here, by design.
"""
from __future__ import annotations

import io
import math
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ─── Palette (sampled from the reference) ─────────────────────────────────────────────────────
INK = (10, 12, 16)
HEAD = (0, 0, 0)
PAPER = (252, 252, 251)
BAR = (195, 246, 34)           # PAYMENT RECEIPT bar, PAID pill, AMOUNT PAID bar
RULE = (196, 251, 15)          # masthead underline
FOOTER_RULE = (189, 243, 12)
RAY = (192, 249, 12)
PALE = (225, 239, 219)         # BILL TO bar, Customer ID pills, item header
DIVIDER = (150, 153, 163)
DOTS = (208, 211, 216)         # dotted row separators
TAX_SEPARATOR = (130, 130, 142)
WEB_GREEN = (8, 118, 16)
RED = (255, 0, 64)             # brand dot, #ff0040 as in BrandLockup

BASE_W = 1024

# ─── Final paper geometry ──────────────────────────────────────────────────────────────────────
PAPER_LEFT = 122.0
PAPER_RIGHT = 902.0
PAPER_TOP = 25.0
FRAME_BOTTOM_BELOW_HERO = 400.5
CANVAS_BELOW_HERO = 468
EDGE_TOOTH_DEPTH = 8.0
EDGE_TOOTH_HALF_STEP = 15.0
BORDER = (100, 105, 112)
BORDER_WIDTH = 1.6
SHADOW = (35, 39, 45)
SHADOW_RADIUS = 8.0
SHADOW_ALPHA = 0.18

# ─── Columns ──────────────────────────────────────────────────────────────────────────────────
BAR_X0, BAR_X1 = 158, 867         # full-width bars (left edge, exclusive right edge)
LEFT_X = 164                      # facts / bill-to left column text
FACT_VALUE_X = 309
SIDE_LABEL_X = 558
SIDE_VALUE_X = 683
COLUMN_DIVIDER_X = 530.5
ADDRESS_X = 557
TEXT_RIGHT = 868                  # last ink column any value may reach

# ─── Type roles: (face, size px, synthetic-weight stroke px, tracking px) ─────────────────────
# Inter Regular/SemiBold/Bold are the only faces in the invoice font prefix; the reference's
# heavier display weight is reproduced with a 1 px stroke on Inter Bold.
TYPE: dict[str, tuple[str, float, int, float]] = {
    "wordmark": ("bold", 42.4, 1, 0.0),
    "legal": ("bold", 27.0, 0, 0.0),
    "tagline": ("regular", 17.4, 0, 7.5),
    "seller": ("regular", 18.6, 0, 0.0),
    "seller_tax": ("regular", 19.6, 0, 0.0),
    "seller_contact": ("regular", 19.0, 0, 0.0),
    "title": ("bold", 43.2, 1, 0.0),
    "fact_label": ("regular", 19.7, 0, 0.0),
    "fact_value": ("regular", 20.2, 0, 0.0),
    "fact_ref": ("bold", 18.7, 0, 0.0),
    "fact_side": ("regular", 19.2, 0, 0.0),
    "pill": ("bold", 22.4, 0, 0.0),
    "section": ("bold", 22.0, 0, 0.0),
    "name": ("semibold", 24.2, 0, 0.0),
    "contact": ("regular", 22.0, 0, 0.0),
    "customer_label": ("bold", 19.0, 0, 0.0),
    "customer_value": ("semibold", 20.0, 0, 0.0),
    "address": ("regular", 18.5, 0, 0.0),
    "place_label": ("regular", 17.8, 0, 0.0),
    "place_value": ("bold", 19.4, 0, 0.0),
    "table_head": ("semibold", 20.0, 0, 0.0),
    "row_index": ("semibold", 20.4, 0, 0.0),
    "row": ("regular", 20.4, 0, 0.0),
    "total": ("regular", 21.2, 0, 0.0),
    "amount_label": ("bold", 38.2, 1, 0.0),
    "amount_value": ("bold", 42.2, 1, 0.0),
    "words": ("regular", 19.5, 0, 0.0),
    "trace_label": ("regular", 18.0, 0, 0.0),
    "trace_value": ("regular", 18.4, 0, 0.0),
    "thanks": ("bold", 39.0, 1, 0.0),
    "visit": ("semibold", 19.8, 0, 5.5),
    "website": ("semibold", 21.4, 0, 0.0),
}

# ─── Vertical rhythm (baselines in px) ────────────────────────────────────────────────────────
FACT_BASELINES = (445.0, 476.0, 506.0)
BILL_FIRST_BASELINE = 594.0
# Distance into each left bill-to line from the previous printed one (reference spacing).
BILL_PITCH = {"phone": 30.0, "email": 28.0, "customer": 31.5}
ADDRESS_BASELINES = (597.0, 625.0, 653.0, 681.0)
PLACE_BASELINE = 685.5
PLACE_BASELINE_LOW = 715.0        # only when the address needs a fourth line
ROW_FIRST_BASELINE = 807.5
ROW_PITCH = 42.0
TOTALS_GAP = 48.9                 # last item baseline -> first totals baseline
TOTAL_PITCH = 37.1
HERO_GAP = 21.2                   # last totals baseline -> AMOUNT PAID bar top
WORDS_LINE = 25.0

# ─── Masthead mark ─────────────────────────────────────────────────────────────────────────────
LOGO_BOX = (365, 71, 448, 164)    # ink box of the bag mark in the reference

class _Fonts:
    """Per-render font cache; each face falls back to regular, then Pillow's default face."""

    def __init__(self, font_paths: Mapping[str, Any]):
        self._paths = font_paths
        self._cache: dict[tuple[str, float], Any] = {}

    def get(self, face: str, size: float) -> Any:
        key = (face, size)
        if key not in self._cache:
            self._cache[key] = self._load(face, size)
        return self._cache[key]

    def role(self, name: str) -> Any:
        face, size, _stroke, _tracking = TYPE[name]
        return self.get(face, size)

    def _load(self, face: str, size: float) -> Any:
        for choice in (self._paths.get(face), self._paths.get("regular")):
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


# ─── Text ─────────────────────────────────────────────────────────────────────────────────────
def _money(value: Any, symbol: str = "₹", minus: str = "−") -> str:
    amount = Decimal(str(value if value is not None else 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = minus if amount < 0 else ""
    return sign + symbol + format(abs(amount), ",.2f")


def _draws(font: Any, char: str) -> bool:
    try:
        return bytes(font.getmask(char)) != bytes(font.getmask("\uffff"))
    except Exception:
        return False


def _advance(font: Any, text: str, tracking: float = 0.0) -> float:
    if not text:
        return 0.0
    if not tracking:
        return float(font.getlength(text))
    return sum(float(font.getlength(ch)) for ch in text) + tracking * (len(text) - 1)


def _ellipsize(font: Any, text: str, max_w: float, tracking: float = 0.0) -> str:
    if _advance(font, text, tracking) <= max_w:
        return text
    while text and _advance(font, text + "…", tracking) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(font: Any, value: str, max_w: float, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in str(value or "").split():
        candidate = (current + " " + word).strip()
        if current and _advance(font, candidate) > max_w:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(font, lines[-1] + "…", max_w)
    return [_ellipsize(font, line, max_w) for line in lines]


class _Writer:
    """Places text by left/right/centre anchor on a baseline, shrinking long values to fit."""

    def __init__(self, draw: ImageDraw.ImageDraw, fonts: _Fonts):
        self.draw = draw
        self.fonts = fonts

    def put(self, role: str, text: Any, x: float, baseline: float, *, align: str = "left",
            fill: tuple[int, int, int] = INK, max_w: float | None = None,
            min_size: float | None = None) -> float:
        """Draw `text` in `role`; with `max_w`, step the size down to `min_size`, then ellipsize.
        Returns the drawn advance width."""
        text = str(text or "")
        if not text:
            return 0.0
        face, size, stroke, tracking = TYPE[role]
        font = self.fonts.get(face, size)
        if max_w is not None:
            floor = min_size if min_size is not None else size
            while _advance(font, text, tracking) > max_w and size - 0.5 >= floor:
                size -= 0.5
                font = self.fonts.get(face, size)
            text = _ellipsize(font, text, max_w, tracking)
        width = _advance(font, text, tracking)
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        if tracking:
            for ch in text:
                self.draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls",
                               stroke_width=stroke, stroke_fill=fill)
                x += float(font.getlength(ch)) + tracking
        else:
            self.draw.text((x, baseline), text, font=font, fill=fill, anchor="ls",
                           stroke_width=stroke, stroke_fill=fill)
        return width

    def width(self, role: str, text: str) -> float:
        face, size, _stroke, tracking = TYPE[role]
        return _advance(self.fonts.get(face, size), text, tracking)


# ─── Anti-aliased shapes ──────────────────────────────────────────────────────────────────────
def _paint(canvas: Image.Image, bounds: tuple[float, float, float, float],
           fill: tuple[int, int, int], paint: Callable[[ImageDraw.ImageDraw, Callable], None],
           ss: int = 4) -> None:
    """Rasterise one shape at `ss`x into a local mask, downsample it and composite `fill`."""
    x0 = max(0, int(math.floor(bounds[0])) - 2)
    y0 = max(0, int(math.floor(bounds[1])) - 2)
    x1 = min(canvas.width, int(math.ceil(bounds[2])) + 2)
    y1 = min(canvas.height, int(math.ceil(bounds[3])) + 2)
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)

    def at(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * ss, (y - y0) * ss

    paint(ImageDraw.Draw(mask), at)
    mask = mask.resize((x1 - x0, y1 - y0), Image.Resampling.BOX)
    layer = Image.new("RGBA", mask.size, fill + (0,))
    layer.putalpha(mask)
    canvas.alpha_composite(layer, (x0, y0))


def _round_rect(canvas: Image.Image, box: tuple[float, float, float, float], radius: float,
                fill: tuple[int, int, int]) -> None:
    """`box` is (left, top, right, bottom) pixel edges; right/bottom are exclusive."""
    def paint(d: ImageDraw.ImageDraw, at: Callable) -> None:
        ax, ay = at(box[0], box[1])
        bx, by = at(box[2], box[3])
        d.rounded_rectangle((ax, ay, bx - 1, by - 1), radius=radius * 4, fill=255)
    _paint(canvas, box, fill, paint)


def _stroke(canvas: Image.Image, points: Sequence[tuple[float, float]], width: float,
            fill: tuple[int, int, int]) -> None:
    """Polyline with round caps and joints."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bounds = (min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width)

    def paint(d: ImageDraw.ImageDraw, at: Callable) -> None:
        scaled = [at(x, y) for x, y in points]
        d.line(scaled, fill=255, width=max(1, round(width * 4)), joint="curve")
        r = width * 2
        for cx, cy in (scaled[0], scaled[-1]):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    _paint(canvas, bounds, fill, paint)


def _disc(canvas: Image.Image, cx: float, cy: float, r: float, fill: tuple[int, int, int]) -> None:
    def paint(d: ImageDraw.ImageDraw, at: Callable) -> None:
        ax, ay = at(cx - r, cy - r)
        bx, by = at(cx + r, cy + r)
        d.ellipse((ax, ay, bx, by), fill=255)
    _paint(canvas, (cx - r, cy - r, cx + r, cy + r), fill, paint)


def _dotted_rule(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    """The reference separator: 2 px dots on a 4 px pitch, one pixel high."""
    for x in range(x0, x1, 4):
        draw.line((x, y, min(x + 1, x1), y), fill=DOTS, width=1)


# ─── Paper frame ───────────────────────────────────────────────────────────────────────────────
def _paper_polygon(bottom: float) -> list[tuple[float, float]]:
    """Approved silhouette: small, even receipt-cut zig-zags on all four sides."""
    x0, x1 = PAPER_LEFT, PAPER_RIGHT
    y0, y1 = PAPER_TOP, bottom
    amp = EDGE_TOOTH_DEPTH
    step = EDGE_TOOTH_HALF_STEP
    pts: list[tuple[float, float]] = []

    # Top edge.
    x = x0
    pts.append((x0, y0))
    flip = 0
    while x + step < x1:
        x += step
        pts.append((x, y0 + (-amp if flip % 2 == 0 else amp)))
        flip += 1
    pts.append((x1, y0))

    # Right edge.
    y = y0
    flip = 0
    while y + step < y1:
        y += step
        pts.append((x1 + (amp if flip % 2 == 0 else -amp), y))
        flip += 1
    pts.append((x1, y1))

    # Bottom edge.
    x = x1
    flip = 0
    while x - step > x0:
        x -= step
        pts.append((x, y1 + (amp if flip % 2 == 0 else -amp)))
        flip += 1
    pts.append((x0, y1))

    # Left edge.
    y = y1
    flip = 0
    while y - step > y0:
        y -= step
        pts.append((x0 + (-amp if flip % 2 == 0 else amp), y))
        flip += 1

    return pts

def _frame(canvas: Image.Image, bottom: float) -> None:
    """Transparent exterior, white paper, subtle neutral shadow, and thin grey outline.

    No lime exterior frame or glow. Lime remains an internal brand accent only.
    """
    w, h = canvas.size
    ss = 4
    pts = _paper_polygon(bottom)
    scaled = [(round(x * ss), round(y * ss)) for x, y in pts]

    paper_mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(paper_mask).polygon(scaled, fill=255)
    paper_mask = paper_mask.resize((w, h), Image.Resampling.LANCZOS)

    # Neutral shadow on transparency, never a coloured halo.
    shadow = paper_mask.filter(ImageFilter.GaussianBlur(SHADOW_RADIUS))
    shadow = shadow.point(lambda v: min(255, round(v * SHADOW_ALPHA)))
    shadow_layer = Image.new("RGBA", (w, h), SHADOW + (0,))
    shadow_layer.putalpha(shadow)
    canvas.alpha_composite(shadow_layer, (2, 3))

    paper_layer = Image.new("RGBA", (w, h), PAPER + (0,))
    paper_layer.putalpha(paper_mask)
    canvas.alpha_composite(paper_layer)

    # Thin neutral border follows the approved zig-zag silhouette on all four sides.
    border_mask = Image.new("L", (w * ss, h * ss), 0)
    bd = ImageDraw.Draw(border_mask)
    bd.line(scaled + [scaled[0]], fill=255, width=max(1, round(BORDER_WIDTH * ss)), joint="curve")
    border_mask = border_mask.resize((w, h), Image.Resampling.LANCZOS)
    border_layer = Image.new("RGBA", (w, h), BORDER + (0,))
    border_layer.putalpha(border_mask)
    canvas.alpha_composite(border_layer)

def _logo(canvas: Image.Image, logo_bytes: bytes | None) -> bool:
    """Fit the immutable receipt bag mark (trimmed to its ink) into the reference ink box."""
    if not logo_bytes:
        return False
    try:
        im = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        bbox = im.getchannel("A").getbbox()
        if bbox:
            im = im.crop(bbox)
        box_w, box_h = LOGO_BOX[2] - LOGO_BOX[0], LOGO_BOX[3] - LOGO_BOX[1]
        scale = min(box_w / im.width, box_h / im.height)
        size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        im = im.resize(size, Image.Resampling.LANCZOS)
        cx = (LOGO_BOX[0] + LOGO_BOX[2]) / 2
        cy = (LOGO_BOX[1] + LOGO_BOX[3]) / 2
        canvas.alpha_composite(im, (round(cx - size[0] / 2), round(cy - size[1] / 2)))
        return True
    except Exception:
        return False



# ─── Field formatting ─────────────────────────────────────────────────────────────────────────
def _place(invoice: Mapping[str, Any]) -> str:
    state = str(invoice.get("state") or invoice.get("shippingState") or "").strip()
    if state.casefold() in {"west bengal", "wb"}:
        return "West Bengal (19)"
    return state


def _display_phone(value: Any) -> str:
    """Group a stored Indian mobile as +91 XXXXX XXXXX; anything else prints as stored."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91") and raw.startswith(("+", "9")):
        return f"+91 {digits[2:7]} {digits[7:]}"
    return raw


def _seller_address(company: Mapping[str, Any]) -> list[str]:
    """Seller address from `business_identity`: '<building>, <unit>' / '<street>, … India'."""
    parts = [part.strip() for part in str(company.get("address") or "").split(",") if part.strip()]
    if len(parts) >= 4:
        return [", ".join(parts[:2]), ", ".join(parts[2:])]
    return [", ".join(parts)] if parts else []


def _address_parts(invoice: Mapping[str, Any]) -> list[str]:
    """Reference form: '<line 1>,' then '<line 2>, <city> – <PIN>, India'. The state is printed
    as Place of Supply, so it is not repeated. A free-text address is used as stored."""
    line1 = str(invoice.get("addressLine1") or "").strip().rstrip(",")
    line2 = str(invoice.get("addressLine2") or "").strip().rstrip(",")
    city = str(invoice.get("city") or "").strip().rstrip(",")
    pin = str(invoice.get("postalCode") or "").strip()
    if not (line1 or line2 or city or pin):
        free = str(invoice.get("shippingAddress") or invoice.get("billingAddress") or "").strip()
        return [free] if free else []
    tail = ", ".join(part for part in (line2, city) if part)
    if pin:
        tail = f"{tail} – {pin}" if tail else pin
        if re.fullmatch(r"\d{6}", pin):
            tail += ", India"
    if line1 and tail:
        return [line1 + ",", tail]
    return [line1 or tail]


def _address_lines(fonts: _Fonts, invoice: Mapping[str, Any], max_w: float,
                   max_lines: int) -> tuple[list[str], float]:
    """Wrap the customer address into the right column: the reference's break after line 1
    first, then one continuous wrap, then a smaller size; truncate only as a last resort."""
    parts = _address_parts(invoice)
    face, size, _stroke, _tracking = TYPE["address"]
    while True:
        font = fonts.get(face, size)
        lines = [line for part in parts for line in _wrap(font, part, max_w, max_lines + 1)]
        if len(lines) > max_lines and len(parts) > 1:
            lines = _wrap(font, " ".join(parts), max_w, max_lines + 1)
        if len(lines) <= max_lines or size <= 15.5:
            break
        size -= 0.5
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(font, lines[-1] + "…", max_w)
    return lines, size


def _contact_line(canvas: Image.Image, put: _Writer, company: Mapping[str, Any]) -> None:
    """email • phone • website on the reference's bullet positions. If an identity value no
    longer fits its slot, fall back to one centred, evenly spaced run."""
    parts = [str(company.get(k) or "").strip() for k in ("email", "phone", "website")]
    widths = [put.width("seller_contact", part) for part in parts]
    if all(parts) and widths[0] <= 244 and widths[1] <= 167 and widths[2] <= TEXT_RIGHT - 613:
        put.put("seller_contact", parts[0], 394, 336, align="right")
        put.put("seller_contact", parts[1], 503, 336, align="center")
        put.put("seller_contact", parts[2], 613, 336)
        for cx in (410.0, 597.0):
            _disc(canvas, cx, 329.5, 2.5, INK)
        return
    present = [(part, width) for part, width in zip(parts, widths) if part]
    gap, dot = 16.0, 5.0
    total_w = sum(width for _, width in present) + max(0, len(present) - 1) * (2 * gap + dot)
    x = 510.5 - total_w / 2
    for i, (part, width) in enumerate(present):
        put.put("seller_contact", part, x, 336)
        x += width
        if i < len(present) - 1:
            _disc(canvas, x + gap + dot / 2, 329.5, dot / 2, INK)
            x += 2 * gap + dot


# ─── Renderer ─────────────────────────────────────────────────────────────────────────────────
def render(invoice: Mapping[str, Any], items: Sequence[Mapping[str, Any]], *,
           company: Mapping[str, Any], font_paths: Mapping[str, Any], logo_bytes: bytes | None,
           ist_strftime: Callable[[str, Any], str], canonical_status: Callable[[Any], Any],
           amount_in_words: Callable[[Decimal], str], source_label: str,
           customer_id: str = "") -> bytes:
    """Render the customer PAYMENT RECEIPT PNG from stored invoice facts."""
    fonts = _Fonts(font_paths)
    symbol = "₹" if _draws(fonts.role("row"), "₹") else "Rs."
    minus = "−" if _draws(fonts.role("total"), "−") else "-"

    raw_status = str(canonical_status(invoice.get("paymentStatus", "pending")) or "pending").upper()
    status = "PAID" if raw_status == "CAPTURED" else raw_status
    paid = status == "PAID"
    epoch = ((invoice.get("paidAt") if paid else None)
             or invoice.get("createdAt") or invoice.get("invoiceDate") or 0)
    date_str = ist_strftime("%d-%m-%Y", epoch) if epoch else ""
    time_str = ist_strftime("%H:%M IST", epoch) if epoch else ""
    ref = str(invoice.get("referenceId") or "").strip()
    txn = str(invoice.get("providerPaymentId") or invoice.get("paymentId") or "").strip()
    seller_gstin = str(company.get("gstin") or "").strip()
    place = _place(invoice)
    customer_id = str(customer_id or "").strip()

    def amount(key: str) -> Decimal:
        return Decimal(str(invoice.get(key) or 0))

    subtotal = amount("subtotal")
    discount = amount("discount")
    shipping = amount("shipping")
    handling = amount("handling")
    supply_tax = amount("tax")
    convenience_net = Decimal(str(invoice.get("convenienceFeeNet")
                                  if invoice.get("convenienceFeeNet") is not None
                                  else invoice.get("convenienceFee") or 0))
    convenience_gst = amount("convenienceFeeGst")
    total_gst = supply_tax + convenience_gst
    total = amount("total")

    totals: list[tuple[str, Decimal]] = [("Items Subtotal", subtotal)]
    if discount:
        totals.append(("Delight", -discount))
    if shipping:
        totals.append(("Express", shipping))
    if handling:
        totals.append(("Handling", handling))
    if convenience_net:
        totals.append(("Convenience Fee", convenience_net))
    if total_gst:
        # One compact tax row labelled with the seller GSTIN, as on the approved reference.
        totals.append((seller_gstin or "GST", total_gst))

    words_lines = _wrap(fonts.role("words"), amount_in_words(total), TEXT_RIGHT - 166, 2)

    # Vertical layout: everything below the item table follows the content above it.
    row_baselines = [ROW_FIRST_BASELINE + i * ROW_PITCH for i in range(len(items))]
    last_row = row_baselines[-1] if row_baselines else ROW_FIRST_BASELINE - ROW_PITCH
    total_baselines = [last_row + TOTALS_GAP + i * TOTAL_PITCH for i in range(len(totals))]
    hero = round(total_baselines[-1] + HERO_GAP)
    low = hero + WORDS_LINE * max(0, len(words_lines) - 1)
    height = math.ceil(low + CANVAS_BELOW_HERO)

    canvas = Image.new("RGBA", (BASE_W, height), (255, 255, 255, 0))
    _frame(canvas, low + FRAME_BOTTOM_BELOW_HERO)
    draw = ImageDraw.Draw(canvas)
    put = _Writer(draw, fonts)

    # Masthead.
    _logo(canvas, logo_bytes)
    wordmark_w = put.put("wordmark", "WECARE", 470, 120, fill=HEAD)
    _disc(canvas, 470 + wordmark_w + 7.5, 114.5, 4.5, RED)
    put.put("wordmark", "DIGITAL", 472, 160, fill=HEAD)
    put.put("legal", company.get("legal_name") or "WECARE.DIGITAL BHARATWORKS", 513, 197,
            align="center", fill=HEAD, max_w=640, min_size=20)
    put.put("tagline", company.get("name") or "WECARE.DIGITAL", 513.25, 220, align="center")
    _stroke(canvas, [(249.5, 231.5), (774.5, 231.5)], 5, RULE)

    tax_left = f"GSTIN: {seller_gstin}" if seller_gstin else ""
    tax_right = f"PAN: {company.get('pan')}" if company.get("pan") else ""
    if tax_left and tax_right:
        lw, rw = put.width("seller_tax", tax_left), put.width("seller_tax", tax_right)
        start = 511.5 - (lw + 47 + rw) / 2
        put.put("seller_tax", tax_left, start, 265)
        _stroke(canvas, [(start + lw + 23.5, 249), (start + lw + 23.5, 266)], 2, TAX_SEPARATOR)
        put.put("seller_tax", tax_right, start + lw + 47, 265)
    elif tax_left or tax_right:
        put.put("seller_tax", tax_left or tax_right, 511.5, 265, align="center")
    for line, baseline in zip(_seller_address(company), (288.0, 312.0)):
        put.put("seller", line, 512, baseline, align="center", max_w=680, min_size=15)
    _contact_line(canvas, put, company)

    # Title bar.
    _round_rect(canvas, (BAR_X0, 352, BAR_X1, 410), 10, BAR)
    put.put("title", "PAYMENT RECEIPT", 513.5, 399, align="center", fill=HEAD)

    # Receipt facts. The full reference is printed (owner decision) and shrinks to its column.
    ref_max = COLUMN_DIVIDER_X - 12 - FACT_VALUE_X
    for (label, value, role), baseline in zip(
            (("Receipt Ref:", ref, "fact_ref"), ("Date:", date_str, "fact_value"),
             ("Time:", time_str, "fact_value")), FACT_BASELINES):
        put.put("fact_label", label, LEFT_X, baseline)
        put.put(role, value, FACT_VALUE_X, baseline, max_w=ref_max, min_size=13)
    _stroke(canvas, [(COLUMN_DIVIDER_X, 430), (COLUMN_DIVIDER_X, 510)], 2, DIVIDER)

    put.put("fact_label", "Status:", SIDE_LABEL_X, FACT_BASELINES[0])
    pill_w = max(97.0, put.width("pill", status) + 46)
    _round_rect(canvas, (680, 424, 680 + pill_w, 454), 8, BAR if paid else PALE)
    put.put("pill", status, 680 + pill_w / 2 - 2, 448, align="center", fill=HEAD)
    side_max = TEXT_RIGHT - SIDE_VALUE_X
    put.put("fact_label", "Channel:", SIDE_LABEL_X, FACT_BASELINES[1])
    put.put("fact_side", source_label, SIDE_VALUE_X, FACT_BASELINES[1], max_w=side_max,
            min_size=14)
    put.put("fact_label", "Txn:", SIDE_LABEL_X, FACT_BASELINES[2])
    put.put("fact_side", txn, SIDE_VALUE_X, FACT_BASELINES[2], max_w=side_max, min_size=13)

    # Bill to: left column stacks the lines that exist, right column holds the address.
    _round_rect(canvas, (BAR_X0, 526, BAR_X1, 562), 8, PALE)
    put.put("section", "BILL TO", 169, 554, fill=HEAD)
    left_max = COLUMN_DIVIDER_X - 14 - LEFT_X
    baseline = BILL_FIRST_BASELINE
    put.put("name", invoice.get("customerName") or "Customer", LEFT_X, baseline, fill=HEAD,
            max_w=left_max, min_size=17)
    for key, value in (("phone", _display_phone(invoice.get("customerPhone"))),
                       ("email", str(invoice.get("customerEmail") or "").strip())):
        if value:
            baseline += BILL_PITCH[key]
            put.put("contact", value, LEFT_X, baseline, max_w=left_max, min_size=15)
    if customer_id:
        baseline += BILL_PITCH["customer"]
        _round_rect(canvas, (158, baseline - 23.5, 298, baseline + 9.5), 7, PALE)
        _round_rect(canvas, (302, baseline - 23.5, 512, baseline + 9.5), 7, PALE)
        put.put("customer_label", "Customer ID:", 168, baseline, fill=HEAD)
        put.put("customer_value", customer_id, 312, baseline + 0.5, fill=HEAD, max_w=192,
                min_size=14)
    _stroke(canvas, [(COLUMN_DIVIDER_X, 580), (COLUMN_DIVIDER_X, 678)], 2, DIVIDER)

    address, address_size = _address_lines(fonts, invoice, TEXT_RIGHT - ADDRESS_X,
                                           len(ADDRESS_BASELINES))
    address_font = fonts.get(TYPE["address"][0], address_size)
    for line, line_baseline in zip(address, ADDRESS_BASELINES):
        draw.text((ADDRESS_X, line_baseline), line, font=address_font, fill=INK, anchor="ls")
    if place:
        place_baseline = (PLACE_BASELINE if len(address) < len(ADDRESS_BASELINES)
                          else PLACE_BASELINE_LOW)
        put.put("place_label", "Place of Supply:", ADDRESS_X, place_baseline)
        put.put("place_value", place, 698, place_baseline, fill=HEAD,
                max_w=TEXT_RIGHT - 698, min_size=14)

    # Item table.
    _round_rect(canvas, (BAR_X0, 737, BAR_X1, 775), 8, PALE)
    for label, x, align in (("#", 178, "left"), ("DESCRIPTION", 239, "left"),
                            ("QTY", 548, "left"), ("RATE", 654, "left"),
                            ("AMOUNT", 862, "right")):
        put.put("table_head", label, x, 765.5, align=align, fill=HEAD)
    for index, (item, row_baseline) in enumerate(zip(items, row_baselines), 1):
        qty = int(item.get("quantity") or 1)
        unit = Decimal(str(item.get("amount") or 0))
        put.put("row_index", str(index), 179, row_baseline, fill=HEAD)
        put.put("row", str(item.get("name") or "Item"), 240, row_baseline, max_w=292,
                min_size=18)
        put.put("row", str(qty), 566, row_baseline, align="center")
        put.put("row", _money(unit, symbol, minus), 709, row_baseline, align="right")
        put.put("row", _money(unit * qty, symbol, minus), 861, row_baseline, align="right",
                max_w=140, min_size=14)
        _dotted_rule(draw, 163, 862, int(row_baseline + 12))

    # Totals.
    for i, ((label, value), total_baseline) in enumerate(zip(totals, total_baselines)):
        put.put("total", label, 169, total_baseline, max_w=420, min_size=15)
        put.put("total", _money(value, symbol, minus), 861, total_baseline, align="right")
        if i < len(totals) - 1:
            _dotted_rule(draw, 167, 862, int(total_baseline + 8))

    # Amount paid.
    _round_rect(canvas, (BAR_X0, hero, BAR_X1, hero + 64), 10, BAR)
    label_w = put.put("amount_label", "AMOUNT PAID" if paid else "AMOUNT PAYABLE", 172,
                      hero + 48, fill=HEAD)
    put.put("amount_value", _money(total, symbol, minus), 855, hero + 50, align="right",
            fill=HEAD, max_w=855 - (172 + label_w + 24), min_size=24)
    for i, line in enumerate(words_lines):
        put.put("words", line, 166, hero + 96 + i * WORDS_LINE)

    # Transaction trace block. The payment state is shown once above in Status.
    # No duplicate PAID stamp/footer mark is rendered.
    _stroke(canvas, [(515.3, low + 131), (515.3, low + 228)], 2, DIVIDER)
    trace = [("Txn ID:", txn), ("Receipt Ref:", ref)]
    if paid:
        trace.append(("Paid On:", (date_str + " " + time_str).strip()))
    for (label, value), offset in zip(trace, (158.0, 188.5, 219.5)):
        if value:
            put.put("trace_label", label, 551, low + offset)
            put.put("trace_value", value, SIDE_VALUE_X, low + offset,
                    max_w=TEXT_RIGHT - SIDE_VALUE_X, min_size=12)

    # Footer.
    _stroke(canvas, [(162, low + 257.5), (862, low + 257.5)], 6, FOOTER_RULE)
    put.put("thanks", "Thank You!", 511, low + 308, align="center", fill=HEAD)
    put.put("visit", "VISIT AGAIN", 512.5, low + 336, align="center", fill=HEAD)
    put.put("website", company.get("website") or "https://wecare.digital", 512, low + 365,
            align="center", fill=WEB_GREEN)
    for (ax, ay), (bx, by) in (((380.0, 308.0), (395.8, 316.8)),
                               ((372.3, 335.2), (388.8, 330.8))):
        _stroke(canvas, [(ax, low + ay), (bx, low + by)], 6, RAY)
        _stroke(canvas, [(1023 - ax, low + ay), (1023 - bx, low + by)], 6, RAY)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
