"""PAY-10: invoice dedupe queries referenceId-index instead of scanning the whole table."""
import ast
from pathlib import Path
from typing import Any, Dict, List

import pytest

_ENGINE = Path(__file__).resolve().parents[2] / "amplify/functions/payments/invoice-engine/handler.py"


def _engine():
    tree = ast.parse(_ENGINE.read_text())
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name == "_invoice_dedup_matches")
             or (isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "_INVOICE_DEDUP_SCAN_MAX_PAGES" for t in n.targets))]
    namespace = {"Any": Any, "Dict": Dict, "List": List}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(_ENGINE), "exec"), namespace)
    return namespace


class Invoices:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def _page(self, kind, kwargs):
        self.calls.append((kind, kwargs))
        index = sum(1 for call in self.calls if call[0] == kind) - 1
        items = self.pages[index] if index < len(self.pages) else []
        more = index + 1 < len(self.pages)
        return {"Items": items, **({"LastEvaluatedKey": {"invoiceId": str(index)}} if more else {})}

    def query(self, **kwargs):
        return self._page("query", kwargs)

    def scan(self, **kwargs):
        return self._page("scan", kwargs)


def test_reference_is_queried_on_the_index_across_every_page():
    dedupe = _engine()["_invoice_dedup_matches"]
    table = Invoices([[{"invoiceId": "a"}], [{"invoiceId": "b"}]])
    rows = dedupe(table, "WD-PAY-ABCDEF12", "pay_1")
    assert [row["invoiceId"] for row in rows] == ["a", "b"]
    assert {kind for kind, _ in table.calls} == {"query"}
    first = table.calls[0][1]
    assert first["IndexName"] == "referenceId-index"
    assert first["ExpressionAttributeValues"] == {":ref": "WD-PAY-ABCDEF12"}
    assert table.calls[1][1]["ExclusiveStartKey"] == {"invoiceId": "0"}


def test_payment_id_only_scan_is_bounded_and_fails_closed():
    engine = _engine()
    dedupe, bound = engine["_invoice_dedup_matches"], engine["_INVOICE_DEDUP_SCAN_MAX_PAGES"]
    small = Invoices([[], [{"invoiceId": "a"}]])
    assert [row["invoiceId"] for row in dedupe(small, "", "pay_1")] == ["a"]
    assert small.calls[0] == ("scan", {"FilterExpression": "paymentId = :pid",
                                       "ExpressionAttributeValues": {":pid": "pay_1"}})
    huge = Invoices([[] for _ in range(bound + 5)])
    with pytest.raises(RuntimeError):
        dedupe(huge, "", "pay_1")
    assert len(huge.calls) == bound
