"""Attach historical orders only after a verified contact/account binding exists."""
from boto3.dynamodb.conditions import Attr, Key
from lambda_utils import contact_key, customer_auth
from lambda_utils.comms.numbers import to_e164
from lambda_utils.ecommerce import order_keys
from lambda_utils.identity import customer_uuid


def _bound(contact, customer_id):
    return (customer_auth.is_cognito_subject(customer_id)
        and contact.get('checkoutCustomerId') == customer_id
        and contact.get('deletedAt') is None and not contact.get('isDeleted')
        and bool(contact_key.resolve(contact)) and bool(to_e164(contact.get('phone'))))


def _promote(orders, row, contact, customer_id):
    contact_id = contact_key.resolve(contact)
    if (not _bound(contact, customer_id) or row.get('contactId') != contact_id
            or row.get('customerId') != contact_id
            or row.get('finalizationStage') != 'NEEDS_CUSTOMER_LINK'
            or row.get('paymentStatus') != 'PAYMENT_PAID'
            or not row.get('paymentAttemptId') or not row.get('providerPaymentId')):
        return False
    values = {':owner': customer_id, ':contact': contact_id,
        ':waiting': 'NEEDS_CUSTOMER_LINK', ':done': 'ORDER_FINALIZED',
        ':paid': 'PAYMENT_PAID', ':attempt': row['paymentAttemptId'], ':provider': row['providerPaymentId']}
    update = 'SET customerId = :owner, finalizationStage = :done'
    public_uuid = customer_uuid.from_contact(contact)
    if public_uuid:
        update += ', customerUuid = :uuid'
        values[':uuid'] = public_uuid
    try:
        orders.update_item(Key={'orderId': row['orderId']}, UpdateExpression=update,
            ConditionExpression=('contactId = :contact AND customerId = :contact '
                'AND finalizationStage = :waiting AND paymentStatus = :paid '
                'AND paymentAttemptId = :attempt AND providerPaymentId = :provider'),
            ExpressionAttributeValues=values)
        return True
    except Exception as error:
        if not order_keys.is_conditional_failure(error):
            raise
        return False


def link(*, orders, contact, customer_id):
    """Promote eligible orders after authenticated profile binding. Phone only discovers rows."""
    if not _bound(contact, customer_id):
        return 0
    count = 0
    kwargs = {'IndexName': 'customerPhone',
        'KeyConditionExpression': Key('customerPhone').eq(to_e164(contact['phone'])), 'Limit': 100}
    while True:
        page = orders.query(**kwargs)
        for row in page.get('Items') or []:
            count += int(_promote(orders, row, contact, customer_id))
        last = page.get('LastEvaluatedKey')
        if not last:
            return count
        kwargs['ExclusiveStartKey'] = last


def reconcile(*, orders, contacts):
    """Scheduled repair covers index lag and profile/projection races. No payment or send.

    The profile role cannot scan. Only the existing private webhook worker runs this
    pending-only scan; contact reads are consistent and every ownership write is conditional.
    """
    count = 0
    fields = ['orderId', 'contactId', 'customerId', 'paymentStatus', 'finalizationStage',
              'paymentAttemptId', 'providerPaymentId']
    kwargs = {'FilterExpression': Attr('finalizationStage').eq('NEEDS_CUSTOMER_LINK'),
        'ProjectionExpression': ', '.join(fields), 'Limit': 100, 'ConsistentRead': True}
    while True:
        page = orders.scan(**kwargs)
        for row in page.get('Items') or []:
            cid = row.get('contactId')
            if not cid:
                continue
            contact = contacts.get_item(Key={'id': cid}, ConsistentRead=True).get('Item') or {}
            count += int(_promote(orders, row, contact, str(contact.get('checkoutCustomerId') or '')))
        last = page.get('LastEvaluatedKey')
        if not last:
            return count
        kwargs['ExclusiveStartKey'] = last
