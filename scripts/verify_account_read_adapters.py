#!/usr/bin/env python3
"""Offline account-read boundary checks; synthetic credentials, no network or AWS."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'amplify/functions/ai/workspace-mcp/provider_adapters.py'
spec = importlib.util.spec_from_file_location('adapters', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Refusal(Exception):
    pass


def main():
    calls = []
    credentials = {
        'wecare/plivo/api': {'auth_id': 'FIXTURE123', 'auth_token': 'fixture-private'},
        'wecare/sinch/rcs': {'username': 'fixture-user', 'password': 'fixture-password',
            'project_id': 'fixture-project', 'app_id': 'fixture-app'},
    }

    def http(url, payload=None, headers=None, form=False):
        calls.append((url, payload, headers, form))
        if url.startswith('https://api.plivo.com/'):
            return {'auth_id': 'FIXTURE123', 'account_type': 'standard', 'billing_mode': 'prepaid',
                'cash_credits': '12.34', 'auth_token': 'fixture-private', 'address': 'private-address'}, None
        if url.startswith('https://auth.aclwhatsapp.com/'):
            assert form and payload['client_id'] == 'ipmessaging-client'
            return {'access_token': 'fixture-bearer', 'expires_in': 300}, None
        assert url == 'https://convapi.aclwhatsapp.com/v1/projects/fixture-project/apps/fixture-app'
        assert payload is None
        return {'id': 'fixture-app', 'channel_credentials': [{'secret': 'fixture-private'}],
            'display_name': 'private-name'}, None

    def verify(provider):
        return module.verify(provider, 'fixture-owner', credentials.__getitem__, http,
            lambda *_: 'fixture-google', Refusal, {})

    plivo = verify('plivo')
    assert plivo['liveAccountAccess'] is True and plivo['mode'] == 'read-only'
    assert plivo['accountType'] == 'standard'
    assert calls[-1][0] == 'https://api.plivo.com/v1/Account/FIXTURE123/'
    sinch = verify('sinch')
    assert sinch['liveAccountAccess'] is True and sinch['platform'] == 'sinch-india-rcs'
    assert sinch['appId'] == 'fixture-app'
    assert 'fixture-private' not in json.dumps([plivo, sinch])
    assert 'private-address' not in json.dumps([plivo, sinch])
    assert 'fixture-bearer' not in json.dumps([plivo, sinch])
    assert all('/messages' not in call[0] for call in calls)
    for provider, key, field in [('plivo', 'wecare/plivo/api', 'auth_token'),
            ('sinch', 'wecare/sinch/rcs', 'password'), ('sinch', 'wecare/sinch/rcs', 'app_id')]:
        original = credentials[key].pop(field)
        before = len(calls)
        try:
            verify(provider)
        except Refusal:
            pass
        else:
            raise AssertionError('Missing credential accepted')
        assert len(calls) == before
        credentials[key][field] = original
    credentials['wecare/sinch/rcs']['app_id'] = '../other-app'
    try:
        verify('sinch')
    except Refusal:
        pass
    else:
        raise AssertionError('Invalid resource path accepted')
    credentials['wecare/sinch/rcs']['app_id'] = 'fixture-app'
    for provider in ('plivo', 'sinch'):
        def denied(*args, **kwargs):
            raise Refusal('fixture-private provider error')
        try:
            module.verify(provider, 'fixture-owner', credentials.__getitem__, denied,
                lambda *_: '', Refusal, {})
        except Refusal as exc:
            assert 'fixture-private' not in str(exc)
        else:
            raise AssertionError('Denied provider accepted')
    print('Account reads: success, missing credentials, path validation, denied access and output minimization passed')


if __name__ == '__main__':
    main()
