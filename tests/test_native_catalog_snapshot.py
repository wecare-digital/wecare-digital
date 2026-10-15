"""AWS-native catalog snapshot contract.

The storefront snapshot is built from ProductsTable. No retired provider snapshot is a storefront build dependency.
"""
from __future__ import annotations

import importlib.util
import json
import re
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


#: The origins the storefront snapshot may reference: our own site and the product-image
#: CloudFront distribution in front of our S3 bucket.
OWNED_MEDIA_HOSTS = {"wecare.digital", "d1kf2rchz7yras.cloudfront.net"}


def test_every_snapshot_url_is_served_from_an_owned_origin():
    raw = SNAPSHOT.read_text(encoding="utf-8")
    hosts = {host.lower() for host in re.findall(r'https?://([^/"\s]+)', raw)}
    assert hosts, "the snapshot carries no media URL at all"
    assert hosts <= OWNED_MEDIA_HOSTS, sorted(hosts - OWNED_MEDIA_HOSTS)


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


def test_storefront_import_is_native_snapshot_only():
    shop = (REPO / "src/content/shop.ts").read_text(encoding="utf-8")
    assert "catalog-snapshot.json" in shop
