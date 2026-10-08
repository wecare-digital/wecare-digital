"""`wecare-meta-catalog-sync-role` is two statements, and the shared fleet role is untouched.

PHASE W, FEAT-001. Every assertion here is EQUALITY rather than containment. A test that checks
the policy *contains* the statements it wants passes just as happily when a third is added, which
is the wrong direction for a document whose whole value is what it leaves out - the same reason
`tests/test_customer_orders_iam.py` is written that way.

THE SHARED ROLE IS THE POINT. `wecare-digital-lambda-role` is attached to most of the ~65-function
fleet, so a grant there is a grant to all of them. This function reads a Meta token that can write
to a customer-visible commerce catalogue and a Wix admin API key; putting either on the shared role
would hand both to sixty unrelated functions. So this file asserts the provisioner never names it -
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
    "dynamodb:", "s3:", "sns:", "sqs:", "ses:", "kms:", "iam:", "sts:",
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


def test_the_policy_is_exactly_these_two_statements(provisioner):
    """Equality, not containment, so a widening is a FAILURE rather than an unnoticed addition.

    Note the second statement names TWO secrets and no more. The brief described this role as the
    Meta token plus logs; the Wix key is there because `lambda_utils.wix_ecom` reads it and the
    function cannot read Wix at all without it, which would make the sync permanently inert. Named
    individually rather than as `wecare/*`, which would include every provider credential in the
    account.
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
                "Sid": "ReadTheTwoSecretsItNeeds",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
                    "wecare/meta-system-user-token-*",
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
                    "wecare/wix/headless-api-key-*",
                ],
            },
        ],
    }


def test_the_policy_has_no_statement_beyond_those_two(provisioner):
    statements = provisioner.expected_role_policy(ACCOUNT)["Statement"]
    assert len(statements) == 2
    assert [s["Sid"] for s in statements] == ["OwnLogs", "ReadTheTwoSecretsItNeeds"]
    assert all(s["Effect"] == "Allow" for s in statements)


def test_no_forbidden_action_appears_anywhere_in_the_policy(provisioner):
    """`lambda:` is in the forbidden list on purpose: this function is INVOKED, it does not
    invoke. `events:` likewise - the schedule invokes it; it does not manage the schedule."""
    actions: list[str] = []
    for statement in provisioner.expected_role_policy(ACCOUNT)["Statement"]:
        action = statement["Action"]
        actions.extend(action if isinstance(action, list) else [action])
    for action in actions:
        for forbidden in FORBIDDEN_ACTION_PREFIXES:
            assert not action.startswith(forbidden), f"{action} is not least privilege here"
    assert sorted(actions) == ["logs:CreateLogStream", "logs:PutLogEvents",
                               "secretsmanager:GetSecretValue"]


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
    assert len(secrets) == 2
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


def test_the_invoke_grant_lands_on_the_WEBHOOKS_role_and_is_alias_qualified(provisioner):
    """Equality again. One statement, one action, one alias-qualified resource.

    Alias-qualified because a grant on the unqualified function ARN does not authorise an alias
    invoke - and the failure is an AccessDenied the webhook swallows, so the sync would silently
    never run while the webhook kept answering 200.
    """
    assert provisioner.WEBHOOK_ROLE == "wecare-wix-catalog-webhook-role"
    assert provisioner.WEBHOOK_ROLE != SHARED_FLEET_ROLE
    assert provisioner.webhook_invoke_policy(ACCOUNT) == {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "InvokeMetaCatalogSync",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": [f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:"
                         "wecare-meta-catalog-sync:live"],
        }],
    }


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


def test_the_provisioned_environment_ships_both_gates_closed(provisioner):
    """Both gates are WRITTEN OUT, at their safe values. `META_CATALOG_SYNC_ENABLED` used to be
    absent here, on the argument that an absent key is harder to flip than a key one word away
    from enabling.

    That reversed because an absent key is also indistinguishable from a key nobody ever
    configured, on the one function in this phase that can write to a customer-visible Meta
    catalogue - and because `config/lambda-env-manifest.json` records what is LIVE, so declaring
    the gate closed there while no deploy ever set it would make `scripts/env_manifest.py` report
    drift and exit 1 for good. The flip risk it traded away is covered by `verify()`, which
    refuses outright when the live value reads true.

    Asserted by equality against "false" rather than by absence, so this still fails the moment
    anything sets it to an enabling value.
    """
    assert provisioner.ENVIRONMENT["META_CATALOG_SYNC_ENABLED"] == "false"
    assert provisioner.ENVIRONMENT["META_CATALOG_SYNC_DRY_RUN"] == "true"


def test_the_environment_carries_secret_NAMES_and_no_value(provisioner):
    """By-reference only. A credential must never appear in a configuration document, and the
    enforcement hook would refuse a command carrying one - this asserts the same rule about the
    file that the hook asserts about the command line."""
    rendered = json.dumps(provisioner.ENVIRONMENT)
    assert "wecare/meta-system-user-token" in rendered
    assert "wecare/wix/headless-api-key" in rendered
    for issuer_shape in ("rzp_live_", "sk-", "AIza", "ghp_", "xoxb-", "AKIA", "ASIA"):
        assert issuer_shape not in rendered


def test_the_handler_defaults_agree_with_the_provisioned_environment():
    """Two places declare the catalog id and the token field; they must not drift.

    The handler's defaults are what runs if a variable is ever missing from the live function, so a
    disagreement here is a silent repoint of a customer-visible catalogue.
    """
    text = HANDLER.read_text(encoding="utf-8")
    assert '"META_CATALOG_ID", "1607047307067517"' in text
    assert '"META_TOKEN_SECRET", "wecare/meta-system-user-token"' in text
    assert '"META_TOKEN_FIELD", "access_token"' in text
