"""The Phase O-1 server allow-list: two services offered, two refused by name, integer paise.

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
    source = _ts("src/config/services.ts")
    product = re.search(r"SERVICES_PRODUCT_ID: string = '([0-9a-f-]{36})'", source)
    assert product and {product.group(1)} == set(sr.SERVICE_PRODUCT_IDS)
    choices = re.findall(
        r"kind: '(\w+)', variantId: '([0-9a-f-]{36})',\s*label: '[^']+', rupees: (\d+), "
        r"paise: (\d+)", source)
    assert len(choices) == 2
    assert {variant: (kind, int(paise)) for kind, variant, _rupees, paise in choices} == \
        dict(sr.SERVICE_CHOICES_PAISE)
    for _kind, _variant, rupees, paise in choices:
        assert int(rupees) * 100 == int(paise)
    block = source[source.index("export const NOT_OFFERED_SERVICE_VARIANT_IDS"):]
    block = block[:block.index("] as const")]
    assert set(re.findall(r"'([0-9a-f-]{36})'", block)) == set(sr.NOT_OFFERED_VARIANT_IDS)


def test_the_refusal_sentences_mirror_the_frontend():
    source = _ts("src/lib/serviceRequests.ts")
    block = source[source.index("export const SERVICE_REFUSAL_MESSAGES"):]
    block = block[:block.index("};")]
    declared = dict(re.findall(r"(SERVICE_[A-Z_]+):\s*'([^']+)'", block))
    for code, message in sr.SERVICE_MESSAGES.items():
        assert declared.get(code) == message, code


def test_only_two_services_are_offered_and_both_cost_9900_paise():
    assert set(sr.SERVICE_CHOICES_PAISE) == {SUBMIT, AMEND}
    assert sr.SERVICE_CHOICES_PAISE[SUBMIT] == ("SUBMIT_REQUEST", 9900)
    assert sr.SERVICE_CHOICES_PAISE[AMEND] == ("REQUEST_AMENDMENT", 9900)
    assert DROP_DOCS not in sr.SERVICE_CHOICES_PAISE and VAULT not in sr.SERVICE_CHOICES_PAISE
    for _kind, paise in sr.SERVICE_CHOICES_PAISE.values():
        assert type(paise) is int
    assert sr.SERVICE_CURRENCY == "INR"


def test_every_refusal_sentence_says_nothing_was_charged():
    for message in sr.SERVICE_MESSAGES.values():
        assert message.endswith("Nothing has been charged.")


# ── the allow-list ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant", [DROP_DOCS, VAULT])
def test_drop_docs_and_vault_are_refused_by_name(variant):
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(variant)])
    assert caught.value.code == "SERVICE_NOT_OFFERED"
    status, payload = sr.checkout_preflight([line(variant)], {"serviceIntentId": INTENT},
                                            v2_enabled=True)
    assert (status, payload["error"]) == (409, "SERVICE_NOT_OFFERED")


@pytest.mark.parametrize("variant", [DROP_DOCS, VAULT])
def test_drop_docs_and_vault_are_refused_beside_an_ordinary_product(variant):
    status, payload = sr.checkout_preflight([kiosk(), line(variant)], {"serviceIntentId": INTENT},
                                            v2_enabled=True)
    assert (status, payload["error"]) == (409, "SERVICE_NOT_OFFERED")


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
    assert sr.payref_extra(basket, {}) == {}
    assert sr.has_service_line(basket) is False


def test_a_contribution_basket_is_not_a_service_basket():
    contribution = {"catalogReference": {"appId": APP,
                                         "catalogItemId": "8514c405-3971-4786-ad0d-15406ca23407",
                                         "options": {"variantId":
                                                     "ab4ee1a2-1568-4dc4-abe1-55e24fa51576"}},
                    "quantity": 1}
    assert sr.service_line([contribution]) is None
    assert sr.checkout_preflight([contribution], {}, v2_enabled=True) is None


def test_a_mixed_basket_is_recognised_and_allowed():
    basket = [kiosk(), line(AMEND)]
    assert sr.has_service_line(basket)
    assert sr.service_line(basket) == sr.ServiceLine("REQUEST_AMENDMENT", AMEND, 9900)
    assert sr.checkout_preflight(basket, {"serviceIntentId": INTENT}, v2_enabled=True) is None


def test_payref_extra_carries_exactly_the_join():
    assert sr.payref_extra([line()], {"serviceIntentId": INTENT}) == {"serviceLine": {
        "kind": "SUBMIT_REQUEST", "variantId": SUBMIT, "paise": 9900, "intentId": INTENT}}


def test_recognition_is_case_insensitive_on_the_ids():
    assert sr.service_line([line(SUBMIT.upper(), product=PRODUCT.upper())]).paise == 9900


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


def test_the_assertion_passes_at_exactly_9900():
    sr.assert_service_line_price(calculated(9900), [line()], delivery_required=False)


@pytest.mark.parametrize("paise", [9899, 9901, 4900, 35000])
def test_a_one_paise_disagreement_fails_closed(paise):
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(paise), [line()], delivery_required=False)


def test_the_assertion_is_a_cart_contract_error_so_create_answers_409_not_500():
    assert issubclass(sr.ServicePriceChanged, cart_v2.CartContractError)
    assert issubclass(sr.ServiceNotPayable, cart_v2.CartContractError)
    assert issubclass(sr.ServiceRejected, ValueError)


def test_delivery_on_a_no_delivery_basket_fails_closed():
    with pytest.raises(sr.ServicePriceChanged):
        sr.assert_service_line_price(calculated(delivery=4000), [line()], delivery_required=False)


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
