#!/usr/bin/env python3
"""Define and provision the exact-scope deploy role `runtime-deploy.yml` assumes.

WHY THIS FILE EXISTS. `.github/workflows/runtime-deploy.yml` assumes
`arn:aws:iam::775261844268:role/GitHubActions-wecare-runtime-deploy` and runs
`scripts/deploy_all_lambdas.py --dry-run <15 functions>` (validate) then the same
without `--dry-run` (deploy). That role's PERMISSION policy lived only in the live
account — nothing in the repo described it — so a missing action surfaced only as a red
CI step, which is how it failed on 2026-10-22:

    Package validation against live configuration -> AccessDenied on
    lambda:GetFunctionConfiguration for three functions.

The first thing `deploy_all_lambdas.py` does per target is
`get_function_configuration` (read current sha, layers, runtime), and the role could
not read three of its own targets. A role whose grant is a committed, reviewable
document fails in a diff instead — the same reasoning as
`scripts/provision_ci_route_auth_role.py`, whose shape this mirrors.

WHAT THE ROLE DOES, and therefore what it may do. It deploys the FUNCTIONS list below
(the exact set runtime-deploy.yml passes), and nothing else:

  validate (--dry-run): GetFunctionConfiguration / GetFunction (current code, layers,
    runtime), GetLayerVersion (read the Pillow layer zip for the PIL import check on the
    image functions), and GetFunctionConfiguration on `wecare-checkout:live` — the
    payment-config sync copies two non-secret merchant expectations from the published
    checkout into invoice-engine/outbound before publishing.
  deploy:   UpdateFunctionCode, UpdateFunctionConfiguration (layer/runtime/payment-env
    reconcile), and publish + alias move via snapstart_publish.py — PublishVersion,
    GetAlias, UpdateAlias.

No secretsmanager, no DynamoDB. Function-level actions are scoped to the listed
function ARNs and their `:*` qualifiers; GetLayerVersion is scoped to the Pillow layer.
The role may not CreateFunction or DeleteFunction — every target already exists and its
lifecycle is owned elsewhere. `wecare-checkout:live` is readable (for the payment-config
sync) but checkout itself is deployed by the dedicated
`scripts/provision_ci_checkout_deploy_role.py`; it is in this list too because
runtime-deploy.yml publishes it first for the /invoices strangler ordering, so the ARN
is included.

TRUST. Identical in shape to the route-auth role and written to agree with
`scripts/fix_github_oidc_trust.py`: GitHub OIDC provider, audience pinned, both numeric
ids pinned as their own condition keys, name segments wildcarded inside `sub` so a
rename cannot silently break it, branch-scoped to `stack`. Keep this file and
`fix_github_oidc_trust.py` writing the SAME trust document.

    python scripts/provision_ci_runtime_deploy_role.py --plan
    python scripts/provision_ci_runtime_deploy_role.py --apply
    python scripts/provision_ci_runtime_deploy_role.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

ACCOUNT = "775261844268"
REGION = "us-east-1"
ROLE = "GitHubActions-wecare-runtime-deploy"
POLICY = "RuntimeDeploy"
OIDC_PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

OWNER_ID = "319896805"
REPO_ID = "1342943014"
OWNER = "wecare-digital"
REPO = "wecare-digital"
BRANCH = "stack"

# The exact function set runtime-deploy.yml passes to deploy_all_lambdas.py. Keep this in
# step with that workflow: a function added there but not here fails validation on its
# first GetFunctionConfiguration, which is the 2026-10-22 failure mode.
FUNCTIONS = (
    "wecare-ai-generate-response",
    "wecare-contacts",
    "wecare-secure-files",
    "wecare-service-api",
    "wecare-messages-read",
    "wecare-customer-whatsapp-auth",
    "wecare-inbound-whatsapp",
    "wecare-outbound-whatsapp",
    "wecare-whatsapp-business-api",
    "wecare-whatsapp-template-management",
    "wecare-checkout",
    "wecare-product-image-gen",
    "wecare-meta-catalog-sync",
    "wecare-razorpay-webhook",
    "wecare-invoice-engine",
)


def _fn_arns() -> list[str]:
    arns: list[str] = []
    for name in FUNCTIONS:
        base = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
        arns.append(base)
        arns.append(base + ":*")  # version/alias qualifiers, e.g. wecare-checkout:live
    return arns


# Every version of the Pillow layer, so a bumped `pillow-python312:N` keeps working.
PILLOW_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:pillow-python312:*"

SUBJECT = f"repo:{OWNER}@{OWNER_ID}/{REPO}@{REPO_ID}:ref:refs/heads/{BRANCH}"
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
            "Sid": "DeployRuntimeFunctions",
            "Effect": "Allow",
            "Action": [
                # validate: read current code/layers/runtime (and checkout:live for the
                # payment-config sync). The 2026-10-22 gap was GetFunctionConfiguration.
                "lambda:GetFunctionConfiguration",
                "lambda:GetFunction",
                "lambda:GetAlias",
                # deploy: push code, reconcile layer/runtime/payment-env, publish, move alias.
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:PublishVersion",
                "lambda:UpdateAlias",
            ],
            "Resource": _fn_arns(),
        },
        {
            "Sid": "ReadPillowLayerForValidation",
            "Effect": "Allow",
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
    print(f"permissions: deploy {len(FUNCTIONS)} functions (+:*), "
          f"GetLayerVersion on pillow-python312:*")
    for name in FUNCTIONS:
        print(f"    {name}")
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
            Description=("Exact-scope runtime deploy role for runtime-deploy.yml. Subject is "
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
    checks["grants GetFunctionConfiguration (the 2026-10-22 gap)"] = (
        "lambda:GetFunctionConfiguration" in actions)
    checks["grants GetLayerVersion"] = "lambda:GetLayerVersion" in actions
    checks["no secretsmanager grant"] = "secretsmanager" not in blob
    checks["no CreateFunction/DeleteFunction"] = not (
        "createfunction" in blob or "deletefunction" in blob)
    # No function-level statement may use a bare "*" resource.
    checks["function writes are not wildcard-resource"] = all(
        r != "*"
        for s in document["Statement"] if s.get("Sid") == "DeployRuntimeFunctions"
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
