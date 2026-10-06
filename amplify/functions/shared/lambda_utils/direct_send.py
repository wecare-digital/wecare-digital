"""WhatsApp Direct Send API — the one home for every fact both senders need.

Direct Send lets a business-initiated utility or authentication message go out
without pre-creating a template: the same `POST /{phone_id}/messages` endpoint,
the same Cloud API body, plus a **top-level `category`** sibling of `type`. Meta
auto-generates or matches a template from the body.

Why this module exists
----------------------
Two functions need the same answers - `messaging/outbound-whatsapp` (the
production sender) and `messaging/whatsapp-business-api` (the admin/diagnostic
surface). Phase 1 put the Direct Send knowledge in the second one only, and got
three of its four facts wrong. Keeping the flag, the WABA map, the TTL table and
the error classifier here means the two senders cannot disagree.

Why an id allowlist and not `DIRECT_SEND_ENABLED=true`
------------------------------------------------------
Eligibility is granted by Meta **per WABA**. WABA1 may be onboarded while WABA2
is not, and a single global boolean would send WABA2's traffic into a guaranteed
error. An allowlist of ids also has no state that can disagree with itself:
turning it on for one WABA is adding one id, turning everything off is clearing
one variable, and a third WABA needs no code change. Unknown input is off by
construction, which matches the stance `outbound-whatsapp._resolve_meta_phone_id`
already takes for sender resolution.

Why a deploy-time env var and NOT a SystemConfigTable row
---------------------------------------------------------
`outbound-whatsapp` already has a runtime-toggle pattern for
`whatsapp_auto_thumb`: read the table, `except Exception -> fall back to the
default`, cache for 300 seconds. That is right for a cosmetic toggle, where the
worst case is a stray reaction emoji. It is wrong here. This flag changes the
**billing category** of a message, and Meta polices misclassification with an
account-level enforcement ladder that ends in permanent revocation. A swallowed
read failure must not be able to turn it on, and "turn it off now" must mean
now, not within five minutes. An env var requires a publish and an alias move,
which is a feature: the change is atomic, recorded and reviewable.

OFF is byte-identical to today
------------------------------
Omitting `category` is Meta's own definition of a service message, not a trick -
so with the flag empty the request body is exactly the one we send now. That is
what makes the rollback complete without a code revert.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

FLAG_ENV = "DIRECT_SEND_ENABLED_WABAS"
DEFAULT = ""  # empty -> OFF for every WABA. Shipped state.


def enabled_wabas() -> Tuple[str, ...]:
    """The configured WABA ids, whitespace trimmed, empties dropped."""
    raw = os.environ.get(FLAG_ENV, DEFAULT) or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def enabled_for_waba(waba_id: str) -> bool:
    """True only when `waba_id` is explicitly listed in `DIRECT_SEND_ENABLED_WABAS`.

    FAILS CLOSED. Unset, `""`, whitespace-only, `None`, and any id that is not
    listed all return False. A falsy `waba_id` returns False without reading the
    environment at all, because "we could not tell which WABA this is" is never
    a reason to change a message's billing category.
    """
    if not waba_id:
        return False
    return str(waba_id).strip() in enabled_wabas()


# ---------------------------------------------------------------------------
# Meta phone-number id -> WABA id
# ---------------------------------------------------------------------------
#
# THE single home for this mapping. It lives here rather than in a handler
# because both senders need it and eligibility is per WABA, so a second copy is
# a second thing to get wrong.
#
# Not reused from elsewhere, deliberately: `auth/customer-whatsapp-auth` is
# packaged `standalone=True`, so no shared module is importable from it and its
# OTP_WABA_MAP has to be a JSON env var. That is a packaging constraint, not a
# precedent to copy.
META_PHONE_TO_WABA: Dict[str, str] = {
    "1016149501586345": "2094615664435155",  # +91 93309 94400 -> WABA1 WECARE.DIGITAL
    "1055232054343117": "2513394156072604",  # +91 99033 00044 -> WABA2 Manish Agarwal
}


def waba_for_meta_phone(meta_phone_id: Optional[str]) -> str:
    """Resolve a Meta phone-number id to its WABA id, or `''` when unknown.

    Returns an empty string rather than guessing. The caller must treat `''` as
    "not enabled" and log it, for the same reason `_resolve_meta_phone_id`
    refuses to default to a working sender: answering from the wrong WABA is a
    support incident, and billing from the wrong WABA is a surprise on someone
    else's invoice.
    """
    if not meta_phone_id:
        return ""
    return META_PHONE_TO_WABA.get(str(meta_phone_id).strip(), "")


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------
#
# These are the bounds for Direct Send's `ttl_seconds` request field.
#
# They are deliberately NOT `lambda_utils.template_ttl.TTL_BOUNDS`. That module
# owns a DIFFERENT field - the template's own `message_send_ttl_seconds` - with
# different numbers (utility 30..43200, authentication 30..900, marketing
# 43200..2592000). Sharing one table between the two would necessarily make one
# of them wrong, and a TTL Meta refuses comes back as an unexplained 100.
TTL_BOUNDS: Dict[str, Tuple[int, int]] = {
    "utility": (30, 2592000),        # up to 30 days
    "authentication": (30, 900),     # 15 minutes, matching OTP expiry practice
    "service": (30, 43200),          # 12 hours
}

TTL_DEFAULTS: Dict[str, int] = {
    "utility": 2592000,      # 30 days
    "authentication": 600,   # 10 minutes
    "service": 43200,        # 12 hours
}


def validate_ttl_seconds(category: Optional[str], value) -> Optional[str]:
    """`None` when `value` is an acceptable `ttl_seconds` for `category`.

    Otherwise a human error string naming **that category's** maximum, so a 901
    on `authentication` is told about 900 rather than about utility's 2592000.
    """
    cat = (category or "").strip().lower()
    bounds = TTL_BOUNDS.get(cat)
    if bounds is None:
        return f"ttlSeconds is not supported for category {cat!r}"
    low, high = bounds
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        return "ttlSeconds must be an integer"
    if not (low <= ttl <= high):
        return (f"ttlSeconds for category '{cat}' must be between {low} and "
                f"{high} seconds")
    return None


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

NOT_ONBOARDED = "not_onboarded"
RESTRICTED = "restricted"
OTHER_100 = "other_100"

# Hints keyed by Meta error code. Collected from the three Direct Send pages that
# document error modes.
#
# The correction that matters: phase 1 treated 139200/131064 as the beta gate and
# had no entry for 100 at all, so a send from a WABA that was never onboarded
# returned a bare "Invalid parameter" with no hint - the one case the whole
# scaffold exists to explain. 139200 is the POST-MISUSE restriction. They are
# different conditions and must stay separate signals.
ERROR_HINTS: Dict[str, str] = {
    "100": ("This WABA is not onboarded to Direct Send, or a Direct Send parameter "
            "was rejected. Read error_data.details: if it says the category requires "
            "Direct Send, the account is not eligible yet - check the eligibility "
            "banner in WhatsApp Manager and use an approved template meanwhile."),
    "132021": ("A template with this template_name already exists and was not created "
               "by Direct Send. Choose a different name. (Arrives asynchronously on "
               "the error webhook.)"),
    "131000": ("Direct Send could not create the named template after 3 retries. "
               "Named sends have no onboarding-template fallback, so the message was "
               "dropped. Retry, or drop template_name to regain the fallback. "
               "(Arrives asynchronously on the error webhook.)"),
    "132015": ("The matched template is paused for low quality, so matching messages "
               "fail until it recovers. (Arrives asynchronously on the status "
               "webhook.)"),
    "139200": ("Direct Send access is BLOCKED for this WABA by Meta enforcement. This "
               "is not the not-onboarded error - it means access was granted and then "
               "restricted. Check for a category-misclassification notice."),
    "131064": ("Direct Send utility volume is capped for this window by "
               "category-misclassification enforcement. Sends resume next window; the "
               "underlying classification still needs fixing."),
}


def classify_error(code, details: Optional[str] = "") -> str:
    """Classify a Meta error as a Direct-Send-specific condition.

    Returns `'not_onboarded'`, `'restricted'`, `'other_100'`, or `''` for
    anything that is not Direct-Send-specific and should keep today's handling.

    The `details` matcher is deliberately tolerant - two lowercased tokens,
    `'direct send'` and `'categor'` - because **the exact wording of that string
    has not been verified against a live Meta response**. It is described in the
    docs, not quoted from one. So the caller must log the full `details` on every
    100: that is how this matcher gets tightened once a real response exists.

    A false negative here degrades to `'other_100'`, which logs the full
    `error_data` and falls back to today's refusal - the same customer-facing
    outcome, just a less specific log line.
    """
    key = str(code) if code is not None else ""
    if key in ("139200", "131064"):
        return RESTRICTED
    if key == "100":
        blob = str(details or "").lower()
        if "direct send" in blob and "categor" in blob:
            return NOT_ONBOARDED
        return OTHER_100
    return ""
