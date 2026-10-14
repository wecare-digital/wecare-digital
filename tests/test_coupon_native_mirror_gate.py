"""CATALOG_SOURCE=aws turns off the Wix coupon mirror: a native coupon create is a
clean AWS-only 201, with no Wix call (the admin key is gone post-cutover).

Loads the coupons handler by path (many handler.py files in the repo).
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"


def _load():
    spec = importlib.util.spec_from_file_location("coupons_mirror_gate_test", HANDLER)
    m = importlib.util.module_from_spec(spec)
    sys.modules["coupons_mirror_gate_test"] = m
    spec.loader.exec_module(m)
    return m


def test_mirror_default_on_wix(monkeypatch):
    h = _load()
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    assert h._wix_mirror_enabled() is True


def test_mirror_off_in_native_mode(monkeypatch):
    h = _load()
    for val in ("aws", "AWS", "dynamodb", "native"):
        monkeypatch.setenv("CATALOG_SOURCE", val)
        assert h._wix_mirror_enabled() is False


def test_native_create_returns_201_without_calling_wix(monkeypatch):
    h = _load()
    monkeypatch.setenv("CATALOG_SOURCE", "aws")

    # Guards: staff auth ok, body parsed, local create returns a definition.
    monkeypatch.setattr(h, "_staff", lambda event: None)
    monkeypatch.setattr(h, "_body", lambda event: {"code": "SAVE10"})
    monkeypatch.setattr(h, "_coupons_table", lambda: object())
    definition = {"code": "SAVE10", "couponId": "c1", "discountKind": "PERCENT_OFF"}
    monkeypatch.setattr(h.coupon_store, "create", lambda t, p, created_by=None: definition)
    monkeypatch.setattr(h, "_public", lambda d: d)

    # If the native branch ever calls the Wix mirror, this fails the test.
    def _boom():
        raise AssertionError("native mode must not call the Wix coupon mirror")
    monkeypatch.setattr(h, "_wix", _boom)

    resp = h._create({"_auth": {"username": "staff"}}, origin="https://wecare.digital")
    assert resp["statusCode"] == 201


def test_wix_mode_still_mirrors(monkeypatch):
    h = _load()
    monkeypatch.setenv("CATALOG_SOURCE", "wix")
    monkeypatch.setattr(h, "_staff", lambda event: None)
    monkeypatch.setattr(h, "_body", lambda event: {"code": "SAVE10"})
    monkeypatch.setattr(h, "_coupons_table", lambda: object())
    definition = {"code": "SAVE10", "couponId": "c1", "discountKind": "PERCENT_OFF"}
    monkeypatch.setattr(h.coupon_store, "create", lambda t, p, created_by=None: definition)
    monkeypatch.setattr(h.coupon_store, "mark_mirrored", lambda t, c, i: definition)
    monkeypatch.setattr(h, "_public", lambda d: d)

    called = {"n": 0}

    class _Wix:
        def create(self, d):
            called["n"] += 1
            return "wix-id-1"

    monkeypatch.setattr(h, "_wix", lambda: _Wix())
    resp = h._create({"_auth": {"username": "staff"}}, origin="https://wecare.digital")
    assert resp["statusCode"] == 201
    assert called["n"] == 1  # mirror WAS called in wix mode
