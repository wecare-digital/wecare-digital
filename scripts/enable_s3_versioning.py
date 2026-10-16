#!/usr/bin/env python3
"""Enable versioning on the media bucket so an overwrite or delete is recoverable.

Why this exists
---------------
`wecare-digital-get` holds invoices, WhatsApp media, voice recordings, product
images and Meta-approved template media. Measured 2026-10-16, bucket versioning
was **Suspended** — so a `PutObject` over an existing key, or a `DeleteObject`,
was unrecoverable. Yet a lifecycle rule `expire-noncurrent-versions` (90-day
noncurrent expiry) already existed, which only makes sense with versioning ON:
the cost-control half was in place while the protection half was off. This
reconciles the two. `docs/migrations/backup-and-dr-plan.md` §4.3 calls for it.

Enabling versioning is non-destructive and reversible: existing objects become
the current version; nothing is rewritten; it can be suspended again at any time.
The pre-existing 90-day noncurrent-version expiry bounds the storage cost, so
versioning does not accumulate old renditions forever.

What it deliberately does NOT touch
-----------------------------------
The bucket's two roots and the Meta-approved `o/public/wa-tpl/` objects are left
exactly as they are — versioning is a bucket-level property and changes no object
content, key, or ACL. The `secure/*` gating and the CloudFront/edge behaviour are
unaffected.

Usage
-----
    python scripts/enable_s3_versioning.py --plan      # show current state
    python scripts/enable_s3_versioning.py --apply     # set versioning Enabled
    python scripts/enable_s3_versioning.py --verify     # confirm Enabled

Exit codes: 0 success (or --verify Enabled), 1 operation failed, 2 --verify found
versioning not Enabled.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
BUCKET = "wecare-digital-get"


def s3():
    return boto3.client("s3", region_name=REGION)


def versioning_status(client) -> str:
    """'Enabled' / 'Suspended' / 'NotSet'."""
    resp = client.get_bucket_versioning(Bucket=BUCKET)
    return resp.get("Status", "NotSet")


def has_noncurrent_expiry(client) -> bool:
    """True if a lifecycle rule bounds noncurrent-version storage cost."""
    try:
        cfg = client.get_bucket_lifecycle_configuration(Bucket=BUCKET)
    except ClientError:
        return False
    return any(
        "NoncurrentVersionExpiration" in rule and rule.get("Status") == "Enabled"
        for rule in cfg.get("Rules", [])
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    client = s3()
    try:
        status = versioning_status(client)
    except ClientError as exc:
        print(f"get-bucket-versioning failed: {exc.response['Error']['Code']}",
              file=sys.stderr)
        return 1

    bounded = has_noncurrent_expiry(client)
    print(f"bucket={BUCKET}  versioning={status}  "
          f"noncurrent-expiry-rule={'yes' if bounded else 'NO'}")

    if args.verify:
        if status == "Enabled":
            print("OK — versioning is Enabled")
            return 0
        print("NOT ENABLED", file=sys.stderr)
        return 2

    if args.plan:
        if status == "Enabled":
            print("no change needed — already Enabled")
        else:
            print(f"would set versioning Enabled (currently {status})")
            if not bounded:
                print("  WARNING: no noncurrent-version expiry lifecycle rule; "
                      "versions would accumulate. Add one before/after enabling.")
        return 0

    # --apply
    if status == "Enabled":
        print("already Enabled — nothing to do")
        return 0
    try:
        client.put_bucket_versioning(
            Bucket=BUCKET,
            VersioningConfiguration={"Status": "Enabled"},
        )
    except ClientError as exc:
        print(f"put-bucket-versioning failed: {exc.response['Error']['Code']}",
              file=sys.stderr)
        return 1

    after = versioning_status(client)
    print(f"versioning now: {after}")
    if after != "Enabled":
        print("set did not take effect", file=sys.stderr)
        return 1
    if not bounded:
        print("REMINDER: add a NoncurrentVersionExpiration lifecycle rule to bound "
              "storage cost.")
    print("OK — overwrites and deletes are now recoverable from a prior version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
