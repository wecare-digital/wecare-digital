#!/usr/bin/env python3
"""Capture the FULL live infrastructure definition as committed, replayable JSON.

Why this exists
---------------
Recovery that depends on reading the live account is not recovery — if the account
is gone, so is the thing you were going to read. The 78 Lambda handlers' SOURCE is
already in git, and the `provision_*.py` fleet encodes how resources are created,
but the live *wiring* (API routes -> integrations -> functions, each function's
runtime config/env-var NAMES/role, each table's key schema + GSIs + TTL, the SQS
queues, EventBridge schedules) is only in the account. This exports all of that to
`docs/execution/infra-snapshot/*.json`, committed, so the recovery orchestrator
(`recover_into_account.py`) can rebuild the stack in a fresh account from git alone.

NO SECRETS. Lambda env-var VALUES are redacted to their NAMES only; Secrets Manager
is enumerated by name (ListSecrets), never read. The snapshot is safe to commit.

    python scripts/export_infrastructure_snapshot.py            # write snapshot
    python scripts/export_infrastructure_snapshot.py --summary   # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
REPO = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs/execution/infra-snapshot"
CFG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

# Secret-ish env var name fragments whose VALUE must never be captured. We only
# ever store the KEY anyway, but this flags any value that slipped through.
SECRET_HINT = ("SECRET", "TOKEN", "KEY", "PASSWORD", "PEPPER", "PRIVATE")


def c(service: str):
    return boto3.client(service, region_name=REGION, config=CFG)


def export_lambdas() -> dict:
    lam = c("lambda")
    out = {}
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            # Env var NAMES only — values redacted.
            env_keys = sorted((fn.get("Environment", {}) or {}).get("Variables", {}).keys())
            out[name] = {
                "runtime": fn.get("Runtime"),
                "handler": fn.get("Handler"),
                "memory": fn.get("MemorySize"),
                "timeout": fn.get("Timeout"),
                "role": fn.get("Role"),
                "architectures": fn.get("Architectures"),
                "layers": [l["Arn"] for l in fn.get("Layers", [])],
                "env_var_names": env_keys,
                "package_type": fn.get("PackageType"),
            }
    return out


def export_apis() -> dict:
    api = c("apigatewayv2")
    out = {}
    for a in api.get_apis()["Items"]:
        aid = a["ApiId"]
        routes, integrations = [], {}
        for r in api.get_paginator("get_routes").paginate(ApiId=aid) \
                if api.can_paginate("get_routes") else [api.get_routes(ApiId=aid)]:
            for route in r["Items"]:
                routes.append({"routeKey": route["RouteKey"],
                               "target": route.get("Target"),
                               "authorizationType": route.get("AuthorizationType")})
        for integ in api.get_integrations(ApiId=aid)["Items"]:
            integrations[integ["IntegrationId"]] = {
                "type": integ.get("IntegrationType"),
                "uri": integ.get("IntegrationUri"),
                "method": integ.get("IntegrationMethod"),
            }
        stages = [s["StageName"] for s in api.get_stages(ApiId=aid)["Items"]]
        out[aid] = {"name": a.get("Name"), "protocol": a.get("ProtocolType"),
                    "routes": routes, "integrations": integrations, "stages": stages}
    return out


def export_tables() -> dict:
    ddb = c("dynamodb")
    out = {}
    for page in ddb.get_paginator("list_tables").paginate():
        for name in page["TableNames"]:
            t = ddb.describe_table(TableName=name)["Table"]
            try:
                ttl = ddb.describe_time_to_live(TableName=name)[
                    "TimeToLiveDescription"]
            except ClientError:
                ttl = {}
            try:
                pitr = ddb.describe_continuous_backups(TableName=name)[
                    "ContinuousBackupsDescription"][
                    "PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"]
            except ClientError:
                pitr = "UNKNOWN"
            out[name] = {
                "keySchema": t.get("KeySchema"),
                "attributeDefinitions": t.get("AttributeDefinitions"),
                "billingMode": (t.get("BillingModeSummary") or {}).get("BillingMode",
                                                                       "PROVISIONED"),
                "gsis": [{"IndexName": g["IndexName"], "KeySchema": g["KeySchema"],
                          "Projection": g["Projection"]}
                         for g in t.get("GlobalSecondaryIndexes", [])],
                "ttl": {"status": ttl.get("TimeToLiveStatus"),
                        "attribute": ttl.get("AttributeName")},
                "pitr": pitr,
            }
    return out


def export_queues() -> dict:
    sqs = c("sqs")
    out = {}
    for url in sqs.list_queues().get("QueueUrls", []):
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])[
            "Attributes"]
        name = url.rsplit("/", 1)[-1]
        out[name] = {k: attrs.get(k) for k in
                     ("VisibilityTimeout", "MessageRetentionPeriod",
                      "RedrivePolicy")}
    return out


def export_schedules() -> dict:
    ev = c("events")
    out = {}
    for page in ev.get_paginator("list_rules").paginate():
        for r in page["Rules"]:
            out[r["Name"]] = {"schedule": r.get("ScheduleExpression"),
                              "state": r.get("State"),
                              "eventPattern": bool(r.get("EventPattern"))}
    return out


def export_roles() -> dict:
    iam = c("iam")
    out = {}
    for page in iam.get_paginator("list_roles").paginate():
        for r in page["Roles"]:
            if not r["RoleName"].startswith(("wecare", "amplify", "stack")):
                continue
            attached = [p["PolicyArn"] for p in
                        iam.list_attached_role_policies(RoleName=r["RoleName"])
                        .get("AttachedPolicies", [])]
            inline = iam.list_role_policies(RoleName=r["RoleName"]).get("PolicyNames", [])
            out[r["RoleName"]] = {"arn": r["Arn"],
                                  "assumeRolePolicy": r.get("AssumeRolePolicyDocument"),
                                  "attachedPolicies": attached,
                                  "inlinePolicyNames": inline}
    return out


def export_secrets_names() -> list[str]:
    sm = c("secretsmanager")
    names = []
    for page in sm.get_paginator("list_secrets").paginate():
        names += [s["Name"] for s in page.get("SecretList", [])]
    return sorted(names)


COLLECTORS = {
    "lambdas": export_lambdas,
    "apis": export_apis,
    "tables": export_tables,
    "queues": export_queues,
    "schedules": export_schedules,
    "roles": export_roles,
    "secret_names": export_secrets_names,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary", action="store_true",
                    help="print counts, write nothing")
    args = ap.parse_args()

    snapshot = {"_generated": datetime.now(timezone.utc).isoformat(),
                "_account": ACCOUNT, "_region": REGION}
    errors = []
    for key, fn in COLLECTORS.items():
        try:
            snapshot[key] = fn()
        except Exception as exc:  # noqa: BLE001 — one collector failing must not lose the rest
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
            snapshot[key] = {"_error": str(exc)}
    snapshot["_errors"] = errors

    def count(v):
        return len(v) if isinstance(v, (dict, list)) else 1
    print("infrastructure snapshot:")
    for key in COLLECTORS:
        print(f"  {key:14s} {count(snapshot.get(key))}")
    if errors:
        print(f"  ERRORS: {len(errors)}")
        for e in errors:
            print(f"    - {e}")

    # Redaction guard: ensure no env VALUE leaked (we only store names, but verify).
    blob = json.dumps(snapshot)
    assert '"Variables"' not in blob, "env var values present — redaction failed"

    if args.summary:
        print("\n(--summary: nothing written)")
        return 1 if errors else 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key in list(COLLECTORS) + ["_errors"]:
        (OUT_DIR / f"{key}.json").write_text(
            json.dumps({"_generated": snapshot["_generated"], key: snapshot[key]},
                       indent=2, default=str))
    (OUT_DIR / "snapshot.json").write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"\nwrote {OUT_DIR}/ (snapshot.json + per-section files)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
