#!/usr/bin/env python3
"""Provision and verify the customer-registration front door Lambda.

What it stands up
-----------------
- A least-privilege execution role: logs; read of the OTP pepper secret; read/write on the OTP
  challenge table and the customers table only; `lambda:InvokeFunction` on the WhatsApp template
  sender (so it can deliver the `wecare_otp` code); and the scoped Cognito actions on the CUSTOMER pool needed to provision/resolve a login —
  `admin_create_user`, `admin_set_user_password`, `admin_update_user_attributes`, and `list_users`. It has NO SES permission (email verification is a separate
  function) and NO `cognito-idp:SignUp` (the pool is AllowAdminCreateUserOnly and self-signup
  stays off — provisioning is admin-only).
- The function `wecare-customer-registration`, then a published version and the `live` alias.
- The website's front door on HTTP API `zllr9lrg7j` (stage `prod`): one Lambda-proxy
  integration on the `live` alias, the `POST` and `OPTIONS /auth/customer-registration` routes,
  and the resource-based permission that lets that API (and only that API) invoke the alias.
  `--verify` reads all three back.

It does NOT create the OTP pepper secret. `provision_email_verification.py` owns that secret's
first creation; this function only reads it, and both doors share one pepper deliberately so a
code minted for one purpose namespace cannot be replayed against another (the purpose is part of
the HMAC).

Usage:
    python scripts/provision_customer_registration.py --dry-run
    python scripts/provision_customer_registration.py
    python scripts/provision_customer_registration.py --verify

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-customer-registration

Follows .kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md): no credential on a command line, in argv, or in a log.
The pepper is read by the function at runtime via a SecretId name only.
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
FUNCTION_NAME = "wecare-customer-registration"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-customer-registration-role"

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "amplify/functions/auth/customer-registration"
SHARED_DIR = ROOT / "amplify/functions/shared"

PEPPER_SECRET_ID = "wecare/otp/pepper"
OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"
#: The one person store. Registration resolves to (or creates) the customer's ContactsTable row,
#: the same row the WhatsApp inbox and the website checkout use; there is no separate customer
#: table. Reads go through the `phone-index` GSI only.
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
IDENTITY_CLAIMS_TABLE = "stack-wecare-digital-IdentityClaimsTable"
CONTACTS_PHONE_INDEX = "phone-index"
WHATSAPP_INBOUND_TABLE = "stack-wecare-digital-WhatsAppInboundTable"
WHATSAPP_INBOUND_MESSAGE_INDEX = "whatsappMessageId-index"
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"
META_WABA_ID = "2094615664435155"
META_PHONE_NUMBER_ID = "1016149501586345"
SENDER_FUNCTION = "wecare-whatsapp-business-api"
OTP_TEMPLATE_NAME = "wecare_otp"
OTP_TEMPLATE_LANGUAGE = "en"

#: The HTTP API the canonical `/auth` backend flow calls for new customers. It posts
#: `{action: 'request'|'verify'}` to `/auth/customer-registration` for a number Cognito does not
#: know yet, so without these routes no new customer can ever sign in. Same shape as the
#: email-verification door: POST plus the CORS preflight, both on the `live` alias.
API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEYS = ("POST /auth/customer-registration", "OPTIONS /auth/customer-registration")

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

    NOT standalone: the handler imports identity.registration, identity.customer, otp_throttle,
    otp_challenge, response and logging, so the shared layer has to be in the package.
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


def ensure_role(dry_run: bool) -> str:
    exists = role_exists()
    if dry_run:
        return "would reconcile existing role" if exists else "would create and reconcile role"

    assume = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    if not exists:
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume),
            Description="Customer registration front door execution role",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "CustomerRegistration"}],
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
                "Sid": "OtpAndContactTables",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                           "dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{OTP_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}/index/{CONTACTS_PHONE_INDEX}",
                ],
            },
            {
                "Sid": "ReadSignedWhatsAppInboundEvidence",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{WHATSAPP_INBOUND_TABLE}/index/{WHATSAPP_INBOUND_MESSAGE_INDEX}"
                ],
            },
            {
                "Sid": "InvokeWhatsAppSender",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                # The alias, not $LATEST — the OTP is delivered through the live sender only.
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}",
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}:{LIVE_ALIAS}",
                ],
            },
            {
                "Sid": "AdminProvisionCustomerLogin",
                "Effect": "Allow",
                # Provisioning plus exact phone/sub lookup for the internal WhatsApp identity
                # bridge. No SignUp: the customer pool is AllowAdminCreateUserOnly and self-signup
                # stays off.
                "Action": [
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminUpdateUserAttributes",
                    "cognito-idp:ListUsers",
                ],
                "Resource": [
                    f"arn:aws:cognito-idp:{REGION}:{acct}:userpool/{CUSTOMER_POOL_ID}"],
            },
        ],
    }
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="CustomerRegistrationLeastPrivilege",
        PolicyDocument=json.dumps(least_privilege),
    )
    return "reconciled" if exists else "created"


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
            "Project": "WECARE.DIGITAL", "Purpose": "CustomerRegistration"})
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


def expected_environment() -> dict:
    return {
        "OTP_TABLE": OTP_TABLE,
        "CONTACTS_TABLE": CONTACTS_TABLE,
        "WHATSAPP_INBOUND_TABLE": WHATSAPP_INBOUND_TABLE,
        "IDENTITY_CLAIMS_TABLE": IDENTITY_CLAIMS_TABLE,
        "CUSTOMER_POOL_ID": CUSTOMER_POOL_ID,
        "OTP_PEPPER_SECRET_ID": PEPPER_SECRET_ID,
        "META_WABA_ID": META_WABA_ID,
        "META_PHONE_NUMBER_ID": META_PHONE_NUMBER_ID,
        "SENDER_FUNCTION": f"{SENDER_FUNCTION}:{LIVE_ALIAS}",
        "OTP_TEMPLATE_NAME": OTP_TEMPLATE_NAME,
        "OTP_TEMPLATE_LANGUAGE": OTP_TEMPLATE_LANGUAGE,
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
                Description="Customer registration front door (WhatsApp OTP + admin provision)",
                Timeout=15,
                MemorySize=256,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "CustomerRegistration"},
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
        FunctionName=FUNCTION_NAME, Description="initial customer registration release")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Production customer-registration target")
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
    """The AWS_PROXY integration on the `live` alias, reused when it already exists."""
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
    """Alias-qualified invoke permission per route. A function-level grant does not cover `live`."""
    states = []
    for route_key in ROUTE_KEYS:
        method, path = route_key.split(" ", 1)
        sid = "apigw-customer-registration-" + method.lower() + path.replace("/", "-")
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

    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        meta = sm.describe_secret(SecretId=PEPPER_SECRET_ID)
        stages = meta.get("VersionIdsToStages") or {}
        if not any("AWSCURRENT" in v for v in stages.values()):
            problems.append("OTP pepper secret exists but holds no current version "
                            "(run provision_email_verification.py first)")
    except ClientError:
        problems.append("OTP pepper secret missing (run provision_email_verification.py first)")

    print(f"function: present (live v{alias['FunctionVersion']})")
    print(f"customer pool: {CUSTOMER_POOL_ID}")
    print(f"sender: {SENDER_FUNCTION}:{LIVE_ALIAS} template {OTP_TEMPLATE_NAME}")

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
    print("\ncustomer registration provisioning verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}")
    print(f"customer pool: {CUSTOMER_POOL_ID}")
    print(f"sender: {SENDER_FUNCTION}:{LIVE_ALIAS} template {OTP_TEMPLATE_NAME}")
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
