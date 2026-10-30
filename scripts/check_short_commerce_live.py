#!/usr/bin/env python3
"""Read-only Short Commerce production configuration audit.

No payment, customer or catalog data is read. No AWS resource is mutated.
Return 0 only if expected account, three deployed live receivers, their
explicit one-unit flags, and existing payment alarm states are all healthy.
This alone does NOT attest the deployed package or replace E2E payment tests.
"""
from __future__ import annotations

import argparse
import json
import sys
import boto3
from botocore.exceptions import BotoCoreError, ClientError

RECEIVERS = ("wecare-commerce", "wecare-checkout", "wecare-inbound-whatsapp")
FLAG = "SHORT_COMMERCE_PART1_ENABLED"


def live_snapshot(session, *, region: str) -> dict:
    sts = session.client("sts", region_name=region)
    functions = session.client("lambda", region_name=region)
    watch = session.client("cloudwatch", region_name=region)
    account = sts.get_caller_identity()["Account"]

    receivers = []
    for name in RECEIVERS:
        try:
            response = functions.get_function_configuration(
                FunctionName=name, Qualifier="live")
        except functions.exceptions.ResourceNotFoundException:
            receivers.append({"name": name, "found": False, "flag": False})
            continue
        value = response.get("Environment", {}).get("Variables", {}).get(FLAG, "")
        receivers.append({
            "name": name,
            "found": True,
            "state": response.get("State"),
            "last_update_status": response.get("LastUpdateStatus"),
            "published_version": response.get("Version"),
            "code_sha256": response.get("CodeSha256"),
            "flag": str(value).strip().lower() in ("true", "1", "yes", "on"),
        })

    alarms = []
    pages = watch.get_paginator("describe_alarms").paginate(
        AlarmNamePrefix="wecare-payment")
    for page in pages:
        for alarm in page.get("MetricAlarms", []):
            alarms.append({"name": alarm.get("AlarmName"),
                           "state": alarm.get("StateValue")})
    config_ok = all(row.get("found") and row.get("state") == "Active"
                    and row.get("flag") for row in receivers)
    alarms_ok = bool(alarms) and all(a["state"] == "OK" for a in alarms)
    return {"account": account, "region": region, "receivers": receivers,
            "payment_alarms": alarms, "config_ok": config_ok,
            "alarms_ok": alarms_ok}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--expect-account", required=True)
    args = parser.parse_args()
    try:
        snapshot = live_snapshot(boto3.Session(), region=args.region)
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}),
              file=sys.stderr)
        return 2
    ok = (snapshot["account"] == args.expect_account
          and snapshot["config_ok"] and snapshot["alarms_ok"])
    print(json.dumps({"ok": ok, **snapshot}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
