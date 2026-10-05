"""Turning a verified-paid order into a Wix order and a recorded payment — and never a charge.

Status: INERT until switched on
-------------------------------
This module is the write-back half of reconciliation (design.md steps 5-6, R7.2-R7.5). It is
written, tested and guarded, but it is **not wired to run**: `is_enabled()` is false unless the
site's capability probe has confirmed the eCommerce write scope AND `WIX_WRITEBACK_ENABLED` is
set. Current readiness and credentials must be verified before enabling it;
historical configuration claims are not activation evidence. The module exists
now so it is ready and reviewed; enabling it is a later, deliberate step.

The one rule this module exists to guarantee: it cannot charge
--------------------------------------------------------------
R7.4 is absolute — recording a payment must not be able to collect one. That is enforced
structurally, not by care:

- **Every** Wix call goes through `_guarded_call`, which refuses any endpoint not in
  `ALLOWED_ENDPOINTS`. That set contains exactly two operations: create an order, and *record* an
  externally-collected payment (Wix's Add Payments, which its own docs state "does NOT perform the
  actual charging").
- The endpoints that *would* charge are named in `FORBIDDEN_ENDPOINT_MARKERS` and a call matching
  any of them raises `WixWouldCharge` before a request is built. This is belt-and-braces: the
  allowlist already excludes them, and this makes an accidental future addition fail loudly.
- `tests/test_wix_writeback.py` enumerates the complete set of calls this path can make and
  asserts none can charge, which is the explicit test R7.4 asks for.

The Add Payments endpoint additionally dedups on the external transaction id — "if any payment's
external transaction id already exists on the order, the entire call fails" — so even a retry that
slipped past our own `side_effect_guard` cannot double-record. Three layers, and the outermost is
the one that cannot be reasoned around.

Idempotency
-----------
Each side effect is claimed through `side_effect_guard` before it runs and confirmed after, so a
duplicate reconciliation converges: the Wix order is created once (`WIX_ORDER`), the payment is
recorded once (`WIX_PAYMENT`). A crash between claim and the Wix call leaves a `pending` marker
that requires provider readback; it must never trigger an automatic repeat write.

Injected client
---------------
`wix_request` is injected — the real `_wix_request` from the wix-store handler in production, a
fake in tests — so this module holds no AWS or Wix client, reads no credential, and every branch is
testable offline.
"""

from __future__ import annotations

import logging
import os
import re
from copy import deepcopy
from typing import Any, Callable, Dict, Mapping, Optional

from lambda_utils.ecommerce import side_effect_guard
from lambda_utils.ecommerce.money import Money, positive_paise

logger = logging.getLogger(__name__)

# ── the complete, static set of calls this path may make ────────────────────────
#: Create an eCommerce order. Non-charging: an order is a record, money moved elsewhere.
CREATE_ORDER = ("POST", "/ecom/v1/orders")
#: Record an externally-collected payment. Wix's own docs: "This does NOT perform the actual
#: charging - the order is only updated with records of the payments." The `{orderId}` is
#: substituted at call time; the template is what the allowlist matches on.
ADD_PAYMENT = ("POST", "/ecom/v1/payments/orders/{orderId}/add-payment")
#: Close the Cart V2 cart an externally-created order came from.
#:
#: Cart V2's own introduction names this as the call to make when an external system created the
#: order, which is exactly this architecture: Razorpay collects on our website, we record the
#: order with Orders API Create Order, and the cart is then marked completed. Without it a paid
#: cart is never closed and remains live for the customer.
#:
#: It CANNOT charge, and the distinction from its neighbour matters: Cart V2 **Place Order** is
#: the replacement for Checkout V1's Create Order and can enter Wix payment collection, which is
#: why it is absent from this list and from `cart_v2.CartV2` altogether. Mark Cart As Completed
#: only sets `orderPlaced` on the cart and attaches the order id -- it moves no money and offers
#: no payment surface.
MARK_CART_COMPLETED = ("POST", "/ecom/v2/carts/{cartId}/mark-as-completed")

#: The ONLY endpoints reachable from this module. Enumerated so R7.4's test can assert the set.
ALLOWED_ENDPOINTS = frozenset({CREATE_ORDER, ADD_PAYMENT, MARK_CART_COMPLETED})
CONFIRMED_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"
WRITE_CONTRACT = "cart-v2-external-v1"

#: Substrings that identify a charging/collecting endpoint. A call whose path contains any of
#: these raises before a request is built. The allowlist already excludes them; this is the loud
#: backstop against a future edit that adds one.
FORBIDDEN_ENDPOINT_MARKERS = (
    "/create-transaction",      # authorizes and optionally captures funds
    "create-transaction",
    "/charge",
    "/capture",
    "/pay-order",
    "/payment-requests",        # creates a payable page URL — a way to collect
    "order-payment-requests",
    "/checkout",                # a checkout can collect
    "/pay/",
    "velo/pay",
)


class WixWritebackDisabled(RuntimeError):
    """The write-back path is not enabled for this site. The order stays recoverable."""


class WixWritebackPending(RuntimeError):
    """An ambiguous write must be reconciled through readback, not repeated."""


class WixWouldCharge(RuntimeError):
    """A call was attempted against an endpoint that could charge the customer. Refused."""


class WixEndpointNotAllowed(RuntimeError):
    """A call was attempted against an endpoint not in the enumerated allowlist."""


def is_enabled() -> bool:
    """True only when the site's eCommerce write capability is proven AND the flag is set.

    Deliberately AND, not OR: the flag alone is a human assertion, the probe alone is a
    capability. Both are required so neither a stray env var nor a probe result can turn writes
    on by itself. Defaults to false — the safe state while the site id and payment config are open.
    """
    flag = str(os.environ.get("WIX_WRITEBACK_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")
    probed = str(os.environ.get("WIX_ECOM_WRITE_CONFIRMED", "")).strip().lower() in (
        "1", "true", "yes", "on")
    return (flag and probed and os.environ.get("WIX_SITE_ID") == CONFIRMED_SITE_ID
            and os.environ.get("WIX_CART_V2_WRITE_CONTRACT") == WRITE_CONTRACT)


def _endpoint_would_charge(path: str) -> bool:
    lowered = str(path or "").lower()
    return any(marker in lowered for marker in FORBIDDEN_ENDPOINT_MARKERS)


#: A single `{name}` placeholder in an allowlist template. Generalised from a hard-coded
#: `{orderId}` when Mark Cart As Completed arrived with a `{cartId}` slot — the slot's NAME was
#: never the point, and special-casing one name would have meant a new endpoint silently matching
#: nothing and being refused as off-list.
_SLOT_RE = re.compile(r"\{[A-Za-z][A-Za-z0-9]*\}")


def _matches_allowed(method: str, path: str) -> bool:
    """True when (method, path) matches an allowlisted endpoint, treating `{name}` as one slot.

    The slot accepts only `[A-Za-z0-9_-]{1,100}`, so a path cannot smuggle an extra segment, a
    query string or traversal through it and land on a different endpoint than the template
    describes.
    """
    for allowed_method, template in ALLOWED_ENDPOINTS:
        if method.upper() != allowed_method:
            continue
        slot = _SLOT_RE.search(template)
        if slot:
            prefix, suffix = template[:slot.start()], template[slot.end():]
            if path.startswith(prefix) and path.endswith(suffix) and \
                    len(path) > len(prefix) + len(suffix):
                if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", path[len(prefix):len(path) - len(suffix)]
                                if suffix else path[len(prefix):]):
                    return True
        elif path == template:
            return True
    return False


def _guarded_call(wix_request: Callable[..., Dict[str, Any]], *,
                  method: str, path: str, body: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """The ONLY way this module talks to Wix. Refuses anything that could charge or is off-list.

    Two independent refusals, checked before any request is built:
      1. `WixWouldCharge` if the path contains a charging marker.
      2. `WixEndpointNotAllowed` if it is not in the enumerated allowlist.
    """
    if _endpoint_would_charge(path):
        raise WixWouldCharge(
            f"refusing a call to {method} {path}: it matches a charging endpoint, and this "
            "path may only RECORD a payment, never collect one")
    if not _matches_allowed(method, path):
        raise WixEndpointNotAllowed(
            f"{method} {path} is not in the write-back allowlist; add it to ALLOWED_ENDPOINTS "
            "deliberately, and only if it cannot charge")
    return wix_request(path, method=method, body=body)


def create_wix_order(table: Any, wix_request: Callable[..., Dict[str, Any]], *,
                     order_id: str, order_payload: Dict[str, Any],
                     key_attr: str = "orderId") -> Dict[str, Any]:
    """Create the Wix order once for a verified-paid internal order. Idempotent via the guard.

    Returns `{"wixOrderId": ..., "created": bool}`. On a duplicate call it returns the existing
    Wix order id from the confirmed marker rather than creating a second order.

    Raises `WixWritebackDisabled` when the path is not enabled, so the caller keeps the order in a
    recoverable state rather than half-writing to Wix.
    """
    if not is_enabled():
        raise WixWritebackDisabled("Wix write-back is not enabled for this site")
    if not order_id:
        raise ValueError("order_id is required")

    existing = side_effect_guard.resolve(
        table, order_id=order_id, effect=side_effect_guard.WIX_ORDER, key_attr=key_attr)
    if existing and existing.get("state") == side_effect_guard.DONE:
        return {"wixOrderId": (existing.get("result") or {}).get("wixOrderId", ""),
                "created": False}

    if existing or not side_effect_guard.claim(
            table, order_id=order_id, effect=side_effect_guard.WIX_ORDER,
            key_attr=key_attr):
        # The other worker may still be calling Wix, or may have succeeded before
        # losing its response. A pending marker is NEVER permission to create again.
        raise WixWritebackPending("Wix order outcome needs readback before retry")

    response = _guarded_call(wix_request, method="POST", path="/ecom/v1/orders",
                             body={"order": order_payload})
    wix_order_id = str((response.get("order") or {}).get("id") or "")
    if not wix_order_id:
        raise WixWritebackPending("Wix order response has no order id")
    side_effect_guard.confirm(
        table, order_id=order_id, effect=side_effect_guard.WIX_ORDER,
        result={"wixOrderId": wix_order_id}, key_attr=key_attr)
    logger.info('{"event":"wix_order_created"}')
    return {"wixOrderId": wix_order_id, "created": True}


def record_external_payment(table: Any, wix_request: Callable[..., Dict[str, Any]], *,
                            order_id: str, wix_order_id: str,
                            provider_transaction_id: str, amount_paise: int,
                            currency: str = "INR",
                            key_attr: str = "orderId") -> Dict[str, Any]:
    """Record the already-collected payment against the Wix order. RECORDS, never charges.

    Uses Wix Add Payments (`/ecom/v1/payments/orders/{id}/add-payment`), which its docs state does
    not charge and which itself dedups on the external transaction id. Guarded by
    `side_effect_guard.WIX_PAYMENT` so a retry records once.
    """
    if not is_enabled():
        raise WixWritebackDisabled("Wix write-back is not enabled for this site")
    for name, value in (("order_id", order_id), ("wix_order_id", wix_order_id),
                        ("provider_transaction_id", provider_transaction_id)):
        if not value:
            raise ValueError(f"{name} is required")
    if isinstance(amount_paise, float):
        raise TypeError("amount_paise must be an int of minor units")
    amount_paise = positive_paise(amount_paise)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", wix_order_id):
        raise ValueError("invalid Wix order id")
    if currency != "INR":
        raise ValueError(f"only INR is supported, got {currency!r}")

    binding = {"providerTransactionId": provider_transaction_id,
               "wixOrderId": wix_order_id, "amountPaise": amount_paise, "currency": currency}
    existing = side_effect_guard.resolve(
        table, order_id=order_id, effect=side_effect_guard.WIX_PAYMENT, key_attr=key_attr)
    if existing and existing.get("state") == side_effect_guard.DONE:
        if existing.get("result") != binding:
            raise WixWritebackPending("recorded payment binding differs; readback required")
        return {"recorded": False}

    if not side_effect_guard.claim(
            table, order_id=order_id, effect=side_effect_guard.WIX_PAYMENT, key_attr=key_attr):
        raise WixWritebackPending("Wix payment outcome needs readback before retry")

    path = f"/ecom/v1/payments/orders/{wix_order_id}/add-payment"
    payload = {
        "payments": [{
            # An external payment record: money collected outside Wix (Razorpay via WhatsApp).
            "amount": {"amount": _paise_to_decimal_string(amount_paise)},
            "status": "APPROVED",
            "refundDisabled": True,
            "regularPaymentDetails": {
                "providerTransactionId": provider_transaction_id,
                "offlinePayment": False,
                "paymentMethodName": {"buyerLanguageName": "Razorpay via WhatsApp"},
            },
        }]
    }
    response = _guarded_call(wix_request, method="POST", path=path, body=payload)
    transactions = response.get("orderTransactions") or {}
    payments = transactions.get("payments") or []
    matching = [p for p in payments if
                (p.get("regularPaymentDetails") or {}).get("providerTransactionId") == provider_transaction_id
                and p.get("status") == "APPROVED"
                and Money.from_wix((p.get("amount") or {}).get("amount")).paise == amount_paise]
    if transactions.get("orderId") != wix_order_id or len(matching) != 1:
        raise WixWritebackPending("Wix payment response requires reconciliation")
    side_effect_guard.confirm(
        table, order_id=order_id, effect=side_effect_guard.WIX_PAYMENT,
        result=binding, key_attr=key_attr)
    logger.info('{"event":"wix_payment_recorded"}')
    return {"recorded": True}


def _paise_to_decimal_string(amount_paise: int) -> str:
    """Integer paise -> a decimal-rupees string, without float arithmetic.

    Wix wants a money string. Integer division keeps the paise exact — `0.1 + 0.2` never enters
    the payment path.
    """
    return Money(amount_paise).to_wix()


# ── the Wix order payload, built once from the frozen quote ────────────────────

#: Our convenience fee as it travels onto a Wix order. The code and the label are OURS: the fee
#: is this application's, not Wix's, and `additionalFees[]` is the only writable place an order
#: can account for it. `PriceSummary.totalAdditionalFees` is what Wix sums.
CONVENIENCE_FEE_CODE = "WD-CONVENIENCE"
CONVENIENCE_FEE_NAME = "Convenience fee"

#: Set on a payload whose line-item detail had to be trimmed to fit the attempt row. A reduced
#: payload is NOT sendable - it has lost its catalog references - so `finalization.accept_paid`
#: refuses it rather than creating a Wix order from it.
PAYLOAD_REDUCED_FLAG = "lineItemsReduced"


def _relayed_money(prices: Mapping[str, Any], key: str) -> Dict[str, str]:
    """One Wix money component, RELAYED verbatim rather than recomputed.

    `Money.from_wix` is called for its refusal, not its value: it raises unless the string is an
    exact decimal, so a malformed component fails here instead of becoming a wrong order total.
    The string itself is passed through untouched, which is what makes "relayed" literally true
    - there is one number and both sides read it.
    """
    raw = (prices.get(key) or {}).get("amount")
    Money.from_wix(raw)
    return {"amount": raw}


def _paise_money(amount_paise: int) -> Dict[str, str]:
    """Integer paise -> a Wix money object, through `Money.to_wix` and never through a float."""
    if isinstance(amount_paise, bool) or type(amount_paise) is not int:
        raise TypeError("a money component must be an int of minor units")
    return {"amount": Money(amount_paise).to_wix()}


def build_wix_order_payload(*, cart: Mapping[str, Any], quote: Any,
                            coupon: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The Create Order payload for a verified-paid order, built from the FROZEN quote.

    `cart` is the Cart V2 Calculate Cart result - `{"cart": ..., "summary": ...}`, which is a
    subset of what `cart_v2.CartV2.calculate` returns, so the same call shape serves production
    and the fixtures. `quote` is the `CheckoutQuote` the price was quoted from.

    NOTHING HERE RECOMPUTES A PRICE, and that is the whole contract. Wix's own components
    (subtotal, discount, delivery, tax) are relayed verbatim from the calculation the customer
    was quoted against; the payable total is `quote.total_payable_paise`, the one figure the
    customer agreed to and the one Razorpay captured. A fresh calculation here could drift from
    the charge by a paise, and a one-paise drift on this path is an order whose total does not
    reconcile with its payment.

    `appliedDiscounts[]` is DELIBERATELY OMITTED. That is SEAM-C2 and it belongs to the coupon
    workstream (`.agents/tasks/wix-coupons-giftcards-20261001/`), which owns the relay of
    `priceSummary.discount` onto the order. `coupon` is accepted so the signature this function
    is already looked up by does not have to change when that work lands, and is ignored here.

    `priceSummary` is `readOnly: true` on Create Order, so what we send there is informational
    and Wix recomputes it from the writable fields. It is sent anyway because it is the record of
    what the payload was built to mean.

    HONEST LIMIT: the line-item and shipping shapes below are relays of the cart's own data onto
    the Order API's documented paths, and have never been exercised against a live Create Order
    call - nothing in this build sends this payload, because `is_enabled()` is false on all four
    of its conditions. Treat them as unverified until the first real write.
    """
    if getattr(quote, "currency", "") != "INR":
        # Compared explicitly, never inferred from an amount.
        raise ValueError("only INR orders can be built")
    summary = cart.get("summary") or {}
    cart_body = cart.get("cart") or {}
    prices = summary.get("priceSummary") or {}

    fee_paise = quote.convenience_fee_paise
    gst_paise = quote.convenience_gst_paise
    # Integer addition on two integer-paise figures the calculator already reconciled against
    # `total_payable_paise`. No float, no rounding, nothing re-derived.
    fee_with_tax_paise = fee_paise + gst_paise

    # Wix's own additional fees are relayed first, then ours is appended. Relaying them matters:
    # they are inside `collection_before_convenience_paise`, so dropping them would leave the
    # order short by exactly their value.
    additional_fees = [deepcopy(entry) for entry in (summary.get("additionalFees") or [])
                       if isinstance(entry, Mapping)]
    additional_fees.append({
        "code": CONVENIENCE_FEE_CODE,
        "name": CONVENIENCE_FEE_NAME,
        # All three price fields, because `totalAdditionalFees` is what Wix sums and nothing
        # documents which of them it derives from. `priceBeforeTax` is the fee; `price` and
        # `priceAfterTax` are the fee plus its GST.
        "price": _paise_money(fee_with_tax_paise),
        "priceBeforeTax": _paise_money(fee_paise),
        "priceAfterTax": _paise_money(fee_with_tax_paise),
    })
    total_additional_paise = sum(
        Money.from_wix((entry.get("price") or {}).get("amount")).paise
        for entry in additional_fees)

    calculated_lines = {str(line.get("lineItemId")): line
                        for line in (summary.get("lineItems") or [])
                        if isinstance(line, Mapping)}
    line_items = []
    for item in cart_body.get("lineItems") or []:
        if not isinstance(item, Mapping):
            continue
        calculated = calculated_lines.get(str(item.get("id"))) or {}
        line_items.append({
            "catalogReference": deepcopy((item.get("source") or {}).get("catalogReference") or {}),
            "productName": deepcopy(item.get("name") or {}),
            "quantity": int((item.get("quantityInfo") or {}).get("confirmedQuantity")
                            or calculated.get("quantity") or 0),
            "price": deepcopy(calculated.get("unitPrice") or {}),
            "totalPriceAfterTax": deepcopy(calculated.get("totalPrice") or {}),
        })

    delivery = cart_body.get("deliveryInfo") or {}
    payload: Dict[str, Any] = {
        "currency": "INR",
        "lineItems": line_items,
        "additionalFees": additional_fees,
        "priceSummary": {
            # Relayed, so the order side cannot have re-derived the pre-discount figure.
            "subtotal": _relayed_money(prices, "subtotal"),
            "discount": _relayed_money(prices, "discount"),
            "delivery": _relayed_money(prices, "delivery"),
            "tax": _relayed_money(prices, "tax"),
            "totalAdditionalFees": _paise_money(total_additional_paise),
            # The one figure that is ours: what the customer agreed to pay and what was captured.
            "total": _paise_money(quote.total_payable_paise),
        },
        "shippingInfo": {
            "title": str((delivery.get("method") or {}).get("title") or ""),
            "logistics": {"shippingDestination": {
                "address": deepcopy(delivery.get("address") or {})}},
        },
    }
    return payload


def mark_cart_completed(table: Any, wix_request: Callable[..., Dict[str, Any]], *,
                        order_id: str, cart_id: str, wix_order_id: str,
                        key_attr: str = "orderId") -> Dict[str, Any]:
    """Close the Cart V2 cart behind a verified-paid, externally-created order. Idempotent.

    The last step of the external-order recording sequence: Orders API Create Order, Order
    Transactions Add Payments, then Cart V2 Mark Cart As Completed. The repo did the first two and
    not the third, so a paid cart was never closed and stayed live for the customer.

    It cannot charge. `mark-as-completed` sets `orderPlaced` and attaches the order id; it moves
    no money and exposes no payment surface. Cart V2's **Place Order** is the one that can enter
    Wix payment collection, and it is deliberately absent from `ALLOWED_ENDPOINTS` and from
    `cart_v2.CartV2` entirely.

    Guarded by its own `WIX_CART_COMPLETED` side effect rather than sharing `WIX_ORDER`: a timeout
    here is ambiguous about the CART, and folding it into the order's marker would make an
    unresolved completion look like an unresolved order creation and invite a second order.

    Returns `{"completed": bool}` — `False` when a previous call already completed it.
    """
    if not is_enabled():
        raise WixWritebackDisabled("Wix write-back is not enabled for this site")
    if not order_id:
        raise ValueError("order_id is required")
    if not wix_order_id:
        # Completing a cart with no order to attach would lose the link between the two, and the
        # cart is the only place that link is recorded on the Wix side.
        raise ValueError("wix_order_id is required to complete a cart")
    try:
        from lambda_utils.ecommerce.cart_v2 import identifier
        cart = identifier(cart_id)
    except (ImportError, ValueError, TypeError, AttributeError):
        raise ValueError("a valid Wix cart id is required") from None

    existing = side_effect_guard.resolve(
        table, order_id=order_id, effect=side_effect_guard.WIX_CART_COMPLETED,
        key_attr=key_attr)
    if existing and existing.get("state") == side_effect_guard.DONE:
        return {"completed": False}
    if existing or not side_effect_guard.claim(
            table, order_id=order_id, effect=side_effect_guard.WIX_CART_COMPLETED,
            key_attr=key_attr):
        raise WixWritebackPending("cart completion outcome needs readback before retry")

    _guarded_call(wix_request, method="POST",
                  path=f"/ecom/v2/carts/{cart}/mark-as-completed",
                  body={"orderId": wix_order_id})
    side_effect_guard.confirm(
        table, order_id=order_id, effect=side_effect_guard.WIX_CART_COMPLETED,
        result={"wixCartId": cart}, key_attr=key_attr)
    logger.info('{"event":"wix_cart_completed"}')
    return {"completed": True}


__all__ = [
    "CREATE_ORDER",
    "ADD_PAYMENT",
    "MARK_CART_COMPLETED",
    "ALLOWED_ENDPOINTS",
    "FORBIDDEN_ENDPOINT_MARKERS",
    "WixWritebackDisabled",
    "WixWritebackPending",
    "WixWouldCharge",
    "WixEndpointNotAllowed",
    "is_enabled",
    "create_wix_order",
    "record_external_payment",
    "mark_cart_completed",
    "CONVENIENCE_FEE_CODE",
    "CONVENIENCE_FEE_NAME",
    "PAYLOAD_REDUCED_FLAG",
    "build_wix_order_payload",
]
