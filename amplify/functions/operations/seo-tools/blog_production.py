"""Durable zero-paid-AI editorial production state for Conversations and Gastronomy.

ChatGPT (or another human-operated editor) does the editorial reasoning. AWS owns the durable
state so a new chat/session can resume without relying on conversation history.

This module deliberately DOES NOT call Bedrock and DOES NOT publish. It only:
  * keeps one control record per category,
  * selects one extracted source at a time per category,
  * stores opportunity manifests and article intents,
  * records the approved sample/master version,
  * stores article work and checkpoints,
  * releases the category lane when the source's editorial work is complete.

DynamoDB is authoritative for small/queryable state. S3 is the durable artifact store.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from botocore.exceptions import ClientError

import blog_sources
import storage

logger = logging.getLogger(__name__)

CATEGORIES: Tuple[str, ...] = ("Conversations", "Gastronomy")
CATEGORY_SLUGS = {"Conversations": "conversations", "Gastronomy": "gastronomy"}

CONTROL_RECORD_TYPE = "blogProductionControl"
INTENT_RECORD_TYPE = "blogArticleIntent"
SAMPLE_RECORD_TYPE = "blogSampleApproval"
RUN_RECORD_TYPE = "blogEditorialRun"

AI_MODE = "CHATGPT_EXTERNAL"
AUTO_PUBLISH = False

MASTERS_PREFIX = blog_sources.SECURE_ROOT_PREFIX + "02-masters/"
WORK_PREFIX = blog_sources.SECURE_ROOT_PREFIX + "03-work/"
CHECKPOINT_PREFIX = blog_sources.SECURE_ROOT_PREFIX + "04-checkpoints/"

INTENT_STATUSES = (
    "PLANNED", "SAMPLE_PENDING", "SAMPLE_APPROVED", "DRAFTED", "QA_READY",
    "HUMAN_REVIEW", "SIGNED_OFF", "RELEASED", "HOLD", "PUBLISHED", "VERIFIED",
)
CHATGPT_WRITABLE_STATUSES = frozenset({"DRAFTED", "QA_READY", "HOLD"})

PROMPT_VERSIONS = {
    "Conversations": "CONV-2026-10-16-v2",
    "Gastronomy": "GAST-2026-10-15-v1",
}

PROMPTS = {
    "Conversations": """# WECARE.DIGITAL Conversations — Zero-Cost Editorial Continuation Prompt

Role: ChatGPT is the editorial worker. AWS is durable state, not an AI model.

At the beginning of every session, load the Conversations production control record, current
master, current checkpoint, current source, existing published Conversations corpus, and pending
article intents. Never rely on chat history as authoritative state.

For each source: read the complete relevant source; identify central distinctions and materially
distinct reader purposes; check the live corpus before reserving article intents; preserve
necessary attribution; keep source provenance internal; do not cosmetically rewrite the source.
Report potential count, duplicate/overlap count, hold/reject count, and net-new count before bulk
article work. Create a sample when the current prompt version is not yet approved.

After sample approval, work through reserved article intents. Save every meaningful transition to
AWS. Machine/editorial preparation may proceed, but publication remains human-gated. Never
fabricate approval, sign-off, or publish state. autoPublish is always false.
""",
    "Gastronomy": """# WECARE.DIGITAL Gastronomy — Zero-Cost Editorial Continuation Prompt

Role: ChatGPT is the editorial worker. AWS is durable state, not an AI model.

At the beginning of every session, load the Gastronomy production control record, current master,
current checkpoint, current source, existing published Gastronomy corpus, and pending article
intents. Never rely on chat history as authoritative state.

For each source: read the complete relevant source; build the source profile; identify genuine
RECIPE, TECHNIQUE, INGREDIENT, CULINARY_ARTICLE, CULINARY_DISTINCTION, MENU_PAIRING, or
CULINARY_CULTURE_HISTORY opportunities as applicable; preserve quantities, temperatures, timing,
sequence, food-safety details, attribution and cultural/historical fidelity; check the live corpus
before reserving article intents. Never invent health claims or culinary facts. Report potential,
duplicate/overlap, hold/reject, and net-new counts before bulk article work. The 150-article
editorial manifest value is a ceiling, never a target.

After sample approval, work through reserved intents. Save every meaningful transition to AWS.
Publication remains human-gated. Never fabricate approval, sign-off, or publish state.
autoPublish is always false.
""",
}


def _category(value: Any) -> str:
    wanted = str(value or "").strip()
    if wanted not in CATEGORIES:
        raise ValueError(f"category must be one of {list(CATEGORIES)}")
    return wanted


def _slug(category: str) -> str:
    return CATEGORY_SLUGS[_category(category)]


def control_id(category: str) -> str:
    return f"blogcontrol_{_slug(category)}"


def master_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/current/master.json"


def prompt_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/current/editorial-master.md"


def policy_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/current/quality-policy.json"


def legacy_master_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/master-current.json"


def legacy_prompt_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/prompt-current.md"


def legacy_policy_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/quality-policy.json"


def master_history_root(category: str, prompt_sha256: str) -> str:
    version = PROMPT_VERSIONS[_category(category)]
    return f"{MASTERS_PREFIX}{_slug(category)}/history/{version}-{prompt_sha256[:12]}/"


def checkpoint_key(category: str) -> str:
    return f"{CHECKPOINT_PREFIX}{_slug(category)}/current.json"


def work_root(category: str, source_id: str) -> str:
    return f"{WORK_PREFIX}{_slug(category)}/{str(source_id).strip()}/"


def manifest_key(category: str, source_id: str) -> str:
    return work_root(category, source_id) + "opportunity-manifest.json"


def dedupe_key(category: str, source_id: str) -> str:
    return work_root(category, source_id) + "dedupe-report.json"


def sample_key(category: str, source_id: str, intent_id: str) -> str:
    return work_root(category, source_id) + f"samples/{intent_id}.json"


def article_key(category: str, source_id: str, intent_id: str) -> str:
    return work_root(category, source_id) + f"articles/{intent_id}.json"


def _put_json(key: str, value: Dict[str, Any]) -> str:
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET,
        Key=key,
        Body=json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return key


def _put_text(key: str, value: str) -> str:
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET,
        Key=key,
        Body=str(value).encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    return key


def _read_json(key: str) -> Dict[str, Any]:
    try:
        raw = blog_sources.s3_client().get_object(
            Bucket=blog_sources.BUCKET, Key=key)["Body"].read()
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - absent checkpoint/master is a normal first-run state
        return {}


def _editorial_master_text(category: str) -> str:
    category = _category(category)
    if category == "Conversations":
        path = Path(__file__).with_name("conversations-production-master.md")
        if path.exists():
            return path.read_text(encoding="utf-8")
    return PROMPTS[category]


def _prompt_sha256(category: str) -> str:
    return hashlib.sha256(_editorial_master_text(category).encode("utf-8")).hexdigest()

def _policy(category: str) -> Dict[str, Any]:
    import blog_catalog
    return dict(blog_catalog.MASTER_POLICIES[_category(category)])


def _base_control(category: str, actor: str) -> Dict[str, Any]:
    now = storage.now_iso()
    return {
        "id": control_id(category),
        "recordType": CONTROL_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": _slug(category),
        "category": category,
        "enabled": True,
        "paused": False,
        "aiMode": AI_MODE,
        "aiBackendEnabled": False,
        "autoPublish": AUTO_PUBLISH,
        "masterVersion": "1",
        "promptVersion": PROMPT_VERSIONS[category],
        "approvedPromptVersion": "",
        "currentSourceId": "",
        "currentIntentId": "",
        "currentStage": "IDLE",
        "lastCheckpointKey": checkpoint_key(category),
        "lastCompletedAt": "",
        "lastActor": actor,
        "error": "",
    }


def ensure_control(category: str, actor: str) -> Dict[str, Any]:
    category = _category(category)
    existing = storage.get_typed(control_id(category), CONTROL_RECORD_TYPE)
    if existing:
        return existing
    record = _base_control(category, actor)
    storage.put_record(record)
    return record


def _master_document(category: str, actor: str) -> Dict[str, Any]:
    control = ensure_control(category, actor)
    now = storage.now_iso()
    prompt_sha = _prompt_sha256(category)
    return {
        "category": category,
        "masterVersion": control.get("masterVersion", "1"),
        "promptVersion": PROMPT_VERSIONS[category],
        "promptSha256": prompt_sha,
        "updatedAt": now,
        "aiMode": AI_MODE,
        "paidAiBackend": False,
        "autoPublish": False,
        "humanGateRequired": True,
        "bucket": blog_sources.BUCKET,
        "table": storage.TABLE_NAME,
        "controlRecordId": control["id"],
        "sourcePrefix": blog_sources.category_source_prefix(category),
        "workPrefix": f"{WORK_PREFIX}{_slug(category)}/",
        "checkpointKey": checkpoint_key(category),
        "editorialMasterKey": prompt_key(category),
        "qualityPolicyKey": policy_key(category),
        "qualityPolicy": _policy(category),
        "continuationRule": (
            "A new ChatGPT session must read AWS control/master/checkpoint state before work."
        ),
    }

def initialize(actor: str) -> Dict[str, Any]:
    """Project the current master and preserve a content-addressed immutable history."""
    categories: Dict[str, Any] = {}
    for category in CATEGORIES:
        control = ensure_control(category, actor)
        wanted_version = PROMPT_VERSIONS[category]
        if str(control.get("promptVersion") or "") != wanted_version:
            storage.table().update_item(
                Key={"id": control["id"]},
                UpdateExpression=(
                    "SET promptVersion = :p, approvedPromptVersion = :empty, "
                    "masterVersion = :m, updatedAt = :u, lastActor = :a"
                ),
                ExpressionAttributeValues={
                    ":p": wanted_version, ":empty": "", ":m": "2",
                    ":u": storage.now_iso(), ":a": actor,
                },
            )
            control = get_control(category)

        editorial_master = _editorial_master_text(category)
        prompt_sha = hashlib.sha256(editorial_master.encode("utf-8")).hexdigest()
        master = _master_document(category, actor)
        policy_doc = {
            "category": category,
            "promptVersion": wanted_version,
            "promptSha256": prompt_sha,
            "policy": _policy(category),
            "updatedAt": storage.now_iso(),
        }

        # Current canonical projection.
        _put_json(master_key(category), master)
        _put_text(prompt_key(category), editorial_master)
        _put_json(policy_key(category), policy_doc)

        # Compatibility projections for existing callers/tools.
        _put_json(legacy_master_key(category), master)
        _put_text(legacy_prompt_key(category), editorial_master)
        _put_json(legacy_policy_key(category), policy_doc)

        # Content-addressed history: changing content creates a new key even if somebody
        # forgets to bump a version, which matters because bucket versioning is suspended.
        history_root = master_history_root(category, prompt_sha)
        _put_json(history_root + "master.json", master)
        _put_text(history_root + "editorial-master.md", editorial_master)
        _put_json(history_root + "quality-policy.json", policy_doc)

        current = _read_json(checkpoint_key(category))
        if not current:
            current = {
                "category": category, "stage": "IDLE", "sourceId": "", "intentId": "",
                "promptVersion": wanted_version, "updatedAt": storage.now_iso(),
                "nextAction": "CLAIM_NEXT_SOURCE",
            }
            _put_json(checkpoint_key(category), current)
        categories[category] = {
            "control": _control_view(get_control(category)),
            "masterKey": master_key(category), "promptKey": prompt_key(category),
            "policyKey": policy_key(category), "masterHistoryRoot": history_root,
            "promptSha256": prompt_sha, "checkpointKey": checkpoint_key(category),
        }
    return {"initialized": True, "aiMode": AI_MODE, "paidAiBackend": False,
            "categories": categories}

def get_control(category: str) -> Dict[str, Any]:
    category = _category(category)
    return ensure_control(category, "system")


def _control_view(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "controlId": item.get("id", ""),
        "category": item.get("category", ""),
        "enabled": bool(item.get("enabled", True)),
        "paused": bool(item.get("paused", False)),
        "aiMode": item.get("aiMode", AI_MODE),
        "aiBackendEnabled": bool(item.get("aiBackendEnabled", False)),
        "autoPublish": bool(item.get("autoPublish", False)),
        "masterVersion": str(item.get("masterVersion") or "1"),
        "promptVersion": str(item.get("promptVersion") or ""),
        "approvedPromptVersion": str(item.get("approvedPromptVersion") or ""),
        "currentSourceId": str(item.get("currentSourceId") or ""),
        "currentIntentId": str(item.get("currentIntentId") or ""),
        "currentStage": str(item.get("currentStage") or "IDLE"),
        "lastCheckpointKey": str(item.get("lastCheckpointKey") or ""),
        "lastCompletedAt": str(item.get("lastCompletedAt") or ""),
        "lastActor": str(item.get("lastActor") or ""),
        "error": str(item.get("error") or ""),
    }


def _source_editorial_status(row: Dict[str, Any]) -> str:
    return str(row.get("editorialStatus") or "PENDING_EDITORIAL")


def _eligible_sources(category: str) -> List[Dict[str, Any]]:
    rows = storage.scan_by_record_type(blog_sources.RECORD_TYPE)
    out = [
        row for row in rows
        if row.get("category") == category
        and row.get("status") == blog_sources.EXTRACTED
        and _source_editorial_status(row) not in (
            "ARTICLE_PRODUCTION_COMPLETE", "EDITORIAL_REVIEW_COMPLETE",
            "PIPELINE_COMPLETE", "EDITORIAL_COMPLETE", "HOLD")
    ]
    out.sort(key=lambda row: (str(row.get("createdAt") or ""), str(row.get("id") or "")))
    return out


def claim_next_source(category: str, actor: str) -> Dict[str, Any]:
    """Claim exactly one extracted source for the category.

    If the lane already has a source, return it. Otherwise atomically set currentSourceId only
    when it is still empty. This makes a second ChatGPT/browser session resolve to the same work
    instead of silently starting another source.
    """
    category = _category(category)
    control = ensure_control(category, actor)
    if not control.get("enabled", True):
        raise ValueError(f"{category} production is disabled")
    if control.get("paused"):
        raise ValueError(f"{category} production is paused")

    current_id = str(control.get("currentSourceId") or "")
    if current_id:
        current = blog_sources.get_source(current_id)
        if current and _source_editorial_status(current) not in (
                "ARTICLE_PRODUCTION_COMPLETE", "EDITORIAL_REVIEW_COMPLETE",
                "PIPELINE_COMPLETE", "EDITORIAL_COMPLETE", "HOLD"):
            return {"claimed": False, "source": blog_sources.source_detail(current_id),
                    "control": _control_view(control), "note": "existing source resumed"}

    candidates = _eligible_sources(category)
    if not candidates:
        return {"claimed": False, "source": None, "control": _control_view(control),
                "note": "no extracted source is waiting"}

    source = candidates[0]
    source_id = str(source["id"])
    now = storage.now_iso()
    try:
        storage.table().update_item(
            Key={"id": control["id"]},
            UpdateExpression=(
                "SET currentSourceId = :sid, currentIntentId = :empty, "
                "currentStage = :stage, updatedAt = :u, lastActor = :actor, #e = :empty"
            ),
            ConditionExpression="currentSourceId = :empty",
            ExpressionAttributeNames={"#e": "error"},
            ExpressionAttributeValues={
                ":sid": source_id, ":empty": "", ":stage": "SOURCE_ANALYSIS",
                ":u": now, ":actor": actor,
            },
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            live = get_control(category)
            live_id = str(live.get("currentSourceId") or "")
            return {"claimed": False,
                    "source": blog_sources.source_detail(live_id) if live_id else None,
                    "control": _control_view(live),
                    "note": "another session claimed the category first"}
        raise

    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression="SET editorialStatus = :s, editorialClaimedAt = :u, editorialClaimedBy = :a",
        ExpressionAttributeValues={":s": "IN_EDITORIAL", ":u": now, ":a": actor},
    )
    checkpoint(category, {
        "stage": "SOURCE_ANALYSIS", "sourceId": source_id,
        "intentId": "", "nextAction": "READ_FULL_SOURCE_AND_BUILD_MANIFEST",
    }, actor)
    return {"claimed": True, "source": blog_sources.source_detail(source_id),
            "control": _control_view(get_control(category))}


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _intent_fingerprint(category: str, distinction: str, promise: str) -> str:
    raw = f"{_slug(category)}|{_normalise(distinction)}|{_normalise(promise)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def intent_id(category: str, distinction: str, promise: str) -> str:
    return "blogintent_" + _intent_fingerprint(category, distinction, promise)[:40]


def intents_for_source(source_id: str) -> List[Dict[str, Any]]:
    rows = [
        row for row in storage.list_slug_records(str(source_id))
        if row.get("recordType") == INTENT_RECORD_TYPE
    ]
    rows.sort(key=lambda row: (int(row.get("ordinal") or 0), str(row.get("createdAt") or "")))
    return [storage._json_safe(row) for row in rows]


def _word_set(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", _normalise(value)))


def _word_jaccard(left: Any, right: Any) -> float:
    a, b = _word_set(left), _word_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _manifest_dedupe_context(category: str) -> Dict[str, Any]:
    """Current published + reserved state used to record deterministic manifest evidence."""
    published = [
        row for row in storage.list_blog_posts(
            published_only=True, limit=0, include_content=False)
        if str(row.get("category") or "") == category
    ]
    intents = [
        row for row in storage.scan_by_record_type(INTENT_RECORD_TYPE, limit=0)
        if str(row.get("category") or "") == category
    ]
    return {"published": published, "intents": intents}


def _intent_dedupe_evidence(raw: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    import blog_quality_v2 as q

    title = str(raw.get("title") or "").strip()
    slug = q.slugify(title) if title else ""
    distinction = str(raw.get("centralDistinction") or "").strip()
    promise = str(raw.get("readerPromise") or "").strip()
    exact_slug, exact_title, near_title = [], [], []
    for post in context["published"]:
        pslug = str(post.get("slug") or "")
        ptitle = str(post.get("title") or "")
        if slug and pslug == slug:
            exact_slug.append({"slug": pslug, "title": ptitle})
        if title and _normalise(ptitle) == _normalise(title):
            exact_title.append({"slug": pslug, "title": ptitle})
        similarity = _word_jaccard(title, ptitle) if title and ptitle else 0.0
        if similarity >= 0.80 and _normalise(ptitle) != _normalise(title):
            near_title.append({"slug": pslug, "title": ptitle,
                               "similarity": round(similarity, 3)})

    near_intents = []
    for prior in context["intents"]:
        dsim = _word_jaccard(distinction, prior.get("centralDistinction"))
        psim = _word_jaccard(promise, prior.get("readerPromise"))
        if dsim >= 0.55 or psim >= 0.70:
            near_intents.append({
                "intentId": prior.get("id", ""), "title": prior.get("title", ""),
                "distinctionSimilarity": round(dsim, 3),
                "readerPromiseSimilarity": round(psim, 3),
            })

    return {
        "candidateTitle": title, "candidateSlug": slug,
        "exactPublishedSlug": exact_slug, "exactPublishedTitle": exact_title,
        "nearPublishedTitle": sorted(near_title, key=lambda x: x["similarity"], reverse=True)[:10],
        "nearReservedIntents": sorted(
            near_intents,
            key=lambda x: max(x["distinctionSimilarity"], x["readerPromiseSimilarity"]),
            reverse=True)[:10],
        "hardCollision": bool(exact_slug),
        "note": (
            "Deterministic evidence only. ChatGPT must still decide conceptual duplication; "
            "body-level corpus comparison runs again during QA."
        ),
    }

def submit_manifest(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    category = _category(body.get("category"))
    source_id = str(body.get("sourceId") or "").strip()
    if not source_id:
        raise ValueError("sourceId is required")
    source = blog_sources.get_source(source_id)
    if not source:
        raise LookupError("Unknown sourceId")
    if source.get("category") != category:
        raise ValueError("source category does not match manifest category")
    if source.get("status") != blog_sources.EXTRACTED:
        raise ValueError("source must be EXTRACTED before an editorial manifest is recorded")

    raw_intents = body.get("intents")
    if not isinstance(raw_intents, list):
        raise ValueError("intents must be an array")
    declared_duplicate = max(0, int(body.get("duplicateCount") or 0))
    rejected_count = max(0, int(body.get("rejectedCount") or 0))
    hold_count = max(0, int(body.get("holdCount") or 0))
    potential_count = int(body.get("potentialCount") or
                          (len(raw_intents) + declared_duplicate + rejected_count + hold_count))
    minimum = len(raw_intents) + declared_duplicate + rejected_count + hold_count
    if potential_count < minimum:
        raise ValueError("potentialCount cannot be smaller than accounted opportunities")

    import blog_article_work
    context = _manifest_dedupe_context(category)
    now = storage.now_iso()
    created: List[Dict[str, Any]] = []
    resolved: List[Dict[str, Any]] = []
    dedupe_items: List[Dict[str, Any]] = []
    backend_duplicate = 0

    for index, raw in enumerate(raw_intents, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"intents[{index - 1}] must be an object")
        distinction = str(raw.get("centralDistinction") or "").strip()
        promise = str(raw.get("readerPromise") or "").strip()
        purpose = str(raw.get("distinctPurpose") or raw.get("purpose") or "").strip()
        if len(distinction) < 8 or len(promise) < 8:
            raise ValueError(
                f"intents[{index - 1}] needs centralDistinction and readerPromise")

        evidence = _intent_dedupe_evidence(raw, context)
        iid = intent_id(category, distinction, promise)
        evidence["intentId"] = iid
        evidence["ordinal"] = index
        dedupe_items.append(evidence)

        if evidence["hardCollision"]:
            backend_duplicate += 1
            resolved.append({
                "intentId": iid, "sourceId": source_id, "status": "DUPLICATE",
                "created": False, "reason": "EXACT_PUBLISHED_SLUG",
                "matches": evidence["exactPublishedSlug"],
            })
            continue

        existing = storage.get_typed(iid, INTENT_RECORD_TYPE)
        if existing:
            backend_duplicate += 1
            resolved.append({
                "intentId": iid, "sourceId": existing.get("sourceId", ""),
                "status": existing.get("status", ""), "created": False,
                "reason": "EXISTING_INTENT_FINGERPRINT",
            })
            continue

        record = {
            "id": iid, "recordType": INTENT_RECORD_TYPE, "createdAt": now, "updatedAt": now,
            "slug": source_id, "sourceId": source_id,
            "batchId": source.get("batchId") or blog_sources.NO_BATCH,
            "category": category, "ordinal": index,
            "title": str(raw.get("title") or "").strip(),
            "centralDistinction": distinction, "readerPromise": promise,
            "distinctPurpose": purpose,
            "articleType": str(raw.get("articleType") or "").strip(),
            "fingerprint": _intent_fingerprint(category, distinction, promise),
            "status": "PLANNED", "workKey": article_key(category, source_id, iid),
            "dedupeEvidence": evidence, "createdBy": actor, "error": "",
        }
        try:
            storage.table().put_item(
                Item=storage._clean(record), ConditionExpression="attribute_not_exists(id)")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = storage.get_typed(iid, INTENT_RECORD_TYPE) or {}
            backend_duplicate += 1
            resolved.append({
                "intentId": iid, "sourceId": existing.get("sourceId", ""),
                "status": existing.get("status", ""), "created": False,
                "reason": "CONCURRENT_EXISTING_INTENT",
            })
            continue

        work = blog_article_work.ensure(source, record, actor)
        storage.table().update_item(
            Key={"id": iid},
            UpdateExpression="SET articleWorkId = :w, updatedAt = :u",
            ExpressionAttributeValues={":w": work["id"], ":u": storage.now_iso()},
        )
        record["articleWorkId"] = work["id"]
        created.append(record)
        context["intents"].append(record)

    duplicate_count = declared_duplicate + backend_duplicate
    dedupe_document = {
        "category": category, "sourceId": source_id, "generatedAt": now,
        "generatedBy": actor, "publishedCorpusChecked": len(context["published"]),
        "reservedIntentsChecked": len(context["intents"]),
        "declaredDuplicateCount": declared_duplicate,
        "backendDuplicateCount": backend_duplicate, "items": dedupe_items,
        "semanticDecisionOwner": "CHATGPT_EXTERNAL",
        "bodyLevelRecheck": "QA_WITH_LIVE_CORPUS",
    }
    dkey = _put_json(dedupe_key(category, source_id), dedupe_document)

    manifest = {
        "category": category, "sourceId": source_id, "generatedAt": now,
        "generatedBy": actor, "promptVersion": get_control(category).get("promptVersion", ""),
        "dedupeReportKey": dkey,
        "counts": {
            "potential": potential_count, "duplicate": duplicate_count,
            "declaredDuplicate": declared_duplicate, "backendDuplicate": backend_duplicate,
            "rejected": rejected_count, "hold": hold_count,
            "netNewRequested": len(raw_intents), "netNewReserved": len(created),
            "resolvedExisting": len(resolved),
        },
        "notes": str(body.get("notes") or "").strip(),
        "intents": [
            {
                "intentId": row["id"], "articleWorkId": row.get("articleWorkId", ""),
                "ordinal": row["ordinal"], "title": row["title"],
                "centralDistinction": row["centralDistinction"],
                "readerPromise": row["readerPromise"],
                "distinctPurpose": row["distinctPurpose"], "articleType": row["articleType"],
            } for row in created
        ],
        "resolvedExisting": resolved,
    }
    key = _put_json(manifest_key(category, source_id), manifest)

    stage = "SAMPLE_REQUIRED" if created else "NO_NET_NEW_ARTICLES"
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression=(
            "SET editorialStatus = :s, opportunityManifestKey = :k, dedupeReportKey = :dk, "
            "opportunityCount = :p, netNewArticleCount = :n, updatedAt = :u"
        ),
        ExpressionAttributeValues={
            ":s": stage, ":k": key, ":dk": dkey, ":p": potential_count,
            ":n": len(created), ":u": now,
        },
    )
    storage.table().update_item(
        Key={"id": control_id(category)},
        UpdateExpression="SET currentStage = :s, updatedAt = :u, lastActor = :a",
        ExpressionAttributeValues={":s": stage, ":u": now, ":a": actor},
    )
    checkpoint(category, {
        "stage": stage, "sourceId": source_id, "intentId": "",
        "potentialCount": potential_count, "netNewCount": len(created),
        "duplicateCount": duplicate_count, "rejectedCount": rejected_count,
        "dedupeReportKey": dkey,
        "nextAction": "CREATE_SAMPLE" if created else "COMPLETE_SOURCE_NO_NET_NEW",
    }, actor)
    return {
        "manifestKey": key, "dedupeReportKey": dkey, "counts": manifest["counts"],
        "createdIntents": [
            {"intentId": row["id"], "articleWorkId": row.get("articleWorkId", ""),
             "ordinal": row["ordinal"], "title": row["title"]}
            for row in created
        ],
        "resolvedExisting": resolved,
    }

def save_sample(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    category = _category(body.get("category"))
    source_id = str(body.get("sourceId") or "").strip()
    intent_ref = str(body.get("intentId") or "").strip()
    article = body.get("article")
    if not source_id or not intent_ref:
        raise ValueError("sourceId and intentId are required")
    if not isinstance(article, dict) or not str(article.get("contentMarkdown") or "").strip():
        raise ValueError("article with contentMarkdown is required")
    intent = storage.get_typed(intent_ref, INTENT_RECORD_TYPE)
    if not intent or intent.get("sourceId") != source_id or intent.get("category") != category:
        raise LookupError("Unknown article intent for this source/category")

    now = storage.now_iso()
    payload = {
        "category": category, "sourceId": source_id, "intentId": intent_ref,
        "promptVersion": get_control(category).get("promptVersion", ""),
        "createdAt": now, "createdBy": actor, "article": article,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sample_hash = hashlib.sha256(raw).hexdigest()
    key = sample_key(category, source_id, intent_ref)
    _put_json(key, {**payload, "sampleSha256": sample_hash})
    import blog_article_work
    work_ref = str(intent.get("articleWorkId") or blog_article_work.work_id(intent_ref))
    blog_article_work.apply_article(work_ref, article, actor, editorial_status="SAMPLE_PENDING")
    storage.table().update_item(
        Key={"id": intent_ref},
        UpdateExpression="SET #s = :s, sampleKey = :k, sampleSha256 = :h, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "SAMPLE_PENDING", ":k": key, ":h": sample_hash, ":u": now,
        },
    )
    storage.table().update_item(
        Key={"id": control_id(category)},
        UpdateExpression=(
            "SET currentIntentId = :i, currentStage = :s, updatedAt = :u, lastActor = :a"
        ),
        ExpressionAttributeValues={
            ":i": intent_ref, ":s": "SAMPLE_REVIEW", ":u": now, ":a": actor,
        },
    )
    checkpoint(category, {
        "stage": "SAMPLE_REVIEW", "sourceId": source_id, "intentId": intent_ref,
        "sampleKey": key, "sampleSha256": sample_hash, "nextAction": "AWAIT_SAMPLE_APPROVAL",
    }, actor)
    return {"sampleKey": key, "sampleSha256": sample_hash, "status": "SAMPLE_PENDING"}


def approve_sample(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    category = _category(body.get("category"))
    source_id = str(body.get("sourceId") or "").strip()
    intent_ref = str(body.get("intentId") or "").strip()
    approved = body.get("approved")
    if approved is not True:
        raise ValueError("approved must be true; rejection should revise/save a new sample")
    intent = storage.get_typed(intent_ref, INTENT_RECORD_TYPE)
    if not intent or intent.get("sourceId") != source_id or intent.get("category") != category:
        raise LookupError("Unknown article intent for this source/category")
    sample_hash = str(intent.get("sampleSha256") or "")
    if not sample_hash:
        raise ValueError("this intent has no saved sample to approve")

    control = get_control(category)
    prompt_version = str(control.get("promptVersion") or PROMPT_VERSIONS[category])
    now = storage.now_iso()
    record = {
        "id": f"blogsample_{uuid.uuid4().hex}",
        "recordType": SAMPLE_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": category,
        "category": category,
        "sourceId": source_id,
        "intentId": intent_ref,
        "promptVersion": prompt_version,
        "sampleSha256": sample_hash,
        "approved": True,
        "approvedBy": actor,
        "approvedAt": now,
        "notes": str(body.get("notes") or "").strip(),
    }
    storage.put_record(record)
    storage.table().update_item(
        Key={"id": intent_ref},
        UpdateExpression="SET #s = :s, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "SAMPLE_APPROVED", ":u": now},
    )
    import blog_article_work
    work_ref = str(intent.get("articleWorkId") or blog_article_work.work_id(intent_ref))
    blog_article_work.set_intent_status(work_ref, "SAMPLE_APPROVED", actor)
    storage.table().update_item(
        Key={"id": control_id(category)},
        UpdateExpression=(
            "SET approvedPromptVersion = :p, currentStage = :s, "
            "updatedAt = :u, lastActor = :a"
        ),
        ExpressionAttributeValues={
            ":p": prompt_version, ":s": "ARTICLE_PRODUCTION", ":u": now, ":a": actor,
        },
    )
    checkpoint(category, {
        "stage": "ARTICLE_PRODUCTION", "sourceId": source_id, "intentId": intent_ref,
        "approvedPromptVersion": prompt_version, "sampleApprovalId": record["id"],
        "nextAction": "PRODUCE_RESERVED_ARTICLES",
    }, actor)
    return {
        "approvalId": record["id"], "approved": True,
        "promptVersion": prompt_version, "sampleSha256": sample_hash,
    }


def save_article(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Persist ChatGPT editorial work onto the independent article-work child.

    This route cannot write protected downstream states. SIGNED_OFF/RELEASED/PUBLISHED/VERIFIED
    are earned only by the mature QA/publish/verify modules.
    """
    category = _category(body.get("category"))
    intent_ref = str(body.get("intentId") or "").strip()
    status = str(body.get("status") or "DRAFTED").strip().upper()
    article = body.get("article")
    if status not in CHATGPT_WRITABLE_STATUSES:
        raise ValueError(
            f"ChatGPT article writes may use only {sorted(CHATGPT_WRITABLE_STATUSES)}")
    if not isinstance(article, dict) or not str(article.get("contentMarkdown") or "").strip():
        raise ValueError("article with contentMarkdown is required")
    intent = storage.get_typed(intent_ref, INTENT_RECORD_TYPE)
    if not intent or intent.get("category") != category:
        raise LookupError("Unknown article intent")

    import blog_article_work
    source_id = str(intent.get("sourceId") or "")
    work_ref = str(intent.get("articleWorkId") or blog_article_work.work_id(intent_ref))
    if not blog_article_work.get(work_ref):
        blog_article_work.ensure_for_intent(intent_ref, actor)
    result = blog_article_work.apply_article(work_ref, article, actor, editorial_status=status)

    now = storage.now_iso()
    payload = {
        "category": category, "sourceId": source_id, "intentId": intent_ref,
        "articleWorkId": work_ref, "status": status,
        "promptVersion": get_control(category).get("promptVersion", ""),
        "updatedAt": now, "updatedBy": actor, "article": article,
        "editorialQa": body.get("qa") if isinstance(body.get("qa"), dict) else {},
    }
    key = article_key(category, source_id, intent_ref)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    artifact_hash = hashlib.sha256(raw).hexdigest()
    _put_json(key, {**payload, "artifactSha256": artifact_hash,
                    "articleBodySha256": result["bodySha256"]})
    storage.table().update_item(
        Key={"id": intent_ref},
        UpdateExpression=(
            "SET #s = :s, workKey = :k, articleWorkId = :w, bodySha256 = :h, "
            "updatedAt = :u, updatedBy = :a"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": status, ":k": key, ":w": work_ref, ":h": result["bodySha256"],
            ":u": now, ":a": actor,
        },
    )
    storage.table().update_item(
        Key={"id": control_id(category)},
        UpdateExpression=(
            "SET currentIntentId = :i, currentStage = :s, updatedAt = :u, lastActor = :a"
        ),
        ExpressionAttributeValues={
            ":i": intent_ref, ":s": status, ":u": now, ":a": actor,
        },
    )
    parent = blog_article_work.refresh_parent_status(source_id, actor)
    return {**result, "intentId": intent_ref, "status": status, "workKey": key,
            "articleWorkId": work_ref, "parentProgress": parent}

def checkpoint(category: str, body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    category = _category(category)
    control = ensure_control(category, actor)
    now = storage.now_iso()
    document = {
        "category": category,
        "stage": str(body.get("stage") or control.get("currentStage") or "IDLE"),
        "sourceId": str(body.get("sourceId") or control.get("currentSourceId") or ""),
        "intentId": str(body.get("intentId") or control.get("currentIntentId") or ""),
        "promptVersion": str(control.get("promptVersion") or ""),
        "approvedPromptVersion": str(control.get("approvedPromptVersion") or ""),
        "updatedAt": now,
        "updatedBy": actor,
        "nextAction": str(body.get("nextAction") or ""),
        "state": {
            key: value for key, value in body.items()
            if key not in {"stage", "sourceId", "intentId", "nextAction"}
        },
    }
    current_key = checkpoint_key(category)
    _put_json(current_key, document)
    history_key = (
        f"{CHECKPOINT_PREFIX}{_slug(category)}/history/"
        f"{now.replace(':','').replace('-','')}-{uuid.uuid4().hex[:8]}.json"
    )
    _put_json(history_key, document)
    run = {
        "id": f"blogrun_{uuid.uuid4().hex}",
        "recordType": RUN_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": category,
        "category": category,
        "sourceId": document["sourceId"],
        "intentId": document["intentId"],
        "stage": document["stage"],
        "checkpointKey": current_key,
        "historyKey": history_key,
        "actor": actor,
    }
    storage.put_record(run)
    storage.table().update_item(
        Key={"id": control["id"]},
        UpdateExpression=(
            "SET currentStage = :s, currentSourceId = :src, currentIntentId = :i, "
            "lastCheckpointKey = :k, updatedAt = :u, lastActor = :a"
        ),
        ExpressionAttributeValues={
            ":s": document["stage"], ":src": document["sourceId"],
            ":i": document["intentId"], ":k": current_key, ":u": now, ":a": actor,
        },
    )
    return {"checkpointKey": current_key, "historyKey": history_key, "runId": run["id"]}


def complete_source(category: str, source_id: str, actor: str) -> Dict[str, Any]:
    """Release the ChatGPT editorial lane after article production, not after publication."""
    category = _category(category)
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("sourceId is required")
    control = get_control(category)
    if str(control.get("currentSourceId") or "") != source_id:
        raise ValueError("sourceId is not the category's current editorial source")

    import blog_article_work
    state = blog_article_work.progress(source_id)
    intents = intents_for_source(source_id)
    if intents and not state["articleProductionComplete"]:
        remaining = max(0, state["articles"] - state["drafted"] - state["held"])
        raise ValueError(
            f"{remaining} article work item(s) are not drafted or held; "
            "HUMAN_REVIEW alone never completes a source")
    if not intents:
        source = blog_sources.get_source(source_id) or {}
        if not str(source.get("opportunityManifestKey") or ""):
            raise ValueError("a source cannot complete before an opportunity manifest exists")

    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression=(
            "SET editorialStatus = :s, editorialCompletedAt = :u, editorialCompletedBy = :a"
        ),
        ExpressionAttributeValues={
            ":s": "ARTICLE_PRODUCTION_COMPLETE", ":u": now, ":a": actor,
        },
    )
    try:
        storage.table().update_item(
            Key={"id": control["id"]},
            UpdateExpression=(
                "SET currentSourceId = :empty, currentIntentId = :empty, currentStage = :idle, "
                "lastCompletedAt = :u, updatedAt = :u, lastActor = :a"
            ),
            ConditionExpression="currentSourceId = :sid",
            ExpressionAttributeValues={
                ":empty": "", ":idle": "IDLE", ":u": now, ":a": actor, ":sid": source_id,
            },
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        raise ValueError("category claim changed before source completion") from error

    checkpoint(category, {
        "stage": "IDLE", "sourceId": "", "intentId": "",
        "completedSourceId": source_id,
        "completion": "ARTICLE_PRODUCTION_COMPLETE",
        "nextAction": "CLAIM_NEXT_SOURCE",
    }, actor)
    return {
        "completed": True, "completion": "ARTICLE_PRODUCTION_COMPLETE",
        "sourceId": source_id, "progress": state, "nextAction": "CLAIM_NEXT_SOURCE",
        "note": ("ChatGPT production is complete. Human QA/release/publish/verification "
                 "continue independently and may advance the parent to PIPELINE_COMPLETE."),
    }

def _counts(category: str) -> Dict[str, Any]:
    sources = [
        row for row in storage.scan_by_record_type(blog_sources.RECORD_TYPE)
        if row.get("category") == category
    ]
    intents = [
        row for row in storage.scan_by_record_type(INTENT_RECORD_TYPE)
        if row.get("category") == category
    ]
    by_source: Dict[str, int] = {}
    for row in sources:
        key = _source_editorial_status(row)
        by_source[key] = by_source.get(key, 0) + 1
    by_intent: Dict[str, int] = {}
    for row in intents:
        key = str(row.get("status") or "PLANNED")
        by_intent[key] = by_intent.get(key, 0) + 1
    works = [
        row for row in storage.scan_by_record_type("blogArticleWork", limit=0)
        if row.get("category") == category
    ]
    return {
        "sources": len(sources),
        "sourceEditorialStatus": dict(sorted(by_source.items())),
        "intents": len(intents),
        "articleWork": len(works),
        "intentStatus": dict(sorted(by_intent.items())),
        "extractedWaiting": len(_eligible_sources(category)),
    }


def resume(category: str) -> Dict[str, Any]:
    category = _category(category)
    control = get_control(category)
    checkpoint_doc = _read_json(checkpoint_key(category))
    current_source_id = str(control.get("currentSourceId") or "")
    current_source = (
        blog_sources.source_detail(current_source_id) if current_source_id else None
    )
    current_intents = intents_for_source(current_source_id) if current_source_id else []
    if current_source_id:
        import blog_article_work
        current_work = blog_article_work.list_for_source(current_source_id)
    else:
        current_work = []
    next_candidates = _eligible_sources(category)
    return {
        "category": category,
        "control": _control_view(control),
        "counts": _counts(category),
        "checkpoint": checkpoint_doc,
        "currentSource": current_source,
        "currentIntents": current_intents,
        "currentArticleWork": current_work,
        "nextSourceId": (
            str(next_candidates[0].get("id") or "") if next_candidates else ""
        ),
        "masterKey": master_key(category),
        "promptKey": prompt_key(category),
        "promptSha256": _prompt_sha256(category),
        "policyKey": policy_key(category),
        "checkpointKey": checkpoint_key(category),
        "aiMode": AI_MODE,
        "paidAiBackend": False,
        "autoPublish": False,
    }


def dashboard() -> Dict[str, Any]:
    return {"categories": {category: resume(category) for category in CATEGORIES}}
