"""Tests for the public MCP server at https://wecare.digital/mcp

Two things are being defended here, and they are different in kind.

THE PROTOCOL. An MCP client does not negotiate around a non-compliant server; it fails
the handshake and reports the endpoint as broken, with no detail a operator can act on.
The transport's MUSTs are cheap to get wrong and expensive to notice, so each one that
this server implements has a test naming it: 403 on a foreign Origin, 405 on GET, 400 on
an unsupported protocol version, 202-with-no-body for a notification, and the
absent-version default of 2025-03-26 rather than the newest.

THE BLAST RADIUS. This is an unauthenticated route that anyone on the internet can call,
so the tool list is asserted for EXACT equality against a frozen allowlist. A test that
merely checked the current tools all work would pass just as happily after someone added
`send_whatsapp`. The point of `test_tool_list_is_exactly_the_frozen_allowlist` is to fail
on the addition itself.

The blog corpus is stubbed throughout. Reaching the live /api/seo-tools/blog-public would
make the suite depend on the network and on 889 records of production content, and would
hammer the hottest function in the fleet from CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "amplify/functions/ai/mcp/handler.py"
CATALOG_PATH = ROOT / "config/public-pages.json"

# Point the handler at the real catalogue in config/ rather than the copy the packager
# places beside handler.py in the zip. Set before exec_module because the path is read at
# import time.
os.environ["MCP_CATALOG_PATH"] = str(CATALOG_PATH)

spec = importlib.util.spec_from_file_location("mcp_server", HANDLER_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

APEX = "https://wecare.digital"

FAKE_POSTS = [
    {"slug": "visa-rules-2026", "title": "Visa rules for 2026",
     "excerpt": "What changed for Indian travellers applying for a Schengen visa.",
     "category": "Travel", "publishedDate": "2026-03-01", "url": f"{APEX}/post/visa-rules-2026/"},
    {"slug": "puja-kit-guide", "title": "Choosing a puja kit",
     "excerpt": "Temple-grade materials and what actually matters.",
     "category": "Ritual", "publishedDate": "2026-01-15", "url": f"{APEX}/post/puja-kit-guide/"},
    {"slug": "older-visa-note", "title": "Visa appointment backlog",
     "excerpt": "Waiting times at consulates.",
     "category": "Travel", "publishedDate": "2025-11-02", "url": f"{APEX}/post/older-visa-note/"},
]


@pytest.fixture(autouse=True)
def stub_blog(monkeypatch):
    """No network. Also clears the memo so one test's cache cannot leak into the next."""
    monkeypatch.setattr(mod, "_blog_cache", (0.0, []))
    monkeypatch.setattr(mod, "_fetch_blog", lambda: list(FAKE_POSTS))
    yield


def call(body, *, method="POST", origin="", headers=None, raw_body=None):
    """Invoke the handler the way API Gateway HTTP API payload 2.0 does."""
    request_headers = {}
    if origin:
        request_headers["origin"] = origin
    if headers:
        request_headers.update(headers)
    event = {
        "requestContext": {"http": {"method": method, "path": "/mcp"}},
        "headers": request_headers,
        "body": raw_body if raw_body is not None else (json.dumps(body) if body is not None else ""),
    }
    return mod.handler(event, None)


def rpc(method, params=None, request_id=1, **kwargs):
    """A JSON-RPC request, returning the parsed response body."""
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    response = call(message, **kwargs)
    return response, (json.loads(response["body"]) if response.get("body") else None)


# --------------------------------------------------------------------------- #
# transport: methods
# --------------------------------------------------------------------------- #

class TestTransportMethods:
    def test_get_returns_405_because_no_sse_stream_is_offered(self):
        """The spec's explicit alternative to opening a stream on GET.

        "The server MUST either return Content-Type: text/event-stream in response to this
        HTTP GET, or else return HTTP 405 Method Not Allowed, indicating that the server
        does not offer an SSE stream at this endpoint."

        API Gateway buffers its Lambda integration, so SSE is not available and 405 is the
        correct half of that MUST - not a gap.
        """
        response = call(None, method="GET")
        assert response["statusCode"] == 405
        # RFC 9110 requires Allow on a 405, and it is how a client discovers POST works.
        assert "POST" in response["headers"]["Allow"]

    def test_delete_returns_405_because_there_is_no_session_to_delete(self):
        response = call(None, method="DELETE")
        assert response["statusCode"] == 405

    def test_options_preflight_advertises_the_mcp_headers(self):
        response = call(None, method="OPTIONS", origin=APEX)
        assert response["statusCode"] == 204
        allowed = response["headers"]["Access-Control-Allow-Headers"]
        # A browser client cannot send these unless they are named, and lambda_utils'
        # DEFAULT_HEADERS does not list them.
        assert "Mcp-Session-Id" in allowed
        assert "MCP-Protocol-Version" in allowed

    def test_unsupported_verb_is_405_not_500(self):
        response = call(None, method="PUT")
        assert response["statusCode"] == 405


# --------------------------------------------------------------------------- #
# transport: every body is a well-formed JSON-RPC response
# --------------------------------------------------------------------------- #

class TestEveryErrorBodyIsValidJsonRpc:
    """`id` is REQUIRED on a Response object, and null is the answer when there is no request.

    WHAT WAS ACTUALLY WRONG, because this reads like pedantry and was not. Four transport-level
    refusals - the Origin 403, the GET and DELETE 405s, the unsupported-verb 405 and the
    unsupported-version 400 - were hand-built as `{"jsonrpc": "2.0", "error": {...}}` with no
    `id` member at all. So a GET on the live endpoint returned:

        {"jsonrpc": "2.0", "error": {"code": -32600, "message": "This endpoint does not offer
         an SSE stream. POST a JSON-RPC message instead."}}

    which announces itself as JSON-RPC 2.0 and is not a valid JSON-RPC 2.0 response. Section 5
    of the specification makes `id` REQUIRED and names this exact situation: "If there was an
    error in detecting the id in the Request Object (e.g. Parse error/Invalid Request), it MUST
    be Null." A GET has no Request Object, so the answer is `"id": null`.

    WHY IT SURVIVED EVERY OTHER TEST IN THIS FILE. The three tests directly above assert the
    status code and the Allow header and never parse the body. That is the shape of the bug:
    a client that ignores the body sees a perfectly correct 405, and a client that validates
    the body rejects the response as malformed, while every measurement we had said healthy.

    ASSERTED AS A PROPERTY OVER EVERY EMITTING PATH rather than four times in four places, so
    a fifth hand-built body fails here instead of shipping. That is the whole reason this is a
    class and not one more line in TestTransportMethods.
    """

    @staticmethod
    def _check(response, *, expect_status):
        assert response["statusCode"] == expect_status
        body = response.get("body")
        assert body, "an error response must carry a body explaining itself"
        message = json.loads(body)
        assert message["jsonrpc"] == "2.0"
        # `in`, not truthiness. `"id": null` is the correct value here, so a check like
        # `assert message["id"]` would pass on the bug and fail on the fix.
        assert "id" in message, f"no id member: {message}"
        assert message["id"] is None, f"id must be null when no request id was read: {message}"
        assert isinstance(message["error"], dict)
        assert isinstance(message["error"]["code"], int)
        assert message["error"]["message"].strip()
        # A Response is an error OR a result, never both.
        assert "result" not in message
        return message

    def test_get_405(self):
        self._check(call(None, method="GET"), expect_status=405)

    def test_delete_405(self):
        self._check(call(None, method="DELETE"), expect_status=405)

    def test_unsupported_verb_405(self):
        self._check(call(None, method="PUT"), expect_status=405)

    def test_foreign_origin_403(self):
        self._check(call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                         origin="https://evil.example"), expect_status=403)

    def test_unsupported_protocol_version_400(self):
        message = self._check(
            call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                 headers={"MCP-Protocol-Version": "1999-01-01"}), expect_status=400)
        # The refusal has to say what IS supported, or a client cannot negotiate down.
        assert message["error"]["data"]["supported"] == list(mod.PROTOCOL_VERSIONS)

    def test_the_handler_builds_no_response_body_by_hand(self):
        """The structural half of the guard, because the cases above can only cover the paths
        they know to call. Every JSON-RPC envelope in the handler must come from the two
        constructors that set `id`; a literal `"jsonrpc": "2.0"` anywhere else is the defect
        class returning, on some path a future test has not thought to exercise.
        """
        source = HANDLER_PATH.read_text(encoding="utf-8")
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(source.splitlines(), start=1)
            if '"jsonrpc": "2.0"' in line
            and not line.lstrip().startswith("#")
            and '"id": request_id' not in line
        ]
        assert offenders == [], (
            "these build a JSON-RPC envelope outside _rpc_error/_rpc_result, so they can omit "
            "the REQUIRED id member:\n  " + "\n  ".join(offenders))


# --------------------------------------------------------------------------- #
# transport: origin
# --------------------------------------------------------------------------- #

class TestOriginValidation:
    def test_absent_origin_is_allowed_because_that_is_every_non_browser_client(self):
        """The rule is "present and invalid" -> 403. Absent is neither.

        This is the case that matters most in practice: a desktop MCP host, a hosted
        agent and curl all send no Origin at all. Rejecting them would make the endpoint
        useless for its primary consumer while satisfying nothing in the spec.
        """
        response, body = rpc("ping")
        assert response["statusCode"] == 200
        assert body["result"] == {}

    @pytest.mark.parametrize("origin", [
        "https://wecare.digital",
        "https://www.wecare.digital",
        # https://app.wecare.digital removed 2026-09-28: that host was retired
        # (NXDOMAIN) and dropped from the handler's allow-list, so asserting it is
        # allowed would pin an origin we deliberately no longer accept.
    ])
    def test_known_origins_are_allowed(self, origin):
        response, _ = rpc("ping", origin=origin)
        assert response["statusCode"] == 200

    def test_foreign_origin_is_403(self):
        response = call({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                        origin="https://evil.example.com")
        assert response["statusCode"] == 403

    def test_foreign_origin_is_refused_before_the_body_is_parsed(self):
        """Ordering, not just outcome. A rebinding attempt should not reach the parser."""
        response = call(None, origin="https://evil.example.com", raw_body="{not json at all")
        assert response["statusCode"] == 403


# --------------------------------------------------------------------------- #
# transport: protocol version
# --------------------------------------------------------------------------- #

class TestProtocolVersionHeader:
    def test_unsupported_version_is_400(self):
        response = call({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                        headers={"mcp-protocol-version": "1999-01-01"})
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert mod.LATEST_PROTOCOL_VERSION in body["error"]["data"]["supported"]

    def test_absent_version_is_not_an_error(self):
        """"if the server does not receive an MCP-Protocol-Version header ... the server
        SHOULD assume protocol version 2025-03-26." Assume, not reject."""
        response, _ = rpc("ping")
        assert response["statusCode"] == 200
        assert response["headers"]["MCP-Protocol-Version"] == mod.DEFAULT_PROTOCOL_VERSION

    def test_the_absent_default_is_not_the_newest_version(self):
        """Guards a plausible "tidy-up" that would break backwards compatibility.

        These two constants look redundant and are not: the spec pins the no-header
        fallback to 2025-03-26 specifically, while `initialize` should offer the newest.
        Collapsing them into one would silently change how an old client is treated.
        """
        assert mod.DEFAULT_PROTOCOL_VERSION == "2025-03-26"
        assert mod.LATEST_PROTOCOL_VERSION != mod.DEFAULT_PROTOCOL_VERSION

    def test_supported_version_is_echoed(self):
        response, _ = rpc("ping", headers={"mcp-protocol-version": "2025-11-25"})
        assert response["headers"]["MCP-Protocol-Version"] == "2025-11-25"


# --------------------------------------------------------------------------- #
# transport: message framing
# --------------------------------------------------------------------------- #

class TestMessageFraming:
    def test_notification_gets_202_and_a_genuinely_empty_body(self):
        """A notification has no `id`, and the transport requires 202 with no body.

        The body must not be the string "null" either - json.dumps(None) would produce
        that, and a strict client would try to parse it as a JSON-RPC message.
        """
        response = call({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert response["statusCode"] == 202
        assert response["body"] == ""

    def test_a_null_id_is_a_request_not_a_notification(self):
        """JSON-RPC 2.0 distinguishes an absent `id` from `"id": null`.

        Testing `message.get("id") is None` instead of `"id" not in message` would collapse
        the two and answer 202 to something that is waiting for a result.
        """
        response = call({"jsonrpc": "2.0", "id": None, "method": "ping"})
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["id"] is None

    def test_a_client_response_is_accepted_with_202(self):
        """A result/error arriving from the client has no `method`; it must not be
        answered "Method not found: "."""
        response = call({"jsonrpc": "2.0", "id": 7, "result": {}})
        assert response["statusCode"] == 202
        assert response["body"] == ""

    def test_invalid_json_is_a_parse_error(self):
        response = call(None, raw_body="{ not json")
        assert response["statusCode"] == 400
        assert json.loads(response["body"])["error"]["code"] == mod.PARSE_ERROR

    def test_a_batch_is_refused_with_an_explanation(self):
        """Batching was removed from the spec in 2025-06-18 and was never supported here.
        Saying so beats a confusing "Body must be a single message object"."""
        response = call([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
        assert response["statusCode"] == 400
        assert "batch" in json.loads(response["body"])["error"]["message"].lower()

    def test_wrong_jsonrpc_version_is_rejected(self):
        response = call({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        assert response["statusCode"] == 400

    def test_unknown_method_is_method_not_found(self):
        response, body = rpc("tools/summon")
        assert response["statusCode"] == 200
        assert body["error"]["code"] == mod.METHOD_NOT_FOUND


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #

class TestInitialize:
    def test_a_known_version_is_echoed_back(self):
        _, body = rpc("initialize", {"protocolVersion": "2025-06-18"})
        assert body["result"]["protocolVersion"] == "2025-06-18"

    def test_an_unknown_version_answers_with_our_newest(self):
        """Counter-offer rather than refuse. The spec leaves the disconnect decision to
        the client, so a newer client gets the chance to negotiate down."""
        _, body = rpc("initialize", {"protocolVersion": "2030-01-01"})
        assert body["result"]["protocolVersion"] == mod.LATEST_PROTOCOL_VERSION

    def test_declares_only_capabilities_it_can_honour(self):
        _, body = rpc("initialize", {"protocolVersion": mod.LATEST_PROTOCOL_VERSION})
        capabilities = body["result"]["capabilities"]
        assert set(capabilities) == {"tools", "resources"}
        # listChanged would promise a notification a stateless server with no stream can
        # never deliver.
        assert "listChanged" not in capabilities["tools"]
        assert "listChanged" not in capabilities["resources"]
        assert "prompts" not in capabilities

    def test_instructions_tell_the_model_what_it_must_not_claim(self):
        """The instructions field is the only prompt-level control this endpoint has.

        It is where the two content constraints live that no schema can express: that the
        endpoint cannot act, and that Bharat Rx is not a pharmacy - a claim a model would
        otherwise make by analogy from "consults, reminders and records".
        """
        _, body = rpc("initialize", {"protocolVersion": mod.LATEST_PROTOCOL_VERSION})
        instructions = body["result"]["instructions"]
        assert "cannot" in instructions.lower()
        assert "Bharat Rx does not retail medicines" in instructions

    def test_no_session_id_is_issued(self):
        """Stateless. Issuing one would oblige us to 404 requests carrying a stale id."""
        response, _ = rpc("initialize", {"protocolVersion": mod.LATEST_PROTOCOL_VERSION})
        assert "Mcp-Session-Id" not in response["headers"]

    def test_a_client_supplied_session_id_is_tolerated(self):
        response, _ = rpc("ping", headers={"mcp-session-id": "left-over-from-another-server"})
        assert response["statusCode"] == 200


# --------------------------------------------------------------------------- #
# the read-only guarantee
# --------------------------------------------------------------------------- #

class TestReadOnlyGuarantee:
    def test_tool_list_is_exactly_the_frozen_allowlist(self):
        """THE TEST THAT MATTERS MOST ON THIS FILE.

        Exact equality, not a subset. `tools/list` is derived from the TOOLS dict, so
        without this a new entry becomes publicly callable with no review step. A test
        that only checked the existing tools still work would pass after someone added
        `send_whatsapp`; this one fails on the addition.
        """
        _, body = rpc("tools/list")
        assert {tool["name"] for tool in body["result"]["tools"]} == set(mod.READ_ONLY_TOOLS)

    def test_every_advertised_tool_declares_itself_read_only(self):
        _, body = rpc("tools/list")
        for tool in body["result"]["tools"]:
            annotations = tool["annotations"]
            assert annotations["readOnlyHint"] is True, tool["name"]
            assert annotations["destructiveHint"] is False, tool["name"]

    @pytest.mark.parametrize("verb", [
        "send", "create", "update", "delete", "write", "pay", "refund",
        "capture", "charge", "invoice", "post_", "set_",
    ])
    def test_no_tool_name_suggests_a_side_effect(self, verb):
        """A crude check that earns its place by catching the mistake early.

        The precise guarantee is the frozen allowlist above. This one fires on the name at
        the moment it is typed, which is where the intent is still visible.
        """
        for name in mod.TOOLS:
            assert verb not in name, f"{name} looks like it mutates something"

    def test_every_tool_schema_refuses_unknown_arguments(self):
        """additionalProperties: False everywhere, so a client cannot smuggle a field a
        future handler might start honouring."""
        for name, spec_ in mod.TOOLS.items():
            assert spec_["schema"].get("additionalProperties") is False, name

    def test_the_handler_imports_no_aws_client(self):
        """No boto3, therefore no reachable AWS resource: no table to read, no queue to
        publish to, no Bedrock model to bill. The absence of the capability is the
        control, which is stronger than a permission check."""
        source = HANDLER_PATH.read_text(encoding="utf-8")
        assert "import boto3" not in source
        assert "boto3.client" not in source


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #

class TestTools:
    def test_search_pages_finds_a_page_by_its_description(self):
        _, body = rpc("tools/call", {"name": "search_pages", "arguments": {"query": "dispute resolution"}})
        payload = body["result"]["structuredContent"]
        assert payload["count"] >= 1
        assert payload["pages"][0]["path"] == "/clear-closure"

    def test_returned_urls_carry_the_trailing_slash(self):
        """next.config.js sets trailingSlash, so the slashless form 301s. Handing an agent
        a URL that redirects gives it a citation that can rot."""
        _, body = rpc("tools/call", {"name": "list_pages", "arguments": {}})
        for page in body["result"]["structuredContent"]["pages"]:
            assert page["url"].endswith("/"), page["url"]
            assert page["url"].startswith(APEX)

    def test_list_pages_can_be_narrowed_to_a_group(self):
        """The set is written out rather than derived from the catalogue the handler just
        read, which would assert nothing. It is SUPPOSED to fail when a page joins the
        group - that failure is what makes adding a page a decision about which heading an
        agent will find it under, instead of something that happens silently. /vault was
        added on 2026-09-30 and this is the line that noticed, and /request-pickup on
        2026-10-10."""
        _, body = rpc("tools/call", {"name": "list_pages", "arguments": {"group": "customerservice"}})
        payload = body["result"]["structuredContent"]
        assert payload["count"] == 7
        assert {p["path"] for p in payload["pages"]} == {
            "/submit-request", "/request-amendment", "/drop-docs", "/vault",
            "/request-pickup", "/leave-review", "/refer-and-earn",
        }

    def test_an_unknown_group_names_the_valid_ones(self):
        _, body = rpc("tools/call", {"name": "list_pages", "arguments": {"group": "nonsense"}})
        assert body["result"]["isError"] is True
        assert "customerservice" in body["result"]["content"][0]["text"]

    def test_search_blog_ranks_relevance_first_then_recency(self):
        _, body = rpc("tools/call", {"name": "search_blog", "arguments": {"query": "visa"}})
        payload = body["result"]["structuredContent"]
        slugs = [post["slug"] for post in payload["posts"]]
        assert slugs[:2] == ["visa-rules-2026", "older-visa-note"]
        assert payload["corpusSize"] == len(FAKE_POSTS)

    def test_blog_results_omit_the_seo_fields_that_bloat_the_payload(self):
        """The upstream response is 924 kB for 889 posts, roughly half of it jsonLd,
        keywords, hashtags and robots. None of it helps a model answer a question, and all
        of it would be re-serialised into every tool result."""
        _, body = rpc("tools/call", {"name": "search_blog", "arguments": {"query": "visa"}})
        post = body["result"]["structuredContent"]["posts"][0]
        for noisy in ("jsonLd", "keywords", "hashtags", "robots", "focusKeyword", "metaDescription"):
            assert noisy not in post

    def test_limit_is_clamped_rather_than_trusted(self):
        _, body = rpc("tools/call", {"name": "search_blog",
                                     "arguments": {"query": "visa", "limit": 10_000}})
        assert body["result"]["structuredContent"]["count"] <= mod.MAX_RESULTS

    def test_a_missing_slug_is_a_tool_error_not_a_protocol_error(self):
        """The distinction MCP implementations most often get wrong.

        A tool that ran and failed must come back as a RESULT with isError, so the model
        can read the reason and choose differently. Returning -32603 would tell the client
        the server is broken rather than that the slug was wrong.
        """
        response, body = rpc("tools/call", {"name": "get_blog_post", "arguments": {"slug": "nope"}})
        assert response["statusCode"] == 200
        assert "error" not in body
        assert body["result"]["isError"] is True

    def test_a_missing_required_argument_is_a_tool_error(self):
        _, body = rpc("tools/call", {"name": "search_pages", "arguments": {}})
        assert body["result"]["isError"] is True

    def test_an_unknown_tool_is_a_protocol_error_that_lists_the_real_ones(self):
        _, body = rpc("tools/call", {"name": "send_whatsapp", "arguments": {}})
        assert body["error"]["code"] == mod.INVALID_PARAMS
        assert set(body["error"]["data"]["availableTools"]) == set(mod.READ_ONLY_TOOLS)

    def test_results_carry_both_text_and_structured_content(self):
        """structuredContent alone renders as empty on an older host; text alone forces a
        newer one to re-parse. Both arms, deliberately."""
        _, body = rpc("tools/call", {"name": "get_site_summary", "arguments": {}})
        result = body["result"]
        assert result["content"][0]["type"] == "text"
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]

    def test_site_summary_states_what_the_endpoint_cannot_do(self):
        _, body = rpc("tools/call", {"name": "get_site_summary", "arguments": {}})
        payload = body["result"]["structuredContent"]
        assert payload["usageTerms"]
        assert any("read-only" in item.lower() for item in payload["notCoveredHere"])


# --------------------------------------------------------------------------- #
# blog cache
# --------------------------------------------------------------------------- #

class TestBlogCache:
    def test_the_corpus_is_fetched_once_across_many_calls(self):
        """Per warm sandbox, not per request. /api/seo-tools/blog-public is the hottest
        function in the fleet at 392k invocations a week; an uncached public endpoint in
        front of it would be a free amplifier."""
        calls = {"n": 0}

        def counting_fetch():
            calls["n"] += 1
            return list(FAKE_POSTS)

        mod._blog_cache = (0.0, [])
        mod._fetch_blog = counting_fetch
        for _ in range(5):
            rpc("tools/call", {"name": "search_blog", "arguments": {"query": "visa"}})
        assert calls["n"] == 1

    def test_a_stale_copy_is_served_when_a_refetch_fails(self):
        """An expired cache beats an empty answer.

        Reporting zero posts because of a two-second blip would make the blog look empty,
        which is the same failure generate-sitemap.js refuses to write a sitemap for.
        """
        def failing_fetch():
            raise OSError("upstream down")

        mod._blog_cache = (0.0, list(FAKE_POSTS))
        mod._fetch_blog = failing_fetch
        mod.BLOG_TTL_SECONDS = 0  # force the refetch path
        try:
            _, body = rpc("tools/call", {"name": "search_blog", "arguments": {"query": "visa"}})
            assert body["result"]["isError"] is False
            assert body["result"]["structuredContent"]["corpusSize"] == len(FAKE_POSTS)
        finally:
            mod.BLOG_TTL_SECONDS = 900

    def test_a_total_failure_is_a_tool_error_not_a_crash(self):
        def failing_fetch():
            raise OSError("upstream down")

        mod._blog_cache = (0.0, [])
        mod._fetch_blog = failing_fetch
        response, body = rpc("tools/call", {"name": "search_blog", "arguments": {"query": "visa"}})
        assert response["statusCode"] == 200
        assert body["result"]["isError"] is True


# --------------------------------------------------------------------------- #
# resources
# --------------------------------------------------------------------------- #

class TestResources:
    def test_resources_list_matches_what_can_be_read(self):
        _, body = rpc("resources/list")
        assert {r["uri"] for r in body["result"]["resources"]} == set(mod.RESOURCES)

    def test_each_resource_reads_as_the_mime_type_it_declares(self):
        _, listed = rpc("resources/list")
        for resource in listed["result"]["resources"]:
            _, body = rpc("resources/read", {"uri": resource["uri"]})
            content = body["result"]["contents"][0]
            assert content["mimeType"] == resource["mimeType"]
            json.loads(content["text"])  # declared application/json, so it must parse

    def test_an_unknown_uri_lists_the_real_ones(self):
        _, body = rpc("resources/read", {"uri": "wecare://nope"})
        assert body["error"]["code"] == mod.INVALID_PARAMS
        assert set(body["error"]["data"]["availableResources"]) == set(mod.RESOURCES)

    def test_optional_methods_answer_empty_rather_than_not_found(self):
        """A client that probes these before reading capabilities should see an empty
        list, not an error it will report as a fault."""
        for method, key in [("prompts/list", "prompts"),
                            ("resources/templates/list", "resourceTemplates")]:
            _, body = rpc(method)
            assert body["result"][key] == []


# --------------------------------------------------------------------------- #
# catalogue integrity
# --------------------------------------------------------------------------- #

class TestCatalogue:
    def test_the_catalogue_in_config_is_the_one_the_handler_reads(self):
        assert mod._CATALOG_PATH == str(CATALOG_PATH)

    def test_every_page_has_a_path_name_description_and_known_group(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        groups = {g["id"] for g in catalog["groups"]}
        for page in catalog["pages"]:
            assert page["path"].startswith("/"), page
            assert page["name"] and page["description"], page
            assert page["group"] in groups, page

    def test_no_page_is_listed_twice(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        paths = [page["path"] for page in catalog["pages"]]
        assert len(paths) == len(set(paths))

    def test_the_advertised_mcp_endpoint_is_the_apex_path(self):
        """Not /api/mcp. An MCP client is given one URL and will not go looking for
        another, and robots.txt disallows /api/ anyway."""
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        assert catalog["ai_surface"]["mcp_endpoint"] == f"{APEX}/mcp"

    def test_the_catalogue_advertises_only_versions_the_server_speaks(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        assert set(catalog["ai_surface"]["mcp_protocol_versions"]) == set(mod.PROTOCOL_VERSIONS)
