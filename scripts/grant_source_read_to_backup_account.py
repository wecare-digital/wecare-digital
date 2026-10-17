#!/usr/bin/env python3
"""Grant the backup account read on the source media bucket, for the one-time backfill.

Why this exists
---------------
Cross-account S3 replication only copies objects written AFTER it was enabled. To
backfill the pre-existing media into the backup account's bucket, the backup
account must `aws s3 sync` FROM the source bucket `wecare-digital-get` — which needs
read (GetObject + ListBucket) on the source, granted by the SOURCE bucket's policy.
This runs in PRODUCTION (which owns the source bucket) and adds exactly that grant,
scoped to the backup account `991322955408`, read-only.

It is additive and reversible: it appends two statements to the existing bucket
policy and can be removed with --revoke once the backfill is done. It never grants
write or delete on the source.

    python scripts/grant_source_read_to_backup_account.py --plan
    python scripts/grant_source_read_to_backup_account.py --apply
    python scripts/grant_source_read_to_backup_account.py --revoke   # remove after backfill
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
SRC_BUCKET = "wecare-digital-get"
SRC_ARN = f"arn:aws:s3:::{SRC_BUCKET}"
BACKUP_ACCOUNT = "991322955408"
SID_OBJ = "BackupAccountBackfillRead"
SID_LIST = "BackupAccountBackfillList"


def s3():
    return boto3.client("s3", region_name=REGION)


def current_policy() -> dict:
    try:
        return json.loads(s3().get_bucket_policy(Bucket=SRC_BUCKET)["Policy"])
    except ClientError:
        return {"Version": "2012-10-17", "Statement": []}


def grant_statements() -> list[dict]:
    principal = {"AWS": f"arn:aws:iam::{BACKUP_ACCOUNT}:root"}
    return [
        {"Sid": SID_OBJ, "Effect": "Allow", "Principal": principal,
         "Action": ["s3:GetObject", "s3:GetObjectVersion"],
         "Resource": f"{SRC_ARN}/*"},
        {"Sid": SID_LIST, "Effect": "Allow", "Principal": principal,
         "Action": ["s3:ListBucket", "s3:ListBucketVersions"],
         "Resource": SRC_ARN},
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revoke", action="store_true")
    args = ap.parse_args()

    pol = current_policy()
    others = [s for s in pol.get("Statement", []) if s.get("Sid") not in (SID_OBJ, SID_LIST)]
    present = len(others) != len(pol.get("Statement", []))
    print(f"source bucket    : {SRC_BUCKET}")
    print(f"backfill grant present : {present}")

    if args.plan:
        print(f"would {'REMOVE' if False else 'ADD'} read grant for {BACKUP_ACCOUNT} "
              "(GetObject + ListBucket, read-only)")
        return 0

    if args.revoke:
        pol["Statement"] = others
        s3().put_bucket_policy(Bucket=SRC_BUCKET, Policy=json.dumps(pol))
        print(f"revoked backfill read grant for {BACKUP_ACCOUNT}")
        return 0

    # --apply
    pol["Statement"] = others + grant_statements()
    try:
        s3().put_bucket_policy(Bucket=SRC_BUCKET, Policy=json.dumps(pol))
    except ClientError as exc:
        print(f"put_bucket_policy failed: {exc.response['Error']['Code']}: "
              f"{exc.response['Error']['Message']}", file=sys.stderr)
        return 1
    print(f"granted {BACKUP_ACCOUNT} read-only on {SRC_BUCKET} for backfill.")
    print("Now, in the BACKUP ACCOUNT (991322955408):")
    print(f"  aws s3 sync s3://{SRC_BUCKET}/ s3://wecare-digital-get-replica-xacct/ "
          "--source-region us-east-1 --region us-east-1")
    print("Then revoke: python scripts/grant_source_read_to_backup_account.py --revoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
