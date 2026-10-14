"""Thirteen assertions against the post that actually went live.

WHY THIS FILE EXISTS AT ALL, GIVEN THE PUBLISH REPORTED SUCCESS.

A successful write is not evidence of a correct post. A slug collision, a dropped node, or a
category that no longer exists would each leave a live article a reader sees and no record
mentions. Reading the post back from the public path and checking it against what was approved is
the only thing that catches that.

THE TWO TESTS THAT CARRY THE FILE.

`test_all_thirteen_assertions_are_enumerated`. A verification suite that shrinks silently is worse
than none, because the report keeps saying "verified".

`test_the_expectation_comes_from_the_signoff_not_the_current_draft`. The draft can be edited after
publication, and verifying against it would report a failure for an article that went live exactly
as approved.

WIX EXIT: publishing writes to the AWS-native store via `storage.create_blog_post`, so a live post
now carries a native `blog_<hex>` id (under `id`) and only markdown `content` - there is no Wix
rich-content node tree. The live-post fixture mirrors the native read shape (`storage._blog_view`).
`blog_verify.run()` reads the live post back through the native public seam
`blog_source.get_blog_post_by_slug` - the same source the live site serves, filtered to published
only. These tests patch that call and feed it the native shape so the expectations align with the
native contract.
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
from test_blog_qa import GOOD_BODY, PROSE, DISTINCTION, STATEMENT  # noqa: E402
from test_blog_publish import FakeStore  # noqa: E402

#: The native post id `storage.create_blog_post` returns for a published post. The live-post
#: fixture puts this under `id` (the native read shape), which is what POST_ID_MATCHES compares
#: the recorded publish `postId` against.
POST_ID = "blog_test1"


@pytest.fixture()
def env(monkeypatch):
    import blog_analysis as ba
    import blog_batches as bb
    import blog_gate as bg
    import blog_publish as bp
    import blog_qa as bq
    import blog_source
    import blog_sources as bs
    import blog_verify as bv
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    store = FakeStore()
    live: Dict[str, Dict[str, Any]] = {}
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(storage, "create_blog_post", store.create_blog_post)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    #: `blog_verify.run()` reads the live post back through the native public seam
    #: `blog_source.get_blog_post_by_slug` (the same source the live site serves). Patch exactly
    #: that call and return the native read shape so the thirteen are checked against the native
    #: contract.
    monkeypatch.setattr(blog_source, "get_blog_post_by_slug", lambda slug: live.get(slug))
    monkeypatch.setenv("WIX_BLOG_AUTHOR_NAME", q.AUTHOR)
    bg.reset_corpus_cache()
    index = q.CorpusIndex()
    index.add({"slug": "an-unrelated-article", "title": "Something else entirely",
               "category": "Conversations",
               "contentMarkdown": "Quite different prose about an unrelated subject at "
                                  "sufficient length to produce a comparable sketch."},
              origin="test-corpus")
    monkeypatch.setattr(bg, "_corpus", index)
    monkeypatch.setattr(bg, "_corpus_state", {"loaded": 1, "present": True, "path": "test",
                                              "packaged": True, "builtAt": "", "note": ""})
    yield {"table": table, "s3": s3, "store": store, "live": live, "ba": ba, "bb": bb,
           "bg": bg, "bp": bp, "bq": bq, "bs": bs, "bv": bv, "storage": storage}
    bg.reset_corpus_cache()


def sample_pdf(header: str = "THE GIVEN WORD") -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


SEO_TITLE = "The given word | WECARE.DIGITAL"
META = ("What breaks when a commitment fails, read as a question about workability rather "
        "than about character or good intent.")


def _published(env, batch_id: str = "", header: str = "THE GIVEN WORD") -> Dict[str, Any]:
    """A source carried all the way to PUBLISHED, with a matching live post registered."""
    import blog_qa
    payload = sample_pdf(header)
    body: Dict[str, Any] = {"category": "Conversations", "sources": [_pdf_entry(payload)]}
    if batch_id:
        body["batchId"] = batch_id
    result = env["bs"].register(body, "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})

    analysis_id = env["ba"].analyse(source_id, "admin")["analysisId"]
    env["ba"].record_review({"analysisId": analysis_id, "sourceReviewedFully": "YES",
                             "centralDistinctionCandidate": DISTINCTION,
                             "originalSourceDate": "1987"}, "editor")
    slug = q.slugify(f"the given word {header.lower()}")
    draft = dict(env["bs"].get_source(source_id)["draftRecord"])
    draft.update({
        "contentMarkdown": GOOD_BODY,
        "title": f"The given word {header.lower()}",
        "slug": slug,
        "canonical": q.expected_canonical(slug),
        "seoTitle": f"The given word {header.lower()} | WECARE.DIGITAL",
        "metaDescription": META,
        "tags": ["integrity"],
        "articleType": "REFLECTION",
        "centralDistinction": DISTINCTION,
        "distinctPurpose": ("It separates repair as work from repair as apology, which no "
                            "other article on the site takes as its subject."),
        "originalSourceDate": "1987",
    })
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)

    qa = env["bq"].run(source_id, "qa")
    env["bq"].sign_off({
        "qaRunId": qa["qaRunId"], "gates": {name: "PASS" for name in q.HUMAN_GATES},
        "declarations": {name: expected for name, expected in blog_qa.DECLARATIONS},
        "statement": STATEMENT}, "editor")
    job = env["bp"].release(source_id, "operator")
    published = env["bp"].publish(job["jobId"], "operator")

    #: The live post's id is the id the NATIVE publish actually recorded, not a fixed
    #: "post-1". `_write_native` -> `storage.create_blog_post` mints `blog_<uuid>` and the
    #: job records it, and the native read seam returns that same id for this slug - so
    #: POST_ID_MATCHES compares the recorded id against the id the read returns, which is the
    #: honest invariant. Seeding "post-1" here was the stale Wix response shape and is what
    #: made the assertion mismatch under native publish.
    env["live"][slug] = _live_post(slug, draft, id=str(published["postId"]))
    return {"sourceId": source_id, "slug": slug, "draft": draft, "jobId": job["jobId"],
            "postId": str(published["postId"])}


def _live_post(slug: str, draft: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """The native public read shape for a correctly published post, mirroring
    `storage._blog_view`.

    The id defaults to the native `blog_<hex>` shape but is overridden by `_published` with the id
    the publish actually recorded, so a correct post matches on POST_ID_MATCHES. The body is
    markdown under `content`/`contentText`; the native store has no Wix rich-content node tree, so
    `richContent` is empty - `verify_post` reads the body from `content`, and NO_MEDIA_NODES /
    NO_LEGACY_MARKUP see an empty tree exactly as the native store serves it.
    """
    body = q.strip_markdown(str(draft["contentMarkdown"]))
    post = {
        "id": "blog_native",
        "title": str(draft["title"]),
        "slug": slug,
        "url": f"https://wecare.digital/post/{slug}",
        "seoTitle": str(draft["seoTitle"]),
        "metaDescription": str(draft["metaDescription"]),
        "category": "Conversations",
        "authorName": q.AUTHOR,
        "content": body,
        "contentText": body,
        "richContent": {},
    }
    post.update(overrides)
    return post


# ── The thirteen ────────────────────────────────────────────────────────────────

def test_all_thirteen_assertions_are_enumerated(env):
    """A suite that shrinks silently is worse than none: the report keeps saying "verified"."""
    assert len(env["bv"].ASSERTIONS) == 13
    assert len(set(env["bv"].assertion_ids())) == 13
    for name, description in env["bv"].ASSERTIONS:
        assert name.isupper()
        assert len(description) > 20, f"{name} has no description"


def test_a_correct_post_passes_all_thirteen(env):
    published = _published(env)
    result = env["bv"].run(published["sourceId"], "operator")
    assert result["assertions"] == 13
    assert result["failed"] == 0, result["failedAssertions"]
    assert result["passed"] + result["skipped"] == 13
    assert result["status"] == "VERIFIED"


def test_every_assertion_reports_expected_and_found(env):
    """A finding a reviewer cannot act on is a number on a dashboard."""
    published = _published(env)
    report = env["bv"].run(published["sourceId"], "operator")["report"]
    names = [item["assertion"] for item in report["results"]]
    assert names == list(env["bv"].assertion_ids())
    for item in report["results"]:
        assert item["result"] in ("PASS", "FAIL", "SKIP")
        assert item["description"], item["assertion"]


def test_a_missing_post_fails_one_assertion_and_skips_the_rest(env):
    """Reporting thirteen failures for one missing post buries the fact that matters."""
    published = _published(env)
    del env["live"][published["slug"]]
    result = env["bv"].run(published["sourceId"], "operator")
    assert result["failedAssertions"] == ["POST_IS_LIVE"]
    assert result["skipped"] == 12
    assert result["status"] == "FAILED"


@pytest.mark.parametrize("field,value,assertion", [
    ("id", "post-other", "POST_ID_MATCHES"),
    ("title", "A different title entirely", "TITLE_MATCHES"),
    ("seoTitle", "Something else | WECARE.DIGITAL", "SEO_TITLE_MATCHES"),
    ("metaDescription", "A different description of the article.",
     "META_DESCRIPTION_MATCHES"),
    ("category", "Gastronomy", "CATEGORY_MATCHES"),
    ("authorName", "Somebody Else", "AUTHOR_MATCHES"),
])
def test_a_mismatched_field_fails_its_own_assertion(env, field, value, assertion):
    published = _published(env)
    env["live"][published["slug"]][field] = value
    result = env["bv"].run(published["sourceId"], "operator")
    assert assertion in result["failedAssertions"]
    assert result["status"] == "FAILED"


def test_a_wix_appended_slug_suffix_is_its_own_failure(env):
    """A suffixed slug means another post already held the URL - a duplication problem wearing
    a routing problem's clothes, which is why it is not folded into CANONICAL_MATCHES."""
    published = _published(env)
    live = env["live"].pop(published["slug"])
    suffixed = published["slug"] + "-2"
    live["slug"] = suffixed
    live["url"] = f"https://wecare.digital/post/{suffixed}/"
    env["live"][published["slug"]] = live
    report = env["bv"].run(published["sourceId"], "operator")["report"]
    slug_result = next(item for item in report["results"]
                       if item["assertion"] == "SLUG_MATCHES")
    assert slug_result["result"] == "FAIL"
    assert "numeric suffix" in slug_result["note"]
    assert "duplication problem" in slug_result["note"]


def test_a_truncated_body_fails_body_intact(env):
    published = _published(env)
    env["live"][published["slug"]]["content"] = q.strip_markdown(GOOD_BODY)[:300]
    env["live"][published["slug"]]["richContent"] = {}
    result = env["bv"].run(published["sourceId"], "operator")
    assert "BODY_INTACT" in result["failedAssertions"]


def test_a_normalisation_in_the_body_still_passes(env):
    """Wix round-trips prose through Ricos, which can normalise a quote or collapse a space.
    Requiring an exact match would fail every correct post, and a check that fails on
    correctness gets switched off."""
    published = _published(env)
    round_tripped = q.strip_markdown(GOOD_BODY).replace("  ", " ").replace("'", "\u2019")
    env["live"][published["slug"]]["content"] = round_tripped
    result = env["bv"].run(published["sourceId"], "operator")
    assert "BODY_INTACT" not in result["failedAssertions"]


def test_a_media_node_in_the_live_post_fails(env):
    """Section 27. Wix can accept a node the compiler never emitted, or a later edit can add one."""
    published = _published(env)
    env["live"][published["slug"]]["richContent"] = {
        "nodes": [{"type": "IMAGE", "imageData": {"image": {"id": "x"}}}]}
    result = env["bv"].run(published["sourceId"], "operator")
    assert "NO_MEDIA_NODES" in result["failedAssertions"]
    report = env["bv"].run(published["sourceId"], "operator")["report"]
    media = next(item for item in report["results"]
                 if item["assertion"] == "NO_MEDIA_NODES")
    assert "IMAGE" in media["found"]


def test_legacy_markup_in_the_live_post_fails(env):
    """Section 26. Typography belongs to the frontend and none of it may survive."""
    published = _published(env)
    env["live"][published["slug"]]["content"] = (
        q.strip_markdown(GOOD_BODY) + ' <font color="#333">still here</font>&nbsp;')
    result = env["bv"].run(published["sourceId"], "operator")
    assert "NO_LEGACY_MARKUP" in result["failedAssertions"]


def test_a_trailing_slash_is_not_a_canonical_failure(env):
    """The two URL builders agree TODAY, and the tolerance is there so they may stop.

    `wix._blog_view` builds `/post/<slug>/` and `q.expected_canonical` also ends with a slash, so
    there is no mismatch to absorb right now - the original version of this test claimed there was
    and failed on its own premise. The tolerance still earns its place: either builder changing its
    trailing slash would otherwise make CANONICAL_MATCHES fail on every correct post, and a check
    that fails on correctness gets switched off.
    """
    assert q.expected_canonical("a-slug").endswith("/")
    assert env["bv"]._same_url("https://wecare.digital/post/a-slug/",
                               "https://wecare.digital/post/a-slug") is True
    assert env["bv"]._same_url("https://wecare.digital/post/a-slug",
                               "https://wecare.digital/post/a-slug/") is True
    assert env["bv"]._same_url("https://wecare.digital/post/a-slug",
                               "https://wecare.digital/post/b-slug") is False

    published = _published(env)
    result = env["bv"].run(published["sourceId"], "operator")
    assert "CANONICAL_MATCHES" not in result["failedAssertions"]


def test_a_wrong_canonical_fails(env):
    published = _published(env)
    env["live"][published["slug"]]["url"] = "https://example.com/blog/something-else"
    result = env["bv"].run(published["sourceId"], "operator")
    assert "CANONICAL_MATCHES" in result["failedAssertions"]


def test_several_failures_are_all_reported(env):
    """An operator fixing one at a time needs the whole list, not the first one."""
    published = _published(env)
    env["live"][published["slug"]].update({
        "title": "Wrong", "authorName": "Wrong", "category": "Gastronomy"})
    result = env["bv"].run(published["sourceId"], "operator")
    assert set(result["failedAssertions"]) >= {"TITLE_MATCHES", "AUTHOR_MATCHES",
                                               "CATEGORY_MATCHES"}


# ── The expectation ─────────────────────────────────────────────────────────────

def test_the_expectation_comes_from_the_signoff_not_the_current_draft(env):
    """THE test. The draft can be edited after publication; verifying against it would report a
    failure for an article that went live exactly as approved."""
    published = _published(env)
    source_id = published["sourceId"]
    #: Edit the draft AFTER publication - a routine thing while preparing a correction.
    draft = dict(env["bs"].get_source(source_id)["draftRecord"])
    draft["title"] = "A title nobody published"
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)

    wanted = env["bv"].expectation(source_id)
    assert wanted["title"] == published["draft"]["title"], (
        "the expectation followed the edited draft instead of the publish record")
    result = env["bv"].run(source_id, "operator")
    assert "TITLE_MATCHES" not in result["failedAssertions"]


def test_the_expectation_carries_the_signed_body_hash(env):
    published = _published(env)
    wanted = env["bv"].expectation(published["sourceId"])
    signoff = env["bq"].current_signoff(published["sourceId"])
    assert wanted["bodySha256"] == signoff["bodySha256"]
    assert len(wanted["bodySha256"]) == 64


def test_an_unpublished_article_cannot_be_verified(env):
    """Verification is about what went live. There is nothing to read back."""
    payload = sample_pdf("UNPUBLISHED")
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload)]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})
    with pytest.raises(ValueError, match="only a published article"):
        env["bv"].run(source_id, "operator")


def test_an_unknown_source_is_refused(env):
    with pytest.raises(LookupError, match="Unknown sourceId"):
        env["bv"].run("blogsrc_nope", "operator")


def test_an_absent_reference_is_a_miss_not_an_error(env):
    """DynamoDB rejects `Key={'id': ''}` with a ValidationException rather than returning
    nothing, and every blog module had its own unguarded `get`.

    That surfaced as a 500 from a live verification run on an article with no recorded sign-off id,
    where the correct answer was simply "there is no sign-off" - and the suite had passed, because
    the fake accepted an empty key. `storage.get_typed` guards it once for every record type, and
    `FakeTable.get_item` now raises the way DynamoDB does so the next one fails here.
    """
    import blog_qa
    import blog_templates
    import storage
    for getter in (env["bv"].get, env["bp"].get, blog_qa.get_run, blog_qa.get_signoff,
                   blog_templates.get, env["ba"].get, env["bb"].get, env["bs"].get_source):
        assert getter("") is None
        assert getter(None) is None
        assert getter("   ") is None
    #: And the type check is not decoration: a source id where a QA run id belongs must miss.
    published = _published(env)
    assert blog_qa.get_run(published["sourceId"]) is None
    assert storage.get_typed(published["sourceId"], "blogSource") is not None


def test_an_article_with_no_signoff_reference_still_verifies(env):
    """The exact shape that failed live: a published article whose publish record and pipeline
    both carry an empty signoffId."""
    published = _published(env)
    source_id = published["sourceId"]
    env["bs"].update_pipeline(source_id, signoffId="")
    env["s3"].objects.pop(env["bp"].record_key(source_id), None)
    wanted = env["bv"].expectation(source_id)
    assert wanted["slug"] == published["slug"]
    result = env["bv"].run(source_id, "operator")
    assert result["assertions"] == 13
    #: The signed hash is simply absent, so that assertion SKIPs rather than failing.
    report = result["report"]
    hash_result = next(item for item in report["results"]
                       if item["assertion"] == "BODY_HASH_MATCHES_SIGNOFF")
    assert hash_result["result"] in ("PASS", "SKIP")


# ── The read path ───────────────────────────────────────────────────────────────

def test_verification_reads_the_native_published_only_view(env):
    """It proves the article is actually PUBLIC rather than merely created.

    WIX EXIT COMPLETE: there is no longer a public-vs-authenticated token distinction - there is
    one AWS-native store. The invariant that mattered survives: verification reads through the
    PUBLISHED-only view (`storage.get_blog_post(slug, published_only=True)`, which the public read
    seam `blog_source.get_blog_post_by_slug` serves), so an article that exists only as a draft is
    invisible to verification exactly as it is to a reader. A draft read would otherwise report
    "verified" on a post nobody can reach.

    The old test drove a Wix public-vs-authenticated token distinction and asserted verification
    still worked while the kill switch was on. Both the second token and the kill switch are gone,
    so this asserts the one native fact underneath: the read seam filters to published only.
    """
    import storage

    #: The normal run still verifies through the fixture's live map.
    published = _published(env)
    assert env["bv"].run(published["sourceId"], "operator")["status"] == "VERIFIED"

    #: And the native read seam the verifier calls is the PUBLISHED-only one. Write a published and
    #: a draft blogPost record straight into the store and assert the filter: the published slug
    #: resolves, the draft slug does not - which is why a verification run cannot certify a draft.
    env["table"].items["blog_pub"] = storage._clean({
        "id": "blog_pub", "recordType": storage.BLOG_RECORD_TYPE, "createdAt": storage.now_iso(),
        "slug": "a-published-post", "title": "Published", "status": "published",
        "content": "Body."})
    env["table"].items["blog_dft"] = storage._clean({
        "id": "blog_dft", "recordType": storage.BLOG_RECORD_TYPE, "createdAt": storage.now_iso(),
        "slug": "a-draft-post", "title": "Draft", "status": "draft", "content": "Body."})
    #: The env fixture monkeypatches blog_source.get_blog_post_by_slug to drive the verifier off
    #: the fixture's live map, so call the real published-only filter directly through storage —
    #: the exact delegate blog_source.get_blog_post_by_slug wraps.
    assert storage.get_blog_post("a-published-post", published_only=True)["id"] == "blog_pub"
    assert storage.get_blog_post("a-draft-post", published_only=True) is None


def test_an_unreachable_store_is_an_outcome_not_an_exception(env, monkeypatch):
    """"the store is unreachable" and "the post is not there" are different facts, and the report
    has to say which."""
    import blog_source
    published = _published(env)

    def exploding(slug):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(blog_source, "get_blog_post_by_slug", exploding)
    result = env["bv"].run(published["sourceId"], "operator")
    assert result["readError"] == "RuntimeError"
    assert result["failedAssertions"] == ["POST_IS_LIVE"]
    assert result["status"] == "FAILED"


# ── The record ──────────────────────────────────────────────────────────────────

def test_a_run_is_recorded_with_its_report_in_s3(env):
    published = _published(env)
    result = env["bv"].run(published["sourceId"], "operator")
    record = env["bv"].get(result["verificationRunId"])
    assert record["recordType"] == env["bv"].RECORD_TYPE
    assert record["bodyKey"].startswith("o/blog-production/verification/")
    report = json.loads(env["s3"].objects[record["bodyKey"]].decode())
    assert len(report["results"]) == 13
    assert report["sourceId"] == published["sourceId"]
    assert "report" not in record


def test_the_report_does_not_carry_the_whole_body(env):
    """A verification report is a verdict, not a second copy of the article."""
    published = _published(env)
    result = env["bv"].run(published["sourceId"], "operator")
    report = result["report"]
    assert "body" not in report["expected"]
    assert report["bodyLength"] > 0


def test_a_failure_is_recorded_and_not_retried(env):
    published = _published(env)
    env["live"][published["slug"]]["title"] = "Wrong"
    first = env["bv"].run(published["sourceId"], "operator")
    assert first["status"] == "FAILED"
    assert "Nothing is retried automatically" in first["note"]
    #: Still readable afterwards, and a second run is a second record rather than a mutation.
    second = env["bv"].run(published["sourceId"], "operator")
    assert second["verificationRunId"] != first["verificationRunId"]
    assert env["bv"].get(first["verificationRunId"]) is not None
    assert len(env["bv"].history(published["sourceId"])) == 2


def test_a_passing_run_moves_the_article_to_verified(env):
    """The only status transition in this system earned by reading the live site."""
    published = _published(env)
    before = env["bs"].get_source(published["sourceId"])
    assert before["articleStatus"] != "VERIFIED"
    env["bv"].run(published["sourceId"], "operator")
    after = env["bs"].get_source(published["sourceId"])
    assert after["articleStatus"] == "VERIFIED"
    assert after["draftRecord"]["status"] == "VERIFIED"
    assert after["pipeline"]["verifyStatus"] == "VERIFIED"
    assert after["pipeline"]["verifiedAt"]


def test_a_failing_run_does_not_move_the_article(env):
    published = _published(env)
    env["live"][published["slug"]]["authorName"] = "Somebody Else"
    env["bv"].run(published["sourceId"], "operator")
    after = env["bs"].get_source(published["sourceId"])
    assert after["articleStatus"] != "VERIFIED"
    assert after["pipeline"]["verifyStatus"] == "FAILED"


def test_the_report_is_proxied_not_linked(env):
    published = _published(env)
    detail = env["bv"].detail(
        env["bv"].run(published["sourceId"], "operator")["verificationRunId"])
    assert len(detail["report"]["results"]) == 13
    for key in detail:
        assert "url" not in key.lower(), key


# ── Batch reporting ─────────────────────────────────────────────────────────────

def test_the_batch_state_counts_published_but_unverified(env):
    """Those are live articles nobody has looked at, which is the number that matters."""
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    first = _published(env, batch_id, "ONE")
    _published(env, batch_id, "TWO")
    state = env["bv"].batch_verify_state(batch_id)
    assert state["sources"] == 2
    assert state["published"] == 2
    assert state["verified"] == 0
    assert state["awaitingVerification"] == 2

    env["bv"].run(first["sourceId"], "operator")
    state = env["bv"].batch_verify_state(batch_id)
    assert state["verified"] == 1
    assert state["awaitingVerification"] == 1
    assert state["runs"] == 1


def test_pending_verification_lists_live_unchecked_articles(env):
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    first = _published(env, batch_id, "ONE")
    second = _published(env, batch_id, "TWO")
    assert set(env["bv"].pending_verification(batch_id)) == {first["sourceId"],
                                                            second["sourceId"]}
    env["bv"].run(first["sourceId"], "operator")
    assert env["bv"].pending_verification(batch_id) == [second["sourceId"]]


def test_a_verification_run_does_not_count_as_a_source(env):
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    published = _published(env, batch_id, "ONE")
    env["bv"].run(published["sourceId"], "operator")
    assert env["bb"].rollup(batch_id)["sources"] == 1


# ── The boundary ────────────────────────────────────────────────────────────────

def test_verification_makes_no_post_mutation(env):
    """Verification reads the live post and records its own run; it must never write a post.

    WIX EXIT: this used to assert no Wix `draft-posts` mutation was issued. Natively the only way
    to write a post is `storage.create_blog_post` (the publish writer), so the native form of the
    invariant is that a verification run never calls it.
    """
    published = _published(env)
    env["store"].calls.clear()
    env["bv"].run(published["sourceId"], "operator")
    assert env["store"].calls == []


def test_verification_is_not_a_model_writable_field(env):
    import blog_draft as bd
    for forbidden in ("verifyStatus", "verifiedAt"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_nothing_verifies_automatically(env):
    """Verification is an operator action. Nothing in the publish path triggers it, because a
    self-verifying publish is a publish that certifies itself."""
    import ast
    source = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
    for name in ("blog_publish.py", "blog_queue.py", "blog_sources.py", "blog_batches.py"):
        tree = ast.parse((source / name).read_text(encoding="utf-8"))
        imported, called = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                called.add(node.value.id)
        assert "blog_verify" not in imported, f"{name} imports blog_verify"
        assert "blog_verify" not in called, f"{name} calls into blog_verify"
