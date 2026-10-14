"""Provision the existing Contacts API lock/unlock routes, without deploying Lambda code.

Default is DRY RUN. The API integration must already exist for POST /contacts,
and both new routes reuse that exact integration. Never overwrite a conflicting
route or mutate an existing integration. Requires AWS credentials only with --apply.
"""
import argparse
import boto3
import os

API_ID = os.environ.get("API_ID", "zllr9lrg7j")
REGION = os.environ.get("AWS_REGION", "us-east-1")
ROUTES = (
    "POST /contacts/{contactId}/lock",
    "POST /contacts/{contactId}/unlock",
)


def plan(client, *, apply=False):
    integrations = []
    token = None
    while True:
        kwargs = {"ApiId": API_ID}
        if token:
            kwargs["NextToken"] = token
        page = client.get_routes(**kwargs)
        integrations.extend(page.get("Items", []))
        token = page.get("NextToken")
        if not token:
            break
    by_key = {r["RouteKey"]: r for r in integrations}
    existing = by_key.get("POST /contacts")
    if not existing or not existing.get("Target", "").startswith("integrations/"):
        raise RuntimeError("POST /contacts integration missing; refusing to guess")
    target = existing["Target"]
    result = {}
    for key in ROUTES:
        row = by_key.get(key)
        if row:
            if row.get("Target") != target:
                raise RuntimeError(f"Conflicting route {key}: {row.get('Target')}")
            result[key] = "exists"
        elif apply:
            client.create_route(ApiId=API_ID, RouteKey=key, Target=target,
                                AuthorizationType="NONE")
            result[key] = "created (handler enforces auth)"
        else:
            result[key] = f"would create -> {target}"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = boto3.client("apigatewayv2", region_name=REGION)
    for key, status in plan(client, apply=args.apply).items():
        print(f"{key}: {status}")
