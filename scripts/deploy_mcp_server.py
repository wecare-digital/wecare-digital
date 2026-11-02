#!/usr/bin/env python3
"""Deploy wecare-mcp and put it on the apex at https://wecare.digital/mcp

Why this is its own script rather than a Spec in deploy_all_lambdas.py
---------------------------------------------------------------------
Two reasons, and both are structural rather than stylistic.

`config/public-pages.json` has to travel in the zip beside handler.py, and
`deploy_all_lambdas.py` resolves `extra_files` relative to the FUNCTION directory and
skips them entirely for a `standalone=True` spec (see `build_zip`). There is no path
expressible in a Spec that reaches `config/`. The alternatives were a checked-in second
copy of the catalogue inside the function directory, or a symlink - the first is the
exact drift `src/test/PublicAiSurface.test.ts` exists to prevent, and the second breaks
on a Windows checkout. So the packaging lives here, and `deploy_all_lambdas.py` marks
`wecare-mcp` as DELEGATED, the same arrangement `wecare-seo-tools` already has.

Second, `/mcp` needs an Amplify Hosting rewrite as well as an API Gateway route, and
that rewrite is not optional decoration - see below.

THE ROUTING PROBLEM THIS SOLVES, WHICH IS NOT OBVIOUS
-----------------------------------------------------
Amplify Hosting 301-redirects any extension-less path that does not match a rule so as
to add a trailing slash, **and it does so for POST as well as GET**. Measured on the live
site before this script existed:

    $ curl -X POST -D- https://wecare.digital/mcp
    HTTP/2 301
    location: /mcp/

That is fatal for MCP specifically. Every MCP client message is an HTTP POST, and a 301
is not a safe redirect for one: RFC 9110 permits a client to rewrite POST to GET when
following it, and many do, while others refuse to follow a redirect on a non-idempotent
method at all. Either way the handshake never arrives. The endpoint would appear to exist
and simply never work, which is the worst failure shape available.

An explicit rule defeats the normalizer, and that is proven rather than assumed: `/get`
already has `/get` and `/get/` rules at status 200 and returns HTTP 200 with no redirect,
while `/anything-random` 301s. So both `/mcp` and `/mcp/` are registered, pointing at the
same execute-api path.

RULE ORDER IS LOAD-BEARING
--------------------------
Amplify evaluates customRules top-down and the last rule is the terminal catch-all
`/<*>` -> `/404.html` at `404-200`. A rule added AFTER it is dead. So these are inserted
immediately BEFORE the catch-all, and the catch-all's position as last is asserted after
the write rather than trusted.

`404-200` is `NOT_FOUND_REWRITE` and is evaluated only once the file lookup misses, which
is why it can sit above nothing and still not shadow the ~123 exported pages. Do not
"fix" it to a plain 200: a 200 on `/<*>` matches unconditionally and would serve the home
page for the entire site.

SHARED HOSTING RULES AND VERIFICATION
-------------------------------------
Changes to Amplify Hosting customRules can replace or reorder the `/mcp` status-200
rewrites. Preserve `/mcp`, `/mcp/`, shared `/api/<*>` and `/get/<*>` rewrites, and
the terminal 404 rule when editing hosting configuration. Run `--verify` after
any change to the live Amplify rules.

Usage
-----
    python scripts/deploy_mcp_server.py                # package, deploy, route, rewrite
    python scripts/deploy_mcp_server.py --dry-run      # build and report, change nothing
    python scripts/deploy_mcp_server.py --verify       # check live state, change nothing
    python scripts/deploy_mcp_server.py --verify-live  # public endpoint vs repo, NO credentials
    python scripts/deploy_mcp_server.py --skip-hosting # Lambda + API only

Exit status is 1 when a step fails, or when --verify finds the live state wrong.

`--verify-live` is the one command here that needs no AWS credentials: it POSTs to
https://wecare.digital/mcp and compares the pages it serves with config/public-pages.json.
That makes it suitable for explicit scheduled execution outside this repository; see the
long note on verify_live() for why a second catalogue check earns its place. It exits 1 on
drift and 3 when the endpoint cannot be read, because a network blip must not look like drift.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "775261844268"
ROOT = Path(__file__).resolve().parents[1]

FUNCTION_NAME = "wecare-mcp"
# The directory name matches the DEPLOYED function name minus the `wecare-` prefix, and it
# has to. scripts/audit_route_auth.py resolves a route's handler source by deriving candidate
# function names from the directory layout - `<parent>/<slug>` gives it `wecare-mcp` only if
# the slug is `mcp`. Named `mcp-server` it resolved to nothing and the route was reported as
# UNRESOLVED, "verify by hand", which is a weaker signal than the truth: the route is
# intentionally public and the audit should be able to see that for itself.
SOURCE_DIR = ROOT / "amplify" / "functions" / "ai" / "mcp"
HANDLER_FILE = SOURCE_DIR / "handler.py"
CATALOG_FILE = ROOT / "config" / "public-pages.json"

ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/wecare-digital-lambda-role"
API_ID = "zllr9lrg7j"
STAGE = "prod"
AMPLIFY_APP_ID = "d22dm4b0jn71jw"

ROUTE_KEY = "ANY /mcp"

# A PER-ROUTE THROTTLE, because the stage default is SHARED.
#
# Stage `prod` defaults to 100 rps / 200 burst, and that budget is shared across all 359
# routes. This is not theoretical: on 2026-09-28 the build hammered
# /seo-tools/blog-public hard enough that **117 requests came back 429**, so one route
# exhausting the shared allowance already happens here.
#
# /mcp is unauthenticated and anyone on the internet can call it, so it is the route most
# able to do that to everything else - and the blast radius of it doing so is the payment
# webhook and the WhatsApp ingress, not the MCP client. 20 rps is generous for an agent
# integration (a client makes a handful of calls per conversation) and is a fifth of the
# stage, so a flood is contained rather than fatal.
#
# This is a CAP, NOT A SPEND LIMIT, and the distinction is the one core/site-language
# already documents at length: a rate limit bounds requests per second, not dollars. It is
# adequate while every tool is a cached read. If a tool that costs money per call is ever
# added, this number needs revisiting BEFORE the flag goes on, not after.
ROUTE_THROTTLE_RATE = 20.0
ROUTE_THROTTLE_BURST = 40
EXECUTE_API_TARGET = f"https://{API_ID}.execute-api.{REGION}.amazonaws.com/{STAGE}/mcp"
HOSTING_RULES = [
    {"source": "/mcp", "target": EXECUTE_API_TARGET, "status": "200"},
    {"source": "/mcp/", "target": EXECUTE_API_TARGET, "status": "200"},
]
CATCH_ALL_SOURCE = "/<*>"

# The public apex endpoint; stdlib urllib can check it without credentials.
SITE = "https://wecare.digital"
PUBLIC_ENDPOINT = f"{SITE}/mcp"

# Deterministic zip, matching deploy_all_lambdas.py, so an unchanged tree produces an
# unchanged CodeSha256 and redeploying does not mint a pointless version.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# SITE_URL IS DELIBERATELY NOT SET HERE, and the reason is worth recording because the
# obvious instinct is to add it.
#
# The handler defaults SITE_URL to https://wecare.digital, which is the same way every other
# consumer of the apex in this repo gets it - PageMeta.tsx, SEO.tsx and generate-sitemap.js all
# hardcode it. It is a code constant, not deployment configuration.
#
# Setting it as an environment variable had a concrete cost. `https://wecare.digital` happens
# to be the exact value of a field in one of the Secrets Manager entries, and
# scripts/env_manifest.py fingerprints any variable whose value equals ANY Secrets Manager
# value - deliberately, because it cannot tell a benign coincidence from a real credential.
# So the committed manifest gained the line:
#
#     "SITE_URL": "sha256:efaa302b7289"
#
# which tells every future reader that this unauthenticated public route holds a secret. It
# does not. A misleading artifact in a file whose whole purpose is to be diffed against is
# worse than the tiny convenience of an overridable hostname.
ENV_VARS = {
    "LOG_LEVEL": "INFO",
    # execute-api directly, not the apex: going via wecare.digital/api would leave AWS,
    # cross CloudFront and re-enter this same API to fetch our own content.
    "MCP_BLOG_API": f"https://{API_ID}.execute-api.{REGION}.amazonaws.com/{STAGE}/seo-tools/blog-public",
    "MCP_BLOG_TTL_SECONDS": "900",
    "MCP_BLOG_TIMEOUT_SECONDS": "12",
}


def _log(stage: str, message: str) -> None:
    print(f"[{stage}] {message}")


# --------------------------------------------------------------------------- #
# packaging
# --------------------------------------------------------------------------- #

def package() -> bytes:
    """handler.py plus the catalogue, which the handler reads from beside itself."""
    for path in (HANDLER_FILE, CATALOG_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"missing {path}")

    catalog_bytes = CATALOG_FILE.read_bytes()
    # Parsed here rather than trusted: a malformed catalogue would deploy fine and then
    # fail every single tool call at runtime, because the handler loads it lazily so that
    # `initialize` still answers. Better to refuse to build.
    catalog = json.loads(catalog_bytes)
    pages = catalog.get("pages") or []
    if not isinstance(pages, list) or len(pages) < 5:
        raise ValueError(f"{CATALOG_FILE} has {len(pages)} pages; that cannot be right")

    members = {
        "handler.py": HANDLER_FILE.read_bytes(),
        "public-pages.json": catalog_bytes,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(members):
            info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[arcname])
    data = buf.getvalue()
    _log("package", f"{len(data)} bytes, {len(members)} entries, {len(pages)} public pages")
    return data


# --------------------------------------------------------------------------- #
# lambda
# --------------------------------------------------------------------------- #

def deploy_lambda(zip_bytes: bytes) -> str:
    """Create or update the function, then publish a version and move `live`.

    Publishing is NOT optional here. The API integration points at the alias, so
    `update_function_code` alone moves `$LATEST` and production keeps serving the old
    code while the deploy reports success - the failure mode
    .kiro/steering/lambda-snapstart-deploy.md (retired 2026-10-09, af7858fa) exists to prevent, and the reason
    provision_live_alias.py refuses to create an alias for a function whose deploy path
    cannot move it.
    """
    lam = boto3.client("lambda", region_name=REGION)
    config = dict(
        Runtime="python3.12",
        Role=ROLE_ARN,
        Handler="handler.handler",
        # 20s, under the API Gateway integration ceiling of 30s. The only slow path is the
        # first blog fetch on a cold sandbox (~5s for 924 kB), memoised for 15 minutes
        # afterwards.
        Timeout=20,
        # 512 MB is about CPU, not resident size: Lambda scales vCPU with memory, and the
        # cold-path work is parsing that 924 kB JSON document. Measured peak on the
        # comparable seo-tools function is 108 MB.
        MemorySize=512,
        Environment={"Variables": dict(ENV_VARS)},
        Description="Read-only MCP (Streamable HTTP) server for public wecare.digital content",
    )

    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        current = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
        current_env = (current.get("Environment") or {}).get("Variables") or {}
        # Merge, do not replace. A flag set out of band by scripts/set_lambda_env_flag.py
        # must survive a code deploy.
        config["Environment"] = {"Variables": {**current_env, **ENV_VARS}}
        _log("lambda", f"{FUNCTION_NAME} exists — updating code and configuration")
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(FunctionName=FUNCTION_NAME, **config)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    else:
        _log("lambda", f"creating {FUNCTION_NAME}")
        lam.create_function(
            FunctionName=FUNCTION_NAME,
            Code={"ZipFile": zip_bytes},
            Architectures=["x86_64"],
            Publish=False,
            **config,
        )
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)

    version = lam.publish_version(FunctionName=FUNCTION_NAME)["Version"]
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME, Qualifier=version)
    try:
        lam.update_alias(FunctionName=FUNCTION_NAME, Name="live", FunctionVersion=version)
        _log("lambda", f"moved live alias -> v{version}")
    except lam.exceptions.ResourceNotFoundException:
        lam.create_alias(FunctionName=FUNCTION_NAME, Name="live", FunctionVersion=version)
        _log("lambda", f"created live alias -> v{version}")

    cfg = lam.get_function_configuration(FunctionName=FUNCTION_NAME, Qualifier="live")
    _log("lambda", f"live = v{version}  state={cfg['State']}  "
                   f"mem={cfg['MemorySize']}MB timeout={cfg['Timeout']}s")
    return f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}:live"


# --------------------------------------------------------------------------- #
# api gateway
# --------------------------------------------------------------------------- #

def ensure_api_route(alias_arn: str) -> None:
    """One route, `ANY /mcp`, pointing at the alias.

    ANY rather than POST because the transport requires this single path to answer POST,
    GET, DELETE and OPTIONS with four different, specified results - 405 on GET is a
    protocol answer, not an accident, and API Gateway rejecting the method itself would
    produce a 403 the client cannot interpret.

    Deliberately NO `{proxy+}` route. An MCP endpoint is exactly one path; a proxy route
    would silently accept /mcp/anything and hand it to a handler that ignores the suffix,
    which invites clients to depend on a path shape we do not support.
    """
    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    integ_id = None
    for item in api.get_integrations(ApiId=API_ID, MaxResults="1000").get("Items", []):
        if (item.get("IntegrationUri") or "") == alias_arn:
            integ_id = item["IntegrationId"]
            break
    if integ_id:
        _log("api", f"reusing integration {integ_id}")
    else:
        integ_id = api.create_integration(
            ApiId=API_ID,
            IntegrationType="AWS_PROXY",
            IntegrationUri=alias_arn,
            IntegrationMethod="POST",
            PayloadFormatVersion="2.0",
            Description="wecare-mcp (live alias)",
        )["IntegrationId"]
        _log("api", f"created integration {integ_id}")

    target = f"integrations/{integ_id}"
    existing = {r["RouteKey"]: r for r in api.get_routes(ApiId=API_ID, MaxResults="1000").get("Items", [])}
    if ROUTE_KEY in existing:
        route = existing[ROUTE_KEY]
        if route.get("Target") != target:
            api.update_route(ApiId=API_ID, RouteId=route["RouteId"], Target=target)
            _log("api", f"repointed {ROUTE_KEY} -> {target}")
        else:
            _log("api", f"route already correct: {ROUTE_KEY}")
    else:
        # AuthorizationType NONE is correct and consistent with all 358 other routes on
        # this API: authentication is done in the handler, and this endpoint is public by
        # design. It is read-only by construction rather than by permission.
        api.create_route(ApiId=API_ID, RouteKey=ROUTE_KEY, Target=target, AuthorizationType="NONE")
        _log("api", f"created route {ROUTE_KEY}")

    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            Qualifier="live",
            StatementId="apigw-mcp",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*/mcp",
        )
        _log("api", "added invoke permission apigw-mcp")
    except lam.exceptions.ResourceConflictException:
        _log("api", "invoke permission apigw-mcp already present")

    ensure_route_throttle(api)


def ensure_route_throttle(api) -> None:
    """Cap /mcp on its own so it cannot spend the stage's shared allowance.

    UpdateStage MERGES RouteSettings, it does not replace them - measured here, and it is
    the opposite of the `update-user-pool` behaviour `.kiro/steering/aws-agent-rules.md` (retired; now .kiro/steering/00-common.md)
    warns about. Worth writing down because the steering's rule of thumb is to treat every
    AWS "update" as a replace until proven otherwise, and this is a proven exception.

    The awkward consequence: because it merges, it also VALIDATES THE MERGED MAP, so a
    stale key already on the stage blocks every future write and omitting it does not
    remove it. Removal needs DeleteRouteSettings. Two attempts failed on exactly that
    before this was understood:

        NotFoundException: Unable to find Route by key POST /site-language/tts
        within the provided RouteSettings

    `POST /site-language/tts` and `GET /site-language/voices` were throttles left behind
    when text-to-speech was retired. They were inert - no route, nothing to throttle - but
    they meant NO per-route throttle could be added to this API by anyone until they went.
    """
    stage = api.get_stage(ApiId=API_ID, StageName=STAGE)
    current = dict(stage.get("RouteSettings") or {})

    # STALE KEYS HAVE TO BE DROPPED, and finding that out is why this reads back.
    # UpdateStage VALIDATES every key in RouteSettings against a live route and rejects the
    # whole call otherwise:
    #
    #     NotFoundException: Unable to find Route by key POST /site-language/tts
    #     within the provided RouteSettings
    #
    # The stage carried throttles for `POST /site-language/tts` and
    # `GET /site-language/voices`, two routes deleted when text-to-speech was retired. The
    # settings were inert - there is no route to throttle - but they made the map
    # unwritable, so no per-route throttle could be added to this API by anyone until they
    # went. Dropping them is the fix and it is safe for the same reason they were harmless.
    live_routes = set()
    token = None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "500"}
        if token:
            kwargs["NextToken"] = token
        page = api.get_routes(**kwargs)
        live_routes |= {r["RouteKey"] for r in page.get("Items", [])}
        token = page.get("NextToken")
        if not token:
            break

    stale = sorted(k for k in current if k not in live_routes)
    for key in stale:
        # Safe by the same argument that made them harmless: the route does not exist, so
        # the setting throttles nothing. Removing it is what makes the map writable again.
        api.delete_route_settings(ApiId=API_ID, StageName=STAGE, RouteKey=key)
        _log("api", f"removed stale route setting for a deleted route: {key}")

    wanted = {
        **current.get(ROUTE_KEY, {}),
        "ThrottlingRateLimit": ROUTE_THROTTLE_RATE,
        "ThrottlingBurstLimit": ROUTE_THROTTLE_BURST,
    }
    if not stale and current.get(ROUTE_KEY) == wanted:
        _log("api", f"route throttle already set: {ROUTE_THROTTLE_RATE} rps / "
                    f"{ROUTE_THROTTLE_BURST} burst")
        return
    # Only our key, because the call merges. Sending the rest would be a no-op at best.
    api.update_stage(ApiId=API_ID, StageName=STAGE, RouteSettings={ROUTE_KEY: wanted})
    after = dict(api.get_stage(ApiId=API_ID, StageName=STAGE).get("RouteSettings") or {})
    applied = after.get(ROUTE_KEY, {})
    if applied.get("ThrottlingRateLimit") != ROUTE_THROTTLE_RATE:
        raise RuntimeError(f"route throttle did not apply: {applied}")
    # Only a LIVE key going missing is a fault. The stale ones were removed on purpose.
    lost = (set(current) - set(after)) & live_routes
    if lost:
        raise RuntimeError(f"update_stage dropped route settings for live routes: {sorted(lost)}")
    _log("api", f"route throttle set on {ROUTE_KEY}: {ROUTE_THROTTLE_RATE} rps / "
                f"{ROUTE_THROTTLE_BURST} burst  (stage default stays "
                f"{stage.get('DefaultRouteSettings', {}).get('ThrottlingRateLimit')} rps)")


# --------------------------------------------------------------------------- #
# amplify hosting
# --------------------------------------------------------------------------- #

def _load_rules(amp) -> list:
    return list(amp.get_app(appId=AMPLIFY_APP_ID)["app"].get("customRules") or [])


def _plan_rules(rules: list) -> list:
    """Insert the /mcp rules immediately above the terminal catch-all.

    Returns the full desired list. Idempotent: an already-correct rule is left in place
    rather than moved, so repeated runs do not churn the ordering of the ~108 rules this
    app carries.
    """
    wanted = {rule["source"]: rule for rule in HOSTING_RULES}
    kept = [r for r in rules if r.get("source") not in wanted]

    catch_all_positions = [i for i, r in enumerate(kept) if r.get("source") == CATCH_ALL_SOURCE]
    if not catch_all_positions:
        # Refuse rather than append. Without the catch-all the app's 404 handling is
        # already wrong, and guessing at a position in someone else's 108-rule list is how
        # a routing change becomes an outage.
        raise RuntimeError(
            f"no {CATCH_ALL_SOURCE} catch-all rule found in the live app; refusing to guess "
            "a position. Inspect the app's Rewrites and redirects before re-running."
        )
    index = catch_all_positions[0]
    return kept[:index] + list(HOSTING_RULES) + kept[index:]


def ensure_hosting_rules(dry_run: bool = False) -> None:
    amp = boto3.client("amplify", region_name=REGION)
    current = _load_rules(amp)
    snapshot = ROOT / ".scratch" / f"amplify-customrules-before-mcp-{time.strftime('%Y%m%d-%H%M%S')}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(current, indent=2), encoding="utf-8")
    _log("hosting", f"snapshotted {len(current)} rules -> {snapshot.relative_to(ROOT)}")

    desired = _plan_rules(current)
    if desired == current:
        _log("hosting", "rules already correct — no change")
        return
    if dry_run:
        _log("hosting", f"WOULD update customRules: {len(current)} -> {len(desired)} rules")
        for rule in HOSTING_RULES:
            _log("hosting", f"  + {rule['source']} -> {rule['target']} ({rule['status']})")
        return

    amp.update_app(appId=AMPLIFY_APP_ID, customRules=desired)
    _log("hosting", f"updated customRules: {len(current)} -> {len(desired)} rules")

    # Read back. `update_app` is a partial update for omitted fields, but customRules is
    # replaced wholesale, and a silently reordered or dropped rule is the failure this
    # guards. The catch-all MUST still be last or every path below it is dead.
    after = _load_rules(amp)
    problems = []
    for rule in HOSTING_RULES:
        if rule not in after:
            problems.append(f"missing after write: {rule['source']}")
    if not after or after[-1].get("source") != CATCH_ALL_SOURCE:
        problems.append(f"{CATCH_ALL_SOURCE} is no longer the last rule")
    for rule in current:
        if rule not in after and rule.get("source") not in {r["source"] for r in HOSTING_RULES}:
            problems.append(f"pre-existing rule lost: {rule.get('source')}")
    if problems:
        raise RuntimeError("hosting rules verification failed:\n  " + "\n  ".join(problems)
                           + f"\n  restore from {snapshot}")
    _log("hosting", f"verified: /mcp rules present, {CATCH_ALL_SOURCE} still last")


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def verify() -> int:
    """Check live state without changing anything. Exit 1 on any problem."""
    problems: list[str] = []
    lam = boto3.client("lambda", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)
    amp = boto3.client("amplify", region_name=REGION)

    try:
        cfg = lam.get_function_configuration(FunctionName=FUNCTION_NAME, Qualifier="live")
        _log("verify", f"lambda live: state={cfg['State']} mem={cfg['MemorySize']} timeout={cfg['Timeout']}")
        if cfg.get("State") != "Active":
            problems.append(f"lambda state is {cfg.get('State')}")
    except ClientError as exc:
        problems.append(f"lambda/live alias unreachable: {exc.response['Error']['Code']}")

    # IS THE DEPLOYED CATALOGUE THE ONE IN THE REPO?
    #
    # This function carries a copy of config/public-pages.json inside its deployment ZIP.
    # A catalogue change therefore requires an explicit MCP redeploy. This verifier compares
    # the deployed bytes with the repository so stale catalogue data fails loudly.
    try:
        import hashlib
        local = hashlib.sha256(CATALOG_FILE.read_bytes()).hexdigest()
        artifact = lam.get_function(FunctionName=FUNCTION_NAME, Qualifier="live")
        import urllib.request as _req
        with _req.urlopen(artifact["Code"]["Location"], timeout=60) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            deployed = hashlib.sha256(archive.read("public-pages.json")).hexdigest()
        if deployed != local:
            problems.append(
                "the DEPLOYED catalogue differs from config/public-pages.json. The MCP "
                "server is describing pages that may no longer exist, or missing ones that "
                "do. Fix with: python scripts/deploy_mcp_server.py")
        else:
            _log("verify", "deployed catalogue matches config/public-pages.json")
    except (ClientError, KeyError, OSError, zipfile.BadZipFile) as exc:
        problems.append(f"could not compare the deployed catalogue: {type(exc)}")

    routes = {r["RouteKey"]: r for r in api.get_routes(ApiId=API_ID, MaxResults="1000").get("Items", [])}
    if ROUTE_KEY not in routes:
        problems.append(f"API route missing: {ROUTE_KEY}")
    else:
        _log("verify", f"api route present: {ROUTE_KEY} -> {routes[ROUTE_KEY].get('Target')}")

    settings = (api.get_stage(ApiId=API_ID, StageName=STAGE).get("RouteSettings") or {})
    throttle = settings.get(ROUTE_KEY) or {}
    if throttle.get("ThrottlingRateLimit") != ROUTE_THROTTLE_RATE:
        problems.append(f"route throttle missing or changed on {ROUTE_KEY}: {throttle or 'none'} "
                        f"(expected {ROUTE_THROTTLE_RATE} rps). Without it this public route "
                        f"shares the stage allowance with every other route.")
    else:
        _log("verify", f"route throttle: {throttle['ThrottlingRateLimit']} rps / "
                       f"{throttle.get('ThrottlingBurstLimit')} burst")

    rules = _load_rules(amp)
    sources = [r.get("source") for r in rules]
    for rule in HOSTING_RULES:
        if rule in rules:
            _log("verify", f"hosting rule present: {rule['source']}")
        else:
            problems.append(f"hosting rule missing or altered: {rule['source']} "
                            f"(expected target {rule['target']} status {rule['status']})")
    if sources and sources[-1] != CATCH_ALL_SOURCE:
        problems.append(f"{CATCH_ALL_SOURCE} is not the last rule; rules below it are dead")
    for rule in HOSTING_RULES:
        if rule["source"] in sources and CATCH_ALL_SOURCE in sources:
            if sources.index(rule["source"]) > sources.index(CATCH_ALL_SOURCE):
                problems.append(f"{rule['source']} sits BELOW the catch-all and can never match")

    if problems:
        print("\nVERIFY FAILED")
        for problem in problems:
            print(f"  - {problem}")
        print("\n  Re-run: python scripts/deploy_mcp_server.py")
        return 1
    print("\nVERIFY OK — wecare-mcp is deployed, routed, and reachable on the apex")
    return 0


# --------------------------------------------------------------------------- #
# verify-live
# --------------------------------------------------------------------------- #

def _rpc(method: str, params: dict, timeout: int) -> dict:
    """One JSON-RPC POST to the public endpoint. Raises on transport or parse failure.

    NO initialize HANDSHAKE. The server is stateless streamable-http, and a bare tools/call
    was measured to work against production on 2026-09-30 - so a handshake would add a round
    trip and a second thing to go wrong without proving anything more.

    `accept: application/json` only. The MCP streamable-http transport invites
    `application/json, text/event-stream`, and the deployed server was measured to answer
    application/json either way; asking for JSON alone means a future switch to event-stream
    framing surfaces as a parse failure here rather than being silently tolerated.
    """
    import urllib.request

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        PUBLIC_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            # Named so an operator reading access logs can tell this apart from a real client.
            "user-agent": "wecare-mcp-catalogue-drift-check",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def verify_live(timeout: int = 25) -> int:
    """Compare what the LIVE endpoint serves with config/public-pages.json. No credentials.

    WHY THIS EXISTS ALONGSIDE --verify, WHICH ALREADY CHECKS THE CATALOGUE.
    --verify downloads the deployed ZIP and compares public-pages.json byte for byte, but it
    requires AWS credentials. This check needs only the public MCP endpoint, so it is useful
    when AWS credentials are unavailable and it measures what clients actually receive.

    It is weaker in one way and the difference is worth stating: it can only see fields a tool
    exposes. `list_pages` returns path, name, description and group, which is every field the
    catalogue's `pages` entries carry, so for `pages` the two are equivalent. It cannot see
    drift in `usage_terms` or `ai_surface`; `--verify` can. Run both where you can.

    EXIT CODES, and why unreachable is not a failure.
        0  the live catalogue matches the repo
        1  DRIFT - the live catalogue disagrees. A real, actionable finding.
        3  UNREACHABLE - the endpoint could not be read, so NOTHING is known about live
           state. Distinct from 1 so a network blip is never reported as configuration drift.
    """
    print("=" * 78)
    print(f"live catalogue drift check  ->  {PUBLIC_ENDPOINT}")
    print("=" * 78)

    try:
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log("live", f"cannot read {CATALOG_FILE}: {exc}")
        return 3

    try:
        payload = _rpc("tools/call", {"name": "list_pages", "arguments": {}}, timeout)
    except Exception as exc:  # noqa: BLE001 - any transport failure means "nothing is known"
        _log("live", f"UNREACHABLE: {type(exc).__name__}: {exc}")
        print("\nNothing is known about the live catalogue, so this is NOT reported as drift.")
        return 3

    if "error" in payload:
        _log("live", f"UNREACHABLE: endpoint returned a JSON-RPC error: {payload['error']}")
        return 3
    result = payload.get("result") or {}
    if result.get("isError"):
        _log("live", f"UNREACHABLE: list_pages reported an error: {result.get('content')}")
        return 3
    served = (result.get("structuredContent") or {}).get("pages")
    if not isinstance(served, list) or not served:
        _log("live", "UNREACHABLE: no structuredContent.pages in the response")
        return 3

    # Compare on the four fields the catalogue declares. `url` is derived from `path` by the
    # handler rather than stored, so it is checked for self-consistency instead of equality.
    fields = ("path", "name", "description", "group")
    def key(page: dict) -> tuple:
        return tuple(page.get(f) for f in fields)

    local = {p["path"]: key(p) for p in catalog.get("pages", [])}
    live = {p.get("path"): key(p) for p in served}
    _log("live", f"repo declares {len(local)} pages; the endpoint serves {len(live)}")

    problems: list[str] = []
    for path in sorted(set(local) - set(live)):
        problems.append(f"MISSING from the live endpoint: {path}  ({local[path][1]})")
    for path in sorted(set(live) - set(local)):
        problems.append(f"STILL SERVED but not in the repo: {path}  ({live[path][1]}) "
                        f"- an agent given this URL may get a 404")
    for path in sorted(set(local) & set(live)):
        if local[path] != live[path]:
            for i, field in enumerate(fields):
                if local[path][i] != live[path][i]:
                    problems.append(f"{path} {field} differs:\n"
                                    f"        repo: {local[path][i]!r}\n"
                                    f"        live: {live[path][i]!r}")

    # A trailing slash on every url, for the reason test_mcp_server.py pins it: trailingSlash
    # means the slashless form 301s, so a citation without it can rot.
    for page in served:
        url, path = page.get("url", ""), page.get("path", "")
        expected = f"{SITE}/" if path == "/" else f"{SITE}{path}/"
        if url != expected:
            problems.append(f"{path} url is {url!r}, expected {expected!r}")

    if problems:
        print("\nDRIFT — the live /mcp is not describing this repository's pages")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\n  /mcp carries its OWN COPY of config/public-pages.json inside its deployment"
            "\n  zip, so a catalogue change does not reach it until the Lambda is redeployed."
            "\n"
            "\n  Converge with:"
            "\n      python scripts/deploy_mcp_server.py"
        )
        return 1

    print(f"\nLIVE OK — the endpoint serves the same {len(live)} pages the repo declares")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="build and report, change nothing")
    parser.add_argument("--verify", action="store_true", help="check live state, change nothing")
    parser.add_argument("--verify-live", action="store_true",
                        help="compare the public endpoint's catalogue with the repo. "
                             "No AWS credentials. Exit 1 on drift, 3 if unreachable.")
    parser.add_argument("--timeout", type=int, default=25,
                        help="seconds to wait for the endpoint in --verify-live (default 25)")
    parser.add_argument("--skip-hosting", action="store_true", help="Lambda and API route only")
    args = parser.parse_args()

    # BEFORE --verify, so the credential-free check never reaches a boto3 client. Both flags
    # together run the cheap public one first and stop if it already found the answer.
    if args.verify_live:
        return verify_live(args.timeout)
    if args.verify:
        return verify()

    print("=" * 78)
    print("deploy wecare-mcp  ->  https://wecare.digital/mcp")
    print("=" * 78)

    zip_bytes = package()
    if args.dry_run:
        _log("dry-run", "not uploading; checking hosting rule plan only")
        ensure_hosting_rules(dry_run=True)
        return 0

    alias_arn = deploy_lambda(zip_bytes)
    ensure_api_route(alias_arn)
    if args.skip_hosting:
        _log("hosting", "skipped by --skip-hosting")
    else:
        ensure_hosting_rules()

    print("=" * 78)
    print(f"Endpoint: https://wecare.digital/mcp   (transport: streamable-http, stateless)")
    print(f"Verify:   python scripts/deploy_mcp_server.py --verify")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
