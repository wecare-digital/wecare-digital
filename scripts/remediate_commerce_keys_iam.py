#!/usr/bin/env python3
"""Approval-gated repair of the live commerce-key IAM drift found on 2026-10-14. PLAN BY DEFAULT.

What is wrong (measured read-only with iam:SimulatePrincipalPolicy, 2026-10-14):

* `wecare-checkout-role` / `CheckoutLeastPrivilege` / `PaymentAttemptAndCommerceKeys` grants
  Get/Put/Update on the DELETED previous commerce-key table. `wecare-checkout:live`
  reads `COMMERCE_KEYS_TABLE=stack-wecare-digital-CommerceKeys`: PutItem there = implicitDeny.
* `wecare-checkout-role` / `CheckoutNativeCatalogAuthority` / `ReserveNativeInventory` grants the
  pseudo-action `dynamodb:TransactWriteItems`. DynamoDB authorizes each transactional item with its
  underlying action, so the stock decrement (an `Update` on ProductsTable inside
  `native_inventory_txn.reserve_basket`, live because NATIVE_STOCK_RESERVATION_ENABLED=true)
  = implicitDeny.
* `wecare-service-requests-role` / `service-requests-rw` / `ReadPaidOrderClaims` grants GetItem on
  the deleted table; paid-service activation reads `PAYREF#`/`PAYMENTATTEMPT#` rows on CommerceKeys.

The target documents are NOT typed here. They come from the repository's IaC homes, so the repair
and the next provisioning run cannot disagree:

    provision_checkout.expected_role_policy()          -> wecare-checkout-role/CheckoutLeastPrivilege
    scripts/iam-native-catalog-checkout.json           -> wecare-checkout-role/CheckoutNativeCatalogAuthority
    provision_service_requests.expected_role_policy()  -> wecare-service-requests-role/service-requests-rw

Modes
    (default)  plan: read the live inline policies, print a unified diff against the targets,
               validate every target with IAM Access Analyzer, and simulate the required allows and
               required denies against the TARGET documents (iam:SimulateCustomPolicy). Writes
               nothing anywhere.
    --apply --confirm I-APPROVE-COMMERCE-KEYS-IAM
               owner-approved: save the current documents to a rollback file, put_role_policy for
               each changed policy only, then re-simulate the ROLES (SimulatePrincipalPolicy).
    --rollback FILE --confirm I-APPROVE-COMMERCE-KEYS-IAM-ROLLBACK
               restore the documents saved by --apply.

Exit status: 0 already compliant (or apply/rollback verified), 10 drift found and the targets are
valid (plan only), 1 a target failed validation/simulation, 2 refused (guard or missing confirm).
No secret value is read; only IAM policy documents, which contain table ARNs, are handled.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "775261844268"
REGION = "us-east-1"
APPLY_TOKEN = "I-APPROVE-COMMERCE-KEYS-IAM"
ROLLBACK_TOKEN = "I-APPROVE-COMMERCE-KEYS-IAM-ROLLBACK"
DEFAULT_ROLLBACK_DIR = ROOT / ".scratch" / "iam-rollback"
NATIVE_POLICY_FILE = ROOT / "scripts" / "iam-native-catalog-checkout.json"

CHECKOUT_ROLE = "wecare-checkout-role"
SERVICE_ROLE = "wecare-service-requests-role"


def _table(name: str) -> str:
    return f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{name}"


KEYS = _table("stack-wecare-digital-CommerceKeys")
PRODUCTS = _table("stack-wecare-digital-ProductsTable")
ATTEMPTS = _table("stack-wecare-digital-PaymentAttemptsTable")
ORDERS = _table("stack-wecare-digital-OrderTable")


@dataclass(frozen=True)
class Case:
    """One simulated decision. `expect` is "allowed" or "denied" (implicit or explicit)."""

    role: str
    action: str
    resource: str
    expect: str
    leading_key: str | None = None

    def context(self) -> list[dict]:
        if self.leading_key is None:
            return []
        return [{"ContextKeyName": "dynamodb:LeadingKeys",
                 "ContextKeyValues": [self.leading_key], "ContextKeyType": "stringList"}]

    def label(self) -> str:
        key = f" [{self.leading_key}]" if self.leading_key else ""
        return f"{self.role} {self.action} {self.resource.split('/')[-1]}{key} -> {self.expect}"


#: What the live code needs (allowed) and what must stay withheld (denied).
CASES: tuple[Case, ...] = (
    # checkout: payment references, attempt pointers, idempotency rows and stock claims.
    Case(CHECKOUT_ROLE, "dynamodb:GetItem", KEYS, "allowed"),
    Case(CHECKOUT_ROLE, "dynamodb:PutItem", KEYS, "allowed"),
    Case(CHECKOUT_ROLE, "dynamodb:UpdateItem", KEYS, "allowed"),
    Case(CHECKOUT_ROLE, "dynamodb:PutItem", ATTEMPTS, "allowed"),
    # checkout: the transactional stock decrement/increment on ProductsTable.
    Case(CHECKOUT_ROLE, "dynamodb:UpdateItem", PRODUCTS, "allowed"),
    Case(CHECKOUT_ROLE, "dynamodb:GetItem", PRODUCTS, "allowed"),
    # checkout: evidence is never deletable, and the new grant does not widen to other tables.
    Case(CHECKOUT_ROLE, "dynamodb:DeleteItem", KEYS, "denied"),
    Case(CHECKOUT_ROLE, "dynamodb:DeleteItem", ATTEMPTS, "denied"),
    Case(CHECKOUT_ROLE, "dynamodb:DeleteItem", ORDERS, "denied"),
    Case(CHECKOUT_ROLE, "dynamodb:DeleteItem", PRODUCTS, "denied"),
    Case(CHECKOUT_ROLE, "dynamodb:Scan", KEYS, "denied"),
    # service-requests: paid-claim reads only, and only the three row families.
    Case(SERVICE_ROLE, "dynamodb:GetItem", KEYS, "allowed", "PAYREF#X"),
    Case(SERVICE_ROLE, "dynamodb:GetItem", KEYS, "allowed", "PAYMENTATTEMPT#X"),
    Case(SERVICE_ROLE, "dynamodb:GetItem", KEYS, "denied", "ORDERNO#X"),
    Case(SERVICE_ROLE, "dynamodb:PutItem", KEYS, "denied", "PAYREF#X"),
    Case(SERVICE_ROLE, "dynamodb:DeleteItem", KEYS, "denied", "PAYREF#X"),
)


def _load_script(name: str):
    module_name = f"_{name}_for_remediation"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def target_documents() -> dict[tuple[str, str], dict]:
    """(role, inline policy name) -> target document, built from the IaC homes."""
    checkout = _load_script("provision_checkout")
    service = _load_script("provision_service_requests")
    return {
        (CHECKOUT_ROLE, "CheckoutLeastPrivilege"): checkout.expected_role_policy(ACCOUNT),
        (CHECKOUT_ROLE, "CheckoutNativeCatalogAuthority"):
            json.loads(NATIVE_POLICY_FILE.read_text(encoding="utf-8")),
        (SERVICE_ROLE, service.INLINE_POLICY_NAME): service.expected_role_policy(ACCOUNT),
    }


def canonical(document: dict | None) -> dict | None:
    """Order-insensitive form: IAM may store single values as strings or reorder nothing."""
    if document is None:
        return None
    doc = copy.deepcopy(document)
    statements = doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for st in statements:
        for field in ("Action", "Resource", "NotAction", "NotResource"):
            if field in st:
                value = st[field]
                st[field] = sorted(value) if isinstance(value, list) else [value]
    doc["Statement"] = sorted(statements, key=lambda s: str(s.get("Sid", "")))
    return doc


def render(document: dict | None) -> list[str]:
    if document is None:
        return ["<absent>\n"]
    return [line + "\n" for line in json.dumps(canonical(document), indent=2,
                                               sort_keys=True).splitlines()]


class Remediation:
    def __init__(self, iam, analyzer, sts, *, out: Callable[[str], None] = print,
                 targets: dict | None = None, sleep: Callable[[float], None] = time.sleep):
        self.iam, self.analyzer, self.sts, self.out, self.sleep = iam, analyzer, sts, out, sleep
        self.targets = targets if targets is not None else target_documents()

    # ── reads ────────────────────────────────────────────────────────────────────────────────
    def guard(self) -> bool:
        account = self.sts.get_caller_identity().get("Account")
        if account != ACCOUNT:
            self.out(f"REFUSED: caller account {account!r} is not {ACCOUNT}")
            return False
        return True

    def live_inline(self, role: str) -> dict[str, dict]:
        names: list[str] = []
        marker = None
        while True:
            kwargs = {"RoleName": role, **({"Marker": marker} if marker else {})}
            page = self.iam.list_role_policies(**kwargs)
            names += page.get("PolicyNames", [])
            marker = page.get("Marker") if page.get("IsTruncated") else None
            if not marker:
                break
        return {n: self.iam.get_role_policy(RoleName=role, PolicyName=n)["PolicyDocument"]
                for n in names}

    def changes(self) -> dict[tuple[str, str], tuple[dict | None, dict]]:
        out = {}
        for (role, name), target in self.targets.items():
            live = self.live_inline(role).get(name)
            if canonical(live) != canonical(target):
                out[(role, name)] = (live, target)
        return out

    # ── checks ───────────────────────────────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        problems = []
        for (role, name), document in self.targets.items():
            findings = self.analyzer.validate_policy(
                policyDocument=json.dumps(document), policyType="IDENTITY_POLICY",
            ).get("findings", [])
            for f in findings:
                kind = f.get("findingType")
                line = f"{role}/{name}: {kind} {f.get('issueCode')}"
                self.out(f"  access-analyzer {line}")
                if kind in {"ERROR", "SECURITY_WARNING"}:
                    problems.append(line)
        return problems

    def _decide(self, result: dict) -> str:
        return "allowed" if result.get("EvalDecision") == "allowed" else "denied"

    def simulate_targets(self) -> list[str]:
        """Evaluate CASES against the TARGET documents plus each role's unchanged inline policies."""
        problems = []
        for role in sorted({c.role for c in CASES}):
            docs = self.live_inline(role)
            for (r, name), target in self.targets.items():
                if r == role:
                    docs[name] = target
            policies = [json.dumps(d) for d in docs.values()]
            for case in (c for c in CASES if c.role == role):
                result = self.iam.simulate_custom_policy(
                    PolicyInputList=policies, ActionNames=[case.action],
                    ResourceArns=[case.resource], ContextEntries=case.context(),
                )["EvaluationResults"][0]
                got = self._decide(result)
                self.out(f"  target {'ok ' if got == case.expect else 'BAD'} {case.label()}"
                         f" (got {got})")
                if got != case.expect:
                    problems.append(case.label())
        return problems

    def simulate_roles(self, attempts: int = 6, wait: float = 10.0) -> list[str]:
        """Evaluate CASES against the LIVE roles. Retries: IAM is eventually consistent."""
        problems: list[str] = []
        for attempt in range(attempts):
            problems = []
            for case in CASES:
                result = self.iam.simulate_principal_policy(
                    PolicySourceArn=f"arn:aws:iam::{ACCOUNT}:role/{case.role}",
                    ActionNames=[case.action], ResourceArns=[case.resource],
                    ContextEntries=case.context(),
                )["EvaluationResults"][0]
                if self._decide(result) != case.expect:
                    problems.append(case.label())
            if not problems:
                return []
            if attempt + 1 < attempts:
                self.sleep(wait)
        return problems

    # ── modes ────────────────────────────────────────────────────────────────────────────────
    def plan(self) -> int:
        if not self.guard():
            return 2
        pending = self.changes()
        for (role, name), (live, target) in pending.items():
            self.out(f"\n--- {role}/{name} (live) vs (IaC target)")
            self.out("".join(difflib.unified_diff(render(live), render(target),
                                                  "live", "target")).rstrip())
        self.out("\nvalidate targets (IAM Access Analyzer):")
        bad = self.validate()
        self.out("\nsimulate targets (iam:SimulateCustomPolicy):")
        bad += self.simulate_targets()
        if bad:
            self.out(f"\nPLAN FAILED: {len(bad)} target problem(s); do not apply")
            return 1
        if not pending:
            self.out("\nCOMPLIANT: live inline policies already equal the IaC targets")
            return 0
        self.out(f"\nDRIFT: {len(pending)} inline polic(y/ies) differ; targets valid. "
                 f"Apply only with owner approval: --apply --confirm {APPLY_TOKEN}")
        return 10

    def apply(self, confirm: str | None, rollback_dir: Path) -> int:
        if confirm != APPLY_TOKEN:
            self.out(f"REFUSED: --apply needs --confirm {APPLY_TOKEN} (owner approval)")
            return 2
        if not self.guard():
            return 2
        bad = self.validate() + self.simulate_targets()
        if bad:
            self.out("REFUSED: a target failed validation/simulation")
            return 1
        pending = self.changes()
        if not pending:
            self.out("nothing to change")
            return 0
        rollback_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rollback_file = rollback_dir / f"commerce-keys-iam-{stamp}.json"
        rollback_file.write_text(json.dumps({
            "account": ACCOUNT, "savedAt": stamp,
            "policies": [{"role": r, "policyName": n, "document": live}
                         for (r, n), (live, _t) in pending.items()],
        }, indent=2, sort_keys=True), encoding="utf-8")
        self.out(f"rollback saved: {rollback_file}")
        for (role, name), (_live, target) in pending.items():
            self.iam.put_role_policy(RoleName=role, PolicyName=name,
                                     PolicyDocument=json.dumps(target))
            self.out(f"put_role_policy {role}/{name}")
        problems = self.simulate_roles()
        for p in problems:
            self.out(f"  live BAD {p}")
        if problems:
            self.out(f"APPLIED BUT NOT VERIFIED; roll back with --rollback {rollback_file} "
                     f"--confirm {ROLLBACK_TOKEN}")
            return 1
        self.out("APPLIED AND VERIFIED (SimulatePrincipalPolicy)")
        return 0

    def rollback(self, path: Path, confirm: str | None) -> int:
        if confirm != ROLLBACK_TOKEN:
            self.out(f"REFUSED: --rollback needs --confirm {ROLLBACK_TOKEN}")
            return 2
        if not self.guard():
            return 2
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("account") != ACCOUNT:
            self.out("REFUSED: rollback file is for another account")
            return 2
        for entry in saved["policies"]:
            if entry["document"] is None:
                self.iam.delete_role_policy(RoleName=entry["role"],
                                            PolicyName=entry["policyName"])
                self.out(f"delete_role_policy {entry['role']}/{entry['policyName']}")
            else:
                self.iam.put_role_policy(RoleName=entry["role"], PolicyName=entry["policyName"],
                                         PolicyDocument=json.dumps(entry["document"]))
                self.out(f"restored {entry['role']}/{entry['policyName']}")
        return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path, metavar="FILE")
    parser.add_argument("--confirm")
    parser.add_argument("--rollback-dir", type=Path, default=DEFAULT_ROLLBACK_DIR)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.apply and args.rollback:
        parser.error("--apply and --rollback are exclusive")

    import boto3  # imported late so the unit tests need no AWS SDK configuration

    tool = Remediation(boto3.client("iam"), boto3.client("accessanalyzer", region_name=REGION),
                       boto3.client("sts", region_name=REGION))
    if args.rollback:
        return tool.rollback(args.rollback, args.confirm)
    if args.apply:
        return tool.apply(args.confirm, args.rollback_dir)
    return tool.plan()


if __name__ == "__main__":
    raise SystemExit(main())
