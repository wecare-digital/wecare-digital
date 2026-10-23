from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_whatsapp_catalog_payment_gate.py"


def _module():
    spec = importlib.util.spec_from_file_location("catalog_gate_reconciler", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_targets_are_exactly_the_two_catalog_payment_runtime_owners():
    m = _module()
    assert m.TARGETS == ("wecare-inbound-whatsapp", "wecare-checkout")
    assert m.FLAG == "WA_CATALOG_ORDERS_ENABLED"
    assert m.VALUE == "true"


def test_reconcile_preserves_unrelated_environment_and_uses_revision_lease():
    m = _module()
    lam = MagicMock()
    lam.get_function_configuration.side_effect = [
        {"RevisionId": "r1", "Environment": {"Variables": {"KEEP": "yes"}}},
        {"Environment": {"Variables": {"KEEP": "yes", m.FLAG: "true"}}},
    ]
    result = m.reconcile(lam, "wecare-checkout", dry_run=False)
    assert result == f"set {m.FLAG}=true"
    lam.update_function_configuration.assert_called_once_with(
        FunctionName="wecare-checkout",
        RevisionId="r1",
        Environment={"Variables": {"KEEP": "yes", m.FLAG: "true"}},
    )


def test_dry_run_never_mutates_aws():
    m = _module()
    lam = MagicMock()
    lam.get_function_configuration.return_value = {
        "RevisionId": "r1", "Environment": {"Variables": {}}
    }
    assert "would set" in m.reconcile(lam, "wecare-inbound-whatsapp", dry_run=True)
    lam.update_function_configuration.assert_not_called()
