"""A contribution is ONE Rs.1 DIGITAL Wix product in the existing cart, and nothing else.

What this file pins, and why each one is a property rather than a shape
----------------------------------------------------------------------
* **The browser names a CHOICE, never an amount.** No price, amount or currency leaves the
  browser; `cart_v2.calculate` stays the sole price authority. The expected collection is looked
  up server-side in the committed `CONTRIBUTION_CHOICES_PAISE` and Wix's computed total is
  asserted against it, so a Wix price edit refuses rather than charging a figure the browser's
  button did not promise.
* **The delivery skip keys on contribution product IDENTITY, not on Wix's `productType`.** The
  live `Contribute` product is PHYSICAL, so a `productType`-keyed skip inverts every no-delivery
  branch -- and the browser keys on identity, so the two sides would disagree about one basket.
  Driven under BOTH product types, asserting the same answer.
* **A contribution basket is contribution-only**, refused server-side before any Wix call -- and
  that includes two contribution lines, which is two contributions rather than one bigger one.
* **`CONTRIBUTION_PRODUCT_ID` unset is a KILL SWITCH, not a de-guard.** A recognised contribution
  product with the env key empty is REFUSED -- never priced as an ordinary product with the alone
  check and the total guard both sitting out. That only works because the recognition set is
  committed to git rather than configured.
* **Contributions are FEE-EXEMPT.** The customer pays exactly the amount they chose, to the paise,
  through `checkout_pricing.exempt_quote` substituted at `build_intent_with_calculation`'s existing
  `quote_fn` seam. An ordinary basket still gets `compute_quote` with the fee, so the substitution
  is proven per-basket rather than global.
* **A no-delivery basket never inherits a place of supply.** `ensure` reuses one Wix cart per
  identity for 30 days and every physical attempt writes `deliveryInfo.address` onto it, and
  nothing in Cart V2 can clear that field -- so the pointer is abandoned and re-`ensure`d.
* **Both callers of the shared `_v2_snapshot` answer 409, never 500.** `_action` defaults to
  `"create"` for any unrecognised action or path, so a crafted contribution reaching the retained
  in-WhatsApp route must land in an arm that route already has.

Offline throughout: `FakeDynamo` plus `tests/contribution_wix.py`'s stateful Cart V2 fake. No AWS
call, no network, no credential read.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import (  # noqa: E402
    ATTEMPTS_TABLE, CONTACTS_TABLE, CUSTOMER, KEYS_TABLE, OWNED, STORED_PHONE, WIX_ADDRESS,
    _Identity, _load_handler, body_of, create_event, make_env, pointer, prepare_event,
    seed_cart_pointer, seed_contact)
from contribution_wix import (  # noqa: E402
    CART_ID, CONTRIBUTION_CHOICES, CONTRIBUTION_ID, CONTRIBUTION_VARIANT, CONTRIBUTION_VARIANTS,
    ContributionWix, KIOSK_ID, KIOSK_VARIANT, OTHER_ID, OTHER_VARIANT, REPLACEMENT_CART_ID,
    contribution_line, contribution_paise, kiosk_line, other_line, saved)
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402

#: The default choice's paise figure, so no case re-types one. `contribution_line()` defaults to
#: the same variant, so the two cannot drift apart.
DEFAULT_PAISE = contribution_paise()

#: Every `productType` Wix could answer for the contribution product. The delivery skip must be
#: identical across all of them, because it keys on identity -- and the live product is PHYSICAL,
#: so the row that matters most is the one that used to be impossible to reach.
EVERY_PRODUCT_TYPE = ("PHYSICAL", "DIGITAL", "digital", "Digital", "", None, "SERVICE",
                      "DIGITAL_GOODS")


@pytest.fixture
def env(monkeypatch):
    return make_env(monkeypatch)


# ══ T1 — the stale delivery address is abandoned, and only when it should be ══════

@pytest.mark.parametrize("product_type", ["PHYSICAL", "DIGITAL"])
def test_t1_i_a_stale_address_carrying_cart_is_abandoned_for_a_contribution(monkeypatch, caplog,
                                                                           product_type):
    """A contribution landing on the cart a previous kiosk purchase left behind.

    `deliveryInfo.address` survives on that cart for thirty days and no Cart V2 call can clear it,
    so the pointer is abandoned and a fresh cart is minted. Without this the contribution's
    snapshot would freeze a place of supply it does not have, and Wix would price delivery
    against it.

    DRIVEN UNDER BOTH PRODUCT TYPES, and the PHYSICAL row is the one that matters. The abandon is
    gated on `not requires_delivery`, and `requires_delivery` used to come from Wix's
    `productType` alone -- so with the live product being PHYSICAL this block was present in the
    tree and unreachable in production, which is exactly the shape of defect a fixture that agreed
    with the code could not show. The skip now keys on contribution product identity, so the
    answer must be identical either way.
    """
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          delivery_address=dict(WIX_ADDRESS),
                          product_type={CONTRIBUTION_ID: product_type, KIOSK_ID: "PHYSICAL",
                                        OTHER_ID: "PHYSICAL"})
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([contribution_line()]), None)

    assert response["statusCode"] == 200, body_of(response)
    # A second `ensure` ran and minted a DIFFERENT cart. The seeded cart was never created by the
    # fake, so exactly one create is recorded -- the replacement -- and its id is not the
    # abandoned one.
    assert wix.created_carts == [REPLACEMENT_CART_ID]
    assert wix.cart_id == REPLACEMENT_CART_ID != CART_ID
    # The replacement carries no address at all, so the frozen snapshot cannot carry one.
    assert wix.delivery_address is None

    events = [json.loads(rec.message) for rec in caplog.records
              if rec.message.startswith("{")]
    reset = [e for e in events if e.get("event") == "checkout_cart_delivery_reset"]
    assert len(reset) == 1
    assert reset[0]["abandonedCartId"] == CART_ID

    # The abandon is a PUT of an expired pointer, never a delete: the checkout function's IAM has
    # no `DeleteItem` on this table, so a conditional delete would be a production-only 403.
    assert ("delete_item" not in [name for _table, name in fake.calls]
            and not any("delete" in str(name) for _table, name in fake.calls))


def test_t1_i_the_frozen_snapshot_address_is_empty_for_a_contribution(monkeypatch):
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          delivery_address=dict(WIX_ADDRESS))
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)
    h.handler(prepare_event([contribution_line()]), None)

    rows = [row for row in fake.all_rows(KEYS_TABLE)
            if str(row["orderId"]).startswith("PAYREF#")]
    assert len(rows) == 1
    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    frozen = attempts[0]["purchasedSnapshot"]
    assert frozen["address"] in ({}, None), frozen["address"]


def test_t1_ii_a_physical_basket_keeps_its_stale_address_and_reconciles(monkeypatch, caplog):
    """THE CONTROL, and it commits this design to a behaviour that must not move.

    The abandon is gated on `not requires_delivery`. An ORDINARY physical basket therefore never
    reaches it however stale its address is: it falls through to the reconcile, and
    `prepare_delivery` runs and reuses the address. That is deliberate -- a physical line
    genuinely has a place of supply, and discarding it would make every kiosk re-enter an address
    it already saved.

    Note what this control is NOT: it is not "PHYSICAL means no abandon". The contribution product
    is PHYSICAL too and the case above abandons for it, because the skip keys on identity. What
    distinguishes the two baskets is whether the line is a recognised contribution, and this pair
    of cases is where that distinction is pinned.
    """
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          delivery_address=dict(WIX_ADDRESS))
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([kiosk_line(2)]), None)

    assert response["statusCode"] == 200, body_of(response)
    assert wix.created_carts == [], "no cart was replaced"
    assert wix.delivery_address == WIX_ADDRESS, "the stored address was reused, not discarded"
    # `prepare_delivery` ran, which it must for a physical basket. It sets the ADDRESS and
    # deliberately chooses no method, which is the legitimate intermediate state.
    assert any(method == "PATCH" and "deliveryInfo" in ((body or {}).get("cart") or {})
               for method, _path, body in wix.requests)
    events = [json.loads(rec.message) for rec in caplog.records if rec.message.startswith("{")]
    assert not [e for e in events if e.get("event") == "checkout_cart_delivery_reset"]
    # It RECONCILED (the quantity moved 1 -> 2) rather than being replaced.
    assert [c[0] for c in wix.commands] == ["quantity"]


def test_t1_iii_a_busy_pointer_is_refused_by_resolve_before_abandon_is_reached(monkeypatch):
    """A busy row is refused by `ensure`/`resolve`, so `abandon` is never evaluated.

    This is the measured half of `abandon`'s docstring: on the stale-delivery path it runs AFTER
    `ensure`, and `resolve` raises `CartBusy` on a busy row before returning a cart id.
    """
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          delivery_address=dict(WIX_ADDRESS))
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake, busy=True)

    calls = []
    original = h.customer_cart.CustomerCart.abandon
    monkeypatch.setattr(h.customer_cart.CustomerCart, "abandon",
                        lambda self, identity: calls.append(identity) or original(self, identity))

    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_RECONCILIATION_REQUIRED"
    assert calls == [], "abandon must not be reached on the stale-delivery path"


def test_t1_iv_reset_against_a_busy_pointer_refuses_and_changes_nothing(monkeypatch):
    """`resetCart` is the ONE path that reaches `abandon`'s busy refusal, and it refuses.

    A lock means a Wix outcome is unknown. Abandoning the pointer behind one would hide that
    rather than resolve it, so the row must come out byte-identical and no `ensure` may run.
    """
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=wix)
    before = dict(seed_cart_pointer(h, fake, busy=True))

    response = h.handler(prepare_event([contribution_line()], resetCart=True), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_RECONCILIATION_REQUIRED"
    assert pointer(fake) == before, "a locked pointer must be reported, never reset"
    assert wix.created_carts == [], "no `ensure` may run after a refused reset"


# ══ T2 — a contribution checks out on its own ════════════════════════════════════

@pytest.mark.parametrize("basket", [
    [contribution_line(), kiosk_line(1)],
    [kiosk_line(1), contribution_line()],
    [contribution_line(CONTRIBUTION_VARIANTS[1]), other_line(2)],
    [contribution_line(), contribution_line(CONTRIBUTION_VARIANTS[2]), kiosk_line(1)],
])
def test_t2_a_contribution_beside_anything_else_is_refused_before_any_wix_call(monkeypatch, basket):
    """The alone rule is per BASKET, not per line, and it is decided from the request alone.

    `_contribution_request` is pure, so the refusal costs no Wix call, no DynamoDB write and no
    cart -- which is what keeps the leave-nothing-behind invariant true for a refused mix.
    """
    h, fake, wix = make_env(monkeypatch)
    response = h.handler(prepare_event(basket), None)

    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CONTRIBUTION_NOT_ALONE"
    assert wix.calls == [], "the alone check must precede every Wix call"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


@pytest.mark.parametrize("basket", [
    [contribution_line(), contribution_line(CONTRIBUTION_VARIANTS[1])],
    [contribution_line(), contribution_line()],
    [contribution_line(CONTRIBUTION_VARIANTS[2])] * 3,
])
def test_t2_two_contribution_lines_are_refused_rather_than_added_together(monkeypatch, basket):
    """TWO CONTRIBUTIONS IS NOT ONE BIGGER ONE, and this replaced the opposite assertion.

    Under the retired amount-as-quantity model two contribution lines were SUMMED -- Rs.150 plus
    Rs.250 was one Rs.400 collection -- because the amount was a quantity and quantities add.
    With three fixed prices there is nothing to add: `_contribution_request` returns ONE expected
    collection, and no single figure describes a basket holding a Rs.100 and a Rs.250 line. So the
    basket is refused in the same vocabulary as a mixed one, which is honest about what happened
    rather than silently charging one of the two.

    Reachable only from a crafted request: `setContribution` replaces the line rather than adding
    to it, so the browser cannot build this.
    """
    h, fake, wix = make_env(monkeypatch)
    response = h.handler(prepare_event(basket), None)

    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CONTRIBUTION_NOT_ALONE"
    assert wix.calls == []
    assert fake.all_rows(ATTEMPTS_TABLE) == []


# ══ T3 — the delivery skip keys on IDENTITY, not on Wix's `productType` ══════════

@pytest.mark.parametrize("product_type", EVERY_PRODUCT_TYPE)
def test_t3_a_contribution_skips_delivery_whatever_wix_calls_the_product(monkeypatch,
                                                                        product_type):
    """THE FIX FOR THE DEFECT THIS FILE PREVIOUSLY ENCODED AS CORRECT.

    `wix_ecom.resolved_catalog_lines` reads Wix's `productType` and fails closed to "needs an
    address" for anything that is not `DIGITAL`. That default is right for a catalogue product and
    wrong for a contribution: the live `Contribute` product is PHYSICAL, because a Wix digital
    product with no downloadable file attached is not purchasable. Keyed on `productType` alone, a
    donation is refused for want of a stored address, a postal address is written onto its Wix
    cart, and the stale-address abandon never runs -- while the browser's `cartRequiresDelivery()`
    keys on identity and says the opposite about the same basket.

    So the answer must be the same for every value Wix could return, including the empty and
    unrecognised ones. This runs with NO stored address at all, so a `productType`-keyed skip
    fails the PHYSICAL row loudly.
    """
    wix = ContributionWix(product_type={CONTRIBUTION_ID: product_type,
                                        KIOSK_ID: "PHYSICAL", OTHER_ID: "PHYSICAL"})
    h, _fake, wix = make_env(monkeypatch, wix=wix, address=None)
    response = h.handler(prepare_event([contribution_line()]), None)

    assert response["statusCode"] == 200, body_of(response)
    # No address was asked for, and none was written onto the cart: a payment with no delivery has
    # no destination, and writing one would claim a place of supply that does not exist.
    assert not any(path.endswith("/set-delivery-method") for path in wix.paths())
    assert wix.delivery_address is None


@pytest.mark.parametrize("product_type,needs_address", [
    ("DIGITAL", False),
    # Case is NORMALISED, not refused: the implemented expression is
    # `str(productType or '').upper() != 'DIGITAL'`. A lowercase `digital` is still Wix's own
    # value saying the product is digital, so reading it case-insensitively is a case-insensitive
    # read of an enum rather than a fail-open -- nothing is being guessed.
    ("digital", False),
    ("Digital", False),
    ("PHYSICAL", True),
    ("", True),
    (None, True),
    ("SERVICE", True),
    ("DIGITAL_GOODS", True),
])
def test_t3_an_ordinary_line_still_reads_productType_and_fails_closed(monkeypatch, product_type,
                                                                     needs_address):
    """THE CONTROL: the `productType` rule is untouched for every line that is NOT a contribution.

    Absent, empty and unrecognised all still mean "needs an address". Asking for an address
    unnecessarily annoys a customer; not asking ships a physical order nowhere with the wrong GST
    split. The identity override narrows that rule rather than replacing it, and a real physical
    product must still demand an address.
    """
    wix = ContributionWix(product_type={KIOSK_ID: product_type,
                                        CONTRIBUTION_ID: "PHYSICAL", OTHER_ID: "PHYSICAL"},
                          delivery_address=None)
    h, _fake, wix = make_env(monkeypatch, wix=wix, address=None)
    response = h.handler(prepare_event([kiosk_line(1)]), None)

    if needs_address:
        assert response["statusCode"] == 409
        assert body_of(response)["error"] == "DELIVERY_DETAILS_REQUIRED"
        assert wix.wrote() == [], "the refusal still precedes every Wix WRITE"
    else:
        assert response["statusCode"] == 200, body_of(response)
        assert not any(path.endswith("/set-delivery-method") for path in wix.paths())


def test_t3_the_delivery_decision_never_reads_productType_for_a_contribution_line(monkeypatch):
    """A SOURCE-LEVEL pin on where the override lives, because a correct answer reached the wrong
    way is the thing that regressed here once already.

    `_v2_catalog_items` must consult `_is_contribution_id` when it folds the per-line
    `requiresDelivery` flags together. `wix_ecom.resolved_catalog_lines` must keep its
    `productType` rule untouched and must NOT learn about contributions -- a catalogue reader that
    knew about payment vehicles would be the wrong place for the knowledge, and it is shared with
    `normalized_catalog_items`.
    """
    import ast
    tree = _tree("amplify/functions/ecommerce/checkout/handler.py")
    fold = [node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_v2_catalog_items"]
    assert fold, "_v2_catalog_items must exist"
    body = ast.unparse(fold[0])
    assert "_is_contribution_id" in body
    assert "requiresDelivery" in body
    catalogue = (ROOT / "amplify/functions/shared/lambda_utils/wix_ecom.py").read_text()
    assert "contribution" not in catalogue.lower()


def test_t3_a_mixed_basket_cannot_reach_the_delivery_question_at_all(monkeypatch):
    """`any(requiresDelivery)` is never consulted for a mix, because the mix is refused first."""
    h, _fake, wix = make_env(monkeypatch, address=None)
    response = h.handler(prepare_event([contribution_line(), kiosk_line(1)]), None)
    assert body_of(response)["error"] == "CONTRIBUTION_NOT_ALONE"
    assert wix.calls == []


# ══ T4 — the choice is one of three, and a bad one costs no Wix call ════════════

#: What this block replaced. There used to be a `[9, 100001, 0, -5]` parametrisation proving an
#: out-of-RANGE amount refused as `CONTRIBUTION_AMOUNT_INVALID` rather than as a 502, and a
#: `[10, 200, 400, 600, 100000]` parametrisation proving an in-range one priced at `quantity x
#: 100`. There is no range any more and no amount on the wire: the browser names a variant, so the
#: only question is whether that variant is one of the three. The refusal CODE is unchanged, which
#: is what keeps the cart page's existing arm correct.

@pytest.mark.parametrize("variant", [
    "ffffffff-0000-4000-8000-000000000999",      # a real GUID, not a contribution variant
    "",                                          # no variant at all
    None,
    CONTRIBUTION_ID,                             # the PRODUCT id, as a variant id
])
def test_t4_an_unknown_choice_is_a_contribution_refusal_not_a_catalogue_error(monkeypatch,
                                                                             variant):
    """`CONTRIBUTION_AMOUNT_INVALID`, never `502 CATALOGUE_UNAVAILABLE`.

    This is why the pure pre-check must run BEFORE `resolved_catalog_lines`: that function refuses
    an unresolvable variant as a `WixEcomError`, which maps to 502 -- a catalogue-outage answer
    for what is really "that is not one of the three contributions", and one with no action
    attached.
    """
    h, fake, wix = make_env(monkeypatch)
    line = contribution_line()
    line["catalogReference"]["options"] = {"variantId": variant}
    response = h.handler(prepare_event([line]), None)

    assert response["statusCode"] == 409
    payload = body_of(response)
    assert payload["error"] == "CONTRIBUTION_AMOUNT_INVALID"
    assert payload["reason"] == "UNKNOWN_CHOICE"
    # The three amounts travel so the browser can say what IS accepted. No min/max, because there
    # is no range to describe.
    assert payload["choicesPaise"] == sorted(CONTRIBUTION_CHOICES.values())
    assert "min" not in payload and "max" not in payload
    assert wix.calls == [], "no Wix call at all for a refused choice"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


@pytest.mark.parametrize("quantity", [True, False, 2, 400, 0, -5, 1.0, "1", None, [1], {"q": 1}])
def test_t4_only_quantity_one_is_accepted_and_a_bool_is_not_one(monkeypatch, quantity):
    """A contribution is ONE fixed-price line, so 1 is the only acceptable quantity.

    `type(q) is not int`, not `isinstance`: `isinstance(True, int)` is True, so an isinstance
    check would read `quantity: true` as 1 and charge for it. `2` is refused for a different
    reason -- two of a Rs.250 variant is a Rs.500 collection the committed choice map does not
    describe, and the browser cannot produce it.
    """
    h, _fake, wix = make_env(monkeypatch)
    response = h.handler(prepare_event([contribution_line(quantity=quantity)]), None)
    assert response["statusCode"] == 409
    payload = body_of(response)
    assert payload["error"] == "CONTRIBUTION_AMOUNT_INVALID"
    assert payload["reason"] == "INVALID_QUANTITY"
    assert wix.calls == []


@pytest.mark.parametrize("variant", CONTRIBUTION_VARIANTS)
def test_t4_each_of_the_three_choices_is_accepted_end_to_end(monkeypatch, variant):
    """All three, priced by Wix at the variant's own price, collected to the paise."""
    h, fake, _wix = make_env(monkeypatch)
    response = h.handler(prepare_event([contribution_line(variant)]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert fake.all_rows(ATTEMPTS_TABLE)[0]["amountPaise"] == contribution_paise(variant)


def test_t4_the_three_committed_choices_are_the_owners_three(monkeypatch):
    """The GUIDs and amounts, pinned once in Python so a typo in one is visible here.

    These are MEASURED values: the variant ids and prices were read off the live
    `GET /stores/v3/products/{id}` for the `Contribute` product on 2026-10-04, not transcribed
    from an instruction. The matching TS declaration is pinned against this one by
    tests/test_blog_contribution.py::test_server_choices_mirror_the_frontend_contract.
    """
    from lambda_utils.ecommerce import blog_contribution as bc
    assert bc.CONTRIBUTION_PRODUCT_IDS == frozenset({"af326b8c-f373-45ea-ad0d-b7a38b8ce0cc"})
    assert dict(bc.CONTRIBUTION_CHOICES_PAISE) == {
        "166ba5b0-a0da-4ea2-b1d2-032af12e916d": 10000,
        "81d2d73a-b4ab-43fb-8043-505971763bcc": 25000,
        "8594562c-286e-48fc-b854-b09a863ba031": 50000,
    }
    # Every amount an integer number of paise, and every id lowercase so `_is_contribution_id`'s
    # `.lower()` can never miss a member of its own set.
    for variant, paise in bc.CONTRIBUTION_CHOICES_PAISE.items():
        assert type(paise) is int and paise > 0
        assert variant == variant.lower()
    # The Rs.1 test product is a STANDALONE shop listing, not a contribution vehicle. Named here
    # because it shares the "a one-rupee product" shape with the retired contribution model.
    assert "15a80e88-97b5-4603-86bf-c4864082b328" not in bc.CONTRIBUTION_PRODUCT_IDS


# ══ T5 — the total guard, and the five refusals it distinguishes ═════════════════

def test_t5_the_happy_case_charges_exactly_the_contributed_amount(monkeypatch):
    """The committed choice figure == Wix's collection == total payable. Under fee-exemption all
    three coincide, and that is a property worth asserting rather than a coincidence."""
    h, fake, _wix = make_env(monkeypatch)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 200, body_of(response)

    attempt = fake.all_rows(ATTEMPTS_TABLE)[0]
    assert attempt["amountPaise"] == DEFAULT_PAISE
    assert type(attempt["amountPaise"]) is int
    reserved = [row for row in fake.all_rows(KEYS_TABLE)
                if str(row["orderId"]).startswith("PAYREF#")][0]
    assert int(reserved["collectionPaise"]) == DEFAULT_PAISE
    assert int(reserved["amountPaise"]) == DEFAULT_PAISE
    assert reserved["currency"] == "INR"


@pytest.mark.parametrize("kwargs,expected", [
    ({"tax_rupees": 72}, "CART_NOT_PAYABLE"),
    ({"delivery_rupees": 50}, "CART_NOT_PAYABLE"),
    ({"fees_rupees": 10}, "CART_NOT_PAYABLE"),
    ({"discount_rupees": 40}, "CART_NOT_PAYABLE"),
])
def test_t5_a_misconfigured_contribution_product_is_refused_loudly(monkeypatch, kwargs, expected):
    """A dashboard mistake must refuse on the FIRST attempt, never over-charge.

    Asserted on `componentsPaise["total"]` rather than on the per-line `totalPrice`, because the
    line figure sums to `subtotal` and is pre-tax -- so a taxable Contribution product passes a
    line check while over-charging.
    """
    wix = ContributionWix(**kwargs)
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == expected
    assert fake.all_rows(ATTEMPTS_TABLE) == [], "nothing is reserved for a refused total"


def test_t5_a_customer_applied_coupon_names_its_own_recoverable_action(monkeypatch):
    """A redemption the customer applied is RECOVERABLE and a misconfiguration is not, so they
    get different codes. Telling someone to review a cart they cannot fix is the dead-end class
    this phase exists to remove."""
    wix = ContributionWix(coupons=[{"id": "c1", "code": "SAVE10"}])
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CONTRIBUTION_REDEMPTION_NOT_ALLOWED"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t5_the_redemption_refusal_logs_two_booleans_and_no_code(monkeypatch, caplog):
    wix = ContributionWix(coupons=[{"id": "c1", "code": "SAVE10"}])
    h, _fake, _wix = make_env(monkeypatch, wix=wix)
    with caplog.at_level("INFO"):
        h.handler(prepare_event([contribution_line()]), None)
    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    refused = [e for e in events if e.get("event") == "contribution_redemption_refused"]
    assert len(refused) == 1
    assert refused[0] == {"event": "contribution_redemption_refused",
                          "hasCoupon": True, "hasGiftCard": False}
    assert "SAVE10" not in caplog.text


def test_t5_an_ordinary_kiosk_basket_is_untouched_by_the_total_guard(monkeypatch):
    """The guard runs only when `contribution_paise is not None`. A kiosk basket carries real
    tax and delivery and must not be refused by it."""
    wix = ContributionWix(delivery_address=dict(WIX_ADDRESS), delivery_rupees=500)
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert fake.all_rows(ATTEMPTS_TABLE)


# ══ T5a — the fee exemption, proven per basket ═══════════════════════════════════

@pytest.mark.parametrize("variant", CONTRIBUTION_VARIANTS)
def test_t5a_a_contribution_pays_no_convenience_fee_and_no_gst_on_one(monkeypatch, variant):
    """OWNER DECISION [PHASE2-FEE-001]: a Rs.100 contribution collects Rs.100.00, to the paise.

    A Rs.102.95 total would mean `exempt_quote` was not substituted, which is a FAILURE rather
    than a variant: `compute_quote` would have added 2.5% plus 18% GST on that fee. Driven for all
    three choices, because the fee is proportional and would be invisible at only one amount.
    """
    paise = contribution_paise(variant)
    h, fake, _wix = make_env(monkeypatch)
    h.handler(prepare_event([contribution_line(variant)]), None)

    attempt = fake.all_rows(ATTEMPTS_TABLE)[0]
    frozen = attempt["purchasedSnapshot"]
    quote = frozen["quote"] if "quote" in frozen else frozen
    components = quote if "convenienceFeePaise" in quote else frozen["components"]
    assert int(components["convenienceFeePaise"]) == 0
    assert int(components["convenienceGstPaise"]) == 0
    assert int(components["totalPayablePaise"]) == paise
    assert int(components["collectionBeforeConveniencePaise"]) == paise
    # And the gateway leg is the bare amount.
    assert int(attempt["amountPaise"]) == paise


def test_t5a_an_ordinary_basket_still_pays_the_fee(monkeypatch):
    """The substitution is PER BASKET, not global. 2.5% of 24999.00 plus 18% GST on the fee."""
    wix = ContributionWix(delivery_address=dict(WIX_ADDRESS))
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    h.handler(prepare_event([kiosk_line(1)]), None)

    collection = 2499900
    fee = cp.round_half_up(collection, cp.CONVENIENCE_FEE_BPS)
    gst = cp.round_half_up(fee, cp.CONVENIENCE_GST_BPS)
    assert fee > 0 and gst > 0
    assert int(fake.all_rows(ATTEMPTS_TABLE)[0]["amountPaise"]) == collection + fee + gst


def test_t5a_an_unresolvable_stored_address_still_reaches_intra_state_true(monkeypatch):
    """The reachable `intra_state is None` case, written against the state that can occur.

    NOT "a contribution has no address": every checkout identity has one, because
    `auth/customer-profile` refuses an addressless create. The producible case is a LEGACY contact
    row whose stored address no longer resolves -- `contact_address.from_contact` rejects it --
    so `owned` is falsy and `exempt_quote` normalises the unknown to intra-state. `split_gst`
    treats `None` as falsy and would store `intraState: false`, a value that changes no total but
    is printed on a receipt and is covered by `basket_hash`.
    """
    h, fake, _wix = make_env(
        monkeypatch, real_loader=True,
        address={"addressLine1": "12 MG Road", "city": "Bengaluru",
                 "state": "Nowhere Pradesh", "postalCode": "560001"})
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 200, body_of(response)

    frozen = fake.all_rows(ATTEMPTS_TABLE)[0]["purchasedSnapshot"]
    blob = json.dumps(frozen, default=str)
    assert '"intraState": true' in blob.replace("True", "true"), blob[:400]


@pytest.mark.parametrize("quote_fn", ["exempt_quote", "compute_quote"])
@pytest.mark.parametrize("bad", [400.0, True, "40000", None])
def test_t5a_both_calculators_refuse_the_same_bad_collection(quote_fn, bad):
    """"Same signature" is not "same refusals". A substituted calculator that validated LESS than
    the one it replaces would make the exempt path the lenient side of a seam whose whole job is
    to be the strict one."""
    fn = getattr(cp, quote_fn)
    with pytest.raises(cp.PricingError):
        fn(bad)


@pytest.mark.parametrize("quote_fn", ["exempt_quote", "compute_quote"])
def test_t5a_both_calculators_refuse_a_non_integral_decimal_and_a_non_inr_currency(quote_fn):
    from decimal import Decimal
    fn = getattr(cp, quote_fn)
    with pytest.raises(cp.PricingError):
        fn(Decimal("400.5"))
    with pytest.raises(cp.PricingError):
        fn(40000, currency="USD")
    with pytest.raises(cp.PricingError):
        fn(-1)


def test_t5a_exempt_quote_stamps_the_shared_policy_version(monkeypatch):
    """A substituted calculator that invented its own version string would be refused at
    `build_intent_with_calculation`'s re-validation seam, which is the point of the constant."""
    quote = cp.exempt_quote(40000)
    assert quote.policy_version == cp.CALCULATION_POLICY_VERSION
    assert quote.policy_version == cp.compute_quote(40000).policy_version
    assert quote.total_payable_paise == quote.collection_before_convenience_paise == 40000
    assert quote.convenience_fee_paise == 0 and quote.convenience_gst_paise == 0
    assert quote.convenience_gst_split.intra_state is True


def test_t5a_exempt_quote_performs_no_float_arithmetic():
    """Integer paise in, integer paise out, and every component an `int` rather than a float."""
    quote = cp.exempt_quote(40000)
    for value in (quote.collection_before_convenience_paise, quote.convenience_fee_paise,
                  quote.convenience_gst_paise, quote.total_payable_paise):
        assert type(value) is int
    assert quote.currency == "INR"


# ══ T5b — quantity is a genuine COUNT now, and the projection needs no exception ══

def test_t5b_a_contribution_projects_as_one_item_with_the_amount_in_its_name(monkeypatch):
    """The projection `_create` hands to the WhatsApp `item_summary`.

    Under the retired amount-as-quantity model this needed a special case: a Rs.400 contribution
    was `quantity: 400`, so reporting the figure verbatim rendered "Contribution x 400" in a
    message to a customer -- a count that was really money. A contribution is a fixed-price
    variant at quantity 1 now, so the confirmed quantity IS an honest count, the special case is
    gone, and the amount travels in the line NAME that Wix itself supplies.
    """
    wix = ContributionWix()
    h, _fake, wix = make_env(monkeypatch, wix=wix)
    identity = _Identity()
    _snapshot, items, _calculated = h._v2_snapshot(
        identity, [contribution_line()], profile=None)
    assert [item["quantity"] for item in items] == [1]
    assert items[0]["name"] == "Contribute \u20b9100"


def test_t5b_a_kiosk_line_still_projects_its_real_count(monkeypatch):
    wix = ContributionWix(lines=[], delivery_address=dict(WIX_ADDRESS))
    h, _fake, wix = make_env(monkeypatch, wix=wix)
    _snapshot, items, _calc = h._v2_snapshot(_Identity(), [kiosk_line(3)], profile=None)
    assert [item["quantity"] for item in items] == [3]


def test_t5b_recognition_takes_an_id_so_each_call_site_owns_its_own_shape(monkeypatch):
    """A Wix CART line nests its catalogue reference under `source`. A top-level read would return
    None on every line, so the ternary would always take its else arm and this would FAIL OPEN to
    "Contribution x 400" with no exception and no log line. The negative case proves the helper
    reads an ID rather than a line: handed a top-level `catalogItemId`, `_is_contribution_id`
    still answers correctly because the CALL SITE owns the shape.
    """
    h = _load_handler(monkeypatch, contribution_env=CONTRIBUTION_ID)
    # The id form is shape-agnostic by construction -- that is why the parameter is an id.
    assert h._is_contribution_id(CONTRIBUTION_ID) is True
    assert h._is_contribution_id(CONTRIBUTION_ID.upper()) is True
    assert h._is_contribution_id(KIOSK_ID) is False
    assert h._is_contribution_id(None) is False
    assert h._is_contribution_id("") is False


def test_t5b_the_frozen_snapshot_keeps_the_quantity_wix_froze(monkeypatch):
    """The frozen copy must NOT be edited. It is the money evidence `cart_v2.calculate`
    reconciles against (the line sum is asserted equal to `components["subtotal"]`), and
    `basket_hash` hashes it. Rewriting a quantity inside it would falsify the record that proves
    what was charged, in order to improve a sentence on a PDF.

    The figure is 1 now rather than 400, which is the whole model change in one assertion: the
    frozen record and the customer-facing projection no longer disagree, because the quantity no
    longer carries money.
    """
    h, fake, _wix = make_env(monkeypatch)
    h.handler(prepare_event([contribution_line()]), None)
    frozen = fake.all_rows(ATTEMPTS_TABLE)[0]["purchasedSnapshot"]
    assert [int(item["quantity"]) for item in frozen["items"]] == [1]


def test_t5b_two_request_lines_for_the_same_choice_are_refused_before_any_merge(monkeypatch):
    """Wix WOULD merge two identical catalogue references into one line of quantity 2, and that is
    exactly why this is refused in the pure pre-check instead.

    A merged line of quantity 2 prices at twice the variant -- a Rs.200 collection against a
    Rs.100 expectation -- so `_assert_contribution_total` would catch it. The refusal happens
    earlier and names the real problem: two contributions in one basket.
    """
    h, _fake, wix = make_env(monkeypatch)
    with pytest.raises(h.ContributionNotAlone):
        h._v2_snapshot(_Identity(), [contribution_line(), contribution_line()], profile=None)
    assert wix.calls == []


def test_t5b_a_contribution_beside_a_kiosk_would_project_separately_but_is_refused_first(
        monkeypatch):
    """The mixed projection is unreachable, and this records WHY rather than leaving a gap:
    `_contribution_request`'s alone rule refuses before any cart exists to project from."""
    h, _fake, wix = make_env(monkeypatch)
    with pytest.raises(h.ContributionNotAlone):
        h._v2_snapshot(_Identity(), [contribution_line(), kiosk_line(1)], profile=None)
    assert wix.calls == []


# ══ T6 — the product invariants, as the failures they produce ═══════════════════

def test_t6_an_ordinary_products_unresolvable_variant_is_still_a_catalogue_refusal(monkeypatch):
    """THE CATALOGUE-REFUSAL PATH, driven through a product that is not a contribution.

    `resolved_catalog_lines` answers 'choose an available product option' when no `variantId`
    resolves, and the route maps that to 409 `CART_ITEM_UNAVAILABLE`. That arm must keep working:
    this is a real catalogue problem, pointing at a Wix dashboard field.

    THE STATUS IS 409, NOT 502, and it was 502 when this case was written. A separate change
    merged to `stack` ("surface unavailable cart item as 409, not a silent 502") re-read this
    condition as PERMANENT and caller-fixable -- remove the item -- rather than as an outage the
    customer should read as "we failed". This case follows that decision rather than re-asserting
    the status it replaced; what this phase contributes to the same arm is the `detail` log field,
    pinned by `test_t6_a_catalogue_refusal_records_WHICH_wix_call_failed`.

    It can no longer be reached through the contribution product, which is the change worth
    recording. A contribution line carrying an unknown variant is refused by the pure pre-check as
    `CONTRIBUTION_AMOUNT_INVALID` / `UNKNOWN_CHOICE` -- see T4 -- because "that is not one of the
    three contributions" is a better answer to a customer than "the catalogue is unavailable".
    """
    wix = ContributionWix(variant_count=3, delivery_address=dict(WIX_ADDRESS))
    h, _fake, _wix = make_env(monkeypatch, wix=wix)
    line = kiosk_line(1)
    line["catalogReference"]["options"] = {"variantId": "ffffffff-0000-4000-8000-000000000999"}
    response = h.handler(prepare_event([line]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_ITEM_UNAVAILABLE"


def test_t6_the_contribution_product_genuinely_has_three_variants(monkeypatch):
    """So the explicit `variantId` is MANDATORY, not merely preferred.

    `resolved_catalog_lines` only falls back to a product's single variant when there is exactly
    one. With three there is no fallback, and a line with no variant would answer 'choose an
    available product option'. That is why `setContribution` writes the variant id and why
    `CONTRIBUTION_CONFIGURED` requires all three to be declared.
    """
    h, _fake, wix = make_env(monkeypatch)
    assert len(wix.variants[CONTRIBUTION_ID]) == 3
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 200, body_of(response)
    # The variant the browser named is the one that reached Wix, unguessed.
    created = [body for _m, path, body in wix.requests
               if path == "/ecom/v2/carts" and body]
    assert created[0]["catalogItems"][0]["catalogReference"]["options"]["variantId"] \
        == CONTRIBUTION_VARIANT


def test_t6_a_catalogue_refusal_records_WHICH_wix_call_failed(monkeypatch, caplog):
    """A refusal that names nothing is a live defect with no evidence, and that is what shipped.

    `wix_ecom` raises `WixEcomError` from FIFTEEN places and logs from none of them, and this arm
    discarded the exception entirely -- so a failed checkout in production left the customer's
    sentence on screen as the only trace. This pins the log line that fixes that.

    The STATUS is incidental to this case and belongs to a separate change (409
    `CART_ITEM_UNAVAILABLE` rather than the 502 this arm used to answer); the `detail` field is
    what is being pinned, and it is what names the raise site regardless of the status.

    It also pins what is NOT in it: no credential-shaped material and no customer field. The
    message is built by our own code from the HTTP method, the endpoint and the status code, which
    is the condition under which the secret-handling rule permits logging an exception's text.
    """
    wix = ContributionWix(in_stock=False)
    h, _fake, _wix = make_env(monkeypatch, wix=wix)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409

    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    recorded = [e for e in events if e.get("event") == "website_checkout_catalogue_unavailable"]
    assert len(recorded) == 1
    assert recorded[0]["error"] == "WixEcomError"
    # The DETAIL is the point: it distinguishes this raise site from the other fourteen.
    assert recorded[0]["detail"] == "choose an available product option"
    # Nothing customer-identifying travels with it. The stored phone is the sharpest thing in
    # scope at this point in the request, so it is the one asserted absent.
    assert STORED_PHONE not in json.dumps(recorded[0])
    assert "asha@example.com" not in json.dumps(recorded[0])


def test_t6_an_out_of_stock_variant_is_a_catalogue_refusal_not_a_quantity_one(monkeypatch):
    """`normalized_catalog_items` filters variants on `visible AND inventoryStatus.inStock`, so an
    untracked product whose variant reports `inStock: false` never reaches `calculate` at all.

    THE DISTINCTION IS NOW CARRIED BY THE ERROR CODE, NOT THE STATUS. These three refusals used to
    be separable as 502-versus-409; since the catalogue arm became 409 `CART_ITEM_UNAVAILABLE` all
    three are 409, and they still point at different Wix dashboard fields:

      * `CART_ITEM_UNAVAILABLE` -- the variant did not resolve at catalogue lookup (this case)
      * `ITEMS_UNAVAILABLE`     -- the priced line came back with an unavailable status
      * `QUANTITY_REDUCED`      -- Wix priced a smaller quantity than was asked for

    So this asserts the CODE rather than the status, which is the part that identifies the field to
    go and fix.
    """
    wix = ContributionWix(in_stock=False)
    h, _fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_ITEM_UNAVAILABLE"


def test_t6_a_reduced_confirmed_quantity_is_refused_and_named(monkeypatch):
    """Tracked inventory makes Wix reduce `confirmedQuantity`, and it prices the reduced amount --
    so the money reconciles perfectly while being the total for something the customer did not
    choose. Refused and shown.

    MUCH HARDER TO REACH NOW, and worth saying why the case stays. A contribution is quantity 1,
    so a reduction needs the variant to be out of stock entirely rather than merely short of a
    400-unit request -- which is the second-order hazard a PHYSICAL contribution product brings
    with it. The refusal is the fail-closed direction either way, and the arm must keep working.
    """
    wix = ContributionWix(confirmed_delta=-1)
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "QUANTITY_REDUCED"
    assert body_of(response)["items"]
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t6_an_unavailable_line_is_its_own_named_refusal(monkeypatch):
    wix = ContributionWix(line_status="OUT_OF_STOCK")
    h, _fake, _wix = make_env(monkeypatch, wix=wix)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "ITEMS_UNAVAILABLE"


def test_t6_wix_demanding_delivery_for_a_contribution_names_its_own_refusal(monkeypatch, caplog):
    """A site-configuration fault, not a customer step, so it is NOT reported as
    `DELIVERY_DETAILS_REQUIRED` -- which would open an address editor for a customer whose address
    is already complete and whose cart will never have one written to it. Saving it again changes
    nothing, forever.

    AND NOT `CART_NOT_PAYABLE` EITHER, which is what this asserted until review pass 3. That code
    carries "Please review your cart and try again", and the basket is one donation: there is
    nothing in it to review and no edit that changes the answer. The live `Contribute` product is
    PHYSICAL, so this is also the arm that fires if Wix wants a shipping destination for physical
    goods -- ordinary Wix behaviour, unmeasured, and therefore possibly the path every
    contribution takes rather than a rare dashboard fault. A distinct code also separates it from
    the shipping-rate and tax-class refusals `_assert_contribution_total` raises, which a shared
    `CART_NOT_PAYABLE` could not.
    """
    wix = ContributionWix(require_delivery_on_calculate=True)
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CONTRIBUTION_NOT_PAYABLE"
    # The copy must not name an action: there is none. And it must say nothing was charged,
    # because the refusal arrives after the Checkout press.
    assert "review your cart" not in body_of(response)["message"].lower()
    assert "Nothing has been charged." in body_of(response)["message"]
    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    blocked = [e for e in events if e.get("event") == "website_checkout_delivery_blocked"]
    assert blocked and blocked[0]["requiresDelivery"] is False
    assert [e for e in events if e.get("event") == "contribution_not_payable"]
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t6_the_same_refusal_on_an_ORDINARY_no_delivery_basket_keeps_the_generic_code(monkeypatch,
                                                                                      caplog):
    """The split is contribution-scoped, deliberately.

    `requires_delivery` is false for any basket no line of which needs delivery, so an all-digital
    ordinary basket reaches the same branch. It is unreachable today -- all seven shop products are
    PHYSICAL -- but "contributions cannot be taken right now" would be a false sentence about a
    basket of goods, so that case keeps `CART_NOT_PAYABLE`. Driven by typing the KIOSK product
    `DIGITAL`, which is what makes `requires_delivery` false without a contribution in the basket.
    """
    wix = ContributionWix(require_delivery_on_calculate=True,
                          product_type={KIOSK_ID: "DIGITAL"})
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    # Reached the SAME branch rather than failing earlier for some other reason, which is what
    # makes this a comparison of the two arms and not just a second 409.
    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    blocked = [e for e in events if e.get("event") == "website_checkout_delivery_blocked"]
    assert blocked and blocked[0]["requiresDelivery"] is False
    assert [e for e in events if e.get("event") == "contribution_not_payable"] == []
    assert fake.all_rows(ATTEMPTS_TABLE) == []


# ══ T7 — the kill switch ════════════════════════════════════════════════════════

def test_t7_with_the_env_key_unset_a_recognised_contribution_is_refused(monkeypatch):
    """THE KILL SWITCH, and the reason the recognition set is committed rather than configured.

    Unsetting the env key must REFUSE a contribution basket. If recognition came from the env key
    too, unsetting it would leave the line pricing as an ordinary Rs.1 product with the bounds
    check, the alone check and the total guard all sitting out -- a de-guard dressed as a switch.
    """
    h, fake, wix = make_env(monkeypatch, contribution_env="")
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CONTRIBUTION_UNAVAILABLE"
    assert wix.calls == [], "nothing is created for an unconfigured contribution"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t7_with_the_env_key_unset_an_ordinary_basket_is_unaffected(monkeypatch):
    """The switch is contribution-scoped. The shop must keep working with the key empty."""
    wix = ContributionWix(delivery_address=dict(WIX_ADDRESS))
    h, fake, _wix = make_env(monkeypatch, wix=wix, contribution_env="")
    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert fake.all_rows(ATTEMPTS_TABLE)


def test_t7_a_stale_committed_id_is_still_recognised_and_still_gated(monkeypatch):
    """An id is added to the committed set and never removed: a RETIRED vehicle must stay
    recognisable, so a line carrying it refuses rather than being priced as an ordinary product."""
    retired = "deadbeef-0000-4000-8000-000000000001"
    h, _fake, wix = make_env(monkeypatch, contribution_env=CONTRIBUTION_ID,
                             committed=(CONTRIBUTION_ID, retired))
    line = contribution_line()
    line["catalogReference"]["catalogItemId"] = retired
    response = h.handler(prepare_event([line, kiosk_line(1)]), None)
    assert body_of(response)["error"] == "CONTRIBUTION_NOT_ALONE"
    assert wix.calls == []


def test_t7_the_env_id_alone_cannot_introduce_an_unrecognised_vehicle(monkeypatch):
    """A set env id is by definition recognised, because `_contribution_ids` is a union."""
    h = _load_handler(monkeypatch, contribution_env=CONTRIBUTION_ID, committed=())
    assert h._contribution_ids() == {CONTRIBUTION_ID}
    assert h._is_contribution_id(CONTRIBUTION_ID) is True


def test_t7_with_nothing_configured_at_all_no_contribution_code_runs(monkeypatch):
    """Empty committed set AND empty env: `_contribution_request` returns None immediately, so a
    basket carrying what WOULD be a contribution is just an ordinary product."""
    h = _load_handler(monkeypatch, contribution_env="", committed=())
    assert h._contribution_ids() == set()
    assert h._contribution_request([contribution_line()]) is None


def test_t7_a_malformed_line_items_is_not_recognised_as_a_contribution(monkeypatch):
    """Deliberately tolerant: anything whose shape it cannot read falls through to
    `resolved_catalog_lines`, which already owns the strict shape refusals and must stay the
    single place they live."""
    h = _load_handler(monkeypatch, contribution_env=CONTRIBUTION_ID)
    for junk in (None, "lineItems", 5, {}, [None], [5], ["x"], [{"catalogReference": 7,
                                                                "quantity": 1}]):
        assert h._contribution_request(junk) is None


# ══ T7b — `_create` answers 409 across the whole matrix, never 500 ══════════════

@pytest.mark.parametrize("basket,expected", [
    # An unknown choice and a wrong quantity are `ContributionRejected`, which is a `ValueError`.
    ([contribution_line("ffffffff-0000-4000-8000-000000000999")], "AMOUNT_NOT_SETTLED"),
    ([contribution_line(quantity=2)], "AMOUNT_NOT_SETTLED"),
    ([contribution_line(quantity=True)], "AMOUNT_NOT_SETTLED"),
    # The three `CartContractError` subclasses land in the existing `CART_NOT_PAYABLE` arm.
    ([contribution_line(), kiosk_line(1)], "CART_NOT_PAYABLE"),
    ([contribution_line(), contribution_line(CONTRIBUTION_VARIANTS[1])], "CART_NOT_PAYABLE"),
])
def test_t7b_the_create_route_refuses_a_contribution_in_its_own_vocabulary(monkeypatch, basket,
                                                                          expected):
    """The exceptions are raised from the SHARED `_v2_snapshot`, so both callers need an answer
    and neither may be a 500. `_create` gets a correct 409 in the vocabulary it already speaks --
    not four new codes a WhatsApp flow would never render.

    `ContributionRejected` is a `ValueError`, so it lands in `_create`'s trailing
    `except ValueError`; the three `CartContractError` subclasses land in its existing
    `CART_NOT_PAYABLE` arm. Derived from bare `Exception` -- as an earlier draft had them -- every
    one of these answered `500 INTERNAL_ERROR` instead.
    """
    h, fake, _wix = make_env(monkeypatch)
    response = h.handler(create_event(basket), None)
    assert response["statusCode"] == 409, body_of(response)
    assert body_of(response)["error"] == expected
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t7b_the_create_route_refuses_an_unconfigured_contribution_as_cart_not_payable(monkeypatch):
    h, _fake, _wix = make_env(monkeypatch, contribution_env="")
    response = h.handler(create_event([contribution_line()]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"


def test_t7b_an_unrecognised_action_routes_to_create_and_still_answers_409(monkeypatch):
    """`_action` returns `"create"` for any unrecognised action or path, so the dispatch default
    is part of the matrix rather than an edge case."""
    h, _fake, _wix = make_env(monkeypatch)
    event = create_event([contribution_line(), kiosk_line(1)])
    body = json.loads(event["body"])
    body["action"] = "not-an-action"
    event["body"] = json.dumps(body)
    event["rawPath"] = "/ecommerce/something-else"
    response = h.handler(event, None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"


def test_t7b_the_create_route_never_reconciles_a_saved_cart(monkeypatch):
    """`reconcile=True` is passed by `_website_snapshot` alone. The WhatsApp path has no cart
    page the customer is looking at, so it keeps refusing a mismatched saved cart."""
    wix = ContributionWix(lines=[saved(OTHER_ID, OTHER_VARIANT, 1)],
                          delivery_address=dict(WIX_ADDRESS))
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)
    response = h.handler(create_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    assert wix.commands == [], "the create route issues no reconcile command"


# ══ money correctness: integer paise, explicit INR, no float in the payment path ══

def _tree(relative):
    import ast
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


#: The modules Phase 2 adds or changes on the money path. `_set_deadline`'s clock conversion is
#: the ONE float in this set and it is excluded by NAME rather than by value, so a float that
#: appears anywhere else fails here.
MONEY_MODULES = (
    "amplify/functions/shared/lambda_utils/wix_ecom.py",
    "amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py",
    "amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py",
    "amplify/functions/ecommerce/checkout/handler.py",
)

#: Functions allowed to carry a float, with the reason. A CLOCK is not money: `_set_deadline`
#: converts `get_remaining_time_in_millis()` to seconds and `_seconds_left` subtracts two
#: monotonic readings. Neither figure can reach a price, a total or a gateway amount -- the only
#: thing either decides is whether a Wix write is issued before a Lambda timeout.
CLOCK_FUNCTIONS = frozenset({"_set_deadline", "_seconds_left"})


@pytest.mark.parametrize("relative", MONEY_MODULES)
def test_no_float_arithmetic_outside_the_invocation_clock(relative):
    """R6.1's rule, as an AST walk rather than a text grep.

    `0.1 + 0.2` is not `0.3` in binary floating point, and a one-paise mismatch against the
    checkout total must FAIL CLOSED -- so a rounding artefact becomes a refused order rather than
    an absorbed discrepancy. The contribution path is integer throughout: `units *
    CONTRIBUTION_UNIT_PAISE` is integer times integer, `componentsPaise` comes from
    `Money.from_wix`, and `exempt_quote` returns four `int`s.
    """
    import ast
    offenders = []
    for node in ast.walk(_tree(relative)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in CLOCK_FUNCTIONS:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, float):
                    offenders.append((node.name, inner.lineno, inner.value))
                if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                        and inner.func.id == "float"):
                    offenders.append((node.name, inner.lineno, "float()"))
    assert offenders == [], f"{relative} performs float arithmetic on the money path: {offenders}"


def test_the_clock_exemption_is_not_a_blanket_one():
    """A guard that can never fire protects nothing, so the exemption is proven narrow.

    Both exempted functions must actually exist and actually be clock functions -- if either is
    renamed or repurposed, this fails rather than silently widening the allowance.
    """
    import ast
    tree = _tree("amplify/functions/ecommerce/checkout/handler.py")
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert CLOCK_FUNCTIONS <= names
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    assert "time.monotonic()" in source
    # Neither EXECUTES anything money-shaped. Measured on the AST with docstrings and comments
    # stripped, because both functions necessarily EXPLAIN in prose why a clock is not money --
    # and a text slice cannot tell an explanation from an expression, which is the same trap the
    # `captured` literal gate solves the same way.
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in CLOCK_FUNCTIONS):
            executable = ast.unparse(ast.Module(
                body=[stmt for stmt in node.body
                      if not (isinstance(stmt, ast.Expr)
                              and isinstance(stmt.value, ast.Constant)
                              and isinstance(stmt.value.value, str))],
                type_ignores=[])).lower()
            for banned in ("paise", "amount", "total", "currency", "price"):
                assert banned not in executable, f"{node.name} computes on {banned}"


def test_the_browser_and_the_server_agree_on_the_wix_stores_app_id():
    """The cross-language pin, from the Python side, on the constant a mismatch would 502.

    `wix_ecom.resolved_catalog_lines` refuses any `catalogReference` whose `appId` is not
    `cart_v2.STORES_APP_ID` -- as "invalid catalogue reference", which becomes a `WixEcomError` and
    then a 502 `CATALOGUE_UNAVAILABLE`. So a one-character drift between the browser's literal and
    the server's constant takes every checkout down and reports it as a catalogue outage.

    They are separate declarations in two languages and neither can import the other, so the only
    thing that can hold them equal is an assertion. `src/test/CartCheckout.test.tsx` pins the same
    equality from the TypeScript side; this is the half that fails if the PYTHON constant moves.

    Written during a live 502 investigation on 2026-10-04, where this was a leading suspect and
    answering it required a measurement. They match.
    """
    import re
    from lambda_utils.ecommerce import cart_v2
    source = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
    declared = set(re.findall(r"appId:\s*'([0-9a-f-]{36})'", source))
    assert declared, "src/lib/cart.ts must declare the Wix Stores appId it sends"
    assert declared == {cart_v2.STORES_APP_ID}, (
        f"browser appId {sorted(declared)} != server STORES_APP_ID {cart_v2.STORES_APP_ID}")


def test_currency_is_compared_explicitly_as_inr_never_inferred():
    """INR is compared against a LITERAL, never inferred from the amount or from a default.

    REWRITTEN FOR THE FIXED-PRICE MODEL. This used to walk the handler's AST for the
    `validate_contribution_amount(units * CONTRIBUTION_UNIT_PAISE, currency="INR")` call and
    assert both the explicit keyword and the integer multiplication. That call is gone with the
    amount arithmetic: there is no customer-proposed amount, so there is nothing to validate a
    proposal against and nothing to multiply.

    The property it was protecting is unchanged and is asserted where the comparison now lives:
    both calculators compare `currency` against the literal `"INR"` and refuse anything else, and
    the handler's own money arms do the same rather than reading a currency off an amount.
    """
    import ast
    pricing = _tree("amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py")
    literals = [node for node in ast.walk(pricing)
                if isinstance(node, ast.Compare)
                and any(isinstance(cmp, ast.Constant) and cmp.value == "INR"
                        for cmp in node.comparators)]
    assert literals, "checkout_pricing must compare currency against the INR literal"

    handler = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    assert 'currency != "INR"' in handler

    # And it is a real refusal rather than a comment: both calculators reject a non-INR currency,
    # so the exempt path is not the lenient side of the seam.
    for fn in (cp.exempt_quote, cp.compute_quote):
        with pytest.raises(cp.PricingError):
            fn(DEFAULT_PAISE, currency="USD")
        assert fn(DEFAULT_PAISE).currency == "INR"

    from lambda_utils.ecommerce import blog_contribution as bc
    assert bc.CONTRIBUTION_CURRENCY == "INR"


def test_the_contributed_paise_figure_is_an_int_at_every_step(monkeypatch):
    """Integer in, integer out, asserted on the real values rather than on the types in a comment.

    There is no arithmetic left on the contribution path: the figure is a committed constant
    looked up by variant id, so the only way it could stop being an integer is if the constant
    did. The `int` assertions therefore guard the committed map rather than a computation, and the
    computation they used to guard (`quantity x 100`) no longer exists.
    """
    h = _load_handler(monkeypatch, contribution_env=CONTRIBUTION_ID)
    for variant in CONTRIBUTION_VARIANTS:
        paise = h._contribution_request([contribution_line(variant)])
        assert type(paise) is int
        assert paise == contribution_paise(variant)
        quote = cp.exempt_quote(paise)
        for value in (quote.collection_before_convenience_paise, quote.convenience_fee_paise,
                      quote.convenience_gst_paise, quote.total_payable_paise):
            assert type(value) is int
        assert quote.total_payable_paise == paise
    # No unit-price constant survives, because nothing multiplies by one any more.
    assert not hasattr(h, "CONTRIBUTION_UNIT_PAISE")
