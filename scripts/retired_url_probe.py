#!/usr/bin/env python3
"""Audit historical public paths against current registration, without reserving names.

HTTP probes do not prove browser navigation; run verify_404_home_handoff.mjs
for that. Protected service and workspace names are reported separately.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://wecare.digital"


def inventory():
    history = json.loads((ROOT / "config/historical-route-paths.json").read_text())
    catalogue = json.loads((ROOT / "config/public-pages.json").read_text())
    active = {page["path"].rstrip("/") or "/" for page in catalogue["pages"]}
    return history, active


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wecare-retired-url-probe/2"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            return response.status, response.headers.get("Location", ""), ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", ""), (
            exc.read(262144).decode("utf-8", "replace") if exc.code == 404 else ""
        )
    except Exception as exc:
        return 0, type(exc).__name__, ""


def classify(status, body, registered):
    if status == 0:
        return "UNVERIFIED"
    if registered:
        return "REUSED-ACTIVE" if status == 200 else "REGISTERED-MISMATCH"
    if status == 404 and '"page":"/404"' in body and 'noindex' in body:
        return "UNASSIGNED-404"
    return "UNEXPECTED-RESPONSE"


def main():
    history, active = inventory()
    protected = set(history["infrastructureAdjacent"])
    public = history["publicPaths"]
    jobs = [(path, path in active) for path in public if path not in protected]
    jobs.append(("/definitely-not-a-page", False))

    def check(job):
        path, registered = job
        status, location, body = probe(SITE + path + "/")
        return {"path": path, "registered": registered, "http": status,
                "location": location, "verdict": classify(status, body, registered)}

    with cf.ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(check, jobs))
    report = {
        "knownHistoricalPublic": len(public),
        "knownHistoricalWorkspace": len(history["workspacePaths"]),
        "knownHistoricalTotal": len(public) + len(history["workspacePaths"]),
        "protectedInfrastructureAdjacent": sorted(protected),
        "workspaceNotPublicReuse": history["workspacePaths"],
        "registeredHistoricalPublic": len(set(public) & active),
        "historicalPublicResults": rows[:-1],
        "unknownControl": rows[-1],
        "browserNavigationVerified": False,
    }
    print(json.dumps(report, indent=2))
    good = {"UNASSIGNED-404", "REUSED-ACTIVE"}
    return int(any(row["verdict"] not in good for row in rows))


if __name__ == "__main__":
    sys.exit(main())
