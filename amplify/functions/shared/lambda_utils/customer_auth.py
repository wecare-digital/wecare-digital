"""Server-side authorisation for a customer session. The only correct way to trust a customer.

Why this must exist in the shared layer
---------------------------------------
Two facts together make every new customer route an IDOR waiting to happen.

**All 359 routes on the HTTP API report `AuthorizationType=NONE`** — measured live. There is no
gateway authorizer, so nothing rejects a request before it reaches a handler, and every check has
to happen in the handler.

**`lambda_utils.middleware.require_auth` is hardcoded to the STAFF pool.** A customer token passed
to it does not fail: `get_user` succeeds against the customer pool, the role lookup finds no staff
group, and the caller falls through to `Viewer`. So the obvious thing to reach for silently grants
a customer read access intended for staff. `secure-files` already discovered this and wrote its own
`_customer_identity` with an explicit issuer pin — but it lives *inside* that function, so every
other route would have to rediscover the same problem.

This module is that helper, promoted to the layer.

The three checks, and why each is load-bearing
----------------------------------------------
1. **The token is valid** — `GetUser` against Cognito. Proves it is live and unrevoked.
2. **The issuer is the CUSTOMER pool.** Step 1 alone does not do this: `GetUser` is called with
   only a token, and a *staff* token is also valid. Without the pin, a staff Viewer token would
   authorise as whichever customer the request claimed to be.
3. **The requested resource belongs to this customer.** Shape is not authorisation. A
   well-formed `CUS_...` from a request body proves only that the caller can type.

Never authorise on an identifier from the request
-------------------------------------------------
Not `customerId`, not `orderNumber`, not `paymentAttemptId`, not a receipt id. Those are all
things a customer legitimately knows about *their own* records and can therefore guess or
enumerate about somebody else's. Authority comes from the token, and the request identifier is
then checked against it — which is what `authorize_resource` is for.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: The customer pool. Deliberately NOT the staff pool `us-east-1_cSx0RHCIR`; keeping the two
#: apart is the whole point, and a single env var holding "the pool" is how they get confused.
CUSTOMER_POOL_ID = os.environ.get("CUSTOMER_POOL_ID", "us-east-1_46ULYuukt")
CUSTOMER_POOL_REGION = os.environ.get("AWS_REGION", "us-east-1")

#: The `iss` claim a customer token must carry.
CUSTOMER_POOL_ISSUER = (
    f"https://cognito-idp.{CUSTOMER_POOL_REGION}.amazonaws.com/{CUSTOMER_POOL_ID}"
)

_cognito = None


def _client():
    """Lazily built, so importing this module needs no AWS configuration."""
    global _cognito
    if _cognito is None:
        import boto3
        _cognito = boto3.client("cognito-idp", region_name=CUSTOMER_POOL_REGION)
    return _cognito


class CustomerNotAuthenticated(PermissionError):
    """No usable customer session on the request."""


class CustomerNotAuthorized(PermissionError):
    """Authenticated, but not for the resource requested.

    A distinct type from `CustomerNotAuthenticated` because the two must produce the same HTTP
    response body while being distinguishable in logs and metrics: a spike in this one is
    somebody probing other customers' records, and a spike in the other is a broken client.
    """


class CustomerIdentity:
    """A proven customer session.

    `phone_verified` is Cognito's `phone_number_verified` flag, carried because one caller needs
    to know it rather than assume it: `auth/customer-profile` links a WhatsApp-first contact to
    this session on the strength of the phone alone, and a number the pool has not confirmed is
    not proof of anything. It defaults to **False** so a construction site that has not proven
    the flag cannot accidentally assert it — the ten test stubs and the checkout path that
    rebuilds an identity from a stored payment attempt all land on that default.
    """

    __slots__ = ("customer_id", "phone", "subject", "phone_verified")

    def __init__(self, *, customer_id: str, phone: str, subject: str,
                 phone_verified: bool = False) -> None:
        self.customer_id = customer_id
        self.phone = phone
        self.subject = subject
        self.phone_verified = bool(phone_verified)

    def owns(self, customer_id: Optional[str]) -> bool:
        """Whether this session may act for `customer_id`. Exact match only."""
        return bool(customer_id) and customer_id == self.customer_id

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        # Never renders the phone number or the customer id: this lands in logs.
        return f"CustomerIdentity(subject=***{self.subject[-4:] if self.subject else ''})"


def bearer_token(event: Dict[str, Any]) -> str:
    """The bearer token from an API Gateway event, or ''.

    Header lookup is case-insensitive because HTTP headers are, and API Gateway v1 and v2 do not
    agree on casing — v2 lowercases, v1 preserves what the client sent. A case-sensitive read
    works in one and silently fails in the other.
    """
    headers = event.get("headers") or {}
    lowered = {str(k).lower(): v for k, v in headers.items()}
    raw = str(lowered.get("authorization") or "")
    if not raw:
        return ""
    parts = raw.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    # A bare token with no scheme. Accepted because clients get this wrong constantly and the
    # token is verified against Cognito either way, so leniency here costs nothing.
    return raw.strip()


def _unverified_issuer(token: str) -> str:
    """The `iss` claim, read WITHOUT signature verification.

    Safe only because it is used to *reject*, never to accept: the token has already been proven
    live by `GetUser`, and this narrows which pool proved it. Reading an unverified claim to
    grant anything would be the classic JWT mistake.
    """
    import base64
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("iss") or "")
    except Exception:  # noqa: BLE001 - a malformed token simply has no issuer
        return ""


#: A Cognito `sub` is a canonical lowercase UUID. The single copy of this pattern in the tree:
#: every `Filter='sub = "' + value + '"'` call site reads it through `is_cognito_subject` below.
_COGNITO_SUBJECT_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def is_cognito_subject(value: Any) -> bool:
    """Whether `value` is a well-formed Cognito `sub`: a canonical lowercase UUID.

    EXISTS TO REFUSE MALFORMED FILTER INPUTS BEFORE `ListUsers`. Every caller builds a
    `ListUsers` filter by concatenation — `Filter='sub = "' + value + '"'` — and the value comes
    from a stored attribute (`contact['checkoutCustomerId']`, `row['customerId']`) rather than
    from handset input. A poisoned row is therefore the only way a quote reaches the filter, and
    it would break the filter syntax into a `ClientError` rather than disclose anything. That
    makes this defence in depth on an identity path, which is where an inconsistency should not
    be left: the predicate lives here once so that no call site carries its own copy.

    Uppercase is deliberately refused. Cognito mints `sub` lowercase, so an uppercase value is
    not a subject this pool issued and is not worth a `ListUsers` call.
    """
    return isinstance(value, str) and bool(_COGNITO_SUBJECT_RE.fullmatch(value))


def customer_id_from_attributes(attributes: Dict[str, Any]) -> str:
    """The customer id for a proven session: the Cognito `sub`, and nothing else.

    WHY THIS FUNCTION EXISTS AT ALL. It replaces a read of `custom:customer_id`, which was an
    outage rather than a design: **that attribute does not exist in this pool's schema and never
    has.** Measured against `us-east-1_46ULYuukt` on 2026-10-02 — the only custom attribute in
    the schema is `custom:partner_waba_id`, and the pool's one user carries `phone_number`,
    `phone_number_verified`, `name`, `custom:partner_waba_id` and `sub`. A Cognito attribute
    that is not in the schema cannot be set on a user, so the old read returned '' for every
    token ever issued, `authenticate` raised for 100% of customers, and every route behind it
    answered 401. `stack-wecare-digital-CustomerSessionsTable` holding 0 items is the
    corroborating measurement: the session exchange had never once succeeded.

    WHY `sub`, AND NOT THE ALTERNATIVES.
      - Adding the pool attribute is possible (`AddCustomAttributes` exists) but it is an
        irreversible pool-schema mutation, so it is owner work, and it would still need a
        backfill plus a stamp on every new user.
      - `stack-wecare-digital-CustomersTable` would be the natural authority, but it **does not
        exist** in the account and nothing in the repo creates it.
      - `sub` is the strongest authority already inside the token: Cognito-assigned, immutable,
        pool-scoped, present on every user, and not writable by the app client. It is already
        the field this pair is trusted on for refresh-owner identity, which compares
        `proven.subject != identity.subject`.

    WHY A SINGLE AUTHORITY AND NOT A FALLBACK. "custom attribute if present, else `sub`" would
    silently re-key a customer the day somebody adds and backfills the attribute, orphaning the
    orders filed under their old id. One rule, so that cannot happen.

    NOTHING TO MIGRATE, MEASURED RATHER THAN ASSUMED. On 2026-10-02 every table that could hold
    a customer-keyed row was empty: CustomerSessionsTable 0, OrderTable 0, PaymentAttemptsTable
    0 (it has a `customerId-index`), WixOrderIds 0, WixOrdersCache 0. So this is a clean
    cut-over, not an identity migration.

    THE SHAPE CHANGES, AND THAT IS DELIBERATE. `lambda_utils.identity.customer` defines the
    customer identity concept as `CUS_<ULID>` and `is_customer_id` validates that shape. A
    `sub` is a UUID and does not satisfy it. Neither production caller of `is_customer_id`
    reads a session identity — `email-verification` validates a `customerId` taken from a
    request body and `is_checkout_ready` validates a field of a `CustomersTable` record — so
    nothing gates on the two agreeing today. Manufacturing a `CUS_`-shaped value from the `sub`
    was rejected on purpose: it would pass `is_customer_id` while not being a real issued
    identity, which is a worse failure than an honest shape mismatch.
    """
    return str(attributes.get("sub") or "")


def authenticate(event: Dict[str, Any]) -> CustomerIdentity:
    """Prove a customer session from the request, or raise `CustomerNotAuthenticated`.

    Order matters. `GetUser` runs first because it is the only step that proves the token is live
    and unrevoked; the issuer pin runs second to establish *which* pool vouched for it. Reversing
    them would let an expired customer token past the pin and into the handler.
    """
    token = bearer_token(event)
    if not token:
        raise CustomerNotAuthenticated("no bearer token on the request")

    try:
        user = _client().get_user(AccessToken=token)
    except Exception as error:  # noqa: BLE001
        # Type only. A Cognito error message can echo the token back.
        logger.info(
            '{"event":"customer_auth_rejected","reason":"%s"}', type(error).__name__
        )
        raise CustomerNotAuthenticated("token is not valid") from error

    issuer = _unverified_issuer(token)
    if issuer != CUSTOMER_POOL_ISSUER:
        # The check `require_auth` does not make. A staff token is *valid*, so without this it
        # would authorise as whichever customer the request named.
        logger.warning('{"event":"customer_auth_wrong_pool"}')
        raise CustomerNotAuthenticated("token was not issued by the customer pool")

    attributes = {a.get("Name"): a.get("Value")
                  for a in (user.get("UserAttributes") or [])}
    customer_id = customer_id_from_attributes(attributes)
    phone = str(attributes.get("phone_number") or user.get("Username") or "")

    if not customer_id:
        # Unreachable for a token Cognito issued: `sub` is assigned at user creation and is
        # always returned by `GetUser`. Kept as a fail-closed guard, because the alternative is
        # authorising a session with no owner key at all — every downstream row is filed under
        # this value. The warning name is unchanged on purpose so the existing CloudWatch
        # evidence of the outage stays searchable.
        logger.warning('{"event":"customer_auth_no_customer_id"}')
        raise CustomerNotAuthenticated("session carries no customer id")

    return CustomerIdentity(
        customer_id=customer_id, phone=phone,
        subject=str(attributes.get("sub") or ""),
        # Cognito renders the flag as the STRING 'true'. Compared explicitly rather than
        # truthiness-tested, because the string 'false' is truthy.
        phone_verified=attributes.get("phone_number_verified") == "true",
    )


def authorize_resource(identity: CustomerIdentity,
                       resource: Optional[Dict[str, Any]],
                       *, owner_field: str = "customerId") -> Dict[str, Any]:
    """Return `resource` if this session owns it, else raise `CustomerNotAuthorized`.

    A missing resource and a resource belonging to somebody else raise the *same* exception, so
    the caller cannot accidentally turn the endpoint into an existence oracle — "not found" and
    "not yours" must be indistinguishable to the client, or an attacker can enumerate which
    order numbers are real.
    """
    if not resource:
        raise CustomerNotAuthorized("resource does not exist or is not yours")
    if not identity.owns(str(resource.get(owner_field) or "")):
        logger.warning('{"event":"customer_idor_attempt","ownerField":"%s"}', owner_field)
        raise CustomerNotAuthorized("resource does not exist or is not yours")
    return dict(resource)


def require_customer(event: Dict[str, Any]) -> Tuple[Optional[CustomerIdentity],
                                                     Optional[Dict[str, Any]]]:
    """`(identity, None)` when authorised, `(None, response)` when not.

    Mirrors `middleware.require_auth`'s shape so a handler reads the same either way::

        identity, denied = customer_auth.require_customer(event)
        if denied:
            return denied

    Both failure modes return **401 with an identical body**. Not 403 for authorisation: a 403
    confirms the resource exists, and the whole point of `authorize_resource` collapsing the two
    cases is that it should not.
    """
    from lambda_utils.response import cors_response, extract_origin

    origin = extract_origin(event)
    try:
        return authenticate(event), None
    except CustomerNotAuthenticated:
        return None, cors_response(
            401, {"error": "VERIFICATION_REQUIRED",
                  "message": "Please verify your WhatsApp number to continue."}, origin)


def denied_response(event: Dict[str, Any]) -> Dict[str, Any]:
    """The 401 to return for a `CustomerNotAuthorized`, identical to the unauthenticated one."""
    from lambda_utils.response import cors_response, extract_origin
    return cors_response(
        401, {"error": "VERIFICATION_REQUIRED",
              "message": "Please verify your WhatsApp number to continue."},
        extract_origin(event))


__all__ = [
    "CUSTOMER_POOL_ID",
    "CUSTOMER_POOL_ISSUER",
    "CustomerNotAuthenticated",
    "CustomerNotAuthorized",
    "CustomerIdentity",
    "bearer_token",
    "is_cognito_subject",
    "customer_id_from_attributes",
    "authenticate",
    "authorize_resource",
    "require_customer",
    "denied_response",
]
