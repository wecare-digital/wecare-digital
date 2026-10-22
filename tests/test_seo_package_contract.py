"""The SEO CI deployment must ship every dependency used by blog ingestion.

The offline package builder is also used by the operational deploy script. Keeping
CI on that builder prevents a green deploy from silently dropping importable code.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from scripts.deploy_seo_tools import package


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/seo-tools-deploy.yml"


def test_seo_package_contains_runtime_blog_ingest_dependencies():
    with zipfile.ZipFile(io.BytesIO(package())) as archive:
        names = set(archive.namelist())
    assert {
        "seo_tools_handler.py",
        "blog_pipeline.py",
        "blog_quality_v2.py",
        "pypdf/__init__.py",
        "content/conversations/corpus-index.json",
        "operations/seo-tools/blog_queue.py",
        "operations/seo-tools/blog_sources.py",
    } <= names


def test_seo_ci_deploy_uses_complete_shared_package_builder():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # The old hand-rolled zip omitted blog_pipeline, blog_quality_v2 and pypdf.
    assert "from scripts.deploy_seo_tools import package" in workflow
    assert "write_bytes(package())" in workflow


def test_seo_ci_deploy_package_step_closes_python_heredoc():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Package SEO tools Lambda", 1)[1].split(
        "      - name: Configure AWS credentials", 1
    )[0]
    assert step.splitlines().count("          PY") == 1, (
        "Unclosed heredoc prevents the deployment package from being built"
    )


def test_seo_ci_deploy_installs_pinned_packaging_dependencies():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    deploy_setup = workflow.split("\n  deploy:", 1)[1].split(
        "      - name: Package SEO tools Lambda", 1
    )[0]
    assert "python -m pip install --disable-pip-version-check boto3 pypdf==6.21.1" in deploy_setup, (
        "The deploy job runs on a fresh runner; test-job dependencies are not inherited"
    )
