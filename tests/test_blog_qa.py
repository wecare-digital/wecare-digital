"""QA runs, gate sign-offs, and the four refusals that make a signature mean something.

THE THREE TESTS THAT CARRY THIS FILE.

`test_editing_the_body_invalidates_the_signoff_with_no_revocation_step` is the integrity
property. The gate is derived from the sign-off on every assessment and compared against the
body hash, so an edit after signing drops it automatically. The alternative - storing the gate
and revoking it on each write path - is a cleanup somebody has to remember at five call sites,
and the failure mode is an article certified by a signature over text nobody approved.

`test_a_signoff_is_refused_when_the_run_could_not_load_the_corpus`. Section 28 duplication needs
the 1,165-post index. A run without it reports NON_DUPLICATION having compared against nothing,
and a signature over that is a signature over nothing.

`test_a_blocking_finding_cannot_be_accepted_by_signature`. A human may accept a REVIEW - that is
what judgement is for. A BLOCK is a mechanical fact, and letting a signature override it would
make the mechanical half of the standard advisory.
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

STATEMENT = ("Read the source and the article end to end, checked the two quotations against "
             "the source, and accept the reconstruction as it stands.")
DISTINCTION = ("The source separates a broken agreement from a broken person, which is the "
               "distinction a reader can act on rather than merely agree with.")

#: A body that passes every mechanical rule, so a sign-off test is testing the sign-off.
#:
#: It took four rounds to get here, and each failure was the gate being right: 201 words against
#: the REFLECTION band of 500-800, a missing `originalSourceDate` that ARCHIVE_DERIVED requires,
#: the section 5 uniqueness declarations that nothing could write until this task, and the word
#: "reliability" tripping the legal-review trigger through the substring "liability". Three of
#: the four were fixed in the fixture. The fourth was a real defect in the gate and was fixed
#: there.
GOOD_BODY = """A person gives their word, and then the word does not hold. The response that
arrives first is moral. It is also useless, because it describes the person and leaves the
situation exactly where it was.

Something was counting on that word. A schedule had been built around it. Somebody else made a
decision on the strength of it, and committed something they cannot now recover. The word was
load-bearing, and the structure moved when it came out.

Workability asks a narrower question than goodness does. What became possible because the
commitment existed, and what stopped being possible when it failed? Those questions have
answers. The moral version mostly has verdicts.

Notice what changes when the question changes. Repair stops being an apology and becomes a
piece of work. Name what moved. Say what is now true. Rebuild the part of the arrangement that
had been resting on the word, and tell the people who were resting on it too. None of that
requires anybody to be good, and none of it is satisfied by feeling bad.

The distinction holds in the other direction. Somebody who keeps every promise inside an
arrangement where nothing depends on them has demonstrated very little. Dependability only
becomes visible where something rests on it, which is why it is tested by inconvenience and
not by intention. The easy promise is not evidence.

There is a second thing the moral reading hides. When a commitment fails, the people around it
start making private arrangements to cover the gap, and those arrangements outlast the original
failure. A team learns not to plan on a colleague. A supplier quietly builds in a week of
slack. None of it is announced, and all of it is expensive.

That is the cost worth naming, because it is the one nobody itemises. An apology addresses the
offence. It does not address the slack, the private workaround, or the plan somebody quietly
stopped making. Those come back only when the word starts holding again, and only after long
enough that planning on it stops feeling reckless.

So the question to ask after a broken commitment is not whether the person is sorry. It is what
other people have started doing differently, and what would have to happen for them to stop.
That is answerable, it is specific to the situation, and working through it produces something
an apology never does, which is an arrangement that holds the next time it is tested."""


@pytest.fixture()
def env(monkeypatch):
    import blog_analysis as ba
    import blog_batches as bb
    import blog_gate as bg
    import blog_qa as bq
    import blog_sources as bs
    import blog_templates as bt
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    bg.reset_corpus_cache()
    #: A corpus with one unrelated entry. Non-empty, because `sign_off` refuses a run that
    #: checked nothing - so an empty index would make every sign-off test fail for the wrong
    #: reason. Loading the real 1.4 MB index in a unit test would be slow and would couple
    #: every assertion here to the live published corpus.
    index = q.CorpusIndex()
    index.add({"slug": "an-unrelated-article", "title": "Something else entirely",
               "category": "Conversations",
               "contentMarkdown": "Quite different prose about an unrelated subject, at "
                                  "sufficient length to produce a sketch worth comparing "
                                  "against and nothing like the article under test."},
              origin="test-corpus")
    monkeypatch.setattr(bg, "_corpus", index)
    monkeypatch.setattr(bg, "_corpus_state", {"loaded": 1, "present": True,
                                              "path": "test", "packaged": True,
                                              "builtAt": "", "note": ""})
    yield {"table": table, "s3": s3, "ba": ba, "bb": bb, "bg": bg, "bq": bq, "bs": bs,
           "bt": bt, "storage": storage}
    bg.reset_corpus_cache()


PROSE = [
    "A person gives their word and then does not honour it. The ordinary response reaches "
    "for morality, and that reading arrives instantly while explaining nothing about what "
    "actually broke in the situation itself.",
    "Something was counting on the word. A schedule, a decision someone else made on the "
    "strength of it, a resource committed. The word was load-bearing and the structure "
    "moved when it came out of the arrangement.",
    "Workability asks a different question from whether the person is good. It asks what "
    "became possible and what stopped being possible for everybody who had planned around "
    "the commitment in the first place.",
]


def sample_pdf(header: str = "THE GIVEN WORD") -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


def _source(env, batch_id: str = "", header: str = "THE GIVEN WORD") -> str:
    payload = sample_pdf(header)
    body: Dict[str, Any] = {"category": "Conversations", "sources": [_pdf_entry(payload)]}
    if batch_id:
        body["batchId"] = batch_id
    result = env["bs"].register(body, "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})
    return source_id


def _written(env, batch_id: str = "", body: str = GOOD_BODY,
            header: str = "THE GIVEN WORD") -> str:
    """A source whose source reading is recorded and whose article body is written."""
    source_id = _source(env, batch_id, header)
    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({"analysisId": analysis_id, "sourceReviewedFully": "YES",
                             "centralDistinctionCandidate": DISTINCTION}, "editor")
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    draft.update({
        "contentMarkdown": body,
        "title": f"The given word {header.lower()}",
        "slug": q.slugify(f"the given word {header.lower()}"),
        "seoTitle": f"The given word {header.lower()} | WECARE.DIGITAL",
        "metaDescription": ("What breaks when a commitment fails, read as a question about "
                            "workability rather than about character or good intent."),
        "excerpt": ("When a given word fails, something that was counting on it moves; "
                    "repair is restoring that structure, not an apology."),
        "tags": ["integrity"],
        "articleType": "REFLECTION",
        "centralDistinction": DISTINCTION,
        "distinctPurpose": ("It separates repair as work from repair as apology, which no "
                            "other article on the site takes as its subject."),
        #: ARCHIVE_DERIVED must preserve this internally (section 23). The extractor found no
        #: date in the fixture PDF, which is the ordinary case for a scanned archive document.
        "originalSourceDate": "1987",
    })
    draft["canonical"] = q.expected_canonical(draft["slug"])
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    return source_id


def _all_pass(env) -> Dict[str, str]:
    return {name: "PASS" for name in q.HUMAN_GATES}


def _declarations(**overrides) -> Dict[str, str]:
    """Every section 5 and 28 declaration answered the way the standard requires."""
    import blog_qa
    return {**{name: expected for name, expected in blog_qa.DECLARATIONS}, **overrides}


def _signed(env, source_id: str, **overrides) -> Dict[str, Any]:
    qa = env["bq"].run(source_id, "qa")
    body = {"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
            "declarations": _declarations(), "statement": STATEMENT}
    body.update(overrides)
    return env["bq"].sign_off(body, "editor")


# ── The QA run ──────────────────────────────────────────────────────────────────

def test_a_qa_run_is_its_own_record_with_its_report_in_s3(env):
    source_id = _written(env)
    result = env["bq"].run(source_id, "qa")
    record = env["bq"].get_run(result["qaRunId"])
    assert record["recordType"] == env["bq"].RUN_RECORD_TYPE
    assert record["bodyKey"] in env["s3"].objects
    assert record["bodyKey"].startswith(
        f"secure/blog-production/03-work/conversations/{source_id}/qa/{source_id}/")
    report = json.loads(env["s3"].objects[record["bodyKey"]].decode())
    assert report["qaRunId"] == result["qaRunId"]
    assert report["sourceId"] == source_id


def test_the_run_records_the_body_it_ran_against(env):
    source_id = _written(env)
    result = env["bq"].run(source_id, "qa")
    record = env["bs"].get_source(source_id)
    assert result["bodySha256"] == env["bg"].body_sha256(record["draftRecord"])
    assert len(result["bodySha256"]) == 64


def test_the_run_records_what_the_corpus_comparison_covered(env):
    """A NON_DUPLICATION verdict is only worth what this says."""
    source_id = _written(env)
    result = env["bq"].run(source_id, "qa")
    assert result["corpusChecked"] == 1
    assert result["report"]["corpus"]["present"] is True


def test_linked_published_revision_does_not_collide_with_its_own_live_slug(env):
    source_id = _written(env)
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    env["bg"]._corpus.add(draft, origin="published-corpus")

    before = env["bg"].assess_draft(record, draft, with_corpus=True)
    assert any("EXACT_SLUG_COLLISION" in finding for finding in before["blocking"])

    record["pipeline"] = {
        "postId": "blog_live",
        "postUrl": f"https://wecare.digital/post/{draft['slug']}",
        "publishStatus": "PUBLISHED",
    }
    revision = env["bg"].assess_draft(record, draft, with_corpus=True)
    assert not any("EXACT_SLUG_COLLISION" in finding for finding in revision["blocking"])


def test_unlinked_collision_cannot_claim_revision_self_exclusion(env):
    source_id = _written(env)
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    env["bg"]._corpus.add(draft, origin="published-corpus")
    record["pipeline"] = {
        "postId": "blog_live",
        "postUrl": "https://wecare.digital/post/a-different-slug",
        "publishStatus": "PUBLISHED",
    }
    assessment = env["bg"].assess_draft(record, draft, with_corpus=True)
    assert any("EXACT_SLUG_COLLISION" in finding for finding in assessment["blocking"])


def test_the_run_records_the_chain_it_rests_on(env):
    """source -> reading -> template -> article -> QA, complete in the records."""
    template = env["bt"].save({
        "name": "Reflection", "category": "Conversations", "minWords": 0, "maxWords": 4000,
        "sections": [{"key": "a", "heading": "The situation", "required": False}],
    }, "admin", q.CATEGORIES, q.ARTICLE_CLASSES)
    source_id = _written(env)
    env["bt"].assign(source_id, template["templateId"], 1, "admin")
    report = env["bq"].run(source_id, "qa")["report"]
    assert report["analysisId"].startswith("blogana_")
    assert report["analysisVersion"] == 1
    assert report["templateId"] == template["templateId"]
    assert report["templateVersion"] == 1


def test_an_article_with_no_body_cannot_be_qa_run(env):
    source_id = _source(env)
    with pytest.raises(ValueError, match="no body yet"):
        env["bq"].run(source_id, "qa")


def test_the_verdict_separates_blocked_from_review_from_pass(env):
    blocked = _written(env, body="Too short.", header="SHORT")
    assert env["bq"].run(blocked, "qa")["verdict"] in (env["bq"].QA_BLOCKED,
                                                      env["bq"].QA_REVIEW)
    clean = _written(env, header="CLEAN")
    assert env["bq"].run(clean, "qa")["verdict"] in (env["bq"].QA_PASS, env["bq"].QA_REVIEW)


def test_running_qa_again_adds_a_run_and_keeps_the_first(env):
    """A run is a record of a moment, so it is never overwritten."""
    source_id = _written(env)
    first = env["bq"].run(source_id, "qa")
    second = env["bq"].run(source_id, "qa")
    assert first["qaRunId"] != second["qaRunId"]
    assert env["bq"].get_run(first["qaRunId"]) is not None
    assert len(env["bq"].run_history(source_id)) == 2
    assert env["bq"].latest_run(source_id)["id"] == second["qaRunId"]
    assert env["bq"].get_run(first["qaRunId"])["bodyKey"] in env["s3"].objects


def test_the_run_is_reachable_on_the_pipeline_map(env):
    source_id = _written(env)
    result = env["bq"].run(source_id, "qa")
    pipeline = env["bs"].get_source(source_id)["pipeline"]
    assert pipeline["qaRunId"] == result["qaRunId"]
    assert pipeline["qaStatus"] == result["verdict"]


def test_the_report_is_proxied_not_linked(env):
    source_id = _written(env)
    detail = env["bq"].run_detail(env["bq"].run(source_id, "qa")["qaRunId"])
    assert detail["report"]["sourceId"] == source_id
    for key in detail:
        assert "url" not in key.lower(), key


# ── Running QA is not approving ─────────────────────────────────────────────────

def test_a_qa_run_never_makes_an_article_publishable(env):
    source_id = _written(env)
    env["bq"].run(source_id, "qa")
    record = env["bs"].get_source(source_id)
    assessment = env["bg"].assess_draft(record, record["draftRecord"])
    assert assessment["readyToPublish"] is False
    assert len(assessment["humanGatesOutstanding"]) == len(q.HUMAN_GATES)


def test_a_qa_run_writes_no_gate(env):
    source_id = _written(env)
    env["bq"].run(source_id, "qa")
    assert "gate" not in env["bs"].get_source(source_id)["draftRecord"]


# ── Sign-off ────────────────────────────────────────────────────────────────────

def test_signing_off_makes_the_article_releasable(env):
    source_id = _written(env)
    result = _signed(env, source_id)
    assert result["signedBy"] == "editor"
    assert result["readyToPublish"] is True
    assert result["articleStatus"] == q.PUBLISHABLE_STATUS
    ok, reason = env["bq"].releasable(source_id)
    assert ok is True, reason


def test_signing_off_does_not_publish(env):
    source_id = _written(env)
    _signed(env, source_id)
    pipeline = env["bs"].get_source(source_id)["pipeline"]
    assert pipeline["publishStatus"] == ""
    assert pipeline["postId"] == ""
    assert pipeline["signoffId"].startswith("blogsign_")


def test_the_gate_is_never_stored_on_the_article(env):
    """A stored gate is a second source of truth that outlives its signature."""
    source_id = _written(env)
    _signed(env, source_id)
    stored = env["table"].items[source_id]
    assert "gate" not in stored["draftRecord"]
    assert "gate" not in stored


def test_the_gate_is_derived_on_every_assessment(env):
    source_id = _written(env)
    record = env["bs"].get_source(source_id)
    assert env["bg"].resolved_gate(record, record["draftRecord"]) == {}
    _signed(env, source_id)
    record = env["bs"].get_source(source_id)
    assert set(env["bg"].resolved_gate(record, record["draftRecord"])) == set(q.HUMAN_GATES)


def test_editing_the_body_invalidates_the_signoff_with_no_revocation_step(env):
    """THE integrity property. There is nothing to revoke and nothing to forget."""
    source_id = _written(env)
    _signed(env, source_id)
    assert env["bq"].releasable(source_id)[0] is True

    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    draft["contentMarkdown"] = draft["contentMarkdown"] + "\n\nOne more paragraph arrives."
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)

    record = env["bs"].get_source(source_id)
    assert env["bg"].resolved_gate(record, record["draftRecord"]) == {}
    ok, reason = env["bq"].releasable(source_id)
    assert ok is False
    assert "edited after it was signed off" in reason
    assert env["bg"].assess_draft(record, record["draftRecord"])["readyToPublish"] is False


def test_a_whitespace_only_reflow_does_not_invalidate(env):
    """A reflow that changes no words is not an edit, and revoking for it would be noise."""
    source_id = _written(env)
    _signed(env, source_id)
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    draft["contentMarkdown"] = draft["contentMarkdown"].replace("\n", "\n ")
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    assert env["bq"].releasable(source_id)[0] is True


def test_changing_a_tag_does_not_invalidate_the_reading_of_the_prose(env):
    """The hash covers the body, deliberately. A metadata field has its own findings."""
    source_id = _written(env)
    _signed(env, source_id)
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    draft["tags"] = ["integrity", "agreements"]
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    assert env["bq"].releasable(source_id)[0] is True


# ── The four refusals ───────────────────────────────────────────────────────────

def test_a_signoff_needs_a_named_qa_run(env):
    source_id = _written(env)
    env["bq"].run(source_id, "qa")
    with pytest.raises(ValueError, match="qaRunId is required"):
        env["bq"].sign_off({"gates": _all_pass(env), "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")
    with pytest.raises(LookupError):
        env["bq"].sign_off({"qaRunId": "blogqa_nope", "gates": _all_pass(env),
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_a_signoff_is_refused_when_the_run_is_stale(env):
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    draft["contentMarkdown"] += "\n\nA later paragraph that changes the text."
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    with pytest.raises(ValueError, match="changed after this QA run"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_a_signoff_is_refused_when_the_run_could_not_load_the_corpus(env, monkeypatch):
    """A NON_DUPLICATION result compared against nothing cannot carry a signature."""
    source_id = _written(env)
    monkeypatch.setattr(env["bg"], "_corpus", q.CorpusIndex())
    monkeypatch.setattr(env["bg"], "_corpus_state",
                        {"loaded": 0, "present": False, "path": "missing",
                         "packaged": False, "builtAt": "", "note": "index missing"})
    qa = env["bq"].run(source_id, "qa")
    assert qa["corpusChecked"] == 0
    with pytest.raises(ValueError, match="compared against nothing"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_a_blocking_finding_cannot_be_accepted_by_signature(env):
    """A REVIEW is judgement. A BLOCK is a mechanical fact."""
    source_id = _written(env, body="Far too short to be an article at all.", header="THIN")
    qa = env["bq"].run(source_id, "qa")
    if qa["blockingCount"] == 0:
        pytest.skip("the fixture produced no blocking finding")
    with pytest.raises(ValueError, match="blocking finding"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_a_gate_answered_fail_blocks_the_signoff(env):
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    gates = {**_all_pass(env), "VOICE": "FAIL"}
    with pytest.raises(ValueError, match=r"answered FAIL.*VOICE"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": gates,
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_every_human_gate_must_be_answered(env):
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    partial = {name: "PASS" for name in q.HUMAN_GATES[:5]}
    with pytest.raises(ValueError, match="missing"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": partial,
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_a_misspelled_gate_is_refused_not_dropped(env):
    """Dropping it silently leaves the article on EDITORIAL_QA with no visible reason."""
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    gates = {**_all_pass(env), "DISTINCTON": "PASS"}
    del gates["DISTINCTION"]
    with pytest.raises(ValueError, match="not a section 29 human gate"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": gates,
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


@pytest.mark.parametrize("answer", ["", "yes", "OK", "TRUE", "MAYBE"])
def test_a_gate_answer_must_be_pass_fail_or_na(env, answer):
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    gates = {**_all_pass(env), "PRIVACY": answer}
    with pytest.raises(ValueError, match="must be one of"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": gates,
                            "declarations": _declarations(),
                            "statement": STATEMENT}, "editor")


def test_na_is_a_real_answer(env):
    """PRIVACY on an article naming nobody is genuinely not applicable, and pretending
    otherwise trains people to answer PASS to make the form go away."""
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    gates = {**_all_pass(env), "PRIVACY": "N/A", "ATTRIBUTION": "NA"}
    result = env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": gates,
                                 "declarations": _declarations(),
                                 "statement": STATEMENT}, "editor")
    assert result["gates"]["PRIVACY"] == "N/A"
    assert result["gates"]["ATTRIBUTION"] == "N/A"
    assert result["readyToPublish"] is True


# ── The declarations, which nothing could write before ──────────────────────────

def test_the_declarations_are_what_makes_ready_to_publish_reachable(env):
    """Before this, sections 5 and 28 had no writer at all.

    They are correctly absent from `blog_draft.WRITABLE_FIELDS` - a model declaring its own
    output non-duplicative is worthless - and there was no human route either. `decide_status`
    routes an unanswered section 5 flag to DEDUPE_REWORK, so READY_TO_PUBLISH was structurally
    unreachable and the whole publish path was dead code that looked finished.
    """
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    with pytest.raises(ValueError, match="materiallyDifferentInquiry"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": {}, "statement": STATEMENT}, "editor")
    signed = _signed(env, source_id)
    assert signed["readyToPublish"] is True
    assert signed["declarations"]["materiallyDifferentInquiry"] == "YES"
    assert signed["declarations"]["titleOnlyDifference"] == "NO"


def test_a_declaration_answered_the_wrong_way_is_refused(env):
    """`titleOnlyDifference: YES` says this is the same article renamed. Recording it and then
    reporting DEDUPE_REWORK would be a slower way of saying no."""
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    for name, wrong in (("titleOnlyDifference", "YES"), ("exactBodyDuplicate", "YES"),
                        ("materiallyDifferentInquiry", "NO"), ("uniqueReaderPromise", "NO")):
        with pytest.raises(ValueError, match="the standard requires"):
            env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                                "declarations": _declarations(**{name: wrong}),
                                "statement": STATEMENT}, "editor")


def test_an_unknown_declaration_is_refused(env):
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    with pytest.raises(ValueError, match="unknown declarations"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(definitelyUnique="YES"),
                            "statement": STATEMENT}, "editor")


def test_a_review_flag_is_required_only_when_the_body_triggers_it(env):
    """Section 20's rule is about claims actually made. Demanding a health review of an article
    with no medicine in it trains people to answer YES to clear the form."""
    source_id = _written(env)
    assert env["bq"].triggered_review_flags(
        env["bs"].get_source(source_id)["draftRecord"], q) == []

    medical = _written(env, header="MEDICAL",
                       body=GOOD_BODY + "\n\nCortisol rises and the diagnosis follows.")
    flags = env["bq"].triggered_review_flags(
        env["bs"].get_source(medical)["draftRecord"], q)
    assert "healthReviewComplete" in flags

    qa = env["bq"].run(medical, "qa")
    assert "healthReviewComplete" in qa["report"]["reviewFlagsRequired"]
    with pytest.raises(ValueError, match="healthReviewComplete must be YES"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(), "statement": STATEMENT}, "editor")
    signed = env["bq"].sign_off(
        {"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
         "declarations": _declarations(healthReviewComplete="YES"),
         "statement": STATEMENT}, "editor")
    assert signed["declarations"]["healthReviewComplete"] == "YES"


def test_a_trigger_inside_a_longer_word_does_not_fire(env):
    """"reliability" contains "liability", and the gate demanded a legal review of an article
    with no legal claim in it - which is section 20's own failure mode, arrived at backwards."""
    assert q._trigger_present("liability", "questions of liability arise") is True
    assert q._trigger_present("liability", "dependability and reliability") is False
    #: Left-anchored only, on purpose: `in 19` is meant to catch "in 1943", and a right-hand
    #: boundary would break exactly that.
    assert q._trigger_present("in 19", "it happened in 1943") is True


def test_the_declarations_are_not_stored_on_the_article(env):
    source_id = _written(env)
    _signed(env, source_id)
    stored = env["table"].items[source_id]["draftRecord"]
    for name, _ in env["bq"].DECLARATIONS:
        assert name not in stored, name


def test_editing_the_body_drops_the_declarations_too(env):
    source_id = _written(env)
    _signed(env, source_id)
    record = env["bs"].get_source(source_id)
    assert env["bg"].resolved_signature(record, record["draftRecord"])[
        "materiallyDifferentInquiry"] == "YES"
    draft = dict(record["draftRecord"])
    draft["contentMarkdown"] += "\n\nA later paragraph arrives and changes the text."
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    record = env["bs"].get_source(source_id)
    assert env["bg"].resolved_signature(record, record["draftRecord"]) == {}


def test_the_declarations_are_not_model_writable(env):
    import blog_draft as bd
    import blog_qa as bq
    for name, _ in bq.DECLARATIONS:
        assert name not in bd.WRITABLE_FIELDS, name
    for flag in q.FACT_DOMAIN_TRIGGERS:
        assert flag not in bd.WRITABLE_FIELDS, flag


def test_a_signoff_needs_a_statement(env):
    """Section 30 asks one question, and a signature with no sentence behind it is a click."""
    source_id = _written(env)
    qa = env["bq"].run(source_id, "qa")
    with pytest.raises(ValueError, match="statement of at least"):
        env["bq"].sign_off({"qaRunId": qa["qaRunId"], "gates": _all_pass(env),
                            "declarations": _declarations(),
                            "statement": "looks fine"}, "editor")


# ── Revocation ──────────────────────────────────────────────────────────────────

def test_revoking_withdraws_the_signature_without_touching_the_article(env):
    source_id = _written(env)
    signed = _signed(env, source_id)
    before = env["bs"].get_source(source_id)["draftRecord"]["contentMarkdown"]
    result = env["bq"].revoke(signed["signoffId"], "the second quotation is misattributed",
                              "editor")
    assert result["revokedAt"]
    assert env["bq"].current_signoff(source_id) is None
    assert env["bq"].releasable(source_id)[0] is False
    assert env["bs"].get_source(source_id)["draftRecord"]["contentMarkdown"] == before


def test_a_revoked_signoff_is_kept(env):
    """"Signed and then withdrawn, by whom and why" is history a deletion destroys."""
    source_id = _written(env)
    signed = _signed(env, source_id)
    env["bq"].revoke(signed["signoffId"], "the reviewer changed their mind", "editor")
    held = env["bq"].get_signoff(signed["signoffId"])
    assert held is not None
    assert held["revokedBy"] == "editor"
    assert held["revokeReason"] == "the reviewer changed their mind"
    assert len(env["bq"].signoff_history(source_id)) == 1


def test_a_revocation_needs_a_reason(env):
    source_id = _written(env)
    signed = _signed(env, source_id)
    with pytest.raises(ValueError, match="reason"):
        env["bq"].revoke(signed["signoffId"], "no", "editor")


def test_revoking_twice_is_reported_not_an_error(env):
    source_id = _written(env)
    signed = _signed(env, source_id)
    env["bq"].revoke(signed["signoffId"], "the first withdrawal", "editor")
    assert env["bq"].revoke(signed["signoffId"], "again", "editor")["alreadyRevoked"] is True


def test_signing_again_after_a_revocation_works(env):
    source_id = _written(env)
    first = _signed(env, source_id)
    env["bq"].revoke(first["signoffId"], "withdrawn for a second read", "editor")
    second = _signed(env, source_id)
    assert second["signoffId"] != first["signoffId"]
    assert env["bq"].releasable(source_id)[0] is True
    assert env["bq"].current_signoff(source_id)["id"] == second["signoffId"]


# ── Reporting ───────────────────────────────────────────────────────────────────

def test_releasable_reports_a_reason_rather_than_a_bare_boolean(env):
    source_id = _source(env)
    assert env["bq"].releasable(source_id) == (False, "the article has no body")
    source_id = _written(env, header="OTHER")
    assert env["bq"].releasable(source_id)[1] == "no gate sign-off has been recorded"
    _signed(env, source_id)
    assert env["bq"].releasable(source_id)[0] is True


def test_source_state_answers_everything_a_reviewer_needs(env):
    source_id = _written(env)
    state = env["bq"].source_state(source_id)
    assert state["latestRun"] == {}
    assert state["signoff"] == {}
    assert state["releasable"] is False

    _signed(env, source_id)
    state = env["bq"].source_state(source_id)
    assert state["latestRun"]["verdict"]
    assert state["signoff"]["signedBy"] == "editor"
    assert state["runStale"] is False
    assert state["signoffStale"] is False
    assert state["releasable"] is True
    assert (state["runs"], state["signoffs"]) == (1, 1)


def test_source_state_reports_staleness_after_an_edit(env):
    source_id = _written(env)
    _signed(env, source_id)
    draft = dict(env["bs"].get_source(source_id)["draftRecord"])
    draft["contentMarkdown"] += "\n\nA later paragraph."
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    state = env["bq"].source_state(source_id)
    assert state["runStale"] is True
    assert state["signoffStale"] is True
    assert state["releasable"] is False


def test_the_batch_qa_state_is_derived_from_the_records(env):
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    first = _written(env, batch_id, header="ONE")
    _written(env, batch_id, header="TWO")
    state = env["bq"].batch_qa_state(batch_id)
    assert state == {"sources": 2, "qaRun": 0, "byVerdict": {}, "signedOff": 0,
                     "awaitingSignoff": 0, "totalRuns": 0, "totalSignoffs": 0}

    _signed(env, first)
    state = env["bq"].batch_qa_state(batch_id)
    assert state["sources"] == 2
    assert state["qaRun"] == 1
    assert state["signedOff"] == 1
    assert state["totalRuns"] == 1
    assert state["totalSignoffs"] == 1


def test_qa_records_do_not_count_as_sources_in_the_rollup(env):
    """Runs and sign-offs carry a batchId and land on the same index as the sources."""
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    source_id = _written(env, batch_id)
    _signed(env, source_id)
    assert env["bb"].rollup(batch_id)["sources"] == 1
    assert len(env["bb"].batch_records(batch_id)) == 4  # source + analysis + run + signoff


# ── The boundary ────────────────────────────────────────────────────────────────

def test_the_gate_is_not_a_model_writable_field(env):
    import blog_draft as bd
    for forbidden in ("gate", "gates", "status", "signoffId", "qaRunId"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_every_assessment_site_routes_through_blog_gate(env):
    """A rule sourced outside the gate has to apply everywhere or nowhere."""
    source = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
    for name in ("blog_sources.py", "blog_draft.py", "blog_analysis.py", "blog_qa.py"):
        text = (source / name).read_text(encoding="utf-8")
        assert "q.assess(" not in text, f"{name} assesses directly; use blog_gate.assess_draft"
        assert "blog_templates.assess_draft" not in text, f"{name} uses the old entry point"


def test_the_corpus_is_off_on_the_hot_path_and_on_for_a_qa_run(env):
    """Extraction assesses five drafts an invocation and none of them has a body yet."""
    source_id = _written(env)
    record = env["bs"].get_source(source_id)
    cheap = env["bg"].assess_draft(record, record["draftRecord"])
    assert cheap["corpus"]["note"] == "corpus not checked"
    dear = env["bg"].assess_draft(record, record["draftRecord"], with_corpus=True)
    assert dear["corpus"]["present"] is True


def test_assess_draft_does_not_mutate_the_caller_dict(env):
    """Mutating it would persist a gate onto draftRecord on the next write."""
    source_id = _written(env)
    _signed(env, source_id)
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    env["bg"].assess_draft(record, draft)
    assert "gate" not in draft


def test_the_corpus_index_is_packaged_for_the_lambda():
    """A QA run that cannot load it reports NON_DUPLICATION on an unchecked corpus, which is
    the "worse than no gate, because it is believed" failure the index exists to fix."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dep_seo_corpus", ROOT / "scripts" / "deploy_seo_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    zipped = module.package()
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        names = set(archive.namelist())
    assert "content/conversations/corpus-index.json" in names
    assert "blog_quality_v2.py" in names
    assert "operations/seo-tools/blog_qa.py" in names
    assert "operations/seo-tools/blog_gate.py" in names
