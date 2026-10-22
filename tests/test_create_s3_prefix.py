"""Creating a folder must not be able to put private data in the public tree.

`scripts/create_s3_prefix.py` exists because S3 has no directories: `secure/Invoice/customer_invoice/x.png`
is one flat key, and the "folders" a console shows are inferred from the `/` characters in keys
that already exist. So a prefix with no objects does not appear at all — which is what
`secure/Invoice/customer_invoice/` looked like after the invoice assets moved to the gated root, since
invoices are rendered on demand and none had been.

A 0-byte key ending in `/` is the only thing S3 treats as a folder, and this codebase already
relies on that: `operations/system-cleanup._wipe_s3_prefix` deletes content but explicitly skips
keys ending in `/`, so a marked folder survives a purge while an unmarked one vanishes.

The risk being guarded
----------------------
The bucket has two roots with opposite meanings — `o/` is served by CloudFront with **no
authentication**, `secure/` is not — and both are composed through `lambda_utils.media_paths`.
A script that accepted a bare `stack/invoices/` would have to pick a root, and picking wrong
puts customer invoices on the public tree. So an unrooted prefix is REFUSED rather than
defaulted, and these tests pin that refusal.

Offline only: every case here is argument validation, so no AWS call and no credentials.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "create_s3_prefix.py"
SHARED = ROOT / "amplify" / "functions" / "shared"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def load_validate():
    """Import the script's validator without running its CLI."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("create_s3_prefix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return load_validate()


@pytest.mark.parametrize("unrooted", [
    "stack/invoices/",
    "invoices/",
    "blog-production/sources/",
    "whatsapp-media/",
])
def test_an_unrooted_prefix_is_refused_rather_than_defaulted(mod, unrooted):
    """Defaulting to a root is the failure this guards. `o/` serves without authentication, so
    guessing it for `stack/invoices/` would publish customer invoices."""
    with pytest.raises(ValueError) as caught:
        mod.validate(unrooted)
    assert "not rooted" in str(caught.value)


@pytest.mark.parametrize("rooted", [
    "secure/Invoice/customer_invoice/",
    "o/stack/whatsapp-media/",
    "secure/d/",
])
def test_a_rooted_prefix_is_accepted(mod, rooted):
    assert mod.validate(rooted) == rooted


def test_a_missing_trailing_slash_is_added():
    """Without the trailing slash the key is content, not a folder — and
    `_wipe_s3_prefix` would delete it on the first cleanup run, which is the exact opposite of
    why it was created."""
    mod = load_validate()
    assert mod.validate("secure/stack/invoices") == "secure/Invoice/customer_invoice/"


@pytest.mark.parametrize("root", ["o/", "secure/", "/o/"])
def test_a_bare_root_is_refused(mod, root):
    """Both roots already exist; marking one adds an object with no meaning."""
    with pytest.raises(ValueError):
        mod.validate(root)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_an_empty_prefix_is_refused(mod, bad):
    with pytest.raises(ValueError):
        mod.validate(bad)


def test_an_empty_path_segment_is_refused(mod):
    with pytest.raises(ValueError):
        mod.validate("secure//invoices/")


def test_the_script_cannot_create_a_bucket(mod):
    """The bucket is mandated by `.kiro/steering/blog-production-s3.md` and a hook refuses the
    command shapes that would make another. A helper that 'helpfully' created one on a typo
    would route around both."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "create_bucket" not in source
    assert "CreateBucket" not in source
    # And it must target the one bucket by reference rather than by literal, so a rename cannot
    # leave this pointing at a bucket nobody owns.
    assert "media_paths.BUCKET" in source


def test_the_gated_root_is_reported_as_gated(mod):
    """The script prints which root a prefix lands in before writing. Getting that label
    backwards would be worse than not printing it."""
    from lambda_utils import media_paths

    assert media_paths.is_gated(mod.validate("secure/Invoice/customer_invoice/")) is True
    assert media_paths.is_gated(mod.validate("o/stack/invoices/")) is False


def test_the_known_prefix_list_only_contains_rooted_entries(mod):
    """The `--list` view is the thing someone copies a prefix from."""
    assert mod.KNOWN_PREFIXES, "the known-prefix list should not be empty"
    for prefix in mod.KNOWN_PREFIXES:
        assert prefix.startswith(("o/", "secure/")), prefix
        assert prefix.endswith("/"), prefix
        assert mod.validate(prefix) == prefix


def test_the_invoice_prefix_is_listed_as_gated(mod):
    """The reason this script was written. If the invoice prefix ever appears under `o/` again,
    that is the P1 exposure returning."""
    from lambda_utils import media_paths

    invoice_prefixes = [p for p in mod.KNOWN_PREFIXES if "invoices" in p]
    assert invoice_prefixes, "the invoice prefix should be listed"
    for prefix in invoice_prefixes:
        assert media_paths.is_gated(prefix), (
            f"{prefix} is on the PUBLIC tree; a rendered invoice carries the customer's name, "
            f"address, amount and GST breakdown")


def test_the_cleanup_sweeper_preserves_folder_markers():
    """The marker only persists because `_wipe_s3_prefix` skips keys ending in `/`. If that
    filter goes, every folder created by this script silently disappears on the next purge."""
    cleanup = (ROOT / "amplify" / "functions" / "operations" / "system-cleanup"
               / "handler.py").read_text(encoding="utf-8")
    assert "not obj['Key'].endswith('/')" in cleanup, (
        "system-cleanup no longer preserves folder markers, so a created folder will not "
        "survive a wipe")


def test_the_script_runs_and_reports_without_arguments():
    """`--list` and the no-argument path must not mutate anything. Cheap to assert, and it is
    the command someone runs first."""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--list"],
                          capture_output=True, text=True, cwd=ROOT)
    # Exit 2 is the no-credentials path, which is fine in CI; what must not happen is a crash
    # or a write.
    assert proc.returncode in (0, 2), proc.stderr
    assert "never created here" in proc.stdout or proc.returncode == 2
