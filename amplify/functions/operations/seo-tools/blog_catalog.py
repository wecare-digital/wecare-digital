"""S3 catalog index and production-master snapshots for the AWS-native blog.

There are deliberately two surfaces:

* ``o/blog-production/catalog/index.json`` is public catalog data only. It contains
  published article cards and can safely back search/index consumers.
* ``secure/blog-production/production-master.json`` is an internal operational snapshot.
  It contains source/pipeline state and therefore stays behind the existing secure prefix.

DynamoDB remains the authoritative transactional store. These S3 documents are durable,
rebuildable projections so a bulk run can be audited or resumed without inventing a second
publisher or a second source of truth.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

import blog_sources
import storage

PUBLIC_CATALOG_PREFIX = blog_sources.ROOT_PREFIX + "catalog/"
PUBLIC_POST_PREFIX = blog_sources.ROOT_PREFIX + "posts/"
CATALOG_INDEX_KEY = PUBLIC_CATALOG_PREFIX + "index.json"
SECURE_MASTER_PREFIX = "secure/blog-production/"
PRODUCTION_MASTER_KEY = SECURE_MASTER_PREFIX + "production-master.json"

GOVERNED_CATEGORIES = ("Conversations", "Gastronomy")
MAX_BULK_ITEMS = 1000


def _put_json(key: str, document: Dict[str, Any]) -> str:
    blog_sources.s3_client().put_object(
        Bucket=blog_sources.BUCKET, Key=key,
        Body=json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return key


def post_key(slug: str) -> str:
    clean = str(slug or "").strip().strip("/")
    if not clean:
        raise ValueError("slug is required")
    return PUBLIC_POST_PREFIX + clean + ".json"


def write_published_post(record: Dict[str, Any], draft: Dict[str, Any],
                         result: Dict[str, Any], actor: str) -> str:
    """Mirror one successfully published article to the existing S3 bucket.

    Only public article fields are written below ``o/``. Source ids, source hashes, source
    filenames, QA ids and other provenance stay out of this document.
    """
    category = str(record.get("category") or draft.get("category") or "").strip()
    if category not in GOVERNED_CATEGORIES:
        raise ValueError(f"unsupported blog category {category!r}")
    slug = str(draft.get("slug") or "").strip()
    document = {
        "postId": str(result.get("postId") or ""),
        "url": str(result.get("postUrl") or ""),
        "slug": slug,
        "title": str(draft.get("title") or "").strip(),
        "excerpt": str(draft.get("excerpt") or "").strip(),
        "content": str(draft.get("contentMarkdown") or ""),
        "category": category,
        "tags": draft.get("tagLabels") or draft.get("tags") or [],
        "hashtags": draft.get("hashtags") or [],
        "authorName": str(draft.get("authorName") or "Anew by WECARE.DIGITAL").strip(),
        "seoTitle": str(draft.get("seoTitle") or "").strip(),
        "metaDescription": str(draft.get("metaDescription") or "").strip(),
        "focusKeyword": str(draft.get("focusKeyword") or "").strip(),
        "secondaryKeywords": draft.get("secondaryKeywords") or [],
        "jsonLd": draft.get("jsonLd") or {},
        "publishedBy": actor,
        "mirroredAt": storage.now_iso(),
    }
    return _put_json(post_key(slug), document)


def catalog_index() -> Dict[str, Any]:
    posts = storage.list_blog_posts(published_only=True, limit=0, include_content=False)
    cards: List[Dict[str, Any]] = []
    for post in posts:
        category = str(post.get("category") or "").strip()
        if category not in GOVERNED_CATEGORIES:
            continue
        cards.append({
            "postId": post.get("id", ""),
            "slug": post.get("slug", ""),
            "title": post.get("title", ""),
            "excerpt": post.get("excerpt", ""),
            "category": category,
            "tags": post.get("tags", []) or [],
            "publishedDate": post.get("publishedDate", ""),
            "modifiedDate": post.get("modifiedDate", ""),
            "url": post.get("url", ""),
        })
    return {
        "generatedAt": storage.now_iso(),
        "count": len(cards),
        "categories": {name: sum(1 for row in cards if row["category"] == name)
                       for name in GOVERNED_CATEGORIES},
        "posts": cards,
    }


def production_master() -> Dict[str, Any]:
    sources = storage.scan_by_record_type(blog_sources.RECORD_TYPE)
    publish_jobs = storage.scan_by_record_type("blogPublishJob")
    batches = storage.scan_by_record_type("blogBatch")
    categories: Dict[str, Any] = {}
    for category in GOVERNED_CATEGORIES:
        category_sources = [row for row in sources if row.get("category") == category]
        source_status = Counter(str(row.get("status") or "") for row in category_sources)
        article_status = Counter(str(row.get("articleStatus") or "")
                                 for row in category_sources if row.get("articleStatus"))
        publish_status = Counter(
            str((row.get("pipeline") or {}).get("publishStatus") or "UNRELEASED")
            for row in category_sources)
        categories[category] = {
            "sources": len(category_sources),
            "bySourceStatus": dict(sorted(source_status.items())),
            "byArticleStatus": dict(sorted(article_status.items())),
            "byPublishStatus": dict(sorted(publish_status.items())),
        }
    return {
        "generatedAt": storage.now_iso(),
        "authoritativeStore": storage.TABLE_NAME,
        "bucket": blog_sources.BUCKET,
        "maxBulkItems": MAX_BULK_ITEMS,
        "governedCategories": list(GOVERNED_CATEGORIES),
        "categories": categories,
        "totals": {
            "sources": len(sources),
            "batches": len(batches),
            "publishJobs": len(publish_jobs),
        },
        "notes": [
            "DynamoDB is authoritative; this S3 master is a rebuildable operational snapshot.",
            "Publishing remains human-gated. Extraction or batch completion never auto-publishes.",
            "Source provenance is intentionally absent from the public catalog index.",
        ],
    }


def sync() -> Dict[str, Any]:
    catalog = catalog_index()
    master = production_master()
    _put_json(CATALOG_INDEX_KEY, catalog)
    _put_json(PRODUCTION_MASTER_KEY, master)
    return {
        "bucket": blog_sources.BUCKET,
        "catalogIndexKey": CATALOG_INDEX_KEY,
        "productionMasterKey": PRODUCTION_MASTER_KEY,
        "catalogPosts": catalog["count"],
        "categories": master["categories"],
        "maxBulkItems": MAX_BULK_ITEMS,
    }
