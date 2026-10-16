#!/usr/bin/env python3
"""Find OLD links: internal hrefs shipped on public pages that no longer resolve.

Reads the static export in ``out/`` - that is the exact HTML the crawler is served -
extracts every internal href, then probes each DISTINCT target against the live site
once. A link is "old" in two different ways and the difference matters:

  404/410  the target is gone. A crawler follows it, finds nothing, and the page that
           links it loses a little trust. This must be removed from the page.
  301/302  the target moved. The link still works, but it spends a redirect hop and
           Google treats the redirect chain as a weaker signal than a direct link.
           This should be rewritten to the final target.

Sitemap entries are checked separately, because a sitemap URL that does not return 200
is a hard Search Console error ("Couldn't fetch" / "Submitted URL not found") rather
than a soft quality issue.

Nothing is modified. Output is JSON on stdout plus a human summary on stderr.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
SITE = "https://wecare.digital"

HREF = re.compile(r'href\s*=\s*"([^"]+)"', re.I)
# Only the routes a crawler is invited to. Mirrors PUBLIC_EXACT + PUBLIC_PREFIXES in
# scripts/generate-sitemap.js; derived from the sitemap so it cannot drift from it.
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "whatsapp:")


def sitemap_routes() -> list[str]:
    xml = (OUT / "sitemap.xml").read_text()
    out = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
        p = loc[len(SITE):] if loc.startswith(SITE) else loc
        out.append(p or "/")
    return sorted(set(out))


def page_file(route: str) -> Path | None:
    rel = route.strip("/")
    cand = OUT / rel / "index.html" if rel else OUT / "index.html"
    return cand if cand.exists() else None


def internal_hrefs(html: str) -> set[str]:
    found = set()
    for raw in HREF.findall(html):
        h = raw.strip()
        if not h or h.startswith("#"):
            continue
        low = h.lower()
        if low.startswith(SKIP_SCHEMES):
            continue
        if low.startswith("//"):
            continue
        if low.startswith("http"):
            if not (low.startswith(SITE) or low.startswith("http://wecare.digital")
                    ):
                continue
            h = h.split("wecare.digital", 1)[1] or "/"
        if not h.startswith("/"):
            continue
        # drop query and fragment - they do not change whether the document exists
        h = h.split("#")[0].split("?")[0]
        if not h:
            continue
        if h.startswith("/_next/") or h.startswith("/images/") or h.startswith("/api/"):
            continue
        if re.search(r"\.(png|jpe?g|svg|webp|ico|css|js|json|xml|txt|pdf|woff2?)$", h, re.I):
            continue
        found.add(h)
    return found


def probe(path: str) -> tuple[str, int, str]:
    """HEAD-like probe that does NOT follow redirects, so a 301 stays visible."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):  # noqa: ANN002, ANN003
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(SITE + path, method="GET",
                                 headers={"User-Agent": "wecare-link-audit/1"})
    try:
        with opener.open(req, timeout=30) as r:
            return path, r.status, ""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.headers else ""
        return path, e.code, loc
    except Exception as e:  # noqa: BLE001
        return path, 0, type(e).__name__


def main() -> int:
    if not OUT.exists():
        sys.exit("out/ does not exist - run `npm run build` first")

    routes = sitemap_routes()
    print(f"sitemap routes: {len(routes)}", file=sys.stderr)

    # href -> set of pages that carry it
    carriers: dict[str, set[str]] = defaultdict(set)
    missing_pages = []
    for r in routes:
        f = page_file(r)
        if f is None:
            missing_pages.append(r)
            continue
        for h in internal_hrefs(f.read_text(errors="replace")):
            carriers[h].add(r)

    targets = sorted(carriers)
    print(f"public pages scanned: {len(routes) - len(missing_pages)}", file=sys.stderr)
    print(f"distinct internal link targets: {len(targets)}", file=sys.stderr)

    # A target is resolvable locally if the export emitted it. That is the cheap check
    # and catches everything a static host would 404 on.
    def emitted(p: str) -> bool:
        rel = p.strip("/")
        return (OUT / rel / "index.html").exists() if rel else (OUT / "index.html").exists()

    not_emitted = [t for t in targets if not emitted(t)]
    print(f"targets NOT in the export: {len(not_emitted)}", file=sys.stderr)

    # Probe live: every not-emitted target (they are the suspects) plus every sitemap
    # route, which must be 200.
    to_probe = sorted(set(not_emitted))
    live: dict[str, tuple[int, str]] = {}
    workers = int(os.environ.get("AUDIT_WORKERS", "8"))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for p, code, loc in ex.map(probe, to_probe):
            live[p] = (code, loc)

    gone, moved, errored = [], [], []
    for t in to_probe:
        code, loc = live[t]
        row = {"href": t, "status": code, "location": loc,
               "linkedFrom": sorted(carriers[t])[:12],
               "linkCount": len(carriers[t])}
        if code in (404, 410):
            gone.append(row)
        elif code in (301, 302, 307, 308):
            moved.append(row)
        elif code == 200:
            pass  # exists live but not in this export - fine
        else:
            errored.append(row)

    report = {
        "site": SITE,
        "sitemapRoutes": len(routes),
        "pagesScanned": len(routes) - len(missing_pages),
        "sitemapRoutesWithNoExportedPage": missing_pages,
        "distinctTargets": len(targets),
        "deadLinks": sorted(gone, key=lambda r: -r["linkCount"]),
        "redirectedLinks": sorted(moved, key=lambda r: -r["linkCount"]),
        "unresolved": errored,
    }
    print(json.dumps(report, indent=2))

    print("\n== DEAD internal links (404/410) ==", file=sys.stderr)
    for r in report["deadLinks"]:
        print(f"  {r['status']}  {r['href']}   on {r['linkCount']} page(s): "
              f"{', '.join(r['linkedFrom'][:4])}", file=sys.stderr)
    if not report["deadLinks"]:
        print("  none", file=sys.stderr)

    print("\n== REDIRECTED internal links (a hop that could be direct) ==", file=sys.stderr)
    for r in report["redirectedLinks"]:
        print(f"  {r['status']}  {r['href']} -> {r['location']}   on "
              f"{r['linkCount']} page(s): {', '.join(r['linkedFrom'][:4])}", file=sys.stderr)
    if not report["redirectedLinks"]:
        print("  none", file=sys.stderr)

    if report["unresolved"]:
        print("\n== could not classify ==", file=sys.stderr)
        for r in report["unresolved"]:
            print(f"  {r['status']}  {r['href']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
