#!/usr/bin/env python3
"""Converge the invoice order-status API route used by PayFlow.

Usage:
    python scripts/provision_invoice_order_status_route.py
    python scripts/provision_invoice_order_status_route.py --apply
    python scripts/provision_invoice_order_status_route.py --verify
"""
from __future__ import annotations

import argparse
import boto3

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
ROUTE_KEY = "POST /invoices/{invoiceId}/order-status"
INTEGRATION_URI = (
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-invoice-engine:live"
)


def _items(client, op):
    items = []
    for page in client.get_paginator(op).paginate(ApiId=API_ID):
        items.extend(page.get("Items", []))
    return items


def _integration_id(api):
    for row in _items(api, "get_integrations"):
        if row.get("IntegrationUri") == INTEGRATION_URI:
            return row["IntegrationId"]
    return ""


def _route(api):
    for row in _items(api, "get_routes"):
        if row.get("RouteKey") == ROUTE_KEY:
            return row
    return None


def verify() -> int:
    api = boto3.client("apigatewayv2", region_name=REGION)
    row = _route(api)
    if not row:
        print(f"FAIL missing {ROUTE_KEY}")
        return 1
    iid = _integration_id(api)
    expected = f"integrations/{iid}" if iid else ""
    if not expected or row.get("Target") != expected:
        print(f"FAIL {ROUTE_KEY} targets {row.get('Target')}, expected {expected or 'invoice live integration'}")
        return 1
    print(f"PASS {ROUTE_KEY} -> {expected}")
    return 0


def apply() -> int:
    api = boto3.client("apigatewayv2", region_name=REGION)
    if _route(api):
        print("route already exists")
        return verify()
    iid = _integration_id(api)
    if not iid:
        print("FAIL invoice-engine:live integration not found")
        return 1
    made = api.create_route(
        ApiId=API_ID,
        RouteKey=ROUTE_KEY,
        Target=f"integrations/{iid}",
        AuthorizationType="NONE",
        ApiKeyRequired=False,
    )
    print(f"created {ROUTE_KEY} routeId={made['RouteId']}")
    return verify()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    if args.apply:
        return apply()
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
