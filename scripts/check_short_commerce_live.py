#!/usr/bin/env python3
"""Read-only Short Commerce production configuration and release attestation gate.

This script never reads customer, order, payment or catalog records and never
mutates AWS. A healthy flag is NOT evidence that old Lambda code is safe to run.
Return 0 only when all three live aliases match an independently reviewed,
version-pinned release manifest and the named payment alarms are OK.

The manifest attests expected release artifacts, not payment-rail owner approval,
provider capture parity, Meta asset publication or completion of handset QA.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
from pathlib import Path
import re
import sys

RECEIVERS = ("wecare-commerce", "wecare-checkout", "wecare-inbound-whatsapp")
FLAG = "SHORT_COMMERCE_PART1_ENABLED"
PAYMENT_ALARMS = (
    "wecare-payment-invoice-delivery-failed",
    "wecare-payment-order-completed-blocked",
    "wecare-payment-order-status-deferred",
    "wecare-payment-order-status-retry-error",
    "wecare-payment-order-status-retry-query-failed",
    "wecare-payment-order-status-uncertain",
    "wecare-payment-paid-state-incomplete",
    "wecare-payment-readiness-refused",
)


def read_release_manifest(path: Path, *, expected_account: str, region: str) -> dict:
    """Refuse incomplete or unpinned operator attestations before AWS is queried."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "short-commerce-release-v1":
        raise ValueError("unsupported release-manifest schema")
    if data.get("account") != expected_account or data.get("region") != region:
        raise ValueError("release manifest is for a different account or region")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("source_commit", ""))):
        raise ValueError("release manifest needs a full reviewed Git commit SHA")
    receivers = data.get("receivers")
    if not isinstance(receivers, dict) or set(receivers) != set(RECEIVERS):
        raise ValueError("release manifest must pin exactly the three receivers")
    for name in RECEIVERS:
        item = receivers[name]
        if not isinstance(item, dict):
            raise ValueError(f"{name}: missing version and code hash")
        version, code_sha = item.get("version"), item.get("code_sha256")
        if not isinstance(version, str) or not re.fullmatch(r"[1-9][0-9]*", version):
            raise ValueError(f"{name}: pin a published numeric Lambda version")
        if not isinstance(code_sha, str):
            raise ValueError(f"{name}: missing CodeSha256")
        try:
            decoded = base64.b64decode(code_sha, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{name}: invalid CodeSha256") from exc
        if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != code_sha:
            raise ValueError(f"{name}: CodeSha256 must be canonical SHA-256 base64")
    return data


def live_snapshot(session, *, region: str, release_manifest: dict | None = None) -> dict:
    """Read live alias targets, deployed code hashes, feature flags and eight alarms."""
    sts = session.client("sts", region_name=region)
    functions = session.client("lambda", region_name=region)
    watch = session.client("cloudwatch", region_name=region)
    account = sts.get_caller_identity()["Account"]

    receivers = []
    for name in RECEIVERS:
        try:
            alias = functions.get_alias(FunctionName=name, Name="live")
            response = functions.get_function_configuration(FunctionName=name, Qualifier="live")
        except functions.exceptions.ResourceNotFoundException:
            receivers.append({"name": name, "found": False, "flag": False,
                              "ready": False, "reason": "live_alias_or_function_missing"})
            continue
        expected = (release_manifest or {}).get("receivers", {}).get(name)
        alias_version = str(alias.get("FunctionVersion", ""))
        deployed_version = str(response.get("Version", ""))
        weighted = bool(alias.get("RoutingConfig", {}).get("AdditionalVersionWeights", {}))
        alias_ok = (bool(re.fullmatch(r"[1-9][0-9]*", alias_version)) and alias_version == deployed_version and not weighted)
        value = response.get("Environment", {}).get("Variables", {}).get(FLAG, "")
        flag = str(value).strip().lower() in ("true", "1", "yes", "on")
        version_ok = bool(expected and expected["version"] == deployed_version)
        code_ok = bool(expected and expected["code_sha256"] == response.get("CodeSha256"))
        healthy = (response.get("State") == "Active"
                   and response.get("LastUpdateStatus") == "Successful")
        receivers.append({
            "name": name,
            "alias_version": alias_version,
            "published_version": deployed_version,
            "code_sha256": response.get("CodeSha256"),
            "state": response.get("State"),
            "last_update_status": response.get("LastUpdateStatus"),
            "flag": flag,
            "alias_unweighted_and_pinned": alias_ok,
            "version_matches_manifest": version_ok,
            "code_matches_manifest": code_ok,
            "ready": bool(healthy and flag and alias_ok and version_ok and code_ok),
        })

    response = watch.describe_alarms(AlarmNames=list(PAYMENT_ALARMS))
    observed = {a.get("AlarmName"): a.get("StateValue")
                for a in response.get("MetricAlarms", [])}
    alarms = [{"name": name, "state": observed.get(name, "MISSING")}
              for name in PAYMENT_ALARMS]
    return {
        "account": account,
        "region": region,
        "reviewed_manifest_supplied": release_manifest is not None,
        "source_commit": release_manifest.get("source_commit") if release_manifest else None,
        "receivers": receivers,
        "payment_alarms": alarms,
        "config_ok": bool(release_manifest) and all(row["ready"] for row in receivers),
        "alarms_ok": all(a["state"] == "OK" for a in alarms),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--expect-account", required=True)
    parser.add_argument("--release-manifest", type=Path,
                        help="reviewed version+CodeSha256 for all three receivers; required to pass")
    args = parser.parse_args()
    manifest = None
    if args.release_manifest:
        try:
            manifest = read_release_manifest(args.release_manifest,
                                             expected_account=args.expect_account,
                                             region=args.region)
        except (OSError, UnicodeError, ValueError) as exc:
            print(json.dumps({"ok": False, "error_type": "InvalidReleaseManifest",
                              "message": str(exc)}), file=sys.stderr)
            return 2
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        print(json.dumps({"ok": False, "error_type": "MissingAwsSdk"}), file=sys.stderr)
        return 2
    try:
        snapshot = live_snapshot(boto3.Session(), region=args.region,
                                 release_manifest=manifest)
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    ok = (snapshot["account"] == args.expect_account
          and snapshot["config_ok"] and snapshot["alarms_ok"])
    print(json.dumps({"ok": ok, **snapshot}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
