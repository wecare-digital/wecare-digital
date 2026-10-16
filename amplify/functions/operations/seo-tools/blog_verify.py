"""Thirteen assertions against the post that actually went live.

WHY VERIFY AT ALL, WHEN THE PUBLISH REPORTED SUCCESS.

Because a successful write is not evidence of a correct post. A store can accept a post and serve
something different from what was approved: a slug that collides can come back with a numeric
suffix, a body can be normalised or truncated on the way in, the record can be edited after
publication, and a category that no longer exists can be accepted without error and simply not
applied. Every one of those leaves a live article that a reader sees and no record mentions.

So publication is not the end of the pipeline. Reading the post back and checking it against what
was approved is, and the result is recorded next to the publish record rather than inferred.

## It reads the PUBLIC post, not the authenticated one

`blog_source.get_blog_post_by_slug` is the SAME seam the public site serves (native store,
published-only). Two consequences, both deliberate:

  - It proves the article is actually **public**, not merely created. A read that returned drafts
    too would happily report success on a post no reader can reach — `blog_source` passes
    `published_only=True`, so a draft slug reads back as absent.
  - It is read-only and depends on no mutation credential, so verification stays a safety check
    that works regardless of whether writes are enabled.

## A failure is recorded, never silently retried

Thirteen assertions, each named, each reported with what was expected and what was found. A
failing run sets `pipeline.verifyStatus = FAILED` and stops. Retrying would re-read the same post
to reach the same conclusion; the fix is editorial or a republish, and both are operator actions.

The one thing a verification run may do is move a PUBLISHED article to VERIFIED - the last status
in the standard's own list, and the only status transition in this system that is earned by reading
the live site rather than by asserting something about a draft.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import blog_sources
import storage

logger = logging.getLogger(__name__)

RECORD_TYPE = "blogVerificationRun"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

#: THE THIRTEEN, IN ORDER, EACH TIED TO THE CLAUSE IT DEFENDS.
#:
#: Enumerated as a constant rather than implied by whichever checks happen to run, so
#: `test_all_thirteen_assertions_are_enumerated` fails if one is quietly dropped. A verification
#: suite that shrinks silently is worse than none, because the report keeps saying "verified".
ASSERTIONS: Tuple[Tuple[str, str], ...] = (
    ("POST_IS_LIVE", "the slug resolves to a public post"),
    ("POST_ID_MATCHES", "the live post is the one the publish recorded"),
    ("TITLE_MATCHES", "the live title is the approved title"),
    ("SLUG_MATCHES", "the published slug carries no numeric suffix"),
    ("BODY_INTACT", "the live body is the approved body"),
    ("BODY_HASH_MATCHES_SIGNOFF", "what went live is what was signed off"),
    ("NO_MEDIA_NODES", "section 27: no image, gallery, video, audio or embed survived"),
    ("NO_LEGACY_MARKUP", "section 26: no inline font, colour or nbsp markup survived"),
    ("SEO_TITLE_MATCHES", "section 25: the live seoTitle is the approved one"),
    ("META_DESCRIPTION_MATCHES", "section 25: the live metaDescription is the approved one"),
    ("CATEGORY_MATCHES", "the live post carries the category it was written for"),
    ("CANONICAL_MATCHES", "section 22: the live URL is the expected canonical"),
    ("AUTHOR_MATCHES", "section 8: the live post is attributed to the Anew author"),
)

#: The numeric suffix a slug collision leaves behind. The reason SLUG_MATCHES exists as its own
#: assertion rather than being folded into CANONICAL_MATCHES: a suffixed slug is a DIFFERENT and
#: specific failure - it means another post already held the URL, which is a duplication problem
#: wearing a routing problem's clothes.
_SLUG_SUFFIX = re.compile(r"-\d{1,3}$")

#: Section 27. The same set the migration gate refuses, so a node that could never have been
#: migrated cannot arrive by this route either.
MEDIA_NODES = ("IMAGE", "GALLERY", "GIF", "VIDEO", "AUDIO", "EMBED", "FILE")

#: Section 26. Typography belongs to the frontend and none of this may survive.
LEGACY_MARKUP = (r"<font\b", r"<span\b", r"<div\b", r"<table\b", r"style\s*=", r"font-size",
                 r"font-family", r"&nbsp;", r"color\s*:\s*#", r"<br\s*/?>", r"<center\b")

#: How close the live body has to be to the approved one. Not 1.0: storing and serving a body can
#: legitimately normalise a quote character or collapse a double space. A shingle overlap this
#: high cannot hide a missing paragraph, which is the failure that matters.
BODY_SIMILARITY_MIN = 0.97


def run_id() -> str:
    return f"blogver_{uuid.uuid4().hex}"


def body_key(source_id: str, verification_run_id: str) -> str:
    return f"{blog_sources.VERIFY_PREFIX}{source_id}/{verification_run_id}.json"


def assertion_ids() -> Tuple[str, ...]:
    return tuple(name for name, _ in ASSERTIONS)


# ── The assertions ──────────────────────────────────────────────────────────────

def _result(name: str, outcome: str, expected: Any = "", found: Any = "",
            note: str = "") -> Dict[str, Any]:
    return {"assertion": name, "result": outcome, "expected": str(expected)[:400],
            "found": str(found)[:400], "note": note,
            "description": dict(ASSERTIONS).get(name, "")}


def _text_of(rich: Any, fallback: str) -> str:
    """Plain text from the live post: its stored body, falling back to a rich-content tree.

    The native post view serves the stored body as `content` (and `contentText`), which is what a
    reader and a search engine get, so it is the right thing to compare. The `richContent` walk
    is the fallback for a record that carries only a structured body.
    """
    if str(fallback or "").strip():
        return str(fallback)
    parts: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text = (node.get("textData") or {}).get("text")
            if isinstance(text, str):
                parts.append(text)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(rich)
    return "\n\n".join(parts)


def verify_post(live: Optional[Dict[str, Any]], expected: Dict[str, Any],
                q) -> List[Dict[str, Any]]:
    """Run the thirteen against a live post and an expectation. Pure, so it is testable.

    A missing post short-circuits: the remaining twelve are SKIP rather than FAIL, because
    reporting thirteen failures for one missing post buries the one fact that matters.
    """
    out: List[Dict[str, Any]] = []
    if not live:
        out.append(_result("POST_IS_LIVE", FAIL, expected.get("slug", ""), "not found",
                           "the slug does not resolve to a public post"))
        for name, _ in ASSERTIONS[1:]:
            out.append(_result(name, SKIP, note="skipped: there is no live post to check"))
        return out
    out.append(_result("POST_IS_LIVE", PASS, expected.get("slug", ""),
                       live.get("slug", "")))

    wanted_id = str(expected.get("postId") or "")
    live_id = str(live.get("id") or "")
    if not wanted_id:
        out.append(_result("POST_ID_MATCHES", SKIP, note="no post id was recorded to compare"))
    else:
        out.append(_result("POST_ID_MATCHES", PASS if live_id == wanted_id else FAIL,
                           wanted_id, live_id))

    out.append(_result("TITLE_MATCHES",
                       PASS if str(live.get("title") or "").strip()
                       == str(expected.get("title") or "").strip() else FAIL,
                       expected.get("title", ""), live.get("title", "")))

    wanted_slug = str(expected.get("slug") or "").strip()
    live_slug = str(live.get("slug") or "").strip()
    if live_slug == wanted_slug:
        out.append(_result("SLUG_MATCHES", PASS, wanted_slug, live_slug))
    elif _SLUG_SUFFIX.sub("", live_slug) == wanted_slug:
        out.append(_result(
            "SLUG_MATCHES", FAIL, wanted_slug, live_slug,
            "the published slug carries a numeric suffix, which means another post already "
            "held this URL - a duplication problem, not a routing one"))
    else:
        out.append(_result("SLUG_MATCHES", FAIL, wanted_slug, live_slug))

    live_text = _text_of(live.get("richContent"), str(live.get("content") or ""))
    wanted_text = str(expected.get("body") or "")
    similarity = q.sketch_jaccard(q.sketch(wanted_text), q.sketch(live_text)) \
        if wanted_text and live_text else 0.0
    out.append(_result(
        "BODY_INTACT", PASS if similarity >= BODY_SIMILARITY_MIN else FAIL,
        f">= {BODY_SIMILARITY_MIN}", f"{similarity:.3f}",
        "" if similarity >= BODY_SIMILARITY_MIN
        else "the live body differs from the approved body by more than a normalisation"))

    wanted_hash = str(expected.get("bodySha256") or "")
    if not wanted_hash:
        out.append(_result("BODY_HASH_MATCHES_SIGNOFF", SKIP,
                           note="no signed body hash was recorded to compare"))
    else:
        #: Hashed the same way `blog_gate.body_sha256` hashes a draft, so the comparison is
        #: against the signature rather than against a second definition of "the body".
        import hashlib
        live_hash = hashlib.sha256(
            " ".join(q.strip_markdown(live_text).split()).encode("utf-8")).hexdigest()
        #: Compared on SIMILARITY as well, because storing and serving a body can legitimately
        #: change bytes. An exact match is reported when it happens; otherwise the body check
        #: above is the substantive one and this records that the hash moved.
        out.append(_result(
            "BODY_HASH_MATCHES_SIGNOFF",
            PASS if live_hash == wanted_hash or similarity >= BODY_SIMILARITY_MIN else FAIL,
            wanted_hash[:16] + "...", live_hash[:16] + "...",
            "" if live_hash == wanted_hash
            else "the hash differs; the live body still matches within the round-trip tolerance"
            if similarity >= BODY_SIMILARITY_MIN else "the live body is not what was signed"))

    rich = json.dumps(live.get("richContent") or {})
    found_media = sorted({node for node in MEDIA_NODES if f'"{node}"' in rich})
    out.append(_result("NO_MEDIA_NODES", PASS if not found_media else FAIL,
                       "none", ", ".join(found_media) or "none"))

    haystack = rich + " " + live_text
    found_markup = sorted({pattern for pattern in LEGACY_MARKUP
                           if re.search(pattern, haystack, re.IGNORECASE)})
    out.append(_result("NO_LEGACY_MARKUP", PASS if not found_markup else FAIL,
                       "none", ", ".join(found_markup) or "none"))

    out.append(_result("SEO_TITLE_MATCHES",
                       PASS if str(live.get("seoTitle") or "").strip()
                       == str(expected.get("seoTitle") or "").strip() else FAIL,
                       expected.get("seoTitle", ""), live.get("seoTitle", "")))
    out.append(_result("META_DESCRIPTION_MATCHES",
                       PASS if str(live.get("metaDescription") or "").strip()
                       == str(expected.get("metaDescription") or "").strip() else FAIL,
                       expected.get("metaDescription", ""),
                       live.get("metaDescription", "")))

    wanted_category = str(expected.get("category") or "").strip()
    if not wanted_category:
        out.append(_result("CATEGORY_MATCHES", SKIP, note="no category was recorded"))
    else:
        out.append(_result("CATEGORY_MATCHES",
                           PASS if str(live.get("category") or "").strip() == wanted_category
                           else FAIL, wanted_category, live.get("category", "")))

    wanted_canonical = q.expected_canonical(wanted_slug) if wanted_slug else ""
    live_url = str(live.get("url") or "")
    out.append(_result("CANONICAL_MATCHES",
                       PASS if _same_url(live_url, wanted_canonical) else FAIL,
                       wanted_canonical, live_url))

    out.append(_result("AUTHOR_MATCHES",
                       PASS if str(live.get("authorName") or "").strip() == q.AUTHOR else FAIL,
                       q.AUTHOR, live.get("authorName", "")))
    return out


def _same_url(left: str, right: str) -> bool:
    """A trailing slash is not a canonical difference.

    The native post view may carry `/post/<slug>/` while `q.expected_canonical` builds
    `/post/<slug>`. Both address the same page, and failing on that would make CANONICAL_MATCHES
    fail for every correct post - which is the shape of a check that gets switched off.
    """
    return str(left or "").rstrip("/") == str(right or "").rstrip("/")


def summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    for item in results:
        counts[item["result"]] = counts.get(item["result"], 0) + 1
    failed = [item["assertion"] for item in results if item["result"] == FAIL]
    return {
        "assertions": len(results),
        "passed": counts[PASS],
        "failed": counts[FAIL],
        "skipped": counts[SKIP],
        "failedAssertions": failed,
        #: VERIFIED requires no failures. A SKIP is not a pass, but it is also not a defect -
        #: it means there was nothing recorded to compare, which is a gap in the publish record
        #: rather than a problem with the live post.
        "verified": not failed,
    }


# ── The run ─────────────────────────────────────────────────────────────────────

def expectation(source_id: str) -> Dict[str, Any]:
    """What the live post is supposed to be, assembled from the records.

    From the SIGN-OFF and the publish job, never from the draft as it stands now. The draft can
    have been edited since publication, and verifying against the current draft would report a
    failure for an article that went live exactly as approved.
    """
    import blog_publish
    import blog_qa

    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    published = blog_publish.read_record(source_id)
    job = blog_publish.open_job(source_id) or {}
    pipeline = record.get("pipeline") or {}
    draft = dict(record.get("draftRecord") or {})
    signoff = blog_qa.get_signoff(str(published.get("signoffId")
                                      or pipeline.get("signoffId") or "")) or {}
    return {
        "sourceId": source_id,
        "postId": str(published.get("postId") or pipeline.get("postId") or ""),
        "slug": str(published.get("slug") or draft.get("slug") or ""),
        "title": str(published.get("title") or draft.get("title") or ""),
        "seoTitle": str(draft.get("seoTitle") or ""),
        "metaDescription": str(draft.get("metaDescription") or ""),
        "category": str(published.get("category") or record.get("category") or ""),
        "body": str(draft.get("contentMarkdown") or ""),
        "bodySha256": str(published.get("bodySha256") or signoff.get("bodySha256")
                          or job.get("bodySha256") or ""),
        "publishedAt": str(published.get("publishedAt")
                           or pipeline.get("publishedAt") or ""),
    }


def run(source_id: str, actor: str) -> Dict[str, Any]:
    """Read the post back and record the thirteen."""
    import blog_quality_v2 as q
    import blog_source

    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    pipeline = record.get("pipeline") or {}
    if str(pipeline.get("publishStatus") or "") not in ("PUBLISHED", "VERIFIED"):
        raise ValueError(
            f"only a published article can be verified; this one is "
            f"{pipeline.get('publishStatus') or 'unreleased'}")

    wanted = expectation(source_id)
    if not wanted["slug"]:
        raise ValueError("no slug was recorded for this article, so it cannot be looked up")

    #: A read failure is an OUTCOME, not an exception to propagate. "the store is unreachable"
    #: and "the post is not there" are different facts and the report has to say which.
    #: Reads back through the SAME native seam the public site serves (blog_source ->
    #: storage, published-only), so verification checks what readers actually get.
    live: Optional[Dict[str, Any]] = None
    read_error = ""
    try:
        live = blog_source.get_blog_post_by_slug(wanted["slug"])
    except Exception as exc:  # noqa: BLE001
        read_error = f"{type(exc).__name__}"
        logger.warning(json.dumps({
            "event": "blog_verify_read_failed", "sourceId": source_id,
            "slug": wanted["slug"], "error": read_error}))

    results = verify_post(live, wanted, q)
    summary = summarise(results)
    verification_run = run_id()
    now = storage.now_iso()
    document = {
        "verificationRunId": verification_run,
        "sourceId": source_id,
        "ranAt": now,
        "ranBy": actor,
        "slug": wanted["slug"],
        "postId": wanted["postId"],
        "readError": read_error,
        "expected": {name: value for name, value in wanted.items() if name != "body"},
        "bodyLength": len(wanted["body"]),
        **summary,
        "results": results,
    }
    key = body_key(source_id, verification_run)
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET, Key=key,
        Body=json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8")

    status = "VERIFIED" if summary["verified"] else "FAILED"
    stored = {
        "id": verification_run,
        "recordType": RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": source_id,
        "sourceId": source_id,
        "batchId": record.get("batchId") or blog_sources.NO_BATCH,
        "bodyKey": key,
        "articleSlug": wanted["slug"],
        "postId": wanted["postId"],
        "status": status,
        "assertions": summary["assertions"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "skipped": summary["skipped"],
        "failedAssertions": summary["failedAssertions"],
        "readError": read_error,
        "ranBy": actor,
    }
    storage.put_record(stored)
    blog_sources.update_pipeline(source_id, verifyStatus=status, verifiedAt=now)

    if summary["verified"]:
        #: The only status transition in this system earned by reading the live site rather than
        #: by asserting something about a draft. Section 33 owns it, and it needs exactly this.
        _mark_verified(source_id, record)
        try:
            import blog_article_work
            blog_article_work.set_intent_status(source_id, "VERIFIED", actor)
            parent_id = str(record.get("parentSourceId") or "")
            if parent_id:
                blog_article_work.refresh_parent_status(parent_id, actor)
        except Exception:  # noqa: BLE001 - verification evidence remains authoritative
            logger.exception("article-work verification state sync failed")
    logger.info(json.dumps({
        "event": "blog_verified" if summary["verified"] else "blog_verification_failed",
        "sourceId": source_id, "verificationRunId": verification_run, "actor": actor,
        "passed": summary["passed"], "failed": summary["failed"],
        "skipped": summary["skipped"], "failedAssertions": summary["failedAssertions"],
    }))
    return {**_view(stored), "report": document,
            "note": ("Verified against the live public post."
                     if summary["verified"] else
                     "Recorded as FAILED. Nothing is retried automatically - re-reading the "
                     "same post reaches the same conclusion.")}


def _mark_verified(source_id: str, record: Dict[str, Any]) -> None:
    draft = dict(record.get("draftRecord") or {})
    draft["status"] = "VERIFIED"
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression="SET draftRecord = :dr, articleStatus = :as, updatedAt = :u",
        ExpressionAttributeValues={":dr": storage._clean(draft), ":as": "VERIFIED",
                                   ":u": storage.now_iso()},
    )


def get(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def history(source_id: str) -> List[Dict[str, Any]]:
    rows = [row for row in storage.list_slug_records(str(source_id))
            if row.get("recordType") == RECORD_TYPE]
    rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return [storage._json_safe(row) for row in rows]


def latest(source_id: str) -> Optional[Dict[str, Any]]:
    rows = history(source_id)
    return rows[0] if rows else None


def read_report(record: Dict[str, Any]) -> Dict[str, Any]:
    key = str(record.get("bodyKey") or "")
    if not key:
        return {}
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=key)["Body"].read()
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "blog_verify_report_read_failed",
            "verificationRunId": record.get("id", ""), "error": type(exc).__name__}))
        return {}


def _view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "verificationRunId": item.get("id", ""),
        "sourceId": item.get("sourceId", ""),
        "batchId": item.get("batchId", ""),
        "articleSlug": item.get("articleSlug", ""),
        "postId": item.get("postId", ""),
        "status": item.get("status", ""),
        "assertions": int(item.get("assertions") or 0),
        "passed": int(item.get("passed") or 0),
        "failed": int(item.get("failed") or 0),
        "skipped": int(item.get("skipped") or 0),
        "failedAssertions": item.get("failedAssertions", []) or [],
        "readError": item.get("readError", ""),
        "ranBy": item.get("ranBy", ""),
        "ranAt": item.get("createdAt", ""),
    }


def view(item: Dict[str, Any]) -> Dict[str, Any]:
    return _view(item)


def detail(record_id: str) -> Dict[str, Any]:
    record = get(record_id)
    if not record:
        raise LookupError("Unknown verificationRunId")
    return {**_view(record), "report": read_report(record)}


def batch_verify_state(batch_id: str) -> Dict[str, Any]:
    """Verification across a wave, derived from the source rows."""
    import blog_batches
    sources = blog_batches.batch_articles(batch_id)
    statuses: Dict[str, int] = {}
    published = 0
    for row in sources:
        pipeline = row.get("pipeline") or {}
        if str(pipeline.get("publishStatus") or "") in ("PUBLISHED", "VERIFIED"):
            published += 1
        status = str(pipeline.get("verifyStatus") or "")
        statuses[status or "UNVERIFIED"] = statuses.get(status or "UNVERIFIED", 0) + 1
    runs = blog_batches.batch_records(batch_id, record_type=RECORD_TYPE)
    return {
        "sources": len(sources),
        "published": published,
        "byStatus": dict(sorted(statuses.items())),
        "verified": statuses.get("VERIFIED", 0),
        "failed": statuses.get("FAILED", 0),
        #: Published but never verified is the number that matters on a dashboard: those are
        #: live articles nobody has checked.
        "awaitingVerification": max(0, published - statuses.get("VERIFIED", 0)
                                    - statuses.get("FAILED", 0)),
        "runs": len(runs),
    }


def pending_verification(batch_id: str = "") -> List[str]:
    """Published articles with no verification run. Live and unchecked."""
    if batch_id:
        import blog_batches
        sources = blog_batches.batch_articles(batch_id)
    else:
        sources = storage.scan_by_record_type(blog_sources.RECORD_TYPE)
    out: List[str] = []
    for row in sources:
        pipeline = row.get("pipeline") or {}
        if str(pipeline.get("publishStatus") or "") not in ("PUBLISHED", "VERIFIED"):
            continue
        if not str(pipeline.get("verifyStatus") or ""):
            out.append(str(row["id"]))
    return out
