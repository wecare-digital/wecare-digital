from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_commerce_shadow_spec_matches_checkout_package():
    deploy = _load(ROOT / "scripts" / "deploy_all_lambdas.py", "_deploy_all_commerce_test")
    by_name = {row.name: row for row in deploy.SPECS}

    assert "wecare-checkout" in by_name
    assert "wecare-commerce" in by_name
    assert "wecare-razorpay-webhook" in by_name

    checkout = by_name["wecare-checkout"]
    commerce = by_name["wecare-commerce"]

    assert commerce.source == checkout.source
    assert commerce.extra_files == checkout.extra_files
    assert commerce.external_files == checkout.external_files
    assert commerce.external_dirs == checkout.external_dirs
    assert commerce.required_layers == checkout.required_layers
    assert commerce.required_memory == checkout.required_memory == 512
    assert commerce.required_timeout == checkout.required_timeout == 60
    assert commerce.provisioned_by == "python scripts/provision_commerce.py"


def test_shadow_provisioner_creates_no_routes_or_api_permission():
    source = (ROOT / "scripts" / "provision_commerce.py").read_text(encoding="utf-8")

    assert "SHADOW (no API Gateway routes, no API invoke permission)" in source
    assert "checkout.ensure_routes(" not in source
    assert "checkout.ensure_integration(" not in source
    assert "checkout.ensure_invoke_permission(" not in source
    assert "checkout.ensure_route_throttle(" not in source

    # Verification must actively refuse an accidentally exposed shadow alias.
    assert "live_policy_statements()" in source
    assert "shadow live alias has invoke/resource-policy statements" in source


def test_commerce_manifest_starts_from_checkout_contract():
    manifest = json.loads(
        (ROOT / "config" / "lambda-env-manifest.json").read_text(encoding="utf-8")
    )["functions"]

    assert manifest["wecare-commerce"] == manifest["wecare-checkout"]
    assert manifest["wecare-commerce"]["WA_PAY_TEMPLATE"] == "wecare_whatapp_native_pay_template"
    assert (
        manifest["wecare-commerce"]["WA_INVOICE_TEMPLATE"]
        == "wecare_default_invoice_image_template"
    )
    assert manifest["wecare-commerce"]["OUTBOUND_FUNCTION"] == "wecare-outbound-whatsapp:live"


def test_razorpay_verifier_remains_independent():
    deploy = _load(ROOT / "scripts" / "deploy_all_lambdas.py", "_deploy_all_webhook_test")
    names = {row.name for row in deploy.SPECS}

    assert "wecare-razorpay-webhook" in names
    assert "wecare-commerce" in names
