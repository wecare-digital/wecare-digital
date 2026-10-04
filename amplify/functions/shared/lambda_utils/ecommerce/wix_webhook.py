"""Wix webhook verification. The raw request BODY is an RS256 JWT signed by Wix.

Design reference: `.agents/tasks/wix-catalog-auto-sync-b2.md` step 3, which requires that the
rebuild endpoint "must verify the Wix webhook signature (do not rebuild on an unauthenticated
POST)".

What Wix sends
--------------
Per Wix's webhooks documentation, event data arrives as a JSON Web Token in the BODY of the
request - there is no separate signature header and no HMAC. The token is signed with the app's
private key and is verified with the PUBLIC key from the Webhooks page of the Wix app dashboard.
The key is PER APP; Wix publishes no JWKS endpoint, so there is nothing to fetch and the key has
to be configured.

The envelope, as documented rather than as measured
---------------------------------------------------
    <JWT payload>
      iss   : "wix.com"
      aud   : our appId
      iat   : int
      exp   : int
      data  : a JSON **STRING**, which parses to
                instanceId : str
                eventType  : str   e.g. "wix.stores.catalog.v3.product_created"
                data       : a JSON string again, the entity itself
                slug       : str   (on some event shapes)
                entityId   : str

`data` being a string that contains a string is the shape Wix's own examples show, and this module
therefore decodes DEFENSIVELY: `_unwrap` accepts a dict or a JSON string at either level and gives
up quietly rather than raising. **That is deliberate and it is the security-relevant decision in
this file.** The payload fields are used for LOGGING AND REPORTING ONLY. Nothing in the rebuild
decision reads them: a verified Wix event means "re-read the catalogue", and re-reading the
catalogue is correct whatever the event said. So a Wix envelope change can cost a useful log line
and can never cost a missed sync or an unauthenticated rebuild.

NOT a copy of gift_card_spi_auth, and not a refactor of it either
-----------------------------------------------------------------
`lambda_utils/ecommerce/gift_card_spi_auth.py` verifies the same kind of token with the same
discipline, and the signature-checking half of this file is close to its. They are deliberately
NOT merged:

  - that module is on the MONEY path (gift-card balance, redeem, void) and is tightly bound to
    SPI semantics - `aud == app_id` and `metadata.instanceId == <installed instance>` are both
    MANDATORY there, and `data.request` / `data.metadata` is an SPI-only shape;
  - this one is a catalogue-refresh trigger with a different envelope and a different secret;
  - extracting a shared core would mean editing a reviewed money-path verifier to serve a
    catalogue job, and the B2 brief says in terms: do not touch the money/checkout path.

Eighty lines of verification duplicated is the cheaper mistake. The two share their `ALLOWED_
ALGORITHMS` values, their clock-skew bound and their fail-closed posture by convention, and a
reader comparing them should find them boringly similar.

Fail-closed at every step
-------------------------
Every failure raises `WixWebhookUnauthorized`, which the handler answers as **401 with an empty
body**. No detail reaches the caller: it is either Wix, which does not need it, or someone
probing, who must not have it.

The algorithm allowlist is `{RS256, RS384, RS512}`. `alg: none` and every HMAC algorithm are
refused outright - accepting the token's own `alg` is the textbook JWT key-confusion attack, and
an HMAC `alg` verified against a PUBLIC key is its worst form, because the attacker has the key.

The public key is read LAZILY, per request, through an injected reader. A module-scope read caches
for the life of the execution environment, so rotating the key in Secrets Manager would not take
effect until every warm sandbox recycled - the exact defect fixed in `payments/razorpay-webhook`
on 2026-09-19. Neither the key nor any token segment appears in a logging expression anywhere in
this module; it logs nothing at all, because CodeQL's `py/clear-text-logging-sensitive-data`
tracks taint across function boundaries and reducing a secret to a bool does not launder it.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

#: GUARDED, and for a PACKAGING reason rather than any doubt about the dependency.
#:
#: `cryptography` lives in the layer `cryptography-python312`, attached only to the functions that
#: need it. This file is part of the shared `lambda_utils` tree, which
#: `scripts/deploy_all_lambdas.py` packages into EVERY function that ships that tree - including
#: ones with no layers at all. An unguarded top-level import would fail that script's static
#: import check for ~60 unrelated functions, which `tests/test_checkout_package_completeness.py`
#: enforces as an error.
#:
#: The import stays at module scope rather than moving inside `verify_signature`: the deploy gate
#: reads TOP-LEVEL imports, so hiding it would make a missing layer invisible to tooling.
#:
#: Without the layer this FAILS CLOSED - `verify_signature` refuses every request rather than
#: skipping the check. A verifier that cannot verify must answer 401, not 200.
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
except ImportError as _import_error:          # pragma: no cover - only without the layer
    _CRYPTOGRAPHY_UNAVAILABLE = type(_import_error).__name__
    InvalidSignature = None   # type: ignore[assignment]
    hashes = None             # type: ignore[assignment]
    padding = None            # type: ignore[assignment]
    load_pem_public_key = None  # type: ignore[assignment]
else:
    _CRYPTOGRAPHY_UNAVAILABLE = ""

#: Secret NAME, never a value. Carries `public_key` (the PEM from the Wix app dashboard) and
#: optionally `app_id`. A PEM public key is not a credential, but it is configuration that decides
#: who may trigger a production rebuild, so it lives beside the rest rather than in an env var
#: anybody with console read can edit.
SECRET_ID = "wecare/wix/catalog-webhook"
PUBLIC_KEY_FIELD = "public_key"
APP_ID_FIELD = "app_id"

#: Asymmetric only. The configured key is a PUBLIC key, so an HMAC algorithm here would mean
#: verifying a signature with a value the attacker also holds.
#:
#: Mapped to hash NAMES rather than to `hashes.SHA256` objects so this module still IMPORTS when
#: the layer is absent. The class is resolved per call, after the unavailability refusal.
ALLOWED_ALGORITHMS: Dict[str, str] = {
    "RS256": "SHA256",
    "RS384": "SHA384",
    "RS512": "SHA512",
}

#: Bounded and symmetric. A missing `iat` or `exp` is REJECTED, never defaulted - a token with no
#: expiry is a replay token.
CLOCK_SKEW_SECONDS = 60

ISSUER = "wix.com"

_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class WixWebhookUnauthorized(Exception):
    """Verification failed. The handler answers 401 with an EMPTY body.

    The message is for OUR logs and is assembled from known-safe parts only - never a claim
    value, never the key, never a segment of the token.
    """


@dataclass(frozen=True)
class WixEvent:
    """A verified Wix webhook, reduced to what a log line and a report need.

    Every field may be empty, and an empty field is NOT an error. See the module docstring: the
    rebuild decision does not read any of them, so a Wix envelope change degrades a log line
    rather than the trigger.
    """

    event_type: str = ""
    slug: str = ""
    entity_id: str = ""
    instance_id: str = ""


SecretReader = Callable[[str], Mapping[str, Any]]


def _hash_for(algorithm: str):
    """The hash instance the `alg` NAMES, resolved from the allowlist and never from the token.

    The token supplies a name that must already be a key of `ALLOWED_ALGORITHMS`; the class comes
    from the library. That is what makes "the token cannot choose its own algorithm" structural
    rather than a promise.
    """
    return getattr(hashes, ALLOWED_ALGORITHMS[algorithm])()


def _b64url(segment: str) -> bytes:
    """Decode one base64url segment, padding it here. Raises on anything that is not base64url."""
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as error:
        raise WixWebhookUnauthorized("a token segment is not base64url") from error


def _json_segment(raw: bytes) -> Any:
    """Parse a decoded token segment as JSON."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise WixWebhookUnauthorized("a token segment is not JSON") from error


def token_from_body(raw_body: Any, *, is_base64_encoded: bool = False) -> str:
    """The JWT, from the raw request body. `isBase64Encoded` is honoured FIRST.

    Before any JWT parsing, because an API Gateway binary-media-type route would otherwise present
    a double-encoded token and the three-segment check would refuse a perfectly good call.
    """
    if isinstance(raw_body, bytes):
        text = raw_body.decode("utf-8", errors="replace")
    elif isinstance(raw_body, str):
        text = raw_body
    else:
        raise WixWebhookUnauthorized("the request body is not a string")
    if is_base64_encoded:
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise WixWebhookUnauthorized("the body is flagged base64 and is not") from error
    return text.strip()


def is_jwt_shaped(token: Any) -> bool:
    """Three non-empty base64url segments separated by dots. THE discriminator.

    A property of the token rather than a declaration about it, which is why there is no
    Content-Type check: Wix publishes no Content-Type contract for webhook delivery, and 401-ing
    on an undocumented header value would make the endpoint answer nothing for a reason
    indistinguishable from a bad key.
    """
    if not isinstance(token, str):
        return False
    parts = token.split(".")
    return len(parts) == 3 and all(part and _SEGMENT.match(part) for part in parts)


def _unwrap(value: Any) -> Dict[str, Any]:
    """A dict, from a dict or from a JSON string holding one. `{}` on anything else.

    NEVER raises. Wix nests `data` as a JSON string inside a JSON string, and this is only ever
    used for the reporting fields - see the module docstring on why that is safe.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _describe(payload: Mapping[str, Any]) -> WixEvent:
    """Best-effort reporting fields out of a VERIFIED payload. Never raises."""
    envelope = _unwrap(payload.get("data"))
    entity = _unwrap(envelope.get("data"))
    # `slug` lives on the entity for a product event and on the envelope for some others, so both
    # are tried. An empty answer is a thinner log line and nothing more.
    slug = entity.get("slug") or envelope.get("slug") or ""
    entity_id = (
        envelope.get("entityId")
        or entity.get("id")
        or entity.get("_id")
        or ""
    )
    return WixEvent(
        event_type=str(envelope.get("eventType") or envelope.get("eventName") or ""),
        slug=str(slug or ""),
        entity_id=str(entity_id or ""),
        instance_id=str(envelope.get("instanceId") or ""),
    )


def verify_signature(raw_body: Any, *, now: int, reader: SecretReader,
                     is_base64_encoded: bool = False,
                     secret_id: str = SECRET_ID,
                     headers: Optional[Mapping[str, Any]] = None) -> WixEvent:
    """Verify a Wix webhook and return its reporting fields. Raises `WixWebhookUnauthorized`.

    The order, and every step fails closed:

    1. honour `isBase64Encoded`, then refuse a body that is not three base64url segments, BEFORE
       any claim is decoded;
    2. refuse an `alg` outside the allowlist - which covers `none` and every HMAC in one check;
    3. read the public key by reference and LAZILY;
    4. verify the signature over `header.payload`;
    5. `iss == "wix.com"`, exact string;
    6. `iat <= now + 60` and `exp > now - 60`, a missing claim refused and never defaulted;
    7. `aud == app_id`, but ONLY when an `app_id` is configured - see below;
    8. only then describe the event, which cannot fail.

    `aud` IS CONDITIONAL, AND THAT IS A DECISION. `gift_card_spi_auth` requires `app_id` and
    refuses without it, because a gift-card redemption aimed at the wrong app is a money event.
    Here the `app_id` is not knowable until the owner creates the Wix app, and the consequence of
    the weaker check is bounded: an attacker would need a token signed by the configured PUBLIC
    KEY's private half to get this far at all, and the worst they could then achieve is a
    catalogue re-read. So the check is applied when the field is present and the field is optional,
    which lets the receiver work the moment the public key is configured. Configure `app_id` too;
    this is a floor, not a recommendation.

    `headers` is accepted and used for NO decision. It is in the signature because the documented
    call shape carries headers and a later reader will look for them.
    """
    if _CRYPTOGRAPHY_UNAVAILABLE:
        raise WixWebhookUnauthorized(
            f"the signature library is unavailable ({_CRYPTOGRAPHY_UNAVAILABLE}); "
            "the cryptography layer is not attached to this function")

    token = token_from_body(raw_body, is_base64_encoded=is_base64_encoded)
    if not is_jwt_shaped(token):
        raise WixWebhookUnauthorized("the request body is not a three-segment JWT")
    header_segment, payload_segment, signature_segment = token.split(".")

    header = _json_segment(_b64url(header_segment))
    if not isinstance(header, dict):
        raise WixWebhookUnauthorized("the token header is not an object")
    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm not in ALLOWED_ALGORITHMS:
        raise WixWebhookUnauthorized("the token names an algorithm outside the allowlist")

    # Read at THIS point, per request, not at import.
    secret = reader(secret_id) or {}
    public_key_pem = secret.get(PUBLIC_KEY_FIELD)
    app_id = secret.get(APP_ID_FIELD)
    if not isinstance(public_key_pem, str) or not public_key_pem:
        raise WixWebhookUnauthorized("no usable public key is configured")

    try:
        public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as error:  # noqa: BLE001 - any failure here is a refusal, never a 500
        raise WixWebhookUnauthorized(
            f"the configured public key did not load ({type(error).__name__})") from None

    signing_input = (header_segment + "." + payload_segment).encode("ascii")
    try:
        public_key.verify(_b64url(signature_segment), signing_input,
                          padding.PKCS1v15(), _hash_for(algorithm))
    except InvalidSignature:
        raise WixWebhookUnauthorized("the token signature does not verify") from None
    except Exception as error:  # noqa: BLE001 - e.g. an EC key presented for an RS alg
        raise WixWebhookUnauthorized(
            f"the token signature could not be checked ({type(error).__name__})") from None

    payload = _json_segment(_b64url(payload_segment))
    if not isinstance(payload, dict):
        raise WixWebhookUnauthorized("the token payload is not an object")

    if payload.get("iss") != ISSUER:
        raise WixWebhookUnauthorized("the token issuer is not Wix")

    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    # `bool` is excluded explicitly: `isinstance(True, int)` is True in Python, so `iat: true`
    # would otherwise pass as the integer 1 and date the token to 1970.
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise WixWebhookUnauthorized("the token carries no usable iat")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise WixWebhookUnauthorized("the token carries no usable exp")
    if issued_at > now + CLOCK_SKEW_SECONDS:
        raise WixWebhookUnauthorized("the token is issued in the future")
    if expires_at <= now - CLOCK_SKEW_SECONDS:
        raise WixWebhookUnauthorized("the token has expired")

    if isinstance(app_id, str) and app_id:
        audience = payload.get("aud")
        # A list-valued `aud` is refused rather than searched: "one of these apps" is not a
        # statement this endpoint has any reason to accept.
        if not isinstance(audience, str) or audience != app_id:
            raise WixWebhookUnauthorized("the token audience is not this application")

    return _describe(payload)
