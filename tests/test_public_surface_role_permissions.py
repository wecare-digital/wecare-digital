"""The public-surface role's policy must be the calls the scripts make. No more, no less.

WHY THIS EXISTS. `scripts/iam-public-surface-README.md` claims every action in
`iam-public-surface-permissions.json` is a call one of the two deploy scripts actually
makes. That claim was written by reading the source, and reading the source is exactly the
step that does not survive the next edit. When it was checked mechanically, on 2026-09-29,
it was wrong in both directions at once:

  * MISSING `apigateway:DELETE`. `deploy_mcp_server.py` calls `delete_route_settings` to
    drop throttle entries left behind by deleted routes - it has to, because UpdateStage
    validates the merged map and a stale key makes it unwritable. Without the grant, an
    `apply` run fails with AccessDenied AFTER `provision_legacy_redirects.py` has already
    rewritten the live Amplify rules. A half-applied deploy is the worst outcome available
    to this workflow, and it was one retired route away.
  * GRANTED BUT NEVER CALLED: `lambda:GetPolicy` and `lambda:GetAlias`. The README
    explained GetPolicy as what makes re-running idempotent. It is not: `add_permission`
    is wrapped in `except ResourceConflictException`. The grant was unused and the
    documented reason for it was fiction.

Neither is catastrophic on its own. Together they are the reason a hand-checked permission
list is not evidence. This test derives the list from the boto3 calls in the two scripts,
so adding a call fails until the policy and the README catch up, and removing one fails
until the grant goes.

No AWS call is made and no credential is read.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_FILE = ROOT / "scripts" / "iam-public-surface-permissions.json"
READ_POLICY_FILE = ROOT / "scripts" / "iam-public-surface-read-permissions.json"
WORKFLOW = ROOT / ".github" / "workflows" / "public-surface-deploy.yml"

#: Which boto3 client each local variable holds, per script. Declared rather than inferred:
#: an inference that silently fails to spot a client would make this test pass by seeing
#: nothing, which is the failure mode it is here to prevent.
CLIENT_VARS = {
    "scripts/deploy_mcp_server.py": {"lam": "lambda", "api": "apigatewayv2", "amp": "amplify"},
    "scripts/provision_legacy_redirects.py": {"client": "amplify"},
}

#: (service, boto3 method) -> the IAM action it authorises against.
#:
#: API Gateway is the one that surprises people: its control plane, v1 and v2 alike, is
#: authorised as `apigateway:` plus an HTTP VERB. There is no `apigatewayv2:` IAM prefix,
#: so a policy naming `apigatewayv2:GetRoutes` is not tighter, it is malformed.
CALL_TO_ACTION = {
    ("lambda", "get_function"): "lambda:GetFunction",
    ("lambda", "get_function_configuration"): "lambda:GetFunctionConfiguration",
    # Both waiters used here poll GetFunctionConfiguration.
    ("lambda", "get_waiter"): "lambda:GetFunctionConfiguration",
    ("lambda", "create_function"): "lambda:CreateFunction",
    ("lambda", "update_function_code"): "lambda:UpdateFunctionCode",
    ("lambda", "update_function_configuration"): "lambda:UpdateFunctionConfiguration",
    ("lambda", "publish_version"): "lambda:PublishVersion",
    ("lambda", "create_alias"): "lambda:CreateAlias",
    ("lambda", "update_alias"): "lambda:UpdateAlias",
    ("lambda", "add_permission"): "lambda:AddPermission",
    ("apigatewayv2", "get_integrations"): "apigateway:GET",
    ("apigatewayv2", "get_routes"): "apigateway:GET",
    ("apigatewayv2", "get_stage"): "apigateway:GET",
    ("apigatewayv2", "create_integration"): "apigateway:POST",
    ("apigatewayv2", "create_route"): "apigateway:POST",
    ("apigatewayv2", "update_route"): "apigateway:PATCH",
    ("apigatewayv2", "update_stage"): "apigateway:PATCH",
    ("apigatewayv2", "delete_route_settings"): "apigateway:DELETE",
    ("amplify", "get_app"): "amplify:GetApp",
    ("amplify", "update_app"): "amplify:UpdateApp",
}

#: Calls that pass an execution role to Lambda, and therefore need iam:PassRole. It is not
#: a boto3 method of its own, which is precisely why it is easy to forget.
PASS_ROLE_CALLS = {("lambda", "create_function"), ("lambda", "update_function_configuration")}

# Additional non-mutating permissions used by least-privilege-and-catalog-migration.yml,
# which deliberately reuses the public-surface read role rather than a write-capable role.
AUXILIARY_READ_ACTIONS = {"iam:GetRolePolicy", "iam:SimulateCustomPolicy"}

def _is_read(action: str) -> bool:
    """`Get*`, plus API Gateway's single coarse read verb.

    API Gateway authorises its control plane by HTTP verb, so its read action is literally
    `apigateway:GET` rather than a `Get`-prefixed operation name.
    """
    service, verb = action.split(":", 1)
    return verb.startswith("Get") or (service, verb) == ("apigateway", "GET")


def test_every_boto3_client_in_the_two_scripts_is_declared_here():
    """CLIENT_VARS is how this test finds calls, so an undeclared client is a blind spot.

    The scan below looks for `<variable>.<method>(` using the variables named in CLIENT_VARS.
    Rename `lam` to `lambda_client` and the scan finds nothing for it, the derived action set
    shrinks, and `test_policy_grants_exactly_what_the_scripts_call` starts reporting the whole
    lambda grant as unused - or worse, passes while a new call goes ungranted. So every
    `boto3.client(...)` in the two scripts has to be accounted for here.
    """
    for relpath, variables in CLIENT_VARS.items():
        source = (ROOT / relpath).read_text(encoding="utf-8")
        for variable, service in re.findall(
            r'(\w+)\s*=\s*boto3\.client\(\s*"([a-z0-9]+)"', source
        ):
            assert variables.get(variable) == service, (
                f"{relpath} assigns a {service} client to `{variable}`, which CLIENT_VARS does "
                f"not map to {service}. Add it, or this test silently stops seeing those calls."
            )
        # `def amplify(): return boto3.client("amplify")` - no assignment to match, so the
        # service itself must be covered by at least one declared variable.
        for service in re.findall(r'return\s+boto3\.client\(\s*"([a-z0-9]+)"', source):
            assert service in variables.values(), (
                f"{relpath} returns a {service} client from a helper and no variable in "
                f"CLIENT_VARS holds one"
            )


def _calls() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    unknown: set[str] = set()
    for relpath, variables in CLIENT_VARS.items():
        source = (ROOT / relpath).read_text(encoding="utf-8")
        for variable, service in variables.items():
            for method in re.findall(rf"\b{variable}\.([a-z_][a-z0-9_]*)\(", source):
                if (service, method) in CALL_TO_ACTION:
                    found.add((service, method))
                else:
                    unknown.add(f"{relpath}: {variable}.{method}() [{service}]")
    assert not unknown, (
        "unrecognised AWS calls. Map each to the IAM action it needs in CALL_TO_ACTION and "
        "grant it in scripts/iam-public-surface-permissions.json, or the deploy fails with "
        "AccessDenied at exactly the wrong moment:\n  " + "\n  ".join(sorted(unknown))
    )
    return found


@pytest.fixture(scope="module")
def policy() -> dict:
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


def _granted(policy: dict) -> set[str]:
    granted: set[str] = set()
    for statement in policy["Statement"]:
        assert statement["Effect"] == "Allow", "a Deny here would need its own reasoning"
        action = statement["Action"]
        granted |= {action} if isinstance(action, str) else set(action)
    return granted


def test_policy_grants_exactly_what_the_scripts_call(policy):
    calls = _calls()
    needed = {CALL_TO_ACTION[call] for call in calls}
    if calls & PASS_ROLE_CALLS:
        needed.add("iam:PassRole")

    granted = _granted(policy)

    missing = sorted(needed - granted)
    assert not missing, (
        "the scripts make these calls and the policy does not allow them: " + ", ".join(missing)
    )

    unused = sorted(granted - needed)
    assert not unused, (
        "granted but never called. Either the call went away and the grant should follow, or "
        "the README's account of why it is there is fiction: " + ", ".join(unused)
    )


def test_pass_role_is_confined_to_lambda(policy):
    statements = [s for s in policy["Statement"] if "iam:PassRole" in
                  ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])]
    assert len(statements) == 1
    statement = statements[0]
    assert statement["Resource"].endswith(":role/wecare-digital-lambda-role"), (
        "PassRole must name the one execution role"
    )
    condition = statement.get("Condition", {}).get("StringEquals", {})
    assert condition.get("iam:PassedToService") == "lambda.amazonaws.com", (
        "without this condition the role can hand the execution role to any service"
    )


def test_nothing_is_granted_on_every_resource(policy):
    for statement in policy["Statement"]:
        resources = statement["Resource"]
        for resource in [resources] if isinstance(resources, str) else resources:
            assert resource != "*", f'{statement["Sid"]} grants on every resource'
            assert resource.startswith("arn:aws:"), f'{statement["Sid"]}: {resource!r}'


def test_destructive_api_gateway_verb_reaches_route_settings_only(policy):
    """DELETE is needed, and it is one wildcard away from deleting the API.

    `delete_route_settings` is the only destructive call either script makes. Granting
    `apigateway:DELETE` on `/apis/zllr9lrg7j*` - the shape the rest of the policy uses -
    would also permit deleting every route, every integration and the API itself, which is
    the whole public surface of this project.
    """
    for statement in policy["Statement"]:
        actions = ([statement["Action"]] if isinstance(statement["Action"], str)
                   else statement["Action"])
        if "apigateway:DELETE" not in actions:
            continue
        resources = statement["Resource"]
        for resource in [resources] if isinstance(resources, str) else resources:
            assert resource.endswith("/routesettings/*"), (
                f"apigateway:DELETE is scoped to {resource!r}, which reaches more than the "
                "stale route settings it exists for"
            )


def test_read_document_is_exactly_the_read_half_of_the_write_document(policy):
    """The safe half must be the same grants minus the writes. Derived, not transcribed.

    `tests/test_github_oidc_trust_policy.py` asserts the read document contains only reads.
    That catches a write leaking in; it cannot catch a read being LEFT OUT, and leaving one
    out fails quietly in the worst way. `lambda:GetFunction` is the example: the
    stale-catalogue check downloads the deployed bundle to compare its page list against
    `config/public-pages.json`, so without that grant the check which exists to catch a
    retired URL still being advertised cannot run at all - and a check that cannot run looks
    exactly like a check that passed.

    So the read document is pinned to a derived set: every action the write role holds whose
    verb is a read. Equality in both directions, so it can neither drift ahead of the write
    role nor fall behind it.
    """
    read_doc = json.loads(READ_POLICY_FILE.read_text(encoding="utf-8"))
    write_actions = _granted(policy)
    expected = {action for action in write_actions if _is_read(action)} | AUXILIARY_READ_ACTIONS
    assert _granted(read_doc) == expected, (
        "the read document is not the read half of the write document. Expected "
        f"{sorted(expected)}"
    )


def test_the_workflow_assumes_the_write_role_only_where_it_writes():
    """The split has to be wired, not just documented.

    Two roles in two files prove nothing if the verify job still assumes the write one. This
    reads the workflow: `verify` and `confirm` must assume the READ variable, `apply` the
    write variable, `confirm` must depend on `apply` (evidence after the fact, on a
    credential that could not have produced it), and no job holding the read credential may
    run a script in a mode that writes.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    def assumed_role(job: dict) -> str | None:
        for step in job["steps"]:
            role = (step.get("with") or {}).get("role-to-assume")
            if role:
                return role
        return None

    assert "READ_ROLE_ARN" in (assumed_role(jobs["verify"]) or ""), "verify must use the read role"
    assert "READ_ROLE_ARN" in (assumed_role(jobs["confirm"]) or ""), "confirm must use the read role"
    apply_role = assumed_role(jobs["apply"]) or ""
    assert "PUBLIC_SURFACE_ROLE_ARN" in apply_role and "READ" not in apply_role, (
        "apply must use the write role"
    )
    assert jobs["confirm"].get("needs") == "apply" or "apply" in (jobs["confirm"].get("needs") or []), (
        "confirm must run after apply, or it is confirming the state before the deploy"
    )

    # Matched against the script invocation rather than the bare string "--apply", because the
    # failure messages in these jobs legitimately mention `-f action=apply` as the next step.
    for name in ("verify", "confirm"):
        for step in jobs[name]["steps"]:
            run = step.get("run") or ""
            for line in run.splitlines():
                if "provision_legacy_redirects.py" in line:
                    assert "--apply" not in line, f"{name} writes redirects: {line.strip()}"
                if "deploy_mcp_server.py" in line:
                    assert "--verify" in line, (
                        f"{name} runs deploy_mcp_server.py without --verify, which deploys: "
                        f"{line.strip()}"
                    )
