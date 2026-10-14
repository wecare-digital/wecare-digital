"""Public AWS-native blog surface: projection, ETag, failure semantics and auth boundary."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEO_DIR = ROOT / "amplify/functions/operations/seo-tools"

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
def stub_native_blog(monkeypatch):
    monkeypatch.setattr(handler_mod.blog_source, "list_blog_posts", lambda: list(POSTS))
    monkeypatch.setattr(
        handler_mod.blog_source,
        "get_blog_post_by_slug",
        lambda slug: next((dict(p) for p in POSTS if p["slug"] == slug), None),
    )


@pytest.mark.usefixtures("stub_native_blog")
class TestProjection:
    def test_no_fields_parameter_returns_every_field(self):
        body = json.loads(get("/prod/seo-tools/blog-public")["body"])
        assert set(body["posts"][0]) == set(POSTS[0])

    def test_fields_trims_the_payload(self):
        response = get(
            "/prod/seo-tools/blog-public",
            query={"fields": "slug,title,excerpt,category,publishedDate"},
        )
        body = json.loads(response["body"])
        assert set(body["posts"][0]) == {
            "slug", "title", "excerpt", "category", "publishedDate",
        }
        assert len(response["body"]) < 400

    def test_total_counts_the_whole_corpus(self):
        body = json.loads(
            get("/prod/seo-tools/blog-public", query={"fields": "slug"})["body"]
        )
        assert body["total"] == len(POSTS)

    def test_slug_is_always_included(self):
        body = json.loads(
            get("/prod/seo-tools/blog-public", query={"fields": "title"})["body"]
        )
        assert "slug" in body["posts"][0]

    def test_unknown_field_is_ignored(self):
        body = json.loads(
            get(
                "/prod/seo-tools/blog-public",
                query={"fields": "title,doesNotExist"},
            )["body"]
        )
        assert set(body["posts"][0]) == {"slug", "title"}

    def test_only_unknown_fields_fall_back_to_full_shape(self):
        body = json.loads(
            get("/prod/seo-tools/blog-public", query={"fields": "nope"})["body"]
        )
        assert set(body["posts"][0]) == set(POSTS[0])

    def test_allowlist_blocks_internal_fields(self):
        assert "content" not in handler_mod._PUBLIC_POST_FIELDS
        assert "richContent" not in handler_mod._PUBLIC_POST_FIELDS


@pytest.mark.usefixtures("stub_native_blog")
class TestConditionalRequests:
    def test_response_has_etag_and_cache_control(self):
        headers = get("/prod/seo-tools/blog-public")["headers"]
        assert headers["ETag"].startswith('"')
        assert "s-maxage" in headers["Cache-Control"]

    def test_matching_if_none_match_returns_304(self):
        first = get("/prod/seo-tools/blog-public")
        second = get(
            "/prod/seo-tools/blog-public",
            headers={"if-none-match": first["headers"]["ETag"]},
        )
        assert second["statusCode"] == 304
        assert second["body"] == ""

    def test_stale_etag_returns_full_body(self):
        response = get(
            "/prod/seo-tools/blog-public",
            headers={"if-none-match": '"outdated"'},
        )
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["ok"] is True

    def test_etag_tracks_projection(self):
        full = get("/prod/seo-tools/blog-public")["headers"]["ETag"]
        trimmed = get(
            "/prod/seo-tools/blog-public", query={"fields": "slug"}
        )["headers"]["ETag"]
        assert full != trimmed

    def test_vary_names_origin(self):
        assert "Origin" in get("/prod/seo-tools/blog-public")["headers"]["Vary"]


class TestNativeFailureSurface:
    def test_native_read_failure_is_503_not_empty_200(self, monkeypatch):
        def boom():
            raise RuntimeError("native blog read failed")
        monkeypatch.setattr(handler_mod.blog_source, "list_blog_posts", boom)
        response = get("/prod/seo-tools/blog-public")
        assert response["statusCode"] == 503
        body = json.loads(response["body"])
        assert body["ok"] is False
        assert body.get("posts") is None
        assert body.get("total") is None

    def test_missing_post_is_404(self, stub_native_blog):
        response = get("/prod/seo-tools/blog-public/no-such-post")
        assert response["statusCode"] == 404


class TestPublicSurfaceStaysNarrow:
    def test_only_get_reaches_public_branch(self):
        event = {
            "requestContext": {
                "http": {"method": "POST", "path": "/prod/seo-tools/blog-public"}
            },
            "headers": {"origin": "https://wecare.digital"},
            "body": "{}",
        }
        assert handler_mod.handler(event, None)["statusCode"] in (401, 403)

    def test_cache_purge_route_is_not_public(self):
        event = {
            "requestContext": {
                "http": {"method": "POST", "path": "/prod/seo-tools/cache-purge"}
            },
            "headers": {"origin": "https://wecare.digital"},
            "body": "{}",
        }
        assert handler_mod.handler(event, None)["statusCode"] in (401, 403)
