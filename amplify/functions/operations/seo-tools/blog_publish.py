"""The publish queue. An operator releases; nothing here decides to publish on its own.

THE ONE FAILURE THIS DOMAIN MUST NEVER HAVE.

Publishing the same article twice cannot be undone after the fact. A duplicate post gets indexed,
linked and cited, and deleting it afterwards leaves a dead URL where a real one was. Every
structural decision in this module is about that:

  - A release RESOLVES BEFORE IT GENERATES. A second release of the same source returns the job
    that already exists rather than creating another one.
  - The transition to PUBLISHING is a CONDITIONAL WRITE on `status = QUEUED`, so two concurrent
    publishers cannot both proceed. Same mechanism as the extraction claim.
  - Releasability is re-checked AT PUBLISH TIME, not trusted from release time. An article can be
    edited, or its sign-off revoked, between the two - and the queue is exactly where that gap
    lives.

## Releasing is not publishing, and that separation is the point

`release` records an intent and enqueues nothing. `publish` performs the native write. Spec
section 38: processing completion must never automatically mean publishing. There is no path from
extraction, the SQS consumer, a QA run or a batch reaching READY to either function - a test
asserts it by grepping, because that is the kind of convenience somebody adds later.

## The write goes to the AWS-native store, and a failure is recorded rather than swallowed

WIX EXIT COMPLETE: the publish write goes to the AWS-native blog store through
`storage.create_blog_post`, which persists the PUBLISHED `blogPost` record the native public read
path (`blog_source`/`storage`) serves. There is no Wix credential and no kill switch in native
mode, so a native publish is NEVER REFUSED - a write that does not succeed is always recorded as
FAILED. `wix_blog_migrate` and the Ricos compiler are gone: the native read path renders the
stored markdown directly, so there is no rich-content compile to satisfy.

The duplicate-publish guarantees are source-agnostic and unchanged: the resolve-before-generate
release, the conditional QUEUED -> PUBLISHING claim, the publish-time releasability and body-hash
re-checks, and the "a record-write failure never reports a failed publish" rule all still hold.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import blog_sources
import storage

logger = logging.getLogger(__name__)

RECORD_TYPE = "blogPublishJob"

#: A job's lifecycle. REFUSED is retained as a historical status constant (older jobs may still
#: carry it, and `batch_publish_state` still rolls it up) but native publishing never produces it:
#: there is no Wix credential to switch off, so a write either PUBLISHED or FAILED.
QUEUED = "QUEUED"
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
REFUSED = "REFUSED"
FAILED = "FAILED"
JOB_STATUSES = (QUEUED, PUBLISHING, PUBLISHED, REFUSED, FAILED)

#: Statuses that mean "this source already has a live or in-flight job", so a second release
#: resolves to it instead of creating another.
OPEN_STATUSES = (QUEUED, PUBLISHING, PUBLISHED)


def job_id() -> str:
    return f"blogpub_{uuid.uuid4().hex}"


def record_key(source_id: str) -> str:
    """One publish record per SOURCE, not per job.

    Deliberately overwritten by a later attempt rather than accumulating: the question this file
    answers is "what was published for this source", and there is only ever one answer. The
    attempt history lives in DynamoDB, where it is queryable.
    """
    return f"{blog_sources.PUBLISH_PREFIX}{source_id}.json"


# ── Release ─────────────────────────────────────────────────────────────────────

def get(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def jobs_for(source_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in storage.list_slug_records(str(source_id))
            if row.get("recordType") == RECORD_TYPE]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return [storage._json_safe(row) for row in rows]


def open_job(source_id: str) -> Optional[Dict[str, Any]]:
    for row in jobs_for(source_id):
        if str(row.get("status")) in OPEN_STATUSES:
            return row
    return None


def release(source_id: str, actor: str) -> Dict[str, Any]:
    """Record an operator's decision to publish. Performs no publish write.

    Refuses without a sign-off that still covers the current body - `blog_qa.releasable` owns
    that question so it cannot be answered two ways.
    """
    import blog_qa

    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")

    existing = open_job(source_id)
    if existing:
        #: RESOLVE BEFORE GENERATE. A double-clicked button, a retried request, or an operator
        #: releasing a batch twice must not produce two jobs - and a second job is how the same
        #: article gets posted twice.
        logger.info(json.dumps({
            "event": "blog_publish_release_resolved", "sourceId": source_id,
            "jobId": existing["id"], "status": existing["status"], "actor": actor}))
        return {**_view(existing), "created": False,
                "note": f"this source already has a {existing['status']} job"}

    ok, reason = blog_qa.releasable(source_id)
    if not ok:
        raise ValueError(f"this article cannot be released: {reason}")

    signoff = blog_qa.current_signoff(source_id) or {}
    draft = dict(record.get("draftRecord") or {})
    pipeline = record.get("pipeline") or {}
    now = storage.now_iso()
    stored = {
        "id": job_id(),
        "recordType": RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": source_id,
        "sourceId": source_id,
        "batchId": record.get("batchId") or blog_sources.NO_BATCH,
        "status": QUEUED,
        "articleSlug": str(draft.get("slug") or ""),
        "articleTitle": str(draft.get("title") or ""),
        "category": str(record.get("category") or ""),
        #: The hash the release covers. `publish` compares it again, because an article edited
        #: between release and publish would otherwise go live under a signature for other text.
        "bodySha256": str(signoff.get("bodySha256") or ""),
        "signoffId": str(signoff.get("id") or ""),
        "qaRunId": str(signoff.get("qaRunId") or ""),
        "templateId": str(pipeline.get("templateId") or ""),
        "templateVersion": int(pipeline.get("templateVersion") or 0),
        "releasedBy": actor,
        "releasedAt": now,
        "attempts": 0,
        "postId": "",
        "postUrl": "",
        "publishedAt": "",
        "error": "",
    }
    storage.put_record(stored)
    blog_sources.update_pipeline(source_id, publishStatus=QUEUED)
    logger.info(json.dumps({
        "event": "blog_publish_released", "sourceId": source_id, "jobId": stored["id"],
        "actor": actor, "slug": stored["articleSlug"]}))
    return {**_view(stored), "created": True,
            "note": ("Queued. This records the decision and performs no publish write; "
                     "publishing is a separate call.")}


def unrelease(job_ref: str, reason: str, actor: str) -> Dict[str, Any]:
    """Take a QUEUED job back out of the queue.

    Only from QUEUED. A PUBLISHING job is mid-flight and a PUBLISHED one is live, and pretending
    either can be withdrawn here would be a lie - a live post comes down through the native blog
    store, which is outside this module's authority.
    """
    job = get(job_ref)
    if not job:
        raise LookupError("Unknown jobId")
    if str(job.get("status")) != QUEUED:
        raise ValueError(
            f"only a QUEUED job can be withdrawn; this one is {job.get('status')}")
    if len(str(reason or "").strip()) < 10:
        raise ValueError("a withdrawal must carry a reason")
    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": job_ref},
        UpdateExpression=("SET #s = :s, #e = :e, updatedAt = :u, withdrawnBy = :by"),
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": FAILED, ":e": f"withdrawn: {str(reason)[:400]}",
                                   ":u": now, ":by": actor},
    )
    blog_sources.update_pipeline(str(job["sourceId"]), publishStatus="")
    logger.info(json.dumps({
        "event": "blog_publish_withdrawn", "jobId": job_ref, "actor": actor}))
    return {**_view({**job, "status": FAILED}), "withdrawn": True}


# ── Publish ─────────────────────────────────────────────────────────────────────

def _claim(job_ref: str) -> bool:
    """QUEUED -> PUBLISHING, atomically.

    The whole reason this is a conditional write: two operators pressing Publish at the same
    moment, or a retried request arriving beside the original, would otherwise both reach the
    native write and post the article twice.
    """
    from botocore.exceptions import ClientError
    try:
        storage.table().update_item(
            Key={"id": str(job_ref)},
            UpdateExpression=("SET #s = :working, updatedAt = :u, "
                              "attempts = if_not_exists(attempts, :zero) + :one"),
            ConditionExpression="#s = :queued",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":working": PUBLISHING, ":queued": QUEUED,
                                       ":u": storage.now_iso(), ":zero": 0, ":one": 1},
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _settle(job_ref: str, status: str, **fields: Any) -> None:
    names = {"#s": "status"}
    values: Dict[str, Any] = {":s": status, ":u": storage.now_iso()}
    assignments = ["#s = :s", "updatedAt = :u"]
    for index, (key, value) in enumerate(fields.items()):
        name, token = f"#f{index}", f":f{index}"
        names[name], values[token] = key, storage._clean(value)
        assignments.append(f"{name} = {token}")
    storage.table().update_item(
        Key={"id": str(job_ref)}, UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def publish(job_ref: str, actor: str) -> Dict[str, Any]:
    """Perform the native publish write for a QUEUED job.

    RE-CHECKS RELEASABILITY, because release time and publish time are different moments and the
    queue is exactly where the gap lives: the body can be edited or the sign-off revoked in
    between, and the job would otherwise publish text nobody approved.
    """
    import blog_gate
    import blog_qa

    job = get(job_ref)
    if not job:
        raise LookupError("Unknown jobId")
    if str(job.get("status")) == PUBLISHED:
        return {**_view(job), "published": False,
                "note": "already published; this is a no-op rather than a second post"}
    if str(job.get("status")) not in (QUEUED,):
        raise ValueError(
            f"only a QUEUED job can be published; this one is {job.get('status')}")

    source_id = str(job["sourceId"])
    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("the article this job belongs to no longer exists")
    draft = dict(record.get("draftRecord") or {})

    ok, reason = blog_qa.releasable(source_id)
    if not ok:
        raise ValueError(f"this job can no longer be published: {reason}")
    live_hash = blog_gate.body_sha256(draft)
    if str(job.get("bodySha256") or "") != live_hash:
        raise ValueError(
            "the article changed after it was released, so the release does not cover what "
            "would go live; re-run QA, re-sign, and release again")

    #: The publish WRITE goes to the AWS-native store (SeoToolsTable `blogPost` records), which
    #: the native public read path (`blog_source.py`) serves. There is no Wix credential and no
    #: kill switch in native mode, so a native publish is NEVER REFUSED - a write either PUBLISHED
    #: or, on an exception, FAILED. `_blog_source_is_aws()` is unconditionally True; it is kept so
    #: `publish` reads as a source-agnostic branch.
    native_blog = _blog_source_is_aws()

    if not _claim(job_ref):
        return {**_view(get(job_ref) or job), "published": False,
                "note": "another publisher holds this job"}

    try:
        result = _write_native(record, draft, actor)
    except Exception as exc:  # noqa: BLE001
        #: A native publish has no Wix credential and no kill switch, so a write that raises is
        #: always a real failure - recorded as FAILED, never reclassified as a refusal.
        logger.exception("blog publish failed")
        #: `wecare-blog-publish-failures` counts this line. A FAILED publish is the native store
        #: rejecting a post, which is a defect to look at.
        logger.warning(json.dumps({
            "event": "blog_publish_failed", "jobId": job_ref, "sourceId": source_id,
            "error": type(exc).__name__}))
        _settle(job_ref, FAILED, error=f"{type(exc).__name__}: {str(exc)[:800]}")
        blog_sources.update_pipeline(source_id, publishStatus=FAILED)
        return {**_view(get(job_ref) or job), "published": False,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                "note": "Recorded as FAILED. Nothing is retried automatically."}

    now = storage.now_iso()
    _settle(job_ref, PUBLISHED, postId=result["postId"], postUrl=result["postUrl"],
            publishedAt=now, error="")
    blog_sources.update_pipeline(
        source_id, publishStatus=PUBLISHED, publishedAt=now,
        postId=result["postId"], postUrl=result["postUrl"])
    _write_record(source_id, {**job, "status": PUBLISHED, "publishedAt": now, **result},
                  draft, actor)
    logger.info(json.dumps({
        "event": "blog_published", "jobId": job_ref, "sourceId": source_id,
        "actor": actor, "postId": result["postId"], "slug": job.get("articleSlug", "")}))
    return {**_view(get(job_ref) or job), "published": True, **result,
            "note": "Published. Run verification to confirm what actually went live."}


def _blog_source_is_aws() -> bool:
    """Whether the blog WRITE goes to the AWS-native store. Shares the one BLOG_SOURCE
    flag with the public READ path (blog_source.py).

    WIX EXIT COMPLETE: the blog WRITE always goes to the AWS-native store now. The Wix
    publish path and its credential/kill-switch handling were removed with the Wix
    Lambdas, so this is unconditionally True and kept only so `publish()` reads as a
    source-agnostic branch."""
    return True


def _write_native(record: Dict[str, Any], draft: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Publish to the AWS-native blog store, returning a `{postId, postUrl}` shape so
    `publish` stays source-agnostic.

    Maps the approved draft to `storage.create_blog_post`'s body and writes it as a
    PUBLISHED `blogPost` record — the exact record type `blog_source`/`storage` serve to
    the public blog. Markdown is stored as-is (the native read path renders it); no Ricos
    compile is needed because there is no Wix to satisfy.
    """
    body = {
        "title": str(draft.get("title") or "").strip(),
        "slug": str(draft.get("slug") or "").strip(),
        "content": draft.get("contentMarkdown") or "",
        "status": "published",
        "category": str(record.get("category") or draft.get("category") or "").strip(),
        "tags": draft.get("tagLabels") or draft.get("tags") or [],
        "hashtags": draft.get("hashtags") or [],
        "excerpt": str(draft.get("excerpt") or "").strip(),
        "coverImage": str(draft.get("coverImage") or "").strip(),
        "authorName": str(draft.get("authorName") or "").strip(),
        "seoTitle": str(draft.get("seoTitle") or "").strip(),
        "metaDescription": str(draft.get("metaDescription") or "").strip(),
        "focusKeyword": str(draft.get("focusKeyword") or "").strip(),
        "secondaryKeywords": draft.get("secondaryKeywords") or [],
        "jsonLd": draft.get("jsonLd") or {},
    }
    result = storage.create_blog_post(body, actor)
    return {"postId": result["postId"], "postUrl": result["url"]}


def _write_record(source_id: str, job: Dict[str, Any], draft: Dict[str, Any],
                  actor: str) -> None:
    """The durable publish record: what went live, from what, approved by whom."""
    document = {
        "sourceId": source_id,
        "jobId": str(job.get("id") or ""),
        "postId": str(job.get("postId") or ""),
        "postUrl": str(job.get("postUrl") or ""),
        "publishedAt": str(job.get("publishedAt") or ""),
        "publishedBy": actor,
        "releasedBy": str(job.get("releasedBy") or ""),
        "signoffId": str(job.get("signoffId") or ""),
        "qaRunId": str(job.get("qaRunId") or ""),
        "templateId": str(job.get("templateId") or ""),
        "templateVersion": int(job.get("templateVersion") or 0),
        "bodySha256": str(job.get("bodySha256") or ""),
        "slug": str(draft.get("slug") or ""),
        "title": str(draft.get("title") or ""),
        "category": str(job.get("category") or ""),
        "articleClass": str(draft.get("articleClass") or ""),
        "originalSourceTitle": str(draft.get("originalSourceTitle") or ""),
        "originalSourceDate": str(draft.get("originalSourceDate") or ""),
        "sourceHash": str(draft.get("sourceHash") or ""),
    }
    try:
        blog_sources.s3_client().put_object(
            Bucket=blog_sources.BUCKET, Key=record_key(source_id),
            Body=json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8")
    except Exception as exc:  # noqa: BLE001
        #: Logged, not raised. The post is already live and the DynamoDB job already records it;
        #: failing here would report a publish failure for a publish that succeeded, which is
        #: the one wrong answer in this direction - it invites a second attempt.
        logger.warning(json.dumps({
            "event": "blog_publish_record_write_failed", "sourceId": source_id,
            "error": type(exc).__name__}))


def read_record(source_id: str) -> Dict[str, Any]:
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=record_key(source_id))["Body"].read()
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ── Views and rollups ───────────────────────────────────────────────────────────

def _view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jobId": item.get("id", ""),
        "sourceId": item.get("sourceId", ""),
        "batchId": item.get("batchId", ""),
        "status": item.get("status", ""),
        "articleSlug": item.get("articleSlug", ""),
        "articleTitle": item.get("articleTitle", ""),
        "category": item.get("category", ""),
        "bodySha256": item.get("bodySha256", ""),
        "signoffId": item.get("signoffId", ""),
        "qaRunId": item.get("qaRunId", ""),
        "templateId": item.get("templateId", ""),
        "templateVersion": int(item.get("templateVersion") or 0),
        "releasedBy": item.get("releasedBy", ""),
        "releasedAt": item.get("releasedAt", ""),
        "attempts": int(item.get("attempts") or 0),
        "postId": item.get("postId", ""),
        "postUrl": item.get("postUrl", ""),
        "publishedAt": item.get("publishedAt", ""),
        "error": item.get("error", ""),
        "createdAt": item.get("createdAt", ""),
        "updatedAt": item.get("updatedAt", ""),
    }


def view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _view(item)


def queue(status: str = "", limit: int = 0) -> List[Dict[str, Any]]:
    """The publish queue, newest first, optionally one status."""
    rows = storage.scan_by_record_type(RECORD_TYPE, limit=0)
    if status:
        wanted = str(status).strip().upper()
        rows = [row for row in rows if str(row.get("status")) == wanted]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    if limit:
        rows = rows[:limit]
    return [_view(row) for row in rows]


def detail(job_ref: str) -> Dict[str, Any]:
    job = get(job_ref)
    if not job:
        raise LookupError("Unknown jobId")
    return {**_view(job), "record": read_record(str(job.get("sourceId") or ""))}


def batch_publish_state(batch_id: str) -> Dict[str, Any]:
    """Publication across a wave, derived from the source rows."""
    import blog_batches
    sources = blog_batches.batch_sources(batch_id)
    statuses: Dict[str, int] = {}
    for row in sources:
        status = str((row.get("pipeline") or {}).get("publishStatus") or "")
        statuses[status or "UNRELEASED"] = statuses.get(status or "UNRELEASED", 0) + 1
    jobs = blog_batches.batch_records(batch_id, record_type=RECORD_TYPE)
    return {
        "sources": len(sources),
        "byStatus": dict(sorted(statuses.items())),
        "published": statuses.get(PUBLISHED, 0),
        "queued": statuses.get(QUEUED, 0),
        "refused": statuses.get(REFUSED, 0),
        "failed": statuses.get(FAILED, 0),
        "unreleased": statuses.get("UNRELEASED", 0),
        "jobs": len(jobs),
    }


def releasable_in_batch(batch_id: str) -> List[Dict[str, Any]]:
    """Which sources in a wave an operator could release right now, and why the rest cannot.

    Returned WITH the reason for every source rather than filtered, because a release page whose
    only content is the eligible rows leaves an operator with no idea why the other forty are
    missing.
    """
    import blog_batches
    import blog_qa
    out: List[Dict[str, Any]] = []
    for row in blog_batches.batch_sources(batch_id):
        source_id = str(row["id"])
        ok, reason = blog_qa.releasable(source_id)
        job = open_job(source_id)
        out.append({
            "sourceId": source_id,
            "title": str(row.get("title") or ""),
            "slug": str(row.get("slug") or ""),
            "releasable": ok and not job,
            "reason": (f"already has a {job['status']} job" if job else reason),
            "jobId": str(job["id"]) if job else "",
            "jobStatus": str(job["status"]) if job else "",
        })
    return out
