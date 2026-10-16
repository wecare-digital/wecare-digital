#!/usr/bin/env python3
"""Probe every RETIRED public URL this repo has ever advertised.

Why this exists. Removing a page from the sitemap does not remove it from Google's
index - the sitemap is an invitation, not a manifest. What actually drops a URL is the
response the crawler gets when it re-fetches it:

    301  consolidates the old URL's signals onto the new one, then drops it   BEST
    404  drops it, signals discarded                                         FINE
    410  same as 404 but faster                                              FINE
    200  the URL is STILL LIVE and still indexable. Being absent from the
         sitemap changes nothing - this is a duplicate competing with the
         page that replaced it                                               BAD

So the only thing to verify is: no retired URL answers 200.

The list is assembled from this repository's own record of removals - the comments in
scripts/generate-sitemap.js and public/robots.txt, the Amplify custom rules, and
docs/execution/change-authority-matrix.md. It is not guessed.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import urllib.error
import urllib.request

SITE = "https://wecare.digital"

RETIRED: dict[str, str] = {
    '/release-check-missing-page/': 'shared missing-page response must remain HTTP 404',
}

HOSTS = {
    "http://wecare.digital/": "http apex must redirect to https",
}


def probe(url: str) -> tuple[str, int, str]:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):  # noqa: ANN002, ANN003
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(
        url, headers={"User-Agent": "wecare-retired-url-probe/1"})
    try:
        with opener.open(req, timeout=30) as r:
            return url, r.status, ""
    except urllib.error.HTTPError as e:
        return url, e.code, (e.headers.get("Location", "") if e.headers else "")
    except Exception as e:  # noqa: BLE001
        return url, 0, type(e).__name__


def verdict(code: int) -> str:
    if code in (301, 308):
        return "OK-redirect"
    if code in (302, 307):
        return "OK-temporary-redirect"
    if code in (404, 410):
        return "OK-gone"
    if code == 200:
        return "STILL-LIVE"
    return "UNKNOWN"


def main() -> int:
    jobs = {SITE + p: why for p, why in RETIRED.items()}
    jobs.update(HOSTS)

    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for url, code, loc in ex.map(probe, list(jobs)):
            rows.append({"url": url, "status": code, "location": loc,
                         "verdict": verdict(code), "why": jobs[url]})

    rows.sort(key=lambda r: (r["verdict"] != "STILL-LIVE", r["url"]))
    print(json.dumps(rows, indent=2))

    still = [r for r in rows if r["verdict"] == "STILL-LIVE"]
    unknown = [r for r in rows if r["verdict"] == "UNKNOWN"]

    print(f"\nprobed {len(rows)} retired URL(s)", file=sys.stderr)
    for r in rows:
        tail = f" -> {r['location']}" if r["location"] else ""
        print(f"  {r['status']:>3} {r['verdict']:<22} {r['url']}{tail}",
              file=sys.stderr)
    print(f"\nSTILL LIVE (a real duplicate): {len(still)}", file=sys.stderr)
    print(f"UNKNOWN (could not classify):  {len(unknown)}", file=sys.stderr)
    return 1 if still or unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
