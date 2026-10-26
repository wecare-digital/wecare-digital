#!/usr/bin/env python3
"""Retired compatibility command for the disabled WhatsApp order-status rail.

Product policy since 2026-10-26: fulfilment is internal (OrderTable / Track Order) and no
structured WhatsApp order-status message is sent. The historical Meta template may remain in
provider inventory, but this repository must never create, resubmit, or require it.

This command intentionally performs no AWS or Meta calls. It is kept only so old runbooks and
operator muscle memory fail safely instead of resurrecting the retired message rail.
"""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        print("RETIRED: WhatsApp order-status sends are disabled; provider template approval is not a release gate.")
        return 0
    if args.dry_run:
        print("RETIRED: no order-status template would be submitted.")
        return 0
    print("REFUSED: order-status template provisioning is retired. Nothing was changed.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
