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

Concurrent deploys
------------------
Nothing serialises deploys. On 2026-10-25 local sessions, a CodeBuild project and an MCP
client moved the same five WhatsApp `live` aliases 19 times in 17 minutes. Unguarded, a run
publishes whatever ``$LATEST`` holds when it gets there, which can be another run's code, and
its alias move can put production back on code another run had already replaced. So each
write here is conditional:

* ``publish_version`` carries ``CodeSha256`` (and ``RevisionId``), so the version holds
  exactly the code and configuration this run inspected;
* ``update_alias`` carries the alias ``RevisionId`` read at the start, so an alias someone
  else moved in the meantime is left alone and this run fails instead;
* ``--expect FUNCTION=CODESHA256`` (``deploy_all_lambdas.py`` passes the sha it uploaded)
  refuses to publish unless ``$LATEST`` still holds that code.

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
from typing import Dict, List, NamedTuple, Optional

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


class State(NamedTuple):
    """One read of the alias and of $LATEST, with the revision ids that guard the writes."""
    alias_version: Optional[str]
    alias_sha: Optional[str]
    alias_revision: Optional[str]
    latest_sha: Optional[str]
    latest_revision: Optional[str]


def current_state(lam, name: str) -> State:
    alias_version = alias_sha = alias_revision = latest_sha = latest_revision = None
    try:
        alias = lam.get_alias(FunctionName=name, Name=ALIAS)
        alias_version, alias_revision = alias["FunctionVersion"], alias.get("RevisionId")
        alias_sha = lam.get_function_configuration(
            FunctionName=f"{name}:{alias_version}"
        )["CodeSha256"]
    except ClientError:
        pass
    try:
        latest = lam.get_function_configuration(FunctionName=name)
        latest_sha, latest_revision = latest["CodeSha256"], latest.get("RevisionId")
    except ClientError:
        pass
    return State(alias_version, alias_sha, alias_revision, latest_sha, latest_revision)


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



META_CATALOG_SYNC_FUNCTION = "wecare-meta-catalog-sync"
META_CATALOG_TARGET_ENV_KEYS = ("META_CATALOG_ID", "META_TOKEN_FIELD")


def _stage_primary_catalog_env(lam, name: str, dry_run: bool):
    """For meta-catalog-sync only, publish `:live` with WABA1's frozen environment.

    The unqualified function is the dedicated WABA2 sync target. A code-only deploy updates
    $LATEST in place, so before publishing the next `:live` version we temporarily copy the
    two public target selectors from the currently served WABA1 version onto $LATEST. After the
    alias moves, the caller restores the original $LATEST environment for WABA2.

    Returns (original_latest_environment, changed).
    """
    if name != META_CATALOG_SYNC_FUNCTION:
        return None, False
    latest = lam.get_function_configuration(FunctionName=name)
    original = dict((latest.get("Environment") or {}).get("Variables") or {})
    live_alias = lam.get_alias(FunctionName=name, Name=ALIAS)
    live_cfg = lam.get_function_configuration(
        FunctionName=f"{name}:{live_alias['FunctionVersion']}"
    )
    live_env = dict((live_cfg.get("Environment") or {}).get("Variables") or {})
    staged = dict(original)
    for key in META_CATALOG_TARGET_ENV_KEYS:
        if key in live_env:
            staged[key] = live_env[key]
    if staged == original:
        return original, False
    if dry_run:
        return original, True
    revision = latest.get("RevisionId")
    kwargs = {
        "FunctionName": name,
        "Environment": {"Variables": staged},
    }
    if revision:
        kwargs["RevisionId"] = revision
    lam.update_function_configuration(**kwargs)
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)
    return original, True


def _restore_secondary_catalog_env(lam, name: str, original_environment, dry_run: bool) -> None:
    """Restore the WABA2 $LATEST target after publishing WABA1's immutable version."""
    if name != META_CATALOG_SYNC_FUNCTION or original_environment is None or dry_run:
        return
    latest = lam.get_function_configuration(FunctionName=name)
    if dict((latest.get("Environment") or {}).get("Variables") or {}) == original_environment:
        return
    kwargs = {
        "FunctionName": name,
        "Environment": {"Variables": original_environment},
    }
    revision = latest.get("RevisionId")
    if revision:
        kwargs["RevisionId"] = revision
    lam.update_function_configuration(**kwargs)
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)


def publish_and_move(lam, name: str, dry_run: bool, only_stale: bool,
                     expected_sha: Optional[str] = None) -> str:
    """Returns one of: 'updated', 'skipped', 'failed'.

    expected_sha: the CodeSha256 the calling deploy uploaded. When given, a $LATEST holding
    anything else means another deploy replaced it, and nothing is published.
    """
    state = current_state(lam, name)
    alias_version, alias_sha, latest_sha = state.alias_version, state.alias_sha, state.latest_sha

    if latest_sha is None:
        print(f"  {name}: cannot read $LATEST, skipping")
        return "failed"

    if expected_sha and latest_sha != expected_sha:
        print(f"  {name}")
        print(f"    $LATEST is {latest_sha[:12]}..., not the {expected_sha[:12]}... this deploy "
              "uploaded: another deploy replaced it. Not publishing.")
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

    original_catalog_env = None
    catalog_env_changed = False
    try:
        original_catalog_env, catalog_env_changed = _stage_primary_catalog_env(
            lam, name, dry_run
        )
    except ClientError as exc:
        print(f"    cannot stage WABA1 catalog environment: {exc.response['Error']['Code']}")
        return "failed"

    if dry_run:
        if catalog_env_changed:
            print("    DRY RUN: would stage WABA1 target selectors for publication, then restore WABA2")
        print(f"    DRY RUN: would publish a version and move {ALIAS} onto it")
        return "skipped"

    publish_request = {
        "FunctionName": name,
        "Description": "auto-publish by _snapstart_publish.py",
        # Exactly the code inspected above, never a $LATEST another deploy swapped in since.
        "CodeSha256": latest_sha,
    }
    if state.latest_revision and not catalog_env_changed:
        # Staging the catalog environment is this run's own write and moves the revision.
        publish_request["RevisionId"] = state.latest_revision
    try:
        published = lam.publish_version(**publish_request)
    except ClientError as exc:
        print(f"    publish_version failed: {exc}")
        try:
            _restore_secondary_catalog_env(lam, name, original_catalog_env, dry_run=False)
        except ClientError as restore_exc:
            print(f"    WABA2 environment restore failed: {restore_exc.response['Error']['Code']}")
        return "failed"

    new_version = published["Version"]
    print(f"    published v{new_version} (sha {published['CodeSha256'][:12]}...)")

    if not wait_active(lam, name, new_version):
        print(f"    NOT moving {ALIAS}: version never became Active")
        return "failed"

    alias_request = {"FunctionName": name, "Name": ALIAS, "FunctionVersion": new_version}
    if state.alias_revision:
        # Only over the alias this run read: never move production back onto older code
        # after another deploy has moved it on.
        alias_request["RevisionId"] = state.alias_revision
    try:
        lam.update_alias(**alias_request)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "PreconditionFailedException":
            print(f"    {ALIAS} moved after this run read it (another deploy); leaving it. "
                  f"v{new_version} is published but not live.")
        else:
            print(f"    update_alias failed: {exc}")
        try:
            _restore_secondary_catalog_env(lam, name, original_catalog_env, dry_run=False)
        except ClientError as restore_exc:
            print(f"    WABA2 environment restore failed: {restore_exc.response['Error']['Code']}")
        return "failed"

    # verify rather than assume
    check = current_state(lam, name)
    if check.alias_version != new_version:
        print(f"    VERIFY FAILED: {ALIAS} is v{check.alias_version}, expected v{new_version}")
        return "failed"

    try:
        _restore_secondary_catalog_env(lam, name, original_catalog_env, dry_run=False)
    except ClientError as exc:
        print(f"    VERIFY FAILED: WABA2 $LATEST environment restore failed: {exc.response['Error']['Code']}")
        return "failed"

    print(f"    {ALIAS}: v{alias_version} -> v{new_version}  "
          f"(rollback: aws lambda update-alias --function-name {name} "
          f"--name {ALIAS} --function-version {alias_version})")
    if catalog_env_changed:
        print("    catalog targets preserved: live=WABA1, $LATEST=WABA2")
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
    ap.add_argument("--expect", action="append", default=[], metavar="FUNCTION=CODESHA256",
                    help="publish FUNCTION only while $LATEST holds exactly this code "
                         "(repeatable; deploy_all_lambdas.py passes what it uploaded)")
    args = ap.parse_args()

    expected: Dict[str, str] = {}
    for item in args.expect:
        # CodeSha256 is base64 and may end in '=', so split on the first '=' only.
        function, separator, sha = item.partition("=")
        if not separator or not function or not sha:
            ap.error(f"--expect wants FUNCTION=CODESHA256, got {item!r}")
        expected[function] = sha

    lam = client()

    targets = args.functions or functions_with_live_alias(lam)
    if not targets:
        print("no functions with a `live` alias found")
        return 0
    stray = sorted(set(expected) - set(targets))
    if stray:
        ap.error("--expect names functions that are not targets: " + ", ".join(stray))

    print(f"region={REGION} alias={ALIAS} targets={len(targets)} "
          f"dry_run={args.dry_run} only_stale={args.only_stale}")
    print()

    tally: Dict[str, int] = {"updated": 0, "skipped": 0, "failed": 0}
    for name in targets:
        tally[publish_and_move(lam, name, args.dry_run, args.only_stale,
                               expected.get(name))] += 1
        print()

    print(f"updated={tally['updated']} skipped={tally['skipped']} "
          f"failed={tally['failed']}")
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
