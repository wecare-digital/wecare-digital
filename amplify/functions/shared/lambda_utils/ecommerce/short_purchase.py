"""Short Commerce Part 1: opt-in purchase-shape policy, never a pricing implementation.

The existing ProductsTable, checkout_pricing, Razorpay verification, payment attempts and
invoice engines remain authoritative. This module has no amount, currency, phone or provider
logic. Refuse unsupported carts BEFORE any cart write or payment reservation.
"""
import os
from collections.abc import Mapping


FLAG = "SHORT_COMMERCE_PART1_ENABLED"


def enabled() -> bool:
    """Default OFF to preserve the signed-off payment rail until rollout approval."""
    return os.environ.get(FLAG, "").strip().lower() in ("true", "1", "yes", "on")


def one_unit_lines(lines) -> bool:
    """Exactly one catalogue line and one unit; reject bool, float and string quantities."""
    if not isinstance(lines, (list, tuple)) or len(lines) != 1:
        return False
    line = lines[0]
    return isinstance(line, Mapping) and type(line.get("quantity")) is int and line["quantity"] == 1


def whatsapp_order_is_one_unit(message, basket) -> bool:
    """Reject ambiguous or partially parsed Meta carts, without silently dropping any item."""
    if not isinstance(message, Mapping) or basket is None:
        return False
    order = message.get("order")
    if not isinstance(order, Mapping):
        return False
    raw_lines = order.get("product_items")
    if not isinstance(raw_lines, (list, tuple)) or len(raw_lines) != 1:
        return False
    line = raw_lines[0]
    if not isinstance(line, Mapping):
        return False
    quantity = line.get("quantity")
    if not ((type(quantity) is int and quantity == 1)
            or (type(quantity) is str and quantity == "1")):
        return False
    return (one_unit_lines(basket.lines)
            and not basket.dropped
            and not basket.clamped)
