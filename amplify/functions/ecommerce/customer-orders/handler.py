"""A signed-in customer's own order history and profile summary. Read-only.

`POST /ecommerce/my-orders` on API `zllr9lrg7j`, stage `prod`, behind the `live` alias.

THE SECURITY BOUNDARY IS STRUCTURAL, NOT A COMPARISON
-----------------------------------------------------
The order list is one `Query` on `customerId-createdAt-index` whose partition key is the Cognito
`sub` taken from `customer_auth.require_customer(event)`. DynamoDB will not return an item from
another partition, so another customer's order is not *rejected* here - it is unreachable. There
is deliberately no row-level filter on `customerId`: a filter runs AFTER DynamoDB has read and
charged for the other customer's item, which means its bytes have already reached this process's
memory. "Unreachable" and "read and then discarded" are different security properties, and only
the first is worth having.

Nothing in the request can be an identity. The body accepts `limit` and `cursor` and nothing
else; an unrecognised key is a 400 rather than a silently ignored field, because a client that
believes it sent a filter it did not is how a wrong list gets trusted.

`POST`, not `GET`. `customer_session.harden_session_headers`'s own docstring records the reason:
the Amplify rewrite serves `/api/<*>` with status 200, so a shared cache sits in front of these
responses, and a cached per-customer order list replayed to a second customer is exactly the
disclosure this module exists to prevent. Every exit is hardened through `_no_store` as well -
`response.cors_response` sets no cache directive at all - but a method that is not cacheable in
the first place is a stronger arrangement than a header that makes a cacheable one safe.

WHAT THIS FUNCTION CANNOT DO
----------------------------
It cannot write. Its role (`scripts/provision_customer_orders.py::expected_role_policy`) holds
`dynamodb:Query` on the ORDER TABLE INDEX ARN only - no statement on the table itself - so a
`GetItem` for `purchasedSnapshot` is an AccessDeniedException rather than a code review finding.
It reads no credential of any kind: no Secrets Manager client, no provider key, and no statement
for one in its role. It cannot capture, refund, charge or message anyone.

MONEY AND STATUS
----------------
Amounts are integer paise on the wire and the currency is compared explicitly to `INR`, never
inferred from the magnitude of the amount. There is no division, no rounding, no float arithmetic
and no rupee string anywhere in this module - the browser renders. Status goes through
`lambda_utils.payment_status` and this handler compares no payment word in any spelling: it
reports a canonical value and a rank, and the sentence a customer reads is chosen in the browser.

DEGRADATION
-----------
A bad ROW degrades to an explicit "unavailable" (null amount, empty status, null date, empty
order number); a bad TABLE refuses with 503. One order with an unreadable amount must not blank a
customer's whole history.
"""

from __future__ import annotations

import base64
import json
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import customer_auth, customer_session, dynamo_reads, payment_status, rate_limit
from lambda_utils.ecommerce import contact_address, order_channel
from lambda_utils.identity import customer as customer_identity
from lambda_utils.identity import customer_uuid
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

#: The internal order record. SINGULAR `OrderTable` - the environment variable is plural and the
#: table is not, which is a trap worth stating rather than rediscovering: `ORDERS_TABLE` naming
#: `stack-wecare-digital-OrdersTable` would be a ResourceNotFoundException read as a missing index.
ORDERS_TABLE = os.environ.get("ORDERS_TABLE", "stack-wecare-digital-OrderTable")

#: The sparse customer-scoped index. `scripts/provision_customer_orders.py` is the single source
#: of truth for this name and creates it; the default here is the same literal deliberately, and
#: `tests/test_customer_orders_iam.py` asserts the two agree.
ORDERS_BY_CUSTOMER_INDEX = os.environ.get(
    "ORDERS_BY_CUSTOMER_INDEX", "customerId-createdAt-index")

CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE", "stack-wecare-digital-RateLimitTable")

#: INR and nothing else. Compared, never inferred from the amount and never defaulted.
EXPECTED_CURRENCY = "INR"

#: Page size. The module default maximum is 100; 50 here, because a 100-order page is a payload
#: nobody reads.
DEFAULT_PAGE = 20
MAX_PAGE = 50

#: A cursor carries two small scalars, so anything longer is not one of ours.
CURSOR_MAX_CHARS = 512

#: Requests per second per PROVEN subject. Keyed on `identity.customer_id` rather than on anything
#: the request supplies, which is what makes the limit meaningful instead of trivially bypassable.
RATE_LIMIT_PER_SECOND = 10

_dynamodb = None


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _table(name: str):
    """The DynamoDB resource, built on FIRST USE rather than at import.

    A module-scope `boto3.resource` reaches for AWS configuration at import time, which breaks
    pytest collection and a local run with no AWS config - `tests/conftest.py` documents that at
    length and records that this lazy shape is the fleet convention.
    """
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _body(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The request body as a dict, or `None` when it is present and not an object."""
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


def _encode_cursor(last_key: Optional[Dict[str, Any]]) -> str:
    """base64url of compact JSON carrying ONLY `{orderId, createdAt}`. `''` when there is no page.

    `customerId` is deliberately omitted. It is not concealment - base64url is not encryption -
    but there is nothing to conceal: the partition component is overwritten from the proven
    identity on the way back in (see `_start_key`), so round-tripping it would serve no purpose
    and would invite a reader to trust it.
    """
    if not isinstance(last_key, dict):
        return ""
    order_id = str(last_key.get("orderId") or "")
    try:
        created_at = int(last_key["createdAt"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not order_id:
        return ""
    payload = json.dumps({"orderId": order_id, "createdAt": created_at}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(raw: Any) -> Dict[str, Any]:
    """`{orderId, createdAt}` from an opaque cursor, or raise `ValueError`.

    A malformed cursor is a 400 rather than a silent reset to page one: a client that believes it
    is paginating while actually re-reading the first page will loop forever.
    """
    value = str(raw or "")
    if not value:
        raise ValueError("cursor is empty")
    if len(value) > CURSOR_MAX_CHARS:
        raise ValueError("cursor is longer than any cursor this handler issues")
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - every decode failure is one 400
        raise ValueError("cursor does not decode") from exc
    if not isinstance(decoded, dict):
        raise ValueError("cursor is not an object")
    order_id = str(decoded.get("orderId") or "")
    if not order_id:
        raise ValueError("cursor carries no orderId")
    try:
        created_at = int(decoded["createdAt"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("cursor carries no usable createdAt") from exc
    return {"orderId": order_id, "createdAt": created_at}


def _start_key(cursor: Dict[str, Any], customer_id: str) -> Dict[str, Any]:
    """The `ExclusiveStartKey` for a paged read, with the partition taken from the TOKEN.

    This is the one place a round-tripped value could become an authorisation input, and it is
    closed by construction rather than by validation: `customerId` comes from the proven identity
    and never from the cursor, so a tampered cursor can at worst name a position inside the
    caller's own partition. That is why the cursor needs no signature - and a signed cursor would
    want a secret this function deliberately has no way to read.
    """
    return {"customerId": customer_id,
            "createdAt": cursor["createdAt"],
            "orderId": cursor["orderId"]}


def _profile_phone(identity: customer_auth.CustomerIdentity) -> str:
    """The contact-row phone key for this session, normalised the way the row was written.

    A THIRD copy of a two-line helper, and the duplication is deliberate rather than lazy. The
    nearest copy is in `ecommerce/checkout/handler.py`, which another phase owns in flight, and
    importing across function packages is not a thing this fleet does - each handler directory is
    packaged on its own. Promoting this (with the owned-contact predicate) to the shared layer is
    the right refactor and is recorded as a follow-up rather than done here.

    `InvalidPhoneNumber` degrades to the raw session value, matching `checkout`. It does NOT
    return a 400 the way `auth/customer-profile` does, and the asymmetry is the point: there the
    phone IS the write key, so an unparseable one must refuse the request; here it only decides
    whether a profile card renders beside an order list that is already correct.
    `MissingCountryCode` subclasses `InvalidPhoneNumber`, so one arm covers both.
    """
    try:
        return customer_identity.normalize_phone_preserving_country(identity.phone)
    except customer_identity.InvalidPhoneNumber:
        return str(identity.phone or "")


def _unowned(row: Dict[str, Any]) -> bool:
    """Whether this contact row has no `checkoutCustomerId` at all.

    The same predicate as `checkout._unowned`, and the same reason for the duplication as
    `_profile_phone` above: handler directories are packaged independently, so there is nothing
    to import. Kept as a named function rather than inlined because it is the distinction
    `_profile` turns on - "owned by nobody" is not "owned by someone else", and reading those two
    as one is exactly how a cross-customer read gets written by accident.

    A CRM-created contact carries no `checkoutCustomerId`, because only the checkout path writes
    one. The stamp is a write and stays in `auth/customer-profile`; see `_profile`.
    """
    return not str(row.get("checkoutCustomerId") or "").strip()


def _profile(identity: customer_auth.CustomerIdentity) -> Optional[Dict[str, Any]]:
    """The customer's own contact summary, or `None`. Never raises.

    THE WHOLE STEP IS INSIDE ONE `try`, not just the query, and that is not tidiness.
    `dynamo_reads.query_index` raises `ValueError` BEFORE it reaches `table.query` when the key is
    blank, and `identity.phone` is not guaranteed to be a phone - so a narrower `try` around the
    query alone would let that escape to the catch-all 500 and lose an order list that was
    already correct. The profile is a card beside the list; the list is the answer.

    The index lookup is on the phone, which is not an authorisation key: `phone-index` is
    hash-only and two rows can share a number (a soft-deleted one and its replacement, which is
    why both existing copies take `Limit=5` and scan the page). The AUTHORISATION is the
    `checkoutCustomerId` comparison, and it is a legitimate predicate here rather than the
    weakness it would be on the order list, because this resolves ONE row to accept or reject -
    rejecting it yields no profile, never another customer's row.

    AN UNOWNED ROW IS ADOPTED FOR READING, exactly as `checkout._unowned` already does. Only the
    checkout path writes `checkoutCustomerId`, so a CRM-created contact carries none, and
    demanding one made a customer who already exists in the CRM see no profile at all on
    `/orders` - while `ecommerce/checkout` and `auth/customer-profile`, reading the SAME row off
    the same index, both accepted it. Three readers, two answers, and this was the odd one out.

    READ-ONLY ADOPTION. This function does not stamp the claim, and must not: that is an
    `UpdateItem` on ContactsTable and this role holds `dynamodb:Query` on the phone index and
    nothing else, so a write from here would fail with AccessDenied at runtime where no test
    would see it. `auth/customer-profile` already emits `checkoutCustomerId` on every save and
    holds the grant to do it. The role is unchanged by this relaxation, which is why its IAM
    equality tests still pass untouched.

    A ROW OWNED BY A DIFFERENT CUSTOMER IS STILL REFUSED, so this cannot read across customers,
    and an OWNED row still wins over an unowned one - otherwise a session with its own row could
    adopt a stray unowned duplicate on the same number and show the wrong name.

    The predicate is deliberately WEAKER than `checkout`'s "ready to pay" (which also demands
    `emailVerifiedAt` and a non-empty email): a customer with real order history and an
    unverified email must still see their own name and address. `emailVerified` therefore travels
    on the wire, because the identity card renders a verified badge beside the email and has to be
    told when that badge would be a lie. Relaxing ownership does NOT relax that: adopting a row on
    a phone match says "this row is about me", never "its email is proven", and the badge still
    reports what the row actually carries.
    """
    try:
        phone = _profile_phone(identity)
        if not phone.strip():
            # No query at all: `query_index` would raise on a blank key, and saying so costs less
            # than catching it.
            return None
        rows = dynamo_reads.query_index(
            _table(CONTACTS_TABLE), index_name="phone-index",
            key_name="phone", value=phone, limit=5,
        )
        live = [row for row in rows if row.get("deletedAt") is None]
        # Two passes rather than one scored loop, because the precedence is the security
        # property: an owned row is preferred, and an unowned one is only ever a fallback.
        owned = next((row for row in live
                      if str(row.get("checkoutCustomerId") or "") == identity.customer_id), None)
        if owned is None:
            owned = next((row for row in live if _unowned(row)), None)
        if owned is None:
            return None
        first_name = str(owned.get("firstName") or "")
        last_name = str(owned.get("lastName") or "")
        # `from_contact` re-validates the stored map and never raises, so an address written
        # before a rule tightened degrades to "no address on file" rather than to a 500. It is
        # never a re-composition of the six address fields: `fullAddress` is derived server-side
        # and is the same string that reaches Wix and the invoice.
        address = contact_address.from_contact(owned)
        return {
            "name": (str(owned.get("name") or "").strip()
                     or f"{first_name} {last_name}".strip()),
            "firstName": first_name,
            "lastName": last_name,
            "email": str(owned.get("email") or ""),
            "emailVerified": bool(owned.get("emailVerifiedAt")),
            "phone": phone,
            "addressComplete": address is not None,
            "address": address,
        }
    except Exception as exc:  # noqa: BLE001 - a degraded card, never a lost order list
        logger.warning(json.dumps({"event": "contact_read_failed",
                                   "error": type(exc).__name__}))
        return None


def _money(row: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """`(paise, currency)` for an order row, or `(None, currency)` when it cannot be trusted.

    One comparison and one coercion, with an integrality guard between them.

    The currency is compared to the literal `INR`. It is never derived from the amount and never
    defaulted: a row storing anything else comes back with a null amount, so the page says
    "amount unavailable" rather than rendering foreign minor units behind a rupee sign.

    ONE TYPE GUARD, AND IT SUBSUMES THE FLOAT CHECK. An allowlist of `(int, Decimal)` excludes
    `float` BY CONSTRUCTION, so a second `isinstance(raw, float)` arm would be dead code - which
    is worse than no check, because a reader trusts it. The allowlist also catches more than a
    float arm would: `payment_status.paise` coerces with `int()`, so a STRING amount that happens
    to parse would otherwise sail through, and a string is not a trusted amount even when it
    parses. `bool` is an `int` subclass, so it passes this guard and is caught by `paise`, which
    raises on it.

    THE INTEGRALITY GUARD IS NOT REDUNDANT, AND THIS WAS MEASURED. `paise` raises on `None`, on a
    bool and on a negative - but it coerces with `int()`, so `paise(Decimal('1.5'))` returns 1
    silently. A truncated amount is the exact failure the money rule exists to stop, so a
    non-integral amount fails CLOSED here rather than displaying a smaller number than the
    customer paid. Unreachable on the website lineage, where `accept_paid` copies an already
    integer-paise attempt value - which makes this a guard rather than a fix, and the right kind:
    two lines, and it cannot be satisfied by accident.

    The `int()` is also required for CORRECTNESS OF THE WIRE FORMAT. `cors_response` serialises
    with `json.dumps(body, default=str)`, so a `Decimal` would arrive in the browser as the string
    "121481" while an int arrives as the number 121481.
    """
    currency = str(row.get("currency") or "")
    if currency != EXPECTED_CURRENCY:
        return None, currency
    raw = row.get("amountPaise")
    if not isinstance(raw, (int, Decimal)):
        return None, currency
    if isinstance(raw, Decimal) and raw != raw.to_integral_value():
        return None, currency
    try:
        return payment_status.paise(raw), currency
    except ValueError:
        return None, currency


def _project(row: Dict[str, Any]) -> Dict[str, Any]:
    """One wire row. Total by construction: every coercion degrades rather than raising.

    Four per-row degradations, all four of them explicit, because one unreadable order must not
    blank a history: an unreadable amount is `null`, an unmappable status is `''` with rank 0, an
    uncoercible date is `null`, and a missing order number is `''` - which is why `referenceId`
    is on the wire as a second identifier the page can fall back to.
    """
    amount_paise, currency = _money(row)
    stored_status = row.get("paymentStatus")
    reference_id = str(row.get("referenceId") or "")
    order_number = str(row.get("orderNumber") or "")

    try:
        created_at: Optional[int] = int(row["createdAt"])
    except (KeyError, TypeError, ValueError):
        created_at = None
        logger.warning(json.dumps({"event": "order_date_unreadable",
                                   "orderNumber": order_number}))

    # `referenceId` is our own identifier, is not a secret and is not a phone number, so it is
    # logged in full on purpose: it is the correlation id that lets a payment log line be traced
    # with no masked field in it.
    if not order_number:
        logger.warning(json.dumps({"event": "order_number_missing",
                                   "referenceId": reference_id}))

    currency_unexpected = currency != EXPECTED_CURRENCY
    if currency_unexpected:
        logger.warning(json.dumps({"event": "order_currency_unexpected",
                                   "currency": currency,
                                   "referenceId": reference_id}))
    elif amount_paise is None:
        logger.warning(json.dumps({"event": "order_amount_unreadable",
                                   "orderNumber": order_number}))

    # No comparison against a payment word in any spelling. This handler has no decision to make
    # about payment state: it reports a canonical value and its rank, and the branch that chooses
    # a sentence lives in the browser. That is what keeps one vocabulary single.
    status = payment_status.canonical(stored_status)
    if not status:
        logger.info(json.dumps({"event": "order_status_unmapped",
                                "storedStatus": str(stored_status or ""),
                                "referenceId": reference_id}))

    return {
        "orderNumber": order_number,
        "referenceId": reference_id,
        "createdAt": created_at,
        "amountPaise": amount_paise,
        "currency": currency,
        # ALWAYS present, defaulting to false, so a browser reading
        # `row.currencyUnexpected === true` is type-stable across rows and pages. A field that
        # appears only when true forces every reader to handle `undefined` as well.
        "currencyUnexpected": currency_unexpected,
        "status": status,
        "statusRank": payment_status.rank(stored_status),
        # WHERE the order was placed, through the one coercion that owns the word. No raw string
        # comparison here for the same reason there is none for payment state: a second reading
        # of a vocabulary is a second answer waiting to disagree. `canonical` is TOTAL, so it
        # cannot break this function's degrade-never-raise property, and an absent `channel` -
        # every row written before the index was widened - reads as `website`, which is true
        # because no WhatsApp order can exist.
        "channel": order_channel.canonical(row.get("channel")),
        # The PUBLIC customer id, and ALWAYS PRESENT defaulting to `''` for exactly the reason
        # `currencyUnexpected` above is always present: a field that appears only when it has a
        # value forces every reader to handle `undefined` as well as the empty case, and the
        # browser's one job here is to show the row or not show it. `from_contact` re-validates,
        # so a junk or uuid7 value stored by some future writer reaches the page as `''` rather
        # than being displayed - and it never raises, which keeps this function's
        # degrade-never-raise property intact.
        #
        # Safe on the wire and safe in a log, unlike the phone beside it: it is ours, opaque,
        # carries no timestamp, and is not a credential. Same standing as `referenceId`.
        customer_uuid.ATTRIBUTE: customer_uuid.from_contact(row),
    }


def _respond(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """The request, in the fixed order of operations the module docstring describes."""
    rc = event.get("requestContext", {}) or {}
    method = str(rc.get("http", {}).get("method", event.get("httpMethod", "")) or "").upper()
    if method == "OPTIONS":
        # The API's own CORS configuration answers the preflight, so there is no OPTIONS route
        # today. This branch exists so one can be added later with no code change.
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    # AUTH PRECEDES EVERYTHING THAT COSTS ANYTHING. Before the rate limit, because rate limiting
    # an anonymous caller would key on something the request supplies; and before any DynamoDB
    # read, so an unauthenticated request costs one Cognito call and nothing else.
    identity, denied = customer_auth.require_customer(event)
    if denied:
        # Rebuilt through `cors_response` rather than returned as-is, so the structural guard in
        # tests/test_session_response_is_not_cacheable.py can resolve a callee here: its AST
        # walker reads `_no_store`'s ARGUMENT, and a bare name tells it nothing about what is
        # being returned. Status and body are carried over verbatim, which keeps the two failure
        # modes `require_customer` collapses - no token, and a token from the staff pool -
        # byte-identical, as its documented contract requires.
        return _no_store(cors_response(int(denied["statusCode"]),
                                       json.loads(denied["body"]), origin))

    # `check_rate_limit` fails OPEN on error, which is right here: this endpoint has no side
    # effect to protect, and refusing a legitimate read because the counter table is unavailable
    # would be the worse outcome.
    if not rate_limit.check_rate_limit("my-orders", identity.customer_id,
                                       RATE_LIMIT_PER_SECOND, table_name=RATE_LIMIT_TABLE):
        return _no_store(cors_response(429, {"error": "TOO_MANY_REQUESTS"}, origin))

    body = _body(event)
    if body is None:
        return _no_store(cors_response(400, {"error": "INVALID_BODY"}, origin))
    # An allowlist, so a typo'd field name is refused rather than silently ignored. There is no
    # `customerId`, `phone`, `orderId` or `email` here: the body carries nothing that could be an
    # identity, which means there is nothing for a future edit to accidentally authorise on.
    if set(body) - {"limit", "cursor"}:
        return _no_store(cors_response(400, {"error": "UNEXPECTED_FIELD"}, origin))

    # `bounded_limit` never raises - `int(params.get('limit','50'))` is a 500 waiting for
    # `?limit=abc`, which is why the clamp is a shared helper rather than a local line.
    limit = dynamo_reads.bounded_limit(body.get("limit"), default=DEFAULT_PAGE, maximum=MAX_PAGE)

    paging = "cursor" in body
    start_key: Optional[Dict[str, Any]] = None
    if paging:
        try:
            start_key = _start_key(_decode_cursor(body.get("cursor")), identity.customer_id)
        except ValueError:
            # The cursor value itself is never logged.
            logger.info(json.dumps({"event": "orders_cursor_rejected"}))
            return _no_store(cors_response(400, {"error": "INVALID_CURSOR"}, origin))

    try:
        result = _table(ORDERS_TABLE).query(
            IndexName=ORDERS_BY_CUSTOMER_INDEX,
            # THE SECURITY BOUNDARY, AND IT IS THIS ONE LINE. `identity.customer_id` comes only
            # from `customer_auth.authenticate` -> the Cognito `sub`. DynamoDB will not return an
            # item from another partition, so another customer's order is unreachable rather than
            # filtered out. There is deliberately no row-level filter naming `customerId`: a
            # filter runs after the other row has been read and charged for and has reached this
            # process's memory, and adding one would signal that the key condition is not trusted
            # - which would entitle the next reader to move the scoping into it.
            KeyConditionExpression=Key("customerId").eq(identity.customer_id),
            ScanIndexForward=False,          # newest first
            # The limit reaches DynamoDB, not just Python: slicing after the fact still pays for
            # and transfers everything.
            Limit=limit,
            **({"ExclusiveStartKey": start_key} if start_key else {}),
        ) or {}
    except Exception as exc:  # noqa: BLE001
        # A failed query has no partial answer, so this is a refusal rather than a degradation.
        # A ResourceNotFoundException here means the index is missing or still CREATING, which
        # reads exactly like a wrong index name - hence logging the name beside the type.
        logger.error(json.dumps({"event": "orders_query_failed",
                                 "error": type(exc).__name__,
                                 "index": ORDERS_BY_CUSTOMER_INDEX}))
        return _no_store(cors_response(503, {"error": "ORDERS_UNAVAILABLE"}, origin))

    orders: List[Dict[str, Any]] = [_project(row) for row in (result.get("Items") or [])
                                    if isinstance(row, dict)]
    payload: Dict[str, Any] = {"orders": orders}
    next_cursor = _encode_cursor(result.get("LastEvaluatedKey"))
    if next_cursor:
        payload["cursor"] = next_cursor

    # THE PROFILE IS FIRST PAGE ONLY, AND IT IS OMITTED - NOT NULL - ON A PAGED REQUEST.
    # `null` is a meaningful value here ("no contact row, or a degraded read"), so returning it
    # for page two would let one transient contacts failure remove a card the customer is already
    # looking at. Omitting it says "not answered on this request" instead, and saves a query per
    # page for a value the page discards anyway.
    if not paging:
        payload["profile"] = _profile(identity)

    logger.info(json.dumps({"event": "customer_orders_read",
                            "orders": len(orders),
                            "paged": paging,
                            "hasNextPage": bool(next_cursor)}))
    return _no_store(cors_response(200, payload, origin))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Entry point. The outer guard exists so no failure can escape as a bare Lambda error.

    An unhandled exception leaving a handler reaches the browser as a network-class failure with
    no body and no CORS headers, which a client cannot read a message out of. The message carries
    the exception TYPE only - never its text, which can echo an input back.
    """
    origin = extract_origin(event)
    try:
        return _respond(event, origin)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_orders_error",
                                 "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
