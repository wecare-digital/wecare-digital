"""Regression checks for the AI contact tools' DynamoDB expression values."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "amplify/functions/ai/ai-generate-response/handler.py"


def _expression_values(function_name):
    """Return the expression text and the placeholder names bound in ExpressionAttributeValues.

    Only the placeholder NAMES matter here: DynamoDB rejects a request that binds a value the
    expressions never use, or uses one it never binds. The bound values are runtime expressions
    (`email`, `int(time.time())`) that cannot be literal-evaluated, so read the keys only.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
    update = next(node for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update_item")
    args = {kw.arg: kw.value for kw in update.keywords}
    expr = ast.literal_eval(args["UpdateExpression"])
    if "ConditionExpression" in args:
        expr += " " + ast.literal_eval(args["ConditionExpression"])
    values = args["ExpressionAttributeValues"]
    assert isinstance(values, ast.Dict), f"{function_name}: ExpressionAttributeValues is not a dict literal"
    return expr, {ast.literal_eval(key) for key in values.keys}


def test_add_contact_email_does_not_send_unused_placeholders():
    expr, values = _expression_values("_tool_add_contact_email")
    assert ":false" not in values
    assert set(values) == {":email", ":now"}


def test_delete_contact_binds_conditional_lock_placeholder():
    expr, values = _expression_values("_tool_delete_contact")
    assert "locked = :false" in expr
    assert ":false" in values
