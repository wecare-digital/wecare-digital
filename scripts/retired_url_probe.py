#!/usr/bin/env python3
"""Probe arbitrary missing or active public paths without maintaining an old URL list.

Supply paths from a current crawl, an access log, or Search Console as arguments.
With no arguments the script probes synthetic unknown URLs and the current
public catalogue. HTTP checks do not establish browser-side navigation.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://wecare.digital"


def active_paths():
    catalogue = json.loads((ROOT / "config/public-pages.json").read_text())
    return {page["path"].rstrip("/") or "/" for page in catalogue["pages"]}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wecare-public-url-probe/3"})
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
        return "ACTIVE" if status == 200 else "REGISTERED-MISMATCH"
    if status == 404 and '"page":"/404"' in body and 'noindex' in body:
        return "UNASSIGNED-404"
    if status == 200:
        return "UNREGISTERED-200"
    return "UNEXPECTED-RESPONSE"


def public_path(value):
    parsed = urlsplit(value)
    if (parsed.scheme or parsed.netloc) and (
        parsed.scheme != "https" or parsed.netloc != "wecare.digital"
    ):
        raise argparse.ArgumentTypeError("Only paths on the canonical public origin")
    path = parsed.path.rstrip("/") or "/"
    if not path.startswith("/") or path.startswith("//"):
        raise argparse.ArgumentTypeError("Use an absolute public page path")
    if any(path == root or path.startswith(root + "/")
           for root in ("/api", "/get", "/r", "/workspace", "/ws")):
        raise argparse.ArgumentTypeError("Protected infrastructure/workspace is outside this audit")
    if path in ("/auth/state", "/auth/step"):
        raise argparse.ArgumentTypeError("Auth endpoints are outside this audit")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=public_path)
    args = parser.parse_args()
    active = active_paths()
    probe_name = "/qa-missing-" + uuid4().hex
    paths = sorted(set(args.paths or [*active, probe_name, probe_name + "/nested",
                                      "/shop" + probe_name]))

    def check(path):
        registered = path in active
        status, location, body = probe(SITE + path.rstrip("/") + "/")
        return {"path": path, "registered": registered, "http": status,
                "location": location, "verdict": classify(status, body, registered)}

    with cf.ThreadPoolExecutor(max_workers=6) as executor:
        rows = list(executor.map(check, paths))
    print(json.dumps({"cases": len(rows), "results": rows,
                      "browserNavigationVerified": False}, indent=2))
    good = {"UNASSIGNED-404", "ACTIVE"}
    return int(any(row["verdict"] not in good for row in rows))


if __name__ == "__main__":
    sys.exit(main())
