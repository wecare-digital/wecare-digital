"""Blog source intake: presigned upload, a durable source record, and the async worker.

THE SHAPE, AND WHY IT IS NOT ONE SYNCHRONOUS REQUEST.

API Gateway cuts a Lambda integration off at 30 seconds. Extracting one PDF is fast;
extracting fifty is not, and "thousands in one go" is the stated requirement. So the work is
split into three phases that each fit comfortably inside their own limit:

  1. `POST /seo-tools/blog-sources`         register N sources, return N presigned PUT URLs.
                                            No bytes touch this function.
  2. browser PUTs each file straight to S3   the only step whose duration scales with size,
                                            and it happens outside our compute entirely.
  3. `POST /seo-tools/blog-sources/confirm`  head_object each key, then hand off to the
                                            worker with InvocationType='Event' and return.

The worker then runs OUTSIDE the API Gateway request, so its ceiling is the function
timeout rather than 30s, and it CHAINS: it processes a bounded batch, and if sources remain
it re-invokes itself. A 2,000-source run is therefore a sequence of short invocations that
can be interrupted and resumed, rather than one long one that cannot.

Resolve-before-generate is enforced here exactly as `scripts/blog_ledger.py` enforces it
locally: the record id is derived from the sha256 of the source bytes, so re-uploading the
same PDF lands on the row that already exists instead of minting a second article. That is
the one failure in this pipeline that cannot be undone after publication.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

import storage

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "wecare-seo-tools")

#: THE PUBLIC ROOT, BY OWNER INSTRUCTION, AND THE CONSEQUENCE IS REAL.
#:
#: `o/` is the public root of this bucket: CloudFront distribution E2GP22R4BIFGQ3 serves it
#: at `https://wecare.digital/get/o/...` with no authentication. `secure/` is the gated root,
#: denied wholesale at the edge. This prefix began as `secure/blog-src/` and was moved to
#: `o/` on owner instruction, confirmed a second time on 2026-09-29 to cover derived
#: artefacts too - so a source document AND its extracted text are fetchable by anyone who
#: has the URL.
#:
#: What limits the exposure, stated so nobody over-credits it:
#:   - Keys are content hashes or record ids, so they are not guessable and not derivable
#:     from the filename.
#:   - Bucket listing is not public - all four public-access-block settings are on and the
#:     bucket policy grants s3:GetObject only to the CloudFront service principal.
#: So a source is unlisted-but-public: safe from enumeration, not safe once a URL leaks.
#:
#: That matters because these are third-party documents - books, journal articles, pages -
#: and a public URL is a public copy. If that becomes unacceptable, the fix is to move the
#: prefix back under `secure/` and let the existing edge deny cover it; nothing else in this
#: module has to change, because the key is composed through `media_paths` below.
BUCKET = os.environ.get("BLOG_SOURCE_BUCKET", os.environ.get("SECURE_FILES_BUCKET", "wecare-digital-get"))

#: Composed through `media_paths` rather than hand-built, which that module explicitly asks
#: for: "Keep composing keys through `public` and `secure` rather than hand-building them."
#: It also documents why `o/` is load-bearing and cannot simply be dropped.
#:
#: Renamed from `o/blog-src/` to `o/blog-production/` on 2026-09-29, while the prefix held
#: ZERO objects. That made it a constant change rather than a data migration, and it is the
#: last moment at which that was true.
try:
    from lambda_utils import media_paths
    ROOT_PREFIX = media_paths.public("blog-production") + "/"
except ImportError:  # pragma: no cover - media_paths ships in every package
    ROOT_PREFIX = "o/blog-production/"

#: The layout recorded in `.kiro/steering/blog-production-s3.md`. One place, so a key is
#: never assembled from a literal at a call site.
PREFIX = ROOT_PREFIX + "sources/pdf/"
URL_PREFIX = ROOT_PREFIX + "sources/url/"
EXTRACT_PREFIX = ROOT_PREFIX + "extracted/"
ANALYSIS_PREFIX = ROOT_PREFIX + "source-analysis/"
WORKING_PREFIX = ROOT_PREFIX + "article-working/"
QA_PREFIX = ROOT_PREFIX + "qa/"
#: Collection-level repetition, which is a property of a BATCH rather than of one article, so it
#: gets its own prefix keyed on the batch rather than living under `qa/`.
REPETITION_PREFIX = ROOT_PREFIX + "repetition/"
PUBLISH_PREFIX = ROOT_PREFIX + "publish-records/"
VERIFY_PREFIX = ROOT_PREFIX + "verification/"
FAILURE_PREFIX = ROOT_PREFIX + "failures/"

#: THE EXTRACT LIVES IN S3, NOT IN THE ITEM, AND THE REASON IS A HARD LIMIT.
#:
#: DynamoDB caps an item at 400 kB. The first version of this module wrote the full extracted
#: text into `sourceExtract` AND again inside `draftRecord`, so the item carried it twice. A
#: 300-page book is roughly 450 kB of text on its own, and `MAX_SOURCE_BYTES` allows a 40 MB
#: PDF - so the write failed on precisely the documents this pipeline exists to process,
#: while working fine on every small test fixture.
#:
#: So the text goes to `extracted/<sourceId>.md` and the item keeps a bounded preview plus
#: the key. The preview is what the admin list renders; the full text is fetched on demand.
EXTRACT_PREVIEW_CHARS = 1500
UPLOAD_URL_TTL = int(os.environ.get("BLOG_SOURCE_URL_TTL_SECONDS", "900"))
MAX_SOURCE_BYTES = int(os.environ.get("BLOG_SOURCE_MAX_BYTES", str(40 * 1024 * 1024)))
#: How many sources one worker invocation handles before chaining. Sized so the batch
#: finishes well inside the 120s function timeout even when every PDF is large.
WORKER_BATCH = int(os.environ.get("BLOG_WORKER_BATCH", "5"))
MAX_REGISTER_BATCH = 1000

RECORD_TYPE = "blogSource"

#: ONE PROJECTED ATTRIBUTE FOR THE WHOLE PIPELINE, AND THE REASON IS A HARD AWS LIMIT.
#:
#: DynamoDB caps a GSI's `NonKeyAttributes` at 20 names. `batchId-createdAt-index` already
#: spends 17 of them, and the remaining stages each want their own state on a batch listing -
#: which analysis was read, which template version the article was written to, which QA run
#: and sign-off it rests on, whether it published, whether verification passed. That is seven
#: more names against three free slots, so adding them one at a time hits the wall partway
#: through and the fix at that point is recreating a populated index.
#:
#: A MAP COUNTS AS ONE NAME. So every downstream stage writes into `pipeline`, the index
#: projects that single attribute, and the cap stops being a design constraint. It was worth
#: doing the moment the second stage arrived rather than the last: a GSI's projection cannot
#: be modified in place, so widening it means deleting and recreating the index, which is free
#: today at zero records and a migration once a wave is in flight.
#:
#: Written whole rather than by nested path: `SET pipeline.qaRunId = :v` fails outright on an
#: item that has no `pipeline` yet, and there is no single expression that can both create the
#: map and set a key inside it. `update_pipeline` therefore reads, merges and writes - the same
#: read-modify-write `draftRecord` has always used, with the same bounded race (two operators
#: acting on ONE source at human speed), not a new one.
PIPELINE_FIELDS: Tuple[str, ...] = (
    "analysisId", "analysisVersion", "sourceReviewedFully",
    "templateId", "templateVersion",
    "qaRunId", "qaStatus", "signoffId", "signedOffBy",
    "publishStatus", "publishedAt", "postId", "postUrl",
    "verifyStatus", "verifiedAt", "repetitionStatus",
)


def empty_pipeline() -> Dict[str, Any]:
    """Every stage present and empty, so a listing never has to test for a missing key."""
    return {name: 0 if name.endswith("Version") else "" for name in PIPELINE_FIELDS}


def update_pipeline(record_id: str, **updates: Any) -> Dict[str, Any]:
    """Merge into a source's `pipeline` map and return the result.

    Unknown keys are refused rather than stored. The map is the index's whole view of the
    downstream pipeline, so a typo'd key would be a state that writes successfully, projects
    successfully, and is never read by anything.
    """
    unknown = sorted(set(updates) - set(PIPELINE_FIELDS))
    if unknown:
        raise ValueError(f"unknown pipeline fields: {unknown}")
    if not str(record_id or "").strip():
        raise ValueError("a record id is required to update a pipeline")
    item = storage.table().get_item(Key={"id": str(record_id)}).get("Item") or {}
    merged = {**empty_pipeline(), **storage._json_safe(item.get("pipeline") or {}), **updates}
    storage.table().update_item(
        Key={"id": str(record_id)},
        UpdateExpression="SET pipeline = :p, updatedAt = :u",
        ExpressionAttributeValues={":p": storage._clean(merged), ":u": storage.now_iso()},
    )
    return merged

#: The batch a source belongs to when it was submitted without one - the interactive
#: single-document path. NOT an empty string: DynamoDB omits an item from a GSI entirely when
#: its partition key attribute is absent or empty, so an unbatched source would be invisible
#: to every batch-index query, including the worker's. A sentinel keeps it indexed and
#: greppable.
NO_BATCH = "unbatched"

#: The statuses a source moves through. Deliberately NOT the article statuses from the
#: quality standard - those describe an article, these describe a source file.
PENDING_UPLOAD = "PENDING_UPLOAD"
UPLOADED = "UPLOADED"
EXTRACTING = "EXTRACTING"
EXTRACTED = "EXTRACTED"
EXTRACTION_FAILED = "EXTRACTION_FAILED"

SOURCE_TYPES = ("pdf", "url")

_s3 = None
_lambda = None


def s3_client():
    global _s3
    if _s3 is None:
        from botocore.client import Config
        # SigV4 + regional endpoint, so a presigned URL is valid in this region. Same
        # configuration secure-files uses for the same reason.
        _s3 = boto3.client("s3", region_name=REGION,
                           config=Config(signature_version="s3v4",
                                         s3={"addressing_style": "virtual"}))
    return _s3


def lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    """Canonical form for URL identity. Mirrors `blog_ledger.normalize_url`.

    Tracking parameters are stripped because otherwise the same article arriving with a
    `utm_source` reads as a different source and converts twice.
    """
    value = str(url or "").strip()
    if not value:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    match = re.match(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://(?P<rest>.*)$", value)
    if not match:
        return ""
    scheme = match.group("scheme").lower()
    rest = match.group("rest").split("#", 1)[0]

    # THE TRAILING SLASH IS STRIPPED FROM THE PATH, NOT FROM THE WHOLE STRING, and the
    # difference is a real defect this caught: `/p/?id=7` and `/p?id=7` are the same page,
    # but rstrip on the assembled URL cannot reach a slash that sits before the `?`. They
    # registered as two sources and would have converted the same article twice.
    path, _, query = rest.partition("?")
    host, _, tail = path.partition("/")
    path = host.lower() + ("/" + tail if tail else "")
    path = path.rstrip("/") or host.lower()

    keep = [part for part in query.split("&")
            if part and not re.match(
                r"^(?:utm_[a-z_]+|gclid|fbclid|mc_cid|mc_eid|ref|source|igshid)=",
                part, re.IGNORECASE)]
    return scheme + "://" + path + ("?" + "&".join(keep) if keep else "")


def source_id(source_type: str, ref: str, sha256: str = "") -> str:
    """The record id, and the join key.

    A PDF is identified by the sha256 of its BYTES, which the browser computes and sends.
    That means a renamed re-export is the same source and will not convert twice - the
    common case when a batch is re-exported from a drive with different filenames.
    """
    kind = str(source_type or "").lower()
    if kind == "pdf":
        if not sha256:
            raise ValueError("a pdf source requires its sha256")
        return f"blogsrc_{sha256}"
    return f"blogsrc_{_sha256_text(normalize_url(ref))}"


def _safe_extension(name: str) -> str:
    _, _, tail = str(name or "").rpartition(".")
    if tail and tail != name and 1 <= len(tail) <= 8 and tail.isalnum():
        return "." + tail.lower()
    return ""


def view(item: Dict[str, Any]) -> Dict[str, Any]:
    """The public name for the listing projection, so `blog_batches` need not reach for `_view`."""
    return _view(item)


def get_source(record_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_typed(record_id, RECORD_TYPE)


def list_sources(limit: int = 500) -> List[Dict[str, Any]]:
    return storage.list_records(RECORD_TYPE, limit=limit)


def source_url(key: str) -> str:
    """The apex URL for an uploaded source, or "" when there is no key.

    Only meaningful because the prefix is on the public root: a reviewer working through the
    quality standard has to read the source, and section 2 is explicit that an article may
    not be built from a title or an excerpt. Handing them a one-click link to the actual
    document is the difference between that rule being followed and being ticked.

    Returns "" for a gated key rather than a URL that would 403, which is what
    `media_paths.public_url` already does for exactly this reason - so if the prefix is ever
    moved back under `secure/`, this degrades to no link instead of a dead one.
    """
    if not key:
        return ""
    try:
        from lambda_utils import media_paths
        return media_paths.public_url(key)
    except ImportError:  # pragma: no cover
        return ""


def _view(item: Dict[str, Any]) -> Dict[str, Any]:
    """The projection a listing renders. Compact, deliberately.

    NEITHER THE EXTRACT NOR ITS PREVIEW BELONGS HERE, and the preview was briefly included
    with a comment claiming it was fine for the list. It is not: a batch is specified to hold
    thousands of sources, and 2,500 rows at a 1,500-character preview is a 3.75 MB response
    for a table that shows a status column. Both come from `source_detail`, one at a time.

    This projection is also the contract for the `batchId-createdAt-index` INCLUDE list. A
    field added here that the index does not project reads as EMPTY for batch-scoped queries
    while working everywhere else - a nasty class of bug, so
    `test_the_batch_index_projects_everything_the_view_needs` asserts the two agree.

    WHICH IS WHY SIX FIELDS LEFT. DynamoDB caps an index's `NonKeyAttributes` at **20**, and
    the first attempt at the batch index asked for 24 and was refused by `UpdateTable`. That
    cap is the reason this list is short, and the cut was made where a listing does not
    render the field anyway: `sourceSha256`, `contentSha256`, `sourceDate`, `sourcePages`,
    `sourceBytes` and `extractedChars` are all on `source_detail`, which reads the full item
    from the table and has no projection limit at all. Nothing in `blog-studio.tsx` read any
    of them from this view.

    The remaining headroom is deliberate. Tasks 6 onward add `articleId`, a QA run reference
    and a publish state to the source record, and each of those has to fit here to be
    visible on a batch page.
    """
    return {
        "sourceId": item.get("id", ""),
        "batchId": item.get("batchId", ""),
        "sourceType": item.get("sourceType", ""),
        "sourceRef": item.get("sourceRef", ""),
        #: Present only for an uploaded PDF on the public root. A URL source already has its
        #: own address in `sourceRef`.
        "sourceUrl": source_url(str(item.get("s3Key") or "")),
        "status": item.get("status", ""),
        "category": item.get("category", ""),
        "articleClass": item.get("articleClass", ""),
        "sourceTitle": item.get("sourceTitle", ""),
        "extractedWords": item.get("extractedWords", 0),
        "slug": item.get("slug", ""),
        "title": item.get("title", ""),
        "articleStatus": item.get("articleStatus", ""),
        "aiDraftStatus": item.get("aiDraftStatus", ""),
        "gateBlocking": item.get("gateBlocking", []),
        "gateReview": item.get("gateReview", []),
        #: Every downstream stage's state, as ONE attribute. See `PIPELINE_FIELDS` for why it
        #: is a map: the index can project 20 names and this would otherwise have been seven.
        "pipeline": {**empty_pipeline(), **(item.get("pipeline") or {})},
        "error": item.get("error", ""),
        "createdAt": item.get("createdAt", ""),
        "updatedAt": item.get("updatedAt", ""),
    }


# ── Phase 1: register and presign ───────────────────────────────────────────────

def register(body: Dict[str, Any], actor: str, categories: Tuple[str, ...]) -> Dict[str, Any]:
    """Create or resolve up to 1,000 source records and presign each new PDF.

    Validation and identity derivation happen before any write. Existing records are then
    resolved with BatchGetItem and new/retryable rows are written through DynamoDB's batch
    writer. That keeps a 1,000-source request bounded instead of doing 1,000 GetItem +
    1,000 PutItem network round-trips inside one API request.
    """
    entries = body.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("sources must be a non-empty array")
    if len(entries) > MAX_REGISTER_BATCH:
        raise ValueError(f"at most {MAX_REGISTER_BATCH} sources per request")

    batch_id = str(body.get("batchId") or "").strip()
    batch: Dict[str, Any] = {}
    if batch_id:
        import blog_batches
        batch = blog_batches.assert_accepting(batch_id)

    default_category = str(body.get("category") or batch.get("defaultCategory") or "").strip()
    default_class = str(body.get("articleClass") or batch.get("articleClass")
                        or "ARCHIVE_DERIVED").strip().upper()

    prepared: List[Dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"sources[{index}] must be an object")
        kind = str(entry.get("sourceType") or "").strip().lower()
        if kind not in SOURCE_TYPES:
            raise ValueError(f"sources[{index}].sourceType must be one of {list(SOURCE_TYPES)}")
        category = str(entry.get("category") or default_category).strip()
        if category not in categories:
            raise ValueError(f"sources[{index}].category must be one of {list(categories)}")
        article_class = str(entry.get("articleClass") or default_class).strip().upper()

        if kind == "pdf":
            sha256 = str(entry.get("sha256") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError(f"sources[{index}].sha256 must be a 64-character hex digest")
            size = int(entry.get("bytes") or 0)
            if size <= 0 or size > MAX_SOURCE_BYTES:
                raise ValueError(
                    f"sources[{index}].bytes must be between 1 and {MAX_SOURCE_BYTES}")
            ref = str(entry.get("fileName") or "").strip()
            if not ref:
                raise ValueError(f"sources[{index}].fileName is required")
            record_id = source_id("pdf", ref, sha256)
            key = PREFIX + sha256 + _safe_extension(ref)
        else:
            ref = normalize_url(entry.get("url") or entry.get("ref") or "")
            if not ref.startswith(("http://", "https://")):
                raise ValueError(f"sources[{index}].url must be an http(s) URL")
            sha256, size, key = "", 0, ""
            record_id = source_id("url", ref)

        prepared.append({
            "recordId": record_id, "sourceType": kind, "sourceRef": ref,
            "sourceSha256": sha256, "sourceBytes": size, "s3Key": key,
            "category": category, "articleClass": article_class,
        })

    existing_by_id = storage.get_typed_many(
        [item["recordId"] for item in prepared], RECORD_TYPE)
    registered: List[Dict[str, Any]] = []
    writes: List[Dict[str, Any]] = []

    for item in prepared:
        record_id = item["recordId"]
        kind = item["sourceType"]
        ref = item["sourceRef"]
        existing = existing_by_id.get(record_id)
        if existing and existing.get("status") in (UPLOADED, EXTRACTING, EXTRACTED):
            registered.append({
                "sourceId": record_id, "sourceRef": ref, "sourceType": kind,
                "status": existing["status"], "alreadyKnown": True, "uploadUrl": "",
            })
            continue

        now = storage.now_iso()
        record = {
            "id": record_id,
            "recordType": RECORD_TYPE,
            "createdAt": (existing or {}).get("createdAt") or now,
            "updatedAt": now,
            "slug": (existing or {}).get("slug") or record_id,
            "batchId": batch_id or (existing or {}).get("batchId") or NO_BATCH,
            "sourceType": kind,
            "sourceRef": ref,
            "sourceSha256": item["sourceSha256"],
            "s3Key": item["s3Key"],
            "sourceBytes": item["sourceBytes"],
            "category": item["category"],
            "articleClass": item["articleClass"],
            "status": PENDING_UPLOAD if kind == "pdf" else UPLOADED,
            "pipeline": (existing or {}).get("pipeline") or empty_pipeline(),
            "createdBy": actor,
            "error": "",
        }
        writes.append(record)

        upload_url = ""
        if kind == "pdf":
            upload_url = s3_client().generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": item["s3Key"],
                        "ContentType": "application/pdf"},
                ExpiresIn=UPLOAD_URL_TTL,
            )
        registered.append({
            "sourceId": record_id, "sourceRef": ref, "sourceType": kind,
            "status": record["status"], "alreadyKnown": False,
            "uploadUrl": upload_url, "expiresInSeconds": UPLOAD_URL_TTL if upload_url else 0,
        })

    storage.put_records(writes)
    logger.info(json.dumps({
        "event": "blog_sources_registered", "actor": actor, "count": len(registered),
        "new": sum(1 for row in registered if not row["alreadyKnown"]),
        "maxBatch": MAX_REGISTER_BATCH,
    }))
    return {"sources": registered, "bucket": BUCKET, "maxBatch": MAX_REGISTER_BATCH}


# ── Phase 2: confirm the bytes arrived, then hand off ────────────────────────────

def confirm(body: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Verify up to 1,000 uploaded objects concurrently, then fan them out to SQS.

    A serial ``head_object`` + DynamoDB update per source makes a 1,000-file wave exceed
    API Gateway's request budget even though the expensive extraction itself is async.
    Existing records are therefore batch-read once, and pending PDFs are checked in a
    bounded thread pool. The status write is conditional on PENDING_UPLOAD, so a retried
    confirm can never move an already-EXTRACTING source backwards to UPLOADED.
    """
    ids = body.get("sourceIds")
    if not isinstance(ids, list) or not ids:
        raise ValueError("sourceIds must be a non-empty array")
    if len(ids) > MAX_REGISTER_BATCH:
        raise ValueError(f"at most {MAX_REGISTER_BATCH} sourceIds per request")

    requested = [str(value).strip() for value in ids if str(value or "").strip()]
    records = storage.get_typed_many(requested, RECORD_TYPE)
    confirmed: List[str] = []
    missing: List[str] = []
    unknown: List[str] = []
    pending: List[Tuple[str, Dict[str, Any]]] = []

    for record_id in requested:
        record = records.get(record_id)
        if not record:
            unknown.append(record_id)
            continue
        if record.get("status") in (UPLOADED, EXTRACTING, EXTRACTED):
            confirmed.append(record_id)
            continue
        key = str(record.get("s3Key") or "")
        if not key:
            confirmed.append(record_id)
            continue
        pending.append((record_id, record))

    table_ref = storage.table()
    table_meta = getattr(table_ref, "meta", None)
    table_client = getattr(table_meta, "client", None) if table_meta is not None else None
    table_name = getattr(table_ref, "name", storage.TABLE_NAME)

    def update_uploaded(record_id: str, content_length: int) -> None:
        kwargs = {
            "Key": {"id": record_id},
            "UpdateExpression": "SET #s = :uploaded, sourceBytes = :b, updatedAt = :u, #e = :e",
            "ConditionExpression": "#s = :pending",
            "ExpressionAttributeNames": {"#s": "status", "#e": "error"},
            "ExpressionAttributeValues": {
                ":uploaded": UPLOADED, ":pending": PENDING_UPLOAD,
                ":b": int(content_length), ":u": storage.now_iso(), ":e": "",
            },
        }
        if table_client is not None:
            table_client.update_item(TableName=table_name, **kwargs)
        else:
            table_ref.update_item(**kwargs)

    def check_upload(item: Tuple[str, Dict[str, Any]]) -> Tuple[str, str]:
        record_id, record = item
        key = str(record.get("s3Key") or "")
        try:
            head = s3_client().head_object(Bucket=BUCKET, Key=key)
        except ClientError:
            return record_id, "missing"
        try:
            update_uploaded(record_id, int(head["ContentLength"]))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            # Another confirm/worker already moved it forward. That is success for confirm.
        return record_id, "confirmed"

    if pending:
        workers = min(32, len(pending))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for record_id, outcome in pool.map(check_upload, pending):
                if outcome == "confirmed":
                    confirmed.append(record_id)
                else:
                    missing.append(record_id)

    import blog_queue
    queued = blog_queue.enqueue(confirmed, reason="confirm") if confirmed else {
        "queued": 0, "failed": 0, "configured": False}
    started = False
    if confirmed and not queued["configured"]:
        started = start_worker(reason="confirm")
    logger.info(json.dumps({
        "event": "blog_sources_confirmed", "actor": actor, "confirmed": len(confirmed),
        "missing": len(missing), "unknown": len(unknown), "workerStarted": started,
        "queued": queued["queued"], "queueConfigured": queued["configured"],
        "maxBatch": MAX_REGISTER_BATCH,
    }))
    return {
        "confirmed": confirmed, "missingUpload": missing, "unknownSourceId": unknown,
        "workerStarted": started, "queued": queued["queued"],
        "queueFailed": queued["failed"], "queueConfigured": queued["configured"],
    }


# ── Phase 3: the worker ─────────────────────────────────────────────────────────

def start_worker(reason: str = "") -> bool:
    """Async self-invoke. Never raises: a failed hand-off must not fail the caller.

    The sources are already durable in DynamoDB at this point, so the worst case of a
    failed invoke is that extraction waits for the next confirm or a manual kick - not
    lost work. Failing the HTTP request instead would tell the operator their upload
    failed when it did not.
    """
    try:
        lambda_client().invoke(
            FunctionName=FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({"blogWorker": True, "reason": reason}).encode("utf-8"),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "blog_worker_invoke_failed", "error": type(exc).__name__}))
        return False


def _claim_for_extraction(record_id: str) -> bool:
    """UPLOADED -> EXTRACTING, atomically.

    The conditional expression is what makes two concurrent workers safe. Without it a
    chained invoke overlapping its predecessor would extract the same source twice, and
    with the Bedrock step attached that is a duplicated model call per overlap.
    """
    try:
        storage.table().update_item(
            Key={"id": record_id},
            UpdateExpression="SET #s = :working, updatedAt = :u",
            ConditionExpression="#s = :uploaded",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":working": EXTRACTING, ":uploaded": UPLOADED, ":u": storage.now_iso()},
        )
        return True
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def pending_sources(limit: int = 0) -> List[Dict[str, Any]]:
    """Sources waiting for extraction, oldest first, with NO 500-item ceiling.

    This used to be `list_sources()` filtered in Python, and `list_sources` goes through
    `storage.list_records`, which clamps to 500. A batch is specified to hold thousands, so
    past 500 the worker simply stopped finding work - silently, and while reporting
    `remaining: 0`, which is the worst possible way for a queue to fail.

    DynamoDB applies the status filter AFTER the read is paid for, so this is not a cheap
    steady-state query. It is correct, which is what matters until the SQS fan-off replaces
    the sweep entirely; at that point the worker consumes messages and stops asking the table
    what is outstanding.
    """
    rows = storage.scan_by_record_type(
        RECORD_TYPE, attribute="status", values=(UPLOADED,), limit=limit)
    rows.sort(key=lambda row: str(row.get("createdAt") or ""))
    return rows[:limit] if limit else rows


#: What `process_source` reports. Distinguished rather than collapsed to a boolean because the
#: SQS consumer has to act differently on each: EXTRACTED and FAILED are both done, SKIPPED means
#: another worker holds the claim, and only RAISED should make a message retry.
DONE = "DONE"
SKIPPED = "SKIPPED"
FAILED = "FAILED"
RAISED = "RAISED"


def process_source(record_id: str) -> str:
    """Claim one source, extract it, store the result. The unit of work, for both paths.

    Pulled out of `run_worker` when the SQS fan-out arrived, so the sweep and the queue consumer
    cannot drift. They differ only in how they choose the next source.

    The conditional claim is what makes at-least-once delivery safe: a standard SQS queue can
    deliver the same message twice, and the second delivery loses the UPLOADED -> EXTRACTING
    race and returns SKIPPED rather than extracting the document again. With the Bedrock step
    attached, a duplicate extraction is a duplicate model call.
    """
    import blog_pipeline as bp

    record = get_source(record_id)
    if not record:
        return SKIPPED
    if not _claim_for_extraction(record_id):
        return SKIPPED
    try:
        extract = _extract_one(record, bp)
    except Exception as exc:  # noqa: BLE001 - one bad source must not stop a batch
        logger.exception("blog source extraction raised")
        _fail(record_id, f"{type(exc).__name__} during extraction")
        return RAISED
    if not extract.ok:
        _fail(record_id, extract.error)
        return FAILED
    _store_extract(record, extract, bp)
    return DONE


def refresh_batches(batch_ids: Iterable[str]) -> None:
    """Recompute the status of the batches a unit of work touched.

    Batch status is DERIVED, so it is recomputed after the fact rather than incremented during
    it - and only for the batches actually touched, because refreshing every batch would page
    every source in the system on each worker run.
    """
    import blog_batches
    for batch_id in sorted({str(value) for value in batch_ids if value}):
        if batch_id == NO_BATCH:
            continue
        try:
            blog_batches.refresh_status(batch_id)
        except Exception:  # noqa: BLE001 - a rollup failure must not lose extraction work
            logger.exception("batch status refresh failed")


def run_worker(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a bounded batch, then chain if more remain.

    STILL HERE AFTER THE SQS FAN-OUT, and deliberately. A queue is the steady-state path, and
    a queue cannot find a source whose message was never sent or was lost - a record written
    before the queue existed, a `SendMessageBatch` that partially failed, a message that aged
    out. This sweep asks the table what is outstanding, which is the only reconciliation that
    does not depend on the queue being correct. `POST /blog-sources/drain` is its route.
    """
    batch = int(event.get("limit") or WORKER_BATCH)
    processed, failed = 0, 0
    touched_batches: set = set()
    for record in pending_sources(limit=batch):
        touched_batches.add(str(record.get("batchId") or NO_BATCH))
        outcome = process_source(record["id"])
        if outcome == DONE:
            processed += 1
        elif outcome in (FAILED, RAISED):
            failed += 1

    refresh_batches(touched_batches)
    remaining = len(pending_sources())
    chained = start_worker(reason="chain") if remaining else False
    logger.info(json.dumps({
        "event": "blog_worker_batch", "processed": processed, "failed": failed,
        "remaining": remaining, "chained": chained,
        "batches": sorted(touched_batches),
    }))
    return {"processed": processed, "failed": failed, "remaining": remaining,
            "chained": chained}


def _extract_one(record: Dict[str, Any], bp) -> Any:
    if record.get("sourceType") == "url":
        return bp.extract_url(record.get("sourceRef") or "")
    key = record.get("s3Key") or ""
    if not key:
        return bp.Extract(False, error="no S3 key recorded for this source")
    try:
        payload = s3_client().get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "S3Error")
        return bp.Extract(False, error=f"could not read the uploaded object ({code})")
    return bp.extract_pdf(payload, ref=record.get("sourceRef") or key)


def _fail(record_id: str, error: str) -> None:
    #: LOGGED AS ITS OWN EVENT, so a metric filter can count it.
    #:
    #: An extraction failure is caught and recorded on the record rather than raised, which is
    #: correct - one bad PDF must not stop a batch of 2,500. The consequence is that it produces no
    #: Lambda error, so `wecare-lambda-errors-wecare-seo-tools` never sees it and a run where every
    #: document failed looks identical to a run where every document succeeded. This line is what
    #: `wecare-blog-extraction-failures` counts.
    logger.warning(json.dumps({
        "event": "blog_source_extraction_failed", "sourceId": record_id,
        "error": str(error)[:300]}))
    storage.table().update_item(
        Key={"id": record_id},
        UpdateExpression="SET #s = :s, #e = :e, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": EXTRACTION_FAILED, ":e": str(error)[:900], ":u": storage.now_iso()},
    )


def extract_key(source_id: str) -> str:
    return EXTRACT_PREFIX + str(source_id) + ".md"


def write_extract(source_id: str, text: str) -> str:
    """Put the extracted text in S3 and return its key."""
    key = extract_key(source_id)
    s3_client().put_object(
        Bucket=BUCKET, Key=key, Body=text.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8")
    return key


def read_extract(record: Dict[str, Any]) -> str:
    """The full extracted text, from S3, with the item's preview as a fallback.

    The fallback is not belt-and-braces padding - it is what keeps a record created before
    this change readable. Those items carry the whole text inline under `sourceExtract` and
    no `extractKey`.
    """
    key = str(record.get("extractKey") or "")
    if key:
        try:
            return s3_client().get_object(Bucket=BUCKET, Key=key)["Body"].read().decode(
                "utf-8", errors="replace")
        except ClientError as error:
            logger.warning(json.dumps({
                "event": "blog_extract_read_failed", "sourceId": record.get("id", ""),
                "error": error.response.get("Error", {}).get("Code", "S3Error")}))
    return str(record.get("sourceExtract") or record.get("extractPreview") or "")


def _store_extract(record: Dict[str, Any], extract: Any, bp) -> None:
    """Persist the extract to S3, the metadata to DynamoDB, and run the quality gate.

    The gate runs HERE rather than only at publish time so the admin page can show, per
    source, exactly what is outstanding. Its verdict is advisory at this point by
    construction: a draft has no article body yet, so it cannot be anything but
    SOURCE_REVIEW.

    Note what the item does NOT hold: the extracted text. See `EXTRACT_PREVIEW_CHARS`.
    """
    import blog_quality_v2 as q
    import blog_gate

    key = write_extract(record["id"], extract.text)
    draft = _draft_record(record, extract, q, bp)
    #: Through `blog_gate.assess_draft`, never `q.assess`, so the template and the gate
    #: sign-off apply at every site that writes an `articleStatus` rather than at whichever
    #: ones somebody remembered to change.
    assessment = blog_gate.assess_draft(record, draft)
    # The gate has read the extract; the stored draft must not carry a second copy of it.
    stored_draft = {name: value for name, value in draft.items() if name != "sourceExtract"}
    stored_draft["extractKey"] = key

    storage.table().update_item(
        Key={"id": record["id"]},
        UpdateExpression=(
            "SET #s = :s, sourceTitle = :t, sourceDate = :d, sourcePages = :p, "
            "extractedChars = :c, extractedWords = :w, contentSha256 = :h, "
            "extractKey = :k, extractPreview = :pv, draftRecord = :dr, "
            "articleStatus = :as, gateBlocking = :gb, gateReview = :gr, "
            "updatedAt = :u, #e = :e REMOVE sourceExtract"
        ),
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": EXTRACTED,
            ":t": extract.title,
            ":d": extract.date,
            ":p": int(extract.pages or 0),
            ":c": len(extract.text),
            ":w": bp.word_count(extract.text),
            ":h": extract.content_sha256,
            ":k": key,
            ":pv": extract.text[:EXTRACT_PREVIEW_CHARS],
            ":dr": storage._clean(stored_draft),
            ":as": assessment["status"],
            ":gb": assessment["blocking"],
            ":gr": assessment["review"],
            ":u": storage.now_iso(),
            ":e": "",
        },
    )


def _draft_record(record: Dict[str, Any], extract: Any, q, bp) -> Dict[str, Any]:
    """A draft with every mechanical field filled and no editorial claim.

    Read what is NOT set. `sourceReviewedFully` is absent, the section 5 uniqueness
    booleans are absent, and `gate` is absent. Those are the fields a human fills after
    doing the reading, and `blog_quality_v2.decide_status` holds the record on
    SOURCE_REVIEW until they are. Pre-filling them would produce a record that validates
    and means nothing - the same contract `scripts/blog_ingest.draft_record` keeps.
    """
    title = extract.title or record.get("sourceRef", "")
    slug = q.slugify(title)
    words = bp.word_count(extract.text)
    if words <= 420:
        article_type = "DISTINCTION"
    elif words <= 820:
        article_type = "REFLECTION"
    elif words <= 1500:
        article_type = "ARTICLE"
    else:
        article_type = "DEEP_ARTICLE"
    return {
        "sourceId": record["id"],
        "articleClass": record.get("articleClass") or "ARCHIVE_DERIVED",
        "status": "SOURCE_REVIEW",
        "sourceFile": record.get("sourceRef", ""),
        "originalSourceTitle": extract.title,
        "originalSourceDate": extract.date,
        "sourceType": record.get("sourceType", ""),
        "sourceHash": record.get("sourceSha256") or extract.content_sha256,
        "title": title,
        "slug": slug,
        "category": record.get("category") or q.DEFAULT_CATEGORY,
        "author": q.AUTHOR,
        "canonical": q.expected_canonical(slug) if slug else "",
        "tags": [],
        "seoTitle": f"{title} | {q.PUBLISHER}" if title else "",
        "metaDescription": "",
        "articleType": article_type,
        "imageStatus": "none",
        #: Present on the in-memory draft so the gate can assess it, and STRIPPED before
        #: storage by `_store_extract` - the item must not carry a second copy of the text.
        "sourceExtract": extract.text,
        "contentMarkdown": "",
        "centralDistinction": "",
        "distinctPurpose": "",
    }


# ── Reporting ───────────────────────────────────────────────────────────────────

def status_report(limit: int = 0, batch_id: str = "") -> Dict[str, Any]:
    """Counts across every source, or one batch's.

    `limit=0` means all of them, and it goes through the paginating helper rather than
    `list_sources`, which clamps at 500. The old default silently reported on the most recent
    500 sources in a system specified to hold thousands - the number looked plausible, which
    is what made it dangerous.
    """
    if batch_id:
        import blog_batches
        rows = blog_batches.batch_sources(batch_id, limit=limit)
    else:
        rows = storage.scan_by_record_type(RECORD_TYPE, limit=limit)
    by_status: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    for row in rows:
        by_status[str(row.get("status") or "")] = by_status.get(str(row.get("status") or ""), 0) + 1
        category = str(row.get("category") or "")
        if category:
            by_category[category] = by_category.get(category, 0) + 1
    return {
        "total": len(rows),
        "byStatus": dict(sorted(by_status.items())),
        "byCategory": dict(sorted(by_category.items())),
        "pending": sum(1 for row in rows if row.get("status") == UPLOADED),
        "extracted": sum(1 for row in rows if row.get("status") == EXTRACTED),
        "failed": sum(1 for row in rows if row.get("status") == EXTRACTION_FAILED),
        "sources": [_view(row) for row in rows],
    }


def source_detail(record_id: str) -> Dict[str, Any]:
    record = get_source(record_id)
    if not record:
        raise LookupError("Unknown sourceId")
    view = _view(record)
    # Fetched from S3 rather than read off the item, because the item does not hold it.
    view["sourceExtract"] = read_extract(record)
    view["extractKey"] = str(record.get("extractKey") or "")
    view["extractPreview"] = str(record.get("extractPreview") or "")
    view["draftRecord"] = record.get("draftRecord", {})
    view["aiDraft"] = record.get("aiDraft", {})
    return view


def retry(record_id: str) -> Dict[str, Any]:
    """Put a failed source back in the queue.

    A transient S3 read or a network blip must not blacklist a source permanently, which is
    what a terminal EXTRACTION_FAILED with no way back would do.
    """
    record = get_source(record_id)
    if not record:
        raise LookupError("Unknown sourceId")
    if record.get("status") not in (EXTRACTION_FAILED, EXTRACTING):
        raise ValueError(f"only a failed source can be retried; this one is "
                         f"{record.get('status')}")
    storage.table().update_item(
        Key={"id": record_id},
        UpdateExpression="SET #s = :s, #e = :e, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": UPLOADED, ":e": "", ":u": storage.now_iso()},
    )
    return {"sourceId": record_id, "status": UPLOADED, "workerStarted": start_worker("retry")}
