#!/usr/bin/env python3
"""Provision the Cognito CustomMessage trigger that sends branded HTML email.

WHY A PROVISIONER: deploy_all_lambdas.py deliberately refuses to CREATE a
production function that does not already exist, which is correct - creating an
unreviewed function should not be a side effect of a deploy. So first-time
standing-up lives here, and ordinary code updates afterwards go through
    python scripts/deploy_all_lambdas.py wecare-cognito-custom-message

WHY ITS OWN IAM ROLE: all 61 existing functions share
`wecare-digital-lambda-role`, which carries WECARESecretsReadOnly and several
secret-reading inline policies. This function formats an email string and needs
nothing but CloudWatch Logs. Attaching it to the shared role would give a trigger
that fires on every authentication attempt the ability to read every application
secret, which is a bad trade for the convenience of skipping one role. It gets
AWSLambdaBasicExecutionRole and nothing else.

THE COUPLING TO WATCH: `emailMessage` is honoured only while the pool's
EmailSendingAccount is DEVELOPER. It is DEVELOPER today (SES, one@wecare.digital).
If anyone switches the pool to COGNITO_DEFAULT, Cognito answers
InvalidLambdaResponseException and sign-in email stops arriving entirely. --verify
asserts DEVELOPER for that reason.

Usage:
    python scripts/provision_cognito_custom_message.py --dry-run
    python scripts/provision_cognito_custom_message.py
    python scripts/provision_cognito_custom_message.py --verify
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
POOL_ID = "us-east-1_cSx0RHCIR"
FUNCTION_NAME = "wecare-cognito-custom-message"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-cognito-custom-message-role"
FUNCTION_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/auth/cognito-custom-message/handler.py"
)
SENDER_ADDRESS = "one@wecare.digital"
BRAND_NAME = "WECARE.DIGITAL"
SIGNIN_URL = "https://wecare.digital/"
STATEMENT_ID = "AllowCognitoCustomMessageInvoke"


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def cognito():
    return boto3.client("cognito-idp", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def _missing(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


def _zip_handler() -> bytes:
    if not FUNCTION_SOURCE.is_file():
        raise FileNotFoundError(FUNCTION_SOURCE)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", FUNCTION_SOURCE.read_bytes())
    return buf.getvalue()


def ensure_role(dry_run: bool) -> str:
    try:
        iam().get_role(RoleName=ROLE_NAME)
        return "exists"
    except ClientError as exc:
        if not _missing(exc, "NoSuchEntity"):
            raise
    if dry_run:
        return "would create (AWSLambdaBasicExecutionRole only)"

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
        Description=(
            "Cognito CustomMessage trigger. Logs only - formats an email string "
            "and must not be able to read secrets."
        ),
        Tags=[
            {"Key": "Project", "Value": BRAND_NAME},
            {"Key": "Purpose", "Value": "CognitoCustomMessage"},
        ],
    )
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn=(
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        ),
    )
    return "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    groups = logs().describe_log_groups(
        logGroupNamePrefix=name, limit=50).get("logGroups", [])
    exists = any(g.get("logGroupName") == name for g in groups)
    if dry_run:
        return "exists" if exists else "would create with 30-day retention"
    if not exists:
        logs().create_log_group(
            logGroupName=name,
            tags={"Project": BRAND_NAME, "Purpose": "CognitoCustomMessage"},
        )
    logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


def ensure_function(dry_run: bool) -> str:
    try:
        lam().get_function(FunctionName=FUNCTION_NAME)
        return "exists"
    except ClientError as exc:
        if not _missing(exc, "ResourceNotFoundException"):
            raise
    if dry_run:
        return "would create"

    role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    env = {
        "SENDER_ADDRESS": SENDER_ADDRESS,
        "BRAND_NAME": BRAND_NAME,
        "SIGNIN_URL": SIGNIN_URL,
    }
    # IAM role propagation is eventually consistent, so the first create can fail.
    for attempt in range(8):
        try:
            lam().create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.15",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": _zip_handler()},
                Description=(
                    "Cognito CustomMessage trigger: branded HTML for MFA, "
                    "verification and recovery email"
                ),
                Timeout=10,
                MemorySize=256,
                Environment={"Variables": env},
                Tags={"Project": BRAND_NAME, "Purpose": "CognitoCustomMessage"},
            )
            return "created"
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") \
                    != "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("Lambda create retry exhausted")


def ensure_live_alias(dry_run: bool) -> str:
    try:
        lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
        return "exists"
    except ClientError as exc:
        if not _missing(exc, "ResourceNotFoundException"):
            raise
    if dry_run:
        return "would publish v1 and create the live alias"

    version = lam().publish_version(
        FunctionName=FUNCTION_NAME,
        Description="initial custom-message release")["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Cognito trigger target")
    return f"created -> v{version}"


def ensure_invoke_permission(dry_run: bool) -> str:
    if dry_run:
        return "would allow cognito-idp to invoke the live alias"
    pool_arn = cognito().describe_user_pool(
        UserPoolId=POOL_ID)["UserPool"]["Arn"]
    try:
        lam().add_permission(
            FunctionName=FUNCTION_NAME,
            Qualifier=LIVE_ALIAS,
            StatementId=STATEMENT_ID,
            Action="lambda:InvokeFunction",
            Principal="cognito-idp.amazonaws.com",
            SourceArn=pool_arn,
        )
        return "created"
    except ClientError as exc:
        if _missing(exc, "ResourceConflictException"):
            return "exists"
        raise


def attach_trigger(dry_run: bool) -> str:
    """Add CustomMessage to LambdaConfig, PRESERVING every other trigger.

    UpdateUserPool resets omitted fields to their defaults - the same trap as
    UpdateUserPoolClient and SetUserPoolMfaConfig. So the existing pool is read
    first and its whole shape passed back, with only LambdaConfig extended.
    Getting this wrong would silently clear MFA config or the admin-create
    settings.
    """
    pool = cognito().describe_user_pool(UserPoolId=POOL_ID)["UserPool"]
    lambda_config = dict(pool.get("LambdaConfig") or {})

    if dry_run:
        alias_arn = (
            f"arn:aws:lambda:{REGION}:<account>:function:{FUNCTION_NAME}:{LIVE_ALIAS}"
        )
        return (f"would set LambdaConfig.CustomMessage -> {alias_arn}; "
                f"existing triggers preserved: {sorted(lambda_config) or 'none'}")

    alias_arn = lam().get_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)["AliasArn"]
    if lambda_config.get("CustomMessage") == alias_arn:
        return "already attached"
    lambda_config["CustomMessage"] = alias_arn

    params = {
        "UserPoolId": POOL_ID,
        "LambdaConfig": lambda_config,
        "AutoVerifiedAttributes": pool.get("AutoVerifiedAttributes", []),
        "AdminCreateUserConfig": pool.get("AdminCreateUserConfig", {}),
        "EmailConfiguration": pool.get("EmailConfiguration", {}),
        "SmsConfiguration": pool.get("SmsConfiguration", {}),
        "UserPoolTags": pool.get("UserPoolTags", {}),
        "VerificationMessageTemplate": pool.get("VerificationMessageTemplate", {}),
        "Policies": pool.get("Policies", {}),
        "DeletionProtection": pool.get("DeletionProtection", "INACTIVE"),
    }
    # MfaConfiguration is NOT sent here. UpdateUserPool accepts it, but MFA is
    # owned by SetUserPoolMfaConfig, and passing a partial value is how the
    # email-MFA block gets wiped. Verified separately below.
    params = {k: v for k, v in params.items() if v not in ({}, [], None)}
    cognito().update_user_pool(**params)
    return "attached"


def verify() -> int:
    problems: list[str] = []

    pool = cognito().describe_user_pool(UserPoolId=POOL_ID)["UserPool"]
    email_cfg = pool.get("EmailConfiguration") or {}
    sending = email_cfg.get("EmailSendingAccount")

    # The hard precondition for HTML email.
    if sending != "DEVELOPER":
        problems.append(
            f"EmailSendingAccount is {sending!r}, not DEVELOPER - Cognito will "
            f"reject emailMessage with InvalidLambdaResponseException and no "
            f"sign-in email will be delivered"
        )

    try:
        alias_arn = lam().get_alias(
            FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)["AliasArn"]
    except ClientError:
        print("FAIL live alias missing")
        return 1

    attached = (pool.get("LambdaConfig") or {}).get("CustomMessage")
    if attached != alias_arn:
        problems.append(f"CustomMessage trigger is {attached!r}, expected the "
                        f"live alias")

    # MFA must have survived the UpdateUserPool call.
    mfa = cognito().get_user_pool_mfa_config(UserPoolId=POOL_ID)
    if mfa.get("MfaConfiguration") != "OPTIONAL":
        problems.append(f"MfaConfiguration is {mfa.get('MfaConfiguration')!r}, "
                        f"expected OPTIONAL")
    if not mfa.get("EmailMfaConfiguration"):
        problems.append("EmailMfaConfiguration was lost")
    if not (mfa.get("SoftwareTokenMfaConfiguration") or {}).get("Enabled"):
        problems.append("software token (TOTP) is no longer enabled")
    if not mfa.get("SmsMfaConfiguration"):
        problems.append("SmsMfaConfiguration was lost")

    # The function must be least-privilege: logs only.
    fn = lam().get_function(FunctionName=FUNCTION_NAME)["Configuration"]
    role = (fn.get("Role") or "").split("/")[-1]
    if role != ROLE_NAME:
        problems.append(f"function uses role {role!r}, expected the dedicated "
                        f"least-privilege role")
    else:
        att = iam().list_attached_role_policies(RoleName=ROLE_NAME)
        names = [p["PolicyName"] for p in att.get("AttachedPolicies", [])]
        if names != ["AWSLambdaBasicExecutionRole"]:
            problems.append(f"role has unexpected policies: {names}")
        inline = iam().list_role_policies(RoleName=ROLE_NAME).get("PolicyNames", [])
        if inline:
            problems.append(f"role has inline policies: {inline}")

    print(f"pool: {POOL_ID}")
    print(f"EmailSendingAccount: {sending}")
    print(f"From: {email_cfg.get('From')}")
    print(f"CustomMessage trigger: {'attached' if attached else 'MISSING'}")
    print(f"MFA: {mfa.get('MfaConfiguration')} "
          f"(email={bool(mfa.get('EmailMfaConfiguration'))}, "
          f"totp={bool((mfa.get('SoftwareTokenMfaConfiguration') or {}).get('Enabled'))}, "
          f"sms={bool(mfa.get('SmsMfaConfiguration'))})")
    print(f"function role: {role}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncustom-message trigger verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}   pool: {POOL_ID}")
    print(f"dry run: {args.dry_run}\n")
    print(f"role: {ensure_role(args.dry_run)}")
    print(f"log group: {ensure_log_group(args.dry_run)}")
    print(f"Lambda: {ensure_function(args.dry_run)}")
    print(f"live alias: {ensure_live_alias(args.dry_run)}")
    print(f"invoke permission: {ensure_invoke_permission(args.dry_run)}")
    print(f"trigger: {attach_trigger(args.dry_run)}")

    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0

    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
