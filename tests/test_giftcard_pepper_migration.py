"""Gift-card HMAC pepper is provider-neutral and fails closed.

The Wix credential namespace is retired. Existing cards remain valid because the
pepper value was copied into the neutral Secrets Manager key before cutover.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402


def test_default_source_is_the_native_pepper_secret():
    assert gc.SECRET_ID == "wecare/prod/security/giftcard-pepper"
    assert gc.resolve_pepper_secret_id({}) == gc.SECRET_ID


def test_explicit_native_secret_override_takes_precedence():
    env = {gc.PEPPER_SECRET_ENV_KEY: "wecare/prod/security/giftcard-pepper-staging"}
    assert gc.resolve_pepper_secret_id(env) == "wecare/prod/security/giftcard-pepper-staging"


def test_no_provider_secret_fallback_exists():
    env = {"WIX_GIFTCARD_SPI_SECRET": "wecare/wix/giftcard-spi"}
    assert gc.resolve_pepper_secret_id(env) == gc.SECRET_ID


def test_read_pepper_uses_the_injected_secret_id():
    seen = {}

    def reader(secret_id):
        seen["id"] = secret_id
        return {gc.PEPPER_FIELD: "the-pepper-value"}

    sid = gc.resolve_pepper_secret_id(
        {gc.PEPPER_SECRET_ENV_KEY: "wecare/prod/security/giftcard-pepper"}
    )
    assert gc.read_pepper(reader, secret_id=sid) == "the-pepper-value"
    assert seen["id"] == "wecare/prod/security/giftcard-pepper"


def test_identical_pepper_gives_identical_card_hash():
    pepper = "same-secret-pepper"
    normalised = gc.normalise_code("GIFT-ABCD-1234")
    h1 = gc.code_hash(normalised, pepper=pepper)
    h2 = gc.code_hash(normalised, pepper=pepper)
    assert h1 == h2 and isinstance(h1, str) and len(h1) == 64


def test_missing_pepper_field_fails_closed():
    with pytest.raises(gc.GiftCardStoreUnavailable):
        gc.read_pepper(lambda _id: {}, secret_id=gc.SECRET_ID)


def test_store_still_imports_no_os():
    src = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_store.py").read_text()
    tree = ast.parse(src)
    imports = {a.name.split(".")[0] for n in ast.walk(tree)
               if isinstance(n, ast.Import) for a in n.names}
    imports |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)}
    assert "os" not in imports and "boto3" not in imports
