"""PAY-8: explicit staff roles on payments-read, product-image-gen and catalog-management."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest

from lambda_utils import middleware  # imported for real first, so no fake client is cached

_FUNCTIONS = Path(__file__).resolve().parents[2] / "amplify/functions"


def _load(relative, name, monkeypatch):
    class NoAws:
        def __getattr__(self, _attr):
            raise AssertionError("no AWS in this test")

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_kw: NoAws())
    monkeypatch.setattr(boto3, "client", lambda *_a, **_kw: NoAws())
    spec = importlib.util.spec_from_file_location(name, _FUNCTIONS / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _api_event(**extra):
    return {"requestContext": {"http": {"method": "GET"}, "apiId": "api"}, "headers": {}, **extra}


@pytest.fixture
def roles(monkeypatch):
    asked = []
    state = {"role": "Viewer"}

    def require_auth(event, required_role=None):
        asked.append(required_role)
        event["_auth"] = {"role": state["role"]}
        return None

    monkeypatch.setattr(middleware, "require_auth", require_auth)
    return asked, state


# ── payments-read ────────────────────────────────────────────────────────────────

ROWS = [[{"id": "pay_old", "createdAt": 100, "contact": "+919000000001", "email": "old@example.com",
          "amount": 100}],
        [{"id": "pay_new", "createdAt": 300, "contact": "+919000000002", "email": "new@example.com",
          "amount": 200}]]


@pytest.fixture
def payments(monkeypatch, roles):
    module = _load("payments/payments-read/handler.py", "payments_read_under_test", monkeypatch)
    pages = []

    def scan(**kwargs):
        index = len(pages)
        pages.append(kwargs)
        more = index + 1 < len(ROWS)
        return {"Items": list(ROWS[index]), **({"LastEvaluatedKey": {"id": "x"}} if more else {})}

    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=lambda _n: SimpleNamespace(scan=scan)))
    return module, roles


def _list(module, **params):
    response = module.handler(_api_event(queryStringParameters=params), None)
    return response["statusCode"], json.loads(response["body"])


def test_viewer_gets_masked_contacts_and_the_newest_rows(payments):
    module, (asked, _state) = payments
    status, body = _list(module, limit="1")
    assert status == 200 and asked == ["Viewer"]
    (row,) = body["payments"]
    assert row["id"] == "pay_new"                       # sorted before the limit applies
    assert row["contact"] == "+91****0002" and row["email"] == "n***@example.com"


def test_viewer_cannot_search_by_contact(payments):
    module, _roles = payments
    status, body = _list(module, contact="9000000002")
    assert status == 403


def test_operator_sees_payer_contacts(payments):
    module, (_asked, state) = payments
    state["role"] = "Operator"
    status, body = _list(module)
    assert status == 200
    assert {row["contact"] for row in body["payments"]} == {"+919000000001", "+919000000002"}


# ── product-image-gen (Pillow is not needed: functions are run from source) ──────

_IMAGE_GEN = _FUNCTIONS / "ecommerce/product-image-gen/handler.py"


def _image_gen(names, **namespace):
    tree = ast.parse(_IMAGE_GEN.read_text())
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") in {"IMG_SIZE", "_MIN_FLAG_SIZE"} for t in n.targets))]
    namespace.setdefault("_resp", lambda code, body: {"statusCode": code, "body": body})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(_IMAGE_GEN), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("method,role", [("POST", "Operator"), ("GET", "Viewer")])
def test_image_writes_need_operator(method, role):
    asked = []
    ns = _image_gen({"handler"}, json=json, extract_origin=lambda _e: "",
                    logger=SimpleNamespace(error=lambda *_: None),
                    require_auth=lambda event, required_role=None: asked.append(required_role) or
                    {"statusCode": 403},
                    Dict=dict, Any=object)
    response = ns["handler"]({"requestContext": {"http": {"method": method}},
                              "rawPath": "/store/convert-flag", "path": "/store/convert-flag"}, None)
    assert response == {"statusCode": 403} and asked == [role]


@pytest.mark.parametrize("size", [100000, 10, "huge", -5])
def test_flag_canvas_size_is_bounded_before_any_work(size):
    ns = _image_gen({"_convert_flag_to_png"},
                    _fetch_flag=lambda *_a: pytest.fail("no work before the size check"),
                    Dict=dict, Any=object)
    response = ns["_convert_flag_to_png"]({"country": "in", "size": size}, "req")
    assert response["statusCode"] == 400


# ── catalog-management ───────────────────────────────────────────────────────────

@pytest.fixture
def catalog(monkeypatch, roles):
    module = _load("ecommerce/catalog-management/handler.py", "catalog_management_under_test",
                   monkeypatch)
    listed = []
    monkeypatch.setattr(module, "_list_products",
                        lambda catalog_id, _params: listed.append(catalog_id) or {"statusCode": 200})
    return module, roles, listed


@pytest.mark.parametrize("catalog_id,expected", [("123456789", 200), ("123/products", 400),
                                                 ("me", 400), ("1?fields=x", 400)])
def test_catalog_routes_need_admin_and_numeric_graph_ids(catalog, catalog_id, expected):
    module, (asked, _state), listed = catalog
    event = _api_event(rawPath="/catalog/products", queryStringParameters={"catalogId": catalog_id})
    event["requestContext"]["http"]["path"] = "/catalog/products"
    response = module.handler(event, None)
    assert asked == ["Admin"] and response["statusCode"] == expected
    assert listed == ([catalog_id] if expected == 200 else [])
