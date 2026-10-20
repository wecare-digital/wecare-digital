"""The retired invoice PDF endpoint must stay fail-closed and side-effect free."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
EVENT = {
    "rawPath": "/invoices/inv-fixture/generate-pdf",
    "requestContext": {"http": {"method": "POST"}},
    "pathParameters": {"invoiceId": "inv-fixture"},
}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "amplify/functions/shared"))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    name = "_invoice_pdf_retired_engine"
    spec = importlib.util.spec_from_file_location(name, FUNCTION)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)
    module.dynamodb = MagicMock()
    module.s3 = MagicMock()
    from lambda_utils import middleware
    auth = MagicMock(return_value=None)
    monkeypatch.setattr(middleware, "require_auth", auth)
    return module, auth


def test_pdf_endpoint_is_retired_and_writes_nothing(engine):
    module, auth = engine
    response = module.handler(EVENT, None)
    assert response["statusCode"] == 410
    assert json.loads(response["body"]) == {
        "error": "Invoice PDF generation is retired. Use the invoice image.",
        "code": "INVOICE_IMAGE_ONLY",
    }
    module.dynamodb.Table.assert_not_called()
    module.s3.put_object.assert_not_called()
    auth.assert_called_once_with(EVENT, required_role="Admin")


def test_admin_authorization_still_precedes_pdf_retirement(engine):
    module, auth = engine
    rejection = {"statusCode": 403, "body": "forbidden"}
    auth.return_value = rejection
    assert module.handler(EVENT, None) is rejection
    module.dynamodb.Table.assert_not_called()
    module.s3.put_object.assert_not_called()
