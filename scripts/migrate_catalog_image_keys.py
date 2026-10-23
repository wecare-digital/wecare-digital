#!/usr/bin/env python3
"""Migrate legacy `catalogImageKey` values on ProductsTable to the canonical prefix.

WHAT THIS FIXES
---------------
Some product rows in `stack-wecare-digital-ProductsTable` carry a pre-split
`catalogImageKey` of the shape `secure/public/catalog-deploy/catalog/products/<n>-4096.png`
(no `d/` segment). The canonical, handler-accepted shape is
`secure/d/public/catalog-deploy/catalog/products/<n>-4096.png`. Until a row is corrected,
the native-catalog-admin handler will reject re-publication (it validates the key with the
canonical prefix) and `catalog-media` cannot serve the image.

WHY THIS GOES THROUGH THE AUTHENTICATED ADMIN API, NOT RAW DYNAMODB
-------------------------------------------------------------------
The authority for a product row is the native-catalog-admin Lambda
(`PATCH /native-catalog/products/{id}`), which:
  * enforces STAFF Cognito **Admin** + MFA (lambda_utils.middleware.require_auth),
  * validates the new key with `_catalog_image_key`, and
  * re-derives `imageRefs` from the key atomically.
A raw DynamoDB write would bypass that validation and the imageRefs derivation, and defeat
the deliberate STAFF-Admin control. So this tool is the AUTOMATION of the operator workflow,
not a bypass: it computes every payload and performs the real authenticated PATCHes. The one
thing it cannot self-mint is the Admin+MFA access token - there is no machine/client-
credentials path on the staff pool by design - so the token is injected via
`WECARE_STAFF_TOKEN` (a human/SSO sign-in produces it once; the rest is unattended).

USAGE
-----
    # dry run (default): list rows that need migration and the exact PATCH payloads
    python scripts/migrate_catalog_image_keys.py

    # execute, consuming a staff Admin access token
    WECARE_STAFF_TOKEN=<access-token> python scripts/migrate_catalog_image_keys.py --apply

    # limit / inspect
    python scripts/migrate_catalog_image_keys.py --only <product-id>
    python scripts/migrate_catalog_image_keys.py --api-base https://wecare.digital/api

Exit status: 0 when nothing needs migration or all migrations succeed; 1 on any failure
(and in --apply mode, 1 if a token is required but absent).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://wecare.digital/api"

CANONICAL_PREFIX = "secure/d/public/catalog-deploy/catalog/products/"
# The legacy shape is the canonical one with the `d/` segment missing.
LEGACY_PREFIX = "secure/public/catalog-deploy/catalog/products/"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-4096[.]png$")


def canonicalize(key: str) -> str | None:
    """Return the canonical key for a legacy key, or None if it is not a known legacy key.

    Only the exact legacy prefix is rewritten, and only when the trailing name is a valid
    approved `*-4096.png` artwork with no nested path - mirroring the handler's own
    `_catalog_image_key` validation so this never produces a key the API would reject.
    """
    if not isinstance(key, str):
        return None
    k = key.strip().lstrip("/")
    if not k.startswith(LEGACY_PREFIX):
        return None
    name = k[len(LEGACY_PREFIX):]
    if "/" in name or not NAME_RE.fullmatch(name):
        return None
    return CANONICAL_PREFIX + name


def http_json(method: str, url: str, token: str, body: dict | None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def list_products(api_base: str, token: str) -> list[dict]:
    status, payload = http_json("GET", f"{api_base}/native-catalog/products", token, None)
    if status != 200:
        raise SystemExit(f"list failed: HTTP {status} {payload}")
    return payload.get("products") or payload.get("items") or payload.get("rows") or []


def needs_migration(row: dict) -> str | None:
    return canonicalize(row.get("catalogImageKey") or "")


def patch_one(api_base: str, token: str, row: dict, canonical_key: str) -> tuple[bool, str]:
    """PATCH a single row, retrying once on a version conflict by re-reading updatedAt."""
    pid = row["id"]
    expected = row.get("updatedAt")
    for attempt in (1, 2):
        body = {"expectedUpdatedAt": expected, "catalogImageKey": canonical_key}
        status, payload = http_json(
            "PATCH", f"{api_base}/native-catalog/products/{pid}", token, body)
        if status == 200:
            return True, "ok"
        if status == 409 and attempt == 1:
            # Re-read the row to get the fresh updatedAt, then retry once.
            s2, fresh = http_json(
                "GET", f"{api_base}/native-catalog/products/{pid}", token, None)
            if s2 == 200:
                expected = (fresh.get("product") or fresh).get("updatedAt")
                continue
        return False, f"HTTP {status} {payload}"
    return False, "version conflict after retry"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the PATCHes (default: dry-run)")
    ap.add_argument("--token", default=os.environ.get("WECARE_STAFF_TOKEN", ""),
                    help="staff Cognito ACCESS token (or set WECARE_STAFF_TOKEN)")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--only", default="", help="limit to a single product id")
    args = ap.parse_args()

    if not args.token:
        # In dry-run we can still try an unauthenticated list, but the admin API requires a
        # viewer token even for GET, so be explicit about what will happen.
        print("NOTE: no WECARE_STAFF_TOKEN set. The admin API requires a staff token even to "
              "LIST products; without one this can only describe intent.", file=sys.stderr)
        if args.apply:
            print("REFUSING --apply without a token.", file=sys.stderr)
            return 1

    rows = list_products(args.api_base, args.token)
    if args.only:
        rows = [r for r in rows if r.get("id") == args.only]

    pending = [(r, canonicalize(r.get("catalogImageKey") or "")) for r in rows]
    pending = [(r, c) for r, c in pending if c]

    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(rows)} products scanned, "
          f"{len(pending)} with a legacy catalogImageKey to migrate.")
    for r, canonical_key in pending:
        print(f"  {r['id']}: {r.get('catalogImageKey')}  ->  {canonical_key}")

    if not pending:
        print("Nothing to migrate.")
        return 0
    if not args.apply:
        print("\nRe-run with --apply and a staff token to execute these PATCHes.")
        return 0

    failures = 0
    for r, canonical_key in pending:
        ok, detail = patch_one(args.api_base, args.token, r, canonical_key)
        print(f"  {'OK  ' if ok else 'FAIL'} {r['id']}: {detail}")
        failures += 0 if ok else 1

    print(f"\n{len(pending) - failures}/{len(pending)} migrated.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
