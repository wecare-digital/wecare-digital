"""The registration front door: the only way a walk-up customer comes into existence.

Why a front door is necessary rather than convenient
----------------------------------------------------
The customer Cognito pool is `AllowAdminCreateUserOnly = true`, measured live, and the trigger's
own docstring says why: *customer users are provisioned administratively; public self-sign-up stays
off.* That is deliberate architecture, not a gap. So a checkout customer cannot simply call
`InitiateAuth` and appear — there is nothing to authenticate against until somebody creates them.

The wrong fix is to open self-signup. `SignUp` from a browser lets anyone mint pool users at will,
which is an unauthenticated write to the identity store that everything else trusts.

The right fix is this: an HTTP route that proves the phone by OTP **first**, then provisions the
Cognito user administratively from the backend. The browser never creates anything; it proves
something, and the backend decides what that entitles it to.

Two things only this layer can do
---------------------------------
**It can see the client IP.** A Cognito trigger event carries none — the trigger's comment says so
and it is correct — so per-IP throttling is structurally impossible there. Here
`requestContext.http.sourceIp` exists and cannot be spoofed. With both web ACLs deleted on
2026-09-28, this route is the only place per-IP limiting can live at all.

**It can refuse to leak.** The existing trigger deliberately returns `registered: true/false` as a
considered trade: every recipient is hand-provisioned, so "this number is a customer" is a
low-value disclosure, and hiding it stranded mistyped numbers on a code screen forever. **That
trade does not survive contact with a public checkout.** Once anyone can reach this endpoint,
whether a number is a customer becomes a real secret, and the usability problem it solved is gone
anyway — a walk-up customer who mistypes a digit gets a code at the number they actually typed,
because we create it. So this layer answers identically either way.

Ordering, and why the throttle comes before everything
------------------------------------------------------
Normalise, throttle, *then* send. The throttle is the only step that costs nothing and prevents
something expensive: a WhatsApp message is billable and lands on a real person's handset. Placing
it after the send, or after a customer lookup, means the flood has already happened by the time the
counter notices.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from lambda_utils import otp_challenge, otp_throttle
from lambda_utils.identity import customer as customer_identity

logger = logging.getLogger(__name__)

#: The purpose string the OTP challenge is bound to. Distinct from any email purpose so a code
#: issued for one cannot be replayed against the other.
PHONE_PURPOSE = "customer_phone_registration"

# ── outcomes ───────────────────────────────────────────────────────────────────
CHALLENGE_SENT = "CHALLENGE_SENT"
INVALID_PHONE = "INVALID_PHONE"
THROTTLED = "THROTTLED"
SEND_FAILED = "SEND_FAILED"
STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

VERIFIED = "VERIFIED"
CODE_REJECTED = "CODE_REJECTED"
PROVISION_FAILED = "PROVISION_FAILED"


class RegistrationResult:
    """The outcome of a registration step.

    `public_body()` is what may cross the wire. It deliberately never says whether the number was
    already known, and never distinguishes a wrong code from an expired one from one that was never
    issued — see the module docstring for why that trade changed.
    """

    __slots__ = ("outcome", "reason", "customer_id", "expires_in_seconds",
                 "retry_after_seconds", "created")

    def __init__(self, outcome: str, reason: str = "", *,
                 customer_id: str = "", expires_in_seconds: int = 0,
                 retry_after_seconds: int = 0, created: bool = False) -> None:
        self.outcome = outcome
        self.reason = reason
        self.customer_id = customer_id
        self.expires_in_seconds = expires_in_seconds
        self.retry_after_seconds = retry_after_seconds
        self.created = created

    @property
    def ok(self) -> bool:
        return self.outcome in (CHALLENGE_SENT, VERIFIED)

    def __bool__(self) -> bool:
        return self.ok

    def public_body(self) -> Dict[str, Any]:
        """The response body. Carries no customer id and no existence signal."""
        if self.outcome == CHALLENGE_SENT:
            return {"status": "code_sent", "expiresInSeconds": self.expires_in_seconds}
        if self.outcome == VERIFIED:
            # The customer id is NOT returned. The session token is the credential; handing the
            # id to the browser invites it to be sent back as an authorisation claim, which
            # `customer_auth` exists to refuse.
            return {"status": "verified"}
        if self.outcome == THROTTLED:
            return {"status": "too_many_requests",
                    "retryAfterSeconds": self.retry_after_seconds}
        if self.outcome == INVALID_PHONE:
            return {"status": "invalid_phone",
                    "message": "Enter a valid mobile number."}
        if self.outcome == CODE_REJECTED:
            # One answer for wrong, expired, already-used and never-issued.
            return {"status": "invalid_code",
                    "message": "That code is not valid. Please request a new one."}
        return {"status": "unavailable",
                "message": "Verification is temporarily unavailable. Please try again shortly."}

    def http_status(self) -> int:
        return {
            CHALLENGE_SENT: 200, VERIFIED: 200,
            INVALID_PHONE: 400, CODE_REJECTED: 401, THROTTLED: 429,
        }.get(self.outcome, 503)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"RegistrationResult({self.outcome})"


def begin(*,
          raw_phone: Any,
          event: Dict[str, Any],
          throttle_table: Any,
          challenge_table: Any,
          pepper: str,
          send_code: Callable[[str, str], None],
          now: Optional[int] = None,
          key_attr: str = "grantId") -> RegistrationResult:
    """Normalise, throttle, issue a code, send it. Creates no customer and no Cognito user.

    `send_code(e164, code)` delivers over WhatsApp. Injected so this module invokes no Lambda and
    holds no Meta credential.

    Nothing about the customer is created here, deliberately. An unverified phone number is a claim,
    and a claim should not produce a record — otherwise an attacker enumerating numbers populates
    the customer table for us.
    """
    try:
        # STRICT, not `normalize_phone`. The lenient function strips every non-digit before it
        # looks for a country code, so a ten-digit foreign E.164 number matches the Indian
        # mobile pattern and `+91` is prepended to an already-complete number: `+6591234567`
        # became `+916591234567`, measured. That would send this OTP to an unrelated Indian
        # handset. `normalize_phone` stays lenient for its other callers, which read
        # already-stored records; this door reads raw browser input, so it refuses to guess a
        # country code at all.
        e164 = customer_identity.normalize_phone_preserving_country(raw_phone)
    except customer_identity.InvalidPhoneNumber as error:
        # Still `InvalidPhoneNumber`: `MissingCountryCode` subclasses it, which is why the
        # strict normaliser needs no new branch here.
        # Refused before the throttle, because a malformed number cannot be counted against
        # anything meaningful and rejecting it costs nothing.
        return RegistrationResult(INVALID_PHONE, str(error))

    try:
        otp_throttle.check_and_consume(
            throttle_table, phone_e164=e164, event=event, now=now, key_attr=key_attr)
    except otp_throttle.OtpThrottled as error:
        return RegistrationResult(THROTTLED, f"{error.axis} limit",
                                  retry_after_seconds=error.retry_after_seconds)
    except otp_throttle.ThrottleStoreUnavailable as error:
        # Fails CLOSED. An unreadable counter means the limit is not being enforced, and this
        # route sends billable messages to real handsets.
        return RegistrationResult(STORE_UNAVAILABLE, str(error))

    try:
        issued = otp_challenge.issue(
            challenge_table, purpose=PHONE_PURPOSE, subject=e164,
            pepper=pepper, now=now, key_attr=key_attr)
    except otp_challenge.ResendTooSoon as error:
        return RegistrationResult(THROTTLED, "cooldown",
                                  retry_after_seconds=error.retry_after_seconds)
    except otp_challenge.ResendLimitReached as error:
        return RegistrationResult(THROTTLED, str(error), retry_after_seconds=60)
    except otp_challenge.OtpStorageUnavailable as error:
        return RegistrationResult(STORE_UNAVAILABLE, str(error))

    try:
        send_code(e164, issued.code)
    except Exception as error:  # noqa: BLE001
        # The challenge is already stored, which is the right order: a stored code with no message
        # is a resend away from working, whereas a sent code with no stored challenge can never be
        # verified. Type only — a provider error can echo the number.
        logger.error('{"event":"registration_send_failed","error":"%s"}',
                     type(error).__name__)
        return RegistrationResult(SEND_FAILED, type(error).__name__)

    # Metadata only. No number, no code.
    logger.info('{"event":"registration_challenge_sent","sendCount":%d}',
                issued.send_count)
    return RegistrationResult(CHALLENGE_SENT, "code sent",
                              expires_in_seconds=issued.ttl_seconds)


def complete(*,
             raw_phone: Any,
             code: str,
             event: Dict[str, Any],
             throttle_table: Any,
             challenge_table: Any,
             pepper: str,
             resolve_customer: Callable[[str], Optional[Dict[str, Any]]],
             create_customer: Callable[[str], Dict[str, Any]],
             provision_login: Callable[[str, str], None],
             now: Optional[int] = None,
             key_attr: str = "grantId") -> RegistrationResult:
    """Verify the code, then resolve or create the customer and provision their login.

    `resolve_customer(e164)` returns an existing customer record or None.
    `create_customer(e164)` creates one with a `CUS_<ULID>` identity and a verified phone.
    `provision_login(e164, customer_id)` administratively creates or updates the Cognito user so
    the phone-keyed login exists and is CONFIRMED. It stamps NO customer id on the user:
    `customer_auth` derives session identity from the Cognito `sub` instead, because
    `custom:customer_id` is not in the customer pool's schema and so could never be set. The
    `customer_id` argument is part of this contract but is no longer written to Cognito.

    All three are injected. This module performs no AWS call, which is what makes the ordering
    below testable at all.

    The order is: throttle, verify, then resolve, then create, then provision. Verification
    first because everything after it writes, and a code is the only thing that proves the
    caller holds the number. The throttle counts submissions per number and per client IP in
    the `verify` buckets, separate from the send budget `begin` uses.
    """
    try:
        # STRICT, and it matters more here than in `begin`: this is where the identity is
        # RESERVED. `normalizedPhone` and the Cognito `Username` are both written from this
        # value, and uniqueness is enforced on it - so the lenient function's `+65 -> +91`
        # corruption would lock the wrong number into the identity store permanently, not
        # merely misdeliver one message. Must match `begin`, or a code issued against one
        # subject could never be verified against the other.
        e164 = customer_identity.normalize_phone_preserving_country(raw_phone)
    except customer_identity.InvalidPhoneNumber as error:
        # `MissingCountryCode` subclasses `InvalidPhoneNumber`, so this clause is unchanged.
        return RegistrationResult(INVALID_PHONE, str(error))

    try:
        otp_throttle.check_verify_attempt(
            throttle_table, subject=e164, event=event, now=now, key_attr=key_attr)
    except otp_throttle.OtpThrottled as error:
        return RegistrationResult(THROTTLED, f"{error.axis} limit",
                                  retry_after_seconds=error.retry_after_seconds)
    except otp_throttle.ThrottleStoreUnavailable as error:
        # Fails CLOSED, like `begin`.
        return RegistrationResult(STORE_UNAVAILABLE, str(error))

    try:
        verdict = otp_challenge.verify(
            challenge_table, purpose=PHONE_PURPOSE, subject=e164,
            code=code, pepper=pepper, now=now, key_attr=key_attr)
    except otp_challenge.OtpStorageUnavailable as error:
        # Raised rather than treated as a wrong code, so an outage does not burn the customer's
        # attempt budget for our problem.
        return RegistrationResult(STORE_UNAVAILABLE, str(error))

    if not verdict.ok:
        # `verdict.outcome` distinguishes wrong / expired / used / never-issued for our metrics;
        # the public body collapses them so the endpoint is not an existence oracle.
        logger.info('{"event":"registration_code_rejected","outcome":"%s"}',
                    verdict.outcome)
        return RegistrationResult(CODE_REJECTED, verdict.outcome)

    try:
        existing = resolve_customer(e164)
        if existing and existing.get("customerId"):
            record, created = existing, False
        else:
            record, created = create_customer(e164), True

        customer_id = str(record.get("customerId") or "")
        if not customer_id:
            raise ValueError("customer record carries no customerId")

        # Runs for an existing customer too, not just a new one. It is idempotent, and it repairs
        # the case the sign-in flow cannot: a customer record with no CONFIRMED Cognito user
        # behind it can never sign in, and that state is invisible until someone tries.
        provision_login(e164, customer_id)
    except Exception as error:  # noqa: BLE001
        logger.error('{"event":"registration_provision_failed","error":"%s"}',
                     type(error).__name__)
        return RegistrationResult(PROVISION_FAILED, type(error).__name__)

    logger.info('{"event":"registration_verified","created":%s}',
                "true" if created else "false")
    return RegistrationResult(VERIFIED, "phone verified",
                              customer_id=customer_id, created=created)


__all__ = [
    "PHONE_PURPOSE",
    "CHALLENGE_SENT",
    "INVALID_PHONE",
    "THROTTLED",
    "SEND_FAILED",
    "STORE_UNAVAILABLE",
    "VERIFIED",
    "CODE_REJECTED",
    "PROVISION_FAILED",
    "RegistrationResult",
    "begin",
    "complete",
]
