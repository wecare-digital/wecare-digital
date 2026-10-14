"""AWS-native catalog snapshot contract.

The storefront snapshot is built from ProductsTable. The retained historical
`wix-catalog.json` exists only for reconciliation and is not a build dependency.
"""
from __future__ import annotations

import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO / "src/content/catalog-snapshot.json"
BUILD = REPO / "scripts/build-catalog-snapshot.py"
CHECK = REPO / "scripts/check_native_catalog_snapshot.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_declares_aws_native_source():
    data = snapshot()
    assert data["catalogVersion"] == "AWS_NATIVE_V1"
    assert data["source"] == "aws products-table (native catalog)"
    assert data["productCount"] == len(data["products"]) == 10


def test_snapshot_has_23_stable_variant_ids():
    data = snapshot()
    variants = [v["id"] for p in data["products"] for v in p.get("variants", [])]
    assert len(variants) == 23
    assert len(variants) == len(set(variants))
    assert all(isinstance(v, str) and v for v in variants)


def test_prices_are_exact_decimal_strings():
    for product in snapshot()["products"]:
        price = product["price"]
        assert isinstance(price, str)
        try:
            Decimal(price)
        except InvalidOperation:
            raise AssertionError(f"{product['slug']}: invalid decimal price {price!r}")


def test_live_media_snapshot_contains_no_provider_urls():
    raw = SNAPSHOT.read_text(encoding="utf-8").lower()
    assert "wixstatic.com" not in raw
    assert "wixapis.com" not in raw


def test_builder_targets_products_table_and_preserves_ids():
    builder = _load(BUILD, "catalog_builder_contract")
    assert builder.PRODUCTS_TABLE == "stack-wecare-digital-ProductsTable"
    item = {
        "id": "product-id",
        "title": "Example",
        "slug": "example",
        "priceMinor": 12345,
        "currency": "INR",
        "inventory": 2,
        "variants": [{"sku": "variant-id", "label": "Standard", "inventory": 2}],
    }
    projected = builder.to_shop_product(item)
    assert projected["id"] == "product-id"
    assert projected["variants"][0]["id"] == "variant-id"
    assert projected["price"] == "123.45"


def test_publish_guard_rejects_empty_snapshot():
    guard = _load(CHECK, "catalog_guard_contract")
    old = snapshot()
    new = dict(old, productCount=0, products=[])
    try:
        guard.check_snapshot(old, new)
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("empty native catalog was accepted")


def test_retained_provider_snapshot_is_not_the_storefront_import():
    shop = (REPO / "src/content/shop.ts").read_text(encoding="utf-8")
    assert "catalog-snapshot.json" in shop
    assert "wix-catalog.json" not in shop
