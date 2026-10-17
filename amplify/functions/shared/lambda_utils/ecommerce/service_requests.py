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

Four of the five REQUIRE a target Submit Request (``TARGET_REQUIRED_KINDS``): an amendment amends
one, Drop Docs sends documents for "a request already under way", Vault asks for "a copy of a
document held against one of your requests", and Request Pickup collects documents for one. A
target-free Drop Docs would let a customer pay Rs.350 to attach documents to nothing, and a
target-free pickup would send a courier to collect paperwork for no request. The target is
resolved and owned-checked in ``service_request_store`` BEFORE money moves.

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

PRICING IS ORDINARY ORDER PRICING
---------------------------------
Unlike a contribution, a service is NOT fee-exempt: the native quote prices the line and
`checkout_pricing.compute_quote` adds the 2.5% convenience fee and 18% GST on that fee, exactly
as for any single order. That is why every page says "a convenience fee is added at checkout"
beside its amount.

Integer paise throughout. No float, no division, no rounding happens in this module.
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
    REQUEST_AMENDMENT, DROP_DOCS, VAULT, REQUEST_PICKUP})

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
SERVICE_INTENT_REQUIRED = "SERVICE_INTENT_REQUIRED"
SERVICE_ORIGINAL_ORDER_REQUIRED = "SERVICE_ORIGINAL_ORDER_REQUIRED"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
SERVICE_WEBSITE_ONLY = "SERVICE_WEBSITE_ONLY"
SERVICE_PRICE_CHANGED = "SERVICE_PRICE_CHANGED"
SERVICE_NOT_PAYABLE = "SERVICE_NOT_PAYABLE"

SERVICE_MESSAGES: Mapping[str, str] = MappingProxyType({
    SERVICE_NOT_OFFERED: "This service is not offered yet. Nothing has been charged.",
    SERVICE_UNKNOWN_CHOICE: "Choose a WECARE.DIGITAL service. Nothing has been charged.",
    SERVICE_INVALID_QUANTITY: "A service is bought one at a time. Set its quantity to 1. "
                              "Nothing has been charged.",
    SERVICE_ONE_PER_ORDER: "Only one service can be paid for in an order. Remove the extra one. "
                           "Nothing has been charged.",
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
        variant_id = (str(options.get("variantId") or "").strip().lower()
                      if isinstance(options, dict) else "")
        if variant_id in NOT_OFFERED_VARIANT_IDS:
            logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_NOT_OFFERED}))
            raise ServiceRejected(SERVICE_NOT_OFFERED)
        if (variant_id not in SERVICE_KIND_BY_VARIANT
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


def checkout_preflight(line_items: Any, body: Any) -> Optional[Tuple[int, Dict[str, str]]]:
    """``None`` to proceed, or ``(status, payload)`` to refuse. PURE: before profile, pricing or
    DynamoDB.

    * a non-service basket -> ``None`` (byte-identical behaviour for every other order);
    * a refused service line -> 409 with its code;
    * no well-formed ``serviceIntentId`` -> 409 ``SERVICE_INTENT_REQUIRED``: a paid service with
      no intent would be a paid service with no request.

    The price itself is checked after the native quote exists, by ``native_service_line_paise``.
    """
    try:
        line = service_line(line_items)
    except ServiceRejected as rejected:
        return 409, refusal(rejected.code)
    if line is None:
        return None
    if not SERVICE_PURCHASES_ENABLED:
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_UNAVAILABLE,
                                "catalog": "retired"}))
        return 409, refusal(SERVICE_UNAVAILABLE)
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
        and str(item.get("variantId") or "").strip() == line.variant_id
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
                 line_paise: Optional[int]) -> Dict[str, Any]:
    """``{}`` for a non-service basket, else ``{"serviceLine": {kind, variantId, paise, intentId}}``.

    This is the join (plan D3): checkout writes it onto the ``PAYREF#`` reservation it already
    makes, and the service-requests Lambda reads it back after the order exists. Checkout gains
    no table and no IAM change. Called only after ``checkout_preflight`` passed.

    ``line_paise`` is the line's price as frozen in the native quote, as returned by
    ``native_service_line_paise``. That is the figure the customer is charged for the thing being
    bought, so it is the only one that can honestly be recorded as what they paid for. ``None``
    records ``None``, so an unpriced row is visibly unpriced rather than silently zero, and
    ``service_request_store.activate`` refuses it.

    REQUIRED KEYWORD, WITH NO DEFAULT, and the missing default is the point. Omitting it used to
    be silent and wrote ``paise: None``, which ``activate`` refuses as ``AMOUNT_MISMATCH`` ->
    ``PAID_SERVICE_UNMATCHED`` -- *after* the customer's money has moved. A ``TypeError`` at
    import and test time is the cheapest possible version of that same mistake. Pass ``None``
    explicitly when there is genuinely no quote to read a figure from.
    """
    line = service_line(line_items)
    if line is None:
        return {}
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
    "SERVICE_LINE_MAX_PAISE", "SERVICE_LINE_MIN_PAISE",
    "SERVICE_MESSAGES", "SERVICE_PRODUCT_IDS", "SERVICE_SLUG_BY_KIND", "SERVICE_VARIANT_BY_KIND",
    "SUBMIT_REQUEST", "TARGET_REQUIRED_KINDS", "VAULT", "ServiceLine",
    "ServiceNotPayable", "ServicePriceChanged", "ServiceRejected",
    "checkout_preflight", "has_service_line", "intent_rebound", "is_service_product",
    "native_service_line_paise", "payref_extra", "refusal",
    "service_line",
]
