"""OPS-4: bulk job routes are Admin-only, attribute jobs to the token, accept approved
WhatsApp templates only, and drop opted-out recipients using the consent ledger."""
import importlib.util
import itertools
import json
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from lambda_utils.identity import consent

ROOT = Path(__file__).resolve().parents[2]
CREATE = ROOT / "amplify/functions/operations/bulk-job-create/handler.py"
CONTROL = ROOT / "amplify/functions/operations/bulk-job-control/handler.py"
SENDER = "phone-number-id-waba1-direct-1016149501586345"
WABA1 = "2094615664435155"
_names = itertools.count()


def _load(path, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("BULK_QUEUE_URL", raising=False)
    spec = importlib.util.spec_from_file_location(f"bulk_{next(_names)}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(state, purpose, at):
    return consent.build_record(channel="WHATSAPP", state=state, source="CUSTOMER_REQUEST",
                                at=at, purpose=purpose)


class Table:
    def __init__(self, rows=None):
        self.rows = {r["id"]: r for r in (rows or [])}
        self.puts, self.updates = [], []

    def get_item(self, Key, **kwargs):
        row = self.rows.get(Key["id"])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item):
        self.puts.append(Item)

    def update_item(self, **kwargs):
        self.updates.append(kwargs)

    def scan(self, **kwargs):
        return {"Items": []}

    @contextmanager
    def batch_writer(self):
        yield self


class Dynamo:
    def __init__(self, contacts):
        self.tables = {"jobs": Table(), "recipients": Table(), "contacts": Table(contacts)}

    def Table(self, name):
        for key in ("Jobs", "Recipients", "Contacts"):
            if key in name:
                return self.tables[key.lower()]
        raise AssertionError(name)


class Meta:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, endpoint, params=None, token_context=None):
        self.calls.append((endpoint, params, token_context))
        return self.result


def approved(category="MARKETING", status="APPROVED", language="en", name="promo"):
    return {"data": [{"name": name, "status": status, "category": category, "language": language}]}


NOW = int(time.time())
CONTACTS = [
    {"id": "c-in", "phone": "+911", "consentLedger": [record("OPTED_IN", "MARKETING", NOW - 50)]},
    {"id": "c-out", "phone": "+912", "consentLedger": [
        record("OPTED_IN", "MARKETING", NOW - 90), record("OPTED_OUT", "MARKETING", NOW - 10)]},
    {"id": "c-none", "phone": "+913"},
    {"id": "c-alias", "mergeState": "merged", "mergedIntoContactId": "c-out"},
    {"id": "c-tx", "phone": "+914", "consentLedger": [
        record("OPTED_OUT", "MARKETING", NOW - 90), record("OPTED_IN", "TRANSACTIONAL", NOW - 10)]},
]


@pytest.fixture
def create(monkeypatch):
    module = _load(CREATE, monkeypatch)
    module.dynamodb = Dynamo(CONTACTS)
    module._meta_client = Meta(approved())
    return module


def call(module, body, auth=None):
    return module._create_job(body, "req", module._actor({"_auth": auth or {"username": "admin-1"}}))


def body_of(response):
    return json.loads(response["body"])


def test_created_by_comes_from_the_token(create):
    response = call(create, {"templateName": "promo", "createdBy": "someone-else",
                             "recipients": [{"contactId": "c-in"}]})
    assert response["statusCode"] == 201
    job = create.dynamodb.tables["jobs"].puts[0]
    assert job["createdBy"] == "admin-1"
    assert job["templateCategory"] == "MARKETING" and job["content"] == ""


def test_actor_falls_back_to_sub_then_internal(create):
    assert create._actor({"_auth": {"attributes": {"sub": "sub-1"}}}) == "sub-1"
    assert create._actor({}) == "internal"


@pytest.mark.parametrize("body", [
    {"content": "hello", "recipients": [{"contactId": "c-in"}]},
    {"content": "hello", "templateName": "promo", "recipients": [{"contactId": "c-in"}]},
    {"channel": "SMS", "content": "hello", "recipients": [{"contactId": "c-in"}]},
    {"channel": "EMAIL", "templateName": "promo", "recipients": [{"contactId": "c-in"}]},
    {"templateName": "promo", "recipients": "c-in"},
])
def test_free_text_and_other_channels_are_refused(create, body):
    assert call(create, body)["statusCode"] == 400
    assert create.dynamodb.tables["jobs"].puts == []
    assert create._meta_client.calls == []


@pytest.mark.parametrize("result", [
    approved(status="PENDING"), approved(status="REJECTED"), approved(status="PAUSED"),
    approved(language="en_US"), approved(name="promo_v2"), {"data": []},
])
def test_only_an_approved_template_is_accepted(create, result):
    create._meta_client = Meta(result)
    response = call(create, {"templateName": "promo", "recipients": [{"contactId": "c-in"}]})
    assert response["statusCode"] == 400 and "APPROVED" in body_of(response)["error"]
    assert create.dynamodb.tables["jobs"].puts == []


class BrokenMeta:
    def get(self, *args, **kwargs):
        raise RuntimeError("secret unreadable")


@pytest.mark.parametrize("client", [
    Meta({"error": {"message": "down"}}), Meta({}), Meta(None), BrokenMeta()])
def test_unreadable_template_list_fails_closed(create, client):
    create._meta_client = client
    response = call(create, {"templateName": "promo", "recipients": [{"contactId": "c-in"}]})
    assert response["statusCode"] == 503
    assert create.dynamodb.tables["jobs"].puts == []


def test_template_is_read_from_the_sender_waba(create):
    call(create, {"templateName": "promo", "recipients": [{"contactId": "c-in"}]})
    endpoint, params, token = create._meta_client.calls[0]
    assert endpoint == f"{WABA1}/message_templates" and token == {"waba_id": WABA1}
    assert params["name"] == "promo"


def test_unknown_sender_is_refused(create):
    response = call(create, {"templateName": "promo", "phoneNumberId": "phone-number-id-unknown",
                             "recipients": [{"contactId": "c-in"}]})
    assert response["statusCode"] == 400
    assert create._meta_client.calls == []


def test_opted_out_and_unknown_recipients_are_dropped(create):
    response = call(create, {"templateName": "promo", "recipients": [
        {"contactId": "c-in"}, {"contactId": "c-out"}, {"contactId": "c-none"},
        {"contactId": "c-alias"}, {"contactId": "missing"}, {"phone": "+915"}, "junk",
    ]})
    body = body_of(response)
    assert response["statusCode"] == 201
    assert body["totalRecipients"] == 2
    assert body["droppedOptedOut"] == 2 and body["droppedUnknownContacts"] == 3
    stored = [r["contactId"] for r in create.dynamodb.tables["recipients"].puts]
    assert stored == ["c-in", "c-none"]


def test_utility_template_uses_the_transactional_ledger(create):
    create._meta_client = Meta(approved(category="UTILITY"))
    response = call(create, {"templateName": "promo", "recipients": [
        {"contactId": "c-tx"}, {"contactId": "c-out"}]})
    assert response["statusCode"] == 201
    assert [r["contactId"] for r in create.dynamodb.tables["recipients"].puts] == ["c-tx"]


def test_all_recipients_dropped_creates_nothing(create):
    response = call(create, {"templateName": "promo", "recipients": [{"contactId": "c-out"}]})
    assert response["statusCode"] == 400 and body_of(response)["droppedOptedOut"] == 1
    assert create.dynamodb.tables["jobs"].puts == []


def _real_auth_event(monkeypatch, groups, method="POST", body=None):
    """Drive the real require_auth with a fake Cognito."""
    from lambda_utils import middleware

    class FakeCognito:
        class exceptions:
            class NotAuthorizedException(Exception):
                pass

        def get_user(self, AccessToken):
            return {"Username": "staff-1", "UserAttributes": []}

        def admin_list_groups_for_user(self, **kwargs):
            return {"Groups": [{"GroupName": g} for g in groups]}

        def admin_get_user(self, **kwargs):
            return {"UserMFASettingList": ["SMS_MFA"]}

    monkeypatch.setattr(middleware, "cognito", FakeCognito())
    monkeypatch.setattr(middleware, "_unverified_issuer", lambda t: middleware.staff_pool_issuer())
    monkeypatch.setattr(middleware, "_unverified_clients", lambda t: {middleware.STAFF_APP_CLIENT_ID})
    monkeypatch.setattr(middleware, "_plausible_access_token", lambda t: True)
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    return {
        "headers": {"authorization": "Bearer t"},
        "requestContext": {"apiId": "api", "http": {"method": method, "sourceIp": "1.2.3.4"}},
        "body": json.dumps(body or {}),
    }


@pytest.mark.parametrize("path,method", [
    (CREATE, "POST"), (CREATE, "GET"), (CONTROL, "POST"), (CONTROL, "GET"), (CONTROL, "DELETE"),
])
@pytest.mark.parametrize("groups", [["Operator"], ["Viewer"]])
def test_bulk_routes_refuse_non_admin(monkeypatch, path, method, groups):
    module = _load(path, monkeypatch)
    module.dynamodb = Dynamo(CONTACTS)
    response = module.handler(_real_auth_event(monkeypatch, groups, method), None)
    assert response["statusCode"] == 403
    assert module.dynamodb.tables["jobs"].puts == [] and module.dynamodb.tables["jobs"].updates == []


def test_admin_create_records_the_token_user(monkeypatch):
    module = _load(CREATE, monkeypatch)
    module.dynamodb = Dynamo(CONTACTS)
    module._meta_client = Meta(approved())
    event = _real_auth_event(monkeypatch, ["Admin"], "POST", {
        "templateName": "promo", "createdBy": "spoofed", "recipients": [{"contactId": "c-in"}]})
    response = module.handler(event, None)
    assert response["statusCode"] == 201
    assert module.dynamodb.tables["jobs"].puts[0]["createdBy"] == "staff-1"


def test_admin_passes_the_control_gate(monkeypatch):
    module = _load(CONTROL, monkeypatch)
    module.dynamodb = Dynamo(CONTACTS)
    event = _real_auth_event(monkeypatch, ["Admin"], "GET")
    event["pathParameters"] = {"jobId": "nope"}
    assert module.handler(event, None)["statusCode"] == 404
