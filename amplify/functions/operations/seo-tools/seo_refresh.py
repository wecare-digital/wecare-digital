"""Scheduled derived-SEO refresh sweep (a content-change detector).

NAME. This module is `seo_refresh` rather than `seo_freshness` deliberately: a separate,
pre-existing `seo_freshness.py` in this package is the Bedrock-cost dedup for the AI SEO-audit
path (its `source_hash`/`decide`/`skip_log`). This one is the scheduled sweep that regenerates
DERIVED SEO records for blog posts whose content changed. Two different jobs, two names.

WHAT IT DOES. Reads the public blog corpus from `wix` (the source of truth, read-only), and for
each post asks `seo_engine.refresh` to recompute the derived SEO record IF its sourceHash
changed. An unchanged post is skipped with zero writes. That is the entire cost story: the job
reads a cached corpus and writes only the records that actually moved.

WHY A SCHEDULED CHECK RATHER THAN AN EVENT. Blog content is authored in Wix, outside this
system, so there is no reliable in-app event to hook. A low-frequency poll that skips unchanged
records (via sourceHash) is the cheap, correct pattern the brief describes, and it never becomes
a constant poller: it runs on an EventBridge schedule (daily by default) and does bounded work.

HOW IT IS INVOKED. Not by a public HTTP route. The handler recognises a scheduler event by its
shape - a top-level `seoFreshness: True` and no `requestContext` - the same IAM-gated,
not-reachable-from-the-API pattern the blog worker uses. An EventBridge Scheduler target invokes
the function with that payload.

COST MODE. In FREE mode the job still runs (it is deterministic and nearly free), but it will
not perform any AI-derived enrichment. The refresh itself is deterministic regardless.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

import blog_source
import seo_config
import seo_engine

logger = logging.getLogger(__name__)

#: A safety ceiling on records touched per invocation, so a one-off corpus-wide change cannot
#: turn a single scheduled run into thousands of writes in one burst. Unchanged records cost
#: nothing, so this only bounds the CHANGED set; the remainder is picked up on the next run.
_DEFAULT_MAX_REFRESH = 500


def is_freshness_event(event: Dict[str, Any]) -> bool:
    """True for the scheduler payload, and only that.

    Mirrors the blog-worker guard in the handler: a top-level marker AND the absence of a
    requestContext. An API Gateway request always carries a requestContext and delivers its
    payload as a JSON string under `body`, so it can never produce this top-level key. Reaching
    this branch therefore requires lambda:InvokeFunction, which is IAM-gated.
    """
    return bool(event.get("seoFreshness")) and not event.get("requestContext")


def run(event: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Refresh derived SEO for the blog corpus, skipping unchanged posts.

    Returns a summary suitable for a CloudWatch log line. Never raises for a single bad post -
    a malformed record is counted and skipped so one row cannot stall the whole sweep - but a
    total failure to read the corpus propagates, because a sweep that silently processed nothing
    is worse than a visible failure.
    """
    event = event or {}
    started = time.time()
    max_refresh = int(event.get("maxRefresh") or _DEFAULT_MAX_REFRESH)
    force = bool(event.get("force"))

    posts = blog_source.list_blog_posts()  # AWS-native (SeoToolsTable); read-only; raises if the store is down

    refreshed = 0
    skipped = 0
    errors = 0
    touched: List[str] = []
    for post in posts:
        if refreshed >= max_refresh:
            # Stop refreshing NEW work but keep counting the rest as skipped, so the summary
            # reflects the true remaining backlog rather than pretending the corpus is shorter.
            skipped += 1
            continue
        slug = str(post.get("slug") or "").strip()
        if not slug:
            errors += 1
            continue
        try:
            result = seo_engine.refresh(seo_engine.ENTITY_BLOG, post, actor="scheduler",
                                        force=force)
        except Exception:  # noqa: BLE001 - one bad post must not stall the sweep
            logger.exception("seo freshness refresh failed for slug=%s", slug)
            errors += 1
            continue
        if result.get("skipped"):
            skipped += 1
        else:
            refreshed += 1
            if len(touched) < 200:
                touched.append(slug)

    summary = {
        "event": "seo_freshness_run",
        "posts": len(posts),
        "refreshed": refreshed,
        "skipped": skipped,
        "errors": errors,
        "forced": force,
        "durationMs": int((time.time() - started) * 1000),
        "config": seo_config.snapshot(),
    }
    logger.info(json.dumps(summary))
    # `touched` is returned for callers/tests but kept out of the standing log line to bound its
    # size. Slugs are not secret, so including them is a size decision, not a privacy one.
    return {**summary, "touchedSlugs": touched}
