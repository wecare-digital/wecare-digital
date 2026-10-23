"""Offline tests for the Meta release-gate opener. No AWS: a mock Lambda client is injected.

Pins the two properties that make this tool safe:
  1. gate-state semantics match the handler (_TRUE/_FALSE; absent/typo dry-run => ON), and
  2. the write is a MERGE - every other env var survives and only DRY_RUN changes.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "open_meta_release_gate.py"


def _load():
    # Stub boto3 so import works without the SDK; tests inject their own client via _lambda.
    if "boto3" not in sys.modules:
        boto3 = types.ModuleType("boto3")
        boto3.client = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["boto3"] = boto3
    spec = importlib.util.spec_from_file_location("open_meta_release_gate", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeLambda:
    def __init__(self, env):
        self.env = dict(env)
        self.updated_with = None

    def get_function_configuration(self, FunctionName):
        return {"Environment": {"Variables": dict(self.env)}}

    def update_function_configuration(self, FunctionName, Environment):
        self.updated_with = Environment["Variables"]
        self.env = dict(Environment["Variables"])

    def get_waiter(self, name):
        return types.SimpleNamespace(wait=lambda **k: None)


def test_gate_state_matches_handler_token_sets():
    m = _load()
    assert m._gate_state({"META_CATALOG_SYNC_ENABLED": "true",
                          "META_CATALOG_SYNC_DRY_RUN": "true"}) == (True, True)
    assert m._gate_state({"META_CATALOG_SYNC_ENABLED": "true",
                          "META_CATALOG_SYNC_DRY_RUN": "false"}) == (True, False)
    # absent dry-run must read as ON (dry-run), the safe direction
    assert m._gate_state({"META_CATALOG_SYNC_ENABLED": "true"}) == (True, True)
    # a typo must leave dry-run ON
    assert m._gate_state({"META_CATALOG_SYNC_ENABLED": "true",
                          "META_CATALOG_SYNC_DRY_RUN": "flase"}) == (True, True)


def test_dry_run_default_writes_nothing(monkeypatch, capsys):
    m = _load()
    fake = FakeLambda({"META_CATALOG_SYNC_ENABLED": "true", "META_CATALOG_SYNC_DRY_RUN": "true",
                       "META_TOKEN_SECRET": "wecare/meta", "META_CATALOG_ID": "123"})
    monkeypatch.setattr(m, "_lambda", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["open_meta_release_gate.py"])  # no --apply
    assert m.main() == 0
    assert fake.updated_with is None  # nothing written


def test_apply_without_confirm_flag_is_refused(monkeypatch):
    m = _load()
    fake = FakeLambda({"META_CATALOG_SYNC_ENABLED": "true", "META_CATALOG_SYNC_DRY_RUN": "true"})
    monkeypatch.setattr(m, "_lambda", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["open_meta_release_gate.py", "--apply"])
    assert m.main() == 1
    assert fake.updated_with is None


def test_apply_with_confirm_merges_and_preserves_all_vars(monkeypatch):
    m = _load()
    live = {"META_CATALOG_SYNC_ENABLED": "true", "META_CATALOG_SYNC_DRY_RUN": "true",
            "META_TOKEN_SECRET": "wecare/meta-system-user-token", "META_CATALOG_ID": "1457",
            "META_TOKEN_FIELD": "access_token", "LOG_LEVEL": "INFO"}
    fake = FakeLambda(live)
    monkeypatch.setattr(m, "_lambda", lambda: fake)
    monkeypatch.setattr(sys, "argv", [
        "open_meta_release_gate.py", "--apply",
        "--i-understand-this-enables-production-catalog-writes"])
    assert m.main() == 0
    # only DRY_RUN changed; every other key is intact
    assert fake.updated_with["META_CATALOG_SYNC_DRY_RUN"] == "false"
    for k in ("META_TOKEN_SECRET", "META_CATALOG_ID", "META_TOKEN_FIELD", "LOG_LEVEL",
              "META_CATALOG_SYNC_ENABLED"):
        assert fake.updated_with[k] == live[k]
    assert set(fake.updated_with) == set(live)  # no var added or dropped


def test_refuses_to_open_when_not_enabled(monkeypatch):
    m = _load()
    fake = FakeLambda({"META_CATALOG_SYNC_ENABLED": "", "META_CATALOG_SYNC_DRY_RUN": "true"})
    monkeypatch.setattr(m, "_lambda", lambda: fake)
    monkeypatch.setattr(sys, "argv", [
        "open_meta_release_gate.py", "--apply",
        "--i-understand-this-enables-production-catalog-writes"])
    assert m.main() == 1
    assert fake.updated_with is None


def test_close_restores_safe_default(monkeypatch):
    m = _load()
    fake = FakeLambda({"META_CATALOG_SYNC_ENABLED": "true", "META_CATALOG_SYNC_DRY_RUN": "false",
                       "META_CATALOG_ID": "1457"})
    monkeypatch.setattr(m, "_lambda", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["open_meta_release_gate.py", "--close", "--apply"])
    assert m.main() == 0
    assert fake.updated_with["META_CATALOG_SYNC_DRY_RUN"] == "true"
    assert fake.updated_with["META_CATALOG_ID"] == "1457"
