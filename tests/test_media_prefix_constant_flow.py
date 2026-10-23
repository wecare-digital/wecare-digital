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
