"""Provider MCP (wecare-sinch-provider-mcp / wecare-plivo-provider-mcp): the token check
refuses bad claims before any Cognito call, and only read tools exist. Fake Cognito,
Secrets Manager and HTTP; no network or AWS calls."""
import base64
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "provider_mcp_under_test", ROOT / "amplify/functions/ai/provider-mcp/index.py")
MCP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)

API_BASE = "https://api.example.test"
CLIENT = "chat-client-id"
DROP = object()


def token(**overrides):
    claims = {"iss": MCP.ISSUER, "client_id": CLIENT, "aud": API_BASE + "/mcp",
              "token_use": "access", "exp": int(time.time()) + 300,
              "scope": "openid " + MCP.SCOPE, "sub": "staff-sub"}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not DROP}

    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return enc({"alg": "RS256"}) + "." + enc(claims) + ".signature"


@pytest.fixture
def cognito(monkeypatch):
    """Records every boto3 client created; Cognito answers as an Admin unless told otherwise."""
    state = {"clients": [], "groups": ["Admin"], "sub": "staff-sub"}

    def client(service, region_name=None):
        state["clients"].append(service)
        return SimpleNamespace(
            get_user=lambda AccessToken: {"Username": "staff-user", "UserAttributes": [
                {"Name": "sub", "Value": state["sub"]}]},
            admin_list_groups_for_user=lambda **kw: {
                "Groups": [{"GroupName": g} for g in state["groups"]]})

    monkeypatch.setattr(MCP, "boto3", SimpleNamespace(client=client))
    monkeypatch.setenv("API_BASE", API_BASE)
    monkeypatch.setenv("CHAT_CLIENT_ID", CLIENT)
    monkeypatch.setenv("PROVIDER", "plivo")
    monkeypatch.setenv("SECRET_ID", "test/provider")
    return state


BAD_TOKENS = {
    "wrong issuer": token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_otherpool"),
    "customer pool issuer": token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"),
    "wrong client_id": token(client_id="another-client"),
    "missing client_id": token(client_id=DROP),
    "wrong aud": token(aud="https://evil.example/mcp"),
    "missing aud": token(aud=DROP),
    "missing scope": token(scope="openid email"),
    "empty scope": token(scope=""),
    "expired": token(exp=int(time.time()) - 1),
    "exp as float": token(exp=time.time() + 300),
    "exp as string": token(exp=str(int(time.time()) + 300)),
    "id token": token(token_use="id"),
    "no subject": token(sub=DROP),
    "two segments": "header.payload",
}


@pytest.mark.parametrize("case", sorted(BAD_TOKENS))
def test_bad_claims_are_refused_before_cognito(cognito, case):
    with pytest.raises(ValueError):
        MCP.auth(BAD_TOKENS[case])
    assert cognito["clients"] == []


def test_handler_answers_401_for_a_bad_token_without_calling_cognito(cognito):
    event = {"headers": {"Authorization": "Bearer " + BAD_TOKENS["wrong aud"]},
             "requestContext": {"http": {"method": "POST"}}, "body": "{}"}
    response = MCP.handler(event, None)
    assert response["statusCode"] == 401 and "WWW-Authenticate" in response["headers"]
    assert cognito["clients"] == []
    assert MCP.handler({"headers": {}}, None)["statusCode"] == 401


def test_valid_claims_still_need_matching_subject_and_admin(cognito):
    assert len(MCP.auth(token())) == 64
    assert cognito["clients"] == ["cognito-idp"]
    cognito["groups"] = ["Operator"]
    with pytest.raises(PermissionError):
        MCP.auth(token())
    cognito["groups"], cognito["sub"] = ["Admin"], "someone-else"
    with pytest.raises(ValueError):
        MCP.auth(token())


@pytest.mark.parametrize("provider,names", [
    ("plivo", {"connection_verify", "get_cdr", "get_mdr"}),
    ("sinch", {"connection_verify", "get_application"}),
])
def test_only_read_tools_are_listed(cognito, monkeypatch, provider, names):
    monkeypatch.setenv("PROVIDER", provider)
    assert {t["name"] for t in MCP.tools()} == names


@pytest.mark.parametrize("name", ["send_sms", "make_call", "send_message", "delete_cdr"])
def test_unlisted_tools_are_refused_before_any_secret_read(cognito, monkeypatch, name):
    monkeypatch.setattr(MCP, "secret", lambda: pytest.fail("secret read for an unknown tool"))
    with pytest.raises(ValueError):
        MCP.run(name, {})


class Reply:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit):
        return self.data[:limit]


def test_provider_calls_only_read(cognito, monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append((request.get_method(), request.full_url))
        if "openid-connect/token" in request.full_url:
            return Reply({"access_token": "provider-token"})
        if "convapi" in request.full_url:
            return Reply({"id": "app-1", "display_name": "WECARE"})
        if request.full_url.endswith("/Account/MA123/"):
            return Reply({"auth_id": "MA123"})
        return Reply({"call_uuid": "c-1", "message_uuid": "m-1"})

    monkeypatch.setattr(MCP.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(MCP, "secret", lambda: {
        "auth_id": "MA123", "auth_token": "t", "username": "u", "password": "p",
        "project_id": "proj-1", "app_id": "app-1"})
    for name, args in (("connection_verify", {}), ("get_cdr", {"call_uuid": "call-uuid-0001"}),
                       ("get_mdr", {"message_uuid": "message-uuid-01"})):
        MCP.run(name, args)
    monkeypatch.setenv("PROVIDER", "sinch")
    for name in ("connection_verify", "get_application"):
        MCP.run(name, {})
    provider_calls = [(m, u) for m, u in requests if "openid-connect/token" not in u]
    assert provider_calls and all(method == "GET" for method, _ in provider_calls)
    # The only POST is the Sinch OAuth token exchange.
    assert {u for m, u in requests if m == "POST"} == {
        "https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token"}
