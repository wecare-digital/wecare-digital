"""`POST /system-cleanup` must not be able to empty production.

What was measured, on commit f87ea643
-------------------------------------
`amplify/functions/operations/system-cleanup/handler.py` called `require_auth(event)` with
**no `required_role`**, while its own module docstring claimed "the caller must be an
authenticated admin". Nothing in the file checked a role, so any authenticated caller
qualified — and before the staff-pool pin in `lambda_utils.middleware`, "any authenticated
caller" included a customer-pool token.

`_build_resources()` then merged the curated registry with `_discover_tables()` (every
`stack-wecare-digital-*` table not in a four-entry `PROTECTED_TABLES`) and
`_discover_s3_prefixes()` (every folder three levels under `o/stack/`). `PROTECTED_TABLES`
held only SystemConfigTable, SystemConfig, ShortLinksTable and LinkClicksTable, so
ContactsTable, InvoicesTable, PaymentsTable and AuditLogsTable were all selectable. The
curated registry named contacts, invoices, payments and audit_logs outright, so
auto-discovery was not even the only hole. `_wipe_s3_prefix` and `_purge_sqs_queue` had no
guard at all. There was no confirmation token and no durable audit record — only a
`logger.info`, and the audit table it would have written to was itself deletable.

Production is currently protected by reserved concurrency 0 on the function. That throttle
is an operational mitigation, not a code guard, and these tests are what make it safe to
lift.

Every case below drives the real `handler()` with the real `require_auth`, so the auth
refusals are end-to-end rather than asserted against a stub.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from unittest.mock import MagicMock, patch  # noqa: E402

import lambda_utils.destructive_confirm as dc  # noqa: E402
import lambda_utils.middleware as mw  # noqa: E402

HANDLER = ROOT / "amplify/functions/operations/system-cleanup/handler.py"

CUSTOMER_POOL_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"

ALLOWED_ID = "rate_limit"
ALLOWED_TABLE = "stack-wecare-digital-RateLimitTable"
#: One representative id from each family the brief names as never-selectable.
PROTECTED_IDS = [
    "contacts",             # customer identity
    "invoices",             # financial record
    "payments",             # financial record
    "audit_logs",           # the audit trail itself
    "wix_order_ids",        # payment idempotency anchors
    "whatsapp_inbox",       # customer messages
    "whatsapp_outbox",
    "submit_requests",      # flow submissions
    "messages_legacy",
    "conversation_history",
    "invoice_items",
    "invoice_sequence",
    "razorpay_webhook_log",
]


def _token(issuer: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer, "sub": "sub-admin-1"}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


# ──────────────────────────────────────────────────────────────────────────
# fakes
# ──────────────────────────────────────────────────────────────────────────
class FakeCognito:
    """`get_user` succeeds for any token, exactly as the real API does."""

    class exceptions:
        class NotAuthorizedException(Exception):
            pass

    def __init__(self, groups, mfa=("SOFTWARE_TOKEN_MFA",)):
        self._groups = list(groups)
        self._mfa = list(mfa)

    def get_user(self, AccessToken):  # noqa: N803
        return {"Username": "admin-1",
                "UserAttributes": [{"Name": "email", "Value": "admin@example.test"},
                                   {"Name": "sub", "Value": "sub-admin-1"}]}

    def admin_list_groups_for_user(self, Username, UserPoolId):  # noqa: N803
        return {"Groups": [{"GroupName": g} for g in self._groups]}

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        return {"UserMFASettingList": self._mfa,
                "PreferredMfaSetting": self._mfa[0] if self._mfa else None}


class FakeBatchWriter:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def delete_item(self, Key):  # noqa: N803
        self.table.deleted.append(dict(Key))
        self.table.items = [i for i in self.table.items
                            if not all(i.get(k) == v for k, v in Key.items())]


class FakeTable:
    def __init__(self, name, items=None):
        self.name = name
        self.items = list(items or [])
        self.deleted = []
        self.put_items = []
        self.batch_writer_calls = 0

    # ── config-row operations (confirmation token) ──
    def get_item(self, Key, **kw):  # noqa: N803
        for item in self.items:
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": dict(item)}
        return {}

    def put_item(self, Item):  # noqa: N803
        self.put_items.append(dict(Item))
        self.items = [i for i in self.items if i.get("id") != Item.get("id")]
        self.items.append(dict(Item))

    def delete_item(self, Key, **kw):  # noqa: N803
        before = len(self.items)
        self.items = [i for i in self.items
                      if not all(i.get(k) == v for k, v in Key.items())]
        if before == len(self.items) and kw.get("ConditionExpression"):
            raise RuntimeError("ConditionalCheckFailedException")
        self.deleted.append(dict(Key))

    # ── bulk operations ──
    def scan(self, **kw):
        if kw.get("Select") == "COUNT":
            return {"Count": len(self.items)}
        return {"Items": [dict(i) for i in self.items]}

    def batch_writer(self):
        self.batch_writer_calls += 1
        return FakeBatchWriter(self)


class FakeDynamo:
    def __init__(self, seed=None):
        self.tables = {}
        for name, items in (seed or {}).items():
            self.tables[name] = FakeTable(name, items)

    def Table(self, name):  # noqa: N802 - boto3's spelling
        if name not in self.tables:
            self.tables[name] = FakeTable(name)
        return self.tables[name]


class FakeDynamoClient:
    def __init__(self, keys=None):
        self.keys = keys or {}

    def describe_table(self, TableName):  # noqa: N803
        key = self.keys.get(TableName, "id")
        return {"Table": {"KeySchema": [{"AttributeName": key, "KeyType": "HASH"}]}}

    def list_tables(self, **kw):
        raise AssertionError("auto-discovery was removed; list_tables must not be called")


class FakeS3:
    def __init__(self):
        self.delete_calls = []

    def get_paginator(self, _op):
        class P:
            def paginate(self, **kw):
                return [{"Contents": [{"Key": "o/stack/x/a.png"}]}]
        return P()

    def list_objects_v2(self, **kw):
        return {"Contents": [{"Key": "o/stack/x/a.png"}]}

    def delete_objects(self, **kw):
        self.delete_calls.append(kw)
        return {}


class FakeSqs:
    def __init__(self):
        self.purge_calls = []

    def get_queue_url(self, QueueName):  # noqa: N803
        return {"QueueUrl": f"https://sqs.test/{QueueName}"}

    def get_queue_attributes(self, **kw):
        return {"Attributes": {"ApproximateNumberOfMessages": "3",
                               "ApproximateNumberOfMessagesNotVisible": "0"}}

    def purge_queue(self, QueueUrl):  # noqa: N803
        self.purge_calls.append(QueueUrl)
        return {}


# ──────────────────────────────────────────────────────────────────────────
# fixtures
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mod():
    """The handler, loaded with boto3 stubbed so importing it makes no AWS call."""
    spec = importlib.util.spec_from_file_location("system_cleanup_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch("boto3.resource", MagicMock()), patch("boto3.client", MagicMock()):
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def audit_calls():
    return []


@pytest.fixture(autouse=True)
def wiring(mod, monkeypatch, audit_calls):
    """Replace every AWS client with a fake and make the audit sink observable."""
    monkeypatch.delenv("ADMIN_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(mw, "AUTH_SKIP_PATHS", [])

    fake_ddb = FakeDynamo(seed={
        ALLOWED_TABLE: [{"id": f"rl-{i}"} for i in range(4)],
        "stack-wecare-digital-ContactsTable": [{"id": "c-1"}, {"id": "c-2"}],
        "stack-wecare-digital-InvoicesTable": [{"invoiceId": "INV-1"}],
        "stack-wecare-digital-AuditLogsTable": [{"id": "a-1"}],
        mod.SYSTEM_CONFIG_TABLE: [],
    })
    fake_s3 = FakeS3()
    fake_sqs = FakeSqs()

    monkeypatch.setattr(mod, "dynamodb", fake_ddb)
    # Confirmation tokens are stored by the shared destructive_confirm helper.
    # Point it at the same fake Dynamo resource so this suite stays hermetic.
    monkeypatch.setattr(mod.destructive_confirm, "_dynamodb", fake_ddb)
    monkeypatch.setattr(mod, "dynamodb_client", FakeDynamoClient(
        {"stack-wecare-digital-InvoicesTable": "invoiceId"}))
    monkeypatch.setattr(mod, "s3", fake_s3)
    monkeypatch.setattr(mod, "sqs", fake_sqs)
    # THE SEAM THAT WAS MISSING. The handler delegates the confirmation token to
    # `lambda_utils.destructive_confirm` (handler.py:71, 598, 605), which builds its OWN
    # resource lazily — so stubbing `mod.dynamodb` leaves the token store pointed at real
    # AWS. With the outbound network guard in conftest.py now refusing that call, `mint`
    # returned None, every preview handed back `confirmationToken: ''`, and 27 of the 64
    # tests in this file failed on the empty token rather than on anything they assert.
    # Measured on origin/stack f280825e: 29 failed, of which 27 were this one line.
    monkeypatch.setattr(dc, "_dynamodb", fake_ddb)

    def fake_audit(**kwargs):
        audit_calls.append(kwargs)
        return "log-id-1"

    monkeypatch.setattr(mod, "record_audit", lambda **kw: fake_audit(**kw))

    return {"ddb": fake_ddb, "s3": fake_s3, "sqs": fake_sqs}


def as_staff(monkeypatch, groups=("Admin",), mfa=("SOFTWARE_TOKEN_MFA",)):
    monkeypatch.setattr(mw, "cognito", FakeCognito(groups, mfa))
    return _token(mw.staff_pool_issuer())


def event(method, token, body=None):
    ev = {
        "requestContext": {"apiId": "zllr9lrg7j", "stage": "prod",
                           "domainName": "api.wecare.digital",
                           "http": {"method": method, "path": "/prod/system-cleanup",
                                    "sourceIp": "203.0.113.1"}},
        "headers": {"origin": "https://wecare.digital"},
    }
    if token:
        ev["headers"]["authorization"] = f"Bearer {token}"
    if body is not None:
        ev["body"] = json.dumps(body)
    return ev


def body_of(response):
    return json.loads(response["body"])


def preview(mod, monkeypatch, **kw):
    """A successful GET, returning (parsed body, confirmation token, bearer)."""
    token = as_staff(monkeypatch, **kw)
    resp = mod.handler(event("GET", token), None)
    assert resp["statusCode"] == 200
    data = body_of(resp)
    return data, data["confirmationToken"], token


def rows(data):
    return {r["id"]: r for r in data["resources"]}


def rebind_token(mod, wiring, confirm, selection):
    """Point an existing token at `selection`.

    Used so a protected-table refusal is the ALLOW-LIST refusing rather than the token
    refusing. It models a caller who has tampered with both the UI's payload AND the
    stored selection, which is the worst case the guard has to survive.
    """
    config = wiring["ddb"].Table(mod.SYSTEM_CONFIG_TABLE)
    row = config.get_item(Key={"id": f"cleanup_confirm_{confirm}"})["Item"]
    row["selection"] = sorted(selection)
    config.put_item(Item=row)


# ──────────────────────────────────────────────────────────────────────────
# auth
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("groups", [("Viewer",), ("Operator",)])
def test_a_non_admin_is_refused(mod, monkeypatch, groups):
    """`require_auth(event)` carried no `required_role` at all. Both methods now need Admin."""
    token = as_staff(monkeypatch, groups=groups)
    assert mod.handler(event("GET", token), None)["statusCode"] == 403
    assert mod.handler(event("POST", token, {"selected": [ALLOWED_ID]}), None)["statusCode"] == 403


def test_a_partner_is_refused(mod, monkeypatch):
    token = as_staff(monkeypatch, groups=("Partner",))
    assert mod.handler(event("GET", token), None)["statusCode"] == 403


def test_an_ungrouped_principal_is_refused(mod, monkeypatch):
    token = as_staff(monkeypatch, groups=())
    assert mod.handler(event("GET", token), None)["statusCode"] == 403


def test_a_customer_pool_token_is_refused(mod, monkeypatch):
    """The finding: `GetUser` validated a customer token, and the role fell through to Viewer."""
    as_staff(monkeypatch, groups=("Admin",))
    resp = mod.handler(event("POST", _token(CUSTOMER_POOL_ISSUER),
                             {"selected": [ALLOWED_ID]}), None)
    assert resp["statusCode"] == 401


def test_no_token_is_refused(mod, monkeypatch):
    as_staff(monkeypatch)
    assert mod.handler(event("GET", None), None)["statusCode"] == 401


@pytest.mark.parametrize("mfa", [(), None])
def test_an_admin_without_mfa_cannot_delete(mod, monkeypatch, mfa):
    """`mfaEnrolled` False or None both refuse. None means the lookup could not answer."""
    if mfa is None:
        fake = FakeCognito(("Admin",), ())
        fake.admin_get_user = lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))
        monkeypatch.setattr(mw, "cognito", fake)
        token = _token(mw.staff_pool_issuer())
    else:
        token = as_staff(monkeypatch, mfa=mfa)
    resp = mod.handler(event("POST", token, {"selected": [ALLOWED_ID]}), None)
    assert resp["statusCode"] == 403
    assert body_of(resp)["error"] == "MFA required"


def test_mfa_is_not_required_to_read_the_preview(mod, monkeypatch):
    """Reading counts is not destructive, and refusing it would hide the protected rows."""
    token = as_staff(monkeypatch, mfa=())
    assert mod.handler(event("GET", token), None)["statusCode"] == 200


# ──────────────────────────────────────────────────────────────────────────
# the allow-list
# ──────────────────────────────────────────────────────────────────────────
def test_auto_discovery_is_gone(mod, monkeypatch):
    """A new `stack-wecare-digital-*` table must not become deletable by existing.

    Asserted through the preview output and through `FakeDynamoClient.list_tables`, which
    raises: the old `_build_resources` called it on every request.
    """
    assert not hasattr(mod, "_discover_tables")
    assert not hasattr(mod, "_discover_s3_prefixes")
    data, _, _ = preview(mod, monkeypatch)
    assert not any(r["id"].startswith(("auto_tbl_", "auto_s3_")) for r in data["resources"])


def test_only_the_four_allow_listed_tables_are_selectable(mod, monkeypatch):
    data, _, _ = preview(mod, monkeypatch)
    selectable = sorted(r["table"] for r in data["resources"] if r["selectable"])
    assert selectable == sorted(mod.CLEANUP_ALLOWLIST)


@pytest.mark.parametrize("res_id", PROTECTED_IDS)
def test_a_protected_row_is_marked_protected_with_a_reason(mod, monkeypatch, res_id):
    data, _, _ = preview(mod, monkeypatch)
    row = rows(data)[res_id]
    assert row["protected"] is True
    assert row["selectable"] is False
    assert row["protectedReason"]


def test_every_row_carries_the_three_flags(mod, monkeypatch):
    data, _, _ = preview(mod, monkeypatch)
    for row in data["resources"]:
        assert {"selectable", "protected", "protectedReason"} <= set(row)
        assert row["selectable"] is not row["protected"]


def test_protected_rows_still_report_their_counts(mod, monkeypatch):
    """Hiding them would answer "what is in this system" with a lie."""
    data, _, _ = preview(mod, monkeypatch)
    assert rows(data)["contacts"]["count"] == 2


def test_every_s3_prefix_is_protected(mod, monkeypatch):
    data, _, _ = preview(mod, monkeypatch)
    s3_rows = [r for r in data["resources"] if r["type"] == "s3"]
    assert s3_rows, "the registry lost its S3 entries; this test would pass vacuously"
    assert all(r["protected"] for r in s3_rows)


def test_every_sqs_queue_is_protected(mod, monkeypatch):
    data, _, _ = preview(mod, monkeypatch)
    sqs_rows = [r for r in data["resources"] if r["type"] == "sqs"]
    assert sqs_rows
    assert all(r["protected"] for r in sqs_rows)


def test_the_keyword_guard_is_independent_of_the_allow_list(mod):
    """Second layer: adding a protected name to CLEANUP_ALLOWLIST must still not work."""
    assert mod._table_protected_reason("stack-wecare-digital-ContactsTable")
    assert mod._table_protected_reason("stack-wecare-digital-SomeNewPaymentsThing")
    assert mod._table_protected_reason("stack-wecare-digital-AuditLogsTable")
    assert mod._table_protected_reason(ALLOWED_TABLE) is None


def test_no_allow_listed_table_matches_the_deny_keywords(mod):
    """A contradiction between the two layers would make one of them unreachable."""
    for table in mod.CLEANUP_ALLOWLIST:
        assert mod._matched_keyword(table) is None, table
        assert table not in mod.PROTECTED_TABLES


# ──────────────────────────────────────────────────────────────────────────
# the confirmation token
# ──────────────────────────────────────────────────────────────────────────
def test_the_preview_mints_a_token_bound_to_the_selectable_ids(mod, monkeypatch, wiring):
    data, token, _ = preview(mod, monkeypatch)
    assert token
    row = wiring["ddb"].Table(mod.SYSTEM_CONFIG_TABLE).get_item(
        Key={"id": f"cleanup_confirm_{token}"})["Item"]
    assert row["selection"] == sorted(data["selectableIds"])
    assert row["actor"] == "sub-admin-1"
    assert row["expiresAt"] > row["createdAt"]


def test_a_post_with_no_token_is_refused(mod, monkeypatch, wiring):
    """THE UI-BYPASS CASE: a direct POST that never called GET cannot delete."""
    token = as_staff(monkeypatch)
    resp = mod.handler(event("POST", token, {"selected": [ALLOWED_ID]}), None)
    assert resp["statusCode"] == 400
    assert "confirmationToken" in body_of(resp)["error"]
    assert wiring["ddb"].Table(ALLOWED_TABLE).batch_writer_calls == 0


def test_a_selection_one_id_different_from_the_token_is_refused(mod, monkeypatch, wiring):
    data, token, bearer = preview(mod, monkeypatch)
    selection = sorted(data["selectableIds"])[:-1]
    resp = mod.handler(event("POST", bearer, {"selected": selection,
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 409
    assert wiring["ddb"].Table(ALLOWED_TABLE).batch_writer_calls == 0


def test_an_unknown_token_is_refused(mod, monkeypatch):
    data, _, bearer = preview(mod, monkeypatch)
    resp = mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                              "confirmationToken": "not-a-token"}), None)
    assert resp["statusCode"] == 409


def test_a_replayed_token_is_refused_so_a_retry_cannot_double_delete(mod, monkeypatch, wiring):
    data, token, bearer = preview(mod, monkeypatch)
    payload = {"selected": data["selectableIds"], "confirmationToken": token}
    first = mod.handler(event("POST", bearer, payload), None)
    assert first["statusCode"] == 200
    second = mod.handler(event("POST", bearer, payload), None)
    assert second["statusCode"] == 409
    assert wiring["ddb"].Table(ALLOWED_TABLE).batch_writer_calls == 1


def test_an_expired_token_is_refused(mod, monkeypatch, wiring):
    data, token, bearer = preview(mod, monkeypatch)
    config = wiring["ddb"].Table(mod.SYSTEM_CONFIG_TABLE)
    row = config.get_item(Key={"id": f"cleanup_confirm_{token}"})["Item"]
    row["expiresAt"] = 1
    config.put_item(Item=row)
    resp = mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 409
    assert "expired" in body_of(resp)["error"]


def test_a_confirmation_store_that_cannot_be_written_blocks_the_delete(mod, monkeypatch):
    """Fail-closed direction: the preview still renders, nothing can be deleted."""
    monkeypatch.setattr(mod, "_mint_confirmation", lambda *a, **kw: None)
    token = as_staff(monkeypatch)
    data = body_of(mod.handler(event("GET", token), None))
    assert data["confirmationToken"] == ""
    assert data["warning"]
    resp = mod.handler(event("POST", token, {"selected": data["selectableIds"],
                                             "confirmationToken": ""}), None)
    assert resp["statusCode"] == 400


# ──────────────────────────────────────────────────────────────────────────
# the delete itself
# ──────────────────────────────────────────────────────────────────────────
def test_an_allow_listed_table_is_deleted_and_counted(mod, monkeypatch, wiring):
    data, token, bearer = preview(mod, monkeypatch)
    resp = mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 200
    out = body_of(resp)
    results = {r["id"]: r for r in out["results"]}
    assert results[ALLOWED_ID]["deleted"] == 4
    assert out["totalDeleted"] == 4
    assert wiring["ddb"].Table(ALLOWED_TABLE).items == []


def test_a_subset_of_the_confirmed_selection_is_refused(mod, monkeypatch, wiring):
    """The token binds the EXACT selection, so narrowing it after the fact is a mismatch."""
    _, token, bearer = preview(mod, monkeypatch)
    resp = mod.handler(event("POST", bearer, {"selected": [ALLOWED_ID],
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 409
    assert wiring["ddb"].Table(ALLOWED_TABLE).batch_writer_calls == 0


@pytest.mark.parametrize("res_id", PROTECTED_IDS)
def test_a_protected_table_is_refused_even_for_an_mfad_admin(mod, monkeypatch, wiring, res_id):
    """Reported `protected` with `deleted == 0`, and `batch_writer` is never called."""
    data, token, bearer = preview(mod, monkeypatch)
    selection = sorted(set(data["selectableIds"]) | {res_id})
    rebind_token(mod, wiring, token, selection)

    resp = mod.handler(event("POST", bearer, {"selected": selection,
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 200
    out = body_of(resp)
    result = {r["id"]: r for r in out["results"]}[res_id]
    assert result["protected"] is True
    assert result["deleted"] == 0
    assert result["protectedReason"]
    assert out["protected"] >= 1

    table = mod.CLEANUP_RESOURCES[res_id]["table"]
    assert wiring["ddb"].Table(table).batch_writer_calls == 0
    assert wiring["ddb"].Table(table).deleted == []


def test_every_s3_prefix_is_refused_and_delete_objects_is_never_called(mod, monkeypatch, wiring):
    s3_ids = [k for k, v in mod.CLEANUP_RESOURCES.items() if v["type"] == "s3"]
    data, token, bearer = preview(mod, monkeypatch)
    selection = sorted(set(data["selectableIds"]) | set(s3_ids))
    rebind_token(mod, wiring, token, selection)

    resp = mod.handler(event("POST", bearer, {"selected": selection,
                                              "confirmationToken": token}), None)
    results = {r["id"]: r for r in body_of(resp)["results"]}
    for sid in s3_ids:
        assert results[sid]["protected"] is True
        assert results[sid]["deleted"] == 0
    assert wiring["s3"].delete_calls == []


def test_every_sqs_queue_is_refused_and_purge_queue_is_never_called(mod, monkeypatch, wiring):
    sqs_ids = [k for k, v in mod.CLEANUP_RESOURCES.items() if v["type"] == "sqs"]
    data, token, bearer = preview(mod, monkeypatch)
    selection = sorted(set(data["selectableIds"]) | set(sqs_ids))
    rebind_token(mod, wiring, token, selection)

    resp = mod.handler(event("POST", bearer, {"selected": selection,
                                              "confirmationToken": token}), None)
    results = {r["id"]: r for r in body_of(resp)["results"]}
    for sid in sqs_ids:
        assert results[sid]["protected"] is True
    assert wiring["sqs"].purge_calls == []


def test_the_low_level_guards_refuse_directly(mod):
    """Called below the registry, so a future careless registry edit still cannot delete."""
    with pytest.raises(mod.CleanupRefused):
        mod._wipe_table("stack-wecare-digital-ContactsTable")
    with pytest.raises(mod.CleanupRefused):
        mod._wipe_table("stack-wecare-digital-AuditLogsTable")
    with pytest.raises(mod.CleanupRefused):
        mod._wipe_s3_prefix("o/stack/whatsapp-media/")
    with pytest.raises(mod.CleanupRefused):
        mod._purge_sqs_queue("stack-wecare-digital-bulk-queue")


# ──────────────────────────────────────────────────────────────────────────
# the audit record
# ──────────────────────────────────────────────────────────────────────────
def test_the_audit_record_names_the_actor_the_selection_and_the_counts(
        mod, monkeypatch, audit_calls):
    data, token, bearer = preview(mod, monkeypatch)
    mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                       "confirmationToken": token}), None)
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["action"] == "system.cleanup"
    assert call["actor"] == "sub-admin-1"
    assert call["details"]["selection"] == sorted(data["selectableIds"])
    assert call["details"]["previewCounts"][ALLOWED_ID] == 4


def test_the_audit_record_is_written_before_the_first_delete(mod, monkeypatch):
    order = []

    monkeypatch.setattr(mod, "record_audit",
                        lambda **kw: (order.append("audit"), "log-1")[1])
    real_wipe = mod._wipe_table
    monkeypatch.setattr(mod, "_wipe_table",
                        lambda name: (order.append("wipe"), real_wipe(name))[1])

    data, token, bearer = preview(mod, monkeypatch)
    mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                       "confirmationToken": token}), None)
    assert order[0] == "audit"
    assert "wipe" in order


def test_a_failing_audit_write_refuses_the_whole_request(mod, monkeypatch, wiring):
    """`record_audit` fails open by design. For an irreversible delete that trade is wrong."""
    monkeypatch.setattr(mod, "record_audit", lambda **kw: None)
    data, token, bearer = preview(mod, monkeypatch)
    resp = mod.handler(event("POST", bearer, {"selected": data["selectableIds"],
                                              "confirmationToken": token}), None)
    assert resp["statusCode"] == 503
    assert wiring["ddb"].Table(ALLOWED_TABLE).batch_writer_calls == 0
    assert len(wiring["ddb"].Table(ALLOWED_TABLE).items) == 4


def test_the_audit_sink_is_not_in_the_deletable_set(mod):
    """An audit trail this handler can empty is not an audit trail."""
    assert "stack-wecare-digital-AuditLogsTable" in mod.PROTECTED_TABLES
    assert "stack-wecare-digital-AuditLogsTable" not in mod.CLEANUP_ALLOWLIST


def test_a_selection_of_only_protected_ids_writes_no_audit_record_and_deletes_nothing(
        mod, monkeypatch, wiring, audit_calls):
    _, confirm, bearer = preview(mod, monkeypatch)
    rebind_token(mod, wiring, confirm, ["contacts"])

    resp = mod.handler(event("POST", bearer, {"selected": ["contacts"],
                                              "confirmationToken": confirm}), None)
    out = body_of(resp)
    assert out["totalDeleted"] == 0
    assert out["protected"] == 1
    assert audit_calls == [], "nothing was deleted, so there is nothing to record"


# ──────────────────────────────────────────────────────────────────────────
# the rest of the contract
# ──────────────────────────────────────────────────────────────────────────
def test_an_empty_selection_is_refused(mod, monkeypatch):
    token = as_staff(monkeypatch)
    assert mod.handler(event("POST", token, {"selected": []}), None)["statusCode"] == 400


def test_an_unknown_id_is_reported_not_deleted(mod, monkeypatch, wiring):
    data, token, bearer = preview(mod, monkeypatch)
    selection = sorted(set(data["selectableIds"]) | {"no_such_resource"})
    rebind_token(mod, wiring, token, selection)
    resp = mod.handler(event("POST", bearer, {"selected": selection,
                                              "confirmationToken": token}), None)
    results = {r["id"]: r for r in body_of(resp)["results"]}
    assert results["no_such_resource"]["error"] == "Unknown resource"


def test_options_is_still_a_preflight(mod, monkeypatch):
    as_staff(monkeypatch)
    assert mod.handler(event("OPTIONS", None), None)["statusCode"] in (200, 204)


def test_an_unsupported_method_is_405(mod, monkeypatch):
    token = as_staff(monkeypatch)
    assert mod.handler(event("PUT", token, {}), None)["statusCode"] == 405
