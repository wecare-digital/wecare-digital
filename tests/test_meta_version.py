"""The Meta Graph API version has exactly one source, and it validates.

Before this, `META_API_VERSION = 'v25.0'` was declared at module scope in **eleven**
handlers and embedded in **five** request URLs as a literal. Five of the eleven read the
environment with a hard-coded default; six ignored the environment entirely. So a version
bump was a sixteen-file edit in which six files would silently disregard the variable you
set -- and nothing failed if you missed one, because the old version keeps working right
up until Meta retires it.

The spec's own count was 7 and 3. It was 11 and 5. That is the reason this test asserts
the invariant rather than a number: a count in a document goes stale, a grep does not.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify/functions"
SHARED = FUNCTIONS / "shared"
SOURCE_MODULE = SHARED / "lambda_utils/meta_version.py"

sys.path.insert(0, str(SHARED))


def _python_files() -> list[pathlib.Path]:
    return sorted(p for p in FUNCTIONS.rglob("*.py") if "__pycache__" not in str(p))


# ── the single source ────────────────────────────────────────────────────────────

def test_the_source_module_exists_and_resolves():
    from lambda_utils.meta_version import GRAPH_BASE, META_API_VERSION, graph_url

    assert re.match(r"^v\d{1,3}\.\d$", META_API_VERSION), META_API_VERSION
    assert GRAPH_BASE == f"https://graph.facebook.com/{META_API_VERSION}"
    assert graph_url("1016149501586345", "messages") == \
        f"https://graph.facebook.com/{META_API_VERSION}/1016149501586345/messages"
    # Leading and trailing slashes on segments must not produce a doubled separator.
    assert "//" not in graph_url("/abc/", "/messages/").replace("https://", "")


@pytest.mark.parametrize("bad", ["v25", "25.0", "latest", "v25.0.1", "", "v.0", "vv25.0",
                                 "v25.00", "V25.0"])
def test_a_malformed_version_is_refused(bad, monkeypatch):
    """R1.2: fail at startup, not at request time.

    A bad value does not produce a useful error from Graph -- it produces a 400 about an
    unknown path, which reads like an application bug rather than a configuration one.
    """
    import importlib

    import lambda_utils.meta_version as mod

    monkeypatch.setenv("META_API_VERSION", bad)
    # `ValueError`, not `mod.MetaVersionError`. `pytest.raises` evaluates its argument
    # BEFORE the reload, so it captures the class object from the OLD module namespace --
    # and the reload re-executes the module body, defining a brand-new class with the
    # same name and raising that one. `except OldClass` does not catch `NewClass`, so the
    # test failed while the code under test was behaving exactly as intended.
    # MetaVersionError subclasses ValueError, which is a builtin and therefore stable
    # across reloads.
    with pytest.raises(ValueError) as caught:
        importlib.reload(mod)
    assert "META_API_VERSION" in str(caught.value)
    assert type(caught.value).__name__ == "MetaVersionError"

    # Leave the module in its normal state for every other test in the session.
    monkeypatch.delenv("META_API_VERSION", raising=False)
    importlib.reload(mod)


def test_a_well_formed_override_is_accepted(monkeypatch):
    import importlib

    import lambda_utils.meta_version as mod

    monkeypatch.setenv("META_API_VERSION", "v26.0")
    importlib.reload(mod)
    assert mod.META_API_VERSION == "v26.0"
    assert mod.GRAPH_BASE == "https://graph.facebook.com/v26.0"

    monkeypatch.delenv("META_API_VERSION", raising=False)
    importlib.reload(mod)


def test_is_valid_version_is_exposed_for_callers():
    from lambda_utils.meta_version import is_valid_version

    assert is_valid_version("v25.0")
    assert is_valid_version("  v25.0  ")
    assert not is_valid_version("v25")
    assert not is_valid_version(None)


# ── nothing else may declare it ──────────────────────────────────────────────────

def test_no_handler_declares_its_own_version():
    """R1.1. A local declaration silently shadows the shared one."""
    declaration = re.compile(r"^\s*META_API_VERSION\s*=", re.M)
    offenders = []
    for path in _python_files():
        if path == SOURCE_MODULE:
            continue
        text = path.read_text()
        for match in declaration.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "these files declare META_API_VERSION locally instead of importing it from "
        "lambda_utils.meta_version:\n  " + "\n  ".join(offenders)
    )


def test_no_request_url_embeds_a_version_literal():
    """R1.1. The five that did were found only because someone grepped for them."""
    literal = re.compile(r"graph\.facebook\.com/v\d")
    offenders = []
    for path in _python_files():
        if path == SOURCE_MODULE:
            continue
        text = path.read_text()
        for match in literal.finditer(text):
            line = text[: match.start()].count("\n") + 1
            snippet = text.splitlines()[line - 1].strip()
            offenders.append(f"{path.relative_to(ROOT)}:{line}  {snippet[:100]}")
    assert not offenders, (
        "these URLs hard-code the Graph version. Interpolate META_API_VERSION or use "
        "graph_url():\n  " + "\n  ".join(offenders)
    )


def test_the_shared_meta_client_uses_the_shared_source():
    text = (SHARED / "lambda_utils/meta_client.py").read_text()
    assert "from lambda_utils.meta_version import" in text
    assert "os.environ.get('META_API_VERSION'" not in text, (
        "meta_client.py went back to reading the environment itself, which makes it a "
        "second opinion about the version"
    )


# ── the Python source and the JSON source must agree ────────────────────────────

def test_python_and_vendor_versions_json_agree():
    """`config/vendor-versions.json` drives the TypeScript side; this module drives the
    Python side. Neither reads the other at runtime -- a Lambda should not read a repo
    file to learn its own configuration -- so a test is what stops them drifting.
    """
    from lambda_utils.meta_version import GRAPH_BASE, META_API_VERSION

    vendor = json.loads((ROOT / "config/vendor-versions.json").read_text())
    assert vendor["metaGraphApiVersion"] == META_API_VERSION, (
        f"config/vendor-versions.json says {vendor['metaGraphApiVersion']}, "
        f"lambda_utils.meta_version says {META_API_VERSION}"
    )
    assert vendor["metaGraphApiBase"] == GRAPH_BASE


# ── every consumer still resolves the symbol ─────────────────────────────────────

def test_every_consumer_imports_what_it_uses():
    """A file that USES META_API_VERSION must import it.

    The rewrite replaced declarations with imports; this catches the case where a file
    uses the symbol and got neither.
    """
    missing = []
    for path in _python_files():
        if path == SOURCE_MODULE:
            continue
        text = path.read_text()
        uses = re.search(r"\bMETA_API_VERSION\b", text)
        if not uses:
            continue
        if "from lambda_utils.meta_version import" in text:
            continue
        # A test fixture or a comment mentioning the name is not a use.
        code_lines = [l for l in text.splitlines()
                      if "META_API_VERSION" in l and not l.strip().startswith("#")]
        if code_lines:
            missing.append(f"{path.relative_to(ROOT)}: {code_lines[0].strip()[:90]}")
    assert not missing, (
        "these files use META_API_VERSION without importing it:\n  " + "\n  ".join(missing)
    )


def test_the_packaged_layer_carries_the_module():
    """Every deploy zip embeds `lambda_utils/`, so the module ships with each function.

    Asserted because the failure mode is an ImportError at cold start in production,
    which the local suite cannot see: the module is importable here from the source tree
    whether or not the packager includes it.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/deploy_all_lambdas.py"), "--list"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr[-400:]
    assert SOURCE_MODULE.exists()
    assert SOURCE_MODULE.parent.name == "lambda_utils", (
        "the module must live inside lambda_utils/, which is what the packager embeds"
    )
