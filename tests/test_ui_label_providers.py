"""The UI label gate's provider rule is positive: a provider named on screen is approved.

`scripts/check_ui_labels.py` reads display names from `scripts/provider_allowlist.py`, the
same allow-list the source and live provider gates use. It carries no list of names that
must not appear and no "historical" exemption, so these tests inject an invented provider,
`Acme`, in every shape that puts a provider in front of a user and expect each to fail -
and expect the approved shapes the product really uses to pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_ui_labels as ui  # noqa: E402
import provider_allowlist  # noqa: E402


def _findings(snippet: str):
    return [shown for _offset, _rule, shown in
            ui.provider_name_findings(ui.strip_noise(snippet))]


def test_the_gate_passes_on_the_current_tree(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_ui_labels.py", "--gate"])
    assert ui.main() == 0, capsys.readouterr().out


def test_display_names_come_from_the_provider_allowlist():
    assert ui.APPROVED_LABELS == provider_allowlist.ui_labels()
    assert ui.APPROVED_IDS == provider_allowlist.provider_ids()
    assert not hasattr(ui, "HISTORICAL_MARKERS"), "the historical exemption is gone"
    assert "retired_provider" not in ui.PATTERNS, "no list of forbidden names"


@pytest.mark.parametrize("snippet, shown", [
    ("<p>Delivered via Acme Telecom with DLT templates.</p>", "Acme Telecom"),
    ("<p>Payments powered by Acme Pay.</p>", "Acme Pay"),
    ('<Row provider="Acme" />', "Acme"),
    ("<Row provider={'Acme'} />", "Acme"),
    ("const row = { provider: 'acme', at: 1 };", "acme"),
    ("<p>SMS: AWS Legacy + Acme IQ</p>", "Acme IQ"),
    ("const PROVIDER_LABELS = { acme: 'Acme' };", "Acme"),
])
def test_an_unapproved_provider_name_fails_in_every_shape(snippet, shown):
    assert shown in _findings(snippet), _findings(snippet)


def test_a_historical_label_is_not_an_exemption():
    """Data recorded under a provider that is no longer used is shown through the product
    vocabulary; naming the provider with a marker beside it still names it."""
    assert _findings('<Row provider="Acme (historical)" />') == ["Acme (historical)"]
    assert _findings("const CARRIER_NAMES = { acme: 'Acme (legacy)' };") == ["Acme (legacy)"]


def test_a_stack_joined_with_an_approved_provider_is_checked_part_by_part():
    assert set(_findings("<p>AWS Legacy + Acme IQ</p>")) == {"AWS Legacy", "Acme IQ"}
    assert _findings("<p>Invoices & WhatsApp Pay</p>") == [], "a title, not a stack"


@pytest.mark.parametrize("snippet", [
    "<p>Sent via WhatsApp Business API, powered by Razorpay.</p>",
    "<p>Subscribe via RSS, or sign in via Google.</p>",
    "<p>Calls are carried by Plivo and messages delivered by AWS End User Messaging.</p>",
    "<p>Handled by YOUR rules.</p><p>Sent via Meta Graph API v25.0</p>",
    "const p = { provider: 'meta-social' };",
    '"provider": { "@id": "https://wecare.digital/#organization" }',
    "<p>Razorpay Integration via Razorpay Checkout</p>",
    "// Delivered via Acme Telecom - a comment records history, it is not UI",
])
def test_approved_names_and_prose_pass(snippet):
    assert _findings(snippet) == []


def test_an_injected_screen_fails_the_gate(tmp_path, monkeypatch, capsys):
    screen = tmp_path / "Injected.tsx"
    screen.write_text("export const Card = () => <p>Delivered via Acme Telecom</p>;\n",
                      encoding="utf-8")
    monkeypatch.setattr(ui, "relevant_files",
                        lambda: iter([("src/components/Injected.tsx", screen)]))
    violations = ui.scan()
    assert [(v["rule"], v["match"], v["severity"]) for v in violations] == [
        ("provider_label", "Acme Telecom", "high")]
    monkeypatch.setattr(sys, "argv", ["check_ui_labels.py", "--gate"])
    assert ui.main() == 1
    assert "GATE FAILED" in capsys.readouterr().out
