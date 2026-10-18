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
    """Only canonicalise the apex host.

    Retired path aliases intentionally fall through to the 404 document. In particular,
    /zip and /zip/ no longer redirect because the former /shipments/ parent page is retired;
    the live children are /shipments/track/ and /request-pickup/.
    """
    return [
        {"source": "https://wecare.digital", "target": SITE, "status": "301"},
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
