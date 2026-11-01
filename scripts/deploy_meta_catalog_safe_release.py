#!/usr/bin/env python3
"""Reviewed code-only catalog sync release to WABA1 live and WABA2 aliases.

Both alias environments intentionally differ in ONLY META_CATALOG_ID and
META_TOKEN_FIELD. A new immutable version is published for each target, with
their prior selectors preserved. No Graph API, ProductsTable, Meta catalog,
approval, secret or IAM mutation is performed. Auto-apply MUST remain OFF.

Invocation (in an exact-SHA CodeBuild checkout):
  SOURCE_COMMIT=<40-char-SHA> python scripts/deploy_meta_catalog_safe_release.py --dry-run
  SOURCE_COMMIT=<40-char-SHA> python scripts/deploy_meta_catalog_safe_release.py
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
FUNCTION = "wecare-meta-catalog-sync"
REGION = "us-east-1"
TARGETS = (
    ("live", "1457045652952851", "access_token"),
    ("waba2", "1317472650427643", "access_token_waba2"),
)
TARGET_SELECTORS = frozenset(("META_CATALOG_ID", "META_TOKEN_FIELD"))
SAFETY_FLAGS = (
    "META_CATALOG_AUTO_APPLY_SAFE",
    "META_CATALOG_SYNC_ENABLED",
    "META_CATALOG_SYNC_DRY_RUN",
)


def packager_zip() -> tuple[bytes, str]:
    path = ROOT / "scripts" / "deploy_all_lambdas.py"
    spec = importlib.util.spec_from_file_location("wecare_packager", path)
    if not spec or not spec.loader:
        raise RuntimeError("canonical Lambda packager unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = [entry for entry in module.SPECS if entry.name == FUNCTION]
    if len(entries) != 1:
        raise RuntimeError("expected one canonical catalog Lambda specification")
    package, _ = module.build_zip(entries[0])
    sha = base64.b64encode(hashlib.sha256(package).digest()).decode("ascii")
    return package, sha


def fail_if_unsafe(aliases, latest):
    versions = {}
    baseline = None
    for name, catalog_id, token_field in TARGETS:
        alias, version = aliases[name]
        current = (version.get("Environment") or {}).get("Variables") or {}
        if (current.get("META_CATALOG_ID") != catalog_id or
                current.get("META_TOKEN_FIELD") != token_field):
            raise RuntimeError(name + " has wrong catalog or token selector")
        if (current.get("META_CATALOG_AUTO_APPLY_SAFE") != "false" or
                current.get("META_CATALOG_SYNC_ENABLED") != "true"):
            raise RuntimeError(name + " is not fail-closed for catalog auto-apply")
        if (alias.get("RoutingConfig") or {}).get("AdditionalVersionWeights"):
            raise RuntimeError(name + " has unexpected weighted production routing")
        nonselectors = {k: v for k, v in current.items() if k not in TARGET_SELECTORS}
        if baseline is not None and baseline != nonselectors:
            raise RuntimeError("WABA1 and WABA2 environment differ beyond selectors")
        baseline = nonselectors
        versions[name] = str(alias["FunctionVersion"])
    latest_env = (latest.get("Environment") or {}).get("Variables") or {}
    waba2_env = (aliases["waba2"][1].get("Environment") or {}).get("Variables") or {}
    if latest_env != waba2_env:
        raise RuntimeError("unqualified function is not in WABA2 baseline state")
    return versions, waba2_env


def run(*, dry_run: bool):
    sha = os.environ.get("SOURCE_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("SOURCE_COMMIT must pin an exact forty-character revision")
    pkg, package_sha = packager_zip()
    lam = boto3.client("lambda", region_name=REGION)
    latest = lam.get_function_configuration(FunctionName=FUNCTION)
    if latest.get("State") != "Active" or latest.get("LastUpdateStatus") != "Successful":
        raise RuntimeError("catalog Lambda not ready for a code update")
    aliases = {}
    for name, _catalog_id, _token_field in TARGETS:
        alias = lam.get_alias(FunctionName=FUNCTION, Name=name)
        version = lam.get_function_configuration(
            FunctionName=FUNCTION, Qualifier=str(alias["FunctionVersion"]))
        if version.get("State") != "Active":
            raise RuntimeError(name + " current immutable version not active")
        aliases[name] = (alias, version)
    versions, waba2_env = fail_if_unsafe(aliases, latest)
    print(json.dumps({
        "phase": "preflight", "commit": sha, "codeSha256": package_sha,
        "zipBytes": len(pkg), "oldVersions": versions,
        "autoApplySafe": False, "catalogWrites": False,
        "unqualifiedTargetPreserved": "WABA2",
    }), flush=True)
    if dry_run:
        print(json.dumps({"phase": "dry-run", "aliases": 2}), flush=True)
        return

    promoted = []
    changed_latest_env = False
    try:
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=pkg,
                                 Publish=False, RevisionId=latest["RevisionId"])
        lam.get_waiter("function_updated_v2").wait(
            FunctionName=FUNCTION, WaiterConfig={"Delay": 2, "MaxAttempts": 60})
        current = lam.get_function_configuration(FunctionName=FUNCTION)
        if current.get("CodeSha256") != package_sha:
            raise RuntimeError("uploaded code hash differs from pinned package")

        for name, catalog_id, token_field in TARGETS:
            alias, _old_version = aliases[name]
            latest_now = lam.get_function_configuration(FunctionName=FUNCTION)
            desired_env = dict(waba2_env)
            desired_env["META_CATALOG_ID"] = catalog_id
            desired_env["META_TOKEN_FIELD"] = token_field
            current_env = (latest_now.get("Environment") or {}).get("Variables") or {}
            if current_env != desired_env:
                lam.update_function_configuration(
                    FunctionName=FUNCTION, Environment={"Variables": desired_env},
                    RevisionId=latest_now["RevisionId"])
                changed_latest_env = True
                lam.get_waiter("function_updated_v2").wait(
                    FunctionName=FUNCTION, WaiterConfig={"Delay": 2, "MaxAttempts": 60})
            latest_now = lam.get_function_configuration(FunctionName=FUNCTION)
            if ((latest_now.get("Environment") or {}).get("Variables") != desired_env
                    or latest_now.get("CodeSha256") != package_sha):
                raise RuntimeError(name + " source or config changed while publishing")
            published = lam.publish_version(
                FunctionName=FUNCTION, CodeSha256=package_sha,
                RevisionId=latest_now["RevisionId"],
                Description="catalog inventory fail-closed source " + sha[:12] + " " + name,
            )
            version = str(published["Version"])
            check = lam.get_function_configuration(
                FunctionName=FUNCTION, Qualifier=version)
            if (check.get("CodeSha256") != package_sha
                    or (check.get("Environment") or {}).get("Variables") != desired_env
                    or check.get("State") != "Active"):
                raise RuntimeError(name + " immutable version readback mismatch")
            # CAS against the original live alias. A concurrent release cannot be
            # silently overwritten.
            lam.update_alias(FunctionName=FUNCTION, Name=name,
                             FunctionVersion=version, RevisionId=alias["RevisionId"])
            readback = lam.get_alias(FunctionName=FUNCTION, Name=name)
            if str(readback.get("FunctionVersion")) != version:
                raise RuntimeError(name + " live alias verification failed")
            promoted.append((name, version))
            print(json.dumps({
                "phase": "promoted", "alias": name,
                "oldVersion": versions[name], "newVersion": version,
                "catalogId": catalog_id, "sourceCommit": sha,
            }), flush=True)

        latest_end = lam.get_function_configuration(FunctionName=FUNCTION)
        if (latest_end.get("Environment") or {}).get("Variables") != waba2_env:
            raise RuntimeError("unqualified Lambda WABA2 target was not restored")
        print(json.dumps({
            "phase": "success", "aliases": [
                {"alias": name, "from": versions[name], "to": version}
                for name, version in promoted
            ], "sourceCommit": sha,
            "catalogWrites": False, "autoApplySafe": False,
        }), flush=True)
    except BaseException:
        # Restore WABA2's original unqualified environment, whether or not
        # either alias was moved. Do not overwrite any third-party concurrent
        # alias move during rollback.
        try:
            now = lam.get_function_configuration(FunctionName=FUNCTION)
            if (now.get("Environment") or {}).get("Variables") != waba2_env:
                lam.update_function_configuration(
                    FunctionName=FUNCTION, Environment={"Variables": waba2_env},
                    RevisionId=now["RevisionId"])
                lam.get_waiter("function_updated_v2").wait(
                    FunctionName=FUNCTION, WaiterConfig={"Delay": 2, "MaxAttempts": 60})
                print(json.dumps({"phase": "restored-waba2-latest"}), flush=True)
        except Exception:
            print(json.dumps({"phase": "latest-env-restore-needs-review"}), flush=True)
        for name, released in reversed(promoted):
            try:
                alias = lam.get_alias(FunctionName=FUNCTION, Name=name)
                if str(alias.get("FunctionVersion")) == released:
                    lam.update_alias(
                        FunctionName=FUNCTION, Name=name,
                        FunctionVersion=versions[name],
                        RevisionId=alias["RevisionId"])
                    print(json.dumps({
                        "phase": "rolled-back", "alias": name,
                        "restoredVersion": versions[name],
                    }), flush=True)
            except Exception:
                print(json.dumps({"phase": "alias-rollback-needs-review", "alias": name}),
                      flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as error:
        print(json.dumps({"phase": "failed", "errorType": type(error).__name__}),
              file=sys.stderr)
        sys.exit(1)
