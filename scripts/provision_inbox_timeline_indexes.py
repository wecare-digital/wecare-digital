"""Inspect/create additive chronological indexes on the manually managed MessagesTable.

Default is inspection only. On an explicitly confirmed account/table, --apply
creates at most one missing index. It never scans message data, changes items,
alters existing indexes, or activates an application flag.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "amplify/functions/shared"))
from lambda_utils.inbox_timeline_indexes import INDEXES, TIME_KEY, all_active, index_definition, timeline_indexes


def create_next(ddb, table_name, table, read_capacity=None, write_capacity=None):
    found = timeline_indexes(table)
    missing = [key for key in INDEXES if key not in found]
    if not missing:
        return None
    if table.get("TableStatus") != "ACTIVE" or any(
        index.get("IndexStatus") != "ACTIVE" or index.get("Backfilling")
        for index in table.get("GlobalSecondaryIndexes") or []
    ):
        raise ValueError("Wait for the table and its other indexes to be ACTIVE before creating another index.")
    partition = missing[0]
    index = index_definition(partition)
    if (table.get("BillingModeSummary") or {}).get("BillingMode") != "PAY_PER_REQUEST":
        if not read_capacity or not write_capacity or min(read_capacity, write_capacity) < 1:
            raise ValueError("A provisioned table requires explicit positive --read-capacity and --write-capacity.")
        index["ProvisionedThroughput"] = {
            "ReadCapacityUnits": read_capacity, "WriteCapacityUnits": write_capacity,
        }
    ddb.update_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": partition, "AttributeType": "S"},
            {"AttributeName": TIME_KEY, "AttributeType": "N"},
        ],
        GlobalSecondaryIndexUpdates=[{"Create": index}],
    )
    return index["IndexName"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True, help="Exact canonical table name, never an Amplify Message table")
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", help="Exact AWS account number, required with --apply")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--read-capacity", type=int)
    parser.add_argument("--write-capacity", type=int)
    args = parser.parse_args()
    if args.apply and not args.expected_account:
        parser.error("--apply requires --expected-account")

    try:
        session = boto3.Session(region_name=args.region)
        identity = session.client("sts").get_caller_identity()
        if args.expected_account and identity["Account"] != args.expected_account:
            raise ValueError("AWS caller does not match the requested account.")
        ddb = session.client("dynamodb")
        table = ddb.describe_table(TableName=args.table)["Table"]
        found = timeline_indexes(table)
        for partition, name in INDEXES.items():
            index = found.get(partition)
            status = index.get("IndexStatus", "UNKNOWN") if index else "MISSING"
            print(f"{name}: {status}" + (" (backfilling)" if index and index.get("Backfilling") else ""))
        if all_active(table):
            print("Both ordered timeline indexes are ACTIVE.")
        elif args.apply:
            created = create_next(ddb, args.table, table, args.read_capacity, args.write_capacity)
            if created:
                print(f"Requested {created}; recheck after it becomes ACTIVE.")
            else:
                print("Both indexes exist but are not ready. Recheck after they become ACTIVE.")
        else:
            print("Inspection only. Ordered history is not ready.")
        return 0
    except (BotoCoreError, ClientError, ValueError) as exc:
        print(f"Unable to proceed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
