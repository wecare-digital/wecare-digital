"""Build a retirement-only plan for the unused home-fallback wildcard.

This pure helper performs no AWS calls and never creates or upserts DNS. Pass a
fresh saved Route53 record inventory; the caller must review the returned plan
before applying it. Only aliases to the retired distribution can be removed.
Explicit service names, xout and certificate-validation records are preserved.
See docs/execution/wildcard-retirement-20261019.md for the stack boundary.
"""

ZONE_ID = "Z03939753QJGZ6ZD6BXO8"
CLOUDFRONT_ZONE_ID = "Z2FDTNDATAQYW2"
RETIRED_DOMAIN = "d27evp2npt2kzr.cloudfront.net"
RETIRED_NAME = "*.wecare.digital."


def changes(domain: str, existing: list[dict]) -> list[dict]:
    if domain.rstrip(".").lower() != RETIRED_DOMAIN:
        raise ValueError("Only the retired home-fallback distribution may be removed")
    expected_alias = {
        "HostedZoneId": CLOUDFRONT_ZONE_ID,
        "DNSName": RETIRED_DOMAIN + ".",
        "EvaluateTargetHealth": False,
    }
    result = []
    for record in existing:
        if record["Name"].replace("\\052", "*").lower() != RETIRED_NAME:
            continue
        if (set(record) != {"Name", "Type", "AliasTarget"}
                or record["Type"] not in ("A", "AAAA")
                or record.get("AliasTarget") != expected_alias):
            raise ValueError("Unexpected wildcard record; rediscover before changing DNS")
        # Route53 DELETE must match the saved record exactly, including escaped Name.
        result.append({"Action": "DELETE", "ResourceRecordSet": record})
    return result
