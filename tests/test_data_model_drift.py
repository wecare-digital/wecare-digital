"""The declared data model must not drift from the live tables again.

`amplify/data/resource.ts` reads like infrastructure and is a document: 58 models
declared, 0 AppSync APIs, 77 live tables provisioned by an entirely different
path. The failure mode is silent in both directions — a model for a table that
does not exist, and a live table nobody declared — and it had accumulated six of
the first kind before anything measured it.

These tests pin the reconciliation script itself, because a drift gate that is
wrong is worse than no gate: it either cries wolf until someone disables it, or
it passes while the two sides disagree.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_data_model_drift.py"
RESOURCE_TS = ROOT / "amplify" / "data" / "resource.ts"
SNAPSHOT = ROOT / "docs" / "execution" / "snapshots" / "dynamodb-tables.json"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--offline", *args],
        capture_output=True, text=True, cwd=ROOT,
    )


@pytest.fixture(scope="module")
def report() -> dict:
    proc = run_script("--json")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_snapshot_exists_so_the_gate_runs_without_aws():
    """CI has no AWS credentials, so the gate must work from the snapshot."""
    assert SNAPSHOT.exists()
    data = json.loads(SNAPSHOT.read_text())
    assert data["count"] == len(data["tables"])
    assert data["count"] > 50, "a truncated snapshot would pass the gate vacuously"


def test_gate_passes_on_the_current_tree():
    proc = run_script("--gate")
    assert proc.returncode == 0, f"unexpected drift:\n{proc.stdout}\n{proc.stderr}"


def test_no_unexpected_disagreement_in_either_direction(report):
    assert report["phantom_models_unexpected"] == []
    assert report["undeclared_tables_unexpected"] == []


def test_the_removed_phantom_models_are_gone(report):
    """Each declared a table that does not exist in the account.

    They are listed individually rather than by count so that reintroducing one
    names itself in the failure. Any other phantom fails
    `test_no_unexpected_disagreement_in_either_direction` whatever it is called.
    """
    removed = {"SmsAws", "RcsMessages", "AdminActionLog", "ProviderDriftSnapshot"}
    text = RESOURCE_TS.read_text()
    for name in sorted(removed):
        # The name survives in a comment explaining the removal; what must not
        # come back is the declaration.
        assert f"\n  {name}: a\n" not in text, f"{name} was re-declared"
        assert name not in report["phantom_models"]


def test_rate_limit_tracker_is_not_reported_as_a_phantom(report):
    """The one that looks like a phantom and is not.

    Model `RateLimitTracker` lives on `stack-wecare-digital-RateLimitTable` — the
    physical name drops the "Tracker". Any rule-based guess reports it missing,
    which is exactly the false positive that made an earlier attempt at this
    check unusable.
    """
    assert "RateLimitTracker" not in report["phantom_models"]


def test_the_header_does_not_claim_to_be_deployed():
    """The file's own header is the first thing a reader trusts.

    It used to open with "41 Tables with PAY_PER_REQUEST billing mode", which was
    wrong about the count and wrong about being infrastructure at all.
    """
    head = RESOURCE_TS.read_text()[:4000]
    assert "41 Tables" not in head
    assert "AppSync GraphQL APIs        0" in head, \
        "the header must state that nothing here is materialised"


def test_ttl_config_has_no_entry_for_a_removed_model():
    """A TTL entry for a model with no table is a silent no-op.

    `backend.ts` guards on `if ( table )`, so four of its eight retention
    policies were configuring nothing while reading as though they were.
    """
    text = (ROOT / "amplify" / "backend.ts").read_text()
    block = text.split("const TTL_CONFIG", 1)[1].split("};", 1)[0]
    configured = set(re.findall(r"^  (\w+): '", block, re.M))
    declared = set(re.findall(r"^  ([A-Z][A-Za-z0-9]*): a$", RESOURCE_TS.read_text(), re.M))
    assert configured, "TTL_CONFIG parsed as empty; this test would pass vacuously"
    assert configured <= declared, f"TTL configured for undeclared models: {sorted(configured - declared)}"


def test_gate_fails_when_a_phantom_is_reintroduced(tmp_path, monkeypatch):
    """Prove the gate can fail. A gate never seen red is not known to work."""
    original = RESOURCE_TS.read_text()
    injected = original.replace(
        "const schema = a.schema( {",
        "const schema = a.schema( {\n  NotARealThing: a\n    .model( {\n"
        "      id: a.id().required(),\n    } ),\n",
        1,
    )
    assert injected != original
    RESOURCE_TS.write_text(injected)
    try:
        proc = run_script("--gate")
        assert proc.returncode == 1
        assert "NotARealThing" in proc.stderr
    finally:
        RESOURCE_TS.write_text(original)
