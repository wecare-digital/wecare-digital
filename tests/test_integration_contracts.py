"""Phase 7.1 — the adapter contract, exercised over fixtures.

7.1's definition of done says it in the master prompt's own words: "Enable safe READ paths
only where the owner has supplied approved access; **otherwise complete fixtures/contracts
and mark the live read `WAITING_FOR_OWNER`**. Record scopes, ownership, quota, freshness and
provider request IDs where available."

So the owner-blocked half is a legitimate closing state, and what was missing was the
first half: nothing exercised the contract. `registry.py` described eight providers and
`ReadResult` defined how a read must report itself, and **no test drove either**. A contract
nobody runs is a docstring.

These tests use fixtures, never a network call, so they prove the read path's shape without
a credential — which is exactly what lets the live read be `WAITING_FOR_OWNER` rather than
unknown.

The five things the prompt names, and why each is checked
--------------------------------------------------------
* **ownership** — a registry without it cannot answer "who do we ask" when a read starts
  failing.
* **scopes** — and read-only separated from write-capable, because a scope that happens to
  read as read-only is how a write capability gets granted by accident. Two of the eight
  are only offered write-capable, and the registry's job is to make that visible, not to
  pretend it is safe.
* **quota** — as used/limit, not a percentage. "Can I make 400 more calls today" is the
  only question a caller has and a percentage cannot answer it. `None` (not reported) is a
  different state from `remaining == 0`.
* **freshness** — derived from the *provider's* max age, not a caller's opinion.
* **request id** — absent is recordable, fabricated is not. Without one there is no support
  conversation to have with Google or Meta.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.integrations import registry as reg  # noqa: E402

NOW = 1_800_000_000
ALL_KEYS = sorted(reg.describe_registry().keys())

# Vague words that turn an "unblock" back into a status line.
VAGUE = ("tbd", "todo", "investigate", "look into", "unknown", "figure out", "n/a")


class TestTheRegistryDescribesEveryProviderFully:
    def test_there_are_eight(self):
        assert len(ALL_KEYS) == 8, ALL_KEYS

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_ownership_is_recorded(self, key):
        provider = reg.resolve(key)
        assert provider.owner.strip(), (
            f"{key} has no owner, so nobody knows whose account to ask about when a read "
            f"starts failing")

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_access_is_one_of_the_three_states(self, key):
        assert reg.resolve(key).access in reg.ACCESS_STATES

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_freshness_is_positive_and_provider_specific(self, key):
        provider = reg.resolve(key)
        assert provider.max_age_seconds > 0, (
            f"{key} has no max age, so a cached answer can be rendered at any age without "
            f"being called stale")

    def test_freshness_is_not_one_value_copied_everywhere(self):
        # GA4 and Ads settle over hours; a search console lags a day or more. One shared
        # number would mean the registry is not actually describing the providers.
        ages = {reg.resolve(k).max_age_seconds for k in ALL_KEYS}
        assert len(ages) > 1, f"every provider has the same max age: {ages}"

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_a_credential_is_referenced_by_name_never_by_value(self, key):
        provider = reg.resolve(key)
        name = provider.secret_name
        if not name:
            # No credential is a valid state, and must line up with the access state.
            assert provider.access == reg.ACCESS_CREDENTIAL_ABSENT
            return
        assert name.startswith("wecare/"), f"{key}: {name!r} is not a secret NAME"
        # An issuer-shaped token would mean a value leaked into the registry.
        for shape in ("sk-", "AIza", "ghp_", "xoxb-", "AKIA", "rzp_live_", "sk_live_"):
            assert shape not in name, f"{key} secret_name looks like a VALUE"


class TestTheThreeStatesAreLoadBearing:
    def test_nothing_claims_VERIFIED(self):
        # VERIFIED means a real authorised read succeeded and was recorded. None has, so a
        # VERIFIED here would be the registry lying about the one thing it exists to say.
        verified = [k for k in ALL_KEYS
                    if reg.resolve(k).access == reg.ACCESS_VERIFIED]
        assert verified == [], f"claims VERIFIED without a recorded read: {verified}"

    def test_credential_absent_and_scope_unverified_are_both_present(self):
        # If everything collapsed to one state the three-state design would be decoration.
        states = {reg.resolve(k).access for k in ALL_KEYS}
        assert reg.ACCESS_CREDENTIAL_ABSENT in states
        assert reg.ACCESS_SCOPE_UNVERIFIED in states

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_credential_absent_implies_no_secret_name(self, key):
        provider = reg.resolve(key)
        if provider.access == reg.ACCESS_CREDENTIAL_ABSENT:
            assert not provider.secret_name, (
                f"{key} says CREDENTIAL_ABSENT but names a secret, so one of the two is "
                f"wrong and a reader cannot tell which")


class TestEveryBlockedProviderCarriesAnExactUnblock:
    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_the_unblock_exists_and_is_specific(self, key):
        provider = reg.resolve(key)
        if provider.access == reg.ACCESS_VERIFIED:
            return
        unblock = provider.unblock.strip()
        assert unblock, f"{key} is blocked with no unblock — that is a status, not information"
        assert len(unblock) > 30, f"{key}'s unblock is too short to be actionable: {unblock!r}"
        lowered = unblock.lower()
        for word in VAGUE:
            assert word not in lowered, (
                f"{key}'s unblock contains {word!r}, which turns it back into a status line")

    def test_waiting_for_owner_covers_every_blocked_provider(self):
        waiting = reg.waiting_for_owner()
        blocked = [k for k in ALL_KEYS
                   if reg.resolve(k).access != reg.ACCESS_VERIFIED]
        missing = [k for k in blocked if k not in waiting]
        assert not missing, (
            f"blocked but absent from waiting_for_owner(), so they would never be chased: "
            f"{missing}")


class TestWriteCapableScopesAreVisibleRatherThanHidden:
    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_read_scopes_and_write_capable_scopes_do_not_overlap(self, key):
        provider = reg.resolve(key)
        overlap = set(provider.read_scopes) & set(provider.write_capable_scopes)
        assert not overlap, (
            f"{key} lists {overlap} as read-only AND write-capable; a scope in both places "
            f"is how a write capability gets granted while looking read-only")

    def test_at_least_one_provider_admits_a_write_capable_scope(self):
        # The registry's docstring says two of the eight are in this position. If this ever
        # finds none, either the providers changed or somebody quietly moved a scope into
        # read_scopes to make the list look clean.
        with_write = [k for k in ALL_KEYS if reg.resolve(k).write_capable_scopes]
        assert with_write, (
            "no provider declares a write-capable scope, which contradicts the registry's "
            "own account of the two that only offer one")

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_a_write_capable_scope_comes_with_a_mitigation(self, key):
        provider = reg.resolve(key)
        if provider.write_capable_scopes:
            assert provider.write_scope_mitigation.strip(), (
                f"{key} needs a write-capable scope and records no mitigation, so the risk "
                f"is visible but unaddressed")


class TestTheReadResultContract:
    """Exercised over fixtures. No provider is called."""

    def a_result(self, **over):
        base = dict(provider="ga4", request_id="req-abc-123", fetched_at=NOW,
                    payload={"rows": [{"sessions": 12}]})
        base.update(over)
        return reg.ReadResult(**base)

    def test_a_read_reports_its_provider_request_id(self):
        described = self.a_result().describe(now=NOW)
        assert described["requestId"] == "req-abc-123"
        assert described["requestIdAvailable"] is True

    def test_an_absent_request_id_is_None_not_an_empty_string(self):
        # So a consumer cannot render '' as though it were an id.
        described = self.a_result(request_id="").describe(now=NOW)
        assert described["requestId"] is None
        assert described["requestIdAvailable"] is False

    def test_freshness_is_derived_from_the_providers_own_max_age(self):
        max_age = reg.resolve("ga4").max_age_seconds
        fresh = self.a_result(fetched_at=NOW - 1).describe(now=NOW)
        stale = self.a_result(fetched_at=NOW - max_age - 1).describe(now=NOW)
        assert fresh["stale"] is False
        assert stale["stale"] is True
        assert stale["maxAgeSeconds"] == max_age

    def test_age_never_goes_negative_on_a_clock_skew(self):
        # A provider timestamp slightly ahead of ours must not render as a negative age.
        described = self.a_result(fetched_at=NOW + 500).describe(now=NOW)
        assert described["ageSeconds"] == 0

    def test_quota_unknown_is_a_different_state_from_none_remaining(self):
        unknown = self.a_result().describe(now=NOW)
        assert unknown["quotaKnown"] is False
        assert unknown["quotaRemaining"] is None

        exhausted = self.a_result(quota_used=500, quota_limit=500).describe(now=NOW)
        assert exhausted["quotaKnown"] is True
        assert exhausted["quotaRemaining"] == 0

    def test_quota_remaining_answers_the_only_question_a_caller_has(self):
        described = self.a_result(quota_used=100, quota_limit=500).describe(now=NOW)
        assert described["quotaRemaining"] == 400

    def test_quota_remaining_does_not_go_negative_when_a_provider_overruns(self):
        described = self.a_result(quota_used=600, quota_limit=500).describe(now=NOW)
        assert described["quotaRemaining"] == 0

    def test_the_payload_is_masked_because_this_gets_logged_and_rendered(self):
        # A provider payload can carry a refreshed token.
        leaky = self.a_result(payload={"access_token": "ya29.SUPERSECRETVALUE",
                                       "rows": [{"sessions": 1}]})
        described = leaky.describe(now=NOW)
        assert "ya29.SUPERSECRETVALUE" not in str(described["payload"])
        # And the useful part survives the masking.
        assert "rows" in described["payload"]

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_every_provider_can_produce_a_describable_result(self, key):
        # The contract has to hold for all eight, not just the one with an adapter.
        described = reg.ReadResult(provider=key, request_id="", fetched_at=NOW).describe(
            now=NOW)
        assert described["provider"] == key
        assert described["maxAgeSeconds"] == reg.resolve(key).max_age_seconds


class TestTheRegistryStillDoesNotFetch:
    def test_there_is_no_write_verb_and_no_provider_call(self):
        source = (SHARED / "lambda_utils/integrations/registry.py").read_text()
        import ast
        tree = ast.parse(source)
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)):
            source = source.replace(tree.body[0].value.value, "", 1)
        source = "\n".join(
            ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
        # A registry that fetches is a status page that costs quota. And it must never
        # read a secret VALUE — existence is established with DescribeSecret.
        for banned in ("urlopen", "requests.", "httpx", "get_secret_value",
                       "batch_get_secret_value"):
            assert banned not in source, f"registry.py now does {banned}"

    def test_the_generated_frontend_snapshot_agrees_with_the_registry(self):
        # The UI renders a generated snapshot; if it drifts, the dashboard shows a
        # connection state that is no longer true. Retired providers still resolve in
        # the registry but the generator leaves them out of the snapshot on purpose.
        import json
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import generate_integration_inventory as inventory

        assert inventory.RETIRED <= set(ALL_KEYS), "a retired key is not in the registry"
        snapshot = json.loads(
            (ROOT / "src/content/integration-registry.json").read_text())
        assert {p["key"] for p in snapshot["providers"]} == set(ALL_KEYS) - inventory.RETIRED
        for entry in snapshot["providers"]:
            assert entry["access"] == reg.resolve(entry["key"]).access, (
                f"{entry['key']} differs between the registry and the committed snapshot; "
                f"run scripts/generate_integration_inventory.py")
