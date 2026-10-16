"""Source analysis: evidence, versioning, and the one field only a human can write.

THE TWO TESTS THAT MATTER MOST.

`test_analysing_never_writes_the_review_answer` is the integrity boundary. Section 2 of the
quality standard - an article may not be built from a title or an excerpt - is enforced by
`sourceReviewedFully`, and the whole value of this module is that producing evidence and
claiming to have read it are separate operations. If `analyse()` ever set that field, the
pipeline would certify its own reading and section 2 would be decoration.

`test_a_signoff_is_refused_after_the_text_moves` is the other. A reviewer signs against a
named analysis version; a re-extraction that changes the text invalidates the reading rather
than inheriting it. Without this, re-uploading a corrected PDF silently keeps a sign-off for
text nobody saw.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blog_quality_v2 as q  # noqa: E402
from blog_pdf_fixture import make_pdf, wrap  # noqa: E402
from test_blog_sources import (  # noqa: E402
    FakeLambda, FakeS3, FakeTable, _pdf_entry,
)

DISTINCTION = ("The source separates a broken agreement from a broken person, which is the "
               "distinction a reader can act on.")


@pytest.fixture()
def env(monkeypatch):
    import blog_analysis as ba
    import blog_batches as bb
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    return {"table": table, "s3": s3, "ba": ba, "bb": bb, "bs": bs, "storage": storage}


PROSE = [
    "A person gives their word and then does not honour it. The ordinary response reaches "
    "for morality, and that reading arrives instantly while explaining nothing about what "
    "actually broke in the situation itself.",
    "I remember the day my father told me this, and I carried it into my thirties before I "
    "understood any of it. My own reading was wrong for years.",
    "Cortisol rises by 40 percent under a sustained breach of trust, and the study reported "
    "that 12 percent of participants withdrew entirely from the arrangement.",
    "As Wendell Berry put it, \"the past is our definition, and we may strive with good "
    "reason to escape it, but we escape it only by adding something better to it.\"",
    "\"An unattributed sentence floats free of whoever said it, and a reader cannot weigh "
    "what they cannot source, which is the point of the convention.\"",
    "Register now for the 2019 workshop, and call 9903300044 for the limited seats still "
    "available at Rs. 4,500 per participant.",
]


def sample_pdf(header: str = "THE GIVEN WORD") -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


def _ready(env, payload: bytes = None, batch_id: str = "") -> str:
    payload = payload if payload is not None else sample_pdf()
    body: Dict[str, Any] = {"category": "Conversations",
                            "sources": [_pdf_entry(payload)]}
    if batch_id:
        body["batchId"] = batch_id
    result = env["bs"].register(body, "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})
    return source_id


def _batch(env, **overrides) -> str:
    body = {"name": "Wave 1", "defaultCategory": "Conversations"}
    body.update(overrides)
    return env["bb"].create(body, "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]


# ── The record ──────────────────────────────────────────────────────────────────

def test_an_analysis_is_its_own_record(env):
    source_id = _ready(env)
    result = env["ba"].analyse(source_id, "admin")
    assert result["analysisId"] == env["ba"].analysis_id(source_id, 1)
    record = env["ba"].get(result["analysisId"])
    assert record["recordType"] == env["ba"].RECORD_TYPE
    assert record["sourceId"] == source_id
    assert record["version"] == 1


def test_the_analysis_id_is_derived_not_random(env):
    """Resolve-before-generate: a replayed request must not mint a second v1."""
    source_id = _ready(env)
    first = env["ba"].analyse(source_id, "admin")["analysisId"]
    assert env["ba"].analysis_id(source_id, 1) == first
    assert env["ba"].analysis_id(source_id, 1) == env["ba"].analysis_id(source_id, 1)


def test_the_evidence_goes_to_s3_not_onto_the_item(env):
    """A long document's passage list is tens of kB against a 400 kB item cap."""
    source_id = _ready(env)
    result = env["ba"].analyse(source_id, "admin")
    record = env["ba"].get(result["analysisId"])
    assert record["bodyKey"] in env["s3"].objects
    assert "evidence" not in record
    body = json.loads(env["s3"].objects[record["bodyKey"]].decode())
    assert body["evidence"]["words"] > 0


def test_the_body_key_sits_under_the_agreed_prefix(env):
    source_id = _ready(env)
    key = env["ba"].get(env["ba"].analyse(source_id, "admin")["analysisId"])["bodyKey"]
    assert key.startswith(
        f"secure/blog-production/03-work/conversations/{source_id}/source-analysis/")
    assert key.endswith("/v1.json")


def test_the_analysis_is_never_handed_out_as_a_url(env):
    """`o/` is public. A source PDF gets a link deliberately; the evidence must not.

    The difference is intent: a reviewer has to open the source document, and nothing has to
    open the evidence file except this application through an authenticated route.
    """
    source_id = _ready(env)
    detail = env["ba"].detail(env["ba"].analyse(source_id, "admin")["analysisId"])
    assert detail["evidence"]
    for key in detail:
        assert "url" not in key.lower(), key


def test_the_detail_route_returns_the_evidence_unwrapped(env):
    """The S3 object is an envelope; the route must return what is inside it.

    This gap is why the test exists. One test asserted the stored object's shape and another
    asserted the route returned something truthy, and nothing joined them - so `read_body`
    returning the envelope passed the suite and failed on the first live call with
    `KeyError: 'words'`. Assert the join, not the two halves.
    """
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    found = env["ba"].detail(analysis_id)["evidence"]
    assert set(env["ba"].analysis_fields()) <= set(found), "the envelope leaked through"
    assert found["words"] > 0
    assert "analysisId" not in found, "metadata belongs on the record, not in the evidence"


def test_the_stored_object_is_self_describing(env):
    """An artifact that only makes sense beside its DynamoDB row is a poor archive."""
    source_id = _ready(env)
    record = env["ba"].get(env["ba"].analyse(source_id, "admin")["analysisId"])
    document = json.loads(env["s3"].objects[record["bodyKey"]].decode())
    assert document["analysisId"] == record["id"]
    assert document["sourceId"] == source_id
    assert document["version"] == 1
    assert document["generatedBy"] == "admin"
    assert document["evidence"]["words"] > 0


def test_every_evidence_field_is_present(env):
    """Enumerated so the shape cannot quietly shrink while still returning a dict."""
    source_id = _ready(env)
    found = env["ba"].analyse(source_id, "admin")["evidence"]
    assert set(env["ba"].analysis_fields()) <= set(found)


# ── The evidence is derived, and it is evidence rather than judgement ────────────

def test_a_first_person_wrapper_is_found_with_its_passage(env):
    source_id = _ready(env)
    found = env["ba"].analyse(source_id, "admin")["evidence"]
    assert found["firstPersonPassages"], "the source has an explicit first-person paragraph"
    assert "I remember the day" in " ".join(
        passage["text"] for passage in found["firstPersonPassages"])


def test_a_checkable_claim_carries_the_review_flag_it_triggers(env):
    source_id = _ready(env)
    claims = env["ba"].analyse(source_id, "admin")["evidence"]["checkableClaims"]
    flags = {flag for claim in claims for flag in claim["reviewFlags"]}
    assert "healthReviewComplete" in flags, "cortisol is a section 20 health trigger"
    assert any(claim["quantities"] for claim in claims)


def test_a_bare_year_is_not_a_checkable_quantity(env):
    """Flagging every date as a QUANTITY buries the percentages and dosages.

    Note what this does not claim. The sentence IS reported, because `in 19` is one of
    section 20's `historicalReviewComplete` triggers and the standard wants a historical claim
    reviewed. The point is narrower: a year contributes no `quantities`, so a document full of
    dates does not drown the one sentence carrying a dosage.
    """
    found = env["ba"].evidence("The agreement was made in 1943 and held.", q)
    claims = found["checkableClaims"]
    assert claims and claims[0]["reviewFlags"] == ["historicalReviewComplete"]
    assert claims[0]["quantities"] == 0
    assert env["ba"].evidence("She drank 250 ml and waited.", q)[
        "checkableClaims"][0]["quantities"] == 1


def test_an_unattributed_quotation_is_counted_separately(env):
    found = env["ba"].evidence(
        'As Wendell Berry put it, "the past is our definition, and we escape it only by '
        'adding something better to it." Then a second voice arrives with no owner at all: '
        '"a sentence can float free of whoever said it, and a reader cannot weigh what they '
        'have no way to source."', q)
    assert len(found["quotations"]) == 2
    assert [item["attributionNearby"] for item in found["quotations"]] == [True, False]
    assert found["unattributedQuotations"] == 1


def test_the_quoted_span_is_excluded_from_the_attribution_window(env):
    """Quoted prose is full of attribution verbs, so a window over it matches itself.

    This is the bug the test above was written for: "whoever said it" INSIDE a quotation made
    that quotation report as attributed, which turned the whole check into a constant True.
    """
    found = env["ba"].evidence(
        '"A sentence that says said and notes and according to, all inside the quotation '
        'marks, and nothing outside them at all."', q)
    assert found["quotations"][0]["attributionNearby"] is False


def test_an_attribution_far_away_does_not_count(env):
    """An attribution three pages from the quotation attributes nothing."""
    filler = "and then nothing relevant happened for a while. " * 12
    found = env["ba"].evidence(
        f'As Berry put it, {filler} "a quoted sentence long enough to be picked up here at '
        f'all, with no owner anywhere near it."', q)
    assert found["quotations"]
    assert found["unattributedQuotations"] == 1


def test_a_named_individual_is_reported_and_a_place_is_not(env):
    found = env["ba"].evidence(
        "Wendell Berry wrote about it. The United States had other ideas. "
        "See Chapter Four for more.", q)
    assert "Wendell Berry" in found["namedIndividuals"]
    assert "United States" not in found["namedIndividuals"]
    assert "Chapter Four" not in found["namedIndividuals"]


def test_the_obsolete_wrapper_is_reported_with_its_phrase(env):
    """Section 3's "obsolete wrapper" is a date, a price, a phone number, a dead platform."""
    markers = env["ba"].evidence(
        "Register now for the 2019 workshop at Rs. 4,500 per participant. Add us on Orkut. "
        "See chapter 4 for the exercises.", q)["obsoleteMarkers"]
    kinds = {marker["kind"] for marker in markers}
    assert kinds == {"dated_event", "call_to_action", "price", "deprecated_platform",
                     "first_edition_pointer"}
    assert all(marker["text"] for marker in markers), "a marker with no example asks nothing"


def test_only_one_example_per_marker_kind_is_reported(env):
    """A reviewer needs the question raised once, not forty times."""
    markers = env["ba"].evidence("Call us. Call us. Call us. Dial now. Phone today.",
                                 q)["obsoleteMarkers"]
    assert [marker["kind"] for marker in markers] == ["call_to_action"]


def test_the_wrapper_is_found_in_a_real_extracted_document(env):
    source_id = _ready(env)
    kinds = {marker["kind"] for marker
             in env["ba"].analyse(source_id, "admin")["evidence"]["obsoleteMarkers"]}
    assert "call_to_action" in kinds
    assert "dated_event" in kinds


def test_the_summary_on_the_row_is_counts_not_prose(env):
    """The row has to stay small; the passages live in S3."""
    source_id = _ready(env)
    summary = env["ba"].get(
        env["ba"].analyse(source_id, "admin")["analysisId"])["summary"]
    assert isinstance(summary["firstPersonPassages"], int)
    assert isinstance(summary["reviewFlagsTriggered"], list)
    assert len(json.dumps(summary)) < 2000


# ── Versioning ──────────────────────────────────────────────────────────────────

def test_re_analysing_adds_a_version_and_leaves_the_first_alone(env):
    source_id = _ready(env)
    first = env["ba"].analyse(source_id, "admin")
    second = env["ba"].analyse(source_id, "admin")
    assert second["version"] == 2
    assert env["ba"].get(first["analysisId"])["version"] == 1
    assert env["ba"].get(first["analysisId"])["bodyKey"] in env["s3"].objects
    assert env["ba"].get(second["analysisId"])["bodyKey"] in env["s3"].objects
    assert len(env["ba"].history(source_id)) == 2


def test_the_history_is_newest_first(env):
    source_id = _ready(env)
    env["ba"].analyse(source_id, "admin")
    env["ba"].analyse(source_id, "admin")
    env["ba"].analyse(source_id, "admin")
    assert [row["version"] for row in env["ba"].history(source_id)] == [3, 2, 1]
    assert env["ba"].current(source_id)["version"] == 3


def test_an_unextracted_source_cannot_be_analysed(env):
    """An analysis of nothing is exactly the artifact this module exists to prevent."""
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(sample_pdf())]},
        "admin", q.CATEGORIES)
    with pytest.raises(ValueError, match="EXTRACTED"):
        env["ba"].analyse(result["sources"][0]["sourceId"], "admin")


def test_an_unknown_source_is_refused(env):
    with pytest.raises(LookupError):
        env["ba"].analyse("blogsrc_nope", "admin")


# ── The boundary: analysing is not reading ──────────────────────────────────────

def test_analysing_never_writes_the_review_answer(env):
    """THE integrity test. Evidence and the claim to have read it are separate operations."""
    source_id = _ready(env)
    env["ba"].analyse(source_id, "admin")
    #: `current` returns the stored RECORD, not the view, so its key is `id`.
    record = env["ba"].get(env["ba"].current(source_id)["id"])
    assert record["sourceReviewedFully"] == ""
    assert record["reviewedBy"] == ""
    source = env["bs"].get_source(source_id)
    assert source["pipeline"]["sourceReviewedFully"] == ""
    assert source["draftRecord"].get("sourceReviewedFully") in (None, "")
    assert source["articleStatus"] == "SOURCE_REVIEW"


def test_analysing_cannot_move_the_article_status(env):
    source_id = _ready(env)
    before = env["bs"].get_source(source_id)["articleStatus"]
    for _ in range(3):
        env["ba"].analyse(source_id, "admin")
    assert env["bs"].get_source(source_id)["articleStatus"] == before


def test_the_review_answer_is_not_a_model_writable_field(env):
    """`blog_draft` applies a whitelist; a prompt-injected source cannot reach this field."""
    import blog_draft as bd
    for forbidden in ("sourceReviewedFully", "gate", "status", "sourceAnalysisId"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_recording_the_review_releases_section_two(env):
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    result = env["ba"].record_review({
        "analysisId": analysis_id, "sourceReviewedFully": "YES",
        "centralDistinctionCandidate": DISTINCTION,
        "wrapperToRemove": "the 2019 workshop pricing and the first-person childhood story",
    }, "editor")
    assert result["sourceReviewedFully"] == "YES"
    assert not any("SOURCE_NOT_READ" in item for item in result["review"])
    source = env["bs"].get_source(source_id)
    assert source["draftRecord"]["sourceReviewedFully"] == "YES"
    assert source["pipeline"]["sourceReviewedFully"] == "YES"
    assert source["pipeline"]["analysisId"] == analysis_id


def test_recording_the_review_does_not_reach_ready_to_publish(env):
    """Section 2 is one clause. The section 29 gates and the section 30 read are separate."""
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    result = env["ba"].record_review({
        "analysisId": analysis_id, "sourceReviewedFully": "YES",
        "centralDistinctionCandidate": DISTINCTION,
    }, "editor")
    assert result["readyToPublish"] is False
    assert result["humanGatesOutstanding"], "every section 29 human gate is still open"


def test_a_yes_must_name_the_distinction(env):
    """A YES with no distinction is the shape of a tick-box, so it is refused."""
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    with pytest.raises(ValueError, match="central distinction"):
        env["ba"].record_review({"analysisId": analysis_id,
                                 "sourceReviewedFully": "YES"}, "editor")


def test_a_no_needs_no_distinction(env):
    """Recording that the source is not usable must stay easy, or it will not be recorded."""
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    result = env["ba"].record_review({"analysisId": analysis_id,
                                      "sourceReviewedFully": "NO",
                                      "reviewNotes": "promotional material only"}, "editor")
    assert result["sourceReviewedFully"] == "NO"
    assert result["readyToPublish"] is False


def test_the_version_must_be_named_explicitly(env):
    source_id = _ready(env)
    env["ba"].analyse(source_id, "admin")
    with pytest.raises(ValueError, match="analysisId is required"):
        env["ba"].record_review({"sourceReviewedFully": "YES",
                                 "centralDistinctionCandidate": DISTINCTION}, "editor")


@pytest.mark.parametrize("answer", ["", "yes please", "MAYBE", "TRUE"])
def test_the_answer_must_be_yes_or_no(env, answer):
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    with pytest.raises(ValueError, match="YES or NO"):
        env["ba"].record_review({"analysisId": analysis_id,
                                 "sourceReviewedFully": answer,
                                 "centralDistinctionCandidate": DISTINCTION}, "editor")


def test_a_signoff_is_refused_after_the_text_moves(env):
    """A re-extraction that changes the text invalidates the reading, not the other way round."""
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    # Simulate a re-extraction landing different text under the same source.
    env["table"].items[source_id]["contentSha256"] = "f" * 64
    assert env["ba"].stale(env["ba"].get(analysis_id),
                           env["bs"].get_source(source_id)) is True
    with pytest.raises(ValueError, match="changed after this analysis"):
        env["ba"].record_review({"analysisId": analysis_id, "sourceReviewedFully": "YES",
                                 "centralDistinctionCandidate": DISTINCTION}, "editor")


def test_identical_re_extracted_bytes_are_not_stale(env):
    """A re-extraction producing the same text is not a change and must not invalidate."""
    source_id = _ready(env)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["bs"].run_worker({})  # no-op, the source is already EXTRACTED
    assert env["ba"].stale(env["ba"].get(analysis_id),
                           env["bs"].get_source(source_id)) is False


def test_re_analysing_does_not_carry_the_previous_review_forward(env):
    source_id = _ready(env)
    first = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({"analysisId": first, "sourceReviewedFully": "YES",
                             "centralDistinctionCandidate": DISTINCTION}, "editor")
    second = env["ba"].analyse(source_id, "admin")["analysisId"]
    assert env["ba"].get(second)["sourceReviewedFully"] == ""
    assert env["ba"].get(first)["sourceReviewedFully"] == "YES"


def test_the_reviewer_can_supply_provenance_the_extractor_missed(env):
    """Section 23 requires ARCHIVE_DERIVED to keep `originalSourceDate`, and a scanned archive
    PDF often has none the extractor can read. Until this existed nothing could write it - not
    the model whitelist, correctly, because a guessed publication date is invented provenance -
    so every undated archive source was permanently held back with no route forward."""
    source_id = _ready(env)
    env["table"].items[source_id]["draftRecord"] = {
        **env["table"].items[source_id]["draftRecord"],
        "originalSourceDate": "", "originalSourceTitle": "",
    }
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({
        "analysisId": analysis_id, "sourceReviewedFully": "YES",
        "centralDistinctionCandidate": DISTINCTION,
        "originalSourceDate": "1987",
        "originalSourceTitle": "The Given Word, first edition",
    }, "editor")
    draft = env["bs"].get_source(source_id)["draftRecord"]
    assert draft["originalSourceDate"] == "1987"
    assert draft["originalSourceTitle"] == "The Given Word, first edition"


def test_an_extracted_date_is_never_overwritten_by_a_reviewer(env):
    """The document is better evidence than a reviewer's recollection of it."""
    source_id = _ready(env)
    env["table"].items[source_id]["draftRecord"] = {
        **env["table"].items[source_id]["draftRecord"], "originalSourceDate": "1974",
    }
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({
        "analysisId": analysis_id, "sourceReviewedFully": "YES",
        "centralDistinctionCandidate": DISTINCTION, "originalSourceDate": "1987",
    }, "editor")
    assert env["bs"].get_source(source_id)["draftRecord"]["originalSourceDate"] == "1974"


def test_provenance_is_not_a_model_writable_field(env):
    import blog_draft as bd
    for forbidden in ("originalSourceDate", "originalSourceTitle", "sourceHash", "sourceFile"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_the_reviewer_distinction_does_not_overwrite_the_writers(env):
    """A candidate is a starting point for the writing, not a replacement for it."""
    source_id = _ready(env)
    env["table"].items[source_id]["draftRecord"] = {
        **env["table"].items[source_id]["draftRecord"],
        "centralDistinction": "What the writer actually settled on after doing the work.",
    }
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({"analysisId": analysis_id, "sourceReviewedFully": "YES",
                             "centralDistinctionCandidate": DISTINCTION}, "editor")
    draft = env["bs"].get_source(source_id)["draftRecord"]
    assert draft["centralDistinction"].startswith("What the writer actually settled on")


# ── The batch view ──────────────────────────────────────────────────────────────

def test_the_batch_review_state_is_derived_from_the_records(env):
    batch_id = _batch(env)
    first = _ready(env, sample_pdf("ONE"), batch_id)
    _ready(env, sample_pdf("TWO"), batch_id)
    state = env["ba"].batch_review_state(batch_id)
    assert state == {"sources": 2, "analysed": 0, "reviewed": 0,
                     "awaitingAnalysis": 2, "awaitingReview": 0, "analysisVersions": 0}

    analysis_id = env["ba"].analyse(first, "admin")["analysisId"]
    state = env["ba"].batch_review_state(batch_id)
    assert (state["analysed"], state["reviewed"], state["awaitingReview"]) == (1, 0, 1)

    env["ba"].record_review({"analysisId": analysis_id, "sourceReviewedFully": "YES",
                             "centralDistinctionCandidate": DISTINCTION}, "editor")
    state = env["ba"].batch_review_state(batch_id)
    assert (state["analysed"], state["reviewed"], state["awaitingReview"]) == (1, 1, 0)


def test_re_analysis_shows_in_the_version_count_not_the_source_count(env):
    batch_id = _batch(env)
    source_id = _ready(env, sample_pdf("ONE"), batch_id)
    env["ba"].analyse(source_id, "admin")
    env["ba"].analyse(source_id, "admin")
    state = env["ba"].batch_review_state(batch_id)
    assert state["sources"] == 1
    assert state["analysed"] == 1
    assert state["analysisVersions"] == 2


def test_pending_analysis_lists_extracted_sources_with_none(env):
    batch_id = _batch(env)
    first = _ready(env, sample_pdf("ONE"), batch_id)
    second = _ready(env, sample_pdf("TWO"), batch_id)
    assert set(env["ba"].pending_analysis(batch_id)) == {first, second}
    env["ba"].analyse(first, "admin")
    assert env["ba"].pending_analysis(batch_id) == [second]


# ── The index the analysis shares with its sources ──────────────────────────────

def test_an_analysis_does_not_count_as_a_source_in_the_rollup(env):
    """Both live on `batchId-createdAt-index`. The first version of `batch_sources`
    returned the whole partition, so an analysis inflated its own batch's source count."""
    batch_id = _batch(env)
    source_id = _ready(env, sample_pdf("ONE"), batch_id)
    env["ba"].analyse(source_id, "admin")
    env["ba"].analyse(source_id, "admin")
    rollup = env["bb"].rollup(batch_id)
    assert rollup["sources"] == 1
    assert len(env["bb"].batch_sources(batch_id)) == 1
    assert len(env["bb"].batch_records(batch_id)) == 3  # 1 source + 2 analyses
    assert len(env["bb"].batch_records(batch_id, record_type=env["ba"].RECORD_TYPE)) == 2


def test_the_pipeline_map_is_one_projected_attribute(env):
    """DynamoDB caps a GSI at 20 non-key attributes. Sixteen states, one name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dep_seo_pipeline", ROOT / "scripts" / "deploy_seo_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    projected = module.BATCH_INDEX_DEFINITION["Projection"]["NonKeyAttributes"]
    assert "pipeline" in projected
    assert len(projected) <= 20
    import blog_sources as bs
    assert len(bs.PIPELINE_FIELDS) > 3, "a map earning its keep holds more than a few keys"
    for name in bs.PIPELINE_FIELDS:
        assert name not in projected, f"{name} should live inside `pipeline`, not beside it"


def test_an_unknown_pipeline_key_is_refused(env):
    """A typo'd key would write, project, and never be read by anything."""
    source_id = _ready(env)
    with pytest.raises(ValueError, match="unknown pipeline fields"):
        env["bs"].update_pipeline(source_id, publishedStatus="live")


def test_the_pipeline_map_survives_a_partial_update(env):
    source_id = _ready(env)
    env["bs"].update_pipeline(source_id, analysisId="a1", analysisVersion=1)
    env["bs"].update_pipeline(source_id, publishStatus="QUEUED")
    pipeline = env["bs"].get_source(source_id)["pipeline"]
    assert pipeline["analysisId"] == "a1"
    assert pipeline["analysisVersion"] == 1
    assert pipeline["publishStatus"] == "QUEUED"


def test_every_source_has_the_map_from_registration(env):
    """A listing must never have to test for a missing key."""
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(sample_pdf())]},
        "admin", q.CATEGORIES)
    item = env["table"].items[result["sources"][0]["sourceId"]]
    assert set(item["pipeline"]) == set(env["bs"].PIPELINE_FIELDS)
