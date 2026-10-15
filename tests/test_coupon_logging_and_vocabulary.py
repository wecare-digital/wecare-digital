"""What the coupon handler may and may not put in a log line.

The asymmetry these two tests protect is deliberate and runs in OPPOSITE directions
-----------------------------------------------------------------------------------
* A secret must not appear in a logging expression AT ALL - not "must not be logged".
  CodeQL's `py/clear-text-logging-sensitive-data` failed this repository's build twice on a line
  that could not leak anything (`"google" if key else "aws"`), and it was right to: the analysis
  cannot prove the value is discarded, and neither can a reviewer at a glance. It also tracks
  taint across function boundaries, so reducing a secret to a bool in a helper does not launder
  it. Hence test 59 walks transitively.
* A coupon code MAY be logged in full. It is broadcast marketing material, printed in campaigns
  and shared deliberately - the exact opposite of a gift-card code, where the same position is
  occupied by an HMAC. Test 60 exists so a later "harden the logging" pass has to read this
  paragraph before masking the one correlation id this path has.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"
STORE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/coupon_store.py"
VOCABULARY_GATE = ROOT / "tests/test_payment_vocabulary_at_decision_points.py"

SOURCE = HANDLER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(HANDLER))

#: Every name by which a credential could be reached in this function. A SECRET NAME is a name,
#: not a value, and may appear in the source - what must never appear in a logging expression is
#: anything that could hold or be derived from the VALUE.
SECRET_BEARING_NAMES = {"api_key", "_api_key", "apiKey", "key", "secret", "_key_cache",
                        "get_secret_value"}


def _functions(tree: ast.Module) -> dict:
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _logging_calls(node: ast.AST) -> list:
    return [call for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "logger"]


def _names_in(node: ast.AST) -> set:
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _called_local_functions(node: ast.AST, local: dict) -> set:
    return {call.func.id for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id in local}


# ── 59 ────────────────────────────────────────────────────────────────────────

def test_no_logging_expression_reaches_a_secret():
    """An AST walk of every `logger.*` argument, TRANSITIVELY through local helpers.

    Transitive because CodeQL is: `provider <- _google_enabled() <- _google_key() <- the secret`
    is one call chain, and the build failed on it. A test that only inspected the immediate
    argument expression would pass on exactly the code that failed CI.
    """
    local = _functions(TREE)
    offenders = []

    for call in _logging_calls(TREE):
        reachable = set()
        frontier = [argument for argument in list(call.args) + [kw.value for kw in call.keywords]]
        seen_helpers = set()
        while frontier:
            node = frontier.pop()
            reachable |= _names_in(node)
            for helper in _called_local_functions(node, local) - seen_helpers:
                seen_helpers.add(helper)
                frontier.append(local[helper])
        tainted = reachable & SECRET_BEARING_NAMES
        if tainted:
            offenders.append(f"line {call.lineno}: logging expression reaches {sorted(tainted)}"
                             f" (helpers walked: {sorted(seen_helpers)})")

    assert not offenders, "\n  ".join(offenders) + (
        "\n\nRemove the log, or derive the logged value from something that never touched the "
        "secret. Reducing it to a bool does not launder it.")


def test_the_coupon_path_reads_no_secret_so_there_is_nothing_to_leak():
    """The coupons handler and `coupon_store` need no credential: a coupon is a CouponsTable row
    and nothing else. With no secret read anywhere on this path, no log line can carry one."""
    assert "get_secret_value" not in SOURCE
    assert "secretsmanager" not in SOURCE
    # The coupon store also reads no secret directly.
    store_text = STORE.read_text(encoding="utf-8")
    assert "get_secret_value" not in store_text
    assert "secretsmanager" not in store_text


def test_an_exception_contributes_only_its_type_name_to_a_log_line():
    """An exception message can carry a status as prose, or a value, and a status in a log is one
    grep away from a branch - so the handler logs an exception by its type name only."""
    for call in _logging_calls(TREE):
        rendered = ast.unparse(call)
        assert "str(exc" not in rendered
        assert "exc.args" not in rendered
        if "exc" in rendered:
            assert "type(exc).__name__" in rendered, \
                f"line {call.lineno} logs an exception other than by type name"


# ── 60 ────────────────────────────────────────────────────────────────────────

def test_a_coupon_code_may_be_logged_in_full():
    """Pins the deliberate asymmetry against gift cards, so nobody "hardens" this into masking
    and loses the correlation id.

    A coupon code is not bearer value: it is printed in campaigns and shared on purpose. A
    gift-card code is the opposite, which is why the gift-card store keys on an HMAC and logs
    only `codeLast4`. Harmonising the two would be a regression in this direction, not an
    improvement.
    """
    logged = [ast.unparse(call) for call in _logging_calls(TREE)]
    assert logged, "the handler logs nothing at all, so the asymmetry is untested"
    # `ast.unparse` normalises string quotes, so match on the key without them.
    full_code_lines = [rendered for rendered in logged if "'code'" in rendered]
    assert full_code_lines, "no log line carries the coupon code"

    for rendered in full_code_lines:
        for masking in ("[-4:]", "last4", "Last4", "sha256", "hexdigest", "mask", "redact",
                        "[:4]"):
            assert masking not in rendered, (
                f"a coupon code is being masked: {rendered}\n"
                "A coupon code is broadcast marketing material and is the correlation id this "
                "path has. Masking it is a loss, not a hardening.")


def test_the_coupon_code_is_the_correlation_id_and_no_phone_or_email_joins_it():
    """The reason the code may be logged in full is that it is NOT personal data. A log line
    that paired it with a phone number or an email would stop being safe."""
    for call in _logging_calls(TREE):
        rendered = ast.unparse(call)
        for personal in ("phone", "Phone", "email", "Email", "msisdn", "customerPhone"):
            assert personal not in rendered, f"line {call.lineno} logs {personal}"


# ── 61 ────────────────────────────────────────────────────────────────────────

def test_the_new_handlers_are_in_the_raw_scan_list():
    """Section 9: the gate is SPLIT rather than stretched, and the reason is load-bearing.

    Neither new handler has a payment-status decision - the coupon handler decides eligibility
    and the gift-card handler decides issuance - so adding them to `CONSULTING_FILES` would
    force an unused `payment_status` import purely to satisfy the import assertion. That makes
    the assertion mean less, and an import nobody uses is the first thing a later cleanup
    deletes, silently removing the file from the gate.
    """
    gate = ast.parse(VOCABULARY_GATE.read_text(encoding="utf-8"))
    assignment = next(
        (node for node in ast.walk(gate)
         if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == "RAW_SCAN_ONLY_FILES"
                 for target in node.targets)),
        None)
    assert assignment is not None, "RAW_SCAN_ONLY_FILES is not declared in the vocabulary gate"
    entries = ast.literal_eval(assignment.value)
    # Both, because nothing else pins these entries and the list is the only thing putting
    # those handlers under the raw-'captured' scan at all.
    for handler in ("ecommerce/coupons/handler.py", "ecommerce/gift-cards/handler.py"):
        assert (handler, None) in entries, f"{handler} is outside the raw-scan gate"


def test_the_coupon_handler_has_no_payment_status_decision_to_consult():
    """The premise of the split above, asserted independently so the xfail cannot hide it.

    This handler never compares a payment word, raw or canonical, because it has no payment
    decision: it issues coupons and answers eligibility. `captured` is AST-banned at decision
    points across the fleet, and this file would pass that scan today.
    """
    forbidden = {"captured"}
    offenders = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        literals = {operand.value for operand in operands
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str)}
        if literals & forbidden:
            offenders.append(f"line {node.lineno}: compares {sorted(literals & forbidden)} raw")
    assert not offenders, "\n  ".join(offenders)
    assert "payment_status" not in SOURCE, (
        "an unused payment_status import would make the gate's import assertion mean less")
