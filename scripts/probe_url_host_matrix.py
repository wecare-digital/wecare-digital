#!/usr/bin/env python3
"""Probe the URL/host matrix and fail on any row that does not match its expectation.

WHAT THIS IS FOR. `scripts/retired_url_probe.py` answers one question - "did a retired URL
start answering 200 again" - and answers it well. This answers a different one: does the
WHOLE host-and-path surface still behave the way it was measured to behave, including the
rows that are supposed to be boring. Hosts, the 404 fallback, the provider passthroughs, the
staff entry, and the aliases the owner retired, all in one pass with one exit code.

ACTIVE ROUTES ARE JUDGED ON THEIR TERMINAL STATUS. `next.config.js` sets
`trailingSlash: true`, so an
extensionless path ALWAYS 301s to add the slash before any page lookup happens. A probe that
records the first status reads `/admin` as "301, fine" when the chain actually terminates on
a 404 - and reads it as "301, fine" equally when the chain terminates on a staff login at
200, which is the exact defect this matrix was built to catch. So every row follows the chain
to a terminal response and judges THAT, while still recording the hops so a new hop is
visible. Retired-host rows expecting status 0 require no HTTP response on the first and
only hop: a redirect followed by a connection failure still means the retired host answered.

LOOPS ARE CHECKED, NOT ASSUMED. A redirect whose target redirects back is the one failure a
status-code assertion cannot see: both codes look correct in isolation. Every chain is walked
with a seen-set and a hop budget, and a repeat is a hard failure.

READ-ONLY. HTTP GET and POST against the public site, nothing else. No AWS call, no secret
read, no write of any kind. The POST rows exist because the provider webhooks are delivered
by POST and a rewrite can behave differently per method - `GET /mcp` is 405 while
`POST /mcp` is 400, which is only visible if both are probed.

CURRENT POLICY: current pages resolve normally. Missing pages return HTTP 404 and the
shared browser fallback goes home. No individual retired-path redirects are maintained.
Wildcard home forwarding is restored, with two exact hostname exclusions. Their expected
status 0 records no HTTP response; it does not prove NXDOMAIN or distinguish DNS from TLS
failure. An HTTP 503 from an egress proxy remains 503 and fails that expectation. Verify
the TXT-only exclusions and CloudFront configuration separately through their control planes.

Usage:
    .venv/bin/python scripts/probe_url_host_matrix.py            # human table
    .venv/bin/python scripts/probe_url_host_matrix.py --json     # machine readable
    .venv/bin/python scripts/probe_url_host_matrix.py --only api # filter rows by group
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://wecare.digital"
WWW = "https://www.wecare.digital"
UA = "wecare-url-host-matrix-probe/1"
MAX_HOPS = 5

# Every entry here auto-generates a row asserting a TERMINAL 200 at the URL itself. `/shop/` is
# back in this tuple as of 2026-10-10: the owner restored the catalogue index, so it serves the
# listing at 200 again rather than 301ing to home. The unslashed `/shop` and `/shop/index.html`
# get their own rows in `matrix()` asserting they terminate at the slashed `/shop/`, and
# `/shop/file-assist/` keeps its row asserting a product page still resolves at itself.
PUBLIC_PAGES = (
    "/", "/checkout/", "/orders/", "/blog/", "/contact/", "/checkout/status/",
    "/grahak-os/", "/vayulok/", "/terms/", "/anew/", "/shop/guided-resolution/", "/shop/",
)


def _row(group: str, url: str, expect: int, why: str, *, method: str = "GET",
         terminal_url: str | None = None, body_contains: tuple[str, ...] = (),
         informational: bool = False) -> dict:
    """`informational=True` records the measured value WITHOUT failing the run.

    Reserved for a host whose configuration belongs to a third party, where a mismatch is
    news rather than a defect of ours. Use it sparingly: every other row is a hard gate, and
    the value of this harness is that a red run means something. Do NOT reach for this to
    silence one of our own rows - a drifting expectation on a surface we control is exactly
    what this script exists to catch.
    """
    return {
        "group": group, "method": method, "url": url, "expect_status": expect,
        "expect_terminal_url": terminal_url, "expect_body_contains": body_contains,
        "why": why, "informational": informational,
    }


def matrix() -> list[dict]:
    rows: list[dict] = []

    # ── hosts ────────────────────────────────────────────────────────────────────────
    rows.append(_row("host", f"{SITE}/", 200, "the canonical home"))
    # www IS A RETIRED NAMED HOST CAUGHT BY THE WILDCARD HOME FALLBACK. The owner excluded www
    # when restoring the wildcard on 2026-10-19, and e6fead218 (2026-10-24, "Keep only the apex
    # plus intentional mta-sts and sip service hosts") removed the fallback exclusions. Since then
    # www, like every unused subdomain, gets CloudFront E1IY68ICLQP3PY's fixed 302 to the apex
    # home, for every path. That commit also set WWW to the apex here, which turned these rows
    # into "the apex has no HTTP service" - five failures on a correct site. WWW is the www host
    # again, and the rows assert the fallback: every www URL ends at the bare apex home.
    rows.append(_row("host", f"{WWW}/", 200, "retired www lands on the apex home via the wildcard fallback",
                     terminal_url=f"{SITE}/"))
    rows.append(_row("host", f"{WWW}/contact/", 200, "a www path also lands on the apex HOME, not a page",
                     terminal_url=f"{SITE}/"))
    rows.append(_row("host", f"{WWW}/blog/", 200, "retired www path, second sample",
                     terminal_url=f"{SITE}/"))
    rows.append(_row("host", f"http://{SITE.split('://')[1]}/", 200,
                     "http apex reaches https apex", terminal_url=f"{SITE}/"))
    # The apex is the Cognito OAuth redirect URI:
    # src/pages/_app.tsx registers `redirectSignIn`/`redirectSignOut` as
    # NEXT_PUBLIC_APP_URL || 'https://wecare.digital/', and that URI is registered on the
    # stack-wecare-digital-web client. The apex remains the sign-in round trip's landing
    # surface; www has no active sign-in route. `zzz`-prefixed values are deliberately
    # invalid - nothing is exchanged, the probe only measures the HTTP response.
    rows.append(_row("host", f"{SITE}/?code=zzztest&state=zzz", 200,
                     "the Cognito OAuth redirect URI itself (_app.tsx redirectSignIn)"))
    # The fallback's Location is a fixed https://wecare.digital/, so the query is dropped: the
    # exact terminal URL proves an OAuth code sent to www is never carried to the apex.
    rows.append(_row("host", f"{WWW}/?code=zzztest&state=zzz", 200,
                     "retired www has no OAuth landing route; the code is dropped",
                     terminal_url=f"{SITE}/"))

    # ── the 404 fallback ─────────────────────────────────────────────────────────────
    # 404 is load-bearing and must never become 200: a non-404 status on /<*> matches
    # unconditionally and would shadow all ~123 exported pages with one rule.
    rows.append(_row("fallback", f"{SITE}/definitely-not-a-page", 404,
                     "trailing-slash 301 then a real 404, judged on the terminal hop"))
    rows.append(_row("fallback", f"{SITE}/definitely-not-a-page/", 404,
                     "must serve 404.html with noindex and the apex canonical",
                     body_contains=('"page":"/404"', 'name="robots"', 'noindex')))
    rows.append(_row("fallback", f"{SITE}/404/", 200, "the exported page itself"))
    rows.append(_row("fallback", f"{SITE}/cart/", 404,
                     "retired cart route must use the same not-found fallback as removed pages",
                     body_contains=('"page":"/404"', 'noindex')))

    # ── the staff entry, untouched ──────────────────────────────────────────────────
    # Not hidden and not opened. This task does not touch authorization, and a 200 here is
    # the Authenticator shell doing its job - it is only a defect when a CUSTOMER path
    # resolves to it, which the legacy-workspace rows above are what guard.
    rows.append(_row("staff", f"{SITE}/workspace/", 200, "the real staff entry, unchanged"))
    rows.append(_row("staff", f"{SITE}/workspace/access/", 200, "staff sign-in, unchanged"))

    # ── customer auth and public pages ──────────────────────────────────────────────
    rows.append(_row("public", f"{SITE}/auth", 200, "the canonical CUSTOMER auth flow",
                     body_contains=("WECARE.DIGITAL", "Sign in to WECARE.DIGITAL")))
    rows.append(_row("fallback", f"{SITE}/account/sign-in/", 404,
                     "retired customer sign-in URL is removed; /auth is the only sign-in URL"))
    for path in PUBLIC_PAGES:
        rows.append(_row("public", f"{SITE}{path}", 200, "a live public page"))

    # ── the restored catalogue index, and the product pages beside it ──────────────────
    # Owner instruction 2026-10-10: /shop/ is browsable again (reversing the 2026-10-04
    # withdrawal), while every /shop/<slug>/ product page keeps rendering and keeps its
    # add-to-cart. /shop/ itself is in PUBLIC_PAGES above, so it already has a terminal-200-at-self
    # row.
    #
    # THE OTHER TWO SPELLINGS reach the catalogue, not home. `/shop` 301s to `/shop/` under
    # next.config trailingSlash, so its terminal URL is the slashed /shop/. `/shop/index.html` is
    # the file itself, which Amplify serves at 200 WITHOUT redirecting - as it does every
    # directory's index.html (measured 2026-10-26 on /, /contact/ and /blog/ too). Expecting it
    # to end at /shop/ failed this row on a correct site, so it is judged on its body instead:
    # the catalogue page's canonical names /shop/, which also proves it is not the home page.
    rows.append(_row("public", f"{SITE}/shop", 200,
                     "unslashed /shop reaches the catalogue index at /shop/",
                     terminal_url=f"{SITE}/shop/"))
    rows.append(_row("public", f"{SITE}/shop/index.html", 200,
                     "the index.html file serves the catalogue index, canonical to /shop/",
                     terminal_url=f"{SITE}/shop/index.html",
                     body_contains=('<link rel="canonical" href="https://wecare.digital/shop/"',)))
    # The product page still resolves at itself, proving no /shop/<*> wildcard swept it up - the
    # live counterpart of the no-wildcard assertion in test_url_host_routing_rules.py.
    rows.append(_row("public", f"{SITE}/shop/file-assist/", 200,
                     "a product page resolves at itself, not caught by any /shop rule",
                     terminal_url=f"{SITE}/shop/file-assist/"))

    # ── passthrough rewrites: the payment-critical rows ─────────────────────────────
    # These statuses ARE the contract. 401 is a signature rejection travelling back from the
    # Lambda - a meaningful answer. If one of these ever returns a PAGE status (200 HTML, or a
    # 302 to a page) the rewrite has been shadowed by a redirect and provider delivery is
    # broken, which is why they are probed by their real method.
    rows.append(_row("api", f"{SITE}/api/razorpay-webhook", 401,
                     "payment webhook: signature rejection, not a page", method="POST"))
    rows.append(_row("api", f"{SITE}/api/auth/validate", 401, "auth route reachable",
                     method="POST"))
    rows.append(_row("api", f"{SITE}/api/payments/webhook", 404, "no such route, from the API",
                     method="POST"))
    rows.append(_row("api", f"{SITE}/api/wa-business/webhooks", 401,
                     "WhatsApp webhook delivery address", method="POST"))
    rows.append(_row("api", f"{SITE}/api/webhook/sinch-rcs", 200, "RCS webhook verification GET"))
    # ADDED 2026-10-01, third convergence pass. `auth/validate` above was the ONLY protected
    # operational row, which is too thin to evidence "unauthenticated REJECTION semantics are
    # preserved" for the class as a whole: one route can keep answering 401 while a rewrite
    # change quietly turns its neighbours into pages. These three are probed by GET and asserted
    # on the BODY as well as the status, because 401 alone cannot tell the API's own rejection
    # from an edge-level one - the JSON is what proves the request reached the Lambda.
    for protected in ("/api/invoices", "/api/contacts", "/api/native-catalog/products"):
        rows.append(_row("api", f"{SITE}{protected}", 401,
                         "protected operational endpoint: rejects an unauthenticated read with "
                         "the API's own JSON, not a page",
                         body_contains=("No authorization token provided",)))
    # ADDED 2026-10-01, third convergence pass. Two surfaces the task brief names that have NO
    # live route yet. They are probed so the document can say "unprovisioned, measured" instead
    # of leaving a reader unable to tell an absent route from an unchecked one. A 404 here is the
    # CORRECT answer and the row exists to notice it changing: the day either ships, this row
    # fails and the matrix has to be updated deliberately rather than drifting.
    #   signed receipt links   - no receipt path is referenced from src/ either
    #   verified-email callback - the function is built but deliberately not provisioned, and is
    #                             owned by the customer-registration workstream, not this task
    rows.append(_row("api", f"{SITE}/api/checkout/download-receipt", 404,
                     "signed receipt link: NOT provisioned yet - 404 is the measured truth"))
    rows.append(_row("api", f"{SITE}/api/auth/verify-email", 404,
                     "verified-email callback: built but NOT provisioned (other workstream)"))
    rows.append(_row("api", f"{SITE}/mcp", 405, "MCP rejects GET"))
    rows.append(_row("api", f"{SITE}/mcp", 400, "MCP accepts POST and rejects an empty body",
                     method="POST"))
    rows.append(_row("api", f"{SITE}/get/o/stream/media/m/wecare-digital.png", 200,
                     "media CDN passthrough"))
    # An unknown short code answers 302 to the canonical homepage, one hop.
    # Active short codes continue to use their stored, validated destination.
    rows.append(_row("api", f"{SITE}/r/zzznotacode", 200, "short-link miss lands on home",
                     terminal_url=f"{SITE}/"))
    # Unknown API paths must remain missing routes, regardless of segment count.
    rows.append(_row("api", f"{SITE}/api/definitely-no-route", 404,
                     "unknown single-segment API path stays 404"))
    rows.append(_row("api", f"{SITE}/api/definitely/no/route", 404,
                     "unknown multi-segment API path stays 404"))

    # mta-sts is the MTA-STS policy endpoint under mode: enforce. Probed at / ONLY, read-only,
    # to confirm nothing about it moved. Its policy path is not touched by this or any probe.
    rows.append(_row("subdomain", "https://mta-sts.wecare.digital/", 403,
                     "email auth is fail-closed - this must not change"))

    return rows


def _open(url: str, method: str):
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):  # noqa: ANN002, ANN003
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    data = b"" if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA})
    return opener.open(req, timeout=30)


# 256 KiB, not 64. The not-found row asserts '"page":"/404"', which Next writes into the data
# script at the END of the page: measured at byte 81,154 of the 81,317-byte 404 page on
# 2026-10-26, so a 64 KiB prefix failed the row on a correct response.
BODY_PREFIX_BYTES = 262144


def _one_hop(url: str, method: str) -> tuple[int, str, str]:
    """Return (status, location, body-prefix) without following the redirect."""
    try:
        with _open(url, method) as response:
            body = ""
            if response.status == 200:
                body = response.read(BODY_PREFIX_BYTES).decode("utf-8", "replace")
            return response.status, response.headers.get("Location", "") or "", body
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(BODY_PREFIX_BYTES).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a bodyless error response is normal
            pass
        location = exc.headers.get("Location", "") if exc.headers else ""
        return exc.code, location or "", body
    except Exception as exc:  # noqa: BLE001 - DNS/TLS failure is a measurable outcome
        return 0, "", type(exc).__name__


def follow(row: dict) -> dict:
    """Walk the chain to a terminal response. A repeated URL is a loop and a hard failure."""
    url, method = row["url"], row["method"]
    hops: list[dict] = []
    seen: list[str] = []
    loop = False

    while True:
        if url in seen:
            loop = True
            break
        seen.append(url)
        status, location, body = _one_hop(url, method)
        hops.append({"url": url, "status": status, "location": location})
        if status in (301, 302, 303, 307, 308) and location:
            url = urllib.parse.urljoin(url, location)
            # A 303, or a 301/302 on a POST, is followed as GET by every real client.
            if status == 303 or (status in (301, 302) and method == "POST"):
                method = "GET"
            if len(hops) >= MAX_HOPS:
                break
            continue
        break

    terminal = hops[-1]
    failures: list[str] = []
    if loop:
        failures.append(f"REDIRECT LOOP: {' -> '.join(seen)}")
    if len(hops) >= MAX_HOPS and terminal["status"] in (301, 302, 307, 308):
        failures.append(f"chain did not terminate within {MAX_HOPS} hops")
    if terminal["status"] != row["expect_status"]:
        failures.append(f"terminal status {terminal['status']}, expected {row['expect_status']}")
    if row["expect_status"] == 0 and (len(hops) != 1 or hops[0]["status"] != 0):
        failures.append("retired host returned an HTTP response")
    if row["expect_terminal_url"] and terminal["url"] != row["expect_terminal_url"]:
        failures.append(f"terminal url {terminal['url']}, expected {row['expect_terminal_url']}")
    for needle in row["expect_body_contains"]:
        if needle not in body:
            failures.append(f"body missing {needle!r}")

    # An informational row still reports every mismatch it found - it just does not fail the
    # run. The mismatches move to `notes` rather than being discarded, so a reader sees the
    # drift instead of a silently green row.
    informational = row.get("informational", False)
    notes = failures if informational else []
    return {
        "group": row["group"], "method": row["method"], "url": row["url"],
        "expect_status": row["expect_status"], "status": terminal["status"],
        "terminal_url": terminal["url"], "hops": hops, "hop_count": len(hops),
        "why": row["why"], "informational": informational,
        "ok": True if informational else not failures,
        "failures": [] if informational else failures,
        "notes": notes,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe the URL/host matrix.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--only", help="probe one group only (host, fallback, legacy-workspace, "
                                       "retired-content, staff, public, api, api-finding, subdomain)")
    args = parser.parse_args(argv)

    rows = matrix()
    if args.only:
        rows = [r for r in rows if r["group"] == args.only]
        if not rows:
            print(f"no rows in group {args.only!r}", file=sys.stderr)
            return 2

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(follow, rows))

    failed = [r for r in results if not r["ok"]]

    if args.json:
        print(json.dumps({
            "probed": len(results), "failed": len(failed),
            "results": results,
        }, indent=2))
    else:
        width = max(len(r["url"]) for r in results)
        current = None
        for result in results:
            if result["group"] != current:
                current = result["group"]
                print(f"\n── {current} ──")
            # An informational row that drifted is marked NOTE, not ok - it must not read as a
            # clean pass, or downgrading a row becomes a way to hide a change.
            if result["ok"] and result.get("notes"):
                mark = "NOTE"
            elif result["ok"]:
                mark = "ok  "
            else:
                mark = "FAIL"
            chain = " -> ".join(str(h["status"]) for h in result["hops"])
            print(f"  {mark} {result['method']:<4} {result['url']:<{width}} "
                  f"[{chain}] expect {result['expect_status']}")
            for failure in result["failures"]:
                print(f"       !! {failure}")
            for note in result.get("notes", []):
                print(f"       ~~ {note} (informational: {result['why']})")
        noted = [r for r in results if r["ok"] and r.get("notes")]
        print(f"\nprobed {len(results)} row(s); {len(failed)} failed; "
              f"{len(noted)} informational row(s) drifted")

    for result in failed:
        print(f"FAIL {result['method']} {result['url']}: {'; '.join(result['failures'])} "
              f"({result['why']})", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
