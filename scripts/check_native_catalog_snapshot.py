#!/usr/bin/env python3
"""Fail-closed guard for publishing an AWS ProductsTable static snapshot.

Checks all 10 original identities and all 23 seeded variants by *shape*, not by
hard-coded product count. New products may be added. Product deletions exceeding
50% of the active catalog require a human-approved dispatch. A scheduled run
must never commit an empty or badly truncated public shop.

When there is no meaningful change, restore the prior snapshot bytes so the
GitHub job does not rebuild the website just to update fetchedAt timestamps.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT = Path("src/content/catalog-snapshot.json")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _semantic(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in snapshot.items()
        if key not in ("fetchedAt", "variantVerifiedAt")
    }


def check_snapshot(
    old: dict[str, Any], new: dict[str, Any], *, allow_large_removal: bool = False
) -> dict[str, Any]:
    before = old.get("products") or []
    after = new.get("products") or []
    if not isinstance(after, list) or not after:
        raise ValueError("AWS product snapshot is empty; refusing storefront publication")
    if new.get("productCount") != len(after):
        raise ValueError("new catalog productCount does not match products array")
    if len(after) < 6:
        raise ValueError("public shop floor breached (fewer than 6 native products)")
    seen_slugs, seen_ids = set(), set()
    for p in after:
        if not isinstance(p, dict):
            raise ValueError("invalid product row")
        pid, slug = p.get("id"), p.get("slug")
        if not isinstance(pid, str) or not pid:
            raise ValueError("product has no stable ID")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError("invalid product slug")
        if pid in seen_ids or slug in seen_slugs:
            raise ValueError("duplicate product or slug")
        seen_slugs.add(slug)
        seen_ids.add(pid)
        if not isinstance(p.get("name"), str) or not p["name"]:
            raise ValueError("product name missing")
        if not isinstance(p.get("formattedPrice"), str) or not p["formattedPrice"]:
            raise ValueError("product display price missing")
        variants = p.get("variants") or []
        if not isinstance(variants, list):
            raise ValueError("invalid variants")
        ids = [v.get("id") if isinstance(v, dict) else None for v in variants]
        if not ids or any(not v for v in ids) or len(ids) != len(set(ids)):
            raise ValueError("missing or duplicate variant identity")
        image = p.get("image") or ""
        if image and (not isinstance(image, str)
                      or not image.startswith("https://")):
            raise ValueError("product image must be HTTPS")
    old_active = {p["id"] for p in before if p.get("visible", True)}
    new_active = {p["id"] for p in after if p.get("visible", True)}
    removed = sorted(old_active - new_active)
    if old_active and len(removed) * 2 > len(old_active) and not allow_large_removal:
        raise ValueError("more than half the visible shop disappeared; human review required")
    return {
        "old": len(before), "new": len(after),
        "old_active": len(old_active), "new_active": len(new_active),
        "removed_active_ids": removed,
        "changed": _semantic(old) != _semantic(new),
    }


def _git_original(path: Path):
    proc = subprocess.run(
        ["git", "show", "HEAD:" + str(path)],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT)
    ap.add_argument("--allow-large-removal", action="store_true")
    ap.add_argument("--restore-if-unchanged", action="store_true")
    args = ap.parse_args()
    current_text = args.snapshot.read_text(encoding="utf-8")
    old_text = _git_original(args.snapshot)
    old = json.loads(old_text)
    new = json.loads(current_text)
    diff = check_snapshot(old, new, allow_large_removal=args.allow_large_removal)
    print(json.dumps(diff, indent=2))
    if args.restore_if_unchanged and not diff["changed"]:
        args.snapshot.write_text(old_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
