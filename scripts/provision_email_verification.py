#!/usr/bin/env python3
"""Provision and verify the checkout email-verification Lambda and its OTP pepper.

What it stands up
-----------------
- A least-privilege execution role: logs, `ses:SendEmail` (SESv2), read of the OTP pepper
  secret, and read/write on the OTP challenge table and the customers table only.
- The OTP pepper secret `wecare/otp/pepper`. The **value is generated in this process with
  `secrets.token_urlsafe` and written by reference** — it is never printed, never passed on a
  command line, and never echoed back. If the secret already holds a value it is left alone,
  because rotating the pepper invalidates every outstanding code and is an owner decision, not a
  side effect of provisioning.
- The function `wecare-email-verification`, then a published version and the `live` alias.

Usage:
    python scripts/provision_email_verification.py --dry-run
    python scripts/provision_email_verification.py
    python scripts/provision_email_verification.py --verify

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-email-verification

Note on the pepper: this script is the ONLY place a pepper value is created, and it creates it
without the value ever leaving the process. It follows .kiro/steering/secret-handling.md — no
credential on a command line, in argv, or in a log.
"""

from __future__ import annotations

import argparse
import io
import json
import secrets as _secrets
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
FUNCTION_NAME = "wecare-email-verification"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-email-verification-role"
API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEYS = ("POST /auth/email-verification", "OPTIONS /auth/email-verification")

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "amplify/functions/auth/email-verification"
SHARED_DIR = ROOT / "amplify/functions/shared"

PEPPER_SECRET_ID = "wecare/otp/pepper"
OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"
SES_CONFIGURATION_SET = "wecare-digital"
SENDER_ADDRESS = "one@wecare.digital"

_account_id_cache = None


def account_id() -> str:
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = boto3.client(
            "sts", region_name=REGION).get_caller_identity()["Account"]
    return _account_id_cache


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def sm():
    return boto3.client("secretsmanager", region_name=REGION)


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
    """handler.py plus the shared lambda_utils tree it imports.

    NOT standalone: the handler imports otp_challenge, otp_throttle, comms.verification_email,
    identity.customer, response and logging, so the shared layer has to be in the package.
    """
    handler = FUNCTION_DIR / "handler.py"
    if not handler.is_file():
        raise FileNotFoundError(handler)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", handler.read_bytes())
        lu = SHARED_DIR / "lambda_utils"
        for path in lu.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            archive.write(path, str(path.relative_to(SHARED_DIR)))
    return buf.getvalue()


def ensure_pepper(dry_run: bool) -> str:
    """Create the pepper secret with a value generated here. Never overwrite an existing value.

    The value is minted with `secrets.token_urlsafe(48)` (~64 chars, ~288 bits) and written via
    the API. It is not returned, not logged, and not placed on any command line.
    """
    try:
        current = sm().get_secret_value(SecretId=PEPPER_SECRET_ID)
        has_value = bool((current or {}).get("SecretString"))
        if has_value:
            return "exists (value retained; rotation is a separate owner action)"
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise
        current = None

    if dry_run:
        return "would create with a freshly generated pepper"

    payload = json.dumps({"pepper": _secrets.token_urlsafe(48)})
    if current is None:
        sm().create_secret(
            Name=PEPPER_SECRET_ID,
            Description="HMAC pepper for OTP code hashing (email + future WhatsApp at-rest).",
            SecretString=payload,
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "OtpPepper"}],
        )
        return "created with a freshly generated pepper"
    # Secret exists but is empty: fill it once.
    sm().put_secret_value(SecretId=PEPPER_SECRET_ID, SecretString=payload)
    return "populated empty secret with a freshly generated pepper"


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
        Description="Email verification (checkout OTP) execution role",
        Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
              {"Key": "Purpose", "Value": "EmailVerification"}],
    )
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    acct = account_id()
    least_privilege = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SendVerificationEmail",
                "Effect": "Allow",
                "Action": ["ses:SendEmail"],
                # Bound to the sender identity and the configuration set, not "*".
                "Resource": [
                    f"arn:aws:ses:{REGION}:{acct}:identity/{SENDER_ADDRESS}",
                    f"arn:aws:ses:{REGION}:{acct}:identity/wecare.digital",
                    f"arn:aws:ses:{REGION}:{acct}:configuration-set/{SES_CONFIGURATION_SET}",
                ],
            },
            {
                "Sid": "ReadOtpPepper",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [f"arn:aws:secretsmanager:{REGION}:{acct}:secret:{PEPPER_SECRET_ID}-*"],
            },
            {
                # The OTP/proof store only. Verification writes no person record: the profile
                # endpoint stamps the verified email on the customer's ContactsTable row.
                "Sid": "OtpTable",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{OTP_TABLE}",
                ],
            },
        ],
    }
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="EmailVerificationLeastPrivilege",
        PolicyDocument=json.dumps(least_privilege),
    )
    return "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    try:
        groups = logs().describe_log_groups(
            logGroupNamePrefix=name, limit=50).get("logGroups", [])
        exists = any(g.get("logGroupName") == name for g in groups)
    except ClientError:
        exists = False
    if not exists and dry_run:
        return "would create with 30-day retention"
    if not exists:
        logs().create_log_group(logGroupName=name, tags={
            "Project": "WECARE.DIGITAL", "Purpose": "EmailVerification"})
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


def expected_environment() -> dict:
    return {
        "OTP_TABLE": OTP_TABLE,
        "OTP_PEPPER_SECRET_ID": PEPPER_SECRET_ID,
        "SES_CONFIGURATION_SET": SES_CONFIGURATION_SET,
        "VERIFICATION_EMAIL_SENDER": SENDER_ADDRESS,
    }


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
                Description="Checkout email verification (OTP request/verify) for WECARE.DIGITAL",
                Timeout=15,
                MemorySize=256,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "EmailVerification"},
            )
            return "created"
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != \
                    "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("Lambda create retry exhausted")


def reconcile_environment(dry_run: bool) -> str:
    if not function_exists():
        return "function absent - nothing to reconcile"
    config = lam().get_function_configuration(FunctionName=FUNCTION_NAME)
    current = dict((config.get("Environment") or {}).get("Variables") or {})
    wanted = expected_environment()
    drifted = {k: v for k, v in wanted.items() if current.get(k) != v}
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
        FunctionName=FUNCTION_NAME, Description="initial email verification release")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Production email-verification target")
    return f"created -> v{version}"


def _all_api(method_name: str) -> list:
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
    wanted = f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}:{LIVE_ALIAS}"
    for item in _all_api("get_integrations"):
        if wanted in str(item.get("IntegrationUri") or ""):
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
    existing = {item["RouteKey"] for item in _all_api("get_routes")}
    states = []
    for route_key in ROUTE_KEYS:
        if route_key in existing:
            states.append(f"{route_key}=exists")
        elif dry_run:
            states.append(f"{route_key}=would create")
        else:
            api().create_route(
                ApiId=API_ID, RouteKey=route_key,
                Target=f"integrations/{integration_id}")
            states.append(f"{route_key}=created")
    return ", ".join(states)


def ensure_permissions(dry_run: bool) -> str:
    states = []
    for route_key in ROUTE_KEYS:
        method, path = route_key.split(" ", 1)
        sid = "apigw-email-verification-" + method.lower() + path.replace("/", "-")
        if dry_run:
            states.append(f"{route_key}=would ensure")
            continue
        try:
            lam().add_permission(
                FunctionName=FUNCTION_NAME,
                Qualifier=LIVE_ALIAS,
                StatementId=sid,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}",
            )
            states.append(f"{route_key}=created")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceConflictException":
                states.append(f"{route_key}=exists")
            else:
                raise
    return ", ".join(states)


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

    live_config = lam().get_function_configuration(
        FunctionName=FUNCTION_NAME, Qualifier=alias["FunctionVersion"])
    live_env = (live_config.get("Environment") or {}).get("Variables") or {}
    for key, value in expected_environment().items():
        if live_env.get(key) != value:
            problems.append(f"env {key} mismatch on live (v{alias['FunctionVersion']})")

    # The pepper must hold a value, without reading the value itself.
    try:
        meta = sm().describe_secret(SecretId=PEPPER_SECRET_ID)
        stages = meta.get("VersionIdsToStages") or {}
        if not any("AWSCURRENT" in v for v in stages.values()):
            problems.append("OTP pepper secret exists but holds no current version")
    except ClientError:
        problems.append("OTP pepper secret missing")

    print(f"function: present (live v{alias['FunctionVersion']})")
    print("OTP pepper secret: present with a current version"
          if "OTP pepper secret missing" not in problems else "OTP pepper secret: MISSING")
    print(f"sender: {SENDER_ADDRESS} / config set {SES_CONFIGURATION_SET}")

    live_routes = {item["RouteKey"] for item in _all_api("get_routes")}
    for route_key in ROUTE_KEYS:
        if route_key not in live_routes:
            problems.append(f"route missing: {route_key}")
    print(f"routes: {', '.join(ROUTE_KEYS)}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nemail verification provisioning verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}")
    print(f"sender: {SENDER_ADDRESS} / config set {SES_CONFIGURATION_SET}")
    print(f"dry run: {args.dry_run}\n")

    print(f"pepper secret: {ensure_pepper(args.dry_run)}")
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
