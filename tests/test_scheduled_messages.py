"""Scheduled API timestamp contract: invalid input refuses writes; offsets are canonical UTC."""
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))

@pytest.fixture
def module(monkeypatch):
    path = ROOT / 'amplify/functions/messaging/scheduled-messages/handler.py'
    spec = importlib.util.spec_from_file_location('schedule_time_test_handler', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(mod, 'datetime', Clock)
    monkeypatch.setattr(mod, 'require_auth', lambda *a, **kw: None)
    table = Mock()
    table.get_item.return_value = {'Item': {'id': 'schedule1', 'status': 'PENDING'}}
    table.update_item.return_value = {'Attributes': {'id': 'schedule1', 'status': 'PENDING'}}
    contacts = Mock()
    contacts.get_item.return_value = {'Item': {'name': 'Fixture', 'phone': '+919999999999'}}
    monkeypatch.setattr(mod, 'dynamodb', Mock(Table=lambda name: contacts if name == mod.CONTACTS_TABLE else table))
    monkeypatch.setattr(mod, 'lambda_client', Mock())
    return mod, table, contacts

def api(mod, method, value):
    body = {'contactId': 'contact1', 'templateName': 'fixture', 'scheduledAt': value}
    return mod.handler({'httpMethod': method, 'path': '/scheduled/schedule1', 'pathParameters': {'scheduledId': 'schedule1'}, 'body': json.dumps(body)}, None)

@pytest.mark.parametrize('method', ['POST', 'PUT'])
@pytest.mark.parametrize('value', ['2027-01-01T12:00:00', 12345, [], {}, None, 'invalid', '2026-10-09T12:00:00Z', '2026-10-09T11:59:59Z'])
def test_invalid_or_nonfuture_timestamp_is_400_without_mutation(module, method, value):
    mod, table, contacts = module
    response = api(mod, method, value)
    assert response['statusCode'] == 400
    table.put_item.assert_not_called()
    table.update_item.assert_not_called()
    mod.lambda_client.invoke.assert_not_called()

@pytest.mark.parametrize('method', ['POST', 'PUT'])
@pytest.mark.parametrize('value', ['2026-10-09T13:30:00+01:00', '2026-10-09T12:30:00Z', '2026-10-09T07:00:00-05:30'])
def test_equivalent_future_instants_store_canonical_utc(module, method, value):
    mod, table, contacts = module
    response = api(mod, method, value)
    assert response['statusCode'] == (201 if method == 'POST' else 200)
    stored = table.put_item.call_args.kwargs['Item']['scheduledAt'] if method == 'POST' else table.update_item.call_args.kwargs['ExpressionAttributeValues'][':scheduledAt']
    assert stored == '2026-10-09T12:30:00.000000+00:00'
    mod.lambda_client.invoke.assert_not_called()

def test_due_query_cutoff_has_same_zero_fraction_format(module):
    mod, table, contacts = module
    table.query.return_value = {'Items': []}
    response = mod._process_due_messages('fixture')
    assert response['statusCode'] == 200
    assert table.query.call_args.kwargs['ExpressionAttributeValues'][':now'] == '2026-10-09T12:00:00.000000+00:00'
    mod.lambda_client.invoke.assert_not_called()

from io import BytesIO
from copy import deepcopy
from botocore.exceptions import ClientError

def conflict():
    return ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'UpdateItem')

def outbound(code=200, body=None, **extra):
    body = body if body is not None else {'status': 'sent', 'mode': 'LIVE', 'whatsappMessageId': 'wamid.fixture'}
    return {'StatusCode': 200, 'Payload': BytesIO(json.dumps({'statusCode': code, 'body': json.dumps(body)}).encode()), **extra}

class ClaimTable:
    def __init__(self, row):
        self.row = deepcopy(row)
        self.snapshot = deepcopy(row)
        self.writes = []
        self.final_failures = 0
    def query(self, **kwargs):
        # Deliberately stale GSI: return the same original pending snapshot each run.
        return {'Items': [deepcopy(self.snapshot)]}
    def update_item(self, **kwargs):
        self.writes.append(kwargs)
        vals = kwargs['ExpressionAttributeValues']
        condition = kwargs['ConditionExpression']
        if ':pending' in vals:
            assert '#status = :pending' in condition
            if self.row['status'] != 'PENDING': raise conflict()
            for key in ('scheduledAt', 'updatedAt'):
                marker = ':expected_' + key
                if marker in vals:
                    assert '#' + key + ' = ' + marker in condition
                    if self.row.get(key) != vals[marker]: raise conflict()
                else:
                    assert 'attribute_not_exists(#' + key + ')' in condition
                    if key in self.row: raise conflict()
            self.row.update(status='DISPATCHING', dispatchToken=vals[':token'], updatedAt=vals[':now'])
        else:
            assert condition == '#status = :dispatching AND #dispatchToken = :token'
            if self.row['status'] != 'DISPATCHING' or self.row['dispatchToken'] != vals[':token']: raise conflict()
            if self.final_failures:
                self.final_failures -= 1
                raise OSError('fixture write failed')
            self.row.update(status=vals[':status'], errorMessage=vals[':error'])
            if vals[':status'] == 'SENT': self.row['sentAt'] = vals[':now']
        return {'Attributes': deepcopy(self.row)}

@pytest.fixture
def worker(module, monkeypatch):
    mod, _, _ = module
    table = ClaimTable({'id': 'schedule1', 'status': 'PENDING', 'scheduledAt': '2026-10-09T11:00:00.000000+00:00', 'updatedAt': 'original', 'contactId': 'contact1', 'templateName': 'fixture', 'recipientBsuid': 'US.fixture'})
    monkeypatch.setattr(mod, 'dynamodb', Mock(Table=lambda _: table))
    mod.lambda_client.invoke.return_value = outbound()
    return mod, table

def test_only_one_claim_winner_sends_despite_repeated_stale_gsi_snapshot(worker):
    mod, table = worker
    first = json.loads(mod._process_due_messages('one')['body'])
    second = json.loads(mod._process_due_messages('two')['body'])
    assert first['sent'] == 1 and second['skipped'] == 1
    assert table.row['status'] == 'SENT'
    assert mod.lambda_client.invoke.call_count == 1
    payload = json.loads(mod.lambda_client.invoke.call_args.kwargs['Payload'])
    assert json.loads(payload['body'])['recipientBsuid'] == 'US.fixture'

@pytest.mark.parametrize('change', [{'status': 'CANCELLED'}, {'updatedAt': 'new'}, {'scheduledAt': '2027-01-01T00:00:00.000000+00:00'}])
def test_cancelled_or_changed_snapshot_cannot_send(worker, change):
    mod, table = worker
    table.row.update(change)
    result = json.loads(mod._process_due_messages('fixture')['body'])
    assert result['skipped'] == 1
    mod.lambda_client.invoke.assert_not_called()

@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_update_cancel_race_returns_409_and_does_not_send(module, method):
    mod, table, _ = module
    table.get_item.return_value = {'Item': {'status': 'PENDING', 'scheduledAt': 'old', 'updatedAt': 'old-version'}}
    table.update_item.side_effect = conflict()
    response = api(mod, method, '2027-01-01T00:00:00Z')
    assert response['statusCode'] == 409
    kw = table.update_item.call_args.kwargs
    assert '#status = :pending' in kw['ConditionExpression']
    assert kw['ExpressionAttributeValues'][':expected_updatedAt'] == 'old-version'
    assert kw['ExpressionAttributeValues'][':expected_scheduledAt'] == 'old'
    mod.lambda_client.invoke.assert_not_called()

def test_legacy_absent_updated_at_is_claimed_only_while_absent(worker):
    mod, table = worker
    table.snapshot.pop('updatedAt');table.row.pop('updatedAt')
    assert json.loads(mod._process_due_messages('fixture')['body'])['sent'] == 1
    assert 'attribute_not_exists(#updatedAt)' in table.writes[0]['ConditionExpression']

def test_legacy_absent_updated_at_changed_since_snapshot_is_not_sent(worker):
    mod, table = worker
    table.snapshot.pop('updatedAt')
    assert json.loads(mod._process_due_messages('fixture')['body'])['skipped'] == 1
    mod.lambda_client.invoke.assert_not_called()

@pytest.mark.parametrize('response,expected', [
    (outbound(400, {'error': 'refused'}), 'FAILED'),
    (outbound(200, {'status': 'dry_run', 'mode': 'DRY_RUN'}), 'FAILED'),
    (outbound(500, {'error': 'ambiguous'}), 'DISPATCH_UNKNOWN'),
    (outbound(200, {'success': True}), 'DISPATCH_UNKNOWN'),
    (outbound(200, {'status': 'sent', 'mode': 'LIVE'}), 'DISPATCH_UNKNOWN'),
    ({'StatusCode': 200, 'Payload': BytesIO(b'[]')}, 'DISPATCH_UNKNOWN'),
    ({'StatusCode': 200, 'Payload': BytesIO(b'invalid')}, 'DISPATCH_UNKNOWN'),
    (outbound(FunctionError='Unhandled'), 'DISPATCH_UNKNOWN'),
    (outbound(200, {'idempotent': True, 'whatsappMessageId': 'wamid.fixture'}), 'SENT'),
])
def test_outcome_requires_positive_send_evidence_and_never_requeues(worker, response, expected):
    mod, table = worker
    mod.lambda_client.invoke.return_value = response
    mod._process_due_messages('fixture')
    assert table.row['status'] == expected
    assert ('sentAt' in table.row) == (expected == 'SENT')
    mod._process_due_messages('retry')
    assert mod.lambda_client.invoke.call_count == 1

def test_invoke_transport_error_is_unknown_without_automatic_retry(worker):
    mod, table = worker
    mod.lambda_client.invoke.side_effect = OSError('fixture transport')
    result = json.loads(mod._process_due_messages('fixture')['body'])
    assert result['unknown'] == 1 and result['sent'] == 0
    assert table.row['status'] == 'DISPATCH_UNKNOWN'
    mod._process_due_messages('retry')
    assert mod.lambda_client.invoke.call_count == 1

@pytest.mark.parametrize('failures,expected', [(1, 'DISPATCH_UNKNOWN'), (2, 'DISPATCHING')])
def test_result_persistence_failure_keeps_claim_excluded_from_retry(worker, failures, expected):
    mod, table = worker
    table.final_failures = failures
    result = json.loads(mod._process_due_messages('fixture')['body'])
    assert result['unknown'] == 1 and result['sent'] == 0
    assert table.row['status'] == expected
    mod._process_due_messages('retry')
    assert mod.lambda_client.invoke.call_count == 1

def test_missing_template_is_failed_before_outbound(worker):
    mod, table = worker
    table.row.pop('templateName');table.snapshot.pop('templateName')
    assert json.loads(mod._process_due_messages('fixture')['body'])['failed'] == 1
    assert table.row['status'] == 'FAILED'
    mod.lambda_client.invoke.assert_not_called()

def test_claim_store_error_prevents_invoke(worker, monkeypatch):
    mod, table = worker
    monkeypatch.setattr(table, 'update_item', Mock(side_effect=ClientError({'Error': {'Code': 'ProvisionedThroughputExceededException'}}, 'UpdateItem')))
    assert mod._process_due_messages('fixture')['statusCode'] == 503
    mod.lambda_client.invoke.assert_not_called()


def test_runtime_lambda_transport_retries_are_disabled(monkeypatch):
    import boto3
    client = Mock(return_value=Mock())
    monkeypatch.setattr(boto3, 'client', client)
    spec = importlib.util.spec_from_file_location('schedule_transport_test_handler', ROOT / 'amplify/functions/messaging/scheduled-messages/handler.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = [call for call in client.call_args_list if call.args and call.args[0] == 'lambda']
    assert len(calls) == 1
    assert calls[0].kwargs['config'].retries['total_max_attempts'] == 1


@pytest.mark.parametrize('body', ['invalid', '[]', 'null', '"text"', '17', 'true'])
@pytest.mark.parametrize('method', ['POST', 'PUT'])
def test_malformed_or_nonobject_json_is_400_before_store_calls(module, method, body):
    mod, table, contacts = module
    response = mod.handler({'httpMethod': method, 'path': '/scheduled/schedule1', 'body': body}, None)
    assert response['statusCode'] == 400
    table.get_item.assert_not_called()
    table.put_item.assert_not_called()
    table.update_item.assert_not_called()
    contacts.get_item.assert_not_called()
    mod.lambda_client.invoke.assert_not_called()

@pytest.mark.parametrize('provider_id', [True, 42, ['wamid'], {'id': 'wamid'}, '', '   ', None])
def test_malformed_provider_id_never_certifies_sent(worker, provider_id):
    mod, table = worker
    mod.lambda_client.invoke.return_value = outbound(200, {'status': 'sent', 'mode': 'LIVE', 'whatsappMessageId': provider_id})
    result = json.loads(mod._process_due_messages('fixture')['body'])
    assert result['sent'] == 0 and result['unknown'] == 1
    assert table.row['status'] == 'DISPATCH_UNKNOWN'

def test_due_query_reads_only_remaining_fifty_items_across_pages(module):
    mod, table, contacts = module
    table.query.side_effect = [
        {'Items': [{} for _ in range(20)], 'LastEvaluatedKey': {'id': 'page1'}},
        {'Items': [{} for _ in range(30)], 'LastEvaluatedKey': {'id': 'page2'}},
        {'Items': [{} for _ in range(50)]},
    ]
    result = json.loads(mod._process_due_messages('fixture')['body'])
    assert result['skipped'] == 50
    assert table.query.call_count == 2
    assert [c.kwargs['Limit'] for c in table.query.call_args_list] == [50, 30]
    assert table.query.call_args_list[1].kwargs['ExclusiveStartKey'] == {'id': 'page1'}
    mod.lambda_client.invoke.assert_not_called()

def test_due_query_empty_page_continues_with_same_remaining_limit(module):
    mod, table, contacts = module
    table.query.side_effect = [{'Items': [], 'LastEvaluatedKey': {'id': 'empty'}}, {'Items': [{}]}]
    assert json.loads(mod._process_due_messages('fixture')['body'])['skipped'] == 1
    assert [c.kwargs['Limit'] for c in table.query.call_args_list] == [50, 50]
