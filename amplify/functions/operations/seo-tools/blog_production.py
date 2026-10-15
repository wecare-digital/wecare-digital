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
    "PLANNED", "SAMPLE_PENDING", "SAMPLE_APPROVED", "DRAFTED",
    "QA_READY", "HUMAN_REVIEW", "APPROVED", "HOLD", "PUBLISHED",
)
EDITORIAL_TERMINAL = frozenset({"HUMAN_REVIEW", "APPROVED", "HOLD", "PUBLISHED"})

PROMPT_VERSIONS = {
    "Conversations": "CONV-2026-10-15-v1",
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
    return f"{MASTERS_PREFIX}{_slug(category)}/master-current.json"


def prompt_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/prompt-current.md"


def policy_key(category: str) -> str:
    return f"{MASTERS_PREFIX}{_slug(category)}/quality-policy.json"


def checkpoint_key(category: str) -> str:
    return f"{CHECKPOINT_PREFIX}{_slug(category)}/current.json"


def work_root(category: str, source_id: str) -> str:
    return f"{WORK_PREFIX}{_slug(category)}/{str(source_id).strip()}/"


def manifest_key(category: str, source_id: str) -> str:
    return work_root(category, source_id) + "opportunity-manifest.json"


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
    return {
        "category": category,
        "masterVersion": control.get("masterVersion", "1"),
        "promptVersion": control.get("promptVersion", PROMPT_VERSIONS[category]),
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
        "qualityPolicy": _policy(category),
        "continuationRule": (
            "A new ChatGPT session must read AWS control/master/checkpoint state before work."
        ),
    }


def initialize(actor: str) -> Dict[str, Any]:
    """Create the two category controls and the durable master/checkpoint artifacts.

    Idempotent: current master/prompt/policy files are deliberate projections of the current
    code policy. No paid model is called and no source/article state is advanced.
    """
    categories: Dict[str, Any] = {}
    for category in CATEGORIES:
        control = ensure_control(category, actor)
        master = _master_document(category, actor)
        _put_json(master_key(category), master)
        _put_text(prompt_key(category), PROMPTS[category])
        _put_json(policy_key(category), {
            "category": category,
            "promptVersion": PROMPT_VERSIONS[category],
            "policy": _policy(category),
            "updatedAt": storage.now_iso(),
        })
        current = _read_json(checkpoint_key(category))
        if not current:
            current = {
                "category": category,
                "stage": "IDLE",
                "sourceId": "",
                "intentId": "",
                "promptVersion": control.get("promptVersion", PROMPT_VERSIONS[category]),
                "updatedAt": storage.now_iso(),
                "nextAction": "CLAIM_NEXT_SOURCE",
            }
            _put_json(checkpoint_key(category), current)
        categories[category] = {
            "control": _control_view(control),
            "masterKey": master_key(category),
            "promptKey": prompt_key(category),
            "policyKey": policy_key(category),
            "checkpointKey": checkpoint_key(category),
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
        and _source_editorial_status(row) not in ("EDITORIAL_COMPLETE", "HOLD")
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
        if current and _source_editorial_status(current) not in ("EDITORIAL_COMPLETE", "HOLD"):
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
    duplicate_count = max(0, int(body.get("duplicateCount") or 0))
    rejected_count = max(0, int(body.get("rejectedCount") or 0))
    hold_count = max(0, int(body.get("holdCount") or 0))
    potential_count = int(body.get("potentialCount") or
                          (len(raw_intents) + duplicate_count + rejected_count + hold_count))
    minimum = len(raw_intents) + duplicate_count + rejected_count + hold_count
    if potential_count < minimum:
        raise ValueError("potentialCount cannot be smaller than accounted opportunities")

    now = storage.now_iso()
    created: List[Dict[str, Any]] = []
    resolved: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_intents, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"intents[{index - 1}] must be an object")
        distinction = str(raw.get("centralDistinction") or "").strip()
        promise = str(raw.get("readerPromise") or "").strip()
        purpose = str(raw.get("distinctPurpose") or raw.get("purpose") or "").strip()
        if len(distinction) < 8 or len(promise) < 8:
            raise ValueError(
                f"intents[{index - 1}] needs centralDistinction and readerPromise")
        iid = intent_id(category, distinction, promise)
        existing = storage.get_typed(iid, INTENT_RECORD_TYPE)
        if existing:
            resolved.append({
                "intentId": iid, "sourceId": existing.get("sourceId", ""),
                "status": existing.get("status", ""), "created": False,
            })
            continue
        record = {
            "id": iid,
            "recordType": INTENT_RECORD_TYPE,
            "createdAt": now,
            "updatedAt": now,
            "slug": source_id,
            "sourceId": source_id,
            "batchId": source.get("batchId") or blog_sources.NO_BATCH,
            "category": category,
            "ordinal": index,
            "title": str(raw.get("title") or "").strip(),
            "centralDistinction": distinction,
            "readerPromise": promise,
            "distinctPurpose": purpose,
            "articleType": str(raw.get("articleType") or "").strip(),
            "fingerprint": _intent_fingerprint(category, distinction, promise),
            "status": "PLANNED",
            "workKey": article_key(category, source_id, iid),
            "createdBy": actor,
            "error": "",
        }
        try:
            storage.table().put_item(
                Item=storage._clean(record),
                ConditionExpression="attribute_not_exists(id)",
            )
            created.append(record)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = storage.get_typed(iid, INTENT_RECORD_TYPE) or {}
            resolved.append({
                "intentId": iid, "sourceId": existing.get("sourceId", ""),
                "status": existing.get("status", ""), "created": False,
            })

    manifest = {
        "category": category,
        "sourceId": source_id,
        "generatedAt": now,
        "generatedBy": actor,
        "promptVersion": get_control(category).get("promptVersion", ""),
        "counts": {
            "potential": potential_count,
            "duplicate": duplicate_count,
            "rejected": rejected_count,
            "hold": hold_count,
            "netNewRequested": len(raw_intents),
            "netNewReserved": len(created),
            "resolvedExisting": len(resolved),
        },
        "notes": str(body.get("notes") or "").strip(),
        "intents": [
            {
                "intentId": row["id"], "ordinal": row["ordinal"], "title": row["title"],
                "centralDistinction": row["centralDistinction"],
                "readerPromise": row["readerPromise"],
                "distinctPurpose": row["distinctPurpose"],
                "articleType": row["articleType"],
            }
            for row in created
        ],
        "resolvedExisting": resolved,
    }
    key = _put_json(manifest_key(category, source_id), manifest)

    stage = "SAMPLE_REQUIRED"
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression=(
            "SET editorialStatus = :s, opportunityManifestKey = :k, "
            "opportunityCount = :p, netNewArticleCount = :n, updatedAt = :u"
        ),
        ExpressionAttributeValues={
            ":s": stage, ":k": key, ":p": potential_count, ":n": len(created), ":u": now,
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
        "nextAction": "CREATE_SAMPLE",
    }, actor)
    return {
        "manifestKey": key,
        "counts": manifest["counts"],
        "createdIntents": [
            {"intentId": row["id"], "ordinal": row["ordinal"], "title": row["title"]}
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
    category = _category(body.get("category"))
    intent_ref = str(body.get("intentId") or "").strip()
    status = str(body.get("status") or "DRAFTED").strip().upper()
    article = body.get("article")
    if status not in INTENT_STATUSES:
        raise ValueError(f"status must be one of {list(INTENT_STATUSES)}")
    if not isinstance(article, dict) or not str(article.get("contentMarkdown") or "").strip():
        raise ValueError("article with contentMarkdown is required")
    intent = storage.get_typed(intent_ref, INTENT_RECORD_TYPE)
    if not intent or intent.get("category") != category:
        raise LookupError("Unknown article intent")
    source_id = str(intent.get("sourceId") or "")
    now = storage.now_iso()
    payload = {
        "category": category,
        "sourceId": source_id,
        "intentId": intent_ref,
        "status": status,
        "promptVersion": get_control(category).get("promptVersion", ""),
        "updatedAt": now,
        "updatedBy": actor,
        "article": article,
        "qa": body.get("qa") if isinstance(body.get("qa"), dict) else {},
    }
    key = article_key(category, source_id, intent_ref)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    body_hash = hashlib.sha256(raw).hexdigest()
    _put_json(key, {**payload, "bodySha256": body_hash})
    storage.table().update_item(
        Key={"id": intent_ref},
        UpdateExpression=(
            "SET #s = :s, workKey = :k, bodySha256 = :h, updatedAt = :u, updatedBy = :a"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": status, ":k": key, ":h": body_hash, ":u": now, ":a": actor,
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
    return {"intentId": intent_ref, "status": status, "workKey": key, "bodySha256": body_hash}


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
    category = _category(category)
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("sourceId is required")
    control = get_control(category)
    if str(control.get("currentSourceId") or "") != source_id:
        raise ValueError("sourceId is not the category's current editorial source")
    intents = intents_for_source(source_id)
    nonterminal = [
        row for row in intents if str(row.get("status") or "PLANNED") not in EDITORIAL_TERMINAL
    ]
    if nonterminal:
        raise ValueError(
            f"{len(nonterminal)} article intents are not yet at HUMAN_REVIEW/APPROVED/HOLD/PUBLISHED"
        )

    now = storage.now_iso()
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression="SET editorialStatus = :s, editorialCompletedAt = :u, editorialCompletedBy = :a",
        ExpressionAttributeValues={":s": "EDITORIAL_COMPLETE", ":u": now, ":a": actor},
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
        "completedSourceId": source_id, "nextAction": "CLAIM_NEXT_SOURCE",
    }, actor)
    return {"completed": True, "sourceId": source_id, "nextAction": "CLAIM_NEXT_SOURCE"}


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
    return {
        "sources": len(sources),
        "sourceEditorialStatus": dict(sorted(by_source.items())),
        "intents": len(intents),
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
    next_candidates = _eligible_sources(category)
    return {
        "category": category,
        "control": _control_view(control),
        "counts": _counts(category),
        "checkpoint": checkpoint_doc,
        "currentSource": current_source,
        "currentIntents": current_intents,
        "nextSourceId": (
            str(next_candidates[0].get("id") or "") if next_candidates else ""
        ),
        "masterKey": master_key(category),
        "promptKey": prompt_key(category),
        "policyKey": policy_key(category),
        "checkpointKey": checkpoint_key(category),
        "aiMode": AI_MODE,
        "paidAiBackend": False,
        "autoPublish": False,
    }


def dashboard() -> Dict[str, Any]:
    return {"categories": {category: resume(category) for category in CATEGORIES}}
