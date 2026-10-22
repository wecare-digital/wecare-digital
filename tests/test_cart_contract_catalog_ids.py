"""Catalog identities are distinct from cart/request UUID identities."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import cart_contract as cart  # noqa: E402


UUID_PRODUCT = "6794847f-303e-598e-bdfb-74db0a642fed"


def test_catalog_item_accepts_current_uuid_product_and_short_sku():
    assert cart.catalog_item({
        "productId": UUID_PRODUCT,
        "variantId": "ANW7Q5K2",
        "quantity": 2,
    }) == {
        "catalogReference": {
            "catalogItemId": UUID_PRODUCT,
            "options": {"variantId": "ANW7Q5K2"},
        },
        "quantity": 2,
    }


def test_catalog_item_accepts_native_product_and_preserves_sku_case():
    assert cart.catalog_item({
        "productId": "native:hunar-kaushal",
        "variantId": "KSL9M2Q4",
        "quantity": 1,
    }) == {
        "catalogReference": {
            "catalogItemId": "native:hunar-kaushal",
            "options": {"variantId": "KSL9M2Q4"},
        },
        "quantity": 1,
    }


@pytest.mark.parametrize("product_id", [
    "",
    "native:",
    "native:Hunar-Kaushal",
    "native:hunar/kaushal",
    "../hunar",
    "not-a-product-id",
])
def test_catalog_product_identifier_rejects_unowned_shapes(product_id):
    with pytest.raises(ValueError):
        cart.catalog_product_identifier(product_id)


@pytest.mark.parametrize("variant_id", [
    "",
    " SKU",
    "SKU/ONE",
    "../SKU",
    "SKU ONE",
    "x" * 101,
])
def test_catalog_variant_identifier_rejects_unsafe_shapes(variant_id):
    with pytest.raises(ValueError):
        cart.catalog_variant_identifier(variant_id)


def test_uuid_only_identifier_contract_is_not_widened():
    value = "11111111-2222-4333-8444-555555555555"
    assert cart.identifier(value.upper()) == value
    with pytest.raises(ValueError):
        cart.identifier("native:hunar-kaushal")
    with pytest.raises(ValueError):
        cart.identifier("KSL9M2Q4")
