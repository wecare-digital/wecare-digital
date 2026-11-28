"""ai-config-management: POST /ai/test (a Bedrock call) needs Operator. No AWS calls."""
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
    ("POST", "/ai/test", "Operator"),
    ("GET", "/ai/config", ""),
    ("PUT", "/ai/config", "Operator"),
    ("POST", "/ai/clear-logs", "Admin"),
])
def test_required_roles(method, path, role):
    assert H._required_write_role(method, path) == role


@pytest.mark.parametrize("role,status,called", [("Viewer", 403, False), ("Operator", 200, True)])
def test_ai_test_route_refuses_a_viewer(monkeypatch, role, status, called):
    import lambda_utils.middleware as middleware
    calls = []

    def require_auth(event, required_role=None):
        if required_role and RANK[role] < RANK[required_role]:
            return {"statusCode": 403, "body": json.dumps({"error": "Insufficient permissions"})}
        event["_auth"] = {"username": "staff", "role": role, "groups": [role]}
        return None

    monkeypatch.setattr(middleware, "require_auth", require_auth)
    monkeypatch.setattr(H, "_test_ai_response",
                        lambda body, request_id: calls.append(body) or {"statusCode": 200, "body": "{}"})
    event = {"requestContext": {"http": {"method": "POST", "path": "/ai/test"}},
             "body": json.dumps({"message": "hello"}), "headers": {}}
    assert H.handler(event, None)["statusCode"] == status
    assert bool(calls) is called
