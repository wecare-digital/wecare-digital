#!/usr/bin/env python3
"""Build a PRODUCTION-QUALITY ProductsTable seed from the committed catalog, OFFLINE.

WHY THIS EXISTS. `seed_products_from_wix.py` reads the LIVE Wix storefront with a
visitor token. The Wix site is gone, so that path is dead, and its last output
(`outputs/products-seed.json`) was thin: `tagline` was the first 200 chars of raw
HTML, `body` was empty, and `variants` was []. Seeding the live (empty)
ProductsTable from that would publish an SEO-degraded, variant-stripped /shop.

THE REAL DATA WE ALREADY HAVE is `src/content/wix-catalog.json` — the last good
committed snapshot, with full `descriptionHtml`, real prices/formattedPrice,
images, and the real per-variant rows (sku, id, label, inStock, pricePaise). This
script projects THAT onto the exact `ProductsTable` item shape the native engine
reads (`catalog_pricing`/`native_cart`/`meta-catalog-sync`/checkout variant
reader), with NO network and NO Wix dependency. Fully offline and idempotent.

Field mapping (ProductsTable item <- wix-catalog product):
  id            <- product.id          (immutable UUID; Meta retailer-id contract)
  sourceId      <- product.id          (provenance)
  title         <- product.name
  slug          <- product.slug
  priceMinor    <- product.price       (integer paise via Decimal; display floor)
  currency      <- product.currency    (default INR)
  formattedPrice<- product.formattedPrice (rendered once, carried for display)
  inventory     <- 1 if product.inStock else 0
  status        <- 'active' (archived rows are already absent from the snapshot)
  categories    <- [] (snapshot carries no category ids; left empty, non-authoritative)
  imageRefs     <- [product.image] when present
  tagline       <- first plain-text paragraph of descriptionHtml
  body          <- remaining plain-text paragraphs, in order
  variants[]    <- {sku, id, label, inStock, priceMinor} from product.variants

PRICES ARE DISPLAY-FLOOR ONLY. The amount charged is recomputed server-side in
integer paise by the native checkout from this same table; this file never
bypasses that. See amplify/.../ecommerce/catalog_pricing.py.

Usage:
    python scripts/reconcile_products_seed.py                     # -> outputs/products-seed.json
    python scripts/reconcile_products_seed.py --out /tmp/seed.json
    python scripts/reconcile_products_seed.py --in src/content/wix-catalog.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_IN = Path("src/content/wix-catalog.json")
DEFAULT_OUT = Path("outputs/products-seed.json")

_BREAK = "\u0001"
_TAG = re.compile(r"<[^>]*>")


def to_paragraphs(markup: str) -> List[str]:
    """HTML -> plain-text paragraphs, mirroring src/content/shop.ts toParagraphs().

    <br> and </p> become paragraph breaks; every other tag is dropped; entities are
    decoded AFTER tag removal; each line's internal whitespace is collapsed. The output
    is display text for React children (escaped on render), never markup.
    """
    if not markup:
        return []
    text = markup.replace(_BREAK, "")
    text = re.sub(r"<\s*br\s*/?\s*>", _BREAK, text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", _BREAK, text, flags=re.IGNORECASE)
    # Strip remaining tags to a fixed point (defeats nested/spliced tags), then bare brackets.
    while True:
        nxt = _TAG.sub("", text)
        if nxt == text:
            break
        text = nxt
    text = text.replace("<", "").replace(">", "")
    text = html.unescape(text)
    out = []
    for line in text.split(_BREAK):
        collapsed = re.sub(r"\s+", " ", line).strip()
        if collapsed:
            out.append(collapsed)
    return out


def _paise(amount_str: Any) -> int:
    """Bare decimal major-unit string -> integer paise, via Decimal (never float)."""
    if amount_str in (None, ""):
        return 0
    whole, _, frac = str(amount_str).partition(".")
    return int(whole or 0) * 100 + int((frac + "00")[:2])


def map_product(p: Dict[str, Any]) -> Dict[str, Any]:
    pid = str(p.get("id") or "")
    paragraphs = to_paragraphs(str(p.get("descriptionHtml") or ""))
    tagline = paragraphs[0] if paragraphs else ""
    body = paragraphs[1:] if len(paragraphs) > 1 else []
    variants = []
    for v in p.get("variants") or []:
        vp = v.get("pricePaise")
        variants.append({
            "sku": str(v.get("sku") or v.get("id") or ""),
            "id": str(v.get("id") or ""),
            "label": str(v.get("label") or ""),
            "inStock": bool(v.get("inStock")),
            "inventory": 1 if v.get("inStock") else 0,
            "priceMinor": int(vp) if isinstance(vp, int) else _paise(p.get("price")),
        })
    item: Dict[str, Any] = {
        "id": pid,
        "sourceId": pid,
        "title": str(p.get("name") or ""),
        "slug": str(p.get("slug") or ""),
        "priceMinor": _paise(p.get("price")),
        "currency": str(p.get("currency") or "INR"),
        "formattedPrice": str(p.get("formattedPrice") or ""),
        "inventory": 1 if p.get("inStock") else 0,
        "status": "active",
        "categories": [],
        "imageRefs": [str(p["image"])] if p.get("image") else [],
        "tagline": tagline,
        "body": body,
        "variants": variants,
        "updatedAt": str(p.get("updatedAt") or p.get("fetchedAt") or ""),
    }
    return item


def build(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = [map_product(p) for p in products if p.get("id") and p.get("slug")]
    items.sort(key=lambda it: it["slug"])
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    snap = json.loads(args.src.read_text())
    products = snap.get("products") if isinstance(snap, dict) else snap
    items = build(products or [])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Round-trip through Decimal-safe json so the file is pure ints (DynamoDB-ready).
    args.out.write_text(json.dumps(items, indent=2, ensure_ascii=False))

    total_variants = sum(len(i["variants"]) for i in items)
    with_body = sum(1 for i in items if i["body"])
    print(f"wrote {args.out} — {len(items)} products, {total_variants} variants, "
          f"{with_body} with body copy")
    for it in items:
        print(f"  - {it['slug']:<28} Rs.{it['priceMinor'] / 100:>9.2f}  "
              f"variants={len(it['variants']):>2}  tagline={len(it['tagline']):>3}c  "
              f"body={len(it['body'])}p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
