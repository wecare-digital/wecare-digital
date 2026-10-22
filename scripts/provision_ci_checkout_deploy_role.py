#!/usr/bin/env python3
"""Define and provision the checkout-only deploy role `checkout-deploy.yml` assumes.

WHY THIS FILE EXISTS. `.github/workflows/checkout-deploy.yml` assumes
`arn:aws:iam::775261844268:role/GitHubActions-wecare-checkout-deploy` and then runs
`scripts/deploy_all_lambdas.py --dry-run wecare-checkout` (validate) and the same
without `--dry-run` (deploy). Until now that role's PERMISSION policy lived only in
the live account — nothing in the repo described it — so a missing action surfaced only
as a red CI step, which is exactly how it failed on 2026-10-22:

    Validate checkout package -> AccessDenied on lambda:GetLayerVersion for
    pillow-python312:2

The validation step resolves the Pillow layer's module list by reading the layer zip
(`layer_modules` -> `get_layer_version_by_arn` in deploy_all_lambdas.py), and the role
could not read the layer. A role whose grant is a committed, reviewable document fails
in a diff instead — which is the same reasoning behind
`scripts/provision_ci_route_auth_role.py`, whose shape this mirrors.

WHAT THE ROLE ACTUALLY DOES, and therefore what it may do. It touches exactly one
function, `wecare-checkout`, and the shared Pillow layer:

  validate (--dry-run): GetFunctionConfiguration (read current code sha / layers /
    runtime), GetLayerVersion (read the layer zip to validate PIL imports).
  deploy:   UpdateFunctionCode, then publish + alias move via snapstart_publish.py —
    PublishVersion, GetAlias, UpdateAlias — plus UpdateFunctionConfiguration for the
    layer/runtime reconcile, and GetFunctionConfiguration on `wecare-checkout:live`
    (the published-alias verify step reads the served sha).

No secretsmanager, no DynamoDB, no second function. The function-level actions are
scoped to the `wecare-checkout` ARN and its `:*` qualifiers; GetLayerVersion is scoped
to the Pillow layer ARN (every version, so a bumped layer keeps working). The role is
deliberately NOT allowed to CreateFunction or DeleteFunction — checkout already exists
and its lifecycle is not a deploy-role concern.

TRUST. Identical in shape to the route-auth role and written to agree with
`scripts/fix_github_oidc_trust.py`: GitHub OIDC provider, audience pinned, the two
numeric ids pinned as their own condition keys, name segments wildcarded inside `sub`
so a repo/owner rename cannot silently break it, branch-scoped to `stack`. Keep this
file and `fix_github_oidc_trust.py` writing the SAME trust document, or whichever runs
last wins and the rename drift returns.

    python scripts/provision_ci_checkout_deploy_role.py --plan
    python scripts/provision_ci_checkout_deploy_role.py --apply
    python scripts/provision_ci_checkout_deploy_role.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

ACCOUNT = "775261844268"
REGION = "us-east-1"
ROLE = "GitHubActions-wecare-checkout-deploy"
POLICY = "CheckoutDeploy"
OIDC_PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

OWNER_ID = "319896805"
REPO_ID = "1342943014"
OWNER = "wecare-digital"
REPO = "wecare-digital"
BRANCH = "stack"

# The one function this role deploys, and the shared layer the validation step reads.
FUNCTION = "wecare-checkout"
FUNCTION_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}"
# Every version of the Pillow layer, so a bumped `pillow-python312:N` keeps working
# without re-provisioning the role.
PILLOW_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:pillow-python312:*"

# The literal subject GitHub sends today, for reporting only — NOT what the trust matches.
SUBJECT = f"repo:{OWNER}@{OWNER_ID}/{REPO}@{REPO_ID}:ref:refs/heads/{BRANCH}"
# What the policy matches: names wildcarded, ids pinned. See the docstring and route-auth role.
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
            "Sid": "DeployCheckoutFunction",
            "Effect": "Allow",
            "Action": [
                # validate: read current code/layers/runtime, and the published-alias sha.
                "lambda:GetFunctionConfiguration",
                "lambda:GetFunction",
                "lambda:GetAlias",
                # deploy: push code, reconcile layer/runtime, publish and move `live`.
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:PublishVersion",
                "lambda:UpdateAlias",
            ],
            "Resource": [
                FUNCTION_ARN,
                f"{FUNCTION_ARN}:*",  # version/alias qualifiers (e.g. wecare-checkout:live)
            ],
        },
        {
            "Sid": "ReadPillowLayerForValidation",
            "Effect": "Allow",
            # The 2026-10-22 failure. validate resolves the Pillow layer's module list by
            # reading the layer zip; without this the PIL import check cannot run.
            "Action": "lambda:GetLayerVersion",
            "Resource": PILLOW_LAYER_ARN,
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
    print(f"permissions: deploy {FUNCTION} (+:*), GetLayerVersion on pillow-python312:*")
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
            Description=("Checkout-only deploy role for checkout-deploy.yml. Subject is "
                         "pinned by repository ID so a rename cannot break it."),
            MaxSessionDuration=3600,
        )
        print(f"created {ROLE}")

    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                        PolicyDocument=json.dumps(PERMISSIONS))
    print(f"attached inline policy {POLICY}")
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

    ids_pinned = (
        equals.get("token.actions.githubusercontent.com:repository_id") == REPO_ID
        and equals.get("token.actions.githubusercontent.com:repository_owner_id") == OWNER_ID
    ) or (REPO_ID in subject and OWNER_ID in subject)

    checks = {
        "trusts the GitHub OIDC provider":
            statement["Principal"].get("Federated") == OIDC_PROVIDER,
        "audience pinned to sts.amazonaws.com":
            equals.get("token.actions.githubusercontent.com:aud") == "sts.amazonaws.com",
        "restricted to branch stack":
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
    actions = set()
    for s in document["Statement"]:
        action = s["Action"]
        actions |= {action} if isinstance(action, str) else set(action)
    blob = json.dumps(document).lower()
    checks["grants GetLayerVersion (the 2026-10-22 gap)"] = "lambda:GetLayerVersion" in actions
    checks["grants GetFunctionConfiguration"] = "lambda:GetFunctionConfiguration" in actions
    checks["no secretsmanager grant"] = "secretsmanager" not in blob
    checks["no CreateFunction/DeleteFunction"] = not (
        "createfunction" in blob or "deletefunction" in blob)
    # Function-level writes stay scoped to wecare-checkout, never "*".
    checks["function writes scoped to wecare-checkout"] = all(
        (("*" not in (r if isinstance(r, str) else "")) or FUNCTION in (r if isinstance(r, str) else ""))
        for s in document["Statement"] if s.get("Sid") == "DeployCheckoutFunction"
        for r in ([s["Resource"]] if isinstance(s["Resource"], str) else s["Resource"]))

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
