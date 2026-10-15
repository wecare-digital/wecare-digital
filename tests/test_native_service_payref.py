"""Protect native service checkout from missing PAYREF unit prices.

These are pure, offline tests. A service payment must never produce a PAYREF
whose serviceLine.paise is None; the amount must come from the frozen AWS quote,
not a client-provided price.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import service_requests as sr  # noqa: E402

SERVICE_PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SERVICE_VARIANT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
VALID_INTENT = "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"


def service_cart(*, quantity=1, variant=SERVICE_VARIANT, client_amount=1):
    return [{
        "catalogReference": {
            "appId": "legacy-client-shape",
            "catalogItemId": SERVICE_PRODUCT,
            "options": {"variantId": variant},
        },
        "quantity": quantity,
        "unitPricePaise": client_amount,
    }]


def frozen_quote(*, price=9900, variant=SERVICE_VARIANT, quantity=1,
                 product=SERVICE_PRODUCT):
    return SimpleNamespace(frozen_data={"items": [{
        "productId": product,
        "variantId": variant,
        "quantity": quantity,
        "unitPricePaise": price,
    }]})


def test_a_well_formed_service_basket_passes_preflight():
    lines = service_cart()
    body = {"serviceIntentId": VALID_INTENT}
    assert sr.checkout_preflight(lines, body) is None


def test_native_service_price_from_frozen_quote_not_client():
    lines = service_cart(client_amount=1)
    quote = frozen_quote(price=9900)
    amount = sr.native_service_line_paise(quote, lines)
    assert amount == 9900
    assert sr.payref_extra(lines, {"serviceIntentId": VALID_INTENT},
                           line_paise=amount)["serviceLine"] == {
        "kind": "SUBMIT_REQUEST",
        "variantId": SERVICE_VARIANT,
        "paise": 9900,
        "intentId": VALID_INTENT,
    }


def test_non_service_cart_has_no_service_payref():
    lines = [{"catalogReference": {
        "catalogItemId": "11111111-1111-4111-8111-111111111111",
        "options": {"variantId": "22222222-2222-4222-8222-222222222222"}},
        "quantity": 1}]
    assert sr.native_service_line_paise(frozen_quote(), lines) is None
    assert sr.payref_extra(lines, {"serviceIntentId": VALID_INTENT},
                           line_paise=None) == {}


@pytest.mark.parametrize("snapshot", [
    SimpleNamespace(frozen_data={"items": []}),
    frozen_quote(variant="00000000-0000-4000-8000-000000000000"),
    frozen_quote(price=0),
    frozen_quote(price=None),
    frozen_quote(price=True),
    frozen_quote(price=5_000_001),
    frozen_quote(quantity=2),
    frozen_quote(product="11111111-1111-4111-8111-111111111111"),
])
def test_invalid_frozen_service_price_refuses_before_gateway(snapshot):
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(snapshot, service_cart())


def test_missing_frozen_quote_refuses_not_charges():
    with pytest.raises(sr.ServicePriceChanged):
        sr.native_service_line_paise(SimpleNamespace(frozen_data={}), service_cart())
