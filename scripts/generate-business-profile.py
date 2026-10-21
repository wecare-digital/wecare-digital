#!/usr/bin/env python3
"""Write the Google Business Profile enrichment data for the static site. DORMANT by default.

    python scripts/generate-business-profile.py

WHAT THIS DOES. It calls the dormant GBP fetch entrypoint
(amplify/functions/operations/seo-tools/business_profile.py:fetch_business_profile) and, ONLY if
that returns real data, writes it to src/config/business-profile.generated.json, the one file
src/lib/schema.ts reads to extend the single Organization node with schema.org
openingHoursSpecification and category. When the fetch returns None (the default and, today, the
only reachable state) it writes `null`: no hours, no category, no markup. The front end treats an
absent or `null` file as "no data" and emits the Organization exactly as published.

THIS IS NOT PART OF `npm run build`. The default build chain (see package.json) does not run this
script, so the committed `null` data file is what ships until a human runs this on purpose after
access is granted. Running it with the flag off is a safe no-op: it (re)writes `null`.

WHY DORMANT, AND WHY DORMANT IS NOT "BROKEN". The Google Business Profile API is NOT approved for
this Cloud project. scripts/business_profile_access.py measures it rather than guessing: every GBP
`quota_limit_value` reads 0, which Google's own quota documentation defines as "access has not yet
been granted". A live call answers HTTP 429 RESOURCE_EXHAUSTED, which reads like rate limiting and
is not: it is an authorization state wearing a rate limit's status code. So the fetch module, and
this generator, return "no data" cleanly until that changes, and the page they feed is unchanged.

HOW TO ACTIVATE (a human task, not an automated one):

  1. Apply for GBP Basic API Access via the form:
         https://support.google.com/business/workflow/16726127
     Choose "Application for Basic API Access". Submit from an email that is an OWNER or MANAGER
     of the Business Profile.
  2. On that form give the PROJECT NUMBER 756034744787 (the number, NOT the project id
     "wecaredigitalbw"). The Business Profile must be VERIFIED AND ACTIVE FOR 60+ DAYS, and the
     website must be LISTED ON the profile. These two eligibility facts are not readable from any
     API we can reach (the check is circular: reading them needs the very access being applied
     for), so confirm them by hand in the Business Profile UI before applying. "Probably fine" is
     how an application gets rejected and re-queued behind another review cycle.
  3. Once Google approves (quota_limit_value flips from 0 to a real QPM), set the env flag and run
     this generator so it writes real data:
         GBP_LOCALBUSINESS_ENABLED=true python scripts/generate-business-profile.py
     Then the same flag at `npm run build` time makes src/lib/schema.ts read the generated file and
     enrich the Organization node. The flag is the identical gate the fetch module reads.

HARD RULES, carried verbatim from business_profile_access.py's warnings:

  * DO NOT add retry or backoff. A 429 here is permanent until a human is approved.
  * DO NOT request a quota increase, and carry no code path that would. The fix is the Application
    For Basic API Access, submitted by a human.
  * NO opening hours or category are EVER hardcoded or fabricated. Every value written comes from
    the live GBP response mapped by business_profile.py:to_schema, or the file is `null`. Absent
    data means absent markup. A fabricated rating/hours/founding claim is grounds for a manual
    action against the whole domain and no validator can catch it.

NO LIVE FETCH IS POSSIBLE IN THE SANDBOX (no gcloud; outbound Google blocked), so running this here
writes `null`. It writes real data only in a context where Basic API Access has been granted and a
business.manage credential is available.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The fetch module lives under amplify/functions; make it importable without packaging.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SEO_TOOLS = _REPO_ROOT / "amplify" / "functions" / "operations" / "seo-tools"
sys.path.insert(0, str(_SEO_TOOLS))

#: The one file src/lib/schema.ts reads. Committed as `null`; populated only here, only when real
#: GBP data is returned. Never commit a populated version; see the module doc for why.
_OUT = _REPO_ROOT / "src" / "config" / "business-profile.generated.json"


def main() -> int:
    # Imported here (not at module top) so the honest no-data path does not depend on the module
    # loading cleanly in every context; mirrors the fetch module's never-break posture.
    from business_profile import business_profile_enabled, fetch_business_profile  # noqa: PLC0415

    if not business_profile_enabled():
        # Fail-safe default: flag off => write `null`, no network call, no markup.
        _write(None)
        print("GBP_LOCALBUSINESS_ENABLED is off; wrote null (integration dormant).")
        return 0

    data = fetch_business_profile()  # returns None on unapproved/absent access; never raises
    _write(data)
    if data is None:
        print("GBP access not yet granted or no usable data; wrote null (integration dormant).")
    else:
        print(f"Wrote GBP enrichment: {sorted(data.keys())}")
    return 0


def _write(data: object | None) -> None:
    """Write the data file. `null` for the dormant/no-data state; the mapped object otherwise."""
    _OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    raise SystemExit(main())
