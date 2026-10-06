"""A signed-in customer's own invoice, as a short-lived presigned download. Read-only.

`POST /ecommerce/my-invoice` on API `zllr9lrg7j`, stage `prod`, behind the `live` alias.

WHY THIS IS A SEPARATE FUNCTION AND NOT A ROUTE ON `wecare-customer-orders`
---------------------------------------------------------------------------
This route needs `dynamodb:Query` on `InvoicesTable/index/referenceId-index`,
`dynamodb:GetItem` on `InvoiceAssetsTable` and `s3:GetObject` under
`secure/stack/invoices/*`. Every one of those is SPECIFICALLY refused by
`wecare-customer-orders`' pinned policy and by six equality assertions in
`tests/test_customer_orders_iam.py` - whose own header states the discipline: "Every
assertion here is EQUALITY rather than containment". Putting this route there would mean
editing those six tests so they assert less, on the one function whose documented security
property IS its emptiness. A wildcard exemption written once becomes the precedent for the
next one.

So this is a new single-purpose function with its own least-privilege role, its own
equality-asserted IAM test and its own `live` alias, and `wecare-customer-orders` is not
edited at all. `tests/test_customer_orders_iam.py` passing UNCHANGED is an assertion about
this work: if it needed an edit, the route went on the wrong function.

Secondary benefit worth naming: this route reads S3 and two more tables, so it is the one
with a real blast radius. Keeping it out of the function that serves the hot list path
means a mistake here cannot reach the list.

`available:false` IS THE SINGLE ANSWER FOR THREE DIFFERENT FACTS
----------------------------------------------------------------
"No invoice row", "no asset row" and "not your order" all answer
`200 {"available": false}`, byte-identically. That is deliberate: a distinguishable
refusal would make this route an existence oracle for another customer's invoice. It is
the same uniform-refusal rule `core/secure-files` already documents.

THE SUCCESS BODY IS EXACTLY TWO KEYS
------------------------------------
`{"available": true, "url": ...}` and nothing else. `expiresInSeconds`, `filename` and an
echoed `format` were all considered and dropped under one rule applied three times: a
field in a contract with no consumer is a field a later edit will treat as load-bearing on
the strength of its presence alone. `filename` in particular would be a SECOND, unverified
source of truth - `receipt_links.signed_url` bakes `attachment; filename="..."` into the
signature, so the server's name is already the one the browser uses. `assetType` appears in
no response field at all; it is an internal table key, and `format` and `assetType` are two
different vocabularies that must not mix on the wire.

IT NEVER GENERATES
------------------
A missing asset row answers `available:false`. There is no call to `generate_invoice_image`
anywhere in this module, and that absence is pinned by a test: generation is
`require_auth`-gated and ADVANCES THE GST SEQUENCE, so a customer-triggered render would
mutate invoice state from a read path.

`POST`, not `GET`, for the reason `customer_session.harden_session_headers` documents: the
Amplify rewrite serves `/api/<*>` with status 200, so a shared cache sits in front of these
responses. Every exit is additionally hardened through `_no_store`.

NO CREDENTIAL IS READ OR NAMED. There is no Secrets Manager client here and no statement
for one in this function's role. Presigning is a local signature computation, not an S3
call, so this function needs no network access to S3 either.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import customer_auth, customer_session, rate_limit, receipt_links
from lambda_utils.ecommerce import customer_receipt
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

#: SINGULAR `OrderTable`. The environment variable is plural and the table is not, which is
#: a trap worth stating rather than rediscovering: `ORDERS_TABLE` naming
#: `stack-wecare-digital-OrdersTable` is a ResourceNotFoundException read as a missing index.
ORDERS_TABLE = os.environ.get("ORDERS_TABLE", "stack-wecare-digital-OrderTable")

#: The sparse customer-scoped index. `scripts/provision_customer_orders.py` owns the NAME
#: and creates it; this function only reads it, and `tests/test_customer_invoice_iam.py`
#: asserts this default agrees with what the policy grants.
ORDERS_BY_CUSTOMER_INDEX = os.environ.get(
    "ORDERS_BY_CUSTOMER_INDEX", "customerId-createdAt-index")

INVOICES_TABLE = os.environ.get("INVOICES_TABLE", "stack-wecare-digital-InvoicesTable")
INVOICES_BY_REFERENCE_INDEX = os.environ.get(
    "INVOICES_BY_REFERENCE_INDEX", "referenceId-index")
INVOICE_ASSETS_TABLE = os.environ.get(
    "INVOICE_ASSETS_TABLE", "stack-wecare-digital-InvoiceAssetsTable")
RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE", "stack-wecare-digital-RateLimitTable")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "wecare-digital-get")

#: TIGHTER than `my-orders`' 10/s, not looser, and the direction is the point: that route is
#: a cheap list read, this one presigns and costs two Queries, a GetItem and a signature per
#: call. A human clicking download buttons does not exceed 5 in a second.
#:
#: `table_name=` is passed EXPLICITLY at the call site for the same reason `my-orders` does
#: it: the module default in `rate_limit.py` reads its own `RATE_LIMIT_TABLE` env var, so an
#: unset variable on THIS function would silently write to a different table name than the
#: one its IAM policy grants - and `check_rate_limit` FAILS OPEN on the resulting
#: AccessDeniedException, logging at WARNING and returning True. The signature default is
#: `max_per_second=80`; never take it by omission.
RATE_LIMIT_PER_SECOND = 5

#: The request field is a FILE FORMAT; the table key is an ASSET TYPE. They are not the same
#: vocabulary and the png -> image step is written down rather than inferred. `assetType`
#: never leaves this function.
ASSET_TYPE = {"png": "image", "pdf": "pdf"}

#: Compared against a literal set, never passed through to `assetType` unchecked.
ALLOWED_FORMATS = frozenset(ASSET_TYPE)

#: Our own generated identifier, never free text, so it is allowlisted rather than escaped.
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
REFERENCE_MAX_CHARS = 128

#: A browser download starts immediately. A day-long grant on a page is the
#: forwarded-message risk `receipt_links` exists to bound, so 300s rather than its 24h
#: default.
LINK_TTL_SECONDS = 300

_dynamodb = None
_s3 = None


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _table(name: str):
    """The DynamoDB resource, built on FIRST USE rather than at import.

    A module-scope `boto3.resource` reaches for AWS configuration at import time, which
    breaks pytest collection and a local run with no AWS config. It is also the lazy-read
    rule in `lambda-snapstart-deploy.md`: a module-scope read is cached for the life of the
    execution environment.
    """
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _s3_client():
    """The S3 client, also on first request. Only ever used to SIGN, never to fetch."""
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=REGION)
    return _s3


def _body(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The request body as a dict, or `None` when it is absent, unparseable or not an object."""
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _validated(body: Dict[str, Any]) -> Tuple[Optional[Tuple[str, int, str]], Optional[str]]:
    """`((reference_id, created_at, fmt), None)` or `(None, error_code)`.

    A STRICT three-key allowlist: any other key is `UNEXPECTED_FIELD` rather than a silently
    ignored field, because a client that believes it sent a filter it did not is how a wrong
    answer gets trusted.
    """
    unexpected = set(body) - {"referenceId", "createdAt", "format"}
    if unexpected:
        return None, "UNEXPECTED_FIELD"

    raw_reference = body.get("referenceId")
    if not isinstance(raw_reference, str):
        return None, "INVALID_BODY"
    reference_id = raw_reference.strip()
    if not reference_id or len(reference_id) > REFERENCE_MAX_CHARS:
        return None, "INVALID_BODY"
    if not REFERENCE_PATTERN.match(reference_id):
        return None, "INVALID_BODY"

    created_at = body.get("createdAt")
    # `isinstance(True, int)` is TRUE, so bool is rejected explicitly rather than by the int
    # check - `Key(...).eq(True)` would be a well-formed query for a nonsense timestamp.
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at <= 0:
        return None, "INVALID_BODY"

    fmt = body.get("format", "png")
    if not isinstance(fmt, str) or fmt not in ALLOWED_FORMATS:
        return None, "UNSUPPORTED_FORMAT"

    return (reference_id, created_at, fmt), None


def _owned_order(customer_id: str, reference_id: str,
                 created_at: int) -> Optional[Dict[str, Any]]:
    """The caller's own order row carrying `reference_id` at `created_at`, or `None`.

    OWNERSHIP IS A MEMBERSHIP TEST, NOT `Items[0]`.

    `createdAt` is the index RANGE key in whole SECONDS, not a unique key, so `eq()` on it
    returns EVERY row the caller holds at that second - and one customer can hold more than
    one. Taking the first row would refuse a legitimate second order in the same second with
    `available:false`, which this route makes indistinguishable from "not yours", so the
    customer would get a permanent, unexplainable "No invoice yet" and the log would say the
    ownership check failed. No `Limit` applies for the same reason.

    The security property is the KEY CONDITION, not a filter: `customerId` comes only from
    the proven identity, and DynamoDB will not return an item from another partition, so
    another customer's order is unreachable rather than read and discarded. `createdAt` is
    required in the body precisely so this stays an exact key condition rather than a scan
    of the caller's whole partition.

    Both `referenceId` and `orderNumber` are already in the index's projection, so this needs
    no follow-up `GetItem` and no projection change.
    """
    result = _table(ORDERS_TABLE).query(
        IndexName=ORDERS_BY_CUSTOMER_INDEX,
        KeyConditionExpression=(Key("customerId").eq(customer_id)
                                & Key("createdAt").eq(created_at)),
    ) or {}
    rows = [row for row in (result.get("Items") or []) if isinstance(row, dict)]
    return next((row for row in rows
                 if str(row.get("referenceId") or "") == reference_id), None)


def _invoice_id(reference_id: str) -> str:
    """The invoice for a reference, through the existing `referenceId-index`, or `''`."""
    result = _table(INVOICES_TABLE).query(
        IndexName=INVOICES_BY_REFERENCE_INDEX,
        KeyConditionExpression=Key("referenceId").eq(reference_id),
        Limit=1,
    ) or {}
    rows = [row for row in (result.get("Items") or []) if isinstance(row, dict)]
    return str(rows[0].get("invoiceId") or "") if rows else ""


def _asset_key(invoice_id: str, fmt: str) -> str:
    """The stored `s3Key` for one rendered asset, or `''`.

    A bare `get_item` on a fully specified `{invoiceId, assetType}` key, which is why the
    IAM grant for it is correctly a bare table ARN: there is nothing an index would narrow.
    """
    result = _table(INVOICE_ASSETS_TABLE).get_item(
        Key={"invoiceId": invoice_id, "assetType": ASSET_TYPE[fmt]}) or {}
    item = result.get("Item")
    return str(item.get("s3Key") or "") if isinstance(item, dict) else ""


def _download_name(order_number: str, reference_id: str, fmt: str) -> str:
    """A sanitised attachment filename.

    `order_number` comes off the ownership row and is an UNVALIDATED DynamoDB string, while
    `reference_id` was allowlisted `[A-Za-z0-9_-]+` on the way in. `signed_url` interpolates
    this into `attachment; filename="{filename}"` and bakes it INTO the signature, so an
    unsanitised value would be interpolated into a signed header.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "", f"invoice-{order_number or reference_id}.{fmt}")


def _available_false(origin: str) -> Dict[str, Any]:
    """The ONE answer for no invoice, no asset and not-your-order. Never distinguishable."""
    return _no_store(cors_response(200, {"available": False}, origin))


def _respond(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """The request, in the fixed order of operations this module's docstring describes."""
    rc = event.get("requestContext", {}) or {}
    method = str(rc.get("http", {}).get("method", event.get("httpMethod", "")) or "").upper()
    if method == "OPTIONS":
        # The API's own CORS configuration answers the preflight, so there is no OPTIONS
        # route today. This branch exists so one can be added later with no code change.
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    # AUTH PRECEDES EVERYTHING THAT COSTS ANYTHING. Before the rate limit, because rate
    # limiting an anonymous caller would key on something the request supplies; and before
    # any read, so an unauthenticated request costs one Cognito call and nothing else.
    identity, denied = customer_auth.require_customer(event)
    if denied or identity is None:
        # Rebuilt through `cors_response` rather than returned as-is, so the structural
        # cache guard can resolve a callee here. Status and body are carried over verbatim,
        # which keeps the two failure modes `require_customer` collapses byte-identical.
        return _no_store(cors_response(int(denied["statusCode"]),
                                       json.loads(denied["body"]), origin))

    if not rate_limit.check_rate_limit("my-invoice", identity.customer_id,
                                       RATE_LIMIT_PER_SECOND, table_name=RATE_LIMIT_TABLE):
        return _no_store(cors_response(429, {"error": "TOO_MANY_REQUESTS"}, origin))

    # VALIDATION RUNS AFTER AUTH AND AFTER THE RATE LIMIT, so an unauthenticated caller
    # cannot use the 400 bodies to probe the shape of the route - and before ANY read, so a
    # malformed request costs no DynamoDB call at all.
    body = _body(event)
    if body is None:
        return _no_store(cors_response(400, {"error": "INVALID_BODY"}, origin))
    validated, error = _validated(body)
    if error or validated is None:
        return _no_store(cors_response(400, {"error": error}, origin))
    reference_id, created_at, fmt = validated

    try:
        owned = _owned_order(identity.customer_id, reference_id, created_at)
        if owned is None:
            # The SAME answer a missing invoice gets. `referenceId` is our own identifier,
            # is not a secret and is not a phone number, so it is logged in full on purpose:
            # it is the correlation id that lets this line be traced with no masked field.
            logger.info(json.dumps({"event": "invoice_not_owned",
                                    "referenceId": reference_id}))
            return _available_false(origin)
        order_number = str(owned.get("orderNumber") or "")

        invoice_id = _invoice_id(reference_id)
        if not invoice_id:
            logger.info(json.dumps({"event": "invoice_absent",
                                    "referenceId": reference_id}))
            return _available_false(origin)

        s3_key = _asset_key(invoice_id, fmt)
        if not s3_key:
            # NOT GENERATED. Generation advances the GST sequence, so a read path must never
            # trigger it - this function imports no generator and calls none.
            logger.info(json.dumps({"event": "invoice_asset_absent",
                                    "referenceId": reference_id}))
            return _available_false(origin)
    except Exception as exc:  # noqa: BLE001
        # A failed read has no partial answer, so this is a refusal rather than a
        # degradation. The type only - a DynamoDB error message can echo an input back.
        logger.error(json.dumps({"event": "invoice_lookup_failed",
                                 "error": type(exc).__name__,
                                 "referenceId": reference_id}))
        return _no_store(cors_response(503, {"error": "INVOICE_UNAVAILABLE"}, origin))

    try:
        # THE STORED KEY IS VALIDATED BEFORE IT IS PRESIGNED, and this is not
        # belt-and-braces. `s3Key` comes out of a DynamoDB row, so it is the one input on
        # this path that is neither the caller's nor this code's. INVOICE_PREFIX moved from
        # the public `o/` root to the gated `secure/` root on 2026-09-30, which means a key
        # shaped `o/stack/invoices/...` is a legal string a row could still carry - and
        # presigning it SUCCEEDS and returns a signed URL for a world-readable object. The
        # client-side signature check would pass while the artifact stayed public forever.
        customer_receipt.assert_private_key(s3_key)
    except Exception as exc:  # noqa: BLE001
        # `type(exc).__name__` AND NEVER `str(exc)`. `ReceiptError`'s message is built as
        # f"refusing a receipt key outside the gated root: {key!r}..." - our own code
        # composed it, but it EMBEDS THE S3 KEY, which is the one thing that must not reach
        # CloudWatch on this path. Logging an exception's text is permitted only when the
        # message was constructed from known-safe parts; this one was not.
        logger.warning(json.dumps({"event": "invoice_key_refused",
                                   "error": type(exc).__name__,
                                   "referenceId": reference_id}))
        return _available_false(origin)

    try:
        url = receipt_links.assert_not_permanent(receipt_links.signed_url(
            _s3_client(), bucket=MEDIA_BUCKET, key=s3_key,
            filename=_download_name(order_number, reference_id, fmt),
            ttl_seconds=LINK_TTL_SECONDS))
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "invoice_sign_failed",
                                 "error": type(exc).__name__,
                                 "referenceId": reference_id}))
        return _no_store(cors_response(503, {"error": "INVOICE_UNAVAILABLE"}, origin))

    # Metadata only. The URL carries a grant, so it never reaches a log line.
    logger.info(json.dumps({"event": "invoice_link_issued",
                            "referenceId": reference_id,
                            "ttlSeconds": LINK_TTL_SECONDS}))
    return _no_store(cors_response(200, {"available": True, "url": url}, origin))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Entry point. The outer guard exists so no failure can escape as a bare Lambda error.

    An unhandled exception leaving a handler reaches the browser as a network-class failure
    with no body and no CORS headers, which a client cannot read a message out of. The
    message carries the exception TYPE only - never its text, which can echo an input back.
    """
    origin = extract_origin(event)
    try:
        return _respond(event, origin)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_invoice_error",
                                 "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
