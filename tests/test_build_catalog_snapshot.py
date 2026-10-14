"""build-catalog-snapshot: ProductsTable item -> ShopProduct snapshot (pure).

No AWS. Verifies the envelope matches the committed Wix snapshot, prices render
exactly (Decimal, never float), Indian grouping, archived products are excluded,
and variants project correctly.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_catalog_snapshot", ROOT / "scripts/build-catalog-snapshot.py")
bcs = importlib.util.module_from_spec(_spec)
sys.modules["build_catalog_snapshot"] = bcs
_spec.loader.exec_module(bcs)


def test_envelope_matches_wix_snapshot_shape():
    snap = bcs.build_snapshot([{"id": "p1", "title": "X", "slug": "x", "priceMinor": 100,
                                "inventory": 1}])
    assert set(snap) == {"source", "catalogVersion", "fetchedAt", "productCount",
                         "products", "variantVerifiedAt"}
    assert snap["productCount"] == 1
    assert "native" in snap["source"]


def test_price_renders_exactly_and_display_only():
    p = bcs.to_shop_product({"id": "1", "title": "A", "slug": "a", "priceMinor": 659900,
                             "inventory": 1})
    assert p["price"] == "6599.00"
    assert p["formattedPrice"] == "\u20b96,599.00"
    assert p["currency"] == "INR"


def test_indian_grouping_large_amount():
    p = bcs.to_shop_product({"id": "1", "title": "A", "slug": "a", "priceMinor": 1234567800,
                             "inventory": 1})
    # 12345678.00 rupees -> 1,23,45,678.00
    assert p["formattedPrice"] == "\u20b91,23,45,678.00"


def test_archived_products_excluded():
    snap = bcs.build_snapshot([
        {"id": "p1", "title": "Live", "slug": "live", "priceMinor": 100, "inventory": 1},
        {"id": "p2", "title": "Gone", "slug": "gone", "priceMinor": 100, "status": "archived"},
    ])
    slugs = [p["slug"] for p in snap["products"]]
    assert slugs == ["live"]


def test_variants_project_and_instock_rolls_up():
    p = bcs.to_shop_product({
        "id": "1", "title": "A", "slug": "a", "priceMinor": 100, "inventory": 0,
        "variants": [{"sku": "A-S", "label": "Small", "inventory": 0},
                     {"sku": "A-L", "label": "Large", "inventory": 3}],
    })
    assert p["inStock"] is True  # a variant has stock
    assert {v["id"] for v in p["variants"]} == {"A-S", "A-L"}


def test_negative_price_rejected():
    with pytest.raises(ValueError):
        bcs.to_shop_product({"id": "1", "title": "A", "slug": "a", "priceMinor": -1})
