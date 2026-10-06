#!/usr/bin/env python3
"""Seed the `ai_hybrid_routing` config row, so the runtime kill switch actually exists.

What was broken
---------------
`inbound-whatsapp-handler/handler.py` defined `_is_deterministic_trigger` **twice**, and
the hardcoded second definition shadowed the config-driven first one. So the function that
reads this row and honours `enabled: false` was never the function being called — the kill
switch was unreachable code. The row itself was also **ABSENT** from
`stack-wecare-digital-SystemConfigTable` (measured 2026-10-06 by GetItem), so it had never
been exercised and would not have worked if it had been written.

Both halves are now fixed: the shadow was deleted, and this writes the row.

Why seeding it changes nothing on the day it runs
-------------------------------------------------
`CONFIG_VALUE` below is **identical to the handler's built-in defaults**, which in turn
reproduce the deleted hardcoded function's decision set exactly. So the row is a no-op at
the moment it lands, which is the only safe way to introduce configuration to a live
decision path: a seed that changes behaviour is a behaviour change dressed as
configuration. `tests/test_deterministic_trigger_equivalence.py` asserts this file and the
handler agree, so the two cannot drift.

What the switch then buys
-------------------------
Setting `enabled: false` on this row makes `_is_deterministic_trigger` return False for
every input, which means **zero standby replies, with no code deploy**. That matters here
more than usual: the Meta ingress invokes `wecare-inbound-whatsapp` unqualified, so
`$LATEST` is production and there is no staging gap — a code-based stop is live the instant
it uploads, whereas this one is a single `update_item` with a 60-second cache behind it.

It is the blunter of the two available stops. The narrower one is
`STANDBY_REPLY_ENABLED=false`, which keeps our deterministic flow deciding and suppresses
only the standby *send*. Reach for this row when the decision set itself is the problem.

Usage:
    .venv/bin/python scripts/seed_ai_hybrid_routing.py --dry-run
    .venv/bin/python scripts/seed_ai_hybrid_routing.py
    .venv/bin/python scripts/seed_ai_hybrid_routing.py --verify
"""

from __future__ import annotations

import argparse
import json

import boto3

REGION = "us-east-1"
TABLE = "stack-wecare-digital-SystemConfigTable"
CONFIG_ID = "ai_hybrid_routing"

#: MUST equal the handler's built-in defaults in `_get_routing_config`, which reproduce
#: the deleted hardcoded `_is_deterministic_trigger`. Pinned by
#: tests/test_deterministic_trigger_equivalence.py::TestTheDefaultsMatchTheSeedScript.
#:
#: `contains` is deliberately EMPTY. The config-driven function's original defaults used
#: substring matching, which would have claimed any free-form message containing 'pay',
#: 'track', 'faq' or 'help' away from the Meta AI — a real behaviour change. Substring
#: matching stays available as an opt-in by editing this row; it is not the default.
CONFIG_VALUE = {
    "enabled": True,
    "types": ["button", "interactive", "order", "nfm_reply"],
    "keywords": sorted({
        'hi', 'hello', 'hey', 'menu', 'main menu', 'show menu', 'start', 'get started',
        'browse menu', '/menu', 'need help!', 'subscribe', 'pay', '/pay', 'catalog',
        'view catalog', 'submit request', 'track request', 'track', 'amend request',
        'appointment', 'rx slot', 'drop docs', 'enterprise', 'leave review', 'faq',
        'get help', 'hi \U0001f44b',
    }),
    "contains": [],
    "commandPrefix": "/",
}


def table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def read():
    return table().get_item(Key={"id": CONFIG_ID}).get("Item")


def verify() -> int:
    item = read()
    if not item:
        print(f"FAIL row id={CONFIG_ID} does not exist in {TABLE}")
        return 1
    raw = item.get("configValue")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (ValueError, TypeError):
        print(f"FAIL configValue is not readable JSON")
        return 1

    problems = []
    if data.get("enabled") is not True:
        problems.append(f"enabled is {data.get('enabled')!r}, expected True - seeding this "
                        f"row must not change behaviour on the day it lands")
    for key in ("types", "keywords", "contains"):
        if sorted(data.get(key) or []) != sorted(CONFIG_VALUE[key]):
            problems.append(f"{key} does not match the handler's built-in defaults")
    if data.get("commandPrefix") != CONFIG_VALUE["commandPrefix"]:
        problems.append(f"commandPrefix is {data.get('commandPrefix')!r}")

    print(f"table: {TABLE}")
    print(f"row: id={CONFIG_ID}")
    print(f"enabled: {data.get('enabled')}")
    print(f"types: {data.get('types')}")
    print(f"keywords: {len(data.get('keywords') or [])} entries")
    print(f"contains: {data.get('contains')} (empty = substring matching OFF)")
    print(f"commandPrefix: {data.get('commandPrefix')!r}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nai_hybrid_routing kill switch exists and is a no-op as seeded")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    existing = read()
    print(f"region: {REGION}\ntable: {TABLE}\nrow exists: {bool(existing)}")
    if args.dry_run:
        print(f"would write id={CONFIG_ID} configValue="
              f"{json.dumps(CONFIG_VALUE, sort_keys=True)}")
        print("\ndry run: nothing changed")
        return 0

    table().put_item(Item={
        "id": CONFIG_ID,
        # Stored as a JSON string: the handler's loader accepts either a string or a map
        # (`json.loads(raw) if isinstance(raw, str) else raw`), and a string keeps the
        # list ordering and the emoji literal intact through the console editor.
        "configValue": json.dumps(CONFIG_VALUE, sort_keys=True),
        "description": ("Which inbound messages our deterministic flow claims rather than "
                        "leaving to the Meta AI agent. Set enabled=false to stop every "
                        "standby reply at the decision function with no code deploy."),
        "managedBy": "script:seed_ai_hybrid_routing",
    })
    print(f"wrote id={CONFIG_ID}")
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
