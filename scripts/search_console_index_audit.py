#!/usr/bin/env python3
"""Ask Google, per URL, why it is or is not indexed. Read-only.

    python scripts/search_console_index_audit.py                  # 10 representative URLs
    python scripts/search_console_index_audit.py --count 20
    python scripts/search_console_index_audit.py /anew/ /post/moar-kali/
    python scripts/search_console_index_audit.py --json

WHY A BATCH TOOL AND NOT `search_console_sitemap.py inspect`
-----------------------------------------------------------
That command inspects one URL. One URL cannot distinguish the two situations this
site might be in, and they call for completely different responses:

    a FEW urls unindexed    -> per-page problem: thin content, a bad canonical, a
                               soft 404
    ALL urls unindexed      -> site-level problem: host consolidation, crawl
                               budget, or simply never crawled

The sitemap reports `indexed=1` of `1353`, which points hard at the second, and the
only way to tell is to sample across page TYPES - home, marketing routes, the blog
index, a paginated blog page, and individual posts - then compare verdicts. A
sample of one from the wrong type produces a confident wrong answer.

WHAT IT CANNOT DO, said up front
--------------------------------
There is no "request indexing" endpoint. URL Inspection is strictly diagnostic: it
reports what Google already knows and triggers nothing. The Indexing API exists but
is documented for JobPosting and BroadcastEvent only, so it does not apply to
ordinary pages. The Search Console UI's "Request indexing" button has no API
equivalent.

So this script tells you WHY and never pretends to fix it. That distinction matters
because the instinct on seeing `indexed=1` is to hunt for a button, and the useful
work is all upstream of any button.

READING `Discovered - currently not indexed` CORRECTLY. It does not mean rejected.
It means Google knows the URL exists and has not spent crawl budget on it. On a site
whose sitemap went un-fetched for four months and whose host canonical is still
being consolidated, that is the expected state rather than a fault, and the remedy
is consistent signals plus time. `Crawled - currently not indexed` would be a
different and worse answer, because it means Google fetched the page and declined
it - that one points at the page, not at crawl budget.

QUOTA. URL Inspection allows 2000 queries/day and 600/minute per property, so the
default sample of 10 sits far below both. `--count` raises it.

Auth is reused from search_console_sitemap.py: an impersonated service-account
token, no browser, no key file, no secret read or printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search_console_sitemap import (  # noqa: E402
    READ_SCOPE,
    SITE,
    VERIFY_SITE,
    post_json,
    resolve_auth,
)

INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

#: Deliberately one per page TYPE rather than ten of the same shape - the whole point
#: is to compare across types. Ordered so the most diagnostic come first, because a
#: quota or auth failure then still leaves a usable sample.
DEFAULT_PATHS = [
    "/",                        # home - the one Google reported a canonical conflict on
    "/blog/",                   # blog index page 1, the only page carrying the full Blog node
    "/blog/page/2/",            # a paginated index - tests whether pagination is reachable
    "/post/moar-kali/",         # an individual article
    "/anew/",                   # a marketing route
    "/grahak-os/",              # carries its own product-level SoftwareApplication schema
    "/contact/",                # ContactPage, the conversion route
    "/llms.txt",                # the AI surface, to see if Google treats it as a page
    "/terms/",                  # a thin legal page, the most likely to be declined on merit
]

INTERESTING = [
    ("coverageState", "coverage"),
    ("robotsTxtState", "robots.txt"),
    ("indexingState", "indexing"),
    ("pageFetchState", "fetch"),
    ("crawledAs", "crawled as"),
    ("lastCrawlTime", "last crawl"),
    ("googleCanonical", "google canonical"),
    ("userCanonical", "our canonical"),
]


def inspect(auth: Any, path: str) -> dict[str, Any]:
    target = path if path.startswith("http") else f"{SITE}{path}"
    st, body = post_json(auth, INSPECT_URL, {
        "inspectionUrl": target,
        "siteUrl": VERIFY_SITE,
        "languageCode": "en-IN",
    })
    if st != 200:
        err = body.get("error") or {}
        return {"url": target, "http": st,
                "error": f"{err.get('status', '')} {err.get('message', '')}".strip()
                         or json.dumps(body)[:200]}
    idx = (body.get("inspectionResult") or {}).get("indexStatusResult") or {}
    out: dict[str, Any] = {"url": target, "http": 200,
                           "verdict": idx.get("verdict", "?")}
    for key, _ in INTERESTING:
        if idx.get(key) is not None:
            out[key] = idx[key]
    out["sitemaps"] = idx.get("sitemap") or []
    out["referringUrls"] = idx.get("referringUrls") or []
    # A canonical MISMATCH is the single most consequential field here, so it is
    # derived rather than left for a reader to spot by eye across two long URLs.
    g, u = idx.get("googleCanonical"), idx.get("userCanonical")
    out["canonical_conflict"] = bool(g and u and g != u)
    return out


def diagnose(rows: list[dict[str, Any]]) -> list[str]:
    """Turn the sample into the few sentences that decide what to do next."""
    notes: list[str] = []
    ok = [r for r in rows if r.get("http") == 200]
    if not ok:
        return ["every inspection failed - see the errors above"]

    indexed = [r for r in ok if r.get("verdict") == "PASS"]
    never_crawled = [r for r in ok if not r.get("lastCrawlTime")]
    discovered = [r for r in ok
                  if "Discovered" in str(r.get("coverageState", ""))]
    crawled_not_indexed = [r for r in ok
                           if "Crawled" in str(r.get("coverageState", ""))
                           and "not indexed" in str(r.get("coverageState", ""))]
    conflicts = [r for r in ok if r.get("canonical_conflict")]
    unknown = [r for r in ok
               if "unknown to Google" in str(r.get("coverageState", ""))]

    # `*_UNSPECIFIED` MEANS "NO DATA", NOT "BLOCKED", and conflating the two is a bug
    # this script shipped with for one run. A never-crawled URL reports
    # ROBOTS_TXT_STATE_UNSPECIFIED and INDEXING_STATE_UNSPECIFIED because Google has
    # not fetched it and therefore has nothing to say - it is a CONSEQUENCE of not
    # being crawled, not a cause of it. Treating it as a fault produced
    # "BLOCKED BY ROBOTS.TXT: 9" against a robots.txt that blocks only /api/ and
    # /workspace/, which would have sent someone hunting a fault that does not exist.
    # So match the blocking states explicitly and let everything else be "unknown".
    blocked = [r for r in ok if r.get("robotsTxtState") == "DISALLOWED"]
    not_allowed = [r for r in ok
                   if str(r.get("indexingState", "")).startswith("BLOCKED_")]
    unknown_state = [r for r in ok
                     if str(r.get("robotsTxtState", "")).endswith("_UNSPECIFIED")]
    missing_sitemap = [r for r in ok if not r.get("sitemaps")]
    no_referrers = [r for r in ok if not r.get("referringUrls")]

    notes.append(f"{len(indexed)}/{len(ok)} sampled URLs are indexed (verdict PASS)")

    if blocked:
        notes.append(f"DISALLOWED by robots.txt: {len(blocked)} - a real fault, and it "
                     "takes priority over everything else below")
    if not_allowed:
        notes.append(f"indexing explicitly BLOCKED on {len(not_allowed)} by a meta "
                     "robots or X-Robots-Tag - also a real fault")
    if not blocked and not not_allowed:
        notes.append("nothing is DISALLOWED and nothing explicitly refuses indexing, so "
                     "the cause is not a technical block on our side")
    if unknown_state:
        notes.append(f"{len(unknown_state)}/{len(ok)} report *_UNSPECIFIED for "
                     "robots.txt/indexing/fetch. That is 'no data because never "
                     "fetched', NOT 'blocked' - a consequence of not being crawled "
                     "rather than a cause of it")
    if unknown:
        paths = ", ".join(r["url"].replace(SITE, "") for r in unknown)
        notes.append(f"'URL is unknown to Google' on {len(unknown)} ({paths}) - Google "
                     "has never even heard of these. Both are absent from sitemap.xml, "
                     "which is the one genuinely ACTIONABLE finding here: a public route "
                     "that is in no sitemap and has no crawled inbound link is invisible")

    if crawled_not_indexed:
        notes.append(f"'Crawled - currently not indexed' on {len(crawled_not_indexed)}: "
                     "Google FETCHED these and declined them. That points at the page - "
                     "thin or duplicate content - not at crawl budget")
    if discovered:
        notes.append(f"'Discovered - currently not indexed' on {len(discovered)}: known "
                     "but not yet crawled. Points at crawl budget and site trust, not at "
                     "the pages. Not a fault, and not fixable by editing the page")
    if never_crawled:
        notes.append(f"{len(never_crawled)}/{len(ok)} have NEVER been crawled "
                     "(no lastCrawlTime) - the strongest signal that this is a "
                     "site-level crawl problem rather than per-page rejection")
    if conflicts:
        hosts = {r.get("googleCanonical", "") for r in conflicts}
        notes.append(f"CANONICAL CONFLICT on {len(conflicts)}: Google chose "
                     f"{', '.join(sorted(hosts))[:120]} over ours. Until this settles "
                     "Google is consolidating signals onto a URL we do not serve")
    if missing_sitemap:
        notes.append(f"{len(missing_sitemap)}/{len(ok)} are not attributed to any "
                     "sitemap by Google. For a URL that IS in sitemap.xml this usually "
                     "means the sitemap has not been reprocessed since it was added")
    if no_referrers:
        notes.append(f"{len(no_referrers)}/{len(ok)} have no referring URLs recorded - "
                     "internal links exist in the HTML but Google has not crawled enough "
                     "of the site to have built the link graph yet")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="paths or URLs (default: a 10-URL sample)")
    ap.add_argument("--count", type=int, default=10, help="how many of the sample to use")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    auth = resolve_auth()
    if auth is None:
        print("no usable credential; run scripts/search_console_sitemap.py check")
        return 2
    if auth.has_any_console() is False:
        print(f"credential lacks a Search Console scope ({auth.source})")
        return 2

    paths = args.paths or DEFAULT_PATHS[:max(1, args.count)]
    rows = [inspect(auth, p) for p in paths]

    if args.json:
        print(json.dumps({"property": VERIFY_SITE, "results": rows,
                          "diagnosis": diagnose(rows)}, indent=2))
        return 0

    print("=" * 78)
    print(f"URL INSPECTION - {len(rows)} url(s) on {VERIFY_SITE}")
    print(f"credential: {auth.source}")
    print("=" * 78)
    for r in rows:
        print(f"\n{r['url']}")
        if r.get("http") != 200:
            print(f"    http {r['http']}  {r.get('error', '')}")
            continue
        print(f"    verdict            : {r['verdict']}")
        for key, label in INTERESTING:
            if key in r:
                print(f"    {label:<19}: {r[key]}")
        if r.get("canonical_conflict"):
            print("    ^^ CANONICAL CONFLICT - Google is not honouring ours")
        print(f"    in sitemap         : {', '.join(r['sitemaps']) or 'not attributed'}")
        print(f"    referring urls     : {len(r['referringUrls'])}")

    print("\n" + "=" * 78)
    print("DIAGNOSIS")
    print("=" * 78)
    for note in diagnose(rows):
        print(f"  * {note}")
    print("\n  Reminder: URL Inspection cannot request indexing, and the Indexing API")
    print("  covers JobPosting/BroadcastEvent only. There is no API button to press.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
