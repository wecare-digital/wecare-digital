"""The issued invoice number must actually reach the customer. GST Rule 46(b).

`invoice-engine._get_next_invoice_number` has issued `WD/<fy>/<seq>` since the engine was
written, atomically, out of a per-financial-year DynamoDB counter - and printed it NOWHERE.
Measured before this change:

  * `_build_invoice_html` assigned `inv_num = invoice.get('invoiceNumber', '')` on its first
    line and never referenced it again, so the HTML and the PDF rendered from it carried no
    number.
  * `_generate_receipt_png` never read the field at all, so the image sent on WhatsApp carried
    no number.
  * the WhatsApp caption carried the total, the order id and the reference id, and no number.

So every tax invoice this engine has produced was missing a mandatory particular, while the
number itself was consumed out of the GST series. That is the worst shape of the defect: the
sequence advanced, the compliance artifact did not exist, and nothing errored.

These tests pin the three render sites plus the website download path, and they pin the two
properties that bound the fix:

  * an invoice with NO number renders no `Invoice No:` row at all. An unnumbered invoice must
    look unnumbered rather than look like a rendering fault, and - decisively - a renderer may
    never mint a substitute, because minting one advances the sequence from a read path.
  * the WhatsApp caption stays free of personal data. It is rendered in notification previews
    and survives forwarding, so it is the least private surface the engine writes to.

The PNG is observed through its DRAWN-TEXT list, not its pixels. PIL is not installed in this
environment (the function imports it lazily, inside the body, and the live function gets it
from the `pillow-python312` layer), so a fake `PIL` is installed for the duration of the call
and records every `draw.text` string. That is a stronger assertion than a pixel diff anyway:
it says what the renderer was asked to write.
"""
from __future__ import annotations

import io
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "amplify" / "functions"
for extra in (FUNCTIONS / "shared",):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import customer_receipt as cr  # noqa: E402
from lambda_utils.ecommerce import order_channel  # noqa: E402

#: The first number of FY 2026-2027, exactly as `_get_next_invoice_number` composes it.
ISSUED = "WD/2627/00001"

#: Personal data that must never appear in a WhatsApp caption.
CUSTOMER_NAME = "A. Customer"
CUSTOMER_PHONE = "+918100640044"
CUSTOMER_ADDRESS = "12 Example Road, Kolkata, West Bengal 700012"


@pytest.fixture
def engine(monkeypatch):
    """Load invoice-engine with boto3 stubbed, and hand back its module."""
    path = str(FUNCTIONS / "payments" / "invoice-engine")
    monkeypatch.syspath_prepend(path)
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415 - deliberately imported under the patches
    yield handler
    sys.modules.pop("handler", None)


def _invoice(**overrides):
    """A paid invoice row as `create_invoice` writes one, with the personal fields populated."""
    row = {
        "invoiceId": "inv-test",
        "invoiceNumber": ISSUED,
        "referenceId": "WD-PAY-ABCD1234",
        "orderId": "WD-ORD-ABCD1234",
        "channel": order_channel.CHANNEL_WEBSITE,
        "status": "paid",
        "paymentStatus": "captured",
        "customerName": CUSTOMER_NAME,
        "customerPhone": CUSTOMER_PHONE,
        "customerEmail": "customer@example.com",
        "shippingAddress": CUSTOMER_ADDRESS,
        "subtotal": 101.0,
        "discount": 0.0,
        "shipping": 0.0,
        "handling": 0.0,
        "gstRate": 0.0,
        "tax": 0.0,
        "convenienceFee": 2.99,
        "total": 103.99,
        "currency": "INR",
        "createdAt": 1791000000,
        "paidAt": 1791000120,
    }
    row.update(overrides)
    return row


ITEMS = [
    {"name": "Rs1 test product", "amount": 1.0, "quantity": 1},
    {"name": "Contribute", "amount": 100.0, "quantity": 1},
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. HTML / PDF
# ══════════════════════════════════════════════════════════════════════════════

def test_the_html_prints_the_exact_issued_number(engine):
    """Not "a number" - the one the sequence issued, character for character. A reformatted
    number would not match the counter row, and the counter row is the GST series."""
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert f"Invoice No: {ISSUED}" in html


def test_the_html_number_row_comes_before_the_date_row(engine):
    """Ordering is the layout contract (docs/invoice-layout.md section 2) and it is also where
    a reader looks first. Positional rather than cosmetic: the number leads the meta block."""
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert html.index("Invoice No:") < html.index("Date:")


@pytest.mark.parametrize("channel,expected", [
    (order_channel.CHANNEL_WEBSITE, "Source: Website"),
    (order_channel.CHANNEL_WHATSAPP, "Source: WhatsApp"),
])
def test_the_html_prints_the_source_for_both_channels(engine, channel, expected):
    html = engine._build_invoice_html(_invoice(channel=channel), ITEMS)
    assert expected in html


def test_an_html_invoice_with_no_number_renders_no_row_at_all(engine):
    """An empty row (`Invoice No: ` with nothing after it) reads as a broken renderer. The
    absence must be the absence of the row."""
    html = engine._build_invoice_html(_invoice(invoiceNumber=""), ITEMS)
    assert "Invoice No:" not in html
    # And the document still renders - the number is missing, not the invoice.
    assert "TAX INVOICE" in html
    assert "Source: Website" in html


def test_an_html_invoice_with_no_channel_still_prints_website(engine):
    """Every row written before `channel` existed carries none, and `Website` is true of all of
    them: no WhatsApp-origin order is reachable yet."""
    row = _invoice()
    row.pop("channel")
    assert "Source: Website" in engine._build_invoice_html(row, ITEMS)


def test_a_junk_channel_degrades_rather_than_breaking_the_render(engine):
    """`order_channel.canonical` is total on purpose, and a renderer is the last place a
    `TypeError` should surface - the money has already moved by then."""
    for junk in (None, 0, {"a": 1}, "WEBSITE-ish", "whats app"):
        html = engine._build_invoice_html(_invoice(channel=junk), ITEMS)
        assert "Source: Website" in html


# ══════════════════════════════════════════════════════════════════════════════
# 2. PNG - observed through the drawn-text list
# ══════════════════════════════════════════════════════════════════════════════

class _FakeFont:
    """Enough of an `ImageFont` for the renderer: it is only ever passed back to PIL."""

    def __init__(self, size=14):
        self.size = size


class _FakeDraw:
    """Records every string the renderer asks to be drawn."""

    def __init__(self, sink):
        self.sink = sink

    def text(self, xy, text, fill=None, font=None):
        self.sink.append(text)

    def textbbox(self, xy, text, font=None):
        # Width proportional to the text, so the centring arithmetic stays sane.
        return (0, 0, len(text) * 8, 12)

    def rectangle(self, *args, **kwargs):
        pass

    def polygon(self, *args, **kwargs):
        pass


class _FakeImage:
    def __init__(self, size=(1, 1)):
        self.size = tuple(size)

    @property
    def width(self):
        return self.size[0]

    @property
    def height(self):
        return self.size[1]

    def crop(self, box):
        return _FakeImage((box[2] - box[0], box[3] - box[1]))

    def resize(self, size, *args, **kwargs):
        return _FakeImage(size)

    def convert(self, mode):
        return self

    def paste(self, other, box=None, mask=None):
        pass

    def save(self, buf, format=None):
        buf.write(b"\x89PNG\r\n\x1a\n-fake-")


def _fake_pil(sink):
    """A `PIL` package covering exactly the surface `_generate_receipt_png` touches.

    Installed into `sys.modules` for the duration of the call, because the function does its
    `from PIL import ...` inside its own body (the live one gets PIL from the
    `pillow-python312` layer; this environment has no PIL at all).
    """
    pil = types.ModuleType("PIL")
    image = types.ModuleType("PIL.Image")
    image_draw = types.ModuleType("PIL.ImageDraw")
    image_font = types.ModuleType("PIL.ImageFont")

    image.LANCZOS = 1
    image.new = lambda mode, size, color=None: _FakeImage(size)

    def _open(_fp):
        raise OSError("no image decoder in this fake")

    image.open = _open
    image_draw.Draw = lambda img: _FakeDraw(sink)

    def _truetype(_font, _size=10, **_kwargs):
        # Refuse, so the renderer walks its documented fallback chain to load_default.
        raise OSError("fake PIL has no truetype loader")

    image_font.truetype = _truetype
    image_font.load_default = lambda size=None: _FakeFont(size or 14)

    pil.Image = image
    pil.ImageDraw = image_draw
    pil.ImageFont = image_font
    return {"PIL": pil, "PIL.Image": image,
            "PIL.ImageDraw": image_draw, "PIL.ImageFont": image_font}


def _drawn_text(engine, invoice, items=ITEMS):
    """Run the real `_generate_receipt_png` against the fake PIL; return every drawn string."""
    sink: list[str] = []
    # A fresh font cache per call: the real one is a function attribute and would otherwise
    # carry a cached `None` (or bytes) between tests.
    engine._generate_receipt_png._font_cache = {}
    s3 = MagicMock()
    s3.get_object.side_effect = RuntimeError("no S3 in tests")
    with patch.dict(sys.modules, _fake_pil(sink)), \
            patch.object(engine, "s3", s3), \
            patch.object(engine, "_load_logo_bytes", return_value=None), \
            patch.object(engine, "_load_s3_image", return_value=None):
        png = engine._generate_receipt_png(invoice, items)
    assert isinstance(png, bytes) and png, "the renderer must still return PNG bytes"
    return sink


def test_the_png_draws_the_invoice_number(engine):
    """The image is what the customer receives on WhatsApp, and it read `invoiceNumber`
    nowhere before this."""
    assert f"Invoice No: {ISSUED}" in _drawn_text(engine, _invoice())


def test_the_png_draws_the_number_before_the_date(engine):
    drawn = _drawn_text(engine, _invoice())
    assert drawn.index(f"Invoice No: {ISSUED}") < next(
        i for i, t in enumerate(drawn) if t.startswith("Date:"))


def test_the_png_draws_source_after_ref(engine):
    """Per docs/invoice-layout.md section 2: `Source:` sits after `Ref:`."""
    drawn = _drawn_text(engine, _invoice(channel=order_channel.CHANNEL_WHATSAPP))
    assert "Source: WhatsApp" in drawn
    ref = next(i for i, t in enumerate(drawn) if t.startswith("Ref:"))
    assert drawn.index("Source: WhatsApp") > ref


def test_the_png_source_reads_website_for_a_website_order(engine):
    assert "Source: Website" in _drawn_text(engine, _invoice())


def test_the_png_draws_no_number_line_when_there_is_none(engine):
    drawn = _drawn_text(engine, _invoice(invoiceNumber=""))
    assert not [t for t in drawn if t.startswith("Invoice No:")]
    # The rest of the document is unaffected.
    assert "TAX INVOICE" in drawn
    assert "Source: Website" in drawn


def test_the_png_still_draws_its_existing_lines(engine):
    """A regression fence around the two inserted lines: the meta block, the totals and the
    PAID stamp must be untouched. The amount lines in particular belong to another worktree."""
    drawn = _drawn_text(engine, _invoice())
    assert "TAX INVOICE" in drawn
    assert "* * *  PAID  * * *" in drawn
    assert "Subtotal" in drawn
    assert "Thank You!" in drawn


# ══════════════════════════════════════════════════════════════════════════════
# 3. The WhatsApp caption
# ══════════════════════════════════════════════════════════════════════════════

class _FakeTable:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.writes = []

    def get_item(self, Key=None, **_):
        key = tuple(sorted((Key or {}).items()))
        row = self.rows.get(key)
        return {"Item": row} if row else {}

    def put_item(self, Item=None, **_):
        self.writes.append(Item)

    def update_item(self, **kwargs):
        self.writes.append(kwargs)


def _caption_for(engine, invoice):
    """Drive the REAL `send_invoice_whatsapp` and return the caption it handed to delivery.

    `lambda_client` is a MagicMock, so nothing is sent: this asserts on the composed message,
    not on a WhatsApp delivery.
    """
    invoice_id = invoice["invoiceId"]
    assets = _FakeTable({
        (("assetType", "image"), ("invoiceId", invoice_id)):
            {"invoiceId": invoice_id, "assetType": "image", "s3Key": "secure/x.png",
             "url": "signed"},
    })
    invoices = _FakeTable({(("invoiceId", invoice_id),): invoice})
    tables = {
        engine.INVOICE_ASSETS_TABLE: assets,
        engine.INVOICES_TABLE: invoices,
        engine.INVOICE_DELIVERY_TABLE: _FakeTable(),
    }
    ddb = MagicMock()
    ddb.Table.side_effect = lambda name: tables.get(name, _FakeTable())
    lam = MagicMock()
    lam.invoke.return_value = {
        "Payload": io.BytesIO(b'{"body": "{\\"status\\": \\"sent\\"}"}')}

    with patch.object(engine, "dynamodb", ddb), \
            patch.object(engine, "lambda_client", lam), \
            patch.object(engine, "_signed_invoice_url", return_value=""), \
            patch.object(engine, "_lookup_contact_by_phone", return_value=None):
        response = engine.send_invoice_whatsapp(
            invoice_id, "+918100640044", "", "req-caption")

    assert response["statusCode"] == 200
    import json as _json
    sent = _json.loads(_json.loads(lam.invoke.call_args.kwargs["Payload"])["body"])
    return sent["content"]


def test_the_caption_carries_the_invoice_number_and_the_source(engine):
    caption = _caption_for(engine, _invoice(channel=order_channel.CHANNEL_WHATSAPP))
    assert f"Invoice: {ISSUED}" in caption
    assert "Ordered on: WhatsApp" in caption


def test_the_caption_says_website_for_a_website_order(engine):
    assert "Ordered on: Website" in _caption_for(engine, _invoice())


def test_the_caption_omits_the_number_line_when_there_is_none(engine):
    caption = _caption_for(engine, _invoice(invoiceNumber=""))
    assert "Invoice:" not in caption
    # The existing lines survive, so the caption is still useful without a number.
    assert "Order: WD-ORD-ABCD1234" in caption
    assert "Ordered on: Website" in caption


def test_the_caption_keeps_its_existing_lines(engine):
    caption = _caption_for(engine, _invoice())
    assert "Order: WD-ORD-ABCD1234" in caption
    assert "Ref: WD-PAY-ABCD1234" in caption
    assert "Thank you for your payment!" in caption


def test_the_caption_contains_no_personal_data(engine):
    """The property, not one spelling of it: a WhatsApp caption appears in notification
    previews and survives forwarding, so a name, a phone or an address in it is a disclosure
    to whoever is looking at the handset. The invoice IMAGE carries the bill-to block; the
    caption carries identifiers only."""
    caption = _caption_for(engine, _invoice(channel=order_channel.CHANNEL_WHATSAPP))
    assert CUSTOMER_NAME not in caption
    assert CUSTOMER_PHONE not in caption
    assert "8100640044" not in caption  # not even unprefixed
    assert "0044" not in caption        # not even the masked suffix
    assert CUSTOMER_ADDRESS not in caption
    assert "Kolkata" not in caption
    assert "customer@example.com" not in caption
    # Positively: every line is a label, an amount or one of our own identifiers.
    for line in caption.splitlines():
        assert line.startswith(("Invoice", "Order:", "Ref:", "Ordered on:", "Thank you")), line


# ══════════════════════════════════════════════════════════════════════════════
# 4. The website download path
# ══════════════════════════════════════════════════════════════════════════════

def _snapshot(*, customer="CUS_01J0000000000000000000000", collection=10100):
    """A real immutable paid snapshot via the section-7 calculator, as test_customer_receipt
    builds one - not a stand-in, so the amounts on the rendered receipt are the charged ones."""
    quote = cp.compute_quote(collection, currency="INR")
    return cp.build_snapshot(
        customer_id=customer,
        cart_id="cart-1",
        cart_revision=1,
        quote=quote,
        created_at=1_791_000_000,
        ttl_seconds=3600,
        items=[{"name": "Rs1 test product", "amountPaise": 100, "quantity": 1}],
        address={"name": CUSTOMER_NAME, "phone": CUSTOMER_PHONE, "line": CUSTOMER_ADDRESS},
    )


def test_a_website_receipt_prints_a_number_when_the_order_has_one(engine):
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234", invoice_number=ISSUED)
    assert invoice["invoiceNumber"] == ISSUED
    assert f"Invoice No: {ISSUED}" in engine._build_invoice_html(
        invoice, invoice["items"])


def test_a_website_receipt_with_no_number_still_renders_and_says_website(engine):
    """The common case today: a website order the engine never invoiced. It must download, and
    it must NOT acquire a number on the way - issuing one advances the GST series."""
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234")
    assert invoice["invoiceNumber"] == ""
    html = engine._build_invoice_html(invoice, invoice["items"])
    assert "Invoice No:" not in html
    assert "Source: Website" in html
    assert "TAX INVOICE" in html


def test_a_whatsapp_origin_receipt_says_whatsapp(engine):
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234",
        channel=order_channel.CHANNEL_WHATSAPP)
    assert invoice["channel"] == order_channel.CHANNEL_WHATSAPP
    assert "Source: WhatsApp" in engine._build_invoice_html(invoice, invoice["items"])


# ══════════════════════════════════════════════════════════════════════════════
# 5. The boundaries this change must not cross
# ══════════════════════════════════════════════════════════════════════════════

def _called_functions(path: Path) -> list[str]:
    """Every plain function name CALLED in a module, from the AST.

    AST rather than a text search, for the reason this repo has been caught by twice: the
    comments and docstrings that explain why a renderer must not mint a number necessarily
    NAME `_get_next_invoice_number`, so a textual search flags its own explanation.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]


def test_no_render_site_can_generate_an_invoice_number():
    """Only `create_invoice` may advance the sequence. A renderer that fell back to minting a
    number would advance the GST series from a READ path - and the read path runs on every
    download and on every re-send, so the series would gap on its own."""
    engine = FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
    receipt = FUNCTIONS / "shared" / "lambda_utils" / "ecommerce" / "customer_receipt.py"

    # Exactly one call site in the engine, and it is the issuing path, not a render path.
    assert _called_functions(engine).count("_get_next_invoice_number") == 1
    # Nothing in the receipt module calls it, and it composes no WD/<fy>/<seq> string either.
    assert "_get_next_invoice_number" not in _called_functions(receipt)
    assert "WD/" not in "".join(_code_strings(receipt))


def _code_strings(path: Path) -> list[str]:
    """Every string literal in a module EXCEPT the docstrings.

    Same reason as `_called_functions`: the docstrings here quote `WD/<fy>/<seq>` while
    explaining that this module must never build one.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstring_nodes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        first = node.body[0] if node.body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstring_nodes.add(id(first.value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstring_nodes]


def test_the_receipt_module_never_derives_the_number_or_the_channel():
    """Both are parameters with safe defaults, so a caller that does not know stays honest
    rather than printing a guess."""
    import inspect
    signature = inspect.signature(cr.invoice_dict_from_snapshot)
    assert signature.parameters["invoice_number"].default == ""
    assert signature.parameters["channel"].default == ""
    generate = inspect.signature(cr.generate_receipt)
    assert generate.parameters["invoice_number"].default == ""
    assert generate.parameters["channel"].default == ""


def test_the_three_render_sites_share_one_source_label(engine):
    """One function, so the HTML, the PNG and the caption cannot show a customer two different
    origins for one order."""
    assert engine._source_label({"channel": order_channel.CHANNEL_WHATSAPP}) == "WhatsApp"
    assert engine._source_label({"channel": order_channel.CHANNEL_WEBSITE}) == "Website"
    assert engine._source_label({}) == "Website"
    source = (FUNCTIONS / "payments" / "invoice-engine" / "handler.py").read_text(
        encoding="utf-8")
    # Defined once, used by all three render sites.
    assert source.count("def _source_label(") == 1
    assert source.count("_source_label(invoice)") == 3


def test_the_amount_line_regions_are_not_touched_by_the_source_label(engine):
    """Phase P owns the amount-line composition. These assertions are the legacy output
    snapshot for the lines this FEAT must leave exactly as they were."""
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert "<span>Subtotal</span><span>101.00</span>" in html
    assert "<span>Conv Fee</span><span>2.99</span>" in html
    assert "&#8377; 103.99" in html
