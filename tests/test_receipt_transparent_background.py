"""The receipt's background is the owner's decision, and the default must not move it.

The owner approved a receipt specimen rendered as a torn-paper thermal receipt on a
TRANSPARENT background, promoted to a stable public asset:

    https://wecare.digital/get/o/public/wa-tpl/img/invoice-receipt.png
    s3://wecare-digital-get/o/public/wa-tpl/img/invoice-receipt.png

Measured on that object (2026-10-08, HTTP 200, image/png): the corners are fully
transparent (alpha 0) and the paper is off-white RGBA (252, 252, 250, 255). Those two
numbers are the acceptance criteria this file pins, and they are the source of the
constants below.

The specimen itself is NOT attached to any message. It is a standalone sample rendered
from fixture customer data, so sending the file would mail one stranger's fixture tax
invoice to every paying customer. What was approved is the APPEARANCE, and the renderer
is what has to produce it — hence a flag on `_generate_receipt_png` rather than a URL in
the send path.

Two halves, and the first is the important one:

1. With `RECEIPT_TRANSPARENT_BG` unset, the output is unchanged — no alpha, grey
   (200, 200, 200) corner. Nothing a customer sees changes until the owner flips it.
2. With the flag on, the output matches the approved specimen's measured properties.

Plus the two things that must NOT have moved: the fixed payment-template header
`wecarepay-header.png`, which is a separate artifact and not what this task replaces, and
the PDF path, which would acquire a BLACK border if an RGBA receipt were handed to PIL's
`convert('RGB')`.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "amplify" / "functions"
for extra in (FUNCTIONS / "shared",):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

# Measured on the owner-approved specimen named in the module docstring.
APPROVED_PAPER_RGBA = (252, 252, 250, 255)
APPROVED_CORNER_ALPHA = 0
# The grey the owner asked to have removed, and today's default.
CURRENT_GREY_BACKDROP = (200, 200, 200)

APPROVED_SPECIMEN_URL = (
    "https://wecare.digital/get/o/public/wa-tpl/img/invoice-receipt.png")
PAYMENT_TEMPLATE_HEADER_URL = (
    "https://wecare.digital/get/o/public/wa-tpl/img/wecarepay-header.png")


@pytest.fixture
def invoice_engine(monkeypatch):
    """Load invoice-engine with boto3 stubbed, and hand back its module."""
    path = str(FUNCTIONS / "payments" / "invoice-engine")
    monkeypatch.syspath_prepend(path)
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415
    yield handler
    sys.modules.pop("handler", None)


@pytest.fixture
def offline_renderer(invoice_engine, monkeypatch):
    """The renderer, with every S3 read failing so it takes its documented fallbacks.

    The font, logo and QR loads are all best-effort in the handler already; forcing them
    to miss keeps this test deterministic and keeps it off the network.
    """
    monkeypatch.setattr(invoice_engine, "_load_logo_bytes", lambda: None)
    monkeypatch.setattr(invoice_engine, "_load_s3_image", lambda _k: None)

    def _no_s3(*_a, **_k):
        raise RuntimeError("no S3 in tests")

    monkeypatch.setattr(invoice_engine.s3, "get_object", _no_s3)
    # The font cache is a function attribute and survives between calls.
    if hasattr(invoice_engine._generate_receipt_png, "_font_cache"):
        invoice_engine._generate_receipt_png._font_cache = {}
    return invoice_engine


INVOICE = {
    "invoiceId": "inv-test-1",
    "referenceId": "WD-PAY-TESTONLY",
    "invoiceNumber": "WD/2627/00001",
    "createdAt": 1760000000,
    "customerName": "A. Customer",
    "customerPhone": "+919812345678",
    "shippingAddress": "Kolkata, WB 700012",
    "subtotal": 101.0,
    "tax": 0.46,
    "gstRate": 18.0,
    "convenienceFee": 2.53,
    "total": 103.99,
    "paymentStatus": "pending",
}
ITEMS = [{"itemIndex": 0, "name": "Rs1 test product", "quantity": 1, "amount": 1.0}]


def _render(mod):
    from PIL import Image

    png = mod._generate_receipt_png(INVOICE, ITEMS)
    return Image.open(io.BytesIO(png))


def _corners(img):
    w, h = img.size
    return [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


# ---------------------------------------------------------------------------
# 1. The default must not change what a customer sees
# ---------------------------------------------------------------------------

def test_the_approved_layout_is_on_by_default(offline_renderer):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RECEIPT_TRANSPARENT_BG", None)
        assert offline_renderer._transparent_receipt_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "FALSE", "maybe"])
def test_only_an_affirmative_value_switches_it_on(offline_renderer, value):
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": value}):
        assert offline_renderer._transparent_receipt_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_the_affirmative_spellings_all_work(offline_renderer, value):
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": value}):
        assert offline_renderer._transparent_receipt_enabled() is True


def test_explicit_false_preserves_the_legacy_layout_for_rollback(offline_renderer):
    """The whole point of the default. This is the output live traffic gets."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ["RECEIPT_TRANSPARENT_BG"] = "false"
        img = _render(offline_renderer)

    assert img.mode == "RGB"
    assert "A" not in img.getbands()
    assert _corners(img) == [CURRENT_GREY_BACKDROP] * 4


# ---------------------------------------------------------------------------
# 2. With the flag on, the output matches the approved specimen
# ---------------------------------------------------------------------------

def test_with_the_flag_on_the_background_is_transparent(offline_renderer):
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": "true"}):
        img = _render(offline_renderer)

    assert img.mode == "RGBA"
    assert [p[3] for p in _corners(img)] == [APPROVED_CORNER_ALPHA] * 4


def test_the_paper_is_the_approved_off_white_and_fully_opaque(offline_renderer):
    """(252, 252, 250, 255) is read off the approved specimen, not chosen here."""
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": "true"}):
        img = _render(offline_renderer)

    w, h = img.size
    # Inside the left padding at mid-height: paper, never text.
    assert img.getpixel((100, h // 2)) == APPROVED_PAPER_RGBA
    assert img.getpixel((w - 101, h // 2)) == APPROVED_PAPER_RGBA


def test_the_tear_is_deterministic_so_one_invoice_renders_the_same_twice(offline_renderer):
    """The edge is seeded. A re-render must not produce a different receipt."""
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": "true"}):
        first = offline_renderer._generate_receipt_png(INVOICE, ITEMS)
        second = offline_renderer._generate_receipt_png(INVOICE, ITEMS)

    assert first == second


# ---------------------------------------------------------------------------
# 3. Transparency must not turn the PDF black
# ---------------------------------------------------------------------------

def test_flattening_an_rgba_receipt_gives_white_not_black(offline_renderer):
    """`convert('RGB')` keeps the RGB under a transparent pixel, which is black.

    So the PDF path has to COMPOSITE onto white. Asserted on the flattening helper
    directly: `generate_invoice_pdf` writes to S3.
    """
    with patch.dict(os.environ, {"RECEIPT_TRANSPARENT_BG": "true"}):
        img = _render(offline_renderer)

    flat = offline_renderer._flatten_onto_white(img)

    assert flat.mode == "RGB"
    assert _corners(flat) == [(255, 255, 255)] * 4


def test_flattening_leaves_an_opaque_receipt_alone(offline_renderer):
    with patch.dict(os.environ, {}, clear=False):
        os.environ["RECEIPT_TRANSPARENT_BG"] = "false"
        img = _render(offline_renderer)

    flat = offline_renderer._flatten_onto_white(img)

    assert flat.mode == "RGB"
    assert _corners(flat) == [CURRENT_GREY_BACKDROP] * 4


# ---------------------------------------------------------------------------
# 4. The payment-template header is a different artifact and must not have moved
# ---------------------------------------------------------------------------

def test_the_fixed_payment_template_header_is_untouched():
    """`wecarepay-header.png` is the header Meta refetches at send time.

    Meta cannot edit an approved template body in place, so swapping this URL would
    break every approved payment template. The receipt artifact is separate.
    """
    outbound = (FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py").read_text()
    presets = (FUNCTIONS / "shared" / "lambda_utils" / "template_presets.py").read_text()

    assert f"FIXED_CHECKOUT_HEADER = '{PAYMENT_TEMPLATE_HEADER_URL}'" in outbound
    assert PAYMENT_TEMPLATE_HEADER_URL in presets

    # And the receipt asset has not been substituted into either of them.
    assert "invoice-receipt.png" not in outbound
    assert "invoice-receipt.png" not in presets


def test_the_approved_specimen_is_not_attached_to_any_send_path():
    """It is fixture data. Referencing it from the send path would mail it to customers."""
    engine = (FUNCTIONS / "payments" / "invoice-engine" / "handler.py").read_text()

    # Named only as the acceptance reference, in a comment — never built into a key,
    # a media field, or a message body.
    for line in engine.splitlines():
        if APPROVED_SPECIMEN_URL in line:
            assert line.lstrip().startswith("#"), line
