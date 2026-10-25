"""
Create the sparse `orderStatusRetry-index` on the invoices table, and optionally tag the rows
that were deferred before it existed.

Why
---
`wecare-invoice-engine.send_order_status` parks a fulfilment update Meta could not take yet (the
customer's 24-hour window closed and no ORDER_STATUS template approved) on the invoice as
`pendingOrderStatus`. Nothing ever retried it. The engine now also sets
`orderStatusRetry = 'PENDING'`, and `wecare-razorpay-webhook`'s 5-minute schedule queries this
index for the oldest few and retries them through the engine. Only rows carrying
`orderStatusRetry` are in the index, so the query reads exactly the owed updates: no scan.

Index: HASH `orderStatusRetry` (S), RANGE `pendingOrderStatusAt` (N), INCLUDE
`pendingOrderStatus`, `pendingOrderStatusSince`. A projection is immutable after creation, so a
live index whose keys or projection differ is reported, never reconciled.

The query fails closed while the index is missing or CREATING (razorpay logs
`order_status_retry_query_failed` and retries nothing), so code may ship before or after this.

Backfill (`--backfill`, with `--apply`): rows deferred before the change carry
`pendingOrderStatus` but no `orderStatusRetry`. Selection: `pendingOrderStatus` present,
`orderStatusRetry` absent, `pendingOrderStatusAt` a number within the retry's 7-day window.
Bounded: refused when the table holds more than MAX_BACKFILL_ITEMS (then this one-off scan is
the wrong tool). Each write is conditional on the same predicate. Recovery: `REMOVE
orderStatusRetry` on a row takes it back out of the index. Verify with the index query this
script prints. Only counts are printed, never invoice data.

Usage:
    python scripts/provision_order_status_retry_index.py                      # report
    python scripts/provision_order_status_retry_index.py --apply              # create, wait ACTIVE
    python scripts/provision_order_status_retry_index.py --apply --backfill   # and tag old rows
"""
from __future__ import annotations

import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-InvoicesTable"
INDEX = "orderStatusRetry-index"
HASH_KEY, RANGE_KEY = "orderStatusRetry", "pendingOrderStatusAt"
NON_KEY = ["pendingOrderStatus", "pendingOrderStatusSince"]
PENDING = "PENDING"
MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # razorpay `_ORDER_STATUS_RETRY_MAX_AGE_SECONDS`
MAX_BACKFILL_ITEMS = 5000
POLL_SECONDS, POLL_ATTEMPTS = 10, 90  # 15 minutes

INDEX_DEFINITION = {
    "IndexName": INDEX,
    "KeySchema": [{"AttributeName": HASH_KEY, "KeyType": "HASH"},
                  {"AttributeName": RANGE_KEY, "KeyType": "RANGE"}],
    "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": NON_KEY},
}


def describe(ddb) -> dict:
    return ddb.describe_table(TableName=TABLE)["Table"]


def find_index(table: dict) -> dict | None:
    return next((g for g in table.get("GlobalSecondaryIndexes") or []
                 if g["IndexName"] == INDEX), None)


def drift(index: dict) -> str:
    keys = [(k["AttributeName"], k["KeyType"]) for k in index["KeySchema"]]
    projection = index.get("Projection") or {}
    if keys != [(HASH_KEY, "HASH"), (RANGE_KEY, "RANGE")]:
        return f"KEY DRIFT: live keys {keys}"
    if (projection.get("ProjectionType") != "INCLUDE"
            or sorted(projection.get("NonKeyAttributes") or []) != sorted(NON_KEY)):
        return f"PROJECTION DRIFT: live {projection}"
    return ""


def wait_active(ddb) -> str:
    for _ in range(POLL_ATTEMPTS):
        index = find_index(describe(ddb))
        status = (index or {}).get("IndexStatus")
        if status == "ACTIVE":
            return "ACTIVE"
        time.sleep(POLL_SECONDS)
    return f"still {status} after {POLL_SECONDS * POLL_ATTEMPTS}s; re-run to keep waiting"


def ensure_index(ddb, apply: bool) -> tuple[bool, str]:
    table = describe(ddb)
    index = find_index(table)
    if index is not None:
        problem = drift(index)
        if problem:
            return False, f"{INDEX} exists but differs: {problem}. Not reconciled."
        status = index.get("IndexStatus")
        if status != "ACTIVE" and apply:
            return True, f"{INDEX} exists ({status}); {wait_active(ddb)}"
        return status == "ACTIVE" or not apply, f"{INDEX} exists, {status}, definition matches"
    if any(g.get("IndexStatus") != "ACTIVE" for g in table.get("GlobalSecondaryIndexes") or []):
        return False, "another index on the table is not ACTIVE; one GSI operation at a time"
    if not apply:
        return True, (f"would create {INDEX} on {TABLE}: {HASH_KEY} (HASH, S) / {RANGE_KEY} "
                      f"(RANGE, N), INCLUDE {NON_KEY}")
    ddb.update_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": HASH_KEY, "AttributeType": "S"},
                              {"AttributeName": RANGE_KEY, "AttributeType": "N"}],
        GlobalSecondaryIndexUpdates=[{"Create": INDEX_DEFINITION}],
    )
    state = wait_active(ddb)
    return state == "ACTIVE", f"creation requested; {state}"


def backfill(ddb, apply: bool) -> tuple[bool, str]:
    table = describe(ddb)
    if int(table.get("ItemCount") or 0) > MAX_BACKFILL_ITEMS:
        return False, (f"refused: about {table['ItemCount']} items, above {MAX_BACKFILL_ITEMS}; "
                       f"a one-off scan is the wrong tool at that size")
    now = int(time.time())
    candidates: list[str] = []
    scanned, kwargs = 0, {
        "TableName": TABLE,
        "ProjectionExpression": "invoiceId, pendingOrderStatus, #at, #retry",
        "FilterExpression": "attribute_exists(pendingOrderStatus) AND attribute_not_exists(#retry)",
        "ExpressionAttributeNames": {"#at": RANGE_KEY, "#retry": HASH_KEY},
    }
    for _ in range(MAX_BACKFILL_ITEMS // 100 + 1):  # bounded by the item cap above
        page = ddb.scan(Limit=100, **kwargs)
        scanned += int(page.get("ScannedCount") or 0)
        for item in page.get("Items") or []:
            at = (item.get(RANGE_KEY) or {}).get("N")
            if at is not None and now - int(float(at)) <= MAX_AGE_SECONDS:
                candidates.append(item["invoiceId"]["S"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    else:
        return False, f"stopped after {scanned} items without reaching the end; nothing written"
    if not apply:
        return True, f"scanned {scanned}; {len(candidates)} deferred row(s) inside 7 days would be tagged"
    tagged = lost = 0
    for invoice_id in candidates:
        try:
            ddb.update_item(
                TableName=TABLE, Key={"invoiceId": {"S": invoice_id}},
                UpdateExpression=("SET #retry = :pending, "
                                  "pendingOrderStatusSince = if_not_exists(pendingOrderStatusSince, #at)"),
                ConditionExpression=("attribute_exists(pendingOrderStatus) AND "
                                     "attribute_not_exists(#retry) AND attribute_exists(#at)"),
                ExpressionAttributeNames={"#retry": HASH_KEY, "#at": RANGE_KEY},
                ExpressionAttributeValues={":pending": {"S": PENDING}},
            )
            tagged += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            lost += 1  # resolved or tagged by the engine in between
    return True, f"scanned {scanned}; tagged {tagged}, {lost} changed underneath and were left alone"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="create the index (and backfill)")
    ap.add_argument("--backfill", action="store_true", help="tag rows deferred before the index")
    args = ap.parse_args()
    ddb = boto3.client("dynamodb", region_name=REGION)

    ok, note = ensure_index(ddb, args.apply)
    print(f"index: {note}")
    if not ok:
        return 1
    if args.backfill:
        if args.apply and (find_index(describe(ddb)) or {}).get("IndexStatus") != "ACTIVE":
            print("backfill: refused until the index is ACTIVE")
            return 1
        ok, note = backfill(ddb, args.apply)
        print(f"backfill: {note}")
        if not ok:
            return 1
    if args.apply:
        index = find_index(describe(ddb)) or {}
        page = ddb.query(TableName=TABLE, IndexName=INDEX, Select="COUNT",
                         KeyConditionExpression="#retry = :pending",
                         ExpressionAttributeNames={"#retry": HASH_KEY},
                         ExpressionAttributeValues={":pending": {"S": PENDING}})
        print(f"verify: {INDEX} {index.get('IndexStatus')}, {page.get('Count', 0)} row(s) awaiting retry")
    else:
        print("dry run: nothing written (pass --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
