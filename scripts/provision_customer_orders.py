"""Provision and verify `wecare-customer-orders` — the customer's own order history read.

What it stands up, in this order
-------------------------------
1. `customerId-createdAt-index` on `stack-wecare-digital-OrderTable`, then polls
   `describe_table` until `IndexStatus == 'ACTIVE'`, then the same for
   `customerId-createdAt-v2-index` (sequentially: one GSI operation in flight per table).
2. `wecare-customer-orders-role`: trusts `lambda.amazonaws.com` only, carries
   `AWSLambdaBasicExecutionRole` and ONE inline policy equal to `expected_role_policy()`.
3. The log group, 30-day retention (the fleet default).
4. The package, with every top-level import validated against the zip before anything is created.
5. The function (python3.12, 512 MB, 15 s) and its five environment variables.
6. The `live` alias, so this function is on the publish-and-move path from day one.
7. `lambda:AddPermission` on the ALIAS, then
8. the `AWS_PROXY` integration against the alias ARN and the route `POST /ecommerce/my-orders`.

THIS SCRIPT IS THE SINGLE SOURCE OF TRUTH FOR THE INDEX NAME. `amplify/data/resource.ts`
declares the index for documentation parity only — there are zero AppSync APIs in this account,
so no `a.model()` block in that file has ever been materialised. The handler defaults
`ORDERS_BY_CUSTOMER_INDEX` to the same literal as `ORDERS_BY_CUSTOMER_INDEX` here, and
`tests/test_customer_orders_iam.py` asserts the two agree, so a rename in one place is a red test
rather than a 503 in production.

THERE ARE TWO INDEXES, AND THE SECOND ONE EXISTS BECAUSE OF THE PARAGRAPH BELOW.
`customerId-createdAt-v2-index` is `customerId-createdAt-index` plus `channel` in the projection.
It is a NEW index rather than a widened one, because a projection cannot be widened; v1 keeps
serving, unchanged, while v2 is created and backfilled beside it. `SERVING_INDEX` names the one
the function actually queries and is still v1 - the move is `--repoint-serving-index`, which
refuses unless `describe_table` reports v2 ACTIVE, because a Query against a CREATING index
raises ResourceNotFoundException and this handler answers that with a 503 and no partial list.

A GSI PROJECTION IS IMMUTABLE AFTER CREATION. Widening or narrowing one means deleting and
recreating the index. So a projection mismatch on a re-run is REPORTED and never reconciled:
silently recreating an index would leave every customer's order list returning partial results
while it backfills. `purchasedSnapshot` is deliberately outside the projection — it is the frozen
cart including a delivery address, and `INCLUDE` keeps a second copy of it out of the index
entirely. That is data minimisation enforced by the storage layer, and the role below makes it
structural: `dynamodb:Query` on the index ARN with no statement on the table means a `GetItem`
for the snapshot is an AccessDeniedException.

NOTHING OUTSIDE THIS SCRIPT KNOWS THE INDEX IS MEANT TO EXIST. `scripts/check_data_model_drift.py`
maps Amplify models to table names and does not assert a `DescribeTable` for `OrderTable`, so a
deleted index would surface as a 503 in production rather than as a red test. The gap is closed as
far as the repo can close it (the name-equality case above) and the live existence check is this
script's idempotent reconcile. Stated here so it stays visible.

`Qualifier="live"` on step 7 is NOT optional. A function-level statement does not authorise an
invoke of an ALIAS, so step 8's integration would be unauthorised while step 7 reported success.
`scripts/provision_checkout.py:601-612` records the symptom: a 500 with no Lambda log line at all,
because the function is never entered.

There is no `OPTIONS` route. The API carries a CORS configuration, so API Gateway answers the
preflight itself — which is why the four `POST /ecommerce/*` checkout routes have no `OPTIONS`
twin. The handler still answers `OPTIONS` first, so a route could be added later with no code
change.

NO CREDENTIAL IS READ, WRITTEN OR NAMED. This function reads no secret: there is no Secrets
Manager statement in the role, and nothing here resolves one. Per
.kiro/steering/secret-handling.md no credential value is ever placed on a command line or a log
line, and this script has none to place.

`config/lambda-env-manifest.json` is updated AFTER the first successful deploy, not here: it is a
record of what is live, and its `_functions`/`_variables` counters are pinned by
tests/test_provision_checkout_contract.py, so the entry and both counters move in one later edit.

Usage:
    python scripts/provision_customer_orders.py --dry-run     # default; changes nothing
    python scripts/provision_customer_orders.py --apply
    python scripts/provision_customer_orders.py --verify
    # then, as a SEPARATE decision once v2 reports ACTIVE:
    python scripts/provision_customer_orders.py --repoint-serving-index            # dry run
    python scripts/provision_customer_orders.py --repoint-serving-index --apply

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-customer-orders
and then `python scripts/snapstart_publish.py wecare-customer-orders`, or the route keeps serving
the old code — the integration targets the alias, not $LATEST.
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
FUNCTION_NAME = "wecare-customer-orders"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-customer-orders-role"
INLINE_POLICY_NAME = "customer-orders-read"

#: The account's single HTTP API and its only stage, which auto-deploys. There is no `$default`
#: stage, so the raw execute-api host needs the `/prod` segment; the apex `/api/*` rewrite adds it.
API_ID = "zllr9lrg7j"
STAGE = "prod"
ROUTE_KEY = "POST /ecommerce/my-orders"

#: Declared ABOVE `expected_role_policy` on purpose: the policy builder is the document three
#: things reason about (create, reconcile, and tests/test_customer_orders_iam.py), so every name
#: it interpolates has to be a module constant rather than something resolved at call time.
#:
#: SINGULAR `OrderTable`. The environment variable is plural and the table is not.
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
ORDERS_BY_CUSTOMER_INDEX = "customerId-createdAt-index"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CONTACTS_PHONE_INDEX = "phone-index"
RATE_LIMIT_TABLE = "stack-wecare-digital-RateLimitTable"

#: The CUSTOMER pool, deliberately not the staff pool. `customer_auth` pins the token issuer to
#: it, and a single env var holding "the pool" is how the two get confused.
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_SOURCE = "ecommerce/customer-orders"

#: `customerId` (HASH, S) / `createdAt` (RANGE, N).
#:
#: The three KEY attributes — `customerId`, `createdAt` and the table's own `orderId` — are
#: projected automatically and must NOT be repeated in `NonKeyAttributes`; `UpdateTable` rejects
#: the duplication. The list below is exactly the set the handler returns, so the query needs no
#: follow-up `GetItem` and `purchasedSnapshot` is never fetched at all.
#:
#: `orderFirstName`/`orderLastName` were considered and DROPPED: they do not exist on the website
#: lineage (`finalization.accept_paid`'s order item carries no name field) and nothing reads them.
#: Projecting speculative attributes to avoid a future delete-and-recreate is a defensible trade,
#: but not for attributes no writer produces.
INDEX_NON_KEY_ATTRIBUTES = ["orderNumber", "referenceId", "amountPaise", "currency",
                            "paymentStatus"]

INDEX_DEFINITION = {
    "IndexName": ORDERS_BY_CUSTOMER_INDEX,
    "KeySchema": [
        {"AttributeName": "customerId", "KeyType": "HASH"},
        {"AttributeName": "createdAt", "KeyType": "RANGE"},
    ],
    "Projection": {
        "ProjectionType": "INCLUDE",
        "NonKeyAttributes": list(INDEX_NON_KEY_ATTRIBUTES),
    },
}

#: A SECOND INDEX, NOT AN EDIT TO THE FIRST, and the reason is stated at :118-137 and :349-356
#: above: A GSI PROJECTION IS IMMUTABLE AFTER CREATION. `channel` has to reach `/orders`, and
#: widening `customerId-createdAt-index` to carry it would mean deleting and recreating the index
#: every order list is served from - which leaves every customer's history returning PARTIAL
#: results for as long as the backfill takes. So the old index keeps serving, unchanged, while
#: this one is created and backfilled beside it.
#:
#: Same key schema, deliberately: this is the same query, and a different partition or sort key
#: would make the repoint a behaviour change rather than a projection change.
#:
#: `channel` projects cleanly because it is one short word - unlike `items`, which is why the
#: detail panel still says item details are unavailable. Adding `items` here is not a free ride
#: on this index: it is `purchasedSnapshot`, tens of kilobytes including a delivery address, and
#: keeping a second copy of it out of the index is the data minimisation the module docstring and
#: the IAM grant exist to enforce.
ORDERS_BY_CUSTOMER_INDEX_V2 = "customerId-createdAt-v2-index"

INDEX_NON_KEY_ATTRIBUTES_V2 = INDEX_NON_KEY_ATTRIBUTES + ["channel"]

INDEX_DEFINITION_V2 = {
    "IndexName": ORDERS_BY_CUSTOMER_INDEX_V2,
    "KeySchema": [
        {"AttributeName": "customerId", "KeyType": "HASH"},
        {"AttributeName": "createdAt", "KeyType": "RANGE"},
    ],
    "Projection": {
        "ProjectionType": "INCLUDE",
        "NonKeyAttributes": list(INDEX_NON_KEY_ATTRIBUTES_V2),
    },
}

#: WHICH INDEX THE FUNCTION ACTUALLY QUERIES. Still v1, and that is the whole point of this
#: constant existing rather than `expected_environment` naming an index directly.
#:
#: The repoint is DEFERRED TO LAND TIME AND GATED ON ACTIVE. A Query against a CREATING index
#: raises ResourceNotFoundException, which the handler turns into a 503 - so pointing the live
#: function at v2 in the same change that creates it would break every order list between the
#: `update_table` call and the end of the backfill. `--repoint-serving-index` performs the move
#: and REFUSES unless `describe_table` reports v2 ACTIVE; nothing else in this script moves it.
#:
#: Until then `channel` is written on every new order row and read through
#: `order_channel.canonical`, which answers `website` for a row the serving projection does not
#: carry it on. So the page is correct, not broken, while the repoint waits.
SERVING_INDEX = ORDERS_BY_CUSTOMER_INDEX

#: A table allows only ONE GSI operation in flight, and creation is not instant to report. A
#: Query against a CREATING index raises ResourceNotFoundException, which a reader mistakes for
#: "the index name is wrong" — so the IAM attach and the publish wait for ACTIVE.
INDEX_POLL_SECONDS = 10
INDEX_POLL_ATTEMPTS = 90

_account_id_cache = None


def account_id() -> str:
    """The account, or the literal `<account>` when STS cannot be reached.

    A dry run must be able to print the policy it WOULD put without credentials, so an
    unreachable STS degrades to a placeholder that is obviously not an account id rather than to
    a traceback.
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


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def source_arn() -> str:
    """The exact source ARN API Gateway presents for this one route. No wildcard at all.

    API Gateway presents `{apiId}/{stage}/{METHOD}/{path}`. A prefix such as
    `{STAGE}/POST/ecommerce/*` was rejected on `provision_checkout.py` after measurement: another
    session had grown a third route into that namespace, so the prefix authorised an invoke for a
    route belonging to a different function. A prefix describes a namespace somebody else can
    grow into, which is not the same as "the route this function serves".
    """
    method, path = ROUTE_KEY.split(" ", 1)
    return f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}"


def statement_id() -> str:
    """Route-specific, and NEW rather than reused.

    `add_permission` cannot edit a statement, and remove-then-add under one id opens a window
    where API Gateway cannot invoke the function. There are no legacy ids to retire here because
    the function is new.
    """
    method, path = ROUTE_KEY.split(" ", 1)
    return f"apigateway-invoke-{method.lower()}{path.replace('/', '-')}"


def _not_found(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


# ── the policy, as one pure builder ───────────────────────────────────────────

def expected_role_policy(acct: str | None = None) -> dict:
    """The one inline policy this role carries. Pure, so create, reconcile and the test agree.

    What is ABSENT is the point: no `GetItem` and no `BatchGetItem` anywhere, no `PutItem`,
    `UpdateItem` or `DeleteItem` on either the order table or the contacts table, no `Scan`, no
    Secrets Manager, no `cognito-idp`, no `lambda:InvokeFunction`, no `sns`/`sqs`/`ses`. The
    function is incapable of writing an order, of charging, of refunding and of messaging anyone.
    """
    acct = acct or account_id()
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                # THE INDEX ARN, NOT THE TABLE ARN. This is the second layer of the security
                # boundary and it is cheap: with no permission on the table itself, a Scan or a
                # GetItem is an AccessDeniedException rather than a code review finding. The only
                # read this role can perform on the order table is a Query through an index whose
                # partition key is the Cognito subject.
                "Sid": "QueryOwnOrdersByCustomer",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{ORDERS_TABLE}"
                    f"/index/{ORDERS_BY_CUSTOMER_INDEX}",
                    # EXACTLY ONE MORE INDEX ARN, and no new verb. The repoint to v2 needs the
                    # grant in place BEFORE the env var moves, or the first query after the move
                    # is an AccessDeniedException; and v1 keeps its grant because it keeps
                    # serving until that move happens. Both are index ARNs, so the structural
                    # property holds unchanged: there is still no statement on the order TABLE,
                    # which is what makes a `GetItem` for `purchasedSnapshot` an
                    # AccessDeniedException rather than a code review finding.
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{ORDERS_TABLE}"
                    f"/index/{ORDERS_BY_CUSTOMER_INDEX_V2}",
                ],
            },
            {
                # Mirrors wecare-checkout-role's ReadVerifiedCheckoutProfile, verbatim in scope:
                # Query on the index only, never on the table, so contact rows cannot be scanned
                # and no row can be fetched by id.
                "Sid": "ReadOwnContactProfile",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}"
                    f"/index/{CONTACTS_PHONE_INDEX}"
                ],
            },
            {
                # HASH `id` only. `check_rate_limit` is one atomic increment on a fully specified
                # key, so it needs no Query, no Scan and no delete.
                "Sid": "RateLimitCounter",
                "Effect": "Allow",
                "Action": ["dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{RATE_LIMIT_TABLE}"],
            },
        ],
    }


def expected_environment(serving_index: str | None = None) -> dict:
    """Five variables, every one of them a NAME. No value here can enable anything.

    `serving_index` defaults to `SERVING_INDEX` so this stays PURE and keeps answering the same
    document on a laptop with no credentials. `--repoint-serving-index` passes
    `ORDERS_BY_CUSTOMER_INDEX_V2` explicitly, and only after `describe_table` has reported it
    ACTIVE - the argument exists so that check lives in one place instead of being inferred here
    from an AWS call this function must not make.
    """
    return {
        "ORDERS_TABLE": ORDERS_TABLE,
        "ORDERS_BY_CUSTOMER_INDEX": serving_index or SERVING_INDEX,
        "CONTACTS_TABLE": CONTACTS_TABLE,
        "RATE_LIMIT_TABLE": RATE_LIMIT_TABLE,
        "CUSTOMER_POOL_ID": CUSTOMER_POOL_ID,
    }


# ── packaging, delegated ──────────────────────────────────────────────────────

def _deploy_module():
    """`scripts/deploy_all_lambdas.py` loaded by path, because `scripts/` is not a package.

    Delegated deliberately: this script CREATES the function and `deploy_all_lambdas.py` updates
    it forever after, so a private packer here would mean the first package and every later one
    were assembled by different code. It also moves validation BEFORE `create_function`, where an
    unresolved import is a refusal instead of a cold-start `Unable to import module`.
    """
    script = ROOT / "scripts" / "deploy_all_lambdas.py"
    loader = importlib.util.spec_from_file_location("deploy_all_lambdas", script)
    module = importlib.util.module_from_spec(loader)
    sys.modules["deploy_all_lambdas"] = module
    loader.loader.exec_module(module)
    return module


def build_package() -> tuple:
    """`(zip_bytes, members, errors, warnings)`. `provided` is empty: this function has no layer,
    so every import must resolve inside the package or in the python3.12 runtime."""
    dal = _deploy_module()
    spec = dal.Spec(FUNCTION_NAME, FUNCTION_SOURCE,
                    provisioned_by="python scripts/provision_customer_orders.py")
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


# ── step 1: the index ─────────────────────────────────────────────────────────

def describe_index(index_name: str = ORDERS_BY_CUSTOMER_INDEX) -> tuple:
    """`(index_description_or_None, note)`. A read failure is reported, never assumed absent.

    Takes the name so v1 and v2 are read by the SAME function: two copies would be two chances
    for one of them to stop distinguishing "absent" from "unreadable", and that distinction is
    what stops this script creating an index that already exists.
    """
    try:
        table = ddb().describe_table(TableName=ORDERS_TABLE)["Table"]
    except ClientError as exc:
        return None, f"NOT MEASURED ({exc.response.get('Error', {}).get('Code', 'unknown')})"
    except BotoCoreError as exc:
        return None, f"NOT MEASURED ({type(exc).__name__})"
    for index in table.get("GlobalSecondaryIndexes") or []:
        if index.get("IndexName") == index_name:
            return index, f"status {index.get('IndexStatus')}"
    return None, "absent"


def _projection_drift(index: dict, wanted_attributes=None) -> str:
    """`''` when the live projection matches, otherwise the mismatch to REPORT (never repair)."""
    projection = index.get("Projection") or {}
    kind = projection.get("ProjectionType")
    live = set(projection.get("NonKeyAttributes") or [])
    wanted = set(INDEX_NON_KEY_ATTRIBUTES if wanted_attributes is None else wanted_attributes)
    if kind == "INCLUDE" and live == wanted:
        return ""
    return (f"PROJECTION DRIFT: live type={kind} attributes={sorted(live)}; wanted "
            f"type=INCLUDE attributes={sorted(wanted)}. A GSI projection is IMMUTABLE after "
            f"creation, so this script will NOT reconcile it — recreating the index would leave "
            f"every order list returning partial results while it backfills. Delete and recreate "
            f"it deliberately if the projection must change.")


def ensure_index(dry_run: bool) -> str:
    existing, note = describe_index()
    if existing is not None:
        drift = _projection_drift(existing)
        status = existing.get("IndexStatus")
        if drift:
            return f"{note}; {drift}"
        if status != "ACTIVE" and not dry_run:
            return f"exists ({note}); {wait_for_index()}"
        return f"exists and projection matches ({note})"
    if note.startswith("NOT MEASURED"):
        return f"could not read {ORDERS_TABLE}: {note}"
    if dry_run:
        return (f"would create GSI {ORDERS_BY_CUSTOMER_INDEX} on {ORDERS_TABLE} — "
                f"customerId (HASH, S) / createdAt (RANGE, N), INCLUDE "
                f"{INDEX_NON_KEY_ATTRIBUTES}, then poll to ACTIVE")
    ddb().update_table(
        TableName=ORDERS_TABLE,
        AttributeDefinitions=[
            {"AttributeName": "customerId", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexUpdates=[{"Create": INDEX_DEFINITION}],
    )
    return f"creation requested; {wait_for_index()}"


def ensure_index_v2(dry_run: bool) -> str:
    """The `channel`-carrying index, created BESIDE v1 and never instead of it.

    A table allows only ONE GSI operation in flight, so this runs after `ensure_index` has
    settled - and if v1 is still CREATING, `update_table` answers
    LimitExceededException/ResourceInUseException, which is reported rather than retried: two
    creations racing on one table is not a condition to paper over.

    The env repoint is NOT here. It is `--repoint-serving-index`, which refuses unless this index
    reads ACTIVE first.
    """
    existing, note = describe_index(ORDERS_BY_CUSTOMER_INDEX_V2)
    if existing is not None:
        drift = _projection_drift(existing, INDEX_NON_KEY_ATTRIBUTES_V2)
        status = existing.get("IndexStatus")
        if drift:
            return f"{note}; {drift}"
        if status != "ACTIVE" and not dry_run:
            return f"exists ({note}); {wait_for_index(ORDERS_BY_CUSTOMER_INDEX_V2)}"
        return f"exists and projection matches ({note})"
    if note.startswith("NOT MEASURED"):
        return f"could not read {ORDERS_TABLE}: {note}"
    if dry_run:
        return (f"would create GSI {ORDERS_BY_CUSTOMER_INDEX_V2} on {ORDERS_TABLE} — "
                f"customerId (HASH, S) / createdAt (RANGE, N), INCLUDE "
                f"{INDEX_NON_KEY_ATTRIBUTES_V2}, then poll to ACTIVE. The serving env var stays "
                f"on {SERVING_INDEX} until --repoint-serving-index is run against an ACTIVE "
                f"index")
    ddb().update_table(
        TableName=ORDERS_TABLE,
        AttributeDefinitions=[
            {"AttributeName": "customerId", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexUpdates=[{"Create": INDEX_DEFINITION_V2}],
    )
    return f"creation requested; {wait_for_index(ORDERS_BY_CUSTOMER_INDEX_V2)}"


def repoint_serving_index(dry_run: bool) -> str:
    """Move `ORDERS_BY_CUSTOMER_INDEX` to v2. REFUSES unless v2 reads ACTIVE.

    The ACTIVE check is the whole function. A Query against a CREATING index raises
    ResourceNotFoundException, which this handler turns into a 503 with no partial answer - so a
    repoint performed a moment too early takes every customer's order history down for the length
    of a backfill. Measured, not assumed: the status comes from `describe_table`, and an
    unreadable table refuses rather than defaulting to "probably fine".

    Deliberately NOT part of the normal `--apply` run. Creating the index and moving production
    onto it are two decisions, and bundling them is how the second one gets made by accident.
    """
    index, note = describe_index(ORDERS_BY_CUSTOMER_INDEX_V2)
    if index is None:
        return (f"REFUSED: {ORDERS_BY_CUSTOMER_INDEX_V2} is {note}. Run --apply first and let it "
                f"reach ACTIVE.")
    status = index.get("IndexStatus")
    if status != "ACTIVE":
        return (f"REFUSED: {ORDERS_BY_CUSTOMER_INDEX_V2} is {status}, not ACTIVE. A Query against "
                f"a CREATING index is a ResourceNotFoundException, which this handler answers as "
                f"a 503 — every order list would fail until the backfill finished.")
    drift = _projection_drift(index, INDEX_NON_KEY_ATTRIBUTES_V2)
    if drift:
        return f"REFUSED: {drift}"
    wanted = expected_environment(ORDERS_BY_CUSTOMER_INDEX_V2)["ORDERS_BY_CUSTOMER_INDEX"]
    if not function_exists():
        return "function absent - nothing to repoint"
    config = lam().get_function_configuration(FunctionName=FUNCTION_NAME)
    current = dict((config.get("Environment") or {}).get("Variables") or {})
    if current.get("ORDERS_BY_CUSTOMER_INDEX") == wanted:
        return f"already serving from {wanted}"
    if dry_run:
        return (f"would set ORDERS_BY_CUSTOMER_INDEX={wanted} "
                f"(was {current.get('ORDERS_BY_CUSTOMER_INDEX')!r}); v2 reads ACTIVE with "
                f"{int(index.get('ItemCount') or 0)} items backfilled")
    current["ORDERS_BY_CUSTOMER_INDEX"] = wanted
    lam().update_function_configuration(
        FunctionName=FUNCTION_NAME, Environment={"Variables": current})
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    # `$LATEST` only. The route invokes the ALIAS, so this is not serving until a version is
    # published and `live` is moved - `python scripts/snapstart_publish.py wecare-customer-orders`
    # - with the rollback version captured first.
    return (f"set ORDERS_BY_CUSTOMER_INDEX={wanted} on $LATEST. NOT LIVE YET: publish a version "
            f"and move the `live` alias, or the route keeps querying {SERVING_INDEX}.")


def wait_for_index(index_name: str = ORDERS_BY_CUSTOMER_INDEX) -> str:
    """Poll until ACTIVE. Nothing downstream may run before this returns.

    A Query against a CREATING index raises ResourceNotFoundException, so attaching the policy or
    publishing the function first would produce a failure that reads as a wrong index name.
    """
    for _ in range(INDEX_POLL_ATTEMPTS):
        index, note = describe_index(index_name)
        if index is not None and index.get("IndexStatus") == "ACTIVE":
            return f"ACTIVE ({int(index.get('ItemCount') or 0)} items backfilled)"
        if index is None and note.startswith("NOT MEASURED"):
            return f"gave up waiting: {note}"
        time.sleep(INDEX_POLL_SECONDS)
    return "TIMED OUT waiting for ACTIVE — do not publish until describe-table says ACTIVE"


# ── steps 2-8 ─────────────────────────────────────────────────────────────────

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
    """Create OR reconcile. Returning early because the role exists is how an older, wider live
    policy survives while the code and the verifier have moved on. `put_role_policy` is an
    idempotent replacement of this function's one owned inline policy."""
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
            Description="Customer order-history read (own orders only) execution role",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "CustomerOrders"}],
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
            "Project": "WECARE.DIGITAL", "Purpose": "CustomerOrders"})
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
                Description="Customer order history and profile summary. Read-only: one Query "
                            "on the customer-scoped index, no write verb of any kind.",
                Timeout=15,
                MemorySize=512,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "CustomerOrders"},
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
        FunctionName=FUNCTION_NAME, Description="initial customer order-history release")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Production customer order-history target")
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
        return (f"DRIFT: {sid} allows {_statement_source_arn(current)!r}, wanted {want!r} — add "
                f"a corrected statement under a NEW id, then retire this one")
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
    """Reuse-or-create ONE AWS_PROXY integration pointing at the alias. Never modifies another."""
    uri = function_arn(qualified=True)
    if dry_run:
        return "", f"would create AWS_PROXY -> {uri}"
    existing = find_integration(uri)
    if existing:
        return existing, f"reusing {existing}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
        PayloadFormatVersion="2.0",
        Description="Customer order history (read-only)")
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

    index, note = describe_index()
    print(f"index {ORDERS_BY_CUSTOMER_INDEX}: {note}")
    if index is None:
        problems.append("the index is absent or unreadable")
    else:
        drift = _projection_drift(index)
        if drift:
            problems.append(drift)
        if index.get("IndexStatus") != "ACTIVE":
            problems.append(f"index status is {index.get('IndexStatus')}, not ACTIVE")

    # v2 is REPORTED, not required. It is absent until `--apply` runs after this change, and an
    # absent v2 is not a fault: v1 is still the serving index, `channel` still reaches the order
    # ROW, and `order_channel.canonical` answers `website` for a projection that does not carry
    # it. Calling that a problem would make `--verify` fail on a correct intermediate state.
    index_v2, note_v2 = describe_index(ORDERS_BY_CUSTOMER_INDEX_V2)
    print(f"index {ORDERS_BY_CUSTOMER_INDEX_V2}: {note_v2} "
          f"(serving: {SERVING_INDEX}; repoint with --repoint-serving-index once ACTIVE)")
    if index_v2 is not None:
        drift_v2 = _projection_drift(index_v2, INDEX_NON_KEY_ATTRIBUTES_V2)
        if drift_v2:
            problems.append(drift_v2)

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
            if key == "ORDERS_BY_CUSTOMER_INDEX":
                # EITHER index is correct here, and that is not laxness: the repoint is a
                # separate deliberate step, so both "before" and "after" are valid live states
                # and `--verify` must pass in both. What would be wrong is a THIRD value, which
                # this still catches.
                if env.get(key) not in (ORDERS_BY_CUSTOMER_INDEX, ORDERS_BY_CUSTOMER_INDEX_V2):
                    problems.append(f"env {key} is {env.get(key)!r}, wanted one of "
                                    f"{ORDERS_BY_CUSTOMER_INDEX!r} or "
                                    f"{ORDERS_BY_CUSTOMER_INDEX_V2!r}")
                continue
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
    parser.add_argument("--repoint-serving-index", action="store_true",
                        help=f"move ORDERS_BY_CUSTOMER_INDEX to {ORDERS_BY_CUSTOMER_INDEX_V2}. "
                             f"Refuses unless that index reports ACTIVE. Needs --apply to write; "
                             f"without it this is a dry run.")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    dry_run = not args.apply

    if args.repoint_serving_index:
        # ON ITS OWN, deliberately. The repoint is the one step in this script that can take a
        # working order list down, so it does not ride along with a provision run that somebody
        # launched for a different reason.
        print(f"repoint: {repoint_serving_index(dry_run)}")
        if dry_run:
            print("\ndry run: nothing changed. Re-run with --apply to repoint.")
        return 0
    print(f"region: {REGION}; account: {account_id()}")
    print(f"function: {FUNCTION_NAME}; role: {ROLE_NAME}; alias: {LIVE_ALIAS}")
    print(f"table: {ORDERS_TABLE}; index: {ORDERS_BY_CUSTOMER_INDEX}")
    print(f"second index: {ORDERS_BY_CUSTOMER_INDEX_V2} (adds `channel`; a GSI projection is "
          f"IMMUTABLE, so this is a new index, not a widened one)")
    print(f"serving index: {SERVING_INDEX} — the repoint to "
          f"{ORDERS_BY_CUSTOMER_INDEX_V2} is a SEPARATE step (--repoint-serving-index) and "
          f"refuses unless that index reports ACTIVE")
    print(f"route: {ROUTE_KEY} on {API_ID} stage {STAGE} (no OPTIONS route — API CORS answers "
          f"the preflight)")
    print(f"invoke grant: Qualifier={LIVE_ALIAS!r} (NOT optional — a function-level statement "
          f"does not authorise an alias invoke)")
    print(f"dry run: {dry_run}\n")

    print("inline policy it would put:")
    print(json.dumps(expected_role_policy(), indent=2))
    print("\nindex definitions it would create (v1 first; one GSI operation in flight per table):")
    print(json.dumps([INDEX_DEFINITION, INDEX_DEFINITION_V2], indent=2))
    print("\nenvironment it would set:")
    print(json.dumps(expected_environment(), indent=2))
    print()

    zip_bytes, members, errors, warnings = build_package()
    if report_package(zip_bytes, members, errors, warnings):
        return 1
    print()

    def step(label, fn, *args):
        """Run one step. In a DRY RUN an AWS read failure is reported, not raised.

        A dry run is a statement about what this script would do, and that statement is worth
        printing on a laptop with no live credentials - the plan above it is computed from pure
        functions. With `--apply` the same failure is fatal, because then it is a real step that
        did not happen.
        """
        try:
            print(f"{label}: {fn(*args)}")
        except (ClientError, BotoCoreError) as exc:
            if not dry_run:
                raise
            print(f"{label}: NOT MEASURED in a dry run ({type(exc).__name__})")

    step("index", ensure_index, dry_run)
    # AFTER v1 and never beside it: a table allows only ONE GSI operation in flight, and
    # `ensure_index` does not return until its own creation reports ACTIVE.
    step("index v2", ensure_index_v2, dry_run)
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
