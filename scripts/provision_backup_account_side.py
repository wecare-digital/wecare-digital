#!/usr/bin/env python3
"""Backup-account-side setup. RUN THIS WITH THE BACKUP ACCOUNT'S CREDENTIALS.

This runs in the DEDICATED BACKUP ACCOUNT `991322955408`, NOT in production. It
creates the destination resources that production copies/replicates into, and —
critically — it is where the IRREVERSIBLE compliance-mode Vault Lock lives, so that
even a full compromise of the production account cannot delete the archived copies.

It will refuse to run if the caller is not account 991322955408, so it cannot be
run against production by mistake.

What it creates
---------------
1. Backup vault `wecare-backup-vault` (destination for prod's cross-account copies).
2. A vault ACCESS POLICY allowing the production account to COPY INTO it, and
   nothing else — prod gets no delete, no describe-and-purge.
3. (Optional, --compliance-lock) COMPLIANCE-mode Vault Lock. THIS IS IRREVERSIBLE:
   once the cooling-off window passes, neither you nor AWS can delete the vault,
   its recovery points, or shorten retention. That irreversibility is the entire
   point of a backup account. Requires an explicit extra flag and prints a loud
   confirmation; omit it to apply only the (removable) governance lock.
4. S3 destination bucket `wecare-digital-get-replica-xacct` for cross-account S3
   replication, with a bucket policy granting the prod replication role write.

Usage (with backup-account creds, e.g. AWS_PROFILE=wecare-backup)
----------------------------------------------------------------
    python scripts/provision_backup_account_side.py --plan
    python scripts/provision_backup_account_side.py --apply                  # governance lock
    python scripts/provision_backup_account_side.py --apply --compliance-lock # IRREVERSIBLE

Exit codes: 0 ok, 1 failure, 2 wrong account / refused.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
PROD_ACCOUNT = "775261844268"
BACKUP_ACCOUNT = "991322955408"

VAULT = "wecare-backup-vault"
DEST_BUCKET = "wecare-digital-get-replica-xacct"
DEST_BUCKET_ARN = f"arn:aws:s3:::{DEST_BUCKET}"
# The prod replication role that will write into the dest bucket.
PROD_REPL_ROLE_ARN = f"arn:aws:iam::{PROD_ACCOUNT}:role/wecare-s3-replication-role"


def whoami() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def guard_account() -> None:
    acct = whoami()
    if acct != BACKUP_ACCOUNT:
        print(f"REFUSING: this must run in the backup account {BACKUP_ACCOUNT}, "
              f"but the current credentials are for {acct}. "
              "Switch to the backup account's profile and re-run.", file=sys.stderr)
        raise SystemExit(2)


def vault_access_policy() -> dict:
    # Allow the production account to COPY recovery points in; deny delete.
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowProdCopyIn",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{PROD_ACCOUNT}:root"},
                "Action": ["backup:CopyIntoBackupVault"],
                "Resource": "*",
            },
            {
                "Sid": "DenyProdDelete",
                "Effect": "Deny",
                "Principal": {"AWS": f"arn:aws:iam::{PROD_ACCOUNT}:root"},
                "Action": [
                    "backup:DeleteRecoveryPoint",
                    "backup:UpdateRecoveryPointLifecycle",
                    "backup:DeleteBackupVault",
                ],
                "Resource": "*",
            },
        ],
    }


def dest_bucket_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowProdReplication",
                "Effect": "Allow",
                "Principal": {"AWS": PROD_REPL_ROLE_ARN},
                "Action": [
                    "s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags",
                    "s3:GetObjectVersionTagging", "s3:ObjectOwnerOverrideToBucketOwner",
                ],
                "Resource": f"{DEST_BUCKET_ARN}/*",
            },
            {
                "Sid": "AllowProdReplicationList",
                "Effect": "Allow",
                "Principal": {"AWS": PROD_REPL_ROLE_ARN},
                "Action": ["s3:List*", "s3:GetBucketVersioning", "s3:PutBucketVersioning"],
                "Resource": DEST_BUCKET_ARN,
            },
            {
                "Sid": "DenyNonTLS", "Effect": "Deny", "Principal": "*",
                "Action": "s3:*",
                "Resource": [DEST_BUCKET_ARN, f"{DEST_BUCKET_ARN}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            },
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--compliance-lock", action="store_true",
                    help="apply IRREVERSIBLE compliance-mode Vault Lock")
    args = ap.parse_args()
    guard_account()
    apply = args.apply
    bk = boto3.client("backup", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    if args.plan:
        print(f"[plan] in backup account {BACKUP_ACCOUNT}:")
        print(f"  - create vault {VAULT} + access policy (prod may copy-in, not delete)")
        print(f"  - {'COMPLIANCE (irreversible)' if args.compliance_lock else 'governance'} Vault Lock")
        print(f"  - create S3 bucket {DEST_BUCKET} + policy for prod repl role")
        return 0

    if args.verify:
        try:
            bk.describe_backup_vault(BackupVaultName=VAULT)
            print(f"vault present : True ({VAULT})")
        except ClientError:
            print("vault present : False"); return 2
        try:
            s3.head_bucket(Bucket=DEST_BUCKET)
            print(f"dest bucket   : present ({DEST_BUCKET})")
        except ClientError:
            print("dest bucket   : MISSING"); return 2
        return 0

    # --apply
    try:
        bk.create_backup_vault(BackupVaultName=VAULT)
        print(f"  created vault {VAULT}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "AlreadyExistsException":
            raise
        print(f"  vault {VAULT} already exists")
    bk.put_backup_vault_access_policy(
        BackupVaultName=VAULT, Policy=json.dumps(vault_access_policy()))
    print("  vault access policy set (prod copy-in allowed, delete denied)")

    if args.compliance_lock:
        print("\n  *** COMPLIANCE-MODE VAULT LOCK — IRREVERSIBLE ***")
        bk.put_backup_vault_lock_configuration(
            BackupVaultName=VAULT,
            MinRetentionDays=35, MaxRetentionDays=366,
            ChangeableForDays=3,  # mandatory cooling-off before it becomes immutable
        )
        print("  compliance lock set with a 3-day cooling-off; immutable thereafter.")
    else:
        bk.put_backup_vault_lock_configuration(
            BackupVaultName=VAULT, MinRetentionDays=35, MaxRetentionDays=366)
        print("  governance lock set (reversible by a backup-account admin).")

    # S3 destination bucket for cross-account replication.
    try:
        s3.create_bucket(Bucket=DEST_BUCKET)
        print(f"  created S3 bucket {DEST_BUCKET}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou",
                                                 "BucketAlreadyExists"):
            raise
        print(f"  bucket {DEST_BUCKET} already exists")
    s3.put_public_access_block(
        Bucket=DEST_BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_versioning(
        Bucket=DEST_BUCKET, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_policy(Bucket=DEST_BUCKET, Policy=json.dumps(dest_bucket_policy()))
    print("  dest bucket: versioned, public-access-blocked, prod-repl policy, TLS-only")
    print("\nDONE (backup account). Now, in PRODUCTION, run:")
    print("  python scripts/provision_cross_account_backup.py --apply")
    print("  python scripts/provision_s3_replication.py --apply   (xacct dest)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
