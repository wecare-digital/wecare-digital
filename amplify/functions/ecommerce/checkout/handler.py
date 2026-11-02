"""The customer checkout front door: the website Razorpay flow and the in-WhatsApp service leg.

Where this sits
---------------
    [customer, signed in]  --create-->  THIS  --price-->  [ProductsTable]  (authoritative total)
                                          |
                                          |  + convenience fee and its GST, frozen into a snapshot
                                          |  readiness gate (live Meta readback)
                                          |  reserve reference_id (PAYREF#), build PaymentAttempt
                                          v
                                   [order_details in WhatsApp]  -->  [Meta]  -->  [Razorpay]   (pays in-chat)

This handler is the *verifier's front half*: it decides an amount authoritatively, records a
PaymentAttempt, and hands the customer off to pay. It never charges anything itself, and the order
record exists only after a capture is verified against Razorpay's API: the reconciliation claims
the order identity, and `finalization.accept_paid` writes the internal order record and stages it
ORDER_FINALIZED. That boundary is the whole design, so this handler imports the post-PAID
functions of `order_keys` not at all.

Four rules it enforces, each load-bearing
------------------------------------------
1. **Authority comes from the session, never the request.** The customer is proven by
   `customer_auth` (issuer-pinned to the customer pool), and every checkout is bound to that
   immutable `CUS_` id. A `paymentAttemptId` or `checkoutId` in the body is checked against the
   session with `authorize_resource`, so one customer cannot read another's attempt (IDOR).
2. **The amount is the server's, in integer paise.** `_native_quote` prices the basket's product
   and variant ids from ProductsTable (`native_checkout.quote_native_cart`) and
   `checkout_pricing.compute_quote` adds the convenience fee and its GST. Vault and Drop Docs
   use the owner-approved sequence at this seam: item price, 18% supply GST, Delight, Rs25
   Express, then convenience fee and 18% GST on that fee. The browser sends
   identifiers and quantities only; a price it sends is never read.
3. **Payments are readiness-gated on a live provider readback.** `payment_readiness.evaluate` must
   return `PAYMENT_READY` before an attempt is created; otherwise the CTA is refused with the
   blocking state. No local constant can make it ready.
4. **The reference is minted once, reserved, and sent byte-for-byte.** `order_keys` mints and
   reserves it under `PAYREF#`; it is never transformed after reservation.

Initiation is live but provider-readiness gated
------------------------------------------
The historical `CHECKOUT_INITIATION_ENABLED` switch is retired. Initiation is hard-enabled in
code; safety comes from `payment_readiness.evaluate`, which reads the live Meta payment
configuration and requires the expected configuration/provider identity before any payable
message is created. A stale environment value cannot enable or disable this path.

Nothing plaintext is logged
---------------------------
No full phone number, no customer id in a form that identifies a person beyond its own opaque id,
no amount tied to a person, no exception text that could echo request content. Event names, opaque
ids, states and counts only.

Two coexisting payment presentations, one verified payment rail
--------------------------------------------------------------
The in-WhatsApp path returns ``PAYMENT_REQUEST_SENT`` after the server has priced the basket,
verified live payment readiness, reserved the immutable payment reference, and handed the customer
to the approved WhatsApp payment experience.

The website path lives in
``lambda_utils/ecommerce/website_checkout.py`` + ``lambda_utils/integrations/razorpay_orders.py``
and returns ``CHECKOUT_OPTIONS_READY`` with only the server-created Razorpay order fields:
``{keyId, orderId, amountPaise, currency, prefill, paymentAttemptId}``. Both presentations converge
on the same capture-verification/finalization boundary; neither browser nor WhatsApp response can
mark an order paid.
    create  (ownership/snapshot/intent fails) -> ``CHECKOUT_REJECTED`` (no order created)
    create  (provider timeout/save ambiguity) -> ``CHECKOUT_AMBIGUOUS`` (never a 2nd payable order)

    callback (browser relays payment id/order id/signature) ->
            HMAC verified over the STORED gateway order id, then STILL requires
            ``razorpay_verify`` authoritative capture -> ``VERIFIED_PAID`` only after capture.

A Razorpay GATEWAY order exists before payment; the internal order record and public purchase
number exist ONLY after an authoritative capture. They are different objects. Cart/resume data is
kept until that verified-paid finalization. Partial payment is disabled for this release.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import (contact_key, contact_store, customer_auth, customer_session, payment_readiness,
                          payment_status, shared_tables, whatsapp_templates)
from lambda_utils.ecommerce import (
    blog_contribution, cart_contract, catalog_analytics, checkout_pricing, contact_address, customer_cart, finalization,
    india_address, order_channel, order_creation, order_delivery, order_keys, payment_address,
    payment_attempt, purchase_intent, short_purchase, wa_order_status, wa_payment_request,
    website_checkout, whatsapp_basket)
# AWS-native supply engine; ProductsTable is the only pricing authority. These compute the
# collection total, and the payment, order and invoice paths downstream consume the frozen
# snapshot they produce. Imported at module load (cheap, pure) so a missing module fails the
# deploy rather than a request.
from lambda_utils.ecommerce import (
    catalog_pricing, native_checkout, native_shipping)
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
from lambda_utils.ecommerce import service_requests, request_service_contracts
from lambda_utils.ecommerce.service_requests import ServiceNotPayable, ServicePriceChanged
# Public service prices use the authoritative AWS product catalog (service_pricing_native).
from lambda_utils.ecommerce import contribute_taxable, service_pricing_native, staff_contribution
from lambda_utils.integrations import razorpay_orders, razorpay_verify
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
PAYMENT_ATTEMPTS_TABLE = shared_tables.payment_attempts_table_name()
COMMERCE_KEYS_TABLE = shared_tables.commerce_keys_table_name()
CONTACTS_TABLE = shared_tables.contacts_table_name()
#: The internal order record. An order exists ONLY after an authoritative capture, and this is
#: where that record lands. Granted `GetItem`/`PutItem`/`UpdateItem` and explicitly NOT
#: `DeleteItem`: an order record is evidence that money moved.
ORDERS_TABLE = shared_tables.orders_table_name()
#: AWS-native product catalog; the only checkout product authority.
PRODUCTS_TABLE = shared_tables.products_table_name()
#: AWS-native working cart (CartTable), the backing store of the customer-cart adapter the
#: WhatsApp claim-basket path drives.
CART_TABLE = shared_tables.carts_table_name()
WEBSITE_SNAPSHOT_TTL_SECONDS = 15 * 60

#: Reasons that mean "we refuse", as opposed to "we do not know". 409 for the first; 200 for the
#: provider-ambiguity reasons, where a claim either way about a charge would be dishonest.
_CART_BLOCKED = (website_checkout.CART_ALREADY_PAID,
                 website_checkout.CART_PAYMENT_IN_FLIGHT)

#: Checkout mode marker on the attempt, so this path is distinguishable from any other and a test
#: can assert which flow created it: the in-WhatsApp catalog-service leg, priced from
#: ProductsTable and finalized natively.
CHECKOUT_MODE = "AWS_NATIVE"

#: ProductsTable is the sole supply/pricing authority. The environment key is retained only as
#: a deployment/readback invariant; there is no provider fallback path, and nothing here reads it.
CHECKOUT_MODE_ENV = "CHECKOUT_MODE"

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

#: Hard-enabled by owner authorization (2026-10-21): the checkout initiation gate was removed.
#: Previously read CHECKOUT_INITIATION_ENABLED (default off); that env toggle is deleted so
#: initiation is always on. NOTE: payment_readiness.evaluate (EXPECTED_CONFIGURATION_NAME /
#: EXPECTED_PROVIDER_MID) still independently governs whether a payable message actually goes
#: out -- that readiness check is intentionally left intact by this change.
INITIATION_ENABLED = True

#: The catalogue product id of the live Contribute product, lowercased, as the deployment
#: environment carries it (`config/lambda-env-manifest.json`). NOT a secret -- a catalogue
#: reference.
CONTRIBUTION_PRODUCT_ID = str(os.environ.get("CONTRIBUTION_PRODUCT_ID", "")).strip().lower()

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
#: invoice carrying seller GSTIN 19AAFFW7196L1Z8 -- and that total would be charged. The native
#: quote freezes no address today (catalog prices are GST-inclusive and native shipping is free),
#: so this is the one place an owned address is read from when a rule needs it.

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


def _products_table():
    return _table(PRODUCTS_TABLE)


def _cart_table():
    return _table(CART_TABLE)


def _native_cart_adapter(customer_id: str = ""):
    """The AWS-native cart adapter `CustomerCart` drives, backed by CartTable and the
    ProductsTable reader."""
    from lambda_utils.ecommerce.native_cart_adapter import NativeCartAdapter
    return NativeCartAdapter(_cart_table(), _native_product_reader(), customer_id=customer_id)


def _native_product_reader():
    """A ProductsTable reader `product_id -> item | None` for the native supply engine.
    Called by the AWS-native checkout path; the table must exist before
    the owner provisions it for the cutover."""
    table = _products_table()

    def read(product_id):
        return table.get_item(Key={"id": str(product_id)}).get("Item")

    return read


def _native_variant_reader():
    """A reader `variant_id -> {priceMinor, currency, status}` for native SERVICE pricing.

    Service pages price by VARIANT id (e.g. the five variants of the services product),
    so this scans ProductsTable once and indexes every variant sku -> a price row. The
    catalog is tiny (10 products), so one scan is cheap and the result is cached in the
    closure for the life of the warm sandbox. Mirrors service_pricing_native's expected
    reader contract: returns None for an unknown variant (-> {"available": false}).
    """
    table = _products_table()
    index = {}
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        for p in resp.get("Items", []):
            status = str(p.get("status") or "active")
            for v in p.get("variants", []) or []:
                sku = str(v.get("sku") or v.get("id") or "")
                if sku:
                    index[sku] = {"priceMinor": v.get("priceMinor"),
                                  "currency": p.get("currency", "INR"),
                                  "status": status}
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def read(variant_id):
        return index.get(str(variant_id))

    return read


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



# Admin staff Contribute is a catalog-order payment, NOT a Vault service
# session, a staff invoice or the historical BLOG_CONTRIBUTION gateway route.
_STAFF_CONTRIBUTION_ACTION = "staff-contribute-send"
_STAFF_CONTRIBUTION_READINESS = "staff-contribute-readiness"
_STAFF_CONTRIBUTION_CONTACT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")



def _staff_contribution_catalog_is_current(product_id: str, variant_id: str) -> bool:
    """Strongly-consistent price check before any staff payment reservation."""
    # An unset product id must fail locally, never become a DynamoDB GetItem.
    # Do not rely on the configured contribution set to exclude empty strings.
    if (not product_id or not variant_id
            or product_id not in CONTRIBUTION_PRODUCT_IDS
            or variant_id not in CONTRIBUTION_CHOICES_PAISE):
        return False
    try:
        product = _products_table().get_item(
            Key={"id": product_id}, ConsistentRead=True,
        ).get("Item")
        return staff_contribution.valid_staff_contribution_catalog_record(
            product, product_id=product_id, variant_id=variant_id)
    except Exception as error:
        logger.warning(json.dumps({"event": "staff_contribute_catalog_unavailable",
                                   "reason": type(error).__name__}))
        return False


def _staff_contribution_readiness(origin: str) -> Dict[str, Any]:
    """Read-only server capability probe: no payment, slot or message side effect.

    The published backend independently checks one strongly-consistent
    canonical ₹300 product and its six-line taxable quote. Approval for
    treating the SKU as a taxable supply is a prerequisite to publishing
    this code; runtime price drift still fails closed.
    """
    variants = list(CONTRIBUTION_CHOICES_PAISE.items())
    quote_matches = (
        len(CONTRIBUTION_PRODUCT_IDS) == 1
        and CONTRIBUTION_PRODUCT_ID in CONTRIBUTION_PRODUCT_IDS
        and len(variants) == 1
        and variants[0][1] == staff_contribution.STAFF_CONTRIBUTION_TOTAL_PAISE
        and _staff_contribution_catalog_is_current(
            CONTRIBUTION_PRODUCT_ID, variants[0][0])
    )
    if quote_matches:
        try:
            terms = service_pricing_native._contribution_breakdown(
                staff_contribution.STAFF_CONTRIBUTION_TOTAL_PAISE)
            quote_matches = (
                terms.get("itemSubtotalPaise") == 23541
                and terms.get("catalogGrossPaise") == 30000
                and terms.get("supplyGstPaise") == 4237
                and terms.get("delightPaise") == 138
                and terms.get("expressPaise") == 1500
                and terms.get("collectionBeforeConveniencePaise") == 29140
                and terms.get("convenienceFeePaise") == 729
                and terms.get("convenienceGstPaise") == 131
                and terms.get("totalPayablePaise") == 30000
            )
        except ValueError:
            quote_matches = False
    return cors_response(200, {
        "status": "STAFF_CONTRIBUTE_READY" if quote_matches else "STAFF_CONTRIBUTE_BLOCKED",
        "sendEnabled": quote_matches,
        "amountPaise": staff_contribution.STAFF_CONTRIBUTION_TOTAL_PAISE,
        "currency": "INR",
        "reason": "READY" if quote_matches else "PRICE_OR_POLICY_UNVERIFIED",
    }, origin)


def _staff_contribution_send(
    body: Dict[str, Any], origin: str, *, staff_actor_hash: str,
) -> Dict[str, Any]:
    """One exact ₹300 Meta ORDER_DETAILS request to a verified saved customer.

    Staff never supply the price, SKU, WhatsApp number, media, payment
    configuration, line details or quote. This reuses _create so the
    canonical reservation, provider readiness and capture rails stay intact.
    """
    if (not isinstance(staff_actor_hash, str) or len(staff_actor_hash) != 64
            or not all(ch in "0123456789abcdef" for ch in staff_actor_hash)):
        return cors_response(403, {"error": "STAFF_ACTOR_UNVERIFIED"}, origin)
    if (set(body) != {"action", "contactId"}
            or type(body.get("contactId")) is not str
            or not _STAFF_CONTRIBUTION_CONTACT_ID.fullmatch(body["contactId"])):
        return cors_response(400, {"error": "STAFF_CONTRIBUTION_REQUEST_INVALID"}, origin)

    variants = list(CONTRIBUTION_CHOICES_PAISE.items())
    if (len(variants) != 1 or len(CONTRIBUTION_PRODUCT_IDS) != 1
            or CONTRIBUTION_PRODUCT_ID not in CONTRIBUTION_PRODUCT_IDS
            or variants[0][1] != staff_contribution.STAFF_CONTRIBUTION_TOTAL_PAISE):
        return cors_response(409, {"error": "CONTRIBUTION_POLICY_UNAVAILABLE"}, origin)
    product_id, variant_id = CONTRIBUTION_PRODUCT_ID, variants[0][0]

    try:
        contact = _table(CONTACTS_TABLE).get_item(
            Key={"id": body["contactId"]}, ConsistentRead=True).get("Item") or {}
    except Exception:
        return cors_response(503, {"error": "CONTRIBUTION_CONTACT_READ_UNAVAILABLE"}, origin)
    try:
        contact_key.assert_consistent(contact)
    except contact_key.ContactKeyMismatch:
        return cors_response(409, {"error": "CONTACT_IDENTITY_CONFLICT"}, origin)
    if (not contact_store.is_live(contact) or contact.get("archivedAt")
            or contact.get("locked") or contact_key.resolve(contact) != body["contactId"]
            or not customer_auth.is_cognito_subject(str(contact.get("checkoutCustomerId") or ""))
            or not str(contact.get("name") or "").strip()):
        return cors_response(409, {
            "error": "CONTRIBUTION_CUSTOMER_UNVERIFIED",
            "message": "Select a verified active customer before requesting payment.",
        }, origin)

    # No staff-supplied sender/phone, no fabricated inbound message.
    sender_id = wa_payment_request.PHONE_NUMBER_ID_1
    if sender_id not in wa_payment_request.PAYMENT_SENDERS:
        return cors_response(409, {"error": "PAYMENT_SENDER_NOT_PERMITTED"}, origin)
    try:
        identity, proven = _native_whatsapp_identity(
            body["contactId"], str(contact.get("phone") or ""), sender_id, "")
    except (customer_auth.CustomerNotAuthorized, customer_identity.InvalidPhoneNumber):
        return cors_response(409, {
            "error": "CONTRIBUTION_CUSTOMER_UNVERIFIED",
            "message": "WhatsApp customer ownership could not be verified. No request was sent.",
        }, origin)
    try:
        contact_key.assert_consistent(proven)
    except contact_key.ContactKeyMismatch:
        return cors_response(409, {"error": "CONTACT_IDENTITY_CONFLICT"}, origin)
    if (identity.customer_id != str(contact["checkoutCustomerId"])
            or not contact_store.is_live(proven) or proven.get("archivedAt")
            or proven.get("locked") or not str(proven.get("name") or "").strip()):
        return cors_response(409, {"error": "CONTRIBUTION_CUSTOMER_UNVERIFIED"}, origin)

    lines = [{
        "catalogReference": {"catalogItemId": product_id,
                             "options": {"variantId": variant_id}},
        "quantity": 1,
    }]
    try:
        preview = _native_quote(identity, lines, int(time.time()))
    except (ValueError, catalog_pricing.CatalogPricingError):
        return cors_response(409, {"error": "CONTRIBUTION_QUOTE_UNAVAILABLE"}, origin)
    if not staff_contribution.valid_staff_contribution_snapshot(
            preview, product_id=product_id, variant_id=variant_id):
        return cors_response(409, {
            "error": "CONTRIBUTION_PRICE_MISMATCH",
            "message": "The live ₹300 quote does not match the taxable Contribute policy. Nothing was sent.",
        }, origin)

    if not _staff_contribution_catalog_is_current(product_id, variant_id):
        return cors_response(409, {"error": "CONTRIBUTION_CATALOG_CHANGED"}, origin)

    # Reuse the existing *conditional* WACARTLIVE per-owner/basket slot.
    # Same customer + SKU sent from native WhatsApp and staff cannot race.
    now = int(time.time())
    live_key = _wa_cart_live_key(identity.customer_id, lines)
    try:
        token = (_claim_wa_cart(live_key, identity.customer_id, now)
                 or _take_over_settled_wa_cart(live_key, identity.customer_id, now))
    except Exception:
        return cors_response(503, {"error": "CONTRIBUTION_RESERVATION_UNAVAILABLE"}, origin)
    if not token:
        return cors_response(409, {
            "error": "CONTRIBUTION_REQUEST_ALREADY_OPEN",
            "message": "A payment request is in progress or cannot be safely retried. Check WhatsApp and the ledger.",
        }, origin)

    # Server-generated request identity, no customer-supplied amount/address.
    # Contributions never ship, so delivery confirmation is inapplicable.
    try:
        result = _create(
            identity, {"lineItems": lines, "requestKey": uuid4().hex,
                       "deliveryConfirmed": True},
            origin, native_contact=proven, required_staff_contribution=True,
            staff_actor_hash=staff_actor_hash)
    except Exception as error:
        logger.error(json.dumps({"event": "staff_contribution_send_unconfirmed",
                                 "error": type(error).__name__}))
        # The provider might have accepted the request before an exception.
        # Keep the slot; do not auto-send again or call this a failed delivery.
        return cors_response(502, {
            "error": "CONTRIBUTION_SEND_UNCONFIRMED", "sendUnconfirmed": True,
            "message": "Delivery status is unknown. Check the ledger and WhatsApp before another attempt.",
        }, origin)

    try:
        status = int(result.get("statusCode") or 0)
        payload = json.loads(result.get("body") or "{}")
    except (TypeError, ValueError):
        status, payload = 0, {}
    accepted = status == 200 and payload.get("status") == "PAYMENT_REQUEST_SENT"
    uncertain = bool(payload.get("sendUnconfirmed")) or status == 0 or status >= 500
    if accepted or uncertain:
        _record_wa_cart(live_key, token,
                        str(payload.get("paymentAttemptId") or ""), now)
    else:
        _release_wa_cart(live_key, token)
    return result


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
    if explicit:
        if explicit in ("create", "status", "prepare", "quote", "verify", "profile",
                        "claim-basket", "order", "request-service-start"):
            return explicit
        # Never reinterpret an unrecognized explicit read (especially 'quote')
        # as create: payment attempts and provider orders are side effects.
        return "unsupported"
    path = str(event.get("rawPath") or event.get("path") or "").lower()
    if path.endswith("/status"):
        return "status"
    if path.endswith("/prepare-checkout"):
        return "prepare"
    if path.endswith("/verify-callback"):
        return "verify"
    if path.endswith("/request-service-start"):
        return "request-service-start"
    return "create"


#: The one error code the public price arm can answer with. No detail: an anonymous caller learns
#: that prices are unavailable, which is all it needs to render the honest unavailable state.
SERVICE_PRICES_UNAVAILABLE = "SERVICE_PRICES_UNAVAILABLE"


def _service_prices(origin: str) -> Dict[str, Any]:
    """`GET /ecommerce/service-prices` -> every service's price, in integer paise, from the
    AWS-native ProductsTable.

    FAILS CLOSED. If the native catalog prices nothing, this answers 503 rather than an empty
    payload a browser might read as "free". A PARTIAL result is served at 200: the slugs that
    resolved carry their price and the rest carry `{"available": false}` with no `paise` key,
    because one service the catalog cannot price is no reason to take the other three off sale.

    Reads ProductsTable (a cheap point/scan on an on-demand table); the edge still caches the
    response (max-age), and the route keeps its own throttle (`scripts/provision_checkout.py`).

    Logs counts only. No credential, no provider message.
    """
    try:
        payload = service_pricing_native.resolve_all(_native_variant_reader())
    except Exception as exc:  # noqa: BLE001 -- `type(exc).__name__` only, never provider text
        logger.error(json.dumps({"event": "service_prices_failed",
                                 "error": type(exc).__name__}))
        return cors_response(503, {"error": SERVICE_PRICES_UNAVAILABLE}, origin)
    priced = sum(1 for price in payload["prices"].values() if price.get("available"))
    if not priced:
        logger.error(json.dumps({"event": "service_prices_none_resolved_native",
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
    # request carrying `Origin: https://wecare.digital` was served the cached apex
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
    # The edge is the FIRST of two bounds on the ProductsTable reads behind a cache miss, not the
    # only one: the route carries its own throttle (`scripts/provision_checkout.py`,
    # ROUTE_THROTTLE_*), because an anonymous route shares the API with the live checkout, and
    # concurrency rather than the per-sandbox minute is the multiplier on a miss.
    response["headers"]["Cache-Control"] = "public, max-age=60"
    response["headers"]["Access-Control-Allow-Origin"] = "*"
    response["headers"]["Vary"] = "Origin"
    return response


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)

    # Strangler seam: invoice-engine is packaged inside checkout and DOES carry live traffic:
    # the Razorpay payment webhook relays a paid cart to `/invoices/from-payment`, so these
    # `/invoices` routes are served here. This dispatch MUST remain before
    # checkout's customer-session gate: invoice routes keep the invoice engine's existing auth
    # contract and must never be rejected as customer checkout with VERIFICATION_REQUIRED.
    # Lazy import keeps ordinary checkout cold starts and trust decisions unchanged.
    rc0 = event.get("requestContext", {}) or {}
    http0 = rc0.get("http", {}) or {}
    commerce_path = str(
        event.get("rawPath")
        or event.get("path")
        or http0.get("path")
        or ""
    )
    route_key = str(event.get("routeKey") or rc0.get("routeKey") or "")
    invoice_route = (
        commerce_path.startswith("/invoices")
        or "/invoices" in route_key
        or "/invoices" in commerce_path
    )
    if invoice_route:
        import invoice_engine as commerce_invoice_engine
        return commerce_invoice_engine.handler(event, context)
    if event.get('internalAction') == 'ensureNativeWhatsAppIdentity':
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return cors_response(403, {'error': 'Internal invocation required'}, origin)
        phone_number_id = str(event.get('phoneNumberId') or '')
        if phone_number_id == '1016149501586345':
            phone_number_id = wa_payment_request.PHONE_NUMBER_ID_1
        if phone_number_id not in wa_payment_request.PAYMENT_SENDERS:
            return {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}
        try:
            identity, contact = _native_whatsapp_identity(
                str(event.get('contactId') or ''),
                str(event.get('senderPhone') or ''),
                phone_number_id,
                str(event.get('sourceMessageId') or ''))
        except (customer_auth.CustomerNotAuthorized, customer_identity.InvalidPhoneNumber):
            return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
        return {
            'outcome': 'WHATSAPP_IDENTITY_READY',
            'customerId': identity.customer_id,
            'phone': identity.phone,
            'contactId': contact_key.resolve(contact),
            'customerUuid': customer_uuid.from_contact(contact),
        }

    if event.get('internalAction') in ('prepareNativeCatalogService', 'finalizeNativeCatalogService'):
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return cors_response(403, {'error': 'Internal invocation required'}, origin)
        return _native_catalog_service(event, origin)
    if event.get('internalAction') == 'prepareNativeCart':
        if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
            return cors_response(403, {'error': 'Internal invocation required'}, origin)
        return _native_cart(event, origin)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return options_response(origin)

    # Staff/admin and customer OAuth tokens are DIFFERENT Cognito pools.
    # This explicit staff action must be routed BEFORE require_customer.
    # It is never reachable via an internal Lambda invoke or another URL,
    # and requires the staff Admin group plus the existing Admin MFA gate.
    staff_candidate = _body(event)
    staff_action = (str(staff_candidate.get("action") or "").strip().lower()
                    if isinstance(staff_candidate, dict) else "")
    if staff_action in (_STAFF_CONTRIBUTION_ACTION, _STAFF_CONTRIBUTION_READINESS):
        from lambda_utils.middleware import require_auth
        staff_path = str(event.get("rawPath") or event.get("path")
                         or rc.get("http", {}).get("path") or "").rstrip("/").lower()
        api_gateway = bool(rc.get("apiId") or rc.get("domainName")
                           or rc.get("http", {}).get("sourceIp"))
        if (not api_gateway or method != "POST"
                or not staff_path.endswith("/ecommerce/checkout")):
            return cors_response(403, {"error": "STAFF_CONTRIBUTE_ROUTE_FORBIDDEN"}, origin)
        denied = require_auth(event, required_role="Admin")
        if denied is not None:
            return denied
        if (event.get("_auth") or {}).get("role") != "Admin":
            return cors_response(403, {"error": "STAFF_CONTRIBUTE_FORBIDDEN"}, origin)
        try:
            if staff_action == _STAFF_CONTRIBUTION_READINESS:
                if set(staff_candidate) != {"action"}:
                    return cors_response(400, {"error": "INVALID_READINESS_REQUEST"}, origin)
                return _staff_contribution_readiness(origin)
            # The actor identity comes ONLY from the verified staff Cognito
            # session, never from the request body. A stable hash is stored
            # privately with the payment attempt and reference for audits.
            import hashlib
            username = str((event.get("_auth") or {}).get("username") or "").strip()
            if not username:
                return cors_response(403, {"error": "STAFF_ACTOR_UNVERIFIED"}, origin)
            actor_hash = hashlib.sha256(
                ("wecare-contribute-staff:" + username).encode("utf-8")
            ).hexdigest()
            return _staff_contribution_send(
                staff_candidate, origin, staff_actor_hash=actor_hash)
        except Exception as error:
            logger.error(json.dumps({"event": "staff_contribute_unavailable",
                                     "reason": type(error).__name__}))
            return cors_response(503, {
                "error": "CONTRIBUTION_UNAVAILABLE",
                "sendUnconfirmed": True,
                "message": "Could not confirm the request. Check the payment ledger before retrying.",
            }, origin)

    # THE ONE PRE-AUTH ARM, and it is deliberately the narrowest shape that can exist: GET only,
    # on one exact path, taking no path parameter, no query string and no body. Nothing a caller
    # supplies reaches a table or a provider, which is what makes an anonymous route safe here.
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
    # customerId or phone).
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
        if action == "quote":
            return _website_quote(identity, body, origin)
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
        # Explicitly retire the old individual-order breakdown API. Customers still
        # get the five-column history from /ecommerce/my-orders and securely signed
        # invoice downloads from /ecommerce/my-invoice. Critically, keep this case
        # ahead of the create fallback: an old detail request must NEVER create a
        # payable attempt, expose invoice sequence/GST lines, or read an order.
        if action == "order":
            return _hardened(cors_response(410, {"error": "ORDER_DETAILS_RETIRED"}, origin))
        if action == "request-service-start":
            return _request_service_start(identity, body, origin)
        if action == "create":
            return _create(identity, body, origin)
        # Unknown operations must never fall through into a payable action.
        return cors_response(400, {"error": "UNKNOWN_CHECKOUT_ACTION"}, origin)
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
    """Return a verified profile only for the permanent customer owner.

    WhatsApp OTP plus the stored Cognito owner, not an optional email address,
    establishes checkout identity. Do not turn a valid phone-owned profile into
    PROFILE_REQUIRED just because the customer never supplied an email.
    Ownerless and foreign-owner contacts remain unavailable.
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
    name = str(row.get("name") or f"{first} {last}").strip()
    company = str(row.get("companyName") or "").strip()
    designation = str(row.get("designation") or "").strip()
    return _hardened(cors_response(200, {
        "status": "PROFILE_READY",
        "contactId": contact_key.resolve(row),
        "name": name,
        "username": str(row.get("profileUsername") or "").strip(),
        # Legacy fields stay in the reply while older clients drain; the current cart uses the
        # canonical F001 name and no longer asks for email.
        "firstName": first,
        "lastName": last,
        "companyName": company,
        "designation": designation,
        "email": str(row.get("email") or "").strip(),
        # From the ROW, with the session value only as a fallback: the row holds the
        # `normalize_phone_preserving_country` output that `customer-profile` also returns, so
        # reading `identity.phone` directly would make the identity card's Phone row change
        # spelling after an edit.
        "phone": str(row.get("phone") or identity.phone),
        "emailVerified": bool(row.get("emailVerifiedAt")),
        # F001 requires the customer name; organisation, job title and username are optional.
        # Delivery readiness is kept separate below so a saved profile with no address still
        # opens the address editor instead of being treated as payable.
        "profileComplete": bool(name),
        "addressComplete": address is not None,
        "address": address,             # null when absent
    }, origin))


def _catalog_contents(snapshot) -> list:
    """Return exact Meta-joinable product/variant identities from one frozen quote.

    This is analytics metadata only. It is copied from the same server-authoritative frozen
    snapshot used for pricing; no browser name, SKU, amount or display value is trusted. If even
    one line is malformed the whole list is suppressed so a later Purchase event cannot partially
    attribute a basket.
    """
    frozen = snapshot.frozen_data if snapshot is not None and isinstance(snapshot.frozen_data, dict) else {}
    lines = frozen.get("items") if isinstance(frozen.get("items"), list) else []
    if not lines:
        return []
    out = []
    for line in lines:
        if not isinstance(line, dict):
            return []
        product_id = str(line.get("productId") or "").strip()
        variant_id = str(line.get("variantId") or "").strip()
        quantity = line.get("quantity")
        if not product_id or not variant_id or type(quantity) is not int or quantity <= 0:
            return []
        out.append({
            "productId": product_id,
            "variantId": variant_id,
            "quantity": quantity,
        })
    return out


def _cart_order_details(snapshot, reference_id: str, profile: Dict[str, Any],
                        address: Dict[str, Any], now: int, *,
                        requires_delivery: bool = True) -> Dict[str, Any]:
    """Build Meta ORDER_DETAILS from the same frozen server-authoritative cart quote.

    The browser contributes only product/variant ids and quantities. Names are display-only reads
    from ProductsTable; every amount comes from the frozen snapshot and its CheckoutQuote.
    """
    from lambda_utils.ecommerce import default_coupon

    frozen = snapshot.frozen_data if isinstance(snapshot.frozen_data, dict) else {}
    frozen_items = frozen.get("items") if isinstance(frozen.get("items"), list) else []
    reader = _native_product_reader()
    items = []
    merchandise_paise = 0
    for line in frozen_items:
        if not isinstance(line, dict):
            continue
        product_id = str(line.get("productId") or "")
        quantity = int(line.get("quantity") or 0)
        unit_paise = int(line.get("unitPricePaise") or 0)
        if not product_id or quantity <= 0 or unit_paise <= 0:
            raise ValueError("unusable frozen cart line")
        product = reader(product_id) or {}
        name = str(product.get("title") or product.get("name") or "WECARE.DIGITAL item").strip()
        items.append({
            "name": name[:60],
            "quantity": quantity,
            "amount": {"value": unit_paise, "offset": 100},
        })
        merchandise_paise += unit_paise * quantity

    if not items:
        raise ValueError("frozen cart has no payable items")

    quote = snapshot.quote
    delivery = frozen.get("delivery") if isinstance(frozen.get("delivery"), dict) else {}
    delivery_paise = int(delivery.get("paise") or 0)
    pricing_metadata = (
        frozen.get("pricingMetadata") if isinstance(frozen.get("pricingMetadata"), dict) else {}
    )
    supply_gst_paise = int(pricing_metadata.get("supplyGstPaise") or 0)
    explicit_discount = pricing_metadata.get("discountPaise")

    # Vault / Drop Docs have an explicit supply-GST step before Delight. Meta ORDER_DETAILS has
    # one tax field, which is already used for GST on the convenience fee. To keep the payment
    # sheet arithmetically honest, fold the supply GST into the one service item's displayed
    # amount and label that item as GST-inclusive. Delight remains Meta's separate discount row,
    # Express remains shipping, and GST on the convenience fee remains tax.
    if supply_gst_paise:
        if len(items) != 1:
            raise ValueError("explicit supply GST requires exactly one service item")
        items[0]["amount"]["value"] += supply_gst_paise
        items[0]["name"] = (items[0]["name"] + " (incl. GST 18%)")[:60]

    display_merchandise_paise = merchandise_paise + supply_gst_paise
    if explicit_discount is not None:
        discount_paise = max(0, int(explicit_discount))
    else:
        # Ordinary native carts already carry GST-inclusive catalogue prices. For those carts the
        # only adjustment between merchandise + delivery and collection is Delight.
        discount_paise = max(
            0, display_merchandise_paise + delivery_paise
            - int(quote.collection_before_convenience_paise))

    subtotal_paise = display_merchandise_paise
    if quote.convenience_fee_paise:
        # A non-catalog line: no retailer_id. `retailer_id` names a catalog content id, and this
        # fee is not in any catalog, so a made-up one would be a synthetic catalog identity.
        items.append({
            "name": "Convenience fee",
            "quantity": 1,
            "amount": {"value": int(quote.convenience_fee_paise), "offset": 100},
        })
        subtotal_paise += int(quote.convenience_fee_paise)

    order = {
        "status": "pending",
        "items": items,
        "subtotal": {"value": subtotal_paise, "offset": 100},
        "shipping": {"value": delivery_paise, "offset": 100},
        "tax": {
            "value": int(quote.convenience_gst_paise),
            "offset": 100,
            "description": "GST on convenience fee",
        },
        "expiration": {
            "timestamp": str(now + 900),
            "description": "Complete payment within 15 minutes",
        },
    }
    if discount_paise:
        order["discount"] = {
            "value": discount_paise,
            "offset": 100,
            "description": default_coupon.DISPLAY_LABEL,
        }
        order["couponCode"] = default_coupon.DELIGHT_CODE

    result = {
        "reference_id": reference_id,
        "type": "physical-goods" if requires_delivery else "digital-goods",
        "currency": "INR",
        "payment_configuration": EXPECTED_CONFIGURATION_NAME,
        "total_amount": {"value": int(quote.total_payable_paise), "offset": 100},
        "order": order,
    }
    if requires_delivery:
        full_address = ", ".join(
            part for part in (
                str(address.get("addressLine1") or "").strip(),
                str(address.get("addressLine2") or "").strip(),
            ) if part)
        result["shipping_info"] = {
            "country": str(address.get("countryCode") or "IN"),
            "addresses": [{
                # The SAME recipient `order_delivery.attempt_fields` freezes for the order, so the
                # name Meta shows before payment is the name the order page shows after it.
                "name": order_delivery.recipient_name(profile)[:60],
                "address": full_address[:300],
                "landmark_area": str(address.get("locality") or address.get("addressLine2") or "")[:100],
                "city": str(address.get("city") or "")[:60],
                "state": str(address.get("state") or "")[:60],
                "in_pin_code": str(address.get("postalCode") or "")[:12],
            }],
        }
    return result


def _native_invoice_lines(snapshot) -> Optional[Dict[str, Any]]:
    """The lines the paid invoice for a WhatsApp cart must itemise, recorded on the attempt.

    Stored BESIDE `purchasedSnapshot`, never inside it: product names are display data and must
    not move `snapshotHash` or `quoteHash`. Every amount is the frozen integer paise the customer
    reviewed in the ORDER_DETAILS message - the lines, the Delight discount, and the convenience
    fee with its GST - so the invoice issued after capture describes exactly what was paid.

    None when the snapshot cannot be itemised (a supply-GST or delivery term this cart does not
    carry today, an unusable line). The invoice then keeps its single-line inclusive split.
    """
    from lambda_utils.ecommerce import default_coupon

    frozen = snapshot.frozen_data if isinstance(snapshot.frozen_data, dict) else {}
    frozen_items = frozen.get("items") if isinstance(frozen.get("items"), list) else []
    reader = _native_product_reader()
    names: Dict[str, str] = {}
    lines = []
    merchandise_paise = 0
    for line in frozen_items:
        if not isinstance(line, dict):
            return None
        product_id = str(line.get("productId") or "")
        quantity = int(line.get("quantity") or 0)
        unit_paise = int(line.get("unitPricePaise") or 0)
        if not product_id or quantity <= 0 or unit_paise <= 0:
            return None
        if product_id not in names:
            product = reader(product_id) or {}
            names[product_id] = str(product.get("title") or product.get("name")
                                    or "WECARE.DIGITAL item").strip()[:120]
        lines.append({"productId": product_id, "variantId": str(line.get("variantId") or ""),
                      "name": names[product_id], "quantity": quantity,
                      "unitPricePaise": unit_paise})
        merchandise_paise += unit_paise * quantity
    if not lines:
        return None
    # This public item wording is not the catalog SKU and never affects price.
    # The same frozen invoice line is used for Meta Review & Pay and for the
    # actual paid GST invoice image, including website-origin Vault checkout.
    if (len(lines) == 1
            and lines[0]["variantId"] == service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
            and lines[0]["productId"] == service_requests.SERVICE_PRODUCT_BY_VARIANT[
                service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]]
            and lines[0]["quantity"] == 1 and lines[0]["unitPricePaise"] == 4900):
        from lambda_utils.ecommerce.catalog_service_checkout import VAULT_ITEM_DESCRIPTION_DEFAULT
        lines[0]["name"] = VAULT_ITEM_DESCRIPTION_DEFAULT
    delivery = frozen.get("delivery") if isinstance(frozen.get("delivery"), dict) else {}
    delivery_paise = int(delivery.get("paise") or 0)
    quote = snapshot.quote
    pricing_metadata = (
        frozen.get("pricingMetadata") if isinstance(frozen.get("pricingMetadata"), dict) else {}
    )
    supply_gst_paise = int(pricing_metadata.get("supplyGstPaise") or 0)
    explicit_discount = pricing_metadata.get("discountPaise")
    if explicit_discount is not None:
        discount_paise = max(0, int(explicit_discount))
    else:
        discount_paise = merchandise_paise + delivery_paise - int(
            quote.collection_before_convenience_paise)
        if discount_paise < 0:
            return None
    spec: Dict[str, Any] = {
        "lines": lines,
        "supplyGstPaise": supply_gst_paise,
        "deliveryPaise": delivery_paise,
        "discountPaise": discount_paise,
        "convenienceFeePaise": int(quote.convenience_fee_paise),
        "convenienceGstPaise": int(quote.convenience_gst_paise),
        "totalPaise": int(quote.total_payable_paise),
    }
    if discount_paise:
        spec["discountCode"] = default_coupon.DELIGHT_CODE
    return spec


class DeliveryMethodUnavailable(purchase_intent.DeliveryDetailsRequired):
    """A chosen delivery method cannot be offered for this basket — DISTINCT from "no address or
    method chosen yet" (`DeliveryDetailsRequired`), which it subclasses so the base arm still
    catches it if a caller does not special-case it. `src/pages/cart.tsx` branches on the
    `DELIVERY_METHOD_UNAVAILABLE` code separately, so the two must not collapse. Native shipping
    currently exposes a single free option, so nothing raises this today; it is retained as the
    seam for a future shipping policy with real, selectable methods.
    """


def _vault_dropdocs_quote(identity, ephemeral_cart: dict, reader, now: int):
    """Owner-approved Vault/Drop Docs sequence in exact integer paise.

    ProductsTable line price -> 18% supply GST -> Delight -> Rs25 Express ->
    canonical 2.5% Convenience Fee -> 18% GST on that fee -> Amount Payable.
    """
    from lambda_utils.ecommerce import default_coupon, service_requests

    # Read/freeze the authoritative ProductsTable line once; no adjustment is trusted from client.
    base = native_checkout.quote_native_cart(
        ephemeral_cart,
        product_reader=reader,
        customer_id=identity.customer_id,
        created_at=now,
        ttl_seconds=WEBSITE_SNAPSHOT_TTL_SECONDS,
        shipping_policy=native_shipping.ShippingPolicy(),
        gst_bps=0,
        coupon_definition=None,
    )
    frozen = base.frozen_data if isinstance(base.frozen_data, dict) else {}
    frozen_items = frozen.get("items") if isinstance(frozen.get("items"), list) else []
    item_paise = sum(
        int(line.get("unitPricePaise") or 0) * int(line.get("quantity") or 0)
        for line in frozen_items if isinstance(line, dict)
    )
    if item_paise <= 0:
        raise ValueError("Vault/Drop Docs service item price unavailable")

    supply_gst_paise = checkout_pricing.round_half_up(item_paise, 1800)
    gst_inclusive_paise = item_paise + supply_gst_paise
    delight_paise = default_coupon.delight_paise(gst_inclusive_paise)
    express_paise = service_requests.VAULT_DROP_DOCS_EXPRESS_PAISE
    collection_paise = gst_inclusive_paise - delight_paise + express_paise
    quote = checkout_pricing.compute_quote(collection_paise, currency="INR")
    return checkout_pricing.build_snapshot(
        customer_id=base.customer_id,
        cart_id=base.cart_id,
        cart_revision=base.cart_revision,
        quote=quote,
        created_at=base.created_at,
        ttl_seconds=base.expires_at - base.created_at,
        site=frozen.get("site"),
        items=frozen_items,
        address=frozen.get("address"),
        delivery={"paise": express_paise, "optionId": "express"},
        pricing_metadata={
            "policy": "vault-dropdocs-explicit-gst-2026-10-28",
            "supplyGstPaise": supply_gst_paise,
            "discountPaise": delight_paise,
        },
    )



def _contribution_quote(identity: customer_auth.CustomerIdentity, ephemeral_cart: dict,
                        reader, now: int, canonical: list):
    """Single-item ₹300 Contribute: exact purpose-specific GST/Delight/Express quote.

    The catalog still sells ONE ₹300 gross product; the server alone expands that
    gross target into the approved 23541 + 4237 - 138 + 1500 + 729 + 131
    native payment lines. Neither browser nor staff supplies any term. This
    must remain isolated from the Vault/Drop Docs and ordinary cart policies.
    """
    if len(canonical) != 1:
        raise ContributionRejected("CONTRIBUTION_REQUIRES_ONE_LINE")
    product_id, variant_id, quantity = canonical[0]
    if str(product_id).lower() not in CONTRIBUTION_PRODUCT_IDS:
        raise ContributionRejected("UNKNOWN_CONTRIBUTION_PRODUCT")
    if variant_id not in CONTRIBUTION_CHOICES_PAISE:
        raise ContributionRejected("UNKNOWN_CONTRIBUTION_VARIANT")
    if quantity != 1:
        raise ContributionRejected("CONTRIBUTION_QUANTITY_MUST_BE_ONE")
    base = native_checkout.quote_native_cart(
        ephemeral_cart,
        product_reader=reader,
        customer_id=identity.customer_id,
        created_at=now,
        ttl_seconds=WEBSITE_SNAPSHOT_TTL_SECONDS,
        shipping_policy=native_shipping.ShippingPolicy(),
        gst_bps=0,
        coupon_definition=None,
    )
    frozen = base.frozen_data if isinstance(base.frozen_data, dict) else {}
    source_items = frozen.get("items") if isinstance(frozen.get("items"), list) else []
    if len(source_items) != 1 or not isinstance(source_items[0], dict):
        raise ContributionRejected("CONTRIBUTION_CATALOG_UNAVAILABLE")
    source = source_items[0]
    if (source.get("productId", "").lower() != str(product_id).lower()
            or source.get("variantId") != variant_id
            or source.get("quantity") != 1
            or type(source.get("unitPricePaise")) is not int):
        raise ContributionRejected("CONTRIBUTION_CATALOG_CHANGED")
    terms = contribute_taxable.breakdown(source["unitPricePaise"])
    collection = terms["collectionBeforeConveniencePaise"]
    quote = checkout_pricing.compute_quote(collection, currency="INR")
    if (quote.total_payable_paise != terms["totalPayablePaise"]
            or quote.convenience_fee_paise != terms["convenienceFeePaise"]
            or quote.convenience_gst_paise != terms["convenienceGstPaise"]):
        raise ContributionRejected("CONTRIBUTION_TOTAL_UNSETTLED")
    line = dict(source)
    line["unitPricePaise"] = terms["itemSubtotalPaise"]
    return checkout_pricing.build_snapshot(
        customer_id=base.customer_id,
        cart_id=base.cart_id,
        cart_revision=base.cart_revision,
        quote=quote,
        created_at=base.created_at,
        ttl_seconds=base.expires_at - base.created_at,
        site=frozen.get("site"),
        items=[line],
        address=frozen.get("address"),
        delivery={"paise": terms["expressPaise"], "optionId": "contribute-express"},
        pricing_metadata={
            "policy": contribute_taxable.POLICY,
            "catalogGrossPaise": terms["catalogGrossPaise"],
            "supplyGstPaise": terms["supplyGstPaise"],
            "discountPaise": terms["delightPaise"],
        },
    )


def _native_quote(identity: customer_auth.CustomerIdentity, line_items: list, now: int):
    """Price a basket of `catalogReference` line items into a native QuoteSnapshot.

    A line names a ProductsTable product (`catalogItemId`) and variant (`options.variantId`).
    This is the ONE pricing seam: the website `prepare` path and the WhatsApp catalog-service
    `_create` path both canonicalise the browser's basket the same way and quote it off
    ProductsTable via `native_checkout.quote_native_cart`. No client-supplied price:
    identifiers in, server-authoritative snapshot out.

    The cart id is a content hash of (customer, sorted variants+quantities), so retrying the exact
    same basket mints the SAME id -- the one-live-payment guard in `website_checkout` keys on it,
    and two tabs for the same items cannot acquire independent payment claims.
    """
    import hashlib
    from lambda_utils.ecommerce import native_cart
    by_variant: Dict[tuple, int] = {}
    for li in line_items:
        if not isinstance(li, dict):
            raise ValueError("cart line must be an object")
        ref = li.get("catalogReference")
        ref = ref if isinstance(ref, dict) else {}
        options = ref.get("options")
        options = options if isinstance(options, dict) else {}
        product_id = str(ref.get("catalogItemId") or li.get("productId") or "").strip()
        variant_id = str(options.get("variantId") or li.get("variantId") or "").strip()
        if not product_id or not variant_id:
            raise ValueError("native cart line needs a product and variant identifier")
        qty = li.get("quantity")
        if type(qty) is not int or not 1 <= qty <= 100000:
            raise ValueError("quantity must be an integer in 1..100000")
        key = (product_id, variant_id)
        by_variant[key] = by_variant.get(key, 0) + qty
        if by_variant[key] > 100000:
            raise ValueError("aggregate quantity exceeds line limit")
    canonical = sorted((pid, vid, qty) for (pid, vid), qty in by_variant.items())
    if not canonical or len(canonical) > 100:
        raise ValueError("cart must contain 1..100 distinct variants")
    stable_input = json.dumps(
        [identity.customer_id, canonical],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    cart_key = hashlib.sha256(stable_input).hexdigest()
    reader = _native_product_reader()
    native_lines = []
    for product_id, variant_id, qty in canonical:
        # Product and variant must be ACTIVE and exist in ProductsTable. A name/price from the
        # public browser is never pricing authority; unknown variant IDs never fall back to a
        # product's base price.
        price = native_cart._unit_price_paise(reader, product_id, variant_id)
        native_lines.append({
            "productId": product_id,
            "variantId": variant_id,
            "quantity": qty,
            "unitPricePaise": price,
            # Never let a browser claim a physical product needs no delivery. The native shipping
            # policy currently charges zero, and actual shipping rules can be enforced by a
            # trusted product policy.
            "requiresDelivery": product_id.lower() not in CONTRIBUTION_PRODUCT_IDS,
        })
    ephemeral_cart = {
        "cartId": "native:" + cart_key,
        "updatedAt": 0,  # stable across retries of the exact same basket
        "lineItems": native_lines,
    }
    # A contribution is a separate voluntary payment contract. Do not mix it with products or
    # service fulfilment: that would either add a fee to the contribution or make one checkout
    # produce two different legal/fulfilment outcomes.
    contribution_lines = [
        row for row in canonical if str(row[0]).lower() in CONTRIBUTION_PRODUCT_IDS
    ]
    if contribution_lines:
        if len(contribution_lines) != len(canonical):
            raise ContributionRejected("CONTRIBUTION_MUST_BE_SEPARATE")
        return _contribution_quote(identity, ephemeral_cart, reader, now, canonical)

    # Delight is server-owned. Vault/Drop Docs use the explicit owner-approved service sequence;
    # every other basket keeps its existing native pricing contract.
    from lambda_utils.ecommerce import default_coupon, service_requests
    service_line = service_requests.service_line(line_items)
    if service_line is not None and service_line.kind in (
            service_requests.VAULT, service_requests.DROP_DOCS):
        return _vault_dropdocs_quote(identity, ephemeral_cart, reader, now)

    coupon_definition = (
        default_coupon.delight_definition()
        if not service_requests.has_service_line(line_items)
        else None
    )
    return native_checkout.quote_native_cart(
        ephemeral_cart,
        product_reader=reader,
        customer_id=identity.customer_id,
        created_at=now,
        ttl_seconds=WEBSITE_SNAPSHOT_TTL_SECONDS,
        shipping_policy=native_shipping.ShippingPolicy(),
        gst_bps=0,
        coupon_definition=coupon_definition,
    )


def _website_snapshot(identity: customer_auth.CustomerIdentity, line_items: list, now: int):
    """The website basket's immutable QuoteSnapshot, priced from ProductsTable.

    The collection comes from ProductsTable via `_native_quote`
    (`native_checkout.quote_native_cart`), and the convenience fee + GST from
    `checkout_pricing.compute_quote`. Everything downstream -- the attempt, the Razorpay order,
    the order record, the invoice and reconciliation -- reads this one frozen snapshot. The
    website submits `catalogReference` line items, which `_native_quote` reads as ProductsTable
    product and variant ids.
    """
    return _native_quote(identity, line_items, now)


def _reserve_website_attempt(attempt: Dict[str, Any]) -> None:
    _attempts_table().put_item(
        Item=attempt,
        ConditionExpression="attribute_not_exists(paymentAttemptId)",
    )


def _basket_requires_delivery(line_items: Any) -> bool:
    """Whether this basket ships anything: the server twin of `src/lib/cart.ts::cartRequiresDelivery`.

    Every line that is neither a contribution nor a service is a product that ships. Fails
    CLOSED: a line whose product cannot be read counts as shipping, so a malformed basket is asked
    for an address rather than waved past it (the native quote refuses that basket anyway).
    """
    if not isinstance(line_items, list) or not line_items:
        return True
    for line in line_items:
        reference = line.get("catalogReference") if isinstance(line, dict) else None
        product_id = (str(reference.get("catalogItemId") or "").strip().lower()
                      if isinstance(reference, dict) else "")
        if not product_id:
            return True
        if (product_id not in CONTRIBUTION_PRODUCT_IDS
                and not service_requests.is_service_product(product_id)):
            return True
    return False


def _refresh_attempt_delivery(attempt_id: str, identity: customer_auth.CustomerIdentity,
                              fields: Dict[str, Any]) -> None:
    """Re-stamp the confirmed delivery address on an UNPAID website attempt. Never raises.

    `website_checkout.prepare_checkout` reserves the attempt once per request key, and a later
    prepare of the same basket resumes it without writing it again. A customer who closed the
    payment window, changed the address and then paid would otherwise ship to the address of the
    first prepare. The update is conditional on the session owning the row and on no capture or
    finalization being recorded on it, so a late or concurrent prepare can never move the address
    of an order that is already paid. Every paid-state writer is covered: the browser verify
    (`_record_verified_capture`) stamps `paidAt` and the verified amount, `finalization.record_paid`
    stamps `paidAt` and the verified provider payment id, and `accept_paid` stages the attempt.
    """
    if not attempt_id or not fields:
        return
    names: Dict[str, str] = {"#owner": "customerId"}
    values: Dict[str, Any] = {":owner": identity.customer_id}
    sets = []
    for index, (key, value) in enumerate(sorted(fields.items())):
        names[f"#f{index}"] = key
        values[f":v{index}"] = value
        sets.append(f"#f{index} = :v{index}")
    update = "SET " + ", ".join(sets)
    if order_delivery.RECIPIENT not in fields:
        # A recipient the profile no longer has must not survive from the earlier prepare.
        names["#recipient"] = order_delivery.RECIPIENT
        update += " REMOVE #recipient"
    try:
        _attempts_table().update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression=update,
            ConditionExpression=("attribute_exists(paymentAttemptId) AND #owner = :owner AND "
                                 "attribute_not_exists(paidAt) AND "
                                 "attribute_not_exists(" + finalization.VERIFIED_CAPTURED_PAISE_ATTR
                                 + ") AND attribute_not_exists(verifiedProviderPaymentId) AND "
                                 "attribute_not_exists(finalizationStage)"),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values)
    except Exception as error:  # noqa: BLE001 - the payment window must still open
        if order_keys.is_conditional_failure(error):
            # Paid, finalised or not this session's row: what is frozen on it stands.
            return
        logger.warning(json.dumps({"event": "checkout_attempt_delivery_refresh_failed",
                                   "error": type(error).__name__}))



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
    `/orders` tag and GST invoice. The pointer records the cart the lines were merged into and
    `whatsapp_basket.active_claim` refuses to answer for any other cart, so the label expires
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
            _keys_table(), _native_cart_adapter(identity.customer_id)).resolve(identity)
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
    """Adopt a WhatsApp catalogue hand-off into the signed-in customer's own cart (CartTable).

    `require_customer` has already run in `handler`, so there is a proven session here and no
    unauthenticated caller reaches this function at all - which is also why the token alone is
    never sufficient: the claim requires the session's phone to equal the phone the hand-off was
    written for.

    THIS ACTION QUOTES NOTHING. It merges lines and marks a row; it computes no total, reads no
    price and returns no money field. The arithmetic stays where it already lives - `_native_quote`
    prices the collection from ProductsTable and `checkout_pricing.compute_quote` turns it into a
    payable, once, on the following `prepare`. That is the whole reason the WhatsApp leg has no
    calculator of its own.

    WHAT IT WRITES, in order, and why that order:

      1. the customer's cart, through `CustomerCart.ensure` - resolve before generate, so one
         purchase has one cart and a retried claim cannot mint a second one;
      2. the hand-off row marked claimed, CONDITIONALLY on `attribute_not_exists(claimedAt)`, so a
         second claim loses the write rather than being refused by a check it could race;
      3. the channel pointer `_claimed_handoff` reads.

    The cart comes first because `ensure` is idempotent and the mark is not: marking first and
    failing at the cart write would burn a basket that was never merged, which is unrecoverable
    from the customer's side. Doing it this way means the worst case is a merged cart whose row is
    still unclaimed - and the second claim then no-ops on `ensure` and completes the mark.

    `resetCart` IS READ HERE, AND IT IS WHAT STOPS `BASKET_CART_IN_USE` BEING A DEAD END. The
    "empty your website cart and open the link again" answer below instructs the customer to clear
    a cart they cannot reach: `clearCart()` empties localStorage, while the condition is the
    SERVER-side `CUSTOMERCART#<phone>` pointer, which lives thirty days and survives the payment
    that consumed its cart. So a customer who paid on the website, then sent a WhatsApp cart, read
    an instruction with no way to follow it and had to wait out the pointer. `src/pages/cart.tsx`
    now retries ONCE with `resetCart: true` when its own cart is empty, and that is the only
    caller that sets it.

    IT RELEASES A POINTER AND LOSES NOTHING DURABLE, which is why it is defensible on this path.
    The browser cart - not the saved server cart - is what the next prepare prices:
    `_website_prepare` quotes the request's own line items through `_native_quote`. So the worst
    case is a saved cart abandoned that no prepare would have priced anyway. `is True` is an
    identity comparison, not a coercion: a truthy reading of `"false"` would make a typo
    destructive.
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
    # An old WhatsApp multi-product hand-off remains unclaimed. Reject before ensure(), so
    # it neither mutates the saved cart nor spends a one-use token without a payable item.
    if short_purchase.enabled() and not short_purchase.one_unit_lines(items):
        return cors_response(200, {
            "status": "BASKET_SHORT_ONLY",
            "message": "Select one product with quantity one in WhatsApp, then send it again.",
        }, origin)

    carts = customer_cart.CustomerCart(_keys_table(), _native_cart_adapter(identity.customer_id))
    try:
        if body.get("resetCart") is True:
            # BEFORE `ensure`, so the create below is reached rather than the existing cart being
            # resolved. `abandon` refuses while the row is `busy` and answers False when there is
            # no pointer at all, so an unnecessary reset is a no-op rather than an error.
            if carts.abandon(identity):
                logger.info(json.dumps({"event": "checkout_basket_claim_cart_released"}))
        cart_id, created = carts.ensure(identity, items)
    except customer_cart.CartBusy:
        # A lock means another cart write is in flight and its outcome is unknown. The hand-off is
        # LEFT UNCLAIMED so the customer can try again, which is the recoverable direction.
        return cors_response(200, {
            "status": "CART_RECONCILIATION_REQUIRED",
            "message": "Your cart is being updated. Please try again shortly.",
        }, origin)

    if not created:
        # THE CUSTOMER ALREADY HAS A LIVE SAVED CART, AND THIS IS REPORTED RATHER THAN RESOLVED.
        #
        # `ensure` is resolve-before-generate: it returns the existing cart and does NOT add to it.
        # So the hand-off lines did not land, and there are only three honest options - add them
        # (several cart writes inside the function's 20s budget), replace the cart (discarding
        # lines the customer put there on the website), or say so.
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
        # They were merged into the server-side cart above, but the cart the customer SEES - and
        # the basket `_website_prepare` prices, because it quotes the request's own line items -
        # is the browser's localStorage cart. A count alone would leave that cart untouched, so a
        # successful claim would show no items (indistinguishable from a refusal) and the next
        # checkout would not carry the claimed lines.
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


#: The ORDER_DETAILS expiry the WhatsApp "Pay on WhatsApp" rail stamps on its PaymentAttempt
#: (`now + 900`, the same window `_cart_order_details` writes into the Meta `expiration`). Recorded
#: on the attempt as `paymentRequestExpiresAt` so the one-live-payment guard can tell a request the
#: customer can still pay from one that has lapsed, WITHOUT consulting Meta. Equal to the
#: `_cart_order_details` expiry and to `WA_CART_LIVE_SECONDS`.
WA_REQUEST_LIVE_SECONDS = 900
#: The handler-level cross-rail refusal both rails answer with, so the browser's existing
#: CHECKOUT_AMBIGUOUS branch (navigate to /checkout/status/?a=) covers it with no frontend change.
PAYMENT_IN_PROGRESS_OTHER_RAIL = "PAYMENT_IN_PROGRESS_OTHER_RAIL"


def _website_invoice_lines(snapshot) -> Optional[Dict[str, Any]]:
    """`_native_invoice_lines` for the website attempt, guarded so it can NEVER refuse a checkout.
    The website snapshot and the WhatsApp-cart snapshot both come from `_native_quote`, so the
    shape `_native_invoice_lines` expects is identical. Display data only: any failure answers
    None and the attempt simply carries no lines, exactly as before this landed.
    """
    try:
        return _native_invoice_lines(snapshot)
    except Exception as error:  # noqa: BLE001 - display data must never refuse a checkout
        logger.warning(json.dumps({"event": "website_checkout_invoice_lines_unavailable",
                                   "error": type(error).__name__}))
        return None


def _attempt_is_website(attempt: Dict[str, Any]) -> bool:
    """Whether a stored attempt belongs to the website Razorpay Standard Checkout rail.
    Keyed on `checkoutMode`, the one field each rail stamps unconditionally: the website rail
    writes `website_checkout.CHECKOUT_MODE_WEBSITE`, and both WhatsApp rails write a
    `wa_payment_request` native-cart/service mode. `channel` is deliberately NOT used -- a website
    order can be attributed to the WhatsApp CHANNEL, so channel does not name the settlement rail.
    """
    return str(attempt.get("checkoutMode") or "") == website_checkout.CHECKOUT_MODE_WEBSITE


def _wa_request_live(attempt: Dict[str, Any], now: int) -> bool:
    """Whether a WhatsApp "Pay on WhatsApp" request on this attempt can still be paid.
    Live means in flight AND inside the ORDER_DETAILS window the attempt recorded. The window is
    read off `paymentRequestExpiresAt`; an attempt written before that field existed falls back to
    the shared in-flight window, which only ever OVER-blocks (fail-safe, never a second charge).
    """
    if not payment_attempt.is_in_flight(attempt):
        return False
    expires_at = int(attempt.get("paymentRequestExpiresAt") or 0)
    if expires_at:
        return now <= expires_at
    moved = int(attempt.get("updatedAt") or attempt.get("createdAt") or 0)
    return now - moved <= website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS


def _website_attempt_live(attempt: Dict[str, Any], now: int) -> bool:
    """Whether a website attempt is a live, unpaid gateway order inside its block window."""
    if not payment_attempt.is_in_flight(attempt):
        return False
    moved = int(attempt.get("updatedAt") or attempt.get("createdAt") or 0)
    return now - moved <= website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS


def _basket_pointer_attempt_ids(keys, *, customer_id: str, cart_id: str,
                                basket_hash: str, narrow_hash: str) -> list:
    """The attempt ids named by the THREE shared cart pointer rows, de-duplicated, order-stable.
    These are the exact rows the website rail writes (`order_keys.record_cart_*`) and its guard
    reads, so the WhatsApp "Pay on WhatsApp" rail claiming the same rows is what makes "one live
    payment per basket" hold ACROSS both rails rather than within each. Lets
    `OrderIdentityUnavailable` propagate: the caller must never read a storage failure as "no live
    payment", because it would then create one.
    """
    ids: list = []
    seen: set = set()
    rows = []
    if cart_id:
        rows.append(order_keys.resolve_cart_payment(
            keys, customer_id=customer_id, cart_id=cart_id) or {})
        if basket_hash:
            rows.append(order_keys.resolve_cart_basket(
                keys, customer_id=customer_id, cart_id=cart_id, basket_hash=basket_hash) or {})
        if narrow_hash:
            rows.append(order_keys.resolve_cart_narrow_basket(
                keys, customer_id=customer_id, cart_id=cart_id, narrow_hash=narrow_hash) or {})
    for row in rows:
        attempt_id = str((row or {}).get("paymentAttemptId") or "")
        if attempt_id and attempt_id not in seen:
            seen.add(attempt_id)
            ids.append(attempt_id)
    return ids


def _cross_rail_block(identity: customer_auth.CustomerIdentity, snapshot, now: int, *,
                      this_rail_is_website: bool):
    """One live payment per basket, ACROSS the website and WhatsApp rails. Shared slot design.

    THE SLOT. The website rail already writes three CommerceKeys pointer rows per basket --
    `CARTPAYMENT#<cus>#<cart>` (which attempt is LIVE on the cart), `CARTBASKET#<cus>#<cart>#<hash>`
    and `CARTNARROW#<cus>#<cart>#<narrow>` (has THIS BASKET been paid) -- and its guard
    (`website_checkout._live_cart_payment`) reads exactly those rows. The WhatsApp "Pay on
    WhatsApp" rail prices with the SAME `_native_quote`, so it derives the SAME `cart_id` and basket
    hashes and can claim the SAME rows (`_record_cross_rail_pointer` below). Both rails therefore
    share ONE slot per customer+cart+basket identity instead of inventing a second. No new row kind
    and no DeleteItem is needed: the rows already exist and are upserted.

    THE DECISION. This reads the shared rows, resolves each named attempt, and classifies it:
      * PAID (`payment_attempt.may_create_order`)             -> CART_ALREADY_PAID, both rails.
      * live on the OTHER rail                                -> PAYMENT_IN_PROGRESS_OTHER_RAIL.
    A live attempt on the SAME rail is NOT reported here: the website rail's own in-rail guard
    (inside `prepare_checkout`) and the WhatsApp rail's same-request-key dedup own that case, and
    reporting it here would convert a legitimate resume into a refusal. Liveness is judged with
    `paymentRequestExpiresAt` for a WhatsApp request (so an expired one stops blocking and a fresh
    attempt is allowed) and the shared in-flight window for a website order.

    Returns `(reason, attempt_id)` or `('', '')`. Lets `OrderIdentityUnavailable` propagate so the
    caller fails closed with a 503 rather than creating a second payable order.
    """
    keys = _keys_table()
    try:
        basket = checkout_pricing.basket_hash(snapshot.frozen_data)
        narrow = checkout_pricing.narrow_basket_hash(snapshot.frozen_data)
    except checkout_pricing.PricingError:
        # No frozen payload means no basket identity and no guard; the per-rail request-key and
        # reference reservations remain. A lost backstop, never an open door.
        return "", ""
    attempt_ids = _basket_pointer_attempt_ids(
        keys, customer_id=identity.customer_id, cart_id=snapshot.cart_id,
        basket_hash=basket, narrow_hash=narrow)
    for attempt_id in attempt_ids:
        stored = _attempts_table().get_item(
            Key={"paymentAttemptId": attempt_id}, ConsistentRead=True).get("Item")
        if not stored:
            continue
        if str(stored.get("customerId") or "") != identity.customer_id:
            # The pointer is an INDEX, not an authority. A foreign-owned row is corrupt and must
            # neither block this customer nor be trusted.
            logger.warning(json.dumps({"event": "checkout_cross_rail_pointer_foreign"}))
            continue
        if payment_attempt.may_create_order(stored):
            return website_checkout.CART_ALREADY_PAID, attempt_id
        other_is_website = _attempt_is_website(stored)
        if other_is_website == this_rail_is_website:
            # Same rail: owned by the per-rail guard / dedup, not reported cross-rail.
            continue
        live = (_website_attempt_live(stored, now) if other_is_website
                else _wa_request_live(stored, now))
        if live:
            return PAYMENT_IN_PROGRESS_OTHER_RAIL, attempt_id
    return "", ""


def _record_cross_rail_pointer(snapshot, *, customer_id: str, attempt_id: str,
                               request_key: str) -> None:
    """Claim the shared cart pointer rows for a WhatsApp "Pay on WhatsApp" attempt.
    The SAME three rows the website rail writes, so the website guard sees this live WhatsApp
    payment and refuses a second order for the basket. A lost row re-opens the double-order path,
    but the WhatsApp rail has already SENT the request by the time the slot matters, so a write
    failure here is logged rather than undoing a delivered payment request -- the per-attempt
    `paymentRequestExpiresAt` and the website guard's own in-flight check still bound it. An empty
    key part (`ValueError`/`PricingError`) is swallowed to a log: this is attribution for the
    cross-rail guard, never a money decision.
    """
    try:
        basket = checkout_pricing.basket_hash(snapshot.frozen_data)
        narrow = checkout_pricing.narrow_basket_hash(snapshot.frozen_data)
        keys = _keys_table()
        order_keys.record_cart_payment(
            keys, customer_id=customer_id, cart_id=snapshot.cart_id,
            payment_attempt_id=attempt_id, request_key=request_key,
            basket_hash=basket, narrow_basket_hash=narrow,
            snapshot_hash=snapshot.snapshot_hash)
        order_keys.record_cart_basket(
            keys, customer_id=customer_id, cart_id=snapshot.cart_id,
            basket_hash=basket, payment_attempt_id=attempt_id,
            request_key=request_key, narrow_basket_hash=narrow,
            snapshot_hash=snapshot.snapshot_hash)
        if narrow:
            order_keys.record_cart_narrow_basket(
                keys, customer_id=customer_id, cart_id=snapshot.cart_id,
                narrow_hash=narrow, payment_attempt_id=attempt_id,
                request_key=request_key, basket_hash=basket,
                snapshot_hash=snapshot.snapshot_hash)
    except (order_keys.OrderIdentityUnavailable, ValueError,
            checkout_pricing.PricingError) as error:  # noqa: BLE001
        logger.warning(json.dumps({"event": "checkout_cross_rail_pointer_save_failed",
                                   "error": type(error).__name__}))


def _verify_vault_website_renewal(identity: customer_auth.CustomerIdentity,
                                  body: Dict[str, Any], line_items: Any) -> None:
    """Refuse a second charge if a Vault file was paid after its cart intent was minted.

    The website cart retains the immutable INTENT# file binding. This check reads
    owner, file and entitlement at prepare time, immediately before any gateway
    order can be minted. Never use a browser-supplied fileId, phone, price or grant.
    Other products and services are unaffected.
    """
    line = service_requests.service_line(line_items)
    if not line or line.kind != service_requests.VAULT:
        return
    iid = body.get("serviceIntentId")
    if not isinstance(iid, str) or not service_requests.INTENT_ID_RE.fullmatch(iid):
        raise website_checkout.CheckoutRejected("VAULT_FILE_BINDING_REQUIRED")
    intent = _table("stack-wecare-digital-ServiceRequestsTable").get_item(
        Key={"requestId": "INTENT#" + iid}, ConsistentRead=True).get("Item") or {}
    file_id = str(intent.get("vaultFileId") or "")
    if (not file_id or intent.get("kind") != service_requests.VAULT
            or intent.get("ownerCustomerId") != identity.customer_id
            or intent.get("status") != "OPEN"
            or intent.get("variantId") != line.variant_id
            or intent.get("targetRequestId") != "FILE#" + file_id):
        raise website_checkout.CheckoutRejected("VAULT_FILE_BINDING_INVALID")
    file_row = _table("stack-wecare-digital-SecureFilesTable").get_item(
        Key={"fileId": file_id}, ConsistentRead=True).get("Item") or {}
    if (file_row.get("status") != "active"
            or file_row.get("ownerCustomerId") != identity.customer_id
            or file_row.get("ownerPhone") != intent.get("vaultOwnerPhone")):
        raise website_checkout.CheckoutRejected("VAULT_FILE_UNAVAILABLE")
    # A paid 24-hour entitlement can no longer be renewed. A stale website
    # intent created before the original capture must not be charged again,
    # regardless of whether the existing access is READY, OPEN or EXPIRED.
    # Read the durable grant rather than trusting only a possibly delayed
    # SecureFilesTable pointer.
    entitlement = _table("stack-wecare-digital-DownloadGrantsTable").get_item(
        Key={"grantId": "vault-entitlement#" + identity.customer_id + "#" + file_id},
        ConsistentRead=True,
    ).get("Item") or {}
    if entitlement:
        if (entitlement.get("recordType") != "VAULT_ENTITLEMENT"
                or entitlement.get("entitlementState") != "ACTIVE"
                or entitlement.get("customerId") != identity.customer_id
                or entitlement.get("fileId") != file_id
                or entitlement.get("ownerPhone") != file_row.get("ownerPhone")):
            raise website_checkout.CheckoutRejected("VAULT_ENTITLEMENT_UNVERIFIED")
        raise website_checkout.CheckoutRejected("VAULT_ALREADY_PAID")
    if (file_row.get("vaultPaymentStatus") == "PAID"
            or file_row.get("vaultEntitlementId")
            or file_row.get("vaultAccessGrantId")):
        raise website_checkout.CheckoutRejected("VAULT_ALREADY_PAID")


def _website_quote(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                   origin: str) -> Dict[str, Any]:
    """READ ONLY: price the full website basket before a Razorpay order is created.

    Returns the same ProductsTable-backed QuoteSnapshot and invoice-line breakdown
    used by _website_prepare. It performs no CartTable write, PaymentAttempt
    allocation, gateway-order creation, message send or invoice issuance.

    Names and financial terms must reconcile to the server quote in exact paise.
    Never fall back to client catalogue display prices on a missing term.
    """
    def answer(code: int, data: Dict[str, Any]) -> Dict[str, Any]:
        return _hardened(cors_response(code, data, origin))

    # Read-only customer quote. Staff provenance belongs to _staff_contribution_send,
    # not this customer action (which has no staff_actor_hash variable).
    line_items = body.get("lineItems")
    if not isinstance(line_items, list) or not line_items:
        return answer(400, {"error": "LINE_ITEMS_REQUIRED"})
    refusal = service_requests.checkout_preflight(line_items, body)
    if refusal is not None:
        return answer(refusal[0], refusal[1])
    try:
        _verify_vault_website_renewal(identity, body, line_items)
        profile = _checkout_profile(identity)
        if not profile or not str(profile.get("name") or
                f'{profile.get("firstName") or ""} {profile.get("lastName") or ""}').strip():
            return answer(409, {"error": "PROFILE_REQUIRED"})
        if _basket_requires_delivery(line_items):
            address = contact_address.from_contact(profile)
            if address is None:
                return answer(409, {"error": "DELIVERY_DETAILS_REQUIRED"})
            try:
                payment_address.assert_payable(
                    address, channel=payment_address.WEBSITE_RAZORPAY)
            except payment_address.UnpayableAddress:
                return answer(409, {"error": "DELIVERY_DETAILS_REQUIRED"})

        snapshot = _website_snapshot(identity, line_items, int(time.time()))
        spec = _website_invoice_lines(snapshot)
        if not spec:
            return answer(503, {"error": "QUOTE_BREAKDOWN_UNAVAILABLE"})
        items = _display_lines(spec.get("lines"))
        charges = _order_charges(spec, items, int(snapshot.quote.total_payable_paise))
        if not items or charges is None:
            return answer(503, {"error": "QUOTE_BREAKDOWN_UNAVAILABLE"})
        return answer(200, {"status": "QUOTE_READY",
                            "quote": {"currency": "INR",
                                      "items": items,
                                      "charges": charges}})
    except website_checkout.CheckoutRejected as rejected:
        return answer(409, {"error": "CHECKOUT_REJECTED",
                            "reason": rejected.reason})
    except (ContributionRejected, service_requests.ServiceNotPayable,
            service_requests.ServicePriceChanged, cart_contract.CartContractError,
            checkout_pricing.PricingError, catalog_pricing.CatalogPricingError,
            ValueError):
        return answer(409, {"error": "CART_NOT_PAYABLE"})
    except Exception as exc:  # noqa: BLE001 - no PII in logs or browser
        logger.error(json.dumps({"event": "website_quote_failed",
                                 "error": type(exc).__name__}))
        return answer(503, {"error": "QUOTE_UNAVAILABLE"})


def _website_prepare(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
                     origin: str) -> Dict[str, Any]:
    line_items = body.get("lineItems")
    request_key = str(body.get("requestKey") or "").strip()
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED"}, origin)
    # Website checkout accepts the complete catalogue basket. The opt-in one-unit
    # enforcement remains on the separate native WhatsApp paths; the website's
    # existing quote/cart contract validates product and quantity server-side.
    if not request_key or len(request_key) > 80:
        return cors_response(400, {"error": "REQUEST_KEY_REQUIRED"}, origin)
    # Phase O-1: a services basket is refused here, PURE, before the profile read, any pricing or
    # any DynamoDB write -- Drop Docs/Vault, a bad quantity or a missing intent.
    refusal = service_requests.checkout_preflight(line_items, body)
    if refusal is not None:
        return cors_response(refusal[0], refusal[1], origin)
    # A Vault intent minted before an original capture must not be renewed,
    # even if the customer's paid access window has since expired.
    try:
        _verify_vault_website_renewal(identity, body, line_items)
    except website_checkout.CheckoutRejected as rejected:
        return cors_response(409, {
            "status": website_checkout.CHECKOUT_REJECTED,
            "reason": rejected.reason,
        }, origin)
    except Exception as error:
        logger.warning(json.dumps({"event": "vault_website_preflight_unavailable",
                                   "error": type(error).__name__}))
        return cors_response(503, {"error": "VAULT_VERIFICATION_UNAVAILABLE"}, origin)

    profile = _checkout_profile(identity)
    if not profile:
        return cors_response(409, {
            "error": "PROFILE_REQUIRED",
            "message": "Sign in with your verified WhatsApp number and save your name first.",
        }, origin)
    # The minimal phone-only contact created during OTP bootstrap is an identity,
    # not a completed checkout profile. Digital-service checkouts need a name,
    # even when no shipping address or email is required.
    if not str(profile.get("name") or
               f'{profile.get("firstName") or ""} {profile.get("lastName") or ""}').strip():
        return cors_response(409, {
            "error": "PROFILE_REQUIRED",
            "message": "Add your name to continue checkout.",
        }, origin)

    # THE DELIVERY ADDRESS, enforced HERE for a basket that ships. The browser's readiness probe
    # asks for it too, but a probe that could not answer still posts prepare (CartPage rule 2), so
    # this is the authority. It is read off the session-owned contact row `_checkout_profile` just
    # returned, never from the request, and asked the WEBSITE channel's payment rule: in India a
    # six-digit PIN and a resolvable state, because the address is the place of supply. A
    # contribution- or service-only basket ships nothing and is not asked.
    #
    # The address that passes is frozen on the attempt (`delivery_fields`), so the order this
    # payment becomes ships where the customer confirmed, whatever the profile says later.
    delivery_fields: Dict[str, Any] = {}
    if _basket_requires_delivery(line_items):
        delivery_address = contact_address.from_contact(profile)
        if delivery_address is None:
            return cors_response(409, {
                "error": "DELIVERY_DETAILS_REQUIRED",
                "message": "Add your delivery address to continue.",
            }, origin)
        try:
            payment_address.assert_payable(
                delivery_address, channel=payment_address.WEBSITE_RAZORPAY)
        except payment_address.UnpayableAddress:
            return cors_response(409, {
                "error": "DELIVERY_DETAILS_REQUIRED",
                "message": "We cannot deliver to this address yet. Please check it and save it again.",
            }, origin)
        delivery_fields = order_delivery.attempt_fields(delivery_address, profile)

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
    # The contact row's own id, off the same row. `resolve` never raises and answers "" for a
    # row without one, which suppresses the field rather than inventing a link.
    public_contact_id = contact_key.resolve(profile)

    now = int(time.time())
    keys = _keys_table()
    try:
        # Phase O-1: before pricing, a resumed key bound to a superseded service intent.
        _refuse_rebound_service_intent(identity, request_key, body, keys)
        snapshot = _website_snapshot(identity, line_items, now)

        # A services basket's payment reference MUST carry the price of the one service as frozen
        # in the ProductsTable-backed snapshot: a reference recorded with `paise=None` would leave
        # even a verified capture PAID_SERVICE_UNMATCHED. Resolved here, before the gateway order
        # is created, so a disagreement refuses while no money can have moved. `None` for a
        # basket with no service line.
        native_service_paise = service_requests.native_service_line_paise(snapshot, line_items)
        # CROSS-RAIL one-live-payment guard, BEFORE the gateway order is created. The website
        # rail's OWN in-rail guard (inside `prepare_checkout`) already refuses a second website
        # order and a paid basket; this arm adds the OTHER rail -- a live WhatsApp "Pay on
        # WhatsApp" request on the same basket -- so one basket can never hold a live payment
        # on both rails at once. Answered as CHECKOUT_AMBIGUOUS so `cart.tsx` navigates to the
        # status page; `PAYMENT_IN_PROGRESS_OTHER_RAIL` is the honest "in progress elsewhere".
        cross_reason, cross_attempt = _cross_rail_block(
            identity, snapshot, now, this_rail_is_website=True)
        if cross_reason:
            logger.info(json.dumps({"event": "website_checkout_cross_rail_block",
                                    "reason": cross_reason}))
            return cors_response(200, {
                "status": website_checkout.CHECKOUT_AMBIGUOUS,
                "reason": cross_reason,
                "paymentAttemptId": cross_attempt,
            }, origin)

        def _allocate_reference(attempt_id: str, leg_paise: int) -> str:
            """Mint and durably reserve the `PAYREF#` row the webhook reconciles on.

            The leg is an ARGUMENT rather than captured from the enclosing scope, because it is
            computed INSIDE `prepare_checkout` -- a closure could not see it.
            """
            return order_keys.allocate_payment_reference(
                keys, payment_attempt_id=attempt_id,
                extra={
                    "customerId": identity.customer_id,
                    # THE RAZORPAY LEG, which is what a capture will be compared against.
                    "amountPaise": leg_paise,
                    # The frozen payable, beside it. `_tenders_reconcile` reads the payable off
                    # the ATTEMPT row, not this one.
                    "payablePaise": snapshot.quote.total_payable_paise,
                    "currency": "INR",
                    "checkoutMode": website_checkout.CHECKOUT_MODE_WEBSITE,
                    # BESIDE `checkoutMode`, never inside it. On the `PAYREF#` row as well as the
                    # attempt because the webhook reconciles on this row and a channel it cannot
                    # read is a channel a reconciliation cannot report.
                    "channel": channel,
                    "cartId": snapshot.cart_id,
                    "cartRevision": snapshot.cart_revision,
                    "quoteHash": snapshot.snapshot_hash,
                    "collectionPaise":
                        snapshot.quote.collection_before_convenience_paise,
                    "quoteExpiresAt": snapshot.expires_at,
                    "policyVersion": snapshot.policy_version,
                    # Phase O-1: `{"serviceLine": {...}}` for a services basket, `{}` otherwise,
                    # so every other PAYREF# row is byte-identical to before.
                    #
                    # `line_paise` is the service line's unit price read from the FROZEN native
                    # quote by `native_service_line_paise` above, never a committed constant and
                    # never a client amount, so an unpriced service row cannot be minted here.
                    **service_requests.payref_extra(
                        line_items, body, line_paise=native_service_paise),
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
                    # The verified session phone and the contact row's id, on the PAYREF#
                    # row as well as the attempt and for the same lineage reason as the
                    # public customer id above: the webhook reads attribution off PAYREF#
                    # while finalisation reads it off the attempt, so writing to only one
                    # leaves one settlement path without it. Spread CONDITIONALLY so a row
                    # with no phone / contact id keeps a byte-identical key set to before.
                    **({"customerPhone": _profile_phone(identity)}
                       if _profile_phone(identity) else {}),
                    **({"contactId": public_contact_id}
                       if public_contact_id else {}),
                })

        # The invoice line items the paid GST invoice itemises after capture, derived ONCE
        # here from the website snapshot (the SAME `_native_invoice_lines` the WhatsApp rail
        # records; both snapshots come from `_native_quote`, so the shape is identical). The
        # helper is guarded so this display data can never refuse a checkout.
        website_invoice_lines = _website_invoice_lines(snapshot)
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
                        if public_customer_uuid else {}),
                     # The ONE ContactsTable row this customer has - the row the session owns,
                     # already read by `_checkout_profile` - so the order lands on the same
                     # contact the WhatsApp inbox and Flows use, whichever channel it came from.
                     **({'contactId': public_contact_id} if public_contact_id else {}),
                     # Invoice lines beside the attribution, emitted only when present so an
                     # un-itemisable snapshot leaves a byte-identical attempt. Same field and
                     # shape the WhatsApp rail writes.
                     **({'invoiceLines': website_invoice_lines}
                        if website_invoice_lines else {}),
                     # The confirmed delivery address, `{}` for a basket that ships nothing.
                     **delivery_fields)),
            # The read-only attempt store the one-live-payment guard needs. Without it the guard
            # can tell a basket has a recorded attempt but not whether that attempt was paid.
            attempts_table=_attempts_table(),
            allocate_reference=_allocate_reference,
            purchased_snapshot=snapshot.frozen_data,
        )
        # Phase O-1: again AFTER, authoritatively -- a concurrent click on the same key may have
        # bound its reference between the check above and the reservation. Options are never
        # handed out for an attempt bound to another intent.
        _refuse_rebound_service_intent(identity, request_key, body, keys)
    # ── EVERY `cart_contract.CartContractError` SUBCLASS MUST PRECEDE ITS PARENT ARM BELOW, or it is
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
    # Phase O-1 services. Both are `CartContractError`s, so both MUST stay above that arm.
    except ServicePriceChanged:
        return cors_response(409, service_requests.refusal(
            service_requests.SERVICE_PRICE_CHANGED), origin)
    except ServiceNotPayable:
        logger.error(json.dumps({"event": "service_not_payable"}))
        return cors_response(409, service_requests.refusal(
            service_requests.SERVICE_NOT_PAYABLE), origin)
    except DeliveryMethodUnavailable:
        # MUST stay ABOVE the `DeliveryDetailsRequired` arm below, or the subclass is swallowed by
        # it and DELIVERY_METHOD_UNAVAILABLE never fires. The distinction (a chosen method that
        # cannot be offered, versus no address/method chosen at all) is a customer-facing refusal
        # `src/pages/cart.tsx` still branches on; native shipping yields a single free option
        # today, so this is dormant, but the contract and the ordering are kept intact.
        return cors_response(409, {"error": "DELIVERY_METHOD_UNAVAILABLE"}, origin)
    except purchase_intent.DeliveryDetailsRequired:
        return cors_response(409, {"error": "DELIVERY_DETAILS_REQUIRED"}, origin)
    except india_address.UnmappableAddress:
        # Belt and braces. `from_contact` re-validates, so the normal answer for a stored address
        # that cannot be mapped is already this 409 via the arm above; without this arm an
        # unmappable address would fall through the generic `except Exception` to
        # `503 TEMPORARILY_UNAVAILABLE` -- a dead end, because no retry fixes it. No delivery
        # detail in the log line: every component of one is PII, and the event name is spelled
        # `..._delivery_unmappable` rather than the design's `..._address_unmappable` for the
        # same AST-gate reason recorded on `checkout_stored_delivery_unusable`.
        logger.info(json.dumps({"event": "website_checkout_delivery_unmappable",
                                "customerIdPresent": True}))
        return cors_response(409, {"error": "DELIVERY_DETAILS_REQUIRED"}, origin)
    # ── The cart-contract arms, in the same codes and messages `_create` answers with: a locked
    # ── or unpayable cart must not read as two different problems on two routes. Without these,
    # ── each would fall to the generic arm below and answer 503 TEMPORARILY_UNAVAILABLE -- a
    # ── code the browser treats as transient, for conditions no retry can clear.
    except cart_contract.CartItemUnavailable as unavailable:
        logger.info(json.dumps({"event": "checkout_item_unavailable",
                                "count": len(unavailable.items)}))
        return cors_response(409, {
            "error": "ITEMS_UNAVAILABLE", "items": unavailable.items,
            "message": "Some items are no longer available. Please review your cart.",
        }, origin)
    except cart_contract.CartQuantityReduced as reduced:
        logger.info(json.dumps({"event": "checkout_quantity_reduced",
                                "count": len(reduced.items)}))
        return cors_response(409, {
            "error": "QUANTITY_REDUCED", "items": reduced.items,
            "message": "Some items are available in smaller quantities than you asked for. "
                       "Please confirm the new amounts.",
        }, origin)
    except cart_contract.CartGone:
        # The cart row the contract expected is gone, which is a fault on our side rather than a
        # customer mistake, and `logger.error` is the level that says so. Deliberately NOT
        # `CART_ITEM_UNAVAILABLE`: no item has been shown to be missing, and telling a customer to
        # remove one would send them after a line that is fine. Must precede the parent arm below.
        logger.error(json.dumps({"event": "website_checkout_cart_gone_unrecoverable"}))
        return cors_response(409, {"error": "CART_NOT_PAYABLE",
                                   "message": "Please review your cart and try again."}, origin)
    except cart_contract.CartContractError:
        # The parent of the item arms and CartResetRequired above (and the catch-all for any
        # residual contribution/contract violation), so it is LAST among them.
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
    except (checkout_pricing.PricingError, catalog_pricing.CatalogPricingError):
        # The native quote could not settle an amount (empty cart, unreadable price). 409 so the
        # customer reviews rather than a 502 they read as our failure.
        return cors_response(409, {"error": "AMOUNT_NOT_SETTLED"}, origin)
    except Exception as error:  # noqa: BLE001
        logger.error(json.dumps({"event": "website_checkout_prepare_failed",
                                 "error": type(error).__name__}))
        return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin)

    if prepared.status == website_checkout.CHECKOUT_OPTIONS_READY and delivery_fields:
        # A RESUMED request key re-opens the attempt the first prepare reserved, without writing
        # it again, so the address on it is the one confirmed THEN. Re-stamp the one confirmed
        # now, while nothing has been paid on it.
        _refresh_attempt_delivery(prepared.payment_attempt_id, identity, delivery_fields)

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

    # ── the second-tender gate ──
    #
    # `accept_paid` is the ONLY production writer of the order record, so this gate refuses
    # exactly the tenders it cannot close, rather than every attempt that carries a second leg:
    # a blanket refusal would leave `finalization._tenders_reconcile` correct and unconsulted.
    #
    # An UNREADABLE tender is refused too: `None` means a listed tender attribute is present but
    # not integer paise, and an amount we cannot read is not the same as no amount. This is an
    # unreadable test and never a PRESENCE test, because tender evidence may be recorded as 0
    # before anything is debited. A READABLE tender is closed by `finalization._tenders_reconcile`
    # itself, exact integers, fail closed on one paise.
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
    # prepare resolves the very same saved cart id, the pointer still matches it, and an ordinary
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


def _request_service_start(identity: customer_auth.CustomerIdentity,
                           body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Start one paid request service against one EXISTING owned order.

    Public input for Flow-backed services is deliberately only
    ``serviceCode + selectedOrderNumber``. Customer id, price, SKU, internal order id, phone
    and Flow identity are all server-owned. Vault is not accepted here: it is bought per secure
    file from /vault/?file=<fileId> and must carry a server-verified file binding before any
    payment exists.
    The public order number resolves through the immutable CommerceKeys ORDERNO# reservation,
    then the OrderTable row is re-read and ownership/status are verified before the context is
    allowed near checkout.
    """
    if not isinstance(body, dict):
        return cors_response(400, {"error": "INVALID_REQUEST"}, origin)
    allowed = {"serviceCode", "selectedOrderNumber", "action"}
    if any(key not in allowed for key in body):
        return cors_response(400, {"error": "INVALID_REQUEST_FIELDS"}, origin)

    service_code = str(body.get("serviceCode") or "").strip().upper()
    selected_order_number = str(body.get("selectedOrderNumber") or "").strip().upper()
    contract = request_service_contracts.request_service_contract(service_code)
    if contract is None:
        return cors_response(400, {"error": "UNKNOWN_SERVICE"}, origin)
    if contract.fulfillment_kind != "flow":
        # Vault is deliberately absent from the generic request rail. Charging it without the
        # exact owned secure file would create money with nothing safe to unlock.
        return cors_response(409, {"error": "SERVICE_REQUIRES_SECURE_FILE"}, origin)
    if not order_keys.is_public_order_number(selected_order_number):
        return cors_response(400, {"error": "INVALID_ORDER_NUMBER"}, origin)

    # The reservation is the immutable number->internal-order join. Never scan OrderTable and
    # never trust an internal id supplied by the browser.
    reservation = _keys_table().get_item(
        Key={"orderId": order_keys.ORDER_NUMBER_PREFIX + selected_order_number},
        ConsistentRead=True,
    ).get("Item") or {}
    selected_order_id = str(reservation.get("orderIdRef") or "")
    if not selected_order_id:
        # Missing and foreign orders are intentionally indistinguishable to the caller.
        return cors_response(404, {"error": "ORDER_NOT_AVAILABLE"}, origin)

    order = _table(ORDERS_TABLE).get_item(
        Key={"orderId": selected_order_id}, ConsistentRead=True
    ).get("Item") or {}
    if (str(order.get("customerId") or "") != identity.customer_id
            or str(order.get("orderNumber") or "").upper() != selected_order_number
            or payment_status.canonical(order.get("paymentStatus")) != payment_status.CAPTURED):
        return cors_response(404, {"error": "ORDER_NOT_AVAILABLE"}, origin)

    line_items = [{
        "catalogReference": {
            "catalogItemId": contract.product_id,
            "options": {"variantId": contract.sku},
        },
        "quantity": 1,
    }]
    verified_context = {
        "singleOrder": True,
        "serviceCode": contract.service_code,
        "selectedOrderId": selected_order_id,
        "selectedOrderNumber": selected_order_number,
        "sku": contract.sku,
        "flowCapability": contract.flow_capability,
        "fulfillmentKind": contract.fulfillment_kind,
    }
    # Context is passed as a Python argument, never copied into the request body. That is the
    # authorization boundary that prevents a browser from forging an owned order.
    return _create(
        identity,
        {"lineItems": line_items},
        origin,
        verified_service_context=verified_context,
    )


def _create(identity: customer_auth.CustomerIdentity, body: Dict[str, Any],
            origin: str, *, catalog_session: Optional[Dict[str, Any]] = None,
            native_contact: Optional[Dict[str, Any]] = None,
            verified_service_context: Optional[Dict[str, Any]] = None,
            required_staff_contribution: bool = False,
            staff_actor_hash: str = "") -> Dict[str, Any]:
    """Resolve authoritative totals, gate on readiness, reserve an attempt, hand off to WhatsApp."""
    line_items = body.get("lineItems")
    if not isinstance(line_items, list) or not line_items:
        return cors_response(400, {"error": "LINE_ITEMS_REQUIRED",
                                   "message": "Your cart is empty."}, origin)

    # Website Pay on WhatsApp uses action=create, not action=prepare.
    # An altered HTTP cart must not bypass the opt-in one-item rule and mint a
    # multi-unit native payment. Refuse before service, quote or attempt writes.
    if short_purchase.enabled() and not short_purchase.one_unit_lines(line_items):
        return cors_response(409, {
            "error": "SHORT_CHECKOUT_ONE_ITEM",
            "message": "Select one product, quantity one, to continue.",
        }, origin)

    # Services use the same pre-payment intent guard on both payment rails. A WhatsApp payment
    # must never be able to create a paid service with no request/target attached.
    service_guard = service_requests.checkout_preflight(
        line_items, body, verified_service_context=verified_service_context)
    if service_guard is not None:
        return cors_response(service_guard[0], service_guard[1], origin)

    # Ordinary cart checkout may now continue to either payment rail. The rail is chosen only
    # after the reviewed cart and authenticated profile are known. Services keep their dedicated
    # intent flow above; this arm is for ordinary product/contribution baskets.
    cart_profile: Optional[Dict[str, Any]] = None
    cart_address: Optional[Dict[str, Any]] = None
    requires_delivery = bool(catalog_session is None and _basket_requires_delivery(line_items))
    if catalog_session is None:
        # Native WhatsApp cart payment already has a signed-inbound, phone-bound ContactsTable
        # row from _native_whatsapp_identity. It must NOT require a browser profile/email just to
        # pay in WhatsApp. Website callers pass no native_contact and keep the existing profile
        # requirement unchanged.
        if native_contact is not None:
            cart_profile = native_contact
        else:
            cart_profile = _checkout_profile(identity)
            # The saved, phone-owned row may omit email, but the browser-led
            # WhatsApp rail still requires a human name. A phone-only OTP
            # bootstrap is an identity, not a payable customer profile.
            row = cart_profile or {}
            full_name = str(
                row.get("name") or
                f'{row.get("firstName") or ""} {row.get("lastName") or ""}'
            ).strip()
            if not cart_profile or not full_name.strip():
                return cors_response(409, {
                    "error": "PROFILE_REQUIRED",
                    "message": "Add your name to continue checkout.",
                }, origin)

        # A contribution or request-service basket has no shipment. Requiring a delivery address
        # for it made the native WhatsApp rail stricter than the website rail and blocked signed-in
        # customers from paying for a purely digital/service transaction. Physical baskets still
        # fail closed on the same India payment-address checks as before.
        if requires_delivery:
            cart_address = contact_address.from_contact(cart_profile)
            if cart_address is None:
                return cors_response(409, {
                    "error": "DELIVERY_DETAILS_REQUIRED",
                    "message": "Confirm your delivery address before paying on WhatsApp.",
                }, origin)
            try:
                payment_address.assert_payable(
                    cart_address, channel=payment_address.WHATSAPP_ORDER_DETAILS)
            except payment_address.UnpayableAddress:
                return cors_response(409, {
                    "error": "DELIVERY_DETAILS_REQUIRED",
                    "message": "This delivery address cannot be used for WhatsApp payment. "
                               "Update it or choose Pay here.",
                }, origin)

    # 1. Authoritative total, from ProductsTable. Both the ordinary cart WhatsApp rail and the
    #    catalog-service leg use the exact same native quote as website prepare. The browser sent
    #    catalogue references and quantities; the amount a customer
    #    pays is the CALCULATOR total -- the native collection plus the convenience fee plus the
    #    GST on that fee -- read off the frozen snapshot.
    native_service_paise: Optional[int] = None
    try:
        snapshot = _native_quote(identity, line_items, int(time.time()))
        amount_paise = snapshot.quote.total_payable_paise
        item_summary = [{"name": it.get("variantId"), "quantity": it.get("quantity")}
                        for it in snapshot.frozen_data.get("items", [])]
    except catalog_pricing.CatalogPricingError:
        return cors_response(502, {"error": "CATALOGUE_UNAVAILABLE",
                                   "message": "The store is temporarily unavailable."}, origin)
    except ValueError:
        return cors_response(409, {"error": "AMOUNT_NOT_SETTLED",
                                   "message": "We could not price this cart. Please try "
                                              "again."}, origin)

    if required_staff_contribution:
        # Last-before-write check: even if the staff preflight saw ₹300,
        # refuse a concurrent catalog or fee-policy change before PAYREF/attempt.
        variants = list(CONTRIBUTION_CHOICES_PAISE)
        if (len(variants) != 1 or not staff_contribution.valid_staff_contribution_snapshot(
                snapshot, product_id=CONTRIBUTION_PRODUCT_ID, variant_id=variants[0])):
            return cors_response(409, {
                "error": "CONTRIBUTION_PRICE_MISMATCH",
                "message": "The ₹300 contribution quote changed. Nothing was sent.",
            }, origin)

    if service_requests.has_service_line(line_items):
        # The authoritative per-line price, read from the FROZEN native quote (never a client
        # amount). Both website-origin and WhatsApp-origin service purchases bind this figure to
        # the PAYREF serviceLine so post-payment activation resolves the same service intent.
        try:
            native_service_paise = service_requests.native_service_line_paise(snapshot, line_items)
        except service_requests.ServicePriceChanged:
            logger.warning(json.dumps({"event": "service_refused",
                                       "reason": service_requests.SERVICE_UNAVAILABLE}))
            return cors_response(503, service_requests.refusal(
                service_requests.SERVICE_UNAVAILABLE), origin)
    # 1b. ONE LIVE PAYMENT PER BASKET, ACROSS RAILS -- only the HTTP "Pay on WhatsApp" rail.
    #     `catalog_session is None` AND a `requestKey` present scopes this to the browser rail;
    #     the internal `_native_cart` caller (no requestKey, its own WACARTLIVE# slot) and the
    #     catalog-service leg (`catalog_session` set) skip it and keep working unchanged. The
    #     SHARED SLOT is the website rail's own cart pointer rows: the request key is stored as a
    #     correlator on them, NOT reserved via REQUESTKEY# -- the frontend reuses one key across
    #     both rails and the website rail owns that REQUESTKEY# row, so claiming it here would
    #     corrupt its create-right coordination.
    wa_request_key = "" if catalog_session is not None else str(body.get("requestKey") or "").strip()
    now_create = int(time.time())
    if wa_request_key:
        try:
            # DEDUP: a repeat with the SAME key and SAME basket while the earlier WhatsApp
            # request is still payable returns the EXISTING attempt and sends nothing. Keyed on
            # the shared cart pointer, whose liveness is judged by `paymentRequestExpiresAt`, so
            # once the request lapses a fresh attempt is allowed.
            pointer = order_keys.resolve_cart_payment(
                _keys_table(), customer_id=identity.customer_id, cart_id=snapshot.cart_id) or {}
            pointer_attempt_id = str(pointer.get("paymentAttemptId") or "")
            if pointer_attempt_id:
                existing = _attempts_table().get_item(
                    Key={"paymentAttemptId": pointer_attempt_id},
                    ConsistentRead=True).get("Item") or {}
                same_customer = str(existing.get("customerId") or "") == identity.customer_id
                wa_live = (same_customer and not _attempt_is_website(existing)
                           and _wa_request_live(existing, now_create))
                if wa_live and str(pointer.get("requestKey") or "") == wa_request_key:
                    # DEDUP: the SAME key and SAME basket while the request is still payable.
                    # Return the existing attempt and send nothing. The amount is the one that
                    # attempt was sent for -- what the customer will actually pay on WhatsApp --
                    # not a re-quote, which can differ if a price moved in between.
                    logger.info(json.dumps({"event": "checkout_wa_request_deduplicated"}))
                    return cors_response(200, {
                        "status": "PAYMENT_REQUEST_SENT",
                        "paymentAttemptId": pointer_attempt_id,
                        "deduplicated": True,
                        "amountPaise": int(existing.get("amountPaise") or amount_paise),
                        "currency": "INR",
                        "message": "Check WhatsApp to complete your payment.",
                    }, origin)
                if wa_live:
                    # ONE LIVE PAYMENT PER BASKET, same rail: a DIFFERENT key presenting a
                    # basket that already has a live WhatsApp request. The HTTP WhatsApp rail
                    # has no other in-rail guard (unlike the website rail), so it is enforced
                    # here. Not a dedup -- a different key is a different interaction -- so the
                    # existing request is surfaced for the customer to finish rather than a
                    # second one minted. CHECKOUT_AMBIGUOUS sends the browser to the status
                    # page, same as the website rail's own in-flight refusal.
                    logger.info(json.dumps({"event": "checkout_wa_request_in_flight"}))
                    return cors_response(200, {
                        "status": website_checkout.CHECKOUT_AMBIGUOUS,
                        "reason": website_checkout.CART_PAYMENT_IN_FLIGHT,
                        "paymentAttemptId": pointer_attempt_id,
                    }, origin)
            # CROSS-RAIL: a live WEBSITE payment on this basket refuses here; a PAID basket
            # refuses on both rails. Both answer CHECKOUT_AMBIGUOUS so the browser navigates to
            # the status page.
            cross_reason, cross_attempt = _cross_rail_block(
                identity, snapshot, now_create, this_rail_is_website=False)
            if cross_reason:
                logger.info(json.dumps({"event": "checkout_wa_cross_rail_block",
                                        "reason": cross_reason}))
                return cors_response(200, {
                    "status": website_checkout.CHECKOUT_AMBIGUOUS,
                    "reason": cross_reason,
                    "paymentAttemptId": cross_attempt,
                }, origin)
        except order_keys.OrderIdentityUnavailable:
            # A read the guard depends on failed. Fail closed: refusing is safe, but creating a
            # second payable request is not.
            logger.error(json.dumps({"event": "checkout_wa_cross_rail_unavailable"}))
            return cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE",
                                       "message": "Please try again shortly."}, origin)
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

    # 2b. EVERY WHATSAPP CART CONFIRMS WHERE IT SHIPS. The ORDER_DETAILS message below shows the
    #     address on file but cannot change it, so a saved address is never assumed: a customer
    #     who has moved would otherwise pay to ship to the old one. Asked LAST, once the cart has
    #     priced and payments are ready, so a cart refused for another reason hears that reason
    #     rather than being sent an address form first. `deliveryConfirmed` is set only by
    #     inbound, when it resumes this cart from the customer's own Address Message submission
    #     (`prepareNativeCart` refuses any HTTP envelope). Meta sends that form to +91 numbers
    #     only, so any other number keeps paying against the address on file.
    if (native_contact is not None and body.get("deliveryConfirmed") is not True
            and contact_address.address_message_reaches(identity.phone)):
        return cors_response(409, {
            "error": "DELIVERY_CONFIRMATION_REQUIRED",
            "message": "Confirm the delivery address for this order.",
        }, origin)

    if required_staff_contribution:
        # Last-before-reservation FRESH price read, not the possibly stale
        # eventual reader used while building the native quote.
        variants = list(CONTRIBUTION_CHOICES_PAISE)
        if (len(variants) != 1 or not _staff_contribution_catalog_is_current(
                CONTRIBUTION_PRODUCT_ID, variants[0])):
            return cors_response(409, {"error": "CONTRIBUTION_CATALOG_CHANGED"}, origin)

    # 3. Reserve a canonical reference bound to a fresh attempt id, then build the attempt. The
    #    reference is minted and durably reserved BEFORE it is used, and never transformed after.
    attempt_id = payment_attempt.new_payment_attempt_id()
    checkout_mode = (
        CHECKOUT_MODE if catalog_session is not None
        else wa_payment_request.WA_NATIVE_CART_CHECKOUT_MODE
    )
    # The ONE sender for this payment request, resolved before the reservation so the PAYREF# row
    # records the same phone the ORDER_DETAILS template is sent from (step 4 below reuses it).
    send_phone_number_id = (str(catalog_session['phoneNumberId']) if catalog_session is not None
                            else wa_payment_request.PHONE_NUMBER_ID_1)
    try:
        extra = {"customerId": identity.customer_id,
                 "amountPaise": amount_paise, "currency": "INR",
                 "checkoutMode": checkout_mode,
                 "channel": order_channel.CHANNEL_WHATSAPP,
                 # Meta creates the Razorpay order when the customer taps Pay, so the Razorpay
                 # webhook can only bind a capture to this reference through an authenticated
                 # Meta payment lookup keyed on sender phone + configuration name
                 # (`meta_payment_binding.bind_attempt`). Without these two fields that lookup
                 # refuses, and every native capture is quarantined as PROVIDER_UNAVAILABLE.
                 # Same field names and source as the invoice-native reservation
                 # (`wa_payment_request._reference_row`). Server-owned values only.
                 "phoneId": send_phone_number_id,
                 "configurationName": EXPECTED_CONFIGURATION_NAME,
                 "wabaId": wa_payment_request.PHONE_ID_TO_WABA.get(send_phone_number_id, "")}
        if snapshot is not None:
            # The cart join keys. `cartId` + `cartRevision` is what reconciliation matches on,
            # and `quoteHash` is what proves the paid amount is the one the customer reviewed --
            # a cart edit produces a different hash rather than mutating this one.
            # `collectionPaise` is recorded beside the payable amount so the convenience fee and
            # its GST stay auditable instead of being inferred from a difference.
            extra.update(cartId=snapshot.cart_id, cartRevision=snapshot.cart_revision,
                         quoteHash=snapshot.snapshot_hash,
                         collectionPaise=snapshot.quote.collection_before_convenience_paise,
                         quoteExpiresAt=snapshot.expires_at,
                         policyVersion=snapshot.policy_version)
        if catalog_session is None and cart_profile is not None:
            public_uuid = customer_uuid.from_contact(cart_profile)
            public_contact_id = contact_key.resolve(cart_profile)
            extra.update(customerPhone=_profile_phone(identity))
            if public_uuid:
                extra[customer_uuid.ATTRIBUTE] = public_uuid
            if public_contact_id:
                extra["contactId"] = public_contact_id
        if required_staff_contribution:
            # Provenance only. Do NOT write legacy Razorpay notes.purpose,
            # which would divert the normal SKU-first capture settlement.
            extra["staffContribute"] = True
            extra["staffActorHash"] = staff_actor_hash
        if service_requests.has_service_line(line_items):
            extra.update(**service_requests.payref_extra(
                line_items, body, line_paise=native_service_paise,
                verified_service_context=verified_service_context))
        if catalog_session is not None:
            extra.update(channel='whatsapp', nativeCatalogService=True,
                         customerPhone=_profile_phone(identity))
            if catalog_session.get('customerUuid'):
                extra[customer_uuid.ATTRIBUTE] = str(catalog_session['customerUuid'])
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
        payment_attempt_id=attempt_id,
    )
    attempt["checkoutMode"] = checkout_mode
    if required_staff_contribution:
        attempt["staffContribute"] = True
        attempt["staffActorHash"] = staff_actor_hash
    if verified_service_context is not None:
        single = service_requests._single_order_context(verified_service_context)
        if single is None:
            return cors_response(409, {"error": "SERVICE_CONTEXT_INVALID"}, origin)
        attempt.update(
            singleOrderService=True,
            serviceCode=single["serviceCode"],
            serviceSku=single["sku"],
            selectedOrderId=single["selectedOrderId"],
            selectedOrderNumber=single["selectedOrderNumber"],
            serviceKind=single["serviceCode"],
            flowCapability=single["flowCapability"],
        )
    if snapshot is not None:
        catalog_contents = _catalog_contents(snapshot)
        if catalog_contents:
            attempt["catalogContents"] = catalog_contents
    if catalog_session is None and cart_profile is not None:
        attempt.update(
            channel=order_channel.CHANNEL_WHATSAPP,
            customerPhone=_profile_phone(identity),
            snapshotHash=snapshot.snapshot_hash,
            purchasedSnapshot=dict(snapshot.frozen_data),
        )
        public_uuid = customer_uuid.from_contact(cart_profile)
        public_contact_id = contact_key.resolve(cart_profile)
        if public_uuid:
            attempt[customer_uuid.ATTRIBUTE] = public_uuid
        if public_contact_id:
            attempt["contactId"] = public_contact_id
        # Only a shipping basket freezes delivery fields. Digital/service transactions have no
        # shipment and therefore no synthetic delivery address on the eventual order.
        if requires_delivery and cart_address is not None:
            attempt.update(order_delivery.attempt_fields(cart_address, cart_profile))
    if catalog_session is not None:
        # AWS-native WhatsApp catalog-service attempt. The authoritative record is the frozen
        # `purchasedSnapshot` + `snapshotHash`, which `finalization.accept_paid` turns into the
        # order record and stages ORDER_FINALIZED.
        attempt.update(nativeCatalogService=True, channel=order_channel.CHANNEL_WHATSAPP,
            customerPhone=_profile_phone(identity), catalogServiceSession=catalog_session['orderId'],
            snapshotHash=snapshot.snapshot_hash, purchasedSnapshot=dict(snapshot.frozen_data),
            serviceKind=str(catalog_session.get('kind') or ''),
            **({'vaultFileId': str(catalog_session.get('vaultFileId') or '')}
               if catalog_session.get('vaultFileId') else {}))
        # The session was opened for, and ownership-checked against, one ContactsTable row; the
        # order inherits it so the WhatsApp purchase sits on the same contact as everything else.
        if catalog_session.get('contactId'):
            attempt['contactId'] = str(catalog_session['contactId'])
        if catalog_session.get('customerUuid'):
            attempt[customer_uuid.ATTRIBUTE] = str(catalog_session['customerUuid'])
        if len(json.dumps(attempt, default=str).encode()) > 350000:
            return cors_response(409, {'error': 'CATALOG_SERVICE_SNAPSHOT_TOO_LARGE'}, origin)

    if snapshot is not None:
        # One canonical item/charge projection for every native checkout, including Vault.
        # It drives the paid invoice, customer order detail and Workspace order record from
        # exactly the same frozen quote Meta showed in ORDER_DETAILS.
        try:
            invoice_lines = _native_invoice_lines(snapshot)
        except Exception as error:  # noqa: BLE001 - display data must never refuse a checkout
            logger.warning(json.dumps({"event": "checkout_invoice_lines_unavailable",
                                       "error": type(error).__name__}))
            invoice_lines = None
        if invoice_lines:
            if catalog_session is not None and catalog_session.get("kind") == service_requests.VAULT:
                # Staff can edit ONLY the display name of the server-quoted one
                # ₹49 Vault item, never price, quantity, fees or another SKU.
                from lambda_utils.ecommerce.catalog_service_checkout import (
                    VAULT_EDITABLE_ITEM_PAISE, VAULT_ITEM_DESCRIPTION_DEFAULT,
                    valid_vault_item_description, vault_item_description)
                requested = catalog_session.get("paymentItemDescription")
                lines = invoice_lines.get("lines") or []
                vault_variant = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
                is_single_49_vault = (
                    len(lines) == 1 and lines[0].get("variantId") == vault_variant
                    and lines[0].get("productId") == service_requests.SERVICE_PRODUCT_BY_VARIANT[vault_variant]
                    and lines[0].get("quantity") == 1
                    and lines[0].get("unitPricePaise") == VAULT_EDITABLE_ITEM_PAISE)
                if requested is not None and not valid_vault_item_description(requested):
                    return cors_response(409, {"error": "VAULT_ITEM_DESCRIPTION_INVALID"}, origin)
                if requested and requested != VAULT_ITEM_DESCRIPTION_DEFAULT and not is_single_49_vault:
                    # Catalog price changed or multiple items unexpectedly supplied.
                    # Refuse BEFORE Meta send rather than showing a different name.
                    return cors_response(409, {"error": "VAULT_ITEM_NOT_49"}, origin)
                if is_single_49_vault:
                    label = vault_item_description(requested)
                    lines[0]["name"] = label
                    attempt["vaultItemDescription"] = label
            attempt["invoiceLines"] = invoice_lines

    attempt = payment_attempt.transition(
        attempt, payment_attempt.PAYMENT_READINESS_CHECKED)
    if wa_request_key:
        # The ORDER_DETAILS window (`now + 900`, the same expiry `_cart_order_details` stamps
        # into Meta) recorded on the attempt so the cross-rail guard can tell a request the
        # customer can still pay from a lapsed one WITHOUT asking Meta. Emitted only on this
        # rail, so every other attempt row is byte-identical to before.
        attempt["paymentRequestExpiresAt"] = now_create + WA_REQUEST_LIVE_SECONDS
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


    # One sender and one approved ORDER_DETAILS template for both WhatsApp checkout rails.
    # Ordinary carts use the authenticated profile/address and frozen cart snapshot; catalog
    # services keep their dedicated service metadata.
    if catalog_session is not None:
        from lambda_utils.ecommerce.catalog_service_checkout import payment_details
        contact_id = catalog_session['contactId']
        details = payment_details(
            catalog_session, snapshot.quote, reference_id,
            EXPECTED_CONFIGURATION_NAME, int(time.time()),
            invoice_lines=attempt.get("invoiceLines"),
        )
    else:
        contact_id = contact_key.resolve(cart_profile or {})
        details = _cart_order_details(
            snapshot, reference_id, cart_profile or {}, cart_address or {}, int(time.time()),
            requires_delivery=requires_delivery)
    # The sender recorded on the PAYREF# row above, so the Meta binding lookup after capture
    # addresses the phone that actually sent this payment request.
    sent = _send_order_details(
        phone=identity.phone, contact_id=contact_id,
        phone_number_id=send_phone_number_id, order_details=details)
    if wa_request_key and sent in (SEND_SENT, SEND_UNCONFIRMED):
        # The request has left, or may have (UNCONFIRMED: the sender timed out after Meta may
        # have accepted it). Either way it can be on the customer's phone, so claim the SHARED
        # cart pointer rows the website guard reads: a website prepare for this basket now sees
        # a live WhatsApp payment and refuses, and a same-key retry deduplicates onto this
        # attempt instead of minting a second payable request. Best-effort by design: the
        # attempt carries `paymentRequestExpiresAt`, so a lost pointer does not undo the send.
        _record_cross_rail_pointer(snapshot, customer_id=identity.customer_id,
                                   attempt_id=attempt_id, request_key=wa_request_key)
    if sent != SEND_SENT:
        # The attempt is stored and ready; no confirmed message. Still NO order and NO charge.
        # `sendUnconfirmed` tells an internal caller (the WhatsApp cart leg) that the request may
        # already be on the customer's phone, so it must keep its dedupe key rather than retry.
        # The website keeps reading `status` exactly as before.
        unconfirmed = sent == SEND_UNCONFIRMED
        return cors_response(502, {
            "status": "SEND_FAILED",
            "sendUnconfirmed": unconfirmed,
            "paymentAttemptId": attempt_id,
            "message": ("We could not confirm the payment request. Check WhatsApp before trying "
                        "again." if unconfirmed else
                        "We could not open the payment. Please try again."),
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
    # The stage itself is deliberately NOT consulted and NOT returned. A paid order can rest at
    # NEEDS_RECONCILIATION (a tender sum that did not close, a missing snapshot) while a human
    # reconciles it; that is our bookkeeping and it is not a fact about the customer's payment.
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


def _display_lines(lines: Any) -> list:
    """Order lines as `{name, quantity, unitPricePaise, totalPaise}`, or `[]`.

    ALL OR NOTHING, the rule `_catalog_contents` applies: one unreadable line suppresses the list,
    so the page never presents part of a basket as if it were the whole order.
    """
    if not isinstance(lines, list):
        return []
    out = []
    for line in lines:
        if not isinstance(line, dict):
            return []
        quantity = finalization.integer_paise(line.get("quantity"))
        unit = finalization.integer_paise(line.get("unitPricePaise"))
        if quantity is None or quantity <= 0 or unit is None or unit < 0:
            return []
        name = " ".join(str(line.get("name") or "").split())[:120] or "WECARE.DIGITAL item"
        out.append({"name": name, "quantity": quantity, "unitPricePaise": unit,
                    "totalPaise": unit * quantity})
    return out


def _order_charges(spec: Dict[str, Any], items: list,
                   amount: Optional[int]) -> Optional[Dict[str, Any]]:
    """The price breakdown recorded with the lines, or None when it does not reconcile.

    Integer paise only, and EXACT: merchandise + delivery - discount + fee + fee GST must equal
    the recorded total and the order's own amount. A breakdown that disagrees with what was
    charged by one paise is omitted rather than shown, and the page shows the total alone.
    """
    terms = {key: finalization.integer_paise(spec.get(key)) for key in (
        "deliveryPaise", "discountPaise", "convenienceFeePaise", "convenienceGstPaise",
        "totalPaise")}
    if any(value is None or value < 0 for value in terms.values()):
        return None
    supply_gst = finalization.integer_paise(spec.get("supplyGstPaise"))
    if supply_gst is None:
        supply_gst = 0
    if supply_gst < 0:
        return None
    merchandise = sum(item["totalPaise"] for item in items)
    total = (merchandise + supply_gst + terms["deliveryPaise"] - terms["discountPaise"]
             + terms["convenienceFeePaise"] + terms["convenienceGstPaise"])
    if total != terms["totalPaise"] or amount is None or total != amount:
        return None
    charges: Dict[str, Any] = {"merchandisePaise": merchandise, "supplyGstPaise": supply_gst, **terms}
    if terms["discountPaise"]:
        from lambda_utils.ecommerce import default_coupon
        # The one string any surface prints for this discount.
        charges["discountLabel"] = default_coupon.DISPLAY_LABEL
    return charges


# ── the WhatsApp order_details handoff ──────────────────────────────────────────

#: `_send_order_details` outcomes. UNCONFIRMED is distinct from FAILED: the sender may already
#: have delivered the payment request, so a caller must not treat it as "safe to send again".
SEND_SENT = "SENT"
SEND_FAILED = "FAILED"
SEND_UNCONFIRMED = "UNCONFIRMED"

#: Above wecare-outbound-whatsapp's 60 s function timeout, so the invoke returns that function's
#: own answer (or its timeout error) instead of timing out client-side mid-send.
OUTBOUND_SEND_READ_TIMEOUT_SECONDS = 75
_outbound_send_lambda = None


def _outbound_send_client():
    """The Lambda client for the payment send ONLY. No SDK retries, by design.

    botocore's default client retries an invoke on a read timeout, and a retried invoke of the
    sender is a second Meta send of the same payment request. Exactly one attempt; an ambiguous
    outcome is reported as UNCONFIRMED instead.
    """
    global _outbound_send_lambda
    if _outbound_send_lambda is None:
        from botocore.config import Config
        _outbound_send_lambda = boto3.client(
            "lambda", region_name=REGION,
            config=Config(read_timeout=OUTBOUND_SEND_READ_TIMEOUT_SECONDS,
                          retries={"max_attempts": 0}))
    return _outbound_send_lambda


def _send_order_details(*, phone: str, contact_id: str, phone_number_id: str,
                        order_details: dict) -> str:
    """Invoke the in-chat payment-request sender ONCE. Returns SEND_SENT on a 2xx, SEND_FAILED on
    a definite refusal, SEND_UNCONFIRMED when the sender may have delivered. THE ONLY SENDER HERE.

    This does NOT build `payment_settings` — `outbound-whatsapp._build_payment_settings` owns
    Mode 3, and the whole point of this shape is that it reaches that resolver. `payment_settings`
    is deliberately ABSENT from the payload: the `isCheckoutTemplate` branch builds them from the
    sender's configured gateway and now REFUSES a caller-supplied block outright, so the WABA1-only
    refusal, the `payment_link_uri` / `upi_intent_link` refusals, the WECAREDIGITAL configuration
    pin and the single-template pin all apply. The configuration NAME still travels, inside
    `order_details`, so the configuration `payment_readiness` proved is the configuration Meta is
    told to use.

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
            "templateName": whatsapp_templates.PAY.name,
            "templateParams": [],
            "checkoutOrderDetails": order_details,
            "idempotencyKey": f"payment-request:{str(order_details.get('reference_id') or '').strip()}",
        }),
    }
    from botocore.exceptions import ConnectionClosedError, ReadTimeoutError
    try:
        response = _outbound_send_client().invoke(
            FunctionName=OUTBOUND_SENDER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(invoke_event).encode("utf-8"),
        )
        raw = response["Payload"].read()
        result = json.loads(raw.decode("utf-8")) if raw else {}
        if response.get("FunctionError"):
            # The sender crashed or timed out. A timeout can land after Meta accepted the send.
            if "timed out" in str((result or {}).get("errorMessage") or "").lower():
                logger.error(json.dumps({"event": "checkout_send_unconfirmed",
                                         "error": "SenderTimedOut"}))
                return SEND_UNCONFIRMED
            return SEND_FAILED
        # TIGHTENED to add the lower bound; this is a change, not a preservation. The old form
        # was `< 300` with no floor, so a `statusCode` of 0, 100 or 204 read as success. Nothing
        # emits a sub-200 status today, so the 502 `SEND_FAILED` contract is unchanged in practice.
        return SEND_SENT if 200 <= int(result.get("statusCode") or 500) < 300 else SEND_FAILED
    except (ReadTimeoutError, ConnectionClosedError) as error:
        # The request reached the sender and no answer came back: it may have been delivered.
        logger.error(json.dumps({"event": "checkout_send_unconfirmed",
                                 "error": type(error).__name__}))
        return SEND_UNCONFIRMED
    except Exception as error:  # noqa: BLE001
        # The invoke was refused before the sender ran (e.g. `AccessDeniedException`, throttling).
        # The attempt is stored and no order exists, so nothing was sent.
        logger.error(json.dumps({"event": "checkout_send_failed",
                                 "error": type(error).__name__}))
        return SEND_FAILED


def _mark_request_sent(attempt_id: str) -> None:
    """Advance the attempt to PAYMENT_REQUEST_SENT with the monotonic guard. Best-effort.

    Uses the same rank condition the state machine defines, so a late/duplicate write cannot move
    the attempt backwards. A failure here does not undo the send; the webhook reconciliation keys on
    the reference regardless of this marker.
    """
    try:
        # `:rank` is the placeholder `condition_expression()` names. Supplying the rank as `:r`
        # left that condition's value undefined, so DynamoDB rejected every one of these writes
        # (swallowed below) and checkout attempts never recorded PAYMENT_REQUEST_SENT.
        _attempts_table().update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression="SET #s = :s, " + payment_attempt.RANK_ATTRIBUTE
            + " = :rank, updatedAt = :t",
            ConditionExpression=payment_attempt.condition_expression(),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": payment_attempt.PAYMENT_REQUEST_SENT,
                ":rank": payment_attempt.rank(payment_attempt.PAYMENT_REQUEST_SENT),
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
    # The service checkout finalizes natively: purchasedSnapshot -> accept_paid ->
    # ORDER_FINALIZED, which `finalizeNativeCatalogService` above confirms before it closes the
    # NATIVESERVICEACTIVE# session.
    token = str(event.get('catalogToken') or '')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}', token):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
    row = _keys_table().get_item(Key={'orderId': catalog.SESSION_PREFIX + token}, ConsistentRead=True).get('Item') or {}
    if row.get('status') != 'PREPARING_PAYMENT' or int(row.get('expiresAt') or 0) <= int(time.time()):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
    if row.get('paymentAttemptId'):
        return {'outcome': 'CATALOG_SERVICE_ALREADY_PREPARED', 'paymentAttemptId': row['paymentAttemptId']}
    contact = _table(CONTACTS_TABLE).get_item(Key={'id': row.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    try:
        identity, contact = _native_whatsapp_identity(
            str(row.get('contactId') or ''),
            str(row.get('phone') or ''),
            str(row.get('phoneNumberId') or ''),
            str(row.get('sourceMessageId') or ''))
    except (customer_auth.CustomerNotAuthorized, customer_identity.InvalidPhoneNumber):
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
    owner = identity.customer_id
    if owner != row.get('customerId'):
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
    # A2.5 — ONLY WABA1 MAY TAKE A PAYMENT, refused here with a named cause.
    #
    # Switching this leg onto the `isCheckoutTemplate` envelope newly subjects it to the
    # resolver's `PAYMENT_SENDERS` refusal, which raises rather than returning an outcome. The
    # shape this guards against is not one that occurs today — the session's `phoneNumberId` is
    # written from `_get_aws_phone_number_id`, which returns only an AWS-style id — it guards
    # against WABA2, which that resolver can legitimately return and which must never collect.
    #
    # POSITION: two constraints hold here. (1) Before the one-shot `nativePrepareClaim` write
    # below. `nativePrepareClaim` is `attribute_not_exists`-conditional, so a check placed after
    # it would make the customer's retry answer CATALOG_SERVICE_RECONCILIATION_REQUIRED and need
    # a human. (2) Deliberately AFTER the VERIFIED_CUSTOMER_REQUIRED refusal above, so that the
    # specific, customer-actionable refusal wins over this operator/configuration fault when a
    # session is both unverified and sent from a non-permitted number.
    # `tests/test_customer_identity_filter_guard.py` pins that precedence. Only a read-only
    # contacts `get_item` newly precedes this gate; `list_users`, the intent read, the readiness
    # invoke, the claim write and `_create` all still happen strictly after it, so no provider
    # call, write or charge is reachable by a non-permitted sender.
    if str(row.get('phoneNumberId') or '') not in wa_payment_request.PAYMENT_SENDERS:
        logger.error(json.dumps({'event': 'catalog_session_sender_not_permitted',
                                 'sessionToken': token[:8]}))
        return {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}
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
              'options': {'variantId': row['variantId']}}, 'quantity': 1}]
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
    public_uuid = customer_uuid.from_contact(contact)
    if public_uuid:
        row['customerUuid'] = public_uuid
    return _create(identity, {'lineItems': lines, 'serviceIntentId': row['serviceIntentId']},
                   origin, catalog_session=row)



WHATSAPP_IDENTITY_FUNCTION = os.environ.get(
    'WHATSAPP_IDENTITY_FUNCTION', 'wecare-customer-registration:live')


def _native_whatsapp_identity(
    contact_id: str, sender_phone: str, phone_number_id: str, source_message_id: str
):
    """Resolve one signed-inbound WhatsApp contact to the permanent customer identity.

    The dedicated registration function owns customer-pool provisioning. Commerce gets only an
    internal READY/CONFLICT answer, then re-reads ContactsTable and accepts the result only when
    the exact row now carries the returned subject and the same canonical phone. No browser token
    is created and no HTTP route reaches this helper.
    """
    # Meta's signed sender id (`from`, the wa_id) is the full international number with no
    # `+`. It already carries its country code, so `canonical_phone` only restores the marker
    # and infers nothing; the country-preserving check then validates it like a typed `+`
    # number. Handing it the bare wa_id raised MissingCountryCode for every real buyer.
    sender_phone = customer_identity.normalize_phone_preserving_country(
        contact_store.canonical_phone(sender_phone))
    waba_id = wa_payment_request.PHONE_ID_TO_WABA.get(phone_number_id, '')
    if not waba_id:
        raise customer_auth.CustomerNotAuthorized('WhatsApp payment sender is not permitted')
    response = _lambda_client().invoke(
        FunctionName=WHATSAPP_IDENTITY_FUNCTION,
        InvocationType='RequestResponse',
        Payload=json.dumps({
            'internalAction': 'ensureWhatsAppIdentity',
            'contactId': contact_id,
            'senderPhone': sender_phone,
            'sourceMessageId': str(source_message_id or ''),
            'wabaId': waba_id,
        }).encode(),
    )
    raw = response['Payload'].read()
    result = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw or '{}')
    if response.get('FunctionError') or result.get('outcome') != 'WHATSAPP_IDENTITY_READY':
        raise customer_auth.CustomerNotAuthorized('WhatsApp customer identity is not ready')
    subject = str(result.get('customerId') or '')
    if not customer_auth.is_cognito_subject(subject):
        raise customer_auth.CustomerNotAuthorized('WhatsApp customer identity is malformed')
    contact = _table(CONTACTS_TABLE).get_item(
        Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
    try:
        # Same spelling rule as the registration bridge: inbound-created rows predating the
        # canonical `+digits` write still hold the bare wa_id.
        contact_phone = customer_identity.normalize_phone_preserving_country(
            contact_store.canonical_phone(contact.get('phone')))
    except customer_identity.InvalidPhoneNumber:
        raise customer_auth.CustomerNotAuthorized(
            'WhatsApp customer contact has no valid phone') from None
    if (contact_key.resolve(contact) != contact_id
            or str(contact.get('checkoutCustomerId') or '') != subject
            or contact_phone != sender_phone):
        raise customer_auth.CustomerNotAuthorized('WhatsApp customer identity changed')
    identity = customer_auth.CustomerIdentity(
        customer_id=subject, subject=subject, phone=sender_phone, phone_verified=True)
    return identity, contact


def _native_cart(event: Dict[str, Any], origin: str):
    """Prepare a native WhatsApp ORDER_DETAILS payment for a GENERAL PRODUCT CART.

    THE GENERAL-CART TWIN OF `_native_catalog_service`. The inbound WhatsApp handler parsed a
    catalogue `order` message into variants and integer quantities and routed them here; this is
    the one place the general cart reaches the unified checkout machinery. It does NOT price, mint
    a reference or send anything itself: it resolves the verified customer from the contact, turns
    the basket lines into `catalogReference` line items (productId/variantId/quantity ONLY, never
    a client amount), and hands them to `_create` — the SAME `_create` the website prepare path
    uses — so pricing comes from `_native_quote` (ProductsTable, integer paise) and the ONE
    PaymentAttempt + PAYREF# reservation carries contactId + customerUuid.

    The gates mirror the service leg's, in the same order so the same precedence tests hold:
      1. The rollout flag. OFF means no customer, no attempt, no reference, no order.
      2. A WABA1-only sender (`wa_payment_request.PAYMENT_SENDERS`): only WABA1 may collect.
      3. A signed-inbound customer: the exact contact + sender phone are bridged server-side to
         the permanent customer identity. No browser sign-in or browser token is required.
    `_create`'s general-cart arm then refuses anything it cannot price (`_native_quote` raising ->
    no attempt, no order) and anything with no saved checkout profile/address, so an unpriceable
    or unattributable cart leaves nothing behind. Last, it answers DELIVERY_CONFIRMATION_REQUIRED
    until the customer has confirmed the delivery address for this cart (`deliveryConfirmed`,
    set by inbound from their Address Message submission).

    NO float money, no `item_price`, no hand-built `WD-PAY` reference: the amount is whatever
    `_native_quote` computes and the reference is whatever `order_keys.allocate_payment_reference`
    mints inside `_create`.
    """
    from lambda_utils.ecommerce import catalog_service_checkout as catalog
    if os.environ.get('WA_CATALOG_ORDERS_ENABLED', 'false').lower() != 'true':
        return {'outcome': 'NATIVE_CART_ROLLOUT_DISABLED'}

    phone_number_id = str(event.get('phoneNumberId') or '')
    # The Meta webhook names WABA1 by its Graph phone-number ID, while the payment sender
    # allowlist deliberately uses our internal Direct-API sender ID. They are two identifiers
    # for the SAME protected sender. Canonicalize only this one known Meta ID at the checkout
    # trust boundary; WABA2 and every unknown identifier remain refused below.
    if phone_number_id == '1016149501586345':
        phone_number_id = wa_payment_request.PHONE_NUMBER_ID_1
    # A2.5 — ONLY WABA1 MAY TAKE A PAYMENT. Checked before any contacts read, Cognito call,
    # pricing or send, so a non-permitted sender reaches none of them.
    if phone_number_id not in wa_payment_request.PAYMENT_SENDERS:
        logger.error(json.dumps({'event': 'native_cart_sender_not_permitted'}))
        return {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}

    lines_in = event.get('lines')
    if not isinstance(lines_in, list) or not lines_in:
        return {'outcome': 'NATIVE_CART_EMPTY'}
    # Fail closed before the live slot, quote, PaymentAttempt and native message send.
    if short_purchase.enabled() and not short_purchase.one_unit_lines(lines_in):
        return {'outcome': 'NATIVE_CART_SHORT_ONLY'}
    line_items = []
    for line in lines_in:
        if not isinstance(line, dict):
            return {'outcome': 'NATIVE_CART_EMPTY'}
        product_id = str(line.get('productId') or '').strip()
        variant_id = str(line.get('variantId') or '').strip()
        quantity = line.get('quantity')
        if not product_id or not variant_id or type(quantity) is not int or quantity <= 0:
            return {'outcome': 'NATIVE_CART_EMPTY'}
        line_items.append({'catalogReference': {'catalogItemId': product_id,
                                                'options': {'variantId': variant_id}},
                          'quantity': quantity})

    contact_id = str(event.get('contactId') or '')
    sender_phone = str(event.get('senderPhone') or '')
    try:
        identity, contact = _native_whatsapp_identity(
            contact_id, sender_phone, phone_number_id,
            str(event.get('sourceMessageId') or ''))
    except (customer_auth.CustomerNotAuthorized, customer_identity.InvalidPhoneNumber):
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}

    # ONE LIVE PAYMENT REQUEST PER BASKET. The inbound dedupe is per MESSAGE, so the same cart
    # sent again as a new message reached `_create` again and minted a second attempt, a second
    # reference and a second payable ORDER_DETAILS for one purchase. The slot is taken before any
    # reservation and is held for the request's own 15-minute expiry.
    now = int(time.time())
    live_key = _wa_cart_live_key(identity.customer_id, line_items)
    try:
        token = (_claim_wa_cart(live_key, identity.customer_id, now)
                 or _take_over_settled_wa_cart(live_key, identity.customer_id, now))
    except Exception as error:  # noqa: BLE001 - no slot, no request: fail closed, nothing reserved
        logger.error(json.dumps({'event': 'native_cart_live_slot_unavailable',
                                 'error': type(error).__name__}))
        return {'outcome': 'NATIVE_CART_NOT_PREPARED', 'statusCode': 503, 'status': None,
                'error': 'TEMPORARILY_UNAVAILABLE', 'sendUnconfirmed': False,
                'paymentAttemptId': None}
    if not token:
        logger.info(json.dumps({'event': 'native_cart_already_requested'}))
        return {'outcome': 'NATIVE_CART_ALREADY_REQUESTED'}

    # The customer confirmed the delivery address for THIS cart: inbound sets this only when it
    # resumes the cart from their Address Message submission, which it saved to the contact read
    # above. The name typed on that form is who the parcel goes to, so it is the recipient Meta
    # is shown and the order records. It is display data, and it changes no stored row:
    # `delivery_contact` is a copy for this one request.
    create_body: Dict[str, Any] = {'lineItems': line_items}
    delivery_contact = contact
    if event.get('deliveryConfirmed') is True:
        create_body['deliveryConfirmed'] = True
        recipient = ' '.join(str(event.get('deliveryRecipient') or '').split())
        if recipient:
            delivery_contact = {**contact, 'name': recipient[:order_delivery.RECIPIENT_MAX]}

    # The general-cart arm of `_create` (catalog_session=None) owns the rest: it requires a saved
    # checkout profile and address, prices via `_native_quote`, asks for the address to be
    # confirmed for this order (2b), reserves ONE attempt + PAYREF# carrying contactId +
    # customerUuid read from that profile, and sends `_cart_order_details` through
    # `_send_order_details` with the approved template. Anything it cannot price or attribute is
    # refused there with no attempt and no order.
    try:
        response = _create(identity, create_body, origin,
                           native_contact=delivery_contact)
    except Exception:
        _release_wa_cart(live_key, token)
        raise
    status = int(response.get('statusCode') or 0)
    body = {}
    try:
        body = json.loads(response.get('body') or '{}')
    except (TypeError, ValueError):
        body = {}
    # PREPARED means a payment request actually went out. A 200 that sent nothing (initiation
    # disabled) is not a prepared cart, and must not be reported to the customer as one.
    prepared = status == 200 and body.get('status') == 'PAYMENT_REQUEST_SENT'
    unconfirmed = bool(body.get('sendUnconfirmed'))
    if prepared or unconfirmed:
        # Either the request is on the customer's phone or it may be: the slot stays held.
        _record_wa_cart(live_key, token, str(body.get('paymentAttemptId') or ''), now)
    else:
        _release_wa_cart(live_key, token)
    return {'outcome': 'NATIVE_CART_PREPARED' if prepared else 'NATIVE_CART_NOT_PREPARED',
            'statusCode': status, 'status': body.get('status'),
            # The refusal code (`error`) and whether a payment request may already have gone out,
            # so the caller can tell a definite refusal from an unconfirmed send.
            'error': body.get('error'),
            'sendUnconfirmed': unconfirmed,
            'paymentAttemptId': body.get('paymentAttemptId')}


# ── one live WhatsApp payment request per customer and basket ─────────────────────────────────
#
# A CommerceKeys slot per (customer, canonical basket). CommerceKeys carries no TTL and this
# function's role has GetItem/PutItem/UpdateItem on it but no DeleteItem, so a slot is released by
# expiring it (`expiresAt = 0`), never by deleting it, and every write is conditional on the
# claim token so one invocation can never release or overwrite another's live slot.

WA_CART_LIVE_PREFIX = 'WACARTLIVE#'
#: The ORDER_DETAILS expiry `_cart_order_details` stamps (now + 900): the window in which the
#: request the customer already holds can still be paid.
WA_CART_LIVE_SECONDS = 900


def _wa_cart_live_key(customer_id: str, line_items: list) -> str:
    """The slot key: the customer plus the basket, summed per variant and sorted.

    The same canonical form `_native_quote` hashes, so two messages carrying the same items in a
    different order, or split across duplicate lines, are the same basket.
    """
    import hashlib
    merged: Dict[tuple, int] = {}
    for line in line_items:
        ref = line.get('catalogReference') or {}
        key = (str(ref.get('catalogItemId') or ''),
               str((ref.get('options') or {}).get('variantId') or ''))
        merged[key] = merged.get(key, 0) + int(line.get('quantity') or 0)
    canonical = sorted((pid, vid, qty) for (pid, vid), qty in merged.items())
    material = json.dumps([str(customer_id or ''), canonical], separators=(',', ':'))
    return WA_CART_LIVE_PREFIX + hashlib.sha256(material.encode('utf-8')).hexdigest()


def _claim_wa_cart(key: str, customer_id: str, now: int) -> str:
    """Take a free or expired slot. The claim token, or '' when a live request holds it."""
    import secrets
    from botocore.exceptions import ClientError
    token = secrets.token_urlsafe(18)
    try:
        _keys_table().put_item(
            Item={'orderId': key, 'customerId': customer_id, 'token': token,
                  'claimedAt': now, 'expiresAt': now + WA_CART_LIVE_SECONDS},
            ConditionExpression='attribute_not_exists(orderId) OR expiresAt < :now',
            ExpressionAttributeValues={':now': now})
    except ClientError as error:
        if not order_keys.is_conditional_failure(error):
            raise
        return ''
    return token


def _take_over_settled_wa_cart(key: str, customer_id: str, now: int) -> str:
    """Re-take a held slot whose request is no longer payable (paid, failed, expired).

    '' while the held request can still be paid, or while its prepare is still running (no
    attempt recorded yet): that is the case the slot exists for. A slot naming another customer's
    attempt is corrupt and stays held until it expires rather than being trusted either way.
    """
    import secrets
    from botocore.exceptions import ClientError
    row = _keys_table().get_item(Key={'orderId': key}, ConsistentRead=True).get('Item') or {}
    attempt_id = str(row.get('paymentAttemptId') or '')
    if not attempt_id or str(row.get('customerId') or '') != customer_id:
        return ''
    attempt = _attempts_table().get_item(Key={'paymentAttemptId': attempt_id},
                                         ConsistentRead=True).get('Item') or {}
    if not attempt or payment_attempt.is_in_flight(attempt):
        return ''
    token = secrets.token_urlsafe(18)
    try:
        _keys_table().update_item(
            Key={'orderId': key},
            UpdateExpression='SET #t = :new, claimedAt = :now, expiresAt = :exp '
                             'REMOVE paymentAttemptId, recordedAt',
            ConditionExpression='#t = :old',
            ExpressionAttributeNames={'#t': 'token'},
            ExpressionAttributeValues={':new': token, ':now': now,
                                       ':exp': now + WA_CART_LIVE_SECONDS,
                                       ':old': str(row.get('token') or '')})
    except ClientError as error:
        if not order_keys.is_conditional_failure(error):
            raise
        return ''
    return token


def _record_wa_cart(key: str, token: str, attempt_id: str, now: int) -> None:
    """Name the attempt holding the slot. Best-effort: the slot is already held either way."""
    try:
        _keys_table().update_item(
            Key={'orderId': key},
            UpdateExpression='SET paymentAttemptId = :a, recordedAt = :now',
            ConditionExpression='#t = :t',
            ExpressionAttributeNames={'#t': 'token'},
            ExpressionAttributeValues={':a': attempt_id, ':now': now, ':t': token})
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'native_cart_live_slot_record_failed',
                                   'error': type(error).__name__}))


def _release_wa_cart(key: str, token: str) -> None:
    """Free the slot after a definite refusal, so the customer's retry is not refused as live."""
    try:
        _keys_table().update_item(
            Key={'orderId': key},
            UpdateExpression='SET expiresAt = :zero',
            ConditionExpression='#t = :t',
            ExpressionAttributeNames={'#t': 'token'},
            ExpressionAttributeValues={':zero': 0, ':t': token})
    except Exception as error:  # noqa: BLE001
        # A held slot expires on its own within WA_CART_LIVE_SECONDS; nothing is lost.
        logger.warning(json.dumps({'event': 'native_cart_live_slot_release_failed',
                                   'error': type(error).__name__}))
