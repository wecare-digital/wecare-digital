"""A backend-owned customer session: an opaque id in a cookie, the Cognito tokens kept server-side.

Why this exists, and why not sessionStorage
--------------------------------------------
`src/lib/customerAuth.ts` puts the Cognito **access token** in `sessionStorage` and nothing else.
That has one visible symptom and one invisible one. The visible symptom is that a shopper who closes
the tab, or whose 60-minute access token expires mid-journey, is sent back through WhatsApp OTP -
because sessionStorage dies with the tab and there is no refresh token to renew with. The invisible
one is that the token is readable by any script on the origin.

The requirement (sections 15-16) is a *remembered* session that survives a tab close, a browser
restart and an access-token renewal on the same browser, WITHOUT a second OTP, for as long as the
session is valid. The deliberate way to do that is NOT to move the refresh token into web storage -
that keeps the renewal working but makes the worse exposure permanent. It is to hold the tokens on
the server and hand the browser only an **opaque session id** in a `Secure; HttpOnly; host-only`
cookie. Script on the page cannot read an HttpOnly cookie, the id names nothing on its own, and the
server is the only thing that can exchange it for a live access token.

This module is the server-side custody. It is pure in the sense `payment_attempt` and
`checkout_pricing` are: every function takes an injected `store` and an injected clock, holds no AWS
client, and never reaches the network itself - so it imports with no credentials and is tested
offline. The one place a Cognito call is unavoidable (refresh) takes an injected callable, so the
test drives it without boto.

The custody model, stated precisely
------------------------------------
A session row holds, keyed by a **hash** of the opaque id (never the id itself - a leaked table
read must not yield usable session ids):

    sidHash            sha256 of the opaque session id. The row key.
    customerId         who this session is for. Authorises nothing on its own; see customer_auth.
    refreshRef         a REFERENCE to the Cognito refresh token in Secrets Manager, never the token.
    createdAt          absolute-deadline anchor. A refresh does NOT move this.
    absoluteExpiresAt  createdAt + 30 days. Hard cap. A refresh may not extend it.
    idleExpiresAt      lastSeenAt + 7 days. Every validated request moves this forward.
    lastSeenAt         touched on each validation.
    csrfToken          the double-submit secret for cookie-authenticated mutations.
    persistent         False for a shared-device sign-in: the cookie is a session cookie and the
                       absolute deadline is short. True for "remember me".
    rotationEnabled     whether the app client rotates refresh tokens; decides the refresh flow.
    revokedAt          set on sign-out. A revoked session validates to nothing, forever.

Why the deadlines are enforced here and not in the cookie
---------------------------------------------------------
A cookie `Max-Age` is a hint the browser may ignore and an attacker will. Idle and absolute expiry
are checked against the stored row on every validation, so a replayed cookie past either deadline is
refused regardless of what the browser did. The rule section 16 is specific about - *a successful
refresh must not extend the absolute deadline* - is why `absoluteExpiresAt` is anchored to
`createdAt` and the refresh path never touches it: without that, a session that refreshes every hour
lives forever, which is exactly the indefinite remembered-login this is meant to bound.

Rotation vs REFRESH_TOKEN_AUTH
------------------------------
For a rotation-enabled app client the only correct refresh is `GetTokensFromRefreshToken`, which
returns a NEW refresh token that must replace the stored reference; `REFRESH_TOKEN_AUTH` is
incompatible with rotation and would fail. For a non-rotation client `REFRESH_TOKEN_AUTH` is correct
and the refresh token is reused. Which flow a client needs is a property of the DEPLOYED app client,
and inspecting it (`aws cognito-idp describe-user-pool-client`) is BLOCKED here - no AWS. So the
flow is a parameter of the session, defaulted conservatively, and the live decision is recorded as
an unblock step in the IaC note (see `customer_session_config.py`).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── policy (section 16 recommended customer policy) ────────────────────────────────
#: 30-day absolute remembered-session lifetime. A refresh never moves the anchor this is added to.
ABSOLUTE_LIFETIME_SECONDS = int(os.environ.get(
    "CUSTOMER_SESSION_ABSOLUTE_SECONDS", str(30 * 24 * 60 * 60)))
#: 7-day inactivity expiry. Every validated request moves this forward from "now".
IDLE_LIFETIME_SECONDS = int(os.environ.get(
    "CUSTOMER_SESSION_IDLE_SECONDS", str(7 * 24 * 60 * 60)))
#: A shared-device ("not persistent") session is deliberately short-lived and uses a session cookie.
SHARED_DEVICE_ABSOLUTE_SECONDS = int(os.environ.get(
    "CUSTOMER_SESSION_SHARED_ABSOLUTE_SECONDS", str(12 * 60 * 60)))

#: The cookie the browser carries. Opaque id only.
COOKIE_NAME = "wd_csid"
#: Bytes of CSPRNG behind the opaque id and the CSRF token. 32 bytes == 256 bits; not guessable.
_ID_BYTES = 32
#: `new_opaque_id()` output: unpadded URL-safe base64 of `_ID_BYTES` bytes (43 characters).
_ID_SHAPE = re.compile(r"[A-Za-z0-9_-]{%d}" % ((4 * _ID_BYTES + 2) // 3))

#: The provisioned store. The module never reads this itself (every function takes an injected
#: store); it exists so the handlers that DO build a client resolve one name.
DEFAULT_TABLE_NAME = "stack-wecare-digital-CustomerSessionsTable"


def table_name() -> str:
    return os.environ.get("CUSTOMER_SESSIONS_TABLE", DEFAULT_TABLE_NAME)


class SessionError(RuntimeError):
    """Base for session failures."""


class SessionInvalid(SessionError):
    """No usable session for the presented id: unknown, revoked, idle- or absolute-expired.

    One type for every "not a live session" reason on purpose, mirroring `customer_auth`: the
    client is told the same thing - re-authenticate - whether the id is unknown, revoked or expired,
    so the cookie cannot be used as an oracle for which session ids exist.
    """


class CsrfInvalid(SessionError):
    """A cookie-authenticated mutation arrived without a matching CSRF token."""


class RefreshFailed(SessionError):
    """A token refresh did not succeed for a definite reason (the refresh token is spent/revoked).

    DISTINCT from a transient provider error. A generic 5xx or an offline provider must NOT log the
    customer out - it is retried - so the single-flight refresh raises this only when Cognito says
    the refresh token itself is no longer valid.
    """


class RefreshUnavailable(SessionError):
    """The refresh could not be attempted or completed for a transient reason (offline/5xx).

    The caller serves a 503 and the session stays valid. Treating this as a logout is the defect
    section 16 calls out: a provider blip must not evict a remembered session.
    """


def _hash_id(session_id: str) -> str:
    """The row key. A table read yields hashes, never usable ids."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def new_opaque_id() -> str:
    """A fresh opaque session id. URL-safe, 256 bits of CSPRNG, names nothing."""
    return secrets.token_urlsafe(_ID_BYTES)


def is_session_id(value: Any) -> bool:
    """Whether `value` has the shape `new_opaque_id` produces. Lets a handler refuse junk early."""
    return isinstance(value, str) and bool(_ID_SHAPE.fullmatch(value))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(_ID_BYTES)


@dataclass(frozen=True)
class SessionView:
    """What a validated session exposes to a handler. Carries no token and no raw id."""

    sid_hash: str
    customer_id: str
    csrf_token: str
    persistent: bool
    absolute_expires_at: int
    idle_expires_at: int


def _absolute_lifetime(persistent: bool) -> int:
    return ABSOLUTE_LIFETIME_SECONDS if persistent else SHARED_DEVICE_ABSOLUTE_SECONDS


def create_session(store: Any, *,
                   customer_id: str,
                   refresh_ref: str,
                   persistent: bool = True,
                   rotation_enabled: bool = True,
                   now: Optional[int] = None) -> Tuple[str, SessionView]:
    """Mint a new session row and return `(opaque_id, view)`.

    The opaque id is returned ONCE, to be set in the cookie; only its hash is stored. `refresh_ref`
    is an encrypted custody reference to the Cognito refresh token, never the token itself - this
    module never holds a credential value.

    The absolute deadline is anchored to `now` and, per section 16, nothing afterwards moves it.
    """
    if not customer_id:
        raise ValueError("customer_id is required")
    if not refresh_ref:
        raise ValueError("refresh_ref is required; a session with no refresh custody cannot renew")

    moment = int(time.time()) if now is None else int(now)
    opaque = new_opaque_id()
    sid_hash = _hash_id(opaque)
    absolute = moment + _absolute_lifetime(persistent)
    idle = moment + IDLE_LIFETIME_SECONDS
    csrf = new_csrf_token()

    row = {
        "sidHash": sid_hash,
        "customerId": customer_id,
        "refreshRef": refresh_ref,
        "createdAt": moment,
        "absoluteExpiresAt": absolute,
        "idleExpiresAt": idle,
        "lastSeenAt": moment,
        "csrfToken": csrf,
        "persistent": bool(persistent),
        "rotationEnabled": bool(rotation_enabled),
        "refreshInFlight": 0,
    }
    store.put_session(row)
    logger.info('{"event":"customer_session_created","persistent":%s}',
                "true" if persistent else "false")
    return opaque, _view(row)


def _view(row: Dict[str, Any]) -> SessionView:
    return SessionView(
        sid_hash=str(row["sidHash"]),
        customer_id=str(row["customerId"]),
        csrf_token=str(row.get("csrfToken") or ""),
        persistent=bool(row.get("persistent")),
        absolute_expires_at=int(row.get("absoluteExpiresAt") or 0),
        idle_expires_at=int(row.get("idleExpiresAt") or 0),
    )


def _live_row(store: Any, session_id: str, now: int) -> Dict[str, Any]:
    """Load the row for `session_id` and prove it is live, or raise `SessionInvalid`.

    Every "not live" reason collapses to the same exception; see `SessionInvalid`.
    """
    if not session_id:
        raise SessionInvalid("no session id presented")
    row = store.get_session(_hash_id(session_id))
    if not row:
        raise SessionInvalid("unknown session")
    if row.get("revokedAt"):
        raise SessionInvalid("session has been revoked")
    if now >= int(row.get("absoluteExpiresAt") or 0):
        raise SessionInvalid("session past its absolute deadline")
    if now >= int(row.get("idleExpiresAt") or 0):
        raise SessionInvalid("session idle-expired")
    return row


def validate(store: Any, session_id: str, *, now: Optional[int] = None) -> SessionView:
    """Prove a live session from the opaque id and slide the idle deadline forward.

    The idle deadline moves to `now + IDLE_LIFETIME_SECONDS` on every validated request - that is
    what makes routine navigation keep the session alive. The absolute deadline is NEVER touched
    here, so idle activity extends inactivity-expiry only, never the hard 30-day cap.
    """
    moment = int(time.time()) if now is None else int(now)
    row = _live_row(store, session_id, moment)

    new_idle = moment + IDLE_LIFETIME_SECONDS
    # Clamp to the absolute deadline: idle may never push a session past its hard cap.
    new_idle = min(new_idle, int(row["absoluteExpiresAt"]))
    store.touch_session(row["sidHash"], last_seen_at=moment, idle_expires_at=new_idle)
    row = dict(row)
    row["lastSeenAt"] = moment
    row["idleExpiresAt"] = new_idle
    return _view(row)


def assert_csrf(view: SessionView, presented_token: str) -> None:
    """Guard a cookie-authenticated mutation. Double-submit, compared in constant time.

    A cookie rides along automatically on a cross-site POST, which is the whole CSRF problem; a
    header the attacker's page cannot read does not. The token is minted per session and compared
    with `hmac.compare_digest` so a timing side channel cannot recover it character by character.
    """
    expected = view.csrf_token or ""
    if not expected or not presented_token or not hmac.compare_digest(expected, str(presented_token)):
        logger.warning('{"event":"customer_session_csrf_rejected"}')
        raise CsrfInvalid("missing or mismatched CSRF token on a cookie-authenticated mutation")


def rotate(store: Any, session_id: str, *, now: Optional[int] = None) -> Tuple[str, SessionView]:
    """Issue a NEW opaque id for an existing live session and retire the old one.

    Called immediately after authentication (and anywhere a privilege level changes), so a session
    id that may have been observed before sign-in cannot be replayed after it. The customer, the
    refresh custody and BOTH deadlines carry over unchanged - rotation is an id swap, not a new
    session, so it must not reset the absolute anchor.
    """
    moment = int(time.time()) if now is None else int(now)
    row = _live_row(store, session_id, moment)

    new_opaque = new_opaque_id()
    new_hash = _hash_id(new_opaque)
    rotated = dict(row)
    rotated["sidHash"] = new_hash
    rotated["csrfToken"] = new_csrf_token()
    rotated["rotatedAt"] = moment
    store.put_session(rotated)
    store.delete_session(row["sidHash"])
    logger.info('{"event":"customer_session_rotated"}')
    return new_opaque, _view(rotated)


def revoke(store: Any, session_id: str, *, now: Optional[int] = None,
           revoke_refresh: Optional[Callable[[str], None]] = None) -> None:
    """Sign-out. The row is marked revoked so a replayed cookie validates to nothing, forever.

    Idempotent: revoking an unknown or already-revoked session is a no-op, not an error - a
    sign-out must never fail because the session was already gone.

    `revoke_refresh(refresh_ref)`, when given, is called after the row is marked revoked with the
    sealed refresh reference the row held, so the caller can revoke the token at Cognito. It
    fails soft: an error is logged by type and the sign-out still succeeds.
    """
    moment = int(time.time()) if now is None else int(now)
    sid_hash = _hash_id(session_id) if session_id else ""
    if not sid_hash:
        return
    row = store.get_session(sid_hash)
    if not row or row.get("revokedAt"):
        return
    store.revoke_session(sid_hash, revoked_at=moment)
    logger.info('{"event":"customer_session_revoked"}')
    refresh_ref = str(row.get("refreshRef") or "")
    if revoke_refresh is not None and refresh_ref:
        try:
            revoke_refresh(refresh_ref)
        except Exception as error:  # noqa: BLE001 - sign-out is already recorded
            logger.warning('{"event":"customer_session_token_revoke_failed","error":"%s"}',
                           type(error).__name__)


# ── single-flight refresh ──────────────────────────────────────────────────────────
#: How long a claimed in-flight refresh is honoured before another worker may re-claim it. Bounds a
#: worker that crashed mid-refresh so the session is not wedged "refreshing" forever.
REFRESH_LEASE_SECONDS = int(os.environ.get("CUSTOMER_SESSION_REFRESH_LEASE_SECONDS", "30"))
#: Bounded retry: a transient refresh is attempted at most this many times before 503. Never
#: unbounded - a provider outage must surface as a 503, not a retry storm.
MAX_REFRESH_ATTEMPTS = int(os.environ.get("CUSTOMER_SESSION_MAX_REFRESH_ATTEMPTS", "3"))


def refresh_access_token(store: Any, session_id: str, *,
                         cognito_refresh: Callable[[str, bool], Dict[str, Any]],
                         now: Optional[int] = None) -> Dict[str, Any]:
    """Renew the access token for a live session, single-flight across tabs and workers.

    Single-flight is a conditional claim on `refreshInFlight`: the first caller to flip 0 -> now
    performs the refresh; a concurrent caller fails the condition and is told to wait rather than
    firing a second refresh. A session's refresh token - especially a rotating one - is single-use,
    so two simultaneous refreshes would spend it twice and log the customer out, which is the exact
    thundering-herd this closes.

    `cognito_refresh(refresh_ref, rotation_enabled)` is injected; the caller wires it to
    `GetTokensFromRefreshToken` for a rotation client and `REFRESH_TOKEN_AUTH` otherwise, and
    returns `{"accessToken":..., "expiresIn":..., "refreshRef":<new ref or same>}`. It is a
    callable so this module needs no boto and the test drives both the success and the two distinct
    failure modes.

    Crucially, a successful refresh does NOT move `absoluteExpiresAt`. It slides the idle deadline
    (the customer is active) and may replace the refresh reference (rotation), nothing more.
    """
    moment = int(time.time()) if now is None else int(now)
    row = _live_row(store, session_id, moment)
    sid_hash = row["sidHash"]

    claimed = store.claim_refresh(sid_hash, now=moment, lease_seconds=REFRESH_LEASE_SECONDS)
    if not claimed:
        # Another tab/worker holds the single-flight lease. Do not fire a second refresh.
        raise RefreshUnavailable("a refresh is already in flight for this session")

    try:
        last_error: Optional[Exception] = None
        for _ in range(max(1, MAX_REFRESH_ATTEMPTS)):
            try:
                result = cognito_refresh(str(row.get("refreshRef") or ""),
                                         bool(row.get("rotationEnabled")))
                break
            except RefreshFailed:
                # The refresh token itself is spent/revoked. Retrying cannot help; this IS a logout.
                raise
            except Exception as transient:  # noqa: BLE001 - offline/5xx/throttle
                last_error = transient
                result = None
        if result is None:
            # Bounded retry exhausted on a transient fault. 503, NOT logout.
            logger.info('{"event":"customer_session_refresh_transient"}')
            raise RefreshUnavailable(
                "token refresh is temporarily unavailable; the session remains valid"
            ) from last_error

        new_ref = str(result.get("refreshRef") or row.get("refreshRef") or "")
        new_idle = min(moment + IDLE_LIFETIME_SECONDS, int(row["absoluteExpiresAt"]))
        store.record_refresh(sid_hash, refresh_ref=new_ref,
                             last_seen_at=moment, idle_expires_at=new_idle)
        logger.info('{"event":"customer_session_refreshed"}')
        return {
            "accessToken": result.get("accessToken"),
            "expiresIn": int(result.get("expiresIn") or 0),
        }
    except RefreshFailed:
        # A definite failure clears custody so a stale reference is not reused.
        store.revoke_session(sid_hash, revoked_at=moment)
        logger.info('{"event":"customer_session_refresh_failed"}')
        raise
    finally:
        store.release_refresh(sid_hash)


# ── cookie assembly ─────────────────────────────────────────────────────────────────
def build_set_cookie(session_id: str, *, persistent: bool,
                     absolute_expires_at: int, now: Optional[int] = None) -> str:
    """The `Set-Cookie` value for the opaque session id.

    `HttpOnly`     script cannot read it, so an XSS cannot exfiltrate the session.
    `Secure`       sent over TLS only.
    `SameSite=Lax` deliberate: the verified checkout journey is top-level same-site navigation, for
                   which Lax sends the cookie, while a cross-site POST does not get it - and the
                   CSRF token guards the mutations Lax would still allow on top-level GETs. `Strict`
                   would drop the cookie on the return hop from the payment provider; `None` would
                   invite CSRF. Lax plus the CSRF token is the policy section 16 asks for.
    host-only      no `Domain=` attribute, so the cookie is scoped to the exact host and not shared
                   with any sibling subdomain.
    `Max-Age`      only for a persistent session; a shared-device session is a session cookie that
                   dies with the browser. The server still enforces both deadlines regardless.
    """
    parts = [
        f"{COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "Secure",
        "SameSite=Lax",
    ]
    if persistent:
        moment = int(time.time()) if now is None else int(now)
        max_age = max(0, int(absolute_expires_at) - moment)
        parts.append(f"Max-Age={max_age}")
    return "; ".join(parts)


def build_clear_cookie() -> str:
    """The `Set-Cookie` that removes the session cookie on sign-out."""
    return (f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; "
            "Max-Age=0")


#: The pair every session-bearing response must carry. `no-store` is the instruction that matters;
#: `Pragma: no-cache` is included because that is the pair this repo already emits at
#: `edge/get-miss-redirect/handler.py:83`. `ai/mcp/handler.py:568` and
#: `core/site-language/handler.py:198` send `no-store` alone - the stricter existing pattern is the
#: one copied here, because an HTTP/1.0-era intermediary that ignores `Cache-Control` still honours
#: `Pragma`, and the cost of the extra header is one line.
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def harden_session_headers(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Merge the no-store pair into `headers`. Mandatory on any response carrying a csrfToken,
    a session id, or a session-bound deadline.

    Why this is necessary rather than defensive
    -------------------------------------------
    `SessionView.csrf_token` is a per-session secret that a handler returns in a response BODY, and
    `lambda_utils/response.py::cors_headers` sets no `Cache-Control` at all. These responses do not
    reach the browser directly either: the Amplify rewrite serves `/api/<*>` with status 200, so a
    shared cache sits in front of them. A cache that stored one customer's session response and
    replayed it to another would hand over that customer's CSRF token - and the token is exactly
    what `build_set_cookie`'s deliberate `SameSite=Lax` choice relies on to guard the mutations Lax
    still permits. Losing the token's secrecy therefore does not degrade the defence, it removes it.

    `response.py` is deliberately NOT changed to do this globally: `core/contacts/handler.py:285`
    removed `Cache-Control` on purpose, so a blanket header there would override a considered
    decision in an unrelated handler. The contract lives here, beside the session it protects, and
    each owning handler opts in.

    Returns a NEW dict; the input is never mutated, and anything already set on it - including a
    `Set-Cookie` or a caller's own `Cache-Control` - is preserved except that the no-store pair
    wins. A weaker `Cache-Control` on a session response is a bug, not a preference.
    """
    merged: Dict[str, str] = dict(headers or {})
    merged.update(NO_STORE_HEADERS)
    return merged


def read_cookie(headers: Optional[Dict[str, Any]]) -> str:
    """The opaque id out of a request's Cookie header, or ''. Case-insensitive header lookup."""
    if not headers:
        return ""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    raw = str(lowered.get("cookie") or "")
    for pair in raw.split(";"):
        name, _, value = pair.strip().partition("=")
        if name == COOKIE_NAME:
            return value.strip()
    return ""


__all__ = [
    "ABSOLUTE_LIFETIME_SECONDS",
    "IDLE_LIFETIME_SECONDS",
    "SHARED_DEVICE_ABSOLUTE_SECONDS",
    "COOKIE_NAME",
    "DEFAULT_TABLE_NAME",
    "REFRESH_LEASE_SECONDS",
    "MAX_REFRESH_ATTEMPTS",
    "table_name",
    "SessionError",
    "SessionInvalid",
    "CsrfInvalid",
    "RefreshFailed",
    "RefreshUnavailable",
    "SessionView",
    "new_opaque_id",
    "is_session_id",
    "new_csrf_token",
    "create_session",
    "validate",
    "assert_csrf",
    "rotate",
    "revoke",
    "refresh_access_token",
    "build_set_cookie",
    "build_clear_cookie",
    "read_cookie",
    "NO_STORE_HEADERS",
    "harden_session_headers",
]
