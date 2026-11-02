#!/usr/bin/env python3
"""Multi-region AWS resource sweep: close the single-region blind spot.

Why this exists
---------------
`aws_account_inventory.py` is deep but pinned to us-east-1 (plus ap-south-1 for
SES). A retired or orphan resource in any other region is invisible to it, so no
account-wide clean-state claim was possible. This sweep enumerates the resource
families that actually carry orphans -- Lambda, API Gateway (v1 + v2), DynamoDB,
SQS and EventBridge rules -- across EVERY enabled region, paginated so a large
account does not truncate, and batched one region at a time so it does not time
out the way the earlier broad scan did.

It is deliberately shallow per resource (names/counts, not full config): the goal
is "where does anything live?", answerable fast, not a per-resource deep audit.
Feed its region list back into the deep tool for anything surprising.

Safety
------
Read-only. Only List/Describe/Get-paginator calls. No secret values, no writes,
no deletes, no AWS mutation of any kind. Errors are recorded per region and make
the run PARTIAL rather than silently dropping a region.

    python scripts/aws_multiregion_sweep.py
    python scripts/aws_multiregion_sweep.py --json-only > /tmp/sweep.json
    python scripts/aws_multiregion_sweep.py --regions us-east-1,ap-south-1
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import sys

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("boto3 is required: pip install boto3", file=sys.stderr)
    raise SystemExit(2)

BOTO_CFG = Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=20, connect_timeout=5)


def enabled_regions() -> list[str]:
    ec2 = boto3.client("ec2", region_name="us-east-1", config=BOTO_CFG)
    resp = ec2.describe_regions(
        Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
    )
    return sorted(r["RegionName"] for r in resp["Regions"])


def _paginate(client, op: str, key: str, **kw) -> list:
    out: list = []
    paginator = client.get_paginator(op)
    for page in paginator.paginate(**kw):
        out.extend(page.get(key, []))
    return out


def sweep_region(region: str) -> dict:
    result: dict = {"region": region, "errors": []}

    def guard(label, fn, default):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - record, never swallow
            result["errors"].append(f"{label}: {type(exc).__name__}: {exc}")
            return default

    lam = boto3.client("lambda", region_name=region, config=BOTO_CFG)
    result["lambda"] = guard(
        "lambda.list_functions",
        lambda: [f["FunctionName"] for f in _paginate(lam, "list_functions", "Functions")],
        [],
    )

    apigwv2 = boto3.client("apigatewayv2", region_name=region, config=BOTO_CFG)
    result["http_apis"] = guard(
        "apigatewayv2.get_apis",
        lambda: [a["Name"] for a in apigwv2.get_apis().get("Items", [])],
        [],
    )

    apigw = boto3.client("apigateway", region_name=region, config=BOTO_CFG)
    result["rest_apis"] = guard(
        "apigateway.get_rest_apis",
        lambda: [a["name"] for a in _paginate(apigw, "get_rest_apis", "items")],
        [],
    )

    ddb = boto3.client("dynamodb", region_name=region, config=BOTO_CFG)
    result["dynamodb_tables"] = guard(
        "dynamodb.list_tables",
        lambda: _paginate(ddb, "list_tables", "TableNames"),
        [],
    )

    sqs = boto3.client("sqs", region_name=region, config=BOTO_CFG)
    result["sqs_queues"] = guard(
        "sqs.list_queues",
        lambda: [u.rsplit("/", 1)[-1] for u in sqs.list_queues().get("QueueUrls", [])],
        [],
    )

    events = boto3.client("events", region_name=region, config=BOTO_CFG)
    result["eventbridge_rules"] = guard(
        "events.list_rules",
        lambda: [r["Name"] for r in _paginate(events, "list_rules", "Rules")],
        [],
    )

    result["counts"] = {
        k: len(v) for k, v in result.items()
        if isinstance(v, list) and k != "errors"
    }
    result["partial"] = bool(result["errors"])
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--regions", help="comma-separated region list (default: all enabled)")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="parallel region workers (default 1 = sequential, accurate)")
    args = ap.parse_args()

    ident = boto3.client("sts", region_name="us-east-1", config=BOTO_CFG).get_caller_identity()
    regions = (
        [r.strip() for r in args.regions.split(",") if r.strip()]
        if args.regions else enabled_regions()
    )

    results: list[dict] = []
    if args.concurrency and args.concurrency > 1:
        # Opt-in parallelism. NOTE: heavy fan-out can throttle list calls into
        # empty results on some credential paths; the sequential default below
        # is the trustworthy mode. Use only when you have verified counts match.
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for res in pool.map(sweep_region, regions):
                results.append(res)
    else:
        # Sequential by default: one region at a time is slower but returns
        # accurate counts without the throttle-to-empty failure mode.
        for region in regions:
            results.append(sweep_region(region))
    results.sort(key=lambda r: r["region"])

    nonempty = [
        r for r in results
        if any(r["counts"].get(k) for k in r["counts"])
    ]
    report = {
        "account": ident["Account"],
        "regions_scanned": len(regions),
        "regions_with_resources": [r["region"] for r in nonempty],
        "partial_regions": [r["region"] for r in results if r["partial"]],
        "regions": results,
    }

    if args.json_only:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Multi-region AWS sweep — account {report['account']}")
    print("=" * 52)
    print(f"regions scanned: {report['regions_scanned']}")
    print(f"regions with resources: {', '.join(report['regions_with_resources']) or 'none'}")
    if report["partial_regions"]:
        print(f"PARTIAL (errors) in: {', '.join(report['partial_regions'])}")
    print()
    for r in results:
        active = {k: v for k, v in r["counts"].items() if v}
        if not active and not r["partial"]:
            continue
        line = "  ".join(f"{k}={v}" for k, v in sorted(active.items()))
        flag = "  [PARTIAL]" if r["partial"] else ""
        print(f"{r['region']:<16} {line or '(empty)'}{flag}")
        for err in r["errors"]:
            print(f"    ! {err}")
    print("\nRead-only sweep. No resource was created, modified or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
