#!/usr/bin/env python3
"""Retire legacy redirects and enforce the owner's current home routing policy.

Keep internal 200 rewrites and the 404-200 fallback unchanged. These serve the
API, files, short-link service, MCP and missing-page document. The legacy filename
is retained because the deployment workflow already invokes this entry point.
Only www canonicalisation may redirect; the retired /access entry must stay unavailable.
No legacy SEO, workspace or frozen-template destination may be recreated.

Usage: python scripts/provision_legacy_redirects.py [--apply | --verify]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
APP_ID = "d22dm4b0jn71jw"
SITE = "https://wecare.digital"
ROOT = pathlib.Path(__file__).resolve().parents[1]
# Historical only, never the rollback target for a new mutation.
SNAPSHOT = ROOT / "docs/execution/snapshots/amplify-custom-rules-before-8.4.json"
REDIRECT_STATUSES = frozenset({"301", "302", "307", "308", "404"})
CATCH_ALL_SOURCE = "/<*>"
CATCH_ALL_TARGET = "/404.html"
CATCH_ALL_STATUS = "404-200"


def amplify():
    return boto3.client("amplify", region_name=REGION)


def desired_redirects() -> list[dict]:
    """The www canonicalisation, the /zip -> /shipments rename, and the withdrawn /shop index.

    WHY A SECOND REDIRECT NOW EXISTS, when this module's whole posture is that retired paths
    should 404 rather than be kept alive: because /zip was not RETIRED, it was RENAMED.

    On 2026-10-02 the owner retired the product name "Zip" entirely and the page moved from
    /zip/ to /shipments/ (src/pages/shipments.tsx, PUBLIC_PAGE_META key, sitemap PUBLIC_EXACT,
    scripts/generate-public-pages.js, config/public-pages.json). The content did not go away and
    it did not change - only its name and its URL did.

    scripts/retired_url_equity.py states the distinction this rule turns on, and it is the
    reason a 404 is the WRONG answer here: "A 404 is the correct answer for a page that was
    deleted because it was wrong. It is the WRONG answer for a page that was replaced, because a
    404 discards the link equity instead of passing it to the replacement - and equity is the one
    thing a new export cannot regenerate on its own." /zip/ measured 404 at the origin after the
    rename, so every inbound link to it - including any already sent in a WhatsApp message - was
    dead and its accumulated ranking was being thrown away rather than consolidated onto
    /shipments/.

    BOTH FORMS ARE DECLARED. next.config's trailingSlash means the canonical URL was /zip/, but
    links in the wild carry both /zip and /zip/, and an Amplify source pattern is matched as
    given rather than normalised. Declaring only one would leave the other 404ing, which is the
    defect this rule exists to remove. The target carries the trailing slash because
    /shipments (no slash) would itself redirect before resolving.

    301, not 302: the move is permanent, and only a permanent redirect consolidates ranking onto
    the new URL.

    WHY THREE /shop RULES NOW EXIST, and why this one is neither a rename nor a retirement.

    On 2026-10-04 the owner instructed that the catalogue INDEX stop being browsable and that
    /shop/ go to the home page. The listing is WITHDRAWN - it is neither replaced by another page
    nor deleted because it was wrong - so retired_url_equity.py's equity argument does not apply
    here at all. The 301 is INSTRUCTION COMPLIANCE, not equity recovery. 301 rather than 302
    because the withdrawal is permanent and a temporary status would keep the old URL in the index.

    THE SEVEN PRODUCT PAGES ARE NOT AFFECTED AND MUST NOT BE. /shop/<slug>/ keeps rendering and
    keeps its add-to-cart. That is why these are three EXACT sources and never a /shop/<*>
    wildcard: an Amplify wildcard source matches any suffix, so /shop/<*> would 301 every product
    page onto the home page and destroy the catalogue. Do not "simplify" the three rules into one.

    ALL THREE SPELLINGS ARE DECLARED, and the third is the one that is easy to miss. Measured on
    2026-10-04 before this change: /shop/ served the full listing at 200, /shop 301'd to /shop/,
    and /shop/index.html ALSO served the full listing at 200 - because `output: 'export'` writes
    out/shop/index.html and Amplify will serve that file by its own name. Deleting the page from
    the export closes that for the current build, but the rule is kept PERMANENTLY: it is what
    stops a re-added index page becoming reachable again by a URL nobody is watching.

    NOTE FOR WHOEVER RUNS --apply: verify() compares the live rule list against this function for
    EXACT equality, so a live app that still carries only the www rule will report FAIL until
    --apply has run. That FAIL is the expected pre-apply state, not a fault in this list.
    """
    return [
        {"source": "https://www.wecare.digital", "target": SITE, "status": "301"},
        {"source": "/zip", "target": "/shipments/", "status": "301"},
        {"source": "/zip/", "target": "/shipments/", "status": "301"},
        {"source": "/shop", "target": "/", "status": "301"},
        {"source": "/shop/", "target": "/", "status": "301"},
        {"source": "/shop/index.html", "target": "/", "status": "301"},
    ]


def is_ours(rule: dict) -> bool:
    return str(rule.get("status", "")) in REDIRECT_STATUSES


def current_rules(client) -> list[dict]:
    return [dict(rule) for rule in client.get_app(appId=APP_ID)["app"].get("customRules", [])]


def report(client) -> tuple[list[dict], list[dict]]:
    existing = current_rules(client)
    removable = [rule for rule in existing if is_ours(rule)]
    print(f"app {APP_ID}: {len(existing)} rules; {len(removable)} redirects to reconcile")
    for rule in removable:
        print(f"  current {rule.get('status')} {rule['source']} -> {rule['target']}")
    return existing, removable


def apply(client, existing: list[dict]) -> int:
    """Snapshot first, remove redirects only, preserve all other rules in order."""
    new_rules = desired_redirects() + [dict(rule) for rule in existing if not is_ours(rule)]
    fallback = [rule for rule in new_rules if rule.get("source") == CATCH_ALL_SOURCE]
    if len(fallback) != 1 or fallback[0].get("status") != CATCH_ALL_STATUS:
        print("Refusing update: one existing 404-200 fallback is required", file=sys.stderr)
        return 2
    if new_rules == existing:
        print("Owner home routing policy is current; no write needed")
        return 0
    rollback = ROOT / ".scratch" / f"amplify-custom-rules-before-{time.time_ns()}.json"
    rollback.parent.mkdir(parents=True, exist_ok=True)
    rollback.write_text(json.dumps(existing, indent=4) + "\n")
    print(f"Rollback snapshot -> {rollback}")
    client.update_app(appId=APP_ID, customRules=new_rules)
    print(f"Reconciled {len(desired_redirects())} approved redirects; preserved runtime rewrites")
    return 0


def verify() -> int:
    _, removable = report(amplify())
    if removable != desired_redirects():
        print("FAIL: redirects differ from the approved home routing policy", file=sys.stderr)
        return 1
    print("Verified: only www canonicalisation remains; retired paths do not redirect")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            return verify()
        client = amplify()
        existing, removable = report(client)
        if existing == desired_redirects() + [r for r in existing if not is_ours(r)]:
            return 0
        if args.apply:
            return apply(client, existing)
        print("Re-run with --apply to enforce the approved home routing policy")
        return 1
    except (ClientError, BotoCoreError) as exc:
        print(f"AWS operation failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
