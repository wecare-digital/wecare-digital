"""The commerce-key table has ONE physical name across code, env and every IAM home.

WHY THIS FILE EXISTS
--------------------
On 2026-10-14 the commerce-key rows moved to `stack-wecare-digital-CommerceKeys` and the previous
table was deleted. Code, the env manifest and `amplify/infra/checkout.json` moved. Two
provisioners (`provision_checkout.py`, `provision_service_requests.py`) and the separately applied
`iam-native-catalog-checkout.json` did not, and the live dedicated roles kept granting only the
deleted table. Measured with the IAM policy simulator the same day: `wecare-checkout-role` PutItem
on CommerceKeys = implicitDeny.

Stock reservation is retired. Checkout may read ProductsTable for server-owned prices and product
validation, but it must not mutate ProductsTable. The dormant inventory transaction helper remains
for historical compatibility only and has no checkout call site or IAM write grant.

These tests pin the shape, not a third copy of today's string: every IaC home must resolve to the
resolver's default, and checkout catalog access must remain read-only.
"""
from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import order_keys  # noqa: E402

ACCT = "775261844268"
TABLE_ARN = f"arn:aws:dynamodb:us-east-1:{ACCT}:table/"
NATIVE_POLICY = ROOT / "scripts" / "iam-native-catalog-checkout.json"
INFRA_CHECKOUT = ROOT / "amplify" / "infra" / "checkout.json"
TXN_MODULE = SHARED / "lambda_utils" / "ecommerce" / "native_inventory_txn.py"
MANIFEST = ROOT / "config" / "lambda-env-manifest.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_alignment_test",
                                                  ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkout_prov():
    return _load("provision_checkout")


@pytest.fixture(scope="module")
def service_prov():
    return _load("provision_service_requests")


@pytest.fixture(scope="module")
def resolver_default():
    saved = os.environ.pop("COMMERCE_KEYS_TABLE", None)
    try:
        return order_keys.commerce_keys_table_name()
    finally:
        if saved is not None:
            os.environ["COMMERCE_KEYS_TABLE"] = saved


def _allows(statements, action: str, resource: str) -> bool:
    """Minimal Allow evaluator for this repo's literal-ARN policies (no NotAction/Deny used)."""
    for st in statements:
        if st.get("Effect") != "Allow":
            continue
        actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        resources = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
        if any(fnmatch.fnmatchcase(action, a) for a in actions) and \
                any(fnmatch.fnmatchcase(resource, r) for r in resources):
            return True
    return False


def _infra_role_statements() -> list[dict]:
    template = json.loads(INFRA_CHECKOUT.read_text(encoding="utf-8"))
    role = template["Resources"]["CheckoutRole"]["Properties"]
    out = []
    for policy in role["Policies"]:
        for st in policy["PolicyDocument"]["Statement"]:
            resources = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            flat = []
            for r in resources:
                if isinstance(r, dict) and "Fn::Sub" in r:
                    r = r["Fn::Sub"].replace("${AWS::Region}", "us-east-1") \
                        .replace("${AWS::AccountId}", ACCT)
                flat.append(r)
            out.append({**st, "Resource": flat})
    return out


def test_both_provisioners_name_the_resolver_default(checkout_prov, service_prov,
                                                      resolver_default):
    assert resolver_default == "stack-wecare-digital-CommerceKeys"
    assert checkout_prov.COMMERCE_KEYS_TABLE == resolver_default
    assert service_prov.COMMERCE_KEYS_TABLE == resolver_default


def test_provisioned_env_matches_the_manifest(checkout_prov, service_prov, resolver_default):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["functions"]
    assert manifest["wecare-checkout"]["COMMERCE_KEYS_TABLE"] == resolver_default
    assert checkout_prov.expected_environment()["COMMERCE_KEYS_TABLE"] == resolver_default
    assert service_prov.expected_environment()["COMMERCE_KEYS_TABLE"] == resolver_default


@pytest.mark.parametrize("home", ["provision_checkout", "provision_service_requests",
                                  "amplify/infra/checkout.json"])
def test_every_commerce_key_home_reads_the_resolver_default(checkout_prov, service_prov,
                                                            resolver_default, home):
    """The 2026-10-14 failure, stated positively: each IAM home of a function that reads
    commerce keys must allow GetItem on the table the resolver names, so a home left on a
    previous table fails here rather than as an implicitDeny in a customer's checkout."""
    statements = {
        "provision_checkout": lambda: checkout_prov.expected_role_policy(ACCT)["Statement"],
        "provision_service_requests":
            lambda: service_prov.expected_role_policy(ACCT)["Statement"],
        "amplify/infra/checkout.json": _infra_role_statements,
    }[home]()
    assert _allows(statements, "dynamodb:GetItem", TABLE_ARN + resolver_default), home


def test_no_policy_relies_on_the_transact_pseudo_action():
    """`dynamodb:TransactWriteItems` is not an IAM action; it can never satisfy a grant."""
    native = json.loads(NATIVE_POLICY.read_text(encoding="utf-8"))["Statement"]
    for st in native + _infra_role_statements():
        actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        assert "dynamodb:TransactWriteItems" not in actions, st.get("Sid")


def _transaction_tables() -> dict[str, set[str]]:
    """Which item action each `TransactItems` entry uses, keyed by the TableName argument name.

    Read from the module's AST so a new `Delete`/`ConditionCheck` entry, or a new table, fails this
    test instead of failing a customer's checkout.
    """
    tree = ast.parse(TXN_MODULE.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in {
                    "Put", "Update", "Delete", "ConditionCheck"} and isinstance(value, ast.Dict):
                for k2, v2 in zip(value.keys, value.values):
                    if isinstance(k2, ast.Constant) and k2.value == "TableName" \
                            and isinstance(v2, ast.Name):
                        found.setdefault(v2.id, set()).add(key.value)
    return found


ITEM_ACTION = {"Put": "dynamodb:PutItem", "Update": "dynamodb:UpdateItem",
               "Delete": "dynamodb:DeleteItem", "ConditionCheck": "dynamodb:ConditionCheckItem"}


def test_dormant_reservation_helper_has_no_product_write_authority():
    assert _transaction_tables() == {"keys_table": {"Put", "Update"},
                                     "products_table": {"Update"}}


@pytest.mark.parametrize("source", ["provisioner+json", "infra"])
def test_checkout_catalog_access_is_read_only(checkout_prov, source):
    if source == "infra":
        statements = _infra_role_statements()
    else:
        statements = (checkout_prov.expected_role_policy(ACCT)["Statement"]
                      + json.loads(NATIVE_POLICY.read_text(encoding="utf-8"))["Statement"])
    products = TABLE_ARN + checkout_prov.PRODUCTS_TABLE
    assert _allows(statements, "dynamodb:GetItem", products)
    assert not _allows(statements, "dynamodb:UpdateItem", products)


@pytest.mark.parametrize("source", ["provisioner+json", "infra"])
def test_checkout_role_still_cannot_delete_evidence_or_touch_other_tables(checkout_prov,
                                                                           resolver_default,
                                                                           source):
    if source == "infra":
        statements = _infra_role_statements()
    else:
        statements = (checkout_prov.expected_role_policy(ACCT)["Statement"]
                      + json.loads(NATIVE_POLICY.read_text(encoding="utf-8"))["Statement"])
    for table in (resolver_default, checkout_prov.PRODUCTS_TABLE,
                  checkout_prov.PAYMENT_ATTEMPTS_TABLE, checkout_prov.ORDERS_TABLE):
        assert not _allows(statements, "dynamodb:DeleteItem", TABLE_ARN + table), table
    # Checkout has no product mutation grant, and no unrelated table write grant.
    assert not _allows(statements, "dynamodb:UpdateItem",
                       TABLE_ARN + "stack-wecare-digital-CouponsTable")
    assert not _allows(statements, "dynamodb:UpdateItem",
                       TABLE_ARN + checkout_prov.PRODUCTS_TABLE + "/index/status-updatedAt-index")


def test_service_requests_role_reads_paid_claims_on_the_live_table(service_prov,
                                                                    resolver_default):
    statements = service_prov.expected_role_policy(ACCT)["Statement"]
    claims = [s for s in statements if s["Sid"] == "ReadPaidOrderClaims"]
    assert len(claims) == 1
    assert claims[0]["Resource"] == [TABLE_ARN + resolver_default]
    assert claims[0]["Action"] == ["dynamodb:GetItem"]
    assert claims[0]["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] == [
        "PAYREF#*", "REFERENCE#*", "PAYMENTATTEMPT#*"]
