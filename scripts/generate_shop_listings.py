#!/usr/bin/env python3
"""Generate the website Shop listing (`src/content/shopProducts.ts`) from ProductsTable.

PURPOSE
-------
The /shop/ listing and the Meta / WhatsApp catalog must publish the same five fields for every
product: title, description, INR price, catalog image URL and canonical website link. Meta gets
them from `wecare-meta-catalog-sync`, which projects ProductsTable rows through
`lambda_utils/ecommerce/meta_catalog_sync.desired_items`. This script runs THAT SAME FUNCTION over
the same rows and writes the result as the website release snapshot, so the two channels cannot
drift through a hand-edited copy list. It is the only writer of `src/content/shopProducts.ts`.

AUTHORITY
---------
Read-only. The input is a DynamoDB JSON scan of ProductsTable (the catalog authority); this
script makes no network call and never writes ProductsTable, S3 or Meta. Product edits belong to
the authenticated native catalog admin; this only re-projects what is already there.

    aws dynamodb scan --table-name stack-wecare-digital-ProductsTable \
        --region us-east-1 --output json > /tmp/products-scan.json
    python3 scripts/generate_shop_listings.py --scan-json /tmp/products-scan.json          # write
    python3 scripts/generate_shop_listings.py --scan-json /tmp/products-scan.json --check  # gate

FAIL-CLOSED RULES
-----------------
* Only rows with `status == "active"` and `websiteEnabled is True` are listed.
* One variant per listed product: a listing card shows one SKU and one price, and multi-variant
  products (for example historical Merchandise sizes) need an explicit owner reconciliation.
* Artwork must use a canonical `secure/d/public/catalog-deploy/catalog/products/` key delivered
  through `/api/catalog-media/<same filename>`. An imageless product is listed only when it is
  explicitly kept off the image shelf (`OFF_SHELF_SLUGS`).
* Every listed slug needs a deliberate place in `SHELF_ORDER`, which mirrors the approved
  artwork manifest order (`catalog/catalog-v3-final-manifest.json`).
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "content" / "shopProducts.ts"
PROJECTION_MODULE = (
    ROOT / "amplify" / "functions" / "shared" / "lambda_utils" / "ecommerce" / "meta_catalog_sync.py"
)

ORIGIN = "https://wecare.digital"
CANONICAL_IMAGE_PREFIX = "secure/d/public/catalog-deploy/catalog/products/"
CATALOG_MEDIA_BASE = f"{ORIGIN}/api/catalog-media/"

#: Approved shelf order: the artwork manifest's `order`, then imageless off-shelf rows.
SHELF_ORDER: tuple[str, ...] = (
    "grahak-os", "vayulok", "sehat",
    "elsewhere-visa", "elsewhere-trip", "elsewhere-activities",
    "expo-week",
    "dastavez-drafting", "dastavez-registration", "dastavez-legal-reference",
    "guided-resolution", "file-assist", "paperwork",
    "ritual-guru-puja-guidance", "ritual-guru-diy-puja-kit", "ritual-guru-ritva",
    "anew", "hunar-kaushal", "hunar-prastuti", "niji-setu",
    "submit-request", "request-amendment", "drop-docs", "vault",
    "shipments-track", "request-pickup",
    "merchandise", "kiosk",
    "contribute",
)

#: Live, purchasable rows kept off the horizontal image rail (owner rule: Contribute).
OFF_SHELF_SLUGS: frozenset[str] = frozenset({"contribute"})

# These six items remain live paid products in ProductsTable (SKU, pricing and
# fulfilment are unchanged), but the five standalone service pages are retired.
# Website browsing must always take customers to the authenticated Orders hub.
# This frontend-only override is necessary until the ProductsTable canonicalPath
# values are reconciled; otherwise regenerating shopProducts.ts resurrects old URLs.
ORDER_HUB_SERVICE_SLUGS: frozenset[str] = frozenset({
    "submit-request", "request-amendment", "drop-docs", "vault",
    "shipments-track", "request-pickup",
})

HEADER = """/** Generated Shop publication projection from the live ProductsTable catalog fields.
 *
 * DO NOT EDIT BY HAND. Regenerate with scripts/generate_shop_listings.py, which runs the same
 * ProductsTable projection wecare-meta-catalog-sync publishes to Meta, so title, description,
 * INR price, image URL and canonical page link stay identical on both channels. Keep this file
 * as the website-side release snapshot only; do not add catalog artwork to individual
 * product/detail/service pages.
 */
export interface ShopListing {
  slug: string;
  name: string;
  blurb: string;
  sku?: string;
  href: string;
  formattedPrice?: string;
  image?: string;
  /** Defaults to true. False keeps a live product and route off the horizontal /shop/ rail. */
  showOnShopShelf?: boolean;
  source: 'product' | 'catalogue';
}

export const SHOP_LISTINGS: ShopListing[] = [
"""

FOOTER = """];

export const SHOP_LISTINGS_PER_PAGE = 6;
export const shopListingPageCount = ( total: number ): number =>
  Math.max( 1, Math.ceil( total / SHOP_LISTINGS_PER_PAGE ) );
export const shopListingPageHref = ( page: number ): string =>
  ( page <= 1 ? '/shop/' : `/shop/page/${page}/` );
"""


class ProjectionError(ValueError):
    """A ProductsTable row cannot be published on the Shop listing as it stands."""


def load_projection() -> ModuleType:
    """Load the pure Meta projection module by path.

    Importing it through the `lambda_utils` package would pull in Lambda runtime dependencies
    (boto3) that a build machine may not have; the module itself only uses the standard library.
    It is registered in `sys.modules` before execution because its dataclass resolves its own
    module there.
    """
    spec = importlib.util.spec_from_file_location("meta_catalog_sync", PROJECTION_MODULE)
    if spec is None or spec.loader is None:
        raise ProjectionError(f"cannot load {PROJECTION_MODULE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _attr(value: dict[str, Any]) -> Any:
    """One DynamoDB JSON attribute value -> a Python value (the AWS CLI scan shape)."""
    (kind, raw), = value.items()
    if kind == "S":
        return raw
    if kind == "N":
        number = Decimal(raw)
        return int(number) if number == number.to_integral_value() else number
    if kind == "BOOL":
        return bool(raw)
    if kind == "NULL":
        return None
    if kind == "M":
        return {key: _attr(item) for key, item in raw.items()}
    if kind == "L":
        return [_attr(item) for item in raw]
    if kind in ("SS", "NS", "BS"):
        return list(raw)
    raise ProjectionError(f"unsupported DynamoDB attribute type {kind}")


def read_scan(path: str) -> list[dict[str, Any]]:
    try:
        if path == "-":
            payload = json.load(sys.stdin)
        else:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionError(f"cannot read the ProductsTable scan: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
        raise ProjectionError("the input is not an AWS CLI `dynamodb scan --output json` result")
    if payload.get("LastEvaluatedKey") or payload.get("NextToken"):
        raise ProjectionError("the scan is paginated/truncated; re-run it to completion")
    return [{key: _attr(value) for key, value in item.items()} for item in payload["Items"]]


def projection_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one ProductsTable row exactly as `wecare-meta-catalog-sync._native_products` does."""
    variants = []
    for variant in row.get("variants") or []:
        shaped: dict[str, Any] = {
            "id": str(variant.get("sku") or variant.get("id") or ""),
            "label": str(variant.get("label") or ""),
            "inStock": True,
        }
        if variant.get("priceMinor") is not None:
            shaped["pricePaise"] = int(variant["priceMinor"])
        variants.append(shaped)
    shaped_row: dict[str, Any] = {
        "id": str(row.get("id") or ""),
        "name": str(row.get("title") or row.get("name") or ""),
        "slug": str(row.get("slug") or ""),
        "visible": True,
        "price": f"{Decimal(int(row.get('priceMinor') or 0)) / Decimal(100):.2f}",
        "currency": str(row.get("currency") or "INR"),
        "descriptionHtml": str(row.get("descriptionHtml") or row.get("tagline") or ""),
        "variants": variants,
        "canonicalPath": str(row.get("canonicalPath") or ""),
    }
    images = row.get("imageRefs") or []
    if images:
        shaped_row["image"] = str(images[0])
    return shaped_row


def inr(price_text: str) -> str:
    """`"26999.00"` -> `"₹26,999.00"`, with en-IN (lakh) digit grouping."""
    rupees, paise = price_text.split(".")
    if len(rupees) > 3:
        head, groups = rupees[:-3], [rupees[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        rupees = ",".join(groups)
    return f"₹{rupees}.{paise}"


def listing_for(row: dict[str, Any], projection: ModuleType) -> dict[str, Any]:
    slug = str(row.get("slug") or "")
    shaped = projection_row(row)
    try:
        items = projection.desired_items([shaped], require_variant_price=True)
    except ValueError as error:  # unpriced variant or unrepresentable retailer id
        raise ProjectionError(f"{slug}: {error}") from error
    # A variant-less row projects to no item, so this also refuses it before any SKU read.
    if len(items) != 1 or len(shaped["variants"]) != 1:
        raise ProjectionError(f"{slug}: expected exactly one variant, found {len(items)}")
    item = items[0]
    if item.get("currency") != "INR":
        raise ProjectionError(f"{slug}: currency {item.get('currency')!r} is not INR")
    url = str(item.get("url") or "")
    if not url.startswith(ORIGIN + "/"):
        raise ProjectionError(f"{slug}: canonical link {url!r} is not on {ORIGIN}")

    listing: dict[str, Any] = {
        "slug": slug,
        "name": item["name"],
        "blurb": item["description"],
        # The same variant identity Meta's retailer id carries (sku, else id).
        "sku": shaped["variants"][0]["id"],
        "href": "/orders/" if slug in ORDER_HUB_SERVICE_SLUGS else url[len(ORIGIN):],
        "formattedPrice": inr(item["price"]),
    }
    image = str(item.get("image_url") or "")
    key = str(row.get("catalogImageKey") or "")
    if image or key:
        filename = key[len(CANONICAL_IMAGE_PREFIX):]
        if not key.startswith(CANONICAL_IMAGE_PREFIX) or not filename or "/" in filename:
            raise ProjectionError(f"{slug}: catalogImageKey {key!r} is not a canonical master")
        if image.split("?", 1)[0] != CATALOG_MEDIA_BASE + filename:
            raise ProjectionError(f"{slug}: image {image!r} is not the catalog-media URL for {key}")
        listing["image"] = image
    elif slug not in OFF_SHELF_SLUGS:
        raise ProjectionError(f"{slug}: no approved catalog artwork for an on-shelf listing")
    if slug in OFF_SHELF_SLUGS:
        listing["showOnShopShelf"] = False
    listing["source"] = "product"
    return listing


def ts_string(value: str) -> str:
    escaped = (value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return f"'{escaped}'"


def render(listings: list[dict[str, Any]]) -> str:
    lines = []
    for listing in listings:
        fields = []
        for key, value in listing.items():
            literal = ("true" if value else "false") if isinstance(value, bool) else ts_string(str(value))
            fields.append(f"{key}:{literal}")
        lines.append("  { " + ", ".join(fields) + " },\n")
    return HEADER + "".join(lines) + FOOTER


def build(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[str]]:
    projection = load_projection()
    listed = [r for r in rows if r.get("status") == "active" and r.get("websiteEnabled") is True]
    skipped = [f"{r.get('slug')} (status={r.get('status')}, websiteEnabled={r.get('websiteEnabled')})"
               for r in rows if r not in listed]
    unplaced = sorted(str(r.get("slug")) for r in listed if r.get("slug") not in SHELF_ORDER)
    if unplaced:
        raise ProjectionError(f"add a deliberate SHELF_ORDER place for: {', '.join(unplaced)}")
    slugs = [str(r.get("slug")) for r in listed]
    if len(set(slugs)) != len(slugs):
        raise ProjectionError("duplicate slugs among listed products")
    if "page" in slugs:
        raise ProjectionError("a product slugged 'page' would collide with /shop/page/N/")
    listed.sort(key=lambda r: SHELF_ORDER.index(str(r.get("slug"))))
    listings = [listing_for(row, projection) for row in listed]
    return render(listings), listings, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--scan-json", required=True,
                        help="AWS CLI `dynamodb scan --output json` of ProductsTable, or - for stdin")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when src/content/shopProducts.ts differs from ProductsTable")
    args = parser.parse_args()

    try:
        text, listings, skipped = build(read_scan(args.scan_json))
    except ProjectionError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    on_shelf = [x for x in listings if x.get("showOnShopShelf") is not False]
    print(f"listings={len(listings)} onShelf={len(on_shelf)} "
          f"withImage={sum(1 for x in listings if x.get('image'))} skipped={len(skipped)}")
    for line in skipped:
        print(f"  not listed: {line}")

    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    if args.check:
        if current == text:
            print(f"OK: {OUTPUT.relative_to(ROOT)} matches ProductsTable")
            return 0
        diff = difflib.unified_diff(current.splitlines(), text.splitlines(),
                                    "committed", "ProductsTable", lineterm="", n=0)
        print("\n".join(list(diff)[:80]))
        print(f"DRIFT: {OUTPUT.relative_to(ROOT)} does not match ProductsTable", file=sys.stderr)
        return 1
    if current != text:
        OUTPUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
    else:
        print(f"unchanged {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
