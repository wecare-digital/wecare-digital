"""Verified contact ownership links only that contact's eligible paid order history."""
from copy import deepcopy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "amplify/functions/shared"))
import pytest
from crm_fake_dynamo import FakeDynamo

OWNER = '12345678-1234-4234-8234-123456789abc'
PUBLIC = 'b5985cda-e76f-4d61-a8a9-97cb0d3225b8'
PHONE = '+919812345678'

def setup():
    table = FakeDynamo(keys={'orders':'orderId'},indexes={'orders':{'customerPhone':('customerPhone',None)}}).Table('orders')
    contact={'id':'contact-1','checkoutCustomerId':OWNER,'phone':PHONE,'customerUuid':PUBLIC}
    row={'orderId':'ord-1','customerPhone':PHONE,'customerId':'contact-1','contactId':'contact-1',
        'paymentStatus':'PAYMENT_PAID','finalizationStage':'NEEDS_CUSTOMER_LINK','orderStatus':'shipped',
        'paymentAttemptId':'attempt-1','providerPaymentId':'pay-1'}
    table.put_item(Item=row)
    return table,contact,row


def test_verified_link_preserves_fulfilment_and_is_idempotent():
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    assert subject.link(orders=table,contact=contact,customer_id=OWNER) == 1
    saved=table.get_item(Key={'orderId':'ord-1'})['Item']
    assert saved['customerId'] == OWNER
    assert saved['customerUuid'] == PUBLIC
    assert saved['orderStatus'] == 'shipped'
    assert saved['finalizationStage'] == 'ORDER_FINALIZED'
    assert subject.link(orders=table,contact=contact,customer_id=OWNER) == 0


@pytest.mark.parametrize('change',['foreign_contact','foreign_order','phone_only','unpaid','deleted','unbound','not_pending'])
def test_link_never_grants_ownership_from_a_phone_match(change):
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    if change=='foreign_contact': contact['checkoutCustomerId']='another-owner'
    if change=='foreign_order': row['customerId']='another-owner'
    if change=='phone_only': row['contactId']='another-contact'
    if change=='unpaid': row['paymentStatus']='pending'
    if change=='deleted': contact['isDeleted']=True
    if change=='unbound': contact.pop('checkoutCustomerId')
    if change=='not_pending': row['finalizationStage']='ORDER_FINALIZED'
    table.put_item(Item=row)
    before=deepcopy(table.rows)
    assert subject.link(orders=table,contact=contact,customer_id=OWNER) == 0
    assert table.rows == before


def test_link_drains_all_index_pages():
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    for n in range(105): table.put_item(Item={**row,'orderId':f'ord-{n+2}'})
    assert subject.link(orders=table,contact=contact,customer_id=OWNER) == 106


def test_concurrent_owner_change_cannot_be_overwritten(monkeypatch):
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    original=table.update_item
    def raced(**kw):
        table.rows['ord-1']['customerId']='another-owner'
        return original(**kw)
    monkeypatch.setattr(table,'update_item',raced)
    assert subject.link(orders=table,contact=contact,customer_id=OWNER) == 0
    assert table.rows['ord-1']['customerId']=='another-owner'


def test_durable_reconciliation_recovers_an_order_missed_by_the_phone_index(monkeypatch):
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    contacts=FakeDynamo(keys={'contacts':'id'}).Table('contacts')
    contacts.put_item(Item=contact)
    # Simulate GSI visibility lag: immediate profile linking cannot discover the row.
    monkeypatch.setattr(table,'query',lambda **kw:{'Items':[]})
    assert subject.link(orders=table,contact=contact,customer_id=OWNER)==0
    monkeypatch.setattr(table,'scan',lambda **kw:{'Items':[deepcopy(row)]},raising=False)
    assert subject.reconcile(orders=table,contacts=contacts)==1
    assert table.rows['ord-1']['customerId']==OWNER


def test_reconciler_drains_empty_scan_pages(monkeypatch):
    from lambda_utils.ecommerce import customer_order_link as subject
    table,contact,row=setup()
    contacts=FakeDynamo(keys={'contacts':'id'}).Table('contacts')
    contacts.put_item(Item=contact)
    pages=iter([{'Items':[],'LastEvaluatedKey':{'orderId':'previous'}},{'Items':[row]}])
    calls=[]
    def scan(**kw):
        calls.append(kw)
        return next(pages)
    monkeypatch.setattr(table,'scan',scan,raising=False)
    assert subject.reconcile(orders=table,contacts=contacts)==1
    assert calls[1]['ExclusiveStartKey']=={'orderId':'previous'}
