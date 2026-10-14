#!/usr/bin/env python3
"""Verify the public blog serves correctly from a given BLOG_SOURCE — the check to
run right before and right after flipping BLOG_SOURCE=aws (cutover runbook step 5).

READ-ONLY. Hits the public blog API (the same endpoint the frontend + build
generators use) and reports: list count, that a sample post resolves by slug, and
whether any response carries a Wix host (which, under BLOG_SOURCE=aws, must be 0).

Usage:
    python scripts/verify_blog_source.py
    NEXT_PUBLIC_API_BASE=https://wecare.digital/api python scripts/verify_blog_source.py
Exit 0 = healthy; exit 1 = empty blog or (in aws mode) a Wix host leaked through.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

API_BASE = os.environ.get("NEXT_PUBLIC_API_BASE", "https://wecare.digital/api").rstrip("/")
ENDPOINT = f"{API_BASE}/seo-tools/blog-public"
EXPECT_SOURCE = os.environ.get("EXPECT_BLOG_SOURCE", "").strip().lower()  # 'aws' | 'wix' | ''


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    body = _get(f"{ENDPOINT}?fields=slug,title,publishedDate")
    posts = body.get("posts") or []
    total = body.get("total", len(posts))
    print(json.dumps({"endpoint": ENDPOINT, "listed": len(posts), "total": total}, indent=2))

    if not posts:
        print("FAIL: the public blog list is EMPTY — do not ship / do not keep this flag.")
        return 1

    # Resolve one post by slug end-to-end.
    slug = posts[0].get("slug")
    detail = _get(f"{ENDPOINT}/{slug}")
    ok_detail = bool((detail.get("post") or {}).get("slug") == slug)
    print(f"sample slug {slug!r} resolves: {ok_detail}")

    # Wix-host leak check: under aws mode the public responses must carry no wix host.
    raw = json.dumps(body) + json.dumps(detail)
    wix_leak = ("wixapis.com" in raw) or ("wixstatic" in raw) or ("wixmp" in raw)
    print(f"wix host present in responses: {wix_leak}")

    if EXPECT_SOURCE == "aws" and wix_leak:
        print("FAIL: BLOG_SOURCE=aws expected but a Wix host appears in the response.")
        return 1
    if not ok_detail:
        print("FAIL: sample post did not resolve by slug.")
        return 1
    print("OK: blog serves a non-empty list and resolves a post."
          + (" No Wix host (aws mode clean)." if EXPECT_SOURCE == "aws" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
