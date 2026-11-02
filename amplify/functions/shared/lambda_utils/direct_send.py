"""Shared Direct Send utility-message policy: account allowlist, TTL and error classification.

Only the utility category is enabled here. Sign-in codes use approved authentication
message templates. No message payload is constructed by this module.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# The flags
# ---------------------------------------------------------------------------

UTILITY = "utility"
AUTHENTICATION = "authentication"

FLAG_ENV = "DIRECT_SEND_ENABLED_WABAS"  # utility
DEFAULT = ""  # empty -> OFF for every WABA. Shipped state.

CATEGORY_FLAG_ENVS: Dict[str, str] = {
    UTILITY: FLAG_ENV,
}


def enabled_wabas(category: str = UTILITY) -> Tuple[str, ...]:
    """The WABA ids enabled for `category`, whitespace trimmed, empties dropped.

    A category with no allowlist (anything but utility)
    returns `()`, so it can never be switched on by configuration alone.
    """
    env = CATEGORY_FLAG_ENVS.get(str(category or "").strip().lower())
    if env is None:
        return ()
    raw = os.environ.get(env, DEFAULT) or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def enabled_for_waba(waba_id: str, category: str = UTILITY) -> bool:
    """True only when `waba_id` is explicitly listed in `category`'s allowlist.

    The default category is utility, so existing callers read
    `DIRECT_SEND_ENABLED_WABAS` exactly as before. Other categories have no enabled-account list.

    FAILS CLOSED. Unset, `""`, whitespace-only, `None`, an unknown category, and
    any id that is not listed all return False. A falsy `waba_id` returns False
    without reading the environment at all, because "we could not tell which
    WABA this is" is never a reason to change a message's billing category.
    """
    if not waba_id:
        return False
    return str(waba_id).strip() in enabled_wabas(category)


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
# These are the bounds for Direct Send's `ttl_seconds` request field, from Meta's
# "Configure message time-to-live (TTL)" page (updated 2026-07-31):
#
#   category        default (field omitted)   explicit ttl_seconds
#   utility         30 days                   30 .. 43200   (12 hours)
#   authentication  600 s                     30 .. 900
#
# The utility maximum used to be 2592000 here, read off the 30-day default. Meta
# refuses anything above 43200 with a 100 ("The time to live value must be lower
# than or equal to 43200"), so a value between the two passed this check and then
# failed at Meta. There is no service row: Meta answers a TTL on a message
# without a Direct Send category with a 100 as well.
#
# They are deliberately NOT `lambda_utils.template_ttl.TTL_BOUNDS`. That module
# owns a DIFFERENT field - the template's own `message_send_ttl_seconds` - with
# different numbers (utility 30..43200, authentication 30..900, marketing
# 43200..2592000). Today the utility and authentication numbers happen to agree;
# the fields are still different, and a TTL Meta refuses comes back as an
# unexplained 100.
TTL_BOUNDS: Dict[str, Tuple[int, int]] = {
    "utility": (30, 43200),          # 12 hours
    "authentication": (30, 900),     # 15 minutes, matching OTP expiry practice
}

# What Meta applies when `ttl_seconds` is omitted. Informational: nothing sends it.
TTL_DEFAULTS: Dict[str, int] = {
    "utility": 2592000,      # 30 days
    "authentication": 600,   # 10 minutes
}


def validate_ttl_seconds(category: Optional[str], value) -> Optional[str]:
    """`None` when `value` is an acceptable `ttl_seconds` for `category`.

    Otherwise a human error string naming **that category's** maximum, so a 901
    on `authentication` is told about 900 rather than about utility's 43200.
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

    Meta's "Send utility and authentication messages" page (updated 2026-10-14)
    now prints the string in full - "Parameter Invalid: The 'category' value
    requires Direct Send, which isn't enabled for this account. Use an approved
    message template instead." - and both tokens match it. That is still the
    documentation, not a captured response.

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
