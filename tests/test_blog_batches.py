"""Batches, and the two scale limits that made "thousands per batch" untrue.

THE POINT OF THIS FILE.

The specification asks for a batch holding thousands of independently tracked records, and
for every total to be derived from those records rather than from a counter. Two things stood
in the way, both of which failed silently while reporting plausible numbers:

  storage.list_records clamps to min(max(limit, 1), 500).
      - blog_sources.status_report read through it, so a 2,500-source batch reported on 500.
      - pending_sources read through it, so the worker stopped finding work past 500 while
        returning `remaining: 0` - the worst possible way for a queue to fail.

  blog_sources._view briefly carried extractPreview, 1,500 characters per row.
      - 2,500 rows is a 3.75 MB response for a table showing a status column.

`test_a_rollup_sees_past_the_500_item_ceiling` and
`test_the_worker_finds_work_past_the_500_item_ceiling` are the two that would have caught
them. They build 600 records deliberately, because 500 is where the behaviour changes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blog_quality_v2 as q  # noqa: E402
from test_blog_sources import (  # noqa: E402
    FakeLambda, FakeS3, FakeTable, _pdf_entry, sample_pdf,
)


@pytest.fixture()
def env(monkeypatch):
    import blog_batches as bb
    import blog_draft as bd
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    return {"table": table, "s3": s3, "lambda": lam, "bs": bs, "bb": bb, "bd": bd,
            "storage": storage}


def _batch(env, **overrides) -> str:
    body = {"name": "Wave 1", "defaultCategory": "Conversations"}
    body.update(overrides)
    return env["bb"].create(body, "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]


def _register(env, batch_id: str, payload: bytes, name: str = "a.pdf") -> str:
    result = env["bs"].register(
        {"batchId": batch_id, "sources": [_pdf_entry(payload, name)]},
        "admin", q.CATEGORIES)
    entry = result["sources"][0]
    key = env["table"].items[entry["sourceId"]]["s3Key"]
    env["s3"].objects[key] = payload
    env["bs"].confirm({"sourceIds": [entry["sourceId"]]}, "admin")
    return entry["sourceId"]


# ── Creation and validation ─────────────────────────────────────────────────────

def test_a_batch_is_created_with_its_defaults(env):
    batch_id = _batch(env, description="The first wave", tags=["integrity"])
    record = env["bb"].get(batch_id)
    assert record["name"] == "Wave 1"
    assert record["defaultCategory"] == "Conversations"
    assert record["articleClass"] == "ARCHIVE_DERIVED"
    assert record["status"] == env["bb"].OPEN
    assert record["createdBy"] == "admin"


def test_a_batch_carries_its_own_id_as_its_slug(env):
    """`storage.put_record` requires `slug` because the slug GSI keys on it."""
    batch_id = _batch(env)
    assert env["bb"].get(batch_id)["slug"] == batch_id


@pytest.mark.parametrize("body,message", [
    ({"name": "", "defaultCategory": "Conversations"}, "name is required"),
    ({"name": "x" * 200, "defaultCategory": "Conversations"}, "at most"),
    ({"name": "W", "defaultCategory": "Insights"}, "defaultCategory"),
    ({"name": "W", "defaultCategory": "Conversations", "articleClass": "NEW"},
     "articleClass"),
    ({"name": "W", "defaultCategory": "Conversations",
      "tags": [f"t{n}" for n in range(20)]}, "batch tags"),
])
def test_creation_validates(env, body, message):
    with pytest.raises(ValueError, match=message):
        env["bb"].create(body, "admin", q.CATEGORIES, q.ARTICLE_CLASSES)


def test_only_the_two_categories_are_accepted(env):
    assert q.CATEGORIES == ("Conversations", "Gastronomy")
    for category in q.CATEGORIES:
        assert _batch(env, name=f"W {category}", defaultCategory=category)


# ── Rollups are derived, never stored ───────────────────────────────────────────

def test_a_new_batch_rolls_up_to_zero(env):
    report = env["bb"].rollup(_batch(env))
    assert report["sources"] == 0
    assert report["complete"] is False
    assert "no sources registered" in report["note"]


def test_the_rollup_is_derived_from_the_source_records(env):
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    _register(env, batch_id, sample_pdf("TWO"), name="b.pdf")

    report = env["bb"].rollup(batch_id)
    assert report["sources"] == 2
    assert report["bySourceStatus"]["UPLOADED"] == 2
    assert report["pending"] == 2
    assert report["complete"] is False

    env["bs"].run_worker({})
    report = env["bb"].rollup(batch_id)
    assert report["extracted"] == 2
    assert report["pending"] == 0
    assert report["complete"] is True
    assert report["words"] > 0


def test_no_counter_attribute_is_stored_on_the_batch(env):
    """A counter and the records it counts drift apart exactly when they must agree.

    A worker that dies after writing the source status but before incrementing the batch
    leaves a batch reading 2,499 of 2,500 forever, and re-running does not fix it because an
    increment is not idempotent.
    """
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    item = env["table"].items[batch_id]
    for forbidden in ("sourceCount", "extractedCount", "failedCount", "pendingCount",
                      "count", "total"):
        assert forbidden not in item, forbidden


def test_the_rollup_reports_both_axes(env):
    """Source status and article status answer different questions and get confused."""
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    report = env["bb"].rollup(batch_id)
    assert report["bySourceStatus"]["EXTRACTED"] == 1
    # The document is extracted; the ARTICLE has not been written.
    assert report["byArticleStatus"]["SOURCE_REVIEW"] == 1


def test_complete_does_not_mean_published(env):
    """Section 38: processing completion must never automatically mean publishing."""
    batch_id = _batch(env)
    source_id = _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    assert env["bb"].rollup(batch_id)["complete"] is True
    record = env["bs"].get_source(source_id)
    assert record["articleStatus"] == "SOURCE_REVIEW"
    assert q.assess(record["draftRecord"])["readyToPublish"] is False


def test_a_failed_source_counts_as_terminal_not_pending(env):
    batch_id = _batch(env)
    from blog_pdf_fixture import make_pdf
    _register(env, batch_id, make_pdf([["x"], ["y"]]))
    env["bs"].run_worker({})
    report = env["bb"].rollup(batch_id)
    assert report["failed"] == 1
    assert report["pending"] == 0
    assert report["complete"] is True


# ── Batch status follows its children ───────────────────────────────────────────

def test_status_moves_open_to_ingesting_to_ready(env):
    batch_id = _batch(env)
    assert env["bb"].refresh_status(batch_id) == env["bb"].OPEN
    _register(env, batch_id, sample_pdf("ONE"))
    assert env["bb"].refresh_status(batch_id) == env["bb"].INGESTING
    env["bs"].run_worker({})
    assert env["bb"].get(batch_id)["status"] == env["bb"].READY


def test_the_worker_refreshes_the_batch_it_touched(env):
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    assert env["bb"].get(batch_id)["status"] == env["bb"].READY


def test_the_displayed_status_is_derived_not_read(env):
    """A live 13-source fan-out reported every source EXTRACTED with the batch on INGESTING.

    `refresh_status` reads the rollup through a global secondary index, which is eventually
    consistent and cannot be read consistently - so the refresh firing immediately after the last
    source's write can still see it as unfinished, store INGESTING, and never run again. Anything
    that shows a rollup derives the status from that rollup instead, which cannot be stale because
    it is the number the caller just read.
    """
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    # Simulate the refresh having observed a lagging index.
    env["table"].items[batch_id]["status"] = env["bb"].INGESTING

    assert env["bb"].detail(batch_id)["status"] == env["bb"].READY
    assert env["bb"].detail(batch_id)["storedStatus"] == env["bb"].INGESTING
    listed = env["bb"].list_batches()[0]
    assert listed["status"] == env["bb"].READY
    assert listed["storedStatus"] == env["bb"].INGESTING


def test_the_cheap_listing_keeps_the_stored_status(env):
    """`?rollup=none` skips the index query, so there is nothing to derive from and the cached
    value is the only answer available. Reporting it as such is honest."""
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    env["table"].items[batch_id]["status"] = env["bb"].INGESTING
    listed = env["bb"].list_batches(with_rollup=False)[0]
    assert listed["status"] == env["bb"].INGESTING
    assert "rollup" not in listed


def test_a_closed_batch_is_never_derived_open_again(env):
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bb"].close(batch_id, "admin")
    assert env["bb"].detail(batch_id)["status"] == env["bb"].CLOSED
    assert env["bb"].derive_status(env["bb"].get(batch_id),
                                  env["bb"].rollup(batch_id)) == env["bb"].CLOSED


def test_closing_is_not_overwritten_by_a_refresh(env):
    """CLOSED is an operator decision; a late source must not silently reopen it."""
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bb"].close(batch_id, "admin")
    assert env["bb"].refresh_status(batch_id) == env["bb"].CLOSED


def test_closing_twice_is_reported_not_an_error(env):
    batch_id = _batch(env)
    env["bb"].close(batch_id, "admin")
    assert env["bb"].close(batch_id, "admin")["alreadyClosed"] is True


def test_a_closed_batch_refuses_further_sources(env):
    """Otherwise a rollup changes after an operator deliberately finished with it."""
    batch_id = _batch(env)
    env["bb"].close(batch_id, "admin")
    with pytest.raises(ValueError, match="closed"):
        env["bs"].register({"batchId": batch_id,
                            "sources": [_pdf_entry(sample_pdf("ONE"))]},
                           "admin", q.CATEGORIES)


def test_an_unknown_batch_is_refused_at_registration(env):
    with pytest.raises(LookupError, match="Unknown batchId"):
        env["bs"].register({"batchId": "blogbatch_nope",
                            "sources": [_pdf_entry(sample_pdf("ONE"))]},
                           "admin", q.CATEGORIES)


def test_refresh_and_close_reject_an_unknown_batch(env):
    with pytest.raises(LookupError):
        env["bb"].refresh_status("blogbatch_nope")
    with pytest.raises(LookupError):
        env["bb"].close("blogbatch_nope", "admin")


# ── Batch defaults flow into a source ───────────────────────────────────────────

def test_a_source_inherits_the_batch_defaults(env):
    batch_id = _batch(env, defaultCategory="Gastronomy", articleClass="ORIGINAL_109")
    source_id = _register(env, batch_id, sample_pdf("ONE"))
    record = env["bs"].get_source(source_id)
    assert record["category"] == "Gastronomy"
    assert record["articleClass"] == "ORIGINAL_109"
    assert record["batchId"] == batch_id


def test_an_explicit_category_overrides_the_batch_default(env):
    batch_id = _batch(env, defaultCategory="Gastronomy")
    result = env["bs"].register(
        {"batchId": batch_id, "category": "Conversations",
         "sources": [_pdf_entry(sample_pdf("ONE"))]}, "admin", q.CATEGORIES)
    record = env["bs"].get_source(result["sources"][0]["sourceId"])
    assert record["category"] == "Conversations"


def test_a_source_with_no_batch_gets_the_sentinel_not_an_empty_string(env):
    """DynamoDB omits an item from a GSI when its partition key is absent or empty.

    An unbatched source with `batchId: ""` would be invisible to every batch-index query,
    including the worker's - so the sentinel is what keeps it findable.
    """
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(sample_pdf("ONE"))]},
        "admin", q.CATEGORIES)
    record = env["bs"].get_source(result["sources"][0]["sourceId"])
    assert record["batchId"] == env["bs"].NO_BATCH
    assert record["batchId"] != ""


# ── The 500-item ceiling, which is where both bugs lived ────────────────────────

def _bulk_sources(env, batch_id: str, count: int, status: str = "UPLOADED") -> None:
    """Write records straight to the fake table; 600 real PDFs would take minutes."""
    for index in range(count):
        record_id = f"blogsrc_{index:064x}"
        env["table"].items[record_id] = {
            "id": record_id, "recordType": env["bs"].RECORD_TYPE,
            "createdAt": f"2026-09-29T00:{index // 60:02d}:{index % 60:02d}+00:00",
            "updatedAt": "2026-09-29T00:00:00+00:00",
            "slug": record_id, "batchId": batch_id, "sourceType": "pdf",
            "sourceRef": f"doc-{index}.pdf", "sourceSha256": f"{index:064x}",
            "s3Key": env["bs"].PREFIX + f"{index:064x}.pdf",
            "category": "Conversations", "articleClass": "ARCHIVE_DERIVED",
            "status": status, "extractedWords": 100, "error": "",
        }


def test_a_rollup_sees_past_the_500_item_ceiling(env):
    """`storage.list_records` clamps at 500, and `status_report` used to read through it.

    600 is chosen because 500 is exactly where the old behaviour changed - and where it
    reported a plausible number rather than an error.
    """
    batch_id = _batch(env)
    _bulk_sources(env, batch_id, 600)
    report = env["bb"].rollup(batch_id)
    assert report["sources"] == 600, f"saw only {report['sources']}"
    assert report["bySourceStatus"]["UPLOADED"] == 600


def test_the_worker_finds_work_past_the_500_item_ceiling(env):
    """Past 500 the worker used to report `remaining: 0` with work outstanding."""
    batch_id = _batch(env)
    _bulk_sources(env, batch_id, 600)
    assert len(env["bs"].pending_sources()) == 600


def test_the_status_report_is_uncapped_by_default(env):
    batch_id = _batch(env)
    _bulk_sources(env, batch_id, 600)
    assert env["bs"].status_report()["total"] == 600


def test_limited_status_report_keeps_exact_totals(env):
    batch_id = _batch(env)
    _bulk_sources(env, batch_id, 600)
    report = env["bs"].status_report(limit=100)
    assert report["total"] == 600
    assert report["shown"] == 100
    assert report["truncated"] is True
    assert len(report["sources"]) == 100
    assert report["byStatus"]["UPLOADED"] == 600


def test_the_status_report_can_be_scoped_to_one_batch(env):
    """Scoped through the batch index, not by reading every source in the system."""
    first = _batch(env, name="Wave 1")
    second = _batch(env, name="Wave 2")
    _bulk_sources(env, first, 5)
    env["table"].items["blogsrc_other"] = {
        "id": "blogsrc_other", "recordType": env["bs"].RECORD_TYPE,
        "createdAt": "2026-09-29T01:00:00+00:00", "slug": "blogsrc_other",
        "batchId": second, "sourceType": "pdf", "sourceRef": "other.pdf",
        "status": "UPLOADED", "category": "Conversations",
    }
    assert env["bs"].status_report(batch_id=first)["total"] == 5
    assert env["bs"].status_report(batch_id=second)["total"] == 1
    assert env["bs"].status_report()["total"] == 6


def test_batch_sources_are_returned_oldest_first(env):
    """A work queue drains oldest-first; `list_records` sorts the other way for logs."""
    batch_id = _batch(env)
    _bulk_sources(env, batch_id, 10)
    rows = env["bb"].batch_sources(batch_id)
    assert [row["createdAt"] for row in rows] == sorted(row["createdAt"] for row in rows)


# ── The listing projection stays compact ────────────────────────────────────────

def test_the_list_view_carries_neither_the_extract_nor_its_preview(env):
    """2,500 rows at a 1,500-character preview is 3.75 MB for a status table."""
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    row = env["bs"].status_report(batch_id=batch_id)["sources"][0]
    assert "sourceExtract" not in row
    assert "extractPreview" not in row
    assert "draftRecord" not in row


def test_the_detail_view_still_carries_both(env):
    batch_id = _batch(env)
    source_id = _register(env, batch_id, sample_pdf("ONE"))
    env["bs"].run_worker({})
    detail = env["bs"].source_detail(source_id)
    assert detail["sourceExtract"]
    assert detail["extractPreview"]
    assert detail["draftRecord"]


def _deploy_module(alias: str):
    """Load the deploy script as a module. It is not importable by name (hyphens, and it is
    a script), and these tests read its index definition rather than a copy of it - a copy is
    a second source of truth that drifts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        alias, ROOT / "scripts" / "deploy_seo_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_batch_index_projects_everything_the_view_needs():
    """A field in `_view` that the GSI does not project reads as EMPTY for batch queries
    while working everywhere else - a defect that only surfaces on the batches page."""
    module = _deploy_module("dep_seo")
    projected = set(module.BATCH_INDEX_DEFINITION["Projection"]["NonKeyAttributes"])
    projected |= {"batchId", "createdAt", "id"}

    import blog_sources as bs
    needed = set(bs.view({}).keys())
    # `sourceId` is the item's `id`, and `sourceUrl` is derived from `s3Key`.
    needed = (needed - {"sourceId", "sourceUrl"}) | {"id", "s3Key"}
    missing = needed - projected
    assert missing == set(), f"not projected into {module.BATCH_INDEX_NAME}: {missing}"


def test_the_batch_index_respects_the_twenty_attribute_cap():
    """DynamoDB refuses an index projecting more than 20 non-key attributes.

    This is here because the first version of the index asked for 24 and was refused by
    `UpdateTable`, not by anything in this suite - so the constraint was discovered at deploy
    time against the live table, with the GSI half-requested. A limit that only a deploy can
    tell you about is a limit worth asserting locally.

    The cap is per index. There is a second, separate cap of 100 projected attributes across
    all of a table's indexes, which this table is nowhere near.
    """
    module = _deploy_module("dep_seo_cap")
    projected = module.BATCH_INDEX_DEFINITION["Projection"]["NonKeyAttributes"]
    assert module.MAX_INDEX_NON_KEY_ATTRIBUTES == 20
    assert len(projected) <= 20, f"{len(projected)} attributes; DynamoDB allows 20"
    assert len(set(projected)) == len(projected), "a duplicate spends a slot for nothing"
    # An index key or the table key would be rejected as a non-key attribute.
    for key in ("id", "batchId", "createdAt"):
        assert key not in projected, key


def test_the_index_projects_include_rather_than_all():
    """ALL would copy extractPreview and draftRecord into the index for data no listing
    renders, roughly doubling storage on the hottest record type."""
    module = _deploy_module("dep_seo2")
    projection = module.BATCH_INDEX_DEFINITION["Projection"]
    assert projection["ProjectionType"] == "INCLUDE"
    for heavy in ("extractPreview", "draftRecord", "aiDraft", "sourceExtract"):
        assert heavy not in projection["NonKeyAttributes"], heavy


# ── Listing ─────────────────────────────────────────────────────────────────────

def test_listing_batches_includes_rollups_by_default(env):
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    listed = env["bb"].list_batches()
    assert listed[0]["batchId"] == batch_id
    assert listed[0]["rollup"]["sources"] == 1


def test_listing_can_skip_the_rollup(env):
    """A real cost switch: each rollup pages that batch's sources."""
    _batch(env)
    assert "rollup" not in env["bb"].list_batches(with_rollup=False)[0]


def test_detail_returns_the_batch_its_rollup_and_its_sources(env):
    batch_id = _batch(env)
    _register(env, batch_id, sample_pdf("ONE"))
    detail = env["bb"].detail(batch_id)
    assert detail["batchId"] == batch_id
    assert detail["rollup"]["sources"] == 1
    assert len(detail["sources"]) == 1


def test_detail_rejects_an_unknown_batch(env):
    with pytest.raises(LookupError):
        env["bb"].detail("blogbatch_nope")


def test_active_batch_ids_excludes_closed_ones(env):
    open_batch = _batch(env, name="Open")
    closed_batch = _batch(env, name="Closed")
    _register(env, open_batch, sample_pdf("ONE"))
    env["bb"].close(closed_batch, "admin")
    active = env["bb"].active_batch_ids()
    assert open_batch in active
    assert closed_batch not in active
