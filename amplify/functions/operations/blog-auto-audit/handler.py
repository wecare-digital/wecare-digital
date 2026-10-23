"""Scheduled protected-corpus blog audit and deterministic auto-remediation."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from boto3.dynamodb.conditions import Attr, Key

import rules

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("SEO_TOOLS_TABLE", "stack-wecare-digital-SeoToolsTable")
AUTO_APPLY = os.environ.get("BLOG_AUTO_APPLY", "true").strip().lower() == "true"
MAX_WRITES = max(0, min(int(os.environ.get("BLOG_AUTO_MAX_WRITES", "50")), 200))

_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(TABLE_NAME)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all_posts() -> List[Dict[str, Any]]:
    client = _dynamodb.meta.client
    paginator = client.get_paginator("query")
    posts: List[Dict[str, Any]] = []
    for page in paginator.paginate(
        TableName=TABLE_NAME,
        IndexName="recordType-createdAt-index",
        KeyConditionExpression="recordType = :record_type",
        ExpressionAttributeValues={":record_type": "blogPost"},
        ScanIndexForward=True,
    ):
        posts.extend(page.get("Items", []))
    return posts


def _integrity(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"Conversations": 0, "Gastronomy": 0}
    other = []
    slugs = set()
    duplicate_slugs = []
    author_failures = []

    for post in posts:
        category = str(post.get("category") or "")
        if category in counts:
            counts[category] += 1
        else:
            other.append({"id": post.get("id", ""), "slug": post.get("slug", ""), "category": category})

        slug = str(post.get("slug") or "")
        if slug:
            if slug in slugs:
                duplicate_slugs.append(slug)
            slugs.add(slug)

        if post.get("authorName") != rules.AUTHOR:
            author_failures.append({
                "id": str(post.get("id") or ""),
                "slug": slug,
                "authorName": str(post.get("authorName") or ""),
            })

    ok = (
        len(posts) == rules.PROTECTED_TOTAL
        and counts == rules.PROTECTED_COUNTS
        and not other
        and not duplicate_slugs
        and not author_failures
    )
    return {
        "ok": ok,
        "total": len(posts),
        "counts": counts,
        "otherCategories": other[:20],
        "duplicateSlugs": duplicate_slugs[:20],
        "authorFailures": author_failures[:50],
    }


def _conditional_update(post: Dict[str, Any], updates: Dict[str, Any]) -> None:
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {}
    sets = []
    condition = (
        Attr("id").eq(post["id"])
        & Attr("slug").eq(post.get("slug"))
        & Attr("authorName").eq(rules.AUTHOR)
        & Attr("publishedAt").eq(post.get("publishedAt"))
    )

    for index, (field, new_value) in enumerate(updates.items()):
        name_key = f"#f{index}"
        value_key = f":v{index}"
        names[name_key] = field
        values[value_key] = new_value
        sets.append(f"{name_key} = {value_key}")
        condition = condition & Attr(field).eq(post.get(field))

    _table.update_item(
        Key={"id": post["id"]},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression=condition,
    )


def _put_run(summary: Dict[str, Any]) -> None:
    created = summary["createdAt"]
    run_id = summary["runId"]
    _table.put_item(Item={
        "id": f"BLOG_AUTO_AUDIT#{created}#{run_id}",
        "recordType": "blogAutoAudit",
        "createdAt": created,
        "updatedAt": created,
        "slug": "__corpus__",
        **summary,
    })


def run(event: Dict[str, Any] | None = None, context: Any = None) -> Dict[str, Any]:
    event = event or {}
    started = time.time()
    run_id = getattr(context, "aws_request_id", "") or uuid.uuid4().hex
    created = now_iso()
    apply_requested = bool(event.get("apply", AUTO_APPLY))
    max_writes = max(0, min(int(event.get("maxWrites", MAX_WRITES)), 200))

    posts = _all_posts()
    before = _integrity(posts)

    summary: Dict[str, Any] = {
        "event": "blog_auto_audit_run",
        "runId": run_id,
        "createdAt": created,
        "mode": "APPLY" if apply_requested else "AUDIT_ONLY",
        "before": before,
        "safeCandidates": 0,
        "appliedPosts": 0,
        "appliedReplacements": 0,
        "conflicts": 0,
        "reviewCount": 0,
        "reviewItems": [],
        "touchedSlugs": [],
        "aborted": False,
    }

    # Hard stop: never write while the protected corpus or author identity is wrong.
    if not before["ok"]:
        summary["aborted"] = True
        summary["reason"] = "CORPUS_INTEGRITY_BLOCK"
        summary["durationMs"] = int((time.time() - started) * 1000)
        _put_run(summary)
        logger.error(json.dumps(summary, default=str))
        return summary

    for post in posts:
        updates, fields, replacements = rules.safe_patch(post)
        if updates:
            summary["safeCandidates"] += 1

        # Review against the would-be public result, so a safe replacement removes its own
        # finding before we decide what still needs a human.
        projected = rules.clone(post)
        projected.update(updates)
        findings = rules.review_findings(projected)
        if findings:
            summary["reviewCount"] += len(findings)
            if len(summary["reviewItems"]) < 100:
                summary["reviewItems"].append({
                    "slug": post.get("slug", ""),
                    "findings": findings[:10],
                })

        if not (apply_requested and updates):
            continue
        if summary["appliedPosts"] >= max_writes:
            continue
        try:
            _conditional_update(post, updates)
        except _table.meta.client.exceptions.ConditionalCheckFailedException:
            summary["conflicts"] += 1
            continue

        summary["appliedPosts"] += 1
        summary["appliedReplacements"] += replacements
        if len(summary["touchedSlugs"]) < 200:
            summary["touchedSlugs"].append(str(post.get("slug") or ""))

    after_posts = _all_posts()
    after = _integrity(after_posts)
    summary["after"] = after
    if not after["ok"]:
        # Identity/count changes are never an accepted outcome. The worker does not delete or
        # change identity fields, so this means something external changed concurrently.
        summary["aborted"] = True
        summary["reason"] = "POST_WRITE_INTEGRITY_BLOCK"

    summary["durationMs"] = int((time.time() - started) * 1000)
    _put_run(summary)
    logger.info(json.dumps(summary, default=str))
    return summary


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # This function has no public API integration. Every invocation is IAM-gated.
    return run(event, context)
