"""Ownership, expiry, optimistic concurrency and untrusted draft input."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lambda_utils.arogya import booking_store as store

ROOT = Path(__file__).resolve().parents[2]
NOW = 1795737600
ID = '550e8400-e29b-41d4-a716-446655440000'


def plan():
    return dict(city='Chennai', hospital='Apollo Greams Road', professional='Doctor',
        patientMode='Telephone', appointmentType='Consultation', speciality='General Surgery',
        date='2026-11-30', time='18:50', userType='Registered User', mobile='9999999999')


def table():
    result = Mock()
    result.meta.client.exceptions.ConditionalCheckFailedException = type('Conflict', (Exception,), {})
    return result


def test_plan_rejects_client_prices_extra_identity_and_invalid_dates():
    for mutation in ({'totalPaise': 1}, {'customerId': 'victim'}, {'date': '2026-02-30'},
                     {'date': '2026-01-01'}, {'time': '00:00'}, {'patientMode': 'proxy'},
                     {'userType': 'Other'}, {'remarks': 'x' * 501}):
        with pytest.raises(store.InvalidPlan):
            store.validate_plan({**plan(), **mutation}, now=NOW)
    assert store.validate_plan(plan(), now=NOW)['time'] == '18:50'


def test_new_patient_and_conditional_pickup_are_required():
    p = {**plan(), 'userType': 'New User'}
    with pytest.raises(store.InvalidPlan):
        store.validate_plan(p, now=NOW)
    p.update(salutation='Dr', patientName='Test', age='30', gender='Female', area='Chennai', pickup='No')
    assert store.validate_plan(p, now=NOW)['salutation'] == 'Dr'
    p['pickup'] = 'Yes'
    with pytest.raises(store.InvalidPlan):
        store.validate_plan(p, now=NOW)


def test_read_is_addressed_only_in_authenticated_partition_and_checks_ttl():
    db = table()
    db.get_item.return_value = {'Item': {'expiresAt': NOW}}
    assert store.get_draft(db, 'owner', ID, now=NOW) is None
    assert db.get_item.call_args.kwargs == {'Key': {'customerId': 'owner', 'draftId': ID}, 'ConsistentRead': True}
    store.delete_draft(db, 'owner', ID)
    assert db.delete_item.call_args.kwargs['Key']['customerId'] == 'owner'


def test_stale_revision_fails_instead_of_overwriting_another_save():
    db = table()
    db.update_item.side_effect = db.meta.client.exceptions.ConditionalCheckFailedException()
    with pytest.raises(store.DraftConflict):
        store.save_draft(db, 'owner', ID, plan(), revision=2, now=NOW)
    call = db.update_item.call_args.kwargs
    assert call['ExpressionAttributeValues'][':revision'] == 2
    assert 'expiresAt > :now' in call['ConditionExpression']


def test_dynamodb_numbers_return_as_json_numbers_and_list_has_no_patient_details():
    from decimal import Decimal
    row = {'draftId': ID, 'status': 'DRAFT', 'revision': Decimal(1),
        'createdAt': Decimal(NOW), 'updatedAt': Decimal(NOW),
        'expiresAt': Decimal(NOW + 300), 'plan': plan()}
    assert type(store.public_draft(row)['revision']) is int
    db = table()
    db.query.return_value = {'Items': [row, {**row, 'expiresAt': NOW}, {**row, 'expiresAt': 'invalid'}]}
    result = store.list_drafts(db, 'owner', now=NOW)
    assert len(result) == 1 and 'plan' not in result[0]
    assert db.query.call_args.kwargs['ExpressionAttributeValues'] == {':owner': 'owner'}
    assert db.query.call_args.kwargs['Limit'] == 20


def test_handler_requires_verified_customer_and_returns_no_provider_confirmation(monkeypatch):
    spec = importlib.util.spec_from_file_location('arogya_handler', ROOT / 'amplify/functions/ecommerce/arogya-booking/handler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    event = {'requestContext': {'http': {'method': 'POST'}}, 'body': json.dumps({'action': 'quote', 'total': 1})}
    monkeypatch.setattr(module, 'require_customer', lambda _: (None, {'statusCode': 401}))
    assert module.handler(event, None)['statusCode'] == 401
    identity = SimpleNamespace(subject='owner', phone_verified=False)
    monkeypatch.setattr(module, 'require_customer', lambda _: (identity, None))
    assert module.handler(event, None)['statusCode'] == 403
    identity.phone_verified = True
    assert module.handler(event, None)['statusCode'] == 400
    event['body'] = json.dumps({'action': 'access'})
    access = json.loads(module.handler(event, None)['body'])
    assert access['phoneVerified'] is True and access['appointmentConfirmed'] is False
    assert len(access['accountKey']) == 64 and access['accountKey'] != identity.subject
    identity.subject = 'different-owner'
    assert json.loads(module.handler(event, None)['body'])['accountKey'] != access['accountKey']
    event['body'] = json.dumps({'action': 'quote'})
    reply = module.handler(event, None)
    body = json.loads(reply['body'])
    assert body['pricing']['totalPayablePaise'] == 71114
    assert body['appointmentConfirmed'] is False
    assert body['estimateOnly'] is True and body['checkoutAvailable'] is False
    assert reply['headers']['Cache-Control'] == 'no-store, private'


def test_template_avoids_fixed_paid_addons_and_auto_scaling():
    t = json.loads((ROOT / 'amplify/infra/arogya-booking.json').read_text())
    resources = t['Resources']
    p = resources['Bookings']['Properties']
    assert p['BillingMode'] == 'PROVISIONED'
    assert p['ProvisionedThroughput'] == {'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
    assert not p['PointInTimeRecoverySpecification']['PointInTimeRecoveryEnabled']
    assert not any(r['Type'] in {'AWS::KMS::Key', 'AWS::ApiGatewayV2::Api', 'AWS::Events::Rule', 'AWS::EC2::NatGateway', 'AWS::ApplicationAutoScaling::ScalableTarget'} for r in resources.values())
    assert 'ProvisionedConcurrencyConfig' not in resources['Function']['Properties']
