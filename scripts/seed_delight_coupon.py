#!/usr/bin/env python3
"""Seed the default Delight coupon in the authoritative CouponsTable.

Dry run by default. Pass --apply only from a non-root deployment/admin role after reviewing the
plan. The write is idempotent: an existing DELIGHT definition is read and compared, never
overwritten silently.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import boto3

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import coupon_store  # noqa: E402

TABLE = coupon_store.DEFAULT_TABLE_NAME
DELIGHT = {
    "code": "Delight",
    "name": "Delight",
    "discountKind": coupon_store.PERCENT_OFF,
    "percentOffBps": 5,
    "maximumDiscountPaise": 10000,
        "scopeNamespace": "stores",
    "currency": "INR",
}


def canonical(row):
    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "discountKind": row.get("discountKind"),
        "percentOffBps": int(row.get("percentOffBps") or 0),
        "maximumDiscountPaise": int(row.get("maximumDiscountPaise") or 0),
        "currency": row.get("currency"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the coupon; default is dry run")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=args.region).Table(TABLE)
    key = coupon_store.definition_key(DELIGHT["code"])
    existing = table.get_item(Key={coupon_store.KEY_ATTRIBUTE: key}, ConsistentRead=True).get("Item")
    expected = coupon_store.validate_definition(DELIGHT, created_by="system:seed-delight")

    plan = {
        "table": TABLE,
        "coupon": canonical(expected),
        "existing": canonical(existing) if existing else None,
        "action": "no-op" if existing and canonical(existing) == canonical(expected)
                  else "conflict" if existing else "create",
        "apply": args.apply,
    }
    print(json.dumps(plan, indent=2, default=str))

    if not args.apply or plan["action"] == "no-op":
        return 0
    if existing:
        raise SystemExit("DELIGHT exists with a different definition; refusing to overwrite")
    if not coupon_store.claim(table, expected):
        raise SystemExit("DELIGHT was created concurrently; inspect before retrying")
    print("created DELIGHT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
