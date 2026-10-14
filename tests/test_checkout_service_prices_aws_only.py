"""No-network guard: checkout loads after removal of legacy Wix service pricing."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))


def load_checkout():
    p = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
    spec = importlib.util.spec_from_file_location("checkout_service_prices_aws_only", p)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_native_prices_do_not_require_deleted_wix_service_pricing(monkeypatch):
    h = load_checkout()
    monkeypatch.setenv("CHECKOUT_MODE", "AWS_NATIVE")
    from lambda_utils.ecommerce import service_pricing_native

    monkeypatch.setattr(
        service_pricing_native, "resolve_all",
        lambda reader: {
            "currency": "INR",
            "prices": {"anew": {"available": True, "paise": 59900}},
        },
    )
    monkeypatch.setattr(h, "_native_variant_reader", lambda: lambda _: None)
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 200


def test_retired_wix_price_mode_returns_503_without_network(monkeypatch):
    h = load_checkout()
    monkeypatch.setenv("CHECKOUT_MODE", "WIX_HEADLESS")
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    monkeypatch.setattr(
        h.cart_v2, "CartV2",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Wix cart must not be called")),
    )
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 503
