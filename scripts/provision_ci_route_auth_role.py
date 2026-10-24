#!/usr/bin/env python3
"""Create the read-only OIDC role that `route-auth.yml`'s live-AWS job needs.

WHY IT WAS NEVER RUNNING. `.github/workflows/route-auth.yml` has two jobs. The
source-scanning half runs on every push and blocks. The `live-gate` half is guarded
by `if: vars.ROUTE_AUTH_ROLE_ARN != ''`, and that repository variable has never been
set -- `gh variable list` returns nothing -- so the job has silently reported
"skipped" since the day it was written. The guard is the right design (a fork must
not go red for a reason a contributor cannot fix), but it means the absence looks
identical to a pass in the checks list. Only the console-drift half can catch a
route added straight in the console, which is exactly the class of change the
source scan is blind to.

THE SUBJECT CLAIM CARRIES BOTH IDS AND NAMES, AND ONLY THE IDS SURVIVE A RENAME.
Corrected 2026-09-28 against measured evidence. This docstring previously claimed the
ID-qualified subject "survives a rename" and that the two older roles "kept working"
through it. **Both halves were wrong**, and the error was load-bearing, because it
justified pinning the whole subject string with `StringEquals`.

GitHub's immutable subject format is

    repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH

The ids survive a rename. The NAME segments are still in the string and do not. So
when the repo became `wecare-digital/wecare-digital` on 2026-09-27, the two older
roles -- `GitHubActions-bharat-stack-docs-scraper` and `-seo-tools` -- stopped
working immediately, exactly like the Amplify app did. They failed with

    Not authorized to perform sts:AssumeRoleWithWebIdentity

from 06:46 on 2026-09-27 until repaired on 2026-09-28. `seo-tools-deploy` succeeded
at 03:58Z and failed at 06:46Z that day with no change to the role, the workflow or
its permissions -- the rename is the only event in the window. So the Amplify app was
not the only name-pinned casualty; it was merely the loudest.

Consequence for this script: pinning the corrected NAME would be the same bug one
rename later, and re-running `--apply` with a name-pinned document would silently
revert the hardening applied by `scripts/fix_github_oidc_trust.py`. The trust
document below therefore wildcards the name segments and pins the ids twice -- inside
`sub` via `StringLike`, and again as their own `repository_id` /
`repository_owner_id` conditions. The effective grant is identical to the
name-pinned form and strictly tighter, because ids cannot be recycled by a namespace
grab whereas freed names can. IAM still sees a `sub` condition that is not solely a
wildcard, which it rejects outright.

Keep this file and `scripts/fix_github_oidc_trust.py` writing the SAME document, or
whichever runs last wins and the drift returns.

PERMISSIONS. Exactly the four calls `audit_route_auth.py` makes --
`apigatewayv2:GET` on the API collection plus `lambda:ListFunctions` -- and nothing
else. No `secretsmanager`, no write verb anywhere. `apigatewayv2:GET` is the one
coarse action the service offers for reads; it cannot mutate.

    python scripts/provision_ci_route_auth_role.py --plan
    python scripts/provision_ci_route_auth_role.py --apply
    python scripts/provision_ci_route_auth_role.py --verify
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

ACCOUNT = "775261844268"
REGION = "us-east-1"
ROLE = "GitHubActions-wecare-digital-route-auth"
POLICY = "RouteAuthReadOnly"
OIDC_PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

OWNER_ID = "319896805"
REPO_ID = "1342943014"
OWNER = "wecare-digital"
REPO = "wecare-digital"
BRANCH = "wecare.digital"

# The literal subject GitHub sends today, kept for reporting in --plan/--verify so a
# reader can see the concrete string. It is NOT what the trust policy matches.
SUBJECT = f"repo:{OWNER}@{OWNER_ID}/{REPO}@{REPO_ID}:ref:refs/heads/{BRANCH}"

# What the policy actually matches: names wildcarded, ids pinned. See the docstring.
SUBJECT_PATTERN = f"repo:*@{OWNER_ID}/*@{REPO_ID}:ref:refs/heads/{BRANCH}"

TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Federated": OIDC_PROVIDER},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    "token.actions.githubusercontent.com:repository_owner_id": OWNER_ID,
                    "token.actions.githubusercontent.com:repository_id": REPO_ID,
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": SUBJECT_PATTERN,
                },
            },
        }
    ],
}

PERMISSIONS = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ReadHttpApiTopology",
            "Effect": "Allow",
            # apigatewayv2 exposes reads as the single coarse action `GET`. It covers
            # get_apis / get_routes / get_integrations and can mutate nothing.
            "Action": "apigateway:GET",
            "Resource": f"arn:aws:apigateway:{REGION}::/apis*",
        },
        {
            "Sid": "ListFunctionsOnly",
            "Effect": "Allow",
            "Action": "lambda:ListFunctions",
            "Resource": "*",
        },
    ],
}


def _iam():
    return boto3.client("iam", region_name=REGION)


def _role_exists(iam) -> bool:
    try:
        iam.get_role(RoleName=ROLE)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchEntity":
            return False
        raise


def plan() -> int:
    iam = _iam()
    print(f"role   {ROLE}: {'EXISTS' if _role_exists(iam) else 'ABSENT'}")
    print(f"subject GitHub sends: {SUBJECT}")
    print(f"subject matched      : {SUBJECT_PATTERN}  (StringLike)")
    print("permissions: apigateway:GET on /apis*, lambda:ListFunctions")
    existing = subprocess.run(["gh", "variable", "list"], capture_output=True, text=True)
    print(f"repo variables now: {existing.stdout.strip() or '(none)'}")
    return 0


def apply() -> int:
    iam = _iam()

    if _role_exists(iam):
        iam.update_assume_role_policy(RoleName=ROLE, PolicyDocument=json.dumps(TRUST))
        print(f"updated trust policy on {ROLE}")
    else:
        iam.create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(TRUST),
            Description=("Read-only role for route-auth.yml's live-AWS drift job. "
                         "Subject is pinned by repository ID so a rename cannot break it."),
            MaxSessionDuration=3600,
        )
        print(f"created {ROLE}")

    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                        PolicyDocument=json.dumps(PERMISSIONS))
    print(f"attached inline policy {POLICY}")

    arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    # A role ARN is not a secret -- it grants nothing without the OIDC trust -- so it
    # belongs in a repository VARIABLE rather than a secret, which is also what the
    # workflow's `vars.` reference expects.
    result = subprocess.run(["gh", "variable", "set", "ROUTE_AUTH_ROLE_ARN", "--body", arn],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh variable set failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"set repository variable ROUTE_AUTH_ROLE_ARN = {arn}")
    return verify()


def verify() -> int:
    iam = _iam()
    problems = []

    try:
        role = iam.get_role(RoleName=ROLE)["Role"]
    except ClientError as exc:
        print(f"role missing: {exc.response['Error']['Code']}", file=sys.stderr)
        return 1

    statement = role["AssumeRolePolicyDocument"]["Statement"][0]
    equals = statement.get("Condition", {}).get("StringEquals", {})
    like = statement.get("Condition", {}).get("StringLike", {})
    subject = str(equals.get("token.actions.githubusercontent.com:sub")
                  or like.get("token.actions.githubusercontent.com:sub") or "")

    # Relaxed 2026-09-28 from an exact-string match on `sub`. `fix_github_oidc_trust.py`
    # rewrote this role, and every other OIDC role, to pin the two numeric ids as their
    # OWN condition keys and wildcard the name segments inside `sub` -- which is strictly
    # tighter, because ids cannot be recycled by a namespace grab whereas names can. An
    # exact-literal assertion called that improvement a failure. What has to hold is the
    # PROPERTY (this repo, this owner, branch wecare.digital), not one spelling of it.
    ids_pinned = (
        equals.get("token.actions.githubusercontent.com:repository_id") == REPO_ID
        and equals.get("token.actions.githubusercontent.com:repository_owner_id") == OWNER_ID
    ) or (REPO_ID in subject and OWNER_ID in subject)

    checks = {
        "trusts the GitHub OIDC provider":
            statement["Principal"].get("Federated") == OIDC_PROVIDER,
        "audience pinned to sts.amazonaws.com":
            equals.get("token.actions.githubusercontent.com:aud") == "sts.amazonaws.com",
        "restricted to branch wecare.digital":
            subject.endswith(f":ref:refs/heads/{BRANCH}"),
        "subject is not a bare wildcard":
            subject not in ("*", ""),
        "both numeric ids are pinned":
            ids_pinned,
    }

    inline = iam.list_role_policies(RoleName=ROLE)["PolicyNames"]
    checks["only the one inline policy"] = inline == [POLICY]
    checks["no attached managed policies"] = not iam.list_attached_role_policies(
        RoleName=ROLE)["AttachedPolicies"]

    document = iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
    actions = {s["Action"] if isinstance(s["Action"], str) else tuple(s["Action"])
               for s in document["Statement"]}
    checks["grants exactly the two read actions"] = actions == {
        "apigateway:GET", "lambda:ListFunctions"}
    checks["no write verb anywhere"] = not any(
        verb in json.dumps(document).lower()
        for verb in ("put", "delete", "update", "create", "invoke"))
    checks["no secretsmanager grant"] = "secretsmanager" not in json.dumps(document).lower()

    variables = subprocess.run(["gh", "variable", "list"], capture_output=True, text=True)
    checks["ROUTE_AUTH_ROLE_ARN is set"] = "ROUTE_AUTH_ROLE_ARN" in variables.stdout

    for name, ok in checks.items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
        if not ok:
            problems.append(name)

    if problems:
        print(f"\n{len(problems)} check(s) failed", file=sys.stderr)
        return 1
    print("\nall checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply:
        return apply()
    if args.verify:
        return verify()
    return plan()


if __name__ == "__main__":
    raise SystemExit(main())
