"""Automation rules and team-inbox meta: roles, PUT validation, actor stamps, audit, and a
rule loader that skips a bad rule. In-memory tables; no AWS calls."""
import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
ROOT = Path(__file__).resolve().parents[2]
RANK = {"Viewer": 1, "Operator": 2, "Admin": 3}


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RULES = _load("automation_rules_under_test", "amplify/functions/core/automation-rules/handler.py")
META = _load("conversation_meta_under_test", "amplify/functions/core/conversation-meta/handler.py")


class FakeTable:
    def __init__(self, key, rows=()):
        self.key = key
        self.rows = {r[key]: dict(r) for r in rows}
        self.puts = []

    def scan(self, **_):
        return {"Items": [dict(r) for r in self.rows.values()], "Count": len(self.rows)}

    def get_item(self, Key):
        row = self.rows.get(Key[self.key])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item):
        self.puts.append(dict(Item))
        self.rows[Item[self.key]] = dict(Item)

    def delete_item(self, Key, ReturnValues=None):
        old = self.rows.pop(Key[self.key], None)
        return {"Attributes": old} if old and ReturnValues == "ALL_OLD" else {}


@pytest.fixture
def staff(monkeypatch):
    """Fake require_auth: records the role asked for and refuses a lower role."""
    import lambda_utils.middleware as middleware
    state = {"role": "Operator", "asked": [], "audits": []}

    def require_auth(event, required_role=None):
        state["asked"].append(required_role)
        if required_role and RANK[state["role"]] < RANK[required_role]:
            return {"statusCode": 403, "body": json.dumps({"error": "Insufficient permissions"})}
        event["_auth"] = {"username": "staff-user-1", "email": "staff@example.test",
                          "role": state["role"]}
        return None

    monkeypatch.setattr(middleware, "require_auth", require_auth)
    for module in (RULES, META):
        monkeypatch.setattr(module, "record_audit",
                            lambda **kw: state["audits"].append(kw) or "log-id")
    return state


def call(module, method, body=None, path="/automation/rules", params=None):
    event = {"requestContext": {"http": {"method": method, "path": path}},
             "rawPath": path, "pathParameters": params or {}, "headers": {}}
    if body is not None:
        event["body"] = json.dumps(body)
    response = module.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture
def rules(monkeypatch):
    table = FakeTable("id")
    monkeypatch.setattr(RULES, "_table", lambda: table)
    return table


def test_reads_need_viewer_and_every_write_needs_operator(staff, rules):
    staff["role"] = "Viewer"
    assert call(RULES, "GET")[0] == 200
    rules.rows["r1"] = {"id": "r1", "name": "x", "priority": 1}
    for method, params in (("POST", {}), ("PUT", {"id": "r1"}), ("DELETE", {"id": "r1"})):
        status, _ = call(RULES, method, {"name": "changed"}, params=params)
        assert status == 403
    assert staff["asked"] == ["Viewer", "Operator", "Operator", "Operator"]
    assert rules.puts == [] and "r1" in rules.rows and staff["audits"] == []


def test_post_stamps_session_actor_not_body(staff, rules):
    status, body = call(RULES, "POST", {"name": "Hi", "triggerType": "any", "actionValue": "Hello",
                                        "createdBy": "forged", "updatedBy": "forged",
                                        "priority": "7"})
    assert status == 200
    rule = body["rule"]
    assert rule["createdBy"] == rule["updatedBy"] == "staff-user-1"
    assert rule["priority"] == 7 and rule["channel"] == "any" and rule["actionType"] == "reply"
    assert [a["action"] for a in staff["audits"]] == ["automation_rule.create"]
    assert staff["audits"][0]["actor"] == "staff-user-1"
    assert staff["audits"][0]["resource_id"] == rule["id"]


@pytest.mark.parametrize("bad", ["abc", None, [], {"n": 1}, "1.5e3"])
def test_post_and_put_refuse_a_priority_that_is_not_an_integer(staff, rules, bad):
    assert call(RULES, "POST", {"name": "x", "priority": bad})[0] == 400
    rules.rows["r1"] = {"id": "r1", "name": "x", "priority": Decimal(5)}
    assert call(RULES, "PUT", {"priority": bad}, params={"id": "r1"})[0] == 400
    assert rules.puts == [] and rules.rows["r1"]["priority"] == Decimal(5)
    assert staff["audits"] == []


def test_put_runs_the_post_validators_and_keeps_creator(staff, rules):
    rules.rows["r1"] = {"id": "r1", "name": "Old", "enabled": True, "channel": "sms",
                        "triggerType": "keyword", "triggerValue": "hi", "actionType": "reply",
                        "actionValue": "Hello", "priority": Decimal(5), "createdBy": "creator",
                        "createdAt": 1, "updatedAt": 1}
    status, body = call(RULES, "PUT", {"channel": "bogus", "triggerType": "nope", "actionType": "x",
                                       "name": "N" * 500, "triggerValue": "t" * 500,
                                       "actionValue": "a" * 5000, "priority": "9",
                                       "createdBy": "forged", "updatedBy": "forged",
                                       "unknownField": "dropped"}, params={"id": "r1"})
    assert status == 200
    rule = body["rule"]
    # An unknown enum value keeps the stored one instead of widening the rule to 'any'.
    assert (rule["channel"], rule["triggerType"], rule["actionType"]) == ("sms", "keyword", "reply")
    assert len(rule["name"]) == 120 and len(rule["triggerValue"]) == 200
    assert len(rule["actionValue"]) == 2000 and rule["priority"] == 9
    assert rule["createdBy"] == "creator" and rule["updatedBy"] == "staff-user-1"
    assert "unknownField" not in rule
    audit = staff["audits"][-1]
    assert audit["action"] == "automation_rule.update" and audit["actor"] == "staff-user-1"
    assert audit["details"]["changes"]["priority"] == {"from": Decimal(5), "to": 9}
    assert "channel" not in audit["details"]["changes"]


def test_delete_is_audited_with_the_deleted_rule(staff, rules):
    rules.rows["r1"] = {"id": "r1", "name": "Gone", "priority": 1}
    status, body = call(RULES, "DELETE", params={"id": "r1"})
    assert status == 200 and body["deleted"] == "r1" and "r1" not in rules.rows
    audit = staff["audits"][-1]
    assert audit["action"] == "automation_rule.delete" and audit["details"]["rule"]["name"] == "Gone"


def test_list_survives_a_stored_bad_priority(staff, rules):
    rules.rows.update({"bad": {"id": "bad", "priority": "abc"},
                       "b": {"id": "b", "priority": Decimal(20)},
                       "a": {"id": "a", "priority": Decimal(10)}})
    status, body = call(RULES, "GET")
    assert status == 200
    assert [r["id"] for r in body["rules"]] == ["a", "b", "bad"]


def test_rule_loader_skips_one_bad_rule_and_keeps_the_rest(monkeypatch):
    from lambda_utils import automation

    items = [{"id": "bad", "priority": "not-a-number", "enabled": True, "triggerType": "any",
              "actionType": "reply", "actionValue": "from bad"},
             {"id": "late", "priority": Decimal(50), "enabled": True, "triggerType": "any",
              "actionType": "reply", "actionValue": "late"},
             {"id": "early", "priority": Decimal(10), "enabled": True, "triggerType": "keyword",
              "triggerValue": "price", "actionType": "reply", "actionValue": "early"}]

    class Table:
        def scan(self):
            return {"Items": items}

    monkeypatch.setattr(automation, "_dynamodb", type("D", (), {"Table": lambda self, name: Table()})())
    monkeypatch.setattr(automation, "_cache", {"rules": None, "at": 0})
    assert [r["id"] for r in automation._load_rules()] == ["early", "late"]
    assert automation.evaluate_rules("what is the price", "whatsapp") == "early"
    assert automation.evaluate_rules("hello", "sms") == "late"


@pytest.fixture
def meta(monkeypatch):
    table = FakeTable("conversationId")
    monkeypatch.setattr(META, "_table", lambda: table)
    return table


def test_meta_reads_need_viewer_and_writes_need_operator(staff, meta):
    staff["role"] = "Viewer"
    assert call(META, "GET", path="/inbox/meta")[0] == 200
    assert call(META, "PUT", {"status": "resolved"}, path="/inbox/meta/c1",
                params={"conversationId": "c1"})[0] == 403
    assert call(META, "POST", {"text": "x"}, path="/inbox/meta/c1/note",
                params={"conversationId": "c1"})[0] == 403
    assert staff["asked"] == ["Viewer", "Operator", "Operator"]
    assert meta.puts == [] and staff["audits"] == []


def test_note_author_comes_from_the_session(staff, meta):
    status, body = call(META, "POST", {"text": "Called back", "by": "someone-else"},
                        path="/inbox/meta/c1/note", params={"conversationId": "c1"})
    assert status == 200
    assert body["meta"]["notes"][-1]["by"] == "staff-user-1"
    assert body["meta"]["updatedBy"] == "staff-user-1"
    audit = staff["audits"][-1]
    assert audit["action"] == "conversation_meta.note" and audit["actor"] == "staff-user-1"
    assert audit["resource_id"] == "c1" and "Called back" not in json.dumps(audit["details"])


def test_meta_update_stamps_actor_and_audits_changes(staff, meta):
    status, body = call(META, "PUT", {"status": "resolved", "assignee": "agent-2",
                                      "updatedBy": "forged"},
                        path="/inbox/meta/c1", params={"conversationId": "c1"})
    assert status == 200
    assert body["meta"]["updatedBy"] == "staff-user-1" and body["meta"]["assignee"] == "agent-2"
    audit = staff["audits"][-1]
    assert audit["action"] == "conversation_meta.update"
    assert audit["details"]["changes"] == {"status": {"from": "open", "to": "resolved"},
                                           "assignee": {"from": "", "to": "agent-2"}}
