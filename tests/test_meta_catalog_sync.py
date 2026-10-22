"""Synthetic tests for the ProductsTable -> Meta projection.

The retired catalog fixture and all retired product/variant UUIDs were deliberately removed.
These tests exercise the projection contract with synthetic UUIDs only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync as sync  # noqa: E402

PRODUCT = "11111111-1111-4111-8111-111111111111"
VARIANT = "22222222-2222-4222-8222-222222222222"
PRODUCT_2 = "33333333-3333-4333-8333-333333333333"
VARIANT_2 = "44444444-4444-4444-8444-444444444444"


def product(*, product_id=PRODUCT, variant_id=VARIANT, slug="example", name="Example",
            price_minor=89900, in_stock=True, visible=True, meta_enabled=True):
    return {
        "id": product_id,
        "slug": slug,
        "name": name,
        "title": name,
        "visible": visible,
        "metaEnabled": meta_enabled,
        "currency": "INR",
        "priceMinor": price_minor,
        "price": f"{price_minor // 100}.{price_minor % 100:02d}",
        "descriptionHtml": "<p>Example product description for projection testing.</p>",
        "variants": [{
            "id": variant_id,
            "sku": variant_id,
            "label": "Standard",
            "inStock": in_stock,
            "inventory": 1 if in_stock else 0,
            "pricePaise": price_minor,
        }],
    }


def test_retailer_id_round_trip_uses_wecare_namespace():
    value = sync.retailer_id(PRODUCT, VARIANT)
    assert value == f"WECARE.DIGITAL:{PRODUCT}:{VARIANT}"
    assert sync.parse_retailer_id(value) == (PRODUCT, VARIANT)


@pytest.mark.parametrize("value", [
    "",
    None,
    "not-a-retailer-id",
    f"other:{PRODUCT}:{VARIANT}",
    f"WECARE.DIGITAL:{PRODUCT}",
    f"WECARE.DIGITAL:{PRODUCT}:not-a-uuid",
])
def test_foreign_or_malformed_retailer_ids_do_not_resolve(value):
    assert sync.parse_retailer_id(value) is None


def test_retailer_id_v2_round_trips_current_native_identifiers():
    cases = [
        ("6794847f-303e-598e-bdfb-74db0a642fed", "ANW7Q5K2"),
        ("native:hunar-kaushal", "KSL9M2Q4"),
        ("native:hunar-prastuti", "PST7K4N2"),
    ]
    for product_id, variant_id in cases:
        value = sync.retailer_id(product_id, variant_id)
        assert value.startswith("WECARE.DIGITAL:v2:")
        assert len(value) <= sync.RETAILER_ID_MAX_LENGTH
        assert sync.parse_retailer_id(value) == (product_id, variant_id)


def test_retailer_id_refuses_missing_or_oversized_identity():
    with pytest.raises(ValueError):
        sync.retailer_id("", "SKU1")
    with pytest.raises(ValueError):
        sync.retailer_id("product", "")
    with pytest.raises(ValueError):
        sync.retailer_id("x" * 100, "y" * 100)


def test_v2_parser_refuses_noncanonical_or_broken_encoding():
    assert sync.parse_retailer_id("WECARE.DIGITAL:v2:not*base64:also*bad") is None
    assert sync.parse_retailer_id("WECARE.DIGITAL:v3:bmF0aXZlOmE:U0tVMQ") is None
    assert sync.parse_retailer_id("WECARE.DIGITAL:v2::U0tVMQ") is None


def test_visible_product_projects_one_meta_item():
    items = sync.desired_items([product()])
    assert len(items) == 1
    item = items[0]
    assert item["item_group_id"] == PRODUCT
    assert item["retailer_id"] == sync.retailer_id(PRODUCT, VARIANT)
    assert item["currency"] == "INR"
    assert item["availability"] == sync.IN_STOCK
    assert item["price"] == "899.00"


def test_hidden_product_does_not_project():
    assert sync.desired_items([product(visible=False)]) == []


def test_stock_state_is_projected():
    item = sync.desired_items([product(in_stock=False)])[0]
    assert item["availability"] == sync.OUT_OF_STOCK


def test_variant_price_is_authoritative_in_strict_mode():
    row = product(price_minor=10000)
    row["variants"][0]["pricePaise"] = 25000
    item = sync.desired_items([row], require_variant_price=True)[0]
    assert item["price"] == "250.00"


def test_missing_variant_price_is_refused_in_strict_mode():
    row = product()
    del row["variants"][0]["pricePaise"]
    with pytest.raises(ValueError):
        sync.desired_items([row], require_variant_price=True)


def test_diff_create_update_retire_and_foreign():
    desired = sync.desired_items([
        product(),
        product(product_id=PRODUCT_2, variant_id=VARIANT_2, slug="second", name="Second"),
    ])
    create_plan = sync.diff(desired, [])
    assert create_plan.counts()["create"] == 2

    matching = [{"id": f"meta-{i}", **sync.meta_payload(item)}
                for i, item in enumerate(desired, start=1)]
    assert sync.diff(desired, matching).is_empty is True

    changed = [dict(matching[0]), matching[1]]
    changed[0]["availability"] = sync.OUT_OF_STOCK
    assert sync.diff(desired, changed).counts()["update"] == 1

    foreign = [{"id": "foreign", "retailer_id": "someone-else"}]
    assert sync.diff(desired, foreign).counts()["foreign"] == 1


def test_diff_matches_v2_by_decoded_identity_without_lowercasing_base64():
    desired = sync.desired_items([
        product(product_id="native:hunar-kaushal", variant_id="KSL9M2Q4",
                slug="hunar-kaushal", name="Kaushal"),
    ])
    matching = [{"id": "meta-v2", **sync.meta_payload(desired[0])}]
    assert sync.diff(desired, matching).is_empty is True


@pytest.mark.parametrize("paise,text", [
    (1, "0.01"),
    (50, "0.50"),
    (89900, "899.00"),
    (2699900, "26999.00"),
])
def test_price_text_uses_integer_paise(paise, text):
    assert sync.price_text(paise) == text
