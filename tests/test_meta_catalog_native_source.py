"""meta-catalog-sync CATALOG_SOURCE=aws: ProductsTable -> the same slim shape.

Proves the AWS-native catalogue read projects onto the identical shape
`catalog.desired_items(require_variant_price=True)` consumes, so the diff/approval
pipeline is source-agnostic. No AWS, no network — the scan is injected.

The handler is loaded BY PATH under a unique module name because the repo has
dozens of handler.py files (see test_meta_catalog_sync_handler.py).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync as sync  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/meta-catalog-sync/handler.py"
MODULE_NAME = "wecare_meta_catalog_sync_native_test"


def _load():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


receiver = _load()


def test_catalog_source_defaults_to_wix(monkeypatch):
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    assert receiver._catalog_source() == "wix"
    monkeypatch.setenv("CATALOG_SOURCE", "aws")
    assert receiver._catalog_source() == "aws"
    monkeypatch.setenv("CATALOG_SOURCE", "banana")
    assert receiver._catalog_source() == "wix"


def test_native_products_projects_slim_shape():
    items = [{
        "id": "prod-1", "title": "Starter Kit", "slug": "starter-kit",
        "status": "active", "priceMinor": 659900, "currency": "INR",
        "inventory": 5, "tagline": "A starter.",
        "variants": [{"sku": "SK-S", "label": "Small", "inventory": 2, "priceMinor": 659900}],
        "imageRefs": ["s3://media/sk.png"],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "prod-1"
    assert row["name"] == "Starter Kit"
    assert row["slug"] == "starter-kit"
    assert row["visible"] is True
    assert row["price"] == "6599.00"          # decimal string, like the Wix slim shape
    assert row["currency"] == "INR"
    assert row["image"] == "s3://media/sk.png"
    assert row["variants"][0]["pricePaise"] == 659900   # integer paise for require_variant_price
    assert row["variants"][0]["inStock"] is True


def test_native_products_excludes_archived():
    items = [
        {"id": "a", "title": "Live", "slug": "live", "status": "active", "priceMinor": 100,
         "variants": [{"sku": "a1", "inventory": 1, "priceMinor": 100}]},
        {"id": "b", "title": "Gone", "slug": "gone", "status": "archived", "priceMinor": 100},
    ]
    rows = receiver._native_products(scanner=lambda: items)
    assert [r["id"] for r in rows] == ["a"]


def test_native_products_feed_desired_items_with_variant_price():
    """A native product with a priced variant must survive desired_items'
    require_variant_price=True gate, exactly as a Wix product would.

    The retailer-id contract requires product AND variant ids to be UUIDs
    (`wix:<productUUID>:<variantUUID>` is the Meta<->catalog join key), so the
    ProductsTable MUST mint UUID ids for products and variants — a real native
    requirement documented in docs/migrations/wix-subsystem-deep-audit.md.
    """
    product_uuid = "11111111-1111-4111-8111-111111111111"
    variant_uuid = "22222222-2222-4222-8222-222222222222"
    items = [{
        "id": product_uuid, "title": "Thing", "slug": "thing", "status": "active",
        "priceMinor": 50000, "currency": "INR", "inventory": 3,
        "variants": [{"sku": variant_uuid, "label": "One", "inventory": 3,
                      "priceMinor": 50000}],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    desired = sync.desired_items(rows, require_variant_price=True)
    assert len(desired) >= 1


def test_native_variant_without_price_is_refused_like_wix():
    items = [{
        "id": "prod-x", "title": "Unpriced", "slug": "unpriced", "status": "active",
        "priceMinor": 0, "currency": "INR", "inventory": 1,
        "variants": [{"sku": "U-1", "label": "One", "inventory": 1}],  # no priceMinor
    }]
    rows = receiver._native_products(scanner=lambda: items)
    # the variant carries no pricePaise, so require_variant_price refuses it
    assert "pricePaise" not in rows[0]["variants"][0]
