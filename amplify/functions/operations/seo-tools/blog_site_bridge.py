"""Automatic native-publish -> Amplify-build -> real-site verification bridge.

Publishing a blogPost to DynamoDB is not the same event as publishing /post/<slug>/ on
wecare.digital. The website is a static Next export with fallback:false, so a new post exists on
the native API immediately but does not exist on the website until Amplify builds again.

This module closes that gap without doing one expensive build per article:

* every successful native publish marks the article SITE_BUILD_PENDING and increments one global
  generation;
* the first publish while the bridge is IDLE schedules ONE delayed SQS trigger; later publishes
  coalesce into the same generation;
* that trigger starts one Amplify RELEASE build and snapshots every pending published article;
* a delayed SQS check waits for Amplify (no Lambda sits open for a four-minute build);
* after a successful deploy, site verification fans out through the existing SQS consumer;
* an article becomes final VERIFIED only after BOTH the native thirteen-point verification and
  the real static website surfaces pass.

Publishes that happen while a build is running increment the generation but are not assigned to
that build. When the current generation finishes, the bridge automatically schedules the next
one. That is the coalescing rule that makes unlimited bulk practical.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError

import blog_sources
import storage

logger = logging.getLogger(__name__)

CONTROL_ID = "blogsitebuild_control"
CONTROL_RECORD_TYPE = "blogSiteBuildControl"
BUILD_RECORD_TYPE = "blogSiteBuild"
VERIFY_RECORD_TYPE = "blogSiteVerificationRun"

IDLE = "IDLE"
PENDING = "PENDING"
BUILDING = "BUILDING"
VERIFYING = "VERIFYING"
FAILED = "FAILED"
VERIFIED = "VERIFIED"
DEPLOYED = "DEPLOYED"

APP_ID = os.environ.get("BLOG_SITE_AMPLIFY_APP_ID", "d22dm4b0jn71jw")
BRANCH_NAME = os.environ.get("BLOG_SITE_AMPLIFY_BRANCH", "stack")
PUBLIC_SITE_URL = os.environ.get("BLOG_SITE_PUBLIC_URL", "https://wecare.digital").rstrip("/")

COALESCE_DELAY_SECONDS = int(os.environ.get("BLOG_SITE_BUILD_DELAY_SECONDS", "45"))
CHECK_DELAY_SECONDS = int(os.environ.get("BLOG_SITE_CHECK_DELAY_SECONDS", "90"))
VERIFY_RETRY_DELAY_SECONDS = int(os.environ.get("BLOG_SITE_VERIFY_RETRY_DELAY_SECONDS", "30"))
MAX_BUILD_CHECKS = int(os.environ.get("BLOG_SITE_MAX_BUILD_CHECKS", "8"))
MAX_SITE_VERIFY_ATTEMPTS = int(os.environ.get("BLOG_SITE_MAX_VERIFY_ATTEMPTS", "3"))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("BLOG_SITE_VERIFY_HTTP_TIMEOUT_SECONDS", "15"))
MAX_HTTP_BYTES = int(os.environ.get("BLOG_SITE_VERIFY_MAX_BYTES", str(8 * 1024 * 1024)))

_amplify = None


def amplify_client():
    global _amplify
    if _amplify is None:
        _amplify = boto3.client("amplify", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _amplify


def _conditional_failed(exc: Exception) -> bool:
    return (
        isinstance(exc, ClientError)
        and (exc.response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    )


def _initial_control() -> Dict[str, Any]:
    now = storage.now_iso()
    return {
        "id": CONTROL_ID,
        "recordType": CONTROL_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": "global",
        "status": IDLE,
        "generation": 0,
        "buildGeneration": 0,
        "jobId": "",
        "articleCount": 0,
        "verifyRemaining": 0,
        "verifyFailures": 0,
        "lastError": "",
        "lastCompletedAt": "",
    }


def ensure_control() -> Dict[str, Any]:
    found = storage.get_typed(CONTROL_ID, CONTROL_RECORD_TYPE)
    if found:
        return found
    item = _initial_control()
    try:
        storage.table().put_item(
            Item=storage._clean(item),
            ConditionExpression="attribute_not_exists(id)",
        )
    except ClientError as exc:
        if not _conditional_failed(exc):
            raise
    return storage.get_typed(CONTROL_ID, CONTROL_RECORD_TYPE) or item


def control() -> Dict[str, Any]:
    return ensure_control()


def _record_types() -> Tuple[str, str]:
    return (blog_sources.ARTICLE_WORK_RECORD_TYPE, blog_sources.RECORD_TYPE)


def _all_article_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record_type in _record_types():
        rows.extend(storage.scan_by_record_type(record_type, limit=0))
    return rows


def _is_published(row: Dict[str, Any]) -> bool:
    return str((row.get("pipeline") or {}).get("publishStatus") or "") == "PUBLISHED"


def _pending_rows() -> List[Dict[str, Any]]:
    return [
        row for row in _all_article_rows()
        if _is_published(row)
        and str((row.get("pipeline") or {}).get("siteVerifyStatus") or "") != VERIFIED
    ]


def _set_top_level(record_id: str, **values: Any) -> None:
    if not values:
        return
    names: Dict[str, str] = {}
    tokens: Dict[str, Any] = {":u": storage.now_iso()}
    assignments = ["updatedAt = :u"]
    for index, (name, value) in enumerate(values.items()):
        alias = f"#n{index}"
        token = f":v{index}"
        names[alias] = name
        tokens[token] = storage._clean(value)
        assignments.append(f"{alias} = {token}")
    storage.table().update_item(
        Key={"id": str(record_id)},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=tokens,
    )


def _mark_site_pending(source_id: str) -> None:
    blog_sources.update_pipeline(
        source_id,
        siteBuildStatus=PENDING,
        siteBuildJobId="",
        siteBuildGeneration=0,
        siteDeployedAt="",
        siteVerifyStatus=PENDING,
        siteVerifiedAt="",
        verifyStatus="SITE_BUILD_PENDING",
    )
    _set_top_level(source_id, siteVerifyState=PENDING, siteBuildJobId="", siteBuildGeneration=0)


def _increment_generation() -> int:
    ensure_control()
    response = storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression=(
            "SET updatedAt = :u, generation = if_not_exists(generation, :zero) + :one"
        ),
        ExpressionAttributeValues={
            ":u": storage.now_iso(), ":zero": 0, ":one": 1,
        },
        ReturnValues="ALL_NEW",
    )
    attrs = storage._json_safe(response.get("Attributes") or {})
    return int(attrs.get("generation") or 1)


def _claim_schedule(generation: int) -> bool:
    try:
        storage.table().update_item(
            Key={"id": CONTROL_ID},
            UpdateExpression=(
                "SET #s = :pending, updatedAt = :u, scheduledGeneration = :g, lastError = :e"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":pending": PENDING, ":idle": IDLE, ":u": storage.now_iso(),
                ":g": int(generation), ":e": "",
            },
            ConditionExpression="#s = :idle",
        )
        return True
    except ClientError as exc:
        if _conditional_failed(exc):
            return False
        raise


def _release_schedule(error: str = "") -> None:
    storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression="SET #s = :idle, updatedAt = :u, lastError = :e",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":idle": IDLE, ":u": storage.now_iso(), ":e": str(error or "")[:800],
        },
    )


def note_published(source_id: str, actor: str) -> Dict[str, Any]:
    """Mark a native publish dirty and schedule one coalesced site build."""
    record = blog_sources.get_source(source_id)
    if not record:
        raise LookupError("Unknown sourceId")
    if str((record.get("pipeline") or {}).get("publishStatus") or "") != "PUBLISHED":
        raise ValueError("site build can only follow a successful native publish")

    _mark_site_pending(source_id)
    generation = _increment_generation()
    scheduled = _claim_schedule(generation)
    queue_result: Dict[str, Any] = {"queued": 0, "failed": 0, "configured": False}
    if scheduled:
        import blog_queue
        queue_result = blog_queue.enqueue_site_build(
            generation, actor or "site-bridge", delay_seconds=COALESCE_DELAY_SECONDS)
        if not queue_result.get("configured") or int(queue_result.get("queued") or 0) != 1:
            _release_schedule("site-build trigger could not be queued")
            scheduled = False
            logger.error(json.dumps({
                "event": "blog_site_build_schedule_failed",
                "sourceId": source_id,
                "generation": generation,
                "queue": queue_result,
            }))
    logger.info(json.dumps({
        "event": "blog_site_build_pending",
        "sourceId": source_id,
        "generation": generation,
        "scheduled": scheduled,
        "coalesced": not scheduled,
    }))
    return {
        "siteBuildStatus": PENDING,
        "generation": generation,
        "scheduled": scheduled,
        "coalesced": not scheduled,
        "queue": queue_result,
    }


def trigger_pending(actor: str) -> Dict[str, Any]:
    """Bootstrap/retry the bridge for every published article not site-verified yet."""
    rows = _pending_rows()
    if not rows:
        return {"pending": 0, "scheduled": False, "status": IDLE}
    for row in rows:
        _mark_site_pending(str(row["id"]))
    generation = _increment_generation()
    scheduled = _claim_schedule(generation)
    result: Dict[str, Any] = {"queued": 0, "failed": 0, "configured": False}
    if scheduled:
        import blog_queue
        result = blog_queue.enqueue_site_build(
            generation, actor or "site-bridge", delay_seconds=0)
        if not result.get("configured") or int(result.get("queued") or 0) != 1:
            _release_schedule("manual site-build trigger could not be queued")
            scheduled = False
    return {
        "pending": len(rows), "generation": generation,
        "scheduled": scheduled, "queue": result,
    }


def _assign_pending(generation: int) -> List[str]:
    assigned: List[str] = []
    for row in _pending_rows():
        source_id = str(row.get("id") or "")
        if not source_id:
            continue
        blog_sources.update_pipeline(
            source_id,
            siteBuildStatus=BUILDING,
            siteBuildGeneration=int(generation),
            siteBuildJobId="",
            siteVerifyStatus=PENDING,
            verifyStatus="SITE_BUILD_PENDING",
        )
        _set_top_level(
            source_id,
            siteBuildGeneration=int(generation),
            siteBuildJobId="",
            siteVerifyState=PENDING,
        )
        assigned.append(source_id)
    return assigned


def _set_job_on_assigned(source_ids: Iterable[str], job_id: str, generation: int) -> None:
    for source_id in source_ids:
        blog_sources.update_pipeline(
            source_id,
            siteBuildStatus=BUILDING,
            siteBuildGeneration=int(generation),
            siteBuildJobId=job_id,
        )
        _set_top_level(
            source_id,
            siteBuildGeneration=int(generation),
            siteBuildJobId=job_id,
        )


def _build_record_id(job_id: str) -> str:
    return "blogsitebuild_" + str(job_id or "").replace("-", "")[:64]


def _put_build(job_id: str, generation: int, article_count: int, actor: str) -> Dict[str, Any]:
    now = storage.now_iso()
    record = {
        "id": _build_record_id(job_id),
        "recordType": BUILD_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": str(job_id),
        "jobId": str(job_id),
        "generation": int(generation),
        "status": BUILDING,
        "articleCount": int(article_count),
        "verifyFailures": 0,
        "appId": APP_ID,
        "branch": BRANCH_NAME,
        "startedBy": actor,
        "startedAt": now,
        "deployedAt": "",
        "completedAt": "",
        "error": "",
    }
    storage.put_record(record)
    return record


def _update_build(job_id: str, **values: Any) -> None:
    record_id = _build_record_id(job_id)
    if storage.get_typed(record_id, BUILD_RECORD_TYPE) is None:
        return
    _set_top_level(record_id, **values)


def _control_to_building(generation: int, article_count: int, job_id: str) -> None:
    storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression=(
            "SET #s = :building, buildGeneration = :g, jobId = :j, articleCount = :c, "
            "verifyRemaining = :zero, verifyFailures = :zero, updatedAt = :u, lastError = :e"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":building": BUILDING, ":g": int(generation), ":j": job_id,
            ":c": int(article_count), ":zero": 0, ":u": storage.now_iso(), ":e": "",
        },
    )


def start_build(actor: str = "site-bridge") -> Dict[str, Any]:
    """Claim the coalesced generation and start one Amplify release."""
    ensure_control()
    try:
        response = storage.table().update_item(
            Key={"id": CONTROL_ID},
            UpdateExpression="SET #s = :building, updatedAt = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":building": BUILDING, ":pending": PENDING, ":u": storage.now_iso(),
            },
            ConditionExpression="#s = :pending",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _conditional_failed(exc):
            current = control()
            return {
                "status": str(current.get("status") or IDLE),
                "started": False,
                "note": "another message already owns this generation",
            }
        raise

    current = storage._json_safe(response.get("Attributes") or control())
    generation = int(current.get("generation") or 0)
    assigned = _assign_pending(generation)
    if not assigned:
        _release_schedule("")
        return {"status": IDLE, "started": False, "articles": 0}

    try:
        result = amplify_client().start_job(
            appId=APP_ID,
            branchName=BRANCH_NAME,
            jobType="RELEASE",
            jobReason=f"Blog site build generation {generation}: {len(assigned)} published article(s)",
        )
        summary = result.get("jobSummary") or {}
        job_id = str(summary.get("jobId") or "")
        if not job_id:
            raise RuntimeError("Amplify StartJob returned no jobId")
    except Exception as exc:
        for source_id in assigned:
            blog_sources.update_pipeline(
                source_id, siteBuildStatus=PENDING, siteBuildJobId="", siteVerifyStatus=PENDING)
            _set_top_level(source_id, siteBuildJobId="", siteVerifyState=PENDING)
        _release_schedule(f"{type(exc).__name__}: {str(exc)[:600]}")
        logger.exception("blog site build start failed")
        return {
            "status": FAILED, "started": False, "articles": len(assigned),
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
        }

    _set_job_on_assigned(assigned, job_id, generation)
    _put_build(job_id, generation, len(assigned), actor)
    _control_to_building(generation, len(assigned), job_id)

    import blog_queue
    queued = blog_queue.enqueue_site_check(
        job_id, attempt=1, delay_seconds=CHECK_DELAY_SECONDS)
    if int(queued.get("queued") or 0) != 1:
        logger.error(json.dumps({
            "event": "blog_site_build_check_schedule_failed",
            "jobId": job_id, "generation": generation, "queue": queued,
        }))
        return _fail_build(
            job_id,
            "Amplify build started, but its completion check could not be queued")

    logger.info(json.dumps({
        "event": "blog_site_build_started", "jobId": job_id,
        "generation": generation, "articles": len(assigned),
    }))
    return {
        "status": BUILDING, "started": True, "jobId": job_id,
        "generation": generation, "articles": len(assigned), "checkQueue": queued,
    }


def _assigned_rows(generation: int, job_id: str) -> List[Dict[str, Any]]:
    out = []
    for row in _all_article_rows():
        if int(row.get("siteBuildGeneration") or 0) != int(generation):
            continue
        if str(row.get("siteBuildJobId") or "") != str(job_id):
            continue
        out.append(row)
    return out


def _reset_assigned(generation: int, job_id: str) -> None:
    for row in _assigned_rows(generation, job_id):
        source_id = str(row["id"])
        blog_sources.update_pipeline(
            source_id,
            siteBuildStatus=PENDING,
            siteBuildJobId="",
            siteVerifyStatus=PENDING,
            verifyStatus="SITE_BUILD_PENDING",
        )
        _set_top_level(source_id, siteBuildJobId="", siteVerifyState=PENDING)


def _fail_build(job_id: str, error: str) -> Dict[str, Any]:
    current = control()
    generation = int(current.get("buildGeneration") or current.get("generation") or 0)
    _reset_assigned(generation, job_id)
    _update_build(job_id, status=FAILED, error=error, completedAt=storage.now_iso())
    _release_schedule(error)
    logger.error(json.dumps({
        "event": "blog_site_build_failed", "jobId": job_id,
        "generation": generation, "error": error,
    }))
    return {"status": FAILED, "jobId": job_id, "error": error}


def check_build(job_id: str, attempt: int = 1) -> Dict[str, Any]:
    """Poll one Amplify build and fan out real-site checks once deployed."""
    wanted = str(job_id or "").strip()
    if not wanted:
        raise ValueError("jobId is required")
    current = control()
    if str(current.get("jobId") or "") != wanted:
        return {
            "status": str(current.get("status") or IDLE),
            "jobId": wanted, "checked": False,
            "note": "this is not the current site build",
        }

    try:
        response = amplify_client().get_job(
            appId=APP_ID, branchName=BRANCH_NAME, jobId=wanted)
        job = (response.get("job") or {})
        summary = job.get("summary") or {}
        status = str(summary.get("status") or "").upper()
    except Exception as exc:
        if attempt < MAX_BUILD_CHECKS:
            import blog_queue
            queued = blog_queue.enqueue_site_check(
                wanted, attempt=attempt + 1, delay_seconds=CHECK_DELAY_SECONDS)
            return {"status": BUILDING, "jobId": wanted, "attempt": attempt,
                    "readError": type(exc).__name__, "checkQueue": queued}
        return _fail_build(wanted, f"GetJob failed: {type(exc).__name__}")

    if status in {"PENDING", "PROVISIONING", "RUNNING"}:
        if attempt >= MAX_BUILD_CHECKS:
            return _fail_build(wanted, f"Amplify build still {status} after {attempt} checks")
        import blog_queue
        queued = blog_queue.enqueue_site_check(
            wanted, attempt=attempt + 1, delay_seconds=CHECK_DELAY_SECONDS)
        return {
            "status": BUILDING, "amplifyStatus": status, "jobId": wanted,
            "attempt": attempt, "checkQueue": queued,
        }

    if status != "SUCCEED":
        return _fail_build(wanted, f"Amplify job ended {status or 'UNKNOWN'}")

    generation = int(current.get("buildGeneration") or 0)
    rows = _assigned_rows(generation, wanted)
    deployed_at = storage.now_iso()
    for row in rows:
        source_id = str(row["id"])
        blog_sources.update_pipeline(
            source_id,
            siteBuildStatus=DEPLOYED,
            siteBuildJobId=wanted,
            siteBuildGeneration=generation,
            siteDeployedAt=deployed_at,
            siteVerifyStatus=PENDING,
            verifyStatus="SITE_DEPLOYED",
        )
        _set_top_level(source_id, siteVerifyState=PENDING)

    _update_build(wanted, status=VERIFYING, deployedAt=deployed_at)
    storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression=(
            "SET #s = :verifying, verifyRemaining = :n, verifyFailures = :zero, "
            "updatedAt = :u"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":verifying": VERIFYING, ":n": len(rows), ":zero": 0, ":u": deployed_at,
        },
    )

    if not rows:
        return _finish_generation(wanted)

    import blog_queue
    enqueue = blog_queue.enqueue_site_verify(
        [str(row["id"]) for row in rows], wanted, delay_seconds=0)
    failed_ids = [str(value) for value in (enqueue.get("failedSourceIds") or [])]
    for source_id in failed_ids:
        blog_sources.update_pipeline(
            source_id, siteVerifyStatus=FAILED, verifyStatus=FAILED)
        _set_top_level(source_id, siteVerifyState=FAILED)
    queued_count = int(enqueue.get("queued") or 0)
    storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression=(
            "SET verifyRemaining = :n, verifyFailures = :f, updatedAt = :u"
        ),
        ExpressionAttributeValues={
            ":n": queued_count, ":f": len(failed_ids), ":u": storage.now_iso(),
        },
    )
    if queued_count == 0:
        return _finish_generation(wanted)
    return {
        "status": VERIFYING, "jobId": wanted, "generation": generation,
        "deployed": len(rows), "verificationQueued": queued_count,
        "verificationQueueFailed": len(failed_ids),
    }


def _cache_busted(path: str, job_id: str) -> str:
    joiner = "&" if "?" in path else "?"
    return f"{PUBLIC_SITE_URL}{path}{joiner}{urlencode({'site_verify': job_id})}"


def _fetch_text(url: str) -> Tuple[int, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "WECARE.DIGITAL-Blog-Site-Verification/1.0",
            "Accept": "text/html,application/json,application/xml,text/xml,*/*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(MAX_HTTP_BYTES + 1)
            if len(body) > MAX_HTTP_BYTES:
                raise ValueError("public verification response exceeded the configured byte limit")
            return status, body.decode("utf-8", errors="replace")
    except HTTPError as exc:
        try:
            body = exc.read(MAX_HTTP_BYTES).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code or 0), body
    except URLError:
        raise


def _result(name: str, passed: bool, expected: str, found: str = "") -> Dict[str, Any]:
    return {
        "assertion": name,
        "result": "PASS" if passed else "FAIL",
        "expected": expected[:400],
        "found": found[:400],
    }


def verify_static_surfaces(source_id: str, job_id: str) -> Dict[str, Any]:
    """Read the actual static website and its generated discovery artifacts."""
    import blog_verify

    expected = blog_verify.expectation(source_id)
    slug = str(expected.get("slug") or "")
    title = str(expected.get("title") or "")
    canonical = f"{PUBLIC_SITE_URL}/post/{slug}/"
    paths = {
        "page": f"/post/{quote(slug)}/",
        "sitemap": "/sitemap.xml",
        "search": "/blog/search-index.json",
        "rss": "/blog/rss.xml",
    }
    fetched: Dict[str, Tuple[int, str]] = {}
    errors: Dict[str, str] = {}
    for name, path in paths.items():
        try:
            fetched[name] = _fetch_text(_cache_busted(path, job_id))
        except Exception as exc:  # noqa: BLE001
            fetched[name] = (0, "")
            errors[name] = type(exc).__name__

    page_status, page_body = fetched["page"]
    sitemap_status, sitemap = fetched["sitemap"]
    search_status, search = fetched["search"]
    rss_status, rss = fetched["rss"]
    canonical_no_slash = canonical.rstrip("/")

    search_has_slug = False
    if search_status == 200:
        try:
            payload = json.loads(search)
            search_has_slug = any(
                str(post.get("slug") or "") == slug
                for post in (payload.get("posts") or [])
                if isinstance(post, dict)
            )
        except (TypeError, ValueError):
            search_has_slug = False

    results = [
        _result("STATIC_POST_200", page_status == 200, "HTTP 200", str(page_status)),
        _result("STATIC_TITLE_PRESENT", title in page_body, title,
                "present" if title in page_body else "missing"),
        _result("STATIC_CANONICAL_PRESENT",
                canonical in page_body or canonical_no_slash in page_body,
                canonical, "present" if canonical in page_body or canonical_no_slash in page_body
                else "missing"),
        _result("SITEMAP_CONTAINS_POST",
                sitemap_status == 200 and (canonical in sitemap or canonical_no_slash in sitemap),
                canonical, f"HTTP {sitemap_status}"),
        _result("SEARCH_INDEX_CONTAINS_POST",
                search_status == 200 and search_has_slug,
                slug, f"HTTP {search_status}"),
        _result("RSS_CONTAINS_POST",
                rss_status == 200 and (canonical in rss or canonical_no_slash in rss),
                canonical, f"HTTP {rss_status}"),
    ]
    failed = [item["assertion"] for item in results if item["result"] == "FAIL"]
    return {
        "sourceId": source_id,
        "jobId": job_id,
        "slug": slug,
        "title": title,
        "canonical": canonical,
        "assertions": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "failedAssertions": failed,
        "fetchErrors": errors,
        "results": results,
        "verified": not failed,
    }


def _site_run_id() -> str:
    return "blogsitever_" + uuid.uuid4().hex


def _site_report_key(source_id: str, run_id: str) -> str:
    return blog_sources.work_key_for_id(
        source_id, f"site-verification/{source_id}/{run_id}.json")


def _store_site_report(source_id: str, job_id: str, actor: str,
                       report: Dict[str, Any], backend_run: Dict[str, Any],
                       status: str) -> Dict[str, Any]:
    run_id = _site_run_id()
    now = storage.now_iso()
    document = {
        "siteVerificationRunId": run_id,
        "sourceId": source_id,
        "jobId": job_id,
        "ranAt": now,
        "ranBy": actor,
        "status": status,
        "backendVerificationRunId": str(backend_run.get("verificationRunId") or ""),
        "backendStatus": str(backend_run.get("status") or ""),
        **report,
    }
    key = _site_report_key(source_id, run_id)
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET,
        Key=key,
        Body=json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    record = {
        "id": run_id,
        "recordType": VERIFY_RECORD_TYPE,
        "createdAt": now,
        "updatedAt": now,
        "slug": source_id,
        "sourceId": source_id,
        "batchId": str((blog_sources.get_source(source_id) or {}).get("batchId")
                       or blog_sources.NO_BATCH),
        "jobId": job_id,
        "bodyKey": key,
        "status": status,
        "backendVerificationRunId": str(backend_run.get("verificationRunId") or ""),
        "assertions": int(report.get("assertions") or 0),
        "passed": int(report.get("passed") or 0),
        "failed": int(report.get("failed") or 0),
        "failedAssertions": list(report.get("failedAssertions") or []),
        "ranBy": actor,
    }
    storage.put_record(record)
    return record


def _claim_site_verify(source_id: str, job_id: str) -> bool:
    try:
        storage.table().update_item(
            Key={"id": source_id},
            UpdateExpression="SET siteVerifyState = :working, updatedAt = :u",
            ExpressionAttributeValues={
                ":working": VERIFYING, ":pending": PENDING, ":u": storage.now_iso(),
            },
            ConditionExpression="siteVerifyState = :pending",
        )
        return True
    except ClientError as exc:
        if _conditional_failed(exc):
            return False
        raise


def _mark_final_verified(source_id: str, actor: str) -> None:
    record = blog_sources.get_source(source_id)
    if not record:
        return
    draft = dict(record.get("draftRecord") or {})
    draft["status"] = VERIFIED
    storage.table().update_item(
        Key={"id": source_id},
        UpdateExpression="SET draftRecord = :dr, articleStatus = :as, updatedAt = :u",
        ExpressionAttributeValues={
            ":dr": storage._clean(draft), ":as": VERIFIED, ":u": storage.now_iso(),
        },
    )
    try:
        import blog_article_work
        blog_article_work.set_intent_status(source_id, VERIFIED, actor)
        parent_id = str(record.get("parentSourceId") or "")
        if parent_id:
            blog_article_work.refresh_parent_status(parent_id, actor)
    except Exception:  # noqa: BLE001
        logger.exception("site verification article-work state sync failed")


def _complete_one(job_id: str, success: bool) -> Dict[str, Any]:
    response = storage.table().update_item(
        Key={"id": CONTROL_ID},
        UpdateExpression=(
            "SET verifyRemaining = verifyRemaining + :minus, "
            "verifyFailures = verifyFailures + :fail, updatedAt = :u"
        ),
        ExpressionAttributeValues={
            ":minus": -1, ":fail": 0 if success else 1, ":u": storage.now_iso(),
        },
        ReturnValues="ALL_NEW",
    )
    attrs = storage._json_safe(response.get("Attributes") or {})
    if int(attrs.get("verifyRemaining") or 0) <= 0:
        return _finish_generation(job_id)
    return {
        "status": VERIFYING,
        "remaining": int(attrs.get("verifyRemaining") or 0),
        "failures": int(attrs.get("verifyFailures") or 0),
    }


def verify_article(source_id: str, job_id: str, attempt: int = 1,
                   actor: str = "site-bridge") -> Dict[str, Any]:
    """Verify one post against the native store AND the rebuilt static website."""
    if not _claim_site_verify(source_id, job_id):
        record = blog_sources.get_source(source_id) or {}
        return {
            "sourceId": source_id,
            "jobId": job_id,
            "status": str(record.get("siteVerifyState") or "DUPLICATE"),
            "claimed": False,
        }

    import blog_verify
    backend = blog_verify.run(source_id, actor)
    site = verify_static_surfaces(source_id, job_id)
    backend_ok = str(backend.get("status") or "") == VERIFIED
    site_ok = bool(site.get("verified"))
    now = storage.now_iso()

    if backend_ok and not site_ok and attempt < MAX_SITE_VERIFY_ATTEMPTS:
        _set_top_level(source_id, siteVerifyState=PENDING)
        import blog_queue
        queued = blog_queue.enqueue_site_verify(
            [source_id], job_id, attempt=attempt + 1,
            delay_seconds=VERIFY_RETRY_DELAY_SECONDS)
        if int(queued.get("queued") or 0) == 1:
            logger.info(json.dumps({
                "event": "blog_site_verify_retry",
                "sourceId": source_id, "jobId": job_id, "attempt": attempt,
                "failedAssertions": site.get("failedAssertions") or [],
            }))
            return {
                "sourceId": source_id, "jobId": job_id, "status": "RETRYING",
                "attempt": attempt, "site": site, "queue": queued,
            }
        # There is no retry if the retry message itself did not enter SQS. Fall through and
        # record a terminal failure so verifyRemaining is decremented and the generation closes.
        site = {
            **site,
            "failedAssertions": list(site.get("failedAssertions") or [])
                                + ["SITE_VERIFY_RETRY_QUEUE"],
            "failed": int(site.get("failed") or 0) + 1,
            "verified": False,
        }

    success = backend_ok and site_ok
    status = VERIFIED if success else FAILED
    record = _store_site_report(source_id, job_id, actor, site, backend, status)
    blog_sources.update_pipeline(
        source_id,
        backendVerifyStatus=str(backend.get("status") or FAILED),
        backendVerifiedAt=now if backend_ok else "",
        siteBuildStatus=DEPLOYED,
        siteBuildJobId=job_id,
        siteVerifyStatus=status,
        siteVerifiedAt=now if site_ok else "",
        verifyStatus=status,
        verifiedAt=now if success else "",
    )
    _set_top_level(source_id, siteVerifyState=status)
    if success:
        _mark_final_verified(source_id, actor)

    bridge = _complete_one(job_id, success)
    logger.info(json.dumps({
        "event": "blog_site_verified" if success else "blog_site_verification_failed",
        "sourceId": source_id, "jobId": job_id,
        "backendStatus": backend.get("status", ""),
        "sitePassed": site.get("passed", 0),
        "siteFailed": site.get("failed", 0),
        "failedAssertions": site.get("failedAssertions") or [],
    }))
    return {
        "sourceId": source_id,
        "jobId": job_id,
        "status": status,
        "siteVerificationRunId": record["id"],
        "backendVerificationRunId": str(backend.get("verificationRunId") or ""),
        "site": site,
        "bridge": bridge,
    }


def _finish_generation(job_id: str) -> Dict[str, Any]:
    current = control()
    failures = int(current.get("verifyFailures") or 0)
    build_generation = int(current.get("buildGeneration") or 0)
    generation = int(current.get("generation") or 0)
    status = VERIFIED if failures == 0 else "PARTIAL_FAILED"
    now = storage.now_iso()
    _update_build(
        job_id,
        status=status,
        verifyFailures=failures,
        completedAt=now,
    )

    next_needed = generation > build_generation
    next_queued: Dict[str, Any] = {"queued": 0, "failed": 0, "configured": False}
    if next_needed:
        storage.table().update_item(
            Key={"id": CONTROL_ID},
            UpdateExpression=(
                "SET #s = :pending, jobId = :empty, articleCount = :zero, "
                "verifyRemaining = :zero, verifyFailures = :zero, updatedAt = :u, "
                "lastCompletedAt = :u, lastError = :e"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":pending": PENDING, ":empty": "", ":zero": 0, ":u": now, ":e": "",
            },
        )
        import blog_queue
        next_queued = blog_queue.enqueue_site_build(
            generation, "site-bridge", delay_seconds=COALESCE_DELAY_SECONDS)
    else:
        storage.table().update_item(
            Key={"id": CONTROL_ID},
            UpdateExpression=(
                "SET #s = :idle, jobId = :empty, articleCount = :zero, "
                "verifyRemaining = :zero, updatedAt = :u, lastCompletedAt = :u, lastError = :e"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":idle": IDLE, ":empty": "", ":zero": 0, ":u": now, ":e": "",
            },
        )

    return {
        "status": status,
        "jobId": job_id,
        "verifyFailures": failures,
        "generation": build_generation,
        "nextGenerationPending": next_needed,
        "nextQueue": next_queued,
    }


def get_build(reference: str) -> Optional[Dict[str, Any]]:
    key = str(reference or "").strip()
    if not key:
        return None
    return (
        storage.get_typed(key, BUILD_RECORD_TYPE)
        or storage.get_typed(_build_record_id(key), BUILD_RECORD_TYPE)
    )


def state() -> Dict[str, Any]:
    builds = storage.scan_by_record_type(BUILD_RECORD_TYPE, limit=20)
    builds.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    pending = _pending_rows()
    return {
        "configured": bool(APP_ID and BRANCH_NAME),
        "appId": APP_ID,
        "branch": BRANCH_NAME,
        "control": control(),
        "pendingArticles": len(pending),
        "pendingSourceIds": [str(row.get("id") or "") for row in pending[:50]],
        "recentBuilds": builds,
    }
