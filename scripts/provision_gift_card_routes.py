#!/usr/bin/env python3
"""Provision the AWS-native gift-card HTTP API routes.

The retired provider SPI routes are not created or verified here. Only the five
WECARE.DIGITAL gift-card routes remain, all targeting `wecare-gift-cards:live`.
"""

from __future__ import annotations

import argparse
import json

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = "775261844268"

#: The account's single HTTP API ("wecare-digital-api") and its only stage, which auto-deploys.
API_ID = "zllr9lrg7j"
STAGE = "prod"
LIVE_ALIAS = "live"

GIFT_CARDS_FUNCTION = "wecare-gift-cards"

#: FIVE routes, not seven. `POST /gift-cards/hold` and `POST /gift-cards/release` are deliberately
#: absent (MEDIUM-5): a customer session has no `paymentAttemptId`, and a hold taken outside the
#: request that mints one skips the `GC_HELD` stage - leaving `giftCardRequiredPaise` unwritten, so
#: `is_fully_settled` reads `required == 0` and would settle a gift-card order on the Razorpay leg
#: alone. The hold is taken only by the checkout producer.
#:
#: No route takes a CODE in a path or a query: a bearer value in a URL lands in access logs, in
#: `Referer` headers and in browser history. The staff reads take our own `giftCardId`; the customer
#: route takes `{code, pin?}` in the BODY. There is no `DELETE` - a disabled card retains its
#: liability record.
OWN_ROUTE_KEYS = (
    "POST /gift-cards",
    "GET /gift-cards/{giftCardId}",
    "GET /gift-cards",
    "POST /gift-cards/{giftCardId}/disable",
    "POST /gift-cards/balance",
)

#: function -> (its route keys, the source-ARN path family). Narrower than `{API_ID}/*/*`, which
#: would authorise any method on any of the 361 routes.
PLAN = (
    (GIFT_CARDS_FUNCTION, OWN_ROUTE_KEYS, "gift-cards*", "Gift-card issuance and balance"),
)

SOURCE_ARN_PREFIX = f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{API_ID}"


def api():
    return boto3.client("apigatewayv2", region_name=REGION)


def lam():
    return boto3.client("lambda", region_name=REGION)


def function_arn(function: str, *, qualified: bool = True) -> str:
    arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{function}"
    return f"{arn}:{LIVE_ALIAS}" if qualified else arn


def source_arn(family: str) -> str:
    """The source ARN for one path family.

    A family rather than a per-route literal, because a templated route key (`{giftCardId}`) is
    presented by API Gateway with the resolved value substituted - so a literal would not match the
    request it is meant to authorise.
    """
    return f"{SOURCE_ARN_PREFIX}/*/*/{family}"


def route_statement_id(function: str, route_key: str) -> str:
    method, path = route_key.split(" ", 1)
    slug = path.strip("/").replace("/", "-").replace("{", "").replace("}", "")
    return f"apigw-{function}-{method.lower()}-{slug}"


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


def ensure_integration(function: str, description: str, apply: bool) -> tuple:
    """Reuse-or-create ONE `AWS_PROXY` integration per function, pointing at the alias."""
    uri = function_arn(function)
    existing = find_integration(uri)
    if existing:
        return existing, f"reusing {existing}"
    if not apply:
        return "", f"would create AWS_PROXY -> {uri}"
    created = api().create_integration(
        ApiId=API_ID, IntegrationType="AWS_PROXY", IntegrationUri=uri,
        PayloadFormatVersion="2.0", Description=description)
    return created["IntegrationId"], f"created {created['IntegrationId']} -> {uri}"


def ensure_routes(route_keys, integration_id: str, apply: bool) -> str:
    """Create only missing route keys. Never deletes or retargets an existing route."""
    existing = {r["RouteKey"]: r["RouteId"] for r in _all_items("get_routes")}
    results = []
    for key in route_keys:
        if key in existing:
            results.append(f"{key} exists ({existing[key]})")
            continue
        if not apply:
            results.append(f"would create {key}")
            continue
        made = api().create_route(ApiId=API_ID, RouteKey=key,
                                  Target=f"integrations/{integration_id}")
        results.append(f"created {key} ({made['RouteId']})")
    return "; ".join(results)


def live_policy_statements(function: str) -> list:
    """The alias's resource-policy statements, or an empty list when it has none yet."""
    try:
        policy = lam().get_policy(FunctionName=function, Qualifier=LIVE_ALIAS)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException",
                                                         "ResourceNotFound"):
            return []
        raise
    return json.loads(policy.get("Policy") or "{}").get("Statement") or []


def _statement_source_arn(statement: dict) -> str:
    return (((statement.get("Condition") or {}).get("ArnLike") or {})
            .get("AWS:SourceArn") or "")


def ensure_invoke_permission(function: str, route_keys, family: str, apply: bool) -> str:
    """One alias-qualified `lambda:InvokeFunction` statement per route.

    Qualified to `live`, because a function-level statement does not authorise an alias invoke.
    Statements are OR'd, so adding one can never remove authorisation from an existing route.
    """
    existing = {s.get("Sid"): s for s in live_policy_statements(function)}
    notes = []
    for key in route_keys:
        sid = route_statement_id(function, key)
        if sid in existing:
            notes.append(f"{sid} exists ({_statement_source_arn(existing[sid])})")
            continue
        if not apply:
            notes.append(f"would add {sid} -> {source_arn(family)}")
            continue
        lam().add_permission(
            FunctionName=function, Qualifier=LIVE_ALIAS, StatementId=sid,
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=source_arn(family))
        notes.append(f"added {sid}")
    return "; ".join(notes)


def verify() -> int:
    """Read routes, integrations and every invoke statement back. Non-zero on any problem."""
    problems: list[str] = []
    integrations = {i["IntegrationId"]: i for i in _all_items("get_integrations")}
    routes = {r["RouteKey"]: r for r in _all_items("get_routes")}

    for function, route_keys, family, _description in PLAN:
        uri = function_arn(function)
        integration_id = find_integration(uri)
        if not integration_id:
            problems.append(f"no AWS_PROXY integration targets {uri}")
        else:
            integration = integrations[integration_id]
            if integration.get("PayloadFormatVersion") != "2.0":
                problems.append(f"{function}: payload format is "
                                f"{integration.get('PayloadFormatVersion')}, expected 2.0")
            if integration.get("IntegrationType") != "AWS_PROXY":
                problems.append(f"{function}: integration type is "
                                f"{integration.get('IntegrationType')}")
            if not str(integration.get("IntegrationUri") or "").endswith(f":{LIVE_ALIAS}"):
                problems.append(f"{function}: the integration does not target the live alias")

        for key in route_keys:
            route = routes.get(key)
            if not route:
                problems.append(f"missing route {key}")
                continue
            if integration_id and route.get("Target") != f"integrations/{integration_id}":
                problems.append(f"route {key} targets {route.get('Target')}, not {function}'s "
                                f"integration")
            if route.get("AuthorizerId"):
                problems.append(f"route {key} carries an authorizer this script did not create")
            # No code may appear in a route template.
            if "{code}" in key or "code=" in key:
                problems.append(f"route {key} carries a code in its path")

        statements = {s.get("Sid"): s for s in live_policy_statements(function)}
        for key in route_keys:
            sid = route_statement_id(function, key)
            if sid not in statements:
                problems.append(f"missing invoke statement {sid}")
                continue
            arn = _statement_source_arn(statements[sid])
            if arn != source_arn(family):
                problems.append(f"{sid} is scoped to {arn}, expected {source_arn(family)}")
        unexpected = sorted(set(statements)
                            - {route_statement_id(function, k) for k in route_keys})
        if unexpected:
            problems.append(f"unexpected invoke statements on {function}:{LIVE_ALIAS}: "
                            f"{unexpected}")

        print(f"function: {function}")
        print(f"  integration: {integration_id or 'MISSING'} -> {uri}")
        for key in route_keys:
            print(f"  route {key}: {'ok' if key in routes else 'MISSING'}")
        print(f"  invoke statements: {sorted(statements)}")

    # The two hold/release routes must NOT exist (MEDIUM-5). Asserted rather than assumed, because
    # a route created by hand would be reachable and unprovisioned.
    for forbidden in ("POST /gift-cards/hold", "POST /gift-cards/release"):
        if forbidden in routes:
            problems.append(f"{forbidden} exists; a customer-taken hold skips the GC_HELD stage "
                            f"and would settle a gift-card order on the Razorpay leg alone")

    print(f"api: {API_ID} stage {STAGE}")
    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ngift-card routes verified")
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
    for function, route_keys, family, description in PLAN:
        integration_id, note = ensure_integration(function, description, args.apply)
        print(f"{function} integration: {note}")
        # The permission goes on BEFORE the routes, so a route is never reachable-but-unauthorised.
        print(f"{function} permissions: "
              f"{ensure_invoke_permission(function, route_keys, family, args.apply)}")
        print(f"{function} routes: {ensure_routes(route_keys, integration_id, args.apply)}")
    if not args.apply:
        print("\ndry run: nothing changed")
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
