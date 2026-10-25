#!/usr/bin/env python3
"""Focused offline checks for the ChatGPT MCP boundary; no live credentials or AWS writes."""
import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'amplify/functions/ai/workspace-mcp'
sys.path.insert(0, str(SOURCE))
import chat_oauth as oauth

BASE = 'https://example.execute-api.us-east-1.amazonaws.com'
RESOURCE = BASE + '/mcp'
CALLBACK = 'https://chatgpt.com/connector/oauth/offline-fixture'
ENV = {'CHAT_API_ID': 'chat-fixture', 'CHAT_API_BASE': BASE,
       'CHAT_CLIENT_ID': 'fixture-client', 'CHAT_REDIRECT_URI': CALLBACK}


def token(**changes) -> str:
    value = {'iss': oauth.ISSUER, 'client_id': ENV['CHAT_CLIENT_ID'],
        'aud': RESOURCE, 'token_use': 'access', 'sub': 'staff-a',
        'exp': int(time.time()) + 900, 'scope': oauth.SCOPE}
    value.update(changes)
    payload = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    # Unsigned synthetic token; only the fake Cognito below accepts it.
    return 'fixture.' + payload + '.unsigned'


class Cognito:
    def __init__(self, groups=('Admin',), sub='staff-a', revoked=False):
        self.groups, self.sub, self.revoked = groups, sub, revoked
        self.calls = []

    def get_user(self, **kwargs):
        self.calls.append('GetUser')
        if self.revoked:
            raise ClientError({'Error': {'Code': 'NotAuthorizedException',
                'Message': 'fixture-credential-must-not-escape'}}, 'GetUser')
        return {'Username': self.sub, 'UserAttributes': [{'Name': 'sub', 'Value': self.sub}]}

    def admin_list_groups_for_user(self, **kwargs):
        assert kwargs == {'UserPoolId': oauth.POOL, 'Username': self.sub}
        self.calls.append('Groups')
        return {'Groups': [{'GroupName': name} for name in self.groups]}


def event(path='/mcp', method='POST', bearer=None, **changes) -> dict:
    value = {'requestContext': {'apiId': ENV['CHAT_API_ID'],
        'routeKey': ('ANY' if path == '/mcp' else method) + ' ' + path,
        'http': {'method': method, 'path': path}}, 'headers': {},
        'body': json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})}
    if bearer is not None:
        value['headers']['authorization'] = 'Bearer ' + bearer
    return {**value, **changes}


def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external call')


def main() -> None:
    checks = 0
    def check(condition, label):
        nonlocal checks
        assert condition, label
        checks += 1

    with patch.dict(os.environ, ENV):
        def dispatch(request, cognito=None, rpc=forbidden, exchange=forbidden):
            return oauth.dispatch(request, lambda service: cognito or Cognito(), rpc, exchange)
        for path in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-authorization-server'):
            response = dispatch(event(path, 'GET'))
            check(response['statusCode'] == 200, 'Public metadata')
            body = json.loads(response['body'])
            check(body.get('resource', RESOURCE) == RESOURCE, 'Resource binding')
            check(body.get('authorization_response_iss_parameter_supported', False) is False, 'Exact callback required')
        wrong_api = event()
        wrong_api['requestContext']['apiId'] = 'another-api'
        check(dispatch(wrong_api) is None, 'Other API ignored')
        check(dispatch(event('/wrong'))['statusCode'] == 404, 'Unknown route')
        check(dispatch(event())['statusCode'] == 401, 'Anonymous challenge')
        query = {'response_type': 'code', 'client_id': ENV['CHAT_CLIENT_ID'],
            'redirect_uri': CALLBACK, 'resource': RESOURCE, 'scope': oauth.SCOPE,
            'state': 'opaque-state', 'code_challenge': 'a' * 43, 'code_challenge_method': 'S256'}
        response = dispatch(event('/authorize', 'GET', rawQueryString=urllib.parse.urlencode(query)))
        check(response['statusCode'] == 302, 'Authorization redirect')
        check(response['headers']['Location'].startswith(oauth.LOGIN + '/oauth2/authorize?'), 'Fixed upstream')
        hinted = dispatch(event('/authorize', 'GET', rawQueryString=urllib.parse.urlencode({**query, 'ui_locales': 'en-US'})))
        check(hinted['statusCode'] == 302, 'ChatGPT locale hint accepted')
        delegated = urllib.parse.parse_qs(urllib.parse.urlsplit(hinted['headers']['Location']).query)
        check('ui_locales' not in delegated and delegated['resource'] == [RESOURCE]
            and delegated['code_challenge'] == [query['code_challenge']], 'Locale hint cannot alter OAuth authority or PKCE')
        for locale in ('', 'en-US<script>', 'a' * 129, 'en_US'):
            check(dispatch(event('/authorize', 'GET', rawQueryString=urllib.parse.urlencode({**query,
                'ui_locales': locale})))['statusCode'] == 400, 'Invalid locale hint refused')
        for key, value in [('client_id', 'other'), ('redirect_uri', 'https://evil.invalid'),
                ('resource', 'https://evil.invalid'), ('code_challenge_method', 'plain'),
                ('code_challenge', ''), ('state', ''), ('scope', 'openid')]:
            raw = urllib.parse.urlencode({**query, key: value})
            check(dispatch(event('/authorize', 'GET', rawQueryString=raw))['statusCode'] == 400, key)
        raw = urllib.parse.urlencode(query) + '&state=duplicate'
        check(dispatch(event('/authorize', 'GET', rawQueryString=raw))['statusCode'] == 400, 'Duplicate field')
        called = []
        def rpc(request, principal):
            called.append(principal)
            return {'statusCode': 200}
        cognito = Cognito()
        check(dispatch(event(bearer=token()), cognito, rpc)['statusCode'] == 200, 'Valid staff')
        expected = hashlib.sha256((oauth.ISSUER + ':staff-a').encode()).hexdigest()
        check(called == [expected] and cognito.calls == ['GetUser', 'Groups'], 'Revocation and group recheck')
        other = oauth.owner(token(sub='staff-b'), ENV['CHAT_CLIENT_ID'], RESOURCE, Cognito(sub='staff-b'))
        check(other != expected, 'Separate principal custody')
        for changes in [{'exp': 0}, {'exp': True}, {'iss': 'https://evil.invalid'}, {'client_id': 'other'},
                {'aud': 'other'}, {'token_use': 'id'}, {'scope': 'openid'}, {'sub': ''}]:
            check(dispatch(event(bearer=token(**changes)))['statusCode'] == 401, str(changes))
        for identity, status in [(Cognito(groups=('Operator',)), 403), (Cognito(sub='wrong'), 401),
                (Cognito(revoked=True), 401)]:
            response = dispatch(event(bearer=token()), identity)
            check(response['statusCode'] == status, 'Identity refused')
            check('fixture-credential' not in response['body'], 'No error credential echo')
        check(dispatch(event(bearer='malformed'))['statusCode'] == 401, 'Malformed token')
        form = {'grant_type': 'authorization_code', 'client_id': ENV['CHAT_CLIENT_ID'],
            'redirect_uri': CALLBACK, 'resource': RESOURCE, 'code': 'fixture-code', 'code_verifier': 'v' * 43}
        def exchange(url, payload, **kwargs):
            assert url == oauth.LOGIN + '/oauth2/token' and kwargs == {'form': True}
            return {'access_token': token(), 'refresh_token': 'fixture-refresh', 'token_type': 'Bearer',
                    'expires_in': 900, 'id_token': 'must-not-return'}, None
        def token_event(data):
            request = event('/token', body=urllib.parse.urlencode(data))
            request['headers']['content-type'] = 'application/x-www-form-urlencoded'
            return request
        response = dispatch(token_event(form), exchange=exchange)
        check(response['statusCode'] == 200 and 'id_token' not in json.loads(response['body']), 'Code exchange filters tokens')
        refresh = {'grant_type': 'refresh_token', 'client_id': ENV['CHAT_CLIENT_ID'], 'refresh_token': 'fixture-refresh'}
        check(dispatch(token_event(refresh), exchange=exchange)['statusCode'] == 200, 'Refresh grant')
        for key, value in [('client_id', 'other'), ('redirect_uri', 'https://evil.invalid'),
                ('resource', ''), ('code_verifier', ''), ('grant_type', 'password'), ('client_secret', 'forbidden')]:
            check(dispatch(token_event({**form, key: value}))['statusCode'] == 400, key)
        check(dispatch(token_event({k: v for k, v in form.items() if k != 'resource'}))['statusCode'] == 400, 'Resource required')
        request = token_event(form)
        request['body'] += '&code=duplicate'
        check(dispatch(request)['statusCode'] == 400, 'Duplicate token form')
        request = token_event(form)
        request['headers']['authorization'] = 'Basic forbidden'
        check(dispatch(request)['statusCode'] == 400, 'No client secrets')
        request['headers'] = {'content-type': 'application/json'}
        check(dispatch(request)['statusCode'] == 400, 'Content type')
        def bad_exchange(*args, **kwargs):
            raise RuntimeError('fixture-credential-must-not-escape')
        response = dispatch(token_event(form), exchange=bad_exchange)
        check(response['statusCode'] == 400 and 'fixture-credential' not in response['body'], 'Upstream errors sanitized')
        def wrong_audience(*args, **kwargs):
            return {'access_token': token(aud='other')}, None
        check(dispatch(token_event(form), exchange=wrong_audience)['statusCode'] == 400, 'Upstream audience checked')
        spec = importlib.util.spec_from_file_location('gateway_handler', SOURCE / 'handler.py')
        gateway = importlib.util.module_from_spec(spec)
        original = Path.read_text
        def bundled_policy(path, *args, **kwargs):
            return original(ROOT / 'config/workspace-mcp.json' if path == SOURCE / 'workspace-mcp.json' else path, *args, **kwargs)
        with patch.object(Path, 'read_text', bundled_policy):
            spec.loader.exec_module(gateway)
        for error, expected_error in [('invalid_grant', 'invalid_grant'),
                ('invalid_grant fixture-credential-must-not-escape', None)]:
            failure = gateway.urllib.error.HTTPError('https://example.invalid', 400, 'Bad request', {},
                io.BytesIO(json.dumps({'error': error,
                    'error_description': 'fixture-credential-must-not-escape'}).encode()))
            detail = gateway.provider_error_detail(failure)
            check(detail.get('oauthError') == expected_error, 'Only exact standard OAuth errors retained')
            def refused_exchange(*args, **kwargs):
                raise gateway.Refusal('fixture-credential-must-not-escape', detail)
            with patch.object(oauth.logging.getLogger('workspace_mcp'), 'info') as log:
                result = dispatch(token_event(form), exchange=refused_exchange)
            audit = json.loads(log.call_args.args[0])
            check(audit == {'event': 'chat_oauth_token_refused',
                'reason': expected_error or 'unclassified'}, 'Bounded OAuth diagnostic')
            check('fixture-credential' not in result['body'] + json.dumps(detail) + json.dumps(audit),
                'OAuth diagnostics never echo credentials or upstream prose')
        with patch.object(gateway, 'client', return_value=Cognito()):
            response = gateway.handler(event(bearer=token()), None)
            tools = json.loads(response['body'])['result']['tools']
            check(bool(tools) and all(t['securitySchemes'][0]['scopes'] == [oauth.SCOPE] for t in tools), 'Real RPC OAuth discovery')
            origin = event(bearer=token())
            origin['headers']['origin'] = 'https://chatgpt.com'
            check(gateway.handler(origin, None)['statusCode'] == 200, 'Chat origin on dedicated API')
            origin['headers']['origin'] = 'https://evil.invalid'
            check(gateway.handler(origin, None)['statusCode'] == 403, 'Untrusted origin refused')
            staff = event(bearer='staff-fixture')
            staff['requestContext']['apiId'] = gateway.API_ID
            staff['requestContext']['authorizer'] = {'jwt': {'claims': {
                'iss': gateway.ISSUER, 'client_id': gateway.STAFF_CLIENT, 'token_use': 'access',
                'cognito:groups': ['Admin'], 'exp': int(time.time()) + 900, 'sub': 'staff-a'}}}
            check(gateway.owner_identity(staff) == expected, 'Same staff owner namespace')
            check(gateway.handler(staff, None)['statusCode'] == 200, 'Existing staff route')
            staff['headers']['origin'] = 'https://chatgpt.com'
            check(gateway.handler(staff, None)['statusCode'] == 403, 'Existing staff origin unchanged')
            staff['headers'].pop('origin')
            staff['requestContext'].pop('authorizer')
            check(gateway.handler(staff, None)['statusCode'] == 401, 'Existing anonymous rejected')
            staff['requestContext']['authorizer'] = {'iam': {'userArn': 'arn:aws:iam::775261844268:user/wecare-admin'}}
            check(gateway.handler(staff, None)['statusCode'] == 200, 'Existing IAM route')
            staff['requestContext']['authorizer']['iam']['userArn'] += '-other'
            check(gateway.handler(staff, None)['statusCode'] == 401, 'Other IAM denied')

    with patch.dict(os.environ, {**ENV, 'CHAT_CLIENT_ID': '', 'CHAT_REDIRECT_URI': ''}):
        for path in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-authorization-server'):
            response = oauth.dispatch(event(path, 'GET'), forbidden, forbidden, forbidden)
            check(response['statusCode'] == 200, 'Bootstrap discovery works before client setup')
        check(oauth.dispatch(event(), forbidden, forbidden, forbidden)['statusCode'] == 401,
            'Bootstrap anonymous MCP remains protected')
        check(oauth.dispatch(event(bearer=token()), forbidden, forbidden, forbidden)['statusCode'] == 503,
            'Bootstrap cannot authenticate until exact client is configured')
        for path, method in (('/authorize', 'GET'), ('/token', 'POST')):
            check(oauth.dispatch(event(path, method), forbidden, forbidden, forbidden)['statusCode'] == 503,
                'Bootstrap OAuth remains disabled')

    template = json.loads((ROOT / 'amplify/infra/workspace-mcp.json').read_text())
    baseline = json.loads(subprocess.check_output(['git', 'show',
        '7bfb5cc0c9ee8fd2ddad962be5417fa948ec5424:amplify/infra/workspace-mcp.json'], cwd=ROOT, text=True))
    # Only two runtime secret resources and Plivo's exact KMS context are added.
    role = json.loads(json.dumps(template['Resources']['Role']))
    statements = role['Properties']['Policies'][0]['PolicyDocument']['Statement']
    for statement in statements:
        if statement.get('Action') == ['secretsmanager:GetSecretValue']:
            added = ['arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/plivo/api-aIEx8b',
                'arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/sinch/rcs-18kRci']
            check(all(item in statement['Resource'] for item in added), 'Exact provider secrets')
            statement['Resource'] = [item for item in statement['Resource'] if item not in added]
        if statement.get('Action') == ['kms:Decrypt']:
            contexts = statement['Condition']['StringEquals']['kms:EncryptionContext:SecretARN']
            check(contexts == ['arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/google/ads-HuIYKY',
                'arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/plivo/api-aIEx8b'], 'Exact KMS contexts')
            statement['Condition']['StringEquals']['kms:EncryptionContext:SecretARN'] = contexts[0]
    check(role == baseline['Resources']['Role'], 'All other role permissions unchanged')
    for name in ('Authorizer', 'StaffRoute', 'IamRoute', 'CallbackRoute',
            'StaffPermission', 'IamPermission', 'CallbackPermission', 'Registry', 'TokenKey'):
        check(template['Resources'][name] == baseline['Resources'][name], name + ' unchanged')
    client = template['Resources']['ChatClient']['Properties']
    check(client['GenerateSecret'] is False and client['AllowedOAuthFlows'] == ['code'], 'Public code-only client')
    check(client['EnableTokenRevocation'] is True, 'Revocation enabled')
    check(client['CallbackURLs'] == [{'Ref': 'ChatRedirectUri'}], 'Exact callback')
    check(template['Parameters']['ChatRedirectUri']['Default'] == '', 'Disabled by default')
    check(template['Resources']['Version']['Properties']['Description']['Fn::If'][1] ==
        {'Ref': 'ChatRedirectUri'}, 'Callback configuration publishes a new immutable Lambda version')
    for name, value in template['Resources'].items():
        if name.startswith('Chat'):
            expected_condition = 'ChatEnabled' if name in {'ChatClient', 'ChatBranding'} else 'ChatProvisioned'
            check(value['Condition'] == expected_condition, name + ' conditional')
    print(f'PASS: {checks} offline authorization, revocation, isolation and infrastructure checks; no live writes')


if __name__ == '__main__':
    main()
