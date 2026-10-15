"""What `POST /ecommerce/checkout` with `action=create` can and cannot do while the gate is off.

Why this file exists
--------------------
The deployment brief named one literal deliverable: `action=create` must answer
`PAYMENT_INITIATION_DISABLED` rather than 404. It does not, and cannot, be observed from outside:
`handler.handler` calls `customer_auth.require_customer` before it parses the body, so an
unauthenticated probe gets 401 and never reaches the branch; and inside `_create` the readiness
evaluation precedes the gate, so with both `EXPECTED_*` inputs empty an authenticated request gets
409 `payment_unavailable` before the gate is consulted.

Making the literal probe observable would mean weakening authentication or reordering the handler.
Both change what the endpoint does, so neither was done. What was done instead is this file: the
branch is pinned by assertion, and the two structural facts that make the probe unreachable are
pinned too, so the substitution recorded in docs/execution/checkout-deployment-20261001.md is
machine-checked rather than taken on trust. The accompanying artifact is
docs/execution/snapshots/checkout-gate-ordering-20261001.json, measured from the bytes on the
`live` alias rather than from this working tree.

The direction these assertions fail in
--------------------------------------
`test_no_new_side_effect_creeps_in_before_the_gate` is a SUBSET assertion, deliberately. Moving the
gate earlier, or removing a side effect from in front of it, makes the endpoint more inert and must
not turn the suite red. Adding a NEW side effect ahead of the gate is the dangerous direction - that
is how "initiation is off" quietly stops meaning "nothing happens" - and that is what fails here.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HANDLER = ROOT / "amplify" / "functions" / "ecommerce" / "checkout" / "handler.py"

#: Calls that reach outside the process, ordered as they appear in `_create`. Each is a real effect
#: an authenticated `action=create` performs BEFORE the gate refuses, which is why "the gate is off"
#: is a statement about payment initiation and not about inertness. Recorded as the known set so a
#: new one cannot arrive unnoticed.
KNOWN_SIDE_EFFECTS_BEFORE_THE_GATE = {
    "allocate_payment_reference",   # reserves PAYREF# in the commerce-keys table
    "put_item",                     # writes the PaymentAttempt row
}

#: Every outbound-looking callee name we scan for. Anything in this list that appears before the
#: gate and is NOT in the known set above is a new side effect.
SIDE_EFFECT_NEEDLES = (
    "create_checkout", "allocate_payment_reference", "put_item", "update_item", "delete_item",
    "transact_write_items", "invoke", "publish", "send_message", "create_order",
    "allocate_order_number", "post", "put", "request",
)


@pytest.fixture(scope="module")
def handler_ast():
    if not HANDLER.is_file():
        pytest.skip("checkout handler not present in this checkout")
    return ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))


def _function(tree: ast.AST, name: str):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name}() is gone from the checkout handler")


def _callee(call: ast.Call) -> str:
    """The final identifier of a call's callee: `a.b.put_item(...)` -> `put_item`.

    Exact, not a substring search. A substring search over the rendered callee reported `put` as a
    distinct side effect because it is a prefix of `put_item`, i.e. the check failed on its own
    overlapping needle list rather than on anything in the handler.
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _first_call(scope, needle: str):
    hits = sorted(call.lineno for call in ast.walk(scope)
                  if isinstance(call, ast.Call) and _callee(call) == needle)
    return hits[0] if hits else None


def _gate_line(create) -> int:
    gates = [node.lineno for node in ast.walk(create)
             if isinstance(node, ast.If) and "INITIATION_ENABLED" in ast.unparse(node.test)]
    assert gates, "the INITIATION_ENABLED gate is gone from _create()"
    return gates[0]


def test_authentication_runs_before_the_body_is_even_parsed(handler_ast):
    """The reason the literal `PAYMENT_INITIATION_DISABLED` probe is unreachable, and a safety
    property in its own right: no body-supplied value can influence anything before the caller has
    proven an identity, so an unauthenticated request cannot cause a side effect at all."""
    handler = _function(handler_ast, "handler")
    auth = _first_call(handler, "require_customer")
    body = _first_call(handler, "_body")
    assert auth is not None, "require_customer() is gone — the endpoint would be public"
    assert body is not None, "the body parse moved; re-measure this ordering"
    assert auth < body, (f"the body is parsed at line {body}, before require_customer at "
                         f"line {auth} — an unauthenticated caller now reaches request data")


def test_no_action_dispatch_happens_before_authentication(handler_ast):
    """`_create` and `_status` must both sit behind the identity check, not beside it."""
    handler = _function(handler_ast, "handler")
    auth = _first_call(handler, "require_customer")
    for branch in ("_create", "_status"):
        line = _first_call(handler, branch)
        assert line is not None and line > auth, \
            f"{branch} is dispatched at line {line}, not after require_customer at {auth}"


def test_the_gate_still_answers_the_contract_the_brief_named(handler_ast):
    """`PAYMENT_INITIATION_DISABLED` is unobservable from outside today, so it is asserted here.
    The branch is covered end-to-end by
    tests/test_checkout_handler.py::test_create_disabled_prepares_attempt_but_sends_nothing_and_makes_no_order,
    which drives it with an authenticated fixture."""
    create = _function(handler_ast, "_create")
    gate_line = _gate_line(create)
    gate = next(node for node in ast.walk(create)
                if isinstance(node, ast.If) and node.lineno == gate_line)
    rendered = ast.unparse(gate)
    assert "PAYMENT_INITIATION_DISABLED" in rendered, \
        "the gate no longer answers PAYMENT_INITIATION_DISABLED"
    assert "ORDERNO" not in rendered and "create_order" not in rendered, \
        "the disabled branch must not create an order"


def test_no_new_side_effect_creeps_in_before_the_gate(handler_ast):
    """A SUBSET assertion: the gate becoming earlier is an improvement and stays green; a new
    outbound call appearing ahead of it is how 'initiation off' stops meaning 'nothing happens'.

    The two known effects are the reference reservation and the attempt row; the price itself is
    a ProductsTable read, which writes nothing. What this pins is that the list cannot grow
    silently.
    """
    create = _function(handler_ast, "_create")
    gate_line = _gate_line(create)
    before = {needle for needle in SIDE_EFFECT_NEEDLES
              if (line := _first_call(create, needle)) is not None and line < gate_line}
    new = before - KNOWN_SIDE_EFFECTS_BEFORE_THE_GATE
    assert not new, (
        "new side effect(s) now run before the initiation gate refuses: "
        + ", ".join(sorted(new))
        + ". Every one of these happens on an authenticated action=create while the gate is OFF, so "
          "the evidence in docs/execution/checkout-deployment-20261001.md is now understated. "
          "Either move the gate above them or update the recorded consequence.")


def test_the_disabled_branch_creates_no_order_and_no_gateway_order(handler_ast):
    """The one property that must hold whatever the ordering: nothing on the disabled path mints an
    order number, an order, or a provider payment."""
    create = _function(handler_ast, "_create")
    gate_line = _gate_line(create)
    gate = next(node for node in ast.walk(create)
                if isinstance(node, ast.If) and node.lineno == gate_line)
    forbidden = ("allocate_order_number", "create_order", "razorpay", "create_payment",
                 "capture", "refund")
    rendered = ast.unparse(gate).lower()
    for needle in forbidden:
        assert needle not in rendered, f"the disabled branch reaches {needle}"
