"""Verified WhatsApp self-service over the website's canonical order partition."""
import json
import os
import re
import boto3
from lambda_utils import customer_auth
from lambda_utils.ecommerce import catalog_service_checkout as catalog
from lambda_utils.identity import customer_uuid

ORDERS_URL = 'https://wecare.digital/orders/'
SIGN_IN_URL = 'https://wecare.digital/account/sign-in/'
ORDER_PAGE_SIZE = 10
MAX_ORDER_PAGE = 10


def command(text):
    value = ' '.join(str(text or '').strip().lower().split())
    if value in ('customer id', 'my customer id', 'customer uuid'):
        return ('customer_id', 1)
    if value in ('orders', 'my orders', 'order history', 'all orders'):
        return ('orders', 1)
    match = re.fullmatch(r'orders page ([1-9][0-9]{0,2})', value)
    return ('orders', int(match[1])) if match else None


def order_page(table, owner, page_number):
    """Same index and owner partition as /ecommerce/my-orders; no phone scans."""
    if not isinstance(page_number, int) or isinstance(page_number, bool) or not 1 <= page_number <= MAX_ORDER_PAGE:
        raise ValueError('Order page exceeds WhatsApp read budget')
    query = {'IndexName': 'customerId-createdAt-index',
             'KeyConditionExpression': 'customerId=:owner',
             'ExpressionAttributeValues': {':owner': owner},
             'ScanIndexForward': False, 'Limit': ORDER_PAGE_SIZE}
    page = {}
    for index in range(page_number):
        page = table.query(**query)
        if index + 1 < page_number:
            if not page.get('LastEvaluatedKey'):
                return [], False
            query['ExclusiveStartKey'] = page['LastEvaluatedKey']
    rows = []
    for item in page.get('Items', []):
        # Never fall back to internal UUIDs as customer-facing order numbers.
        number = str(item.get('orderNumber') or '').strip()
        if number and len(number) <= 80 and '\n' not in number:
            rows.append(number)
    return rows, bool(page.get('LastEvaluatedKey'))


def reply(table, contact, identity, selection):
    kind, page = selection
    if kind == 'customer_id':
        identifier = customer_uuid.from_contact(contact)
        return ('Your Customer ID: ' + identifier + '\n\n' + ORDERS_URL
                if identifier else 'Your Customer ID is not available yet. Please open your account so we can help complete your profile.\n' + SIGN_IN_URL)
    if page > MAX_ORDER_PAGE:
        return 'Please open your account to view further orders and download receipts:\n' + ORDERS_URL
    rows, more = order_page(table, identity.customer_id, page)
    text = ('Your orders' + (f' — page {page}' if page > 1 else '') + '\n\n'
            + '\n'.join(rows)) if rows else 'No orders were found on this page of your verified account.'
    if more:
        if page < MAX_ORDER_PAGE:
            text += f'\n\nType Orders page {page + 1} to see more.'
        else:
            text += '\n\nOpen your account to view further orders.'
    return text + '\n\nView orders and download receipts:\n' + ORDERS_URL


def handle(event, client):
    if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    selected = command(event.get('text'))
    if not selected:
        return {'outcome': 'UNKNOWN_CUSTOMER_COMMAND'}
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    contact = db.Table('stack-wecare-digital-ContactsTable').get_item(
        Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    owner = str(contact.get('checkoutCustomerId') or '')
    # Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', owner):
        return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED', 'reply': 'Please sign in and verify this WhatsApp number to view your orders or Customer ID.\n' + SIGN_IN_URL}
    users = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'us-east-1')).list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID, Filter='sub = "' + owner + '"', Limit=2).get('Users') or []
    identity = catalog.verified_identity(contact, users, event.get('senderPhone', ''))
    text = reply(db.Table('stack-wecare-digital-OrderTable'), contact, identity, selected)
    # Inbound owns reply sending, dedup and receiving-number context. This function is read-only.
    return {'outcome': 'CUSTOMER_COMMAND_READY', 'reply': text}
