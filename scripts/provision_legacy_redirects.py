#!/usr/bin/env python3
"""Own the site's permanent redirects in Amplify customRules, and nothing else.

Authority: this script writes ONE thing, the 30x redirect rules of Amplify app d22dm4b0jn71jw
(`UpdateApp customRules`), and only with --apply. It writes a rollback snapshot first and reads
the list back afterwards. Without a flag it reports; --verify is read-only (AWS read plus public
HTTP GETs).

What it manages: the approved blog post merges in config/blog-merges.json and the five
retired public service page routes, which now 301 to /orders/. Only those approved routes may redirect here; no
legacy SEO, workspace or frozen-template destination may be recreated, and the retired /access
entry stays unavailable. Host canonicalisation (www -> apex) is NOT an Amplify rule: www resolves
to the wildcard CloudFront distribution, whose function in amplify/infra/home-fallback.json owns
it. See desired_redirects().

What it preserves, byte for byte and in order: every non-30x rule. That is the internal 200
rewrites (API, files, short links, MCP), the not-found rules for retired routes, and the terminal
`/<*>` catch-all. Those belong to the owner's live routing policy, which has moved since this
script was first written (retired routes now answer through explicit 404 rules and the catch-all
target changed), so they are kept exactly as found rather than re-asserted from a stale copy.
The catch-all must exist once, be last and be a not-found rule, or the script refuses to write.

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
# These marketing pages are removed. A legacy link must reach the authenticated
# Orders hub, not a 404 or an obsolete product checkout. Do NOT redirect /vault:
# /vault/?file=<id> is an approved exact-file link and the hosting rules cannot
# distinguish it from /vault/ by path alone.
RETIRED_SERVICE_PAGE_ROUTES = (
    "/submit-request",
    "/request-amendment",
    "/drop-docs",
    "/request-pickup",
    "/shipments/track",
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
    """The approved permanent redirects: retired services, then each blog merge, twice.

    Both the slashless and the trailing-slash source are listed so neither falls through to
    the not-found catch-all.

    NO HOST RULE. This list used to open with {"source": "https://wecare.digital", "target": SITE},
    a redirect from the apex to itself: the `www` host had been rewritten to the apex by a
    bulk cleanup, which turned the www canonicalisation rule into a no-op that --apply kept
    re-asserting. It cannot simply be pointed back at `www` either: www.wecare.digital is not a
    domain of this Amplify app. Route 53 resolves it through `*.wecare.digital` to the wildcard
    CloudFront distribution, so an Amplify rule for that host would never see a request. The
    www -> apex redirect is owned by the CloudFront function in amplify/infra/home-fallback.json.
    """
    rules: list[dict] = []
    for route in RETIRED_SERVICE_PAGE_ROUTES:
        for source in (route, route + "/"):
            rules.append({"source": source, "target": "/orders/", "status": "301"})
    for source_slug, target_slug in blog_merges():
        for source in (f"/post/{source_slug}", f"/post/{source_slug}/"):
            rules.append({"source": source, "target": f"/post/{target_slug}/", "status": "301"})
    return rules


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
        print("Approved redirects are current; no write needed")
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
    print(f"Reconciled {len(desired_redirects())} approved redirects; preserved "
          f"{len(new_rules) - len(desired_redirects())} other rules in order")
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


def verify_live_merges() -> list[str]:
    """Both retired service routes and approved blog merges must redirect to real targets."""
    failures = []
    for route in RETIRED_SERVICE_PAGE_ROUTES:
        for source in (route, route + "/"):
            status, location = _no_follow_status(f"{SITE}{source}")
            if status != 301 or location.removeprefix(SITE) != "/orders/":
                failures.append(f"{source} answered {status} -> {location or '-'}, "
                                "expected 301 -> /orders/")
    for source_slug, target_slug in blog_merges():
        target_path = f"/post/{target_slug}/"
        status, location = _no_follow_status(f"{SITE}/post/{source_slug}/")
        if status != 301 or location.removeprefix(SITE) != target_path:
            failures.append(f"/post/{source_slug}/ answered {status} -> {location or '-'}, "
                            f"expected 301 -> {target_path}")
        status, location = _no_follow_status(f"{SITE}{target_path}")
        if status != 200:
            failures.append(f"{target_path} answered {status} {location}".rstrip())
    return failures


def verify() -> int:
    existing, removable = report(amplify())
    failures = []
    if removable != desired_redirects():
        failures.append("live redirects differ from the approved set")
    problem = catch_all_problem(existing)
    if problem:
        failures.append(problem)
    failures += verify_live_merges()
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"Verified: {len(desired_redirects())} approved redirects are live, every merge answers "
          "301 to a 200 target, and the not-found catch-all is intact and last")
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
            print("Approved redirects are current; no write needed")
            return 0
        if args.apply:
            return apply(client, existing)
        for rule in desired_redirects():
            if rule not in existing:
                print(f"  would add {rule['status']} {rule['source']} -> {rule['target']}")
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
