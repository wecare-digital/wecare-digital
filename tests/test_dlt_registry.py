"""TRAI DLT template registry contract tests.

The registry is application-owned regulatory data and remains independent of the
SMS transport implementation.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.comms import dlt as dlt_mod              # noqa: E402
from lambda_utils.comms import dlt_registry                 # noqa: E402


class _FakeTable:
    """Minimal DynamoDB Table double: get/put/update/delete/scan."""

    def __init__(self, items=None, key_name="templateId"):
        self.items = {str(i[key_name]): dict(i) for i in (items or [])}
        self.key_name = key_name
        self.deleted = []
        self.scan_calls = []

    def get_item(self, Key):
        found = self.items.get(str(Key[self.key_name]))
        return {"Item": dict(found)} if found else {}

    def put_item(self, Item):
        self.items[str(Item[self.key_name])] = dict(Item)
        return {}

    def update_item(self, **kwargs):
        key = str(kwargs["Key"][self.key_name])
        if "ConditionExpression" in kwargs and key not in self.items:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        row = self.items.setdefault(key, {self.key_name: key})
        values = kwargs.get("ExpressionAttributeValues", {})
        names = kwargs.get("ExpressionAttributeNames", {})
        for assignment in kwargs["UpdateExpression"][4:].split(", "):
            field, placeholder = [p.strip() for p in assignment.split("=")]
            row[names.get(field, field)] = values[placeholder]
        return {"Attributes": dict(row)}

    def delete_item(self, Key):
        self.deleted.append(str(Key[self.key_name]))
        self.items.pop(str(Key[self.key_name]), None)
        return {}

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        return {"Items": [dict(v) for v in self.items.values()]}

    def batch_writer(self):
        table = self

        class _Batch:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def delete_item(self_inner, Key):
                table.delete_item(Key)
        return _Batch()


# ==========================================================================
# DLT template registry
# ==========================================================================
@pytest.fixture
def registry(monkeypatch):
    table = _FakeTable(key_name="templateId")
    monkeypatch.setattr(dlt_registry, "_table", lambda: table)
    return table


def test_variables_are_extracted_in_positional_order():
    """DLT variables are positional in the approved template, so order matters."""
    found = dlt_registry.extract_variables("Hi {#name#}, order {#id#} for {#name#}")
    assert found == ["name", "id"]


def test_create_defaults_to_the_registered_identity(registry):
    created = dlt_registry.create_template({
        "templateId": "1000000000000000001",
        "name": "test-tpl",
        "content": "Hello {#var#}",
    })
    assert created["entityId"] == dlt_mod.ENTITY_ID
    assert created["senderId"] == dlt_mod.SENDER_ID
    assert created["variables"] == ["var"]


def test_create_requires_id_and_content(registry):
    with pytest.raises(dlt_registry.RegistryError):
        dlt_registry.create_template({"content": "x"})
    with pytest.raises(dlt_registry.RegistryError):
        dlt_registry.create_template({"templateId": "1"})


def test_create_rejects_an_invalid_message_type(registry):
    with pytest.raises(dlt_registry.RegistryError) as exc:
        dlt_registry.create_template({
            "templateId": "1", "content": "x", "messageType": "MARKETING"})
    assert exc.value.code == "INVALID_MESSAGE_TYPE"


def test_update_refuses_to_create_a_row(registry):
    """A typo'd id must not silently add a template nobody registered."""
    with pytest.raises(dlt_registry.RegistryError) as exc:
        dlt_registry.update_template({"templateId": "does-not-exist", "name": "x"})
    assert exc.value.code == "NOT_FOUND"


def test_update_rederives_variables_from_new_content(registry):
    dlt_registry.create_template({
        "templateId": "1000000000000000002", "content": "old {#a#}"})
    updated = dlt_registry.update_template({
        "templateId": "1000000000000000002", "content": "new {#b#} {#c#}"})
    assert updated["variables"] == ["b", "c"]


def test_update_cannot_empty_the_content(registry):
    dlt_registry.create_template({
        "templateId": "1000000000000000003", "content": "body"})
    with pytest.raises(dlt_registry.RegistryError):
        dlt_registry.update_template({
            "templateId": "1000000000000000003", "content": ""})


def test_builtin_template_cannot_be_deleted(registry):
    """Deleting it would not stop it being used - dlt.resolve checks builtins first.

    The only effect would be a registry that disagrees with live traffic.
    """
    builtin_id = dlt_mod.TEMPLATES["ivr-default"]
    with pytest.raises(dlt_registry.RegistryError) as exc:
        dlt_registry.delete_template(builtin_id)
    assert exc.value.code == "BUILTIN_TEMPLATE_PROTECTED"
    assert registry.deleted == []


def test_non_builtin_template_can_be_deleted(registry):
    dlt_registry.create_template({
        "templateId": "1000000000000000004", "content": "x"})
    result = dlt_registry.delete_template("1000000000000000004")
    assert result["deleted"] == "1000000000000000004"


def test_list_reports_which_keys_the_send_path_knows(registry):
    dlt_registry.create_template({
        "templateId": "1000000000000000005", "name": "ivr-default", "content": "x"})
    listing = dlt_registry.list_templates()
    assert listing["builtinKeys"] == dlt_mod.known_keys()
    assert listing["templates"][0]["isBuiltinKey"] is True


def test_list_marks_a_non_builtin_name_as_such(registry):
    dlt_registry.create_template({
        "templateId": "1000000000000000006", "name": "something-else", "content": "x"})
    assert dlt_registry.list_templates()["templates"][0]["isBuiltinKey"] is False
