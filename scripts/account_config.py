#!/usr/bin/env python3
"""Account/region/API/SNS/KMS resolution so provisioners work in ANY account.

Why this exists
---------------
The `provision_*.py` fleet was written for production and hardcodes the account id
`775261844268`, the HTTP API id `zllr9lrg7j`, and the SNS alarm topic ARN. A replay
into a fresh account therefore builds a PARTIAL, broken stack (IAM/KMS policies name
a foreign account, routes target a non-existent API, alarms publish to a topic in
another account). This module centralises those values so a script asks the helper
instead of baking in a prod constant — and the helper resolves them from the LIVE
caller plus optional environment overrides.

Resolution order for each value:
  1. an explicit environment override (so a migration/recovery run can pin them), else
  2. the live account's own value (account id from STS; API id discovered by name;
     SNS topic built from the live account id), else
  3. the production default (so existing prod runs behave exactly as before).

This keeps production behaviour identical (defaults = today's values) while making a
build in `991322955408` or any recovery account correct instead of prod-pinned.

    import account_config as cfg
    acct = cfg.account_id()           # live account, never a hardcoded guess
    api  = cfg.http_api_id()          # discovered by name in the live account
    topic= cfg.alarm_topic_arn()      # built from the live account id
"""
from __future__ import annotations

import functools
import os

import boto3

REGION = os.environ.get("WECARE_REGION", "us-east-1")

# Production reference values — used ONLY as a last-resort default, never to
# override what the live account actually is.
PROD_ACCOUNT = "775261844268"
PROD_API_ID = "zllr9lrg7j"
API_NAME = "wecare-digital-api"
ALARM_TOPIC_NAME = os.environ.get("WECARE_ALARM_TOPIC", "wecare-alarm-notifications")


@functools.lru_cache(maxsize=1)
def account_id() -> str:
    """The account these credentials belong to. Override: WECARE_ACCOUNT_ID."""
    override = os.environ.get("WECARE_ACCOUNT_ID")
    if override:
        return override
    try:
        return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    except Exception:  # noqa: BLE001 — offline/no creds: fall back to prod default
        return PROD_ACCOUNT


def region() -> str:
    return REGION


@functools.lru_cache(maxsize=1)
def http_api_id() -> str:
    """The HTTP API id in the LIVE account.

    Override: WECARE_HTTP_API_ID. Otherwise discovered by the API's name in this
    account (so a fresh account's freshly-created API is found by name, not by the
    prod id). Falls back to the prod id only if discovery finds nothing AND we are
    in the prod account.
    """
    override = os.environ.get("WECARE_HTTP_API_ID")
    if override:
        return override
    try:
        api = boto3.client("apigatewayv2", region_name=REGION)
        for item in api.get_apis().get("Items", []):
            if item.get("Name") == API_NAME:
                return item["ApiId"]
    except Exception:  # noqa: BLE001
        pass
    # Nothing discovered. Only hand back the prod id if we actually are prod,
    # so a recovery account does not silently target prod's API.
    return PROD_API_ID if account_id() == PROD_ACCOUNT else ""


def alarm_topic_arn() -> str:
    """SNS alarm topic ARN, built from the LIVE account id (never a foreign one).

    Override: WECARE_ALARM_TOPIC_ARN.
    """
    override = os.environ.get("WECARE_ALARM_TOPIC_ARN")
    if override:
        return override
    return f"arn:aws:sns:{REGION}:{account_id()}:{ALARM_TOPIC_NAME}"


def is_production() -> bool:
    return account_id() == PROD_ACCOUNT


def summary() -> dict:
    return {
        "region": REGION,
        "account_id": account_id(),
        "is_production": is_production(),
        "http_api_id": http_api_id() or "(none in this account)",
        "alarm_topic_arn": alarm_topic_arn(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
