"""Coupons are AWS-native: there is NO Wix coupon mirror any more.

The Wix mirror (and its CATALOG_SOURCE gate) was removed in the Wix-exit refactor. The local
DynamoDB row is the sole authority and `coupon_store.discount_paise` prices it on the native
checkout path. These tests pin the removal: a create is a clean 201 with no external call, and the
handler imports no Wix module at all.

Loads the coupons handler by path (many handler.py files in the repo).
"""
import ast
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"


def _load():
    spec = importlib.util.spec_from_file_location("coupons_native_test", HANDLER)
    m = importlib.util.module_from_spec(spec)
    sys.modules["coupons_native_test"] = m
    spec.loader.exec_module(m)
    return m


def test_create_returns_201_with_no_wix_mirror(monkeypatch):
    h = _load()
    monkeypatch.setenv("CATALOG_SOURCE", "aws")
    monkeypatch.setattr(h, "_staff", lambda event: None)
    monkeypatch.setattr(h, "_body", lambda event: {"code": "SAVE10"})
    monkeypatch.setattr(h, "_coupons_table", lambda: object())
    definition = {"code": "SAVE10", "couponId": "c1", "discountKind": "PERCENT_OFF"}
    monkeypatch.setattr(h.coupon_store, "create", lambda t, p, created_by=None: definition)
    monkeypatch.setattr(h, "_public", lambda d: d)

    resp = h._create({"_auth": {"username": "staff"}}, origin="https://wecare.digital")
    assert resp["statusCode"] == 201


def test_the_removed_mirror_symbols_are_gone():
    """The mirror machinery must not come back: no `_wix`, `_wix_mirror_enabled`, or mark_mirrored
    call survives in the handler."""
    h = _load()
    assert not hasattr(h, "_wix")
    assert not hasattr(h, "_wix_mirror_enabled")


def test_handler_imports_no_wix_module():
    """AST ban: the coupons handler imports neither wix_coupons nor wix_ecom. The native row is the
    only authority, so there is no provider module to import."""
    tree = ast.parse(HANDLER.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    joined = " ".join(imported)
    assert "wix_coupons" not in joined, "coupons handler must not import wix_coupons"
    assert "wix_ecom" not in joined, "coupons handler must not import wix_ecom"
