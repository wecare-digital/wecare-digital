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
        current_master = result["categories"][category]["masterKey"]
        current_prompt = result["categories"][category]["promptKey"]
        history_root = result["categories"][category]["masterHistoryRoot"]
        assert current_master in s3.objects
        assert current_prompt in s3.objects
        assert history_root + "master.json" in s3.objects
        assert history_root + "editorial-master.md" in s3.objects
        assert history_root + "quality-policy.json" in s3.objects

    conversations_prompt = s3.objects[
        "secure/blog-production/02-masters/conversations/current/editorial-master.md"
    ].decode()
    assert len(conversations_prompt) > 20000
    assert "Bulk lowering of standards is not." in conversations_prompt

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
    assert all(row["articleWorkId"].startswith("blogwork_")
               for row in result["createdIntents"])
    work_rows = [row for row in table.items.values()
                 if row.get("recordType") == "blogArticleWork"]
    assert len(work_rows) == 2
    assert {row["parentSourceId"] for row in work_rows} == {source_id}
    assert result["dedupeReportKey"] in s3.objects
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



def _two_intent_manifest(bp, source_id):
    return bp.submit_manifest({
        "category": "Conversations",
        "sourceId": source_id,
        "potentialCount": 2,
        "intents": [
            {
                "title": "Integrity Without Moral Verdict",
                "centralDistinction": "Integrity can be examined through completeness before moral judgement.",
                "readerPromise": "Notice what remains incomplete without turning the event into identity.",
                "distinctPurpose": "Separates practical completeness from a verdict about character.",
            },
            {
                "title": "The Moment a Promise Changes",
                "centralDistinction": "A commitment can become unworkable before the deadline visibly fails.",
                "readerPromise": "Notice the earlier moment when changed reality needs to enter conversation.",
                "distinctPurpose": "Examines the disclosure moment rather than promise repair after failure.",
            },
        ],
    }, "editor")


def test_one_source_creates_independent_article_work_children(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")
    manifest = _two_intent_manifest(bp, source_id)

    first, second = manifest["createdIntents"]
    assert first["articleWorkId"] != second["articleWorkId"]
    first_work = table.items[first["articleWorkId"]]
    second_work = table.items[second["articleWorkId"]]
    assert first_work["parentSourceId"] == source_id
    assert second_work["parentSourceId"] == source_id
    assert first_work["draftRecord"]["contentMarkdown"] == ""
    assert second_work["draftRecord"]["contentMarkdown"] == ""


def test_chatgpt_article_write_bridges_into_the_existing_qa_record_shape(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")
    manifest = _two_intent_manifest(bp, source_id)
    intent = manifest["createdIntents"][0]

    saved = bp.save_article({
        "category": "Conversations",
        "intentId": intent["intentId"],
        "status": "DRAFTED",
        "article": {
            "title": "Integrity Without Moral Verdict",
            "slug": "integrity-without-moral-verdict",
            "contentMarkdown": (
                "A commitment can fail without settling the question of character. " * 90
            ),
            "seoTitle": "Integrity Without Moral Verdict | WECARE.DIGITAL",
            "metaDescription": (
                "An inquiry into what becomes incomplete when a commitment breaks, "
                "before the event is turned into a judgement about character."
            ),
            "tags": ["Integrity", "Workability"],
            "articleType": "ARTICLE",
            "centralDistinction": (
                "Integrity can be examined through completeness before moral judgement."
            ),
            "distinctPurpose": (
                "Separates practical completeness from a verdict about character."
            ),
            # These must be ignored by the ChatGPT editorial whitelist.
            "sourceReviewedFully": "YES",
            "gate": {"VOICE": "PASS"},
        },
    }, "editor")

    child = bs.get_source(saved["articleWorkId"])
    assert child["recordType"] == "blogArticleWork"
    assert child["draftRecord"]["contentMarkdown"]
    assert child["draftRecord"].get("sourceReviewedFully", "") == ""
    assert "gate" not in child["draftRecord"]
    assert table.items[intent["intentId"]]["status"] == "DRAFTED"


def test_chatgpt_cannot_write_protected_publish_states(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")
    intent = _two_intent_manifest(bp, source_id)["createdIntents"][0]

    with pytest.raises(ValueError, match="ChatGPT article writes may use only"):
        bp.save_article({
            "category": "Conversations",
            "intentId": intent["intentId"],
            "status": "PUBLISHED",
            "article": {"contentMarkdown": "This body must never become published by this route."},
        }, "editor")


def test_source_completion_means_writing_complete_not_human_review(prod):
    bp, bs, storage, table, s3 = prod
    bp.initialize("admin")
    source_id = _source(table)
    bp.claim_next_source("Conversations", "editor")
    manifest = _two_intent_manifest(bp, source_id)

    # A status label alone cannot close the parent: both article children still have no body.
    for row in manifest["createdIntents"]:
        table.items[row["articleWorkId"]]["editorialStatus"] = "HUMAN_REVIEW"
        table.items[row["intentId"]]["status"] = "HUMAN_REVIEW"
    with pytest.raises(ValueError, match="not drafted or held"):
        bp.complete_source("Conversations", source_id, "editor")

    for row in manifest["createdIntents"]:
        bp.save_article({
            "category": "Conversations",
            "intentId": row["intentId"],
            "status": "DRAFTED",
            "article": {
                "title": row["title"],
                "contentMarkdown": "A complete independent article body. " * 100,
            },
        }, "editor")

    completed = bp.complete_source("Conversations", source_id, "editor")
    assert completed["completion"] == "ARTICLE_PRODUCTION_COMPLETE"
    assert table.items[source_id]["editorialStatus"] == "ARTICLE_PRODUCTION_COMPLETE"
    assert bp.get_control("Conversations")["currentSourceId"] == ""
    assert all(table.items[row["articleWorkId"]]["pipeline"]["verifyStatus"] == ""
               for row in manifest["createdIntents"])
