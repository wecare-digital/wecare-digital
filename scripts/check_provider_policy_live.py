#!/usr/bin/env python3
"""The provider allow-list, asserted against the LIVE AWS account.

Why this exists
---------------
``scripts/check_provider_allowlist.py`` proves what the source tree references. It cannot
see the account, and a clean tree is not a clean estate: a retirement commit removes code,
while the deployed function, its API routes, its environment and its secrets stay live
until something removes them. This script reads the account and applies the same
allow-list - ``scripts/provider_allowlist.py`` - to what is actually deployed.

It is positive in the same way. Nothing here names a provider that must be absent; every
live secret, environment value, webhook route and channel Lambda must be APPROVED, so
anything outside the allow-list fails whatever it is called.

What it checks
--------------
1. SECRETS      every Secrets Manager secret name starts with an approved prefix.
2. LAMBDA ENV   on every live function: URL/host values resolve to approved domains,
                secret-id values carry an approved prefix (single-capability providers
                only on their own functions), backend selectors hold approved values,
                and credential/endpoint-shaped keys carry an approved namespace.
3. ROUTES       every webhook-shaped route on every HTTP/WebSocket API is an approved
                webhook route.
4. FUNCTIONS    voice, SMS and RCS Lambdas are exactly the supported functions, and every
                live Lambda can be redeployed from this repo (the deploy map, or the short
                list of externally deployed functions). The question is whether a fix can
                REACH production, not whether source exists somewhere in the tree.

Values are never printed except where the value IS the finding and is not a credential:
a host, a secret NAME, a selector value. Credential-shaped keys are reported by name.

Usage
-----
    python scripts/check_provider_policy_live.py           # gate
    python scripts/check_provider_policy_live.py --report  # list everything, exit 0
    python scripts/check_provider_policy_live.py --json

Exit codes
----------
    0  every live reference is approved and every live function is deployable
    1  a live reference is not on the allow-list, or a live function cannot be redeployed
       (the two are reported separately)
    2  could not query AWS
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import provider_allowlist as allow  # noqa: E402

REGION = "us-east-1"

# Live Lambdas this repo deliberately does not deploy through scripts/deploy_all_lambdas.py.
# Documented in .kiro/steering/lambda-snapstart-deploy.md (retired 2026-10-09, af7858fa).
EXTERNALLY_DEPLOYED = {
    "wecare-seo-tools",      # scripts/deploy_seo_tools.py owns it
    "wecare-docs-scraper",   # PackageType=Image; separate container deployment
    # Lambda@Edge, source at amplify/functions/edge/get-miss-redirect. CloudFront associates
    # Lambda@Edge by published VERSION, and the deploy map's contract is
    # publish-then-move-the-`live`-alias; an alias is not a valid Lambda@Edge association
    # target. Owned by its own deployer; see docs/SECURE-FILE-SHARING.md.
    "wecare-get-miss-redirect",
    # scripts/provision_native_catalog_api.py packages and updates it, run by
    "wecare-native-catalog-admin",
}

#: The deployability finding, kept apart from allow-list findings in the report. A live
#: function no supported path can redeploy cannot receive a fix, whoever it talks to.
UNDEPLOYABLE = "not in the deploy map: no supported path can patch it"

URL_VALUE = re.compile(r"\b(?:https?|wss?)://([A-Za-z0-9.-]+)")
HOST_VALUE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?$")
VAULT_REF = re.compile(r"^wecare/[A-Za-z0-9._/+-]*$")


def deploy_map() -> set:
    """Function names the portable deploy path can reach."""
    try:
        import deploy_all_lambdas as deploy  # type: ignore
        return ({spec.name for spec in deploy.SPECS} | set(deploy.DELEGATED)
                | set(deploy.SKIPPED))
    except Exception:  # noqa: BLE001 - fall back to the script's own listing
        out = subprocess.run([sys.executable, str(ROOT / "scripts/deploy_all_lambdas.py"),
                              "--list"], capture_output=True, text=True).stdout
        return set(re.findall(r"^\s*((?:stack-)?wecare[a-z0-9-]*)", out, re.M))


def _paginate_v2(call, **kwargs) -> list:
    items, token = [], None
    while True:
        params = dict(kwargs, MaxResults="100")
        if token:
            params["NextToken"] = token
        page = call(**params)
        items += page.get("Items", [])
        token = page.get("NextToken")
        if not token:
            return items


def check_env(fn: str, env: dict) -> list:
    """Findings for one function's environment. Pure, so it is unit-testable."""
    findings = []
    owner = f"lambda:{fn}"
    ids = allow.provider_ids()
    for key, value in sorted((env or {}).items()):
        value = value if isinstance(value, str) else ""
        if allow.is_credential_env_key(key) and not allow.env_namespace_ok(key):
            findings.append(("env", fn, key,
                             "credential/endpoint key outside the approved namespaces"))
        for host in URL_VALUE.findall(value):
            if allow.host_owner(host, owner)[0] is None:
                findings.append(("env", fn, f"{key} -> {host}",
                                 allow.host_owner(host, owner)[1]))
        if not URL_VALUE.search(value) and HOST_VALUE.match(value):
            host = value.split("/", 1)[0]
            if allow.host_owner(host, owner)[0] is None:
                findings.append(("env", fn, f"{key} -> {host}",
                                 allow.host_owner(host, owner)[1]))
        for part in (p.strip() for p in value.split(",")):
            if VAULT_REF.match(part) and part.rstrip("/") != "wecare":
                found, why = allow.vault_owner(part, owner)
                if found is None:
                    findings.append(("env", fn, f"{key} -> {part}", why))
        if key in allow.SELECTOR_VALUES and value not in allow.SELECTOR_VALUES[key]:
            findings.append(("env", fn, f"{key}={value}",
                             f"selector value not approved ({sorted(allow.SELECTOR_VALUES[key])})"))
        elif key.endswith(allow.PROVIDER_SELECTOR_SUFFIX) and value and value not in ids:
            findings.append(("env", fn, f"{key}={value}",
                             "provider selector value not in the approved vocabulary"))
    return findings


def check_vault_entry(name: str) -> list:
    found, why = allow.vault_owner(name)
    return [] if found else [("secret", name, name, why)]


def check_route(api_id: str, route_key: str) -> list:
    path = route_key.split(None, 1)[-1]
    if allow.is_webhook_route(path) and not allow.webhook_route_ok(path):
        return [("route", api_id, route_key, "webhook route not on the allow-list")]
    return []


def check_function(fn: str, deployable: set) -> list:
    findings = []
    if not allow.channel_function_ok(fn):
        findings.append(("lambda", fn, fn,
                         f"{allow.channel_of(fn)} Lambda outside the supported set"))
    if deployable and fn not in deployable and fn not in EXTERNALLY_DEPLOYED:
        findings.append(("lambda", fn, fn, UNDEPLOYABLE))
    return findings


def collect(client) -> tuple[list, dict]:
    """Read the account through ``client(service)`` and return (findings, counts)."""
    findings: list = []
    counts = {"vault_entries": 0, "functions": 0, "env_values": 0, "apis": 0, "routes": 0}

    sm = client("secretsmanager")
    for page in sm.get_paginator("list_secrets").paginate():
        for entry in page.get("SecretList", []):
            counts["vault_entries"] += 1
            findings += check_vault_entry(entry["Name"])

    lam = client("lambda")
    deployable = deploy_map()
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page.get("Functions", []):
            name = fn["FunctionName"]
            env = (fn.get("Environment") or {}).get("Variables") or {}
            counts["functions"] += 1
            counts["env_values"] += len(env)
            findings += check_function(name, deployable)
            findings += check_env(name, env)

    api = client("apigatewayv2")
    for item in _paginate_v2(api.get_apis):
        counts["apis"] += 1
        # get_routes returns 25 items per page by default and has no boto3 paginator, so
        # NextToken is always drained - reading page 1 alone undercounts a 375-route API.
        for route in _paginate_v2(api.get_routes, ApiId=item["ApiId"]):
            counts["routes"] += 1
            findings += check_route(item["ApiId"], route["RouteKey"])
    return findings, counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="list everything and exit 0")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        print("boto3 required: .venv/bin/python -m pip install boto3", file=sys.stderr)
        return 2

    def client(service):
        return boto3.client(service, region_name=REGION)

    try:
        findings, counts = collect(client)
    except (ClientError, BotoCoreError) as exc:
        print(f"could not query AWS: {type(exc).__name__}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"region": REGION, "counts": counts,
                          "findings": [dict(zip(("kind", "resource", "reference", "why"), f))
                                       for f in findings]}, indent=2))
        return 0 if (args.report or not findings) else 1

    print(f"account region : {REGION}")
    print(f"allow-list     : {', '.join(p.name for p in allow.PROVIDERS)}")
    print(f"scanned        : {counts['vault_entries']} secrets, {counts['functions']} functions "
          f"({counts['env_values']} env values), {counts['routes']} routes on "
          f"{counts['apis']} API(s)")
    provider = [f for f in findings if f[3] != UNDEPLOYABLE]
    undeployable = [f for f in findings if f[3] == UNDEPLOYABLE]
    if provider:
        print(f"\nNOT ON THE ALLOW-LIST ({len(provider)}):")
        for kind, resource, reference, why in sorted(provider):
            print(f"  {kind:7} {resource:34} {reference}")
            print(f"          {why}")
        print("\nLIVE PROVIDER ALLOW-LIST FAILED - the account uses something "
              "scripts/provider_allowlist.py does not approve.")
        print("Remove it from the account, or approve it there as a deliberate decision.")
    else:
        print("\nLIVE PROVIDER ALLOW-LIST OK - every live secret, environment value, "
              "webhook route and channel Lambda is approved.")
    if undeployable:
        print(f"\nUNDEPLOYABLE FUNCTIONS ({len(undeployable)}) - {UNDEPLOYABLE}:")
        for _kind, resource, _reference, _why in sorted(undeployable):
            print(f"  lambda  {resource}")
        print("Restore its source and add it to scripts/deploy_all_lambdas.py, record its "
              "own deployer in EXTERNALLY_DEPLOYED, or retire it.")
    if findings and not args.report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
