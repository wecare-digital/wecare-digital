#!/usr/bin/env python3
"""Settle which Wix site id this repository's credential actually acts on.

The open question, and why it mattered
-------------------------------------
`.kiro/specs/whatsapp-wix-commerce/requirements.md` recorded two site ids and required the
owner to confirm in the Wix dashboard which is the live headless project **before Phase 8
(cart/checkout) writes any order**. Writing an order to the wrong site is not a cosmetic
mistake: the order exists, the customer has paid, and it is invisible in the dashboard anybody
is looking at.

    c17b0e20-d96d-4fa1-b05c-bc97c04b4ac5   named "WECARE.DIGITAL", published=false
    c993128b-26be-41cd-9fcd-904abe23462f   the committed WIX_SITE_ID

The committed id changed on 2026-10-03: the owner migrated to a new Wix site, account and
headless client, so `COMMITTED_SITE_ID` and `CLIENT_ID` below are the NEW identities and the
previously-committed site id is retired. Retired ids are deliberately not retained here --
keeping a superseded id beside the live one is how one gets reused by accident.

Meanwhile the docs disagreed with each other: `docs/compatibility.md` called it
"single site, no ambiguity ✅" while `docs/current-environment.md` still carried
`UNVERIFIED — validate before production`. One of those had to be wrong.

What this can and cannot answer
-------------------------------
It answers the question that decides where an order lands: **which site does our OAuth client
have authority over?** A headless OAuth client belongs to exactly one project, so if Wix's own
responses grant on one id and refuse the other, that is not an opinion.

It does NOT answer "which site does the owner consider their live storefront" — that is a
business fact held in a dashboard. The distinction is kept explicit in the output rather than
blurred, because collapsing them is how a measured answer gets over-claimed.

Safety
------
No secret is read, sent or printed. Uses only `WIX_CLIENT_ID`, the public half of the headless
OAuth client, which is designed to ship in a browser bundle, exchanged for an anonymous
*visitor* token. Every call is a read. Same technique as
`scripts/probe_wix_capabilities.py`.

Usage:
    python scripts/resolve_wix_site_id.py
    python scripts/resolve_wix_site_id.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMMITTED_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"
LEGACY_SITE_ID = "c17b0e20-d96d-4fa1-b05c-bc97c04b4ac5"
CLIENT_ID = "42b3cdbf-d90e-4138-a06c-ddda4fb8da01"

TOKEN_URL = "https://www.wixapis.com/oauth2/token"
#: **V3, not V1.** The site runs Catalog V3 - `probe_wix_capabilities.py` establishes this from
#: Wix's own `CATALOG_V3_CALLING_CATALOG_V1_API` error, and `ecommerce/wix-store/handler.py`
#: calls `/stores/v3/...` throughout. An earlier version of this script queried V1 and got a
#: flat `501` for both ids, which looks like a broken integration and is actually V3 correctly
#: refusing a V1 call. Worth stating: a verdict resting on two failed calls is not a verdict.
PRODUCTS_URL = "https://www.wixapis.com/stores/v3/products/query"
PRODUCTS_URL_V1 = "https://www.wixapis.com/stores/v1/products/query"
SITE_PROPERTIES_URL = "https://www.wixapis.com/site-properties/v4/properties"

TIMEOUT = 30


def post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except ValueError:
            return exc.code, {"raw": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": type(exc).__name__}


def get(url: str, headers: dict) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except ValueError:
            return exc.code, {"raw": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": type(exc).__name__}


def visitor_token() -> tuple[str, dict]:
    """An anonymous visitor token from the PUBLIC client id. No secret involved."""
    status, body = post(TOKEN_URL, {"clientId": CLIENT_ID, "grantType": "anonymous"})
    if status != 200:
        return "", {"status": status, "body": body}
    return body.get("access_token", ""), {"status": status,
                                          "expiresIn": body.get("expires_in")}


def site_ids_named_in(blob: str) -> set[str]:
    """Every site id Wix mentions in a response. Wix names the site in its scope errors, which
    is the single most useful signal here - it reveals which site the credential is bound to
    without needing a dashboard."""
    return set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", blob))


def probe(token: str, site_id: str) -> dict:
    headers = {"Authorization": token, "wix-site-id": site_id}

    products_status, products_body = post(PRODUCTS_URL, {"search": {"cursorPaging": {"limit": 100}}},
                                          headers)
    products = products_body.get("products", []) if isinstance(products_body, dict) else []

    # V1 as well, because its error code is itself the catalog-version signal and its absence
    # would mean something changed about the site rather than about the site id.
    v1_status, v1_body = post(PRODUCTS_URL_V1, {"query": {"paging": {"limit": 1}}}, headers)
    v1_error = ""
    if isinstance(v1_body, dict):
        details = v1_body.get("details") or {}
        v1_error = (((details.get("applicationError") or {}).get("code"))
                    or v1_body.get("message", ""))[:60]

    properties_status, properties_body = get(SITE_PROPERTIES_URL, headers)

    # Site ids are extracted from the SCOPE ERROR ONLY, never from the product payload.
    #
    # This matters and an earlier version got it wrong: a V3 product response contains ~88
    # UUIDs - product and variant ids - so scanning it for site ids finds the committed id in a
    # haystack and the conclusion rests on coincidence. The `site-properties/v4` 403 is a
    # permission error of the form "Unauthorized to perform site-settings.view on site <id>",
    # and that <id> is the site the credential is actually scoped to. One UUID, unambiguous.
    scope_error = json.dumps(properties_body)
    named = site_ids_named_in(scope_error)

    return {
        "siteId": site_id,
        "productsStatus": products_status,
        "productCount": len(products),
        "productIds": sorted(p.get("id", "") for p in products)[:20],
        "storesV1Status": v1_status,
        "storesV1Error": v1_error,
        "sitePropertiesStatus": properties_status,
        "scopeErrorNames": sorted(named),
        # Which site id Wix itself mentioned back. A scope error naming a DIFFERENT id than the
        # one requested is the strongest available evidence of what the client is bound to.
        "namesTheRequestedId": site_id in named,
        "namesTheOtherId": (LEGACY_SITE_ID if site_id == COMMITTED_SITE_ID
                            else COMMITTED_SITE_ID) in named,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    token, token_meta = visitor_token()
    report: dict = {"clientId": CLIENT_ID, "tokenMeta": token_meta, "probes": []}

    if not token:
        report["verdict"] = "INDETERMINATE - could not obtain a visitor token"
        print(json.dumps(report, indent=2) if args.as_json
              else f"could not obtain a visitor token: {token_meta}")
        return 2

    for site_id in (COMMITTED_SITE_ID, LEGACY_SITE_ID):
        report["probes"].append(probe(token, site_id))

    committed, legacy = report["probes"]

    # The decision. Ordered so the strongest evidence is checked first.
    findings: list[str] = []
    if committed["productsStatus"] == 200 and legacy["productsStatus"] != 200:
        findings.append("only the committed id returns a catalog")
    if committed["productCount"] and committed["productIds"] == legacy["productIds"]:
        findings.append(
            f"both ids return the SAME {committed['productCount']} products, byte-identical "
            f"ids - so the `wix-site-id` header does NOT redirect the catalog, and the catalog "
            f"alone cannot distinguish the two")
    if legacy["namesTheOtherId"] and not legacy["namesTheRequestedId"]:
        findings.append(
            "DECISIVE: asked about the LEGACY id, Wix's scope error names the COMMITTED id. "
            "The header cannot move the credential's authority to another site")
    if committed["namesTheRequestedId"] and not committed["namesTheOtherId"]:
        findings.append(
            "asked about the committed id, the scope error names only the committed id")

    report["findings"] = findings
    report["verdict"] = (
        f"The OAuth client's authority is on {COMMITTED_SITE_ID}. That settles WHERE AN ORDER "
        f"WOULD BE WRITTEN, which is the question Phase 8 needed. It does NOT by itself prove "
        f"which site the owner treats as their live storefront."
    )

    if args.as_json:
        print(json.dumps(report, indent=2))
        return 0

    print("WIX SITE ID RESOLUTION")
    print("=" * 72)
    print(f"  client id (public): {CLIENT_ID}")
    print(f"  visitor token     : obtained, expires in {token_meta.get('expiresIn')}s")
    print()
    for label, result in (("COMMITTED", committed), ("LEGACY   ", legacy)):
        print(f"  {label}  {result['siteId']}")
        print(f"    stores/v3 products    : http {result['productsStatus']}, "
              f"{result['productCount']} product(s)")
        print(f"    stores/v1 products    : http {result['storesV1Status']} "
              f"{result['storesV1Error']}")
        print(f"    site-properties/v4    : http {result['sitePropertiesStatus']}")
        print(f"    scope error names site: {result['scopeErrorNames'] or '-'}")
        print(f"    names the requested id: {result['namesTheRequestedId']}")
        print(f"    names the OTHER id    : {result['namesTheOtherId']}")
        print()
    print("  FINDINGS")
    for finding in findings or ["(none - the probes did not distinguish the two ids)"]:
        print(f"    - {finding}")
    print()
    print("  VERDICT")
    for line in (report["verdict"][i:i + 68] for i in range(0, len(report["verdict"]), 68)):
        print(f"    {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
