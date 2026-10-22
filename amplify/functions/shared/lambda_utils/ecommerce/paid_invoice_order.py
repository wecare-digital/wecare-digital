"""Project provider-verified staff invoices into the shared customer order store.

A contact's stored checkoutCustomerId is the only website ownership join. A missing
join leaves a staff-owned order needing linkage; a payer phone never grants access.
"""
from copy import deepcopy
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from lambda_utils import contact_key, customer_auth
from lambda_utils.comms.numbers import to_e164
from lambda_utils.ecommerce import finalization, order_keys, order_record
from lambda_utils.identity import customer_uuid


def _paid_note_is_contradictory(note):
    note = str(note or '').strip().lower()
    if not note:
        return False
    if 'unpaid' in note or 'no money moved' in note:
        return True
    return 'cancelled' in note and any(marker in note for marker in ('qa', 'test', 'proof'))


def _authoritative_invoice_metadata(invoice, attempt):
    """Project non-fiscal paid metadata from verified attempt evidence.

    This intentionally does not touch amounts, tax fields, invoice numbering, provider evidence,
    or delivery state. A fully paid attempt is authoritative for order origin, and notes which
    explicitly describe that same transaction as cancelled/unpaid are stale QA metadata.
    """
    projected = deepcopy(invoice)
    channel = str(attempt.get('channel') or '').strip().lower()
    if channel in ('whatsapp', 'website'):
        projected['channel'] = channel
    if attempt.get('status') == 'PAYMENT_PAID':
        note = str(projected.get('notes') or '').strip().lower()
        if _paid_note_is_contradictory(note):
            projected.pop('notes', None)
    return projected


def build(*, invoice, attempt, contact, outcome, items, now):
    amount = finalization.integer_paise(attempt.get('verifiedCapturedPaise'))
    expected = finalization.integer_paise(attempt.get('amountPaise'))
    provider = str(attempt.get('verifiedProviderPaymentId') or '')
    contact_id = contact_key.resolve(contact)
    if (attempt.get('currency') != 'INR'
            or invoice.get('currency', 'INR') != 'INR'
            or contact.get('deletedAt') is not None or bool(contact.get('isDeleted'))
            or attempt.get('customerId') not in (contact_id, contact.get('checkoutCustomerId'))
            or attempt.get('contactId') not in (None, '', contact_id)
            or (outcome.get('providerPaymentId') and outcome['providerPaymentId'] != provider)
            or attempt.get('status') != 'PAYMENT_PAID' or not provider or amount is None
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
    public_uuid = customer_uuid.from_contact(attempt) or customer_uuid.from_contact(contact)
    if invoice.get('customerUuid') and invoice['customerUuid'] != public_uuid:
        raise ValueError('invoice customer identity does not agree')
    snapshot = _authoritative_invoice_metadata(invoice, attempt)
    if public_uuid:
        snapshot['customerUuid'] = public_uuid
    row = {
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
        'invoiceSnapshot': snapshot, 'items': deepcopy(items),
    }
    if public_uuid:
        row['customerUuid'] = public_uuid
    return row


def store(*, orders, row):
    """Create once. A replay can only promote the original contact to its verified account."""
    try:
        orders.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
        return row
    except Exception as error:
        if not order_keys.is_conditional_failure(error):
            raise
    current = orders.get_item(Key={'orderId': row['orderId']}, ConsistentRead=True).get('Item') or {}
    for field in ('paymentAttemptId', 'providerPaymentId', 'referenceId', 'invoiceId',
                  'orderNumber', 'amountPaise', 'contactId'):
        if current.get(field) != row.get(field):
            raise ValueError('existing order belongs to another payment')
    same_owner = current.get('customerId') == row['customerId']
    promoting = (current.get('finalizationStage') == 'NEEDS_CUSTOMER_LINK'
        and current.get('customerId') == row['contactId']
        and row['finalizationStage'] == 'ORDER_FINALIZED')
    if not same_owner and not promoting:
        raise ValueError('existing order belongs to another customer')
    public_uuid = row.get('customerUuid')
    if public_uuid and current.get('customerUuid') and current['customerUuid'] != public_uuid:
        raise ValueError('existing order customer identity disagrees')
    assignments = []
    values = {':previous': current['customerId'], ':contact': row['contactId'],
              ':attempt': row['paymentAttemptId'], ':provider': row['providerPaymentId'],
              ':reference': row['referenceId'], ':invoice': row['invoiceId'],
              ':number': row['orderNumber'], ':amount': row['amountPaise']}
    if promoting:
        assignments.extend(['customerId = :customer', 'finalizationStage = :done'])
        values.update({':customer': row['customerId'], ':done': 'ORDER_FINALIZED'})
    if public_uuid and not current.get('customerUuid'):
        assignments.append('customerUuid = :uuid')
        values[':uuid'] = public_uuid
    desired_channel = row.get('channel')
    if desired_channel in ('whatsapp', 'website') and current.get('channel') != desired_channel:
        assignments.append('channel = :channel')
        values[':channel'] = desired_channel
    desired_snapshot = row.get('invoiceSnapshot')
    if isinstance(desired_snapshot, dict) and current.get('invoiceSnapshot') != desired_snapshot:
        assignments.append('invoiceSnapshot = :snapshot')
        values[':snapshot'] = desired_snapshot
    if not assignments:
        return current
    orders.update_item(Key={'orderId': row['orderId']},
        UpdateExpression='SET ' + ', '.join(assignments),
        ConditionExpression=('customerId = :previous AND contactId = :contact '
            'AND paymentAttemptId = :attempt AND providerPaymentId = :provider '
            'AND referenceId = :reference AND invoiceId = :invoice '
            'AND orderNumber = :number AND amountPaise = :amount'),
        ExpressionAttributeValues=values)
    return orders.get_item(Key={'orderId': row['orderId']}, ConsistentRead=True)['Item']



def _query_all(table, **kwargs):
    """Drain pages, including pages whose filters returned no rows."""
    rows = []
    while True:
        page = table.query(**kwargs)
        rows.extend(page.get('Items') or [])
        last = page.get('LastEvaluatedKey')
        if not last:
            return rows
        kwargs['ExclusiveStartKey'] = last


def materialize(*, invoices, items, contacts, attempts, keys, orders, reference_id, now):
    """Resume projection from verified stored evidence and an existing claim. No charge/send.

    Accept only a reference, never caller-supplied evidence. Each side effect is
    repeatable; an interrupted run completes its remaining links on the next call.
    """
    reference = order_keys.resolve_payment_reference(keys, reference_id) or {}
    attempt_id = reference.get('paymentAttemptId')
    if not attempt_id:
        raise ValueError('stored payment attempt required')
    attempt = attempts.get_item(Key={'paymentAttemptId': attempt_id}, ConsistentRead=True).get('Item') or {}
    claim = order_keys.resolve_order_for_payment(keys, attempt_id) or {}
    provider = str(attempt.get('verifiedProviderPaymentId') or '')
    provider_claim = order_keys.resolve_order_for_provider_payment(keys, provider) or {}
    if (not claim.get('orderIdRef') or not claim.get('orderNumber')
            or claim.get('paymentAttemptId') != attempt_id
            or claim.get('providerTransactionId') != provider
            or provider_claim.get('paymentAttemptId') != attempt_id
            or provider_claim.get('orderIdRef') != claim['orderIdRef']):
        raise ValueError('matching existing order and provider claims required')
    matches = _query_all(invoices, IndexName='referenceId-index',
        KeyConditionExpression=Key('referenceId').eq(reference_id))
    if len(matches) != 1:
        raise ValueError('unique saved invoice required')
    # The GSI only locates the invoice; the evidence is read consistently from its table.
    invoice = invoices.get_item(Key={'invoiceId': matches[0]['invoiceId']}, ConsistentRead=True).get('Item') or {}
    projected_invoice = _authoritative_invoice_metadata(invoice, attempt)
    contact = contacts.get_item(Key={'id': invoice.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    lines = _query_all(items, KeyConditionExpression=Key('invoiceId').eq(invoice['invoiceId']), ConsistentRead=True)
    outcome = {'hasOrder': True, 'orderId': claim['orderIdRef'],
        'orderNumber': claim['orderNumber'], 'providerPaymentId': provider}
    row = build(invoice=projected_invoice, attempt=attempt, contact=contact, outcome=outcome, items=lines, now=now)
    row = store(orders=orders, row=row)
    # A profile can bind the contact after our first read and before this insert.
    # Rebuild only the ownership projection from a fresh read, retaining the claim.
    fresh_contact = contacts.get_item(Key={'id': row['contactId']}, ConsistentRead=True).get('Item') or {}
    if fresh_contact.get('checkoutCustomerId') and fresh_contact.get('checkoutCustomerId') != row['customerId']:
        row = store(orders=orders, row=build(invoice=projected_invoice, attempt=attempt,
            contact=fresh_contact, outcome=outcome, items=lines, now=now))
    attempt_update = ('SET finalizationStage = :stage, orderId = :order, '
                      'orderNumber = :number, contactId = :contact')
    attempt_values = {':stage': row['finalizationStage'], ':order': row['orderId'],
        ':number': row['orderNumber'], ':provider': row['providerPaymentId'],
        ':amount': row['amountPaise'], ':contact': row['contactId']}
    if row.get('customerUuid'):
        attempt_update += ', customerUuid = :uuid'
        attempt_values[':uuid'] = row['customerUuid']
    attempts.update_item(Key={'paymentAttemptId': attempt_id},
        UpdateExpression=attempt_update,
        ConditionExpression=('verifiedProviderPaymentId = :provider AND verifiedCapturedPaise = :amount '
            'AND (attribute_not_exists(contactId) OR contactId = :contact)'),
        ExpressionAttributeValues=attempt_values)
    values = {':order': row['orderId'], ':number': row['orderNumber'], ':ref': reference_id}
    names = {}
    expression = 'SET orderId = :order, orderNumber = :number'
    channel = str(projected_invoice.get('channel') or '')
    if channel in ('whatsapp', 'website'):
        names['#channel'] = 'channel'
        expression += ', #channel = :channel'
        values[':channel'] = channel
    if row.get('customerUuid'):
        expression += ', customerUuid = :uuid'
        values[':uuid'] = row['customerUuid']
    if invoice.get('notes') and not projected_invoice.get('notes'):
        expression += ' REMOVE notes'
    invoices.update_item(Key={'invoiceId': invoice['invoiceId']}, UpdateExpression=expression,
        ConditionExpression='referenceId = :ref', ExpressionAttributeValues=values,
        **({'ExpressionAttributeNames': names} if names else {}))
    return {key: row[key] for key in ('orderId', 'orderNumber', 'finalizationStage')}
