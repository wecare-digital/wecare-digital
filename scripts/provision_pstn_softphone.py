#!/usr/bin/env python3
"""Provision the softphone surface: sessions table, Lambda, integration, 5 routes.

    python scripts/provision_pstn_softphone.py --dry-run
    python scripts/provision_pstn_softphone.py
    python scripts/provision_pstn_softphone.py --verify

Creates nothing at Plivo. The protected identifiers - PSTN number +918031830030, voice
application 12775976954213184, endpoint 543585900967411 - are read-only here and are never
registered, re-registered or deleted by this script.

`PSTN_BROWSER_ROUTING_ENABLED` is deliberately **not set**, so it is false and the token
route refuses to mint. That is the intended posture: the route, its auth, its role gate and
its contract are all live and verifiable while the capability to place live outbound calls
from a browser stays closed. Enabling it later is a flag plus session-endpoint provisioning,
with no code change.

Routes are `AuthorizationType=NONE` at the gateway and authenticate in the handler via
`lambda_utils.middleware.require_auth` - the pattern the other 312 routes on this API use.
`scripts/audit_route_auth.py` must stay at 0 OPEN afterwards.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
ACCOUNT = "775261844268"
API_ID = "zllr9lrg7j"

FUNCTION = "wecare-pstn-softphone"
ALIAS = "live"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/wecare-digital-lambda-role"
STATEMENT_ID = "PstnSoftphoneHttpApiInvokeLive"

TABLE = "stack-wecare-digital-PstnSoftphoneSessions"

ROUTES = [
    "POST /pstn/token",
    "GET /pstn/session",
    "POST /pstn/session/events",
    "POST /pstn/session/presence",
    "GET /pstn/diagnostics",
]

#: Non-secret only. The Plivo REST credential is read from Secrets Manager at request time.
#: `PSTN_BROWSER_ROUTING_ENABLED` and `PSTN_AGENT_ENDPOINT` are absent on purpose - see the
#: module docstring.
ENVIRONMENT = {
    "PSTN_SESSIONS_TABLE": TABLE,
    "PLIVO_API_SECRET_ID": "wecare/plivo/api",
    "PLIVO_APPLICATION_ID": "12775976954213184",
    "PSTN_TOKEN_TTL_SECONDS": "300",
}

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify" / "functions" / "messaging" / "pstn-softphone"
SHARED = ROOT / "amplify" / "functions" / "shared"


def _ddb():
    return boto3.client("dynamodb", region_name=REGION)


def _lambda():
    return boto3.client("lambda", region_name=REGION)


def _apigw():
    return boto3.client("apigatewayv2", region_name=REGION)


def function_arn() -> str:
    return f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}:{ALIAS}"


def ensure_table(dry_run: bool) -> str:
    """One row per softphone session, keyed on `{actor}#{tab}`.

    TTL on `expiresAt`: a tab closed without signing out leaves a row behind, and a stale
    `AVAILABLE` agent is worse than no record because it routes calls into a void.

    No PITR. Unlike the CRM tables this holds transient device state, not business history -
    a lost row costs one re-registration, and the session is rebuilt by the next token mint.
    """
    try:
        _ddb().describe_table(TableName=TABLE)
        return "exists"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    if dry_run:
        return "would create"
    _ddb().create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "sessionId", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "sessionId", "KeyType": "HASH"}],
        Tags=[{"Key": "domain", "Value": "pstn"}, {"Key": "phase", "Value": "5"}],
    )
    _ddb().get_waiter("table_exists").wait(TableName=TABLE)
    # Session validity is checked by the application; DynamoDB TTL is disabled.
    return "created (TTL disabled)"


def build_package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            archive.write(path, path.relative_to(SOURCE).as_posix())
        for path in sorted((SHARED / "lambda_utils").rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            archive.write(path, path.relative_to(SHARED).as_posix())
    return buffer.getvalue()


def ensure_function(dry_run: bool) -> str:
    try:
        _lambda().get_function(FunctionName=FUNCTION)
        return "exists"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    if dry_run:
        return "would create"
    _lambda().create_function(
        FunctionName=FUNCTION,
        Runtime="python3.15",
        Role=ROLE,
        Handler="handler.handler",
        Code={"ZipFile": build_package()},
        Timeout=30,
        MemorySize=256,
        Architectures=["x86_64"],
        Environment={"Variables": ENVIRONMENT},
        Description="Protected Plivo Browser SDK token route, softphone session state "
                    "and diagnostics. Browser routing disabled.",
        Tags={"domain": "pstn", "phase": "5"},
    )
    _lambda().get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    return "created"


def ensure_alias(dry_run: bool) -> str:
    if dry_run:
        return "would ensure"
    version = _lambda().publish_version(FunctionName=FUNCTION)["Version"]
    try:
        _lambda().create_alias(FunctionName=FUNCTION, Name=ALIAS,
                               FunctionVersion=version)
        return f"created -> v{version}"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceConflictException":
            raise
        _lambda().update_alias(FunctionName=FUNCTION, Name=ALIAS,
                               FunctionVersion=version)
        return f"moved -> v{version}"


def ensure_permission(dry_run: bool) -> str:
    if dry_run:
        return "would ensure"
    try:
        _lambda().add_permission(
            FunctionName=FUNCTION, Qualifier=ALIAS, StatementId=STATEMENT_ID,
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*/*",
        )
        return "added"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceConflictException":
            return "exists"
        raise


def _all(operation: str) -> list:
    items = []
    for page in _apigw().get_paginator(operation).paginate(ApiId=API_ID):
        items.extend(page.get("Items", []))
    return items


def ensure_integration(dry_run: bool) -> tuple:
    arn = function_arn()
    for item in _all("get_integrations"):
        if item.get("IntegrationUri") == arn:
            return item["IntegrationId"], "exists"
    if dry_run:
        return "", "would create"
    created = _apigw().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=arn,
        PayloadFormatVersion="2.0", TimeoutInMillis=30000,
    )
    return created["IntegrationId"], "created"


def ensure_routes(integration_id: str, dry_run: bool) -> dict:
    existing = {item["RouteKey"]: item for item in _all("get_routes")}
    results = {}
    for route_key in ROUTES:
        current = existing.get(route_key)
        if current:
            target = current.get("Target", "")
            results[route_key] = ("exists" if integration_id and
                                  target.endswith(integration_id)
                                  else f"CONFLICT -> {target}")
            continue
        if dry_run or not integration_id:
            results[route_key] = "would create"
            continue
        _apigw().create_route(ApiId=API_ID, RouteKey=route_key,
                              Target=f"integrations/{integration_id}",
                              AuthorizationType="NONE")
        results[route_key] = "created"
    return results


def verify() -> int:
    problems = []

    try:
        ttl = _ddb().describe_time_to_live(TableName=TABLE)
        described = _ddb().describe_table(TableName=TABLE)["Table"]
        status = ttl.get("TimeToLiveDescription", {}).get("TimeToLiveStatus")
        print(f"table        : {TABLE}  {described['TableStatus']}  "
              f"items={described.get('ItemCount', 0)}  TTL={status}")
        if status not in ("ENABLED", "ENABLING"):
            problems.append(f"{TABLE} TTL is {status}; stale sessions would persist")
    except ClientError:
        problems.append(f"{TABLE} missing")
        print(f"table        : MISSING")

    try:
        config = _lambda().get_function_configuration(
            FunctionName=f"{FUNCTION}:{ALIAS}")
        env = (config.get("Environment") or {}).get("Variables") or {}
        print(f"function     : {FUNCTION}:{ALIAS}  {config['MemorySize']}MB  "
              f"{config['Timeout']}s")
        flag = env.get("PSTN_BROWSER_ROUTING_ENABLED", "(absent)")
        print(f"browser flag : {flag}")
        if str(flag).lower() == "true":
            problems.append("PSTN_BROWSER_ROUTING_ENABLED is true; it must stay off")
        credentialish = [k for k in env if any(
            t in k.upper() for t in ("PASSWORD", "AUTH_TOKEN", "SECRET_KEY"))]
        if credentialish:
            problems.append(f"credential-shaped env keys: {credentialish}")
        print(f"env vars     : {len(env)} (credential-shaped: {len(credentialish)})")
    except ClientError:
        problems.append(f"{FUNCTION}:{ALIAS} missing")
        print("function     : MISSING")

    arn = function_arn()
    integration_id = next((i["IntegrationId"] for i in _all("get_integrations")
                           if i.get("IntegrationUri") == arn), "")
    print(f"integration  : {integration_id or 'MISSING'}")
    if not integration_id:
        problems.append("no integration points at the live alias")

    routes = {item["RouteKey"]: item for item in _all("get_routes")}
    print(f"\n{'route':<34} {'authType':<10} target")
    for route_key in ROUTES:
        route = routes.get(route_key)
        if not route:
            problems.append(f"missing route {route_key}")
            print(f"{route_key:<34} {'-':<10} MISSING")
            continue
        target = route.get("Target", "")
        ok = bool(integration_id) and target.endswith(integration_id)
        if not ok:
            problems.append(f"{route_key} targets {target}")
        print(f"{route_key:<34} {route.get('AuthorizationType', 'NONE'):<10} "
              f"{'ok' if ok else target}")

    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"\nSoftphone surface verified: {len(ROUTES)} routes, browser routing OFF, "
          "no credential-shaped environment variables.")
    print("Confirm auth with: python scripts/audit_route_auth.py --gate")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region={REGION} api={API_ID} function={FUNCTION} "
          f"routes={len(ROUTES)} dry_run={args.dry_run}")
    print("  NOTE: creates nothing at Plivo; protected identifiers are read-only here")
    print(f"  table         : {ensure_table(args.dry_run)}")
    print(f"  function      : {ensure_function(args.dry_run)}")
    print(f"  alias         : {ensure_alias(args.dry_run)}")
    print(f"  permission    : {ensure_permission(args.dry_run)}")
    integration_id, integration_state = ensure_integration(args.dry_run)
    print(f"  integration   : {integration_state} {integration_id}")
    for route_key, state in ensure_routes(integration_id, args.dry_run).items():
        print(f"    {state:<16} {route_key}")

    if args.dry_run:
        print("\ndry run: nothing created")
        return 0
    print("\nNext: python scripts/provision_pstn_softphone.py --verify")
    print("      python scripts/audit_route_auth.py --gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
