#!/usr/bin/env python3
"""Prove the S3 and secrets backups actually restore — not just exist.

Why this exists
---------------
A backup is a hypothesis until a restore succeeds. The DynamoDB PITR drill was run
and recorded (`docs/execution/restore-drill-20261016.md`); this automates the other
two the DR plan calls for on a quarterly cadence:

  s3      : write a throwaway object to the media bucket, overwrite it, then recover
            the ORIGINAL from its prior version — proving versioning truly protects
            against an overwrite. Cleans up after itself.
  secrets : confirm the encrypted credential backup decrypts and its field NAMES are
            intact (via verify_backup_artifact.py), and that the S3 copy is present.
            No secret VALUE is read or printed.

Non-destructive to real data: the S3 test uses a dedicated throwaway key under
`drill/`, never a real object.

    python scripts/restore_drill.py --s3        # S3 version-recovery drill
    python scripts/restore_drill.py --secrets    # secrets restore check
    python scripts/restore_drill.py --all         # both (default)

Exit codes: 0 all drills passed, 1 a drill failed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
BUCKET = "wecare-digital-get"
DRILL_KEY = "drill/restore-drill-probe.txt"
REPO_PY = sys.executable


def s3_drill() -> bool:
    s3 = boto3.client("s3", region_name=REGION)
    original = f"original-{datetime.now(timezone.utc).isoformat()}".encode()
    overwrite = b"OVERWRITTEN-this-should-be-recoverable-from-the-prior-version"
    print("S3 version-recovery drill")
    try:
        # 1. write original -> capture its versionId
        r1 = s3.put_object(Bucket=BUCKET, Key=DRILL_KEY, Body=original)
        v1 = r1.get("VersionId")
        print(f"  wrote original      version={v1}")
        # 2. overwrite it
        s3.put_object(Bucket=BUCKET, Key=DRILL_KEY, Body=overwrite)
        cur = s3.get_object(Bucket=BUCKET, Key=DRILL_KEY)["Body"].read()
        print(f"  current is overwrite: {cur == overwrite}")
        # 3. recover the ORIGINAL from its prior version
        if not v1 or v1 == "null":
            print("  FAIL: no versionId — versioning not actually on")
            return False
        recovered = s3.get_object(Bucket=BUCKET, Key=DRILL_KEY,
                                  VersionId=v1)["Body"].read()
        ok = recovered == original
        print(f"  recovered original from prior version: {ok}")
        return ok
    except ClientError as exc:
        print(f"  FAIL: {exc.response['Error']['Code']}", file=sys.stderr)
        return False
    finally:
        # cleanup: delete all versions of the drill key
        try:
            versions = s3.list_object_versions(Bucket=BUCKET, Prefix=DRILL_KEY)
            for v in versions.get("Versions", []) + versions.get("DeleteMarkers", []):
                s3.delete_object(Bucket=BUCKET, Key=v["Key"], VersionId=v["VersionId"])
            print("  cleaned up drill object (all versions)")
        except ClientError:
            pass


def secrets_drill() -> bool:
    print("Secrets restore check")
    rc = subprocess.run([REPO_PY, "scripts/verify_backup_artifact.py"]).returncode
    ok = rc == 0
    print(f"  verify_backup_artifact.py -> {'OK' if ok else 'FAILED'}")
    return ok


def record(results: dict) -> None:
    """Append a dated line to the drill log so the cadence is auditable."""
    import pathlib
    log = pathlib.Path(__file__).resolve().parents[1] / \
        "docs/execution/restore-drill-log.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = (f"- {stamp}  " +
            "  ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in results.items()))
    header = "# Restore drill log\n\nAutomated S3/secrets drills (DynamoDB drill: see restore-drill-20261016.md).\n\n"
    if not log.exists():
        log.write_text(header)
    with log.open("a") as fh:
        fh.write(line + "\n")
    print(f"  recorded: {line}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--s3", action="store_true")
    ap.add_argument("--secrets", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    do_s3 = args.s3 or args.all or not (args.s3 or args.secrets)
    do_secrets = args.secrets or args.all or not (args.s3 or args.secrets)

    results: dict[str, bool] = {}
    if do_s3:
        results["s3"] = s3_drill()
    if do_secrets:
        results["secrets"] = secrets_drill()
    record(results)

    failed = [k for k, v in results.items() if not v]
    print("\n" + ("all drills PASSED" if not failed else f"FAILED: {failed}"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
