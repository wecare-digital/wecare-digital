"""Provider-neutral public page and product catalog for SEO tooling.

The SEO Lambda audits the same static page inventory and storefront snapshot that the
public Next.js export publishes. No provider network call or credential is involved.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

SITE_BASE = "https://wecare.digital"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_json(packaged_name: str, repository_path: str) -> Dict[str, Any]:
    packaged = Path(__file__).resolve().parent / packaged_name
    repository = _repo_root() / repository_path
    path = packaged if packaged.is_file() else repository
    return json.loads(path.read_text(encoding="utf-8"))


def public_page_catalog() -> List[Dict[str, Any]]:
    return list(_load_json("public-pages.json", "config/public-pages.json").get("pages") or [])


def product_catalog() -> List[Dict[str, Any]]:
    """No legacy Shop snapshot is published. Fresh SKU-first products will be wired separately."""
    return []


def _plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def _product_path(slug: str) -> str:
    return f"/shop/{slug.strip('/')}/"


def page_seo(path: str) -> Dict[str, Any]:
    """SEO metadata from the public build inputs, never from an upstream CMS."""
    wanted = "/" + str(path or "").strip("/")
    if wanted != "/":
        wanted += "/"
    for page in public_page_catalog():
        candidate = "/" + str(page.get("path") or "").strip("/")
        if candidate != "/":
            candidate += "/"
        if candidate == wanted:
            return {
                "title": str(page.get("name") or ""),
                "metaDescription": str(page.get("description") or ""),
                "keywords": [],
                "jsonLdTypes": [],
                "hasJsonLd": False,
                "canonical": SITE_BASE + candidate,
            }
    if wanted.startswith("/shop/"):
        slug = wanted[len("/shop/"):].strip("/")
        for product in product_catalog():
            if str(product.get("slug") or "").strip("/") == slug:
                description = _plain(
                    product.get("tagline") or product.get("descriptionHtml") or ""
                )
                return {
                    "title": str(product.get("name") or slug),
                    "metaDescription": description[:320],
                    "keywords": [],
                    "jsonLdTypes": ["Product"],
                    "hasJsonLd": True,
                    "canonical": SITE_BASE + _product_path(slug),
                }
    return {}


def list_site_pages() -> List[Dict[str, Any]]:
    return [
        {
            "path": page["path"],
            "name": page["name"],
            "type": page["group"],
            "url": SITE_BASE + page["path"],
            "title": page["name"],
            "metaDescription": page["description"],
            "keywords": [],
            "jsonLdTypes": [],
            "hasJsonLd": False,
            "canonical": SITE_BASE + page["path"],
        }
        for page in public_page_catalog()
    ]


def list_products() -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    for product in product_catalog():
        slug = str(product.get("slug") or "").strip("/")
        image = str(product.get("image") or "")
        variants = product.get("variants") or []
        products.append({
            "id": str(product.get("id") or ""),
            "name": str(product.get("name") or ""),
            "slug": slug,
            "url": SITE_BASE + _product_path(slug),
            "description": _plain(
                product.get("tagline") or product.get("descriptionHtml") or ""
            )[:200],
            "price": str(product.get("formattedPrice") or product.get("price") or ""),
            "priceAmount": product.get("price") or 0,
            "currency": str(product.get("currency") or "INR"),
            "inStock": bool(product.get("inStock", True)),
            "image": image,
            "type": "native",
            "hasJsonLd": True,
            "jsonLdType": "Product",
            "variantCount": len(variants),
        })
    return products
