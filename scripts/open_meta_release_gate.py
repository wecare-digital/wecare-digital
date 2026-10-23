#!/usr/bin/env python3
"""Open the Meta catalog release gate safely by flipping ONE env var on the live function.

WHAT THIS DOES
--------------
Sets `META_CATALOG_SYNC_DRY_RUN=false` on `wecare-meta-catalog-sync`, which is the single
value keeping the release gate Closed once a plan is APPROVED and `META_CATALOG_SYNC_ENABLED`
is already `true`. After this, "Apply to Meta" unlocks for the approved exact-plan hash and a
real provider write becomes possible.

WHY A DEDICATED TOOL INSTEAD OF `aws lambda update-function-configuration`
--------------------------------------------------------------------------
`update-function-configuration --environment` REPLACES the entire variable map. Hand-running it
with just the two gate vars would wipe every other variable the function needs (the Meta token
secret id, catalog id, table names...). This tool does a MERGE: it reads the current live env,
changes only `META_CATALOG_SYNC_DRY_RUN`, and writes the full map back - so nothing else is lost.

SAFETY
------
* Dry-run by default: prints the exact before/after diff and exits without writing.
* `--apply` writes, then waits for the update and reads the value back to confirm.
* Refuses unless `META_CATALOG_SYNC_ENABLED` is already `true` (opening dry-run alone on a
  disabled function is pointless and signals a misread state).
* Requires `--i-understand-this-enables-production-catalog-writes` together with `--apply`,
  because this is the switch that lets an approved plan write to the customer-visible Meta
  catalogue (the current plan RETIRES 21 live items - confirm that is intended first).
* This does NOT approve a plan and does NOT call Apply. It only opens the gate. The exact-plan
  approval and the Apply click remain separate, deliberate owner actions.

USAGE
-----
    python scripts/open_meta_release_gate.py                 # dry-run: show the diff
    python scripts/open_meta_release_gate.py --apply \
        --i-understand-this-enables-production-catalog-writes

    # to re-close the gate (restore the safe default):
    python scripts/open_meta_release_gate.py --close --apply \
        --i-understand-this-enables-production-catalog-writes

Exit: 0 on a clean dry-run or a confirmed apply; non-zero on refusal or verification failure.
"""
from __future__ import annotations

import argparse
import sys

REGION = "us-east-1"
FUNCTION = "wecare-meta-catalog-sync"
ENABLED_KEY = "META_CATALOG_SYNC_ENABLED"
DRY_RUN_KEY = "META_CATALOG_SYNC_DRY_RUN"

# Mirror the handler's own token sets (handler lines 310-311) so "open"/"closed" here means
# exactly what the function will compute. _dry_run() is OFF only when the value is in _FALSE.
_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})

CONFIRM_FLAG = "i_understand_this_enables_production_catalog_writes"


def _lambda():
    import boto3
    return boto3.client("lambda", region_name=REGION)


def _read_env(lam) -> dict:
    cfg = lam.get_function_configuration(FunctionName=FUNCTION)
    return dict((cfg.get("Environment") or {}).get("Variables") or {})


def _gate_state(env: dict) -> tuple[bool, bool]:
    enabled = str(env.get(ENABLED_KEY, "")).strip().lower() in _TRUE
    dry_run = str(env.get(DRY_RUN_KEY, "")).strip().lower() not in _FALSE  # absent/typo => ON
    return enabled, dry_run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the update (default: dry-run)")
    ap.add_argument("--close", action="store_true",
                    help="restore the safe default (DRY_RUN=true) instead of opening")
    ap.add_argument(f"--{CONFIRM_FLAG.replace('_', '-')}", dest=CONFIRM_FLAG,
                    action="store_true",
                    help="required with --apply when OPENING the gate")
    args = ap.parse_args()

    target_dry_run = "true" if args.close else "false"
    opening = not args.close

    lam = _lambda()
    try:
        env = _read_env(lam)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot read {FUNCTION} configuration: {exc}", file=sys.stderr)
        return 1

    enabled_now, dry_run_now = _gate_state(env)
    print(f"Function: {FUNCTION} ({REGION})")
    print(f"  {ENABLED_KEY} = {env.get(ENABLED_KEY)!r}  (enabled={enabled_now})")
    print(f"  {DRY_RUN_KEY} = {env.get(DRY_RUN_KEY)!r}  (dry_run={dry_run_now})")
    print(f"  current gate: {'OPEN' if (enabled_now and not dry_run_now) else 'CLOSED'}")

    if opening and not enabled_now:
        print(f"\nREFUSING: {ENABLED_KEY} is not true. Opening dry-run on a disabled function "
              "does not open the gate; confirm the intended state first.", file=sys.stderr)
        return 1

    if env.get(DRY_RUN_KEY, "").strip().lower() == target_dry_run:
        print(f"\nNo change needed: {DRY_RUN_KEY} is already {target_dry_run!r}.")
        return 0

    new_env = dict(env)
    new_env[DRY_RUN_KEY] = target_dry_run
    print(f"\nProposed change (merge - all other {len(env)} variables preserved):")
    print(f"  {DRY_RUN_KEY}: {env.get(DRY_RUN_KEY)!r} -> {target_dry_run!r}")
    print(f"  resulting gate: {'OPEN' if (enabled_now and target_dry_run in _FALSE) else 'CLOSED'}")

    if opening:
        print("\n*** This OPENS the production catalog write gate. The approved plan can then "
              "write to the live Meta catalogue (the current plan RETIRES 21 items). ***")

    if not args.apply:
        print("\nDRY RUN: nothing written. Re-run with --apply "
              + ("" if args.close else f"--{CONFIRM_FLAG.replace('_', '-')} ") + "to proceed.")
        return 0

    if opening and not getattr(args, CONFIRM_FLAG):
        print(f"\nREFUSING --apply: opening the gate requires "
              f"--{CONFIRM_FLAG.replace('_', '-')}.", file=sys.stderr)
        return 1

    # Merge write: replace the whole map, but the map IS the live map with one key changed.
    lam.update_function_configuration(
        FunctionName=FUNCTION, Environment={"Variables": new_env})
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)

    confirmed = _read_env(lam)
    c_enabled, c_dry = _gate_state(confirmed)
    if confirmed.get(DRY_RUN_KEY, "").strip().lower() != target_dry_run:
        print(f"\nVERIFY FAILED: {DRY_RUN_KEY} readback is "
              f"{confirmed.get(DRY_RUN_KEY)!r}, expected {target_dry_run!r}", file=sys.stderr)
        return 1
    # Preservation check: every other key survived.
    lost = sorted(set(env) - set(confirmed))
    if lost:
        print(f"\nWARNING: variables missing after write: {lost}", file=sys.stderr)
        return 1

    print(f"\nDONE. gate is now {'OPEN' if (c_enabled and not c_dry) else 'CLOSED'} "
          f"({len(confirmed)} variables intact).")
    if c_enabled and not c_dry:
        print("Apply to Meta is now unlocked for the APPROVED exact-plan hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
