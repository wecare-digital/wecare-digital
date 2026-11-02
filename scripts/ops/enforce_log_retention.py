#!/usr/bin/env python3
"""Apply retention only to groups missing it (dry-run unless --apply).

Use only with a scoped IAM role. Existing longer/shorter explicit policies are preserved. No log groups, logs or filters are deleted.
"""
import argparse
import json
import sys
import boto3

REGION = "us-east-1"
LONGER = ("auth", "cognito", "payment", "razorpay", "checkout", "invoice", "billing", "secure-files")
MEDIUM = ("whatsapp", "waba", "message", "notification", "sms", "rcs")

def days(name):
    lower = name.lower()
    if lower.startswith("/aws/apigateway/") or any(x in lower for x in LONGER):
        return 14
    if any(x in lower for x in MEDIUM):
        return 7
    return 3

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-account", required=True)
    args = parser.parse_args()
    session = boto3.Session(region_name=REGION)
    if session.client("sts").get_caller_identity()["Account"] != args.expected_account:
        parser.error("AWS account mismatch. No changes made.")
    client = session.client("logs")
    changes = []
    for page in client.get_paginator("describe_log_groups").paginate():
        for group in page["logGroups"]:
            name = group["logGroupName"]
            if name.startswith("aws-waf-logs-") or "cloudtrail" in name.lower() or "audit" in name.lower():
                continue  # Security logs require a separate retention policy.
            required = days(name)
            if group.get("retentionInDays") is None:
                changes.append({"name": name, "current": group.get("retentionInDays"), "desired": required})
    if args.apply:
        for item in changes:
            client.put_retention_policy(logGroupName=item["name"], retentionInDays=item["desired"])
    print(json.dumps({"applied": args.apply, "changes": changes}, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
