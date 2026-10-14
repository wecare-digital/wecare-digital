"""Synthetic secrets only; refresh, isolation and safe failures are the contract."""
import json

import pytest

from lambda_utils.secrets_access import JsonSecretCache, SecretAccessError


class Client:
    def __init__(self):
        self.calls = []
        self.value = {"key": "fixture-v1"}
        self.failure = False

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise RuntimeError("synthetic-private-provider-diagnostic")
        return {"SecretString": json.dumps(self.value), "VersionId": "fixture-version"}


def test_cached_credentials_refresh_after_rotation_ttl():
    now = [0]
    cache = JsonSecretCache(ttl_seconds=10, clock=lambda: now[0])
    c = Client()
    assert cache.read(c, "synthetic/a", required=("key",))["key"] == "fixture-v1"
    c.value["key"] = "fixture-v2"
    now[0] = 9
    assert cache.read(c, "synthetic/a", required=("key",))["key"] == "fixture-v1"
    now[0] = 10
    assert cache.read(c, "synthetic/a", required=("key",))["key"] == "fixture-v2"
    assert len(c.calls) == 2


def test_rotation_generation_invalidates_without_waiting():
    cache, c = JsonSecretCache(), Client()
    cache.read(c, "synthetic/a", required=("key",), generation="one")
    c.value["key"] = "fixture-v2"
    assert cache.read(c, "synthetic/a", required=("key",), generation="two")["key"] == "fixture-v2"
    assert len(cache._entries) == 1


def test_secret_names_and_clients_do_not_share_credentials():
    cache, a, b = JsonSecretCache(), Client(), Client()
    b.value["key"] = "fixture-other"
    cache.read(a, "synthetic/a", required=("key",))
    assert cache.read(b, "synthetic/a", required=("key",))["key"] == "fixture-other"
    cache.read(a, "synthetic/b", required=("key",))
    assert len(a.calls) == 2


def test_expired_cache_never_falls_back_after_lookup_failure():
    now = [0]
    cache, c = JsonSecretCache(ttl_seconds=10, clock=lambda: now[0]), Client()
    cache.read(c, "synthetic/a", required=("key",))
    now[0], c.failure = 10, True
    with pytest.raises(SecretAccessError) as error:
        cache.read(c, "synthetic/a", required=("key",))
    assert "private-provider" not in str(error.value)


@pytest.mark.parametrize("value", [{}, {"key": ""}, {"key": 123}, [], "fixture-private"])
def test_missing_or_invalid_credentials_fail_without_value_exposure(value):
    cache, c = JsonSecretCache(), Client()
    c.value = value
    with pytest.raises(SecretAccessError) as error:
        cache.read(c, "synthetic/a", required=("key",))
    assert "fixture-private" not in str(error.value)


def test_pending_and_current_versions_are_not_confused():
    cache, c = JsonSecretCache(), Client()
    cache.read(c, "synthetic/a", required=("key",), stage="AWSPENDING")
    cache.read(c, "synthetic/a", required=("key",), stage="AWSCURRENT")
    assert [v["VersionStage"] for v in c.calls] == ["AWSPENDING", "AWSCURRENT"]
