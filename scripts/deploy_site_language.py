#!/usr/bin/env python3
"""Deploy WECARE.DIGITAL site-language Lambda and API routes.

Idempotent direct-AWS deployment, following the repository's existing model for
Python Lambdas that are not owned by Amplify Gen 2.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
API_ID = "zllr9lrg7j"  # HTTP API behind wecare.digital/api
FUNCTION_NAME = "wecare-site-language"
ROLE_NAME = "wecare-digital-lambda-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
TABLE_NAME = "stack-wecare-digital-SiteLanguageCache"
HANDLER = Path("amplify/functions/core/site-language/handler.py")

# API Gateway is pointed at this alias, never at $LATEST. Every other Lambda in
# the account follows the same convention, and it is what makes a rollback
# possible: repoint the alias at the previous version and traffic moves with it.
ALIAS_NAME = "live"

# Browser origins allowed to call the service. This AWS service exists because the
# Cloud Run language relay answers a 403 to this site's origins.
#
# retired-legacy-host.invalid was dropped when that hostname was retired - Amplify serves
# the apex directly and the subdomain was only a 301 to it. A redirecting host
# cannot be a useful allowed origin anyway: the browser compares the literal
# request origin and never follows a redirect to satisfy CORS.
ALLOWED_ORIGINS = [
    "https://wecare.digital",
    "https://www.wecare.digital",
]

# Throttle applied to the site-language routes ONLY.
SITE_LANGUAGE_RATE_LIMIT = 15.0
SITE_LANGUAGE_BURST_LIMIT = 30

# Translation provider. "auto" prefers Google Cloud Translation when the key below
# resolves and falls back to Amazon Translate when it does not, so this deploys
# safely whether or not the key has been provisioned or the API enabled.
TRANSLATE_PROVIDER = "auto"

# The id that ALREADY holds the unified Google API key in this account - see the
# google-cloud entry in scripts/store_provider_secret.py. Deliberately not a new
# wecare/google-translate id: a parallel copy means rotation updates one and
# consumers keep reading the other.
GOOGLE_SECRET_NAME = "wecare/google/cloud"


def ensure_table() -> None:
    ddb = boto3.client("dynamodb", region_name=REGION)
    try:
        ddb.describe_table(TableName=TABLE_NAME)
        print(f"[ddb] table exists: {TABLE_NAME}")
    except ddb.exceptions.ResourceNotFoundException:
        ddb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "cacheKey", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "cacheKey", "KeyType": "HASH"}],
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        print(f"[ddb] created: {TABLE_NAME}")

    ttl = ddb.describe_time_to_live(TableName=TABLE_NAME).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("ENABLED", "ENABLING"):
        ddb.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
        print("[ddb] enabled TTL on expiresAt")


def ensure_role_policy() -> None:
    iam = boto3.client("iam", region_name=REGION)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["translate:ListLanguages", "translate:TranslateText"],
                "Resource": "*",
            },
            {
                # Amazon Translate implements SourceLanguageCode="auto" by
                # calling Comprehend on the caller's behalf, so auto-detect
                # fails with AccessDenied without this. Deep testing caught it:
                # every request that omitted sourceLanguage returned 500.
                "Effect": "Allow",
                "Action": ["comprehend:DetectDominantLanguage"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["polly:DescribeVoices", "polly:SynthesizeSpeech"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE_NAME}",
            },
            {
                # Google Cloud Translation key, read at request time and cached in
                # the container. Scoped to this one secret by ARN: the role is
                # shared with every other Lambda in the account, so a wildcard here
                # would hand all 28 secrets to all of them. The -* suffix matches
                # the six random characters Secrets Manager appends to every ARN.
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{GOOGLE_SECRET_NAME}-*",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{FUNCTION_NAME}:*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="wecare-site-language",
        PolicyDocument=json.dumps(policy),
    )
    print(f"[iam] ensured inline policy on {ROLE_NAME}")


def package() -> bytes:
    if not HANDLER.exists():
        raise SystemExit(f"missing {HANDLER}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(HANDLER, "handler.py")
    return buffer.getvalue()


def deploy_lambda(zip_bytes: bytes) -> str:
    lam = boto3.client("lambda", region_name=REGION)
    # AWS_REGION is deliberately absent: Lambda reserves it and rejects any
    # attempt to set it. The runtime provides it, and the handler defaults to
    # us-east-1 regardless.
    env = {
        "SITE_LANGUAGE_CACHE_TABLE": TABLE_NAME,
        "SITE_LANGUAGE_ALLOWED_ORIGINS": ",".join(ALLOWED_ORIGINS),
        "SITE_LANGUAGE_CACHE_TTL_SECONDS": str(90 * 24 * 3600),
        "SITE_LANGUAGE_MAX_TEXTS": "40",
        "SITE_LANGUAGE_MAX_TEXT_BYTES": "9000",
        "SITE_LANGUAGE_MAX_TOTAL_BYTES": "30000",
        "SITE_LANGUAGE_MAX_TTS_CHARS": "2800",
        # A secret NAME, not a value. The key itself is never an env var - it is
        # fetched through the role above at request time. See
        # .kiro/steering/secret-handling.md.
        "SITE_LANGUAGE_GOOGLE_SECRET": GOOGLE_SECRET_NAME,
        "SITE_LANGUAGE_TRANSLATE_PROVIDER": TRANSLATE_PROVIDER,
    }

    try:
        current = lam.get_function(FunctionName=FUNCTION_NAME)
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes, Publish=False)
        waiter = lam.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=ROLE_ARN,
            Handler="handler.handler",
            Runtime="python3.12",
            Timeout=30,
            MemorySize=512,
            Environment={"Variables": env},
        )
        waiter.wait(FunctionName=FUNCTION_NAME)
        arn = current["Configuration"]["FunctionArn"]
        print(f"[lambda] updated {FUNCTION_NAME}")
        return arn
    except lam.exceptions.ResourceNotFoundException:
        created = lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="handler.handler",
            Code={"ZipFile": zip_bytes},
            Timeout=30,
            MemorySize=512,
            Environment={"Variables": env},
            Description="WECARE.DIGITAL dynamic site translation and Polly TTS",
            Publish=False,
        )
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
        print(f"[lambda] created {FUNCTION_NAME}")
        return created["FunctionArn"]


def ensure_alias() -> str:
    """Publish the current code and move the live alias onto it.

    A new version is only cut when $LATEST actually differs from what the alias
    already serves, so repeated deploys of unchanged code do not pile up
    versions.
    """
    lam = boto3.client("lambda", region_name=REGION)
    latest_sha = lam.get_function_configuration(FunctionName=FUNCTION_NAME)["CodeSha256"]

    current_version = None
    try:
        alias = lam.get_alias(FunctionName=FUNCTION_NAME, Name=ALIAS_NAME)
        current_version = alias["FunctionVersion"]
        served_sha = lam.get_function_configuration(
            FunctionName=FUNCTION_NAME, Qualifier=current_version
        )["CodeSha256"]
        if served_sha == latest_sha:
            print(f"[lambda] alias {ALIAS_NAME} already serves version {current_version} (code unchanged)")
            return f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:{ALIAS_NAME}"
    except lam.exceptions.ResourceNotFoundException:
        pass

    version = lam.publish_version(FunctionName=FUNCTION_NAME, CodeSha256=latest_sha)["Version"]
    if current_version is None:
        lam.create_alias(FunctionName=FUNCTION_NAME, Name=ALIAS_NAME, FunctionVersion=version)
        print(f"[lambda] created alias {ALIAS_NAME} -> version {version}")
    else:
        lam.update_alias(FunctionName=FUNCTION_NAME, Name=ALIAS_NAME, FunctionVersion=version)
        print(f"[lambda] alias {ALIAS_NAME}: version {current_version} -> {version}")
        print(f"[lambda] rollback: aws lambda update-alias --function-name {FUNCTION_NAME} "
              f"--name {ALIAS_NAME} --function-version {current_version}")
    return f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:{ALIAS_NAME}"


def ensure_api_routes(function_arn: str) -> None:
    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    integration_id = None
    for item in api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", []):
        if FUNCTION_NAME in (item.get("IntegrationUri") or ""):
            integration_id = item["IntegrationId"]
            current_uri = item.get("IntegrationUri") or ""
            break
    else:
        current_uri = ""

    if not integration_id:
        integration_id = api.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=function_arn,
            IntegrationMethod="POST",
            PayloadFormatVersion="2.0",
            TimeoutInMillis=29000,
        )["IntegrationId"]
        print(f"[api] created integration {integration_id} -> {function_arn.split(':')[-1]}")
    elif current_uri != function_arn:
        # Repoint an integration that still targets the unqualified function.
        api.update_integration(
            ApiId=API_ID, IntegrationId=integration_id, IntegrationUri=function_arn
        )
        print(f"[api] repointed integration {integration_id} at :{ALIAS_NAME}")
    else:
        print(f"[api] integration {integration_id} already targets :{ALIAS_NAME}")

    target = f"integrations/{integration_id}"
    existing = {
        row["RouteKey"]: row
        for row in api.get_routes(ApiId=API_ID, MaxResults="1000").get("Items", [])
    }
    route_keys = [
        "GET /site-language/languages",
        "POST /site-language/translate",
        # GET /site-language/voices and POST /site-language/tts are NOT listed here any
        # more. They drove Polly, had no consumer once the widget dropped read-aloud, and
        # stayed unauthenticated and billable. The handler 404s both paths now.
        # NOTE: this list only CREATES routes; it does not delete. The two existing routes
        # must be removed from the API by hand or they keep pointing at a handler that
        # refuses them - a 404 rather than a charge, but still a live surface.
        "OPTIONS /site-language/{proxy+}",
    ]
    for route_key in route_keys:
        if route_key not in existing:
            api.create_route(ApiId=API_ID, RouteKey=route_key, Target=target, AuthorizationType="NONE")
            print(f"[api] created route: {route_key}")
        else:
            print(f"[api] route exists: {route_key}")

    # Limit public spend at the API layer as a second guard behind the request
    # size caps in the handler.
    #
    # This MUST be per-route. DefaultRouteSettings is the fallback for every
    # route on the stage, and prod currently serves 100 rps / burst 200 across
    # WhatsApp inbound, Razorpay webhooks, SMS and voice. Lowering the default
    # to protect one new endpoint would throttle all of production by 85%.
    stage = api.get_stage(ApiId=API_ID, StageName="prod")
    existing_settings = dict(stage.get("RouteSettings") or {})
    desired = dict(existing_settings)
    for route_key in route_keys:
        desired[route_key] = {
            **(existing_settings.get(route_key) or {}),
            "ThrottlingBurstLimit": SITE_LANGUAGE_BURST_LIMIT,
            "ThrottlingRateLimit": SITE_LANGUAGE_RATE_LIMIT,
        }

    if desired != existing_settings:
        api.update_stage(ApiId=API_ID, StageName="prod", RouteSettings=desired)
        print(
            f"[api] throttled the {len(route_keys)} site-language routes to "
            f"{SITE_LANGUAGE_RATE_LIMIT:g} rps / burst {SITE_LANGUAGE_BURST_LIMIT}"
        )
    else:
        print("[api] per-route throttling already in place")

    default_settings = stage.get("DefaultRouteSettings") or {}
    print(
        "[api] stage default left untouched at "
        f"{default_settings.get('ThrottlingRateLimit')} rps / "
        f"burst {default_settings.get('ThrottlingBurstLimit')}"
    )

    # An alias needs its own resource policy; a grant on the unqualified
    # function does not cover invocations through :live.
    source_arn = f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*/site-language/*"
    for qualifier, sid in ((f"{FUNCTION_NAME}:{ALIAS_NAME}", "apigw-site-language-live"),
                           (FUNCTION_NAME, "apigw-site-language")):
        try:
            lam.add_permission(
                FunctionName=qualifier,
                StatementId=sid,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=source_arn,
            )
            print(f"[lambda] granted API Gateway invoke on {qualifier}")
        except lam.exceptions.ResourceConflictException:
            print(f"[lambda] invoke permission already present on {qualifier}")


def main() -> None:
    print("=== deploy WECARE site language ===")
    ensure_table()
    ensure_role_policy()
    # IAM policy propagation can be briefly eventual after first creation/update.
    time.sleep(2)
    deploy_lambda(package())
    alias_arn = ensure_alias()
    ensure_api_routes(alias_arn)
    print("=== done ===")
    print("Endpoints: https://wecare.digital/api/site-language/*")
    print(f"Serving via alias {FUNCTION_NAME}:{ALIAS_NAME}")


if __name__ == "__main__":
    main()
