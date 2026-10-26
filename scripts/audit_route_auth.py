#!/usr/bin/env python3
"""Find HTTP API routes that are open at BOTH the gateway and the handler.

Why this exists
---------------
On 2026-09-20, while retiring a provider integration, three routes were found by
accident:

    POST   /voice-cdr-webhook              AuthorizationType=NONE
    GET    /voice-cdr-webhook              AuthorizationType=NONE
    DELETE /voice-cdr-webhook/clear-logs   AuthorizationType=NONE

Their handler contained no `require_auth` either, so they were reachable by
anyone. That allowed a forged CDR to fan out WhatsApp and SMS to two hardcoded
admin numbers, an arbitrary `recordingURL` to be fetched server-side and written
into S3 (SSRF plus arbitrary upload), and every call detail record to be wiped.

Three were found by accident out of 331 routes. This script checks the rest.

What "open" means here
----------------------
`AuthorizationType=NONE` on its own is NOT a finding. Most of this API
authenticates inside the Lambda via `lambda_utils.middleware.require_auth`, and
provider webhooks authenticate by signature (Plivo V3, Razorpay HMAC, Meta
X-Hub-Signature) which cannot be expressed as an API Gateway authorizer.

A route is reported OPEN only when the gateway does not authorize it AND its
handler shows no evidence of authenticating: no `require_auth`, no signature
verification, no shared-secret comparison.

Confidence is deliberately limited: this greps handler source for auth markers,
so a handler that authenticates by some means not in MARKERS will be reported as
a false positive. Read the finding before acting on it. Silence is not proof of
safety either - an unused marker name would hide a real hole.

Scope corrections, 2026-09-21
-----------------------------
Three defects in the original version made its "0 findings" untrustworthy:

1. It hardcoded ONE api id. Account 775261844268 has TWO HTTP APIs, and the
   unscanned one (`79g3bbufdh`) carries `/webhook/sinch-dlr` plus `/ai/generate`.
   Every prior "331 routes, 0 findings" claim silently excluded them. All HTTP
   APIs are now discovered unless `--api` is given.

2. Handler directories were registered only as `wecare-{slug}`,
   `wecare-{parent}-{slug}` and `stack-wecare-{slug}`. The directory
   `messaging/inbound-whatsapp-handler` therefore never matched the deployed
   function `wecare-inbound-whatsapp`, so `POST /whatsapp/inbound` - a genuinely
   unauthenticated Meta ingress - was filed as "source not resolvable" instead of
   OPEN. A `-handler` suffix is now stripped, among other aliases.

3. A route whose target function no longer exists was indistinguishable from a
   route whose source could not be located. Those are now separate classes, so a
   route left pointing at a deleted function is reported as DANGLING rather than
   hiding inside UNRESOLVED.

Scope corrections, 2026-10-26
-----------------------------
4. Function names now resolve through `deploy_all_lambdas.SPECS` before the
   directory guess. No directory is named after `wecare-commerce`, which ships
   `ecommerce/checkout` plus the invoice engine, so once the invoice and checkout
   routes moved to it they were all UNRESOLVED: 22 routes, `DELETE
   /invoices/clear-all` among them, that this audit had stopped checking.

5. An allowlisted route key no longer covers every API that reuses it. The reason
   written for `ANY /mcp` on `wecare-mcp` ("read-only MCP server over public
   content") was also passing `ANY /mcp` on the staff Chat API, which is the
   administrative workspace MCP.

6. A function whose code ships inline in a CloudFormation template keeps it in
   `index.py`, the name Lambda gives `Code.ZipFile`, so a directory holding only
   `index.py` was never read: the seven routes of `wecare-customer-commerce-mcp`
   (ai/customer-commerce-mcp) could only ever be UNRESOLVED.

Marker strength
---------------
Some MARKERS are weak: `Authorization`, `api_key`/`API_KEY` and `verify_token`
match a handler that merely sends an outbound provider header, which would mark a
hole as safe - the exact failure the docstring calls unacceptable. `--strict`
recomputes with the weak markers removed and prints the delta so the difference
is visible instead of assumed. The default keeps the established baseline.

Usage
-----
    python scripts/audit_route_auth.py              # report, all HTTP APIs
    python scripts/audit_route_auth.py --strict     # also report the strict delta
    python scripts/audit_route_auth.py --json       # machine-readable evidence
    python scripts/audit_route_auth.py --api zllr9lrg7j
    python scripts/audit_route_auth.py --gate       # exit 1 if any OPEN route

Exit codes
----------
    0  no OPEN routes, or report mode
    1  at least one OPEN route (only with --gate)
    2  could not query AWS
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
REPO = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS_ROOT = REPO / "amplify/functions"

# Evidence that a handler authenticates its caller somehow. Deliberately broad:
# a false NEGATIVE here (missing a real auth mechanism) produces a false alarm,
# which is cheap. A false POSITIVE marks a hole as safe, which is not.
STRONG_MARKERS = (
    "require_auth",            # lambda_utils.middleware, Cognito JWT
    "require_role",
    "verify_signature",
    "_verify_provider",        # plivo-answer signature/trust ladder
    "plivo_signature",
    "X-Razorpay-Signature",
    "x-hub-signature",
    "X-Hub-Signature",
    "hmac.compare_digest",
    "compare_digest",
    "shared_secret",
    "SHARED_SECRET",
    # Delegation to the shared verifiers. Handler source is concatenated per
    # directory, so a handler that calls out to lambda_utils shows only the call
    # site - without these, rcs-dlr and inbound-whatsapp read as unauthenticated
    # even though they verify correctly.
    "sinch_signature.verify",
    "meta_signature.verify",
    # Customer pool verification delegates to its issuer-pinned JWT helper.
    # Match the call, not a module import or an outbound Authorization header.
    "customer_auth.require_customer(",
    "customer_auth.authenticate(",
    # The workspace MCP checks its own callers: issuer, staff client, access-token use, the
    # Admin group and expiry, then a live Cognito recheck of the session.
    "owner_identity(event)",
    # The customer commerce MCP's private tools: a `wca_` bearer bound to this resource and
    # scope, its stored session, then a live Cognito recheck of the customer.
    "customer_oauth.customer_event(",
)

# Markers that only prove a handler can CALL OUT with a credential, never that it
# checks its own caller. Retired from the default set on 2026-09-21 after each one
# was traced to an outbound header or a CORS string:
#
#   appsecret_proof  the Graph query parameter Meta requires on outbound calls.
#                    On its own it classified POST /whatsapp/inbound as
#                    "handler authenticates" while that handler verified nothing.
#   api_key/API_KEY  in product-image-gen this was an outbound provider API key,
#                    never a check on the caller.
#   Authorization    in all seven affected handlers this was either
#                    "Access-Control-Allow-Headers: Content-Type,Authorization"
#                    or an outbound `Authorization: Bearer` to a provider.
#   verify_token     a Meta webhook verify token, used on the GET handshake only.
#
# They remain listed so --lenient can reproduce the old baseline for comparison,
# but the default is now the strict set. A marker must prove the handler checks
# ITS CALLER.
WEAK_MARKERS = (
    "appsecret_proof",
    "verify_token",
    "VERIFY_TOKEN",
    "api_key",
    "API_KEY",
    "Authorization",
)

MARKERS = STRONG_MARKERS

# Routes intentionally reachable without a caller identity. Each needs a reason,
# and each was read before being listed.
EXPECTED_PUBLIC_METHODS = {
    "OPTIONS": "CORS preflight; carries no data and must not require auth",
}

EXPECTED_PUBLIC_ROUTES = {
    # Dedicated GET-only Lambda: published posts and approved FAQ projections only.
    # Its execution role cannot write the native store. See test_blog_public_reader.py.
    "GET /seo-tools/blog-public": "anonymous published-blog list; fixed public field allowlist and read-only dedicated Lambda",
    "GET /seo-tools/blog-public/{proxy+}": "anonymous published-post detail; validated slug, published-only lookup, approved FAQ only",
    # Short links are followed by customers who have no Cognito session. The
    # handler authenticates the /links management routes separately.
    "GET /r/{code}": "public short-link redirect; anonymous by definition",
    # The endpoint whose job is to validate a token cannot require a valid token.
    "POST /auth/validate": "token validation endpoint; authenticating it would be circular",
    "POST /auth/email-verification": "public email-ownership OTP door; it returns only a short-lived email-bound proof and performs no customer or contact write",
    "POST /vayulok/environment": "anonymous public environmental read proxy; no customer session exists, and the handler restricts origin, India bounds, fixed operations and provider fan-out before any metered call",
    # Provider webhooks authenticate by signature over the raw body, which cannot
    # be expressed as an API Gateway authorizer. Verified in the handler.
    "GET /webhook/sinch-rcs": "Sinch health probe; POST carries the HMAC",
    "POST /webhook/sinch-rcs": "Sinch Conversation API HMAC over rawBody.nonce.timestamp",
    # The MCP endpoint. An MCP client has no Cognito session and the protocol has no
    # place to put one, so requiring auth would make the endpoint unusable for its only
    # purpose. Safe because every tool is a read of ALREADY-PUBLIC content and the
    # capability to do anything else is absent rather than merely unpermitted: the
    # handler imports no boto3, so there is no table, queue or model it can reach, and
    # tests/test_mcp_server.py asserts the advertised tool list for EXACT equality
    # against a frozen read-only allowlist. Read docs/ai-discovery-surface.md before
    # widening this. If a tool that mutates or that costs money per call is ever added,
    # this line must come out and the route must move behind require_auth.
    "ANY /mcp": "read-only MCP server over public content; no auth possible in-protocol",
    "GET /workspace/mcp/oauth/callback": "provider OAuth callback; exact route, ten-minute principal-bound one-use state and PKCE; no administrative tools exposed",
    # Public catalogue artwork is fetched by browsers and Meta before any customer identity
    # exists. The dedicated handler accepts GET only, validates an exact lowercase
    # *-4096.png filename, and its execution role can only GetObject below the one
    # secure/d/public/catalog-deploy/catalog/products/ prefix.
    "GET /catalog-media/{filename}": "anonymous approved-catalog-artwork read; GET only, strict *-4096.png filename validation, and read-only S3 permission scoped to secure/d/public/catalog-deploy/catalog/products/",
    # The live price shown on the four public service pages. A visitor reads it BEFORE signing
    # in -- the price is what decides whether they sign in at all -- so there is no identity to
    # authenticate. Narrow by construction: GET only, and the handler arm accepts no path
    # parameter, no query string and no body, so nothing a caller supplies reaches the
    # catalog read. It cannot mutate anything, returns only live prices from the AWS-native
    # ProductsTable in integer paise, and is edge-cached for 60 seconds. POST on the same
    # path still requires a customer session.
    "GET /ecommerce/service-prices": "anonymous public price read. There is no customer identity to authenticate on a public service page; the arm accepts no path, query or body input, returns only live AWS-native catalog prices in integer paise, cannot mutate anything, and is edge-cached for 60 seconds",
}

# Route keys are reused across APIs, and a reason written for one handler says nothing about
# another. A key listed here is allowlisted only when its route targets one of these functions.
PUBLIC_ROUTE_TARGETS = {
    "ANY /mcp": {"wecare-mcp"},
}

# Public by protocol on one function only. The Chat API fronts the staff workspace MCP with
# OAuth for a public client, so discovery, authorize and token must be reachable before sign-in.
# Its `ANY /mcp` is deliberately absent: it must keep passing on its own caller check.
EXPECTED_PUBLIC_BY_FUNCTION = {
    "wecare-workspace-mcp": {
        "GET /.well-known/oauth-protected-resource": "RFC 9728 protected-resource metadata; a fixed discovery document that reads no request input",
        "GET /.well-known/oauth-authorization-server": "RFC 8414 authorization-server metadata; a fixed discovery document that reads no request input",
        "GET /authorize": "OAuth authorization endpoint for a public client: exact client_id, redirect_uri and resource, PKCE S256 only, then a 302 to the Cognito hosted UI where staff sign in; it issues nothing itself",
        "POST /token": "OAuth token endpoint for a public client: form-encoded, exact client_id, redirect_uri and resource, PKCE verifier required for a code; it relays Cognito's token only when that token is bound to this client and resource",
    },
    # The customer commerce MCP is its own OAuth server; customers sign in on its form with a
    # WhatsApp code. `POST /mcp` is absent: it keeps passing on its bearer check.
    "wecare-customer-commerce-mcp": {
        "GET /.well-known/oauth-protected-resource": "RFC 9728 protected-resource metadata; a fixed discovery document that reads no request input",
        "GET /.well-known/oauth-authorization-server": "RFC 8414 authorization-server metadata; a fixed discovery document that reads no request input",
        "GET /oauth/authorize": "OAuth authorize for a registered public client: exact parameter set, a registered redirect_uri, this resource, PKCE S256; it only opens a 10-minute sign-in form bound to an HttpOnly cookie and a CSRF hash",
        "POST /oauth/authorize": "the sign-in form post: same origin, the session cookie and a one-use CSRF hash; the customer proves the WhatsApp number with a Cognito CUSTOM_AUTH code before a two-minute PKCE-bound code is issued",
        "POST /oauth/token": "OAuth token endpoint for a public client: a one-use code with its PKCE S256 verifier and exact redirect, or a one-use refresh token; each grant rechecks the customer's Cognito session",
        "POST /oauth/revoke": "OAuth revocation: exact client and resource; it can delete only the session rows of the token presented",
    },
}


def packaged_sources() -> dict[str, list[pathlib.Path]]:
    """Function name -> the .py files its package is built from, per the deploy map.

    `deploy_all_lambdas.SPECS` is the authority on which directory a function ships, so the
    directory-name guess in `handler_sources` is only the fallback for functions it does not
    own (the delegated MCP, SEO and blog readers).
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import deploy_all_lambdas as dal  # noqa: PLC0415

    out: dict[str, list[pathlib.Path]] = {}
    for spec in dal.SPECS:
        if spec.standalone:
            files = [spec.handler_file]
        else:
            files = [f for f in spec.source.rglob("*.py")
                     if not set(f.relative_to(spec.source).parts) & dal.EXCLUDE_DIRS]
            files += [dal.FUNCTIONS / source for source, _ in spec.external_files
                      if source.endswith(".py")]
        files = sorted(f for f in files if f.is_file())
        if files:
            out[spec.name] = files
    return out


def handler_sources() -> dict[str, str]:
    """Map candidate deployed function name -> concatenated source of its dir."""
    out: dict[str, str] = {}
    # `index.py` is the entry file when the code ships inline in a CloudFormation template.
    entries = list(FUNCTIONS_ROOT.rglob("handler.py"))
    with_handler = {p.parent for p in entries}
    entries += [p for p in FUNCTIONS_ROOT.rglob("index.py") if p.parent not in with_handler]
    for handler in entries:
        if "__pycache__" in str(handler):
            continue
        # amplify/functions/messaging/outbound-sms/handler.py -> outbound-sms
        slug = handler.parent.name
        parent = handler.parent.parent.name
        text = ""
        for f in handler.parent.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            try:
                text += f.read_text(errors="replace")
            except OSError:
                pass

        # A directory name is not the deployed function name. Register every
        # plausible mapping, including the `-handler` suffix that the repo uses
        # for `inbound-whatsapp-handler` -> `wecare-inbound-whatsapp`.
        slugs = {slug, parent + "-" + slug}
        if slug.endswith("-handler"):
            bare = slug[: -len("-handler")]
            slugs |= {bare, parent + "-" + bare}
        if slug.startswith("wecare-"):
            slugs.add(slug[len("wecare-"):])

        keys = set()
        for s in slugs:
            keys |= {"wecare-" + s, "stack-wecare-" + s, s}
        for key in keys:
            out.setdefault(key, "")
            out[key] += text

    # The deploy map overrides the guess. No directory is named after `wecare-commerce`, which
    # ships ecommerce/checkout plus the invoice engine, so without this its routes resolve to
    # nothing and are filed UNRESOLVED instead of being checked.
    for name, files in packaged_sources().items():
        text = ""
        for f in files:
            try:
                text += f.read_text(errors="replace")
            except OSError:
                pass
        out[name] = text
    return out


def _paginate(fn, api_id: str, item_key: str = "Items") -> tuple[list, int]:
    items, token, pages = [], None, 0
    while True:
        kw = {"ApiId": api_id, "MaxResults": "100"}
        if token:
            kw["NextToken"] = token
        r = fn(**kw)
        items += r[item_key]
        pages += 1
        token = r.get("NextToken")
        if not token:
            return items, pages


def classify(routes, integrations, sources, live_functions, markers):
    """Split routes into authorized / handler-ok / OPEN / dangling / unresolved."""
    authorized = 0
    handler_ok: list[tuple[str, str]] = []
    open_routes: list[tuple[str, str]] = []
    dangling: list[tuple[str, str]] = []
    unresolved: list[tuple[str, str]] = []
    expected_public: list[tuple[str, str]] = []

    for rt in sorted(routes, key=lambda x: x["RouteKey"]):
        key = rt["RouteKey"]
        method = key.split()[0]
        if rt.get("AuthorizationType") not in (None, "NONE"):
            authorized += 1
            continue
        if method in EXPECTED_PUBLIC_METHODS:
            continue

        target = (rt.get("Target") or "").split("/")[-1]
        uri = integrations.get(target, "")
        fn = ""
        m = re.search(r"function:([A-Za-z0-9\-_]+)", uri)
        if m:
            fn = m.group(1)

        reason = EXPECTED_PUBLIC_ROUTES.get(key)
        allowed_targets = PUBLIC_ROUTE_TARGETS.get(key)
        if reason and allowed_targets is not None and fn not in allowed_targets:
            reason = None
        if not reason:
            reason = EXPECTED_PUBLIC_BY_FUNCTION.get(fn, {}).get(key)
        if reason:
            expected_public.append((key, reason))
            continue

        # A route whose target function does not exist is retirement residue,
        # not an authentication question. Report it separately.
        if fn and live_functions and fn not in live_functions:
            dangling.append((key, fn))
            continue

        src = sources.get(fn, "")
        if not src:
            unresolved.append((key, fn or "<unresolved>"))
            continue
        if any(mk in src for mk in markers):
            handler_ok.append((key, fn))
        else:
            open_routes.append((key, fn))

    return authorized, handler_ok, open_routes, dangling, unresolved, expected_public


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 if any OPEN route is found")
    ap.add_argument("--api", action="append", metavar="API_ID",
                    help="restrict to one api id (repeatable); default is all")
    ap.add_argument("--lenient", action="store_true",
                    help="also accept the weak markers (Authorization, api_key, "
                         "verify_token, appsecret_proof) that were retired from "
                         "the default set on 2026-09-21; reproduces the old "
                         "baseline for comparison only")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable evidence instead of a report")
    args = ap.parse_args()

    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    try:
        if args.api:
            api_ids = list(args.api)
            api_names = {a: a for a in api_ids}
        else:
            apis, _ = [], None
            token = None
            while True:
                kw = {"MaxResults": "100"}
                if token:
                    kw["NextToken"] = token
                r = api.get_apis(**kw)
                apis += r["Items"]
                token = r.get("NextToken")
                if not token:
                    break
            http = [a for a in apis if a.get("ProtocolType") == "HTTP"]
            api_ids = [a["ApiId"] for a in http]
            api_names = {a["ApiId"]: a.get("Name", "") for a in http}

        live_functions = set()
        token = None
        while True:
            kw = {"MaxItems": 100}
            if token:
                kw["Marker"] = token
            r = lam.list_functions(**kw)
            live_functions |= {f["FunctionName"] for f in r["Functions"]}
            token = r.get("NextMarker")
            if not token:
                break

        per_api = {}
        for aid in api_ids:
            routes, pages = _paginate(api.get_routes, aid)
            ints, _ = _paginate(api.get_integrations, aid)
            per_api[aid] = {
                "routes": routes,
                "pages": pages,
                "integrations": {i["IntegrationId"]: i.get("IntegrationUri", "")
                                 for i in ints},
            }
    except (ClientError, BotoCoreError) as exc:
        print(f"could not read AWS: {type(exc).__name__}", file=sys.stderr)
        return 2

    sources = handler_sources()
    total_open: list[tuple[str, str, str]] = []
    total_dangling: list[tuple[str, str, str]] = []
    total_unresolved: list[tuple[str, str, str]] = []
    report = {"region": REGION, "apis": {}, "liveFunctions": len(live_functions)}

    for aid in api_ids:
        d = per_api[aid]
        markers = MARKERS + WEAK_MARKERS if args.lenient else MARKERS
        authorized, handler_ok, open_r, dangling, unresolved, pub = classify(
            d["routes"], d["integrations"], sources, live_functions, markers)

        entry = {
            "name": api_names.get(aid, ""),
            "routes": len(d["routes"]),
            "pages": d["pages"],
            "integrations": len(d["integrations"]),
            "gatewayAuthorized": authorized,
            "handlerAuthenticates": len(handler_ok),
            "expectedPublic": [f"{k}  ({why})" for k, why in pub],
            "open": [f"{k} -> {f}" for k, f in open_r],
            "dangling": [f"{k} -> {f}" for k, f in dangling],
            "unresolved": [f"{k} -> {f}" for k, f in unresolved],
        }

        report["apis"][aid] = entry
        total_open += [(aid, k, f) for k, f in open_r]
        total_dangling += [(aid, k, f) for k, f in dangling]
        total_unresolved += [(aid, k, f) for k, f in unresolved]

    report["totals"] = {
        "apis": len(api_ids),
        "routes": sum(len(per_api[a]["routes"]) for a in api_ids),
        "open": len(total_open),
        "dangling": len(total_dangling),
        "unresolved": len(total_unresolved),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if (total_open and args.gate) else 0

    print(f"HTTP APIs scanned : {len(api_ids)}  ({', '.join(api_ids)})")
    print(f"handler dirs      : {len(sources)}")
    print(f"live functions    : {len(live_functions)}\n")

    for aid in api_ids:
        e = report["apis"][aid]
        print(f"--- {aid}  {e['name']}")
        print(f"    routes {e['routes']} across {e['pages']} page(s), "
              f"integrations {e['integrations']}")
        print(f"    gateway-authorized                  : {e['gatewayAuthorized']}")
        print(f"    gateway NONE, handler authenticates : {e['handlerAuthenticates']}")
        print(f"    expected public (allowlisted)       : {len(e['expectedPublic'])}")
        print(f"    DANGLING (target function absent)   : {len(e['dangling'])}")
        print(f"    UNRESOLVED (source not found)       : {len(e['unresolved'])}")
        print(f"    OPEN (no auth at either layer)      : {len(e['open'])}")
        for line in e["expectedPublic"]:
            print(f"      public: {line}")
        print()

    if total_open:
        print("OPEN ROUTES - reachable by anyone:")
        for aid, key, fn in total_open:
            print(f"  [{aid}] {key:40} -> {fn}")
        print()
    if total_dangling:
        print("DANGLING ROUTES - target Lambda no longer exists:")
        for aid, key, fn in total_dangling:
            print(f"  [{aid}] {key:40} -> {fn}")
        print()
    if total_unresolved:
        print("UNRESOLVED - could not find handler source, verify by hand:")
        for aid, key, fn in total_unresolved[:40]:
            print(f"  [{aid}] {key:40} -> {fn}")
        if len(total_unresolved) > 40:
            print(f"  ... {len(total_unresolved) - 40} more")
        print()
    if args.lenient:
        print("NOTE: --lenient accepted the retired weak markers. The default run "
              "is the honest one.\n")

    if total_open and args.gate:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
