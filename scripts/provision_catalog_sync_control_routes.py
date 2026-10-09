#!/usr/bin/env python3
"""Provision the authenticated Workspace Meta catalog control routes.

The private catalog-sync Lambda remains non-HTTP. These two routes reuse the existing
whatsapp-business-api live integration, whose handler applies Cognito Admin + MFA authorization
and then invokes the private sync Lambda. No new integration, authorizer or public catalog writer
is created.

Usage:
    python scripts/provision_catalog_sync_control_routes.py
    python scripts/provision_catalog_sync_control_routes.py --apply
    python scripts/provision_catalog_sync_control_routes.py --verify
"""

from __future__ import annotations

import argparse

import boto3

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
BUSINESS_FUNCTION_ARN = (
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-business-api:live"
)
ROUTE_KEYS = (
    "GET /wa-business/catalog-sync",
    "POST /wa-business/catalog-sync",
)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def business_integration_id() -> str:
    token = None
    while True:
        params = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            params["NextToken"] = token
        page = api().get_integrations(**params)
        for item in page.get("Items", []):
            if (
                item.get("IntegrationType") == "AWS_PROXY"
                and item.get("IntegrationUri") == BUSINESS_FUNCTION_ARN
                and item.get("PayloadFormatVersion") == "2.0"
            ):
                return str(item["IntegrationId"])
        token = page.get("NextToken")
        if not token:
            break
    raise RuntimeError("live whatsapp-business-api integration not found")


def current_routes() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    token = None
    while True:
        params = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            params["NextToken"] = token
        page = api().get_routes(**params)
        for item in page.get("Items", []):
            rows[str(item.get("RouteKey") or "")] = item
        token = page.get("NextToken")
        if not token:
            break
    return rows


def apply_routes(apply: bool) -> list[str]:
    integration = business_integration_id()
    target = f"integrations/{integration}"
    routes = current_routes()
    results = []
    for key in ROUTE_KEYS:
        existing = routes.get(key)
        if existing:
            if existing.get("Target") != target:
                raise RuntimeError(
                    f"{key} already targets {existing.get('Target')}, refusing to retarget"
                )
            results.append(f"{key}: exists")
            continue
        if not apply:
            results.append(f"{key}: would create -> {target}")
            continue
        api().create_route(
            ApiId=API_ID,
            RouteKey=key,
            Target=target,
            AuthorizationType="NONE",
            ApiKeyRequired=False,
        )
        results.append(f"{key}: created -> {target}")
    return results


def verify() -> int:
    integration = business_integration_id()
    expected = f"integrations/{integration}"
    routes = current_routes()
    problems = []
    for key in ROUTE_KEYS:
        row = routes.get(key)
        if not row:
            problems.append(f"missing {key}")
            continue
        if row.get("Target") != expected:
            problems.append(f"{key} targets {row.get('Target')} not {expected}")
    print(f"integration: {integration} -> {BUSINESS_FUNCTION_ARN}")
    for key in ROUTE_KEYS:
        row = routes.get(key) or {}
        print(f"{key}: {row.get('Target', 'MISSING')}")
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}")
        return 1
    print("catalog control routes verified; authorization remains application Admin + MFA")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        return verify()
    for line in apply_routes(args.apply):
        print(line)
    if args.apply:
        return verify()
    print("dry run: nothing changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
