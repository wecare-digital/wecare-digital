#!/usr/bin/env python3
"""Deploy the public catalog-media Lambda and route. Dry-run by default."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import time
import zipfile

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION = "wecare-catalog-media"
ROLE = "wecare-catalog-media-role"
POLICY = "CatalogMediaReadOnly"
API_ID = "zllr9lrg7j"
ROUTE = "GET /catalog-media/{filename}"
ENTRY = ROOT / "amplify/functions/ecommerce/catalog-media/handler.py"


def client(service):
    return boto3.client(service, region_name=REGION)


def existing(call, **kwargs):
    try:
        return call(**kwargs)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {
            "ResourceNotFoundException", "NotFoundException", "NoSuchEntity"
        }:
            return None
        raise


def zip_code():
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ENTRY, "handler.py")
    return memory.getvalue()


def role_arn():
    iam = client("iam")
    role = iam.get_role(RoleName=ROLE)["Role"]
    policy = iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
    expected = {
        "Effect": "Allow",
        "Action": ["s3:GetObject"],
        "Resource": ["arn:aws:s3:::wecare-digital-get/secure/d/public/catalog-deploy/catalog/products/*"],
    }
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not any(
        s.get("Effect") == expected["Effect"]
        and sorted(s.get("Action", [])) == expected["Action"]
        and s.get("Resource") == expected["Resource"]
        for s in statements
    ):
        raise RuntimeError("catalog-media role is not scoped to approved catalog-deploy artwork")
    return role["Arn"]


def all_items(call, **kwargs):
    items, token = [], None
    while True:
        page = call(**(dict(kwargs, NextToken=token) if token else kwargs))
        items.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            return items


def apply():
    lam = client("lambda")
    apigw = client("apigatewayv2")
    role = role_arn()
    artifact = zip_code()

    found = existing(lam.get_function, FunctionName=FUNCTION)
    if found is None:
        for attempt in range(6):
            try:
                lam.create_function(
                    FunctionName=FUNCTION,
                    Runtime="python3.12",
                    Role=role,
                    Handler="handler.handler",
                    Code={"ZipFile": artifact},
                    Timeout=15,
                    MemorySize=512,
                    Publish=False,
                    Environment={"Variables": {"CATALOG_BUCKET": "wecare-digital-get"}},
                    Description="Public delivery of approved secure catalog PNG artwork",
                )
                break
            except ClientError as error:
                if attempt == 5 or "cannot be assumed" not in str(error).lower():
                    raise
                time.sleep(5)
    else:
        if found["Configuration"]["Role"] != role:
            raise RuntimeError("catalog-media Lambda uses unexpected execution role")
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=artifact, Publish=False)
        lam.get_waiter("function_updated").wait(FunctionName=FUNCTION)
        lam.update_function_configuration(
            FunctionName=FUNCTION,
            Handler="handler.handler",
            Environment={"Variables": {"CATALOG_BUCKET": "wecare-digital-get"}},
            Timeout=15,
            MemorySize=512,
        )

    lam.get_waiter("function_updated").wait(FunctionName=FUNCTION)
    version = lam.get_function_configuration(FunctionName=FUNCTION)["Version"]

    arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}"
    integrations = all_items(apigw.get_integrations, ApiId=API_ID)
    integration = next((i for i in integrations if i.get("IntegrationUri") == arn), None)
    if integration:
        integration_id = integration["IntegrationId"]
    else:
        integration_id = apigw.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=arn,
            PayloadFormatVersion="2.0",
        )["IntegrationId"]

    routes = {r["RouteKey"]: r for r in all_items(apigw.get_routes, ApiId=API_ID)}
    target = "integrations/" + integration_id
    if ROUTE in routes:
        if routes[ROUTE].get("Target") != target:
            raise RuntimeError("refusing to replace existing catalog-media route")
    else:
        apigw.create_route(
            ApiId=API_ID,
            RouteKey=ROUTE,
            Target=target,
            AuthorizationType="NONE",
        )

    try:
        lam.add_permission(
            FunctionName=FUNCTION,
            StatementId="ApiGatewayCatalogMedia",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/GET/catalog-media/*",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceConflictException":
            raise

    print(json.dumps({"function": FUNCTION, "version": version, "route": ROUTE}))


def verify():
    lam = client("lambda")
    apigw = client("apigatewayv2")
    cfg = lam.get_function_configuration(FunctionName=FUNCTION)
    routes = {r["RouteKey"]: r for r in all_items(apigw.get_routes, ApiId=API_ID)}
    if ROUTE not in routes:
        raise RuntimeError("catalog-media route missing")
    integrations = all_items(apigw.get_integrations, ApiId=API_ID)
    expected_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}"
    matches = [i for i in integrations if i.get("IntegrationUri") == expected_arn]
    if len(matches) != 1:
        raise RuntimeError("catalog-media integration missing or ambiguous")
    if routes[ROUTE].get("Target") != "integrations/" + matches[0]["IntegrationId"]:
        raise RuntimeError("catalog-media route targets wrong integration")
    print(json.dumps({
        "function": FUNCTION,
        "version": cfg["Version"],
        "state": cfg["State"],
        "route": ROUTE,
    }))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply()
    elif args.verify:
        verify()
    else:
        print(json.dumps({"mode": "DRY_RUN", "function": FUNCTION, "route": ROUTE, "zip_bytes": len(zip_code())}))


if __name__ == "__main__":
    main()
