#!/usr/bin/env python3
"""Standard backup posture for a DynamoDB table: PITR + the AWS Backup tag.

Why this exists
---------------
The AWS Backup plan (`scripts/provision_aws_backup.py`) selects tables by the tag
`backup=daily`, and continuous recovery depends on PITR. Both were applied to the
75 tables that existed on 2026-10-16, but a table provisioned LATER joins neither
until someone remembers to. That "someone remembers" is exactly the gap
`docs/migrations/backup-and-dr-plan.md` §4.2 warns about.

This is the one-line call every `provision_*_table.py` (and any domain script that
creates a table) should make right after the table becomes ACTIVE, so coverage is
a property of creating a table, not a follow-up chore:

    import table_backup_defaults
    table_backup_defaults.apply(table_name)   # PITR on + backup=daily tag

It is idempotent and safe to call repeatedly. It NEVER reads or writes table data —
only the continuous-backups setting and the resource tag.

Direct use (for a one-off / backfill of a single table):

    python scripts/table_backup_defaults.py stack-wecare-digital-NewThing
    python scripts/table_backup_defaults.py --verify stack-wecare-digital-NewThing
"""
from __future__ import annotations

import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
BACKUP_TAG_KEY = "backup"
BACKUP_TAG_VALUE = "daily"


def _ddb():
    return boto3.client("dynamodb", region_name=REGION)


def _table_arn(table_name: str) -> str:
    return f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{table_name}"


def pitr_status(table_name: str, client=None) -> str:
    client = client or _ddb()
    resp = client.describe_continuous_backups(TableName=table_name)
    return resp["ContinuousBackupsDescription"][
        "PointInTimeRecoveryDescription"
    ]["PointInTimeRecoveryStatus"]


def has_backup_tag(table_name: str, client=None) -> bool:
    client = client or _ddb()
    tags = client.list_tags_of_resource(ResourceArn=_table_arn(table_name)).get("Tags", [])
    return any(t["Key"] == BACKUP_TAG_KEY and t["Value"] == BACKUP_TAG_VALUE
              for t in tags)


def apply(table_name: str, client=None) -> dict:
    """Enable PITR and the backup=daily tag on a table. Idempotent.

    Returns a small dict describing what it did, so a caller can log it.
    """
    client = client or _ddb()
    result = {"table": table_name, "pitr": "unknown", "tagged": False}

    # PITR — only toggle if not already on, so a re-run is a no-op.
    try:
        if pitr_status(table_name, client) != "ENABLED":
            client.update_continuous_backups(
                TableName=table_name,
                PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
            )
        result["pitr"] = "ENABLED"
    except ClientError as exc:
        result["pitr"] = f"error:{exc.response['Error']['Code']}"

    # Tag — tag_resource is itself idempotent (re-tagging the same value is a no-op).
    try:
        client.tag_resource(
            ResourceArn=_table_arn(table_name),
            Tags=[{"Key": BACKUP_TAG_KEY, "Value": BACKUP_TAG_VALUE}],
        )
        result["tagged"] = True
    except ClientError as exc:
        result["tagged"] = f"error:{exc.response['Error']['Code']}"

    return result


def main() -> int:
    args = sys.argv[1:]
    verify = "--verify" in args
    names = [a for a in args if not a.startswith("--")]
    if not names:
        print("usage: table_backup_defaults.py [--verify] <table-name> [<table-name>...]",
              file=sys.stderr)
        return 2

    client = _ddb()
    rc = 0
    for name in names:
        if verify:
            try:
                p = pitr_status(name, client)
                t = has_backup_tag(name, client)
            except ClientError as exc:
                print(f"{name}: ERROR {exc.response['Error']['Code']}")
                rc = 1
                continue
            ok = p == "ENABLED" and t
            print(f"{name}: pitr={p} backup_tag={'yes' if t else 'NO'} "
                  f"{'OK' if ok else 'INCOMPLETE'}")
            if not ok:
                rc = 2
        else:
            r = apply(name, client)
            print(f"{name}: pitr={r['pitr']} tagged={r['tagged']}")
            if "error" in str(r["pitr"]) or "error" in str(r["tagged"]):
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
