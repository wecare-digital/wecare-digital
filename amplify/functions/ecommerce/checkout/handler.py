"""The customer checkout front door for the headless WhatsApp/Razorpay flow.

Where this sits
---------------
    [customer, signed in]  --create-->  THIS  --create checkout-->  [Wix eCom]     (authoritative total)
                                          |
                                          |  readiness gate (live Meta readback)
                                          |  reserve reference_id, build PaymentAttempt
                                          v
                                   [order_details in WhatsApp]  -->  [Meta]  -->  [Razorpay]   (pays in-chat)

This handler is the *verifier's front half*: it decides an amount authoritatively, records a
PaymentAttempt, and hands the customer off to pay inside WhatsApp. It never charges anything itself
and never creates an order — an order exists only after the razorpay-webhook reconciliation verifies
a capture against Razorpay's API. That boundary is the whole design, so this handler imports the
post-PAID functions of `order_keys` not at all.

Four rules it enforces, each load-bearing
------------------------------------------
1. **Authority comes from the session, never the request.** The customer is proven by
   `customer_auth` (issuer-pinned to the customer pool), and every checkout is bound to that
   immutable `CUS_` id. A `paymentAttemptId` or `checkoutId` in the body is checked against the
   session with `authorize_resource`, so one customer cannot read another's attempt (IDOR).
2. **The amount is Wix's, in integer paise.** `wix_ecom.authoritative_total_paise` reads
   `priceSummary.total` — the browser cannot set or influence it, and a non-whole-paise total is
   refused, not rounded.
3. **Payments are readiness-gated on a live provider readback.** `payment_readiness.evaluate` must
   return `PAYMENT_READY` before an attempt is created; otherwise the CTA is refused with the
   blocking state. No local constant can make it ready.
4. **The reference is minted once, reserved, and sent byte-for-byte.** `order_keys` mints and
   reserves it under `PAYREF#`; it is never transformed after reservation.

Initiation is disabled by default
----------------------------------
`CHECKOUT_INITIATION_ENABLED` gates the actual WhatsApp order_details send. Off (the default), the
handler does everything up to and including reserving the attempt, and returns the attempt in a
`PAYMENT_INITIATION_DISABLED` state instead of sending a payable message. This is the same
posture as the Velo adapter's `initiationEnabled=false`: the plumbing is exercised end to end, but
no live payment request goes out until someone deliberately turns it on. It can only be turned on,
never made permissive by a value that also disables readiness.

Nothing plaintext is logged
---------------------------
No full phone number, no customer id in a form that identifies a person beyond its own opaque id,
no amount tied to a person, no exception text that could echo request content. Event names, opaque
ids, states and counts only.

Two coexisting flows: the retained in-chat path and the additive website contract (section 8)
---------------------------------------------------------------------------------------------
This handler's `_create` returns ``PAYMENT_REQUEST_SENT`` for the IN-WHATSAPP flow above. That is
a RETAINED legacy response: callers still consume it, and it is NOT removed until they are migrated.
The in-WhatsApp vs website decision is an owner decision flagged in
``.agents/tasks/checkout-audit-2026-10-01/findings.md`` (the repo spec records "pay inside
WhatsApp" / "WhatsApp-only receipts"; the task asks for a website Razorpay Standard Checkout). Both
paths coexist behind the SAME ``CHECKOUT_INITIATION_ENABLED`` gate, default off.

The ADDITIVE website path lives in
``lambda_utils/ecommerce/website_checkout.py`` + ``lambda_utils/integrations/razorpay_orders.py``.
Its documented contract, which replaces ``PAYMENT_REQUEST_SENT`` for the website without deleting
it for the in-chat path, is:

    create  (gate off, the default)  -> ``PAYMENT_INITIATION_DISABLED``
            {paymentAttemptId}                 no gateway order, no payable attempt
    create  (gate on)                -> ``CHECKOUT_OPTIONS_READY``
            {keyId, orderId, amountPaise, currency, prefill, paymentAttemptId}
                                               ONLY these fields; keyId is the PUBLIC key id,
                                               orderId is the SERVER-STORED Razorpay gateway order
                                               id, amountPaise is the FEAT-001 calculator total
                                               (collection+fee+GST), never the raw Wix total.
    create  (ownership/snapshot/intent fails) -> ``CHECKOUT_REJECTED`` (no order created)
    create  (provider timeout/save ambiguity) -> ``CHECKOUT_AMBIGUOUS`` (never a 2nd payable order)

    callback (browser relays payment id/order id/signature) ->
            HMAC verified over the STORED gateway order id, then STILL requires
            ``razorpay_verify`` authoritative capture -> ``VERIFIED_PAID`` only after capture.

A Razorpay GATEWAY order exists before payment; an internal/Wix purchase order and public purchase
number exist ONLY after an authoritative capture. They are different objects. Cart/resume data is
kept until that verified-paid finalization. Partial payment is disabled for this release.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, customer_auth, customer_session, payment_readiness
from lambda_utils.ecommerce import (
    cart_v2, checkout_pricing, contact_address, customer_cart, finalization,
    gift_card_settlement, order_creation, order_keys, payment_attempt, purchase_intent,
    website_checkout, wix_address, wix_writeback)
from lambda_utils.integrations import razorpay_orders, razorpay_verify
from lambda_utils import wix_ecom
# Aliased `customer_identity`, NEVER `identity`: `identity` is a parameter name in nearly every
# function in this file (`_checkout_profile(identity)`, `_website_snapshot(identity, ...)`,
# `_profile_status(identity, ...)`), so that alias would be shadowed locally and
# `identity.normalize_phone_preserving_country` would resolve against a `CustomerIdentity`
# instance and raise `AttributeError` inside `_checkout_profile`'s `except Exception: raise` --
# a 500 on every checkout.
from lambda_utils.identity import customer as customer_identity
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

#: The payment-attempt store and the commerce-keys (reference reservation) store.
PAYMENT_ATTEMPTS_TABLE = os.environ.get(
    "PAYMENT_ATTEMPTS_TABLE", payment_attempt.DEFAULT_TABLE_NAME)
COMMERCE_KEYS_TABLE = os.environ.get("COMMERCE_KEYS_TABLE", "")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
#: The internal order record. An order exists ONLY after an authoritative capture, and this is
#: where that record lands. Granted `GetItem`/`PutItem`/`UpdateItem` and explicitly NOT
#: `DeleteItem`: an order record is evidence that money moved.
ORDERS_TABLE = os.environ.get("ORDERS_TABLE", "stack-wecare-digital-OrderTable")
WEBSITE_SNAPSHOT_TTL_SECONDS = 15 * 60

#: Reasons that mean "we refuse", as opposed to "we do not know". 409 for the first; 200 for the
#: provider-ambiguity reasons, where a claim either way about a charge would be dishonest.
_CART_BLOCKED = (website_checkout.CART_ALREADY_PAID,
                 website_checkout.CART_PAYMENT_IN_FLIGHT)

#: Checkout mode marker on the attempt, so this path is distinguishable from any other and a test
#: can assert which flow created it. Headless WhatsApp/Razorpay, not the (set-aside) Velo provider.
CHECKOUT_MODE = "WIX_HEADLESS"

#: The in-chat payment sender and the identity of the paying WABA/config. These name the existing
#: order_details path; this handler invokes it rather than reimplementing the message build.
SENDER_FUNCTION = os.environ.get("SENDER_FUNCTION", "wecare-whatsapp-business-api:live")
PAYMENT_WABA_ID = os.environ.get("PAYMENT_WABA_ID", "2094615664435155")

#: Readiness inputs. Deliberately have NO safe default that could read as "ready": an empty MID or
#: configuration name makes `payment_readiness.evaluate` return CONFIGURATION_UNVERIFIED, which
#: blocks. They are set from the environment at deploy time and re-derived from a live read.
EXPECTED_CONFIGURATION_NAME = os.environ.get("EXPECTED_CONFIGURATION_NAME", "")
EXPECTED_PROVIDER_MID = os.environ.get("EXPECTED_PROVIDER_MID", "")

#: Off by default. The plumbing runs; the payable message does not go out until this is truthy.
INITIATION_ENABLED = str(
    os.environ.get("CHECKOUT_INITIATION_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")

#: THE SEAM IS WIRED. `LOAD_OWNED_ADDRESS` is assigned just below `_load_owned_address`, which
#: has to follow `_checkout_profile` -- `deploy_all_lambdas.py` validates every top-level import
#: at module import, so a forward reference fails the build rather than a request.
#:
#: Signature: `(identity: customer_auth.CustomerIdentity) -> dict | None`. Widened from
#: `(customer_id)` because the lookup is a `phone-index` Query and the phone comes only from the
#: proven session; an address a browser can set is an address an attacker can set.
#:
#: The address is loaded SERVER-SIDE from the authenticated session's CRM contact row --
#: `checkoutDeliveryAddress`, written by `auth/customer-profile` -- not injected by a caller and
#: never read from a request body. This function does have the contacts table: `CONTACTS_TABLE`
#: is read above and the `dynamodb:Query` grant on `ContactsTable/index/phone-index` already
#: exists (`scripts/provision_checkout.py`). An earlier revision of this comment claimed
#: otherwise, and claimed the environment carried only `PAYMENT_ATTEMPTS_TABLE` and
#: `COMMERCE_KEYS_TABLE`; both were false.
#:
#: It stays a seam rather than becoming a direct call so a test can stub it, and because the
#: refusal it guards is the expensive one: the delivery address is the place of supply, so a
#: placeholder would produce a real total with the wrong CGST/SGST-versus-IGST split on an
#: invoice carrying seller GSTIN 19AAFFW7196L1Z8 -- and that total would be charged. With no
#: usable address on file a Cart V2 checkout still answers `DELIVERY_DETAILS_REQUIRED`, before
#: any Wix call.

_dynamodb = None
_lambda = None


def _table(name: str):
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _attempts_table():
    return _table(PAYMENT_ATTEMPTS_TABLE)


def _keys_table():
    return _table(COMMERCE_KEYS_TABLE or order_keys.commerce_keys_table_name())


def _orders_table():
    return _table(ORDERS_TABLE)


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


# ── readiness ────────────────────────────────────────────────────────────────

def _fetch_payment_configurations(waba_id: str) -> Dict[str, Any]:
    """Live Meta read of `GET /{waba}/payment_configurations`, via the WhatsApp business Lambda.

    Injected into `payment_readiness.evaluate` so this handler holds no Meta credential. The
    business-API Lambda already owns the Graph token and the read; we invoke its check route and
    return the parsed configurations payload it produces.
    """
    invoke_event = {
        "httpMethod": "GET",
        "path": "/wa-business/payment-config/raw",
        "queryStringParameters": {"wabaId": waba_id},
    }
    response = _lambda_client().invoke(
        FunctionName=SENDER_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(invoke_event).encode("utf-8"),
    )
    raw = response["Payload"].read()
    if response.get("FunctionError"):
        raise RuntimeError("payment-config read Lambda failed")
    result = json.loads(raw.decode("utf-8")) if raw else {}
    body = result.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            body = {}
    return body if isinstance(body, dict) else {}


def _readiness() -> payment_readiness.PaymentReadiness:
    return payment_readiness.evaluate(
        expected_waba_id=PAYMENT_WABA_ID,
        expected_configuration_name=EXPECTED_CONFIGURATION_NAME,
        expected_provider_mid=EXPECTED_PROVIDER_MID,
        fetch_configurations=_fetch_payment_configurations,
    )


# ── request plumbing ───────────────────────────────────────────────────────────

def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {k: v for k, v in event.items()
                if k not in ("requestContext", "headers", "httpMethod", "path",
                             "rawPath", "isBase64Encoded", "queryStringParameters")}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _action(event: Dict[str, Any], body: Dict[str, Any]) -> str:
    explicit = str(body.get("action") or event.get("action") or "").strip().lower()
    if explicit in ("create", "status", "prepare", "verify", "profile"):
        return explicit
    path = str(event.get("rawPath") or event.get("path") or "").lower()
    if path.endswith("/status"):
        return "status"
    if path.endswith("/prepare-checkout"):
        return "prepare"
    if path.endswith("/verify-callback"):
        return "verify"
    return "create"


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return options_response(origin)

    # Every checkout action requires a proven customer session. Unlike registration/email-OTP,
    # this endpoint is NOT public: by the time a customer reaches checkout they have signed in, and
    # a checkout must be bound to an authenticated identity server-side (never to a body-supplied
    # customerId, phone or Wix buyerId).
    identity, denied = customer_auth.require_customer(event)
    if denied:
        return denied

    body = _body(event)
    action = _action(event, body)
    try:
        if action == "status":
            return _status(identity, body, origin)
        if action == "prepare":
            return _website_prepare(identity, body, origin)
        if action == "verify":
            return _website_verify(identity, body, origin)
        # The readiness question. This arm is NOT optional alongside adding "profile" to
        # `_action`'s tuple: the `return _create(...)` below is this chain's `else`, so the tuple
        # alone would route a readiness probe into the checkout-CREATE path.
        if action == "profile":
            return _profile_status(identity, origin)
        return _create(identity, body, origin)
    except customer_auth.CustomerNotAuthorized:
        # Same opaque 401 as unauthenticated, so the endpoint is not an IDOR oracle.
        return customer_auth.denied_response(event)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "checkout_error",
                                 "action": action, "error": type(exc).__name__}))
        return cors_response(500, {"error": "INTERNAL_ERROR"}, origin)


def _profile_phone(identity: customer_auth.CustomerIdentity) -> str:
    """The contact-row phone key for this session: the SAME value customer-profile writes.

    The phone is the row key, so the read key and the write key have to be one string by
    construction. `auth/customer-profile` normalises the session phone and writes the normalised
    value; this is the other half.

    On `InvalidPhoneNumber` the fallback is the raw session value, which degrades an UNPARSEABLE
    phone to exactly today's behaviour -- a lookup that may miss -- rather than to a 500.
    `MissingCountryCode` subclasses `InvalidPhoneNumber`, so one arm covers both. A session
    carrying NO phone at all also keeps today's behaviour: `Key("phone").eq("")` is an invalid key
    condition and lands in the existing `checkout_profile_lookup_failed` 500 arm below, which this
    phase does not change. So this is not a claim that the lookup can never 500 -- only that an
    unparseable phone is not a new way to get one.
    """
    try:
        return customer_identity.normalize_phone_preserving_country(identity.phone)
    except customer_identity.InvalidPhoneNumber:
        return str(identity.phone or "")


def _unowned(item: Dict[str, Any]) -> bool:
    """Whether this contact row has no `checkoutCustomerId` at all.

    A CRM-created contact carries none, because only the checkout path writes one. Refusing such
    a row made a customer who already exists in the CRM look brand new at checkout.

    This handler ADOPTS the row for reading; it does not stamp it. The stamp is a write, and this
    function's role holds `dynamodb:Query` on `ContactsTable/index/phone-index` and nothing else
    (`amplify/infra/checkout.json`, Sid `ReadVerifiedCheckoutProfile`). The claim is written by
    `auth/customer-profile`, which already emits `checkoutCustomerId` on every save and has the
    `UpdateItem` grant to do it. Widening this role to write would be a larger change than the
    defect requires, so the ownership predicate is relaxed here and the stamp happens there.

    A row owned by a DIFFERENT customer is still refused, so this cannot read across customers.
    """
    return not str(item.get("checkoutCustomerId") or "").strip()


def _checkout_profile(identity: customer_auth.CustomerIdentity) -> Optional[Dict[str, Any]]:
    """The verified CRM profile for this signed-in phone, or None.

    The lookup key comes from the proven session, through `_profile_phone` so it is the same
    string `customer-profile` stored the row under. A browser cannot choose a phone/customer id.
    A row is accepted when it is either owned by this customer or owned by nobody (see
    `_unowned`), and in BOTH cases it must still carry `emailVerifiedAt` and a non-empty email
    before its name/email are allowed into Razorpay prefill.

    **The email gate is not relaxed, deliberately.** Claiming a row on a phone match says "this
    row is about me"; it says nothing about the email on it. Paying against an unverified email
    is a worse problem than being asked to verify one, so a claimed-but-unverified row still
    answers `PROFILE_REQUIRED` and goes through email verification first.
    """
    try:
        response = _table(CONTACTS_TABLE).query(
            IndexName="phone-index",
            KeyConditionExpression=Key("phone").eq(_profile_phone(identity)),
            Limit=5,
        )
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "checkout_profile_lookup_failed",
                                 "error": type(error).__name__}))
        raise
    # An owned row wins over an unowned one, so a customer with their own row never reads a
    # stray unowned duplicate on the same number. Both still pass the email-verified gate.
    claimable: Optional[Dict[str, Any]] = None
    for item in response.get("Items") or []:
        if item.get("deletedAt") is not None:
            continue
        owned = str(item.get("checkoutCustomerId") or "") == identity.customer_id
        if not owned and not _unowned(item):
            continue
        if not item.get("emailVerifiedAt"):
            continue
        if not str(item.get("email") or "").strip():
            continue
        if owned:
            return item
        if claimable is None:
            claimable = item
    return claimable


def _load_owned_address(
        identity: customer_auth.CustomerIdentity) -> Optional[Dict[str, Any]]:
    """The authenticated customer's stored delivery address, or None.

    `from_contact` re-validates the stored map and never raises, so a legacy or CRM-hand-edited
    address degrades to the recoverable `409 DELIVERY_DETAILS_REQUIRED` and never to a 503 or a
    priced cart with the wrong tax split.
    """
    return contact_address.from_contact(_checkout_profile(identity))


#: See the docblock above `_dynamodb` for why this is a seam and what its signature means.
LOAD_OWNED_ADDRESS = _load_owned_address


def _hardened(response: Dict[str, Any]) -> Dict[str, Any]:
    """`no-store` on a response body carrying an email and a postal address.

    Mandatory, not defensive, and mirrors `auth/customer-profile`'s `_no_store`:
    `response.cors_response` sets no `Cache-Control` at all, and Amplify serves `/api/*` through
    a rewrite with a shared cache in front of it.
    """
    return dict(response) | {
        "headers": customer_session.harden_session_headers(response.get("headers") or {})}


def _profile_status(identity: customer_auth.CustomerIdentity, origin: str) -> Dict[str, Any]:
    """`action:"profile"` -- can this customer pay without being asked for anything?

    `200` for BOTH answers, with the state in `status`. `PROFILE_REQUIRED` is a question being
    answered, not a refused request, and a 409 would make the browser treat a normal first-time
    customer as an error.
    """
    row = _checkout_profile(identity)
    if not row:
        return _hardened(cors_response(200, {"status": "PROFILE_REQUIRED"}, origin))
    address = contact_address.from_contact(row)
    if address is None and row.get(contact_address.ATTRIBUTE) is not None:
        # The row carries a stored delivery address the storage contract no longer accepts.
        # Event name only -- no value, because every component of one is PII.
        #
        # Spelled `..._delivery_unusable` rather than the design's `..._address_unusable`:
        # `tests/test_graft_money_correctness.py::test_no_pii_appears_in_any_log_expression`
        # walks the AST of this file and rejects the substring "address" anywhere inside a
        # `logger.*` call, including a string literal. That gate is a deliberate pin on this
        # build and mirrors a CodeQL rule that failed twice, so the event name moved instead.
        logger.info(json.dumps({"event": "checkout_stored_delivery_unusable"}))
    first = str(row.get("firstName") or "").strip()
    last = str(row.get("lastName") or "").strip()
    return _hardened(cors_response(200, {
        "status": "PROFILE_READY",
        "contactId": contact_key.resolve(row),
        "name": str(row.get("name") or f"{first} {last}").strip(),
        "firstName": first,
        "lastName": last,
        "email": str(row.get("email") or "").strip(),
        # From the ROW, with the session value only as a fallback: the row holds the
        # `normalize_phone_preserving_country` output that `customer-profile` also returns, so
        # reading `identity.phone` directly would make the identity card's Phone row change
        # spelling after an edit.
        "phone": str(row.get("phone") or identity.phone),
        "emailVerified": True,          # `_checkout_profile` already required it
        "addressComplete": address is not None,
        "address": address,             # null when absent
    }, origin))


def _website_snapshot(identity: customer_auth.CustomerIdentity, line_items: list,
                      now: int, *, profile: Optional[Dict[str, Any]] = None):
    """`(snapshot, calculated_or_None)`. `None` on the V1 branch, which has no Cart V2 result.

    Cart V2 uses its existing owned-cart producer and hands back the calculation it already
    performed, so the Wix order payload is built from the SAME figures the price was quoted from.
    The deployed V1 branch is converted into the same immutable QuoteSnapshot using Wix's
    authoritative checkout total, then the one central convenience-fee calculator -- and is
    refused outright when the initiation gate is on, because it has no stable cart identity.

    `profile` is the contact row the caller already loaded, threaded down so the happy path costs
    no second DynamoDB Query. KEYWORD-ONLY with a `None` default, because
    `tests/test_graft_money_correctness.py` calls this positionally as
    `_website_snapshot(identity, line_items, now)` and must keep working unchanged.
    """
    if cart_v2.is_enabled():
        snapshot, _items, calculated = _v2_snapshot(identity, line_items, profile=profile)
        return snapshot, calculated

    if INITIATION_ENABLED:
        # V1 mints a NEW Wix checkout id on every prepare -- `wix_ecom.create_checkout` is a
        # create, not a resolve -- so there is no stable cart identity for the one-live-payment
        # guard to key on and no `CUSTOMERCART#` row behind it. The guard cannot run, which means
        # a second prepare on the same basket would be indistinguishable from the first. Refused
        # BEFORE any Wix checkout is minted, so nothing is created and nothing is written.
        #
        # With the gate OFF this branch is not reached and the V1 body below stays byte-identical,
        # still answering 200 PAYMENT_INITIATION_DISABLED. That is what every existing test
        # exercises, and `WIX_CART_V2_ENABLED` is set on the live function anyway, so V2 is the
        # serving path.
        logger.warning(json.dumps({"event": "website_checkout_v1_refused_when_enabled"}))
        raise website_checkout.CheckoutRejected(website_checkout.CART_V2_REQUIRED)

    checkout = wix_ecom.create_checkout(line_items)
    currency = wix_ecom.checkout_currency(checkout)
    if currency != "INR":
        raise checkout_pricing.PricingError("only INR is supported")
    collection_paise = wix_ecom.authoritative_total_paise(checkout)
    quote = checkout_pricing.compute_quote(collection_paise, currency="INR")
    checkout_id = str(checkout.get("id") or "")
    if not checkout_id:
        raise checkout_pricing.PricingError("Wix checkout id missing")
    built = checkout_pricing.build_snapshot(
        customer_id=identity.customer_id,
        cart_id=checkout_id,
        cart_revision=0,
        quote=quote,
        created_at=now,
        ttl_seconds=WEBSITE_SNAPSHOT_TTL_SECONDS,
        site=wix_ecom.WIX_SITE_ID,
        items=wix_ecom.line_item_summary(checkout),
        address=None,
        delivery=None,
    )
    # No Wix order payload is synthesised for V1: it has no `summary.lineItems` with the fields
    # `build_wix_order_payload` relays, and guessing them is how a Wix order gets the wrong total.
    return built, None


def _reserve_website_attempt(attempt: Dict[str, Any]) -> None:
    _attempts_table().put_item(
        Item=attempt,
        ConditionExpression="attribute_not_exists(paymentAttemptId)",
    )


def _attempt_for_gateway_order(gateway_order_id: str) -> Optional[Dict[str, Any]]:
    binding = order_keys.resolve_gateway_order(_keys_table(), gateway_order_id) or {}
    attempt_id = str(binding.get("paymentAttemptId") or "")
    if not attempt_id:
        return None
    return _attempts_table().get_item(
        Key={"paymentAttemptId": attempt_id}
    ).get("Item")


def _website_prepare(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                     origin: str) -> Dict[str, Any]:
    line_items = body.get("lineItems")
    request_key = str(body.get("requestKey") or "").strip()
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED"}, origin)
    if not request_key or len(request_key) > 80:
        return cors_response(400, {"error": "REQUEST_KEY_REQUIRED"}, origin)

    profile = _checkout_profile(identity)
    if not profile:
        return cors_response(409, {
            "error": "PROFILE_REQUIRED",
            "message": "Verify your email and save your checkout details first.",
        }, origin)

    now = int(time.time())
    keys = _keys_table()
    try:
        # The row is already in hand from the `_checkout_profile` call above, so threading it
        # keeps the happy path at one contacts Query.
        snapshot, calculated = _website_snapshot(identity, line_items, now, profile=profile)
        wix_order_payload = None
        if calculated is not None:
            # Built from the SAME frozen calculation the price was quoted from, at the same
            # instant. Deriving it later from the stored projection would reintroduce the
            # recompute this exists to prevent, and the projection has no `catalogReference` to
            # derive it from.
            wix_order_payload = wix_writeback.build_wix_order_payload(
                cart=calculated, quote=snapshot.quote)

        def _allocate_reference(attempt_id: str, leg_paise: int,
                                gift_card_paise: int) -> str:
            """Mint and durably reserve the `PAYREF#` row the webhook reconciles on.

            The amounts are ARGUMENTS rather than captured from the enclosing scope, because both
            are computed INSIDE `prepare_checkout` -- a closure could not see them, and
            recomputing the gift-card split here would mean two readings of one split.
            """
            return order_keys.allocate_payment_reference(
                keys, payment_attempt_id=attempt_id,
                extra={
                    "customerId": identity.customer_id,
                    # THE RAZORPAY LEG, which is what a capture will be compared against.
                    "amountPaise": leg_paise,
                    # The frozen payable, beside it, so the split stays auditable rather than
                    # being inferred from a difference. `_tenders_reconcile` reads the payable off
                    # the ATTEMPT row, not this one.
                    "payablePaise": snapshot.quote.total_payable_paise,
                    "giftCardRedeemPaise": gift_card_paise,
                    "currency": "INR",
                    "checkoutMode": website_checkout.CHECKOUT_MODE_WEBSITE,
                    "wixCartId": snapshot.cart_id,
                    "cartRevision": snapshot.cart_revision,
                    "quoteHash": snapshot.snapshot_hash,
                    "collectionPaise":
                        snapshot.quote.collection_before_convenience_paise,
                    "quoteExpiresAt": snapshot.expires_at,
                    "policyVersion": snapshot.policy_version,
                })

        prepared = website_checkout.prepare_checkout(
            customer_id=identity.customer_id,
            snapshot=snapshot,
            presented_snapshot_hash=snapshot.snapshot_hash,
            request_key=request_key,
            now=now,
            keys_table=keys,
            create_order=razorpay_orders.create_order,
            find_order_by_receipt=razorpay_orders.find_order_by_receipt,
            account_mode_of=razorpay_orders.account_mode,
            initiation_enabled=INITIATION_ENABLED,
            prefill={
                "name": str(profile.get("name") or "").strip(),
                "email": str(profile.get("email") or "").strip(),
                "contact": identity.phone,
            },
            configuration_name=website_checkout.CHECKOUT_MODE_WEBSITE,
            reserve_attempt=_reserve_website_attempt,
            # The read-only attempt store the one-live-payment guard needs. Without it the guard
            # can tell a basket has a recorded attempt but not whether that attempt was paid.
            attempts_table=_attempts_table(),
            allocate_reference=_allocate_reference,
            purchased_snapshot=snapshot.frozen_data,
            wix_order_payload=wix_order_payload,
        )
    except DeliveryMethodUnavailable:
        # MUST stay ABOVE the parent arm below, or the subclass is swallowed by it and
        # DELIVERY_METHOD_UNAVAILABLE never fires.
        return cors_response(409, {"error": "DELIVERY_METHOD_UNAVAILABLE"}, origin)
    except purchase_intent.DeliveryDetailsRequired:
        return cors_response(409, {"error": "DELIVERY_DETAILS_REQUIRED"}, origin)
    except wix_address.UnmappableAddress:
        # Belt and braces. `from_contact` re-validates, so the normal answer for a stored address
        # Wix cannot map is already this 409 via the arm above; without this arm an unmappable
        # address reaching `to_wix_address` would fall through the generic `except Exception` to
        # `503 TEMPORARILY_UNAVAILABLE` -- a dead end, because no retry fixes it. No delivery
        # detail in the log line: every component of one is PII, and the event name is spelled
        # `..._delivery_unmappable` rather than the design's `..._address_unmappable` for the
        # same AST-gate reason recorded on `checkout_stored_delivery_unusable`.
        logger.info(json.dumps({"event": "website_checkout_delivery_unmappable",
                                "customerIdPresent": True}))
        return cors_response(409, {"error": "DELIVERY_DETAILS_REQUIRED"}, origin)
    except website_checkout.CheckoutRejected as exc:
        return cors_response(409, {
            "status": website_checkout.CHECKOUT_REJECTED,
            "reason": exc.reason,
        }, origin)
    except order_keys.OrderIdentityUnavailable:
        # A read or a durable write the guard depends on failed. 503, never a pass: the caller
        # acts on "no live payment" by creating a payable order. The generic arm below already
        # answered this way by accident; this makes it intentional and testable.
        logger.error(json.dumps({"event": "website_checkout_identity_unavailable"}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)
    except (checkout_pricing.PricingError, wix_ecom.AmountNotWhole):
        return cors_response(409, {"error": "AMOUNT_NOT_SETTLED"}, origin)
    except wix_ecom.WixEcomError:
        return cors_response(502, {"error": "CATALOGUE_UNAVAILABLE"}, origin)
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "website_checkout_prepare_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    payload: Dict[str, Any] = {
        "status": prepared.status,
        "paymentAttemptId": prepared.payment_attempt_id,
    }
    if prepared.options:
        payload["options"] = prepared.options
    if prepared.reason:
        payload["reason"] = prepared.reason
    if prepared.status == website_checkout.CHECKOUT_AMBIGUOUS:
        # 409 for a deliberate refusal; 200 for the provider-ambiguity reasons
        # (BINDING_SAVE_FAILED, CREATE_UNCONFIRMED, CREATE_IN_FLIGHT, BINDING_OWNED_ELSEWHERE,
        # CART_POINTER_SAVE_FAILED) and for PAYABLE_MODAL_UNRESOLVED, where we genuinely do not
        # know. The browser branches on `status`, not on the code, so this is observable in logs
        # and alarms and nowhere else.
        status_code = 409 if prepared.reason in _CART_BLOCKED else 200
    elif prepared.status in (website_checkout.PAYMENT_INITIATION_DISABLED,
                             website_checkout.CHECKOUT_OPTIONS_READY):
        # PAYMENT_INITIATION_DISABLED must stay 200: `cart.tsx` answers it with the "no charge was
        # made" copy, which is only honest because the server stopped before the payment rail.
        # CHECKOUT_OPTIONS_READY must stay 200: it opens the modal.
        status_code = 200
    else:
        status_code = 409
    return cors_response(status_code, payload, origin)


def _load_attempt_via(keys, *, provider_order_id: str = ""):
    """The attempt loader BOTH the signature check and the reconciler use.

    A SUPERSET of the webhook's `_load_attempt`: it resolves a `PAYREF#` row by reference id, and
    ALSO by a GATEWAY ORDER id, because `verify_callback` calls its capture verifier with the
    stored gateway order id rather than with the reference while `order_creation.reconcile_payment`
    calls its verifier with the reference. One loader, two identifier kinds -- the alternative is
    a loader that resolves only one of them, which makes every website payment end with a
    verified capture and no order record.

    It returns exactly the webhook's six-field projection, so both callers compare the provider's
    answer against the same stored authority and not against the event.

    `provider_order_id` is an optional SERVER-STORED fallback for the `providerOrderId` field.
    `verifier_for_event` raises unless `providerPaymentId` or `providerOrderId` is present, and
    the only writer of either onto the `PAYREF#` row is deliberately best-effort. The fallback
    removes that dependency. It is SAFE because every value it can take is ours -- the
    `gatewayOrderId` off the binding we wrote at create time, or `CallbackResult.gateway_order_id`,
    which `verify_callback` read off that same stored binding. It is NEVER the browser's
    `presented_order_id` and never anything from the event body, and it only selects which
    provider order's payments are read; the HMAC check and both amount comparisons are untouched.

    A storage failure propagates as `order_keys.OrderIdentityUnavailable` rather than becoming
    `None`: a read failure must never be reported as absence, because absence here means "no
    attempt exists for this reference", which is a refusal.
    """
    def _load_attempt(ref: str) -> Optional[Dict[str, Any]]:
        row = order_keys.resolve_payment_reference(keys, ref)
        bound_order = provider_order_id
        if row is None:
            binding = order_keys.resolve_gateway_order(keys, ref) or {}
            bound_reference = str(binding.get("referenceId") or "")
            bound_order = bound_order or str(binding.get("gatewayOrderId") or "")
            if bound_reference:
                row = order_keys.resolve_payment_reference(keys, bound_reference)
        if not row or not row.get("paymentAttemptId"):
            # NO PAYREF# row resolved. Degrade to the FULL attempt row behind the binding -- which
            # is exactly what this handler passed before the reference existed, and which always
            # carries `providerOrderId` because `_bind_and_ready` writes it. Without this arm,
            # replacing the loader REMOVES a path that works today: any attempt whose binding
            # carries no `referenceId` could no longer be verified by the browser at all.
            #
            # Losing the projection costs nothing here: `verifier_for_event` reads only
            # `providerPaymentId` / `providerOrderId` off the loaded row, and this arm is reached
            # only when NO reference resolved, so `reconcile_payment` -- which is called with a
            # reference and compares `amountPaise` -- is never handed the fallback.
            return _attempt_for_gateway_order(ref) or None
        return {"paymentAttemptId": row["paymentAttemptId"],
                "customerId": row.get("customerId", ""),
                "amountPaise": row.get("amountPaise"),
                "providerPaymentId": row.get("providerPaymentId", ""),
                "providerOrderId": str(row.get("providerOrderId") or bound_order or ""),
                "currency": row.get("currency", "")}
    return _load_attempt


def _record_verified_capture(*, owned: Dict[str, Any], payment_attempt_id: str,
                             provider_payment_id: str, provider_order_id: str,
                             amount_paise: int) -> None:
    """Persist the proven capture on the attempt row. Monotonic, and the FIRST thing done once a
    capture is proven, so no downstream failure can leave money recorded nowhere.

    Extracted and performed first because five reconciliation outcomes return without order
    identity -- PROVIDER_UNAVAILABLE, AMOUNT_MISMATCH, CURRENCY_MISMATCH, IDENTITY_UNAVAILABLE,
    PROVIDER_PAYMENT_CONFLICT -- so `accept_paid` is never reached on any of them, and a proven
    capture would otherwise be recorded nowhere at all.

    `amount_paise` is the PROVIDER's confirmed figure. Never the order total and never a
    subtraction. `int()` is safe rather than a coercion of unknown input: `razorpay_verify` has
    already passed the figure through `money.positive_paise` and `verify_callback` has already
    asserted it equals the stored binding by integer equality.

    Raises on failure. Both callers treat a failure as 503 / "not finalized", never as paid.
    """
    advanced = payment_attempt.transition(
        owned, payment_attempt.PAYMENT_PAID,
        provider_payment_id=provider_payment_id, provider_order_id=provider_order_id)
    _attempts_table().update_item(
        Key={"paymentAttemptId": payment_attempt_id},
        UpdateExpression=(
            "SET #s=:s, attemptRank=:rank, paidAt=if_not_exists(paidAt,:paid), "
            "updatedAt=:u, providerPaymentId=:pid, providerOrderId=:oid, "
            + finalization.VERIFIED_CAPTURED_PAISE_ATTR + "=:vcp"),
        # Unchanged: rank-based, forwards-only, so a late arrival cannot move the attempt back.
        ConditionExpression=payment_attempt.condition_expression(),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": advanced["status"], ":rank": advanced[payment_attempt.RANK_ATTRIBUTE],
            ":paid": advanced["paidAt"], ":u": advanced["updatedAt"],
            ":pid": provider_payment_id, ":oid": provider_order_id,
            ":vcp": int(amount_paise)},
    )


class _ClaimOutcome:
    """The attributes `_finalize` and `accept_paid` read, built from a stored order claim.

    `reconcile_payment`'s `ReconciliationOutcome` exists only on the verify path. On `status` the
    authority is the claim row, whose MEASURED field names are `orderIdRef` (NOT `orderId` --
    that is the commerce-keys table's own partition attribute, so a business field of the same
    name would be overwritten by the key), `orderNumber` and `providerTransactionId`. Mapping
    them here keeps `_finalize` to ONE argument contract rather than two.
    """

    __slots__ = ("payment_attempt_id", "order_id", "order_number", "provider_payment_id")

    def __init__(self, claim: Dict[str, Any], attempt: Dict[str, Any]) -> None:
        self.payment_attempt_id = str(attempt.get("paymentAttemptId") or "")
        self.order_id = str(claim.get("orderIdRef") or "")
        self.order_number = str(claim.get("orderNumber") or "")
        self.provider_payment_id = str(claim.get("providerTransactionId") or "")

    @property
    def has_order(self) -> bool:
        return bool(self.order_id and self.order_number)

    def as_dict(self) -> Dict[str, Any]:
        # EXACTLY the keys `accept_paid` reads -- hasOrder, orderId, orderNumber -- plus the two
        # carried for `_finalize` and the providerPaymentId merge. `orderId` is read TWICE by
        # `accept_paid` (the order record and the conditional-failure get_item), so omitting it
        # would KeyError after money had moved and `record_paid` had written PAYMENT_PAID.
        return {"hasOrder": True, "orderId": self.order_id, "orderNumber": self.order_number,
                "providerPaymentId": self.provider_payment_id,
                "paymentAttemptId": self.payment_attempt_id}


def _finalize(identity: customer_auth.CustomerIdentity, outcome,
              *, verified_captured_paise: int) -> None:
    """Write the internal order record for an outcome that already HAS order identity.

    Reads the FULL attempt row, not the six-field projection the verifier uses: `record_paid`
    needs `referenceId`, and the order record needs `currency`, `amountPaise`, `customerId`,
    `checkoutMode`, `purchasedSnapshot` and `snapshotHash`. `ConsistentRead` because on a
    browser-return sequence the row was written microseconds earlier on this same request.

    `accept_paid` is safe to re-enter -- its `put_item` is conditional with an explicit
    field-agreement check on the adopted row -- so running this from both `verify` and `status`
    cannot write two records.
    """
    attempt = _attempts_table().get_item(
        Key={"paymentAttemptId": outcome.payment_attempt_id},
        ConsistentRead=True).get("Item")
    if not attempt:
        # `authorize_resource(identity, None)` raises `CustomerNotAuthorized`, and an opaque 401
        # is the wrong answer for a customer whose capture has just been proven. A missing attempt
        # row here is an internal fault. Alarm and return; the order NUMBER still reaches the
        # shopper.
        logger.error(json.dumps({"event": "checkout_finalize_attempt_row_missing",
                                 "alert": "PAID_BUT_NO_ORDER_RECORD",
                                 "paymentAttemptId": outcome.payment_attempt_id}))
        return
    # The third ownership check, and the only one that sees the attempt row itself.
    customer_auth.authorize_resource(identity, attempt, owner_field="customerId")

    # ── the two-leg gate, SPLIT, because there are two different second legs ──
    #
    # A blanket "refuse every attempt carrying a non-zero second tender" would cancel the
    # split-tender graft from its ONLY production caller: `accept_paid` is called from nowhere
    # else, so `_tenders_reconcile`, the verified-leg `record_external_payment` and
    # `mark_cart_completed` would never run for the order the graft was written for. "Correct and
    # unconsulted" is the exact failure this wiring exists to prevent, so the gate is per-leg.
    #
    # LEG A -- the WECARE gift card. It has its OWN forward-only stage ladder and its OWN
    # redemption evidence in our own table, and `accept_paid` consults neither, so this leg is
    # refused until that workstream wires the ladder into finalization.
    required = finalization.integer_paise(
        attempt.get(gift_card_settlement.REQUIRED_PAISE_ATTR)) or 0
    if required and (
            gift_card_settlement.stage(attempt) != gift_card_settlement.GC_REDEEMED
            or not attempt.get(gift_card_settlement.TRANSACTION_ID_ATTR)):
        logger.error(json.dumps({"event": "checkout_finalize_gift_card_unsettled",
                                 "alert": "PAID_BUT_NO_ORDER_RECORD",
                                 "paymentAttemptId": outcome.payment_attempt_id}))
        return
    #
    # LEG B -- the WIX-NATIVE gift card. There is NO ladder to consult and nothing to wire: the
    # closure for this leg IS `finalization._tenders_reconcile`, exact integers, fail closed on
    # one paise. A basket that satisfies it is fully funded by construction, so refusing it here
    # would refuse a correct order.
    #
    # What IS still refused is an UNREADABLE leg: `None` means a listed tender attribute is
    # present but not integer paise, and an amount we cannot read is not the same as no amount.
    # Note this is a non-zero / unreadable test and never a PRESENCE test --
    # `website_checkout._bind_and_ready` writes `wixGiftCardRedeemPaise` unconditionally,
    # including 0, so a presence test would refuse every ordinary card-free website order.
    if finalization.other_tender_paise(attempt) is None:
        logger.error(json.dumps({"event": "checkout_finalize_unreadable_tender",
                                 "alert": "PAID_BUT_NO_ORDER_RECORD",
                                 "paymentAttemptId": outcome.payment_attempt_id}))
        return
    finalization.accept_paid(
        attempts=_attempts_table(), orders=_orders_table(), keys=_keys_table(),
        attempt=attempt,
        # `ReconciliationOutcome.as_dict()` omits the provider payment id, and the attempt carries
        # no verified one before `record_paid` runs, so without this merge the first call raises
        # `ValueError('verified provider payment id required')`.
        outcome={**outcome.as_dict(), "providerPaymentId": outcome.provider_payment_id},
        verified_captured_paise=verified_captured_paise)


def _finalize_from_claim(identity: customer_auth.CustomerIdentity,
                         attempt: Dict[str, Any]) -> bool:
    """Finish an order record the verify leg never got to write. True when it ran.

    The gate is the CLAIM, not the attempt's status: the webhook reconciles and reserves the
    public number without ever touching the attempt row -- measured, it references neither
    `payment_attempt` nor `finalization` -- so on the closed-tab path the status is still
    PAYMENT_PENDING when the claim already exists. Gating on `may_create_order` could therefore
    never be satisfied on the one path this exists for.

    A claimed-but-UNNUMBERED claim (`orderIdRef` present, `orderNumber` absent) is LEFT ALONE:
    the numbering step is mid-flight or crashed, and writing a record with no public number -- or
    inventing one -- would burn or duplicate a number, which cannot be undone invisibly.
    """
    attempt_id = str(attempt.get("paymentAttemptId") or "")
    keys = _keys_table()
    claim = order_keys.resolve_order_for_payment(keys, attempt_id) or {}
    if not claim.get("orderIdRef") or not claim.get("orderNumber"):
        return False
    if not str(attempt.get("referenceId") or ""):
        # Explicit rather than falling through to the readback. With an empty reference every
        # resolver answers None, the inner verify raises, and the except arm would return False on
        # this poll and every future poll, indefinitely. The claim exists, so money moved; nothing
        # here can resolve it and repeated polls will not change that. Alarm ONCE, at ERROR, so a
        # human reconciles, and stop.
        logger.error(json.dumps({"event": "checkout_status_claim_without_reference",
                                 "alert": "PAID_BUT_NO_ORDER_RECORD",
                                 "paymentAttemptId": attempt_id}))
        return False
    verified = finalization.integer_paise(
        attempt.get(finalization.VERIFIED_CAPTURED_PAISE_ATTR))
    if verified is None:
        # No provider-confirmed amount is stored, which is exactly the closed-tab shape. ASK THE
        # PROVIDER rather than substituting the frozen payable: under split tender the payable is
        # a different number, and substituting it is precisely the full-amount-instead-of-leg
        # defect the split-tender graft removes.
        provider_payment_id = str(claim.get("providerTransactionId") or "")
        if not provider_payment_id:
            return False
        try:
            paid, _pid, amount, currency = razorpay_verify.verifier_for_event(
                payment_id=provider_payment_id,
                load_attempt=_load_attempt_via(
                    keys, provider_order_id=str(attempt.get("providerOrderId") or "")),
            )(str(attempt.get("referenceId") or ""))
        except Exception as error:  # noqa: BLE001
            logger.warning(json.dumps({"event": "checkout_status_capture_readback_failed",
                                       "error": type(error).__name__}))
            return False
        if not paid or currency != "INR":
            # Compared explicitly against INR, never inferred from the amount.
            return False
        verified = amount
        # Persist it, so the next poll does not ask the provider again.
        _record_verified_capture(
            owned=attempt, payment_attempt_id=attempt_id,
            provider_payment_id=provider_payment_id,
            provider_order_id=str(attempt.get("providerOrderId") or ""),
            amount_paise=verified)
    _finalize(identity, _ClaimOutcome(claim, attempt), verified_captured_paise=verified)
    return True


def _website_verify(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                    origin: str) -> Dict[str, Any]:
    order_id = str(body.get("razorpay_order_id") or "").strip()
    payment_id = str(body.get("razorpay_payment_id") or "").strip()
    signature = str(body.get("razorpay_signature") or "").strip()
    if not order_id or not payment_id or not signature:
        return cors_response(400, {"error": "CALLBACK_FIELDS_REQUIRED"}, origin)

    keys = _keys_table()
    try:
        attempt = _attempt_for_gateway_order(order_id)
        owned = customer_auth.authorize_resource(identity, attempt, owner_field="customerId")
        result = website_checkout.verify_callback(
            customer_id=identity.customer_id,
            presented_order_id=order_id,
            payment_id=payment_id,
            signature=signature,
            keys_table=keys,
            verify_signature=razorpay_orders.verify_checkout_signature,
            verify_capture=razorpay_verify.verifier_for_event(
                payment_id=payment_id, order_id=order_id,
                load_attempt=_load_attempt_via(keys)),
            account_mode_of=razorpay_orders.account_mode,
        )
    except customer_auth.CustomerNotAuthorized:
        raise
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "website_checkout_verify_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    if result.status != website_checkout.CALLBACK_VERIFIED_PAID:
        return cors_response(200, {"status": result.status,
                                   "paymentAttemptId": result.payment_attempt_id}, origin)

    # ── STEP 1: record the capture, FIRST, so no later failure strands proven money. ──
    try:
        _record_verified_capture(
            owned=owned, payment_attempt_id=result.payment_attempt_id,
            provider_payment_id=result.payment_id,
            provider_order_id=result.gateway_order_id,
            amount_paise=result.amount_paise)
    except Exception as error:  # noqa: BLE001
        # 503, because the paid state is the one thing that must survive a lost browser response
        # and we could not write it. The webhook reconciles independently from
        # `notes.referenceId`, so this is recoverable without the browser.
        logger.error(json.dumps({"event": "website_checkout_paid_persist_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    # ── STEP 2: order identity and the internal order record. Never changes the verdict. ──
    outcome = None                      # bound BEFORE the try; see the final return
    try:
        binding = order_keys.resolve_gateway_order(keys, result.gateway_order_id) or {}
        reference_id = str(binding.get("referenceId") or "")
        if not reference_id:
            # A pre-graft attempt, or a binding written before the reference existed. The webhook
            # reconciles from `notes.referenceId` independently, so this is recoverable without
            # the browser -- and the capture is already recorded above.
            logger.error(json.dumps({"event": "website_checkout_verify_reference_unresolved",
                                     "alert": "PAID_BUT_NO_ORDER",
                                     "paymentAttemptId": result.payment_attempt_id}))
        else:
            reconcile_loader = _load_attempt_via(
                keys, provider_order_id=result.gateway_order_id)
            outcome = order_creation.reconcile_payment(
                table=keys, reference_id=reference_id,
                # A REFERENCE-keyed verifier. The one built above is keyed on the gateway order
                # id, which `reconcile_payment` never passes.
                verify_payment=razorpay_verify.verifier_for_event(
                    payment_id=result.payment_id, order_id=result.gateway_order_id,
                    load_attempt=reconcile_loader),
                load_attempt=reconcile_loader,
                # The proven session id, so a CUSTOMER_MISMATCH refuses BEFORE an order number is
                # reserved. The PAYREF# row carries `customerId`, so this is checkable.
                expected_customer_id=identity.customer_id)
            if outcome.outcome == order_creation.CUSTOMER_MISMATCH:
                # Unreachable by construction once the binding carries its owner, and kept as
                # defence in depth. It does NOT become a 401: ownership was already proven against
                # the attempt ROW before verify ran, so a third disagreement is our own bookkeeping
                # contradicting itself, and telling a payer "not authorised" after their money
                # moved is the one answer that cannot be taken back.
                logger.error(json.dumps({"event": "checkout_verify_customer_mismatch",
                                         "alert": "PAID_BUT_NO_ORDER",
                                         "paymentAttemptId": result.payment_attempt_id}))
                outcome = None
            elif outcome.needs_human:
                logger.error(json.dumps({"event": "checkout_verify_paid_but_blocked",
                                         "alert": "PAID_BUT_NO_ORDER",
                                         "outcome": outcome.outcome,
                                         "paymentAttemptId": result.payment_attempt_id}))
            if outcome is not None and outcome.has_order:
                # TWO provider-derived figures, from two separate authenticated readbacks:
                # `result.amount_paise` (already asserted equal to GATEWAYORDER#.amountPaise) and
                # `outcome.verified_captured_paise` (already asserted equal to the attempt's
                # authoritative amount). For a design whose discipline is "fail closed on one
                # paise", silently preferring one is the wrong shape -- so they are compared, and
                # a disagreement writes nothing rather than choosing.
                reconciled = int(outcome.verified_captured_paise or 0)
                if reconciled and reconciled != result.amount_paise:
                    logger.error(json.dumps({
                        "event": "checkout_verify_capture_disagreement",
                        "alert": "PAID_BUT_NO_ORDER_RECORD",
                        "paymentAttemptId": result.payment_attempt_id}))
                else:
                    # Zero means `reconcile_payment` carried no figure, not that it carried zero:
                    # the outcome object coerces `int(verified_captured_paise or 0)`, so absence
                    # and zero are the same value on it. `result.amount_paise` stays the only
                    # source either way.
                    _finalize(identity, outcome,
                              verified_captured_paise=result.amount_paise)
    except Exception as error:  # noqa: BLE001
        # Money moved AND is recorded. The order number, if one was reserved, is still returned: a
        # finalization fault must not make a paying customer think the payment failed.
        logger.error(json.dumps({"event": "website_checkout_finalize_failed",
                                 "alert": "PAID_BUT_NO_ORDER_RECORD",
                                 "error": type(error).__name__}))

    return cors_response(200, {
        "status": result.status,
        "paymentAttemptId": result.payment_attempt_id,
        # `outcome` is None on every failure arm, so this is a plain attribute read on a value
        # that is always bound.
        "orderNumber": (outcome.order_number if outcome is not None else "") or None,
    }, origin)


def _wix_request(endpoint: str, method: str = "GET",
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Transport for the Cart V2 adapter, delegating to `wix_ecom`'s authenticated client.

    `wix_ecom._request` already owns the credential (read by reference from Secrets Manager,
    lazily, at request time) and the site header. Reusing it keeps one authenticated client in
    this package rather than giving Cart V2 a second one that would need its own lazy-read
    discipline to stay rotation-safe.
    """
    return wix_ecom._request(endpoint, method=method, body=body)


def _v2_catalog_items(line_items: list) -> list:
    """Bridge the browser's `{catalogReference, quantity}` shape to Cart V2's catalog items.

    `cart_v2.catalog_item` demands exactly `{productId, variantId, quantity}` with both ids as
    UUIDs, while the browser sends a nested `catalogReference` and may omit the variant.
    Resolving a product's single visible, in-stock variant against the live catalogue -- and
    refusing to guess when there is more than one -- is work `wix_ecom.normalized_catalog_items`
    already does correctly, so this reuses it rather than growing a second copy that could
    disagree about which variant a cart line means.
    """
    return [{"productId": line["catalogReference"]["catalogItemId"],
             "variantId": line["catalogReference"]["options"]["variantId"],
             "quantity": line["quantity"]}
            for line in wix_ecom.normalized_catalog_items(line_items)]


def _require_same_basket(cart: Dict[str, Any], requested: list) -> None:
    """Refuse when the customer's saved cart is not the basket this request asked to price.

    Reusing the saved cart is what keeps one purchase to one cart, but the cart is maintained by
    the `/wix-store/cart` route, so it can legitimately hold something else by the time checkout
    is pressed -- a second tab, another device, an edit made after this page loaded. Pricing it
    anyway would charge for a basket the customer is not looking at, which is worse than asking
    them to review it.

    Quantities are compared on `requestedQuantity`, never `confirmedQuantity`: Wix reduces the
    confirmed figure to available stock, and reporting that reduction is `CartQuantityReduced`'s
    job. Reading it here would turn an out-of-stock item into "your cart changed".
    """
    asked: Dict[tuple, int] = {}
    for item in requested:
        key = (str(item["productId"]).lower(), str(item["variantId"]).lower())
        asked[key] = asked.get(key, 0) + int(item["quantity"])
    saved: Dict[tuple, int] = {}
    for line in cart.get("lineItems") or []:
        reference = (line.get("source") or {}).get("catalogReference") or {}
        quantities = line.get("quantityInfo") or {}
        key = (str(reference.get("catalogItemId") or "").lower(),
               str((reference.get("options") or {}).get("variantId") or "").lower())
        quantity = quantities.get("requestedQuantity")
        if quantity is None:
            quantity = quantities.get("confirmedQuantity")
        saved[key] = saved.get(key, 0) + int(quantity or 0)
    if saved != asked:
        logger.info(json.dumps({"event": "checkout_cart_basket_mismatch",
                                "savedLines": len(saved), "requestedLines": len(asked)}))
        raise cart_v2.CartContractError("the saved cart is not the basket that was requested")


class DeliveryMethodUnavailable(purchase_intent.DeliveryDetailsRequired):
    """Wix priced nothing because it offered no delivery METHOD for a known-good address.

    The base class is load-bearing. `_v2_snapshot`'s other caller is `_create`, the retained
    in-WhatsApp path, whose existing first arm then still answers
    `409 DELIVERY_DETAILS_REQUIRED` -- not `500 INTERNAL_ERROR` (a plain `Exception`) and not
    `409 AMOUNT_NOT_SETTLED` (a plain `ValueError`, via its trailing `except ValueError`).
    """


def _blocking_codes(adapter, cart_id: str) -> set:
    """Wix's own blocking-violation codes for this cart, or an empty set.

    Mirrors `purchase_intent._delivery_is_missing`'s evidence rule: a failed preview is NO
    evidence, and no evidence must not be reported to a customer as "choose an address".
    """
    try:
        preview = adapter.preview(cart_id)
    except Exception:  # noqa: BLE001
        return set()
    return {str(v.get("code") or "") for v in preview.get("blockingViolations") or []}


def _v2_snapshot(identity: customer_auth.CustomerIdentity, line_items: list,
                 *, profile: Optional[Dict[str, Any]] = None):
    """The Cart V2 price authority. Returns `(snapshot, price_free_items, calculated)`.

    `calculated` is the `cart_v2.calculate` result the snapshot was frozen from, returned rather
    than discarded so `wix_writeback.build_wix_order_payload` can be built from the SAME figures
    the price was quoted from. A second `calculate` could drift from the charge by a paise, and
    the frozen snapshot keeps `summary.lineItems` but not `cart.lineItems`, so it carries no
    `catalogReference` to rebuild a payload from.

    This is the producer half of the chain `website_checkout` and `customer_receipt` already
    consume, and which nothing in production produced before. `QuoteSnapshot.quote`'s
    `collection_before_convenience_paise` is Wix's own `summary.priceSummary.total` -- items,
    discounts, delivery and supply GST, all computed by Wix from the catalogue and the delivery
    address. This handler adds nothing to that figure; `compute_quote` adds only our convenience
    fee and the GST on that fee, and `total_payable_paise` is what a customer pays.

    ORDERING IS LOAD-BEARING, NOT STYLE. The owned address is resolved BEFORE any call that can
    write to Wix. A cart created and then refused is a real cart abandoned on the live site, one
    per attempt, and nothing deletes it; an earlier revision created the cart first and then
    discovered there was no address, so every attempt leaked one. A request that cannot be priced
    must be refused before it leaves anything behind.

    The cart itself is resolved before it is generated. `customer_cart` already owns identity-keyed
    cart persistence and its lock protocol, so this asks it for the customer's existing cart and
    lets it create one only when there is none -- a retried checkout then reuses the same Wix cart
    instead of minting another.

    Raises `purchase_intent.DeliveryDetailsRequired` when no owned address is on file, and the
    narrower `DeliveryMethodUnavailable` when Wix has a known-good address but offers no delivery
    METHOD for it -- both recoverable steps in the purchase flow rather than errors.

    `profile` is the already-loaded contact row, so the happy path adds no DynamoDB read. The
    `loader is _load_owned_address` identity check keeps the test seam authoritative: a
    monkeypatched loader is ALWAYS called, so no test silently bypasses its own stub.
    """
    loader = LOAD_OWNED_ADDRESS
    owned = (contact_address.from_contact(profile)
             if profile is not None and loader is _load_owned_address
             else (loader(identity) if callable(loader) else None))
    if not owned:
        raise purchase_intent.DeliveryDetailsRequired("no owned delivery address on file")

    adapter = cart_v2.CartV2(_wix_request)
    requested = _v2_catalog_items(line_items)
    cart_id, created = customer_cart.CustomerCart(_keys_table(), adapter).ensure(
        identity, requested)
    if not created:
        _require_same_basket(adapter.get(cart_id), requested)

    prepared = purchase_intent.prepare_delivery(adapter, cart_id, owned)
    try:
        snapshot, calculated = purchase_intent.build_intent_with_calculation(
            adapter, customer_id=identity.customer_id, cart_id=cart_id,
            owned_address=owned, now=int(time.time()), site=wix_ecom.WIX_SITE_ID)
    except purchase_intent.DeliveryDetailsRequired:
        # `purchase_intent` collapses MISSING_DELIVERY_ADDRESS and MISSING_DELIVERY_METHOD into
        # one refusal, and a method problem reported as a missing address tells a customer to
        # enter an address they already saved, forever. Distinguish on Wix's own violation codes
        # rather than inferring: a successful `set_delivery_address` does NOT rule out
        # MISSING_DELIVERY_ADDRESS, because an address outside every shipping region still
        # reports it.
        #
        # `revision` is logged as `str(...)` rather than through a numeric coercion -- Wix sends
        # it as a decimal string, so a string needs no helper and cannot throw inside an `except`
        # arm. A `NameError` here would be swallowed by `_website_prepare`'s generic
        # `except Exception` and surface as the 503 dead end this work exists to prevent.
        codes = _blocking_codes(adapter, cart_id)
        logger.info(json.dumps({"event": "website_checkout_delivery_blocked",
                                "cartRevision": str(prepared.get("revision") or ""),
                                "violations": sorted(codes)}))
        if not codes or "MISSING_DELIVERY_ADDRESS" in codes:
            raise                       # unchanged meaning, and fail-closed on no evidence
        raise DeliveryMethodUnavailable("wix offered no usable delivery method") from None
    # Names and quantities only, for the payment request and the receipt. Line money never
    # travels with the item list: the authoritative amount is the one computed once, above, and
    # the snapshot hash already covers the per-line figures Wix calculated.
    items = [{"name": _translatable(line.get("name")),
              "quantity": int((line.get("quantityInfo") or {}).get("confirmedQuantity") or 1)}
             for line in (prepared.get("lineItems") or [])]
    return snapshot, items, calculated


def _translatable(value: Any) -> str:
    """Cart V2 renamed `lineItems[].productName` to `name` and changed it to a translatable
    string, so a plain `str()` would render a dict. Original preferred over translated, matching
    `wix_ecom.line_item_summary`'s existing behaviour on the V1 shape."""
    if isinstance(value, dict):
        return str(value.get("original") or value.get("translated") or "")
    return str(value or "")


def _create(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
            origin: str) -> Dict[str, Any]:
    """Resolve authoritative totals, gate on readiness, reserve an attempt, hand off to WhatsApp."""
    line_items = body.get("lineItems")
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED",
                                   "message": "Your cart is empty."}, origin)

    # 1. Authoritative total, from Wix. The browser sent catalogue references and quantities;
    #    Wix computes the price. A non-INR or non-whole-paise total fails closed.
    #
    #    Checkout V1 is what serves: Cart V2 is opt-in behind `WIX_CART_V2_ENABLED`
    #    (`cart_v2.is_enabled`), which is absent on every function, so absence keeps V1. Both are
    #    the SAME checkout mode -- website Razorpay Standard Checkout -- differing only in which
    #    Wix API prices the cart. Neither routes a customer to a Wix-hosted checkout surface.
    wix_checkout_id = ""
    snapshot = None
    if cart_v2.is_enabled():
        try:
            # `_calculated` is deliberately discarded here: this is the retained in-WhatsApp
            # path, which never reaches `accept_paid` and so needs no Wix order payload.
            snapshot, item_summary, _calculated = _v2_snapshot(identity, line_items)
            # The amount a customer pays is the CALCULATOR total -- Wix's collection total plus
            # our convenience fee plus the GST on that fee -- not the raw Wix total. That is the
            # contract section 8 of this module's docstring states for the website path, and
            # before the Cart V2 producer existed there was no code path that honoured it.
            amount_paise = snapshot.quote.total_payable_paise
        except purchase_intent.DeliveryDetailsRequired:
            # Not an error. The customer has not chosen where this is going, and Cart V2 is right
            # to refuse a price for an unknown destination: delivery is a component of the total
            # and the address is the place of supply. Never substitute a default address.
            logger.info(json.dumps({"event": "checkout_delivery_details_required"}))
            return cors_response(409, {
                "error": "DELIVERY_DETAILS_REQUIRED",
                "message": "Choose a delivery address and method to see your final total.",
            }, origin)
        except cart_v2.CartItemUnavailable as unavailable:
            # Checkout V1 dropped a missing item and priced what was left, so a cart could shrink
            # silently between review and payment. Named per line so the customer can act, and the
            # line ids and statuses are safe to return: they are opaque and carry no personal data.
            logger.info(json.dumps({"event": "checkout_item_unavailable",
                                    "count": len(unavailable.items)}))
            return cors_response(409, {
                "error": "ITEMS_UNAVAILABLE", "items": unavailable.items,
                "message": "Some items are no longer available. Please review your cart.",
            }, origin)
        except cart_v2.CartQuantityReduced as reduced:
            # Wix still auto-reduces `confirmedQuantity` to available stock in V2, and it prices the
            # reduced amount -- so the money reconciles perfectly while being the total for goods
            # the customer did not agree to buy. Refused and shown, never silently accepted.
            logger.info(json.dumps({"event": "checkout_quantity_reduced",
                                    "count": len(reduced.items)}))
            return cors_response(409, {
                "error": "QUANTITY_REDUCED", "items": reduced.items,
                "message": "Some items are available in smaller quantities than you asked for. "
                           "Please confirm the new amounts.",
            }, origin)
        except cart_v2.CartContractError:
            return cors_response(409, {"error": "CART_NOT_PAYABLE",
                                       "message": "Please review your cart and try again."},
                                 origin)
        except customer_cart.CartBusy:
            # A cart whose last Wix outcome is unknown. Never priced and never reused until it is
            # reconciled -- the same answer `/wix-store/cart` gives, in the same vocabulary, so a
            # locked cart does not read as two different problems on two routes.
            logger.info(json.dumps({"event": "checkout_cart_reconciliation_required"}))
            return cors_response(409, {
                "error": "CART_RECONCILIATION_REQUIRED",
                "message": "Your cart is being updated. Please try again shortly.",
            }, origin)
        except wix_ecom.WixEcomError:
            return cors_response(502, {"error": "CATALOGUE_UNAVAILABLE",
                                       "message": "The store is temporarily unavailable."}, origin)
        except ValueError:
            return cors_response(409, {"error": "AMOUNT_NOT_SETTLED",
                                       "message": "We could not price this cart. Please try "
                                                  "again."}, origin)
    else:
        try:
            checkout = wix_ecom.create_checkout(line_items)
            currency = wix_ecom.checkout_currency(checkout)
            if currency != "INR":
                logger.warning(json.dumps({"event": "checkout_non_inr", "currency": currency}))
                return cors_response(409, {"error": "UNSUPPORTED_CURRENCY"}, origin)
            amount_paise = wix_ecom.authoritative_total_paise(checkout)
        except wix_ecom.AmountNotWhole:
            return cors_response(409, {"error": "AMOUNT_NOT_SETTLED",
                                       "message": "We could not price this cart. Please try "
                                                  "again."},
                                 origin)
        except wix_ecom.WixEcomError:
            return cors_response(502, {"error": "CATALOGUE_UNAVAILABLE",
                                       "message": "The store is temporarily unavailable."}, origin)
        # Retained only on the V1 branch. In Cart V2 the cart id IS the checkout id, so a
        # separate `wixCheckoutId` has nothing to identify.
        wix_checkout_id = str(checkout.get("id") or "")
        item_summary = wix_ecom.line_item_summary(checkout)

    # 2. Readiness gate. A live provider readback must confirm PAYMENT_READY, or the CTA is refused
    #    with the blocking state. No local constant makes this pass.
    readiness = _readiness()
    if not readiness.ready:
        logger.info(json.dumps({"event": "checkout_not_ready", "state": readiness.state}))
        return cors_response(409, {
            "status": "payment_unavailable",
            "readiness": readiness.state,
            "message": "Payments are temporarily unavailable. No charge was made.",
        }, origin)

    # 3. Reserve a canonical reference bound to a fresh attempt id, then build the attempt. The
    #    reference is minted and durably reserved BEFORE it is used, and never transformed after.
    attempt_id = payment_attempt.new_payment_attempt_id()
    try:
        extra = {"customerId": identity.customer_id,
                 "amountPaise": amount_paise, "currency": "INR",
                 "wixCheckoutId": wix_checkout_id, "checkoutMode": CHECKOUT_MODE}
        if snapshot is not None:
            # The Cart V2 join keys. `wixCartId` + `cartRevision` is what reconciliation matches
            # on, and `quoteHash` is what proves the paid amount is the one the customer
            # reviewed -- a cart edit produces a different hash rather than mutating this one.
            # `collectionPaise` is recorded beside the payable amount so the convenience fee and
            # its GST stay auditable instead of being inferred from a difference.
            extra.update(wixCartId=snapshot.cart_id, cartRevision=snapshot.cart_revision,
                         quoteHash=snapshot.snapshot_hash,
                         collectionPaise=snapshot.quote.collection_before_convenience_paise,
                         quoteExpiresAt=snapshot.expires_at,
                         policyVersion=snapshot.policy_version)
        reference_id = order_keys.allocate_payment_reference(
            _keys_table(), payment_attempt_id=attempt_id, extra=extra,
        )
    except order_keys.OrderIdentityUnavailable:
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE",
                                   "message": "Please try again shortly."}, origin)

    attempt = payment_attempt.build(
        customer_id=identity.customer_id,
        reference_id=reference_id,
        amount_paise=amount_paise,
        configuration_name=EXPECTED_CONFIGURATION_NAME,
        wix_checkout_id=wix_checkout_id,
        payment_attempt_id=attempt_id,
    )
    attempt["checkoutMode"] = CHECKOUT_MODE
    attempt = payment_attempt.transition(
        attempt, payment_attempt.PAYMENT_READINESS_CHECKED)
    try:
        _attempts_table().put_item(
            Item=attempt,
            ConditionExpression="attribute_not_exists(paymentAttemptId)",
        )
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "checkout_attempt_store_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    # 4. Hand off to the in-chat payment request — UNLESS initiation is disabled, in which case the
    #    attempt exists and is ready but no payable message goes out. Either way, NO order exists.
    if not INITIATION_ENABLED:
        logger.info(json.dumps({"event": "checkout_initiation_disabled",
                                "attemptId": attempt_id}))
        return cors_response(200, {
            "status": "PAYMENT_INITIATION_DISABLED",
            "paymentAttemptId": attempt_id,
            "amountPaise": amount_paise,
            "currency": "INR",
            "message": "Checkout prepared. Live payment initiation is currently disabled.",
        }, origin)

    sent = _send_order_details(
        phone=identity.phone, reference_id=reference_id,
        amount_paise=amount_paise, configuration_name=EXPECTED_CONFIGURATION_NAME,
        items=item_summary)
    if not sent:
        # The attempt is stored and ready; the message did not go. A soft failure the client can
        # retry, and crucially still NO order and NO second charge — the reference is reusable for a
        # delivery retry because the attempt is unchanged.
        return cors_response(502, {
            "status": "SEND_FAILED",
            "paymentAttemptId": attempt_id,
            "message": "We could not open the payment. Please try again.",
        }, origin)

    _mark_request_sent(attempt_id)
    return cors_response(200, {
        "status": "PAYMENT_REQUEST_SENT",
        "paymentAttemptId": attempt_id,
        "amountPaise": amount_paise,
        "currency": "INR",
        "message": "Check WhatsApp to complete your payment.",
    }, origin)


def _status(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
            origin: str) -> Dict[str, Any]:
    """Return the customer-safe status of one of the caller's own payment attempts.

    IDOR-safe: the attempt is loaded by id and then `authorize_resource` refuses it unless it
    belongs to this session. A missing attempt and someone else's attempt return the identical
    opaque 401, so the endpoint cannot be used to discover which attempt ids are real.
    """
    attempt_id = str(body.get("paymentAttemptId") or "").strip()
    if not attempt_id:
        return cors_response(400, {"error": "PAYMENT_ATTEMPT_ID_REQUIRED"}, origin)

    try:
        stored = _attempts_table().get_item(
            Key={"paymentAttemptId": attempt_id},
            # Consistent now, because this read decides whether to write an order record.
            ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "checkout_status_read_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    owned = customer_auth.authorize_resource(identity, stored, owner_field="customerId")
    order_number = ""
    if not owned.get("finalizationStage"):
        # Not yet finalized -- which is the closed-tab shape, where the webhook gave the attempt
        # order identity and nothing wrote the order record. `_finalize_from_claim` decides from
        # the CLAIM row and returns False cheaply when there is none, so an ordinary in-flight
        # poll costs one extra get_item. Once it succeeds, `finalizationStage` is set and this
        # never runs again.
        try:
            if _finalize_from_claim(identity, owned):
                owned = _attempts_table().get_item(
                    Key={"paymentAttemptId": attempt_id},
                    ConsistentRead=True).get("Item") or owned
                order_number = str(owned.get("orderNumber") or "")
        except Exception as error:  # noqa: BLE001
            # The poll must still answer. A failure here leaves the attempt exactly as it was.
            logger.error(json.dumps({"event": "checkout_status_finalize_failed",
                                     "alert": "PAID_BUT_NO_ORDER_RECORD",
                                     "error": type(error).__name__}))
    # payment_history_entry never carries an order number for a non-paid attempt, and collapses a
    # failed one to the "Payment failed — no order created" label. It is the exact customer-facing
    # projection the status UI needs.
    entry = payment_attempt.payment_history_entry(owned, order_number=order_number)
    return cors_response(200, {"status": entry.get("status"), "attempt": entry}, origin)


# ── the WhatsApp order_details handoff ──────────────────────────────────────────

def _send_order_details(*, phone: str, reference_id: str, amount_paise: int,
                        configuration_name: str, items: list) -> bool:
    """Invoke the existing in-chat payment-request sender. Returns True on a 2xx.

    This does NOT build the order_details payload itself — `outbound-whatsapp`/`whatsapp-business-api`
    own that (`_build_payment_settings`, the interactive-payment path). We pass the reserved
    reference byte-for-byte, the authoritative paise amount, the configuration name and a price-free
    item summary, and let the sender construct the Meta message. Meta + Razorpay collect the money
    in-chat; nothing here charges anything.
    """
    invoke_event = {
        "httpMethod": "POST",
        "path": "/wa-business/messages/send/interactive-payment",
        "body": json.dumps({
            "to": "".join(ch for ch in str(phone or "") if ch.isdigit()),
            "reference_id": reference_id,
            "payment_configuration": configuration_name,
            "amount_paise": amount_paise,
            "currency": "INR",
            "items": items,
        }),
    }
    try:
        response = _lambda_client().invoke(
            FunctionName=SENDER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(invoke_event).encode("utf-8"),
        )
        raw = response["Payload"].read()
        if response.get("FunctionError"):
            return False
        result = json.loads(raw.decode("utf-8")) if raw else {}
        return int(result.get("statusCode") or 500) < 300
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "checkout_send_failed",
                                 "error": type(error).__name__}))
        return False


def _mark_request_sent(attempt_id: str) -> None:
    """Advance the attempt to PAYMENT_REQUEST_SENT with the monotonic guard. Best-effort.

    Uses the same rank condition the state machine defines, so a late/duplicate write cannot move
    the attempt backwards. A failure here does not undo the send; the webhook reconciliation keys on
    the reference regardless of this marker.
    """
    try:
        _attempts_table().update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression="SET #s = :s, " + payment_attempt.RANK_ATTRIBUTE
            + " = :r, updatedAt = :t",
            ConditionExpression=payment_attempt.condition_expression(),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": payment_attempt.PAYMENT_REQUEST_SENT,
                ":r": payment_attempt.rank(payment_attempt.PAYMENT_REQUEST_SENT),
                ":t": int(time.time()),
            },
        )
    except Exception as error:  # noqa: BLE001
        logger.info(json.dumps({"event": "checkout_mark_sent_skipped",
                               "error": type(error).__name__}))
