"""Eligible local message deletion is exact-key and preserves retention evidence."""
from lambda_utils.erasure.inbox_delete import delete_visible_message


class MemoryTable:
    def __init__(self, rows=(), *, fail_delete=False, bad_scan=False):
        self.rows = {row["id"]: dict(row) for row in rows if "id" in row}
        self.meta = {row["conversationId"]: dict(row) for row in rows if "conversationId" in row}
        self.deleted = []
        self.fail_delete = fail_delete
        self.bad_scan = bad_scan

    def get_item(self, Key, **kwargs):
        if "id" in Key:
            row = self.rows.get(Key["id"])
        else:
            row = self.meta.get(Key["conversationId"])
        return {"Item": dict(row)} if row else {}

    def scan(self, **kwargs):
        if self.bad_scan:
            return {"Count": 0}
        cid = kwargs["ExpressionAttributeValues"][":cid"]
        return {"Items": [dict(row) for row in self.rows.values()
                          if row.get("contactId") == cid]}

    def delete_item(self, Key, **kwargs):
        if self.fail_delete:
            raise RuntimeError("delete write failed")
        row = self.rows.get(Key["id"])
        if not row or row.get("contactId") != kwargs["ExpressionAttributeValues"][":cid"]:
            raise RuntimeError("conditional conflict")
        self.deleted.append(Key["id"])
        del self.rows[Key["id"]]

    def query(self, **kwargs):
        values = kwargs.get("ExpressionAttributeValues", {})
        target = next(iter(values.values()), None)
        condition = kwargs.get("KeyConditionExpression", "")
        key = condition.split(" = ")[0]
        return {"Items": [dict(row) for row in self.rows.values()
                          if row.get(key) == target]}


def fixtures(*, content="Hello", media=False, contact_lock="created", held=False,
             financial=False, source_contact="person-c", fail_source=False,
             fail_audit=False):
    row = {"id": "message-1", "contactId": "person-c", "channel": "whatsapp",
           "direction": "INBOUND", "content": content, "messageType": "text"}
    if media:
        row["s3Key"] = "secure/stack/message-a"
    source = {**row, "contactId": source_contact}
    table = MemoryTable([row])
    inbound = MemoryTable([source], fail_delete=fail_source)
    outbound = MemoryTable([])
    contact = MemoryTable([
        {"id": "person-c", "phone": "", "locked": True,
         "lockedReason": contact_lock}
    ])
    metadata = MemoryTable([
        {"conversationId": "person-c", "tags": ["retention-hold"] if held else []}
    ])
    invoices = MemoryTable([
        {"id": "invoice-1", "contactId": "person-c", "paymentId": "pay-1"}
    ] if financial else [])
    orders = MemoryTable([])
    calls = []

    def audit(**kwargs):
        calls.append(kwargs)
        return None if fail_audit else "audit-example"

    args = dict(message_id="message-1", actor="admin-1",
                canonical_table=table, inbound_table=inbound,
                outbound_table=outbound, contacts_table=contact,
                meta_table=metadata, invoices_table=invoices,
                orders_table=orders, audit=audit)
    return args, calls


def test_text_message_removes_canonical_and_matching_source_only():
    args, calls = fixtures()
    result = delete_visible_message(**args)
    assert result.status == 200
    assert result.body["rowDeleted"] is True
    assert result.body["sourceRowDeleted"] is True
    assert result.body["erasureComplete"] is False
    assert "message-1" not in args["canonical_table"].rows
    assert "message-1" not in args["inbound_table"].rows
    assert len(calls) == 1
    assert calls[0]["action"] == "messages.delete_local_inbox"


def test_protected_conversation_does_not_mutate_any_table():
    args, calls = fixtures(held=True)
    result = delete_visible_message(**args)
    assert result.status == 409
    assert result.body["errorCode"] == "MESSAGE_RETENTION_HOLD"
    assert "message-1" in args["canonical_table"].rows
    assert "message-1" in args["inbound_table"].rows
    assert calls == []


def test_financial_message_and_paid_contact_are_preserved():
    for option in ({"content": "Razorpay refund receipt"},
                   {"financial": True}):
        args, calls = fixtures(**option)
        result = delete_visible_message(**args)
        assert result.status == 409
        assert result.body["errorCode"] == "MESSAGE_FINANCIAL_RETENTION"
        assert args["canonical_table"].rows
        assert calls == []


def test_non_default_legal_lock_is_retained():
    args, calls = fixtures(contact_lock="legal-hold")
    assert delete_visible_message(**args).body["errorCode"] == "MESSAGE_CONTACT_LOCKED"
    assert calls == []


def test_media_is_not_deleted_without_exact_s3_version_review():
    args, calls = fixtures(media=True)
    result = delete_visible_message(**args)
    assert result.body["errorCode"] == "MESSAGE_MEDIA_REVIEW_REQUIRED"
    assert calls == []


def test_source_contact_conflict_cannot_delete_wrong_identity():
    args, calls = fixtures(source_contact="person-other")
    result = delete_visible_message(**args)
    assert result.body["errorCode"] == "MESSAGE_SOURCE_IDENTITY_CONFLICT"
    assert calls == []


def test_unavailable_audit_does_not_allow_delete():
    args, calls = fixtures(fail_audit=True)
    result = delete_visible_message(**args)
    assert result.status == 503
    assert result.body["errorCode"] == "MESSAGE_DELETE_AUDIT_UNAVAILABLE"
    assert args["canonical_table"].rows


def test_source_write_failure_preserves_canonical_retry_point():
    args, calls = fixtures(fail_source=True)
    result = delete_visible_message(**args)
    assert result.status == 503
    assert result.body["erasureComplete"] is False
    assert args["canonical_table"].rows


def test_scan_failure_never_assumes_no_financial_context():
    args, calls = fixtures()
    args["canonical_table"].bad_scan = True
    result = delete_visible_message(**args)
    assert result.body["errorCode"] == "MESSAGE_DELETE_INVENTORY_UNAVAILABLE"
    assert calls == []


def test_missing_actor_and_missing_canonical_identity_refused():
    args, _ = fixtures()
    args["actor"] = ""
    assert delete_visible_message(**args).status == 400
    args["actor"] = "admin-1"
    args["canonical_table"].rows = {}
    assert delete_visible_message(**args).status == 404
