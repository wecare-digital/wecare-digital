#!/usr/bin/env python3
"""Build a provider-independent catalog snapshot from the AWS ProductsTable.

This is the AWS-native replacement for `scripts/fetch-wix-catalog.js`. It reads
the authoritative `ProductsTable` and writes `src/content/catalog-snapshot.json`
in the SAME envelope `src/content/wix-catalog.json` uses, so `src/content/shop.ts`
can switch its import with no interface change and the static `/shop` pages build
from AWS instead of Wix (spec task 4.4).

Envelope (matches the committed Wix snapshot):
  { source, catalogVersion, fetchedAt, productCount, products[], variantVerifiedAt }
Each product matches the `ShopProduct` interface in shop.ts: id, name, slug,
formattedPrice, price (bare decimal string, DISPLAY ONLY — never charged),
currency, inStock, image?, tagline, body[], variants?.

Prices here are DISPLAY ONLY. The amount actually charged comes from the native
checkout pricing (`catalog_pricing`/`checkout_pricing`) compared in integer paise,
never from this file — the same guarantee the Wix snapshot carried.

READ-ONLY against AWS. `--dry` (default) uses a fixture and writes nothing, so CI
and local verification need no AWS access. `--live` reads ProductsTable (needs
IAM) and writes the snapshot locally. Committing the snapshot (which triggers an
Amplify rebuild) is a separate, owner-approved step.

Usage:
  python scripts/build-catalog-snapshot.py --dry
  python scripts/build-catalog-snapshot.py --dry --fixture products.json
  python scripts/build-catalog-snapshot.py --live   # reads ProductsTable
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

PRODUCTS_TABLE = os.environ.get("PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")
OUT_PATH = Path(os.environ.get("CATALOG_SNAPSHOT_PATH", "src/content/catalog-snapshot.json"))


def _paise_to_decimal_string(paise: int) -> str:
    """Integer paise -> bare decimal major-unit string, e.g. 659900 -> '6599.00'.
    Decimal only, never float — the price string must be exact."""
    if type(paise) is not int or paise < 0:
        raise ValueError("priceMinor must be a nonnegative integer paise")
    return f"{Decimal(paise) / Decimal(100):.2f}"


def _formatted_inr(paise: int) -> str:
    """'₹6,599.00' with Indian-style grouping on the rupee part."""
    rupees, p = divmod(int(paise), 100)
    s = str(rupees)
    # Indian grouping: last 3 digits, then groups of 2.
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"\u20b9{s}.{p:02d}"


def to_shop_product(item: Dict[str, Any]) -> Dict[str, Any]:
    """Project one ProductsTable item onto the ShopProduct shape shop.ts expects."""
    price_minor = int(item.get("priceMinor", 0) or 0)
    body = item.get("body") or []
    if isinstance(body, str):
        body = [body]
    variants = []
    for v in item.get("variants", []) or []:
        variants.append({
            "id": str(v.get("sku") or v.get("id") or ""),
            "label": str(v.get("label") or v.get("options") or ""),
            "inStock": bool(v.get("inventory", 0)),
        })
    product: Dict[str, Any] = {
        "id": str(item.get("id", "")),
        "name": str(item.get("title") or item.get("name") or ""),
        "slug": str(item.get("slug", "")),
        "price": _paise_to_decimal_string(price_minor),
        "formattedPrice": _formatted_inr(price_minor),
        "currency": str(item.get("currency", "INR")),
        "inStock": bool(item.get("inventory", 0)) or any(x["inStock"] for x in variants),
        "tagline": str(item.get("tagline") or item.get("seoDescription") or ""),
        "body": [str(b) for b in body],
    }
    images = item.get("imageRefs") or []
    if images:
        product["image"] = str(images[0])
    if variants:
        product["variants"] = variants
    return product


def _utc_now_z() -> str:
    """Canonical UTC timestamp: millisecond precision, trailing 'Z'
    (e.g. '2026-10-14T06:52:56.535Z'). Provider-independent and byte-stable, so the
    static build cannot render two different dates for the same instant and the shape
    does not drift with the Python version's default isoformat()."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def build_snapshot(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    products = [to_shop_product(it) for it in items if it.get("status", "active") != "archived"]
    products.sort(key=lambda p: p["slug"])
    now = _utc_now_z()
    return {
        "source": "aws products-table (native catalog)",
        "catalogVersion": "AWS_NATIVE_V1",
        "fetchedAt": now,
        "productCount": len(products),
        "products": products,
        "variantVerifiedAt": now,
    }


def _read_products_table() -> List[Dict[str, Any]]:
    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(PRODUCTS_TABLE)
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)  # catalog is small; a scan is acceptable here
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    # DynamoDB returns Decimal; normalise priceMinor/inventory to int.
    for it in items:
        for k in ("priceMinor", "inventory"):
            if isinstance(it.get(k), Decimal):
                it[k] = int(it[k])
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", default=True,
                      help="default: fixture-driven, writes nothing")
    mode.add_argument("--live", action="store_true", help="read ProductsTable (needs IAM)")
    ap.add_argument("--fixture", type=Path, help="dry fixture json: [ {ProductsTable item}, ... ]")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    if args.live:
        items = _read_products_table()
        snap = build_snapshot(items)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
        print(f"wrote {args.out} ({snap['productCount']} products)")
        return 0

    if args.fixture and args.fixture.exists():
        items = json.loads(args.fixture.read_text())
    else:
        items = [
            {"id": "p1", "title": "Starter", "slug": "starter", "priceMinor": 659900,
             "currency": "INR", "inventory": 5, "tagline": "A starter.", "body": ["Line one."]},
            {"id": "p2", "title": "Archived", "slug": "old", "priceMinor": 100,
             "status": "archived", "inventory": 0},
        ]
    snap = build_snapshot(items)
    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
