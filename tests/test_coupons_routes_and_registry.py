"""The seven coupon routes: who authenticates them, and what the integration points at.

Design reference: the coupons and gift-cards design note of 2026-10-01 (`coupons-20261001.md`),
sections 5.1 and 5.1.1, and the test list in section 7 (tests 62-64).

Test 65 - that all three new functions resolve in `deploy_all_lambdas.SPECS` - is now here, added
by the shared-gate step alongside the `scripts/deploy_all_lambdas.py` edit it asserts. It lives in
this one file for both documents rather than being duplicated in the gift-card suite, for the same
reason the registry edit itself is made once: one file, one session, one commit.

Why test 62 exists at all
-------------------------
All seven routes are created with `AuthorizationType=NONE` and no authorizer, because this account
has zero API Gateway authorizers across 361 routes. `00-current-owner-overrides.md` is explicit
that the gateway field cannot distinguish an intentionally public signed webhook from an
accidentally public API - so the authorization claim cannot be read off the gateway and has to be
asserted here, at the only place that actually enforces it: before the first table access in each
route function.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"
ROUTES_SCRIPT = ROOT / "scripts" / "provision_coupons_routes.py"

SOURCE = HANDLER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(HANDLER))

DOCUMENTED_ROUTES = (
    "POST /coupons",
    "GET /coupons/{code}",
    "GET /coupons",
    "POST /coupons/{code}/deactivate",
    "POST /coupons/validate",
    "POST /coupons/hold",
    "POST /coupons/release",
)

STAFF_ROUTES = ("POST /coupons", "GET /coupons/{code}", "GET /coupons",
                "POST /coupons/{code}/deactivate")
CUSTOMER_ROUTES = ("POST /coupons/validate", "POST /coupons/hold", "POST /coupons/release")


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_coupons_routes", ROUTES_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_coupons_routes"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_coupons_routes", None)


@pytest.fixture(scope="module")
def route_map():
    """`ROUTE_HANDLERS` read off the handler's AST, with no import and so no boto3 or AWS."""
    assignment = next(node for node in ast.walk(TREE)
                      if isinstance(node, ast.AnnAssign)
                      and isinstance(node.target, ast.Name)
                      and node.target.id == "ROUTE_HANDLERS")
    return ast.literal_eval(assignment.value)


def _function(name: str) -> ast.FunctionDef:
    return next(node for node in ast.walk(TREE)
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _first_line(function: ast.FunctionDef, predicate) -> int:
    """The earliest line in `function` at which `predicate` holds for a call node."""
    lines = [node.lineno for node in ast.walk(function)
             if isinstance(node, ast.Call) and predicate(node)]
    return min(lines) if lines else 10 ** 9


def _is_auth(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id in ("_staff", "_customer")


def _is_table_access(node: ast.Call) -> bool:
    """Any call that reaches storage: building the table resource, or a store function."""
    if isinstance(node.func, ast.Name) and node.func.id in ("_coupons_table", "_table"):
        return True
    return (isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "coupon_store")


# ── 62 ────────────────────────────────────────────────────────────────────────

def test_the_handler_declares_exactly_the_seven_documented_routes(route_map):
    assert tuple(route_map) == DOCUMENTED_ROUTES
    for route, (identity, function_name) in route_map.items():
        assert identity in ("staff", "customer")
        assert _function(function_name) is not None


@pytest.mark.parametrize("route", DOCUMENTED_ROUTES)
def test_every_coupon_route_authenticates_before_touching_the_table(route, route_map):
    """The five staff routes call `require_auth` and the two customer routes resolve a session,
    in both cases BEFORE any table access.

    Line order rather than mere presence: an auth check that runs after a read has already
    leaked whether a code exists, which on `/coupons/validate` is the enumeration this endpoint
    is rate-limited against in the first place.
    """
    identity, function_name = route_map[route]
    function = _function(function_name)

    auth_line = _first_line(function, _is_auth)
    table_line = _first_line(function, _is_table_access)
    assert auth_line < 10 ** 9, f"{function_name} never authenticates"
    assert auth_line < table_line, (
        f"{function_name} touches storage at line {table_line} before authenticating at "
        f"line {auth_line}")

    calls = {node.func.id for node in ast.walk(function)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    expected = "_staff" if identity == "staff" else "_customer"
    assert expected in calls, f"{function_name} is a {identity} route but never calls {expected}"


def test_the_staff_check_is_cognito_require_auth_with_a_role():
    """`middleware.require_auth`, with a role rather than merely "any valid token"."""
    staff = _function("_staff")
    rendered = ast.unparse(staff)
    assert "middleware.require_auth(event, STAFF_ROLE)" in rendered
    assert "STAFF_ROLE = \"Operator\"" in SOURCE or "STAFF_ROLE = 'Operator'" in SOURCE


def test_the_customer_id_comes_from_the_session_and_never_from_the_body():
    """An id a browser can set is an id an attacker can set, and here it would hand one customer
    another's per-customer coupon allowance."""
    assert "CUSTOMER_BODY_FIELDS = (\"code\", \"cartId\")" in SOURCE
    for name in ("_validate", "_hold"):
        rendered = ast.unparse(_function(name))
        assert "session.customer_id" in rendered
        assert 'body.get("customerId")' not in rendered
        assert 'body["customerId"]' not in rendered


def test_the_validate_route_is_rate_limited_and_the_others_need_not_be():
    """With WAF removed there is no per-IP layer in front of these routes, and
    `/coupons/validate` is the one a stranger could grind to enumerate valid codes."""
    validate = ast.unparse(_function("_validate"))
    assert "rate_limit.check_rate_limit(" in validate


def test_the_validate_route_returns_a_verdict_and_no_amount():
    """The security boundary. The amount is the checkout's to compute (`coupon_store.discount_paise`
    on the native checkout path); a validate endpoint returning a discount figure would become a
    number a browser could quote."""
    validate = _function("_validate")
    returned = [node for node in ast.walk(validate) if isinstance(node, ast.Return)]
    assert returned
    for node in returned:
        rendered = ast.unparse(node)
        for money in ("Paise", "paise", "amount", "Amount", "discount", "Discount", "total"):
            assert money not in rendered, f"the validate response mentions {money!r}"
        assert "verdict" in rendered


def test_there_is_no_delete_route():
    """Deactivation is reversible and preserves the audit trail; deletion destroys the
    definition a settled order references, so no delete is wired, deliberately."""
    assert not [route for route in DOCUMENTED_ROUTES if route.startswith("DELETE")]
    assert "DELETE" not in str(DOCUMENTED_ROUTES)


# ── 63 ────────────────────────────────────────────────────────────────────────

def test_the_route_integration_targets_the_live_alias(provisioner):
    """`:live`, never `$LATEST`.

    `lambda-snapstart-deploy.md`: 58 of 65 functions are invoked through their `live` alias, so
    a `$LATEST` change does not reach production until a version is published and the alias
    moves. An integration on `$LATEST` would serve whatever was uploaded last, which is the
    opposite of that control.
    """
    assert provisioner.function_arn(qualified=True).endswith(
        ":function:wecare-coupons:live")

    # Over the AST, not the text: the comment explaining why `$LATEST` must not be used
    # necessarily contains it, and a text search makes the explanation indistinguishable from
    # the offence. The same trap `tests/test_payment_vocabulary_at_decision_points.py` records.
    tree = ast.parse(ROUTES_SCRIPT.read_text(encoding="utf-8"), filename=str(ROUTES_SCRIPT))
    docstrings = _docstring_ids(tree)
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and id(node) not in docstrings and "$LATEST" in node.value]
    assert not offenders, f"a $LATEST literal appears at line(s) {offenders}"

    source = ROUTES_SCRIPT.read_text(encoding="utf-8")
    assert 'IntegrationType="AWS_PROXY"' in source
    assert 'PayloadFormatVersion="2.0"' in source
    assert "function_arn(qualified=True)" in source


def _docstring_ids(tree: ast.Module) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = (node.body or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def test_the_invoke_permission_is_qualified_to_the_alias():
    """A function-level statement does not authorise an alias invoke, and the failure is a 500
    with no Lambda log line at all, because the function is never entered."""
    tree = ast.parse(ROUTES_SCRIPT.read_text(encoding="utf-8"), filename=str(ROUTES_SCRIPT))
    grants = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "add_permission"]
    assert grants, "the provisioner grants no invoke permission at all"
    for call in grants:
        kwargs = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
        assert kwargs.get("Qualifier") == "LIVE_ALIAS"
        assert kwargs.get("Principal") == "'apigateway.amazonaws.com'"
        assert kwargs.get("SourceArn") == "source_arn(key)"


def test_the_source_arn_is_scoped_to_the_coupons_paths(provisioner):
    """Not `{API_ID}/*/*`, which would authorise any method on any of the 361 routes."""
    for route in DOCUMENTED_ROUTES:
        arn = provisioner.source_arn(route)
        assert arn.endswith("/coupons*")
        assert provisioner.API_ID in arn
        assert not arn.endswith("/*")


# ── 64 ────────────────────────────────────────────────────────────────────────

def test_the_provisioner_creates_exactly_the_seven_documented_routes(provisioner):
    """An exact tuple, not a membership check. The interesting failure is an ADDED route - a
    `{proxy+}` or a `DELETE` would widen the public surface past the design."""
    assert provisioner.ROUTE_KEYS == DOCUMENTED_ROUTES
    for key in provisioner.ROUTE_KEYS:
        method = key.split(" ", 1)[0]
        assert method in ("GET", "POST"), f"{key} widens the surface past GET/POST"
        assert "proxy" not in key
        assert "+" not in key


def test_the_provisioner_and_the_handler_agree_on_the_route_set(provisioner, route_map):
    """One list, two consumers. A route the provisioner creates and the handler cannot serve is
    a 404 that looks like an outage; the reverse is dead code."""
    assert set(provisioner.ROUTE_KEYS) == set(route_map)


def test_route_creation_never_deletes_or_retargets(provisioner):
    """Additive only. 361 pre-existing routes belong to other functions.

    Over the AST, because the docstring that promises this necessarily names the calls it
    forbids - a text search would flag its own explanation.
    """
    tree = ast.parse(ROUTES_SCRIPT.read_text(encoding="utf-8"), filename=str(ROUTES_SCRIPT))
    forbidden = {"delete_route", "delete_integration", "update_route", "update_integration",
                 "delete_function", "delete_alias", "delete_permission", "delete_api"}
    offenders = [f"line {node.lineno}: calls {node.func.attr}"
                 for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in forbidden]
    assert not offenders, "\n  ".join(offenders)


def test_the_provisioner_dry_run_is_the_default(provisioner):
    """`--apply` is required. A provisioner whose default mutates the account is one typo away
    from an unplanned change."""
    source = ROUTES_SCRIPT.read_text(encoding="utf-8")
    assert '"--apply", action="store_true"' in source
    assert "--dry-run" not in source, (
        "two spellings of the same idea: dry run is the default, so there is nothing to opt into")


def test_verify_reads_routes_integration_and_every_invoke_statement_back(provisioner):
    """A missing route, a route pointed at someone else's integration, a statement scoped wider
    than its route, or an EXTRA statement nobody here created must all FAIL rather than be
    inferred from the routes existing."""
    body = ROUTES_SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert "live_policy_statements()" in body
    assert "route_statement_id(" in body
    assert "_statement_source_arn(" in body
    assert "unexpected" in body, "an extra invoke statement would pass unnoticed"
    assert "AuthorizerId" in body, "an authorizer added by someone else would pass unnoticed"


# ── 65: the coupon deploy registry ───────────────────────────────────────────

NEW_FUNCTIONS = ("wecare-coupons",)


@pytest.fixture(scope="module")
def deploy_specs():
    """`deploy_all_lambdas.SPECS`, by name. Loaded offline - no AWS call, no packaging."""
    path = ROOT / "scripts" / "deploy_all_lambdas.py"
    spec = importlib.util.spec_from_file_location("deploy_all_lambdas_registry", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_all_lambdas_registry"] = module
    spec.loader.exec_module(module)
    try:
        yield {s.name: s for s in module.SPECS}
    finally:
        sys.modules.pop("deploy_all_lambdas_registry", None)


@pytest.mark.parametrize("name", NEW_FUNCTIONS)
def test_the_new_function_is_deployable_at_all(name, deploy_specs):
    """`deploy_all_lambdas.py` deploys from an explicit list, so a name absent from it is not
    deployable - `deploy_all_lambdas.py wecare-coupons` would resolve nothing and exit having done
    nothing, which looks like a successful run."""
    assert name in deploy_specs, (
        f"{name} is not in SPECS, so it cannot be deployed by any means in this repo")
    assert deploy_specs[name].source.is_dir(), (
        f"{deploy_specs[name].source} does not exist; the Spec points at no source directory")
    assert (deploy_specs[name].source / "handler.py").exists()


@pytest.mark.parametrize("name", NEW_FUNCTIONS)
def test_the_new_function_declares_what_must_create_it_first(name, deploy_specs):
    """The coupon function is provisioned separately, so deploy-all reports it absent until its provisioner has
    run. Without `provisioned_by` that lands in `failed`, and a tally that is never zero stops being
    a signal - the exact reason the field was introduced.

    The referenced scripts have to exist, or the message sends the operator nowhere.
    """
    provisioned_by = deploy_specs[name].provisioned_by
    assert provisioned_by, f"{name} would be reported as a deploy FAILURE until it is created"
    referenced = [word for word in provisioned_by.split() if word.endswith(".py")]
    assert referenced, f"{name}'s provisioned_by names no script"
    for script in referenced:
        assert (ROOT / script).exists(), f"{name} points at {script}, which does not exist"


