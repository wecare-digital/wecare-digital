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
WIX_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"
WIX_ACCOUNT_ID = "478bf907-96cc-4cab-9220-bb96f1d35cbb"
WIX_CLIENT_ID = "42b3cdbf-d90e-4138-a06c-ddda4fb8da01"
ROLE_NAME = "wecare-digital-lambda-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"

#: Where uploaded blog source PDFs land: the existing `wecare-digital-get` bucket, under a
#: new prefix on the PUBLIC root. No bucket is created by this script.
#:
#: `o/` is public - CloudFront E2GP22R4BIFGQ3 serves it at `https://wecare.digital/get/o/...`
#: with no authentication - while `secure/` is denied at the edge. This began as
#: `secure/blog-src/` and moved to `o/` on owner instruction, confirmed a second time on
#: 2026-09-29 to cover derived artefacts as well as sources. The exposure is bounded but
#: real: keys are content hashes or record ids so they cannot be guessed, and listing is not
#: public (all four public-access-block settings are on, and the bucket policy grants
#: s3:GetObject only to the CloudFront service principal) - but every document here,
#: including its extracted text, is readable by anyone holding the URL. These are
#: third-party books and articles, so treat the URL as the secret.
#:
#: Declared above ENV_VARS because ENV_VARS reads it.
SOURCE_BUCKET = "wecare-digital-get"
#: The whole Blog Production tree. Renamed from `o/blog-src/` on 2026-09-29 while the prefix
#: held ZERO objects, which made it a constant change rather than a data migration - and that
#: was the last moment at which it was free. The IAM statement below is scoped to this root,
#: so every sub-prefix (sources/, extracted/, qa/, publish-records/, verification/) is
#: covered without widening to the bucket.
SOURCE_PREFIX = "o/blog-production/"

#: Pure-python wheel, no compiled parts, so it zips straight into the function package -
#: no layer, no Amazon Linux cross-compile. Pinned, and the same version
#: requirements-dev.txt pins, so local extraction and Lambda extraction cannot differ.
PYPDF_VERSION = "6.19.0"

# HTTP API behind wecare.digital/api (stage prod, AutoDeploy on).
# Frontend calls https://wecare.digital/api/seo-tools/{route} (src/api/seo.ts).
API_ID = "zllr9lrg7j"

ENV_VARS = {
    "LOG_LEVEL": "INFO",
    "SEO_TOOLS_TABLE": TABLE_NAME,
    "WEBHOOK_DEDUP_TABLE": DEDUP_TABLE,
    "WIX_SITE_ID": WIX_SITE_ID,
    "WIX_ACCOUNT_ID": WIX_ACCOUNT_ID,
    "WIX_CLIENT_ID": WIX_CLIENT_ID,
    "WIX_BLOG_AUTHOR_NAME": "Anew by WECARE.DIGITAL",
    "BEDROCK_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
    "COGNITO_USER_POOL_ID": "us-east-1_cSx0RHCIR",
    # Blog Production storage, into the existing bucket under o/blog-production/. See
    # SOURCE_PREFIX above for what `o/` being the public root means for these documents.
    "BLOG_SOURCE_BUCKET": SOURCE_BUCKET,
    # AI drafting costs money per call, so it is a cost flag rather than always-on.
    # Enabled here because this function ALREADY invokes Bedrock for ai-seo-audit and
    # already holds the IAM for it - this adds volume to an accepted cost category, not a
    # new one. Turn it off in the SystemConfig cost_flags item without a deploy; the route
    # then answers 409 with the reason instead of silently doing nothing.
    "ENABLE_BEDROCK_ASSIST": "true",
    # Derived-SEO cost/AI posture (seo_config.py). FREE + AI off is the fail-safe default the
    # brief mandates: the deterministic engine and the scheduled freshness check need none of
    # these on, and a public read path must never be one typo from a model call. seo_config
    # additionally requires ENABLE_BEDROCK_ASSIST for AI, so either flag off is sufficient to
    # force deterministic behaviour. Change COST_MODE/AI_ENABLED here to opt in deliberately.
    "COST_MODE": "FREE",
    "AI_ENABLED": "false",
    "FAQ_AI_GENERATION": "false",
}


#: Blog Production needs one source's batch without reading every source in the system.
#:
#: WHY `INCLUDE` AND NOT `ALL`, unlike the two older indexes. A source item carries
#: `extractPreview` (1,500 characters) and `draftRecord`, and an ALL projection would copy
#: both into the index for data that no listing renders - roughly doubling the storage for the
#: hottest record type. The projected list is exactly what `blog_sources._view` returns plus
#: what `blog_batches.rollup` counts.
#:
#: KEEP THE TWO IN STEP. A field added to `_view` but not projected here reads as EMPTY for
#: batch-scoped queries while working fine for every other query - which is a defect that
#: only shows up on the batches page.
#:
#: AND KEEP IT UNDER 20. DynamoDB refuses an index with more than 20 `NonKeyAttributes`:
#:
#:     ValidationException: Value '[...]' at
#:     'globalSecondaryIndexUpdates.1.member.create.projection.nonKeyAttributes'
#:     failed to satisfy constraint: Member must have length less than or equal to 20
#:
#: The first attempt asked for 24 and was refused at deploy time rather than at test time,
#: which is why `test_the_batch_index_respects_the_twenty_attribute_cap` now asserts it. Both
#: `_view` and this list were trimmed to fit; the six fields that went are on `source_detail`,
#: which reads the whole item and has no projection limit.
MAX_INDEX_NON_KEY_ATTRIBUTES = 20
BATCH_INDEX_NAME = "batchId-createdAt-index"
BATCH_INDEX_DEFINITION = {
    "IndexName": BATCH_INDEX_NAME,
    "KeySchema": [
        {"AttributeName": "batchId", "KeyType": "HASH"},
        {"AttributeName": "createdAt", "KeyType": "RANGE"},
    ],
    "Projection": {
        "ProjectionType": "INCLUDE",
        "NonKeyAttributes": [
            "recordType", "slug", "status", "sourceType", "sourceRef", "s3Key",
            "category", "articleClass", "sourceTitle", "extractedWords", "title",
            "articleStatus", "aiDraftStatus", "gateBlocking", "gateReview", "error",
            "updatedAt",
            #: ONE NAME FOR EVERY DOWNSTREAM STAGE. `blog_sources.PIPELINE_FIELDS` holds
            #: sixteen states - analysis, template, QA, sign-off, publish, verification - and
            #: projecting them individually would need sixteen of the twenty slots. A Map
            #: counts as one attribute, so the cap stops constraining the design.
            #:
            #: Also the reason this landed early: a GSI's projection CANNOT be modified in
            #: place. Widening it means deleting and recreating the index, which is free while
            #: the batch partition holds nothing and a migration once a wave is in flight.
            "pipeline",
            #: Analysis records share this index (same `batchId`), and a batch page reports how
            #: much of the wave has actually been read. `slug` above carries the analysed
            #: source id, so only the version number needs its own slot.
            "version",
        ],
    },
}


def _wait_for_index(ddb, gone: bool = False, attempts: int = 60) -> None:
    for _ in range(attempts):
        indexes = {
            index["IndexName"]: index
            for index in ddb.describe_table(TableName=TABLE_NAME)["Table"].get(
                "GlobalSecondaryIndexes") or []
        }
        found = indexes.get(BATCH_INDEX_NAME)
        if gone and not found:
            return
        if not gone and found and found["IndexStatus"] == "ACTIVE" and not found.get(
                "Backfilling"):
            return
        time.sleep(10)
    raise SystemExit(f"[table] timed out waiting for {BATCH_INDEX_NAME}")


def ensure_batch_index(ddb) -> None:
    """Create the batch index, or replace it when its projection has drifted.

    A GSI is created online: the table stays readable and writable while it backfills, and a
    query against an index still building returns partial results rather than failing. So the
    only ordering requirement is that this runs before anything depends on batch-scoped
    queries returning complete answers, which is why it happens in the deploy rather than
    lazily on first use.

    THE PROJECTION CANNOT BE MODIFIED IN PLACE. DynamoDB offers no "change the projected
    attributes" operation - the only route is delete the index and create it again. That is
    cheap while the partition holds nothing and a real migration once it does, so this refuses
    to do it silently: if the projection has drifted AND the index holds records, it prints
    what is missing and stops rather than dropping an index something is querying.
    """
    indexes = {
        index["IndexName"]: index
        for index in ddb.describe_table(TableName=TABLE_NAME)["Table"].get(
            "GlobalSecondaryIndexes") or []
    }
    found = indexes.get(BATCH_INDEX_NAME)
    if found:
        live = set((found.get("Projection") or {}).get("NonKeyAttributes") or [])
        wanted = set(BATCH_INDEX_DEFINITION["Projection"]["NonKeyAttributes"])
        if live == wanted:
            print(f"[table] GSI {BATCH_INDEX_NAME} already present ({len(live)} attributes)")
            return
        missing = sorted(wanted - live)
        held = int(found.get("ItemCount") or 0)
        print(f"[table] GSI {BATCH_INDEX_NAME} projection drifted; missing={missing} "
              f"extra={sorted(live - wanted)} itemCount={held}")
        if held:
            raise SystemExit(
                f"[table] {BATCH_INDEX_NAME} holds {held} items and its projection cannot be "
                f"changed in place. Recreating it would leave batch-scoped queries returning "
                f"partial results while it backfills. Do it deliberately: delete the index, "
                f"wait, and re-run this script.")
        print(f"[table] recreating {BATCH_INDEX_NAME} (it projects nothing anybody is reading)")
        ddb.update_table(TableName=TABLE_NAME,
                         GlobalSecondaryIndexUpdates=[
                             {"Delete": {"IndexName": BATCH_INDEX_NAME}}])
        _wait_for_index(ddb, gone=True)

    print(f"[table] adding GSI {BATCH_INDEX_NAME} (online, backfills in the background)")
    ddb.update_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "batchId", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexUpdates=[{"Create": BATCH_INDEX_DEFINITION}],
    )
    print(f"[table] GSI {BATCH_INDEX_NAME} creation requested")


def ensure_table() -> None:
    ddb = boto3.client("dynamodb", region_name=REGION)
    try:
        ddb.describe_table(TableName=TABLE_NAME)
        print(f"[table] {TABLE_NAME} already exists — skipping create")
        ensure_batch_index(ddb)
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
            },
            BATCH_INDEX_DEFINITION,
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


def _vendor_pypdf(z: zipfile.ZipFile) -> int:
    """Put pypdf in the package, from the local install rather than a fresh download.

    Resolved from the interpreter running this script, which is the same version
    requirements-dev.txt pins and the same one the local CLI extracts with. That equality
    is the point: if the Lambda extracted with a different pypdf, the same PDF could
    produce different article text depending on which door it came through, and nobody
    would notice until somebody compared two extracts of one document.

    Safe to zip from a Mac because pypdf is pure python - `pypdf-6.19.0-py3-none-any.whl`
    has no compiled parts and no platform tag. Do NOT use this helper for anything with a
    C extension; lxml would need building on Amazon Linux, which is exactly why
    `shared/blog_pipeline.py` parses HTML with the stdlib instead.
    """
    try:
        import pypdf
    except ImportError:
        raise SystemExit(
            f"pypdf is not installed locally. Run:\n"
            f"    python -m pip install pypdf=={PYPDF_VERSION}\n"
            "It is pinned in requirements-dev.txt and is vendored into this package."
        )
    version = getattr(pypdf, "__version__", "?")
    if version != PYPDF_VERSION:
        raise SystemExit(
            f"pypdf {version} is installed but this deploy pins {PYPDF_VERSION}. "
            "Matching versions is what keeps local and Lambda extraction identical."
        )
    root = Path(pypdf.__file__).resolve().parent
    count = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        z.write(path, f"pypdf/{path.relative_to(root).as_posix()}")
        count += 1
    # pypdf ships a py.typed marker; harmless to include and keeps the tree faithful.
    marker = root / "py.typed"
    if marker.exists():
        z.write(marker, "pypdf/py.typed")
    print(f"[package] vendored pypdf {version}: {count} modules")
    return count


def ensure_blog_source_perms() -> None:
    """Additive inline policy for the blog source intake: S3 on one prefix, self-invoke.

    Scoped as narrowly as the two capabilities allow, because this role is SHARED by the
    whole fleet - a wildcard here would widen every other function too.

    - S3 is limited to `o/blog-production/*` in one bucket, and to the three actions the
      pipeline uses. No DeleteObject: nothing here deletes a source, and a source is the
      provenance record for a published article. Note this grants WRITE on a prefix of the
      public root, so the blast radius of a bug in key construction is "publishes a file
      publicly" rather than "overwrites something" - which is why every key is derived from a
      content hash or a record id and cannot collide with the 273 existing objects under `o/`.
    - lambda:InvokeFunction is limited to THIS function, which is all the async worker
      hand-off needs. The worker is reached only through IAM, so this statement is also the
      thing that makes the `blogWorker` branch in the handler unreachable from the internet.
    """
    iam = boto3.client("iam")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BlogSourceObjects",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject", "s3:HeadObject"],
                "Resource": f"arn:aws:s3:::{SOURCE_BUCKET}/{SOURCE_PREFIX}*",
            },
            {
                "Sid": "BlogWorkerSelfInvoke",
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="seo-blog-source-intake",
        PolicyDocument=json.dumps(policy),
    )
    print(f"[iam] ensured inline policy seo-blog-source-intake on {ROLE_NAME}")


#: The ingest queue. Names, and the numbers that matter, all in one place so the deploy and the
#: Lambda cannot disagree - `blog_queue` reads the same constants for its consume batch and
#: concurrency cap.
QUEUE_NAME = "wecare-blog-ingest"
DLQ_NAME = QUEUE_NAME + "-dlq"
#: The function's own timeout, named rather than repeated as a literal, because the queue's
#: visibility timeout has to be DERIVED from it - see `VISIBILITY_TIMEOUT`. It was a bare `120`
#: in two places, which is exactly how the two drift apart.
FUNCTION_TIMEOUT = 120
CONSUME_BATCH = 5
#: DERIVED from the function timeout, not a coincidentally larger number. A visibility timeout
#: shorter than the handler's worst case is the classic SQS mistake: the message reappears while
#: the first consumer is still working, a second consumer picks it up, and the work happens
#: twice. The worst case is a full batch of documents each taking the whole function timeout,
#: plus headroom for the cold start and the batch refresh at the end.
VISIBILITY_TIMEOUT = FUNCTION_TIMEOUT * CONSUME_BATCH + FUNCTION_TIMEOUT
#: Four days. Long enough that a weekend outage does not silently discard a wave.
MESSAGE_RETENTION = 345_600
DLQ_RETENTION = 1_209_600  # 14 days, the maximum: a dead-lettered document is evidence.
MAX_RECEIVES = 3
#: Why this is capped at all: this function ALSO serves the admin HTTP API. Left alone, SQS
#: scales a consumer to 1,000 concurrent executions, which would consume the account's
#: concurrency and put every admin request behind document extraction. Five is still five times
#: the old serial rate.
MAX_CONCURRENCY = 5


def ensure_queues() -> Dict[str, str]:
    """Create the ingest queue and its dead-letter queue. Idempotent.

    The DLQ is created FIRST, because the main queue's redrive policy names its ARN. Creating a
    queue with attributes it already has is a no-op that returns the existing URL, so re-running
    is safe - `create_queue` only errors when the attributes CONFLICT with an existing queue, and
    then `set_queue_attributes` is the fix rather than a delete and recreate.
    """
    sqs = boto3.client("sqs", region_name=REGION)

    dlq_url = sqs.create_queue(QueueName=DLQ_NAME, Attributes={
        "MessageRetentionPeriod": str(DLQ_RETENTION),
    })["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]

    attributes = {
        "VisibilityTimeout": str(VISIBILITY_TIMEOUT),
        "MessageRetentionPeriod": str(MESSAGE_RETENTION),
        #: Long polling. Without it a consumer with an empty queue returns immediately and is
        #: re-invoked in a tight loop, which is billed.
        "ReceiveMessageWaitTimeSeconds": "20",
        "RedrivePolicy": json.dumps({
            "deadLetterTargetArn": dlq_arn, "maxReceiveCount": MAX_RECEIVES}),
    }
    queue_url = sqs.create_queue(QueueName=QUEUE_NAME, Attributes=attributes)["QueueUrl"]
    #: Applied again after create, because `create_queue` on an EXISTING queue ignores
    #: attributes rather than updating them - so a changed visibility timeout would otherwise
    #: never take effect and the deploy would report success.
    sqs.set_queue_attributes(QueueUrl=queue_url, Attributes=attributes)
    queue_arn = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    print(f"[sqs] {QUEUE_NAME} ready (visibility={VISIBILITY_TIMEOUT}s, "
          f"maxReceive={MAX_RECEIVES}, dlq={DLQ_NAME})")
    return {"url": queue_url, "arn": queue_arn, "dlqUrl": dlq_url, "dlqArn": dlq_arn}


def ensure_queue_perms(queue_arn: str, dlq_arn: str) -> None:
    """Send on the ingest queue, consume from it, and read the DLQ.

    `ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` are what the event source mapping
    itself needs - Lambda polls using THIS role, so a missing permission shows up as a mapping
    stuck in `Disabled` with a `PROBLEM: Insufficient permissions` cause rather than as a runtime
    error.

    Scoped to two queue ARNs, not `sqs:*`, because this role is shared by the whole fleet.
    """
    iam = boto3.client("iam")
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "BlogIngestQueue",
            "Effect": "Allow",
            "Action": ["sqs:SendMessage", "sqs:SendMessageBatch", "sqs:ReceiveMessage",
                       "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"],
            "Resource": [queue_arn, dlq_arn],
        }],
    }
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="seo-blog-ingest-queue",
                        PolicyDocument=json.dumps(policy))
    print(f"[iam] ensured inline policy seo-blog-ingest-queue on {ROLE_NAME}")


def ensure_event_source(queue_arn: str) -> None:
    """Wire the queue to this function, concurrency-capped and reporting per-message failures.

    `FunctionResponseTypes=['ReportBatchItemFailures']` is the setting that makes partial failure
    work. Without it, one bad document in a batch of five redelivers all five: four
    already-extracted sources are re-read, lose the conditional claim, and the batch makes no
    progress while looking busy.
    """
    client = boto3.client("lambda", region_name=REGION)
    existing = None
    for mapping in client.list_event_source_mappings(
            EventSourceArn=queue_arn, FunctionName=FUNCTION_NAME).get(
                "EventSourceMappings") or []:
        existing = mapping
        break
    wanted = {
        "BatchSize": CONSUME_BATCH,
        "FunctionResponseTypes": ["ReportBatchItemFailures"],
        "ScalingConfig": {"MaximumConcurrency": MAX_CONCURRENCY},
    }
    if existing:
        client.update_event_source_mapping(UUID=existing["UUID"], Enabled=True, **wanted)
        print(f"[lambda] event source mapping updated "
              f"(batch={CONSUME_BATCH}, maxConcurrency={MAX_CONCURRENCY})")
        return
    client.create_event_source_mapping(
        EventSourceArn=queue_arn, FunctionName=FUNCTION_NAME, Enabled=True, **wanted)
    print(f"[lambda] event source mapping created "
          f"(batch={CONSUME_BATCH}, maxConcurrency={MAX_CONCURRENCY})")


# ── Scheduled derived-SEO freshness check ────────────────────────────────────────
#
# A single EventBridge Scheduler schedule invokes this function once a day with the payload
# `{"seoFreshness": true}`. The handler recognises that shape (a top-level key, no
# requestContext) and runs `seo_freshness.run`, which reads the blog corpus and re-derives ONLY
# the records whose sourceHash changed. Unchanged posts cost nothing, so the steady-state daily
# run is a cached corpus read plus a handful of writes at most.
#
# WHY EventBridge Scheduler AND NOT a Lambda self-loop or a 1-minute rule: Scheduler has no idle
# cost, bills per invocation at a rate that is free at one-per-day, and cannot become a tight
# poll. Daily is the lowest reasonable frequency for a blog that publishes at most a few times a
# day; raise it only with a reason.
#
# IAM: a dedicated execution role scoped to invoke EXACTLY this one function - not the shared
# fleet role, and not a wildcard. Creating it is why this step is OPT-IN behind --with-schedule:
# the code path works without the schedule (invoke the function with {"seoFreshness":true} by
# hand, or wire the schedule later), so deploying code never forces an IAM role creation.
SCHEDULE_NAME = "wecare-seo-freshness-daily"
SCHEDULE_ROLE_NAME = "wecare-seo-scheduler-role"
#: Once a day, early UTC. cron rather than rate() so the time of day is explicit and stable.
SCHEDULE_EXPRESSION = "cron(15 2 * * ? *)"


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
# THE ONE DISTINCTION THAT MATTERS. `blog_publish_refused` is deliberately NOT counted. A refusal
# is an operator having switched Wix writes off, and paging somebody because the switch they threw
# is working would teach them to ignore the channel - which is the only thing that makes an alarm
# worthless. `blog_publish_failed` is Wix rejecting a post, and that is worth a look.
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
        ("blog_publish_failed logged - Wix rejected a post. Deliberately does NOT count "
         "blog_publish_refused, which is the kill switch working as intended."),
    ),
)


def provision_alarms(queue_url: str) -> None:
    """Metric filters and alarms for the recorded failure modes. Idempotent.

    `put_metric_filter` and `put_metric_alarm` are both upserts, so re-running is safe and a
    threshold change here takes effect on the next deploy rather than needing a console edit.
    """
    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    log_group = f"/aws/lambda/{FUNCTION_NAME}"

    for name, event, metric, threshold, period, description in LOG_ALARMS:
        logs.put_metric_filter(
            logGroupName=log_group,
            filterName=event.replace("_", "-"),
            filterPattern=f'"{event}"',
            metricTransformations=[{
                "metricName": metric,
                "metricNamespace": ALARM_NAMESPACE,
                "metricValue": "1",
                #: Without a default the metric has NO datapoints while nothing is failing, and
                #: `TreatMissingData` then decides the state instead of the data. With 0 the alarm
                #: sits in OK on evidence rather than on a default.
                "defaultValue": 0.0,
            }],
        )
        cw.put_metric_alarm(
            AlarmName=name,
            AlarmDescription=description,
            Namespace=ALARM_NAMESPACE,
            MetricName=metric,
            Statistic="Sum",
            Period=period,
            EvaluationPeriods=1,
            Threshold=threshold,
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            AlarmActions=[ALARM_TOPIC],
        )
        print(f"[alarm] {name} (>{threshold} in {period}s on {event})")

    #: THE DEAD-LETTER QUEUE IS THE ONE THAT MATTERS MOST. A message reaches it after three
    #: deliveries, and at that point nothing else in this system will ever mention that document
    #: again - it is not in the queue, its source row still says UPLOADED, and the reconciliation
    #: sweep will re-queue it only to have it fail three more times. Threshold 0, matching the
    #: eight existing `wecare-*-dlq-depth` alarms.
    cw.put_metric_alarm(
        AlarmName=f"wecare-{QUEUE_NAME.removeprefix('wecare-')}-dlq-depth",
        AlarmDescription=(
            f"{DLQ_NAME} has messages - a source failed {MAX_RECEIVES} deliveries and nothing "
            "else in the pipeline will mention it again. Read the source's error, fix the cause, "
            "then POST /blog-sources/redrive."),
        Namespace="AWS/SQS",
        MetricName="ApproximateNumberOfMessagesVisible",
        Dimensions=[{"Name": "QueueName", "Value": DLQ_NAME}],
        Statistic="Maximum",
        Period=300,
        EvaluationPeriods=1,
        Threshold=0.0,
        ComparisonOperator="GreaterThanThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[ALARM_TOPIC],
    )
    print(f"[alarm] wecare-{QUEUE_NAME.removeprefix('wecare-')}-dlq-depth (>0 on {DLQ_NAME})")

    #: Age rather than depth on the main queue. Depth is meaningless mid-wave - 2,000 messages is
    #: a healthy fan-out - whereas an oldest message older than the visibility timeout means the
    #: consumer is not keeping up or the mapping is disabled. 900s matches `wecare-queue-age-bulk`.
    cw.put_metric_alarm(
        AlarmName=f"wecare-queue-age-{QUEUE_NAME.removeprefix('wecare-')}",
        AlarmDescription=(
            f"{QUEUE_NAME}'s oldest message is over 15 minutes old - the consumer is not keeping "
            "up, or the event source mapping is disabled. Depth alone says nothing here, because "
            "a large wave is a legitimately deep queue."),
        Namespace="AWS/SQS",
        MetricName="ApproximateAgeOfOldestMessage",
        Dimensions=[{"Name": "QueueName", "Value": QUEUE_NAME}],
        Statistic="Maximum",
        Period=300,
        EvaluationPeriods=1,
        Threshold=900.0,
        ComparisonOperator="GreaterThanThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[ALARM_TOPIC],
    )
    print(f"[alarm] wecare-queue-age-{QUEUE_NAME.removeprefix('wecare-')} (>900s on {QUEUE_NAME})")

    #: Verified, not assumed. `put_metric_alarm` accepts an empty `AlarmActions` without complaint,
    #: so an alarm that pages nobody is created just as successfully as one that works - and reads
    #: identically in a deploy log.
    names = [name for name, *_ in LOG_ALARMS] + [
        f"wecare-{QUEUE_NAME.removeprefix('wecare-')}-dlq-depth",
        f"wecare-queue-age-{QUEUE_NAME.removeprefix('wecare-')}",
    ]
    live = {alarm["AlarmName"]: alarm
            for alarm in cw.describe_alarms(AlarmNames=names)["MetricAlarms"]}
    actionless = [name for name in names
                  if not (live.get(name, {}).get("AlarmActions") or [])]
    if actionless:
        raise SystemExit(f"[alarm] these alarms have no action and would page nobody: {actionless}")
    print(f"[alarm] {len(live)}/{len(names)} present, all routed to "
          f"{ALARM_TOPIC.rsplit(':', 1)[-1]}")


def package() -> bytes:
    """Zip: shim + operations/seo-tools + shared/lambda_utils + blog pipeline + pypdf."""
    shim = FUNCTIONS_DIR / "seo_tools_handler.py"
    seo_dir = FUNCTIONS_DIR / "operations" / "seo-tools"
    lambda_utils = FUNCTIONS_DIR / "shared" / "lambda_utils"
    pipeline = FUNCTIONS_DIR / "shared" / "blog_pipeline.py"
    # The quality gate is SHARED WITH THE CLI rather than reimplemented, which is the only
    # way the browser path and the bulk path can agree on what passes. It is dependency-free
    # by design so it can be dropped into a Lambda package unchanged.
    gate = ROOT / "scripts" / "blog_quality_v2.py"
    #: THE PUBLISHED CORPUS SKETCH INDEX, AND IT IS NOT OPTIONAL BALLAST.
    #:
    #: `blog_quality_v2.CorpusIndex.load_published_index` reads this path, and when it is
    #: absent it returns 0 SILENTLY - by design, so a unit test building a two-record corpus
    #: does not depend on a 1.4 MB file. In a Lambda that silence is the dangerous case: a QA
    #: run would report NON_DUPLICATION PASS having compared the article against nothing,
    #: which is precisely the "worse than no gate, because it is believed" failure the index
    #: was built to fix. It was missing from this package until the QA run needed it.
    #:
    #: The relative path is what `PUBLISHED_INDEX` expects, and Lambda's working directory is
    #: /var/task, so packaging it at the same relative location makes it resolve unchanged.
    #: `blog_gate` loads it lazily and caches it, and `blog_qa` refuses to accept a sign-off
    #: against a run that did not load it.
    corpus = ROOT / "content" / "conversations" / "corpus-index.json"
    #: THE RICOS COMPILER, REUSED RATHER THAN REIMPLEMENTED.
    #:
    #: `wix_blog_migrate.markdown_to_rich_content` already compiles editorial Markdown into the
    #: image-free Ricos subset this site renders, `draft_post` already builds the Wix draft-post
    #: body, and `tests/test_wix_blog_migrate.py` already covers both. A second compiler in the
    #: Lambda would drift from the one that produced the 1,165 live posts, and the first symptom
    #: would be a published article that renders differently from every article beside it.
    #:
    #: Safe to package flat: stdlib plus boto3 (present in the runtime), every module-level
    #: statement is a constant or an `os.environ.get`, and the CLI sits behind `if __name__`.
    migrate = ROOT / "scripts" / "wix_blog_migrate.py"
    for required in (shim, seo_dir, lambda_utils, pipeline, gate, corpus, migrate):
        assert required.exists(), f"missing {required}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(shim, "seo_tools_handler.py")
        for f in sorted(seo_dir.glob("*.py")):
            z.write(f, f"operations/seo-tools/{f.name}")
        z.write(ROOT / "config" / "public-pages.json", "operations/seo-tools/public-pages.json")
        for f in sorted(lambda_utils.glob("*.py")):
            z.write(f, f"shared/lambda_utils/{f.name}")
        skb = FUNCTIONS_DIR / "shared" / "static_knowledge_base.py"
        if skb.exists():
            z.write(skb, "shared/static_knowledge_base.py")
        # Flat at the root, because the shim puts operations/seo-tools on sys.path and
        # these are imported as bare module names (`import blog_pipeline`,
        # `import blog_quality_v2`) from handler-local code.
        z.write(pipeline, "blog_pipeline.py")
        z.write(gate, "blog_quality_v2.py")
        z.write(migrate, "wix_blog_migrate.py")
        z.write(corpus, "content/conversations/corpus-index.json")
        _vendor_pypdf(z)
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
    ensure_bedrock_inference_profile_perms()
    ensure_blog_source_perms()
    #: ORDER MATTERS. The queue has to exist before its URL can go into the function's
    #: environment, the IAM policy has to be in place before the event source mapping is
    #: created or Lambda parks it in `Disabled` with an insufficient-permissions cause, and the
    #: mapping must come last so the first message arrives at code that can handle it.
    queues = ensure_queues()
    ensure_queue_perms(queues["arn"], queues["dlqArn"])
    ENV_VARS["BLOG_INGEST_QUEUE_URL"] = queues["url"]
    ENV_VARS["BLOG_INGEST_QUEUE_NAME"] = QUEUE_NAME
    zip_bytes = package()
    deploy_lambda(zip_bytes)
    ensure_event_source(queues["arn"])
    #: AFTER the function, because a metric filter needs its log group to exist - Lambda creates
    #: `/aws/lambda/<name>` on the first invocation, and `put_metric_filter` against a missing
    #: group is a ResourceNotFoundException rather than a no-op.
    provision_alarms(queues["url"])
    ensure_api_route()
    #: OPT-IN. Creating the scheduler's IAM role is the one step here that creates IAM, so it is
    #: gated: `python scripts/deploy_seo_tools.py --with-schedule`. Without the flag the code is
    #: deployed and the freshness check is reachable (invoke with {"seoFreshness": true}); the
    #: daily automation is simply not wired until someone opts in.
    if with_schedule:
        ensure_freshness_schedule()
    else:
        print("[schedule] skipped (pass --with-schedule to create the daily freshness schedule "
              "and its scoped IAM role)")
    print("=== done ===")
    print(f"Endpoint: https://wecare.digital/api/seo-tools/  (stage prod, auto-deploy)")


if __name__ == "__main__":
    main()
