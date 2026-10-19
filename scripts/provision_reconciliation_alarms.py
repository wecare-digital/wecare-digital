#!/usr/bin/env python3
"""Alarm the customer-order-link reconciliation health metrics.

Why this exists
---------------
The 5-minute reconciliation (`wecare-razorpay-webhook` invoked by the
`wecare-commerce-customer-links` schedule) now publishes four metrics to the
`WeCare/CustomerOrderLink` namespace (see `customer_order_link.reconcile_metrics` /
`razorpay-webhook._emit_reconciliation_metrics`). A Lambda error alarm would catch the sweep
THROWING; it would not catch the sweep running green while a backlog of paid-but-unlinked orders
grows, ages, or quietly fails to promote. These alarms cover that:

  ReconciliationFailures    > 0   over 5 min  — a promotion RAISED (storage error), not a no-op.
  PendingRemaining          > 50  for 30 min  — backlog that is not draining (not a transient
                                                 spike): some orders may be stuck ineligible.
  OldestPendingAgeSeconds   > 24h for 30 min  — a small backlog can still hide one OLD order a
                                                 customer has been waiting on; age catches what
                                                 count misses.

Thresholds are starting points an operator can tune. `TreatMissingData='notBreaching'` because the
steady state for a healthy system is a near-empty, fast-draining backlog.

MODELLED ON scripts/provision_identity_claim_alarms.py. Every put_metric_alarm is an upsert, so
this is idempotent. Routed to the confirmed-human topic wecare-alarm-notifications.

    python scripts/provision_reconciliation_alarms.py            # dry run, prints the alarms
    python scripts/provision_reconciliation_alarms.py --apply
    python scripts/provision_reconciliation_alarms.py --verify

Cost: three alarms at roughly $0.10/month each.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
NS = "WeCare/CustomerOrderLink"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

# alarm name -> (metric, statistic, period, evaluation_periods, threshold, comparison, description)
ALARMS = {
    "wecare-reconciliation-failures": (
        "ReconciliationFailures", "Sum", 300, 1, 0.0, "GreaterThanThreshold",
        "A customer-order-link promotion RAISED during the 5-minute reconciliation (a storage "
        "error, not a benign no-op). Investigate the razorpay-webhook logs for the sweep run."),
    "wecare-reconciliation-pending-backlog": (
        "PendingRemaining", "Maximum", 300, 6, 50.0, "GreaterThanThreshold",
        "Paid orders awaiting a customer link stayed above 50 for 30 minutes - the backlog is "
        "not draining. Some orders may be stuck ineligible rather than simply waiting for their "
        "customer to register."),
    "wecare-reconciliation-oldest-pending": (
        "OldestPendingAgeSeconds", "Maximum", 300, 6, 86400.0, "GreaterThanThreshold",
        "The oldest paid-but-unlinked order has been pending more than 24 hours - a customer may "
        "be waiting on an order that never appears in their website history. Age catches the one "
        "old order a small backlog count would hide."),
}


def _describe(cw, name: str) -> str:
    try:
        alarms = cw.describe_alarms(AlarmNames=[name]).get("MetricAlarms", [])
        if not alarms:
            return "absent"
        a = alarms[0]
        return (f"state={a['StateValue']} metric={a['MetricName']} "
                f"{a['ComparisonOperator']} {a['Threshold']} actions={len(a['AlarmActions'])}")
    except (ClientError, BotoCoreError) as exc:
        return f"read error {type(exc).__name__}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="create/update the alarms")
    ap.add_argument("--verify", action="store_true", help="report alarm state, exit 1 if absent")
    args = ap.parse_args(argv)

    cw = boto3.client("cloudwatch", region_name=REGION)

    if args.verify:
        missing = 0
        for name in ALARMS:
            state = _describe(cw, name)
            print(f"  {name}: {state}")
            missing += 1 if state == "absent" else 0
        print("\nRESULT:", "all present" if not missing else f"{missing} absent")
        return 1 if missing else 0

    print(f"namespace: {NS}")
    print(f"notification topic: {SNS_ARN.rsplit(':', 1)[-1]}\n")
    for name, (metric, stat, period, evals, threshold, comparison, desc) in ALARMS.items():
        print(f"  {name}")
        print(f"      {metric} {comparison} {threshold} ({stat}, {evals}x{period}s)")
        print(f"      {desc}")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
        return 0

    print("\napplying:")
    for name, (metric, stat, period, evals, threshold, comparison, desc) in ALARMS.items():
        try:
            cw.put_metric_alarm(
                AlarmName=name, AlarmDescription=desc, Namespace=NS, MetricName=metric,
                Statistic=stat, Period=period, EvaluationPeriods=evals, Threshold=threshold,
                ComparisonOperator=comparison, TreatMissingData="notBreaching",
                ActionsEnabled=True, AlarmActions=[SNS_ARN], OKActions=[SNS_ARN])
            print(f"  WROTE {name}")
        except (ClientError, BotoCoreError) as exc:
            print(f"  FAILED {name}: {type(exc).__name__}", file=sys.stderr)
            return 2

    print("\nverify:")
    for name in ALARMS:
        print(f"  {name}: {_describe(cw, name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
