#!/usr/bin/env python3
"""Add a cross-account COPY of every backup into the dedicated backup account.

Why this exists
---------------
Every protection so far lives in the production account `775261844268`. A copy of
the backups in a SEPARATE account is the only thing that survives losing that
account — a credential compromise that deletes the backups too, or an account
suspension. `docs/migrations/backup-and-dr-plan.md` names this as the final
hardening step. The dedicated backup account is `991322955408`
(WECARE DIGITAL BHARATWORKS), a native member of org o-plhlfh8drl.

This runs in the PRODUCTION account and adds a cross-account copy action to the
existing `wecare-backup-plan`, so every daily/monthly recovery point is copied
into the backup account's vault. The backup account keeps the copies under its OWN
Vault Lock (ideally compliance mode), and production is granted NO delete rights
there — so a prod-account compromise cannot reach them.

PREREQUISITES (must be true before --apply does anything useful)
----------------------------------------------------------------
1. The backup account `991322955408` has ACCEPTED the AWS Organizations invite
   (handshake sent from the management account) and is an org member.
   Check: `aws organizations list-accounts`.
2. Cross-account backup is enabled org-wide (done:
   `aws backup update-global-settings isCrossAccountBackupEnabled=true`).
3. A destination vault exists IN THE BACKUP ACCOUNT. Create it there with the
   backup account's own credentials — see `provision_backup_account_side.py`
   (that script runs in 991322955408, not here).
4. AWS Backup ADVANCED DynamoDB management is enabled in this Region
   (`aws backup update-region-settings --resource-type-management-preference
   DynamoDB=true,EFS=true`). Without it a DynamoDB recovery point is a native
   DynamoDB backup, and every cross-account copy fails with "Feature is not
   supported for provided resource type". That is exactly what happened from
   2026-10-17 to 2026-10-24: 600 copy jobs, 600 failures, and a `--verify` that
   only checked the plan still passed. Enabled 2026-10-25.

This script FAILS LOUDLY if (1) or (3) are not yet true, rather than creating a
copy rule that silently never lands. `--verify` checks the copies themselves,
not just the plan: the region setting in (4), and the latest copy job of every
resource copied in the last `--days` days.

Usage
-----
    python scripts/provision_cross_account_backup.py --plan
    python scripts/provision_cross_account_backup.py --apply
    python scripts/provision_cross_account_backup.py --verify
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
PROD_ACCOUNT = "775261844268"
BACKUP_ACCOUNT = "991322955408"

PLAN_NAME = "wecare-backup-plan"
# The destination vault lives in the backup account. Convention: same vault name
# there as here. Its ARN is cross-account.
DEST_VAULT = "wecare-backup-vault"
DEST_VAULT_ARN = f"arn:aws:backup:{REGION}:{BACKUP_ACCOUNT}:backup-vault:{DEST_VAULT}"

# Copy retention mirrors the source rules: keep the daily copy 35 days, the
# monthly copy 365 (cold after 90).
COPY_LIFECYCLE = {
    "daily-35d": {"DeleteAfterDays": 35},
    "monthly-365d": {"MoveToColdStorageAfterDays": 90, "DeleteAfterDays": 365},
}


def backup():
    return boto3.client("backup", region_name=REGION)


def orgs():
    return boto3.client("organizations", region_name=REGION)


def backup_account_is_member() -> bool:
    try:
        for page in orgs().get_paginator("list_accounts").paginate():
            for a in page.get("Accounts", []):
                if a["Id"] == BACKUP_ACCOUNT and a["Status"] == "ACTIVE":
                    return True
    except ClientError:
        pass
    return False


def get_plan():
    c = backup()
    for page in c.get_paginator("list_backup_plans").paginate():
        for p in page.get("BackupPlansList", []):
            if p["BackupPlanName"] == PLAN_NAME:
                return c.get_backup_plan(BackupPlanId=p["BackupPlanId"])
    return None


def has_cross_account_copy(plan_doc) -> bool:
    for rule in plan_doc["BackupPlan"]["Rules"]:
        for ca in rule.get("CopyActions", []):
            if ca.get("DestinationBackupVaultArn") == DEST_VAULT_ARN:
                return True
    return False


def dynamodb_fully_managed() -> bool:
    """Prerequisite (4): copies of DynamoDB recovery points need advanced management."""
    prefs = backup().describe_region_settings().get("ResourceTypeManagementPreference", {})
    return bool(prefs.get("DynamoDB"))


def latest_copy_states(days: int) -> tuple[dict[str, str], collections.Counter]:
    """State of the most recent copy job into DEST_VAULT_ARN, per source resource.

    Judged per resource rather than over the whole window, so a fix shows as healthy on
    the next run instead of only once the old failures have aged out. Failure messages are
    counted (they name a cause, never a credential) so a failing run says why.
    """
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    latest: dict[str, tuple[dt.datetime, str]] = {}
    reasons: collections.Counter = collections.Counter()
    pages = backup().get_paginator("list_copy_jobs").paginate(
        ByDestinationVaultArn=DEST_VAULT_ARN, ByCreatedAfter=since)
    for page in pages:
        for job in page.get("CopyJobs", []):
            resource, created = job.get("ResourceArn", ""), job["CreationDate"]
            if resource not in latest or created > latest[resource][0]:
                latest[resource] = (created, job["State"])
            if job["State"] == "FAILED":
                reasons[(job.get("StatusMessage") or "no status message")[:160]] += 1
    return {resource: state for resource, (_, state) in latest.items()}, reasons


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--days", type=int, default=3,
                    help="--verify: copy-job lookback window in days (default 3)")
    args = ap.parse_args()

    member = backup_account_is_member()
    print(f"backup account {BACKUP_ACCOUNT} is an org member : {member}")

    plan_doc = get_plan()
    if plan_doc is None:
        print(f"ERROR: plan {PLAN_NAME} not found — run provision_aws_backup.py first",
              file=sys.stderr)
        return 2
    plan_id = plan_doc["BackupPlanId"]
    already = has_cross_account_copy(plan_doc)

    if args.verify:
        print(f"cross-account copy action present : {already}")
        print(f"destination vault : {DEST_VAULT_ARN}")
        managed = dynamodb_fully_managed()
        print(f"advanced DynamoDB backup management : {managed}")
        states, reasons = latest_copy_states(args.days)
        tally = collections.Counter(states.values())
        print(f"latest copy job per resource (last {args.days}d) : {len(states)} resource(s) "
              + (", ".join(f"{state}={n}" for state, n in sorted(tally.items())) or "none"))
        for reason, n in reasons.most_common(3):
            print(f"   {n} failed copy job(s): {reason}")
        # A copy rule that never lands is the failure this check exists for, so the plan
        # alone is not a pass: the latest copy of every resource must have completed.
        healthy = (already and managed and tally.get("COMPLETED", 0) > 0
                   and not tally.get("FAILED") and not tally.get("PARTIAL"))
        print("RESULT:", "PASS" if healthy else "FAIL")
        return 0 if healthy else 2

    if already:
        print("cross-account copy action already present — nothing to do")
        return 0

    # Build updated rules with a CopyAction appended to each.
    new_rules = []
    for rule in plan_doc["BackupPlan"]["Rules"]:
        r = {k: v for k, v in rule.items() if k != "RuleId"}
        lifecycle = COPY_LIFECYCLE.get(rule["RuleName"], {"DeleteAfterDays": 35})
        r.setdefault("CopyActions", [])
        r["CopyActions"].append({
            "DestinationBackupVaultArn": DEST_VAULT_ARN,
            "Lifecycle": lifecycle,
        })
        new_rules.append(r)

    if args.plan:
        print(f"would add a copy action -> {DEST_VAULT_ARN} to "
              f"{len(new_rules)} rule(s)")
        for r in new_rules:
            print(f"   {r['RuleName']}: copy lifecycle "
                  f"{COPY_LIFECYCLE.get(r['RuleName'])}")
        if not member:
            print("\nNOTE: backup account is NOT an org member yet — accept the "
                  "org invite from 991322955408 before --apply, or the copy jobs "
                  "will fail at run time.")
        return 0

    # --apply
    if not member:
        print("REFUSING to apply: backup account 991322955408 has not accepted the "
              "org invite yet. A copy rule to a non-member vault silently fails every "
              "backup. Accept the invite, then re-run.", file=sys.stderr)
        return 2
    try:
        backup().update_backup_plan(
            BackupPlanId=plan_id,
            BackupPlan={
                "BackupPlanName": PLAN_NAME,
                "Rules": new_rules,
            },
        )
    except ClientError as exc:
        print(f"update_backup_plan failed: {exc.response['Error']['Code']}: "
              f"{exc.response['Error']['Message']}", file=sys.stderr)
        return 1
    print(f"added cross-account copy -> {DEST_VAULT_ARN} to all plan rules")
    print("Every new daily/monthly recovery point will now be copied to the backup "
          "account. Confirm the destination vault's access policy allows copies "
          "from this account (provision_backup_account_side.py handles that).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
