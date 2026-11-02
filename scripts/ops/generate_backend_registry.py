#!/usr/bin/env python3
"""Generate a local, PRIVATE backend registry. Do not commit the output.

Examples:
  python scripts/ops/generate_backend_registry.py --expected-account 123456789012 > .scratch/backend-registry.json

The registry contains ARNs, API routes, infrastructure linkage and role names,
which are operationally sensitive. Keep it in restricted storage.
"""
import argparse
import json
from datetime import datetime, timezone
import boto3

REGION = "us-east-1"

def pages(client, operation, key, **kwargs):
    paginator = client.get_paginator(operation)
    for page in paginator.paginate(**kwargs):
        yield from page.get(key, [])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-account", required=True)
    args = parser.parse_args()
    session = boto3.Session(region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    if account != args.expected_account:
        parser.error("Unexpected account; refusing to enumerate.")
    lam = session.client("lambda")
    api = session.client("apigatewayv2")
    db = session.client("dynamodb")
    events = session.client("events")
    cloud = session.client("cloudformation")
    functions = list(pages(lam, "list_functions", "Functions"))
    tables = list(pages(db, "list_tables", "TableNames"))
    apis = list(pages(api, "get_apis", "Items"))
    stacks = [x for x in pages(cloud, "list_stacks", "StackSummaries") if x["StackStatus"] != "DELETE_COMPLETE"]
    rules = list(pages(events, "list_rules", "Rules"))
    stack_resources = {}
    for stack in stacks:
        for resource in pages(cloud, "list_stack_resources", "StackResourceSummaries", StackName=stack["StackName"]):
            if resource.get("PhysicalResourceId"):
                stack_resources[resource["PhysicalResourceId"]] = stack["StackName"]
    rows = []
    for application in apis:
        api_id = application["ApiId"]
        integrations = {x["IntegrationId"]: x for x in pages(api, "get_integrations", "Items", ApiId=api_id)}
        for route in pages(api, "get_routes", "Items", ApiId=api_id):
            integration = integrations.get(route.get("Target", "").split("/")[-1], {})
            rows.append({"api_id": api_id, "api_name": application["Name"], "route": route.get("RouteKey"),
                         "authorization": route.get("AuthorizationType"),
                         "integration_uri": integration.get("IntegrationUri")})
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "account": account, "region": REGION,
        "lambdas": [{"name": f["FunctionName"], "runtime": f.get("Runtime", "image"),
                     "role": f["Role"], "stack": stack_resources.get(f["FunctionName"]),
                     "aliases": [{"name": a["Name"], "version": a["FunctionVersion"]}
                                 for a in pages(lam, "list_aliases", "Aliases", FunctionName=f["FunctionName"])],
                     "source_path": None, "deployment_script": None, "business_owner": None}
                    for f in functions],
        "tables": [{"name": t, "stack": stack_resources.get(t), "consumers": None} for t in tables],
        "routes": rows,
        "event_rules": [{"name": r["Name"], "state": r.get("State"),
                         "targets": [{"id": t["Id"], "arn": t["Arn"]}
                                     for t in pages(events, "list_targets_by_rule", "Targets", Rule=r["Name"])]}
                        for r in rules],
        "event_source_mappings": [{"function_arn": x.get("FunctionArn"),
                                   "source_arn": x.get("EventSourceArn"), "state": x.get("State")}
                                  for x in pages(lam, "list_event_source_mappings", "EventSourceMappings")],
        "cloudformation_stacks": [{"name": s["StackName"], "status": s["StackStatus"]} for s in stacks],
        "limitations": ["Missing source/deployer/owner fields require code review; do not infer from names"]
    }
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
