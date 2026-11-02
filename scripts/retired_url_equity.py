#!/usr/bin/env python3
"""Find every URL Google still has impressions for that this site no longer serves.

WHY THIS IS NOT scripts/retired_url_probe.py. That script probes a HAND-WRITTEN list
assembled from this repository's own record of removals, and it answers one question:
"did we leave a retired page serving 200?" It is a regression guard, and it can only
ever know about removals somebody wrote down.

This script asks the opposite question, and takes its list from Google rather than from
us: "which URLs is Google still SHOWING, that we answer with a 404?" Those are the ones
losing accumulated ranking, and the repo has no record of most of them because they were
pages of the previous site that never existed in this codebase at all.

The distinction is load-bearing. A 404 is the correct answer for a page that was deleted
because it was wrong. It is the WRONG answer for a page that was replaced, because a 404
discards the link equity instead of passing it to the replacement - and equity is the one
thing a new export cannot regenerate on its own.

THE PROPERTY THAT MATTERS IS THE www ONE. There are two Search Console properties:

    https://wecare.digital/    480 days of history   the previous site
    https://wecare.digital/        created 2026-09-30    the current export, no backfill

Reading only the apex property shows zero impressions and invites the conclusion that the
site is invisible to Google. It is not - the history lives under www, which now 301s to
the apex. So this script queries BOTH and merges, keyed on path.

OUTPUT is a verdict per path:

    SERVED        answers 200 - nothing to do
    REDIRECTED    answers 301/308 - equity already consolidated
    RECOVERABLE   answers 404 AND has impressions - this is the actionable set
    GONE-QUIET    answers 404 with no impressions - correctly dead, leave it

Read-only. Does not change live Amplify Hosting customRules; any redirect changes
require a separate review of hosting configuration. No secret value is read or printed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

SA = "automation@wecaredigitalbw.iam.gserviceaccount.com"
SCOPE = "https://www.googleapis.com/auth/webmasters"

APEX = "https://wecare.digital"
PROPERTIES = ["https://wecare.digital/"]

#: GSC keeps 16 months. Ask for more and the API silently clamps, which is fine, but an
#: explicit window makes the report reproducible.
WINDOW_DAYS = 490


def token() -> str:
    p = subprocess.run(
        ["gcloud", "auth", "print-access-token",
         f"--impersonate-service-account={SA}", f"--scopes={SCOPE}"],
        capture_output=True, text=True, timeout=180)
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(f"could not mint a token: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def gsc(tok: str, prop: str, body: dict) -> dict:
    url = ("https://www.googleapis.com/webmasters/v3/sites/"
           f"{urllib.parse.quote(prop, safe='')}/searchAnalytics/query")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"__error__": f"{e.code} {e.read()[:400].decode('utf8', 'replace')}"}


def pages(tok: str, prop: str, days: int) -> tuple[list[dict], str]:
    """Every page row in the window, paged out to exhaustion."""
    end = date.today() - timedelta(days=2)      # GSC lags ~2 days
    start = end - timedelta(days=days)
    rows: list[dict] = []
    start_row = 0
    while True:
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
                "dimensions": ["page"], "rowLimit": 25000, "startRow": start_row}
        got = gsc(tok, prop, body)
        if "__error__" in got:
            return rows, got["__error__"]
        batch = got.get("rows", [])
        rows.extend(batch)
        if len(batch) < 25000:
            break
        start_row += len(batch)
    return rows, ""


def path_of(url: str) -> str:
    p = urllib.parse.urlsplit(url).path or "/"
    return p


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # noqa: ANN002, ANN003
        return None


def _one_hop(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(
        url, headers={"User-Agent": "wecare-retired-url-equity/1"})
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Location", "") if e.headers else "")
    except Exception as e:  # noqa: BLE001
        return 0, type(e).__name__


def probe(path: str) -> tuple[str, int, list[str], int]:
    """Follow the chain to its TERMINAL status, and report both.

    Stopping at the first hop is the mistake this function exists to avoid, and it is
    not a hypothetical one - the first version of this script made it and reported 151
    paths as safely "REDIRECTED". The site runs `trailingSlash: true`, so EVERY extension-
    less path gets a global 301 appending the slash before any page even gets looked for.
    `/bnb-club` answers 301 -> `/bnb-club/`, which answers 404. One hop sees a 301 and
    concludes the equity was consolidated; the crawler sees the 404 and discards it.

    So the only status that means anything here is the last one in the chain.
    """
    chain: list[str] = []
    url = APEX + path
    code = 0
    for _ in range(10):
        code, loc = _one_hop(url)
        if code not in (301, 302, 307, 308) or not loc:
            break
        nxt = urllib.parse.urljoin(url, loc)
        chain.append(nxt)
        if nxt == url:
            break
        url = nxt
    return path, code, chain, len(chain)


def verdict(code: int, hops: int, impressions: float) -> str:
    if code == 200:
        #: A 200 reached only by redirecting is still a recovery, but it is worth
        #: distinguishing from a path the site serves directly, because the first is a
        #: rule someone can delete by accident and the second is a real page.
        return "SERVED" if hops == 0 else "REDIRECTED-200"
    if code in (404, 410):
        return "RECOVERABLE" if impressions > 0 else "GONE-QUIET"
    return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--json", action="store_true",
                    help="emit the merged table as JSON on stdout")
    ap.add_argument("--min-impressions", type=int, default=1,
                    help="floor for calling a 404 RECOVERABLE in the summary")
    args = ap.parse_args()

    tok = token()

    merged: dict[str, dict] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0, "position_weighted": 0.0,
                 "seen_as": set()})
    errors: dict[str, str] = {}

    for prop in PROPERTIES:
        rows, err = pages(tok, prop, args.days)
        if err:
            errors[prop] = err
            print(f"  {prop}: ERROR {err}", file=sys.stderr)
            continue
        print(f"  {prop}: {len(rows)} page row(s)", file=sys.stderr)
        for r in rows:
            url = r["keys"][0]
            m = merged[path_of(url)]
            m["clicks"] += r.get("clicks", 0)
            m["impressions"] += r.get("impressions", 0)
            m["position_weighted"] += r.get(
                "position", 0) * r.get("impressions", 0)
            m["seen_as"].add(url)

    if not merged:
        print("no page rows from either property - cannot proceed", file=sys.stderr)
        return 1

    paths = sorted(merged)
    print(f"\nprobing {len(paths)} distinct path(s) against {APEX}",
          file=sys.stderr)

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for path, code, chain, hops in ex.map(probe, paths):
            merged[path]["status"] = code
            merged[path]["chain"] = chain
            merged[path]["hops"] = hops

    table = []
    for path in paths:
        m = merged[path]
        impr = m["impressions"]
        table.append({
            "path": path,
            "clicks": int(m["clicks"]),
            "impressions": int(impr),
            "avg_position": round(m["position_weighted"] / impr, 1) if impr else None,
            "status": m.get("status", 0),
            "hops": m.get("hops", 0),
            "chain": m.get("chain", []),
            "final": (m.get("chain") or [APEX + path])[-1],
            "verdict": verdict(m.get("status", 0), m.get("hops", 0), impr),
            "seen_as": sorted(m["seen_as"]),
        })

    table.sort(key=lambda r: (-r["impressions"], r["path"]))

    if args.json:
        print(json.dumps({"errors": errors, "rows": table}, indent=2))

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in table:
        buckets[r["verdict"]].append(r)

    print("", file=sys.stderr)
    for name in ("RECOVERABLE", "UNKNOWN", "GONE-QUIET",
                 "REDIRECTED-200", "SERVED"):
        rows = buckets.get(name, [])
        if not rows:
            continue
        impr = sum(r["impressions"] for r in rows)
        print(f"{name:<12} {len(rows):>5} path(s)  {impr:>7} impression(s)",
              file=sys.stderr)

    recoverable = [r for r in buckets.get("RECOVERABLE", [])
                   if r["impressions"] >= args.min_impressions]
    if recoverable:
        print("\nRECOVERABLE - 404 today, still earning impressions:", file=sys.stderr)
        print(f"  {'impr':>7} {'clicks':>6} {'pos':>5}  path", file=sys.stderr)
        for r in recoverable:
            pos = f"{r['avg_position']:.1f}" if r["avg_position"] else "-"
            print(f"  {r['impressions']:>7} {r['clicks']:>6} {pos:>5}  {r['path']}",
                  file=sys.stderr)
        print(f"\n  total recoverable impressions: "
              f"{sum(r['impressions'] for r in recoverable)}", file=sys.stderr)

    unknown = buckets.get("UNKNOWN", [])
    if unknown:
        print(f"\nUNKNOWN - could not classify {len(unknown)}:", file=sys.stderr)
        for r in unknown:
            print(f"  {r['status']} {r['path']}", file=sys.stderr)

    return 1 if (recoverable or unknown or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
