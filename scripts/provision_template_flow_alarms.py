"""
Metric filters + alarms for WhatsApp template and Flow status alerts.

Why
---
Meta tells us when a template or a Flow stops working, by webhook, and until 2026-10-25 that
news only reached a log line nobody watched:

* `template_status_alert` (inbound `_process_template_status`): a template went REJECTED,
  PAUSED, DISABLED or FLAGGED. Payment, invoice, order status, OTP, leave-review and Vault
  sends all depend on one approved template each, so a PAUSED one silently stops a customer
  path. The line carries `registered: true` when automation sends that template.
* `flow_status_alert` (inbound `_process_flow_event`): a Flow went BLOCKED or THROTTLED, a
  Flow the runtime still opens went DEPRECATED, an endpoint/client health alert ACTIVATED, or
  Meta warned that a Flow version is about to freeze or expire.

Threshold is 1: each event is rare and individually actionable. `TreatMissingData=notBreaching`
because silence is the steady state. Every put_* is an upsert, so the script is idempotent.
Same convention as scripts/provision_direct_send_alarms.py.

Usage:
    python scripts/provision_template_flow_alarms.py           # show what would be set
    python scripts/provision_template_flow_alarms.py --apply   # set filters + alarms, then read back

Cost: metric filters are free; two alarms at roughly $0.10/month each.
"""
from __future__ import annotations

import argparse
import sys

import boto3

REGION = "us-east-1"
NS = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"
# Both events are logged by the webhook worker only.
LOG_GROUP = "/aws/lambda/wecare-inbound-whatsapp"

SIGNALS = [
    {
        "event": "template_status_alert",
        "filterName": "whatsapp-template-status-alert",
        "metricName": "WhatsAppTemplateStatusAlert",
        "alarmName": "wecare-whatsapp-template-status-alert",
        "description": (
            "template_status_alert logged by wecare-inbound-whatsapp: Meta reported a WhatsApp "
            "template REJECTED, PAUSED, DISABLED or FLAGGED. When the line says registered=true, "
            "automation (payment, invoice, order status, OTP, leave review, Vault) sends that "
            "template and those sends now fail. Check the template in WhatsApp Manager and run "
            "scripts/check_whatsapp_templates_live.py."
        ),
    },
    {
        "event": "flow_status_alert",
        "filterName": "whatsapp-flow-status-alert",
        "metricName": "WhatsAppFlowStatusAlert",
        "alarmName": "wecare-whatsapp-flow-status-alert",
        "description": (
            "flow_status_alert logged by wecare-inbound-whatsapp: a WhatsApp Flow went BLOCKED "
            "or THROTTLED, a Flow in use went DEPRECATED, an endpoint health alert activated, or "
            "a Flow version is about to freeze/expire. Customers may be unable to open it. Check "
            "WhatsApp Manager > Flows; the event is also in Workspace (GET /waba/events?type=flows)."
        ),
    },
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the filters and alarms")
    args = ap.parse_args()

    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)

    # Refuse to attach a filter to a log group that does not exist: put_metric_filter would
    # fail anyway, and an alarm with no filter behind it is silence that looks like health.
    groups = logs.describe_log_groups(logGroupNamePrefix=LOG_GROUP)["logGroups"]
    if not any(g["logGroupName"] == LOG_GROUP for g in groups):
        print(f"log group {LOG_GROUP} not found; nothing set")
        return 1

    for sig in SIGNALS:
        if not args.apply:
            print(f'would set filter {sig["filterName"]} on {LOG_GROUP} '
                  f'("{sig["event"]}" -> {NS}/{sig["metricName"]}) and alarm {sig["alarmName"]}')
            continue
        logs.put_metric_filter(
            logGroupName=LOG_GROUP,
            filterName=sig["filterName"],
            filterPattern=f'"{sig["event"]}"',
            metricTransformations=[{
                "metricName": sig["metricName"],
                "metricNamespace": NS,
                "metricValue": "1",
                "defaultValue": 0.0,
            }],
        )
        print(f'metric filter {sig["filterName"]} set on {LOG_GROUP}')
        cw.put_metric_alarm(
            AlarmName=sig["alarmName"],
            AlarmDescription=sig["description"],
            Namespace=NS,
            MetricName=sig["metricName"],
            Statistic="Sum",
            Period=300,
            EvaluationPeriods=1,
            Threshold=0.0,
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            AlarmActions=[SNS_ARN],
            OKActions=[],
        )
        print(f'alarm {sig["alarmName"]} set')

    if not args.apply:
        print("dry run: nothing written (pass --apply)")
        return 0

    # Read back rather than assume.
    ok = True
    filters = {f["filterName"]: f for f in
               logs.describe_metric_filters(logGroupName=LOG_GROUP)["metricFilters"]}
    alarms = {a["AlarmName"]: a for a in
              cw.describe_alarms(AlarmNames=[s["alarmName"] for s in SIGNALS])["MetricAlarms"]}
    for sig in SIGNALS:
        f = filters.get(sig["filterName"])
        a = alarms.get(sig["alarmName"])
        good = (f is not None and f["filterPattern"] == f'"{sig["event"]}"'
                and a is not None and a["AlarmActions"] == [SNS_ARN]
                and a["MetricName"] == sig["metricName"] and a["Namespace"] == NS)
        ok &= good
        print(f'verify: {sig["alarmName"]} {"OK" if good else "MISMATCH"} '
              f'state={a["StateValue"] if a else "missing"}')
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
