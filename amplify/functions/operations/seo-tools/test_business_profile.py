"""The DORMANT Google Business Profile enrichment returns 'no data' until a human is approved.

THE REFUSALS ARE THE POINT. The GBP API is not approved for this project: every quota_limit_value
reads 0, which Google defines as "access never granted", and a live call answers HTTP 429 that only
LOOKS like rate limiting. So the two most important tests here prove the module does the two things
business_profile_access.py warns against NOT doing: it does not retry a 429, and it treats
quota_limit_value==0 as permanent "no data" rather than a transient fault. The rest prove the pure
mapping is honest - it maps what is present and omits what is not, never fabricating hours or a
category.

NETWORK-FREE BY CONSTRUCTION. The flag-off test asserts no network call is even attempted. The
mapping tests feed FIXTURE location objects (clearly test-only data below, never shipped as site
data) straight into to_schema(), so no token, no urllib, no socket is involved. The repo's root
conftest.py additionally blocks every outbound connection, so an accidental live call would fail
loudly rather than silently reach Google.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SEO_DIR = pathlib.Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SEO_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


business_profile = _load("business_profile")


# ── FIXTURES: test-only data. NOT real business hours or category; never shipped as site data. ──

def _fixture_location():
    """A realistic-shaped GBP location: Mon-Fri 09:00-17:00 plus a primaryCategory displayName.

    These are invented values for exercising the mapping. They are intentionally NOT the business's
    real hours or category - this module never carries real GBP values; those come only from a live
    approved API call in the real deployment.
    """
    return {
        "name": "locations/11367616731342236672",
        "regularHours": {
            "periods": [
                {"openDay": "MONDAY", "openTime": {"hours": 9},
                 "closeDay": "MONDAY", "closeTime": {"hours": 17}},
                {"openDay": "TUESDAY", "openTime": {"hours": 9},
                 "closeDay": "TUESDAY", "closeTime": {"hours": 17}},
                {"openDay": "WEDNESDAY", "openTime": {"hours": 9},
                 "closeDay": "WEDNESDAY", "closeTime": {"hours": 17}},
                {"openDay": "THURSDAY", "openTime": {"hours": 9},
                 "closeDay": "THURSDAY", "closeTime": {"hours": 17}},
                {"openDay": "FRIDAY", "openTime": {"hours": 9, "minutes": 30},
                 "closeDay": "FRIDAY", "closeTime": {"hours": 17, "minutes": 30}},
            ],
        },
        "categories": {
            "primaryCategory": {
                "name": "gcid:test_category",
                "displayName": "Test Category Display Name",
            },
        },
    }


def _quota_zero_429_body():
    """A GBP 429 body carrying quota_limit_value '0' - the 'access never granted' signal."""
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "metadata": {"quota_limit_value": "0"},
                },
            ],
        },
    }


# ── (a) Flag OFF => no data, and no network attempt. ──

def test_flag_off_returns_none_without_network(monkeypatch):
    monkeypatch.delenv("GBP_LOCALBUSINESS_ENABLED", raising=False)

    # If the flag-off path ever reached these, the test would fail loudly rather than silently
    # make a live call. The default is off, so neither should be touched.
    def _boom(*_args, **_kwargs):
        raise AssertionError("flag-off path must not mint a token or hit the network")

    monkeypatch.setattr(business_profile, "_sa_token", _boom)
    monkeypatch.setattr(business_profile, "_get", _boom)

    assert business_profile.business_profile_enabled() is False
    assert business_profile.fetch_business_profile() is None


def test_flag_typo_is_still_off(monkeypatch):
    # A fail-safe default: anything that is not an explicit truthy value resolves to off.
    monkeypatch.setenv("GBP_LOCALBUSINESS_ENABLED", "treu")
    assert business_profile.business_profile_enabled() is False


# ── (b) A 429 with quota_limit_value '0' is diagnosed as dormant/no-data, and is NOT retried. ──

def test_quota_zero_429_is_dormant_not_retried(monkeypatch):
    monkeypatch.setenv("GBP_LOCALBUSINESS_ENABLED", "true")
    monkeypatch.setattr(business_profile, "_sa_token", lambda: "fake-token")

    calls = {"count": 0}

    def _fake_get(_url, _token):
        calls["count"] += 1
        return 429, _quota_zero_429_body()

    monkeypatch.setattr(business_profile, "_get", _fake_get)

    assert business_profile.fetch_business_profile() is None
    # The whole point: a single attempt, never a retry loop against a quota that does not exist.
    assert calls["count"] == 1


def test_quota_limit_value_reads_zero():
    assert business_profile.quota_limit_value(_quota_zero_429_body()) == "0"
    assert business_profile.quota_limit_value({}) is None
    assert business_profile.quota_limit_value("not a dict") is None


# ── (c) to_schema maps a realistic fixture to valid openingHoursSpecification + category. ──

def test_to_schema_maps_fixture_hours_and_category():
    result = business_profile.to_schema(_fixture_location())
    assert result is not None

    specs = result["openingHoursSpecification"]
    assert len(specs) == 5
    for spec in specs:
        assert spec["@type"] == "OpeningHoursSpecification"
        assert isinstance(spec["dayOfWeek"], list) and len(spec["dayOfWeek"]) == 1

    monday = specs[0]
    assert monday["dayOfWeek"] == ["Monday"]
    assert monday["opens"] == "09:00"
    assert monday["closes"] == "17:00"

    friday = specs[4]
    assert friday["dayOfWeek"] == ["Friday"]
    assert friday["opens"] == "09:30"
    assert friday["closes"] == "17:30"

    assert result["category"] == "Test Category Display Name"


# ── (d) Missing regularHours omits openingHoursSpecification (no fabrication). ──

def test_to_schema_omits_missing_hours():
    only_category = {
        "categories": {"primaryCategory": {"displayName": "Just A Category"}},
    }
    result = business_profile.to_schema(only_category)
    assert result == {"category": "Just A Category"}
    assert "openingHoursSpecification" not in result


def test_to_schema_omits_missing_category():
    only_hours = {
        "regularHours": {
            "periods": [
                {"openDay": "MONDAY", "openTime": {"hours": 9},
                 "closeDay": "MONDAY", "closeTime": {"hours": 17}},
            ],
        },
    }
    result = business_profile.to_schema(only_hours)
    assert "category" not in result
    assert len(result["openingHoursSpecification"]) == 1


def test_to_schema_drops_half_specified_period():
    # A period missing its close time is dropped, never completed with a guessed time.
    partial = {
        "regularHours": {
            "periods": [
                {"openDay": "MONDAY", "openTime": {"hours": 9}},
                {"openDay": "TUESDAY", "openTime": {"hours": 9},
                 "closeDay": "TUESDAY", "closeTime": {"hours": 17}},
            ],
        },
    }
    result = business_profile.to_schema(partial)
    assert len(result["openingHoursSpecification"]) == 1
    assert result["openingHoursSpecification"][0]["dayOfWeek"] == ["Tuesday"]


# ── (e) Empty / unusable input returns None. ──

@pytest.mark.parametrize("raw", [{}, None, "not a dict", {"regularHours": {}, "categories": {}}])
def test_to_schema_empty_input_returns_none(raw):
    assert business_profile.to_schema(raw) is None
