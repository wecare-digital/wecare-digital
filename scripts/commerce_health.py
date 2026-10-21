#!/usr/bin/env python3
"""Read-only business payment health + deployment consistency for the commerce path.

Why this exists
---------------
A Lambda error alarm catches a function THROWING. It does not catch the quieter failures the
commerce acceptance review called out: a verified capture whose order never materialised, a paid
order stuck waiting for a customer link, an unacknowledged parked capture, or a deployment whose
live alias / serving index / reconciliation target drifted from the intended release. This script
reports those directly, read-only, so an operator (or a scheduled check) can see business health
rather than infer it from the absence of errors.

It NEVER writes, charges, sends, or deletes. Every count degrades rather than raising, so one
unreadable table does not blank the whole report.

    python scripts/commerce_health.py            # full report
    python scripts/commerce_health.py --json      # machine-readable
    python scripts/commerce_health.py --verify     # exit 1 if any health signal is non-green

Exit codes: 0 all green, 1 a health signal needs attention, 2 an AWS call failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
IDENTITY_CLAIMS_TABLE = "stack-wecare-digital-IdentityClaimsTable"
ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
QUARANTINE_PREFIX = "CAPTUREQUARANTINE#"

# The intended live release shape, asserted by the deployment-consistency section. These are the
# facts a drift would silently break: the website order history must serve the v2 index (channel +
# customerUuid), and the reconciliation schedule must still target the webhook's live alias.
EXPECTED_SERVING_INDEX = "customerId-createdAt-v2-index"
RECONCILIATION_RULE = "wecare-commerce-customer-links"
RECONCILIATION_TARGET_FN = "wecare-razorpay-webhook"


def _ddb():
    return boto3.resource("dynamodb", region_name=REGION)


def _scan_count(table, **kwargs) -> tuple[int, list]:
    """Count + collect rows across all pages. Returns (count, rows)."""
    rows, count = [], 0
    while True:
        page = table.scan(**kwargs)
        items = page.get("Items") or []
        rows += items
        count += len(items)
        key = page.get("LastEvaluatedKey")
        if not key:
            return count, rows
        kwargs["ExclusiveStartKey"] = key


def payment_health(ddb) -> dict:
    """The business signals, each a count an operator can act on."""
    now = int(time.time())
    out: dict = {}

    # Paid attempts whose order never materialised: PAYMENT_PAID with no orderId. This is the
    # "money moved, order missing" signal the recovery of the ₹4.67 payment was about.
    try:
        attempts = ddb.Table(ATTEMPTS_TABLE)
        paid, rows = _scan_count(attempts, FilterExpression=Attr("status").eq("PAYMENT_PAID"))
        missing = [r for r in rows if not str(r.get("orderId") or "")]
        out["paidAttempts"] = paid
        out["paidAttemptsMissingOrder"] = len(missing)
        out["paidAttemptsMissingOrderIds"] = [str(r.get("paymentAttemptId") or "")
                                              for r in missing][:20]
    except (ClientError, BotoCoreError) as exc:
        out["attempts_error"] = type(exc).__name__

    # Orders: finalized vs still waiting for a customer link, and the oldest pending age.
    try:
        orders = ddb.Table(ORDERS_TABLE)
        total, all_rows = _scan_count(orders, ProjectionExpression="finalizationStage, createdAt")
        pending = [r for r in all_rows
                   if str(r.get("finalizationStage") or "") == "NEEDS_CUSTOMER_LINK"]
        finalized = sum(1 for r in all_rows
                        if str(r.get("finalizationStage") or "") == "ORDER_FINALIZED")
        oldest = min((int(r["createdAt"]) for r in pending
                      if str(r.get("createdAt") or "").lstrip("-").isdigit()), default=None)
        out["ordersTotal"] = total
        out["ordersFinalized"] = finalized
        out["ordersPendingCustomerLink"] = len(pending)
        out["oldestPendingLinkAgeSeconds"] = (now - oldest) if oldest is not None else 0
    except (ClientError, BotoCoreError) as exc:
        out["orders_error"] = type(exc).__name__

    # Parked captures (quarantine): how many, and how many a human has NOT yet acknowledged or
    # resolved. An unacknowledged row is the one that needs attention.
    try:
        keys = ddb.Table(KEYS_TABLE)
        _, krows = _scan_count(keys, FilterExpression=Attr("kind").eq("CAPTURE_QUARANTINE"))
        unresolved = [r for r in krows if str(r.get("status") or "") != "RESOLVED"]
        unacknowledged = [r for r in krows if not r.get("acknowledged")]
        out["quarantinedCaptures"] = len(krows)
        out["quarantineUnresolved"] = len(unresolved)
        out["quarantineUnacknowledged"] = len(unacknowledged)
    except (ClientError, BotoCoreError) as exc:
        out["quarantine_error"] = type(exc).__name__
    return out


def deployment_consistency() -> dict:
    """Live-vs-intended checks that a Lambda error alarm cannot see."""
    out: dict = {}
    lam = boto3.client("lambda", region_name=REGION)
    ddb_client = boto3.client("dynamodb", region_name=REGION)
    events = boto3.client("events", region_name=REGION)

    # Strong identity serialization must be live before any contact writer can safely create.
    try:
        claim_meta = ddb_client.describe_table(TableName=IDENTITY_CLAIMS_TABLE)["Table"]
        out["identityClaimsTableStatus"] = claim_meta.get("TableStatus", "")
        out["identityClaimsTableActive"] = claim_meta.get("TableStatus") == "ACTIVE"
        backups = ddb_client.describe_continuous_backups(
            TableName=IDENTITY_CLAIMS_TABLE
        ).get("ContinuousBackupsDescription", {})
        pitr = backups.get("PointInTimeRecoveryDescription", {}).get(
            "PointInTimeRecoveryStatus", ""
        )
        out["identityClaimsPitrStatus"] = pitr
        out["identityClaimsPitrEnabled"] = pitr == "ENABLED"
    except (ClientError, BotoCoreError) as exc:
        out["identityClaims_error"] = type(exc).__name__

    # The website order history must serve the v2 index (channel + customerUuid).
    try:
        env = lam.get_function_configuration(
            FunctionName="wecare-customer-orders", Qualifier="live"
        ).get("Environment", {}).get("Variables", {})
        serving = env.get("ORDERS_BY_CUSTOMER_INDEX", "")
        out["servingIndex"] = serving
        out["servingIndexMatches"] = serving == EXPECTED_SERVING_INDEX
    except (ClientError, BotoCoreError) as exc:
        out["servingIndex_error"] = type(exc).__name__

    # That index must be ACTIVE (a repoint to a CREATING index would 503 every history read).
    try:
        gsis = ddb_client.describe_table(TableName=ORDERS_TABLE)["Table"].get(
            "GlobalSecondaryIndexes", [])
        v2 = next((g for g in gsis if g["IndexName"] == EXPECTED_SERVING_INDEX), None)
        out["servingIndexStatus"] = v2["IndexStatus"] if v2 else "ABSENT"
        out["servingIndexActive"] = bool(v2 and v2["IndexStatus"] == "ACTIVE"
                                         and not v2.get("Backfilling"))
    except (ClientError, BotoCoreError) as exc:
        out["servingIndexStatus_error"] = type(exc).__name__

    # The 5-minute reconciliation rule must exist, be ENABLED, and target the webhook's live alias.
    try:
        rule = events.describe_rule(Name=RECONCILIATION_RULE)
        targets = events.list_targets_by_rule(Rule=RECONCILIATION_RULE).get("Targets", [])
        target_arns = [t.get("Arn", "") for t in targets]
        out["reconciliationRuleState"] = rule.get("State", "")
        out["reconciliationScheduled"] = rule.get("ScheduleExpression", "")
        out["reconciliationTargetsLiveAlias"] = any(
            f":function:{RECONCILIATION_TARGET_FN}:live" in a for a in target_arns)
        out["reconciliationEnabled"] = rule.get("State") == "ENABLED"
    except (ClientError, BotoCoreError) as exc:
        out["reconciliationRule_error"] = type(exc).__name__
    return out


def _green(health: dict, deploy: dict) -> bool:
    """Every signal in its healthy state."""
    return (health.get("paidAttemptsMissingOrder", 0) == 0
            and health.get("ordersPendingCustomerLink", 0) == 0
            and health.get("quarantineUnacknowledged", 0) == 0
            and deploy.get("identityClaimsTableActive") is True
            and deploy.get("identityClaimsPitrEnabled") is True
            and deploy.get("servingIndexMatches") is True
            and deploy.get("servingIndexActive") is True
            and deploy.get("reconciliationEnabled") is True
            and deploy.get("reconciliationTargetsLiveAlias") is True
            and not any(k.endswith("_error") for k in {**health, **deploy}))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--verify", action="store_true", help="exit 1 if any signal is non-green")
    args = ap.parse_args(argv)

    try:
        ddb = _ddb()
        health = payment_health(ddb)
        deploy = deployment_consistency()
    except (ClientError, BotoCoreError) as exc:
        print(f"AWS call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    green = _green(health, deploy)

    if args.json:
        print(json.dumps({"green": green, "paymentHealth": health,
                          "deploymentConsistency": deploy}, indent=2, default=str))
        return 0 if green or not args.verify else 1

    print("=" * 70)
    print("COMMERCE PAYMENT HEALTH")
    print("=" * 70)
    print(f"  paid attempts                   : {health.get('paidAttempts', '?')}")
    print(f"  ... MISSING an order            : {health.get('paidAttemptsMissingOrder', '?')}")
    if health.get("paidAttemptsMissingOrderIds"):
        print(f"      {health['paidAttemptsMissingOrderIds']}")
    print(f"  orders total / finalized        : {health.get('ordersTotal', '?')}"
          f" / {health.get('ordersFinalized', '?')}")
    print(f"  orders pending customer link    : {health.get('ordersPendingCustomerLink', '?')}"
          f"  (oldest {health.get('oldestPendingLinkAgeSeconds', '?')}s)")
    print(f"  quarantined captures            : {health.get('quarantinedCaptures', '?')}"
          f"  (unresolved {health.get('quarantineUnresolved', '?')},"
          f" unacknowledged {health.get('quarantineUnacknowledged', '?')})")

    print("\n" + "=" * 70)
    print("DEPLOYMENT CONSISTENCY")
    print("=" * 70)
    print(f"  identity claims table           : {deploy.get('identityClaimsTableStatus', '?')}"
          f"  (pitr={deploy.get('identityClaimsPitrStatus', '?')})")
    print(f"  serving index                   : {deploy.get('servingIndex', '?')}"
          f"  (matches={deploy.get('servingIndexMatches')})")
    print(f"  serving index status            : {deploy.get('servingIndexStatus', '?')}"
          f"  (active={deploy.get('servingIndexActive')})")
    print(f"  reconciliation rule             : {deploy.get('reconciliationScheduled', '?')}"
          f"  (enabled={deploy.get('reconciliationEnabled')})")
    print(f"  ... targets webhook :live       : {deploy.get('reconciliationTargetsLiveAlias')}")

    errors = [k for k in {**health, **deploy} if k.endswith("_error")]
    if errors:
        print(f"\n  READ ERRORS (degraded): {errors}")

    print("\n" + "=" * 70)
    print("RESULT:", "GREEN - every signal healthy" if green
          else "ATTENTION - one or more signals need action")
    print("=" * 70)
    return 0 if green or not args.verify else 1


if __name__ == "__main__":
    sys.exit(main())
