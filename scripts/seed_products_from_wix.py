#!/usr/bin/env python3
"""Seed ProductsTable from the Wix storefront, using the ANONYMOUS VISITOR TOKEN.

WHY VISITOR TOKEN, NOT ADMIN KEY. The Wix admin key (`wecare/wix/headless-api-key`)
was scheduled for deletion on 2026-10-14, so admin reads (orders, inventory writes)
are gone. But the STOREFRONT CATALOG is still readable with the public visitor
token (the same path `scripts/fetch-wix-catalog.js` uses) — product id, name,
slug, price, currency, inventory, media, variants. That is exactly what the
AWS-native catalog needs, so this script recovers the catalog without the admin
key.

It maps each Wix product onto the `ProductsTable` item shape used by
`catalog_pricing`/`native_cart`/`meta-catalog-sync`, PRESERVING THE WIX UUID as
the item `id` and variant `sku`/`id` (the Meta retailer-id contract requires
UUIDs). priceMinor is integer paise via Decimal (never float).

SAFETY. Default is --dry: it reads Wix (read-only) and prints the mapped items,
writing NOTHING. `--apply` writes to ProductsTable and requires the table to exist
(a billable resource an owner must provision first) plus
CONFIRM=I-APPROVE-seed-products. Historical orders are NOT seeded here (they live
in the AWS OrderTable already and were never Wix-authoritative).

Usage:
    python scripts/seed_products_from_wix.py --dry
    python scripts/seed_products_from_wix.py --dry --out outputs/products-seed.json
    CONFIRM=I-APPROVE-seed-products python scripts/seed_products_from_wix.py --apply   # 🔒
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

WIX_API = "https://www.wixapis.com"
CLIENT_ID = os.environ.get("WIX_CLIENT_ID", "42b3cdbf-d90e-4138-a06c-ddda4fb8da01")
SITE = os.environ.get("WIX_SITE_ID", "c993128b-26be-41cd-9fcd-904abe23462f")
PRODUCTS_TABLE = os.environ.get("PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")
FIELDS = ["URL", "CURRENCY", "MEDIA_ITEMS_INFO", "PLAIN_DESCRIPTION",
          "DIRECT_CATEGORIES_INFO", "VARIANT_OPTION_CHOICE_NAMES", "INFO_SECTION"]


def _visitor_token() -> str:
    req = urllib.request.Request(
        f"{WIX_API}/oauth2/token",
        data=json.dumps({"clientId": CLIENT_ID, "grantType": "anonymous"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())["access_token"]


def _read_products(token: str) -> List[Dict[str, Any]]:
    products, cursor = [], ""
    for _ in range(50):
        paging = {"limit": 100}
        if cursor:
            paging = {"cursor": cursor}
        req = urllib.request.Request(
            f"{WIX_API}/stores/v3/products/search",
            data=json.dumps({"search": {"cursorPaging": paging}, "fields": FIELDS}).encode(),
            headers={"Authorization": token, "wix-site-id": SITE,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        products.extend(d.get("products", []) or [])
        cursor = (((d.get("pagingMetadata") or {}).get("cursors") or {}).get("next") or "")
        if not cursor:
            break
    return products


def _read_variants(token: str, product_id: str) -> List[Dict[str, Any]]:
    # Correct Wix V3 shape (matches meta-catalog-sync._wix_variants): filter on
    # productData.productId with $in, request CURRENCY, read variantId + actualPrice.
    req = urllib.request.Request(
        f"{WIX_API}/stores/v3/products/query-variants",
        data=json.dumps({"fields": ["CURRENCY"],
                         "query": {"filter": {"productData.productId": {"$in": [product_id]}},
                                   "cursorPaging": {"limit": 1000}}}).encode(),
        headers={"Authorization": token, "wix-site-id": SITE,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("variants", []) or []
    except Exception:  # noqa: BLE001
        return []


def _paise(amount_str: Any) -> int:
    if amount_str in (None, ""):
        return 0
    whole, _, frac = str(amount_str).partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def map_product(p: Dict[str, Any], token: str) -> Dict[str, Any]:
    pid = str(p.get("id") or "")
    rng = (p.get("actualPriceRange") or {}).get("minValue") or {}
    price_minor = _paise(rng.get("amount"))
    media = (((p.get("media") or {}).get("itemsInfo") or {}).get("items") or [])
    image_refs = []
    for m in media:
        u = str(((m.get("image") or {}).get("url") if isinstance(m.get("image"), dict)
                 else m.get("url")) or "").strip()
        if u:
            image_refs.append(u)
    variants = []
    for v in _read_variants(token, pid):
        if v.get("visible") is False:
            continue
        vid = str(v.get("variantId") or v.get("id") or "")
        vprice = ((v.get("price") or {}).get("actualPrice") or {}).get("amount")
        label = " / ".join(
            str((c.get("optionChoiceNames") or {}).get("choiceName") or "")
            for c in (v.get("optionChoices") or [])
            if (c.get("optionChoiceNames") or {}).get("choiceName"))
        variants.append({
            "sku": vid,
            "label": label,
            "priceMinor": _paise(vprice) if vprice is not None else price_minor,
            "inventory": 1 if ((v.get("inventoryStatus") or {}).get("inStock") is True) else 0,
        })
    return {
        "id": pid,                                   # preserve Wix UUID (retailer-id contract)
        "sourceId": pid,
        "title": str(p.get("name") or ""),
        "slug": str(p.get("slug") or ""),
        "priceMinor": price_minor,
        "currency": str(p.get("currency") or "INR"),
        "inventory": int((p.get("inventory") or {}).get("quantity") or 0)
                     if isinstance(p.get("inventory"), dict) else 0,
        "status": "active" if p.get("visible") is not False else "archived",
        "categories": [c.get("id") for c in (p.get("directCategoriesInfo") or {}).get("categories", [])
                       if isinstance(c, dict)] if p.get("directCategoriesInfo") else [],
        "imageRefs": image_refs,
        "tagline": str(p.get("plainDescription") or "")[:200],
        "descriptionHtml": str(p.get("plainDescription") or ""),
        "variants": variants,
        "updatedAt": str(p.get("updatedDate") or ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true", help="🔒 write to ProductsTable")
    ap.add_argument("--out", type=Path, help="also write the mapped items to a JSON file")
    args = ap.parse_args()

    token = _visitor_token()
    raw = _read_products(token)
    items = [map_product(p, token) for p in raw]
    items.sort(key=lambda it: it["slug"])

    summary = {"read": len(raw), "mapped": len(items),
               "with_uuid_id": sum(1 for i in items if len(i["id"]) == 36),
               "total_variants": sum(len(i["variants"]) for i in items)}
    print(json.dumps({"mode": "apply" if args.apply else "dry", "summary": summary}, indent=2))
    for it in items:
        print(f"  - {it['slug']:<28} {it['id']}  Rs.{it['priceMinor']/100:.2f}  "
              f"variants={len(it['variants'])}  status={it['status']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(items, indent=2))
        print(f"wrote {args.out}")

    if args.apply:
        if os.environ.get("CONFIRM") != "I-APPROVE-seed-products":
            print("REFUSED: --apply needs CONFIRM=I-APPROVE-seed-products", file=sys.stderr)
            return 2
        import boto3
        table = boto3.resource("dynamodb", region_name=REGION).Table(PRODUCTS_TABLE)
        for it in items:
            # Decimal for DynamoDB numeric fields
            it = json.loads(json.dumps(it), parse_int=Decimal, parse_float=Decimal)
            table.put_item(Item=it)
        print(f"WROTE {len(items)} products to {PRODUCTS_TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
