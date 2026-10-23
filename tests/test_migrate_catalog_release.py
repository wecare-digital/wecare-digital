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


def test_inspect_meta_returns_status_and_does_not_raise_on_409():
    """The Meta inspect must hand the status back so the caller can distinguish an owner-gated
    'plan not loaded' (409) from an unexpected transport error - it no longer raises on 409."""
    mod = load_module()

    captured = {}

    def fake_http_json(method, url, token, body=None):
        captured["method"] = method
        return 409, {"ok": False, "reason": "unconfigured"}

    mod.http_json = fake_http_json  # type: ignore[assignment]
    status, data = mod.inspect_meta("https://wecare.digital/api", "tok")
    assert status == 409
    assert data["reason"] == "unconfigured"
    assert captured["method"] == "GET"


def test_plan_not_loaded_reasons_match_the_handler_inspect_failures():
    """These are exactly the ok:False reasons the meta-catalog-sync GET/inspect path can return;
    treating them as 'plan not loaded' (success) rather than a release failure is the fix for the
    HTTP 409 on the bulk catalog release."""
    mod = load_module()
    assert "unconfigured" in mod.META_PLAN_NOT_LOADED_REASONS
    assert "read_failed" in mod.META_PLAN_NOT_LOADED_REASONS
    assert "approval_store_unavailable" in mod.META_PLAN_NOT_LOADED_REASONS
    # A genuine plan state (blocked) must NOT be silently treated as not-loaded.
    assert "blocked" not in mod.META_PLAN_NOT_LOADED_REASONS
