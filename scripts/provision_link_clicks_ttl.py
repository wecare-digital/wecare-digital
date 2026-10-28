#!/usr/bin/env python3
"""Expire short-link click rows after a retention period (DynamoDB TTL on `expiresAt`).

Purpose: LinkClicksTable stores each click's source IP and user agent and, until 2026-10-27, kept
them forever. stack-wecare-url-shortener now writes `expiresAt` on every click; this script turns
on the table's TTL and backfills `expiresAt` on the rows written before that change.

Authority: writes only to LinkClicksTable, and only with --apply: UpdateTimeToLive (once) and a
conditional UpdateItem on each row that lacks `expiresAt`. A row whose clickedAt is already older
than the retention period gets an `expiresAt` in the past, and DynamoDB deletes it within a few
days. That is the retention policy taking effect, so the dry run reports how many rows it affects.
Reads only the key attributes and expiresAt; never reads or prints an IP or a user agent.

    python scripts/provision_link_clicks_ttl.py            # dry run: counts only
    python scripts/provision_link_clicks_ttl.py --apply    # enable TTL, then backfill
    python scripts/provision_link_clicks_ttl.py --verify   # read-only check
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

TABLE = os.environ.get("LINK_CLICKS_TABLE", "stack-wecare-digital-LinkClicksTable")
# Same default as the handler's LINK_CLICK_RETENTION_DAYS.
RETENTION_DAYS = int(os.environ.get("LINK_CLICK_RETENTION_DAYS", "365"))
TTL_ATTR = "expiresAt"
# Upper bound for this one-off backfill. The table held 1,080 rows on 2026-10-27.
MAX_ITEMS = 50_000


def clicked_epoch(value: object) -> int | None:
    """clickedAt as epoch seconds; the handler writes naive UTC ISO timestamps."""
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def scan_keys(table) -> list[dict]:
    """Every row's keys and expiresAt, bounded by MAX_ITEMS."""
    items: list[dict] = []
    kwargs: dict = {"ProjectionExpression": "shortCode, clickedAt, #e",
                    "ExpressionAttributeNames": {"#e": TTL_ATTR}}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if len(items) > MAX_ITEMS:
            sys.exit(f"refusing: more than {MAX_ITEMS} rows; raise MAX_ITEMS deliberately")
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="enable TTL and backfill expiresAt")
    mode.add_argument("--verify", action="store_true", help="read-only: TTL on and every row covered")
    args = ap.parse_args()

    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    client = ddb.meta.client
    table = ddb.Table(TABLE)
    ttl = client.describe_time_to_live(TableName=TABLE)["TimeToLiveDescription"]
    status, attr = ttl.get("TimeToLiveStatus"), ttl.get("AttributeName")

    now, keep = int(time.time()), RETENTION_DAYS * 86400
    items = scan_keys(table)
    missing = [i for i in items if TTL_ATTR not in i]
    unreadable = [i for i in missing if clicked_epoch(i.get("clickedAt")) is None]
    past = [i for i in missing if (clicked_epoch(i.get("clickedAt")) or now) + keep <= now]
    print(f"{TABLE}: {len(items)} rows; {len(items) - len(missing)} have {TTL_ATTR}, {len(missing)} do not "
          f"({len(past)} are older than {RETENTION_DAYS} days and TTL will delete them; "
          f"{len(unreadable)} have an unreadable clickedAt and get {RETENTION_DAYS} days from now)")
    print(f"TTL: {status} on {attr!r}")

    if args.verify:
        ok = status == "ENABLED" and attr == TTL_ATTR and not missing
        print("verified" if ok else "NOT verified")
        return 0 if ok else 1
    if not args.apply:
        print("dry run: re-run with --apply to enable TTL and backfill")
        return 0

    if status == "DISABLED" or status is None:
        client.update_time_to_live(TableName=TABLE,
                                   TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTR})
        print(f"TTL enabled on {TTL_ATTR}")
    elif attr != TTL_ATTR:
        sys.exit(f"refusing: TTL already uses {attr!r}")

    done = 0
    for item in missing:
        start = clicked_epoch(item.get("clickedAt")) or now
        try:
            table.update_item(
                Key={"shortCode": item["shortCode"], "clickedAt": item["clickedAt"]},
                UpdateExpression="SET #e = :e",
                ConditionExpression="attribute_not_exists(#e)",
                ExpressionAttributeNames={"#e": TTL_ATTR},
                ExpressionAttributeValues={":e": start + keep},
            )
            done += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    print(f"backfilled {done} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
