"""`wecare-gift-cards` - issuance, the staff view, and a customer balance check. FIVE routes.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md`
sections 5.3 (the code never appears in a URL), 6 (data model), 7.2 (our own routes) and 10.1 (the
scoped role).

| Route | Identity | Purpose |
|---|---|---|
| `POST /gift-cards` | staff | Issue a card. Generates the code and returns it **once**. |
| `GET /gift-cards/{giftCardId}` | staff | By OUR id. Never by code, never a code in the response. |
| `GET /gift-cards` | staff | List by `status`, with the outstanding liability. |
| `POST /gift-cards/{giftCardId}/disable` | staff | `status=DISABLED`. Never deletes. |
| `POST /gift-cards/balance` | customer session | `{code, pin?}` in the BODY. Balance only. |

FIVE ROUTES, NOT SEVEN - AND THE TWO MISSING ONES ARE A DECISION (MEDIUM-5)
---------------------------------------------------------------------------
`POST /gift-cards/hold` and `POST /gift-cards/release` are deliberately absent. A customer session
has no `paymentAttemptId` - our checkout producers mint one, and nothing a browser can reach does -
so a hold taken from a customer route would either have to invent a key or be keyed on something
that is not the claim key. Worse, a hold taken OUTSIDE the request that mints the attempt skips the
`GC_HELD` stage, which leaves `giftCardRequiredPaise` unwritten; `is_fully_settled` then reads
`required == 0` and settles a gift-card order on the Razorpay leg alone. That is the exact failure
DECISION 3 exists to prevent, so the route is not provided rather than provided-and-guarded.

The hold is taken only by the checkout producer, inside the request that mints the attempt
(SEAM-G4 / SEAM-G14). The customer surface here is `POST /gift-cards/balance`, which reserves
nothing.

NO CODE IN A PATH OR A QUERY, EVER
----------------------------------
A bearer value in a URL lands in access logs, in `Referer` headers and in browser history. The
customer route takes `{code, pin?}` in the body; the staff reads take OUR `giftCardId`. Enforced by
SHAPE - no route template accepts a code - and asserted by a route-enumeration test, not by
convention. Wix's own `GiftCard.obfuscatedCode` masks the code on its side too, which is
corroboration rather than our rule.

There is no `DELETE`. A disabled card retains its liability record.

AUTHORIZATION, STATED RATHER THAN READ OFF THE GATEWAY
------------------------------------------------------
All five routes are created with `AuthorizationType=NONE` and no authorizer, because this account
has zero API Gateway authorizers across 361 routes and this change does not introduce the first one.
Authentication is `middleware.require_auth` INSIDE the handler on the four staff routes and a
customer-session resolution on the one customer route, before any table access.
`00-current-owner-overrides.md` records why the gateway field cannot be read as the answer: it
cannot distinguish an intentionally public signed webhook from an accidentally public API.

With WAF removed there is no per-IP layer in front of `POST /gift-cards/balance`, which is the one
route a stranger could grind to discover live codes. So it additionally goes through
`rate_limit.check_rate_limit` per session, and every refusal - malformed code, unknown code, wrong
PIN - answers identically.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from lambda_utils import customer_session as sessions
from lambda_utils import middleware, rate_limit
from lambda_utils.ecommerce import gift_card_store as store
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, error_response, extract_origin, options_response

logger = get_logger(__name__)

#: Secret NAME only. The pepper is read by reference, lazily, inside the request.
SPI_SECRET_ID = store.resolve_pepper_secret_id(os.environ)

GIFT_CARDS_TABLE = os.environ.get(store.TABLE_ENV_KEY, store.DEFAULT_TABLE_NAME)
CUSTOMER_SESSIONS_TABLE = os.environ.get(
    "CUSTOMER_SESSIONS_TABLE", "stack-wecare-digital-CustomerSessionsTable")

#: Grind budget for `POST /gift-cards/balance`, per session per second. WAF is gone, so this is
#: the only layer in front of the one route that takes a code.
BALANCE_RATE_LIMIT_PER_SECOND = 3

#: Issuing a card creates a liability, so it is an operator action.
STAFF_ROLE = "Operator"

#: route key -> (identity, the function that serves it). Declared so the provisioner's route list
#: and this dispatch cannot drift, and so a test can resolve each route to the function whose auth
#: call it has to inspect. FIVE entries - see the module docstring for the two that are absent.
ROUTE_HANDLERS: Dict[str, Tuple[str, str]] = {
    "POST /gift-cards": ("staff", "_create"),
    "GET /gift-cards/{giftCardId}": ("staff", "_get"),
    "GET /gift-cards": ("staff", "_list"),
    "POST /gift-cards/{giftCardId}/disable": ("staff", "_disable"),
    "POST /gift-cards/balance": ("customer", "_balance"),
}

#: Request-body keys a browser may send on the customer route. A code and an optional PIN, and
#: nothing financial - a body carrying `amountPaise` or `balancePaise` is refused outright rather
#: than ignored, so an attempt to supply a balance fails loudly.
CUSTOMER_BODY_FIELDS = ("code", "pin")

#: Accepted on the staff issue payload. An unexpected key is refused rather than dropped, so a
#: misspelled `expiresAtMS` cannot issue a card that never expires.
CREATE_FIELDS = ("initialValuePaise", "pin", "expiresAtMs", "issuedToContactId",
                 "sourceOrderId", "currency")


class Refused(Exception):
    """An input or policy refusal carrying the status and machine code to answer with."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


# ── lazily built collaborators ────────────────────────────────────────────────

def _table(name: str):
    """A DynamoDB table resource, built per request.

    `boto3` is imported here rather than at module scope so the shared modules stay importable with
    no AWS at all, which is what makes the offline tests possible.
    """
    import boto3
    return boto3.resource("dynamodb",
                          region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(name)


def _cards():
    return _table(GIFT_CARDS_TABLE)


def _read_secret(secret_id: str) -> Mapping[str, Any]:
    """Read the SPI secret by id, at request time. No cache, deliberately.

    A module-scope read is frozen into a warm sandbox, so a pepper rotation would not take effect
    until every sandbox recycled. Nothing here logs the result, not even its truthiness.
    """
    import boto3
    client = boto3.client("secretsmanager",
                          region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])


def _pepper() -> str:
    return store.read_pepper(_read_secret, secret_id=SPI_SECRET_ID)


# ── identity ──────────────────────────────────────────────────────────────────

def _staff(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cognito staff authentication. Returns a response to send back, or None to proceed."""
    return middleware.require_auth(event, STAFF_ROLE)


def _customer(event: Dict[str, Any]) -> sessions.SessionView:
    """Resolve the customer session, or refuse.

    The identity comes from the SESSION, never from the request body. An id a browser can set is an
    id an attacker can set, and here it would be the rate-limit subject.
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    cookie = sessions.read_cookie({
        **headers,
        "cookie": "; ".join(event.get("cookies") or []) or headers.get("cookie", "")})
    if not cookie:
        raise Refused(401, "VERIFICATION_REQUIRED")
    try:
        return sessions.validate(_table(CUSTOMER_SESSIONS_TABLE), cookie)
    except sessions.SessionError:
        raise Refused(401, "VERIFICATION_REQUIRED") from None


# ── request parsing ───────────────────────────────────────────────────────────

def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        parsed = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        raise Refused(400, "INVALID_JSON") from None
    if not isinstance(parsed, dict):
        raise Refused(400, "INVALID_JSON")
    return parsed


def _customer_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """A customer body carrying only a code and an optional PIN.

    An unexpected key is refused rather than dropped. That makes "a browser cannot supply a
    balance, only a code" a property of the shape instead of a property of which keys we read.
    """
    parsed = _body(event)
    if set(parsed) - set(CUSTOMER_BODY_FIELDS):
        raise Refused(400, "UNSUPPORTED_FIELD")
    return parsed


def _path_id(event: Dict[str, Any]) -> str:
    return str((event.get("pathParameters") or {}).get("giftCardId") or "")


def _route_key(event: Dict[str, Any]) -> str:
    context = event.get("requestContext") or {}
    http = context.get("http") or {}
    method = str(http.get("method") or event.get("httpMethod") or "").upper()
    raw = context.get("routeKey") or event.get("routeKey") or ""
    if raw and " " in str(raw):
        return str(raw)
    path = str(http.get("path") or event.get("path") or "")
    return f"{method} {path}"


# ── staff routes ──────────────────────────────────────────────────────────────

def _create(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Issue a card and return the code ONCE.

    The code is in the response body and in nothing else: the stored row carries `codeLast4`, the
    log line carries `****1234`, and no subsequent read can return the code. A card whose code is
    lost is reissued, not recovered - which is the correct property for bearer value.
    """
    denied = _staff(event)
    if denied:
        return denied
    payload = _body(event)
    unknown = sorted(set(payload) - set(CREATE_FIELDS))
    if unknown:
        raise Refused(400, "UNSUPPORTED_FIELD")
    subject = ((event.get("_auth") or {}).get("username")) or None
    issued = store.issue(
        _cards(),
        initial_value_paise=payload.get("initialValuePaise"),
        pepper=_pepper(),
        pin=payload.get("pin"),
        expires_at_ms=payload.get("expiresAtMs"),
        issued_to_contact_id=payload.get("issuedToContactId"),
        source_order_id=payload.get("sourceOrderId"),
        created_by=subject,
        currency=payload.get("currency", store.CURRENCY))
    card = issued["card"]
    logger.info(json.dumps({"event": "gift_card_issued",
                            "giftCardId": card["giftCardId"],
                            "codeLast4": store.masked(card["codeLast4"]),
                            "initialValuePaise": card["initialValuePaise"]}))
    # `code` is in the RESPONSE and in no row, no log and no later read.
    return cors_response(201, {"giftCard": _public(card), "code": issued["code"]}, origin)


def _get(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """One card, by OUR `giftCardId`. Resolved through the `GCID#` pointer row, two exact reads."""
    denied = _staff(event)
    if denied:
        return denied
    card = store.get_card_by_id(_cards(), gift_card_id=_path_id(event))
    if not card:
        return error_response(404, "GIFT_CARD_NOT_FOUND", origin)
    return cors_response(200, {"giftCard": _public(card)}, origin)


def _list(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """The staff list by `status`, through `status-index`, with the outstanding liability.

    The liability is summed over the page in integer paise. It is the figure this table exists to
    answer, and summing it here rather than in a browser is what keeps it an integer.
    """
    denied = _staff(event)
    if denied:
        return denied
    status = str((event.get("queryStringParameters") or {}).get("status")
                 or store.STATUS_ACTIVE)
    page = store.list_by_status(_cards(), status)
    rows = [_public(row) for row in page.get("Items") or []]
    liability = sum(int(row.get("balancePaise") or 0) for row in rows)
    return cors_response(200, {"giftCards": rows, "outstandingLiabilityPaise": liability},
                         origin)


def _disable(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """`status = DISABLED`. Never a delete - the liability record survives the card."""
    denied = _staff(event)
    if denied:
        return denied
    cards = _cards()
    existing = store.get_card_by_id(cards, gift_card_id=_path_id(event))
    if not existing:
        return error_response(404, "GIFT_CARD_NOT_FOUND", origin)
    digest = existing[store.KEY_ATTRIBUTE][len(store.PREFIX_CARD):]
    card = store.disable(cards, code_hash=digest)
    logger.info(json.dumps({"event": "gift_card_disabled",
                            "giftCardId": card.get("giftCardId"),
                            "codeLast4": store.masked(card.get("codeLast4"))}))
    return cors_response(200, {"giftCard": _public(card)}, origin)


# ── customer route ────────────────────────────────────────────────────────────

def _balance(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Balance only, from a code in the BODY. Reserves nothing.

    Every refusal - malformed code, unknown code, wrong PIN - answers `GIFT_CARD_NOT_FOUND` with
    the same status, so this cannot be ground into a code-validity oracle. The rate limit is what
    makes grinding expensive rather than merely uninformative.
    """
    session = _customer(event)
    if not rate_limit.check_rate_limit("gift-card-balance", session.customer_id,
                                       BALANCE_RATE_LIMIT_PER_SECOND):
        raise Refused(429, "RATE_LIMITED")
    body = _customer_body(event)
    pepper = _pepper()
    cards = _cards()
    digest = store.code_hash(body.get("code"), pepper=pepper)
    card = store.assert_spendable(store.get_card(cards, code_hash=digest),
                                  now_ms=_now() * 1000)
    store.verify_pin(card, body.get("pin"), pepper=pepper)
    logger.info(json.dumps({"event": "gift_card_balance_checked",
                            "giftCardId": card.get("giftCardId"),
                            "codeLast4": store.masked(card.get("codeLast4"))}))
    return cors_response(200, {"giftCardId": card.get("giftCardId"),
                               "codeLast4": card.get("codeLast4"),
                               "balancePaise": int(card.get("balancePaise") or 0),
                               "currency": store.CURRENCY,
                               "status": card.get("status")}, origin)


# ── projection ────────────────────────────────────────────────────────────────

#: What a response may carry. `codeLast4` is the only part of the code that ever leaves, and
#: `pinHash` is absent from this list deliberately - an HMAC of a short PIN is still worth not
#: publishing, and nothing a client does needs it.
PUBLIC_ATTRIBUTES = ("giftCardId", "codeLast4", "initialValuePaise", "balancePaise", "currency",
                     "status", "issuedAtMs", "expiresAtMs", "issuedToContactId", "sourceOrderId",
                     "policyVersion", "createdAt", "updatedAt")


def _public(row: Mapping[str, Any]) -> Dict[str, Any]:
    """An allowlisted projection, so an attribute added later is not published by accident."""
    return {key: _plain(row[key]) for key in PUBLIC_ATTRIBUTES if key in row}


def _plain(value: Any) -> Any:
    """DynamoDB `Decimal` to `int`, exactly, or raise.

    `int(Decimal)` truncates, so a fractional value would silently become a different number.
    Every money attribute here is integer paise, so a fraction is a data error and is refused
    rather than absorbed.
    """
    if type(value).__name__ == "Decimal":
        if value != value.to_integral_value():
            raise Refused(500, "NON_INTEGER_STORED_AMOUNT")
        return int(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _now() -> int:
    """Epoch SECONDS as an int. One conversion at the boundary, so no float reaches a comparison."""
    return int(time.time())


# ── dispatch ──────────────────────────────────────────────────────────────────

def handler(event, context):  # noqa: ARG001 - Lambda signature
    origin = extract_origin(event)
    route = _route_key(event)
    if route.startswith("OPTIONS "):
        return options_response(origin)

    entry = ROUTE_HANDLERS.get(route) or _by_suffix(route)
    if not entry:
        return error_response(404, "UNKNOWN_ROUTE", origin)
    served = globals()[entry[1]]
    try:
        return served(event, origin)
    except Refused as refusal:
        return error_response(refusal.status, refusal.code, origin)
    except store.GiftCardError as refusal:
        return error_response(refusal.status, refusal.code, origin)
    except store.GiftCardStoreUnavailable as exc:
        logger.error(json.dumps({"event": "gift_card_store_unavailable",
                                 "reason": type(exc).__name__}))
        return error_response(503, "TEMPORARILY_UNAVAILABLE", origin)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "gift_card_request_failed", "route": route,
                                 "reason": type(exc).__name__}))
        return error_response(503, "TEMPORARILY_UNAVAILABLE", origin)


def _by_suffix(route: str) -> Optional[Tuple[str, str]]:
    """Resolve a concrete path onto its templated route key.

    API Gateway supplies `requestContext.routeKey` with the template intact, so this only matters
    for a direct invoke or a local test that sends a real path. Matching is on the SHAPE, and the
    segment it matches is a `giftCardId` - never a code, because no route accepts one.
    """
    method, _, path = route.partition(" ")
    parts = [part for part in path.split("/") if part]
    if not parts or parts[0] != "gift-cards":
        return None
    if method == "GET" and len(parts) == 2:
        return ROUTE_HANDLERS["GET /gift-cards/{giftCardId}"]
    if method == "POST" and len(parts) == 3 and parts[2] == "disable":
        return ROUTE_HANDLERS["POST /gift-cards/{giftCardId}/disable"]
    return None
