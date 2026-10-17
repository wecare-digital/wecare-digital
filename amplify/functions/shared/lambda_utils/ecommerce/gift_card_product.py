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

import logging
import os
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

#: The env var naming the ProductsTable product id(s) that ARE gift cards, comma-separated. One
#: owner for the vocabulary; read at call time (never module scope) so turning the purchase side
#: on is an env change, not a deploy, and a warm sandbox cannot cache the old empty set.
PRODUCT_IDS_ENV_KEY = "GIFT_CARD_PRODUCT_IDS"


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
    """Every gift-card line in a FROZEN purchased snapshot, as `{productId, faceValuePaise, quantity}`.

    The face value is the line's own frozen unit price (`unitPricePaise`) read from the quote the
    customer paid — never a client field — so a gift card is only ever issued for value actually
    collected. One entry per gift-card line; a line of quantity N means N cards of that face value
    (the caller issues N codes). Returns an empty list for a non-gift-card basket or when no SKU is
    configured. PURE: no table, no clock, no I/O.
    """
    out: List[Dict[str, Any]] = []
    for line in _snapshot_lines(snapshot):
        product_id = line.get("productId")
        if not is_gift_card_product(product_id, env=env):
            continue
        unit = line.get("unitPricePaise")
        quantity = line.get("quantity")
        if (isinstance(unit, bool) or not isinstance(unit, int) or unit <= 0
                or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1):
            # A gift-card line that carries no usable integer price/quantity in the FROZEN quote
            # is skipped rather than guessed: issuing for an unknown value is worse than not
            # issuing, and the frozen quote is the one place the paid value is authoritative.
            logger.warning('{"event":"gift_card_line_unpriced_in_snapshot"}')
            continue
        out.append({"productId": str(product_id), "faceValuePaise": int(unit),
                    "quantity": int(quantity)})
    return out


__all__ = [
    "PRODUCT_IDS_ENV_KEY",
    "gift_card_product_ids",
    "is_gift_card_product",
    "has_gift_card_line",
    "gift_card_purchases",
]
