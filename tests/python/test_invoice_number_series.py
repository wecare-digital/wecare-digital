"""Invoice-number series letter: `WD/2627/A/00001`. The original shape must not change.

Runs the real `_format_invoice_number` / `_get_next_invoice_number` from invoice-engine and the
real reconcile-script parser, against in-memory tables. No AWS.
"""
import ast
import importlib.util
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'amplify/functions/payments/invoice-engine/handler.py'
RECONCILE = ROOT / 'scripts/reconcile_invoice_sequence.py'


def engine(names, **env):
    nodes = [n for n in ast.parse(ENGINE.read_text()).body
             if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.ClassDef) and n.name == 'InvoiceSequenceUnavailable')
             or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in
                 {'_SERIES_RE', '_INVOICE_NUMBER_ATTEMPTS'} for t in n.targets))]
    ns = {'re': re, 'time': time, 'json': json, **env}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ENGINE), 'exec'), ns)
    return ns


def test_original_shape_is_unchanged_without_a_series():
    fmt = engine({'_format_invoice_number'})['_format_invoice_number']
    assert fmt('WD', '2026-2027', 21) == 'WD/2627/00021'
    assert fmt('WD', '2026-2027', 21, '') == 'WD/2627/00021'
    assert fmt('WD', '2026-2027', 21, None) == 'WD/2627/00021'


def test_series_letter_goes_between_year_and_number():
    fmt = engine({'_format_invoice_number'})['_format_invoice_number']
    assert fmt('WD', '2026-2027', 1, 'A') == 'WD/2627/A/00001'
    assert fmt('WD', '2026-2027', 3, 'a') == 'WD/2627/A/00003'
    # Anything that is not 1-3 letters is ignored rather than written into a number.
    for bad in ('A1', 'A/B', 'ABCD', ' ', '../'):
        assert fmt('WD', '2026-2027', 3, bad) == 'WD/2627/00003'


class Seq:
    def __init__(self, row):
        self.row = dict(row)

    def update_item(self, Key, ExpressionAttributeValues, ReturnValues, **_):
        assert ReturnValues == 'ALL_NEW'
        self.row['last_seq'] = self.row.get('last_seq', 0) + 1
        self.row.setdefault('prefix', 'WD')
        return {'Attributes': dict(self.row)}


def next_fn(row, reserved):
    seq = Seq(row)
    ok = lambda table, invoice_number, fy: (invoice_number not in reserved
                                           and not reserved.add(invoice_number))
    ns = engine({'_format_invoice_number', '_get_next_invoice_number', '_current_fy'},
                dynamodb=SimpleNamespace(Table=lambda name: seq),
                INVOICE_SEQ_TABLE='seq', COMMERCE_KEYS_TABLE='keys', IST_OFFSET=19800,
                logger=SimpleNamespace(error=lambda *a: None, warning=lambda *a: None),
                order_keys=SimpleNamespace(reserve_invoice_number=ok,
                                           OrderIdentityUnavailable=RuntimeError))
    return ns['_get_next_invoice_number'], seq


def test_counter_issues_next_number_in_its_series():
    reserved = {f'WD/2627/{n:05d}' for n in range(1, 22)} | {'WD/2627/A/00001', 'WD/2627/A/00002'}
    nxt, seq = next_fn({'fy': '2026-2027', 'prefix': 'WD', 'series': 'A', 'last_seq': 2}, reserved)
    assert nxt('2026-2027') == 'WD/2627/A/00003'
    assert nxt('2026-2027') == 'WD/2627/A/00004'
    assert seq.row['last_seq'] == 4


def test_counter_without_series_behaves_exactly_as_before():
    reserved = {f'WD/2627/{n:05d}' for n in range(1, 22)}
    nxt, _ = next_fn({'fy': '2026-2027', 'prefix': 'WD', 'last_seq': 21}, reserved)
    assert nxt('2026-2027') == 'WD/2627/00022'


def test_a_series_number_already_issued_is_walked_past_never_reissued():
    reserved = {'WD/2627/A/00001', 'WD/2627/A/00002', 'WD/2627/A/00003'}
    nxt, _ = next_fn({'fy': '2026-2027', 'prefix': 'WD', 'series': 'A', 'last_seq': 2}, reserved)
    assert nxt('2026-2027') == 'WD/2627/A/00004'


def reconcile():
    spec = importlib.util.spec_from_file_location('reconcile_invoice_sequence', RECONCILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reconcile_counts_only_the_counters_series():
    r = reconcile()
    assert r.parse_sequence('WD/2627/00021', fy='2026-2027') == 21
    assert r.parse_sequence('WD/2627/A/00002', fy='2026-2027') == 0
    assert r.parse_sequence('WD/2627/A/00002', fy='2026-2027', series='A') == 2
    # The old series must not push the A-series counter forward.
    assert r.parse_sequence('WD/2627/00021', fy='2026-2027', series='A') == 0
    assert r.parse_sequence('WD/2526/A/00009', fy='2026-2027', series='A') == 0
    assert r.parse_sequence('garbage', fy='2026-2027', series='A') == 0
