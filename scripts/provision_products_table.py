#!/usr/bin/env python3
"""Provision the AWS-native product catalog table — the Wix Stores replacement.

Mirrors scripts/provision_gift_cards_table.py (the repo's boto3 provisioning
convention; the backend is NOT deployed via `ampx pipeline-deploy` — see
amplify.yml). PAY_PER_REQUEST, point-in-time recovery ON, RETAIN semantics
(DynamoDB tables are not auto-deleted). No CMK: a product catalog is not a secret
ledger (unlike gift cards), so the AWS-owned key is appropriate and avoids CMK
cost/complexity.

Shape (consumed by catalog_pricing / native_cart / native_checkout /
meta-catalog-sync _native_products):
    PK  id                     the Wix product UUID, preserved (Meta retailer-id contract)
    GSI slug-updatedAt-index   public /shop/<slug> lookup, newest first
    GSI status-updatedAt-index active | archived listing
    GSI category-updatedAt-index category listing
Item attrs (schemaless, written by the seed): title, slug, priceMinor (int paise),
currency, inventory, variants[], categories[], imageRefs[], tagline,
descriptionHtml, status, sourceId, updatedAt. A DynamoDB stream (NEW_AND_OLD_IMAGES)
is enabled so product changes can drive meta-catalog-sync natively (replacing the
Wix catalog webhook).

Usage:
    python scripts/provision_products_table.py            # dry run (default)
    python scripts/provision_products_table.py --apply    # 🔒 creates a billable table
    python scripts/provision_products_table.py --verify
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = "775261844268"
TABLE = "stack-wecare-digital-ProductsTable"
KEY_ATTRIBUTE = "id"

INDEXES = [
    ("slug-updatedAt-index", [("slug", "HASH"), ("updatedAt", "RANGE")]),
    ("status-updatedAt-index", [("status", "HASH"), ("updatedAt", "RANGE")]),
    ("category-updatedAt-index", [("category", "HASH"), ("updatedAt", "RANGE")]),
]

ATTRIBUTES = {
    KEY_ATTRIBUTE: "S",
    "slug": "S",
    "status": "S",
    "category": "S",
    "updatedAt": "S",
}


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def describe():
    try:
        return ddb().describe_table(TableName=TABLE)["Table"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise


def _gsi_defs():
    return [{
        "IndexName": name,
        "KeySchema": [{"AttributeName": a, "KeyType": t} for a, t in schema],
        "Projection": {"ProjectionType": "ALL"},
    } for name, schema in INDEXES]


def create(apply: bool) -> str:
    if describe():
        return "exists"
    if not apply:
        return (f"would create ({KEY_ATTRIBUTE} PK, PAY_PER_REQUEST, {len(INDEXES)} GSI, "
                f"stream NEW_AND_OLD_IMAGES, PITR, AWS-owned SSE)")
    ddb().create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": t}
                              for a, t in ATTRIBUTES.items()],
        KeySchema=[{"AttributeName": KEY_ATTRIBUTE, "KeyType": "HASH"}],
        GlobalSecondaryIndexes=_gsi_defs(),
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)
    ddb().update_continuous_backups(
        TableName=TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
    return "created"


def verify() -> int:
    t = describe()
    if not t:
        print(f"MISSING: {TABLE} does not exist"); return 1
    ok = True
    if t["BillingModeSummary"]["BillingMode"] != "PAY_PER_REQUEST":
        print("FAIL: not PAY_PER_REQUEST"); ok = False
    gsis = {g["IndexName"] for g in t.get("GlobalSecondaryIndexes", [])}
    for name, _ in INDEXES:
        if name not in gsis:
            print(f"FAIL: missing GSI {name}"); ok = False
    pitr = ddb().describe_continuous_backups(TableName=TABLE) \
        ["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"]
    if pitr != "ENABLED":
        print("FAIL: PITR not enabled"); ok = False
    print(f"{TABLE}: status={t['TableStatus']} GSIs={sorted(gsis)} PITR={pitr} "
          f"items={t.get('ItemCount')}")
    print("OK" if ok else "VERIFY FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="🔒 create the billable table")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        return verify()
    print(f"ProductsTable provisioning ({'APPLY' if args.apply else 'DRY RUN'}):")
    print("  create:", create(args.apply))
    if not args.apply:
        print("\nDRY RUN — nothing created. Re-run with --apply to create the table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
