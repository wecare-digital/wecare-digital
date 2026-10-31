#!/usr/bin/env python3
"""Per-function Lambda error alarms, for the functions that carry real traffic.

The gap this closes
-------------------
Measured 2026-09-28: the account had 41 alarms, none in `ALARM`, none in
`INSUFFICIENT_DATA`, every one with an action - and **56 of 66 Lambda functions had no
alarm at all**. The 41 covered 10 functions plus the DynamoDB tables, the API stage, the
DLQs and a cert.

The uncovered set was not the idle tail. It included:

    wecare-seo-tools              392,447 invocations in 7 days, the hottest in the fleet
    wecare-site-language           54,110  second hottest, on every public pageview
    wecare-messages-read            1,790
    wecare-contacts                 1,785
    wecare-rcs-dlr                  1,253
    wecare-whatsapp-calling         1,121
    wecare-customer-whatsapp-auth      58  and ACTUALLY FAILING - 1 error in 58, an
                                           "internal WhatsApp sender returned HTTP 400"
                                           on the customer OTP path

So the one function known to be failing a customer-facing flow was the one nobody would
be told about. `wecare-lambda-throttles` already provides an account-wide throttle net,
but there was no equivalent for errors: a function could fail every invocation and the
review would still come back green.

Why discovered rather than a hardcoded list
-------------------------------------------
A checked-in list of "important functions" is wrong the week after it is written - the
fleet went 58 -> 65 -> 66 in a month. This reads CloudWatch for 7-day invocation counts
and alarms anything above a floor, so a function that becomes busy acquires an alarm the
next time this runs, without anyone remembering to add it.

`ALWAYS` is the exception list, and it exists because volume is the wrong test for some
things. `wecare-customer-whatsapp-auth` runs 58 times a week; every one of those is
somebody trying to sign in. A money or identity path deserves an alarm at any volume.

Cost, stated because it is a real trade
---------------------------------------
CloudWatch charges about $0.10 per alarm per month. Covering all 66 functions with
errors-plus-duration would be ~130 alarms, ~$13/month, most of it watching functions that
run twice a week. The floor plus `ALWAYS` lands around 25 new alarms, ~$2.50/month, and
the account-wide net below catches anything the floor excludes. WAF was removed as an
$18/month cost decision, so spending is not free here and the number matters.

What it creates
---------------
    wecare-lambda-errors-<fn>      per function: Errors Sum > 0 over 5 min
    wecare-lambda-duration-<fn>    only where a function runs close to its timeout
    wecare-lambda-errors-any       ONE account-wide net, no FunctionName dimension

The account-wide net is the important cheap one: it cannot tell you WHICH function broke,
but it means a function below the floor cannot fail silently forever. It complements the
existing `wecare-lambda-throttles`, which is the same idea for throttling.

    python scripts/provision_lambda_alarms.py            # report only, no writes
    python scripts/provision_lambda_alarms.py --apply
    python scripts/provision_lambda_alarms.py --verify

Exit codes: 0 coverage is complete, 1 drift remains.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
ALARM_TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:wecare-alarm-notifications"

# The topic whose only subscription is a CONFIRMED email to the owner. Deliberately not
# `stack-wecare-digital`: provision_alarm_coverage.py found that 33 of 41 alarms published
# only there, and its sole subscriber is the wecare-inbound-whatsapp Lambda - a message
# handler that now silently SKIPS those deliveries. Alarms were firing into a void.

# 7-day invocation floor for an automatic alarm. 50 is about 7 a day: below that a
# function is either scheduled-and-quiet or genuinely unused, and the account-wide net
# covers it.
INVOCATION_FLOOR = int(50)

# Alarmed at ANY volume, because the cost of a silent failure is not proportional to
# traffic. Each entry needs a reason.
ALWAYS = {
    "wecare-customer-whatsapp-auth": "customer sign-in; every invocation is a real person",
    "wecare-razorpay-webhook": "payment confirmation; a missed webhook is an unpaid order",
    "wecare-commerce": "canonical Pay Flow collection, invoice issuance, and paid-order finalisation",
    "wecare-payments-read": "staff reconciliation ledger; an error hides the payment state needed for safe retries",
    "wecare-customer-invoice": "paid-customer invoice download; an error strands the statutory document",
    "wecare-outbound-whatsapp": "payment request and paid-invoice messaging; send errors must reach an operator",
    "wecare-secure-files": "paid file delivery; a failure is a customer who paid and got nothing",
    "wecare-mcp": "public unauthenticated endpoint; nothing else would report it failing",
    "wecare-cognito-custom-message": "sends the sign-in email; failing it locks people out",
    "wecare-notification-worker": "SQS-driven, so a failure shows up as silence",
    "wecare-outbound-email": "low volume by design; failure is invisible without this",
    "wecare-outbound-sms": "low volume by design; failure is invisible without this",
    # The commerce payment->order->customer path. Alarmed at ANY volume on purpose:
    # customer-profile in particular ran zero times in the audited 24h window, so a
    # volume-floor rule would never cover the exact function whose silence is hardest to
    # notice - a failed account link that quietly hides a customer's orders.
    "wecare-checkout": "website checkout; a failure is a customer who cannot pay",
    "wecare-customer-orders": "website order history; a failure hides a paid customer's orders",
    "wecare-customer-profile": "website account link; a failure silently detaches orders from the account",
    "wecare-invoice-engine": "invoice + payment-link + fulfilment; a failure is an uncollected or unshipped order",
}

# Never alarmed, with the reason, so an absence is a decision on the record.
NEVER = {
    "wecare-get-miss-redirect": "Lambda@Edge - executes in the edge region, so a "
                                "us-east-1 FunctionName alarm would watch nothing",
}

# A function running this close to its EFFECTIVE ceiling gets a duration alarm as well.
# 0.5 is not arbitrary: a function at half its ceiling under normal load has no headroom
# for a slow upstream, which is exactly how wecare-seo-tools reached 30,499ms and returned
# a bodiless 503 on the build's critical path.
DURATION_HEADROOM = 0.5

# THE LAMBDA TIMEOUT IS NOT THE CEILING FOR AN HTTP-BACKED FUNCTION, and using it was
# wrong in the first version of this script. API Gateway cuts a Lambda integration off at
# 30 seconds regardless of what the function's own timeout says.
#
# wecare-seo-tools is configured with a 120s timeout, so "peak 30,499ms of 120,000ms" reads
# as 25% utilisation and comfortably healthy. It is not: 30,499ms is PAST the gateway's
# limit, and the access log records that request as `30001ms status=503`. Measuring against
# 120s would have declared the exact function this gap was raised about to be fine.
APIGW_INTEGRATION_CEILING_MS = 30_000

ERROR_SPEC = dict(
    MetricName="Errors", Namespace="AWS/Lambda", Statistic="Sum",
    Period=300, EvaluationPeriods=1, Threshold=0.0,
    ComparisonOperator="GreaterThanThreshold",
    # notBreaching, not missing: a function with no invocations in a period has no
    # datapoint, and treating that as breaching would make every quiet function alarm
    # overnight. This is the same choice provision_alarm_coverage.py made for the DLQs.
    TreatMissingData="notBreaching",
)


def _tag(name: str) -> str:
    return f"wecare-lambda-errors-{name}"


def _dur_tag(name: str) -> str:
    return f"wecare-lambda-duration-{name}"


def discover(lam, cw, http_backed: set) -> tuple[dict, dict, list]:
    """Return (functions to alarm -> reason, functions needing a duration alarm, skipped)."""
    functions = []
    for page in lam.get_paginator("list_functions").paginate():
        functions += page["Functions"]
    config = {f["FunctionName"]: f for f in functions}

    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=7)
    queries, index = [], {}
    for i, name in enumerate(sorted(config)):
        for metric, stat in (("Invocations", "Sum"), ("Duration", "Maximum")):
            qid = f"q{len(queries)}"
            index[qid] = (name, metric)
            queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {"Namespace": "AWS/Lambda", "MetricName": metric,
                               "Dimensions": [{"Name": "FunctionName", "Value": name}]},
                    "Period": 604800, "Stat": stat,
                },
            })

    measured: dict = {}
    for i in range(0, len(queries), 500):
        result = cw.get_metric_data(MetricDataQueries=queries[i:i + 500],
                                    StartTime=start, EndTime=now)
        for row in result["MetricDataResults"]:
            name, metric = index[row["Id"]]
            measured.setdefault(name, {})[metric] = sum(row.get("Values") or [])

    wanted, duration, skipped = {}, {}, []
    for name in sorted(config):
        if name in NEVER:
            skipped.append(f"{name}: {NEVER[name]}")
            continue
        invocations = measured.get(name, {}).get("Invocations", 0)
        if name in ALWAYS:
            wanted[name] = ALWAYS[name]
        elif invocations >= INVOCATION_FLOOR:
            wanted[name] = f"{int(invocations)} invocations in 7 days"
        else:
            skipped.append(f"{name}: {int(invocations)} invocations, below the floor "
                           f"of {INVOCATION_FLOOR}")
            continue
        timeout_ms = (config[name].get("Timeout") or 3) * 1000
        # The lower of the two limits is the one that actually terminates the request.
        ceiling_ms = min(timeout_ms, APIGW_INTEGRATION_CEILING_MS) \
            if name in http_backed else timeout_ms
        peak = measured.get(name, {}).get("Duration", 0)
        if peak and peak > ceiling_ms * DURATION_HEADROOM:
            duration[name] = (int(peak), int(ceiling_ms), name in http_backed)
    return wanted, duration, skipped


def existing_coverage(cw) -> tuple[set, set, set]:
    """Return (alarm names, functions with an Errors alarm, functions with a Duration alarm).

    COVERAGE IS MATCHED BY DIMENSION, NOT BY ALARM NAME, and the first version of this
    script got that wrong in a way that would have been invisible. Two functions are
    already covered under names that predate the `wecare-lambda-errors-<fn>` convention:

        wecare-inbound-lambda-errors   -> FunctionName wecare-inbound-whatsapp
        wecare-outbound-lambda-errors  -> FunctionName wecare-outbound-whatsapp

    A name-based check reported both as uncovered and would have created a second alarm on
    the same metric. Two alarms on one metric is not twice the safety - it is two emails
    per incident, which is how an operator learns to filter the whole topic.
    """
    names, errors, durations = set(), set(), set()
    for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["MetricAlarm"]):
        for alarm in page["MetricAlarms"]:
            names.add(alarm["AlarmName"])
            if alarm.get("Namespace") != "AWS/Lambda":
                continue
            target = next((d["Value"] for d in alarm.get("Dimensions") or []
                           if d["Name"] == "FunctionName"), None)
            if not target:
                continue
            if alarm.get("MetricName") == "Errors":
                errors.add(target)
            elif alarm.get("MetricName") == "Duration":
                durations.add(target)
    return names, errors, durations


def http_backed_functions(api) -> set:
    """Functions reachable through the HTTP API, so subject to its 30s integration ceiling."""
    import re
    out = set()
    token = None
    while True:
        kwargs = {"ApiId": "zllr9lrg7j", "MaxResults": "500"}
        if token:
            kwargs["NextToken"] = token
        page = api.get_integrations(**kwargs)
        for item in page.get("Items", []):
            match = re.search(r":function:([A-Za-z0-9\-_]+)", item.get("IntegrationUri") or "")
            if match:
                out.add(match.group(1))
        token = page.get("NextToken")
        if not token:
            return out


def put_error_alarm(cw, name: str, reason: str) -> None:
    cw.put_metric_alarm(
        AlarmName=_tag(name),
        AlarmDescription=f"{name} returned an error. Selected because: {reason}",
        Dimensions=[{"Name": "FunctionName", "Value": name}],
        AlarmActions=[ALARM_TOPIC], OKActions=[ALARM_TOPIC],
        **ERROR_SPEC,
    )


def put_duration_alarm(cw, name: str, peak_ms: int, ceiling_ms: int, http: bool) -> None:
    # Threshold at 80% of the EFFECTIVE ceiling. Firing at the ceiling itself would only
    # tell you what the Errors alarm already did; the point is to hear about it while
    # there is still headroom to act.
    threshold = ceiling_ms * 0.8
    limit = ("the API Gateway 30s integration ceiling" if http and ceiling_ms == APIGW_INTEGRATION_CEILING_MS
             else "its configured Lambda timeout")
    cw.put_metric_alarm(
        AlarmName=_dur_tag(name),
        AlarmDescription=(f"{name} is running close to {limit} ({ceiling_ms}ms; peak "
                          f"{peak_ms}ms in the last 7 days). A function with no headroom "
                          f"fails on any upstream slowdown, and past the gateway ceiling "
                          f"the caller gets a 503 with no body."),
        MetricName="Duration", Namespace="AWS/Lambda", Statistic="Maximum",
        Dimensions=[{"Name": "FunctionName", "Value": name}],
        Period=300, EvaluationPeriods=1, Threshold=threshold,
        ComparisonOperator="GreaterThanThreshold", TreatMissingData="notBreaching",
        AlarmActions=[ALARM_TOPIC], OKActions=[ALARM_TOPIC],
    )


def put_account_net(cw) -> None:
    """One alarm, no FunctionName dimension: any Lambda error anywhere in the account.

    It cannot say WHICH function broke, and that is fine - it exists so that a function
    below the invocation floor cannot fail silently forever. The threshold is above zero
    rather than at it because the fleet has a nonzero background error rate across 66
    functions, and an alarm that cries wolf gets muted, which is worse than no alarm.
    """
    cw.put_metric_alarm(
        AlarmName="wecare-lambda-errors-any",
        AlarmDescription=("Lambda errors across the whole account. The safety net for "
                          "functions below the per-function alarm floor - it does not "
                          "identify the function, so check CloudWatch by invocation."),
        MetricName="Errors", Namespace="AWS/Lambda", Statistic="Sum",
        Period=300, EvaluationPeriods=2, Threshold=5.0,
        ComparisonOperator="GreaterThanThreshold", TreatMissingData="notBreaching",
        AlarmActions=[ALARM_TOPIC], OKActions=[ALARM_TOPIC],
    )


def assert_topic_reaches_a_human(sns) -> None:
    """Refuse to create alarms that nobody receives.

    This is the exact defect provision_alarm_coverage.py was written for: 33 alarms
    publishing only to a topic whose single subscriber was a Lambda that discarded the
    message. Creating 25 more alarms into a void would look like progress and be none.
    """
    subs = sns.list_subscriptions_by_topic(TopicArn=ALARM_TOPIC).get("Subscriptions", [])
    human = [s for s in subs
             if s.get("Protocol") in ("email", "email-json", "sms")
             and not str(s.get("SubscriptionArn", "")).endswith("PendingConfirmation")]
    if not human:
        raise SystemExit(
            f"{ALARM_TOPIC} has no CONFIRMED human subscriber "
            f"({len(subs)} subscription(s) total). Alarms would fire into a void.\n"
            "Fix with scripts/provision_alarm_coverage.py --apply, then re-run."
        )
    print(f"  topic reaches a human: {len(human)} confirmed "
          f"{', '.join(sorted({s['Protocol'] for s in human}))} subscription(s)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="create the missing alarms")
    ap.add_argument("--verify", action="store_true", help="check coverage, change nothing")
    args = ap.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    sns = boto3.client("sns", region_name=REGION)

    print("=" * 78)
    print("LAMBDA ALARM COVERAGE")
    print("=" * 78)
    assert_topic_reaches_a_human(sns)

    api = boto3.client("apigatewayv2", region_name=REGION)
    http_backed = http_backed_functions(api)
    wanted, duration, skipped = discover(lam, cw, http_backed)
    have, covered_errors, covered_duration = existing_coverage(cw)

    missing_errors = {n: r for n, r in wanted.items() if n not in covered_errors}
    missing_duration = {n: v for n, v in duration.items() if n not in covered_duration}
    net_missing = "wecare-lambda-errors-any" not in have

    print(f"\n  functions considered        : {len(wanted) + len(skipped)}")
    print(f"  selected for an alarm       : {len(wanted)}")
    print(f"  already covered             : {len(wanted) - len(missing_errors)}")
    print(f"  MISSING error alarm         : {len(missing_errors)}")
    print(f"  MISSING duration alarm      : {len(missing_duration)}")
    print(f"  account-wide net            : {'MISSING' if net_missing else 'present'}")

    if missing_errors:
        print("\n  would create error alarms for:")
        for name, reason in sorted(missing_errors.items()):
            print(f"    {name:38s} {reason}")
    if missing_duration:
        print("\n  would create duration alarms for (running close to the effective ceiling):")
        for name, (peak, ceiling, http) in sorted(missing_duration.items()):
            why = "API Gateway ceiling" if http and ceiling == APIGW_INTEGRATION_CEILING_MS \
                else "Lambda timeout"
            print(f"    {name:38s} peak {peak}ms of {ceiling}ms ({why})")
    if skipped:
        print(f"\n  not alarmed ({len(skipped)}):")
        for line in skipped:
            print(f"    {line}")

    outstanding = len(missing_errors) + len(missing_duration) + (1 if net_missing else 0)

    if args.verify:
        print("\n" + "=" * 78)
        print("RESULT: " + ("PASS - coverage complete" if not outstanding
                            else f"FAIL - {outstanding} alarm(s) missing"))
        print("=" * 78)
        return 1 if outstanding else 0

    if not args.apply:
        new = len(missing_errors) + len(missing_duration) + (1 if net_missing else 0)
        print(f"\n  DRY RUN - nothing written. {new} alarm(s) would be created, "
              f"about ${new * 0.10:.2f}/month.")
        print("  Re-run with --apply.")
        return 0

    created = 0
    for name, reason in sorted(missing_errors.items()):
        try:
            put_error_alarm(cw, name, reason)
            print(f"  created {_tag(name)}")
            created += 1
        except ClientError as exc:
            print(f"  FAILED {_tag(name)}: {exc.response['Error']['Code']}")
    for name, (peak, ceiling, http) in sorted(missing_duration.items()):
        try:
            put_duration_alarm(cw, name, peak, ceiling, http)
            print(f"  created {_dur_tag(name)}")
            created += 1
        except ClientError as exc:
            print(f"  FAILED {_dur_tag(name)}: {exc.response['Error']['Code']}")
    if net_missing:
        put_account_net(cw)
        print("  created wecare-lambda-errors-any")
        created += 1

    print(f"\n  created {created} alarm(s), about ${created * 0.10:.2f}/month")
    print("\n" + "=" * 78)
    print("Verify: python scripts/provision_lambda_alarms.py --verify")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
