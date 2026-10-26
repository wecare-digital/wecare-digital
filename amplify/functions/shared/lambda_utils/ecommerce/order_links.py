"""The customer's order page link, built in one place.

The order page is `/orders/?o=<orderNumber>` on the canonical apex origin. It is gated behind the
customer's WhatsApp-OTP session: the page reads the order through the checkout `order` action,
which answers only for an order the signed-in customer owns. So the number in the URL SELECTS one
of the caller's own orders and never authorises anything - the rule `receipt_links` states for
receipts ("signed or gated behind a proven session").

Only a well-formed public order number produces a link (`order_keys.is_public_order_number`, the
current `WD-ORD-` form and the bare legacy form, both drawn from a URL-safe alphabet). Anything
else answers `''` so a caller omits the link instead of sending one that cannot resolve.
"""
from __future__ import annotations

from typing import Any

from . import order_keys

#: The canonical order page. Apex origin and trailing slash: the site is a static export with
#: `trailingSlash`, so `/orders` would spend a redirect.
ORDER_PAGE_URL = "https://wecare.digital/orders/"


def order_page_url(order_number: Any) -> str:
    """`https://wecare.digital/orders/?o=<orderNumber>`, or `''` for anything that is not one."""
    value = str(order_number or "").strip()
    if not order_keys.is_public_order_number(value):
        return ""
    return f"{ORDER_PAGE_URL}?o={value}"


__all__ = ["ORDER_PAGE_URL", "order_page_url"]
