"""A provider-paid manual invoice produces one complete, owned order record."""
from decimal import Decimal
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
