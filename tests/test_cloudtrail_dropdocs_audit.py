"""CloudTrail Drop Docs data-event selectors must remain scoped and opt-in."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/provision_cloudtrail.py"
spec = importlib.util.spec_from_file_location("provision_cloudtrail_test", SCRIPT)
assert spec is not None and spec.loader is not None
cloudtrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloudtrail)


def test_delete_selector_logs_only_dropdocs_source_mutations():
    fields = {item["Field"]: item for item in cloudtrail.DROP_DOCS_DELETE_SELECTOR["FieldSelectors"]}
    assert fields["eventCategory"]["Equals"] == ["Data"]
    assert fields["resources.type"]["Equals"] == ["AWS::S3::Object"]
    assert fields["resources.ARN"]["StartsWith"] == [
        "arn:aws:s3:::wecare-digital-get/secure/u/dropdocs/"
    ]
    assert fields["eventName"]["Equals"] == ["DeleteObject", "DeleteObjects"]
    assert fields["readOnly"]["Equals"] == ["false"]


def test_management_only_remains_the_default_no_cost_increase():
    old = {"AdvancedEventSelectors": [cloudtrail.MANAGEMENT_SELECTOR]}
    assert cloudtrail.desired_advanced_selectors(old) == [cloudtrail.MANAGEMENT_SELECTOR]
    assert not cloudtrail.has_dropdocs_delete_audit(old)


def test_opt_in_is_idempotent_and_followup_apply_preserves_it():
    old = {"AdvancedEventSelectors": [cloudtrail.MANAGEMENT_SELECTOR]}
    enabled = cloudtrail.desired_advanced_selectors(old, enable_dropdocs=True)
    response = {"AdvancedEventSelectors": enabled}
    assert cloudtrail.has_dropdocs_delete_audit(response)
    assert cloudtrail.logs_all_management_events(response)
    assert cloudtrail.desired_advanced_selectors(response) == enabled
    assert cloudtrail.desired_advanced_selectors(response, enable_dropdocs=True) == enabled


def test_other_existing_advanced_selectors_survive_both_paths():
    other = {"Name": "Other audit", "FieldSelectors": [
        {"Field": "eventCategory", "Equals": ["Data"]},
        {"Field": "resources.type", "Equals": ["AWS::Lambda::Function"]},
    ]}
    old = {"AdvancedEventSelectors": [cloudtrail.MANAGEMENT_SELECTOR, other]}
    normal = cloudtrail.desired_advanced_selectors(old)
    opted = cloudtrail.desired_advanced_selectors(old, enable_dropdocs=True)
    assert other in normal and other in opted
    assert cloudtrail.MANAGEMENT_SELECTOR in normal and cloudtrail.MANAGEMENT_SELECTOR in opted


def test_basic_data_event_selector_is_not_overwritten():
    old = {"EventSelectors": [{"IncludeManagementEvents": True, "DataResources": [
        {"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::another-bucket/"]},
    ]}]}
    with pytest.raises(ValueError, match="basic data-event"):
        cloudtrail.desired_advanced_selectors(old, enable_dropdocs=True)
    with pytest.raises(ValueError, match="basic data-event"):
        cloudtrail.desired_advanced_selectors(old)


def test_explicit_enable_writes_once_and_requires_verification(monkeypatch):
    class FakeTrail:
        def __init__(self):
            self.selectors = {"AdvancedEventSelectors": [cloudtrail.MANAGEMENT_SELECTOR]}
            self.writes = 0

        def get_event_selectors(self, *, TrailName):
            assert TrailName == cloudtrail.TRAIL
            return self.selectors

        def put_event_selectors(self, *, TrailName, AdvancedEventSelectors):
            assert TrailName == cloudtrail.TRAIL
            self.writes += 1
            self.selectors = {"AdvancedEventSelectors": AdvancedEventSelectors}

    fake = FakeTrail()
    checks = []
    monkeypatch.setattr(cloudtrail, "_ct", lambda: fake)
    monkeypatch.setattr(cloudtrail, "_trail_exists", lambda _: True)
    monkeypatch.setattr(cloudtrail, "verify", lambda **kw: checks.append(kw) or 0)
    assert cloudtrail.enable_dropdocs_delete_audit() == 0
    assert cloudtrail.enable_dropdocs_delete_audit() == 0
    assert fake.writes == 1
    assert checks == [
        {"require_dropdocs_delete_audit": True},
        {"require_dropdocs_delete_audit": True},
    ]
