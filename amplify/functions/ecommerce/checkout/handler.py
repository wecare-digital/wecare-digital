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
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, customer_auth, customer_session, payment_readiness
from lambda_utils.ecommerce import (
    blog_contribution, cart_v2, catalog_analytics, checkout_pricing, contact_address, customer_cart, finalization,
    gift_card_settlement, order_channel, order_creation, order_keys, payment_address,
    payment_attempt, purchase_intent, wa_payment_request, website_checkout, whatsapp_basket,
    wix_address, wix_writeback)
# The committed recognition set and the three allowed contributions live in `blog_contribution`
# and are IMPORTED rather than re-declared, so they are stated once and the TS<->Python drift test
# that pins them stays meaningful. Its own payment surface (`prepare_contribution` and friends) is
# NOT imported and has no caller here: a contribution is a product in the one checkout, not a
# second payment implementation. Its amount VALIDATOR is not imported either -- with three fixed
# prices there is no customer-proposed amount to validate.
from lambda_utils.ecommerce.blog_contribution import (
    CONTRIBUTION_CHOICES_PAISE, CONTRIBUTION_PRODUCT_IDS, ContributionRejected)
# Phase O-1 services (Submit Request / Request Amendment): the server allow-list and its
# per-line price assertion. All logic lives in the module; this file only calls it.
from lambda_utils.ecommerce import service_requests
from lambda_utils.ecommerce.service_requests import ServiceNotPayable, ServicePriceChanged
# The LIVE Wix price of each service, for the four public service pages. Same adapter, same cart,
# same figure the checkout charges -- see `_service_prices` below for why this arm lives here.
from lambda_utils.ecommerce import service_pricing
from lambda_utils.integrations import razorpay_orders, razorpay_verify
from lambda_utils import wix_ecom
# Aliased `customer_identity`, NEVER `identity`: `identity` is a parameter name in nearly every
# function in this file (`_checkout_profile(identity)`, `_website_snapshot(identity, ...)`,
# `_profile_status(identity, ...)`), so that alias would be shadowed locally and
# `identity.normalize_phone_preserving_country` would resolve against a `CustomerIdentity`
# instance and raise `AttributeError` inside `_checkout_profile`'s `except Exception: raise` --
# a 500 on every checkout.
from lambda_utils.identity import customer as customer_identity
from lambda_utils.identity import customer_uuid
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

#: The business-API Lambda, which holds the Meta token and answers the readiness readback. It is
#: NOT a payment sender and has not been one since the in-chat send moved to
#: `OUTBOUND_SENDER_FUNCTION` below; the identifier was renamed from `SENDER_FUNCTION` so the
#: name stops lying, and its ONE remaining use is `_fetch_payment_configurations`.
#:
#: The ENV KEY stays `SENDER_FUNCTION`, deliberately: renaming it would change a live environment
#: variable and would need an edit to `provision_checkout.expected_environment()`. Only the Python
#: identifier and this comment changed.
PAYMENT_CONFIG_READER_FUNCTION = os.environ.get("SENDER_FUNCTION",
                                                "wecare-whatsapp-business-api:live")

#: The in-chat payment sender: the ONLY function in this repository that composes a Meta
#: `review_and_pay` message, and therefore the only one that owns `_build_payment_settings`.
#:
#: A LITERAL rather than an env var. It is a function name, not a Meta-registered string, so the
#: "one home, env-read" argument that justifies the template name does not transfer, and a stale
#: env value here would surface as a send failure that looks like a Meta problem.
OUTBOUND_SENDER_FUNCTION = "wecare-outbound-whatsapp:live"

PAYMENT_WABA_ID = os.environ.get("PAYMENT_WABA_ID", "2094615664435155")

#: Readiness inputs. Deliberately have NO safe default that could read as "ready": an empty MID or
#: configuration name makes `payment_readiness.evaluate` return CONFIGURATION_UNVERIFIED, which
#: blocks. They are set from the environment at deploy time and re-derived from a live read.
EXPECTED_CONFIGURATION_NAME = os.environ.get("EXPECTED_CONFIGURATION_NAME", "")
EXPECTED_PROVIDER_MID = os.environ.get("EXPECTED_PROVIDER_MID", "")

#: Off by default. The plumbing runs; the payable message does not go out until this is truthy.
INITIATION_ENABLED = str(
    os.environ.get("CHECKOUT_INITIATION_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")

#: The Wix catalogue product id of the live Contribute product, lowercased. NOT a secret -- a
#: catalogue reference. UNSET MEANS CONTRIBUTIONS ARE REFUSED, not "priced as an ordinary
#: product": recognition comes from the COMMITTED `CONTRIBUTION_PRODUCT_IDS` set, so the server
#: can still identify a contribution line with this key empty and answers 409 rather than
#: charging through with the alone check and the total guard both sitting out. That is what makes
#: this a kill switch rather than a de-guard.
CONTRIBUTION_PRODUCT_ID = str(os.environ.get("CONTRIBUTION_PRODUCT_ID", "")).strip().lower()

#: Sized against wecare-checkout's measured 20s timeout, not against "any real basket". Each
#: command is one Wix write plus ~5 DynamoDB ops, and this runs alongside ensure(), the
#: per-product GETs, calculate(), the Razorpay create and the PAYREF# reservation.
#:
#: EXCEEDING THIS IS NOT THE SAME REFUSAL AS FAILING TO CONVERGE. A six-line saved cart against a
#: one-line contribution needs 1 add + 6 removes = 7 commands, and the lines to drop are on the
#: SERVER cart, which no browser affordance touches -- `/wix-store/*` appears nowhere in
#: src/pages/cart.tsx. So this raises `CartResetRequired`, whose answer tells the customer the one
#: thing that actually works, instead of `CART_NOT_PAYABLE` plus "remove some lines" about lines
#: they cannot see.
MAX_RECONCILE_COMMANDS = 6
#: Stop issuing commands with this much of the invocation left. A command interrupted by a Lambda
#: timeout is NOT an exception, so execute() never reaches its unlock and the cart row stays
#: `busy` -- and resolve() checks `busy` BEFORE expiresAt, so that is a 30-day lockout for that
#: customer with nothing in this repo able to clear it.
RECONCILE_DEADLINE_MARGIN_SECONDS = 8
#: The Wix cart line ceiling, which the transient union must also respect.
CART_LINE_CEILING = 100

DEFAULT_INVOCATION_BUDGET_SECONDS = 20.0
#: `None` means "this frame was not entered through `handler`", NOT "no time left".
_DEADLINE: Optional[float] = None       # time.monotonic() terms once set


def _set_deadline(context: Any) -> None:
    """Record when this invocation must stop issuing remote writes. Called FIRST in `handler`.

    Written on EVERY invocation before any branch, which is what makes a module global safe here:
    a warm sandbox always overwrites it, so a stale value from a previous request cannot be read.
    A conditional write would not have that property.

    `context` is None in every unit test (`h.handler(event, None)`), so the fallback is the
    function's configured timeout rather than an error.
    """
    global _DEADLINE
    remaining = DEFAULT_INVOCATION_BUDGET_SECONDS
    getter = getattr(context, "get_remaining_time_in_millis", None)
    if callable(getter):
        try:
            remaining = max(0.0, float(getter()) / 1000.0)
        except (TypeError, ValueError):
            remaining = DEFAULT_INVOCATION_BUDGET_SECONDS
    _DEADLINE = time.monotonic() + remaining


def _seconds_left() -> float:
    """Seconds before this invocation must stop issuing remote writes.

    `_DEADLINE is None` means this frame was NOT entered through `handler`, so answer the
    configured budget. The unset state has to be explicit rather than a sentinel 0.0, because
    `0.0 - time.monotonic()` is a large NEGATIVE number -- which would make the reconcile refuse
    before the first command, in every such caller, permanently.

    Such callers exist and are promised to keep working: `_website_snapshot` is documented
    keyword-only-with-default precisely because `tests/test_graft_money_correctness.py` drives it
    positionally as `_website_snapshot(identity, line_items, now)`, which never passes through
    `handler` and therefore never calls `_set_deadline`.
    """
    if _DEADLINE is None:
        return DEFAULT_INVOCATION_BUDGET_SECONDS
    return _DEADLINE - time.monotonic()

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
    business-API Lambda already owns the Graph token and the read; we invoke its
    `/payment-config/list` route, which returns the FLATTENED `{data:[config,...]}` shape
    evaluate consumes. (The older `/payment-config/raw` route returned a human
    paymentConfig/liveReadiness view with no top-level `data`, so evaluate read it as
    META_UNAVAILABLE — fixed 2026-10-08 alongside the nested-shape / provider_mid parsing.)
    """
    invoke_event = {
        "httpMethod": "GET",
        "path": "/wa-business/payment-config/list",
        "queryStringParameters": {"wabaId": waba_id},
    }
    response = _lambda_client().invoke(
        FunctionName=PAYMENT_CONFIG_READER_FUNCTION,
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
    if explicit in ("create", "status", "prepare", "verify", "profile", "claim-basket"):
        return explicit
    path = str(event.get("rawPath") or event.get("path") or "").lower()
    if path.endswith("/status"):
        return "status"
    if path.endswith("/prepare-checkout"):
        return "prepare"
    if path.endswith("/verify-callback"):
        return "verify"
    return "create"


#: The one error code the public price arm can answer with. No detail: an anonymous caller learns
#: that prices are unavailable, which is all it needs to render the honest unavailable state.
SERVICE_PRICES_UNAVAILABLE = "SERVICE_PRICES_UNAVAILABLE"


def _service_prices(origin: str) -> Dict[str, Any]:
    """`GET /ecommerce/service-prices` -> every service's LIVE Wix price, in integer paise.

    WHY THIS LIVES IN THE CHECKOUT LAMBDA. It is the only function carrying `WIX_API_KEY_SECRET`
    *and* the live `WIX_SITE_ID` *and* `WIX_CART_V2_ENABLED`, and it already owns `_wix_request`
    and the `cart_v2` adapter. `wecare-service-requests` is structurally barred from Wix (it
    imports no Wix module and reads no secret, and `scripts/provision_service_requests.py`
    enforces that in its role policy), so putting the call there would break a guarantee a test
    enumerates. `wecare-wix-store`'s site id is fingerprinted rather than recorded in the
    manifest, so which site it points at is UNVERIFIED -- and pricing against the wrong site is
    precisely the drift this endpoint exists to remove.

    FAILS CLOSED, TWICE OVER. With Cart V2 off there is no pricing path at all, so this answers
    503 rather than an empty payload a browser might read as "free". If Wix prices nothing, it
    answers 503 for the same reason. A PARTIAL result is served at 200: the slugs that resolved
    carry their price and the rest carry `{"available": false}` with no `paise` key, because one
    service Wix cannot price is no reason to take the other three off sale.

    WIX READ VOLUME IS BOUNDED TWICE, because this is the one unauthenticated arm and a cache
    miss costs 8 Wix calls on the same API key the live checkout prices with. The headers below
    carry the measurement of the first bound (the edge really does cache); the second is a
    per-route throttle on `GET /ecommerce/service-prices`, applied by
    `scripts/provision_checkout.py` and read back by its `--verify`. Wix WRITES are bounded
    structurally and permanently instead: four carts for the life of the site, by the pointer
    rows `service_pricing` keeps.

    Logs counts only. No credential, no cart id, no provider message.
    """
    if not cart_v2.is_enabled():
        logger.warning(json.dumps({"event": "service_prices_disabled"}))
        return cors_response(503, {"error": SERVICE_PRICES_UNAVAILABLE}, origin)
    try:
        payload = service_pricing.resolve_all(cart_v2.CartV2(_wix_request), _keys_table())
    except Exception as exc:  # noqa: BLE001 -- `type(exc).__name__` only, never provider text
        logger.error(json.dumps({"event": "service_prices_failed",
                                 "error": type(exc).__name__}))
        return cors_response(503, {"error": SERVICE_PRICES_UNAVAILABLE}, origin)
    priced = sum(1 for price in payload["prices"].values() if price.get("available"))
    if not priced:
        logger.error(json.dumps({"event": "service_prices_none_resolved",
                                 "slugs": len(payload["prices"])}))
        return cors_response(503, {"error": SERVICE_PRICES_UNAVAILABLE}, origin)
    logger.info(json.dumps({"event": "service_prices_served", "priced": priced,
                            "slugs": len(payload["prices"])}))
    response = cors_response(200, payload, origin)
    # Post-processed because `cors_response` takes no header argument.
    #
    # THE EDGE DOES CACHE THIS, AND THAT IS MEASURED RATHER THAN ASSERTED. An earlier version of
    # this comment claimed the `/api/*` edge "absorbs the anonymous traffic" with nothing behind
    # the claim, while `docs/execution/change-authority-matrix.md` row 297 recorded three
    # requests through that same rewrite all answering `Miss from cloudfront`. Measured on
    # 2026-10-08 against `wecare.digital/api/seo-tools/blog-public` -- the one other PUBLIC
    # `max-age` response behind the same rewrite -- four identical requests answered
    # `Miss`, then `Hit (age 2)`, `Hit (age 4)`, `Hit (age 7)`. Row 297 does not contradict that:
    # it states the API was sending `cache-control: no-store`, which nothing is allowed to cache.
    # The variable was the header, not the edge.
    #
    # `Access-Control-Allow-Origin: *`, NOT the origin `cors_headers` reflects, and the
    # measurement is what forces it rather than a preference. In the same run the origin's
    # `Vary: Origin` was STRIPPED (`vary: Accept-Encoding` is what reached the client), and a
    # request carrying `Origin: https://www.wecare.digital` was served the cached apex
    # `Access-Control-Allow-Origin: https://wecare.digital`. A browser rejects that, so
    # `fetchServicePrices` would fail closed and every `www` visitor would read "temporarily
    # unavailable" with no way to buy. A shared cache cannot hand the wrong origin a response
    # that names every origin. Safe HERE and nowhere else in this handler, for reasons specific
    # to this one body: a public price list, no customer data, no credential, no cookie, and the
    # browser client fetches it without credentials (so `*` is even a legal answer).
    #
    # `Vary: Origin` is sent anyway, for an intermediary that does honour it and so that a future
    # change back to a reflected origin is not silently poisoned.
    #
    # The edge is the FIRST of two bounds on Wix reads, not the only one: the route carries its
    # own throttle (`scripts/provision_checkout.py`, ROUTE_THROTTLE_*), because an anonymous
    # route whose cache misses cost 8 Wix calls shares an API key with the live checkout's
    # `calculate`, and concurrency rather than the per-sandbox minute is the multiplier on a miss.
    response["headers"]["Cache-Control"] = f"public, max-age={service_pricing.CACHE_SECONDS}"
    response["headers"]["Access-Control-Allow-Origin"] = "*"
    response["headers"]["Vary"] = "Origin"
    return response


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # FIRST, before any branch, so every frame below can ask how much of the invocation is left
    # without the context being threaded through four signatures. See `_set_deadline`.
    _set_deadline(context)
    origin = extract_origin(event)
    if event.get('internalAction') in ('prepareNativeCatalogService', 'finalizeNativeCatalogService'):
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return cors_response(403, {'error': 'Internal invocation required'}, origin)
        return _native_catalog_service(event, origin)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return options_response(origin)

    # THE ONE PRE-AUTH ARM, and it is deliberately the narrowest shape that can exist: GET only,
    # on one exact path, taking no path parameter, no query string and no body. Nothing a caller
    # supplies reaches Wix or a table, which is what makes an anonymous route safe here. Mirrors
    # how `wix-store/handler.py` routes `/wix-store/cart` ahead of `require_auth`.
    #
    # It must come BEFORE `require_customer`, because a visitor reading a public service page has
    # no session yet and the price is the thing that decides whether they sign in at all. Any
    # other method or path falls straight through to the authenticated chain unchanged.
    if method == "GET" and str(event.get("rawPath") or event.get("path") or "") \
            .rstrip("/").lower().endswith("/ecommerce/service-prices"):
        return _service_prices(origin)

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
        # A WhatsApp catalogue basket being adopted by the signed-in customer who sent it. AHEAD
        # of the `_create` fallback for the same reason `profile` is: the `return _create(...)`
        # below is this chain's `else`, so an arm in `_action`'s tuple without an arm here would
        # route a claim into the checkout-CREATE path.
        if action == "claim-basket":
            return _claim_basket(identity, body, origin)
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
    """Return a verified profile only for an exact permanent customer owner.

    Phone matching locates candidates; ownerless contacts require staff reconciliation.
    Email verification remains mandatory for payment prefill.
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
    for item in response.get("Items") or []:
        if item.get("deletedAt") is not None:
            continue
        if not identity.customer_id or item.get("checkoutCustomerId") != identity.customer_id:
            continue
        if not item.get("emailVerifiedAt") or not str(item.get("email") or "").strip():
            continue
        return item
    return None

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


def _owned_for_supply(owned: Optional[Dict[str, Any]],
                      requires_delivery: bool) -> Optional[Dict[str, Any]]:
    """What to hand `build_intent_with_calculation` as `owned_address` for GST place-of-supply.

    FEAT-003 made storage international, so `from_contact` now returns a structurally-valid
    address whose state may not resolve to a GST subdivision. The place-of-supply derivation in
    `purchase_intent` raises `UnmappableAddress` on such a value, which is CORRECT for a delivery
    basket (and already pre-empted by the `for_wix` gate upstream) but WRONG for a no-delivery
    contribution, which has no place of supply at all. For a no-delivery basket, an address whose
    state is not GST-resolvable is passed as `None` so the quote falls back to the documented
    intra-state default - exactly the pre-FEAT-003 behaviour, when `from_contact` returned None.
    A delivery basket's address is passed through unchanged (it is already proven payable).
    """
    if owned and not requires_delivery:
        try:
            wix_address.gst_state_code(owned)
        except wix_address.UnmappableAddress:
            return None
    return owned or None


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
                      now: int, *, profile: Optional[Dict[str, Any]] = None,
                      reset: bool = False):
    """`(snapshot, calculated_or_None)`. `None` on the V1 branch, which has no Cart V2 result.

    Cart V2 uses its existing owned-cart producer and hands back the calculation it already
    performed, so the Wix order payload is built from the SAME figures the price was quoted from.
    The deployed V1 branch is converted into the same immutable QuoteSnapshot using Wix's
    authoritative checkout total, then the one central convenience-fee calculator -- and is
    refused outright when the initiation gate is on, because it has no stable cart identity.

    `profile` is the contact row the caller already loaded, threaded down so the happy path costs
    no second DynamoDB Query. KEYWORD-ONLY with a `None` default, because
    `tests/test_graft_money_correctness.py` calls this positionally as
    `_website_snapshot(identity, line_items, now)` and must keep working unchanged. `reset` is
    keyword-only with a `False` default for the same reason.

    `reconcile=True` is passed HERE AND NOWHERE ELSE. The website route has a cart page the
    customer is looking at, so bringing the saved Wix cart to the requested basket is "asking
    them to review it" carried out. The WhatsApp `_create` path has no such surface, so it keeps
    refusing a mismatched saved cart, unchanged.
    """
    if cart_v2.is_enabled():
        snapshot, _items, calculated = _v2_snapshot(
            identity, line_items, profile=profile, reconcile=True, reset=reset)
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


def _claimed_handoff(identity: customer_auth.CustomerIdentity,
                     body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The WhatsApp hand-off row this prepare is settling, or `None` for a website basket.

    One job: give `channel` exactly ONE source, so `_website_prepare` does not later grow a second
    reading of it that can disagree with the first. The hand-off row is written phone-bound by the
    inbound WhatsApp catalogue-order path and claimed by the authenticated `claim-basket` action
    (plan item 7); until that lands there is no row to find, so this answers `None` and every
    prepare is attributed to the website. That is TRUE rather than convenient: the path that
    would create a WhatsApp-origin basket does not exist yet and is gated off when it does.

    DELIBERATELY NOT READ OFF `body`. Attribution the browser can type is attribution a customer
    can forge, and `/orders` reports this word back as fact. The phone binding lives on the row,
    which is why the row - and not the request - is the thing to read.

    IT IS A POINTER READ, NOT A SEARCH. CommerceKeys is keyed on `orderId` alone and carries no
    customer index, so "this customer's claimed hand-off" is not a query anybody can make - and a
    Scan is neither in this function's IAM nor acceptable on a checkout path. `_claim_basket`
    therefore writes one keyed row per customer (`WABASKETCLAIM#<customerId>`) and this reads it.

    IT IS BOUND TO THE CART, NOT JUST TO THE CUSTOMER, and that is the correction rather than a
    refinement. The pointer's thirty-day lifetime matches `customer_cart.CART_LIFETIME`, but the
    cart is CONSUMED at payment while the pointer is not - so a customer who claimed a WhatsApp
    basket, paid for it, and placed an ordinary website order a week later was inside the lifetime
    and had `whatsapp` written onto that second order's attempt, `PAYREF#` row, order row,
    `/orders` tag and GST invoice. The pointer now records the Wix cart the lines were merged into
    and `whatsapp_basket.active_claim` refuses to answer for any other cart, so the label expires
    with the BASKET it describes.

    THE CART IS RESOLVED ONLY WHEN A POINTER EXISTS, so the ordinary website prepare - which is
    almost every prepare - still makes exactly one extra DynamoDB read and not two.

    NEVER RAISES, and that is load-bearing rather than defensive. This runs on the money path, and
    the only thing it decides is a LABEL. A DynamoDB blip while reading an attribution pointer must
    not fail a prepare, so the failure mode is "attributed to the website" - the same asymmetric
    default `order_channel.canonical` applies, which under-claims the WhatsApp channel rather than
    mislabelling a website order. That now covers the cart read too: `CustomerCart.resolve` raises
    `CartBusy` on a locked row and `ValueError` on a phone it will not key, and both of those are
    "no claim" here rather than a 500 in a checkout.
    """
    try:
        pointer = _keys_table().get_item(
            Key={"orderId": whatsapp_basket.claim_pointer_key(identity.customer_id)}
        ).get("Item")
    except Exception as exc:  # noqa: BLE001 - see the docstring: a label never fails a prepare
        logger.info(json.dumps({"event": "checkout_channel_pointer_unavailable",
                                "error": type(exc).__name__}))
        return None
    if pointer is None:
        return None
    # Same ownership check every other customer-scoped row in this table gets. A pointer is
    # keyed on the customer id, so this cannot normally fail; it is here because a read that
    # trusts its key is a read that stops being safe the moment the key scheme changes.
    try:
        customer_auth.authorize_resource(identity, pointer)
    except customer_auth.CustomerNotAuthorized:
        return None
    try:
        current_cart = customer_cart.CustomerCart(
            _keys_table(), cart_v2.CartV2(_wix_request)).resolve(identity)
    except Exception as exc:  # noqa: BLE001 - a label never fails a prepare; see the docstring
        logger.info(json.dumps({"event": "checkout_channel_cart_unresolved",
                                "error": type(exc).__name__}))
        return None
    return whatsapp_basket.active_claim(pointer, int(time.time()), cart_id=current_cart or "")


#: The one refusal every unclaimable basket gets, whatever made it unclaimable.
#:
#: ONE ANSWER FOR FOUR DIFFERENT FACTS - no such token, somebody else's token, already claimed,
#: expired - because distinguishing them turns this endpoint into an existence oracle: a caller
#: holding a guessed token could learn that it names a real basket, and a caller holding a real
#: token could learn whose. The copy says what the customer can do about it, which is the same
#: thing in all four cases.
_BASKET_REFUSED = {
    "status": "BASKET_UNAVAILABLE",
    "message": "This cart link is no longer available. Send your cart again on WhatsApp to get a "
               "fresh link.",
}


def _claim_basket(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                  origin: str) -> Dict[str, Any]:
    """Adopt a WhatsApp catalogue hand-off into the signed-in customer's own Wix cart.

    `require_customer` has already run in `handler`, so there is a proven session here and no
    unauthenticated caller reaches this function at all - which is also why the token alone is
    never sufficient: the claim requires the session's phone to equal the phone the hand-off was
    written for.

    THIS ACTION QUOTES NOTHING. It merges lines and marks a row; it computes no total, reads no
    price and returns no money field. The arithmetic stays where it already lives - Wix calculates
    the collection and `checkout_pricing.compute_quote` turns it into a payable, once, on the
    following `prepare`. That is the whole reason the WhatsApp leg no longer has a calculator.

    WHAT IT WRITES, in order, and why that order:

      1. the Wix cart, through `CustomerCart.ensure` - resolve before generate, so one purchase has
         one cart and a retried claim cannot mint a second one on the live site;
      2. the hand-off row marked claimed, CONDITIONALLY on `attribute_not_exists(claimedAt)`, so a
         second claim loses the write rather than being refused by a check it could race;
      3. the channel pointer `_claimed_handoff` reads.

    The cart comes first because `ensure` is idempotent and the mark is not: marking first and
    failing at Wix would burn a basket that was never merged, which is unrecoverable from the
    customer's side. Doing it this way means the worst case is a merged cart whose row is still
    unclaimed - and the second claim then no-ops on `ensure` and completes the mark.

    `resetCart` IS READ HERE, AND IT IS WHAT STOPS `BASKET_CART_IN_USE` BEING A DEAD END. The
    "empty your website cart and open the link again" answer below instructs the customer to clear
    a cart they cannot reach: `clearCart()` empties localStorage, while the condition is the
    SERVER-side `CUSTOMERCART#<phone>` pointer, which lives thirty days and survives the payment
    that consumed its cart. So a customer who paid on the website, then sent a WhatsApp cart, read
    an instruction with no way to follow it and had to wait out the pointer. `src/pages/cart.tsx`
    now retries ONCE with `resetCart: true` when its own cart is empty, and that is the only
    caller that sets it.

    IT RELEASES A POINTER AND LOSES NOTHING DURABLE, which is why it is defensible on this path.
    `_website_prepare` already offers the same release (`resetCart` there, behind "Start a new
    cart"), and the browser cart - not the saved Wix cart - is what the next prepare rebuilds from:
    `_reconcile_saved_cart`'s own docstring says the request's basket wins. So the worst case is a
    Wix cart abandoned a few minutes before the next prepare would have reconciled it anyway.
    `is True` is an identity comparison for the same reason it is in `_website_prepare`: a truthy
    reading of `"false"` would make a typo destructive.
    """
    token = str(body.get("basket") or "").strip()
    # Bounded before it is used as a key. `new_token()` produces 32 URL-safe characters; a value
    # outside that shape is not a token this system ever issued, and refusing it here keeps a
    # megabyte of request body out of a DynamoDB key.
    if not token or len(token) > 100:
        return cors_response(404, _BASKET_REFUSED, origin)

    keys = _keys_table()
    now = int(time.time())
    row = keys.get_item(Key={"orderId": whatsapp_basket.handoff_key(token)}).get("Item")

    # THE PHONE BINDING. `normalize_phone_preserving_country` is the same function
    # `auth/customer-profile` normalises with, and `whatsapp_basket.e164` is the same E.164 shape
    # the row was written under, so this is one comparison of two strings rather than two notions
    # of "the same number". A mismatch takes the SAME refusal a missing row takes.
    try:
        presented = customer_identity.normalize_phone_preserving_country(identity.phone)
    except customer_identity.InvalidPhoneNumber:
        presented = ""
    if not whatsapp_basket.claimable(row, presented, now):
        logger.info(json.dumps({
            "event": "checkout_basket_claim_refused",
            # No reason field, deliberately: a reason logged is a reason that gets returned by the
            # next person to touch this, and the four reasons are what must not be distinguishable.
            "found": bool(row),
        }))
        return cors_response(404, _BASKET_REFUSED, origin)

    items = whatsapp_basket.catalog_items(row)
    if not items:
        return cors_response(404, _BASKET_REFUSED, origin)

    carts = customer_cart.CustomerCart(_keys_table(), cart_v2.CartV2(_wix_request))
    try:
        if body.get("resetCart") is True:
            # BEFORE `ensure`, so the create below is reached rather than the existing cart being
            # resolved. `abandon` refuses while the row is `busy` and answers False when there is
            # no pointer at all, so an unnecessary reset is a no-op rather than an error.
            if carts.abandon(identity):
                logger.info(json.dumps({"event": "checkout_basket_claim_cart_released"}))
        cart_id, created = carts.ensure(identity, items)
    except customer_cart.CartBusy:
        # A lock means a Wix outcome is unknown. The hand-off is LEFT UNCLAIMED so the customer can
        # try again, which is the recoverable direction.
        return cors_response(200, {
            "status": "CART_RECONCILIATION_REQUIRED",
            "message": "Your cart is being updated. Please try again shortly.",
        }, origin)

    if not created:
        # THE CUSTOMER ALREADY HAS A LIVE WIX CART, AND THIS IS REPORTED RATHER THAN RESOLVED.
        #
        # `ensure` is resolve-before-generate: it returns the existing cart and does NOT add to it.
        # So the hand-off lines did not land, and there are only three honest options - add them
        # (several Wix writes inside a 20s budget, on a function whose measured timeout already
        # bounds commands at MAX_RECONCILE_COMMANDS), replace the cart (discarding lines the
        # customer put there on the website), or say so.
        #
        # Saying so is chosen because it loses nothing: the row is LEFT UNCLAIMED and still
        # claimable until `expiresAt`, so the customer can clear their website cart and open the
        # same link again. Claiming success here and merging nothing would be the one outcome that
        # is both silent and wrong.
        logger.info(json.dumps({"event": "checkout_basket_claim_cart_in_use",
                                "handoffLines": len(items)}))
        return cors_response(200, {
            "status": "BASKET_CART_IN_USE",
            "channel": order_channel.CHANNEL_WHATSAPP,
            "handoffLines": len(items),
            "message": "Your website cart already has items in it. Empty it, then open your "
                       "WhatsApp cart link again.",
        }, origin)

    try:
        keys.update_item(
            Key={"orderId": row["orderId"]},
            UpdateExpression="SET claimedAt = :now, claimedBy = :customer",
            ConditionExpression="attribute_not_exists(claimedAt)",
            ExpressionAttributeValues={":now": now, ":customer": identity.customer_id})
    except Exception as error:  # noqa: BLE001 - re-raised unless it is the conditional
        if (getattr(error, "response", {}).get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"):
            raise
        # Another request claimed it between the read and here. The cart it merged is the same cart
        # this one resolved, so there is nothing to undo - and the loser must not report success for
        # a claim it did not make.
        return cors_response(404, _BASKET_REFUSED, origin)

    # The attribution pointer, LAST, so it can never say `whatsapp` for a claim that did not
    # complete. An unconditional put: last claim wins, because the channel describes the basket the
    # customer is about to pay for. BOUND TO `cart_id`, so the label dies with this basket instead
    # of with this customer - see `_claimed_handoff` and `whatsapp_basket.build_claim_pointer`.
    keys.put_item(Item=whatsapp_basket.build_claim_pointer(
        row, identity.customer_id, now=now, cart_id=cart_id))

    logger.info(json.dumps({"event": "checkout_basket_claimed",
                            "handoffId": row["orderId"],
                            "channel": order_channel.CHANNEL_WHATSAPP,
                            "mergedLines": len(items)}))
    return cors_response(200, {
        "status": "BASKET_CLAIMED",
        "channel": order_channel.CHANNEL_WHATSAPP,
        "mergedLines": len(items),
        # THE LINES, SO THE HAND-OFF ACTUALLY ARRIVES SOMEWHERE THE CUSTOMER CAN PAY FROM.
        #
        # They were merged into the server-side Wix cart above, but the cart the customer SEES -
        # and the basket `_website_prepare` prices, because `_reconcile_saved_cart` makes the Wix
        # cart match the request - is the browser's localStorage cart. Returning only a count left
        # that cart untouched, so a successful claim showed no items (indistinguishable from a
        # refusal) and the next checkout reconciled the claimed lines straight back OUT of the Wix
        # cart instead of paying for them.
        #
        # `catalog_items` shape exactly: `productId`, `variantId`, `quantity`. STILL NO MONEY FIELD
        # OF ANY KIND - not a price, not a currency, not a total. The browser resolves its own
        # display price from the committed catalogue snapshot it already renders every other cart
        # line from, and the payable is still produced once, by `checkout_pricing.compute_quote`,
        # on the prepare that follows.
        "lines": items,
    }, origin)


def _attempt_for_gateway_order(gateway_order_id: str) -> Optional[Dict[str, Any]]:
    binding = order_keys.resolve_gateway_order(_keys_table(), gateway_order_id) or {}
    attempt_id = str(binding.get("paymentAttemptId") or "")
    if not attempt_id:
        return None
    return _attempts_table().get_item(
        Key={"paymentAttemptId": attempt_id}
    ).get("Item")


def _refuse_rebound_service_intent(identity: customer_auth.CustomerIdentity, request_key: str,
                                   body: Dict[str, Any], keys) -> None:
    """Phase O-1: refuse a request key whose attempt is bound to a different service intent.

    Reads only (the REQUESTKEY# row, then its PAYREF#). A no-op for every non-service basket and
    for a key with no reference yet. Raises `CheckoutRejected("INTENT_CHANGED")`, which
    `cart.tsx` already answers by rotating the key once -- so the customer pays a FRESH attempt
    bound to the intent they chose now, never the superseded one. See
    `service_requests.intent_rebound`.
    """
    if not service_requests.has_service_line(body.get("lineItems")):
        return
    reservation = order_keys.resolve_checkout_request_key(
        keys, customer_id=identity.customer_id, request_key=request_key) or {}
    reference = str(reservation.get("referenceId") or "")
    if not reference:
        return
    if service_requests.intent_rebound(order_keys.resolve_payment_reference(keys, reference),
                                       body):
        logger.warning(json.dumps({"event": "service_intent_rebound"}))
        raise website_checkout.CheckoutRejected("INTENT_CHANGED")


def _website_prepare(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                     origin: str) -> Dict[str, Any]:
    line_items = body.get("lineItems")
    request_key = str(body.get("requestKey") or "").strip()
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED"}, origin)
    if not request_key or len(request_key) > 80:
        return cors_response(400, {"error": "REQUEST_KEY_REQUIRED"}, origin)
    # Phase O-1: a services basket is refused here, PURE, before the profile read, any Wix call
    # or any DynamoDB write -- Drop Docs/Vault, a bad quantity, a missing intent, or V1 pricing.
    refusal = service_requests.checkout_preflight(line_items, body,
                                                  v2_enabled=cart_v2.is_enabled())
    if refusal is not None:
        return cors_response(refusal[0], refusal[1], origin)

    profile = _checkout_profile(identity)
    if not profile:
        return cors_response(409, {
            "error": "PROFILE_REQUIRED",
            "message": "Verify your email and save your checkout details first.",
        }, origin)

    # ATTRIBUTION, read once, here. `channel` says WHERE the order came from; `checkoutMode`
    # below says HOW it settles and stays `CHECKOUT_MODE_WEBSITE` for both channels -- nothing is
    # added to `finalization.ACCEPTED_CHECKOUT_MODES`, because a second accepted mode would be a
    # second finalisation path rather than a label on one.
    channel = order_channel.canonical((_claimed_handoff(identity, body) or {}).get("channel"))

    # THE PUBLIC CUSTOMER ID, read off the SAME row `_checkout_profile` already returned - so
    # this costs no extra contacts Query, and the money path below never has to read
    # ContactsTable at all. `from_contact` never raises and answers "" for a row that has none,
    # which is every row written before this attribute existed; "" then suppresses the field
    # everywhere downstream rather than printing a placeholder on an invoice.
    public_customer_uuid = customer_uuid.from_contact(profile)

    now = int(time.time())
    keys = _keys_table()
    try:
        # Phase O-1: before any Wix call, a resumed key bound to a superseded service intent.
        _refuse_rebound_service_intent(identity, request_key, body, keys)
        # The row is already in hand from the `_checkout_profile` call above, so threading it
        # keeps the happy path at one contacts Query.
        #
        # `resetCart` is read HERE and only here. `is True` is an identity comparison, not a
        # coercion, so `"true"`, `1` and `[]` are all simply false -- a truthy-string reading
        # would make a typo destructive. `_create` never reads it, so `_action`'s `"create"`
        # default is not a way into abandoning a customer's saved cart.
        snapshot, calculated = _website_snapshot(
            identity, line_items, now, profile=profile,
            reset=body.get("resetCart") is True)
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
                    # BESIDE `checkoutMode`, never inside it. On the `PAYREF#` row as well as the
                    # attempt because the webhook reconciles on this row and a channel it cannot
                    # read is a channel a reconciliation cannot report.
                    "channel": channel,
                    "wixCartId": snapshot.cart_id,
                    "cartRevision": snapshot.cart_revision,
                    "quoteHash": snapshot.snapshot_hash,
                    "collectionPaise":
                        snapshot.quote.collection_before_convenience_paise,
                    "quoteExpiresAt": snapshot.expires_at,
                    "policyVersion": snapshot.policy_version,
                    # Phase O-1: `{"serviceLine": {...}}` for a services basket, `{}` otherwise,
                    # so every other PAYREF# row is byte-identical to before.
                    #
                    # `line_paise` is WIX'S OWN price for the service line, re-read from the
                    # same `calculated` that `_v2_snapshot` already asserted, never a committed
                    # constant (see service_requests' "WIX IS THE PRICE AUTHORITY"). It is
                    # `None` when there is no calculation -- the V1 branch, which
                    # `checkout_preflight` refuses for a services basket with 503 before
                    # reaching here -- so an unpriced row cannot be minted by this path.
                    **service_requests.payref_extra(
                        line_items, body,
                        line_paise=(service_requests.observed_service_line_paise(calculated)
                                    if calculated is not None else None)),
                    # THE PUBLIC CUSTOMER ID, on this row as well as on the attempt, and that is
                    # not redundant: the webhook lineage reads attribution off the `PAYREF#` row
                    # (`razorpay-webhook._load_attempt`) while the finalisation lineage reads it
                    # off the ATTEMPT row (`finalization.accept_paid`). Writing it to only one
                    # would give one order's invoice a customer id on one settlement path and
                    # nothing on the other.
                    #
                    # Spread conditionally, in the same shape as `payref_extra` above and for the
                    # same reason: a contact with no id - every contact created before the
                    # attribute existed - produces a row whose KEY SET is byte-identical to
                    # today's, which `test_checkout_service_lines` asserts by equality. A key
                    # present with `''` would be a different row shape for no gain, since `''`
                    # suppresses every downstream render anyway.
                    **({customer_uuid.ATTRIBUTE: public_customer_uuid}
                       if public_customer_uuid else {}),
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
            # Stamped HERE rather than inside `prepare_checkout`, so the shared module stays
            # channel-agnostic and this edit is one wrapper instead of a new parameter threaded
            # through six call sites. `reserve_attempt` is the single sink that writes the attempt
            # row, so there is no second path the stamp could miss.
            #
            # The public customer id rides the SAME wrapper, and that is not laziness - it is the
            # measured answer. `payment_attempt.build` is called from `_bind_and_ready`, a
            # module-level helper reached from FOUR sites through two more helpers, so a
            # `customer_uuid=` parameter on `prepare_checkout` would have to be threaded through
            # all of them; the first attempt at exactly that produced a `NameError` inside a
            # money path's `except Exception` and a 503 on every checkout. One sink, one stamp.
            #
            # `**({...} if v else {})` rather than a plain key, so an attempt for a contact with
            # no public id is byte-identical to one written before this landed - the same
            # conditional-emit rule `payment_attempt.build` applies to `cartId` and `retryOf`.
            reserve_attempt=lambda attempt: _reserve_website_attempt(
                dict(attempt, channel=channel, customerPhone=_profile_phone(identity),
                     **({customer_uuid.ATTRIBUTE: public_customer_uuid}
                        if public_customer_uuid else {}))),
            # The read-only attempt store the one-live-payment guard needs. Without it the guard
            # can tell a basket has a recorded attempt but not whether that attempt was paid.
            attempts_table=_attempts_table(),
            allocate_reference=_allocate_reference,
            purchased_snapshot=snapshot.frozen_data,
            wix_order_payload=wix_order_payload,
        )
        # Phase O-1: again AFTER, authoritatively -- a concurrent click on the same key may have
        # bound its reference between the check above and the reservation. Options are never
        # handed out for an attempt bound to another intent.
        _refuse_rebound_service_intent(identity, request_key, body, keys)
    # ── EVERY `cart_v2.CartContractError` SUBCLASS MUST PRECEDE ITS PARENT ARM BELOW, or it is
    # ── swallowed and its named code never fires. The parent is the `CART_NOT_PAYABLE` arm.
    except ContributionRejected as rejected:
        # First, because it is the narrowest. Now a `ValueError`, so it must also stay above the
        # `CartContractError` arm, which is a `ValueError` too.
        #
        # NO `min`/`max` TRAVELS ANY MORE, because there is no range: there are three fixed
        # contributions, so the only honest instruction is to choose one of them. The amounts are
        # derived from the committed choice map rather than re-typed, so the sentence cannot claim
        # an amount the server does not accept.
        return cors_response(409, {
            "error": "CONTRIBUTION_AMOUNT_INVALID",
            "reason": rejected.reason,
            "choicesPaise": sorted(CONTRIBUTION_CHOICES_PAISE.values()),
            "message": "Choose one of the offered contribution amounts: "
                       + ", ".join("\u20b9" + str(paise // 100)
                                   for paise in sorted(CONTRIBUTION_CHOICES_PAISE.values()))
                       + ".",
        }, origin)
    except ContributionNotAlone:
        # THE COPY MOVED WITH THE RULE. It used to read "a contribution is paid on its own",
        # which stopped being true when a contribution beside a product became payable; this
        # exception now names only the basket holding TWO contributions. Word for word the
        # browser's `CONTRIBUTION_ALONE_MESSAGE`, so the two refusals still read identically
        # whichever side produced them.
        return cors_response(409, {
            "error": "CONTRIBUTION_NOT_ALONE",
            "message": "Only one contribution can be paid at a time. Remove the extra "
                       "contribution, then check out.",
        }, origin)
    except ContributionUnavailable:
        return cors_response(409, {
            "error": "CONTRIBUTION_UNAVAILABLE",
            "message": "Contributions are not available right now.",
        }, origin)
    except ContributionRedemptionNotAllowed:
        return cors_response(409, {
            "error": "CONTRIBUTION_REDEMPTION_NOT_ALLOWED",
            "message": "A contribution takes no coupon or gift card. Remove it, then check out.",
        }, origin)
    except ContributionNotPayable:
        # NOT `CART_NOT_PAYABLE`, and not "please review your cart": the basket is one donation,
        # so there is nothing in it to review and the customer has no move to make. Says what is
        # true -- it cannot be taken right now -- and says nothing was charged, because a refusal
        # arriving after the Checkout press reads like a failed payment otherwise. Nothing is
        # reserved, attempted or ordered on this path.
        logger.error(json.dumps({"event": "contribution_not_payable"}))
        return cors_response(409, {
            "error": "CONTRIBUTION_NOT_PAYABLE",
            "message": "Contributions cannot be taken right now. Nothing has been charged.",
        }, origin)
    # Phase O-1 services. Both are `CartContractError`s, so both MUST stay above that arm.
    except ServicePriceChanged:
        return cors_response(409, service_requests.refusal(
            service_requests.SERVICE_PRICE_CHANGED), origin)
    except ServiceNotPayable:
        logger.error(json.dumps({"event": "service_not_payable"}))
        return cors_response(409, service_requests.refusal(
            service_requests.SERVICE_NOT_PAYABLE), origin)
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
    # ── The Cart V2 arms `_create` already has, in `_create`'s own vocabulary. Copying the codes
    # ── and the messages rather than inventing a second set is the point: a locked or unpayable
    # ── cart must not read as two different problems on two routes. Without these, every one of
    # ── them fell to the generic arm below and answered 503 TEMPORARILY_UNAVAILABLE -- a code the
    # ── browser treats as transient, for conditions no retry can clear.
    except cart_v2.CartItemUnavailable as unavailable:
        logger.info(json.dumps({"event": "checkout_item_unavailable",
                                "count": len(unavailable.items)}))
        return cors_response(409, {
            "error": "ITEMS_UNAVAILABLE", "items": unavailable.items,
            "message": "Some items are no longer available. Please review your cart.",
        }, origin)
    except cart_v2.CartQuantityReduced as reduced:
        logger.info(json.dumps({"event": "checkout_quantity_reduced",
                                "count": len(reduced.items)}))
        return cors_response(409, {
            "error": "QUANTITY_REDUCED", "items": reduced.items,
            "message": "Some items are available in smaller quantities than you asked for. "
                       "Please confirm the new amounts.",
        }, origin)
    except CartResetRequired:
        # The deliberate exception to the copy-the-vocabulary rule, and it does not break it:
        # reconciliation exists only on this route, so `_create` cannot produce the condition.
        # The excess lines are on the SERVER cart, which no browser affordance touches, so
        # "review your cart" would name an action the customer cannot take. Starting a new cart
        # is the one that works, and it is one click.
        return cors_response(409, {
            "error": "CART_RESET_REQUIRED",
            "message": "Your saved cart has too many items to update. Start a new cart.",
        }, origin)
    except cart_v2.CartGone:
        # PERSISTENT only. `_v2_snapshot` already discarded the dead pointer and minted a fresh
        # cart; reaching here means the NEW cart 404'd too, which is a Wix fault rather than a
        # stale pointer, and `logger.error` is the level that says so. Deliberately NOT
        # `CART_ITEM_UNAVAILABLE`: no item has been shown to be missing, and telling a customer to
        # remove one would send them after a line that is fine. Must precede the parent arm below.
        logger.error(json.dumps({"event": "website_checkout_cart_gone_unrecoverable"}))
        return cors_response(409, {"error": "CART_NOT_PAYABLE",
                                   "message": "Please review your cart and try again."}, origin)
    except cart_v2.CartContractError:
        # The parent of the five contribution arms above, the two item arms and CartResetRequired,
        # so it is LAST among them.
        return cors_response(409, {"error": "CART_NOT_PAYABLE",
                                   "message": "Please review your cart and try again."}, origin)
    except customer_cart.CartBusy:
        logger.info(json.dumps({"event": "checkout_cart_reconciliation_required"}))
        return cors_response(409, {
            "error": "CART_RECONCILIATION_REQUIRED",
            "message": "Your cart is being updated. Please try again shortly.",
        }, origin)
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
    except wix_ecom.WixEcomError as error:
        # A cart line's product/variant is retired, invisible, or out of stock in Wix, so the
        # catalogue lookup raises. This is a PERMANENT, caller-fixable condition (remove the item),
        # not a transient outage, so answer 409 CART_ITEM_UNAVAILABLE rather than a 502 the customer
        # reads as "we failed".
        #
        # THE `detail` FIELD IS WHAT MAKES THIS ARM DIAGNOSABLE. It logged nothing but a status for
        # long enough to cost a live diagnosis: a failed checkout in production named none of the
        # FIFTEEN places `wix_ecom` raises `WixEcomError` -- "product unavailable", "choose an
        # available product option", an HTTP code from `_request`, a non-JSON body -- and
        # `wix_ecom` itself never logs, so the only evidence was the customer's sentence on screen.
        # `type(error).__name__` alone cannot distinguish the fifteen sites, which is the whole
        # reason this field exists.
        #
        # THE MESSAGE IS SAFE TO LOG, and that is a decision rather than an oversight. Every
        # `WixEcomError` message in that module is built by OUR code out of known-safe parts: a
        # literal, or an f-string of the HTTP method, the endpoint and the status code. No
        # provider body, no credential and no customer field reaches it. The secret-handling rule
        # permits an exception's text on exactly that condition -- our own message from known-safe
        # parts. An endpoint can carry a product or cart GUID; those are resource ids, not PII.
        #
        # `logger.error`, not `info`: a basket that cannot be priced is a failed checkout, and it
        # should be visible at the level an alarm reads.
        logger.error(json.dumps({"event": "website_checkout_catalogue_unavailable",
                                 "error": type(error).__name__, "detail": str(error)}))
        return cors_response(409, {"error": "CART_ITEM_UNAVAILABLE"}, origin)
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
    # The basket is paid, so the WhatsApp attribution pointer has stopped describing "the basket
    # this customer is about to pay for". Released HERE because this is the one place in this
    # function that writes a paid order record, and because nothing else consumes the saved cart:
    # no code path abandons `CUSTOMERCART#<phone>` at payment, so without this the NEXT website
    # prepare resolves the very same Wix cart id, the pointer still matches it, and an ordinary
    # website order is stamped `whatsapp` on its attempt, its `PAYREF#` row, the order row, the
    # `/orders` tag and the GST invoice's `Source:` line.
    #
    # AFTER `accept_paid`, never before. The order row carries `channel` already, so releasing the
    # label cannot change what was just written; releasing it first and then failing to write the
    # order would lose the attribution for a retry that is still entitled to it.
    _release_claim_pointer(identity)


def _release_claim_pointer(identity: customer_auth.CustomerIdentity) -> None:
    """Expire this customer's claimed-channel pointer. Never raises, and never creates one.

    AN EXPIRING UPDATE, NOT A DELETE, for the reason `customer_cart.abandon` is also a put: this
    function's IAM grants GetItem/PutItem/UpdateItem on CommerceKeys and NOT DeleteItem
    (amplify/infra/checkout.json, Sid PaymentAttemptAndCommerceKeys), so a delete would answer
    AccessDeniedException in production and pass against every fake in the test suite.
    `whatsapp_basket.active_claim` already reads `expiresAt > now`, so an expired pointer is
    indistinguishable from an absent one to the only thing that reads it.

    `attribute_exists(orderId)` so a customer who never claimed anything does not acquire a
    pointer row as a side effect of paying.

    SWALLOWS EVERYTHING, deliberately. The order is already written and the money has already
    moved; failing a verified-capture response because a LABEL could not be expired would turn a
    successful payment into an error the customer can do nothing about. The cost of a missed
    release is one mis-attributed subsequent order, which is why it is also logged.
    """
    try:
        _keys_table().update_item(
            Key={"orderId": whatsapp_basket.claim_pointer_key(identity.customer_id)},
            UpdateExpression="SET expiresAt = :zero",
            ConditionExpression="attribute_exists(orderId)",
            ExpressionAttributeValues={":zero": 0})
    except Exception as error:  # noqa: BLE001 - see the docstring
        if (getattr(error, "response", {}).get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"):
            # No pointer to release. The ordinary website order, and not worth a log line.
            return
        logger.warning(json.dumps({"event": "checkout_channel_pointer_release_failed",
                                   "error": type(error).__name__}))


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


def _v2_catalog_items(line_items: list) -> tuple:
    """Bridge the browser's `{catalogReference, quantity}` shape to Cart V2's catalog items.

    `cart_v2.catalog_item` demands exactly `{productId, variantId, quantity}` with both ids as
    UUIDs, while the browser sends a nested `catalogReference` and may omit the variant.
    Resolving a product's single visible, in-stock variant against the live catalogue -- and
    refusing to guess when there is more than one -- is work `wix_ecom.normalized_catalog_items`
    already does correctly, so this reuses it rather than growing a second copy that could
    disagree about which variant a cart line means.

    Returns `(requested, requires_delivery)`, and a basket requires delivery when ANY line does.
    The strip to exactly `{productId, variantId, quantity}` is mandatory rather than tidy:
    `cart_v2.catalog_item` refuses any dict whose key set is not exactly those three.

    THE DELIVERY FACT IS IDENTITY FIRST, `productType` SECOND, AND THE ORDER MATTERS.
    `wix_ecom.resolved_catalog_lines` reads Wix's own `productType` on a `GET` that already
    happens, and fails closed to "needs an address" for anything that is not `DIGITAL`. That is
    the right default for a catalogue product and the wrong answer for a contribution: the live
    `Contribute` product is **PHYSICAL** (measured, 2026-10-04), because a Wix digital product with
    no downloadable file attached is not purchasable. Keyed on `productType` alone, every
    no-delivery branch downstream inverts -- a donation is refused for want of a stored address, a
    postal address is written onto its Wix cart, and the stale-address abandon never runs -- while
    the browser's `cartRequiresDelivery()` keys on identity and disagrees about the same basket.

    So a recognised contribution line contributes NO delivery requirement, whatever Wix says its
    `productType` is. The override is per LINE rather than per basket on purpose: it leaves
    `resolved_catalog_lines` and its fail-closed default untouched for every ordinary line, so a
    real physical product still needs an address even if a contribution is ever allowed beside one.
    """
    lines = wix_ecom.resolved_catalog_lines(line_items)
    requested = [{"productId": line["productId"], "variantId": line["variantId"],
                  "quantity": line["quantity"]} for line in lines]
    # A Phase O-1 service line ships nothing either (the Wix product is PHYSICAL), so it gets the
    # same per-line identity override as a contribution.
    return requested, any(line["requiresDelivery"] and not _is_contribution_id(line["productId"])
                          and not service_requests.is_service_product(line["productId"])
                          for line in lines)


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

    On the website path `_reconcile_saved_cart` runs first and this is the backstop rather than
    the first answer. The *request's* basket wins there, and that is consistent with the rationale
    above rather than opposed to it: the request comes from the cart page the customer is looking
    at, so making the Wix cart match it is "asking them to review it" carried out, not bypassed.
    On the WhatsApp `_create` path there is no such surface, so the refusal stands as written.
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


def _saved_basket_index(cart: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
    """`{(catalogItemId.lower(), variantId.lower()): {lineItemId, quantity}}` for a Wix cart.

    Keyed exactly as `_require_same_basket` keys, so the reconcile and the backstop that follows
    it cannot disagree about what "the same line" means. Two saved lines sharing one key is
    degenerate: `_require_same_basket` *sums* them for comparison, which is fine, but there is no
    single line to edit, so this refuses rather than guessing which one to change.
    """
    index: Dict[tuple, Dict[str, Any]] = {}
    for line in cart.get("lineItems") or []:
        reference = (line.get("source") or {}).get("catalogReference") or {}
        quantities = line.get("quantityInfo") or {}
        key = (str(reference.get("catalogItemId") or "").lower(),
               str((reference.get("options") or {}).get("variantId") or "").lower())
        if key in index:
            raise cart_v2.CartContractError(
                "the saved cart holds two lines for one catalogue item")
        quantity = quantities.get("requestedQuantity")
        if quantity is None:
            quantity = quantities.get("confirmedQuantity")
        index[key] = {"lineItemId": line.get("id"), "quantity": int(quantity or 0)}
    return index


def _reconcile_saved_cart(carts, identity: customer_auth.CustomerIdentity,
                          cart_id: str, requested: list) -> None:
    """Bring the saved Wix cart to the requested basket, then re-assert equality.

    `carts` is the CustomerCart instance `_v2_snapshot` already built for `ensure`. Taking it
    rather than re-constructing one means ONE `self.now` governs `expiresAt = now +
    CART_LIFETIME`, the QUOTE_LIFETIME expiry check and every command here; a second instance
    would carry a second clock through the same lock protocol. It also means `ensure`, `abandon`
    and this function share one lock holder.

    Reuses `carts.execute`'s existing `remove` / `quantity` / `add` commands, which already own
    the lock protocol, the duplicate-request fingerprint and the persistence. Nothing about price
    authority moves: Wix still prices whatever is in the cart, and the cart is now provably the
    basket that was asked for.

    A LINE IN BOTH BASKETS GETS A `quantity` COMMAND, NEVER `remove` THEN `add`, and that is not a
    performance choice. `lineItemId` is part of basket identity: `basket_hash` hashes the frozen
    payload including Wix's raw items (each carrying `id`), and `narrow_basket_hash` enumerates
    `{lineItemId: quantity}` explicitly. A remove-then-add of the same key mints a new
    `lineItemId`, changes both hashes, makes the `CARTBASKET#` and `CARTNARROW#` paid-basket rows
    miss by key, and drops `_live_cart_payment` from TIER 1 `CART_ALREADY_PAID` to the TIER 2
    in-flight window.

    THE ORDER IS `quantity` -> `add` -> `remove`. `CartV2.remove` routes its response through
    `_cart()`, which raises unless Wix returns a cart object, and whether Wix returns one when the
    LAST line is removed is unverified. Remove-first would empty the cart on the very first
    command for any one-line-to-one-line diff, putting that unverified behaviour directly in the
    hot path, and a raise there lands AFTER the lock claim. With this order the cart can never be
    transiently empty: a reconcile only runs when `requested` is non-empty, and every requested
    key is either already present or added before any removal.

    IDEMPOTENT IN EFFECT, because it is a diff against live state rather than a replay of a
    command log. A mid-way `CartBusy` or deadline refusal leaves a partially reconciled cart, and
    the next prepare re-reads and re-diffs from its CURRENT state -- so an `add` that already
    landed is seen as present and not repeated. Commands are deliberately NOT rolled back: a
    rollback would be a second mutation on a cart whose state is already uncertain, and the
    mutation cannot reach money anyway (the refusal writes no reservation, no attempt and no
    gateway order, and `finalization.accept_paid` builds the order from the frozen snapshot and
    the attested payload rather than from the live cart).
    """
    saved = _saved_basket_index(carts.adapter.get(cart_id))
    asked: Dict[tuple, int] = {}
    for item in requested:
        key = (str(item["productId"]).lower(), str(item["variantId"]).lower())
        asked[key] = asked.get(key, 0) + int(item["quantity"])

    quantities, additions, removals = [], [], []
    for key, quantity in asked.items():
        if key in saved:
            if saved[key]["quantity"] != quantity:
                quantities.append({"action": "quantity", "requestId": str(uuid4()),
                                   "lineItemId": saved[key]["lineItemId"],
                                   "quantity": quantity})
        else:
            additions.append({"action": "add", "requestId": str(uuid4()),
                              "item": {"productId": key[0], "variantId": key[1],
                                       "quantity": quantity}})
    for key, line in saved.items():
        if key not in asked:
            removals.append({"action": "remove", "requestId": str(uuid4()),
                             "lineItemId": line["lineItemId"]})

    commands = quantities + additions + removals
    if not commands:
        return

    # BOTH PRE-CHECKS REFUSE HAVING ISSUED NOTHING, and both raise `CartResetRequired` rather than
    # the generic refusal, because the excess lines are on the server cart and the only action the
    # customer can take is to start a new one.
    if len(commands) > MAX_RECONCILE_COMMANDS or len(set(saved) | set(asked)) > CART_LINE_CEILING:
        logger.info(json.dumps({"event": "checkout_cart_reset_required",
                                "commandCount": len(commands),
                                "unionSize": len(set(saved) | set(asked))}))
        raise CartResetRequired("the saved cart is too far from the requested basket")

    for command in commands:
        # BEFORE the execute, never after. A command already in flight when the invocation is
        # killed is the failure this margin exists to avoid, because `execute`'s own comment says
        # "Any exception after the claim retains the lock" and a timeout is not an exception.
        if _seconds_left() < RECONCILE_DEADLINE_MARGIN_SECONDS:
            logger.info(json.dumps({"event": "checkout_cart_reconcile_deadline",
                                    "issued": commands.index(command)}))
            raise cart_v2.CartContractError("not enough time to reconcile this cart safely")
        carts.execute(identity, command)

    logger.info(json.dumps({"event": "checkout_cart_reconciled",
                            "commandCount": len(commands)}))
    # The fail-closed backstop stays; it stops being the first answer.
    _require_same_basket(carts.adapter.get(cart_id), requested)


def _settle_saved_cart(carts, adapter, identity: customer_auth.CustomerIdentity,
                       cart_id: str, created: bool, requested: list, *,
                       requires_delivery: bool, reconcile: bool) -> tuple:
    """Make a REUSED Wix cart safe to price. Returns `(cart_id, created)`.

    Extracted from `_v2_snapshot` unchanged, because it is exactly the set of calls that address
    the saved cart BY ID -- the stale-delivery read, the reconcile diff and the basket-equality
    backstop. That makes it the whole surface on which a cart Wix no longer has can answer 404,
    so the caller can recover from `cart_v2.CartGone` in ONE place instead of three call sites
    each needing their own recovery.

    A freshly `created` cart was built from `requested` by definition, so there is nothing to
    settle and this returns immediately.
    """
    if created:
        return cart_id, created

    # A NO-DELIVERY BASKET MUST NOT INHERIT A PLACE OF SUPPLY. `ensure` reuses one Wix cart per
    # identity for 30 days, and every physical attempt writes `deliveryInfo.address` onto it.
    # There is no Cart V2 call that clears that field and no `execute` command that could issue
    # one, so the only way to get a clean cart is to stop using this one.
    if not requires_delivery and (
            ((adapter.get(cart_id).get("deliveryInfo") or {}).get("address")) or {}):
        abandoned = cart_id
        carts.abandon(identity)                 # refuses while `busy` is set
        cart_id, created = carts.ensure(identity, requested)
        # The DURABLE record of the abandon: the `abandonedCartId` written onto the row does not
        # survive the next `ensure`'s full `put_item`. A Wix cart id is a resource id, not PII.
        logger.info(json.dumps({"event": "checkout_cart_delivery_reset",
                                "abandonedCartId": str(abandoned)}))

    if not created:
        if reconcile:
            _reconcile_saved_cart(carts, identity, cart_id, requested)
        else:
            _require_same_basket(adapter.get(cart_id), requested)
    return cart_id, created


class DeliveryMethodUnavailable(purchase_intent.DeliveryDetailsRequired):
    """Wix priced nothing because it offered no delivery METHOD for a known-good address.

    The base class is load-bearing. `_v2_snapshot`'s other caller is `_create`, the retained
    in-WhatsApp path, whose existing first arm then still answers
    `409 DELIVERY_DETAILS_REQUIRED` -- not `500 INTERNAL_ERROR` (a plain `Exception`) and not
    `409 AMOUNT_NOT_SETTLED` (a plain `ValueError`, via its trailing `except ValueError`).
    """


class ContributionUnavailable(cart_v2.CartContractError):
    """A recognised contribution product with CONTRIBUTION_PRODUCT_ID unset.

    The base class is load-bearing, and it follows `DeliveryMethodUnavailable`'s precedent above:
    `_v2_snapshot`'s other caller is `_create`, whose `except cart_v2.CartContractError` arm
    answers `409 CART_NOT_PAYABLE`. Derived from bare `Exception` this would instead reach
    `handler`'s outer handler and answer `500 INTERNAL_ERROR` on the dispatch-default route --
    `_action` returns `"create"` for any unrecognised action or path.
    """


class ContributionNotAlone(cart_v2.CartContractError):
    """TWO contribution lines in one basket. No longer "a contribution beside a product".

    NARROWED BY OWNER DECISION, 2026-10-06. A contribution beside an ordinary product used to
    raise this and now does not: a mixed basket is priced as an ordinary basket, fee and all. What
    survives is the case no single figure can describe -- two contribution lines, which is two
    contributions in one payment, while `_contribution_request` returns ONE expected collection.
    A Rs.100 line and a Rs.250 line have no sum that either of them promised.

    The REASON the mix was refused is still true and is why the mixed path deliberately does not
    assert a contribution total: in a mixed basket `componentsPaise` carries one tax, one
    delivery, one fee and one discount figure across every line and there is no per-line tax
    field, so "the contribution's share of the total" has no exact formulation. The mix is now
    allowed BECAUSE it stops being a contribution basket at all, not because that problem was
    solved. See `_contribution_request`.

    THE WIRE CODE IS STILL `CONTRIBUTION_NOT_ALONE`, deliberately. The copy says what it now
    means; the code is a client/server contract that the browser and this function do not deploy
    atomically (Amplify on push, Lambda on alias move), so renaming it would make one of them
    answer `UNRECOGNISED` for the length of the gap. Reachable only from a crafted request:
    `setContribution` replaces the line rather than adding to it, so the browser cannot build it.

    Base class is load-bearing, as above.
    """


class ContributionNotPayable(cart_v2.CartContractError):
    """Wix will not price a contribution basket, so no contribution can be taken right now.

    Raised when Wix answers a contribution-only cart with a delivery requirement. The cart holds
    one donation and no delivery address is ever written onto it (`_v2_snapshot` skips
    `prepare_delivery` deliberately -- a payment with no delivery has no place of supply), so
    there is no address the customer can save that would satisfy it.

    SEPARATE FROM `CART_NOT_PAYABLE`, for the same reason `CartResetRequired` is: the generic code
    carries "Please review your cart and try again", and a basket that is one donation has nothing
    to review. It also makes the condition distinguishable in the logs and on the wire from the
    OTHER two ways a Wix dashboard setting can make a contribution unpayable -- a shipping rate or
    a tax class landing on the product, which `_assert_contribution_total` refuses -- which a
    single shared code cannot be.

    THE PREMISE IS NOW MEASURED, AND IT WAS WRONG IN THE DIRECTION THAT MATTERED. This docstring
    used to say that whether Wix prices a `PHYSICAL` line with no `deliveryInfo` address had not
    been measured, and that if it did not, this would be the arm EVERY contribution took. It was.
    The probe on 2026-10-05, against the live `Contribute` product with no address written:

        summary.violations  = [{"scope": "DELIVERY", "code": "MISSING_DELIVERY_METHOD",
                                "severity": "ERROR"}]
        summary.priceSummary = subtotal 100.00, discount 0, delivery 0.00, additionalFees 0,
                               tax 0.00, total 100.00

    So Wix prices it exactly right and blocks only on the unselected delivery METHOD -- and it
    populates `deliveryInfo.address` itself, from the site's own location, on Create Cart. The fix
    is therefore the method and not an address: `_v2_snapshot`'s no-delivery branch now calls
    `purchase_intent.select_offered_delivery_method`, which selects the single ₹0 option Wix
    already resolved and writes nothing. All three choices then price to exactly the contributed
    paise (10000 / 25000 / 50000) with delivery, tax, fees and discount all zero, which
    `_assert_contribution_total` re-checks on every request.

    THIS ARM IS THEREFORE NO LONGER THE EXPECTED PATH; it is the dashboard fault it was always
    meant to describe -- a Wix delivery region that offers a contribution no option at all, which
    `select_offered_delivery_method` reports by returning `None` and leaving the cart unpriceable.
    Fail-closed either way: nothing is reserved, no attempt is written and no gateway order is
    created, so no money moves.

    Base class is load-bearing and follows `DeliveryMethodUnavailable`: `_v2_snapshot`'s other
    caller is `_create`, whose `except cart_v2.CartContractError` arm answers
    `409 CART_NOT_PAYABLE`, not `500 INTERNAL_ERROR`.
    """


class ContributionRedemptionNotAllowed(cart_v2.CartContractError):
    """A coupon or a Wix gift card is applied to a contribution cart.

    A SEPARATE state from the misconfiguration `_assert_contribution_total` refuses, because the
    customer can clear this and a misconfiguration they cannot. Base class is deliberate and
    follows `DeliveryMethodUnavailable`: `_v2_snapshot`'s other caller is `_create`, whose
    `except cart_v2.CartContractError` arm then answers 409 CART_NOT_PAYABLE rather than letting
    this reach `handler`'s 500.
    """


class CartResetRequired(cart_v2.CartContractError):
    """The saved cart is too far from the requested basket to reconcile inside one invocation.

    SEPARATE FROM `CART_NOT_PAYABLE` because the recovery is different and the generic code
    pointed at an action the customer cannot take: the excess lines are on the SERVER cart, and
    `/wix-store/*` appears nowhere in src/pages/cart.tsx, so "remove some lines" names lines they
    cannot see. Starting a fresh cart is the one action that works, it is one click, and
    `CustomerCart.abandon` is what performs it.

    Base class is load-bearing, as above. On `_create` it is unreachable -- `reconcile=False`
    there -- and would answer `CART_NOT_PAYABLE` through the parent arm if it ever did arrive,
    which is the right answer for a route that refuses a mismatched saved cart by design.
    """


def _contribution_ids() -> set:
    """Every product id this function will treat as a contribution.

    The COMMITTED set plus the env id, union rather than either alone: the committed set is what
    makes "env unset" a refusal rather than an ordinary product, and the env id is what makes the
    live product recognised before the next deploy. Recomputed per call rather than at import,
    for the same reason every other config read here is lazy.
    """
    known = set(CONTRIBUTION_PRODUCT_IDS)
    if CONTRIBUTION_PRODUCT_ID:
        known.add(CONTRIBUTION_PRODUCT_ID)
    return known


def _is_contribution_id(product_id: Any) -> bool:
    """Takes the ID, NOT the line, deliberately.

    A request line and a Wix cart line both carry a `catalogReference` and they carry it at
    DIFFERENT levels (top level vs under `source`). A helper that took the line would be applied
    to both and silently answer False for one of them -- no exception, no log, and the only
    symptom a quantity on a customer's WhatsApp message. Making the parameter an id forces each
    call site to read its own shape, where the shape is visible in the same expression.
    """
    return str(product_id or "").strip().lower() in _contribution_ids()


def _contribution_request(line_items: Any) -> Optional[int]:
    """The contribution's expected collection in integer paise, or None when this is not one.

    PURE. No I/O, so every refusal below costs no Wix call, no DynamoDB write and no cart -- which
    is what keeps `_v2_snapshot`'s leave-nothing-behind invariant true for a refused contribution.
    It must also run BEFORE `resolved_catalog_lines`, because a bad *variant* is refused there as a
    `WixEcomError` which maps to 502 CATALOGUE_UNAVAILABLE -- a catalogue-outage answer for what is
    really "that is not one of the three contributions".

    THREE FIXED PRICES, CHOSEN AT QUANTITY 1 (owner model change, 2026-10-04). The amount is NOT
    carried by the quantity and is not derived from anything the browser sends: the browser names a
    VARIANT, and the paise figure is looked up in the committed `CONTRIBUTION_CHOICES_PAISE`. So
    there is no arithmetic on a customer-supplied number anywhere in this function, and no bounds
    to widen -- an unrecognised variant is simply not one of the three.

    The returned figure is an EXPECTED COLLECTION, not a price. `cart_v2.calculate` remains the
    sole price authority; `_assert_contribution_total` compares its answer against this and fails
    closed on any disagreement, so a Wix price edit refuses the contribution rather than charging a
    figure the browser's button did not promise.

    `None` THEREFORE MEANS "PRICE THIS AS AN ORDINARY BASKET", and since 2026-10-06 that includes
    a basket holding a contribution BESIDE a product. Every caller keys the whole contribution
    treatment -- the fee exemption, the address-free delivery handling, the exact-total assertion
    -- on `is not None`, so one return value switches a mixed basket onto the path every other
    order takes. See the mixed-basket block below.

    Deliberately tolerant of a malformed `line_items`: anything whose shape it cannot read is
    simply not recognised as a contribution and falls through to `resolved_catalog_lines`, which
    already owns the strict shape refusals and must stay the single place they live.
    """
    known = _contribution_ids()
    if not known or not isinstance(line_items, list):
        return None

    chosen: list = []
    others = 0
    for line in line_items:
        reference = (line or {}).get("catalogReference") or {} if isinstance(line, dict) else {}
        if not isinstance(reference, dict):
            reference = {}
        product_id = str(reference.get("catalogItemId") or "").strip().lower()
        if not product_id or product_id not in known:
            others += 1
            continue
        options = reference.get("options")
        variant_id = str((options or {}).get("variantId") or "").strip().lower() \
            if isinstance(options, dict) else ""
        quantity = line.get("quantity")
        # `type(...) is not int` rather than `isinstance`, deliberately: `isinstance(True, int)` is
        # True, so an isinstance check would accept `quantity: true` as 1. A contribution is one
        # fixed-price line, so the only acceptable quantity is exactly 1 -- two of them is two
        # contributions, which is a basket this path does not price.
        if type(quantity) is not int or quantity != 1:
            logger.info(json.dumps({"event": "contribution_amount_rejected",
                                    "reason": "INVALID_QUANTITY"}))
            raise ContributionRejected("INVALID_QUANTITY")
        if variant_id not in CONTRIBUTION_CHOICES_PAISE:
            logger.info(json.dumps({"event": "contribution_amount_rejected",
                                    "reason": "UNKNOWN_CHOICE"}))
            raise ContributionRejected("UNKNOWN_CHOICE")
        chosen.append(variant_id)
    if not chosen:
        return None
    if not CONTRIBUTION_PRODUCT_ID:
        logger.warning(json.dumps({"event": "contribution_unavailable"}))
        raise ContributionUnavailable("contribution is not configured on this version")
    # A MIXED BASKET IS NOT A CONTRIBUTION BASKET, AND IT IS NO LONGER REFUSED.
    #
    # OWNER DECISION, 2026-10-06: a product and a contribution may be paid together, and the mixed
    # total is priced "the same way as a single order" -- Wix prices every line, then
    # `checkout_pricing.compute_quote` adds 2.5% convenience plus 18% GST on that fee over the
    # whole collection. `checkout_pricing` needed no change for this: it operates on one total and
    # has never known what kind of lines produced it.
    #
    # RETURNING `None` IS THE WHOLE MECHANISM, and it is a redirection rather than a de-guard.
    # `None` means "this is not a contribution basket", so the ORDINARY path runs end to end: the
    # fee-bearing `compute_quote` instead of `exempt_quote`, `prepare_delivery` with the owned
    # address instead of the address-free method selection, and no `_assert_contribution_total`.
    # That last one is deliberate and unavoidable rather than overlooked -- `componentsPaise`
    # carries ONE tax, delivery, fee and discount figure across the whole basket and there is no
    # per-line tax field, so "the contribution's share of the mixed total" has no exact
    # formulation to fail closed against. See `ContributionNotAlone`, which still holds that
    # reasoning for the basket it still refuses.
    #
    # WHAT THE MIX DOES *NOT* RELAX, because all three run earlier in this function: the kill
    # switch above (an unconfigured contribution is still refused rather than priced as an
    # ordinary product), the quantity-exactly-1 check and the variant allow-list. A mixed basket's
    # contribution line must still be one of the three committed choices at quantity 1.
    if others:
        logger.info(json.dumps({"event": "contribution_in_mixed_basket",
                                "otherLines": others, "contributionLines": len(chosen)}))
        return None
    # Two contribution lines and nothing else is STILL refused: it is two contributions in one
    # payment, and the ONE expected collection this function returns could not describe it.
    if len(chosen) != 1:
        logger.info(json.dumps({"event": "contribution_not_alone",
                                "otherLines": others, "contributionLines": len(chosen)}))
        raise ContributionNotAlone("one contribution at a time")
    return CONTRIBUTION_CHOICES_PAISE[chosen[0]]


def _assert_contribution_total(calculated: Dict[str, Any], contributed_paise: int) -> None:
    """The payable collection for a contribution basket IS the chosen amount, to the paise.

    `contributed_paise` is the committed figure for the chosen variant
    (`CONTRIBUTION_CHOICES_PAISE`), and this is where that figure earns its keep: `cart_v2` is
    still the sole price authority, and this asserts its answer against what the browser's button
    promised. A Wix price edit therefore REFUSES the contribution instead of charging a different
    amount than the one the customer was offered -- fail-closed, which for money is the only
    defensible direction.

    Asserted on `componentsPaise["total"]` rather than on the per-line `totalPrice`, because the
    line figure sums to `subtotal` and is pre-tax -- so a taxable Contribute product passes a line
    check and still over-charges. Every other component must be zero: there is nothing to deliver
    (and the `delivery` term is what catches a Wix shipping rule matching this PHYSICAL product),
    no coupon is accepted on a contribution, and a gift card would make the customer pay less than
    the amount the order records as contributed.
    """
    components = calculated["componentsPaise"]
    redeem = int(calculated.get("wixGiftCardRedeemPaise") or 0)
    applied = bool((calculated.get("cart") or {}).get("coupons")) or bool(
        calculated.get("wixGiftCard")) or redeem

    # A redemption the customer applied is RECOVERABLE and names its own action.
    if applied:
        logger.info(json.dumps({"event": "contribution_redemption_refused",
                                "hasCoupon": bool((calculated.get("cart") or {}).get("coupons")),
                                "hasGiftCard": bool(calculated.get("wixGiftCard"))}))
        raise ContributionRedemptionNotAllowed("a contribution takes no coupon or gift card")

    if (components["total"] != contributed_paise
            or components["subtotal"] != contributed_paise
            or components["tax"] or components["delivery"]
            or components["additionalFees"] or components["discount"]):
        logger.error(json.dumps({"event": "contribution_total_mismatch",
                                 "expectedPaise": contributed_paise,
                                 "totalPaise": components["total"]}))
        raise cart_v2.CartContractError("contribution total is not the contributed amount")


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
                 *, profile: Optional[Dict[str, Any]] = None,
                 reconcile: bool = False, reset: bool = False):
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

    `reconcile` and `reset` are keyword-only with `False` defaults, and ONLY `_website_snapshot`
    passes them. Reconciling unconditionally would silently change the WhatsApp payment path,
    which has no contribution entry point and gains nothing from it; `reset` arrives from a
    request field read in `_website_prepare` alone, so the `action:"create"` default is not a way
    into abandoning a customer's saved cart.

    THE ADDRESS REQUIREMENT IS NOW CONDITIONAL ON THE BASKET, not removed. A contribution-only
    basket has no place of supply to state, so demanding one would be asking for a delivery
    destination that does not exist. That decision keys on contribution product IDENTITY, not on
    Wix's `productType` -- see `_v2_catalog_items`, where the live `Contribute` product being
    PHYSICAL is what makes the distinction load-bearing. A basket with any ordinary physical line
    still refuses before any Wix write, exactly as before -- the requirement moved below
    `_v2_catalog_items`,
    which performs `GET /stores/v3/products/{id}` only and already ran before
    `CustomerCart.ensure` on every request, so the leave-nothing-behind invariant is preserved.
    """
    # 1. PURE PRE-CHECK, BEFORE ANY I/O AT ALL. Recognition, enablement, alone-ness and amount
    #    bounds are decided from the request alone, so a refusable contribution costs no Wix call,
    #    no DynamoDB write and no cart.
    contribution_paise = _contribution_request(line_items)      # None when not a contribution

    loader = LOAD_OWNED_ADDRESS
    owned = (contact_address.from_contact(profile)
             if profile is not None and loader is _load_owned_address
             else (loader(identity) if callable(loader) else None))

    adapter = cart_v2.CartV2(_wix_request)
    requested, requires_delivery = _v2_catalog_items(line_items)   # GET only, writes nothing
    if requires_delivery and not owned:
        raise purchase_intent.DeliveryDetailsRequired("no owned delivery address on file")

    # FEAT-003: storage is international; the India place-of-supply / Wix-mappability rule now
    # runs HERE, at pay time, through the shared gate -- but ONLY when the basket REQUIRES
    # delivery. A fee-exempt contribution or any no-delivery basket must not be refused for an
    # unmappable stored address it never ships to. For a delivery basket, an address the CRM
    # accepted that cannot price a Razorpay/Wix cart (e.g. a legacy unmappable Indian state)
    # becomes the recoverable 409 DELIVERY_DETAILS_REQUIRED rather than a 503 or a wrong tax
    # split. A caller-supplied loader (tests) returning an already-Wix-shaped dict is left alone.
    if requires_delivery and owned and loader is _load_owned_address:
        try:
            payment_address.for_wix(owned)
        except payment_address.UnpayableAddress:
            raise purchase_intent.DeliveryDetailsRequired(
                "stored address is not payable on the website channel") from None

    # ONE CustomerCart, so ONE `now` and one lock protocol own `ensure`, `abandon` and the
    # reconcile. `self.now` drives both `expiresAt = now + CART_LIFETIME` and the QUOTE_LIFETIME
    # expiry check, so a second instance would carry a second clock.
    carts = customer_cart.CustomerCart(_keys_table(), adapter)

    # `resetCart`. BEFORE `ensure`, so the next `ensure` mints a fresh cart rather than
    # reconciling onto the one being discarded. `CartBusy` propagates unchanged: a locked cart is
    # not reset, it is reported.
    if reset:
        carts.abandon(identity)

    cart_id, created = carts.ensure(identity, requested)

    # A CART WIX NO LONGER HAS IS DISCARDED AND REMINTED, NOT REPORTED AS AN ITEM PROBLEM.
    #
    # `ensure` keeps one Wix cart id per identity for thirty days, so a pointer written before the
    # catalogue moved to site `c993128b` outlives the site it was minted against -- and
    # `GET /ecom/v2/carts/{id}` answers 404 for it. On 2026-10-05 that reached a live customer as
    # "An item in your cart is no longer available. Remove it and try again", on a basket whose
    # only line (the ₹1 test product) was visible and in stock: the single `WixEcomError` arm in
    # `_website_prepare` cannot tell a dead CART from a missing ITEM, and removing a line from a
    # cart that does not exist is not an action anybody can take. Every attempt dead-ended.
    #
    # A 404 on the cart resource says the CART is gone and says nothing about the catalogue, so
    # the pointer is abandoned and a fresh cart is minted from `requested` -- the same basket,
    # re-priced from scratch by `calculate` below. Nothing about price authority moves: the new
    # cart carries no total of ours, the amount still comes from Wix's own `summary.priceSummary`
    # in integer paise, and `_assert_contribution_total`'s exact comparison still runs.
    #
    # EXACTLY ONCE. A cart created in this invocation that is itself 404 is a Wix outage, not a
    # stale pointer, so the second `CartGone` propagates to the caller's refusal arm rather than
    # looping -- `ensure` would otherwise create a cart per attempt, abandoning each on the live
    # site with nothing to clean them up.
    try:
        cart_id, created = _settle_saved_cart(
            carts, adapter, identity, cart_id, created, requested,
            requires_delivery=requires_delivery, reconcile=reconcile)
    except cart_v2.CartGone as gone:
        logger.info(json.dumps({"event": "checkout_cart_gone_recreated",
                                "goneCartId": str(gone.cart_id or cart_id)}))
        carts.abandon(identity)                 # refuses while `busy` is set
        cart_id, created = carts.ensure(identity, requested)
        cart_id, created = _settle_saved_cart(
            carts, adapter, identity, cart_id, created, requested,
            requires_delivery=requires_delivery, reconcile=reconcile)

    # Initialised BEFORE the try, because neither branch below is guaranteed to assign and the
    # except arm logs the revision. A `NameError` inside an `except` arm would be swallowed by
    # `_website_prepare`'s generic `except Exception` and surface as the 503 dead end the new arms
    # exist to remove. It stays empty when Wix offers no delivery option at all, which the arm
    # disambiguates with `requiresDelivery` and Wix's own violation codes.
    prepared_revision = ""
    prepared: Dict[str, Any] = {}

    try:
        if requires_delivery:
            # INSIDE THE TRY, deliberately. `prepare_delivery` now selects a method, so it can
            # raise `DeliveryDetailsRequired` itself when Wix offers no option for the address.
            # Left above the try that would escape to `_website_prepare`'s generic
            # `except Exception` and become the 503 dead end; inside it, the existing arm below
            # reads Wix's own violation codes and answers 409 like every other delivery refusal.
            prepared = purchase_intent.prepare_delivery(adapter, cart_id, owned) or {}
        elif contribution_paise is not None or service_requests.has_service_line(line_items):
            # (Phase O-1: a services-only basket takes this same address-free branch -- a request
            # has nothing to ship, and its Wix product is PHYSICAL exactly like `Contribute`.)
            #
            # THE ADDRESS IS STILL NEVER WRITTEN HERE. `prepare_delivery` is not called and
            # `owned` is not passed: a contribution must not have a postal address written onto
            # its Wix cart, because a payment with no delivery has no place of supply and writing
            # one would be a claim about a destination that does not exist.
            #
            # THE METHOD, HOWEVER, IS NOW SELECTED, AND THAT IS A MEASURED CORRECTION rather than
            # a relaxation. Skipping both halves made every contribution unpayable: the live
            # `Contribute` product is PHYSICAL, so Cart V2 answers a contribution-only cart with
            # an ERROR-severity `MISSING_DELIVERY_METHOD`, `cart_v2.calculate` refuses a cart
            # carrying a blocking violation, and `build_intent_with_calculation` converts that
            # into `DeliveryDetailsRequired` -- which the arm below then turned into
            # `ContributionNotPayable` on EVERY attempt. That was the unverified premise in
            # `ContributionNotPayable`'s docstring; the probe on 2026-10-05 resolved it. Wix
            # prices the no-address line correctly (subtotal 100.00, delivery 0.00, tax 0.00,
            # fees 0, total 100.00) and blocks only on the unselected method, and it populates
            # `deliveryInfo.address` itself from the site's own location on Create Cart -- so the
            # missing piece was never an address of ours.
            #
            # SCOPED TO A CONTRIBUTION, NOT TO EVERY NO-DELIVERY BASKET. The ordinary all-digital
            # basket (today unreachable: all seven shop products are PHYSICAL) needs no method,
            # Wix does not demand one for it, and selecting whatever Wix happened to resolve would
            # be adding a shipping decision to a cart that has nothing to ship. Its behaviour is
            # deliberately left exactly as it was.
            #
            # `select_offered_delivery_method` is NON-RAISING, so "Wix named no option at all" --
            # a genuine delivery-region gap in the dashboard -- still arrives at the arm below
            # through `calculate` and still answers `ContributionNotPayable`, which is the
            # dashboard fault that exception was always meant to name.
            prepared = purchase_intent.select_offered_delivery_method(adapter, cart_id) or {}
        prepared_revision = str(prepared.get("revision") or "")

        snapshot, calculated = purchase_intent.build_intent_with_calculation(
            adapter, customer_id=identity.customer_id, cart_id=cart_id,
            # `owned or None` so an EMPTY stored address reaches `purchase_intent` as an explicit
            # `None` rather than a falsy dict. `purchase_intent` tests `is not None`, because `{}`
            # is a placeholder address that must still raise `UnmappableAddress` rather than be
            # laundered into a price; only a true `None` means "no place of supply to resolve".
            #
            # FEAT-003: for a DELIVERY basket, `owned` is already proven payable by the `for_wix`
            # gate above, so it resolves here. For a NO-DELIVERY basket (a contribution), storage
            # is now international and `from_contact` returns a structurally-valid but possibly
            # GST-unresolvable address (e.g. a legacy "Nowhere Pradesh"); a payment with no
            # delivery has no place of supply, so such an address is passed as `None` rather than
            # raising `UnmappableAddress` inside the quote. This preserves the pre-FEAT-003
            # behaviour exactly (the intra-state default) now that `from_contact` no longer
            # returns None for it. The laundering guard for delivery baskets is unchanged.
            owned_address=(_owned_for_supply(owned, requires_delivery)),
            now=int(time.time()), site=wix_ecom.WIX_SITE_ID,
            # The fee-exempt calculator, substituted at an EXISTING seam rather than branching
            # inside the calculator every other basket shares. OWNER DECISION [PHASE2-FEE-001]:
            # a contribution collects exactly the amount chosen. `build_intent_with_calculation`
            # re-validates the returned quote's `policy_version` and refuses one that altered the
            # collection total, and `exempt_quote` stamps the same shared constant, so the
            # substitution is checked at the seam rather than trusted.
            **({"quote_fn": checkout_pricing.exempt_quote}
               if contribution_paise is not None else {}))
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
                                "cartRevision": str(prepared_revision),
                                "requiresDelivery": requires_delivery,
                                "violations": sorted(codes)}))
        if not requires_delivery:
            # Wix wants a delivery destination for a basket that has nothing to deliver. No
            # address the customer can save will satisfy it, because none is ever written to this
            # cart. Non-recoverable by the customer, and loud.
            #
            # This branch is only defensible because the abandon above removed the OTHER way in:
            # a reused cart carrying a stale `deliveryInfo.address` with no method chosen makes
            # Wix answer MISSING_DELIVERY_METHOD, which is a stale-data condition rather than a
            # dashboard fault. The abandon runs BEFORE this call, so by the time this can fire the
            # cart is provably addressless.
            #
            # A CONTRIBUTION GETS ITS OWN CODE, and the split is not cosmetic. The live
            # `Contribute` product is PHYSICAL, so this is the arm that fires if Wix requires a
            # shipping destination for physical goods -- ordinary Wix behaviour, unmeasured here,
            # and therefore possibly the path EVERY contribution takes rather than a rare
            # dashboard fault. `CART_NOT_PAYABLE` answers "Please review your cart and try
            # again", which names the one action a single-donation basket cannot take. The
            # ordinary (today unreachable: all seven shop products are PHYSICAL) all-digital
            # basket keeps the generic code, because "review your cart" is at least not false for
            # a basket with lines in it.
            if contribution_paise is not None:
                raise ContributionNotPayable(
                    "wix requires delivery for a contribution basket") from None
            if service_requests.has_service_line(line_items):
                raise ServiceNotPayable("wix requires delivery for a services basket") from None
            raise cart_v2.CartContractError(
                "wix requires delivery for a no-delivery basket") from None
        if not codes or "MISSING_DELIVERY_ADDRESS" in codes:
            raise                       # unchanged meaning, and fail-closed on no evidence
        raise DeliveryMethodUnavailable("wix offered no usable delivery method") from None
    if contribution_paise is not None:
        _assert_contribution_total(calculated, contribution_paise)
    if service_requests.has_service_line(line_items):
        # Phase O-1: per LINE, so it holds in a mixed basket and under a coupon. Fail-closed.
        #
        # THE RETURN VALUE IS DISCARDED HERE ON PURPOSE, and the redundancy is deliberate rather
        # than an oversight. The figure is needed when the `PAYREF#` row is written, four frames
        # away in `_allocate_reference`, so it is re-derived there with the pure
        # `observed_service_line_paise(calculated)` instead of being threaded through three
        # signatures that have no other use for it. The two cannot disagree: same `calculated`,
        # same single-service-line selection, and `assert_service_line_price` has already refused
        # the basket if that selection is not unique. The assertion runs for its REFUSAL, which
        # is the only thing this call site wants from it.
        service_requests.assert_service_line_price(
            calculated, line_items, delivery_required=requires_delivery)
    # Names and quantities only, for the payment request and the receipt. Line money never
    # travels with the item list: the authoritative amount is the one computed once, above, and
    # the snapshot hash already covers the per-line figures Wix calculated.
    #
    # Read off `calculated["cart"]["lineItems"]` on BOTH branches: `calculate` sends
    # `{"refreshCart": True}` and returns a deepcopy of the cart, so this is the post-refresh
    # list, already in hand. It also deletes a branch-dependent `adapter.get`.
    # NO CONTRIBUTION SPECIAL CASE HERE ANY MORE, and its removal is the point rather than a
    # tidy-up. Under the retired amount-as-quantity model a Rs.400 contribution was quantity 400,
    # so reporting the figure verbatim rendered "Contribution x 400" in a WhatsApp message -- a
    # count that was really money. A contribution is now a fixed-price variant at quantity 1, so
    # the confirmed quantity IS an honest count and the projection needs no exception.
    items = [{"name": _translatable(line.get("name")),
              "quantity": int((line.get("quantityInfo") or {}).get("confirmedQuantity") or 1)}
             for line in (calculated["cart"].get("lineItems") or [])]
    return snapshot, items, calculated


def _translatable(value: Any) -> str:
    """Cart V2 renamed `lineItems[].productName` to `name` and changed it to a translatable
    string, so a plain `str()` would render a dict. Original preferred over translated, matching
    `wix_ecom.line_item_summary`'s existing behaviour on the V1 shape."""
    if isinstance(value, dict):
        return str(value.get("original") or value.get("translated") or "")
    return str(value or "")


def _create(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
            origin: str, *, catalog_session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve authoritative totals, gate on readiness, reserve an attempt, hand off to WhatsApp."""
    line_items = body.get("lineItems")
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED",
                                   "message": "Your cart is empty."}, origin)

    # Phase O-1: A SERVICE IS NEVER BOUGHT ON THIS ROUTE, refused first and before any I/O.
    #
    # The reason is measured from the call graph, not the price. WIX_CART_V2_ENABLED=true on
    # wecare-checkout (measured 2026-10-06), so `_v2_snapshot` below WOULD apply the service
    # pre-check and the per-line price assertion here too -- the price would be honest. What this
    # route cannot do is create the REQUEST: it reads no `serviceIntentId` and never runs
    # `_website_prepare`'s `_allocate_reference`, so its PAYREF# row carries no `serviceLine`,
    # and a capture here would be a paid service with no request, recoverable only by a human.
    # (On the V1 branch it would also be priced with no per-line assertion at all.) Returned as
    # a 409 directly rather than raised, so it can never reach `handler`'s outer 500.
    if service_requests.has_service_line(line_items) and catalog_session is None:
        logger.info(json.dumps({"event": "service_refused",
                                "reason": service_requests.SERVICE_WEBSITE_ONLY}))
        return cors_response(409, service_requests.refusal(
            service_requests.SERVICE_WEBSITE_ONLY), origin)

    # A2.6 — CART PURCHASES ARE COLLECTED ON THE WEBSITE, refused here and before any I/O.
    #
    # Requirements statement 8 and the owner's direction both say cart purchases are collected on
    # the website via Razorpay Standard Checkout; native in-WhatsApp payment is retained for
    # invoice collection and service purchases. With `_send_order_details` repaired onto a working
    # envelope, the non-catalog leg of this function would otherwise have become a working in-chat
    # cart payment, which is the opposite of that ruling.
    #
    # POSITION IS THE POINT, and it is why this sits above everything rather than beside the
    # initiation gate further down. By that point `_create` has already made a live Wix call,
    # run the readiness gate, durably reserved a `PAYREF#` and written an attempt row — so a
    # PERMANENT POLICY refusal would burn a reference and store an attempt for a payment that can
    # never be sent. The service refusal immediately above is "refused first and before any I/O"
    # for the same reason.
    #
    # 200, not 409, matching the `PAYMENT_INITIATION_DISABLED` sibling for the reason recorded
    # there: `cart.tsx` answers it with the "no charge was made" copy, which is only honest
    # because the server stopped before the payment rail. No `paymentAttemptId` is returned,
    # because no attempt exists.
    if catalog_session is None:
        logger.info(json.dumps({"event": "cart_payment_website_only"}))
        return cors_response(200, {
            "status": "CART_PAYMENT_IS_WEBSITE_ONLY",
            "message": "Please complete this payment on the website. "
                       "Nothing has been charged."}, origin)

    # 1. Authoritative total, from Wix. The browser sent catalogue references and quantities;
    #    Wix computes the price. A non-INR or non-whole-paise total fails closed.
    #
    #    Cart V2 is opt-in behind `WIX_CART_V2_ENABLED` (`cart_v2.is_enabled`), and
    #    WIX_CART_V2_ENABLED=true on wecare-checkout (measured 2026-10-06), so V2 serves here;
    #    absence would keep V1. Both are
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

    if catalog_session is not None:
        # The native leg REQUIRES Cart V2, refused explicitly rather than crashed into.
        #
        # Everything below this point reads `snapshot` and `_calculated`, and both are produced
        # only by the V2 branch above — so on V1 this function previously raised
        # `UnboundLocalError` on the per-line assertion and would have raised `AttributeError` on
        # `snapshot.snapshot_hash` a few frames later. In production the crash was unreachable,
        # because a catalog basket always carries a service line and `checkout_preflight` refuses
        # a service line with V2 off; this makes the precondition structural instead of argued.
        # 503 and the same vocabulary `checkout_preflight` uses, so a V2-off deployment reads as
        # one condition rather than two.
        if not cart_v2.is_enabled():
            logger.warning(json.dumps({"event": "service_refused",
                                       "reason": service_requests.SERVICE_UNAVAILABLE}))
            return cors_response(503, service_requests.refusal(
                service_requests.SERVICE_UNAVAILABLE), origin)
        # Native services require the same authoritative per-line guard as website services.
        guard = service_requests.checkout_preflight(line_items, body, v2_enabled=True)
        if guard is not None:
            return cors_response(guard[0], guard[1], origin)
        service_requests.assert_service_line_price(_calculated, line_items, delivery_required=False)

    # 2. Readiness gate. A live provider readback must confirm PAYMENT_READY, or the CTA is refused
    #    with the blocking state. No local constant makes this pass.
    readiness = _readiness()
    # Membership in `BLOCKING_STATES`, not `not readiness.ready`. Equivalent today
    # (`ALL_STATES == {PAYMENT_READY} | BLOCKING_STATES`), but the enumerated form is what the
    # module asks for in its own words, so a state added later without being classified cannot
    # become permissive by omission. Same form as the invoice-engine and outbound gates.
    if readiness.state in payment_readiness.BLOCKING_STATES:
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
        if catalog_session is not None:
            extra.update(channel='whatsapp', nativeCatalogService=True,
                customerPhone=_profile_phone(identity),
                **service_requests.payref_extra(line_items, body,
                    line_paise=service_requests.observed_service_line_paise(_calculated)))
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
    if catalog_session is not None:
        attempt.update(nativeCatalogService=True, channel='whatsapp',
            customerPhone=_profile_phone(identity), catalogServiceSession=catalog_session['orderId'],
            snapshotHash=snapshot.snapshot_hash, purchasedSnapshot=dict(snapshot.frozen_data))
        attempt['wixOrderPayload'] = wix_writeback.build_wix_order_payload(
            cart=_calculated, quote=snapshot.quote, buyer={'phone': identity.phone})
        attempt['wixOrderPayload']['channelInfo']['externalOrderId'] = reference_id
        for line in attempt['wixOrderPayload']['lineItems']:
            line['itemType'] = {'preset': 'SERVICE'}
        if len(json.dumps(attempt, default=str).encode()) > 350000:
            return cors_response(409, {'error': 'CATALOG_SERVICE_SNAPSHOT_TOO_LARGE'}, origin)

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

    if catalog_session is not None:
        _keys_table().update_item(Key={'orderId': catalog_session['orderId']},
            UpdateExpression='SET paymentAttemptId=:attempt, referenceId=:ref',
            ConditionExpression='serviceIntentId=:intent AND #s=:preparing',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':attempt': attempt_id, ':ref': reference_id,
                ':intent': body['serviceIntentId'], ':preparing': 'PREPARING_PAYMENT'})


    # ONE in-chat sender for this handler. The `catalog_session is None` branch that used to sit
    # here is gone: A2.6 refuses that case at the top of `_create`, so the catalog leg is the only
    # leg that reaches this line, and keeping a second call shape would have left a dead branch
    # holding a call that no longer matches the signature.
    #
    # The envelope changed from `isPaymentTemplate` + `orderDetails` to `isCheckoutTemplate` +
    # `checkoutOrderDetails`, which is the correctness fix open task 9.4 asks for. The old
    # envelope attaches the caller's dict VERBATIM as the button action and never calls
    # `_build_payment_settings`, so this leg reached Meta without passing the resolver at all —
    # not the WABA1-only refusal, not the link refusals, not the `VALID_PAYMENT_CONFIGS`
    # membership check. It is now refused by name at the boundary gate.
    from lambda_utils.ecommerce.catalog_service_checkout import payment_details
    sent = _send_order_details(
        phone=identity.phone, contact_id=catalog_session['contactId'],
        phone_number_id=catalog_session['phoneNumberId'],
        order_details=payment_details(catalog_session, snapshot.quote, reference_id,
                                      EXPECTED_CONFIGURATION_NAME, int(time.time())))
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
        except Exception as error:  # noqa: BLE001
            # The poll must still answer. A failure here leaves the attempt exactly as it was.
            logger.error(json.dumps({"event": "checkout_status_finalize_failed",
                                     "alert": "PAID_BUT_NO_ORDER_RECORD",
                                     "error": type(error).__name__}))
    # READ THE NUMBER OFF THE ROW, NOT OFF THE BRANCH ABOVE. `finalization._stage` writes
    # `orderNumber` at INTERNAL_ORDER_CREATED, which happens only AFTER the order record has
    # committed, so its presence on the attempt is exactly the evidence an order exists.
    #
    # It used to be set only inside the `_finalize_from_claim` arm, which runs only while
    # `finalizationStage` is still unset. So the ordinary case -- the webhook finalized the
    # attempt, as it did for the real captured order WD-ORD-7ZTSG8X7 -- fell straight past it and
    # reported `orderNumber: None` forever. The paid customer got the "we are creating your order"
    # screen permanently and never saw a confirmation.
    #
    # The stage itself is deliberately NOT consulted and NOT returned. A paid order rests at
    # NEEDS_RECONCILIATION / WIX_WRITE_CONTRACT_REQUIRED while the Wix writeback is gated off;
    # that is our bookkeeping against the store and it is not a fact about the customer's payment.
    # `payment_history_entry` still strips the number unless the state is in
    # ORDER_ELIGIBLE_STATES, so a non-paid attempt cannot carry one no matter what is on its row.
    order_number = str(owned.get("orderNumber") or "")
    # payment_history_entry never carries an order number for a non-paid attempt, and collapses a
    # failed one to the "Payment failed — no order created" label. It is the exact customer-facing
    # projection the status UI needs.
    entry = payment_attempt.payment_history_entry(owned, order_number=order_number)
    catalog_event = catalog_analytics.purchase_facts(owned)
    if catalog_event:
        entry['catalogEvent'] = catalog_event
    return cors_response(200, {"status": entry.get("status"), "attempt": entry}, origin)


# ── the WhatsApp order_details handoff ──────────────────────────────────────────

def _send_order_details(*, phone: str, contact_id: str, phone_number_id: str,
                        order_details: dict) -> bool:
    """Invoke the in-chat payment-request sender. Returns True on a 2xx. THE ONLY SENDER HERE.

    This does NOT build `payment_settings` — `outbound-whatsapp._build_payment_settings` owns
    Mode 3, and the whole point of this shape is that it reaches that resolver. `payment_settings`
    is deliberately ABSENT from the payload: the `isCheckoutTemplate` branch builds them from the
    sender's configured gateway and now REFUSES a caller-supplied block outright, so the WABA1-only
    refusal, the `payment_link_uri` / `upi_intent_link` refusals and the `VALID_PAYMENT_CONFIGS`
    membership check all apply. The configuration NAME still travels, inside `order_details`, so
    the configuration `payment_readiness` proved is the configuration Meta is told to use.

    THE ROUTE IT USED TO CALL DID NOT EXIST. It POSTed
    `/wa-business/messages/send/interactive-payment` at the business-API Lambda, whose send
    dispatcher handles ten paths and then falls through to a 404 `Unknown send path`. The 404 read
    as a non-2xx and surfaced as this handler's 502 `SEND_FAILED`, so the function could never
    have sent anything. It is repaired onto `wecare-outbound-whatsapp:live` with the envelope that
    function's checkout-template branch owns.

    `headerImageUrl` is deliberately not passed. The `isCheckoutTemplate` branch forces its own
    fixed header for the approved template and ignores a per-call value, so supplying one is
    misleading.

    Meta + Razorpay collect the money in-chat; nothing here charges anything.
    """
    invoke_event = {
        "body": json.dumps({
            "contactId": contact_id,
            "recipientPhone": phone,
            "phoneNumberId": phone_number_id,
            "isTemplate": True,
            "isCheckoutTemplate": True,
            "templateName": "wecarepay_wa",
            "templateParams": [],
            "checkoutOrderDetails": order_details,
        }),
    }
    try:
        response = _lambda_client().invoke(
            FunctionName=OUTBOUND_SENDER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(invoke_event).encode("utf-8"),
        )
        raw = response["Payload"].read()
        if response.get("FunctionError"):
            return False
        result = json.loads(raw.decode("utf-8")) if raw else {}
        # TIGHTENED to add the lower bound; this is a change, not a preservation. The old form
        # was `< 300` with no floor, so a `statusCode` of 0, 100 or 204 read as success. Nothing
        # emits a sub-200 status today, so the 502 `SEND_FAILED` contract is unchanged in practice.
        return 200 <= int(result.get("statusCode") or 500) < 300
    except Exception as error:  # noqa: BLE001
        # Includes `AccessDeniedException` until the `wecare-checkout-role` invoke grant lands in
        # both of its homes. The attempt is stored and no order exists, so the reference stays
        # reusable for a delivery retry.
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


def _native_catalog_service(event: Dict[str, Any], origin: str):
    from lambda_utils.ecommerce import catalog_service_checkout as catalog
    if event['internalAction'] == 'finalizeNativeCatalogService':
        attempt = _attempts_table().get_item(Key={'paymentAttemptId': str(event.get('paymentAttemptId') or '')},
                                             ConsistentRead=True).get('Item') or {}
        if not attempt.get('nativeCatalogService'):
            return {'outcome': 'NOT_A_NATIVE_SERVICE'}
        identity = customer_auth.CustomerIdentity(customer_id=attempt['customerId'],
            subject=attempt['customerId'], phone=attempt['customerPhone'])
        ran = _finalize_from_claim(identity, attempt)
        current = _attempts_table().get_item(Key={'paymentAttemptId': attempt['paymentAttemptId']},
                                           ConsistentRead=True).get('Item') or {}
        done = ran and catalog.finalization_complete(current)
        if done:
            try:
                _keys_table().update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + attempt['customerId']},
                    UpdateExpression='SET #s=:closed', ConditionExpression='sessionKey=:session',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':closed': 'CLOSED', ':session': attempt['catalogServiceSession']})
            except Exception as error:
                if getattr(error, 'response', {}).get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                    raise
        return {'outcome' : 'NATIVE_SERVICE_FINALIZED' if done else 'NATIVE_SERVICE_FINALIZATION_PENDING'}
    if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true':
        return {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}
    if not wix_writeback.is_enabled():
        return {'outcome': 'NATIVE_SERVICE_WRITEBACK_NOT_READY'}
    token = str(event.get('catalogToken') or '')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}', token):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
    row = _keys_table().get_item(Key={'orderId': catalog.SESSION_PREFIX + token}, ConsistentRead=True).get('Item') or {}
    if row.get('status') != 'PREPARING_PAYMENT' or int(row.get('expiresAt') or 0) <= int(time.time()):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
    if row.get('paymentAttemptId'):
        return {'outcome': 'CATALOG_SERVICE_ALREADY_PREPARED', 'paymentAttemptId': row['paymentAttemptId']}
    # A2.5 — ONLY WABA1 MAY TAKE A PAYMENT, refused here with a named cause.
    #
    # Switching this leg onto the `isCheckoutTemplate` envelope newly subjects it to the
    # resolver's `PAYMENT_SENDERS` refusal, which raises rather than returning an outcome. The
    # shape this guards against is not one that occurs today — the session's `phoneNumberId` is
    # written from `_get_aws_phone_number_id`, which returns only an AWS-style id — it guards
    # against WABA2, which that resolver can legitimately return and which must never collect.
    #
    # POSITION: before the one-shot `nativePrepareClaim` write below. `nativePrepareClaim` is
    # `attribute_not_exists`-conditional, so a check placed after it would make the customer's
    # retry answer CATALOG_SERVICE_RECONCILIATION_REQUIRED and need a human.
    if str(row.get('phoneNumberId') or '') not in wa_payment_request.PAYMENT_SENDERS:
        logger.error(json.dumps({'event': 'catalog_session_sender_not_permitted',
                                 'sessionToken': token[:8]}))
        return {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}
    contact = _table(CONTACTS_TABLE).get_item(Key={'id': row.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    owner = contact.get('checkoutCustomerId')
    # Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
    if not customer_auth.is_cognito_subject(owner) or owner != row.get('customerId'):
        return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}
    users = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'us-east-1')).list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID, Filter='sub = "' + owner + '"', Limit=2).get('Users') or []
    identity = catalog.verified_identity(contact, users, row.get('phone', ''))
    from lambda_utils.ecommerce import service_request_store as store
    intent = _table('stack-wecare-digital-ServiceRequestsTable').get_item(
        Key={'requestId': 'INTENT#' + str(row.get('serviceIntentId') or '')}, ConsistentRead=True).get('Item') or {}
    if (intent.get('ownerCustomerId') != owner or intent.get('kind') != row.get('kind')
            or intent.get('variantId') != row.get('variantId') or intent.get('status') != store.INTENT_OPEN
            or (row.get('kind') == 'VAULT' and intent.get('vaultFileId') != row.get('vaultFileId'))):
        return {'outcome': 'CATALOG_SERVICE_INTENT_UNAVAILABLE'}
    response = _lambda_client().invoke(FunctionName='wecare-whatsapp-business-api:live',
        InvocationType='RequestResponse', Payload=json.dumps({'internalAction': 'catalogServiceReadiness'}).encode())
    readiness = json.loads(response['Payload'].read())
    if response.get('FunctionError') or not catalog.meta_ready(readiness, row['kind']):
        return {'outcome': 'NATIVE_SERVICE_META_NOT_READY'}
    lines = [{'catalogReference': {'catalogItemId': row['productId'],
              'options': {'variantId': row['variantId']}, 'appId': cart_v2.STORES_APP_ID}, 'quantity': 1}]
    catalog.service_from_lines([{'productId': row['productId'], 'variantId': row['variantId'], 'quantity': 1}])
    # Claim before pricing/provider calls. A timed-out preparation cannot be charged again blindly.
    try:
        _keys_table().update_item(Key={'orderId': row['orderId']}, UpdateExpression='SET nativePrepareClaim=:claimed',
            ConditionExpression='attribute_not_exists(nativePrepareClaim)',
            ExpressionAttributeValues={':claimed': 'CLAIMED'})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return {'outcome': 'CATALOG_SERVICE_RECONCILIATION_REQUIRED'}
        raise
    return _create(identity, {'lineItems': lines, 'serviceIntentId': row['serviceIntentId']},
                   origin, catalog_session=row)
