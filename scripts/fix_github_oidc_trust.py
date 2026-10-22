#!/usr/bin/env python3
"""Repair the GitHub Actions OIDC trust policies broken by the repository rename.

WHY. The GitHub repo was renamed `bharat-stack` -> `wecare-digital` on 2026-09-27.
Both deploy workflows authenticate by OIDC and then failed with

    Not authorized to perform sts:AssumeRoleWithWebIdentity

which reads as a credentials problem and is not one. This repository was created
2026-08-22, i.e. after 2026-07-15, so it uses GitHub's **immutable** subject
format:

    repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH

The owner id and repo id survive a rename -- that is the point of the format --
but the *name* segments do not, and they are still present in `sub`. So the
trust policies, which pinned the whole string with `StringEquals`, went stale at
the name and nowhere else:

    before  repo:wecare-digital@319896805/bharat-stack@1342943014:ref:refs/heads/stack
    after   repo:wecare-digital@319896805/wecare-digital@1342943014:ref:refs/heads/stack

Evidence this is the cause and not a coincidence: `seo-tools-deploy` succeeded at
2026-09-27T03:58Z and failed at 06:46Z with no change to the role, the workflow
or its permissions in between. The rename happened in that window.

WHAT THIS WRITES, and why it is not simply the corrected literal. Pinning the new
name would break again on the next rename. Instead the name segments become
wildcards while the two immutable ids are pinned twice over -- inside `sub` and
again as their own condition keys:

    StringEquals  aud                  = sts.amazonaws.com
    StringEquals  repository_owner_id  = 319896805
    StringEquals  repository_id        = 1342943014
    StringLike    sub                  = repo:*@319896805/*@1342943014:ref:refs/heads/stack

The effective grant is unchanged: branch `stack` of repository 1342943014 owned
by 319896805, and nothing else. It is strictly tighter than the previous policy,
because ids cannot be recycled by a namespace grab whereas names can, and AWS
still sees a `sub` condition that is not solely a wildcard (IAM rejects the
policy outright if it is).

DO NOT "FIX" THE ANALYZER WARNING. `aws accessanalyzer validate-policy` reports
WILDCARD_USAGE_TOO_PERMISSIVE against this document, advising at least six literal
characters before the `*` in `sub`. There are five (`repo:`), and the only way to add more
is to start spelling out the repository OWNER NAME -- which is the exact thing that went
stale on 2026-09-27 and took two deploy roles down for 22 hours. The warning is a generic
heuristic that cannot see the two `StringEquals` id conditions sitting beside the pattern;
with `repository_id` and `repository_owner_id` both pinned, the wildcard can only ever
match names that belong to those immutable ids. Leave it, and leave this paragraph here so
the next person reading an analyzer report does not undo it. (The MISSING_RESOURCE error in
the same report is the analyzer applying resource-policy rules to a trust policy; trust
policies have no `Resource` element.)

    python scripts/fix_github_oidc_trust.py --status
    python scripts/fix_github_oidc_trust.py --apply

`--status` also audits the account for `GitHubActions-*` roles this script does NOT
manage and exits non-zero if it finds any. That check exists because ROLES is a literal:
plivo-drift was created in AWS on 2026-09-28 and sat unregistered for a day while a test
asserted the list was complete. A list that cannot notice a role someone else created is
a list that certifies its own blind spot.

`--apply` snapshots each existing trust policy to
docs/execution/snapshots/ before writing, and is idempotent: a role already
holding the target document is reported UNCHANGED and skipped.

ROLLBACK
    aws iam update-assume-role-policy --role-name <role> \
        --policy-document file://docs/execution/snapshots/<role>-trust-before-rename-repair.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "docs" / "execution" / "snapshots"

PROVIDER = "token.actions.githubusercontent.com"

# Immutable GitHub identifiers for wecare-digital/wecare-digital, confirmed from
# the REST API (`gh api repos/wecare-digital/wecare-digital`). These do not change
# on rename or transfer, which is why the policy keys on them.
OWNER_ID = "319896805"
REPO_ID = "1342943014"
BRANCH = "stack"

# The first two keep "bharat-stack" in their names on purpose: an IAM role name is
# not a repository reference and renaming it would invalidate every
# `role-to-assume` in .github/workflows. Only the trust policy was wrong.
#
# The third was created fresh on 2026-09-28 02:55 with the *correct* new repo name,
# so it was never broken - but it pinned that name with StringEquals, which is the
# same latent bug one rename away from repeating this outage. It is included so all
# three are rename-proof and auditable from one command.
#
# The fourth is the write role for public-surface-deploy.yml, added 2026-09-28 at the
# same time as that workflow. It is listed here BEFORE it exists in AWS, deliberately:
# --status reports an absent role as such and --apply skips it, whereas a role created
# later and never added here is one that silently keeps whatever trust document the
# person who created it happened to paste. That is the exact latent trap
# test_fixer_covers_every_oidc_role holds down, and a role with WRITE permissions is
# the worst one to leave out of it.
#
# The fifth is the READ-ONLY half of the same workflow, and the split is the point: the write
# role is assumed only for the two steps that write, and the confirmation afterwards runs on a
# credential that cannot. Both share this trust document - the distinction between them is
# entirely in their permission policies, not in who may assume them.
#
# The sixth, plivo-drift, is the trap actually springing rather than a hypothetical.
# `scripts/provision_ci_plivo_drift_role.py` created it in AWS on 2026-09-28 07:21 and
# nobody added it here, so for a day this list -- and the test asserting the list was
# complete -- certified a set that was missing a live role. Added 2026-09-29 after
# `aws iam list-roles` was compared against it. That comparison is no longer manual:
# `unregistered()` below does it on every --status run, because a hand-maintained
# literal cannot notice a role someone else creates, and the two roles above show how
# ordinary it is for this list to be edited by somebody who is thinking about something
# else.
ROLES = [
    "GitHubActions-bharat-stack-docs-scraper",
    # seo-tools and native-catalog were removed 2026-10-22: the CI-consolidation pass deleted
    # seo-tools-deploy.yml and native-catalog-admin-deploy.yml, so neither role is declared
    # anywhere in the repo any more. A role the repo no longer wires up must not stay registered
    # here — test_fixer_covers_every_oidc_role's reverse check fails on exactly that drift — and
    # the fixer should not keep rewriting the trust of a role nothing assumes. If either workflow
    # returns, re-add its role alongside the workflow that declares it.
    "GitHubActions-wecare-digital-route-auth",
    "GitHubActions-wecare-digital-public-surface",
    "GitHubActions-wecare-digital-public-surface-read",
    "GitHubActions-wecare-digital-plivo-drift",
    # The selected runtime-deploy role, declared by .github/workflows/runtime-deploy.yml.
    # Registered here so it gets the SAME repo-pinned OIDC trust document as every other role
    # rather than whatever its creator hand-wrote.
    "GitHubActions-wecare-runtime-deploy",
    # Dedicated least-privilege deployer for wecare-checkout, declared by checkout-deploy.yml.
    "GitHubActions-wecare-checkout-deploy",
]

# Any IAM role whose name starts with this is assumed to be a GitHub Actions OIDC role
# and therefore in scope for this script. The prefix is the convention every role in
# this account already follows.
ROLE_PREFIX = "GitHubActions"


def target_policy(account_id: str) -> dict:
    """Return the repo-pinned trust document for the caller's AWS account.

    The account id is supplied by STS at runtime rather than committed as a repository literal.
    Tests inject the account id parsed from the provisioner's existing trust document, so this
    module stays offline-testable without credentials.
    """
    provider_arn = f"arn:aws:iam::{account_id}:oidc-provider/{PROVIDER}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": provider_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{PROVIDER}:aud": "sts.amazonaws.com",
                        f"{PROVIDER}:repository_owner_id": OWNER_ID,
                        f"{PROVIDER}:repository_id": REPO_ID,
                    },
                    "StringLike": {
                        f"{PROVIDER}:sub": (
                            f"repo:*@{OWNER_ID}/*@{REPO_ID}:ref:refs/heads/{BRANCH}"
                        )
                    },
                },
            }
        ],
    }


def _canonical(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _current(iam, role: str) -> dict | None:
    try:
        return iam.get_role(RoleName=role)["Role"]["AssumeRolePolicyDocument"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        print(f"  {role}: cannot read trust policy ({code})")
        return None


def _subject(doc: dict) -> str:
    """Pull the sub condition out of a trust document, for reporting."""
    for statement in doc.get("Statement", []):
        condition = statement.get("Condition", {})
        for operator in ("StringEquals", "StringLike"):
            value = condition.get(operator, {}).get(f"{PROVIDER}:sub")
            if value:
                return f"{operator}: {value}"
    return "<no sub condition>"


def unregistered(iam) -> list[str]:
    """Live `GitHubActions-*` roles that ROLES does not mention.

    The point of this function is that ROLES is a hand-written literal, and a literal
    cannot notice a role created by someone else. That is not hypothetical: plivo-drift
    was created in AWS on 2026-09-28 and went a day unregistered, while a test asserted
    the list was exactly the set of OIDC roles. An unregistered role keeps whatever
    document its creator pasted, which is how the rename outage happened in the first
    place.

    Needs iam:ListRoles. If the caller does not have it the check is skipped with a note
    rather than failing the run -- a missing audit is not the same as drift.
    """
    known = set(ROLES)
    found: list[str] = []
    try:
        paginator = iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for role in page.get("Roles", []):
                name = role.get("RoleName", "")
                if name.startswith(ROLE_PREFIX) and name not in known:
                    found.append(name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        print(f"  (cannot list roles to audit for unregistered ones: {code})")
        return []
    return sorted(found)


def status(iam, account_id: str) -> int:
    want = target_policy(account_id)
    stale = 0
    print(f"target sub  StringLike: repo:*@{OWNER_ID}/*@{REPO_ID}:ref:refs/heads/{BRANCH}\n")
    for role in ROLES:
        doc = _current(iam, role)
        if doc is None:
            stale += 1
            continue
        matches = _canonical(doc) == _canonical(want)
        print(f"{'OK      ' if matches else 'STALE   '} {role}")
        print(f"         live  {_subject(doc)}")
        if not matches:
            stale += 1
    print(f"\n{len(ROLES) - stale}/{len(ROLES)} roles already correct")

    extra = unregistered(iam)
    if extra:
        print("\nUNREGISTERED — live OIDC roles this script does not manage. Each one keeps")
        print("whatever trust document its creator wrote, which is the rename outage waiting")
        print("to happen again. Add them to ROLES (and to the test) or explain why not:")
        for role in extra:
            print(f"  {role}")
        return 1

    return 0 if stale == 0 else 1


def apply(iam, account_id: str) -> int:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    want = target_policy(account_id)
    failures = 0

    for role in ROLES:
        doc = _current(iam, role)
        if doc is None:
            failures += 1
            continue

        if _canonical(doc) == _canonical(want):
            print(f"UNCHANGED {role} (already holds the target document)")
            continue

        snapshot = SNAPSHOTS / f"{role}-trust-before-rename-repair.json"
        if not snapshot.exists():
            snapshot.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            print(f"SNAPSHOT  {snapshot.relative_to(ROOT)}")
        else:
            print(f"SNAPSHOT  {snapshot.relative_to(ROOT)} (kept, already present)")

        try:
            iam.update_assume_role_policy(
                RoleName=role, PolicyDocument=json.dumps(want)
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            print(f"FAILED    {role}: {code}")
            failures += 1
            continue

        after = _current(iam, role)
        if after is not None and _canonical(after) == _canonical(want):
            print(f"UPDATED   {role}")
            print(f"          now   {_subject(after)}")
        else:
            print(f"FAILED    {role}: write did not verify")
            failures += 1

    # Reported here too, not only in --status. Somebody repairing drift is exactly the person
    # who should be told a role exists outside this list, and expecting them to run the other
    # subcommand as well is how the audit gets missed. It does not affect the exit code:
    # --apply's job is the roles it manages, and an unregistered role is a finding rather
    # than a failed write.
    for role in unregistered(iam):
        print(f"UNREGISTERED {role} — live but not in ROLES, so --apply did not touch it")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="report drift, change nothing")
    group.add_argument("--apply", action="store_true", help="snapshot then repair")
    args = parser.parse_args()

    iam = boto3.client("iam")
    account_id = str(boto3.client("sts").get_caller_identity()["Account"])
    return status(iam, account_id) if args.status else apply(iam, account_id)


if __name__ == "__main__":
    sys.exit(main())
