#!/usr/bin/env python3
"""Full off-DynamoDB backup of every blogPost record (read-only).

Insurance before any Wix deletion: dumps all `recordType=blogPost` items from
`stack-wecare-digital-SeoToolsTable` to a single JSON file with a per-record
sha256 and a manifest (count, total bytes, min/median/max content length, any
empty/duplicate slugs). READ-ONLY — never writes to DynamoDB or Wix.

Usage:
    python scripts/backup_blog_posts.py                       # -> outputs/blog-backup-<ts>.json
    python scripts/backup_blog_posts.py --out /path/file.json
    python scripts/backup_blog_posts.py --verify /path/file.json   # re-check a backup's checksums
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

TABLE = "stack-wecare-digital-SeoToolsTable"
REGION = "us-east-1"
INDEX = "recordType-createdAt-index"


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def _checksum(item: dict) -> str:
    payload = json.dumps(item, sort_keys=True, separators=(",", ":"), default=_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scan_all():
    import boto3
    from boto3.dynamodb.conditions import Key
    t = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    kw = dict(IndexName=INDEX, KeyConditionExpression=Key("recordType").eq("blogPost"))
    items = []
    while True:
        r = t.query(**kw)
        items.extend(r["Items"])
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return items


def export(out_path: Path) -> dict:
    items = _scan_all()
    items.sort(key=lambda it: str(it.get("slug", "")))
    records, slugs, lens, empty = [], {}, [], 0
    for it in items:
        c = str(it.get("content") or "")
        lens.append(len(c))
        if not c:
            empty += 1
        sl = str(it.get("slug", ""))
        slugs[sl] = slugs.get(sl, 0) + 1
        records.append({"slug": sl, "checksum": _checksum(it), "data": it})
    lens.sort()
    manifest = {
        "source": f"dynamodb://{REGION}/{TABLE} (recordType=blogPost)",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "distinct_slugs": len(slugs),
        "duplicate_slugs": sum(1 for v in slugs.values() if v > 1),
        "empty_content": empty,
        "content_len_min": lens[0] if lens else 0,
        "content_len_median": lens[len(lens) // 2] if lens else 0,
        "content_len_max": lens[-1] if lens else 0,
    }
    payload = {"manifest": manifest, "records": records}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=_default))
    manifest["bytes_written"] = out_path.stat().st_size
    manifest["file"] = str(out_path)
    return manifest


def verify(path: Path) -> dict:
    payload = json.loads(path.read_text())
    mismatches = 0
    for rec in payload["records"]:
        if _checksum(rec["data"]) != rec["checksum"]:
            mismatches += 1
    return {"records": len(payload["records"]), "checksum_mismatches": mismatches,
            "verdict": "INTACT" if mismatches == 0 else "CORRUPT"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--verify", type=Path, metavar="FILE")
    args = ap.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), indent=2))
        return 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = args.out or Path(f"outputs/blog-backup-{ts}.json")
    manifest = export(out)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
