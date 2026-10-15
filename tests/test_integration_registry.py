"""The shared integration registry: what we can read, from whom, and how stale it is.

Measured 2026-09-23 before writing any of it, because the item's provider list and
the repo's actual state disagree:

    provider            adapter files    credential
    Google Ads              0            wecare/google/ads
    Search Console          0            wecare/seo/google-oauth
    Play Reporting          0            NONE
    GA4                     6            wecare/seo/google-oauth
    Business Profile        4            wecare/seo/google-oauth
    Bing Webmaster         14            wecare/bing/api
    Meta Ads / CTWA        26            wecare/meta-system-user-token

So three of the seven have no adapter at all, and one of those has no credential
either. There was no registry of any kind.

The three decisions this module exists to enforce
-------------------------------------------------
**Access is three-state, never a boolean.** A credential existing is not the same as
a scope being granted, and that distinction has already cost this project once: the
Google OAuth client exists and works, but `contacts.readonly` was never added to the
consent screen, so the identity import is blocked on a provider setting rather than
on code. `CREDENTIAL_ABSENT` / `SCOPE_UNVERIFIED` / `VERIFIED` keeps that honest.

**A read carries its provider request id, or records that it has none.** Without one
there is no support conversation to be had with Google or Meta — "it returned the
wrong number yesterday" is unactionable. Absent is recordable; fabricated is not.

**Freshness is explicit and comparable.** A cached metric rendered without its age
is how a dashboard shows last week's numbers as today's. Every result carries
`fetched_at` and the provider's own `max_age_seconds`, and `stale` is derived rather
than asserted by the caller.

Read-only by construction: this module has no write verb. Not a flag, not a guard —
there is nothing here that could mutate a provider.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

SHARED = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.integrations import registry as reg  # noqa: E402

EXPECTED = ("google_ads", "ga4", "search_console", "business_profile",
            "play_reporting", "bing_webmaster", "meta_ads")


# ==========================================================================
# the registry covers the brief, and states the truth about each entry
# ==========================================================================
def test_every_provider_in_the_brief_is_registered():
    assert set(reg.REGISTRY) == set(EXPECTED)


@pytest.mark.parametrize("key", EXPECTED)
def test_each_entry_is_fully_described(key):
    provider = reg.resolve(key)
    assert provider.key == key
    assert provider.display_name.strip()
    assert provider.owner.strip(), "who owns the account must be recorded"
    assert provider.access in reg.ACCESS_STATES
    assert isinstance(provider.read_scopes, tuple)
    assert provider.max_age_seconds > 0, "freshness has to be expressible"


@pytest.mark.parametrize("key", EXPECTED)
def test_read_scopes_contain_nothing_write_capable(key):
    """`read_scopes` must be genuinely read-only.

    Two providers have no read-only scope available at all — Business Profile's
    `business.manage` and Play's `androidpublisher` both grant writes, and Google
    offers no narrower alternative. Those belong in `write_capable_scopes`, where
    they are visible, rather than sitting in `read_scopes` behind a name that reads
    as harmless. The registry cannot make them safe; it can only stop them being
    quietly mislabelled.
    """
    for scope in reg.resolve(key).read_scopes:
        lowered = scope.lower()
        for forbidden in (".write", ".manage", ".edit", "publish", "adwords",
                          "full_control", "_management"):
            assert forbidden not in lowered, (
                f"{key} lists {scope} as read-only; if the provider offers no "
                f"read-only alternative, declare it in write_capable_scopes with a "
                f"mitigation")


@pytest.mark.parametrize("key", EXPECTED)
def test_a_write_capable_scope_carries_a_mitigation(key):
    """Declaring the problem is not enough — the record has to say where the
    constraint is actually enforced, because it cannot be enforced here."""
    provider = reg.resolve(key)
    if provider.write_capable_scopes:
        assert len(provider.write_scope_mitigation.strip()) >= 60, (
            f"{key} declares a write-capable scope with no mitigation")


def test_exactly_the_two_known_providers_need_a_write_capable_scope():
    """Pinned so a third one cannot be added casually. Google Ads is NOT here: its
    only scope is also read/write, which is why its scope list is empty and no
    adapter may be built until that is reviewed."""
    needing = sorted(p.key for p in reg.REGISTRY.values()
                     if p.write_capable_scopes)
    assert needing == ["business_profile", "play_reporting"]


def test_google_ads_declares_no_scope_at_all():
    """Its single scope is read/write. Listing it either way would be misleading, so
    the entry carries none and says why."""
    provider = reg.resolve("google_ads")
    assert provider.read_scopes == ()
    assert provider.write_capable_scopes == ()
    assert "read/write" in provider.notes


def test_providers_without_an_adapter_are_marked_not_built():
    """Google Ads, Search Console and Play Reporting have zero adapter files. Saying
    so is the point: a registry that lists them as available would be the same lie as
    the Bedrock agent config."""
    for key in ("google_ads", "search_console", "play_reporting"):
        assert reg.resolve(key).adapter_built is False


def test_play_reporting_has_no_credential_and_says_so():
    """No secret exists for it. That is a different blocker from a missing scope, and
    conflating them sends someone to the wrong console."""
    provider = reg.resolve("play_reporting")
    assert provider.secret_name == ""
    assert provider.access == reg.ACCESS_CREDENTIAL_ABSENT


def test_the_providers_with_a_credential_name_a_real_secret():
    """Secret names measured against the account on 2026-09-23. Naming a secret that
    does not exist is how the agent config came to claim a working KB."""
    expected = {
        "google_ads": "wecare/google/ads",
        "ga4": "wecare/seo/google-oauth",
        "search_console": "wecare/seo/google-oauth",
        "business_profile": "wecare/seo/google-oauth",
        "bing_webmaster": "wecare/bing/api",
        "meta_ads": "wecare/meta-system-user-token",
    }
    for key, secret in expected.items():
        assert reg.resolve(key).secret_name == secret


def test_an_unknown_provider_is_refused_not_defaulted():
    with pytest.raises(KeyError):
        reg.resolve("linkedin_ads")


# ==========================================================================
# access is three-state
# ==========================================================================
def test_the_three_access_states_are_distinct():
    assert len({reg.ACCESS_CREDENTIAL_ABSENT, reg.ACCESS_SCOPE_UNVERIFIED,
                reg.ACCESS_VERIFIED}) == 3
    assert reg.ACCESS_STATES == (reg.ACCESS_CREDENTIAL_ABSENT,
                                 reg.ACCESS_SCOPE_UNVERIFIED,
                                 reg.ACCESS_VERIFIED)


def test_a_credential_being_present_does_not_imply_a_granted_scope():
    """The Phase 4e lesson, encoded. The Google OAuth client exists and works, and
    `contacts.readonly` was still never added to the consent screen."""
    for key in ("google_ads", "ga4", "search_console", "business_profile"):
        provider = reg.resolve(key)
        assert provider.secret_name, f"{key} should name a credential"
        assert provider.access != reg.ACCESS_VERIFIED, (
            f"{key} claims VERIFIED; nothing in this repo has demonstrated a "
            f"successful authorised read against it")


def test_nothing_claims_verified_without_evidence():
    """`VERIFIED` must mean a real read succeeded and was recorded. None has been."""
    verified = [p.key for p in reg.REGISTRY.values()
                if p.access == reg.ACCESS_VERIFIED]
    assert verified == [], verified


@pytest.mark.parametrize("key", EXPECTED)
def test_every_unverified_provider_names_its_unblock(key):
    """"Blocked" without the exact next action is a status, not information."""
    provider = reg.resolve(key)
    if provider.access != reg.ACCESS_VERIFIED:
        assert len(provider.unblock.strip()) >= 30, f"{key} has no unblock step"


def test_waiting_for_owner_is_derivable_for_reporting():
    pending = reg.waiting_for_owner()
    assert set(pending) == set(EXPECTED)
    for key, reason in pending.items():
        assert reason.strip()


# ==========================================================================
# read results: request id, freshness, quota
# ==========================================================================
def test_a_result_records_the_provider_request_id():
    result = reg.ReadResult(provider="ga4", request_id="req-abc",
                            fetched_at=1000, payload={"sessions": 5})
    assert result.request_id == "req-abc"


def test_a_missing_request_id_is_recorded_not_invented():
    """Some providers do not return one. Absent is a fact; fabricated is a lie that
    wastes a support ticket."""
    result = reg.ReadResult(provider="ga4", request_id="", fetched_at=1000,
                            payload={})
    described = result.describe()
    assert described["requestId"] is None
    assert described["requestIdAvailable"] is False


def test_staleness_is_derived_from_the_providers_own_max_age():
    fresh = reg.ReadResult(provider="ga4", request_id="r", fetched_at=1000,
                           payload={})
    assert fresh.is_stale(now=1000 + 10) is False
    max_age = reg.resolve("ga4").max_age_seconds
    assert fresh.is_stale(now=1000 + max_age + 1) is True


def test_staleness_is_reported_in_the_description():
    result = reg.ReadResult(provider="ga4", request_id="r", fetched_at=0, payload={})
    described = result.describe(now=10 ** 9)
    assert described["stale"] is True
    assert described["ageSeconds"] > 0


def test_a_result_for_an_unknown_provider_is_refused():
    with pytest.raises(KeyError):
        reg.ReadResult(provider="nope", request_id="r", fetched_at=0,
                       payload={}).is_stale(now=1)


def test_quota_headroom_is_expressed_as_used_and_limit_not_a_percentage():
    """A percentage alone cannot answer "can I make 400 more calls today", which is
    the only question a caller actually has."""
    result = reg.ReadResult(provider="bing_webmaster", request_id="r",
                            fetched_at=0, payload={},
                            quota_used=90, quota_limit=100)
    described = result.describe(now=0)
    assert described["quotaUsed"] == 90
    assert described["quotaLimit"] == 100
    assert described["quotaRemaining"] == 10


def test_quota_absent_is_distinguishable_from_quota_exhausted():
    """`remaining: 0` and "the provider does not report quota" are opposite
    situations and must not render the same."""
    unknown = reg.ReadResult(provider="ga4", request_id="r", fetched_at=0,
                             payload={}).describe(now=0)
    assert unknown["quotaRemaining"] is None
    assert unknown["quotaKnown"] is False

    exhausted = reg.ReadResult(provider="ga4", request_id="r", fetched_at=0,
                               payload={}, quota_used=100,
                               quota_limit=100).describe(now=0)
    assert exhausted["quotaRemaining"] == 0
    assert exhausted["quotaKnown"] is True


def test_a_description_carries_no_credential_material():
    result = reg.ReadResult(provider="ga4", request_id="r", fetched_at=0,
                            payload={"access_token": "ya29.not-real",
                                     "sessions": 5})
    blob = str(result.describe(now=0))
    assert "ya29.not-real" not in blob
    assert "sessions" in blob, "the actual data should survive masking"


# ==========================================================================
# read-only by construction
# ==========================================================================
def test_the_module_exposes_no_write_verb():
    """Not a flag and not a guard: there is nothing here that could mutate a
    provider, so there is nothing to switch on."""
    for name in dir(reg):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        for verb in ("write", "update", "create", "delete", "post", "put",
                     "patch", "publish", "mutate", "send"):
            assert verb not in lowered, f"registry exposes {name}"


def test_the_module_never_reads_a_secret_value():
    """Existence is checked with DescribeSecret. Pulling the value into this layer
    would put a credential in the process that renders a dashboard."""
    source = (SHARED / "lambda_utils/integrations/registry.py").read_text()
    assert "get_secret_value" not in source
    assert "GetSecretValue" not in source


def test_the_module_makes_no_provider_call():
    """A registry describes; an adapter fetches. Mixing them is how a status page
    starts costing quota."""
    source = (SHARED / "lambda_utils/integrations/registry.py").read_text()
    for forbidden in ("urllib.request", "requests.get", "http.client", "urlopen"):
        assert forbidden not in source
