import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("media_prefix_flow", ROOT / "scripts/verify_media_prefixes.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def result(source):
    tree = ast.parse(source)
    return verifier.constant_is_always_rooted(tree, tree.body[0])


def test_receipt_suffix_is_rooted_before_addressing():
    assert result("PREFIX = 'd/public/receipts/'\nkey = media_paths.secure(f'{PREFIX}receipt.pdf')")


@pytest.mark.parametrize("use", [
    "key = PREFIX + 'receipt.pdf'",
    "s3.put_object(Key=PREFIX + 'receipt.pdf')",
    "key = media_paths.secure(f'{PREFIX}receipt.pdf')\nleak = PREFIX",
    "key = media_paths.secure(other(PREFIX))",
    "key = other.secure(PREFIX)",
    "key = media_paths.unknown(PREFIX)",
    "def export():\n    return PREFIX",
    "alias = PREFIX\nkey = media_paths.secure(alias)",
])
def test_unrooted_or_unproven_use_still_fails(use):
    assert not result("PREFIX = 'd/public/receipts/'\n" + use)


def test_unused_prefix_is_not_assumed_safe():
    assert not result("PREFIX = 'd/public/receipts/'")


def test_canonical_static_and_generated_prefixes_are_declared():
    source = (ROOT / "amplify/functions/shared/lambda_utils/media_paths.py").read_text(encoding="utf-8")
    assert 'PUBLIC_STREAM_MEDIA_DOCS_PREFIX = PUBLIC_STREAM_MEDIA_ROOT + "docs/"' in source
    assert 'PUBLIC_STREAM_MEDIA_FLAGS_PREFIX = PUBLIC_STREAM_MEDIA_M_PREFIX + "flags/"' in source
    assert 'CATALOG_GENERATED_MEDIA_PREFIX = CATALOG_MEDIA_PREFIX + "generated/"' in source

    docs = (ROOT / "amplify/functions/operations/docs-scraper/handler.py").read_text(encoding="utf-8")
    reports = (ROOT / "amplify/functions/operations/bulk-job-control/handler.py").read_text(encoding="utf-8")
    assert "PUBLIC_STREAM_MEDIA_DOCS_PREFIX" in docs
    assert "PUBLIC_STREAM_MEDIA_REPORTS_PREFIX" in reports
    assert "o/stream/docs" not in docs
    assert "o/stack/reports" not in reports
