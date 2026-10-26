#!/usr/bin/env python3
"""Provision and verify the wecare-commerce runtime.

wecare-commerce runs the exact checkout+invoice package wecare-checkout runs. This script reuses
provision_checkout's package, IAM and environment contracts, but gives the runtime its own
function/role/log group. It creates NO API Gateway routes or invoke permissions.

Since the commerce cutover (#1554, 2026-10-25) the checkout and invoice integrations target
`wecare-commerce:live`, so `--verify` requires the alias to be invocable by this API's routes and
by nothing else. Razorpay settlement verification remains in wecare-razorpay-webhook.

Usage:
    python scripts/provision_commerce.py --dry-run
    python scripts/provision_commerce.py
    python scripts/provision_commerce.py --verify
"""
from __future__ import annotations

import argparse

import provision_checkout as checkout

checkout.FUNCTION_NAME = "wecare-commerce"
checkout.ROLE_NAME = "wecare-commerce-role"
checkout.DEPLOY_SOURCE_ROOT = checkout.ROOT / ".scratch" / "deploy-commerce"


def _retag_role_description() -> None:
    """The reused policy builders are authoritative; only names differ for the shadow runtime."""
    # All helper functions in provision_checkout resolve FUNCTION_NAME/ROLE_NAME dynamically from
    # module globals, so overriding those two constants before any call is sufficient.
    return None


def verify_runtime(members=None, source_note: str = "") -> int:
    """Read back the commerce runtime; its `live` alias must be invocable by this API only."""
    problems = []

    if not checkout.function_exists():
        print("function: missing")
        return 1

    cfg = checkout.lam().get_function_configuration(
        FunctionName=checkout.FUNCTION_NAME, Qualifier=checkout.LIVE_ALIAS)
    print(
        f"function: present (live v{cfg.get('Version')}); "
        f"memory={cfg.get('MemorySize')} timeout={cfg.get('Timeout')}"
    )
    if cfg.get("MemorySize") != 512:
        problems.append("memory is not 512 MB")
    if cfg.get("Timeout") != 60:
        problems.append("timeout is not 60 seconds")

    env = dict((cfg.get("Environment") or {}).get("Variables") or {})
    for key, value in checkout.expected_environment().items():
        if env.get(key) != value:
            problems.append(f"environment mismatch: {key}")

    aliases = checkout.lam().list_aliases(FunctionName=checkout.FUNCTION_NAME).get("Aliases", [])
    live = next((a for a in aliases if a.get("Name") == checkout.LIVE_ALIAS), None)
    if not live:
        problems.append("live alias missing")
    else:
        print(f"live alias: -> v{live.get('FunctionVersion')}")

    # The cut-over routes need API Gateway to invoke :live. Any other grant on the alias is a
    # caller nobody provisioned, so it is reported rather than tolerated.
    statements = checkout.live_policy_statements()
    api_prefix = f"arn:aws:execute-api:{checkout.REGION}:{checkout.account_id()}:{checkout.API_ID}/"

    def _from_this_api(statement: dict) -> bool:
        principal = statement.get("Principal")
        service = principal.get("Service") if isinstance(principal, dict) else principal
        return (statement.get("Effect") == "Allow"
                and service == "apigateway.amazonaws.com"
                and statement.get("Action") == "lambda:InvokeFunction"
                and checkout._statement_source_arn(statement).startswith(api_prefix))

    foreign = sorted(str(s.get("Sid") or "?") for s in statements if not _from_this_api(s))
    if not statements:
        problems.append("live alias has no API Gateway invoke permission, so the cut-over "
                        "checkout and invoice routes cannot reach it")
    elif foreign:
        problems.append(f"live alias grants invoke beyond {checkout.API_ID}'s routes: {foreign}")
    else:
        print(f"invoke policy: {len(statements)} statement(s), API Gateway {checkout.API_ID} only")

    if members is not None:
        errors, warnings = checkout.validate_members(members, checkout.ROOT)
        for warning in warnings:
            print(f"  warning: {warning}")
        problems.extend(errors)

    if source_note:
        print(f"comparison source: {source_note}")

    if problems:
        print("\nFAIL:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\ncommerce runtime verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--source-root", default=None, metavar="PATH")
    args = parser.parse_args(argv)

    source_root, why = checkout.resolve_source_root(
        args.source_root, prefer_deploy_export=args.verify)

    try:
        zip_bytes, members, errors, warnings = checkout.build_package(source_root)
    except Exception as exc:
        if args.verify:
            print(f"note: comparison package unavailable: {type(exc).__name__}")
            return verify_runtime(None, source_note=why)
        raise

    if args.verify:
        return verify_runtime(members, source_note=why)

    print(f"region: {checkout.REGION}")
    print(f"source root: {why}")
    print("mode: route owner since #1554; this script creates no routes or invoke permissions")
    print(f"dry run: {args.dry_run}\n")

    if checkout.report_package(zip_bytes, members, errors, warnings):
        return 1

    print(f"role: {checkout.ensure_role(args.dry_run)}")
    print(f"log group: {checkout.ensure_log_group(args.dry_run)}")
    print(f"Lambda: {checkout.ensure_function(args.dry_run, zip_bytes)}")
    print(f"env: {checkout.reconcile_environment(args.dry_run)}")
    print(f"runtime: {checkout.reconcile_runtime_shape(args.dry_run)}")
    print(f"layers: {checkout.reconcile_layers(args.dry_run)}")
    print(f"live alias: {checkout.ensure_live_alias(args.dry_run)}")

    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0

    print("\nread-back verification:")
    return verify_shadow(members, source_note=why)


if __name__ == "__main__":
    raise SystemExit(main())
