"""Collision safety, retryable derived audits, and bounded partner caches."""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'amplify/functions/shared'), str(ROOT / 'tests'),
                str(ROOT / 'amplify/functions/operations/seo-tools')]
from crm_fake_dynamo import FakeDynamo
from lambda_utils import flow_completion as fc, idempotency as idem


def test_short_collision_keeps_both_completions_and_dedupes_each(monkeypatch):
    keys = {'one': '12345678' + '1' * 24, 'two': '12345678' + '2' * 24}
    monkeypatch.setattr(fc, 'completion_key', lambda token, *_: (keys[token], False))
    fake = FakeDynamo({fc.FLOW_SUBMISSIONS_TABLE: 'submissionId'}, {fc.FLOW_SUBMISSIONS_TABLE: {}})
    monkeypatch.setattr(fc, '_table', lambda: fake.Table(fc.FLOW_SUBMISSIONS_TABLE))
    first = fc.claim_completion(flow_token='one', reference_prefix='WD-SR')
    second = fc.claim_completion(flow_token='two', reference_prefix='WD-SR', requires_payment=True,
                                 payment_amount=100, extra={'referenceId': 'original'})
    assert first.created and second.created
    assert first.submission_id == 'WD-SR-12345678'
    assert second.submission_id != first.submission_id
    assert second.reference == second.submission_id
    assert second.item['paymentAmount'] == 100
    assert second.item['referenceId'] == 'original'
    assert fc.claim_completion(flow_token='one', reference_prefix='WD-SR').duplicate
    assert fc.claim_completion(flow_token='two', reference_prefix='WD-SR').duplicate


def test_collision_lookup_failure_fails_closed(monkeypatch):
    table = MagicMock()
    table.put_item.side_effect = ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'PutItem')
    table.get_item.side_effect = RuntimeError('unavailable')
    monkeypatch.setattr(fc, '_table', lambda: table)
    result = fc.claim_completion(flow_token='synthetic')
    assert result.status == 'error' and not result.should_fire_side_effects


def test_completion_table_initialization_failure_fails_closed(monkeypatch):
    def unavailable():
        raise RuntimeError('table unavailable')
    monkeypatch.setattr(fc, '_table', unavailable)
    result = fc.claim_completion(flow_token='synthetic')
    assert result.status == 'error' and not result.should_fire_side_effects


def test_registry_writer_uses_free_standard_ssm_and_dry_run_writes_nothing():
    spec = importlib.util.spec_from_file_location('review_registry', ROOT / 'scripts/sync_webhook_registry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module.boto3, 'client') as client:
        module.write_parameter(True)
        client.assert_not_called()
        client.return_value.put_parameter.return_value = {'Version': 2}
        module.write_parameter(False)
        client.assert_called_once_with('ssm', region_name='us-east-1')
        params = client.return_value.put_parameter.call_args.kwargs
        assert params['Tier'] == 'Standard' and params['Type'] == 'String'
        assert len(params['Value'].encode()) <= 4096


@pytest.fixture
def seo():
    spec = importlib.util.spec_from_file_location('review_seo', ROOT / 'amplify/functions/operations/seo-tools/handler.py')
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    return module


def test_missing_post_never_claims_then_corrected_retry_runs(seo):
    with patch.object(seo, 'claim_admin_action', return_value=True) as claim, \
         patch.object(seo, 'release_admin_audit'), \
         patch.object(seo.storage, 'get_blog_post', side_effect=[None, {'slug': 'post'}]), \
         patch.object(seo, '_run_audit', return_value=({}, {})) as audit:
        with pytest.raises(LookupError):
            seo._blog_audit({'slug': 'post'}, 'admin', '')
        claim.assert_not_called()
        assert seo._blog_audit({'slug': 'post', 'force': True}, 'admin', '')['statusCode'] == 200
        assert audit.call_args.kwargs['force'] is True


def test_failed_audit_releases_its_fenced_lease(seo):
    with patch.object(seo, 'claim_admin_action', return_value=True) as claim, \
         patch.object(seo, 'release_admin_audit') as release, \
         patch.object(seo.storage, 'get_blog_post', return_value={'slug': 'post'}), \
         patch.object(seo, '_run_audit', side_effect=RuntimeError('model failed')):
        with pytest.raises(RuntimeError):
            seo._blog_audit({'slug': 'post'}, 'admin', '')
        release.assert_called_once_with(claim.call_args.args[0], claim.call_args.kwargs['claim_token'])


def test_audit_expired_lease_is_reclaimable_and_release_is_fenced():
    resource = MagicMock()
    table = resource.Table.return_value
    with patch.object(idem.boto3, 'resource', return_value=resource):
        assert idem.claim_admin_action('key', 'admin', 'audit', claim_token='owner')
        assert 'expiresAt < :now' in table.put_item.call_args.kwargs['ConditionExpression']
        idem.release_admin_audit('key', 'owner')
        assert table.delete_item.call_args.kwargs['ExpressionAttributeValues'] == {':token': 'owner'}
        table.delete_item.side_effect = ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'DeleteItem')
        idem.release_admin_audit('key', 'stale-owner')


def test_partner_tokens_refresh_after_ttl_and_do_not_serve_expired_token():
    with patch('boto3.client'), patch('boto3.resource'):
        spec = importlib.util.spec_from_file_location('review_partner', ROOT / 'amplify/functions/shared/lambda_utils/partner_tokens.py')
        pt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pt)
    secrets = MagicMock()
    secrets.exceptions.ResourceNotFoundException = type('MissingSecret', (Exception,), {})
    secrets.get_secret_value.side_effect = [
        {'SecretString': json.dumps({'access_token': 'synthetic-old'})},
        {'SecretString': json.dumps({'access_token': 'synthetic-new'})}, RuntimeError('down')]
    with patch.object(pt, '_secrets', secrets), patch.object(pt.time, 'monotonic', side_effect=[1000, 1001, 1301, 1602]):
        assert pt.get_partner_token('waba') == 'synthetic-old'
        assert pt.get_partner_token('waba') == 'synthetic-old'
        assert pt.get_partner_token('waba') == 'synthetic-new'
        assert pt.get_partner_token('waba') is None
    with patch.object(pt, 'list_tenants', side_effect=[[], [{'wabaId': 'new', 'phoneNumberId': 'phone'}], []]), \
         patch.object(pt.time, 'monotonic', side_effect=[2000, 2301, 2602]):
        pt._load_phone_index()
        pt._load_phone_index()
        assert pt._phone_index == {'phone': 'new'}
        pt._load_phone_index()
        assert pt._phone_index == {}
