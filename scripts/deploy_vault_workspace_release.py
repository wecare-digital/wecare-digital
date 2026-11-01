#!/usr/bin/env python3
"""Release reviewed Vault and service-payment Lambda subsets from a pinned commit.

Runs inside the dedicated CodeBuild release project. It does not touch environment
variables, roles, layers, API routes, S3 objects, customers, payment rows, or WhatsApp.
The Lambda live alias is the production cutover; previous alias versions are recorded
and restored on partial failure. Do not run from an unpinned local checkout.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import boto3

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
RELEASE_ORDER = (
    "wecare-whatsapp-business-api",  # native exact-file service payment sender
    "wecare-secure-files",           # forward validated offer body {{1}}
    "wecare-service-api",           # UUID file / S3 object names on new uploads
    "wecare-ai-config-management",  # read-only registry reference for workspace
)


def load_packager():
    target = ROOT / "scripts" / "deploy_all_lambdas.py"
    spec = importlib.util.spec_from_file_location("wecare_lambda_packager", target)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not import the repository Lambda packager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Explicitly allowed for the additional message-spacing rollout only.
# Exact additional Vault renewal/scheduling backend functions; never permit an
# arbitrary Lambda name in the production release script.
ALLOWED_EXTRA_FUNCTIONS = (
    "wecare-razorpay-webhook",
    "wecare-service-requests",
    "wecare-checkout",
    # Same ecommerce/checkout package as wecare-checkout; legacy/native
    # commerce invokes must enforce the same paid-file guard at runtime.
    "wecare-commerce",
    "wecare-scheduled-messages",
)


def run(*, dry_run: bool, targets: tuple[str, ...] = RELEASE_ORDER) -> None:
    source_commit = os.environ.get("SOURCE_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("SOURCE_COMMIT must pin an exact forty-character commit SHA")

    packager = load_packager()
    client = boto3.client("lambda", region_name=REGION)
    specs = {entry.name: entry for entry in packager.SPECS}
    plans = []
    for name in targets:
        if name not in specs:
            raise RuntimeError(f"Missing packager spec for {name}")
        package, _ = packager.build_zip(specs[name])
        sha = base64.b64encode(hashlib.sha256(package).digest()).decode("ascii")
        latest = client.get_function_configuration(FunctionName=name)
        alias = client.get_alias(FunctionName=name, Name="live")
        live = client.get_function_configuration(FunctionName=name, Qualifier="live")
        if latest.get("State") != "Active" or latest.get("LastUpdateStatus") != "Successful":
            raise RuntimeError(f"{name} is not ready for a code update")
        if alias.get("FunctionVersion") != live.get("Version"):
            raise RuntimeError(f"{name}: live alias changed during preflight")
        plans.append({
            "name": name, "package": package, "sha": sha,
            "previous": str(alias["FunctionVersion"]),
            "alreadyLive": live.get("CodeSha256") == sha,
        })
        print(json.dumps({
            "phase": "preflight", "function": name, "commit": source_commit,
            "previousVersion": alias["FunctionVersion"], "alreadyLive": live.get("CodeSha256") == sha,
            "zipBytes": len(package),
        }), flush=True)

    if dry_run:
        print(json.dumps({"phase": "dry-run", "functions": len(plans)}), flush=True)
        return

    promoted = []
    try:
        for plan in plans:
            name = plan["name"]
            if plan["alreadyLive"]:
                print(json.dumps({"phase": "unchanged", "function": name}), flush=True)
                continue

            latest = client.get_function_configuration(FunctionName=name)
            alias = client.get_alias(FunctionName=name, Name="live")
            if str(alias["FunctionVersion"]) != plan["previous"]:
                raise RuntimeError(f"{name}: live alias moved after preflight")
            if latest.get("State") != "Active" or latest.get("LastUpdateStatus") != "Successful":
                raise RuntimeError(f"{name}: function changed state")

            client.update_function_code(
                FunctionName=name, ZipFile=plan["package"],
                Publish=False, RevisionId=latest["RevisionId"],
            )
            client.get_waiter("function_updated_v2").wait(
                FunctionName=name, WaiterConfig={"Delay": 2, "MaxAttempts": 60},
            )
            now = client.get_function_configuration(FunctionName=name)
            if now.get("CodeSha256") != plan["sha"]:
                raise RuntimeError(f"{name}: uploaded code SHA differs from pinned package")

            version = client.publish_version(
                FunctionName=name, RevisionId=now["RevisionId"],
                CodeSha256=plan["sha"],
                Description=f"Vault UUID storage and staff WhatsApp variable {source_commit[:12]}",
            )["Version"]
            client.update_alias(
                FunctionName=name, Name="live", FunctionVersion=str(version),
                RevisionId=alias["RevisionId"],
            )
            live = client.get_function_configuration(FunctionName=name, Qualifier="live")
            if live.get("CodeSha256") != plan["sha"] or str(live.get("Version")) != str(version):
                raise RuntimeError(f"{name}: live alias failed verification")
            promoted.append({"name": name, "before": plan["previous"], "after": str(version)})
            print(json.dumps({
                "phase": "promoted", "function": name,
                "fromVersion": plan["previous"], "toVersion": str(version),
            }), flush=True)
    except BaseException:
        for entry in reversed(promoted):
            try:
                now = client.get_alias(FunctionName=entry["name"], Name="live")
                if str(now["FunctionVersion"]) == entry["after"]:
                    client.update_alias(
                        FunctionName=entry["name"], Name="live",
                        FunctionVersion=entry["before"], RevisionId=now["RevisionId"],
                    )
                    print(json.dumps({
                        "phase": "rolled-back", "function": entry["name"],
                        "restoredVersion": entry["before"],
                    }), flush=True)
            except Exception as rollback_error:
                print(json.dumps({
                    "phase": "rollback-failed", "function": entry["name"],
                    "errorType": type(rollback_error).__name__,
                }), flush=True)
        raise

    print(json.dumps({"phase": "success", "promoted": promoted, "sourceCommit": source_commit}), flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--functions", default="",
                   help="Comma-separated subset: explicit Vault functions only")
    args = p.parse_args()
    try:
        permitted = set(RELEASE_ORDER) | set(ALLOWED_EXTRA_FUNCTIONS)
        chosen = tuple(n.strip() for n in args.functions.split(",") if n.strip()) if args.functions else RELEASE_ORDER
        if not chosen or len(chosen) != len(set(chosen)) or any(n not in permitted for n in chosen):
            raise ValueError("Invalid, duplicate or non-Vault release function")
        run(dry_run=args.dry_run, targets=chosen)
        return 0
    except Exception as exc:
        print(json.dumps({"phase": "failed", "errorType": type(exc).__name__, "message": str(exc)[:350]}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
