#!/usr/bin/env python3
"""Provision one AWS Backup plan covering DynamoDB + the media bucket.

Why this exists
---------------
PITR gives continuous 35-day recovery, but there is NO long-retention snapshot
layer: measured 2026-10-16 the account had 0 backup vaults and 0 backup plans.
`docs/migrations/backup-and-dr-plan.md` §4.6 calls for a single scheduled,
auditable plan that also reports success/failure to the existing SNS alarm topic,
so a FAILED backup pages you the way a failed deploy does.

What it creates (all idempotent)
--------------------------------
1. IAM role `wecare-backup-role` with the AWS-managed backup + S3-backup policies.
2. Backup vault `wecare-backup-vault`.
3. Backup plan `wecare-backup-plan` with two rules:
     - daily  @ 05:00 UTC, retain 35 days
     - monthly@ 05:00 UTC on the 1st, retain 365 days (cold storage after 90)
4. A TAG-BASED selection: everything tagged `backup=daily` is backed up. The
   script also APPLIES that tag to every `stack-wecare-digital-*` DynamoDB table,
   the two retained CDK tables, and the media bucket — so a newly provisioned
   table joins the plan the moment it carries the tag (the design in §4.2/§4.6).
5. SNS notifications to `stack-wecare-digital` on BACKUP_JOB_FAILED /
   RESTORE_JOB_FAILED / COPY_JOB_FAILED.

Vault Lock
----------
NOT applied here. Compliance-mode Vault Lock is irreversible — once the grace
period passes, neither you nor AWS can delete the vault or shorten retention. That
is the point, and also why it is a deliberate, separate owner decision rather than
a side effect of first provisioning. Governance-mode is reversible but adds an IAM
surface. The plan notes it; `--lock-governance` can be added later.

Usage
-----
    python scripts/provision_aws_backup.py --plan
    python scripts/provision_aws_backup.py --apply
    python scripts/provision_aws_backup.py --verify

Exit codes: 0 success, 1 an operation failed, 2 --verify found the plan absent.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"

ROLE = "wecare-backup-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
VAULT = "wecare-backup-vault"
PLAN_NAME = "wecare-backup-plan"
SELECTION = "wecare-backup-selection"
SNS_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:stack-wecare-digital"

BACKUP_TAG_KEY = "backup"
BACKUP_TAG_VALUE = "daily"

DDB_PREFIX = "stack-wecare-digital-"
EXTRA_DDB = {"ShortLinksTable", "LinkClicksTable"}
MEDIA_BUCKET = "wecare-digital-get"

MANAGED_POLICIES = [
    # DynamoDB/EBS/etc. backup + restore live under service-role/.
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores",
    # The S3 backup/restore managed policies are published WITHOUT the
    # service-role/ path segment (verified via iam list-policies). Using the
    # service-role/ path for these returns NoSuchEntity and S3 backup silently
    # lacks permission.
    "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Backup",
    "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Restore",
]

TRUST = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "backup.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
}

PLAN_RULES = {
    "BackupPlanName": PLAN_NAME,
    "Rules": [
        {
            "RuleName": "daily-35d",
            "TargetBackupVaultName": VAULT,
            "ScheduleExpression": "cron(0 5 * * ? *)",
            "StartWindowMinutes": 60,
            "CompletionWindowMinutes": 180,
            "Lifecycle": {"DeleteAfterDays": 35},
        },
        {
            "RuleName": "monthly-365d",
            "TargetBackupVaultName": VAULT,
            "ScheduleExpression": "cron(0 5 1 * ? *)",
            "StartWindowMinutes": 60,
            "CompletionWindowMinutes": 360,
            "Lifecycle": {"MoveToColdStorageAfterDays": 90, "DeleteAfterDays": 365},
        },
    ],
}


def iam():
    return boto3.client("iam", region_name=REGION)


def backup():
    return boto3.client("backup", region_name=REGION)


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def s3():
    return boto3.client("s3", region_name=REGION)


# ── discovery ────────────────────────────────────────────────────────────────
def project_tables(client) -> list[str]:
    names: list[str] = []
    for page in client.get_paginator("list_tables").paginate():
        names.extend(page.get("TableNames", []))
    return sorted(n for n in names if n.startswith(DDB_PREFIX) or n in EXTRA_DDB)


# ── ensure helpers (idempotent) ──────────────────────────────────────────────
def ensure_role(apply: bool) -> bool:
    c = iam()
    try:
        c.get_role(RoleName=ROLE)
        exists = True
    except ClientError:
        exists = False
    if not exists:
        print(f"  role {ROLE}: MISSING")
        if apply:
            c.create_role(RoleName=ROLE,
                          AssumeRolePolicyDocument=json.dumps(TRUST),
                          Description="AWS Backup service role for wecare-digital")
            print(f"    created {ROLE}")
    else:
        print(f"  role {ROLE}: present")
    if apply:
        for pol in MANAGED_POLICIES:
            try:
                c.attach_role_policy(RoleName=ROLE, PolicyArn=pol)
            except ClientError as exc:
                print(f"    attach {pol.split('/')[-1]}: "
                      f"{exc.response['Error']['Code']}")
        print(f"    ensured {len(MANAGED_POLICIES)} managed policies")
    return exists


def ensure_vault(apply: bool) -> bool:
    c = backup()
    try:
        c.describe_backup_vault(BackupVaultName=VAULT)
        print(f"  vault {VAULT}: present")
        return True
    except ClientError:
        print(f"  vault {VAULT}: MISSING")
        if apply:
            c.create_backup_vault(BackupVaultName=VAULT)
            print(f"    created {VAULT}")
        return False


def tag_resources(apply: bool) -> int:
    """Apply backup=daily to every project table + the media bucket."""
    d, s = ddb(), s3()
    tables = project_tables(d)
    n = 0
    for name in tables:
        arn = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{name}"
        if apply:
            try:
                d.tag_resource(ResourceArn=arn,
                               Tags=[{"Key": BACKUP_TAG_KEY, "Value": BACKUP_TAG_VALUE}])
                n += 1
            except ClientError as exc:
                print(f"    tag {name}: {exc.response['Error']['Code']}")
    if apply:
        try:
            existing = s.get_bucket_tagging(Bucket=MEDIA_BUCKET).get("TagSet", [])
        except ClientError:
            existing = []
        tagset = [t for t in existing if t["Key"] != BACKUP_TAG_KEY]
        tagset.append({"Key": BACKUP_TAG_KEY, "Value": BACKUP_TAG_VALUE})
        s.put_bucket_tagging(Bucket=MEDIA_BUCKET, Tagging={"TagSet": tagset})
        n += 1
    print(f"  tagged {len(tables)} table(s) + media bucket with "
          f"{BACKUP_TAG_KEY}={BACKUP_TAG_VALUE}"
          + ("" if apply else " (plan: not applied)"))
    return n


def plan_id(c) -> str | None:
    for page in c.get_paginator("list_backup_plans").paginate():
        for p in page.get("BackupPlansList", []):
            if p["BackupPlanName"] == PLAN_NAME:
                return p["BackupPlanId"]
    return None


def ensure_plan(apply: bool) -> str | None:
    c = backup()
    pid = plan_id(c)
    if pid:
        print(f"  plan {PLAN_NAME}: present ({pid})")
    else:
        print(f"  plan {PLAN_NAME}: MISSING")
        if apply:
            resp = c.create_backup_plan(BackupPlan=PLAN_RULES)
            pid = resp["BackupPlanId"]
            print(f"    created plan {pid}")
    return pid


def ensure_selection(apply: bool, pid: str) -> None:
    c = backup()
    try:
        for page in c.get_paginator("list_backup_selections").paginate(BackupPlanId=pid):
            for sel in page.get("BackupSelectionsList", []):
                if sel["SelectionName"] == SELECTION:
                    print(f"  selection {SELECTION}: present")
                    return
    except ClientError:
        pass
    print(f"  selection {SELECTION}: MISSING")
    if apply:
        c.create_backup_selection(
            BackupPlanId=pid,
            BackupSelection={
                "SelectionName": SELECTION,
                "IamRoleArn": ROLE_ARN,
                "ListOfTags": [{
                    "ConditionType": "STRINGEQUALS",
                    "ConditionKey": BACKUP_TAG_KEY,
                    "ConditionValue": BACKUP_TAG_VALUE,
                }],
            },
        )
        print(f"    created tag-based selection ({BACKUP_TAG_KEY}={BACKUP_TAG_VALUE})")


def ensure_notifications(apply: bool) -> None:
    c = backup()
    if apply:
        try:
            c.put_backup_vault_notifications(
                BackupVaultName=VAULT,
                SNSTopicArn=SNS_ARN,
                BackupVaultEvents=[
                    "BACKUP_JOB_FAILED", "RESTORE_JOB_FAILED", "COPY_JOB_FAILED",
                ],
            )
            print(f"  notifications -> {SNS_ARN.split(':')[-1]} on *_FAILED")
        except ClientError as exc:
            print(f"  notifications: {exc.response['Error']['Code']} "
                  "(SNS topic policy may need backup.amazonaws.com publish rights)")
    else:
        print(f"  would set vault notifications -> {SNS_ARN.split(':')[-1]}")


def ensure_vault_lock_governance(apply: bool) -> None:
    """Apply GOVERNANCE-mode Vault Lock (reversible).

    Governance mode blocks deletion of recovery points and shortening of
    retention for everyone EXCEPT a principal holding the explicit
    backup:*GovernanceLock*/DeleteBackupVaultLockConfiguration permissions — so it
    stops accidents and most malicious deletes while remaining removable by an
    administrator. Compliance mode would make it irreversible for everyone
    including the root account, which is a separate, deliberate owner decision and
    is intentionally NOT offered by this flag.

    MinRetentionDays=35 matches the daily rule; MaxRetentionDays=366 leaves the
    monthly 365-day rule room. ChangeableForDays is omitted (governance locks take
    effect immediately and stay removable; the cooling-off period is a
    compliance-mode concept).
    """
    c = backup()
    cur = c.describe_backup_vault(BackupVaultName=VAULT)
    if cur.get("Locked"):
        print(f"  vault lock: already locked "
              f"(min={cur.get('MinRetentionDays')} max={cur.get('MaxRetentionDays')})")
        return
    print("  vault lock: NOT locked")
    if apply:
        c.put_backup_vault_lock_configuration(
            BackupVaultName=VAULT,
            MinRetentionDays=35,
            MaxRetentionDays=366,
        )
        after = c.describe_backup_vault(BackupVaultName=VAULT)
        print(f"    GOVERNANCE lock applied (locked={after.get('Locked')}, "
              f"min={after.get('MinRetentionDays')}, max={after.get('MaxRetentionDays')}) "
              "— reversible by an administrator")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--lock-governance", action="store_true",
                    help="also apply reversible GOVERNANCE-mode Vault Lock "
                         "(use with --apply)")
    args = ap.parse_args()
    apply = args.apply

    if args.verify:
        c = backup()
        pid = plan_id(c)
        print(f"plan present      : {bool(pid)}")
        if not pid:
            return 2
        try:
            c.describe_backup_vault(BackupVaultName=VAULT)
            print(f"vault present     : True ({VAULT})")
        except ClientError:
            print("vault present     : False")
            return 2
        sels = []
        for page in c.get_paginator("list_backup_selections").paginate(BackupPlanId=pid):
            sels += [s["SelectionName"] for s in page.get("BackupSelectionsList", [])]
        print(f"selections        : {sels}")
        d = ddb()
        tagged = 0
        for name in project_tables(d):
            arn = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{name}"
            tags = d.list_tags_of_resource(ResourceArn=arn).get("Tags", [])
            if any(t["Key"] == BACKUP_TAG_KEY and t["Value"] == BACKUP_TAG_VALUE
                   for t in tags):
                tagged += 1
        print(f"tables tagged     : {tagged}/{len(project_tables(d))}")
        v = c.describe_backup_vault(BackupVaultName=VAULT)
        print(f"vault locked      : {v.get('Locked')} "
              f"(min={v.get('MinRetentionDays')}, max={v.get('MaxRetentionDays')})")
        return 0

    print(f"=== AWS Backup provisioning ({'APPLY' if apply else 'PLAN'}) ===")
    ensure_role(apply)
    if apply:
        time.sleep(8)  # let the new role/policy attachments propagate
    ensure_vault(apply)
    tag_resources(apply)
    pid = ensure_plan(apply)
    if pid:
        ensure_selection(apply, pid)
    ensure_notifications(apply)
    if args.lock_governance:
        print("\n--- Vault Lock (governance) ---")
        ensure_vault_lock_governance(apply)
    else:
        print("\nVault Lock not requested. Add --lock-governance for the reversible "
              "lock; compliance (irreversible) mode is a separate owner decision.")
    print("done." if apply else "plan only — nothing changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
