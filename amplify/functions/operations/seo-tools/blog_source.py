"""One seam that decides WHERE the public blog is read from: Wix or AWS.

WHY THIS EXISTS. The public blog read path (`/blog-public` in handler.py) calls
Wix directly through `wix.list_blog_posts()` / `wix.get_blog_post_by_slug()`,
using an anonymous visitor token. That is the single largest active Wix runtime
dependency, and `WIX_CREDENTIALS_DISABLED` deliberately does NOT disable it (see
`wix_guard.py`). To make AWS authoritative for the blog WITHOUT a risky rewrite,
this module provides the same two functions and dispatches on one environment
variable:

    BLOG_SOURCE = wix   (default)  -> current behaviour, unchanged
    BLOG_SOURCE = aws              -> read published posts from the SeoToolsTable
                                      (`storage.list_blog_posts` / `get_blog_post`),
                                      no Wix call at all

The AWS branch is NOT a stub: `storage._blog_view` already projects a
public-shaped post from the `blogPost` records in DynamoDB, and the admin Blog
Studio already writes those records. The migration seeds that table from the Wix
export (see docs/migrations/wix-data-reconciliation.md); flipping BLOG_SOURCE to
`aws` after reconciliation is the blog half of the Wix cutover, and flipping it
back to `wix` is the instant rollback.

REVERSIBILITY IS THE POINT. This file changes nothing until the flag is set, so
merging it to `stack` is non-mutating. The flag flip itself is a production change
and is owner-approval-gated (spec Phase 6).

The frontend (`src/lib/public-blog.ts`) and the handler route shape are untouched
either way — only the data source behind this seam moves.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import storage
import wix

SOURCE_ENV = "BLOG_SOURCE"
_AWS_VALUES = ("aws", "ddb", "dynamodb", "native")


def source() -> str:
    """Return the active blog source, normalised. Read on every call (not captured
    at import) so an operator flip takes effect without waiting for sandbox
    recycling - the same incident-control discipline as wix_guard.credentials_disabled.
    """
    value = str(os.environ.get(SOURCE_ENV, "wix")).strip().lower()
    return "aws" if value in _AWS_VALUES else "wix"


def using_aws() -> bool:
    return source() == "aws"


def list_blog_posts() -> List[Dict[str, Any]]:
    """Public blog list. AWS branch returns ONLY published posts (the public
    corpus); the Wix branch is the pre-existing visitor-token read."""
    if using_aws():
        return storage.list_blog_posts(published_only=True, include_content=False)
    return wix.list_blog_posts()


def get_blog_post_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Public single post by slug. AWS branch serves only published posts so an
    unpublished draft slug 404s publicly, matching the Wix behaviour."""
    if using_aws():
        return storage.get_blog_post(slug, published_only=True)
    return wix.get_blog_post_by_slug(slug)
