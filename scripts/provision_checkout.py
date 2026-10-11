#!/usr/bin/env python3
"""Provision and verify the customer checkout Lambda.

What it stands up
-----------------
- A least-privilege execution role: logs; read of the Wix admin API key secret; read/write on the
  payment-attempts table and the commerce-keys (reference reservation) table; and
  `lambda:InvokeFunction` on the WhatsApp business Lambda (used for the readiness payment-config
  read and, once initiation is enabled, the in-chat order_details send). It has NO Cognito IAM
  permission — `customer_auth.authenticate` calls `GetUser` with the *customer's own* access token,
  which authorises itself and needs no role permission. It has NO order-creation permission of any
  kind, because checkout never creates an order.
- The function `wecare-checkout`, then a published version and the `live` alias.
- The two HTTP API routes its only two consumers call, an `AWS_PROXY` integration pointing at the
  `live` alias, and the alias-qualified `lambda:AddPermission` that lets API Gateway invoke it.
  Without that last piece a route exists and answers 500 with no Lambda log line at all, because a
  function-level statement does not authorise an *alias* invoke — the exact failure
  `scripts/provision_missing_ui_routes.py` documents for `POST /plivo/dial-events`. There is one
  statement per route, each carrying that route's exact source ARN, so the grant contains no
  wildcard at all — see `source_arn`, which records why the obvious `/ecommerce/*` prefix was not
  good enough.

Initiation stays OFF. `CHECKOUT_INITIATION_ENABLED` is deliberately absent from the environment
this script sets, so the deployed function prepares attempts and reserves references but sends no
payable message until someone sets that flag on purpose. Readiness inputs
(`EXPECTED_CONFIGURATION_NAME`, `EXPECTED_PROVIDER_MID`) are also left empty here, so even if
initiation were flipped on, `payment_readiness` blocks until an owner supplies the values from a
live Meta/Razorpay read. There is no path from this script to a live charge.

Packaging is delegated, deliberately
------------------------------------
The ZIP is built by `scripts/deploy_all_lambdas.build_zip` and checked by its `validate` /
`validate_handler`, rather than by a private zip helper here. Two reasons, both load-bearing:

1. **The two scripts can no longer produce different bytes for the same function.** This script
   creates `wecare-checkout`; `deploy_all_lambdas.py` updates it forever after. A private packer
   here meant the first package and every later one were assembled by different code.
2. **Validation now happens BEFORE `create_function`.** `deploy_all_lambdas.py` calls
   `get_function_configuration` before `validate()`, so for an absent function it takes the
   `awaiting_provisioning` branch and never validates — its `--dry-run` could not check this
   function until after it existed. An unresolved import would therefore have surfaced as a
   cold-start `Unable to import module` on the first real request.

`--source-root` exists so the package can be built from a clean `git archive` of reviewed code
while the script itself runs from the working tree. The shared tree is routinely dirty with other
sessions' in-flight edits, and a package built from it would ship a handler whose siblings are
stale.

`--verify` defaults `--source-root` to that same export instead of to the working tree, and prints
which root it used either way. That export is now only a COMPARISON: `--verify` downloads the
artifact off the `live` alias and scopes the import validation, the reachability closure and the
IAM grant report to those bytes. A report about a package nobody deployed is a report about
nothing, and for one afternoon that is exactly what was on record — another session published v2
and moved the alias while every package-derived conclusion still described v1.

Usage:
    python scripts/provision_checkout.py --dry-run
    python scripts/provision_checkout.py --dry-run --source-root .scratch/deploy-checkout
    python scripts/provision_checkout.py --source-root .scratch/deploy-checkout
    python scripts/provision_checkout.py --verify

After first provision, normal code updates use:
    python scripts/deploy_all_lambdas.py wecare-checkout

Follows .kiro/steering/secret-handling.md: the Wix key is read by reference at runtime via a
SecretId name only; no credential is ever placed on a command line or in a log.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
FUNCTION_NAME = "wecare-checkout"
LIVE_ALIAS = "live"
ROLE_NAME = "wecare-checkout-role"

#: The account's single HTTP API ("wecare-digital-api") and its only stage, which auto-deploys.
#: There is no `$default` stage, so the raw execute-api host needs the `/prod` segment; the apex
#: `wecare.digital/api/*` rewrite supplies it.
API_ID = "zllr9lrg7j"
STAGE = "prod"

#: Exactly the two route keys this function's two consumers call — `src/pages/cart.tsx` POSTs
#: `/ecommerce/checkout` and `src/pages/checkout/status.tsx` POSTs `/ecommerce/checkout/status`.
#: Deliberately NOT a `{proxy+}`: the surface stays exactly as wide as its consumers, and
#: `handler._action` resolves `status` off the path suffix so both land on the right branch.
ROUTE_KEYS = (
    "POST /ecommerce/checkout",
    "POST /ecommerce/checkout/status",
    "POST /ecommerce/prepare-checkout",
    "POST /ecommerce/verify-callback",
    # The ONE anonymous arm: the four public service pages read their live Wix price from it
    # before a visitor has signed in. GET only, no input of any kind, and allow-listed by name in
    # `scripts/audit_route_auth.py` with its justification. `handler.handler` routes it ahead of
    # `require_customer`; every other method on this path still requires a session.
    "GET /ecommerce/service-prices",
)

#: The one anonymous route, and the per-route throttle that bounds what it can cost.
#:
#: WHY A THROTTLE EXISTS ON THIS ROUTE AND NOT THE OTHERS. Every other route key above requires a
#: proven customer session, so its volume is bounded by the number of signed-in customers. This
#: one is reachable by anyone, and a CACHE MISS on it costs EIGHT Wix calls (`get` + `estimate`
#: per variant) on the SAME API key the live checkout prices real baskets with -- so provider
#: throttling induced by anonymous traffic here would reach the payment path.
#:
#: It is the second of two bounds, deliberately, because the first one is not ours. The edge in
#: front of `/api/*` was MEASURED caching a `public, max-age` response on 2026-10-08 (see
#: `_service_prices` in the handler for the four-request trace), which is what keeps origin
#: volume to roughly one fill per PoP per minute. But that is a property of someone else's
#: configuration: an Amplify rewrite change, a `Cache-Control` edit, or a cache-busting query
#: string would remove it silently and nothing in this repo would notice. The throttle is the
#: bound that does not depend on the edge behaving.
#:
#: 5 rps sustained is far above any legitimate volume for a four-figure price list sitting behind
#: a 60-second shared cache, and far below what would trouble Wix. Refusals are 429s from API
#: Gateway, which `src/lib/servicePricing.ts` already treats as "unavailable" -- so exceeding it
#: fails closed on the page rather than charging or guessing.
PRICE_ROUTE_KEY = "GET /ecommerce/service-prices"
ROUTE_THROTTLE_RATE = 5.0
ROUTE_THROTTLE_BURST = 10

#: Superseded statement ids, removed only once the per-route statements are in place.
#: `add_permission` cannot EDIT a statement, and remove-then-add under one id opens a window where
#: API Gateway cannot invoke the function — a 500 with no Lambda log line. New ids let the narrow
#: statements go on FIRST: resource-policy statements are OR'd, so the route is never unauthorised.
#:
#:   apigateway-invoke-checkout            {API_ID}/*/*                 any stage, method and path
#:   apigateway-invoke-checkout-ecommerce  {STAGE}/POST/ecommerce/*     a prefix another session's
#:                                                                     route had already grown into
LEGACY_STATEMENT_IDS = ("apigateway-invoke-checkout", "apigateway-invoke-checkout-ecommerce")

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "amplify/functions/ecommerce/checkout"
SHARED_DIR = ROOT / "amplify/functions/shared"

#: Where the deployed artifact was exported from (`git archive origin/stack | tar -x`). `--verify`
#: prefers it over the working tree, because a verdict about a package nobody deployed is a verdict
#: about nothing — and in this repo the working tree routinely carries three other sessions'
#: uncommitted edits, all of which `build_zip` would package.
DEPLOY_SOURCE_ROOT = ROOT / ".scratch" / "deploy-checkout"

PAYMENT_ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
COMMERCE_KEYS_TABLE = "stack-wecare-digital-WixOrderIds"
#: Website checkout keeps coupons and gift cards Wix-authoritative. The legacy custom coupon and
#: gift-card stores have their own functions/roles and are deliberately NOT granted to checkout.
WIX_API_KEY_SECRET = "wecare/wix/headless-api-key"
RAZORPAY_API_SECRET = "wecare/razorpay/api"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
#: The internal order record. An order exists ONLY after an authoritative capture, and
#: `finalization.accept_paid` is what writes it. Granted GetItem/PutItem/UpdateItem and
#: explicitly NOT DeleteItem or Scan: an order record is evidence that money moved.
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
WIX_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"
#: The business-API Lambda. Holds the Meta token; answers the readiness readback.
SENDER_FUNCTION = "wecare-whatsapp-business-api"
#: The in-chat payment sender — the only function that composes a Meta `review_and_pay` message.
#: `wecare-checkout` invokes it for the native service leg, and WITHOUT the grant below that
#: invoke raises `AccessDeniedException` after the attempt, the reference and the one-shot claim
#: are all written, surfacing as a 500 that looks like a Meta problem.
OUTBOUND_SENDER_FUNCTION = "wecare-outbound-whatsapp"
PAYMENT_WABA_ID = "2094615664435155"

_account_id_cache = None


def account_id() -> str:
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = boto3.client(
            "sts", region_name=REGION).get_caller_identity()["Account"]
    return _account_id_cache


def iam():
    return boto3.client("iam")


def lam():
    return boto3.client("lambda", region_name=REGION)


def logs():
    return boto3.client("logs", region_name=REGION)


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def source_arn(route_key: str) -> str:
    """The exact source ARN API Gateway presents for one route key. No wildcard at all.

    Narrowed twice on 2026-10-01, and the second step is the one worth explaining. The original
    `{API_ID}/*/*` authorised any stage and any method/path on this API — scoped to one API, so
    never a wildcard over the account, but 360 routes wider than the two that exist. The obvious
    replacement was the prefix `{STAGE}/POST/ecommerce/*`; it was applied, and then measured:
    another session had added `POST /ecommerce/customer-session`, so that prefix already matched a
    third route belonging to a different function. A prefix describes a namespace somebody else can
    grow into, which is not the same as "the routes this function serves".

    API Gateway presents `{apiId}/{stage}/{METHOD}/{path}`, so one statement per route key matches
    exactly `POST /ecommerce/checkout` and `POST /ecommerce/checkout/status`. `prod` is spelled out
    rather than `*` because it is the only stage on `zllr9lrg7j` and there is no `$default`.
    """
    method, path = route_key.split(" ", 1)
    return f"arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}"


def route_statement_id(route_key: str) -> str:
    """A stable, readable statement id per route, so re-running replaces rather than accumulates."""
    method, path = route_key.split(" ", 1)
    return f"apigateway-invoke-{method.lower()}{path.replace('/', '-')}"


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{account_id()}:function:{FUNCTION_NAME}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def _not_found(exc: ClientError, *codes: str) -> bool:
    return exc.response.get("Error", {}).get("Code") in codes


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


def is_repo_root(path: Path) -> bool:
    """A directory `build_package` can actually package the checkout function from."""
    return (path / "amplify" / "functions" / "ecommerce" / "checkout" / "handler.py").is_file()


def resolve_source_root(explicit: str | None, *, prefer_deploy_export: bool) -> tuple:
    """Return `(root, why)`. `why` is printed, so no verdict is ever anonymous.

    Two different defaults on purpose. A provisioning run packages what the operator points it at
    and says so; a `--verify` run is a statement ABOUT the deployed artifact, so it defaults to the
    export that artifact was built from and labels the fallback as not-the-deployed-package.
    """
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return root, f"{root} (given on the command line)"
    if prefer_deploy_export and is_repo_root(DEPLOY_SOURCE_ROOT):
        root = DEPLOY_SOURCE_ROOT.resolve()
        return root, f"{root} (the recorded deploy export — what the live artifact was built from)"
    return ROOT, (f"{ROOT} (this WORKING TREE, not the deployed artifact: it may carry other "
                  f"sessions' uncommitted edits, and build_zip packages them)")


def _deploy_module(source_root: Path):
    """`scripts/deploy_all_lambdas.py` loaded by path, re-rooted at `source_root`.

    Loaded by path rather than imported, because `scripts/` is not a package. The four module
    globals are re-pointed BEFORE any `Spec` is constructed: `Spec.__init__` resolves
    `self.source` from the module-level `FUNCTIONS` at construction time, so a Spec built before
    the override would still read the working tree.
    """
    script = ROOT / "scripts" / "deploy_all_lambdas.py"
    loader = importlib.util.spec_from_file_location("deploy_all_lambdas", script)
    module = importlib.util.module_from_spec(loader)
    sys.modules["deploy_all_lambdas"] = module
    loader.loader.exec_module(module)

    functions = (source_root / "amplify" / "functions").resolve()
    if not (functions / "ecommerce" / "checkout" / "handler.py").is_file():
        raise FileNotFoundError(
            f"no checkout handler under {functions} — is --source-root a repo root?")
    module.FUNCTIONS = functions
    module.SHARED = functions / "shared"
    module.LAMBDA_UTILS = module.SHARED / "lambda_utils"
    module.STATIC_KB = module.SHARED / "static_knowledge_base.py"
    return module


def build_package(source_root: Path) -> tuple:
    """Return (zip_bytes, members, errors, warnings) for the checkout package.

    The validation is the point: an import the packaging step forgot is caught here, before
    `create_function`, instead of as a cold-start `Unable to import module` on a real request.
    `provided` is empty because this function has no layers — everything must resolve inside the
    package, or come from the python3.12 runtime / stdlib.
    """
    dal = _deploy_module(source_root)
    spec = dal.Spec(FUNCTION_NAME, "ecommerce/checkout",
                    provisioned_by="python scripts/provision_checkout.py")
    zip_bytes, members = dal.build_zip(spec)
    errors, warnings = dal.validate(spec, members, frozenset())
    errors += dal.validate_handler(members, "handler.handler")
    return zip_bytes, members, sorted(set(errors)), sorted(set(warnings))


def package_sha(zip_bytes: bytes) -> str:
    """base64(sha256(zip)) — the same value Lambda reports as `CodeSha256`."""
    return base64.b64encode(hashlib.sha256(zip_bytes).digest()).decode()


def live_members(qualifier: str = LIVE_ALIAS) -> tuple:
    """Return `(members, sha, note)` for the code actually running on `qualifier`.

    This exists because every package-derived verdict here used to describe a LOCAL export while
    the alias pointed at a version somebody else published. The import validation, the reachability
    closure and therefore the `ConditionCheckItem` verdict were all computed from
    `.scratch/deploy-checkout`; the function in production had never had its imports walked. The
    consequence was specific rather than theoretical — if a later version wired `razorpay_orders`
    in, the role would be missing `secretsmanager:GetSecretValue` on `wecare/razorpay/api` and
    nothing here would have said so.

    `get_function` returns a short-lived **presigned** S3 URL for the artifact. That URL carries an
    `X-Amz-Signature`, so it is credential-shaped material: it is fetched in-process and is never
    printed, logged, passed as an argument or written to a file. Only the resulting `CodeSha256`
    and member list leave this function. See .kiro/steering/secret-handling.md.
    """
    try:
        described = lam().get_function(FunctionName=FUNCTION_NAME, Qualifier=qualifier)
    except ClientError as exc:
        return None, "", f"live code NOT MEASURED: get_function failed " \
                         f"({exc.response.get('Error', {}).get('Code', 'unknown')})"
    sha = described.get("Configuration", {}).get("CodeSha256", "")
    location = (described.get("Code") or {}).get("Location")
    if not location:
        return None, sha, "live code NOT MEASURED: no download location returned"
    try:
        with urllib.request.urlopen(location, timeout=60) as response:  # noqa: S310 - AWS presigned
            payload = response.read()
    except Exception as exc:  # noqa: BLE001 - never surface the URL in the message
        return None, sha, f"live code NOT MEASURED: download failed ({type(exc).__name__})"
    fetched = package_sha(payload)
    if sha and fetched != sha:
        return None, sha, (f"live code NOT MEASURED: downloaded bytes hash to {fetched}, "
                           f"but the alias reports {sha}")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = {info.filename: archive.read(info)
                       for info in archive.infolist() if not info.is_dir()}
    except zipfile.BadZipFile:
        return None, sha, "live code NOT MEASURED: artifact is not a readable zip"
    return members, sha, f"{len(members)} files, {len(payload)} bytes, sha256 {sha}"


def validate_members(members: dict, source_root: Path) -> tuple:
    """Run the fleet's own import resolution over an arbitrary member set.

    `deploy_all_lambdas.validate` does not read the `Spec` it is handed — it reasons purely over
    `members` — so the same checker that gates a build can be pointed at bytes pulled back out of
    Lambda. That is what makes a verdict about the live artifact possible at all.
    """
    dal = _deploy_module(source_root)
    spec = dal.Spec(FUNCTION_NAME, "ecommerce/checkout")
    errors, warnings = dal.validate(spec, members, frozenset())
    errors += dal.validate_handler(members, "handler.handler")
    return sorted(set(errors)), sorted(set(warnings))


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


def expected_role_policy(acct: str | None = None) -> dict:
    """Least-privilege inline policy for the current checkout import closure.

    Kept as one pure builder so create, reconcile and tests all reason about the same document.
    Coupons and gift cards are Wix-authoritative on the website path; the legacy custom stores are
    not imported by checkout and therefore do not belong in this role.
    """
    acct = acct or account_id()
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadWixApiKey",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [f"arn:aws:secretsmanager:{REGION}:{acct}:secret:{WIX_API_KEY_SECRET}-*"],
            },
            {
                "Sid": "ReadRazorpayApiKey",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [f"arn:aws:secretsmanager:{REGION}:{acct}:secret:{RAZORPAY_API_SECRET}-*"],
            },
            {
                "Sid": "ReadVerifiedCheckoutProfile",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}/index/phone-index"
                ],
            },
            {
                "Sid": "PaymentAttemptAndCommerceKeys",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{PAYMENT_ATTEMPTS_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:{acct}:table/{COMMERCE_KEYS_TABLE}",
                ],
            },
            {
                "Sid": "InternalOrderRecord",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/{ORDERS_TABLE}"],
            },
            {
                # Four ARNs, no wildcard. The two `wecare-outbound-whatsapp` entries are the
                # grant the in-chat send needs; this role is used by one function, the widening
                # grants no new data access and no ability to charge. The SAME four ARNs are
                # declared in `amplify/infra/checkout.json`'s `CheckoutRole`, and a test pins the
                # two homes equal — they have already drifted apart once.
                "Sid": "InvokeWhatsAppSender",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}",
                    f"arn:aws:lambda:{REGION}:{acct}:function:{SENDER_FUNCTION}:{LIVE_ALIAS}",
                    f"arn:aws:lambda:{REGION}:{acct}:function:{OUTBOUND_SENDER_FUNCTION}",
                    f"arn:aws:lambda:{REGION}:{acct}:function:"
                    f"{OUTBOUND_SENDER_FUNCTION}:{LIVE_ALIAS}",
                ],
            },
        ],
    }


def ensure_role(dry_run: bool) -> str:
    """Create OR reconcile the dedicated checkout role.

    Returning early merely because the role exists is unsafe: that is exactly how an older live
    role can survive while the verifier and candidate code have moved on. `put_role_policy` is an
    idempotent replacement of this function's one owned inline policy.
    """
    exists = role_exists()
    if dry_run:
        return "would reconcile existing role" if exists else "would create and reconcile role"

    if not exists:
        assume = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume),
            Description="Customer checkout (headless WhatsApp/Razorpay) execution role",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "Checkout"}],
        )

    # Both calls are idempotent. Re-running the provisioner repairs policy drift on an existing
    # role instead of reporting it only after other resources have already changed.
    iam().attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    iam().put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="CheckoutLeastPrivilege",
        PolicyDocument=json.dumps(expected_role_policy()),
    )
    return "reconciled" if exists else "created"


def ensure_log_group(dry_run: bool) -> str:
    name = f"/aws/lambda/{FUNCTION_NAME}"
    try:
        groups = logs().describe_log_groups(
            logGroupNamePrefix=name, limit=50).get("logGroups", [])
        exists = any(g.get("logGroupName") == name for g in groups)
    except ClientError:
        exists = False
    if not exists and dry_run:
        return "would create with 30-day retention"
    if not exists:
        logs().create_log_group(logGroupName=name, tags={
            "Project": "WECARE.DIGITAL", "Purpose": "Checkout"})
    if not dry_run:
        logs().put_retention_policy(logGroupName=name, retentionInDays=30)
    return "exists; retention verified" if exists else "created"


#: Environment keys this script seeds empty and an owner later fills from a live Meta/Razorpay
#: read. `--verify` checks them for PRESENCE only; every other key in `expected_environment()` is
#: checked for an exact value.
READINESS_KEYS = ("EXPECTED_CONFIGURATION_NAME", "EXPECTED_PROVIDER_MID")

#: The two deliberate switches that turn the Wix order write-back on. Both default to EMPTY here,
#: for the same reason `READINESS_KEYS` do: a key that exists is a key an owner flips with one
#: `update-function-configuration`, and seeding it empty means enabling Wix writes is a deliberate
#: two-value edit rather than something a routine provisioner run can do by accident.
#:
#: `lambda_utils/ecommerce/wix_writeback.is_enabled()` is the gate they feed, and it is AND of
#: four conditions:
#:   WIX_WRITEBACK_ENABLED (truthy)   — this script seeds it empty
#:   WIX_ECOM_WRITE_CONFIRMED (truthy)— this script seeds it empty
#:   WIX_SITE_ID == the confirmed id  — already set below and reconciled
#:   WIX_CART_V2_WRITE_CONTRACT == "cart-v2-external-v1" — a fixed contract string, set below
#:
#: So `--verify` checks these two for PRESENCE only (an owner may legitimately set either to a
#: truthy value), exactly like the readiness inputs. The contract string, by contrast, is a fixed
#: constant checked for its EXACT value — it alone cannot enable anything, so pinning it is safe.
#:
#: WHY THE SWITCHES STAY EMPTY FOR NOW. The live Wix headless API key answers the eCommerce Orders
#: API with 403 READ_ORDER_FORBIDDEN (verified by `scripts/probe_wix_capabilities.py`). The write
#: scope is not provisioned, so a POST /ecom/v1/orders would be rejected and every paid order would
#: stall at the WIX_READBACK_REQUIRED reconciliation stage instead of landing cleanly in DynamoDB.
#: Deploying the keys declared-but-empty makes the switch READY on the function; turning it on is
#: the follow-up `WIX_WRITEBACK_ENABLED=true WIX_ECOM_WRITE_CONFIRMED=true` edit, to be made only
#: after the Wix key is granted the eCommerce write scope and one real order is validated.
WIX_WRITEBACK_SWITCH_KEYS = ("WIX_WRITEBACK_ENABLED", "WIX_ECOM_WRITE_CONFIRMED")

#: Presence-only keys = readiness inputs + the two write-back switches. Every OTHER key in
#: `expected_environment()` is checked for an exact value by `--verify` and repaired by
#: `reconcile_environment`.
PRESENCE_ONLY_KEYS = READINESS_KEYS + WIX_WRITEBACK_SWITCH_KEYS

#: The fixed Cart V2 external-order write contract string `wix_writeback.is_enabled()` requires.
#: A constant, not a switch: on its own it enables nothing, so it is set and value-checked.
WIX_CART_V2_WRITE_CONTRACT = "cart-v2-external-v1"


def expected_environment() -> dict:
    return {
        "PAYMENT_ATTEMPTS_TABLE": PAYMENT_ATTEMPTS_TABLE,
        "COMMERCE_KEYS_TABLE": COMMERCE_KEYS_TABLE,
        "WIX_API_KEY_SECRET": WIX_API_KEY_SECRET,
        "RAZORPAY_SECRET_ID": RAZORPAY_API_SECRET,
        "CONTACTS_TABLE": CONTACTS_TABLE,
        "ORDERS_TABLE": ORDERS_TABLE,
        "WIX_SITE_ID": WIX_SITE_ID,
        "SENDER_FUNCTION": f"{SENDER_FUNCTION}:{LIVE_ALIAS}",
        "PAYMENT_WABA_ID": PAYMENT_WABA_ID,
        # Deliberately empty: payment_readiness returns CONFIGURATION_UNVERIFIED until an owner sets
        # these from a live Meta/Razorpay read. No value here can enable a payment.
        "EXPECTED_CONFIGURATION_NAME": "",
        "EXPECTED_PROVIDER_MID": "",
        # CHECKOUT_INITIATION_ENABLED intentionally omitted -> initiation OFF.
        # ── Wix order write-back (headless Wix -> real Wix Orders list) ──────────────────
        # `finalization.accept_paid` runs on the verify-callback leg of THIS function and is the
        # single place a paid order is pushed to Wix. The payload is already built on the attempt
        # (`website_checkout`/`handler` call `wix_writeback.build_wix_order_payload`); the only
        # thing standing between a paid order and the Wix Orders list is `wix_writeback.is_enabled`,
        # which these four keys feed. The contract string is set to its one required value; the two
        # switches stay empty so turning writes on is a deliberate edit — see WIX_WRITEBACK_* notes.
        "WIX_CART_V2_WRITE_CONTRACT": WIX_CART_V2_WRITE_CONTRACT,
        "WIX_WRITEBACK_ENABLED": "",
        "WIX_ECOM_WRITE_CONFIRMED": "",
    }


def ensure_function(dry_run: bool, zip_bytes: bytes) -> str:
    if function_exists():
        return "exists"
    if dry_run:
        return "would create"

    role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    for attempt in range(8):
        try:
            lam().create_function(
                FunctionName=FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": zip_bytes},
                Description="Customer checkout: authoritative Wix total, readiness gate, "
                            "PaymentAttempt, in-chat handoff. Initiation off by default.",
                Timeout=20,
                MemorySize=256,
                Environment={"Variables": expected_environment()},
                Tags={"Project": "WECARE.DIGITAL", "Purpose": "Checkout"},
            )
            return "created"
        except ClientError as exc:
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
    wanted = expected_environment()
    # Only ADD/repair the keys this script owns; never clobber an operator-set
    # CHECKOUT_INITIATION_ENABLED, a live-read EXPECTED_* value, or a deliberately-flipped
    # WIX_WRITEBACK_ENABLED / WIX_ECOM_WRITE_CONFIRMED switch. Those are seeded here only when
    # ABSENT, so a reconcile run makes the switch available without ever turning Wix writes on or
    # off against an owner's decision.
    drifted = {k: v for k, v in wanted.items()
               if k not in PRESENCE_ONLY_KEYS and current.get(k) != v}
    for k in PRESENCE_ONLY_KEYS:
        if k not in current:
            drifted[k] = wanted[k]
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
        return "would publish v1 and create live alias"
    published = lam().publish_version(
        FunctionName=FUNCTION_NAME, Description="initial checkout release (initiation off)")
    version = published["Version"]
    lam().get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION_NAME, Qualifier=version)
    lam().create_alias(
        FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS, FunctionVersion=version,
        Description="Production checkout target")
    return f"created -> v{version}"


# ── HTTP API wiring ───────────────────────────────────────────────────────────

def live_policy_statements() -> list:
    """Resource-policy statements on the `live` alias, or `[]` when there is no policy yet."""
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
    """Let API Gateway invoke the `live` alias. Qualified, which is the whole point.

    A function-level statement does NOT authorise an alias invoke. Getting this wrong produces a
    500 with no Lambda log line at all, because the function is never entered — see
    `scripts/provision_missing_ui_routes.ensure_permission`, which records the same trap costing a
    live route.

    Add-then-remove, in that order. The narrow statement goes on before any superseded one comes
    off, so there is never an instant where the two routes resolve to a target API Gateway is not
    authorised to invoke.
    """
    if dry_run:
        wanted = ", ".join(f"{route_statement_id(k)} -> {k}" for k in ROUTE_KEYS)
        return (f"would grant lambda:InvokeFunction on :{LIVE_ALIAS} to apigateway.amazonaws.com "
                f"per route ({wanted}), then remove {', '.join(LEGACY_STATEMENT_IDS)}")

    notes = []
    existing = {s.get("Sid"): s for s in live_policy_statements()}

    for route_key in ROUTE_KEYS:
        sid, want = route_statement_id(route_key), source_arn(route_key)
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
            notes.append(f"granted {sid} for {want}")
        elif _statement_source_arn(current) != want:
            # Reported, not silently repaired: `add_permission` cannot edit a statement, and
            # remove-then-add under a live id is exactly the window this function avoids.
            # `--verify` fails on the same condition, so drift cannot pass as success.
            notes.append(f"DRIFT: {sid} allows {_statement_source_arn(current)!r}, wanted "
                         f"{want!r} — add a corrected statement under a NEW id, then retire this "
                         f"one by adding it to LEGACY_STATEMENT_IDS")
        else:
            notes.append(f"{sid} already correct")

    # Only after every per-route statement is in place.
    for stale in LEGACY_STATEMENT_IDS:
        if stale not in existing:
            continue
        lam().remove_permission(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS, StatementId=stale)
        notes.append(f"removed superseded {stale} ({_statement_source_arn(existing[stale])})")

    return "; ".join(notes)


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
    existing = find_integration(uri)
    if existing:
        return existing, f"reusing {existing}"
    if dry_run:
        return "", f"would create AWS_PROXY -> {uri}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
        PayloadFormatVersion="2.0",
        Description="Customer checkout (initiation off by default)")
    return created["IntegrationId"], f"created {created['IntegrationId']} -> {uri}"


def ensure_routes(dry_run: bool, integration_id: str) -> str:
    """Create only missing route keys. Never deletes or retargets an existing route."""
    existing = {r["RouteKey"]: r["RouteId"] for r in _all_items("get_routes")}
    results = []
    for key in ROUTE_KEYS:
        if key in existing:
            results.append(f"{key} exists ({existing[key]})")
            continue
        if dry_run:
            results.append(f"would create {key}")
            continue
        made = api().create_route(
            ApiId=API_ID, RouteKey=key, Target=f"integrations/{integration_id}")
        results.append(f"created {key} ({made['RouteId']})")
    return "; ".join(results)


def live_route_keys() -> set:
    return {r["RouteKey"] for r in _all_items("get_routes")}


def route_throttle() -> dict:
    """The live `RouteSettings` for the anonymous price route, or `{}`."""
    stage = api().get_stage(ApiId=API_ID, StageName=STAGE)
    return dict((stage.get("RouteSettings") or {}).get(PRICE_ROUTE_KEY) or {})


def ensure_route_throttle(dry_run: bool) -> str:
    """Cap the ONE anonymous route so it cannot spend the stage's shared allowance.

    `UpdateStage` MERGES `RouteSettings` rather than replacing them -- the opposite of the
    replace-not-patch rule `.kiro/steering/aws-agent-rules.md` applies to AWS "update" calls, and
    a proven exception measured by `scripts/deploy_mcp_server.py`, which is where this pattern
    comes from. Only this script's own key is ever sent, so a throttle another route owns cannot
    be dropped by this call.

    The awkward consequence of merging is that it also VALIDATES the merged map, so a setting
    left behind for a DELETED route makes the whole map unwritable:

        NotFoundException: Unable to find Route by key POST /site-language/tts
        within the provided RouteSettings

    This script REPORTS that condition instead of clearing it. Removal needs
    `DeleteRouteSettings`, and `deploy_mcp_server.ensure_route_throttle` already owns that
    cleanup with the argument for why it is safe; a second place deleting stage configuration is
    how two scripts start fighting over one shared resource. `--verify` fails on a missing
    throttle, so skipping here is visible rather than silent.
    """
    stage = api().get_stage(ApiId=API_ID, StageName=STAGE)
    current = dict(stage.get("RouteSettings") or {})
    wanted = {**current.get(PRICE_ROUTE_KEY, {}),
              "ThrottlingRateLimit": ROUTE_THROTTLE_RATE,
              "ThrottlingBurstLimit": ROUTE_THROTTLE_BURST}
    default_rate = (stage.get("DefaultRouteSettings") or {}).get("ThrottlingRateLimit")
    if current.get(PRICE_ROUTE_KEY) == wanted:
        return (f"already {ROUTE_THROTTLE_RATE} rps / {ROUTE_THROTTLE_BURST} burst on "
                f"{PRICE_ROUTE_KEY} (stage default {default_rate})")
    if dry_run:
        return (f"would set {ROUTE_THROTTLE_RATE} rps / {ROUTE_THROTTLE_BURST} burst on "
                f"{PRICE_ROUTE_KEY}")
    stale = sorted(key for key in current if key not in live_route_keys())
    if stale:
        return (f"SKIPPED — the stage carries settings for route(s) that no longer exist, which "
                f"makes RouteSettings unwritable: {stale}. Clear them with "
                f"`python scripts/deploy_mcp_server.py` (it owns DeleteRouteSettings), then "
                f"re-run. `--verify` will keep failing until {PRICE_ROUTE_KEY} is capped")
    api().update_stage(ApiId=API_ID, StageName=STAGE,
                       RouteSettings={PRICE_ROUTE_KEY: wanted})
    applied = route_throttle()
    if (applied.get("ThrottlingRateLimit") != ROUTE_THROTTLE_RATE
            or applied.get("ThrottlingBurstLimit") != ROUTE_THROTTLE_BURST):
        raise RuntimeError(f"route throttle did not apply: {applied}")
    lost = (set(current) - set(api().get_stage(
        ApiId=API_ID, StageName=STAGE).get("RouteSettings") or {}))
    if lost:
        raise RuntimeError(f"update_stage dropped route settings for: {sorted(lost)}")
    return (f"set {ROUTE_THROTTLE_RATE} rps / {ROUTE_THROTTLE_BURST} burst on "
            f"{PRICE_ROUTE_KEY} (stage default stays {default_rate})")


# ── IAM reachability report (never a grant) ───────────────────────────────────

#: DynamoDB actions the checkout path could plausibly need, and the verdict we expect.
_SIMULATED_ACTIONS = ("dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                      "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem",
                      "dynamodb:Query")

#: (action, TABLE NAME) pairs the inline policy deliberately withholds, so a `denied` verdict is
#: the CORRECT answer rather than a problem to report.
#:
#: DeleteItem is deliberately withheld from every table checkout owns. These rows are evidence, not
#: temporary holds. Keying on the action/resource pair keeps that withholding directly measured.
_EXPECTED_DENY = {
    ("dynamodb:DeleteItem", PAYMENT_ATTEMPTS_TABLE),
    ("dynamodb:DeleteItem", COMMERCE_KEYS_TABLE),
    # Without this pair, `--verify` reports a false "GRANTED BY THE INLINE POLICY BUT DENIED IN
    # SIMULATION" for DeleteItem on the OrderTable and exits non-zero on a CORRECTLY provisioned
    # role -- because InternalOrderRecord deliberately withholds it.
    ("dynamodb:DeleteItem", ORDERS_TABLE),
}


def _package_of(arcname: str) -> list:
    """The dotted package an arcname's module lives IN, as a list of parts.

    `lambda_utils/template_ttl.py` -> `['lambda_utils']`, and
    `lambda_utils/ecommerce/__init__.py` -> `['lambda_utils', 'ecommerce']`, because a package's
    `__init__` is inside the package rather than beside it. Getting that distinction wrong makes
    every relative import from an `__init__.py` resolve one level too high.
    """
    parts = arcname.split("/")
    return parts[:-1] if parts[-1] != "__init__.py" else parts[:-1]


def resolve_relative_import(arcname: str, module: str | None, level: int) -> str:
    """`from ..x import y` inside `arcname` -> the dotted module it names, or `""` if it escapes.

    `level` counts dots. One dot means "this package", so the base is the importing module's own
    package; each further dot climbs one more. Returns `""` rather than raising when the import
    climbs above the package root, because a malformed package should produce a measurable miss in
    the closure report, not a crash in the middle of an IAM verdict.
    """
    base = _package_of(arcname)
    climb = level - 1
    if climb > len(base):
        return ""
    base = base[:len(base) - climb] if climb else base
    return ".".join(base + (module.split(".") if module else []))


def import_closure(members: dict, entry: str = "handler.py") -> set:
    """Modules actually reachable from `entry` by following imports inside the package.

    Scoped to the closure rather than to the whole ZIP, and that distinction is the difference
    between a useful report and a false alarm. The package ships the ENTIRE `lambda_utils` tree —
    112 files — because `deploy_all_lambdas.build_zip` does not prune, so `crm/service.py` and
    `notifications/store.py` are present and both use `TransactWriteItems`. Neither is imported by
    the checkout handler. Scanning the ZIP therefore reports a `ConditionCheckItem` grant the
    function can never need, and a grant report that cries wolf is one nobody reads.

    **Relative imports count, and used to be skipped.** This walker did `if node.level: continue`,
    which silently discarded every `from .x import y` edge — and `lambda_utils` carries 35 of them,
    one of them inside this very closure (`template_ttl.py` -> `whatsapp_types.py`). The measured
    set was 18 files where 19 are reachable. The verdict happened to be unchanged because the
    missed module opens no transaction, but the failure direction is the dangerous one: a future
    relatively-imported module that calls `TransactWriteItems` would produce a false "grant not
    required" while the verifier exits 0, i.e. a function missing a permission with a green gate.
    """
    reachable, pending = set(), [entry]
    while pending:
        arcname = pending.pop()
        if arcname in reachable or arcname not in members:
            continue
        reachable.add(arcname)
        try:
            tree = ast.parse(members[arcname].decode("utf-8", "replace"), filename=arcname)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dotted = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    resolved = resolve_relative_import(arcname, node.module, node.level)
                    if not resolved:
                        continue
                    dotted = [resolved] + [f"{resolved}.{a.name}" for a in node.names]
                elif not node.module:
                    continue
                else:
                    # `from lambda_utils.ecommerce import order_keys, payment_attempt` imports both
                    # the package module and each named submodule; try every candidate and keep
                    # whichever exist.
                    dotted = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            for name in dotted:
                stem = name.replace(".", "/")
                for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
                    if candidate in members:
                        pending.append(candidate)
    return reachable


def _package_needs_transactions(members: dict) -> list:
    """Reachable call sites that would require `dynamodb:ConditionCheckItem`.

    `ConditionCheckItem` is only ever required inside `TransactWriteItems` / `TransactGetItems`;
    a plain `put_item`/`update_item` carrying a `ConditionExpression` needs `PutItem`/`UpdateItem`
    and nothing more. Conflating the two is what turns a working condition into a phantom
    permission gap.
    """
    needles = ("transact_write_items", "TransactWriteItems",
               "transact_get_items", "TransactGetItems", "ConditionCheckItem")
    hits = []
    for arcname in sorted(import_closure(members)):
        text = members[arcname].decode("utf-8", "replace")
        for needle in needles:
            if needle in text:
                hits.append(f"{arcname}: {needle}")
    return hits


def report_required_grants(members: dict | None) -> list:
    """Print a per-action verdict for the checkout role and RETURN every problem found.

    Deliberately does not touch `wecare-digital-lambda-role`: that role is shared by the whole
    fleet, so a statement added for checkout would widen every other function too. Checkout has
    its own role, which is why a gap here is reportable rather than contagious.

    **The return value is load-bearing, and used to be thrown away.** `verify()` discarded it, so a
    `REQUIRED GRANT` line printed while the script exited 0 — latent while the verdict is "not
    required", and wrong in exactly the circumstance the check exists for. Every problem returned
    here is now a `verify()` problem.

    An unmeasured verdict is a problem too, not a pass. A failed `simulate_principal_policy`, an
    unreadable role, or a package that could not be rebuilt all mean "we do not know", and a run
    that measured nothing must not be indistinguishable from one that measured everything and found
    nothing.
    """
    acct = account_id()
    tables = [f"arn:aws:dynamodb:{REGION}:{acct}:table/{PAYMENT_ATTEMPTS_TABLE}",
              f"arn:aws:dynamodb:{REGION}:{acct}:table/{COMMERCE_KEYS_TABLE}",
              f"arn:aws:dynamodb:{REGION}:{acct}:table/{ORDERS_TABLE}",
              f"arn:aws:dynamodb:{REGION}:{acct}:table/{CONTACTS_TABLE}/index/phone-index"]
    core_tables = tables[:3]
    profile_index = tables[3]
    table_names = {
        tables[0]: PAYMENT_ATTEMPTS_TABLE,
        tables[1]: COMMERCE_KEYS_TABLE,
        tables[2]: ORDERS_TABLE,
        tables[3]: CONTACTS_TABLE + "/index/phone-index",
    }
    try:
        role_arn = iam().get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        print(f"iam: role absent or unreadable ({code}) — cannot simulate")
        return [f"IAM verdicts NOT MEASURED: {ROLE_NAME} could not be read ({code})"]

    verdicts, problems = {}, []
    try:
        result = iam().simulate_principal_policy(
            PolicySourceArn=role_arn,
            ActionNames=list(_SIMULATED_ACTIONS),
            ResourceArns=tables,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        print(f"iam: simulate unavailable ({code}) — verdicts not measured")
        return [f"IAM verdicts NOT MEASURED: simulate_principal_policy failed ({code})"]

    for item in result.get("EvaluationResults", []):
        action = item["EvalActionName"]
        specific = item.get("ResourceSpecificResults") or []
        if specific:
            # With multiple ResourceArns, IAM returns one EvaluationResult per ACTION and nests the
            # per-resource verdicts here. Reading only top-level EvalResourceName yields AWS's
            # generic resource template and makes every real ARN look "not evaluated".
            for resource_result in specific:
                key = (action, resource_result.get("EvalResourceName", ""))
                verdicts.setdefault(key, set()).add(
                    resource_result.get("EvalResourceDecision", "not evaluated"))
        else:
            # Keep the single-resource/fake shape supported as well.
            key = (action, item.get("EvalResourceName", ""))
            verdicts.setdefault(key, set()).add(item.get("EvalDecision", "not evaluated"))

    # `None` means the closure was never measured, which is NOT the same as "measured, needs
    # nothing" — the empty list. Keep the two distinguishable all the way to the exit code.
    needed_by_code = _package_needs_transactions(members) if members is not None else None

    condition_check: set = set()
    for action in _SIMULATED_ACTIONS:
        # Query exists only to read the verified checkout profile from the Contacts phone index.
        # Every other Dynamo action is evaluated only on the three checkout-owned tables. IAM simulation
        # returns the full action/resource cross product, but irrelevant pairs are intentionally
        # ignored rather than treated as desired permissions.
        resources = [profile_index] if action == "dynamodb:Query" else core_tables
        for arn in resources:
            name = table_names[arn]
            decisions = verdicts.get((action, arn), {"not evaluated"})
            decision = "allowed" if decisions == {"allowed"} else "/".join(sorted(decisions))
            if action == "dynamodb:ConditionCheckItem":
                # Granted on no table, so the question is not "which table" but "does the
                # handler's import closure open a transaction at all". Judged once, below.
                condition_check |= decisions
                print(f"iam {action} on {name}: {decision}")
                continue
            note = ""
            if action == "dynamodb:Query":
                if decision != "allowed":
                    note = "  <-- PROFILE INDEX QUERY MUST BE ALLOWED"
                    problems.append(
                        f"{action} on {name} is {decision}, but checkout cannot load the "
                        f"server-verified CRM profile without it")
                print(f"iam {action} on {name}: {decision}{note}")
                continue
            if (action, name) in _EXPECTED_DENY:
                if decision == "allowed":
                    note = "  <-- ALLOWED BUT MUST BE DENIED"
                    problems.append(
                        f"{action} on {name} is allowed, but CheckoutLeastPrivilege withholds "
                        f"it — a failed attempt is the evidence that no charge became an order, "
                        f"and a reservation is not ours to delete")
                else:
                    note = "  (correctly withheld)"
            elif decision != "allowed":
                # The inline policy grants this pair outright. A deny means the role is not what
                # this script wrote, so the function cannot record a payment attempt at all.
                note = "  <-- GRANTED BY THE INLINE POLICY BUT DENIED IN SIMULATION"
                problems.append(
                    f"{action} on {name} is {decision}, but CheckoutLeastPrivilege grants it "
                    f"— the live role does not match this script")
            print(f"iam {action} on {name}: {decision}{note}")

    cc_decision = ("allowed" if condition_check == {"allowed"}
                   else "/".join(sorted(condition_check or {"not evaluated"})))
    if cc_decision != "allowed":
        if needed_by_code is None:
            problems.append(
                f"dynamodb:ConditionCheckItem is {cc_decision} and the verdict is NOT JUDGED: "
                f"the package could not be rebuilt, so the handler's import closure was "
                f"never measured")
            print("iam dynamodb:ConditionCheckItem: NOT JUDGED (import closure not measured)")
        elif needed_by_code:
            problems.append(
                f"dynamodb:ConditionCheckItem on {', '.join(tables)} — needed by "
                + "; ".join(needed_by_code))
            print("iam dynamodb:ConditionCheckItem: REQUIRED GRANT")
        else:
            print("iam dynamodb:ConditionCheckItem: not required (no TransactWriteItems/"
                  "TransactGetItems anywhere in the handler's import closure; a "
                  "ConditionExpression on put_item/update_item needs PutItem/UpdateItem only)")

    for line in problems:
        print(f"REQUIRED GRANT: {line}")
    return problems


def verify(members: dict | None = None, source_note: str = "") -> int:
    """Read every provisioned fact back off the account and return 1 on any problem.

    `members`, when given, is a LOCAL build used only as a comparison. Everything judged here is
    read from the account: the alias, the published version's environment, the routes, the
    per-route invoke statements, and — since the artifact can be downloaded — the deployed bytes
    themselves. An earlier shape of this function judged a local export and reported on live in the
    same breath, which is how a package nobody deployed came to carry the IAM verdict.
    """
    problems: list[str] = []
    if source_note:
        print(f"comparison package built from: {source_note}")
    if not function_exists():
        print("FAIL function missing")
        return 1
    try:
        alias = lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)
    except ClientError:
        print("FAIL live alias missing")
        return 1

    live_config = lam().get_function_configuration(
        FunctionName=FUNCTION_NAME, Qualifier=alias["FunctionVersion"])
    live_env = (live_config.get("Environment") or {}).get("Variables") or {}

    # Derived from `expected_environment()`, never restated. A hand-enumerated list omitted
    # WIX_SITE_ID — a key this script sets and `reconcile_environment` repairs — so a wrong Wix
    # site id on live passed verification. Any key added to `expected_environment` is now checked
    # by construction, which is the only version of this check that cannot drift out of date.
    for key, want in sorted(expected_environment().items()):
        if key in PRESENCE_ONLY_KEYS:
            # Deliberately presence-only. For READINESS_KEYS these are values an owner fills in
            # from a live Meta/Razorpay read; for WIX_WRITEBACK_SWITCH_KEYS they are the two
            # switches an owner flips to truthy once the Wix write scope is confirmed. In both
            # cases a non-empty value is legitimate owner drift from the empty seed this script
            # writes, so only ABSENCE is a fault.
            if key not in live_env:
                problems.append(f"env {key} absent on live (v{alias['FunctionVersion']})")
            continue
        if live_env.get(key) != want:
            problems.append(f"env {key} mismatch on live (v{alias['FunctionVersion']})")

    initiation = str(live_env.get("CHECKOUT_INITIATION_ENABLED", "")).strip().lower()
    if initiation in ("1", "true", "yes", "on"):
        problems.append("CHECKOUT_INITIATION_ENABLED is ON — live payment initiation is enabled")

    # Readiness blocks independently of the gate. Both empty means `payment_readiness.evaluate`
    # returns CONFIGURATION_UNVERIFIED, so a flipped flag alone still cannot produce a payment.
    readiness_empty = not (live_env.get("EXPECTED_CONFIGURATION_NAME")
                           or live_env.get("EXPECTED_PROVIDER_MID"))

    # Wix order write-back readout. `is_enabled()` is AND of all four, so report ON only when both
    # switches are truthy AND the contract/site id are the required constants — i.e. exactly the
    # condition under which a paid order would be pushed to the Wix Orders list.
    def _truthy(name: str) -> bool:
        return str(live_env.get(name, "")).strip().lower() in ("1", "true", "yes", "on")
    writeback_on = (_truthy("WIX_WRITEBACK_ENABLED") and _truthy("WIX_ECOM_WRITE_CONFIRMED")
                    and live_env.get("WIX_SITE_ID") == WIX_SITE_ID
                    and live_env.get("WIX_CART_V2_WRITE_CONTRACT") == WIX_CART_V2_WRITE_CONTRACT)

    print(f"function: present (live v{alias['FunctionVersion']})")
    print(f"initiation: {'ON' if initiation in ('1','true','yes','on') else 'OFF (expected)'}")
    print(f"wix order write-back: {'ON — paid orders are pushed to the Wix Orders list' if writeback_on else 'OFF (keys present, switches empty)'}")
    print(f"readiness inputs: {'empty — blocks regardless of the gate' if readiness_empty else 'SET by an operator'}")
    print(f"sender: {SENDER_FUNCTION}:{LIVE_ALIAS}; WABA {PAYMENT_WABA_ID}")

    # Gate off is NOT the same as nothing happens, and this used to be a print that exited 0.
    # The gate is the LAST check in `handler._create`; the measured order is
    #   wix_ecom.create_checkout (a live Wix write) -> currency compare -> payment_readiness
    #   -> order_keys.allocate_payment_reference -> put_item on PaymentAttemptsTable
    #   -> `if not INITIATION_ENABLED: refuse`.
    # So while readiness is empty it refuses early and the table stays at 0 rows. The moment an
    # owner supplies both readiness values with the flag still off, every authenticated
    # action=create performs a live Wix write and writes an attempt row before refusing. No money
    # moves and no gateway order is created, but "the gate is off" stops meaning "inert" — and an
    # operator who set those values expecting inertness deserves a non-zero exit, not a note.
    if not readiness_empty and initiation not in ("1", "true", "yes", "on"):
        problems.append(
            "readiness inputs are SET while CHECKOUT_INITIATION_ENABLED is off: every "
            "authenticated action=create now reaches wix_ecom.create_checkout (a live Wix write) "
            "and writes a PaymentAttempt row BEFORE the gate refuses. Either enable initiation "
            "deliberately or clear EXPECTED_CONFIGURATION_NAME/EXPECTED_PROVIDER_MID to keep the "
            "endpoint inert")

    # Routes + integration: the half that turns a deployed function into a reachable endpoint.
    want_uri = function_arn(qualified=True)
    integrations = {i["IntegrationId"]: i.get("IntegrationUri", "")
                    for i in _all_items("get_integrations")}
    routes = {r["RouteKey"]: r for r in _all_items("get_routes")}
    for key in ROUTE_KEYS:
        route = routes.get(key)
        if not route:
            problems.append(f"route missing: {key}")
            continue
        target = str(route.get("Target") or "")
        uri = integrations.get(target.rsplit("/", 1)[-1], "")
        if uri != want_uri:
            problems.append(f"route {key} targets {uri or target!r}, not {want_uri}")
            continue
        print(f"route {key}: -> {want_uri}")
    print(f"routes on {API_ID}: {len(routes)} total, stage {STAGE}")

    # The throttle on the ONE anonymous route, read back rather than assumed. This is the bound on
    # Wix read volume that does not depend on the `/api/*` edge continuing to cache, so an absent
    # or loosened cap is a real finding and not a cosmetic one — see PRICE_ROUTE_KEY above.
    applied_throttle = route_throttle()
    if (applied_throttle.get("ThrottlingRateLimit") != ROUTE_THROTTLE_RATE
            or applied_throttle.get("ThrottlingBurstLimit") != ROUTE_THROTTLE_BURST):
        problems.append(
            f"{PRICE_ROUTE_KEY} is not throttled at {ROUTE_THROTTLE_RATE} rps / "
            f"{ROUTE_THROTTLE_BURST} burst (live: {applied_throttle or 'no route setting'}) — "
            f"the anonymous price read is the only route here reachable without a session, and "
            f"each cache miss costs 8 Wix calls on the checkout's own API key")
    else:
        print(f"route throttle {PRICE_ROUTE_KEY}: {ROUTE_THROTTLE_RATE} rps / "
              f"{ROUTE_THROTTLE_BURST} burst")

    # The invoke permission, read back per route rather than assumed. A statement scoped wider than
    # its route's exact ARN is drift, and a superseded statement left behind is the whole reason the
    # narrowing needed new ids. An EXTRA statement matters too: anything beyond the known set is a
    # grant nobody in this script asked for.
    statements = {s.get("Sid"): s for s in live_policy_statements()}
    for route_key in ROUTE_KEYS:
        sid, want_arn = route_statement_id(route_key), source_arn(route_key)
        granted = statements.get(sid)
        if granted is None:
            problems.append(f"invoke permission {sid} missing on :{LIVE_ALIAS} — {route_key} "
                            f"resolves to a target API Gateway cannot invoke")
        elif _statement_source_arn(granted) != want_arn:
            problems.append(f"invoke permission {sid} allows "
                            f"{_statement_source_arn(granted)!r}, wanted {want_arn!r}")
        else:
            print(f"invoke permission {sid}: {want_arn}")
    for stale in LEGACY_STATEMENT_IDS:
        if stale in statements:
            problems.append(f"superseded invoke statement {stale} still present "
                            f"({_statement_source_arn(statements[stale])})")
    unexpected = sorted(set(statements) - {route_statement_id(k) for k in ROUTE_KEYS}
                        - set(LEGACY_STATEMENT_IDS))
    for extra in unexpected:
        problems.append(f"unexpected invoke statement {extra} on :{LIVE_ALIAS} "
                        f"({_statement_source_arn(statements[extra])}) — not created by this script")

    # The package the GRANT REPORT reasons over must be the one that is running, not a local
    # export that happens to be lying around. Those two diverged in practice: another session
    # published v2 and moved the alias, and every package-derived conclusion on record still
    # described v1. Pull the artifact back out of Lambda, re-run the fleet's own import resolution
    # over it, and reason about THAT. The local export is kept only as a comparison.
    deployed, deployed_sha, deployed_note = live_members()
    print(f"live artifact (v{alias['FunctionVersion']}): {deployed_note}")
    if deployed is None:
        problems.append(f"the deployed artifact could not be measured — {deployed_note}")
    else:
        live_errors, live_warnings = validate_members(deployed, ROOT)
        for warning in live_warnings:
            print(f"  warning (live artifact): {warning}")
        for error in live_errors:
            problems.append(f"live artifact v{alias['FunctionVersion']}: {error}")
        if not live_errors:
            print(f"  imports on the live artifact: all resolve "
                  f"({len(live_warnings)} guarded warning(s))")
        print(f"  reachable from handler.py on live: {len(import_closure(deployed))} of "
              f"{len(deployed)} packaged modules")
        if members is not None:
            # A member-set difference is the readable form of "live is not what this tree would
            # build". Reported, never a gate: the local export is evidence about the repository,
            # and the artifact is the thing under verification.
            only_live = sorted(set(deployed) - set(members))
            only_export = sorted(set(members) - set(deployed))
            if only_live or only_export:
                print(f"  NOTE live artifact differs from the compared export: "
                      f"{len(only_live)} file(s) only on live, "
                      f"{len(only_export)} only in the export")
            else:
                print("  live artifact ships the same member set as the compared export")
        print(f"  grant report scoped to the LIVE artifact (CodeSha256 {deployed_sha})")

    # `deployed` when the artifact was readable, else `None`, which `report_required_grants` keeps
    # distinct from "measured and needs nothing". Falling back to the local export here would be
    # the exact substitution this block exists to stop.
    problems.extend(report_required_grants(deployed))

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncheckout provisioning verified (initiation disabled)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--source-root", default=None, metavar="PATH",
        help="repo root to PACKAGE from. Default: this checkout for a provisioning run, and "
             f"{DEPLOY_SOURCE_ROOT.relative_to(ROOT)} for --verify when it exists. Point it at a "
             "clean `git archive` export so a dirty shared tree cannot reach production.")
    args = parser.parse_args(argv)

    source_root, why = resolve_source_root(
        args.source_root, prefer_deploy_export=args.verify)

    if args.verify:
        # Build the local package only as a COMPARISON. The grant report itself is scoped to the
        # artifact pulled back off the `live` alias — see `verify`. A failure to build here is
        # therefore a lost comparison, not a lost verdict.
        try:
            _, members, _, _ = build_package(source_root)
        except Exception as exc:  # noqa: BLE001
            print(f"note: could not rebuild the comparison package: {type(exc).__name__}")
            members = None
        return verify(members, source_note=why)

    print(f"region: {REGION}")
    print(f"source root: {why}")
    print(f"sender: {SENDER_FUNCTION}:{LIVE_ALIAS}; WABA {PAYMENT_WABA_ID}")
    print("initiation: OFF (CHECKOUT_INITIATION_ENABLED not set)")
    print(f"dry run: {args.dry_run}\n")

    zip_bytes, members, errors, warnings = build_package(source_root)
    if report_package(zip_bytes, members, errors, warnings):
        return 1
    print()

    print(f"role: {ensure_role(args.dry_run)}")
    print(f"log group: {ensure_log_group(args.dry_run)}")
    print(f"Lambda: {ensure_function(args.dry_run, zip_bytes)}")
    print(f"env: {reconcile_environment(args.dry_run)}")
    print(f"live alias: {ensure_live_alias(args.dry_run)}")
    print(f"invoke permission: {ensure_invoke_permission(args.dry_run)}")
    integration_id, integration_note = ensure_integration(args.dry_run)
    print(f"integration: {integration_note}")
    print(f"routes: {ensure_routes(args.dry_run, integration_id)}")
    print(f"anonymous route throttle: {ensure_route_throttle(args.dry_run)}")

    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0

    print("\nread-back verification:")
    return verify(members, source_note=why)


if __name__ == "__main__":
    raise SystemExit(main())
