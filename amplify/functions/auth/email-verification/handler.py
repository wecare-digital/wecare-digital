"""Email verification for checkout: request a code, then verify it.

This is the wiring, not the mechanism
-------------------------------------
Every hard part already exists as a tested, storage-agnostic, AWS-free module, and this handler
composes them rather than reimplementing any of them:

- `lambda_utils.otp_throttle`   — per-phone and per-IP limits, fail-closed, so one origin cannot
                                   flood many addresses and one address cannot be flooded.
- `lambda_utils.otp_challenge`  — the code itself: HMAC-with-pepper at rest, TTL, attempt cap,
                                   resend cooldown, resend window, single-use conditional consume.
- `lambda_utils.comms.verification_email` — the branded SESv2 send from `one@wecare.digital`
                                   with the `wecare-digital` configuration set attached.
- `lambda_utils.identity.customer` — `normalize_email`, so the code is keyed to exactly one
                                   spelling of the address.

Two endpoints, and the security properties that shape them
----------------------------------------------------------
`request`  throttle → issue → send. The throttle runs BEFORE the code is issued, so a refused
           request never spends a send. The code is generated inside `otp_challenge.issue`,
           returned once, handed straight to SES, and never touched again — not logged, not
           echoed, not stored in plaintext.

`verify`   check the code and, on success, mark the address verified on the customer record with
           a conditional write so it happens at most once.

**No enumeration, on either endpoint.** `request` returns the same shape whether or not the
address is already known — there is no "email already registered" branch, because that branch is
an oracle. `verify` collapses every failure (`no challenge`, `wrong code`, `expired`, `already
used`, `attempts exhausted`) into one opaque `INVALID_OR_EXPIRED` via
`VerificationResult.public_outcome()`; the server keeps the real reason for its logs and metrics.

The pepper is read lazily
--------------------------
`_pepper()` reads `wecare/otp/pepper` from Secrets Manager on first use and caches it for the
execution environment — never at import scope. A module-scope read would freeze the value into a
warm sandbox, so a rotation would silently keep validating against the old pepper until every
sandbox recycled. Read by reference only: the value never reaches a command line, a log, or a
response. Rotating the pepper invalidates every outstanding code, which is the correct blast
radius — a customer simply requests another.

Why this is a standalone function, not a branch of outbound-email
-----------------------------------------------------------------
`messaging/outbound-email` is SES v1 with `noreply@` and no configuration set, and it sends
opted-in CRM mail keyed on a contact id. A verification code is a different message with different
rules: a verified sender under `p=reject`, a configuration set so a bounce is visible, and a
recipient who may not be a contact yet. Folding it in would mean one handler with two senders and
two trust models. It is cleaner as its own small function.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from typing import Any, Dict, Optional

import boto3

from lambda_utils import customer_session, otp_challenge, otp_throttle
from lambda_utils.comms import verification_email
from lambda_utils.identity import customer as identity
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    """Every response from this door is uncacheable. Applied at the return, not at the builder.

    `response.py::cors_headers` sets no `Cache-Control`, and these responses travel through the
    Amplify `/api/<*>` status-200 rewrite, so a shared cache sits in front of them. A cached
    verification outcome replayed to another caller is an answer about someone else's address and
    someone else's throttle budget. `response.py` is deliberately left alone -
    `core/contacts/handler.py:285` removed `Cache-Control` there on purpose - so the contract is
    applied here. The throttle rejection is wrapped too: it is built by `otp_throttle`, not by
    `cors_response`, and a cached 429 would misreport another caller's budget.
    """
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened

# ── configuration ────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-east-1")

#: The short-lived challenge + throttle store. `DownloadGrantsTable` (key `grantId`, TTL on
#: `expiresAt`) is the established precedent — the WhatsApp-auth probe counter already shares it,
#: and both OTP modules default to a `grantId` key. Reusing it avoids standing up a table for a
#: handful of ephemeral rows.
OTP_TABLE = os.environ.get("OTP_TABLE", "stack-wecare-digital-DownloadGrantsTable")

#: This handler writes NO person record. Verification proves ownership of the email only; the
#: authenticated profile endpoint (`auth/customer-profile`) consumes the proof and stamps
#: `emailVerifiedAt` on the customer's row in the one contact store, ContactsTable. The
#: `CUSTOMERS_TABLE` stamp that used to live here pointed at a table that never existed and had
#: no caller; it was removed so there is exactly one person store.

#: Read by reference, lazily. Never printed. The `block-inline-secrets` hook explicitly allows a
#: `SecretId='wecare/...'` name, which is what this is — a name, not a value.
OTP_PEPPER_SECRET_ID = os.environ.get("OTP_PEPPER_SECRET_ID", "wecare/otp/pepper")

PURPOSE = "email_verification"
PROOF_PURPOSE = "email_verification_proof"
PROOF_PREFIX = "email-proof#"
PROOF_TTL_SECONDS = 15 * 60

_dynamodb = None
_secrets = None
_pepper_cache: Dict[str, str] = {}


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(OTP_TABLE)


def _proof_digest(email: str) -> str:
    message = ("email-proof\x1f" + email).encode("utf-8")
    return hmac.new(_pepper().encode("utf-8"), message, sha256).hexdigest()


def _issue_proof(email: str) -> str:
    proof_id = secrets.token_urlsafe(24)
    now = int(time.time())
    _table().put_item(Item={
        "grantId": PROOF_PREFIX + proof_id,
        "purpose": PROOF_PURPOSE,
        "subjectDigest": _proof_digest(email),
        "createdAt": now,
        "expiresAt": now + PROOF_TTL_SECONDS,
    })
    return proof_id


def _ses_client():
    return boto3.client("sesv2", region_name=REGION)


def _pepper() -> str:
    """Resolve the OTP pepper from Secrets Manager, lazily, cached per environment.

    Raises rather than returning '' when the secret is missing: `otp_challenge` refuses to hash
    without a pepper, and surfacing that here as a 503 is clearer than an opaque hash failure.
    """
    global _secrets
    if "pepper" in _pepper_cache:
        return _pepper_cache["pepper"]
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    raw = _secrets.get_secret_value(SecretId=OTP_PEPPER_SECRET_ID).get("SecretString", "") or ""
    value = ""
    try:
        data = json.loads(raw)
        value = (data.get("pepper") or data.get("value") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise RuntimeError("OTP pepper is not configured")
    _pepper_cache["pepper"] = value
    return value


# ── request/response helpers ──────────────────────────────────────────────────

def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        # An internal Lambda invoke may pass fields at the top level rather than in `body`.
        return {k: v for k, v in event.items()
                if k not in ("requestContext", "headers", "httpMethod", "path",
                             "rawPath", "isBase64Encoded")}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _action(event: Dict[str, Any], body: Dict[str, Any]) -> str:
    """Which operation to run. From an explicit `action`, or inferred from the path suffix."""
    explicit = str(body.get("action") or event.get("action") or "").strip().lower()
    if explicit in ("request", "verify"):
        return explicit
    path = str(event.get("rawPath") or event.get("path") or "").lower()
    if path.endswith("/verify"):
        return "verify"
    return "request"


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))

    # No JWT requirement here, deliberately. Email verification runs DURING checkout, before the
    # customer has any session to present a token from — the same position as the WhatsApp OTP
    # front door. The control on this endpoint is not a bearer token; it is the per-phone/per-IP
    # throttle (fail-closed) plus the fact that neither endpoint reveals whether an address is
    # known. Requiring auth would make the verification step unreachable for the very people it
    # exists to onboard. This route is therefore listed in AUTH_SKIP_PATHS at the gateway.

    body = _body(event)
    action = _action(event, body)
    try:
        if action == "verify":
            return _verify(event, body, origin)
        return _request(event, body, origin)
    except Exception as exc:  # noqa: BLE001
        # Type only. An exception message can echo the address or the code.
        logger.error(json.dumps({"event": "email_verification_error",
                                  "action": action, "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))


def _request(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Issue and send a verification code. Same response whether or not the address is known."""
    try:
        email = identity.normalize_email(body.get("email"))
    except identity.InvalidEmailAddress:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))

    first_name = str(body.get("firstName") or "").strip()

    # A phone axis is required by the throttle; fall back to the email so an email-only request is
    # still bounded per-address. The IP axis comes from the gateway context and cannot be spoofed.
    #
    # The phone is NORMALISED before it becomes a throttle key. Passing the raw value gave
    # `+65 9123 4567` and `+6591234567` two separate buckets, so respacing one number bought a
    # fresh budget - a free evasion. The strict normaliser is used rather than
    # `identity.normalize_phone` because the lenient one collapses a ten-digit foreign number
    # onto an unrelated Indian number's bucket, which would let one customer exhaust another's.
    #
    # Any failure falls back to the email subject and NEVER returns 400: the phone is optional on
    # this endpoint, so rejecting the request over its shape would break email-only verification.
    try:
        throttle_subject = identity.normalize_phone_preserving_country(body.get("phone"))
    except identity.InvalidPhoneNumber:
        throttle_subject = email
    try:
        otp_throttle.check_and_consume(_table(), phone_e164=throttle_subject, event=event)
    except otp_throttle.OtpThrottled as throttled:
        return _no_store(otp_throttle.throttled_response(throttled, event))
    except otp_throttle.ThrottleStoreUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))

    try:
        issued = otp_challenge.issue(
            _table(), purpose=PURPOSE, subject=email, pepper=_pepper())
    except otp_challenge.ResendTooSoon as soon:
        return _no_store(cors_response(
            429, {"error": "RESEND_TOO_SOON",
                  "retryAfterSeconds": soon.retry_after_seconds}, origin))
    except otp_challenge.ResendLimitReached:
        # Deliberately not distinguished from success in the customer-visible shape beyond the
        # error code: it does not reveal whether the address exists, only that too many codes were
        # requested for it in the window.
        return _no_store(cors_response(429, {"error": "RESEND_LIMIT_REACHED"}, origin))
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))

    try:
        verification_email.send(
            _ses_client(), to_address=email, code=issued.code,
            first_name=first_name, ttl_minutes=max(1, issued.ttl_seconds // 60))
    except verification_email.VerificationEmailFailed:
        # The code was issued but not delivered. Report a soft failure so the client can retry;
        # the issued row simply expires unused. No address or code is logged by the send module.
        return _no_store(cors_response(502, {"error": "SEND_FAILED"}, origin))

    # Public payload carries no code and nothing that identifies the address.
    return _no_store(cors_response(200, {"status": "sent", **issued.as_public_dict()}, origin))


def _verify(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Check a submitted code. Every failure is one opaque outcome; success may stamp a customer."""
    try:
        email = identity.normalize_email(body.get("email"))
    except identity.InvalidEmailAddress:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))

    code = str(body.get("code") or "").strip()
    if not code:
        return _no_store(cors_response(400, {"error": "CODE_REQUIRED"}, origin))

    try:
        result = otp_challenge.verify(
            _table(), purpose=PURPOSE, subject=email, code=code, pepper=_pepper())
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))

    if not result.ok:
        # One shape for every failure, so the endpoint is not an existence oracle. The real
        # outcome stays server-side.
        logger.info(json.dumps({"event": "email_verification_failed",
                                 "outcome": result.outcome}))
        return _no_store(cors_response(400, {"status": result.public_outcome()}, origin))

    # Do not trust a body-supplied customerId on this public endpoint. Verification proves
    # ownership of the EMAIL only. The authenticated profile endpoint consumes this opaque proof
    # and binds it to the signed-in customer's session identity.
    proof = _issue_proof(email)
    logger.info(json.dumps({"event": "email_verified"}))
    return _no_store(cors_response(200, {
        "status": "VERIFIED",
        "proof": proof,
        "expiresInSeconds": PROOF_TTL_SECONDS,
    }, origin))
