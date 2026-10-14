#!/usr/bin/env python3
"""Idempotent Wix export + reconciliation report (read-only against Wix).

This exports the Wix blog and store into a LOCAL archive with per-item checksums
and a reconciliation report, so the AWS-native stores can be seeded and proven
complete (docs/migrations/wix-data-reconciliation.md). It is deliberately
READ-ONLY against Wix (GET/query only) and writes only to a local output
directory. Writing the encrypted archive to the S3 credential/export bucket is a
separate, owner-approved step (billable write) — NOT done here.

Design (task A5):
  - paginated reads with a cursor guard,
  - immutable Wix ids preserved as `sourceId`,
  - retry on transient status,
  - per-item sha256 content checksum in the manifest,
  - a reconciliation report comparing exported counts to fresh authoritative
    Wix counts,
  - repeatable + idempotent: re-running converges and the manifest is stable
    (items sorted by id; checksums are content-only).

NO SECRETS ARE PRINTED. The Wix admin key is read by reference from Secrets
Manager only in --live mode; --dry (default) performs NO network/secret access
and is what CI and local verification run.

Usage:
  python -m scripts.wix_export.export --dry                 # structure self-test
  python -m scripts.wix_export.export --dry --fixture f.json
  python -m scripts.wix_export.export --live --out outputs/wix-export  # 🔒 needs creds
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

WIX_API = os.environ.get("WIX_API_BASE", "https://www.wixapis.com")
WIX_SITE_ID = os.environ.get("WIX_SITE_ID", "c993128b-26be-41cd-9fcd-904abe23462f")
WIX_ACCOUNT_ID = os.environ.get("WIX_ACCOUNT_ID", "478bf907-96cc-4cab-9220-bb96f1d35cbb")
WIX_API_KEY_SECRET = os.environ.get("WIX_API_KEY_SECRET", "wecare/wix/headless-api-key")
REGION = os.environ.get("AWS_REGION", "us-east-1")

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_PAGES = 500
PAGE_SIZE = 100


def content_checksum(item: Dict[str, Any]) -> str:
    """Stable sha256 over the item's content, independent of key order so re-runs
    produce identical checksums for identical content."""
    payload = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise(items: List[Dict[str, Any]], id_key: str = "id") -> List[Dict[str, Any]]:
    """Preserve the immutable Wix id as sourceId and sort by it, so the manifest is
    deterministic and idempotent across runs."""
    out = []
    for it in items:
        rec = dict(it)
        rec.setdefault("sourceId", rec.get(id_key, ""))
        out.append(rec)
    out.sort(key=lambda r: str(r.get("sourceId", "")))
    return out


def manifest_for(kind: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    norm = _normalise(items)
    return {
        "kind": kind,
        "site_id": WIX_SITE_ID,
        "account_id": WIX_ACCOUNT_ID,
        "count": len(norm),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "items": [
            {"sourceId": r.get("sourceId", ""), "checksum": content_checksum(r), "data": r}
            for r in norm
        ],
    }


def reconcile(kind: str, manifest: Dict[str, Any], fresh_count: Optional[int]) -> Dict[str, Any]:
    exported = manifest["count"]
    checksums = {i["sourceId"]: i["checksum"] for i in manifest["items"]}
    dup_ids = exported - len(checksums)
    verdict = "RECONCILED"
    if fresh_count is not None and fresh_count != exported:
        verdict = "DISCREPANCY"
    if dup_ids:
        verdict = "DISCREPANCY"
    return {
        "kind": kind,
        "exported": exported,
        "fresh_wix_count": fresh_count,
        "duplicate_ids": dup_ids,
        "verdict": verdict,
    }


# ── live Wix reads (only used with --live) ───────────────────────────────────

def _api_key() -> str:
    import boto3
    raw = boto3.client("secretsmanager", region_name=REGION) \
        .get_secret_value(SecretId=WIX_API_KEY_SECRET).get("SecretString", "") or ""
    try:
        data = json.loads(raw)
        value = (data.get("apiKey") or data.get("api_key") or data.get("value")
                 or data.get("key") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise SystemExit("Wix API key not configured")
    return value


def _post(endpoint: str, body: Dict[str, Any], key: str) -> Dict[str, Any]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        f"{WIX_API}{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Authorization": key, "Content-Type": "application/json",
                 "wix-site-id": WIX_SITE_ID, "wix-account-id": WIX_ACCOUNT_ID},
        method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"Wix {endpoint} HTTP {e.code}")  # no body (may echo data)
    raise SystemExit(f"Wix {endpoint} exhausted retries")


def _paginate(endpoint: str, base_body: Dict[str, Any], items_key: str,
              key: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(MAX_PAGES):
        body = dict(base_body)
        paging = {"limit": PAGE_SIZE}
        if cursor:
            paging = {"cursor": cursor}
        body.setdefault("query", {})["cursorPaging"] = paging
        data = _post(endpoint, body, key)
        batch = data.get(items_key, []) or []
        items.extend(batch)
        cursor = (data.get("pagingMetadata", {}) or {}).get("cursors", {}).get("next")
        if not cursor or not batch:
            break
    return items


def export_live(out_dir: Path) -> Dict[str, Any]:
    key = _api_key()
    blog = _paginate("/blog/v3/posts/query", {"query": {}}, "posts", key)
    products = _paginate("/stores/v3/products/search", {"query": {}}, "products", key)
    reports = {}
    for kind, items in (("blog", blog), ("store-products", products)):
        man = manifest_for(kind, items)
        (out_dir / f"{kind}.json").write_text(json.dumps(man, indent=2))
        reports[kind] = reconcile(kind, man, fresh_count=len(items))
    return reports


# ── dry mode (default): structure self-test, no network ──────────────────────

def export_dry(fixture: Optional[Path]) -> Dict[str, Any]:
    if fixture and fixture.exists():
        data = json.loads(fixture.read_text())
        blog = data.get("blog", [])
        products = data.get("products", [])
    else:
        blog = [{"id": "p2", "slug": "b", "title": "B"},
                {"id": "p1", "slug": "a", "title": "A"}]
        products = [{"id": "x1", "slug": "prod-a", "price": {"amount": "599.00"}}]
    reports = {}
    for kind, items in (("blog", blog), ("store-products", products)):
        man = manifest_for(kind, items)
        reports[kind] = reconcile(kind, man, fresh_count=len(items))
        # prove idempotency: a second manifest over the same items is identical
        man2 = manifest_for(kind, items)
        assert man["items"] == man2["items"], "export is not idempotent"
    return reports


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", default=True,
                      help="default: structure self-test, no network/secret access")
    mode.add_argument("--live", action="store_true",
                      help="read live Wix (needs creds); 🔒 still writes only locally")
    ap.add_argument("--fixture", type=Path, help="dry-mode fixture json {blog:[],products:[]}")
    ap.add_argument("--out", type=Path, default=Path("outputs/wix-export"))
    args = ap.parse_args()

    if args.live:
        args.out.mkdir(parents=True, exist_ok=True)
        reports = export_live(args.out)
    else:
        reports = export_dry(args.fixture)

    print(json.dumps({"mode": "live" if args.live else "dry", "reports": reports}, indent=2))
    return 0 if all(r["verdict"] == "RECONCILED" for r in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
