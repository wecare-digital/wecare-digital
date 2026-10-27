"""Read-only production smoke check for the WhatsApp backend.

This script never sends a customer message. It validates live Lambda aliases,
the bounded internal operational contracts used by Workspace MCP, the delivery
reconciliation backstop, and the two ambiguity alarms. A mutation smoke must
remain a separate explicitly gated tool with a QA recipient.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
EXPECTED = {
    "wecare-commerce": "Active",
    "wecare-checkout": "Active",
    "wecare-inbound-whatsapp": "Active",
    "wecare-outbound-whatsapp": "Active",
    "wecare-whatsapp-business-api": "Active",
    "wecare-service-api": "Active",
    "wecare-workspace-mcp": "Active",
}
RECONCILIATION_RULE = "wecare-whatsapp-delivery-reconciliation"
RECONCILIATION_SCHEDULE = "rate(10 minutes)"
RECONCILIATION_INPUT = {
    "internalAction": "reconcileUnknownDeliveries",
    "graceSeconds": 900,
    "maxPages": 5,
    "pageLimit": 50,
}
ALARM_NAMES = [
    "wecare-whatsapp-delivery-outcome-unknown",
    "wecare-whatsapp-delivery-reconciliation-stuck",
]


def invoke(lamb: Any, function: str, payload: dict) -> dict:
    response = lamb.invoke(
        FunctionName=function,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )
    stream = response["Payload"]
    try:
        raw = stream.read()
    finally:
        stream.close()
    if response.get("FunctionError"):
        raise RuntimeError(f"{function}: FunctionError")
    value = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{function}: non-object response")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    lamb = boto3.client("lambda", region_name=REGION)
    events = boto3.client("events", region_name=REGION)
    cloudwatch = boto3.client("cloudwatch", region_name=REGION)

    checks = []
    ok = True
    for fn, expected_tracing in EXPECTED.items():
        cfg = lamb.get_function_configuration(FunctionName=fn, Qualifier="live")
        row = {
            "name": fn,
            "version": cfg.get("Version"),
            "status": cfg.get("LastUpdateStatus"),
            "tracing": (cfg.get("TracingConfig") or {}).get("Mode"),
        }
        row["ok"] = row["status"] == "Successful" and row["tracing"] == expected_tracing
        checks.append(row)
        ok &= row["ok"]

    workspace_concurrency = lamb.get_function_concurrency(
        FunctionName="wecare-workspace-mcp"
    ).get("ReservedConcurrentExecutions")
    workspace_concurrency_ok = workspace_concurrency == 10
    ok &= workspace_concurrency_ok

    rule = events.describe_rule(Name=RECONCILIATION_RULE)
    targets = events.list_targets_by_rule(Rule=RECONCILIATION_RULE).get("Targets", [])
    target_arn = (
        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:wecare-whatsapp-business-api:live"
    )
    rule_ok = (
        rule.get("State") == "ENABLED"
        and rule.get("ScheduleExpression") == RECONCILIATION_SCHEDULE
        and len(targets) == 1
        and targets[0].get("Arn") == target_arn
        and json.loads(targets[0].get("Input") or "{}") == RECONCILIATION_INPUT
    )
    ok &= rule_ok

    alarm_rows = cloudwatch.describe_alarms(AlarmNames=ALARM_NAMES).get("MetricAlarms", [])
    alarm_state = {row.get("AlarmName"): row.get("StateValue") for row in alarm_rows}
    alarms_ok = len(alarm_rows) == len(ALARM_NAMES) and all(
        alarm_state.get(name) == "OK" for name in ALARM_NAMES
    )
    ok &= alarms_ok

    snapshot = invoke(
        lamb,
        "wecare-whatsapp-business-api:live",
        {"internalAction": "workspaceRead", "scope": "snapshot", "limit": 25},
    )
    unknown = invoke(
        lamb,
        "wecare-whatsapp-business-api:live",
        {"internalAction": "workspaceRead", "scope": "unknown_deliveries", "limit": 25},
    )
    orders = invoke(
        lamb,
        "wecare-service-api:live",
        {"internalAction": "workspaceOrders", "limit": 5},
    )

    contracts_ok = (
        snapshot.get("scope") == "snapshot"
        and isinstance(snapshot.get("unknownDeliveries"), dict)
        and unknown.get("scope") == "unknown_deliveries"
        and isinstance(unknown.get("items"), list)
        and isinstance(orders.get("orders"), list)
    )
    ok &= contracts_ok
    print(json.dumps({
        "ok": ok,
        "functions": checks,
        "workspaceMcp": {
            "reservedConcurrency": workspace_concurrency,
            "ok": workspace_concurrency_ok,
        },
        "reconciliation": {
            "rule": RECONCILIATION_RULE,
            "state": rule.get("State"),
            "schedule": rule.get("ScheduleExpression"),
            "ok": rule_ok,
        },
        "alarms": {"states": alarm_state, "ok": alarms_ok},
        "snapshot": snapshot,
        "unknownDeliveries": {
            "count": len(unknown.get("items") or []),
            "nextCursor": bool(unknown.get("nextCursor")),
        },
        "orders": {"count": len(orders.get("orders") or [])},
        "contractsOk": contracts_ok,
        "mutationFree": True,
    }, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
