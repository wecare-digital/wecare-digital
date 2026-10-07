"""Phase O-1 services: Submit Request and Request Amendment, as fixed-price product lines.

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

WHAT IS OFFERED IN O-1, AND WHAT IS REFUSED
-------------------------------------------
Only Submit Request and Request Amendment, Rs.99 each. The same product carries two more variants,
Drop Docs and Vault, which belong to a later phase (document storage, upload/download, CRM pull).
They are named in ``NOT_OFFERED_VARIANT_IDS`` so the server can REFUSE them by name
(`SERVICE_NOT_OFFERED`) rather than mistake them for an unknown variant -- and, crucially, rather
than let them through as an ordinary product line, which would charge for a service nothing in
this phase can deliver.

PRICING IS ORDINARY ORDER PRICING (plan D1)
-------------------------------------------
Unlike a contribution, a service is NOT fee-exempt: `cart_v2.calculate` prices the line and
`checkout_pricing.compute_quote` adds the 2.5% convenience fee and 18% GST on that fee, exactly
as for any single order. The committed paise figure below is therefore not a total -- it is the
expected LINE price, asserted per line by ``assert_service_line_price`` so that a Wix price edit
refuses the purchase (``SERVICE_PRICE_CHANGED``) instead of charging a figure the page did not
promise. A per-line assertion is what makes this work in a mixed basket and under a coupon: line
totals are pre-discount and sum to the subtotal (`cart_v2.calculate` enforces that).

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

#: THE ONLY TWO SERVICES THAT CAN BE BOUGHT IN O-1, as ``{variant id: (kind, line paise)}``.
#: Mirrored in src/config/services.ts as SERVICE_CHOICES.
SERVICE_CHOICES_PAISE: Mapping[str, Tuple[str, int]] = MappingProxyType({
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b": (SUBMIT_REQUEST, 9900),        # Rs.99
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b": (REQUEST_AMENDMENT, 9900),     # Rs.99
})

#: Variants of the same product that are deliberately NOT offered in this phase. Refused by name.
#: Mirrored in src/config/services.ts as NOT_OFFERED_SERVICE_VARIANT_IDS.
NOT_OFFERED_VARIANT_IDS: FrozenSet[str] = frozenset({
    "db166bc8-a763-41ec-9f65-0f718f18155a",     # Drop Docs  (O-2)
    "dcff995e-448c-493a-9259-f6a82ccdc2b4",     # Vault      (O-2)
})

#: The kind names of the not-offered services, so `request-intent` refuses them by name too.
NOT_OFFERED_KINDS: FrozenSet[str] = frozenset({"DROP_DOCS", "VAULT"})

#: ``{kind: variant id}`` for the two offered services.
SERVICE_VARIANT_BY_KIND: Mapping[str, str] = MappingProxyType(
    {kind: variant for variant, (kind, _paise) in SERVICE_CHOICES_PAISE.items()})

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
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
SERVICE_WEBSITE_ONLY = "SERVICE_WEBSITE_ONLY"
SERVICE_PRICE_CHANGED = "SERVICE_PRICE_CHANGED"
SERVICE_NOT_PAYABLE = "SERVICE_NOT_PAYABLE"

SERVICE_MESSAGES: Mapping[str, str] = MappingProxyType({
    SERVICE_NOT_OFFERED: "This service is not offered yet. Nothing has been charged.",
    SERVICE_UNKNOWN_CHOICE: "Choose Submit Request or Request Amendment. Nothing has been charged.",
    SERVICE_INVALID_QUANTITY: "A service is bought one at a time. Set its quantity to 1. "
                              "Nothing has been charged.",
    SERVICE_ONE_PER_ORDER: "Only one service can be paid for in an order. Remove the extra one. "
                           "Nothing has been charged.",
    SERVICE_INTENT_REQUIRED: "Start this service from its own page, then check out. "
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
    """The one service line in a basket: which kind, which variant, and its committed line paise."""

    kind: str
    variant_id: str
    paise: int


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

    The not-offered check runs BEFORE the allow-list, so Drop Docs and Vault are refused by name
    (``SERVICE_NOT_OFFERED``) rather than as an unknown choice.
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
        if variant_id not in SERVICE_CHOICES_PAISE:
            logger.info(json.dumps({"event": "service_refused", "reason": SERVICE_UNKNOWN_CHOICE}))
            raise ServiceRejected(SERVICE_UNKNOWN_CHOICE)
        quantity = line.get("quantity")
        # `type(...) is not int`, because `isinstance(True, int)` is True.
        if type(quantity) is not int or quantity != 1:
            logger.info(json.dumps({"event": "service_refused",
                                    "reason": SERVICE_INVALID_QUANTITY}))
            raise ServiceRejected(SERVICE_INVALID_QUANTITY)
        kind, paise = SERVICE_CHOICES_PAISE[variant_id]
        found.append(ServiceLine(kind=kind, variant_id=variant_id, paise=paise))
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


def payref_extra(line_items: Any, body: Any) -> Dict[str, Any]:
    """``{}`` for a non-service basket, else ``{"serviceLine": {kind, variantId, paise, intentId}}``.

    This is the join (plan D3): checkout writes it onto the ``PAYREF#`` reservation it already
    makes, and the service-requests Lambda reads it back after the order exists. Checkout gains
    no table and no IAM change. Called only after ``checkout_preflight`` passed.
    """
    line = service_line(line_items)
    if line is None:
        return {}
    return {"serviceLine": {"kind": line.kind, "variantId": line.variant_id,
                            "paise": line.paise, "intentId": _intent_id(body)}}


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


def _mismatch(expected: int, actual: Any, reason: str) -> None:
    logger.error(json.dumps({"event": "service_price_mismatch", "reason": reason,
                             "expectedPaise": expected,
                             "linePaise": actual if type(actual) is int else None}))
    raise ServicePriceChanged("service line is not priced at its committed paise")


def assert_service_line_price(calculated: Dict[str, Any], line_items: Any, *,
                              delivery_required: bool) -> None:
    """The service line Wix priced IS the committed paise figure, to the paise, at quantity 1.

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
        return
    cart_lines = [line for line in ((calculated.get("cart") or {}).get("lineItems") or [])
                  if isinstance(line, dict) and is_service_product(_catalog_item_id(line))]
    if len(cart_lines) != 1 or _variant_id(cart_lines[0]) != committed.variant_id:
        _mismatch(committed.paise, None, "SERVICE_LINE_NOT_FOUND")
    cart_line = cart_lines[0]
    if ((cart_line.get("quantityInfo") or {}).get("confirmedQuantity")) != 1:
        _mismatch(committed.paise, None, "SERVICE_LINE_QUANTITY")
    summary_lines = [line for line in ((calculated.get("summary") or {}).get("lineItems") or [])
                     if isinstance(line, dict) and line.get("lineItemId") == cart_line.get("id")]
    if len(summary_lines) != 1:
        _mismatch(committed.paise, None, "SERVICE_SUMMARY_LINE_NOT_FOUND")
    try:
        line_paise = Money.from_wix((summary_lines[0].get("totalPrice") or {}).get("amount")).paise
    except ValueError:
        _mismatch(committed.paise, None, "SERVICE_LINE_UNREADABLE")
    if line_paise != positive_paise(committed.paise):
        _mismatch(committed.paise, line_paise, "SERVICE_LINE_PRICE")
    if not delivery_required:
        delivery = (calculated.get("componentsPaise") or {}).get("delivery")
        if type(delivery) is not int or delivery != 0:
            _mismatch(committed.paise, line_paise, "SERVICE_DELIVERY_CHARGED")


__all__ = [
    "INTENT_ID_RE", "NOT_OFFERED_KINDS", "NOT_OFFERED_VARIANT_IDS", "PUBLIC_REQUEST_ID_RE",
    "REQUEST_AMENDMENT", "SERVICE_CHOICES_PAISE", "SERVICE_CURRENCY", "SERVICE_MESSAGES",
    "SERVICE_PRODUCT_IDS", "SERVICE_VARIANT_BY_KIND", "SUBMIT_REQUEST", "ServiceLine",
    "ServiceNotPayable", "ServicePriceChanged", "ServiceRejected", "assert_service_line_price",
    "checkout_preflight", "has_service_line", "is_service_product", "payref_extra", "refusal",
    "service_line",
]
