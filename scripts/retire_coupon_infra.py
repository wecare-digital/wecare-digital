#!/usr/bin/env python3
"""Retire the dead legacy coupon infrastructure: routes, integration, Lambda, and table.

Why this exists
---------------
The coupon/gift-card SYSTEM was removed from the codebase on 2026-10-18. The only discount is now
the standalone Delight policy (`lambda_utils/ecommerce/default_coupon.py`) - pure arithmetic, no
table, no Lambda, no routes. What remains is the dead LIVE infrastructure (issue #897):

    7 API routes `/coupons*` on HTTP API zllr9lrg7j  -> integration ain7v3l -> wecare-coupons
    Lambda  wecare-coupons  (:live)
    DynamoDB stack-wecare-digital-CouponsTable

Verified 2026-10-19 (us-east-1): there are ZERO code callers (a repo grep finds only the Delight
arithmetic module, which touches no coupon infra); the Lambda has NO event-source mappings; its
invocations are 15 on Oct 8 (the removal day), 1 on Oct 15, and zero since; the table holds 0
rows and its only reads match this retirement's own read-only audits. So the "callers drained"
precondition is met by evidence, not assumption - and this script RE-CHECKS it at apply time.

Safety
------
- DRY RUN BY DEFAULT. `--apply` is required to delete anything.
- DRAIN GATE: refuses to apply if the Lambda shows invocations, or the table shows writes, within
  `--drain-days` (default 7). A live caller aborts the teardown - this is the #897 precondition,
  enforced mechanically.
- ROLLBACK CAPTURE FIRST: before any delete it writes a snapshot to docs/execution/snapshots/
  containing the Lambda configuration (environment values redacted to key names), the
  integration, every `/coupons*` route, and a full scan
  of the table (0 rows today, but captured regardless). An operator can recreate all of it from
  the snapshot. The table additionally has PITR (35 days) as a second recovery path.
- ORDERED teardown so nothing is briefly reachable-but-broken: routes first (makes the API stop
  routing to the integration), then the integration, then the Lambda, then the table.
- RE-READS routes immediately before deleting (this repo runs parallel sessions), like
  retire_orphan_integrations.py.
- The table delete sets no force: if deletion protection is ON the delete fails loudly rather
  than being bypassed. Enable/disable protection is a separate, deliberate operator action.

    python scripts/retire_coupon_infra.py            # report + rollback snapshot, no deletes
    python scripts/retire_coupon_infra.py --verify   # report only; exit 1 while anything remains
    python scripts/retire_coupon_infra.py --apply     # gated teardown
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
LAMBDA_NAME = "wecare-coupons"
TABLE_NAME = "stack-wecare-digital-CouponsTable"
ROUTE_PREFIX = "/coupons"
DEFAULT_DRAIN_DAYS = 7

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "docs/execution/snapshots"


def _coupon_routes(api) -> list:
    """Every `/coupons*` route on the API, re-read live."""
    items, token = [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "500"}
        if token:
            kwargs["NextToken"] = token
        page = api.get_routes(**kwargs)
        items += [r for r in page.get("Items", [])
                  if str(r.get("RouteKey", "")).split(" ")[-1].startswith(ROUTE_PREFIX)]
        token = page.get("NextToken")
        if not token:
            return items


def _coupon_integration_ids(routes: list) -> set:
    return {str(r.get("Target") or "").split("/")[-1]
            for r in routes if (r.get("Target") or "").startswith("integrations/")}


def _recent_invocations(cw, days: int) -> float:
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/Lambda", MetricName="Invocations",
            Dimensions=[{"Name": "FunctionName", "Value": LAMBDA_NAME}],
            StartTime=start, EndTime=dt.datetime.now(dt.timezone.utc),
            Period=86400, Statistics=["Sum"])
        return sum(p.get("Sum", 0) for p in resp.get("Datapoints", []))
    except ClientError:
        # Unreadable metrics must NOT read as "drained"; fail closed to a non-zero sentinel.
        return float("nan")


def _recent_writes(cw, days: int) -> float:
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/DynamoDB", MetricName="ConsumedWriteCapacityUnits",
            Dimensions=[{"Name": "TableName", "Value": TABLE_NAME}],
            StartTime=start, EndTime=dt.datetime.now(dt.timezone.utc),
            Period=86400, Statistics=["Sum"])
        return sum(p.get("Sum", 0) for p in resp.get("Datapoints", []))
    except ClientError:
        return float("nan")


def _scan_table(ddb_resource) -> list:
    rows, kwargs = [], {}
    table = ddb_resource.Table(TABLE_NAME)
    while True:
        page = table.scan(**kwargs)
        rows += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def capture_rollback(api, lam, ddb_resource, routes) -> pathlib.Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = SNAPSHOT_DIR / f"coupon-infra-retirement-{stamp}.json"

    try:
        lambda_config = lam.get_function_configuration(FunctionName=LAMBDA_NAME)
        lambda_config.pop("ResponseMetadata", None)
        # This snapshot is written inside the repository, so environment VALUES never enter
        # it: key names are enough to rebuild from config/lambda-env-manifest.json and source.
        env = (lambda_config.get("Environment") or {}).get("Variables") or {}
        if env:
            lambda_config["Environment"]["Variables"] = {k: "<redacted>" for k in sorted(env)}
    except ClientError as exc:
        lambda_config = {"error": exc.response["Error"]["Code"]}

    integrations = {}
    for iid in _coupon_integration_ids(routes):
        try:
            integrations[iid] = api.get_integration(ApiId=API_ID, IntegrationId=iid)
            integrations[iid].pop("ResponseMetadata", None)
        except ClientError as exc:
            integrations[iid] = {"error": exc.response["Error"]["Code"]}

    try:
        rows = _scan_table(ddb_resource)
    except ClientError as exc:
        rows = [{"error": exc.response["Error"]["Code"]}]

    path.write_text(json.dumps({
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "api_id": API_ID, "lambda": LAMBDA_NAME, "table": TABLE_NAME,
        "note": ("Rollback snapshot for the legacy coupon teardown (#897). Recreate: "
                 "create_integration from `integrations`, create_route for each `routes` entry, "
                 "redeploy the Lambda from source control (config under `lambda_config`), and "
                 "restore the table via PITR or re-put `table_rows`."),
        "routes": [{k: r.get(k) for k in ("RouteKey", "RouteId", "Target",
                                          "AuthorizationType")} for r in routes],
        "integrations": integrations,
        "lambda_config": lambda_config,
        "table_row_count": len(rows),
        "table_rows": rows,
    }, indent=2, default=str), encoding="utf-8")
    return path


def _nonzero_or_unknown(value: float) -> bool:
    """True if the metric shows activity OR could not be read (fail closed)."""
    return value != 0  # NaN != 0 is True, so an unreadable metric blocks the teardown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the teardown")
    ap.add_argument("--verify", action="store_true",
                    help="report only; exit 1 while any coupon resource still exists")
    ap.add_argument("--drain-days", type=int, default=DEFAULT_DRAIN_DAYS,
                    help="window checked for invocations/writes before allowing --apply")
    args = ap.parse_args()

    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    ddb_client = boto3.client("dynamodb", region_name=REGION)
    ddb_resource = boto3.resource("dynamodb", region_name=REGION)

    routes = _coupon_routes(api)
    lambda_exists = True
    try:
        # Existence only. GetFunction would also return environment values and a signed
        # code URL, neither of which this check needs.
        lam.get_function_concurrency(FunctionName=LAMBDA_NAME)
    except ClientError:
        lambda_exists = False
    table_exists = True
    try:
        ddb_client.describe_table(TableName=TABLE_NAME)
    except ClientError:
        table_exists = False

    remaining = len(routes) + (1 if lambda_exists else 0) + (1 if table_exists else 0)

    print("=" * 78)
    print("LEGACY COUPON INFRASTRUCTURE RETIREMENT (#897)")
    print("=" * 78)
    print(f"  /coupons routes on {API_ID} : {len(routes)}")
    print(f"  Lambda {LAMBDA_NAME}         : {'present' if lambda_exists else 'absent'}")
    print(f"  table {TABLE_NAME}           : {'present' if table_exists else 'absent'}")

    if args.verify:
        done = remaining == 0
        print("\nRESULT:", "PASS - coupon infra fully retired" if done
              else f"FAIL - {remaining} coupon resource(s) remain")
        return 0 if done else 1

    invocations = _recent_invocations(cw, args.drain_days)
    writes = _recent_writes(cw, args.drain_days)
    print(f"\n  drain check (last {args.drain_days}d): "
          f"invocations={invocations}, table writes={writes}")

    snapshot = capture_rollback(api, lam, ddb_resource, routes)
    print(f"  rollback snapshot -> {snapshot.relative_to(ROOT)}")

    if not args.apply:
        print("\n  DRY RUN - nothing deleted. Re-run with --apply once the drain check is clean.")
        return 0

    # DRAIN GATE. A caller invoked the Lambda or wrote the table inside the window - or the
    # metric could not be read - so the teardown is refused. This is the #897 precondition.
    if _nonzero_or_unknown(invocations) or _nonzero_or_unknown(writes):
        print("\n  REFUSED: recent activity (or unreadable metrics). Callers are NOT drained; "
              "reconcile them before teardown. Nothing deleted.")
        return 2

    # Ordered teardown. Routes re-read right here so a route added since the survey is included.
    deleted_routes = 0
    for route in _coupon_routes(api):
        try:
            api.delete_route(ApiId=API_ID, RouteId=route["RouteId"])
            deleted_routes += 1
        except ClientError as exc:
            print(f"  FAILED route {route.get('RouteKey')}: {exc.response['Error']['Code']}")
    print(f"  deleted {deleted_routes} route(s)")

    # Integrations only after NO coupon route points at them (re-read).
    still_used = _coupon_integration_ids(_coupon_routes(api))
    for iid in _coupon_integration_ids(routes):
        if iid in still_used:
            print(f"  SKIP integration {iid}: a coupon route still targets it")
            continue
        try:
            api.delete_integration(ApiId=API_ID, IntegrationId=iid)
            print(f"  deleted integration {iid}")
        except ClientError as exc:
            print(f"  FAILED integration {iid}: {exc.response['Error']['Code']}")

    if lambda_exists:
        try:
            lam.delete_function(FunctionName=LAMBDA_NAME)
            print(f"  deleted Lambda {LAMBDA_NAME}")
        except ClientError as exc:
            print(f"  FAILED Lambda: {exc.response['Error']['Code']}")

    if table_exists:
        try:
            ddb_client.delete_table(TableName=TABLE_NAME)
            print(f"  delete requested for table {TABLE_NAME} (PITR retains 35-day recovery)")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            # Deletion protection ON surfaces here rather than being bypassed - deliberate.
            print(f"  FAILED table: {code}"
                  + ("  (deletion protection is ON - disable it deliberately first)"
                     if code == "ValidationException" else ""))

    print("\n  Verify: python scripts/retire_coupon_infra.py --verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
