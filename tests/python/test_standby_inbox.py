"""Regression coverage for read-only AI standby -> Unified Inbox projection."""

import os

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

from lambda_utils import standby_inbox, thread_ownership


class Table:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = 0

    def get_item(self, *, Key, ConsistentRead=False):
        key = next(iter(Key.values()))
        return {"Item": self.items[key]} if key in self.items else {}

    def query(self, *, IndexName, KeyConditionExpression, Limit=2):
        if IndexName != "whatsappMessageId-index":
            raise ValueError("unexpected index")
        wamid = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": [item for item in self.items.values()
                          if item.get("whatsappMessageId") == wamid][:Limit]}

    def put_item(self, *, Item, ConditionExpression=None):
        if Item["id"] in self.items:
            raise AssertionError("duplicate row must not overwrite an existing row")
        self.items[Item["id"]] = Item
        self.puts += 1
        return {}


class Db:
    def __init__(self, claims=None, contacts=None):
        self.tables = {
            standby_inbox.MESSAGES_TABLE: Table(),
            standby_inbox.CLAIMS_TABLE: Table(claims),
            standby_inbox.CONTACTS_TABLE: Table(contacts),
        }

    def Table(self, name):
        return self.tables[name]


PHONE_ID = "1055232054343117"
PORTFOLIO = "125951953587391"
BSUID = "IN.test-scoped-bsuid"
WAMID = "wamid.12345"


def message():
    return {"id": WAMID, "timestamp": "1795100000", "type": "text", "text": {"body": "hello"}}


def test_verified_claim_attaches_only_exact_business_contact():
    contact_id = "C-EXAMPLE-01"
    contact = {
        "id": contact_id,
        "contactId": contact_id,
        "name": "Verified example",
        "phone": "+919123450001",
        "whatsappIdentities": {PORTFOLIO: {"bsuid": BSUID}},
    }
    claim_key = f"WHATSAPP_BSUID#{PORTFOLIO}#{BSUID}"
    db = Db(claims={claim_key: {"contactId": contact_id}}, contacts={contact_id: contact})

    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message=message(), content="hello", resource=db)
    rows = list(db.Table(standby_inbox.MESSAGES_TABLE).items.values())
    assert len(rows) == 1
    assert rows[0]["contactId"] == contact_id
    assert rows[0]["senderPhone"] == contact["phone"]
    assert rows[0]["standbySourced"] is True
    assert rows[0]["replyAllowed"] is False
    assert rows[0]["routingOwner"] == "ai_agent"
    assert rows[0]["content"] == "hello"
    assert rows[0]["channel"] == "whatsapp"


def test_legacy_or_unverified_bsuid_never_guesses_contact():
    wrong_portfolio = "382642103987922"
    other_key = f"WHATSAPP_BSUID#{wrong_portfolio}#{BSUID}"
    db = Db(claims={other_key: {"contactId": "ANOTHER-PERSON"}})

    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message=message(), content="hello", resource=db)
    row = next(iter(db.Table(standby_inbox.MESSAGES_TABLE).items.values()))
    assert row["contactId"].startswith("wa-standby:")
    assert "senderPhone" not in row
    assert row["replyAllowed"] is False
    assert row["senderName"].startswith("WhatsApp contact #")


def test_signed_meta_profile_name_displays_without_merging_customer():
    db = Db()
    assert standby_inbox.mirror(
        PHONE_ID, bsuid=BSUID, message=message(), sender_name="  Priya Kumar  ",
        content="hello", resource=db
    )
    row = next(iter(db.Table(standby_inbox.MESSAGES_TABLE).items.values()))
    assert row["senderName"] == "Priya Kumar"
    assert row["contactId"].startswith("wa-standby:")
    assert "senderPhone" not in row
    assert row["replyAllowed"] is False


def test_standby_contact_name_requires_exact_message_identity():
    contacts = [
        {"user_id": BSUID, "wa_id": "919000000001", "profile": {"name": "First Person"}},
        {"user_id": "IN.other", "wa_id": "919000000002", "profile": {"name": "Second Person"}},
    ]
    assert standby_inbox.profile_name_from_contacts(
        {"from_user_id": BSUID}, contacts
    ) == "First Person"
    assert standby_inbox.profile_name_from_contacts(
        {"from": "919000000002"}, contacts
    ) == "Second Person"
    assert standby_inbox.profile_name_from_contacts(
        {"from_user_id": "IN.missing"}, contacts
    ) == ""
    assert standby_inbox.profile_name_from_contacts(
        {"from_user_id": BSUID, "from": "919000000002"}, contacts
    ) == ""
    assert standby_inbox.profile_name_from_contacts(
        {}, [contacts[0]]
    ) == ""
    assert standby_inbox.profile_name_from_contacts(
        {"from": "919000000001"}, [{"wa_id": "919000000001", "profile": {"name": "  Alex   Shah  "}}]
    ) == "Alex Shah"


def test_a_different_existing_message_does_not_suppress_new_wamid():
    db = Db()
    table = db.Table(standby_inbox.MESSAGES_TABLE)
    table.items["existing-message"] = {
        "id": "existing-message",
        "whatsappMessageId": "wamid.other-message",
        "content": "old",
    }
    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message=message(), content="new", resource=db)
    assert len(table.items) == 2
    assert table.puts == 1
    assert any(row.get("whatsappMessageId") == WAMID for row in table.items.values())


def test_retries_do_not_create_duplicate_messages_or_replies():
    db = Db()
    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message=message(), content="hello", resource=db)
    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message=message(), content="hello", resource=db)
    table = db.Table(standby_inbox.MESSAGES_TABLE)
    assert table.puts == 1
    assert len(table.items) == 1
    assert "senderPhone" not in next(iter(table.items.values()))


def test_invalid_identity_is_rejected_before_database_access():
    assert standby_inbox.mirror(PHONE_ID, bsuid="", wa_id="", message=message(), resource=Db()) is False
    assert standby_inbox.mirror(PHONE_ID, bsuid=BSUID, message={"type": "text"}, resource=Db()) is False


def test_standby_context_remains_available_if_inbox_projection_fails(monkeypatch):
    class ContextTable:
        def __init__(self):
            self.rows = []

        def put_item(self, *, Item):
            self.rows.append(Item)
            return {}

    table = ContextTable()
    monkeypatch.setattr(standby_inbox, "mirror", lambda *args, **kwargs: False)
    thread_ownership.set_table(table)
    try:
        assert thread_ownership.store_standby_message(
            PHONE_ID, bsuid=BSUID, message=message(), content="hello", now=1795100001
        ) is True
        assert table.rows[0]["recordType"].startswith("SB#")
    finally:
        thread_ownership.set_table(None)
