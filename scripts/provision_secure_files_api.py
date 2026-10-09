#!/usr/bin/env python3
"""Provision the wecare-secure-files Lambda, its role, and its HTTP API routes.

Creates or updates, idempotently:

* IAM role ``wecare-secure-files-role`` with a least-privilege inline policy
* Lambda ``wecare-secure-files`` (python3.12) + published version + ``live`` alias
* Every route in ``ROUTES`` on HTTP API ``zllr9lrg7j``, all pointing at the alias
  (the count used to be written out here and went stale twice; read the list)
* Revocation of ``wecare-razorpay-webhook``'s grants-table access. The webhook used to
  mark grants paid; it no longer may, so the permission is removed rather than granted.
  See ``ensure_webhook_access``.

Two policy choices worth stating, because a wildcard here would be invisible and
wrong:

* S3 writes are scoped to ``secure/*`` on the one bucket. The function may now also
  **read** exactly one public prefix, ``o/stack/whatsapp-media/incoming/*``, because a
  Drop Docs document arriving over WhatsApp lands there and ``CopyObject`` needs
  ``GetObject`` on its source. That grant is read-only and single-prefix: the function
  still cannot write anywhere under ``o/``, and nothing in this policy can delete an
  object anywhere.
* Cognito admin actions are scoped to the **customer** pool ARN only. This role
  must never be able to create or modify a user in the admin pool.

Run after ``provision_secure_file_sharing.py`` (which makes the tables) and
``provision_customer_whatsapp_auth.py`` (which makes the customer pool).

Usage
-----
**A bare invocation is a DRY RUN.** Writing requires ``--apply``, which publishes a
version and moves the production ``live`` alias. The default used to be the other way
round and it cost an unauthorized production apply on 2026-10-07; see ``main``.

    python scripts/provision_secure_files_api.py              # dry run (the default)
    python scripts/provision_secure_files_api.py --dry-run    # the same, said out loud
    python scripts/provision_secure_files_api.py --apply      # writes; moves live
    python scripts/provision_secure_files_api.py --verify
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
ACCOUNT = "775261844268"
API_ID = "zllr9lrg7j"

FUNCTION_NAME = "wecare-secure-files"
ROLE_NAME = "wecare-secure-files-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
LIVE_ALIAS = "live"

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "amplify" / "functions" / "core" / "secure-files"
LAMBDA_UTILS = ROOT / "amplify" / "functions" / "shared" / "lambda_utils"

BUCKET = "wecare-digital-get"
SECURE_PREFIX = "secure/"
# The ONE public prefix this role may read, and only to copy out of it. WhatsApp uploads
# land here (inbound-whatsapp-handler) and CloudFront serves the whole o/ root
# unauthenticated, so a Drop Docs document has to be copied into secure/ before anything
# treats it as a customer document. CopyObject needs GetObject on the source; PutObject and
# HeadObject on secure/* already exist above.
PUBLIC_WHATSAPP_INCOMING_PREFIX = "o/stack/whatsapp-media/incoming/"
FILES_TABLE = "stack-wecare-digital-SecureFilesTable"
GRANTS_TABLE = "stack-wecare-digital-DownloadGrantsTable"
REQUESTS_TABLE = "stack-wecare-digital-ServiceRequestsTable"
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"
ADMIN_POOL_ID = "us-east-1_cSx0RHCIR"
META_WABA_ID = "2094615664435155"
# The API key pair lives here. wecare/razorpay-webhook holds only webhook_secret
# and never the pair - reading the pair from it is the bug that returned 501 on
# every customer-service top-up. See amplify/functions/core/secure-files/razorpay_orders.py
RAZORPAY_SECRET_NAME = "wecare/razorpay/api"

WEBHOOK_FUNCTION = "wecare-razorpay-webhook"

ROUTES = [
    # admin surface (authorised inside the handler via require_auth Operator)
    ("GET", "/secure-files"),
    ("POST", "/secure-files/upload-init"),
    ("POST", "/secure-files/{fileId}/confirm"),
    ("POST", "/secure-files/{fileId}/revoke"),
    # customer surface (customer-pool token, checked inside the handler)
    ("GET", "/secure-files/mine"),
    ("POST", "/secure-files/{fileId}/order"),
    ("POST", "/secure-files/{fileId}/whatsapp-pay"),
    ("GET", "/secure-files/{fileId}/download"),
    # Drop Docs: promote a document into secure/ and register it against a paid request,
    # and read back the caller's own documents for one request. Both flag-gated OFF by
    # DROPDOCS_ATTACH_ENABLED; the routes exist so the flag has something to switch. The
    # `dropdocs` segment is literal, so neither collides with the {fileId} routes above.
    ("POST", "/secure-files/dropdocs/attach"),
    ("GET", "/secure-files/dropdocs/{requestId}/documents"),
]

# Lambdas secure-files invokes for WhatsApp delivery.
WA_SENDER = "wecare-outbound-whatsapp"
WA_MEDIA = "wecare-whatsapp-business-api"

EXCLUDE_DIRS = {"__pycache__", "tests", ".pytest_cache"}


def iam():
    return boto3.client("iam", region_name=REGION)


def lam():
    return boto3.client("lambda", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


# ── IAM ───────────────────────────────────────────────────────────────────────

def policy_document() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SecurePrefixOnly",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:HeadObject"],
                # deliberately NOT the whole bucket: the open o/ tier is out of scope
                "Resource": f"arn:aws:s3:::{BUCKET}/{SECURE_PREFIX}*",
            },
            {
                "Sid": "ReadWhatsAppIncomingToPromote",
                "Effect": "Allow",
                # READ ONLY, and one prefix. No PutObject here (a Drop Docs document is
                # only ever copied OUT of o/) and no DeleteObject anywhere in this policy:
                # the public original is left to expire under the existing
                # s3_whatsapp_media_incoming TTL in operations/system-cleanup, which is
                # recorded as residual exposure rather than papered over.
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::{BUCKET}/{PUBLIC_WHATSAPP_INCOMING_PREFIX}*",
            },
            {
                "Sid": "PrivateIncomingOwnershipProof",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-MessagesTable",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-ContactsTable",
                ],
            },
            {
                "Sid": "DropDocsRequestRows",
                "Effect": "Allow",
                # Enough to resolve the caller's own REQ# row and register a DOC# row, and
                # nothing more. No Query, no Scan, no DeleteItem, no UpdateItem on the
                # request table beyond what the attach transaction needs.
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{REQUESTS_TABLE}",
            },
            {
                "Sid": "Catalogue",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{FILES_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{FILES_TABLE}/index/*",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{GRANTS_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{GRANTS_TABLE}/index/*",
                ],
            },
            {
                "Sid": "CustomerPoolOnly",
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminUpdateUserAttributes",
                    "cognito-idp:AdminAddUserToGroup",
                    "cognito-idp:AdminGetUser",
                ],
                # scoped to the customer pool: this role must never be able to
                # touch a user in the admin pool
                "Resource": f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/{CUSTOMER_POOL_ID}",
            },
            {
                "Sid": "ValidateCallerToken",
                "Effect": "Allow",
                # GetUser acts on the token's own user, so it takes no resource
                "Action": ["cognito-idp:GetUser"],
                "Resource": "*",
            },
            {
                "Sid": "AdminRoleLookup",
                "Effect": "Allow",
                # require_auth resolves the admin's groups in the admin pool. Read
                # only - no admin-pool mutation.
                "Action": ["cognito-idp:AdminListGroupsForUser", "cognito-idp:AdminGetUser"],
                "Resource": f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/{ADMIN_POOL_ID}",
            },
            {
                "Sid": "RazorpayKeyByArn",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                # one secret by ARN. The -* suffix matches the six random
                # characters Secrets Manager appends.
                "Resource": (
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{RAZORPAY_SECRET_NAME}-*"
                ),
            },
            {
                "Sid": "WhatsAppDelivery",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                # Named individually rather than a wildcard: this role should be able
                # to send WhatsApp messages and upload media, not invoke the fleet.
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_SENDER}",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_SENDER}:*",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_MEDIA}",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_MEDIA}:*",
                ],
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION_NAME}:*",
            },
        ],
    }


def ensure_role(dry_run: bool) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam().get_role(RoleName=ROLE_NAME)
        exists = True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        exists = False

    if dry_run:
        return "exists (would refresh policy)" if exists else "would create"

    if not exists:
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for wecare-secure-files",
        )
        time.sleep(12)  # IAM propagation before Lambda validates the role

    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="wecare-secure-files",
        PolicyDocument=json.dumps(policy_document()),
    )
    return "created" if not exists else "policy refreshed"


# ── packaging ─────────────────────────────────────────────────────────────────

def package() -> bytes:
    """handler.py + razorpay_orders.py + lambda_utils/, deterministically."""
    if not (SOURCE_DIR / "handler.py").exists():
        raise SystemExit(f"missing {SOURCE_DIR / 'handler.py'}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("handler.py", "razorpay_orders.py"):
            archive.write(SOURCE_DIR / name, name)
        for path in sorted(LAMBDA_UTILS.rglob("*")):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            archive.write(path, str(Path("lambda_utils") / path.relative_to(LAMBDA_UTILS)))
    return buffer.getvalue()


def environment(payment_enabled: bool = False) -> dict:
    # AWS_REGION is deliberately absent: Lambda reserves it and rejects it.
    return {
        "SECURE_FILES_BUCKET": BUCKET,
        "SECURE_FILES_TABLE": FILES_TABLE,
        "DOWNLOAD_GRANTS_TABLE": GRANTS_TABLE,
        "CUSTOMER_USER_POOL_ID": CUSTOMER_POOL_ID,
        "COGNITO_USER_POOL_ID": ADMIN_POOL_ID,  # require_auth resolves admins here
        "META_WABA_ID": META_WABA_ID,
        "META_PHONE_NUMBER_ID": "1016149501586345",
        "PARTNER_GROUP": "Partner",
        # Both templates are already APPROVED; nothing here waits on Meta.
        # wecare_pay    [IMAGE, BODY, FOOTER, BUTTONS(ORDER_DETAILS)]
        # 01_wecare_doc [DOCUMENT, BODY, FOOTER, BUTTONS(FLOW)]
        "WA_PAY_TEMPLATE": "wecarepay_wa",
        # wd_file_delivery: APPROVED 2026-09-25. DOCUMENT header, BODY variables for
        # customer and file name, and no buttons. Replaced 01_wecare_doc, which could
        # name neither and carried a stray FLOW button labelled "Subscribe".
        # Reverting to "01_wecare_doc" is a safe rollback; the body-parameter shape
        # follows the template NAME so the two cannot desynchronise.
        "WA_DOC_TEMPLATE": "wd_file_delivery",
        "WA_SENDER_FUNCTION": WA_SENDER,
        "WA_MEDIA_FUNCTION": f"{WA_MEDIA}:live",
        "SECURE_FILE_PRICE_PAISE": "4900",
        # Web redeem: a browser follows it instantly.
        "DOWNLOAD_URL_TTL_SECONDS": "60",
        # WhatsApp link delivery: a person taps when they read the message. 60s
        # would usually be expired on arrival, and they have already paid.
        "WHATSAPP_LINK_TTL_SECONDS": "21600",
        # OTP_PROBE_* deliberately absent. The enumeration budget is enforced in
        # wecare-customer-whatsapp-auth, which is the only function that reads those
        # keys; they are provisioned there by provision_customer_whatsapp_auth.py.
        "UPLOAD_URL_TTL_SECONDS": "900",
        "GRANT_TTL_SECONDS": "1800",
        # The Phase O-1 request store. A Drop Docs document is registered against a REQ#
        # row there, not in SecureFilesTable.
        "SERVICE_REQUESTS_TABLE": REQUESTS_TABLE,
        # Drop Docs document attach. Ships OFF and stays off: there is no upload UI in
        # Phase O-2, so the only thing turning this on would do is open a route nothing
        # calls. Read per call in the handler, so flipping it does not need a republish
        # to be observed - but it DOES need one to reach production, because the HTTP API
        # invokes the live alias. Separate from SECURE_FILES_PAYMENT_ENABLED and must
        # never be confused with it: this one stores a document, that one takes money.
        "DROPDOCS_ATTACH_ENABLED": "false",
        # A secret NAME, never a value. See .kiro/steering/secret-handling.md.
        "RAZORPAY_SECRET_ID": RAZORPAY_SECRET_NAME,
        # Enabling paid downloads is an owner action. While off, the order route
        # refuses and razorpay_orders is never even imported, so no Razorpay
        # endpoint is contacted and no credential is read.
        #
        # Defaults to off, and a plain re-provision therefore never silently turns
        # payments on: only --enable-payment does that.
        "SECURE_FILES_PAYMENT_ENABLED": "true" if payment_enabled else "false",
    }


def current_payment_flag() -> bool:
    variables = (
        lam().get_function_configuration(FunctionName=f"{FUNCTION_NAME}:{LIVE_ALIAS}")
        .get("Environment", {})
        .get("Variables", {})
    )
    return str(variables.get("SECURE_FILES_PAYMENT_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on",
    )


def set_payment_flag(enabled: bool) -> int:
    """Turn paid downloads on or off, and actually make it reach production.

    Three steps, not one, and skipping any of them leaves a misleading state:

    1. ``update_function_configuration`` with the **whole** variable map. Passing a
       partial map would delete every variable not mentioned - the function would
       come back up with no bucket, no table and no pool id.
    2. Publish a version. A version freezes its environment, so the flag has to be
       captured into a new one.
    3. Move the ``live`` alias. The HTTP API invokes the alias, so until this runs
       the change is real on ``$LATEST`` and invisible to every request.

    Written out because doing only step 1 by hand looks like it worked.
    """
    client = lam()

    # Preflight: confirm the key secret exists. Metadata only - this deliberately
    # does not read the secret's value, so nothing lands in a log or a terminal.
    # It catches a typo'd secret name, which would otherwise surface much later as
    # an opaque order-creation failure.
    if enabled:
        try:
            boto3.client("secretsmanager", region_name=REGION).describe_secret(
                SecretId=RAZORPAY_SECRET_NAME
            )
            print(f"preflight: secret {RAZORPAY_SECRET_NAME} exists")
        except ClientError as exc:
            print(f"ABORT: cannot find secret {RAZORPAY_SECRET_NAME}: "
                  f"{exc.response['Error']['Code']}")
            return 1
        print("preflight: this script cannot verify the secret's key_id/key_secret "
              "values, and deliberately does not read them.")
        print("           If order creation fails after this, check those two fields "
              "in the Razorpay dashboard.")

    was = current_payment_flag()
    print(f"payment flag: {was} -> {enabled}")
    if was == enabled:
        print("already in the requested state; nothing to do")
        return 0

    rollback_version = client.get_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS
    )["FunctionVersion"]

    client.update_function_configuration(
        FunctionName=FUNCTION_NAME,
        Environment={"Variables": environment(payment_enabled=enabled)},
    )
    client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)

    version = client.publish_version(
        FunctionName=FUNCTION_NAME,
        Description=f"payment {'enabled' if enabled else 'disabled'}",
    )["Version"]
    client.update_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version
    )

    print(f"live: v{rollback_version} -> v{version}")
    print(f"rollback: aws lambda update-alias --function-name {FUNCTION_NAME} "
          f"--name {LIVE_ALIAS} --function-version {rollback_version} --region {REGION}")

    now = current_payment_flag()
    if now != enabled:
        print(f"FAIL read-back says {now}, expected {enabled}")
        return 1
    print(f"read-back: payment enabled = {now}")
    return 0


def ensure_function(zip_bytes: bytes, dry_run: bool) -> str:
    client = lam()
    try:
        client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except client.exceptions.ResourceNotFoundException:
        exists = False

    # Preserve whatever the owner set, rather than resetting to the default.
    #
    # Without this, re-running the provisioner after payments were deliberately
    # enabled would quietly turn them back OFF: `environment()` defaults the flag to
    # false and the update below writes the whole map. Customers would stop being
    # able to pay, with nothing in the output saying so.
    #
    # Read from the live alias, not $LATEST, because the alias is what production
    # actually serves. A fresh function has nothing to preserve and stays off.
    keep_payment = current_payment_flag() if exists else False

    if dry_run:
        state = "on" if keep_payment else "off"
        return f"exists (would update, payment stays {state})" if exists else "would create"

    if exists:
        client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=ROLE_ARN,
            Handler="handler.handler",
            Runtime="python3.12",
            Timeout=30,
            MemorySize=512,
            Environment={"Variables": environment(payment_enabled=keep_payment)},
        )
        client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        return f"updated (payment left {'on' if keep_payment else 'off'})"

    client.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.12",
        Role=ROLE_ARN,
        Handler="handler.handler",
        Code={"ZipFile": zip_bytes},
        Timeout=30,
        MemorySize=512,
        Architectures=["x86_64"],
        Environment={"Variables": environment()},
        Description="Secure file sharing for wecare.digital/get/secure",
    )
    client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
    return "created"


def ensure_alias(dry_run: bool) -> str:
    """Publish a version and point ``live`` at it.

    The HTTP API integrates with the alias, not ``$LATEST``, so nothing reaches
    production until this runs. See .kiro/steering/lambda-snapstart-deploy.md.
    """
    if dry_run:
        return "would publish and move alias"
    client = lam()
    version = client.publish_version(FunctionName=FUNCTION_NAME)["Version"]
    try:
        client.update_alias(
            FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version
        )
        return f"alias moved -> v{version}"
    except client.exceptions.ResourceNotFoundException:
        client.create_alias(
            FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version
        )
        return f"alias created -> v{version}"


# ── API Gateway ───────────────────────────────────────────────────────────────

def ensure_routes(dry_run: bool) -> list:
    client = api()
    alias_arn = (
        f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:{LIVE_ALIAS}"
    )
    results = []

    existing_routes = {}
    token = None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            kwargs["NextToken"] = token
        page = client.get_routes(**kwargs)
        for route in page.get("Items", []):
            existing_routes[route["RouteKey"]] = route
        token = page.get("NextToken")
        if not token:
            break

    if dry_run:
        for method, path in ROUTES:
            key = f"{method} {path}"
            results.append(f"{key}: {'exists' if key in existing_routes else 'would create'}")
        return results

    integration_id = client.create_integration(
        ApiId=API_ID,
        IntegrationType="AWS_PROXY",
        IntegrationUri=alias_arn,
        PayloadFormatVersion="2.0",
        IntegrationMethod="POST",
    )["IntegrationId"]
    target = f"integrations/{integration_id}"

    # one permission for the whole API, so every route can invoke the alias
    try:
        lam().add_permission(
            FunctionName=f"{FUNCTION_NAME}:{LIVE_ALIAS}",
            StatementId="apigw-secure-files",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*",
        )
    except lam().exceptions.ResourceConflictException:
        pass

    for method, path in ROUTES:
        key = f"{method} {path}"
        if key in existing_routes:
            client.update_route(
                ApiId=API_ID, RouteId=existing_routes[key]["RouteId"], Target=target
            )
            results.append(f"{key}: retargeted")
        else:
            client.create_route(ApiId=API_ID, RouteKey=key, Target=target)
            results.append(f"{key}: created")
    return results


# ── revoke the webhook's grants-table access ──────────────────────────────────

def ensure_webhook_access(dry_run: bool) -> str:
    """Take the grants table away from wecare-razorpay-webhook.

    This used to do the opposite: it granted the webhook ``dynamodb:Query`` and
    ``dynamodb:UpdateItem`` on the grants table plus a ``DOWNLOAD_GRANTS_TABLE`` env var,
    because the webhook itself flipped a grant to ``paid``.

    It no longer does. A valid webhook signature is no longer proof of payment - the
    webhook only forwards an order id, and ``secure-files`` asks Razorpay's API whether
    money actually moved. So this permission is not merely unused, it is the permission a
    forged callback would have needed. Removing it makes the code change enforceable at
    the IAM layer: even if a future edit reintroduced the write, the role could not
    perform it.

    Proven safe before removal, because ``wecare-digital-lambda-role`` is shared by 61
    functions: the webhook was the only consumer of this policy on that role.
    ``wecare-secure-files`` and ``wecare-customer-whatsapp-auth`` each have their own
    role, each with its own narrower grants-table policy, and neither is touched here.
    """
    client = lam()
    try:
        config = client.get_function_configuration(FunctionName=WEBHOOK_FUNCTION)
    except client.exceptions.ResourceNotFoundException:
        return f"{WEBHOOK_FUNCTION} not found - skipped"

    variables = dict((config.get("Environment") or {}).get("Variables") or {})
    role_name = config["Role"].rsplit("/", 1)[-1]
    actions = []

    if "DOWNLOAD_GRANTS_TABLE" in variables:
        if dry_run:
            actions.append("would drop DOWNLOAD_GRANTS_TABLE env")
        else:
            variables.pop("DOWNLOAD_GRANTS_TABLE")
            client.update_function_configuration(
                FunctionName=WEBHOOK_FUNCTION, Environment={"Variables": variables}
            )
            client.get_waiter("function_updated_v2").wait(FunctionName=WEBHOOK_FUNCTION)
            actions.append("dropped DOWNLOAD_GRANTS_TABLE env")
    else:
        actions.append("env already clean")

    if dry_run:
        actions.append(f"would delete wecare-download-grants from {role_name}")
        return "; ".join(actions)

    try:
        iam().delete_role_policy(
            RoleName=role_name, PolicyName="wecare-download-grants"
        )
        actions.append(f"revoked grants policy on {role_name}")
    except iam().exceptions.NoSuchEntityException:
        actions.append("grants policy already absent")

    # The webhook still needs to reach secure-files to forward the order id. That grant
    # is separate and stays.
    iam().put_role_policy(
        RoleName=role_name,
        PolicyName="wecare-invoke-secure-files",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "InvokeSecureFiles",
                        "Effect": "Allow",
                        "Action": ["lambda:InvokeFunction"],
                        "Resource": [
                            f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}",
                            f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:*",
                        ],
                    }
                ],
            }
        ),
    )
    actions.append("invoke-secure-files policy confirmed")
    return "; ".join(actions)


# ── verify ────────────────────────────────────────────────────────────────────

def verify() -> int:
    failures = 0
    client = lam()

    try:
        config = client.get_function_configuration(
            FunctionName=f"{FUNCTION_NAME}:{LIVE_ALIAS}"
        )
        print(f"PASS {FUNCTION_NAME}:{LIVE_ALIAS} {config['Runtime']} {config['State']}")
        variables = (config.get("Environment") or {}).get("Variables") or {}

        # Reported, not judged. Once the owner enables payments deliberately, a
        # verifier that fails because of it is a verifier people learn to ignore.
        if variables.get("SECURE_FILES_PAYMENT_ENABLED", "").lower() in ("1", "true", "yes", "on"):
            print("INFO payment flag is ON - paid downloads are live, real money moves")
        else:
            print("PASS payment flag off - the order route refuses")

        for key in ("SECURE_FILES_BUCKET", "SECURE_FILES_TABLE", "DOWNLOAD_GRANTS_TABLE",
                    "CUSTOMER_USER_POOL_ID", "RAZORPAY_SECRET_ID"):
            if variables.get(key):
                print(f"PASS env {key}")
            else:
                print(f"FAIL env {key} missing")
                failures += 1

        # a credential must never be an env var, only a secret NAME
        for key, value in variables.items():
            if value.startswith("rzp_") or value.startswith("sk_"):
                print(f"FAIL env {key} looks like a credential value")
                failures += 1
    except client.exceptions.ResourceNotFoundException:
        print(f"FAIL {FUNCTION_NAME}:{LIVE_ALIAS} missing")
        failures += 1

    routes = set()
    token = None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            kwargs["NextToken"] = token
        page = api().get_routes(**kwargs)
        routes.update(r["RouteKey"] for r in page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            break

    for method, path in ROUTES:
        key = f"{method} {path}"
        if key in routes:
            print(f"PASS route {key}")
        else:
            print(f"FAIL route {key} missing")
            failures += 1

    # The webhook must NOT be able to write a grant. This assertion is inverted from what
    # it used to be, on purpose: a valid signature is no longer proof of payment, so the
    # ability to mark a grant paid is precisely what a forged callback would need.
    try:
        webhook = client.get_function_configuration(FunctionName=WEBHOOK_FUNCTION)
        variables = (webhook.get("Environment") or {}).get("Variables") or {}
        if "DOWNLOAD_GRANTS_TABLE" in variables:
            print("FAIL webhook still carries DOWNLOAD_GRANTS_TABLE")
            failures += 1
        else:
            print("PASS webhook has no grants-table env var")

        role_name = webhook["Role"].rsplit("/", 1)[-1]
        try:
            iam().get_role_policy(
                RoleName=role_name, PolicyName="wecare-download-grants"
            )
            print(f"FAIL {role_name} still grants the webhook grants-table write access")
            failures += 1
        except iam().exceptions.NoSuchEntityException:
            print(f"PASS {role_name} cannot write grants")

        # It does still need to forward the order id.
        try:
            iam().get_role_policy(
                RoleName=role_name, PolicyName="wecare-invoke-secure-files"
            )
            print("PASS webhook may invoke secure-files")
        except iam().exceptions.NoSuchEntityException:
            print("FAIL webhook cannot invoke secure-files - confirmations will not land")
            failures += 1
    except client.exceptions.ResourceNotFoundException:
        print(f"FAIL {WEBHOOK_FUNCTION} missing")
        failures += 1

    print()
    print("secure files API verified" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # DRY RUN IS THE DEFAULT, and `--apply` is the only way to write.
    #
    # It used to be the other way round: `--dry-run` was opt-in, so a bare invocation
    # refreshed the role policy, uploaded code, published a version and MOVED THE LIVE
    # ALIAS. On 2026-10-07 that is exactly what happened - the command was run from a build
    # loop with no flag and put unmerged worktree code behind `wecare-secure-files:live`
    # for about six minutes across ten writes (recorded in
    # docs/execution/change-authority-matrix.md). Nothing about the script said it would.
    #
    # Every other provisioning habit in this repo trains the opposite expectation
    # (`terraform plan`, `cdk synth`, `sam build`, `deploy_all_lambdas.py --dry-run`), so
    # the default is now the safe direction and the dangerous one has to be typed.
    # `--dry-run` is still accepted, and still means what it says, so every recorded
    # command and every habit keeps working.
    ap.add_argument("--apply", action="store_true",
                    help="actually write: refresh the role policy, upload code, publish a "
                         "version and MOVE THE LIVE ALIAS. Without it this is a dry run.")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicitly report the delta and change nothing. The default, "
                         "kept so an existing command keeps meaning what it meant.")
    ap.add_argument("--verify", action="store_true")
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--enable-payment",
        action="store_true",
        help="turn paid downloads ON: sets the flag, publishes a version and moves "
             "the live alias. Real money starts moving.",
    )
    group.add_argument(
        "--disable-payment",
        action="store_true",
        help="turn paid downloads OFF again (the safe direction).",
    )
    args = ap.parse_args(argv)

    if args.verify:
        return verify()
    if args.enable_payment:
        return set_payment_flag(True)
    if args.disable_payment:
        return set_payment_flag(False)

    if args.apply and args.dry_run:
        # Refuse rather than pick one. Both flags together means the caller does not know
        # which they want, and guessing in either direction is worse than stopping.
        print("--apply and --dry-run contradict each other; pass one")
        return 2
    dry_run = not args.apply

    print(f"region: {REGION}  api: {API_ID}")
    print(f"dry run: {dry_run}\n")
    print(f"role: {ensure_role(dry_run)}")
    zip_bytes = package()
    print(f"package: {len(zip_bytes)} bytes")
    print(f"function: {ensure_function(zip_bytes, dry_run)}")
    print(f"alias: {ensure_alias(dry_run)}")
    for line in ensure_routes(dry_run):
        print(f"route {line}")
    print(f"webhook: {ensure_webhook_access(dry_run)}")

    if dry_run:
        print("\ndry run: nothing changed  (pass --apply to write)")
        return 0

    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
