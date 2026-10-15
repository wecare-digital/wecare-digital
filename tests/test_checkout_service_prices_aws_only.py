"""No-network guard: service prices come from the native ProductsTable resolver only."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

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


def test_native_prices_are_served_from_the_native_resolver(monkeypatch):
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


@pytest.mark.parametrize("env_mode", ["AWS_NATIVE", "LEGACY", ""])
def test_an_empty_native_catalog_fails_closed_without_network(monkeypatch, env_mode):
    """Whatever CHECKOUT_MODE says, prices come from the native catalog. A catalog that prices
    nothing answers 503 -- the native fail-closed path -- with no network call to fall back on."""
    h = load_checkout()
    monkeypatch.setenv("CHECKOUT_MODE", env_mode)
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    monkeypatch.setattr(h, "_native_variant_reader", lambda: lambda _id: None)
    response = h._service_prices("https://wecare.digital")
    assert response["statusCode"] == 503
