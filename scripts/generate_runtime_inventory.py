#!/usr/bin/env python3
"""Join every live Lambda to its source, routes, tables, traffic and callers.

Why this exists
---------------
Phase 1 of the production brief requires a machine-readable row per deployed
function and per route, joined to IaC, permissions, tables, traffic and frontend
callers. Until now each of those lived in a different place, and the gaps between
them are where the real defects were:

  * a whole HTTP API nobody audited, because the audit hardcoded one api id
  * five routes pointing at Lambdas that had been deleted
  * six table names in code for tables that do not exist
  * a function whose deployed env still named a retired provider's secret

None of those are visible from any single source. They are visible in the join.

What it produces
----------------
  docs/execution/runtime-inventory.json   the full join, machine-readable
  docs/execution/runtime-inventory.md     a reviewable summary with the anomalies

Safety
------
Environment variable NAMES are recorded; VALUES never are. A function's env can
hold a table name, a flag, or a secret id, and this file is committed, so the
values stay out of it. Secret ids appear only where they are already recorded in
the protected-resource register.

    python scripts/generate_runtime_inventory.py
    python scripts/generate_runtime_inventory.py --quiet
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
REPO = pathlib.Path(__file__).resolve().parents[1]
OUT_JSON = REPO / "docs/execution/runtime-inventory.json"
OUT_MD = REPO / "docs/execution/runtime-inventory.md"
FRONTEND = REPO / "src"

# Env names whose value would be sensitive even though we only store names.
# Recorded as present, never read.
SENSITIVE_HINT = re.compile(r"SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL", re.I)

# Documented exceptions, so the report separates "known and justified" from
# "nobody has answered this". An anomaly list that mixes the two gets ignored.
EXPECTED = {
    "liveButNotInDeployMap": {
        "wecare-docs-scraper":
            "PackageType=Image; separate container deployment",
        "wecare-seo-tools":
            "different in-zip layout; scripts/deploy_seo_tools.py owns it with its "
            "table and IAM policy",
        "wecare-get-miss-redirect":
            "Lambda@Edge. CloudFront associates it by published VERSION, and an alias "
            "is not a valid association target, so the deploy map's "
            "publish-then-move-the-alias contract would publish a version CloudFront "
            "never picks up and then report success. Source at "
            "amplify/functions/edge/get-miss-redirect; see docs/SECURE-FILE-SHARING.md",
        # wecare-pstn-softphone was here until 2026-09-25. It was not an expected
        # exclusion at all: it served 5 live routes through its `live` alias while
        # its provisioner only created, so the first deploy was also the last. Now
        # in the deploy map.
    },
    "noLiveAliasButHasRoutes": {
        # Was "no justification recorded for these three", left empty so they kept
        # showing up until someone decided. Two remain and the decision is now
        # recorded in scripts/provision_live_alias.py EXCLUDED; partner-onboarding
        # and marketing-ads have since been given aliases, which is why the count
        # fell from three.
        "wecare-seo-tools":
            "deploy_seo_tools.py has no alias handling, so an alias would leave the "
            "alias pinned to an old version while every deploy reported success",
        "wecare-docs-scraper":
            "same shape: its deployment path only calls update-function-code, "
            "so an alias would silently stop reaching production",
    },
}


def deploy_map() -> dict[str, str]:
    """function name -> source directory, read from the deploy script's SPECS."""
    spec_path = REPO / "scripts/deploy_all_lambdas.py"
    spec = importlib.util.spec_from_file_location("deploy_all", spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_all"] = mod
    spec.loader.exec_module(mod)
    out = {}
    for s in getattr(mod, "SPECS", []):
        try:
            out[s.name] = str(s.source.relative_to(REPO))
        except Exception:
            out[s.name] = str(s.source)
    return out


def frontend_route_callers(route_paths: set[str]) -> dict[str, list[str]]:
    """route path -> frontend files that mention it."""
    hits: dict[str, set[str]] = {p: set() for p in route_paths}
    if not FRONTEND.is_dir():
        return {k: [] for k in hits}
    files = [p for ext in ("*.ts", "*.tsx") for p in FRONTEND.rglob(ext)]
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(REPO))
        for p in route_paths:
            # Match the literal path, ignoring a leading slash difference and
            # API Gateway's {param} placeholders.
            needle = re.sub(r"\{[^}]+\}", "", p).rstrip("/")
            if needle and needle in text:
                hits[p].add(rel)
    return {k: sorted(v) for k, v in hits.items()}


def metric_batch(cw, functions: list[str], metric: str, days: int) -> dict[str, float]:
    """One GetMetricData call for a metric across every function."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    queries, idmap = [], {}
    for i, fn in enumerate(functions):
        qid = f"m{i}"
        idmap[qid] = fn
        queries.append({
            "Id": qid,
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Lambda", "MetricName": metric,
                           "Dimensions": [{"Name": "FunctionName", "Value": fn}]},
                "Period": days * 86400,
                "Stat": "Sum",
            },
            "ReturnData": True,
        })
    out: dict[str, float] = {}
    for chunk in (queries[i:i + 500] for i in range(0, len(queries), 500)):
        r = cw.get_metric_data(MetricDataQueries=chunk,
                               StartTime=start, EndTime=end)
        for res in r.get("MetricDataResults", []):
            vals = res.get("Values") or []
            out[idmap[res["Id"]]] = float(sum(vals)) if vals else 0.0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    lam = boto3.client("lambda", region_name=REGION)
    api = boto3.client("apigatewayv2", region_name=REGION)
    ddb = boto3.client("dynamodb", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    logs = boto3.client("logs", region_name=REGION)

    try:
        # --- functions ---
        funcs, token = [], None
        while True:
            kw = {"MaxItems": 100}
            if token:
                kw["Marker"] = token
            r = lam.list_functions(**kw)
            funcs += r["Functions"]
            token = r.get("NextMarker")
            if not token:
                break
        names = sorted(f["FunctionName"] for f in funcs)

        aliases, sources, event_sources = {}, {}, {}
        for fn in names:
            aliases[fn] = {a["Name"]: a["FunctionVersion"]
                           for a in lam.list_aliases(FunctionName=fn).get("Aliases", [])}
            esm = lam.list_event_source_mappings(FunctionName=fn).get("EventSourceMappings", [])
            event_sources[fn] = [
                {"arn": e.get("EventSourceArn"), "state": e.get("State"),
                 "enabled": e.get("State") == "Enabled",
                 "batchSize": e.get("BatchSize")}
                for e in esm
            ]

        # --- routes ---
        apis, token = [], None
        while True:
            kw = {"MaxResults": "100"}
            if token:
                kw["NextToken"] = token
            r = api.get_apis(**kw)
            apis += r["Items"]
            token = r.get("NextToken")
            if not token:
                break

        routes_by_fn: dict[str, list[str]] = {}
        all_routes = []
        for a in apis:
            if a.get("ProtocolType") != "HTTP":
                continue
            aid = a["ApiId"]
            items, token = [], None
            while True:
                kw = {"ApiId": aid, "MaxResults": "100"}
                if token:
                    kw["NextToken"] = token
                r = api.get_routes(**kw)
                items += r["Items"]
                token = r.get("NextToken")
                if not token:
                    break
            integ, token = {}, None
            while True:
                kw = {"ApiId": aid, "MaxResults": "100"}
                if token:
                    kw["NextToken"] = token
                r = api.get_integrations(**kw)
                for i in r["Items"]:
                    integ[i["IntegrationId"]] = i.get("IntegrationUri", "")
                token = r.get("NextToken")
                if not token:
                    break
            for rt in items:
                iid = (rt.get("Target") or "").split("/")[-1]
                uri = integ.get(iid, "")
                m = re.search(r"function:([A-Za-z0-9\-_]+)(:([A-Za-z0-9$_-]+))?", uri)
                fn = m.group(1) if m else ""
                qualifier = m.group(3) if m and m.group(3) else "$LATEST"
                all_routes.append({
                    "apiId": aid, "apiName": a.get("Name"),
                    "routeKey": rt.get("RouteKey"), "routeId": rt.get("RouteId"),
                    "authorizationType": rt.get("AuthorizationType", "NONE"),
                    "targetFunction": fn, "qualifier": qualifier,
                })
                if fn:
                    routes_by_fn.setdefault(fn, []).append(rt.get("RouteKey"))

        tables = set()
        token = None
        while True:
            kw = {"Limit": 100}
            if token:
                kw["ExclusiveStartTableName"] = token
            r = ddb.list_tables(**kw)
            tables |= set(r.get("TableNames", []))
            token = r.get("LastEvaluatedTableName")
            if not token:
                break

        inv_24h = metric_batch(cw, names, "Invocations", 1)
        err_24h = metric_batch(cw, names, "Errors", 1)
        inv_7d = metric_batch(cw, names, "Invocations", 7)
        err_7d = metric_batch(cw, names, "Errors", 7)
    except (ClientError, BotoCoreError) as exc:
        print(f"could not read AWS: {type(exc).__name__}", file=sys.stderr)
        return 2

    dmap = deploy_map()
    paths = {r["routeKey"].split(" ", 1)[1] for r in all_routes
             if " " in (r["routeKey"] or "")}
    callers = frontend_route_callers(paths)

    # Log retention per function.
    #
    # Two names are tried, because a Lambda@Edge replica's log group is
    # `/aws/lambda/us-east-1.<fn>` - the region is inside the name, so the plain
    # `/aws/lambda/<fn>` prefix can never match it. Without the fallback,
    # `wecare-get-miss-redirect` reported retention `None`, which is not the same as
    # "no retention" and was therefore excluded from the anomaly count: an unknown
    # read as fine. Note CloudFront also writes Edge logs in the region nearest the
    # viewer, so a us-east-1 lookup can still miss a replica elsewhere -
    # `scripts/provision_log_retention.py` is the multi-region check.
    retention: dict[str, object] = {}
    for fn in names:
        retention[fn] = "no log group"
        for candidate in (f"/aws/lambda/{fn}", f"/aws/lambda/{REGION}.{fn}"):
            try:
                lg = logs.describe_log_groups(
                    logGroupNamePrefix=candidate, limit=1).get("logGroups", [])
            except (ClientError, BotoCoreError):
                retention[fn] = None
                break
            if lg:
                retention[fn] = lg[0].get("retentionInDays", "never expires")
                break

    rows = []
    for f in sorted(funcs, key=lambda x: x["FunctionName"]):
        fn = f["FunctionName"]
        env = ((f.get("Environment") or {}).get("Variables") or {})
        rows.append({
            "function": fn,
            "sourcePath": dmap.get(fn),
            "inDeployMap": fn in dmap,
            "runtime": f.get("Runtime"),
            "packageType": f.get("PackageType", "Zip"),
            "architectures": f.get("Architectures", []),
            "memoryMb": f.get("MemorySize"),
            "timeoutSec": f.get("Timeout"),
            "codeSha256": f.get("CodeSha256"),
            "lastModified": f.get("LastModified"),
            "snapStart": (f.get("SnapStart") or {}).get("ApplyOn"),
            "layers": [l.get("Arn", "").split(":layer:")[-1]
                       for l in (f.get("Layers") or [])],
            "role": (f.get("Role") or "").split("/")[-1],
            "deadLetterArn": (f.get("DeadLetterConfig") or {}).get("TargetArn"),
            "aliases": aliases.get(fn, {}),
            "hasLiveAlias": "live" in aliases.get(fn, {}),
            "routes": sorted(routes_by_fn.get(fn, [])),
            "routeCount": len(routes_by_fn.get(fn, [])),
            "envNames": sorted(env.keys()),
            "envSensitiveNames": sorted(k for k in env if SENSITIVE_HINT.search(k)),
            "eventSources": event_sources.get(fn, []),
            "logRetentionDays": retention.get(fn),
            "invocations24h": inv_24h.get(fn, 0.0),
            "errors24h": err_24h.get(fn, 0.0),
            "invocations7d": inv_7d.get(fn, 0.0),
            "errors7d": err_7d.get(fn, 0.0),
        })

    # anomalies worth a human's attention
    anomalies = {
        "liveButNotInDeployMap": [r["function"] for r in rows if not r["inDeployMap"]],
        "noLiveAliasButHasRoutes": [r["function"] for r in rows
                                    if r["routeCount"] and not r["hasLiveAlias"]],
        "routesTargetingLatest": [f"{r['apiId']} {r['routeKey']} -> {r['targetFunction']}"
                                  for r in all_routes
                                  if r["qualifier"] == "$LATEST" and r["targetFunction"]],
        "routesToAbsentFunction": [f"{r['apiId']} {r['routeKey']} -> {r['targetFunction']}"
                                   for r in all_routes
                                   if r["targetFunction"]
                                   and r["targetFunction"] not in set(names)],
        "zeroInvocations7d": [r["function"] for r in rows if r["invocations7d"] == 0],
        "errors7d": {r["function"]: r["errors7d"] for r in rows if r["errors7d"]},
        "noRoutesNoEventSourceNoTraffic": [
            r["function"] for r in rows
            if not r["routeCount"] and not r["eventSources"]
            and r["invocations7d"] == 0
        ],
        # `None` means the lookup itself failed, and "no log group" means the function
        # has never written one. Neither is "has a retention policy", so neither is
        # counted as clean - the previous check compared only against "never expires",
        # so an unreadable or unmatched group silently passed.
        "logsNeverExpire": [r["function"] for r in rows
                            if r["logRetentionDays"] == "never expires"],
        "logRetentionUnknown": [r["function"] for r in rows
                                if r["logRetentionDays"] is None],
        "routesWithoutFrontendCaller": sorted(
            p for p, c in callers.items() if not c),
    }

    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": REGION,
        "counts": {
            "functions": len(rows),
            "httpApis": len([a for a in apis if a.get("ProtocolType") == "HTTP"]),
            "routes": len(all_routes),
            "tables": len(tables),
            "withLiveAlias": sum(1 for r in rows if r["hasLiveAlias"]),
        },
        "functions": rows,
        "routes": sorted(all_routes, key=lambda r: (r["apiId"], r["routeKey"] or "")),
        "tables": sorted(tables),
        "frontendCallersByRoutePath": callers,
        "anomalies": anomalies,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    c = report["counts"]
    md = [
        "# Runtime inventory",
        "",
        f"Generated {report['generated']} · `{REGION}` · "
        f"regenerate with `python scripts/generate_runtime_inventory.py`",
        "",
        "Machine-readable companion: `runtime-inventory.json`. Environment variable",
        "**names** are recorded, values never are.",
        "",
        "| Count | |",
        "|---|---:|",
        f"| Lambda functions | {c['functions']} |",
        f"| with a `live` alias | {c['withLiveAlias']} |",
        f"| HTTP APIs | {c['httpApis']} |",
        f"| Routes | {c['routes']} |",
        f"| DynamoDB tables | {c['tables']} |",
        "",
        "## Anomalies",
        "",
        "Each list is a question to answer, not automatically a defect.",
        "",
    ]
    labels = {
        "liveButNotInDeployMap": "Live functions absent from the deploy map — cannot be patched by the standard path",
        "noLiveAliasButHasRoutes": "Functions with routes but no `live` alias — `$LATEST` reaches production directly",
        "routesTargetingLatest": "Routes whose integration is unqualified — bypasses the version/alias model",
        "routesToAbsentFunction": "Routes pointing at a function that does not exist",
        "errors7d": "Functions with errors in 7 days",
        "zeroInvocations7d": "Zero invocations in 7 days — candidates for retirement review",
        "noRoutesNoEventSourceNoTraffic": "No route, no event source, no traffic — strongest retirement candidates",
        "logsNeverExpire": "Log groups with no retention — unbounded cost and data retention",
        "routesWithoutFrontendCaller": "Route paths no frontend file mentions — provider webhook, internal, or dead",
    }
    for key, label in labels.items():
        val = anomalies[key]
        md += [f"### {label}", ""]
        if not val:
            md += ["(none)", ""]
            continue
        if isinstance(val, dict):
            md += [f"- `{k}`: {int(v)}" for k, v in sorted(val.items())] + [""]
        else:
            known = EXPECTED.get(key, {})
            unanswered = [v for v in val if v not in known]
            for v in val:
                if v in known:
                    md.append(f"- `{v}` — **expected**: {known[v]}")
                else:
                    md.append(f"- `{v}`")
            md += [""]
            if known and not unanswered:
                md += ["Every entry above is a documented exception.", ""]

    OUT_MD.write_text("\n".join(md))

    if not args.quiet:
        print(f"functions {c['functions']}  routes {c['routes']}  "
              f"tables {c['tables']}  live-alias {c['withLiveAlias']}")
        for key, label in labels.items():
            val = anomalies[key]
            known = EXPECTED.get(key, {})
            unanswered = len([v for v in val if v not in known]) \
                if not isinstance(val, dict) else len(val)
            suffix = "" if unanswered == len(val) else \
                f"  ({len(val) - unanswered} expected)"
            print(f"  {unanswered:>3}  {label}{suffix}")
        print(f"\nwrote {OUT_JSON.relative_to(REPO)}")
        print(f"wrote {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
