"""Any-hospital request ownership, atomic intake and replay protection."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError
from lambda_utils.arogya import assistance_requests as requests
from lambda_utils.arogya.booking_store import InvalidPlan, DraftConflict

NOW = 1795819000
ID = '550e8400-e29b-41d4-a716-446655440000'


def form():
    return dict(hospitalChoice='Another hospital', hospitalName='Synthetic independent hospital',
        city='Chennai', appointmentType='Consultation', speciality='General Surgery', doctor='',
        preferredDate='2026-11-30', preferredTime='Flexible', patientName='Synthetic Patient',
        mobile='919999999999', email='', notes='', consent=True)


@pytest.mark.parametrize('mutation', [
    {'consent': False}, {'hospitalChoice': 'unverified partner'}, {'hospitalName': ''},
    {'preferredDate': '2026-02-30'}, {'preferredDate': '2026-01-01'}, {'preferredTime': 'confirmed'},
    {'mobile': '123'}, {'notes': 'x' * 501}, {'email': 'wrong'}, {'total': 1}, {'customerId': 'victim'},
])
def test_invalid_request_fails_before_storage(mutation):
    with pytest.raises(InvalidPlan): requests.validate({**form(), **mutation}, now=NOW)


def test_any_hospital_or_help_choosing_requires_no_provider_identifiers():
    for choice in ['Another hospital', 'Apollo Hospitals', 'Help me choose']:
        value = form(); value['hospitalChoice'] = choice
        if choice != 'Another hospital': value['hospitalName'] = ''
        assert requests.validate(value, now=NOW)['hospitalChoice'] == choice


def test_customer_and_operator_pointer_are_one_atomic_transaction(monkeypatch):
    table = Mock(); table.name = 'existing-table'; table.get_item.return_value = {}
    client = Mock(); monkeypatch.setattr(requests, 'transaction_client', lambda: client)
    result = requests.submit(table, 'verified-owner', ID, form(), now=NOW)
    assert result == {'requestId': ID, 'status': 'REQUESTED', 'createdAt': NOW, 'appointmentConfirmed': False}
    writes = client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(writes) == 2
    assert writes[0]['Update']['Key'] == {'customerId': {'S': 'verified-owner'}, 'draftId': {'S': ID}}
    assert all(w['Update']['ConditionExpression'] == 'attribute_not_exists(draftId)' for w in writes)
    pointer = writes[1]['Update']
    assert pointer['Key']['customerId'] == {'S': requests.QUEUE}
    assert 'requestData' not in pointer['UpdateExpression']
    assert 'Synthetic Patient' not in json.dumps(pointer)


def test_lost_response_retry_returns_original_receipt_but_changed_payload_conflicts(monkeypatch):
    table = Mock(); table.name = 'existing-table'; table.get_item.return_value = {}
    client = Mock(); monkeypatch.setattr(requests, 'transaction_client', lambda: client)
    original = requests.submit(table, 'owner', ID, form(), now=NOW)
    values = client.transact_write_items.call_args.kwargs['TransactItems'][0]['Update']['ExpressionAttributeValues']
    table.get_item.return_value = {'Item': {'kind': requests.KIND, 'fingerprint': values[':hash']['S'],
        'draftId': ID, 'createdAt': NOW, 'expiresAt': NOW + 100}}
    assert requests.submit(table, 'owner', ID, form(), now=NOW + 1) == original
    assert client.transact_write_items.call_count == 1
    with pytest.raises(DraftConflict): requests.submit(table, 'owner', ID, {**form(), 'doctor': 'different'}, now=NOW + 1)


def test_failed_transaction_does_not_report_success_or_make_a_separate_queue_write(monkeypatch):
    table = Mock(); table.name = 'existing-table'; table.get_item.return_value = {}
    client = Mock(); client.transact_write_items.side_effect = ClientError({'Error': {'Code': 'TransactionCanceledException'}}, 'TransactWriteItems')
    monkeypatch.setattr(requests, 'transaction_client', lambda: client)
    with pytest.raises(DraftConflict): requests.submit(table, 'owner', ID, form(), now=NOW)
    table.update_item.assert_not_called()


def test_customer_history_is_owner_bound_expiring_and_paginated():
    table = Mock()
    table.query.return_value = {'Items': [{'kind': requests.KIND, 'draftId': ID, 'createdAt': NOW, 'expiresAt': NOW + 100},
        {'kind': requests.KIND, 'draftId': ID, 'createdAt': NOW, 'expiresAt': NOW}],
        'LastEvaluatedKey': {'customerId': 'owner', 'draftId': ID}}
    page = requests.customer_requests(table, 'owner', now=NOW, after=ID)
    assert len(page['requests']) == 1 and page['nextAfter'] == ID
    assert table.query.call_args.kwargs['ExclusiveStartKey'] == {'customerId': 'owner', 'draftId': ID}
    assert 'requestData' not in table.query.call_args.kwargs['ProjectionExpression']
    with pytest.raises(InvalidPlan): requests.customer_requests(table, 'owner', now=NOW, after={'customerId': 'victim'})


def test_native_operator_queue_cannot_be_called_through_http(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('assistance_handler', root / 'amplify/functions/ecommerce/arogya-booking/handler.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'require_customer', lambda _: (None, {'statusCode': 401}))
    db = Mock(); monkeypatch.setattr(module, '_table', db)
    event = {'requestContext': {'http': {'method': 'POST'}}, 'body': json.dumps({'internalAction': 'listAssistanceRequests'})}
    assert module.handler(event, None)['statusCode'] == 401
    db.assert_not_called()
    identity = SimpleNamespace(subject='owner', phone_verified=True)
    monkeypatch.setattr(module, 'require_customer', lambda _: (identity, None))
    event['body'] = json.dumps({'action': 'access'})
    key = json.loads(module.handler(event, None)['body'])['accountKey']
    submit = Mock(return_value={'requestId': ID, 'appointmentConfirmed': False})
    monkeypatch.setattr(module.requests, 'submit', submit)
    event['body'] = json.dumps({'action': 'submitRequest', 'accountKey': 'wrong', 'requestId': ID, 'request': form()})
    assert module.handler(event, None)['statusCode'] == 409
    submit.assert_not_called()
    event['body'] = json.dumps({'action': 'submitRequest', 'accountKey': key, 'requestId': ID, 'request': form()})
    assert module.handler(event, None)['statusCode'] == 200
    assert submit.call_args.args[1] == 'owner'


def test_replay_after_midnight_uses_original_intake_date(monkeypatch):
    table = Mock(); table.name = 'existing-table'; table.get_item.return_value = {}
    client = Mock(); monkeypatch.setattr(requests, 'transaction_client', lambda: client)
    value = form(); value['preferredDate'] = '2026-11-28'
    original = requests.submit(table, 'owner', ID, value, now=NOW)
    values = client.transact_write_items.call_args.kwargs['TransactItems'][0]['Update']['ExpressionAttributeValues']
    table.get_item.return_value = {'Item': {'kind': requests.KIND, 'fingerprint': values[':hash']['S'],
        'draftId': ID, 'createdAt': NOW, 'expiresAt': NOW + 30 * 86400}}
    assert requests.submit(table, 'owner', ID, value, now=NOW + 86400) == original


def test_transaction_parameters_are_accepted_by_the_real_sdk_shape(monkeypatch):
    import boto3
    from botocore.stub import Stubber, ANY
    client = boto3.client('dynamodb', region_name='us-east-1', aws_access_key_id='synthetic', aws_secret_access_key='synthetic')
    table = Mock(); table.name = 'existing-table'; table.get_item.return_value = {}
    monkeypatch.setattr(requests, 'transaction_client', lambda: client)
    with Stubber(client) as stub:
        stub.add_response('transact_write_items', {}, {'TransactItems': ANY})
        assert requests.submit(table, 'owner', ID, form(), now=NOW)['status'] == 'REQUESTED'
        stub.assert_no_pending_responses()
