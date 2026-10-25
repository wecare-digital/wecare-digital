#!/usr/bin/env python3
"""Replace the shared Lambda role's `secret:wecare/*` read and `function:wecare-*` invoke grants
with explicit allowlists. Approval-gated, staged, and reversible.

THE PROBLEM
-----------
`wecare-digital-lambda-role` (54 functions) can read every `wecare/*` secret (inline
`wecare-digital-lambda-permissions` Sid `SecretsManager`) and invoke every `wecare-*` function
(inline `ExtraPermissions` Sid `LambdaInvoke`, and the whole of inline `LambdaInvokePolicy`).
So any one of 54 functions, compromised, could read the OTP pepper or invoke a customer-auth or
partner function. Evidence for what the fleet actually needs (2026-10-25):
  * secrets - CloudTrail GetSecretValue for 90 days by every function under the role, plus the
    secret ids the role's function code and lambda_utils name (AST scan);
  * invokes - every deployed function name the role's function code and lambda_utils carry as a
    literal, plus the `*_FUNCTION`/`*_LAMBDA` environment routes. All 21 targets have `live`.

THE CHANGE
----------
A customer-managed policy `wecare-shared-role-scoped-access` (the inline documents are at IAM's
10,240-byte aggregate limit) holding both allowlists, then the three broad statements removed.
Order is additive first: attach, verify, and only then subtract, so no moment exists where the
fleet has less than it needs. Before-state is written to
docs/execution/snapshots/iam-lambda-role-before-scope-<date>.json; rollback restores it.

Modes (plan by default):
    (default)  print both documents, validate the policy with IAM Access Analyzer, simulate the
               role's TARGET state (SimulateCustomPolicy). Writes nothing.
    --apply --confirm I-APPROVE-SHARED-ROLE-SCOPE
    --rollback --confirm I-APPROVE-SHARED-ROLE-SCOPE-ROLLBACK
Exit: 0 ok, 10 not yet applied (plan), 1 validation/simulation failure, 2 refused.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Callable

ACCOUNT = "775261844268"
REGION = "us-east-1"
ROLE = "wecare-digital-lambda-role"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
POLICY_NAME = "wecare-shared-role-scoped-access"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/{POLICY_NAME}"
APPLY_TOKEN = "I-APPROVE-SHARED-ROLE-SCOPE"
ROLLBACK_TOKEN = "I-APPROVE-SHARED-ROLE-SCOPE-ROLLBACK"
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "docs" / "execution" / "snapshots"
SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
FUNCTION_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:"

#: Every secret a function under the role reads. Secret ARNs end in `-` + 6 random characters.
SECRETS = (
    "wecare/meta-system-user-token", "wecare/flow-private-key", "wecare/agent-connector-token",
    "wecare/razorpay/api", "wecare/razorpay-webhook", "wecare/sinch/rcs",
    "wecare/seo/google-oauth", "wecare/google/cloud", "wecare/google/ads", "wecare/bing/api",
    "wecare/plivo/api", "wecare/plivo-answer",
)
#: Per-tenant secrets wecare-partner-token-refresh creates and reads (`PARTNER_SECRET_PREFIX`).
SECRET_PREFIXES = ("wecare/partners/",)
#: Secrets that exist and that no function under the role reads: they must end up denied.
MUST_DENY_SECRETS = ("wecare/otp/pepper", "wecare/google-maps", "wecare/meta/payments",
                     "wecare/github-pat", "wecare/backup/recovery-passphrase")

#: Every function the role's code invokes. Each is granted bare and qualified (`:live`).
INVOKE_TARGETS = tuple(f"wecare-{name}" for name in (
    "ai-generate-response", "ai-query-kb", "billing", "bulk-worker", "checkout", "commerce",
    "inbound-whatsapp", "meta-catalog-sync", "outbound-email", "outbound-sms",
    "outbound-whatsapp", "razorpay-webhook", "rcs-send", "scheduled-messages", "secure-files",
    "service-requests", "sms-aws", "voice-aws", "voice-cdr-read", "whatsapp-business-api",
    "whatsapp-voice"))
#: Functions that exist and that nothing under the role may invoke.
MUST_DENY_INVOKES = ("wecare-customer-registration", "wecare-customer-whatsapp-auth",
                     "wecare-partner-onboarding", "wecare-contacts")

#: The statements this change removes, exactly as they are live. Anything else there is drift
#: and the change refuses rather than guess.
BROAD_SECRETS = ("wecare-digital-lambda-permissions", "SecretsManager",
                 ["secretsmanager:GetSecretValue"], [f"{SECRET_ARN}wecare/*"])
BROAD_INVOKE = ("ExtraPermissions", "LambdaInvoke",
                ["lambda:InvokeFunction"], [f"{FUNCTION_ARN}wecare-*"])
BROAD_INVOKE_POLICY = "LambdaInvokePolicy"  # one statement, the same broad invoke: deleted

#: Unrelated grants that must survive the edit to the two documents it rewrites.
MUST_KEEP = (
    ("dynamodb:GetItem", f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-InvoicesTable"),
    ("s3:GetObject", "arn:aws:s3:::wecare-digital-get/o/x.png"),
    ("social-messaging:ListLinkedWhatsAppBusinessAccounts", "*"),
    ("cloudwatch:PutMetricData", "*"),
)


def scoped_document() -> dict:
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": "ReadFleetSecrets", "Effect": "Allow",
         "Action": ["secretsmanager:GetSecretValue"],
         "Resource": [f"{SECRET_ARN}{name}-??????" for name in SECRETS]
         + [f"{SECRET_ARN}{prefix}*" for prefix in SECRET_PREFIXES]},
        {"Sid": "InvokeFleetFunctions", "Effect": "Allow",
         "Action": ["lambda:InvokeFunction"],
         "Resource": [arn for name in INVOKE_TARGETS
                      for arn in (f"{FUNCTION_ARN}{name}", f"{FUNCTION_ARN}{name}:*")]},
    ]}


def _norm(value) -> list:
    return [value] if isinstance(value, str) else list(value or [])


def _is(statement: dict, sid: str, actions: list, resources: list) -> bool:
    return (statement.get("Sid") == sid and statement.get("Effect") == "Allow"
            and sorted(_norm(statement.get("Action"))) == sorted(actions)
            and sorted(_norm(statement.get("Resource"))) == sorted(resources)
            and not statement.get("Condition"))


def without(document: dict, spec: tuple) -> tuple[dict | None, str]:
    """`document` minus the one statement `spec` names, or (None, why) when it is not there."""
    _, sid, actions, resources = spec
    matches = [s for s in document["Statement"] if _is(s, sid, actions, resources)]
    if len(matches) != 1:
        return None, f"expected exactly one {sid} statement {actions} on {resources}"
    out = copy.deepcopy(document)
    out["Statement"] = [s for s in document["Statement"] if not _is(s, sid, actions, resources)]
    return out, ""


def _secret_probe(name: str, real: dict[str, str]) -> str:
    return real.get(name) or f"{SECRET_ARN}{name}-AbC123"


class Scope:
    def __init__(self, iam, analyzer, sts, secrets, *, out: Callable[[str], None] = print,
                 sleep: Callable[[float], None] = time.sleep):
        self.iam, self.analyzer, self.sts, self.secrets = iam, analyzer, sts, secrets
        self.out, self.sleep = out, sleep

    # ── reads ──
    def account_ok(self) -> bool:
        account = self.sts.get_caller_identity().get("Account")
        if account != ACCOUNT:
            self.out(f"REFUSED: caller account {account!r} is not {ACCOUNT}")
            return False
        return True

    def inline(self) -> dict[str, dict]:
        return {name: self.iam.get_role_policy(RoleName=ROLE, PolicyName=name)["PolicyDocument"]
                for name in self.iam.list_role_policies(RoleName=ROLE)["PolicyNames"]}

    def managed(self) -> dict[str, dict]:
        docs = {}
        for attached in self.iam.list_attached_role_policies(RoleName=ROLE)["AttachedPolicies"]:
            arn = attached["PolicyArn"]
            version = self.iam.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
            docs[arn] = self.iam.get_policy_version(PolicyArn=arn, VersionId=version)[
                "PolicyVersion"]["Document"]
        return docs

    def real_secret_arns(self) -> dict[str, str]:
        """Name -> ARN from ListSecrets: metadata only, never a value."""
        arns, kwargs = {}, {"MaxResults": 100, "Filters": [{"Key": "name", "Values": ["wecare/"]}]}
        for _ in range(10):
            page = self.secrets.list_secrets(**kwargs)
            for entry in page.get("SecretList", []):
                arns[entry["Name"]] = entry["ARN"]
            if not page.get("NextToken"):
                break
            kwargs["NextToken"] = page["NextToken"]
        return arns

    def target_inline(self, live: dict[str, dict]) -> tuple[dict[str, dict] | None, str]:
        """The inline documents after the change, or (None, why) on drift."""
        target = dict(live)
        for spec in (BROAD_SECRETS, BROAD_INVOKE):
            if spec[0] not in live:
                return None, f"inline policy {spec[0]} is missing"
            edited, why = without(live[spec[0]], spec)
            if edited is None:
                return None, f"{spec[0]}: {why}"
            target[spec[0]] = edited
        invoke_only = live.get(BROAD_INVOKE_POLICY)
        if invoke_only is not None:
            rest, why = without(invoke_only, (BROAD_INVOKE_POLICY,) + BROAD_INVOKE[1:])
            if rest is None or rest["Statement"]:
                return None, f"{BROAD_INVOKE_POLICY} is no longer only the broad invoke"
            del target[BROAD_INVOKE_POLICY]
        return target, ""

    # ── checks ──
    def cases(self, real: dict[str, str]) -> list[tuple[str, str, str, str]]:
        cases = [("secretsmanager:GetSecretValue", _secret_probe(n, real), "allowed", n)
                 for n in SECRETS]
        cases += [("secretsmanager:GetSecretValue", f"{SECRET_ARN}{p}tenant-1-AbC123", "allowed",
                   f"{p}*") for p in SECRET_PREFIXES]
        cases += [("secretsmanager:GetSecretValue", _secret_probe(n, real), "denied", n)
                  for n in MUST_DENY_SECRETS]
        for name in INVOKE_TARGETS:
            cases.append(("lambda:InvokeFunction", f"{FUNCTION_ARN}{name}", "allowed", name))
            cases.append(("lambda:InvokeFunction", f"{FUNCTION_ARN}{name}:live", "allowed",
                          f"{name}:live"))
        for name in MUST_DENY_INVOKES:
            cases.append(("lambda:InvokeFunction", f"{FUNCTION_ARN}{name}:live", "denied",
                          f"{name}:live"))
        cases += [(action, arn, "allowed", f"keep {action}") for action, arn in MUST_KEEP]
        return cases

    def run_cases(self, evaluate: Callable[[str, str], str], real: dict[str, str]) -> list[str]:
        bad = []
        for action, arn, expect, label in self.cases(real):
            got = "allowed" if evaluate(action, arn) == "allowed" else "denied"
            if got != expect:
                bad.append(label)
            self.out(f"  {'ok ' if got == expect else 'BAD'} {action:32s} {label} -> {expect}"
                     f"{'' if got == expect else f' (got {got})'}")
        return bad

    def simulate_target(self, live: dict[str, dict], real: dict[str, str]) -> list[str]:
        target, why = self.target_inline(live)
        if target is None:
            self.out(f"  DRIFT: {why}")
            return ["drift"]
        managed = {arn: doc for arn, doc in self.managed().items() if arn != POLICY_ARN}
        docs = [json.dumps(d) for d in [*target.values(), *managed.values(), scoped_document()]]
        return self.run_cases(lambda action, arn: self.iam.simulate_custom_policy(
            PolicyInputList=docs, ActionNames=[action], ResourceArns=[arn],
            ContextEntries=[{"ContextKeyName": "aws:SecureTransport", "ContextKeyValues": ["true"],
                             "ContextKeyType": "boolean"}],
        )["EvaluationResults"][0]["EvalDecision"], real)

    def simulate_live(self, real: dict[str, str]) -> list[str]:
        return self.run_cases(lambda action, arn: self.iam.simulate_principal_policy(
            PolicySourceArn=ROLE_ARN, ActionNames=[action], ResourceArns=[arn],
            ContextEntries=[{"ContextKeyName": "aws:SecureTransport", "ContextKeyValues": ["true"],
                             "ContextKeyType": "boolean"}],
        )["EvaluationResults"][0]["EvalDecision"], real)

    def validate(self) -> list[str]:
        findings = self.analyzer.validate_policy(policyDocument=json.dumps(scoped_document()),
                                                 policyType="IDENTITY_POLICY").get("findings", [])
        for f in findings:
            self.out(f"  access-analyzer {f.get('findingType')} {f.get('issueCode')}")
        return [f.get("issueCode", "?") for f in findings
                if f.get("findingType") in {"ERROR", "SECURITY_WARNING"}]

    def attached(self) -> bool:
        return any(a["PolicyArn"] == POLICY_ARN for a in
                   self.iam.list_attached_role_policies(RoleName=ROLE)["AttachedPolicies"])

    def broad_removed(self, live: dict[str, dict]) -> bool:
        return (BROAD_INVOKE_POLICY not in live
                and not any(_is(s, *BROAD_SECRETS[1:]) for s in
                            live.get(BROAD_SECRETS[0], {}).get("Statement", []))
                and not any(_is(s, *BROAD_INVOKE[1:]) for s in
                            live.get(BROAD_INVOKE[0], {}).get("Statement", [])))

    def _policy_exists(self) -> bool:
        try:
            self.iam.get_policy(PolicyArn=POLICY_ARN)
            return True
        except self.iam.exceptions.NoSuchEntityException:
            return False

    # ── modes ──
    def plan(self) -> int:
        if not self.account_ok():
            return 2
        live = self.inline()
        if self.attached() and self.broad_removed(live):
            self.out("COMPLIANT: scoped policy attached and broad statements removed")
            self.out("simulate live role:")
            return 1 if self.simulate_live(self.real_secret_arns()) else 0
        self.out(json.dumps(scoped_document(), indent=2))
        self.out(f"scoped policy: {len(json.dumps(scoped_document(), separators=(',', ':')))} "
                 "bytes (managed limit 6,144)")
        self.out("validate (IAM Access Analyzer):")
        bad = self.validate()
        self.out("simulate role TARGET state (SimulateCustomPolicy):")
        bad += self.simulate_target(live, self.real_secret_arns())
        if bad:
            self.out("PLAN FAILED")
            return 1
        self.out(f"NOT APPLIED. Apply with --apply --confirm {APPLY_TOKEN}")
        return 10

    def apply(self, confirm: str | None) -> int:
        if confirm != APPLY_TOKEN:
            self.out(f"REFUSED: --apply needs --confirm {APPLY_TOKEN}")
            return 2
        if not self.account_ok():
            return 2
        real = self.real_secret_arns()
        live = self.inline()
        if self.validate() or self.simulate_target(live, real):
            self.out("REFUSED: validation/simulation of the target state failed")
            return 1
        target, why = self.target_inline(live)
        if target is None:
            self.out(f"REFUSED: {why}")
            return 1
        snapshot = SNAPSHOTS / f"iam-lambda-role-before-scope-{dt.date.today():%Y%m%d}.json"
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(json.dumps({"role": ROLE, "inline": {
                name: live[name] for name in (BROAD_SECRETS[0], BROAD_INVOKE[0], BROAD_INVOKE_POLICY)
                if name in live}}, indent=2) + "\n")
            self.out(f"before-state written to {snapshot.relative_to(ROOT)}")

        # 1. Additive: the allowlists, beside the broad grants.
        if not self._policy_exists():
            self.iam.create_policy(
                PolicyName=POLICY_NAME, PolicyDocument=json.dumps(scoped_document()),
                Description="Secrets and functions wecare-digital-lambda-role functions use",
                Tags=[{"Key": "Project", "Value": "WECARE.DIGITAL"},
                      {"Key": "Purpose", "Value": "least-privilege"}])
            self.out(f"create_policy {POLICY_ARN}")
        if not self.attached():
            self.iam.attach_role_policy(RoleName=ROLE, PolicyArn=POLICY_ARN)
            self.out(f"attach_role_policy {POLICY_ARN}")

        # 2. Subtractive, re-reading first so a concurrent edit is never overwritten.
        live = self.inline()
        target, why = self.target_inline(live)
        if target is None:
            self.out(f"STOPPED after attach (additive only, safe): {why}")
            return 1
        for name in (BROAD_SECRETS[0], BROAD_INVOKE[0]):
            self.iam.put_role_policy(RoleName=ROLE, PolicyName=name,
                                     PolicyDocument=json.dumps(target[name]))
            self.out(f"put_role_policy {name} (broad statement removed)")
        if BROAD_INVOKE_POLICY in live:
            self.iam.delete_role_policy(RoleName=ROLE, PolicyName=BROAD_INVOKE_POLICY)
            self.out(f"delete_role_policy {BROAD_INVOKE_POLICY}")

        for _ in range(6):  # IAM is eventually consistent
            self.sleep(10)
            self.out("simulate live role (SimulatePrincipalPolicy):")
            if not self.simulate_live(real):
                self.out("APPLIED AND VERIFIED")
                return 0
        self.out(f"APPLIED BUT NOT VERIFIED; roll back with --rollback --confirm {ROLLBACK_TOKEN}")
        return 1

    def rollback(self, confirm: str | None) -> int:
        if confirm != ROLLBACK_TOKEN:
            self.out(f"REFUSED: --rollback needs --confirm {ROLLBACK_TOKEN}")
            return 2
        if not self.account_ok():
            return 2
        snapshots = sorted(SNAPSHOTS.glob("iam-lambda-role-before-scope-*.json"))
        if not snapshots:
            self.out("REFUSED: no before-state snapshot to restore")
            return 2
        before = json.loads(snapshots[-1].read_text())["inline"]
        for name, document in before.items():  # restore first, then remove the allowlists
            self.iam.put_role_policy(RoleName=ROLE, PolicyName=name,
                                     PolicyDocument=json.dumps(document))
            self.out(f"put_role_policy {name} (restored from {snapshots[-1].name})")
        if self.attached():
            self.iam.detach_role_policy(RoleName=ROLE, PolicyArn=POLICY_ARN)
            self.out(f"detach_role_policy {POLICY_ARN}")
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

    tool = Scope(boto3.client("iam"), boto3.client("accessanalyzer", region_name=REGION),
                 boto3.client("sts", region_name=REGION),
                 boto3.client("secretsmanager", region_name=REGION))
    if args.rollback:
        return tool.rollback(args.confirm)
    if args.apply:
        return tool.apply(args.confirm)
    return tool.plan()


if __name__ == "__main__":
    sys.exit(main())
