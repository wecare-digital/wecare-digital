"""Native coupon route security invariants — no Wix.

Preserved from the retired `test_coupon_reconciliation.py` (which tested the deleted Wix coupon
mirror / Wix cart reconciliation). These two properties are provider-independent and matter on
the native path exactly as they did on the Wix one:

  1. A browser may supply a CODE and a cartId, never an amount. The customer-body allowlist is a
     closed set and an unexpected key is REFUSED (raised), not silently dropped — so no client
     can smuggle a discount/total into a coupon route.
  2. The validate route returns a VERDICT and never a money figure.

Both are asserted structurally (AST over the handler source) so they do not depend on a live
table or any provider adapter.
"""
import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"


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
    # The native verdict vocabulary — no WIX_MIRROR_INCOMPLETE.
    assert set(cs.VERDICTS) == {
        "ELIGIBLE", "UNKNOWN_CODE", "NOT_ACTIVE", "NOT_STARTED", "EXPIRED",
        "USAGE_LIMIT_REACHED", "CUSTOMER_LIMIT_REACHED", "HELD_BY_ANOTHER_CART"}
