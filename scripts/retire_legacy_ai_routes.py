#!/usr/bin/env python3
"""Retire the three legacy /ai routes and their dedicated Lambda, after UI deploy.

This script defaults to a read-only plan. Execute against production only AFTER
the matching web release has removed FloatingAgent, Inbox AI suggestions and
the old Staff Agent. Preserves logs, payment records and the separate /ai/agent
and /ai/query integrations. Does not delete data tables or shared IAM roles.

Usage:
  python scripts/retire_legacy_ai_routes.py
  python scripts/retire_legacy_ai_routes.py --apply
"""
from __future__ import annotations

import argparse
import json

import boto3

REGION = "us-east-1"
API_NAME = "wecare-digital-api"
FUNCTION = "wecare-ai-generate-response"
LEGACY_ROUTES = {
    "POST /ai/generate",
    "POST /ai/approvals",
    "POST /ai/approvals/status",
}


def pages(client, operation: str, result_key: str, **kwargs):
    result = []
    token = None
    while True:
        args = dict(kwargs)
        if token:
            args["NextToken"] = token
        answer = getattr(client, operation)(**args)
        result.extend(answer.get(result_key, []))
        token = answer.get("NextToken")
        if not token:
            return result


def plan():
    apigw = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    matches = []
    other_refs = []
    for api in pages(apigw, "get_apis", "Items"):
        aid = api["ApiId"]
        integrations = {i["IntegrationId"]: i for i in
                        pages(apigw, "get_integrations", "Items", ApiId=aid)}
        for route in pages(apigw, "get_routes", "Items", ApiId=aid):
            target = (route.get("Target") or "").split("/")[-1]
            uri = integrations.get(target, {}).get("IntegrationUri", "")
            points_to_old_ai = "function:" + FUNCTION in uri
            row = {"api": api.get("Name"), "apiId": aid,
                   "route": route["RouteKey"], "routeId": route["RouteId"],
                   "integrationId": target}
            if api.get("Name") == API_NAME and route["RouteKey"] in LEGACY_ROUTES:
                if not points_to_old_ai:
                    raise RuntimeError("Legacy route target changed; refuse cleanup: "
                                       + row["route"])
                matches.append(row)
            elif points_to_old_ai:
                other_refs.append(row)

    names = {row["route"] for row in matches}
    if names != LEGACY_ROUTES:
        raise RuntimeError("Legacy route inventory mismatch: " + repr(names))
    if other_refs:
        raise RuntimeError("Legacy Lambda is still used by other routes: " +
                           repr(other_refs))

    qualified = lam.get_function_configuration(FunctionName=FUNCTION)
    source_mappings = pages(lam, "list_event_source_mappings",
                            "EventSourceMappings", FunctionName=FUNCTION)
    if source_mappings:
        raise RuntimeError("Legacy Lambda has event-source mappings; inspect manually.")
    return apigw, lam, matches, {
        "function": FUNCTION,
        "functionVersion": qualified.get("Version"),
        "routes": matches,
        "eventSourceMappings": 0,
        "otherApiRoutes": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Delete the three routes and the old Lambda.")
    args = parser.parse_args()

    apigw, lam, routes, audit = plan()
    print(json.dumps({"mode": "APPLY" if args.apply else "DRY_RUN",
                      **audit}, indent=2))
    if not args.apply:
        return

    # Deletion order: keep Lambda alive until no public API route can invoke it.
    for row in routes:
        apigw.delete_route(ApiId=row["apiId"], RouteId=row["routeId"])
        print("Deleted route:", row["route"])
    # The dedicated function has no event mappings or other API users; its
    # historical CloudWatch log group is deliberately retained for audit.
    lam.delete_function(FunctionName=FUNCTION)
    print("Deleted function:", FUNCTION)
    print("Retained: /ai/agent, /ai/query, WhatsApp templates, payment Lambda fleet")


if __name__ == "__main__":
    main()
