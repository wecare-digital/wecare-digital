from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_catalog_release.py"


def load_module():
    spec = importlib.util.spec_from_file_location("migrate_catalog_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_target_key_rewrites_only_retired_catalog_prefix():
    mod = load_module()
    old = "secure/public/catalog-deploy/catalog/products/anew-4096.png"
    assert mod.target_key(old) == (
        "secure/d/public/catalog-deploy/catalog/products/anew-4096.png"
    )


def test_meta_candidate_requires_active_website_and_canonical_image():
    mod = load_module()
    base = {
        "status": "active",
        "websiteEnabled": True,
        "catalogImageKey": "secure/d/public/catalog-deploy/catalog/products/anew-4096.png",
    }
    assert mod.meta_candidate(base) is True
    assert mod.meta_candidate({**base, "status": "draft"}) is False
    assert mod.meta_candidate({**base, "websiteEnabled": False}) is False
    assert mod.meta_candidate({**base, "catalogImageKey": ""}) is False


def test_plan_summary_preserves_wix_foreign_readback():
    mod = load_module()
    plan = {
        "planHash": "abc",
        "counts": {"create": 1, "update": 2, "retire": 0, "foreign": 2},
        "desiredItems": [{"retailer_id": "WECARE.DIGITAL:v2:x:y"}],
        "existingItems": [
            {"retailer_id": "wix:a:b"},
            {"retailer_id": "wix:c:d"},
            {"retailer_id": "WECARE.DIGITAL:v2:x:y"},
        ],
        "blocked": [],
    }
    summary = mod.summarize_plan(plan)
    assert summary["planHash"] == "abc"
    assert summary["retire"] == 0
    assert summary["foreign"] == 2
    assert summary["foreignIds"] == ["wix:a:b", "wix:c:d"]
