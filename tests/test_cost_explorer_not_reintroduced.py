"""Cost Explorer was removed on 2026-09-28. This test is what stops it coming back.

The removal had three halves, and only two of them are durable on their own:

  THE CODE went first - `operations/billing/handler.py` dropped its three `ce` calls and
  now reports AWS Health and Support/Trusted Advisor only. Its module docstring records
  the measurement: the CE API bills $0.01 per request, the function made three calls per
  invocation and was invoked 504 times in September 2026, which accounts for effectively
  the entire $14.97/month charge.

  THE IAM GRANT went second, and that is the stronger guard - `amplify/iam-policies.ts`
  withholds `ce:*` from the `billing` policy, so a reintroduced call fails with
  AccessDenied rather than quietly re-establishing a per-request bill.

  WHAT NEITHER COVERS is a new call site in a function whose role happens to hold a
  wildcard, or a CE client added in a script run with developer credentials. Neither
  fails closed. That is the gap this test fills, and it is the reason the gate is on the
  source tree rather than on one file.

The Python assertions use `ast`, not grep, for the same reason the payment vocabulary gate
does: the files that explain why Cost Explorer must not return necessarily name the thing
they forbid. `billing/handler.py` says "Do NOT reintroduce a boto3 'ce' client here" in its
docstring, and a textual search would flag its own explanation.

Deliberately NOT covered, so the scope is readable rather than guessed at:

  * `docs/execution/snapshots/` holds historical IAM snapshots that contain `ce:` on
    purpose, as the rollback evidence for the removal. Excluded by path.
  * Prose anywhere - docs, comments, docstrings, change-authority entries. Cost Explorer
    has to stay discussable or the reasoning above cannot be written down.
  * The AWS account itself. A prior read-only audit confirmed zero live CE calls and zero
    `ce:` grants; this gate is about the tree, which is what CI can actually see.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The trees that can actually invoke AWS. Everything else in the repo is prose or config.
SOURCE_TREES = [ROOT / "amplify", ROOT / "src", ROOT / "scripts"]

#: Historical IAM snapshots contain `ce:` deliberately - they are the rollback evidence for
#: the 2026-09-28 removal. Excluded explicitly even though it sits outside the trees above,
#: so that widening the scan later cannot silently start failing on its own audit trail.
EXCLUDED_PATHS = [ROOT / "docs" / "execution" / "snapshots"]

#: Directory names that are never our source.
EXCLUDED_DIR_NAMES = {
    "node_modules", "__pycache__", ".next", ".venv", "venv", "out", "dist", "build",
    ".pytest_cache", ".mypy_cache", "coverage", "site-packages",
}

#: The Cost Explorer service name as boto3 spells it.
CE_SERVICE_NAME = "ce"

#: Cost Explorer operations. An operation name appearing as a string literal in code means
#: someone is calling CE, whether through a client, a paginator, or a hand-signed request.
CE_OPERATIONS = frozenset({
    "GetCostAndUsage",
    "GetCostForecast",
    "GetCostAndUsageWithResources",
    "GetDimensionValues",
    "GetReservationUtilization",
    "GetSavingsPlansUtilization",
    "GetAnomalies",
    "GetCostCategories",
})

#: The JS/TS spellings. All three are import- or constructor-level, so none of them has any
#: reason to appear in prose - unlike `ce:`, which the IAM policy's do-not-re-add comment
#: legitimately names. Comments are stripped before matching anyway (see `_strip_js_comments`),
#: so that comment stays safe even if it is ever reworded to quote one of these.
JS_PATTERNS = [
    "@aws-sdk/client-cost-explorer",
    "CostExplorerClient",
    "new CostExplorer(",
]

PY_SUFFIXES = {".py"}
JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _is_excluded(path: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
        return True
    return any(excluded in path.parents for excluded in EXCLUDED_PATHS)


def _source_files(suffixes: set[str]) -> list[Path]:
    found: list[Path] = []
    for tree in SOURCE_TREES:
        if not tree.is_dir():
            continue
        for path in tree.rglob("*"):
            if path.suffix in suffixes and path.is_file() and not _is_excluded(path):
                found.append(path)
    return sorted(found)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ── Python: AST, so a docstring forbidding Cost Explorer does not trip the gate ───────

def _is_client_call(node: ast.Call) -> bool:
    """`boto3.client(...)`, `<session>.client(...)` or a bare imported `client(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "client"
    return isinstance(func, ast.Name) and func.id == "client"


def _names_ce_service(node: ast.Call) -> bool:
    """True when the first positional arg - or `service_name=` - is the literal 'ce'."""
    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == CE_SERVICE_NAME:
            return True
    for keyword in node.keywords:
        if keyword.arg == "service_name":
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value == CE_SERVICE_NAME:
                return True
    return False


def _ce_offenders_in_python(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - a file we cannot parse is not a finding
        return [f"{_rel(path)}: could not be parsed ({exc.msg} at line {exc.lineno})"]

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_client_call(node) and _names_ce_service(node):
            offenders.append(
                f"{_rel(path)}:{node.lineno}: constructs a boto3 client for "
                f"{CE_SERVICE_NAME!r} (Cost Explorer)")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in CE_OPERATIONS:
                offenders.append(
                    f"{_rel(path)}:{node.lineno}: names the Cost Explorer operation "
                    f"{node.value!r}")
    return offenders


def test_no_python_source_constructs_a_cost_explorer_client_or_names_an_operation():
    """One finding fails the build, and the message names every one of them.

    Aggregated rather than parametrized per file because the file list is discovered: a new
    handler must be covered the moment it lands, without anyone remembering to add it here.
    """
    files = _source_files(PY_SUFFIXES)
    assert files, "found no Python sources - the tree layout moved and this gate went blind"

    offenders = [o for path in files for o in _ce_offenders_in_python(path)]

    assert not offenders, (
        "Cost Explorer has been reintroduced:\n  " + "\n  ".join(offenders)
        + "\n\nThe CE API bills $0.01 per request and this is how a $14.97/month charge got "
          "here the first time. `amplify/iam-policies.ts` withholds `ce:*` from the billing "
          "role, so the call will also fail with AccessDenied. If programmatic cost data is "
          "genuinely needed, export the Cost and Usage Report to S3 and query that - CUR "
          "delivery is free and Athena bills per byte scanned, not per question asked."
    )


# ── JS/TS: text, but only on spellings that cannot occur in prose ─────────────────────

_JS_TOKENS = re.compile(r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|//[^\n]*|/\*.*?\*/|.)""",
                        re.DOTALL)


def _strip_js_comments(source: str) -> str:
    """Blank out `//` and `/* */` comments while leaving string and template literals intact.

    Scans token-wise rather than regex-replacing, because a naive `//.*$` eats the rest of
    any line containing a URL - and `https://` appears all over this frontend. Newlines are
    preserved so reported line numbers stay true to the file.
    """
    out: list[str] = []
    for match in _JS_TOKENS.finditer(source):
        token = match.group(0)
        if token.startswith("//") or token.startswith("/*"):
            out.append("\n" * token.count("\n"))
        else:
            out.append(token)
    return "".join(out)


def _ce_offenders_in_js(path: Path) -> list[str]:
    code = _strip_js_comments(path.read_text(encoding="utf-8", errors="replace"))
    offenders: list[str] = []
    for lineno, line in enumerate(code.splitlines(), start=1):
        for pattern in JS_PATTERNS:
            if pattern in line:
                offenders.append(f"{_rel(path)}:{lineno}: references {pattern!r}")
    return offenders


def test_no_frontend_or_iac_source_imports_the_cost_explorer_sdk_client():
    files = _source_files(JS_SUFFIXES)
    assert files, "found no JS/TS sources - the tree layout moved and this gate went blind"

    offenders = [o for path in files for o in _ce_offenders_in_js(path)]

    assert not offenders, (
        "a Cost Explorer SDK client has been reintroduced:\n  " + "\n  ".join(offenders)
        + "\n\nCost Explorer was removed on 2026-09-28 because every request is billable. "
          "Read spend from the AWS Billing console, or from a Cost and Usage Report in S3."
    )


# ── the gate is pointed at the right tree, and it can actually see a violation ────────

def test_the_billing_handler_is_in_scope_and_is_clean():
    """The one file this is really about. If the scan ever stops reaching it, say so loudly."""
    handler = ROOT / "amplify" / "functions" / "operations" / "billing" / "handler.py"
    assert handler in _source_files(PY_SUFFIXES), (
        "the billing handler is no longer covered by this gate - it is the function that "
        "produced the original charge")
    assert _ce_offenders_in_python(handler) == []


def test_the_detection_would_actually_fire():
    """A guard that cannot detect anything passes forever and protects nothing.

    Exercised against source held in this test rather than against a file planted in the
    tree, which is the whole point: a detection-trigger file in `amplify/` would be a real
    violation of the thing being guarded.
    """
    cases = [
        "import boto3\nce = boto3.client('ce')\n",
        "ce = session.client('ce')\n",
        "from boto3 import client\nce = client('ce')\n",
        "ce = boto3.client(service_name='ce')\n",
        "resp = ce.get_paginator('GetCostAndUsage')\n",
        "op = 'GetSavingsPlansUtilization'\n",
    ]
    for source in cases:
        tree = ast.parse(source)
        hit = any(
            (isinstance(n, ast.Call) and _is_client_call(n) and _names_ce_service(n))
            or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value in CE_OPERATIONS)
            for n in ast.walk(tree))
        assert hit, f"detection missed: {source!r}"

    # And it must not fire on the neighbouring services this account really uses, or the
    # gate becomes noise - a noisy gate gets switched off, and a switched-off gate protects
    # nothing.
    for benign in ("boto3.client('health')", "boto3.client('support')",
                   "boto3.client('cloudwatch')", "x = 'GetCostAndUsageReport'",
                   "boto3.resource('ce')", "obj.describe('ce')"):
        tree = ast.parse(benign)
        hit = any(
            (isinstance(n, ast.Call) and _is_client_call(n) and _names_ce_service(n))
            or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value in CE_OPERATIONS)
            for n in ast.walk(tree))
        assert not hit, f"false positive on {benign!r}"


def test_the_do_not_re_add_comment_in_the_iam_policy_is_not_a_violation():
    """The durable half of the removal is a withheld IAM grant, documented in a comment that
    necessarily names `ce:*`. That comment must never be what breaks the build - otherwise
    the next person deletes the explanation to get green, which is the worst outcome
    available. Pinned here so the asymmetry is executable rather than assumed.
    """
    policies = ROOT / "amplify" / "iam-policies.ts"
    text = policies.read_text(encoding="utf-8")
    assert "Do not add `ce:*` back here." in text, (
        "the do-not-re-add note has gone from the billing IAM policy; the withheld grant is "
        "what makes a reintroduced CE call fail closed")
    assert _ce_offenders_in_js(policies) == []


def test_the_snapshot_directory_is_excluded_on_purpose():
    """Historical IAM snapshots hold `ce:` as rollback evidence. Pinned so a later widening
    of the scan does not start failing on the audit trail for this very removal."""
    snapshots = ROOT / "docs" / "execution" / "snapshots"
    assert snapshots in EXCLUDED_PATHS
    assert _is_excluded(snapshots / "any-historical-policy.json")
