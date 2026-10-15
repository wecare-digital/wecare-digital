#!/usr/bin/env python3
"""Conversations batch runner: validate a manifest, audit what went live.

WHAT IT CHECKS AGAINST. The AWS-native blog: posts are `blogPost` records in SeoToolsTable,
served by `wecare-seo-tools` and rendered from Markdown by the post page.
`blog_native_contract` holds that contract - slug rules, body size, the Markdown the
renderer can display, the public read route - so this runner and the Gastronomy one apply
the same definition.

WHY THERE IS NO PUBLISH MODE. Publication belongs to Blog Studio: an operator releases a
signed-off article and `wecare-seo-tools` performs the native write (`blog_publish.release`
then `blog_publish.publish`), re-checking the sign-off and the body hash at publish time.
Those are Admin-authenticated routes with their own human gates. A writer here would be a
second route to the same store that skips both, so this runner reports the queue and
audits the result, and writes no post.

THE HUMAN GATE. Only records whose eleven `gate` answers a human has recorded reach
READY_TO_PUBLISH, and `blog_quality_v2.decide_status` will not award that status to a
record no human signed. `validate` reports that queue; this module never writes a `gate`
value and never overrides a status.

MANIFEST SIZE IS ARBITRARY. There is no editorial batch size, unlike Gastronomy's
contiguous 25. A manifest may hold one record or two thousand.

Usage:
    python scripts/conversations_batch.py validate --manifest content/conversations/batches/CONV-001.json
    python scripts/conversations_batch.py audit    --manifest <file> [--published-since <iso>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

#: None of these imports pulls in boto3, so `validate` runs in a job with no AWS role and
#: no AWS SDK. The audit's Lambda client is created inside `blog_native_contract`.
import blog_ledger  # noqa: E402
import blog_native_contract as native  # noqa: E402
import blog_quality_v2 as quality  # noqa: E402

CATEGORY = quality.DEFAULT_CATEGORY
AUTHOR = quality.AUTHOR
LEDGER_PATH = blog_ledger.DEFAULT_LEDGER

#: The read-back uses the same unauthenticated, published-only route the site build reads,
#: so auditing needs permission to invoke this one function and nothing else.
AUDIT_FUNCTION = os.environ.get("CONVERSATIONS_AUDIT_FUNCTION", native.PUBLIC_FUNCTION)
AUDIT_REGION = os.environ.get("AWS_REGION", native.PUBLIC_REGION)

MIN_PUBLISHED_CHARS = 400

#: How close the live body must be to the record's. The threshold `blog_verify` applies to
#: the same comparison: storing and serving can normalise a quote or a double space, and an
#: overlap this high still cannot hide a missing paragraph.
BODY_SIMILARITY_MIN = 0.97
#: Below this the live text is not an edited copy of the record's body at all.
WRONG_BODY_MAX = 0.5

IMAGE_FIELDS = ("heroImage", "media", "coverImage", "image")


# ── loading ─────────────────────────────────────────────────────────────────────

def load_document(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"posts": data}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a JSON object or array")
    return data


def manifest_posts(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    posts = document.get("posts") if isinstance(document, dict) else document
    if not isinstance(posts, list):
        raise ValueError("manifest must carry a posts array")
    return [post for post in posts if isinstance(post, dict)]


def build_corpus(manifest_path: Optional[Path]) -> quality.CorpusIndex:
    """The section 28 corpus, with the manifest under test excluded from itself.

    Without the exclusion every committed record reports an exact slug collision with its
    own committed copy, which is how a duplication gate ends up being switched off.
    """
    target = Path(manifest_path).resolve() if manifest_path else None
    patterns = [p for p in quality.DEFAULT_CORPUS
                if not (manifest_path and str(manifest_path) in p)]
    corpus = quality._build_corpus(patterns, published=True)
    if target is not None:
        corpus.entries = [entry for entry in corpus.entries
                          if Path(entry.origin or ".").resolve() != target]
        corpus._by_slug = {entry.slug: entry
                           for entry in reversed(corpus.entries) if entry.slug}
    return corpus


# ── the native record contract ──────────────────────────────────────────────────

def canonical_url(slug: str) -> str:
    return native.canonical_url(slug)


def payload_errors(record: Dict[str, Any]) -> List[str]:
    """Whether the native store and renderer can take this record as written.

    The v2 gate judges whether a record is fit to publish. This judges whether it would go
    live intact, which is a different question with different failure text - a slug the
    store would rewrite, or a body line the renderer would show as raw Markdown.
    """
    slug = str(record.get("slug") or "").strip()
    prefix = slug or str(record.get("title") or "<untitled>")
    errors: List[str] = [f"{prefix}: {problem}" for problem in native.slug_errors(slug)]

    if not str(record.get("title") or "").strip():
        errors.append(f"{prefix}: title is required")
    if not quality.text_field(record, "seoTitle"):
        errors.append(f"{prefix}: seoTitle is required")
    if not quality.text_field(record, "metaDescription"):
        errors.append(f"{prefix}: metaDescription is required")

    category = str(record.get("category") or "").strip()
    if category and category != CATEGORY:
        errors.append(f"{prefix}: category must be {CATEGORY!r}, got {category!r}")
    author = quality.text_field(record, "author")
    if author and author != AUTHOR:
        errors.append(f"{prefix}: author must be {AUTHOR!r}, got {author!r}")

    tags = quality.field(record, "tags") or []
    if not isinstance(tags, list) or not 1 <= len(tags) <= 3:
        errors.append(f"{prefix}: tags must be a list of 1-3 labels")

    canonical = str(record.get("canonical") or "").strip()
    if slug and canonical and canonical != canonical_url(slug):
        errors.append(f"{prefix}: canonical must be {canonical_url(slug)}, got {canonical}")

    for key in IMAGE_FIELDS:
        if record.get(key):
            errors.append(f"{prefix}: {key} is forbidden; the blog is image-free")

    errors.extend(f"{prefix}: {problem}"
                  for problem in native.body_errors(quality.body_of(record)))
    return errors


# ── the ledger ──────────────────────────────────────────────────────────────────

def ledger_row(ledger: "blog_ledger.Ledger", record: Dict[str, Any]):
    """The row for a record: by sourceId first, then by slug.

    sourceId is the durable identity - it is the hash of the source bytes - so it is tried
    first. Slug is the fallback for a record predating the ledger.
    """
    source_id = str(record.get("sourceId") or "").strip()
    if source_id:
        row = ledger.resolve(source_id)
        if row is not None:
            return row
    slug = str(record.get("slug") or "").strip()
    return ledger.by_slug(slug) if slug else None


def ledger_errors(ledger: "blog_ledger.Ledger",
                  records: Sequence[Dict[str, Any]]) -> List[str]:
    """Records with no ledger row. Their provenance is unrecorded and VERIFIED cannot be
    checkpointed against anything, so publishing one would lose the link permanently."""
    problems: List[str] = []
    for record in records:
        if ledger_row(ledger, record) is None:
            slug = str(record.get("slug") or "<no slug>")
            problems.append(f"{slug}: no ledger row; run blog_ingest so its source "
                            "provenance is recorded before publishing")
    return problems


# ── validate ────────────────────────────────────────────────────────────────────

def validate_document(document: Dict[str, Any], *, manifest_path: Optional[Path] = None,
                      ledger_path: Path = LEDGER_PATH) -> Dict[str, Any]:
    """The full entry gate: v2 standard, native record contract, ledger provenance.

    Returns a report rather than raising, so the CLI can print every problem in one pass.
    """
    posts = manifest_posts(document)
    corpus = build_corpus(manifest_path)
    wave = quality.assess_wave(posts, corpus)
    queue = set(quality.publish_queue(wave))

    errors: List[str] = []
    if not posts:
        errors.append("manifest holds no posts")

    slugs: Dict[str, int] = {}
    for post in posts:
        slug = str(post.get("slug") or "").strip()
        if slug:
            slugs[slug] = slugs.get(slug, 0) + 1
    for slug, count in sorted(slugs.items()):
        if count > 1:
            errors.append(f"{slug}: appears {count} times in this manifest")

    for post in posts:
        errors.extend(payload_errors(post))

    for record in wave["records"]:
        for line in record["blocking"]:
            errors.append(f"{record['slug'] or '<no slug>'}: {line}")

    ledger = blog_ledger.Ledger.load(ledger_path)
    publishable = [post for post in posts
                   if str(post.get("slug") or "").strip() in queue]
    if ledger.rows:
        errors.extend(ledger_errors(ledger, publishable))

    return {
        "manifest": str(manifest_path or ""),
        "total": len(posts),
        "readyToPublish": sorted(queue),
        "byStatus": wave["byStatus"],
        "blocked": wave["blocked"],
        "publishedIndex": quality.published_index_health(),
        "errors": errors,
    }


# ── audit ───────────────────────────────────────────────────────────────────────

def fetch_public_post(slug: str) -> Dict[str, Any]:
    """One published post, read through the public route of `wecare-seo-tools`."""
    return native.fetch_public_post(slug, function=AUDIT_FUNCTION, region=AUDIT_REGION)


def list_public_posts() -> List[Dict[str, Any]]:
    """Slug and title of every published post, for the duplicate and presence checks."""
    return native.list_public_posts(("slug", "title"), function=AUDIT_FUNCTION,
                                    region=AUDIT_REGION)


def parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def body_similarity(expected_body: str, live_body: str) -> float:
    """Shingle overlap with Markdown stripped, via the same sketch the duplication gate uses."""
    if not str(expected_body or "").strip() or not str(live_body or "").strip():
        return 0.0
    return quality.sketch_jaccard(quality.sketch(expected_body), quality.sketch(live_body))


def audit_post(public: Dict[str, Any], expected: Dict[str, Any], *,
               live_slug_counts: Optional[Dict[str, int]] = None,
               live_title_counts: Optional[Dict[str, int]] = None,
               published_since: Optional[datetime] = None,
               now: Optional[datetime] = None) -> List[str]:
    """Compare one live post against the record that produced it.

    Pure: every input is plain data, so the whole audit is testable without touching Lambda.
    """
    slug = str(expected.get("slug") or "").strip()
    errors: List[str] = []
    now = now or datetime.now(timezone.utc)

    def fail(message: str) -> None:
        errors.append(f"{slug or '<no slug>'}: {message}")

    if not public:
        fail("not found on the live site")
        return errors

    if str(public.get("slug") or "") != slug:
        fail(f"slug is {public.get('slug')!r}, expected {slug!r}")
    if str(public.get("title") or "") != str(expected.get("title") or "").strip():
        fail(f"title is {public.get('title')!r}, expected "
             f"{str(expected.get('title') or '').strip()!r}")

    #: The native store keeps `authorName` on each post and the public view returns that
    #: stored value, so this field is evidence of the attribution rather than a default.
    if str(public.get("authorName") or "") != AUTHOR:
        fail(f"authorName is {public.get('authorName')!r}, expected {AUTHOR!r}")
    if str(public.get("category") or "") != CATEGORY:
        fail(f"category is {public.get('category')!r}, expected {CATEGORY!r}")

    #: Compared without case. The standard already treats tag identity that way (its
    #: TAG_DUPLICATE check folds case), and posts migrated into the native store kept the
    #: casing of a label that already existed, so `Change` against `change` is the same tag.
    want_tags = [str(tag).strip() for tag in (quality.field(expected, "tags") or [])
                 if str(tag).strip()]
    got_tags = [str(tag).strip() for tag in (public.get("tags") or []) if str(tag).strip()]
    if sorted(t.casefold() for t in got_tags) != sorted(t.casefold() for t in want_tags):
        fail(f"tags are {got_tags}, expected {want_tags}")

    want_seo_title = quality.text_field(expected, "seoTitle")
    if str(public.get("seoTitle") or "").strip() != want_seo_title:
        fail(f"seoTitle is {public.get('seoTitle')!r}, expected {want_seo_title!r}")
    want_meta = quality.text_field(expected, "metaDescription")
    if str(public.get("metaDescription") or "").strip() != want_meta:
        fail(f"metaDescription is {public.get('metaDescription')!r}, "
             f"expected {want_meta!r}")

    url = str(public.get("url") or "").strip()
    if not native.same_url(url, canonical_url(slug)):
        fail(f"public URL is {url!r}, expected {canonical_url(slug)!r}")
    canonical = str(expected.get("canonical") or "").strip()
    if canonical and not native.same_url(canonical, url):
        fail(f"record canonical {canonical!r} does not match the live URL {url!r}")
    if str(public.get("coverImage") or "").strip():
        fail("coverImage is set on the live post; the blog is image-free")

    published_at = parse_iso(public.get("publishedDate"))
    if published_at is None:
        fail(f"publishedDate {public.get('publishedDate')!r} is missing or unparseable")
    else:
        if published_at > now + timedelta(minutes=5):
            fail(f"publishedDate {published_at.isoformat()} is in the future")
        if published_since and published_at < published_since:
            fail(f"publishedDate {published_at.isoformat()} predates this run "
                 f"({published_since.isoformat()}); the post was not freshly published")
        #: THE DATE THAT MUST NOT BE REUSED. A reconstructed article is published at the
        #: moment it goes live; a live date at or before the source's own date means the
        #: archive date was carried onto the public post.
        source_date = parse_iso(quality.field(expected, "originalSourceDate")
                                or quality.field(expected, "originalPublishedDate"))
        if source_date and published_at <= source_date:
            fail(f"publishedDate {published_at.isoformat()} is not newer than the "
                 f"source's own date {source_date.isoformat()}")

    #: The native view serves the stored Markdown as `content`, which is exactly what the
    #: post page renders, so the body is judged by the same contract `validate` applies.
    content = str(public.get("content") or public.get("contentText") or "")
    if not content.strip():
        fail("published body is empty")
    else:
        for problem in native.body_errors(content):
            fail(f"published body: {problem}")
        shown = native.rendered_text(content)
        if len(shown) < MIN_PUBLISHED_CHARS:
            fail(f"published body is {len(shown)} chars, expected at least "
                 f"{MIN_PUBLISHED_CHARS}")
        similarity = body_similarity(quality.body_of(expected), content)
        if similarity < WRONG_BODY_MAX:
            fail(f"the published body matches this record's body at {similarity:.2f}; "
                 "the wrong content is live under this slug")
        elif similarity < BODY_SIMILARITY_MIN:
            fail(f"the published body matches this record's body at {similarity:.2f}, "
                 f"below {BODY_SIMILARITY_MIN}; it has drifted from the approved text")

    if live_slug_counts is not None and live_slug_counts.get(slug, 0) > 1:
        fail(f"{live_slug_counts[slug]} live posts share this slug")
    if live_title_counts is not None:
        title = str(expected.get("title") or "").strip()
        if title and live_title_counts.get(title, 0) > 1:
            fail(f"{live_title_counts[title]} live posts share the title {title!r}")
    return errors


def audit_document(document: Dict[str, Any], *, manifest_path: Optional[Path] = None,
                   ledger_path: Path = LEDGER_PATH,
                   published_since: Optional[datetime] = None) -> Dict[str, Any]:
    """Read every published record in this manifest back off the live site.

    Presence comes from the public listing, which holds published posts only. A record that
    is not live yet - still behind the human gate or not yet released - is reported as
    not-yet-published rather than as a failure, because that is the system working.
    """
    posts = manifest_posts(document)
    live_slug_counts: Dict[str, int] = {}
    live_title_counts: Dict[str, int] = {}
    for post in list_public_posts():
        slug = str(post.get("slug") or "")
        live_slug_counts[slug] = live_slug_counts.get(slug, 0) + 1
        title = str(post.get("title") or "").strip()
        if title:
            live_title_counts[title] = live_title_counts.get(title, 0) + 1

    ledger = blog_ledger.Ledger.load(ledger_path)
    errors: List[str] = []
    verified: List[str] = []
    absent: List[str] = []

    for record in posts:
        slug = str(record.get("slug") or "").strip()
        if not slug:
            errors.append("<no slug>: record cannot be audited without a slug")
            continue
        if slug not in live_slug_counts:
            absent.append(slug)
            continue
        try:
            public = fetch_public_post(slug)
        except RuntimeError as exc:
            errors.append(f"{slug}: read-back failed ({exc})")
            continue
        problems = audit_post(public, record,
                              live_slug_counts=live_slug_counts,
                              live_title_counts=live_title_counts,
                              published_since=published_since)
        if problems:
            errors.extend(problems)
            continue
        verified.append(slug)
        row = ledger_row(ledger, record)
        if row is not None:
            ledger.update(row.sourceId, status="VERIFIED",
                          verifiedAt=blog_ledger.now_iso(),
                          publishedAt=row.publishedAt or str(public.get("publishedDate")
                                                             or blog_ledger.now_iso()))

    if verified and ledger.rows:
        ledger.path = Path(ledger_path)
        ledger.save()

    return {
        "manifest": str(manifest_path or ""),
        "total": len(posts),
        "verified": verified,
        "notPublished": absent,
        "errors": errors,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────────

def _print_report(title: str, report: Dict[str, Any]) -> None:
    print(f"{title}: {report.get('manifest') or '<manifest>'}")
    for key in ("total", "blocked"):
        if key in report:
            print(f"  {key:<16} {report[key]}")
    if "readyToPublish" in report:
        print(f"  {'readyToPublish':<16} {len(report['readyToPublish'])}")
    if report.get("byStatus"):
        print(f"  {'byStatus':<16} {report['byStatus']}")
    if report.get("verified"):
        print(f"  {'verified':<16} {len(report['verified'])}")
    if report.get("notPublished"):
        print(f"  {'notPublished':<16} {len(report['notPublished'])}")
    health = report.get("publishedIndex")
    if health:
        if health.get("present"):
            print(f"  published corpus index: {health['indexed']} posts"
                  + (f"  ⚠ {health['note']}" if health.get("note") else ""))
        else:
            print(f"  ⚠ NO PUBLISHED CORPUS INDEX — {health.get('note')}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Conversations batch runner: validate and audit (publication happens "
                    "in Blog Studio)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "audit"):
        node = sub.add_parser(name)
        node.add_argument("--manifest", required=True, type=Path)
        node.add_argument("--ledger", type=Path, default=LEDGER_PATH)
        node.add_argument("--json", action="store_true")
    sub.choices["audit"].add_argument(
        "--published-since", default="",
        help="ISO timestamp; a post published before it fails the freshness check")

    args = parser.parse_args(argv)
    document = load_document(args.manifest)

    if args.command == "validate":
        report = validate_document(document, manifest_path=args.manifest,
                                   ledger_path=args.ledger)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_report("validate", report)
            for line in report["errors"]:
                print(f"  ✗ {line}")
        return 1 if report["errors"] else 0

    since = parse_iso(args.published_since) if args.published_since else None
    if args.published_since and since is None:
        print(f"--published-since {args.published_since!r} is not an ISO timestamp",
              file=sys.stderr)
        return 2
    report = audit_document(document, manifest_path=args.manifest,
                            ledger_path=args.ledger, published_since=since)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report("audit", report)
        for slug in report["notPublished"]:
            print(f"  · {slug} not published yet")
        for line in report["errors"]:
            print(f"  ✗ {line}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
