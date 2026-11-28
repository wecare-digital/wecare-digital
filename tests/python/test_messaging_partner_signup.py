"""MSG-1: the public Embedded Signup route proves the WABA before writing anything.

The handler is loaded with fake AWS credentials and every Meta, Secrets Manager,
DynamoDB and Cognito call is replaced by an in-memory fake, so nothing leaves the
process.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/messaging/partner-onboarding/handler.py")
APP_ID = "2238810740192680"
WABA = "123456789012345"
PHONE = "987654321098765"


@pytest.fixture(scope="module")
def module():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    spec = importlib.util.spec_from_file_location("partner_onboarding_under_test", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


class ResourceExists(Exception):
    pass


class FakeSecrets:
    class exceptions:
        ResourceExistsException = ResourceExists

    def __init__(self, exists=False):
        self.exists = exists
        self.created = []
        self.put = []

    def create_secret(self, Name, SecretString):
        if self.exists:
            raise ResourceExists()
        self.created.append(Name)

    def put_secret_value(self, **kwargs):
        self.put.append(kwargs)


class FakeTable:
    def __init__(self, record=None):
        self.item = ({"id": f"partner_tenant_{WABA}", "configValue": json.dumps(record)}
                     if record is not None else None)
        self.puts = []

    def get_item(self, Key, ConsistentRead=False):
        return {"Item": self.item} if self.item else {}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression == "attribute_not_exists(id)" and self.item is not None:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.puts.append((Item, ConditionExpression))
        self.item = Item


class FakeDdb:
    def __init__(self, table):
        self.table = table

    def Table(self, _name):
        return self.table


class FakeCognito:
    def __init__(self, groups=(), waba=""):
        self.groups = list(groups)
        self.waba = waba
        self.calls = []

    def admin_get_user(self, UserPoolId, Username):
        self.calls.append(("get", Username))
        return {"UserAttributes": [{"Name": "custom:partner_waba_id", "Value": self.waba}]}

    def admin_list_groups_for_user(self, UserPoolId, Username):
        self.calls.append(("groups", Username))
        return {"Groups": [{"GroupName": g} for g in self.groups]}

    def admin_disable_user(self, UserPoolId, Username):
        self.calls.append(("disable", Username))

    def __getattr__(self, name):  # any other Cognito write is a test failure
        raise AssertionError(f"unexpected Cognito call {name}")


def debug_data(targets=(WABA,), app_id=APP_ID, valid=True):
    return {"app_id": app_id, "is_valid": valid, "granular_scopes": [
        {"scope": "whatsapp_business_management", "target_ids": list(targets)},
        {"scope": "whatsapp_business_messaging", "target_ids": list(targets)},
    ]}


@pytest.fixture
def wire(module, monkeypatch):
    def setup(debug=None, phones=(PHONE,), record=None, secret_exists=False, cognito=None):
        calls = []

        def graph(method, path, token="", params=None, payload=None):
            calls.append((method, path))
            if path == "debug_token":
                assert token == f"{APP_ID}|app-secret"
                return {"data": debug if debug is not None else debug_data()}
            if path.endswith("/phone_numbers"):
                return {"data": [{"id": p} for p in phones]}
            if path.endswith(("/subscribed_apps", "/register")):
                return {"success": True}
            return {}

        state = {
            "graph": calls,
            "secrets": FakeSecrets(exists=secret_exists),
            "table": FakeTable(record),
            "cognito": cognito or FakeCognito(),
            "audit": [],
        }
        monkeypatch.setattr(module, "_graph", graph)
        monkeypatch.setattr(module, "_exchange_code",
                            lambda code: {"access_token": "partner-token", "expires_in": 3600})
        monkeypatch.setattr(module, "_app_secret", lambda: "app-secret")
        monkeypatch.setattr(module, "_secrets", state["secrets"])
        monkeypatch.setattr(module, "_ddb", FakeDdb(state["table"]))
        monkeypatch.setattr(module, "_cognito", state["cognito"])
        monkeypatch.setattr(module, "record_audit", lambda **kw: state["audit"].append(kw))
        return state
    return setup


def body(**extra):
    return {"code": "oauth-code", "wabaId": WABA, "phoneNumberId": PHONE, **extra}


def wrote_nothing(state):
    assert state["secrets"].created == [] and state["secrets"].put == []
    assert state["table"].puts == []
    assert not any(p.endswith(("/subscribed_apps", "/register")) for _, p in state["graph"])


@pytest.mark.parametrize("debug", [
    debug_data(targets=("555",)),            # token covers another WABA
    debug_data(app_id="999"),                # token minted for another app
    debug_data(valid=False),
    {"app_id": APP_ID, "is_valid": True, "granular_scopes": [
        {"scope": "whatsapp_business_management"}]},  # no target list: not provable
])
def test_unproven_waba_is_refused_before_any_write(module, wire, debug):
    state = wire(debug=debug)
    result = module._do_onboard(body(), "", "req")
    assert result["statusCode"] == 403
    wrote_nothing(state)


def test_phone_outside_the_waba_is_refused(module, wire):
    state = wire(phones=("111",))
    result = module._do_onboard(body(), "", "req")
    assert result["statusCode"] == 403
    wrote_nothing(state)


def test_missing_or_malformed_waba_is_refused_without_code_exchange(module, wire):
    state = wire()
    assert module._do_onboard(body(wabaId=""), "", "r")["statusCode"] == 400
    assert module._do_onboard(body(wabaId="me/accounts"), "", "r")["statusCode"] == 400
    assert state["graph"] == []


def test_verified_signup_ignores_customer_email_and_writes_create_only(module, wire):
    state = wire()
    result = module._do_onboard(body(customerEmail="owner@wecare.digital"), "", "req")
    assert result["statusCode"] == 200
    assert state["secrets"].created == [f"wecare/partners/{WABA}"]
    assert state["secrets"].put == []
    (item, condition), = state["table"].puts
    assert condition == "attribute_not_exists(id)"
    record = json.loads(item["configValue"])
    assert "customerEmail" not in record and record["phoneNumberId"] == PHONE
    assert state["cognito"].calls == []
    assert state["audit"][0]["actor"] == "self-serve"


def test_existing_secret_is_never_overwritten(module, wire):
    state = wire(secret_exists=True)
    result = module._do_onboard(body(), "", "req")
    assert result["statusCode"] == 409
    assert state["secrets"].put == []
    assert state["table"].puts == []


def test_tenant_with_a_different_setup_is_refused(module, wire):
    state = wire(record={"wabaId": WABA, "phoneNumberId": "222", "status": "CONNECTED"})
    result = module._do_onboard(body(), "", "req")
    assert result["statusCode"] == 409
    wrote_nothing(state)


def test_disconnected_tenant_is_not_reconnected_from_the_public_route(module, wire):
    state = wire(record={"wabaId": WABA, "phoneNumberId": PHONE, "status": "DISCONNECTED"})
    assert module._do_onboard(body(), "", "req")["statusCode"] == 409
    wrote_nothing(state)


def test_same_setup_answers_already_connected_without_writing(module, wire):
    state = wire(record={"wabaId": WABA, "phoneNumberId": PHONE, "status": "CONNECTED",
                         "connectedAt": "2026-11-01T00:00:00+00:00"})
    result = module._do_onboard(body(), "", "req")
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["alreadyConnected"] is True
    wrote_nothing(state)


def _disconnect(module, state):
    event = {"_auth": {"username": "admin"}}
    return module._do_disconnect(event, WABA, "")


def test_disconnect_never_disables_a_staff_login(module, wire, monkeypatch):
    cognito = FakeCognito(groups=("Admin",), waba=WABA)
    state = wire(record={"wabaId": WABA, "customerEmail": "admin@wecare.digital"}, cognito=cognito)
    monkeypatch.setattr(module.billing, "get_wallet", lambda waba: None)
    result = _disconnect(module, state)
    assert result["statusCode"] == 200
    assert ("disable", "admin@wecare.digital") not in cognito.calls
    assert json.loads(result["body"])["cleanup"]["cognitoDisabled"] is False


@pytest.mark.parametrize("groups,waba", [(("Partner", "Operator"), WABA), (("Partner",), "555")])
def test_disconnect_skips_mixed_role_or_other_waba_partner(module, wire, monkeypatch, groups, waba):
    cognito = FakeCognito(groups=groups, waba=waba)
    state = wire(record={"wabaId": WABA, "customerEmail": "p@example.com"}, cognito=cognito)
    monkeypatch.setattr(module.billing, "get_wallet", lambda waba: None)
    _disconnect(module, state)
    assert ("disable", "p@example.com") not in cognito.calls


def test_disconnect_disables_the_partner_only_login_of_this_waba(module, wire, monkeypatch):
    cognito = FakeCognito(groups=("Partner",), waba=WABA)
    state = wire(record={"wabaId": WABA, "customerEmail": "p@example.com"}, cognito=cognito)
    monkeypatch.setattr(module.billing, "get_wallet", lambda waba: None)
    result = _disconnect(module, state)
    assert ("disable", "p@example.com") in cognito.calls
    assert json.loads(result["body"])["cleanup"]["cognitoDisabled"] is True
