"""One table per shared concept: contacts, orders, flow responses, flow logs.

The WhatsApp inbox, WhatsApp catalog orders, WhatsApp Flows and the website checkout must read
and write the SAME contact, order and flow-response rows. `lambda_utils.shared_tables` names
those stores and the tables that were folded into them; these tests keep the code honest:

* no runtime module names a folded table (a second store cannot quietly come back);
* every env default for a shared store resolves to the one shared table;
* every literal shared-store name in runtime code is spelled exactly as the live table.

Read from the AST, never from the text: comments and docstrings necessarily NAME the folded
tables when they explain the fold, so a substring search would find its own explanation.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterator, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / 'amplify' / 'functions'
sys.path.insert(0, str(FUNCTIONS / 'shared'))

from lambda_utils import shared_tables  # noqa: E402

PREFIX = shared_tables.DEFAULT_PREFIX


def runtime_modules() -> Iterator[Path]:
    for path in sorted(FUNCTIONS.rglob('*.py')):
        parts = set(path.parts)
        if 'tests' in parts or '__pycache__' in parts or 'node_modules' in parts:
            continue
        yield path


def _docstring_nodes(tree: ast.AST) -> set:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                nodes.add(id(body[0].value))
    return nodes


def code_strings(path: Path) -> Iterator[Tuple[int, str]]:
    """Every string constant in the module that is code, not documentation."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docs = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def test_the_registry_names_exactly_the_live_tables():
    assert {t.default_name for t in shared_tables.SHARED} == {
        f'{PREFIX}-ContactsTable', f'{PREFIX}-OrderTable', f'{PREFIX}-FlowSubmissionTable',
        f'{PREFIX}-FlowLogTable', f'{PREFIX}-RequestStatusHistoryTable', f'{PREFIX}-FlowDraftTable'}
    # Every folded table maps into one of the shared stores, never into another folded table.
    shared_physical = {t.physical for t in shared_tables.SHARED}
    assert set(shared_tables.RETIRED.values()) <= shared_physical
    assert not set(shared_tables.RETIRED) & shared_physical


#: The registry is the one module allowed to name a folded table: `RETIRED` is how everything
#: else learns where those rows went.
REGISTRY = FUNCTIONS / 'shared' / 'lambda_utils' / 'shared_tables.py'


def test_no_runtime_module_names_a_folded_table():
    offenders = []
    for path in runtime_modules():
        if path == REGISTRY:
            continue
        for line, text in code_strings(path):
            for retired in shared_tables.RETIRED:
                if retired in text:
                    offenders.append(f'{path.relative_to(ROOT)}:{line} names {retired}')
    assert not offenders, (
        'runtime code writes or reads a folded table; route it through the shared store '
        'instead:\n' + '\n'.join(offenders))


def test_every_env_default_for_a_shared_store_is_the_shared_table():
    by_env = {t.env: t.default_name for t in shared_tables.SHARED}
    drift = []
    for path in runtime_modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get' and len(node.args) >= 2):
                continue
            key, default = node.args[0], node.args[1]
            if not (isinstance(key, ast.Constant) and isinstance(default, ast.Constant)):
                continue
            expected = by_env.get(key.value)
            if expected is not None and default.value not in ('', expected):
                drift.append(f'{path.relative_to(ROOT)}:{node.lineno} {key.value} '
                             f'defaults to {default.value!r}, not {expected!r}')
    assert not drift, '\n'.join(drift)


#: Spellings of a shared store that are NOT a live table. `OrdersTable` is the classic one:
#: the env var is ORDERS_TABLE, the table is OrderTable.
_SHARED_STEMS = re.compile(
    rf'{re.escape(PREFIX)}-(Contacts?|Customers?|Orders?|FlowSubmissions?|FlowLogs?|'
    r'RequestStatusHistory|FlowDrafts?)(Table)?\b')


def test_every_literal_shared_store_name_is_spelled_as_the_live_table():
    canonical = {t.default_name for t in shared_tables.SHARED}
    wrong = []
    for path in runtime_modules():
        for line, text in code_strings(path):
            for match in _SHARED_STEMS.finditer(text):
                if match.group(0) not in canonical:
                    wrong.append(f'{path.relative_to(ROOT)}:{line} {match.group(0)!r}')
    assert not wrong, '\n'.join(wrong)


@pytest.mark.parametrize('spec', shared_tables.SHARED, ids=lambda s: s.concept)
def test_name_prefers_the_env_then_the_prefix_then_the_account_default(spec, monkeypatch):
    monkeypatch.delenv(spec.env, raising=False)
    monkeypatch.delenv('TABLE_PREFIX', raising=False)
    assert spec.name() == spec.default_name
    monkeypatch.setenv('TABLE_PREFIX', 'stage-x')
    assert spec.name() == f'stage-x-{spec.physical}'
    monkeypatch.setenv(spec.env, 'explicit-table')
    assert spec.name() == 'explicit-table'


def test_the_folded_domain_kinds_live_in_the_flow_response_table():
    from lambda_utils import flow_records
    codes = [code for kind in flow_records.KINDS for code in kind.flow_codes]
    assert len(codes) == len(set(codes)), 'two kinds share a flowCode'
    assert flow_records.table_name() == shared_tables.flow_submissions_table_name()
