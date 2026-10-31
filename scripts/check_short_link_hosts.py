#!/usr/bin/env python3
"""Prove the apex short-link path resolves, and that the retired subdomain stays retired.

Why this is a live probe and not a unit test
--------------------------------------------
Short-link resolution is not a property of the handler. It is the product of three
independent pieces of live configuration, and the handler is only one of them:

  1. `GET /r/{code}` on HTTP API `zllr9lrg7j`
  2. the Amplify custom rule `/r/<*>` -> the API, which must sit BEFORE the
     `/<*>` -> `/index.html` SPA catch-all or it can never match
  3. the `live` alias of `stack-wecare-url-shortener` pointing at current code

A unit test can assert none of that. Any of the three can be removed by a console
click or a well-meaning cleanup, and they fail silently - the SPA catch-all in
particular answers `200` with the app shell, so a broken short link looks like a
working page rather than an error.

What changed on 2026-09-28, and why this script was inverted
-----------------------------------------------------------
There used to be a fourth piece: the `wecare.digital/r` API Gateway custom domain.
This script asserted that host still resolved, and said in as many words "do not
'fix' this by retiring the old host; it is the links already sent that cannot be
changed". That was the right call on the evidence available, and the owner
subsequently made the opposite one: the Route 53 record was deleted under
`YES R53-DELETE-001` (before-state in
`docs/execution/snapshots/route53-r-subdomain-before-delete-20260928.json`).

So the old assertion now fails on a deliberate decision rather than on a defect,
and a guard that fails for a reason nobody intends to act on stops being read.

The consequence is real and is NOT what this script is for: every short link already
delivered on `wecare.digital/r` - printed material, sent SMS, RCS cards already on
handsets - is dead, and no configuration change here can recall them. That is recorded
in `docs/media-bucket-merge.md` and the change-authority matrix. What this script now
does is narrower and still worth having:

  wecare.digital/r/<code>    MUST resolve - this is what we mint, and all we serve
  wecare.digital/r/<code>    MUST NOT resolve - retirement must stay complete

The second check is not spite. A retired host that quietly comes back - an IaC deploy
re-creating the alias record is the likely route, which is why those constructs were
deleted from the retired link CDK before that file itself was removed - would start serving links again from a
certificate and mapping nobody is maintaining. Either state is defensible; drifting
between them silently is not.

`operations/system-cleanup` still protects the link tables from factory reset, on the
same grounds as before: the codes themselves remain valid on the apex path.

Usage
-----
    python scripts/check_short_link_hosts.py
    python scripts/check_short_link_hosts.py --code wa

Exit 0 means the apex forms resolve and the retired host does not. Non-zero names
the mismatch.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

APEX = "wecare.digital"
LEGACY_HOST = "wecare.digital/r"

# A code that must exist. `wa` is the WhatsApp entry point embedded in the SMS and
# voice auto-replies, so if any single code matters it is this one.
DEFAULT_CODE = "wa"

# A code that must NOT exist, to prove the allow-list is real and that a miss is
# handled rather than 404ing or serving the SPA shell.
ABSENT_CODE = "zz-no-such-code-probe"

# Must match url-shortener.FALLBACK_URL exactly. Unknown, expired, and
# inactive codes must fall back to the canonical homepage, not Contact or Orders.
# This check does not change active codes: they keep their saved destinations.
FALLBACK = "https://wecare.digital/"
TIMEOUT = 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Capture the redirect instead of following it. Following it would test the
    destination site, which is not what is under test here."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def probe(url: str) -> tuple[int, str | None]:
    try:
        with _opener.open(url, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location")
    except Exception as exc:  # noqa: BLE001
        return 0, f"error: {type(exc)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default=DEFAULT_CODE,
                    help=f"short code that must resolve (default: {DEFAULT_CODE})")
    args = ap.parse_args()
    code = args.code

    # The forms we actually serve. Both are on the apex, because the handler accepts
    # `/r/{code}` and a bare `/{code}` and Amplify proxies both.
    forms = [
        (f"https://{APEX}/r/{code}", "apex path (canonical, what we mint)"),
    ]

    print(f"code under test : {code}\n")
    results = []
    for url, label in forms:
        status, location = probe(url)
        results.append((url, label, status, location))
        print(f"  {status:>3}  {url}")
        print(f"       {label}")
        print(f"       -> {location}")

    targets = {loc for _, _, st, loc in results if st in (301, 302, 307, 308)}
    redirecting = [r for r in results if r[2] in (301, 302, 307, 308)]

    print("\n  absent-code handling (must fall back, not 404 or serve the app shell)")
    status, location = probe(f"https://{APEX}/r/{ABSENT_CODE}")
    miss_ok = status in (301, 302) and location == FALLBACK
    print(f"  {status:>3}  https://{APEX}/r/{ABSENT_CODE}\n"
          f"       -> {location}  {'ok' if miss_ok else 'UNEXPECTED'}")

    # The retired host must stay retired. `0` from probe() means the connection never
    # got made, which for a hostname with no DNS record is exactly what we want to see.
    print("\n  retired subdomain (must NOT resolve)")
    legacy_status, legacy_detail = probe(f"https://{LEGACY_HOST}/{code}")
    legacy_gone = legacy_status == 0
    print(f"  {legacy_status:>3}  https://{LEGACY_HOST}/{code}\n"
          f"       -> {legacy_detail}  "
          f"{'ok - retired, as intended' if legacy_gone else 'UNEXPECTED - it answered'}")

    print()
    failures = []
    if len(redirecting) != len(forms):
        broken = [u for u, _, st, _ in results if st not in (301, 302, 307, 308)]
        failures.append("these forms did not redirect: " + ", ".join(broken))
    if len(targets) > 1:
        failures.append(f"forms disagree on the target: {sorted(targets)}")
    if not miss_ok:
        failures.append("an unknown code did not fall back to " + FALLBACK)
    if not legacy_gone:
        failures.append(
            f"{LEGACY_HOST} answered with status {legacy_status}. It was retired on "
            "2026-09-28; something has re-created its DNS record or custom domain. "
            "Check whether an IaC deploy re-added the Route 53 alias.")

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print("\nSHORT LINK HOSTS FAILED - either the apex path a customer follows is "
              "broken, or the retired subdomain has come back. Fix the apex; do not "
              "restore the subdomain.")
        return 1

    print(f"  apex form redirects to: {targets.pop()}")
    print(f"  {LEGACY_HOST} does not resolve, as intended since 2026-09-28")
    print("\nSHORT LINK HOSTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
