"""WECARE.DIGITAL services: four fixed-price product lines on the ONE checkout.

What this is, and why it mirrors `blog_contribution`
----------------------------------------------------
A WECARE.DIGITAL service is bought exactly the way a contribution is: ONE fixed-price VARIANT of
ONE Wix product (`WECARE.DIGITAL Services`, PHYSICAL in Wix), added to the existing cart at
quantity 1 and paid on the ONE live checkout path -- `POST /ecommerce/prepare-checkout` ->
`cart_v2.calculate` -> Razorpay -> verify-callback / razorpay-webhook reconciliation, which
creates ONE order. There is no second payment implementation for a service, and this module has
no gateway client, no table and no I/O of any kind.

It is the SERVER half of the allow-list. The browser half is `src/config/services.ts`, declared
separately on purpose so the browser cannot widen the trusted set;
`tests/test_service_requests.py` fails if the two drift.

WHAT IS OFFERED, AND WHAT IS REFUSED
------------------------------------
FOUR services, all four variants of the one Wix product: Submit Request, Request Amendment,
Drop Docs and Vault. Drop Docs and Vault were refused by name in O-1 (``SERVICE_NOT_OFFERED``)
because nothing could deliver them; O-2 added them to the allow-list instead, which was the
whole of that change -- no second payment path and no new ownership machinery.

**No price appears in this module any more.** See "WIX IS THE PRICE AUTHORITY" below.

``NOT_OFFERED_VARIANT_IDS`` and ``NOT_OFFERED_KINDS`` are EMPTY, and the refusal code, its
message and the not-offered branch in ``service_line`` all deliberately remain. They are the guard
for the NEXT variant somebody adds in Wix: naming it here refuses it by name rather than letting it
through as an ordinary product line, which would charge for a service nothing can deliver.

Three of the four REQUIRE a target Submit Request (``TARGET_REQUIRED_KINDS``): an amendment amends
one, Drop Docs sends documents for "a request already under way", and Vault asks for "a copy of a
document held against one of your requests". A target-free Drop Docs would let a customer pay
Rs.350 to attach documents to nothing. The target is resolved and owned-checked in
``service_request_store`` BEFORE money moves.

WIX IS THE PRICE AUTHORITY (owner decision 2026-10-08)
------------------------------------------------------
This module used to hold ``SERVICE_CHOICES_PAISE``, ``{variant: (kind, committed paise)}``, and
``assert_service_line_price`` refused any Wix line price that was not EQUAL to the committed
figure. That had a consequence worth stating plainly, because it is the reason the constant is
gone: **editing a price in Wix did not change what the page charged, it refused the purchase.**
A card showing the live Rs.149 would answer ``SERVICE_PRICE_CHANGED`` on every attempt until
somebody deployed. The owner's requirement is that a price be changeable in Wix with no deploy,
so the authority moved to Wix and the constant could not stay.

What that costs, and what replaces it. The equality check was the only thing standing between a
Wix catalogue typo and a charge, so its removal leaves exactly one rail:
``SERVICE_LINE_MIN_PAISE``/``SERVICE_LINE_MAX_PAISE``. That is **not a price lock** -- 49 -> 149
-> 999 all pass untouched, which is the point -- it refuses only a figure of the Rs.99,999
shape, where the likeliest explanation is a mistyped Wix field rather than a pricing decision.

Every STRUCTURAL check survives unchanged, and they are what keep this safe: exactly one service
line, an allow-listed variant of the one services product, ``confirmedQuantity == 1``, the
summary line found and readable, and -- on a services-only basket -- delivery, tax and
additionalFees all exactly zero. A per-line assertion is also what makes this work in a mixed
basket and under a coupon: line totals are pre-discount and sum to the subtotal
(`cart_v2.calculate` enforces that).

`lambda_utils.ecommerce.service_pricing` reads the SAME figure through the SAME adapter for the
public service pages, so the price a page promises and the price the checkout charges come from
one source and cannot drift.

PRICING IS ORDINARY ORDER PRICING
---------------------------------
Unlike a contribution, a service is NOT fee-exempt: `cart_v2.calculate` prices the line and
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

from lambda_utils.ecommerce import cart_v2
from lambda_utils.ecommerce.money import Money, positive_paise

logger = logging.getLogger(__name__)

#: The only currency services are taken in. Compared explicitly, never inferred.
SERVICE_CURRENCY = "INR"

#: The Wix catalogue product that carries every service variant, lowercased. A catalogue
#: reference, not a secret. Measured in `src/content/wix-catalog.json` (`WECARE.DIGITAL
#: Services`, PHYSICAL, four variants).
SERVICE_PRODUCT_IDS: FrozenSet[str] = frozenset({
    "df976a0a-f582-4535-b2e1-d532f348bd27",
})

#: Request kinds. A REQUEST lifecycle vocabulary, unrelated to payment status.
SUBMIT_REQUEST = "SUBMIT_REQUEST"
REQUEST_AMENDMENT = "REQUEST_AMENDMENT"
DROP_DOCS = "DROP_DOCS"
VAULT = "VAULT"

#: THE ONLY FOUR SERVICES THAT CAN BE BOUGHT, as ``{variant id: kind}``. NO PRICE: the mapping is
#: stable catalogue identity, the price is Wix's and is read live. Mirrored in
#: src/config/services.ts as SERVICE_CHOICES.
SERVICE_KIND_BY_VARIANT: Mapping[str, str] = MappingProxyType({
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b": SUBMIT_REQUEST,
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b": REQUEST_AMENDMENT,
    "db166bc8-a763-41ec-9f65-0f718f18155a": DROP_DOCS,
    "dcff995e-448c-493a-9259-f6a82ccdc2b4": VAULT,
})

#: THE CATASTROPHE RAIL, and the only bound on a service line now that Wix owns the price.
#:
#: Deliberately wide. A rail narrow enough to be a price check would reintroduce the deploy the
#: owner removed -- an ordinary edit from Rs.49 to Rs.999 must pass with nobody's involvement.
#: Rs.50,000 is far above any plausible service price and far below the Rs.99,999-shaped figure a
#: mistyped Wix field produces, which is the single failure this is here to refuse. The minimum is
#: 1 paise, not 0: a free service line would charge a convenience fee on nothing.
#:
#: Owner-visible limit: a service genuinely priced above Rs.50,000 in Wix will be refused with
#: ``SERVICE_PRICE_CHANGED`` until this figure is raised, and that requires a deploy.
SERVICE_LINE_MIN_PAISE = 1
SERVICE_LINE_MAX_PAISE = 5_000_000

#: The four PUBLIC PAGE SLUGS, ``{slug: kind}``. One owner for the slug vocabulary, shared by the
#: public price endpoint (`service_pricing.resolve_all`) and mirrored in src/config/services.ts as
#: each choice's ``slug``. A slug is a URL path segment, never an identifier Wix sees.
SERVICE_KIND_BY_SLUG: Mapping[str, str] = MappingProxyType({
    "submit-request": SUBMIT_REQUEST,
    "request-amendment": REQUEST_AMENDMENT,
    "drop-docs": DROP_DOCS,
    "vault": VAULT,
})

#: The services that cannot exist without a target Submit Request of the CALLER'S OWN. One
#: frozenset rather than three ``kind ==`` comparisons, so adding a fourth target-taking service
#: cannot reach only two of the three places that have to agree.
TARGET_REQUIRED_KINDS: FrozenSet[str] = frozenset({REQUEST_AMENDMENT, DROP_DOCS, VAULT})

#: Variants of the same product that are deliberately NOT offered. EMPTY: all four are offered.
#: Kept, with its refusal code and its branch in ``service_line``, as the guard for the next Wix
#: variant somebody adds -- refusing by name beats charging for something nothing can deliver.
#: Mirrored in src/config/services.ts as NOT_OFFERED_SERVICE_VARIANT_IDS.
NOT_OFFERED_VARIANT_IDS: FrozenSet[str] = frozenset()

#: The kind names of the not-offered services, so `request-intent` refuses them by name too.
#: EMPTY for the same reason, and kept for the same reason.
NOT_OFFERED_KINDS: FrozenSet[str] = frozenset()

#: ``{kind: variant id}`` for the four offered services. Derived, so the two cannot drift.
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


class ServicePriceChanged(cart_v2.CartContractError):
    """Wix priced the service line at something other than its committed paise figure."""


class ServiceNotPayable(cart_v2.CartContractError):
    """Wix will not price a no-delivery services basket (it demands a delivery destination)."""


@dataclass(frozen=True)
class ServiceLine:
    """The one service line in a basket: which kind, which variant, and what Wix priced it at.

    ``paise`` is ``None`` from ``service_line``, because a basket is read BEFORE Wix prices it and
    this module no longer holds a figure to assume. It carries an integer only where the caller
    obtained one from Wix -- `assert_service_line_price` returns it and `payref_extra` records it.
    ``None`` therefore means "not priced yet", which is a different fact from "free", and keeping
    the two distinguishable is what stops an unpriced line being recorded as a zero charge.
    """

    kind: str
    variant_id: str
    paise: Optional[int] = None


def refusal(code: str) -> Dict[str, str]:
    """The wire payload for a refusal code: the code and its one honest sentence."""
    return {"error": code, "message": SERVICE_MESSAGES[code]}


def is_service_product(product_id: Any) -> bool:
    """Takes the ID, not the line -- the same reason as ``checkout/handler.py:_is_contribution_id``.

    A request line and a Wix cart line carry ``catalogReference`` at different levels, so a
    helper that took the line would silently answer False for one of them.
    """
    return str(product_id or "").strip().lower() in SERVICE_PRODUCT_IDS


def service_line(line_items: Any) -> Optional[ServiceLine]:
    """The basket's one service line, ``None`` when it holds none, or raise ``ServiceRejected``.

    PURE, and tolerant of a malformed ``line_items`` exactly like ``_contribution_request``:
    anything whose shape cannot be read is simply not recognised as a service and falls through
    to ``wix_ecom.resolved_catalog_lines``, which owns the strict shape refusals.

    The not-offered check runs BEFORE the allow-list so that a named-but-unavailable variant is
    refused by name (``SERVICE_NOT_OFFERED``) rather than as an unknown choice.
    ``NOT_OFFERED_VARIANT_IDS`` is currently empty -- all four services are offered -- so this
    branch is the guard for the next variant added in Wix, not dead code.
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
        if variant_id not in SERVICE_KIND_BY_VARIANT:
            logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_UNKNOWN_CHOICE}))
            raise ServiceRejected(SERVICE_UNKNOWN_CHOICE)
        quantity = line.get("quantity")
        # `type(...) is not int`, because `isinstance(True, int)` is True.
        if type(quantity) is not int or quantity != 1:
            logger.info(json.dumps({"event": "service_refused",
                                    "reason": SERVICE_INVALID_QUANTITY}))
            raise ServiceRejected(SERVICE_INVALID_QUANTITY)
        # No price: Wix prices the line, and nothing here may presume what that will be.
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


def checkout_preflight(line_items: Any, body: Any, *,
                       v2_enabled: bool) -> Optional[Tuple[int, Dict[str, str]]]:
    """``None`` to proceed, or ``(status, payload)`` to refuse. PURE: before profile, Wix or DynamoDB.

    * a non-service basket -> ``None`` (byte-identical behaviour for every other order);
    * a refused service line -> 409 with its code;
    * Cart V2 off -> 503 ``SERVICE_UNAVAILABLE``: the V1 branch has no per-line price assertion,
      so a service is never priced there unchecked;
    * no well-formed ``serviceIntentId`` -> 409 ``SERVICE_INTENT_REQUIRED``: a paid service with
      no intent would be a paid service with no request.
    """
    try:
        line = service_line(line_items)
    except ServiceRejected as rejected:
        return 409, refusal(rejected.code)
    if line is None:
        return None
    if not v2_enabled:
        logger.warning(json.dumps({"event": "service_refused", "reason": SERVICE_UNAVAILABLE}))
        return 503, refusal(SERVICE_UNAVAILABLE)
    if not _intent_id(body):
        logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_INTENT_REQUIRED}))
        return 409, refusal(SERVICE_INTENT_REQUIRED)
    return None


def payref_extra(line_items: Any, body: Any, *,
                 line_paise: Optional[int]) -> Dict[str, Any]:
    """``{}`` for a non-service basket, else ``{"serviceLine": {kind, variantId, paise, intentId}}``.

    This is the join (plan D3): checkout writes it onto the ``PAYREF#`` reservation it already
    makes, and the service-requests Lambda reads it back after the order exists. Checkout gains
    no table and no IAM change. Called only after ``checkout_preflight`` passed.

    ``line_paise`` is WIX'S OWN figure for the line, as returned by
    ``assert_service_line_price``. The key set is unchanged -- a ``paise`` was always recorded
    here -- but its source moved from a committed constant to the calculation that priced the
    thing being charged, which is the only figure that can honestly claim to be what the customer
    paid for. ``None`` records ``None``, so an unpriced row is visibly unpriced rather than
    silently zero, and ``service_request_store.activate`` refuses it.

    REQUIRED KEYWORD, WITH NO DEFAULT, and the missing default is the point. Omitting it used to
    be silent and wrote ``paise: None``, which ``activate`` refuses as ``AMOUNT_MISMATCH`` ->
    ``PAID_SERVICE_UNMATCHED`` -- *after* the customer's money has moved. A ``TypeError`` at
    import and test time is the cheapest possible version of that same mistake. Pass ``None``
    explicitly when there is genuinely no calculation to read a figure from.
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


def _catalog_item_id(cart_line: Dict[str, Any]) -> str:
    source = cart_line.get("source") if isinstance(cart_line, dict) else None
    reference = (source or {}).get("catalogReference") if isinstance(source, dict) else None
    return str((reference or {}).get("catalogItemId") or "").strip().lower() \
        if isinstance(reference, dict) else ""


def _variant_id(cart_line: Dict[str, Any]) -> str:
    reference = ((cart_line.get("source") or {}).get("catalogReference") or {})
    options = reference.get("options") if isinstance(reference, dict) else None
    return str((options or {}).get("variantId") or "").strip().lower() \
        if isinstance(options, dict) else ""


def _mismatch(actual: Any, reason: str) -> None:
    logger.error(json.dumps({"event": "service_price_mismatch", "reason": reason,
                             "minPaise": SERVICE_LINE_MIN_PAISE,
                             "maxPaise": SERVICE_LINE_MAX_PAISE,
                             "linePaise": actual if type(actual) is int else None}))
    raise ServicePriceChanged("service line price is outside what may be charged")


def observed_service_line_paise(calculated: Dict[str, Any]) -> Optional[int]:
    """Wix's price for the one service line in a calculation, in integer paise, or ``None``.

    PURE and non-raising, so the figure can be re-read where the assertion has already passed
    without re-running it -- `checkout/handler.py` needs it in `_allocate_reference`, several
    frames away from `_v2_snapshot`. ``None`` whenever the shape is not readable; the assertion,
    not this, is what refuses a basket.
    """
    cart_lines = [line for line in ((calculated.get("cart") or {}).get("lineItems") or [])
                  if isinstance(line, dict) and is_service_product(_catalog_item_id(line))]
    if len(cart_lines) != 1:
        return None
    summary_lines = [line for line in ((calculated.get("summary") or {}).get("lineItems") or [])
                     if isinstance(line, dict)
                     and line.get("lineItemId") == cart_lines[0].get("id")]
    if len(summary_lines) != 1:
        return None
    try:
        return Money.from_wix((summary_lines[0].get("totalPrice") or {}).get("amount")).paise
    except ValueError:
        return None


def assert_service_line_price(calculated: Dict[str, Any], line_items: Any, *,
                              delivery_required: bool) -> Optional[int]:
    """Wix's own line price for the one service, at quantity 1, inside the catastrophe rail.

    RETURNS that figure in integer paise (``None`` for a non-service basket), because it is what
    will be charged and the caller has to record it. See the module docstring for why this no
    longer compares against a committed constant, and what the rail does and does not cover.

    Per LINE, not on the total, because the total legitimately carries other lines, a coupon and
    (in a mixed basket) delivery. ``summary.lineItems[].totalPrice`` is pre-discount and
    ``cart_v2.calculate`` already enforced that the lines sum to ``subtotal``, so a coupon cannot
    make an honest line read as a mismatch. When nothing in the basket needs delivery, the
    ``delivery`` component must also be exactly zero -- a Wix shipping rule matching this
    PHYSICAL product would otherwise add a charge to a request that ships nothing.

    Fails CLOSED on every disagreement, including a line it cannot find.
    """
    committed = service_line(line_items)
    if committed is None:
        return None
    cart_lines = [line for line in ((calculated.get("cart") or {}).get("lineItems") or [])
                  if isinstance(line, dict) and is_service_product(_catalog_item_id(line))]
    if len(cart_lines) != 1 or _variant_id(cart_lines[0]) != committed.variant_id:
        _mismatch(None, "SERVICE_LINE_NOT_FOUND")
    cart_line = cart_lines[0]
    if ((cart_line.get("quantityInfo") or {}).get("confirmedQuantity")) != 1:
        _mismatch(None, "SERVICE_LINE_QUANTITY")
    summary_lines = [line for line in ((calculated.get("summary") or {}).get("lineItems") or [])
                     if isinstance(line, dict) and line.get("lineItemId") == cart_line.get("id")]
    if len(summary_lines) != 1:
        _mismatch(None, "SERVICE_SUMMARY_LINE_NOT_FOUND")
    try:
        line_paise = Money.from_wix((summary_lines[0].get("totalPrice") or {}).get("amount")).paise
    except ValueError:
        _mismatch(None, "SERVICE_LINE_UNREADABLE")
    if not SERVICE_LINE_MIN_PAISE <= line_paise <= SERVICE_LINE_MAX_PAISE:
        _mismatch(line_paise, "SERVICE_LINE_OUT_OF_BOUNDS")
    # Re-asserted through the money core even though the bounds already imply it, so the one
    # figure that leaves this function has been through the same gate as every other amount.
    positive_paise(line_paise)
    if not delivery_required:
        # A services-only basket (nothing ships, so nothing else is in it but services). Every
        # component Wix can add on top of the lines must be exactly zero, or the payable rises
        # above "the committed line price + convenience fee" without a refusal -- the same hole
        # `_assert_contribution_total` closes on the total. NOT applied to a mixed basket, where
        # other lines legitimately carry delivery, tax and fees.
        components = calculated.get("componentsPaise") or {}
        for component, reason in (("delivery", "SERVICE_DELIVERY_CHARGED"),
                                  ("tax", "SERVICE_TAX_CHARGED"),
                                  ("additionalFees", "SERVICE_FEES_CHARGED")):
            value = components.get(component)
            if type(value) is not int or value != 0:
                _mismatch(line_paise, reason)
    return line_paise


__all__ = [
    "DROP_DOCS", "INTENT_ID_RE", "NOT_OFFERED_KINDS", "NOT_OFFERED_VARIANT_IDS",
    "PUBLIC_REQUEST_ID_RE", "REQUEST_AMENDMENT", "SERVICE_CURRENCY", "SERVICE_KIND_BY_SLUG",
    "SERVICE_KIND_BY_VARIANT", "SERVICE_LINE_MAX_PAISE", "SERVICE_LINE_MIN_PAISE",
    "SERVICE_MESSAGES", "SERVICE_PRODUCT_IDS", "SERVICE_SLUG_BY_KIND", "SERVICE_VARIANT_BY_KIND",
    "SUBMIT_REQUEST", "TARGET_REQUIRED_KINDS", "VAULT", "ServiceLine",
    "ServiceNotPayable", "ServicePriceChanged", "ServiceRejected", "assert_service_line_price",
    "checkout_preflight", "has_service_line", "intent_rebound", "is_service_product",
    "observed_service_line_paise", "payref_extra", "refusal",
    "service_line",
]
