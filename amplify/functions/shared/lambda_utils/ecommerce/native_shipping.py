"""AWS-native shipping/delivery resolver — the last native supply component.

Replaces the Wix delivery path (`cart_v2.delivery_options` /
`set_delivery_method`, whose charge Wix put in `priceSummary.delivery`). Shipping
is a BUSINESS POLICY, not something Wix uniquely owns: it is a rule over the cart
subtotal, the delivery address (place of supply), and whether any line requires
physical delivery. This module makes that policy explicit and server-authoritative,
returning options in the SAME `{id, title, pricePaise}` shape the Wix path used and
a chosen `delivery_paise` that feeds `catalog_pricing.price_cart(delivery_paise=...)`.

Policy (overridable via a ShippingPolicy; defaults are explicit, not hidden):
  - A fully-digital cart (no line requires delivery) ships free — there is nothing
    to deliver.
  - Otherwise: FREE at or above `free_above_paise`; else a flat `flat_rate_paise`.
  - An option id is an identifier, never a price (same rule as the Wix path):
    the charge is decided here from the policy, not supplied by the client.

Integer paise only, no float, no I/O. Unit-testable offline. NOT wired until
CHECKOUT_MODE=AWS_NATIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from lambda_utils.ecommerce.catalog_pricing import CatalogLine, _nonneg_paise

FREE_OPTION_ID = "free"
STANDARD_OPTION_ID = "standard"


class ShippingError(ValueError):
    """A delivery charge could not be resolved (e.g. an unknown option id)."""


@dataclass(frozen=True)
class ShippingPolicy:
    """Explicit, server-side shipping policy. Defaults are conservative and visible."""

    flat_rate_paise: int = 0
    free_above_paise: int = 0  # 0 means "always free above 0", i.e. free

    def __post_init__(self) -> None:
        _nonneg_paise(self.flat_rate_paise, "flat_rate_paise")
        _nonneg_paise(self.free_above_paise, "free_above_paise")


def requires_physical_delivery(lines: Sequence[CatalogLine]) -> bool:
    return any(getattr(line, "requires_delivery", True) for line in lines)


def delivery_options(lines: Sequence[CatalogLine], subtotal_paise: int,
                     policy: ShippingPolicy) -> List[Dict[str, Any]]:
    """Available delivery options, cheapest first, as `{id, title, pricePaise}`.

    A digital-only cart gets exactly one free option. A physical cart gets a free
    option when the subtotal qualifies, otherwise the standard flat-rate option.
    """
    _nonneg_paise(subtotal_paise, "subtotal_paise")
    if not requires_physical_delivery(lines):
        return [{"id": FREE_OPTION_ID, "title": "No delivery (digital)", "pricePaise": 0}]
    if policy.flat_rate_paise == 0 or subtotal_paise >= policy.free_above_paise:
        return [{"id": FREE_OPTION_ID, "title": "Free delivery", "pricePaise": 0}]
    return [{
        "id": STANDARD_OPTION_ID,
        "title": "Standard delivery",
        "pricePaise": policy.flat_rate_paise,
    }]


def resolve_delivery_paise(lines: Sequence[CatalogLine], subtotal_paise: int,
                           policy: ShippingPolicy, *, option_id: Optional[str] = None) -> int:
    """The authoritative delivery charge in paise for a chosen option.

    If `option_id` is None, the single resolved option's price is used (Wix's model
    resolved exactly one method for a cart+address). If an id is given it must be one
    the policy actually offers for this cart — a client cannot name a cheaper option.
    """
    options = delivery_options(lines, subtotal_paise, policy)
    by_id = {o["id"]: o for o in options}
    if option_id is None:
        chosen = options[0]
    else:
        chosen = by_id.get(option_id)
        if chosen is None:
            raise ShippingError(f"delivery option {option_id!r} is not offered for this cart")
    return _nonneg_paise(int(chosen["pricePaise"]), "delivery_paise")


__all__ = [
    "FREE_OPTION_ID", "STANDARD_OPTION_ID", "ShippingError", "ShippingPolicy",
    "requires_physical_delivery", "delivery_options", "resolve_delivery_paise",
]
