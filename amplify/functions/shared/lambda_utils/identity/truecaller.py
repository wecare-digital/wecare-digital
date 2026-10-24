"""Truecaller consent verification: nonce lifecycle, endpoint allowlist, profile mapping.

The contract, from Truecaller's mobile-web documentation
-------------------------------------------------------
1. We mint a `requestNonce` (8-64 characters) and open a deep link::

       truecallersdk://truesdk/web_verify?requestNonce=...&partnerKey=<app_key>
           &partnerName=<app_name>&lang=en&...

2. The user consents in the Truecaller app.
3. Truecaller **POSTs to our callback URL**::

       {"requestId": "...", "accessToken": "...",
        "endpoint": "https://profile4-noneu.truecaller.com/v1/default"}

   or, on refusal::

       {"requestId": "...", "status": "user_rejected"}

4. We GET that endpoint with `Authorization: Bearer <accessToken>` and receive the profile:
   `phoneNumbers`, `name.first/last`, `onlineIdentities.email`, `badges`, and so on.

The security property that drives this module
---------------------------------------------
**Step 3 hands us the URL we are about to trust, and step 4 believes it.**

The callback is a public, unauthenticated endpoint - it has to be, because Truecaller calls
it. So `endpoint` is attacker-controlled input. Point it at a host under the attacker's
control, return `{"phoneNumbers": ["919999999999"]}`, and we record that number as
*verified for the current user*. That is a complete authentication bypass wearing the costume
of a feature, and it is simultaneously an SSRF into whatever the Lambda can reach - including
the VPC and the instance metadata service.

`resolve_profile_endpoint` therefore refuses any host outside `ALLOWED_PROFILE_HOSTS`,
requires HTTPS, and rejects embedded credentials, ports and redirect-looking paths. The
allowlist is the control; the `Bearer` token is not, because the attacker supplies that too.

The second property: no bulk lookup
-----------------------------------
The brief requires consent-based verification of the **current user** only. The structural
guarantee is that a profile fetch is reachable only with an access token Truecaller minted
against a nonce **we** issued, and `claim_nonce` binds the nonce to the session that asked
for it - so the flow cannot verify a third party's number either, only the person holding the
handset.

There is deliberately no function here that takes a phone number and asks Truecaller who owns
it. That API exists; we do not call it, and this module exposes no arbitrary-number lookup function.

Nonce rules
-----------
* Minted by us from a CSPRNG, never sequential - it is the only correlation the public
  callback has.
* Single use. `claim_nonce` is a state transition, so a replayed callback cannot re-verify.
* Expiring. A consent dialog the user abandons must not leave a nonce claimable next week.
* Bound to a session. Otherwise user A completes a flow and the result lands on user B.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlparse

#: Hosts permitted to serve a profile. Truecaller routes by region, hence the pair.
#: An exact-match set, not a suffix test: a suffix check on "truecaller.com" would accept
#: `truecaller.com.evil.example`, which is the classic bypass of that shortcut.
ALLOWED_PROFILE_HOSTS = frozenset({
    "profile4-noneu.truecaller.com",
    "profile4-eu.truecaller.com",
})

DEEP_LINK_SCHEME = "truecallersdk://truesdk/web_verify"

#: Truecaller's documented bounds for `requestNonce`.
NONCE_MIN_LENGTH = 8
NONCE_MAX_LENGTH = 64

#: How long a minted nonce stays claimable. A consent dialog is a few seconds of user
#: attention; ten minutes is generous and still closes the window on an abandoned flow.
NONCE_TTL_SECONDS = 600

STATUS_PENDING = "PENDING"
STATUS_VERIFIED = "VERIFIED"
STATUS_REJECTED = "REJECTED"
STATUS_EXPIRED = "EXPIRED"

#: What we record as the origin of a verified number. `provenance.SOURCE_TRUST` maps this to
#: VERIFIED - the user proved possession of the handset by consenting in the app.
SOURCE = "TRUECALLER"


class UntrustedEndpoint(ValueError):
    """The callback named a profile host we do not trust.

    A distinct type because this is the auth-bypass attempt, not a formatting problem, and it
    must never be recovered from by falling back to a default host - that would make the
    check decorative.
    """


class NonceRejected(ValueError):
    """The callback's requestId does not match a live, unclaimed nonce."""


# ---------------------------------------------------------------------------
# Nonce
# ---------------------------------------------------------------------------

def new_nonce() -> str:
    """A fresh request nonce.

    `secrets.token_urlsafe(24)` gives 32 characters - inside Truecaller's 8-64 bound with
    192 bits of entropy. It must be unguessable because the callback endpoint is public and
    unauthenticated, so this value is the only thing tying a callback to a real request.
    """
    nonce = secrets.token_urlsafe(24)
    return nonce[:NONCE_MAX_LENGTH]


def nonce_is_wellformed(nonce: Optional[str]) -> bool:
    if not nonce:
        return False
    return NONCE_MIN_LENGTH <= len(str(nonce)) <= NONCE_MAX_LENGTH


def nonce_record(nonce: str, *, session_id: str, actor: str = "",
                 at: Optional[int] = None,
                 ttl_seconds: int = NONCE_TTL_SECONDS) -> Dict[str, Any]:
    """A storable nonce claim.

    `sessionId` is required, not optional. Without it a verified number has nowhere to land
    except "whoever polls next", which is how user A's consent ends up on user B's contact.
    """
    if not nonce_is_wellformed(nonce):
        raise ValueError(
            f"nonce must be {NONCE_MIN_LENGTH}-{NONCE_MAX_LENGTH} characters")
    if not session_id:
        raise ValueError("session_id is required; a verified number must bind to a session")
    now = at if at is not None else int(time.time())
    return {
        "requestNonce": nonce,
        "sessionId": session_id,
        "actorId": actor or "",
        "status": STATUS_PENDING,
        "createdAt": now,
        "expiresAt": now + int(ttl_seconds),
        # TTL attribute, so an abandoned consent cleans itself up.
        "ttl": now + int(ttl_seconds) + 86400,
    }


def claim_nonce(record: Optional[Mapping[str, Any]], received_nonce: str, *,
                at: Optional[int] = None) -> Tuple[bool, str]:
    """`(claimable, reason)` for a callback against a stored nonce.

    Pure: the atomic single-use claim is a conditional write in the store. This function
    decides *whether* the claim is legitimate; it cannot enforce that it happens once, and
    pretending otherwise would put a read-then-write race on the auth path.
    """
    if not record:
        return False, "no such nonce"
    if not received_nonce or str(record.get("requestNonce")) != str(received_nonce):
        return False, "nonce mismatch"
    status = str(record.get("status") or "")
    if status != STATUS_PENDING:
        # Already used, rejected or expired. A replayed callback lands here.
        return False, f"nonce is {status or 'in an unknown state'}, not {STATUS_PENDING}"
    now = at if at is not None else int(time.time())
    try:
        expires_at = int(record.get("expiresAt") or 0)
    except (TypeError, ValueError):
        return False, "nonce has no usable expiry"
    if expires_at <= now:
        return False, "nonce has expired"
    return True, "ok"


# ---------------------------------------------------------------------------
# Deep link
# ---------------------------------------------------------------------------

def build_deep_link(*, nonce: str, app_key: str, app_name: str,
                    lang: str = "en",
                    privacy_url: str = "", terms_url: str = "",
                    ttl_ms: Optional[int] = None) -> str:
    """The `truecallersdk://` deep link the mobile page triggers.

    `app_key` is the partner key from the secret. It identifies our app to Truecaller and is
    not a bearer credential for our own systems, but it is still read from Secrets Manager
    rather than embedded here - the caller passes it in.
    """
    if not nonce_is_wellformed(nonce):
        raise ValueError(
            f"nonce must be {NONCE_MIN_LENGTH}-{NONCE_MAX_LENGTH} characters")
    if not app_key:
        raise ValueError("app_key is required")
    if not app_name:
        raise ValueError("app_name is required")

    parts = [
        f"requestNonce={quote(nonce, safe='')}",
        f"partnerKey={quote(app_key, safe='')}",
        f"partnerName={quote(app_name, safe='')}",
        f"lang={quote(lang or 'en', safe='')}",
    ]
    if privacy_url:
        parts.append(f"privacyUrl={quote(privacy_url, safe='')}")
    if terms_url:
        parts.append(f"termsUrl={quote(terms_url, safe='')}")
    if ttl_ms is not None:
        # Truecaller floors this at 8000ms; sending less is silently raised, so clamp here to
        # keep the link honest about what will happen.
        parts.append(f"ttl={max(8000, int(ttl_ms))}")
    return f"{DEEP_LINK_SCHEME}?type=btmsheet&" + "&".join(parts)


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

def read_callback(body: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Normalise the callback body into `{requestId, accessToken, endpoint, rejected}`.

    Truecaller sends either an access token or `status: "user_rejected"`. A rejection is a
    normal outcome, not an error - the user declined - so it is reported rather than raised.
    """
    payload = dict(body or {})
    status = str(payload.get("status") or "").strip().lower()
    return {
        "requestId": str(payload.get("requestId") or "").strip(),
        "accessToken": str(payload.get("accessToken") or "").strip(),
        "endpoint": str(payload.get("endpoint") or "").strip(),
        "rejected": status == "user_rejected",
        "status": status,
    }


def resolve_profile_endpoint(endpoint: Optional[str]) -> str:
    """Validate the callback-supplied profile URL, or refuse it.

    **This is the security boundary of the whole flow.** The callback is public and
    unauthenticated, so `endpoint` is attacker-controlled. An attacker who can reach the
    callback and choose this host returns any phone number they like and we record it as
    verified for the current user - and the same primitive is an SSRF into the VPC and the
    instance metadata service.

    Every check below closes a specific bypass:

    * **HTTPS only** - `http://` would allow interception even of an allowlisted host.
    * **Exact host match** - a suffix test on `truecaller.com` accepts
      `truecaller.com.evil.example`; a substring test accepts
      `evil.example/profile4-noneu.truecaller.com`.
    * **No userinfo** - `https://profile4-noneu.truecaller.com@evil.example/` has
      `evil.example` as its real host, and reading the text left to right suggests otherwise.
      `urlparse` gets this right; humans reviewing logs do not.
    * **No explicit port** - restricting to 443 removes the allowlisted name pointing at an
      unexpected service.
    * **No query or fragment** - the documented endpoint has neither, and both are places to
      smuggle a redirect.

    Refuses rather than defaulting to a known host: silently substituting one would make the
    check decorative and hide an attack in progress.
    """
    raw = (endpoint or "").strip()
    if not raw:
        raise UntrustedEndpoint("callback carried no profile endpoint")

    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise UntrustedEndpoint(f"profile endpoint must be https, got {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise UntrustedEndpoint(
            "profile endpoint carries userinfo; the real host is after the '@'")
    if parsed.port is not None:
        raise UntrustedEndpoint("profile endpoint must not specify a port")
    if parsed.query or parsed.fragment:
        raise UntrustedEndpoint("profile endpoint must not carry a query or fragment")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_PROFILE_HOSTS:
        # The host is named because it is attacker-supplied, not secret, and naming it is what
        # makes the log line actionable.
        raise UntrustedEndpoint(
            f"profile host {host!r} is not an allowed Truecaller profile host "
            f"({sorted(ALLOWED_PROFILE_HOSTS)})")
    return raw


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def verified_phone(profile: Optional[Mapping[str, Any]]) -> str:
    """The single phone number this consent verifies, or `''`.

    Truecaller returns `phoneNumbers` as a list. Exactly one number is taken - the first -
    because the assertion is about the handset the user consented on. Treating every entry as
    verified would let one consent vouch for numbers the user never proved possession of.
    """
    numbers = (profile or {}).get("phoneNumbers")
    if not isinstance(numbers, list):
        return ""
    for value in numbers:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def to_contact_fields(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a Truecaller profile onto our Contact fields.

    Only `phone` carries the VERIFIED weight - that is what the consent actually proves. The
    name and email are self-reported profile data of the same quality as an address book, so
    they are returned separately by `declared_fields` rather than mixed in here, and the
    caller records them under a weaker source.
    """
    phone = verified_phone(profile)
    return {"phone": phone} if phone else {}


def declared_fields(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Profile data the consent does NOT verify: name, email, company.

    Kept apart from `to_contact_fields` on purpose. The consent proves possession of a phone
    number; it proves nothing about the name on the Truecaller profile, which the user typed.
    Recording those at VERIFIED would let a self-chosen display name overwrite a name the
    customer gave us in our own Flow.
    """
    fields: Dict[str, Any] = {}
    name = profile.get("name")
    if isinstance(name, Mapping):
        full = " ".join(str(name.get(part) or "").strip()
                        for part in ("first", "last")).strip()
        if full:
            fields["name"] = full
    identities = profile.get("onlineIdentities")
    if isinstance(identities, Mapping):
        email = str(identities.get("email") or "").strip()
        if email:
            fields["email"] = email
    company = str(profile.get("companyName") or "").strip()
    if company:
        fields["companyName"] = company
    title = str(profile.get("jobTitle") or "").strip()
    if title:
        fields["designation"] = title
    return fields


def summarize_profile(profile: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Log-safe summary. No phone number, no email, no name."""
    phone = verified_phone(profile)
    badges = (profile or {}).get("badges")
    return {
        "hasVerifiedPhone": bool(phone),
        "phoneSuffix": phone[-4:] if len(phone) >= 4 else "",
        "declaredFields": sorted(declared_fields(profile or {}).keys()),
        "badges": [str(b) for b in badges] if isinstance(badges, list) else [],
        "isActive": str((profile or {}).get("isActive") or ""),
    }
