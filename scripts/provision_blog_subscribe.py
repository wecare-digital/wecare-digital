#!/usr/bin/env python3
"""Provision and verify the public blog-subscription Lambda.

Creates the least-privilege Lambda, its live alias, one API Gateway integration, the exact
POST/OPTIONS /blog/subscribe routes, and alias-qualified invoke permissions.

The function may:
- read the shared OTP pepper secret;
- read/write short-lived OTP/proof rows in DownloadGrantsTable;
- query/write ContactsTable and its phone/email indexes;
- invoke the existing live WhatsApp template sender;
- send the email verification code through SESv2.

It has no Cognito permissions. A blog subscription never creates a customer login.
"""

from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
FUNCTION_NAME = "wecare-blog-subscribe"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-blog-subscribe-role"
API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEYS = ("POST /blog/subscribe", "OPTIONS /blog/subscribe")

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "amplify/functions/auth/blog-subscribe"
SHARED_DIR = ROOT / "amplify/functions/shared"

PEPPER_SECRET_ID = "wecare/otp/pepper"
OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
IDENTITY_CLAIMS_TABLE = "stack-wecare-digital-IdentityClaimsTable"
SENDER_FUNCTION = "wecare-whatsapp-business-api"
META_PHONE_NUMBER_ID = "1016149501586345"
OTP_TEMPLATE_NAME = "wecare_otp"
OTP_TEMPLATE_LANGUAGE = "en"
SES_IDENTITY = "wecare.digital"
SES_CONFIGURATION_SET = "wecare-digital"

_account_id_cache = None


def account_id() -> str:
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    return _account_id_cache


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def _not_found(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


def role_exists() -> bool:
    try:
        iam().get_role(RoleName=ROLE_NAME)
        return True
    except ClientError as exc:
        if _not_found(exc, "NoSuchEntity"):
            return False
        raise


def function_exists() -> bool:
    try:
        lam().get_function(FunctionName=FUNCTION_NAME)
        return True
    except ClientError as exc:
        if _not_found(exc, "ResourceNotFoundException"):
            return False
        raise


def _zip_package() -> bytes:
    handler = FUNCTION_DIR / "handler.py"
    if not handler.is_file():
        raise FileNotFoundError(handler)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", handler.read_bytes())
        lu = SHARED_DIR / "lambda_utils"
        for item in sorted(lu.rglob("*.py")):
            if "__pycache__" in item.parts:
                continue
            archive.write(item, str(item.relative_to(SHARED_DIR)))
    return buf.getvalue()


def expected_environment() -> dict:
    return {
        "OTP_TABLE": OTP_TABLE,
        "CONTACTS_TABLE": CONTACTS_TABLE,
        "IDENTITY_CLAIMS_TABLE": IDENTITY_CLAIMS_TABLE,
        "OTP_PEPPER_SECRET_ID": PEPPER_SECRET_ID,
        "SENDER_FUNCTION": f"{SENDER_FUNCTION}:{LIVE_ALIAS}",
        "META_PHONE_NUMBER_ID": META_PHONE_NUMBER_ID,
        "OTP_TEMPLATE_NAME": OTP_TEMPLATE_NAME,
        "OTP_TEMPLATE_LANGUAGE": OTP_TEMPLATE_LANGUAGE,
    }


def ensure_role(dry_run: bool) -> str:
    if role_exists():
        return "exists"
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
        Description="Public verified blog subscription execution role",
        Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
              {"Key": "Purpose", "Value": "BlogSubscribe"}],
    )
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    acct = account_id()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CustomerIdentityClaims",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{IDENTITY_CLAIMS_TABLE}"
                ],
            },
            {
                "Sid": "ReadOtpPepper",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [f"arn:aws:secretsmanager:{REGION}:{acct}:secret:{PEPPER_SECRET_ID}-*"],
            },
            {
                "Sid": "OtpProofStore",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{OTP_TABLE}"],
            },
            {
                "Sid": "ContactsWrite",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}/index/*",
                ],
            },
            {
                "Sid": "InvokeWhatsAppSender",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}",
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}:{LIVE_ALIAS}",
                ],
            },
            {
                "Sid": "SendVerificationEmail",
                "Effect": "Allow",
                "Action": ["ses:SendEmail"],
                "Resource": [
                    f"arn:aws:ses:{REGION}:{acct}:identity/{SES_IDENTITY}",
                    f"arn:aws:ses:{REGION}:{acct}:configuration-set/{SES_CONFIGURATION_SET}",
                ],
            },
        ],
    }
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="BlogSubscribeLeastPrivilege",
        PolicyDocument=json.dumps(policy),
    )
    return "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    groups = logs().describe_log_groups(logGroupNamePrefix=name, limit=50).get("logGroups", [])
    exists = any(group.get("logGroupName") == name for group in groups)
    if not exists and dry_run:
        return "would create with 30-day retention"
    if not exists:
        logs().create_log_group(
            logGroupName=name, tags={"Project": "WECARE.DIGITAL", "Purpose": "BlogSubscribe"})
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


def ensure_function(dry_run: bool) -> str:
    if function_exists():
        return "exists"
    if dry_run:
        return "would create"

    role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    for attempt in range(8):
        try:
            lam().create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": _zip_package()},
                Description="Verified public blog subscription -> Workspace Contacts",
                Timeout=15,
                MemorySize=256,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "BlogSubscribe"},
            )
            return "created"
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("Lambda create retry exhausted")


def reconcile_environment(dry_run: bool) -> str:
    if not function_exists():
        return "function absent - nothing to reconcile"
    config = lam().get_function_configuration(FunctionName=FUNCTION_NAME)
    current = dict((config.get("Environment") or {}).get("Variables") or {})
    wanted = expected_environment()
    drifted = {key: value for key, value in wanted.items() if current.get(key) != value}
    if not drifted:
        return "env already correct"
    if dry_run:
        return f"would set {', '.join(sorted(drifted))}"
    current.update(drifted)
    lam().update_function_configuration(
        FunctionName=FUNCTION_NAME, Environment={"Variables": current})
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    return f"set {', '.join(sorted(drifted))}"


def ensure_live_alias(dry_run: bool) -> str:
    try:
        lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
        return "exists"
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise
    if dry_run:
        return "would publish v1 and create live alias"
    published = lam().publish_version(
        FunctionName=FUNCTION_NAME, Description="initial verified blog subscription release")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME,
        Name=LIVE_ALIAS,
        FunctionVersion=version,
        Description="Production blog-subscribe target",
    )
    return f"created -> v{version}"


def function_arn() -> str:
    return f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}:{LIVE_ALIAS}"


def _all(method_name: str) -> list:
    method = getattr(api(), method_name)
    items, token = [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            kwargs["NextToken"] = token
        result = method(**kwargs)
        items.extend(result.get("Items", []))
        token = result.get("NextToken")
        if not token:
            return items


def ensure_integration(dry_run: bool) -> tuple[str, str]:
    wanted = function_arn()
    for item in _all("get_integrations"):
        uri = str(item.get("IntegrationUri") or "")
        if wanted in uri:
            return item["IntegrationId"], "exists"
    if dry_run:
        return "DRY_RUN", "would create"
    created = api().create_integration(
        ApiId=API_ID,
        IntegrationType="AWS_PROXY",
        IntegrationUri=wanted,
        PayloadFormatVersion="2.0",
        TimeoutInMillis=15000,
    )
    return created["IntegrationId"], "created"


def ensure_routes(integration_id: str, dry_run: bool) -> str:
    existing = {item["RouteKey"]: item for item in _all("get_routes")}
    results = []
    for route_key in ROUTE_KEYS:
        if route_key in existing:
            results.append(f"{route_key}=exists")
            continue
        if dry_run:
            results.append(f"{route_key}=would create")
            continue
        api().create_route(ApiId=API_ID, RouteKey=route_key, Target=f"integrations/{integration_id}")
        results.append(f"{route_key}=created")
    return ", ".join(results)


def statement_id(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    return "apigw-blog-subscribe-" + method.lower() + path.replace("/", "-")


def source_arn(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    return f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}"


def ensure_permissions(dry_run: bool) -> str:
    results = []
    for route_key in ROUTE_KEYS:
        sid = statement_id(route_key)
        if dry_run:
            results.append(f"{route_key}=would ensure")
            continue
        try:
            lam().add_permission(
                FunctionName=FUNCTION_NAME,
                Qualifier=LIVE_ALIAS,
                StatementId=sid,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=source_arn(route_key),
            )
            results.append(f"{route_key}=created")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceConflictException":
                results.append(f"{route_key}=exists")
            else:
                raise
    return ", ".join(results)


def verify() -> int:
    problems: list[str] = []
    if not function_exists():
        print("FAIL function missing")
        return 1
    try:
        alias = lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
    except ClientError:
        print("FAIL live alias missing")
        return 1

    config = lam().get_function_configuration(
        FunctionName=FUNCTION_NAME, Qualifier=alias["FunctionVersion"])
    env = (config.get("Environment") or {}).get("Variables") or {}
    for key, value in expected_environment().items():
        if env.get(key) != value:
            problems.append(f"env {key} mismatch")

    routes = {item["RouteKey"]: item for item in _all("get_routes")}
    for route_key in ROUTE_KEYS:
        if route_key not in routes:
            problems.append(f"route missing: {route_key}")

    print(f"function: present (live v{alias['FunctionVersion']})")
    print(f"routes: {', '.join(ROUTE_KEYS)}")
    if problems:
        print("\nFAIL:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nblog subscription provisioning verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        return verify()

    print(f"region: {REGION}")
    print(f"api: {API_ID}/{STAGE}")
    print(f"dry run: {args.dry_run}\n")
    print(f"role: {ensure_role(args.dry_run)}")
    print(f"log group: {ensure_log_group(args.dry_run)}")
    print(f"Lambda: {ensure_function(args.dry_run)}")
    print(f"env: {reconcile_environment(args.dry_run)}")
    print(f"live alias: {ensure_live_alias(args.dry_run)}")
    integration_id, integration_state = ensure_integration(args.dry_run)
    print(f"integration: {integration_state}")
    print(f"routes: {ensure_routes(integration_id, args.dry_run)}")
    print(f"permissions: {ensure_permissions(args.dry_run)}")
    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
