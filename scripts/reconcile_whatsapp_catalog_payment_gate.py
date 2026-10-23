#!/usr/bin/env python3
"""Reconcile the WhatsApp catalog-order rollout gate on its two runtime owners.

This flag is non-secret and intentionally exact. A catalog order reaches payment only when both:
- wecare-inbound-whatsapp accepts the Meta `order` message, and
- wecare-checkout accepts `prepareNativeCart`.

The script preserves every unrelated environment variable, uses RevisionId as a lease, and
reads the result back. It does not send a message or create a payment.
"""
from __future__ import annotations

import argparse
import boto3

REGION = "us-east-1"
FLAG = "WA_CATALOG_ORDERS_ENABLED"
VALUE = "true"
TARGETS = ("wecare-inbound-whatsapp", "wecare-checkout")


def reconcile(lam, name: str, *, dry_run: bool) -> str:
    current = lam.get_function_configuration(FunctionName=name)
    env = dict((current.get("Environment") or {}).get("Variables") or {})
    if env.get(FLAG) == VALUE:
        return "already correct"
    if dry_run:
        return f"would set {FLAG}={VALUE}"
    revision = current.get("RevisionId")
    if not revision:
        raise RuntimeError(f"{name}: missing RevisionId")
    desired = dict(env)
    desired[FLAG] = VALUE
    lam.update_function_configuration(
        FunctionName=name,
        RevisionId=revision,
        Environment={"Variables": desired},
    )
    lam.get_waiter("function_updated_v2").wait(FunctionName=name)
    readback = lam.get_function_configuration(FunctionName=name)
    actual = dict((readback.get("Environment") or {}).get("Variables") or {})
    if actual.get(FLAG) != VALUE:
        raise RuntimeError(f"{name}: {FLAG} readback mismatch")
    for key, value in env.items():
        if actual.get(key) != value:
            raise RuntimeError(f"{name}: unrelated environment key changed: {key}")
    return f"set {FLAG}={VALUE}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    lam = boto3.client("lambda", region_name=REGION)
    for name in TARGETS:
        print(f"{name}: {reconcile(lam, name, dry_run=args.dry_run)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
