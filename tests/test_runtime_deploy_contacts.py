"""Contacts must be part of the production runtime deploy workflow.

A contacts-handler change can alter customer identity/consent projection used by the workspace.
If the path trigger or deploy list omits it, code can merge cleanly while the live alias stays stale.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/runtime-deploy.yml"


def test_runtime_deploy_covers_contacts_source_and_live_function():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "amplify/functions/core/contacts/**" in source
    assert "amplify/functions/core/contacts/handler.py" in source
    assert source.count("wecare-contacts") >= 3
