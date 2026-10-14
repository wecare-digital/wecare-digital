"""Connection evidence must come from fixed, authenticated, read-only endpoints."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('workspace_adapters', Path(__file__).resolve().parents[1] / 'amplify/functions/ai/workspace-mcp/provider_adapters.py')
ADAPTERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTERS)


class Refusal(Exception): pass


def test_retired_provider_never_reads_credentials_or_network():
    def forbidden(*args, **kwargs):
        pytest.fail("retired provider performed an external operation")
    with pytest.raises(Refusal, match="not enabled"):
        ADAPTERS.verify('wix', 'owner', forbidden, forbidden, forbidden, Refusal, {})


def verify(provider, response, calls):
    def http(url, payload=None, headers=None):
        calls.append((url, payload, headers))
        return response, None
    def secret(name):
        assert name in {'wecare/razorpay/api', 'wecare/wix/headless-api-key', 'wecare/google/ads'}
        return {'key_id': 'fixture-id', 'key_secret': 'fixture-secret', 'api_key': 'fixture-key', 'site_id': 'fixture-site', 'developer_token': 'fixture-developer'}
    return ADAPTERS.verify(provider, 'owner', secret, http, lambda owner, provider: 'fixture-access', Refusal, {})


def test_payment_probe_does_not_return_order_or_customer_data():
    calls = []
    result = verify('razorpay', {'entity': 'collection', 'count': 1, 'items': [{'id': 'private-order', 'notes': {'customer': 'private-customer'}}]}, calls)
    assert calls[0][0] == 'https://api.razorpay.com/v1/orders?count=1'
    assert calls[0][1] is None
    assert result == {'mode': 'read-only', 'resource': 'collection', 'returnedCount': 1}


@pytest.mark.parametrize('provider', ['razorpay', 'wix', 'google-cloud', 'google-ads'])
def test_invalid_provider_response_cannot_be_verified(provider):
    with pytest.raises(Refusal): verify(provider, {}, [])


def test_google_project_is_bound_to_owner_project():
    with pytest.raises(Refusal): verify('google-cloud', {'projectId': 'unrelated'}, [])
    calls = []
    result = verify('google-cloud', {'projectId': 'wecaredigitalbw', 'state': 'ACTIVE', 'name': 'projects/756034744787'}, calls)
    assert calls[0][0].endswith('/projects/wecaredigitalbw')
    assert result['project'] == 'wecaredigitalbw'


def test_docs_use_negotiated_session_and_never_claim_live_access():
    calls = []
    def http(url, payload=None, headers=None):
        calls.append((payload['method'], dict(headers or {})))
        if payload['method'] == 'initialize': return {'result': {'protocolVersion': '2025-06-18'}}, 'fixture-session'
        if payload['method'] == 'tools/list': return {'result': {'tools': [{'name': 'search'}]}}, None
        return {}, None
    result = ADAPTERS.verify('sinch', 'owner', lambda name: pytest.fail('documentation must not use credentials'), http,
        lambda *a: pytest.fail('documentation must not use account token'), Refusal, {'endpoint': 'https://developers.sinch.com/mcp'})
    assert result['liveAccountAccess'] is False
    assert result['mode'] == 'documentation-only'
    assert calls[2][1]['MCP-Protocol-Version'] == '2025-06-18'
    assert calls[2][1]['Mcp-Session-Id'] == 'fixture-session'
