#!/usr/bin/env python3
"""Retired compatibility command for the old WhatsApp order-status retry index.

The live invoice table may still carry the historical `orderStatusRetry-index` and old rows may
still contain `pendingOrderStatus` / `orderStatusRetry` fields. They are audit-only. Runtime
reconciliation deliberately ignores them and must never retry a WhatsApp fulfilment message.

This command makes no DynamoDB calls and cannot create or backfill retry state.
"""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args(argv)
    if args.apply or args.backfill:
        print("REFUSED: WhatsApp order-status retry provisioning is retired. Nothing was changed.")
        return 2
    print("RETIRED: historical retry fields/index are audit-only; no retry worker consumes them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
