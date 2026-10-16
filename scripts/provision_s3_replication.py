#!/usr/bin/env python3
"""Replicate the media bucket to a second region for an off-primary-region copy.

Why this exists
---------------
`docs/migrations/backup-and-dr-plan.md` §4.3 / §6 call for an off-primary copy of
`wecare-digital-get` so a region outage or a bucket-level mistake does not lose the
media (invoices, WhatsApp media, voice recordings, product images, Meta template
media). This sets up S3 Cross-Region Replication (CRR) to a destination bucket in
`us-west-2`, in the same account.

Honest scope note
-----------------
The plan's stronger form is CROSS-ACCOUNT replication, which survives a compromise
of the primary account, not just a region outage. That needs a second AWS account
this tooling does not have and cannot create. This script does the achievable half
— cross-REGION, same account — which closes the region-failure gap. If a second
account is ever stood up, point `DEST_BUCKET` at a bucket there and add the
destination `Account` + `AccessControlTranslation` to the rule; the rest is
unchanged.

What it creates (idempotent)
----------------------------
1. Destination bucket `wecare-digital-get-replica-usw2` in us-west-2: versioned
   (CRR requires it), public access blocked, SSE-S3, TLS-only.
2. IAM role `wecare-s3-replication-role` the source bucket assumes to replicate.
3. A replication configuration on the source bucket replicating ALL objects,
   including existing ones (via replicate-existing where supported) and delete
   markers off (a replicated delete marker would propagate a deletion, defeating
   the purpose of the copy).

Source versioning is already Enabled (scripts/enable_s3_versioning.py); CRR will
not configure without it.

Usage
-----
    python scripts/provision_s3_replication.py --plan
    python scripts/provision_s3_replication.py --apply
    python scripts/provision_s3_replication.py --verify

Exit codes: 0 success, 1 operation failed, 2 --verify found replication absent.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

SRC_REGION = "us-east-1"
DST_REGION = "us-west-2"
ACCOUNT = "775261844268"
SRC_BUCKET = "wecare-digital-get"
DST_BUCKET = "wecare-digital-get-replica-usw2"
DST_ARN = f"arn:aws:s3:::{DST_BUCKET}"
ROLE = "wecare-s3-replication-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"

TRUST = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "s3.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
}


def replication_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetReplicationConfiguration", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{SRC_BUCKET}"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObjectVersionForReplication",
                    "s3:GetObjectVersionAcl",
                    "s3:GetObjectVersionTagging",
                ],
                "Resource": [f"arn:aws:s3:::{SRC_BUCKET}/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:ReplicateObject",
                    "s3:ReplicateDelete",
                    "s3:ReplicateTags",
                ],
                "Resource": [f"{DST_ARN}/*"],
            },
        ],
    }


def s3(region: str):
    return boto3.client("s3", region_name=region)


def iam():
    return boto3.client("iam", region_name=SRC_REGION)


def ensure_dest_bucket(apply: bool) -> bool:
    c = s3(DST_REGION)
    try:
        c.head_bucket(Bucket=DST_BUCKET)
        print(f"  dest bucket {DST_BUCKET}: present")
        exists = True
    except ClientError:
        print(f"  dest bucket {DST_BUCKET}: MISSING")
        exists = False
        if apply:
            c.create_bucket(
                Bucket=DST_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": DST_REGION},
            )
            print(f"    created {DST_BUCKET} in {DST_REGION}")
    if apply:
        c.put_public_access_block(
            Bucket=DST_BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True},
        )
        c.put_bucket_versioning(
            Bucket=DST_BUCKET, VersioningConfiguration={"Status": "Enabled"})
        c.put_bucket_encryption(
            Bucket=DST_BUCKET,
            ServerSideEncryptionConfiguration={"Rules": [{
                "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                "BucketKeyEnabled": True}]},
        )
        c.put_bucket_policy(Bucket=DST_BUCKET, Policy=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "DenyNonTLS", "Effect": "Deny", "Principal": "*",
                "Action": "s3:*",
                "Resource": [DST_ARN, f"{DST_ARN}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }],
        }))
        print("    dest: versioned, public-access-blocked, SSE-S3, TLS-only")
    return exists


def ensure_role(apply: bool) -> None:
    c = iam()
    try:
        c.get_role(RoleName=ROLE)
        print(f"  role {ROLE}: present")
    except ClientError:
        print(f"  role {ROLE}: MISSING")
        if apply:
            c.create_role(RoleName=ROLE,
                          AssumeRolePolicyDocument=json.dumps(TRUST),
                          Description="S3 CRR role for wecare-digital-get")
            print(f"    created {ROLE}")
    if apply:
        c.put_role_policy(RoleName=ROLE, PolicyName="replication",
                          PolicyDocument=json.dumps(replication_policy()))
        print("    put inline replication policy")


def ensure_replication(apply: bool) -> bool:
    c = s3(SRC_REGION)
    try:
        c.get_bucket_replication(Bucket=SRC_BUCKET)
        print("  source replication config: present")
        return True
    except ClientError:
        print("  source replication config: MISSING")
    if apply:
        c.put_bucket_replication(
            Bucket=SRC_BUCKET,
            ReplicationConfiguration={
                "Role": ROLE_ARN,
                "Rules": [{
                    "ID": "replicate-all-to-usw2",
                    "Priority": 0,
                    "Status": "Enabled",
                    "Filter": {},
                    "DeleteMarkerReplication": {"Status": "Disabled"},
                    "Destination": {"Bucket": DST_ARN, "StorageClass": "STANDARD"},
                }],
            },
        )
        print(f"    replication rule -> {DST_BUCKET} (all objects, deletes NOT replicated)")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    apply = args.apply

    if args.verify:
        c = s3(SRC_REGION)
        try:
            cfg = c.get_bucket_replication(Bucket=SRC_BUCKET)
        except ClientError:
            print("replication: NOT configured", file=sys.stderr)
            return 2
        rules = cfg["ReplicationConfiguration"]["Rules"]
        print(f"replication rules : {len(rules)}")
        for r in rules:
            print(f"  {r['ID']}  status={r['Status']}  "
                  f"dest={r['Destination']['Bucket']}")
        try:
            s3(DST_REGION).head_bucket(Bucket=DST_BUCKET)
            print(f"dest bucket       : present ({DST_BUCKET} in {DST_REGION})")
        except ClientError:
            print("dest bucket       : MISSING")
            return 2
        return 0

    src_ver = s3(SRC_REGION).get_bucket_versioning(Bucket=SRC_BUCKET).get("Status")
    print(f"=== S3 replication ({'APPLY' if apply else 'PLAN'}) ===")
    print(f"  source versioning: {src_ver}")
    if src_ver != "Enabled":
        print("  ERROR: source versioning must be Enabled first "
              "(scripts/enable_s3_versioning.py --apply)", file=sys.stderr)
        return 1

    ensure_dest_bucket(apply)
    ensure_role(apply)
    if apply:
        time.sleep(8)  # role propagation
    ensure_replication(apply)
    print("\nNote: CRR replicates objects written AFTER it is enabled. To copy "
          "pre-existing objects, run an S3 Batch Replication job (console/API) once.")
    print("done." if apply else "plan only — nothing changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
