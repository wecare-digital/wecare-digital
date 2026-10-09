"""Metric filters + alarms for the two WhatsApp payment-gate refusal events.

Why this exists, and why it is part of the gate change rather than a follow-up
-----------------------------------------------------------------------------
The readiness gates convert a provider outage into *silently no payment requests at all*. That
is the intended fail-closed direction under requirements statement 9, and it is a real
availability reduction — so it needs a compensating control, and this is it. Fail-closed is only
safe if someone hears it.

The discoverability problem is concrete, not theoretical. The inbound auto-send leg invokes the
invoice route with `InvocationType='Event'` and never reads the response, so a refusal is
invisible to the customer: they receive the invoice message and simply no payment request. The
handler-side ERROR line is the ONLY signal on that leg, which is why these two filters target the
handler events and not `payment_readiness`'s own `payment_readiness_blocked` WARNING — that line
carries no invoice id and no request id.

* `wa_payment_readiness_refused` means a live provider readback did not prove the configuration
  (or, at the boundary, the approved template). Every in-WhatsApp payment send on that function
  is refusing. Eight of the ten blocking states need a human; two are availability states that
  will clear on their own, which is why the alarm description says to read the `readiness` field
  rather than assuming an outage.

* `wa_payment_disabled_refused` means `WA_PAYMENTS_DISABLED` is set and the brake is being hit.
  Pulling the brake is a legitimate administrative act, so this is not a defect alarm — it exists
  so a pulled brake is visible as an EVENT rather than as silence, and so nobody spends a day
  debugging Meta while the kill switch is on.

Both functions are watched because both carry a gate: `wecare-invoice-engine` refuses before the
reserve-and-send transaction, and `wecare-outbound-whatsapp` refuses at the boundary every payment
send crosses.

Threshold is deliberately 1, not a rate. These events are rare by construction and each one is
individually actionable on a money path; averaging would hide the first.

`TreatMissingData='notBreaching'` because no data is the expected steady state.

MODELLED ON `scripts/provision_direct_send_alarms.py`, which is the working in-repo pattern for a
log-event metric filter. `provision_lambda_alarms.py` and `provision_alarm_coverage.py` cannot do
this: neither calls `put_metric_filter`, and both only create alarms on AWS-native Lambda metrics.

Created via boto3 because ampx cannot run in the agent environment. Every put_* is an upsert, so
this script is idempotent and safe to re-run.

Cost: metric filters are free; four alarms at roughly $0.10/month each.
"""
import boto3

REGION = "us-east-1"
NS = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

#: The two functions that carry a payment gate. One alarm per function per signal, so the alarm
#: name says which gate refused — the two answer different questions and a merged metric would
#: lose that.
GATED_FUNCTIONS = [
    "wecare-invoice-engine",
    "wecare-outbound-whatsapp",
]

SIGNALS = [
    {
        "event": "wa_payment_readiness_refused",
        "filterName": "wa-payment-readiness-refused",
        "metricName": "WaPaymentReadinessRefused",
        "alarmSuffix": "wa-payment-readiness-refused",
        "description": (
            "wa_payment_readiness_refused logged - a live provider readback did not prove the "
            "payment configuration, so an in-WhatsApp payment request was refused and NOTHING "
            "was charged. Read the `readiness` field on the log line: META_UNAVAILABLE and "
            "RAZORPAY_UNAVAILABLE are transient and answered 503; the other eight states are "
            "operator-actionable and answered 409. On the inbound auto-send leg the customer "
            "sees no payment request and no caller sees a status, so this log line is the only "
            "signal that leg produces."
        ),
    },
    {
        "event": "wa_payment_disabled_refused",
        "filterName": "wa-payment-disabled-refused",
        "metricName": "WaPaymentDisabledRefused",
        "alarmSuffix": "wa-payment-disabled-refused",
        "description": (
            "wa_payment_disabled_refused logged - WA_PAYMENTS_DISABLED is set and the kill "
            "switch is refusing in-WhatsApp payment sends. This is a legitimate administrative "
            "state, not a defect: the alarm exists so a pulled brake is visible as an event "
            "rather than as silence. Nothing was charged. If the brake was not pulled "
            "deliberately, unset the variable on the named function."
        ),
    },
]


def main() -> None:
    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    created = []

    for sig in SIGNALS:
        for fn in GATED_FUNCTIONS:
            log_group = f"/aws/lambda/{fn}"
            logs.put_metric_filter(
                logGroupName=log_group,
                filterName=f'{sig["filterName"]}-{fn}',
                filterPattern=f'"{sig["event"]}"',
                metricTransformations=[{
                    "metricName": sig["metricName"],
                    "metricNamespace": NS,
                    "metricValue": "1",
                    "defaultValue": 0.0,
                    # Dimensioned by function so one alarm per gate is possible; the metric name
                    # is shared so a future "any gate refused" view needs no second filter.
                    "dimensions": {"FunctionName": fn},
                }],
            )
            print(f'metric filter {sig["filterName"]}-{fn} set on {log_group}')

            alarm_name = f'wecare-{fn}-{sig["alarmSuffix"]}'
            cw.put_metric_alarm(
                AlarmName=alarm_name,
                AlarmDescription=f'{fn}: {sig["description"]}',
                Namespace=NS,
                MetricName=sig["metricName"],
                Dimensions=[{"Name": "FunctionName", "Value": fn}],
                Statistic="Sum",
                Period=300,
                EvaluationPeriods=1,
                # One occurrence is actionable on a money path.
                Threshold=0.0,
                ComparisonOperator="GreaterThanThreshold",
                TreatMissingData="notBreaching",
                AlarmActions=[SNS_ARN],
                OKActions=[],
            )
            created.append(alarm_name)
            print(f"alarm {alarm_name} created")

    for alarm in cw.describe_alarms(AlarmNames=created)["MetricAlarms"]:
        print(f'verify: {alarm["AlarmName"]} state={alarm["StateValue"]} '
              f'alarm_actions={len(alarm["AlarmActions"])}')


if __name__ == "__main__":
    main()
