"""`scripts/remediate_commerce_keys_iam.py`: plan writes nothing, apply is owner-gated and
reversible, and the targets are the repository's IaC documents rather than a third copy."""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "remediate_commerce_keys_iam.py"
DELETED = "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-WixOrderIds"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("remediate_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["remediate_under_test"] = module  # @dataclass looks the module up here
    spec.loader.exec_module(module)
    return module


def _evaluate(documents, action, resource, context):
    """Tiny Allow evaluator good enough for these literal-ARN policies."""
    leading = {e["ContextKeyName"]: e["ContextKeyValues"] for e in context}
    for doc in documents:
        for st in doc["Statement"]:
            actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
            resources = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            if not (any(fnmatch.fnmatchcase(action, a) for a in actions)
                    and any(fnmatch.fnmatchcase(resource, r) for r in resources)):
                continue
            cond = st.get("Condition", {}).get("ForAllValues:StringLike", {})
            patterns = cond.get("dynamodb:LeadingKeys")
            if patterns is not None:
                values = leading.get("dynamodb:LeadingKeys", [])
                if not values or not all(any(fnmatch.fnmatchcase(v, p) for p in patterns)
                                         for v in values):
                    continue
            return "allowed"
    return "implicitDeny"


class FakeIam:
    def __init__(self, live):
        self.live = {k: json.loads(json.dumps(v)) for k, v in live.items()}
        self.puts, self.deletes = [], []

    def list_role_policies(self, RoleName, Marker=None):
        return {"PolicyNames": sorted(n for (r, n) in self.live if r == RoleName),
                "IsTruncated": False}

    def get_role_policy(self, RoleName, PolicyName):
        return {"PolicyDocument": json.loads(json.dumps(self.live[(RoleName, PolicyName)]))}

    def put_role_policy(self, RoleName, PolicyName, PolicyDocument):
        self.puts.append((RoleName, PolicyName))
        self.live[(RoleName, PolicyName)] = json.loads(PolicyDocument)

    def delete_role_policy(self, RoleName, PolicyName):
        self.deletes.append((RoleName, PolicyName))
        self.live.pop((RoleName, PolicyName), None)

    def simulate_custom_policy(self, PolicyInputList, ActionNames, ResourceArns, ContextEntries):
        docs = [json.loads(p) for p in PolicyInputList]
        return {"EvaluationResults": [{"EvalDecision": _evaluate(
            docs, ActionNames[0], ResourceArns[0], ContextEntries)}]}

    def simulate_principal_policy(self, PolicySourceArn, ActionNames, ResourceArns,
                                  ContextEntries):
        role = PolicySourceArn.split("/")[-1]
        docs = [d for (r, _n), d in self.live.items() if r == role]
        return {"EvaluationResults": [{"EvalDecision": _evaluate(
            docs, ActionNames[0], ResourceArns[0], ContextEntries)}]}


class FakeAnalyzer:
    def __init__(self, findings=()):
        self.findings, self.calls = list(findings), 0

    def validate_policy(self, policyDocument, policyType):
        self.calls += 1
        assert policyType == "IDENTITY_POLICY"
        json.loads(policyDocument)
        return {"findings": self.findings}


class FakeSts:
    def __init__(self, account="775261844268"):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


def _drifted_live(mod):
    """Today's measured live state: every commerce-key grant points at the deleted table."""
    live = {}
    for (role, name), target in mod.target_documents().items():
        doc = json.loads(json.dumps(target).replace(
            "stack-wecare-digital-CommerceKeys", "stack-wecare-digital-WixOrderIds"))
        for st in doc["Statement"]:
            if st.get("Sid") == "ReserveNativeInventory":
                st["Action"] = ["dynamodb:TransactWriteItems"]
                st["Resource"] = [st["Resource"][0], DELETED]
        live[(role, name)] = doc
    live[("wecare-service-requests-role", "vault-file-selection")] = {
        "Version": "2012-10-17", "Statement": [{
            "Sid": "BindSelectedVaultFile", "Effect": "Allow", "Action": ["dynamodb:GetItem"],
            "Resource": ["arn:aws:dynamodb:us-east-1:775261844268:table/"
                         "stack-wecare-digital-SecureFilesTable"]}]}
    return live


def _tool(mod, live, *, account="775261844268", findings=()):
    lines: list[str] = []
    iam = FakeIam(live)
    tool = mod.Remediation(iam, FakeAnalyzer(findings), FakeSts(account), out=lines.append,
                           sleep=lambda _s: None)
    return tool, iam, lines


def test_targets_are_the_iac_documents(mod):
    targets = mod.target_documents()
    assert set(targets) == {("wecare-checkout-role", "CheckoutLeastPrivilege"),
                            ("wecare-checkout-role", "CheckoutNativeCatalogAuthority"),
                            ("wecare-service-requests-role", "service-requests-rw")}
    native = json.loads((ROOT / "scripts" / "iam-native-catalog-checkout.json").read_text())
    assert targets[("wecare-checkout-role", "CheckoutNativeCatalogAuthority")] == native
    assert "WixOrderIds" not in json.dumps(list(targets.values()))


def test_plan_reports_drift_and_writes_nothing(mod):
    tool, iam, lines = _tool(mod, _drifted_live(mod))
    assert tool.plan() == 10
    assert iam.puts == [] and iam.deletes == []
    text = "\n".join(lines)
    assert "DRIFT: 3 inline" in text and "BAD" not in text


def test_the_drifted_live_state_really_denies_what_checkout_needs(mod):
    """The fake reproduces the 2026-10-14 simulator verdicts, so the cases are meaningful."""
    _tool_, iam, _ = _tool(mod, _drifted_live(mod))
    tool = mod.Remediation(iam, FakeAnalyzer(), FakeSts(), out=lambda _l: None,
                           sleep=lambda _s: None)
    problems = tool.simulate_roles(attempts=1)
    assert any("PutItem stack-wecare-digital-CommerceKeys" in p for p in problems)
    assert any("UpdateItem stack-wecare-digital-ProductsTable" in p for p in problems)
    assert any("wecare-service-requests-role dynamodb:GetItem" in p for p in problems)


def test_plan_on_a_compliant_account_is_zero(mod):
    live = {k: v for k, v in mod.target_documents().items()}
    tool, iam, _ = _tool(mod, live)
    assert tool.plan() == 0 and iam.puts == []


def test_plan_fails_closed_on_an_access_analyzer_error(mod):
    tool, iam, lines = _tool(mod, _drifted_live(mod),
                             findings=[{"findingType": "ERROR", "issueCode": "X"}])
    assert tool.plan() == 1 and iam.puts == []


def test_wrong_account_is_refused(mod):
    tool, iam, _ = _tool(mod, _drifted_live(mod), account="111111111111")
    assert tool.plan() == 2
    assert tool.apply(mod.APPLY_TOKEN, ROOT / ".scratch" / "never") == 2
    assert iam.puts == []


def test_apply_without_the_owner_token_changes_nothing(mod, tmp_path):
    tool, iam, lines = _tool(mod, _drifted_live(mod))
    assert tool.apply(None, tmp_path) == 2
    assert tool.apply("yes", tmp_path) == 2
    assert iam.puts == [] and list(tmp_path.iterdir()) == []


def test_apply_saves_rollback_first_then_fixes_only_changed_policies(mod, tmp_path):
    live = _drifted_live(mod)
    tool, iam, lines = _tool(mod, live)
    assert tool.apply(mod.APPLY_TOKEN, tmp_path) == 0
    assert sorted(iam.puts) == sorted(mod.target_documents())
    assert ("wecare-service-requests-role", "vault-file-selection") not in iam.puts
    saved = json.loads(next(tmp_path.iterdir()).read_text())
    assert saved["account"] == "775261844268"
    assert {(p["role"], p["policyName"]) for p in saved["policies"]} == set(iam.puts)
    assert all("WixOrderIds" in json.dumps(p["document"]) for p in saved["policies"])
    assert "APPLIED AND VERIFIED" in "\n".join(lines)


def test_rollback_restores_the_saved_documents(mod, tmp_path):
    live = _drifted_live(mod)
    tool, iam, _ = _tool(mod, live)
    assert tool.apply(mod.APPLY_TOKEN, tmp_path) == 0
    rollback = next(tmp_path.iterdir())
    assert tool.rollback(rollback, None) == 2
    assert tool.rollback(rollback, mod.ROLLBACK_TOKEN) == 0
    for key, document in live.items():
        assert mod.canonical(iam.live[key]) == mod.canonical(document)


def test_cases_cover_the_live_code_paths(mod):
    labels = {c.label() for c in mod.CASES}
    assert any("UpdateItem stack-wecare-digital-ProductsTable -> allowed" in l for l in labels)
    assert any("DeleteItem stack-wecare-digital-CommerceKeys -> denied" in l for l in labels)
    assert any("[ORDERNO#X] -> denied" in l for l in labels)
