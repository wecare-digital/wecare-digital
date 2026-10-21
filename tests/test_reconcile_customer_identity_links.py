from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/reconcile_customer_identity_links.py"
spec = importlib.util.spec_from_file_location("reconcile_customer_identity_links", PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class Contacts:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kwargs):
        value = kwargs["KeyConditionExpression"]._values[1]
        return {"Items": [r for r in self.rows if r.get("phone") == value]}


class Dependent:
    key_schema = [{"AttributeName": "id", "KeyType": "HASH"}]

    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.updated = []

    def scan(self, **kwargs):
        rows = [dict(r) for r in self.rows.values() if not r.get("contactId")]
        return {"Items": rows}

    def update_item(self, **kwargs):
        row = self.rows[kwargs["Key"]["id"]]
        if row.get("contactId"):
            raise AssertionError("test does not model a race")
        row["contactId"] = kwargs["ExpressionAttributeValues"][":cid"]
        self.updated.append(row["id"])
        return {}


def test_resolve_contact_requires_exactly_one_live_contact():
    contacts = Contacts([
        {"id": "c1", "contactId": "c1", "phone": "+919876543210"},
    ])
    assert subject.resolve_contact(contacts, "919876543210") == ("c1", "resolved")

    duplicate = Contacts([
        {"id": "c1", "contactId": "c1", "phone": "+919876543210"},
        {"id": "c2", "contactId": "c2", "phone": "+919876543210"},
    ])
    assert subject.resolve_contact(duplicate, "+919876543210") == ("", "ambiguous")


def test_repair_is_dry_run_by_default_and_apply_is_conditional():
    contacts = Contacts([
        {"id": "c1", "contactId": "c1", "phone": "+919876543210"},
    ])
    rows = [{"id": "m1", "senderPhone": "919876543210"}]
    table = Dependent(rows)

    dry = subject.repair_table(table, contacts, phone_field="senderPhone", apply=False)
    assert dry["resolved"] == 1
    assert dry["updated"] == 0
    assert "contactId" not in table.rows["m1"]

    applied = subject.repair_table(table, contacts, phone_field="senderPhone", apply=True)
    assert applied["updated"] == 1
    assert table.rows["m1"]["contactId"] == "c1"


def test_repair_never_guesses_missing_identity():
    contacts = Contacts([])
    table = Dependent([{"id": "m1", "senderPhone": "+919876543210"}])
    result = subject.repair_table(table, contacts, phone_field="senderPhone", apply=True)
    assert result["missing"] == 1
    assert result["updated"] == 0
    assert "contactId" not in table.rows["m1"]
