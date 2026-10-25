#!/usr/bin/env python3
"""Provision the four notification tables plus the work queue and its DLQ.

Why a script and not `amplify/data/resource.ts`
----------------------------------------------
`resource.ts` declares 65 Amplify models. The account holds 66 DynamoDB tables, and
the two sets have almost no name correspondence - `Contact` against
`ContactsTable`, and so on. Whether those models are deployed at all is an open
question (`NOTIF-STORE-003`), which means a declaration there is not evidence that a
table exists.

That is not a theoretical concern for this domain specifically, it is the exact
failure being repaired. `PstnNotificationDelivery` was declared in four places -
`backend.ts`, `data/resource.ts`, `pstn/claims.py` and `pstn/keys.py` - and exists in
none of the 66 live tables. So every claim attempt raised `ClaimStoreUnavailable` and
the dial-events route answered 503 without sending. Measured: `plivo_dial_event`
fired 0 times in 14 days. A declaration nobody verified is how a notification
subsystem came to be permanently broken while looking complete in source.

So this script creates the tables against the live account and then reads them back.
It is idempotent, safe to re-run, and `--verify` asserts the deployed shape without
changing anything.

Usage
-----
    python scripts/provision_notification_domain.py --dry-run
    python scripts/provision_notification_domain.py
    python scripts/provision_notification_domain.py --verify
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
PREFIX = "stack-wecare-digital"

EVENTS = f"{PREFIX}-NotificationEvents"
DELIVERIES = f"{PREFIX}-NotificationDeliveries"
ATTEMPTS = f"{PREFIX}-NotificationAttempts"
OUTBOX = f"{PREFIX}-NotificationOutbox"

QUEUE = f"{PREFIX}-notification-queue"
DLQ = f"{PREFIX}-notification-dlq"

#: Every table TTLs on the same attribute name, so a sweep or an audit does not need
#: a per-table lookup to know which one to read.
TTL_ATTRIBUTE = "expiresAt"

TABLES = {
    EVENTS: {
        "keys": [("eventClaimKey", "HASH")],
        "attrs": {"eventClaimKey": "S", "canonicalCallId": "S"},
        # Find the event for a provider call id without knowing the version suffix.
        "gsi": [("canonicalCallId-index", [("canonicalCallId", "HASH")])],
    },
    DELIVERIES: {
        "keys": [("deliveryId", "HASH")],
        "attrs": {"deliveryId": "S", "eventClaimKey": "S", "state": "S",
                  "createdAt": "N"},
        "gsi": [
            # All three channels of one call, for the per-number QA matrix rows.
            ("eventClaimKey-index", [("eventClaimKey", "HASH")]),
            # Deliveries stuck in a non-terminal state, oldest first: the backlog and
            # oldest-age signals the observability requirement asks for.
            ("state-createdAt-index", [("state", "HASH"), ("createdAt", "RANGE")]),
        ],
    },
    ATTEMPTS: {
        "keys": [("attemptId", "HASH")],
        "attrs": {"attemptId": "S", "deliveryId": "S", "at": "N"},
        # Append-only history in order. This is the audit trail the brief forbids
        # erasing during the rebuild.
        "gsi": [("deliveryId-at-index", [("deliveryId", "HASH"), ("at", "RANGE")])],
    },
    OUTBOX: {
        "keys": [("jobId", "HASH")],
        "attrs": {"jobId": "S", "status": "S", "availableAt": "N"},
        # The worker's poll: READY jobs whose availableAt has passed, oldest first.
        "gsi": [("status-availableAt-index",
                 [("status", "HASH"), ("availableAt", "RANGE")])],
    },
}


def _ddb():
    return boto3.client("dynamodb", region_name=REGION)


def _sqs():
    return boto3.client("sqs", region_name=REGION)


def table_exists(name: str) -> bool:
    try:
        _ddb().describe_table(TableName=name)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return False
        raise


def create_table(name: str, spec: dict, dry_run: bool) -> str:
    if table_exists(name):
        return "exists"
    if dry_run:
        return "would create"

    _ddb().create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": t}
                              for a, t in sorted(spec["attrs"].items())],
        KeySchema=[{"AttributeName": a, "KeyType": k} for a, k in spec["keys"]],
        GlobalSecondaryIndexes=[
            {
                "IndexName": index_name,
                "KeySchema": [{"AttributeName": a, "KeyType": k} for a, k in index_keys],
                "Projection": {"ProjectionType": "ALL"},
            }
            for index_name, index_keys in spec.get("gsi", [])
        ] or None,
        Tags=[{"Key": "domain", "Value": "notifications"},
              {"Key": "phase", "Value": "3"}],
    )
    _ddb().get_waiter("table_exists").wait(TableName=name)
    return "created"


def enable_ttl(name: str, dry_run: bool) -> str:
    """TTL bounds claim growth. A claim must outlive every provider retry window, or
    it expiring would permit a duplicate send - hence 30 days in `store.py`, not 1."""
    current = _ddb().describe_time_to_live(TableName=name)
    desc = current.get("TimeToLiveDescription", {}) or {}
    if desc.get("TimeToLiveStatus") in ("ENABLED", "ENABLING"):
        return f"ttl already {desc.get('AttributeName')}"
    if dry_run:
        return f"would enable ttl on {TTL_ATTRIBUTE}"
    _ddb().update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE})
    return f"ttl enabled on {TTL_ATTRIBUTE}"


def enable_pitr(name: str, dry_run: bool) -> str:
    """Point-in-time recovery. The brief requires a restorable snapshot before any
    notification table is retired, and requires restoring notification state without
    duplicate sends as a disaster-recovery exercise. Neither is possible without it."""
    try:
        current = _ddb().describe_continuous_backups(TableName=name)
        status = (current.get("ContinuousBackupsDescription", {})
                  .get("PointInTimeRecoveryDescription", {})
                  .get("PointInTimeRecoveryStatus"))
        if status == "ENABLED":
            return "pitr already enabled"
        if dry_run:
            return "would enable pitr"
        _ddb().update_continuous_backups(
            TableName=name,
            PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
        return "pitr enabled"
    except ClientError as exc:
        return f"pitr skipped ({exc.response.get('Error', {}).get('Code')})"


def queue_url(name: str) -> str:
    try:
        return _sqs().get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if "NonExistentQueue" in code or code == "AWS.SimpleQueueService.NonExistentQueue":
            return ""
        raise


def create_queues(dry_run: bool) -> dict:
    """Work queue with a DLQ after 3 receives, following the repo's own convention:
    `visibilityTimeout` 300s, work retention 1 day, DLQ retention 7 days,
    `maxReceiveCount` 3 (see `amplify/backend-resources.ts`).

    The visibility timeout matches `store.LEASE_SECONDS`. They must agree: a
    visibility timeout shorter than the lease would redeliver a message whose lease is
    still held, and a lease shorter than the timeout would let a second worker take a
    job the first is still processing. Either way the channel sends twice.
    """
    out = {}

    dlq_url = queue_url(DLQ)
    if dlq_url:
        out[DLQ] = "exists"
    elif dry_run:
        out[DLQ] = "would create"
    else:
        dlq_url = _sqs().create_queue(
            QueueName=DLQ,
            Attributes={"MessageRetentionPeriod": str(7 * 24 * 3600),
                        "VisibilityTimeout": "300"})["QueueUrl"]
        out[DLQ] = "created"

    main_url = queue_url(QUEUE)
    if main_url:
        out[QUEUE] = "exists"
        return out
    if dry_run:
        out[QUEUE] = "would create"
        return out

    dlq_arn = _sqs().get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    _sqs().create_queue(
        QueueName=QUEUE,
        Attributes={
            "MessageRetentionPeriod": str(24 * 3600),
            "VisibilityTimeout": "300",
            "RedrivePolicy": ('{"deadLetterTargetArn":"%s","maxReceiveCount":3}'
                              % dlq_arn),
        })
    out[QUEUE] = "created"
    return out


def verify() -> int:
    """Read back the deployed shape. Exit 1 on any discrepancy."""
    problems = []
    print(f"region {REGION}\n")

    for name, spec in TABLES.items():
        if not table_exists(name):
            problems.append(f"{name}: MISSING")
            print(f"  FAIL {name}  does not exist")
            continue
        desc = _ddb().describe_table(TableName=name)["Table"]
        keys = [(k["AttributeName"], k["KeyType"]) for k in desc["KeySchema"]]
        indexes = sorted(i["IndexName"] for i in desc.get("GlobalSecondaryIndexes", []))
        expected_indexes = sorted(n for n, _ in spec.get("gsi", []))

        ttl = (_ddb().describe_time_to_live(TableName=name)
               .get("TimeToLiveDescription", {}) or {})
        ttl_ok = ttl.get("TimeToLiveStatus") == "ENABLED" and ttl.get("AttributeName") == TTL_ATTRIBUTE

        pitr = (_ddb().describe_continuous_backups(TableName=name)
                .get("ContinuousBackupsDescription", {})
                .get("PointInTimeRecoveryDescription", {})
                .get("PointInTimeRecoveryStatus"))

        ok = (keys == spec["keys"] and indexes == expected_indexes
              and ttl_ok and desc["TableStatus"] == "ACTIVE")
        if not ok:
            problems.append(name)
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        print(f"       status {desc['TableStatus']}  keys {keys}")
        print(f"       indexes {indexes}")
        print(f"       ttl {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}"
              f"   pitr {pitr}")
        print(f"       items {desc.get('ItemCount')}")

    print()
    for name in (QUEUE, DLQ):
        url = queue_url(name)
        if not url:
            problems.append(f"{name}: MISSING")
            print(f"  FAIL {name}  does not exist")
            continue
        attrs = _sqs().get_queue_attributes(
            QueueUrl=url, AttributeNames=["VisibilityTimeout", "MessageRetentionPeriod",
                                          "RedrivePolicy"])["Attributes"]
        print(f"  ok   {name}")
        print(f"       visibility {attrs.get('VisibilityTimeout')}s  "
              f"retention {attrs.get('MessageRetentionPeriod')}s")
        if attrs.get("RedrivePolicy"):
            print(f"       redrive {attrs['RedrivePolicy']}")

    # The lease and the visibility timeout must agree, or a job is processed twice.
    try:
        sys.path.insert(0, "amplify/functions/shared")
        from lambda_utils.notifications import store as store_mod
        url = queue_url(QUEUE)
        if url:
            visibility = int(_sqs().get_queue_attributes(
                QueueUrl=url, AttributeNames=["VisibilityTimeout"]
            )["Attributes"]["VisibilityTimeout"])
            if visibility != store_mod.LEASE_SECONDS:
                problems.append("lease/visibility mismatch")
                print(f"\n  FAIL lease {store_mod.LEASE_SECONDS}s != queue visibility "
                      f"{visibility}s — a job could be processed twice")
            else:
                print(f"\n  ok   lease {store_mod.LEASE_SECONDS}s == queue visibility "
                      f"{visibility}s")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  warn could not cross-check the lease: {type(exc).__name__}")

    problems.extend(verify_worker())

    print()
    if problems:
        print(f"{len(problems)} problem(s): {', '.join(problems)}")
        return 1
    print("notification domain verified")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, create nothing")
    ap.add_argument("--verify", action="store_true",
                    help="read back the deployed shape and exit non-zero on a gap")
    args = ap.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region {REGION}  dry_run {args.dry_run}\n")
    for name, spec in TABLES.items():
        print(f"  {name}")
        print(f"    {create_table(name, spec, args.dry_run)}")
        if not args.dry_run or table_exists(name):
            print(f"    {enable_ttl(name, args.dry_run)}")
            print(f"    {enable_pitr(name, args.dry_run)}")

    print()
    for name, status in create_queues(args.dry_run).items():
        print(f"  {name}\n    {status}")

    print()
    print(f"  {WORKER_FUNCTION}")
    print(f"    {create_worker_function(args.dry_run)}")
    print(f"    {ensure_worker_alias(args.dry_run)}")
    print(f"    {ensure_event_source(args.dry_run)}")

    if args.dry_run:
        print("\ndry run: nothing created")
        return 0

    print("\nre-reading the deployed shape ...\n")
    return verify()




# ── the worker function ───────────────────────────────────────────────────────
#
# Appended after the tables and queues because it depends on both: the event source
# mapping needs the queue ARN, and the function is useless without the tables.
#
# `scripts/deploy_all_lambdas.py` updates existing functions; it does not create them.
# So the first existence of `wecare-notification-worker` has to come from here, and
# from then on the normal deploy path owns its code.

WORKER_FUNCTION = "wecare-notification-worker"
WORKER_SOURCE = "amplify/functions/messaging/notification-worker"
WORKER_ROLE = "arn:aws:iam::775261844268:role/wecare-digital-lambda-role"

#: Must not exceed the queue's VisibilityTimeout, and must be under the lease. A worker
#: still running when its lease expires would have its job taken by a second worker, and
#: the channel would be sent twice.
WORKER_TIMEOUT = 120
WORKER_MEMORY = 512

#: How often the recovery sweep runs. Not a substitute for the queue - it exists for the
#: crash-before-enqueue window, which is rare, so a slow cadence is correct.
SWEEP_SCHEDULE = "rate(5 minutes)"


def _lambda():
    return boto3.client("lambda", region_name=REGION)


def function_exists(name: str) -> bool:
    try:
        _lambda().get_function(FunctionName=name)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return False
        raise


def create_worker_function(dry_run: bool) -> str:
    """Create the function with a minimal placeholder, then let the normal deploy path
    put real code on it.

    Deliberately does NOT try to build the production zip here. That logic lives in
    `deploy_all_lambdas.py`, which resolves shared `lambda_utils`, validates that every
    top-level import exists in the package or a layer, and produces a reproducible
    CodeSha256. Duplicating any of that would give two answers to "what is in the
    package", which is the class of problem this whole phase is fixing.
    """
    if function_exists(WORKER_FUNCTION):
        return "exists"
    if dry_run:
        return "would create (placeholder, then deploy_all_lambdas.py ships the code)"

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Fails loudly if invoked before the real deploy, rather than silently
        # returning success and acknowledging SQS messages it never processed.
        zf.writestr(
            "handler.py",
            "def handler(event, context):\n"
            "    raise RuntimeError(\n"
            "        'placeholder: run scripts/deploy_all_lambdas.py "
            "wecare-notification-worker'\n"
            "    )\n")

    _lambda().create_function(
        FunctionName=WORKER_FUNCTION,
        Runtime="python3.12",
        Role=WORKER_ROLE,
        Handler="handler.handler",
        Code={"ZipFile": buf.getvalue()},
        Timeout=WORKER_TIMEOUT,
        MemorySize=WORKER_MEMORY,
        Architectures=["x86_64"],
        Description="Drains the notification outbox: one channel send per job.",
        Environment={"Variables": {
            "NOTIF_SWEEP_LIMIT": "25",
            # The flag is NOT set here. Absent means off, and the worker has nothing to
            # do until the domain is enabled deliberately.
        }},
        Tags={"domain": "notifications", "phase": "3"},
    )
    _lambda().get_waiter("function_active_v2").wait(FunctionName=WORKER_FUNCTION)
    return "created (placeholder)"


def ensure_worker_alias(dry_run: bool) -> str:
    """The `live` alias. Every HTTP integration and event source in this account targets
    an alias, never `$LATEST` - see `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa)."""
    if dry_run and not function_exists(WORKER_FUNCTION):
        return "would create alias live"
    try:
        alias = _lambda().get_alias(FunctionName=WORKER_FUNCTION, Name="live")
        return f"alias live -> v{alias['FunctionVersion']}"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    if dry_run:
        return "would create alias live"
    version = _lambda().publish_version(FunctionName=WORKER_FUNCTION)["Version"]
    _lambda().create_alias(FunctionName=WORKER_FUNCTION, Name="live",
                           FunctionVersion=version)
    return f"alias live created -> v{version}"


def ensure_event_source(dry_run: bool) -> str:
    """Wire the queue to the worker alias.

    Created **disabled**. The domain is off, so the queue is empty and an enabled mapping
    would be equally inert - but a disabled mapping makes the cutover an explicit,
    reversible step with its own record, rather than something that was already true and
    nobody noticed.
    """
    url = queue_url(QUEUE)
    if not url:
        return "queue missing; skipped"
    arn = _sqs().get_queue_attributes(
        QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]

    if not function_exists(WORKER_FUNCTION):
        return "function missing; skipped"

    existing = _lambda().list_event_source_mappings(
        FunctionName=f"{WORKER_FUNCTION}:live", EventSourceArn=arn)
    if existing.get("EventSourceMappings"):
        mapping = existing["EventSourceMappings"][0]
        return (f"exists uuid={mapping['UUID'][:8]} state={mapping.get('State')} "
                f"batch={mapping.get('BatchSize')}")
    if dry_run:
        return "would create event source mapping (disabled)"

    mapping = _lambda().create_event_source_mapping(
        EventSourceArn=arn,
        FunctionName=f"{WORKER_FUNCTION}:live",
        Enabled=False,
        BatchSize=10,
        # Partial batch failure, so one poison message does not redrive the whole batch
        # and re-examine channels that already succeeded.
        FunctionResponseTypes=["ReportBatchItemFailures"],
    )
    return f"created uuid={mapping['UUID'][:8]} state={mapping.get('State')} (disabled)"


def verify_worker() -> list:
    """Read back the worker, its alias and its event source. Returns a problem list."""
    problems = []
    print()
    if not function_exists(WORKER_FUNCTION):
        print(f"  FAIL {WORKER_FUNCTION}  does not exist")
        return [f"{WORKER_FUNCTION}: MISSING"]

    cfg = _lambda().get_function_configuration(FunctionName=WORKER_FUNCTION)
    print(f"  ok   {WORKER_FUNCTION}")
    print(f"       state {cfg.get('State')}  runtime {cfg.get('Runtime')}  "
          f"timeout {cfg.get('Timeout')}s  memory {cfg.get('MemorySize')}MB")

    env = (cfg.get("Environment") or {}).get("Variables") or {}
    flag = env.get("PSTN_CONNECTED_NOTIFICATIONS_ENABLED", "(absent)")
    print(f"       PSTN_CONNECTED_NOTIFICATIONS_ENABLED {flag}")
    if flag not in ("(absent)", "false"):
        problems.append("worker has the domain flag enabled")

    try:
        alias = _lambda().get_alias(FunctionName=WORKER_FUNCTION, Name="live")
        print(f"       alias live -> v{alias['FunctionVersion']}")
    except ClientError:
        problems.append(f"{WORKER_FUNCTION}: no live alias")
        print("       FAIL no live alias")

    url = queue_url(QUEUE)
    if url:
        arn = _sqs().get_queue_attributes(
            QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        mappings = _lambda().list_event_source_mappings(
            FunctionName=f"{WORKER_FUNCTION}:live", EventSourceArn=arn)
        for mapping in mappings.get("EventSourceMappings", []):
            state = mapping.get("State")
            print(f"       event source {mapping['UUID'][:8]} state {state} "
                  f"batch {mapping.get('BatchSize')} "
                  f"responseTypes {mapping.get('FunctionResponseTypes')}")
            if state not in ("Disabled", "Disabling"):
                problems.append(f"event source mapping is {state}, expected Disabled "
                                "while the domain is off")
        if not mappings.get("EventSourceMappings"):
            problems.append("no event source mapping")
            print("       FAIL no event source mapping")

    # The timeout must stay under the lease, or a still-running worker has its job taken.
    try:
        sys.path.insert(0, "amplify/functions/shared")
        from lambda_utils.notifications import store as store_mod
        if int(cfg.get("Timeout") or 0) >= store_mod.LEASE_SECONDS:
            problems.append("worker timeout >= lease; a running worker could be "
                            "superseded and the channel sent twice")
            print(f"       FAIL timeout {cfg.get('Timeout')}s >= lease "
                  f"{store_mod.LEASE_SECONDS}s")
        else:
            print(f"       ok   timeout {cfg.get('Timeout')}s < lease "
                  f"{store_mod.LEASE_SECONDS}s")
    except Exception as exc:  # noqa: BLE001
        print(f"       warn could not cross-check the lease: {type(exc).__name__}")

    return problems


if __name__ == "__main__":
    raise SystemExit(main())
