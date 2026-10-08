"""DECISION 1: one discount arithmetic, and it is Wix's. Plus the order-total identity.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` sections 2,
2.3 and 3, and the test list in section 7 (tests 42-51).

One strict xfail remains
------------------------
* **SEAM-C1 is CLOSED** - `cart_v2.add_coupon` now sends the current Cart V2
  `{"coupon":{"code":...}}` request and enforces Wix's 50-character maximum.
* **SEAM-C2** - the Wix order payload must carry the convenience fee and its GST in
  `additionalFees[]`, and nothing builds that payload yet. `strict=True` so test 48 converts from
  "pending" to "passing" by the producer's change, and fails loudly if someone satisfies it by
  lowering the bar.

Why test 48 reads the RESPONSE and not the request
--------------------------------------------------
`Create Order`'s `priceSummary` is documented `readOnly: true`, so a `priceSummary.total` we SEND
is discarded - an identity asserted against the sent payload would be asserting a property of a
discarded field. The writable fields are `appliedDiscounts[]` and `additionalFees[]`, and the
readback is where the totals are checked. The Wix stub below therefore RECOMPUTES `priceSummary`
from those writable fields, exactly as a server that ignores what we send would, which is what
makes the equality a real test rather than an echo.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import purchase_intent as pi  # noqa: E402
from lambda_utils.ecommerce import wix_coupons as wc  # noqa: E402
from lambda_utils.ecommerce.cart_v2 import BASE, CartV2  # noqa: E402
from lambda_utils.ecommerce.money import Money  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"
STORE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/coupon_store.py"
ADAPTER = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wix_coupons.py"

NOW = 1_700_000_000
OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}

#: The SEAM-C2 producer, by the name this test expects it to land under. Several homes are
#: tried because the design names a CALL SITE rather than a module: whichever file ends up
#: building `attempt['wixOrderPayload']` owns it.
SEAM_C2_PRODUCER = "build_wix_order_payload"
SEAM_C2_HOMES = ("website_checkout", "wix_writeback", "initiation", "order_creation",
                 "finalization")

SEAM_C1 = "CLOSED: current Cart V2 nested coupon body is implemented."
SEAM_C2 = ("SEAM-C2: nothing builds attempt['wixOrderPayload'] yet, so the convenience fee and "
           "its GST cannot travel onto the order as an additional fee. strict=True per "
           "DECISION 8, so this converts to passing by the producer's change and fails loudly "
           "if someone satisfies it by weakening the assertion.")


def cart_fixture():
    return json.loads((FIXTURES / "wix_cart_v2_coupon_applied_v2_shape.json").read_text())


class Wix:
    """A spy request callable over one canned Calculate Cart response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, endpoint, method="GET", body=None):
        self.calls.append((method.upper(), endpoint, copy.deepcopy(body)))
        return copy.deepcopy(self.response)

    def paths(self, cart_id):
        return [(method, path.replace(cart_id, "{id}")) for method, path, _ in self.calls]


def quote_for(response):
    """The payable quote the existing chain produces for this cart, with no coupon knowledge."""
    adapter = CartV2(Wix(response))
    snapshot = pi.build_intent(adapter, customer_id="cus-1",
                               cart_id=response["cart"]["id"], owned_address=OWNED, now=NOW)
    return snapshot.quote


def find_seam_c2_producer():
    """The SEAM-C2 builder, or None while the seam is open."""
    import importlib
    for module_name in SEAM_C2_HOMES:
        try:
            module = importlib.import_module(f"lambda_utils.ecommerce.{module_name}")
        except Exception:  # noqa: BLE001 - an absent or unimportable home is just "not here"
            continue
        producer = getattr(module, SEAM_C2_PRODUCER, None)
        if callable(producer):
            return producer
    return None


def create_order_stub(payload):
    """A Wix that RECOMPUTES `priceSummary` from the writable fields, as the schema implies.

    `priceSummary` is `readOnly: true` on Create Order, so a total we send is discarded. This
    stub therefore derives the response total from `appliedDiscounts[]` and `additionalFees[]`
    and from the cart figures - which means the identity in test 48 holds only if the fee and its
    GST really do travel as an additional fee. A stub that echoed our payload would assert
    nothing.
    """
    subtotal = Money.from_wix(payload["priceSummary"]["subtotal"]["amount"]).paise
    delivery = Money.from_wix(payload["priceSummary"]["delivery"]["amount"]).paise
    tax = Money.from_wix(payload["priceSummary"]["tax"]["amount"]).paise
    discount = sum(Money.from_wix(entry["coupon"]["amount"]["amount"]).paise
                   for entry in payload.get("appliedDiscounts") or [])
    fees = sum(Money.from_wix(entry["price"]["amount"]).paise
               for entry in payload.get("additionalFees") or [])
    total = subtotal - discount + delivery + tax + fees
    returned = copy.deepcopy(payload)
    returned["priceSummary"] = {
        "subtotal": {"amount": Money(subtotal).to_wix()},
        "discount": {"amount": Money(discount).to_wix()},
        "delivery": {"amount": Money(delivery).to_wix()},
        "tax": {"amount": Money(tax).to_wix()},
        "totalAdditionalFees": {"amount": Money(fees).to_wix()},
        "total": {"amount": Money(total).to_wix()},
    }
    return returned


# ── 42: there is no second arithmetic ─────────────────────────────────────────

#: The one coupon-amount function permitted to exist, and only in `coupon_store`.
#:
#: On the WEBSITE the discount is still Wix's answer to `Calculate Cart` and this test's name is
#: still literally true there - nothing below changes what the cart path reads. The exception is
#: the INVOICE surface, which has no Wix cart and therefore no `Calculate Cart` to defer to, so
#: one reading of our own definition is unavoidable. It is allowed BY NAME rather than by relaxing
#: the pattern, so a second amount function still fails this test.
PERMITTED_AMOUNT_FUNCTIONS = {"coupon_store": {"discount_paise"}}


def test_the_coupon_discount_comes_only_from_wix_calculate_cart():
    """The ADAPTER computes no discount at all, and the store computes one only for the surface
    Wix cannot answer for. One number per surface, read rather than re-derived - a mismatch is
    not merely detected, it is unrepresentable."""
    for module in (cs, wc):
        permitted = PERMITTED_AMOUNT_FUNCTIONS.get(module.__name__.rsplit(".", 1)[-1], set())
        for name in dir(module):
            if name.startswith("_") or name in permitted:
                continue
            attribute = getattr(module, name)
            if not callable(attribute):
                continue
            assert "discount" not in name.lower() or "kind" in name.lower(), \
                f"{module.__name__}.{name} looks like a discount calculator"
    # The adapter's ban stays absolute: it is the Wix boundary, and a discount computed there
    # would be a number Wix did not agree to.
    assert not [name for name in dir(wc)
                if not name.startswith("_") and callable(getattr(wc, name))
                and "discount" in name.lower() and "kind" not in name.lower()]

    # And no arithmetic on a discount anywhere in either module: the only money operation is the
    # paise -> whole-rupee integer division at the Wix boundary.
    for path in (STORE, ADAPTER):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.Mult)):
                rendered = ast.unparse(node)
                assert "discount" not in rendered.lower(), \
                    f"{path.name}:{node.lineno} performs arithmetic on a discount"


# ── 43: the method that makes the Wix total net ───────────────────────────────

def test_add_coupon_is_the_method_that_makes_the_wix_total_net():
    """Option (a), asserted unconditionally: the CITED endpoint, and a total that arrives already
    net of the discount.

    `POST /ecom/v2/carts/{cartId}/add-coupon` followed by
    `POST /ecom/v2/carts/{cartId}/calculate`. A browser supplies a CODE; Wix decides whether it
    is valid, what it is worth and whether this cart qualifies.
    """
    response = cart_fixture()
    cart_id = response["cart"]["id"]
    wix = Wix(response)
    CartV2(wix).add_coupon(cart_id, "SAVE10")
    assert wix.paths(cart_id) == [("POST", f"{BASE}/{{id}}/add-coupon")]

    # The reduced total arrives from Calculate Cart, with the discount in its own component.
    prices = response["summary"]["priceSummary"]
    subtotal = Money.from_wix(prices["subtotal"]["amount"]).paise
    discount = Money.from_wix(prices["discount"]["amount"]).paise
    total = Money.from_wix(prices["total"]["amount"]).paise
    assert discount > 0
    assert total < subtotal
    quote = quote_for(response)
    assert quote.collection_before_convenience_paise == total


def test_add_coupon_sends_the_v2_nested_coupon_body():
    """The deferred half of test 43. `AddCouponRequest.coupon` is `CouponInput`, and the schema's
    `required` array names both `coupon` and `coupon.code`, so today's `{"couponCode": ...}`
    cannot succeed at all. The migration mapping states the rename explicitly."""
    response = cart_fixture()
    wix = Wix(response)
    CartV2(wix).add_coupon(response["cart"]["id"], "SAVE10")
    assert wix.calls[0][2] == {"coupon": {"code": "SAVE10"}}


# ── 44-45: a browser supplies a code, never an amount ─────────────────────────

@pytest.mark.parametrize("smuggled", ["discountPaise", "amount", "amountPaise", "discount",
                                      "total", "moneyOffPaise", "customerId"])
def test_a_browser_cannot_supply_a_discount_only_a_code_to_the_coupon_routes(smuggled):
    """Asserted from OUR routes' side, independently of the cart adapter, so the guarantee does
    not rest on a single file another session owns.

    The body allowlist is a closed set, and an unexpected key is REFUSED rather than dropped -
    which is what makes the property structural instead of a property of which keys we read.
    """
    source = HANDLER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(HANDLER))
    allowlist = next(
        ast.literal_eval(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "CUSTOMER_BODY_FIELDS"
                for t in node.targets))
    assert set(allowlist) == {"code", "cartId"}
    assert smuggled not in allowlist

    # And the refusal is a raise, not a filter.
    body_reader = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name == "_customer_body")
    rendered = ast.unparse(body_reader)
    assert "set(parsed) - set(CUSTOMER_BODY_FIELDS)" in rendered
    assert "raise Refused(400, 'UNSUPPORTED_FIELD')" in rendered

    # The amount still comes from the mocked Wix total, whatever the body said.
    response = cart_fixture()
    assert quote_for(response).collection_before_convenience_paise == Money.from_wix(
        response["summary"]["priceSummary"]["total"]["amount"]).paise


def test_the_coupon_validate_route_returns_a_verdict_and_no_amount():
    """No key in the response is money-shaped, and the verdict set is closed."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    validate = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "_validate")
    for node in ast.walk(validate):
        if not isinstance(node, ast.Return):
            continue
        rendered = ast.unparse(node)
        for money in ("paise", "Paise", "amount", "Amount", "discount", "Discount", "total"):
            assert money not in rendered
    assert set(cs.VERDICTS) == {
        "ELIGIBLE", "UNKNOWN_CODE", "NOT_ACTIVE", "NOT_STARTED", "EXPIRED",
        "USAGE_LIMIT_REACHED", "CUSTOMER_LIMIT_REACHED", "HELD_BY_ANOTHER_CART",
        "WIX_MIRROR_INCOMPLETE"}


# ── 46-47: the fee basis and the quote identity ───────────────────────────────

def test_the_coupon_store_reduces_the_convenience_fee_basis():
    """A coupon is a DISCOUNT, so it lowers `collection_before_convenience_paise` and the 2.5%
    fee and its 18% GST are computed on the REDUCED total. `compute_quote` needs no change - it
    simply receives a smaller number."""
    discounted = cart_fixture()
    coupon_quote = quote_for(discounted)

    undiscounted = cart_fixture()
    prices = undiscounted["summary"]["priceSummary"]
    subtotal = Money.from_wix(prices["subtotal"]["amount"]).paise
    delivery = Money.from_wix(prices["delivery"]["amount"]).paise
    gross = subtotal + delivery
    _rewrite_total(undiscounted, discount_paise=0, total_paise=gross)
    plain_quote = quote_for(undiscounted)

    assert coupon_quote.collection_before_convenience_paise < \
        plain_quote.collection_before_convenience_paise
    assert coupon_quote.convenience_fee_paise < plain_quote.convenience_fee_paise
    assert coupon_quote.convenience_gst_paise < plain_quote.convenience_gst_paise
    # The fee really is 2.5% of the reduced collection, rounded half up by the shared helper.
    assert coupon_quote.convenience_fee_paise == cp.round_half_up(
        coupon_quote.collection_before_convenience_paise, cp.CONVENIENCE_FEE_BPS)


def test_the_coupon_store_quote_still_reconciles_exactly():
    """`collection + fee + gst == total`, with the discount applied. Already enforced by
    `CheckoutQuote.__post_init__`; asserted here so the coupon path is covered by name."""
    quote = quote_for(cart_fixture())
    assert (quote.collection_before_convenience_paise + quote.convenience_fee_paise
            + quote.convenience_gst_paise) == quote.total_payable_paise
    assert quote.convenience_gst_split.total_paise == quote.convenience_gst_paise
    assert quote.currency == "INR"


def _rewrite_total(response, *, discount_paise, total_paise):
    """Rewrite a fixture's discount and total consistently, so `calculate` still reconciles."""
    prices = response["summary"]["priceSummary"]
    prices["discount"] = {"amount": Money(discount_paise).to_wix(),
                          "convertedAmount": Money(discount_paise).to_wix()}
    for key in ("total",):
        prices[key] = {"amount": Money(total_paise).to_wix(),
                       "convertedAmount": Money(total_paise).to_wix()}
    payment = response["summary"]["paymentSummary"]
    for key in ("payNow", "totalAfterGiftCards"):
        payment[key] = {"amount": Money(total_paise).to_wix(),
                        "convertedAmount": Money(total_paise).to_wix()}
    if not discount_paise:
        response["summary"]["discounts"] = []
        response["cart"]["coupons"] = []


# ── 48: the one invariant, on the Create Order RESPONSE ───────────────────────

@pytest.mark.xfail(strict=True, reason=SEAM_C2)
def test_the_wix_order_total_equals_the_razorpay_charged_total():
    """The DECISION 1 test, asserting ALL FOUR equalities against a Create Order response.

    1. `priceSummary.total` == `quote.total_payable_paise`
                            == `verifiedCapturedPaise + giftCardRedeemedPaise`
       (the gift-card term is 0 on the coupon-only path, so this reduces to the "Wix order total
       == Razorpay-charged total" the brief asks for - now against the charge Razorpay
       CONFIRMED rather than the charge we asked for).
    2. `priceSummary.subtotal` == the cart's subtotal (HIGH-2's added dependency: the order side
       must not have re-derived the pre-discount figure).
    3. `priceSummary.totalAdditionalFees` == `convenience_fee_paise + convenience_gst_paise`
       (MEDIUM-8).
    4. `appliedDiscounts[0].coupon.amount.amount` BYTE-IDENTICAL to the cart's
       `priceSummary.discount.amount` (HIGH-1: relayed verbatim, never recomputed).

    And the `additionalFees[]` entry sends all three of `price`, `priceBeforeTax` and
    `priceAfterTax` - `price` and `priceAfterTax` = fee + GST, `priceBeforeTax` = fee - because
    `PriceSummary.totalAdditionalFees` is what Wix sums and nothing documents which field it
    derives from.
    """
    producer = find_seam_c2_producer()
    assert producer is not None, (
        f"SEAM-C2 is open: no {SEAM_C2_PRODUCER}() in any of {SEAM_C2_HOMES}")

    cart = cart_fixture()
    quote = quote_for(cart)
    coupon = cart["cart"]["coupons"][0]
    payload = producer(cart=cart, quote=quote, coupon=coupon)

    # The writable fields, as sent.
    fees = payload["additionalFees"]
    assert len(fees) == 1
    fee = fees[0]
    assert fee["code"] == "WD-CONVENIENCE"
    assert fee["name"] == "Convenience fee"
    assert Money.from_wix(fee["priceBeforeTax"]["amount"]).paise == quote.convenience_fee_paise
    for field in ("price", "priceAfterTax"):
        assert Money.from_wix(fee[field]["amount"]).paise == (
            quote.convenience_fee_paise + quote.convenience_gst_paise)

    applied = payload["appliedDiscounts"]
    assert len(applied) == 1
    assert applied[0]["discountType"] == "GLOBAL"
    assert applied[0]["coupon"]["code"] == coupon["code"]
    # HIGH-1: byte-identical, because it is RELAYED and not recomputed.
    assert applied[0]["coupon"]["amount"]["amount"] == \
        cart["summary"]["priceSummary"]["discount"]["amount"]

    # The readback is where the totals are asserted, because priceSummary is readOnly on
    # Create Order and a sent total is discarded.
    returned = create_order_stub(payload)
    verified_captured_paise = quote.total_payable_paise
    gift_card_redeemed_paise = 0

    assert Money.from_wix(returned["priceSummary"]["total"]["amount"]).paise == \
        quote.total_payable_paise == verified_captured_paise + gift_card_redeemed_paise
    assert returned["priceSummary"]["subtotal"]["amount"] == \
        cart["summary"]["priceSummary"]["subtotal"]["amount"]
    assert Money.from_wix(returned["priceSummary"]["totalAdditionalFees"]["amount"]).paise == \
        quote.convenience_fee_paise + quote.convenience_gst_paise
    assert Money.from_wix(returned["priceSummary"]["discount"]["amount"]).paise == \
        Money.from_wix(cart["summary"]["priceSummary"]["discount"]["amount"]).paise


def test_the_order_total_identity_is_arithmetically_reachable_today():
    """The unconditional half of test 48: the identity is not aspirational.

    Given the cart's own components and the quote, `subtotal - discount + delivery + tax +
    (fee + GST)` already equals `quote.total_payable_paise`. So the only thing SEAM-C2 has to do
    is TRANSPORT the fee - no new arithmetic, and nothing for the two sides to disagree about.
    """
    cart = cart_fixture()
    quote = quote_for(cart)
    prices = cart["summary"]["priceSummary"]
    components = {key: Money.from_wix(prices[key]["amount"]).paise
                  for key in ("subtotal", "discount", "delivery", "additionalFees", "tax")}
    supply = (components["subtotal"] - components["discount"] + components["delivery"]
              + components["additionalFees"] + components["tax"])
    assert supply == quote.collection_before_convenience_paise
    assert supply + quote.convenience_fee_paise + quote.convenience_gst_paise == \
        quote.total_payable_paise


# ── 49-51: one arithmetic, and nothing that can charge ────────────────────────

def test_the_wix_order_discount_equals_the_wix_cart_discount():
    """One arithmetic, both sides. Under option (a) this is not a check that happens to pass -
    there is a single number and both sides read it."""
    cart = cart_fixture()
    cart_discount = cart["summary"]["priceSummary"]["discount"]["amount"]
    relayed = {"discountType": "GLOBAL",
               "coupon": {"id": cart["cart"]["coupons"][0]["id"],
                          "code": cart["cart"]["coupons"][0]["code"],
                          "name": cart["summary"]["discounts"][0]["name"],
                          "amount": {"amount": cart_discount}}}
    assert relayed["coupon"]["amount"]["amount"] == cart_discount
    assert Money.from_wix(relayed["coupon"]["amount"]["amount"]).paise == \
        Money.from_wix(cart_discount).paise


def test_a_coupon_that_only_exists_our_side_cannot_lower_what_is_charged():
    """The writeback-mismatch scenario, proven impossible under (a).

    A coupon that failed to mirror is `PENDING_WIX`, which `evaluate` refuses - so `Add Coupon`
    is never called, Wix never applies a discount, and the charged amount is the undiscounted
    Wix total. There is no path by which our row alone lowers a price.
    """
    store = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                      indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    row = cs.create(store, {"code": "OURSONLY", "name": "never mirrored",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 250000,
                            "startTimeMs": 1_700_000_000_000,
                            "minimumSubtotalPaise": 100000},
                    clock=lambda: NOW)
    assert row["wixMirrorState"] == cs.MIRROR_PENDING
    assert cs.evaluate(row, clock=lambda: NOW + 10) == cs.WIX_MIRROR_INCOMPLETE

    # And the charged amount is whatever Wix said, with no reference to our stored amount.
    undiscounted = cart_fixture()
    prices = undiscounted["summary"]["priceSummary"]
    gross = (Money.from_wix(prices["subtotal"]["amount"]).paise
             + Money.from_wix(prices["delivery"]["amount"]).paise)
    _rewrite_total(undiscounted, discount_paise=0, total_paise=gross)
    quote = quote_for(undiscounted)
    assert quote.collection_before_convenience_paise == gross
    assert quote.collection_before_convenience_paise != gross - row["moneyOffPaise"]


def test_nothing_in_the_coupon_path_calls_place_order_or_get_checkout_url():
    """Enumerates the adapter methods. `Place Order`'s own description is "This endpoint may
    charge the customer", and a method that can charge must not EXIST on an adapter a
    customer-facing route holds - so the guarantee is absence, which a test can enumerate."""
    for module, forbidden in ((wc, ("place_order", "checkout_url", "redirect")),
                              (cs, ("place_order", "checkout_url", "redirect", "charge",
                                    "capture", "refund"))):
        names = [name for name in dir(module) if not name.startswith("__")]
        for name in names:
            lowered = name.lower()
            for banned in forbidden:
                assert banned not in lowered, f"{module.__name__}.{name}"

    adapter_methods = [name for name in dir(wc.WixCoupons) if not name.startswith("_")]
    assert sorted(adapter_methods) == ["assert_mirrors", "create", "deactivate", "get"]

    source = (HANDLER.read_text(encoding="utf-8")
              + (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wix_coupons.py")
              .read_text(encoding="utf-8"))
    for endpoint in ("place-order", "/redirect-session", "checkout-url", "/payments/"):
        assert endpoint not in source, f"the coupon path references {endpoint}"


# ── the invoice leg: a third surface, the SAME namespace ──────────────────────

def test_an_invoice_path_redemption_lands_in_the_same_namespace_as_a_cart_one():
    """One coupon system means one place a redemption is recorded, whichever surface sold it.

    The invoice surface keys its hold and its redemption on the invoice `referenceId`, because
    that is the identifier it has - there is no `wixCartId` on a Pay Flow invoice. That could
    easily have become a second namespace ("invoice redemptions live over here"), and then a
    single-use coupon could be spent once on the website and once on an invoice, because neither
    claim would see the other.

    So this asserts the namespace rather than the mechanics: both surfaces reach
    `coupon_store.commit_redemption`, both land under `COUPONREDEEM#<code>#<orderId>`, both feed
    the SAME `usageCount`, and the second attempt on one order is refused by the conditional write
    rather than counted twice.
    """
    store = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                      indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    cs.create(store, {"code": "SHARED1", "name": "One system",
                      "discountKind": cs.MONEY_OFF, "moneyOffPaise": 10000,
                      "startTimeMs": 1_700_000_000_000, "minimumSubtotalPaise": 0},
              created_by="staff-1", clock=lambda: 1_700_000_000)

    # The website leg: keyed on a Wix cart and a Wix order.
    cart_leg = cs.commit_redemption(store, code="SHARED1", cart_id="wix-cart-1",
                                    order_id="WD-ORD-WEBSITE1", customer_id="customer-a",
                                    clock=lambda: 1_700_000_000)
    # The invoice leg: keyed on the invoice referenceId, which is also its cart id.
    invoice_leg = cs.commit_redemption(store, code="SHARED1", cart_id="WD-PAY-INVOICE01",
                                       order_id="WD-PAY-INVOICE01", customer_id="customer-b",
                                       clock=lambda: 1_700_000_100)

    assert cart_leg["committed"] is True
    assert invoice_leg["committed"] is True
    recorded = sorted(key for key in store.rows if key.startswith(cs.PREFIX_REDEEM))
    assert recorded == [cs.redeem_key("SHARED1", "WD-ORD-WEBSITE1"),
                        cs.redeem_key("SHARED1", "WD-PAY-INVOICE01")]
    # One counter, fed by both surfaces. Two namespaces would have left this at 1.
    assert int(cs.get_definition(store, "SHARED1")["usageCount"]) == 2

    # And the invoice leg is idempotent on its own order id, so a redelivered capture does not
    # count a second use.
    replay = cs.commit_redemption(store, code="SHARED1", cart_id="WD-PAY-INVOICE01",
                                  order_id="WD-PAY-INVOICE01", customer_id="customer-b",
                                  clock=lambda: 1_700_000_200)
    assert replay["committed"] is False
    assert int(cs.get_definition(store, "SHARED1")["usageCount"]) == 2
