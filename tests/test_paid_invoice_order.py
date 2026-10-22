"""A provider-paid manual invoice produces one complete, owned order record."""
from decimal import Decimal
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pytest
from lambda_utils.ecommerce import paid_invoice_order as subject

OWNER = '12345678-1234-4234-8234-123456789abc'

def inputs():
    return dict(invoice={'invoiceId':'inv-1','referenceId':'ref-1','customerPhone':'+919812345678',
        'contactId':'contact-1','total':Decimal('4.66'),'discount':Decimal('0.01'),
        'couponCode':'DELIGHT','invoiceNumber':'WD/2627/00004','createdAt':123},
        attempt={'paymentAttemptId':'attempt-1','referenceId':'ref-1','invoiceId':'inv-1',
            'customerId':'contact-1','amountPaise':466,'currency':'INR',
            'status':'PAYMENT_PAID','verifiedCapturedPaise':466,'verifiedProviderPaymentId':'pay-1'},
        contact={'id':'contact-1','phone':'+919812345678','checkoutCustomerId':OWNER},
        outcome={'hasOrder':True,'orderId':'internal-order-1','orderNumber':'WD-ORD-ABCD2345'},
        items=[{'name':'Goods','amount':Decimal('3'),'quantity':1}], now=456)

def test_order_uses_saved_customer_identity_and_exact_verified_total():
    row = subject.build(**inputs())
    assert row['customerId'] == OWNER
    assert row['amountPaise'] == 466
    assert row['paymentStatus'] == 'PAYMENT_PAID'
    assert row['invoiceId'] == 'inv-1'
    assert row['invoiceSnapshot']['couponCode'] == 'DELIGHT'
    assert row['finalizationStage'] == 'ORDER_FINALIZED'

def test_unlinked_contact_remains_staff_owned_until_a_verified_account_link_exists():
    args = inputs()
    del args['contact']['checkoutCustomerId']
    row = subject.build(**args)
    assert row['customerId'] == 'contact-1'
    assert row['finalizationStage'] == 'NEEDS_CUSTOMER_LINK'

PUBLIC_ID = 'abcdef12-3456-4789-8abc-def123456789'


def test_public_customer_id_is_carried_from_the_attempt():
    args = inputs()
    args['attempt']['customerUuid'] = PUBLIC_ID
    row = subject.build(**args)
    assert row['customerUuid'] == PUBLIC_ID


def test_public_customer_id_falls_back_to_the_contact():
    args = inputs()
    args['contact']['customerUuid'] = PUBLIC_ID
    row = subject.build(**args)
    assert row['customerUuid'] == PUBLIC_ID


def test_public_customer_id_is_absent_when_neither_carries_one():
    row = subject.build(**inputs())
    # Absent rather than empty - a legacy row carried none, and the conditional emit keeps this
    # row byte-identical to one written before the field existed.
    assert 'customerUuid' not in row


def test_a_junk_public_customer_id_is_dropped_not_stored():
    args = inputs()
    args['attempt']['customerUuid'] = 'not-a-uuid'
    row = subject.build(**args)
    assert 'customerUuid' not in row


@pytest.mark.parametrize('change', ['amount', 'payment', 'reference', 'contact'])
def test_projection_refuses_disagreeing_evidence(change):
    args = inputs()
    if change == 'amount': args['attempt']['verifiedCapturedPaise'] = 467
    if change == 'payment': args['attempt']['status'] = 'PAYMENT_REQUEST_SENT'
    if change == 'reference': args['attempt']['referenceId'] = 'someone-else'
    if change == 'contact': args['contact']['phone'] = '+919999999999'
    with pytest.raises(ValueError): subject.build(**args)


def test_order_replay_preserves_fulfilment_and_cannot_duplicate():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from crm_fake_dynamo import FakeDynamo
    orders = FakeDynamo(keys={'orders':'orderId'}).Table('orders')
    row = subject.build(**inputs())
    subject.store(orders=orders, row=row)
    orders.update_item(Key={'orderId':row['orderId']}, UpdateExpression='SET orderStatus = :s',
        ExpressionAttributeValues={':s':'shipped'})
    subject.store(orders=orders, row=row)
    saved = orders.get_item(Key={'orderId':row['orderId']})['Item']
    assert saved['orderStatus'] == 'shipped'


def test_replay_repairs_stale_paid_order_snapshot_without_duplication():
    from crm_fake_dynamo import FakeDynamo
    args = inputs()
    args['attempt']['channel'] = 'whatsapp'
    args['invoice']['channel'] = 'website'
    args['invoice']['notes'] = 'Cancelled: native-pay live proof; unpaid, no money moved'
    desired = subject.build(**args)
    orders = FakeDynamo(keys={'orders':'orderId'}).Table('orders')
    stale = dict(desired)
    stale['channel'] = 'whatsapp'
    stale['invoiceSnapshot'] = dict(args['invoice'])
    stale['orderStatus'] = 'shipped'
    orders.put_item(Item=stale)

    repaired = subject.store(orders=orders, row=desired)
    assert len(orders.rows) == 1
    assert repaired['orderId'] == desired['orderId']
    assert repaired['paymentAttemptId'] == desired['paymentAttemptId']
    assert repaired['providerPaymentId'] == desired['providerPaymentId']
    assert repaired['referenceId'] == desired['referenceId']
    assert repaired['invoiceId'] == desired['invoiceId']
    assert repaired['orderNumber'] == desired['orderNumber']
    assert repaired['orderStatus'] == 'shipped'
    assert repaired['channel'] == 'whatsapp'
    assert repaired['invoiceSnapshot']['channel'] == 'whatsapp'
    assert 'notes' not in repaired['invoiceSnapshot']


def test_only_the_original_contact_can_promote_an_unlinked_order():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from crm_fake_dynamo import FakeDynamo
    orders = FakeDynamo(keys={'orders':'orderId'}).Table('orders')
    args = inputs()
    del args['contact']['checkoutCustomerId']
    subject.store(orders=orders, row=subject.build(**args))
    linked = subject.build(**inputs())
    subject.store(orders=orders, row=linked)
    assert orders.get_item(Key={'orderId':linked['orderId']})['Item']['customerId'] == OWNER
    linked['customerId'] = 'another-owner'
    with pytest.raises(ValueError): subject.store(orders=orders, row=linked)

PUBLIC_UUID = 'b5985cda-e76f-4d61-a8a9-97cb0d3225b8'

def test_public_customer_uuid_reaches_order_and_invoice_snapshot():
    args = inputs()
    args['contact']['customerUuid'] = PUBLIC_UUID
    row = subject.build(**args)
    assert row['customerUuid'] == PUBLIC_UUID
    assert row['invoiceSnapshot']['customerUuid'] == PUBLIC_UUID


def test_verified_paid_attempt_overrides_stale_invoice_origin_metadata():
    args = inputs()
    args['attempt']['channel'] = 'whatsapp'
    args['invoice']['channel'] = 'website'
    args['invoice']['notes'] = 'Cancelled: native-pay live proof; unpaid, no money moved'
    row = subject.build(**args)
    assert row['channel'] == 'whatsapp'
    assert row['invoiceSnapshot']['channel'] == 'whatsapp'
    assert 'notes' not in row['invoiceSnapshot']


def test_non_contradictory_invoice_note_is_preserved():
    args = inputs()
    args['attempt']['channel'] = 'whatsapp'
    args['invoice']['channel'] = 'website'
    args['invoice']['notes'] = 'Customer requested GST copy by email'
    row = subject.build(**args)
    assert row['invoiceSnapshot']['channel'] == 'whatsapp'
    assert row['invoiceSnapshot']['notes'] == 'Customer requested GST copy by email'

@pytest.mark.parametrize('change', ['currency', 'attempt_owner', 'attempt_contact', 'deleted_contact', 'provider_conflict'])
def test_projection_refuses_cross_domain_evidence(change):
    args = inputs()
    if change == 'currency': args['attempt']['currency'] = 'USD'
    if change == 'attempt_owner': args['attempt']['customerId'] = 'another-contact'
    if change == 'attempt_contact': args['attempt']['contactId'] = 'another-contact'
    if change == 'deleted_contact': args['contact']['deletedAt'] = 100
    if change == 'provider_conflict': args['outcome']['providerPaymentId'] = 'another-payment'
    with pytest.raises(ValueError): subject.build(**args)


def materialization_tables():
    from crm_fake_dynamo import FakeDynamo
    from lambda_utils.ecommerce import order_keys
    args = inputs()
    args['contact']['customerUuid'] = PUBLIC_UUID
    fake = FakeDynamo(keys={'invoices':'invoiceId','items':'itemId','contacts':'id',
        'attempts':'paymentAttemptId','keys':'orderId','orders':'orderId'},
        indexes={'invoices':{'referenceId-index':('referenceId', None)}}, base_query_tables={'items'})
    tables = {name: fake.Table(name) for name in (
        'invoices', 'items', 'contacts', 'attempts', 'keys', 'orders')}
    tables['invoices'].put_item(Item=args['invoice'])
    tables['contacts'].put_item(Item=args['contact'])
    tables['attempts'].put_item(Item=args['attempt'])
    tables['items'].put_item(Item={'itemId':'item-1','invoiceId':'inv-1','name':'Goods'})
    order_keys.reserve_payment_reference(tables['keys'],reference_id='ref-1',payment_attempt_id='attempt-1')
    order_keys.claim_order_for_payment(tables['keys'],payment_attempt_id='attempt-1',
        order_id='internal-order-1',provider_transaction_id='pay-1')
    order_keys.record_order_number_on_claim(tables['keys'],payment_attempt_id='attempt-1',
        order_number='WD-ORD-ABCD2345')
    return fake,tables


def test_materialization_preserves_claim_and_completes_all_links_on_replay():
    fake,tables = materialization_tables()
    first = subject.materialize(**tables,reference_id='ref-1',now=456)
    assert first['orderId'] == 'internal-order-1'
    assert first['orderNumber'] == 'WD-ORD-ABCD2345'
    assert tables['invoices'].get_item(Key={'invoiceId':'inv-1'})['Item']['customerUuid'] == PUBLIC_UUID
    tables['orders'].update_item(Key={'orderId':first['orderId']},UpdateExpression='SET orderStatus = :s',
        ExpressionAttributeValues={':s':'shipped'})
    second = subject.materialize(**tables,reference_id='ref-1',now=789)
    saved = tables['orders'].get_item(Key={'orderId':first['orderId']})['Item']
    assert second['orderId'] == first['orderId']
    assert saved['orderStatus'] == 'shipped'
    assert len(tables['orders'].rows) == 1
    assert tables['attempts'].get_item(Key={'paymentAttemptId':'attempt-1'})['Item']['orderId'] == first['orderId']


def test_materialization_refuses_missing_order_claim_without_minting_one():
    fake,tables = materialization_tables()
    tables['keys'].rows.pop('PAYMENTATTEMPT#attempt-1')
    with pytest.raises(ValueError): subject.materialize(**tables,reference_id='ref-1',now=456)
    assert not tables['orders'].rows


def test_replay_enriches_legacy_order_and_invoice_without_changing_fulfilment():
    fake,tables=materialization_tables()
    subject.materialize(**tables,reference_id='ref-1',now=456)
    tables['orders'].rows['internal-order-1'].pop('customerUuid')
    tables['orders'].rows['internal-order-1']['orderStatus']='shipped'
    tables['invoices'].rows['inv-1'].pop('customerUuid')
    subject.materialize(**tables,reference_id='ref-1',now=789)
    assert tables['orders'].rows['internal-order-1']['customerUuid']==PUBLIC_UUID
    assert tables['orders'].rows['internal-order-1']['orderStatus']=='shipped'
    assert tables['invoices'].rows['inv-1']['customerUuid']==PUBLIC_UUID


def test_account_binding_during_order_insert_is_completed_before_projection_returns(monkeypatch):
    fake,tables=materialization_tables()
    tables['contacts'].rows['contact-1'].pop('checkoutCustomerId')
    original=tables['orders'].put_item
    def bind_while_inserting(**kw):
        tables['contacts'].rows['contact-1']['checkoutCustomerId']=OWNER
        return original(**kw)
    monkeypatch.setattr(tables['orders'],'put_item',bind_while_inserting)
    result=subject.materialize(**tables,reference_id='ref-1',now=456)
    assert result['finalizationStage']=='ORDER_FINALIZED'
    assert tables['orders'].rows['internal-order-1']['customerId']==OWNER


def test_promotion_populates_uuid_on_the_saved_order():
    args=inputs()
    args['contact'].pop('checkoutCustomerId')
    from crm_fake_dynamo import FakeDynamo
    orders=FakeDynamo(keys={'orders':'orderId'}).Table('orders')
    subject.store(orders=orders,row=subject.build(**args))
    linked=inputs();linked['contact']['customerUuid']=PUBLIC_UUID
    subject.store(orders=orders,row=subject.build(**linked))
    assert orders.rows['internal-order-1']['customerUuid']==PUBLIC_UUID


def test_materialization_carries_contact_and_public_uuid_into_the_payment_attempt():
    fake,tables=materialization_tables()
    subject.materialize(**tables,reference_id='ref-1',now=456)
    saved=tables['attempts'].get_item(Key={'paymentAttemptId':'attempt-1'})['Item']
    assert saved['contactId']=='contact-1'
    assert saved['customerUuid']==PUBLIC_UUID
    # Original financial ownership is preserved; the website binding is on the order.
    assert saved['customerId']=='contact-1'
