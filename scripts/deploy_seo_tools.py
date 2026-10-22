"""Deploy the wecare-seo-tools Lambda + SeoToolsTable via boto3 (Docker-free).

Mirrors amplify/seo-resources.ts but deploys directly — like scripts/deploy_task12.py —
because CI builds frontend only and does NOT run `ampx pipeline-deploy`. The Gen2
backend + 42+ Lambdas are all managed this way and already exist in AWS.

Idempotent: safe to re-run. Creates on first run, updates code+config afterward.

What it does:
  1. Create DynamoDB `stack-wecare-digital-SeoToolsTable` (PK id, 2 GSIs, PAY_PER_REQUEST, PITR).
  2. Add an additive Bedrock inference-profile inline policy to the shared lambda role
     (ai.py uses cross-region `global.anthropic.*` profiles the role didn't cover).
  3. Package the Lambda (shim + operations/seo-tools + shared/lambda_utils) and
     create/update `wecare-seo-tools` (python3.12, handler seo_tools_handler.handler).

Usage:  python scripts/deploy_seo_tools.py
"""
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Dict

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_DIR = ROOT / "amplify" / "functions"

FUNCTION_NAME = "wecare-seo-tools"
TABLE_NAME = "stack-wecare-digital-SeoToolsTable"
DEDUP_TABLE = "stack-wecare-digital-WebhookDedup"
ROLE_NAME = "wecare-digital-lambda-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
FUNCTION_TIMEOUT = 120

# HTTP API behind wecare.digital/api (stage prod, AutoDeploy on).
# Frontend calls https://wecare.digital/api/seo-tools/{route} (src/api/seo.ts).
API_ID = "zllr9lrg7j"

ENV_VARS = {
    "LOG_LEVEL": "INFO",
    "SEO_TOOLS_TABLE": TABLE_NAME,
    "WEBHOOK_DEDUP_TABLE": DEDUP_TABLE,
    "BEDROCK_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
    "COGNITO_USER_POOL_ID": "us-east-1_cSx0RHCIR",    # Derived-SEO cost/AI posture (seo_config.py). FREE + AI off is the fail-safe default the
    # brief mandates: the deterministic engine and the scheduled freshness check need none of
    # these on, and a public read path must never be one typo from a model call. seo_config
    # additionally requires ENABLE_BEDROCK_ASSIST for AI, so either flag off is sufficient to
    # force deterministic behaviour. Change COST_MODE/AI_ENABLED here to opt in deliberately.
    "COST_MODE": "FREE",
    "AI_ENABLED": "false",
    "FAQ_AI_GENERATION": "false",
}


def ensure_table() -> None:
    ddb = boto3.client("dynamodb", region_name=REGION)
    try:
        ddb.describe_table(TableName=TABLE_NAME)
        print(f"[table] {TABLE_NAME} already exists — skipping create")
        return
    except ddb.exceptions.ResourceNotFoundException:
        pass

    print(f"[table] creating {TABLE_NAME} ...")
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "recordType", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
            {"AttributeName": "slug", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "recordType-createdAt-index",
                "KeySchema": [
                    {"AttributeName": "recordType", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "slug-createdAt-index",
                "KeySchema": [
                    {"AttributeName": "slug", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    ddb.update_continuous_backups(
        TableName=TABLE_NAME,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )
    print(f"[table] {TABLE_NAME} ACTIVE with PITR enabled")


def ensure_bedrock_inference_profile_perms() -> None:
    """Additive inline policy so ai.py's cross-region `global.*` profiles can invoke."""
    iam = boto3.client("iam")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockInferenceProfiles",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": [
                    f"arn:aws:bedrock:*:{ACCOUNT}:inference-profile/*",
                    f"arn:aws:bedrock:*:{ACCOUNT}:application-inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*",
                ],
            }
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="seo-bedrock-inference-profiles",
        PolicyDocument=json.dumps(policy),
    )
    print(f"[iam] ensured inline policy seo-bedrock-inference-profiles on {ROLE_NAME}")


def ensure_freshness_schedule() -> None:
    """Create/update the daily freshness schedule and its narrowly-scoped role. Idempotent.

    Provisions:
      1. An execution role assumable ONLY by scheduler.amazonaws.com, whose single inline
         policy allows lambda:InvokeFunction on THIS function alone.
      2. An EventBridge Scheduler schedule invoking the function daily with
         {"seoFreshness": true}, FLEXIBLE off (exact time), retries bounded.
    """
    iam = boto3.client("iam")
    scheduler = boto3.client("scheduler", region_name=REGION)
    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"

    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"},
            "Action": "sts:AssumeRole",
            #: Confused-deputy guard: only THIS account's scheduler may assume the role.
            "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}},
        }],
    }
    try:
        iam.create_role(
            RoleName=SCHEDULE_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Invoke wecare-seo-tools for the daily derived-SEO freshness check.",
        )
        print(f"[schedule] created role {SCHEDULE_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        iam.update_assume_role_policy(
            RoleName=SCHEDULE_ROLE_NAME, PolicyDocument=json.dumps(trust))
        print(f"[schedule] role {SCHEDULE_ROLE_NAME} exists — trust refreshed")

    iam.put_role_policy(
        RoleName=SCHEDULE_ROLE_NAME,
        PolicyName="invoke-seo-tools",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "InvokeSeoTools",
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": fn_arn,
            }],
        }),
    )
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{SCHEDULE_ROLE_NAME}"
    print(f"[schedule] scoped invoke policy on {SCHEDULE_ROLE_NAME} -> {FUNCTION_NAME} only")

    target = {
        "Arn": fn_arn,
        "RoleArn": role_arn,
        "Input": json.dumps({"seoFreshness": True}),
        #: A daily maintenance sweep that fails should wait for tomorrow, not hammer retries.
        "RetryPolicy": {"MaximumRetryAttempts": 2},
    }
    common = dict(
        ScheduleExpression=SCHEDULE_EXPRESSION,
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        State="ENABLED",
        Description="Daily derived-SEO freshness check (sourceHash-gated, deterministic).",
        Target=target,
    )
    #: IAM role creation is eventually consistent, and Scheduler VALIDATES the trust
    #: relationship at create/update time - so a schedule created in the same breath as its role
    #: fails with "must allow AWS EventBridge Scheduler to assume the role" until the role has
    #: propagated. Retry that specific ValidationException with backoff; anything else raises.
    def _put_schedule(op):
        for attempt in range(6):
            try:
                op(Name=SCHEDULE_NAME, **common)
                return
            except scheduler.exceptions.ValidationException as exc:
                if "assume the role" not in str(exc) or attempt == 5:
                    raise
                wait = 2 ** attempt
                print(f"[schedule] role not yet propagated, retrying in {wait}s")
                time.sleep(wait)

    try:
        _put_schedule(scheduler.create_schedule)
        print(f"[schedule] created {SCHEDULE_NAME} ({SCHEDULE_EXPRESSION} UTC)")
    except scheduler.exceptions.ConflictException:
        _put_schedule(scheduler.update_schedule)
        print(f"[schedule] updated {SCHEDULE_NAME} ({SCHEDULE_EXPRESSION} UTC)")


# ── Monitoring ──────────────────────────────────────────────────────────────────
#
# WHAT THE EXISTING ALARMS CANNOT SEE.
#
# `wecare-lambda-errors-wecare-seo-tools` already alarms on unhandled Lambda errors, and that is
# the wrong instrument for this pipeline. Every failure mode here is CAUGHT and recorded on a
# record rather than raised - one bad PDF must not stop a batch of 2,500, a failed verification is
# evidence rather than a crash, a rejected post is a defect to investigate rather than an outage.
# So a run where every document failed produces zero Lambda errors and looks, from the existing
# alarms, exactly like a run where every document succeeded.
#
# Hence a metric filter per recorded outcome, following `scripts/_create_dedup_alarm.py`: the same
# `WECARE.DIGITAL` namespace, the same `filterPattern='"event_name"'` shape, the same SNS topic all
# 61 existing alarms already route to.
#
# THE ONE DISTINCTION THAT MATTERS. Only a recorded FAILURE pages anybody. A native publish has no
# credential to revoke and no kill switch, so it is never refused: a write either PUBLISHED or
# FAILED, and `blog_publish_failed` is the native store rejecting a post, which is worth a look.
# A refusal must never be counted: paging somebody because the switch they threw is working would
# teach them to ignore the channel - which is the only thing that makes an alarm worthless.
ALARM_NAMESPACE = "WECARE.DIGITAL"
#: The topic every one of the 61 existing alarms already uses. An alarm with no action is a row in
#: a console nobody opens, so `provision_alarms` refuses to create one without it.
ALARM_TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:wecare-alarm-notifications"

#: (alarm name, log event, metric, threshold, period, description)
#:
#: Thresholds are deliberately not all zero. A single extraction failure in a 2,500-document wave
#: is ordinary - a scanned PDF with no text layer - and alarming on it would fire on every real
#: batch. Five in five minutes is a pattern. A verification failure is different: it means a LIVE
#: article does not match what was approved, and one of those is worth knowing about immediately.
LOG_ALARMS = (
    (
        "wecare-blog-extraction-failures",
        "blog_source_extraction_failed",
        "BlogExtractionFailures",
        5.0,
        300,
        ("blog_source_extraction_failed logged repeatedly - extraction is failing for a class of "
         "document, not one bad PDF. Caught and recorded, so it produces no Lambda error."),
    ),
    (
        "wecare-blog-verification-failures",
        "blog_verification_failed",
        "BlogVerificationFailures",
        0.0,
        300,
        ("blog_verification_failed logged - a LIVE article does not match what was signed off. "
         "Read the verification report; nothing retries automatically."),
    ),
    (
        "wecare-blog-publish-failures",
        "blog_publish_failed",
        "BlogPublishFailures",
        0.0,
        300,
        ("blog_publish_failed logged - the native blog store rejected a post. Recorded as "
         "FAILED; nothing retries automatically."),
    ),
)


def package() -> bytes:
    """Zip the live SEO/public-blog Lambda runtime."""
    shim = FUNCTIONS_DIR / "seo_tools_handler.py"
    seo_dir = FUNCTIONS_DIR / "operations" / "seo-tools"
    lambda_utils = FUNCTIONS_DIR / "shared" / "lambda_utils"
    for required in (shim, seo_dir, lambda_utils):
        assert required.exists(), f"missing {required}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(shim, "seo_tools_handler.py")
        for path in sorted(seo_dir.glob("*.py")):
            z.write(path, f"operations/seo-tools/{path.name}")
        z.write(ROOT / "config" / "public-pages.json",
                "operations/seo-tools/public-pages.json")
        for path in sorted(lambda_utils.glob("*.py")):
            z.write(path, f"shared/lambda_utils/{path.name}")
        skb = FUNCTIONS_DIR / "shared" / "static_knowledge_base.py"
        if skb.exists():
            z.write(skb, "shared/static_knowledge_base.py")

    data = buf.getvalue()
    print(f"[package] built zip: {len(data)} bytes")
    if len(data) > 50 * 1024 * 1024:
        raise SystemExit("package exceeds the 50MB direct-upload limit; use S3 instead")
    return data

def deploy_lambda(zip_bytes: bytes) -> None:
    lam = boto3.client("lambda", region_name=REGION)
    config = dict(
        Runtime="python3.12",
        Role=ROLE_ARN,
        Handler="seo_tools_handler.handler",
        Timeout=FUNCTION_TIMEOUT,
        MemorySize=512,
        Environment={"Variables": ENV_VARS},
    )
    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        print(f"[lambda] {FUNCTION_NAME} exists — updating code + config")
        current = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
        current_env = (current.get("Environment") or {}).get("Variables") or {}
        config["Environment"] = {"Variables": {**current_env, **ENV_VARS}}
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(FunctionName=FUNCTION_NAME, **config)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    else:
        print(f"[lambda] creating {FUNCTION_NAME}")
        lam.create_function(
            FunctionName=FUNCTION_NAME,
            Code={"ZipFile": zip_bytes},
            Architectures=["x86_64"],
            Publish=False,
            **config,
        )
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)

    cfg = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
    print(f"[lambda] {FUNCTION_NAME} {cfg['State']} / {cfg.get('LastUpdateStatus')} "
          f"(runtime={cfg['Runtime']}, mem={cfg['MemorySize']}, timeout={cfg['Timeout']})")


def ensure_api_route() -> None:
    """Wire https://wecare.digital/api/seo-tools/* -> wecare-seo-tools (idempotent)."""
    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"

    # 1) Integration (reuse if one already targets this function)
    integ_id = None
    for it in api.get_integrations(ApiId=API_ID, MaxResults="500").get("Items", []):
        if FUNCTION_NAME in (it.get("IntegrationUri") or ""):
            integ_id = it["IntegrationId"]
            break
    if integ_id:
        print(f"[api] reusing integration {integ_id}")
    else:
        integ_id = api.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=fn_arn,
            IntegrationMethod="POST",
            PayloadFormatVersion="2.0",
        )["IntegrationId"]
        print(f"[api] created integration {integ_id}")

    # 2) Routes (ANY covers GET/POST/PUT/DELETE/OPTIONS; handler does its own auth)
    target = f"integrations/{integ_id}"
    existing = {r["RouteKey"] for r in api.get_routes(ApiId=API_ID, MaxResults="1000").get("Items", [])}
    for rk in ["ANY /seo-tools", "ANY /seo-tools/{proxy+}"]:
        if rk in existing:
            print(f"[api] route exists: {rk}")
        else:
            api.create_route(ApiId=API_ID, RouteKey=rk, Target=target, AuthorizationType="NONE")
            print(f"[api] created route: {rk}")

    # 3) Allow API Gateway to invoke the Lambda
    for sid, res in [
        ("apigw-seo-tools-base", "seo-tools"),
        ("apigw-seo-tools-proxy", "seo-tools/*"),
    ]:
        try:
            lam.add_permission(
                FunctionName=FUNCTION_NAME,
                StatementId=sid,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*/{res}",
            )
            print(f"[api] added invoke permission {sid}")
        except lam.exceptions.ResourceConflictException:
            print(f"[api] invoke permission {sid} already present")


def main() -> None:
    import sys as _sys
    with_schedule = "--with-schedule" in _sys.argv[1:]
    print("=== deploy wecare-seo-tools ===")
    ensure_table()
    # Retained for the separate ai-seo-audit feature. Blog Studio/Production AI is removed.
    ensure_bedrock_inference_profile_perms()
    zip_bytes = package()
    deploy_lambda(zip_bytes)
    ensure_api_route()
    if with_schedule:
        ensure_freshness_schedule()
    else:
        print("[schedule] skipped (pass --with-schedule to create the daily freshness schedule)")
    print("=== done ===")
    print("Endpoint: https://wecare.digital/api/seo-tools/  (stage prod, auto-deploy)")


if __name__ == "__main__":
    main()
