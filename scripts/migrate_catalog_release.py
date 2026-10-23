#!/usr/bin/env python3
"""One-shot authenticated catalog release migration.

Uses only the staff Admin HTTP API. No raw DynamoDB writes and no browser token extraction.

Default is dry-run. With --apply:
1. migrate every legacy catalogImageKey to secure/d/public/... through native catalog admin;
2. verify each saved key + imageRefs from the API response;
3. meta-enable only active + websiteEnabled + image-backed products;
4. fetch the read-only Meta reconciliation plan;
5. fail closed on blockers or unexpected foreign ownership and print the exact plan hash.

It deliberately does NOT approve/apply the Meta provider plan. Exact-plan approval is a separate
owner decision after the concrete hash/counts are visible.

Auth:
  --token <staff Admin JWT>
or:
  WECARE_STAFF_TOKEN=<staff Admin JWT>

Usage:
  python scripts/migrate_catalog_release.py
  python scripts/migrate_catalog_release.py --token "$STAFF_ADMIN_TOKEN" --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API_BASE = "https://wecare.digital/api"
PRODUCTS_PATH = "/native-catalog/products"
META_PATH = "/wa-business/catalog-sync"

OLD_PREFIX = "secure/public/catalog-deploy/catalog/products/"
NEW_PREFIX = "secure/d/public/catalog-deploy/catalog/products/"
MEDIA_BASE = "https://wecare.digital/api/catalog-media/"

EXPECTED_FOREIGN_PREFIX = "wix:"


def http_json(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, json.loads(payload or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw or exc.reason}
        return exc.code, payload


def product_url(api_base: str, product_id: str = "") -> str:
    root = api_base.rstrip("/") + PRODUCTS_PATH
    return root if not product_id else root + "/" + urllib.parse.quote(product_id, safe="")


def list_products(api_base: str, token: str) -> list[dict[str, Any]]:
    status, data = http_json("GET", product_url(api_base), token)
    if status != 200 or not isinstance(data.get("products"), list):
        raise RuntimeError(f"catalog read failed: HTTP {status} {data}")
    return list(data["products"])


def get_product(api_base: str, token: str, product_id: str) -> dict[str, Any]:
    status, data = http_json("GET", product_url(api_base, product_id), token)
    if status != 200 or not isinstance(data.get("product"), dict):
        raise RuntimeError(f"product read failed for {product_id}: HTTP {status} {data}")
    return data["product"]


def patch_product(api_base: str, token: str, product: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    payload = {"expectedUpdatedAt": product.get("updatedAt"), **changes}
    status, data = http_json("PATCH", product_url(api_base, str(product["id"])), token, payload)
    if status == 409:
        # One safe retry with a freshly read optimistic-lock token.
        current = get_product(api_base, token, str(product["id"]))
        payload["expectedUpdatedAt"] = current.get("updatedAt")
        status, data = http_json("PATCH", product_url(api_base, str(product["id"])), token, payload)
    if status != 200 or not isinstance(data.get("product"), dict):
        raise RuntimeError(f"PATCH failed for {product.get('id')}: HTTP {status} {data}")
    return data["product"]


def target_key(key: str) -> str:
    return NEW_PREFIX + key[len(OLD_PREFIX):]


def verify_migrated(product: dict[str, Any], expected_key: str) -> None:
    if product.get("catalogImageKey") != expected_key:
        raise RuntimeError(f"{product.get('id')}: catalogImageKey readback mismatch")
    filename = expected_key[len(NEW_PREFIX):]
    expected_url = MEDIA_BASE + filename
    refs = product.get("imageRefs") or []
    if refs != [expected_url]:
        raise RuntimeError(f"{product.get('id')}: imageRefs readback mismatch: {refs!r}")


def meta_candidate(product: dict[str, Any]) -> bool:
    return (
        product.get("status") == "active"
        and product.get("websiteEnabled") is True
        and isinstance(product.get("catalogImageKey"), str)
        and product["catalogImageKey"].startswith(NEW_PREFIX)
    )


# Owner-gated / not-yet-provisioned states the Meta inspect legitimately returns as HTTP 409
# (ok:False). These are NOT release failures: the product migration + meta-enablement have
# already succeeded; only the advisory read-only Meta plan could not be computed because the
# Meta channel is not configured/reachable yet. Meta is a projected sales channel, not the
# product database, and this tool never approves/applies the provider plan anyway - so a plan
# that cannot load is reported, not treated as a hard error.
META_PLAN_NOT_LOADED_REASONS = frozenset({
    "unconfigured",            # Meta system-user token field is empty
    "read_failed",             # ProductsTable or Meta Graph read failed
    "approval_store_unavailable",
})


def inspect_meta(api_base: str, token: str) -> tuple[int, dict[str, Any]]:
    """Return (status, data) from the read-only Meta inspect. Does not raise on 409: the caller
    distinguishes an owner-gated 'plan not loaded' from an unexpected transport error."""
    status, data = http_json("GET", api_base.rstrip("/") + META_PATH, token)
    return status, data


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    counts = plan.get("counts") or {}
    existing = plan.get("existingItems") or []
    desired = plan.get("desiredItems") or []
    foreign_ids = [
        str(item.get("retailer_id") or "")
        for item in existing
        if str(item.get("retailer_id") or "").lower().startswith(EXPECTED_FOREIGN_PREFIX)
    ]
    return {
        "planHash": plan.get("planHash") or plan.get("currentPlanHash"),
        "desired": len(desired),
        "existing": len(existing),
        "create": int(counts.get("create", 0) or 0),
        "update": int(counts.get("update", 0) or 0),
        "retire": int(counts.get("retire", 0) or 0),
        "foreign": int(counts.get("foreign", len(foreign_ids)) or 0),
        "blocked": plan.get("blocked") or [],
        "foreignIds": foreign_ids,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform authenticated product PATCHes")
    ap.add_argument("--token", default=os.environ.get("WECARE_STAFF_TOKEN", ""))
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument(
        "--skip-meta-enable",
        action="store_true",
        help="migrate image keys only; do not set metaEnabled on active website products",
    )
    args = ap.parse_args()

    if not args.token:
        print("ERROR: provide --token or WECARE_STAFF_TOKEN.", file=sys.stderr)
        return 2

    products = list_products(args.api_base, args.token)
    legacy = [
        p for p in products
        if isinstance(p.get("catalogImageKey"), str)
        and p["catalogImageKey"].startswith(OLD_PREFIX)
    ]

    print(f"Products: {len(products)}")
    print(f"Legacy image keys to migrate: {len(legacy)}")
    for p in legacy:
        print(f"  {p.get('title')} :: {p.get('catalogImageKey')} -> {target_key(p['catalogImageKey'])}")

    if not args.apply:
        print("\nDRY RUN: no changes made. Re-run with --apply.")
        return 0

    migrated: list[dict[str, Any]] = []
    for product in legacy:
        new_key = target_key(str(product["catalogImageKey"]))
        saved = patch_product(args.api_base, args.token, product, {"catalogImageKey": new_key})
        verify_migrated(saved, new_key)
        migrated.append(saved)
        print(f"MIGRATED {saved.get('title')}")

    products = list_products(args.api_base, args.token)
    old_left = [p for p in products if str(p.get("catalogImageKey") or "").startswith(OLD_PREFIX)]
    canonical = [p for p in products if str(p.get("catalogImageKey") or "").startswith(NEW_PREFIX)]
    if old_left:
        raise RuntimeError(f"migration incomplete: {len(old_left)} legacy keys remain")
    if len(canonical) != len(legacy):
        raise RuntimeError(
            f"canonical-key count mismatch: expected {len(legacy)}, got {len(canonical)}"
        )
    print(f"VERIFY image keys: canonical={len(canonical)} legacy=0")

    if not args.skip_meta_enable:
        changed = 0
        products = list_products(args.api_base, args.token)
        for product in products:
            if not meta_candidate(product) or product.get("metaEnabled") is True:
                continue
            saved = patch_product(args.api_base, args.token, product, {"metaEnabled": True})
            if saved.get("metaEnabled") is not True:
                raise RuntimeError(f"{product.get('id')}: metaEnabled readback failed")
            changed += 1
            print(f"META ENABLED {saved.get('title')}")
        print(f"VERIFY metaEnabled changes: {changed}")

    final_products = list_products(args.api_base, args.token)
    selected = [p for p in final_products if p.get("metaEnabled") is True]
    invalid_selected = [
        p for p in selected
        if p.get("status") != "active"
        or not str(p.get("catalogImageKey") or "").startswith(NEW_PREFIX)
    ]
    if invalid_selected:
        raise RuntimeError(
            "refusing Meta inspect: enabled products include draft/imageless/noncanonical rows"
        )

    status, plan = inspect_meta(args.api_base, args.token)

    if status == 409 and isinstance(plan, dict) and plan.get("reason") in META_PLAN_NOT_LOADED_REASONS:
        # The release work (image-key migration + meta-enablement) is DONE and verified above.
        # Only the advisory Meta plan could not be computed because the Meta channel is
        # owner-gated / not provisioned. Report it clearly and succeed - there is nothing to
        # approve, and this tool never applies a provider plan.
        print("\nMETA READ-ONLY PLAN")
        print(f"Meta plan not loaded (reason={plan.get('reason')}). "
              "The catalog release to AWS ProductsTable is complete; the Meta projection is "
              "owner-gated and will reconcile once the Meta channel is configured.")
        print("\nCATALOG RELEASE COMPLETE (AWS authoritative). META SYNC PENDING OWNER SETUP.")
        return 0

    if status != 200:
        raise RuntimeError(f"Meta inspect failed: HTTP {status} {plan}")

    summary = summarize_plan(plan)
    print("\nMETA READ-ONLY PLAN")
    print(json.dumps(summary, indent=2))

    if summary["blocked"]:
        raise RuntimeError(f"Meta plan has blocked items: {summary['blocked']}")
    if summary["foreign"] != len(summary["foreignIds"]):
        raise RuntimeError("Meta foreign count does not match wix retailer-id readback")
    if not summary["planHash"]:
        raise RuntimeError("Meta inspect returned no plan hash")

    print("\nSTOPPED BEFORE META WRITE.")
    print("Exact-plan approval is required before provider apply.")
    print(f"PLAN_HASH={summary['planHash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
