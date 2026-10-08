#!/usr/bin/env python3
"""Provision `wecare-coupons-role` and the function's log group.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` section 6.

Its OWN role, never the shared fleet role
-----------------------------------------
`wecare-digital-lambda-role` is attached to the whole fleet, so a statement added there grants
every other function the same access. Everything below is scoped to one function, one table, one
index and one secret.

What it deliberately does NOT have
----------------------------------
* No `dynamodb:Scan`. Every access in `coupon_store` is an exact-key operation or the
  `status-index` Query, and a grant nobody exercises is a grant nobody notices has gone wrong.
* Customer authentication reads and touches the session table; rate limiting updates
  only its own table. These permissions do not grant session creation or deletion.
* No `dynamodb:*`, no `DeleteTable`, no wildcard action or resource.
* No Razorpay credential read. Nothing in this function's import closure reaches a gateway.

`DeleteItem` is present for exactly one reason: releasing a `COUPONHOLD#` row. An IAM policy
cannot be narrowed below item granularity, so the restriction that actually holds is in code -
`coupon_store` has no function that deletes a `COUPON#` or a `COUPONREDEEM#` row, and
`tests/test_coupon_store.py` enumerates the delete call sites to keep it that way.

The trust policy carries `aws:SourceAccount`, so the role cannot be assumed on behalf of another
account's Lambda service principal.

Usage:
    python scripts/provision_coupons_role.py              # dry run, the default
    python scripts/provision_coupons_role.py --apply
    python scripts/provision_coupons_role.py --verify
"""

from __future__ import annotations

import argparse
import json

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"

#: The one account this project uses. Not a credential - an account id is public in every ARN
#: this repository already commits.
ACCOUNT_ID = "775261844268"

FUNCTION_NAME = "wecare-coupons"
ROLE_NAME = "wecare-coupons-role"
POLICY_NAME = "wecare-coupons-table"
LOG_GROUP = f"/aws/lambda/{FUNCTION_NAME}"
LOG_RETENTION_DAYS = 30

COUPONS_TABLE = "stack-wecare-digital-CouponsTable"
STATUS_INDEX = "status-index"
WIX_API_KEY_SECRET = "wecare/wix/headless-api-key"

#: Five actions, enumerated rather than globbed so the policy reads as the capability list it is.
TABLE_ACTIONS = ("dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                 "dynamodb:DeleteItem", "dynamodb:Query")


def table_arn() -> str:
    return f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{COUPONS_TABLE}"


def index_arn() -> str:
    return f"{table_arn()}/index/{STATUS_INDEX}"


def secret_arn() -> str:
    """The secret ARN pattern. A NAME, never a value.

    The trailing `-*` is Secrets Manager's six-character suffix, which is part of the ARN and is
    not known until the secret is created - so the wildcard is the documented way to name one
    secret, not a widening to all of them.
    """
    return f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:{WIX_API_KEY_SECRET}-*"


def trust_policy() -> dict:
    """Lambda may assume this role, but only on behalf of THIS account.

    Without `aws:SourceAccount` the Lambda service principal is a confused-deputy opening: any
    account's function could, in principle, be used to assume it.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT_ID}},
        }],
    }


def least_privilege_policy() -> dict:
    """The inline policy document, built with no AWS call.

    A pure function on purpose: `tests/test_coupons_iam_and_table.py` asserts over this exact
    document offline, so the policy that is tested is the policy that is written rather than a
    transcription of it.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CouponIssuanceTable",
                "Effect": "Allow",
                # DeleteItem is for COUPONHOLD# rows only. No Scan: every access is an exact-key
                # operation or the status-index Query.
                "Action": list(TABLE_ACTIONS),
                "Resource": [table_arn(), index_arn()],
            },
            {
                "Sid": "ValidateCustomerSession",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/stack-wecare-digital-CustomerSessionsTable"],
            },
            {
                "Sid": "CouponRateLimit",
                "Effect": "Allow",
                "Action": ["dynamodb:UpdateItem"],
                "Resource": [f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/stack-wecare-digital-RateLimitTable"],
            },
            {
                "Sid": "StaffRoleMembership",
                "Effect": "Allow",
                "Action": ["cognito-idp:AdminListGroupsForUser", "cognito-idp:AdminGetUser"],
                "Resource": [f"arn:aws:cognito-idp:{REGION}:{ACCOUNT_ID}:userpool/us-east-1_cSx0RHCIR"],
            },
            {
                "Sid": "ReadWixApiKey",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [secret_arn()],
            },
            {
                "Sid": "OwnLogGroup",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:log-group:{LOG_GROUP}",
                    f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:log-group:{LOG_GROUP}:*",
                ],
            },
        ],
    }


def iam():
    return boto3.client("iam")


def logs():
    return boto3.client("logs", region_name=REGION)


def role_exists() -> bool:
    try:
        iam().get_role(RoleName=ROLE_NAME)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchEntity", "NoSuchEntityException"):
            return False
        raise


def ensure_role(apply: bool) -> str:
    existed = role_exists()
    if not apply:
        return "exists; would reconcile the inline policy" if existed else "would create"
    if not existed:
        iam().create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
            Description="Coupon issuance and eligibility execution role",
            Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                  {"Key": "Purpose", "Value": "Coupons"}],
        )
    else:
        iam().update_assume_role_policy(RoleName=ROLE_NAME,
                                        PolicyDocument=json.dumps(trust_policy()))
    iam().put_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME,
                          PolicyDocument=json.dumps(least_privilege_policy()))
    return "reconciled" if existed else "created"


def ensure_log_group(apply: bool) -> str:
    """The function's own log group, with retention.

    Created here rather than left to Lambda's first invocation, because a group Lambda creates
    has no retention policy and keeps logs forever.
    """
    try:
        groups = logs().describe_log_groups(
            logGroupNamePrefix=LOG_GROUP, limit=50).get("logGroups", [])
        exists = any(g.get("logGroupName") == LOG_GROUP for g in groups)
    except ClientError:
        exists = False
    if not apply:
        return ("exists; would verify retention" if exists
                else f"would create with {LOG_RETENTION_DAYS}-day retention")
    if not exists:
        logs().create_log_group(logGroupName=LOG_GROUP, tags={
            "Project": "WECARE.DIGITAL", "Purpose": "Coupons"})
    logs().put_retention_policy(logGroupName=LOG_GROUP,
                                retentionInDays=LOG_RETENTION_DAYS)
    return "exists; retention verified" if exists else "created"


def verify() -> int:
    """Read the facts back off the account. Non-zero on any problem."""
    problems: list[str] = []
    if not role_exists():
        print(f"FAIL role {ROLE_NAME} does not exist")
        return 1

    role = iam().get_role(RoleName=ROLE_NAME)["Role"]
    trust = role.get("AssumeRolePolicyDocument") or {}
    if isinstance(trust, str):
        trust = json.loads(trust)
    statements = trust.get("Statement") or []
    conditions = [((s.get("Condition") or {}).get("StringEquals") or {}).get("aws:SourceAccount")
                  for s in statements]
    if conditions != [ACCOUNT_ID]:
        problems.append(f"trust policy SourceAccount is {conditions}, expected [{ACCOUNT_ID}]")

    try:
        live = iam().get_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME)
        document = live["PolicyDocument"]
        if isinstance(document, str):
            document = json.loads(document)
    except ClientError:
        print(f"FAIL inline policy {POLICY_NAME} is missing from {ROLE_NAME}")
        return 1

    expected = least_privilege_policy()
    if document != expected:
        problems.append("the live inline policy differs from this script's document")

    actions = {a for s in document.get("Statement", []) for a in s.get("Action", [])}
    for forbidden in ("dynamodb:Scan", "dynamodb:*", "*"):
        if forbidden in actions:
            problems.append(f"policy grants {forbidden}")
    resources = [r for s in document.get("Statement", []) for r in s.get("Resource", [])]
    for resource in resources:
        if resource == "*":
            problems.append("policy carries a wildcard resource")
    tables = sorted({r for r in resources if ":table/" in r})
    if tables != sorted({table_arn(), index_arn(),
                         f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/stack-wecare-digital-CustomerSessionsTable",
                         f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/stack-wecare-digital-RateLimitTable"}):
        problems.append(f"policy names {tables}, expected coupons plus bounded session and rate-limit tables")

    attached = iam().list_attached_role_policies(RoleName=ROLE_NAME).get(
        "AttachedPolicies", [])
    print(f"role: {ROLE_NAME}")
    print(f"trust SourceAccount: {conditions}")
    print(f"inline policy: {POLICY_NAME} matches this script: {document == expected}")
    print(f"actions: {sorted(actions)}")
    print(f"tables: {tables}")
    print(f"attached managed policies: {[p['PolicyArn'] for p in attached]}")

    try:
        retention = next(
            g.get("retentionInDays")
            for g in logs().describe_log_groups(logGroupNamePrefix=LOG_GROUP,
                                                limit=50).get("logGroups", [])
            if g.get("logGroupName") == LOG_GROUP)
    except StopIteration:
        retention = None
        problems.append(f"log group {LOG_GROUP} does not exist")
    print(f"log group retention: {retention}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncoupons role verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="create or reconcile; without it this is a dry run")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}\napply: {args.apply}\n")
    print(f"role: {ensure_role(args.apply)}")
    print(f"log group: {ensure_log_group(args.apply)}")
    if not args.apply:
        print("\ndry run: nothing changed")
        print(json.dumps(least_privilege_policy(), indent=2))
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
