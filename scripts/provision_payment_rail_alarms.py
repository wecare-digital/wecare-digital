"""Provision CloudWatch metric filters and alarms for the WhatsApp payment rail.

Signals are intentionally event-specific rather than generic Lambda Errors:
- deferred order status (approved template unavailable)
- uncertain order-status send (outbound invoke/function error)
- completed transition blocked after capture
- scheduled order-status retry error/query failure
- paid-invoice WhatsApp delivery failure

Every filter/alarm is idempotent and sends to the standard WECARE alarm topic.
"""
from __future__ import annotations

import argparse
import sys

import boto3

REGION = "us-east-1"
NAMESPACE = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

SIGNALS = [
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "event": "order_status_deferred",
        "filterName": "payment-order-status-deferred",
        "metricName": "PaymentOrderStatusDeferred",
        "alarmName": "wecare-payment-order-status-deferred",
        "threshold": 0.0,
        "description": "Approved WhatsApp ORDER_STATUS template unavailable; payment order update was deferred.",
    },
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "event": "order_status_outbound_function_error",
        "filterName": "payment-order-status-uncertain",
        "metricName": "PaymentOrderStatusUncertain",
        "alarmName": "wecare-payment-order-status-uncertain",
        "threshold": 0.0,
        "description": "Payment order-status outbound Lambda failed after invocation; Meta delivery is uncertain.",
    },
    {
        "logGroup": "/aws/lambda/wecare-razorpay-webhook",
        "event": "order_status_completed_blocked",
        "filterName": "payment-order-completed-blocked",
        "metricName": "PaymentOrderCompletedBlocked",
        "alarmName": "wecare-payment-order-completed-blocked",
        "threshold": 0.0,
        "description": "Payment capture could not advance from processing to completed.",
    },
    {
        "logGroup": "/aws/lambda/wecare-razorpay-webhook",
        "event": "order_status_retry_error",
        "filterName": "payment-order-status-retry-error",
        "metricName": "PaymentOrderStatusRetryError",
        "alarmName": "wecare-payment-order-status-retry-error",
        "threshold": 0.0,
        "description": "Scheduled retry of a deferred payment order-status update failed.",
    },
    {
        "logGroup": "/aws/lambda/wecare-razorpay-webhook",
        "event": "order_status_retry_query_failed",
        "filterName": "payment-order-status-retry-query-failed",
        "metricName": "PaymentOrderStatusRetryQueryFailed",
        "alarmName": "wecare-payment-order-status-retry-query-failed",
        "threshold": 0.0,
        "description": "Payment order-status retry index could not be queried.",
    },
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "event": "invoice_delivery_failed_claim_released",
        "filterName": "payment-invoice-delivery-failed",
        "metricName": "PaymentInvoiceDeliveryFailed",
        "alarmName": "wecare-payment-invoice-delivery-failed",
        "threshold": 0.0,
        "description": "Paid invoice WhatsApp delivery failed and its idempotency claim was released for retry.",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)

    existing_groups = {
        g["logGroupName"]
        for page in logs.get_paginator("describe_log_groups").paginate()
        for g in page["logGroups"]
    }

    ok = True
    for sig in SIGNALS:
        if sig["logGroup"] not in existing_groups:
            print(f'missing log group: {sig["logGroup"]}')
            ok = False
            continue
        if not args.apply:
            print(f'would set {sig["alarmName"]} from {sig["event"]}')
            continue

        logs.put_metric_filter(
            logGroupName=sig["logGroup"],
            filterName=sig["filterName"],
            filterPattern=f'"{sig["event"]}"',
            metricTransformations=[{
                "metricName": sig["metricName"],
                "metricNamespace": NAMESPACE,
                "metricValue": "1",
                "defaultValue": 0.0,
            }],
        )
        cw.put_metric_alarm(
            AlarmName=sig["alarmName"],
            AlarmDescription=sig["description"],
            Namespace=NAMESPACE,
            MetricName=sig["metricName"],
            Statistic="Sum",
            Period=300,
            EvaluationPeriods=1,
            Threshold=sig["threshold"],
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            AlarmActions=[SNS_ARN],
            OKActions=[],
        )

    if not args.apply:
        print("dry run: nothing written")
        return 0 if ok else 1

    filters_by_group = {}
    for sig in SIGNALS:
        if sig["logGroup"] not in filters_by_group:
            filters_by_group[sig["logGroup"]] = {
                f["filterName"]: f
                for f in logs.describe_metric_filters(logGroupName=sig["logGroup"])["metricFilters"]
            }
    alarms = {
        a["AlarmName"]: a
        for a in cw.describe_alarms(AlarmNames=[s["alarmName"] for s in SIGNALS])["MetricAlarms"]
    }
    for sig in SIGNALS:
        f = filters_by_group[sig["logGroup"]].get(sig["filterName"])
        a = alarms.get(sig["alarmName"])
        good = (
            f is not None
            and f["filterPattern"] == f'"{sig["event"]}"'
            and a is not None
            and a["MetricName"] == sig["metricName"]
            and a["Namespace"] == NAMESPACE
            and a["AlarmActions"] == [SNS_ARN]
        )
        print(f'verify: {sig["alarmName"]} {"OK" if good else "MISMATCH"}')
        ok &= good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
