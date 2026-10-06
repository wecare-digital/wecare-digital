#!/usr/bin/env python3
"""Provision and verify the isolated customer Cognito + WhatsApp OTP stack.

This intentionally does NOT modify the existing WECARE admin user pool.

Usage:
    python scripts/provision_customer_whatsapp_auth.py --dry-run
    python scripts/provision_customer_whatsapp_auth.py
    python scripts/provision_customer_whatsapp_auth.py --verify

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-customer-whatsapp-auth
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
FUNCTION_NAME = "wecare-customer-whatsapp-auth"
LIVE_ALIAS = "live"
FUNCTION_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
)
ROLE_NAME = "wecare-customer-whatsapp-auth-role"
SENDER_FUNCTION = "wecare-whatsapp-business-api:live"

POOL_NAME = "WECARE.DIGITAL-CUSTOMERS"
CLIENT_NAME = "wecare-customer-whatsapp-otp"
GROUP_NAME = "Partner"

# Live Meta values verified through the production backend on 2026-09-23.
WABA_ID = "2094615664435155"
PHONE_NUMBER_ID = "1016149501586345"
# The second WABA. Customer OTP used to be pinned to WABA1 alone, which meant a
# WABA2-scoped customer was refused at the isolation gate and could never sign in.
#
# PRECONDITION, not verified here: `wecare_otp` must be APPROVED in WABA2's OWN template
# list. Meta approves an AUTHENTICATION template per WABA and approval does not cross
# WABAs, so a correct map plus a missing approval answers 132001 and nothing is delivered.
# Checking it needs a Graph call with a token, which this repo does not make.
WABA2_ID = "2513394156072604"
WABA2_PHONE_NUMBER_ID = "1055232054343117"
OTP_TEMPLATE_NAME = "wecare_otp"
OTP_TEMPLATE_LANGUAGE = "en"
OTP_TTL_SECONDS = "600"
MAX_ATTEMPTS = "3"

# Enumeration budget for the unregistered-number reveal. This function answers an
# unknown number with registered="false" so the caller is not left at a dead end, which
# makes the pool enumerable; the budget is what bounds that.
#
# These two keys were originally provisioned onto wecare-secure-files, which reads
# neither of them - the code that does is in this function. Behaviour was correct anyway
# because the values matched the in-code defaults exactly, so the mistake was invisible:
# tuning the numbers on secure-files would have changed nothing at all.
OTP_PROBE_MAX_PER_WINDOW = "5"
OTP_PROBE_WINDOW_SECONDS = "3600"

# Send throttle for REGISTERED numbers (G5 fix). Bounds outbound WhatsApp OTP messages per
# number per window, fail-closed. Defaults match the handler; set here so they are tunable.
OTP_SEND_MAX_PER_WINDOW = "5"
OTP_SEND_WINDOW_SECONDS = "3600"

EXPECTED_ADMIN_POOL_ID = "us-east-1_cSx0RHCIR"


def otp_waba_map() -> str:
    """The WABA -> sender map as the handler's `OTP_WABA_MAP` env value.

    `sort_keys` + compact separators so the string is byte-stable: `reconcile_environment`
    and `--verify` both compare it literally against what is on the `live` alias, and a
    reordered dict would read as drift forever.
    """
    return json.dumps(
        {
            WABA_ID: {
                "phone_number_id": PHONE_NUMBER_ID,
                "template_language": OTP_TEMPLATE_LANGUAGE,
                "template_name": OTP_TEMPLATE_NAME,
            },
            WABA2_ID: {
                "phone_number_id": WABA2_PHONE_NUMBER_ID,
                "template_language": OTP_TEMPLATE_LANGUAGE,
                "template_name": OTP_TEMPLATE_NAME,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


_account_id_cache = None


def account_id() -> str:
    """Resolve the active AWS account instead of embedding it in source."""
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = boto3.client(
            "sts", region_name=REGION
        ).get_caller_identity()["Account"]
    return _account_id_cache


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def cognito():
    return boto3.client("cognito-idp", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


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


def find_pool() -> dict | None:
    paginator = cognito().get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for pool in page.get("UserPools", []):
            if pool.get("Name") == POOL_NAME:
                return pool
    return None


def _zip_handler() -> bytes:
    if not FUNCTION_SOURCE.is_file():
        raise FileNotFoundError(FUNCTION_SOURCE)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", FUNCTION_SOURCE.read_bytes())
    return buf.getvalue()


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
        Description="Customer Cognito WhatsApp OTP execution role",
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "CustomerWhatsAppOTP"},
        ],
    )
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn=(
            "arn:aws:iam::aws:policy/service-role/"
            "AWSLambdaBasicExecutionRole"
        ),
    )
    invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "InvokeWhatsAppSender",
            "Effect": "Allow",
            "Action": ["lambda:InvokeFunction"],
            "Resource": [
                (
                    f"arn:aws:lambda:{REGION}:{account_id()}:function:"
                    "wecare-whatsapp-business-api"
                ),
                (
                    f"arn:aws:lambda:{REGION}:{account_id()}:function:"
                    "wecare-whatsapp-business-api:live"
                ),
            ],
        }],
    }
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="InvokeWhatsAppBusinessApi",
        PolicyDocument=json.dumps(invoke_policy),
    )
    return "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    try:
        logs().describe_log_groups(
            logGroupNamePrefix=name,
            limit=50,
        )
        groups = logs().describe_log_groups(
            logGroupNamePrefix=name,
            limit=50,
        ).get("logGroups", [])
        exists = any(g.get("logGroupName") == name for g in groups)
    except ClientError:
        exists = False
    if not exists and dry_run:
        return "would create with 30-day retention"
    if not exists:
        logs().create_log_group(
            logGroupName=name,
            tags={
                "Project": "WECARE.DIGITAL",
                "Purpose": "CustomerWhatsAppOTP",
            },
        )
    if not dry_run:
        logs().put_retention_policy(
            logGroupName=name,
            retentionInDays=30,
        )
    return "exists; retention verified" if exists else "created"


def expected_environment() -> dict:
    """The env this function must have. One definition, used by create, reconcile and
    verify, so the three cannot drift apart."""
    return {
        "SENDER_FUNCTION": SENDER_FUNCTION,
        # Legacy single-WABA pair. Kept because the handler falls back to it when
        # OTP_WABA_MAP is absent, which keeps a missed env apply a WABA1-only
        # degradation rather than a total OTP outage.
        "META_WABA_ID": WABA_ID,
        "META_PHONE_NUMBER_ID": PHONE_NUMBER_ID,
        # The map the isolation gate tests membership against. Both WABAs, no default.
        "OTP_WABA_MAP": otp_waba_map(),
        "OTP_TEMPLATE_NAME": OTP_TEMPLATE_NAME,
        "OTP_TEMPLATE_LANGUAGE": OTP_TEMPLATE_LANGUAGE,
        "OTP_TTL_SECONDS": OTP_TTL_SECONDS,
        "MAX_ATTEMPTS": MAX_ATTEMPTS,
        "OTP_PROBE_MAX_PER_WINDOW": OTP_PROBE_MAX_PER_WINDOW,
        "OTP_PROBE_WINDOW_SECONDS": OTP_PROBE_WINDOW_SECONDS,
        # Send throttle for registered numbers (G5). Defaults are baked into the handler, so
        # these are set explicitly only to make the limit tunable without a code change.
        "OTP_SEND_MAX_PER_WINDOW": OTP_SEND_MAX_PER_WINDOW,
        "OTP_SEND_WINDOW_SECONDS": OTP_SEND_WINDOW_SECONDS,
    }


def reconcile_environment(dry_run: bool) -> str:
    """Apply any missing or stale env keys to an already-created function.

    ``ensure_function`` returns early when the function exists, so it sets env only on
    first creation. Without this step a key added to ``expected_environment`` after the
    function was created would ship in the source, pass review, and never reach the live
    function - which is exactly how the two probe keys came to be absent here while
    sitting unused on wecare-secure-files.

    Additive only. Keys present on the function but absent from the expected set are left
    alone, because this function's env is also touched by deploy tooling.
    """
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
        FunctionName=FUNCTION_NAME, Environment={"Variables": current}
    )
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    return f"set {', '.join(sorted(drifted))}"


def ensure_function(dry_run: bool) -> str:
    if function_exists():
        return "exists"
    if dry_run:
        return "would create"

    role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]

    # IAM role propagation is eventually consistent.
    for attempt in range(8):
        try:
            lam().create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": _zip_handler()},
                Description=(
                    "Cognito CUSTOM_AUTH WhatsApp OTP for WECARE.DIGITAL WABA1"
                ),
                Timeout=15,
                MemorySize=256,
                Environment={
                    "Variables": {
                        "SENDER_FUNCTION": SENDER_FUNCTION,
                        "META_WABA_ID": WABA_ID,
                        "META_PHONE_NUMBER_ID": PHONE_NUMBER_ID,
                        "OTP_TEMPLATE_NAME": OTP_TEMPLATE_NAME,
                        "OTP_TEMPLATE_LANGUAGE": OTP_TEMPLATE_LANGUAGE,
                        "OTP_TTL_SECONDS": OTP_TTL_SECONDS,
                        "MAX_ATTEMPTS": MAX_ATTEMPTS,
                        "OTP_PROBE_MAX_PER_WINDOW": OTP_PROBE_MAX_PER_WINDOW,
                        "OTP_PROBE_WINDOW_SECONDS": OTP_PROBE_WINDOW_SECONDS,
                    }
                },
                Tags={
                    "Project": "WECARE.DIGITAL",
                    "Purpose": "CustomerWhatsAppOTP",
                    "WabaId": WABA_ID,
                },
            )
            return "created"
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("Lambda create retry exhausted")


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
        FunctionName=FUNCTION_NAME,
        Description="initial customer WhatsApp auth release",
    )
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME,
        Qualifier=version,
    )
    lam().create_alias(
        FunctionName=FUNCTION_NAME,
        Name=LIVE_ALIAS,
        FunctionVersion=version,
        Description="Production Cognito trigger target",
    )
    return f"created -> v{version}"


def ensure_pool(dry_run: bool) -> tuple[str, str | None]:
    current = find_pool()
    if current:
        return "exists", current["Id"]
    if dry_run:
        return "would create", None

    response = cognito().create_user_pool(
        PoolName=POOL_NAME,
        UsernameAttributes=["phone_number"],
        MfaConfiguration="OFF",
        AdminCreateUserConfig={"AllowAdminCreateUserOnly": True},
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 16,
                "RequireUppercase": True,
                "RequireLowercase": True,
                "RequireNumbers": True,
                "RequireSymbols": True,
                "TemporaryPasswordValidityDays": 1,
            }
        },
        Schema=[
            {
                "Name": "phone_number",
                "AttributeDataType": "String",
                "Mutable": True,
                "Required": True,
                "StringAttributeConstraints": {
                    "MinLength": "10",
                    "MaxLength": "20",
                },
            },
            {
                "Name": "email",
                "AttributeDataType": "String",
                "Mutable": True,
                "Required": False,
                "StringAttributeConstraints": {
                    "MinLength": "3",
                    "MaxLength": "2048",
                },
            },
            {
                "Name": "partner_waba_id",
                "AttributeDataType": "String",
                "Mutable": True,
                "Required": False,
                "StringAttributeConstraints": {
                    "MinLength": "1",
                    "MaxLength": "64",
                },
            },
        ],
        UserPoolTags={
            "Project": "WECARE.DIGITAL",
            "Purpose": "CustomerWhatsAppOTP",
            "WabaId": WABA_ID,
        },
    )
    return "created", response["UserPool"]["Id"]


def attach_triggers(pool_id: str, dry_run: bool) -> str:
    if dry_run:
        return "would attach custom-auth triggers"
    function_arn = lam().get_alias(
        FunctionName=FUNCTION_NAME,
        Name=LIVE_ALIAS,
    )["AliasArn"]
    pool = cognito().describe_user_pool(
        UserPoolId=pool_id
    )["UserPool"]

    lambda_config = pool.get("LambdaConfig") or {}
    expected = {
        "DefineAuthChallenge": function_arn,
        "CreateAuthChallenge": function_arn,
        "VerifyAuthChallengeResponse": function_arn,
    }

    if all(lambda_config.get(k) == v for k, v in expected.items()):
        return "already attached"

    cognito().update_user_pool(
        UserPoolId=pool_id,
        LambdaConfig=expected,
        MfaConfiguration="OFF",
        AdminCreateUserConfig={"AllowAdminCreateUserOnly": True},
    )
    return "attached"


def ensure_invoke_permission(pool_id: str, dry_run: bool) -> str:
    sid = "AllowCustomerCognitoInvoke"
    if dry_run:
        return "would ensure Cognito invoke permission"

    source_arn = cognito().describe_user_pool(
        UserPoolId=pool_id
    )["UserPool"]["Arn"]

    try:
        lam().add_permission(
            FunctionName=FUNCTION_NAME,
            Qualifier=LIVE_ALIAS,
            StatementId=sid,
            Action="lambda:InvokeFunction",
            Principal="cognito-idp.amazonaws.com",
            SourceArn=source_arn,
        )
        return "created"
    except ClientError as exc:
        if _not_found(exc, "ResourceConflictException"):
            return "exists"
        raise


def ensure_client(pool_id: str, dry_run: bool) -> tuple[str, str | None]:
    clients = cognito().list_user_pool_clients(
        UserPoolId=pool_id,
        MaxResults=60,
    ).get("UserPoolClients", [])
    for client in clients:
        if client.get("ClientName") == CLIENT_NAME:
            return "exists", client.get("ClientId")
    if dry_run:
        return "would create", None

    created = cognito().create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=CLIENT_NAME,
        GenerateSecret=False,
        ExplicitAuthFlows=[
            "ALLOW_CUSTOM_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
        ],
        PreventUserExistenceErrors="ENABLED",
        AuthSessionValidity=10,
        AccessTokenValidity=60,
        IdTokenValidity=60,
        RefreshTokenValidity=30,
        TokenValidityUnits={
            "AccessToken": "minutes",
            "IdToken": "minutes",
            "RefreshToken": "days",
        },
        EnableTokenRevocation=True,
    )["UserPoolClient"]
    return "created", created["ClientId"]


def ensure_group(pool_id: str, dry_run: bool) -> str:
    try:
        cognito().get_group(
            GroupName=GROUP_NAME,
            UserPoolId=pool_id,
        )
        return "exists"
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise

    if dry_run:
        return "would create"

    cognito().create_group(
        GroupName=GROUP_NAME,
        UserPoolId=pool_id,
        Description="Customer users authenticated by WhatsApp OTP",
        Precedence=10,
    )
    return "created"


def verify() -> int:
    problems: list[str] = []

    # Existing admin auth must remain untouched.
    admin = cognito().describe_user_pool(
        UserPoolId=EXPECTED_ADMIN_POOL_ID
    )["UserPool"]
    if admin.get("LambdaConfig", {}).get("CreateAuthChallenge"):
        problems.append("admin pool unexpectedly has custom-auth trigger")

    pool = find_pool()
    if not pool:
        problems.append("customer pool missing")
        print("FAIL customer pool missing")
        return 1

    pool_id = pool["Id"]
    desc = cognito().describe_user_pool(UserPoolId=pool_id)["UserPool"]
    lambda_config = desc.get("LambdaConfig") or {}

    fn = lam().get_function(FunctionName=FUNCTION_NAME)["Configuration"]
    alias = lam().get_alias(
        FunctionName=FUNCTION_NAME,
        Name=LIVE_ALIAS,
    )
    fn_arn = alias["AliasArn"]

    for key in (
        "DefineAuthChallenge",
        "CreateAuthChallenge",
        "VerifyAuthChallengeResponse",
    ):
        if lambda_config.get(key) != fn_arn:
            problems.append(f"{key} trigger mismatch")

    # Verify the env on the ALIAS, not on $LATEST.
    #
    # The three Cognito triggers invoke `...:live`, so the alias is production and
    # $LATEST is a staging slot nothing calls. A published version freezes its
    # configuration, env included, which means `update_function_configuration` alone
    # changes nothing a caller can observe.
    #
    # Reading $LATEST here is what this function used to do, and it reported
    # "customer WhatsApp Cognito auth verified" immediately after a run that set two env
    # vars the live alias did not have. A verifier that passes while production is stale
    # is worse than no verifier, because it is the thing you trust instead of looking.
    alias_version = alias["FunctionVersion"]
    live_config = lam().get_function_configuration(
        FunctionName=FUNCTION_NAME, Qualifier=alias_version
    )
    live_env = (live_config.get("Environment") or {}).get("Variables") or {}
    latest_env = fn.get("Environment", {}).get("Variables", {})

    for key, value in expected_environment().items():
        if live_env.get(key) != value:
            problems.append(
                f"Lambda env {key} mismatch on live (v{alias_version}) - "
                f"publish a version and move the alias"
            )

    # Called out separately: this is the specific state where the config edit landed but
    # was never published, which is otherwise invisible.
    pending = [
        key for key in expected_environment()
        if latest_env.get(key) != live_env.get(key)
    ]
    if pending:
        problems.append(
            f"$LATEST and live (v{alias_version}) disagree on {', '.join(sorted(pending))} "
            "- an unpublished configuration change"
        )

    client_status, client_id = ensure_client(pool_id, True)
    if client_status == "would create":
        problems.append("app client missing")

    try:
        cognito().get_group(GroupName=GROUP_NAME, UserPoolId=pool_id)
    except ClientError:
        problems.append("Partner group missing")

    print("customer pool: present")
    print(f"app client: {'present' if client_id else 'missing'}")
    print("auth Lambda alias: present")
    print(f"OTP template: {OTP_TEMPLATE_NAME}/{OTP_TEMPLATE_LANGUAGE}")
    print("admin pool: unchanged")

    if problems:
        print("\nFAIL:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\ncustomer WhatsApp Cognito auth verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}")
    print(f"template: {OTP_TEMPLATE_NAME}/{OTP_TEMPLATE_LANGUAGE}")
    print(f"dry run: {args.dry_run}\n")

    print(f"role: {ensure_role(args.dry_run)}")
    print(f"log group: {ensure_log_group(args.dry_run)}")
    print(f"Lambda: {ensure_function(args.dry_run)}")
    print(f"env: {reconcile_environment(args.dry_run)}")
    print(f"live alias: {ensure_live_alias(args.dry_run)}")

    pool_status, pool_id = ensure_pool(args.dry_run)
    print(f"customer pool: {pool_status}")

    if args.dry_run:
        # These used to be four hardcoded strings, which made a dry run against a fully
        # provisioned account report "app client: would create" and "Partner group: would
        # create". Both already existed. A dry run whose output does not depend on the
        # account is worse than no dry run: it is the thing you read to decide whether the
        # real run is safe, and this one said it was about to duplicate a Cognito client.
        #
        # The underlying calls are all read-then-act and take a dry_run flag, so they can
        # report the truth. pool_id is None only when the pool itself is absent, in which
        # case nothing downstream can be inspected yet.
        if pool_id:
            print(f"invoke permission: {ensure_invoke_permission(pool_id, True)}")
            print(f"triggers: {attach_triggers(pool_id, True)}")
            client_status, _ = ensure_client(pool_id, True)
            print(f"app client: {client_status}")
            print(f"Partner group: {ensure_group(pool_id, True)}")
        else:
            print("triggers / client / group: pool absent, cannot inspect yet")
        print("\ndry run: nothing changed")
        return 0

    assert pool_id
    print(f"pool id: {pool_id}")
    print(f"invoke permission: {ensure_invoke_permission(pool_id, False)}")
    print(f"triggers: {attach_triggers(pool_id, False)}")
    client_status, client_id = ensure_client(pool_id, False)
    print(f"app client: {client_status} ({client_id})")
    print(f"Partner group: {ensure_group(pool_id, False)}")

    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
