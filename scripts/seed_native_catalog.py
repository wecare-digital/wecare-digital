#!/usr/bin/env python3
"""Seed real native-catalogue product rows for the product pages that still fall back to the
₹1 placeholder at checkout, then print ready-to-paste PRODUCT_CHECKOUT entries.

WHY THIS EXISTS
    Creates fresh native catalog rows through the staff admin API.

    It must only be used with the current SKU-first seed data. There is no placeholder checkout
    fallback and no retired product mapping to restore.

AUTH
    The admin routes (POST/PATCH /native-catalog/products…) are gated to the STAFF Cognito
    Admin group, so this must run with a staff access token. Pass it with --token <JWT> or set
    WECARE_STAFF_TOKEN. The sandbox has no staff token, so run this from a trusted machine.

SAFETY
    Dry-run by default: prints the exact create payloads and does nothing. Pass --apply to POST.
    New rows are created status:draft with channels OFF (the admin API enforces this). To make a
    product buyable AND visible, set its catalogImageKey in the seed JSON (an approved
    *-4096.png under wd-catalog-live/) and pass --activate; the script then PATCHes
    status:active + websiteEnabled:true. Without --activate the row stays draft (still priceable
    for checkout, just not on /shop/).

USAGE
    python scripts/seed_native_catalog.py                      # dry-run, all products with a price set
    python scripts/seed_native_catalog.py --apply --token JWT  # create the rows
    python scripts/seed_native_catalog.py --apply --activate --token JWT   # create + publish (needs images)
    python scripts/seed_native_catalog.py --only grahak-os     # just one product
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "scripts" / "native_catalog_seed_products.json"
# The staff API base. Override with --api-base if the stage/domain differs.
DEFAULT_API_BASE = "https://wecare.digital/api"
CREATE_PATH = "/native-catalog/products"


def load_seed() -> list[dict]:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return list(data.get("products") or [])


def rupees(paise: int) -> str:
    return "\u20B9" + f"{paise / 100:.2f}"


def create_payload(p: dict) -> dict:
    """Build the POST body the admin API's _create expects."""
    return {
        "title": p["title"],
        "slug": p["slug"],
        "currency": "INR",
        "canonicalPath": p.get("canonicalPath") or f"/shop/{p['slug']}/",
        "variants": [
            {
                "label": p.get("variantLabel") or "Standard",
                "priceMinor": p["priceMinor"],
                "inventory": 0,
            }
        ],
    }


def http_json(method: str, url: str, token: str, body: dict | None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def checkout_snippet(slug: str, name: str, product_id: str, variant_id: str, paise: int) -> str:
    return (
        f"  '{slug}': {{\n"
        f"    productId: '{product_id}',\n"
        f"    variantId: '{variant_id}',\n"
        f"    name: '{name}',\n"
        f"    slug: '{slug}',\n"
        f"    formattedPrice: '{rupees(paise)}',\n"
        f"  }},"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually POST (default: dry-run)")
    ap.add_argument("--activate", action="store_true",
                    help="also PATCH status:active + websiteEnabled (needs catalogImageKey)")
    ap.add_argument("--token", default=os.environ.get("WECARE_STAFF_TOKEN", ""),
                    help="staff Cognito access token (or set WECARE_STAFF_TOKEN)")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--only", default="", help="limit to a single slug")
    args = ap.parse_args()

    products = load_seed()
    if args.only:
        products = [p for p in products if p["slug"] == args.only]
        if not products:
            print(f"No seed entry for slug '{args.only}'", file=sys.stderr)
            return 2

    priced = [p for p in products if isinstance(p.get("priceMinor"), int)]
    missing = [p["slug"] for p in products if not isinstance(p.get("priceMinor"), int)]
    if missing:
        print("SKIPPING (no priceMinor set yet in native_catalog_seed_products.json):")
        for slug in missing:
            print(f"  - {slug}")
        print()
    if not priced:
        print("Nothing to do — set priceMinor (integer paise) for at least one product.")
        return 1

    if args.apply and not args.token:
        print("ERROR: --apply needs a staff token (--token or WECARE_STAFF_TOKEN).", file=sys.stderr)
        return 2

    snippets: list[str] = []
    for p in priced:
        payload = create_payload(p)
        print(f"=== {p['slug']}  ({rupees(p['priceMinor'])}) ===")
        if not args.apply:
            print("  DRY-RUN create payload:")
            print("    " + json.dumps(payload))
            if args.activate and not p.get("catalogImageKey"):
                print("  NOTE: --activate requested but catalogImageKey is empty; this product "
                      "would stay draft (publication needs an approved image).")
            print()
            continue

        status, resp = http_json("POST", args.api_base + CREATE_PATH, args.token, payload)
        if status not in (200, 201):
            print(f"  CREATE FAILED (HTTP {status}): {resp}")
            print()
            continue
        product = resp.get("product") or {}
        product_id = product.get("id", "")
        variant_id = ""
        variants = product.get("variants") or []
        if variants:
            variant_id = variants[0].get("sku") or variants[0].get("id") or ""
        print(f"  created product id={product_id} variant sku={variant_id} status={product.get('status')}")

        if args.activate:
            if not p.get("catalogImageKey"):
                print("  activate skipped: no catalogImageKey set (publication needs one).")
            else:
                patch = {
                    "expectedUpdatedAt": product.get("updatedAt"),
                    "status": "active",
                    "catalogImageKey": p["catalogImageKey"],
                    "websiteEnabled": True,
                }
                ps, pr = http_json("PATCH", f"{args.api_base}{CREATE_PATH}/{product_id}",
                                   args.token, patch)
                print(f"  activate -> HTTP {ps}: {pr.get('product', pr).get('status', pr) if isinstance(pr, dict) else pr}")

        snippets.append(checkout_snippet(p["slug"], p["title"], product_id, variant_id, p["priceMinor"]))
        print()

    if snippets:
        print("\n" + "=" * 72)
        print("Paste these into PRODUCT_CHECKOUT in src/config/productCheckout.ts:")
        print("=" * 72)
        print("\n".join(snippets))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
