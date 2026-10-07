"""A ContactsTable fake shaped for `core/contacts`, which queries with STRING expressions.

Why this is not `crm_fake_dynamo.FakeDynamo`
-------------------------------------------
`FakeDynamo` reads the private `_values` off a boto3 `Key('phone').eq(...)` object, because every
caller it was built for composes conditions that way. `core/contacts` does not: `_check_duplicate`
passes `KeyConditionExpression='phone = :ph'` with `ExpressionAttributeValues`, so `FakeDynamo`
raises `AssertionError` on it - which `_check_duplicate` then catches and answers by falling back
to `_check_duplicate_scan`, a method the fake has no `scan` for at all.

The failure mode that matters: against `FakeDynamo` a duplicate-detection test would exercise the
scan fallback instead of the index query, and pass. So this fake speaks the dialect the handler
actually speaks, and refuses anything else rather than guessing.

Supported, and only this
------------------------
    query     one index, a `partition = :value` string condition, optional Limit
    put_item  unconditional
    scan      every row, so the `_check_duplicate_scan` fallback is reachable on purpose
"""

from __future__ import annotations

from typing import Any, Dict, List


class FakeContactsTable:
    """One table. Records every `query` and `scan` so a test can assert on the READ, not the
    result - the distinction that separates "found the right row" from "looked in the right
    place"."""

    def __init__(self, items: List[Dict[str, Any]] | None = None) -> None:
        self.items: List[Dict[str, Any]] = [dict(item) for item in (items or [])]
        self.queries: List[Dict[str, Any]] = []
        self.scans: List[Dict[str, Any]] = []
        self.puts: List[Dict[str, Any]] = []

    # -- reads -----------------------------------------------------------
    def query(self, **kwargs) -> Dict[str, Any]:
        self.queries.append(kwargs)
        values = kwargs.get("ExpressionAttributeValues") or {}
        condition = str(kwargs.get("KeyConditionExpression") or "")
        if ":ph" in values and condition.startswith("phone"):
            matched = [i for i in self.items if i.get("phone") == values[":ph"]]
        elif ":em" in values and condition.startswith("email"):
            matched = [i for i in self.items
                       if str(i.get("email") or "").lower() == str(values[":em"]).lower()]
        else:
            raise AssertionError(
                f"unsupported key condition {condition!r} with values {sorted(values)}; "
                "teach this fake rather than letting the handler silently fall back to a scan")
        limit = kwargs.get("Limit")
        if limit:
            matched = matched[:limit]
        return {"Items": [dict(i) for i in matched], "Count": len(matched)}

    def scan(self, **kwargs) -> Dict[str, Any]:
        self.scans.append(kwargs)
        return {"Items": [dict(i) for i in self.items], "Count": len(self.items)}

    # -- writes ----------------------------------------------------------
    def put_item(self, Item=None, **_) -> Dict[str, Any]:  # noqa: N803 - boto3's spelling
        item = dict(Item or {})
        self.puts.append(item)
        self.items.append(item)
        return {}

    def get_item(self, Key=None, **_) -> Dict[str, Any]:  # noqa: N803 - boto3's spelling
        wanted = (Key or {}).get("id")
        for item in self.items:
            if item.get("id") == wanted:
                return {"Item": dict(item)}
        return {}


class FakeContactsResource:
    """`boto3.resource('dynamodb')` with exactly one table on it."""

    def __init__(self, table: FakeContactsTable) -> None:
        self.table = table
        self.names: List[str] = []

    def Table(self, name: str) -> FakeContactsTable:  # noqa: N802 - boto3's spelling
        self.names.append(name)
        return self.table
