#!/usr/bin/env python3
"""Provision the server-side VayuLok Weather/Air Quality gateway.

This creates the Lambda, a least-privilege execution role, the single public API
Gateway route, a live alias, per-route throttling, and invocation permission.

It deliberately does NOT create or print a Google key. The function reads
wecare/google-maps-server at runtime. That secret is owned by
scripts/provision_maps_server_key.py, which captures key material without putting
it on argv/stdout and now scopes the server key to Places/Geocoding/Address
Validation plus Weather and Air Quality.

Usage:
    python scripts/provision_vayulok_environment.py --dry-run
    python scripts/provision_vayulok_environment.py
    python scripts/provision_vayulok_environment.py --verify

After first provision, ordinary code-only updates use:
    python scripts/deploy_all_lambdas.py wecare-vayulok-environment
"""

from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
API_ID = "zllr9lrg7j"
FUNCTION_NAME = "wecare-vayulok-environment"
ROLE_NAME = "wecare-vayulok-environment-role"
ALIAS_NAME = "live"
ROUTE_KEY = "POST /vayulok/environment"
OPTIONS_ROUTE_KEY = "OPTIONS /vayulok/environment"
GOOGLE_SECRET_NAME = "wecare/google-maps-server"
HANDLER = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/core/vayulok-environment/handler.py"
)
RATE_LIMIT = 3.0
BURST_LIMIT = 10


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def _not_found(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


def _zip_handler() -> bytes:
    if not HANDLER.is_file():
        raise FileNotFoundError(HANDLER)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", HANDLER.read_bytes())
    return buf.getvalue()


def ensure_role(dry_run: bool) -> str:
    try:
        iam().get_role(RoleName=ROLE_NAME)
        exists = True
    except ClientError as exc:
        if not _not_found(exc, "NoSuchEntity"):
            raise
        exists = False

    if not exists:
        if dry_run:
            return "would create"
        assume = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume),
            Description="VayuLok Weather/Air Quality server gateway",
            Tags=[
                {"Key": "Project", "Value": "WECARE.DIGITAL"},
                {"Key": "Purpose", "Value": "VayuLokEnvironment"},
            ],
        )
        iam().attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

    if not dry_run:
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "ReadVayuLokGoogleServerKey",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": (
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:"
                    f"secret:{GOOGLE_SECRET_NAME}-*"
                ),
            }],
        }
        iam().put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName="ReadVayuLokGoogleServerKey",
            PolicyDocument=json.dumps(policy),
        )
    return "exists" if exists else "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    groups = logs().describe_log_groups(
        logGroupNamePrefix=name, limit=50
    ).get("logGroups", [])
    exists = any(row.get("logGroupName") == name for row in groups)
    if not exists and not dry_run:
        logs().create_log_group(
            logGroupName=name,
            tags={"Project": "WECARE.DIGITAL", "Purpose": "VayuLokEnvironment"},
        )
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists" if exists else ("would create" if dry_run else "created")


def ensure_function(dry_run: bool) -> str:
    client = lam()
    try:
        current = client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise
        current = None
        exists = False

    if dry_run:
        return "would update" if exists else "would create"

    payload = _zip_handler()
    env = {
        "VAYULOK_GOOGLE_SECRET": GOOGLE_SECRET_NAME,
        "VAYULOK_GOOGLE_SECRET_FIELDS": "api_key,unified_google_api_key",
        "VAYULOK_GOOGLE_TIMEOUT": "10",
        "VAYULOK_MAX_REQUEST_BYTES": "8192",
        "VAYULOK_MAX_UPSTREAM_BYTES": str(6 * 1024 * 1024),
    }

    if exists:
        client.update_function_code(
            FunctionName=FUNCTION_NAME, ZipFile=payload, Publish=False
        )
        client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}",
            Handler="handler.handler",
            Runtime="python3.12",
            Timeout=30,
            MemorySize=512,
            Environment={"Variables": env},
        )
        client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        return "updated"

    client.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.12",
        Role=f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}",
        Handler="handler.handler",
        Code={"ZipFile": payload},
        Timeout=30,
        MemorySize=512,
        Environment={"Variables": env},
        Description="WECARE.DIGITAL VayuLok Weather and Air Quality gateway",
        Publish=False,
    )
    client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
    return "created"


def ensure_alias(dry_run: bool) -> str:
    if dry_run:
        return "would publish/move live alias"

    client = lam()
    latest = client.get_function_configuration(FunctionName=FUNCTION_NAME)["CodeSha256"]
    current = None
    try:
        alias = client.get_alias(FunctionName=FUNCTION_NAME, Name=ALIAS_NAME)
        current = alias["FunctionVersion"]
        served = client.get_function_configuration(
            FunctionName=FUNCTION_NAME, Qualifier=current
        )["CodeSha256"]
        if served == latest:
            return f"already {current}"
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise

    version = client.publish_version(
        FunctionName=FUNCTION_NAME, CodeSha256=latest
    )["Version"]
    if current is None:
        client.create_alias(
            FunctionName=FUNCTION_NAME,
            Name=ALIAS_NAME,
            FunctionVersion=version,
        )
    else:
        client.update_alias(
            FunctionName=FUNCTION_NAME,
            Name=ALIAS_NAME,
            FunctionVersion=version,
        )
    return f"{current or 'none'} -> {version}"


def ensure_routes(dry_run: bool) -> str:
    gateway = api()
    alias_arn = (
        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:"
        f"{FUNCTION_NAME}:{ALIAS_NAME}"
    )

    integrations = gateway.get_integrations(ApiId=API_ID, MaxResults="500").get(
        "Items", []
    )
    integration = next(
        (
            row for row in integrations
            if FUNCTION_NAME in str(row.get("IntegrationUri") or "")
        ),
        None,
    )

    if dry_run:
        integration_id = integration.get("IntegrationId") if integration else "new"
    elif integration:
        integration_id = integration["IntegrationId"]
        if integration.get("IntegrationUri") != alias_arn:
            gateway.update_integration(
                ApiId=API_ID,
                IntegrationId=integration_id,
                IntegrationUri=alias_arn,
            )
    else:
        integration_id = gateway.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=alias_arn,
            IntegrationMethod="POST",
            PayloadFormatVersion="2.0",
            TimeoutInMillis=29000,
        )["IntegrationId"]

    if not dry_run:
        existing = {
            row["RouteKey"]: row
            for row in gateway.get_routes(ApiId=API_ID, MaxResults="1000").get(
                "Items", []
            )
        }
        target = f"integrations/{integration_id}"
        for route_key in (ROUTE_KEY, OPTIONS_ROUTE_KEY):
            if route_key not in existing:
                gateway.create_route(
                    ApiId=API_ID,
                    RouteKey=route_key,
                    Target=target,
                    AuthorizationType="NONE",
                )
            elif existing[route_key].get("Target") != target:
                gateway.update_route(
                    ApiId=API_ID,
                    RouteId=existing[route_key]["RouteId"],
                    Target=target,
                )

        stage = gateway.get_stage(ApiId=API_ID, StageName="prod")
        settings = dict(stage.get("RouteSettings") or {})
        desired = dict(settings)
        for route_key in (ROUTE_KEY, OPTIONS_ROUTE_KEY):
            desired[route_key] = {
                **(settings.get(route_key) or {}),
                "ThrottlingRateLimit": RATE_LIMIT,
                "ThrottlingBurstLimit": BURST_LIMIT,
            }
        if desired != settings:
            gateway.update_stage(
                ApiId=API_ID, StageName="prod", RouteSettings=desired
            )

        source = (
            f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}"
            "/*/*/vayulok/environment"
        )
        for qualifier, sid in (
            (f"{FUNCTION_NAME}:{ALIAS_NAME}", "apigw-vayulok-environment-live"),
            (FUNCTION_NAME, "apigw-vayulok-environment"),
        ):
            try:
                lam().add_permission(
                    FunctionName=qualifier,
                    StatementId=sid,
                    Action="lambda:InvokeFunction",
                    Principal="apigateway.amazonaws.com",
                    SourceArn=source,
                )
            except ClientError as exc:
                if not _not_found(exc, "ResourceConflictException"):
                    raise

    return (
        f"integration={integration_id}; routes={ROUTE_KEY}, {OPTIONS_ROUTE_KEY}; "
        f"throttle={RATE_LIMIT:g}rps/{BURST_LIMIT}burst"
    )


def verify() -> int:
    gateway = api()
    routes = {
        row["RouteKey"]: row
        for row in gateway.get_routes(ApiId=API_ID, MaxResults="1000").get(
            "Items", []
        )
    }
    missing = [
        route for route in (ROUTE_KEY, OPTIONS_ROUTE_KEY) if route not in routes
    ]
    try:
        alias = lam().get_alias(FunctionName=FUNCTION_NAME, Name=ALIAS_NAME)
        version = alias["FunctionVersion"]
    except ClientError:
        version = ""

    ok = not missing and bool(version)
    print(f"function alias live -> {version or 'MISSING'}")
    print(f"routes missing: {', '.join(missing) if missing else 'none'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        return verify()

    print(f"role: {ensure_role(args.dry_run)}")
    print(f"log group: {ensure_log_group(args.dry_run)}")
    if not args.dry_run:
        time.sleep(2)
    print(f"function: {ensure_function(args.dry_run)}")
    print(f"alias: {ensure_alias(args.dry_run)}")
    print(f"api: {ensure_routes(args.dry_run)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
