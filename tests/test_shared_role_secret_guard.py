"""`scripts/shared_role_secret_guard.py`: Deny exactly three secrets, keep the rest readable,
and never touch the role's inline policies (they are at IAM's 10,240-byte limit)."""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "shared_role_secret_guard.py"
ARN = "arn:aws:secretsmanager:us-east-1:775261844268:secret:"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("secret_guard_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["secret_guard_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _decide(documents, action, resource):
    allowed = False
    for doc in documents:
        for st in doc["Statement"]:
            actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
            resources = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            if any(fnmatch.fnmatchcase(action, a) for a in actions) and \
                    any(fnmatch.fnmatchcase(resource, r) for r in resources):
                if st["Effect"] == "Deny":
                    return "explicitDeny"
                allowed = True
    return "allowed" if allowed else "implicitDeny"


SHARED = {"Version": "2012-10-17", "Statement": [{
    "Sid": "SecretsManager", "Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"],
    "Resource": ARN + "wecare/*"}]}


class NoSuchEntityException(Exception):
    pass


class FakeIam:
    def __init__(self):
        self.inline = {"wecare-digital-lambda-permissions": SHARED}
        self.managed: dict[str, dict] = {}
        self.attached = ["arn:aws:iam::aws:policy/X"]
        self.calls: list[str] = []

    def list_role_policies(self, RoleName):
        return {"PolicyNames": sorted(self.inline)}

    def get_role_policy(self, RoleName, PolicyName):
        return {"PolicyDocument": self.inline[PolicyName]}

    def list_attached_role_policies(self, RoleName):
        return {"AttachedPolicies": [{"PolicyArn": a, "PolicyName": a.split("/")[-1]}
                                     for a in self.attached]}

    def get_policy(self, PolicyArn):
        if PolicyArn not in self.managed:
            raise NoSuchEntityException("NoSuchEntity")
        return {"Policy": {"DefaultVersionId": "v1"}}

    def get_policy_version(self, PolicyArn, VersionId):
        return {"PolicyVersion": {"Document": self.managed[PolicyArn]}}

    def create_policy(self, PolicyName, PolicyDocument, Description, Tags):
        self.calls.append("create")
        self.managed[f"arn:aws:iam::775261844268:policy/{PolicyName}"] = json.loads(PolicyDocument)

    def attach_role_policy(self, RoleName, PolicyArn):
        self.calls.append("attach")
        self.attached.append(PolicyArn)

    def detach_role_policy(self, RoleName, PolicyArn):
        self.calls.append("detach")
        self.attached.remove(PolicyArn)

    def delete_policy(self, PolicyArn):
        self.calls.append("delete")
        self.managed.pop(PolicyArn)

    def put_role_policy(self, **_):  # pragma: no cover - must never be used
        raise AssertionError("inline policies are at the size limit; never written")

    def simulate_custom_policy(self, PolicyInputList, ActionNames, ResourceArns):
        docs = [json.loads(p) for p in PolicyInputList]
        return {"EvaluationResults": [{"EvalDecision": _decide(docs, ActionNames[0],
                                                               ResourceArns[0])}]}

    def simulate_principal_policy(self, PolicySourceArn, ActionNames, ResourceArns):
        docs = list(self.inline.values()) + [self.managed[a] for a in self.attached
                                             if a in self.managed]
        return {"EvaluationResults": [{"EvalDecision": _decide(docs, ActionNames[0],
                                                               ResourceArns[0])}]}


class Analyzer:
    def validate_policy(self, policyDocument, policyType):
        return {"findings": []}


class Sts:
    def __init__(self, account="775261844268"):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


def _tool(mod, account="775261844268"):
    iam = FakeIam()
    return mod.Guard(iam, Analyzer(), Sts(account), out=lambda _l: None,
                     sleep=lambda _s: None), iam


def test_guard_denies_exactly_three_and_never_allows(mod):
    doc = mod.guard_document()
    assert [s["Effect"] for s in doc["Statement"]] == ["Deny"]
    resources = doc["Statement"][0]["Resource"]
    assert len(resources) == 3 and all(r.endswith("-??????") for r in resources)
    # The 6-character suffix pattern cannot swallow a longer neighbouring name.
    assert not fnmatch.fnmatchcase(ARN + "wecare/github-pat-extra-AbC123", resources[0])


def test_plan_writes_nothing(mod):
    tool, iam = _tool(mod)
    assert tool.plan() == 10 and iam.calls == []


def test_apply_needs_token_then_creates_attaches_and_verifies(mod):
    tool, iam = _tool(mod)
    assert tool.apply(None) == 2 and iam.calls == []
    assert tool.apply(mod.APPLY_TOKEN) == 0
    assert iam.calls == ["create", "attach"]
    assert list(iam.inline) == ["wecare-digital-lambda-permissions"]
    assert tool.plan() == 0
    assert tool.apply(mod.APPLY_TOKEN) == 0 and iam.calls == ["create", "attach"]  # idempotent


def test_used_secrets_stay_readable_after_apply(mod):
    tool, iam = _tool(mod)
    tool.apply(mod.APPLY_TOKEN)
    docs = list(iam.inline.values()) + list(iam.managed.values())
    for name in mod.STILL_ALLOWED:
        assert _decide(docs, "secretsmanager:GetSecretValue", ARN + name + "-AbC123") == "allowed"
    for name in mod.DENIED:
        assert _decide(docs, "secretsmanager:GetSecretValue", ARN + name + "-AbC123") == \
            "explicitDeny"


def test_rollback_detaches_and_deletes_only_the_guard(mod):
    tool, iam = _tool(mod)
    tool.apply(mod.APPLY_TOKEN)
    assert tool.rollback(None) == 2
    assert tool.rollback(mod.ROLLBACK_TOKEN) == 0
    assert iam.calls[-2:] == ["detach", "delete"]
    assert iam.attached == ["arn:aws:iam::aws:policy/X"] and iam.managed == {}


def test_wrong_account_refused(mod):
    tool, iam = _tool(mod, account="111111111111")
    assert tool.plan() == 2 and tool.apply(mod.APPLY_TOKEN) == 2 and iam.calls == []
