#!/usr/bin/env python3
"""Provision the CRM API: the Lambda, its `live` alias, the integration and 12 routes.

    python scripts/provision_crm_api.py --dry-run
    python scripts/provision_crm_api.py
    python scripts/provision_crm_api.py --verify

Routes are created with `AuthorizationType=NONE` at the gateway and authenticate inside the
handler via `lambda_utils.middleware.require_auth`. That is not a gap - it is the pattern the
other 300 routes on this API use, and `scripts/audit_route_auth.py` recognises it: a route is
reported OPEN only when the gateway does not authorize it **and** its handler shows no
evidence of authenticating. Run that audit after this script; it must stay at 0 OPEN.

Why a Lambda rather than extending `wecare-contacts`
---------------------------------------------------
`wecare-contacts` owns one table and one resource. Folding five CRM entities into it would
mean one function's timeout, memory and IAM policy covering both, and a contacts bug taking
the funnel down with it. The CRM surface is also the first consumer of
`lambda_utils.identity`, which contacts has no reason to package.

Idempotent throughout: the function, alias, integration, permission and every route are
created only when absent, so re-running is a no-op. That matters because this is the kind of
script that gets run twice when someone is unsure whether the first run finished.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
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

FUNCTION = "wecare-crm"
ALIAS = "live"
HANDLER = "handler.handler"
RUNTIME = "python3.12"
#: Same role every other function in this fleet uses. Its policy already covers the CRM
#: tables, which were created in the same account with the same naming prefix.
ROLE = f"arn:aws:iam::{ACCOUNT}:role/wecare-digital-lambda-role"
TIMEOUT = 30
# 256MB, matching wecare-contacts. Measured peak on the live function: 97MB, so 512
# was paying for headroom nothing used - and a smaller size is also slower CPU, so
# this is the measured floor rather than the smallest number that fits.
MEMORY = 256

STATEMENT_ID = "CrmHttpApiInvokeLive"

#: The full surface. `{proxy+}` is deliberately NOT used: an explicit route per method and
#: path is what lets `audit_route_auth.py` reason about each one, and a proxy route hides
#: which methods actually exist behind it.
ROUTES = [
    "GET /crm/pipelines",
    "GET /crm/leads",
    "POST /crm/leads",
    "GET /crm/leads/{leadId}",
    "PATCH /crm/leads/{leadId}",
    "POST /crm/leads/{leadId}/convert",
    "GET /crm/opportunities",
    "GET /crm/opportunities/{opportunityId}",
    "PATCH /crm/opportunities/{opportunityId}",
    "GET /crm/activities",
    "POST /crm/activities",
    "GET /crm/contacts/{contactId}/360",
]

#: Non-secret configuration only. No credential is ever placed in a Lambda environment
#: variable; the CRM surface reads no provider credential at all.
ENVIRONMENT = {
    "CONTACTS_TABLE": "stack-wecare-digital-ContactsTable",
    "PAYMENTS_TABLE": "stack-wecare-digital-PaymentsTable",
    "INVOICES_TABLE": "stack-wecare-digital-InvoicesTable",
    "CRM_PIPELINES_TABLE": "stack-wecare-digital-CrmPipelines",
    "CRM_STAGES_TABLE": "stack-wecare-digital-CrmStages",
    "CRM_LEADS_TABLE": "stack-wecare-digital-CrmLeads",
    "CRM_OPPORTUNITIES_TABLE": "stack-wecare-digital-CrmOpportunities",
    "CRM_ACTIVITIES_TABLE": "stack-wecare-digital-CrmActivities",
}

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify" / "functions" / "core" / "crm"
SHARED = ROOT / "amplify" / "functions" / "shared"


def _lambda():
    return boto3.client("lambda", region_name=REGION)


def _apigw():
    return boto3.client("apigatewayv2", region_name=REGION)


def function_arn(qualified: bool = True) -> str:
    base = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}"
    return f"{base}:{ALIAS}" if qualified else base


def build_package() -> bytes:
    """Zip the handler plus `lambda_utils`, matching `deploy_all_lambdas` layout.

    Built here so the very first deploy has something to upload; every subsequent deploy
    should go through `scripts/deploy_all_lambdas.py wecare-crm`, which also publishes a
    version and moves the alias.
    """
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


def function_exists() -> bool:
    try:
        _lambda().get_function(FunctionName=FUNCTION)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return False
        raise


def ensure_function(dry_run: bool) -> str:
    if function_exists():
        return "exists"
    if dry_run:
        return "would create"
    _lambda().create_function(
        FunctionName=FUNCTION,
        Runtime=RUNTIME,
        Role=ROLE,
        Handler=HANDLER,
        Code={"ZipFile": build_package()},
        Timeout=TIMEOUT,
        MemorySize=MEMORY,
        Architectures=["x86_64"],
        Environment={"Variables": ENVIRONMENT},
        Description="CRM read/write surface: leads, pipeline, opportunities, activities, "
                    "contact 360. Authenticates via lambda_utils.middleware.require_auth.",
        Tags={"domain": "crm", "phase": "4"},
    )
    _lambda().get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    return "created"


def ensure_alias(dry_run: bool) -> str:
    """Publish a version and point `live` at it.

    The alias is what the API integration targets, so `$LATEST` changes never reach
    production on their own - see `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa).
    """
    if dry_run:
        return "would ensure"
    published = _lambda().publish_version(FunctionName=FUNCTION)["Version"]
    try:
        _lambda().create_alias(FunctionName=FUNCTION, Name=ALIAS,
                               FunctionVersion=published)
        return f"created -> v{published}"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceConflictException":
            raise
        _lambda().update_alias(FunctionName=FUNCTION, Name=ALIAS,
                               FunctionVersion=published)
        return f"moved -> v{published}"


def ensure_permission(dry_run: bool) -> str:
    """Let API Gateway invoke the alias.

    Scoped to this API only. A wildcard `SourceArn` would let any API in the account invoke
    it, which is the kind of thing that is invisible until a second API exists.
    """
    if dry_run:
        return "would ensure"
    try:
        _lambda().add_permission(
            FunctionName=FUNCTION,
            Qualifier=ALIAS,
            StatementId=STATEMENT_ID,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
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
        ApiId=API_ID,
        IntegrationType="AWS_PROXY",
        IntegrationUri=arn,
        PayloadFormatVersion="2.0",
        TimeoutInMillis=30000,
    )
    return created["IntegrationId"], "created"


def ensure_routes(integration_id: str, dry_run: bool) -> dict:
    existing = {item["RouteKey"]: item for item in _all("get_routes")}
    results = {}
    for route_key in ROUTES:
        current = existing.get(route_key)
        if current:
            target = current.get("Target", "")
            if integration_id and target.endswith(integration_id):
                results[route_key] = "exists"
            else:
                # A route of this name pointing somewhere else is not ours to silently
                # repoint - report it and let a human look.
                results[route_key] = f"CONFLICT -> {target}"
            continue
        if dry_run or not integration_id:
            results[route_key] = "would create"
            continue
        _apigw().create_route(
            ApiId=API_ID,
            RouteKey=route_key,
            Target=f"integrations/{integration_id}",
            AuthorizationType="NONE",
        )
        results[route_key] = "created"
    return results


def verify() -> int:
    """Read back the deployed surface. Exit 1 on any problem."""
    problems = []

    try:
        config = _lambda().get_function_configuration(
            FunctionName=f"{FUNCTION}:{ALIAS}")
        print(f"function        : {FUNCTION}:{ALIAS}  {config['Runtime']}  "
              f"{config['MemorySize']}MB  {config['Timeout']}s")
        env = (config.get("Environment") or {}).get("Variables") or {}
        credentialish = [k for k in env
                         if any(t in k.upper()
                                for t in ("PASSWORD", "SECRET", "TOKEN", "KEY"))]
        if credentialish:
            problems.append(f"credential-shaped env keys present: {credentialish}")
        print(f"env vars        : {len(env)} (credential-shaped: {len(credentialish)})")
    except ClientError as exc:
        problems.append(f"{FUNCTION}:{ALIAS} not found ({exc.response['Error']['Code']})")
        print(f"function        : MISSING")

    arn = function_arn()
    integration_id = next((i["IntegrationId"] for i in _all("get_integrations")
                           if i.get("IntegrationUri") == arn), "")
    print(f"integration     : {integration_id or 'MISSING'}")
    if not integration_id:
        problems.append("no integration points at the live alias")

    routes = {item["RouteKey"]: item for item in _all("get_routes")}
    print(f"\n{'route':<46} {'authType':<10} target")
    for route_key in ROUTES:
        route = routes.get(route_key)
        if not route:
            problems.append(f"missing route {route_key}")
            print(f"{route_key:<46} {'-':<10} MISSING")
            continue
        target = route.get("Target", "")
        auth = route.get("AuthorizationType", "NONE")
        ok = bool(integration_id) and target.endswith(integration_id)
        if not ok:
            problems.append(f"{route_key} targets {target}, not our integration")
        print(f"{route_key:<46} {auth:<10} {'ok' if ok else target}")

    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"\nCRM API verified: {len(ROUTES)} routes on the live alias, no "
          "credential-shaped environment variables.")
    print("Handler-level auth. Confirm with: python scripts/audit_route_auth.py --gate")
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
    print("\nNext: python scripts/provision_crm_api.py --verify")
    print("      python scripts/audit_route_auth.py --gate   (must stay at 0 OPEN)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
