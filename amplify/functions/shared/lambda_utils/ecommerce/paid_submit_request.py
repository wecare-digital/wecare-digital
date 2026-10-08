"""Complete a paid Submit Request purchase without collecting another payment.

The server's PAYREF and PAYMENTATTEMPT records establish the purchase. An opaque
stored capability binds the Flow to the paid request; an exact customerId binds
its selected earlier order. Customer-entered amounts and identities are ignored.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from typing import Any
from lambda_utils.ecommerce import order_keys, service_request_store as store

VARIANT_ID = 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b'
FLOW_ID = '1107164111921876'
TOKEN_PREFIX = 'paidsr:'

class RequestUnavailable(ValueError):
    pass


def paid_request(table: Any, keys: Any, request_key: str) -> dict:
    if not request_key.startswith('REQ#') or len(request_key) > 100:
        raise RequestUnavailable('REQUEST_UNAVAILABLE')
    row = table.get_item(Key={'requestId': request_key}, ConsistentRead=True).get('Item') or {}
    ref = str(row.get('referenceId') or '')
    payref = order_keys.resolve_payment_reference(keys, ref) if ref else None
    attempt = str(row.get('paymentAttemptId') or '')
    claim = order_keys.resolve_order_for_payment(keys, attempt) if attempt else None
    line = (payref or {}).get('serviceLine') or {}
    owner = str(row.get('customerId') or '')
    if (not owner or row.get('kind') != 'SUBMIT_REQUEST'
            or row.get('serviceVariantId') != VARIANT_ID or not row.get('paidAt')
            or not payref or not claim or line.get('variantId') != VARIANT_ID
            or line.get('kind') != 'SUBMIT_REQUEST'
            or payref.get('customerId') != owner
            or payref.get('paymentAttemptId') != attempt
            or claim.get('orderIdRef') != row.get('orderId')
            or (claim.get('referenceId') and claim['referenceId'] != ref)):
        raise RequestUnavailable('PAID_PURCHASE_UNAVAILABLE')
    return row


def prepare(table: Any, keys: Any, request_key: str) -> tuple[dict, str]:
    row = paid_request(table, keys, request_key)
    if row.get('requestFlowToken'):
        return row, row['requestFlowToken']
    token = TOKEN_PREFIX + request_key[4:] + ':' + secrets.token_urlsafe(32)
    try:
        result = table.update_item(
            Key={'requestId': request_key},
            UpdateExpression='SET requestFlowToken=:t, requestFlowTokenHash=:h, '
                             'detailsStatus=if_not_exists(detailsStatus,:s)',
            ConditionExpression='customerId=:owner AND attribute_not_exists(requestFlowToken)',
            ExpressionAttributeValues={':t': token, ':h': hashlib.sha256(token.encode()).hexdigest(),
                                       ':s': 'AWAITING_DETAILS', ':owner': row['customerId']},
            ReturnValues='ALL_NEW')
        return result['Attributes'], token
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        row = paid_request(table, keys, request_key)
        if not row.get('requestFlowToken'):
            raise RequestUnavailable('REQUEST_UNAVAILABLE') from error
        return row, row['requestFlowToken']


def resolve(table: Any, keys: Any, token: str) -> dict:
    parts = str(token or '').split(':')
    if len(parts) != 3 or parts[0] != 'paidsr' or len(parts[2]) < 40:
        raise RequestUnavailable('REQUEST_UNAVAILABLE')
    row = paid_request(table, keys, 'REQ#' + parts[1])
    expected = str(row.get('requestFlowTokenHash') or '')
    if not expected or not hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest()):
        raise RequestUnavailable('REQUEST_UNAVAILABLE')
    return row


def list_orders(orders: Any, row: dict) -> list[dict]:
    """Customer partition only. Fetch base rows because the GSI is projected."""
    kwargs = {'IndexName': 'customerId-createdAt-index',
              'KeyConditionExpression': 'customerId=:owner',
              'ExpressionAttributeValues': {':owner': row['customerId']},
              'ScanIndexForward': False, 'Limit': 50}
    result = []
    while len(result) < 100:
        page = orders.query(**kwargs)
        for projected in page.get('Items', []):
            oid = str(projected.get('orderId') or '')
            if not oid or oid == row['orderId']:
                continue
            current = orders.get_item(Key={'orderId': oid}, ConsistentRead=True).get('Item') or {}
            if current.get('customerId') != row['customerId']:
                continue
            label = str(current.get('orderNumber') or oid)
            result.append({'id': oid, 'title': label[:60]})
            if len(result) == 100:
                break
        cursor = page.get('LastEvaluatedKey')
        if not cursor:
            break
        kwargs['ExclusiveStartKey'] = cursor
    return result


def submit(table: Any, keys: Any, orders: Any, token: str, data: dict) -> dict:
    row = resolve(table, keys, token)
    oid = str(data.get('record_id') or '').strip()
    subject = str(data.get('subject') or '').strip()
    description = str(data.get('description') or '').strip()
    if not oid or not 1 <= len(subject) <= 80 or not 1 <= len(description) <= 600:
        raise RequestUnavailable('REQUEST_DETAILS_REQUIRED')
    parent = orders.get_item(Key={'orderId': oid}, ConsistentRead=True).get('Item') or {}
    if oid == row['orderId'] or parent.get('customerId') != row['customerId']:
        raise RequestUnavailable('ORDER_UNAVAILABLE')
    if row.get('detailsSubmittedAt'):
        return row
    values = {':owner': row['customerId'], ':parent': oid, ':subject': subject,
              ':description': description, ':ready': 'READY', ':now': int(time.time())}
    items = [
        {'ConditionCheck': {'TableName': orders.name,
            'Key': store._marshal_item({'orderId': oid}),
            'ConditionExpression': 'customerId=:owner',
            'ExpressionAttributeValues': store._marshal_item({':owner': row['customerId']})}},
        {'Update': {'TableName': table.name, 'Key': store._marshal_item({'requestId': row['requestId']}),
            'UpdateExpression': 'SET parentOrderId=:parent, subject=:subject, description=:description, '
                                'detailsStatus=:ready, detailsSubmittedAt=:now, updatedAt=:now',
            'ConditionExpression': 'customerId=:owner AND attribute_not_exists(detailsSubmittedAt)',
            'ExpressionAttributeValues': store._marshal_item(values)}}]
    try:
        store._transact(table, items)
    except Exception:
        existing = resolve(table, keys, token)
        if not existing.get('detailsSubmittedAt'):
            raise
        return existing
    return table.get_item(Key={'requestId': row['requestId']}, ConsistentRead=True)['Item']
