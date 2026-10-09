"""Admin catalog sync control stays authenticated and never trusts a browser approver."""

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
BIZ = ROOT / "amplify/functions/messaging/whatsapp-business-api"
for p in (str(SHARED), str(BIZ)):
    if p not in sys.path:
        sys.path.insert(0, p)


class _Payload:
    def __init__(self, value):
        self.value = value

    def read(self):
        return json.dumps(self.value).encode("utf-8")


class _Lambda:
    def __init__(self, result=None):
        self.result = result or {"ok": True}
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"Payload": _Payload(self.result)}


@pytest.fixture
def api():
    # Load the whatsapp-business-api handler under a UNIQUE module name rather than the bare
    # `handler`. Several Lambda functions each have a file literally named `handler.py`, so
    # `importlib.import_module("handler")` binds whichever one an earlier test already cached in
    # sys.modules — which is why these tests passed in isolation but failed in the full suite with
    # `module 'handler' from .../ad-attribution/handler.py has no attribute 'require_auth'`. Loading
    # by file path under its own name (the pattern test_customer_orders_flow.py already uses) makes
    # the import order-independent. BIZ/SHARED stay on sys.path so the handler's own submodule
    # imports still resolve.
    handler_path = BIZ / "handler.py"
    spec = importlib.util.spec_from_file_location(
        "catalog_sync_control_biz_handler", handler_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
         patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)
    yield module


def _body(response):
    return json.loads(response["body"])


def test_catalog_sync_control_requires_admin(api):
    lam = _Lambda()
    refusal = api._resp(403, {"error": "Insufficient permissions"})
    with patch.object(api, "require_auth", return_value=refusal), \
         patch.object(api, "lambda_client", lam):
        result = api._catalog_sync_admin_control(
            {"_auth": {"username": "viewer"}}, "GET", {}, {})
    assert result["statusCode"] == 403
    assert lam.calls == []


def test_approve_uses_authenticated_actor_not_browser_value(api):
    lam = _Lambda({"ok": True, "approved": True})
    event = {"_auth": {"username": "owner-admin", "role": "Admin"}}
    with patch.object(api, "require_auth", return_value=None), \
         patch.object(api, "lambda_client", lam):
        result = api._catalog_sync_admin_control(
            event, "POST", {},
            {"action": "approve", "planHash": "a" * 64, "approvedBy": "browser-forged"})
    assert result["statusCode"] == 200
    payload = json.loads(lam.calls[0]["Payload"].decode("utf-8"))
    assert payload == {
        "catalogAction": "approve",
        "planHash": "a" * 64,
        "approvedBy": "owner-admin",
    }
    assert lam.calls[0]["FunctionName"] == "wecare-meta-catalog-sync:live"


@pytest.mark.parametrize("action", ["apply", "readback"])
def test_exact_plan_hash_is_forwarded_for_mutating_control_actions(api, action):
    lam = _Lambda({"ok": True})
    with patch.object(api, "require_auth", return_value=None), \
         patch.object(api, "lambda_client", lam):
        result = api._catalog_sync_admin_control(
            {"_auth": {"username": "owner-admin"}}, "POST", {},
            {"action": action, "planHash": "b" * 64})
    assert result["statusCode"] == 200
    payload = json.loads(lam.calls[0]["Payload"].decode("utf-8"))
    assert payload["catalogAction"] == action
    assert payload["planHash"] == "b" * 64
    assert "approvedBy" not in payload


def test_plan_hash_is_required_for_approve_apply_and_readback(api):
    with patch.object(api, "require_auth", return_value=None):
        for action in ("approve", "apply", "readback"):
            result = api._catalog_sync_admin_control(
                {"_auth": {"username": "owner-admin"}}, "POST", {}, {"action": action})
            assert result["statusCode"] == 400


def test_source_dispatches_catalog_sync_before_catalog_flow_map():
    source = (BIZ / "handler.py").read_text(encoding="utf-8")
    assert "elif '/catalog-sync' in path:" in source
    assert source.index("elif '/catalog-sync' in path:") < source.index("elif '/catalog-flow-map' in path:")
    assert "required_role='Admin'" in source
