#!/usr/bin/env python3
"""Retire the legacy WhatsApp templates Lambda after route cutover.

Dry-run by default.  This is deliberately separate from route migration so the old Lambda remains
an immediate rollback target until every /whatsapp/templates* route has been read back on the
canonical template-management integration.

Usage:
    python scripts/retire_whatsapp_templates_lambda.py
    python scripts/retire_whatsapp_templates_lambda.py --apply
"""
from __future__ import annotations

import argparse
import boto3

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
OLD_FUNCTION = "wecare-whatsapp-templates"


def _owner(uri: str) -> str:
    marker = ":function:"
    if marker not in str(uri):
        return ""
    return str(uri).split(marker, 1)[1].split(":", 1)[0]


def blockers(lam, api) -> list[str]:
    problems: list[str] = []

    routes = api.get_routes(ApiId=API_ID, MaxResults="500").get("Items", [])
    integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
    by_id = {row["IntegrationId"]: row for row in integrations}
    for route in routes:
        iid = str(route.get("Target") or "").rsplit("/", 1)[-1]
        integ = by_id.get(iid) or {}
        if _owner(integ.get("IntegrationUri", "")) == OLD_FUNCTION:
            problems.append("API route still targets legacy Lambda: " + str(route.get("RouteKey")))

    mappings = lam.list_event_source_mappings(FunctionName=OLD_FUNCTION).get("EventSourceMappings", [])
    for mapping in mappings:
        problems.append("event source mapping remains: " + str(mapping.get("UUID") or "unknown"))

    try:
        url = lam.get_function_url_config(FunctionName=OLD_FUNCTION)
        if url.get("FunctionUrl"):
            problems.append("function URL remains: " + str(url["FunctionUrl"]))
    except lam.exceptions.ResourceNotFoundException:
        pass

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)

    try:
        fn = lam.get_function(FunctionName=OLD_FUNCTION)
    except lam.exceptions.ResourceNotFoundException:
        print(f"{OLD_FUNCTION}: already absent")
        return 0

    problems = blockers(lam, api)
    if problems:
        for problem in problems:
            print("BLOCKED:", problem)
        raise SystemExit("legacy template Lambda is still reachable")

    version = (fn.get("Configuration") or {}).get("Version")
    print(f"{OLD_FUNCTION}: no live API/event-source/function-URL references; version={version}")
    if not args.apply:
        print("dry-run: function would be deleted")
        return 0

    lam.delete_function(FunctionName=OLD_FUNCTION)
    try:
        lam.get_function(FunctionName=OLD_FUNCTION)
    except lam.exceptions.ResourceNotFoundException:
        print(f"deleted: {OLD_FUNCTION}")
        return 0
    raise RuntimeError("delete returned but function still exists")


if __name__ == "__main__":
    raise SystemExit(main())
