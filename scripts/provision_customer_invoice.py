"""Provision and verify `wecare-customer-invoice` — a customer's own invoice, presigned.

What it stands up, in this order
-------------------------------
1. `wecare-customer-invoice-role`: trusts `lambda.amazonaws.com` only, carries
   `AWSLambdaBasicExecutionRole` and ONE inline policy equal to `expected_role_policy()`.
2. The log group, 30-day retention (the fleet default).
3. The package, with every top-level import validated against the zip before anything is
   created.
4. The function (python3.12, 512 MB, 15 s) and its eight environment variables.
5. The `live` alias, so this function is on the publish-and-move path from day one.
6. `lambda:AddPermission` on the ALIAS, then
7. the `AWS_PROXY` integration against the alias ARN and the route
   `POST /ecommerce/my-invoice`.

IT CREATES NO TABLE AND NO INDEX. Every resource this function reads already exists and is
owned elsewhere: `customerId-createdAt-index` by `scripts/provision_customer_orders.py`,
`referenceId-index` and both invoice tables by the invoice engine's own provisioning, and
`secure/stack/invoices/` by `payments/invoice-engine`. This script therefore has no
`update_table` call at all, which is deliberate — a second writer for one GSI is how a
projection gets silently recreated.

WHY A SEPARATE FUNCTION AT ALL
------------------------------
See the handler's docstring. In short: this route needs `dynamodb:GetItem`,
`s3:GetObject` and a second `dynamodb:Query`, and all three are specifically refused by
`wecare-customer-orders`' policy and by six EQUALITY assertions in
`tests/test_customer_orders_iam.py`. Bolting the route on there would mean editing those
tests so they assert less, on the one function whose documented security property is its
emptiness.

THE RATE-LIMIT GRANT IS NOT OPTIONAL AND ITS ABSENCE IS SILENT
--------------------------------------------------------------
`rate_limit.check_rate_limit` is a WRITE — `table.update_item` — and its contract is
FAIL-OPEN. Its `except` escalates to ERROR only for `ValidationException` or
`ResourceNotFoundException`; an `AccessDeniedException` is neither, so it logs at WARNING
and returns `True`. Without the `RateLimitCounter` statement below this route would answer
every request UNTHROTTLED, reporting the cause once per request at a level nobody alarms
on. `tests/test_customer_invoice_iam.py` asserts the action set by equality precisely so
nobody "simplifies" it away on the grounds that the function is read-only.

`Qualifier="live"` on step 6 is NOT optional. A function-level statement does not authorise
an invoke of an ALIAS, so step 7's integration would be unauthorised while step 6 reported
success. The symptom is a 500 with no Lambda log line at all, because the function is never
entered.

There is no `OPTIONS` route. The API carries a CORS configuration, so API Gateway answers
the preflight itself. The handler still answers `OPTIONS` first, so a route could be added
later with no code change.

NO CREDENTIAL IS READ, WRITTEN OR NAMED. This function reads no secret: there is no Secrets
Manager statement in the role and nothing here resolves one. Per
.kiro/steering/secret-handling.md no credential value is ever placed on a command line or a
log line, and this script has none to place.

Usage:
    python scripts/provision_customer_invoice.py --dry-run     # default; changes nothing
    python scripts/provision_customer_invoice.py --apply
    python scripts/provision_customer_invoice.py --verify

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-customer-invoice
and then `python scripts/snapstart_publish.py wecare-customer-invoice`, or the route keeps
serving the old code — the integration targets the alias, not $LATEST.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ── identity of everything this script owns ───────────────────────────────────

REGION = "us-east-1"
FUNCTION_NAME = "wecare-customer-invoice"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-customer-invoice-role"
INLINE_POLICY_NAME = "customer-invoice-read"

#: The account's single HTTP API and its only stage, which auto-deploys. There is no
#: `$default` stage, so the raw execute-api host needs the `/prod` segment.
API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEY = "POST /ecommerce/my-invoice"

#: Declared ABOVE `expected_role_policy` on purpose: the policy builder is the document
#: three things reason about (create, reconcile, and tests/test_customer_invoice_iam.py), so
#: every name it interpolates has to be a module constant rather than resolved at call time.
#:
#: SINGULAR `OrderTable`. The environment variable is plural and the table is not.
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
ORDERS_BY_CUSTOMER_INDEX = "customerId-createdAt-index"
INVOICES_TABLE = "stack-wecare-digital-InvoicesTable"
INVOICES_BY_REFERENCE_INDEX = "referenceId-index"
INVOICE_ASSETS_TABLE = "stack-wecare-digital-InvoiceAssetsTable"
RATE_LIMIT_TABLE = "stack-wecare-digital-RateLimitTable"

#: The ONE bucket. `.kiro/steering/blog-production-s3.md`: do not create a new bucket.
MEDIA_BUCKET = "wecare-digital-get"

#: The GATED root, not the public `o/` one. A rendered invoice carries a name, an address,
#: an amount and a GSTIN, and this prefix moved off `o/` on 2026-09-30 for exactly that
#: reason. The object-prefix wildcard is permitted here BECAUSE the prefix is pinned.
INVOICE_PREFIX = "secure/stack/invoices/"

#: The CUSTOMER pool, deliberately not the staff pool. `customer_auth` pins the token issuer
#: to it, and a single env var holding "the pool" is how the two get confused.
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_SOURCE = "ecommerce/customer-invoice"

_account_id_cache = None


def account_id() -> str:
    """The account, or the literal `<account>` when STS cannot be reached.

    A dry run must be able to print the policy it WOULD put without credentials, so an
    unreachable STS degrades to a placeholder that is obviously not an account id rather
    than to a traceback.
    """
    global _account_id_cache
    if _account_id_cache is None:
        try:
            _account_id_cache = boto3.client(
                "sts", region_name=REGION).get_caller_identity()["Account"]
        except (ClientError, BotoCoreError):
            _account_id_cache = "<account>"
    return _account_id_cache


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def source_arn() -> str:
    """The exact source ARN API Gateway presents for this one route. No wildcard at all.

    A prefix such as `{STAGE}/POST/ecommerce/*` was rejected on `provision_checkout.py`
    after measurement: another session had grown a third route into that namespace, so the
    prefix authorised an invoke for a route belonging to a different function. A prefix
    describes a namespace somebody else can grow into, which is not the same as "the route
    this function serves".
    """
    method, path = ROUTE_KEY.split(" ", 1)
    return f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}"


def statement_id() -> str:
    """Route-specific, and NEW rather than reused.

    `add_permission` cannot edit a statement, and remove-then-add under one id opens a
    window where API Gateway cannot invoke the function. There are no legacy ids to retire
    here because the function is new.
    """
    method, path = ROUTE_KEY.split(" ", 1)
    return f"apigateway-invoke-{method.lower()}{path.replace('/', '-')}"


def _not_found(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


# ── the policy, as one pure builder ───────────────────────────────────────────

def expected_role_policy(acct: str | None = None) -> dict:
    """The one inline policy this role carries. Pure, so create, reconcile and the test agree.

    FIVE statements: four reads plus one counter increment. What is ABSENT is the point —
    no `PutItem`, `UpdateItem` or `DeleteItem` on any invoice, order or contact row, no
    `Scan`, no `s3:PutObject` and no `s3:DeleteObject` anywhere, no Secrets Manager, no
    `cognito-idp`, no `lambda:InvokeFunction`, no `sns`/`sqs`/`ses`. The function is
    incapable of generating an invoice, of advancing the GST sequence, of writing an object
    under the gated prefix, of charging, of refunding and of messaging anyone.
    """
    acct = acct or account_id()
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                # THE INDEX ARN, NOT THE TABLE ARN. With no permission on the order table
                # itself, a Scan or a GetItem for `purchasedSnapshot` is an
                # AccessDeniedException rather than a code review finding. The only read
                # this role can perform on the order table is a Query through an index whose
                # partition key is the Cognito subject.
                "Sid": "QueryOwnOrdersByCustomer",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{ORDERS_TABLE}"
                    f"/index/{ORDERS_BY_CUSTOMER_INDEX}"
                ],
            },
            {
                # The order -> invoice join, on the index the webhook already uses. Index
                # only, never the table, so invoice rows cannot be scanned and none can be
                # fetched by id.
                "Sid": "QueryInvoiceByReference",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{INVOICES_TABLE}"
                    f"/index/{INVOICES_BY_REFERENCE_INDEX}"
                ],
            },
            {
                # A BARE TABLE ARN, and it is correct here: the key `{invoiceId, assetType}`
                # is FULLY SPECIFIED, so there is nothing an index would narrow. GetItem on
                # a complete key cannot enumerate.
                "Sid": "ReadInvoiceAsset",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{INVOICE_ASSETS_TABLE}"
                ],
            },
            {
                # GetObject only, and only under the GATED prefix. An object-prefix grant is
                # inherently `.../*`, which is why the test asserts the PREFIX rather than
                # banning the wildcard: a pinned prefix and an open wildcard are different
                # things, and the distinction is the whole grant.
                "Sid": "SignGatedInvoiceObject",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{MEDIA_BUCKET}/{INVOICE_PREFIX}*"],
            },
            {
                # HASH `id` only. `check_rate_limit` is one atomic increment on a fully
                # specified key, so it needs no Query, no Scan and no delete. NOT OPTIONAL:
                # see the module docstring — the limiter fails open, so its absence would be
                # an unthrottled presigning route reporting the cause at WARNING.
                "Sid": "RateLimitCounter",
                "Effect": "Allow",
                "Action": ["dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{RATE_LIMIT_TABLE}"],
            },
        ],
    }


def expected_environment() -> dict:
    """Eight variables, every one of them a NAME. No value here can enable anything."""
    return {
        "ORDERS_TABLE": ORDERS_TABLE,
        "ORDERS_BY_CUSTOMER_INDEX": ORDERS_BY_CUSTOMER_INDEX,
        "INVOICES_TABLE": INVOICES_TABLE,
        "INVOICES_BY_REFERENCE_INDEX": INVOICES_BY_REFERENCE_INDEX,
        "INVOICE_ASSETS_TABLE": INVOICE_ASSETS_TABLE,
        "RATE_LIMIT_TABLE": RATE_LIMIT_TABLE,
        "MEDIA_BUCKET": MEDIA_BUCKET,
        "CUSTOMER_POOL_ID": CUSTOMER_POOL_ID,
    }


# ── packaging, delegated ──────────────────────────────────────────────────────

def _deploy_module():
    """`scripts/deploy_all_lambdas.py` loaded by path, because `scripts/` is not a package.

    Delegated deliberately: this script CREATES the function and `deploy_all_lambdas.py`
    updates it forever after, so a private packer here would mean the first package and
    every later one were assembled by different code. It also moves validation BEFORE
    `create_function`, where an unresolved import is a refusal instead of a cold-start
    `Unable to import module`.
    """
    script = ROOT / "scripts" / "deploy_all_lambdas.py"
    loader = importlib.util.spec_from_file_location("deploy_all_lambdas", script)
    module = importlib.util.module_from_spec(loader)
    sys.modules["deploy_all_lambdas"] = module
    loader.loader.exec_module(module)
    return module


def build_package() -> tuple:
    """`(zip_bytes, members, errors, warnings)`. `provided` is empty: this function has no
    layer, so every import must resolve inside the package or in the python3.12 runtime."""
    dal = _deploy_module()
    spec = dal.Spec(FUNCTION_NAME, FUNCTION_SOURCE,
                    provisioned_by="python scripts/provision_customer_invoice.py")
    zip_bytes, members = dal.build_zip(spec)
    errors, warnings = dal.validate(spec, members, frozenset())
    errors += dal.validate_handler(members, "handler.handler")
    return zip_bytes, members, sorted(set(errors)), sorted(set(warnings))


def package_sha(zip_bytes: bytes) -> str:
    """base64(sha256(zip)) — the same value Lambda reports as `CodeSha256`."""
    return base64.b64encode(hashlib.sha256(zip_bytes).digest()).decode()


def report_package(zip_bytes: bytes, members: dict, errors: list, warnings: list) -> int:
    print(f"package: {len(members)} files, {len(zip_bytes)} bytes, "
          f"sha256 {package_sha(zip_bytes)}")
    for warning in warnings:
        print(f"  warning: {warning}")
    for error in errors:
        print(f"  ERROR: {error}")
    if errors:
        print(f"\nFAIL: {len(errors)} unresolved import(s) — refusing to create the function")
        return 1
    print(f"  imports: all resolve ({len(warnings)} guarded warning(s))")
    return 0


# ── steps 1-7 ─────────────────────────────────────────────────────────────────

def role_exists() -> bool:
    try:
        iam().get_role(RoleName=ROLE_NAME)
        return True
    except ClientError as exc:
        if _not_found(exc, "NoSuchEntity"):
            return False
        raise


def function_exists() -> bool:
    try:
        lam().get_function(FunctionName=FUNCTION_NAME)
        return True
    except ClientError as exc:
        if _not_found(exc, "ResourceNotFoundException"):
            return False
        raise


def ensure_role(dry_run: bool) -> str:
    """Create OR reconcile. Returning early because the role exists is how an older, wider
    live policy survives while the code and the verifier have moved on. `put_role_policy` is
    an idempotent replacement of this function's one owned inline policy."""
    exists = role_exists()
    if dry_run:
        return "would reconcile existing role" if exists else "would create and reconcile role"
    if not exists:
        assume = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                # lambda.amazonaws.com and nothing else. No cross-account principal, no
                # federated principal, no wildcard.
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume),
            Description="Customer invoice presign (own orders only) execution role",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "CustomerInvoice"}],
        )
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=INLINE_POLICY_NAME,
        PolicyDocument=json.dumps(expected_role_policy()),
    )
    return "reconciled" if exists else "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    try:
        groups = logs().describe_log_groups(
            logGroupNamePrefix=name, limit=50).get("logGroups", [])
        exists = any(g.get("logGroupName") == name for g in groups)
    except (ClientError, BotoCoreError):
        exists = False
    if not exists and dry_run:
        return "would create with 30-day retention"
    if not exists:
        logs().create_log_group(logGroupName=name, tags={
            "Project": "WECARE.DIGITAL", "Purpose": "CustomerInvoice"})
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


def ensure_function(dry_run: bool, zip_bytes: bytes) -> str:
    if function_exists():
        return "exists"
    if dry_run:
        return "would create (python3.12, 512 MB, 15 s)"
    role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    for attempt in range(8):
        try:
            lam().create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": zip_bytes},
                Description="Customer invoice presign. Read-only: ownership Query, invoice "
                            "lookup, asset GetItem and a signature. It never generates.",
                Timeout=15,
                MemorySize=512,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "CustomerInvoice"},
            )
            return "created"
        except ClientError as exc:
            # IAM is eventually consistent, so a freshly created role is not immediately
            # assumable by Lambda.
            if exc.response.get("Error", {}).get("Code") != \
                    "InvalidParameterValueException" or attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("Lambda create retry exhausted")


def reconcile_environment(dry_run: bool) -> str:
    if not function_exists():
        return "function absent - nothing to reconcile"
    config = lam().get_function_configuration(FunctionName=FUNCTION_NAME)
    current = dict((config.get("Environment") or {}).get("Variables") or {})
    drifted = {k: v for k, v in expected_environment().items() if current.get(k) != v}
    if not drifted:
        return "env already correct"
    if dry_run:
        return f"would set {', '.join(sorted(drifted))}"
    current.update(drifted)
    lam().update_function_configuration(
        FunctionName=FUNCTION_NAME, Environment={"Variables": current})
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    return f"set {', '.join(sorted(drifted))}"


def ensure_live_alias(dry_run: bool) -> str:
    try:
        lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
        return "exists"
    except ClientError as exc:
        if not _not_found(exc, "ResourceNotFoundException"):
            raise
    if dry_run:
        return f"would publish v1 and create the {LIVE_ALIAS} alias"
    published = lam().publish_version(
        FunctionName=FUNCTION_NAME, Description="initial customer invoice presign release")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Production customer invoice presign target")
    return f"created -> v{version}"


def live_policy_statements() -> list:
    try:
        raw = lam().get_policy(FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)
    except ClientError as exc:
        if _not_found(exc, "ResourceNotFoundException"):
            return []
        raise
    return json.loads(raw["Policy"]).get("Statement", [])


def _statement_source_arn(statement: dict) -> str:
    return str(statement.get("Condition", {}).get("ArnLike", {}).get("AWS:SourceArn") or "")


def ensure_invoke_permission(dry_run: bool) -> str:
    """Let API Gateway invoke the `live` ALIAS. Qualified, which is the whole point."""
    sid, want = statement_id(), source_arn()
    if dry_run:
        return (f"would grant lambda:InvokeFunction on :{LIVE_ALIAS} to "
                f"apigateway.amazonaws.com as {sid} for {want}")
    existing = {s.get("Sid"): s for s in live_policy_statements()}
    current = existing.get(sid)
    if current is None:
        lam().add_permission(
            FunctionName=FUNCTION_NAME,
            Qualifier=LIVE_ALIAS,
            StatementId=sid,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=want,
        )
        return f"granted {sid} for {want}"
    if _statement_source_arn(current) != want:
        # Reported, not silently repaired: `add_permission` cannot edit a statement, and
        # remove-then-add under a live id is the window this avoids.
        return (f"DRIFT: {sid} allows {_statement_source_arn(current)!r}, wanted {want!r} — "
                f"add a corrected statement under a NEW id, then retire this one")
    return f"{sid} already correct"


def _all_items(method: str) -> list:
    client = api()
    paginate, items, token = getattr(client, method), [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "1000"}
        if token:
            kwargs["NextToken"] = token
        page = paginate(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            return items


def find_integration(uri: str) -> str:
    for integration in _all_items("get_integrations"):
        if integration.get("IntegrationUri") == uri:
            return integration["IntegrationId"]
    return ""


def ensure_integration(dry_run: bool) -> tuple:
    """Reuse-or-create ONE AWS_PROXY integration pointing at the alias. Never modifies
    another."""
    uri = function_arn(qualified=True)
    if dry_run:
        return "", f"would create AWS_PROXY -> {uri}"
    existing = find_integration(uri)
    if existing:
        return existing, f"reusing {existing}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
        PayloadFormatVersion="2.0",
        Description="Customer invoice presign (read-only)")
    return created["IntegrationId"], f"created {created['IntegrationId']} -> {uri}"


def ensure_route(dry_run: bool, integration_id: str) -> str:
    """Create the one missing route. Never deletes or retargets an existing one.

    No `OPTIONS` twin: the API's CORS configuration answers the preflight.
    """
    if dry_run:
        return f"would create {ROUTE_KEY} on {API_ID} stage {STAGE}"
    existing = {r["RouteKey"]: r["RouteId"] for r in _all_items("get_routes")}
    if ROUTE_KEY in existing:
        return f"{ROUTE_KEY} exists ({existing[ROUTE_KEY]})"
    made = api().create_route(
        ApiId=API_ID, RouteKey=ROUTE_KEY, Target=f"integrations/{integration_id}")
    return f"created {ROUTE_KEY} ({made['RouteId']})"


# ── read-back verification ────────────────────────────────────────────────────

def verify() -> int:
    """Read every resource back and report. Reads only; never repairs."""
    problems = []

    try:
        live_policy = iam().get_role_policy(
            RoleName=ROLE_NAME, PolicyName=INLINE_POLICY_NAME)["PolicyDocument"]
        if live_policy == expected_role_policy():
            print(f"role {ROLE_NAME}: inline policy matches exactly")
        else:
            problems.append(f"{INLINE_POLICY_NAME} differs from expected_role_policy()")
            print(f"role {ROLE_NAME}: POLICY DRIFT")
    except ClientError as exc:
        problems.append(f"could not read {INLINE_POLICY_NAME}: "
                        f"{exc.response.get('Error', {}).get('Code', 'unknown')}")

    try:
        config = lam().get_function_configuration(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)
        env = dict((config.get("Environment") or {}).get("Variables") or {})
        print(f"function :{LIVE_ALIAS}: {config.get('Runtime')} "
              f"{config.get('MemorySize')}MB {config.get('Timeout')}s "
              f"v{config.get('Version')}")
        for key, value in expected_environment().items():
            if env.get(key) != value:
                problems.append(f"env {key} is {env.get(key)!r}, wanted {value!r}")
    except ClientError as exc:
        problems.append(f"could not read the {LIVE_ALIAS} alias: "
                        f"{exc.response.get('Error', {}).get('Code', 'unknown')}")

    statements = {s.get("Sid"): s for s in live_policy_statements()}
    if statement_id() not in statements:
        problems.append(f"no {statement_id()} statement on :{LIVE_ALIAS} — the route will "
                        f"answer 500 with no Lambda log line")
    elif _statement_source_arn(statements[statement_id()]) != source_arn():
        problems.append(f"{statement_id()} allows "
                        f"{_statement_source_arn(statements[statement_id()])!r}")
    else:
        print(f"invoke permission: {statement_id()} on :{LIVE_ALIAS}, exactly {source_arn()}")

    try:
        routes = {r["RouteKey"]: r for r in _all_items("get_routes")}
        if ROUTE_KEY in routes:
            print(f"route: {ROUTE_KEY} -> {routes[ROUTE_KEY].get('Target')}")
        else:
            problems.append(f"{ROUTE_KEY} does not exist on {API_ID}")
    except (ClientError, BotoCoreError) as exc:
        problems.append(f"could not read routes: {type(exc).__name__}")

    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: every resource reads back as expected")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually create/reconcile. Without it this is a dry run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="the default; accepted explicitly so a habit does not surprise.")
    parser.add_argument("--verify", action="store_true", help="read back and report only")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    dry_run = not args.apply
    print(f"region: {REGION}; account: {account_id()}")
    print(f"function: {FUNCTION_NAME}; role: {ROLE_NAME}; alias: {LIVE_ALIAS}")
    print(f"reads: {ORDERS_TABLE}/index/{ORDERS_BY_CUSTOMER_INDEX}, "
          f"{INVOICES_TABLE}/index/{INVOICES_BY_REFERENCE_INDEX}, {INVOICE_ASSETS_TABLE}, "
          f"s3://{MEDIA_BUCKET}/{INVOICE_PREFIX}*")
    print("creates no table and no index: every resource above is owned elsewhere")
    print(f"route: {ROUTE_KEY} on {API_ID} stage {STAGE} (no OPTIONS route — API CORS "
          f"answers the preflight)")
    print(f"invoke grant: Qualifier={LIVE_ALIAS!r} (NOT optional — a function-level "
          f"statement does not authorise an alias invoke)")
    print(f"dry run: {dry_run}\n")

    print("inline policy it would put:")
    print(json.dumps(expected_role_policy(), indent=2))
    print("\nenvironment it would set:")
    print(json.dumps(expected_environment(), indent=2))
    print()

    zip_bytes, members, errors, warnings = build_package()
    if report_package(zip_bytes, members, errors, warnings):
        return 1
    print()

    def step(label, fn, *args):
        """Run one step. In a DRY RUN an AWS read failure is reported, not raised.

        A dry run is a statement about what this script would do, and that statement is
        worth printing on a laptop with no live credentials - the plan above it is computed
        from pure functions. With `--apply` the same failure is fatal, because then it is a
        real step that did not happen.
        """
        try:
            print(f"{label}: {fn(*args)}")
        except (ClientError, BotoCoreError) as exc:
            if not dry_run:
                raise
            print(f"{label}: NOT MEASURED in a dry run ({type(exc).__name__})")

    step("role", ensure_role, dry_run)
    step("log group", ensure_log_group, dry_run)
    step("Lambda", ensure_function, dry_run, zip_bytes)
    step("env", reconcile_environment, dry_run)
    step("live alias", ensure_live_alias, dry_run)
    step("invoke permission", ensure_invoke_permission, dry_run)
    integration_id, integration_note = ensure_integration(dry_run)
    print(f"integration: {integration_note}")
    step("route", ensure_route, dry_run, integration_id)

    if dry_run:
        print("\ndry run: nothing changed. Re-run with --apply to provision.")
        return 0

    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
