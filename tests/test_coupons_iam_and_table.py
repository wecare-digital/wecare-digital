"""Coupon IAM and table provisioning, as offline contract tests over the scripts themselves.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` sections 4,
5.2.1 and 6, and the test list in section 7 (tests 52-58). Modelled on
`tests/test_provision_checkout_contract.py`: parse the provisioner, read its policy document and
its constants, and assert over those. No provisioner is ever run with `--apply`, and no AWS call is
made.

Tests 52, 52a and 52b are no longer `xfail` - SEAM-C3b has landed
-----------------------------------------------------------------
They were written `xfail(strict=True)` against `scripts/provision_checkout.py` while that file
belonged to the checkout workstream, under DECISION 8: a seam-dependent assertion is marked, never
weakened, so it converts from "pending" to "passing" the moment its producer lands. DECISION 7 then
assigned that file and its contract test to this work, and the shared-gate step made all three
parts of the HIGH-5 edit in one visit - the grant, the simulated action and table lists, and the
pair-keyed verdict. `strict=True` is what made the conversion safe to do by deleting a mark rather
than by re-deriving what the tests were supposed to prove: an unmarked xfail would have passed
silently either way.

Test 57 lives here, with the drift-gate allowance it asserts added to
`scripts/check_data_model_drift.py` by the same step - one file, one session, one commit.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

TABLE_SCRIPT = ROOT / "scripts" / "provision_coupons_table.py"
ROLE_SCRIPT = ROOT / "scripts" / "provision_coupons_role.py"
CHECKOUT_SCRIPT = ROOT / "scripts" / "provision_checkout.py"
DRIFT_SCRIPT = ROOT / "scripts" / "check_data_model_drift.py"

COUPONS_TABLE_ARN = ("arn:aws:dynamodb:us-east-1:775261844268:table/"
                     "stack-wecare-digital-CouponsTable")
SHARED_FLEET_ROLE = "wecare-digital-lambda-role"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def role():
    module = _load(ROLE_SCRIPT, "provision_coupons_role")
    yield module
    sys.modules.pop("provision_coupons_role", None)


@pytest.fixture(scope="module")
def table():
    module = _load(TABLE_SCRIPT, "provision_coupons_table")
    yield module
    sys.modules.pop("provision_coupons_table", None)


@pytest.fixture(scope="module")
def drift():
    module = _load(DRIFT_SCRIPT, "check_data_model_drift")
    yield module
    sys.modules.pop("check_data_model_drift", None)


def _docstring_ids(tree: ast.Module) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = (node.body or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _checkout_policy() -> dict:
    """Current checkout inline policy, from the provisioner's single policy builder."""
    checkout = _load(CHECKOUT_SCRIPT, "provision_checkout")
    try:
        return checkout.expected_role_policy("775261844268")
    finally:
        sys.modules.pop("provision_checkout", None)


def _checkout_simulated_tables() -> list:
    """The ARN list `provision_checkout.verify` simulates against, read off its source."""
    source = CHECKOUT_SCRIPT.read_text(encoding="utf-8")
    body = source.split("    tables = [", 1)[1].split("]", 1)[0]
    checkout = _load(CHECKOUT_SCRIPT, "provision_checkout")
    namespace = {
        "REGION": checkout.REGION, "acct": "775261844268",
        "PAYMENT_ATTEMPTS_TABLE": checkout.PAYMENT_ATTEMPTS_TABLE,
        "COMMERCE_KEYS_TABLE": checkout.COMMERCE_KEYS_TABLE,
        "COUPONS_TABLE": getattr(checkout, "COUPONS_TABLE", "stack-wecare-digital-CouponsTable"),
        "GIFT_CARDS_TABLE": getattr(checkout, "GIFT_CARDS_TABLE",
                                    "stack-wecare-digital-GiftCardsTable"),
        "RAZORPAY_API_SECRET": getattr(checkout, "RAZORPAY_API_SECRET",
                                       "wecare/razorpay/api"),
        "ORDERS_TABLE": getattr(checkout, "ORDERS_TABLE",
                                "stack-wecare-digital-OrderTable"),
        "CONTACTS_TABLE": getattr(checkout, "CONTACTS_TABLE",
                                  "stack-wecare-digital-ContactsTable"),
    }
    try:
        return eval("[" + body + "]", {"__builtins__": {}}, namespace)  # noqa: S307
    finally:
        sys.modules.pop("provision_checkout", None)


# ── 52 / 52a / 52b: SEAM-C3b, landed ──────────────────────────────────────────

def test_checkout_role_does_not_gain_the_custom_coupons_table():
    """Website coupons are Wix-authoritative; checkout must not depend on the legacy custom store."""
    policy = _checkout_policy()
    resources = [r for s in policy["Statement"] for r in s.get("Resource", [])]
    assert COUPONS_TABLE_ARN not in resources


def test_the_iam_simulation_covers_every_action_the_policy_grants():
    """MEDIUM-18. The script's job is MEASURING this role, and both of its lists are hard-coded,
    so a grant it does not simulate is granted and never measured - while the simulation keeps
    reporting a clean verdict. This makes the grant and its check structurally unable to drift.

    DELIBERATELY NOT `xfail`, unlike tests 52 and 52b either side of it, and the distinction is
    the point. This is a SUBSET relation, so it holds today - vacuously, because nothing has
    been added yet - and it is the gate that fires the moment SEAM-C3b adds the `CouponsTable`
    grant WITHOUT extending `_SIMULATED_ACTIONS` and the simulated table list. Marking it
    `xfail(strict=True)` would make it xpass immediately and, worse, would switch off the only
    assertion that catches the half-done seam. Tests 52 and 52b assert facts that are absent
    until the producer lands; this one asserts a relation that must never break.
    """
    checkout = _load(CHECKOUT_SCRIPT, "provision_checkout")
    try:
        simulated = set(checkout._SIMULATED_ACTIONS)
    finally:
        sys.modules.pop("provision_checkout", None)

    policy = _checkout_policy()
    granted = {action for statement in policy["Statement"]
               for action in statement["Action"] if action.startswith("dynamodb:")}
    assert granted <= simulated, f"granted but never simulated: {sorted(granted - simulated)}"

    policy_tables = {resource for statement in policy["Statement"]
                     for resource in statement["Resource"] if ":table/" in resource}
    assert policy_tables <= set(_checkout_simulated_tables()), (
        f"in the policy but not simulated: "
        f"{sorted(policy_tables - set(_checkout_simulated_tables()))}")


def test_delete_item_is_still_denied_on_the_payment_attempt_and_keys_tables():
    """The other half of extending `_SIMULATED_ACTIONS`: the new action must come back DENIED on
    the two existing tables, which `provision_checkout.py`'s own policy comment promises - "No
    DeleteItem: a checkout never deletes a payment attempt or a reservation". So the simulation
    pins both the new permission and the existing refusal."""
    checkout = _load(CHECKOUT_SCRIPT, "provision_checkout")
    try:
        assert "dynamodb:DeleteItem" in checkout._SIMULATED_ACTIONS
        attempts_arn = (f"arn:aws:dynamodb:{checkout.REGION}:775261844268:table/"
                        f"{checkout.PAYMENT_ATTEMPTS_TABLE}")
        keys_arn = (f"arn:aws:dynamodb:{checkout.REGION}:775261844268:table/"
                    f"{checkout.COMMERCE_KEYS_TABLE}")
    finally:
        sys.modules.pop("provision_checkout", None)

    policy = _checkout_policy()
    for statement in policy["Statement"]:
        if "dynamodb:DeleteItem" not in statement.get("Action", []):
            continue
        for forbidden in (attempts_arn, keys_arn):
            assert forbidden not in statement["Resource"], (
                "DeleteItem must stay denied on the payment attempt and reservation tables: a "
                "failed attempt is the evidence that no charge became an order")


# ── 53-55: the coupons role ───────────────────────────────────────────────────

def test_the_coupons_role_is_not_the_shared_fleet_role(role):
    """`wecare-digital-lambda-role` is attached to ~65 functions. A statement added there would
    grant every one of them coupon-table access.

    Over the AST rather than the text, for the same reason the vocabulary gate walks the AST: the
    comment explaining why the shared role must not be touched necessarily contains its name.
    """
    assert role.ROLE_NAME == "wecare-coupons-role"
    tree = ast.parse(ROLE_SCRIPT.read_text(encoding="utf-8"), filename=str(ROLE_SCRIPT))
    docstrings = _docstring_ids(tree)
    offenders = [f"line {node.lineno}: a string literal names the shared role"
                 for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and id(node) not in docstrings and SHARED_FLEET_ROLE in node.value]
    assert not offenders, "\n  ".join(offenders)


def test_the_coupons_policy_scopes_coupon_and_authentication_tables(role):
    document = role.least_privilege_policy()
    resources = [r for s in document["Statement"] for r in s["Resource"]]
    tables = sorted(r for r in resources if ":table/" in r)
    assert tables == sorted([COUPONS_TABLE_ARN, COUPONS_TABLE_ARN + "/index/status-index",
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-CustomerSessionsTable",
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-RateLimitTable"])
    session_grant = next(s for s in document["Statement"] if s["Sid"] == "ValidateCustomerSession")
    assert set(session_grant["Action"]) == {"dynamodb:GetItem", "dynamodb:UpdateItem"}
    staff_grant = next(s for s in document["Statement"] if s["Sid"] == "StaffRoleMembership")
    assert staff_grant["Resource"] == ["arn:aws:cognito-idp:us-east-1:775261844268:userpool/us-east-1_cSx0RHCIR"]
    rate_grant = next(s for s in document["Statement"] if s["Sid"] == "CouponRateLimit")
    assert rate_grant["Action"] == ["dynamodb:UpdateItem"]
    assert role.STATUS_INDEX == "status-index"


def test_the_coupons_policy_has_no_scan_and_no_wildcard_action(role):
    document = role.least_privilege_policy()
    actions = {a for s in document["Statement"] for a in s["Action"]}
    assert actions == {
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
        "dynamodb:Query", "secretsmanager:GetSecretValue",
        "cognito-idp:AdminListGroupsForUser", "cognito-idp:AdminGetUser",
        "logs:CreateLogStream", "logs:PutLogEvents"}
    for forbidden in ("dynamodb:Scan", "dynamodb:*", "*", "secretsmanager:*", "iam:*"):
        assert forbidden not in actions
    for resource in (r for s in document["Statement"] for r in s["Resource"]):
        assert resource != "*", "a wildcard resource"
        assert not resource.endswith(":table/*")


def test_the_coupons_policy_names_only_the_wix_secret_and_by_name(role):
    """A secret NAME, never a value. The six-character suffix wildcard is how Secrets Manager
    names ONE secret, not a widening to all of them."""
    document = role.least_privilege_policy()
    secrets = [r for s in document["Statement"]
               if "secretsmanager:GetSecretValue" in s["Action"] for r in s["Resource"]]
    assert secrets == ["arn:aws:secretsmanager:us-east-1:775261844268:"
                       "secret:wecare/wix/headless-api-key-*"]
    rendered = json.dumps(document)
    for shape in ("rzp_live_", "rzp_test_", "sk-", "AIza", "ghp_", "xoxb-", "AKIA", "ASIA",
                  "sk_live_", "-----BEGIN"):
        assert shape not in rendered, "the policy document carries an issuer-shaped value"
    assert "razorpay" not in rendered.lower(), (
        "nothing in this function's import closure reaches a gateway, so a credential read "
        "would be privilege for code that cannot run")


def test_the_trust_policy_pins_the_source_account(role):
    """Without `aws:SourceAccount` the Lambda service principal is a confused-deputy opening."""
    trust = role.trust_policy()
    assert [((s.get("Condition") or {}).get("StringEquals") or {}).get("aws:SourceAccount")
            for s in trust["Statement"]] == ["775261844268"]
    assert all(s["Principal"] == {"Service": "lambda.amazonaws.com"}
               for s in trust["Statement"])


def test_the_role_provisioner_verifies_what_it_wrote(role):
    """A provisioner that writes a policy and does not read it back has measured nothing, and a
    run that measured nothing must not be indistinguishable from a clean one."""
    body = ROLE_SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert "get_role_policy" in body
    assert "least_privilege_policy()" in body
    assert "dynamodb:Scan" in body, "verify does not re-check the Scan refusal on the live role"
    assert "aws:SourceAccount" in body


def test_both_provisioners_require_apply_and_default_to_a_dry_run(role, table):
    for script in (ROLE_SCRIPT, TABLE_SCRIPT):
        source = script.read_text(encoding="utf-8")
        assert '"--apply", action="store_true"' in source
        assert '"--verify", action="store_true"' in source


# ── 56 / 58: the table ────────────────────────────────────────────────────────

def test_the_coupons_provisioner_asserts_ttl_disabled_and_pitr_enabled(table):
    """TTL disabled is load-bearing: a coupon definition is what a settled order cites, so
    deleting it makes that order unauditable. Asserted in `--verify` rather than merely left
    unset, so enabling it later trips a gate instead of being discovered from a gap."""
    body = TABLE_SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert "describe_time_to_live" in body
    assert "DISABLED" in body
    assert "PointInTimeRecoveryDescription" in body
    assert "ENABLED" in body

    # And the create path turns PITR on rather than assuming the default.
    create_body = (TABLE_SCRIPT.read_text(encoding="utf-8")
                   .split("def create(")[1].split("\ndef ")[0])
    assert "update_continuous_backups" in create_body
    assert "PointInTimeRecoveryEnabled" in create_body
    # No TTL is ever enabled, anywhere in the script.
    tree = ast.parse(TABLE_SCRIPT.read_text(encoding="utf-8"), filename=str(TABLE_SCRIPT))
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update_time_to_live"]


def test_the_table_shape_is_the_documented_one(table):
    assert table.TABLE == "stack-wecare-digital-CouponsTable"
    assert table.KEY_ATTRIBUTE == "couponKey"
    assert table.INDEXES == [("status-index", [("status", "HASH"), ("createdAt", "RANGE")])]
    # Only key-participating attributes may be declared; DynamoDB rejects the rest.
    assert set(table.ATTRIBUTES) == {"couponKey", "status", "createdAt"}


def test_the_table_provisioner_never_deletes_or_retargets(table):
    tree = ast.parse(TABLE_SCRIPT.read_text(encoding="utf-8"), filename=str(TABLE_SCRIPT))
    forbidden = {"delete_table", "update_table", "delete_item", "put_item"}
    offenders = [f"line {node.lineno}: calls {node.func.attr}" for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in forbidden]
    assert not offenders, "\n  ".join(offenders)


def test_both_new_tables_are_allowed_in_the_drift_gate_with_a_reason(drift):
    """57. Neither `Coupon` nor `GiftCard` is a declared model in `amplify/data/resource.ts`, so a
    live table with that name lands in `undeclared_tables_unexpected` and `--gate` exits non-zero.
    The allowance is what makes the disagreement a recorded decision rather than a failure.

    The reason string is asserted non-empty, not merely present. `UNDECLARED_ALLOWED` carries a
    reason per entry precisely because a gate that fires on a decision already taken is a gate
    somebody switches off - an empty reason restores that problem while passing the membership
    check.
    """
    for table in ("CouponsTable", "GiftCardsTable"):
        assert table in drift.UNDECLARED_ALLOWED, (
            f"{table} has no drift-gate allowance, so check_data_model_drift --gate fails once "
            f"the table is live")
        reason = drift.UNDECLARED_ALLOWED[table]
        assert reason.strip(), f"{table} is allowed with no reason recorded"
        assert "provision_" in reason, (
            f"{table}'s reason does not name the provisioner that owns it")


def test_the_table_name_follows_the_drift_script_default_rule(drift):
    """`Coupon -> CouponsTable` under `check_data_model_drift`'s pluralise-and-append rule, so
    no `EXPLICIT_TABLE` entry is needed. A name that needs an exception recorded is a name that
    will be got wrong later."""
    assert drift.expected_table("Coupon") == "CouponsTable"
    assert "Coupon" not in drift.EXPLICIT_TABLE
    assert "GiftCard" not in drift.EXPLICIT_TABLE
    assert drift.expected_table("GiftCard") == "GiftCardsTable"


def test_the_role_and_the_table_scripts_agree_with_the_store_module(role, table):
    """Three files name the same table and the same index. A disagreement means the function is
    granted access to a table it does not use, or queries an index that was never created - and
    the second returns an empty result set in production rather than an error."""
    from lambda_utils.ecommerce import coupon_store as cs
    assert cs.DEFAULT_TABLE_NAME == table.TABLE == role.COUPONS_TABLE
    assert cs.STATUS_INDEX == table.INDEXES[0][0] == role.STATUS_INDEX
    assert cs.KEY_ATTRIBUTE == table.KEY_ATTRIBUTE
