"""Deterministic derived-SEO engine.

WHAT THIS IS. Given a SOURCE record (a public blog post as `storage.get_blog_post` returns it,
or a static page descriptor), this computes a DERIVED SEO record - title, meta description,
canonical, robots, OpenGraph and JSON-LD - and stores it in `SeoToolsTable` under
`recordType='seo'`. It reads source content and writes only derived records. It calls no model
by default.

THE ONE RULE THIS MODULE ENFORCES, in code and in tests: the source is READ ONLY. Nothing here
mutates the post/page it is handed, and the only item it writes is its own derived record,
keyed `seo_<entityType>_<slug>` with `recordType='seo'`. Deleting or rewriting that item cannot
touch the source: a blog post is a separate `blogPost` record written by the blog admin and
publish paths, never by this module, and page content is in-repo TSX.

CHANGE DETECTION. A `sourceHash` is computed from the fields that actually affect SEO output.
If the stored derived record already carries that hash, refresh is a no-op: no write, no model
call, nothing. That is the whole cost-control mechanism the brief asks for, and
`test_seo_engine_idempotent` pins it.

AI. This module is deterministic. `seo_config.ai_enabled()` gates whether an optional
model-derived suggestion may be ADDED (to a separate suggestion field), and when AI is off or
fails, the deterministic result is what ships. A model is never required to produce a record.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import seo_config
import storage

logger = logging.getLogger(__name__)

#: The record type for every derived SEO item. A separate partition from `blogPost`, `audit`,
#: `log` and the blog-production types, so a query for derived SEO never sees a source record
#: and vice versa.
SEO_RECORD_TYPE = "seo"

#: Entity types this engine understands. Kept small and explicit; an unknown type is refused
#: rather than guessed, because emitting the wrong schema.org @type is worse than emitting none.
ENTITY_BLOG = "blog"
ENTITY_PAGE = "page"
_ENTITY_TYPES = (ENTITY_BLOG, ENTITY_PAGE)

_BRAND = "WECARE.DIGITAL"
_SITE_URL = storage.PUBLIC_SITE_URL  # 'https://wecare.digital', already trailing-slash-free
_DEFAULT_ROBOTS = "index, follow, max-image-preview:large"

#: Meta description target window. Google truncates around 160 characters; below ~50 it reads
#: as thin. These bound the DERIVED fallback only - a source-provided description is used
#: verbatim regardless of length, because the source is authoritative and we do not edit it.
_META_MIN = 50
_META_MAX = 160
_TITLE_MAX = 60


def _text(value: Any) -> str:
    return str(value or "").strip()


def _record_id(entity_type: str, slug: str) -> str:
    """Deterministic id, so a refresh overwrites the same item instead of accumulating copies.

    Slug is normalised to the same shape the public URL uses. The id is not a secret and not a
    phone number; it is a correlation key and may be logged in full.
    """
    clean = slug.strip().strip("/")
    return f"seo_{entity_type}_{clean}"


# --------------------------------------------------------------------------- #
# sourceHash
# --------------------------------------------------------------------------- #

def source_hash(source: Dict[str, Any]) -> str:
    """A stable sha256 over the source fields that affect SEO output, and nothing else.

    WHY THESE FIELDS. The derived record must change exactly when something a crawler would see
    changes: the title, the body-derived excerpt, the category, the author, the cover image, the
    modification date, and any SEO overrides the source itself carries. A change to an unrelated
    field (an internal tag, a view count) must NOT invalidate the derived record, or the skip
    logic stops saving anything.

    Serialised as sorted JSON so key order and whitespace cannot produce a different hash for
    identical content - the same discipline `blog_gate.body_sha256` uses.
    """
    material = {
        "title": _text(source.get("title")),
        "excerpt": _text(source.get("excerpt")),
        "category": _text(source.get("category")),
        "authorName": _text(source.get("authorName")),
        "coverImage": _text(source.get("coverImage")),
        "modifiedDate": _text(source.get("modifiedDate")),
        "publishedDate": _text(source.get("publishedDate")),
        # Source-authored SEO overrides. If the author set these on the post, they are part of the
        # input and a change to them must re-derive.
        "seoTitle": _text(source.get("seoTitle")),
        "metaDescription": _text(source.get("metaDescription")),
        "focusKeyword": _text(source.get("focusKeyword")),
        "robots": _text(source.get("robots")),
        "keywords": [_text(k) for k in (source.get("keywords") or [])],
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# deterministic derivation
# --------------------------------------------------------------------------- #

def _canonical(entity_type: str, source: Dict[str, Any]) -> str:
    """The canonical URL. Prefer the source's own url; otherwise compose from the slug.

    Composed to match the live routes exactly: blog posts live at /post/<slug>/, static pages
    at /<slug>/. We never invent a different canonical than the page actually serves - a
    mismatch is the "Duplicate, Google chose a different canonical" failure the sitemap header
    warns about.
    """
    url = _text(source.get("url"))
    if url:
        return url
    slug = _text(source.get("slug")).strip("/")
    if entity_type == ENTITY_BLOG:
        return f"{_SITE_URL}/post/{slug}/"
    return f"{_SITE_URL}/{slug}/" if slug else f"{_SITE_URL}/"


def _seo_title(source: Dict[str, Any]) -> str:
    """Title | Brand, unless the source already carries a seoTitle, which is used verbatim.

    The deterministic template is the brief's own example. A source seoTitle is authoritative
    and never rewritten - this is the "use existing meta title if present" rule.
    """
    existing = _text(source.get("seoTitle"))
    if existing:
        return existing
    title = _text(source.get("title"))
    if not title:
        return _BRAND
    suffix = f" | {_BRAND}"
    # Keep the brand suffix but do not let the whole thing balloon; trim the title part only.
    if len(title) + len(suffix) <= _TITLE_MAX + len(suffix):
        return f"{title}{suffix}"
    return f"{title[:_TITLE_MAX].rstrip()}{suffix}"


def _meta_description(source: Dict[str, Any]) -> str:
    """A source metaDescription verbatim; else the excerpt; else a trimmed body-derived summary.

    Never fabricated beyond trimming existing safe text. If nothing usable exists we return the
    excerpt as-is even if short - an honest short description beats an invented one.
    """
    existing = _text(source.get("metaDescription"))
    if existing:
        return existing
    excerpt = _text(source.get("excerpt"))
    if not excerpt:
        return ""
    if len(excerpt) <= _META_MAX:
        return excerpt
    # Trim on a word boundary within the window rather than mid-word.
    window = excerpt[:_META_MAX]
    cut = window.rsplit(" ", 1)[0] if " " in window else window
    return f"{cut.rstrip('.,;:')}\u2026"  # ellipsis


def _robots(source: Dict[str, Any]) -> str:
    return _text(source.get("robots")) or _DEFAULT_ROBOTS


def _open_graph(entity_type: str, source: Dict[str, Any], canonical: str, title: str,
                description: str) -> Dict[str, str]:
    og = {
        "og:type": "article" if entity_type == ENTITY_BLOG else "website",
        "og:title": title,
        "og:description": description,
        "og:url": canonical,
        "og:site_name": _BRAND,
        "og:locale": "en_IN",
    }
    image = _text(source.get("coverImage"))
    if image:
        og["og:image"] = image
    return og


def _json_ld(entity_type: str, source: Dict[str, Any], canonical: str, title: str,
             description: str) -> List[Dict[str, Any]]:
    """JSON-LD built ONLY from verified source fields. An unsupported property is omitted, never
    invented - the brief is explicit that the structured data must match the page, not the other
    way around.

    BreadcrumbList is always safe (Home > section > this page). For a blog post we add a
    BlogPosting, but only the properties the source actually supports: no author node unless an
    author name exists, no dates unless the source has them.
    """
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "@id": f"{canonical}#breadcrumb",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{_SITE_URL}/"},
        ],
    }
    if entity_type == ENTITY_BLOG:
        breadcrumb["itemListElement"].append(
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": f"{_SITE_URL}/blog/"})
        breadcrumb["itemListElement"].append(
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical})
        article: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "@id": f"{canonical}#article",
            "headline": title,
            "url": canonical,
            "inLanguage": "en-IN",
            "publisher": {"@id": f"{_SITE_URL}/#organization"},
        }
        if description:
            article["description"] = description
        published = _text(source.get("publishedDate"))
        modified = _text(source.get("modifiedDate")) or published
        if published:
            article["datePublished"] = published
        if modified:
            article["dateModified"] = modified
        author = _text(source.get("authorName"))
        if author:
            article["author"] = {"@type": "Organization", "name": author}
        image = _text(source.get("coverImage"))
        if image:
            article["image"] = image
        return [article, breadcrumb]
    # Static page.
    breadcrumb["itemListElement"].append(
        {"@type": "ListItem", "position": 2, "name": title, "item": canonical})
    return [breadcrumb]


def derive(entity_type: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """The deterministic derived-SEO payload for one source. Pure: no I/O, no mutation of
    `source`, no model call. Returns a NEW dict.
    """
    if entity_type not in _ENTITY_TYPES:
        raise ValueError(f"Unknown SEO entity type: {entity_type!r}")
    slug = _text(source.get("slug"))
    if not slug and entity_type == ENTITY_BLOG:
        raise ValueError("a blog source must carry a slug")
    canonical = _canonical(entity_type, source)
    title = _seo_title(source)
    description = _meta_description(source)
    robots = _robots(source)
    return {
        "seoTitle": title,
        "metaDescription": description,
        "canonicalUrl": canonical,
        "robotsDirective": robots,
        "openGraphData": _open_graph(entity_type, source, canonical, title, description),
        "structuredData": _json_ld(entity_type, source, canonical, title, description),
        # FAQ suggestions are DERIVED and SEPARATE. Deterministic mode never fabricates them;
        # they arrive only through the optional AI path, into their own record type. Empty here.
        "faqSuggestions": [],
        "generator": "deterministic",
    }


# --------------------------------------------------------------------------- #
# store, with sourceHash skip
# --------------------------------------------------------------------------- #

def get_derived(entity_type: str, slug: str) -> Optional[Dict[str, Any]]:
    """The stored derived record for one entity, or None. Read-only."""
    return storage.get_typed(_record_id(entity_type, slug), SEO_RECORD_TYPE)


def refresh(entity_type: str, source: Dict[str, Any], *, actor: str = "system",
            force: bool = False) -> Dict[str, Any]:
    """Recompute and store the derived SEO record for one source IF its sourceHash changed.

    Returns a small result dict describing what happened. This is the idempotent unit the
    freshness check calls once per source.

    NEVER writes to `source`. NEVER writes outside `recordType='seo'`. When the hash is
    unchanged and `force` is false, it performs ZERO writes and returns skipped=True - which is
    what keeps a re-run of an unchanged corpus free.
    """
    if entity_type not in _ENTITY_TYPES:
        raise ValueError(f"Unknown SEO entity type: {entity_type!r}")
    slug = _text(source.get("slug"))
    new_hash = source_hash(source)
    existing = get_derived(entity_type, slug)
    if existing and not force and existing.get("sourceHash") == new_hash:
        return {
            "entityType": entity_type,
            "slug": slug,
            "skipped": True,
            "reason": "sourceHash unchanged",
            "sourceHash": new_hash,
        }

    payload = derive(entity_type, source)
    now = storage.now_iso()
    record = {
        "id": _record_id(entity_type, slug),
        "recordType": SEO_RECORD_TYPE,
        "createdAt": existing.get("createdAt", now) if existing else now,
        "updatedAt": now,
        # `slug` is required by storage.put_record and also powers the slug GSI, so a derived
        # record is findable by the same slug the public URL uses.
        "slug": slug,
        "entityType": entity_type,
        "entityId": _text(source.get("id")) or slug,
        "sourceHash": new_hash,
        "sourceVersion": _text(source.get("modifiedDate")) or _text(source.get("publishedDate")),
        "lastAnalyzedAt": now,
        "validationStatus": "ok",
        "validationErrors": [],
        "sitemapIncluded": _robots(source).startswith("index"),
        "updatedBy": actor,
        **payload,
    }
    storage.put_record(record)
    logger.info(json.dumps({
        "event": "seo_derived_refreshed",
        "entityType": entity_type,
        "slug": slug,
        "created": existing is None,
        "forced": force,
    }))
    return {
        "entityType": entity_type,
        "slug": slug,
        "skipped": False,
        "created": existing is None,
        "sourceHash": new_hash,
    }
