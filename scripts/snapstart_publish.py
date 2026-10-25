#!/usr/bin/env python3
"""Publish a new Lambda version and move the `live` alias onto it.

Why this exists
---------------
The HTTP API integrations invoke the **`live` alias**
(``...:function:wecare-contacts:live``), never ``$LATEST``. So
``update-function-code`` alone does not reach production: it only rewrites
``$LATEST``. A new version must be published and the alias moved.

``.kiro/steering/lambda-snapstart-deploy.md`` (retired 2026-10-09, af7858fa) documents this and states that
this file automates step 2. The PowerShell deploy scripts that used to call it
were deleted on 2026-09-20; ``scripts/deploy_all_lambdas.py`` calls it now.

Worth remembering why they went: this file had been missing from the repository
entirely, so the publish step silently no-opped on every one of those deploys.
They invoked it as ``python scripts\\_snapstart_publish.py ...`` and the
"can't open file" error was swallowed by ``$ErrorActionPreference = "Continue"``.
A deploy path that cannot fail loudly is worse than none.

Consequence observed on 2026-08-25: every payment-path `live` alias was still
pinned to a July version while ``$LATEST`` carried weeks of newer code.

Usage
-----
    python scripts/_snapstart_publish.py                     # every function with a `live` alias
    python scripts/_snapstart_publish.py wecare-contacts     # only the named functions
    python scripts/_snapstart_publish.py --dry-run           # report, change nothing
    python scripts/_snapstart_publish.py --only-stale        # skip functions already current

Exit codes: 0 all good (or nothing to do), 1 one or more functions failed.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3")

REGION = "us-east-1"
ALIAS = "live"
POLL_SECONDS = 3
POLL_ATTEMPTS = 60  # 3 min; SnapStart snapshotting can be slow


def client():
    return boto3.client("lambda", region_name=REGION)


def functions_with_live_alias(lam) -> List[str]:
    """Every function that has a `live` alias.

    Membership is keyed on the alias, not on SnapStart.ApplyOn: what decides
    whether production sees new code is the alias, and some functions carry a
    `live` alias while SnapStart is off.
    """
    names: List[str] = []
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            try:
                lam.get_alias(FunctionName=name, Name=ALIAS)
                names.append(name)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
    return sorted(names)


def current_state(lam, name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(alias_version, alias_sha, latest_sha)"""
    alias_version = alias_sha = latest_sha = None
    try:
        alias_version = lam.get_alias(FunctionName=name, Name=ALIAS)["FunctionVersion"]
        alias_sha = lam.get_function_configuration(
            FunctionName=f"{name}:{alias_version}"
        )["CodeSha256"]
    except ClientError:
        pass
    try:
        latest_sha = lam.get_function_configuration(FunctionName=name)["CodeSha256"]
    except ClientError:
        pass
    return alias_version, alias_sha, latest_sha


def environment_matches(lam, name: str, version: str) -> bool:
    """CodeSha256 excludes environment variables, which are frozen on publication."""
    served = lam.get_function_configuration(FunctionName=f'{name}:{version}')
    latest = lam.get_function_configuration(FunctionName=name)
    return (served.get('Environment', {}).get('Variables', {})
            == latest.get('Environment', {}).get('Variables', {}))


def wait_active(lam, name: str, version: str) -> bool:
    qualified = f"{name}:{version}"
    for _ in range(POLL_ATTEMPTS):
        cfg = lam.get_function_configuration(FunctionName=qualified)
        state = cfg.get("State")
        if state == "Active":
            return True
        if state == "Failed":
            print(f"    version {version} entered State=Failed: "
                  f"{cfg.get('StateReason', '')}")
            return False
        time.sleep(POLL_SECONDS)
    print(f"    timed out waiting for {qualified} to become Active")
    return False


def publish_and_move(lam, name: str, dry_run: bool, only_stale: bool) -> str:
    """Returns one of: 'updated', 'skipped', 'failed'."""
    alias_version, alias_sha, latest_sha = current_state(lam, name)

    if latest_sha is None:
        print(f"  {name}: cannot read $LATEST, skipping")
        return "failed"

    # A function with no `live` alias is not a failure - it is a documented
    # deployment model. Nine functions invoke $LATEST directly (see
    # .kiro/steering/lambda-snapstart-deploy.md (retired 2026-10-09, af7858fa)), so update_function_code already
    # reached production and there is no alias to move. Reporting these as failed
    # meant every fleet deploy ended "failed=7" for reasons unrelated to the
    # deploy, which trains everyone to ignore the number that matters.
    if alias_version is None:
        print(f"  {name}")
        print(f"    no {ALIAS} alias; invokes $LATEST directly, nothing to move")
        return "skipped"

    try:
        already_current = (alias_sha is not None and alias_sha == latest_sha
                           and environment_matches(lam, name, alias_version))
    except ClientError as exc:
        print(f"    cannot verify published environment: {exc.response['Error']['Code']}")
        return "failed"
    print(f"  {name}")
    print(f"    alias {ALIAS} -> v{alias_version}   current: {already_current}")

    if already_current and only_stale:
        print("    already serving $LATEST, skipping")
        return "skipped"

    if dry_run:
        print(f"    DRY RUN: would publish a version and move {ALIAS} onto it")
        return "skipped"

    try:
        published = lam.publish_version(
            FunctionName=name,
            Description=f"auto-publish by _snapstart_publish.py",
        )
    except ClientError as exc:
        print(f"    publish_version failed: {exc}")
        return "failed"

    new_version = published["Version"]
    print(f"    published v{new_version} (sha {published['CodeSha256'][:12]}...)")

    if not wait_active(lam, name, new_version):
        print(f"    NOT moving {ALIAS}: version never became Active")
        return "failed"

    try:
        lam.update_alias(
            FunctionName=name, Name=ALIAS, FunctionVersion=new_version
        )
    except ClientError as exc:
        print(f"    update_alias failed: {exc}")
        return "failed"

    # verify rather than assume
    check_version, check_sha, _ = current_state(lam, name)
    if check_version != new_version:
        print(f"    VERIFY FAILED: {ALIAS} is v{check_version}, expected v{new_version}")
        return "failed"

    print(f"    {ALIAS}: v{alias_version} -> v{new_version}  "
          f"(rollback: aws lambda update-alias --function-name {name} "
          f"--name {ALIAS} --function-version {alias_version})")
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Publish a Lambda version and move the `live` alias onto it."
    )
    ap.add_argument("functions", nargs="*",
                    help="function names; default is every function with a `live` alias")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    ap.add_argument("--only-stale", action="store_true",
                    help="skip functions whose alias already matches $LATEST")
    args = ap.parse_args()

    lam = client()

    targets = args.functions or functions_with_live_alias(lam)
    if not targets:
        print("no functions with a `live` alias found")
        return 0

    print(f"region={REGION} alias={ALIAS} targets={len(targets)} "
          f"dry_run={args.dry_run} only_stale={args.only_stale}")
    print()

    tally: Dict[str, int] = {"updated": 0, "skipped": 0, "failed": 0}
    for name in targets:
        tally[publish_and_move(lam, name, args.dry_run, args.only_stale)] += 1
        print()

    print(f"updated={tally['updated']} skipped={tally['skipped']} "
          f"failed={tally['failed']}")
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
