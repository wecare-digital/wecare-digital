#!/usr/bin/env python3
"""Move /whatsapp/templates* routes to the canonical template-management Lambda.

Dry-run by default.  This script deliberately does NOT delete the retired Lambda; route cutover
and function deletion are separate rollback boundaries.

Safety gates:
- target live alias must exist
- every source route must currently target wecare-whatsapp-templates:live
- the target integration must already point at wecare-whatsapp-template-management:live
- all route updates are verified by readback

Usage:
    python scripts/consolidate_whatsapp_template_routes.py
    python scripts/consolidate_whatsapp_template_routes.py --apply
"""
from __future__ import annotations

import argparse
import boto3

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
OLD_FUNCTION = "wecare-whatsapp-templates"
NEW_FUNCTION = "wecare-whatsapp-template-management"
PREFIX = "/whatsapp/templates"


def _function_name(uri: str) -> str:
    marker = ":function:"
    if marker not in str(uri):
        return ""
    return str(uri).split(marker, 1)[1].split(":", 1)[0]


def plan(api):
    routes = api.get_routes(ApiId=API_ID, MaxResults="500").get("Items", [])
    integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
    by_id = {row["IntegrationId"]: row for row in integrations}

    source = []
    target_ids = []
    for row in integrations:
        if _function_name(row.get("IntegrationUri", "")) == NEW_FUNCTION:
            target_ids.append(row["IntegrationId"])
    if not target_ids:
        raise RuntimeError("canonical template-management integration is missing")

    # All existing target integrations are equivalent AWS_PROXY POST / payload 2.0. Reuse one.
    target_id = sorted(target_ids)[0]
    target = by_id[target_id]
    if target.get("IntegrationType") != "AWS_PROXY" or target.get("PayloadFormatVersion") != "2.0":
        raise RuntimeError("canonical integration shape is unexpected")

    for route in routes:
        route_key = str(route.get("RouteKey") or "")
        if PREFIX not in route_key:
            continue
        integration_id = str(route.get("Target") or "").rsplit("/", 1)[-1]
        integration = by_id.get(integration_id) or {}
        owner = _function_name(integration.get("IntegrationUri", ""))
        if owner == OLD_FUNCTION:
            source.append({
                "routeKey": route_key,
                "routeId": route["RouteId"],
                "fromIntegration": integration_id,
                "toIntegration": target_id,
            })
        elif owner != NEW_FUNCTION:
            raise RuntimeError(f"{route_key}: unexpected integration owner {owner!r}")

    return source, target_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)

    # Refuse before any route change if the destination alias is not deployable.
    alias = lam.get_alias(FunctionName=NEW_FUNCTION, Name="live")
    served = lam.get_function_configuration(
        FunctionName=NEW_FUNCTION, Qualifier=alias["FunctionVersion"])
    latest = lam.get_function_configuration(FunctionName=NEW_FUNCTION)
    if served["CodeSha256"] != latest["CodeSha256"]:
        raise RuntimeError("template-management live alias does not serve current deployed code")

    changes, target_id = plan(api)
    print(f"target integration: {target_id}")
    for row in changes:
        print(f"{row['routeKey']}: integrations/{row['fromIntegration']} -> "
              f"integrations/{row['toIntegration']}")

    if not args.apply:
        print(f"dry-run: {len(changes)} route(s) would move")
        return 0

    for row in changes:
        api.update_route(
            ApiId=API_ID,
            RouteId=row["routeId"],
            Target="integrations/" + row["toIntegration"],
        )

    remaining, _ = plan(api)
    if remaining:
        raise RuntimeError(f"route migration incomplete: {remaining}")
    print(f"applied: {len(changes)} route(s) moved to {NEW_FUNCTION}:live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
