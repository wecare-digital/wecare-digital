"""Service request policy tests for the clean-slate catalog.

Production product/variant mappings are empty until the fresh SKU-first catalog is created.
Generic service rules are exercised with synthetic test-only UUIDs.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("synthetic_service_catalog")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lambda_utils.ecommerce import cart_contract, checkout_pricing  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402
from synthetic_service_catalog import (  # noqa: E402
    PRODUCT, SUBMIT, AMEND, DROP_DOCS, VAULT, PICKUP,
)


INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
INTENT_B = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60"
OTHER_PRODUCT = "99999999-9999-4999-8999-999999999999"
OTHER_VARIANT = "88888888-8888-4888-8888-888888888888"


def line(variant=SUBMIT, quantity=1, product=PRODUCT):
    return {
        "catalogReference": {
            "catalogItemId": product,
            "options": {"variantId": variant},
        },
        "quantity": quantity,
    }


def item(variant=SUBMIT, unit_paise=9900, *, quantity=1, product=PRODUCT):
    return {
        "productId": product,
        "variantId": variant,
        "quantity": quantity,
        "unitPricePaise": unit_paise,
    }


def frozen(*items):
    return SimpleNamespace(frozen_data={"items": list(items)})


def test_frontend_service_catalog_is_clean_slate():
    source = (ROOT / "src/config/services.ts").read_text(encoding="utf-8")
    assert "export const SERVICES_PRODUCT_ID: string = ''" in source
    assert "export const SERVICES_OPTION_ID: string = ''" in source
    assert "export const SERVICE_CHOICES: readonly ServiceChoice[] = []" in source
    assert "export const SERVICES_CONFIGURED = false" in source


def test_synthetic_fixture_exercises_five_service_kinds_only_in_tests():
    assert dict(sr.SERVICE_KIND_BY_VARIANT) == {
        SUBMIT: sr.SUBMIT_REQUEST,
        AMEND: sr.REQUEST_AMENDMENT,
        DROP_DOCS: sr.DROP_DOCS,
        VAULT: sr.VAULT,
        PICKUP: sr.REQUEST_PICKUP,
    }
    assert sr.SERVICE_PRODUCT_IDS == frozenset({PRODUCT})
    assert sr.SERVICE_PURCHASES_ENABLED is True


def test_target_rules_are_preserved_for_fresh_catalog_rebuild():
    assert set(sr.TARGET_REQUIRED_KINDS) == {
        sr.REQUEST_AMENDMENT, sr.DROP_DOCS, sr.VAULT, sr.REQUEST_PICKUP,
    }
    assert sr.SUBMIT_REQUEST not in sr.TARGET_REQUIRED_KINDS


@pytest.mark.parametrize("variant,kind", [
    (SUBMIT, sr.SUBMIT_REQUEST),
    (AMEND, sr.REQUEST_AMENDMENT),
    (DROP_DOCS, sr.DROP_DOCS),
    (VAULT, sr.VAULT),
    (PICKUP, sr.REQUEST_PICKUP),
])
def test_synthetic_service_line_is_recognized(variant, kind):
    assert sr.service_line([line(variant)]) == sr.ServiceLine(kind, variant, None)


def test_valid_synthetic_service_preflight_proceeds():
    assert sr.checkout_preflight([line()], {"serviceIntentId": INTENT}) is None


@pytest.mark.parametrize("body", [
    {}, {"serviceIntentId": ""}, {"serviceIntentId": "abc"},
    {"serviceIntentId": INTENT.upper()}, {"serviceIntentId": 7}, None,
])
def test_missing_or_malformed_intent_is_refused(body):
    status, payload = sr.checkout_preflight([line()], body)
    assert (status, payload["error"]) == (409, sr.SERVICE_INTENT_REQUIRED)


@pytest.mark.parametrize("quantity", [True, 2, "1", 0, None, 1.0])
def test_only_quantity_one_is_accepted(quantity):
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(quantity=quantity)])
    assert caught.value.code == sr.SERVICE_INVALID_QUANTITY


def test_unknown_variant_of_service_product_is_refused():
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(OTHER_VARIANT)])
    assert caught.value.code == sr.SERVICE_UNKNOWN_CHOICE


def test_non_service_line_is_untouched():
    basket = [line(OTHER_VARIANT, product=OTHER_PRODUCT)]
    assert sr.service_line(basket) is None
    assert sr.has_service_line(basket) is False
    assert sr.checkout_preflight(basket, {}) is None
    assert sr.payref_extra(basket, {}, line_paise=None) == {}


def test_two_service_lines_are_refused():
    with pytest.raises(sr.ServiceRejected) as caught:
        sr.service_line([line(SUBMIT), line(AMEND)])
    assert caught.value.code == sr.SERVICE_ONE_PER_ORDER


def test_frozen_quote_price_is_authoritative():
    assert sr.native_service_line_paise(frozen(item(unit_paise=9900)), [line()]) == 9900


@pytest.mark.parametrize("paise", [1, 4900, 9900, 14900, 35000, 99900, 5_000_000])
def test_price_inside_safety_rail_is_accepted(paise):
    assert sr.native_service_line_paise(frozen(item(unit_paise=paise)), [line()]) == paise


@pytest.mark.parametrize("paise", [0, 5_000_001, 9_999_900])
def test_price_outside_safety_rail_is_refused(paise):
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(frozen(item(unit_paise=paise)), [line()])


def test_quote_must_match_service_product_variant_and_quantity():
    for quote in (
        frozen(),
        frozen(item(product=OTHER_PRODUCT)),
        frozen(item(variant=OTHER_VARIANT)),
        frozen(item(quantity=2)),
    ):
        with pytest.raises(sr.ServicePriceChanged):
            sr.native_service_line_paise(quote, [line()])


def test_payref_extra_uses_frozen_amount_and_intent():
    assert sr.payref_extra([line()], {"serviceIntentId": INTENT}, line_paise=14900) == {
        "serviceLine": {
            "kind": sr.SUBMIT_REQUEST,
            "variantId": SUBMIT,
            "paise": 14900,
            "intentId": INTENT,
        },
    }


def test_intent_rebound_is_fail_closed():
    bound = {"serviceLine": {
        "kind": sr.REQUEST_AMENDMENT,
        "variantId": AMEND,
        "paise": 9900,
        "intentId": INTENT,
    }}
    assert sr.intent_rebound(bound, {"serviceIntentId": INTENT}) is False
    assert sr.intent_rebound(bound, {"serviceIntentId": INTENT_B}) is True
    assert sr.intent_rebound({}, {"serviceIntentId": INTENT}) is True


def test_refusal_messages_are_pre_payment_and_honest():
    for message in sr.SERVICE_MESSAGES.values():
        assert message.endswith("Nothing has been charged.")


def test_service_errors_keep_checkout_contract_types():
    assert issubclass(sr.ServicePriceChanged, cart_contract.CartContractError)
    assert issubclass(sr.ServiceNotPayable, cart_contract.CartContractError)
    assert issubclass(sr.ServiceRejected, ValueError)


def test_service_pricing_uses_integer_paise():
    quote = checkout_pricing.compute_quote(9900)
    assert quote.collection_before_convenience_paise == 9900
    assert quote.total_payable_paise == 10193
    assert all(type(value) is int for value in (
        quote.collection_before_convenience_paise,
        quote.convenience_fee_paise,
        quote.convenience_gst_paise,
        quote.total_payable_paise,
    ))
