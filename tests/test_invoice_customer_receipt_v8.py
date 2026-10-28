import importlib.util
import io
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
RECEIPT = ROOT / "amplify/functions/payments/invoice-engine/receipt_layout.py"
OUTBOUND = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"
DEFAULT_COUPON = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/default_coupon.py"


def _round_half_up(paise: int, bps: int) -> int:
    exact = Decimal(paise) * Decimal(bps) / Decimal(10000)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class InvoiceCustomerReceiptContractTest(unittest.TestCase):
    def test_exact_mixed_gst_example_reconciles_to_429_paise(self):
        # One Rs1 line at 0% + one Rs1 line at 18%.
        item_subtotal = 200
        supply_gst = 18
        delight = 1
        express = 200

        collection_before_convenience = item_subtotal + supply_gst - delight + express
        self.assertEqual(collection_before_convenience, 417)

        fee_net = _round_half_up(collection_before_convenience, 250)
        fee_gst = _round_half_up(fee_net, 1800)
        self.assertEqual((fee_net, fee_gst), (10, 2))

        whatsapp_subtotal = item_subtotal + fee_net
        total_gst = supply_gst + fee_gst
        total = whatsapp_subtotal + total_gst + express - delight

        self.assertEqual(whatsapp_subtotal, 210)
        self.assertEqual(total_gst, 20)
        self.assertEqual(total, 429)

    def test_manual_whatsapp_items_show_brand_thumbnail_and_fee_gst_is_tax(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("conv_net_paise = _paise(invoice.get('convenienceFeeNet'", source)
        self.assertIn("total_gst_paise = supply_gst_paise + conv_gst_paise", source)
        self.assertIn("'description': 'GST'", source)
        self.assertIn("entry['image'] = {'link': template_media.DEFAULT_ORDER_ITEM_THUMBNAIL}", source)
        fee_block = source[source.index("if conv_net_paise > 0:"):source.index("total_gst_paise =", source.index("if conv_net_paise > 0:"))]
        self.assertIn("template_media.DEFAULT_ORDER_ITEM_THUMBNAIL", fee_block)

    def test_internal_invoice_api_retains_tax_facts(self):
        source = ENGINE.read_text(encoding="utf-8")
        for token in (
            "'convenienceFeeNet': _dec(convenience_fee_net)",
            "'convenienceFeeGst': _dec(convenience_fee_gst)",
            "'totalGst': _dec(tax + convenience_fee_gst)",
            "'delightTaxTreatment': default_coupon.DELIGHT_TAX_TREATMENT",
            "'taxAmount': item_tax",
            "'hsnSac': str(item.get('hsnSac') or '').strip()",
            "'gstStateCode': gst_code",
            "'portalUploadFormat': False",
            "'gstWorkpaper'] = _gst_workpaper(invoice, items)",
        ):
            self.assertIn(token, source)

        coupon = DEFAULT_COUPON.read_text(encoding="utf-8")
        self.assertIn('DELIGHT_TAX_TREATMENT = "POST_TAX_COMMERCIAL_DISCOUNT"', coupon)
        self.assertIn("'buyerGstin': buyer_gstin or ''", source)
        self.assertIn("checkout_pricing.validate_buyer_gstin", source)

    def test_gst_workpaper_refuses_to_guess_classification_or_portal_schema(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("'schemaVersion': 'wecare-gst-workpaper-v1'", source)
        self.assertIn("'portalUploadFormat': False", source)
        self.assertIn("'classificationComplete': classification_complete", source)
        self.assertIn("'resolved': bool(place_code and iso_subdivision)", source)
        self.assertIn("'hsnSac': hsn_sac", source)
        self.assertIn("'lineSupplyTax': _money_display(line_supply_tax)", source)

    def test_customer_receipt_is_compact_and_uses_customer_labels(self):
        source = RECEIPT.read_text(encoding="utf-8")
        self.assertIn('total_row("Items Subtotal", subtotal)', source)
        self.assertIn('total_row("Delight", -discount', source)
        self.assertIn('total_row("Express", shipping)', source)
        self.assertIn('total_row("Convenience Fee", convenience_net)', source)
        self.assertIn('total_row("GST", total_gst', source)
        self.assertNotIn('total_row("Taxable Value"', source)
        self.assertNotIn('total_row("Total Tax"', source)
        self.assertNotIn('total_row("Discount"', source)
        self.assertNotIn('total_row("Shipping"', source)

    def test_receipt_shows_the_full_payment_reference(self):
        # v9 geometry is pinned by test_receipt_v9_uses_fixed_reference_canvas.
        source = RECEIPT.read_text(encoding="utf-8")
        self.assertIn('ref = str(invoice.get("referenceId") or "").strip()', source)
        self.assertNotIn('ref = _strip_ref(invoice.get("referenceId"))', source)

    def test_preview_has_module_base64_and_tiny_delight_stays_visible(self):
        engine = ENGINE.read_text(encoding="utf-8")
        coupon = DEFAULT_COUPON.read_text(encoding="utf-8")
        self.assertIn("\nimport base64\n", engine)
        self.assertIn("effective = max(1, raw)", coupon)

    def test_receipt_png_has_real_transparent_exterior(self):
        spec = importlib.util.spec_from_file_location("receipt_layout_contract", RECEIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        invoice = {
            "paymentStatus": "captured",
            "paidAt": 1793061780,
            "referenceId": "WD-PAY-TEST",
            "providerPaymentId": "pay_test",
            "customerName": "Customer",
            "customerPhone": "+910000000000",
            "shippingAddress": "Kolkata, West Bengal 700012",
            "state": "West Bengal",
            "subtotal": "2.00",
            "discount": "0.01",
            "shipping": "2.00",
            "handling": "0.00",
            "tax": "0.18",
            "convenienceFee": "0.12",
            "convenienceFeeNet": "0.10",
            "convenienceFeeGst": "0.02",
            "total": "4.29",
        }
        items = [
            {"name": "Service", "amount": "1.00", "quantity": 1, "gstRate": 0},
            {"name": "Service", "amount": "1.00", "quantity": 1, "gstRate": 18},
        ]
        company = {
            "name": "WECARE.DIGITAL",
            "legal_name": "WECARE.DIGITAL BHARATWORKS",
            "gstin": "19AAFFW7196L1Z8",
            "pan": "AAFFW7196L",
            "email": "one@wecare.digital",
            "phone": "+91 93309 94400",
            "website": "https://wecare.digital",
        }
        png = module.render(
            invoice,
            items,
            company=company,
            font_paths={},
            logo_bytes=b"",
            ist_strftime=lambda _fmt, _epoch: "27-10-2026",
            canonical_status=lambda _status: "captured",
            amount_in_words=lambda _amount: "Rupees Four and Twenty-Nine Paise Only",
            source_label="WhatsApp",
        )
        image = Image.open(io.BytesIO(png)).convert("RGBA")
        alpha = image.getchannel("A")
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertEqual(alpha.getpixel((image.width - 1, image.height - 1)), 0)
        self.assertGreater(max(alpha.getdata()), 0)
        self.assertEqual(image.width, 1024)
        source = RECEIPT.read_text(encoding="utf-8")
        self.assertIn('"BILL TO"', source)
        self.assertIn('total_row("Items Subtotal", subtotal)', source)
        self.assertIn('total_row("GST", total_gst', source)

    def test_branded_receipt_uses_canonical_customer_display_id_only(self):
        engine = ENGINE.read_text(encoding="utf-8")
        receipt = RECEIPT.read_text(encoding="utf-8")

        self.assertIn("customer_id=_customer_id(invoice)", engine)
        self.assertIn('customer_id=""', receipt)
        self.assertIn('"Customer ID:"', receipt)
        self.assertIn("customer_id, font=small_bold", receipt)
        self.assertNotIn('"customerUuid"', receipt)

    def test_legacy_receipt_renderer_and_appearance_switch_are_removed(self):
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("RECEIPT_TRANSPARENT_BG", engine)
        self.assertNotIn("_transparent_receipt_enabled", engine)
        self.assertNotIn("DejaVuSansMono", engine)
        self.assertNotIn("grey-backdrop", engine)
        start = engine.index("def _generate_receipt_png(")
        end = engine.index("\ndef _amount_in_words(", start)
        renderer = engine[start:end]
        self.assertIn("return receipt_layout.render(", renderer)
        self.assertNotIn("if transparent", renderer)

    def test_preissue_preview_is_server_rendered_before_invoice_numbering(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("def preview_invoice(body: Dict, request_id: str) -> Dict:", source)
        self.assertIn("preview_body['previewOnly'] = True", source)
        self.assertIn("preview_png = _generate_receipt_png(preview_invoice_row, list(items))", source)
        self.assertIn("'previewImageBase64'", source)
        self.assertIn("'pricingAuthority': 'invoice-engine'", source)

        preview_guard = source.index("if body.get('previewOnly'):")
        numbering = source.index("invoice_number = _get_next_invoice_number", preview_guard)
        put_invoice = source.index("table.put_item(", numbering)
        self.assertLess(preview_guard, numbering)
        self.assertLess(numbering, put_invoice)

    def test_workspace_preview_uses_backend_and_keeps_hsn_advanced(self):
        payflow = (ROOT / "src/components/workspace/pay/PayFlow.tsx").read_text(encoding="utf-8")
        client = (ROOT / "src/api/client.ts").read_text(encoding="utf-8")
        self.assertIn("previewInvoiceEngine( request, true )", payflow)
        self.assertIn("Server authoritative", payflow)
        self.assertIn("No invoice number or record is created while previewing.", payflow)
        self.assertIn("Advanced tax details", payflow)
        self.assertIn('Express ({', payflow)
        self.assertIn("_action: 'preview'", client)

    def test_existing_png_media_keeps_png_display_extension(self):
        source = OUTBOUND.read_text(encoding="utf-8")
        self.assertIn("actual_ext = os.path.splitext(s3_key)[1].lower()", source)
        self.assertIn('display_filename = f"wecare-digital-{short_id}{actual_ext}"', source)

    def test_receipt_uses_dedicated_immutable_brand_mark_and_wordmark(self):
        engine = ENGINE.read_text(encoding="utf-8")
        receipt = RECEIPT.read_text(encoding="utf-8")
        self.assertIn(
            "secure/d/public/Invoice/brand/wecare-digital-receipt-mark-v2.png",
            engine,
        )
        self.assertIn("'logo_s3_key': RECEIPT_BRAND_MARK_KEY", engine)
        self.assertNotIn(
            "'logo_s3_key': media_paths.public('stream/media/m/wecare-digital.png')",
            engine,
        )
        self.assertIn('"WECARE", font=brand, fill=INK', receipt)
        self.assertIn('"DIGITAL", font=brand, fill=INK', receipt)
        # The dot stays the site's brand red, #ff0040, as in BrandLockup and the v8 receipt.
        self.assertIn("RED = (255, 0, 64)", receipt)
        self.assertIn('".", font=brand, fill=RED', receipt)


    def test_order_details_uses_owner_default_item_thumbnail(self):
        media = (ROOT / "amplify/functions/shared/lambda_utils/template_media.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("DEFAULT_ORDER_ITEM_THUMBNAIL", media)
        self.assertIn(
            "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png",
            media,
        )
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn(
            "entry['image'] = {'link': template_media.DEFAULT_ORDER_ITEM_THUMBNAIL}",
            source,
        )
        self.assertNotIn(
            "entry['image'] = {'link': template_media.PAYMENT_TEMPLATE_HEADER}",
            source,
        )


    def test_outbound_forces_owner_thumbnail_on_every_item(self):
        source = OUTBOUND.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_ORDER_ITEM_THUMBNAIL", source)
        self.assertIn("clean_item['image'] = {'link': DEFAULT_ORDER_ITEM_THUMBNAIL}", source)


    def test_media_trace_id_never_collapses_to_wa_idem_prefix(self):
        source = OUTBOUND.read_text(encoding="utf-8")
        self.assertIn("def _media_trace_id(message_id: str) -> str:", source)
        self.assertIn("short_id = _media_trace_id(message_id)", source)
        self.assertNotIn("short_id = message_id[:8]", source)

        start = source.index("def _media_trace_id")
        end = source.index("\ndef _upload_media", start)
        namespace = {"hashlib": __import__("hashlib")}
        exec(source[start:end], namespace)
        trace = namespace["_media_trace_id"](
            "wa-idem-invoice-WD-PAY-7A6F2104BEF148D4"
        )
        self.assertEqual(len(trace), 10)
        self.assertNotEqual(trace, "waidem")
        self.assertNotIn("wa-idem-", f"wecare-digital-{trace}.png")


    def test_issued_receipt_keys_are_unique_and_no_store(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("render_token = uuid.uuid4().hex[:12]", source)
        self.assertIn("no-store, max-age=0, must-revalidate", source)

    def test_customer_receipt_key_does_not_expose_internal_invoice_number(self):
        source = ENGINE.read_text(encoding="utf-8")
        stem = source[source.index("def _invoice_asset_stem"):source.index("def _next_asset_version")]
        self.assertNotIn("invoiceNumber", stem)
        self.assertNotIn("__{reference}", stem)
        self.assertIn('return f"{INVOICE_PREFIX}wecare-digital-{reference}-{date_token}-{time_token}"', stem)

    def test_receipt_v9_uses_fixed_reference_canvas(self):
        source = RECEIPT.read_text(encoding="utf-8")
        self.assertIn("BASE_W = 1024", source)
        self.assertIn("BASE_H = 1536", source)
        self.assertIn("Fresh fixed-coordinate renderer", source)

    def test_customer_receipt_key_uses_public_reference_date_time(self):
        source = ENGINE.read_text(encoding="utf-8")
        target = source[source.index("def _asset_target"):source.index("# ─── Generate Invoice Image")]
        self.assertIn("render_token = uuid.uuid4().hex[:12]", target)
        self.assertNotIn("-v{version}-r", target)


if __name__ == "__main__":
    unittest.main()
