"""Opt-in backfill of canonical Subscriber IDs and creation locks on legacy rows.

Dry-run by default. Never overwrites existing IDs, workspace ownership or
retention locks. Apply uses one conditional UpdateItem per row and fails closed
if the row changes concurrently. Operators must review the plan before --apply.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
from lambda_utils.identity import subscriber_id  # noqa: E402

TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")


def backfill(table, *, apply=False):
    workspace = subscriber_id.current_workspace_id()
    stats = {"scanned": 0, "would_update": 0, "updated": 0, "conflicts": 0}
    kwargs = {}
    while True:
        response = table.scan(**kwargs)
        for row in response.get("Items", []):
            stats["scanned"] += 1
            if row.get("deletedAt") is not None:
                continue
            # Do not reassign a row belonging to a different workspace.
            if row.get("workspaceId") not in (None, workspace):
                stats["conflicts"] += 1
                continue
            if row.get("subscriberId") and not subscriber_id.is_subscriber_id(
                    row["subscriberId"], workspace_id=workspace):
                stats["conflicts"] += 1
                continue
            if row.get("subscriberId") and row.get("locked") is True and row.get("workspaceId"):
                continue
            stats["would_update"] += 1
            if not apply:
                continue
            now = int(time.time())
            values = {
                ":sid": subscriber_id.new_subscriber_id(workspace_id=workspace),
                ":ws": workspace,
                ":locked": True,
                ":reason": "migration",
                ":at": now,
            }
            try:
                table.update_item(
                    Key={"id": row["id"]},
                    UpdateExpression=(
                        "SET subscriberId=if_not_exists(subscriberId,:sid), "
                        "workspaceId=if_not_exists(workspaceId,:ws), "
                        "locked=if_not_exists(locked,:locked), "
                        "lockedReason=if_not_exists(lockedReason,:reason), "
                        "lockedAt=if_not_exists(lockedAt,:at)"
                    ),
                    ConditionExpression=(
                        "attribute_exists(id) AND "
                        "(attribute_not_exists(workspaceId) OR workspaceId=:ws)"
                    ),
                    ExpressionAttributeValues=values,
                )
                stats["updated"] += 1
            except Exception:
                stats["conflicts"] += 1
        if not response.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = backfill(boto3.resource("dynamodb").Table(TABLE), apply=args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **result}, indent=2))
