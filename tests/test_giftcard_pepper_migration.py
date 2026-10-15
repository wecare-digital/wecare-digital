"""The gift-card HMAC pepper: one secret, resolved by injection, and fail-closed.

Every card key is an HMAC under the pepper VALUE, so the secret id has exactly one override
(`GIFTCARD_PEPPER_SECRET`) and an unusable secret refuses rather than deriving a key from nothing.
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


class _RecordingEnv(dict):
    """An env mapping that records every key the resolver asks for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.asked = []

    def get(self, key, default=None):
        self.asked.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.asked.append(key)
        return super().__getitem__(key)


def test_the_resolver_consults_exactly_one_env_var():
    """`GIFTCARD_PEPPER_SECRET` is the only key read. Any other secret-looking variable in the
    environment leaves the default in place, so the pepper cannot be redirected by accident."""
    env = _RecordingEnv({"OTHER_GIFTCARD_SECRET": "wecare/prod/security/other",
                         "AWS_REGION": "us-east-1"})
    assert gc.resolve_pepper_secret_id(env) == gc.SECRET_ID
    assert env.asked == [gc.PEPPER_SECRET_ENV_KEY]


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
