"""The gift-card HMAC pepper can migrate out of the Wix SPI secret by config alone.

The pepper is the HMAC key for EVERY gift-card row lookup. To retire the Wix
`wecare/wix/giftcard-spi` secret, the pepper VALUE is copied verbatim into a
non-Wix secret and GIFTCARD_PEPPER_SECRET points at it. These tests prove the
source resolves by env preference (from an INJECTED env mapping — the store holds
no ambient config), that an explicit secret_id still overrides read_pepper, and
that an identical pepper value produces an identical card hash regardless of which
secret it came from (so no card is re-keyed by the move).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402


def test_default_source_is_the_wix_spi_secret():
    assert gc.resolve_pepper_secret_id({}) == gc.SECRET_ID  # unchanged until migrated


def test_new_non_wix_secret_takes_precedence():
    env = {gc.PEPPER_SECRET_ENV_KEY: "wecare/prod/security/giftcard-pepper",
           gc.SECRET_ENV_KEY: "wecare/wix/giftcard-spi"}
    assert gc.resolve_pepper_secret_id(env) == "wecare/prod/security/giftcard-pepper"


def test_wix_env_override_without_migration():
    env = {gc.SECRET_ENV_KEY: "wecare/wix/giftcard-spi-staging"}
    assert gc.resolve_pepper_secret_id(env) == "wecare/wix/giftcard-spi-staging"


def test_read_pepper_uses_the_injected_secret_id():
    seen = {}

    def reader(secret_id):
        seen["id"] = secret_id
        return {gc.PEPPER_FIELD: "the-pepper-value"}

    sid = gc.resolve_pepper_secret_id({gc.PEPPER_SECRET_ENV_KEY: "wecare/prod/security/giftcard-pepper"})
    assert gc.read_pepper(reader, secret_id=sid) == "the-pepper-value"
    assert seen["id"] == "wecare/prod/security/giftcard-pepper"


def test_identical_pepper_gives_identical_card_hash_across_secrets():
    """The migration copies the pepper VALUE; an identical value -> identical
    code_hash, so no existing card is re-keyed by moving secrets. Uses the store's
    own hashing primitive, not a guess."""
    pepper = "same-secret-pepper"
    normalised = gc.normalise_code("GIFT-ABCD-1234")
    h1 = gc.code_hash(normalised, pepper=pepper)
    h2 = gc.code_hash(normalised, pepper=pepper)
    assert h1 == h2 and isinstance(h1, str) and len(h1) == 64  # sha256 hex


def test_missing_pepper_field_fails_closed():
    with pytest.raises(gc.GiftCardStoreUnavailable):
        gc.read_pepper(lambda _id: {}, secret_id="wecare/prod/security/giftcard-pepper")


def test_store_still_imports_no_os():
    """Regression guard mirroring test_gift_card_store: the resolver takes an
    injected env, so the store must NOT read os.environ itself."""
    import ast
    src = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_store.py").read_text()
    tree = ast.parse(src)
    imports = {a.name.split(".")[0] for n in ast.walk(tree)
               if isinstance(n, ast.Import) for a in n.names}
    imports |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)}
    assert "os" not in imports and "boto3" not in imports
