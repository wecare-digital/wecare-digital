"""The producer that was missing: a Wix Cart V2 calculation becomes a payable `QuoteSnapshot`.

THE GAP THESE TESTS CLOSE
-------------------------
`checkout_pricing.build_snapshot` produces a `QuoteSnapshot`. `QuoteSnapshot` is consumed in
production by `ecommerce/website_checkout.py` (which turns it into the Razorpay gateway amount)
and `ecommerce/customer_receipt.py` (which prints it). But `checkout_pricing.compute_quote` had
**no production caller at all** -- only tests. So both consumers depended on a snapshot that
nothing in the running system produced, and the calculator was a standalone unused component.

`lambda_utils.ecommerce.purchase_intent` is the producer, and the chain it completes is:

    CartV2.calculate            authoritative collection total, integer paise
      -> compute_quote          plus OUR convenience fee and the GST on that fee
      -> build_snapshot         frozen customer / cart / revision / items / address / delivery
      -> QuoteSnapshot          -> website_checkout (gateway) / customer_receipt (printed)

TWO HALVES OF THE MONEY, AND THEY MUST STAY APART
-------------------------------------------------
Wix owns the supply side: item prices, discounts, delivery and supply GST, computed from the
catalogue under the site's own tax configuration, for the delivery address on the cart. We own
the convenience fee and the GST on that fee. `compute_quote` contains no reference to Wix and
must not acquire one, so `test_the_collection_total_is_wix_s_and_is_not_altered` asserts the
handover is exact rather than approximately right.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import purchase_intent as pi  # noqa: E402
from lambda_utils.ecommerce.cart_v2 import CartV2  # noqa: E402
from lambda_utils.ecommerce.wix_address import UnmappableAddress  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = 1_700_000_000
SITE = "fcd82f0c-9572-49c7-acfb-88fb05042ece"

OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}

#: Maharashtra: a different state from the seller's (GSTIN 19... = West Bengal), so the GST on the
#: convenience fee must come out as a single IGST line rather than a CGST/SGST pair.
OWNED_OTHER_STATE = {"addressLine1": "1 Marine Drive", "city": "Mumbai",
                     "state": "Maharashtra", "postalCode": "400001"}


def live():
    return json.loads((FIXTURES / "wix_cart_v2_live_demo.json").read_text())


def delivery_complete():
    return json.loads((FIXTURES / "wix_cart_v2_delivery_complete.json").read_text())


class Wix:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, path, method="GET", body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        return copy.deepcopy(self.response)


def adapter(response):
    return CartV2(Wix(response))


def intent(response=None, owned=None, **kwargs):
    response = delivery_complete() if response is None else response
    return pi.build_intent(adapter(response), customer_id="CUS_abc123",
                           cart_id=response["cart"]["id"],
                           owned_address=OWNED if owned is None else owned,
                           now=NOW, site=SITE, **kwargs)


# ── the chain produces a real snapshot ───────────────────────────────────────────

def test_a_delivery_complete_cart_produces_a_quote_snapshot():
    snapshot = intent()
    assert isinstance(snapshot, cp.QuoteSnapshot)
    assert snapshot.customer_id == "CUS_abc123"
    assert snapshot.cart_id == delivery_complete()["cart"]["id"]
    assert snapshot.policy_version == cp.CALCULATION_POLICY_VERSION


def test_the_collection_total_is_wix_s_and_is_not_altered():
    """The handover point between the two halves of the money.

    `collection_before_convenience_paise` must equal Wix's `summary.priceSummary.total` exactly:
    items + discounts + delivery + supply GST. Passing a subtotal would under-collect; re-deriving
    it locally would risk double-taxing the supply.
    """
    snapshot = intent()
    assert snapshot.quote.collection_before_convenience_paise == 2549900
    wix_total = delivery_complete()["summary"]["priceSummary"]["total"]["amount"]
    assert snapshot.quote.collection_before_convenience_paise == \
        int(str(wix_total).replace(".", "").lstrip("0") or "0")


def test_the_payable_total_is_the_collection_plus_our_fee_and_its_gst():
    """What the customer pays, and it is not the raw Wix total.

    This is the contract `website_checkout` documents: the gateway amount is the calculator total,
    never the Wix figure. Before this producer existed there was no code path that honoured it.
    """
    snapshot = intent()
    quote = snapshot.quote
    assert quote.total_payable_paise == (quote.collection_before_convenience_paise
                                         + quote.convenience_fee_paise
                                         + quote.convenience_gst_paise)
    assert quote.total_payable_paise == 2625123
    assert quote.total_payable_paise > quote.collection_before_convenience_paise


def test_every_money_value_is_an_integer_number_of_paise():
    """R6.1: no float arithmetic anywhere in the payment path."""
    quote = intent().quote
    for value in (quote.collection_before_convenience_paise, quote.convenience_fee_paise,
                  quote.convenience_gst_paise, quote.total_payable_paise):
        assert type(value) is int


def test_the_cart_revision_is_converted_to_the_integer_the_snapshot_requires():
    """Wix sends `revision` as a decimal STRING; `QuoteSnapshot` validates it as an int.

    A silent type mismatch here would have been a `PricingError` at the worst moment rather than
    a converted value, so the conversion is asserted rather than assumed.
    """
    snapshot = intent()
    assert snapshot.cart_revision == 4
    assert type(snapshot.cart_revision) is int


# ── place of supply reaches the fee's tax split ──────────────────────────────────

def test_an_in_state_delivery_splits_the_fee_gst_as_cgst_and_sgst():
    """Destination West Bengal, seller GSTIN 19... = West Bengal, so intra-state."""
    split = intent().quote.convenience_gst_split
    assert split.intra_state is True
    assert split.igst_paise == 0
    assert split.cgst_paise + split.sgst_paise == intent().quote.convenience_gst_paise


def test_an_out_of_state_delivery_produces_a_single_igst_line():
    """Destination Maharashtra, so inter-state: one IGST line, no CGST/SGST pair.

    The assertion that matters for the owner's placeholder-address rule: the delivery address
    genuinely changes the tax treatment, so a fabricated one would produce a wrong split on a real
    invoice rather than merely an untidy record.
    """
    split = intent(owned=OWNED_OTHER_STATE).quote.convenience_gst_split
    assert split.intra_state is False
    assert split.cgst_paise == 0 and split.sgst_paise == 0
    assert split.igst_paise == intent(owned=OWNED_OTHER_STATE).quote.convenience_gst_paise


def test_the_two_states_produce_different_tax_splits_for_the_same_goods():
    """Same cart, same amount, different place of supply, different split. One number, two truths
    -- which is exactly why the address cannot be invented."""
    here, there = intent(), intent(owned=OWNED_OTHER_STATE)
    assert here.quote.total_payable_paise == there.quote.total_payable_paise
    assert here.quote.convenience_gst_split != there.quote.convenience_gst_split


def test_a_registered_buyer_gstin_overrides_the_destination_for_the_fee_split():
    """A registered buyer's own state code is the stronger signal, and `compute_quote` already
    implements that precedence; this asserts the producer does not defeat it."""
    snapshot = intent(buyer_gstin="27AAAAA0000A1Z5")
    assert snapshot.quote.buyer_gstin == "27AAAAA0000A1Z5"
    assert snapshot.quote.convenience_gst_split.intra_state is False


# ── the snapshot freezes what justifies the amount ───────────────────────────────

def test_the_snapshot_freezes_the_address_and_delivery_that_produced_the_total():
    frozen = intent().frozen_data
    assert frozen["address"]["subdivision"] == "IN-WB"
    assert frozen["delivery"]["id"]
    assert frozen["cart"] == {"id": delivery_complete()["cart"]["id"], "revision": 4}
    assert frozen["site"] == SITE


def test_a_different_delivery_address_yields_a_different_snapshot_hash():
    """A quote is bound to its destination. Reusing one across addresses would be the same number
    standing for a different tax treatment and a different delivery charge."""
    assert intent().snapshot_hash != intent(owned=OWNED_OTHER_STATE).snapshot_hash


def test_a_changed_cart_yields_a_different_snapshot_hash():
    changed = delivery_complete()
    changed["cart"]["revision"] = "5"
    changed["summary"]["cartRevision"] = "5"
    assert intent().snapshot_hash != intent(changed).snapshot_hash


def test_the_snapshot_expires_and_an_expired_quote_is_not_payable():
    snapshot = intent()
    assert snapshot.expires_at == NOW + pi.QUOTE_TTL_SECONDS
    assert snapshot.is_expired(snapshot.expires_at) is True
    assert snapshot.is_expired(snapshot.expires_at - 1) is False


def test_the_quote_lifetime_matches_the_cart_module_s():
    """Two numbers describing one fact -- how long a reviewed price stays honourable -- would
    eventually disagree."""
    from lambda_utils.ecommerce.customer_cart import QUOTE_LIFETIME

    assert pi.QUOTE_TTL_SECONDS == QUOTE_LIFETIME


# ── the refusals ─────────────────────────────────────────────────────────────────

def test_a_cart_with_no_delivery_details_refuses_with_a_recoverable_error():
    """The real live cart. `DeliveryDetailsRequired` rather than a generic contract error, so the
    caller can tell "the customer has not chosen a destination" -- a normal step -- from "Wix
    returned something unsafe"."""
    response = live()
    with pytest.raises(pi.DeliveryDetailsRequired):
        pi.build_intent(adapter(response), customer_id="CUS_abc123",
                        cart_id=response["cart"]["id"], owned_address=OWNED, now=NOW)


def test_the_missing_delivery_refusal_is_keyed_on_the_violation_code_not_a_message():
    """Only Wix's own `code` converts the error. An exception string is not a stable contract, and
    reporting an unexplained failure to a customer as "choose an address" would be a lie."""
    response = live()
    response["summary"]["violations"] = [
        {"scope": "OTHER", "code": "SOMETHING_ELSE", "severity": "ERROR"}]
    with pytest.raises(Exception) as caught:
        pi.build_intent(adapter(response), customer_id="CUS_abc123",
                        cart_id=response["cart"]["id"], owned_address=OWNED, now=NOW)
    assert not isinstance(caught.value, pi.DeliveryDetailsRequired)


def test_an_unmappable_owned_address_never_reaches_a_quote():
    """A placeholder cannot be laundered into a price by the producer either."""
    for placeholder in ({}, {"state": "Unknown"},
                        {"addressLine1": "-", "city": "-", "postalCode": "-"}):
        with pytest.raises(UnmappableAddress):
            intent(owned=placeholder)


def test_a_non_inr_cart_is_refused():
    response = delivery_complete()
    for field in ("businessInfo", "customerInfo", "paymentInfo"):
        response["cart"][field]["currencyCode"] = "USD"
    with pytest.raises(ValueError):
        pi.build_intent(adapter(response), customer_id="CUS_abc123",
                        cart_id=response["cart"]["id"], owned_address=OWNED, now=NOW)


def test_a_calculator_that_altered_the_collection_total_is_refused():
    """Integer equality, not a tolerance.

    The payment path fails closed on a one-paise mismatch, so a calculator that moved the
    authoritative collection total must not reach a gateway. Injected rather than mocked globally
    so the real `compute_quote` stays the thing under test everywhere else.
    """
    def tampering(collection, **kwargs):
        return cp.compute_quote(collection + 1, **kwargs)

    with pytest.raises(cp.PricingError):
        intent(quote_fn=tampering)


def test_a_missing_customer_id_is_refused_before_any_wix_call():
    wix = Wix(delivery_complete())
    for bad in ("", None, 0):
        with pytest.raises(cp.PricingError):
            pi.build_intent(CartV2(wix), customer_id=bad,
                            cart_id=delivery_complete()["cart"]["id"],
                            owned_address=OWNED, now=NOW)
    assert not wix.calls


# ── preparing delivery, and what the producer may not do ─────────────────────────

def test_prepare_delivery_sets_the_address_and_then_selects_the_offered_method():
    """THE REGRESSION THIS FILE EXISTS TO PREVENT FROM RETURNING.

    `prepare_delivery` used to set the address and stop whenever no `delivery_option_id` was
    passed -- which is what every caller does. Cart V2 then answers Calculate Cart with
    `MISSING_DELIVERY_METHOD`, so no physical website checkout could be priced at all. The old
    version of this test asserted `== ["PATCH"]`, i.e. it asserted the defect.
    """
    response = delivery_complete()
    wix = Wix(response)
    pi.prepare_delivery(CartV2(wix), response["cart"]["id"], OWNED)

    assert [method for method, _, _ in wix.calls] == ["PATCH", "POST", "POST"]
    assert wix.calls[1][1].endswith("/calculate")        # the options read
    assert wix.calls[2][1].endswith("/set-delivery-method")
    # And the id selected is the one WIX offered in `summary.deliverySummary.method.code`.
    assert wix.calls[2][2] == {"deliveryMethod": {
        "code": response["summary"]["deliverySummary"]["method"]["code"]}}


def test_an_explicitly_chosen_option_is_used_without_reading_the_options():
    """A customer who picked from a UI is not second-guessed, and costs no extra Wix call."""
    response = delivery_complete()
    wix = Wix(response)
    pi.prepare_delivery(CartV2(wix), response["cart"]["id"], OWNED,
                        delivery_option_id="11111111-2222-3333-4444-555555555555")

    assert [method for method, _, _ in wix.calls] == ["PATCH", "POST"]
    assert wix.calls[1][1].endswith("/set-delivery-method")
    assert not [path for _m, path, _b in wix.calls if path.endswith("/calculate")]


def test_zero_offered_options_refuses_and_says_wix_was_asked(caplog):
    """The honest refusal is kept, and made DISTINGUISHABLE from "we never asked".

    Both states produce the same `MISSING_DELIVERY_METHOD` violation downstream, so the violation
    cannot tell them apart. The log line can: `website_checkout_delivery_zero_options` is only
    written after Wix has been asked and has named nothing, which is a Wix delivery-region gap
    rather than a defect here.
    """
    response = delivery_complete()
    response["summary"].pop("deliverySummary")          # Wix named no option for this address
    wix = Wix(response)

    with caplog.at_level("WARNING"):
        with pytest.raises(pi.DeliveryDetailsRequired):
            pi.prepare_delivery(CartV2(wix), response["cart"]["id"], OWNED)

    # The address was still written; only the method was not chosen.
    assert [method for method, _, _ in wix.calls] == ["PATCH", "POST"]
    assert not [path for _m, path, _b in wix.calls if "set-delivery-method" in path]

    events = [json.loads(record.message) for record in caplog.records
              if record.message.startswith("{")]
    zero = [event for event in events
            if event["event"] == "website_checkout_delivery_zero_options"]
    assert zero and zero[0]["optionCount"] == 0
    # A cart id and a count. No address, no customer, nothing maskable.
    assert set(zero[0]) == {"event", "wixCartId", "cartRevision", "optionCount"}


def test_several_options_resolve_to_the_cheapest_deterministically():
    """The rule is named and tested on its own, because it is a decision about someone's money.

    Lowest price wins; a tie keeps Wix's own order; an option Wix priced as unknown sorts LAST
    rather than being read as free.
    """
    from lambda_utils.ecommerce.cart_v2 import cheapest_delivery_option

    assert cheapest_delivery_option([]) is None
    assert cheapest_delivery_option([
        {"id": "express", "title": "Express", "pricePaise": 29900},
        {"id": "free", "title": "Free Delivery", "pricePaise": 0},
        {"id": "standard", "title": "Standard", "pricePaise": 9900},
    ])["id"] == "free"
    # Tie -> Wix's first.
    assert cheapest_delivery_option([
        {"id": "first", "title": "A", "pricePaise": 5000},
        {"id": "second", "title": "B", "pricePaise": 5000},
    ])["id"] == "first"
    # Unknown price is not free.
    assert cheapest_delivery_option([
        {"id": "unpriced", "title": "?", "pricePaise": None},
        {"id": "priced", "title": "Standard", "pricePaise": 9900},
    ])["id"] == "priced"


def test_the_producer_makes_no_order_or_charging_call():
    """Enumerated, so "it cannot charge again" is demonstrated rather than asserted."""
    response = delivery_complete()
    wix = Wix(response)
    pi.prepare_delivery(CartV2(wix), response["cart"]["id"], OWNED, delivery_option_id="opt-1")
    pi.build_intent(CartV2(wix), customer_id="CUS_abc123", cart_id=response["cart"]["id"],
                    owned_address=OWNED, now=NOW)

    for _method, path, _body in wix.calls:
        lowered = path.lower()
        for forbidden in ("place-order", "mark-as-completed", "/orders", "/payments",
                          "/checkout", "capture", "charge", "redirect"):
            assert forbidden not in lowered, f"producer reached {path}"


def test_the_producer_never_chooses_a_delivery_method_on_the_customer_s_behalf():
    """`build_intent` quotes; it does not select. A function that both chose and priced could pick
    the cheapest or the first option silently, and delivery is money."""
    response = delivery_complete()
    wix = Wix(response)
    pi.build_intent(CartV2(wix), customer_id="CUS_abc123", cart_id=response["cart"]["id"],
                    owned_address=OWNED, now=NOW)
    assert not [path for _m, path, _b in wix.calls if "delivery-method" in path]
