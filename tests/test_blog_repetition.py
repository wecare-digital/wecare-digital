"""Collection-level repetition: the failure where no two articles are duplicates.

THE TEST THAT JUSTIFIES THE MODULE.

`test_a_collection_of_individually_clean_articles_is_still_caught`. Every article in it passes
the per-article gate and the per-article dedupe, because no two of them overlap. They all open
the same way and they all use the same stock phrase once, which the per-article rule allows.
That is the signature of bulk generation, and a gate that only ever sees one record at a time
cannot see it at all.

`test_the_candidate_prefilter_is_exact_not_a_heuristic` is the other one. The pair sweep discards
pairs without comparing them, and it is only safe to do that because `sketch_jaccard` scores a
pair with no shared hash values at exactly zero. If that ever stopped being true, this module
would silently miss duplicates.
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
from blog_pdf_fixture import make_pdf, wrap  # noqa: E402
from test_blog_sources import FakeLambda, FakeS3, FakeTable, _pdf_entry  # noqa: E402
from test_blog_qa import GOOD_BODY, PROSE  # noqa: E402


@pytest.fixture()
def env(monkeypatch):
    import blog_batches as bb
    import blog_repetition as br
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    return {"table": table, "s3": s3, "bb": bb, "br": br, "bs": bs, "storage": storage}


def sample_pdf(header: str) -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


def _batch(env, name: str = "Wave 1") -> str:
    return env["bb"].create({"name": name, "defaultCategory": "Conversations"},
                            "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]


def _article(env, batch_id: str, header: str, body: str, title: str = "",
             distinction: str = "") -> str:
    """A source in a batch whose draft carries a body. Written straight to the fake table
    because the point here is the collection, not the intake path."""
    payload = sample_pdf(header)
    result = env["bs"].register(
        {"batchId": batch_id, "category": "Conversations",
         "sources": [_pdf_entry(payload, f"{header.lower()}.pdf")]}, "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})
    item = env["table"].items[source_id]
    draft = dict(item.get("draftRecord") or {})
    draft.update({
        "contentMarkdown": body,
        "title": title or f"The given word, {header.lower()}",
        "slug": q.slugify(title or f"the given word {header.lower()}"),
        "centralDistinction": distinction or (
            f"What {header.lower()} makes newly visible about a commitment that was "
            f"load-bearing for somebody else."),
    })
    item["draftRecord"] = env["storage"]._clean(draft)
    return source_id


def _prepared(bodies: List[str], titles: List[str] = None,
             distinctions: List[str] = None) -> List[Dict[str, Any]]:
    """`_articles` input without touching a table, so `analyse` can be tested as a pure
    function - which is where all the interesting logic lives."""
    import blog_repetition as br
    titles = titles or [f"Article number {index}" for index in range(len(bodies))]
    distinctions = distinctions or [f"Distinction {index}" for index in range(len(bodies))]
    rows = []
    for index, body in enumerate(bodies):
        rows.append({
            "id": f"blogsrc_{index:064x}",
            "recordType": "blogSource",
            "draftRecord": {"contentMarkdown": body, "title": titles[index],
                            "slug": q.slugify(titles[index]),
                            "centralDistinction": distinctions[index]},
        })
    return br._articles(rows, q)


# ── Pairs, and the prefilter that makes them affordable ─────────────────────────

def test_the_candidate_prefilter_is_exact_not_a_heuristic(env):
    """A pair with no shared sketch values scores exactly zero, so discarding it is safe.

    If `sketch_jaccard` ever stopped returning 0 for a disjoint pair, this module would start
    silently missing duplicates rather than reporting a wrong number.
    """
    left = q.sketch("A passage about keeping agreements and what rests on them in practice.")
    right = q.sketch("Entirely unrelated prose concerning the migration of arctic terns.")
    assert set(left).isdisjoint(set(right))
    assert q.sketch_jaccard(left, right) == 0.0
    assert env["br"].candidate_pairs([left, right]) == []


def test_the_prefilter_keeps_a_pair_that_shares_anything(env):
    body = "A person gives their word and then the word does not hold at all, in the end."
    sketches = [q.sketch(body), q.sketch(body + " And one more sentence arrives here.")]
    assert env["br"].candidate_pairs(sketches) == [(0, 1)]


def test_a_near_duplicate_pair_inside_the_batch_is_found(env):
    """The per-article gate compares against the PUBLISHED corpus, so it cannot see a sibling
    still in flight - which is exactly where a bulk run produces its duplicates."""
    report = env["br"].analyse(_prepared([GOOD_BODY, GOOD_BODY]), q)
    assert len(report["pairs"]) == 1
    pair = report["pairs"][0]
    assert pair["severity"] == "NEAR_DUPLICATE"
    assert pair["bodySimilarity"] > 0.9
    assert set(report["implicated"]) == {pair["a"], pair["b"]}


def test_unrelated_articles_produce_no_pairs(env):
    report = env["br"].analyse(_prepared([
        GOOD_BODY,
        "Arctic terns migrate further than any other bird, and the reason is daylight rather "
        "than temperature. They follow the summer from one pole to the other, and in doing so "
        "see more sunlight in a year than anything else alive. The journey is not an escape "
        "from winter so much as a pursuit of the feeding it makes possible.",
    ]), q)
    assert report["pairs"] == []
    assert report["implicated"] == []


def test_pairs_are_ordered_worst_first_and_bounded(env):
    """A reviewer works from the worst offenders, not from an alphabetical list."""
    bodies = [GOOD_BODY, GOOD_BODY, GOOD_BODY[:1200], GOOD_BODY[:600]]
    report = env["br"].analyse(_prepared(bodies), q)
    scores = [item["bodySimilarity"] for item in report["pairs"]]
    assert scores == sorted(scores, reverse=True)
    assert len(report["pairs"]) <= env["br"].MAX_PAIRS


def test_a_repeated_title_is_reported_even_with_different_bodies(env):
    titles = ["What a broken promise teaches about trust",
              "What a broken promise teaches about trust"]
    report = env["br"].analyse(_prepared(
        [GOOD_BODY, "Wholly different prose about arctic terns and their migration habits."],
        titles=titles), q)
    assert len(report["titlePairs"]) == 1
    assert report["titlePairs"][0]["similarity"] == 1.0


def test_a_shared_distinction_is_reported(env):
    same = ("The same distinction stated in the same words, which means these are one article "
            "wearing two subjects.")
    report = env["br"].analyse(_prepared(
        [GOOD_BODY, "Unrelated prose about terns entirely."],
        distinctions=[same, same]), q)
    assert len(report["distinctionPairs"]) == 1


# ── Patterns, which is the point ────────────────────────────────────────────────

_OPENER = "Something was counting on that word."
_TAIL = (" The arrangement moved when it came out, and the people around it started making "
         "private accommodations that outlasted the original failure by years.")


def _openers_collection(count: int, opener: str = _OPENER) -> List[str]:
    return [f"{opener} This is article {index}. {_TAIL} Subject {index} differs entirely, "
            f"concerning {'terns' if index % 2 else 'harbours'} and number {index * 37}."
            for index in range(count)]


def test_a_collection_of_individually_clean_articles_is_still_caught(env):
    """THE test. Ten articles, no two overlapping, all opening identically.

    Each one passes the per-article gate and the per-article dedupe. The wave does not, and
    nothing that looks at one record at a time can tell.
    """
    report = env["br"].analyse(_prepared(_openers_collection(10)), q)
    openers = [item for item in report["patterns"] if item["kind"] == "OPENER"]
    assert openers, "ten identical openings went unreported"
    assert openers[0]["count"] == 10
    assert openers[0]["share"] == 1.0
    assert openers[0]["severity"] == "DOMINANT"
    assert len(report["implicated"]) > 0


def test_a_shape_below_the_noticeable_share_is_not_reported(env):
    """A proportion is the unit. Two out of twenty is not a house tic."""
    bodies = _openers_collection(2) + [
        f"A quite different beginning number {index}. {_TAIL} Subject {index} concerns "
        f"harbours and the number {index * 91}." for index in range(18)]
    report = env["br"].analyse(_prepared(bodies), q)
    openers = [item for item in report["patterns"]
               if item["kind"] == "OPENER" and item["shape"].startswith("something was")]
    assert openers == []


def test_noticeable_and_dominant_are_separated(env):
    bodies = _openers_collection(5) + [
        f"An unrelated beginning number {index}. {_TAIL} Subject {index} concerns harbours "
        f"and the number {index * 91}." for index in range(15)]
    report = env["br"].analyse(_prepared(bodies), q)
    shared = next(item for item in report["patterns"]
                  if item["kind"] == "OPENER" and item["shape"].startswith("something was"))
    assert shared["count"] == 5
    assert shared["severity"] == "NOTICEABLE"  # 0.25, above 0.20 and below 0.33


def test_a_repeated_closer_is_reported(env):
    closer = " Nothing about that requires anybody to be good."
    bodies = [f"A distinct opening number {index} about subject {index * 7}. {_TAIL}{closer}"
              for index in range(8)]
    report = env["br"].analyse(_prepared(bodies), q)
    assert any(item["kind"] == "CLOSER" for item in report["patterns"])


def test_a_shared_title_frame_is_caught_without_shared_words(env):
    """"What a broken promise teaches about trust" and "What a missed deadline teaches about
    reliability" are one template wearing two subjects, and they share almost no content words -
    so a title similarity check misses them entirely."""
    import blog_repetition as br
    first = br.title_shape("What a broken promise teaches about trust")
    second = br.title_shape("What a missed deadline teaches about reliability")
    assert first == second

    titles = ["What a broken promise teaches about trust",
              "What a missed deadline teaches about reliability",
              "What a silent partner teaches about ownership",
              "What a late invoice teaches about goodwill",
              "What a lost receipt teaches about process",
              "What a full inbox teaches about attention",
              "A different sort of title entirely"]
    bodies = [f"Opening number {index} about subject {index * 11}. {_TAIL}"
              for index in range(len(titles))]
    report = env["br"].analyse(_prepared(bodies, titles=titles), q)
    frames = [item for item in report["patterns"] if item["kind"] == "TITLE_FRAME"]
    assert frames
    assert frames[0]["count"] == 6


def test_a_stock_phrase_used_once_each_across_the_batch_is_caught(env):
    """Section 13 allows two per article and fails at three, which is correct for one article
    and says nothing about a wave using one each."""
    phrase = q.AI_RHYTHM_PHRASES[0]
    bodies = [f"Opening number {index}. {phrase.capitalize()} the subject is {index * 13}. "
              f"{_TAIL}" for index in range(8)]
    report = env["br"].analyse(_prepared(bodies), q)
    stock = [item for item in report["patterns"] if item["kind"] == "STOCK_PHRASE"]
    assert stock
    assert stock[0]["shape"] == phrase
    assert stock[0]["count"] == 8
    #: And each article individually passes the per-article rule, which is the whole point.
    single = q.assess({"title": "T", "slug": "t", "category": "Conversations",
                       "contentMarkdown": bodies[0]})
    assert not any("AI_RHYTHM" in item for item in single["blocking"])


def test_uniform_cadence_across_the_collection_is_reported(env):
    """Human prose spreads its mean sentence length across 50 articles; a generator clusters it."""
    bodies = [" ".join(f"Sentence {word} of article {index} holds exactly seven words."
                       for word in range(12)) for index in range(10)]
    report = env["br"].analyse(_prepared(bodies), q)
    assert report["cadenceSpread"] < env["br"].CADENCE_SPREAD_MIN
    assert any(item["kind"] == "UNIFORM_CADENCE" for item in report["patterns"])


def test_varied_cadence_is_not_reported(env):
    bodies = []
    for index in range(10):
        sentences = ["Short." if index % 2 else
                     ("A considerably longer sentence which runs on for some distance and "
                      "carries several clauses before it finally arrives at its full stop, "
                      "number %d." % index)]
        bodies.append(" ".join(sentences * (3 + index)))
    report = env["br"].analyse(_prepared(bodies), q)
    assert not any(item["kind"] == "UNIFORM_CADENCE" for item in report["patterns"])


def test_patterns_are_not_reported_below_the_minimum_collection(env):
    """Two articles sharing an opening is a coincidence; the statistics say nothing."""
    report = env["br"].analyse(_prepared(_openers_collection(3)), q)
    assert report["patterns"] == []
    assert "minimum for pattern statistics" in report["note"]


def test_every_pattern_names_the_articles_it_implicates(env):
    """A finding a reviewer cannot act on is a number on a dashboard."""
    report = env["br"].analyse(_prepared(_openers_collection(8)), q)
    for pattern in report["patterns"]:
        if pattern["kind"] == "UNIFORM_CADENCE":
            continue
        assert pattern["sources"], pattern["kind"]
        assert pattern["description"]


def test_an_empty_collection_reports_nothing_rather_than_failing(env):
    report = env["br"].analyse([], q)
    assert report["articles"] == 0
    assert report["pairs"] == []
    assert "no articles" in report["note"]


def test_a_source_with_no_body_is_skipped(env):
    import blog_repetition as br
    rows = [{"id": "blogsrc_a", "draftRecord": {"contentMarkdown": ""}},
            {"id": "blogsrc_b", "draftRecord": {"contentMarkdown": GOOD_BODY}}]
    prepared = br._articles(rows, q)
    assert [item["sourceId"] for item in prepared] == ["blogsrc_b"]


# ── The run record ──────────────────────────────────────────────────────────────

def test_a_run_is_recorded_with_its_report_in_s3(env):
    batch_id = _batch(env)
    _article(env, batch_id, "ONE", GOOD_BODY)
    _article(env, batch_id, "TWO", GOOD_BODY)
    result = env["br"].run(batch_id, "admin")
    record = env["br"].get(result["repetitionRunId"])
    assert record["recordType"] == env["br"].RECORD_TYPE
    assert record["bodyKey"].startswith("secure/blog-production/repetition/")
    report = json.loads(env["s3"].objects[record["bodyKey"]].decode())
    assert report["batchId"] == batch_id
    assert report["thresholds"]["pairBody"] == env["br"].PAIR_BODY
    assert "report" not in record


def test_the_run_marks_the_sources_it_implicates(env):
    batch_id = _batch(env)
    first = _article(env, batch_id, "ONE", GOOD_BODY)
    second = _article(env, batch_id, "TWO", GOOD_BODY)
    env["br"].run(batch_id, "admin")
    assert env["bs"].get_source(first)["pipeline"]["repetitionStatus"] == "IMPLICATED"
    assert env["bs"].get_source(second)["pipeline"]["repetitionStatus"] == "IMPLICATED"


def test_a_clear_article_is_marked_clear_not_left_blank(env):
    """"checked and clear" and "never checked" are different facts, and an empty string has to
    keep meaning the second."""
    batch_id = _batch(env)
    only = _article(env, batch_id, "ONE", GOOD_BODY)
    assert env["bs"].get_source(only)["pipeline"]["repetitionStatus"] == ""
    env["br"].run(batch_id, "admin")
    assert env["bs"].get_source(only)["pipeline"]["repetitionStatus"] == "CLEAR"


def test_running_again_keeps_the_previous_run(env):
    batch_id = _batch(env)
    _article(env, batch_id, "ONE", GOOD_BODY)
    first = env["br"].run(batch_id, "admin")
    second = env["br"].run(batch_id, "admin")
    assert first["repetitionRunId"] != second["repetitionRunId"]
    assert env["br"].get(first["repetitionRunId"]) is not None
    assert [row["id"] for row in env["br"].history(batch_id)][0] == second[
        "repetitionRunId"]
    assert len(env["br"].history(batch_id)) == 2


def test_an_unknown_batch_is_refused(env):
    with pytest.raises(LookupError, match="Unknown batchId"):
        env["br"].run("blogbatch_nope", "admin")


def test_the_batch_state_is_derived_from_the_source_rows(env):
    """Not from the run's own counts: an article edited after the sweep still carries the
    status it was given, and the honest report is what the sources currently say."""
    batch_id = _batch(env)
    first = _article(env, batch_id, "ONE", GOOD_BODY)
    _article(env, batch_id, "TWO", GOOD_BODY)
    #: A genuinely different distinction as well as a different body. The default distinction in
    #: `_article` is deliberately formulaic, which the DISTINCTION pair check catches - correctly,
    #: and it would make this test assert the wrong thing.
    _article(env, batch_id, "THREE", "Unrelated prose about arctic terns and daylight.",
             distinction="Daylight rather than temperature is what the migration follows.")
    state = env["br"].batch_state(batch_id)
    assert state["unchecked"] == 3
    assert state["latestRun"] == {}

    env["br"].run(batch_id, "admin")
    state = env["br"].batch_state(batch_id)
    assert state["sources"] == 3
    assert state["implicated"] == 2
    assert state["clear"] == 1
    assert state["unchecked"] == 0
    assert state["latestRun"]["articles"] == 3
    assert state["runs"] == 1


def test_a_repetition_run_does_not_count_as_a_source(env):
    batch_id = _batch(env)
    _article(env, batch_id, "ONE", GOOD_BODY)
    env["br"].run(batch_id, "admin")
    assert env["bb"].rollup(batch_id)["sources"] == 1


def test_the_report_is_proxied_not_linked(env):
    batch_id = _batch(env)
    _article(env, batch_id, "ONE", GOOD_BODY)
    detail = env["br"].detail(env["br"].run(batch_id, "admin")["repetitionRunId"])
    assert detail["report"]["batchId"] == batch_id
    for key in detail:
        assert "url" not in key.lower(), key


# ── The boundary ────────────────────────────────────────────────────────────────

def test_repetition_never_blocks_a_release(env):
    """A proportion is not a defect in any individual article, and picking one of fifty
    identical openings to refuse would be arbitrary. The reviewer decides."""
    import blog_qa as bq
    batch_id = _batch(env)
    first = _article(env, batch_id, "ONE", GOOD_BODY)
    _article(env, batch_id, "TWO", GOOD_BODY)
    env["br"].run(batch_id, "admin")
    assert env["bs"].get_source(first)["pipeline"]["repetitionStatus"] == "IMPLICATED"
    #: The release path's refusal is about the sign-off, never about repetition.
    ok, reason = bq.releasable(first)
    assert ok is False
    assert "repetition" not in reason.lower()


def test_the_repetition_status_is_not_model_writable(env):
    import blog_draft as bd
    for forbidden in ("repetitionStatus", "pipeline"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_the_sweep_is_affordable_at_collection_scale(env):
    """400 articles is 79,800 pairs. The prefilter has to cut that to something a Lambda can
    finish, and it has to do so without discarding a real duplicate.

    The two inserted duplicates are the control: if the prefilter were over-aggressive they
    would vanish, and the test would pass on speed while the module had stopped working.
    """
    import time
    bodies = [
        f"Article {index} opens on the subject of {index * 7} and continues. "
        f"The harbour at {index} was built in {1700 + index} for reasons nobody wrote down, "
        f"and the {index} berths it holds have silted differently ever since. "
        f"Number {index * 13} is what the survey recorded, and number {index * 29} is what "
        f"the dredger found. Neither figure explains the {index * 3} feet of difference."
        for index in range(400)
    ]
    bodies.append(bodies[0])  # an exact duplicate of article 0
    articles = _prepared(bodies)

    started = time.monotonic()
    pairs = env["br"].candidate_pairs([item["sketch"] for item in articles])
    elapsed = time.monotonic() - started

    total_pairs = len(articles) * (len(articles) - 1) // 2
    assert total_pairs > 80_000
    assert len(pairs) < total_pairs / 10, (
        f"the prefilter kept {len(pairs)} of {total_pairs} pairs, which is not a reduction")
    assert elapsed < 5.0, f"the prefilter took {elapsed:.1f}s"
    # The planted duplicate survives the filter and is scored.
    assert (0, 400) in pairs
    report = env["br"].analyse(articles, q)
    assert any({item["a"], item["b"]} == {articles[0]["sourceId"], articles[400]["sourceId"]}
               for item in report["pairs"])


def test_the_pair_threshold_matches_the_published_corpus_threshold(env):
    """A sibling still in flight and a sibling already published must not be judged by
    different numbers."""
    assert env["br"].PAIR_BODY == q.CorpusIndex.BODY_SIMILARITY
    assert env["br"].PAIR_BODY_NEAR_DUPLICATE == q.CorpusIndex.BODY_NEAR_DUPLICATE
    assert env["br"].PAIR_TITLE == q.CorpusIndex.TITLE_SIMILARITY
    assert env["br"].PAIR_DISTINCTION == q.CorpusIndex.DISTINCTION_SIMILARITY
