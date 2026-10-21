"""Fetch opening hours + primary category from the Google Business Profile API — DORMANT.

WHY THIS IS DORMANT, AND WHY DORMANT IS NOT "BROKEN".
The Google Business Profile API is NOT approved for this Cloud project. `scripts/business_profile_access.py`
measures it rather than guessing: every GBP `quota_limit_value` reads **0**, which Google's own quota
documentation defines as "access has not yet been granted". A live call answers **HTTP 429
RESOURCE_EXHAUSTED**, which reads like rate limiting and is not - it is an authorization state wearing a
rate limit's status code. So this module is built to the real deployment it will one day run in, and to
the reality it runs in today: the moment access is NOT yet granted, it returns `None` ("no data") cleanly,
and the page it feeds is unchanged.

HARD RULES, carried verbatim from that script's warnings. A 429 invites exactly the two wrong responses,
and this module must make neither:

  * DO NOT add retry or backoff. There is no rate to back off from. A 429 here is permanent until a human
    is approved, so a retry loop burns quota budget that does not exist and never succeeds.
  * DO NOT request a quota increase, and carry no code path that would. The fix is the Application For
    Basic API Access, submitted by a human, not an automated quota bump.
  * Treat `quota_limit_value == 0`, HTTP 429 and HTTP 403 as "access not yet granted" => return `None`.
    This is NOT a retryable error and must never be raised as one.

HONESTY IS A HARD RULE. No opening hours and no business category are EVER hardcoded or fabricated here.
Every value this module emits is read from the live GBP response for the real location, or it is omitted.
A field missing in the API response is omitted from the output, never guessed. This mirrors the rest of
the repo's structured-data posture (schemacheck.js refuses fabricated values; faq.py refuses to publish
unreviewed content).

NEVER-RAISE CONTRACT, mirrored from faq.py. This is an enhancement to a page that must be served either
way. Any failure - the flag being off, no credentials, a 429/403, a malformed body, a transport error -
resolves to `None`, never to an exception that could break the page or a build step.

AUTH, reused from business_profile_access.py rather than reinvented. A GBP call needs the `business.manage`
OAuth token minted for the service account, NOT the Unified API key. In a dev context the token comes from
gcloud impersonation / ADC exactly as the probe script does; in Lambda it comes from the function's own
service-account credentials. There is deliberately no second auth path in this module.

NO LIVE FETCH IS POSSIBLE IN THE SANDBOX (no gcloud; outbound Google blocked), so this module is exercised
here only by unit tests against FIXTURES. It goes live only in the real deployment once a human obtains
Basic API Access and the flag below is turned on.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger()

# ── Constants reused from scripts/business_profile_access.py ──
# Kept identical on purpose: there is one project, one service account, one scope for GBP, and
# duplicating them here (a Python Lambda cannot import that script's module cleanly either) is
# safer than letting them drift.
PROJECT_NUMBER = "756034744787"
SA = "automation@wecaredigitalbw.iam.gserviceaccount.com"
SCOPE = "https://www.googleapis.com/auth/business.manage"

#: The location resource id. The single source of truth is src/config/analytics.ts
#: (GOOGLE_BUSINESS_PROFILE.location = 'locations/11367616731342236672'); a Python Lambda cannot
#: import the TypeScript config, so the literal is mirrored here with this pointer. If analytics.ts
#: changes, change this too.
LOCATION = "locations/11367616731342236672"

#: The business-information endpoint and the fields we ask for. readMask keeps the response to the
#: two things this module maps - nothing else is requested, so nothing else can leak into output.
_ENDPOINT = f"https://mybusinessbusinessinformation.googleapis.com/v1/{LOCATION}"
_READ_MASK = "regularHours,categories"

#: GBP day enum -> schema.org day name. GBP uses SUNDAY..SATURDAY; schema.org wants the English
#: day name (Google accepts the name form for openingHoursSpecification.dayOfWeek).
_GBP_DAY_TO_SCHEMA = {
    "MONDAY": "Monday",
    "TUESDAY": "Tuesday",
    "WEDNESDAY": "Wednesday",
    "THURSDAY": "Thursday",
    "FRIDAY": "Friday",
    "SATURDAY": "Saturday",
    "SUNDAY": "Sunday",
}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def business_profile_enabled() -> bool:
    """Whether the GBP LocalBusiness enrichment is switched on. Defaults OFF (fail-safe).

    Mirrors seo_config.py's posture: a public read path must never be one environment-variable
    typo away from an active integration. GBP_LOCALBUSINESS_ENABLED must be spelled correctly and
    set on purpose; anything else - unset, blank, a typo - resolves to off, and off means this
    module performs no network call and returns no data.
    """
    return _truthy(os.environ.get("GBP_LOCALBUSINESS_ENABLED", "false"))


# ── Pure mapping (no network, unit-testable) ──

def _opening_hours(regular_hours: Any) -> List[Dict[str, Any]]:
    """Map GBP regularHours.periods to schema.org OpeningHoursSpecification objects.

    GBP periods look like {openDay, openTime:{hours,minutes}, closeDay, closeTime:{hours,minutes}}.
    openTime/closeTime may also arrive as a bare 'HH:MM' string on some response shapes, so both are
    accepted. A period missing a usable day or either time is dropped, not fabricated.
    """
    if not isinstance(regular_hours, dict):
        return []
    periods = regular_hours.get("periods")
    if not isinstance(periods, list):
        return []

    out: List[Dict[str, Any]] = []
    for period in periods:
        if not isinstance(period, dict):
            continue
        day = _GBP_DAY_TO_SCHEMA.get(str(period.get("openDay") or "").strip().upper())
        opens = _time_str(period.get("openTime"))
        closes = _time_str(period.get("closeTime"))
        if not day or not opens or not closes:
            # Honest omission: a half-specified period is not emitted as a guess.
            continue
        out.append({
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": [day],
            "opens": opens,
            "closes": closes,
        })
    return out


def _time_str(value: Any) -> Optional[str]:
    """Normalise a GBP time to 'HH:MM', or None if it is not usable.

    Accepts the structured {hours, minutes} form (GBP's TimeOfDay) and a plain 'HH:MM' string.
    Returns None rather than inventing a time when the input is absent or malformed.
    """
    if isinstance(value, str):
        text = value.strip()
        parts = text.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return None
    if isinstance(value, dict):
        hours = value.get("hours")
        minutes = value.get("minutes", 0)
        # GBP omits an all-zero field, so a missing 'hours' legitimately means midnight (00).
        if hours is None and "hours" not in value and not value:
            return None
        try:
            h = int(hours or 0)
            m = int(minutes or 0)
        except (TypeError, ValueError):
            return None
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    return None


def _category(categories: Any) -> Optional[str]:
    """Map the GBP primaryCategory displayName to a schema.org category string, or None.

    Only the primaryCategory's human-readable displayName is used; if it is absent or blank the
    category is omitted rather than substituting the internal category id or a guess.
    """
    if not isinstance(categories, dict):
        return None
    primary = categories.get("primaryCategory")
    if not isinstance(primary, dict):
        return None
    name = str(primary.get("displayName") or "").strip()
    return name or None


def to_schema(raw_location: Any) -> Optional[Dict[str, Any]]:
    """Normalise a raw GBP location object to a schema.org fragment, or None if nothing usable.

    PURE and NETWORK-FREE on purpose, separated from the fetch entrypoint exactly as faq.py keeps
    normalise() apart from its storage query - so a test can feed a fixture location and assert the
    mapping without touching the network.

    Returns only the keys that were actually present in the input:
      { 'openingHoursSpecification': [...], 'category': '...' }
    Missing or empty fields are omitted (no fabrication). None is returned when neither field is
    usable, so the caller can treat "no data" uniformly.
    """
    if not isinstance(raw_location, dict):
        return None

    result: Dict[str, Any] = {}

    hours = _opening_hours(raw_location.get("regularHours"))
    if hours:
        result["openingHoursSpecification"] = hours

    category = _category(raw_location.get("categories"))
    if category:
        result["category"] = category

    return result or None


# ── Access diagnosis (reused from business_profile_access.py) ──

def quota_limit_value(err: Any) -> Optional[str]:
    """Pull `quota_limit_value` out of a GBP error body. The whole access diagnosis, per the probe.

    A limit of '0' means access has never been granted - the dormant state. Reused from
    business_profile_access.py so the 0-means-unapproved reading stays identical in both places.
    """
    if not isinstance(err, dict):
        return None
    for detail in err.get("error", {}).get("details", []):
        if not isinstance(detail, dict):
            continue
        metadata = detail.get("metadata") or {}
        if "quota_limit_value" in metadata:
            return str(metadata["quota_limit_value"])
    return None


def _is_access_not_yet_granted(status: int, body: Any) -> bool:
    """Whether a response is the "access not yet granted" state, NOT a retryable error.

    True when the quota limit reads 0, or the status is 429/403. Each of those is the authorization
    gate, not a transient fault, so the caller returns None and stops - it never retries, backs off,
    or asks for a quota increase.
    """
    if quota_limit_value(body) == "0":
        return True
    return status in (401, 403, 429)


# ── Network entrypoint (dormant by default) ──

def _sa_token() -> Optional[str]:
    """Mint a business.manage token for the service account, exactly as the probe script does.

    gcloud impersonation / ADC in a dev context; in Lambda the function's own SA credentials back
    the same call. Returns None (never raises, never logs a token) when no credential is available -
    which is the sandbox's reality and resolves cleanly to "no data".
    """
    try:
        proc = subprocess.run(
            ["gcloud", "auth", "print-access-token",
             f"--impersonate-service-account={SA}", f"--scopes={SCOPE}"],
            capture_output=True, text=True, timeout=180,
        )
    except Exception:  # noqa: BLE001 - no gcloud / no credentials is a no-data state, not a crash
        return None
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        return None
    return token


def _get(url: str, token: str) -> tuple[int, Any]:
    """GET `url` with a bearer token. Returns (status, parsed body). Never raises; never logs a secret.

    Imported lazily so merely importing this module touches no network stack, and so the pure
    mapping functions above can be unit-tested with no urllib involvement at all.
    """
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return exc.code, raw[:400].decode("utf8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def fetch_business_profile() -> Optional[Dict[str, Any]]:
    """Fetch and map the live GBP data for the location, or None ("no data").

    The dormant-safe entrypoint. In order:
      (a) flag OFF (the default) => return None immediately, NO network call;
      (b) no business.manage token => return None (the sandbox reality);
      (c) on quota_limit_value==0 / HTTP 429/403/401 => log one INFO line and return None, with NO
          retry, NO backoff, NO quota-increase path (per business_profile_access.py's warnings);
      (d) any other non-200 or malformed body => return None (never raise - faq.py's contract);
      (e) otherwise map the location through the pure to_schema() and return its result.
    """
    if not business_profile_enabled():
        return None

    token = _sa_token()
    if not token:
        logger.info("GBP token unavailable; integration dormant")
        return None

    status, body = _get(f"{_ENDPOINT}?readMask={_READ_MASK}", token)

    if _is_access_not_yet_granted(status, body):
        # Authorization state, not a transient fault. Stop here - no retry, no backoff, no quota bump.
        logger.info("GBP access not yet granted; integration dormant")
        return None

    if status != 200 or not isinstance(body, dict):
        logger.info("GBP returned no usable data; integration dormant")
        return None

    return to_schema(body)
