"""The producer: a Wix Cart V2 calculation becomes a frozen, payable purchase intent.

THE GAP THIS CLOSES
-------------------
`checkout_pricing.build_snapshot` produces a `QuoteSnapshot`, and `QuoteSnapshot` is already
consumed in production by `ecommerce/website_checkout.py` (which turns it into the Razorpay
gateway amount) and `ecommerce/customer_receipt.py` (which prints it). But before this module,
`checkout_pricing.compute_quote` had **no production caller at all** -- only tests. So both
consumers depended on a snapshot that nothing in the running system produced. This is the
missing link, and it is the reason the Cart V2 migration matters rather than being version
hygiene.

The chain, end to end:

    CartV2.calculate(cart_id)            authoritative collection total, integer paise
      -> compute_quote(collection)       adds OUR convenience fee + GST on that fee
      -> build_snapshot(...)             freezes customer/cart/revision/items/address/delivery
      -> QuoteSnapshot                   -> website_checkout (gateway) / customer_receipt (print)

WHY THE TWO HALVES OF THE MONEY ARE SEPARATE, AND MUST STAY SEPARATE
--------------------------------------------------------------------
Wix owns the *supply* side: item prices, discounts, delivery and supply GST, computed from the
catalogue and the delivery address under the site's own tax configuration. We own the
*convenience fee* and the GST on that fee -- `compute_quote` contains no reference to Wix and
must not acquire one.

So `collection_before_convenience_paise` is Wix's `summary.priceSummary.total` and nothing
else. Passing a subtotal, or re-deriving the total locally, would either double-tax the supply
or under-collect it. `compute_quote`'s own docstring states the contract; this module is where
it is honoured.

WHY THE ADDRESS IS REQUIRED WHENEVER THE BASKET REQUIRES DELIVERY
-----------------------------------------------------------------
Two independent reasons, and both are about the number being right rather than present:

1. Delivery is a *component* of the collection total. A quote taken before a delivery method
   is chosen is missing money.
2. The delivery address is the place of supply, which decides CGST+SGST versus IGST on an
   invoice carrying seller GSTIN `19AAFFW7196L1Z8`.

Cart V2 enforces (1) itself: a cart with no address or method answers Calculate Cart with
`ERROR`-severity `MISSING_DELIVERY_ADDRESS` / `MISSING_DELIVERY_METHOD` violations, and
`CartV2.calculate` refuses to quote. That refusal is the contract working. Checkout V1 returned
a total in the same situation only because it validated nothing.

There is deliberately **no** placeholder-address path here. A fabricated address makes Calculate
Cart answer 200 and produces a wrong tax split that would then be charged, which is worse than
no quote at all.

AND WHY `owned_address` IS NEVERTHELESS `Optional` (Phase 2, Sec 3.3). Both reasons above remain
true for a physical basket and nothing about them is softened. What changed is that a basket can
now contain no line that requires delivery at all -- a DIGITAL contribution product -- and for
such a basket there is no place of supply to state. Two cases follow:

1. A no-delivery basket passes `owned_address=None`. `gst_state_code(None)` would raise
   `UnmappableAddress` through `normalize_address`, so the call below is guarded and
   `seller_state_known` becomes `None`. `_intra_state(None)` already answers `None`, and
   `compute_quote` already documents its own fallback ("It defaults to intra-state when neither
   is available"), so no new rule is invented. `checkout_pricing.exempt_quote` -- the fee-exempt
   `quote_fn` a contribution substitutes here -- normalises the same unknown the same way.
2. A physical basket with no resolvable stored address still raises `DeliveryDetailsRequired`
   from its caller, before any Wix write. The guard is not removed, it is made conditional on
   the basket, and the condition lives in `checkout/handler.py:_v2_snapshot`.

Do not read the `= None` default as an invitation to stop requiring an address for goods.

INTEGER PAISE THROUGHOUT
------------------------
Nothing in this module performs float arithmetic. The amount arrives as integer paise from
`CartV2.calculate`, is handed to `compute_quote` as integer paise, and the reconciliation below
is integer equality. A one-paise discrepancy fails closed rather than being absorbed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from .cart_v2 import cheapest_delivery_option
from .checkout_pricing import (
    CALCULATION_POLICY_VERSION,
    PricingError,
    QuoteSnapshot,
    build_snapshot,
    compute_quote,
)
from .wix_address import UnmappableAddress, gst_state_code, to_wix_address

logger = logging.getLogger(__name__)

#: How long a frozen quote may be paid against. Matches `customer_cart.QUOTE_LIFETIME`: the two
#: describe the same fact -- how long a price the customer reviewed stays honourable -- and a
#: second number would eventually disagree with the first.
QUOTE_TTL_SECONDS = 300


class DeliveryDetailsRequired(ValueError):
    """A payable quote was requested for a cart that has no delivery address or method.

    Separate from `CartContractError` so a caller can tell "the customer has not chosen a
    delivery destination yet", which is a normal, recoverable step in the purchase flow, from
    "Wix returned something unsafe", which is not. The first deserves a prompt; the second
    deserves a refusal.
    """


def apply_coupon(adapter, cart_id: str, code: str) -> Dict[str, Any]:
    """Apply a coupon code server-side and return the updated cart.

    A coupon is the one customer-supplied input on this path that is allowed to lower the amount,
    and it is safe for a specific reason: the code is a CLAIM, not a value. Wix decides whether it
    is valid, what it is worth, and whether this cart qualifies; the reduced figure then arrives
    through Calculate Cart like every other component. So a browser can ask for a discount to be
    validated and cannot grant itself one.

    It lowers the collection total, which legitimately lowers the convenience-fee basis: the fee is
    charged on the collection total after supply GST, discounts and delivery, excluding the fee and
    its own GST. Nothing about the fee calculation needs to know a coupon was involved.
    """
    return adapter.add_coupon(cart_id, code)


def prepare_delivery(adapter, cart_id: str, owned: Dict[str, Any],
                     *, delivery_option_id: Optional[str] = None) -> Dict[str, Any]:
    """Put the customer's OWNED address onto a Cart V2 cart AND select a delivery method.

    `owned` is this application's structured address, as produced by
    `lambda_utils.identity.address`, loaded server-side against the authenticated customer. It
    is never taken from a request body: an address a browser can set is an address an attacker
    can set, and here that would move the place of supply.

    SETTING THE ADDRESS WAS NEVER ENOUGH, AND THAT IS WHAT THIS FUNCTION NOW FIXES. Cart V2 needs
    `deliveryInfo.address` *and* `deliveryInfo.method`; an addressed cart with no method answers
    Calculate Cart with an `ERROR`-severity `MISSING_DELIVERY_METHOD` and cannot be priced. This
    function used to set only the address whenever `delivery_option_id` was omitted -- which is
    what every caller does -- so no physical website checkout could ever be priced. The live logs
    for 2026-10-04 15:00-15:01 UTC are one `website_checkout_delivery_blocked` per attempt,
    `violations: ["MISSING_DELIVERY_METHOD"]`, and this is the line they point at.

    THE AUTO-SELECTION IS A DELIBERATE REVERSAL OF A PREVIOUS DECISION, so the old reasoning is
    worth answering rather than deleting. `build_intent`'s docstring says a function that both
    chooses and quotes "could silently pick the cheapest or the first option on the customer's
    behalf". Three things make that safe here, and the first is the load-bearing one:

    1. **Wix picks, not us.** `adapter.delivery_options` reads `summary.deliverySummary`, which is
       Wix's own resolution of which option applies to this cart and address. On the live site it
       reports exactly one. We select what Wix already resolved; we do not search a menu.
    2. **The price still comes from Wix.** The option is an identifier. The delivery charge is
       whatever `calculate` then reports in `summary.priceSummary.delivery`, and
       `build_intent_with_calculation` quotes that figure, so selecting a method cannot alter a
       price in our favour or the customer's.
    3. **An explicit `delivery_option_id` still wins.** When a caller passes one -- a customer who
       chose from several options in a UI -- nothing is read and nothing is inferred.

    With several options the rule is the CHEAPEST, ties resolved to Wix's own first
    (`cart_v2.cheapest_delivery_option`). Deterministic, and the only direction defensible without
    asking: it is the smallest amount we could add to someone's bill. It does not arise on the
    live site today, where Wix resolves one option.

    With ZERO options the address is left set, NO method is chosen, and
    `DeliveryDetailsRequired` is raised -- the same honest refusal as before, reached one step
    earlier. The `website_checkout_delivery_zero_options` log line is what makes a genuine region
    gap ("Wix offered nothing for this address") distinguishable from the defect above ("we never
    asked"), which the `MISSING_DELIVERY_METHOD` violation alone cannot do: both produce it.

    Returns the updated cart.
    """
    cart = adapter.set_delivery_address(cart_id, to_wix_address(owned))
    if delivery_option_id is None:
        options = adapter.delivery_options(cart_id)
        chosen = cheapest_delivery_option(options)
        if chosen is None:
            # Wix was ASKED and named nothing. A region/rate gap in the Wix dashboard, not a bug
            # here, and not something the customer can fix by re-entering their address. The cart
            # id is a resource id and the option count is a count: no address, no PII.
            logger.warning(json.dumps({"event": "website_checkout_delivery_zero_options",
                                       "wixCartId": str(cart_id),
                                       "cartRevision": str(cart.get("revision") or ""),
                                       "optionCount": 0}))
            raise DeliveryDetailsRequired(
                "wix offered no delivery option for this address, so the cart cannot be priced")
        delivery_option_id = chosen["id"]
        logger.info(json.dumps({"event": "website_checkout_delivery_selected",
                                "wixCartId": str(cart_id),
                                "optionCount": len(options),
                                # The charge itself still arrives from `calculate`; this is the
                                # figure the selection was made ON, logged so a surprising
                                # delivery charge can be traced to the option that carried it.
                                "optionPricePaise": chosen.get("pricePaise"),
                                "autoSelected": True}))
    return adapter.set_delivery_method(cart_id, delivery_option_id)


def build_intent(adapter, *, customer_id: str, cart_id: str,
                 owned_address: Optional[Dict[str, Any]] = None,
                 now: int, site: Any = None, buyer_gstin: Optional[str] = None,
                 ttl_seconds: int = QUOTE_TTL_SECONDS,
                 quote_fn: Callable[..., Any] = compute_quote) -> QuoteSnapshot:
    """Unchanged contract: the snapshot only. ONE `adapter.calculate` call, via the sibling below.

    The signature is forwarded explicitly rather than through `**kwargs`: `**kwargs` would drop
    `ttl_seconds` and `quote_fn` from the public surface, where a reader and a type checker both
    look for them, and would turn an argument typo into a `TypeError` one frame deeper.
    """
    snapshot, _calculated = build_intent_with_calculation(
        adapter, customer_id=customer_id, cart_id=cart_id, owned_address=owned_address,
        now=now, site=site, buyer_gstin=buyer_gstin, ttl_seconds=ttl_seconds,
        quote_fn=quote_fn)
    return snapshot


def build_intent_with_calculation(adapter, *, customer_id: str, cart_id: str,
                                  owned_address: Optional[Dict[str, Any]] = None,
                                  now: int, site: Any = None,
                                  buyer_gstin: Optional[str] = None,
                                  ttl_seconds: int = QUOTE_TTL_SECONDS,
                                  quote_fn: Callable[..., Any] = compute_quote,
                                  ) -> Tuple[QuoteSnapshot, Dict[str, Any]]:
    """`(snapshot, calculated)` from ONE `adapter.calculate` call.

    The Wix order payload must be built from the same calculation the price was quoted from, and
    `build_intent` was throwing that calculation away. Returning it is strictly cheaper than any
    way of getting it back later: a second `calculate` can drift by a paise, and the frozen
    snapshot keeps `summary.lineItems` but not `cart.lineItems`, so it has no `catalogReference`
    to rebuild a payload from.

    Raises exactly what `build_intent` raised, from the same places: `PricingError`,
    `DeliveryDetailsRequired`, and any other `CartContractError` unchanged.

    The cart must already carry a delivery address and method -- call `prepare_delivery` first.
    This does not set them itself, deliberately: choosing a delivery method is a customer
    decision with a price attached, and a function that both chooses and quotes could silently
    pick the cheapest or the first option on the customer's behalf.

    `owned_address` is used for two things and neither is the supply tax: it is frozen into the
    snapshot hash, and its state resolves `intra_state` for the GST on our convenience fee. The
    supply tax is whatever Wix calculated from the address already on the cart.

    `owned_address` may be `None`, and only for a basket where no line requires delivery -- see
    the module header. `intra_state` then falls back to the documented intra-state default
    instead of being resolved from a state code. The caller, not this function, decides whether
    an address was required.

    Raises `DeliveryDetailsRequired` when the cart cannot be quoted because delivery details are
    missing, and lets any other `CartContractError` through unchanged.
    """
    if not isinstance(customer_id, str) or not customer_id:
        raise PricingError("a customer id is required")

    try:
        calculated = adapter.calculate(cart_id)
    except ValueError as error:
        # `preview` is the non-raising read; use it to tell a missing-delivery cart from an
        # unsafe one. Only the delivery case is converted, and only when Wix itself says so --
        # never inferred from the exception text, which is not a stable contract.
        if _delivery_is_missing(adapter, cart_id):
            raise DeliveryDetailsRequired(
                "this cart has no delivery address or delivery method, so it cannot be priced"
            ) from None
        raise error

    if calculated["currency"] != "INR":
        raise PricingError("only INR carts can be quoted")

    # `None` for a basket with no line that requires delivery (Phase 2, Sec 3.3). Guarded
    # rather than passed through: `gst_state_code(None)` raises `UnmappableAddress` via
    # `normalize_address`. `_intra_state(None)` already answers `None`, which both
    # `compute_quote` and `exempt_quote` normalise to intra-state.
    #
    # THE TEST IS `is not None`, NOT TRUTHINESS, and the difference is a guard rather than a
    # style choice. An EMPTY dict is a placeholder address, and
    # `test_an_unmappable_owned_address_never_reaches_a_quote` requires `{}`, `{"state":
    # "Unknown"}` and a dashes-only address to raise `UnmappableAddress` rather than be laundered
    # into a price. Truthiness would make `{}` skip the resolution silently and quote anyway.
    # Only an explicit `None` -- which only a no-delivery basket passes, see
    # `checkout/handler.py:_v2_snapshot`, where the argument is `owned or None` -- means "there is
    # no place of supply to resolve".
    seller_state_known = gst_state_code(owned_address) if owned_address is not None else None
    quote = quote_fn(
        calculated["amountPaise"],
        currency="INR",
        buyer_gstin=buyer_gstin,
        # None lets `compute_quote` infer from the buyer GSTIN when one is present, which is the
        # stronger signal: a registered buyer's own state code is authoritative over a shipping
        # destination. Falls back to the delivery state otherwise.
        intra_state=None if buyer_gstin else _intra_state(seller_state_known),
    )
    if quote.policy_version != CALCULATION_POLICY_VERSION:
        raise PricingError("quote policy version does not match the current calculator")
    if quote.collection_before_convenience_paise != calculated["amountPaise"]:
        # Integer equality, not a tolerance. The whole payment path fails closed on a one-paise
        # mismatch, so a calculator that altered the collection total must not reach a gateway.
        raise PricingError("the quote altered the authoritative collection total")

    snapshot = build_snapshot(
        customer_id=customer_id,
        cart_id=calculated["wixCartId"],
        cart_revision=_revision(calculated["cartRevision"]),
        quote=quote,
        created_at=now,
        ttl_seconds=ttl_seconds,
        site=site,
        items=calculated["summary"].get("lineItems"),
        address=calculated["deliveryAddress"],
        delivery=calculated["deliveryMethod"],
        payment={
            "wixGiftCard": calculated.get("wixGiftCard"),
            "wixGiftCardRedeemPaise": int(calculated.get("wixGiftCardRedeemPaise") or 0),
            "wixPayNowPaise": int(calculated.get("wixPayNowPaise") or 0),
        },
    )
    return snapshot, calculated


def _intra_state(delivery_state_code: Optional[str]) -> Optional[bool]:
    """Whether the supply is intra-state, from the delivery state's GST code.

    `None` when the destination is outside India, which leaves `compute_quote`'s own default in
    place rather than asserting a split this module cannot determine.
    """
    if delivery_state_code is None:
        return None
    from .checkout_pricing import SELLER_GSTIN
    return delivery_state_code == SELLER_GSTIN[:2]


def _delivery_is_missing(adapter, cart_id: str) -> bool:
    """Whether Wix itself reported a missing delivery address or method on this cart.

    Keyed on the violation `code`, which is part of the Cart V2 contract, rather than on an
    exception message. If the preview call itself fails there is no evidence either way, so this
    answers `False` and the original refusal stands -- an unexplained failure must not be
    reported to a customer as "choose an address".
    """
    try:
        preview = adapter.preview(cart_id)
    except Exception:  # noqa: BLE001
        return False
    codes = {str(v.get("code") or "") for v in preview.get("blockingViolations") or []}
    return bool(codes & {"MISSING_DELIVERY_ADDRESS", "MISSING_DELIVERY_METHOD"})


def _revision(value: Any) -> int:
    """Wix sends `revision` as a decimal string; `QuoteSnapshot` requires a non-negative int."""
    try:
        revision = int(str(value))
    except (TypeError, ValueError):
        raise PricingError("cart revision is not an integer") from None
    if revision < 0:
        raise PricingError("cart revision must be non-negative")
    return revision


__all__ = [
    "QUOTE_TTL_SECONDS",
    "DeliveryDetailsRequired",
    "apply_coupon",
    "prepare_delivery",
    "build_intent",
    "build_intent_with_calculation",
]
