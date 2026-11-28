"""PAY-4: Pay-on-WhatsApp create cannot skip its guards, and readiness is read at most once a minute."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "amplify/functions/ecommerce/checkout/handler.py"


def _readiness_namespace(evaluate, clock):
    tree = ast.parse(HANDLER.read_text())
    wanted = {"_READINESS_READY_TTL_SECONDS", "_READINESS_BLOCKED_TTL_SECONDS", "_readiness_cache"}
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name == "_readiness")
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))
             or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") in wanted)]
    namespace = {"Dict": Dict, "Any": Any, "time": SimpleNamespace(time=lambda: clock["now"]),
                 "payment_readiness": SimpleNamespace(evaluate=evaluate,
                                                      PaymentReadiness=object),
                 "PAYMENT_WABA_ID": "waba", "EXPECTED_CONFIGURATION_NAME": "config",
                 "EXPECTED_PROVIDER_MID": "mid", "_fetch_payment_configurations": None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(HANDLER), "exec"), namespace)
    return namespace


def test_ready_verdict_is_reused_for_a_minute_and_a_blocked_one_briefly():
    clock, calls, verdicts = {"now": 1000.0}, [], []

    def evaluate(**_kwargs):
        calls.append(clock["now"])
        return verdicts.pop(0)

    verdicts.extend([SimpleNamespace(ready=True), SimpleNamespace(ready=False),
                     SimpleNamespace(ready=True)])
    readiness = _readiness_namespace(evaluate, clock)["_readiness"]
    assert readiness().ready and readiness().ready
    clock["now"] += 59
    assert readiness().ready
    assert calls == [1000.0]
    clock["now"] += 2                     # past 60 s: read again, now blocked
    assert not readiness().ready
    clock["now"] += 9
    assert not readiness().ready          # blocked verdict still cached
    clock["now"] += 2                     # past 10 s: read again
    assert readiness().ready
    assert len(calls) == 3


def _create_branch():
    """The body of `if action == "create":` inside `handler`, runnable with fakes."""
    tree = ast.parse(HANDLER.read_text())
    handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "handler")
    branch = next(n for n in ast.walk(handler)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                  and getattr(n.test.left, "id", "") == "action"
                  and getattr(n.test.comparators[0], "value", None) == "create")
    run = ast.FunctionDef(name="run", args=ast.arguments(
        posonlyargs=[], args=[ast.arg(arg="body")], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=branch.body, decorator_list=[])
    return ast.fix_missing_locations(ast.Module(body=[run], type_ignores=[]))


@pytest.mark.parametrize("request_key,refused", [
    (None, True), ("", True), ("   ", True), (["k"], True), ("key-0123456789abcdef", False)])
def test_http_create_requires_a_request_key(request_key, refused):
    created = []
    namespace = {
        "cors_response": lambda code, body, _origin: {"statusCode": code, "body": body},
        "_website_contribution_requires_web_rail": lambda _lines: False,
        "_create": lambda identity, body, origin: created.append(body) or {"statusCode": 200},
        "identity": object(), "origin": "",
    }
    exec(compile(_create_branch(), str(HANDLER), "exec"), namespace)
    body = {"lineItems": [{"quantity": 1}]}
    if request_key is not None:
        body["requestKey"] = request_key
    response = namespace["run"](body)
    if refused:
        assert response == {"statusCode": 400, "body": {
            "error": "REQUEST_KEY_REQUIRED", "message": "Please refresh the page and try again."}}
        assert created == []
    else:
        assert response == {"statusCode": 200} and created == [body]
