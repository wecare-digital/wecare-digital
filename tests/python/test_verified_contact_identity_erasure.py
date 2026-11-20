"""Exact-contact approval and identity release tests; no production mutations."""
import copy
from lambda_utils.erasure import verified_identity as m


class Table:
    def __init__(self, name, records=()):
        self.name = name
        self.items = {}
        for row in records:
            key = next((row[k] for k in ("id", "claimKey", "conversationId") if k in row), None)
            if key is not None:
                self.items[key] = copy.deepcopy(row)

    def get_item(self, *, Key, **kwargs):
        key = next(iter(Key.values()))
        row = self.items.get(key)
        return {"Item": copy.deepcopy(row)} if row is not None else {}

    def scan(self, **kwargs):
        return {"Items": copy.deepcopy(list(self.items.values()))}

    def put_item(self, *, Item, **kwargs):
        assert Item["id"] not in self.items
        self.items[Item["id"]] = copy.deepcopy(Item)

    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeValues,
                    **kwargs):
        row = self.items[Key["id"]]
        assert row["status"] == "PENDING_SECOND_REVIEW"
        row.update({"status": ExpressionAttributeValues[":approved"],
                    "approvedBy": ExpressionAttributeValues[":actor"],
                    "tokenHash": ExpressionAttributeValues[":hash"],
                    "approvalAuditId": ExpressionAttributeValues[":log"]})


def setup(*, has_message=False, paid=False, legal=False,
          source_identity=False, held=False, phone=False):
    contact = {"id": "subject-a", "phone": "+919999000999" if phone else "",
               "email": "subject@example.org",
               "customerUuid": "cust-public-1", "subscriberId": "sub-public-1",
               "locked": True, "lockedReason": "legal" if legal else "created"}
    if source_identity:
        contact["bsuid"] = "IN.provider-token"
    d = {}
    for name in (m.DEPENDENCY_TABLES + ("ContactsTable", "IdentityClaimsTable",
                                       "ConversationMetaTable", "SystemConfigTable")):
        d[name] = Table(name)
    d["ContactsTable"] = Table("ContactsTable", [contact])
    d["IdentityClaimsTable"] = Table("IdentityClaimsTable", [
        {"claimKey": "EMAIL#subject@example.org", "contactId": "subject-a"},
        *([{"claimKey": "PHONE#+919999000999", "contactId": "subject-a"}] if phone else []),
    ])
    if has_message:
        d["MessagesTable"] = Table("MessagesTable", [
            {"id": "message-one", "contactId": "subject-a"}])
    if paid:
        d["PaymentsTable"] = Table("PaymentsTable", [
            {"id": "pay-one", "contactId": "subject-a"}])
    if held:
        d["ConversationMetaTable"] = Table("ConversationMetaTable", [
            {"conversationId": "subject-a", "tags": ["retention-hold"]}])
    audits = []
    def audit(**fields):
        audits.append(fields)
        return "audit-" + str(len(audits))
    return d, audit, audits


def transact(tables):
    calls = []
    def do(ops):
        calls.append(ops)
        assert len(ops) == 3
        for op in ops:
            if "Update" in op:
                entry = op["Update"]
                tables["SystemConfigTable"].items[entry["Key"]["id"]]["status"] = "CONSUMED"
            else:
                entry = op["Delete"]
                if entry["TableName"] == "ContactsTable":
                    del tables["ContactsTable"].items[entry["Key"]["id"]]
                else:
                    del tables["IdentityClaimsTable"].items[entry["Key"]["claimKey"]]
    return do, calls


def test_two_admins_can_remove_only_dependency_free_contact():
    tables, audit, logs = setup()
    p = m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
    assert p["status"] == "PENDING_SECOND_REVIEW"
    assert p["erasureComplete"] is False
    approved = m.approve(case_id=p["caseId"], actor="admin-b", tables=tables, audit=audit)
    assert approved["status"] == "APPROVED"
    action, calls = transact(tables)
    result = m.execute(contact_id="subject-a", case_id=p["caseId"],
                       manifest_sha256=approved["manifestSha256"],
                       approval_token=approved["approvalToken"], actor="admin-b",
                       tables=tables, transact_write=action, audit=audit)
    assert result["identityClaimsReleased"] is True
    assert result["contactRecreatable"] is True
    assert result["providerCopiesErased"] is False
    assert "subject-a" not in tables["ContactsTable"].items
    assert not tables["IdentityClaimsTable"].items
    assert len(calls) == 1
    assert [x["action"] for x in logs] == [
        "contact.erasure_prepare", "contact.erasure_approve", "contact.erasure_execute"]


def test_same_admin_cannot_approve():
    tables, audit, _ = setup()
    p = m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
    try:
        m.approve(case_id=p["caseId"], actor="admin-a", tables=tables, audit=audit)
        assert False
    except m.Refused as exc:
        assert exc.code == "ERASURE_SECOND_REVIEWER_REQUIRED"


def test_dependencies_providers_and_locks_fail_closed():
    for options, code in (
        ({"has_message": True}, "ERASURE_DEPENDENCY_RETAINED"),
        ({"paid": True}, "ERASURE_DEPENDENCY_RETAINED"),
        ({"legal": True}, "CONTACT_LOCKED"),
        ({"source_identity": True}, "ERASURE_EXTERNAL_IDENTITY_REVIEW_REQUIRED"),
        ({"phone": True}, "ERASURE_EXTERNAL_IDENTITY_REVIEW_REQUIRED"),
        ({"held": True}, "CONTACT_HAS_HISTORY"),
    ):
        tables, audit, _ = setup(**options)
        try:
            m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
            assert False
        except m.Refused as exc:
            assert exc.code == code
        assert tables["ContactsTable"].items


def test_bad_token_cannot_execute():
    tables, audit, _ = setup()
    p = m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
    approved = m.approve(case_id=p["caseId"], actor="admin-b", tables=tables, audit=audit)
    action, calls = transact(tables)
    try:
        m.execute(contact_id="subject-a", case_id=p["caseId"],
                  manifest_sha256=approved["manifestSha256"],
                  approval_token="unapproved", actor="admin-b",
                  tables=tables, transact_write=action, audit=audit)
        assert False
    except m.Refused as exc:
        assert exc.code == "ERASURE_APPROVAL_INVALID"
    assert calls == []


def test_contact_change_invalidates_review():
    tables, audit, _ = setup()
    p = m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
    tables["ContactsTable"].items["subject-a"]["email"] = "new@example.org"
    try:
        m.approve(case_id=p["caseId"], actor="admin-b", tables=tables, audit=audit)
        assert False
    except m.Refused as exc:
        assert exc.code == "ERASURE_SNAPSHOT_CHANGED"


def test_unreadable_dependency_refuses():
    tables, audit, _ = setup()
    del tables["InvoicesTable"]
    try:
        m.prepare(contact_id="subject-a", actor="admin-a", tables=tables, audit=audit)
        assert False
    except m.Refused as exc:
        assert exc.code == "ERASURE_INVENTORY_INCOMPLETE"
