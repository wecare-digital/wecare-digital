"""Pure regression tests for the AWS-native SEO blog deployment smoke."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "verify_seo_blog_lambda_native",
    ROOT / "scripts" / "verify_seo_blog_lambda_native.py",
)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def fake_invoker(*, count=1421, reported=None, duplicate=False,
                 missing_body=False):
    posts = [{"slug": f"post-{i}", "title": f"Title {i}"} for i in range(count)]
    if duplicate and posts:
        posts[-1]["slug"] = posts[0]["slug"]

    def invoke(event):
        path = event["rawPath"]
        if path == "/seo-tools/blog-public":
            return {"ok": True, "posts": posts,
                    "total": count if reported is None else reported}
        slug = path.rsplit("/", 1)[-1]
        return {"ok": True, "post": {
            "slug": slug,
            "content": "" if missing_body else ("AWS-native body " * 15),
            "seoTitle": f"SEO {slug}",
        }}
    return invoke


def test_all_1421_slugs_have_complete_native_list():
    result = smoke.verify_blog(fake_invoker())
    assert result["status"] == "PASS"
    assert result["published_posts"] == 1421
    assert len(result["sample_posts"]) == 3


def test_paginated_500_post_regression_is_refused():
    with pytest.raises(AssertionError, match="truncated"):
        smoke.verify_blog(fake_invoker(count=500))


def test_total_mismatch_refused():
    with pytest.raises(AssertionError, match="total mismatch"):
        smoke.verify_blog(fake_invoker(reported=1421 + 500))


def test_duplicate_slug_refused():
    with pytest.raises(AssertionError, match="duplicate slugs"):
        smoke.verify_blog(fake_invoker(duplicate=True))


def test_missing_article_content_refused():
    with pytest.raises(AssertionError, match="body missing"):
        smoke.verify_blog(fake_invoker(missing_body=True))


def test_allows_an_expected_publish_count_to_grow():
    result = smoke.verify_blog(fake_invoker(count=1500))
    assert result["published_posts"] == 1500
