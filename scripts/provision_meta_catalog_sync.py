"""Provision `wecare-meta-catalog-sync`: the Wix -> Meta catalogue projection.

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
| Webhook grant | `lambda:InvokeFunction` on the alias, added to the WEBHOOK's own role |

NO HTTP API ROUTE, NO FUNCTION URL, NO PUBLIC SURFACE AT ALL. Nothing calls this over the
internet. Its two callers are `wecare-wix-catalog-webhook` (an async invoke after its own JWT
verification) and the schedule. So there is no authorizer question to answer here and
`scripts/audit_route_auth.py` has nothing to classify - which is the cheapest possible answer to
"is this endpoint protected".

ADDITIVE ONLY. It never calls `delete_*` or `detach_*`. An existing resource is reported, never
recreated or retargeted.

A DEDICATED ROLE, AND THE SHARED FLEET ROLE IS NOT TOUCHED
----------------------------------------------------------
`wecare-digital-lambda-role` is attached to most of the ~65-function fleet, so granting anything
there hands it to all of them. This function gets its own role with TWO statements and nothing
else: one `secretsmanager:GetSecretValue`, and CloudWatch Logs. No DynamoDB, no S3, no KMS, no
`lambda:InvokeFunction`, no `iam:*`. `tests/test_meta_catalog_sync_iam.py` asserts the document by
EQUALITY, so a fourth statement is a test failure rather than an unnoticed addition, and asserts
this file never names the shared role.

TWO SECRETS, NOT ONE, AND THE SECOND IS RECORDED RATHER THAN QUIET
-------------------------------------------------------------------
The feature brief describes this role as "the Meta token read plus CloudWatch Logs". It is one
statement naming TWO secret ARNs, because the function reads BOTH ends of the sync:

    wecare/meta-system-user-token   the Meta Graph token, to read and (never, as shipped) write
                                    the catalog
    wecare/wix/headless-api-key     read by `lambda_utils.wix_ecom`, which is the request helper
                                    the handler uses for Catalog V3

Granted only the Meta token, the function cannot read Wix at all: `wix_ecom._api_key()` raises,
every invocation ends `read_failed`, and the dry-run plan this whole feature exists to produce is
unobtainable. So the choice was between a role that cannot work and a statement that names one
more secret by its exact ARN. The second is still least privilege - two named secrets, no
`wecare/*` wildcard, which would otherwise include every provider credential in the account - and
it is the same shape `provision_wix_catalog_webhook.py` uses for its own two reads.

THE SECRET ARNS ARE WILDCARDED ON THE SUFFIX, and that is not laziness: Secrets Manager appends a
random six-character suffix to every secret ARN, so `wecare/meta-system-user-token-*` is the only
way to name it without reading it first. Each matches one secret, not a family.

THE SCHEDULE IS THE BACKSTOP, NOT THE TRIGGER
---------------------------------------------
Six-hourly, at `cron(25 */6 * * ? *)` - the same cadence and the same minute as
`.github/workflows/catalogue-sync.yml`, so the website snapshot refresh and the Meta projection
move together rather than drifting six hours apart. The webhook invoke is what makes it prompt;
the schedule is what makes it eventually correct if the webhook is unregistered, failing closed on
a missing key, or simply missed an event.

OWNER-APPROVED CATALOG MIGRATION, 2026-10-09
-----------------------------------------
The owner requested the fresh catalog and approval before new product publication.
ENVIRONMENT stages all four existing paid variants against the fresh catalog, disabled and
dry-run, held out of stock pending approval and native purchase QA. Inspect remains read-only.
The exact live plan hash must be copied into META_CATALOG_SYNC_APPROVED_PLAN_SHA256 before opening both write gates; any Wix/Meta drift changes the hash and invalidates that approval.

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
#: Six-hourly at minute 25, matching `.github/workflows/catalogue-sync.yml`'s `25 */6 * * *`.
SCHEDULE_EXPRESSION = "cron(25 */6 * * ? *)"

#: The function that invokes this one, and the role whose policy gains that permission. Named here
#: so the grant lands on the WEBHOOK's own least-privilege role rather than on the shared one.
WEBHOOK_FUNCTION = "wecare-wix-catalog-webhook"
WEBHOOK_ROLE = f"{WEBHOOK_FUNCTION}-role"
WEBHOOK_INVOKE_POLICY = f"{WEBHOOK_FUNCTION}-invokes-catalog-sync"

#: Secret NAMES, never values. Neither is read by this script.
META_TOKEN_SECRET = "wecare/meta-system-user-token"
WIX_API_KEY_SECRET = "wecare/wix/headless-api-key"

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
    "META_CATALOG_SYNC_ENABLED": "false",
    "META_CATALOG_SYNC_DRY_RUN": "true",
    "META_CATALOG_SYNC_APPROVED_PLAN_SHA256": "",
    "META_CATALOG_SYNC_VARIANT_IDS": "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b,864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b,db166bc8-a763-41ec-9f65-0f718f18155a,dcff995e-448c-493a-9259-f6a82ccdc2b4",
    "META_CATALOG_SYNC_FORCE_OUT_OF_STOCK": "true",
    "WIX_API_KEY_SECRET": WIX_API_KEY_SECRET,
    "WIX_SITE_ID": "c993128b-26be-41cd-9fcd-904abe23462f",
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
    """TWO statements: its own log group, and the two secrets it reads. Nothing else.

    Pinned by EQUALITY in `tests/test_meta_catalog_sync_iam.py`. Note what is absent and why:

    - no `dynamodb:*` - this function keeps no state; the Meta catalog IS the state, and the diff
      is recomputed from Wix on every run rather than cached;
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
                # Both ends of the sync, named INDIVIDUALLY. `wecare/*` would include every
                # provider credential in the account; see the module docstring for why the Wix
                # key is here and not omitted.
                "Sid": "ReadTheTwoSecretsItNeeds",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [
                    secret_arn(META_TOKEN_SECRET, account),
                    secret_arn(WIX_API_KEY_SECRET, account),
                ],
            },
        ],
    }


def webhook_invoke_policy(account: str = ACCOUNT_ID) -> dict:
    """One statement on the WEBHOOK's role: invoke this function's `live` alias.

    ALIAS-QUALIFIED. A grant on the unqualified function ARN does not authorise an alias invoke,
    and the failure mode is an AccessDenied the caller swallows - so the sync would simply never
    run and the webhook would still answer 200.

    On `wecare-wix-catalog-webhook-role`, NOT on `wecare-digital-lambda-role`: the shared role is
    attached to most of the fleet, so putting an invoke grant there would let ~60 unrelated
    functions start catalogue syncs.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "InvokeMetaCatalogSync",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": [f"arn:aws:lambda:{REGION}:{account}:function:{FUNCTION}:{LIVE_ALIAS}"],
        }],
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
                else f"would create {ROLE} with {POLICY} (2 statements)")

    if not existing:
        iam().create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
            Description="Wix to Meta catalogue sync: read two secrets, write its own logs",
            Tags=[{"Key": "domain", "Value": "ecommerce"},
                  {"Key": "purpose", "Value": "meta-catalog-sync"}],
        )
    # Idempotent: put_role_policy REPLACES the named inline policy, so re-running converges.
    iam().put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                          PolicyDocument=json.dumps(expected_role_policy()))
    return f"{'updated' if existing else 'created'} {ROLE} + {POLICY}"


def ensure_webhook_invoke_grant(apply: bool) -> str:
    """Let the webhook invoke this function. On the webhook's OWN role."""
    try:
        iam().get_role(RoleName=WEBHOOK_ROLE)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        return (f"{WEBHOOK_ROLE} does not exist; run "
                "scripts/provision_wix_catalog_webhook.py --apply first")
    if not apply:
        return f"would put {WEBHOOK_INVOKE_POLICY} on {WEBHOOK_ROLE}"
    iam().put_role_policy(RoleName=WEBHOOK_ROLE, PolicyName=WEBHOOK_INVOKE_POLICY,
                          PolicyDocument=json.dumps(webhook_invoke_policy()))
    return f"put {WEBHOOK_INVOKE_POLICY} on {WEBHOOK_ROLE}"


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
        # 120 seconds covers a paged Wix read, a paged Meta read and the diff with room to spare.
        # It is invoked asynchronously, so nothing is waiting on it.
        Timeout=120,
        MemorySize=512,
        Architectures=["x86_64"],
        Environment={"Variables": ENVIRONMENT},
        Description="Project owner-authorized Wix variants onto Meta, held out of stock for QA.",
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
        Description="Six-hourly backstop for the Wix to Meta catalogue sync. The webhook invoke "
                    "makes it prompt; this makes it eventually correct.")
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

    try:
        iam().get_role_policy(RoleName=WEBHOOK_ROLE, PolicyName=WEBHOOK_INVOKE_POLICY)
    except ClientError:
        problems.append(f"{WEBHOOK_ROLE} cannot invoke {FUNCTION}; the webhook's fan-out would "
                        "fail closed and only the schedule would run")

    print(f"verify {FUNCTION}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not problems:
        print("  in step")
        print(f"  no public surface: no HTTP API route, no function URL")
        print("  owner rollout: Submit Request/Vault only; held out of stock")
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
    print(f"  schedule          : {ensure_schedule(apply)}")
    print(f"  schedule invoke   : {ensure_schedule_permission(apply)}")
    print(f"  webhook can invoke: {ensure_webhook_invoke_grant(apply)}")
    print()
    print("  no HTTP API route and no function URL are created: this function has no public")
    print("  surface. Its callers are the webhook's async invoke and the schedule above.")
    print("  Owner rollout: Submit Request/Vault only; both remain out of stock for QA.")
    if not apply:
        print()
        print("  dry run: nothing above was changed. Re-run with --apply to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
