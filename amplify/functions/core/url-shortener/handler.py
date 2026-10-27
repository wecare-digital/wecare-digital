"""
URL Shortener Lambda - WECARE.DIGITAL

Canonical base for links: wecare.digital/r  (since 2026-09-26)
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

import html
import json
import os
import re
import time
import logging
import uuid
import secrets
import string
import boto3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from botocore.exceptions import ClientError

from lambda_utils import short_link_lifecycle as lifecycle

SHORT_LINKS_TABLE = os.environ.get("SHORT_LINKS_TABLE", "stack-wecare-digital-ShortLinksTable")
LINK_CLICKS_TABLE = os.environ.get("LINK_CLICKS_TABLE", "stack-wecare-digital-LinkClicksTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# The base that short links are published under: the apex path `wecare.digital/r`,
# canonical since 2026-09-26.
#
# This is deliberately NOT called SHORT_DOMAIN, because that one name was doing three
# incompatible jobs in the retired link CDK: the ACM certificate subject, the API Gateway
# custom domain, and this public link base. The first two had to be a bare DNS label —
# `wecare.digital/r` is not a hostname and cannot be either — while this one must carry
# the path. Reusing one constant for both is what made "move the shortener to a path"
# look like it required giving up the subdomain.
#
# The subdomain was given up anyway, separately, on 2026-09-28, and those two constructs
# were removed before that undeployed CDK file was retired. SHORT_DOMAIN is still read as a
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


# ── Destination validation ──────────────────────────────────────────────────────
#
# A short link is an apex URL (wecare.digital/r/<code>) that sends a visitor somewhere else, and
# the deep-link page below is HTML served from that same apex origin. So a stored destination
# is not inert data: before 2026-10-27 `originalUrl`, `iosUrl` and `androidUrl` were stored as
# typed and then written raw into a `Location` header, an inline `<script>` string and an
# `href`. `iosUrl: "javascript:..."` ran script on wecare.digital, where the staff session lives.
#
# Validated at WRITE time so bad data is refused with a reason, and again at READ time so a row
# written before this check (or edited outside this API) still cannot redirect anywhere unsafe.

#: A short code is a path segment published on printed cards and QR codes: a plain URL-safe
#: alphabet only. Every live code matched this on 2026-10-27.
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Schemes that run or embed content in whatever opens them. Never a link destination.
_ACTIVE_SCHEMES = frozenset({"javascript", "vbscript", "data", "blob", "file", "about", "filesystem"})

_MAX_URL_LENGTH = 2048


def _clean_url(value):
    """The stripped string, or None when it is empty, oversized or carries control characters.

    Browsers drop tabs and newlines inside a scheme ("java\\tscript:"), so any control character
    is a refusal rather than something to normalise.
    """
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > _MAX_URL_LENGTH or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        return None
    return url


def web_destination(value):
    """`value` if it is an absolute https URL with a host, else None. The redirect target rule."""
    url = _clean_url(value)
    if url is None:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not parts.hostname:
        return None
    return url


def app_destination(value):
    """A deep-link target: an https URL, or an app's own scheme (myapp://, intent://).

    Never a script-bearing scheme and never plain http.
    """
    url = _clean_url(value)
    if url is None:
        return None
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    if not match:
        return None
    scheme = match.group(1).lower()
    if scheme in _ACTIVE_SCHEMES or scheme == "http":
        return None
    if scheme == "https":
        return web_destination(url)
    return url


def _bad_request(message):
    return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": message})}


def _validate_destinations(fields):
    """Return an error message for the first unsafe destination in `fields`, or None.

    `originalUrl` is checked only when present (update bodies are partial); empty app URLs are
    allowed because deep links are optional.
    """
    if "originalUrl" in fields and web_destination(fields.get("originalUrl")) is None:
        return "originalUrl must be an absolute https:// URL"
    for key in ("iosUrl", "androidUrl"):
        raw = fields.get(key)
        if raw not in (None, "") and app_destination(raw) is None:
            return f"{key} must be an https:// URL or an app link (javascript:, data: and http: are refused)"
    return None


def _actor(event):
    """Who is acting, from the verified session. Never from the request body."""
    auth = event.get("_auth") or {}
    return str(auth.get("email") or auth.get("username") or "system")


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

        # Redirect: GET /r/:code
        if "/r/" in path:
            code = path.split("/r/")[-1].strip("/")
            logger.info(f"Redirect via /r/ path: code={code}")
            return redirect(code, event)

        # CRUD: /links
        #
        # Authentication is applied here rather than at the top of the handler
        # because this function serves two different audiences on one Lambda:
        # the short-link redirects below are anonymous by definition - a customer
        # following wecare.digital/r/abc123 has no Cognito token - while link
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

            # Reads need any staff role; creating or repointing a public apex link needs Operator,
            # the same floor every other staff write in this account uses; retiring needs Admin.
            # Writes used to accept Viewer, so any staff account could mint a phishing link.
            if method == 'DELETE':
                required_role = 'Admin'
            elif method in ('POST', 'PUT'):
                required_role = 'Operator'
            else:
                required_role = 'Viewer'
            auth_failure = require_auth(event, required_role=required_role)
            if auth_failure is not None:
                return auth_failure

        if method == "POST" and "links" in path:
            return create_link(body, actor=_actor(event))
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

        # Catch-all: GET /{code}
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


def create_link(body, actor="system"):
    original_url = body.get("originalUrl")
    if not original_url:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "originalUrl required"})}
    problem = _validate_destinations(body)
    if problem:
        return _bad_request(problem)
    original_url = web_destination(original_url)

    requested_code = body.get("shortCode")
    if requested_code not in (None, ""):
        if not isinstance(requested_code, str) or not _CODE_RE.fullmatch(requested_code):
            return _bad_request("shortCode may use only letters, digits, '-' and '_' (1-64 characters)")
    short_code = requested_code or generate_code()
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    # Attachment: a link may optionally point at the record it was minted for. "general" is the
    # unattached default rather than an empty string, so a filter can tell a deliberately
    # general link from a legacy row written before attachments existed.
    related_type = lifecycle.canonical_related_type(body.get("relatedType"))
    related_id = str(body.get("relatedId") or "").strip()

    item = {
        "shortCode": short_code,
        "originalUrl": original_url,
        "shortUrl": f"https://{SHORT_LINK_BASE}/{short_code}",
        "title": body.get("title", original_url),
        "purpose": str(body.get("purpose") or "").strip(),
        "relatedType": related_type,
        "relatedId": related_id,
        "clicks": 0,
        "createdAt": now,
        # The verified session, not `body.userId`: a client-supplied creator made the audit trail
        # say whatever the caller wanted.
        "createdBy": actor,
        "deepLink": body.get("deepLink", False),
        "iosUrl": app_destination(body.get("iosUrl")) or "",
        "androidUrl": app_destination(body.get("androidUrl")) or "",
        "expiresAt": body.get("expiresAt", ""),
        # A new link is born ACTIVE. `active` is kept in sync with the lifecycle for the redirect
        # fast-path and any older reader that still consults the boolean.
        "lifecycleState": lifecycle.STATE_ACTIVE,
        "active": True,
    }

    # CREATE MEANS CREATE. An unconditional put let any POST that named an existing code replace
    # its destination - including codes printed on cards and the checkout's /r/wa - with no
    # trace of the old target. Repointing is PUT /links/{code}, which keeps the lifecycle rules.
    # A generated code that collides is simply drawn again.
    for attempt in range(5):
        try:
            links_table.put_item(Item=item, ConditionExpression="attribute_not_exists(shortCode)")
            break
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            if requested_code or attempt == 4:
                return {"statusCode": 409, "headers": HEADERS,
                        "body": json.dumps({"error": "That short code is already in use"})}
            item["shortCode"] = generate_code()
            item["shortUrl"] = f"https://{SHORT_LINK_BASE}/{item['shortCode']}"

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
    # Resolve a lifecycle state for every row, including legacy rows that carry only `active`,
    # so the dashboard can render ACTIVE/INACTIVE/RETIRED without re-deriving the rule client-side.
    for row in all_items:
        row["lifecycleState"] = lifecycle.state_from_record(row)
    # Sort by createdAt desc
    all_items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"links": all_items}, default=str)}


def get_link(code):
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Link not found"})}

    item["lifecycleState"] = lifecycle.state_from_record(item)

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
    """DELETE retires a link; it does not destroy it.

    A short link lives on printed cards, in sent messages, in QR codes and on invoices, so a
    hard row delete turns every one of those copies into a dead end AND discards the click
    history that is the audit trail. The safe, irreversible action a DELETE verb maps to is
    therefore RETIRED: the code stops resolving for good but the row and its clicks survive.
    An already-retired link is idempotent here.
    """
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Link not found"})}

    links_table.update_item(
        Key={"shortCode": code},
        UpdateExpression="SET lifecycleState = :state, active = :active",
        ExpressionAttributeValues={
            ":state": lifecycle.STATE_RETIRED,
            ":active": lifecycle.active_flag_for(lifecycle.STATE_RETIRED),
        },
    )
    _invalidate(code)
    updated = links_table.get_item(Key={"shortCode": code}).get("Item", {})
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"success": True, "retired": True, "link": updated}, default=str)}


def update_link(code, body):
    """Update an existing short link, including its lifecycle state.

    Lifecycle is the reason this is not a blind field copy. A link moves ACTIVE <-> INACTIVE
    freely, but RETIRED is terminal: once a code is spent it must never redirect again, so a
    transition out of RETIRED (or an attempt to reactivate a retired link via the legacy
    `active` flag) is refused here rather than silently re-opening a link that was deliberately
    killed. `active` and `lifecycleState` are always written together so the two never disagree.
    """
    item = links_table.get_item(Key={"shortCode": code}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Link not found"})}

    current_state = lifecycle.state_from_record(item)

    problem = _validate_destinations(body)
    if problem:
        return _bad_request(problem)

    # Resolve the requested lifecycle move. An explicit `lifecycleState` wins; otherwise a legacy
    # `active` boolean maps to ACTIVE/INACTIVE so existing callers keep working unchanged.
    target_state = None
    if "lifecycleState" in body:
        target_state = lifecycle.canonical_state(body["lifecycleState"])
    elif "active" in body:
        target_state = lifecycle.STATE_ACTIVE if body["active"] else lifecycle.STATE_INACTIVE

    if target_state is not None and not lifecycle.can_transition(current_state, target_state):
        return {
            "statusCode": 409,
            "headers": HEADERS,
            "body": json.dumps(
                {"error": f"Illegal lifecycle transition {current_state} -> {target_state}"}
            ),
        }

    update_expr = []
    expr_values = {}

    # Content and attachment fields are editable in any non-retired state. A RETIRED link is
    # frozen: its destination and metadata are audit, so only a repeat retire (a no-op) is let
    # through above and nothing below rewrites it.
    editable = ["originalUrl", "title", "purpose", "deepLink", "iosUrl", "androidUrl", "expiresAt"]
    if current_state != lifecycle.STATE_RETIRED:
        for field in editable:
            if field in body:
                value = body[field]
                # Store the normalised destination that passed _validate_destinations above.
                if field == "originalUrl":
                    value = web_destination(value)
                elif field in ("iosUrl", "androidUrl"):
                    value = app_destination(value) or ""
                update_expr.append(f"{field} = :{field}")
                expr_values[f":{field}"] = value
        if "relatedType" in body:
            update_expr.append("relatedType = :relatedType")
            expr_values[":relatedType"] = lifecycle.canonical_related_type(body["relatedType"])
        if "relatedId" in body:
            update_expr.append("relatedId = :relatedId")
            expr_values[":relatedId"] = str(body["relatedId"] or "").strip()

    if target_state is not None:
        update_expr.append("lifecycleState = :lifecycleState")
        expr_values[":lifecycleState"] = target_state
        update_expr.append("active = :active")
        expr_values[":active"] = lifecycle.active_flag_for(target_state)

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
    # Only an ACTIVE link resolves to its destination. INACTIVE and RETIRED both land on the
    # safe fallback — asked as one lifecycle question rather than reading `active`, so a link
    # taken down by lifecycle still stops even if an older `active` flag drifted out of sync.
    if not item or not lifecycle.is_resolvable(item):
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

    # Re-checked on the way out: a row stored before write-time validation existed, or edited
    # outside this API, must still not send a visitor to a non-https destination.
    destination = web_destination(item.get("originalUrl"))
    if destination is None:
        logging.getLogger(__name__).warning(json.dumps({"event": "short_link_unsafe_destination", "code": code}))
        return {
            "statusCode": 302,
            "headers": {**HEADERS, "Location": FALLBACK_URL},
            "body": "",
        }

    # Deep link routing
    if item.get("deepLink"):
        if platform == "ios" and item.get("iosUrl"):
            # Return HTML that tries app scheme first, falls back to web
            return deep_link_html(item["iosUrl"], destination, "ios")
        elif platform == "android" and item.get("androidUrl"):
            return deep_link_html(item["androidUrl"], destination, "android")

    # Standard redirect
    return {
        "statusCode": 302,
        "headers": {**HEADERS, "Location": destination},
        "body": "",
    }


def _js_string(value):
    """A JavaScript string literal that cannot end the <script> element it sits in.

    json.dumps gives a valid JS string (and, with ensure_ascii, escapes U+2028/U+2029); `<`, `>`
    and `&` are escaped as well so the value cannot spell `</script>` or an HTML comment.
    """
    return (json.dumps(value)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def deep_link_html(app_url, fallback_url, platform):
    """Return HTML page that attempts app deep link, falls back to web.

    Both values are validated again here and encoded for the context they land in: a JS string
    literal for the script, an escaped attribute for the href. An unusable app URL degrades to a
    plain redirect rather than a page.
    """
    web_url = web_destination(fallback_url) or FALLBACK_URL
    app = app_destination(app_url)
    if app is None:
        return {"statusCode": 302, "headers": {**HEADERS, "Location": web_url}, "body": ""}
    page = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Redirecting...</title>
<script>
  var appUrl = {_js_string(app)};
  var webUrl = {_js_string(web_url)};
  var start = Date.now();
  window.location.href = appUrl;
  setTimeout(function() {{
    if (Date.now() - start < 2000) window.location.href = webUrl;
  }}, 1500);
</script>
</head>
<body style="font-family:sans-serif;text-align:center;padding:60px 20px;color:#1a3a2a">
<p>Redirecting...</p>
<p style="font-size:13px;color:#6b7280;margin-top:12px">
  <a href="{html.escape(web_url, quote=True)}" style="color:#1a3a2a">Click here</a> if not redirected
</p>
</body></html>"""
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            # Nothing on this page needs to load or send anything: one inline script that
            # navigates, inline styles, and a link.
            "Content-Security-Policy": ("default-src 'none'; script-src 'unsafe-inline'; "
                                        "style-src 'unsafe-inline'; base-uri 'none'; "
                                        "form-action 'none'; frame-ancestors 'none'"),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
        "body": page,
    }