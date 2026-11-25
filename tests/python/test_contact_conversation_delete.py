"""Delete conversation + contact: only verified customers, payments and legal holds refuse."""
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from lambda_utils.erasure import contact_conversation_delete as ccd
from lambda_utils.erasure import inbox_delete

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

CID = "wa919999900001"
PHONE = "+919999900001"


class Table:
    def __init__(self, rows=(), pk="id", fail_delete_on=None, bad_query=False):
        self.pk = pk
        self.rows = {r[pk]: dict(r) for r in rows}
        self.fail_delete_on = fail_delete_on
        self.bad_query = bad_query
        self.deleted = []
        self.updates = []

    def _check_condition(self, row, kwargs, operation):
        condition = kwargs.get("ConditionExpression", "")
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        parts = condition.split(" AND ") if condition else []
        for part in parts:
            target = re.fullmatch(r"attribute_(exists|not_exists)\((#[a-z0-9]+)\)", part)
            if target:
                exists = bool(row and names[target[2]] in row)
                matched = exists if target[1] == "exists" else not exists
            else:
                field, val = (x.strip() for x in part.split("="))
                field = names.get(field, field)
                matched = bool(row and field in row and row[field] == values[val])
            if not matched:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}},
                                  operation)

    def update_item(self, Key, UpdateExpression, **kw):
        row = self.rows.get(Key[self.pk])
        self._check_condition(row, kw, "UpdateItem")
        verb, expr = UpdateExpression.split(" ", 1)
        names = kw["ExpressionAttributeNames"]
        if verb == "SET":
            lhs, rhs = expr.split(" = ")
            row[names[lhs]] = dict(kw["ExpressionAttributeValues"][rhs])
        elif verb == "REMOVE":
            del row[names[expr]]
        else:
            raise AssertionError(verb)
        self.updates.append(UpdateExpression)

    def get_item(self, Key, **kw):
        row = self.rows.get(Key[self.pk])
        return {"Item": dict(row)} if row else {}

    def scan(self, **kw):
        cid = kw["ExpressionAttributeValues"][":cid"]
        return {"Items": [dict(r) for r in self.rows.values() if r.get("contactId") == cid]}

    def query(self, **kw):
        if self.bad_query:
            raise RuntimeError("query unavailable")
        target = next(iter(kw["ExpressionAttributeValues"].values()))
        field = kw["KeyConditionExpression"].split(" = ")[0]
        return {"Items": [dict(r) for r in self.rows.values() if r.get(field) == target]}

    def delete_item(self, Key, **kw):
        if self.fail_delete_on and Key[self.pk] == self.fail_delete_on:
            raise RuntimeError("delete failed")
        self._check_condition(self.rows.get(Key[self.pk]), kw, "DeleteItem")
        self.rows.pop(Key[self.pk], None)
        self.deleted.append(Key[self.pk])


def build(*, contact=None, messages=None, invoices=(), orders=(), meta=True,
          claims=True, fail_audit=False, fail_message=None, bad_invoices=False):
    base = {"id": CID, "phone": PHONE, "locked": True, "lockedReason": "created",
            "tags": [], "lastInboundMessageAt": 1}
    base.update(contact or {})
    msgs = messages if messages is not None else [
        {"id": "m1", "contactId": CID, "direction": "INBOUND", "content": "Hello",
         "messageType": "text"},
        {"id": "m2", "contactId": CID, "direction": "INBOUND", "content": "photo",
         "messageType": "image", "s3Key": "secure/stack/whatsapp-media/a.jpg"},
    ]
    audits, media = [], []
    claim_rows = []
    if claims:
        claim_rows = [
            {"claimKey": "PHONE#" + PHONE, "contactId": CID},
            {"claimKey": "WHATSAPP_BSUID#portfolio1#BS.1", "contactId": CID},
        ]
        base.setdefault("whatsappIdentities", {"portfolio1": {"bsuid": "BS.1"}})
    args = dict(
        contact_id=CID, actor="admin-1",
        canonical_table=Table(msgs, fail_delete_on=fail_message),
        inbound_table=Table([dict(m, id="src-" + m["id"]) for m in msgs
                             if m["direction"] == "INBOUND"]),
        outbound_table=Table([]),
        contacts_table=Table([base]),
        meta_table=Table([{"conversationId": CID, "tags": []}] if meta else [],
                         pk="conversationId"),
        claims_table=Table(claim_rows, pk="claimKey"),
        invoices_table=Table(invoices, bad_query=bad_invoices),
        orders_table=Table(orders),
        delete_media=lambda key: media.append(key) or True,
        extra_tables={"scheduled": (Table([{"id": "s1", "contactId": CID}]), ("id",))},
    )

    def audit(**kw):
        audits.append(kw)
        return None if fail_audit else "audit-1"

    args["audit"] = audit
    return args, audits, media


def untouched(args):
    return (CID in args["contacts_table"].rows and len(args["canonical_table"].rows) == 2
            and not args["canonical_table"].deleted)


def test_plain_unverified_contact_is_fully_removed_and_recreatable():
    args, audits, media = build()
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 200
    body = out.body
    assert body["contactDeleted"] is True and body["messagesDeleted"] == 2
    assert body["mediaObjectsDeleted"] == 1 and body["contactRecreatable"] is True
    assert body["identityClaimsReleased"] is True and body["auditId"] == "audit-1"
    assert body["providerCopiesErased"] is False
    assert media == ["secure/stack/whatsapp-media/a.jpg"]
    assert not args["contacts_table"].rows
    assert not args["canonical_table"].rows and not args["inbound_table"].rows
    assert not args["meta_table"].rows and not args["claims_table"].rows
    assert not args["extra_tables"]["scheduled"][0].rows
    assert audits[0]["action"] == "contact.delete_with_conversation"


def test_unconverted_contact_with_long_history_is_deletable():
    msgs = [{"id": f"m{i}", "contactId": CID, "direction": "OUTBOUND",
             "content": "hi", "messageType": "text"} for i in range(30)]
    args, _, _ = build(messages=msgs)
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 200 and out.body["messagesDeleted"] == 30


@pytest.mark.parametrize("text", ["what is the fee?", "booking for Saturday",
                                  "amount? can I pay in INR \u20b9500"])
def test_unconverted_lead_mentioning_fee_or_booking_is_deletable(text):
    msgs = [{"id": "m1", "contactId": CID, "direction": "INBOUND",
             "content": text, "messageType": "text"}]
    args, _, _ = build(messages=msgs)
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 200 and not args["contacts_table"].rows


def assert_no_destructive_writes(args, media):
    assert not media
    for name in ("contacts_table", "canonical_table", "inbound_table",
                 "outbound_table", "meta_table", "claims_table"):
        assert not args[name].deleted, name
    assert not args["extra_tables"]["scheduled"][0].deleted


@pytest.mark.parametrize("reason", ["Created", "CREATED", " created "])
def test_noncanonical_creation_lock_refuses_before_any_effect(reason):
    args, audits, media = build(contact={"lockedReason": reason})
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 409 and out.body["errorCode"] == "CONTACT_DELETE_LOCKED"
    assert audits == [] and args["contacts_table"].updates == []
    assert_no_destructive_writes(args, media)


def test_eligibility_change_during_reservation_does_not_allow_any_effect():
    args, _, media = build()
    original_audit = args["audit"]

    def audit(**kw):
        args["contacts_table"].rows[CID]["cognitoSub"] = "newly-verified"
        return original_audit(**kw)

    args["audit"] = audit
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 409 and out.body["errorCode"] == "CONTACT_DELETE_STATE_CHANGED"
    assert args["contacts_table"].updates == []
    assert_no_destructive_writes(args, media)


def test_hold_added_before_first_effect_refuses_and_relinquishes_reservation():
    args, _, media = build()
    table = args["contacts_table"]
    update = table.update_item

    def with_new_hold(**kw):
        update(**kw)
        if len(table.updates) == 1:
            args["meta_table"].rows[CID]["tags"] = ["retention-hold"]

    table.update_item = with_new_hold
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 409 and out.body["errorCode"] == "CONTACT_DELETE_RETENTION_HOLD"
    assert ccd._RESERVATION not in table.rows[CID]
    assert_no_destructive_writes(args, media)


def test_verification_during_effects_stops_before_message_or_claim_deletes():
    args, _, _ = build()

    def media(_):
        assert args["contacts_table"].rows[CID][ccd._RESERVATION]["started"] is True
        args["contacts_table"].rows[CID]["fieldSources"] = {"phone": "PAYMENT_VERIFIED"}
        return True

    args["delete_media"] = media
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 503 and out.body["errorCode"] == "CONTACT_DELETE_INCOMPLETE"
    assert CID in args["contacts_table"].rows
    assert_no_destructive_writes(args, [])
    assert args["contacts_table"].rows[CID][ccd._RESERVATION]["expiresAt"] == 0


def test_second_invocation_cannot_make_destructive_writes_during_reservation():
    args, audits, _ = build()
    nested = []

    def media(_):
        nested.append(ccd.delete_contact_conversation(**args))
        return True

    args["delete_media"] = media
    result = ccd.delete_contact_conversation(**args)
    assert result.status == 200
    assert len(audits) == 1 and len(nested) == 1
    assert nested[0].status == 409
    assert nested[0].body["errorCode"] == "CONTACT_DELETE_IN_PROGRESS"


def test_straggler_before_final_check_keeps_contact_and_rerun_cleans_up():
    args, _, _ = build()
    canonical, injected = args["canonical_table"], []

    def media(key):
        if not injected:
            injected.append(1)
            canonical.rows["late"] = {"id": "late", "contactId": CID,
                                      "direction": "INBOUND", "content": "hi"}
        return True

    args["delete_media"] = media
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 503 and out.body["errorCode"] == "CONTACT_DELETE_INCOMPLETE"
    assert out.body["contactDeleted"] is False and CID in args["contacts_table"].rows
    again = ccd.delete_contact_conversation(**args)
    assert again.status == 200 and not canonical.rows and not args["contacts_table"].rows


@pytest.mark.parametrize("fields", [
    {"checkoutCustomerId": "sub-1"}, {"cognitoSub": "sub-1"},
    {"phoneVerifiedAt": 5}, {"identityClaimedAt": 5},
    {"fieldSources": {"phone": "PAYMENT_VERIFIED"}},
])
def test_verified_customer_refused(fields):
    args, audits, _ = build(contact=fields)
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 409 and out.body["errorCode"] == "CONTACT_DELETE_VERIFIED_CUSTOMER"
    assert out.body["contactDeleted"] is False and audits == [] and untouched(args)


def test_bsuid_and_inbound_activity_do_not_count_as_verified():
    args, _, _ = build(contact={"bsuid": "BS.1", "lastInboundMessageAt": 99,
                                "emailVerifiedAt": 3})
    assert ccd.delete_contact_conversation(**args).status == 200


@pytest.mark.parametrize("message", [
    {"paymentReferenceId": "pay_1"}, {"invoiceId": "inv_1"}, {"paymentAmount": 500},
])
def test_payment_messages_refused(message):
    msgs = [{"id": "m1", "contactId": CID, "direction": "INBOUND",
             "content": "Hello", "messageType": "text", **message},
            {"id": "m2", "contactId": CID, "direction": "INBOUND",
             "content": "x", "messageType": "text"}]
    args, audits, _ = build(messages=msgs)
    out = ccd.delete_contact_conversation(**args)
    assert out.body["errorCode"] == "CONTACT_DELETE_FINANCIAL_RETENTION"
    assert audits == [] and CID in args["contacts_table"].rows


def test_invoice_and_order_linkage_refused():
    args, audits, _ = build(invoices=[{"id": "i1", "contactId": CID, "paymentId": "pay_1"}])
    assert ccd.delete_contact_conversation(**args).body["errorCode"] == \
        "CONTACT_DELETE_FINANCIAL_RETENTION"
    args, audits, _ = build(contact={"checkoutCustomerIdX": "1"},
                            orders=[{"id": "o1", "customerPhone": PHONE}])
    out = ccd.delete_contact_conversation(**args)
    assert out.body["errorCode"] == "CONTACT_DELETE_FINANCIAL_RETENTION" and audits == []


def test_unreadable_linkage_refused():
    args, audits, _ = build(bad_invoices=True)
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 503 and out.body["errorCode"] == "CONTACT_DELETE_LINKAGE_UNKNOWN"
    assert audits == [] and CID in args["contacts_table"].rows


def test_legal_lock_and_retention_hold_refused_but_created_lock_allowed():
    args, _, _ = build(contact={"lockedReason": "legal-hold"})
    assert ccd.delete_contact_conversation(**args).body["errorCode"] == "CONTACT_DELETE_LOCKED"
    args, _, _ = build(contact={"tags": ["retention-hold"]})
    assert ccd.delete_contact_conversation(**args).body["errorCode"] == \
        "CONTACT_DELETE_RETENTION_HOLD"
    args, _, _ = build()
    args["meta_table"].rows[CID]["tags"] = ["retention-hold"]
    assert ccd.delete_contact_conversation(**args).body["errorCode"] == \
        "CONTACT_DELETE_RETENTION_HOLD"
    args, _, _ = build(contact={"lockedReason": "created"})
    assert ccd.delete_contact_conversation(**args).status == 200


def test_missing_contact_is_404_and_audit_failure_deletes_nothing():
    args, _, _ = build()
    args["contacts_table"].rows.clear()
    assert ccd.delete_contact_conversation(**args).status == 404
    args, audits, media = build(fail_audit=True)
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 503 and out.body["errorCode"] == "CONTACT_DELETE_AUDIT_UNAVAILABLE"
    assert untouched(args) and media == [] and len(args["claims_table"].rows) == 2


def test_mid_way_failure_keeps_contact_and_rerun_completes():
    args, audits, _ = build(fail_message="m2")
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 503 and out.body["errorCode"] == "CONTACT_DELETE_INCOMPLETE"
    assert out.body["contactDeleted"] is False
    pending = args["contacts_table"].rows[CID][ccd._RESERVATION]
    assert pending["started"] is True and pending["expiresAt"] == 0
    assert pending["auditId"] == "audit-1"
    args["canonical_table"].fail_delete_on = None
    again = ccd.delete_contact_conversation(**args)
    assert again.status == 200 and not args["contacts_table"].rows
    assert audits[-1]["details"]["priorAuditId"] == "audit-1"


def test_foreign_claim_is_not_released_and_non_message_media_skipped():
    args, _, media = build(messages=[
        {"id": "m1", "contactId": CID, "direction": "INBOUND", "content": "hi",
         "messageType": "text", "s3Key": "o/catalog/x.png"}])
    args["claims_table"].rows["PHONE#" + PHONE]["contactId"] = "someone-else"

    def delete_media(key):
        raise ValueError("outside message storage")

    args["delete_media"] = delete_media
    out = ccd.delete_contact_conversation(**args)
    assert out.status == 200 and out.body["mediaObjectsDeleted"] == 0
    assert "PHONE#" + PHONE in args["claims_table"].rows
    assert "WHATSAPP_BSUID#portfolio1#BS.1" not in args["claims_table"].rows


def test_deleted_number_finds_no_contact_or_claim_for_a_new_inbound():
    args, _, _ = build()
    ccd.delete_contact_conversation(**args)
    assert args["contacts_table"].get_item(Key={"id": CID}) == {}
    for key in ("PHONE#" + PHONE, "WHATSAPP_BSUID#portfolio1#BS.1"):
        assert args["claims_table"].get_item(Key={"claimKey": key}) == {}


# ---- handler level -------------------------------------------------------------------
SOURCE = Path(__file__).resolve().parents[2] / "amplify/functions/core/messages-delete/handler.py"
SPEC = importlib.util.spec_from_file_location("messages_delete_contact_scope", SOURCE)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)
MARKER = "__canonical_contact_v1__:"


def request(message_id, scope="contact"):
    return {"requestContext": {"http": {"method": "DELETE", "path": "/messages/x"}},
            "queryStringParameters": {"scope": scope},
            "pathParameters": {"messageId": message_id}}


@pytest.fixture
def invoke(monkeypatch):
    import lambda_utils.middleware as middleware

    auth = {"role": "Admin", "mfaEnrolled": True, "username": "synthetic-admin"}
    calls = []

    def permit(event, required_role=None):
        event["_auth"] = dict(auth)
        return None

    class Db:
        def Table(self, name):
            return object()

    def fake(**kwargs):
        calls.append(kwargs)
        return inbox_delete.DeleteDecision(200, {"success": True, "contactDeleted": True})

    monkeypatch.setattr(middleware, "require_auth", permit)
    monkeypatch.setattr(ccd, "delete_contact_conversation", fake)
    monkeypatch.setattr(HANDLER, "dynamodb", Db())
    monkeypatch.setattr(HANDLER, "_get_key_schema",
                        lambda name: [{"AttributeName": "id", "KeyType": "HASH"}])
    return auth, calls


def run(event):
    resp = HANDLER.handler(event, None)
    return int(resp["statusCode"]), json.loads(resp["body"])


def test_handler_requires_contact_marker(invoke):
    _, calls = invoke
    assert run(request(CID))[0] == 400
    assert run(request("__canonical_inbox_v1__:" + CID))[0] == 400
    assert run(request(MARKER + MARKER + CID))[0] == 400
    assert calls == []


def test_handler_contact_marker_reaches_delete(invoke):
    _, calls = invoke
    status, body = run(request(MARKER + CID))
    assert status == 200 and body["contactDeleted"] is True
    assert calls[0]["contact_id"] == CID and calls[0]["actor"] == "synthetic-admin"


def test_handler_requires_admin_mfa_and_actor(invoke):
    auth, calls = invoke
    auth["mfaEnrolled"] = False
    assert run(request(MARKER + CID))[0] == 403
    auth["mfaEnrolled"] = True
    auth.pop("username")
    assert run(request(MARKER + CID))[0] == 403
    assert calls == []


def test_inbox_scope_still_needs_inbox_marker_and_contact_marker_rejected(invoke):
    _, calls = invoke
    assert run(request(MARKER + CID, scope="inbox"))[0] == 400
    assert run(request(CID, scope="bogus"))[0] == 400
    assert calls == []


def test_handler_contact_delete_refuses_noncanonical_lock_before_any_effect(monkeypatch):
    import lambda_utils.middleware as middleware
    from lambda_utils import identity_claims

    args, audits, media = build(contact={"lockedReason": "Created"})
    tables = {
        HANDLER.INBOUND_TABLE: args["inbound_table"],
        HANDLER.OUTBOUND_TABLE: args["outbound_table"],
        identity_claims.TABLE_NAME: args["claims_table"],
    }
    # The handler is exercised without a stub for the deletion policy itself.
    for env, default, arg in (
        ("MESSAGES_TABLE", "MessagesTable", "canonical_table"),
        ("CONTACTS_TABLE", "ContactsTable", "contacts_table"),
        ("CONVERSATION_META_TABLE", "ConversationMetaTable", "meta_table"),
        ("INVOICES_TABLE", "InvoicesTable", "invoices_table"),
        ("ORDERS_TABLE", "OrderTable", "orders_table"),
        ("SCHEDULED_TABLE", "ScheduledMessagesTable", None),
    ):
        table = args[arg] if arg else args["extra_tables"]["scheduled"][0]
        tables[os.environ.get(env, "stack-wecare-digital-" + default)] = table

    class Db:
        def Table(self, name):
            return tables[name]

    def permit(event, required_role=None):
        event["_auth"] = {
            "role": "Admin", "mfaEnrolled": True, "username": "synthetic-admin",
        }

    monkeypatch.setattr(middleware, "require_auth", permit)
    monkeypatch.setattr(HANDLER, "dynamodb", Db())
    monkeypatch.setattr(HANDLER, "_get_key_schema", lambda name: [{"AttributeName": "id"}])
    monkeypatch.setattr(HANDLER, "record_audit", args["audit"])
    monkeypatch.setattr(HANDLER, "_find_and_delete_s3_file", lambda key, _: args["delete_media"](key))

    status, body = run(request(MARKER + CID))
    assert status == 409 and body["errorCode"] == "CONTACT_DELETE_LOCKED"
    assert audits == [] and args["contacts_table"].updates == []
    assert_no_destructive_writes(args, media)
