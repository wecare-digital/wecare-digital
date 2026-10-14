#!/usr/bin/env python3
"""Build the Secrets Manager access matrix from live METADATA only. Read-only.

For every secret (planned deletions included) this reports who can actually read it, so a
consolidation decision rests on measured access instead of names:

* IAM readers: every non-service-linked role whose inline or customer-managed statements allow
  `secretsmanager:GetSecretValue` (or a wildcard) on a resource pattern matching the secret ARN.
* Lambda consumers: functions running under those roles, plus functions whose environment names
  the secret by reference (the env KEY is reported, never the value).
* Source references: tracked files under amplify/functions, scripts and .github naming the secret.

Never calls GetSecretValue / BatchGetSecretValue. The candidate action column is policy from this
file (`POLICY`), not inferred from values; anything unlisted is NEEDS_OWNER_REVIEW.

    python scripts/secrets_access_matrix.py --markdown docs/migrations/secrets-access-matrix.md
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
ACCOUNT = "775261844268"
READ_ACTIONS = ("secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue")

#: name -> (security domain, candidate action, rationale). Policy, reviewed by a human.
POLICY: dict[str, tuple[str, str, str]] = {
    "wecare/razorpay/api": ("payments", "KEEP_ISOLATED", "payment gateway API credentials"),
    "wecare/razorpay-webhook": ("payments", "KEEP_ISOLATED", "webhook signature verification secret"),
    "wecare/meta/payments": ("payments", "KEEP_ISOLATED", "payment configuration; owner to confirm which fields are secret"),
    "wecare/meta-system-user-token": ("integrations/meta", "KEEP_ISOLATED", "Graph system-user token and app secret"),
    "wecare/flow-private-key": ("security", "KEEP_ISOLATED", "WhatsApp Flows RSA private key"),
    "wecare/otp/pepper": ("security", "KEEP_ISOLATED", "OTP hashing pepper"),
    "wecare/backup/recovery-passphrase": ("security", "KEEP_ISOLATED", "disaster-recovery passphrase"),
    "wecare/aws/iam-access-keys": ("security", "NEEDS_OWNER_REVIEW", "stored long-lived AWS keys; replace with role-based temporary credentials, then retire"),
    "wecare/github-pat": ("security", "ROTATE", "classic near-full-scope PAT, description says EXPOSED 2026-08-25; replace with a fine-grained token or GitHub App"),
    "wecare/plivo/api": ("communications", "KEEP_ISOLATED", "voice provider API credentials"),
    "wecare/plivo-answer": ("communications", "NEEDS_OWNER_REVIEW", "same provider as plivo/api; group only if every reader needs both and rotation matches"),
    "wecare/sinch/rcs": ("communications", "KEEP_ISOLATED", "RCS provider credentials"),
    "wecare/truecaller": ("communications", "KEEP_ISOLATED", "identity callback credentials"),
    "wecare/agent-connector-token": ("integrations", "NEEDS_OWNER_REVIEW", "identify the consumer before any action"),
    "wecare/seo/google-oauth": ("seo", "KEEP_ISOLATED", "Google OAuth client"),
    "wecare/google/ads": ("integrations", "KEEP_ISOLATED", "Google Ads credentials"),
    "wecare/google/cloud": ("integrations", "KEEP_ISOLATED", "GCP service-account key"),
    "wecare/bing/api": ("seo", "NEEDS_OWNER_REVIEW", "confirm an active consumer exists"),
    "wecare/config/webhook-registry": ("integrations", "NEEDS_OWNER_REVIEW", "MOVE_TO_PARAMETER_STORE only if the owner confirms no field is secret"),
}


def _list(value):
    return value if isinstance(value, list) else ([value] if value is not None else [])


def _statements(document) -> list[dict]:
    return _list(document.get("Statement")) if isinstance(document, dict) else []


def _allows_read(statement: dict) -> bool:
    if statement.get("Effect") != "Allow" or "Action" not in statement:
        return False
    return any(fnmatch.fnmatchcase(action, pattern) for pattern in _list(statement["Action"])
               for action in READ_ACTIONS)


def role_documents(iam) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for page in iam.get_paginator("list_roles").paginate():
        for role in page["Roles"]:
            if role.get("Path", "/").startswith("/aws-service-role/"):
                continue
            name, docs = role["RoleName"], []
            for p in iam.get_paginator("list_role_policies").paginate(RoleName=name):
                for pname in p["PolicyNames"]:
                    docs.append(iam.get_role_policy(RoleName=name, PolicyName=pname)
                                ["PolicyDocument"])
            for p in iam.get_paginator("list_attached_role_policies").paginate(RoleName=name):
                for attached in p["AttachedPolicies"]:
                    arn = attached["PolicyArn"]
                    if arn.startswith("arn:aws:iam::aws:"):
                        continue
                    version = iam.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
                    docs.append(iam.get_policy_version(PolicyArn=arn, VersionId=version)
                                ["PolicyVersion"]["Document"])
            out[name] = docs
    return out


def readers_of(secret_arn: str, documents: dict[str, list[dict]]) -> list[str]:
    readers = []
    for role, docs in documents.items():
        for doc in docs:
            if any(_allows_read(st) and any(fnmatch.fnmatchcase(secret_arn, r)
                                            for r in _list(st.get("Resource")))
                   for st in _statements(doc)):
                readers.append(role)
                break
    return sorted(readers)


def source_references(name: str) -> list[str]:
    result = subprocess.run(["git", "grep", "-l", "-F", name, "--", "amplify/functions",
                             "scripts", ".github"], cwd=ROOT, capture_output=True, text=True)
    return [p for p in result.stdout.splitlines() if p and not p.endswith(".md")]


def build(secrets, documents, functions) -> list[dict]:
    by_role: dict[str, list[str]] = {}
    for fn in functions:
        by_role.setdefault(fn["Role"].split("/")[-1], []).append(fn["FunctionName"])
    rows = []
    for s in sorted(secrets, key=lambda x: x["Name"]):
        name, arn = s["Name"], s["ARN"]
        roles = readers_of(arn, documents)
        env_refs = sorted(
            f"{fn['FunctionName']}.{key}" for fn in functions
            for key, value in ((fn.get("Environment") or {}).get("Variables") or {}).items()
            if isinstance(value, str) and value in (name, arn))
        domain, action, why = POLICY.get(name, ("unclassified", "NEEDS_OWNER_REVIEW",
                                                "not in the reviewed policy table"))
        if s.get("DeletedDate"):
            action, why = "SCHEDULED_DELETION", "already scheduled; not billed, not a new saving"
        elif not roles and not env_refs and action not in {"ROTATE"}:
            why += "; no IAM reader measured, candidate RETIRE_AFTER_OWNER_CONFIRMATION"
        rows.append({
            "name": name, "domain": domain, "action": action, "rationale": why,
            "iam_reader_roles": roles,
            "consumers_by_role": {r: sorted(by_role.get(r, [])) for r in roles},
            "lambda_consumers": sorted({f for r in roles for f in by_role.get(r, [])}),
            "env_references": env_refs,
            "source_files": source_references(name),
            "last_accessed": str(s.get("LastAccessedDate") or "")[:10],
            "last_changed": str(s.get("LastChangedDate") or "")[:10],
            "rotation": bool(s.get("RotationEnabled")),
            "kms": "aws/secretsmanager" if not s.get("KmsKeyId") or
                   s["KmsKeyId"] == "alias/aws/secretsmanager" else "CMK " +
                   s["KmsKeyId"].split("/")[-1][:8],
            "scheduled_deletion": str(s.get("DeletedDate") or "")[:10],
        })
    return rows


def to_markdown(rows: list[dict], when: str) -> str:
    active = [r for r in rows if not r["scheduled_deletion"]]
    lines = [
        "# Secrets access matrix", "",
        f"Generated {when} by `scripts/secrets_access_matrix.py` from live metadata only "
        "(ListSecrets, IAM policy documents, Lambda configuration). No secret value was read.", "",
        f"Active: **{len(active)}**. Scheduled for deletion: **{len(rows) - len(active)}** "
        "(not billed; not counted as new savings).", "",
        "IAM readers = roles whose policies allow `secretsmanager:GetSecretValue` on a pattern "
        "matching the secret ARN. A Lambda consumer is a function running under such a role.", "",
        "| Secret | Domain | Action | IAM reader roles | Lambda consumers | Last access | KMS | Rationale |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    def consumers(row: dict) -> str:
        parts = []
        for role, fns in row.get("consumers_by_role", {}).items():
            if len(fns) > 5:
                parts.append(f"{len(fns)} functions via {role}")
            elif fns:
                parts.append(", ".join(fns))
        return "; ".join(parts) or "—"

    for r in active:
        lambda_src = sum(1 for f in r["source_files"] if f.startswith("amplify/functions/"))
        lines.append(
            f"| `{r['name']}` | {r['domain']} | {r['action']} | "
            f"{', '.join(r['iam_reader_roles']) or '—'} | {consumers(r)} "
            f"(source files in amplify/functions: {lambda_src}) | "
            f"{r['last_accessed'] or 'never'} | {r['kms']} | {r['rationale']} |")
    lines += ["", "## Scheduled for deletion", "", "| Secret | Deletion requested | IAM readers |",
              "| --- | --- | --- |"]
    for r in rows:
        if r["scheduled_deletion"]:
            lines.append(f"| `{r['name']}` | {r['scheduled_deletion']} | "
                         f"{', '.join(r['iam_reader_roles']) or '—'} |")
    lines += ["", "## Source references (by-reference names, no values)", ""]
    for r in active:
        if r["source_files"] or r["env_references"]:
            refs = r["env_references"] + r["source_files"]
            lines.append(f"- `{r['name']}`: " + ", ".join(f"`{x}`" for x in refs[:12])
                         + (f" (+{len(refs) - 12} more)" if len(refs) > 12 else ""))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    import boto3

    if boto3.client("sts", region_name=REGION).get_caller_identity()["Account"] != ACCOUNT:
        print("refusing: wrong account", file=sys.stderr)
        return 2
    sm = boto3.client("secretsmanager", region_name=REGION)
    secrets = [s for p in sm.get_paginator("list_secrets").paginate(IncludePlannedDeletion=True)
               for s in p["SecretList"]]
    lam = boto3.client("lambda", region_name=REGION)
    functions = [f for p in lam.get_paginator("list_functions").paginate()
                 for f in p["Functions"]]
    rows = build(secrets, role_documents(boto3.client("iam")), functions)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows:
        print(f"{r['action']:<20} {r['name']:<40} readers={len(r['iam_reader_roles'])} "
              f"lambdas={len(r['lambda_consumers'])}")
    if args.markdown:
        args.markdown.write_text(to_markdown(rows, when), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
