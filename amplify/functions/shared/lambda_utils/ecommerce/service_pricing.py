"""The LIVE Wix price of each WECARE.DIGITAL service, for the public service pages.

WHY THIS EXISTS
---------------
Owner decision 2026-10-08: "price 49 or 99 can change any time so make dynamic". Before this
module the four prices were a committed constant in `service_requests.SERVICE_CHOICES_PAISE`, so
changing a price in Wix needed a code deploy -- and until that deploy, a Wix edit *refused* the
purchase with ``SERVICE_PRICE_CHANGED`` rather than charging the new figure. Wix is now the
price authority on both halves: this module reads the live figure for DISPLAY, and
`service_requests.assert_service_line_price` charges whatever Wix prices the line at (inside a
catastrophe rail). The two therefore cannot disagree about what a service costs.

THE PRICE COMES FROM THE CART, NOT FROM A PRODUCT READ
------------------------------------------------------
`CartV2.estimate` on a one-line, quantity-1 cart reports exactly the figure `CartV2.calculate`
would price that service line at, through the same adapter and the same Wix pricing rules. A
`/stores/v3/products/{id}` variant read would be a SECOND pricing path, free to drift from the
cart under an automatic discount -- and then the page would promise one number while the
checkout charged another. There is one pricing path, and it is the cart's.

`estimate` sends all four calculate flags false, so it needs no delivery address, which is
exactly the pre-address state a public page is in. It deliberately returns no `amountPaise`,
`calculationId` or `priceVerificationToken`, so nothing it produces can reach a gateway.

ONE CART PER VARIANT, FOREVER
-----------------------------
`SERVICEPRICECART#<variantId>` on the commerce-keys table points at the one Wix cart this
module ever creates for that variant, and every later read reuses it. Without the pointer a
public, unauthenticated endpoint would create a Wix cart per cache miss -- an unbounded write
rate on a provider, driven by anonymous traffic. With it, the lifetime total is four carts.
The row is a POINTER, not an expiring uniqueness claim, so it is permanent and the table's
TTL stays disabled (which `order_keys` requires of this table anyway).

THE REUSE PATH GOES THROUGH `get`, AND THAT IS NOT INCIDENTAL
-------------------------------------------------------------
`CartV2.get` is the ONLY adapter call that converts Wix's 404 on the cart resource into
`cart_v2.CartGone`; `estimate` would let a raw transport error escape. Since a persisted cart id
is exactly the thing that can go stale (expired, deleted, or minted against a different site --
the live dead end `CartGone`'s docstring records), the reuse path reads the cart first and only
then estimates it. That read pays for itself twice: it is also where the explicit INR check
happens, because `estimate()["currency"]` is a LITERAL inside `CartV2._not_payable` and not a
value Wix returned. A currency check against a literal checks nothing.

FAIL CLOSED, PER SLUG
---------------------
A slug whose price cannot be resolved is reported `{"available": False}` with NO `paise` key at
all -- not a zero, not a stale figure, not a fallback constant. The page then shows its
"temporarily unavailable" sentence and offers no way to pay, because paying a guessed price is
the one outcome worse than not selling. One slug failing leaves the other three priced.

Integer paise throughout, via `Money.from_wix` and `positive_paise`. No float arithmetic, no
boto3 import, no secret read, no HTTP client: the cart adapter and the table are injected.
"""

from __future__ import annotations

import json
import logging
import time
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional

from lambda_utils.ecommerce import cart_v2, service_requests
from lambda_utils.ecommerce.money import positive_paise

logger = logging.getLogger(__name__)

#: The pointer row prefix on the commerce-keys table. One row per offered variant, permanent.
SERVICE_PRICE_CART_PREFIX = "SERVICEPRICECART#"

#: How long a resolved payload is served from the warm sandbox before Wix is asked again.
#:
#: THE HONEST COST: a price edited in Wix appears on the page up to this many seconds later
#: (plus the edge's own `max-age`, which the route sets to the same figure). That staleness is
#: the price of not calling Wix four times per page view from an anonymous endpoint. It is a
#: DISPLAY delay only -- the checkout re-prices the line against Wix at the moment of payment,
#: so a stale card cannot cause a stale charge.
CACHE_SECONDS = 60

#: The currency every service is sold in. Compared explicitly against Wix's own fields.
SERVICE_CURRENCY = service_requests.SERVICE_CURRENCY

#: Wix's own currency fields on a cart. The same three `CartV2.calculate` checks, so a cart this
#: module prices from cannot be in a currency the checkout would refuse.
_CURRENCY_FIELDS = ("businessInfo", "customerInfo", "paymentInfo")

#: The one catalogue product carrying all four variants.
#:
#: Unpacked rather than indexed, so a SECOND product arriving in `SERVICE_PRODUCT_IDS` fails at
#: import with a readable error instead of this module silently pricing every variant against
#: whichever id sorted first -- which would quote four prices from the wrong catalogue entry.
(_PRODUCT_ID,) = tuple(service_requests.SERVICE_PRODUCT_IDS)


class ServicePriceUnavailable(Exception):
    """Wix's live price for a service could not be resolved. The caller must fail closed."""


def _pointer_key(variant_id: str) -> str:
    return SERVICE_PRICE_CART_PREFIX + str(variant_id or "").strip().lower()


def _stored_cart_id(table: Any, variant_id: str, key_attr: str) -> str:
    """The persisted Wix cart id for this variant, or `''`.

    A read failure answers `''` rather than raising: the recovery for "no usable pointer" is to
    create a cart, which is also the correct behaviour when the pointer merely could not be
    read. An invalid stored value is treated the same way, so a corrupt row cannot wedge a
    price permanently.
    """
    try:
        row = table.get_item(Key={key_attr: _pointer_key(variant_id)},
                             ConsistentRead=True).get("Item") or {}
        return cart_v2.identifier(str(row.get("wixCartId") or ""))
    except Exception:  # noqa: BLE001 -- any unreadable pointer means "create a fresh cart"
        return ""


def _remember_cart_id(table: Any, variant_id: str, cart_id: str, key_attr: str) -> None:
    """Overwrite the pointer. A write failure is logged and ignored, never raised.

    The price has already been resolved by the time this runs, so refusing to serve it because a
    pointer could not be saved would turn a cosmetic storage fault into an unavailable service.
    The only cost of a lost write is one extra Wix cart on the next miss.
    """
    try:
        table.put_item(Item={key_attr: _pointer_key(variant_id), "wixCartId": cart_id,
                             "variantId": str(variant_id).strip().lower()})
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({"event": "service_price_cart_pointer_unsaved",
                                   "variantId": str(variant_id).strip().lower(),
                                   "error": type(error).__name__}))


def _assert_inr(cart: Mapping[str, Any]) -> None:
    for field in _CURRENCY_FIELDS:
        value = cart.get(field) if isinstance(cart, Mapping) else None
        code = (value or {}).get("currencyCode") if isinstance(value, Mapping) else None
        if code != SERVICE_CURRENCY:
            raise ServicePriceUnavailable("service price cart is not in INR")


def _subtotal_paise(estimate: Mapping[str, Any]) -> int:
    if not isinstance(estimate, Mapping):
        raise ServicePriceUnavailable("estimate returned no readable view")
    value = estimate.get("itemSubtotalPaise")
    # `type(...) is not int` rather than isinstance, because `isinstance(True, int)` is True.
    if type(value) is not int:
        raise ServicePriceUnavailable("estimate carried no integer subtotal")
    try:
        return positive_paise(value)
    except ValueError as error:
        raise ServicePriceUnavailable("estimate subtotal is not positive paise") from error


def resolve_variant_paise(cart_adapter: Any, table: Any, variant_id: str, *,
                          key_attr: str = "orderId") -> int:
    """Wix's live line price for one service variant, in integer paise, or raise.

    Reuses the persisted cart when there is one and it still exists; creates one and overwrites
    the pointer when there is not. Raises `ServicePriceUnavailable` for every other outcome --
    there is no fallback figure, by design.
    """
    variant = cart_v2.identifier(str(variant_id or "").strip().lower())
    cart_id = _stored_cart_id(table, variant, key_attr)
    if cart_id:
        try:
            cart = cart_adapter.get(cart_id)
            _assert_inr(cart)
            return _subtotal_paise(cart_adapter.estimate(cart_id))
        except cart_v2.CartGone:
            # The pointer is worthless: expired, deleted, or minted against another site. Drop
            # it and mint a fresh cart, which is a recovery the customer never sees.
            logger.info(json.dumps({"event": "service_price_cart_gone", "variantId": variant}))
        except ServicePriceUnavailable:
            raise
        except Exception as error:  # noqa: BLE001
            raise ServicePriceUnavailable(
                "could not price the stored cart: %s" % type(error).__name__) from error
    try:
        # `CartV2.create` applies `cart_v2.catalog_item` itself, so the plain
        # `{productId, variantId, quantity}` shape is what it wants -- wrapping it here would
        # hand it an already-converted item and its exact-key-set check would refuse.
        cart = cart_adapter.create(
            [{"productId": _PRODUCT_ID, "variantId": variant, "quantity": 1}])
        _assert_inr(cart)
        fresh_id = cart_v2.identifier(str(cart.get("id") or ""))
        paise = _subtotal_paise(cart_adapter.estimate(fresh_id))
    except ServicePriceUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        raise ServicePriceUnavailable(
            "could not price a fresh cart: %s" % type(error).__name__) from error
    _remember_cart_id(table, variant, fresh_id, key_attr)
    return paise


#: `(deadline, payload)` for the warm sandbox. Module level, so it survives between invocations
#: in one execution environment and dies with it -- which is the whole of its lifecycle.
_cached: Optional[tuple] = None


def reset_cache() -> None:
    """Drop the warm-sandbox cache. For tests, and for a caller that must force a re-read."""
    global _cached
    _cached = None


def resolve_all(cart_adapter: Any, table: Any, *,
                clock: Callable[[], float] = time.monotonic,
                key_attr: str = "orderId") -> Dict[str, Any]:
    """Every public slug's live price: `{"currency": "INR", "prices": {slug: {...}}}`.

    Each slug is `{"available": True, "paise": <int>}` or `{"available": False}` -- and an
    unavailable slug carries NO `paise` key, so a consumer cannot read a price that was never
    resolved. Failures are per slug: one service Wix cannot price leaves the other three priced.

    Served from `CACHE_SECONDS` of warm-sandbox cache. A payload in which EVERY slug failed is
    not cached, so a transient Wix outage does not pin the pages as unavailable for a minute.
    """
    global _cached
    now = clock()
    if _cached is not None and now < _cached[0]:
        return _cached[1]
    prices: Dict[str, Dict[str, Any]] = {}
    for slug, kind in service_requests.SERVICE_KIND_BY_SLUG.items():
        variant = service_requests.SERVICE_VARIANT_BY_KIND.get(kind, "")
        try:
            prices[slug] = {"available": True,
                            "paise": resolve_variant_paise(cart_adapter, table, variant,
                                                           key_attr=key_attr)}
        except Exception as error:  # noqa: BLE001 -- one slug must not blank the other three
            logger.warning(json.dumps({"event": "service_price_unavailable", "slug": slug,
                                       "error": type(error).__name__}))
            prices[slug] = {"available": False}
    payload = {"currency": SERVICE_CURRENCY, "prices": prices}
    if any(price.get("available") for price in prices.values()):
        _cached = (now + CACHE_SECONDS, payload)
    return payload


#: Read-only view of the slug vocabulary, so a caller need not import `service_requests` too.
SERVICE_SLUGS: Mapping[str, str] = MappingProxyType(
    dict(service_requests.SERVICE_KIND_BY_SLUG))


__all__ = [
    "CACHE_SECONDS", "SERVICE_CURRENCY", "SERVICE_PRICE_CART_PREFIX", "SERVICE_SLUGS",
    "ServicePriceUnavailable", "reset_cache", "resolve_all", "resolve_variant_paise",
]
