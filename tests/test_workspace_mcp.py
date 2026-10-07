import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "amplify/functions/ai/workspace-mcp"


def test_persisted_refresh_grant_has_no_ttl_and_registry_explains_renewal(module, memory):
    module.save_tokens('owner', 'google-cloud', {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'expires_in': 3600})
    saved = memory.rows['connection:owner:google-cloud']
    assert saved['hasRefreshToken'] is True
    assert 'ttl' not in saved
    saved.update(expiresAt=1, status='verified', lastVerifiedAt=10)
    connection = next(c for c in module.registry('owner')['connections'] if c['provider'] == 'google-cloud')
    assert connection['status'] == 'refresh_pending'
    assert connection['automaticRefresh'] is True
    assert connection['persistent'] is True
    assert connection['lastVerifiedAt'] == 10
    assert 'fixture-' not in json.dumps(connection)


def test_refresh_preserves_account_verification_and_has_conditional_custody(module, memory, monkeypatch):
    calls = []
    monkeypatch.setattr(memory, 'update_item', lambda **kw: calls.append(kw))
    module.save_tokens('owner', 'google-cloud', {'access_token': 'fixture-new', 'refresh_token': 'fixture-refresh', 'expires_in': 3600}, lease='fixture-lease')
    update = calls[0]
    assert update['ConditionExpression'] == 'refreshLease = :lease'
    assert ':status' not in update['ExpressionAttributeValues']
    assert update['ExpressionAttributeValues'][':refresh'] is True
    assert 'lastVerifiedAt' not in update['UpdateExpression']
    assert 'ttl' not in update['UpdateExpression']


def test_connections_remain_scoped_to_same_account_across_new_requests(module, memory):
    memory.rows['connection:owner:aws'] = {'status': 'verified', 'lastVerifiedAt': 10}
    first = next(c for c in module.registry('owner')['connections'] if c['provider'] == 'aws')
    second = next(c for c in module.registry('owner')['connections'] if c['provider'] == 'aws')
    another = next(c for c in module.registry('another')['connections'] if c['provider'] == 'aws')
    assert first == second and second['lastVerifiedAt'] == 10
    assert another['lastVerifiedAt'] is None


@pytest.fixture
def module(monkeypatch):
    # Import needs only the static policy. No AWS clients are created at import.
    monkeypatch.syspath_prepend(str(DIRECTORY))
    policy_path = DIRECTORY / "workspace-mcp.json"
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **kw: (ROOT / "config/workspace-mcp.json").read_bytes().decode() if p == policy_path else original(p, *a, **kw))
    spec = importlib.util.spec_from_file_location("workspace_mcp_test", DIRECTORY / "handler.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    for name in ('meta-social', 'whatsapp'):
        result.POLICY['connections'][name].pop('registrationEndpoint', None)
        result.POLICY['connections'][name]['clientId'] = 'fixture-client'
    return result


def event(message=None, auth=True):
    return {"body": json.dumps(message or {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        "headers": {}, "requestContext": {"apiId": "zllr9lrg7j", "routeKey": "POST /workspace/mcp-iam",
        "http": {"method": "POST", "path": "/workspace/mcp-iam"},
        "authorizer": {"iam": {"userArn": "arn:aws:iam::775261844268:user/wecare-admin"}} if auth else {}}}


class MemoryTable:
    def __init__(self): self.rows = {}
    def get_item(self, Key, **kwargs): return {"Item": self.rows.get(Key["pk"], {})}
    def put_item(self, Item, **kwargs): self.rows[Item["pk"]] = Item
    def delete_item(self, Key, **kwargs):
        item = self.rows.get(Key["pk"])
        values = kwargs.get("ExpressionAttributeValues", {})
        if not item or (values and (item["stateHash"] != values[":s"] or item["expiresAt"] <= values[":n"])):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        del self.rows[Key["pk"]]
    def update_item(self, **kwargs): pass


@pytest.fixture
def memory(module, monkeypatch):
    table = MemoryTable()
    monkeypatch.setattr(module, "table", lambda: table)
    monkeypatch.setattr(module, "encrypt", lambda value, owner, provider: json.dumps(value).encode())
    monkeypatch.setattr(module, "decrypt", lambda value, owner, provider: json.loads(value))
    return table


def test_unauthenticated_never_reaches_tools(module, monkeypatch):
    monkeypatch.setattr(module, "run_tool", lambda *a: pytest.fail("must not call a tool"))
    assert module.handler(event(auth=False), None)["statusCode"] == 401


@pytest.mark.parametrize("change", ["api", "arn", "origin"])
def test_identity_binding(module, change):
    request = event()
    if change == "api": request["requestContext"]["apiId"] = "other"
    if change == "arn": request["requestContext"]["authorizer"]["iam"]["userArn"] = "arn:aws:iam::010526260063:user/wecare-admin"
    if change == "origin": request["headers"]["Origin"] = "https://evil.invalid"
    assert module.handler(request, None)["statusCode"] in (401, 403)


@pytest.mark.parametrize("bad", ["issuer", "audience", "id_token", "viewer", "expired"])
def test_staff_jwt_claims_fail_closed(module, bad):
    claims = {"iss": module.ISSUER, "client_id": module.STAFF_CLIENT, "token_use": "access", "cognito:groups": "[Admin]", "sub": "staff", "exp": str(int(time.time()) + 3600)}
    if bad == "issuer": claims["iss"] = "https://customer.invalid"
    if bad == "audience": claims["client_id"] = "customer-app"
    if bad == "id_token": claims["token_use"] = "id"
    if bad == "viewer": claims["cognito:groups"] = "[Viewer]"
    if bad == "expired": claims["exp"] = "1"
    request = event()
    request["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    assert module.handler(request, None)["statusCode"] == 401


def test_staff_access_token_authorized(module, monkeypatch):
    class Cognito:
        def get_user(self, **kwargs): return {"Username": "staff", "UserAttributes": [{"Name": "sub", "Value": "staff"}]}
        def admin_list_groups_for_user(self, **kwargs): return {"Groups": [{"GroupName": "Admin"}]}
    monkeypatch.setattr(module, "client", lambda *a: Cognito())
    request = event()
    request["headers"]["authorization"] = "Bearer fixture"
    request["requestContext"]["authorizer"] = {"jwt": {"claims": {"iss": module.ISSUER, "client_id": module.STAFF_CLIENT, "token_use": "access", "cognito:groups": "[Admin]", "sub": "staff", "exp": str(int(time.time()) + 3600)}}}
    assert module.handler(request, None)["statusCode"] == 200


def test_tool_inventory_has_no_mutating_provider_tools(module):
    result = json.loads(module.handler(event(), None)["body"])["result"]
    assert {x["name"] for x in result["tools"]} == {"connections_list", "connection_authorize", "connection_verify", "provider_read", "aws_status", "github_status", "code_job_submit", "code_job_status"}
    assert module.POLICY["connections"]["whatsapp"]["tools"] == {"whatsapp_biz_businesses": ["list"]}


@pytest.mark.parametrize("name,args", [
    ("whatsapp_biz_send_message", {"action": "send"}),
    ("devtools_webhook_manage", {"action": "create"}),
    ("devtools_app", {"action": "advanced_settings", "app_id": "other-app"}),
    ("devtools_app_list", {"action": "list", "endpoint": "http://169.254.169.254"}),
    ("devtools_app_list", {"action": "delete"}),
    ("devtools_app_list", {"action": "list", "limit": True}),
])
def test_provider_policy_refuses_before_network(module, name, args):
    with pytest.raises(module.Refusal): module.safe_provider_args("meta-social", name, args)


def test_callback_one_use_and_pkce(module, memory, monkeypatch):
    import urllib.parse
    begin = module.oauth_begin("owner", "meta-social")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(begin["authorizationUrl"]).query)
    assert query["redirect_uri"] == [module.CALLBACK]
    assert query["code_challenge_method"] == ["S256"]
    assert "developer_tools_mcp_app_management" not in query["scope"][0]
    seen = []
    def exchange(url, payload=None, **kw):
        seen.append(payload)
        return {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600}, None
    monkeypatch.setattr(module, "http", exchange)
    callback = {"state": query["state"][0], "code": "fixture-code"}
    assert module.oauth_callback(callback)["status"] == "authorized_unverified"
    assert "code_verifier" in seen[0] and seen[0]["resource"] == "https://mcp.facebook.com/devtools"
    connection = memory.rows["connection:owner:meta-social"]
    # TTL must not delete the refresh credential at access-token expiry.
    assert "ttl" not in connection
    with pytest.raises(module.Refusal): module.oauth_callback(callback)
    assert len(seen) == 1


def test_superseded_oauth_flow_cannot_authorize(module, memory, monkeypatch):
    import urllib.parse
    a = module.oauth_begin("owner", "whatsapp")
    module.oauth_begin("owner", "whatsapp")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(a["authorizationUrl"]).query)["state"][0]
    monkeypatch.setattr(module, "http", lambda *a, **kw: pytest.fail("superseded flow must not exchange"))
    with pytest.raises(module.Refusal): module.oauth_callback({"state": state, "code": "fixture"})


def test_callback_does_not_bypass_auth_on_similar_path(module):
    request = event(auth=False)
    request["requestContext"]["http"]["path"] = "/workspace/mcp/oauth/callback-evil"
    assert module.handler(request, None)["statusCode"] == 401


def test_registry_never_returns_ciphertext(module, memory):
    memory.rows["connection:owner:whatsapp"] = {"status": "verified", "expiresAt": int(time.time()) + 3600, "cipher": b"fixture-sensitive"}
    result = json.dumps(module.registry("owner"))
    assert "fixture-sensitive" not in result and "cipher" not in result
    assert "oauth-sdk" in result and "documentation-only" in result


def test_meta_registration_failure_does_not_create_login_flow(module, memory, monkeypatch):
    module.POLICY['connections']['meta-social']['registrationEndpoint'] = 'https://mcp.facebook.com/.well-known/register/devtools'
    def blocked(*a, **kw): raise module.Refusal('Provider authorization required')
    monkeypatch.setattr(module, 'http', blocked)
    with pytest.raises(module.Refusal, match='client registration is unavailable'):
        module.oauth_begin('owner', 'meta-social')
    assert not memory.rows


def test_ads_existing_app_uses_pkce_without_dynamic_registration(module, memory, monkeypatch):
    import urllib.parse
    monkeypatch.setattr(module, 'http', lambda *a, **kw: pytest.fail('must not register a dynamic Ads client'))
    value = module.oauth_begin('owner', 'meta-ads')
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value['authorizationUrl']).query)
    assert query['client_id'] == ['2238810740192680']
    assert query['code_challenge_method'] == ['S256']
    assert query['redirect_uri'] == [module.CALLBACK]
    # Exactly one permission mechanism is requested: a Login for Business configuration id
    # when the policy carries one, otherwise the scope list. Never both.
    if module.POLICY['connections']['meta-ads'].get('loginConfigId'):
        assert 'scope' not in query
    else:
        assert 'ads_mcp_management' in query['scope'][0]
        assert 'config_id' not in query
    assert 'client_secret' not in query


def test_ads_login_configuration_replaces_scope_on_the_consent_dialog(module, memory, monkeypatch):
    import urllib.parse
    module.POLICY['connections']['meta-ads']['loginConfigId'] = 'test-login-config-123'
    monkeypatch.setattr(module, 'http', lambda *a, **kw: pytest.fail('must not register a dynamic Ads client'))
    value = module.oauth_begin('owner', 'meta-ads')
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value['authorizationUrl']).query)
    assert query['config_id'] == ['test-login-config-123']
    assert 'scope' not in query
    assert query['client_id'] == ['2238810740192680']
    assert query['redirect_uri'] == [module.CALLBACK]
    assert query['code_challenge_method'] == ['S256']
    assert query['resource'] == ['https://mcp.facebook.com/ads']
    assert query['state'] and query['code_challenge']


def test_ads_rejects_token_from_a_different_oauth_client(module, memory):
    memory.rows['connection:owner:meta-ads'] = {'expiresAt': int(time.time()) + 3600,
        'cipher': json.dumps({'access_token': 'fixture', '_oauth_client_id': 'other-app'}).encode()}
    with pytest.raises(module.Refusal, match='configured Ads MCP app'):
        module.token('owner', 'meta-ads')


def test_ads_verification_discovers_tools_without_claiming_account_access(module, memory, monkeypatch):
    monkeypatch.setattr(module, 'token', lambda *a: 'fixture-access')
    monkeypatch.setattr(module, 'secret_json', lambda name: {'app_secret': 'fixture-app-secret'})
    calls = []
    def remote(url, payload, headers):
        if payload is None:
            return {'data': [{'permission': name, 'status': 'granted'} for name in ('ads_read', 'ads_mcp_management')]}, None
        calls.append((payload['method'], dict(headers)))
        if payload['method'] == 'initialize': return {'result': {'protocolVersion': '2025-06-18'}}, 'fixture-session'
        if payload['method'] == 'notifications/initialized': return {}, None
        return {'result': {'tools': [{'name': 'fixture-ad-write'}]}}, None
    monkeypatch.setattr(module, 'http', remote)
    result = module.run_tool('owner', 'connection_verify', {'provider': 'meta-ads'})
    assert result['status'] == 'authenticated'
    assert result['read']['accountReadVerified'] is False
    assert result['read']['toolExecutionEnabled'] is False
    assert [x[0] for x in calls] == ['initialize', 'notifications/initialized', 'tools/list']
    assert calls[-1][1]['Mcp-Session-Id'] == 'fixture-session'
    assert calls[-1][1]['MCP-Protocol-Version'] == '2025-06-18'


def test_ads_empty_or_failed_tool_discovery_is_not_authenticated(module, memory, monkeypatch):
    monkeypatch.setattr(module, 'token', lambda *a: 'fixture-access')
    monkeypatch.setattr(module, 'secret_json', lambda name: {'app_secret': 'fixture-app-secret'})
    def remote(url, payload, headers):
        if payload is None:
            return {'data': [{'permission': name, 'status': 'granted'} for name in ('ads_read', 'ads_mcp_management')]}, None
        if payload['method'] == 'initialize': return {'result': {'protocolVersion': '2025-11-25'}}, None
        return {'error': {'code': -32000}}, None
    monkeypatch.setattr(module, 'http', remote)
    with pytest.raises(module.Refusal, match='discovery failed'):
        module.run_tool('owner', 'connection_verify', {'provider': 'meta-ads'})


def test_ads_missing_grant_is_reported_before_mcp_connection(module, memory, monkeypatch):
    import urllib.parse
    monkeypatch.setattr(module, 'token', lambda *a: 'fixture-access')
    monkeypatch.setattr(module, 'secret_json', lambda name: {'app_secret': 'fixture-app-secret'})
    calls = []
    def remote(url, payload, headers):
        calls.append(url)
        return {'data': [{'permission': 'ads_read', 'status': 'granted'},
            {'permission': 'ads_mcp_management', 'status': 'declined'}]}, None
    monkeypatch.setattr(module, 'http', remote)
    with pytest.raises(module.Refusal, match='did not grant required Ads MCP permissions: ads_mcp_management'):
        module.run_tool('owner', 'connection_verify', {'provider': 'meta-ads'})
    assert len(calls) == 1
    parsed = urllib.parse.urlparse(calls[0])
    assert parsed.scheme + '://' + parsed.netloc + parsed.path == 'https://graph.facebook.com/v26.0/me/permissions'
    assert urllib.parse.parse_qs(parsed.query)['appsecret_proof'][0]


def test_ads_permission_read_carries_a_correct_appsecret_proof(module, memory, monkeypatch):
    import hashlib
    import hmac
    import urllib.parse
    monkeypatch.setattr(module, 'token', lambda *a: 'fixture-access')
    monkeypatch.setattr(module, 'secret_json', lambda name: {'app_secret': 'fixture-app-secret'})
    calls = []
    def remote(url, payload, headers):
        calls.append(url)
        return {'data': [{'permission': 'ads_read', 'status': 'declined'}]}, None
    monkeypatch.setattr(module, 'http', remote)
    with pytest.raises(module.Refusal, match='did not grant required'):
        module.run_tool('owner', 'connection_verify', {'provider': 'meta-ads'})
    expected = hmac.new(b'fixture-app-secret', b'fixture-access', hashlib.sha256).hexdigest()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
    assert query['appsecret_proof'] == [expected]
    # Only the HMAC travels. The app secret itself never reaches the request.
    assert 'fixture-app-secret' not in calls[0]


def test_ads_verification_fails_closed_without_the_app_secret(module, memory, monkeypatch):
    monkeypatch.setattr(module, 'token', lambda *a: 'fixture-access')
    monkeypatch.setattr(module, 'secret_json', lambda name: {})
    monkeypatch.setattr(module, 'http', lambda *a, **kw: pytest.fail('must not read Graph without a proof'))
    with pytest.raises(module.Refusal, match='app credential is unavailable'):
        module.run_tool('owner', 'connection_verify', {'provider': 'meta-ads'})


def test_vendored_appsecret_proof_matches_the_shared_helper(module):
    from lambda_utils.appsecret import build_appsecret_proof
    assert (module.appsecret_proof('fixture-access', 'fixture-app-secret')
        == build_appsecret_proof('fixture-access', 'fixture-app-secret'))
    assert module.appsecret_proof('', 'fixture-app-secret') == ''
    assert module.appsecret_proof('fixture-access', '') == ''


@pytest.mark.parametrize('status', [400, 401, 403])
def test_http_4xx_detail_is_structured_and_omits_url_and_body(module, monkeypatch, status):
    import email.message
    import io
    import urllib.error
    url = 'https://graph.facebook.com/v26.0/me/permissions?appsecret_proof=deadbeef'
    headers = email.message.Message()
    headers['WWW-Authenticate'] = 'Bearer scope="ads_read ads_mcp_management"'
    body = b'{"error":{"message":"Unsupported get request","type":"OAuthException","code":100}}'
    class Opener:
        def open(self, *a, **kw):
            raise urllib.error.HTTPError(url, status, 'Bad Request', headers, io.BytesIO(body))
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(module.Refusal) as caught:
        module.http(url, None, {'Authorization': 'Bearer fixture-access'})
    exc = caught.value
    assert exc.detail == {'status': status, 'code': 100, 'type': 'OAuthException',
        'message': 'Unsupported get request', 'scope': 'ads_read ads_mcp_management'}
    rendered = str(exc) + json.dumps(exc.detail)
    assert str(status) in rendered and '100' in rendered and 'OAuthException' in rendered
    # Neither the request URL nor its secret-derived query string may travel.
    assert 'deadbeef' not in rendered and 'appsecret_proof' not in rendered
    assert 'fixture-access' not in rendered


def test_http_drops_a_provider_message_that_echoes_a_credential(module, monkeypatch):
    import email.message
    import io
    import urllib.error
    body = b'{"error":{"message":"Invalid appsecret_proof provided","type":"OAuthException","code":100}}'
    class Opener:
        def open(self, *a, **kw):
            raise urllib.error.HTTPError('https://graph.facebook.com/v26.0/me/permissions',
                400, 'Bad Request', email.message.Message(), io.BytesIO(body))
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(module.Refusal) as caught:
        module.http('https://graph.facebook.com/v26.0/me/permissions')
    assert 'message' not in caught.value.detail
    assert caught.value.detail == {'status': 400, 'code': 100, 'type': 'OAuthException'}
    assert 'appsecret_proof' not in str(caught.value)


def test_http_5xx_stays_opaque_without_detail(module, monkeypatch):
    import email.message
    import io
    import urllib.error
    class Opener:
        def open(self, *a, **kw):
            raise urllib.error.HTTPError('https://mcp.facebook.com/ads', 500, 'Server Error',
                email.message.Message(), io.BytesIO(b'{"error":{"message":"boom","code":1}}'))
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(module.Refusal, match='^Provider unavailable$') as caught:
        module.http('https://mcp.facebook.com/ads')
    assert caught.value.detail is None


def test_registered_meta_client_is_reused_without_business_app_id(module, memory, monkeypatch):
    module.POLICY['connections']['meta-social']['registrationEndpoint'] = 'https://mcp.facebook.com/.well-known/register/devtools'
    calls = []
    def register(url, payload, **kwargs):
        calls.append(payload)
        return {'client_id': 'registered-client', 'token_endpoint_auth_method': 'none'}, None
    monkeypatch.setattr(module, 'http', register)
    first = module.oauth_begin('owner', 'meta-social')
    second = module.oauth_begin('owner', 'meta-social')
    assert len(calls) == 1 and calls[0]['redirect_uris'] == [module.CALLBACK]
    assert 'client_id=registered-client' in first['authorizationUrl']
    assert '2238810740192680' not in second['authorizationUrl']


def test_google_callback_uses_runtime_secret_and_keeps_tokens_out_of_response(module, memory, monkeypatch):
    import urllib.parse
    config = module.POLICY['connections']['google-cloud']
    monkeypatch.setattr(module, 'secret_json', lambda name: {'client_id': config['clientId'], 'client_secret': 'fixture-confidential'})
    begin = module.oauth_begin('owner', 'google-cloud')
    query = urllib.parse.parse_qs(urllib.parse.urlparse(begin['authorizationUrl']).query)
    assert query['access_type'] == ['offline']
    assert query['scope'] == ['https://www.googleapis.com/auth/cloud-platform.read-only']
    calls = []
    def exchange(url, payload, **kwargs):
        calls.append((url, payload))
        return {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'expires_in': 3600}, None
    monkeypatch.setattr(module, 'http', exchange)
    result = module.oauth_callback({'state': query['state'][0], 'code': 'fixture-code'})
    assert calls[0][0] == 'https://oauth2.googleapis.com/token'
    assert calls[0][1]['client_secret'] == 'fixture-confidential'
    assert 'resource' not in calls[0][1]
    assert 'fixture-' not in json.dumps(result)
    assert result['status'] == 'authorized_unverified'


def test_google_rejects_wrong_runtime_client_before_token_exchange(module, memory, monkeypatch):
    monkeypatch.setattr(module, 'secret_json', lambda name: {'client_id': 'wrong', 'client_secret': 'fixture-confidential'})
    monkeypatch.setattr(module, 'http', lambda *a, **kw: pytest.fail('must not send secret to token endpoint'))
    with pytest.raises(module.Refusal, match='does not match'):
        module.exchange_parameters('owner', 'google-ads')


def test_old_business_app_token_is_not_used_for_meta_mcp(module, memory, monkeypatch):
    module.POLICY['connections']['whatsapp']['registrationEndpoint'] = 'https://mcp.facebook.com/.well-known/register/whatsapp_business_tools'
    monkeypatch.setattr(module, 'http', lambda *a, **kw: pytest.fail('must not forward an ordinary Graph token'))
    # Two independent bindings refuse an ordinary Graph token, and the clientMode one
    # comes first. A token carrying no client id at all predates the static-client
    # model, so it is rejected before the registration check is ever consulted.
    module.save_tokens('owner', 'whatsapp', {'access_token': 'fixture-graph', 'expires_in': 3600})
    with pytest.raises(module.Refusal, match='Reconnect Meta'):
        module.provider_call('owner', 'whatsapp', 'whatsapp_biz_businesses', {'action': 'list'})
    # Being bound to the configured app is necessary but not sufficient: without an
    # approved MCP client registration the token is still not an MCP credential.
    module.save_tokens('owner', 'whatsapp', {'access_token': 'fixture-graph', 'expires_in': 3600,
        '_oauth_client_id': module.POLICY['connections']['whatsapp']['clientId']})
    with pytest.raises(module.Refusal, match='Prior business-app authorization'):
        module.provider_call('owner', 'whatsapp', 'whatsapp_biz_businesses', {'action': 'list'})


def test_sdk_provider_cannot_be_called_as_arbitrary_remote_tool(module):
    with pytest.raises(module.Refusal, match='read allowlist'):
        module.safe_provider_args('google-cloud', 'run_gcloud_command', {'action': 'list'})


def test_notification_does_not_execute_tool(module, monkeypatch):
    monkeypatch.setattr(module, "run_tool", lambda *a: pytest.fail("notification must not call tool"))
    request = event({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "code_job_submit"}})
    assert module.handler(request, None)["statusCode"] == 400


def test_provider_result_redacts_nested_credentials(module):
    value = {"content": [{"type": "text", "text": json.dumps({"app_secret": "fixture-sensitive", "name": "WECARE"})}]}
    result = json.dumps(module.redact(value))
    assert "fixture-sensitive" not in result and "WECARE" in result


def test_iac_roles_cannot_mutate_providers_or_lambda():
    template = json.loads((ROOT / "amplify/infra/workspace-mcp.json").read_text())
    resources = template["Resources"]
    assert resources["StaffRoute"]["Properties"]["AuthorizationType"] == "JWT"
    assert resources["IamRoute"]["Properties"]["AuthorizationType"] == "AWS_IAM"
    assert resources["CallbackRoute"]["Properties"]["RouteKey"] == "GET /workspace/mcp/oauth/callback"
    statements = resources["Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    actions = {a for s in statements for a in s["Action"]}
    assert "lambda:UpdateFunctionCode" not in actions and "iam:PassRole" not in actions
    reads = [s for s in statements if "secretsmanager:GetSecretValue" in s["Action"]]
    secret_arns = [r for s in reads for r in ([s["Resource"]] if isinstance(s["Resource"], str) else s["Resource"])]
    assert any(r.startswith("arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/meta-system-user-token") for r in secret_arns)
    # The Graph proof needs one named secret, never a wildcard over every credential.
    assert all(r != "*" and ":secret:*" not in r for r in secret_arns)
    assert resources["Function"]["Properties"]["Environment"]["Variables"]["CODE_JOBS_ENABLED"] == "false"
    assert resources['Version']['UpdateReplacePolicy'] == 'Retain'
    assert resources['Version']['DeletionPolicy'] == 'Retain'


@pytest.mark.parametrize("path", [".github/workflows/build-test.yml", ".kiro/steering/secret-handling.md", "amplify/functions/ecommerce/checkout/handler.py", "src/components/../lib/auth.ts", "src/components/Header.tsx\"", "/etc/passwd"])
def test_patch_path_policy_denies_sensitive_paths(path):
    sys.path.insert(0, str(DIRECTORY))
    from patch_policy import validate_patch
    patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(ValueError): validate_patch(patch)


def test_patch_alternate_header_attack_denied():
    sys.path.insert(0, str(DIRECTORY))
    from patch_policy import validate_patch
    patch = "diff --git a/src/components/Header.tsx b/src/components/Header.tsx\n--- a/.kiro/steering/secret-handling.md\n+++ b/.kiro/steering/secret-handling.md\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(ValueError): validate_patch(patch)


def test_patch_existing_public_component_allowed():
    sys.path.insert(0, str(DIRECTORY))
    from patch_policy import validate_patch
    patch = "diff --git a/src/components/Header.tsx b/src/components/Header.tsx\n--- a/src/components/Header.tsx\n+++ b/src/components/Header.tsx\n@@ -1 +1 @@\n-a\n+b\n"
    assert validate_patch(patch) == ["src/components/Header.tsx"]


def test_expired_state_never_exchanges_token(module, memory, monkeypatch):
    import urllib.parse
    begin = module.oauth_begin("owner", "whatsapp")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(begin["authorizationUrl"]).query)["state"][0]
    for item in memory.rows.values(): item["expiresAt"] = 1
    monkeypatch.setattr(module, "http", lambda *a, **kw: pytest.fail("expired state must not exchange"))
    with pytest.raises(module.Refusal): module.oauth_callback({"state": state, "code": "fixture"})


def test_removed_admin_membership_refused(module, monkeypatch):
    class Cognito:
        def get_user(self, **kwargs): return {"Username": "staff", "UserAttributes": [{"Name": "sub", "Value": "staff"}]}
        def admin_list_groups_for_user(self, **kwargs): return {"Groups": [{"GroupName": "Viewer"}]}
    monkeypatch.setattr(module, "client", lambda *a: Cognito())
    request = event()
    request["headers"]["authorization"] = "Bearer fixture"
    request["requestContext"]["authorizer"] = {"jwt": {"claims": {"iss": module.ISSUER, "client_id": module.STAFF_CLIENT, "token_use": "access", "cognito:groups": "[Admin]", "sub": "staff", "exp": str(int(time.time()) + 3600)}}}
    assert module.handler(request, None)["statusCode"] == 401


def test_provider_call_initializes_and_uses_negotiated_session(module, monkeypatch):
    monkeypatch.setattr(module, "token", lambda *a: "fixture-access")
    calls = []
    def remote(url, payload=None, headers=None, **kw):
        calls.append((url, payload, dict(headers)))
        if payload["method"] == "initialize": return {"result": {"protocolVersion": "2025-06-18"}}, "fixture-session"
        if payload["method"] == "notifications/initialized": return {}, None
        return {"result": {"content": [{"type": "text", "text": '{"app_secret":"fixture-sensitive","name":"WECARE"}'}]}}, None
    monkeypatch.setattr(module, "http", remote)
    result = module.provider_call("owner", "meta-social", "devtools_app_list", {"action": "list"})
    assert [call[1]["method"] for call in calls] == ["initialize", "notifications/initialized", "tools/call"]
    assert calls[-1][2]["MCP-Protocol-Version"] == "2025-06-18"
    assert calls[-1][2]["Mcp-Session-Id"] == "fixture-session"
    assert "fixture-sensitive" not in json.dumps(result)


def test_sse_returns_without_waiting_for_eof(module, monkeypatch):
    import io
    class Response:
        headers = {"Content-Type": "text/event-stream"}
        def __init__(self): self.stream = io.BytesIO(b'data: {"jsonrpc":"2.0","id":9,"result":{"ok":true}}\n\n')
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def readline(self, size):
            line = self.stream.readline(size)
            if not line: pytest.fail("must not wait for persistent stream EOF")
            return line
    class Opener:
        def open(self, *a, **kw): return Response()
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: Opener())
    result, _ = module.http("https://mcp.facebook.com/devtools", {"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert result["result"] == {"ok": True}


def test_disabled_code_jobs_are_persisted_once_without_dispatch(module, memory, monkeypatch):
    monkeypatch.setenv("PATCH_BUCKET", "fixture-bucket")
    monkeypatch.setenv("CODE_JOBS_ENABLED", "false")
    puts = []
    class S3:
        def put_object(self, **kwargs): puts.append(kwargs)
    monkeypatch.setattr(module, "client", lambda *a: S3())
    monkeypatch.setattr(module, "http", lambda *a, **kw: pytest.fail("disabled job must not dispatch"))
    patch = "diff --git a/src/components/Header.tsx b/src/components/Header.tsx\n--- a/src/components/Header.tsx\n+++ b/src/components/Header.tsx\n@@ -1 +1 @@\n-a\n+b\n"
    args = {"expectedBase": "a" * 40, "patch": patch}
    one = module.code_submit("owner", args)
    two = module.code_submit("owner", args)
    assert one["jobId"] == two["jobId"] and two["status"] == "dispatch_pending"
    assert len(puts) == 1 and puts[0]["Key"].startswith("workspace-mcp/patches/owner/")


def test_audit_log_does_not_include_arguments(module, memory, caplog):
    request = event({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "connections_list", "arguments": {"unrecognized": "fixture-sensitive"}}})
    module.handler(request, None)
    assert "fixture-sensitive" not in caplog.text
    assert "workspace_mcp_tool" in caplog.text


def test_route_audit_only_exempts_nonce_callback():
    spec = importlib.util.spec_from_file_location("workspace_route_audit", ROOT / "scripts/audit_route_auth.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    assert "GET /workspace/mcp/oauth/callback" in audit.EXPECTED_PUBLIC_ROUTES
    assert "ANY /workspace/mcp" not in audit.EXPECTED_PUBLIC_ROUTES
    assert "POST /workspace/mcp-iam" not in audit.EXPECTED_PUBLIC_ROUTES


def test_generic_deployer_delegates_workspace_bundle():
    source = (ROOT / "scripts/deploy_all_lambdas.py").read_text()
    assert '"wecare-workspace-mcp": "scripts/build_workspace_mcp.py + scripts/deploy_workspace_mcp.py' in source


@pytest.mark.parametrize("owner,provider", [("../owner", "meta-social"), ("a" * 64, "unknown"), ("a" * 63, "whatsapp")])
def test_invalid_custody_context_is_refused(module, owner, provider):
    with pytest.raises(module.Refusal): module.custody_context(owner, provider)


def test_missing_cloud_config_has_safe_error(module, monkeypatch):
    monkeypatch.delenv("TOKEN_KEY", raising=False)
    with pytest.raises(module.Refusal, match="configuration is incomplete"):
        module.configured("TOKEN_KEY")


def test_refresh_rereads_after_acquiring_lease(module, memory, monkeypatch):
    owner = "a" * 64
    key = "connection:" + owner + ":whatsapp"
    # The stored credential is bound to the configured static client, as a real one
    # authorized through oauth_callback is, so the clientMode check lets it through
    # and the refresh-lease behaviour under test is actually reached.
    client = module.POLICY["connections"]["whatsapp"]["clientId"]
    memory.rows[key] = {"expiresAt": 1, "cipher": json.dumps({"access_token": "fixture-old", "refresh_token": "fixture-refresh", "_oauth_client_id": client}).encode()}
    updates = []
    def update(**kwargs):
        updates.append(kwargs)
        if kwargs["UpdateExpression"].startswith("SET refreshLockUntil"):
            # A preceding refresher completed between this reader's first read
            # and successful acquisition of its own lease.
            memory.rows[key] = {"expiresAt": int(time.time()) + 3600,
                "cipher": json.dumps({"access_token": "fixture-new", "refresh_token": "fixture-refresh-new", "_oauth_client_id": client}).encode()}
    memory.update_item = update
    monkeypatch.setattr(module, "http", lambda *a, **kw: pytest.fail("already refreshed credential must not be refreshed again"))
    assert module.token(owner, "whatsapp") == "fixture-new"
    assert updates[-1]["ConditionExpression"] == "refreshLease = :lease"
    assert updates[0]["ExpressionAttributeValues"][":lease"] == updates[-1]["ExpressionAttributeValues"][":lease"]


def test_empty_patch_chunk_is_rejected():
    sys.path.insert(0, str(DIRECTORY))
    from patch_policy import validate_patch
    with pytest.raises(ValueError, match="Empty patch chunk"):
        validate_patch("diff --git ")
