"""Wix Cart V2 boundary. No order, checkout redirect, or payment collection calls.

Reference: Wix Cart V2 Calculate Cart and Stores Catalog V3 eCommerce integration.
The request client is injected by wix-store. All prices come from Wix calculation.

WHY V2 AND NOT CHECKOUT V1
--------------------------
Cart V2 unifies Cart V1 and Checkout V1 into one Cart entity, and those two APIs are removed
on 2027-02-01. A Checkout V1 id *is* a V2 cart id, so ids carry across unchanged.
https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/purchase-flow/cart-v2/migration-guide

Two consequences shape everything below:

- **Totals are not stored on the entity.** Checkout V1 kept `priceSummary`, `taxSummary`,
  `payNow` and `payLater` on the checkout; V2 keeps none of them. They come from Calculate
  Cart as `summary.*`, which is why `calculate()` returns a bound snapshot rather than this
  module exposing V1-style total readers.
- **V2 validates where V1 silently adjusted.** Checkout V1 dropped a missing item and
  quietly reduced an over-ordered quantity. V2 answers with explicit `summary.violations`,
  and an `ERROR`-severity violation must block. `calculate()` refusing to quote is that rule,
  not a defect: V1's total was obtainable precisely because nothing validated it.

DELIVERY IS A DEDICATED SURFACE IN V2
-------------------------------------
Checkout V1 carried `shippingInfo.shippingDestination.address` and
`shippingInfo.selectedCarrierServiceOption` on the entity. V2 maps those to
`deliveryInfo.address` (set through Update Cart) and `deliveryInfo.method`, and the mapping
states that the method is set through the dedicated Set Delivery Method call. Set Delivery
Method and Remove Delivery Method are both new in V2 with no V1 equivalent.
https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/purchase-flow/cart-v2/migration-mapping

WHAT THIS MODULE REFUSES TO BE ABLE TO DO
-----------------------------------------
There is no Place Order, no Mark Cart As Completed, no Get Checkout URL and no redirect
session here, and that is structural rather than an omission. Place Order is the V2
replacement for Checkout V1's Create Order and can enter Wix payment collection; this
architecture collects through Razorpay and records the order afterwards. A method that can
charge must not exist on the adapter a customer-facing route holds, so the guarantee is "the
code is absent", which a test can enumerate, instead of "the code is guarded".
"""
from copy import deepcopy

from .money import Money, positive_paise
# The provider-neutral cart contract lives in cart_contract.py so native code can depend on it
# without importing this Wix adapter. Re-exported here for backward compatibility with existing
# `cart_v2.<name>` importers.
from .cart_contract import (  # noqa: F401
    ADDRESS_FIELDS,
    CartContractError,
    CartGone,
    CartItemUnavailable,
    CartQuantityReduced,
    REQUIRED_ADDRESS_FIELDS,
    STORES_APP_ID,
    available_delivery_options,
    catalog_item,
    cheapest_delivery_option,
    delivery_address,
    identifier,
)

BASE = "/ecom/v2/carts"

#: Truthy spellings accepted for either gate key, matching the rest of the fleet.
_TRUTHY = ("1", "true", "yes", "on")

#: The opt-IN key. Cart V2 serves only when this is truthy. Absent means off.
ENABLE_KEY = "WIX_CART_V2_ENABLED"

#: A kill switch layered ON TOP of the opt-in, never instead of it. Set it to turn V2 off
#: without having to find and unset `WIX_CART_V2_ENABLED` on every function that carries it.
DISABLE_KEY = "WIX_CART_V2_DISABLED"


def is_not_found(error):
    """Whether a transport failure is specifically HTTP 404.

    Reads a STRUCTURED status and never a substring of the message: `wix_ecom.http_error` attaches
    `.status` from `urllib.error.HTTPError.code`, and `.code` is checked too so a raw urllib error
    from some other transport is understood as well. A money path must not branch on prose.

    Anything without a readable status answers False, which fails CLOSED: an unknown failure keeps
    today's behaviour (it propagates) rather than being optimistically treated as "the cart is
    gone" and triggering a cart creation.
    """
    for attribute in ("status", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and value == 404:
            return True
    return False


def is_enabled(env=None):
    """Whether the Cart V2 path serves. **Opt-in**: absent means off.

    ABSENCE MUST MEAN OFF, AND THAT IS THE WHOLE RULE HERE. An earlier revision inverted this
    into a `WIX_CART_V2_DISABLED` opt-out so that V2 became the default. Measured against the
    fleet, neither key is set on any function, so "default on" did not mean an operator had
    chosen V2 -- it meant V2 would switch itself on at the next routine deploy, with no
    environment change and nobody's decision. Turning on a path that performs live Create Cart
    and Add Line Items writes, and that is the price authority for a payable amount, is an
    operator action. A flag whose safety depends on nobody having deployed yet is not a flag.

    `WIX_CART_V2_DISABLED` is kept as an override *on top of* the opt-in, not as a replacement
    for it: with the key set, V2 stays off even where `WIX_CART_V2_ENABLED=true` is already
    deployed, so the rollback lever is still one environment variable rather than a code change.
    Both keys absent is the configuration of every function today, and it answers `False`.

    One function, shared by the customer cart route and the checkout handler, so the two cannot
    disagree about whether V2 serves.
    """
    import os
    environ = os.environ if env is None else env
    if str(environ.get(DISABLE_KEY, "")).strip().lower() in _TRUTHY:
        return False
    return str(environ.get(ENABLE_KEY, "")).strip().lower() in _TRUTHY


class CartV2:
    def __init__(self, request):
        self.request = request

    def _cart(self, response, expected_id=None):
        cart = response.get("cart") if isinstance(response, dict) else None
        if not isinstance(cart, dict) or not cart.get("revision"):
            raise CartContractError("missing cart or revision")
        identifier(cart.get("id"))
        if expected_id and cart["id"] != expected_id:
            raise CartContractError("cart identity mismatch")
        if cart.get("orderPlaced") or cart.get("orderId"):
            raise CartContractError("cart is already completed")
        return cart

    def create(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("create requires 1 to 100 catalog items")
        return self._cart(self.request(BASE, method="POST", body={
            "catalogItems": [catalog_item(item) for item in items]}))

    def get(self, cart_id):
        """Read the cart. A 404 here is `CartGone`, never an item problem. See `CartGone`.

        THIS IS THE ONLY CALL THAT NEEDS THE DISTINCTION, and that is measured rather than
        assumed: every path that reuses a persisted cart id touches it through `get` FIRST -- the
        stale-delivery check, the basket-equality backstop and the reconcile diff all start here --
        so a cart Wix no longer has is discovered on this call and on no other. The add/remove/
        calculate endpoints are only reached once this one has answered, i.e. once the cart has
        been proven to exist a moment earlier.
        """
        cart_id = identifier(cart_id)
        try:
            response = self.request(f"{BASE}/{cart_id}")
        except Exception as error:          # noqa: BLE001 -- re-raised unless it is a 404
            if is_not_found(error):
                raise CartGone("the wix cart no longer exists", cart_id) from None
            raise
        return self._cart(response, cart_id)

    def add(self, cart_id, item):
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/add-line-items", method="POST",
                         body={"catalogItems": [catalog_item(item)]}), cart_id)

    def set_quantity(self, cart_id, line_id, quantity):
        if type(quantity) is not int or not 1 <= quantity <= 100000:
            raise ValueError("quantity must be a positive integer")
        cart_id, line_id = identifier(cart_id), identifier(line_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/update-line-items", method="POST",
                         body={"lineItems": [{"lineItemId": line_id,
                                             "quantity": {"newQuantity": quantity}}]}), cart_id)

    def remove(self, cart_id, line_id):
        cart_id, line_id = identifier(cart_id), identifier(line_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/remove-line-items", method="POST",
                         body={"lineItemIds": [line_id]}), cart_id)

    def refresh(self, cart_id):
        """Refresh Cart: re-evaluate prices, inventory and discounts. New in V2.

        Checkout V1's "Get Checkout with refresh" maps here. `calculate()` already passes
        `refreshCart`, so this exists for the case where a caller wants the re-evaluation
        without asking for a quote -- for example after a catalogue change, where forcing a
        quote would be the wrong shape of question.
        """
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/refresh", method="POST",
                                       body={}), cart_id)

    def set_delivery_address(self, cart_id, address):
        """Write `deliveryInfo.address` through Update Cart.

        Checkout V1 carried this as `shippingInfo.shippingDestination.address`; the V2 mapping
        moves it to `deliveryInfo.address`. Only the address is sent -- this never touches
        `businessInfo`, `paymentInfo` or line items, so it cannot change a currency or a price
        on the way past.

        The address is validated by `delivery_address` first. There is no default and no
        placeholder, deliberately: in India the delivery address is the place of supply, so a
        made-up address yields a real total with the wrong CGST/SGST-versus-IGST split, and
        that total is what a customer would be charged. An honest refusal is the cheaper
        failure.
        """
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}", method="PATCH", body={
            "cart": {"deliveryInfo": {"address": delivery_address(address)}}}), cart_id)

    def delivery_options(self, cart_id):
        """Every delivery option Wix currently offers for this cart's address.

        A list of `{"id", "title", "pricePaise"}`, cheapest first, or `[]` when Wix offers
        nothing for the address on the cart. `id` is what `set_delivery_method` takes.

        THE FIELD IS `summary.deliverySummary`, AND IT WAS MEASURED RATHER THAN GUESSED. The
        module's own `_not_payable` used to say the enumerating field "could not be confirmed
        from a fetchable reference page". A live probe against the confirmed site on 2026-10-04
        settles it, and the answer has a shape worth stating plainly:

            summary.deliverySummary.method = {"code", "appId", "title": {"original", ...},
                                              "pickup"}
            summary.deliverySummary.price  = {"amount": "0.00", ...}

        Cart V2 reports ONE resolved method here, not a menu -- `deliverySummary.method` is
        populated for a cart whose `deliveryInfo.method` is still null and whose summary still
        carries the `MISSING_DELIVERY_METHOD` violation. So Wix has already decided which option
        applies to this cart and address; it just has not been selected. There is no V2
        list-options endpoint (`delivery-options`, `list-delivery-options`,
        `get-delivery-options`, `shipping-options` and `delivery-methods` all answer 404).

        The retired V1 entity's `shippingInfo.carrierServiceOptions[]` DOES enumerate every
        carrier, and a V1 id is a V2 cart id, so reading the old entity would return the full
        menu. It is deliberately not read: V1 is removed on 2027-02-01, and on the live site it
        returns two carriers with one of them carrying an EMPTY `code`, which is not a value
        `set_delivery_method` can send. Wix's own resolution is the better authority.

        The return type is still a LIST, with one entry or none. A single-value reader would have
        to change shape if Wix ever enumerates here, and the caller's "exactly one option" and
        "no options" branches are the two that matter either way.
        """
        return self.preview(cart_id)["deliveryOptions"]

    def set_delivery_method(self, cart_id, option_id):
        """Set Delivery Method. New in V2, with no Cart V1 or Checkout V1 equivalent.

        `option_id` identifies a shipping option Wix itself offered for this cart and address --
        `summary.deliverySummary.method.code`, which `delivery_options` returns as `id`. It is an
        identifier, never a price: the delivery charge that follows is whatever `calculate()`
        reports in `summary.priceSummary.delivery`, and a caller cannot influence it. That is the
        same rule `catalog_item` applies to line items.

        THE REQUEST BODY IS `{"deliveryMethod": {"code": ...}}`, MEASURED LIVE. It was
        `{"deliveryMethodId": option_id}`, which Wix answers with HTTP 400 and the field
        violation `deliveryMethod / must not be empty / REQUIRED_FIELD` -- so this method could
        never have selected anything, and every physical checkout that reached it would still
        have been refused with `MISSING_DELIVERY_METHOD`. `appId` is NOT sent: `code` alone is
        accepted, and the selection clears the violation (verified 2026-10-04 against the
        confirmed site, cart + West Bengal address + the live Rs.1 product).
        """
        if not isinstance(option_id, str) or not option_id.strip() or len(option_id) > 200:
            raise ValueError("a delivery option id is required")
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/set-delivery-method", method="POST",
                                       body={"deliveryMethod": {"code": option_id.strip()}}),
                          cart_id)

    def remove_delivery_method(self, cart_id):
        """Remove Delivery Method. New in V2.

        Present so a selected method can be withdrawn when the address changes, rather than a
        stale method surviving into a quote for a different destination.
        """
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/remove-delivery-method",
                                       method="POST", body={}), cart_id)

    def add_coupon(self, cart_id, code):
        """Add Coupon. New in V2 as a dedicated method; in V1 the code was inline in create/update.

        A coupon is a DISCOUNT, and it lands in `summary.priceSummary.discount`, not in the
        subtotal -- Cart V2 defines subtotal as line prices after item-level automatic discounts
        but BEFORE cart-level discounts like coupons. So the existing reconciliation,
        `subtotal - discount + delivery + additionalFees + tax == total`, already accounts for it
        and does not need widening.

        Applied SERVER-SIDE only. The code is a claim; Wix decides whether it is valid, what it is
        worth and whether this cart qualifies. A caller cannot supply a discount amount here, and
        the reduced total still arrives from Calculate Cart, so a browser cannot lower what it
        pays by inventing a coupon -- it can only ask for one to be validated.

        One coupon at a time: Cart V2's introduction states a cart supports a single coupon and
        adding a second returns an error.
        https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/purchase-flow/cart-v2/introduction
        """
        if not isinstance(code, str) or not code.strip() or len(code.strip()) > 50:
            raise ValueError("a coupon code is required")
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/add-coupon", method="POST",
                                       body={"coupon": {"code": code.strip()}}), cart_id)

    def remove_coupon(self, cart_id, coupon_id):
        """Remove Coupon. V2 additionally requires the `couponId`, where V1 took only the cart."""
        if not isinstance(coupon_id, str) or not coupon_id.strip():
            raise ValueError("a coupon id is required")
        cart_id = identifier(cart_id)
        return self._cart(self.request(f"{BASE}/{cart_id}/remove-coupon", method="POST",
                                       body={"couponId": coupon_id.strip()}), cart_id)

    def add_gift_card(self, cart_id, code, redeem_amount=None):
        """Apply one Wix-native gift card to this Cart V2 cart.

        Current Wix Cart V2 supports one gift card. The customer supplies a bearer code only;
        Wix owns validity, balance and the calculated redemption. An optional exact decimal
        redeem amount is forwarded only when the server deliberately caps the redemption.
        """
        if not isinstance(code, str) or not 8 <= len(code.strip()) <= 20:
            raise ValueError("gift card code must be 8-20 characters")
        gift_card = {"code": code.strip()}
        if redeem_amount is not None:
            if not isinstance(redeem_amount, str):
                raise ValueError("gift card redeem amount must be an exact decimal string")
            Money.from_wix(redeem_amount)
            gift_card["redeemAmount"] = {"amount": redeem_amount}
        cart_id = identifier(cart_id)
        return self._cart(self.request(
            f"{BASE}/{cart_id}/add-gift-card", method="POST",
            body={"giftCard": gift_card}), cart_id)

    def remove_gift_card(self, cart_id, gift_card_id):
        """Remove a Wix-native gift card by the cart-assigned GUID."""
        gift_card_id = identifier(gift_card_id)
        cart_id = identifier(cart_id)
        return self._cart(self.request(
            f"{BASE}/{cart_id}/remove-gift-card", method="POST",
            body={"giftCardId": gift_card_id}), cart_id)

    def estimate(self, cart_id):
        """A NON-PAYABLE item-subtotal view, for the state before a delivery address exists.

        This is the answer to "what do we show before the customer has chosen where it goes?", and
        Estimate Cart is the method Wix provides for it rather than a workaround. Verified against
        the Cart V2 introduction rather than assumed:

            "Estimate Cart: Performs a partial, component-based estimation controlled by boolean
            flags (calculateDelivery, calculateTax, calculateAdditionalFees, calculateGiftCards).
            Components not explicitly enabled are excluded from the calculation."
            -- https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/purchase-flow/cart-v2/introduction

        All four flags are sent explicitly false. `calculateDelivery` and `calculateTax` are the
        two that need an address, so disabling them is what makes this answerable with no address
        -- which is precisely the pre-address state. `calculateGiftCards` is false because gift
        cards are refused outright on this path (see the module note below), and leaving it off
        keeps a gift-card balance from appearing in a number a customer might read as their price.

        The flags are not parameters. A caller that could switch `calculateDelivery` on would be
        able to obtain a delivery-inclusive figure through the method whose entire contract is
        "this is not your total", and that figure would then be one short conversion away from a
        charge.

        What it deliberately does NOT return: `amountPaise`, `calculationId`,
        `priceVerificationToken`, or anything else that could reach a gateway. The money is named
        `itemSubtotalPaise` because that is all it is. `payable` is always `False`.

        Violations still come back: the introduction says they are returned by both Calculate Cart
        and Estimate Cart, so this is also how the customer learns an item went out of stock before
        they have typed an address.
        """
        cart_id = identifier(cart_id)
        response = self.request(f"{BASE}/{cart_id}/estimate", method="POST", body={
            "calculateDelivery": False, "calculateTax": False,
            "calculateAdditionalFees": False, "calculateGiftCards": False})
        return self._not_payable(response, cart_id)

    def preview(self, cart_id):
        """The same non-payable view, from the FULL calculation.

        Kept separate from `estimate` because the two answer different questions. `estimate` is the
        lightweight pre-address figure; this runs Calculate Cart -- which "always runs
        checkout-level validations" -- and reports what it found without raising, so a caller can
        discover exactly why a cart is not yet payable. `purchase_intent` uses it to tell "no
        delivery address chosen" from "Wix returned something unsafe".
        """
        cart_id = identifier(cart_id)
        response = self.request(f"{BASE}/{cart_id}/calculate", method="POST",
                                body={"refreshCart": True})
        return self._not_payable(response, cart_id)

    def _not_payable(self, response, cart_id):
        """The shared non-payable projection. One shape, so `estimate` and `preview` cannot drift.

        `deliveryInfo` is handed back verbatim, and `deliveryOptions` is the normalised list from
        `summary.deliverySummary` -- the field the live probe on 2026-10-04 confirmed, replacing
        this docstring's previous admission that it was unknown.

        `estimate` sends `calculateDelivery: False`, so its `deliveryOptions` is legitimately
        empty; `preview` runs the full calculation and is the read that answers the question.
        `CartV2.delivery_options` goes through `preview` for exactly that reason.
        """
        cart = self._cart(response, cart_id)
        summary = response.get("summary") or {}
        violations = [v for v in (summary.get("violations") or [])
                      if v.get("severity") != "WARNING"]
        prices = summary.get("priceSummary") or {}
        subtotal = Money.from_wix((prices.get("subtotal") or {}).get("amount")).paise
        return {"payable": False, "wixCartId": cart_id, "cartRevision": cart["revision"],
                "currency": "INR", "itemSubtotalPaise": subtotal,
                "blockingViolations": deepcopy(violations),
                "coupons": deepcopy(cart.get("coupons") or []),
                "deliveryInfo": deepcopy(cart.get("deliveryInfo") or {}),
                "deliveryOptions": available_delivery_options(summary),
                "items": [{"lineItemId": item.get("id"),
                           "requestedQuantity": (item.get("quantityInfo") or {}).get(
                               "requestedQuantity"),
                           "quantity": (item.get("quantityInfo") or {}).get("confirmedQuantity"),
                           "status": item.get("status")}
                          for item in (cart.get("lineItems") or [])]}

    def calculate(self, cart_id):
        cart_id = identifier(cart_id)
        response = self.request(f"{BASE}/{cart_id}/calculate", method="POST",
                                body={"refreshCart": True})
        cart = self._cart(response, cart_id)
        summary = response.get("summary") or {}
        if (summary.get("cartId") != cart_id or
                summary.get("cartRevision") != cart["revision"] or
                not summary.get("calculationId") or not summary.get("priceVerificationToken") or
                not cart.get("purchaseFlowId")):
            raise CartContractError("incomplete calculation binding")
        for field in ("businessInfo", "customerInfo", "paymentInfo"):
            if (cart.get(field) or {}).get("currencyCode") != "INR":
                raise CartContractError("all cart currencies must be INR")
        if any((summary.get("calculationErrors") or {}).values()) or summary.get("spiViolations"):
            raise CartContractError("calculation has unresolved legacy errors")
        if cart.get("demo"):
            raise CartContractError("demo cart cannot be paid")
        items = cart.get("lineItems") or []
        if not items:
            raise CartContractError("empty cart")
        # ITEM AVAILABILITY AND QUANTITY ARE CHECKED BEFORE THE GENERAL VIOLATIONS CHECK, AND THE
        # ORDER IS THE POINT. An out-of-stock cart carries an ERROR violation too, so checking
        # violations first would collapse "this item is gone" into the same generic refusal as
        # "no delivery address chosen" -- and those need different things from the customer. The
        # specific diagnosis has to come first to survive.
        unavailable = [{"lineItemId": item.get("id"), "status": item.get("status")}
                       for item in items if item.get("status") != "IN_STOCK"]
        if unavailable:
            raise CartItemUnavailable(
                "one or more items are not available at the requested quantity", unavailable)
        reduced = []
        for item in items:
            quantities = item.get("quantityInfo") or {}
            requested, confirmed = (quantities.get("requestedQuantity"),
                                    quantities.get("confirmedQuantity"))
            if type(requested) is not int or requested < 1:
                raise CartContractError("line item has no usable requested quantity")
            if requested != confirmed:
                reduced.append({"lineItemId": item.get("id"),
                                "requestedQuantity": requested,
                                "confirmedQuantity": confirmed})
        if reduced:
            raise CartQuantityReduced(
                "Wix confirmed fewer units than were requested", reduced)
        if any(v.get("severity") != "WARNING" for v in summary.get("violations", [])):
            raise CartContractError("cart has blocking or unknown violations")
        for item in items:
            source = item.get("source") or {}
            reference = source.get("catalogReference") or {}
            if (item.get("customLineItem") or source.get("catalogOverrideFields") or
                    reference.get("appId") != STORES_APP_ID or
                    not (reference.get("options") or {}).get("variantId") or
                    (item.get("pricing") or {}).get("priceUndetermined") or
                    (item.get("paymentConfig") or {}).get("paymentOption") != "FULL_PAYMENT_ONLINE"):
                raise CartContractError("unsupported or unavailable catalog item")
        prices = summary.get("priceSummary") or {}
        components = {key: Money.from_wix((prices.get(key) or {}).get("amount")).paise
                      for key in ("subtotal", "discount", "delivery", "additionalFees", "tax", "total")}
        total = positive_paise(components["total"])
        lines = summary.get("lineItems") or []
        expected_quantities = {item["id"]: item["quantityInfo"]["confirmedQuantity"] for item in items}
        calculated_quantities = {line.get("lineItemId"): line.get("quantity") for line in lines}
        if (len(lines) != len(items) or len(expected_quantities) != len(items) or
                calculated_quantities != expected_quantities or
                sum(Money.from_wix((line.get("totalPrice") or {}).get("amount")).paise
                    for line in lines) != components["subtotal"]):
            raise CartContractError("line calculation differs from cart")
        if (components["subtotal"] - components["discount"] + components["delivery"] +
                components["additionalFees"] + components["tax"] != total):
            raise CartContractError("price components do not match the total")
        payment = summary.get("paymentSummary") or {}
        # Membership/subscription/deferred rails remain outside website checkout. A Wix-native
        # gift card is the one supported split: Wix calculates the redemption and Razorpay
        # collects only the remaining external leg plus WECARE's fee/GST added downstream.
        if any(payment.get(key) for key in ("memberships", "subscriptionCharges")):
            raise CartContractError("membership or subscription payment is not supported")
        for field in ("payLater", "payAfterFreeTrial"):
            if field in payment and Money.from_wix((payment.get(field) or {}).get("amount")).paise:
                raise CartContractError("deferred payment is not supported")

        gift_cards = payment.get("giftCards") or []
        if not isinstance(gift_cards, list) or len(gift_cards) > 1:
            raise CartContractError("only one Wix gift card is supported")
        pay_now = Money.from_wix((payment.get("payNow") or {}).get("amount")).paise
        after_cards = Money.from_wix(
            (payment.get("totalAfterGiftCards") or {}).get("amount")).paise
        wix_gift_card = None
        if gift_cards:
            gift = gift_cards[0] if isinstance(gift_cards[0], dict) else {}
            gift_id = identifier(gift.get("giftCardId"))
            redeem = Money.from_wix((gift.get("redeemAmount") or {}).get("amount")).paise
            if redeem <= 0 or redeem > total:
                raise CartContractError("gift card redemption is outside the cart total")
            if pay_now != total - redeem or after_cards != pay_now:
                raise CartContractError("gift card payment split does not reconcile")
            expected_requires = pay_now > 0
            if payment.get("requiresPaymentAfterGiftCard") is not expected_requires:
                raise CartContractError("gift card payment requirement does not match the remainder")
            cart_cards = ((cart.get("paymentInfo") or {}).get("giftCards") or [])
            if len(cart_cards) != 1 or str(cart_cards[0].get("id") or "") != gift_id:
                raise CartContractError("gift card calculation is not bound to the cart")
            wix_gift_card = {
                "giftCardId": gift_id,
                "redeemPaise": redeem,
                "obfuscatedCode": str(cart_cards[0].get("obfuscatedCode") or ""),
                "appId": str(cart_cards[0].get("appId") or ""),
            }
        else:
            if pay_now != total or after_cards != total:
                raise CartContractError("full immediate payment required")
            if payment.get("requiresPaymentAfterGiftCard") not in (None, True):
                raise CartContractError("payment requirement conflicts with the cart total")

        delivery = cart.get("deliveryInfo") or {}
        return {"wixCartId": cart_id, "cartRevision": cart["revision"],
                "purchaseFlowId": cart["purchaseFlowId"],
                "calculationId": summary["calculationId"],
                "priceVerificationToken": summary["priceVerificationToken"],
                "amountPaise": total, "currency": "INR", "componentsPaise": components,
                "wixGiftCard": wix_gift_card,
                "wixGiftCardRedeemPaise": int(wix_gift_card["redeemPaise"]) if wix_gift_card else 0,
                "wixPayNowPaise": pay_now,
                # Frozen alongside the amount because they are part of WHY it is that amount:
                # delivery is a component of the total and the address is the place of supply.
                # `build_snapshot` hashes both, so a changed address yields a different intent
                # rather than silently reusing a quote computed for somewhere else.
                "deliveryAddress": deepcopy(delivery.get("address") or {}),
                "deliveryMethod": deepcopy(delivery.get("method") or {}),
                "cart": deepcopy(cart), "summary": deepcopy(summary)}
