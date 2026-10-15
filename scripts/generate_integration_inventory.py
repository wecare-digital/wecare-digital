#!/usr/bin/env python3
"""Emit the integration registry as JSON the frontend can render.

Why a generated snapshot rather than a live API call
---------------------------------------------------
`lambda_utils/integrations/registry.py` was built in 7.1 and then imported by
**nothing** — it described eight providers and no surface showed them. This closes that
without inventing an endpoint, because the registry makes **no provider call**: it is a
static description plus a `DescribeSecret` existence check. There is no live number to
fetch, so an HTTP round trip would add a route, an auth gate and a failure mode in order
to return a constant.

What that costs, stated rather than skipped: the credential-existence half is frozen at
generation time. The registry's own doctrine is that *freshness must be explicit and
comparable* — "a cached metric rendered without its age is how a dashboard shows last
week's numbers as today's" — so the snapshot carries `generatedAt` and the pages render
it. A stale snapshot is visible rather than silent.

Regenerate whenever a credential or scope changes:

    python scripts/generate_integration_inventory.py

`--check` exits 1 if the committed file is out of date, so CI can catch a registry change
that never reached the UI.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "src/content/integration-registry.json"
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

def build() -> dict:
    from lambda_utils.integrations import registry

    described = registry.describe_registry()
    waiting = registry.waiting_for_owner()

    providers = []
    for key, entry in described.items():
        record = dict(entry) if isinstance(entry, dict) else {"access": entry}
        record["key"] = key
        record["unblock"] = waiting.get(key)
        providers.append(record)
    providers.sort(key=lambda p: p["key"])

    counts: dict[str, int] = {}
    for p in providers:
        counts[p.get("access", "UNKNOWN")] = counts.get(p.get("access", "UNKNOWN"), 0) + 1

    return {
        # Deliberately not a bare date: the pages show this, and the registry insists
        # that an age rendered without its timestamp is how stale data passes as fresh.
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
        "source": "amplify/functions/shared/lambda_utils/integrations/registry.py",
        "note": ("Generated. Access is three-state on purpose: a credential existing is "
                 "not a scope being granted, and VERIFIED means a real authorised read "
                 "succeeded and was recorded. Nothing here claims VERIFIED."),
        "counts": counts,
        "providers": providers,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the committed file is out of date")
    args = parser.parse_args(argv)

    fresh = build()

    if args.check:
        if not OUT.exists():
            print(f"FAIL {OUT} does not exist; run this script", file=sys.stderr)
            return 1
        committed = json.loads(OUT.read_text())
        # generatedAt always differs, so compare everything else.
        a = {k: v for k, v in committed.items() if k != "generatedAt"}
        b = {k: v for k, v in fresh.items() if k != "generatedAt"}
        if a != b:
            print("FAIL the registry has changed and the committed inventory has not. "
                  "Run scripts/generate_integration_inventory.py", file=sys.stderr)
            return 1
        print(f"inventory current: {len(committed['providers'])} providers, "
              f"{committed['counts']}")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fresh, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  {len(fresh['providers'])} providers: {fresh['counts']}")
    for p in fresh["providers"]:
        print(f"    {p['key']:20} {p.get('access')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
