"""Provision `wecare-meta-catalog-sync`: the AWS ProductsTable -> Meta catalogue projection.

PHASE W, FEAT-001. Design reference: decision D3 in
`.agents/tasks/phase-w-whatsapp-commerce-20261006/plan.md`.

WHAT IT CREATES

| | |
|---|---|
| Role | `wecare-meta-catalog-sync-role`, with the inline policy `wecare-meta-catalog-sync-reads` |
| Log group | `/aws/lambda/wecare-meta-catalog-sync`, 30-day retention |
| Function | python3.12, 512 MB, 120 s, `handler.handler`, no layer |
| Alias | `live`, pointing at a published version |
| Schedule | EventBridge rule `wecare-meta-catalog-sync-schedule`, six-hourly, as the BACKSTOP |
| Permission | `events.amazonaws.com` may invoke the `live` alias, scoped to that rule's ARN |
| Stream mapping | the ProductsTable change stream -> the `live` alias, the prompt trigger |

NO HTTP API ROUTE, NO FUNCTION URL, NO PUBLIC SURFACE AT ALL. Nothing calls this over the
internet. Its two triggers are the ProductsTable stream (an event-source mapping on the `live`
alias) and the schedule. So there is no authorizer question to answer here and
`scripts/audit_route_auth.py` has nothing to classify - which is the cheapest possible answer to
"is this endpoint protected".

ADDITIVE ONLY. It never calls `delete_*` or `detach_*`. An existing resource is reported, never
recreated or retargeted.

A DEDICATED ROLE, AND THE SHARED FLEET ROLE IS NOT TOUCHED
----------------------------------------------------------
`wecare-digital-lambda-role` is attached to most of the ~65-function fleet, so granting anything
there hands it to all of them. This function gets its own role with five statements and nothing
else: CloudWatch Logs, one `secretsmanager:GetSecretValue`, three item actions on the
AgentApprovals table, and read-only access to ProductsTable and its one change stream. No S3, no
KMS, no `lambda:InvokeFunction`, no `iam:*`. `tests/test_meta_catalog_sync_iam.py` asserts the
document by EQUALITY, so a sixth statement is a test failure rather than an unnoticed addition,
and asserts this file never names the shared role.

ONE SECRET
----------
The catalogue source is the AWS-native ProductsTable, read under this role, so the Meta Graph
token (`wecare/meta-system-user-token`) is the only secret the function reads: it reads and,
within the approval gates below, writes the Meta catalog. No `wecare/*` wildcard, which would
include every provider credential in the account.

THE SECRET ARN IS WILDCARDED ON THE SUFFIX, and that is not laziness: Secrets Manager appends a
random six-character suffix to every secret ARN, so `wecare/meta-system-user-token-*` is the only
way to name it without reading it first. It matches one secret, not a family.

THE SCHEDULE IS THE BACKSTOP, NOT THE TRIGGER
---------------------------------------------
Six-hourly, at `cron(25 */6 * * ? *)` - the same cadence and the same minute as
`.github/workflows/aws-native-catalog-publish.yml`, so the website snapshot refresh and the Meta
projection move together rather than drifting six hours apart. The ProductsTable stream is what
makes it prompt; the schedule is what makes it eventually correct if the mapping is disabled, a
batch exhausted its retries, or an event was simply missed.

OWNER-APPROVED CATALOG MIGRATION, 2026-10-09
-----------------------------------------
The owner requested the fresh catalog and approval before new product publication.
ENVIRONMENT stages all five paid service variants against the fresh catalog, disabled and
dry-run, held out of stock pending approval and native purchase QA. Inspect remains read-only.
The exact live plan is persisted in the existing AgentApprovals table under a catalog-specific
namespaced key. An authenticated admin approval is bound to that exact hash; any catalogue or Meta
drift changes the hash and invalidates it. Background stream/schedule invocations cannot spend an
approval: apply is an explicit admin action and still requires both release gates to be opened.

Usage:
    python scripts/provision_meta_catalog_sync.py              # dry run, the default
    python scripts/provision_meta_catalog_sync.py --apply
    python scripts/provision_meta_catalog_sync.py --verify
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import zipfile

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = "775261844268"

LIVE_ALIAS = "live"

FUNCTION = "wecare-meta-catalog-sync"
ROLE = f"{FUNCTION}-role"
POLICY = f"{FUNCTION}-reads"
LOG_GROUP = f"/aws/lambda/{FUNCTION}"
LOG_RETENTION_DAYS = 30

SCHEDULE_RULE = f"{FUNCTION}-schedule"
#: Six-hourly at minute 25, matching `.github/workflows/aws-native-catalog-publish.yml`'s
#: `25 */6 * * *`.
SCHEDULE_EXPRESSION = "cron(25 */6 * * ? *)"

#: Secret NAMES, never values. Neither is read by this script.
META_TOKEN_SECRET = "wecare/meta-system-user-token"
CATALOG_APPROVALS_TABLE = "stack-wecare-digital-AgentApprovalsTable"
#: The ONE ProductsTable stream the `live` alias's event-source mapping reads, named by its exact
#: label rather than `stream/*`. Re-enabling a stream mints a new label, and a new stream is a new,
#: deliberate grant. Matches the live `NativeProductsChangeStream` grant on this role.
PRODUCTS_STREAM_LABEL = "2026-10-14T06:15:10.307"

#: No secret value, by construction - only NAMES and public identifiers. The catalog id is the ONE
#: shared `wecare_shop` catalog used by BOTH WABAs, from `src/pages/catalog-builder.tsx`, so this
#: single sync target covers both business numbers. Another catalog stays reachable by changing
#: this one variable; `META_TOKEN_FIELD` remains the per-WABA knob, because the token is not shared.
#:
# Owner-authorized rollout; scope and availability hold must remain explicit.
ENVIRONMENT = {
    "META_TOKEN_SECRET": META_TOKEN_SECRET,
    "META_TOKEN_FIELD": "access_token",
    "META_CATALOG_ID": "1457045652952851",
    "META_CATALOG_SYNC_ENABLED": "true",
    "META_CATALOG_SYNC_DRY_RUN": "false",
    "META_CATALOG_AUTO_APPLY_SAFE": "true",
    "META_CATALOG_AUTO_APPLY_MAX_CHANGES": "50",
    "META_CATALOG_APPROVALS_TABLE": CATALOG_APPROVALS_TABLE,
    # Empty means the product-level metaEnabled flag owns scope. Existing legacy rows remain
    # eligible until they are explicitly migrated; every newly-created native product starts
    # metaEnabled=false, so it cannot appear in the plan accidentally.
    # The live rollout scope (set 2026-10-15 11:54 IST with the gates). Clear it deliberately,
    # with the manifest and the test, to hand scope to the product-level flag.
    "META_CATALOG_SYNC_VARIANT_IDS": "ac5cee5d-0dd1-4a1e-ac13-c3767d3fd8dd,1960aa09-7585-4813-91b5-13b30e64d342,9a108efe-e3b9-42f2-b465-0e8470a293e4,081aa95d-82e4-451c-80f2-bc076d1cdb4d,4d3e2b31-7888-4250-8f5a-0587344431db,750a2d69-198d-42fa-ad80-f13a19ec6603,864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b,8ee7e325-d772-4452-a993-5c79e927d42b,db166bc8-a763-41ec-9f65-0f718f18155a,dcff995e-448c-493a-9259-f6a82ccdc2b4,e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b,3788a657-9af2-4ecf-8c9b-f218669d753c,3879304e-f924-430e-991a-bd9592c1d8f7,4a691fd4-549d-4698-bff6-2df7c094ccf9,973e32ca-6272-43d9-b9ea-9dc1dd9ac2af,997508d6-1f2a-4d33-80df-83e992b4910a,9a3ac454-45b6-44ed-9d4a-7b4106e45556,a3559cf9-ced8-47d4-be89-ba6267af0b83,b2dc278c-1653-4012-acd8-feb0cf871899,b6aeb636-d3d8-4765-a63c-751c440d9a32,da9a27b8-d781-49c2-954a-66d8020861df",
    "META_CATALOG_SYNC_FORCE_OUT_OF_STOCK": "false",
    "CATALOG_SOURCE": "aws",
    "PRODUCTS_TABLE": "stack-wecare-digital-ProductsTable",
    "LOG_LEVEL": "INFO",
}

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify/functions/ecommerce/meta-catalog-sync"
SHARED = ROOT / "amplify/functions/shared"


def iam():
    return boto3.client("iam", region_name=REGION)


def lam():
    return boto3.client("lambda", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def events():
    return boto3.client("events", region_name=REGION)


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FUNCTION}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def rule_arn() -> str:
    return f"arn:aws:events:{REGION}:{ACCOUNT_ID}:rule/{SCHEDULE_RULE}"


def secret_arn(name: str, account: str = ACCOUNT_ID) -> str:
    return f"arn:aws:secretsmanager:{REGION}:{account}:secret:{name}-*"


def trust_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }


def expected_role_policy(account: str = ACCOUNT_ID) -> dict:
    """Four exact statements: logs, Meta token, approval table, and ProductsTable read.

    Pinned by EQUALITY in `tests/test_meta_catalog_sync_iam.py`. The DynamoDB grant is deliberately
    limited to the existing AgentApprovals table and only GetItem/PutItem/UpdateItem: proposal,
    exact approval, apply claim and readback status. No Scan/Query/Delete and no other table.

    - no `s3:*` - it writes no artefact;
    - no `lambda:InvokeFunction` - it is invoked, it does not invoke;
    - no `secretsmanager:PutSecretValue`, `UpdateSecret` or `DescribeSecret` - it reads;
    - no `events:*` - the schedule invokes it, it does not manage the schedule.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OwnLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{REGION}:{account}:log-group:{LOG_GROUP}",
                    f"arn:aws:logs:{REGION}:{account}:log-group:{LOG_GROUP}:*",
                ],
            },
            {
                "Sid": "ReadMetaToken",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [secret_arn(META_TOKEN_SECRET, account)],
            },
            {
                "Sid": "CatalogProposalApprovalRecords",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{account}:table/{CATALOG_APPROVALS_TABLE}"
                ],
            },
            {
                "Sid": "ReadProductsStream",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:DescribeStream",
                    "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator",
                    "dynamodb:ListStreams",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{account}:table/stack-wecare-digital-ProductsTable"
                    f"/stream/{PRODUCTS_STREAM_LABEL}"
                ],
            },
            {
                "Sid": "ReadNativeProductCatalog",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{account}:table/stack-wecare-digital-ProductsTable",
                    f"arn:aws:dynamodb:{REGION}:{account}:table/stack-wecare-digital-ProductsTable/index/*",
                ],
            },
        ],
    }


def build_package() -> bytes:
    """handler.py plus the shared `lambda_utils` tree - the shape `deploy_all_lambdas` builds."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            archive.write(path, path.relative_to(SOURCE).as_posix())
        for path in sorted((SHARED / "lambda_utils").rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            archive.write(path, path.relative_to(SHARED).as_posix())
    return buffer.getvalue()


def ensure_role(apply: bool) -> str:
    try:
        iam().get_role(RoleName=ROLE)
        existing = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        existing = False

    if not apply:
        return (f"would put {POLICY} on existing {ROLE}" if existing
                else f"would create {ROLE} with {POLICY} (4 statements)")

    if not existing:
        iam().create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
            Description="AWS ProductsTable to Meta catalogue sync with exact-plan durable owner approval",
            Tags=[{"Key": "domain", "Value": "ecommerce"},
                  {"Key": "purpose", "Value": "meta-catalog-sync"}],
        )
    # Idempotent: put_role_policy REPLACES the named inline policy, so re-running converges.
    iam().put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                          PolicyDocument=json.dumps(expected_role_policy()))
    return f"{'updated' if existing else 'created'} {ROLE} + {POLICY}"


def ensure_log_group(apply: bool) -> str:
    try:
        groups = logs().describe_log_groups(logGroupNamePrefix=LOG_GROUP).get("logGroups", [])
    except ClientError:
        groups = []
    found = next((g for g in groups if g.get("logGroupName") == LOG_GROUP), None)
    if found:
        if int(found.get("retentionInDays") or 0) == LOG_RETENTION_DAYS:
            return f"exists, {LOG_RETENTION_DAYS}d"
        if not apply:
            return f"would set retention to {LOG_RETENTION_DAYS}d"
        logs().put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=LOG_RETENTION_DAYS)
        return f"retention set to {LOG_RETENTION_DAYS}d"
    if not apply:
        return f"would create {LOG_GROUP} at {LOG_RETENTION_DAYS}d"
    logs().create_log_group(logGroupName=LOG_GROUP)
    logs().put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=LOG_RETENTION_DAYS)
    return f"created {LOG_GROUP} at {LOG_RETENTION_DAYS}d"


def ensure_function(apply: bool) -> str:
    try:
        lam().get_function(FunctionName=FUNCTION)
        # Code updates belong to `scripts/deploy_all_lambdas.py`, the one place that packages,
        # validates imports against the attached layers, publishes and moves the alias.
        return "exists (code updates belong to deploy_all_lambdas.py)"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    if not apply:
        return "would create (owner scoped rollout; two variants held out of stock)"
    lam().create_function(
        FunctionName=FUNCTION,
        Runtime="python3.12",
        Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE}",
        Handler="handler.handler",
        Code={"ZipFile": build_package()},
        # 120 seconds covers a ProductsTable read, a paged Meta read and the diff with room to
        # spare. It is invoked asynchronously, so nothing is waiting on it.
        Timeout=120,
        MemorySize=512,
        Architectures=["x86_64"],
        Environment={"Variables": ENVIRONMENT},
        Description="AWS ProductsTable to Meta catalogue projection, owner-approved scope.",
        Tags={"domain": "ecommerce", "purpose": "meta-catalog-sync"},
    )
    lam().get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    return "created"


def ensure_alias(apply: bool) -> str:
    """Publish a version and point `live` at it.

    Both callers target the ALIAS, so a `$LATEST` change does not reach them until a version is
    published and the alias moves. That is the control, per
    `.kiro/steering/lambda-snapstart-deploy.md`.
    """
    if not apply:
        return f"would publish a version and point {LIVE_ALIAS} at it"
    version = lam().publish_version(FunctionName=FUNCTION)["Version"]
    try:
        lam().create_alias(FunctionName=FUNCTION, Name=LIVE_ALIAS, FunctionVersion=version)
        return f"created {LIVE_ALIAS} -> v{version}"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceConflictException":
            raise
        lam().update_alias(FunctionName=FUNCTION, Name=LIVE_ALIAS, FunctionVersion=version)
        return f"moved {LIVE_ALIAS} -> v{version}"


def ensure_stream_mapping(apply: bool) -> str:
    table = boto3.client("dynamodb", region_name=REGION).describe_table(
        TableName="stack-wecare-digital-ProductsTable")["Table"]
    stream_arn = str(table.get("LatestStreamArn") or "")
    if not stream_arn:
        raise RuntimeError("ProductsTable stream is not enabled")

    # By the `live` ALIAS ARN. A mapping belongs to the qualified function it invokes, and
    # listing by the bare name returns none of the alias's mappings - so this saw no mapping,
    # and `--apply` would have created a duplicate beside the live one (c15e412f).
    mappings = lam().list_event_source_mappings(FunctionName=function_arn()).get(
        "EventSourceMappings", [])
    current = next((m for m in mappings if m.get("EventSourceArn") == stream_arn), None)
    if current:
        if current.get("State") == "Enabled":
            return f"exists enabled {current.get('UUID')}"
        if not apply:
            return f"would enable {current.get('UUID')}"
        lam().update_event_source_mapping(UUID=current["UUID"], Enabled=True)
        return f"enabled {current.get('UUID')}"

    if not apply:
        return f"would create {stream_arn} -> {function_arn()}"

    created = lam().create_event_source_mapping(
        EventSourceArn=stream_arn,
        FunctionName=function_arn(),
        Enabled=True,
        # The live mapping's settings (c15e412f, read 2026-10-15), so a re-create reproduces
        # what runs rather than a second opinion of it.
        BatchSize=1,
        MaximumBatchingWindowInSeconds=5,
        StartingPosition="LATEST",
        BisectBatchOnFunctionError=True,
        MaximumRetryAttempts=2,
        MaximumRecordAgeInSeconds=3600,
        ParallelizationFactor=1,
    )
    return f"created {created.get('UUID')}"


def ensure_schedule(apply: bool) -> str:
    """The six-hourly backstop, pointed at the `live` alias."""
    try:
        existing = events().describe_rule(Name=SCHEDULE_RULE)
        if existing.get("ScheduleExpression") == SCHEDULE_EXPRESSION:
            note = "exists"
        elif not apply:
            return f"would retarget {SCHEDULE_RULE} to {SCHEDULE_EXPRESSION}"
        else:
            note = "updated"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        if not apply:
            return f"would create {SCHEDULE_RULE} {SCHEDULE_EXPRESSION} -> {function_arn()}"
        note = "created"

    if not apply:
        return note

    events().put_rule(
        Name=SCHEDULE_RULE,
        ScheduleExpression=SCHEDULE_EXPRESSION,
        State="ENABLED",
        Description="Six-hourly backstop for the AWS ProductsTable to Meta catalogue sync.")
    events().put_targets(Rule=SCHEDULE_RULE,
                         Targets=[{"Id": "live-alias", "Arn": function_arn()}])
    return f"{note} {SCHEDULE_RULE} {SCHEDULE_EXPRESSION}"


def live_policy_statements() -> list:
    try:
        policy = lam().get_policy(FunctionName=FUNCTION, Qualifier=LIVE_ALIAS)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException",
                                                         "ResourceNotFound"):
            return []
        raise
    return json.loads(policy.get("Policy") or "{}").get("Statement") or []


def ensure_schedule_permission(apply: bool) -> str:
    """EventBridge needs a resource policy statement on the ALIAS, scoped to the rule's ARN.

    A function-level statement does not authorise an alias invoke, and an unscoped one would let
    any rule in the account invoke this function.
    """
    sid = f"events-{SCHEDULE_RULE}"
    if any(s.get("Sid") == sid for s in live_policy_statements()):
        return f"{sid} exists"
    if not apply:
        return f"would add {sid} -> {rule_arn()}"
    lam().add_permission(
        FunctionName=FUNCTION, Qualifier=LIVE_ALIAS, StatementId=sid,
        Action="lambda:InvokeFunction", Principal="events.amazonaws.com",
        SourceArn=rule_arn())
    return f"added {sid}"


def verify() -> int:
    """Read everything back. Non-zero on any problem."""
    problems: list[str] = []

    try:
        live = iam().get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
        if live != expected_role_policy():
            problems.append(f"{ROLE}/{POLICY} does not match expected_role_policy()")
    except ClientError:
        problems.append(f"{ROLE} has no inline policy {POLICY}")

    try:
        config = lam().get_function_configuration(FunctionName=FUNCTION)
    except ClientError:
        config = {}
        problems.append(f"{FUNCTION} does not exist")

    if config:
        if config.get("Runtime") != "python3.12":
            problems.append(f"{FUNCTION} runtime is {config.get('Runtime')}")
        env = (config.get("Environment") or {}).get("Variables") or {}
        for key, value in ENVIRONMENT.items():
            if env.get(key) != value:
                problems.append(f"{FUNCTION} env {key} is {env.get(key)!r}, expected {value!r}")
        # Owner authorized the scoped two-variant rollout on 2026-10-08.
        # Exact environment comparison above preserves the scope and out-of-stock hold.
        try:
            lam().get_alias(FunctionName=FUNCTION, Name=LIVE_ALIAS)
        except ClientError:
            problems.append(f"{FUNCTION} has no {LIVE_ALIAS} alias, so neither caller can "
                            "reach a code update")

    try:
        table = boto3.client("dynamodb", region_name=REGION).describe_table(
            TableName="stack-wecare-digital-ProductsTable")["Table"]
        stream_arn = str(table.get("LatestStreamArn") or "")
        mappings = lam().list_event_source_mappings(FunctionName=function_arn()).get(
            "EventSourceMappings", [])
        current = next((m for m in mappings if m.get("EventSourceArn") == stream_arn), None)
        if not stream_arn:
            problems.append("ProductsTable stream is not enabled")
        elif not current:
            problems.append("ProductsTable stream has no Meta sync event-source mapping")
        elif current.get("State") != "Enabled":
            problems.append(f"ProductsTable stream mapping is {current.get('State')}")
    except ClientError:
        problems.append("could not verify ProductsTable stream mapping")

    try:
        rule = events().describe_rule(Name=SCHEDULE_RULE)
        if rule.get("ScheduleExpression") != SCHEDULE_EXPRESSION:
            problems.append(f"{SCHEDULE_RULE} runs {rule.get('ScheduleExpression')}")
        if rule.get("State") != "ENABLED":
            problems.append(f"{SCHEDULE_RULE} is {rule.get('State')}")
        targets = events().list_targets_by_rule(Rule=SCHEDULE_RULE).get("Targets", [])
        if not any(t.get("Arn") == function_arn() for t in targets):
            problems.append(f"{SCHEDULE_RULE} does not target {function_arn()}")
    except ClientError:
        problems.append(f"{SCHEDULE_RULE} does not exist, so there is no backstop")

    sid = f"events-{SCHEDULE_RULE}"
    if not any(s.get("Sid") == sid for s in live_policy_statements()):
        problems.append(f"{LIVE_ALIAS} has no invoke statement {sid}; the schedule would fire "
                        "and nothing would run")

    print(f"verify {FUNCTION}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not problems:
        print("  in step")
        print(f"  no public surface: no HTTP API route, no function URL")
        print("  owner rollout: five paid service variants; held out of stock")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="make the changes; without it this is a dry run")
    parser.add_argument("--verify", action="store_true",
                        help="read the live state back and report problems")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    apply = args.apply
    print(f"{'APPLY' if apply else 'DRY RUN'}  {FUNCTION}")
    print(f"  role              : {ensure_role(apply)}")
    print(f"  log group         : {ensure_log_group(apply)}")
    print(f"  function          : {ensure_function(apply)}")
    print(f"  alias             : {ensure_alias(apply)}")
    print(f"  stream trigger    : {ensure_stream_mapping(apply)}")
    print(f"  schedule          : {ensure_schedule(apply)}")
    print(f"  schedule invoke   : {ensure_schedule_permission(apply)}")
    print()
    print("  no HTTP API route and no function URL are created: this function has no public")
    print("  surface. Its callers are the ProductsTable stream and the schedule above.")
    print("  Owner rollout: five paid service variants; all remain out of stock for QA.")
    if not apply:
        print()
        print("  dry run: nothing above was changed. Re-run with --apply to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
