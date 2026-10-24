#!/usr/bin/env python3
"""Create the OIDC role that `plivo-drift.yml` needs, scoped to one secret.

WHY THIS WAS HELD BACK, AND WHAT CHANGED. `plivo-drift.yml` is guarded by
`if: vars.PLIVO_DRIFT_ROLE_ARN != ''` and that variable has never been set, so the drift
job has reported SKIPPED since it was written -- the same failure mode as
`route-auth.yml`'s live gate, where absence is indistinguishable from a pass in the
checks list.

Unlike route-auth, this job needs `secretsmanager:GetSecretValue`. Granting GitHub
Actions the ability to read a live provider credential genuinely widens who can read it,
so it sat outside the standing grant and was reported as an owner decision rather than
done quietly. It is created here under explicit authorisation.

WHAT KEEPS IT NARROW. Three things, all asserted by `--verify`:

1. **One secret, by ARN.** `wecare/plivo/api` only -- the id
   `scripts/plivo_control_plane.py` actually reads. Not `wecare/plivo`, not
   `wecare/plivo-answer`, not a wildcard. A `Deny` on every other secret ARN backs the
   allow, so a future widening of the allow statement still fails.
2. **Read only.** `GetSecretValue`, `DescribeSecret`, and `kms:Decrypt` on the one key
   that secret is encrypted with. No `Put`, no `Update`, no `Delete`, no `List` -- the role
   cannot even discover what other secrets exist. The decrypt is conditioned on
   `kms:ViaService` so it cannot be used against KMS directly, and a second `Deny` holds it
   to that single key.
3. **Branch `wecare.digital` of this repository, by numeric ID.** `repo:*@319896805/*@1342943014:
   ref:refs/heads/wecare.digital` plus `repository_id` / `repository_owner_id` as their own
   condition keys. Names are excluded deliberately: the rename on 2026-09-27 broke every
   policy that pinned a name, and ids cannot be recycled by a namespace grab.

The drift job is read-only by construction -- it compares live Plivo configuration
against the committed expectation and reports -- so this grant cannot mutate either side.

THE KMS HOP, ADDED 2026-09-29. The role as first created on 2026-09-28 held both Secrets
Manager read verbs and still could not read the secret, because `wecare/plivo/api` is
encrypted with a customer-managed key and Secrets Manager performs that decrypt with the
CALLER's credentials. The job's first real run failed with `AccessDeniedException: Access
to KMS is not allowed` and -- because `plivo-reconcile` returned the same exit code for a
failed init as for CRITICAL drift -- reported it as live call routing having moved. Both
halves are fixed: `kms:Decrypt` is granted here, and the exit codes are now distinct.

    python scripts/provision_ci_plivo_drift_role.py --plan
    python scripts/provision_ci_plivo_drift_role.py --apply
    python scripts/provision_ci_plivo_drift_role.py --verify
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
ROLE = "GitHubActions-wecare-digital-plivo-drift"
POLICY = "PlivoSecretReadOnly"
OIDC_PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

OWNER_ID = "319896805"
REPO_ID = "1342943014"
BRANCH = "wecare.digital"

#: The exact secret `scripts/plivo_control_plane.py` reads (`SECRET_ID`). The trailing
#: `-??????` matches Secrets Manager's 6-character suffix without widening to a prefix
#: match, so `wecare/plivo/api-anything-else` cannot satisfy it.
SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:wecare/plivo/api-??????"

#: The customer-managed key that encrypts `wecare/plivo/api` -- `alias/wecare-secrets-manager`,
#: `KeyManager: CUSTOMER`. THIS IS THE LINE THE ROLE WAS MISSING, and its absence is why the
#: drift job failed on the first run where it was actually used (2026-09-28):
#:
#:     could not initialise Plivo control plane: An error occurred (AccessDeniedException)
#:     when calling the GetSecretValue operation: Access to KMS is not allowed
#:
#: `GetSecretValue` on a CMK-encrypted secret is TWO authorisations, not one. Secrets Manager
#: does not decrypt with its own privileges; it re-calls KMS with the CALLER's, so a role
#: holding every Secrets Manager read verb and no `kms:Decrypt` is denied at the second hop.
#: On a secret left under the AWS-managed `aws/secretsmanager` key the same policy works,
#: which is exactly why the gap is easy to write and invisible until the first real run.
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/9b5b8734-9968-4464-90a9-329dad12c1a9"

#: `kms:ViaService` restricts the decrypt to requests KMS received FROM Secrets Manager, so
#: the grant cannot be used to decrypt anything by calling KMS directly. It mirrors the
#: `UseOnlyViaSecretsManager` statement already in the key policy, which is also why no key
#: policy change is needed here: that statement allows the account root principal, which
#: delegates the decision to IAM, so this document is the only place that has to change.
SECRETS_MANAGER_SERVICE = f"secretsmanager.{REGION}.amazonaws.com"

# NO `Sid` HERE, and that is the whole point of the missing line. Three files write this
# same trust document -- this one, scripts/provision_ci_route_auth_role.py and
# scripts/fix_github_oidc_trust.py -- and fix_github_oidc_trust.py compares what is live
# against its own document BYTE FOR BYTE to decide whether a role is stale. A `Sid` that
# only this file emitted made that comparison fail: the fixer would report this role STALE,
# rewrite it without the Sid, and the next `--apply` here would put it back. Two scripts
# fighting over one role, each correct on its own terms, is exactly the drift
# tests/test_github_oidc_trust_policy.py exists to prevent, so the Sid went rather than
# being propagated into the other two. The statement is identified by being the only one.
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
                    "token.actions.githubusercontent.com:repository_id": REPO_ID,
                    "token.actions.githubusercontent.com:repository_owner_id": OWNER_ID,
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub":
                        f"repo:*@{OWNER_ID}/*@{REPO_ID}:ref:refs/heads/{BRANCH}",
                },
            },
        }
    ],
}

PERMISSIONS = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ReadOnlyThePlivoApiSecret",
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            "Resource": SECRET_ARN,
        },
        {
            # The second half of that read. See KMS_KEY_ARN above: without this statement
            # the allow above is decorative, because the secret is CMK-encrypted and the
            # decrypt happens with this role's credentials.
            #
            # `kms:Decrypt` alone -- not `GenerateDataKey`, which is the write side of the
            # same key and is what Secrets Manager needs when it STORES a value. A reader
            # that cannot generate a data key cannot re-encrypt a new secret version.
            "Sid": "DecryptOnlyViaSecretsManager",
            "Effect": "Allow",
            "Action": "kms:Decrypt",
            "Resource": KMS_KEY_ARN,
            "Condition": {"StringEquals": {"kms:ViaService": SECRETS_MANAGER_SERVICE}},
        },
        {
            # Belt and braces: even if the allow above is widened by accident, this keeps
            # the role to the one secret it was created for.
            "Sid": "DenyEveryOtherSecret",
            "Effect": "Deny",
            "Action": "secretsmanager:*",
            "NotResource": SECRET_ARN,
        },
        {
            # The same belt and braces on the KMS side. The CMK is shared by every
            # `wecare/*` secret, so a widened decrypt would be a decrypt for all of them --
            # this keeps the blast radius at one key even then, and the Deny above keeps it
            # at one secret, so the two compose into "this role reads one credential".
            "Sid": "DenyEveryOtherKey",
            "Effect": "Deny",
            "Action": "kms:*",
            "NotResource": KMS_KEY_ARN,
        },
    ],
}


def _iam():
    return boto3.client("iam", region_name=REGION)


def _exists(iam) -> bool:
    try:
        iam.get_role(RoleName=ROLE)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchEntity":
            return False
        raise


def plan() -> int:
    iam = _iam()
    print(f"role   {ROLE}: {'EXISTS' if _exists(iam) else 'ABSENT'}")
    print(f"secret {SECRET_ARN}")
    print(f"key    {KMS_KEY_ARN}")
    print("actions: secretsmanager:GetSecretValue, DescribeSecret (+ Deny on all others)")
    print(f"         kms:Decrypt via {SECRETS_MANAGER_SERVICE} (+ Deny on all other keys)")
    variables = subprocess.run(["gh", "variable", "list"], capture_output=True, text=True)
    print(f"repo variables now:\n{variables.stdout.strip() or '  (none)'}")
    return 0


def apply() -> int:
    iam = _iam()
    if _exists(iam):
        iam.update_assume_role_policy(RoleName=ROLE, PolicyDocument=json.dumps(TRUST))
        print(f"updated trust on {ROLE}")
    else:
        iam.create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(TRUST),
            Description=("Read-only role for plivo-drift.yml. Scoped to "
                         "secretsmanager:GetSecretValue on wecare/plivo/api plus "
                         "kms:Decrypt on that secret's key via Secrets Manager only. "
                         "Subject pinned by repository ID."),
            MaxSessionDuration=3600,
        )
        print(f"created {ROLE}")

    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY,
                        PolicyDocument=json.dumps(PERMISSIONS))
    print(f"attached inline policy {POLICY}")

    arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    result = subprocess.run(["gh", "variable", "set", "PLIVO_DRIFT_ROLE_ARN",
                             "--body", arn], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh variable set failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"set repository variable PLIVO_DRIFT_ROLE_ARN = {arn}")
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
    document = iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
    rendered = json.dumps(document)
    allow = [s for s in document["Statement"] if s["Effect"] == "Allow"]
    deny = [s for s in document["Statement"] if s["Effect"] == "Deny"]
    secret_allow = [s for s in allow if s.get("Resource") == SECRET_ARN]
    kms_allow = [s for s in allow if s.get("Resource") == KMS_KEY_ARN]

    def actions(statement) -> set:
        raw = statement["Action"]
        return {raw} if isinstance(raw, str) else set(raw)

    #: Every action this role is permitted to hold, as a closed set. Asserting membership
    #: rather than a `secretsmanager:` prefix is the point: the prefix test used to stand in
    #: for "reads one credential and can do nothing else", and adding the KMS hop made the
    #: prefix false while leaving the real property true. A closed set survives that.
    permitted = {"secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret",
                 "kms:Decrypt"}

    checks = {
        "trusts the GitHub OIDC provider":
            statement["Principal"].get("Federated") == OIDC_PROVIDER,
        "audience pinned":
            equals.get("token.actions.githubusercontent.com:aud") == "sts.amazonaws.com",
        "repository_id pinned":
            equals.get("token.actions.githubusercontent.com:repository_id") == REPO_ID,
        "repository_owner_id pinned":
            equals.get("token.actions.githubusercontent.com:repository_owner_id") == OWNER_ID,
        "subject restricted to refs/heads/wecare.digital":
            like.get("token.actions.githubusercontent.com:sub", "").endswith(
                f":ref:refs/heads/{BRANCH}"),
        "subject is not a bare wildcard":
            like.get("token.actions.githubusercontent.com:sub") != "*",
        "one inline policy only":
            iam.list_role_policies(RoleName=ROLE)["PolicyNames"] == [POLICY],
        "no managed policies attached":
            not iam.list_attached_role_policies(RoleName=ROLE)["AttachedPolicies"],
        "allow covers exactly the plivo api secret":
            len(secret_allow) == 1,
        "secret allow is read-only":
            len(secret_allow) == 1 and actions(secret_allow[0]) == {
                "secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"},
        # Without this the secret allow above is decorative: the secret is CMK-encrypted, so
        # GetSecretValue is denied at the KMS hop. This check is here because that is how the
        # role shipped on 2026-09-28 and nothing caught it until CI ran.
        "can decrypt the key that secret is encrypted with":
            len(kms_allow) == 1 and actions(kms_allow[0]) == {"kms:Decrypt"},
        "the decrypt is only reachable through secrets manager":
            len(kms_allow) == 1
            and kms_allow[0].get("Condition", {}).get("StringEquals", {}).get(
                "kms:ViaService") == SECRETS_MANAGER_SERVICE,
        "no allow beyond those two":
            len(allow) == 2,
        "a Deny backs it for every other secret":
            any(d.get("NotResource") == SECRET_ARN for d in deny),
        "a Deny backs it for every other key":
            any(d.get("NotResource") == KMS_KEY_ARN for d in deny),
        "no write verb anywhere":
            not any(v in rendered.lower()
                    for v in ("putsecret", "updatesecret", "deletesecret",
                              "createsecret", "rotatesecret", "tagresource",
                              "generatedatakey", "kms:encrypt", "reencrypt")),
        "cannot list or discover other secrets":
            "listsecrets" not in rendered.lower(),
        "every allowed action is on the permitted read list":
            all(a in permitted for s in allow for a in actions(s)),
        "no wildcard action or resource in any allow":
            not any("*" in a for s in allow for a in actions(s))
            and not any("*" in str(s.get("Resource", "")) for s in allow),
    }

    variables = subprocess.run(["gh", "variable", "list"], capture_output=True, text=True)
    checks["PLIVO_DRIFT_ROLE_ARN is set"] = "PLIVO_DRIFT_ROLE_ARN" in variables.stdout

    for name, ok in checks.items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
        if not ok:
            problems.append(name)

    if problems:
        print(f"\n{len(problems)} check(s) failed: {problems}", file=sys.stderr)
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
