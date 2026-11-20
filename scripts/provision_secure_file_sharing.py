#!/usr/bin/env python3
"""Provision the DynamoDB tables behind wecare.digital/get/secure.

Two tables, and the split matters.

``SecureFilesTable`` - the catalogue
-----------------------------------
Every uploaded object is stored under an unguessable key:

    secure/wecare-digital-<uuid4>-<uuid4><ext>

That is deliberate: the key carries no customer name, no original filename and no
sequence, so it cannot be guessed and one customer's key tells you nothing about
another's. But it also means the key is meaningless to a human, which is exactly
why this table exists. It is the only place that knows a given opaque key belongs
to a particular person and was originally called something readable.

This is what answers "with many files uploaded, how do we know which file belongs
to which user": the ``owner-created-index`` GSI, partitioned on ``ownerPhone``, so
listing one customer's files is a single query rather than a scan.

``DownloadGrantsTable`` - one paid download
-------------------------------------------
Nothing is permanent here. A grant is written only after Razorpay's webhook
signature verifies, is redeemed by a conditional write so a forwarded link is dead
on second use, and carries a TTL so unredeemed grants evaporate. The
``order-index`` GSI exists because the webhook knows only the Razorpay order id and
has to find the pending grant from it.

Usage
-----
    python scripts/provision_secure_file_sharing.py --dry-run
    python scripts/provision_secure_file_sharing.py
    python scripts/provision_secure_file_sharing.py --verify

Idempotent: existing tables are left alone and reported, never recreated.
Exit codes: 0 success, 1 a check failed.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
FILES_TABLE = "stack-wecare-digital-SecureFilesTable"
GRANTS_TABLE = "stack-wecare-digital-DownloadGrantsTable"

TAGS = [
    {"Key": "Project", "Value": "wecare-digital"},
    {"Key": "Feature", "Value": "secure-file-sharing"},
]

FILES_SCHEMA = {
    "TableName": FILES_TABLE,
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "fileId", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "fileId", "AttributeType": "S"},
        {"AttributeName": "ownerPhone", "AttributeType": "S"},
        {"AttributeName": "createdAt", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            # "which files belong to this customer", newest first
            "IndexName": "owner-created-index",
            "KeySchema": [
                {"AttributeName": "ownerPhone", "KeyType": "HASH"},
                {"AttributeName": "createdAt", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
    "Tags": TAGS,
}

GRANTS_SCHEMA = {
    "TableName": GRANTS_TABLE,
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [{"AttributeName": "grantId", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "grantId", "AttributeType": "S"},
        {"AttributeName": "orderId", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            # the Razorpay webhook knows the order id and nothing else
            "IndexName": "order-index",
            "KeySchema": [{"AttributeName": "orderId", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
    "Tags": TAGS,
}


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def table_exists(name: str) -> bool:
    try:
        ddb().describe_table(TableName=name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def wait_active(name: str, timeout: int = 180) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        desc = ddb().describe_table(TableName=name)["Table"]
        if desc["TableStatus"] == "ACTIVE":
            gsis = desc.get("GlobalSecondaryIndexes") or []
            if all(g["IndexStatus"] == "ACTIVE" for g in gsis):
                return "ACTIVE"
        time.sleep(3)
    return "TIMEOUT"


def ensure_table(schema: dict, dry_run: bool) -> str:
    name = schema["TableName"]
    if table_exists(name):
        return "exists"
    if dry_run:
        return "would create"
    ddb().create_table(**schema)
    return f"created ({wait_active(name)})"


def ensure_ttl(name: str, attribute: str, dry_run: bool) -> str:
    """Compatibility hook; never re-enable DynamoDB TTL after retention disable."""
    if not table_exists(name):
        return "would verify" if dry_run else "table missing"
    current = ddb().describe_time_to_live(TableName=name)["TimeToLiveDescription"]
    if current.get("TimeToLiveStatus") != "DISABLED":
        raise RuntimeError("DynamoDB TTL unexpectedly enabled on " + name)
    return "TTL disabled"


def verify() -> int:
    failures = 0

    for name, expected_gsi in (
        (FILES_TABLE, "owner-created-index"),
        (GRANTS_TABLE, "order-index"),
    ):
        if not table_exists(name):
            print(f"FAIL {name} missing")
            failures += 1
            continue
        desc = ddb().describe_table(TableName=name)["Table"]
        print(f"PASS {name} {desc['TableStatus']}")

        gsis = {g["IndexName"]: g for g in desc.get("GlobalSecondaryIndexes") or []}
        if expected_gsi in gsis:
            print(f"PASS   GSI {expected_gsi} {gsis[expected_gsi]['IndexStatus']}")
        else:
            print(f"FAIL   GSI {expected_gsi} missing (have: {sorted(gsis)})")
            failures += 1

        if desc.get("BillingModeSummary", {}).get("BillingMode") != "PAY_PER_REQUEST":
            print(f"FAIL   {name} is not PAY_PER_REQUEST")
            failures += 1

    ttl = ddb().describe_time_to_live(TableName=GRANTS_TABLE)["TimeToLiveDescription"]
    if ttl.get("TimeToLiveStatus") == "DISABLED":
        print("PASS grants DynamoDB TTL disabled")
    else:
        print(f"FAIL grants TTL unexpectedly enabled: {ttl}")
        failures += 1

    print()
    print("secure file sharing tables verified" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}")
    print(f"dry run: {args.dry_run}\n")
    print(f"{FILES_TABLE}: {ensure_table(FILES_SCHEMA, args.dry_run)}")
    print(f"{GRANTS_TABLE}: {ensure_table(GRANTS_SCHEMA, args.dry_run)}")
    print(f"grants TTL: {ensure_ttl(GRANTS_TABLE, 'expiresAt', args.dry_run)}")

    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0

    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
