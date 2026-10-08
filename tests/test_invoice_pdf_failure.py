"""PDF render failures must not publish an incomplete financial document.

These exercise the existing admin endpoint with inert DynamoDB fixtures and PIL
transport fakes. No invoice number, payment state, S3 object or asset is written
when receipt rendering fails. The successful PDF bytes keep the existing wire
contract; the fake deliberately does not certify the visual renderer.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import boto3.dynamodb.conditions  # real Dynamo resource loads this; fixture mocks construction

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
PRIVATE_DETAIL = "Private Customer, 17 Confidential Street"
PDF_BYTES = b"%PDF-1.4\nexisting rendered receipt bytes\n%%EOF"
EVENT = {
    "rawPath": "/invoices/inv-fixture/generate-pdf",
    "requestContext": {"http": {"method": "POST"}},
    "pathParameters": {"invoiceId": "inv-fixture"},
}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "amplify/functions/shared"))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    name = "_invoice_pdf_failure_engine"
    spec = importlib.util.spec_from_file_location(name, FUNCTION)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)
    invoices = MagicMock()
    invoices.get_item.return_value = {"Item": {
        "invoiceId": "inv-fixture", "invoiceNumber": "WD/2627/00001",
        "referenceId": "ref-fixture", "customerName": PRIVATE_DETAIL,
    }}
    items = MagicMock()
    items.query.return_value = {"Items": [{"itemIndex": 0, "name": PRIVATE_DETAIL}]}
    assets = MagicMock()
    tables = {module.INVOICES_TABLE: invoices, module.INVOICE_ITEMS_TABLE: items,
              module.INVOICE_ASSETS_TABLE: assets}
    module.dynamodb = MagicMock()
    module.dynamodb.Table.side_effect = tables.__getitem__
    module.s3 = MagicMock()
    module.logger = MagicMock()
    module._signed_invoice_url = MagicMock(return_value="https://example.test/temporary")
    module._generate_receipt_png = MagicMock(return_value=b"fixture PNG")
    module._build_invoice_html = MagicMock()
    from lambda_utils import middleware
    auth = MagicMock(return_value=None)
    monkeypatch.setattr(middleware, "require_auth", auth)
    image = MagicMock()
    image.save.side_effect = lambda target, **kwargs: target.write(PDF_BYTES)
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")
    pil_image.open = MagicMock(return_value=image)
    pil.Image = pil_image
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image)
    module._flatten_onto_white = MagicMock(return_value=image)
    return module, invoices, items, assets, auth, image, pil_image


@pytest.mark.parametrize("failure_stage", ["receipt", "decode", "flatten", "encode"])
def test_failed_pdf_is_retryable_and_never_published(engine, failure_stage):
    module, invoices, items, assets, auth, image, pil_image = engine
    target = {"receipt": module._generate_receipt_png, "decode": pil_image.open,
              "flatten": module._flatten_onto_white, "encode": image.save}[failure_stage]
    target.side_effect = RuntimeError(PRIVATE_DETAIL)

    response = module.handler(EVENT, None)

    assert response["statusCode"] == 503, response
    body = json.loads(response["body"])
    assert body["code"] == "INVOICE_PDF_RENDER_FAILED"
    assert body["retryable"] is True
    assert "HTML or image" in body["help"]
    assert not {"pdfUrl", "s3Key", "html"} & body.keys()
    assert PRIVATE_DETAIL not in response["body"]
    assert PRIVATE_DETAIL not in str(module.logger.mock_calls)
    module.s3.put_object.assert_not_called()
    module._signed_invoice_url.assert_not_called()
    assets.put_item.assert_not_called()
    invoices.put_item.assert_not_called()
    invoices.update_item.assert_not_called()
    items.put_item.assert_not_called()
    module._build_invoice_html.assert_not_called()
    assert [c.args[0] for c in module.dynamodb.Table.call_args_list] == [
        module.INVOICES_TABLE, module.INVOICE_ITEMS_TABLE]
    auth.assert_called_once_with(EVENT, required_role="Admin")


def test_success_preserves_primary_pdf_bytes_and_asset_contract(engine):
    module, invoices, items, assets, auth, image, pil_image = engine

    response = module.handler(EVENT, None)

    assert response["statusCode"] == 200, response
    body = json.loads(response["body"])
    assert body["invoiceId"] == "inv-fixture"
    assert body["pdfUrl"] == "https://example.test/temporary"
    key = f"{module.INVOICE_PREFIX}wecare-digital-ref-fixture.pdf"
    assert body["s3Key"] == key
    module.s3.put_object.assert_called_once_with(
        Bucket=module.MEDIA_BUCKET, Key=key, Body=PDF_BYTES,
        ContentType="application/pdf", CacheControl="max-age=86400")
    module._signed_invoice_url.assert_called_once_with(key, "inv-fixture", "local")
    asset = assets.put_item.call_args.kwargs["Item"]
    assert asset["assetType"] == "pdf" and asset["s3Key"] == key
    assert "url" not in asset
    assert image.save.call_args.kwargs == {"format": "PDF", "resolution": 150}
    invoices.update_item.assert_not_called()
    module._build_invoice_html.assert_not_called()


def test_existing_admin_authorization_still_precedes_rendering(engine):
    module, invoices, items, assets, auth, image, pil_image = engine
    rejection = {"statusCode": 403, "body": "forbidden"}
    auth.return_value = rejection

    assert module.handler(EVENT, None) is rejection
    module.dynamodb.Table.assert_not_called()
    module._generate_receipt_png.assert_not_called()
    module.s3.put_object.assert_not_called()
    assets.put_item.assert_not_called()
