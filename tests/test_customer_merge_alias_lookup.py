"""Customer merge aliases resolve through the shared contact lookup."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils import contact_store  # noqa: E402


class Table:
    def __init__(self, rows):
        self.rows = rows

    def get_item(self, *, Key, **_kwargs):
        row = self.rows.get(Key["id"])
        return {"Item": dict(row)} if row else {}

    def query(self, **_kwargs):
        return {"Items": []}


def test_completed_merge_alias_resolves_to_canonical_contact():
    table = Table({
        "source": {
            "id": "source",
            "mergeState": "merged",
            "mergedIntoContactId": "target",
        },
        "target": {
            "id": "target",
            "phone": "+910000000001",
        },
    })
    row = contact_store.lookup(table, contact_id="source")
    assert row is not None
    assert row["id"] == "target"
    assert contact_store.lookup_id(table, contact_id="source") == "target"


def test_merge_alias_cycle_fails_closed():
    table = Table({
        "a": {"id": "a", "mergeState": "merged", "mergedIntoContactId": "b"},
        "b": {"id": "b", "mergeState": "merged", "mergedIntoContactId": "a"},
    })
    assert contact_store.lookup(table, contact_id="a") is None


def test_completed_alias_is_not_live_but_claimed_source_is_live():
    assert not contact_store.is_live(
        {"id": "source", "mergeState": "merged", "mergedIntoContactId": "target"}
    )
    assert contact_store.is_live(
        {"id": "source", "mergeState": "claimed", "mergedIntoContactId": "target"}
    )
