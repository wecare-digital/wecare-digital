"""`wecare-coupons` - coupon issuance, eligibility and holds. Seven routes, no discount.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` sections 5.1
(routes), 5.1.1 (the route provisioner and the authorization posture), 5.3 (error handling) and 5.4
(validation).

| Route | Identity | Wix call |
|---|---|---|
| `POST /coupons` | staff | `POST /stores/v2/coupons` |
| `GET /coupons/{code}` | staff | `GET /stores/v2/coupons/{id}` |
| `GET /coupons` | staff | none |
| `POST /coupons/{code}/deactivate` | staff | `PATCH /stores/v2/coupons/{id}` |
| `POST /coupons/validate` | customer session | none |
| `POST /coupons/hold` | customer session | none |
| `POST /coupons/release` | customer session | none |

There is no `DELETE /coupons/{code}`. Deactivation is reversible and preserves the audit trail;
deletion destroys the definition a settled order references.

AUTHORIZATION, STATED RATHER THAN READ OFF THE GATEWAY
------------------------------------------------------
All seven routes are created with `AuthorizationType=NONE` and no authorizer, because this account
has zero API Gateway authorizers across 361 routes and this change does not introduce the first
one. Authentication is `middleware.require_auth` INSIDE the handler on the five staff routes, and a
customer-session resolution on the two customer routes. `00-current-owner-overrides.md` records why
the gateway field must not be read as the answer: it cannot distinguish an intentionally public
signed webhook from an accidentally public API. So the claim lives here and in
`tests/test_coupons_routes_and_registry.py`, which asserts every route authenticates BEFORE any
table access.

With WAF removed by owner decision there is no per-IP layer in front of these routes.
`POST /coupons/validate` is the one a stranger could grind to enumerate valid codes, so it
additionally goes through `rate_limit.check_rate_limit` per session, and its refusal vocabulary
gives `UNKNOWN_CODE` the same answer SHAPE as `EXPIRED`.

VALIDATE RETURNS A VERDICT AND NEVER AN AMOUNT
----------------------------------------------
That is the security boundary, not a stylistic choice. The amount is Wix's answer to
`Calculate Cart`; a validate endpoint that returned a discount figure would become a number a
browser could quote. Every answer is one word from `coupon_store.VERDICTS`.

THE CREDENTIAL
--------------
The Wix admin key is referenced only by its secret ID and is read LAZILY, at request time, by
`wix_ecom._request` - never at module scope, because a module-scope read is frozen into a warm
sandbox and a rotation would keep using the old value until every sandbox recycled. Nothing here
reads the key at all, so no logging expression can touch it, not even reduced to a bool: CodeQL
tracks taint across function boundaries and a ternary on a secret's truthiness is still a finding.

A Wix error body is never surfaced or logged. `wix_ecom._request` already reduces an `HTTPError` to
a status-only message for exactly that reason, and that behaviour is relied on rather than
reimplemented. No branch here parses a status out of an exception's prose.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from lambda_utils import customer_session as sessions
from lambda_utils import middleware, rate_limit, wix_ecom
from lambda_utils.customer_session_store import SessionStore
from lambda_utils.ecommerce import coupon_store, wix_coupons
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, error_response, extract_origin, options_response

logger = get_logger(__name__)

#: Secret NAME only. The value is read lazily inside `wix_ecom._request`, by reference.
WIX_API_KEY_SECRET = os.environ.get("WIX_API_KEY_SECRET", "wecare/wix/headless-api-key")

COUPONS_TABLE = os.environ.get(coupon_store.TABLE_ENV_KEY, coupon_store.DEFAULT_TABLE_NAME)
CUSTOMER_SESSIONS_TABLE = os.environ.get(
    "CUSTOMER_SESSIONS_TABLE", "stack-wecare-digital-CustomerSessionsTable")

#: Grind budget for `POST /coupons/validate`, per session per second. WAF is gone, so this is
#: the only layer in front of the one route a stranger could use to enumerate codes.
VALIDATE_RATE_LIMIT_PER_SECOND = 5

#: Staff routes need at least this role. Issuing a discount is an operator action.
STAFF_ROLE = "Operator"

#: route key -> (identity, the function that serves it). Declared so the provisioner's route
#: list and the handler's dispatch cannot drift, and so a test can resolve each route to the
#: function whose auth call it has to inspect.
ROUTE_HANDLERS: Dict[str, Tuple[str, str]] = {
    "POST /coupons": ("staff", "_create"),
    "GET /coupons/{code}": ("staff", "_get"),
    "GET /coupons": ("staff", "_list"),
    "POST /coupons/{code}/deactivate": ("staff", "_deactivate"),
    "POST /coupons/validate": ("customer", "_validate"),
    "POST /coupons/hold": ("customer", "_hold"),
    "POST /coupons/release": ("customer", "_release"),
}

#: Request-body keys a browser may send on the customer routes. `cartId` and the code, and
#: nothing financial - a body carrying `discountPaise` or `amount` is refused outright rather
#: than ignored, so an attempt to supply a discount fails loudly.
CUSTOMER_BODY_FIELDS = ("code", "cartId")


class Refused(Exception):
    """An input or policy refusal carrying the status and machine code to answer with."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


# ── lazily built collaborators ────────────────────────────────────────────────

def _table(name: str):
    """A DynamoDB table resource, built per request.

    `boto3` is imported here rather than at module scope so the shared modules stay importable
    with no AWS at all, which is what makes the offline tests possible.
    """
    import boto3
    return boto3.resource("dynamodb",
                          region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(name)


def _coupons_table():
    return _table(COUPONS_TABLE)


def _wix() -> wix_coupons.WixCoupons:
    """The Wix mirror adapter over the shared request callable.

    `wix_ecom._request` reads the API key by reference from Secrets Manager, lazily, on its
    first call. Nothing in this module sees the value.
    """
    return wix_coupons.WixCoupons(wix_ecom._request)


# ── identity ──────────────────────────────────────────────────────────────────

def _staff(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cognito staff authentication. Returns a response to send back, or None to proceed."""
    return middleware.require_auth(event, STAFF_ROLE)


def _customer(event: Dict[str, Any]) -> sessions.SessionView:
    """Resolve the customer session, or refuse.

    The customer id comes from the SESSION, never from the request body. An id a browser can
    set is an id an attacker can set, and here it would hand one customer another's per-customer
    coupon allowance.
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    cookie = sessions.read_cookie({
        **headers,
        "cookie": "; ".join(event.get("cookies") or []) or headers.get("cookie", "")})
    if not cookie:
        raise Refused(401, "VERIFICATION_REQUIRED")
    try:
        view = sessions.validate(SessionStore(_table(CUSTOMER_SESSIONS_TABLE)), cookie)
        sessions.assert_csrf(view, str(headers.get('x-customer-csrf') or ''))
        return view
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
    """A customer body carrying only a code and a cart id.

    An unexpected key is refused rather than dropped. That is what makes "a browser cannot
    supply a discount, only a code" a property of the shape instead of a property of which keys
    we happen to read.
    """
    parsed = _body(event)
    if set(parsed) - set(CUSTOMER_BODY_FIELDS):
        raise Refused(400, "UNSUPPORTED_FIELD")
    return parsed


def _path_code(event: Dict[str, Any]) -> str:
    return str((event.get("pathParameters") or {}).get("code") or "")


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
    """Create locally, then mirror into Wix. Local claim FIRST, deliberately.

    The local conditional put is the cheap, reversible half. If the Wix call then fails we hold
    a `PENDING_WIX` row that a retry resolves. The reverse order would create a Wix coupon our
    table has no record of - an issued discount with no owner, which nothing would reconcile.

    Every Wix failure of every status leaves the row `PENDING_WIX` and answers `202`. No status
    is special-cased because `Create Coupon` documents none, and a `PENDING_WIX` coupon is
    refused by `validate`, so the worst case is a coupon that does not work rather than one that
    works differently from what was promised.
    """
    denied = _staff(event)
    if denied:
        return denied
    payload = _body(event)
    subject = ((event.get("_auth") or {}).get("username")) or None
    table = _coupons_table()
    definition = coupon_store.create(table, payload, created_by=subject)
    # The code may be logged in full: it is broadcast marketing material, not bearer value.
    logger.info(json.dumps({"event": "coupon_created", "code": definition["code"],
                            "couponId": definition["couponId"],
                            "discountKind": definition["discountKind"]}))
    try:
        wix_coupon_id = _wix().create(definition)
    except Exception as exc:  # noqa: BLE001 - every status leaves the row PENDING_WIX
        logger.warning(json.dumps({"event": "coupon_mirror_pending",
                                   "code": definition["code"],
                                   "reason": type(exc).__name__}))
        return cors_response(202, {"coupon": _public(definition)}, origin)
    mirrored = coupon_store.mark_mirrored(table, definition["code"], wix_coupon_id)
    return cors_response(201, {"coupon": _public(mirrored or definition)}, origin)


def _get(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Our record plus the Wix mirror state, resolved code -> row -> `wixCouponId`.

    The Wix call is by ID, never by code: `Get Coupon` takes an id, and composing a Wix URL out
    of a customer-visible code is how a path-injection bug gets written. A Wix failure answers
    `200` with `PENDING_WIX` rather than failing the read - our row is the authority.
    """
    denied = _staff(event)
    if denied:
        return denied
    table = _coupons_table()
    definition = coupon_store.get_definition(table, _path_code(event))
    if not definition:
        return error_response(404, "UNKNOWN_CODE", origin)
    mirror: Dict[str, Any] = {"state": definition.get("wixMirrorState")}
    wix_coupon_id = definition.get("wixCouponId")
    if wix_coupon_id:
        try:
            mirror["wix"] = _wix().assert_mirrors(wix_coupon_id=wix_coupon_id,
                                                  code=definition["code"])
        except wix_coupons.WixCouponConflict:
            logger.error(json.dumps({"event": "coupon_wix_code_conflict",
                                     "code": definition["code"]}))
            return error_response(409, wix_coupons.WixCouponConflict.code, origin)
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"event": "coupon_mirror_unreadable",
                                       "code": definition["code"],
                                       "reason": type(exc).__name__}))
            mirror["state"] = coupon_store.MIRROR_PENDING
    return cors_response(200, {"coupon": _public(definition), "mirror": mirror}, origin)


def _list(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """The staff list, by `status`, through `status-index`."""
    denied = _staff(event)
    if denied:
        return denied
    status = str((event.get("queryStringParameters") or {}).get("status")
                 or coupon_store.STATUS_ACTIVE)
    page = coupon_store.list_by_status(_coupons_table(), status)
    return cors_response(200, {"coupons": [_public(row) for row in page.get("Items") or []]},
                         origin)


def _deactivate(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """`INACTIVE` locally FIRST, then ask Wix. Never a delete.

    The local state binds: a coupon that is INACTIVE with us and still active in Wix is refused
    by `validate` before `Add Coupon` is ever called. The reverse order would leave a window in
    which we believe a coupon is live and Wix has already switched it off.
    """
    denied = _staff(event)
    if denied:
        return denied
    table = _coupons_table()
    code = _path_code(event)
    definition = coupon_store.deactivate(table, code)
    logger.info(json.dumps({"event": "coupon_deactivated",
                            "code": definition.get("code") or code}))
    wix_coupon_id = definition.get("wixCouponId")
    if wix_coupon_id:
        try:
            _wix().deactivate(wix_coupon_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"event": "coupon_mirror_deactivate_pending",
                                       "code": definition.get("code") or code,
                                       "reason": type(exc).__name__}))
            return cors_response(202, {"coupon": _public(definition)}, origin)
    return cors_response(200, {"coupon": _public(definition)}, origin)


# ── customer routes ───────────────────────────────────────────────────────────

def _validate(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Eligibility only. Answers a verdict from the closed vocabulary and NEVER an amount."""
    session = _customer(event)
    if not rate_limit.check_rate_limit("coupon-validate", session.customer_id,
                                       VALIDATE_RATE_LIMIT_PER_SECOND):
        raise Refused(429, "RATE_LIMITED")
    body = _customer_body(event)
    table = _coupons_table()
    code = coupon_store.normalise_code(body.get("code"))
    definition = coupon_store.get_definition(table, code)
    uses = coupon_store.customer_uses(table, code, session.customer_id) if definition else 0
    verdict = coupon_store.evaluate(definition, cart_id=body.get("cartId"),
                                    customer_uses_count=uses)
    logger.info(json.dumps({"event": "coupon_validated", "code": code, "verdict": verdict}))
    return cors_response(200, {"code": code, "verdict": verdict}, origin)


def _hold(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Take a `COUPONHOLD#` for one cart, through the single conditional write of DECISION 5."""
    session = _customer(event)
    body = _customer_body(event)
    table = _coupons_table()
    code = coupon_store.normalise_code(body.get("code"))
    cart_id = body.get("cartId")
    definition = coupon_store.get_definition(table, code)
    verdict = coupon_store.evaluate(definition, cart_id=cart_id,
                                    customer_uses_count=coupon_store.customer_uses(
                                        table, code, session.customer_id) if definition else 0)
    if verdict != coupon_store.ELIGIBLE:
        return cors_response(200, {"code": code, "verdict": verdict, "held": False}, origin)
    held = coupon_store.hold(table, code=code, cart_id=cart_id)
    logger.info(json.dumps({"event": "coupon_held", "code": code,
                            "expiresAtMs": held["expiresAtMs"]}))
    return cors_response(200, {"code": code, "verdict": coupon_store.ELIGIBLE, "held": True,
                               "expiresAtMs": held["expiresAtMs"]}, origin)


def _release(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Drop this cart's hold."""
    _customer(event)
    body = _customer_body(event)
    table = _coupons_table()
    code = coupon_store.normalise_code(body.get("code"))
    coupon_store.release(table, code=code, cart_id=body.get("cartId"))
    logger.info(json.dumps({"event": "coupon_released", "code": code}))
    return cors_response(200, {"code": code, "released": True}, origin)


# ── projection ────────────────────────────────────────────────────────────────

#: What a response may carry. A definition row holds the promised discount, and the staff view
#: needs it; the customer routes never return a row at all, only a verdict.
PUBLIC_ATTRIBUTES = ("code", "name", "status", "discountKind", "moneyOffPaise", "percentOffBps",
                     "fixedPricePaise", "buyX", "buyY", "minimumSubtotalPaise",
                     "scopeNamespace", "scopeGroupName", "scopeEntityId", "startTimeMs",
                     "expirationTimeMs", "usageLimit", "limitPerCustomer", "usageCount",
                     "limitedToOneItem", "currency", "wixMirrorState", "couponId",
                     "policyVersion", "createdAt", "updatedAt", "tags")


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    """An allowlisted projection, so an attribute added later is not published by accident."""
    return {key: _plain(row[key]) for key in PUBLIC_ATTRIBUTES if key in row}


def _plain(value: Any) -> Any:
    """DynamoDB `Decimal` to `int`, exactly, or raise.

    `int(Decimal)` truncates, so a fractional value would silently become a different number.
    Every money attribute on this path is integer paise, so a fraction here is a data error and
    is refused rather than absorbed.
    """
    if type(value).__name__ == "Decimal":
        if value != value.to_integral_value():
            raise Refused(500, "NON_INTEGER_STORED_AMOUNT")
        return int(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


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
    except coupon_store.CouponError as refusal:
        return error_response(refusal.status, refusal.code, origin)
    except coupon_store.CouponStoreUnavailable as exc:
        logger.error(json.dumps({"event": "coupon_store_unavailable",
                                 "reason": type(exc).__name__}))
        return error_response(503, "TEMPORARILY_UNAVAILABLE", origin)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "coupon_request_failed", "route": route,
                                 "reason": type(exc).__name__}))
        return error_response(503, "TEMPORARILY_UNAVAILABLE", origin)


def _by_suffix(route: str) -> Optional[Tuple[str, str]]:
    """Resolve a concrete path onto its templated route key.

    API Gateway supplies `routeContext.routeKey` with the template intact, so this only matters
    for a direct invoke or a local test that sends a real path. Matching is on the shape, never
    on a substring of the code.
    """
    method, _, path = route.partition(" ")
    parts = [part for part in path.split("/") if part]
    if not parts or parts[0] != "coupons":
        return None
    if method == "GET" and len(parts) == 2:
        return ROUTE_HANDLERS["GET /coupons/{code}"]
    if method == "POST" and len(parts) == 3 and parts[2] == "deactivate":
        return ROUTE_HANDLERS["POST /coupons/{code}/deactivate"]
    return None
