"""The retired wildcard can be removed safely, but cannot be recreated here."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
RETIRED_DOMAIN = "d27evp2npt2kzr.cloudfront.net"
spec = importlib.util.spec_from_file_location("home_dns", ROOT / "scripts/home_fallback_dns.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def alias(kind="A", name="*.wecare.digital."):
    return {
        "Name": name,
        "Type": kind,
        "AliasTarget": {
            "HostedZoneId": "Z2FDTNDATAQYW2",
            "DNSName": RETIRED_DOMAIN + ".",
            "EvaluateTargetHealth": False,
        },
    }


def test_retirement_deletes_only_exact_wildcard_aliases_and_preserves_other_records():
    protected = [
        alias(name="wecare.digital."),
        alias(name="mta-sts.wecare.digital."),
        alias(name="xout.wecare.digital."),
        {"Name": "sip.wecare.digital.", "Type": "A", "TTL": 60,
         "ResourceRecords": [{"Value": "192.0.2.1"}]},
        {"Name": "_validation.wecare.digital.", "Type": "CNAME", "TTL": 60,
         "ResourceRecords": [{"Value": "example.acm-validations.aws."}]},
    ]
    wildcard = [alias(), alias("AAAA")]
    records = wildcard + protected
    before = deepcopy(records)
    assert module.changes(RETIRED_DOMAIN, records) == [
        {"Action": "DELETE", "ResourceRecordSet": record} for record in wildcard
    ]
    assert records == before
    assert module.changes(RETIRED_DOMAIN, protected) == []
    assert module.changes(RETIRED_DOMAIN, []) == []


def test_route53_escaped_wildcard_is_deleted_without_rewriting_the_saved_record():
    record = alias(name="\\052.wecare.digital.")
    assert module.changes(RETIRED_DOMAIN, [record]) == [
        {"Action": "DELETE", "ResourceRecordSet": record}
    ]


@pytest.mark.parametrize("record", [
    {"Name": "*.wecare.digital.", "Type": "TXT", "ResourceRecords": [{"Value": "service"}]},
    {"Name": "*.wecare.digital.", "Type": "CNAME", "ResourceRecords": [{"Value": "other.example."}]},
    {"Name": "*.wecare.digital.", "Type": "A", "TTL": 60, "ResourceRecords": [{"Value": "192.0.2.1"}]},
    {**alias(), "AliasTarget": {**alias()["AliasTarget"], "DNSName": "other.cloudfront.net."}},
    {**alias(), "AliasTarget": {**alias()["AliasTarget"], "HostedZoneId": "OTHER"}},
    {**alias(), "AliasTarget": {**alias()["AliasTarget"], "EvaluateTargetHealth": True}},
    {**alias(), "SetIdentifier": "weighted", "Weight": 50},
])
def test_unexpected_wildcard_record_prevents_retirement(record):
    with pytest.raises(ValueError):
        module.changes(RETIRED_DOMAIN, [alias("AAAA"), record])


def test_planner_cannot_be_reused_to_remove_another_distribution():
    with pytest.raises(ValueError):
        module.changes("other.cloudfront.net", [])


def test_retired_fallback_has_no_creation_template_or_edge_function():
    assert not (ROOT / "amplify/infra/home-fallback.json").exists()
    assert not (ROOT / "scripts/home-fallback-function.js").exists()
    for path in (ROOT / "amplify/infra").glob("*.json"):
        template = json.loads(path.read_text())
        for resource in template.get("Resources", {}).values():
            if resource.get("Type") == "AWS::CloudFront::Distribution":
                aliases = resource["Properties"]["DistributionConfig"].get("Aliases", [])
                assert "*.wecare.digital" not in aliases, path.name


def test_active_migration_export_cannot_restore_retired_wildcard_routing():
    export = json.loads((ROOT / "docs/migrations/domain/wecare-digital-zone-export.json").read_text())
    wildcard_addresses = [
        (record["Name"], record["Type"])
        for record in export["ResourceRecordSets"]
        if record["Name"].replace("\\052", "*").lower() == "*.wecare.digital."
        and record["Type"] in ("A", "AAAA", "CNAME")
    ]
    assert wildcard_addresses == [], "Active migration input must preserve wildcard retirement"
