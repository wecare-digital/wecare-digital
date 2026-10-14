#!/usr/bin/env python3
"""Provision the staff-only AWS-native catalog API. Dry-run by default.

Production creation/update, API Gateway routing and alias promotion occur only
with --apply after tests and human review. NEVER reads Secrets Manager values.
The existing API Gateway routes and noncatalog IAM roles are untouched.

Usage:
    python scripts/provision_native_catalog_api.py
    python scripts/provision_native_catalog_api.py --apply
    python scripts/provision_native_catalog_api.py --verify
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import time
import zipfile

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION = "wecare-native-catalog-admin"
ROLE = FUNCTION + "-role"
POLICY = "NativeCatalogLeastPrivilege"
API_NAME = "wecare-digital-api"
TABLE = "stack-wecare-digital-ProductsTable"
STAFF_POOL = "us-east-1_cSx0RHCIR"
ROUTES = (
    "GET /native-catalog/products",
    "POST /native-catalog/products",
    "GET /native-catalog/products/{id}",
    "PATCH /native-catalog/products/{id}",
    "DELETE /native-catalog/products/{id}",
    "PATCH /native-catalog/products/{id}/variants/{sku}",
)
ENTRY = ROOT / "amplify/functions/ecommerce/native-catalog-admin/handler.py"
SHARED = ROOT / "amplify/functions/shared"


def client(service):
    return boto3.client(service, region_name=REGION)


def is_missing(error):
    return error.response.get("Error", {}).get("Code") in (
        "NoSuchEntity", "ResourceNotFoundException", "NotFoundException"
    )


def existing(call, **kwargs):
    try:
        return call(**kwargs)
    except ClientError as error:
        if is_missing(error):
            return None
        raise


def role_policy():
    table = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}"
    pool = f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/{STAFF_POOL}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "OnlyNativeProductsTable", "Effect": "Allow",
             "Action": [
                 "dynamodb:GetItem", "dynamodb:Scan", "dynamodb:PutItem",
                 "dynamodb:UpdateItem",
             ], "Resource": [table]},
            {"Sid": "ReadStaffGroupMembership", "Effect": "Allow",
             "Action": ["cognito-idp:AdminListGroupsForUser"],
             "Resource": [pool]},
            {"Sid": "OwnLogs", "Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream",
                        "logs:PutLogEvents"],
             "Resource": [
                 f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION}",
                 f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION}:*",
             ]},
        ],
    }


def zip_code():
    if not ENTRY.exists() or not (SHARED / "lambda_utils/middleware.py").exists():
        raise RuntimeError("native admin handler or shared middleware missing")
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ENTRY, "handler.py")
        for p in sorted((SHARED / "lambda_utils").rglob("*.py")):
            if "/__pycache__/" not in p.as_posix():
                archive.write(p, p.relative_to(SHARED).as_posix())
    return memory.getvalue()


def api_id():
    paginator = client("apigatewayv2").get_paginator("get_apis")
    apis = [
        a for page in paginator.paginate()
        for a in page.get("Items", [])
        if a.get("Name") == API_NAME
    ]
    if len(apis) != 1:
        raise RuntimeError("Expected exactly one production HTTP API")
    return apis[0]["ApiId"]


def apply():
    iam, lam, apigw = client("iam"), client("lambda"), client("apigatewayv2")
    role = existing(iam.get_role, RoleName=ROLE)
    if role is None:
        trust = {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"}]}
        role = iam.create_role(
            RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
            Description="Dedicated, staff-only AWS-native catalog CRUD role",
        )
        role_arn = role["Role"]["Arn"]
    else:
        role_arn = role["Role"]["Arn"]
    iam.put_role_policy(
        RoleName=ROLE, PolicyName=POLICY,
        PolicyDocument=json.dumps(role_policy()),
    )
    artifact = zip_code()
    env = {"Variables": {
        "AWS_REGION": REGION, "PRODUCTS_TABLE": TABLE,
        "COGNITO_USER_POOL_ID": STAFF_POOL, "LOG_LEVEL": "INFO",
        "AUTH_SKIP_PATHS": "",
    }}
    found = existing(lam.get_function, FunctionName=FUNCTION)
    if found is None:
        # New IAM roles may need a short propagation period.
        for attempt in range(6):
            try:
                lam.create_function(
                    FunctionName=FUNCTION, Runtime="python3.12",
                    Role=role_arn, Handler="handler.handler",
                    Code={"ZipFile": artifact}, Timeout=20, MemorySize=256,
                    Publish=False, Environment=env,
                    Description="Staff Cognito protected AWS-native product catalog",
                )
                break
            except ClientError as error:
                if attempt == 5 or "cannot be assumed" not in str(error).lower():
                    raise
                time.sleep(5)
    else:
        if found["Configuration"]["Role"] != role_arn:
            raise RuntimeError("Existing native-catalog function uses different IAM role")
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=artifact, Publish=False)
        client("lambda").get_waiter("function_updated").wait(FunctionName=FUNCTION)
        lam.update_function_configuration(FunctionName=FUNCTION, Environment=env)
    client("lambda").get_waiter("function_updated").wait(FunctionName=FUNCTION)
    version = lam.publish_version(FunctionName=FUNCTION)["Version"]
    alias = existing(lam.get_alias, FunctionName=FUNCTION, Name="live")
    if alias:
        lam.update_alias(FunctionName=FUNCTION, Name="live", FunctionVersion=version)
    else:
        lam.create_alias(FunctionName=FUNCTION, Name="live", FunctionVersion=version)
    aid = api_id()
    integration_uri = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}:live"
    integrations = apigw.get_integrations(ApiId=aid).get("Items", [])
    match = next((i for i in integrations if i.get("IntegrationUri") == integration_uri), None)
    if match:
        integration_id = match["IntegrationId"]
    else:
        integration_id = apigw.create_integration(
            ApiId=aid, IntegrationType="AWS_PROXY",
            IntegrationUri=integration_uri, PayloadFormatVersion="2.0",
        )["IntegrationId"]
    current = {
        x["RouteKey"]: x for x in apigw.get_routes(ApiId=aid).get("Items", [])
    }
    target = "integrations/" + integration_id
    for route in ROUTES:
        if route in current:
            if current[route].get("Target") != target:
                raise RuntimeError(f"Refusing to replace existing route: {route}")
        else:
            apigw.create_route(
                ApiId=aid, RouteKey=route, Target=target,
                AuthorizationType="NONE",  # handler enforces Cognito GetUser and role!
            )
    source = f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{aid}/*/*/native-catalog/products*"
    statement = "ApiGatewayNativeCatalog"
    try:
        lam.add_permission(
            FunctionName=FUNCTION, Qualifier="live",
            StatementId=statement, Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com", SourceArn=source,
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceConflictException":
            raise
    print(json.dumps({"function": FUNCTION, "version": version,
                      "api_id": aid, "route_count": len(ROUTES)}))


def verify():
    lam, apigw = client("lambda"), client("apigatewayv2")
    cfg = lam.get_function_configuration(FunctionName=FUNCTION, Qualifier="live")
    aid = api_id()
    all_routes = {v["RouteKey"]: v for v in apigw.get_routes(ApiId=aid)["Items"]}
    missing = sorted(set(ROUTES) - set(all_routes))
    wrong = [x for x in ROUTES if x in all_routes and
             not all_routes[x].get("Target", "").startswith("integrations/")]
    print(json.dumps({
        "function": FUNCTION, "version": cfg["Version"], "status": cfg["State"],
        "role": cfg["Role"], "api_id": aid,
        "missing_routes": missing, "unintegrated_routes": wrong,
    }))
    if missing or wrong or cfg["State"] != "Active":
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply and args.verify:
        parser.error("--apply and --verify are mutually exclusive")
    if args.verify:
        verify()
    elif args.apply:
        apply()
    else:
        print(json.dumps({
            "mode": "DRY_RUN", "function": FUNCTION, "role": ROLE,
            "table": TABLE, "routes": ROUTES,
            "zip_bytes": len(zip_code()),
            "notice": "No AWS resources changed. --apply required.",
        }))


if __name__ == "__main__":
    main()
