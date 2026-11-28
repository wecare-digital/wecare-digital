"""Bounded DynamoDB reads. One implementation, no copies.

These began life inside an agent governance module (since removed), written to stop a
language model paginating a whole table on a whim. The problem is not specific to agents:
`messaging/ad-attribution` had the same shape reached from an ordinary HTTP route,
and worse in one respect — it passed **no** `Limit` to DynamoDB at all, so asking for
one item still transferred up to 1 MB per page, and with a `FilterExpression` it
could read the entire table while collecting almost nothing.

So the helpers live here, in one place. A second copy is how
the stage-prefix rule came back twice before it was given a shared home.

The two rules worth stating
---------------------------
**A limit must reach DynamoDB, not just Python.** Slicing after the fact still pays
for and transfers everything. `Limit` bounds what is *examined*, which is what you are
billed for.

**`truncated` is part of the answer.** "50 results" and "at least 50 results" are
different claims, and whatever a caller is handed is what it will repeat to a person
or render as a total.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Small on purpose: a "limit" of ten thousand is an exhaustive scan with extra steps.
DEFAULT_READ_LIMIT = 25
MAX_READ_LIMIT = 100


def bounded_limit(requested: Any,
                  *, default: int = DEFAULT_READ_LIMIT,
                  maximum: int = MAX_READ_LIMIT) -> int:
    """Clamp a caller-supplied limit. Anything unusable becomes the default.

    Never raises. `int(params.get('limit', '50'))` on a query string is a 500 waiting
    for `?limit=abc`, and that is a real shape - it is what `ad-attribution` did on a
    public-facing route.
    """
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def read_page(table: Any, *, limit: Any = DEFAULT_READ_LIMIT,
              **scan_kwargs: Any) -> Tuple[List[Dict[str, Any]], bool]:
    """One page of a scan, hard-bounded. Returns (items, truncated).

    Deliberately does NOT paginate. The code this replaces looped on
    `LastEvaluatedKey`, which on a table of any real size is an exhaustive scan billed
    per read.

    An `ExclusiveStartKey` from a caller is refused: resuming across invocations turns
    a bounded read back into an unbounded one, one page per request.
    """
    if "ExclusiveStartKey" in scan_kwargs:
        raise ValueError(
            "read_page does not resume a scan; a caller-supplied "
            "ExclusiveStartKey would make a bounded read unbounded")

    capped = bounded_limit(limit)
    response = table.scan(Limit=capped, **scan_kwargs) or {}
    items = list(response.get("Items") or [])
    truncated = bool(response.get("LastEvaluatedKey")) or len(items) > capped
    return items[:capped], truncated


def query_index(table: Any, *, index_name: str, key_name: str, value: Any,
                limit: Any = 1) -> List[Dict[str, Any]]:
    """Exact lookup through a GSI. Never a scan, never a substring match."""
    from boto3.dynamodb.conditions import Key

    if not str(value or "").strip():
        raise ValueError(f"{key_name} is required for an index lookup")

    response = table.query(
        IndexName=index_name,
        KeyConditionExpression=Key(key_name).eq(value),
        Limit=bounded_limit(limit, default=1),
    ) or {}
    return list(response.get("Items") or [])
