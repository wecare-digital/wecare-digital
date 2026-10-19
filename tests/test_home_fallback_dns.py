"""The fallback owns six DNS records and preserves every unrelated service."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOMAIN = "d123example.cloudfront.net"
spec = importlib.util.spec_from_file_location("home_dns", ROOT / "scripts/home_fallback_dns.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def alias(kind="A", name="*.wecare.digital."):
    return {
        "Name": name,
        "Type": kind,
        "AliasTarget": {
            "HostedZoneId": "Z2FDTNDATAQYW2",
            "DNSName": DOMAIN + ".",
            "EvaluateTargetHealth": False,
        },
    }


def test_desired_topology_has_four_aliases_and_two_txt_only_exclusions():
    records = module.desired_records(DOMAIN)
    assert len(records) == 6
    assert {(record["Name"], record["Type"]) for record in records} == {
        (name, kind) for name in module.ROUTED_NAMES for kind in ("A", "AAAA")
    } | {(name, "TXT") for name in module.EXCLUDED_NAMES}
    for record in records[:4]:
        assert record == alias(record["Type"], record["Name"])
    for record in records[4:]:
        assert record["TTL"] == 300
        assert record["ResourceRecords"] == [{"Value": '"retired-host"'}]


def test_existing_service_inventory_is_preserved_and_reports_only_six_missing_records():
    export = json.loads((ROOT / "docs/migrations/domain/wecare-digital-zone-export.json").read_text())
    records = export["ResourceRecordSets"]
    before = deepcopy(records)
    result = module.validate_existing(DOMAIN, records)
    assert result["missing_records"] == module.desired_records(DOMAIN)
    assert result["present_record_count"] == 0
    assert result["preserved_record_count"] == len(records)
    assert records == before


def test_existing_records_are_idempotent_and_route53_names_normalize_without_mutation():
    records = module.desired_records(DOMAIN)
    records[0]["Name"] = "\\052.WECARE.DIGITAL."
    records[0]["AliasTarget"]["DNSName"] = DOMAIN.upper()
    before = deepcopy(records)
    result = module.validate_existing(DOMAIN, records)
    assert result["missing_records"] == []
    assert result["present_record_count"] == 6
    assert result["preserved_record_count"] == 0
    assert records == before


@pytest.mark.parametrize("record", [
    {"Name": "*.wecare.digital.", "Type": "CNAME", "ResourceRecords": [{"Value": "other.example."}]},
    {"Name": "*.wecare.digital.", "Type": "A", "TTL": 60, "ResourceRecords": [{"Value": "192.0.2.1"}]},
    {"Name": "xout.wecare.digital.", "Type": "TXT", "TTL": 60, "ResourceRecords": [{"Value": '"service"'}]},
    {"Name": "www.wecare.digital.", "Type": "CNAME", "ResourceRecords": [{"Value": "other.example."}]},
    {"Name": "www.xout.wecare.digital.", "Type": "A", "TTL": 60, "ResourceRecords": [{"Value": "192.0.2.1"}]},
    {"Name": "www.wecare.digital.", "Type": "TXT", "TTL": 300, "ResourceRecords": [{"Value": '"other"'}]},
])
def test_unexpected_records_fail_validation_without_mutation(record):
    before = deepcopy(record)
    with pytest.raises(ValueError):
        module.validate_existing(DOMAIN, [record])
    assert record == before


@pytest.mark.parametrize("changes", [
    {"DNSName": "dother.cloudfront.net."},
    {"HostedZoneId": "OTHER"},
    {"EvaluateTargetHealth": True},
])
def test_alias_target_drift_fails_validation(changes):
    record = alias()
    record["AliasTarget"].update(changes)
    with pytest.raises(ValueError):
        module.validate_existing(DOMAIN, [record])


def test_routing_policy_or_duplicate_records_fail_validation():
    with pytest.raises(ValueError):
        module.validate_existing(DOMAIN, [{**alias(), "SetIdentifier": "weighted", "Weight": 50}])
    with pytest.raises(ValueError):
        module.validate_existing(DOMAIN, [alias(), alias()])


@pytest.mark.parametrize("domain", [
    module.RETIRED_DOMAIN, "https://d123example.cloudfront.net", "d123example.cloudfront.net/path", "other.example",
])
def test_deleted_or_invalid_distribution_cannot_be_planned(domain):
    with pytest.raises(ValueError):
        module.desired_records(domain)


def test_template_owns_the_same_six_records_and_reuses_certificate_and_log_bucket():
    template = json.loads((ROOT / "amplify/infra/home-fallback.json").read_text())
    resources = template["Resources"]
    assert set(resources) == {"RedirectFunction", "Distribution", "FallbackDns"}
    group = resources["FallbackDns"]
    assert group["Type"] == "AWS::Route53::RecordSetGroup"
    assert group["Properties"]["HostedZoneId"] == {"Ref": "HostedZoneId"}
    resolved = deepcopy(group["Properties"]["RecordSets"])
    for record in resolved:
        if "AliasTarget" in record:
            # These four references make CloudFormation create DNS after the distribution.
            assert record["AliasTarget"]["DNSName"] == {"Fn::GetAtt": ["Distribution", "DomainName"]}
            record["AliasTarget"]["DNSName"] = DOMAIN + "."
        else:
            record["TTL"] = int(record["TTL"])
            record["ResourceRecords"] = [{"Value": value} for value in record["ResourceRecords"]]
    assert resolved == module.desired_records(DOMAIN)
    distribution = resources["Distribution"]["Properties"]["DistributionConfig"]
    assert distribution["Aliases"] == ["*.wecare.digital"]
    assert distribution["ViewerCertificate"]["AcmCertificateArn"] == {"Ref": "CertificateArn"}
    assert distribution["Logging"]["Bucket"] == {"Ref": "ExistingLogBucketDomain"}
    assert distribution["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert distribution["DefaultCacheBehavior"]["FunctionAssociations"] == [{
        "EventType": "viewer-request",
        "FunctionARN": {"Fn::GetAtt": ["RedirectFunction", "FunctionARN"]},
    }]
    assert resources["RedirectFunction"]["Properties"]["AutoPublish"] is True
    assert resources["RedirectFunction"]["Properties"]["FunctionCode"] == (
        ROOT / "scripts/home-fallback-function.js"
    ).read_text()


def test_active_migration_export_does_not_create_a_second_writer_for_fallback_records():
    export = json.loads((ROOT / "docs/migrations/domain/wecare-digital-zone-export.json").read_text())
    duplicate_ownership = [
        (record["Name"], record["Type"])
        for record in export["ResourceRecordSets"]
        if module._name(record["Name"]) in module.MANAGED_NAMES
    ]
    assert duplicate_ownership == [], "Fallback DNS belongs only to the CloudFormation RecordSetGroup"
