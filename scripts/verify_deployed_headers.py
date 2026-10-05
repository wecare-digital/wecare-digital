#!/usr/bin/env python3
"""Assert the DEPLOYED security headers, not the ones in config.

Why this exists
---------------
The app is a static export. `next.config.js` declares a `headers()` block, but
Next.js only serves those when it runs as a server (`next start`); with
`output: export` the artifacts are plain files and the response headers come from
Amplify Hosting - specifically from `customHttp.yml` in the repository root.

On 2026-09-19 the two disagreed: `next.config.js` allowed `microphone=(self)`
while the deployed header sent `microphone=()`. Reading the Next config - the
file that looks like it configures this - gave the wrong answer, and the Plivo
Browser SDK would have been denied the microphone with no visible cause.

So this check reads the live response. A config assertion cannot catch that class
of bug, because the config was already correct.

WHICH HOST, AND WHY IT IS NOT `app.`
------------------------------------
Corrected 2026-09-25. This defaulted to `https://app.wecare.digital/`, which was a
**different distribution**: CloudFront `ERCXSFDL0VM8X` in front of the S3 bucket
`app.wecare.digital`, serving media. Amplify's `customHeaders` are applied by
Amplify Hosting and never reached it, so the script reported

    live Permissions-Policy: (absent)
    FAIL x-content-type-options=(absent)
    FAIL referrer-policy=(absent)
    RESULT: FAIL

against a host that was never meant to carry them - while `wecare.digital`, the
Amplify-hosted app, served all three correctly. A check that fails for a reason
unrelated to the thing it guards is worse than no check, because its red gets
learned as noise and then the real regression is invisible.

The Amplify app is served from the **apex**. That is also the origin the Plivo
softphone runs on, so it is the origin whose `microphone=(self)` actually matters.

THE ASSETS GAP IS CLOSED, and the target moved (2026-09-29)
-----------------------------------------------------------
Two things changed underneath this script and both had left it reporting noise.

1. `ASSETS_URL` still pointed at the retired `app.wecare.digital` host (written bare
   here on purpose - `check_retired_origins.py` escalates a scheme-qualified retired
   host near the word "origin" to a violation, and it is right to: prose cannot be
   distinguished from an allow-list entry by inspection). That host and its
   distribution are **gone**: `get-distribution ERCXSFDL0VM8X` returns
   NoSuchDistribution, no distribution carries the alias, the name resolves to no
   address, and `head-bucket app.wecare.digital` is 404. So the "report" printed
   only `request failed` - the exact learned-noise failure the section above warns
   about, reintroduced by a dead constant.

2. The premise was obsolete. Media is now served from the **apex** as
   `wecare.digital/get/<key>` through CloudFront `E2GP22R4BIFGQ3`, so it is behind
   the same host whose headers this script gates. Measured 2026-09-29 against
   `/get/o/stream/media/m/wecare-digital.png`:

       HTTP/2 200, content-type image/png
       referrer-policy: strict-origin-when-cross-origin
       permissions-policy: camera=(), microphone=(self), geolocation=()
       strict-transport-security: max-age=31536000
       x-content-type-options: nosniff

   All four are present. The "public distribution serving content with no security
   headers at all" gap that justified reporting it closed when the media moved.

`ASSETS_URL` now points at that media path. It stays **reported and never gated**,
because a media 404 or an S3-side change should not fail a headers check - but it
now reports a live surface rather than a dead name.

THE GAP THIS SCRIPT HAD, AND THE GATE THAT CLOSES IT (2026-09-29)
-----------------------------------------------------------------
This script passed for weeks while `amplify.yml` declared a
`Content-Security-Policy` that was never served on any build.

It passed because it only ever gated three things - Permissions-Policy,
X-Content-Type-Options and Referrer-Policy - and all three happened to be set at
the Amplify **app level** as well, so they were live for a reason unrelated to the
file this script was reading. The `customHeaders:` block in `amplify.yml` was inert
in its entirety: 7 headers declared, 5 served, and the live set was not even a
subset of the declared one. `Strict-Transport-Security` was live without appearing
in `amplify.yml`, and both CSP headers were in `amplify.yml` and absent from every
response. AWS documents the `amplify.yml` route as legacy; headers now live in
`customHttp.yml`, which the docs state overrides the app-level set.

So a second gate exists now, and it is the general one: **every header declared in
`customHttp.yml` must be present on the live response with an equal value.** That
is the check that would have caught this on the day the CSP was added, whereas an
allowlist of three header names could not - it can only ever catch a regression in
something somebody already thought to list.

The named floors below are kept as well as, not instead of, that comparison.
`customHttp.yml` overrides the app-level config wholesale, so deleting a line from
it silently removes a live header; the floor makes that a failure rather than a
quiet downgrade.

Usage
-----
    python scripts/verify_deployed_headers.py
    python scripts/verify_deployed_headers.py --url https://wecare.digital
    python scripts/verify_deployed_headers.py --no-assets  # skip the report
    python scripts/verify_deployed_headers.py --local      # parse amplify.yml only

Exit codes
    0  every required header matches on the Amplify origin
    1  a header is missing or wrong on the Amplify origin
    2  the request failed (network, DNS, TLS) - NOT a header failure

The assets-distribution report never changes the exit code.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# The Amplify-hosted app, which is what `amplify.yml` customHeaders apply to.
# NOT app.wecare.digital - see "WHICH HOST" above before changing this.
DEFAULT_URL = "https://wecare.digital/"

# Reported, never gated. The media edge: CloudFront E2GP22R4BIFGQ3 over the S3 bucket
# `wecare-digital-get`, reached on the apex as /get/<key>. A concrete object rather than
# `/get/`, because a prefix has no object to serve and would report a 403/404 that says
# nothing about headers. See "THE ASSETS GAP IS CLOSED" above before changing this.
ASSETS_URL = "https://wecare.digital/get/o/stream/media/m/wecare-digital.png"

# Directive -> required allowlist. The microphone is same-origin because the
# softphone needs it; camera and geolocation are denied outright.
REQUIRED_PERMISSIONS = {
    "camera": "()",
    "microphone": "(self)",
    "geolocation": "()",
}

# The named floor: these must be live whatever customHttp.yml happens to say, because
# that file overrides the app-level config wholesale and deleting a line from it is a
# live header removal. Values are compared case-insensitively.
OTHER_REQUIRED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "strict-transport-security": "max-age=31536000",
    # The three enforced directives, in the order customHttp.yml writes them. None of
    # them can break this site: there is no <object>/<embed> in the export, nothing
    # sets <base>, and frame-ancestors mirrors X-Frame-Options: SAMEORIGIN.
    "content-security-policy": "object-src 'none'; base-uri 'self'; frame-ancestors 'self'",
}

# Declared in customHttp.yml and gated only by the declared-vs-live comparison, not by
# the floor above: this is the report-only policy, whose whole point is that it will be
# rewritten repeatedly as violation reports come in. Pinning its exact value here would
# make every tightening pass edit two files to say the same thing.
REPORT_ONLY_HEADER = "content-security-policy-report-only"

# Populated by declared_headers(): folded-scalar lines indented deeper than the first
# line of their value. YAML keeps those as literal newlines instead of folding them, an
# HTTP header value cannot contain a newline, and Amplify responds by dropping the whole
# header with no build error. Entries are (key, line, indent, expected_indent).
FOLD_DEFECTS: list = []

ROOT = Path(__file__).resolve().parent.parent


def fetch_headers(url: str) -> tuple[int, dict]:
    """(status, lowercased headers). Raises on a transport failure.

    A 4xx/5xx still carries response headers, so it is checkable and is not
    treated as a transport failure.
    """
    request = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "wecare-header-check/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}


def report_assets_distribution(url: str) -> None:
    """Print the media edge's posture. Never affects the exit code.

    Originally included because the media distribution served content with no
    security headers at all and no response-headers policy - a real gap that would
    have stayed unnoticed if unreported. That gap is closed: media moved onto the
    apex host, and all four headers were measured present on 2026-09-29.

    Kept as a report rather than promoted to a gate, because a media 404 or an
    S3-side change is not a headers regression and should not fail this script.
    """
    print(f"\n  MEDIA EDGE (reported, never gated): {url}")
    print("    CloudFront E2GP22R4BIFGQ3 over s3://wecare-digital-get, served on the "
          "apex as /get/<key>.")
    try:
        status, headers = fetch_headers(url)
    except Exception as exc:  # noqa: BLE001
        print(f"    request failed: {type(exc).__name__} - not a gate, continuing")
        return

    present = [h for h in ("permissions-policy", "x-content-type-options",
                           "referrer-policy", "x-frame-options",
                           "strict-transport-security", "content-security-policy")
               if headers.get(h)]
    print(f"    HTTP {status}, content-type {headers.get('content-type', '(none)')}")
    if present:
        for h in present:
            print(f"    present  {h}={headers[h]}")
    else:
        print("    none of Permissions-Policy, X-Content-Type-Options, Referrer-Policy,")
        print("    X-Frame-Options, HSTS or CSP is present.")
        print("    Worth noting rather than alarming: this origin serves image/svg+xml")
        print("    (the BIMI logo), and SVG can carry script, so a document opened here")
        print("    executes in this origin. It is a distinct origin from wecare.digital,")
        print("    which limits the blast radius. Fix is a CloudFront response-headers")
        print("    policy on ERCXSFDL0VM8X - tracked separately, not by this script.")


def parse_permissions_policy(value: str) -> dict:
    """'camera=(), microphone=(self)' -> {'camera': '()', 'microphone': '(self)'}"""
    found = {}
    for part in value.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, allowlist = part.partition("=")
        found[name.strip().lower()] = allowlist.strip()
    return found


def check_permissions(value: str) -> list:
    """Returns a list of failure strings; empty means compliant."""
    failures = []
    found = parse_permissions_policy(value)
    for directive, expected in REQUIRED_PERMISSIONS.items():
        actual = found.get(directive)
        if actual is None:
            failures.append(f"{directive} missing (expected {expected})")
        elif actual != expected:
            failures.append(f"{directive}={actual}, expected {expected}")
    return failures


def resolve_pattern_probe(pattern: str, page_url: str) -> str | None:
    """One live URL that matches `pattern`, found by reading the page's own markup.

    Only `/_next/static/**/*` is handled, because it is the only non-sitewide pattern the
    file declares and because it is the case a literal path cannot serve: every filename
    under it is content-hashed by the build, so anything written down here is stale after
    the next deploy and the check would report a 404 as a missing header.

    Returns None rather than guessing. The caller prints SKIP and leaves the block
    unverified, which is the honest outcome - an asset nobody could find is not an asset
    that passed.
    """
    if not pattern.startswith("/_next/static/"):
        return None
    try:
        with urllib.request.urlopen(page_url, timeout=20) as response:  # noqa: S310
            body = response.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    # A stylesheet or a script; either one is served from the same prefix.
    match = re.search(r'["\'](/_next/static/[^"\']+\.(?:css|js))["\']', body)
    if not match:
        return None
    origin = page_url.split("/", 3)
    return f"{origin[0]}//{origin[2]}{match.group(1)}"


def declared_headers_by_pattern() -> dict:
    """customHttp.yml as {pattern: {lowercased key: value}}.

    WHY THIS IS SPLIT BY PATTERN NOW, AND WHY IT HAD TO BE.
    -----------------------------------------------------
    The parser used to flatten every block into one dict and the gate below compared all
    of it against the apex HTML response. That was correct while the file had exactly one
    `**/*` block and WOULD HAVE REPORTED A FALSE FAILURE the moment a second one appeared:
    customHttp.yml now sets `Cache-Control: public, max-age=31536000, immutable` on
    `/_next/static/**/*` only - deliberately not on HTML, for the reasons written at the
    top of that file - so a flat comparison would have declared a correctly-configured
    header "ABSENT from the response" and invited someone to delete it.

    A gate that fails on correct configuration is worse than no gate: the obvious way to
    make it green is to undo the thing it is complaining about.

    Each pattern is now checked against a URL that MATCHES it. `main()` resolves one such
    URL per pattern; where it cannot, that block is reported as unverified rather than
    assumed good.
    """
    return _parse_custom_http()


def declared_headers() -> dict:
    """Every header declared for the sitewide `**/*` pattern, as {lowercased key: value}.

    Kept as the sitewide view because that is what the apex HTML response can be held to.

    Hand-parsed rather than handed to PyYAML on purpose: this script must run with
    no third-party dependency, since it is also useful in a bare CI shell. PyYAML is
    pinned in requirements-dev.txt, but relying on it here would mean the header gate
    cannot run anywhere the dev requirements are not installed - which is exactly
    where a quick "did the headers ship?" check is most wanted.

    Handles the two scalar forms the file actually uses:
      - key: X-Frame-Options
        value: SAMEORIGIN              plain, optionally quoted
      - key: Content-Security-Policy-Report-Only
        value: >-                      folded block; continuation lines are joined
          default-src 'self';          with single spaces, which is what the YAML
          script-src ...               `>-` folding means for a browser header

    Verified to agree with PyYAML's parse of this file on 2026-09-29.
    """
    return _parse_custom_http().get(SITEWIDE_PATTERN, {})


SITEWIDE_PATTERN = "**/*"


def _parse_custom_http() -> dict:
    """The shared parser. Returns {pattern: {lowercased key: value}}."""
    FOLD_DEFECTS.clear()
    path = ROOT / "customHttp.yml"
    if not path.exists():
        return {}

    # {pattern: {header: value}}. A pattern that appears twice ACCUMULATES rather than
    # being overwritten, so a split block is read the way Amplify reads it.
    blocks: dict = {}
    # Defaulted to the sitewide pattern so a file that somehow omits `pattern:` is read as
    # applying everywhere - the pessimistic reading, which is the one that gates.
    pattern = SITEWIDE_PATTERN
    key = None
    folded: list | None = None
    fold_indent: int | None = None
    headers = blocks.setdefault(pattern, {})

    for raw in path.read_text().splitlines():
        line = raw.strip()

        # A folded value keeps consuming indented, non-comment lines until the next
        # `- key:`/`value:` at a shallower structural position.
        if folded is not None:
            if line and not line.startswith("#") and not re.match(r"-?\s*(key|value|pattern):", line):
                indent = len(raw) - len(raw.lstrip())
                if fold_indent is None:
                    fold_indent = indent
                elif indent > fold_indent:
                    # YAML does NOT fold a more-indented line inside `>-`; it keeps a
                    # literal newline. An HTTP header cannot carry one, so Amplify drops
                    # the header silently. Recorded as a value the caller can detect.
                    FOLD_DEFECTS.append((key, raw.strip()[:60], indent, fold_indent))
                folded.append(line)
                continue
            headers[key.lower()] = " ".join(folded)
            key, folded, fold_indent = None, None, None

        if line.startswith("#") or not line:
            continue

        # A new `- pattern:` opens a block. Everything until the next one belongs to it.
        match = re.match(r"-\s*pattern:\s*[\"']?(.+?)[\"']?\s*$", line)
        if match:
            pattern = match.group(1).strip()
            headers = blocks.setdefault(pattern, {})
            key = None
            continue

        match = re.match(r"-\s*key:\s*[\"']?(.+?)[\"']?\s*$", line)
        if match:
            key = match.group(1).strip()
            continue

        match = re.match(r"value:\s*(.*)$", line)
        if match and key:
            value = match.group(1).strip()
            if value in (">-", ">", "|", "|-"):
                folded = []
            else:
                # Strip only a MATCHED surrounding pair. A blanket strip("\"'") ate the
                # final character of
                #     "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
                # because the value is double-quoted but ends in a single quote, which
                # silently turned the enforced CSP into a different policy.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                headers[key.lower()] = value
                key = None

    if folded is not None and key:  # folded value ran to end of file
        headers[key.lower()] = " ".join(folded)
    # Drop a pattern that collected nothing, so an empty block does not read as a
    # configured surface with zero required headers.
    return {p: h for p, h in blocks.items() if h}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"origin to gate on (default: {DEFAULT_URL})")
    parser.add_argument("--assets-url", default=ASSETS_URL,
                        help="assets distribution to report on, never gated")
    parser.add_argument("--no-assets", action="store_true",
                        help="skip the assets-distribution report")
    parser.add_argument("--local", action="store_true",
                        help="check amplify.yml only; do not make a request")
    args = parser.parse_args()

    print("DEPLOYED SECURITY HEADER CHECK")

    # Always report the configured value, so a mismatch between config and live
    # is visible rather than inferred.
    declared = declared_headers()
    if not declared:
        print("  customHttp.yml: NOT FOUND or declares no headers.")
        print("  That file is the only thing setting response headers on this app.")
        return 1
    print(f"  customHttp.yml declares {len(declared)} headers: "
          f"{', '.join(sorted(declared))}")

    configured = declared.get("permissions-policy", "")
    print(f"  customHttp.yml Permissions-Policy: {configured or '(not found)'}")
    config_failures = (check_permissions(configured) if configured
                       else ["Permissions-Policy not found in customHttp.yml"])

    # Caught before a deploy rather than after one. A more-indented line inside a `>-`
    # folded scalar becomes a literal newline, and Amplify silently drops any header
    # whose value contains one - which is exactly how the report-only CSP went missing
    # while the other six headers shipped fine.
    for defect_key, line, indent, expected in FOLD_DEFECTS:
        print(f"    FAIL  {defect_key}: line indented {indent}, expected {expected}")
        print(f"            {line}")
        print("            A more-indented line in a `>-` scalar becomes a literal")
        print("            newline. Amplify drops headers whose value contains one.")
        config_failures.append(f"{defect_key} folded-scalar indentation")
    for failure in config_failures:
        print(f"    FAIL  {failure}")
    if not config_failures:
        print("    ok    camera=(), microphone=(self), geolocation=()")

    # next.config.js is inert under static export. Report it so the discrepancy
    # that caused the original bug stays visible.
    next_config = (ROOT / "next.config.js").read_text()
    next_match = re.search(r"'Permissions-Policy',\s*value:\s*'([^']+)'", next_config)
    if next_match:
        next_value = next_match.group(1)
        print(f"  next.config.js (INERT under static export): {next_value}")
        if next_value != configured:
            print("    WARN  next.config.js and customHttp.yml disagree. "
                  "customHttp.yml wins.")

    if args.local:
        return 1 if config_failures else 0

    print(f"  requesting {args.url}  (the Amplify-hosted app)")
    try:
        status, headers = fetch_headers(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"  REQUEST FAILED: {type(exc).__name__}: {exc}")
        print("  Cannot verify the deployed header. This is not a pass.")
        return 2

    print(f"  HTTP {status}")
    live = headers.get("permissions-policy", "")
    print(f"  live Permissions-Policy: {live or '(absent)'}")

    failures = check_permissions(live) if live else ["header absent from the response"]
    for failure in failures:
        print(f"    FAIL  {failure}")
    if not failures:
        print("    ok    camera=(), microphone=(self), geolocation=()")

    for name, expected in OTHER_REQUIRED.items():
        actual = headers.get(name, "")
        if actual.lower() != expected.lower():
            print(f"    FAIL  {name}={actual or '(absent)'}, expected {expected}")
            failures.append(name)
        else:
            print(f"    ok    {name}={actual}")

    # THE GENERAL GATE. Everything customHttp.yml declares must actually be on the
    # response. This is the check that catches a header which looks configured and is
    # not - the failure that let an undeployed CSP sit in amplify.yml unnoticed,
    # because an allowlist of header names can only catch a regression in a name
    # somebody already thought to write down.
    print("\n  DECLARED vs LIVE (every header in customHttp.yml)")
    for name in sorted(declared):
        want, got = declared[name], headers.get(name, "")
        if not got:
            print(f"    FAIL  {name} declared but ABSENT from the response")
            failures.append(name)
        elif " ".join(got.split()) != " ".join(want.split()):
            # Whitespace-normalised: a folded YAML scalar and the header a CDN emits
            # can differ in run-length without differing in meaning.
            print(f"    FAIL  {name} differs")
            print(f"            declared: {want[:110]}")
            print(f"            live:     {got[:110]}")
            failures.append(name)
        else:
            print(f"    ok    {name} matches ({len(got)} chars)")

    # ── The non-sitewide patterns ────────────────────────────────────────────────────
    #
    # customHttp.yml sets `Cache-Control: public, max-age=31536000, immutable` on
    # `/_next/static/**/*` and deliberately NOT on HTML, so the gate above - which reads
    # the apex HTML response - cannot see it. Checked here against a URL that actually
    # matches the pattern.
    #
    # THE URL IS DISCOVERED, NOT HARDCODED. Every filename under /_next/static/ carries a
    # content hash that changes on each build, so a literal path in this file would be
    # stale by the next deploy and the check would report a 404 as a header failure. The
    # live page links at least one such asset, so the page under test names its own.
    extra_patterns = {p: h for p, h in declared_headers_by_pattern().items()
                      if p != SITEWIDE_PATTERN}
    if extra_patterns:
        print("\n  NON-SITEWIDE PATTERNS")
    for pat, want_headers in extra_patterns.items():
        probe = resolve_pattern_probe(pat, args.url)
        if not probe:
            # Reported, not passed. An unverifiable surface is not a verified one, and
            # saying so is the difference between a gate and a decoration.
            print(f"    SKIP  {pat}: no URL on {args.url} matches it; "
                  f"{len(want_headers)} declared header(s) UNVERIFIED")
            continue
        print(f"    {pat} -> {probe}")
        try:
            probe_status, probe_headers = fetch_headers(probe)
        except Exception as exc:  # noqa: BLE001
            print(f"      REQUEST FAILED: {type(exc).__name__}: {exc}")
            failures.append(f"{pat} unreachable")
            continue
        print(f"      HTTP {probe_status}")
        for name in sorted(want_headers):
            want, got = want_headers[name], probe_headers.get(name, "")
            if not got:
                print(f"      FAIL  {name} declared but ABSENT")
                failures.append(f"{pat}:{name}")
            elif " ".join(got.split()) != " ".join(want.split()):
                print(f"      FAIL  {name} differs")
                print(f"              declared: {want[:90]}")
                print(f"              live:     {got[:90]}")
                failures.append(f"{pat}:{name}")
            else:
                print(f"      ok    {name}={got[:70]}")

    if not args.no_assets:
        report_assets_distribution(args.assets_url)

    if failures or config_failures:
        print("\nRESULT: FAIL")
        return 1
    print(f"\nRESULT: PASS - the Amplify origin serves all {len(declared)} headers "
          "declared in customHttp.yml,")
    print("        permits same-origin microphone, denies camera/geolocation, and "
          "enforces CSP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
