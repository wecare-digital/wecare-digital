#!/usr/bin/env python3
"""Add CROSS-ACCOUNT S3 replication of the media bucket to the backup account.

Why this exists
---------------
`provision_s3_replication.py` set up cross-REGION replication to a same-account
bucket (`wecare-digital-get-replica-usw2`) — that survives a region outage. This
adds a SECOND replication destination: a bucket in the dedicated backup account
`991322955408`, which survives losing the PRODUCTION account entirely (compromise
or suspension). Both rules coexist; this does not replace the region replica.

Runs in PRODUCTION (`775261844268`). The destination bucket and its bucket policy
(granting this account's replication role write access) are created in the backup
account by the backup-account-side setup — that must be done first.

What it does (idempotent)
-------------------------
1. Extends the inline policy on `wecare-s3-replication-role` to allow replicate
   actions into the cross-account bucket.
2. Adds a second rule `replicate-all-to-backup-account` to the source bucket's
   replication config, with `AccessControlTranslation` so the backup account owns
   the replicated objects (required for cross-account), keeping the existing
   region-replica rule intact.

Usage
-----
    python scripts/provision_s3_replication_xacct.py --plan
    python scripts/provision_s3_replication_xacct.py --apply
    python scripts/provision_s3_replication_xacct.py --verify

Exit codes: 0 success, 1 failure, 2 --verify found the cross-account rule absent.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

SRC_REGION = "us-east-1"
PROD_ACCOUNT = "775261844268"
BACKUP_ACCOUNT = "991322955408"
SRC_BUCKET = "wecare-digital-get"
XACCT_BUCKET = "wecare-digital-get-replica-xacct"
XACCT_ARN = f"arn:aws:s3:::{XACCT_BUCKET}"
ROLE = "wecare-s3-replication-role"
ROLE_ARN = f"arn:aws:iam::{PROD_ACCOUNT}:role/{ROLE}"
RULE_ID = "replicate-all-to-backup-account"
REGION_RULE_ID = "replicate-all-to-usw2"


def s3():
    return boto3.client("s3", region_name=SRC_REGION)


def iam():
    return boto3.client("iam", region_name=SRC_REGION)


def extend_role_policy(apply: bool) -> None:
    """Add the cross-account bucket to the replication role's inline policy."""
    c = iam()
    doc = c.get_role_policy(RoleName=ROLE, PolicyName="replication")["PolicyDocument"]
    # Does a statement already allow ReplicateObject into the xacct bucket?
    def covers_xacct(stmt) -> bool:
        res = stmt.get("Resource", [])
        res = res if isinstance(res, list) else [res]
        return any(XACCT_BUCKET in r for r in res)
    if any(covers_xacct(s) for s in doc.get("Statement", [])):
        print("  role policy: already covers the cross-account bucket")
        return
    print("  role policy: cross-account bucket NOT yet allowed")
    if apply:
        doc["Statement"].append({
            "Effect": "Allow",
            "Action": ["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags",
                       "s3:ObjectOwnerOverrideToBucketOwner"],
            "Resource": [f"{XACCT_ARN}/*"],
        })
        c.put_role_policy(RoleName=ROLE, PolicyName="replication",
                          PolicyDocument=json.dumps(doc))
        print("    extended role policy to the cross-account bucket")


def current_rules():
    try:
        cfg = s3().get_bucket_replication(Bucket=SRC_BUCKET)
        return cfg["ReplicationConfiguration"]["Rules"], \
               cfg["ReplicationConfiguration"]["Role"]
    except ClientError:
        return [], ROLE_ARN


def has_xacct_rule(rules) -> bool:
    return any(r.get("Destination", {}).get("Bucket") == XACCT_ARN for r in rules)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    rules, role = current_rules()

    if args.verify:
        present = has_xacct_rule(rules)
        print(f"cross-account replication rule present : {present}")
        for r in rules:
            print(f"  {r['ID']}  status={r['Status']}  "
                  f"dest={r['Destination']['Bucket']}")
        return 0 if present else 2

    if has_xacct_rule(rules):
        print("cross-account replication rule already present — nothing to do")
        return 0

    if args.plan:
        print(f"would extend role {ROLE} policy to {XACCT_BUCKET}")
        print(f"would add rule {RULE_ID} -> {XACCT_ARN} "
              f"(keeping {len(rules)} existing rule(s))")
        return 0

    # --apply
    extend_role_policy(apply=True)

    # Existing region rule needs an explicit Priority once there are 2+ rules.
    new_rules = []
    for r in rules:
        rr = dict(r)
        rr.setdefault("Priority", 0)
        rr.setdefault("Filter", {})
        new_rules.append(rr)
    new_rules.append({
        "ID": RULE_ID,
        "Priority": 1,
        "Status": "Enabled",
        "Filter": {},
        "DeleteMarkerReplication": {"Status": "Disabled"},
        "Destination": {
            "Bucket": XACCT_ARN,
            "Account": BACKUP_ACCOUNT,
            "StorageClass": "STANDARD",
            # Cross-account: hand ownership to the destination account so the backup
            # account actually owns (and can read/restore) the replicated objects.
            "AccessControlTranslation": {"Owner": "Destination"},
        },
    })
    try:
        s3().put_bucket_replication(
            Bucket=SRC_BUCKET,
            ReplicationConfiguration={"Role": ROLE_ARN, "Rules": new_rules},
        )
    except ClientError as exc:
        print(f"put_bucket_replication failed: {exc.response['Error']['Code']}: "
              f"{exc.response['Error']['Message']}", file=sys.stderr)
        return 1
    print(f"added {RULE_ID} -> {XACCT_ARN} (account {BACKUP_ACCOUNT}); "
          f"region replica rule retained")
    print("Note: replicates objects written AFTER this. Backfill pre-existing media "
          "with: aws s3 sync s3://wecare-digital-get/ s3://"
          f"{XACCT_BUCKET}/ (run with a principal that can write both).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
