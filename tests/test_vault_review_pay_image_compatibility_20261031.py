"""Regression: Vault native Review & Pay keeps Pay Flow media without Meta error 131009.

Meta rejected a real Vault payment on 31 Oct 2026 because its item had BOTH
retailer_id and image. The successful staff Pay Flow used the same approved
header and thumbnail without a retailer_id. No AWS, customer, or network access
is needed to exercise the native service payment-details function.
"""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py"
MEDIA = ROOT / "amplify/functions/shared/lambda_utils/template_media.py"
OUTBOUND = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"
INVOICES = ROOT / "amplify/functions/payments/invoice-engine/handler.py"


def _payment_details():
    """Execute the isolated pure builder, without importing live AWS clients."""
    source = CATALOG.read_text(encoding="utf-8")
    module = ast.parse(source)
    builder = next(node for node in module.body if
                   isinstance(node, ast.FunctionDef) and node.name == "payment_details")
    namespace = {"re": re, "Any": Any}
    exec(compile(ast.Module(body=[builder], type_ignores=[]), str(CATALOG), "exec"),
         namespace)
    return namespace["payment_details"]


def _media_constant(name: str) -> str:
    module = ast.parse(MEDIA.read_text(encoding="utf-8"))
    value = next(node.value for node in module.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == name
                         for target in node.targets))
    return ast.literal_eval(value)


def test_vault_native_payment_matches_working_pay_flow_images_and_total():
    row = {"kind": "VAULT", "productId": "owned-service-product", "variantId": "RVT6K4Q8"}
    quote = SimpleNamespace(collection_before_convenience_paise=8254,
                            convenience_fee_paise=206,
                            convenience_gst_paise=37,
                            total_payable_paise=8497)
    details = _payment_details()(row, quote, "WD-PAY-TEST-VAULT", "verified-payment-config",
                                 1793400000,
                                 invoice_lines={"lines": [{"unitPricePaise": 4900, "quantity": 1}],
                                                "supplyGstPaise": 882, "discountPaise": 28,
                                                "deliveryPaise": 2500})
    assert details["type"] == "digital-goods"
    assert details["currency"] == "INR"
    assert details["total_amount"] == {"value": 8497, "offset": 100}
    assert details["order"]["subtotal"]["value"] == 5106
    assert details["order"]["tax"]["value"] == 919
    assert details["order"]["shipping"]["value"] == 2500
    assert details["order"]["discount"]["value"] == 28
    item, convenience = details["order"]["items"]
    assert item["name"] == "Vault"
    assert item["amount"] == {"value": 4900, "offset": 100}
    assert item["image"] == {"link": _media_constant("DEFAULT_ORDER_ITEM_THUMBNAIL")}
    assert "retailer_id" not in item and "catalog_id" not in item
    assert "retailer_id" not in convenience and "image" not in convenience
    # Do not mutate the identity of the original catalog service selection.
    assert row == {"kind": "VAULT", "productId": "owned-service-product",
                   "variantId": "RVT6K4Q8"}


def test_drop_docs_uses_same_compatible_service_media_shape():
    quote = SimpleNamespace(collection_before_convenience_paise=20000,
                            convenience_fee_paise=500,
                            convenience_gst_paise=90,
                            total_payable_paise=20590)
    details = _payment_details()(
        {"kind": "DROP_DOCS", "productId": "owned-product", "variantId": "RDD9P3M7"},
        quote, "WD-PAY-TEST-DROPDOC", "verified-payment-config", 1793400000,
        invoice_lines={"lines": [{"unitPricePaise": 20000, "quantity": 1}]})
    assert details["total_amount"]["value"] == 20590
    assert details["order"]["items"][0]["image"]["link"] == _media_constant(
        "DEFAULT_ORDER_ITEM_THUMBNAIL")
    assert all("retailer_id" not in item for item in details["order"]["items"])


def test_payment_template_header_and_item_thumbnail_remain_unchanged():
    header = _media_constant("SHARED_TEMPLATE_HEADER")
    thumbnail = _media_constant("DEFAULT_ORDER_ITEM_THUMBNAIL")
    assert header.endswith("/whatsapp-header.png")
    assert thumbnail.endswith("/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png")
    assert header != thumbnail

    outbound = OUTBOUND.read_text(encoding="utf-8")
    pay_flow = INVOICES.read_text(encoding="utf-8")
    assert "FIXED_CHECKOUT_HEADER = ORDER_CATALOG_HEADER_IMAGE" in outbound
    assert "clean_item['image'] = {'link': DEFAULT_ORDER_ITEM_THUMBNAIL}" in outbound
    assert "'headerImageUrl': template_media.PAYMENT_TEMPLATE_HEADER" in pay_flow
    assert "entry['image'] = {'link': template_media.DEFAULT_ORDER_ITEM_THUMBNAIL}" in pay_flow
