"""A rendering defect is HIGH when a customer can receive it, and only then.

WHY THIS TEST EXISTS. `scripts/rcs_template_sync.py --check` exits non-zero on any HIGH
finding. Until 2026-09-28 every rendering defect was flat HIGH, and one of them sat on
`get_started` — a template **no code path sends**, whose senders never existed. So the
gate returned 1 permanently, was wired into no workflow, and guarded nothing. The repo
already documents this failure mode for CodeQL in `tests/test_log_phone_masking.py`: a
check that fires on the safe majority trains people to ignore it.

Severity is now derived from reachability. The risk this creates is obvious and is what
these tests exist to prevent: reachability must not become a way to silence a defect that
actually matters. So the escalation direction is asserted as hard as the relaxation —
flipping a template to referenced must restore HIGH, and `rcsmenu`, the one template code
does send, must never be de-escalated.

No AWS or Sinch call is made. `validate()` is a pure function over exported rows.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rcs" / "templates" / "manifest.json"


@pytest.fixture(scope="module")
def sync():
    path = ROOT / "scripts" / "rcs_template_sync.py"
    spec = importlib.util.spec_from_file_location("_rcs_sync", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_rcs_sync"] = module
    spec.loader.exec_module(module)
    return module


def _row(**overrides) -> dict:
    """A minimal normalized row; validate() reads only these keys."""
    row = {
        "name": "t", "type": "rich_card", "status": "approved", "isRichCard": True,
        "cardOrientation": "VERTICAL", "mediaHeight": "MEDIUM", "mediaExtension": "png",
        "hasTrailingBackticks": False, "variableSyntax": "none", "actions": [],
        "referencedByCode": False, "documentedOnly": False,
    }
    row.update(overrides)
    return row


def _find(findings, needle):
    return [f for f in findings if needle in f["finding"]]


def test_unreachable_rendering_defect_is_medium_not_high(sync):
    findings = sync.validate([_row(cardOrientation="HORIZONTAL", mediaHeight="TALL")])
    hit = _find(findings, "HORIZONTAL card orientation")
    assert hit, "the defect must still be reported"
    assert hit[0]["severity"] == "MEDIUM"
    assert "cannot reach a customer" in hit[0]["reachability"]


def test_reachable_rendering_defect_escalates_to_high(sync):
    findings = sync.validate([
        _row(cardOrientation="HORIZONTAL", mediaHeight="TALL", referencedByCode=True)
    ])
    hit = _find(findings, "HORIZONTAL card orientation")
    assert hit[0]["severity"] == "HIGH", (
        "a defect a customer can receive must block; reachability must not silence it"
    )
    assert "can receive" in hit[0]["reachability"]


def test_mixed_placeholder_syntax_follows_the_same_rule(sync):
    unreachable = sync.validate([_row(variableSyntax="MIXED")])
    reachable = sync.validate([_row(variableSyntax="MIXED", referencedByCode=True)])
    assert _find(unreachable, "two placeholder syntaxes")[0]["severity"] == "MEDIUM"
    assert _find(reachable, "two placeholder syntaxes")[0]["severity"] == "HIGH"


def test_defect_is_never_dropped_only_reweighted(sync):
    """De-escalation must not mean disappearance."""
    findings = sync.validate([_row(cardOrientation="HORIZONTAL", mediaHeight="TALL")])
    hit = _find(findings, "HORIZONTAL card orientation")[0]
    assert hit["consequence"], "consequence text must survive de-escalation"
    assert hit["action"], "remediation text must survive de-escalation"
    assert hit["needsProviderReadback"] is True


def test_documented_only_is_not_treated_as_reachable(sync):
    """Their senders were deleted on 2026-09-19, so they cannot be sent."""
    findings = sync.validate([
        _row(cardOrientation="HORIZONTAL", mediaHeight="TALL", documentedOnly=True)
    ])
    assert _find(findings, "HORIZONTAL")[0]["severity"] == "MEDIUM"


def test_the_committed_export_has_no_high_finding(sync):
    """This is what makes the CI gate meaningful rather than permanently red."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    findings = sync.validate(manifest["templates"])
    high = [f for f in findings if f["severity"] == "HIGH"]
    assert not high, f"HIGH findings would fail the provider allow-list workflow: {high}"


def test_the_one_referenced_template_is_still_covered(sync):
    """`rcsmenu` is the only template any code sends; it must never be de-escalated."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    referenced = [r for r in manifest["templates"] if r.get("referencedByCode")]
    assert [r["name"] for r in referenced] == ["rcsmenu"], (
        "the referenced set changed; re-check which templates the gate now covers"
    )
    assert sync._reachable(referenced[0]) is True
