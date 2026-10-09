"""Owner-scoped Orders data exchange. No financial or messaging side effects."""
import hashlib
import json
import os
import re
import secrets
import time
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError
from lambda_utils import customer_auth
from lambda_utils.identity import customer_uuid
from lambda_utils.ecommerce import catalog_service_checkout as catalog, contact_address

PREFIX = 'CUSTOMERHUB#'
TOKEN_PATTERN = re.compile(r'^orders:([A-Za-z0-9_-]{40,80})$')


def record_order_help(table, identity, contact_id, session_token, data, *, public_customer_id=''):
    """One unassociated lookup request per verified session; no checkout side effect."""
    description = data.get('description', '')
    reference = data.get('order_reference', '')
    if (not isinstance(description, str) or not 1 <= len(description.strip()) <= 600
            or not isinstance(reference, str) or len(reference.strip()) > 80
            or not identity.customer_id or not contact_id or not session_token):
        raise ValueError('Invalid order help request')
    request_id = 'WD-HELP-' + hashlib.sha256(
        (identity.customer_id + ':' + session_token).encode()).hexdigest()[:24].upper()
    row = {'submissionId': request_id, 'flowType': 'order_lookup', 'flowName': 'Orders',
           'flowCode': 'WD_Orders', 'submissionNumber': request_id,
           'subject': 'Help finding an order', 'paymentStatus': 'none',
           'customerId': identity.customer_id, 'contactId': contact_id, 'phone': identity.phone,
           'orderReference': reference.strip(), 'description': description.strip(),
           'status': 'awaiting_order_verification', 'source': 'whatsapp_flow',
           'tags': ['Orders', 'Order verification pending'], 'createdAt': int(time.time())}
    if public_customer_id:
        row['customerUuid'] = public_customer_id
    try:
        table.put_item(Item=row, ConditionExpression='attribute_not_exists(submissionId)')
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        existing = table.get_item(Key={'submissionId': request_id}, ConsistentRead=True).get('Item') or {}
        if existing.get('customerId') != identity.customer_id:
            raise customer_auth.CustomerNotAuthorized('request unavailable')
    return request_id


def record_order_support(table, identity, contact_id, session_token, order, *, public_customer_id=''):
    """Create one owner-bound support request per order in this verified Orders session."""
    if (not identity.customer_id or not contact_id or not session_token
            or not order.get('order_id') or not order.get('order_number')):
        raise ValueError('Invalid order support request')
    request_id = 'WD-SUPPORT-' + hashlib.sha256(
        (identity.customer_id + ':' + session_token + ':' + order['order_id']).encode()
    ).hexdigest()[:24].upper()
    row = {
        'submissionId': request_id, 'flowType': 'order_support', 'flowName': 'Orders',
        'flowCode': 'WD_Orders', 'submissionNumber': request_id,
        'subject': 'Order support', 'paymentStatus': 'none',
        'customerId': identity.customer_id, 'contactId': contact_id, 'phone': identity.phone,
        'orderId': order['order_id'], 'orderNumber': order['order_number'],
        'status': 'open', 'source': 'whatsapp_flow',
        'tags': ['Orders', 'Customer support'], 'createdAt': int(time.time())
    }
    if public_customer_id:
        row['customerUuid'] = public_customer_id
    try:
        table.put_item(Item=row, ConditionExpression='attribute_not_exists(submissionId)')
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        existing = table.get_item(
            Key={'submissionId': request_id}, ConsistentRead=True).get('Item') or {}
        if (existing.get('customerId') != identity.customer_id
                or existing.get('orderId') != order['order_id']):
            raise customer_auth.CustomerNotAuthorized('support request unavailable')
    return request_id


def _db():
    return boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def _verified(db, contact_id, phone):
    contact = db.Table('stack-wecare-digital-ContactsTable').get_item(
        Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
    owner = str(contact.get('checkoutCustomerId') or '')
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', owner):
        raise customer_auth.CustomerNotAuthorized('account unavailable')
    users = boto3.client('cognito-idp').list_users(UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + owner + '"', Limit=2).get('Users') or []
    return contact, catalog.verified_identity(contact, users, phone)


def prepare(event):
    if any(k in event for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    db = _db()
    _, identity = _verified(db, str(event.get('contactId') or ''), str(event.get('senderPhone') or ''))
    token = 'orders:' + secrets.token_urlsafe(32)
    db.Table('stack-wecare-digital-WixOrderIds').put_item(
        Item={'orderId': PREFIX + hashlib.sha256(token.encode()).hexdigest(),
              'customerId': identity.customer_id, 'phone': identity.phone,
              'contactId': event['contactId'], 'createdAt': int(time.time()),
              'expiresAt': int(time.time()) + 1800},
        ConditionExpression='attribute_not_exists(orderId)')
    return {'outcome': 'ORDERS_SESSION_PREPARED', 'flowToken': token}


def _context(token):
    if not TOKEN_PATTERN.fullmatch(str(token or '')):
        raise customer_auth.CustomerNotAuthorized('account unavailable')
    db = _db()
    session = db.Table('stack-wecare-digital-WixOrderIds').get_item(
        Key={'orderId': PREFIX + hashlib.sha256(token.encode()).hexdigest()}, ConsistentRead=True).get('Item') or {}
    if int(session.get('expiresAt') or 0) <= int(time.time()):
        raise customer_auth.CustomerNotAuthorized('account unavailable')
    contact, identity = _verified(db, session.get('contactId', ''), session.get('phone', ''))
    if identity.customer_id != session.get('customerId'):
        raise customer_auth.CustomerNotAuthorized('account unavailable')
    return db, contact, identity, session


def profile(contact, identity):
    address = contact_address.from_contact(contact)
    return {'customer_id': customer_uuid.from_contact(contact) or 'Not available yet',
            'name': str(contact.get('name') or '').strip() or 'Not provided',
            'phone': identity.phone, 'email': str(contact.get('email') or 'Not provided'),
            'email_state': 'Verified' if contact.get('emailVerifiedAt') else 'Verification needed',
            'address': str(address.get('fullAddress') or 'Not provided') if address else 'Not provided'}


def profile_form(contact):
    address = contact_address.from_contact(contact) or {}
    return {'first_name': str(contact.get('firstName') or ''), 'last_name': str(contact.get('lastName') or ''),
        **{field: str(address.get(stored) or '') for field, stored in {
            'address_line1': 'addressLine1', 'address_line2': 'addressLine2', 'city': 'city',
            'state': 'state', 'postal_code': 'postalCode', 'country_code': 'countryCode'}.items()}}


def update_profile(db, contact, identity, data):
    allowed = {'first_name', 'last_name', 'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country_code'}
    if set(data) - allowed or not isinstance(data.get('first_name'), str):
        raise ValueError('Unsupported profile field')
    first, last = data['first_name'].strip(), data.get('last_name', '')
    if not isinstance(last, str) or not 1 <= len(first) <= 100 or len(last.strip()) > 100:
        raise ValueError('Invalid name')
    address = contact_address.normalize_for_storage({
        stored: data.get(field, '') for field, stored in {
            'address_line1': 'addressLine1', 'address_line2': 'addressLine2', 'city': 'city',
            'state': 'state', 'postal_code': 'postalCode', 'country_code': 'countryCode'}.items()})
    db.Table('stack-wecare-digital-ContactsTable').update_item(
        Key={'id': contact['id']},
        UpdateExpression='SET firstName=:first, lastName=:last, #name=:name, checkoutDeliveryAddress=:address, checkoutAddressUpdatedAt=:now, updatedAt=:now',
        ConditionExpression='checkoutCustomerId=:owner AND attribute_not_exists(deletedAt) AND (attribute_not_exists(isDeleted) OR isDeleted=:false)',
        ExpressionAttributeNames={'#name': 'name'},
        ExpressionAttributeValues={':first': first, ':last': last.strip(), ':name': ' '.join([first, last.strip()]).strip(),
            ':address': address, ':now': int(time.time()), ':owner': identity.customer_id, ':false': False})


def order_details(orders, identity, order_id):
    row = orders.get_item(Key={'orderId': str(order_id)}, ConsistentRead=True).get('Item') or {}
    if row.get('customerId') != identity.customer_id or not row.get('orderNumber'):
        raise customer_auth.CustomerNotAuthorized('order unavailable')
    raw = row.get('amountPaise')
    valid = (type(raw) is int or isinstance(raw, Decimal)) and raw >= 0 and raw == int(raw) and row.get('currency') == 'INR'
    actions = [
        {'id': 'invoice_copy', 'title': 'Send invoice copy'},
        {'id': 'contact_support', 'title': 'Contact support'},
        {'id': 'done', 'title': 'Finish'},
    ]
    return {'order_id': str(order_id), 'order_number': str(row['orderNumber']),
            'amount': f'₹{int(raw)/100:.2f}' if valid else 'Amount unavailable',
            'payment_state': str(row.get('paymentStatus') or 'Status unavailable'),
            'actions': actions}


def order_page(db, identity, session, token, next_page=False):
    orders = db.Table('stack-wecare-digital-OrderTable')
    query = {'IndexName': 'customerId-createdAt-index', 'KeyConditionExpression': 'customerId=:owner',
             'ExpressionAttributeValues': {':owner': identity.customer_id}, 'Limit': 10, 'ScanIndexForward': False}
    if next_page:
        cursor = session.get('orderCursor')
        if not isinstance(cursor, dict) or cursor.get('customerId') != identity.customer_id:
            raise customer_auth.CustomerNotAuthorized('page unavailable')
        query['ExclusiveStartKey'] = cursor
    page = orders.query(**query)
    choices = []
    for entry in page.get('Items') or []:
        try:
            owned = order_details(orders, identity, entry.get('orderId', ''))
            choices.append({'id': owned['order_id'], 'title': owned['order_number'][:60]})
        except customer_auth.CustomerNotAuthorized:
            continue
    cursor = page.get('LastEvaluatedKey') or {}
    if cursor and cursor.get('customerId') != identity.customer_id:
        raise customer_auth.CustomerNotAuthorized('page unavailable')
    db.Table('stack-wecare-digital-WixOrderIds').update_item(
        Key={'orderId': PREFIX + hashlib.sha256(token.encode()).hexdigest()},
        UpdateExpression='SET orderCursor=:cursor', ConditionExpression='customerId=:owner',
        ExpressionAttributeValues={':cursor': cursor, ':owner': identity.customer_id})
    if cursor:
        choices.append({'id': 'more_orders', 'title': 'Show older orders'})
    choices.append({'id': 'not_found', 'title': 'I cannot find my order'})
    return {'screen': 'ORDERS', 'data': {'orders': choices,
        'page_note': 'Choose your order. Select Show older orders to continue when available.'}}


def route(action, screen, data, token):
    if action == 'ping':
        return {'data': {'status': 'active'}}
    try:
        db, contact, identity, session = _context(token)
        if action == 'INIT' or (action == 'BACK' and screen == 'ACCOUNT'):
            return {'screen': 'ACCOUNT', 'data': profile(contact, identity)}
        if action == 'data_exchange' and screen == 'ACCOUNT':
            if data.get('account_action') == 'edit_profile':
                return {'screen': 'PROFILE', 'data': profile_form(contact)}
            return order_page(db, identity, session, token)
        if action == 'data_exchange' and screen == 'PROFILE':
            update_profile(db, contact, identity, data)
            return {'screen': 'PROFILE_SAVED', 'data': {}}
        if action == 'data_exchange' and screen == 'ORDERS':
            if data.get('order_id') == 'more_orders':
                return order_page(db, identity, session, token, next_page=True)
            if data.get('order_id') == 'not_found':
                return {'screen': 'ORDER_HELP', 'data': {}}
            return {'screen': 'DETAILS', 'data': order_details(
                db.Table('stack-wecare-digital-OrderTable'), identity, data.get('order_id', ''))}
        if action == 'data_exchange' and screen == 'DETAILS':
            owned = order_details(db.Table('stack-wecare-digital-OrderTable'), identity, data.get('order_id', ''))
            if data.get('detail_action') == 'invoice_copy':
                response = boto3.client('lambda').invoke(FunctionName='wecare-whatsapp-business-api:live',
                    InvocationType='RequestResponse', Payload=json.dumps({'internalAction': 'customerInvoiceCopy',
                        'flowToken': token, 'orderId': owned['order_id']}).encode())
                if response.get('FunctionError'):
                    raise RuntimeError('invoice copy unavailable')
                result = json.loads(response['Payload'].read())
                if not result.get('reference') or not result.get('message'):
                    raise RuntimeError('invoice copy unavailable')
                return {'screen': 'RESULT', 'data': {'reference': result['reference'], 'message': result['message']}}
            if data.get('detail_action') == 'contact_support':
                reference = record_order_support(
                    db.Table('stack-wecare-digital-FlowSubmissionTable'),
                    identity, session.get('contactId', ''), token, owned,
                    public_customer_id=customer_uuid.from_contact(contact) or '')
                return {'screen': 'RESULT', 'data': {'reference': reference,
                    'message': 'Your support request is saved against this order. No payment has been requested.'}}
            return {'screen': 'RESULT', 'data': {'reference': owned['order_number'], 'message': 'No changes were requested.'}}
        if action == 'data_exchange' and screen == 'ORDER_HELP':
            reference = record_order_help(db.Table('stack-wecare-digital-FlowSubmissionTable'),
                identity, session.get('contactId', ''), token, data,
                public_customer_id=customer_uuid.from_contact(contact) or '')
            return {'screen': 'RESULT', 'data': {'reference': reference,
                'message': 'Your request is saved for order verification. No payment has been requested.'}}
        return {'screen': 'UNAVAILABLE', 'data': {}}
    except Exception:
        return {'screen': 'UNAVAILABLE', 'data': {}}
