import importlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'amplify/functions/messaging/whatsapp-business-api'))
sys.path.insert(0,str(ROOT/'tests'))
from coupon_fake_dynamo import FakeTable
from lambda_utils import customer_auth

@pytest.fixture
def copy_module():return importlib.import_module('flows.customer_invoice')


def test_foreign_order_refuses_before_invoice_read(copy_module):
    orders=FakeTable(key_attr='orderId');orders.seed({'orderId':'foreign','customerId':'other','orderNumber':'WD-OTHER','referenceId':'ref'})
    db=Mock();db.Table.return_value=orders
    with pytest.raises(customer_auth.CustomerNotAuthorized):copy_module.resolve(db,SimpleNamespace(customer_id='owner'),'foreign')
    assert db.Table.call_count==1


def invoice_fixture():
    orders=FakeTable(key_attr='orderId');orders.seed({'orderId':'order','customerId':'owner','orderNumber':'WD-ORDER','referenceId':'REF-OWN'})
    invoices=Mock();invoices.query.return_value={'Items':[{'invoiceId':'invoice'}]}
    invoices.get_item.return_value={'Item':{'invoiceId':'invoice','referenceId':'REF-OWN'}}
    assets=Mock();assets.get_item.return_value={'Item':{'s3Key':'secure/stack/invoices/wecare-digital-REF-OWN.png'}}
    db=Mock();db.Table.side_effect=lambda name: orders if name.endswith('OrderTable') else invoices if name.endswith('InvoicesTable') else assets
    return db,invoices,assets


def test_invoice_association_and_exact_private_asset_are_required(copy_module):
    db,invoices,assets=invoice_fixture();identity=SimpleNamespace(customer_id='owner')
    assert copy_module.resolve(db,identity,'order')[1]['invoiceId']=='invoice'
    invoices.get_item.return_value={'Item':{'invoiceId':'invoice','referenceId':'REF-FOREIGN'}}
    with pytest.raises(customer_auth.CustomerNotAuthorized):copy_module.resolve(db,identity,'order')
    invoices.get_item.return_value={'Item':{'invoiceId':'invoice','referenceId':'REF-OWN'}}
    assets.get_item.return_value={'Item':{'s3Key':'secure/stack/invoices/wecare-digital-REF-FOREIGN.png'}}
    assert copy_module.resolve(db,identity,'order')[1] is None


def test_ambiguous_invoice_association_is_not_selected_arbitrarily(copy_module):
    db,invoices,assets=invoice_fixture();invoices.query.return_value={'Items':[{'invoiceId':'a'},{'invoiceId':'b'}]}
    assert copy_module.resolve(db,SimpleNamespace(customer_id='owner'),'order')[1] is None
    invoices.get_item.assert_not_called();assets.get_item.assert_not_called()


def test_http_request_cannot_send_invoice(copy_module,monkeypatch):
    context=Mock();monkeypatch.setattr(copy_module.customer_orders,'_context',context)
    assert copy_module.handle({'requestContext':{}},Mock(),Mock(),Mock())['statusCode']==403
    context.assert_not_called()


def test_copy_reuses_invoice_and_fixed_recipient_once_per_day(copy_module,monkeypatch):
    table=FakeTable(key_attr='submissionId');db=Mock();db.Table.return_value=table
    identity=SimpleNamespace(customer_id='owner',phone='+919000000000')
    monkeypatch.setattr(copy_module.customer_orders,'_context',lambda token:(db,{},identity,{'contactId':'contact'}))
    monkeypatch.setattr(copy_module,'resolve',lambda *args:({'orderId':'order','orderNumber':'WD-ORDER'},
        {'invoiceId':'existing-invoice','s3Key':'secure/stack/invoices/wecare-digital-REF.png'}))
    template=Mock(return_value={'data':[{'name':'wecare_share_pdf','language':'en','status':'APPROVED','components':[{'type':'HEADER','format':'IMAGE'}]}]})
    sender=Mock();sender.invoke.side_effect=lambda **kwargs:{'Payload':io.BytesIO(b'{"statusCode":200}')}
    s3=Mock();s3.generate_presigned_url.return_value='https://signed.example/short-lived'
    event={'flowToken':'verified-session','orderId':'order','recipientPhone':'+919999999999','amount':9999}
    first=copy_module.handle(event,template,sender,s3);second=copy_module.handle(event,template,sender,s3)
    assert first['reference']==second['reference']
    assert sender.invoke.call_count==1 and len(table.rows)==1
    payload=json.loads(json.loads(sender.invoke.call_args.kwargs['Payload'])['body'])
    assert payload['recipientPhone']==identity.phone
    assert 'amount' not in payload and 'invoiceId' not in payload
    assert set(db.Table.call_args_list[0].args)=={'stack-wecare-digital-FlowSubmissionTable'}
    assert next(iter(table.rows.values()))['invoiceDeliveryStatus']=='ACCEPTED'
    assert s3.generate_presigned_url.call_args.kwargs['ExpiresIn']==300
