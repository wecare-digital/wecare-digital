#!/usr/bin/env python3
"""Fail if a retired hostname is allowed by any live CORS allow-list, or is
reachable as effective configuration in this repository.

Why this gate exists
--------------------
the retired legacy frontend host was retired on 2026-09-25 when the `stack` CNAME was
removed from Route 53. It is **NXDOMAIN** — measured, not assumed. Amplify serves
the apex directly and the subdomain had only ever 301'd to it.

The cleanup that accompanied the retirement reached the API Gateway CORS
configuration, the Amplify custom rules, the branch environment, the Cognito
callback and logout lists, and every source allow-list. It missed exactly one
place, found on 2026-09-26: the **S3 bucket `app.wecare.digital`** still carried

    AllowedOrigins: [ "https://retired-legacy-host.invalid", ... ]

At the time that bucket was the live media CDN behind CloudFront `ERCXSFDL0VM8X` —
it served the logos, the RCS video, and the WhatsApp template media. So the one
surface that kept the dead origin was also the one with the widest reach.

Since then the retired list has grown, and the media surface named above is itself
retired. On **2026-09-28** the owner deleted the `app.wecare.digital` bucket, the
`ERCXSFDL0VM8X` distribution that fronted it (aliases `app.`, `customerservice.` and
`selfcare.`), and the `r.wecare.digital` record for the URL shortener. All four
hostnames are NXDOMAIN, measured. Media now serves from the apex path
`wecare.digital/get` over bucket `wecare-digital-get`, and short links from
`wecare.digital/r`. Each of those four is in `RETIRED_HOSTS` below, so the same gate
that caught the S3 CORS entry now also refuses an allow-list offering any of them.

It survived because nothing in this repository configured it. There is no
`put_bucket_cors` call, no CDK construct and no CloudFormation resource for that
bucket's CORS: it was set in the console and then never re-read. A setting with no
generator has no diff, so no review would ever have surfaced it. This script is
the substitute for the missing generator — it does not write the config, but it
refuses to pass while the config is wrong.

Why a dead origin still matters
-------------------------------
It is not merely untidy. An allow-list entry for a hostname nobody owns is a
standing offer: whoever can next resolve that name gets credentialed
cross-origin reads of the media bucket. the retired legacy frontend host is a subdomain of
a domain we control, so the realistic risk is low — but the same class of entry
is exactly how a dangling-DNS takeover becomes a CORS bypass, and the cost of
removing it is zero. It is also dead weight in every preflight decision.

Comments are stripped before matching
-------------------------------------
Thirteen source files name the retired legacy frontend host in a comment that explains why
it was retired — `lambda_utils/response.py`, `link-resources.ts`,
`waba-management/handler.py`, `_app.tsx`, `sw.js`, `capacitor.ts`, the Android
manifest, the iOS plist, both native templates, `deploy_site_language.py`,
`google-language-relay.sh` and `.env.local.example`. That is the documentation
working. Reporting it would be reporting the record of the fix as the defect,
which is a mistake this repository's tests have had to correct three times, so
`#`, `//`, `/* */` and `<!-- -->` are blanked before the scan runs.

`tests/test_response.py` goes further and assembles the hostname at runtime
(`'https://' + 'stack.' + 'wecare.digital'`) precisely so a literal scan cannot
trip on a test whose whole purpose is asserting the host is absent. Prose is out
of scope by design: `docs/`, `seo/`, `.kiro/` and every `*.md` are excluded, and
`docs/execution/snapshots/` is excluded absolutely — those files are immutable
rollback evidence and are SUPPOSED to contain the old value.

Usage
-----
    python scripts/check_retired_origins.py          # live + repo
    python scripts/check_retired_origins.py --repo    # repo only, no AWS calls

Exit code 0 means no retired origin is allowed anywhere. Non-zero names every
surface that still carries one.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-east-1"

# The one origin that MUST be allowed, and on which bucket. Imported from the
# generator rather than re-declared, so the gate and the thing it gates cannot
# disagree - the whole reason the missing CORS went unnoticed is that the setting
# had no generator to diff against.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from provision_media_bucket_cors import (  # noqa: E402
    BUCKET as MEDIA_BUCKET,
    REQUIRED_ORIGIN as MEDIA_REQUIRED_ORIGIN,
    rules_allow_required_origin as media_cors_ok,
)

# Hostnames that must never appear in a CORS allow-list, with the reason. Keyed on
# the bare host so both the scheme-qualified origin and a stray bare reference are
# caught.
RETIRED_HOSTS = {
    "stack." + "wecare.digital": (
        "retired 2026-09-25 with the Route 53 CNAME; NXDOMAIN. Amplify serves the "
        "apex and this host only ever 301'd to it, and a redirecting host cannot be "
        "a usable allowed origin because the browser compares Access-Control-Allow-"
        "Origin to the literal request origin and never follows it"
    ),
    "app.wecare.digital": (
        "retired 2026-09-28; NXDOMAIN. Was the media CDN host, served by CloudFront "
        "ERCXSFDL0VM8X over the same-named S3 bucket and later over "
        "wecare-digital-get with origin path /o. The owner deleted the bucket, the "
        "distribution and the DNS record. Media is served from the apex path "
        "wecare.digital/get instead, and the bucket for S3 API calls is "
        "wecare-digital-get - see lambda_utils/media_paths.py"
    ),
    "customerservice.wecare.digital": (
        "retired 2026-09-28 alongside app.wecare.digital; both were aliases on "
        "CloudFront ERCXSFDL0VM8X. NXDOMAIN"
    ),
    "selfcare.wecare.digital": (
        "retired 2026-09-28 alongside app.wecare.digital; both were aliases on "
        "CloudFront ERCXSFDL0VM8X. NXDOMAIN"
    ),
    "r.wecare.digital": (
        "retired 2026-09-28 under YES R53-DELETE-001; NXDOMAIN. Was the URL "
        "shortener's custom domain. Short links are minted and served on the apex "
        "path wecare.digital/r, and scripts/check_short_link_hosts.py asserts this "
        "host stays unresolvable so an IaC deploy cannot quietly bring it back"
    ),
}

# Extensions that can carry effective configuration. Prose and snapshots are not
# scanned; see the module docstring.
SCANNED_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".json", ".yml", ".yaml", ".sh", ".xml", ".plist", ".template", ".example",
}
EXCLUDED_DIRS = {
    ".git", ".venv", "node_modules", ".next", ".scratch", ".pytest_cache",
    "docs", "seo", ".kiro", "tests", "dist", "build", "coverage",
}
# This file is the registry, so it necessarily contains every value it forbids -
# in RETIRED_HOSTS and in the docstring that explains the retirement. Its first
# run flagged itself five times, which is the same "record of the fix reported as
# the defect" trap the docstring warns about, arriving by the shortest possible
# route. `check_design_drift.py` avoids it by only ever scanning `src/`; this
# script scans the whole tree, so the exclusion has to be explicit.
SELF = Path(__file__).resolve()


def strip_comments(text: str, suffix: str) -> str:
    """Blank comments, preserving line numbers so reported locations stay usable."""
    # Block comments: C-family and XML/HTML.
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)

    out = []
    for line in text.splitlines():
        if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            # Avoid eating the // in https://
            line = re.sub(r"(?<!:)//.*$", "", line)
        elif suffix in (".py", ".sh", ".yml", ".yaml", ".example", ".template"):
            line = re.sub(r"(?<!\$)#.*$", "", line)
        out.append(line)
    return "\n".join(out)


# An allow-list context. A retired hostname is a FAILURE only when it is being offered
# as an origin; anywhere else it is a mention, and mentions are usually the record of the
# retirement rather than the defect.
#
# This narrowing was forced by evidence. Stripping comments was sufficient while
# the retired legacy frontend host was the only entry, because all 13 of its prose references sat
# in `#` or `//` comments. When `app.wecare.digital` and `r.wecare.digital` were added on
# 2026-09-28 the scan produced 44 hits and only ONE was a real allow-list entry. The rest
# were Python **docstrings** - which are string literals, not comments, so `strip_comments`
# cannot see them - plus dashboard inventory labels, test names, and the detector
# constants in this script's siblings (`DEAD_BUCKETS`, `LEGACY_HOST`, `ASSETS_URL`).
#
# That is exactly the "record of the fix reported as the defect" trap named in the module
# docstring, arriving for the third time. Left alone it would have made this gate
# something people pass with `|| true`.
ORIGIN_CONTEXT_RE = re.compile(
    r"(origin|allowedorigins|allow_origins|alloworigins|callbackurls|logouturls|"
    r"redirect_uri|redirecturi|cors)",
    re.I,
)
# How many lines above a hit may supply the allow-list context. An origin list is
# usually a multi-line array whose key sits several lines up; 6 covers the ones in this
# repo (`_PROD_ORIGINS`, `allowOrigins`, `AllowedOrigins`) without reaching into an
# unrelated block.
CONTEXT_WINDOW = 6


def _in_origin_context(lines: list[str], index: int) -> bool:
    start = max(0, index - CONTEXT_WINDOW)
    return bool(ORIGIN_CONTEXT_RE.search("\n".join(lines[start:index + 1])))


def scan_repo() -> tuple[list[str], list[str]]:
    """(violations, mentions) for retired hosts in effective repository configuration.

    A violation is a retired host offered as an origin - scheme-qualified and inside an
    allow-list context. A mention is any other occurrence; it is reported for review but
    does not fail the gate, because the overwhelming majority are the documentation and
    the detectors that exist *because* of the retirement.
    """
    violations, mentions = [], []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if path.resolve() == SELF:
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not any(h in raw for h in RETIRED_HOSTS):
            continue
        lines = strip_comments(raw, path.suffix).splitlines()
        for index, line in enumerate(lines):
            for host in RETIRED_HOSTS:
                if host not in line:
                    continue
                where = f"{rel}:{index + 1}  {host}  {line.strip()[:120]}"
                # A CORS origin is always scheme-qualified; a bare mention is not one.
                if f"https://{host}" in line and _in_origin_context(lines, index):
                    violations.append(where)
                else:
                    mentions.append(where)
    return violations, mentions


def _client(service):
    import boto3
    return boto3.client(service, region_name=REGION)


def scan_live() -> tuple[list[str], list[str], int, list[str]]:
    """Retired hosts allowed by a live CORS surface, plus the one positive assertion.

    Returns (violations, surfaces_checked, error_count, missing). A non-zero error
    count means the sweep is PARTIAL and its silence must not be read as a pass.

    `missing` is the inverse check added on 2026-10-06. This gate was written to
    catch an origin that should NOT be allowed, and it did its job - but the media
    bucket then failed the opposite way: `wecare-digital-get` carried **no CORS
    configuration at all**, so the dashboard's presigned browser upload died at the
    preflight with `403 CORSResponse: CORS is not enabled for this bucket` and every
    outbound WhatsApp attachment on both WABAs failed before Meta was called. An
    absent allow-list is invisible to a scan that only looks for wrong entries, which
    is how it survived from the 2026-09-25 bucket cutover to 2026-10-06. So the one
    origin that MUST be allowed is now asserted here too.
    """
    from botocore.exceptions import ClientError

    violations, checked, errors, missing = [], [], 0, []
    media_bucket_rules: list[dict] | None = None
    media_bucket_seen = False

    def flag(where, blob):
        for host in RETIRED_HOSTS:
            if host in str(blob):
                violations.append(f"{where}  allows {host}")

    # S3 bucket CORS. Discovered rather than hardcoded, so a new bucket is covered.
    try:
        s3 = _client("s3")
        for b in s3.list_buckets().get("Buckets", []):
            name = b["Name"]
            if name == MEDIA_BUCKET:
                media_bucket_seen = True
            try:
                rules = s3.get_bucket_cors(Bucket=name).get("CORSRules", [])
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "NoSuchCORSConfiguration":
                    errors += 1
                    print(f"  ! s3://{name} cors read failed: "
                          f"{exc.response.get('Error', {}).get('Code')}")
                continue
            checked.append(f"s3://{name} cors")
            flag(f"s3://{name} cors", rules)
            if name == MEDIA_BUCKET:
                media_bucket_rules = rules
    except Exception as exc:  # noqa: BLE001
        errors += 1
        print(f"  ! s3 sweep failed: {type(exc)}")

    # The positive assertion. Only meaningful if the bucket was actually enumerated -
    # if the sweep errored before reaching it, that is a PARTIAL read, not a failure,
    # and `errors` already carries that.
    if media_bucket_seen and not errors:
        checked.append(f"s3://{MEDIA_BUCKET} cors allows {MEDIA_REQUIRED_ORIGIN}")
        if not media_cors_ok(media_bucket_rules):
            missing.append(
                f"s3://{MEDIA_BUCKET} cors does NOT allow {MEDIA_REQUIRED_ORIGIN} "
                f"for PUT"
                + ("  (no CORS configuration at all)" if not media_bucket_rules else "")
                + " - the browser preflight for every presigned media upload will be "
                  "refused. Fix with: "
                  "python scripts/provision_media_bucket_cors.py --apply"
            )

    # API Gateway HTTP API CORS.
    try:
        agw = _client("apigatewayv2")
        for api in agw.get_apis().get("Items", []):
            label = f"apigatewayv2 {api.get('ApiId')} ({api.get('Name')}) cors"
            checked.append(label)
            flag(label, api.get("CorsConfiguration") or {})
    except Exception as exc:  # noqa: BLE001
        errors += 1
        print(f"  ! apigatewayv2 sweep failed: {type(exc)}")

    # Lambda environment variables that carry an origin allow-list.
    try:
        lam = _client("lambda")
        for page in lam.get_paginator("list_functions").paginate():
            for fn in page.get("Functions", []):
                env = (fn.get("Environment") or {}).get("Variables") or {}
                relevant = {k: v for k, v in env.items()
                            if "ORIGIN" in k.upper() or "CORS" in k.upper()}
                if relevant:
                    label = f"lambda {fn['FunctionName']} env"
                    checked.append(label)
                    flag(label, relevant)
    except Exception as exc:  # noqa: BLE001
        errors += 1
        print(f"  ! lambda sweep failed: {type(exc)}")

    # CloudFront response-headers policies can carry their own CORS allow-list.
    try:
        cf = _client("cloudfront")
        for item in (cf.list_response_headers_policies()
                     .get("ResponseHeadersPolicyList", {}).get("Items", [])):
            pol = item.get("ResponseHeadersPolicy", {})
            cfg = pol.get("ResponseHeadersPolicyConfig", {})
            cors = cfg.get("CorsConfig")
            if cors:
                label = f"cloudfront rhp {cfg.get('Name')}"
                checked.append(label)
                flag(label, cors)
    except Exception as exc:  # noqa: BLE001
        errors += 1
        print(f"  ! cloudfront sweep failed: {type(exc)}")

    return violations, checked, errors, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="store_true",
                    help="scan the repository only; make no AWS calls")
    ap.add_argument("--mentions", action="store_true",
                    help="also list non-failing mentions of a retired host")
    args = ap.parse_args()

    print("retired hosts  : " + ", ".join(sorted(RETIRED_HOSTS)))
    for host, why in sorted(RETIRED_HOSTS.items()):
        print(f"  {host}\n      {why}")
    print()

    repo_v, repo_mentions = scan_repo()
    print(f"repository     : {len(repo_v)} violation(s) in an origin allow-list, "
          f"{len(repo_mentions)} other mention(s) (comments stripped)")

    live_v, checked, errors, missing = ([], [], 0, [])
    if not args.repo:
        live_v, checked, errors, missing = scan_live()
        print(f"live surfaces  : {len(checked)} checked, {len(live_v)} violation(s), "
              f"{len(missing)} missing allowance(s), {errors} collector error(s)")

    if args.mentions and repo_mentions:
        print()
        for m in repo_mentions:
            print(f"  note  {m}")
        print(f"\n  {len(repo_mentions)} mention(s) above are NOT failures. Most are the "
              "documentation of the retirement or a detector that must name the host to "
              "detect it. Review them for stale claims, not for removal.")

    if repo_v or live_v or missing:
        print()
        for v in repo_v:
            print(f"  REPO  {v}")
        for v in live_v:
            print(f"  LIVE  {v}")
        for m in missing:
            print(f"  GONE  {m}")
        if repo_v or live_v:
            print("\nRETIRED ORIGIN CHECK FAILED - a hostname that no longer resolves "
                  "is still allowed as an origin. Remove it; do not allowlist it here.")
        if missing:
            print("\nREQUIRED ORIGIN CHECK FAILED - an origin this app is served from "
                  "is NOT allowed where it must be. This is the opposite defect and it "
                  "breaks uploads rather than widening access.")
        return 1

    if errors:
        print("\nPARTIAL - no violation found, but a collector errored, so this is "
              "NOT a pass. Fix the read and re-run.")
        return 2

    print("\nRETIRED ORIGIN CHECK PASSED - no retired hostname is allowed by any "
          "scanned surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
