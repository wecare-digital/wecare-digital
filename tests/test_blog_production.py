"""Contracts for the zero-paid-AI blog production state backend."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_blog_sources import FakeS3, FakeTable  # noqa: E402


@pytest.fixture()
def prod(monkeypatch):
    import blog_production
    import blog_sources
    import storage

    table = FakeTable()
    s3 = FakeS3()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(blog_sources, "s3_client", lambda: s3)
    monkeypatch.setattr(blog_sources, "BUCKET", "wecare-digital-get")
    return blog_production, blog_sources, storage, table, s3


def _source(table, category="Conversations", source_id="blogsrc_demo"):
    table.items[source_id] = {
        "id": source_id,
        "recordType": "blogSource",
        "createdAt": "2026-10-15T00:00:00+00:00",
        "updatedAt": "2026-10-15T00:00:00+00:00",
        "slug": source_id,
        "batchId": "blogbatch_demo",
        "sourceType": "url",
        "sourceRef": "https://example.com/source",
        "s3Key": "",
        "extractKey": "",
        "status": "EXTRACTED",
        "category": category,
        "articleClass": "ARCHIVE_DERIVED",
        "editorialStatus": "PENDING_EDITORIAL",
        "pipeline": {},
    }
    return source_id


def test_initialize_creates_two_controls_and_four_area_contract(prod):
    bp, bs, storage, table, s3 = prod
    result = bp.initialize("admin")

    assert result["aiMode"] == "CHATGPT_EXTERNAL"
    assert result["paidAiBackend"] is False
    assert set(result["categories"]) == {"Conversations", "Gastronomy"}

    for category, slug in (("Conversations", "conversations"), ("Gastronomy", "gastronomy")):
        control = storage.get_typed(bp.control_id(category), bp.CONTROL_RECORD_TYPE)
        assert control["category"] == category
        assert control["aiBackendEnabled"] is False
        assert control["autoPublish"] is False

        assert f"secure/blog-production/02-masters/{slug}/master-current.json" in s3.objects
        assert f"secure/blog-production/02-masters/{slug}/prompt-current.md" in s3.objects
        assert f"secure/blog-production/02-masters/{slug}/quality-policy.json" in s3.objects
        assert f"secure/blog-production/04-checkpoints/{slug}/current.json" in s3.objects

    assert bs.category_source_prefix("Conversations") == (
        "secure/blog-production/01-sources/conversations/")
    assert bs.category_source_prefix("Gastronomy") == (
        "secure/blog-production/01-sources/gastronomy/")


def test_claim_next_source_is_one_lane_per_category(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    first = _source(table, "Conversations", "blogsrc_first")
    _source(table, "Conversations", "blogsrc_second")

    claimed = bp.claim_next_source("Conversations", "editor")
    assert claimed["claimed"] is True
    assert claimed["source"]["sourceId"] == first

    again = bp.claim_next_source("Conversations", "another-editor")
    assert again["claimed"] is False
    assert again["source"]["sourceId"] == first
    assert again["note"] == "existing source resumed"


def test_manifest_reports_counts_and_reserves_net_new_intents(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")

    result = bp.submit_manifest({
        "category": "Conversations",
        "sourceId": source_id,
        "potentialCount": 5,
        "duplicateCount": 2,
        "rejectedCount": 1,
        "intents": [
            {
                "title": "Integrity as Workability",
                "centralDistinction": "Integrity can be examined as wholeness and completeness.",
                "readerPromise": "See how missing integrity changes what can work.",
                "distinctPurpose": "Separate workability from moral judgement.",
            },
            {
                "title": "The Cost of an Unkept Word",
                "centralDistinction": "An unkept word changes the structure others are relying on.",
                "readerPromise": "Notice the practical cost of a broken commitment.",
                "distinctPurpose": "Examine downstream consequences rather than blame.",
            },
        ],
    }, "editor")

    assert result["counts"]["potential"] == 5
    assert result["counts"]["duplicate"] == 2
    assert result["counts"]["rejected"] == 1
    assert result["counts"]["netNewReserved"] == 2
    assert len(result["createdIntents"]) == 2
    assert table.items[source_id]["editorialStatus"] == "SAMPLE_REQUIRED"
    assert table.items[source_id]["netNewArticleCount"] == 2
    assert result["manifestKey"] in s3.objects


def test_sample_approval_unlocks_prompt_version_not_auto_publish(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")
    manifest = bp.submit_manifest({
        "category": "Conversations",
        "sourceId": source_id,
        "intents": [{
            "centralDistinction": "Integrity can be examined as wholeness and completeness.",
            "readerPromise": "See how integrity changes workability in ordinary commitments.",
            "distinctPurpose": "Separate integrity from moral judgement.",
        }],
    }, "editor")
    intent_id = manifest["createdIntents"][0]["intentId"]

    sample = bp.save_sample({
        "category": "Conversations",
        "sourceId": source_id,
        "intentId": intent_id,
        "article": {"title": "Sample", "contentMarkdown": "A sufficiently complete sample body."},
    }, "editor")
    assert sample["status"] == "SAMPLE_PENDING"

    approved = bp.approve_sample({
        "category": "Conversations",
        "sourceId": source_id,
        "intentId": intent_id,
        "approved": True,
    }, "owner")
    control = bp.get_control("Conversations")
    assert approved["approved"] is True
    assert control["approvedPromptVersion"] == bp.PROMPT_VERSIONS["Conversations"]
    assert control["autoPublish"] is False


def test_resume_is_a_complete_new_session_bookmark(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")

    resume = bp.resume("Conversations")
    assert resume["aiMode"] == "CHATGPT_EXTERNAL"
    assert resume["paidAiBackend"] is False
    assert resume["autoPublish"] is False
    assert resume["control"]["currentSourceId"] == source_id
    assert resume["checkpoint"]["sourceId"] == source_id
    assert resume["checkpoint"]["nextAction"] == "READ_FULL_SOURCE_AND_BUILD_MANIFEST"
    assert resume["masterKey"].startswith("secure/blog-production/02-masters/conversations/")
    assert resume["checkpointKey"].startswith(
        "secure/blog-production/04-checkpoints/conversations/")
