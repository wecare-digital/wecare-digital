"""WECARE.DIGITAL services: five fixed-price product lines on the ONE checkout.

What this is, and why it mirrors `blog_contribution`
----------------------------------------------------
A WECARE.DIGITAL service is bought exactly the way a contribution is: ONE fixed-price VARIANT of
ONE ProductsTable product (`Request`), added to the existing cart at quantity 1 and paid on the
ONE live checkout path -- `POST /ecommerce/prepare-checkout` -> the AWS-native ProductsTable
quote (`native_checkout.quote_native_cart`) -> Razorpay -> verify-callback / razorpay-webhook
reconciliation, which creates ONE order. There is no second payment implementation for a
service, and this module has no gateway client, no table and no I/O of any kind.

It is the SERVER half of the allow-list. The browser half is `src/config/services.ts`, declared
separately on purpose so the browser cannot widen the trusted set;
`tests/test_service_requests.py` fails if the two drift.

WHAT IS OFFERED, AND WHAT IS REFUSED
------------------------------------
FIVE services, all five variants of the one services product: Submit Request, Request Amendment,
Drop Docs, Vault and Request Pickup. Drop Docs and Vault were refused by name in O-1
(``SERVICE_NOT_OFFERED``) because nothing could deliver them; O-2 added them to the allow-list
instead, which was the whole of that change -- no second payment path and no new ownership
machinery. Request Pickup joined on 2026-10-10 as the fifth variant.

**No price appears in this module.** See "PRODUCTSTABLE IS THE PRICE AUTHORITY" below.

``NOT_OFFERED_VARIANT_IDS`` and ``NOT_OFFERED_KINDS`` are EMPTY, and the refusal code, its
message and the not-offered branch in ``service_line`` all deliberately remain. They are the guard
for the NEXT variant somebody adds to the catalogue: naming it here refuses it by name rather than
letting it through as an ordinary product line, which would charge for a service nothing can
deliver.

Three services require a target Submit Request before payment (``TARGET_REQUIRED_KINDS``):
Request Amendment, Vault and Request Pickup. Drop Docs is intentionally different: F003 is a
paid upload entitlement, and the customer chooses an owned order/request inside the Flow after
payment. The Flow endpoint re-verifies ownership and binds that target when the paid upload
completes, so one paid order authorizes one completed Drop Docs submission without asking the
customer to select the target twice.

PRODUCTSTABLE IS THE PRICE AUTHORITY
------------------------------------
The owner's requirement (2026-10-08) is that a service price be changeable with no deploy, so no
committed price constant lives here. Each service variant is priced by its `priceMinor` in
ProductsTable. `native_checkout` freezes that figure into the quote snapshot, and
``native_service_line_paise`` reads the one service line back out of the FROZEN quote -- never a
client amount -- before any gateway order can exist.

What bounds the figure. A catalogue typo is the only thing between an edit and a charge, so
exactly one rail remains: ``SERVICE_LINE_MIN_PAISE``/``SERVICE_LINE_MAX_PAISE``. That is **not a
price lock** -- 49 -> 149 -> 999 all pass untouched, which is the point -- it refuses only a
figure of the Rs.99,999 shape, where the likeliest explanation is a mistyped catalogue field
rather than a pricing decision.

The STRUCTURAL checks are what keep this safe: exactly one service line, an allow-listed variant
of the one services product, quantity exactly 1, and exactly one matching line in the frozen
quote carrying an integer unit price inside the rail.

`service_pricing_native` reads the SAME ProductsTable `priceMinor` for the public service pages
(`GET /ecommerce/service-prices`), so the price a page promises and the price the checkout
charges come from one source and cannot drift.

VAULT AND DROP DOCS USE THE COLLECT BREAKDOWN
---------------------------------------------
The native quote always prices the service line from ProductsTable. Vault and Drop Docs use the
same customer-visible breakdown vocabulary as Collect: GST-inclusive item subtotal, automatic
Delight, Express, Convenience Fee, GST on the Convenience Fee, then Amount Payable. Delight remains
the ONE server-owned default calculation (0.5% of the eligible GST-inclusive item subtotal, capped
at Rs.50); Express is the fixed Rs.25 service-delivery charge declared below. The standard checkout
calculator then applies the 2.5% Convenience Fee and 18% GST on that fee. Website, WhatsApp Review
& Pay, Workspace orders and invoices therefore read one frozen quote and reconcile exactly.

Integer paise throughout. No float pricing is introduced here.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from lambda_utils.ecommerce import cart_contract

logger = logging.getLogger(__name__)

#: The only currency services are taken in. Compared explicitly, never inferred.
SERVICE_CURRENCY = "INR"

#: The ProductsTable product that carries every service variant, lowercased. A catalogue key, not
#: a secret (`Request`, renamed from `WECARE.DIGITAL Services` on 2026-10-10, PHYSICAL, five
#: variants).
SERVICE_PRODUCT_IDS: FrozenSet[str] = frozenset({
    "f829697a-b1db-5c4e-bfce-51d1487278a7",
    "7133c98d-de8d-5e56-94ff-8d9fea7aa331",
    "e1ca7833-5d7d-567b-837c-face04647598",
    "d4cfc6e8-10b3-5c47-94c8-3c69f4c03907",
    "166370fe-69a8-5ad2-9f9a-e9ce3f92839c",
})

#: Request kinds. A REQUEST lifecycle vocabulary, unrelated to payment status.
SUBMIT_REQUEST = "SUBMIT_REQUEST"
REQUEST_AMENDMENT = "REQUEST_AMENDMENT"
DROP_DOCS = "DROP_DOCS"
VAULT = "VAULT"
REQUEST_PICKUP = "REQUEST_PICKUP"

#: THE ONLY FIVE SERVICES THAT CAN BE BOUGHT, as ``{variant id: kind}``. NO PRICE: the mapping is
#: stable catalogue identity; the price is ProductsTable's and is read from the frozen quote at
#: checkout. Mirrored in src/config/services.ts as SERVICE_CHOICES.
SERVICE_KIND_BY_VARIANT: Mapping[str, str] = MappingProxyType({
    "RSR7M2P9": SUBMIT_REQUEST,
    "RAM5Q8K4": REQUEST_AMENDMENT,
    "RDD9P3M7": DROP_DOCS,
    "RVT6K4Q8": VAULT,
    "SHP7Q4N9": REQUEST_PICKUP,
})

SERVICE_PRODUCT_BY_VARIANT: Mapping[str, str] = MappingProxyType({
    "RSR7M2P9": "f829697a-b1db-5c4e-bfce-51d1487278a7",
    "RAM5Q8K4": "7133c98d-de8d-5e56-94ff-8d9fea7aa331",
    "RDD9P3M7": "e1ca7833-5d7d-567b-837c-face04647598",
    "RVT6K4Q8": "d4cfc6e8-10b3-5c47-94c8-3c69f4c03907",
    "SHP7Q4N9": "166370fe-69a8-5ad2-9f9a-e9ce3f92839c",
})

#: Folded spelling -> the catalogue's own spelling. The SKUs above are upper-case, but the
#: retired UUID identities were compared lower-cased, and #733 kept that `.lower()` when it
#: switched to SKUs: every service line then missed this map and checkout refused all five
#: services with SERVICE_UNKNOWN_CHOICE. Every lookup goes through `canonical_variant_id` so the
#: comparison cannot depend on how a browser, a Meta cart or a stored row spelled the id.
_CANONICAL_VARIANT_BY_FOLDED: Mapping[str, str] = MappingProxyType(
    {variant.casefold(): variant for variant in SERVICE_KIND_BY_VARIANT})


def canonical_variant_id(value: Any) -> str:
    """The catalogue spelling of a service variant id, or ``''`` when it names no service."""
    return _CANONICAL_VARIANT_BY_FOLDED.get(str(value or "").strip().casefold(), "")


#: No legacy catalog identity is recognized. Fresh SKU-first service identities will be wired
#: when the new catalog is created.
SERVICE_PURCHASES_ENABLED = True

#: THE CATASTROPHE RAIL, and the only bound on a service line now that ProductsTable owns the
#: price.
#:
#: Deliberately wide. A rail narrow enough to be a price check would reintroduce the deploy the
#: owner removed -- an ordinary edit from Rs.49 to Rs.999 must pass with nobody's involvement.
#: Rs.50,000 is far above any plausible service price and far below the Rs.99,999-shaped figure a
#: mistyped catalogue field produces, which is the single failure this is here to refuse. The
#: minimum is 1 paise, not 0: a free service line would charge a convenience fee on nothing.
#:
#: Owner-visible limit: a service genuinely priced above Rs.50,000 in ProductsTable will be
#: refused with ``SERVICE_PRICE_CHANGED`` until this figure is raised, and that requires a deploy.
SERVICE_LINE_MIN_PAISE = 1
SERVICE_LINE_MAX_PAISE = 5_000_000

#: Customer-facing "Express" row for Vault and Drop Docs. This is a service delivery/handling
#: charge, not physical courier postage, and is included in the frozen supply quote before payment.
#: Rs.25 = 2,500 paise. It does NOT increase Delight's basis.
VAULT_DROP_DOCS_EXPRESS_PAISE = 2_500

#: The five PUBLIC PAGE SLUGS, ``{slug: kind}``. One owner for the slug vocabulary, shared by the
#: public price endpoint (`service_pricing_native.resolve_all`) and mirrored in
#: src/config/services.ts as each choice's ``slug``. A slug is a URL path segment, never a
#: catalogue identifier.
SERVICE_KIND_BY_SLUG: Mapping[str, str] = MappingProxyType({
    "submit-request": SUBMIT_REQUEST,
    "request-amendment": REQUEST_AMENDMENT,
    "drop-docs": DROP_DOCS,
    "vault": VAULT,
    "request-pickup": REQUEST_PICKUP,
})

#: The services that cannot exist without a target Submit Request of the CALLER'S OWN. One
#: frozenset rather than a ``kind ==`` comparison per service, so adding another target-taking
#: service cannot reach only some of the places that have to agree.
TARGET_REQUIRED_KINDS: FrozenSet[str] = frozenset({
    REQUEST_AMENDMENT, VAULT, REQUEST_PICKUP})

#: Variants of the same product that are deliberately NOT offered. EMPTY: all five are offered.
#: Kept, with its refusal code and its branch in ``service_line``, as the guard for the next
#: catalogue variant somebody adds -- refusing by name beats charging for something nothing can
#: deliver. Mirrored in src/config/services.ts as NOT_OFFERED_SERVICE_VARIANT_IDS.
NOT_OFFERED_VARIANT_IDS: FrozenSet[str] = frozenset()

#: The kind names of the not-offered services, so `request-intent` refuses them by name too.
#: EMPTY for the same reason, and kept for the same reason.
NOT_OFFERED_KINDS: FrozenSet[str] = frozenset()

#: ``{kind: variant id}`` for the five offered services. Derived, so the two cannot drift.
SERVICE_VARIANT_BY_KIND: Mapping[str, str] = MappingProxyType(
    {kind: variant for variant, kind in SERVICE_KIND_BY_VARIANT.items()})

#: ``{kind: public page slug}``, derived from ``SERVICE_KIND_BY_SLUG`` for the same reason.
SERVICE_SLUG_BY_KIND: Mapping[str, str] = MappingProxyType(
    {kind: slug for slug, kind in SERVICE_KIND_BY_SLUG.items()})

#: A pre-payment intent id: a canonical lowercase UUIDv7 (`identifiers.new_uuid7`).
INTENT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

#: The public, copyable request id: ``WD-REQ-`` + 8 symbols of the order-number alphabet (no
#: 0/1/I/L/O/U, so it survives being read aloud). Mirrors ``order_keys``' ``WD-ORD-`` shape.
PUBLIC_REQUEST_ID_PREFIX = "WD-REQ-"
PUBLIC_REQUEST_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_REQUEST_ID_ENTROPY = 8
PUBLIC_REQUEST_ID_RE = re.compile(
    r"^WD-REQ-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{8}$")

#: Refusal codes. One sentence each, every one ending "Nothing has been charged." because every
#: one is raised before a gateway order can exist. Mirrored in src/lib/serviceRequests.ts.
SERVICE_NOT_OFFERED = "SERVICE_NOT_OFFERED"
SERVICE_UNKNOWN_CHOICE = "SERVICE_UNKNOWN_CHOICE"
SERVICE_INVALID_QUANTITY = "SERVICE_INVALID_QUANTITY"
SERVICE_ONE_PER_ORDER = "SERVICE_ONE_PER_ORDER"
SERVICE_SEPARATE_CHECKOUT = "SERVICE_SEPARATE_CHECKOUT"
SERVICE_INTENT_REQUIRED = "SERVICE_INTENT_REQUIRED"
SERVICE_ORIGINAL_ORDER_REQUIRED = "SERVICE_ORIGINAL_ORDER_REQUIRED"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
SERVICE_WEBSITE_ONLY = "SERVICE_WEBSITE_ONLY"
SERVICE_PRICE_CHANGED = "SERVICE_PRICE_CHANGED"
SERVICE_NOT_PAYABLE = "SERVICE_NOT_PAYABLE"
#: Vault is sold per FILE. A Vault intent with no file could be paid for and never unlock
#: anything, because `vault_access.grant_access` needs the file the payment is for.
VAULT_FILE_REQUIRED = "VAULT_FILE_REQUIRED"
#: The file is paid and its access window is open (or a paid window is still unused), so a new
#: ₹49 would charge for access the customer already has.
VAULT_ACCESS_ACTIVE = "VAULT_ACCESS_ACTIVE"

SERVICE_MESSAGES: Mapping[str, str] = MappingProxyType({
    VAULT_FILE_REQUIRED: "Choose the Vault document you want to unlock. Nothing has been charged.",
    VAULT_ACCESS_ACTIVE: "This document is already paid and ready to download. "
                         "Nothing has been charged.",
    SERVICE_NOT_OFFERED: "This service is not offered yet. Nothing has been charged.",
    SERVICE_UNKNOWN_CHOICE: "Choose a WECARE.DIGITAL service. Nothing has been charged.",
    SERVICE_INVALID_QUANTITY: "A service is bought one at a time. Set its quantity to 1. "
                              "Nothing has been charged.",
    SERVICE_ONE_PER_ORDER: "Only one service can be paid for in an order. Remove the extra one. "
                           "Nothing has been charged.",
    SERVICE_SEPARATE_CHECKOUT: "Vault and Drop Docs need a separate cart checkout. "
                               "Remove other cart items or buy them first. Nothing has been charged.",
    SERVICE_INTENT_REQUIRED: "Start this service from its own page, then check out. "
                             "Nothing has been charged.",
    SERVICE_ORIGINAL_ORDER_REQUIRED: "Choose the original order this request is for. "
                                     "Nothing has been charged.",
    SERVICE_UNAVAILABLE: "Services cannot be paid for right now. Nothing has been charged.",
    SERVICE_WEBSITE_ONLY: "Services can only be paid for on the website. Nothing has been charged.",
    SERVICE_PRICE_CHANGED: "The price of this service has changed. Nothing has been charged.",
    SERVICE_NOT_PAYABLE: "This service cannot be paid for right now. Nothing has been charged.",
})


class ServiceRejected(ValueError):
    """A pure pre-check refused a services basket. Carries a stable ``code``, never a body string.

    ``ValueError`` for the same load-bearing reason as ``ContributionRejected``: anything that
    escapes into ``_create``'s trailing ``except ValueError`` answers 409, not 500.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ServicePriceChanged(cart_contract.CartContractError):
    """The frozen native quote does not carry one valid, in-rail price for the service line."""


class ServiceNotPayable(cart_contract.CartContractError):
    """A services basket that cannot be priced for payment.

    The checkout handler maps it to 409 ``SERVICE_NOT_PAYABLE``. Nothing on the native pricing
    path raises it today.
    """


@dataclass(frozen=True)
class ServiceLine:
    """The one service line in a basket: which kind, which variant, and what it was priced at.

    ``paise`` is ``None`` from ``service_line``, because a basket is read BEFORE the native quote
    prices it and this module holds no figure to assume. The authoritative figure comes from the
    frozen quote via ``native_service_line_paise``, and ``payref_extra`` records it. ``None``
    therefore means "not priced yet", which is a different fact from "free", and keeping the two
    distinguishable is what stops an unpriced line being recorded as a zero charge.
    """

    kind: str
    variant_id: str
    paise: Optional[int] = None


def refusal(code: str) -> Dict[str, str]:
    """The wire payload for a refusal code: the code and its one honest sentence."""
    return {"error": code, "message": SERVICE_MESSAGES[code]}


def is_service_product(product_id: Any) -> bool:
    """Takes the ID, not the line -- the same reason as ``checkout/handler.py:_is_contribution_id``.

    A request line carries the product as ``catalogReference.catalogItemId`` while a frozen
    native quote item carries it as ``productId``, so a helper that took the line would silently
    answer False for one of them.
    """
    return str(product_id or "").strip().lower() in SERVICE_PRODUCT_IDS


def service_line(line_items: Any) -> Optional[ServiceLine]:
    """The basket's one service line, ``None`` when it holds none, or raise ``ServiceRejected``.

    PURE, and tolerant of a malformed ``line_items`` exactly like ``_contribution_request``:
    anything whose shape cannot be read is simply not recognised as a service and falls through
    to the checkout's native quote (``checkout/handler.py:_native_quote``), which owns the strict
    shape refusals.

    The not-offered check runs BEFORE the allow-list so that a named-but-unavailable variant is
    refused by name (``SERVICE_NOT_OFFERED``) rather than as an unknown choice.
    ``NOT_OFFERED_VARIANT_IDS`` is currently empty -- all five services are offered -- so this
    branch is the guard for the next variant added to the catalogue, not dead code.
    """
    if not isinstance(line_items, list):
        return None
    found = []
    for line in line_items:
        if not isinstance(line, dict):
            continue
        reference = line.get("catalogReference")
        if not isinstance(reference, dict):
            continue
        if not is_service_product(reference.get("catalogItemId")):
            continue
        options = reference.get("options")
        raw_variant = (str(options.get("variantId") or "").strip()
                       if isinstance(options, dict) else "")
        if raw_variant.casefold() in {v.casefold() for v in NOT_OFFERED_VARIANT_IDS}:
            logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_NOT_OFFERED}))
            raise ServiceRejected(SERVICE_NOT_OFFERED)
        # The catalogue spelling, so the PAYREF serviceLine and `store.activate` agree with
        # SERVICE_KIND_BY_VARIANT byte for byte.
        variant_id = canonical_variant_id(raw_variant)
        if (not variant_id
                or SERVICE_PRODUCT_BY_VARIANT.get(variant_id) !=
                str(reference.get("catalogItemId") or "").strip().lower()):
            logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_UNKNOWN_CHOICE}))
            raise ServiceRejected(SERVICE_UNKNOWN_CHOICE)
        quantity = line.get("quantity")
        # `type(...) is not int`, because `isinstance(True, int)` is True.
        if type(quantity) is not int or quantity != 1:
            logger.info(json.dumps({"event": "service_refused",
                                    "reason": SERVICE_INVALID_QUANTITY}))
            raise ServiceRejected(SERVICE_INVALID_QUANTITY)
        # No price: the native quote prices the line, and nothing here may presume what that
        # will be.
        found.append(ServiceLine(kind=SERVICE_KIND_BY_VARIANT[variant_id],
                                 variant_id=variant_id, paise=None))
    if not found:
        return None
    if len(found) != 1:
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_ONE_PER_ORDER,
                                "serviceLines": len(found)}))
        raise ServiceRejected(SERVICE_ONE_PER_ORDER)
    return found[0]


def has_service_line(line_items: Any) -> bool:
    """Whether the basket names the services product at all. NEVER raises.

    Deliberately keyed on the PRODUCT, not on a valid choice: a basket holding a refused variant
    is still a services basket for the purposes of every guard that asks this question.
    """
    if not isinstance(line_items, list):
        return False
    for line in line_items:
        if not isinstance(line, dict):
            continue
        reference = line.get("catalogReference")
        if isinstance(reference, dict) and is_service_product(reference.get("catalogItemId")):
            return True
    return False


def _intent_id(body: Any) -> str:
    value = body.get("serviceIntentId") if isinstance(body, dict) else None
    if not isinstance(value, str) or not INTENT_ID_RE.match(value):
        return ""
    return value


def _single_order_context(context: Any, line: Optional[ServiceLine] = None) -> Optional[Dict[str, str]]:
    """Validated server-only single-order binding, or None.

    This object is NEVER read from the HTTP body. The authenticated request-service-start handler
    constructs it only after resolving the selected public Order Number through CommerceKeys and
    re-reading the owned OrderTable row. Keeping it as a separate argument makes a browser field
    with the same spelling inert rather than an authorization bypass.
    """
    if not isinstance(context, Mapping) or context.get("singleOrder") is not True:
        return None
    service_code = str(context.get("serviceCode") or "").strip().upper()
    selected_order_id = str(context.get("selectedOrderId") or "").strip()
    selected_order_number = str(context.get("selectedOrderNumber") or "").strip().upper()
    sku = canonical_variant_id(context.get("sku"))
    flow_capability = str(context.get("flowCapability") or "").strip()
    if (not service_code or not selected_order_id or not selected_order_number
            or not sku or not flow_capability):
        return None
    if SERVICE_KIND_BY_VARIANT.get(sku) != service_code:
        return None
    if line is not None and (line.kind != service_code or line.variant_id != sku):
        return None
    return {
        "serviceCode": service_code,
        "selectedOrderId": selected_order_id,
        "selectedOrderNumber": selected_order_number,
        "sku": sku,
        "flowCapability": flow_capability,
    }


def checkout_preflight(line_items: Any, body: Any, *,
                       verified_service_context: Any = None
                       ) -> Optional[Tuple[int, Dict[str, str]]]:
    """``None`` to proceed, or ``(status, payload)`` to refuse. PURE.

    Legacy callers still prove a service purchase with ``serviceIntentId``. The new public
    request-service-start route proves the stronger contract first — authenticated owner +
    existing Order Number — and passes that proof as ``verified_service_context``, a Python
    argument that is never populated from request JSON.
    """
    try:
        line = service_line(line_items)
    except ServiceRejected as rejected:
        return 409, refusal(rejected.code)
    if line is None:
        return None
    # The explicit supply-GST / Express calculation for Vault and Drop Docs
    # currently applies to the whole basket. Refuse extra items BEFORE any
    # order is created so a digital-file renewal cannot reprice merchandise.
    if line.kind in (VAULT, DROP_DOCS) and len(line_items) != 1:
        logger.info(json.dumps({"event": "service_refused",
                                "reason": SERVICE_SEPARATE_CHECKOUT}))
        return 409, refusal(SERVICE_SEPARATE_CHECKOUT)
    # The published Pickup Flow still carries a cloned Submit Request completion schema.
    # Refuse every new checkout rail BEFORE any payment is created. The website's
    # service selector is not a security boundary; this pure guard is shared by all rails.
    if line.kind == REQUEST_PICKUP:
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_NOT_PAYABLE,
                                "serviceCode": REQUEST_PICKUP}))
        return 409, refusal(SERVICE_NOT_PAYABLE)
    if not SERVICE_PURCHASES_ENABLED:
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_UNAVAILABLE,
                                "catalog": "retired"}))
        return 409, refusal(SERVICE_UNAVAILABLE)
    if _single_order_context(verified_service_context, line) is not None:
        return None
    if not _intent_id(body):
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_INTENT_REQUIRED}))
        return 409, refusal(SERVICE_INTENT_REQUIRED)
    return None


def native_service_line_paise(snapshot: Any, line_items: Any) -> Optional[int]:
    """Resolve one service's charged unit price from the frozen AWS-native quote.

    Source of truth is *snapshot.frozen_data['items']*, already priced from the
    ProductsTable by native_checkout. Never use client-supplied amounts, and
    never permit a missing price to become a PAID_SERVICE_UNMATCHED ledger row.

    Called before creating a Razorpay order so mismatch failures stay pre-payment.
    Returns None only when the basket has no service line.
    """
    line = service_line(line_items)
    if line is None:
        return None
    frozen = getattr(snapshot, "frozen_data", None)
    if not isinstance(frozen, Mapping):
        raise ServicePriceChanged("native service quote has no frozen line items")
    items = frozen.get("items")
    if not isinstance(items, (list, tuple)):
        raise ServicePriceChanged("native service quote has no line items")
    matches = [
        item for item in items
        if isinstance(item, Mapping)
        and str(item.get("productId") or "").strip().lower()
            == SERVICE_PRODUCT_BY_VARIANT.get(line.variant_id)
        and canonical_variant_id(item.get("variantId")) == line.variant_id
    ]
    if len(matches) != 1:
        raise ServicePriceChanged("native service quote does not identify one priced line")
    item = matches[0]
    unit = item.get("unitPricePaise")
    if (type(unit) is not int
            or type(item.get("quantity")) is not int
            or item["quantity"] != 1
            or not SERVICE_LINE_MIN_PAISE <= unit <= SERVICE_LINE_MAX_PAISE):
        raise ServicePriceChanged("native service line lacks a valid authoritative price")
    return unit


def payref_extra(line_items: Any, body: Any, *,
                 line_paise: Optional[int],
                 verified_service_context: Any = None) -> Dict[str, Any]:
    """Server-owned service join stored beside one immutable payment reference.

    Legacy intent purchases keep their ``intentId``. A single-order purchase instead records
    the already-verified existing order identity and Flow capability. It never records or mints a
    customer-facing request id.
    """
    line = service_line(line_items)
    if line is None:
        return {}
    single = _single_order_context(verified_service_context, line)
    if single is not None:
        return {"serviceLine": {
            "kind": line.kind,
            "variantId": line.variant_id,
            "paise": line_paise,
            "singleOrder": True,
            **single,
        }}
    return {"serviceLine": {"kind": line.kind, "variantId": line.variant_id,
                            "paise": line_paise, "intentId": _intent_id(body)}}


def intent_rebound(payref: Optional[Mapping[str, Any]], body: Any) -> bool:
    """True when a reserved attempt's ``PAYREF#`` row is bound to a DIFFERENT intent than ``body``.

    The intent id is not part of either request-key fingerprint, and ``payref_extra`` is written
    only when a FRESH attempt mints its reference. So a resumed request key keeps the intent its
    first prepare bound -- and after a customer switches an amendment's target (intent A
    superseded by B, identical cart lines), paying the resumed attempt would activate A and amend
    the request they moved away from. The caller refuses such a resume with ``INTENT_CHANGED``.

    PURE. Fails closed: a missing row or a row with no ``serviceLine`` is a rebind, never a match.
    """
    line = payref.get("serviceLine") if isinstance(payref, Mapping) else None
    bound = str(line.get("intentId") or "") if isinstance(line, Mapping) else ""
    presented = _intent_id(body)
    return not bound or not presented or bound != presented


__all__ = [
    "DROP_DOCS", "INTENT_ID_RE", "NOT_OFFERED_KINDS", "NOT_OFFERED_VARIANT_IDS",
    "PUBLIC_REQUEST_ID_RE", "REQUEST_AMENDMENT", "REQUEST_PICKUP", "SERVICE_CURRENCY",
    "SERVICE_KIND_BY_SLUG", "SERVICE_KIND_BY_VARIANT",
    "SERVICE_LINE_MAX_PAISE", "SERVICE_LINE_MIN_PAISE", "VAULT_DROP_DOCS_EXPRESS_PAISE",
    "SERVICE_MESSAGES", "SERVICE_PRODUCT_IDS", "SERVICE_SLUG_BY_KIND", "SERVICE_VARIANT_BY_KIND",
    "SUBMIT_REQUEST", "TARGET_REQUIRED_KINDS", "VAULT", "VAULT_ACCESS_ACTIVE",
    "VAULT_FILE_REQUIRED", "ServiceLine",
    "ServiceNotPayable", "ServicePriceChanged", "ServiceRejected",
    "canonical_variant_id", "checkout_preflight", "has_service_line", "intent_rebound",
    "_single_order_context",
    "is_service_product", "native_service_line_paise", "payref_extra", "refusal",
    "service_line",
]
