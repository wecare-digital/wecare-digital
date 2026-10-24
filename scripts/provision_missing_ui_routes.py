#!/usr/bin/env python3
"""Create the API routes three live dashboard pages already call and never reach.

What was wrong
--------------
Measured against `GetRoutes` on the only HTTP API (`zllr9lrg7j`), not inferred:

| Page | Calls | Route |
|---|---|---|
| `/workspace/engage/docs` | `GET /docs/sources`, `POST /docs/sources`, `POST /docs/scrape`, `GET /docs/changelog` | **absent** |
| `/workspace/engage/push` | `GET /push/devices`, `POST /push/send` | **absent** |
| `src/api/client.ts` | `GET` + `PUT /whatsapp-voice/language-config` | **absent** |

Every one of those calls 404s today, and **both pages hide it**. `/workspace/engage/docs` wraps its
reads in `.catch(() => [])`, so it renders an empty source list and an empty changelog
as though that were the truth. `/workspace/engage/push` checks `res.ok` and silently shows nothing.
So three screens look functional and cannot work - the same shape as the agent panel
advertising 18 refused tools and the `createInvoice` that returned success and wrote
no row.

The handlers were written expecting these routes
------------------------------------------------
This is not a feature being added. `docs-scraper` carries an explicit `ROUTE_ACTIONS`
map keyed on the exact strings `GET /docs/sources`, `POST /docs/sources`,
`POST /docs/scrape` and `GET /docs/changelog`. `push-notifications` dispatches on the
`devices` and `send` path segments and requires `Admin` for both.
`whatsapp-voice` handles `language-config` for GET and PUT and documents it in its own
docstring. All three are ready; only the wiring was missing.

`scripts/register_task12_routes.py` claims to register most of these. They are not in
the account, so either it never ran against this API or the routes were lost with the
second HTTP API that no longer exists. Either way the fix is to converge the account,
idempotently, and that is what this does.

Qualified where safe, unqualified where an alias would break the deploy
----------------------------------------------------------------------
- `wecare-whatsapp-voice` already has a `live` alias, so its two routes reuse the
  existing `:live` integration.
- `wecare-push-notifications` is in `deploy_all_lambdas.py`, which calls
  `snapstart_publish.py`, which finds its targets by looking for a `live` alias. So
  creating one here immediately makes its deploys publish-and-move, and its routes get
  `:live`.
- `wecare-docs-scraper` gets an **unqualified** integration, deliberately. It is
  `PackageType=Image` and uses its separate container deployment path, which
  runs `update-function-code` and nothing else. Give it an alias and every future
  deploy would report success and never reach production - the "it looked shipped"
  failure. The alias must be moved by that explicit container deployment path.

No OPTIONS routes are created: the API carries an API-level `CorsConfiguration`, so
preflight is answered by API Gateway before any route lookup.

Usage:
    python scripts/provision_missing_ui_routes.py            # report
    python scripts/provision_missing_ui_routes.py --apply
    python scripts/provision_missing_ui_routes.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
ACCOUNT = "775261844268"
ALIAS = "live"
STATEMENT_ID = "apigw-live-alias-invoke"
SOURCE_ARN = f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{API_ID}/*/*"

# function -> (use_alias, route keys)
PLAN = {
    "wecare-whatsapp-voice": (True, [
        "GET /whatsapp-voice/language-config",
        "PUT /whatsapp-voice/language-config",
    ]),
    "wecare-push-notifications": (True, [
        "GET /push/devices",
        "POST /push/send",
    ]),
    "wecare-docs-scraper": (False, [
        "GET /docs/sources",
        "POST /docs/sources",
        "POST /docs/scrape",
        "GET /docs/changelog",
    ]),
}

# Every route here reaches a handler that requires Admin, so an unauthenticated probe
# must be refused. 401 is the pass; 404 means the route is still missing and 500 means
# the invoke permission is wrong and the Lambda was never called.
PROBES = [
    ("GET", "/push/devices"),
    ("GET", "/workspace/docs/sources"),
    ("GET", "/whatsapp-voice/language-config"),
]


def function_arn(name: str, qualified: bool) -> str:
    base = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
    return f"{base}:{ALIAS}" if qualified else base


def all_items(client, operation: str):
    items = []
    for page in client.get_paginator(operation).paginate(ApiId=API_ID):
        items.extend(page.get("Items", []))
    return items


def ensure_alias(lam, name: str) -> str:
    try:
        return lam.get_alias(FunctionName=name, Name=ALIAS)["FunctionVersion"]
    except ClientError:
        pass
    published = lam.publish_version(FunctionName=name)
    version = published["Version"]
    for _ in range(30):
        if lam.get_function_configuration(
                FunctionName=name, Qualifier=version).get("State") == "Active":
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"{name} v{version} never reached Active")
    lam.create_alias(FunctionName=name, Name=ALIAS, FunctionVersion=version,
                     Description="Production traffic; moved by snapstart_publish.py")
    return version


def ensure_permission(lam, name: str, qualified: bool) -> None:
    """Grant API Gateway the invoke, on the alias when one is in play.

    A function-level statement does NOT authorise an alias invoke. Getting this wrong
    produces a 500 with no Lambda log line at all, because the function is never
    called - which is how `POST /plivo/dial-events` looked deployed and was not.
    """
    kwargs = dict(FunctionName=name, StatementId=STATEMENT_ID,
                  Action="lambda:InvokeFunction",
                  Principal="apigateway.amazonaws.com", SourceArn=SOURCE_ARN)
    if qualified:
        kwargs["Qualifier"] = ALIAS
    try:
        lam.add_permission(**kwargs)
    except lam.exceptions.ResourceConflictException:
        pass


def find_integration(api, uri: str) -> str:
    for integration in all_items(api, "get_integrations"):
        if integration.get("IntegrationUri") == uri:
            return integration["IntegrationId"]
    return ""


def report(api) -> dict:
    existing = {r["RouteKey"] for r in all_items(api, "get_routes")}
    missing = {}
    for name, (qualified, keys) in PLAN.items():
        absent = [k for k in keys if k not in existing]
        missing[name] = absent
        state = "all present" if not absent else f"{len(absent)} missing"
        print(f"{name} ({'alias' if qualified else '$LATEST, deliberate'}): {state}")
        for key in absent:
            print(f"    MISSING {key}")
    return missing


def apply(api, lam, missing) -> int:
    for name, absent in missing.items():
        if not absent:
            continue
        qualified, _ = PLAN[name]
        print(f"\n{name}")

        if qualified:
            version = ensure_alias(lam, name)
            print(f"  {ALIAS} -> v{version}")
        ensure_permission(lam, name, qualified)
        print(f"  invoke permission ensured"
              f"{' on alias ' + ALIAS if qualified else ' on the function'}")

        uri = function_arn(name, qualified)
        integration_id = find_integration(api, uri)
        if not integration_id:
            created = api.create_integration(
                ApiId=API_ID, IntegrationType="AWS_PROXY",
                IntegrationUri=uri, PayloadFormatVersion="2.0")
            integration_id = created["IntegrationId"]
            print(f"  created integration {integration_id} -> {uri}")
        else:
            print(f"  reusing integration {integration_id}")

        for key in absent:
            made = api.create_route(ApiId=API_ID, RouteKey=key,
                                    Target=f"integrations/{integration_id}")
            print(f"  created {key} (routeId {made['RouteId']})")
    return 0


def probe(method: str, path: str) -> str:
    request = urllib.request.Request(
        f"https://wecare.digital/api{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return str(response.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


def verify() -> int:
    problems = []
    api = boto3.client("apigatewayv2", region_name=REGION)
    missing = report(api)
    for name, absent in missing.items():
        for key in absent:
            problems.append(f"{key} does not exist")

    print("\nunauthenticated probes (401 or 403 is the pass):")
    for method, path in PROBES:
        code = probe(method, path)
        print(f"  {method} {path} -> {code}")
        if code == "404":
            problems.append(f"{method} {path} is still 404")
        elif code == "500":
            problems.append(f"{method} {path} returned 500; the invoke permission is "
                            f"wrong and the Lambda was never called")
        elif code == "200":
            problems.append(f"{method} {path} returned 200 WITHOUT a token; these "
                            f"handlers all require Admin")
        elif code not in ("401", "403"):
            problems.append(f"{method} {path} returned {code}, expected 401 or 403")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nall three pages can now reach their handlers, and each refuses anonymous "
          "callers")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    try:
        missing = report(api)
    except (ClientError, BotoCoreError) as exc:
        print(f"could not read the API: {type(exc).__name__}", file=sys.stderr)
        return 2

    if not any(missing.values()):
        print("\nnothing to do; run --verify to probe")
        return 0
    if not args.apply:
        print("\nre-run with --apply to converge")
        return 1

    rc = apply(api, lam, missing)
    if rc:
        return rc
    print("\nread-back verification:")
    time.sleep(6)
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
