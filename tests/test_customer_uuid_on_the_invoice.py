"""The public customer id must reach the customer, and an absent one must leave no trace.

WHAT THIS PINS, AND WHY EACH HALF MATTERS
-----------------------------------------
The owner's requirement is that a customer carries a unique id shown on their invoice and on
their order pages. Two properties bound the implementation, and the second is the one that is
easy to get wrong:

  1. **It renders at all three sites.** The HTML/PDF, the PNG the customer receives on WhatsApp,
     and the caption beside that image. Three renderers reading one value through one function,
     so a customer cannot be shown two different ids - or an id in one place and nothing in
     another - for one order. The exact failure `invoiceNumber` had before it was printed: the
     field existed, was consumed, and reached no document.

  2. **An absent one renders NOTHING.** Not an empty `Customer ID:` label, which reads as a
     broken renderer, and emphatically not a minted substitute. Every contact created before this
     attribute existed carries no id, so this is the common case rather than an edge one - and a
     renderer that invented a value would print an identifier matching no record anywhere. The
     same rule `tests/test_invoice_number_is_rendered.py` pins for the number, for the same
     reason.

A third property is asserted because printing the id is only safe if the reason it is safe stays
true: the caption must still carry no name, no phone, no email and no address. The uuid is OURS,
opaque, and carries no timestamp (it is a uuid4, not a uuid7 - see `customer_uuid`), so it
identifies nobody to a stranger reading a notification preview. A phone does.

TECHNIQUE
---------
Modelled on `test_invoice_number_is_rendered.py` and reusing its fake-PIL approach: PIL is not
installed here (the live function gets it from the `pillow-python312` layer), so a fake `PIL` is
installed for the duration of the call and records every `draw.text` string. Asserting on the
DRAWN-TEXT list is stronger than a pixel diff anyway - it says what the renderer was asked to
write.
"""
from __future__ import annotations

import io
import json
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

from lambda_utils import identifiers  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import customer_receipt as cr  # noqa: E402
from lambda_utils.ecommerce import order_channel  # noqa: E402
from lambda_utils.identity import customer_uuid  # noqa: E402

#: A real minted id, not a hand-written string, so this test cannot drift from the minter.
CUSTOMER_ID = customer_uuid.new_customer_uuid()

ISSUED = "WD/2627/00001"
CUSTOMER_NAME = "A. Customer"
CUSTOMER_PHONE = "+918100640044"
CUSTOMER_ADDRESS = "12 Example Road, Kolkata, West Bengal 700012"

ITEMS = [
    {"name": "Rs1 test product", "amount": 1.0, "quantity": 1},
    {"name": "Contribute", "amount": 100.0, "quantity": 1},
]


@pytest.fixture
def engine(monkeypatch):
    path = str(FUNCTIONS / "payments" / "invoice-engine")
    monkeypatch.syspath_prepend(path)
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415 - deliberately imported under the patches
    yield handler
    sys.modules.pop("handler", None)


def _invoice(**overrides):
    """A paid invoice row as `create_invoice` writes one, carrying a public customer id."""
    row = {
        "invoiceId": "inv-test",
        "invoiceNumber": ISSUED,
        "referenceId": "WD-PAY-ABCD1234",
        "orderId": "WD-ORD-ABCD1234",
        "channel": order_channel.CHANNEL_WEBSITE,
        customer_uuid.ATTRIBUTE: CUSTOMER_ID,
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


# ══════════════════════════════════════════════════════════════════════════════
# 1. HTML / PDF
# ══════════════════════════════════════════════════════════════════════════════

def test_the_html_prints_the_customer_id(engine):
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert f"Customer ID: {CUSTOMER_ID}" in html


def test_the_html_prints_it_in_the_bill_to_block(engine):
    """Position is the contract (docs/invoice-layout.md section 2): it identifies the person being
    billed, so it sits inside Bill To - after the name, before the phone - rather than up in the
    invoice meta block beside the invoice number."""
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert html.index("Bill To") < html.index("Customer ID:")
    assert html.index(CUSTOMER_NAME) < html.index("Customer ID:")
    assert html.index("Customer ID:") < html.index(CUSTOMER_PHONE)


def test_the_html_prints_the_id_in_full(engine):
    """IN FULL, deliberately, beside a phone that is not. The uuid is ours, opaque and carries no
    timestamp, so there is nothing to mask; masking it would also destroy its only purpose, which
    is being quotable by a support agent instead of the phone."""
    html = engine._build_invoice_html(_invoice(), ITEMS)
    assert CUSTOMER_ID in html
    assert "\u2026" not in html.split("Customer ID:")[1][:60]


def test_an_html_invoice_with_no_customer_id_renders_NO_row(engine):
    row = _invoice()
    row.pop(customer_uuid.ATTRIBUTE)
    html = engine._build_invoice_html(row, ITEMS)
    assert "Customer ID" not in html
    # The document still renders, and the rest of Bill To is untouched.
    assert "TAX INVOICE" in html
    assert "Bill To" in html
    assert CUSTOMER_NAME in html


@pytest.mark.parametrize("stored", [
    "", None, "junk", "not-a-uuid-at-all", 12345, {},
])
def test_an_html_invoice_with_a_JUNK_customer_id_renders_no_row(engine, stored):
    """Suppressed, not printed. A row's stored value is the one input here that is neither the
    caller's nor this code's, and whatever lands in it must never reach a tax invoice verbatim."""
    html = engine._build_invoice_html(_invoice(**{customer_uuid.ATTRIBUTE: stored}), ITEMS)
    assert "Customer ID" not in html


def test_a_uuid7_in_the_attribute_is_never_printed(engine):
    """The one junk case worth naming on its own. A uuid7 PARSES, so a renderer that only checked
    "is it a uuid" would print it - and printing it would disclose, on a document the customer
    keeps and forwards, the millisecond their record was created."""
    seven = identifiers.new_uuid7()
    html = engine._build_invoice_html(_invoice(**{customer_uuid.ATTRIBUTE: seven}), ITEMS)
    assert "Customer ID" not in html
    assert seven not in html


def test_the_render_sites_never_mint_a_customer_id(engine):
    """A renderer that fell back to minting would print an id matching no record anywhere - and
    it runs on every download and every re-send, so a customer could collect several."""
    source = (FUNCTIONS / "payments" / "invoice-engine" / "handler.py").read_text(
        encoding="utf-8")
    assert "new_customer_uuid" not in source
    # One definition, read by all three render sites, so they cannot disagree.
    assert source.count("def _customer_id(") == 1
    assert source.count("_customer_id(invoice)") == 3


# ══════════════════════════════════════════════════════════════════════════════
# 2. PNG - observed through the drawn-text list
# ══════════════════════════════════════════════════════════════════════════════

class _FakeFont:
    def __init__(self, size=14):
        self.size = size


class _FakeDraw:
    """Records every string the renderer asks to be drawn."""

    def __init__(self, sink):
        self.sink = sink

    def text(self, xy, text, fill=None, font=None):
        self.sink.append(text)

    def textbbox(self, xy, text, font=None):
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
    """A `PIL` covering exactly the surface `_generate_receipt_png` touches."""
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


def test_the_png_draws_the_customer_id(engine):
    """The image is what the customer actually receives on WhatsApp."""
    drawn = _drawn_text(engine, _invoice())
    assert any(f"Customer ID: {CUSTOMER_ID}" in text for text in drawn)


def test_the_png_draws_it_after_the_name_and_before_the_phone(engine):
    """The same Bill To ordering as the HTML, so the two documents for one order match."""
    drawn = _drawn_text(engine, _invoice())
    bill_to = drawn.index("Bill To:")
    name = next(i for i, t in enumerate(drawn) if CUSTOMER_NAME in t)
    cust_id = next(i for i, t in enumerate(drawn) if "Customer ID:" in t)
    phone = next(i for i, t in enumerate(drawn) if CUSTOMER_PHONE in t)
    assert bill_to < name < cust_id < phone


def test_the_png_draws_no_customer_id_line_when_there_is_none(engine):
    row = _invoice()
    row.pop(customer_uuid.ATTRIBUTE)
    drawn = _drawn_text(engine, row)
    assert not [t for t in drawn if "Customer ID" in t]
    # The rest of the receipt is unaffected.
    assert "TAX INVOICE" in drawn
    assert "Bill To:" in drawn
    assert "* * *  PAID  * * *" in drawn


def test_the_png_still_draws_its_existing_lines(engine):
    """A regression fence around the inserted line: the meta block, the totals and the PAID
    stamp must be untouched."""
    drawn = _drawn_text(engine, _invoice())
    assert "TAX INVOICE" in drawn
    assert f"Invoice No: {ISSUED}" in drawn
    assert "Source: Website" in drawn
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
    """Drive the REAL `send_invoice_whatsapp` and return the caption it handed to delivery."""
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
    sent = json.loads(json.loads(lam.invoke.call_args.kwargs["Payload"])["body"])
    return sent["content"]


def test_the_caption_carries_the_customer_id(engine):
    assert f"Customer ID: {CUSTOMER_ID}" in _caption_for(engine, _invoice())


def test_the_caption_omits_the_line_when_there_is_no_customer_id(engine):
    row = _invoice()
    row.pop(customer_uuid.ATTRIBUTE)
    caption = _caption_for(engine, row)
    assert "Customer ID" not in caption
    # The existing lines survive, so the caption is still useful without one.
    assert f"Invoice: {ISSUED}" in caption
    assert "Order: WD-ORD-ABCD1234" in caption
    assert "Ref: WD-PAY-ABCD1234" in caption
    assert "Ordered on: Website" in caption
    assert "Thank you for your payment!" in caption


def test_the_caption_STILL_contains_no_personal_data(engine):
    """The property re-asserted with a uuid present, which is the state the existing caption test
    does not cover. Printing the uuid is only defensible because the reason it is safe stays true:
    it is ours, opaque and timestamp-free, whereas a name, phone, email or address identifies the
    recipient to whoever is looking at the handset. So the uuid being added must not have dragged
    anything else in with it."""
    caption = _caption_for(engine, _invoice(channel=order_channel.CHANNEL_WHATSAPP))
    assert CUSTOMER_ID in caption                 # the id IS there
    assert CUSTOMER_NAME not in caption
    assert CUSTOMER_PHONE not in caption
    assert "8100640044" not in caption            # not even unprefixed
    assert "0044" not in caption                  # not even the masked suffix
    assert CUSTOMER_ADDRESS not in caption
    assert "Kolkata" not in caption
    assert "customer@example.com" not in caption
    for line in caption.splitlines():
        assert line.startswith(("Invoice", "Order:", "Ref:", "Ordered on:",
                                "Customer ID:", "Thank you")), line


def test_the_caption_and_the_image_show_the_SAME_id(engine):
    """One order, two surfaces, one id. Two readings of one attribute is how a customer ends up
    quoting an id that does not match their document."""
    invoice = _invoice()
    caption = _caption_for(engine, invoice)
    drawn = _drawn_text(engine, invoice)
    in_caption = next(line for line in caption.splitlines()
                      if line.startswith("Customer ID:"))
    in_image = next(t for t in drawn if "Customer ID:" in t)
    assert in_caption.split(":", 1)[1].strip() == in_image.split(":", 1)[1].strip()


# ══════════════════════════════════════════════════════════════════════════════
# 4. The website download path
# ══════════════════════════════════════════════════════════════════════════════

def _snapshot(*, customer="CUS_01J0000000000000000000000", collection=10100):
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


def test_a_website_receipt_prints_the_id_when_the_order_has_one(engine):
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234", customer_uuid=CUSTOMER_ID)
    assert invoice[customer_uuid.ATTRIBUTE] == CUSTOMER_ID
    assert f"Customer ID: {CUSTOMER_ID}" in engine._build_invoice_html(
        invoice, invoice["items"])


def test_a_website_receipt_with_no_id_still_renders(engine):
    """The common case today: an order row written before the attribute existed. It must download,
    and it must NOT acquire an id on the way."""
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234")
    assert invoice[customer_uuid.ATTRIBUTE] == ""
    html = engine._build_invoice_html(invoice, invoice["items"])
    assert "Customer ID" not in html
    assert "TAX INVOICE" in html


def test_the_receipt_module_never_derives_the_customer_id():
    """A parameter with a safe default, so a caller that does not know stays honest rather than
    printing a guess - exactly as `invoice_number` and `channel` already behave."""
    import inspect
    signature = inspect.signature(cr.invoice_dict_from_snapshot)
    assert signature.parameters["customer_uuid"].default == ""
    generate = inspect.signature(cr.generate_receipt)
    assert generate.parameters["customer_uuid"].default == ""
    source = (FUNCTIONS / "shared" / "lambda_utils" / "ecommerce"
              / "customer_receipt.py").read_text(encoding="utf-8")
    assert "new_customer_uuid" not in source
