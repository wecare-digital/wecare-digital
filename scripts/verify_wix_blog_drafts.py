#!/usr/bin/env python3
"""Read-only check: are there Wix blog DRAFTS (unpublished posts) not in our AWS store?

A migration completeness gate before deleting the Wix site. An anonymous visitor
token sees only PUBLISHED posts, so draft existence can only be confirmed with the
Wix ADMIN API key. This script reads that key from Secrets Manager
(`wecare/wix/headless-api-key`) at runtime, queries Wix for posts in every status,
and compares against the published count our AWS store holds (1421).

KNOWN ISSUE DISCOVERED 2026-10-14 — the admin key cannot reach the live blog site.
Measured: `/blog/v3/posts/query` with this admin key + `wix-site-id=c993128b...`
returns HTTP 404 "meta-site c993128b... not found", and the account-header variant
returns 403, while the anonymous VISITOR token (public WIX_BLOG_CLIENT_ID) reads
the same site's 1421 published posts fine. So the admin key is bound to a different
or stale Wix site/app identity than the one serving the blog. Until that binding is
fixed in the Wix console (attach the Blog app + Blog read scope for site
c993128b... to this key), THIS CHECK CANNOT COUNT DRAFTS, and "no drafts" cannot be
asserted. The published completeness (1421 == 1421) is already proven by the
visitor path; only the DRAFT question is blocked on the admin-key binding.

READ-ONLY: no writes to Wix, DynamoDB, or anywhere. The admin key is used only for
the GET/query and is NEVER printed.

Usage:
    python scripts/verify_wix_blog_drafts.py
Exit 0 = no drafts (safe for blog deletion); exit 1 = drafts found OR inconclusive
(including the admin-key/site-binding problem above).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

WIX_API = "https://www.wixapis.com"
SITE = os.environ.get("WIX_SITE_ID", "c993128b-26be-41cd-9fcd-904abe23462f")
ACCOUNT = os.environ.get("WIX_ACCOUNT_ID", "478bf907-96cc-4cab-9220-bb96f1d35cbb")
SECRET = os.environ.get("WIX_API_KEY_SECRET", "wecare/wix/headless-api-key")
REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_PUBLISHED = 1421  # our reconciled AWS blogPost count


def _admin_key() -> str:
    import boto3
    raw = boto3.client("secretsmanager", region_name=REGION) \
        .get_secret_value(SecretId=SECRET).get("SecretString", "") or ""
    try:
        d = json.loads(raw)
        v = (d.get("apiKey") or d.get("api_key") or d.get("value") or d.get("key") or "").strip()
    except (ValueError, TypeError):
        v = raw.strip()
    if not v:
        raise SystemExit("Wix admin key not configured in " + SECRET)
    return v


def _query(key: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{WIX_API}/blog/v3/posts/query",
        data=json.dumps(body).encode(),
        headers={"Authorization": key, "Content-Type": "application/json",
                 "wix-site-id": SITE, "wix-account-id": ACCOUNT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Wix query HTTP {e.code} (admin key needs Blog read scope)")


def main() -> int:
    key = _admin_key()
    # Ask Wix for posts across ALL statuses the admin key can see. The Blog V3 query
    # with no status filter under an admin key returns published + unpublished; some
    # tenants require an explicit fieldsets/status — we read the total either way.
    allp = _query(key, {"query": {"paging": {"limit": 1}}})
    total_all = (allp.get("pagingMetadata") or {}).get("total")

    # Explicitly request unpublished where supported (DRAFT / UNPUBLISHED status).
    drafts = None
    try:
        dq = _query(key, {"query": {"filter": {"status": {"$in": ["UNPUBLISHED", "DRAFT"]}},
                                    "paging": {"limit": 1}}})
        drafts = (dq.get("pagingMetadata") or {}).get("total")
    except SystemExit:
        drafts = None  # filter unsupported on this tenant; fall back to the delta

    delta = (total_all - AWS_PUBLISHED) if isinstance(total_all, int) else None
    print(json.dumps({
        "wix_total_all_statuses": total_all,
        "wix_draft_count_explicit": drafts,
        "aws_published_count": AWS_PUBLISHED,
        "implied_unpublished_delta": delta,
    }, indent=2))

    draft_n = drafts if isinstance(drafts, int) else delta
    if draft_n is None:
        print("INCONCLUSIVE: could not read a draft count; do not delete on this alone.")
        return 1
    if draft_n <= 0:
        print("OK: no Wix drafts beyond the 1421 published posts already in AWS. "
              "Blog content is complete for deletion.")
        return 0
    print(f"DRAFTS FOUND: {draft_n} unpublished Wix post(s) are NOT in the AWS store. "
          "Export these before deleting the Wix site.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
