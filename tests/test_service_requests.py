"""The server allow-list: five services offered and priced, none refused by name, integer paise.

Pure module, pure tests: no AWS, no network, no credential.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import cart_contract, checkout_pricing  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402
from synthetic_service_catalog import (  # noqa: E402
    PRODUCT, SUBMIT, AMEND, DROP_DOCS, VAULT, PICKUP, configure as configure_services,
)

configure_services(sr)
INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
KIOSK = "00d4c72b-f694-441a-a192-e16f4b192440"
KIOSK_VARIANT = "9f1c0e8a-1111-4222-8333-444455556666"


def line(variant=SUBMIT, quantity=1, product=PRODUCT):
    return {"catalogReference": {"catalogItemId": product,
                                 "options": {"variantId": variant}}, "quantity": quantity}


def kiosk():
    return {"catalogReference": {"catalogItemId": KIOSK,
                                 "options": {"variantId": KIOSK_VARIANT}},
            "quantity": 1}


# ── the TS <-> Python mirror ──────────────────────────────────────────────────

def _ts(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_the_frontend_is_clean_slate_while_synthetic_server_fixture_drives_tests():
    source = _ts("src/config/services.ts")
    assert "export const SERVICE_CHOICES: readonly ServiceChoice[] = []" in source
    assert "export const SERVICES_PRODUCT_ID: string = ''" in source
    assert len(sr.SERVICE_KIND_BY_VARIANT) == 5
    assert sr.SERVICE_PURCHASES_ENABLED is True

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
    """Was `..._at_their_committed_paise`. The committed paise are gone; ProductsTable owns the
    price."""
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
    """Empty sets, and the refusal machinery intact for the next variant added to the catalogue."""
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
    """`paise` is None: a basket is read BEFORE the native quote prices it, so there is nothing
    to presume."""
    assert sr.service_line([line(variant)]) == sr.ServiceLine(kind, variant, None)
    status, payload = sr.checkout_preflight([line(variant)], {"serviceIntentId": INTENT})
    assert (status, payload["error"]) == (409, "SERVICE_UNAVAILABLE")


@pytest.mark.parametrize("variant,kind", [(DROP_DOCS, "DROP_DOCS"), (VAULT, "VAULT")])
def test_drop_docs_and_vault_are_allowed_beside_an_ordinary_product(variant, kind):
    basket = [kiosk(), line(variant)]
    assert sr.service_line(basket) == sr.ServiceLine(kind, variant, None)
    status, payload = sr.checkout_preflight(basket, {"serviceIntentId": INTENT})
    assert (status, payload["error"]) == (409, "SERVICE_UNAVAILABLE")


def test_an_unpriced_line_is_distinguishable_from_a_free_one():
    """`None` means "not priced yet". A `0` would mean "free", and nothing here may claim that."""
    assert sr.service_line([line()]).paise is None
    assert sr.ServiceLine("SUBMIT_REQUEST", SUBMIT).paise is None


@pytest.mark.parametrize("variant", ["00000000-0000-4000-8000-000000000001",
                                     "db166bc8-a763-41ec-9f65-0f718f18155b"])
def test_an_unknown_variant_of_the_same_product_is_still_an_unknown_choice(variant):
    """The allow-list is closed: a variant it does not name is refused, not sold.

    Both ids here are FABRICATED - one is all zeros, the other is the Drop Docs id with its last
    character changed. Neither is a variant ProductsTable holds. The five it holds are offered,
    so what this pins is that membership is decided by the map rather than by the id looking
    plausible for the product.
    """
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(variant)])
    assert caught.value.code == "SERVICE_UNKNOWN_CHOICE"
    status, payload = sr.checkout_preflight([line(variant)], {"serviceIntentId": INTENT})
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
    status, payload = sr.checkout_preflight([line()], body)
    assert (status, payload["error"]) == (409, "SERVICE_INTENT_REQUIRED")


def test_a_well_formed_legacy_services_basket_is_refused_before_pricing():
    """Retired service identities remain decodable for history, but cannot create a new payment."""
    status, payload = sr.checkout_preflight([line()], {"serviceIntentId": INTENT})
    assert (status, payload["error"]) == (409, "SERVICE_UNAVAILABLE")


@pytest.mark.parametrize("basket", [[kiosk()], [], None, "x", [None, 3, {"quantity": 1}]])
def test_a_non_service_basket_is_untouched(basket):
    assert sr.checkout_preflight(basket, {}) is None
    assert sr.payref_extra(basket, {}, line_paise=None) == {}
    assert sr.has_service_line(basket) is False


def test_a_contribution_basket_is_not_a_service_basket():
    # The LIVE contribution reference: product 8514c405-… at its single Rs.250 variant
    # 8ad6f376-…, which is all `Contribute` carries since the owner reduced it on 2026-10-10.
    # The deleted Rs.100 variant stood here before; a basket nothing can price is a weaker
    # subject for "this is not a service" than one that can.
    contribution = {"catalogReference": {"catalogItemId": "77777777-7777-4777-8777-777777777777",
                                         "options": {"variantId":
                                                     "7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a"}},
                    "quantity": 1}
    assert sr.service_line([contribution]) is None
    assert sr.checkout_preflight([contribution], {}) is None


def test_a_mixed_basket_is_recognised_and_allowed():
    basket = [kiosk(), line(AMEND)]
    assert sr.has_service_line(basket)
    assert sr.service_line(basket) == sr.ServiceLine("REQUEST_AMENDMENT", AMEND, None)
    status, payload = sr.checkout_preflight(basket, {"serviceIntentId": INTENT})
    assert (status, payload["error"]) == (409, "SERVICE_UNAVAILABLE")


def test_payref_extra_carries_exactly_the_join_with_the_quoted_figure():
    """The key set is the join; `paise` is the line's price from the frozen native quote."""
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


# ── the per-line price guard, over the frozen native quote ────────────────────

def _item(variant=SUBMIT, unit_paise=9900, *, quantity=1, product=PRODUCT):
    return {"productId": product, "variantId": variant, "quantity": quantity,
            "unitPricePaise": unit_paise}


def frozen(*items):
    """The `frozen_data['items']` shape `native_checkout.quote_native_cart` freezes."""
    return SimpleNamespace(frozen_data={"items": list(items)})


def test_the_guard_returns_the_frozen_line_price():
    assert sr.native_service_line_paise(frozen(_item(unit_paise=9900)), [line()]) == 9900
    assert sr.native_service_line_paise(frozen(_item()), [kiosk()]) is None


@pytest.mark.parametrize("paise", [1, 4900, 9899, 9901, 14900, 35000, 999900, 5_000_000])
def test_a_catalogue_price_edit_is_CHARGED_rather_than_refused(paise):
    """THE BEHAVIOUR INVERSION, 2026-10-08, stated as a test so the change is visible.

    Every one of these figures used to raise ``ServicePriceChanged`` -- which is to say an edited
    price refused the purchase until somebody deployed. The owner's requirement is that a price be
    changeable with no deploy, so the ProductsTable figure frozen into the quote is what is
    charged, and the guard returns it.
    """
    assert sr.native_service_line_paise(frozen(_item(unit_paise=paise)), [line()]) == paise


@pytest.mark.parametrize("paise", [5_000_001, 9_999_900, 100_000_000])
def test_a_figure_above_the_rail_still_fails_closed(paise):
    """The one thing the rail is for: a catalogue typo of the Rs.99,999 shape, not a price
    decision."""
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen(_item(unit_paise=paise)), [line()])


def test_a_zero_line_fails_closed():
    """A free service line would charge a convenience fee on nothing."""
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen(_item(unit_paise=0)), [line()])


def test_the_guard_errors_are_cart_contract_errors_so_create_answers_409_not_500():
    assert issubclass(sr.ServicePriceChanged, cart_contract.CartContractError)
    assert issubclass(sr.ServiceNotPayable, cart_contract.CartContractError)
    assert issubclass(sr.ServiceRejected, ValueError)


def test_only_the_service_line_is_read_in_a_mixed_quote():
    """A mixed basket's OTHER lines carry their own prices; only the service line is pinned."""
    quote = frozen(_item(KIOSK_VARIANT, 24999_00, product=KIOSK), _item(unit_paise=9900))
    assert sr.native_service_line_paise(quote, [kiosk(), line()]) == 9900


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


def test_a_line_the_quote_does_not_carry_fails_closed():
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen(), [line()])


def test_a_frozen_quantity_other_than_one_fails_closed():
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen(_item(quantity=2)), [line()])


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
