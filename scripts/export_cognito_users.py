#!/usr/bin/env python3
"""Export Cognito user attributes to the encrypted backup bucket.

Why this exists
---------------
Cognito users cannot be recreated from code, and there is no native "export
users" button. Deletion protection guards the pool from deletion, but it does not
give you the users back if attributes are lost or the pool is recreated elsewhere
(e.g. a migration to another provider). `docs/migrations/backup-and-dr-plan.md`
§4.5 calls for a periodic attribute export.

What it does and does NOT capture
---------------------------------
Captures, per user: username, status, enabled flag, create/modified dates, group
membership, and all standard/custom ATTRIBUTES. It does NOT and CANNOT capture
passwords — Cognito never exposes password material, by design. On restore, users
re-verify; what this protects is identity, contact attributes and group/role
membership, not the secret.

Storage
-------
Written as SSE-KMS to the existing credential-backup bucket (versioned, public
access blocked, TLS-only — created by `secrets_backup.py`). The export contains
PII (emails, phone numbers), so it is treated like a credential artifact: KMS at
rest, never printed, counts only in the run summary.

Usage
-----
    python scripts/export_cognito_users.py --plan       # count users, write nothing
    python scripts/export_cognito_users.py --apply       # export to S3
    python scripts/export_cognito_users.py --verify      # confirm the S3 object

Exit codes: 0 success, 1 failure, 2 --verify found no export object.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
POOL_ID = "us-east-1_cSx0RHCIR"
BUCKET = f"wecare-credential-backups-{ACCOUNT}"
S3_KEY = "cognito-exports/current/user-attributes.json"


def idp():
    return boto3.client("cognito-idp", region_name=REGION)


def s3():
    return boto3.client("s3", region_name=REGION)


def list_users(client) -> list[dict]:
    users: list[dict] = []
    kwargs = {"UserPoolId": POOL_ID, "Limit": 60}
    while True:
        resp = client.list_users(**kwargs)
        for u in resp.get("Users", []):
            users.append({
                "username": u["Username"],
                "status": u.get("UserStatus"),
                "enabled": u.get("Enabled"),
                "created": str(u.get("UserCreateDate")),
                "modified": str(u.get("UserLastModifiedDate")),
                "attributes": {
                    a["Name"]: a["Value"] for a in u.get("Attributes", [])
                },
            })
        token = resp.get("PaginationToken")
        if not token:
            break
        kwargs["PaginationToken"] = token
    return users


def groups_for(client, username: str) -> list[str]:
    out: list[str] = []
    kwargs = {"UserPoolId": POOL_ID, "Username": username, "Limit": 60}
    while True:
        try:
            resp = client.admin_list_groups_for_user(**kwargs)
        except ClientError:
            break
        out += [g["GroupName"] for g in resp.get("Groups", [])]
        token = resp.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if args.verify:
        try:
            head = s3().head_object(Bucket=BUCKET, Key=S3_KEY)
        except ClientError:
            print(f"no export at s3://{BUCKET}/{S3_KEY}", file=sys.stderr)
            return 2
        print(f"export present: s3://{BUCKET}/{S3_KEY}")
        print(f"  size={head['ContentLength']}  modified={head['LastModified']}  "
              f"users={head['Metadata'].get('user_count', '?')}  "
              f"SSE={head.get('ServerSideEncryption')}")
        return 0

    client = idp()
    users = list_users(client)
    for u in users:
        u["groups"] = groups_for(client, u["username"])
    print(f"pool={POOL_ID}  users={len(users)}")

    if args.plan:
        enabled = sum(1 for u in users if u.get("enabled"))
        print(f"  enabled={enabled}  would write s3://{BUCKET}/{S3_KEY} (SSE-KMS)")
        print("  (plan only — nothing written)")
        return 0

    payload = {
        "_format": "wecare-cognito-export/1",
        "_generated": datetime.now(timezone.utc).isoformat(),
        "_pool": POOL_ID,
        "_note": "User attributes + group membership. Passwords are NOT included "
                 "(Cognito never exposes them). On restore, users re-verify.",
        "users": users,
    }
    body = json.dumps(payload, indent=2, default=str).encode()
    try:
        res = s3().put_object(
            Bucket=BUCKET, Key=S3_KEY, Body=body,
            ServerSideEncryption="aws:kms",
            ChecksumAlgorithm="SHA256",
            Metadata={"user_count": str(len(users)),
                      "format": "wecare-cognito-export/1"},
        )
    except ClientError as exc:
        print(f"put_object failed: {exc.response['Error']['Code']}", file=sys.stderr)
        return 1
    print(f"  wrote s3://{BUCKET}/{S3_KEY}  {len(body)} bytes  "
          f"SSE={res.get('ServerSideEncryption')}  VersionId={res.get('VersionId')}")
    print("  no user value printed; export is SSE-KMS on a versioned, TLS-only bucket.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
