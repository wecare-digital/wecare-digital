"""`scripts/aws_cost_model.py` is deterministic over the committed Cost Explorer evidence."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aws_cost_model.py"
EVIDENCE = ROOT / "docs" / "migrations" / "evidence" / "cost-explorer-20261014.json"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("cost_model_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cost_model_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def measured(mod):
    return mod.measured(json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_measured_totals_match_the_cost_explorer_readings(measured):
    assert measured["gross_total"]["2026-09"] == pytest.approx(101.30, abs=0.02)
    assert measured["credits"]["2026-09"] == pytest.approx(-101.30, abs=0.02)
    assert measured["oct_days"] == 14


def test_support_is_not_scaled_but_usage_is(measured):
    rr = measured["oct_run_rate_by_service"]
    assert rr["AWS Business Support+"] == pytest.approx(29.00)
    assert measured["amplify_build_usd"]["2026-10_run_rate"] == pytest.approx(
        20.90 * 31 / 14, abs=0.02)


def test_labels_keep_potential_separate_from_realised(mod, measured):
    levers = {lv.name: lv for lv in mod.levers(dict(mod.RECORDED), measured)}
    assert levers["secrets_deleted"].label == "REALISED"
    assert levers["secrets_deleted"].monthly_delta == pytest.approx(-1.20)
    assert levers["cost_explorer_calls"].label == "HISTORICAL"
    assert levers["cost_explorer_calls"].monthly_delta == 0.0
    assert levers["lightsail_nano"].label == "POTENTIAL"
    assert levers["lightsail_nano"].monthly_delta == pytest.approx(-2.0)


def test_snapshot_cost_uses_billed_size_not_disk_size(mod, measured):
    levers = {lv.name: lv for lv in mod.levers(dict(mod.RECORDED), measured)}
    assert any("$0.27/mo" in n for n in levers["lightsail_nano"].notes)


def test_payback(mod):
    assert mod.payback_months(5.0, 2.0) == 2.5
    assert mod.payback_months(5.0, 0.0) is None


def test_main_writes_a_json_artifact_without_aws(mod, tmp_path, capsys):
    out = tmp_path / "model.json"
    assert mod.main(["--json", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["counts"]["active_secrets"] == 19
    assert "credits" in capsys.readouterr().out
