#!/usr/bin/env python3
"""Read-only Gate 4/5 evidence for what `scripts/check_provider_policy_live.py` cannot see.

That gate applies the provider allow-list (`scripts/provider_allowlist.py`) to the account as
`list_functions` and `list_secrets` return it: each function's `$LATEST` environment and every
active secret. Three things sit outside that view:

  - a published version keeps the environment it was published with, so an env update on
    `$LATEST` does not change what a `live` alias runs;
  - a secret scheduled for deletion is not listed by default, and can still be restored;
  - an IAM grant on a DynamoDB table outlives the table: on 2026-10-14 two dedicated roles still
    granted only a deleted table while their functions had moved to `CommerceKeys`.

Checks (each PASS/FAIL with evidence):
  lambda-env           every environment on $LATEST and on each alias's published version passes
                       the allow-list (the same rules: `check_provider_policy_live.check_env`)
  secrets              every Secrets Manager name, planned deletion included, is on the allow-list
  iam-dangling-tables  no customer IAM statement grants a DynamoDB table that does not exist
  commerce-key-access  every function with COMMERCE_KEYS_TABLE (on its live alias) can GetItem
                       that table under its own role (iam:SimulatePrincipalPolicy)

Never calls GetSecretValue and never prints a credential: an env finding names the KEY, plus the
host, secret name or selector value when that value is itself the finding.
Exit 0 = all PASS, 1 = any FAIL.

    python scripts/check_live_provider_independence.py
    python scripts/check_live_provider_independence.py --json out.json --markdown out.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import provider_allowlist as allow  # noqa: E402
from check_provider_policy_live import check_env  # noqa: E402

ACCOUNT = "775261844268"
REGION = "us-east-1"
TABLE_ARN = re.compile(r"^arn:aws:dynamodb:[a-z0-9-]+:\d{12}:table/([A-Za-z0-9_.-]+)$")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    evidence: list[str] = field(default_factory=list)


def _pages(call: Callable[..., dict], key: str, token_in: str, token_out: str, **kwargs):
    token = None
    while True:
        page = call(**kwargs, **({token_in: token} if token else {}))
        yield from page.get(key, [])
        token = page.get(token_out)
        if not token:
            return


class LiveAudit:
    def __init__(self, clients: dict[str, Any]):
        self.c = clients
        self._functions: list[dict] | None = None

    def functions(self) -> list[dict]:
        if self._functions is None:
            self._functions = list(_pages(self.c["lambda"].list_functions, "Functions",
                                          "Marker", "NextMarker"))
        return self._functions

    def alias_configs(self) -> list[tuple[str, str, dict]]:
        out = []
        lam = self.c["lambda"]
        for fn in self.functions():
            name = fn["FunctionName"]
            for alias in _pages(lam.list_aliases, "Aliases", "Marker", "NextMarker",
                                FunctionName=name):
                cfg = lam.get_function_configuration(FunctionName=name,
                                                     Qualifier=alias["FunctionVersion"])
                out.append((name, alias["Name"], cfg))
        return out

    # ── individual checks ────────────────────────────────────────────────────────────────────
    def lambda_env(self) -> Check:
        hits = []
        configs = [(f["FunctionName"], "$LATEST", f) for f in self.functions()]
        configs += self.alias_configs()
        for name, qualifier, cfg in configs:
            env = (cfg.get("Environment") or {}).get("Variables") or {}
            for _kind, _fn, reference, _why in check_env(name, env):
                hits.append(f"{name}:{qualifier} {reference}")
        return Check("lambda-env", not hits,
                     f"{len(configs)} configurations ($LATEST + alias versions)",
                     sorted(set(hits)))

    def secrets(self) -> Check:
        names = [s["Name"] for s in _pages(self.c["secretsmanager"].list_secrets, "SecretList",
                                           "NextToken", "NextToken",
                                           IncludePlannedDeletion=True)]
        hits = sorted(n for n in names if allow.secret_owner(n)[0] is None)
        return Check("secrets", not hits,
                     f"{len(names)} secrets incl. planned deletion, {len(hits)} not approved",
                     hits)

    def tables(self) -> set[str]:
        return set(_pages(self.c["dynamodb"].list_tables, "TableNames",
                          "ExclusiveStartTableName", "LastEvaluatedTableName"))

    def iam_dangling_tables(self, tables: set[str]) -> Check:
        iam = self.c["iam"]
        hits = []
        for role in _pages(iam.list_roles, "Roles", "Marker", "Marker"):
            name = role["RoleName"]
            if role.get("Path", "/").startswith("/aws-service-role/"):
                continue
            docs = []
            for pname in _pages(iam.list_role_policies, "PolicyNames", "Marker", "Marker",
                                RoleName=name):
                docs.append((f"inline:{pname}",
                             iam.get_role_policy(RoleName=name, PolicyName=pname)
                             ["PolicyDocument"]))
            for attached in _pages(iam.list_attached_role_policies, "AttachedPolicies",
                                   "Marker", "Marker", RoleName=name):
                arn = attached["PolicyArn"]
                if arn.startswith("arn:aws:iam::aws:"):
                    continue
                version = iam.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
                docs.append((f"managed:{attached['PolicyName']}",
                             iam.get_policy_version(PolicyArn=arn, VersionId=version)
                             ["PolicyVersion"]["Document"]))
            for label, doc in docs:
                statements = doc.get("Statement", [])
                for st in statements if isinstance(statements, list) else [statements]:
                    resources = st.get("Resource", [])
                    for res in resources if isinstance(resources, list) else [resources]:
                        m = TABLE_ARN.match(str(res))
                        if m and "*" not in m.group(1) and m.group(1) not in tables:
                            hits.append(f"{name} {label} {st.get('Sid', '-')} -> {m.group(1)}")
        return Check("iam-dangling-tables", not hits,
                     "customer-managed and inline statements naming a missing table", hits)

    def commerce_key_access(self) -> Check:
        iam, lam = self.c["iam"], self.c["lambda"]
        hits, measured = [], []
        for fn in self.functions():
            name = fn["FunctionName"]
            try:
                cfg = lam.get_function_configuration(FunctionName=name, Qualifier="live")
            except Exception:  # noqa: BLE001 - no live alias: $LATEST is what is invoked
                cfg = fn
            table = ((cfg.get("Environment") or {}).get("Variables") or {}).get(
                "COMMERCE_KEYS_TABLE")
            if not table:
                continue
            role_arn = cfg["Role"]
            result = iam.simulate_principal_policy(
                PolicySourceArn=role_arn, ActionNames=["dynamodb:GetItem"],
                ResourceArns=[f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{table}"],
                ContextEntries=[{"ContextKeyName": "dynamodb:LeadingKeys",
                                 "ContextKeyValues": ["PAYREF#PROBE"],
                                 "ContextKeyType": "stringList"}],
            )["EvaluationResults"][0]["EvalDecision"]
            line = f"{name} role={role_arn.split('/')[-1]} GetItem {table} -> {result}"
            measured.append(line)
            if result != "allowed":
                hits.append(line)
        return Check("commerce-key-access", not hits,
                     f"{len(measured)} functions read COMMERCE_KEYS_TABLE", hits or measured)

    def run(self, progress: Callable[[str], None] = lambda _m: None) -> list[Check]:
        account = self.c["sts"].get_caller_identity()["Account"]
        if account != ACCOUNT:
            raise SystemExit(f"refusing: caller account {account} is not {ACCOUNT}")
        checks: list[Check] = []

        def timed(label: str, fn: Callable[[], Any]):
            started = datetime.now(timezone.utc)
            progress(f"running {label} ...")
            value = fn()
            progress(f"done {label} in {(datetime.now(timezone.utc) - started).seconds}s")
            return value

        tables = timed("dynamodb list", self.tables)
        checks.append(timed("lambda-env", self.lambda_env))
        checks.append(timed("secrets", self.secrets))
        checks.append(timed("iam-dangling-tables", lambda: self.iam_dangling_tables(tables)))
        checks.append(timed("commerce-key-access", self.commerce_key_access))
        return checks


def to_markdown(checks: list[Check], when: str) -> str:
    lines = [f"# Live provider-independence check — {when}", "",
             f"Account {ACCOUNT}, {REGION}. Generated by "
             "`scripts/check_live_provider_independence.py` (read-only; no secret values).", "",
             "| Check | Result | Detail |", "| --- | --- | --- |"]
    for c in checks:
        lines.append(f"| `{c.name}` | {'PASS' if c.passed else '**FAIL**'} | {c.detail} |")
    for c in checks:
        if c.evidence:
            lines += ["", f"## {c.name}", ""] + [f"- `{e}`" for e in c.evidence]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    import boto3
    from botocore.config import Config

    cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"})
    clients = {n: boto3.client(n, region_name=REGION, config=cfg)
               for n in ("lambda", "secretsmanager", "dynamodb", "iam", "sts")}
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checks = LiveAudit(clients).run(
        progress=lambda m: print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}",
                                 file=sys.stderr, flush=True))
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:<20} {c.detail}")
        for e in (c.evidence if not c.passed else []):
            print(f"      {e}")
    if args.json:
        args.json.write_text(json.dumps({"generated": when, "checks": [c.__dict__ for c in checks]},
                                        indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(to_markdown(checks, when), encoding="utf-8")
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
