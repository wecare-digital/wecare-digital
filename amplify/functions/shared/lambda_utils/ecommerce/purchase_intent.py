"""Purchase-intent vocabulary the checkout handler shares.

The payable quote itself is produced natively: `native_checkout.quote_native_cart` prices the
basket from ProductsTable and freezes it with `checkout_pricing.build_snapshot`. What lives here
is the refusal a caller raises when a basket cannot be quoted YET, which the checkout handler
answers with its own named 409.
"""

from __future__ import annotations

from typing import Any, Dict


class DeliveryDetailsRequired(ValueError):
    """A payable quote was requested for a basket whose delivery address or method is missing.

    Separate from `cart_contract.CartContractError` so a caller can tell "the customer has not
    chosen a delivery destination yet", which is a normal, recoverable step in the purchase flow,
    from a cart the contract refuses, which is not. The first deserves a prompt; the second
    deserves a refusal. `ecommerce/checkout/handler.py` answers it with 409
    `DELIVERY_DETAILS_REQUIRED`, and its subclass `DeliveryMethodUnavailable` with
    `DELIVERY_METHOD_UNAVAILABLE`.
    """


def apply_coupon(adapter, cart_id: str, code: str) -> Dict[str, Any]:
    """Apply a coupon code to a cart through its adapter and return the updated cart.

    The code is a CLAIM, not a value: the adapter decides whether it is valid, what it is worth
    and whether this cart qualifies, and the reduced figure arrives through the adapter's own
    pricing like every other component. So a browser can ask for a discount to be validated and
    cannot grant itself one. No amount is accepted here.
    """
    return adapter.add_coupon(cart_id, code)


__all__ = [
    "DeliveryDetailsRequired",
    "apply_coupon",
]
