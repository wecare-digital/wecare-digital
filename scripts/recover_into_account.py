#!/usr/bin/env python3
"""Stand the ENTIRE platform up in a recovery account, from git + snapshot.

Why this exists
---------------
"Backups" protect data. This protects the whole SYSTEM: it rebuilds the compute
and wiring (tables, IAM, Lambdas, the HTTP API and its routes, queues, schedules)
in a fresh account so the platform can run again — not just be restored to disk.
It reads the committed `docs/execution/infra-snapshot/*.json` (from
`export_infrastructure_snapshot.py`) and the in-repo `provision_*.py` fleet, and
drives them against a TARGET account in dependency order.

Designed for the dedicated recovery account `991322955408`, but takes any account
via --target-account so it can also validate against a throwaway account.

RTO expectation, stated honestly
--------------------------------
This is warm-standby orchestration, not active-active. Realistic time to a serving
platform:
  * tables + IAM + Lambda code .......... ~10-20 min (code is in git, deploys fast)
  * DynamoDB DATA restore from the cross-account backup copies ... longer, size-dependent
  * DNS + provider webhook repoint (WhatsApp/Razorpay/Plivo) .... manual, ~minutes
So end-to-end is tens of minutes, not single-digit — but it is a REAL rebuild, and
every step is scripted rather than a runbook someone follows by hand.

What it does NOT do
-------------------
It does not move data by itself (that is the AWS Backup cross-account restore +
S3 replica, which already exist) and it does not repoint DNS/providers (deliberate
human gate — you do not want an automated failover flipping live phone/payment
routing). It PRINTS those as the final manual steps.

    python scripts/recover_into_account.py --plan   --target-account 991322955408
    python scripts/recover_into_account.py --apply  --target-account 991322955408
    python scripts/recover_into_account.py --verify --target-account 991322955408

SAFETY: --apply refuses to run against the production account 775261844268 (you do
not "recover" onto the live account), and refuses unless the caller's credentials
are actually for the target account.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import boto3

REGION = "us-east-1"
PROD_ACCOUNT = "775261844268"
REPO = pathlib.Path(__file__).resolve().parents[1]
SNAP = REPO / "docs/execution/infra-snapshot/snapshot.json"
PY = sys.executable

# Provisioning order: tables first (Lambdas reference them by env name), then the
# roles/functions/routes each domain owns. These are the repo's own idempotent
# provisioners; the orchestrator runs them, it does not reimplement them.
ORDER = [
    # 1. Tables
    "provision_products_table.py",
    "provision_payment_attempts_table.py",
    "provision_agent_approvals_table.py",
    "provision_thread_ownership_table.py",
    "provision_notification_domain.py",
    # 2. Core domains / APIs / functions
    "provision_crm_api.py",
    "provision_crm_domain.py",
    "provision_checkout.py",
    "provision_customer_registration.py",
    "provision_customer_profile.py",
    "provision_email_verification.py",
    "provision_secure_file_sharing.py",
    "provision_service_requests.py",
    "provision_native_catalog_api.py",
    # 3. Infra extras
    "provision_log_retention.py",
    "provision_lambda_alarms.py",
]


def caller_account() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def apply_flag_for(script: str) -> str:
    """Return the flag that makes this provisioner APPLY.

    The fleet is inconsistent: some scripts have an explicit `--apply`, others
    default to a real run and use `--dry-run` to NOT mutate (so applying means
    passing NO flag). Passing `--apply` to the second kind makes argparse error out
    and the step silently does nothing — the exact failure the first backup-account
    run hit. Detect per script by reading its source.
    """
    src = (REPO / "scripts" / script).read_text(errors="replace")
    if '"--apply"' in src or "'--apply'" in src:
        return "--apply"
    # No --apply flag: a bare run applies (dry-run is the opt-out). Pass nothing.
    return ""


def load_snapshot() -> dict:
    if not SNAP.exists():
        sys.exit(f"missing {SNAP} — run export_infrastructure_snapshot.py first")
    return json.loads(SNAP.read_text())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--target-account", required=True,
                    help="the recovery account to build into (e.g. 991322955408)")
    args = ap.parse_args()

    snap = load_snapshot()
    target = args.target_account
    present = [s for s in ORDER if (REPO / "scripts" / s).exists()]
    missing = [s for s in ORDER if not (REPO / "scripts" / s).exists()]

    print(f"recovery target account : {target}")
    print(f"snapshot generated      : {snap.get('_generated')}")
    print(f"to rebuild              : {len(snap.get('lambdas', {}))} functions, "
          f"{len(snap.get('tables', {}))} tables, "
          f"{len(snap.get('apis', {}))} API(s), "
          f"{len(snap.get('queues', {}))} queues")
    print(f"provisioners available  : {len(present)}/{len(ORDER)}")
    if missing:
        print(f"  (not found, skipped): {', '.join(missing)}")

    if args.plan:
        print("\nwould run, in order:")
        for s in present:
            print(f"   python scripts/{s} --apply")
        print("   python scripts/deploy_all_lambdas.py        # push all function code")
        print("\nthen (manual, printed by --apply):")
        print("   - restore DynamoDB data via AWS Backup cross-account restore")
        print("   - restore S3 media from the cross-account replica bucket")
        print("   - repoint DNS + provider webhooks (WhatsApp/Razorpay/Plivo)")
        return 0

    # Guardrails for apply/verify that actually touch an account.
    if args.apply:
        if target == PROD_ACCOUNT:
            sys.exit("REFUSING: --apply target is the PRODUCTION account. Recovery "
                     "rebuilds into a SEPARATE account, never onto prod.")
        who = caller_account()
        if who != target:
            sys.exit(f"REFUSING: credentials are for {who}, not the target {target}. "
                     f"Run with the recovery account's credentials.")
        print(f"\n=== rebuilding stack in {target} ===")
        print("WARNING: the provision_*.py fleet is written for PRODUCTION and many "
              "scripts hardcode prod's account id, the HTTP API id (zllr9lrg7j), the "
              "SNS alarm topic, and KMS principals. A plain replay therefore produces "
              "a PARTIAL stack in a fresh account. This orchestrator invokes each "
              "script with its correct apply flag, but full account-portability needs "
              "those scripts parameterized (tracked in the DR plan). Treat the result "
              "as a best-effort scaffold, not a turnkey clone.\n")
        failed = []
        for s in present:
            flag = apply_flag_for(s)
            print(f"\n--- scripts/{s} {flag} ---")
            argv = [PY, f"scripts/{s}"] + ([flag] if flag else [])
            rc = subprocess.run(argv, cwd=REPO).returncode
            if rc != 0:
                failed.append(s)
        print("\n--- deploy_all_lambdas.py ---")
        rc = subprocess.run([PY, "scripts/deploy_all_lambdas.py"], cwd=REPO).returncode
        if rc != 0:
            failed.append("deploy_all_lambdas.py")
        print("\n=== compute/wiring rebuild complete ===")
        if failed:
            print(f"  steps that FAILED (re-run them): {', '.join(failed)}")
        print("\nNEXT (manual data + cutover steps):")
        print("  1. aws backup start-restore-job  (per table, from the cross-account")
        print("     recovery points in this account's wecare-backup-vault)")
        print("  2. restore S3 media from wecare-digital-get-replica-* ")
        print("  3. repoint DNS + WhatsApp/Razorpay/Plivo webhooks to this account")
        return 1 if failed else 0

    # --verify: how much of the stack already exists in the target.
    who = caller_account()
    print(f"\ncaller account          : {who}")
    if who != target:
        print("  (verify is only meaningful run with the target account's creds)")
        return 2
    lam = boto3.client("lambda", region_name=REGION)
    live = lam.get_paginator("list_functions")
    live_names = {f["FunctionName"] for p in live.paginate() for f in p["Functions"]}
    want = set(snap.get("lambdas", {}))
    print(f"functions present       : {len(live_names & want)}/{len(want)}")
    missing_fns = sorted(want - live_names)
    if missing_fns:
        print(f"  missing: {len(missing_fns)} (e.g. {', '.join(missing_fns[:5])} ...)")
    return 0 if not missing_fns else 2


if __name__ == "__main__":
    raise SystemExit(main())
