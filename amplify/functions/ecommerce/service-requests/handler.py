"""Phase O-1 service requests: the pre-payment intent, the customer's own list, and activation.

`wecare-service-requests`, behind the `live` alias, on API `zllr9lrg7j`:

    POST /services/request-intent   {kind, targetRequestId?}
    POST /services/my-requests      {referenceIds?, limit?, cursor?}

plus one INTERNAL invoke, honoured only when the event carries no `requestContext` (an API
Gateway event always does), sent fire-and-forget by `razorpay-webhook` after reconciliation
reports an order:

    {"internalAction": "activateServiceRequest", "referenceId", "paymentAttemptId", "orderId"}

WHAT THIS FUNCTION CANNOT DO
----------------------------
It cannot move money. It imports no Razorpay, Wix or cart module and reads no secret; its role
(`scripts/provision_service_requests.py::expected_role_policy`) grants its own table, one index
Query, a LeadingKeys-scoped GetItem on the commerce-keys table and the rate-limit counter -- and
nothing else. Paid-ness is never a word compared here: a request is created only when the
`PAYMENTATTEMPT#` claim exists, and that claim exists only after `razorpay_verify` read an
authenticated capture back from Razorpay. So the internal invoke is a HINT, not an authority:
every id in it is re-read and must agree, and a forged invoke produces at most a no-op.

THE SECURITY BOUNDARY IS STRUCTURAL
-----------------------------------
The customer id is the Cognito `sub` from `customer_auth.require_customer`, and nothing in a body
can be an identity. The list is one Query on the caller's own GSI partition. An amendment target
that is missing, someone else's, or not a Submit Request is one identical 404, so the route is not
an existence oracle. `POST` and `Cache-Control: no-store` on every exit, for the reason
`customer-orders/handler.py` records: a shared cache sits in front of `/api/<*>`.

Logs carry ids only; a phone never appears, and an exception is logged by type name only.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import boto3

from lambda_utils import customer_auth, customer_session, rate_limit
from lambda_utils.ecommerce import service_request_store as store
from lambda_utils.ecommerce import service_requests
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
SERVICE_REQUESTS_TABLE = os.environ.get("SERVICE_REQUESTS_TABLE", store.DEFAULT_TABLE_NAME)
COMMERCE_KEYS_TABLE = os.environ.get("COMMERCE_KEYS_TABLE", "stack-wecare-digital-WixOrderIds")
RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE", "stack-wecare-digital-RateLimitTable")

#: Per proven subject, per second. Keyed on the Cognito `sub`, never on anything in the request.
INTENT_RATE_PER_SECOND = 3
LIST_RATE_PER_SECOND = 10
MAX_REFERENCE_IDS = 20
INTERNAL_ACTION = "activateServiceRequest"

#: The `WD-PAY-` payment reference shape `order_keys.mint_payment_reference` produces (and the
#: Meta reference charset it is validated against). Anything else is not one of ours.
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,35}$")

_dynamodb = None


def _table(name: str):
    """Built on FIRST USE rather than at import, the fleet convention (see tests/conftest.py)."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _body(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _path(event: Dict[str, Any]) -> str:
    return str(event.get("rawPath") or event.get("path") or "").rstrip("/").lower()


# ── internal: activation hint from the webhook ────────────────────────────────

def _internal(event: Dict[str, Any]) -> Dict[str, Any]:
    """Never raises. Returns the outcome dict; the caller (an async invoke) discards it anyway."""
    reference_id = str(event.get("referenceId") or "")
    attempt_id = str(event.get("paymentAttemptId") or "")
    if reference_id and not _REFERENCE_RE.match(reference_id):
        return {"outcome": store.NOT_A_SERVICE_ORDER}
    try:
        outcome = store.activate(_table(SERVICE_REQUESTS_TABLE), _table(COMMERCE_KEYS_TABLE),
                                 reference_id=reference_id, payment_attempt_id=attempt_id)
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "service_activation_failed",
                                 "error": type(error).__name__, "referenceId": reference_id}))
        return {"outcome": "ERROR"}
    if outcome.outcome != store.NOT_A_SERVICE_ORDER:
        logger.info(json.dumps({"event": "service_activation_hint", "outcome": outcome.outcome,
                                "referenceId": reference_id,
                                "orderId": str(event.get("orderId") or "")}))
    return outcome.as_dict()


# ── POST /services/request-intent ─────────────────────────────────────────────

def _request_intent(identity, body: Dict[str, Any], origin: str, event=None) -> Dict[str, Any]:
    if set(body) - {"kind", "targetRequestId", "fileId"}:
        return cors_response(400, {"error": "UNEXPECTED_FIELD"}, origin)
    if not rate_limit.check_rate_limit("service-intent", identity.customer_id,
                                       INTENT_RATE_PER_SECOND, table_name=RATE_LIMIT_TABLE):
        return cors_response(429, {"error": "RATE_LIMITED"}, origin)
    try:
        vault_file = None
        if body.get('fileId'):
            if str(body.get('kind') or '').upper() != 'VAULT' or body.get('targetRequestId'):
                return cors_response(400, {'error': 'INVALID_FILE_CHOICE'}, origin)
            user = boto3.client('cognito-idp', region_name=REGION).get_user(
                AccessToken=customer_auth.bearer_token(event or {}))
            attrs = {a['Name']: a['Value'] for a in user.get('UserAttributes', [])}
            if (attrs.get('phone_number_verified') != 'true' or attrs.get('sub') != identity.customer_id
                    or attrs.get('phone_number') != identity.phone):
                return cors_response(401, {'error': 'PHONE_VERIFICATION_REQUIRED'}, origin)
            from lambda_utils.ecommerce import vault_access
            vault_file = vault_access.bind_file(_table(vault_access.FILES_TABLE), identity, body['fileId'])
        intent = store.request_intent(_table(SERVICE_REQUESTS_TABLE), identity,
                                      body.get("kind"), body.get("targetRequestId"), vault_file=vault_file)
    except service_requests.ServiceRejected as rejected:
        if rejected.code == service_requests.SERVICE_NOT_OFFERED:
            return cors_response(409, service_requests.refusal(rejected.code), origin)
        if rejected.code in service_requests.SERVICE_MESSAGES:
            return cors_response(400, service_requests.refusal(rejected.code), origin)
        return cors_response(400, {"error": rejected.code}, origin)
    except customer_auth.CustomerNotAuthorized:
        return cors_response(404, {"error": "REQUEST_NOT_FOUND",
                                   "message": "We could not find that request on your account."},
                             origin)
    except store.ServiceIdentityUnavailable as error:
        logger.error(json.dumps({"event": "service_intent_unavailable",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)
    return cors_response(200, intent, origin)


# ── POST /services/my-requests ────────────────────────────────────────────────

def _my_requests(identity, body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    if set(body) - {"referenceIds", "limit", "cursor"}:
        return cors_response(400, {"error": "UNEXPECTED_FIELD"}, origin)
    references = body.get("referenceIds", [])
    if (not isinstance(references, list) or len(references) > MAX_REFERENCE_IDS
            or not all(isinstance(ref, str) and _REFERENCE_RE.match(ref) for ref in references)):
        return cors_response(400, {"error": "INVALID_REFERENCE_IDS"}, origin)
    if not rate_limit.check_rate_limit("my-requests", identity.customer_id,
                                       LIST_RATE_PER_SECOND, table_name=RATE_LIMIT_TABLE):
        return cors_response(429, {"error": "RATE_LIMITED"}, origin)
    cursor = None
    if "cursor" in body:
        try:
            cursor = store.decode_cursor(body.get("cursor"))
        except ValueError:
            return cors_response(400, {"error": "INVALID_CURSOR"}, origin)
    limit = body.get("limit")
    limit = limit if type(limit) is int and 0 < limit <= store.LIST_MAX else store.LIST_MAX

    table = _table(SERVICE_REQUESTS_TABLE)
    # THE SELF-HEAL. Each of the caller's own paid references is activated if it is a services
    # order whose webhook hint was missed. Scoped to the caller (`caller_customer_id`), and a
    # failure never fails the read: the list below is the answer.
    for reference_id in dict.fromkeys(references):
        try:
            store.activate(table, _table(COMMERCE_KEYS_TABLE), reference_id=reference_id,
                           caller_customer_id=identity.customer_id)
        except Exception as error:  # noqa: BLE001
            logger.warning(json.dumps({"event": "service_self_heal_skipped",
                                       "error": type(error).__name__,
                                       "referenceId": reference_id}))
    try:
        rows, next_cursor = store.list_for_customer(table, identity, limit=limit, cursor=cursor)
    except store.ServiceIdentityUnavailable as error:
        logger.error(json.dumps({"event": "service_requests_list_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "REQUESTS_UNAVAILABLE"}, origin)
    payload: Dict[str, Any] = {"requests": rows}
    if next_cursor:
        payload["cursor"] = next_cursor
    return cors_response(200, payload, origin)


def _respond(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    rc = event.get("requestContext", {}) or {}
    method = str(rc.get("http", {}).get("method", event.get("httpMethod", "")) or "").upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    # AUTH PRECEDES EVERYTHING THAT COSTS ANYTHING.
    identity, denied = customer_auth.require_customer(event)
    if denied:
        return _no_store(cors_response(int(denied["statusCode"]),
                                       json.loads(denied["body"]), origin))
    body = _body(event)
    if body is None:
        return _no_store(cors_response(400, {"error": "INVALID_BODY"}, origin))
    path = _path(event)
    if path.endswith("/services/request-intent"):
        return _no_store(_request_intent(identity, body, origin, event))
    if path.endswith("/services/my-requests"):
        return _no_store(_my_requests(identity, body, origin))
    return _no_store(cors_response(404, {"error": "NOT_FOUND"}, origin))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Entry point. The internal arm is reachable ONLY from a direct invoke (no requestContext)."""
    if isinstance(event, dict) and "requestContext" not in event \
            and event.get("internalAction") == INTERNAL_ACTION:
        try:
            return _internal(event)
        except Exception as error:  # noqa: BLE001
            logger.error(json.dumps({"event": "service_internal_error",
                                     "error": type(error).__name__}))
            return {"outcome": "ERROR"}
    origin = extract_origin(event if isinstance(event, dict) else {})
    try:
        return _respond(event, origin)
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "service_requests_error",
                                 "error": type(error).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
