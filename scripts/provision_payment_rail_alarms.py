"""Provision CloudWatch metric filters and alarms for the WhatsApp payment rail.

Signals are intentionally event-specific rather than generic Lambda Errors:
- deferred order status (approved template unavailable)
- uncertain order-status send (outbound invoke/function error)
- completed transition blocked after capture
- scheduled order-status retry error/query failure
- paid-invoice WhatsApp delivery failure
- Vault send/payment/runtime failures
- catalog synchronization failures
- Flow validation/health failures
- a captured payment whose order, invoice or receipt did not complete (paid state incomplete)
- a paid Vault file with no entitlement, or whose Access Vault link did not go out
- the live payment-readiness readback refusing WhatsApp payment requests
- the WhatsApp catalogs drifting from ProductsTable across two scheduled syncs

Every filter/alarm is idempotent and sends to the standard WECARE alarm topic. Several log groups
may feed one alarm: each such signal names the same metric and alarm, with its own filter.
"""
from __future__ import annotations

import argparse
import sys

import boto3

REGION = "us-east-1"
NAMESPACE = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

SIGNALS = [
    # The five order-status signals (deferred, uncertain, completed-blocked, retry-error,
    # retry-query-failed) were retired with WhatsApp order-status sends (#1650): their events
    # are no longer emitted, so their alarms could never fire. Their alarms and filters were
    # deleted on 2026-10-26; tests/test_architecture_closeout.py keeps every signal live.
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "event": "invoice_delivery_failed_claim_released",
        "filterName": "payment-invoice-delivery-failed",
        "metricName": "PaymentInvoiceDeliveryFailed",
        "alarmName": "wecare-payment-invoice-delivery-failed",
        "threshold": 0.0,
        "description": "Paid invoice WhatsApp delivery failed and its idempotency claim was released for retry.",
    },
    {
        "logGroup": "/aws/lambda/wecare-secure-files",
        "pattern": '{ $.event = "vault_offer_invoke_failed" || $.event = "payment_not_confirmed" || $.event = "secure_files_error" }',
        "filterName": "wecare-vault-operation-failure",
        "metricName": "VaultOperationFailure",
        "alarmName": "wecare-vault-operation-failure",
        "threshold": 0.0,
        "description": "Vault offer invocation, payment confirmation, or secure-files runtime failed.",
    },
    {
        "logGroup": "/aws/lambda/wecare-meta-catalog-sync",
        "pattern": '{ $.event = "meta_catalog_sync_read_failed" || $.event = "meta_catalog_batch_rejected" || $.event = "meta_catalog_sync_unconfigured" }',
        "filterName": "wecare-catalog-sync-failure",
        "metricName": "CatalogSyncFailure",
        "alarmName": "wecare-catalog-sync-failure",
        "threshold": 0.0,
        "description": "Meta catalog sync could not read, was rejected, or was unconfigured.",
    },
    {
        "logGroup": "/aws/lambda/wecare-whatsapp-business-api",
        "pattern": '{ $.event = "flow_health_blocked" || $.event = "flow_validation_error" }',
        "filterName": "wecare-flow-health-failure",
        "metricName": "FlowHealthFailure",
        "alarmName": "wecare-flow-health-failure",
        "threshold": 0.0,
        "description": "A WhatsApp Flow reported validation errors or blocked health.",
    },
    # Money moved, but the order, invoice or receipt did not complete. The webhook parks the
    # capture (CommerceKeys quarantine row) and the website callback logs the same alerts; both
    # used to be log lines with no alarm behind them.
    {
        "logGroup": "/aws/lambda/wecare-razorpay-webhook",
        # INVOICE_IMAGE_ENSURE_FAILED: the paid invoice has no customer PNG, so no receipt can go.
        "pattern": ('{ $.alert = "PAID_BUT_NO_ORDER" || $.alert = "PAID_BUT_NO_ORDER_RECORD" || '
                    '$.alert = "NEEDS_RECONCILIATION" || $.alert = "INVOICE_CREATE_FAILED" || '
                    '$.alert = "RECEIPT_DELIVERY_EXHAUSTED" || '
                    '$.alert = "INVOICE_IMAGE_ENSURE_FAILED" }'),
        "filterName": "payment-paid-state-incomplete",
        "metricName": "PaymentPaidStateIncomplete",
        "alarmName": "wecare-payment-paid-state-incomplete",
        "threshold": 0.0,
        "description": ("A captured payment has no final order, invoice or receipt. Read the alert and "
                        "referenceId on the log line; quarantined captures are listed by "
                        "scripts/reconcile_captures.py. Do not charge again."),
    },
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "pattern": '{ $.alert = "PAID_BUT_NO_ORDER" || $.alert = "PAID_BUT_NO_ORDER_RECORD" }',
        "filterName": "payment-paid-state-incomplete",
        "metricName": "PaymentPaidStateIncomplete",
        "alarmName": "wecare-payment-paid-state-incomplete",
        "threshold": 0.0,
        "description": ("A captured payment has no final order, invoice or receipt. Read the alert and "
                        "referenceId on the log line; quarantined captures are listed by "
                        "scripts/reconcile_captures.py. Do not charge again."),
    },
    {
        "logGroup": "/aws/lambda/wecare-whatsapp-business-api",
        "pattern": ('{ $.alert = "PAID_VAULT_UNFULFILLED" || $.alert = "VAULT_DELIVERY_UNSENT" || '
                    '$.alert = "VAULT_PAID_WINDOW_UNAVAILABLE" }'),
        "filterName": "vault-paid-delivery-incomplete",
        "metricName": "VaultPaidDeliveryIncomplete",
        "alarmName": "wecare-vault-paid-delivery-incomplete",
        "threshold": 0.0,
        "description": ("A paid Vault file has no entitlement, or its Access Vault link was not sent. "
                        "Reconcile the entitlement or use Send access; never request payment again."),
    },
    # The live readiness readback refused a WhatsApp payment request, so no payment request is
    # going out. Transient Meta/Razorpay outages also land here; the log line names the state.
    {
        "logGroup": "/aws/lambda/wecare-commerce",
        "pattern": '{ $.event = "wa_payment_readiness_refused" || $.event = "checkout_not_ready" }',
        "filterName": "payment-readiness-refused",
        "metricName": "PaymentReadinessRefused",
        "alarmName": "wecare-payment-readiness-refused",
        "threshold": 0.0,
        "description": ("Payment readiness refused a WhatsApp payment request; nothing was charged. Read "
                        "the readiness state on the log line before treating it as an outage."),
    },
    {
        "logGroup": "/aws/lambda/wecare-outbound-whatsapp",
        "pattern": '{ $.event = "wa_payment_readiness_refused" }',
        "filterName": "payment-readiness-refused",
        "metricName": "PaymentReadinessRefused",
        "alarmName": "wecare-payment-readiness-refused",
        "threshold": 0.0,
        "description": ("Payment readiness refused a WhatsApp payment request; nothing was charged. Read "
                        "the readiness state on the log line before treating it as an outage."),
    },
    # A scheduled sync that still finds create/update/retire work: the WhatsApp catalog shows
    # names or prices ProductsTable no longer has, and stays that way until the exact plan is
    # approved and applied. Two consecutive six-hourly runs, so a fresh product edit is not paged.
    {
        "logGroup": "/aws/lambda/wecare-meta-catalog-sync",
        "pattern": ('{ $.event = "meta_catalog_sync_planned" && $.source = "schedule" && '
                    '($.create > 0 || $.update > 0 || $.retire > 0) }'),
        "filterName": "catalog-sync-drift",
        "metricName": "CatalogSyncDrift",
        "alarmName": "wecare-catalog-sync-drift",
        "threshold": 0.0,
        "period": 21600,
        "evaluationPeriods": 2,
        "description": ("The WhatsApp catalog has differed from ProductsTable for two scheduled syncs. "
                        "Review and approve the exact plan in Catalog sync, or correct the product."),
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
            source = sig.get("event") or sig.get("pattern")
            print(f'would set {sig["alarmName"]} from {source}')
            continue

        logs.put_metric_filter(
            logGroupName=sig["logGroup"],
            filterName=sig["filterName"],
            filterPattern=sig.get("pattern") or f'"{sig["event"]}"',
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
            Period=int(sig.get("period", 300)),
            EvaluationPeriods=int(sig.get("evaluationPeriods", 1)),
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
        for a in cw.describe_alarms(
            AlarmNames=sorted({s["alarmName"] for s in SIGNALS}))["MetricAlarms"]
    }
    for sig in SIGNALS:
        f = filters_by_group[sig["logGroup"]].get(sig["filterName"])
        a = alarms.get(sig["alarmName"])
        good = (
            f is not None
            and f["filterPattern"] == (sig.get("pattern") or f'"{sig["event"]}"')
            and a is not None
            and a["MetricName"] == sig["metricName"]
            and a["Namespace"] == NAMESPACE
            and a["AlarmActions"] == [SNS_ARN]
            and a["Period"] == int(sig.get("period", 300))
            and a["EvaluationPeriods"] == int(sig.get("evaluationPeriods", 1))
        )
        print(f'verify: {sig["alarmName"]} {sig["logGroup"]} {"OK" if good else "MISMATCH"}')
        ok &= good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
