"""Gmail consent stays on the existing staff gateway and exact business mailbox."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'amplify/functions/ai/workspace-mcp'
MAILBOX = 'wecare.digital.bw@gmail.com'
SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    for name in ('handler.py', 'provider_adapters.py', 'chat_oauth.py'):
        (tmp_path / name).write_bytes((SOURCE / name).read_bytes())
    (tmp_path / 'workspace-mcp.json').write_bytes((ROOT / 'config/workspace-mcp.json').read_bytes())
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = importlib.util.spec_from_file_location('arogya_workspace_fixture', tmp_path / 'handler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_consent_uses_existing_callback_pkce_and_only_the_required_gmail_scope(gateway, monkeypatch):
    writes = []
    class Table:
        def put_item(self, **kwargs): writes.append(kwargs)
    monkeypatch.setattr(gateway, 'table', lambda: Table())
    monkeypatch.setattr(gateway, 'encrypt', lambda *args: b'synthetic-cipher')
    result = gateway.oauth_begin('a' * 64, 'google-gmail-apollo')
    query = parse_qs(urlsplit(result['authorizationUrl']).query)
    assert query['scope'] == [SCOPE]
    assert query['login_hint'] == [MAILBOX]
    assert query['access_type'] == ['offline']
    assert query['prompt'] == ['consent']
    assert query['code_challenge_method'] == ['S256']
    assert query['redirect_uri'] == ['https://wecare.digital/api/workspace/mcp/oauth/callback']
    assert len(writes) == 2
    assert 'refresh_token' not in result


@pytest.mark.parametrize('scope,email,success', [
    (SCOPE, MAILBOX, True),
    ('https://www.googleapis.com/auth/cloud-platform.read-only', MAILBOX, False),
    (SCOPE, 'other@gmail.com', False),
])
def test_callback_refuses_missing_scope_or_wrong_mailbox_before_saving(gateway, monkeypatch, scope, email, success):
    state = 's' * 40
    record = {'owner': 'a' * 64, 'provider': 'google-gmail-apollo',
              'expiresAt': 9999999999, 'cipher': b'synthetic'}
    class Table:
        def delete_item(self, **kwargs): pass
    monkeypatch.setattr(gateway, 'row', lambda key: record)
    monkeypatch.setattr(gateway, 'table', lambda: Table())
    monkeypatch.setattr(gateway, 'decrypt', lambda *args: {'verifier': 'v' * 64})
    monkeypatch.setattr(gateway, 'exchange_parameters', lambda *args: {'client_id': 'fixture-client'})
    saves = []
    monkeypatch.setattr(gateway, 'save_tokens', lambda *args: saves.append(args))
    def http(url, payload=None, headers=None, **kwargs):
        if url == 'https://oauth2.googleapis.com/token':
            return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'scope': scope}, None
        assert url == 'https://gmail.googleapis.com/gmail/v1/users/me/profile'
        assert headers == {'Authorization': 'Bearer synthetic-access'}
        return {'emailAddress': email}, None
    monkeypatch.setattr(gateway, 'http', http)
    if success:
        result = gateway.oauth_callback({'state': state, 'code': 'synthetic-code'})
        assert result['provider'] == 'google-gmail-apollo'
        assert len(saves) == 1
    else:
        with pytest.raises(gateway.Refusal): gateway.oauth_callback({'state': state, 'code': 'synthetic-code'})
        assert saves == []


def test_profile_verification_does_not_expose_mail_or_tokens(gateway):
    config = gateway.POLICY['connections']['google-gmail-apollo']
    from provider_adapters import verify
    result = verify(
        'google-gmail-apollo', 'a' * 64, lambda *_: pytest.fail('no secret read'),
        lambda url, **kwargs: ({'emailAddress': MAILBOX}, None),
        lambda *_: 'synthetic-access', gateway.Refusal, config)
    assert result == {'mode': 'read-only', 'mailboxVerified': True, 'purpose': 'Apollo IC sign-in codes'}
