"""Contracts for the S3 blog catalog index and internal production master."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))

from test_blog_sources import FakeS3  # noqa: E402


def test_sync_writes_public_catalog_and_secure_master(monkeypatch):
    import blog_catalog
    import blog_sources
    import storage

    s3 = FakeS3()
    monkeypatch.setattr(blog_sources, "s3_client", lambda: s3)
    monkeypatch.setattr(blog_sources, "BUCKET", "wecare-digital-get")
    monkeypatch.setattr(storage, "list_blog_posts", lambda **kwargs: [
        {
            "id": "blog_1", "slug": "one", "title": "One", "excerpt": "Public",
            "category": "Conversations", "tags": ["attention"],
            "publishedDate": "2026-10-15T00:00:00Z", "modifiedDate": "",
            "url": "https://wecare.digital/post/one",
        },
        {
            "id": "blog_2", "slug": "two", "title": "Two", "excerpt": "Food",
            "category": "Gastronomy", "tags": ["recipe"],
            "publishedDate": "2026-10-15T00:00:00Z", "modifiedDate": "",
            "url": "https://wecare.digital/post/two",
        },
    ])

    rows = {
        "blogSource": [
            {"id": "s1", "category": "Conversations", "status": "EXTRACTED",
             "articleStatus": "EDITORIAL_QA", "pipeline": {"publishStatus": ""}},
            {"id": "s2", "category": "Gastronomy", "status": "EXTRACTED",
             "articleStatus": "READY_TO_PUBLISH", "pipeline": {"publishStatus": "QUEUED"}},
        ],
        "blogPublishJob": [{"id": "j1"}],
        "blogBatch": [{"id": "b1"}],
    }
    monkeypatch.setattr(storage, "scan_by_record_type",
                        lambda record_type, **kwargs: rows.get(record_type, []))

    result = blog_catalog.sync()
    assert result["unlimitedBulk"] is True
    assert blog_catalog.CATALOG_INDEX_KEY in s3.objects
    assert blog_catalog.PRODUCTION_MASTER_KEY in s3.objects
    assert blog_catalog.CATALOG_INDEX_KEY.startswith("o/blog-production/")
    assert blog_catalog.PRODUCTION_MASTER_KEY.startswith("secure/blog-production/")

    catalog = json.loads(s3.objects[blog_catalog.CATALOG_INDEX_KEY])
    assert catalog["count"] == 2
    assert catalog["categories"] == {"Conversations": 1, "Gastronomy": 1}
    assert all("sourceRef" not in post and "sourceHash" not in post
               for post in catalog["posts"])

    master = json.loads(s3.objects[blog_catalog.PRODUCTION_MASTER_KEY])
    assert set(master["governedCategories"]) == {"Conversations", "Gastronomy"}
    assert master["masterPolicies"]["Conversations"]["centralDistinctionRequired"] is True
    assert master["masterPolicies"]["Gastronomy"]["sourceProfileRequired"] is True
    assert master["masterPolicies"]["Gastronomy"]["editorialManifestMaxArticles"] == 150


def test_published_post_mirror_contains_no_internal_provenance(monkeypatch):
    import blog_catalog
    import blog_sources

    s3 = FakeS3()
    monkeypatch.setattr(blog_sources, "s3_client", lambda: s3)
    monkeypatch.setattr(blog_sources, "BUCKET", "wecare-digital-get")
    record = {
        "id": "blogsrc_secret", "category": "Conversations",
        "sourceRef": "private-book.pdf", "sourceSha256": "a" * 64,
    }
    draft = {
        "slug": "attention-and-choice", "title": "Attention and Choice",
        "contentMarkdown": "Independent public article.", "tags": ["attention"],
        "sourceHash": "b" * 64, "sourceFile": "private-book.pdf",
    }
    key = blog_catalog.write_published_post(
        record, draft, {"postId": "blog_1", "postUrl": "https://wecare.digital/post/attention-and-choice"},
        "operator")
    payload = json.loads(s3.objects[key])
    assert key == "o/blog-production/posts/attention-and-choice.json"
    assert payload["category"] == "Conversations"
    for forbidden in ("sourceRef", "sourceHash", "sourceFile", "sourceId", "qaRunId"):
        assert forbidden not in payload


def test_both_production_master_policies_keep_bulk_quality_gated():
    import blog_catalog

    for category in blog_catalog.GOVERNED_CATEGORIES:
        policy = blog_catalog.MASTER_POLICIES[category]
        assert policy["qualityOverSpeed"] is True
        assert policy["bulkAllowed"] is True
        assert policy["humanGateRequired"] is True
        assert policy["autoPublish"] is False
        assert policy["postPublishReadbackRequired"] is True
