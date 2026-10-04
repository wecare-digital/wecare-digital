"""Provision `wecare-wix-catalog-webhook`: the Wix catalogue webhook receiver.

Design reference: `.agents/tasks/wix-catalog-auto-sync-b2.md` step 3, and
`docs/wix-catalogue-auto-sync.md` for the owner registration steps this cannot do.

WHAT IT CREATES

| | |
|---|---|
| Role | `wecare-wix-catalog-webhook-role`, with the inline policy `wecare-wix-catalog-webhook-reads` |
| Log group | `/aws/lambda/wecare-wix-catalog-webhook`, 30-day retention |
| Function | python3.12, 128 MB, 15 s, `handler.handler`, the `cryptography` layer attached |
| Alias | `live`, pointing at a published version |
| Route | `POST /wix-catalog-webhook` on HTTP API `zllr9lrg7j`, stage `prod` |
| Integration | one `AWS_PROXY` payload-2.0 integration onto `...:function:wecare-wix-catalog-webhook:live` |
| Permission | one alias-qualified `lambda:InvokeFunction`, `SourceArn` scoped to its own path |

ADDITIVE ONLY. It never calls `delete_route`, `delete_integration`, `delete_function`,
`delete_role` or `detach_*`. An existing resource is reported, never recreated or retargeted.

A DEDICATED ROLE, NOT THE SHARED FLEET ROLE
-------------------------------------------
This function reads `wecare/github-pat`, a token that can push to `stack`. The shared
`wecare-digital-lambda-role` is attached to most of the fleet, so granting that read there would
hand ~60 unrelated functions the ability to write to the repository. The role here grants exactly
two secret reads and CloudWatch Logs, and nothing else - no DynamoDB, no S3, no Lambda invoke.

THE SECRET ARNS ARE WILDCARDED ON THE SUFFIX, and that is not laziness: Secrets Manager appends a
random six-character suffix to every secret ARN, so `wecare/wix/catalog-webhook-*` is the only way
to name a secret that does not exist yet. It matches one secret, not a family: no other secret in
this account shares that prefix.

THE RECEIVER SHIPS FAIL-CLOSED, ON PURPOSE
------------------------------------------
`wecare/wix/catalog-webhook` does NOT exist in this account, so every request is answered 401 with
an empty body until the owner creates it with the Wix app's public key. That is the correct resting
state for an endpoint whose success path starts a production build, and it costs nothing: the
six-hourly `.github/workflows/catalogue-sync.yml` cron is the mechanism that actually keeps the
catalogue in step, and it needs no secret, no role and no Wix registration. This receiver only
makes the sync near-instant once registered.

THE LAYER IS VERSION-PINNED
---------------------------
`cryptography-python312:1` is the only version that exists and is the one
`wecare-whatsapp-business-api` and `provision_gift_cards_roles.py` already use. Pinned rather than
floating, because a layer version is immutable and `$LATEST` is not a thing for layers - a
floating reference would be a lie about reproducibility.

AUTHORIZATION
-------------
The route is created with `AuthorizationType=NONE` and no authorizer, because this account has
zero API Gateway authorizers and this change does not introduce the first one. It MUST be: Wix
presents its own RS256 JWT as the request body, not a Cognito token, and an API Gateway authorizer
cannot verify a signature over the raw body. Verification is the first thing the handler does, is
asserted on the AST by `tests/test_wix_catalog_webhook.py`, and
`scripts/audit_route_auth.py` classifies the handler on the `verify_signature` STRONG_MARKER -
so no allowlist entry is needed and none is added.

Usage:
    python scripts/provision_wix_catalog_webhook.py              # dry run, the default
    python scripts/provision_wix_catalog_webhook.py --apply
    python scripts/provision_wix_catalog_webhook.py --verify
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

#: The account's single HTTP API ("wecare-digital-api") and its only stage, which auto-deploys.
API_ID = "zllr9lrg7j"
LIVE_ALIAS = "live"

FUNCTION = "wecare-wix-catalog-webhook"
ROLE = f"{FUNCTION}-role"
POLICY = f"{FUNCTION}-reads"
ROUTE_KEY = f"POST /{FUNCTION.replace('wecare-', '')}"
LOG_GROUP = f"/aws/lambda/{FUNCTION}"
LOG_RETENTION_DAYS = 30

#: Secret NAMES, never values. Neither is read by this script.
WIX_SECRET = "wecare/wix/catalog-webhook"
GITHUB_SECRET = "wecare/github-pat"

CRYPTOGRAPHY_LAYER_ARN = (
    f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:layer:cryptography-python312:1")

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify/functions/ecommerce/wix-catalog-webhook"
SHARED = ROOT / "amplify/functions/shared"

#: No secret value, by construction - only NAMES and public identifiers. `GITHUB_REPOSITORY` is
#: the repo the workflow lives in; `CATALOGUE_DISPATCH_EVENT` must match the `repository_dispatch`
#: type in .github/workflows/catalogue-sync.yml.
ENVIRONMENT = {
    "GITHUB_TOKEN_SECRET_ID": GITHUB_SECRET,
    "GITHUB_REPOSITORY": "wecare-digital/wecare-digital",
    "CATALOGUE_DISPATCH_EVENT": "wix-catalogue-changed",
}

SOURCE_ARN = f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{API_ID}/*/*/{FUNCTION.replace('wecare-', '')}"


def iam():
    return boto3.client("iam", region_name=REGION)


def lam():
    return boto3.client("lambda", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FUNCTION}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def secret_arn(name: str) -> str:
    return f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:{name}-*"


def trust_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }


def read_policy() -> dict:
    """Two secret reads and its own log group. Nothing else, and nothing writable.

    No DynamoDB, no S3, no `lambda:InvokeFunction`, no `amplify:StartJob`. The function's entire
    job is to verify a signature and POST to api.github.com, and outbound HTTPS needs no IAM.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OwnLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:log-group:{LOG_GROUP}",
                    f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:log-group:{LOG_GROUP}:*",
                ],
            },
            {
                # The Wix app PUBLIC key, and the GitHub token that starts the workflow. Named
                # individually rather than as `wecare/*`: that wildcard would include every
                # provider credential in the account.
                "Sid": "ReadTheTwoSecretsItNeeds",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [secret_arn(WIX_SECRET), secret_arn(GITHUB_SECRET)],
            },
        ],
    }


def build_package() -> bytes:
    """handler.py plus the shared `lambda_utils` tree, the same shape deploy_all_lambdas builds."""
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
                else f"would create {ROLE} with {POLICY}")

    if not existing:
        iam().create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
            Description="Wix catalogue webhook receiver: read two secrets, write its own logs",
            Tags=[{"Key": "domain", "Value": "ecommerce"},
                  {"Key": "purpose", "Value": "wix-catalogue-auto-sync"}],
        )
    # Idempotent: put_role_policy REPLACES the named inline policy, so re-running converges.
    iam().put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                          PolicyDocument=json.dumps(read_policy()))
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
        # Code updates belong to `scripts/deploy_all_lambdas.py`, which is the one place that
        # packages, validates imports against the attached layers, publishes and moves the alias.
        # Doing it here too would be a second deploy path with its own drift.
        return "exists (code updates belong to deploy_all_lambdas.py)"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
    if not apply:
        return "would create"
    lam().create_function(
        FunctionName=FUNCTION,
        Runtime="python3.12",
        Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE}",
        Handler="handler.handler",
        Code={"ZipFile": build_package()},
        # 15 seconds covers a 10-second GitHub timeout plus a cold RSA verify with room to spare.
        # Longer would only mean a hung dispatch costs more.
        Timeout=15,
        MemorySize=128,
        Architectures=["x86_64"],
        Environment={"Variables": ENVIRONMENT},
        Layers=[CRYPTOGRAPHY_LAYER_ARN],
        Description="Verify a Wix Stores product webhook and fire a GitHub repository_dispatch "
                    "to re-sync src/content/wix-catalog.json. Fails closed with no public key.",
        Tags={"domain": "ecommerce", "purpose": "wix-catalogue-auto-sync"},
    )
    lam().get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    return "created"


def ensure_layer(apply: bool) -> str:
    """The cryptography layer. Without it `wix_webhook.verify_signature` refuses every call."""
    try:
        config = lam().get_function_configuration(FunctionName=FUNCTION)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        return f"function absent; {CRYPTOGRAPHY_LAYER_ARN} after it is created"
    attached = [layer["Arn"] for layer in config.get("Layers") or []]
    if CRYPTOGRAPHY_LAYER_ARN in attached:
        return "already attached"
    if not apply:
        return f"would attach {CRYPTOGRAPHY_LAYER_ARN}"
    lam().update_function_configuration(
        FunctionName=FUNCTION,
        Layers=sorted(set(attached) | {CRYPTOGRAPHY_LAYER_ARN}))
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    return "attached"


def ensure_alias(apply: bool) -> str:
    """Publish a version and point `live` at it.

    `lambda-snapstart-deploy.md`: the integration below targets the ALIAS, so a `$LATEST` change
    does not reach production until a version is published and the alias moves. That is the
    control, and it is why the integration is not pointed at `$LATEST`.
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


def _all_items(method: str) -> list:
    client, items, token = api(), [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "1000"}
        if token:
            kwargs["NextToken"] = token
        page = getattr(client, method)(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            return items


def find_integration() -> str:
    uri = function_arn()
    for integration in _all_items("get_integrations"):
        if integration.get("IntegrationUri") == uri:
            return integration["IntegrationId"]
    return ""


def ensure_integration(apply: bool) -> tuple:
    existing = find_integration()
    if existing:
        return existing, f"reusing {existing}"
    if not apply:
        return "", f"would create AWS_PROXY -> {function_arn()}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=function_arn(),
        PayloadFormatVersion="2.0",
        Description="Wix catalogue webhook receiver")
    return created["IntegrationId"], f"created {created['IntegrationId']}"


def ensure_route(integration_id: str, apply: bool) -> str:
    existing = {r["RouteKey"]: r for r in _all_items("get_routes")}
    if ROUTE_KEY in existing:
        return f"exists ({existing[ROUTE_KEY]['RouteId']})"
    if not apply:
        return f"would create {ROUTE_KEY}"
    made = api().create_route(ApiId=API_ID, RouteKey=ROUTE_KEY,
                              Target=f"integrations/{integration_id}")
    return f"created {ROUTE_KEY} ({made['RouteId']})"


def live_policy_statements() -> list:
    try:
        policy = lam().get_policy(FunctionName=FUNCTION, Qualifier=LIVE_ALIAS)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException",
                                                         "ResourceNotFound"):
            return []
        raise
    return json.loads(policy.get("Policy") or "{}").get("Statement") or []


def ensure_invoke_permission(apply: bool) -> str:
    """One alias-qualified statement. A function-level statement does not authorise an alias
    invoke, and the failure mode is a 500 with no Lambda log line at all."""
    sid = f"apigw-{FUNCTION}-post"
    if any(s.get("Sid") == sid for s in live_policy_statements()):
        return f"{sid} exists"
    if not apply:
        return f"would add {sid} -> {SOURCE_ARN}"
    lam().add_permission(
        FunctionName=FUNCTION, Qualifier=LIVE_ALIAS, StatementId=sid,
        Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
        SourceArn=SOURCE_ARN)
    return f"added {sid}"


def verify() -> int:
    """Read everything back. Non-zero on any problem."""
    problems: list[str] = []

    try:
        iam().get_role_policy(RoleName=ROLE, PolicyName=POLICY)
    except ClientError:
        problems.append(f"{ROLE} has no inline policy {POLICY}")

    try:
        config = lam().get_function_configuration(FunctionName=FUNCTION)
    except ClientError:
        config = {}
        problems.append(f"{FUNCTION} does not exist")

    if config:
        layers = [layer["Arn"] for layer in config.get("Layers") or []]
        if CRYPTOGRAPHY_LAYER_ARN not in layers:
            problems.append(
                f"{FUNCTION} is missing {CRYPTOGRAPHY_LAYER_ARN}; without it "
                "wix_webhook.verify_signature refuses every request (fail-closed, but the "
                "receiver is then permanently dead)")
        if config.get("Runtime") != "python3.12":
            problems.append(f"{FUNCTION} runtime is {config.get('Runtime')}")
        env = (config.get("Environment") or {}).get("Variables") or {}
        for key, value in ENVIRONMENT.items():
            if env.get(key) != value:
                problems.append(f"{FUNCTION} env {key} is {env.get(key)!r}, expected {value!r}")

        try:
            lam().get_alias(FunctionName=FUNCTION, Name=LIVE_ALIAS)
        except ClientError:
            problems.append(f"{FUNCTION} has no {LIVE_ALIAS} alias, so a code update would "
                            "never reach the route")

    integration_id = find_integration()
    if not integration_id:
        problems.append(f"no AWS_PROXY integration targets {function_arn()}")

    routes = {r["RouteKey"]: r for r in _all_items("get_routes")}
    route = routes.get(ROUTE_KEY)
    if not route:
        problems.append(f"missing route {ROUTE_KEY}")
    else:
        if integration_id and route.get("Target") != f"integrations/{integration_id}":
            problems.append(f"{ROUTE_KEY} targets {route.get('Target')}")
        if route.get("AuthorizerId"):
            problems.append(f"{ROUTE_KEY} carries an authorizer this script did not create")

    sid = f"apigw-{FUNCTION}-post"
    if not any(s.get("Sid") == sid for s in live_policy_statements()):
        problems.append(f"{LIVE_ALIAS} has no invoke statement {sid}; API Gateway would answer "
                        "500 with no Lambda log line")

    print(f"verify {FUNCTION}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if not problems:
        print("  in step")
        print(f"  endpoint: https://{API_ID}.execute-api.{REGION}.amazonaws.com/prod"
              f"/{FUNCTION.replace('wecare-', '')}")
        print(f"  NOTE: {WIX_SECRET} must carry `public_key` before the receiver can accept "
              "anything. Until then every call is 401 and the six-hourly "
              ".github/workflows/catalogue-sync.yml cron is the whole of auto-sync.")
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
    print(f"  role            : {ensure_role(apply)}")
    print(f"  log group       : {ensure_log_group(apply)}")
    print(f"  function        : {ensure_function(apply)}")
    print(f"  layer           : {ensure_layer(apply)}")
    print(f"  alias           : {ensure_alias(apply)}")
    integration_id, note = ensure_integration(apply)
    print(f"  integration     : {note}")
    print(f"  route           : {ensure_route(integration_id, apply)}")
    print(f"  invoke permission: {ensure_invoke_permission(apply)}")

    if apply:
        print()
        print("WAITING_FOR_OWNER - the receiver is live and refuses everything until:")
        print(f"  1. a Wix app webhook for Stores product created/updated/deleted points at")
        print(f"     https://{API_ID}.execute-api.{REGION}.amazonaws.com/prod"
              f"/{FUNCTION.replace('wecare-', '')}")
        print(f"  2. Secrets Manager {WIX_SECRET} carries `public_key` (the app's PUBLIC key from")
        print("     the Wix app dashboard Webhooks page) and ideally `app_id`")
        print("  See docs/wix-catalogue-auto-sync.md. Catalogue auto-sync already WORKS without")
        print("  either of these, via the six-hourly .github/workflows/catalogue-sync.yml cron.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
