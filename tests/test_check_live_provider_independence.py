"""`scripts/check_live_provider_independence.py` against stub clients: it flags frozen alias env
keys, dangling table grants and a role that cannot read the commerce-key table, and it never
needs a secret value."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_live_provider_independence.py"
ACCT = "775261844268"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("live_independence_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_independence_under_test"] = module
    spec.loader.exec_module(module)
    return module


class Lambda:
    def __init__(self, functions, aliases, versions):
        self.functions, self.aliases, self.versions = functions, aliases, versions

    def list_functions(self, **_):
        return {"Functions": self.functions}

    def list_aliases(self, FunctionName, **_):
        return {"Aliases": self.aliases.get(FunctionName, [])}

    def get_function_configuration(self, FunctionName, Qualifier):
        if Qualifier == "live":
            alias = next((a for a in self.aliases.get(FunctionName, []) if a["Name"] == "live"),
                         None)
            if alias is None:
                raise RuntimeError("ResourceNotFoundException")
            Qualifier = alias["FunctionVersion"]
        return self.versions[(FunctionName, Qualifier)]


class Gateway:
    def __init__(self, keys):
        self.keys = keys

    def get_routes(self, ApiId, **_):
        return {"Items": [{"RouteKey": k} for k in self.keys]}


class Secrets:
    def __init__(self, names):
        self.names = names

    def list_secrets(self, IncludePlannedDeletion, **_):
        assert IncludePlannedDeletion is True
        return {"SecretList": [{"Name": n} for n in self.names]}

    def get_secret_value(self, **_):  # pragma: no cover - must never be called
        raise AssertionError("secret values must never be read")


class Dynamo:
    def __init__(self, tables):
        self.tables = tables

    def list_tables(self, **_):
        return {"TableNames": self.tables}


class Iam:
    def __init__(self, inline, decisions):
        self.inline, self.decisions = inline, decisions

    def list_roles(self, **_):
        return {"Roles": [{"RoleName": r, "Path": "/"} for r in sorted({r for r, _ in self.inline})]}

    def list_role_policies(self, RoleName, **_):
        return {"PolicyNames": [n for r, n in self.inline if r == RoleName]}

    def get_role_policy(self, RoleName, PolicyName):
        return {"PolicyDocument": self.inline[(RoleName, PolicyName)]}

    def list_attached_role_policies(self, RoleName, **_):
        return {"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::aws:policy/Basic",
                                      "PolicyName": "Basic"}]}

    def simulate_principal_policy(self, PolicySourceArn, ActionNames, ResourceArns,
                                  ContextEntries):
        role = PolicySourceArn.split("/")[-1]
        return {"EvaluationResults": [{"EvalDecision": self.decisions[(role, ResourceArns[0])]}]}


class Sts:
    def get_caller_identity(self):
        return {"Account": ACCT}


def _table(name):
    return f"arn:aws:dynamodb:us-east-1:{ACCT}:table/{name}"


def _clients(*, alias_env, decision, grant_table, routes=("GET /shop",), secrets=("wecare/x",),
             tables=("stack-wecare-digital-CommerceKeys",)):
    role = f"arn:aws:iam::{ACCT}:role/wecare-checkout-role"
    latest = {"FunctionName": "wecare-checkout", "Role": role,
              "Environment": {"Variables": {"COMMERCE_KEYS_TABLE":
                                            "stack-wecare-digital-CommerceKeys"}}}
    version = {"FunctionName": "wecare-checkout", "Role": role,
               "Environment": {"Variables": alias_env}}
    lam = Lambda([latest], {"wecare-checkout": [{"Name": "live", "FunctionVersion": "7"}]},
                 {("wecare-checkout", "7"): version})
    iam = Iam({("wecare-checkout-role", "keys"): {"Statement": [{
        "Sid": "Keys", "Effect": "Allow", "Action": ["dynamodb:GetItem"],
        "Resource": [_table(grant_table)]}]}},
        {("wecare-checkout-role", _table("stack-wecare-digital-CommerceKeys")): decision})
    return {"lambda": lam, "apigatewayv2": Gateway(list(routes)),
            "secretsmanager": Secrets(list(secrets)), "dynamodb": Dynamo(list(tables)),
            "iam": iam, "sts": Sts()}


def _by_name(checks):
    return {c.name: c for c in checks}


def test_a_clean_account_passes(mod):
    checks = _by_name(mod.LiveAudit(_clients(
        alias_env={"COMMERCE_KEYS_TABLE": "stack-wecare-digital-CommerceKeys"},
        decision="allowed", grant_table="stack-wecare-digital-CommerceKeys")).run())
    assert all(c.passed for c in checks.values()), {k: c.evidence for k, c in checks.items()}


def test_todays_drift_is_caught(mod):
    """The 2026-10-14 state: alias env frozen with a WIX_ key, role grants the deleted table."""
    checks = _by_name(mod.LiveAudit(_clients(
        alias_env={"COMMERCE_KEYS_TABLE": "stack-wecare-digital-CommerceKeys",
                   "WIX_ORDER_IDS_TABLE": "stack-wecare-digital-CommerceKeys"},
        decision="implicitDeny", grant_table="stack-wecare-digital-WixOrderIds")).run())
    assert not checks["lambda-env-keys"].passed
    assert checks["lambda-env-keys"].evidence == ["wecare-checkout:live WIX_ORDER_IDS_TABLE"]
    assert not checks["iam-dangling-tables"].passed
    assert "stack-wecare-digital-WixOrderIds" in checks["iam-dangling-tables"].evidence[0]
    assert not checks["commerce-key-access"].passed
    assert "implicitDeny" in checks["commerce-key-access"].evidence[0]


def test_routes_secrets_tables_and_hosts_are_flagged(mod):
    checks = _by_name(mod.LiveAudit(_clients(
        alias_env={"COMMERCE_KEYS_TABLE": "stack-wecare-digital-CommerceKeys",
                   "CDN": "https://static.wixstatic.com/media"},
        decision="allowed", grant_table="stack-wecare-digital-CommerceKeys",
        routes=("POST /wix-catalog-webhook",), secrets=("wecare/wix/app-oauth",),
        tables=("stack-wecare-digital-CommerceKeys", "stack-wecare-digital-WixOrderIds"))).run())
    for name in ("api-routes", "secrets", "dynamodb-tables", "lambda-env-hosts"):
        assert not checks[name].passed, name
    # A host hit reports the KEY, never the value.
    assert checks["lambda-env-hosts"].evidence == ["wecare-checkout:live CDN"]
    assert all("wixstatic" not in e for e in checks["lambda-env-hosts"].evidence)


def test_markdown_lists_every_check(mod):
    checks = mod.LiveAudit(_clients(
        alias_env={"COMMERCE_KEYS_TABLE": "stack-wecare-digital-CommerceKeys"},
        decision="allowed", grant_table="stack-wecare-digital-CommerceKeys")).run()
    text = mod.to_markdown(checks, "2026-10-14T00:00:00Z")
    for c in checks:
        assert f"`{c.name}`" in text
