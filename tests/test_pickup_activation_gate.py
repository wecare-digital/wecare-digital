"""Paid Pickup release must stay OFF until the live Meta asset is verified.

This is not a live Meta test: the operator must read back the published Flow
JSON and run a paid handset test before setting the production Lambda flags.
"""
from pathlib import Path
import hashlib
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
          "pickup_activation.py")
ASSET = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/"
         "published/request-pickup.json")


def _module():
    spec = importlib.util.spec_from_file_location("pickup_activation", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_expected_fingerprint_is_for_corrected_pickup_json():
    module = _module()
    actual = hashlib.sha256(ASSET.read_bytes()).hexdigest()
    assert actual.startswith(module.EXPECTED_META_ASSET_SHA_PREFIX)
    assert actual == ("9d37ad0dce3cecb09f6788ab54295d954287dad849fd5f2fe220759482c7c6ca")


def test_pickup_remains_off_without_both_flags(monkeypatch):
    module = _module()
    monkeypatch.delenv(module.FEATURE_FLAG, raising=False)
    monkeypatch.delenv(module.ASSET_ATTESTATION, raising=False)
    assert module.enabled() is False
    monkeypatch.setenv(module.FEATURE_FLAG, "true")
    assert module.enabled() is False
    monkeypatch.delenv(module.FEATURE_FLAG, raising=False)
    monkeypatch.setenv(module.ASSET_ATTESTATION, module.EXPECTED_META_ASSET_SHA_PREFIX)
    assert module.enabled() is False


def test_wrong_or_old_meta_asset_never_unlocks_money(monkeypatch):
    module = _module()
    monkeypatch.setenv(module.FEATURE_FLAG, "true")
    for value in ("b685e0289b0257", "", "9d37ad0dce3c", "not-checked", "1"):
        monkeypatch.setenv(module.ASSET_ATTESTATION, value)
        assert module.enabled() is False
    monkeypatch.setenv(module.ASSET_ATTESTATION, module.EXPECTED_META_ASSET_SHA_PREFIX)
    assert module.enabled() is True
    monkeypatch.setenv(module.FEATURE_FLAG, "no")
    assert module.enabled() is False


def test_frontend_requires_the_same_asset_proof():
    source = (ROOT / "src/components/ServiceBuyBox.tsx").read_text()
    assert "NEXT_PUBLIC_PICKUP_SERVICE_ENABLED" in source
    assert "NEXT_PUBLIC_PICKUP_PUBLISHED_ASSET_SHA_PREFIX" in source
    assert "9d37ad0dce3cecb0" in source
    assert "&& !PICKUP_CHECKOUT_ACTIVE" in source


def test_sender_and_checkout_use_same_shared_gate():
    commerce = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                "service_requests.py").read_text()
    sender = (ROOT / "amplify/functions/messaging/whatsapp-business-api/"
              "flows/service_flow_launcher.py").read_text()
    assert "pickup_activation.enabled()" in commerce
    assert "pickup_activation.enabled()" in sender
    assert commerce.index("not pickup_activation.enabled()") < commerce.index(
        "if _single_order_context(verified_service_context, line)"
    )
