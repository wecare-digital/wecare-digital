#!/usr/bin/env python3
"""Narrow, gated deploy entrypoint for wecare-inbound-whatsapp.

The canonical packager remains scripts/deploy_all_lambdas.py. This wrapper exists
so the inbound WhatsApp Lambda can be dry-run or deployed without touching the
rest of the Lambda fleet.

It deliberately reuses deploy_all_lambdas.build_zip(), which packages:
- handler.py
- the COMPLETE recursive lambda_utils tree
- static_knowledge_base.py
- the function's COMPLETE modules/ tree

Running with no flags is a dry run. Production deployment requires --apply.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from deploy_all_lambdas import SPECS, build_zip

FUNCTION = "wecare-inbound-whatsapp"
ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ALL = ROOT / "scripts" / "deploy_all_lambdas.py"


def inbound_spec():
    matches = [spec for spec in SPECS if spec.name == FUNCTION]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one {FUNCTION} spec, found {len(matches)}"
        )
    return matches[0]


def validate_package() -> tuple[int, int]:
    """Build once and assert the inbound package contains its critical trees."""
    zip_bytes, members = build_zip(inbound_spec())
    names = set(members)

    required = {"handler.py", "static_knowledge_base.py"}
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"inbound package missing required files: {missing}")

    if not any(name.startswith("modules/") for name in names):
        raise RuntimeError("inbound package contains no modules/ files")

    if not any(name.startswith("lambda_utils/ecommerce/") for name in names):
        raise RuntimeError(
            "inbound package contains no recursive lambda_utils/ecommerce files"
        )

    if not any(name.startswith("lambda_utils/identity/") for name in names):
        raise RuntimeError(
            "inbound package contains no recursive lambda_utils/identity files"
        )

    return len(zip_bytes), len(names)


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "deploy $LATEST, publish a version, and move the live alias. "
            "Without this flag the script only performs a dry run."
        ),
    )
    args = parser.parse_args()

    zip_size, member_count = validate_package()
    print(f"validated package: {member_count} files, {zip_size} bytes")

    cmd = [sys.executable, str(DEPLOY_ALL)]
    if not args.apply:
        cmd += ["--dry-run"]
    cmd += [FUNCTION]

    rc = run(cmd)
    if rc:
        return rc

    if not args.apply:
        print()
        print("DRY RUN ONLY: no production change was made.")
        print(
            "Do not use --apply until the Subscribe test and WhatsApp "
            "command/Flow behavior gates are green."
        )
    else:
        print()
        print(
            "Deployment command completed. deploy_all_lambdas.py also invokes "
            "snapstart_publish.py for the live alias."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
