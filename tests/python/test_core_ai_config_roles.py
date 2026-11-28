"""ai-config-management (generic settings API): writes need Operator. No AWS calls."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ai_config_management_under_test", ROOT / "amplify/functions/ai/ai-config-management/handler.py")
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)
RANK = {"Viewer": 1, "Operator": 2, "Admin": 3}


@pytest.mark.parametrize("method,path,role", [
    ("GET", "/ai/config", ""),
    ("PUT", "/ai/config", "Operator"),
])
def test_required_roles(method, path, role):
    assert H._required_write_role(method, path) == role


@pytest.mark.parametrize("role,status,called", [("Viewer", 403, False), ("Operator", 200, True)])
def test_settings_write_refuses_a_viewer(monkeypatch, role, status, called):
    import lambda_utils.middleware as middleware
    calls = []

    def require_auth(event, required_role=None):
        if required_role and RANK[role] < RANK[required_role]:
            return {"statusCode": 403, "body": json.dumps({"error": "Insufficient permissions"})}
        event["_auth"] = {"username": "staff", "role": role, "groups": [role]}
        return None

    monkeypatch.setattr(middleware, "require_auth", require_auth)
    monkeypatch.setattr(H, "_update_config",
                        lambda body, request_id, config_key: calls.append(config_key) or {"statusCode": 200, "body": "{}"})
    event = {"requestContext": {"http": {"method": "PUT", "path": "/ai/config"}},
             "body": json.dumps({"key": "flow_triggers_config", "config": {}}), "headers": {}}
    assert H.handler(event, None)["statusCode"] == status
    assert bool(calls) is called


def test_removed_ai_routes_and_keys_are_refused(monkeypatch):
    import lambda_utils.middleware as middleware
    monkeypatch.setattr(middleware, "require_auth", lambda event, required_role=None: None)
    for key in ("ai_config", "welcome_message", "wa_auto_response"):
        event = {"requestContext": {"http": {"method": "GET", "path": "/ai/config"}},
                 "queryStringParameters": {"key": key}, "headers": {}}
        assert H.handler(event, None)["statusCode"] == 400
    event = {"requestContext": {"http": {"method": "POST", "path": "/ai/test"}},
             "body": "{}", "headers": {}}
    assert H.handler(event, None)["statusCode"] == 400
