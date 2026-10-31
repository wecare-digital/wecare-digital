#!/usr/bin/env python3
"""Remove legacy 30x content redirects from the site's Amplify customRules.

Authority: this script reconciles only Amplify app d22dm4b0jn71jw customRules,
and only with --apply. It snapshots the complete prior list and reads it back.
Without --apply it reports; --verify is read-only (AWS read + public HTTP GETs).

No 30x content redirect is approved: retired service URLs and merged blog source
slugs should use the site's not-found fallback and land on the homepage, never
automatically navigate to Orders, Contact, or a different post. Real current pages
continue to serve normally. Host canonicalisation (www -> apex) is separately
owned by the CloudFront function in amplify/infra/home-fallback.json.

All non-30x rules are preserved byte for byte and in order: API, file, short-link,
and MCP 200 rewrites, specific 404 rules, and the terminal /<*> -> /404.html
404-200 catch-all. The catch-all must remain last and must be a not-found rule.

The legacy filename is retained because earlier deployment tooling invokes this entry point.

Usage: python scripts/provision_legacy_redirects.py [--apply | --verify]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
APP_ID = "d22dm4b0jn71jw"
SITE = "https://wecare.digital"
ROOT = pathlib.Path(__file__).resolve().parents[1]
MERGES_FILE = ROOT / "config" / "blog-merges.json"
# Historical only, never the rollback target for a new mutation.
SNAPSHOT = ROOT / "docs/execution/snapshots/amplify-custom-rules-before-8.4.json"
# Only redirects are this script's to replace. 404 and 404-200 rules are not-found routing.
REDIRECT_STATUSES = frozenset({"301", "302", "307", "308"})
NOT_FOUND_STATUSES = frozenset({"404", "404-200"})
CATCH_ALL_SOURCE = "/<*>"
# These former service pages have no standalone content. Without 301 rules they
# fall through to /404.html, which sends visitors Home. Never add /vault/ here:
# /vault/?file=<id> is an approved exact-file link and path-only rules cannot
# distinguish it from bare /vault/.
RETIRED_SERVICE_PAGE_ROUTES = (
    "/submit-request",
    "/request-amendment",
    "/drop-docs",
    "/request-pickup",
    "/shipments/track",
    # Shipment Track also had a separate /shop/<slug>/ product page.
    "/shop/shipments-track",
)


def amplify():
    return boto3.client("amplify", region_name=REGION)


def blog_merges() -> list[tuple[str, str]]:
    """The approved (from, to) post merges. A malformed file refuses rather than shrinking."""
    merges = json.loads(MERGES_FILE.read_text(encoding="utf-8")).get("merges")
    if not isinstance(merges, list) or not merges:
        raise ValueError(f"{MERGES_FILE.relative_to(ROOT)}: 'merges' must be a non-empty list")
    pairs = [(str(m["from"]).strip(), str(m["to"]).strip()) for m in merges]
    if any(not source or not target or source == target for source, target in pairs):
        raise ValueError(f"{MERGES_FILE.relative_to(ROOT)}: every merge needs distinct from/to")
    targets = {target for _, target in pairs}
    if any(source in targets for source, _ in pairs):
        raise ValueError(f"{MERGES_FILE.relative_to(ROOT)}: a merge target is itself merged away")
    return pairs


def desired_redirects() -> list[dict]:
    """No 30x rules are approved in Amplify; missing pages use /404.html."""
    return []


def is_ours(rule: dict) -> bool:
    return str(rule.get("status", "")) in REDIRECT_STATUSES


def current_rules(client) -> list[dict]:
    return [dict(rule) for rule in client.get_app(appId=APP_ID)["app"].get("customRules", [])]


def catch_all_problem(rules: list[dict]) -> str:
    """Why `rules` would break not-found routing, or '' when the catch-all is intact."""
    catch_alls = [i for i, rule in enumerate(rules) if rule.get("source") == CATCH_ALL_SOURCE]
    if len(catch_alls) != 1:
        return f"expected exactly one {CATCH_ALL_SOURCE} catch-all, found {len(catch_alls)}"
    index = catch_alls[0]
    if index != len(rules) - 1:
        return f"the {CATCH_ALL_SOURCE} catch-all must be the last rule; every rule after it is dead"
    if str(rules[index].get("status")) not in NOT_FOUND_STATUSES:
        return (f"the {CATCH_ALL_SOURCE} catch-all is status {rules[index].get('status')}, not a "
                "not-found rule; a plain rewrite there would shadow every exported page")
    return ""


def report(client) -> tuple[list[dict], list[dict]]:
    existing = current_rules(client)
    removable = [rule for rule in existing if is_ours(rule)]
    print(f"app {APP_ID}: {len(existing)} rules; {len(removable)} redirects to reconcile")
    for rule in removable:
        print(f"  current {rule.get('status')} {rule['source']} -> {rule['target']}")
    return existing, removable


def planned(existing: list[dict]) -> list[dict]:
    return desired_redirects() + [dict(rule) for rule in existing if not is_ours(rule)]


def apply(client, existing: list[dict]) -> int:
    """Snapshot first, replace the redirects only, preserve every other rule in order."""
    new_rules = planned(existing)
    problem = catch_all_problem(new_rules)
    if problem:
        print(f"Refusing update: {problem}", file=sys.stderr)
        return 2
    if new_rules == existing:
        print("No Amplify 30x redirects remain; no write needed")
        return 0
    rollback = ROOT / ".scratch" / f"amplify-custom-rules-before-{time.time_ns()}.json"
    rollback.parent.mkdir(parents=True, exist_ok=True)
    rollback.write_text(json.dumps(existing, indent=4) + "\n")
    print(f"Rollback snapshot -> {rollback}")
    client.update_app(appId=APP_ID, customRules=new_rules)
    # customRules is replaced wholesale, so read it back rather than trust the write.
    after = current_rules(client)
    if after != new_rules:
        print("FAIL: read-back differs from what was written; restore from the snapshot above",
              file=sys.stderr)
        return 1
    print(f"Removed {len(existing) - len(new_rules)} 30x redirects; preserved "
          f"{len(new_rules)} rewrites and not-found rules in order")
    return 0


def _no_follow_status(url: str) -> tuple[int, str]:
    """One GET without following redirects: (status, Location)."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
            return None

    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "wecare-redirect-verify"})
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "") if exc.headers else ""


def verify_live_fallbacks() -> list[str]:
    """Retired trailing-slash pages must 404, while real destination posts stay live."""
    failures = []
    for route in RETIRED_SERVICE_PAGE_ROUTES:
        status, location = _no_follow_status(f"{SITE}{route}/")
        if status != 404:
            failures.append(f"{route}/ answered {status} -> {location or '-'}, "
                            "expected the not-found page (404), which navigates home")
    for source_slug, target_slug in blog_merges():
        source_path = f"/post/{source_slug}/"
        status, location = _no_follow_status(f"{SITE}{source_path}")
        if status != 404:
            failures.append(f"{source_path} answered {status} -> {location or '-'}, "
                            "expected the not-found page (404), which navigates home")
        target_path = f"/post/{target_slug}/"
        status, location = _no_follow_status(f"{SITE}{target_path}")
        if status != 200:
            failures.append(f"{target_path} answered {status} {location}".rstrip())
    return failures


def verify() -> int:
    existing, removable = report(amplify())
    failures = []
    if removable:
        failures.append(f"{len(removable)} unexpected 30x Amplify redirect rules remain")
    problem = catch_all_problem(existing)
    if problem:
        failures.append(problem)
    failures += verify_live_fallbacks()
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("Verified: zero Amplify 30x redirects, retired paths answer 404, "
          "canonical blog targets answer 200, and the not-found catch-all remains last")
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
        existing, _ = report(client)
        new_rules = planned(existing)
        if new_rules == existing:
            print("No Amplify 30x redirects remain; no write needed")
            return 0
        if args.apply:
            return apply(client, existing)
        for rule in existing:
            if is_ours(rule):
                print(f"  would remove {rule['status']} {rule['source']} -> {rule['target']}")
        problem = catch_all_problem(new_rules)
        print(f"Refusing to plan a write: {problem}" if problem
              else "Re-run with --apply to write the approved redirects")
        return 1
    except (ClientError, BotoCoreError) as exc:
        print(f"AWS operation failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"Refusing: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
