"""OAuth 2.0 authorization code flow with PKCE, and the token lifecycle.

Pure: builds URLs, verifies parameters, and decides when a token needs refreshing. The HTTP
calls live in the Lambda so these decisions stay testable without credentials - which
matters here because the live consent screen is owner-gated.

The five things that go wrong in this flow
------------------------------------------
Each of these is a real, common failure rather than a theoretical one, and each is handled
explicitly below.

**1. `expires_in` is relative, and gets stored as if it were absolute.** Google returns
``"expires_in": 3599``. Persist that number and the token looks fresh forever, because
3599 is always greater than "now" under a naive comparison. `token_record` converts it to
an absolute `expiresAt` at the moment of exchange, which is the only point where the
relative value means anything.

**2. The refresh token arrives once and then never again.** Google issues
`refresh_token` only on the first consent for a client/user pair, unless you explicitly ask
again with `access_type=offline` **and** `prompt=consent`. A re-authorisation therefore
returns a token response with no `refresh_token` - and code that stores the response
wholesale wipes the one it already had, converting a working long-lived integration into one
that dies at the next expiry. `merge_token_record` never overwrites a stored refresh token
with an absent one.

**3. Refreshing exactly at expiry.** A token that expires in 5 seconds passes an
`expiresAt > now` check and then fails mid-request, and clock skew between us and Google
makes the window wider than it looks. `needs_refresh` applies a skew so the refresh happens
before the cliff.

**4. `state` is generated but never actually checked, or checked but reusable.** Either way
the CSRF protection is decorative. `state` here is a random token the caller must store
against the session and consume exactly once; `verify_state` does a constant-time compare
and the store is responsible for single use.

**5. The user silently grants fewer scopes than asked for.** Google's consent screen lets
a user deselect individual scopes. The token that comes back is valid, so nothing looks
wrong - but `people.connections.list` then returns 403 and the sync appears to find no
contacts. `missing_scopes` compares granted against required at exchange time, so the
failure is legible at the point of consent rather than as an empty sync days later.

Why S256 only
-------------
`plain` is still in RFC 7636 and is never acceptable here: it sends the verifier itself as
the challenge, so an attacker who can read the authorization request can complete the
exchange. `build_authorization_url` hard-codes S256 and `CHALLENGE_METHOD` is not a
parameter, so there is no way to weaken it from a call site.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlencode

#: RFC 7636 allows 43-128 characters. 64 random URL-safe bytes yields ~86 characters, which
#: is comfortably inside the range and well past the entropy the spec asks for.
_VERIFIER_BYTES = 64

#: RFC 7636 s4.2. `plain` is deliberately unsupported - see the module docstring.
CHALLENGE_METHOD = "S256"

#: Refresh this many seconds before the recorded expiry. Covers clock skew between us and
#: the provider plus the round trip of the request the token is about to be used for.
#: 120s against a 3600s token costs one extra refresh per hour at worst.
REFRESH_SKEW_SECONDS = 120

#: Google issues a refresh token only on first consent unless BOTH of these are sent.
#: Omitting either is why long-lived integrations mysteriously stop working after a
#: re-authorisation.
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: Read-only is deliberate. Contact sync needs to read an address book, never to write one,
#: and `contacts` (read-write) would let a bug in our mapper edit a customer's own Google
#: contacts. Narrower scope also means a less alarming consent screen.
GOOGLE_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"


class OAuthError(ValueError):
    """A malformed or unsafe OAuth parameter. Never carries a token value."""


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    """Base64url without padding, per RFC 7636 s4.2.

    The stripped `=` matters: Google rejects a padded challenge, and the symptom is an
    `invalid_grant` at exchange time that looks like a verifier mismatch.
    """
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_code_verifier() -> str:
    """A fresh PKCE code verifier. `secrets`, never `random`.

    `random` is seeded deterministically and, under a snapshotting runtime, can be restored
    to an identical state across environments - which would hand every concurrent
    authorisation the same verifier. See `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa); the
    same hazard is recorded there for the URL shortener.
    """
    return _b64url(secrets.token_bytes(_VERIFIER_BYTES))


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge for a verifier."""
    if not verifier or len(verifier) < 43 or len(verifier) > 128:
        raise OAuthError(
            f"code verifier must be 43-128 characters (RFC 7636 s4.1), got {len(verifier or '')}")
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state() -> str:
    """A CSRF state token. Store it against the session and consume it exactly once."""
    return _b64url(secrets.token_bytes(32))


def verify_state(expected: Optional[str], received: Optional[str]) -> bool:
    """Constant-time state comparison.

    Constant-time because a timing oracle on this value would let an attacker discover a
    valid state and complete an authorisation against someone else's session. Single use is
    the store's job - this function cannot know it has been called before.
    """
    if not expected or not received:
        return False
    return hmac.compare_digest(str(expected), str(received))


# ---------------------------------------------------------------------------
# Authorization request
# ---------------------------------------------------------------------------

def build_authorization_url(*, client_id: str, redirect_uri: str,
                            scopes: Iterable[str], state: str,
                            code_challenge: str,
                            login_hint: Optional[str] = None,
                            endpoint: str = GOOGLE_AUTH_ENDPOINT) -> str:
    """The URL to send the user to.

    `access_type=offline` plus `prompt=consent` are both present on purpose. Offline asks for
    a refresh token; `prompt=consent` forces the consent screen so the refresh token is
    reissued on a re-authorisation instead of being silently withheld. Without the pair, a
    re-auth returns no refresh token and the integration dies at the next expiry.

    `include_granted_scopes=true` makes this incremental: a later authorisation for an
    additional scope returns a token carrying the previously granted ones too, rather than
    replacing them.
    """
    if not client_id:
        raise OAuthError("client_id is required")
    if not redirect_uri:
        raise OAuthError("redirect_uri is required")
    scope_list = [s for s in scopes if s]
    if not scope_list:
        raise OAuthError("at least one scope is required")
    if not state:
        raise OAuthError("state is required; without it the callback has no CSRF binding")
    if not code_challenge:
        raise OAuthError("code_challenge is required; this flow is PKCE-only")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scope_list),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": CHALLENGE_METHOD,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{endpoint}?{urlencode(params)}"


def token_exchange_body(*, client_id: str, client_secret: str, code: str,
                        redirect_uri: str, code_verifier: str) -> Dict[str, str]:
    """The form body for the code->token exchange.

    Returned as a dict rather than an encoded string so the caller encodes it once and this
    stays inspectable in a test without parsing. The secret is a parameter, never read from
    this module - it comes from Secrets Manager at the call site.
    """
    for name, value in (("client_id", client_id), ("client_secret", client_secret),
                        ("code", code), ("redirect_uri", redirect_uri),
                        ("code_verifier", code_verifier)):
        if not value:
            raise OAuthError(f"{name} is required for the token exchange")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
    }


def refresh_body(*, client_id: str, client_secret: str,
                 refresh_token: str) -> Dict[str, str]:
    """The form body for a refresh. No `code_verifier`: PKCE applies to the code exchange."""
    for name, value in (("client_id", client_id), ("client_secret", client_secret),
                        ("refresh_token", refresh_token)):
        if not value:
            raise OAuthError(f"{name} is required to refresh")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }


# ---------------------------------------------------------------------------
# Scope verification
# ---------------------------------------------------------------------------

def granted_scopes(token_response: Optional[Mapping[str, Any]]) -> List[str]:
    """The scopes actually granted, from the token response's space-delimited `scope`."""
    raw = (token_response or {}).get("scope") or ""
    return [s for s in str(raw).split(" ") if s]


def missing_scopes(token_response: Optional[Mapping[str, Any]],
                   required: Iterable[str]) -> List[str]:
    """Required scopes the provider did NOT grant.

    The consent screen lets a user deselect individual scopes, and the resulting token is
    perfectly valid - so nothing looks wrong until the API returns 403 and the sync reports
    zero contacts. Checking here turns that into a legible failure at the moment of consent.

    An empty `scope` in the response is treated as "nothing granted" rather than "everything
    granted". Assuming the optimistic reading is how a silent 403 gets shipped.
    """
    granted = set(granted_scopes(token_response))
    return [s for s in required if s and s not in granted]


# ---------------------------------------------------------------------------
# Token records
# ---------------------------------------------------------------------------

def token_record(token_response: Mapping[str, Any], *, at: Optional[int] = None,
                 subject: str = "") -> Dict[str, Any]:
    """A storable token record with an **absolute** expiry.

    `expires_in` is relative to this instant and is meaningless once persisted, so it is
    converted here - the only place where the value can be interpreted correctly. Storing the
    raw number is the single most common bug in this flow: 3599 is always greater than any
    later comparison against "seconds remaining", so the token reads as permanently fresh.
    """
    now = at if at is not None else int(time.time())
    access = str(token_response.get("access_token") or "").strip()
    if not access:
        raise OAuthError("token response carried no access_token")

    try:
        lifetime = int(token_response.get("expires_in") or 0)
    except (TypeError, ValueError):
        lifetime = 0
    if lifetime <= 0:
        # Treat an absent lifetime as already expired rather than as unlimited. A refresh is
        # cheap; serving a dead token is a 401 in front of a customer.
        lifetime = 0

    record: Dict[str, Any] = {
        "accessToken": access,
        "expiresAt": now + lifetime,
        "obtainedAt": now,
        "tokenType": str(token_response.get("token_type") or "Bearer"),
        "scope": " ".join(granted_scopes(token_response)),
    }
    if subject:
        record["subject"] = subject
    refresh = str(token_response.get("refresh_token") or "").strip()
    if refresh:
        record["refreshToken"] = refresh
    return record


def merge_token_record(existing: Optional[Mapping[str, Any]],
                       fresh: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge a new token record over a stored one, **preserving the refresh token**.

    This is the guard for failure 2 in the module docstring. Google withholds
    `refresh_token` on a re-authorisation and on every refresh response, so a wholesale
    overwrite deletes the only copy we will ever have - turning a working integration into
    one that stops at the next expiry, hours later, with no obvious cause.

    A fresh refresh token, when the provider does send one, always wins: that is a rotation.
    """
    merged: Dict[str, Any] = dict(existing) if existing else {}
    merged.update({k: v for k, v in fresh.items() if v not in (None, "")})
    if not str(fresh.get("refreshToken") or "").strip():
        stored = str((existing or {}).get("refreshToken") or "").strip()
        if stored:
            merged["refreshToken"] = stored
        else:
            merged.pop("refreshToken", None)
    return merged


def needs_refresh(record: Optional[Mapping[str, Any]], *,
                  at: Optional[int] = None,
                  skew: int = REFRESH_SKEW_SECONDS) -> bool:
    """Should this token be refreshed before use?

    True when there is no token, or when expiry is within `skew`. Refreshing early rather
    than exactly at expiry is what stops a request failing mid-flight because the token died
    between the check and the call, or because our clock is slightly behind the provider's.
    """
    if not record:
        return True
    if not str(record.get("accessToken") or "").strip():
        return True
    try:
        expires_at = int(record.get("expiresAt") or 0)
    except (TypeError, ValueError):
        return True
    now = at if at is not None else int(time.time())
    return expires_at - skew <= now


def can_refresh(record: Optional[Mapping[str, Any]]) -> bool:
    """Is a non-interactive refresh possible, or does the user have to consent again?"""
    return bool(str((record or {}).get("refreshToken") or "").strip())


def describe(record: Optional[Mapping[str, Any]], *,
             at: Optional[int] = None) -> Dict[str, Any]:
    """Diagnostic summary. Contains no token material.

    Deliberately reports lengths and booleans rather than values: this output is designed to
    be safe in a CloudWatch line and in an admin screen.
    """
    now = at if at is not None else int(time.time())
    if not record:
        return {"present": False, "canRefresh": False, "needsRefresh": True}
    try:
        expires_at = int(record.get("expiresAt") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    return {
        "present": bool(str(record.get("accessToken") or "").strip()),
        "accessTokenLength": len(str(record.get("accessToken") or "")),
        "canRefresh": can_refresh(record),
        "needsRefresh": needs_refresh(record, at=now),
        "secondsRemaining": max(0, expires_at - now),
        "expired": expires_at <= now,
        "scopes": granted_scopes({"scope": record.get("scope")}),
        "subject": record.get("subject", ""),
    }
