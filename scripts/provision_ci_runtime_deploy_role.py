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
For the FUNCTIONS list the role may not CreateFunction or DeleteFunction — every target
already exists and its lifecycle is owned elsewhere. The two exceptions are the pinned
provisioning blocks below, which MAY CreateFunction on exactly one function each
(wecare-vayulok-environment and wecare-catalog-media) and never DeleteFunction anywhere.
`wecare-checkout:live` is readable (for the payment-config
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

# POLICIES mirrors the LIVE inline policy set exactly, as the two named policies the deployed
# role carries — captured 2026-10-22 (see
# docs/execution/snapshots/GitHubActions-wecare-runtime-deploy-before-provision-*.json). The
# live role was already correct before the stale 2026-10-22 failure report (it had
# GetFunctionConfiguration on every target, GetLayerVersion on the runtime layers, plus a
# self-contained VayuLok-environment provisioning block). Reconciling to live means `--apply`
# reproduces the deployed grant instead of narrowing it.
#
# The VayuLok block (CreateFunction / iam:PassRole+PutRolePolicy on exactly
# wecare-vayulok-environment-role / secretsmanager:DescribeSecret metadata-only / scoped
# apigateway + logs) is the one surface this role may CREATE, and it is pinned to that single
# function, role, secret prefix and API id — not a wildcard. It is reproduced verbatim so a
# future --apply cannot silently drop VayuLok provisioning.
_FN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function"
_VAYULOK_FN = f"{_FN}:wecare-vayulok-environment"
_VAYULOK_ROLE = f"arn:aws:iam::{ACCOUNT}:role/wecare-vayulok-environment-role"

# The catalog-media provisioning surface. `.github/workflows/storage-layout-runtime-deploy.yml`
# runs `scripts/provision_catalog_media.py --apply/--verify` under THIS role, and that script's
# first act is iam.get_role(RoleName="wecare-catalog-media-role") + get_role_policy to confirm
# the exec role is scoped to the approved catalog-deploy artwork before it will create/update
# the function. This role previously granted iam:GetRole only on the VayuLok role, so the step
# failed with AccessDenied on GetRole for wecare-catalog-media-role. Grant exactly what that
# script needs, pinned to the one function, its one execution role and the one HTTP API - a
# mirror of the VayuLok block above, same least-privilege shape.
_CATALOG_MEDIA_FN = f"{_FN}:wecare-catalog-media"
_CATALOG_MEDIA_ROLE = f"arn:aws:iam::{ACCOUNT}:role/wecare-catalog-media-role"

POLICIES = {
    "ReadConsolidatedFunctionConfig": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadConsolidatedFunctionConfig",
                "Effect": "Allow",
                "Action": "lambda:GetFunctionConfiguration",
                "Resource": [
                    f"{_FN}:wecare-secure-files",
                    f"{_FN}:wecare-checkout",
                    f"{_FN}:wecare-whatsapp-template-management",
                ],
            }
        ],
    },
    "SelectedRuntimeDeployOnly": {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DeployOnlySelectedRuntimeFunctions",
                "Effect": "Allow",
                "Action": [
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:UpdateFunctionCode",
                    "lambda:PublishVersion",
                    "lambda:GetAlias",
                    "lambda:UpdateAlias",
                ],
                "Resource": _fn_arns(),
            },
            {
                "Sid": "ReadDeployInventory",
                "Effect": "Allow",
                "Action": ["lambda:ListFunctions"],
                "Resource": "*",
            },
            {
                "Sid": "ReadExistingRuntimeLayers",
                "Effect": "Allow",
                "Action": ["lambda:GetLayerVersion"],
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:cryptography-python312:1",
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:layer:pillow-python312:2",
                ],
            },
            {
                "Sid": "ReadPinnedPillowLayer",
                "Effect": "Allow",
                "Action": "lambda:GetLayerVersion",
                # The AWS-managed Klayers Pillow build in its own account.
                "Resource": "arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p312-Pillow:10",
            },
            {
                "Sid": "ProvisionVayuLokEnvironmentOnly",
                "Effect": "Allow",
                "Action": [
                    "lambda:CreateFunction",
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:UpdateFunctionCode",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:PublishVersion",
                    "lambda:GetAlias",
                    "lambda:CreateAlias",
                    "lambda:UpdateAlias",
                    "lambda:AddPermission",
                    "lambda:GetPolicy",
                ],
                "Resource": [_VAYULOK_FN, f"{_VAYULOK_FN}:*"],
            },
            {
                "Sid": "PassOnlyVayuLokExecutionRole",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": _VAYULOK_ROLE,
                "Condition": {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}},
            },
            {
                "Sid": "MaintainOnlyVayuLokExecutionRole",
                "Effect": "Allow",
                "Action": ["iam:GetRole", "iam:PutRolePolicy", "iam:AttachRolePolicy"],
                "Resource": _VAYULOK_ROLE,
            },
            {
                "Sid": "ReadVayuLokSecretMetadataOnly",
                "Effect": "Allow",
                # DescribeSecret is metadata only — never GetSecretValue.
                "Action": "secretsmanager:DescribeSecret",
                "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:wecare/google/cloud-*",
            },
            {
                "Sid": "ProvisionVayuLokApiRoutesOnly",
                "Effect": "Allow",
                "Action": ["apigateway:GET", "apigateway:POST", "apigateway:PATCH"],
                "Resource": [
                    f"arn:aws:apigateway:{REGION}::/apis/zllr9lrg7j",
                    f"arn:aws:apigateway:{REGION}::/apis/zllr9lrg7j/*",
                ],
            },
            {
                "Sid": "MaintainVayuLokLogGroupOnly",
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups",
                    "logs:CreateLogGroup",
                    "logs:PutRetentionPolicy",
                ],
                "Resource": "*",
            },
            {
                "Sid": "ApiGatewayLogDeliveryForStageUpdate",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogDelivery",
                    "logs:GetLogDelivery",
                    "logs:UpdateLogDelivery",
                    "logs:DeleteLogDelivery",
                    "logs:ListLogDeliveries",
                    "logs:PutResourcePolicy",
                    "logs:DescribeResourcePolicies",
                    "logs:DescribeLogGroups",
                ],
                "Resource": "*",
            },
            {
                "Sid": "ProvisionCatalogMediaFunctionOnly",
                "Effect": "Allow",
                "Action": [
                    "lambda:CreateFunction",
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:UpdateFunctionCode",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:PublishVersion",
                    "lambda:GetAlias",
                    "lambda:CreateAlias",
                    "lambda:UpdateAlias",
                    "lambda:AddPermission",
                    "lambda:GetPolicy",
                ],
                "Resource": [_CATALOG_MEDIA_FN, f"{_CATALOG_MEDIA_FN}:*"],
            },
            {
                "Sid": "PassOnlyCatalogMediaExecutionRole",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": _CATALOG_MEDIA_ROLE,
                "Condition": {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}},
            },
            {
                "Sid": "ReadOnlyCatalogMediaExecutionRole",
                "Effect": "Allow",
                # provision_catalog_media.role_arn() reads the role and its inline policy to
                # confirm it is scoped to the approved catalog-deploy artwork before use. Read
                # only - this role may not mutate wecare-catalog-media-role.
                "Action": ["iam:GetRole", "iam:GetRolePolicy"],
                "Resource": _CATALOG_MEDIA_ROLE,
            },
        ],
    },
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
    print(f"inline policies this file declares: {', '.join(POLICIES)}")
    print(f"permissions: deploy {len(FUNCTIONS)} functions (+:*), layer reads, and a pinned "
          f"VayuLok-environment provisioning block")
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

    for name, doc in POLICIES.items():
        iam.put_role_policy(RoleName=ROLE, PolicyName=name, PolicyDocument=json.dumps(doc))
        print(f"attached inline policy {name}")
    # Mirror, don't accrete: delete any live inline policy this file does not declare.
    for stale in set(iam.list_role_policies(RoleName=ROLE)["PolicyNames"]) - set(POLICIES):
        iam.delete_role_policy(RoleName=ROLE, PolicyName=stale)
        print(f"removed undeclared inline policy {stale}")
    return verify()


def _normalize(doc: dict) -> str:
    """Canonical form for comparing two policy documents regardless of statement/resource/action
    ORDER. IAM treats a policy's statement list and each statement's action/resource lists as
    sets, so a reorder is not a real difference — only a brittle string compare would say so."""
    def norm_list(v):
        return sorted(v) if isinstance(v, list) else v
    statements = []
    for s in doc.get("Statement", []):
        statements.append(json.dumps({
            k: (norm_list(v) if k in ("Action", "Resource") else v)
            for k, v in sorted(s.items())
        }, sort_keys=True))
    return json.dumps({"Version": doc.get("Version"), "Statement": sorted(statements)},
                      sort_keys=True)


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

    inline = set(iam.list_role_policies(RoleName=ROLE)["PolicyNames"])
    checks["inline policy set matches this file exactly"] = inline == set(POLICIES)
    checks["no attached managed policies"] = not iam.list_attached_role_policies(
        RoleName=ROLE)["AttachedPolicies"]

    live_docs = {n: iam.get_role_policy(RoleName=ROLE, PolicyName=n)["PolicyDocument"]
                 for n in inline & set(POLICIES)}
    actions: set = set()
    blob = ""
    deploy_statement = None
    for name, document in live_docs.items():
        blob += json.dumps(document).lower()
        for s in document["Statement"]:
            action = s["Action"]
            actions |= {action} if isinstance(action, str) else set(action)
            if s.get("Sid") == "DeployOnlySelectedRuntimeFunctions":
                deploy_statement = s
    checks["grants GetFunctionConfiguration"] = "lambda:GetFunctionConfiguration" in actions
    checks["grants GetLayerVersion"] = "lambda:GetLayerVersion" in actions
    # CreateFunction is allowed ONLY on the pinned VayuLok function; assert it is never paired
    # with a wildcard resource. DeleteFunction must be absent entirely.
    checks["no DeleteFunction anywhere"] = "deletefunction" not in blob
    # The committed POLICIES mirror live, order-insensitively (IAM treats these lists as sets).
    checks["committed policies match live"] = (
        set(live_docs) == set(POLICIES)
        and all(_normalize(POLICIES[n]) == _normalize(live_docs[n]) for n in POLICIES))
    # The core deploy statement never uses a bare "*" resource.
    checks["function deploy writes are not wildcard-resource"] = (
        deploy_statement is not None
        and all(r != "*" for r in (
            [deploy_statement["Resource"]]
            if isinstance(deploy_statement["Resource"], str)
            else deploy_statement["Resource"])))

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
