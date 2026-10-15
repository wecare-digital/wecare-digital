#!/usr/bin/env python3
"""Delete API Gateway integrations that no route points at, after exporting them.

What this cleans up
-------------------
Measured 2026-09-28 on HTTP API `zllr9lrg7j`: **112 integrations for 65 routed targets**.
47 had no route attached at all, and several of those pointed at Lambda functions that no
longer exist, among them:

    wecare-outbound-voice        deleted with the voice provider retirement
    wecare-sinch-dlr             Sinch messaging is a PROHIBITED provider here
    wecare-elevenlabs-webhook    deleted with the TTS retirement

Why bother, given none of them is reachable
-------------------------------------------
An integration with no route cannot be invoked, so this is not an exposure. Three reasons
it is still worth removing:

1. **It misleads the next audit.** A grep for "sinch" across live AWS state returns these,
   and a reviewer then has to re-derive that they are unreachable. Retired-provider
   residue that keeps re-appearing in inventories is how a retirement gets re-litigated.
2. **`deploy_seo_tools.py` reuses an integration by matching the function name inside
   `IntegrationUri` and takes the FIRST match.** Several of these orphans target live
   functions, so duplicates are exactly the input that makes "find the existing
   integration" ambiguous.
3. The stale `RouteSettings` for two deleted routes blocked every per-route throttle write
   on this API until they were removed. Dead configuration is not always inert.

Safety
------
`--apply` deletes only integrations that, RE-CHECKED at delete time, have zero routes
pointing at them. The route list is re-read immediately before each delete rather than
trusted from the report, because this repo runs parallel sessions and a route created
between the two would otherwise be orphaned by this script.

Every integration is exported to `docs/execution/snapshots/` first, in full, so any
deletion can be reconstructed with `create_integration`. The
retired-provider ones are additionally appended to
`docs/prohibited-provider-retirement.md`, which is where the standing authorization
requires retired-provider surfaces to be recorded before removal.

    python scripts/retire_orphan_integrations.py            # report + export, no deletes
    python scripts/retire_orphan_integrations.py --apply
    python scripts/retire_orphan_integrations.py --verify
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "docs/execution/snapshots"
RETIREMENT_DOC = ROOT / "docs/prohibited-provider-retirement.md"

# Functions whose absence is a completed retirement rather than a mistake. Listed so the
# report can say WHY a target is missing instead of just that it is.
RETIRED_PROVIDERS = {
    "wecare-outbound-voice": "voice provider retirement",
    "wecare-sinch-dlr": "Sinch messaging - prohibited provider",
    "wecare-elevenlabs-webhook": "ElevenLabs TTS retirement",
}


def _paginate(fn, key="Items"):
    items, token = [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "500"}
        if token:
            kwargs["NextToken"] = token
        page = fn(**kwargs)
        items += page.get(key, [])
        token = page.get("NextToken")
        if not token:
            return items


def _target_function(integration: dict) -> str:
    match = re.search(r":function:([A-Za-z0-9\-_]+)", integration.get("IntegrationUri") or "")
    return match.group(1) if match else ""


def survey(api, lam):
    integrations = _paginate(api.get_integrations)
    routes = _paginate(api.get_routes)
    live_functions = set()
    for page in lam.get_paginator("list_functions").paginate():
        live_functions |= {f["FunctionName"] for f in page["Functions"]}

    used = {(r.get("Target") or "").split("/")[-1] for r in routes}
    orphans = []
    for integration in integrations:
        iid = integration["IntegrationId"]
        if iid in used:
            continue
        target = _target_function(integration)
        orphans.append({
            "IntegrationId": iid,
            "target_function": target,
            "target_exists": bool(target) and target in live_functions,
            "retired_reason": RETIRED_PROVIDERS.get(target, ""),
            "integration": integration,
        })
    return integrations, routes, orphans


def export(integrations, routes, orphans) -> pathlib.Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = SNAPSHOT_DIR / f"apigw-orphan-integrations-{stamp}.json"
    path.write_text(json.dumps({
        "api_id": API_ID,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "integration_count": len(integrations),
        "route_count": len(routes),
        "orphan_count": len(orphans),
        "note": ("Full IntegrationResponse for every integration with no route. Restore "
                 "with apigatewayv2 create_integration using these fields, then "
                 "create_route with Target=integrations/<new id>."),
        "orphans": orphans,
    }, indent=2, default=str), encoding="utf-8")
    return path


def append_retirement_record(orphans, snapshot: pathlib.Path) -> None:
    """Record the prohibited-provider ones where the standing authorization expects them."""
    retired = [o for o in orphans if o["retired_reason"]]
    if not retired or not RETIREMENT_DOC.exists():
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "",
        f"## Orphaned API Gateway integrations removed {stamp}",
        "",
        "Integrations on `zllr9lrg7j` with **no route attached** whose target Lambda no",
        "longer exists. Unreachable before removal - an integration with no route cannot be",
        "invoked - so this is inventory hygiene rather than closing an exposure. Removed so",
        "a future audit grepping live AWS state for a retired provider stops finding them.",
        "",
        f"Full export, sufficient to recreate any of them: `{snapshot.relative_to(ROOT)}`",
        "",
        "| Integration | Target function | Why the target is gone |",
        "|---|---|---|",
    ]
    for item in sorted(retired, key=lambda o: o["target_function"]):
        lines.append(f"| `{item['IntegrationId']}` | `{item['target_function']}` "
                     f"| {item['retired_reason']} |")
    lines.append("")
    with RETIREMENT_DOC.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="delete the orphans")
    ap.add_argument("--verify", action="store_true", help="report only, exit 1 if any remain")
    args = ap.parse_args()

    api = boto3.client("apigatewayv2", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    integrations, routes, orphans = survey(api, lam)
    dead_target = [o for o in orphans if not o["target_exists"]]

    print("=" * 78)
    print("ORPHANED API GATEWAY INTEGRATIONS")
    print("=" * 78)
    print(f"  integrations                : {len(integrations)}")
    print(f"  routes                      : {len(routes)}")
    print(f"  integrations with NO route  : {len(orphans)}")
    print(f"  ... whose target is deleted : {len(dead_target)}")

    if dead_target:
        print("\n  target function no longer exists:")
        for item in sorted(dead_target, key=lambda o: o["target_function"]):
            why = item["retired_reason"] or "target absent"
            print(f"    {item['IntegrationId']:10s} {item['target_function']:34s} {why}")

    live_target = [o for o in orphans if o["target_exists"]]
    if live_target:
        from collections import Counter
        counts = Counter(o["target_function"] for o in live_target)
        print(f"\n  no route, target still live ({len(live_target)}):")
        for name, n in sorted(counts.items()):
            print(f"    {name:38s} {n} orphan integration(s)")

    if args.verify:
        print("\n" + "=" * 78)
        print("RESULT: " + ("PASS - no orphaned integrations" if not orphans
                            else f"FAIL - {len(orphans)} orphaned integration(s) remain"))
        print("=" * 78)
        return 1 if orphans else 0

    snapshot = export(integrations, routes, orphans)
    print(f"\n  exported {len(orphans)} orphan(s) -> {snapshot.relative_to(ROOT)}")

    if not args.apply:
        print(f"\n  DRY RUN - nothing deleted. Re-run with --apply.")
        return 0

    append_retirement_record(orphans, snapshot)

    # RE-READ the routes immediately before deleting. This repo runs parallel sessions and
    # a route created between the survey above and the delete below would be silently
    # orphaned by this script - the exact failure it exists to clean up.
    still_used = {(r.get("Target") or "").split("/")[-1] for r in _paginate(api.get_routes)}
    deleted, skipped = 0, 0
    for item in orphans:
        iid = item["IntegrationId"]
        if iid in still_used:
            print(f"  SKIP {iid}: a route now points at it (created since the survey)")
            skipped += 1
            continue
        try:
            api.delete_integration(ApiId=API_ID, IntegrationId=iid)
            deleted += 1
        except ClientError as exc:
            print(f"  FAILED {iid}: {exc.response['Error']['Code']}")

    print(f"\n  deleted {deleted}, skipped {skipped}")
    after_i, after_r, after_o = survey(api, lam)
    print(f"  integrations now {len(after_i)} for {len(after_r)} routes, "
          f"{len(after_o)} orphan(s) remaining")
    if len(after_r) != len(routes):
        print(f"  WARNING: route count moved {len(routes)} -> {len(after_r)} during this run")
    print("\n" + "=" * 78)
    print("Verify: python scripts/retire_orphan_integrations.py --verify")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
