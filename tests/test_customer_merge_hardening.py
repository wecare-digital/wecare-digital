"""Regression coverage for retained customer merge aliases and safe operator behavior."""
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


def test_claimed_source_stays_live_but_completed_alias_does_not():
    assert contact_store.is_live(
        {"id": "source", "mergeState": "claimed", "mergedIntoContactId": "target"}
    )
    assert not contact_store.is_live(
        {"id": "source", "mergeState": "merged", "mergedIntoContactId": "target"}
    )


def test_handler_resolves_old_ids_and_hides_completed_aliases_from_active_views():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    read = source[source.index("def _read_one"):source.index("# ─── COUNT")]
    assert "merge_state == MERGE_COMPLETE and merged_target" in read
    assert "resolvedFromMergedContactId" in read
    assert "ConsistentRead=True" in read

    filt = source[source.index("def _active_contact_filter"):source.index("# ─── COUNT")]
    assert "_identity_contact_filter()" in filt
    identity_filter = source[
        source.index("def _identity_contact_filter"):
        source.index("def _active_contact_filter")
    ]
    assert "Attr('mergeState').not_exists()" in identity_filter
    assert "Attr('mergeState').ne(MERGE_COMPLETE)" in identity_filter

    count_to_update = source[source.index("def _count_active"):source.index("# ─── UPDATE")]
    assert count_to_update.count("_active_contact_filter()") >= 3


def test_completed_alias_is_immutable_but_claimed_row_is_not_blocked_by_merge_guard():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    guard = source[
        source.index("def _merged_alias_mutation_refusal"):
        source.index("# ─── UPDATE")
    ]
    assert "merge_state != MERGE_COMPLETE" in guard
    assert "CONTACT_MERGED" in guard
    assert "CONTACT_IDENTITY_STATE_UNAVAILABLE" in guard

    for fn in ("def _update", "def _delete", "def _lock_contact", "def _unlock_contact"):
        start = source.index(fn)
        next_def = source.find("\ndef ", start + 5)
        block = source[start: next_def if next_def != -1 else len(source)]
        assert "_merged_alias_mutation_refusal" in block


def test_duplicate_conflicts_do_not_disclose_existing_customer_name():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    block = source[source.index("def _check_duplicate"):source.index("def _matches")]
    assert "item.get('name'" not in block
    assert "A contact with this phone number already exists" in block
    assert "A contact with this email address already exists" in block
    assert "MERGE_COMPLETE" in block


def test_empty_post_and_put_bodies_are_null_safe():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    assert source.count("json.loads(event.get('body') or '{}')") >= 2


def test_merge_actor_is_verified_middleware_context_not_request_body():
    handler = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()
    middleware = (ROOT / "amplify/functions/shared/lambda_utils/middleware.py").read_text()
    assert "event['_auth'] = {" in middleware
    assert "return _merge_contacts(preauth_body, event.get('_auth') or {}, request_id, origin)" in handler
    merge = handler[handler.index("def _merge_contacts"):handler.index("# ─── CREATE")]
    assert "body.get('actor')" not in merge
    assert "(auth or {}).get('username')" in merge


def test_customer_merge_is_registered_in_audit_vocabulary():
    audit = (ROOT / "amplify/functions/shared/lambda_utils/audit.py").read_text()
    assert "'customer.merge'" in audit
