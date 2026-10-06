"""
Metric filters + alarms for the two Direct Send failure modes.

Why these two events are alarm-worthy, when the whole feature ships OFF
---------------------------------------------------------------------
Neither event can fire while `DIRECT_SEND_ENABLED_WABAS` is empty, so today both
alarms sit in OK with no data. They exist *before* the flag is ever switched on,
and that ordering is the point:

* `direct_send_restricted` (Meta 139200 / 131064) means Meta's
  category-misclassification enforcement has restricted or capped Direct Send for
  a WABA. The enforcement ladder escalates **on a timer** - warning, then rate
  limiting, then a 7-day restriction, then 30 days, then permanent revocation.
  An unmonitored first strike is precisely how an account reaches the 7-day rung,
  because nothing in the send path fails loudly: the message falls back to the
  existing 403 and the customer-facing behaviour is unchanged. The damage is
  silent and cumulative, which is the shape of problem an alarm is for.

* `direct_send_not_onboarded` (Meta 100 with Direct-Send-category details) means
  the flag names a WABA Meta has not onboarded. Not dangerous - every send falls
  back to today's refusal - but it means the flag is lying, and the operator who
  set it believes a feature is on that is not.

Threshold is deliberately 1, not a rate. Both events are rare by construction and
each one is individually actionable; averaging them would hide the first.

`TreatMissingData='notBreaching'` because no data is the expected steady state
while the flag is empty, and an alarm that sits in INSUFFICIENT_DATA forever is an
alarm people learn to ignore.

Follows the convention of scripts/_create_dedup_alarm.py: created via boto3 because
ampx cannot run in the agent environment. Every put_* is an upsert, so this script
is idempotent and safe to re-run.

Cost: metric filters are free; two alarms at roughly $0.10/month each.
"""
import boto3

REGION = "us-east-1"
NS = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

# Both senders. outbound-whatsapp is where the production fallback logs these;
# whatsapp-business-api is the admin surface that can hit the same Meta errors.
LOG_GROUPS = [
    "/aws/lambda/wecare-outbound-whatsapp",
    "/aws/lambda/wecare-whatsapp-business-api",
]

SIGNALS = [
    {
        "event": "direct_send_restricted",
        "filterName": "direct-send-restricted",
        "metricName": "DirectSendRestricted",
        "alarmName": "wecare-direct-send-restricted",
        "description": (
            "direct_send_restricted logged (Meta 139200/131064) - Direct Send access "
            "restricted or capped by category-misclassification enforcement. The "
            "enforcement ladder escalates on a timer and ends in permanent "
            "revocation, so investigate the flagged auto-generated template now. "
            "Sends are NOT dropped: they fall back to the existing outside-window 403."
        ),
    },
    {
        "event": "direct_send_not_onboarded",
        "filterName": "direct-send-not-onboarded",
        "metricName": "DirectSendNotOnboarded",
        "alarmName": "wecare-direct-send-not-onboarded",
        "description": (
            "direct_send_not_onboarded logged (Meta 100 with Direct-Send-category "
            "details) - DIRECT_SEND_ENABLED_WABAS names a WABA Meta has not "
            "onboarded. Harmless to customers (every send falls back to the existing "
            "403) but the flag is misconfigured: clear that WABA id, or complete "
            "onboarding in WhatsApp Manager."
        ),
    },
]


def main() -> None:
    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)

    for sig in SIGNALS:
        for lg in LOG_GROUPS:
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
            # One occurrence is actionable. Both events are rare by construction.
            Threshold=0.0,
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            AlarmActions=[SNS_ARN],
            OKActions=[],
        )
        print(f'alarm {sig["alarmName"]} created')

    names = [s["alarmName"] for s in SIGNALS]
    for a in cw.describe_alarms(AlarmNames=names)["MetricAlarms"]:
        print(f'verify: {a["AlarmName"]} state={a["StateValue"]} '
              f'alarm_actions={len(a["AlarmActions"])}')


if __name__ == "__main__":
    main()
