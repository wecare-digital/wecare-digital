"""Project provider-verified staff invoices into the shared customer order store.

A contact's stored checkoutCustomerId is the only website ownership join. A missing
join leaves a staff-owned order needing linkage; a payer phone never grants access.
"""
from copy import deepcopy
from decimal import Decimal
from lambda_utils import contact_key, customer_auth
from lambda_utils.comms.numbers import to_e164
from lambda_utils.ecommerce import finalization, order_keys, order_record


def build(*, invoice, attempt, contact, outcome, items, now):
    amount = finalization.integer_paise(attempt.get('verifiedCapturedPaise'))
    expected = finalization.integer_paise(attempt.get('amountPaise'))
    provider = str(attempt.get('verifiedProviderPaymentId') or '')
    contact_id = contact_key.resolve(contact)
    if (attempt.get('status') != 'PAYMENT_PAID' or not provider or amount is None
            or amount <= 0 or amount != expected
            or amount != order_record.paise_from_rupees(invoice.get('total'))
            or attempt.get('referenceId') != invoice.get('referenceId')
            or attempt.get('invoiceId') != invoice.get('invoiceId')
            or not outcome.get('hasOrder') or not outcome.get('orderId')
            or not order_keys.is_public_order_number(outcome.get('orderNumber'))
            or not contact_id or contact_id != invoice.get('contactId')
            or not to_e164(invoice.get('customerPhone'))
            or to_e164(contact.get('phone')) != to_e164(invoice.get('customerPhone'))):
        raise ValueError('invoice order evidence does not agree')
    linked = str(contact.get('checkoutCustomerId') or '')
    if linked and not customer_auth.is_cognito_subject(linked):
        raise ValueError('invalid website customer binding')
    stage = 'ORDER_FINALIZED' if linked else 'NEEDS_CUSTOMER_LINK'
    return {
        'orderId': outcome['orderId'], 'orderNumber': outcome['orderNumber'],
        'shortId': order_record.short_id(outcome['orderNumber']),
        'customerId': linked or str(attempt['customerId']), 'contactId': contact_id,
        'customerPhone': to_e164(invoice['customerPhone']),
        'customerName': str(invoice.get('customerName') or ''),
        'paymentAttemptId': attempt['paymentAttemptId'], 'providerPaymentId': provider,
        'referenceId': invoice['referenceId'], 'invoiceId': invoice['invoiceId'],
        'invoiceNumber': str(invoice.get('invoiceNumber') or ''),
        'amountPaise': amount, 'totalAmount': Decimal(amount) / 100, 'currency': 'INR',
        'paymentStatus': 'PAYMENT_PAID', 'orderStatus': 'processing', 'status': 'processing',
        'channel': 'whatsapp', 'source': 'manual', 'checkoutMode': attempt.get('checkoutMode', ''),
        'finalizationStage': stage,
        'createdAt': int(invoice.get('createdAt') or now), 'updatedAt': int(now),
        'invoiceSnapshot': deepcopy(invoice), 'items': deepcopy(items),
    }


def store(*, orders, row):
    """Create once. A replay can only promote the original contact to its verified account."""
    try:
        orders.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
        return
    except Exception as error:
        if not order_keys.is_conditional_failure(error):
            raise
    current = orders.get_item(Key={'orderId': row['orderId']}, ConsistentRead=True).get('Item') or {}
    for field in ('paymentAttemptId', 'providerPaymentId', 'referenceId', 'invoiceId',
                  'orderNumber', 'amountPaise', 'contactId'):
        if current.get(field) != row.get(field):
            raise ValueError('existing order belongs to another payment')
    if current.get('customerId') == row['customerId']:
        return
    if (current.get('finalizationStage') != 'NEEDS_CUSTOMER_LINK'
            or current.get('customerId') != row['contactId']
            or row['finalizationStage'] != 'ORDER_FINALIZED'):
        raise ValueError('existing order belongs to another customer')
    orders.update_item(Key={'orderId': row['orderId']},
        UpdateExpression='SET customerId = :customer, finalizationStage = :stage',
        ConditionExpression='customerId = :contact AND paymentAttemptId = :attempt',
        ExpressionAttributeValues={':customer': row['customerId'], ':stage': 'ORDER_FINALIZED',
            ':contact': row['contactId'], ':attempt': row['paymentAttemptId']})
