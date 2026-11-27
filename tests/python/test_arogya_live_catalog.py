"""Live transport normalization, current-challenge sender discovery and Admin delegation."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lambda_utils.arogya.provider_runtime import choices, schedule_dates, discover_sender, ProviderRuntime, ProviderSetupRequired
from lambda_utils.arogya.apollo_client import ApolloUnavailable, ApolloSessionExpired
from lambda_utils.arogya.apollo_session import SessionResult, MAILBOX

ROOT = Path(__file__).resolve().parents[2]


def test_normalizes_the_inspected_provider_shapes_without_snapshot_fallback():
    assert choices([{'HospitalId': 1, 'HospitalName': 'Live hospital', 'CityName': 'Live city'}], 'hospitals') == [{'id': 1, 'label': 'Live hospital', 'city': 'Live city'}]
    assert choices([{'SpecialityId': 7, 'SpecialityName': 'Live speciality'}], 'specialities') == [{'id': 7, 'label': 'Live speciality'}]
    assert choices([{'id': -1, 'name': 'Other'}, {'id': 9, 'name': 'Live doctor'}], 'doctors') == [{'id': 9, 'label': 'Live doctor'}]
    assert choices([{'id': 0, 'name': '00'}], 'minutes') == [{'id': 0, 'label': '00'}]
    with pytest.raises(ApolloUnavailable):
        choices({'error': 'unavailable'}, 'hospitals')
    assert choices([], 'hospitals') == []


def test_schedule_filters_invalid_and_past_dates_and_deduplicates():
    assert schedule_dates([{'Name': '2026-11-30,2026-11-29,2026-02-30,2026-01-01,2026-11-30'}], 1795737600) == ['2026-11-29', '2026-11-30']


def test_sender_discovery_requires_current_apollo_sender_and_intended_recipient():
    message = {'internalDate': '1000000', 'payload': {'headers': [
        {'name': 'From', 'value': 'Apollo <otp@apollohospitals.com>'},
        {'name': 'To', 'value': MAILBOX}, {'name': 'Subject', 'value': 'Apollo OTP'}]}}
    def read(path, params):
        if path.endswith('/profile'): return {'emailAddress': MAILBOX}
        if path.endswith('/messages'): return {'messages': [{'id': 'current'}]}
        return message
    assert discover_sender(read, 990, 1010) == 'otp@apollohospitals.com'
    message['payload']['headers'][0]['value'] = 'OTP <otp@unrelated.example>'
    assert discover_sender(read, 990, 1010) == ''


def test_runtime_never_calls_provider_without_an_explicit_matching_delegation(monkeypatch):
    table = Mock(); table.get_item.return_value = {}
    runtime = object.__new__(ProviderRuntime)
    runtime.table = table
    runtime.oauth = Mock()
    with pytest.raises(ProviderSetupRequired): runtime.connect()
    runtime.oauth.token.assert_not_called()
    runtime.oauth.decrypt.assert_not_called()


def test_live_read_does_not_report_ready_while_service_signin_is_pending():
    runtime = object.__new__(ProviderRuntime)
    provider = Mock()
    runtime.connect = lambda: (provider, SessionResult('renewing', retry_after=3))
    assert runtime.read({'kind': 'bootstrap'}) == {'status': 'renewing', 'retryAfter': 3}
    provider.catalog.assert_not_called()


def test_runtime_uses_delegated_credentials_and_returns_only_live_options(monkeypatch):
    from lambda_utils.arogya import provider_runtime as module
    owner = 'a' * 64
    rows = {'arogya:provider:gmail': {'owner': owner, 'provider': 'google-gmail-apollo', 'expectedMailbox': MAILBOX, 'revision': 'v1'},
        'arogya:provider:credentials': {'owner': owner, 'cipher': b'synthetic-cipher', 'revision': 'v1'}}
    table = Mock()
    table.get_item.side_effect = lambda **kw: {'Item': rows[kw['Key']['pk']]}
    oauth = Mock()
    config = {'username': MAILBOX, 'password': 'synthetic-password', 'applicationHeader': 'public-app-id'}
    oauth.decrypt.return_value = config
    state = Mock(); state.read.return_value = {}
    monkeypatch.setenv('TOKEN_KEY', 'arn:aws:kms:us-east-1:775261844268:key/test')
    monkeypatch.setattr(module, 'EncryptedSessionStore', lambda *args, **kwargs: state)
    provider = Mock()
    provider.catalog.side_effect = lambda kind, **kw: ([{'hospitalId': 77, 'hospitalName': 'Current provider hospital', 'cityName': 'Current city'}] if kind == 'hospitals' else [{'id': 5, 'name': 'Current option'}])
    monkeypatch.setattr(module, 'ApolloClient', lambda header: provider)
    def advance(**kw):
        assert kw['credentials']() == config
        return SessionResult('ready', token='synthetic-provider-token')
    monkeypatch.setattr(module, 'advance_session', advance)
    runtime = ProviderRuntime(table=table, oauth=oauth, kms=Mock(), clock=lambda: 1795737600)
    result = runtime.read({'kind': 'bootstrap'})
    assert result['data']['hospitals'] == [{'id': 77, 'label': 'Current provider hospital', 'city': 'Current city'}]
    assert result['observedAt'] == 1795737600
    assert 'synthetic-provider-token' not in json.dumps(result)
    assert 'synthetic-password' not in json.dumps(result)
    assert provider.catalog.call_count == 5
    rows['arogya:provider:credentials']['revision'] = 'uncommitted-version'
    with pytest.raises(ProviderSetupRequired): runtime.connect()


def test_admin_setup_requires_explicit_consent_and_never_returns_password():
    spec = importlib.util.spec_from_file_location('arogya_setup_test', ROOT / 'amplify/functions/ai/workspace-mcp/arogya_setup.py')
    setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
    table = Mock(); encrypt = Mock(return_value=b'encrypted-only')
    token = Mock(return_value='test-access')
    http = Mock(return_value=({'emailAddress': MAILBOX}, None))
    params = dict(table=table, encrypt=encrypt, token=token, http=http, refuse=ValueError, header=lambda: 'public-app-id')
    with pytest.raises(ValueError): setup.configure('a' * 64, {'password': 'synthetic-password', 'authorizeService': False}, **params)
    table.put_item.assert_not_called()
    result = setup.configure('a' * 64, {'password': 'synthetic-password', 'authorizeService': True}, **params)
    assert 'synthetic-password' not in json.dumps(result)
    rows = [call.kwargs['Item'] for call in table.put_item.call_args_list]
    assert rows[0]['cipher'] == b'encrypted-only' and 'password' not in rows[0]
    assert rows[0]['revision'] == rows[1]['revision']
    assert rows[1]['expectedMailbox'] == MAILBOX
    table.delete_item.assert_called_once_with(Key={'pk': 'arogya:provider:apollo'})
