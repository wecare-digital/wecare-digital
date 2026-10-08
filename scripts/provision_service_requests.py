"""Provision `wecare-service-requests` (Phase O-1) end to end. Dry run by default.

Creates or reconciles, additively and nothing else:

  1. table `stack-wecare-digital-ServiceRequestsTable` (PK `requestId`, PAY_PER_REQUEST, PITR on,
     TTL left disabled) with GSI `customerId-createdAt-index` and GSI `orderId-index`;
  2. role `wecare-service-requests-role`: the AWS managed `AWSLambdaBasicExecutionRole` plus ONE
     inline policy `service-requests-rw` with NO logs statement (see `expected_role_policy`).
     the fleet's shared role is not touched;
  3. log group with 30-day retention;
  4. the function (python3.12), its env (names only), a `live` alias;
  5. the invoke permission on `:live` for each of the two routes, exact source ARNs;
  6. one AWS_PROXY integration (payload 2.0) to the alias, and the two routes;
  7. a metric filter + alarm on `{ $.alert = "PAID_SERVICE_UNMATCHED" }` routed to the alarm
     topic `provision_alarm_coverage.py` uses.

Nothing here deletes, retargets or widens an existing resource. Packaging is delegated to
`scripts/deploy_all_lambdas.py`, which owns every later code update.

    python scripts/provision_service_requests.py            # dry run: print the plan
    python scripts/provision_service_requests.py --apply    # provision
    python scripts/provision_service_requests.py --verify   # read back only
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
FUNCTION_NAME = "wecare-service-requests"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-service-requests-role"
INLINE_POLICY_NAME = "service-requests-rw"
MANAGED_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEYS = ("POST /services/request-intent", "POST /services/my-requests")

SERVICE_REQUESTS_TABLE = "stack-wecare-digital-ServiceRequestsTable"
CUSTOMER_INDEX = "customerId-createdAt-index"
ORDER_INDEX = "orderId-index"
COMMERCE_KEYS_TABLE = "stack-wecare-digital-WixOrderIds"
RATE_LIMIT_TABLE = "stack-wecare-digital-RateLimitTable"
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"

#: The commerce-keys row families activation reads. Nothing else on that table is reachable.
COMMERCE_KEY_PREFIXES = ["PAYREF#*", "REFERENCE#*", "PAYMENTATTEMPT#*"]

ALARM_TOPIC_NAME = "wecare-alarm-notifications"
ALARM_NAME = "wecare-service-requests-paid-unmatched"
METRIC_NAMESPACE = "WECARE/ServiceRequests"
METRIC_NAME = "PaidServiceUnmatched"
FILTER_NAME = "paid-service-unmatched"
FILTER_PATTERN = '{ $.alert = "PAID_SERVICE_UNMATCHED" }'

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_SOURCE = "ecommerce/service-requests"
LOG_GROUP = f"/aws/lambda/{FUNCTION_NAME}"

CUSTOMER_INDEX_INCLUDE = ["kind", "publicRequestId", "status", "orderNumber",
                          "targetPublicRequestId", "amountPaise", "currency"]

_account = None


def account_id() -> str:
    global _account
    if _account is None:
        try:
            _account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
        except (ClientError, BotoCoreError):
            _account = "<account>"
    return _account


def _c(name: str):
    return boto3.client(name, region_name=REGION) if name != "iam" else boto3.client("iam")


def _code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


# ── pure builders (tests/test_service_requests_iam.py holds these EQUAL) ──────

def expected_role_policy(acct: str | None = None) -> dict:
    """The canonical request policy. No logs (the managed policy owns that), no DeleteItem, no Scan, no
    BatchWrite, no secretsmanager/kms/lambda/s3/sns/ses: this role cannot move money, read a
    secret, message anyone, or delete a request."""
    acct = acct or account_id()
    table = f"arn:aws:dynamodb:{REGION}:{acct}:table/{SERVICE_REQUESTS_TABLE}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ServiceRequestsRW", "Effect": "Allow",
             "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                        "dynamodb:ConditionCheckItem"],
             "Resource": [table]},
            {"Sid": "ServiceRequestsByCustomer", "Effect": "Allow",
             "Action": ["dynamodb:Query"],
             "Resource": [f"{table}/index/{CUSTOMER_INDEX}"]},
            {"Sid": "ReadPaidOrderClaims", "Effect": "Allow",
             "Action": ["dynamodb:GetItem"],
             "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{COMMERCE_KEYS_TABLE}"],
             "Condition": {"ForAllValues:StringLike": {
                 "dynamodb:LeadingKeys": list(COMMERCE_KEY_PREFIXES)}}},
            {"Sid": "RateLimitCounter", "Effect": "Allow",
             "Action": ["dynamodb:UpdateItem"],
             "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{RATE_LIMIT_TABLE}"]},
        ],
    }


def expected_vault_file_policy(acct: str | None = None) -> dict:
    """Separate additive policy, matching the deployed vault-file-selection policy."""
    acct = acct or account_id()
    return {"Version": "2012-10-17", "Statement": [{
        "Sid": "BindSelectedVaultFile", "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
        "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/stack-wecare-digital-SecureFilesTable"]}]}


def expected_managed_policies() -> list:
    return [MANAGED_POLICY_ARN]


def expected_environment() -> dict:
    """Every value is a NAME. No value here can enable anything."""
    return {
        "SERVICE_REQUESTS_TABLE": SERVICE_REQUESTS_TABLE,
        "COMMERCE_KEYS_TABLE": COMMERCE_KEYS_TABLE,
        "RATE_LIMIT_TABLE": RATE_LIMIT_TABLE,
        "CUSTOMER_POOL_ID": CUSTOMER_POOL_ID,
    }


def expected_table_definition() -> dict:
    return {
        "TableName": SERVICE_REQUESTS_TABLE,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": "requestId", "AttributeType": "S"},
            {"AttributeName": "customerId", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "N"},
            {"AttributeName": "orderId", "AttributeType": "S"},
        ],
        "KeySchema": [{"AttributeName": "requestId", "KeyType": "HASH"}],
        "GlobalSecondaryIndexes": [
            {"IndexName": CUSTOMER_INDEX,
             "KeySchema": [{"AttributeName": "customerId", "KeyType": "HASH"},
                           {"AttributeName": "createdAt", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "INCLUDE",
                            "NonKeyAttributes": list(CUSTOMER_INDEX_INCLUDE)}},
            {"IndexName": ORDER_INDEX,
             "KeySchema": [{"AttributeName": "orderId", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "KEYS_ONLY"}},
        ],
        "Tags": [{"Key": "Project", "Value": "WECARE.DIGITAL"},
                 {"Key": "Purpose", "Value": "ServiceRequests"}],
    }


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def source_arn(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    return f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}"


def statement_id(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    return f"apigateway-invoke-{method.lower()}{path.replace('/', '-')}"


# ── packaging, delegated ──────────────────────────────────────────────────────

def _deploy_module():
    script = ROOT / "scripts" / "deploy_all_lambdas.py"
    loader = importlib.util.spec_from_file_location("deploy_all_lambdas", script)
    module = importlib.util.module_from_spec(loader)
    sys.modules["deploy_all_lambdas"] = module
    loader.loader.exec_module(module)
    return module


def build_package() -> tuple:
    dal = _deploy_module()
    spec = dal.Spec(FUNCTION_NAME, FUNCTION_SOURCE,
                    provisioned_by="python scripts/provision_service_requests.py")
    zip_bytes, members = dal.build_zip(spec)
    errors, warnings = dal.validate(spec, members, frozenset())
    errors += dal.validate_handler(members, "handler.handler")
    return zip_bytes, members, sorted(set(errors)), sorted(set(warnings))


# ── steps ─────────────────────────────────────────────────────────────────────

def ensure_table(dry_run: bool) -> str:
    ddb = _c("dynamodb")
    try:
        status = ddb.describe_table(TableName=SERVICE_REQUESTS_TABLE)["Table"]["TableStatus"]
        exists = True
    except ClientError as exc:
        if _code(exc) != "ResourceNotFoundException":
            raise
        exists, status = False, ""
    if dry_run:
        return (f"exists ({status})" if exists else
                f"would create {SERVICE_REQUESTS_TABLE} + GSIs {CUSTOMER_INDEX}, {ORDER_INDEX}; "
                f"PITR on; TTL disabled")
    if not exists:
        ddb.create_table(**expected_table_definition())
    ddb.get_waiter("table_exists").wait(TableName=SERVICE_REQUESTS_TABLE)
    for _ in range(90):
        table = ddb.describe_table(TableName=SERVICE_REQUESTS_TABLE)["Table"]
        if table["TableStatus"] == "ACTIVE" and all(
                g.get("IndexStatus") == "ACTIVE" for g in table.get("GlobalSecondaryIndexes", [])):
            break
        time.sleep(5)
    ddb.update_continuous_backups(
        TableName=SERVICE_REQUESTS_TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
    return "created; ACTIVE; PITR on" if not exists else "exists; ACTIVE; PITR on"


def ensure_role(dry_run: bool) -> str:
    iam = _c("iam")
    try:
        iam.get_role(RoleName=ROLE_NAME)
        exists = True
    except ClientError as exc:
        if _code(exc) != "NoSuchEntity":
            raise
        exists = False
    if dry_run:
        return "would reconcile existing role" if exists else "would create and reconcile role"
    if not exists:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"}]}),
            Description="Phase O-1 service requests execution role (own table only)",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "ServiceRequests"}])
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=MANAGED_POLICY_ARN)
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName=INLINE_POLICY_NAME,
                        PolicyDocument=json.dumps(expected_role_policy()))
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="vault-file-selection",
                        PolicyDocument=json.dumps(expected_vault_file_policy()))
    return "reconciled" if exists else "created"


def ensure_log_group(dry_run: bool) -> str:
    logs = _c("logs")
    groups = logs.describe_log_groups(logGroupNamePrefix=LOG_GROUP).get("logGroups", [])
    exists = any(g.get("logGroupName") == LOG_GROUP for g in groups)
    if dry_run:
        return "exists" if exists else "would create with 30-day retention"
    if not exists:
        logs.create_log_group(logGroupName=LOG_GROUP)
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=30)
    return "created" if not exists else "exists; retention verified"


def _function_exists() -> bool:
    try:
        _c("lambda").get_function(FunctionName=FUNCTION_NAME)
        return True
    except ClientError as exc:
        if _code(exc) == "ResourceNotFoundException":
            return False
        raise


def ensure_function(dry_run: bool, zip_bytes: bytes) -> str:
    if _function_exists():
        return "exists"
    if dry_run:
        return "would create (python3.12, 512 MB, 15 s)"
    role_arn = _c("iam").get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    for attempt in range(8):
        try:
            _c("lambda").create_function(
                FunctionName=FUNCTION_NAME, Runtime="python3.12", Role=role_arn,
                Handler="handler.handler", Code={"ZipFile": zip_bytes}, Timeout=15,
                MemorySize=512, Environment={"Variables": expected_environment()},
                Description="Phase O-1 service requests: intent, own list, activation. "
                            "Moves no money.",
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "ServiceRequests"})
            return "created"
        except ClientError as exc:
            if _code(exc) != "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("create retry exhausted")


def ensure_live_alias(dry_run: bool) -> str:
    lam = _c("lambda")
    try:
        lam.get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
        return "exists"
    except ClientError as exc:
        if _code(exc) != "ResourceNotFoundException":
            raise
    if dry_run:
        return "would publish v1 and create the live alias"
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
    version = lam.publish_version(FunctionName=FUNCTION_NAME)["Version"]
    lam.create_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version)
    return f"created -> v{version}"


def ensure_invoke_permissions(dry_run: bool) -> str:
    if dry_run:
        return "; ".join(f"would grant {statement_id(r)} for {source_arn(r)}" for r in ROUTE_KEYS)
    lam = _c("lambda")
    try:
        existing = {s.get("Sid") for s in json.loads(lam.get_policy(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)["Policy"]).get("Statement", [])}
    except ClientError as exc:
        if _code(exc) != "ResourceNotFoundException":
            raise
        existing = set()
    notes = []
    for route in ROUTE_KEYS:
        sid = statement_id(route)
        if sid in existing:
            notes.append(f"{sid} exists")
            continue
        lam.add_permission(FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS, StatementId=sid,
                           Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
                           SourceArn=source_arn(route))
        notes.append(f"granted {sid}")
    return "; ".join(notes)


def _all(method: str) -> list:
    client, items, token = _c("apigatewayv2"), [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "1000"}
        if token:
            kwargs["NextToken"] = token
        page = getattr(client, method)(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            return items


def ensure_integration_and_routes(dry_run: bool) -> str:
    uri = function_arn()
    if dry_run:
        return f"would create AWS_PROXY 2.0 -> {uri} and routes {', '.join(ROUTE_KEYS)}"
    api = _c("apigatewayv2")
    integration = next((i["IntegrationId"] for i in _all("get_integrations")
                        if i.get("IntegrationUri") == uri), "")
    if not integration:
        integration = api.create_integration(
            ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
            PayloadFormatVersion="2.0", Description="Phase O-1 service requests")["IntegrationId"]
    routes = {r["RouteKey"] for r in _all("get_routes")}
    made = []
    for route in ROUTE_KEYS:
        if route not in routes:
            api.create_route(ApiId=API_ID, RouteKey=route, Target=f"integrations/{integration}")
            made.append(route)
    return f"integration {integration}; created routes {made or 'none (all exist)'}"


def ensure_alarm(dry_run: bool) -> str:
    topic = f"arn:aws:sns:{REGION}:{account_id()}:{ALARM_TOPIC_NAME}"
    if dry_run:
        return f"would put metric filter {FILTER_PATTERN!r} and alarm {ALARM_NAME} -> {topic}"
    _c("logs").put_metric_filter(
        logGroupName=LOG_GROUP, filterName=FILTER_NAME, filterPattern=FILTER_PATTERN,
        metricTransformations=[{"metricName": METRIC_NAME, "metricNamespace": METRIC_NAMESPACE,
                                "metricValue": "1", "defaultValue": 0}])
    _c("cloudwatch").put_metric_alarm(
        AlarmName=ALARM_NAME, Namespace=METRIC_NAMESPACE, MetricName=METRIC_NAME,
        Statistic="Sum", Period=300, EvaluationPeriods=1, Threshold=1,
        ComparisonOperator="GreaterThanOrEqualToThreshold", TreatMissingData="notBreaching",
        AlarmActions=[topic],
        AlarmDescription="A paid services order could not be matched to a request. Staff action.")
    return "metric filter + alarm reconciled"


def verify() -> int:
    problems = []
    try:
        live = _c("iam").get_role_policy(RoleName=ROLE_NAME,
                                         PolicyName=INLINE_POLICY_NAME)["PolicyDocument"]
        if live != expected_role_policy():
            problems.append("inline policy drift")
        vault_policy = _c("iam").get_role_policy(RoleName=ROLE_NAME,
                                                PolicyName="vault-file-selection")["PolicyDocument"]
        if vault_policy != expected_vault_file_policy():
            problems.append("vault file selection policy drift")
        attached = [p["PolicyArn"] for p in _c("iam").list_attached_role_policies(
            RoleName=ROLE_NAME)["AttachedPolicies"]]
        if sorted(attached) != expected_managed_policies():
            problems.append(f"managed policies {attached}")
    except ClientError as exc:
        problems.append(f"role unreadable: {_code(exc)}")
    try:
        env = _c("lambda").get_function_configuration(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)["Environment"]["Variables"]
        for key, value in expected_environment().items():
            if env.get(key) != value:
                problems.append(f"env {key}")
    except (ClientError, KeyError) as exc:
        problems.append(f"function unreadable: {type(exc).__name__}")
    routes = {r["RouteKey"] for r in _all("get_routes")}
    problems += [f"route {r} missing" for r in ROUTE_KEYS if r not in routes]
    for problem in problems:
        print(f"  - {problem}")
    print("OK" if not problems else f"FAIL: {len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        return verify()
    dry_run = not args.apply
    print(f"region {REGION}; account {account_id()}; function {FUNCTION_NAME}; role {ROLE_NAME}")
    print(f"routes {', '.join(ROUTE_KEYS)} on {API_ID}/{STAGE}; dry run: {dry_run}\n")
    print("inline policy:\n" + json.dumps(expected_role_policy(), indent=2))
    print("managed policies: " + ", ".join(expected_managed_policies()))
    print("environment:\n" + json.dumps(expected_environment(), indent=2) + "\n")
    zip_bytes, members, errors, warnings = build_package()
    print(f"package: {len(members)} files, {len(zip_bytes)} bytes; "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    for error in errors:
        print(f"  ERROR: {error}")
    if errors:
        return 1

    def step(label, fn, *a):
        try:
            print(f"{label}: {fn(*a)}")
        except (ClientError, BotoCoreError) as exc:
            if not dry_run:
                raise
            print(f"{label}: NOT MEASURED in a dry run ({type(exc).__name__})")

    step("table", ensure_table, dry_run)
    step("role", ensure_role, dry_run)
    step("log group", ensure_log_group, dry_run)
    step("Lambda", ensure_function, dry_run, zip_bytes)
    step("live alias", ensure_live_alias, dry_run)
    step("invoke permissions", ensure_invoke_permissions, dry_run)
    step("integration/routes", ensure_integration_and_routes, dry_run)
    step("alarm", ensure_alarm, dry_run)
    if dry_run:
        print("\ndry run: nothing changed. Re-run with --apply to provision.")
        return 0
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
