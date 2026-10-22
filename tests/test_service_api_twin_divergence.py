"""Service Ops has exactly one business-logic implementation."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = ROOT / "amplify/functions/core/service-api/handler.py"
RETIRED = ROOT / "amplify/functions/messaging/whatsapp-business-api/service_api.py"
IMPORTER = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
DEPLOY = ROOT / "scripts/deploy_all_lambdas.py"


def test_duplicate_service_api_module_is_retired():
    assert not RETIRED.exists()


def test_whatsapp_business_api_no_longer_imports_service_api():
    source = IMPORTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "service_api"
    ]
    assert not imports
    assert "SERVICE MODULE ROUTES" not in source


def test_duplicate_service_api_is_not_packaged():
    source = DEPLOY.read_text(encoding="utf-8")
    spec = source[source.index('"wecare-whatsapp-business-api"'):]
    spec = spec[:spec.index("),") + 2]
    assert "service_api.py" not in spec


def test_canonical_service_api_authenticates_before_dispatching():
    source = ENTRY_POINT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "handler"
    )
    auth_lines = [
        node.lineno for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "require_auth")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "require_auth")
        )
    ]
    route_lines = [
        node.lineno for node in ast.walk(handler)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.In) for op in node.ops)
        and any(
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.startswith("/")
            for value in node.comparators + [node.left]
        )
    ]
    assert auth_lines
    if route_lines:
        assert min(auth_lines) < min(route_lines)
