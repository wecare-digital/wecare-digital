#!/usr/bin/env python3
"""Offline checks for provider audience, tool and configuration isolation; no live writes."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'amplify/functions/ai/workspace-mcp'
sys.path.insert(0, str(SOURCE))
import chat_oauth
from verify_chat_mcp_auth import Cognito, token


def main() -> None:
    providers = ('google-cloud', 'google-ads', 'plivo', 'sinch')
    endpoints = {name: {'apiId': name + '-api', 'base': 'https://' + name + '.example.com',
        'callback': 'https://chatgpt.com/connector/oauth/' + name} for name in providers}
    env = {'PROVIDER_CHAT_ENDPOINTS': json.dumps(endpoints), 'CHAT_API_ID': 'legacy-api',
        'CHAT_API_BASE': 'https://legacy.example.com', 'CHAT_CLIENT_ID': 'public-client',
        'CHAT_REDIRECT_URI': 'https://chatgpt.com/connector/oauth/legacy'}
    with patch.dict(os.environ, env):
        for provider, config in endpoints.items():
            request = {'requestContext': {'apiId': config['apiId'],
                'routeKey': 'ANY /mcp', 'http': {'path': '/mcp', 'method': 'POST'}}, 'headers': {}}
            settings = chat_oauth.connection_settings(request)
            assert settings['provider'] == provider and settings['base'] == config['base']
            response = chat_oauth.dispatch(request, None, None, None)
            assert response['statusCode'] == 401
            assert config['base'] in response['headers']['WWW-Authenticate']
        assert chat_oauth.connection_settings({'requestContext': {'apiId': 'unknown'}}) is None
    spec = importlib.util.spec_from_file_location('provider_gateway', SOURCE / 'handler.py')
    gateway = importlib.util.module_from_spec(spec)
    original = Path.read_text
    def policy(path, *args, **kwargs):
        return original(ROOT / 'config/workspace-mcp.json' if path == SOURCE / 'workspace-mcp.json' else path, *args, **kwargs)
    with patch.object(Path, 'read_text', policy):
        spec.loader.exec_module(gateway)
    for provider in providers:
        tools = gateway.provider_tools(provider)
        names = {entry[0] for entry in tools}
        assert names == ({'connection_status', 'connection_verify', 'connection_authorize'}
            if provider.startswith('google-') else {'connection_status', 'connection_verify'})
        assert all(entry[2]['properties'] == {} for entry in tools)
        with patch.object(gateway, 'run_tool', return_value={'provider': provider}) as run:
            assert gateway.run_provider_tool('fixture-owner', provider, 'connection_verify', {}) == {'provider': provider}
            run.assert_called_once_with('fixture-owner', 'connection_verify', {'provider': provider})
        for name, args in [('aws_status', {}), ('connection_verify', {'provider': 'other'}),
                ('provider_read', {}), ('connection_verify', {'unused': 1})]:
            with patch.object(gateway, 'run_tool', side_effect=AssertionError('Must fail before provider access')):
                try:
                    gateway.run_provider_tool('fixture-owner', provider, name, args)
                    raise AssertionError('Cross-provider or unknown tool accepted')
                except gateway.Refusal:
                    pass
        request = {'requestContext': {'apiId': endpoints[provider]['apiId'],
            'routeKey': 'ANY /mcp', 'http': {'method': 'POST', 'path': '/mcp'}},
            'headers': {'origin': 'https://chatgpt.com'},
            'body': json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})}
        with patch.dict(os.environ, env), patch.object(gateway, 'client', return_value=Cognito()):
            request['headers']['authorization'] = 'Bearer ' + token(
                client_id='public-client', aud=endpoints[provider]['base'] + '/mcp')
            response = gateway.handler(request, None)
            assert response['statusCode'] == 200
            actual = json.loads(response['body'])['result']['tools']
            assert {tool['name'] for tool in actual} == names
            for other in providers:
                if other == provider:
                    continue
                request['headers']['authorization'] = 'Bearer ' + token(
                    client_id='public-client', aud=endpoints[other]['base'] + '/mcp')
                assert gateway.handler(request, None)['statusCode'] == 401
            request['headers']['authorization'] = 'Bearer ' + token(
                client_id='public-client', aud=endpoints[provider]['base'] + '/mcp')
            with patch.object(gateway, 'client', return_value=Cognito(groups=())):
                assert gateway.handler(request, None)['statusCode'] == 403
        with patch.object(gateway, 'row', return_value={}) as row:
            status = gateway.run_provider_tool('fixture-owner', provider, 'connection_status', {})
            assert [item['provider'] for item in status['connections']] == [provider]
            row.assert_called_once_with('connection:fixture-owner:' + provider)
    template = json.loads((ROOT / 'amplify/infra/workspace-mcp.json').read_text())
    assert template['Parameters']['ChatRedirectUri']['MaxLength'] <= 185
    assert template['Resources']['Function']['Properties']['ReservedConcurrentExecutions'] >= 5
    for resource in ('PlivoAuthorizeRoute', 'PlivoAuthorizePermission', 'PlivoTokenRoute', 'PlivoTokenPermission',
            'SinchIndiaAuthorizeRoute', 'SinchIndiaAuthorizePermission', 'SinchIndiaTokenRoute', 'SinchIndiaTokenPermission'):
        assert resource not in template['Resources']
    provider_request = {'requestContext': {'apiId': endpoints['plivo']['apiId'],
        'routeKey': 'ANY /mcp', 'http': {'method': 'POST', 'path': '/mcp'}},
        'headers': {'origin': 'https://chatgpt.com'},
        'body': json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'connection_status', 'arguments': {}}})}
    with patch.dict(os.environ, env), patch.object(gateway, 'client', return_value=Cognito()), \
            patch.object(gateway, 'row', return_value={}), patch.object(gateway.LOGGER, 'info') as audit:
        provider_request['headers']['authorization'] = 'Bearer ' + token(
            client_id='public-client', aud=endpoints['plivo']['base'] + '/mcp')
        response = gateway.handler(provider_request, None)
        assert response['statusCode'] == 200
        audit_payload = json.loads(audit.call_args.args[0])
        assert audit_payload['tool'] == 'connection_status' and audit_payload['outcome'] == 'completed'
    print('PASS: four provider routes, anonymous denial, fixed tool schemas and cross-provider call rejection')


if __name__ == '__main__':
    main()
