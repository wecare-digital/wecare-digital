#!/usr/bin/env python3
"""Provision the shadow wecare-commerce runtime without moving production traffic.

The commerce strangler deliberately starts as the exact proven checkout+invoice package.
This script reuses provision_checkout's package, IAM and environment contracts, but gives the
runtime its own function/role/log group and creates NO API Gateway routes or invoke permission.

Razorpay settlement verification remains in wecare-razorpay-webhook. This runtime owns checkout
intent + invoice/order orchestration only until a later reviewed cutover.

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


def verify_shadow(members=None, source_note: str = "") -> int:
    """Read back only the shadow-runtime facts; it must have no API Gateway resource policy."""
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

    # Shadow means unreachable from API Gateway. Any resource policy on :live is unexpected.
    statements = checkout.live_policy_statements()
    if statements:
        problems.append(
            "shadow live alias has invoke/resource-policy statements; no production caller "
            "should be able to reach it before cutover"
        )
    else:
        print("invoke policy: none (shadow-only, expected)")

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

    print("\ncommerce shadow provisioning verified")
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
            return verify_shadow(None, source_note=why)
        raise

    if args.verify:
        return verify_shadow(members, source_note=why)

    print(f"region: {checkout.REGION}")
    print(f"source root: {why}")
    print("mode: SHADOW (no API Gateway routes, no API invoke permission)")
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
