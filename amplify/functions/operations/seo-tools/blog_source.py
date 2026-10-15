"""One seam that decides WHERE the public blog is read from.

AWS is the sole source of the public blog: published `blogPost` records are read
from the SeoToolsTable via `storage.list_blog_posts` / `storage.get_blog_post`
(published-only). There is no source flag and no other store to dispatch to, so
nothing here reads the environment.

The seam is kept (rather than inlining `storage` at every call site) so that the
public read surface stays named in one place and the handler/frontend route shape
(`src/lib/public-blog.ts`) is untouched. `using_aws()` is retained and always
returns True for any caller that still asks.

AWS was proven authoritative (1,421 published posts in SeoToolsTable == live API
total) before it became the only read path.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import storage


def source() -> str:
    """Always 'aws'. Retained for callers/tests that still query the source name."""
    return "aws"


def using_aws() -> bool:
    return True


def list_blog_posts() -> List[Dict[str, Any]]:
    """Public blog list — published posts only, heavy content omitted."""
    return storage.list_blog_posts(published_only=True, limit=0, include_content=False)


def get_blog_post_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Public single post by slug — published only, so a draft slug 404s publicly."""
    return storage.get_blog_post(slug, published_only=True)
