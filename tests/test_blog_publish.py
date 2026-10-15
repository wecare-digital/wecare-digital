"""The publish queue, and the one failure this domain cannot recover from.

THE FOUR TESTS THAT CARRY THIS FILE.

`test_releasing_twice_resolves_to_the_same_job`. Publishing the same article twice cannot be
undone: a duplicate post gets indexed, linked and cited, and deleting it afterwards leaves a dead
URL where a real one was. A second job is how that happens.

`test_two_concurrent_publishers_cannot_both_write`. The conditional QUEUED -> PUBLISHING claim.
Two operators pressing Publish at the same moment would otherwise both reach the native write.

`test_an_edit_after_release_blocks_the_publish`. Release time and publish time are different
moments, and the queue is exactly where the gap lives.

`test_nothing_in_the_pipeline_can_release`. Section 38: processing completion must never
automatically mean publishing. Enforced by grepping the modules, because that is the kind of
convenience somebody adds later.

Publishing writes to the AWS-native store via `storage.create_blog_post`. There is no external
credential and no kill switch on that path, so a publish is NEVER REFUSED - a write that does not
succeed is always FAILED. Every test here runs against the native fake below.
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


POST_ID = "blog_test1"


class FakeStore:
    """The native blog-store surface `blog_publish` touches: a stand-in for
    `storage.create_blog_post`.

    Records every write so a test can assert "written exactly once", and returns the native shape
    (`postId` of the form `blog_<hex>`, a `url` under /post/<slug>). It also PERSISTS a published
    `blogPost` record into the fake table the way the real `storage.create_blog_post` does, so a
    test that drives the real native read seam (`storage.get_blog_post` /
    `blog_source.get_blog_post_by_slug`) reads back the exact record this write produced.

    `raise_on_write` models a native-store failure - the FAILED path, the only way a publish
    does not succeed.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.raise_on_write = False
        self.error = "the native blog store rejected the post"
        self._seq = 0

    def create_blog_post(self, body, actor):
        self.calls.append({"body": body, "actor": actor})
        if self.raise_on_write:
            raise RuntimeError(self.error)
        import storage
        slug = str(body.get("slug") or "")
        #: A stable id for the first post (so the single-publish tests can assert POST_ID) and a
        #: unique id for any further posts, mirroring the native `blog_<hex>` shape.
        post_id = POST_ID if self._seq == 0 else f"{POST_ID}_{self._seq}"
        self._seq += 1
        now = storage.now_iso()
        status = str(body.get("status") or "published").strip().lower()
        record = {
            "id": post_id,
            "recordType": "blogPost",
            "createdAt": now,
            "updatedAt": now,
            "publishedAt": now if status == "published" else "",
            "slug": slug,
            "title": str(body.get("title") or ""),
            "excerpt": str(body.get("excerpt") or ""),
            "content": body.get("content") or "",
            "status": status,
            "category": str(body.get("category") or ""),
            "tags": body.get("tags") or body.get("tagLabels") or [],
            "hashtags": body.get("hashtags") or [],
            "coverImage": str(body.get("coverImage") or ""),
            "authorName": str(body.get("authorName") or actor or "WECARE.DIGITAL"),
            "seoTitle": str(body.get("seoTitle") or ""),
            "metaDescription": str(body.get("metaDescription") or ""),
            "focusKeyword": str(body.get("focusKeyword") or ""),
            "secondaryKeywords": body.get("secondaryKeywords") or [],
            "jsonLd": body.get("jsonLd") or {},
            "robots": "index, follow, max-image-preview:large",
            "url": f"https://wecare.digital/post/{slug}",
            "version": 1,
            "createdBy": actor,
            "updatedBy": actor,
        }
        storage.put_record(record)
        return {"postId": post_id, "slug": slug, "title": record["title"],
                "status": status, "url": record["url"],
                "rebuildRequired": status == "published"}


@pytest.fixture()
def env(monkeypatch):
    import blog_analysis as ba
    import blog_batches as bb
    import blog_gate as bg
    import blog_publish as bp
    import blog_qa as bq
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    store = FakeStore()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(storage, "create_blog_post", store.create_blog_post)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
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
    yield {"table": table, "s3": s3, "store": store, "ba": ba, "bb": bb, "bg": bg,
           "bp": bp, "bq": bq, "bs": bs, "storage": storage}
    bg.reset_corpus_cache()


def sample_pdf(header: str = "THE GIVEN WORD") -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


def _signed(env, batch_id: str = "", header: str = "THE GIVEN WORD") -> str:
    """A source all the way through to a valid gate sign-off."""
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
    record = env["bs"].get_source(source_id)
    draft = dict(record["draftRecord"])
    slug = q.slugify(f"the given word {header.lower()}")
    draft.update({
        "contentMarkdown": GOOD_BODY,
        "title": f"The given word {header.lower()}",
        "slug": slug,
        "canonical": q.expected_canonical(slug),
        "seoTitle": f"The given word {header.lower()} | WECARE.DIGITAL",
        "metaDescription": ("What breaks when a commitment fails, read as a question about "
                            "workability rather than about character or good intent."),
        "tags": ["integrity"],
        "articleType": "REFLECTION",
        "centralDistinction": DISTINCTION,
        "distinctPurpose": ("It separates repair as work from repair as apology, which no "
                            "other article on the site takes as its subject."),
        "originalSourceDate": "1987",
    })
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)

    qa = env["bq"].run(source_id, "qa")
    import blog_qa
    env["bq"].sign_off({
        "qaRunId": qa["qaRunId"],
        "gates": {name: "PASS" for name in q.HUMAN_GATES},
        "declarations": {name: expected for name, expected in blog_qa.DECLARATIONS},
        "statement": STATEMENT}, "editor")
    return source_id


# ── Release records a decision and nothing more ─────────────────────────────────

def test_releasing_queues_without_publishing(env):
    source_id = _signed(env)
    env["store"].calls.clear()
    job = env["bp"].release(source_id, "operator")
    assert job["status"] == env["bp"].QUEUED
    assert job["created"] is True
    assert job["postId"] == ""
    assert env["store"].calls == [], "release wrote a post"
    assert env["bs"].get_source(source_id)["pipeline"]["publishStatus"] == "QUEUED"


def test_a_release_records_what_it_rests_on(env):
    """source -> reading -> QA -> signature -> release, complete in the records."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    signoff = env["bq"].current_signoff(source_id)
    assert job["signoffId"] == signoff["id"]
    assert job["qaRunId"] == signoff["qaRunId"]
    assert job["bodySha256"] == signoff["bodySha256"]
    assert job["releasedBy"] == "operator"
    assert job["articleSlug"]


def test_releasing_twice_resolves_to_the_same_job(env):
    """THE test. A second job is how the same article gets posted twice."""
    source_id = _signed(env)
    first = env["bp"].release(source_id, "operator")
    second = env["bp"].release(source_id, "operator")
    assert second["jobId"] == first["jobId"]
    assert second["created"] is False
    assert "already has a QUEUED job" in second["note"]
    assert len(env["bp"].jobs_for(source_id)) == 1


def test_releasing_after_publishing_is_still_a_no_op(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    again = env["bp"].release(source_id, "operator")
    assert again["created"] is False
    assert again["status"] == env["bp"].PUBLISHED
    assert len(env["bp"].jobs_for(source_id)) == 1


def test_a_release_is_refused_without_a_signoff(env):
    payload = sample_pdf("UNSIGNED")
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload)]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bs"].run_worker({})
    with pytest.raises(ValueError, match="cannot be released"):
        env["bp"].release(source_id, "operator")
    assert env["bp"].jobs_for(source_id) == []


def test_a_release_is_refused_after_the_signoff_is_revoked(env):
    source_id = _signed(env)
    signoff = env["bq"].current_signoff(source_id)
    env["bq"].revoke(signoff["id"], "the second quotation needs re-checking", "editor")
    with pytest.raises(ValueError, match="no gate sign-off"):
        env["bp"].release(source_id, "operator")


def test_an_unknown_source_is_refused(env):
    with pytest.raises(LookupError, match="Unknown sourceId"):
        env["bp"].release("blogsrc_nope", "operator")


# ── Withdrawal ──────────────────────────────────────────────────────────────────

def test_a_queued_job_can_be_withdrawn(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    result = env["bp"].unrelease(job["jobId"], "holding this wave for a second read",
                                "operator")
    assert result["withdrawn"] is True
    assert env["bs"].get_source(source_id)["pipeline"]["publishStatus"] == ""
    # And it can be released again afterwards.
    assert env["bp"].release(source_id, "operator")["created"] is True


def test_a_published_job_cannot_be_withdrawn(env):
    """A live post comes down through the native blog store, which is outside this module's
    authority. Pretending otherwise would be a lie told to an operator during an incident."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    with pytest.raises(ValueError, match="only a QUEUED job"):
        env["bp"].unrelease(job["jobId"], "changed our mind about this one", "operator")


def test_a_withdrawal_needs_a_reason(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    with pytest.raises(ValueError, match="reason"):
        env["bp"].unrelease(job["jobId"], "no", "operator")


# ── Publish ─────────────────────────────────────────────────────────────────────

def test_publishing_writes_once_and_records_the_post(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    result = env["bp"].publish(job["jobId"], "operator")
    assert result["published"] is True
    assert result["postId"] == POST_ID
    assert result["postUrl"].startswith("https://wecare.digital/post/")
    #: WRITTEN EXACTLY ONCE. One `storage.create_blog_post` call is how "it cannot post twice"
    #: is demonstrated rather than asserted.
    assert len(env["store"].calls) == 1
    assert env["store"].calls[0]["body"]["status"] == "published"


def test_the_published_body_is_the_approved_markdown(env):
    """Native: the approved draft markdown is written as-is to the store, and the native read
    path renders it. What matters is that the body that goes to `storage.create_blog_post` is
    exactly the signed-off markdown - no compiler sits between the approval and the live post to
    drift from it.
    """
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    body = env["store"].calls[0]["body"]
    assert body["content"] == GOOD_BODY
    assert body["slug"] == job["articleSlug"]
    assert body["category"] == "Conversations"
    assert body["status"] == "published"


# Section 27 "no image/gallery/video node reaches the post": the native store persists the
# approved markdown directly with no rich-content compile, so there is no node tree to inspect
# here. The media/legacy-markup guarantee against the LIVE post is asserted in
# test_blog_verify.py (NO_MEDIA_NODES / NO_LEGACY_MARKUP).


def test_publishing_updates_the_pipeline_and_writes_the_record(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    pipeline = env["bs"].get_source(source_id)["pipeline"]
    assert pipeline["publishStatus"] == env["bp"].PUBLISHED
    assert pipeline["postId"] == POST_ID
    assert pipeline["publishedAt"]
    key = env["bp"].record_key(source_id)
    assert key in env["s3"].objects
    record = json.loads(env["s3"].objects[key].decode())
    assert record["postId"] == POST_ID
    assert record["signoffId"] == job["signoffId"]
    assert record["templateVersion"] == job["templateVersion"]
    assert record["originalSourceDate"] == "1987"


def test_publishing_twice_is_a_no_op_not_a_second_post(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    env["store"].calls.clear()
    again = env["bp"].publish(job["jobId"], "operator")
    assert again["published"] is False
    assert "already published" in again["note"]
    assert env["store"].calls == []


def test_two_concurrent_publishers_cannot_both_write(env):
    """The conditional QUEUED -> PUBLISHING claim. Two operators pressing Publish at the same
    moment would otherwise both reach the native write."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    assert env["bp"]._claim(job["jobId"]) is True
    assert env["bp"]._claim(job["jobId"]) is False
    env["store"].calls.clear()
    #: The job is now PUBLISHING, so a publish attempt refuses rather than writing.
    with pytest.raises(ValueError, match="only a QUEUED job"):
        env["bp"].publish(job["jobId"], "operator")
    assert env["store"].calls == []


def test_an_edit_after_release_blocks_the_publish(env):
    """Release time and publish time are different moments, and the queue is the gap."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    draft = dict(env["bs"].get_source(source_id)["draftRecord"])
    draft["contentMarkdown"] += "\n\nOne more paragraph arrives after the release."
    env["table"].items[source_id]["draftRecord"] = env["storage"]._clean(draft)
    env["store"].calls.clear()
    with pytest.raises(ValueError, match="no longer be published|changed after it was released"):
        env["bp"].publish(job["jobId"], "operator")
    assert env["store"].calls == []
    assert env["bp"].get(job["jobId"])["status"] == env["bp"].QUEUED


def test_a_revocation_after_release_blocks_the_publish(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    signoff = env["bq"].current_signoff(source_id)
    env["bq"].revoke(signoff["id"], "withdrawn before it went live", "editor")
    env["store"].calls.clear()
    with pytest.raises(ValueError, match="no longer be published"):
        env["bp"].publish(job["jobId"], "operator")
    assert env["store"].calls == []


def test_an_unknown_job_is_refused(env):
    with pytest.raises(LookupError, match="Unknown jobId"):
        env["bp"].publish("blogpub_nope", "operator")


# ── A write that does not succeed is FAILED ─────────────────────────────────────
#
# Native publishing has no credential to revoke and no kill switch, so a publish is never
# REFUSED: a write either PUBLISHED or FAILED, and a FAILED write is not retried.


def test_a_store_rejection_records_failed(env):
    """A native-store write that raises is recorded as FAILED (never as a refusal), carries the
    error, and is not retried."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["store"].raise_on_write = True
    env["store"].error = "slug already exists"
    result = env["bp"].publish(job["jobId"], "operator")
    assert result["published"] is False
    assert result.get("refused") is None
    stored = env["bp"].get(job["jobId"])
    assert stored["status"] == env["bp"].FAILED
    assert "slug already exists" in stored["error"]


def test_a_transport_failure_records_failed_and_does_not_retry(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["store"].raise_on_write = True
    env["store"].error = "store 503"
    result = env["bp"].publish(job["jobId"], "operator")
    assert result["published"] is False
    assert env["bp"].get(job["jobId"])["status"] == env["bp"].FAILED
    #: The claim incremented the counter before the write, so a single failed attempt reads as 1.
    assert env["bp"].get(job["jobId"])["attempts"] == 1


def test_a_failed_publish_is_not_retried_automatically(env):
    """A FAILED job is no longer QUEUED, so nothing re-attempts it on its own - the operator has
    to fix the cause and release again. (The native equivalent of the old "a refusal is not
    retried automatically" invariant.)"""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["store"].raise_on_write = True
    env["bp"].publish(job["jobId"], "operator")
    env["store"].raise_on_write = False
    env["store"].calls.clear()
    with pytest.raises(ValueError, match="only a QUEUED job"):
        env["bp"].publish(job["jobId"], "operator")
    assert env["store"].calls == []


def test_a_record_write_failure_does_not_report_a_failed_publish(env, monkeypatch):
    """The post is already live. Reporting failure invites a second attempt, which is the one
    wrong answer in this direction."""
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")

    def exploding(**kwargs):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(env["s3"], "put_object", exploding)
    result = env["bp"].publish(job["jobId"], "operator")
    assert result["published"] is True
    assert env["bp"].get(job["jobId"])["status"] == env["bp"].PUBLISHED


# ── Nothing else may publish ────────────────────────────────────────────────────

def test_nothing_in_the_pipeline_can_release(env):
    """Section 38: pipeline work may publish an ALREADY-RELEASED job, but may never release.

    Bulk publish fan-out deliberately lives in blog_queue: an operator creates QUEUED jobs
    first, then the queue scales the existing publish() operation. What remains forbidden is
    any extraction/batch/QA path calling release(), because that would turn processing
    completion into publication intent without the operator decision.
    """
    import ast
    source = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
    for name in ("blog_sources.py", "blog_queue.py", "blog_batches.py", "blog_qa.py",
                 "blog_draft.py", "blog_analysis.py", "blog_repetition.py",
                 "blog_templates.py", "blog_gate.py"):
        tree = ast.parse((source / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            assert not (
                node.func.value.id == "blog_publish" and node.func.attr == "release"
            ), f"{name} calls blog_publish.release; release must remain operator-only"


def test_the_publish_route_is_not_idempotency_claimed(env):
    """It was, and the first live run caught the claim doing harm.

    The claim keys on the request body, which is just `{jobId}`, so the first attempt records it
    whatever the outcome and a later legitimate retry answers 409. The live run hit exactly that:
    a publish correctly refused because the article had been edited, then the operator restored
    the body, re-signed, pressed Publish again, and got "This Admin action was already submitted"
    with no way forward.

    The conditional QUEUED -> PUBLISHING claim is the real guard and is strictly better, because
    it is tied to the job's STATE rather than to a request shape.
    """
    import ast
    text = (ROOT / "amplify" / "functions" / "operations" / "seo-tools"
            / "handler.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_claim":
            continue
        literals = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
        assert "seo.blogpublish.publish" not in literals, (
            "the publish route is idempotency-claimed again; that blocks a legitimate retry "
            "after a refusal, and the conditional state claim already covers double-submit")


# Only the publish path writes a post: demonstrated by the "written exactly once" assertion in
# test_publishing_writes_once_and_records_the_post and by test_the_batch_worker_cannot_publish.


def test_publishing_is_not_a_model_writable_field(env):
    import blog_draft as bd
    for forbidden in ("publishStatus", "postId", "postUrl", "publishedAt"):
        assert forbidden not in bd.WRITABLE_FIELDS, forbidden


def test_the_batch_worker_cannot_publish(env):
    """A whole batch extracted and signed off still publishes nothing on its own."""
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    source_id = _signed(env, batch_id, "ONE")
    env["bs"].run_worker({})
    assert env["bb"].detail(batch_id)["status"] == env["bb"].READY
    assert env["bs"].get_source(source_id)["pipeline"]["publishStatus"] == ""
    assert env["bp"].queue() == []
    assert env["store"].calls == []


# ── The queue surface ───────────────────────────────────────────────────────────

def test_the_queue_lists_newest_first_and_filters_by_status(env):
    first = _signed(env, header="ONE")
    second = _signed(env, header="TWO")
    job_one = env["bp"].release(first, "operator")
    job_two = env["bp"].release(second, "operator")
    env["bp"].publish(job_one["jobId"], "operator")

    assert len(env["bp"].queue()) == 2
    queued = env["bp"].queue(status="QUEUED")
    assert [row["jobId"] for row in queued] == [job_two["jobId"]]
    published = env["bp"].queue(status="published")
    assert [row["jobId"] for row in published] == [job_one["jobId"]]


def test_the_detail_carries_the_publish_record(env):
    source_id = _signed(env)
    job = env["bp"].release(source_id, "operator")
    env["bp"].publish(job["jobId"], "operator")
    detail = env["bp"].detail(job["jobId"])
    assert detail["record"]["postId"] == POST_ID
    for key in detail:
        assert "url" not in key.lower() or key == "postUrl"


def test_the_batch_publish_state_is_derived_from_the_sources(env):
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    first = _signed(env, batch_id, "ONE")
    _signed(env, batch_id, "TWO")
    state = env["bp"].batch_publish_state(batch_id)
    assert state == {"sources": 2, "byStatus": {"UNRELEASED": 2}, "published": 0,
                     "queued": 0, "refused": 0, "failed": 0, "unreleased": 2, "jobs": 0}

    job = env["bp"].release(first, "operator")
    env["bp"].publish(job["jobId"], "operator")
    state = env["bp"].batch_publish_state(batch_id)
    assert state["published"] == 1
    assert state["unreleased"] == 1
    assert state["jobs"] == 1


def test_the_candidate_list_says_why_each_source_cannot_be_released(env):
    """A release page whose only content is the eligible rows leaves an operator with no idea
    why the other forty are missing."""
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    ready = _signed(env, batch_id, "READY")
    payload = sample_pdf("NOTREADY")
    result = env["bs"].register(
        {"batchId": batch_id, "category": "Conversations",
         "sources": [_pdf_entry(payload)]}, "admin", q.CATEGORIES)
    unready = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[unready]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [unready]}, "admin")
    env["bs"].run_worker({})

    candidates = {row["sourceId"]: row for row in env["bp"].releasable_in_batch(batch_id)}
    assert candidates[ready]["releasable"] is True
    assert candidates[unready]["releasable"] is False
    assert candidates[unready]["reason"]

    env["bp"].release(ready, "operator")
    candidates = {row["sourceId"]: row for row in env["bp"].releasable_in_batch(batch_id)}
    assert candidates[ready]["releasable"] is False
    assert "already has a QUEUED job" in candidates[ready]["reason"]
    assert candidates[ready]["jobStatus"] == "QUEUED"


def test_a_publish_job_does_not_count_as_a_source(env):
    batch_id = env["bb"].create({"name": "Wave 1", "defaultCategory": "Conversations"},
                                "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    source_id = _signed(env, batch_id, "ONE")
    env["bp"].release(source_id, "operator")
    assert env["bb"].rollup(batch_id)["sources"] == 1
