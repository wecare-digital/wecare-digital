"""Protection changes are restricted to project tables and cannot disable protection."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'protect_tables', Path(__file__).resolve().parents[1] / 'scripts/protect_dynamodb_tables.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self):
        self.tables = {module.PREFIX + 'ContactsTable': False,
                       module.PREFIX + 'ProductsTable': True, 'unrelated-table': False}
        self.writes = []

    def get_paginator(self, operation):
        assert operation == 'list_tables'
        return self

    def paginate(self):
        yield {'TableNames': list(self.tables)[:1]}
        yield {'TableNames': list(self.tables)[1:]}

    def describe_table(self, TableName):
        assert TableName.startswith(module.PREFIX)
        return {'Table': {'DeletionProtectionEnabled': self.tables[TableName]}}

    def update_table(self, TableName, DeletionProtectionEnabled):
        assert DeletionProtectionEnabled is True
        self.writes.append(TableName)
        self.tables[TableName] = True


def test_plan_cannot_mutate_tables_and_discovers_all_pages():
    client = FakeClient()
    rows = module.protect(client)
    assert len(rows) == 2
    assert not client.writes
    assert {r['protected'] for r in rows} == {False, True}


def test_apply_only_enables_missing_project_protection():
    client = FakeClient()
    rows = module.protect(client, apply=True)
    assert client.writes == [module.PREFIX + 'ContactsTable']
    assert all(r['protected'] for r in rows)
    assert client.tables['unrelated-table'] is False
    module.protect(client, apply=True)
    assert client.writes == [module.PREFIX + 'ContactsTable']
