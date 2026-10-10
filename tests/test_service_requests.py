"""The server allow-list: five services offered and priced, none refused by name, integer paise.

Pure module, pure tests: no AWS, no network, no credential, no Wix call.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import cart_v2, checkout_pricing  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
AMEND = "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b"
DROP_DOCS = "db166bc8-a763-41ec-9f65-0f718f18155a"
VAULT = "dcff995e-448c-493a-9259-f6a82ccdc2b4"
PICKUP = "8ee7e325-d772-4452-a993-5c79e927d42b"
APP = "215238eb-22a5-4c36-9e7b-e7c08025e04e"
INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
KIOSK = "00d4c72b-f694-441a-a192-e16f4b192440"


def line(variant=SUBMIT, quantity=1, product=PRODUCT):
    return {"catalogReference": {"appId": APP, "catalogItemId": product,
                                 "options": {"variantId": variant}}, "quantity": quantity}


def kiosk():
    return {"catalogReference": {"appId": APP, "catalogItemId": KIOSK,
                                 "options": {"variantId": "9f1c0e8a-1111-4222-8333-444455556666"}},
            "quantity": 1}


# ── the TS <-> Python mirror ──────────────────────────────────────────────────

def _ts(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_the_server_choices_mirror_the_frontend_contract():
    """Identity only: variant, slug and needsTarget. NO PRICE on either side any more."""
    source = _ts("src/config/services.ts")
    product = re.search(r"SERVICES_PRODUCT_ID: string = '([0-9a-f-]{36})'", source)
    assert product and {product.group(1)} == set(sr.SERVICE_PRODUCT_IDS)
    choices = re.findall(
        r"kind: '(\w+)', variantId: '([0-9a-f-]{36})',\s*label: '[^']+', "
        r"slug: '([a-z-]+)', path: '[^']+',\s*needsTarget: (true|false),", source)
    assert len(choices) == 5
    assert {variant: kind for kind, variant, _slug, _t in choices} == \
        dict(sr.SERVICE_KIND_BY_VARIANT)
    # The slug vocabulary is the key the live-price payload is read by, so a drift here would show
    # one page another page's price -- the exact fault the owner reported.
    assert {slug: kind for kind, _v, slug, _t in choices} == dict(sr.SERVICE_KIND_BY_SLUG)
    # `needsTarget` mirrors TARGET_REQUIRED_KINDS, which is the rule the server enforces.
    assert {kind for kind, _v, _s, needs in choices if needs == "true"} == \
        set(sr.TARGET_REQUIRED_KINDS)


def test_the_frontend_declares_no_price_at_all():
    """The owner's requirement, asserted on the DECLARATION rather than on the whole file.

    Scoped to the `SERVICE_CHOICES` block and to the `ServiceChoice` interface, because the
    docblock legitimately quotes the owner's instruction ("price 49 or 99 can change any time")
    and a file-wide digit scan would fail on the sentence explaining why the digits left.
    """
    source = _ts("src/config/services.ts")
    assert "rupees" not in source and "paise" not in source
    for start, end in (("export interface ServiceChoice", "\n}"),
                       ("export const SERVICE_CHOICES", "] as const;")):
        block = source[source.index(start):]
        block = block[:block.index(end)]
        # Every GUID is stripped first: a variant id is catalogue identity, not a price, and it
        # is the one place digits belong in this declaration.
        assert not re.search(r"\d", re.sub(r"'[0-9a-f-]{36}'", "", block)), start
    block = source[source.index("export const NOT_OFFERED_SERVICE_VARIANT_IDS"):]
    block = block[:block.index("] as const")]
    assert set(re.findall(r"'([0-9a-f-]{36})'", block)) == set(sr.NOT_OFFERED_VARIANT_IDS) \
        == set()


def test_the_refusal_sentences_mirror_the_frontend():
    source = _ts("src/lib/serviceRequests.ts")
    block = source[source.index("export const SERVICE_REFUSAL_MESSAGES"):]
    block = block[:block.index("};")]
    declared = dict(re.findall(r"(SERVICE_[A-Z_]+):\s*'([^']+)'", block))
    for code, message in sr.SERVICE_MESSAGES.items():
        assert declared.get(code) == message, code


def test_exactly_five_services_are_offered_and_the_map_carries_no_price():
    """Was `..._at_their_committed_paise`. The committed paise are gone; Wix owns the price."""
    assert dict(sr.SERVICE_KIND_BY_VARIANT) == {
        SUBMIT: "SUBMIT_REQUEST", AMEND: "REQUEST_AMENDMENT",
        DROP_DOCS: "DROP_DOCS", VAULT: "VAULT", PICKUP: "REQUEST_PICKUP"}
    assert all(isinstance(kind, str) for kind in sr.SERVICE_KIND_BY_VARIANT.values())
    assert dict(sr.SERVICE_VARIANT_BY_KIND) == {
        kind: variant for variant, kind in sr.SERVICE_KIND_BY_VARIANT.items()}
    assert sr.SERVICE_CURRENCY == "INR"
    assert not hasattr(sr, "SERVICE_CHOICES_PAISE")


def test_the_catastrophe_rail_is_wide_enough_not_to_be_a_price_lock():
    """A rail narrow enough to be a price check would reintroduce the deploy this removed."""
    assert sr.SERVICE_LINE_MIN_PAISE == 1
    assert sr.SERVICE_LINE_MAX_PAISE == 5_000_000
    assert type(sr.SERVICE_LINE_MIN_PAISE) is int
    assert type(sr.SERVICE_LINE_MAX_PAISE) is int
    # Every price the owner might plausibly set passes without anybody deploying.
    for paise in (4900, 9900, 14900, 35000, 99900, 499900):
        assert sr.SERVICE_LINE_MIN_PAISE <= paise <= sr.SERVICE_LINE_MAX_PAISE


def test_nothing_is_refused_by_name_any_more_but_the_guard_is_still_there():
    """Empty sets, and the refusal machinery intact for the next variant added in Wix."""
    assert set(sr.NOT_OFFERED_VARIANT_IDS) == set()
    assert set(sr.NOT_OFFERED_KINDS) == set()
    assert sr.SERVICE_NOT_OFFERED == "SERVICE_NOT_OFFERED"
    assert sr.SERVICE_MESSAGES[sr.SERVICE_NOT_OFFERED] == \
        "This service is not offered yet. Nothing has been charged."
    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                     "service_requests.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "service_line")
    body = ast.unparse(fn)
    assert "NOT_OFFERED_VARIANT_IDS" in body and "SERVICE_NOT_OFFERED" in body


def test_four_of_the_five_need_a_target_submit_request():
    assert set(sr.TARGET_REQUIRED_KINDS) == {
        "REQUEST_AMENDMENT", "DROP_DOCS", "VAULT", "REQUEST_PICKUP"}
    assert sr.SUBMIT_REQUEST not in sr.TARGET_REQUIRED_KINDS
    assert sr.DROP_DOCS == "DROP_DOCS" and sr.VAULT == "VAULT"
    assert sr.REQUEST_PICKUP == "REQUEST_PICKUP"


def test_every_refusal_sentence_says_nothing_was_charged():
    for message in sr.SERVICE_MESSAGES.values():
        assert message.endswith("Nothing has been charged.")


# ── the allow-list ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant,kind", [(DROP_DOCS, "DROP_DOCS"), (VAULT, "VAULT")])
def test_drop_docs_and_vault_are_offered(variant, kind):
    """`paise` is None: a basket is read BEFORE Wix prices it, so there is nothing to presume."""
    assert sr.service_line([line(variant)]) == sr.ServiceLine(kind, variant, None)
    assert sr.checkout_preflight([line(variant)], {"serviceIntentId": INTENT},
                                 v2_enabled=True) is None


@pytest.mark.parametrize("variant,kind", [(DROP_DOCS, "DROP_DOCS"), (VAULT, "VAULT")])
def test_drop_docs_and_vault_are_allowed_beside_an_ordinary_product(variant, kind):
    basket = [kiosk(), line(variant)]
    assert sr.service_line(basket) == sr.ServiceLine(kind, variant, None)
    assert sr.checkout_preflight(basket, {"serviceIntentId": INTENT}, v2_enabled=True) is None


def test_an_unpriced_line_is_distinguishable_from_a_free_one():
    """`None` means "not priced yet". A `0` would mean "free", and nothing here may claim that."""
    assert sr.service_line([line()]).paise is None
    assert sr.ServiceLine("SUBMIT_REQUEST", SUBMIT).paise is None


@pytest.mark.parametrize("variant", ["00000000-0000-4000-8000-000000000001",
                                     "db166bc8-a763-41ec-9f65-0f718f18155b"])
def test_an_unknown_variant_of_the_same_product_is_still_an_unknown_choice(variant):
    """The allow-list is closed: a variant it does not name is refused, not sold.

    Both ids here are FABRICATED - one is all zeros, the other is the Drop Docs id with its last
    character changed. Neither is a variant live Wix returns. The five it does return are offered,
    so what this pins is that membership is decided by the map rather than by the id looking
    plausible for the product.
    """
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(variant)])
    assert caught.value.code == "SERVICE_UNKNOWN_CHOICE"
    status, payload = sr.checkout_preflight([line(variant)], {"serviceIntentId": INTENT},
                                            v2_enabled=True)
    assert (status, payload["error"]) == (409, "SERVICE_UNKNOWN_CHOICE")


@pytest.mark.parametrize("quantity", [True, 2, "1", 0, None, 1.0])
def test_only_quantity_exactly_one_is_accepted(quantity):
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(quantity=quantity)])
    assert caught.value.code == "SERVICE_INVALID_QUANTITY"


def test_an_unknown_variant_is_an_unknown_choice():
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line("00000000-0000-4000-8000-000000000000")])
    assert caught.value.code == "SERVICE_UNKNOWN_CHOICE"
    with pytest.raises(sr.ServiceRejected):
        sr.service_line([{"catalogReference": {"catalogItemId": PRODUCT}, "quantity": 1}])


@pytest.mark.parametrize("basket", [[line(SUBMIT), line(AMEND)], [line(SUBMIT), line(SUBMIT)]])
def test_two_service_lines_are_one_too_many(basket):
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line(basket)
    assert caught.value.code == "SERVICE_ONE_PER_ORDER"


@pytest.mark.parametrize("body", [{}, {"serviceIntentId": ""}, {"serviceIntentId": "abc"},
                                  {"serviceIntentId": INTENT.upper()},
                                  {"serviceIntentId": 7}, None])
def test_a_missing_or_malformed_intent_is_refused(body):
    status, payload = sr.checkout_preflight([line()], body, v2_enabled=True)
    assert (status, payload["error"]) == (409, "SERVICE_INTENT_REQUIRED")


def test_cart_v2_off_refuses_a_services_basket_with_503():
    status, payload = sr.checkout_preflight([line()], {"serviceIntentId": INTENT},
                                            v2_enabled=False)
    assert (status, payload["error"]) == (503, "SERVICE_UNAVAILABLE")


@pytest.mark.parametrize("basket", [[kiosk()], [], None, "x", [None, 3, {"quantity": 1}]])
def test_a_non_service_basket_is_untouched(basket):
    assert sr.checkout_preflight(basket, {}, v2_enabled=False) is None
    assert sr.payref_extra(basket, {}, line_paise=None) == {}
    assert sr.has_service_line(basket) is False


def test_a_contribution_basket_is_not_a_service_basket():
    # The LIVE contribution reference: product 8514c405-… at its single Rs.250 variant
    # 8ad6f376-…, which is all `Contribute` carries since the owner reduced it in Wix on
    # 2026-10-10. The deleted Rs.100 variant stood here before; a basket nothing can price is a
    # weaker subject for "this is not a service" than one that can.
    contribution = {"catalogReference": {"appId": APP,
                                         "catalogItemId": "8514c405-3971-4786-ad0d-15406ca23407",
                                         "options": {"variantId":
                                                     "8ad6f376-a526-4631-b510-0e047b33a5b9"}},
                    "quantity": 1}
    assert sr.service_line([contribution]) is None
    assert sr.checkout_preflight([contribution], {}, v2_enabled=True) is None


def test_a_mixed_basket_is_recognised_and_allowed():
    basket = [kiosk(), line(AMEND)]
    assert sr.has_service_line(basket)
    assert sr.service_line(basket) == sr.ServiceLine("REQUEST_AMENDMENT", AMEND, None)
    assert sr.checkout_preflight(basket, {"serviceIntentId": INTENT}, v2_enabled=True) is None


def test_payref_extra_carries_exactly_the_join_with_wixs_own_figure():
    """The key set is byte-identical to before; only the SOURCE of `paise` moved to Wix."""
    assert sr.payref_extra([line()], {"serviceIntentId": INTENT}, line_paise=14900) == {
        "serviceLine": {"kind": "SUBMIT_REQUEST", "variantId": SUBMIT, "paise": 14900,
                        "intentId": INTENT}}


def test_payref_extra_records_an_unpriced_line_as_none_rather_than_zero():
    row = sr.payref_extra([line()], {"serviceIntentId": INTENT},
                          line_paise=None)["serviceLine"]
    assert row["paise"] is None
    assert set(row) == {"kind", "variantId", "paise", "intentId"}


def test_omitting_the_figure_is_a_typeerror_rather_than_an_unpriced_row():
    """The hazard the default used to carry: an omission landed `paise: None` on a PAYREF# row,
    which `service_request_store.activate` refuses as AMOUNT_MISMATCH -- *after* money moved.
    With no default, the same mistake is a TypeError here instead of a post-payment unmatched
    order. `None` still has to be passable, and deliberately."""
    with pytest.raises(TypeError):
        sr.payref_extra([line()], {"serviceIntentId": INTENT})      # type: ignore[call-arg]
    assert sr.payref_extra([line()], {"serviceIntentId": INTENT},
                           line_paise=None)["serviceLine"]["paise"] is None


def test_recognition_is_case_insensitive_on_the_ids():
    read = sr.service_line([line(SUBMIT.upper(), product=PRODUCT.upper())])
    assert read == sr.ServiceLine("SUBMIT_REQUEST", SUBMIT, None)


# ── the per-line price assertion ──────────────────────────────────────────────

def _rupees(paise: int) -> dict:
    return {"amount": f"{paise // 100}.{paise % 100:02d}"}


def calculated(line_paise=9900, *, delivery=0, discount=0, extra_line_paise=None):
    cart_lines = [{"id": "L1", "quantityInfo": {"confirmedQuantity": 1},
                   "source": {"catalogReference": {"catalogItemId": PRODUCT,
                                                   "options": {"variantId": SUBMIT}}}}]
    summary = [{"lineItemId": "L1", "totalPrice": _rupees(line_paise)}]
    subtotal = line_paise
    if extra_line_paise is not None:
        cart_lines.append({"id": "L2", "quantityInfo": {"confirmedQuantity": 1},
                           "source": {"catalogReference": {"catalogItemId": KIOSK}}})
        summary.append({"lineItemId": "L2", "totalPrice": _rupees(extra_line_paise)})
        subtotal += extra_line_paise
    return {"cart": {"lineItems": cart_lines}, "summary": {"lineItems": summary},
            "componentsPaise": {"subtotal": subtotal, "discount": discount, "delivery": delivery,
                                "additionalFees": 0, "tax": 0,
                                "total": subtotal - discount + delivery}}


def test_the_assertion_returns_wixs_own_figure():
    assert sr.assert_service_line_price(
        calculated(9900), [line()], delivery_required=False) == 9900
    assert sr.assert_service_line_price(None, [kiosk()], delivery_required=False) is None


@pytest.mark.parametrize("paise", [1, 4900, 9899, 9901, 14900, 35000, 999900, 5_000_000])
def test_a_wix_price_edit_is_now_CHARGED_rather_than_refused(paise):
    """THE BEHAVIOUR INVERSION, 2026-10-08, stated as a test so the change is visible.

    Every one of these figures used to raise ``ServicePriceChanged`` -- which is to say a price
    edited in Wix refused the purchase until somebody deployed. The owner's requirement is that a
    price be changeable in Wix with no deploy, so Wix's figure is now what is charged, and the
    assertion returns it.
    """
    assert sr.assert_service_line_price(
        calculated(paise), [line()], delivery_required=False) == paise


@pytest.mark.parametrize("paise", [5_000_001, 9_999_900, 100_000_000])
def test_a_figure_above_the_rail_still_fails_closed(paise):
    """The one thing the rail is for: a Wix typo of the Rs.99,999 shape, not a price decision."""
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(paise), [line()], delivery_required=False)


def test_a_zero_line_fails_closed():
    """A free service line would charge a convenience fee on nothing."""
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(0), [line()], delivery_required=False)


def test_observed_service_line_paise_reads_the_same_figure_without_asserting():
    assert sr.observed_service_line_paise(calculated(14900)) == 14900
    # Non-raising on every unreadable shape: the assertion, not this, is what refuses a basket.
    assert sr.observed_service_line_paise({"cart": {}, "summary": {}}) is None
    assert sr.observed_service_line_paise(calculated(5_000_001)) == 5_000_001
    broken = calculated()
    broken["summary"]["lineItems"][0]["totalPrice"] = {"amount": "not-money"}
    assert sr.observed_service_line_paise(broken) is None


def test_the_assertion_is_a_cart_contract_error_so_create_answers_409_not_500():
    assert issubclass(sr.ServicePriceChanged, cart_v2.CartContractError)
    assert issubclass(sr.ServiceNotPayable, cart_v2.CartContractError)
    assert issubclass(sr.ServiceRejected, ValueError)


def test_delivery_on_a_no_delivery_basket_fails_closed():
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(delivery=4000), [line()], delivery_required=False)


def _with_component(component: str, paise):
    calc = calculated()
    calc["componentsPaise"][component] = paise
    if type(paise) is int:
        calc["componentsPaise"]["total"] += paise
    return calc


@pytest.mark.parametrize("paise", [1, 1782, "0", None])
def test_tax_on_a_no_delivery_basket_fails_closed(paise):
    """Review SERVICE-TAX-FEES-UNCHECKED: a Wix tax rule on the PHYSICAL services product would
    raise the payable above Rs.99 + convenience fee. One paise is enough to refuse."""
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(_with_component("tax", paise), [line()],
                                     delivery_required=False)


@pytest.mark.parametrize("paise", [1, 2500, "0", None])
def test_additional_fees_on_a_no_delivery_basket_fail_closed(paise):
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(_with_component("additionalFees", paise), [line()],
                                     delivery_required=False)


def test_tax_and_fees_are_ignored_when_the_basket_genuinely_ships_something():
    """A mixed basket's OTHER lines legitimately carry tax and fees; only the line is pinned."""
    calc = calculated(delivery=4000, extra_line_paise=24999_00)
    calc["componentsPaise"]["tax"] = 4500
    calc["componentsPaise"]["additionalFees"] = 1000
    sr.assert_service_line_price(calc, [kiosk(), line()], delivery_required=True)


INTENT_B = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60"


def test_intent_rebound_matches_only_the_bound_intent():
    bound = {"serviceLine": {"kind": "REQUEST_AMENDMENT", "variantId": AMEND, "paise": 9900,
                             "intentId": INTENT}}
    assert sr.intent_rebound(bound, {"serviceIntentId": INTENT}) is False
    assert sr.intent_rebound(bound, {"serviceIntentId": INTENT_B}) is True


@pytest.mark.parametrize("payref", [None, {}, {"serviceLine": None},
                                    {"serviceLine": {"intentId": ""}}])
def test_intent_rebound_fails_closed_on_an_unbound_row(payref):
    assert sr.intent_rebound(payref, {"serviceIntentId": INTENT}) is True


def test_delivery_is_ignored_when_the_basket_genuinely_ships_something():
    sr.assert_service_line_price(calculated(delivery=4000, extra_line_paise=24999_00),
                                 [kiosk(), line()], delivery_required=True)


def test_a_coupon_discount_does_not_affect_the_line_assertion():
    sr.assert_service_line_price(calculated(discount=990), [line()], delivery_required=False)


def test_a_line_wix_did_not_return_fails_closed():
    calc = calculated()
    calc["cart"]["lineItems"] = []
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calc, [line()], delivery_required=False)


def test_a_confirmed_quantity_other_than_one_fails_closed():
    calc = calculated()
    calc["cart"]["lineItems"][0]["quantityInfo"]["confirmedQuantity"] = 2
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calc, [line()], delivery_required=False)


def test_the_payable_for_one_service_is_ordinary_order_pricing():
    """9900 line -> fee 248 (2.5%, half-up) + GST 45 (18% of the fee, half-up) = 10193."""
    quote = checkout_pricing.compute_quote(9900)
    assert quote.collection_before_convenience_paise == 9900
    assert quote.convenience_fee_paise == checkout_pricing.round_half_up(
        9900, checkout_pricing.CONVENIENCE_FEE_BPS) == 248
    assert quote.convenience_gst_paise == checkout_pricing.round_half_up(
        248, checkout_pricing.CONVENIENCE_GST_BPS) == 45
    assert quote.total_payable_paise == 10193
    assert all(type(value) is int for value in (
        quote.collection_before_convenience_paise, quote.convenience_fee_paise,
        quote.convenience_gst_paise, quote.total_payable_paise))


def test_the_module_does_no_float_arithmetic_and_no_io():
    tree = ast.parse((ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                      "service_requests.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("float", "open")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] + [getattr(node, "module", "") or ""]
            assert not any(n.split(".")[0] in ("boto3", "botocore", "urllib", "requests")
                           for n in names)
