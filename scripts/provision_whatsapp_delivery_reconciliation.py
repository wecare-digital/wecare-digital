"""Provision the WhatsApp ambiguous-delivery reconciliation schedule.

The rule invokes the existing WhatsApp Business API Lambda every 10 minutes. The handler never
resends messages. It only reconciles aged unknown rows when Meta Message History evidence exists,
and otherwise emits an alarmable stuck-delivery event.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
RULE_NAME = "wecare-whatsapp-delivery-reconciliation"
FUNCTION_NAME = "wecare-whatsapp-business-api"
ALIAS = "live"
SCHEDULE = "rate(10 minutes)"
STATEMENT_ID = "EventBridgeWhatsAppDeliveryReconciliation"
INPUT = {
    "internalAction": "reconcileUnknownDeliveries",
    "graceSeconds": 900,
    "maxPages": 5,
    "pageLimit": 50,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    events = boto3.client("events", region_name=REGION)
    lamb = boto3.client("lambda", region_name=REGION)
    target_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:{ALIAS}"
    rule_arn = f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{RULE_NAME}"

    if not args.apply:
        print(json.dumps({
            "rule": RULE_NAME,
            "schedule": SCHEDULE,
            "target": target_arn,
            "input": INPUT,
            "apply": False,
        }, indent=2))
        return 0

    rule = events.put_rule(
        Name=RULE_NAME,
        ScheduleExpression=SCHEDULE,
        State="ENABLED",
        Description="Reconcile aged ambiguous WhatsApp sends without resending.",
    )
    events.put_targets(
        Rule=RULE_NAME,
        Targets=[{
            "Id": "whatsapp-delivery-reconciliation",
            "Arn": target_arn,
            "Input": json.dumps(INPUT, separators=(",", ":")),
        }],
    )
    try:
        lamb.add_permission(
            FunctionName=FUNCTION_NAME,
            Qualifier=ALIAS,
            StatementId=STATEMENT_ID,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule.get("RuleArn") or rule_arn,
        )
    except lamb.exceptions.ResourceConflictException:
        pass

    live_rule = events.describe_rule(Name=RULE_NAME)
    targets = events.list_targets_by_rule(Rule=RULE_NAME).get("Targets", [])
    good = (
        live_rule.get("State") == "ENABLED"
        and live_rule.get("ScheduleExpression") == SCHEDULE
        and len(targets) == 1
        and targets[0].get("Arn") == target_arn
        and json.loads(targets[0].get("Input") or "{}") == INPUT
    )
    print(json.dumps({
        "rule": RULE_NAME,
        "state": live_rule.get("State"),
        "schedule": live_rule.get("ScheduleExpression"),
        "target": targets[0].get("Arn") if targets else None,
        "verified": good,
    }, indent=2))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
