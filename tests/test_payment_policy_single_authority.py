"""Payment/order policy has one arithmetic authority and one seller/importer identity."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import business_identity, checkout_pricing  # noqa: E402

OUTBOUND = ROOT / "amplify" / "functions" / "messaging" / "outbound-whatsapp" / "handler.py"
INVOICE = ROOT / "amplify" / "functions" / "payments" / "invoice-engine" / "handler.py"
FRONTEND_CONSTANTS = ROOT / "src" / "config" / "constants.ts"


def test_seller_gstin_is_the_canonical_business_identity():
    assert business_identity.GSTIN == "19AAFFW7196L1Z8"
    assert checkout_pricing.SELLER_GSTIN == business_identity.GSTIN


def test_native_whatsapp_uses_canonical_importer_and_common_fee_calculator():
    source = OUTBOUND.read_text(encoding="utf-8")
    native = source.split("if is_interactive_payment and order_details:", 1)[1].split(
        "if is_template and template_name:", 1)[0]
    assert "business_identity.meta_importer_fields()" in native
    assert "81/2/7 Phears Ln" not in native
    assert "checkout_pricing.compute_quote(" in native
    assert "convenienceFeeRate" not in native
    assert "convenienceFeeGstRate" not in native
    assert "beneficiary_fallback_to_business_address" not in native


def test_invoice_engine_derives_new_collection_fee_from_common_calculator():
    source = INVOICE.read_text(encoding="utf-8")
    create = source.split("def create_invoice(", 1)[1].split("\ndef ", 1)[0]
    assert "checkout_pricing.compute_quote(" in create
    assert "collection * 0.025" not in create
    assert "conv_base * 0.18" not in create


def test_browser_does_not_export_a_second_fee_rate():
    source = FRONTEND_CONSTANTS.read_text(encoding="utf-8")
    assert "export const CONVENIENCE_FEE" not in source
