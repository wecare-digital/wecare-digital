#!/usr/bin/env python3
"""Provision the seven `wecare-coupons` HTTP API routes, their integration and their permissions.

Design reference: the coupon design note of 2026-10-01 (`coupons-20261001.md`),
section 5.1.1.

Without this script the function would be deployed with no way to reach it, which is the gap the
design calls out: the deploy sequence is table -> role -> routes -> deploy -> alias -> publish.

| | |
|---|---|
| API | HTTP API `zllr9lrg7j`, the account's only one |
| Stage | `prod`. There is no `$default` stage, so the raw execute-api host needs the `/prod` segment |
| Integration | `AWS_PROXY`, payload format `2.0`, onto `...:function:wecare-coupons:live` |
| Permission | one `lambda:InvokeFunction` statement per route, `SourceArn` scoped to `.../coupons*` |
| Idempotence | an existing route is reported, never recreated or retargeted |

THE INTEGRATION TARGETS THE ALIAS, NOT `$LATEST`
------------------------------------------------
`lambda-snapstart-deploy.md`: 58 of 65 functions are invoked through their `live` alias, and a
`$LATEST` change does not reach production until a version is published and the alias moves. An
integration pointed at `$LATEST` would serve whatever was last uploaded, which is the opposite of
that control. The invoke permission is QUALIFIED to the alias for the same reason - a
function-level statement does not authorise an alias invoke, and the failure mode is a 500 with no
Lambda log line at all, because the function is never entered.

AUTHORIZATION
-------------
All seven routes are created with `AuthorizationType=NONE` and no authorizer, because this account
has zero API Gateway authorizers and this change does not introduce the first one. Authentication
is `middleware.require_auth` on the five staff routes and a customer-session check on the two
customer routes, inside the handler - the same posture as every other route on this API.
`tests/test_coupons_routes_and_registry.py` is where that claim is pinned, because
`00-current-owner-overrides.md` records that the gateway field alone cannot distinguish an
intentionally public route from an accidentally public one.

ADDITIVE ONLY
-------------
361 pre-existing routes belong to other functions. This script never calls `delete_route`,
`delete_integration`, `update_route` or `update_integration`.

Usage:
    python scripts/provision_coupons_routes.py              # dry run, the default
    python scripts/provision_coupons_routes.py --apply
    python scripts/provision_coupons_routes.py --verify
"""

from __future__ import annotations

import argparse

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = "775261844268"

FUNCTION_NAME = "wecare-coupons"
LIVE_ALIAS = "live"

#: The account's single HTTP API ("wecare-digital-api") and its only stage, which auto-deploys.
API_ID = "zllr9lrg7j"
STAGE = "prod"

#: Exactly the seven routes of section 5.1. Deliberately NOT a `{proxy+}`: the surface stays as
#: wide as the design and no wider, so an eighth route cannot appear without a design change.
#: There is no `DELETE /coupons/{code}` - deactivation preserves the definition a settled order
#: references.
ROUTE_KEYS = (
    "POST /coupons",
    "GET /coupons/{code}",
    "GET /coupons",
    "POST /coupons/{code}/deactivate",
    "POST /coupons/validate",
    "POST /coupons/hold",
    "POST /coupons/release",
)

#: One statement per route, scoped to this API's coupon paths on this stage. Narrower than
#: `{API_ID}/*/*`, which would authorise any method on any of the 361 routes.
SOURCE_ARN_PREFIX = f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{API_ID}"


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def lam():
    return boto3.client("lambda", region_name=REGION)


def function_arn(*, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FUNCTION_NAME}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def source_arn(route_key: str) -> str:
    """The source ARN for one route key, scoped to the coupons path family.

    `.../zllr9lrg7j/*/*/coupons*` rather than a per-route literal: a templated route key
    (`{code}`) is presented by API Gateway with the resolved value substituted, so a literal
    would not match the request it is meant to authorise.
    """
    method = route_key.split(" ", 1)[0]
    if method not in ("GET", "POST"):
        raise ValueError(f"unexpected method in {route_key!r}")
    return f"{SOURCE_ARN_PREFIX}/*/*/coupons*"


def route_statement_id(route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    slug = path.strip("/").replace("/", "-").replace("{", "").replace("}", "")
    return f"apigw-{FUNCTION_NAME}-{method.lower()}-{slug}"


def _all_items(method: str) -> list:
    client = api()
    paginate, items, token = getattr(client, method), [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "1000"}
        if token:
            kwargs["NextToken"] = token
        page = paginate(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            return items


def find_integration(uri: str) -> str:
    for integration in _all_items("get_integrations"):
        if integration.get("IntegrationUri") == uri:
            return integration["IntegrationId"]
    return ""


def ensure_integration(apply: bool) -> tuple:
    """Reuse-or-create ONE `AWS_PROXY` integration pointing at the alias. Never modifies another."""
    uri = function_arn(qualified=True)
    existing = find_integration(uri)
    if existing:
        return existing, f"reusing {existing}"
    if not apply:
        return "", f"would create AWS_PROXY -> {uri}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
        PayloadFormatVersion="2.0",
        Description="Coupon issuance and eligibility")
    return created["IntegrationId"], f"created {created['IntegrationId']} -> {uri}"


def ensure_routes(apply: bool, integration_id: str) -> str:
    """Create only missing route keys. Never deletes or retargets an existing route."""
    existing = {r["RouteKey"]: r["RouteId"] for r in _all_items("get_routes")}
    results = []
    for key in ROUTE_KEYS:
        if key in existing:
            results.append(f"{key} exists ({existing[key]})")
            continue
        if not apply:
            results.append(f"would create {key}")
            continue
        made = api().create_route(
            ApiId=API_ID, RouteKey=key, Target=f"integrations/{integration_id}")
        results.append(f"created {key} ({made['RouteId']})")
    return "; ".join(results)


def live_policy_statements() -> list:
    """The alias's resource-policy statements, or an empty list when it has none yet."""
    import json
    try:
        policy = lam().get_policy(FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException",
                                                         "ResourceNotFound"):
            return []
        raise
    return json.loads(policy.get("Policy") or "{}").get("Statement") or []


def _statement_source_arn(statement: dict) -> str:
    return (((statement.get("Condition") or {}).get("ArnLike") or {})
            .get("AWS:SourceArn") or "")


def ensure_invoke_permission(apply: bool) -> str:
    """One alias-qualified `lambda:InvokeFunction` statement per route.

    Qualified to `live`, because a function-level statement does not authorise an alias invoke.
    Statements are OR'd, so adding one can never remove authorisation from an existing route.
    """
    existing = {s.get("Sid"): s for s in live_policy_statements()}
    notes = []
    for key in ROUTE_KEYS:
        sid = route_statement_id(key)
        if sid in existing:
            notes.append(f"{sid} exists ({_statement_source_arn(existing[sid])})")
            continue
        if not apply:
            notes.append(f"would add {sid} -> {source_arn(key)}")
            continue
        lam().add_permission(
            FunctionName=FUNCTION_NAME, Qualifier=LIVE_ALIAS, StatementId=sid,
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=source_arn(key))
        notes.append(f"added {sid}")
    return "; ".join(notes)


def verify() -> int:
    """Read routes, integration and every invoke statement back. Non-zero on any problem."""
    problems: list[str] = []
    uri = function_arn(qualified=True)
    integration_id = find_integration(uri)
    if not integration_id:
        problems.append(f"no AWS_PROXY integration targets {uri}")

    integrations = {i["IntegrationId"]: i for i in _all_items("get_integrations")}
    if integration_id:
        integration = integrations[integration_id]
        if integration.get("PayloadFormatVersion") != "2.0":
            problems.append(f"payload format is {integration.get('PayloadFormatVersion')}, "
                            f"expected 2.0")
        if integration.get("IntegrationType") != "AWS_PROXY":
            problems.append(f"integration type is {integration.get('IntegrationType')}")
        if not str(integration.get("IntegrationUri") or "").endswith(f":{LIVE_ALIAS}"):
            problems.append("the integration does not target the live alias")

    routes = {r["RouteKey"]: r for r in _all_items("get_routes")}
    for key in ROUTE_KEYS:
        route = routes.get(key)
        if not route:
            problems.append(f"missing route {key}")
            continue
        if integration_id and route.get("Target") != f"integrations/{integration_id}":
            problems.append(f"route {key} targets {route.get('Target')}, not this integration")
        if route.get("AuthorizerId"):
            problems.append(f"route {key} carries an authorizer this script did not create")

    statements = {s.get("Sid"): s for s in live_policy_statements()}
    for key in ROUTE_KEYS:
        sid = route_statement_id(key)
        if sid not in statements:
            problems.append(f"missing invoke statement {sid}")
            continue
        arn = _statement_source_arn(statements[sid])
        if arn != source_arn(key):
            problems.append(f"{sid} is scoped to {arn}, expected {source_arn(key)}")
    unexpected = sorted(set(statements) - {route_statement_id(k) for k in ROUTE_KEYS})
    if unexpected:
        problems.append(f"unexpected invoke statements on the alias: {unexpected}")

    print(f"api: {API_ID} stage {STAGE}")
    print(f"integration: {integration_id or 'MISSING'} -> {uri}")
    for key in ROUTE_KEYS:
        print(f"route {key}: {'ok' if key in routes else 'MISSING'}")
    print(f"invoke statements: {sorted(statements)}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncoupons routes verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="create what is missing; without it this is a dry run")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}\napply: {args.apply}\n")
    integration_id, note = ensure_integration(args.apply)
    print(f"integration: {note}")
    # The permission goes on BEFORE the routes, so a route is never reachable-but-unauthorised.
    print(f"permissions: {ensure_invoke_permission(args.apply)}")
    print(f"routes: {ensure_routes(args.apply, integration_id)}")
    if not args.apply:
        print("\ndry run: nothing changed")
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
