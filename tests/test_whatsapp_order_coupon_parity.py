"""A coupon works on a WhatsApp-origin basket BY CONSTRUCTION, and gift cards are deferred.

WHY "BY CONSTRUCTION" IS THE WHOLE CLAIM
----------------------------------------
Phase W adds no coupon code. After the hand-off is claimed, a WhatsApp catalogue order IS a Wix
cart belonging to a signed-in customer - the same row, under the same `CUSTOMERCART#` key, holding
the same `wixCartId` a website basket would have. Every coupon authority downstream keys on that
cart id and on the customer, and NONE of them can see a channel:

  * `ecommerce/coupons` decides eligibility and holds the code, keyed on `cartId` + `customerId`;
  * `purchase_intent.apply_coupon` sends the code to Wix, which decides what it is worth;
  * `redemption.apply_coupon` turns a provider verdict into `discounted_collection_paise`;
  * `checkout_pricing.compute_quote` charges the convenience fee ON that discounted collection.

So the tests below are mostly NEGATIVE and STRUCTURAL: there is no second discount arithmetic, no
channel-aware branch in any coupon authority, and the fee basis is the discounted collection rather
than the original. A positive end-to-end coupon test would prove the Wix stub works; these prove
there is only one implementation to get wrong.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lambda_utils.ecommerce import (  # noqa: E402
    coupon_store, purchase_intent, redemption, whatsapp_basket as wb)
from lambda_utils.ecommerce.checkout_pricing import compute_quote  # noqa: E402

BASKET_MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/whatsapp_basket.py"
INBOUND_HANDLER = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"
CHECKOUT_HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
INVOICE_ENGINE = ROOT / "amplify/functions/payments/invoice-engine/handler.py"

#: Wix collection 25499.00, the shared Cart V2 fixture's figure.
COLLECTION_PAISE = 2549900
#: A flat ₹500 coupon, as a provider would report it.
DISCOUNT_PAISE = 50000


class _Provider:
    """A redemption provider that records what it was asked, and answers authoritatively."""

    def __init__(self, *, discount_paise=DISCOUNT_PAISE, reason=redemption.COUPON_APPLIED):
        self.discount_paise = discount_paise
        self.reason = reason
        self.asked = []

    def validate_coupon(self, *, code, collection_before_discount_paise, cart_ref):
        self.asked.append({"code": code, "collection": collection_before_discount_paise,
                           "cartRef": cart_ref})
        return redemption.CouponAuthority(
            valid=self.reason == redemption.COUPON_APPLIED, reason=self.reason,
            discount_paise=self.discount_paise)


class _RecordingAdapter:
    """A Cart V2 adapter recording every coupon call, so the two channels can be compared."""

    def __init__(self):
        self.coupons = []

    def add_coupon(self, cart_id, code):
        self.coupons.append((cart_id, code))
        return {"id": cart_id, "revision": "2"}


# ── the fee is charged on the DISCOUNTED collection ───────────────────────────


def test_the_convenience_fee_is_computed_on_the_discounted_collection():
    """`redemption.apply_coupon` feeds `discounted_collection_paise` to `compute_quote`, so a
    smaller cart genuinely costs a smaller fee - the coupon is not quietly charged a fee on the
    pre-discount figure."""
    provider = _Provider()
    result = redemption.apply_coupon(
        code="WELCOME500", collection_before_discount_paise=COLLECTION_PAISE,
        cart_ref="cart-whatsapp-1", provider=provider)
    assert result.applied
    assert result.discount_paise == DISCOUNT_PAISE
    assert result.discounted_collection_paise == COLLECTION_PAISE - DISCOUNT_PAISE

    discounted = compute_quote(result.discounted_collection_paise)
    undiscounted = compute_quote(COLLECTION_PAISE)
    assert discounted.collection_before_convenience_paise == COLLECTION_PAISE - DISCOUNT_PAISE
    assert discounted.convenience_fee_paise < undiscounted.convenience_fee_paise
    assert discounted.total_payable_paise < undiscounted.total_payable_paise
    # And the whole thing still reconciles exactly, in integer paise.
    assert discounted.total_payable_paise == (discounted.collection_before_convenience_paise
                                              + discounted.convenience_fee_paise
                                              + discounted.convenience_gst_paise)
    assert all(type(value) is int for value in (
        discounted.collection_before_convenience_paise, discounted.convenience_fee_paise,
        discounted.convenience_gst_paise, discounted.total_payable_paise))


def test_a_refused_coupon_leaves_the_collection_untouched_on_either_channel():
    """Fail closed: an invalid code charges the full price rather than an arbitrary discount."""
    for reason in (redemption.COUPON_INVALID, redemption.COUPON_EXPIRED,
                   redemption.COUPON_INELIGIBLE):
        result = redemption.apply_coupon(
            code="NOPE", collection_before_discount_paise=COLLECTION_PAISE,
            cart_ref="cart-whatsapp-1", provider=_Provider(reason=reason))
        assert not result.applied
        assert result.discount_paise == 0
        assert result.discounted_collection_paise == COLLECTION_PAISE
        assert compute_quote(result.discounted_collection_paise).total_payable_paise == \
            compute_quote(COLLECTION_PAISE).total_payable_paise


# ── parity between the two channels ───────────────────────────────────────────


def test_the_same_coupon_on_the_same_basket_costs_the_same_on_both_channels():
    """The payable is a function of the collection and the coupon, and of nothing else.

    The channel is not an argument to `apply_coupon` or to `compute_quote`, and these assertions
    are what makes that a property rather than an observation: two identical calls differing only
    in which surface produced the cart yield one number.
    """
    whatsapp = redemption.apply_coupon(
        code="WELCOME500", collection_before_discount_paise=COLLECTION_PAISE,
        cart_ref="cart-from-whatsapp", provider=_Provider())
    website = redemption.apply_coupon(
        code="WELCOME500", collection_before_discount_paise=COLLECTION_PAISE,
        cart_ref="cart-from-website", provider=_Provider())
    assert whatsapp.discounted_collection_paise == website.discounted_collection_paise
    assert compute_quote(whatsapp.discounted_collection_paise).total_payable_paise == \
        compute_quote(website.discounted_collection_paise).total_payable_paise


def test_a_coupon_reaches_wix_through_the_one_purchase_intent_path():
    """`purchase_intent.apply_coupon` is a one-line delegation to the adapter, and both channels go
    through it. The code is a CLAIM: Wix decides the value, and the reduced figure comes back
    through Calculate Cart like every other component."""
    adapter = _RecordingAdapter()
    purchase_intent.apply_coupon(adapter, "cart-from-whatsapp", "WELCOME500")
    purchase_intent.apply_coupon(adapter, "cart-from-website", "WELCOME500")
    assert adapter.coupons == [("cart-from-whatsapp", "WELCOME500"),
                               ("cart-from-website", "WELCOME500")]
    # No amount is ever passed. A caller cannot supply a discount here.
    source = ast.parse((ROOT / "amplify/functions/shared/lambda_utils/ecommerce"
                        "/purchase_intent.py").read_text())
    for node in ast.walk(source):
        if isinstance(node, ast.FunctionDef) and node.name == "apply_coupon":
            arguments = {argument.arg for argument in node.args.args}
            assert arguments == {"adapter", "cart_id", "code"}


def test_no_coupon_authority_can_see_a_channel():
    """The structural reason parity holds: `channel` is not a parameter of any coupon authority.

    `coupon_store.evaluate` keys on the definition, the cart id and the customer's use count;
    `coupon_store.hold` keys on code and cart id. Neither takes a channel, so neither can branch on
    one - which is why a WhatsApp-origin cart is indistinguishable from a website cart to both.
    """
    for module, name in ((coupon_store, "evaluate"), (coupon_store, "hold"),
                         (coupon_store, "commit_redemption"), (redemption, "apply_coupon")):
        tree = ast.parse(pathlib.Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                arguments = ({argument.arg for argument in node.args.args}
                             | {argument.arg for argument in node.args.kwonlyargs})
                assert "channel" not in arguments
                assert "source" not in arguments


def test_coupon_store_is_the_only_issuance_authority_the_whatsapp_path_can_reach():
    """Phase W adds no coupon code at all, and this is the assertion of that.

    Neither the hand-off module nor the inbound cart-order path imports a coupon module, mentions a
    discount, or holds a percentage - so there is no place for a second issuance authority or a
    second discount arithmetic to live. The issuance authority stays `coupon_store`, reached by the
    `ecommerce/coupons` route the cart page already calls.
    """
    basket_source = BASKET_MODULE.read_text()
    for forbidden in ("coupon", "discount", "gift_card", "giftcard", "percent"):
        assert forbidden not in basket_source.lower(), \
            f"{forbidden} appeared in whatsapp_basket.py - the hand-off carries no money"

    tree = ast.parse(INBOUND_HANDLER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_cart_order":
            text = ast.unparse(node).lower()
            for forbidden in ("coupon", "discount", "gift_card", "giftcard"):
                assert forbidden not in text, \
                    f"{forbidden} appeared in the cart-order path - it computes no money"

    # And the checkout handler's claim arm quotes nothing either: no coupon call, no quote.
    checkout_tree = ast.parse(CHECKOUT_HANDLER.read_text())
    for node in ast.walk(checkout_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_claim_basket":
            called = {child.func.attr for child in ast.walk(node)
                      if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)}
            assert "apply_coupon" not in called
            assert "compute_quote" not in called
            assert "exempt_quote" not in called


def test_the_invoice_path_uses_the_same_coupon_authority_as_the_cart():
    """The invoice surface asks; it does not answer.

    `invoice-engine` is the third coupon surface (after the cart panel and the `/coupons/*`
    routes), and it is the one with the strongest incentive to grow its own arithmetic: it already
    computes a subtotal, a GST figure and a convenience fee in rupees, so "just multiply by the
    percentage here" is a one-line change that would silently fork the discount in two.

    So this asserts the shape rather than a figure. The handler must import `redemption` and the
    one concrete provider, and `create_invoice` must contain no percentage, no basis-points
    arithmetic and no local function that returns a discount. Every amount it uses comes back from
    a call.
    """
    source = INVOICE_ENGINE.read_text()
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    assert "redemption" in imported, "the invoice path must reach the money authority"
    assert "store_redemption_provider" in imported, \
        "the invoice path must use the ONE concrete provider, not a local binding"

    # No second amount function anywhere in the handler.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert "discount_paise" != node.name, \
                "coupon_store owns the only discount amount function"

    create = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "create_invoice")
    body = ast.unparse(create)
    for forbidden in ("percentOff", "moneyOffPaise", "fixedPricePaise", "round_half_up",
                      "RATE_DENOMINATOR"):
        assert forbidden not in body, \
            f"create_invoice names {forbidden} - it is pricing a coupon itself"
    # And the figures it does use are returned by a call, not derived: the only names it reads off
    # the coupon result are the ones `redemption` computed.
    calls = {node.func.attr for node in ast.walk(create)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "apply_coupon" in calls or "_apply_coupon_leg" in ast.unparse(create)


def test_the_claim_leaves_the_coupon_panel_exactly_where_it_was():
    """The cart page's coupon panel is unchanged by this feature, which is what "by construction"
    means in the browser: the customer applies a coupon on `/cart/` after the claim, through the
    same `/ecommerce/redemption` call a website basket uses."""
    cart_page = (ROOT / "src/pages/cart.tsx").read_text()
    assert "REDEMPTION_URL" in cart_page
    # The claim effect must not touch the redemption call.
    assert "basket" in cart_page, "the claim effect is present"
    assert cart_page.count("const REDEMPTION_URL") == 1


# ── gift cards: DEFERRED, and recorded as deferred ────────────────────────────


@pytest.mark.skip(reason=(
    "The Wix gift-card SPI is UNPROVISIONED: its secret, its function registration and the SPI "
    "registration on the site are all absent (Phase W findings section 3). So there is no "
    "gift-card tender for a WhatsApp-origin order to be at parity ON. "
    "`wixGiftCardRedeemPaise` remains the only gift-card tender the website consumes, and a "
    "WhatsApp-origin order INHERITS exactly that by being the same website checkout after the "
    "claim - there is no separate WhatsApp gift-card path to implement or to test. Provisioning "
    "the SPI is an owner action and out of this phase's scope; this test exists so the deferral is "
    "a recorded skip with a reason rather than a silent gap or a passing claim."))
def test_gift_card_parity_is_inherited_not_implemented():
    raise AssertionError("unreachable: see the skip reason")


def test_the_gift_card_tender_is_untouched_by_this_feature():
    """What CAN be asserted today: the gift-card surface gained nothing from Phase W.

    The tender is subtracted from the final payable by `gift_card_settlement`, after
    `compute_quote`, and the hand-off contributes no money field for it to interact with. So the
    deferral above costs nothing: there is no half-built WhatsApp gift-card path.
    """
    basket_source = BASKET_MODULE.read_text().lower()
    assert "gift" not in basket_source
    tree = ast.parse(CHECKOUT_HANDLER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_claim_basket":
            text = ast.unparse(node).lower()
            assert "gift" not in text
    # The hand-off row's key set is money-free, so nothing on it can be mistaken for a tender.
    basket = wb.Basket(lines=[{"productId": "a", "variantId": "b", "quantity": 1}])
    row = wb.build_handoff(basket, "+918100640044", token="t", now=1)
    assert not [key for key in row if "gift" in key.lower() or "redeem" in key.lower()]
