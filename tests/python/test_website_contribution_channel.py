"""Isolated contribution guard and integer-price regression; no provider calls."""
import ast
from pathlib import Path

from lambda_utils.ecommerce.blog_contribution import CONTRIBUTION_PRODUCT_IDS
from lambda_utils.ecommerce.contribute_taxable import breakdown

ROOT = Path(__file__).resolve().parents[2]


def test_public_contribution_requires_website_payment():
    # Compile only the pure predicate, without importing the Lambda's runtime.
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    guard = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "_website_contribution_requires_web_rail")
    namespace = {"Any": object, "CONTRIBUTION_PRODUCT_IDS": CONTRIBUTION_PRODUCT_IDS}
    exec(compile(ast.Module(body=[guard], type_ignores=[]), "<guard>", "exec"), namespace)
    requires_web = namespace[guard.name]
    line = {"catalogReference": {"catalogItemId": next(iter(CONTRIBUTION_PRODUCT_IDS)).upper()}, "quantity": 1}
    ordinary = {"catalogReference": {"catalogItemId": "ordinary"}, "quantity": 1}
    assert requires_web([line])
    assert requires_web([ordinary, line])
    assert not requires_web([ordinary])
    assert not requires_web([None, {}, {"catalogReference": None}])
    assert not requires_web(None)


def test_contribution_breakdown_reconciles():
    quote = breakdown(30000)
    assert quote["totalPayablePaise"] == 30000
    assert quote["itemSubtotalPaise"] + quote["supplyGstPaise"] - quote["delightPaise"] + quote["expressPaise"] + quote["convenienceFeePaise"] + quote["convenienceGstPaise"] == 30000
