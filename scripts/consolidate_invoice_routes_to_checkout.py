#!/usr/bin/env python3
"""Move /invoices* API routes from invoice-engine to the staged checkout commerce runtime.

Dry-run by default. The script refuses unless:
- checkout:live exists and its deployed ZIP contains invoice_engine.py plus exact renderer assets;
- checkout:live has the Pillow dependency layer;
- the checkout role has the exact CheckoutInvoiceAuthority policy;
- every invoice route currently targets either invoice-engine or checkout;
- the checkout integration is AWS_PROXY payload 2.0.

Route migration and invoice-engine deletion are deliberately separate rollback boundaries.
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
import zipfile

import boto3

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
PREFIX = "/invoices"
OLD_FUNCTION = "wecare-invoice-engine"
NEW_FUNCTION = "wecare-checkout"
NEW_ROLE = "wecare-checkout-role"
POLICY_NAME = "CheckoutInvoiceAuthority"
STAGE = "prod"
PILLOW_LAYER_ARN = "arn:aws:lambda:us-east-1:775261844268:layer:pillow-python312:2"
REQUIRED_SIDS = {
    "InvoiceRecords",
    "InvoicePaymentEvidence",
    "InvoiceRefundCases",
    "InvoiceContactLookup",
    "InvoiceAudit",
    "InvoicePaymentReservationTransaction",
    "InvoiceMediaRead",
    "InvoiceMediaObjects",
    "InvoiceMediaList",
}


def _function_name(uri: str) -> str:
    marker = ":function:"
    if marker not in str(uri):
        return ""
    return str(uri).split(marker, 1)[1].split(":", 1)[0]


def _live_package_has_invoice_engine(lam) -> None:
    alias = lam.get_alias(FunctionName=NEW_FUNCTION, Name="live")
    deployed = lam.get_function(
        FunctionName=NEW_FUNCTION, Qualifier=alias["FunctionVersion"])
    location = (deployed.get("Code") or {}).get("Location")
    if not location:
        raise RuntimeError("checkout:live returned no package download location")
    # The presigned URL is credential-shaped. Fetch it in-process and never print/store it.
    with urllib.request.urlopen(location, timeout=60) as response:  # noqa: S310 - AWS presigned
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = set(archive.namelist())
    required = {
        "invoice_engine.py",
        "receipt_layout.py",
        "fonts/DotGothic16-Regular.ttf",
    }
    missing = required - members
    if missing:
        raise RuntimeError(
            "checkout:live is missing invoice runtime assets: " + ", ".join(sorted(missing)))


def _role_has_invoice_authority(iam) -> None:
    row = iam.get_role_policy(RoleName=NEW_ROLE, PolicyName=POLICY_NAME)
    doc = row.get("PolicyDocument") or {}
    sids = {str(item.get("Sid") or "") for item in doc.get("Statement") or []}
    missing = REQUIRED_SIDS - sids
    if missing:
        raise RuntimeError("checkout invoice IAM is incomplete: " + ", ".join(sorted(missing)))


def _live_has_pillow_layer(lam) -> None:
    alias = lam.get_alias(FunctionName=NEW_FUNCTION, Name="live")
    config = lam.get_function_configuration(
        FunctionName=NEW_FUNCTION, Qualifier=alias["FunctionVersion"])
    layers = {row.get("Arn") for row in (config.get("Layers") or [])}
    if PILLOW_LAYER_ARN not in layers:
        raise RuntimeError("checkout:live is missing the Pillow layer")


def _route_source_arn(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    # API Gateway invokes a concrete path, so path parameters must match one segment.
    import re
    concrete_pattern = re.sub(r"\{[^/]+\}", "*", path)
    return (
        f"arn:aws:execute-api:{REGION}:775261844268:{API_ID}/"
        f"{STAGE}/{method}{concrete_pattern}"
    )


def _permission_sid(route_key: str) -> str:
    import hashlib
    digest = hashlib.sha256(route_key.encode("utf-8")).hexdigest()[:12]
    return "apigw-invoice-" + digest


def _ensure_route_permissions(lam, route_keys) -> None:
    for route_key in route_keys:
        sid = _permission_sid(route_key)
        try:
            lam.add_permission(
                FunctionName=NEW_FUNCTION,
                Qualifier="live",
                StatementId=sid,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=_route_source_arn(route_key),
            )
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code != "ResourceConflictException":
                raise


def plan(api):
    routes = api.get_routes(ApiId=API_ID, MaxResults="500").get("Items", [])
    integrations = api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", [])
    by_id = {row["IntegrationId"]: row for row in integrations}

    target_ids = [
        row["IntegrationId"] for row in integrations
        if _function_name(row.get("IntegrationUri", "")) == NEW_FUNCTION
        and row.get("IntegrationType") == "AWS_PROXY"
        and row.get("PayloadFormatVersion") == "2.0"
    ]
    if not target_ids:
        raise RuntimeError("checkout AWS_PROXY payload-2.0 integration is missing")
    target_id = sorted(target_ids)[0]

    changes = []
    invoice_routes = 0
    for route in routes:
        route_key = str(route.get("RouteKey") or "")
        if PREFIX not in route_key:
            continue
        invoice_routes += 1
        integration_id = str(route.get("Target") or "").rsplit("/", 1)[-1]
        integration = by_id.get(integration_id) or {}
        owner = _function_name(integration.get("IntegrationUri", ""))
        if owner == OLD_FUNCTION:
            changes.append({
                "routeKey": route_key,
                "routeId": route["RouteId"],
                "fromIntegration": integration_id,
                "toIntegration": target_id,
            })
        elif owner != NEW_FUNCTION:
            raise RuntimeError(f"{route_key}: unexpected integration owner {owner!r}")

    if not invoice_routes:
        raise RuntimeError("no /invoices routes found")
    return changes, target_id, invoice_routes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    iam = boto3.client("iam", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)

    _live_package_has_invoice_engine(lam)
    _live_has_pillow_layer(lam)
    _role_has_invoice_authority(iam)
    changes, target_id, count = plan(api)

    print(f"invoice routes: {count}; target integration: {target_id}")
    for row in changes:
        print(f"{row['routeKey']}: integrations/{row['fromIntegration']} -> "
              f"integrations/{row['toIntegration']}")

    if not args.apply:
        print(f"dry-run: {len(changes)} route(s) would move")
        return 0

    _ensure_route_permissions(lam, [row["routeKey"] for row in changes])

    for row in changes:
        api.update_route(
            ApiId=API_ID,
            RouteId=row["routeId"],
            Target="integrations/" + row["toIntegration"],
        )

    remaining, _, _ = plan(api)
    if remaining:
        raise RuntimeError(f"invoice route migration incomplete: {remaining}")
    print(f"applied: {len(changes)} route(s) moved to {NEW_FUNCTION}:live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
