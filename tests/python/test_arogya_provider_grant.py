"""Synthetic grant/session tests; no Google, Apollo, KMS or live AWS access."""
import json
from unittest.mock import Mock

import pytest

from lambda_utils.arogya import provider_grant as grant_module
from lambda_utils.arogya import provider_runtime as runtime
from lambda_utils.arogya.apollo_session import SessionResult
from lambda_utils.arogya.gmail_otp import MailboxAccessRequired

NOW = 1800000000
OWNER = 'a' * 64
CLIENT_ID = 'synthetic.apps.googleusercontent.com'
SCOPE = grant_module.SCOPE


def grant_fixture(*, status='verified', scope=SCOPE, expiry=NOW + 3600):
    db, kms, refresh = Mock(), Mock(), Mock()
    tokens = {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
              'scope': scope, '_oauth_client_id': CLIENT_ID}
    row = {'owner': OWNER, 'provider': grant_module.PROVIDER, 'status': status,
           'hasRefreshToken': True, 'lastVerifiedAt': NOW, 'cipher': b'cipher', 'expiresAt': expiry}
    db.get_item.return_value = {'Item': row}
    kms.decrypt.return_value = {'Plaintext': json.dumps(tokens).encode()}
    kms.encrypt.return_value = {'CiphertextBlob': b'new-cipher'}
    refresh.return_value = {'access_token': 'synthetic-new-access', 'expires_in': 3600}
    grant = grant_module.VerifiedGmailGrant(db, kms, key_arn='synthetic-key', owner=OWNER,
        oauth_config=lambda: {'client_id': CLIENT_ID, 'client_secret': 'synthetic-client-secret'},
        clock=lambda: NOW, refresh=refresh)
    return grant, db, kms, refresh


def test_cached_grant_is_owner_bound_and_does_not_refresh():
    grant, db, kms, refresh = grant_fixture()
    assert grant.access_token() == 'synthetic-access'
    assert db.get_item.call_args.kwargs == {
        'Key': {'pk': 'connection:' + OWNER + ':google-gmail-apollo'}, 'ConsistentRead': True}
    assert kms.decrypt.call_args.kwargs['EncryptionContext'] == {
        'purpose': 'workspace-mcp', 'provider': 'google-gmail-apollo', 'owner': OWNER}
    refresh.assert_not_called()
    db.update_item.assert_not_called()


def test_unverified_or_broader_grant_is_rejected():
    grant, _, kms, refresh = grant_fixture(status='authorized_unverified')
    with pytest.raises(MailboxAccessRequired):
        grant.access_token()
    kms.decrypt.assert_not_called()
    refresh.assert_not_called()
    grant, _, _, refresh = grant_fixture(scope=SCOPE + ' https://mail.google.com/')
    with pytest.raises(MailboxAccessRequired):
        grant.access_token()
    refresh.assert_not_called()


def test_refresh_preserves_exact_scope_and_is_fenced():
    grant, db, kms, refresh = grant_fixture(expiry=NOW)
    assert grant.access_token() == 'synthetic-new-access'
    refresh.assert_called_once_with(CLIENT_ID, 'synthetic-client-secret', 'synthetic-refresh')
    refreshed = json.loads(kms.encrypt.call_args.kwargs['Plaintext'])
    assert refreshed['scope'] == SCOPE and refreshed['refresh_token'] == 'synthetic-refresh'
    updates = db.update_item.call_args_list
    assert len(updates) == 3
    assert 'refreshLease = :lease' in updates[1].kwargs['ConditionExpression']
    assert 'refreshLockUntil > :now' in updates[1].kwargs['ConditionExpression']
    assert updates[2].kwargs['ConditionExpression'] == 'refreshLease = :lease'


def test_expanded_scope_on_refresh_does_not_persist():
    grant, db, kms, refresh = grant_fixture(expiry=NOW)
    refresh.return_value['scope'] = SCOPE + ' https://mail.google.com/'
    with pytest.raises(MailboxAccessRequired):
        grant.access_token()
    kms.encrypt.assert_not_called()
    assert len(db.update_item.call_args_list) == 2


def test_disabled_runtime_does_not_contact_aws(monkeypatch):
    monkeypatch.delenv('APOLLO_AUTOMATION_ENABLED', raising=False)
    resource = Mock()
    monkeypatch.setattr(runtime.boto3, 'resource', resource)
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime._provider_session(NOW)
    resource.assert_not_called()


def test_runtime_validates_grant_before_credentials_and_returns_renewal_only(monkeypatch):
    table, kms, store, grant = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime, '_runtime_store', lambda: (table, kms, store))
    monkeypatch.setenv('APOLLO_TOKEN_KEY_ARN', 'synthetic-key')
    monkeypatch.setenv('APOLLO_GMAIL_GRANT_OWNER', OWNER)
    monkeypatch.setattr(runtime, 'VerifiedGmailGrant', lambda *args, **kwargs: grant)
    config = Mock(return_value={'applicationHeader': 'synthetic', 'approvedSender': 'test@apollohospitals.com',
                                'username': runtime.MAILBOX, 'password': 'synthetic'})
    monkeypatch.setattr(runtime, '_provider_config', config)
    grant.verified_row.side_effect = MailboxAccessRequired('not verified')
    with pytest.raises(MailboxAccessRequired):
        runtime._provider_session(NOW)
    config.assert_not_called()
    grant.verified_row.side_effect = None
    advance = Mock(return_value=SessionResult('renewing', retry_after=3))
    monkeypatch.setattr(runtime, 'advance_session', advance)
    with pytest.raises(runtime.CatalogueRenewing) as pending:
        runtime._provider_session(NOW)
    assert pending.value.retry_after == 3
    grant.transport.assert_not_called()
    grant.verify_mailbox.assert_not_called()


def test_runtime_reuses_ready_session_without_gmail_reads(monkeypatch):
    table, kms, store, grant = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime, '_runtime_store', lambda: (table, kms, store))
    monkeypatch.setenv('APOLLO_TOKEN_KEY_ARN', 'synthetic-key')
    monkeypatch.setenv('APOLLO_GMAIL_GRANT_OWNER', OWNER)
    monkeypatch.setattr(runtime, 'VerifiedGmailGrant', lambda *args, **kwargs: grant)
    monkeypatch.setattr(runtime, '_provider_config', lambda *args: {
        'applicationHeader': 'synthetic', 'approvedSender': 'test@apollohospitals.com',
        'username': runtime.MAILBOX, 'password': 'synthetic'})
    monkeypatch.setattr(runtime, 'advance_session', lambda **kwargs: SessionResult('ready', token='synthetic-provider-token'))
    _, token = runtime._provider_session(NOW)
    assert token == 'synthetic-provider-token'
    grant.transport.assert_not_called()
    grant.verify_mailbox.assert_not_called()


def test_time_components_are_not_claimed_as_live_slots():
    provider = Mock()
    provider.catalog.side_effect = [[{'hour': '08'}, {'hour': 9}], [{'minute': 0}, {'minute': 15}]]
    result = runtime.read_catalog({'action': 'catalog', 'kind': 'times'}, now=NOW,
        session=lambda now: (provider, 'synthetic'))
    assert result['preferredOnly'] is True
    assert [v['id'] for v in result['options']] == ['08:00', '08:15', '09:00', '09:15']


def test_appointment_types_and_salutations_come_from_provider_rows():
    rows = [{'appointmentTypeId': 1, 'appointmentTypeName': 'Health Check'},
            {'appointmentTypeId': 2, 'appointmentTypeName': 'Unsupported'}]
    assert runtime.normalize('appointmentTypes', rows, now=NOW) == [{'id': '1', 'label': 'Health Checks'}]
    assert runtime.normalize('salutations', [{'salutationId': 2, 'salutationName': 'Dr.'}], now=NOW) == [{'id': '2', 'label': 'Dr'}]


SERVICE_ARN = 'arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/arogya/apollo-ABC123'


def approved_config():
    return {'username': runtime.MAILBOX, 'password': 'synthetic-password',
            'websiteAddress': 'https://aauser-ic.apollohospitals.com/',
            'providerAutomationApproved': True, 'grantOwner': OWNER,
            'approvedSender': 'synthetic@apollohospitals.com', 'applicationHeader': 'synthetic-header'}


def test_runtime_reads_only_pinned_current_service_secret(monkeypatch):
    monkeypatch.setenv('APOLLO_SERVICE_SECRET_ARN', SERVICE_ARN)
    monkeypatch.setenv('APOLLO_GMAIL_GRANT_OWNER', OWNER)
    client = Mock()
    client.get_secret_value.return_value = {'SecretString': json.dumps(approved_config())}
    monkeypatch.setattr(runtime.boto3, 'client', lambda service: client)
    assert runtime._provider_config() == approved_config()
    client.get_secret_value.assert_called_once_with(SecretId=SERVICE_ARN, VersionStage='AWSCURRENT')


@pytest.mark.parametrize('field,value', [
    ('providerAutomationApproved', False),
    ('grantOwner', 'b' * 64),
    ('username', 'other@example.com'),
    ('websiteAddress', 'https://example.com/'),
    ('applicationHeader', ''),
    ('applicationHeader', 'a\r\ninjected: header'),
    ('approvedSender', 'wrong@example.com'),
    ('password', ''),
])
def test_incomplete_or_wrong_service_config_fails_closed(field, value):
    config = {**approved_config(), field: value}
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime.validate_provider_config(config, OWNER)


def test_secret_arn_is_not_a_caller_selected_resource(monkeypatch):
    monkeypatch.setenv('APOLLO_SERVICE_SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:775261844268:secret:unrelated')
    load = Mock()
    monkeypatch.setattr(runtime, '_secret', load)
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime._provider_config()
    load.assert_not_called()


def test_saved_password_alone_does_not_enable_provider():
    config = {'username': runtime.MAILBOX, 'password': 'synthetic',
              'websiteAddress': 'https://aauser-ic.apollohospitals.com/'}
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime.validate_provider_config(config, OWNER)
