"""The new staff preview is an aggregate-only read, never deletion."""
import pytest

from lambda_utils.erasure.live_preview import (
    inspect_tables, _scan_complete, ErasurePreviewError,
)


class ReadOnlyTable:
    def __init__(self, rows, page_size=3):
        self.rows = list(rows)
        self.page_size = page_size
        self.scan_count = 0

    def scan(self, **kwargs):
        assert kwargs.get("ConsistentRead") is True
        self.scan_count += 1
        start = int(kwargs.get("ExclusiveStartKey", {}).get("offset", 0))
        batch = self.rows[start:start + self.page_size]
        result = {"Items": batch}
        if start + self.page_size < len(self.rows):
            result["LastEvaluatedKey"] = {"offset": start + self.page_size}
        return result


def tables():
    return {
        "contacts": ReadOnlyTable([
            {"id": "held-a", "name": "Duplicate", "locked": True,
             "lockedReason": "created"},
            {"id": "held-b", "name": "Duplicate", "locked": True,
             "lockedReason": "created"},
            {"id": "other-c", "locked": True, "lockedReason": "created"},
        ], page_size=2),
        "conversation_meta": ReadOnlyTable([
            {"conversationId": "held-a", "tags": ["retention-hold"]},
            {"conversationId": "held-b", "tags": ["retention-hold"]},
        ], page_size=1),
        "message": ReadOnlyTable([
            {"id": "m-a", "contactId": "held-a"},
            {"id": "m-b", "contactId": "held-b"},
            {"id": "m-c", "contactId": "other-c"},
        ]),
        "inbound": ReadOnlyTable([]),
        "outbound": ReadOnlyTable([]),
        "payments": ReadOnlyTable([]),
        "attempts": ReadOnlyTable([]),
        "invoices": ReadOnlyTable([]),
        "orders": ReadOnlyTable([]),
    }


def test_two_same_name_identities_are_kept_and_others_only_reviewed():
    t = tables()
    result = inspect_tables(t)
    assert result["readOnly"] is True
    assert result["eligibleForExecution"] == 0
    assert result["executionAuthorized"] is False
    assert result["contacts"]["protected"] == 2
    assert result["contacts"]["other"] == 1
    assert result["messages"]["byTable"]["MessagesTable"]["protected"] == 2
    assert result["contacts"]["disposition"]["REVIEW_REQUIRED"] == 1
    assert all(table.scan_count >= 1 for table in t.values())
    assert t["conversation_meta"].scan_count == 2


def test_missing_protected_contact_refuses_entire_preview():
    t = tables()
    t["contacts"].rows.pop()
    t["contacts"].rows.pop()
    with pytest.raises(ErasurePreviewError):
        inspect_tables(t)


def test_missing_private_hold_refuses_entire_preview():
    t = tables()
    t["conversation_meta"].rows.pop()
    with pytest.raises(ErasurePreviewError):
        inspect_tables(t)


def test_missing_source_refuses_instead_of_assuming_empty():
    t = tables()
    del t["payments"]
    with pytest.raises(ErasurePreviewError):
        inspect_tables(t)


def test_pagination_is_complete_and_guarded():
    t = ReadOnlyTable([{"id": "a"}, {"id": "b"}], page_size=1)
    assert len(_scan_complete(t)) == 2
    with pytest.raises(ErasurePreviewError):
        _scan_complete(t, max_rows=1)


def test_unreadable_page_fails_closed():
    class Broken:
        def scan(self, **kwargs):
            return {"Count": 0}
    with pytest.raises(ErasurePreviewError):
        _scan_complete(Broken())


def test_no_customer_identifiers_in_summary():
    result = inspect_tables(tables())
    rendered = str(result)
    assert "held-a" not in rendered
    assert "held-b" not in rendered
    assert "other-c" not in rendered
    assert len(result["snapshotSha256"]) == 64
