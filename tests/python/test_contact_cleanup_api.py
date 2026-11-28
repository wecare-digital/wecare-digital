"""Tests for the contacts Lambda cleanup_scan / cleanup_archive actions, with in-memory fakes.

All identifiers are synthetic. Archive is the only cleanup action; nothing may delete a row.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
for sub in ("amplify/functions/shared", "amplify/functions/core/contacts"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)
os.environ.setdefault("AWS_REGION", "us-east-1")

import handler as h  # noqa: E402
from lambda_utils import contact_cleanup, destructive_confirm  # noqa: E402

ACTOR = {"username": "admin-1"}


class FakeTable:
    def __init__(self, items=None, page_size=2, fail=False, key="id"):
        self.items = list(items or [])
        self.page_size = page_size
        self.fail = fail
        self.key = key
        self.deletes = []
        self.updates = []

    def scan(self, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        start = int((kwargs.get("ExclusiveStartKey") or {}).get("i", 0))
        out = {"Items": [dict(i) for i in self.items[start:start + self.page_size]]}
        if start + self.page_size < len(self.items):
            out["LastEvaluatedKey"] = {"i": start + self.page_size}
        return out

    def query(self, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        attr = kwargs["KeyConditionExpression"].split("=")[0].strip()
        value = list(kwargs["ExpressionAttributeValues"].values())[0]
        return {"Items": [i for i in self.items if i.get(attr) == value]}

    def get_item(self, **kwargs):
        for row in self.items:
            if row.get("id") == kwargs["Key"]["id"]:
                return {"Item": dict(row)}
        return {}

    def update_item(self, **kwargs):
        cid = kwargs["Key"]["id"]
        row = next((r for r in self.items if r.get("id") == cid), None)
        if row is None or row.get("locked") or row.get("mergeState") == "merged":
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        vals = kwargs["ExpressionAttributeValues"]
        row["archivedAt"] = vals[":now"]
        row["archivedBy"] = vals[":actor"]
        row["archivedReason"] = vals[":reason"]
        self.updates.append(cid)
        return {"Attributes": dict(row)}

    def delete_item(self, **kwargs):
        self.deletes.append(kwargs)
        raise AssertionError("delete_item must never be called on ContactsTable")


class FakeConfig:
    """In-memory SystemConfigTable for destructive_confirm."""

    def __init__(self):
        self.rows = {}

    def put_item(self, Item, **kw):
        self.rows[Item["id"]] = Item

    def get_item(self, Key, **kw):
        row = self.rows.get(Key["id"])
        return {"Item": dict(row)} if row else {}

    def delete_item(self, Key, **kw):
        if Key["id"] not in self.rows:
            raise RuntimeError("gone")
        del self.rows[Key["id"]]


def contact(cid, phone, **extra):
    row = {"id": cid, "contactId": cid, "phone": phone, "name": "Same Name"}
    row.update(extra)
    return row


def junk(n):
    return contact(f"junk{n}", f"+1555000{n:04d}")


@pytest.fixture
def env(monkeypatch):
    config = FakeConfig()
    monkeypatch.setattr(destructive_confirm, "_table", lambda: config)
    store = {k: FakeTable() for k in contact_cleanup.ENV_TABLES}
    monkeypatch.setattr(h, "_cleanup_tables", lambda: store)
    monkeypatch.setattr(h, "dynamodb", type("D", (), {"Table": lambda self, name: store["contacts"]})())
    monkeypatch.setattr(h, "record_audit", lambda **kw: "log")
    return type("Env", (), {"tables": store, "config": config})


def set_contacts(env, rows):
    env.tables["contacts"].items = list(rows)


def body_of(resp):
    return json.loads(resp["body"])


def scan(env, **extra):
    resp = h._cleanup_scan(extra, ACTOR, "req")
    assert resp["statusCode"] == 200
    return body_of(resp)


def archive(env, token, ids, **extra):
    payload = {"confirmationToken": token, "contactIds": ids, "reason": "junk"}
    payload.update(extra)
    return h._cleanup_archive(payload, ACTOR, "req")


def standard(env):
    set_contacts(env, [
        contact("paidmsg", "+15550000001"),
        contact("inv", "+15550000002"),
        contact("link", "+15550000003"),
        contact("locked", "+15550000004", locked=True),
        contact("holdid", "+15550000005"),
        contact("holdphone", "+15550000006"),
        contact("holdbsuid", "+15550000007", bsuid="US.abc123"),
        contact("junk1", "+15550000008"),
        contact("junk2", "+15550000009"),
    ])
    env.tables["outbound"].items = [
        {"id": "m1", "contactId": "paidmsg", "content": "Payment received", "paymentId": "pay_ABCDEF123"}]
    env.tables["invoices"].items = [
        {"invoiceId": "i1", "contactId": "inv", "paymentStatus": "captured"}]
    env.tables["orders"].items = [{"orderId": "o1", "customerPhone": "+15550000003"}]


KEEP = {"keepContactIds": ["holdid"], "keepPhones": ["+15550000006"], "keepBsuids": ["US.abc123"]}


def by_label(report, cid):
    return next(c for c in report["contacts"] if c["contactId"] == cid)


def test_scan_keeps_every_kind_of_evidence_and_flags_only_junk(env):
    standard(env)
    out = scan(env, **KEEP)
    assert out["status"] == "OK"
    ids = [e["contactId"] for e in out["eligible"]]
    assert ids == ["junk1", "junk2"]
    kept_labels = {k["classification"] for k in out["kept"]}
    assert {"FINANCIAL_RETENTION", "LEGAL_OR_IDENTITY_LOCK", "OPERATOR_HOLD"} <= kept_labels
    assert out["keptTotal"] == 7
    assert out["confirmationToken"]
    assert out["action"] == "archive"
    assert "ttlGap" in out and out["counts"]["eligible"] == 2
    for e in out["eligible"]:
        assert e["maskedPhone"].startswith("****")
        assert "+1555" not in json.dumps(e)


def test_payment_link_via_has_payment_links_keeps_contact(env):
    standard(env)
    out = scan(env, **KEEP)
    assert "link" not in [e["contactId"] for e in out["eligible"]]


def test_scan_response_never_contains_raw_payment_payload(env):
    standard(env)
    text = json.dumps(scan(env, **KEEP))
    assert "pay_ABCDEF123" not in text


def test_without_operator_hold_payment_and_lock_still_protect(env):
    standard(env)
    out = scan(env)
    ids = {e["contactId"] for e in out["eligible"]}
    assert "paidmsg" not in ids and "inv" not in ids and "link" not in ids and "locked" not in ids


def test_same_name_contacts_stay_distinct(env):
    set_contacts(env, [contact("a", "+15550000011"), contact("b", "+15550000012")])
    out = scan(env, keepContactIds=["a"])
    assert [e["contactId"] for e in out["eligible"]] == ["b"]


def test_names_are_rejected_as_selectors(env):
    resp = h._cleanup_scan({"keepNames": ["Same Name"]}, ACTOR, "req")
    assert resp["statusCode"] == 400


def test_incomplete_read_yields_zero_eligible_and_no_token(env):
    standard(env)
    env.tables["payments"].fail = True
    out = scan(env, **KEEP)
    assert out["status"] == "INCOMPLETE"
    assert out["eligible"] == [] and out["counts"]["eligible"] == 0
    assert out["confirmationToken"] is None


def test_contacts_unreadable_yields_zero_eligible(env):
    standard(env)
    env.tables["contacts"].fail = True
    out = scan(env, **KEEP)
    assert out["eligible"] == [] and out["confirmationToken"] is None


def test_scan_pages_eligible_and_binds_token_to_the_page(env):
    set_contacts(env, [junk(n) for n in range(5)])
    blocked = scan(env, limit=2, keepContactIds=["nobody-x"])
    # An unmatched selector blocks the run (fail closed).
    assert blocked["eligible"] == [] and blocked["confirmationToken"] is None
    set_contacts(env, [junk(n) for n in range(5)] + [contact("keep", "+15550009999")])
    page = scan(env, limit=2, keepContactIds=["keep"])
    assert [e["contactId"] for e in page["eligible"]] == ["junk0", "junk1"]
    assert page["eligibleNextOffset"] == 2


def test_archive_success_only_eligible_and_never_deletes(env):
    standard(env)
    out = scan(env, **KEEP)
    resp = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    assert resp["statusCode"] == 200
    result = body_of(resp)
    assert result["archived"] == 2 and result["reversible"] is True
    contacts = env.tables["contacts"]
    assert contacts.deletes == []
    assert sorted(contacts.updates) == ["junk1", "junk2"]
    rows = {r["id"]: r for r in contacts.items}
    assert rows["junk1"]["archivedAt"] and rows["junk1"]["archivedReason"].startswith("cleanup:")
    assert "archivedAt" not in rows["paidmsg"] and "archivedAt" not in rows["locked"]
    assert len(rows) == 9


def test_archive_without_token_is_refused(env):
    standard(env)
    resp = archive(env, "", ["junk1"], **KEEP)
    assert resp["statusCode"] == 400
    assert env.tables["contacts"].updates == []


def test_archive_replayed_token_is_refused(env):
    standard(env)
    out = scan(env, **KEEP)
    first = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    assert first["statusCode"] == 200
    again = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    assert again["statusCode"] == 409


def test_archive_with_mismatched_selection_is_refused(env):
    standard(env)
    out = scan(env, **KEEP)
    resp = archive(env, out["confirmationToken"], ["junk1"], **KEEP)
    assert resp["statusCode"] == 409
    assert env.tables["contacts"].updates == []
    # Token was not consumed by a mismatch, so adding a protected id is also refused.
    resp = archive(env, out["confirmationToken"], ["junk1", "junk2", "paidmsg"], **KEEP)
    assert resp["statusCode"] == 409
    assert env.tables["contacts"].updates == []


def test_archive_refuses_id_that_gained_payment_evidence_after_scan(env):
    standard(env)
    out = scan(env, **KEEP)
    env.tables["invoices"].items.append(
        {"invoiceId": "late", "contactId": "junk2", "paymentStatus": "captured"})
    resp = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    assert resp["statusCode"] == 409
    body = body_of(resp)
    assert body["errorCode"] == "CLEANUP_NOT_ELIGIBLE"
    assert set(body["refused"]) == {"junk2"}
    assert env.tables["contacts"].updates == []


def test_archive_refuses_contact_locked_after_scan(env):
    standard(env)
    out = scan(env, **KEEP)
    next(r for r in env.tables["contacts"].items if r["id"] == "junk1")["locked"] = True
    resp = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    assert resp["statusCode"] == 409
    assert "junk1" in body_of(resp)["refused"]
    assert env.tables["contacts"].updates == []


def test_archive_refuses_locked_and_protected_ids_even_with_a_valid_token(env):
    standard(env)
    token = destructive_confirm.mint(h.CLEANUP_SCOPE, ["locked", "paidmsg"], {}, "admin-1")
    resp = archive(env, token, ["locked", "paidmsg"], **KEEP)
    assert resp["statusCode"] == 409
    assert set(body_of(resp)["refused"]) == {"locked", "paidmsg"}
    assert env.tables["contacts"].updates == []


def test_archive_refuses_operator_hold(env):
    standard(env)
    token = destructive_confirm.mint(h.CLEANUP_SCOPE, ["holdid"], {}, "admin-1")
    resp = archive(env, token, ["holdid"], **KEEP)
    assert resp["statusCode"] == 409
    assert env.tables["contacts"].updates == []


def test_lock_set_between_rescan_and_update_is_refused_atomically(env, monkeypatch):
    standard(env)
    out = scan(env, **KEEP)
    real = h._cleanup_run

    def racing(selection):
        report = real(selection)
        next(r for r in env.tables["contacts"].items if r["id"] == "junk2")["locked"] = True
        return report

    monkeypatch.setattr(h, "_cleanup_run", racing)
    resp = archive(env, out["confirmationToken"], ["junk1", "junk2"], **KEEP)
    result = body_of(resp)
    assert result["archived"] == 1 and result["refused"] == 1
    assert env.tables["contacts"].updates == ["junk1"]


def test_archive_batch_is_capped(env):
    ids = [f"j{n}" for n in range(h.CLEANUP_BATCH_MAX + 1)]
    resp = archive(env, "x", ids)
    assert resp["statusCode"] == 400


def test_archive_requires_reason(env):
    resp = h._cleanup_archive({"confirmationToken": "x", "contactIds": ["a"]}, ACTOR, "req")
    assert resp["statusCode"] == 400


def _event(action, role):
    return {"httpMethod": "POST", "body": json.dumps({"_action": action}), "_role": role}


def test_non_admin_cannot_reach_cleanup_archive(env, monkeypatch):
    from lambda_utils import middleware
    asked = []

    def fake_require_auth(event, required_role=None):
        asked.append(required_role)
        rank = {"Viewer": 0, "Operator": 1, "Admin": 2}
        if rank[event["_role"]] < rank[required_role]:
            return {"statusCode": 403, "body": "{}"}
        return None

    monkeypatch.setattr(middleware, "require_auth", fake_require_auth)
    denied = h.handler(_event("cleanup_archive", "Operator"), None)
    assert denied["statusCode"] == 403 and "Admin" in asked
    assert env.tables["contacts"].updates == []
    # Operator cannot scan either (expensive full-table read); Admin can.
    standard(env)
    body = json.dumps({"_action": "cleanup_scan", **KEEP})
    scan_denied = h.handler({**_event("cleanup_scan", "Operator"), "body": body}, None)
    assert scan_denied["statusCode"] == 403
    ok = h.handler({**_event("cleanup_scan", "Admin"), "body": body}, None)
    assert ok["statusCode"] == 200


def test_cleanup_does_not_open_permanent_delete(env, monkeypatch):
    # Permanent erasure goes only through the approved coordinator with a
    # verified Admin + MFA caller. Cleanup candidates get no shortcut.
    standard(env)
    unauthenticated = h._delete("junk1", True, "req")
    assert unauthenticated["statusCode"] == 403
    assert "ERASURE_ADMIN_MFA_REQUIRED" in unauthenticated["body"]
    no_mfa = h._delete("junk1", True, "req", event={"_auth": {"role": "Admin", "mfaEnrolled": False}})
    assert no_mfa["statusCode"] == 403
    soft = h._delete("junk1", False, "req")
    assert soft["statusCode"] == 400
    assert "ERASURE_EXPLICIT_HARD_REQUEST_REQUIRED" in soft["body"]
    assert env.tables["contacts"].deletes == []


def test_cleanup_code_never_calls_delete_item():
    layer = (ROOT / "amplify/functions/shared/lambda_utils/contact_cleanup.py").read_text()
    handler_src = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    block = handler_src[handler_src.index("# ─── JUNK CONTACT CLEANUP"):
                        handler_src.index("# ─── DELETE (soft / hard)")]
    assert "delete_item" not in layer
    assert "delete_item" not in block


def _real_auth_event(action, monkeypatch, groups, mfa_settings, mfa_required="true"):
    """Drive the real require_auth with a faked Cognito client."""
    from lambda_utils import middleware

    class FakeCognito:
        class exceptions:
            class NotAuthorizedException(Exception):
                pass

        def get_user(self, AccessToken):
            return {"Username": "u1", "UserAttributes": []}

        def admin_list_groups_for_user(self, **kw):
            return {"Groups": [{"GroupName": g} for g in groups]}

        def admin_get_user(self, **kw):
            return {"UserMFASettingList": mfa_settings}

    monkeypatch.setattr(middleware, "cognito", FakeCognito())
    monkeypatch.setattr(middleware, "_unverified_issuer", lambda t: middleware.staff_pool_issuer())
    monkeypatch.setattr(middleware, "_unverified_clients", lambda t: {middleware.STAFF_APP_CLIENT_ID})
    monkeypatch.setattr(middleware, "_plausible_access_token", lambda t: True)
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", mfa_required)
    return {
        "httpMethod": "POST",
        "headers": {"Authorization": "Bearer t"},
        "requestContext": {"apiId": "api", "http": {"sourceIp": "1.2.3.4"}},
        "body": json.dumps({"_action": action, **KEEP}),
    }


@pytest.mark.parametrize("action", ["cleanup_scan", "cleanup_archive"])
def test_admin_without_mfa_refused_by_real_middleware(env, monkeypatch, action):
    standard(env)
    event = _real_auth_event(action, monkeypatch, ["Admin"], [])
    resp = h.handler(event, None)
    assert resp["statusCode"] == 403 and "MFA required" in resp["body"]
    assert env.tables["contacts"].updates == []


def test_admin_with_mfa_passes_real_middleware_and_operator_refused(env, monkeypatch):
    standard(env)
    event = _real_auth_event("cleanup_scan", monkeypatch, ["Admin"], ["SMS_MFA"])
    assert h.handler(event, None)["statusCode"] == 200
    event = _real_auth_event("cleanup_scan", monkeypatch, ["Operator"], ["SMS_MFA"])
    resp = h.handler(event, None)
    assert resp["statusCode"] == 403 and "Insufficient permissions" in resp["body"]
