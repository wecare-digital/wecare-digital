"""Guarded DNS cutover for the owner-approved home redirect distribution.

The distribution is provisioned by amplify/infra/home-fallback.json. Cut over
only after CloudFront reports Deployed; never change explicit service records.
Both names are owned by the alias records this module writes, so any existing
CNAME there is unexpected and refuses the change rather than being replaced.
Call apply(client, domain, existing) after saving existing to a rollback file.
"""

ZONE_ID = "Z03939753QJGZ6ZD6BXO8"
CLOUDFRONT_ZONE_ID = "Z2FDTNDATAQYW2"
NAMES = ("*.wecare.digital.", "xout.wecare.digital.")


def changes(domain: str, existing: list[dict]) -> list[dict]:
    if not domain.endswith(".cloudfront.net"):
        raise ValueError("Expected a CloudFront distribution hostname")
    result = []
    for name in NAMES:
        current = [r for r in existing if r["Name"].replace("\\052", "*") == name]
        for record in current:
            if record["Type"] not in ("A", "AAAA", "CNAME"):
                raise ValueError("Refusing cutover over a service/verification record")
            if record["Type"] in ("A", "AAAA") and record.get("AliasTarget", {}).get("DNSName", "").rstrip(".") != domain:
                raise ValueError("Unexpected existing address; rediscover before changing DNS")
            if record["Type"] == "CNAME":
                raise ValueError("Unexpected existing CNAME; rediscover before changing DNS")
        for kind in ("A", "AAAA"):
            desired = {"Name": name, "Type": kind, "AliasTarget": {
                "HostedZoneId": CLOUDFRONT_ZONE_ID, "DNSName": domain + ".",
                "EvaluateTargetHealth": False,
            }}
            if not any({**r, "Name": r["Name"].replace("\\052", "*")} == desired for r in current):
                result.append({"Action": "UPSERT", "ResourceRecordSet": desired})
    return result
