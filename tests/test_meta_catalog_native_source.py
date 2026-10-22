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


def test_catalog_source_is_unconditionally_native(monkeypatch):
    """The catalogue source is UNCONDITIONAL: ProductsTable is the sole authority.

    The handler reads the native catalogue directly via `_native_products`, so CATALOG_SOURCE
    routes nothing. This asserts the native reader is the one path the plan is computed from.
    """
    assert hasattr(receiver, "_native_products")
    source = HANDLER.read_text(encoding="utf-8")
    # The handler computes its plan from the native products read, with no provider branch.
    assert "products = _native_products()" in source


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
    assert row["price"] == "6599.00"          # decimal string in major units
    assert row["currency"] == "INR"
    assert row["image"] == "s3://media/sk.png"
    assert row["variants"][0]["pricePaise"] == 659900   # integer paise for require_variant_price
    assert row["variants"][0]["inStock"] is True


def test_untracked_zero_inventory_is_sellable_like_native_checkout():
    items = [{
        "id": "prod-untracked", "title": "Digital Service", "slug": "digital-service",
        "status": "active", "priceMinor": 9900, "currency": "INR",
        "variants": [{
            "sku": "DIGI1", "label": "Standard", "inventory": 0,
            "trackInventory": False, "inventoryVerified": True, "priceMinor": 9900,
        }],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    assert rows[0]["variants"][0]["inStock"] is True
    desired = sync.desired_items(rows, require_variant_price=True)
    assert desired[0]["availability"] == sync.IN_STOCK


def test_tracked_inventory_controls_meta_availability():
    items = [{
        "id": "prod-tracked", "title": "Physical", "slug": "physical",
        "status": "active", "priceMinor": 9900, "currency": "INR",
        "variants": [
            {"sku": "ZERO1", "label": "Zero", "inventory": 0,
             "trackInventory": True, "inventoryVerified": True, "priceMinor": 9900},
            {"sku": "ONE1", "label": "One", "inventory": 1,
             "trackInventory": True, "inventoryVerified": True, "priceMinor": 9900},
        ],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    projected = {v["id"]: v["inStock"] for v in rows[0]["variants"]}
    assert projected == {"ZERO1": False, "ONE1": True}


def test_native_products_excludes_archived():
    items = [
        {"id": "a", "title": "Live", "slug": "live", "status": "active", "priceMinor": 100,
         "variants": [{"sku": "a1", "inventory": 1, "priceMinor": 100}]},
        {"id": "b", "title": "Gone", "slug": "gone", "status": "archived", "priceMinor": 100},
    ]
    rows = receiver._native_products(scanner=lambda: items)
    assert [r["id"] for r in rows] == ["a"]


def test_native_products_feed_desired_items_with_variant_price():
    """A priced native row survives projection with its actual ProductsTable identities."""
    product_id = "native:hunar-kaushal"
    variant_id = "KSL9M2Q4"
    items = [{
        "id": product_id, "title": "Kaushal", "slug": "hunar-kaushal", "status": "active",
        "priceMinor": 50000, "currency": "INR", "inventory": 3,
        "variants": [{"sku": variant_id, "label": "Standard", "inventory": 3,
                      "priceMinor": 50000}],
        "imageRefs": ["https://wecare.digital/api/catalog-media/kaushal-4096.png"],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    desired = sync.desired_items(rows, require_variant_price=True)
    assert len(desired) == 1
    assert desired[0]["retailer_id"].startswith("WECARE.DIGITAL:v2:")
    assert sync.parse_retailer_id(desired[0]["retailer_id"]) == (product_id, variant_id)


def test_missing_status_defaults_visible_from_productstable():
    """A ProductsTable row with NO status still renders visible=True.

    The `or "active"` default is intentional and preserved: ProductsTable is OUR
    catalogue authority, so a legacy row without an explicit status is treated as
    live. This locks that behaviour so it is not "fixed" into a fail-closed default
    that would hide legitimate legacy rows.
    """
    items = [{
        "id": "no-status", "title": "Legacy", "slug": "legacy", "priceMinor": 100,
        "variants": [{"sku": "L-1", "inventory": 1, "priceMinor": 100}],
    }]
    rows = receiver._native_products(scanner=lambda: items)
    assert len(rows) == 1
    assert "status" not in items[0]        # the default fills in, the source has none
    assert rows[0]["visible"] is True


def test_visibility_is_sourced_only_from_productstable_scanner():
    """Visibility is derived from the injected ProductsTable scanner, never a Meta response.

    There is no Meta-sourced visibility path in this handler: `_native_products` reads
    status exclusively from the scanner's items. This proves the row builder consumes the
    scanner (an archived row is skipped, a missing-status row defaults visible) rather than
    any Meta GET response, which is why the permissive `or "active"` default is safe here.
    The fail-closed invariant for any future Meta-sourced status is documented at the
    `visible` site in the handler.
    """
    items = [
        {"id": "keep", "title": "Keep", "slug": "keep",
         "variants": [{"sku": "k1", "inventory": 1, "priceMinor": 100}]},  # no status -> visible
        {"id": "drop", "title": "Drop", "slug": "drop", "status": "archived", "priceMinor": 100},
    ]
    rows = receiver._native_products(scanner=lambda: items)
    assert [r["id"] for r in rows] == ["keep"]   # archived skipped, derived from the scanner
    assert rows[0]["visible"] is True            # missing status -> ProductsTable default


def test_native_variant_without_price_is_refused():
    items = [{
        "id": "prod-x", "title": "Unpriced", "slug": "unpriced", "status": "active",
        "priceMinor": 0, "currency": "INR", "inventory": 1,
        "variants": [{"sku": "U-1", "label": "One", "inventory": 1}],  # no priceMinor
    }]
    rows = receiver._native_products(scanner=lambda: items)
    # the variant carries no pricePaise, so require_variant_price refuses it
    assert "pricePaise" not in rows[0]["variants"][0]
