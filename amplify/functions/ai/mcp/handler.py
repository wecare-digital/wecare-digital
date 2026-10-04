"""A read-only MCP server for the public wecare.digital content, at https://wecare.digital/mcp

WHAT THIS IS FOR
----------------
An AI assistant that wants to answer a question about this business has two options
today. It can crawl the HTML and hope its extractor keeps the meaning, or it can read
`/llms.txt` and hope its vendor implemented that convention. Neither is a query
interface: both hand over a fixed blob and leave the model to guess.

MCP is the query interface. An agent connects once and can then ask a specific
question - "which page covers dispute resolution", "find posts about visas" - and get
a structured answer scoped to what is actually published. That is a materially better
signal than an extractor's best effort, and unlike llms.txt it is a protocol with
clients that exist rather than a file crawlers are free to ignore.

Read `docs/ai-discovery-surface.md` for how this sits alongside `/llms.txt`, and for the
honest limits of each.

TRANSPORT: Streamable HTTP, stateless, JSON response mode
---------------------------------------------------------
Implemented against the 2025-11-25 spec (`basic/transports`), and the shape is dictated
by where it runs. API Gateway HTTP API **buffers** its Lambda integration - there is no
chunked transfer and no Server-Sent Events - so the SSE arm of the transport is not
available here. That is not a compromise. The spec offers two equal alternatives for a
JSON-RPC *request*:

    the server MUST either return Content-Type: text/event-stream, to initiate an SSE
    stream, or Content-Type: application/json, to return one JSON object

and for the GET arm it explicitly blesses declining:

    The server MUST either return Content-Type: text/event-stream in response to this
    HTTP GET, or else return HTTP 405 Method Not Allowed, indicating that the server
    does not offer an SSE stream at this endpoint.

So: POST answers with a single JSON object, GET answers 405, DELETE answers 405. A
compliant client handles all three - the spec says "The client MUST support both these
cases" about the POST pair. Nothing is degraded, because this server has no long-running
tool and never needs to push an unsolicited message, which is the only thing SSE buys.

Stateless follows from the same place. Session IDs exist so a server can keep state
across requests; `MCP-Session-Id` is a MAY, and a Lambda behind an alias has no sticky
sandbox to keep state in. Every request carries everything it needs. A client that
sends a session id gets a normal answer rather than a 404, because we never issued one.

WHAT IT DELIBERATELY CANNOT DO
------------------------------
Every tool here is a read of already-public content. This endpoint cannot send a
WhatsApp message, create or amend a request, take or refund a payment, mutate a payment
configuration, read a contact record, or touch anything under /workspace/. That is not
enforced by a check somewhere else - the capability is simply absent from this file, and
`test_mcp_server.py` asserts the tool list against a frozen allowlist so it stays that
way. An unauthenticated public route is the wrong place to put a side effect.

THE THREAT MODEL IS COST, NOT DATA
----------------------------------
`core/site-language/handler.py` already learned this on the one other anonymous route on
the site, and its comment is worth repeating: the exposure on a public endpoint that
calls a billed API is not disclosure, it is spend. 15 rps against a per-character
translation API works out near $32,000/hour, and caching cannot help because attacker
text never repeats a cache key.

Three things follow, and they are the reason this file looks the way it does:

  * The blog corpus is fetched once per warm sandbox and memoised for
    `MCP_BLOG_TTL_SECONDS`. `/api/seo-tools/blog-public` returns the entire 889-post
    corpus as 924 kB in about 5 s; calling it per request would make this endpoint a
    free amplifier for the hottest function in the fleet.
  * `ask_site`, the one tool that would reach Bedrock, is **off unless
    `MCP_ASK_ENABLED=true`**, and while it is off it is absent from `tools/list`
    entirely rather than present-and-failing. An agent should see a smaller honest
    toolset, not a tool that errors.
  * The only rate limit in front of this is the API Gateway stage throttle
    (100 rps / 200 burst, shared with every other route). That is a real limit but it is
    a shared one, so it is recorded here rather than assumed: if `ask_site` is ever
    enabled, it needs its own cap before it is turned on, not after.

ORIGIN VALIDATION
-----------------
The spec requires it, for DNS rebinding:

    Servers MUST validate the Origin header on all incoming connections... If the Origin
    header is present and invalid, servers MUST respond with HTTP 403 Forbidden.

"Present and invalid" is the whole of the rule, and the distinction matters here more
than it does for a local server. A non-browser MCP client - a desktop host, a hosted
agent, curl - sends **no** Origin at all, and that is the primary way this endpoint will
be used. So an absent Origin is allowed and a present-but-unrecognised one is refused.
Defaulting closed rather than open is a judgement call on a read-only endpoint where
rebinding wins an attacker nothing they could not get from the public HTML; it is closed
anyway because the rule is a MUST and `MCP_ALLOWED_ORIGINS` makes widening it a
deliberate, recorded act rather than a default.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ── Protocol ────────────────────────────────────────────────────────────────────
# Newest first: PROTOCOL_VERSIONS[0] is what `initialize` offers when the client asks
# for something we do not recognise. The spec's rule for a missing MCP-Protocol-Version
# header on a *subsequent* request is explicit, and it is not "use the newest":
#
#     if the server does not receive an MCP-Protocol-Version header, and has no other
#     way to identify the version ... the server SHOULD assume protocol version
#     2025-03-26.
#
# Hence DEFAULT_PROTOCOL_VERSION differs from PROTOCOL_VERSIONS[0] on purpose. Do not
# "tidy" them into one constant.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]
DEFAULT_PROTOCOL_VERSION = "2025-03-26"

SERVER_NAME = "wecare-digital-public"
SERVER_TITLE = "WECARE.DIGITAL public content"
SERVER_VERSION = "1.0.0"

# JSON-RPC 2.0 error codes (§5.1). -32000..-32099 is the implementation-defined band.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SITE_URL = os.environ.get("SITE_URL", "https://wecare.digital").rstrip("/")

# Straight to execute-api, NOT back through the apex. The apex path would be
# wecare.digital/api/... -> CloudFront -> this same API, so a request from inside the
# API would leave AWS, traverse the CDN and come back, adding latency and a second
# failure domain to fetch our own content.
BLOG_API = os.environ.get(
    "MCP_BLOG_API",
    "https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/seo-tools/blog-public",
)
BLOG_TTL_SECONDS = int(os.environ.get("MCP_BLOG_TTL_SECONDS", "900"))
BLOG_TIMEOUT_SECONDS = float(os.environ.get("MCP_BLOG_TIMEOUT_SECONDS", "12"))

MAX_RESULTS = 50
DEFAULT_RESULTS = 10

# In the deployed zip the catalogue sits beside this file; `config/public-pages.json` is
# the single source and the packager copies it in. MCP_CATALOG_PATH exists so the test
# suite and a local run can point at that source directly instead of needing a build step
# or a checked-in duplicate - a second copy in the tree is exactly the drift this file's
# own guard test is meant to prevent.
_CATALOG_PATH = os.environ.get(
    "MCP_CATALOG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "public-pages.json"),
)


# ── Catalogue ───────────────────────────────────────────────────────────────────

_catalog_cache: Optional[Dict[str, Any]] = None


def _catalog() -> Dict[str, Any]:
    """The public page catalogue, read from the zip once per sandbox.

    Lazy rather than module-scope so an unreadable or malformed file surfaces as a
    JSON-RPC error on one call instead of an import-time crash that takes out every
    request including `initialize`.
    """
    global _catalog_cache
    if _catalog_cache is None:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as fh:
            _catalog_cache = json.load(fh)
    return _catalog_cache


def _pages() -> List[Dict[str, Any]]:
    return list(_catalog().get("pages") or [])


def _page_url(path: str) -> str:
    """Canonical URL for a catalogue path.

    `trailingSlash: true` in next.config.js, so every route except the root carries the
    slash. Emitting the slashless form would hand an agent a URL that 301s, and a
    citation that redirects is a citation that can rot.
    """
    if path == "/":
        return f"{SITE_URL}/"
    return f"{SITE_URL}{path}/"


# ── Blog corpus ─────────────────────────────────────────────────────────────────

_blog_cache: Tuple[float, List[Dict[str, Any]]] = (0.0, [])

# The fields an agent can use. The upstream response carries jsonLd, keywords, hashtags,
# robots, focusKeyword, seoTitle, metaDescription and id as well - roughly half the 924 kB
# - none of which help a model answer a question, and all of which would be re-serialised
# into every tool result.
_BLOG_FIELDS = ("slug", "title", "excerpt", "category", "publishedDate", "authorName")


def _fetch_blog() -> List[Dict[str, Any]]:
    req = urllib.request.Request(BLOG_API, headers={
        "Accept": "application/json",
        # Points at this endpoint, not at a page describing it. It named /llm/ until
        # 2026-09-30, when that page was retired; a User-Agent URL that 301s is a URL
        # someone reading an access log has to follow twice to learn who called them.
        "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION} (+{SITE_URL}/mcp)",
    })
    with urllib.request.urlopen(req, timeout=BLOG_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok") or not isinstance(payload.get("posts"), list):
        raise ValueError("blog-public returned an unexpected shape")
    out: List[Dict[str, Any]] = []
    for post in payload["posts"]:
        if not isinstance(post, dict):
            continue
        slug = str(post.get("slug") or "").strip().strip("/")
        if not slug:
            continue
        trimmed = {k: post.get(k) for k in _BLOG_FIELDS if post.get(k)}
        trimmed["slug"] = slug
        trimmed["url"] = f"{SITE_URL}/post/{slug}/"
        out.append(trimmed)
    return out


def _blog() -> List[Dict[str, Any]]:
    """The published corpus, memoised per warm sandbox.

    AN EXPIRED CACHE IS BETTER THAN NO CACHE when the upstream is down. If the refetch
    fails and we already hold posts, the stale copy is served: this is a public blog
    index, so a 15-minute-old list is a non-event, whereas returning nothing would make
    `search_blog` look like the blog is empty. `generate-sitemap.js` refuses to write a
    zero-post sitemap for the same reason - a transient fetch failure must not be
    reported as an absence of content.
    """
    global _blog_cache
    fetched_at, posts = _blog_cache
    if posts and (time.time() - fetched_at) < BLOG_TTL_SECONDS:
        return posts
    try:
        posts = _fetch_blog()
        _blog_cache = (time.time(), posts)
        return posts
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        # type(exc).__name__ only. The URL is ours and carries no credential, but the
        # secret-handling rule is that an exception's text is logged only when our own
        # code built it from known-safe parts, and urllib's is not ours.
        logger.warning(json.dumps({
            "event": "mcp_blog_fetch_failed",
            "errorType": type(exc).__name__,
            "servingStaleCount": len(posts),
        }))
        if posts:
            return posts
        raise RuntimeError("The blog index is temporarily unavailable") from exc


# ── Search ──────────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]+")


def _terms(query: str) -> List[str]:
    return _WORD.findall(str(query or "").lower())


def _score(terms: Iterable[str], *fields: Any) -> int:
    """Count term hits, weighting the first field highest.

    A title match is a stronger signal than a body match, so fields are passed
    most-significant first and weighted by position. Deliberately not TF-IDF: the corpus
    is 889 short records and the caller is a language model that will re-read the
    results anyway, so ranking only has to be roughly right.
    """
    total = 0
    for index, field in enumerate(fields):
        if not field:
            continue
        text = (" ".join(field) if isinstance(field, (list, tuple)) else str(field)).lower()
        weight = max(1, len(fields) - index)
        for term in terms:
            if term in text:
                total += weight
    return total


def _limit(params: Dict[str, Any], default: int = DEFAULT_RESULTS) -> int:
    try:
        value = int(params.get("limit", default))
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_RESULTS, value))


# ── Tools ───────────────────────────────────────────────────────────────────────

def _tool_search_pages(params: Dict[str, Any]) -> Dict[str, Any]:
    terms = _terms(params.get("query"))
    if not terms:
        raise ValueError("query is required")
    scored = []
    for page in _pages():
        score = _score(terms, page.get("name"), page.get("description"), page.get("path"))
        if score:
            scored.append((score, page))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("path", "")))
    results = [{
        "path": p.get("path"),
        "url": _page_url(str(p.get("path") or "/")),
        "name": p.get("name"),
        "description": p.get("description"),
        "group": p.get("group"),
    } for _, p in scored[:_limit(params)]]
    return {"query": params.get("query"), "count": len(results), "pages": results}


def _tool_list_pages(params: Dict[str, Any]) -> Dict[str, Any]:
    group = str(params.get("group") or "").strip().lower()
    groups = {g["id"]: g for g in _catalog().get("groups") or []}
    if group and group not in groups:
        raise ValueError(f"unknown group '{group}'; valid groups: {', '.join(sorted(groups))}")
    pages = [p for p in _pages() if not group or p.get("group") == group]
    return {
        "count": len(pages),
        "groups": [{"id": g["id"], "title": g.get("title"), "note": g.get("note")}
                   for g in (_catalog().get("groups") or [])
                   if not group or g["id"] == group],
        "pages": [{
            "path": p.get("path"),
            "url": _page_url(str(p.get("path") or "/")),
            "name": p.get("name"),
            "description": p.get("description"),
            "group": p.get("group"),
        } for p in pages],
    }


def _tool_search_blog(params: Dict[str, Any]) -> Dict[str, Any]:
    terms = _terms(params.get("query"))
    if not terms:
        raise ValueError("query is required")
    posts = _blog()
    scored = []
    for post in posts:
        score = _score(terms, post.get("title"), post.get("excerpt"), post.get("category"))
        if score:
            scored.append((score, post))
    # Two passes, relying on sort stability, because the two keys want opposite
    # directions: relevance descending, then newest first within equal relevance. A
    # single tuple key cannot express that without inverting a date string.
    scored.sort(key=lambda pair: str(pair[1].get("publishedDate") or ""), reverse=True)
    scored.sort(key=lambda pair: pair[0], reverse=True)
    limit = _limit(params)
    return {
        "query": params.get("query"),
        "corpusSize": len(posts),
        "matched": len(scored),
        "count": min(len(scored), limit),
        "posts": [post for _, post in scored[:limit]],
    }


def _tool_get_blog_post(params: Dict[str, Any]) -> Dict[str, Any]:
    slug = str(params.get("slug") or "").strip().strip("/")
    if not slug:
        raise ValueError("slug is required")
    for post in _blog():
        if post.get("slug") == slug:
            return {"post": post}
    raise LookupError(f"No published post with slug '{slug}'")


def _tool_get_site_summary(_params: Dict[str, Any]) -> Dict[str, Any]:
    catalog = _catalog()
    return {
        "site": catalog.get("site"),
        "aiSurface": catalog.get("ai_surface"),
        "usageTerms": catalog.get("usage_terms"),
        "howToReachUs": {
            "note": "Requests are handled through the customer-service pages rather than by email.",
            "pages": [{
                "path": p.get("path"),
                "url": _page_url(str(p.get("path") or "/")),
                "name": p.get("name"),
                "description": p.get("description"),
            } for p in _pages() if p.get("group") in ("customerservice", "start")],
        },
        "notCoveredHere": [
            "Any authenticated surface under /workspace/ - staff operations.",
            "Contact records, message history, orders and payments.",
            "Anything this endpoint could change. It is read-only by construction.",
        ],
    }


TOOLS: Dict[str, Dict[str, Any]] = {
    "search_pages": {
        "title": "Search public pages",
        "description": ("Find the public pages on wecare.digital whose name or description match a "
                        "query. Use this first to locate the right page for a topic, then cite its url."),
        "handler": _tool_search_pages,
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for, e.g. 'dispute resolution'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": DEFAULT_RESULTS},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "list_pages": {
        "title": "List public pages",
        "description": ("The full catalogue of public pages, grouped. Cheaper and more complete than "
                        "crawling. Pass a group id to narrow it."),
        "handler": _tool_list_pages,
        "schema": {
            "type": "object",
            "properties": {
                "group": {"type": "string",
                          "description": "One of: start, platform, services, customerservice, legal."},
            },
            "additionalProperties": False,
        },
    },
    "search_blog": {
        "title": "Search published articles",
        "description": ("Search the published blog corpus by title, excerpt and category. Returns slugs "
                        "and canonical urls; fetch the page itself for the full text."),
        "handler": _tool_search_blog,
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": DEFAULT_RESULTS},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_blog_post": {
        "title": "Get one article by slug",
        "description": "Metadata and canonical url for a single published post, by its slug.",
        "handler": _tool_get_blog_post,
        "schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
            "additionalProperties": False,
        },
    },
    "get_site_summary": {
        "title": "What this business is",
        "description": ("Identity, what the business does, how to start a request, and the terms for "
                        "citing this content. Read this before answering a question about the company."),
        "handler": _tool_get_site_summary,
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

# THE ALLOWLIST, FROZEN, AND IT IS THE POINT OF THIS MODULE.
#
# `tools/list` is derived from TOOLS, so without this a tool would become publicly
# callable the moment someone added a dict entry - no review step, no test failure. This
# is asserted for exact equality in tests/test_mcp_server.py, which means adding a tool
# is a deliberate edit in two places and a tool with a side effect cannot arrive by
# accident on an unauthenticated endpoint.
#
# EVERY NAME HERE MUST BE A READ. If you are about to add one that writes, that is the
# signal to put it behind require_auth on a different route instead.
READ_ONLY_TOOLS = frozenset({
    "search_pages", "list_pages", "search_blog", "get_blog_post", "get_site_summary",
})


def _enabled_tools() -> Dict[str, Dict[str, Any]]:
    """The tools this request may call, intersected with the frozen allowlist.

    Indirection rather than using TOOLS directly, for two reasons. It is the single
    choke point where the allowlist is enforced at call time as well as at list time -
    `tools/call` and `tools/list` both go through here, so they cannot disagree. And it
    is where a future environment gate belongs: if a tool that costs money per call is
    ever added (a Bedrock-backed answer tool is the obvious candidate), it is switched on
    here and is ABSENT from tools/list while off, rather than present and erroring. An
    agent should see a smaller honest toolset, not a tool that fails.
    """
    return {name: spec for name, spec in TOOLS.items() if name in READ_ONLY_TOOLS}


# ── Resources ───────────────────────────────────────────────────────────────────

RESOURCES = {
    "wecare://site/summary": {
        "name": "site-summary",
        "title": "WECARE.DIGITAL summary",
        "description": "Who this business is, what it does, and the terms for citing its content.",
        "mimeType": "application/json",
        "build": lambda: json.dumps(_tool_get_site_summary({}), indent=2, default=str),
    },
    "wecare://pages/catalog": {
        "name": "page-catalog",
        "title": "Public page catalogue",
        "description": "Every public page with its canonical url, name and description.",
        "mimeType": "application/json",
        "build": lambda: json.dumps(_tool_list_pages({}), indent=2, default=str),
    },
}


# ── HTTP plumbing ───────────────────────────────────────────────────────────────

def _allowed_origins() -> List[str]:
    configured = os.environ.get("MCP_ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in configured.split(",") if o.strip()]
    # app.wecare.digital dropped 2026-09-28: host retired, NXDOMAIN.
    return origins or [SITE_URL, "https://www.wecare.digital"]


def _header(event: Dict[str, Any], name: str) -> str:
    """Case-insensitive header read.

    API Gateway HTTP API payload 2.0 lower-cases header names, but a Function URL or a
    direct test invocation may not, and `MCP-Protocol-Version` is mixed case in the spec.
    Reading case-insensitively costs nothing and removes a class of bug that only appears
    off the API Gateway path.
    """
    headers = event.get("headers") or {}
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value or "")
    return ""


def _method(event: Dict[str, Any]) -> str:
    ctx = (event.get("requestContext") or {}).get("http") or {}
    return str(ctx.get("method") or event.get("httpMethod") or "POST").upper()


def _cors(origin: str) -> Dict[str, str]:
    allowed = _allowed_origins()
    return {
        # Mcp-Session-Id and MCP-Protocol-Version are NOT in lambda_utils' DEFAULT_HEADERS
        # and a browser client cannot send them without being named here. Last-Event-ID is
        # listed for the same reason even though this server never opens a stream: a
        # client that supports resumption may send it unconditionally, and a preflight
        # failure would look like the endpoint is down.
        "Access-Control-Allow-Origin": origin if origin in allowed else allowed[0],
        "Access-Control-Allow-Methods": "POST,GET,DELETE,OPTIONS",
        "Access-Control-Allow-Headers":
            "Content-Type,Accept,Authorization,Mcp-Session-Id,MCP-Protocol-Version,Last-Event-ID",
        "Access-Control-Expose-Headers": "Mcp-Session-Id,MCP-Protocol-Version",
        "Access-Control-Max-Age": "86400",
    }


def _http(status: int, body: Optional[Any], origin: str,
          content_type: str = "application/json",
          extra: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = {"Cache-Control": "no-store", **_cors(origin)}
    if extra:
        headers.update(extra)
    response: Dict[str, Any] = {"statusCode": status, "headers": headers}
    if body is None:
        # 202 Accepted for a notification "MUST" carry no body. An empty string rather
        # than a literal "null", which json.dumps(None) would produce and which a strict
        # client would try to parse as a JSON-RPC message.
        response["body"] = ""
        return response
    headers["Content-Type"] = content_type
    response["body"] = body if isinstance(body, str) else json.dumps(body, default=str)
    return response


def _rpc_error(request_id: Any, code: int, message: str,
               data: Optional[Any] = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _rpc_result(request_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_error(request_id: Any, message: str) -> Dict[str, Any]:
    """A failed tool call is a SUCCESSFUL JSON-RPC response with isError set.

    This is the part of MCP most often got wrong. A protocol-level error means the call
    could not be dispatched; a tool that ran and failed must come back as a result, so
    the model can read the reason and choose differently. Returning -32603 here would
    look to the client like the server is broken rather than like the slug was wrong.
    """
    return _rpc_result(request_id, {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


# ── JSON-RPC dispatch ───────────────────────────────────────────────────────────

def _handle_initialize(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    requested = str(params.get("protocolVersion") or "").strip()
    # Echo the client's version when we speak it, otherwise answer with our newest and
    # let the client decide. The spec puts the disconnect decision on the client, so
    # refusing here would be stricter than required and would lock out a newer client
    # that could have negotiated down.
    negotiated = requested if requested in PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return _rpc_result(request_id, {
        "protocolVersion": negotiated,
        "capabilities": {
            # No listChanged on either: the catalogue ships in the zip and changes only
            # on deploy, and a stateless server has no stream on which to deliver the
            # notification. Advertising it would promise something we cannot send.
            "tools": {},
            "resources": {},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "title": SERVER_TITLE,
            "version": SERVER_VERSION,
        },
        "instructions": (
            "Read-only access to the public content of wecare.digital: the marketing and "
            "customer-service pages, and the published blog corpus.\n\n"
            "Start with get_site_summary for identity and citation terms. Use search_pages to "
            "find the page covering a topic and search_blog for articles. Always cite the "
            "canonical url a tool returns; it already carries the trailing slash.\n\n"
            "This endpoint cannot act. It cannot send a message, create or amend a request, take "
            "a payment, or read any customer record. Direct a person who wants to do one of those "
            f"to the relevant customer-service page at {SITE_URL}/contact/ .\n\n"
            "Do not state prices, turnaround times, or medical, legal or financial advice that a "
            "page does not state. Bharat Rx does not retail medicines."
        ),
    })


def _handle_tools_list(request_id: Any) -> Dict[str, Any]:
    tools = [{
        "name": name,
        "title": spec["title"],
        "description": spec["description"],
        "inputSchema": spec["schema"],
        # Hints are advisory, and honest ones are worth setting: a host that surfaces
        # "this tool only reads" can auto-approve instead of prompting a user for every
        # lookup, which is the difference between a usable and an annoying integration.
        "annotations": {
            "title": spec["title"],
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    } for name, spec in sorted(_enabled_tools().items())]
    return _rpc_result(request_id, {"tools": tools})


def _handle_tools_call(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("name") or "")
    tools = _enabled_tools()
    if name not in tools:
        return _rpc_error(request_id, INVALID_PARAMS, f"Unknown tool: {name}",
                          {"availableTools": sorted(tools)})
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _rpc_error(request_id, INVALID_PARAMS, "arguments must be an object")
    try:
        payload = tools[name]["handler"](arguments)
    except (ValueError, LookupError) as exc:
        # Our own message, built from our own parts, so it is safe to return - and it is
        # the thing the model needs in order to retry correctly.
        return _tool_error(request_id, str(exc))
    except RuntimeError as exc:
        return _tool_error(request_id, str(exc))
    except Exception:
        logger.exception("mcp tool failed: %s", name)
        return _tool_error(request_id, "That lookup failed. Try again shortly.")
    text = json.dumps(payload, indent=2, default=str)
    return _rpc_result(request_id, {
        # Both arms on purpose. `content` is what every client renders; `structuredContent`
        # is what a newer client can consume without re-parsing the text. Sending only
        # structuredContent would render as empty on an older host.
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": False,
    })


def _handle_resources_list(request_id: Any) -> Dict[str, Any]:
    return _rpc_result(request_id, {"resources": [{
        "uri": uri,
        "name": spec["name"],
        "title": spec["title"],
        "description": spec["description"],
        "mimeType": spec["mimeType"],
    } for uri, spec in sorted(RESOURCES.items())]})


def _handle_resources_read(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    uri = str(params.get("uri") or "")
    spec = RESOURCES.get(uri)
    if spec is None:
        return _rpc_error(request_id, INVALID_PARAMS, f"Unknown resource: {uri}",
                          {"availableResources": sorted(RESOURCES)})
    try:
        text = spec["build"]()
    except Exception:
        logger.exception("mcp resource build failed: %s", uri)
        return _rpc_error(request_id, INTERNAL_ERROR, "That resource is temporarily unavailable")
    return _rpc_result(request_id, {"contents": [{
        "uri": uri, "name": spec["name"], "title": spec["title"],
        "mimeType": spec["mimeType"], "text": text,
    }]})


def _dispatch(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Route one JSON-RPC message. `None` means "nothing to send back".

    A notification is identified by the ABSENCE of `id`, not by a null id - JSON-RPC 2.0
    treats `"id": null` as a request with a null id. `"id" not in message` is therefore
    the correct test and `message.get("id") is None` is not.
    """
    method = str(message.get("method") or "")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    is_notification = "id" not in message
    request_id = message.get("id")

    if is_notification:
        # notifications/initialized, notifications/cancelled and friends. Nothing to do
        # in a stateless server, and the transport requires 202 with no body either way.
        return None

    if method == "initialize":
        return _handle_initialize(request_id, params)
    if method == "ping":
        return _rpc_result(request_id, {})
    if method == "tools/list":
        return _handle_tools_list(request_id)
    if method == "tools/call":
        return _handle_tools_call(request_id, params)
    if method == "resources/list":
        return _handle_resources_list(request_id)
    if method == "resources/read":
        return _handle_resources_read(request_id, params)
    if method in ("prompts/list", "resources/templates/list"):
        # Answered rather than 404'd. A client that probes these before checking
        # capabilities should see an empty list, not an error that reads as a fault.
        key = "prompts" if method.startswith("prompts") else "resourceTemplates"
        return _rpc_result(request_id, {key: []})
    if method == "completion/complete":
        return _rpc_result(request_id, {"completion": {"values": [], "hasMore": False}})
    return _rpc_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")


# ── Entry point ─────────────────────────────────────────────────────────────────

def handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    origin = _header(event, "origin")
    method = _method(event)

    if method == "OPTIONS":
        return _http(204, None, origin)

    # EVERY ERROR BODY BELOW GOES THROUGH _rpc_error, AND THAT IS NOT TIDYING.
    #
    # These four transport-level refusals were hand-built dicts of the form
    # `{"jsonrpc": "2.0", "error": {...}}` - with no `id` member. That is a MALFORMED
    # JSON-RPC response object, not a stylistic difference. JSON-RPC 2.0 s5 is explicit that
    # `id` is REQUIRED on a Response, and names this exact case:
    #
    #     If there was an error in detecting the id in the Request Object (e.g. Parse error /
    #     Invalid Request), it MUST be Null.
    #
    # A GET carries no Request Object at all, so `"id": null` is the specified answer and
    # omitting it is simply wrong. It shipped because the tests assert the status code and the
    # Allow header and never looked at the body - so a client that ignores the body saw
    # nothing wrong, and a client that validates it would reject the response as malformed
    # while the endpoint looked healthy from every direction we were measuring.
    #
    # `_rpc_error(None, ...)` puts `"id": null` in by construction, which is why these route
    # through it rather than being fixed in place four times. test_mcp_server.py now asserts
    # the property over every response the handler can emit, so a fifth hand-built body fails.

    # Origin first, before anything else is parsed. A rebinding attempt should not reach
    # the body parser, and the check is cheap.
    if origin and origin not in _allowed_origins():
        logger.warning(json.dumps({"event": "mcp_origin_rejected", "originAllowed": False}))
        return _http(403, _rpc_error(None, INVALID_REQUEST, "Origin not allowed"), origin)

    if method in ("GET", "DELETE"):
        # GET: "return HTTP 405 Method Not Allowed, indicating that the server does not
        # offer an SSE stream at this endpoint." DELETE: "The server MAY respond to this
        # request with HTTP 405 Method Not Allowed, indicating that the server does not
        # allow clients to terminate sessions." Both are spec-blessed for this server
        # shape. Allow advertises what the endpoint does support, per RFC 9110.
        detail = ("This endpoint does not offer an SSE stream. POST a JSON-RPC message instead."
                  if method == "GET" else
                  "This server is stateless and issues no session, so there is none to delete.")
        return _http(405, _rpc_error(None, INVALID_REQUEST, detail),
                     origin, extra={"Allow": "POST, OPTIONS"})

    if method != "POST":
        return _http(405, _rpc_error(None, INVALID_REQUEST, f"{method} is not supported"),
                     origin, extra={"Allow": "POST, OPTIONS"})

    # An unsupported version MUST be 400. Absent is NOT an error - the spec says assume
    # 2025-03-26 - so the empty case falls through deliberately.
    version = _header(event, "mcp-protocol-version").strip()
    if version and version not in PROTOCOL_VERSIONS:
        return _http(400, _rpc_error(None, INVALID_REQUEST,
                                     f"Unsupported MCP-Protocol-Version: {version}",
                                     {"supported": list(PROTOCOL_VERSIONS)}), origin)
    negotiated = version or DEFAULT_PROTOCOL_VERSION

    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and raw:
        import base64
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            return _http(400, _rpc_error(None, PARSE_ERROR, "Body is not valid base64 UTF-8"), origin)

    try:
        message = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return _http(400, _rpc_error(None, PARSE_ERROR, "Invalid JSON"), origin)

    if isinstance(message, list):
        # Batching was removed in 2025-06-18 and this server never supported it. Saying
        # so beats a confusing parse failure.
        return _http(400, _rpc_error(None, INVALID_REQUEST,
                                     "JSON-RPC batching is not supported; send one message per request"),
                     origin)
    if not isinstance(message, dict):
        return _http(400, _rpc_error(None, INVALID_REQUEST,
                                     "Body must be a single JSON-RPC message object"), origin)
    if message.get("jsonrpc") != "2.0":
        return _http(400, _rpc_error(message.get("id"), INVALID_REQUEST,
                                     "jsonrpc must be \"2.0\""), origin)

    # A response or error arriving from the client is a valid thing to receive and, like a
    # notification, takes 202 with no body. Checked before `method`, because such a
    # message has no method and would otherwise fall through as "Method not found: ".
    if "method" not in message and ("result" in message or "error" in message):
        return _http(202, None, origin)
    if "method" not in message:
        return _http(400, _rpc_error(message.get("id"), INVALID_REQUEST,
                                     "Message has no method"), origin)

    try:
        reply = _dispatch(message)
    except Exception:
        logger.exception("mcp dispatch failed")
        return _http(500, _rpc_error(message.get("id"), INTERNAL_ERROR, "Internal error"), origin)

    if reply is None:
        return _http(202, None, origin)

    return _http(200, reply, origin, extra={"MCP-Protocol-Version": negotiated})
