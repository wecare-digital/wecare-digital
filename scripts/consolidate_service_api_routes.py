#!/usr/bin/env python3
"""Move /wa-business service-domain routes to the canonical wecare-service-api Lambda.

Dry-run by default. This script does not delete the old whatsapp-business-api integration,
so rollback is one route-target change away.

Safety gates:
- canonical service-api live alias must exist and serve current code
- every selected route must currently target either whatsapp-business-api or service-api
- target integration is AWS_PROXY payload 2.0
- all route updates are verified by readback

Usage:
    python scripts/consolidate_service_api_routes.py
    python scripts/consolidate_service_api_routes.py --apply
"""
from __future__ import annotations

import argparse
import json
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = "775261844268"
API_ID = "zllr9lrg7j"
OLD_FUNCTION = "wecare-whatsapp-business-api"
NEW_FUNCTION = "wecare-service-api"
SERVICE_TERMS = (
    "/orders",
    "/service/",
    "/documents",
    "/faq",
    "/appointments",
    "/rx-slots",
    "/enterprise-assist",
    "/reviews",
)


def _function_name(uri: str) -> str:
    marker = ":function:"
    if marker not in str(uri):
        return ""
    return str(uri).split(marker, 1)[1].split(":", 1)[0]


def _selected(route_key: str) -> bool:
    return "/wa-business/" in route_key and any(term in route_key for term in SERVICE_TERMS)


def _ensure_permission(lam) -> None:
    statement_id = "apigw-service-api-live"
    source_arn = f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{API_ID}/*/*"
    try:
        lam.add_permission(
            FunctionName=NEW_FUNCTION,
            Qualifier="live",
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceConflictException":
            raise


def _target_integration(api, alias_arn: str) -> str:
    integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
    candidates = [
        row for row in integrations
        if _function_name(row.get("IntegrationUri", "")) == NEW_FUNCTION
        and str(row.get("IntegrationUri") or "").endswith(":live")
    ]
    if candidates:
        target = sorted(candidates, key=lambda row: row["IntegrationId"])[0]
    else:
        target = api.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=alias_arn,
            PayloadFormatVersion="2.0",
            TimeoutInMillis=30000,
            Description="Canonical service domain API",
        )
    if target.get("IntegrationType") != "AWS_PROXY" or target.get("PayloadFormatVersion") != "2.0":
        raise RuntimeError("canonical service-api integration shape is unexpected")
    return target["IntegrationId"]


def plan(api, target_id: str):
    routes = api.get_routes(ApiId=API_ID, MaxResults="500").get("Items", [])
    integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
    by_id = {row["IntegrationId"]: row for row in integrations}
    changes = []
    state = []
    for route in routes:
        route_key = str(route.get("RouteKey") or "")
        if not _selected(route_key):
            continue
        current_id = str(route.get("Target") or "").rsplit("/", 1)[-1]
        current_owner = _function_name((by_id.get(current_id) or {}).get("IntegrationUri", ""))
        if current_owner not in (OLD_FUNCTION, NEW_FUNCTION):
            raise RuntimeError(f"{route_key}: unexpected integration owner {current_owner!r}")
        state.append((route_key, current_owner, current_id))
        if current_owner == OLD_FUNCTION:
            changes.append({
                "routeKey": route_key,
                "routeId": route["RouteId"],
                "fromIntegration": current_id,
                "toIntegration": target_id,
            })
    return changes, state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)

    alias = lam.get_alias(FunctionName=NEW_FUNCTION, Name="live")
    served = lam.get_function_configuration(
        FunctionName=NEW_FUNCTION, Qualifier=alias["FunctionVersion"])
    latest = lam.get_function_configuration(FunctionName=NEW_FUNCTION)
    if served["CodeSha256"] != latest["CodeSha256"]:
        raise RuntimeError("service-api live alias does not serve current deployed code")

    if args.apply:
        _ensure_permission(lam)

    target_id = _target_integration(api, alias["AliasArn"]) if args.apply else ""
    if not target_id:
        integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
        existing = [
            row for row in integrations
            if _function_name(row.get("IntegrationUri", "")) == NEW_FUNCTION
            and str(row.get("IntegrationUri") or "").endswith(":live")
        ]
        if existing:
            target_id = sorted(existing, key=lambda row: row["IntegrationId"])[0]["IntegrationId"]
        else:
            target_id = "<create-on-apply>"

    changes, state = plan(api, target_id)
    for route_key, owner, integration_id in sorted(state):
        print(f"{route_key}: {owner} ({integration_id})")
    if not args.apply:
        print(f"dry-run: {len(changes)} route(s) would move")
        return 0

    for row in changes:
        api.update_route(
            ApiId=API_ID,
            RouteId=row["routeId"],
            Target="integrations/" + row["toIntegration"],
        )

    remaining, readback = plan(api, target_id)
    if remaining:
        raise RuntimeError("service route migration incomplete: " + json.dumps(remaining))
    wrong = [row for row in readback if row[1] != NEW_FUNCTION]
    if wrong:
        raise RuntimeError("service route readback mismatch: " + json.dumps(wrong))
    print(f"applied: {len(changes)} route(s) moved to {NEW_FUNCTION}:live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
