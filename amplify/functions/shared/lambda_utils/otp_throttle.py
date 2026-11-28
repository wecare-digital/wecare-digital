"""Per-IP and per-phone throttling for the OTP front door, because the trigger cannot do it.

Why this cannot live in the Cognito trigger
-------------------------------------------
`customer-whatsapp-auth` is a `CUSTOM_AUTH` trigger, and **a Cognito trigger event carries no
client IP**. The function's own comment says so, and it is correct — there is no field to read. So
per-IP limiting is structurally impossible there, and the existing per-phone counter only runs on
the `userNotFound` branch, which means a **registered** number has no send limit at all: a caller
can loop `InitiateAuth` and drive unbounded WhatsApp messages to a real handset.

Both web ACLs were deleted on 2026-09-28, so nothing in front of the pool filters by IP either.

The answer is an HTTP front door that sees `requestContext.http.sourceIp` and throttles before it
ever reaches Cognito. That is this module.

Two axes, because either alone is bypassable
--------------------------------------------
- **Per phone** bounds how fast one number can be targeted. Without it, one victim's handset can
  be flooded from a botnet.
- **Per IP** bounds how many *different* numbers one origin can touch. Without it, an attacker
  spreads across numbers and every per-phone counter stays happily under its limit while
  thousands of messages go out.

Neither is sufficient. Both are cheap.

Fail closed, unlike the primitive next door
-------------------------------------------
`lambda_utils/rate_limit.py` fails **open** on error, which is right for a throughput guard: a
DynamoDB blip should not stop legitimate traffic. It is wrong here. This limiter's whole purpose is
to bound a path that spends real money and reaches a real person's phone, so an unreadable counter
means "refuse", not "allow". That is the single most important difference between the two modules,
and the reason this is not just a call into that one.

Rate-limit state must outlive the thing it protects
---------------------------------------------------
The TTL is set from the window, not from the request. If the row expired with the challenge, an
attacker would get a fresh budget every time a code expired, which is precisely the opposite of a
limit.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import time
from typing import Any, Dict, Optional, Tuple

from lambda_utils import client_ip

logger = logging.getLogger(__name__)

#: Namespaces so both axes can share one table without colliding.
PHONE_PREFIX = "otpphone#"
IP_PREFIX = "otpip#"

#: One code a minute per number is generous for a human and useless for a flood.
DEFAULT_PHONE_MAX = 5
DEFAULT_PHONE_WINDOW = 3600

#: Higher than the phone limit on purpose: a household, an office or a mobile carrier NAT shares
#: one address, so this must not lock out a legitimate second person. It still bounds the spread
#: attack, which needs hundreds of numbers rather than a handful.
DEFAULT_IP_MAX = 20
DEFAULT_IP_WINDOW = 3600


class OtpThrottled(RuntimeError):
    """The request exceeded a limit. Carries the axis for metrics, never for the response."""

    def __init__(self, axis: str, retry_after_seconds: int) -> None:
        super().__init__(f"{axis} limit reached")
        self.axis = axis
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class ThrottleStoreUnavailable(RuntimeError):
    """The counter could not be read or written, so the request is refused."""


def source_ip(event: Dict[str, Any]) -> str:
    """The client IP from an API Gateway event, or ''. See `lambda_utils.client_ip`.

    The connecting peer (`requestContext.http.sourceIp`, then REST `identity.sourceIp`), unless
    that peer is listed in `TRUSTED_PROXY_CIDRS`. Only then is `X-Forwarded-For` read, and only
    its right-most untrusted entry: the client writes the entries to the left, so trusting them
    would let an attacker rotate the value per request and defeat the limit.
    """
    return client_ip.client_ip(event)


def _ip_bucket(raw_ip: str) -> str:
    """The key an IP counts against.

    IPv6 is bucketed to its **/64**, not its full address. A single residential IPv6 allocation is
    typically a /64 or larger, and clients rotate addresses within it freely under privacy
    extensions — so counting full v6 addresses gives an attacker a effectively unlimited supply of
    fresh buckets. IPv4 counts per address, since a /32 is already the smallest unit available.

    An unparseable value returns a marker rather than raising: the caller has already decided to
    throttle, and a malformed IP should count against *something* rather than skip the check.
    """
    if not raw_ip:
        return "unknown"
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return "unparseable"
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
    return str(address)


def _hashed(value: str) -> str:
    """A stable, non-reversible key component.

    Phone numbers and IP addresses are both personal data, and a rate-limit table is a low-value
    target that nobody thinks to guard. Hashing means a dump of it reveals no numbers. There is no
    pepper because this is not a secret to be guessed — it is a counter key, and an attacker who
    already knows the number learns nothing from confirming its hash.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _consume(table: Any, key: str, *, max_count: int, window: int,
             axis: str, now: int, key_attr: str) -> int:
    """Increment one counter and raise if it is over budget. Returns the new count."""
    try:
        result = table.update_item(
            Key={key_attr: key},
            UpdateExpression=(
                "ADD attempts :one "
                "SET windowStartedAt = if_not_exists(windowStartedAt, :now), "
                "expiresAt = if_not_exists(expiresAt, :exp)"
            ),
            ExpressionAttributeValues={":one": 1, ":now": now, ":exp": now + window},
            ReturnValues="ALL_NEW",
        )
    except Exception as error:  # noqa: BLE001
        # Fail CLOSED. See the module docstring: this guards a path that sends messages and
        # spends money, so an unreadable counter must refuse.
        raise ThrottleStoreUnavailable(
            f"could not record the {axis} attempt: {type(error).__name__}"
        ) from error

    attributes = result.get("Attributes") or {}
    count = int(attributes.get("attempts") or 0)
    started = int(attributes.get("windowStartedAt") or now)

    # A window that has rolled over resets. Handled by writing a fresh row rather than trusting
    # TTL, because TTL deletion is best-effort and can lag by hours — long enough to lock out a
    # legitimate customer for the rest of the day.
    if now - started >= window:
        try:
            table.put_item(Item={
                key_attr: key, "attempts": 1,
                "windowStartedAt": now, "expiresAt": now + window,
            })
        except Exception as error:  # noqa: BLE001
            raise ThrottleStoreUnavailable(
                f"could not roll the {axis} window: {type(error).__name__}"
            ) from error
        return 1

    if count > max_count:
        retry_after = max(1, (started + window) - now)
        logger.warning(
            '{"event":"otp_throttled","axis":"%s","count":%d,"max":%d}',
            axis, count, max_count,
        )
        raise OtpThrottled(axis, retry_after)
    return count


def check_and_consume(table: Any, *,
                      phone_e164: str,
                      event: Optional[Dict[str, Any]] = None,
                      ip: Optional[str] = None,
                      now: Optional[int] = None,
                      phone_max: int = DEFAULT_PHONE_MAX,
                      phone_window: int = DEFAULT_PHONE_WINDOW,
                      ip_max: int = DEFAULT_IP_MAX,
                      ip_window: int = DEFAULT_IP_WINDOW,
                      key_attr: str = "grantId") -> Tuple[int, int]:
    """Consume one unit on both axes. Returns `(phone_count, ip_count)`.

    Raises `OtpThrottled` on the first axis over budget, or `ThrottleStoreUnavailable` if a
    counter could not be written.

    **Phone is checked first, deliberately.** It is the axis that protects a *person* — the human
    whose handset would ring — whereas the IP axis protects our sending reputation and cost. When
    both are over, the phone limit is the one worth reporting.
    """
    if not phone_e164:
        raise ValueError("phone_e164 is required")

    moment = int(time.time()) if now is None else int(now)
    resolved_ip = ip if ip is not None else source_ip(event or {})

    phone_count = _consume(
        table, PHONE_PREFIX + _hashed(phone_e164),
        max_count=phone_max, window=phone_window, axis="phone",
        now=moment, key_attr=key_attr,
    )
    ip_count = _consume(
        table, IP_PREFIX + _hashed(_ip_bucket(resolved_ip)),
        max_count=ip_max, window=ip_window, axis="ip",
        now=moment, key_attr=key_attr,
    )
    return phone_count, ip_count


def throttled_response(error: OtpThrottled, event: Dict[str, Any]) -> Dict[str, Any]:
    """The 429 to return. Says nothing about which axis tripped.

    Naming the axis would tell an attacker whether they are being limited per number or per
    address, which is exactly the information needed to pick the cheaper way around. The customer
    gets one message and a retry hint either way.
    """
    from lambda_utils.response import cors_response, extract_origin
    return cors_response(
        429,
        {
            "error": "TOO_MANY_REQUESTS",
            "message": "Too many verification attempts. Please try again shortly.",
            "retryAfterSeconds": error.retry_after_seconds,
        },
        extract_origin(event),
    )


__all__ = [
    "PHONE_PREFIX",
    "IP_PREFIX",
    "DEFAULT_PHONE_MAX",
    "DEFAULT_PHONE_WINDOW",
    "DEFAULT_IP_MAX",
    "DEFAULT_IP_WINDOW",
    "OtpThrottled",
    "ThrottleStoreUnavailable",
    "source_ip",
    "check_and_consume",
    "throttled_response",
]
