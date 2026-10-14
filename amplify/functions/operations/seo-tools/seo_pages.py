"""Native page/product SEO reads for the Admin SEO tools (Wix exit).

Replaces the four `wix.*` calls the SEO handler used to make. There is no Wix site
to read from any more, so each reads a native source:

  page_seo(path)       -> the public page's own SEO shape; the Wix Velo
                          `/_functions/seohead` endpoint is gone, so this returns the
                          native empty shape unless a native SEO record exists in storage.
  list_site_pages()    -> the committed public-pages catalog (never came from Wix).
  list_products()      -> the native ProductsTable (the Wix store was deleted).
  clear_blog_cache()   -> no-op; the blog is served from DynamoDB (storage), which has
                          no per-sandbox Wix cache to purge.

Read-only. No Wix host, SDK, credential or flag appears here.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import boto3

SITE_BASE = os.environ.get("PUBLIC_SITE_URL", "https://wecare.digital").rstrip("/")
PRODUCTS_TABLE = os.environ.get("PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def public_page_catalog() -> List[Dict[str, Any]]:
    """The same generated catalogue the public site and MCP publish (local JSON)."""
    packaged = Path(__file__).resolve().parent / "public-pages.json"
    repository = Path(__file__).resolve().parents[4] / "config" / "public-pages.json"
    catalog = packaged if packaged.is_file() else repository
    return json.loads(catalog.read_text(encoding="utf-8"))["pages"]


def page_seo(path: str) -> Dict[str, Any]:
    """SEO head for a page. The Wix Velo seohead endpoint was retired with the site, so
    there is no live per-page SEO service to read. Return the native empty shape; the
    audit tool treats this as "no custom SEO declared", which is now the truth for pages
    served by the static Next.js export (their SEO lives in the page source, not a CMS)."""
    return {
        "title": "",
        "metaDescription": "",
        "keywords": [],
        "jsonLdTypes": [],
        "hasJsonLd": False,
        "canonical": SITE_BASE + path if path.startswith("/") else SITE_BASE + "/" + path,
    }


def list_site_pages() -> List[Dict[str, Any]]:
    """Current published pages from the committed catalogue (never a Wix inventory)."""
    return [
        {
            "path": page["path"], "name": page["name"], "type": page["group"],
            "url": SITE_BASE + page["path"], "title": page["name"],
            "metaDescription": page["description"], "keywords": [],
            "jsonLdTypes": [], "hasJsonLd": False,
            "canonical": SITE_BASE + page["path"],
        }
        for page in public_page_catalog()
    ]


def _products_table():
    return boto3.resource("dynamodb", region_name=REGION).Table(PRODUCTS_TABLE)


def list_products() -> List[Dict[str, Any]]:
    """Products from the native ProductsTable (the Wix store was deleted).

    Projects each row into the same shape the SEO handler's /product-pages consumers
    already expect from the old `wix.list_products()`."""
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    table = _products_table()
    while True:
        resp = table.scan(**kwargs)  # catalogue is small; a scan is acceptable
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    products: List[Dict[str, Any]] = []
    for p in items:
        if str(p.get("status", "active")) == "archived":
            continue
        price_minor = p.get("priceMinor") or 0
        if isinstance(price_minor, Decimal):
            price_minor = int(price_minor)
        amount = f"{Decimal(int(price_minor)) / Decimal(100):.2f}" if price_minor else ""
        slug = str(p.get("slug", ""))
        images = p.get("imageRefs") or []
        inventory = p.get("inventory") or 0
        if isinstance(inventory, Decimal):
            inventory = int(inventory)
        variant_in_stock = any(
            int(v.get("M", {}).get("inventory", {}).get("N", 0)
                if isinstance(v, dict) and "M" in v else (v.get("inventory") or 0)) > 0
            for v in (p.get("variants") or [])
        )
        products.append({
            "id": str(p.get("id", "")),
            "name": str(p.get("title") or p.get("name") or ""),
            "slug": slug,
            "url": f"{SITE_BASE}/shop/{slug}/" if slug else SITE_BASE + "/shop/",
            "description": str(p.get("tagline") or "")[:200],
            "price": f"INR {amount}".strip() if amount else "",
            "priceAmount": amount or 0,
            "currency": str(p.get("currency", "INR")),
            "inStock": bool(inventory) or variant_in_stock,
            "image": str(images[0]) if images else "",
            "type": str(p.get("productType", "")).lower(),
            "hasJsonLd": False, "jsonLdType": "",
        })
    return products


def clear_blog_cache() -> None:
    """No-op. The public blog is served from DynamoDB (storage); there is no Wix
    per-sandbox cache to purge now that the Wix blog read path is gone."""
    return None
