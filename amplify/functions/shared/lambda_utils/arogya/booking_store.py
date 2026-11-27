"""Customer-owned appointment drafts. Saving never sends a request to Apollo.

Access patterns: Get/Put/Delete one owned draft, Query up to 20 owned references.
The authenticated Cognito subject is the partition key; no scan or GSI is needed.
TTL is storage cleanup only: every read independently enforces expiry.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid

FIELDS = frozenset('city hospital professional patientMode appointmentType speciality healthCheck time userType salutation patientName age gender area email mobile uhid pickup remarks pickupFrom vehicleNo arrivalDate arrivalTime attendants journeyRemarks shiftingFrom shiftingDate shiftingTime healthDescription ambulancePickup ambulanceFrom ambulanceArea ambulanceDate ambulanceTime date'.split())
ENUMS = {
    'patientMode': {'Telephone', 'Camp'},
    'appointmentType': {'Consultation', 'Health Checks', 'Admission'},
    'userType': {'Registered User', 'New User'},
    'salutation': {'Master', 'Mr.', 'Mrs.', 'Ms.', 'Dr'},
    'gender': {'Male', 'Female'}, 'pickup': {'Yes', 'No'},
    'pickupFrom': {'Railway Station', 'Airport'},
    'attendants': {'1', '2', '3', '4', '5'},
    'shiftingFrom': {'Home', 'Other Hospital', 'RTA', 'Workplace'},
    'ambulancePickup': {'Yes', 'No'}, 'ambulanceFrom': {'Apollo', 'Others'},
    'ambulanceArea': {'Airport', 'Home', 'Railway Station', 'Other Hospital'},
}
RETENTION_SECONDS = 30 * 86400


class InvalidPlan(ValueError):
    pass


class DraftConflict(RuntimeError):
    pass


def draft_id(value):
    if not isinstance(value, str):
        raise InvalidPlan('Invalid draft reference.')
    try:
        if str(uuid.UUID(value, version=4)) != value:
            raise ValueError
    except ValueError:
        raise InvalidPlan('Invalid draft reference.') from None
    return value


def validate_plan(value, *, now):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise InvalidPlan('Appointment fields are invalid.')
    plan = {key: value.get(key, '') for key in FIELDS}
    for key, text in plan.items():
        limit = 500 if key in {'remarks', 'journeyRemarks', 'healthDescription'} else 120
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
            raise InvalidPlan('Appointment fields exceed the allowed format.')
        plan[key] = text.strip()
    for key, choices in ENUMS.items():
        if plan[key] and plan[key] not in choices:
            raise InvalidPlan('Choose a valid appointment option.')
    required = ['city', 'hospital', 'patientMode', 'appointmentType', 'date', 'time', 'userType']
    required += ['healthCheck'] if plan['appointmentType'] == 'Health Checks' else ['speciality', 'professional']
    if plan['userType'] == 'New User':
        required += ['salutation', 'patientName', 'age', 'gender', 'area', 'mobile', 'pickup']
        if not re.fullmatch(r'\d{1,3}', plan['age']) or int(plan['age']) > 120:
            raise InvalidPlan('Enter an age between 0 and 120.')
        if not re.fullmatch(r'\+?[1-9]\d{9,14}', plan['mobile']):
            raise InvalidPlan('Enter a valid patient mobile number.')
        if plan['pickup'] == 'Yes':
            required += ['pickupFrom', 'vehicleNo', 'arrivalDate', 'arrivalTime', 'attendants', 'journeyRemarks']
        if plan['appointmentType'] == 'Admission':
            required += ['shiftingFrom', 'shiftingDate', 'shiftingTime', 'healthDescription', 'ambulancePickup']
            if plan['ambulancePickup'] == 'Yes':
                required += ['ambulanceFrom', 'ambulanceArea', 'ambulanceDate', 'ambulanceTime']
    elif not (re.fullmatch(r'[6-9]\d{9}', plan['mobile']) or re.fullmatch(r'[A-Za-z0-9]{2,12}\.\d{4,20}', plan['uhid'])):
        raise InvalidPlan('Enter a registered mobile number or UHID.')
    if any(not plan[key] for key in required):
        raise InvalidPlan('Complete all mandatory appointment fields.')
    today = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    for key in ('date', 'arrivalDate', 'shiftingDate', 'ambulanceDate'):
        if plan[key]:
            try:
                parsed = dt.date.fromisoformat(plan[key])
                if parsed.isoformat() != plan[key] or parsed < today:
                    raise ValueError
            except ValueError:
                raise InvalidPlan('Choose a valid current or future date in India Standard Time.') from None
    for key in ('time', 'arrivalTime', 'shiftingTime', 'ambulanceTime'):
        pattern = r'(?:0[1-9]|1\d|2[0-3]):(?:00|05|10|15|20|25|30|35|40|45|50|55)' if key == 'time' else r'(?:[01]\d|2[0-3]):[0-5]\d'
        if plan[key] and not re.fullmatch(pattern, plan[key]):
            raise InvalidPlan('Choose a valid time.')
    if plan['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', plan['email']):
        raise InvalidPlan('Enter a valid email address.')
    return plan


def _key(owner, reference):
    return {'customerId': owner, 'draftId': draft_id(reference)}


def get_draft(table, owner, reference, *, now):
    row = table.get_item(Key=_key(owner, reference), ConsistentRead=True).get('Item')
    if not row or int(row.get('expiresAt', 0)) <= now:
        return None
    return public_draft(row)


def public_draft(row, *, details=True):
    result = {key: row[key] for key in ('draftId', 'status')}
    result.update({key: int(row[key]) for key in ('revision', 'createdAt', 'updatedAt', 'expiresAt')})
    if details:
        result['plan'] = row['plan']
    return result


def save_draft(table, owner, reference, plan, *, revision, now):
    if type(revision) is not int or not 0 <= revision < 1000000:
        raise InvalidPlan('Invalid draft revision.')
    plan = validate_plan(plan, now=now)
    key = _key(owner, reference)
    values = {':plan': plan, ':status': 'DRAFT', ':next': revision + 1,
              ':now': now, ':expires': now + RETENTION_SECONDS}
    condition = 'attribute_not_exists(draftId)'
    if revision:
        condition = 'revision = :revision AND expiresAt > :now AND #status = :status'
        values[':revision'] = revision
    try:
        row = table.update_item(Key=key,
            UpdateExpression='SET #plan = :plan, #status = :status, revision = :next, createdAt = if_not_exists(createdAt, :now), updatedAt = :now, expiresAt = :expires',
            ConditionExpression=condition,
            ExpressionAttributeNames={'#plan': 'plan', '#status': 'status'},
            ExpressionAttributeValues=values, ReturnValues='ALL_NEW')['Attributes']
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise DraftConflict('This draft changed. Reload it before saving again.') from None
    return public_draft(row)


def list_drafts(table, owner, *, now):
    # Explicit bound; no scan, automatic pagination or PII in list responses.
    page = table.query(KeyConditionExpression='customerId = :owner',
        ExpressionAttributeValues={':owner': owner}, Limit=20, ConsistentRead=True)
    return [public_draft(row, details=False) for row in page.get('Items', []) if int(row.get('expiresAt', 0)) > now]


def delete_draft(table, owner, reference):
    table.delete_item(Key=_key(owner, reference))
