#!/usr/bin/env python3
"""Provision/backfill the strong customer identity claim registry.

Dry-run is the default.  The rollout is additive and fail-closed:
- creates stack-wecare-digital-IdentityClaimsTable (claimKey HASH, PAY_PER_REQUEST, PITR);
- refuses backfill if live ContactsTable already has duplicate phone/email ownership;
- backfills PHONE#/EMAIL# claims conditionally;
- grants only GetItem/UpdateItem/DeleteItem on the registry to contact-writing Lambda roles;
- verifies every live contact strong identity resolves to that same contact.

No phone, email or customer id is printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CLAIMS_TABLE = "stack-wecare-digital-IdentityClaimsTable"
ROLES = (
    "wecare-digital-lambda-role",
    "wecare-customer-profile-role",
    "wecare-customer-registration-role",
    "wecare-blog-subscribe-role",
)
POLICY_NAME = "CustomerIdentityClaimsRegistry"
MANAGED_POLICY_NAME = "wecare-customer-identity-claims"


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def resource():
    return boto3.resource("dynamodb", region_name=REGION)


def iam():
    return boto3.client("iam")


def account_id():
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def exists_table(name):
    try:
        return ddb().describe_table(TableName=name)["Table"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise


def ensure_table(apply):
    current = exists_table(CLAIMS_TABLE)
    if current:
        return "exists"
    if not apply:
        return "would create"
    ddb().create_table(
        TableName=CLAIMS_TABLE,
        AttributeDefinitions=[{"AttributeName": "claimKey", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "claimKey", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
        SSESpecification={"Enabled": True},
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "CustomerIdentityClaims"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=CLAIMS_TABLE)
    ddb().update_continuous_backups(
        TableName=CLAIMS_TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )
    return "created"


def scan(table):
    rows, key = [], None
    while True:
        kw = {}
        if key:
            kw["ExclusiveStartKey"] = key
        page = table.scan(**kw)
        rows.extend(page.get("Items") or [])
        key = page.get("LastEvaluatedKey")
        if not key:
            return rows


def live(row):
    return (
        not row.get("deletedAt")
        and not row.get("isDeleted")
        and str(row.get("mergeState") or "").strip().lower() != "merged"
    )


def phone_key(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return "PHONE#+" + digits if 7 <= len(digits) <= 15 else ""


def email_key(value):
    email = str(value or "").strip().lower()
    return "EMAIL#" + email if email and "@" in email else ""


def inventory():
    contacts = [r for r in scan(resource().Table(CONTACTS_TABLE)) if live(r)]
    ownership = defaultdict(set)
    expected = {}
    for row in contacts:
        cid = str(row.get("id") or row.get("contactId") or "").strip()
        if not cid:
            continue
        for claim_key in (phone_key(row.get("phone")), email_key(row.get("email"))):
            if not claim_key:
                continue
            ownership[claim_key].add(cid)
            expected[claim_key] = cid
    conflicts = [ids for ids in ownership.values() if len(ids) > 1]
    return contacts, expected, conflicts


def grant_roles(apply):
    """Attach a small customer-managed policy instead of growing already-large inline policies."""
    account = account_id()
    table_arn = f"arn:aws:dynamodb:{REGION}:{account}:table/{CLAIMS_TABLE}"
    policy_arn = f"arn:aws:iam::{account}:policy/{MANAGED_POLICY_NAME}"
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "CustomerIdentityClaims",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
            ],
            "Resource": table_arn,
        }],
    }

    try:
        iam().get_policy(PolicyArn=policy_arn)
        policy_state = "exists"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        policy_state = "would create"
        if apply:
            iam().create_policy(
                PolicyName=MANAGED_POLICY_NAME,
                PolicyDocument=json.dumps(policy),
                Description="Minimal access to WECARE.DIGITAL customer identity claims registry",
            )
            policy_state = "created"

    states = {"managedPolicy": policy_state}
    for role in ROLES:
        try:
            iam().get_role(RoleName=role)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchEntity":
                states[role] = "absent (future provisioner owns it)"
                continue
            raise
        if not apply:
            states[role] = "would attach"
            continue
        iam().attach_role_policy(RoleName=role, PolicyArn=policy_arn)
        states[role] = "attached"
    return states


def claim(table, claim_key, cid, apply):
    current = table.get_item(Key={"claimKey": claim_key}, ConsistentRead=True).get("Item") or {}
    if current and str(current.get("contactId") or "") != cid:
        return "conflict"
    if not apply:
        return "exists" if current else "would create"
    now = int(time.time())
    try:
        table.update_item(
            Key={"claimKey": claim_key},
            UpdateExpression=(
                "SET contactId=:cid, identityType=:kind, claimedAt=if_not_exists(claimedAt,:now), "
                "updatedAt=:now"
            ),
            ConditionExpression="attribute_not_exists(claimKey) OR contactId=:cid",
            ExpressionAttributeValues={
                ":cid": cid,
                ":kind": claim_key.split("#", 1)[0],
                ":now": now,
            },
        )
        return "ensured"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return "conflict"
        raise


def backfill(apply):
    contacts, expected, conflicts = inventory()
    if conflicts:
        return {
            "ok": False,
            "liveContacts": len(contacts),
            "expectedClaims": len(expected),
            "duplicateIdentityGroups": len(conflicts),
            "message": "ContactsTable is not unique; no claims written",
        }
    table_exists = bool(exists_table(CLAIMS_TABLE))
    if apply and not table_exists:
        raise RuntimeError("claim table must exist before backfill")
    table = resource().Table(CLAIMS_TABLE) if table_exists else None
    counts = defaultdict(int)
    for claim_key, cid in expected.items():
        if not table_exists and not apply:
            counts["would create"] += 1
        else:
            counts[claim(table, claim_key, cid, apply)] += 1
    return {
        "ok": counts["conflict"] == 0,
        "liveContacts": len(contacts),
        "expectedClaims": len(expected),
        "duplicateIdentityGroups": 0,
        "results": dict(counts),
    }


def verify():
    if not exists_table(CLAIMS_TABLE):
        return {"ok": False, "reason": "claims table missing"}
    contacts, expected, conflicts = inventory()
    table = resource().Table(CLAIMS_TABLE)
    wrong = missing = 0
    for claim_key, cid in expected.items():
        row = table.get_item(Key={"claimKey": claim_key}, ConsistentRead=True).get("Item") or {}
        if not row:
            missing += 1
        elif str(row.get("contactId") or "") != cid:
            wrong += 1
    table_meta = ddb().describe_table(TableName=CLAIMS_TABLE)["Table"]
    pitr = ddb().describe_continuous_backups(TableName=CLAIMS_TABLE)
    return {
        "ok": not conflicts and missing == 0 and wrong == 0
              and table_meta.get("TableStatus") == "ACTIVE",
        "liveContacts": len(contacts),
        "expectedClaims": len(expected),
        "duplicateIdentityGroups": len(conflicts),
        "missingClaims": missing,
        "wrongOwnerClaims": wrong,
        "tableStatus": table_meta.get("TableStatus"),
        "pitrStatus": (
            pitr.get("ContinuousBackupsDescription", {})
                .get("PointInTimeRecoveryDescription", {})
                .get("PointInTimeRecoveryStatus")
        ),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    if args.verify:
        report = verify()
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    mode = "apply" if args.apply else "dry-run"
    table_state = ensure_table(args.apply)
    result = backfill(args.apply)
    roles = grant_roles(args.apply)
    report = {"mode": mode, "table": table_state, "backfill": result, "roles": roles}
    if args.apply and result.get("ok"):
        report["verify"] = verify()
    print(json.dumps(report, indent=2))
    if not result.get("ok"):
        return 1
    if args.apply and not report.get("verify", {}).get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
