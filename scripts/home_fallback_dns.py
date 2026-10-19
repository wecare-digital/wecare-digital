"""Describe and validate the DNS owned by the restored home-fallback stack.

This pure helper performs no AWS calls and returns no mutation batch. The single
RecordSetGroup in amplify/infra/home-fallback.json is the only writer for these
six records. Pass the new distribution domain and a fresh saved Route53 inventory
to detect conflicts before deployment or verify its readback. Matching records
alone do not establish CloudFormation ownership. Unrelated records are untouched.
See docs/execution/wildcard-restoration-20261019.md for the ownership boundary.
"""

from copy import deepcopy
import re

CLOUDFRONT_ZONE_ID = "Z2FDTNDATAQYW2"
RETIRED_DOMAIN = "d27evp2npt2kzr.cloudfront.net"
ROUTED_NAMES = ("*.wecare.digital.", "xout.wecare.digital.")
EXCLUDED_NAMES = ("www.wecare.digital.", "www.xout.wecare.digital.")
MANAGED_NAMES = ROUTED_NAMES + EXCLUDED_NAMES


def _name(value: str) -> str:
    return value.replace("\\052", "*").rstrip(".").lower() + "."


def desired_records(domain: str) -> list[dict]:
    domain = domain.rstrip(".").lower()
    if not re.fullmatch(r"d[a-z0-9]+\.cloudfront\.net", domain) or domain == RETIRED_DOMAIN:
        raise ValueError("Use the new deployed CloudFront distribution hostname")
    records = [
        {
            "Name": name,
            "Type": kind,
            "AliasTarget": {
                "HostedZoneId": CLOUDFRONT_ZONE_ID,
                "DNSName": domain + ".",
                "EvaluateTargetHealth": False,
            },
        }
        for name in ROUTED_NAMES for kind in ("A", "AAAA")
    ]
    records.extend({
        "Name": name,
        "Type": "TXT",
        "TTL": 300,
        "ResourceRecords": [{"Value": '"retired-host"'}],
    } for name in EXCLUDED_NAMES)
    return records


def validate_existing(domain: str, existing: list[dict]) -> dict:
    desired = desired_records(domain)
    expected = {(record["Name"], record["Type"]): record for record in desired}
    present = set()
    preserved_count = 0
    for record in existing:
        name = _name(record["Name"])
        if name not in MANAGED_NAMES:
            preserved_count += 1
            continue
        normalized = deepcopy(record)
        normalized["Name"] = name
        if "AliasTarget" in normalized:
            normalized["AliasTarget"]["DNSName"] = _name(normalized["AliasTarget"]["DNSName"])
        key = (name, record["Type"])
        if key in present or normalized != expected.get(key):
            raise ValueError(f"Conflicting fallback record {name} {record['Type']}; rediscover before deployment")
        present.add(key)
    return {
        "desired_records": desired,
        "missing_records": [record for key, record in expected.items() if key not in present],
        "present_record_count": len(present),
        "preserved_record_count": preserved_count,
    }
