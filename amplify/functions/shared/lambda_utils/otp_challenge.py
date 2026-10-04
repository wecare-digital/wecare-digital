"""One-time codes that are never stored in plaintext, and never readable from the table.

What this fixes
---------------
The existing customer WhatsApp OTP is a Cognito `CUSTOM_AUTH` trigger, and it is sound as far
as it goes: `secrets.randbelow` for the code, `secrets.compare_digest` for the comparison, and
the plaintext living only inside Cognito's encrypted session. But Cognito custody brings three
gaps that a checkout flow cannot carry:

- **No server-side record**, so there is nothing to rate-limit or audit against. A registered
  number today has *no* send throttle at all - the only counter in that function sits on the
  `userNotFound` branch and returns before any message is sent.
- **"3 attempts" is really 3 codes.** Cognito re-invokes `CreateAuthChallenge` per challenge,
  so one session sends up to three separate messages, each silently invalidating the last.
- **No resend limit and no cooldown.**

And email verification has no implementation at all, so it needs a store regardless.

This module is that store, and it is deliberately storage-agnostic: the table and the pepper are
both injected, so it holds no AWS client, reads no credential, and is fully testable without
network access.

Nothing plaintext reaches the table
-----------------------------------
Two values are hashed, not one.

The **code** is stored as `HMAC-SHA256(pepper, purpose|subject|code)`. A hash alone would not be
enough: a six-digit code has a million possibilities, so an unsalted digest is brute-forceable in
milliseconds. The pepper lives in Secrets Manager and never in the table, so a read of the table
does not yield the codes even offline.

The **subject** - an email address or a phone number - is hashed into the key as well, so the
table holds no plaintext contact detail at rest. That loses the ability to list challenges by
email, which is the correct thing to lose: nothing legitimate needs it, and a support tool that
could would be a lookup oracle.

Because the pepper participates in the key, rotating it invalidates every outstanding challenge.
That is the right behaviour - a customer re-requests a code - and it is why the pepper must be
read lazily per request rather than at import: a module-scope read is cached for the life of the
execution environment, so a rotation would not take effect until every warm sandbox recycled.

Never log anything derived from the pepper
-----------------------------------------
Not the pepper, not a hash, not a boolean about one. CodeQL's
`py/clear-text-logging-sensitive-data` tracks taint across function boundaries and has already
failed this repository's build twice over a ternary on a secret's truthiness - reducing a secret
to a bool does not launder it. Every log line here carries only counts, outcomes and timestamps.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from hashlib import sha256
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Six digits. Short enough to read off a phone and retype, long enough that the attempt limit
#: is what stops guessing rather than the keyspace.
CODE_DIGITS = 6

DEFAULT_TTL_SECONDS = 600          # 10 minutes, matching the WhatsApp OTP already in production
DEFAULT_MAX_ATTEMPTS = 5           # verification attempts against ONE code
DEFAULT_MAX_SENDS = 5              # codes issued per subject per window
DEFAULT_RESEND_COOLDOWN = 60       # seconds between sends
DEFAULT_SEND_WINDOW = 3600         # the window MAX_SENDS applies over

#: Namespace so this can share a table with other short-lived rows without colliding.
KEY_PREFIX = "otp#"

# ── outcomes ───────────────────────────────────────────────────────────────────
VERIFIED = "VERIFIED"
CODE_INCORRECT = "CODE_INCORRECT"
NO_CHALLENGE = "NO_CHALLENGE"
EXPIRED = "EXPIRED"
ALREADY_USED = "ALREADY_USED"
ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"

#: Outcomes a caller must NOT distinguish in an HTTP response. Telling them apart turns the
#: endpoint into an oracle: "no challenge" reveals that an address was never enrolled, and
#: "already used" reveals that it was. The public answer is one string for all of them.
_INDISTINGUISHABLE = frozenset({
    CODE_INCORRECT, NO_CHALLENGE, EXPIRED, ALREADY_USED, ATTEMPTS_EXHAUSTED,
})


class OtpStorageUnavailable(RuntimeError):
    """The challenge store could not be reached.

    Raised rather than returning a failure, so a storage outage can never be mistaken for a
    wrong code - which would burn a customer's attempt budget for our problem.
    """


class ResendTooSoon(RuntimeError):
    """A code was requested inside the cooldown window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"retry in {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class ResendLimitReached(RuntimeError):
    """Too many codes have been issued to this subject in the window."""


def generate_code(digits: int = CODE_DIGITS) -> str:
    """A uniformly random numeric code.

    `secrets.randbelow` over the exact range, not `randint` on each digit and not
    `secrets.choice` in a loop: this is one draw with no modulo bias, and it cannot accidentally
    produce a code shorter than `digits` when the leading draw is zero.
    """
    if digits < 4:
        raise ValueError("a code shorter than 4 digits is not defensible")
    upper = 10 ** digits
    lower = 10 ** (digits - 1)
    return str(secrets.randbelow(upper - lower) + lower)


def _digest(pepper: str, *parts: str) -> str:
    """Keyed HMAC over the joined parts. The separator cannot occur in any part.

    `\\x1f` (unit separator) rather than `:` or `|`, because an email local part may legitimately
    contain either, and a separator that can appear inside a field lets two different inputs
    produce one digest.
    """
    if not pepper:
        # Not a warning-and-continue. Without the pepper the stored digest is an unsalted hash
        # of a six-digit code, which is trivially reversible.
        raise ValueError("an OTP pepper is required; refusing to hash without one")
    message = "\x1f".join(parts).encode("utf-8")
    return hmac.new(pepper.encode("utf-8"), message, sha256).hexdigest()


#: Service errors that mean "this request is malformed and every retry will fail identically".
#: Deliberately short: a transient fault must still become `OtpStorageUnavailable` so a storage
#: outage never burns a customer's attempt budget. Only a permanent *request* fault belongs here.
_PERMANENT_REQUEST_ERRORS = frozenset({
    "ValidationException",      # a bad expression - e.g. an unaliased reserved word
    "SerializationException",   # a value DynamoDB cannot read at all
})


def _error_code(error: Any) -> str:
    """The DynamoDB error code on a botocore `ClientError`, or `""` for anything else."""
    return str((getattr(error, "response", None) or {}).get("Error", {}).get("Code") or "")


def _is_permanent_request_error(error: Any) -> bool:
    """Whether this error is our bug rather than the store's weather.

    Kept separate from the transient path because the two need opposite handling: a transient
    fault must be reported as `OtpStorageUnavailable` (503, retry), while a permanent one must
    SURFACE. Disguising a permanent coding error as "temporarily unavailable" is what let the
    reserved-keyword defect in `verify`'s consume step run for two days with no log line.
    """
    return _error_code(error) in _PERMANENT_REQUEST_ERRORS


def challenge_key(pepper: str, purpose: str, subject: str) -> str:
    """The table key for one (purpose, subject) pair. Contains no plaintext subject."""
    if not purpose or not subject:
        raise ValueError("purpose and subject are required")
    return KEY_PREFIX + _digest(pepper, "subject", purpose, subject)[:40]


class IssuedChallenge:
    """The result of issuing a code. The code is here and nowhere else."""

    __slots__ = ("code", "expires_at", "send_count", "ttl_seconds")

    def __init__(self, code: str, expires_at: int, send_count: int,
                 ttl_seconds: int) -> None:
        self.code = code
        self.expires_at = expires_at
        self.send_count = send_count
        self.ttl_seconds = ttl_seconds

    def as_public_dict(self) -> Dict[str, Any]:
        """What may be returned to a client. Deliberately excludes the code."""
        return {
            "expiresInSeconds": self.ttl_seconds,
            "expiresAt": self.expires_at,
        }


class VerificationResult:
    """The outcome of checking a code.

    `outcome` is for the server - logs, metrics, rate limiting. `public_outcome()` is what may
    cross the wire, and it collapses every failure into one value so the endpoint cannot be used
    to discover which addresses have pending challenges.
    """

    __slots__ = ("outcome", "attempts_remaining")

    def __init__(self, outcome: str, attempts_remaining: int = 0) -> None:
        self.outcome = outcome
        self.attempts_remaining = max(0, attempts_remaining)

    @property
    def ok(self) -> bool:
        return self.outcome == VERIFIED

    def __bool__(self) -> bool:
        return self.ok

    def public_outcome(self) -> str:
        return VERIFIED if self.ok else "INVALID_OR_EXPIRED"

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"VerificationResult({self.outcome})"


def issue(table: Any, *,
          purpose: str,
          subject: str,
          pepper: str,
          now: Optional[int] = None,
          ttl_seconds: int = DEFAULT_TTL_SECONDS,
          max_attempts: int = DEFAULT_MAX_ATTEMPTS,
          max_sends: int = DEFAULT_MAX_SENDS,
          resend_cooldown: int = DEFAULT_RESEND_COOLDOWN,
          send_window: int = DEFAULT_SEND_WINDOW,
          key_attr: str = "grantId") -> IssuedChallenge:
    """Mint a code, store only its digest, and return the plaintext to the caller once.

    The returned code exists in memory and in the message about to be sent. It is never written
    to the table, never logged, and cannot be recovered afterwards - a lost code means
    requesting another, which is the correct trade.

    Raises `ResendTooSoon` or `ResendLimitReached` rather than silently issuing, so the caller
    can tell the customer when to try again. Note the ordering: both limits are enforced
    **before** a new code replaces the old one, so an attacker cannot use resends to reset
    somebody else's attempt budget.
    """
    moment = int(time.time()) if now is None else int(now)
    key = challenge_key(pepper, purpose, subject)

    try:
        existing = table.get_item(Key={key_attr: key}).get("Item") or {}
    except Exception as error:  # noqa: BLE001
        raise OtpStorageUnavailable(
            f"could not read the challenge store: {type(error).__name__}"
        ) from error

    send_count = int(existing.get("sendCount") or 0)
    window_started = int(existing.get("windowStartedAt") or moment)
    last_sent = int(existing.get("lastSentAt") or 0)

    # A window that has rolled over resets the count. Without this the fifth code of the day
    # would lock a legitimate customer out permanently.
    if moment - window_started >= send_window:
        send_count = 0
        window_started = moment

    if last_sent and moment - last_sent < resend_cooldown:
        raise ResendTooSoon(resend_cooldown - (moment - last_sent))
    if send_count >= max_sends:
        logger.warning('{"event":"otp_resend_limit_reached","purpose":"%s","sendCount":%d}',
                       purpose, send_count)
        raise ResendLimitReached(
            f"{send_count} codes already issued in the current window"
        )

    code = generate_code()
    expires_at = moment + ttl_seconds

    item = {
        key_attr: key,
        "purpose": purpose,
        # HMAC over purpose and subject as well as the code, so a digest captured for one
        # purpose cannot be replayed against another.
        "codeDigest": _digest(pepper, "code", purpose, subject, code),
        "attempts": 0,
        "maxAttempts": max_attempts,
        "sendCount": send_count + 1,
        "windowStartedAt": window_started,
        "lastSentAt": moment,
        "createdAt": moment,
        "expiresAtEpoch": expires_at,
        # The table's TTL attribute. Set past the code's own expiry so an expired-but-unexpired
        # row still carries its send counters - otherwise TTL would delete the rate-limit state
        # along with the challenge and hand an attacker a fresh budget.
        "expiresAt": window_started + send_window + ttl_seconds,
        "consumed": False,
    }

    try:
        table.put_item(Item=item)
    except Exception as error:  # noqa: BLE001
        raise OtpStorageUnavailable(
            f"could not store the challenge: {type(error).__name__}"
        ) from error

    logger.info('{"event":"otp_issued","purpose":"%s","sendCount":%d,"ttlSeconds":%d}',
                purpose, send_count + 1, ttl_seconds)
    return IssuedChallenge(code, expires_at, send_count + 1, ttl_seconds)


def verify(table: Any, *,
           purpose: str,
           subject: str,
           code: str,
           pepper: str,
           now: Optional[int] = None,
           key_attr: str = "grantId") -> VerificationResult:
    """Check a code, consume it on success, and count the attempt on failure.

    Single use is enforced by a conditional update rather than a read-then-write, so two
    simultaneous submissions of a correct code cannot both succeed - which matters because
    success is what marks an email or a phone verified.
    """
    moment = int(time.time()) if now is None else int(now)
    key = challenge_key(pepper, purpose, subject)

    try:
        item = table.get_item(Key={key_attr: key}).get("Item")
    except Exception as error:  # noqa: BLE001
        raise OtpStorageUnavailable(
            f"could not read the challenge store: {type(error).__name__}"
        ) from error

    if not item:
        return VerificationResult(NO_CHALLENGE)
    if item.get("consumed"):
        return VerificationResult(ALREADY_USED)

    attempts = int(item.get("attempts") or 0)
    max_attempts = int(item.get("maxAttempts") or DEFAULT_MAX_ATTEMPTS)
    if attempts >= max_attempts:
        return VerificationResult(ATTEMPTS_EXHAUSTED)

    if moment > int(item.get("expiresAtEpoch") or 0):
        return VerificationResult(EXPIRED)

    expected = str(item.get("codeDigest") or "")
    supplied = _digest(pepper, "code", purpose, subject, str(code or ""))

    # Constant-time, and guarded against an empty stored digest comparing equal to an empty
    # computed one. `hmac.compare_digest` is what `secrets.compare_digest` aliases.
    if not expected or not hmac.compare_digest(expected, supplied):
        try:
            table.update_item(
                Key={key_attr: key},
                UpdateExpression="SET attempts = :next, lastAttemptAt = :now",
                ExpressionAttributeValues={":next": attempts + 1, ":now": moment},
            )
        except Exception as error:  # noqa: BLE001
            raise OtpStorageUnavailable(
                f"could not record a failed attempt: {type(error).__name__}"
            ) from error
        logger.info('{"event":"otp_incorrect","purpose":"%s","attempts":%d}',
                    purpose, attempts + 1)
        return VerificationResult(CODE_INCORRECT,
                                  attempts_remaining=max_attempts - (attempts + 1))

    try:
        table.update_item(
            Key={key_attr: key},
            # `consumed` MUST be aliased. It is a DynamoDB reserved word, and an unaliased
            # occurrence makes DynamoDB refuse the whole call with `ValidationException` - so
            # only a CORRECT code failed, because the wrong-code branch above happens to name
            # no reserved word. That is exactly the shape the live defect took: eight 503s on
            # the one path that was supposed to succeed, with `attempts` stuck at 0.
            #
            # The alias is required on BOTH expressions. `UpdateExpression` is validated first,
            # so aliasing only the condition still fails.
            UpdateExpression="SET #consumed = :true, consumedAt = :now",
            ConditionExpression="#consumed = :false",
            ExpressionAttributeNames={"#consumed": "consumed"},
            ExpressionAttributeValues={":true": True, ":false": False, ":now": moment},
        )
    except Exception as error:  # noqa: BLE001
        # A lost conditional race means a concurrent request consumed it first. That request
        # succeeded, this one must not - exactly one verification per code.
        if _error_code(error) == "ConditionalCheckFailedException":
            return VerificationResult(ALREADY_USED)
        if _is_permanent_request_error(error):
            # A malformed expression is a coding error, not an outage, and it will fail
            # identically on every retry. Reporting it as `OtpStorageUnavailable` produced a
            # 503 "temporarily unavailable" that logged nothing, which is what hid the reserved
            # keyword above for two days. Let it escape: the handler's own arm answers 500 and
            # records the exception type.
            raise
        raise OtpStorageUnavailable(
            f"could not consume the challenge: {type(error).__name__}"
        ) from error

    logger.info('{"event":"otp_verified","purpose":"%s"}', purpose)
    return VerificationResult(VERIFIED)


def is_indistinguishable(outcome: str) -> bool:
    """True for outcomes an HTTP response must not tell apart."""
    return outcome in _INDISTINGUISHABLE


__all__ = [
    "CODE_DIGITS",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_SENDS",
    "DEFAULT_RESEND_COOLDOWN",
    "DEFAULT_SEND_WINDOW",
    "KEY_PREFIX",
    "VERIFIED",
    "CODE_INCORRECT",
    "NO_CHALLENGE",
    "EXPIRED",
    "ALREADY_USED",
    "ATTEMPTS_EXHAUSTED",
    "STORAGE_UNAVAILABLE",
    "OtpStorageUnavailable",
    "ResendTooSoon",
    "ResendLimitReached",
    "IssuedChallenge",
    "VerificationResult",
    "generate_code",
    "challenge_key",
    "issue",
    "verify",
    "is_indistinguishable",
]
