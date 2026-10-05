#!/usr/bin/env python3
"""Find HTTP API routes that are open at BOTH the gateway and the handler.

Why this exists
---------------
On 2026-09-20, while removing Airtel, three routes were found by accident:

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
   route whose source could not be located. Those are now separate classes, so
   retired-provider residue (`wecare-sinch-dlr`, `wecare-voice-in-cdr`) is
   reported as DANGLING rather than hiding inside UNRESOLVED.

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
)

# Markers that only prove a handler can CALL OUT with a credential, never that it
# checks its own caller. Retired from the default set on 2026-09-21 after each one
# was traced to an outbound header or a CORS string:
#
#   appsecret_proof  the Graph query parameter Meta requires on outbound calls.
#                    On its own it classified POST /whatsapp/inbound as
#                    "handler authenticates" while that handler verified nothing.
#   api_key/API_KEY  in product-image-gen this is WIX_API_KEY, the outbound
#                    credential for calling Wix.
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
    # Short links are followed by customers who have no Cognito session. The
    # handler authenticates the /links management routes separately.
    "GET /r/{code}": "public short-link redirect; anonymous by definition",
    # The endpoint whose job is to validate a token cannot require a valid token.
    "POST /auth/validate": "token validation endpoint; authenticating it would be circular",
    "POST /auth/email-verification": "public email-ownership OTP door; it returns only a short-lived email-bound proof and performs no customer or contact write",
    "POST /blog/subscribe": "public subscription front door; caller has no session yet and must prove phone plus email OTP before any contact write",
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
}


def handler_sources() -> dict[str, str]:
    """Map candidate deployed function name -> concatenated source of its dir."""
    out: dict[str, str] = {}
    for handler in FUNCTIONS_ROOT.rglob("handler.py"):
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
        if key in EXPECTED_PUBLIC_ROUTES:
            expected_public.append((key, EXPECTED_PUBLIC_ROUTES[key]))
            continue

        target = (rt.get("Target") or "").split("/")[-1]
        uri = integrations.get(target, "")
        fn = ""
        m = re.search(r"function:([A-Za-z0-9\-_]+)", uri)
        if m:
            fn = m.group(1)

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
