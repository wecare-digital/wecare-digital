"""Coupon route invariants, asserted against the handler itself.

  1. A browser may supply a CODE and a cartId, never an amount. The customer-body allowlist is a
     closed set and an unexpected key is REFUSED (raised), not silently dropped — so no client
     can smuggle a discount/total into a coupon route.
  2. The validate route returns a VERDICT and never a money figure.
  3. The staff routes answer with the allowlisted projection of the stored row and nothing else,
     and the handler reaches coupons only through `coupon_store`, the one authority.

The first two are asserted structurally (AST over the handler source) so they do not depend on a
live table; the third drives the handler against the in-memory table.
"""
import ast
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"


def _load_handler():
    spec = importlib.util.spec_from_file_location("coupons_route_contract", HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["coupons_route_contract"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("smuggled", ["discountPaise", "amount", "amountPaise", "discount",
                                      "total", "moneyOffPaise", "customerId"])
def test_a_browser_cannot_supply_a_discount_only_a_code_to_the_coupon_routes(smuggled):
    """The customer body allowlist is {code, cartId}; anything else is refused with a raise."""
    source = HANDLER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(HANDLER))
    allowlist = next(
        ast.literal_eval(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "CUSTOMER_BODY_FIELDS"
                for t in node.targets))
    assert set(allowlist) == {"code", "cartId"}
    assert smuggled not in allowlist

    # And the refusal is a raise, not a filter.
    body_reader = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name == "_customer_body")
    rendered = ast.unparse(body_reader)
    assert "set(parsed) - set(CUSTOMER_BODY_FIELDS)" in rendered
    assert "raise Refused(400, 'UNSUPPORTED_FIELD')" in rendered


def test_the_coupon_validate_route_returns_a_verdict_and_no_amount():
    """No `return` in `_validate` renders a money-shaped key, and the verdict set is closed."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    validate = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "_validate")
    for node in ast.walk(validate):
        if not isinstance(node, ast.Return):
            continue
        rendered = ast.unparse(node)
        for money in ("paise", "Paise", "amount", "Amount", "discount", "Discount", "total"):
            assert money not in rendered
    assert set(cs.VERDICTS) == {
        "ELIGIBLE", "UNKNOWN_CODE", "NOT_ACTIVE", "NOT_STARTED", "EXPIRED",
        "USAGE_LIMIT_REACHED", "CUSTOMER_LIMIT_REACHED", "HELD_BY_ANOTHER_CART"}


def test_every_published_attribute_is_a_declared_row_attribute():
    """The staff projection can only publish what a definition row is declared to carry."""
    handler = _load_handler()
    assert set(handler.PUBLIC_ATTRIBUTES) <= set(cs.DEFINITION_ATTRIBUTES), (
        set(handler.PUBLIC_ATTRIBUTES) - set(cs.DEFINITION_ATTRIBUTES))


def test_staff_create_then_get_answer_with_the_stored_row_and_nothing_else(monkeypatch):
    """`POST /coupons` is ONE conditional put answered 201, and the coupon is readable at once:
    `GET /coupons/{code}` returns that same row through `PUBLIC_ATTRIBUTES`, under a single
    `coupon` key, with no other top-level field."""
    handler = _load_handler()
    store = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                      indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    monkeypatch.setattr(handler, "_staff", lambda event: None)
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    payload = {"code": "SAVE10", "name": "Ten rupees off", "discountKind": cs.MONEY_OFF,
               "moneyOffPaise": 100000, "startTimeMs": 1_700_000_000_000,
               "minimumSubtotalPaise": 500000}

    created = handler.handler({"routeKey": "POST /coupons", "headers": {},
                               "body": json.dumps(payload)}, None)
    assert created["statusCode"] == 201
    assert store.operations() == ["put_item"]
    created_body = json.loads(created["body"])
    assert set(created_body) == {"coupon"}

    read = handler.handler({"routeKey": "GET /coupons/{code}", "headers": {},
                            "pathParameters": {"code": "save10"}}, None)
    assert read["statusCode"] == 200
    read_body = json.loads(read["body"])
    assert set(read_body) == {"coupon"}
    stored = store.rows["COUPON#SAVE10"]
    assert read_body["coupon"] == {key: stored[key] for key in handler.PUBLIC_ATTRIBUTES
                                   if key in stored}
    assert read_body["coupon"] == created_body["coupon"]
    assert read_body["coupon"]["status"] == cs.STATUS_ACTIVE


def test_the_handler_reaches_coupons_only_through_coupon_store():
    """One authority: the only commerce module the handler imports is `coupon_store`."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    commerce = sorted(
        f"{node.module}.{alias.name}" for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "lambda_utils.ecommerce")
        for alias in node.names)
    assert commerce == ["lambda_utils.ecommerce.coupon_store"]
    plain = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names]
    assert not [name for name in plain if name.startswith("lambda_utils.ecommerce")]
