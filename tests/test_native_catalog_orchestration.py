"""Pre-payment orchestration: an unfulfillable service cannot create a payment."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(ROOT / 'tests'))
from coupon_fake_dynamo import FakeTable
from lambda_utils.ecommerce import service_requests

@pytest.fixture
def module(monkeypatch):
    path = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py'
    spec = importlib.util.spec_from_file_location('native_catalog_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    return module

@pytest.mark.parametrize('kind', ['SUBMIT_REQUEST', 'VAULT'])
def test_missing_order_or_unpaid_file_never_requests_payment(module, monkeypatch, kind):
    phone = '+919876543210'
    contact = FakeTable(key_attr='id')
    contact.seed({'id': 'contact', 'phone': phone, 'checkoutCustomerId': 'owner'})
    keys = FakeTable(key_attr='orderId')
    orders = FakeTable(key_attr='orderId', indexes={'customerId-createdAt-index': ('customerId', 'createdAt')})
    files = FakeTable(key_attr='fileId', indexes={'owner-created-index': ('ownerPhone', 'createdAt')})
    if kind == 'VAULT':
        files.seed({'fileId': 'already-paid', 'ownerPhone': phone[1:], 'ownerCustomerId': 'owner',
                    'status': 'active', 'vaultPaymentStatus': 'PAID', 'vaultAccessGrantId': 'existing'})
    tables = {'stack-wecare-digital-ContactsTable': contact,
              'stack-wecare-digital-WixOrderIds': keys,
              'stack-wecare-digital-OrderTable': orders,
              'stack-wecare-digital-SecureFilesTable': files}
    db = Mock();db.Table.side_effect=lambda name: tables[name]
    cognito = Mock();cognito.list_users.return_value = {'Users': [{'Enabled': True, 'Attributes': [
        {'Name': 'sub', 'Value': 'owner'}, {'Name': 'phone_number', 'Value': phone},
        {'Name': 'phone_number_verified', 'Value': 'true'}]}]}
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    sends = [];monkeypatch.setattr(module, '_send', lambda client,row,**body: sends.append(body))
    client = Mock()
    result = module.handle({'contactId': 'contact', 'senderPhone': phone, 'phoneNumberId': 'sender',
        'sourceMessageId': 'message', 'lines': [{'productId': next(iter(service_requests.SERVICE_PRODUCT_IDS)),
        'variantId': service_requests.SERVICE_VARIANT_BY_KIND[kind], 'quantity': 1}]}, client)
    assert result['outcome'] in ('SUBMIT_REQUEST_PARENT_ORDER_REQUIRED', 'VAULT_FILE_NOT_READY')
    client.invoke.assert_not_called()
    assert len(sends) == 1 and 'payment' in sends[0]['content'].lower()
    assert not any(str(k).startswith('NATIVESERVICEACTIVE#') for k in keys.rows)
