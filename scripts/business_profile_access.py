#!/usr/bin/env python3
"""Measure whether this Cloud project is approved for the Google Business Profile APIs.

    python scripts/business_profile_access.py

Read-only. Mints no credential onto a command line and prints no secret value.

WHY A SCRIPT RATHER THAN A NOTE. The approval state is invisible in the obvious place and
actively misleading in two others, so anybody checking by eye reaches the wrong answer:

  1. ALL EIGHT modern GBP APIs report `state: ENABLED` on this project. Enabling them is
     customer-service and means nothing about approval. Only the legacy
     `mybusiness.googleapis.com` behaves as the docs describe - invisible until approved,
     and it answers HTTP 403 from serviceusage and an HTML 404 from the API itself.
  2. An actual call returns **HTTP 429 RESOURCE_EXHAUSTED**, which reads as rate limiting.
     It is not. The error's own metadata carries `quota_limit_value: "0"`, and the GBP
     quota doc is explicit that a limit of 0 means access has never been granted:
     "If your quota limit for the Google Business Profile API is 0, you have not yet been
     granted access. Don't request a quota increase. Instead, submit the Application For
     Basic API Access."

That second point is the whole reason this file exists. A 429 invites exactly the two
wrong responses - add retry with backoff, or file a quota-increase request - and neither
can ever succeed, because there is no rate to back off from and no quota to increase. It
is an authorization state wearing a rate limit's status code. Distinguish them on
`quota_limit_value`: 0 means unapproved, 300 QPM means approved.

WHAT THIS SCRIPT CANNOT MEASURE, stated rather than guessed. The two eligibility
requirements are not readable from any API available to us:

    a Business Profile VERIFIED AND ACTIVE FOR 60+ DAYS
    a website representing that business, listed ON the profile

Reading a profile's verification date needs `mybusinessverifications` /
`mybusinessbusinessinformation`, which are behind the very gate being tested - so the
check is circular and has to be done by a human in the Business Profile UI. The script
reports what it can prove and names the rest as unverified, because "probably fine" is
how an application gets rejected and re-queued behind another review cycle.

Circumstantial evidence, from this repository rather than from Google, that a listing
does exist: `src/components/ContactLocation.tsx` pins a real Google Place
(`ChIJQTvOovt3AjoRitCdl0-xHJk`) and its comments record that querying the embed by
business name made Google draw its own info card carrying the business name, the address
and a 4.5-star rating. A star rating only renders on an established listing. That is
evidence a PROFILE EXISTS. It is not evidence of its verification date, nor that the
applying account manages it - both of which the reviewer checks.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

PROJECT_ID = "wecaredigitalbw"
PROJECT_NUMBER = "756034744787"
SA = "automation@wecaredigitalbw.iam.gserviceaccount.com"
SCOPE = "https://www.googleapis.com/auth/business.manage"

#: The eight modern APIs plus the legacy one. The legacy entry is kept deliberately: it is
#: the only one whose visibility tracks approval, so it is a second, independent signal.
GBP_SERVICES = [
    "mybusinessaccountmanagement.googleapis.com",
    "mybusinessbusinessinformation.googleapis.com",
    "mybusinessverifications.googleapis.com",
    "mybusinessplaceactions.googleapis.com",
    "mybusinesslodging.googleapis.com",
    "mybusinessnotifications.googleapis.com",
    "mybusinessqanda.googleapis.com",
    "businessprofileperformance.googleapis.com",
    "mybusiness.googleapis.com",
]

FORM = "https://support.google.com/business/workflow/16726127"
PREREQS = "https://developers.google.com/my-business/content/prereqs"


def adc_token() -> str:
    p = subprocess.run(["gcloud", "auth", "print-access-token"],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(f"could not mint an ADC token: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def sa_token() -> str:
    p = subprocess.run(
        ["gcloud", "auth", "print-access-token",
         f"--impersonate-service-account={SA}", f"--scopes={SCOPE}"],
        capture_output=True, text=True, timeout=180)
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(f"could not mint a business.manage token: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def get(url: str, tok: str) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, raw[:400].decode("utf8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def quota_limit_value(err: object) -> str | None:
    """Pull `quota_limit_value` out of a 429 body. This is the whole diagnosis."""
    if not isinstance(err, dict):
        return None
    for d in err.get("error", {}).get("details", []):
        md = d.get("metadata") or {}
        if "quota_limit_value" in md:
            return str(md["quota_limit_value"])
    return None


def main() -> int:
    print("=" * 78)
    print(f"GOOGLE BUSINESS PROFILE API ACCESS   project {PROJECT_ID} "
          f"({PROJECT_NUMBER})")
    print("=" * 78)

    adc = adc_token()

    print("\nAPI enablement state (customer-service; NOT an approval signal)")
    enabled = 0
    for s in GBP_SERVICES:
        code, body = get(
            "https://serviceusage.googleapis.com/v1/projects/"
            f"{PROJECT_NUMBER}/services/{s}", adc)
        state = body.get("state", "?") if isinstance(body, dict) and code == 200 \
            else f"HTTP{code}"
        if state == "ENABLED":
            enabled += 1
        legacy = "   <- legacy; visibility tracks approval" \
            if s == "mybusiness.googleapis.com" else ""
        print(f"  {s:<46} {state}{legacy}")

    print("\nLive call, which is the only thing that settles it")
    tok = sa_token()
    limits: list[str] = []
    for label, url in [
        ("accounts.list",
         "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"),
        ("performance API",
         "https://businessprofileperformance.googleapis.com/v1/locations/1"
         ":getDailyMetricsTimeSeries?dailyMetric=WEBSITE_CLICKS"),
    ]:
        code, body = get(url, tok)
        lv = quota_limit_value(body)
        if lv is not None:
            limits.append(lv)
        status = body.get("error", {}).get("status", "") \
            if isinstance(body, dict) else ""
        print(f"  {label:<18} HTTP {code}  {status}"
              + (f"  quota_limit_value={lv}" if lv is not None else ""))

    zero = [v for v in limits if v == "0"]
    approved = [v for v in limits if v not in ("0", None)]

    print("\n" + "=" * 78)
    if zero and not approved:
        print("VERDICT   NOT APPROVED - measured, not inferred.")
        print("          Every quota limit reads 0, which the GBP quota doc defines as")
        print("          'access has not been granted'. The HTTP 429 is an authorization")
        print("          state wearing a rate-limit status code.")
        print("")
        print("          DO NOT add retry/backoff. DO NOT request a quota increase.")
        print("          Both are explicitly the wrong move and neither can succeed.")
    elif approved:
        print(f"VERDICT   APPROVED - non-zero quota limit(s): {sorted(set(approved))}")
        print("          300 QPM is the documented approved value.")
    else:
        print("VERDICT   INCONCLUSIVE - no quota_limit_value came back. Re-read the raw")
        print("          error bodies rather than trusting this summary.")
    print("=" * 78)

    if zero and not approved:
        print("\nHOW TO APPLY")
        print(f"  form     {FORM}")
        print("           pick 'Application for Basic API Access' from the drop-down")
        print(f"  project  give the PROJECT NUMBER {PROJECT_NUMBER}, not the id")
        print("  email    apply from an address that is an OWNER or MANAGER on the")
        print("           Business Profile. A non-manager address is a rejection.")
        print("")
        print("CHECK THESE TWO FIRST - this script cannot, and they gate the review")
        print("  [ ] the Business Profile has been VERIFIED AND ACTIVE FOR 60+ DAYS")
        print("  [ ] the Profile lists the business website")
        print("      Read both at https://business.google.com - the verification date is")
        print("      not exposed by any API we can reach, because the APIs that would")
        print("      report it are behind this same gate.")
        print("")
        print("  Evidence a profile EXISTS (repo, not Google): ContactLocation.tsx pins")
        print("  place ChIJQTvOovt3AjoRitCdl0-xHJk and records Google's own card showing")
        print("  the name, address and a 4.5-star rating. That proves existence only -")
        print("  not the 60-day clock, and not that the applying account manages it.")
        print(f"\n  requirements: {PREREQS}")

    #: Exit non-zero while blocked so this can gate a checklist without being read.
    return 0 if approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
