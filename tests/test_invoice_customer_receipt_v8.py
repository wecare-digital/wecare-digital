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

    def test_manual_whatsapp_items_have_no_repeated_thumbnail_and_fee_gst_is_tax(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("conv_net_paise = _paise(invoice.get('convenienceFeeNet'", source)
        self.assertIn("total_gst_paise = supply_gst_paise + conv_gst_paise", source)
        self.assertIn("'description': COMPANY[\"gstin\"]", source)
        self.assertNotIn("entry['image'] = {'link': template_media.ORDER_ITEM_IMAGE}", source)
        fee_block = source[source.index("if conv_net_paise > 0:"):source.index("total_gst_paise =", source.index("if conv_net_paise > 0:"))]
        self.assertNotIn("'image'", fee_block)

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
        self.assertIn('total_row(str(company.get("gstin") or ""), total_gst', source)
        self.assertNotIn('total_row("Taxable Value"', source)
        self.assertNotIn('total_row("Total Tax"', source)
        self.assertNotIn('total_row("Discount"', source)
        self.assertNotIn('total_row("Shipping"', source)

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
        self.assertIn("_gradient_roundrect", source)
        self.assertIn('"BILL TO"', source)
        self.assertIn("divider_x = width // 2", source)
        self.assertIn('total_row("Items Subtotal", subtotal)', source)
        self.assertIn('total_row(str(company.get("gstin") or ""), total_gst', source)

    def test_existing_png_media_keeps_png_display_extension(self):
        source = OUTBOUND.read_text(encoding="utf-8")
        self.assertIn("actual_ext = os.path.splitext(s3_key)[1].lower()", source)
        self.assertIn('display_filename = f"wecare-digital-{short_id}{actual_ext}"', source)

    def test_receipt_uses_dedicated_immutable_masthead_asset(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn(
            "secure/d/public/Invoice/brand/wecare-digital-receipt-masthead-v1.png",
            source,
        )
        self.assertIn("'logo_s3_key': RECEIPT_MASTHEAD_KEY", source)
        self.assertNotIn(
            "'logo_s3_key': media_paths.public('stream/media/m/wecare-digital.png')",
            source,
        )

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


    def test_receipt_gradient_avoids_python_pixel_loop(self):
        source = RECEIPT.read_text(encoding="utf-8")
        self.assertIn('Image.linear_gradient("L")', source)
        self.assertNotIn("pixels = band.load()", source)

    def test_preview_returns_before_invoice_number_is_consumed(self):
        source = ENGINE.read_text(encoding="utf-8")
        route = source.index("body.get('_action') == 'preview'")
        preview_return = source.index("if body.get('previewOnly'):")
        number = source.index("# ── Only now is a GST invoice number consumed")
        self.assertLess(route, number)
        self.assertLess(preview_return, number)
        block = source[preview_return:number]
        self.assertIn("'pricingAuthority': 'invoice-engine'", block)
        self.assertNotIn("_get_next_invoice_number", block)


if __name__ == "__main__":
    unittest.main()
