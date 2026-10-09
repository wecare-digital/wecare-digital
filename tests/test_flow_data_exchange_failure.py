"""Two Flow gaps carried over as MEDIUM from the Phase 4c audit.

1. `whatsapp-business-api._save_flow_submission` was a FOURTH writer into
   FlowSubmissionTable with no duplicate guard - a bare put_item with a random
   submissionId, so every call made a new row. `lambda_utils/flow_completion`
   exists to prevent exactly that: one duplicated paid submit_request completion
   previously produced 2 submissions, 2 invoices and 2 payment links sent to the
   customer. The task was to check reachability first; it had zero callers, so it
   is removed rather than guarded.

2. `_handle_flow_data` returned HTTP 200 on a routing exception, and put the raw
   exception text into the payload the handset renders.

These are source-level assertions on purpose. `_handle_flow_data` is the
decrypt -> route -> encrypt wrapper for an E2E-encrypted endpoint; exercising it
end to end needs an RSA keypair and a Meta-shaped envelope, which would test the
crypto rather than the two properties that regressed.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WBA = ROOT / "amplify" / "functions" / "messaging" / "whatsapp-business-api" / "handler.py"
FLOWS_COMMON = ROOT / "amplify" / "functions" / "messaging" / "whatsapp-business-api" / "flows" / "common.py"


def source() -> str:
    return WBA.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. The unguarded fourth writer
# ---------------------------------------------------------------------------

def test_the_unguarded_fourth_writer_is_gone():
    text = source()
    assert "def _save_flow_submission(" not in text
    # The explanatory comment must survive, so the next person does not helpfully
    # reinstate it.
    assert "_save_flow_submission REMOVED" in text


def test_it_is_not_referenced_anywhere_in_the_function_tree():
    """Including dynamically. A dead writer that something still calls is not dead.

    Parsed with ast rather than grepped. A line-based scan cannot tell code from
    prose, and it flagged flow_completion's own audit table - which names the
    function precisely because it is documenting the problem.
    """
    import ast

    hits = []
    for path in (ROOT / "amplify").rglob("*.py"):
        # `amplify/node_modules` is untracked vendored code (aws-cdk-lib custom-resource
        # handlers). Parsing it cannot tell us anything about OUR call graph, and a
        # vendored reference to this name would make a dependency able to fail the gate.
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A string literal could be a getattr target. Only flag exact
                # matches, so a docstring mentioning it in a sentence is ignored.
                name = node.value.strip() if node.value.strip() == "_save_flow_submission" else None
            if name == "_save_flow_submission":
                hits.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}")
    assert hits == [], "live reference to the removed writer: " + ", ".join(hits)


def test_the_guarded_writer_the_live_flows_use_is_untouched():
    """The nine live flows go through common.save_flow_submission, which claims first."""
    text = FLOWS_COMMON.read_text(encoding="utf-8")
    assert "def save_flow_submission(" in text
    assert "flow_completion" in text
    assert "claim_completion" in text


# ---------------------------------------------------------------------------
# 2. The routing failure
# ---------------------------------------------------------------------------

def test_the_exception_text_no_longer_reaches_the_handset():
    """`data.error` is rendered on the customer's phone.

    An internal Python message there is both bad UX and an information disclosure
    to anyone who can open the flow. The detail belongs in the log line, keyed by
    requestId.
    """
    text = source()
    assert "f'Flow routing failed: {str(e)}'" not in text
    assert 'f"Flow routing failed: {str(e)}"' not in text


def test_the_handset_gets_a_stable_code_instead():
    text = source()
    assert "FLOW_ROUTING_FAILED" in text
    assert "FLOW_NO_RESPONSE" in text
    # A generic apology is the right customer-facing string; the code carries the
    # meaning for anything that needs to branch.
    assert "Something went wrong. Please try again." in text


def test_a_failed_route_is_logged_as_a_failure_not_as_a_response():
    """It used to fall through into `flow_response_full` at info level.

    So a dropped submission looked like an ordinary exchange to anyone reading
    logs, which is the property that made this gap survive an audit.
    """
    text = source()
    assert "flow_data_exchange_failed_returning_200" in text
    assert "flow_no_response_payload" in text


def test_the_empty_payload_path_also_marks_failure():
    """`if not response_payload` was silent - no log at all, just an error body."""
    text = source()
    index = text.index("if not response_payload:")
    window = text[index:index + 600]
    assert "routing_failed = True" in window


def test_the_status_code_question_is_recorded_not_silently_left():
    """The part deliberately NOT changed, and why.

    Returning 200 on failure may mean Meta never retries, losing the submission.
    Changing it is a live behaviour change on an encrypted customer-facing
    endpoint and Meta's data_exchange retry semantics are not documented clearly
    enough to act on. That is a reason to record the open question, not a reason
    to guess - and not a reason to let it drop off the list either.
    """
    text = source()
    assert "STILL OPEN" in text
    assert "retry semantics" in text
    # And the note must say the retry-safety precondition is already met, so
    # whoever settles it knows the hard part is done.
    assert "claim_completion" in text
