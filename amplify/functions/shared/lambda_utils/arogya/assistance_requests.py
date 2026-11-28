"""Any-hospital assistance intake in the existing table. No provider calls or payment.

Customer record and minimal IAM-operator queue pointer commit atomically. A stable
client UUID makes retries return the original receipt without another request.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeSerializer
from .booking_store import draft_id, InvalidPlan, DraftConflict

KIND = 'HOSPITAL_ASSISTANCE'
QUEUE = 'queue:hospital-assistance'
FIELDS = {'hospitalChoice', 'hospitalName', 'city', 'appointmentType', 'speciality',
          'doctor', 'preferredDate', 'preferredTime', 'patientName', 'mobile', 'email', 'notes', 'consent'}
SERIALIZER = TypeSerializer()
_transactions = None


def transaction_client():
    global _transactions
    if _transactions is None:
        _transactions = boto3.client('dynamodb')
    return _transactions


def validate(value, *, now):
    if not isinstance(value, dict) or set(value) != FIELDS or value.get('consent') is not True:
        raise InvalidPlan('Complete the request and agree to coordination of these details.')
    result = {'consent': True}
    for key in FIELDS - {'consent'}:
        text = value[key]
        limit = 500 if key == 'notes' else 120
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
            raise InvalidPlan('Request fields exceed the allowed format.')
        result[key] = text.strip()
    if result['hospitalChoice'] not in {'Apollo Hospitals', 'Another hospital', 'Help me choose'}:
        raise InvalidPlan('Choose a hospital preference.')
    if result['appointmentType'] not in {'Consultation', 'Health check', 'Admission assistance'}:
        raise InvalidPlan('Choose an appointment request type.')
    if result['preferredTime'] not in {'Flexible', 'Morning', 'Afternoon', 'Evening'}:
        raise InvalidPlan('Choose a preferred time window.')
    if not result['city'] or not result['patientName'] or len(result['city']) > 80:
        raise InvalidPlan('Enter the city and patient name.')
    if result['hospitalChoice'] == 'Another hospital' and not result['hospitalName']:
        raise InvalidPlan('Enter the preferred hospital name.')
    if not re.fullmatch(r'\+?[1-9]\d{9,14}', result['mobile']):
        raise InvalidPlan('Enter the patient contact number with country code.')
    if result['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', result['email']):
        raise InvalidPlan('Enter a valid email address or leave it blank.')
    try:
        date = dt.date.fromisoformat(result['preferredDate'])
        today = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
        if date.isoformat() != result['preferredDate'] or date < today:
            raise ValueError
    except ValueError:
        raise InvalidPlan('Choose today or a future date in India Standard Time.') from None
    return result


def receipt(row):
    return {'requestId': row['draftId'], 'status': 'REQUESTED',
            'createdAt': int(row['createdAt']), 'appointmentConfirmed': False}


def submit(table, owner, reference, value, *, now):
    reference = draft_id(reference)
    key = {'customerId': owner, 'draftId': reference}
    # A hash binds the immutable request to its retry, not to a caller-selected owner.
    existing = table.get_item(Key=key, ConsistentRead=True).get('Item')
    # A response lost before midnight can be replayed after midnight. Validate
    # the frozen date at its original intake time, then require the exact hash.
    original_time = int(existing['createdAt']) if existing and existing.get('kind') == KIND else now
    data = validate(value, now=original_time)
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if existing:
        if existing.get('kind') == KIND and existing.get('fingerprint') == fingerprint and int(existing.get('expiresAt', 0)) > now:
            return receipt(existing)
        raise DraftConflict('This request reference is already in use. Check your submitted requests.')
    expires = now + 30 * 86400
    values = {':kind': KIND, ':status': 'REQUESTED', ':data': data, ':hash': fingerprint,
              ':now': now, ':expires': expires}
    def typed(value):
        return {k: SERIALIZER.serialize(v) for k, v in value.items()}
    queue_key = {'customerId': QUEUE, 'draftId': f'{now:012d}#{hashlib.sha256(owner.encode()).hexdigest()}#{reference}'}
    writes = [
        {'Update': {'TableName': table.name, 'Key': typed(key),
            'UpdateExpression': 'SET kind=:kind, #s=:status, requestData=:data, fingerprint=:hash, createdAt=:now, expiresAt=:expires',
            'ConditionExpression': 'attribute_not_exists(draftId)',
            'ExpressionAttributeNames': {'#s': 'status'}, 'ExpressionAttributeValues': typed(values)}},
        {'Update': {'TableName': table.name, 'Key': typed(queue_key),
            'UpdateExpression': 'SET kind=:kind, requestOwner=:owner, requestId=:id, createdAt=:now, expiresAt=:expires',
            'ConditionExpression': 'attribute_not_exists(draftId)',
            'ExpressionAttributeValues': typed({':kind': KIND, ':owner': owner, ':id': reference, ':now': now, ':expires': expires})}},
    ]
    try:
        transaction_client().transact_write_items(TransactItems=writes)
    except ClientError as error:
        if error.response['Error']['Code'] != 'TransactionCanceledException':
            raise
        # A simultaneous identical retry may have won the transaction.
        saved = table.get_item(Key=key, ConsistentRead=True).get('Item', {})
        if saved.get('kind') == KIND and saved.get('fingerprint') == fingerprint and int(saved.get('expiresAt', 0)) > now:
            return receipt(saved)
        raise DraftConflict('The request could not be saved. Retry using the same reference.') from None
    return receipt({'draftId': reference, 'createdAt': now})


def customer_requests(table, owner, *, now, after=None):
    kwargs = dict(KeyConditionExpression='customerId = :owner',
        ExpressionAttributeValues={':owner': owner}, Limit=50, ConsistentRead=True,
        ProjectionExpression='draftId, kind, #s, createdAt, expiresAt',
        ExpressionAttributeNames={'#s': 'status'})
    if after is not None:
        kwargs['ExclusiveStartKey'] = {'customerId': owner, 'draftId': draft_id(after)}
    page = table.query(**kwargs)
    rows = [receipt(row) for row in page.get('Items', [])
            if row.get('kind') == KIND and int(row.get('expiresAt', 0)) > now]
    return {'requests': sorted(rows, key=lambda row: row['createdAt'], reverse=True),
            'nextAfter': page.get('LastEvaluatedKey', {}).get('draftId')}


def operator_queue(table, *, now, after=None):
    kwargs = {'KeyConditionExpression': 'customerId = :queue',
        'ExpressionAttributeValues': {':queue': QUEUE}, 'Limit': 20,
        'ScanIndexForward': False, 'ConsistentRead': True}
    if after is not None:
        if not isinstance(after, str) or not re.fullmatch(r'\d{12}#[a-f0-9]{64}#[a-f0-9-]{36}', after):
            raise InvalidPlan('Invalid request cursor.')
        kwargs['ExclusiveStartKey'] = {'customerId': QUEUE, 'draftId': after}
    page = table.query(**kwargs)
    rows = [{'customerId': row['requestOwner'], 'requestId': row['requestId'],
             'createdAt': int(row['createdAt'])} for row in page.get('Items', [])
            if row.get('kind') == KIND and int(row.get('expiresAt', 0)) > now]
    return {'requests': rows, 'nextAfter': page.get('LastEvaluatedKey', {}).get('draftId')}


def operator_request(table, owner, reference, *, now):
    if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', owner):
        raise InvalidPlan('Invalid request owner.')
    row = table.get_item(Key={'customerId': owner, 'draftId': draft_id(reference)}, ConsistentRead=True).get('Item', {})
    if row.get('kind') != KIND or int(row.get('expiresAt', 0)) <= now:
        return None
    return {**receipt(row), 'details': row['requestData']}
