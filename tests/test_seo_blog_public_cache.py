"""The public blog read surface: caching, projection, conditional requests, upstream failure.

WHY THESE EXIST. This endpoint took 185,576 requests in 24 hours on 2026-09-28 - the
hottest in the account - and it reached the API Gateway 30-second ceiling, logging
`30001ms status=503`. The cause was arithmetic rather than a slow network: every request
re-fetched the Wix category and tag maps, and the list path walked 9 sequential pages, each
with a 30-second timeout, against a 30-second budget.

The fix has three layers and each one can regress silently, so each one is pinned here:

  the per-sandbox caches in wix.py        a warm request must make NO upstream call
  serve-stale-on-failure                  an upstream 503 must not empty the blog
  the ?fields= projection and the ETag    the response must shrink, and 304 must work

The stale-serving test is the one that matters most. `scripts/generate-sitemap.js` refuses
to write a sitemap with zero posts precisely because a two-second network blip once
produced one, and that guard is the last line rather than the first.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEO_DIR = ROOT / "amplify/functions/operations/seo-tools"

# The handler imports `ai`, `storage` and `wix` as top-level siblings, the way the deployed
# zip lays them out, so its directory has to be importable as itself.
for path in (str(SEO_DIR), str(ROOT / "amplify/functions/shared")):
    if path not in sys.path:
        sys.path.insert(0, path)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SEO_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wix = _load("wix")

POSTS = [
    {"slug": "first-post", "title": "First post", "excerpt": "An excerpt.",
     "category": "Travel", "publishedDate": "2026-03-01", "authorName": "A",
     "jsonLd": {"@type": "BlogPosting", "headline": "First post"},
     "keywords": ["a", "b"], "hashtags": ["#x"], "robots": "index, follow",
     "metaDescription": "A meta description.", "focusKeyword": "travel",
     "url": "https://wecare.digital/post/first-post/"},
    {"slug": "second-post", "title": "Second post", "excerpt": "Another.",
     "category": "Ritual", "publishedDate": "2026-02-01", "authorName": "B",
     "jsonLd": {"@type": "BlogPosting"}, "keywords": [], "hashtags": [],
     "robots": "index, follow", "metaDescription": "Another meta.",
     "focusKeyword": "ritual", "url": "https://wecare.digital/post/second-post/"},
]


@pytest.fixture(autouse=True)
def clean_cache():
    wix.clear_blog_cache()
    yield
    wix.clear_blog_cache()


# --------------------------------------------------------------------------- #
# the per-sandbox caches
# --------------------------------------------------------------------------- #

class TestUpstreamCaching:
    def test_a_warm_repeat_makes_no_upstream_call(self, monkeypatch):
        """The change that actually removed the 30s timeout.

        Uncached, the list path was 2 reference-map queries plus 9 paginated post queries
        on EVERY request. This asserts the second call costs zero upstream requests.
        """
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return list(POSTS)

        monkeypatch.setattr(wix, "_fetch_blog_posts", fake_fetch)
        first = wix.list_blog_posts()
        second = wix.list_blog_posts()
        assert calls["n"] == 1
        assert first == second == POSTS

    def test_the_reference_maps_are_not_refetched_per_request(self, monkeypatch):
        """They resolve category and tag LABELS, which change on a content edit rather
        than per request, and re-fetching them was the single biggest waste here."""
        calls = {"n": 0}

        def fake_refs():
            calls["n"] += 1
            return {"categories": {}, "tags": {}}

        monkeypatch.setattr(wix, "_fetch_blog_reference_maps", fake_refs)
        for _ in range(5):
            wix._blog_reference_maps()
        assert calls["n"] == 1

    def test_a_purge_forces_the_next_read_to_refetch(self, monkeypatch):
        """Content is authored in Wix, outside this system, so an operator who has just
        published needs a way to beat the TTL. Without this the new post simply appears
        to be missing for five minutes."""
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return list(POSTS)

        monkeypatch.setattr(wix, "_fetch_blog_posts", fake_fetch)
        wix.list_blog_posts()
        wix.clear_blog_cache()
        wix.list_blog_posts()
        assert calls["n"] == 2


class TestServeStaleOnFailure:
    def test_a_failed_refresh_serves_the_previous_corpus(self, monkeypatch):
        """AN EXPIRED CACHE BEATS AN EMPTY ANSWER, and this is the asymmetry that matters.

        Wix returned a genuine 503 twice in 7 days. Surfacing that as an empty blog makes
        `next build` emit a site with no posts; generate-sitemap.js exists because that
        happened once already from a brief network failure. Five-minute-old category
        labels are a non-event by comparison.
        """
        state = {"fail": False}

        def flaky():
            if state["fail"]:
                raise RuntimeError("Wix public Blog API request failed with status 503")
            return list(POSTS)

        monkeypatch.setattr(wix, "_fetch_blog_posts", flaky)
        monkeypatch.setattr(wix, "_BLOG_CACHE_TTL", 0)  # every call re-fetches
        assert wix.list_blog_posts() == POSTS
        state["fail"] = True
        assert wix.list_blog_posts() == POSTS, "should have served the stale corpus"

    def test_a_failure_with_nothing_cached_still_raises(self, monkeypatch):
        """Serving stale must not become swallowing errors. With no previous value there
        is nothing honest to return, so the caller gets to decide."""
        def always_fails():
            raise RuntimeError("Wix public Blog API request failed with status 503")

        monkeypatch.setattr(wix, "_fetch_blog_posts", always_fails)
        with pytest.raises(RuntimeError):
            wix.list_blog_posts()

    def test_a_missing_slug_is_not_cached(self, monkeypatch):
        """`None` means both "no such post" and "the lookup failed". Caching it would keep
        a real post missing for the whole TTL after one transient failure."""
        state = {"found": False}

        def fetch(_slug):
            return dict(POSTS[0]) if state["found"] else None

        monkeypatch.setattr(wix, "_fetch_blog_post", fetch)
        assert wix.get_blog_post_by_slug("first-post") is None
        state["found"] = True
        assert wix.get_blog_post_by_slug("first-post")["slug"] == "first-post"

    def test_the_list_loop_refuses_to_return_a_truncated_corpus(self, monkeypatch):
        """It RAISES on budget exhaustion rather than returning what it has.

        A truncated corpus is the worse failure by a distance, because it looks like
        success: generate-sitemap.js would write a sitemap silently missing the rest, and
        its guard only catches ZERO posts, not 400 of 889.
        """
        monkeypatch.setenv("WIX_BLOG_LIST_BUDGET_SECONDS", "0")
        monkeypatch.setattr(wix, "_blog_reference_maps", lambda: {"categories": {}, "tags": {}})
        monkeypatch.setattr(wix, "public_blog_request",
                            lambda *a, **k: pytest.fail("should not reach the upstream"))
        with pytest.raises(RuntimeError, match="time budget"):
            wix._fetch_blog_posts()


class TestRetryPolicy:
    def test_only_the_transient_statuses_are_retried(self):
        """A 404 is the answer, not a failure - get_blog_post_by_slug reads that string to
        return None, so retrying it would double the latency of every miss. A 401 means
        the token is wrong and will be wrong again."""
        assert 503 in wix._RETRY_STATUSES
        assert 429 in wix._RETRY_STATUSES
        assert 404 not in wix._RETRY_STATUSES
        assert 401 not in wix._RETRY_STATUSES

    def test_the_per_call_timeout_leaves_room_under_the_30s_ceiling(self):
        """Two attempts plus backoff must fit, with room for a caller making several
        calls. The old flat 30s could spend the entire API Gateway budget on one request.
        """
        worst_case = 2 * wix._REQUEST_TIMEOUT + 0.4
        assert worst_case < 30, f"one call can consume {worst_case}s of a 30s budget"


# --------------------------------------------------------------------------- #
# the HTTP surface
# --------------------------------------------------------------------------- #

handler_mod = _load("handler")


def get(path: str, *, query=None, headers=None):
    event = {
        "requestContext": {"http": {"method": "GET", "path": path}},
        "rawPath": path,
        "headers": {"origin": "https://wecare.digital", **(headers or {})},
        "queryStringParameters": query,
        "body": "",
    }
    return handler_mod.handler(event, None)


@pytest.fixture
def stub_upstream(monkeypatch):
    """Replace the two public reads at the HTTP boundary.

    PATCH THE SEAM THE HANDLER ACTUALLY CALLS. Since the blog_source split, the handler reads
    through `blog_source.list_blog_posts()` / `blog_source.get_blog_post_by_slug()` (which
    dispatch to Wix by default or AWS under BLOG_SOURCE), NOT through `wix.*` directly. Patching
    `handler_mod.wix` here left the real `wix` fetch on the handler's path, so a warm suite - any
    test that first imported `blog_source` under its own sys.path, e.g. test_blog_source_dispatch
    - diverged `blog_source.wix` from `handler_mod.wix`, the stub missed, and the read hit the
    network (blocked by conftest) and 503'd. Patching `blog_source` is the handler's true
    dependency and is immune to that module-identity divergence.

    DELIBERATELY NOT autouse. The TestUpstreamCaching / TestServeStaleOnFailure tests above need
    the real caching `wix` implementation; an autouse stub would replace it for them too.
    """
    monkeypatch.setattr(handler_mod.blog_source, "list_blog_posts", lambda: list(POSTS))
    monkeypatch.setattr(handler_mod.blog_source, "get_blog_post_by_slug",
                        lambda slug: next((dict(p) for p in POSTS if p["slug"] == slug), None))
    yield


@pytest.mark.usefixtures("stub_upstream")
class TestProjection:
    def test_no_fields_parameter_returns_every_field(self):
        """Backwards compatible. src/lib/public-blog.ts reads the unprojected shape and
        must not be broken by this feature existing."""
        body = json.loads(get("/prod/seo-tools/blog-public")["body"])
        assert set(body["posts"][0]) == set(POSTS[0])

    def test_fields_drops_the_payload_nobody_renders(self):
        """The list response is 924 kB for 889 posts and about half of it is jsonLd,
        keywords, hashtags, robots, focusKeyword and metaDescription."""
        response = get("/prod/seo-tools/blog-public",
                       query={"fields": "slug,title,excerpt,category,publishedDate"})
        body = json.loads(response["body"])
        assert set(body["posts"][0]) == {"slug", "title", "excerpt", "category", "publishedDate"}
        assert len(response["body"]) < 400

    def test_total_still_counts_the_whole_corpus(self):
        """`total` describes the blog, not the projection. generate-sitemap.js and the
        paginated index both rely on it."""
        body = json.loads(get("/prod/seo-tools/blog-public", query={"fields": "slug"})["body"])
        assert body["total"] == len(POSTS)

    def test_slug_is_always_included(self):
        body = json.loads(get("/prod/seo-tools/blog-public", query={"fields": "title"})["body"])
        assert "slug" in body["posts"][0]

    def test_an_unknown_field_is_ignored_rather_than_rejected(self):
        """A 400 here would break a build over a field rename. The caller gets what still
        exists."""
        body = json.loads(get("/prod/seo-tools/blog-public",
                              query={"fields": "title,doesNotExist"})["body"])
        assert set(body["posts"][0]) == {"slug", "title"}

    def test_asking_only_for_nonsense_falls_back_to_everything(self):
        body = json.loads(get("/prod/seo-tools/blog-public", query={"fields": "nope"})["body"])
        assert set(body["posts"][0]) == set(POSTS[0])

    def test_the_allowlist_blocks_probing_for_internal_fields(self):
        assert "content" not in handler_mod._PUBLIC_POST_FIELDS
        assert "richContent" not in handler_mod._PUBLIC_POST_FIELDS


@pytest.mark.usefixtures("stub_upstream")
class TestConditionalRequests:
    def test_the_response_carries_an_etag_and_cache_control(self):
        headers = get("/prod/seo-tools/blog-public")["headers"]
        assert headers["ETag"].startswith('"')
        assert "s-maxage" in headers["Cache-Control"]

    def test_a_matching_if_none_match_returns_304_with_no_body(self):
        first = get("/prod/seo-tools/blog-public")
        etag = first["headers"]["ETag"]
        second = get("/prod/seo-tools/blog-public", headers={"if-none-match": etag})
        assert second["statusCode"] == 304
        # A 304 MUST NOT carry a body - which is why this path cannot use cors_response,
        # since that always serialises one.
        assert second["body"] == ""

    def test_a_stale_etag_returns_the_full_body(self):
        response = get("/prod/seo-tools/blog-public", headers={"if-none-match": '"outdated"'})
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["ok"] is True

    def test_the_etag_tracks_the_projection(self):
        """Two different projections are two different documents. One shared tag would let
        a cache serve a trimmed body to a caller that asked for everything."""
        full = get("/prod/seo-tools/blog-public")["headers"]["ETag"]
        trimmed = get("/prod/seo-tools/blog-public", query={"fields": "slug"})["headers"]["ETag"]
        assert full != trimmed

    def test_vary_names_origin_because_cors_reflects_it(self):
        """cors_headers reflects an allowed Origin back. Without Vary, a shared cache
        could serve one origin's Access-Control-Allow-Origin to another."""
        assert "Origin" in get("/prod/seo-tools/blog-public")["headers"]["Vary"]


@pytest.mark.usefixtures("stub_upstream")
class TestUpstreamFailureSurface:
    def test_an_upstream_failure_is_503_not_500(self, monkeypatch):
        """503 is the honest status and it is the one a caller can act on. wix.py already
        retried and already tried to serve stale, so reaching here means genuinely down
        with nothing cached."""
        def boom():
            raise RuntimeError("Wix public Blog API request failed with status 503")

        monkeypatch.setattr(handler_mod.blog_source, "list_blog_posts", boom)
        response = get("/prod/seo-tools/blog-public")
        assert response["statusCode"] == 503
        assert json.loads(response["body"])["ok"] is False

    def test_a_failure_never_looks_like_an_empty_blog(self, monkeypatch):
        """The failure mode that actually cost something. An empty `posts` array with
        HTTP 200 is what makes a build publish a site with no blog."""
        def boom():
            raise RuntimeError("upstream down")

        monkeypatch.setattr(handler_mod.blog_source, "list_blog_posts", boom)
        body = json.loads(get("/prod/seo-tools/blog-public")["body"])
        assert body.get("posts") is None
        assert body.get("total") is None

    def test_a_genuinely_missing_post_is_still_404(self, monkeypatch):
        response = get("/prod/seo-tools/blog-public/no-such-post")
        assert response["statusCode"] == 404


@pytest.mark.usefixtures("stub_upstream")
class TestPublicSurfaceStaysNarrow:
    def test_only_GET_reaches_the_public_branch(self):
        """A POST to the same path must fall through to require_auth. Verified live before
        this change: it returns 401."""
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/prod/seo-tools/blog-public"}},
            "headers": {"origin": "https://wecare.digital"},
            "body": "{}",
        }
        assert handler_mod.handler(event, None)["statusCode"] in (401, 403)

    def test_the_cache_purge_route_is_not_public(self):
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/prod/seo-tools/cache-purge"}},
            "headers": {"origin": "https://wecare.digital"},
            "body": "{}",
        }
        assert handler_mod.handler(event, None)["statusCode"] in (401, 403)
