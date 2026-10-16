#!/usr/bin/env python3
"""One command that refreshes every self-managed backup and checks freshness.

Why this exists
---------------
The encrypted credential artifact drifted 20 days behind the account before
anyone noticed (measured 2026-10-16: 10 secrets had changed since the last
backup). A backup step that must be remembered does not get run. This is the
single entry point a scheduler (GitHub Actions cron, EventBridge, cron) points
at, so "scheduled refresh" means pointing one job at one command.

What it does
------------
1. Rebuilds the encrypted credential backup from Secrets Manager
   (`secrets_backup.py create`) — plaintext never hits disk.
2. Independently verifies that artifact (`verify_backup_artifact.py`).
3. Refreshes the Cognito user export (`export_cognito_users.py --apply`).
4. Mirrors secrets one-way to GCP, if gcloud is configured (best-effort).
5. Reports a freshness check: how many secrets changed since the backup, so a
   stale result is loud rather than silent.

Steps are independent: one failing does not abort the rest, and the exit code is
non-zero if ANY required step failed, so a scheduler surfaces it.

Usage
-----
    python scripts/refresh_all_backups.py             # run everything
    python scripts/refresh_all_backups.py --check      # freshness report only, no writes

Exit codes: 0 all good, 1 one or more steps failed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

REGION = "us-east-1"
ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(label: str, argv: list[str]) -> bool:
    print(f"\n=== {label} ===")
    proc = subprocess.run(argv, cwd=ROOT)
    ok = proc.returncode == 0
    print(f"  -> {'OK' if ok else f'FAILED (exit {proc.returncode})'}")
    return ok


def backup_generated_at() -> datetime | None:
    """Read the _generated date from the local artifact header (no decrypt)."""
    f = Path.home() / ".secure-backups" / "wecare-secrets-backup.txt.enc"
    if not f.exists():
        return None
    for line in f.read_text(errors="replace").splitlines():
        if line.startswith("created="):
            try:
                return datetime.fromisoformat(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


def freshness_report() -> int:
    """Count secrets changed since the backup. Returns that count."""
    gen = backup_generated_at()
    if gen is None:
        print("  no local backup artifact found")
        return -1
    sm = boto3.client("secretsmanager", region_name=REGION)
    changed = []
    for page in sm.get_paginator("list_secrets").paginate():
        for s in page.get("SecretList", []):
            lcd = s.get("LastChangedDate")
            if lcd and lcd > gen:
                changed.append(s["Name"])
    print(f"  backup generated : {gen.isoformat()}")
    print(f"  secrets changed since backup : {len(changed)}")
    for n in sorted(changed):
        print(f"     - {n}")
    return len(changed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="freshness report only; write nothing")
    args = ap.parse_args()

    print(f"backup refresh @ {datetime.now(timezone.utc).isoformat()}")

    if args.check:
        print("\n=== freshness check (no writes) ===")
        n = freshness_report()
        if n > 0:
            print(f"\nSTALE: {n} secret(s) changed since the last backup — run a refresh.")
            return 1
        print("\nbackup is current." if n == 0 else "\ncould not determine freshness.")
        return 0 if n == 0 else 1

    results: dict[str, bool] = {}
    results["secrets backup (create)"] = run(
        "credential backup refresh", [PY, "scripts/secrets_backup.py", "create"])
    results["secrets backup (verify)"] = run(
        "credential backup verify", [PY, "scripts/verify_backup_artifact.py"])
    results["cognito export"] = run(
        "cognito user export", [PY, "scripts/export_cognito_users.py", "--apply"])

    # GCP mirror is best-effort: it needs gcloud, which may be absent in CI.
    gcp = subprocess.run(["bash", "scripts/google-cloud-setup.sh", "mirror-secrets"],
                         cwd=ROOT)
    results["gcp mirror (best-effort)"] = gcp.returncode == 0
    if not results["gcp mirror (best-effort)"]:
        print("  (GCP mirror skipped/failed — not required; gcloud may be absent)")

    print("\n=== freshness after refresh ===")
    freshness_report()

    print("\n=== summary ===")
    required_ok = True
    for label, ok in results.items():
        best_effort = "best-effort" in label
        mark = "OK  " if ok else ("warn" if best_effort else "FAIL")
        print(f"  {mark}  {label}")
        if not ok and not best_effort:
            required_ok = False
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
