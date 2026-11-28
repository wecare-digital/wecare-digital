"""PAY-5: customer-session reads the app client settings once per cache window and refuses
malformed bodies and cookies before any Cognito call."""
import base64
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from lambda_utils import customer_auth, customer_session as sessions

HANDLER = Path(__file__).resolve().parents[2] / "amplify/functions/ecommerce/customer-session/handler.py"
ORIGIN = "https://wecare.digital"
SUB = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def customer_token():
    """An UNSIGNED customer access token with synthetic claims."""
    claims = {"iss": customer_auth.CUSTOMER_POOL_ISSUER, "client_id": "4avmt9n4gpmkvkdk88qbtit33o",
              "token_use": "access", "exp": int(time.time()) + 600, "sub": SUB}
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.c2lnbmF0dXJl"


class SessionCognito:
    def __init__(self):
        self.calls = []

    def describe_user_pool_client(self, **kwargs):
        self.calls.append("describe")
        return {"UserPoolClient": {}}

    def initiate_auth(self, **kwargs):
        self.calls.append("initiate_auth")
        return {"AuthenticationResult": {"AccessToken": customer_token(), "ExpiresIn": 3600}}

    def get_user(self, AccessToken):
        self.calls.append("get_user")
        return {"Username": "+919000000001", "UserAttributes": [{"Name": "sub", "Value": SUB}]}


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def put_session(self, row):
        self.rows[row["sidHash"]] = dict(row)

    def get_session(self, key):
        return dict(self.rows[key]) if key in self.rows else None

    def touch_session(self, key, **kwargs):
        pass

    def revoke_session(self, key, **kwargs):
        self.rows[key]["revokedAt"] = 1

    def claim_refresh(self, key, **kwargs):
        return True

    def record_refresh(self, key, **kwargs):
        pass

    def release_refresh(self, key):
        pass


class FakeKms:
    def encrypt(self, **kwargs):
        return {"CiphertextBlob": b"sealed:" + kwargs["Plaintext"]}

    def decrypt(self, **kwargs):
        return {"Plaintext": kwargs["CiphertextBlob"][len(b"sealed:"):]}


@pytest.fixture
def session(monkeypatch):
    spec = importlib.util.spec_from_file_location("customer_session_quota", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("CUSTOMER_SESSIONS_TABLE", "sessions")
    monkeypatch.setenv("CUSTOMER_SESSION_KMS_KEY_ID", "key")
    cognito, store = SessionCognito(), MemoryStore()
    clock = {"now": 1000.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(module, "SessionStore", lambda table: store)
    monkeypatch.setattr(module, "boto3", SimpleNamespace(
        resource=lambda name: SimpleNamespace(Table=lambda table_name: object()),
        client=lambda name: {"kms": FakeKms(), "cognito-idp": cognito}[name]))
    monkeypatch.setattr(customer_auth, "_client", lambda: cognito)
    module.cognito, module.store, module.clock = cognito, store, clock
    return module


def _post(module, body, *, token=None, cookie=None, csrf=None):
    headers = {"origin": ORIGIN}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if csrf:
        headers["x-customer-csrf"] = csrf
    event = {"headers": headers, "body": body if isinstance(body, str) else json.dumps(body)}
    if cookie:
        event["cookies"] = [f"{sessions.COOKIE_NAME}={cookie}"]
    return module.handler(event, None)


@pytest.mark.parametrize("body,kwargs,status", [
    ("not json", {}, 400),
    ([1, 2], {}, 400),
    ({"action": "unknown"}, {}, 400),
    ({"action": "refresh"}, {}, 401),
    ({"action": "logout"}, {"cookie": "short"}, 401),
    ({"action": "refresh"}, {"cookie": "x" * 42 + "!"}, 401),
    ({"action": "exchange", "refreshToken": "r"}, {"token": "junk"}, 401),
    ({"action": "exchange"}, {"token": customer_token()}, 401),
    ({"action": "exchange", "refreshToken": 42}, {"token": customer_token()}, 401),
    ({"action": "exchange", "refreshToken": "bad token\n"}, {"token": customer_token()}, 401),
    ({"action": "exchange", "refreshToken": "a" * 4097}, {"token": customer_token()}, 401),
])
def test_malformed_requests_make_no_cognito_call(session, body, kwargs, status):
    reply = _post(session, body, **kwargs)
    assert reply["statusCode"] == status
    assert session.cognito.calls == []
    assert reply["headers"]["Cache-Control"] == "no-store"


def test_unknown_cookie_is_refused_by_the_store_without_cognito(session):
    reply = _post(session, {"action": "refresh"}, cookie=sessions.new_opaque_id(), csrf="x")
    assert reply["statusCode"] == 401 and session.cognito.calls == []


def test_session_ids_have_one_shape():
    assert sessions.is_session_id(sessions.new_opaque_id())
    for value in ("", None, 42, "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "/"):
        assert not sessions.is_session_id(value)


def test_client_settings_are_read_once_per_cache_window(session):
    for _ in range(3):
        reply = _post(session, {"action": "exchange", "refreshToken": "refresh.token.value"},
                      token=customer_token())
        assert reply["statusCode"] == 200
    assert session.cognito.calls.count("describe") == 1
    session.clock["now"] += session.ROTATION_CACHE_SECONDS + 1
    opaque, view = sessions.create_session(session.store, customer_id=SUB,
                                           refresh_ref=base64.b64encode(b"sealed:r").decode())
    reply = _post(session, {"action": "refresh"}, cookie=opaque, csrf=view.csrf_token)
    assert reply["statusCode"] == 200
    assert session.cognito.calls.count("describe") == 2


def test_a_failed_client_read_answers_503_and_is_not_cached(session, monkeypatch):
    def unavailable(**kwargs):
        session.cognito.calls.append("describe")
        raise RuntimeError("TooManyRequestsException")

    monkeypatch.setattr(session.cognito, "describe_user_pool_client", unavailable)
    body = {"action": "exchange", "refreshToken": "refresh.token.value"}
    assert _post(session, body, token=customer_token())["statusCode"] == 503
    assert _post(session, body, token=customer_token())["statusCode"] == 503
    assert session.cognito.calls.count("describe") == 2


def test_logout_needs_no_client_settings(session):
    opaque, view = sessions.create_session(session.store, customer_id=SUB,
                                           refresh_ref=base64.b64encode(b"sealed:r").decode())
    session.cognito.revoke_token = lambda **kwargs: session.cognito.calls.append("revoke")
    reply = _post(session, {"action": "logout"}, cookie=opaque, csrf=view.csrf_token)
    assert reply["statusCode"] == 200 and session.cognito.calls == ["revoke"]
