#!/usr/bin/env python3
"""Print the exact create/update/retire/foreign item ids for a Meta catalog inspect payload.

Read-only. Takes the JSON returned by `GET /wa-business/catalog-sync` (the staff-Admin inspect,
which carries `desiredItems` + `existingItems`) and re-runs the SAME diff the live sync uses, so
what it prints is exactly what Apply would do. No AWS, no writes.

    python scripts/decode_meta_plan.py < inspect.json
    curl -H "Authorization: Bearer $TOKEN" https://wecare.digital/api/wa-business/catalog-sync \
        | python scripts/decode_meta_plan.py

Why this exists: the inspect response reports COUNTS (create/update/retire/foreign) but a plan
with `retire: 21` should be verified by the actual retailer ids before the release gate is
opened. `retire` sets out-of-stock (reversible), `foreign` is never touched, but the owner
should still see which 21 owned variants go out of stock and which 22 foreign ids are left alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared" / "lambda_utils" / "ecommerce"))
import meta_catalog_sync as mcs  # noqa: E402  (the real diff/parse logic the handler uses)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        print(f"not valid JSON on stdin: {exc}", file=sys.stderr)
        return 2

    desired = payload.get("desiredItems") or []
    existing = payload.get("existingItems") or []
    if not desired and not existing:
        print("inspect payload has no desiredItems/existingItems. Pipe the full "
              "GET /wa-business/catalog-sync response (staff Admin token required).",
              file=sys.stderr)
        return 2

    plan = mcs.diff(desired, existing)
    counts = plan.counts()

    print(f"planHash (recomputed) : {plan.fingerprint()}")
    print(f"reported planHash      : {payload.get('planHash') or payload.get('currentPlanHash') or '—'}")
    print(f"counts                 : create {counts['create']} · update {counts['update']} · "
          f"retire {counts['retire']} · foreign {counts['foreign']}")

    print("\nCREATE (added to Meta):")
    for i in plan.create:
        print(f"  + {i.get('retailer_id')}  {i.get('name') or ''}")

    print("\nUPDATE (changed fields):")
    for i in plan.update:
        print(f"  ~ {i.get('retailer_id')}  {i.get('name') or ''}")
    if not plan.update:
        print("  (none)")

    print("\nRETIRE (set OUT OF STOCK — reversible, NOT deleted):")
    for i in plan.retire:
        print(f"  ! {i.get('retailer_id')}  {i.get('product_name') or ''}")
    if not plan.retire:
        print("  (none)")

    print("\nFOREIGN (reported only — NEVER touched by sync):")
    for rid in plan.foreign:
        print(f"  = {rid}")
    if not plan.foreign:
        print("  (none)")

    print("\nSafe to apply: CREATE and FOREIGN carry no risk (additions / untouched). "
          "Verify the RETIRE list above is the superseded prior-generation variants before "
          "opening the release gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
