"""Metric filters + alarms for the three Conversation Routing signals.

Why these exist while routing is dormant — that ordering IS the point
---------------------------------------------------------------------
Measured over the 30 days to 2026-10-06: **zero** `standby` webhooks, **zero**
`messaging_handovers` webhooks, and zero occurrences of either routing error code, across
all three log groups, against 3,994 ingress events and 473 real customer messages. So all
three alarms will sit in OK-with-no-data on the day they are created.

But routing **was** live on both WABAs between 2026-07-21 and 2026-08-01, driven by the
Meta Business Agent, and the record of it survived only in a 10-deep DynamoDB ring buffer
rather than anywhere a person would look. More importantly, the thing that turns routing
back on is **a console toggle by the owner, not a deploy by us**: per Meta's Get started
guide, enabling a Business Agent on a phone number automatically makes it the sole primary
for messaging entry points and moves previous primaries to standby. One click flips us into
standby with no warning and no deploy on our side.

An alarm that only gets created after the thing it watches for has happened is not
monitoring, it is archaeology. These three are the early warning that someone flipped the
switch.

The three signals
-----------------
* `standby_webhook` — a standby copy arrived, which means another responder now owns the
  thread. This is the single highest-value signal here: it is the first observable
  consequence of a routing configuration appearing.

* `thread_control_changed` — a `messaging_handovers` event was parsed. Control moved.

* `routing_ownership_rejected` — Meta refused a send or a call action with `2494191` or
  `138038` because we do not own the thread / are not the Call primary. This is the
  failure itself rather than a precursor, and it is customer-visible: the customer taps a
  menu row and nothing arrives.

Substring matching, and why that is wanted here
-----------------------------------------------
`"standby_webhook"` is a substring pattern, so it also matches the existing
`standby_webhook_error` line in the inbound handler. That is deliberate rather than
tolerated: both mean standby traffic arrived, and the error variant means it arrived AND we
could not parse it, which is strictly more urgent. Suppressing it to get an exact match
would hide the worse case.

Threshold is 0, not a rate
--------------------------
Each occurrence is individually actionable and all three are rare by construction. An
average or a percentage would hide the first one, and the first one is the whole purpose.
`TreatMissingData='notBreaching'` because no data is the expected steady state today, and
an alarm parked in INSUFFICIENT_DATA forever is an alarm people learn to ignore.

Follows scripts/provision_direct_send_alarms.py exactly: boto3 because ampx cannot run in
the agent environment, and every put_* is an upsert, so re-running is safe and idempotent.

Cost: metric filters are free; three alarms at roughly $0.10/month each.

Usage:
    .venv/bin/python scripts/provision_conversation_routing_alarms.py
    .venv/bin/python scripts/provision_conversation_routing_alarms.py --verify
"""
import argparse

import boto3

REGION = "us-east-1"
NS = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

INBOUND = "/aws/lambda/wecare-inbound-whatsapp"
OUTBOUND = "/aws/lambda/wecare-outbound-whatsapp"
CALLING = "/aws/lambda/wecare-whatsapp-calling"

SIGNALS = [
    {
        "event": "standby_webhook",
        "filterName": "conversation-routing-standby-webhook",
        "metricName": "StandbyWebhookReceived",
        "alarmName": "wecare-standby-webhook-received",
        # Only the worker sees the standby nesting; the ingress forwards it verbatim.
        "logGroups": [INBOUND],
        "description": (
            "standby_webhook logged - a WhatsApp standby copy arrived, meaning another "
            "responder (most likely Meta Business Agent, app 1143680903703001) now owns "
            "the thread. Zero of these in the 30 days to 2026-10-06, so one firing is a "
            "state change: a Conversation Routing configuration now exists, or a Business "
            "Agent was enabled on a phone number. Check whether STANDBY_REPLY_ENABLED "
            "should be set to false on wecare-inbound-whatsapp. Substring match, so this "
            "also catches standby_webhook_error, which is strictly more urgent."
        ),
    },
    {
        "event": "thread_control_changed",
        "filterName": "conversation-routing-thread-control-changed",
        "metricName": "ThreadControlChanged",
        "alarmName": "wecare-thread-control-changed",
        "logGroups": [INBOUND],
        "description": (
            "thread_control_changed logged - a messaging_handovers webhook was parsed, so "
            "WhatsApp thread ownership moved between responders. Last real occurrence was "
            "2026-08-01T13:55:48Z. Read `control`, `previousOwnerRole` and `newOwnerRole` "
            "on the log line: control_taken means we may have LOST a thread, and a send "
            "from a non-owner is rejected by Meta rather than silently dropped."
        ),
    },
    {
        "event": "routing_ownership_rejected",
        "filterName": "conversation-routing-ownership-rejected",
        "metricName": "RoutingOwnershipRejected",
        "alarmName": "wecare-routing-ownership-rejected",
        # Both senders: outbound is every message send, calling is every call action.
        "logGroups": [OUTBOUND, CALLING],
        "description": (
            "routing_ownership_rejected logged (Meta 2494191 or 138038) - Meta refused a "
            "send or a call action because we do not own the thread, or are not the Call "
            "primary for that entry point. This one is CUSTOMER-VISIBLE: the customer taps "
            "a menu row, a list row, submits a flow or checks out a cart, and nothing "
            "arrives. Not retryable - the remedy is the routing configuration in Meta "
            "Business Suite, which is console-only and owner-only."
        ),
    },
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="read back the alarms without writing anything")
    args = parser.parse_args(argv)

    cw = boto3.client("cloudwatch", region_name=REGION)
    names = [s["alarmName"] for s in SIGNALS]

    if not args.verify:
        logs = boto3.client("logs", region_name=REGION)
        for sig in SIGNALS:
            for lg in sig["logGroups"]:
                logs.put_metric_filter(
                    logGroupName=lg,
                    filterName=sig["filterName"],
                    filterPattern=f'"{sig["event"]}"',
                    metricTransformations=[{
                        "metricName": sig["metricName"],
                        "metricNamespace": NS,
                        "metricValue": "1",
                        "defaultValue": 0.0,
                    }],
                )
                print(f'metric filter {sig["filterName"]} set on {lg}')

            cw.put_metric_alarm(
                AlarmName=sig["alarmName"],
                AlarmDescription=sig["description"],
                Namespace=NS,
                MetricName=sig["metricName"],
                Statistic="Sum",
                Period=300,
                EvaluationPeriods=1,
                # One occurrence is actionable. All three are rare by construction.
                Threshold=0.0,
                ComparisonOperator="GreaterThanThreshold",
                TreatMissingData="notBreaching",
                AlarmActions=[SNS_ARN],
                OKActions=[],
            )
            print(f'alarm {sig["alarmName"]} upserted')

    live = {a["AlarmName"]: a for a in cw.describe_alarms(AlarmNames=names)["MetricAlarms"]}
    problems = []
    for name in names:
        alarm = live.get(name)
        if not alarm:
            problems.append(f"alarm {name} does not exist")
            continue
        if SNS_ARN not in alarm.get("AlarmActions", []):
            problems.append(f"alarm {name} has no action routing to a human")
        print(f'verify: {name} state={alarm["StateValue"]} '
              f'alarm_actions={len(alarm["AlarmActions"])}')

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nconversation routing alarms verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
