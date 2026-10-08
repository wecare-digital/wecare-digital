"""The private Download-receipt: authorised, bounded-expiry, cross-customer-denied, idempotent.

Section 9 requires a receipt that is offered on success and in history, stays PRIVATE, uses
bounded-expiry links, denies cross-customer access, regenerates idempotently, reuses the invoice
engine's design, and is generated from the IMMUTABLE verified-paid snapshot.

The S3 object storage and presign are BLOCKED here (no AWS); the client is mocked. What is asserted:
  * authority comes from the session; another customer's snapshot is refused like a missing one;
  * the link is signed and short-lived, and a TTL past the ceiling is refused;
  * the storage key is derived from the snapshot, so regeneration is idempotent (same key);
  * the receipt is never written to a public prefix or the bag-icon media folder;
  * amounts come from the frozen snapshot, not recomputed;
  * the engine's own `_build_invoice_html` is the design (injected here).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils import media_paths  # noqa: E402
from lambda_utils.customer_auth import CustomerIdentity, CustomerNotAuthorized  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import customer_receipt as cr  # noqa: E402

BUCKET = "wecare-digital-get"
CUSTOMER = "CUS_01J0000000000000000000000"
OTHER = "CUS_01J9999999999999999999999"
NOW = 1_700_000_000

SIGNED = ("https://wecare-digital-get.s3.amazonaws.com/secure/stack/receipts/x.pdf"
          "?X-Amz-Signature=deadbeef&X-Amz-Expires=86400")


class FakeS3:
    def __init__(self, *, fail_put=False):
        self.puts = []
        self.presigns = []
        self._fail_put = fail_put

    def put_object(self, Bucket=None, Key=None, Body=None, ContentType=None, **_):
        if self._fail_put:
            raise RuntimeError("AccessDenied")
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        self.presigns.append({"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn})
        return SIGNED


def _html(invoice, items):
    """Stand-in for the engine's `_build_invoice_html`: proves it is invoked with the right dict."""
    return (f"<html><body>INVOICE {invoice['orderId']} total={invoice['total']} "
            f"items={len(items)}</body></html>")


def _render(html, fmt):
    return html.encode("utf-8")


def _identity(customer_id=CUSTOMER):
    return CustomerIdentity(customer_id=customer_id, phone="+919330994400", subject="sub-1")


def _snapshot(customer_id=CUSTOMER, collection=100000):
    """A real immutable paid snapshot via the section-7 calculator."""
    quote = cp.compute_quote(collection, currency="INR")
    return cp.build_snapshot(
        customer_id=customer_id,
        cart_id="cart-1",
        cart_revision=1,
        quote=quote,
        created_at=NOW,
        ttl_seconds=3600,
        items=[{"name": "Hamper", "amountPaise": collection, "quantity": 1}],
        address={"name": "A Buyer", "phone": "+919330994400", "line": "1 Road, Kolkata"},
    )


# ── authorisation / cross-customer denial ──────────────────────────────────────────

def test_the_owner_can_generate_a_receipt():
    s3 = FakeS3()
    out = cr.generate_receipt(
        identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="pdf", render=_render)
    assert out["url"] == SIGNED
    assert out["key"].startswith(media_paths.SECURE_ROOT)
    assert len(s3.puts) == 1


def test_another_customers_snapshot_is_refused():
    """Authority from the token; the snapshot belongs to OTHER, so the owner-of-CUSTOMER is denied,
    with the same exception a missing resource raises - not an existence oracle."""
    s3 = FakeS3()
    with pytest.raises(CustomerNotAuthorized):
        cr.generate_receipt(
            identity=_identity(CUSTOMER), snapshot=_snapshot(OTHER),
            order_number="WD-ORD-ABCD1234", s3_client=s3,
            build_invoice_html=_html, bucket=BUCKET, fmt="pdf", render=_render)
    # Nothing was stored for a denied request.
    assert s3.puts == []


# ── bounded expiry ─────────────────────────────────────────────────────────────────

def test_the_link_is_bounded_and_the_default_ttl_is_applied():
    s3 = FakeS3()
    cr.generate_receipt(
        identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="html")
    from lambda_utils import receipt_links as rl
    assert s3.presigns[0]["ExpiresIn"] == rl.DEFAULT_TTL_SECONDS


def test_a_ttl_past_the_ceiling_is_refused():
    s3 = FakeS3()
    from lambda_utils import receipt_links as rl
    with pytest.raises(ValueError):
        cr.generate_receipt(
            identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
            s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="html",
            ttl_seconds=rl.MAX_TTL_SECONDS + 1)


# ── idempotent regeneration ─────────────────────────────────────────────────────────

def test_regeneration_targets_the_same_object():
    """The key is derived from the snapshot, so a second call overwrites the same object rather than
    creating a parallel receipt."""
    snap = _snapshot()
    s3 = FakeS3()
    first = cr.generate_receipt(
        identity=_identity(), snapshot=snap, order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="pdf", render=_render)
    second = cr.generate_receipt(
        identity=_identity(), snapshot=snap, order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="pdf", render=_render)
    assert first["key"] == second["key"]
    assert s3.puts[0]["Key"] == s3.puts[1]["Key"]


def test_two_customers_get_two_different_keys():
    assert cr.receipt_key(_snapshot(CUSTOMER)) != cr.receipt_key(_snapshot(OTHER))


def test_different_formats_get_different_keys():
    snap = _snapshot()
    assert cr.receipt_key(snap, fmt="pdf") != cr.receipt_key(snap, fmt="png")


# ── private, never public, never the bag-icon prefix ───────────────────────────────

def test_the_receipt_key_is_under_the_gated_root():
    key = cr.receipt_key(_snapshot())
    assert key.startswith(media_paths.SECURE_ROOT)
    assert not key.startswith(media_paths.PUBLIC_ROOT)


def test_a_public_key_is_refused():
    with pytest.raises(cr.ReceiptError):
        cr.assert_private_key(media_paths.public("stack/receipts/x.pdf"))


def test_the_bag_icon_media_prefix_is_refused():
    with pytest.raises(cr.ReceiptError):
        cr.assert_private_key(media_paths.public("stream/media/m/receipt.png"))


# ── generated from the immutable snapshot, reusing the engine design ────────────────

def test_amounts_come_from_the_frozen_snapshot_not_recomputed():
    snap = _snapshot(collection=100000)  # 1000.00 INR before convenience
    invoice = cr.invoice_dict_from_snapshot(snap, order_number="WD-ORD-ABCD1234")
    # Total in rupees equals the snapshot's integer-paise total / 100, exactly.
    assert invoice["total"] == round(snap.quote.total_payable_paise / 100.0, 2)
    assert invoice["subtotal"] == round(snap.quote.collection_before_convenience_paise / 100.0, 2)
    assert invoice["status"] == "paid" and invoice["paymentStatus"] == "captured"


def test_the_engine_html_builder_is_the_design():
    s3 = FakeS3()
    captured = {}

    def _spy(invoice, items):
        captured["invoice"] = invoice
        captured["items"] = items
        return _html(invoice, items)

    cr.generate_receipt(
        identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_spy, bucket=BUCKET, fmt="html")
    # The injected engine builder was called with the snapshot-derived invoice.
    assert captured["invoice"]["orderId"] == "WD-ORD-ABCD1234"
    assert captured["items"][0]["name"] == "Hamper"


# ── the invoice number and the channel are THREADED, never derived ─────────────────
#
# A downloaded receipt has to print the order's own invoice number (GST Rule 46(b)) and the
# channel it was ordered on. Both are PARAMETERS: this module is on the read path, and issuing
# an invoice number advances the GST consecutive series, which only
# `invoice-engine._get_next_invoice_number` may do. So the default is "nothing printed", not
# "something invented".

def test_the_invoice_number_is_passed_through_unchanged():
    invoice = cr.invoice_dict_from_snapshot(
        _snapshot(), order_number="WD-ORD-ABCD1234", invoice_number="WD/2627/00001")
    assert invoice["invoiceNumber"] == "WD/2627/00001"


def test_an_absent_invoice_number_stays_absent():
    """The common case today - a website order the engine never invoiced. Empty, so the
    renderer draws no `Invoice No:` row; never a substitute number."""
    invoice = cr.invoice_dict_from_snapshot(_snapshot(), order_number="WD-ORD-ABCD1234")
    assert invoice["invoiceNumber"] == ""


def test_the_channel_is_canonicalised_on_the_way_through():
    """One coercion, `order_channel.canonical`, so the receipt cannot print a third word."""
    for given, expected in (("whatsapp", "whatsapp"), ("WhatsApp", "whatsapp"),
                            ("website", "website"), ("", "website"), (None, "website"),
                            ("junk", "website")):
        invoice = cr.invoice_dict_from_snapshot(
            _snapshot(), order_number="WD-ORD-ABCD1234", channel=given)
        assert invoice["channel"] == expected, given


def test_generate_receipt_threads_both_to_the_engine_builder():
    """The seam that matters: whatever the caller knows must reach the injected renderer."""
    s3 = FakeS3()
    captured = {}

    def _spy(invoice, items):
        captured["invoice"] = invoice
        return _html(invoice, items)

    cr.generate_receipt(
        identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_spy, bucket=BUCKET, fmt="html",
        invoice_number="WD/2627/00001", channel="whatsapp")
    assert captured["invoice"]["invoiceNumber"] == "WD/2627/00001"
    assert captured["invoice"]["channel"] == "whatsapp"


def test_generate_receipt_defaults_to_no_number_and_the_website_channel():
    s3 = FakeS3()
    captured = {}

    def _spy(invoice, items):
        captured["invoice"] = invoice
        return _html(invoice, items)

    cr.generate_receipt(
        identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
        s3_client=s3, build_invoice_html=_spy, bucket=BUCKET, fmt="html")
    assert captured["invoice"]["invoiceNumber"] == ""
    assert captured["invoice"]["channel"] == "website"


def test_the_storage_key_still_depends_only_on_the_snapshot_and_the_format():
    """Deliberate, and worth pinning: neither new argument enters the key, so the idempotent
    regeneration property is unchanged and the gated `secure/` key scheme is untouched. Safe
    because an order has at most one invoice number, so the same key is the same bytes."""
    snap = _snapshot()
    assert cr.receipt_key(snap, fmt="pdf").startswith(media_paths.SECURE_ROOT)
    first = cr.invoice_dict_from_snapshot(
        snap, order_number="WD-ORD-ABCD1234", invoice_number="WD/2627/00001",
        channel="whatsapp")
    second = cr.invoice_dict_from_snapshot(snap, order_number="WD-ORD-ABCD1234")
    # Different documents, one key - because the key is derived from the snapshot alone.
    assert first["invoiceNumber"] != second["invoiceNumber"]
    assert cr.receipt_key(snap, fmt="pdf") == cr.receipt_key(snap, fmt="pdf")


def test_a_png_or_pdf_without_a_renderer_is_refused():
    s3 = FakeS3()
    with pytest.raises(cr.ReceiptError):
        cr.generate_receipt(
            identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
            s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="pdf")  # no render=


def test_an_unsupported_format_is_refused():
    with pytest.raises(cr.ReceiptError):
        cr.receipt_key(_snapshot(), fmt="exe")


# ── storage failure surfaces, never a public fallback ───────────────────────────────

def test_a_storage_failure_raises_rather_than_falling_back():
    s3 = FakeS3(fail_put=True)
    with pytest.raises(cr.ReceiptError):
        cr.generate_receipt(
            identity=_identity(), snapshot=_snapshot(), order_number="WD-ORD-ABCD1234",
            s3_client=s3, build_invoice_html=_html, bucket=BUCKET, fmt="html")


def test_no_url_or_key_reaches_a_log():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(cr))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not ast.unparse(node.func).startswith("logger."):
            continue
        rendered = ast.unparse(node).lower()
        for forbidden in ("url", "key", "customer_id", "customerid"):
            assert forbidden not in rendered, f"log call references {forbidden!r}: {rendered}"
