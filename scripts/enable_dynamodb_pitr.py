#!/usr/bin/env python3
"""Enable DynamoDB point-in-time recovery (PITR) on every live project table.

Why this exists
---------------
PITR is the continuous, 35-day rolling backup that lets a table be restored to
any second in the window — the single most important protection against "a bad
deploy or a bad actor corrupted rows an hour ago" and against an accidental table
drop. `docs/migrations/backup-and-dr-plan.md` §4.2 calls for it on every table;
this script is the enforcement. It is idempotent: a table that already has PITR is
reported and skipped, so it is safe to re-run after new tables are provisioned.

Scope
-----
Only this project's tables are touched, identified two ways:

* the `stack-wecare-digital-*` naming scheme the Lambda fleet addresses, and

Any other table in the account is listed under "skipped (not a project table)"
and left untouched — this script never enables PITR on something it does not own.

Usage
-----
    python scripts/enable_dynamodb_pitr.py --plan      # show what would change
    python scripts/enable_dynamodb_pitr.py --apply     # enable PITR where missing
    python scripts/enable_dynamodb_pitr.py --verify     # report PITR status only

Exit codes: 0 success (or --verify with everything enabled), 1 one or more
operations failed, 2 --verify found a project table without PITR.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
PREFIX = "stack-wecare-digital-"
# No current project DynamoDB tables live outside the shared prefix.
EXTRA_PROJECT_TABLES: set[str] = set()


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def all_tables(client) -> list[str]:
    names: list[str] = []
    for page in client.get_paginator("list_tables").paginate():
        names.extend(page.get("TableNames", []))
    return sorted(names)


def is_project_table(name: str) -> bool:
    return name.startswith(PREFIX) or name in EXTRA_PROJECT_TABLES


def pitr_status(client, name: str) -> str:
    """ENABLED / DISABLED, or an error code string if the describe failed."""
    try:
        resp = client.describe_continuous_backups(TableName=name)
    except ClientError as exc:
        return exc.response["Error"]["Code"]
    return resp["ContinuousBackupsDescription"][
        "PointInTimeRecoveryDescription"
    ]["PointInTimeRecoveryStatus"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="show changes, mutate nothing")
    g.add_argument("--apply", action="store_true", help="enable PITR where missing")
    g.add_argument("--verify", action="store_true", help="report PITR status only")
    args = ap.parse_args()

    client = ddb()
    tables = all_tables(client)
    project = [t for t in tables if is_project_table(t)]
    skipped = [t for t in tables if not is_project_table(t)]

    print(f"region={REGION}  tables_total={len(tables)}  "
          f"project={len(project)}  other={len(skipped)}\n")

    enabled, missing, failed = [], [], []
    for name in project:
        status = pitr_status(client, name)
        if status == "ENABLED":
            enabled.append(name)
        else:
            missing.append((name, status))

    if args.verify:
        print(f"PITR ENABLED : {len(enabled)}")
        for n in enabled:
            print(f"   ok   {n}")
        print(f"\nPITR NOT ENABLED : {len(missing)}")
        for n, s in missing:
            print(f"   !!   {n}  ({s})")
        print(f"\nother tables (ignored): {len(skipped)}")
        return 2 if missing else 0

    if args.plan:
        print(f"already ENABLED : {len(enabled)}")
        print(f"would ENABLE    : {len(missing)}")
        for n, s in missing:
            print(f"   -> {n}  (currently {s})")
        print(f"\nwould skip (not project tables): {len(skipped)}")
        return 0

    # --apply
    print(f"already ENABLED (skipped): {len(enabled)}")
    for name, _status in missing:
        try:
            client.update_continuous_backups(
                TableName=name,
                PointInTimeRecoverySpecification={
                    "PointInTimeRecoveryEnabled": True
                },
            )
            print(f"   ENABLED  {name}")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            print(f"   FAILED   {name}  ({code})", file=sys.stderr)
            failed.append(name)

    print(f"\nsummary: enabled_now={len(missing) - len(failed)}  "
          f"already_on={len(enabled)}  failed={len(failed)}  "
          f"untouched_other={len(skipped)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
