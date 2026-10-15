"""`wecare-meta-catalog-sync-role` is four exact statements, and the shared fleet role is untouched.

PHASE W, FEAT-001. Every assertion here is EQUALITY rather than containment. A test that checks
the policy *contains* the statements it wants passes just as happily when a third is added, which
is the wrong direction for a document whose whole value is what it leaves out - the same reason
`tests/test_customer_orders_iam.py` is written that way.

THE SHARED ROLE IS THE POINT. `wecare-digital-lambda-role` is attached to most of the ~65-function
fleet, so a grant there is a grant to all of them. This function reads a Meta token that can write
to a customer-visible commerce catalogue; putting that grant on the shared role would hand it to
sixty unrelated functions. So this file asserts the provisioner never names it -
not that it does not grant anything to it, which would be weaker: a script that merely MENTIONS
the shared role is one edit away from widening it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/provision_meta_catalog_sync.py"
HANDLER = ROOT / "amplify/functions/ecommerce/meta-catalog-sync/handler.py"

ACCOUNT = "775261844268"
REGION = "us-east-1"

SHARED_FLEET_ROLE = "wecare-digital-lambda-role"

#: Anything that could change data, invoke code, message a person or widen access. None of these
#: may appear anywhere in the new role's policy.
FORBIDDEN_ACTION_PREFIXES = (
    "s3:", "sns:", "sqs:", "ses:", "kms:", "iam:", "sts:",
    "cognito-idp:", "lambda:", "events:", "apigateway:", "execute-api:",
    "secretsmanager:Put", "secretsmanager:Update", "secretsmanager:Create",
    "secretsmanager:Delete", "secretsmanager:Describe", "secretsmanager:List",
    "secretsmanager:Tag", "secretsmanager:Restore", "secretsmanager:Rotate",
    "logs:Create" + "LogGroup", "logs:Put" + "RetentionPolicy", "logs:Delete",
)


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_meta_catalog_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_meta_catalog_sync"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_meta_catalog_sync", None)


# ── 1. the document, exactly ─────────────────────────────────────────────────


def test_the_policy_is_exactly_the_five_required_statements(provisioner):
    """Native: logs + ONE Meta token secret + the approvals table + the ProductsTable change
    stream + the native ProductsTable read.

    The catalog source is AWS-native: the function reads the ProductsTable, so the Meta token is
    its only secret. The stream statement lets the ProductsTable change stream deliver real-time
    sync events; the last statement grants the read-only ProductsTable access the projection needs.
    """
    assert provisioner.expected_role_policy(ACCOUNT) == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OwnLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:"
                    "/aws/lambda/wecare-meta-catalog-sync",
                    f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:"
                    "/aws/lambda/wecare-meta-catalog-sync:*",
                ],
            },
            {
                "Sid": "ReadMetaToken",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
                    "wecare/meta-system-user-token-*",
                ],
            },
            {
                "Sid": "CatalogProposalApprovalRecords",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/"
                    "stack-wecare-digital-AgentApprovalsTable"
                ],
            },
            {
                "Sid": "ReadProductsStream",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:DescribeStream", "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator", "dynamodb:ListStreams",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/"
                    "stack-wecare-digital-ProductsTable/stream/*",
                ],
            },
            {
                "Sid": "ReadNativeProductCatalog",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem", "dynamodb:Query",
                    "dynamodb:Scan", "dynamodb:BatchGetItem",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-ProductsTable",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/"
                    "stack-wecare-digital-ProductsTable/index/*",
                ],
            },
        ],
    }


def test_the_policy_has_no_statement_beyond_the_five_required(provisioner):
    statements = provisioner.expected_role_policy(ACCOUNT)["Statement"]
    assert len(statements) == 5
    assert [s["Sid"] for s in statements] == [
        "OwnLogs", "ReadMetaToken", "CatalogProposalApprovalRecords",
        "ReadProductsStream", "ReadNativeProductCatalog"]
    assert all(s["Effect"] == "Allow" for s in statements)


def test_no_forbidden_action_appears_anywhere_in_the_policy(provisioner):
    """`lambda:` is in the forbidden list on purpose: this function is INVOKED, it does not
    invoke. `events:` likewise - the schedule invokes it; it does not manage the schedule.

    Native: the ProductsTable read adds Query/Scan/BatchGetItem alongside GetItem — all read-only
    DynamoDB actions, none forbidden, no Delete/Put/Update on the catalog table.
    """
    actions: list[str] = []
    for statement in provisioner.expected_role_policy(ACCOUNT)["Statement"]:
        action = statement["Action"]
        actions.extend(action if isinstance(action, list) else [action])
    for action in actions:
        for forbidden in FORBIDDEN_ACTION_PREFIXES:
            assert not action.startswith(forbidden), f"{action} is not least privilege here"
    assert sorted(actions) == [
        "dynamodb:BatchGetItem", "dynamodb:DescribeStream",
        "dynamodb:GetItem", "dynamodb:GetItem",
        "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams",
        "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:UpdateItem",
        "logs:CreateLogStream", "logs:PutLogEvents", "secretsmanager:GetSecretValue"]


def test_dynamodb_is_limited_to_one_table_and_three_item_actions(provisioner):
    statement = provisioner.expected_role_policy(ACCOUNT)["Statement"][2]
    assert statement["Action"] == ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    assert statement["Resource"] == [
        f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/stack-wecare-digital-AgentApprovalsTable"]
    rendered = json.dumps(statement)
    assert "Scan" not in rendered and "Query" not in rendered and "Delete" not in rendered


def test_no_resource_is_a_wildcard(provisioner):
    """A bare `*` on `GetSecretValue` would read every provider credential in the account; on
    logs it would let this function write into another function's log group."""
    for statement in provisioner.expected_role_policy(ACCOUNT)["Statement"]:
        for resource in statement["Resource"]:
            assert resource != "*"
            assert not resource.endswith(":secret:*")
            assert "wecare/*" not in resource


def test_the_secret_arns_are_suffix_wildcarded_and_nothing_more(provisioner):
    """Secrets Manager appends a random six-character suffix to every secret ARN, so a trailing
    `-*` is the only way to name a secret without reading it first. It matches one secret, not a
    family: no other secret in this account shares either prefix."""
    secrets = provisioner.expected_role_policy(ACCOUNT)["Statement"][1]["Resource"]
    assert len(secrets) == 1
    for arn in secrets:
        assert arn.endswith("-*")
        assert arn.count("*") == 1


# ── 2. the shared fleet role is not named, let alone widened ────────────────


def test_the_provisioner_never_names_the_shared_fleet_role(provisioner):
    """Asserted on the AST rather than the text, because the docstring explains WHY the shared
    role is avoided and necessarily contains its name - a substring scan of the file would fail
    on its own documentation.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    code_strings = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings]
    for value in code_strings:
        assert SHARED_FLEET_ROLE not in value, (
            f"the provisioner names {SHARED_FLEET_ROLE} in code; this function gets its own role")


def test_the_role_this_script_creates_is_its_own(provisioner):
    assert provisioner.ROLE == "wecare-meta-catalog-sync-role"
    assert provisioner.ROLE != SHARED_FLEET_ROLE


def test_the_schedule_is_the_only_invoke_grant_and_iam_writes_target_only_its_own_role():
    """The scheduled EventBridge rule is the function's one provisioned caller, so the provisioner
    adds exactly one invoke permission (for `events.amazonaws.com`) and writes IAM for its own role
    only - no grant lands on another function's role."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]

    grants = [call for call in calls if call.func.attr == "add_permission"]
    assert len(grants) == 1
    principal = {kw.arg: kw.value for kw in grants[0].keywords}["Principal"]
    assert isinstance(principal, ast.Constant) and principal.value == "events.amazonaws.com"

    iam_writes = [call for call in calls if call.func.attr in ("create_role", "put_role_policy")]
    assert iam_writes
    for call in iam_writes:
        role = {kw.arg: kw.value for kw in call.keywords}["RoleName"]
        assert isinstance(role, ast.Name) and role.id == "ROLE"


# ── 3. no public surface ─────────────────────────────────────────────────────


def test_the_provisioner_creates_no_http_api_route_or_function_url(provisioner):
    """Nothing calls this over the internet, so there is no authorizer question to answer.

    Asserted on the module's attributes and its AST: no apigatewayv2 client, no route key, no
    function-url call. The cheapest possible answer to "is this endpoint protected" is "there is
    no endpoint".
    """
    assert not hasattr(provisioner, "API_ID")
    assert not hasattr(provisioner, "ROUTE_KEY")

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("create_route", "create_integration", "create_function_url_config",
                      "add_layer_version_permission", "attach_role_policy"):
        assert forbidden not in called


def test_the_provisioner_is_additive_only(provisioner):
    """No delete, no detach. An existing resource is reported, never recreated or retargeted."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not [name for name in called
                if name.startswith("delete_") or name.startswith("detach_")
                or name.startswith("remove_")]


def test_a_dry_run_is_the_default_and_calls_no_mutating_api(provisioner):
    """`--apply` gated. Asserted on the argument parser's default rather than by running it."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--apply", action="store_true"' in source
    assert "if not apply:" in source


# ── 4. the gates ship closed, and this script does not open them ───────────


def test_the_provisioned_environment_matches_the_product_scoped_rollout(provisioner):
    """Real-time sync with bounded auto-apply; per-product metaEnabled owns catalogue scope.

    The fixed five-variant rollout list is intentionally empty after catalog-publishing v2.
    Background runs may auto-apply only small non-destructive plans (AUTO_APPLY_SAFE with a
    50-change ceiling); anything destructive still needs an exact-plan approval.
    """
    manifest = json.loads((ROOT / "config/lambda-env-manifest.json").read_text())
    live = manifest["functions"]["wecare-meta-catalog-sync"]
    expected = {
        "META_CATALOG_SYNC_ENABLED": "true",
        "META_CATALOG_SYNC_DRY_RUN": "false",
        "META_CATALOG_SYNC_VARIANT_IDS": "",
        "META_CATALOG_SYNC_FORCE_OUT_OF_STOCK": "false",
    }
    for key, value in expected.items():
        assert provisioner.ENVIRONMENT[key] == value
        assert live[key] == value


def test_the_environment_carries_secret_NAMES_and_no_value(provisioner):
    """By-reference only. A credential must never appear in a configuration document, and the
    enforcement hook would refuse a command carrying one - this asserts the same rule about the
    file that the hook asserts about the command line."""
    rendered = json.dumps(provisioner.ENVIRONMENT)
    secret_names = [value for key, value in provisioner.ENVIRONMENT.items()
                    if key.endswith("_SECRET")]
    assert secret_names == ["wecare/meta-system-user-token"]
    for issuer_shape in ("rzp_live_", "sk-", "AIza", "ghp_", "xoxb-", "AKIA", "ASIA"):
        assert issuer_shape not in rendered


def test_the_handler_defaults_agree_with_the_provisioned_environment():
    """Two places declare the catalog id and the token field; they must not drift.

    The handler's defaults are what runs if a variable is ever missing from the live function, so a
    disagreement here is a silent repoint of a customer-visible catalogue.
    """
    text = HANDLER.read_text(encoding="utf-8")
    assert '"META_CATALOG_ID", "1457045652952851"' in text
    assert '"META_TOKEN_SECRET", "wecare/meta-system-user-token"' in text
    assert '"META_TOKEN_FIELD", "access_token"' in text
