"""Exercise the real, extracted portfolio-BSUID claim functions without AWS writes.

The inbound handler imports many AWS clients and Flow modules at import time, so
these tests compile only the three pure/DynamoDB-facing functions under test,
then inject an in-memory contract-level fake. This is not a cloud integration
test: staging verification remains necessary before Lambda promotion.
"""
import ast
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

import pytest
from botocore.exceptions import ClientError


HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py")
WECARE = "2094615664435155"
MANISH = "2513394156072604"
WECARE_PORTFOLIO = "382642103987922"
MANISH_PORTFOLIO = "125951953587391"


class Conflict(RuntimeError):
    def __init__(self, label, owners):
        super().__init__(label)
        self.label = label


def conditional():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}},
                       "UpdateItem")


class FakeClaims:
    def __init__(self):
        self.rows = {}

    def get_item(self, *, Key, ConsistentRead):
        item = self.rows.get(Key["claimKey"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, *, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeValues):
        key = Key["claimKey"]
        owner = ExpressionAttributeValues[":cid"]
        old = self.rows.get(key)
        if old and old["contactId"] != owner:
            raise conditional()
        self.rows[key] = {"contactId": owner}


class FakeContacts:
    def __init__(self, *rows):
        self.rows = {row["id"]: row for row in rows}
        self.writes = 0

    def update_item(self, *, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeNames, ExpressionAttributeValues):
        row = self.rows[Key["id"]]
        self.writes += 1
        if "if_not_exists(#profiles" in UpdateExpression:
            row.setdefault("whatsappIdentities", {})
            return {}
        business = ExpressionAttributeNames["#business"]
        profiles = row["whatsappIdentities"]
        old = profiles.get(business)
        values = ExpressionAttributeValues
        if ":previous" in values:
            if old is None or old["bsuid"] != values[":previous"]:
                raise conditional()
        elif old and old["bsuid"] != values[":bsuid"]:
            raise conditional()
        profiles[business] = dict(values[":entry"])
        return {}


class FakeContactStore:
    IdentityConflict = Conflict

    def __init__(self, contacts):
        self.contacts = contacts

    def canonical_phone(self, phone):
        digits = "".join(c for c in str(phone or "") if c.isdigit())
        return "+" + digits if digits else ""

    def lookup(self, table, *, contact_id):
        return table.rows.get(contact_id)

    def find_by_bsuid(self, table, bsuid):
        matches = [row for row in table.rows.values()
                   if row.get("bsuid") == bsuid]
        if len(matches) > 1:
            raise Conflict("duplicate-legacy", ())
        return matches[0] if matches else None


def helpers(*contacts):
    db = FakeContacts(*contacts)
    claims = FakeClaims()
    store = FakeContactStore(db)
    allowed = {WECARE: WECARE_PORTFOLIO, MANISH: MANISH_PORTFOLIO}
    ast_root = ast.parse(HANDLER.read_text(encoding="utf-8"))
    names = {"_portfolio_scope", "_message_account_id", "_scoped_bsuid_key",
             "_find_scoped_bsuid", "_attach_scoped_bsuid"}
    nodes = [n for n in ast_root.body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    stub = SimpleNamespace(Table=lambda _name: claims)
    send = SimpleNamespace(waba_for_meta_phone=lambda phone_id: {
        "1016149501586345": WECARE,
        "1055232054343117": MANISH,
    }.get(phone_id, ""))
    env = {
        "__builtins__": __builtins__,
        "Dict": Dict,
        "Optional": Optional,
        "Decimal": Decimal,
        "ClientError": ClientError,
        "time": time,
        "_WABA_PORTFOLIOS": allowed,
        "direct_send": send,
        "contact_store": store,
        "contact_key": SimpleNamespace(resolve=lambda row: row.get("id", "")),
        "identity_claims": SimpleNamespace(TABLE_NAME="Claims"),
        "dynamodb": stub,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(HANDLER), "exec"), env)
    return SimpleNamespace(db=db, claims=claims, store=store, **{
        name: env[name] for name in names
    })


def test_two_businesses_have_distinct_scoped_claims_for_same_meta_user_id():
    h = helpers({"id": "contact-a"}, {"id": "contact-b"})
    bsuid = "IN.123456789"
    h._attach_scoped_bsuid(h.db, h.db.rows["contact-a"],
                           waba_id=WECARE, bsuid=bsuid)
    h._attach_scoped_bsuid(h.db, h.db.rows["contact-b"],
                           waba_id=MANISH, bsuid=bsuid)
    k1 = h._scoped_bsuid_key(WECARE, bsuid)
    k2 = h._scoped_bsuid_key(MANISH, bsuid)
    assert k1 != k2
    assert h.claims.rows[k1]["contactId"] == "contact-a"
    assert h.claims.rows[k2]["contactId"] == "contact-b"
    assert h.db.rows["contact-a"]["whatsappIdentities"][WECARE_PORTFOLIO]["bsuid"] == bsuid
    assert h.db.rows["contact-b"]["whatsappIdentities"][MANISH_PORTFOLIO]["bsuid"] == bsuid


def test_one_phone_backed_customer_can_hold_both_portfolio_identities():
    row = {"id": "customer", "phone": "+919999999999",
           "bsuid": "IN.wecareLegacy"}
    h = helpers(row)
    h._attach_scoped_bsuid(h.db, row, waba_id=WECARE,
                           bsuid="IN.wecareLegacy", username="wecare_user")
    h._attach_scoped_bsuid(h.db, row, waba_id=MANISH,
                           bsuid="IN.manishId", username="manish_user")
    assert row["phone"] == "+919999999999"
    assert row["bsuid"] == "IN.wecareLegacy"
    assert row["whatsappIdentities"][WECARE_PORTFOLIO]["username"] == "wecare_user"
    assert row["whatsappIdentities"][MANISH_PORTFOLIO]["username"] == "manish_user"
    assert len(h.claims.rows) == 2


def test_claim_prevents_other_customer_from_stealing_same_business_identity():
    first = {"id": "first"}
    second = {"id": "second"}
    h = helpers(first, second)
    h._attach_scoped_bsuid(h.db, first, waba_id=WECARE, bsuid="IN.789")
    before = h.db.writes
    with pytest.raises(Conflict):
        h._attach_scoped_bsuid(h.db, second, waba_id=WECARE, bsuid="IN.789")
    assert h.db.writes == before
    assert WECARE_PORTFOLIO not in second.get("whatsappIdentities", {})


def test_new_sender_number_must_match_declared_business_scope():
    h = helpers()
    assert h._message_account_id(
        {"phone_number_id": "1016149501586345"},
        [WECARE], needs_bsuid=True) == WECARE
    assert h._message_account_id(
        {"phone_number_id": "1055232054343117"},
        [MANISH], needs_bsuid=True) == MANISH
    with pytest.raises(Conflict):
        h._message_account_id(
            {"phone_number_id": "1016149501586345"},
            [MANISH], needs_bsuid=True)
    with pytest.raises(Conflict):
        h._message_account_id(
            {"phone_number_id": "unknown"}, [], needs_bsuid=True)


def test_unscoped_legacy_id_without_verified_phone_is_not_guessed():
    row = {"id": "old-contact", "bsuid": "IN.legacy", "phone": "+919999999999"}
    h = helpers(row)
    with pytest.raises(Conflict):
        h._find_scoped_bsuid(h.db, "IN.legacy", MANISH, sender_phone="")
    assert h._find_scoped_bsuid(
        h.db, "IN.legacy", MANISH, sender_phone="+919999999999") is row


def test_existing_business_mapping_cannot_be_changed_without_previous_id():
    row = {"id": "customer"}
    h = helpers(row)
    h._attach_scoped_bsuid(h.db, row, waba_id=MANISH, bsuid="IN.old")
    with pytest.raises(Conflict):
        h._attach_scoped_bsuid(h.db, row, waba_id=MANISH, bsuid="IN.new")
    h._attach_scoped_bsuid(h.db, row, waba_id=MANISH,
                           bsuid="IN.new", previous_bsuid="IN.old")
    assert row["whatsappIdentities"][MANISH_PORTFOLIO]["bsuid"] == "IN.new"
    assert h.claims.rows[h._scoped_bsuid_key(MANISH, "IN.old")]["contactId"] == "customer"
    assert h.claims.rows[h._scoped_bsuid_key(MANISH, "IN.new")]["contactId"] == "customer"


def test_other_signed_partner_waba_uses_strict_waba_local_scope():
    partner = "1987654321098765"
    h = helpers({"id": "partner-customer"})
    assert h._message_account_id(
        {"phone_number_id": "partner-phone"},
        [partner], needs_bsuid=True) == partner
    key = h._scoped_bsuid_key(partner, "IN.123")
    assert "WABA_" + partner in key
    h._attach_scoped_bsuid(h.db, h.db.rows["partner-customer"],
                           waba_id=partner, bsuid="IN.123")
    assert h.claims.rows[key]["contactId"] == "partner-customer"
    assert h.db.rows["partner-customer"]["whatsappIdentities"]["WABA_" + partner]["bsuid"] == "IN.123"
    with pytest.raises(Conflict):
        h._portfolio_scope("unknown")
