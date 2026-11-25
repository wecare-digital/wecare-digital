"""Bounded, warm-cached statistics for the canonical MessagesTable.

The cache contains only aggregate counts. DynamoDB scans are not atomic snapshots;
`asOf` marks the start of the observation, not a transactional read timestamp.
Incomplete reads are never returned as fresh or published as partial totals.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

log = logging.getLogger(__name__)

CACHE_SECONDS = 60
MAX_STALE_SECONDS = 5 * 60
RETRY_SECONDS = 30
SCAN_LIMIT = 1000
MAX_PAGES = 12
MAX_SCAN_SECONDS = 4
DAY_SECONDS = 24 * 60 * 60
ACKNOWLEDGED = {"delivered", "read"}


class IncompleteMessageStats(RuntimeError):
    """The result is not sufficient to publish statistics."""


@dataclass(frozen=True)
class Snapshot:
    as_of: int
    today: int
    week: int
    total: int
    outbound: int
    sent: int
    delivered: int

    def payload(self, *, stale: bool = False) -> dict[str, Any]:
        return {
            "status": "stale" if stale else "ok" if self.total else "no_data",
            "asOf": self.as_of,
            "messagesToday": self.today,
            "messagesWeek": self.week,
            "totalMessages": self.total,
            # Keep the historical denominator (all stored outbound statuses).
            # A sent-only or pending row is not proof of delivery.
            "deliveryRate": round(self.delivered * 100 / self.outbound) if self.outbound else None,
            "outboundMessages": self.outbound,
            "sentMessages": self.sent,
            "deliveredMessages": self.delivered,
        }


UNAVAILABLE = dict.fromkeys((
    "asOf", "messagesToday", "messagesWeek", "totalMessages", "deliveryRate",
    "outboundMessages", "sentMessages", "deliveredMessages",
)) | {"status": "unavailable", "errorCode": "MESSAGE_STATS_UNAVAILABLE"}


def _summarize(table: Any, as_of: int, monotonic: Callable[[], float]) -> Snapshot:
    today_start = as_of - as_of % DAY_SECONDS
    # Preserve the existing endpoint boundary: UTC midnight seven days ago.
    week_start = today_start - 7 * DAY_SECONDS
    today = week = total = outbound = sent = delivered = 0
    deadline = monotonic() + MAX_SCAN_SECONDS
    kwargs: dict[str, Any] = {
        "Limit": SCAN_LIMIT,
        "ProjectionExpression": "#d, #s, #ts",
        "ExpressionAttributeNames": {"#d": "direction", "#s": "status", "#ts": "timestamp"},
    }
    for _ in range(MAX_PAGES):
        if monotonic() >= deadline:
            break
        page = table.scan(**kwargs)
        items = page.get("Items")
        if not isinstance(items, list):
            raise IncompleteMessageStats("scan returned no item list")
        for row in items:
            if not isinstance(row, Mapping):
                raise IncompleteMessageStats("scan returned an unreadable item")
            direction = str(row.get("direction") or "").lower()
            if direction not in {"inbound", "outbound"}:
                continue
            total += 1
            if direction == "outbound":
                outbound += 1
                status = str(row.get("status") or "").lower()
                if status == "sent":
                    sent += 1
                elif status in ACKNOWLEDGED:
                    delivered += 1
            ts = row.get("timestamp")
            if isinstance(ts, (int, Decimal)) and not isinstance(ts, bool):
                today += int(today_start <= ts <= as_of)
                week += int(week_start <= ts <= as_of)
        cursor = page.get("LastEvaluatedKey")
        if cursor is None or cursor == {}:
            return Snapshot(as_of, today, week, total, outbound, sent, delivered)
        if not isinstance(cursor, dict) or cursor == kwargs.get("ExclusiveStartKey"):
            raise IncompleteMessageStats("scan cursor did not advance")
        kwargs["ExclusiveStartKey"] = cursor
    raise IncompleteMessageStats("stats refresh exceeded its scan budget")


class CachedMessageStats:
    """Reuse successful observations and cap repeated refreshes after failures."""

    def __init__(
        self,
        table: Callable[[], Any],
        *,
        wall_time: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._table = table
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._snapshot: Snapshot | None = None
        self._next_refresh = float("-inf")

    def read(self) -> tuple[int, dict[str, Any]]:
        now = int(self._wall_time())
        snapshot = self._snapshot
        age = now - snapshot.as_of if snapshot is not None else None
        if (snapshot is not None and age is not None and 0 <= age < CACHE_SECONDS
                and snapshot.as_of // DAY_SECONDS == now // DAY_SECONDS):
            return 200, snapshot.payload()
        if self._monotonic() >= self._next_refresh:
            try:
                snapshot = _summarize(self._table(), now, self._monotonic)
            except Exception as exc:
                # Don't expose infrastructure details or item data in the response/log.
                log.warning("message_stats_refresh_failed errorType=%s", type(exc).__name__)
                snapshot = self._snapshot
                self._next_refresh = self._monotonic() + RETRY_SECONDS
            else:
                self._snapshot = snapshot
                self._next_refresh = float("-inf")
                return 200, snapshot.payload()
        if snapshot is not None and age is not None and 0 <= age <= MAX_STALE_SECONDS:
            return 200, snapshot.payload(stale=True)
        return 503, dict(UNAVAILABLE)
