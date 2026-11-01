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
  **read** exactly one public prefix, ``secure/d/public/whatsapp/incoming/*``, because a
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
PUBLIC_WHATSAPP_INCOMING_PREFIX = "secure/d/public/whatsapp/incoming/"
FILES_TABLE = "stack-wecare-digital-SecureFilesTable"
GRANTS_TABLE = "stack-wecare-digital-DownloadGrantsTable"
REQUESTS_TABLE = "stack-wecare-digital-ServiceRequestsTable"
DOCUMENTS_TABLE = "stack-wecare-digital-DocumentTable"
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"
ADMIN_POOL_ID = "us-east-1_cSx0RHCIR"
META_WABA_ID = "2094615664435155"
# The API key pair lives here. wecare/razorpay-webhook holds only webhook_secret
# and never the pair - reading the pair from it is the bug that returned 501 on
# every customer-service top-up. See amplify/functions/core/secure-files/razorpay_orders.py
RAZORPAY_SECRET_NAME = "wecare/razorpay/api"
ASYNC_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCOUNT}:wecare-lambda-async-dlq"

WEBHOOK_FUNCTION = "wecare-razorpay-webhook"

ROUTES = [
    # admin surface (authorised inside the handler via require_auth Operator)
    ("GET", "/secure-files"),
    # Staff Vault-only intake; feature-flagged OFF until deployed edge deny is verified.
    ("POST", "/secure-files/upload-init"),
    ("POST", "/secure-files/{fileId}/confirm"),
    ("GET", "/secure-files/{fileId}/staff-download"),
    # Historical clients get a 410 tombstone from the handler. Never publish
    # customer Drop Docs uploads as new staff Vault files.
    ("POST", "/secure-files/publish-document"),
    ("POST", "/secure-files/{fileId}/revoke"),
    # Direct owner-bound native Review & Pay, staff-only media preview and paid access resend.
    ("POST", "/secure-files/{fileId}/request-payment"),
    ("GET", "/secure-files/payment-media-preview"),
    ("GET", "/secure-files/{fileId}/message-log"),
    ("GET", "/secure-files/{fileId}/schedules"),
    ("POST", "/secure-files/{fileId}/schedules"),
    ("DELETE", "/secure-files/{fileId}/schedules/{scheduleId}"),
    ("POST", "/secure-files/{fileId}/send-access"),
    # customer surface (customer-pool token, checked inside the handler)
    ("GET", "/secure-files/mine"),
    ("GET", "/secure-files/{fileId}/download"),
    # Drop Docs: promote a document into secure/ and register it against a paid request,
    # and read back the caller's own documents for one request. Both flag-gated OFF by
    # DROPDOCS_ATTACH_ENABLED; the routes exist so the flag has something to switch. The
    # `dropdocs` segment is literal, so neither collides with the {fileId} routes above.
    ("POST", "/secure-files/dropdocs/attach"),
    ("GET", "/secure-files/dropdocs/{requestId}/documents"),
]

# Routes retired from the product boundary. The provisioner deletes these explicitly;
# merely removing them from ROUTES would leave them live in API Gateway forever.
RETIRED_ROUTES = {
    "POST /secure-files/{fileId}/send-offer",
}


# The two explicit WhatsApp capabilities secure-files may invoke: delivery of Access Vault and
# the native Vault payment orchestrator. No wildcard Lambda invoke permission is allowed.
WA_SENDER = "wecare-outbound-whatsapp"
VAULT_PAYMENT_FUNCTION = "wecare-whatsapp-business-api"

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
                "Sid": "SecureBucketExistenceProbe",
                "Effect": "Allow",
                # HeadObject returns 403 rather than 404 for an absent key when the
                # caller cannot ListBucket. Logs need to distinguish Missing from
                # Unknown, so allow only existence checks under the secure/ prefix.
                "Action": ["s3:ListBucket"],
                "Resource": f"arn:aws:s3:::{BUCKET}",
                "Condition": {
                    "StringLike": {
                        "s3:prefix": [f"{SECURE_PREFIX}*"],
                    },
                },
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
                "Sid": "ReadNativeVaultPaymentSendId",
                "Effect": "Allow",
                # The GSI projects the primary key but not the message ID.
                # Exact GetItem only; no scans or writes.
                "Action": ["dynamodb:GetItem"],
                "Resource": (
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/"
                    "stack-wecare-digital-WhatsAppOutboundTable"
                ),
            },
            {
                "Sid": "ReadPaidVaultJourneyLogs",
                "Effect": "Allow",
                # Read-only GSI/PK queries bound to a verified paid entitlement.
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-"
                    "WhatsAppOutboundTable/index/paymentReferenceId-index",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-"
                    "InvoicesTable/index/referenceId-index",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-"
                    "InvoiceDeliveryLogTable",
                ],
            },
            {
                "Sid": "VaultScheduledMessages",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem",
                           "dynamodb:UpdateItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-ScheduledMessagesTable",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-SecureFilesTable",
                ],
            },
            {
                "Sid": "ValidateVaultOfferCatalogPrice",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-ProductsTable",
            },
            {
                "Sid": "ReadVerifiedWhatsAppMessageStatus",
                "Effect": "Allow",
                # ONLY status lookups by server-recorded provider message IDs;
                # never permit a scan or a customer-supplied phone search.
                "Action": ["dynamodb:Query"],
                "Resource": (
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/"
                    "stack-wecare-digital-MessagesTable/index/whatsappMessageId-index"
                ),
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
                "Sid": "DropDocsDocumentBridge",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{DOCUMENTS_TABLE}",
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
                # Named individually rather than a wildcard: this role may deliver the Access
                # Vault template and ask the existing business-api service rail to send native
                # Review and Pay. It may not invoke the rest of the fleet.
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_SENDER}",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{WA_SENDER}:*",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{VAULT_PAYMENT_FUNCTION}",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{VAULT_PAYMENT_FUNCTION}:*",
                ],
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION_NAME}:*",
            },
            {
                "Sid": "XRayWrite",
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                ],
                "Resource": "*",
            },
            {
                "Sid": "AsyncFailureDestination",
                "Effect": "Allow",
                "Action": ["sqs:SendMessage"],
                "Resource": ASYNC_DLQ_ARN,
            },
        ],
    }



def legacy_media_write_guard_policy() -> dict:
    """Keep historical prefixes readable where needed, but never writable."""
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "DenyLegacyMediaWrites",
            "Effect": "Deny",
            "Action": ["s3:PutObject", "s3:DeleteObject"],
            "Resource": [
                f"arn:aws:s3:::{BUCKET}/secure/Invoice/customer_invoice/*",
                f"arn:aws:s3:::{BUCKET}/secure/Invoice/fonts/*",
                f"arn:aws:s3:::{BUCKET}/o/stack/whatsapp-media/*",
                f"arn:aws:s3:::{BUCKET}/stack/whatsapp-media/*",
            ],
        }],
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
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="LegacyMediaWriteGuard",
        PolicyDocument=json.dumps(legacy_media_write_guard_policy()),
    )
    return "created" if not exists else "policy refreshed"


# ── packaging ─────────────────────────────────────────────────────────────────

def package() -> bytes:
    """handler.py + settlement compatibility + lambda_utils/, deterministically."""
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


def environment() -> dict:
    # AWS_REGION is deliberately absent: Lambda reserves it and rejects it.
    return {
        "SECURE_FILES_BUCKET": BUCKET,
        "SECURE_FILES_TABLE": FILES_TABLE,
        "DOCUMENTS_TABLE": DOCUMENTS_TABLE,
        "DOWNLOAD_GRANTS_TABLE": GRANTS_TABLE,
        "CUSTOMER_USER_POOL_ID": CUSTOMER_POOL_ID,
        "COGNITO_USER_POOL_ID": ADMIN_POOL_ID,  # require_auth resolves admins here
        "META_WABA_ID": META_WABA_ID,
        # Meta's OWN phone-number id; the handler derives the customer's WABA stamp from it.
        # It is NOT a valid `phoneNumberId` for `wecare-outbound-whatsapp`.
        "META_PHONE_NUMBER_ID": "1016149501586345",
        # The AWS-style sender id outbound-whatsapp requires for secure-file delivery.
        "WA_SEND_PHONE_ID": "phone-number-id-waba1-direct-1016149501586345",
        "PARTNER_GROUP": "Partner",
        # Secure-files owns document delivery only; payment templates belong to commerce.
        # Every paid file is announced with the approved `wecare_default_download` template
        # (lambda_utils.whatsapp_templates), so no template name, media uploader or WhatsApp
        # link TTL is configured here. `wd_file_delivery` is not on WABA1 (readback 2026-10-25).
        # Explicit live aliases, never $LATEST's unpublished code. secure-files does not build
        # payment details; the business-api/commerce native rail still owns that work.
        "WA_SENDER_FUNCTION": f"{WA_SENDER}:live",
        "VAULT_PAYMENT_FUNCTION": f"{VAULT_PAYMENT_FUNCTION}:live",
        # Web redeem: a browser follows it instantly. The only presigned link issued.
        "DOWNLOAD_URL_TTL_SECONDS": "60",
        # OTP_PROBE_* deliberately absent. The enumeration budget is enforced in
        # wecare-customer-whatsapp-auth, which is the only function that reads those
        # keys; they are provisioned there by provision_customer_whatsapp_auth.py.
        "UPLOAD_URL_TTL_SECONDS": "900",
        # Never turn this on until Lambda@Edge LIVE blocks secure/d/public/valut/.
        "VAULT_DIRECT_UPLOAD_ENABLED": "false",
        "GRANT_TTL_SECONDS": "1800",
        # Vault access window: ₹49 buys one window of this many hours (free re-downloads
        # inside it); after it closes it is ₹49 again for a new window on the same durable
        # entitlement. Grace is added to the OPEN check only, so a boundary download is not
        # cut off by clock skew.
        "VAULT_ACCESS_WINDOW_HOURS": "24",
        "VAULT_ACCESS_WINDOW_GRACE_SECONDS": "300",
        # The Phase O-1 request store. A Drop Docs document is registered against a REQ#
        # row there, not in SecureFilesTable.
        "SERVICE_REQUESTS_TABLE": REQUESTS_TABLE,
        # Drop Docs document attach. Ships OFF and stays off: there is no upload UI in
        # Phase O-2, so the only thing turning this on would do is open a route nothing calls.
        "DROPDOCS_ATTACH_ENABLED": "false",
        # A secret NAME, never a value. See .kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md).
        "RAZORPAY_SECRET_ID": RAZORPAY_SECRET_NAME,
    }


def ensure_function(zip_bytes: bytes, dry_run: bool) -> str:
    client = lam()
    try:
        client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except client.exceptions.ResourceNotFoundException:
        exists = False

    if dry_run:
        return "exists (would update)" if exists else "would create"

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
            TracingConfig={"Mode": "Active"},
            Environment={"Variables": environment()},
        )
        client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        return "updated"

    client.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.12",
        Role=ROLE_ARN,
        Handler="handler.handler",
        Code={"ZipFile": zip_bytes},
        Timeout=30,
        MemorySize=512,
        Architectures=["x86_64"],
        TracingConfig={"Mode": "Active"},
        Environment={"Variables": environment()},
        Description="Secure file sharing for wecare.digital/get/secure",
    )
    client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
    return "created"


def ensure_alias(dry_run: bool) -> str:
    """Publish a version and point ``live`` at it.

    The HTTP API integrates with the alias, not ``$LATEST``, so nothing reaches
    production until this runs. See .kiro/steering/lambda-snapstart-deploy.md (retired 2026-10-09, af7858fa).
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


def ensure_async_failure_destination(dry_run: bool) -> str:
    """Persist exhausted async paid-delivery events to the standard Lambda DLQ.

    Razorpay invokes this function with InvocationType=Event for historical secure-file
    settlement. Keep Lambda's normal retry/age semantics (2 retries, 6 hours), but never
    discard the final event after retries are exhausted.
    """
    if dry_run:
        try:
            current = lam().get_function_event_invoke_config(
                FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)
            dest = ((current.get("DestinationConfig") or {}).get("OnFailure") or {}).get(
                "Destination")
            return "configured" if dest == ASYNC_DLQ_ARN else "would configure async DLQ"
        except lam().exceptions.ResourceNotFoundException:
            return "would configure async DLQ"

    lam().put_function_event_invoke_config(
        FunctionName=FUNCTION_NAME,
        Qualifier=LIVE_ALIAS,
        MaximumRetryAttempts=2,
        MaximumEventAgeInSeconds=21600,
        DestinationConfig={"OnFailure": {"Destination": ASYNC_DLQ_ARN}},
    )
    return "async failures -> wecare-lambda-async-dlq"


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
        for key in sorted(RETIRED_ROUTES):
            if key in existing_routes:
                results.append(f"{key}: would delete (retired)")
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

    for key in sorted(RETIRED_ROUTES):
        route = existing_routes.get(key)
        if route:
            client.delete_route(ApiId=API_ID, RouteId=route["RouteId"])
            results.append(f"{key}: deleted (retired)")

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
        if (config.get("TracingConfig") or {}).get("Mode") == "Active":
            print("PASS X-Ray tracing Active")
        else:
            print("FAIL X-Ray tracing is not Active")
            failures += 1
        variables = (config.get("Environment") or {}).get("Variables") or {}
        if variables.get("VAULT_DIRECT_UPLOAD_ENABLED", "false").lower() not in ("false", "true"):
            print("FAIL invalid VAULT_DIRECT_UPLOAD_ENABLED value")
            failures += 1

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

    for key in sorted(RETIRED_ROUTES):
        if key in routes:
            print(f"FAIL retired route still live: {key}")
            failures += 1
        else:
            print(f"PASS retired route absent: {key}")

    try:
        async_cfg = client.get_function_event_invoke_config(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)
        destination = (
            ((async_cfg.get("DestinationConfig") or {}).get("OnFailure") or {})
            .get("Destination")
        )
        if (destination == ASYNC_DLQ_ARN
                and async_cfg.get("MaximumRetryAttempts") == 2
                and async_cfg.get("MaximumEventAgeInSeconds") == 21600):
            print("PASS async failures persist to standard DLQ")
        else:
            print("FAIL async failure destination/retry contract differs")
            failures += 1
    except client.exceptions.ResourceNotFoundException:
        print("FAIL async failure destination missing")
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
    args = ap.parse_args(argv)

    if args.verify:
        return verify()
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
    print(f"async failure destination: {ensure_async_failure_destination(dry_run)}")
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
