"""SEO CI must package the live Lambda runtime and use the shared package builder."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from scripts.deploy_seo_tools import package

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/seo-tools-deploy.yml"


def test_seo_package_contains_live_runtime():
    with zipfile.ZipFile(io.BytesIO(package())) as archive:
        names = set(archive.namelist())
    assert "seo_tools_handler.py" in names
    assert "operations/seo-tools/handler.py" in names
    assert "operations/seo-tools/storage.py" in names
    assert "operations/seo-tools/blog_source.py" in names
    assert "operations/seo-tools/blog_sources.py" not in names
    assert "operations/seo-tools/blog_production.py" not in names
    assert "operations/seo-tools/blog_draft.py" not in names


def test_seo_ci_deploy_uses_shared_package_builder():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "from scripts.deploy_seo_tools import package" in workflow
    assert "write_bytes(package())" in workflow


def test_seo_ci_deploy_package_step_closes_python_heredoc():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Package SEO tools Lambda", 1)[1].split(
        "      - name: Configure AWS credentials", 1
    )[0]
    assert step.splitlines().count("          PY") == 1


def test_seo_ci_deploy_has_only_required_packaging_dependency():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    deploy_setup = workflow.split("\n  deploy:", 1)[1].split(
        "      - name: Package SEO tools Lambda", 1
    )[0]
    assert "python -m pip install --disable-pip-version-check boto3" in deploy_setup
    assert "pypdf" not in deploy_setup
