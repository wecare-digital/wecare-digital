"""WhatsApp Direct Send API — the one home for every fact both senders need.

Direct Send lets a business-initiated utility or authentication message go out
without pre-creating a template: the same `POST /{phone_id}/messages` endpoint,
the same Cloud API body, plus a **top-level `category`** sibling of `type`. Meta
auto-generates or matches a template from the body.

Why this module exists
----------------------
Two functions need the same answers - `messaging/outbound-whatsapp` (the
production sender) and `messaging/whatsapp-business-api` (the admin/diagnostic
surface, and the sign-in code sender). Phase 1 put the Direct Send knowledge in
the second one only, and got three of its four facts wrong. Keeping the flags,
the WABA map, the TTL table, the error classifier and the authentication OTP
shape here means the two senders cannot disagree.

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

One allowlist per category
--------------------------
Meta grants the two categories separately: utility by messaging-limit
eligibility (the WhatsApp Manager banner), authentication through an
access-restricted beta arranged by a partner or client manager. A WABA can hold
one without the other, so one shared list would force an authentication attempt
on a WABA that only has utility, and every sign-in code would pay a refused
round trip before its fallback. `DIRECT_SEND_ENABLED_WABAS` keeps its name and
meaning (utility) because that is what the live functions carry.
"""

from __future__ import annotations

import os
import string
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# The flags
# ---------------------------------------------------------------------------

UTILITY = "utility"
AUTHENTICATION = "authentication"

FLAG_ENV = "DIRECT_SEND_ENABLED_WABAS"  # utility
AUTHENTICATION_FLAG_ENV = "DIRECT_SEND_AUTHENTICATION_ENABLED_WABAS"
DEFAULT = ""  # empty -> OFF for every WABA. Shipped state.

CATEGORY_FLAG_ENVS: Dict[str, str] = {
    UTILITY: FLAG_ENV,
    AUTHENTICATION: AUTHENTICATION_FLAG_ENV,
}


def enabled_wabas(category: str = UTILITY) -> Tuple[str, ...]:
    """The WABA ids enabled for `category`, whitespace trimmed, empties dropped.

    A category with no allowlist (anything but utility and authentication)
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
    `DIRECT_SEND_ENABLED_WABAS` exactly as before. Authentication reads
    `DIRECT_SEND_AUTHENTICATION_ENABLED_WABAS`.

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


# ---------------------------------------------------------------------------
# Authentication: the one-time-password message
# ---------------------------------------------------------------------------
#
# Meta's documented shape (Direct Send > Supported message types > Interactive
# authentication messages): top-level `category: "authentication"`, `type:
# "interactive"`, `interactive.type: "button"`, and EXACTLY one button, of type
# `otp`, with `otp_type: "copy_code"`. The code is 4 to 10 ASCII alphanumerics and
# must also appear as a standalone value in the body text.
# `code_expiration_minutes` is 1..90 and defaults to 10. Authentication cannot
# address a business-scoped user id, so the recipient is always a phone number in
# `to`.
#
# The body copy is fixed here and says only the code and the security line.
# Authentication is billed and policed as authentication; copy a caller could set
# is copy that could be misclassified, and misclassification is what Meta's
# enforcement ladder punishes.

OTP_CODE_LENGTH: Tuple[int, int] = (4, 10)
OTP_EXPIRATION_MINUTES: Tuple[int, int] = (1, 90)
OTP_DEFAULT_EXPIRATION_MINUTES = 10

# Explicit ASCII sets rather than str.isdigit()/isalnum(), which accept hundreds of
# non-ASCII codepoints that Meta's "ASCII alphanumeric" rule does not.
_OTP_CODE_CHARS = frozenset(string.ascii_letters + string.digits)
_PHONE_DIGITS = frozenset(string.digits)


def otp_body_text(code: str) -> str:
    """The authentication body. The code stands alone, as Meta requires."""
    return f"{code} is your verification code. For your security, do not share this code."


def otp_expiration_minutes(expires_in_seconds: Any) -> int:
    """Whole minutes for `code_expiration_minutes`, clamped to Meta's 1..90.

    Rounded DOWN: telling a customer a code lasts longer than it does is the
    failure that matters, so a 90-second code says 1 minute, not 2. A value that
    is not a positive integer gets Meta's own default of 10, which is also the
    lifetime every sender here issues today.
    """
    try:
        seconds = int(expires_in_seconds)
    except (TypeError, ValueError):
        return OTP_DEFAULT_EXPIRATION_MINUTES
    if seconds <= 0:
        return OTP_DEFAULT_EXPIRATION_MINUTES
    low, high = OTP_EXPIRATION_MINUTES
    return max(low, min(high, seconds // 60))


def build_authentication_otp_payload(
        to: Any, code: Any,
        expiration_minutes: Any = OTP_DEFAULT_EXPIRATION_MINUTES) -> Dict[str, Any]:
    """The Direct Send authentication message for one code, or `ValueError`.

    The error messages never repeat the input. The code is a credential and `to`
    is a phone number, and these messages reach logs.
    """
    recipient = str(to or "").strip()
    if recipient.startswith("+"):
        recipient = recipient[1:]
    # E.164 allows at most 15 digits.
    if not 8 <= len(recipient) <= 15 or not set(recipient) <= _PHONE_DIGITS:
        raise ValueError("recipient must be a phone number in digits (authentication "
                         "cannot address a business-scoped user id)")

    otp = str(code or "")
    low, high = OTP_CODE_LENGTH
    if not low <= len(otp) <= high or not set(otp) <= _OTP_CODE_CHARS:
        raise ValueError("code must be 4 to 10 ASCII letters or digits")

    try:
        minutes = int(expiration_minutes)
    except (TypeError, ValueError):
        raise ValueError("code_expiration_minutes must be an integer") from None
    low, high = OTP_EXPIRATION_MINUTES
    if not low <= minutes <= high:
        raise ValueError("code_expiration_minutes must be between 1 and 90")

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "interactive",
        "category": AUTHENTICATION,
        "interactive": {
            "type": "button",
            "body": {"text": otp_body_text(otp)},
            "action": {"buttons": [{
                "type": "otp",
                "otp": {
                    "code": otp,
                    "otp_type": "copy_code",
                    "code_expiration_minutes": minutes,
                },
            }]},
        },
    }
