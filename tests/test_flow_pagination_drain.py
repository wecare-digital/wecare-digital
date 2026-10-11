"""The flow reads that must see EVERY row follow LastEvaluatedKey — not just page one.

Guards the fix for the "first DynamoDB page looked like the whole dataset" class of bug:
stats that understated, an SLA sweep that skipped the oldest overdue rows, a reconciliation CSV
that truncated, a registry list that hid flows. `_drain` is the shared helper; this pins that it
pages to completion and reports partial only when the safety cap is hit.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
FUNC = ROOT / "amplify/functions/messaging/whatsapp-business-api"
for p in (str(SHARED), str(FUNC)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "wecare_wa_business_handler_drain", FUNC / "handler.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wecare_wa_business_handler_drain"] = module
    spec.loader.exec_module(module)
    return module


class _PagedTable:
    """Serves rows in pages, handing back a LastEvaluatedKey until the last page."""
    def __init__(self, rows, page_size):
        self.rows = rows
        self.page_size = page_size
        self.calls = 0

    def _page(self, start):
        end = min(start + self.page_size, len(self.rows))
        out = {"Items": self.rows[start:end]}
        if end < len(self.rows):
            out["LastEvaluatedKey"] = {"i": end}
        return out

    def scan(self, ExclusiveStartKey=None, **_):
        self.calls += 1
        return self._page(ExclusiveStartKey["i"] if ExclusiveStartKey else 0)

    def query(self, ExclusiveStartKey=None, **_):
        return self.scan(ExclusiveStartKey=ExclusiveStartKey)


def test_drain_follows_every_page(mod):
    rows = [{"id": n} for n in range(1250)]  # well beyond one page
    table = _PagedTable(rows, page_size=500)
    items, complete = mod._drain(table, "scan")
    assert len(items) == 1250           # nothing dropped
    assert complete is True
    assert table.calls == 3             # 500 + 500 + 250


def test_drain_single_page_is_complete(mod):
    table = _PagedTable([{"id": 1}, {"id": 2}], page_size=500)
    items, complete = mod._drain(table, "scan")
    assert len(items) == 2 and complete is True


def test_drain_reports_partial_when_the_safety_cap_is_hit(mod):
    # One row per page forces more pages than the cap, so it must stop and say so.
    rows = [{"id": n} for n in range(mod._DRAIN_MAX_PAGES + 5)]
    table = _PagedTable(rows, page_size=1)
    items, complete = mod._drain(table, "scan")
    assert complete is False                       # honestly flagged, not silently truncated
    assert len(items) == mod._DRAIN_MAX_PAGES       # stopped at the cap
