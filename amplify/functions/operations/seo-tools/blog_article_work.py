"""First-class article work records for one-source -> many-article production.

A blogSource is evidence: one uploaded PDF/book/article, one extract, one human source review.
A blogArticleWork is publication work: one independent article derived from an approved intent.

The mature QA/publish/verify pipeline historically used the blogSource row as the article row,
which made one source -> one article an accidental data-model constraint. This module removes
that constraint without weakening any gate. Article work records deliberately carry the same
draftRecord/pipeline shape that blog_qa, blog_publish and blog_verify already enforce.

ChatGPT may write editorial fields only. Human-only source review, gate declarations, sign-off,
release and publish state are never accepted from an editorial payload.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

import blog_sources
import storage

RECORD_TYPE = "blogArticleWork"

EDITORIAL_WRITABLE_FIELDS = (
    "title", "contentMarkdown", "seoTitle", "metaDescription", "tags", "articleType",
    "centralDistinction", "distinctPurpose", "slug",
)

INTENT_PIPELINE_STATUSES = {
    "PLANNED", "SAMPLE_PENDING", "SAMPLE_APPROVED", "DRAFTED", "QA_READY",
    "HUMAN_REVIEW", "SIGNED_OFF", "RELEASED", "PUBLISHED", "SITE_BUILD_PENDING",
    "SITE_DEPLOYED", "VERIFIED", "HOLD",
}


def work_id(intent_id: str) -> str:
    value = str(intent_id or "").strip()
    if not value:
        raise ValueError("intentId is required")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]
    return "blogwork_" + digest


def get(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def for_intent(intent_id: str) -> Optional[Dict[str, Any]]:
    return get(work_id(intent_id))


def list_for_source(source_id: str) -> List[Dict[str, Any]]:
    rows = [
        row for row in storage.list_slug_records(str(source_id))
        if row.get("recordType") == RECORD_TYPE
    ]
    rows.sort(key=lambda row: (int(row.get("ordinal") or 0), str(row.get("createdAt") or "")))
    return [storage._json_safe(row) for row in rows]


def _parent_source(source_id: str) -> Dict[str, Any]:
    parent = storage.get_typed(str(source_id), blog_sources.RECORD_TYPE)
    if not parent:
        raise LookupError("Unknown parent sourceId")
    return parent


def _review_state(parent: Dict[str, Any]) -> str:
    pipeline = parent.get("pipeline") or {}
    answer = str(pipeline.get("sourceReviewedFully") or
                 (parent.get("draftRecord") or {}).get("sourceReviewedFully") or "").upper()
    return answer if answer in {"YES", "NO"} else ""


def _source_provenance(parent: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sourceFile": str(parent.get("sourceRef") or parent.get("s3Key") or ""),
        "originalSourceTitle": str(parent.get("sourceTitle") or ""),
        "originalSourceDate": str(parent.get("sourceDate") or ""),
        "sourceType": str(parent.get("sourceType") or ""),
        "sourceHash": str(parent.get("sourceSha256") or parent.get("contentSha256") or ""),
    }


def _base_draft(parent: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    import blog_quality_v2 as q

    title = str(intent.get("title") or "").strip()
    slug = q.slugify(title)
    draft = {
        "sourceId": work_id(str(intent["id"])),
        "parentSourceId": str(parent["id"]),
        "intentId": str(intent["id"]),
        "articleClass": str(parent.get("articleClass") or "ARCHIVE_DERIVED"),
        "status": "SOURCE_REVIEW",
        **_source_provenance(parent),
        "title": title,
        "slug": slug,
        "category": str(parent.get("category") or q.DEFAULT_CATEGORY),
        "author": q.AUTHOR,
        "authorName": q.AUTHOR,
        "canonical": q.expected_canonical(slug) if slug else "",
        "tags": [],
        "seoTitle": f"{title} | {q.PUBLISHER}" if title else "",
        "metaDescription": "",
        "articleType": str(intent.get("articleType") or "").strip(),
        "imageStatus": "none",
        "contentMarkdown": "",
        "centralDistinction": str(intent.get("centralDistinction") or "").strip(),
        "distinctPurpose": str(intent.get("distinctPurpose") or "").strip(),
        "readerPromise": str(intent.get("readerPromise") or "").strip(),
    }
    review = _review_state(parent)
    if review:
        draft["sourceReviewedFully"] = review
    return draft


def ensure(parent: Dict[str, Any], intent: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Create one deterministic child article record for an accepted intent."""
    iid = str(intent.get("id") or "").strip()
    if not iid:
        raise ValueError("intent id is required")
    wid = work_id(iid)
    existing = get(wid)
    if existing:
        return existing

    now = storage.now_iso()
    draft = _base_draft(parent, intent)
    pipeline = blog_sources.empty_pipeline()
    review = _review_state(parent)
    if review:
        pipeline["sourceReviewedFully"] = review
        parent_pipeline = parent.get("pipeline") or {}
        pipeline["analysisId"] = str(parent_pipeline.get("analysisId") or "")
        pipeline["analysisVersion"] = int(parent_pipeline.get("analysisVersion") or 0)

    record = {
        "id": wid,
        "recordType": RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": str(parent["id"]),
        "parentSourceId": str(parent["id"]),
        "intentId": iid,
        "ordinal": int(intent.get("ordinal") or 0),
        "batchId": parent.get("batchId") or blog_sources.NO_BATCH,
        "category": str(parent.get("category") or ""),
        "articleClass": str(parent.get("articleClass") or "ARCHIVE_DERIVED"),
        "sourceType": str(parent.get("sourceType") or ""),
        "sourceRef": str(parent.get("sourceRef") or ""),
        "s3Key": str(parent.get("s3Key") or ""),
        "extractKey": str(parent.get("extractKey") or ""),
        "sourceTitle": str(parent.get("sourceTitle") or ""),
        "sourceDate": str(parent.get("sourceDate") or ""),
        "sourceSha256": str(parent.get("sourceSha256") or ""),
        "contentSha256": str(parent.get("contentSha256") or ""),
        "status": "ACTIVE",
        "editorialStatus": "PLANNED",
        "articleStatus": "SOURCE_REVIEW",
        "title": str(intent.get("title") or ""),
        "draftRecord": storage._clean(draft),
        "pipeline": storage._clean(pipeline),
        "createdBy": actor,
        "updatedBy": actor,
        "error": "",
    }
    try:
        storage.table().put_item(
            Item=storage._clean(record),
            ConditionExpression="attribute_not_exists(id)",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    return get(wid) or record


def ensure_for_intent(intent_id: str, actor: str) -> Dict[str, Any]:
    intent = storage.get_typed(str(intent_id), "blogArticleIntent")
    if not intent:
        raise LookupError("Unknown article intent")
    parent = _parent_source(str(intent.get("sourceId") or ""))
    return ensure(parent, intent, actor)


def _clean_editorial_payload(article: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist editorial fields exactly like the paid model boundary does."""
    import blog_quality_v2 as q

    cleaned: Dict[str, Any] = {}
    for field in EDITORIAL_WRITABLE_FIELDS:
        if field not in article:
            continue
        value = article[field]
        if field == "tags":
            cleaned["tags"] = [str(x).strip() for x in (value or []) if str(x).strip()][:3]
        elif field == "articleType":
            candidate = str(value or "").strip().upper().replace(" ", "_")
            if candidate in q.ARTICLE_TYPES:
                cleaned["articleType"] = candidate
        elif field == "slug":
            cleaned["slug"] = q.slugify(str(value or ""))
        else:
            cleaned[field] = str(value or "").strip()
    return cleaned


def apply_article(work_ref: str, article: Dict[str, Any], actor: str,
                  editorial_status: str = "DRAFTED") -> Dict[str, Any]:
    """Write ChatGPT editorial work onto the child, never a human gate."""
    import blog_gate
    import blog_quality_v2 as q

    record = get(work_ref)
    if not record:
        raise LookupError("Unknown article work id")
    if not isinstance(article, dict) or not str(article.get("contentMarkdown") or "").strip():
        raise ValueError("article with contentMarkdown is required")

    candidate = dict(record.get("draftRecord") or {})
    candidate.update(_clean_editorial_payload(article))
    # Editing a previously published/verified article creates a NEW editorial candidate.
    # The quality engine deliberately never rewinds PUBLISHED/VERIFIED on validation, so
    # carrying that old draft status forward would make a revised body look pre-verified.
    if str(candidate.get("status") or "").upper() in {"PUBLISHED", "VERIFIED"}:
        candidate["status"] = "EDITORIAL_QA"
    candidate["category"] = str(record.get("category") or q.DEFAULT_CATEGORY)
    candidate["author"] = q.AUTHOR
    candidate["authorName"] = q.AUTHOR
    candidate["parentSourceId"] = str(record.get("parentSourceId") or "")
    candidate["intentId"] = str(record.get("intentId") or "")
    if candidate.get("slug"):
        candidate["canonical"] = q.expected_canonical(candidate["slug"])

    parent = _parent_source(str(record.get("parentSourceId") or ""))
    review = _review_state(parent)
    if review:
        candidate["sourceReviewedFully"] = review
    else:
        candidate.pop("sourceReviewedFully", None)

    candidate.pop("gate", None)
    assessment = blog_gate.assess_draft(record, candidate)
    blog_gate.persist_assessment(work_ref, candidate, assessment)

    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": work_ref},
        UpdateExpression=(
            "SET editorialStatus = :es, title = :t, updatedAt = :u, updatedBy = :a"
        ),
        ExpressionAttributeValues={
            ":es": str(editorial_status or "DRAFTED").upper(),
            ":t": str(candidate.get("title") or ""),
            ":u": now,
            ":a": actor,
        },
    )
    refreshed = get(work_ref) or record
    return {
        "workId": work_ref,
        "intentId": str(refreshed.get("intentId") or ""),
        "parentSourceId": str(refreshed.get("parentSourceId") or ""),
        "editorialStatus": str(refreshed.get("editorialStatus") or ""),
        "articleStatus": str(refreshed.get("articleStatus") or assessment["status"]),
        "bodySha256": assessment["bodySha256"],
        "blocking": assessment["blocking"],
        "review": assessment["review"],
    }


def set_intent_status(work_ref: str, status: str, actor: str) -> None:
    """Keep the editorial intent ledger aligned with the protected downstream pipeline."""
    wanted = str(status or "").upper()
    if wanted not in INTENT_PIPELINE_STATUSES:
        raise ValueError(f"unsupported intent pipeline status {wanted!r}")
    record = get(work_ref)
    if not record:
        return
    intent_id = str(record.get("intentId") or "")
    if not intent_id:
        return
    intent = storage.get_typed(intent_id, "blogArticleIntent")
    if not intent:
        return
    storage.table().update_item(
        Key={"id": intent_id},
        UpdateExpression="SET #s = :s, updatedAt = :u, updatedBy = :a",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": wanted, ":u": storage.now_iso(), ":a": actor},
    )
    storage.table().update_item(
        Key={"id": work_ref},
        UpdateExpression="SET editorialStatus = :s, updatedAt = :u, updatedBy = :a",
        ExpressionAttributeValues={":s": wanted, ":u": storage.now_iso(), ":a": actor},
    )


def sync_parent_review(source_id: str, answer: str, analysis_id: str,
                       analysis_version: int, actor: str) -> int:
    """Propagate a human parent-source review to every child article."""
    import blog_gate

    normalized = str(answer or "").strip().upper()
    if normalized not in {"YES", "NO"}:
        return 0
    changed = 0
    for record in list_for_source(source_id):
        draft = dict(record.get("draftRecord") or {})
        draft["sourceReviewedFully"] = normalized
        blog_sources.update_pipeline(
            str(record["id"]),
            sourceReviewedFully=normalized,
            analysisId=str(analysis_id or ""),
            analysisVersion=int(analysis_version or 0),
        )
        assessment = blog_gate.assess_draft(record, draft)
        blog_gate.persist_assessment(str(record["id"]), draft, assessment)
        storage.table().update_item(
            Key={"id": str(record["id"])},
            UpdateExpression=(
                "SET parentReviewAnalysisId = :i, parentReviewPropagatedAt = :u, "
                "parentReviewPropagatedBy = :a"
            ),
            ExpressionAttributeValues={
                ":i": str(analysis_id or ""), ":u": storage.now_iso(), ":a": actor,
            },
        )
        changed += 1
    return changed


def progress(source_id: str) -> Dict[str, Any]:
    """Three truthful completion layers for one parent source."""
    rows = list_for_source(source_id)
    total = len(rows)
    held = 0
    drafted = 0
    signed = 0
    published = 0
    verified = 0
    by_status: Dict[str, int] = {}

    for row in rows:
        editorial = str(row.get("editorialStatus") or "PLANNED").upper()
        pipeline = row.get("pipeline") or {}
        draft = row.get("draftRecord") or {}
        status = editorial
        if editorial == "HOLD":
            held += 1
            status = "HOLD"
        else:
            if str(draft.get("contentMarkdown") or "").strip():
                drafted += 1
            if str(pipeline.get("signoffId") or ""):
                signed += 1
                status = "SIGNED_OFF"
            if str(pipeline.get("publishStatus") or "") == "PUBLISHED":
                published += 1
                status = "PUBLISHED"
            if str(pipeline.get("verifyStatus") or "") == "VERIFIED":
                verified += 1
                status = "VERIFIED"
        by_status[status] = by_status.get(status, 0) + 1

    active = max(0, total - held)
    return {
        "sourceId": source_id,
        "articles": total,
        "held": held,
        "drafted": drafted,
        "signedOff": signed,
        "published": published,
        "verified": verified,
        "byStatus": dict(sorted(by_status.items())),
        "articleProductionComplete": total > 0 and drafted + held == total,
        "editorialReviewComplete": total > 0 and signed + held == total,
        "pipelineComplete": total > 0 and verified + held == total,
        "activeArticles": active,
    }


def refresh_parent_status(source_id: str, actor: str) -> Dict[str, Any]:
    state = progress(source_id)
    if state["pipelineComplete"]:
        status = "PIPELINE_COMPLETE"
    elif state["editorialReviewComplete"]:
        status = "EDITORIAL_REVIEW_COMPLETE"
    elif state["articleProductionComplete"]:
        status = "ARTICLE_PRODUCTION_COMPLETE"
    else:
        return state

    storage.table().update_item(
        Key={"id": str(source_id)},
        UpdateExpression="SET editorialStatus = :s, updatedAt = :u, editorialUpdatedBy = :a",
        ExpressionAttributeValues={":s": status, ":u": storage.now_iso(), ":a": actor},
    )
    return {**state, "parentEditorialStatus": status}
