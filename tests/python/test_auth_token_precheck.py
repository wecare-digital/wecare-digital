"""PAY-5: customer_auth and the staff middleware screen bearer tokens locally before GetUser.

The screen reads claims without a signature check and only ever refuses; GetUser stays the
real check, so a plausible token still reaches it.
"""
import base64
import json
import time

import pytest

from lambda_utils import customer_auth, middleware

CUSTOMER_CLIENT = "4avmt9n4gpmkvkdk88qbtit33o"


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def jwt(**claims):
    """An UNSIGNED token with synthetic claims."""
    return f"{_b64({'alg': 'RS256', 'kid': 'synthetic'})}.{_b64(claims)}.c2lnbmF0dXJl"


def customer_token(**overrides):
    claims = {"iss": customer_auth.CUSTOMER_POOL_ISSUER, "client_id": CUSTOMER_CLIENT,
              "token_use": "access", "exp": int(time.time()) + 600,
              "sub": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"}
    claims.update(overrides)
    return jwt(**claims)


def staff_token(**overrides):
    claims = {"iss": middleware.staff_pool_issuer(), "client_id": middleware.STAFF_APP_CLIENT_ID,
              "token_use": "access", "exp": int(time.time()) + 600}
    claims.update(overrides)
    return jwt(**claims)


class CountingCognito:
    def __init__(self):
        self.calls = []

    def get_user(self, AccessToken):
        self.calls.append(AccessToken)
        return {"Username": "+919000000001", "UserAttributes": [
            {"Name": "sub", "Value": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"},
            {"Name": "phone_number", "Value": "+919000000001"}]}


@pytest.fixture
def customer_cognito(monkeypatch):
    fake = CountingCognito()
    monkeypatch.setattr(customer_auth, "_client", lambda: fake)
    return fake


@pytest.mark.parametrize("token", [
    "junk", "a.b", "a.b.c.d", "abc.def.ghi", "..", f"{_b64({})}.{_b64({})}.",
    jwt(),
    customer_token(exp=int(time.time()) - 1),
    customer_token(exp="9999999999"),
    customer_token(exp=True),
    customer_token(token_use="id"),
    customer_token(client_id="another-client"),
    customer_token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_cSx0RHCIR"),
    staff_token(),
])
def test_customer_auth_refuses_implausible_tokens_without_get_user(customer_cognito, token):
    with pytest.raises(customer_auth.CustomerNotAuthenticated):
        customer_auth.authenticate({"headers": {"authorization": f"Bearer {token}"}})
    assert customer_cognito.calls == []


def test_customer_auth_still_proves_plausible_tokens_with_get_user(customer_cognito):
    token = customer_token()
    identity = customer_auth.authenticate({"headers": {"authorization": f"Bearer {token}"}})
    assert customer_cognito.calls == [token]
    assert identity.customer_id == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


class StaffCognito:
    class exceptions:
        class NotAuthorizedException(Exception):
            pass

    def __init__(self):
        self.calls = []

    def get_user(self, AccessToken):
        self.calls.append("get_user")
        return {"Username": "staff1", "UserAttributes": []}

    def admin_list_groups_for_user(self, **kwargs):
        self.calls.append("groups")
        return {"Groups": [{"GroupName": "Viewer"}]}


def _staff_event(token):
    return {"headers": {"authorization": f"Bearer {token}"},
            "requestContext": {"apiId": "api", "http": {"method": "GET", "sourceIp": "1.2.3.4",
                                                        "path": "/x"}}}


@pytest.mark.parametrize("token", [
    "junk", "a.b.c", staff_token(exp=int(time.time()) - 5), staff_token(token_use="id"),
    staff_token(client_id="another-client"), customer_token(),
])
def test_staff_middleware_refuses_implausible_tokens_without_get_user(monkeypatch, token):
    fake = StaffCognito()
    monkeypatch.setattr(middleware, "cognito", fake)
    denied = middleware.require_auth(_staff_event(token), required_role="Viewer")
    assert denied["statusCode"] == 401
    assert json.loads(denied["body"]) == {"error": "Invalid or expired token"}
    assert fake.calls == []


def test_staff_middleware_passes_plausible_tokens_to_get_user(monkeypatch):
    fake = StaffCognito()
    monkeypatch.setattr(middleware, "cognito", fake)
    event = _staff_event(staff_token())
    assert middleware.require_auth(event, required_role="Viewer") is None
    assert fake.calls == ["get_user", "groups"] and event["_auth"]["role"] == "Viewer"
