"""
URL Shortener Lambda - WECARE.DIGITAL

Canonical base for links: wecare.digital/r  (since 2026-09-26)
Retired:                  r.wecare.digital  (2026-09-28)

This function is reached on the apex path only. Amplify proxies `/r/<*>` to the
shared API, and the handler accepts both `/r/{code}` and a bare `/{code}`.

The subdomain used to be described here as a permanent alias, on the reasoning
that short links already sent to customers name it and a shortener must honour
the codes it issued. That reasoning was sound and it was overtaken: the owner
deleted the Route 53 record on 2026-09-28, so the host no longer resolves and
those already-delivered links are dead. Nothing in this function can bring them
back — the redirect only runs once DNS has already found us. Recorded so the next
reader does not restore the record on the strength of a comment.

Creates short links with optional deep link support for iOS/Android.
Tracks clicks with device/geo info.

Tables:
- ShortLinksTable: shortCode (PK)
- LinkClicksTable: shortCode (PK), clickedAt (SK)
"""

import json
import os
import time
import logging
import uuid
import secrets
import string
import boto3
from datetime import datetime, timezone

SHORT_LINKS_TABLE = os.environ.get("SHORT_LINKS_TABLE", "stack-wecare-digital-ShortLinksTable")
LINK_CLICKS_TABLE = os.environ.get("LINK_CLICKS_TABLE", "stack-wecare-digital-LinkClicksTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# The base that short links are published under: the apex path `wecare.digital/r`,
# canonical since 2026-09-26.
#
# This is deliberately NOT called SHORT_DOMAIN, because that one name was doing three
# incompatible jobs in link-resources.ts: the ACM certificate subject, the API Gateway
# custom domain, and this public link base. The first two had to be a bare DNS label —
# `wecare.digital/r` is not a hostname and cannot be either — while this one must carry
# the path. Reusing one constant for both is what made "move the shortener to a path"
# look like it required giving up the subdomain.
#
# The subdomain was given up anyway, separately, on 2026-09-28, and those two constructs
# have since been removed from link-resources.ts. SHORT_DOMAIN is still read as a
# fallback so an environment that has not been updated yet keeps working rather than
# silently minting on a bare default — but note that a stale SHORT_DOMAIN would now mint
# links on a host that does not resolve, so the ordering below matters: SHORT_LINK_BASE
# must win.
SHORT_LINK_BASE = (
    os.environ.get("SHORT_LINK_BASE")
    or os.environ.get("SHORT_DOMAIN")
    or "wecare.digital/r"
).strip().strip("/")

# DynamoDB resources are built LAZILY, on first use, not at import.
#
# This module used to do `dynamodb = boto3.resource("dynamodb")` and bind both tables
# at module scope. boto3 resolves a region when the resource is CONSTRUCTED, so merely
# importing this file reached for AWS configuration — and with no region configured it
# raised `botocore.exceptions.NoRegionError: You must specify a region`.
#
# That is invisible on a developer machine, because `~/.aws/config` supplies a default
# region, and fatal in CI, which has no AWS config at all. It took out all 8 tests in
# tests/test_url_shortener_base.py — none of which touch DynamoDB; they only import the
# module to read SHORT_LINK_BASE — and through them the whole `Route auth` workflow.
# Measured 2026-09-27: 20 of the 28 failing runs in the last 120 were this one cause.
#
# Region is also explicit now rather than inherited, so the Lambda does not depend on
# AWS_REGION being present in its environment either.
_ddb = None


def _resource():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=REGION)
    return _ddb


class _LazyTable:
    """Defers `.Table(name)` until an attribute is actually touched.

    Keeps the `links_table.get_item(...)` call shape used throughout this file, so the
    fix is one indirection rather than rewriting every call site — which is what would
    turn a CI fix into a risky change to a live redirect path.
    """

    __slots__ = ("_name", "_table")

    def __init__(self, name):
        self._name = name
        self._table = None

    def __getattr__(self, attr):
        if self._table is None:
            self._table = _resource().Table(self._name)
        return getattr(self._table, attr)


links_table = _LazyTable(SHORT_LINKS_TABLE)
clicks_table = _LazyTable(LINK_CLICKS_TABLE)

# ── In-memory link cache (per warm container) for fast repeat redirects ──
# Content-addressed by shortCode; bounded by TTL so edits/deactivations
# propagate within LINK_CACHE_TTL seconds. Explicitly invalidated on write.
_link_cache = {}
_CACHE_TTL = int(os.environ.get("LINK_CACHE_TTL", "60"))


def _get_link_cached(code):
    now = time.time()
    hit = _link_cache.get(code)
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    _link_cache[code] = (item, now)
    return item


def _invalidate(code):
    _link_cache.pop(code, None)

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


# Where an unknown, expired or malformed short code lands. Four call sites use it.
#
# This pointed at `[retired public path]` until 2026-09-27, which had been a
# 404 since commit 6bc44a35 removed the in-repo stub on 2026-09-24 and nothing replaced
# it. Measured live before the change: /r/<unknown> -> 302 -> [retired public path] -> 301 ->
# [retired public path]/ -> 404. So every mistyped or expired PRINTED short link ended on an error
# page, which is the worst possible destination for the one visitor who already got
# something slightly wrong.
#
# `/contact/` is a real page and TERMINAL - 200 with zero redirect hops, verified with the
# trailing slash, because `/contact` without it costs a 301. Keep the slash.
FALLBACK_URL = "https://wecare.digital/contact/"


def handler(event, context):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    method = event.get("httpMethod", event.get("requestContext", {}).get("http", {}).get("method", "GET"))
    raw_path = event.get("path", event.get("rawPath", ""))
    
    # Strip stage prefix (e.g., /prod/wa -> /wa) for custom domain requests.
    #
    # This used to be a hand-rolled fourth copy of the rule. It was the most
    # complete one - it alone handled a path of exactly "/{stage}", which for a
    # short-link service is the difference between the root and a lookup for a
    # code named after the stage - so that case was folded into the shared helper
    # rather than lost. See lambda_utils/http_path.py for the two incidents this
    # rule exists to prevent.
    from lambda_utils.http_path import normalize_path
    path = normalize_path(event)
    stage = event.get("requestContext", {}).get("stage", "")
    
    logger.info(f"URL Shortener: method={method} raw_path={raw_path} path={path} stage={stage}")
    try:
        body = json.loads(event.get("body", "{}") or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    try:
        if method == "OPTIONS":
            return {"statusCode": 200, "headers": HEADERS, "body": ""}

        # Redirect: GET /r/:code or GET /{code} (from r.wecare.digital)
        if "/r/" in path:
            code = path.split("/r/")[-1].strip("/")
            logger.info(f"Redirect via /r/ path: code={code}")
            return redirect(code, event)

        # CRUD: /links
        #
        # Authentication is applied here rather than at the top of the handler
        # because this function serves two different audiences on one Lambda:
        # the short-link redirects below are anonymous by definition - a customer
        # following r.wecare.digital/abc123 has no Cognito token - while link
        # management is dashboard-only.
        #
        # Until 2026-09-21 none of it was authenticated. Anyone could enumerate
        # every short link, repoint an existing one, or mint new ones on a
        # wecare.digital domain, which is a ready-made phishing primitive.
        # require_auth skips internal Lambda invokes and OPTIONS, so callers that
        # are not API Gateway requests are unaffected.
        if "links" in path and method in ("POST", "GET", "DELETE", "PUT"):
            # Imported here, not at module scope, so the redirect paths above
            # never pay to load the middleware or construct its Cognito client.
            # A short-link redirect is latency-sensitive and anonymous; link
            # management is neither.
            from lambda_utils.middleware import require_auth

            auth_failure = require_auth(event)
            if auth_failure is not None:
                return auth_failure

        if method == "POST" and "links" in path:
            return create_link(body)
        if method == "GET" and "links" in path:
            code = path.split("/links/")[-1].strip("/") if "/links/" in path else None
            if code:
                return get_link(code)
            return list_links()
        if method == "DELETE" and "links" in path:
            code = path.split("/links/")[-1].strip("/")
            return delete_link(code)
        if method == "PUT" and "links" in path:
            code = path.split("/links/")[-1].strip("/")
            if code:
                return update_link(code, body)

        # Catch-all: GET /{code} — treat as redirect (for r.wecare.digital/abc123)
        if method == "GET" and path and path != "/":
            code = path.strip("/")
            logger.info(f"Catch-all redirect: code={code}")
            if code and "." not in code and "/" not in code:
                return redirect(code, event)

        # 404 → redirect to customer-service
        logger.info(f"No route matched, falling back")
        return {
            "statusCode": 302,
            "headers": {**HEADERS, "Location": FALLBACK_URL},
            "body": "",
        }

    except Exception as e:
        # 500 → redirect to customer-service
        logger.error(f"Handler exception: {e}", exc_info=True)
        return {
            "statusCode": 302,
            "headers": {**HEADERS, "Location": FALLBACK_URL},
            "body": "",
        }


def generate_code(length=6):
    # secrets (not random) so codes stay unique under Lambda SnapStart, where a
    # restored snapshot would otherwise share the random module's PRNG state.
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def create_link(body):
    original_url = body.get("originalUrl")
    if not original_url:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "originalUrl required"})}

    short_code = body.get("shortCode", generate_code())
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    item = {
        "shortCode": short_code,
        "originalUrl": original_url,
        "shortUrl": f"https://{SHORT_LINK_BASE}/{short_code}",
        "title": body.get("title", original_url),
        "clicks": 0,
        "createdAt": now,
        "createdBy": body.get("userId", "admin"),
        "deepLink": body.get("deepLink", False),
        "iosUrl": body.get("iosUrl", ""),
        "androidUrl": body.get("androidUrl", ""),
        "expiresAt": body.get("expiresAt", ""),
        "active": True,
    }

    links_table.put_item(Item=item)

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"success": True, "link": item})}


def list_links():
    all_items = []
    scan_kwargs = {}
    while True:
        result = links_table.scan(**scan_kwargs)
        all_items.extend(result.get("Items", []))
        if 'LastEvaluatedKey' not in result:
            break
        scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
    # Sort by createdAt desc
    all_items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"links": all_items}, default=str)}


def get_link(code):
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Link not found"})}

    # Get click analytics
    clicks_result = clicks_table.query(
        KeyConditionExpression="shortCode = :sc",
        ExpressionAttributeValues={":sc": code},
        ScanIndexForward=False,
        Limit=50,
    )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"link": item, "recentClicks": clicks_result.get("Items", [])}, default=str),
    }


def delete_link(code):
    links_table.delete_item(Key={"shortCode": code})
    _invalidate(code)
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"success": True})}


def update_link(code, body):
    """Update an existing short link."""
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Link not found"})}

    update_expr = []
    expr_values = {}
    for field in ["originalUrl", "title", "deepLink", "iosUrl", "androidUrl", "expiresAt", "active"]:
        if field in body:
            update_expr.append(f"{field} = :{field}")
            expr_values[f":{field}"] = body[field]

    if not update_expr:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "No fields to update"})}

    links_table.update_item(
        Key={"shortCode": code},
        UpdateExpression="SET " + ", ".join(update_expr),
        ExpressionAttributeValues=expr_values,
    )

    _invalidate(code)
    updated = links_table.get_item(Key={"shortCode": code}).get("Item", {})
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"success": True, "link": updated}, default=str)}


def redirect(code, event):
    """Redirect to original URL, track click, handle deep links."""
    item = _get_link_cached(code)
    if not item or not item.get("active", True):
        return {
            "statusCode": 302,
            "headers": {**HEADERS, "Location": FALLBACK_URL},
            "body": "",
        }

    # Check expiry
    expires = item.get("expiresAt")
    if expires and expires < datetime.now(timezone.utc).replace(tzinfo=None).isoformat():
        return {
            "statusCode": 302,
            "headers": {**HEADERS, "Location": FALLBACK_URL},
            "body": "",
        }

    # Track click
    user_agent = ""
    source_ip = ""
    try:
        headers_map = event.get("headers", {})
        user_agent = headers_map.get("user-agent", headers_map.get("User-Agent", ""))
        source_ip = (
            event.get("requestContext", {}).get("http", {}).get("sourceIp", "")
            or headers_map.get("x-forwarded-for", "").split(",")[0].strip()
        )
    except Exception as e:
        logging.getLogger(__name__).debug(f'Header extraction failed: {e}')

    # Detect platform from user agent
    ua_lower = user_agent.lower()
    platform = "web"
    if "iphone" in ua_lower or "ipad" in ua_lower:
        platform = "ios"
    elif "android" in ua_lower:
        platform = "android"

    # Click tracking is best-effort — it must NEVER block or break the redirect.
    try:
        clicks_table.put_item(
            Item={
                "shortCode": code,
                "clickedAt": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "platform": platform,
                "userAgent": user_agent[:500],
                "sourceIp": source_ip,
            }
        )
        links_table.update_item(
            Key={"shortCode": code},
            UpdateExpression="SET clicks = if_not_exists(clicks, :zero) + :inc",
            ExpressionAttributeValues={":inc": 1, ":zero": 0},
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"click tracking failed for {code}: {e}")

    # Deep link routing
    if item.get("deepLink"):
        if platform == "ios" and item.get("iosUrl"):
            # Return HTML that tries app scheme first, falls back to web
            return deep_link_html(item["iosUrl"], item["originalUrl"], "ios")
        elif platform == "android" and item.get("androidUrl"):
            return deep_link_html(item["androidUrl"], item["originalUrl"], "android")

    # Standard redirect
    return {
        "statusCode": 302,
        "headers": {**HEADERS, "Location": item["originalUrl"]},
        "body": "",
    }


def deep_link_html(app_url, fallback_url, platform):
    """Return HTML page that attempts app deep link, falls back to web."""
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redirecting...</title>
<script>
  var appUrl = "{app_url}";
  var webUrl = "{fallback_url}";
  var start = Date.now();
  window.location.href = appUrl;
  setTimeout(function() {{
    if (Date.now() - start < 2000) window.location.href = webUrl;
  }}, 1500);
</script>
</head>
<body style="font-family:sans-serif;text-align:center;padding:60px 20px;color:#1a3a2a">
<p>Redirecting to Stack CRM...</p>
<p style="font-size:13px;color:#6b7280;margin-top:12px">
  <a href="{fallback_url}" style="color:#1a3a2a">Click here</a> if not redirected
</p>
</body></html>"""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html", "Access-Control-Allow-Origin": "*"},
        "body": html,
    }