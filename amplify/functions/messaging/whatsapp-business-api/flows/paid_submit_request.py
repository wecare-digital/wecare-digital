"""Native form for one already-paid Submit Request service purchase."""
import os
import json
import time
import logging
from datetime import datetime
import boto3
from lambda_utils.ecommerce import paid_submit_request as paid
from lambda_utils.ecommerce import service_request_store as store, order_keys
from lambda_utils import customer_auth

logger = logging.getLogger(__name__)


def tables():
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return (db.Table('stack-wecare-digital-ServiceRequestsTable'),
            db.Table('stack-wecare-digital-WixOrderIds'),
            db.Table('stack-wecare-digital-OrderTable'))


def route(action, screen, data, token):
    if action == 'ping':
        return {'data': {'status': 'active'}}
    requests, keys, orders = tables()
    try:
        row = paid.resolve(requests, keys, token)
        if row.get('detailsSubmittedAt'):
            mirror(row)
            return {'screen': 'DONE', 'data': {'request_number': row['publicRequestId']}}
        if action == 'INIT' or (action == 'BACK' and screen == 'SELECT_RECORD'):
            choices = paid.list_orders(orders, row)
            if not choices:
                return {'screen': 'NO_ORDERS', 'data': {}}
            return {'screen': 'SELECT_RECORD', 'data': {'orders': choices,
                    'request_number': row['publicRequestId']}}
        if action == 'data_exchange' and screen == 'REVIEW':
            saved = paid.submit(requests, keys, orders, token, data)
            mirror(saved)
            return {'screen': 'DONE', 'data': {'request_number': saved['publicRequestId']}}
        return {'data': data}
    except Exception as error:
        # No raw exception, payment data, token or request details reach the handset.
        logger.warning(json.dumps({'event': 'paid_request_flow_unavailable',
                                   'error': type(error).__name__}))
        return {'screen': 'UNAVAILABLE', 'data': {}}


def mirror(row):
    """Repairable workspace projection. The paid REQ row remains authoritative."""
    table = boto3.resource('dynamodb').Table('stack-wecare-digital-FlowSubmissionTable')
    item = {
        'submissionId': row['publicRequestId'], 'flowId': paid.FLOW_ID,
        'flowCode': '01.WD_PAID_SR', 'flowName': 'Paid Submit Request',
        'flowType': 'form_submit', 'status': 'submitted', 'paymentStatus': 'paid',
        'customerId': row['customerId'], 'createdAt': row['detailsSubmittedAt'],
        'orderId': row['parentOrderId'], 'serviceOrderId': row['orderId'],
        'requestId': row['publicRequestId'], 'referenceId': row['referenceId'],
        'subject': row['subject'], 'description': row['description']}
    # Empty strings are not valid keys on a sparse DynamoDB index.
    if row.get('flowContactId'):
        item['contactId'] = row['flowContactId']
    if row.get('flowPhone'):
        item['phone'] = row['flowPhone']
    table.put_item(Item=item)
    # Queue an ids-only follow-up. The worker re-reads the submitted record before sending.
    try:
        boto3.client('lambda').invoke(FunctionName='wecare-whatsapp-business-api:live',
            InvocationType='Event', Payload=json.dumps({'internalAction': 'serviceReview',
                                                       'requestId': row['requestId']}).encode())
    except Exception as error:
        logger.warning(json.dumps({'event': 'request_review_queue_failed',
                                   'error': type(error).__name__}))


def send_review(event, lambda_client):
    from .paid_vault import _send_once, HEADER_IMAGE
    requests, _, _ = tables()
    row = requests.get_item(Key={'requestId': str(event.get('requestId') or '')},
                            ConsistentRead=True).get('Item') or {}
    if (row.get('kind') != 'SUBMIT_REQUEST' or not row.get('detailsSubmittedAt')
            or not row.get('flowContactId') or not row.get('flowPhone')):
        return {'outcome': 'REVIEW_NOT_DUE'}
    contact = boto3.resource('dynamodb').Table('stack-wecare-digital-ContactsTable').get_item(
        Key={'id': row['flowContactId']}, ConsistentRead=True).get('Item') or {}
    if (contact.get('checkoutCustomerId') != row.get('customerId') or contact.get('isDeleted')
            or contact.get('deletedAt') is not None or contact.get('phone') != row['flowPhone']):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    users = boto3.client('cognito-idp').list_users(UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + row['customerId'] + '"', Limit=2).get('Users') or []
    if len(users) != 1 or not users[0].get('Enabled', True):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}
    if attrs.get('phone_number') != row['flowPhone'] or attrs.get('phone_number_verified') != 'true':
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    accepted = _send_once(requests, row, 'requestReviewStatus', lambda_client, {
        'contactId': row['flowContactId'], 'recipientPhone': row['flowPhone'],
        'phoneNumberId': '1016149501586345', 'isTemplate': True,
        'templateName': 'wecare_leave_review', 'templateParams': [],
        'headerImageUrl': HEADER_IMAGE, 'flowButton': {'index': 0, 'flowKey': 'leave_review'}})
    return {'outcome': 'REVIEW_ACCEPTED' if accepted else 'REVIEW_PENDING'}


def prepare_and_send(event, lambda_client, get_flow):
    """Internal ids-only hint; independently re-check every paid ownership link."""
    requests, keys, _ = tables()
    payref = order_keys.resolve_payment_reference(keys, str(event.get('referenceId') or '')) or {}
    if payref.get('nativeCatalogService'):
        result = lambda_client.invoke(FunctionName='wecare-checkout:live', InvocationType='RequestResponse',
            Payload=json.dumps({'internalAction': 'finalizeNativeCatalogService',
                'paymentAttemptId': str(event.get('paymentAttemptId') or '')}).encode())
        answer = json.loads(result['Payload'].read())
        if result.get('FunctionError') or answer.get('outcome') != 'NATIVE_SERVICE_FINALIZED':
            return {'outcome': 'NATIVE_SERVICE_FINALIZATION_PENDING'}
    outcome = store.activate(requests, keys,
                            reference_id=str(event.get('referenceId') or ''),
                            payment_attempt_id=str(event.get('paymentAttemptId') or ''))
    if outcome.outcome not in (store.ACTIVATED, store.ALREADY_ACTIVE):
        return {'outcome': outcome.outcome}
    claim = order_keys.resolve_order_for_payment(keys, str(event.get('paymentAttemptId') or '')) or {}
    oid = claim.get('orderIdRef')
    if not oid or oid != event.get('orderId'):
        return {'outcome': 'ORDER_MISMATCH'}
    pointer = requests.get_item(Key={'requestId': 'ORDER#' + oid}, ConsistentRead=True).get('Item') or {}
    target = pointer.get('targetRequestId', '')
    candidate = requests.get_item(Key={'requestId': target}, ConsistentRead=True).get('Item') or {}
    if candidate.get('kind') == 'VAULT':
        from .paid_vault import prepare_and_send as vault_send
        return vault_send(event, lambda_client)
    if candidate.get('kind') != 'SUBMIT_REQUEST':
        return {'outcome': 'NOT_SUBMIT_REQUEST'}
    row, token = paid.prepare(requests, keys, target)
    if row.get('detailsSubmittedAt'):
        mirror(row)
        return {'outcome': 'ALREADY_COMPLETED'}
    meta = get_flow(paid.FLOW_ID)
    info = json.loads(meta.get('body') or '{}').get('flow') or {}
    if info.get('status') != 'PUBLISHED':
        return {'outcome': 'FLOW_DRAFT', 'requestId': row['publicRequestId']}
    users = boto3.client('cognito-idp').list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + row['customerId'] + '"', Limit=2).get('Users') or []
    if len(users) != 1 or not users[0].get('Enabled', True):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}
    phone = attrs.get('phone_number', '')
    if attrs.get('phone_number_verified') != 'true' or not phone.startswith('+'):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    contacts = boto3.resource('dynamodb').Table('stack-wecare-digital-ContactsTable')
    matches = contacts.query(IndexName='phone-index', KeyConditionExpression='phone=:p',
                             ExpressionAttributeValues={':p': phone}).get('Items') or []
    valid = []
    for projection in matches:
        contact = contacts.get_item(Key={'id': projection['id']}, ConsistentRead=True).get('Item') or {}
        if (contact.get('checkoutCustomerId') == row['customerId']
                and not contact.get('isDeleted') and contact.get('deletedAt') is None):
            valid.append(contact)
    if len(valid) != 1:
        return {'outcome': 'CONTACT_LINK_UNAVAILABLE'}
    contact = valid[0]
    last = contact.get('lastInboundMessageAt', 0)
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace('Z', '+00:00')).timestamp()
    if not 0 <= time.time() - float(last or 0) < 86400:
        return {'outcome': 'AWAITING_CUSTOMER_MESSAGE'}
    # A claimed send is not automatically repeated after an ambiguous network result.
    try:
        requests.update_item(Key={'requestId': target},
            UpdateExpression='SET flowInviteStatus=:s, flowContactId=:c, flowPhone=:p',
            ConditionExpression='attribute_not_exists(flowInviteStatus)',
            ExpressionAttributeValues={':s': 'SENDING', ':c': contact['id'], ':p': phone})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return {'outcome': 'INVITATION_ALREADY_CLAIMED'}
        raise
    response = lambda_client.invoke(FunctionName='wecare-outbound-whatsapp:live',
        InvocationType='RequestResponse', Payload=json.dumps({'body': json.dumps({
            'contactId': contact['id'], 'recipientPhone': phone, 'isInteractive': True,
            'interactiveType': 'flow', 'interactiveData': {
                'body': 'Payment received. Complete the details for your Submit Request.',
                'footer': 'WECARE.DIGITAL', 'flowId': paid.FLOW_ID,
                'flowCta': 'Complete Request', 'flowAction': 'data_exchange', 'flowToken': token}})}).encode())
    answer = json.loads(response['Payload'].read())
    accepted = not response.get('FunctionError') and 200 <= int(answer.get('statusCode', 500)) < 300
    requests.update_item(Key={'requestId': target},
        UpdateExpression='SET flowInviteStatus=:s',
        ExpressionAttributeValues={':s': 'ACCEPTED' if accepted else 'SEND_FAILED'})
    return {'outcome': 'INVITATION_ACCEPTED' if accepted else 'SEND_FAILED',
            'requestId': row['publicRequestId']}
