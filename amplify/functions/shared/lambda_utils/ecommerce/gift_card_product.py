"""Recognising a GIFT-CARD PURCHASE in a cart, and extracting the face value to issue.

This is the SERVER half of the gift-card BUY side — the mirror of `service_requests` for the
services product. A customer buys a gift card the same way they buy anything: a ProductsTable SKU
added to the cart and paid on the one checkout path. When that payment is verified, a gift card of
the purchased face value must be ISSUED (a liability we take on), exactly once, keyed on the order
so a webhook replay mints one code and not two.

WHY THE SKU SET IS CONFIG-DRIVEN AND EMPTY BY DEFAULT
-----------------------------------------------------
There is no gift-card product in the catalogue yet, and inventing opaque SKU identifiers here
would hard-code catalogue identity that the owner has not created. So the recognised gift-card
SKUs are read from the environment (`GIFT_CARD_PRODUCT_IDS`, a comma-separated list) and default
to EMPTY. With none configured, `is_gift_card_product` is always False and `has_gift_card_line`
never fires — the BUY side is built but dormant, which is the truthful state (the terms copy
already says gift cards are built but not on sale online yet). The owner creates the SKU and sets
the env var; no code change is needed to turn the purchase side on.

This mirrors `WA_CATALOG_ORDERS_ENABLED` gating the WhatsApp order hand-off: capability present,
switched off until the catalogue data behind it exists.

FACE VALUE IS READ FROM THE FROZEN QUOTE, NEVER A CLIENT FIELD
--------------------------------------------------------------
The gift card's face value is the amount the customer PAID for the line, taken from the frozen
purchased snapshot (the same authority `native_service_line_paise` reads a service price from),
never from a browser field. A gift card issued for a value the customer did not pay is a liability
we never collected against. Integer paise throughout; no float, no division, no rounding here.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

#: The env var naming the ProductsTable product id(s) that ARE gift cards, comma-separated. One
#: owner for the vocabulary; read at call time (never module scope) so turning the purchase side
#: on is an env change, not a deploy, and a warm sandbox cannot cache the old empty set.
PRODUCT_IDS_ENV_KEY = "GIFT_CARD_PRODUCT_IDS"

# ── one gift card per purchase, no multiples ────────────────────────────────────
#: Refusal codes, mirroring `service_requests`'s one-per-order vocabulary. A gift card is bought
#: ONE at a time: a single line, quantity exactly 1.
GIFT_CARD_INVALID_QUANTITY = "GIFT_CARD_INVALID_QUANTITY"
GIFT_CARD_ONE_PER_ORDER = "GIFT_CARD_ONE_PER_ORDER"

GIFT_CARD_PURCHASE_MESSAGES: Mapping[str, str] = {
    GIFT_CARD_INVALID_QUANTITY: ("A gift card is bought one at a time. Set its quantity to 1. "
                                 "Nothing has been charged."),
    GIFT_CARD_ONE_PER_ORDER: ("Only one gift card can be bought in an order. Remove the extra "
                              "one. Nothing has been charged."),
}


class GiftCardPurchaseRejected(ValueError):
    """A pure pre-check refused a gift-card basket. Carries a stable `code`, never a body string.

    `ValueError` for the same load-bearing reason `service_requests.ServiceRejected` is: anything
    that escapes into the checkout handler's trailing `except ValueError` answers 409, not 500.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def refusal(code: str) -> Dict[str, str]:
    """The one wire shape for a gift-card purchase refusal, mirroring `service_requests.refusal`."""
    return {"error": code, "message": GIFT_CARD_PURCHASE_MESSAGES.get(
        code, "This gift-card purchase could not be accepted. Nothing has been charged.")}


def gift_card_product_ids(env: Optional[Dict[str, str]] = None) -> FrozenSet[str]:
    """The configured gift-card product ids (lowercased), or an empty set when none are set.

    Read from the injected mapping (defaulting to `os.environ`) at call time. Empty by default,
    so the BUY side is dormant until the owner creates the SKU and names it here.
    """
    raw = (env if env is not None else os.environ).get(PRODUCT_IDS_ENV_KEY, "") or ""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def is_gift_card_product(product_id: Any, *, env: Optional[Dict[str, str]] = None) -> bool:
    """Whether a ProductsTable product id is a configured gift-card SKU. NEVER raises."""
    if not isinstance(product_id, str) or not product_id.strip():
        return False
    return product_id.strip().lower() in gift_card_product_ids(env)


def has_gift_card_line(line_items: Any, *, env: Optional[Dict[str, str]] = None) -> bool:
    """Whether a NATIVE cart's line items name a gift-card product at all. NEVER raises.

    Keyed on the PRODUCT, mirroring `service_requests.has_service_line`, so a guard that must
    treat a gift-card basket specially asks one question. A native cart line carries the product
    id under `catalogReference.catalogItemId` (the website cart shape); this reads that. False
    whenever no gift-card SKU is configured.
    """
    if not isinstance(line_items, list):
        return False
    for line in line_items:
        if not isinstance(line, dict):
            continue
        reference = line.get("catalogReference")
        if isinstance(reference, dict) and is_gift_card_product(
                reference.get("catalogItemId"), env=env):
            return True
    return False


def checkout_preflight(line_items: Any, *, env: Optional[Dict[str, str]] = None
                       ) -> Optional[Tuple[int, Dict[str, str]]]:
    """`None` to proceed, or `(status, payload)` to refuse. PURE: before pricing or any DynamoDB.

    THE "ONE GIFT CARD PER PURCHASE" GATE, the mirror of `service_requests.checkout_preflight`.
    A gift card is bought one at a time, so a basket is refused BEFORE any money can move when:

      * a gift-card line carries a quantity that is not exactly 1 -> `GIFT_CARD_INVALID_QUANTITY`;
      * the basket holds more than one gift-card line (two SKUs, or the same one twice) ->
        `GIFT_CARD_ONE_PER_ORDER`.

    A non-gift-card basket, or any basket when no gift-card SKU is configured, returns `None`
    (byte-identical behaviour for every other order). The browser already keeps a product line at
    quantity 1, but that is convention; this is the authoritative server cap a crafted request or
    two distinct gift-card SKUs cannot bypass.

    `type(quantity) is not int` rather than `isinstance`, because `isinstance(True, int)` is True
    and a boolean quantity is not a count.
    """
    if not isinstance(line_items, list):
        return None
    gift_card_lines = 0
    for line in line_items:
        if not isinstance(line, dict):
            continue
        reference = line.get("catalogReference")
        product_id = reference.get("catalogItemId") if isinstance(reference, dict) else None
        if not is_gift_card_product(product_id, env=env):
            continue
        gift_card_lines += 1
        quantity = line.get("quantity")
        if type(quantity) is not int or quantity != 1:
            logger.info(json.dumps({"event": "gift_card_purchase_refused",
                                    "reason": GIFT_CARD_INVALID_QUANTITY}))
            return 409, refusal(GIFT_CARD_INVALID_QUANTITY)
    if gift_card_lines > 1:
        logger.info(json.dumps({"event": "gift_card_purchase_refused",
                                "reason": GIFT_CARD_ONE_PER_ORDER,
                                "giftCardLines": gift_card_lines}))
        return 409, refusal(GIFT_CARD_ONE_PER_ORDER)
    return None


def _snapshot_lines(snapshot: Any) -> List[Dict[str, Any]]:
    """The frozen quote's line items, or an empty list. The quote is the price authority.

    The stored `purchasedSnapshot` is `checkout_pricing` `frozen_data`: the lines live at the
    top-level `items` key (each `{lineItemId, productId, variantId, quantity, unitPricePaise}`),
    NOT under `cart` — `cart` is only `{id, revision}`. `_bounded_snapshot` keeps `items` even when
    it trims a large basket, so this reads the same key on both the full and reduced forms.
    """
    if not isinstance(snapshot, dict):
        return []
    lines = snapshot.get("items")
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def gift_card_purchases(snapshot: Any, *, env: Optional[Dict[str, str]] = None
                        ) -> List[Dict[str, Any]]:
    """The gift cards a FROZEN purchased snapshot bought, as `[{productId, faceValuePaise, quantity}]`.

    ONE GIFT CARD PER PURCHASE. `checkout_preflight` is the authoritative gate that refuses a
    multi-gift-card basket before any money moves, so a settled snapshot can only ever carry one
    gift-card line at quantity 1. This extractor enforces that as a BACKSTOP regardless: it caps
    `quantity` at 1 and returns AT MOST ONE entry, so even a snapshot that somehow slipped past the
    gate issues exactly one card rather than a windfall. A second gift-card line (or a quantity > 1)
    is logged and dropped, never issued.

    The face value is the line's own frozen unit price (`unitPricePaise`) read from the quote the
    customer paid — never a client field — so a gift card is only ever issued for value actually
    collected. Returns an empty list for a non-gift-card basket or when no SKU is configured.
    PURE: no table, no clock, no I/O.
    """
    out: List[Dict[str, Any]] = []
    for line in _snapshot_lines(snapshot):
        product_id = line.get("productId")
        if not is_gift_card_product(product_id, env=env):
            continue
        if out:
            # The one-per-order backstop: a second gift-card line should have been refused at
            # preflight. If one reached here, do NOT issue a second card.
            logger.warning('{"event":"gift_card_extra_line_dropped_at_issue"}')
            break
        unit = line.get("unitPricePaise")
        quantity = line.get("quantity")
        if (isinstance(unit, bool) or not isinstance(unit, int) or unit <= 0
                or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1):
            # A gift-card line that carries no usable integer price/quantity in the FROZEN quote
            # is skipped rather than guessed: issuing for an unknown value is worse than not
            # issuing, and the frozen quote is the one place the paid value is authoritative.
            logger.warning('{"event":"gift_card_line_unpriced_in_snapshot"}')
            continue
        if quantity != 1:
            # The quantity backstop: a gift card is one per purchase. A snapshot carrying more
            # than one unit was a basket preflight should have refused; issue exactly one.
            logger.warning('{"event":"gift_card_quantity_capped_to_one_at_issue"}')
        out.append({"productId": str(product_id), "faceValuePaise": int(unit), "quantity": 1})
    return out


__all__ = [
    "PRODUCT_IDS_ENV_KEY",
    "GIFT_CARD_INVALID_QUANTITY",
    "GIFT_CARD_ONE_PER_ORDER",
    "GIFT_CARD_PURCHASE_MESSAGES",
    "GiftCardPurchaseRejected",
    "refusal",
    "gift_card_product_ids",
    "is_gift_card_product",
    "has_gift_card_line",
    "checkout_preflight",
    "gift_card_purchases",
]
