#!/usr/bin/env python3
"""Approval-gated explicit Deny that keeps three unneeded secrets away from the shared role.

`wecare-digital-lambda-role` (61 functions) allowed `secretsmanager:GetSecretValue` on
`secret:wecare/*` until 2026-10-25, when scripts/scope_shared_lambda_role.py replaced that with an
allowlist; this Deny stays as a second line. CloudTrail (90 days, 2026-10-15) shows no role
under it ever read these:

    wecare/github-pat                 readers: wecare-workspace-mcp-runtime (own role), a since-
                                      deleted webhook receiver role, root, iamuser wecare-admin
    wecare/backup/recovery-passphrase readers: root, iamuser wecare-admin
    wecare/aws/iam-access-keys        readers: root, iamuser wecare-admin

so an explicit Deny for exactly these three removes them from 61 functions without touching the
allow list the functions do use. The guard is a customer-managed policy
(`wecare-shared-role-secret-guard`, IAM is free) attached to the role: the role's inline policies
are already at IAM's 10,240-byte aggregate limit (PutRolePolicy LimitExceeded, 2026-10-15), and
no existing document is modified. Rollback detaches and deletes the guard.

Modes (plan by default):
    (default)  show the guard, validate it with IAM Access Analyzer and simulate it together with
               the role's current policies (SimulateCustomPolicy). Writes nothing.
    --apply --confirm I-APPROVE-SHARED-ROLE-SECRET-GUARD
    --rollback --confirm I-APPROVE-SHARED-ROLE-SECRET-GUARD-ROLLBACK   (detach + delete)
Exit: 0 ok, 10 guard not yet applied (plan), 1 validation/simulation failure, 2 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Callable

ACCOUNT = "775261844268"
REGION = "us-east-1"
ROLE = "wecare-digital-lambda-role"
POLICY_NAME = "wecare-shared-role-secret-guard"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/{POLICY_NAME}"
APPLY_TOKEN = "I-APPROVE-SHARED-ROLE-SECRET-GUARD"
ROLLBACK_TOKEN = "I-APPROVE-SHARED-ROLE-SECRET-GUARD-ROLLBACK"
SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
DENIED = ("wecare/github-pat", "wecare/backup/recovery-passphrase", "wecare/aws/iam-access-keys")
#: Secrets functions under the shared role do read; they must stay readable. The same list
#: scripts/scope_shared_lambda_role.py grants. `wecare/otp/pepper` left it on 2026-10-25: its
#: readers (customer-registration, customer-profile, email-verification) run on their own roles.
STILL_ALLOWED = ("wecare/razorpay/api", "wecare/razorpay-webhook", "wecare/meta-system-user-token",
                 "wecare/flow-private-key", "wecare/sinch/rcs", "wecare/agent-connector-token",
                 "wecare/seo/google-oauth", "wecare/google/cloud", "wecare/google/ads",
                 "wecare/bing/api", "wecare/plivo/api", "wecare/plivo-answer")


def guard_document() -> dict:
    return {"Version": "2012-10-17", "Statement": [{
        "Sid": "DenySecretsNoSharedRoleFunctionReads",
        "Effect": "Deny",
        "Action": ["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"],
        "Resource": [f"{SECRET_ARN}{name}-??????" for name in DENIED],
    }]}


def _probe(name: str) -> str:
    # Secret ARNs end in a 6-character random suffix; the probe uses a fixed one.
    return f"{SECRET_ARN}{name}-AbC123"


class Guard:
    def __init__(self, iam, analyzer, sts, *, out: Callable[[str], None] = print,
                 sleep: Callable[[float], None] = time.sleep):
        self.iam, self.analyzer, self.sts, self.out, self.sleep = iam, analyzer, sts, out, sleep

    def guard_ok(self) -> bool:
        account = self.sts.get_caller_identity().get("Account")
        if account != ACCOUNT:
            self.out(f"REFUSED: caller account {account!r} is not {ACCOUNT}")
            return False
        return True

    def role_documents(self, with_guard: bool) -> list[dict]:
        docs = {}
        for name in self.iam.list_role_policies(RoleName=ROLE)["PolicyNames"]:
            docs[name] = self.iam.get_role_policy(RoleName=ROLE, PolicyName=name)["PolicyDocument"]
        for attached in self.iam.list_attached_role_policies(RoleName=ROLE)["AttachedPolicies"]:
            arn = attached["PolicyArn"]
            if arn.startswith("arn:aws:iam::aws:") or arn == POLICY_ARN:
                continue  # AWS-managed VPC/X-Ray policies grant no Secrets Manager access
            version = self.iam.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
            docs[arn] = self.iam.get_policy_version(PolicyArn=arn, VersionId=version)[
                "PolicyVersion"]["Document"]
        if with_guard:
            docs[POLICY_ARN] = guard_document()
        return list(docs.values())

    def cases(self) -> list[tuple[str, str]]:
        return ([(n, "denied") for n in DENIED] + [(n, "allowed") for n in STILL_ALLOWED])

    def simulate(self, evaluate: Callable[[str], str]) -> list[str]:
        bad = []
        for name, expect in self.cases():
            got = "allowed" if evaluate(_probe(name)) == "allowed" else "denied"
            self.out(f"  {'ok ' if got == expect else 'BAD'} GetSecretValue {name} -> {expect}"
                     f" (got {got})")
            if got != expect:
                bad.append(name)
        return bad

    def simulate_target(self) -> list[str]:
        policies = [json.dumps(d) for d in self.role_documents(with_guard=True)]
        return self.simulate(lambda arn: self.iam.simulate_custom_policy(
            PolicyInputList=policies, ActionNames=["secretsmanager:GetSecretValue"],
            ResourceArns=[arn])["EvaluationResults"][0]["EvalDecision"])

    def simulate_live(self) -> list[str]:
        return self.simulate(lambda arn: self.iam.simulate_principal_policy(
            PolicySourceArn=f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
            ActionNames=["secretsmanager:GetSecretValue"],
            ResourceArns=[arn])["EvaluationResults"][0]["EvalDecision"])

    def validate(self) -> list[str]:
        findings = self.analyzer.validate_policy(policyDocument=json.dumps(guard_document()),
                                                 policyType="IDENTITY_POLICY").get("findings", [])
        for f in findings:
            self.out(f"  access-analyzer {f.get('findingType')} {f.get('issueCode')}")
        return [f.get("issueCode", "?") for f in findings
                if f.get("findingType") in {"ERROR", "SECURITY_WARNING"}]

    def applied(self) -> bool:
        attached = self.iam.list_attached_role_policies(RoleName=ROLE)["AttachedPolicies"]
        return any(a["PolicyArn"] == POLICY_ARN for a in attached)

    def _policy_exists(self) -> bool:
        try:
            self.iam.get_policy(PolicyArn=POLICY_ARN)
            return True
        except Exception as error:  # noqa: BLE001
            if "NoSuchEntity" in type(error).__name__ or "NoSuchEntity" in str(error):
                return False
            raise

    def plan(self) -> int:
        if not self.guard_ok():
            return 2
        self.out(json.dumps(guard_document(), indent=2))
        self.out("validate (IAM Access Analyzer):")
        bad = self.validate()
        self.out("simulate role + guard (SimulateCustomPolicy):")
        bad += self.simulate_target()
        if bad:
            self.out("PLAN FAILED")
            return 1
        if self.applied():
            self.out("COMPLIANT: guard already attached")
            return 0
        self.out(f"NOT APPLIED. Apply with --apply --confirm {APPLY_TOKEN}")
        return 10

    def apply(self, confirm: str | None) -> int:
        if confirm != APPLY_TOKEN:
            self.out(f"REFUSED: --apply needs --confirm {APPLY_TOKEN}")
            return 2
        if not self.guard_ok():
            return 2
        if self.validate() or self.simulate_target():
            self.out("REFUSED: guard failed validation/simulation")
            return 1
        if not self._policy_exists():
            self.iam.create_policy(
                PolicyName=POLICY_NAME, PolicyDocument=json.dumps(guard_document()),
                Description="Deny three secrets no wecare-digital-lambda-role function reads",
                Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                      {"Key": "Purpose", "Value": "secret-isolation"}])
            self.out(f"create_policy {POLICY_ARN}")
        if not self.applied():
            self.iam.attach_role_policy(RoleName=ROLE, PolicyArn=POLICY_ARN)
            self.out(f"attach_role_policy {ROLE} {POLICY_ARN}")
        for attempt in range(6):
            bad = self.simulate_live()
            if not bad:
                self.out("APPLIED AND VERIFIED (SimulatePrincipalPolicy)")
                return 0
            self.sleep(10)
        self.out(f"APPLIED BUT NOT VERIFIED; roll back with --rollback --confirm {ROLLBACK_TOKEN}")
        return 1

    def rollback(self, confirm: str | None) -> int:
        if confirm != ROLLBACK_TOKEN:
            self.out(f"REFUSED: --rollback needs --confirm {ROLLBACK_TOKEN}")
            return 2
        if not self.guard_ok():
            return 2
        if self.applied():
            self.iam.detach_role_policy(RoleName=ROLE, PolicyArn=POLICY_ARN)
            self.out(f"detach_role_policy {ROLE} {POLICY_ARN}")
        if self._policy_exists():
            self.iam.delete_policy(PolicyArn=POLICY_ARN)
            self.out(f"delete_policy {POLICY_ARN}")
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    import boto3

    tool = Guard(boto3.client("iam"), boto3.client("accessanalyzer", region_name=REGION),
                 boto3.client("sts", region_name=REGION))
    if args.rollback:
        return tool.rollback(args.confirm)
    if args.apply:
        return tool.apply(args.confirm)
    return tool.plan()


if __name__ == "__main__":
    sys.exit(main())
