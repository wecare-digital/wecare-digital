"""Provision WABA2 as a dedicated immutable alias of the proven Meta catalog sync Lambda.

The base function remains `wecare-meta-catalog-sync`.
- alias `live` -> WABA1 catalog 1457045652952851, token field access_token
- alias `waba2` -> WABA2 catalog 1317472650427643, token field access_token_waba2

Both aliases read the same ProductsTable authority and keep the same dry-run / exact-plan gates.
A separate alias/version is enough because Lambda versions freeze environment variables as well as
code, so the two WABAs cannot overwrite each other's catalog configuration.
"""
from __future__ import annotations

import argparse
import boto3

REGION = "us-east-1"
FUNCTION = "wecare-meta-catalog-sync"
WABA2_ALIAS = "waba2"
WABA2_SCHEDULE_RULE = "wecare-meta-catalog-sync-waba2-schedule"
WABA2_CATALOG_ID = "1317472650427643"
WABA2_TOKEN_FIELD = "access_token_waba2"
SCHEDULE_EXPRESSION = "cron(25 */6 * * ? *)"


def lam():
    return boto3.client("lambda", region_name=REGION)


def events():
    return boto3.client("events", region_name=REGION)


def alias_arn() -> str:
    return f"arn:aws:lambda:{REGION}:775261844268:function:{FUNCTION}:{WABA2_ALIAS}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        alias = lam().get_alias(FunctionName=FUNCTION, Name=WABA2_ALIAS)
        version = lam().get_function_configuration(
            FunctionName=FUNCTION, Qualifier=alias["FunctionVersion"]
        )
        env = (version.get("Environment") or {}).get("Variables") or {}
        problems = []
        if env.get("META_CATALOG_ID") != WABA2_CATALOG_ID:
            problems.append("wrong WABA2 catalog id")
        if env.get("META_TOKEN_FIELD") != WABA2_TOKEN_FIELD:
            problems.append("wrong WABA2 token field")
        mappings = lam().list_event_source_mappings(FunctionName=alias_arn()).get(
            "EventSourceMappings", []
        )
        if not mappings or not any(m.get("State") == "Enabled" for m in mappings):
            problems.append("WABA2 alias has no enabled ProductsTable stream mapping")
        rule = events().describe_rule(Name=WABA2_SCHEDULE_RULE)
        if rule.get("State") != "ENABLED":
            problems.append("WABA2 schedule is not enabled")
        print("in step" if not problems else "\n".join(problems))
        return 1 if problems else 0

    print("Use the production deployment workflow to publish the WABA2-configured version,")
    print("point alias waba2 at it, and wire the stream + schedule. --verify is read-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
