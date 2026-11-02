#!/usr/bin/env python3
"""Rewrite the two live WhatsApp welcome rows so neither mentions a menu.

Run with the repository `.venv` interpreter, which is where boto3 lives:

    .venv/bin/python scripts/update_welcome_message_config.py            # dry run
    .venv/bin/python scripts/update_welcome_message_config.py --apply    # write

`AWS_PROFILE=wecare-prod` is exported from `~/.zprofile`, so no credential is
passed here, on the command line, or anywhere else. Nothing is read from Secrets
Manager and nothing secret is printed.

Why this exists
---------------
Every WhatsApp menu was deleted on 2026-10-02. Both `welcome_message` (phone 1)
and `welcome_message_2` (phone 2) still ended with "Tap *Menu* to get started",
pointing a customer at something that no longer exists. Both rows ARE read at
runtime - `inbound-whatsapp-handler._load_welcome_text` and
the shared welcome configuration both use `textMessage` - so this is a
real customer-facing copy change, which is why the before-value is printed and
the default behaviour is a dry run.

Safety properties, deliberately
-------------------------------
* Dry run by default. `--apply` is required to write.
* `update_item` touches `configValue` and `updatedAt` only, under a condition
  that the row already exists, so a typo cannot create a new row.
* The parsed document is round-tripped, so any field this script does not know
  about survives (`phoneNumberId`, `delaySeconds`, `welcomeBackMessage`, ...).
* `ensure_ascii=False` matches the encoding of the rows already stored, so the
  emoji stays one character rather than becoming an escape sequence.
* If a row is missing, or its `configValue` does not parse, it STOPS rather than
  guessing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Tuple

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

TABLE_NAME = "stack-wecare-digital-SystemConfigTable"
REGION = "us-east-1"
ROW_IDS = ("welcome_message", "welcome_message_2")

#: Menu-free replacement. Same three-paragraph shape as the copy it replaces, so
#: the message reads the same way; only the final call to action changes, because
#: there is no menu to tap.
NEW_TEXT = (
    "Hi there! \U0001f44b Welcome to WECARE.DIGITAL\n\n"
    "Shop, pay, track requests, or get support \u2014 all right here.\n\n"
    "Just tell us what you need, or send a voice note."
)


def _load(table, row_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return `(item, parsed_config)` or exit non-zero with a reason."""
    try:
        result = table.get_item(Key={"id": row_id})
    except ClientError as exc:
        sys.exit(f"STOP: get_item failed for {row_id}: {type(exc).__name__}")
    item = result.get("Item")
    if not item:
        sys.exit(f"STOP: row {row_id!r} does not exist in {TABLE_NAME}; refusing to create it")
    raw = item.get("configValue")
    if raw is None:
        sys.exit(f"STOP: row {row_id!r} has no configValue attribute")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError) as exc:
        sys.exit(f"STOP: configValue on {row_id!r} does not parse as JSON: {type(exc).__name__}")
    if not isinstance(parsed, dict):
        sys.exit(f"STOP: configValue on {row_id!r} is not a JSON object")
    return item, parsed


def _report(label: str, row_id: str, parsed: Dict[str, Any]) -> None:
    print(f"  {label} {row_id}")
    print(f"    textMessage : {parsed.get('textMessage', '')!r}")
    print(f"    sendMenu    : {parsed.get('sendMenu')!r}")
    print(f"    other keys  : {sorted(k for k in parsed if k not in ('textMessage', 'sendMenu'))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="perform the write (default is a dry run that changes nothing)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    print(f"table  : {TABLE_NAME} ({REGION})")
    print(f"rows   : {', '.join(ROW_IDS)}")
    print(f"mode   : {'APPLY' if args.apply else 'DRY RUN'}\n")

    staged = []
    for row_id in ROW_IDS:
        item, parsed = _load(table, row_id)
        _report("BEFORE", row_id, parsed)
        after = dict(parsed)
        after["textMessage"] = NEW_TEXT
        if "sendMenu" in after:
            after["sendMenu"] = False
        _report("AFTER ", row_id, after)
        print()
        staged.append((row_id, item, after))

    if not args.apply:
        print("DRY RUN - nothing written. Re-run with --apply to write.")
        return 0

    now = int(time.time())
    for row_id, _item, after in staged:
        after["updatedAt"] = now
        try:
            table.update_item(
                Key={"id": row_id},
                UpdateExpression="SET configValue = :cv, updatedAt = :ts",
                ExpressionAttributeValues={
                    ":cv": json.dumps(after, ensure_ascii=False),
                    ":ts": now,
                },
                ConditionExpression=Attr("id").exists(),
            )
        except ClientError as exc:
            sys.exit(f"STOP: update_item failed for {row_id}: {type(exc).__name__}")
        print(f"WROTE {row_id}")

    print("\nRe-reading to confirm:")
    for row_id in ROW_IDS:
        _item, parsed = _load(table, row_id)
        _report("NOW   ", row_id, parsed)
        if parsed.get("textMessage") != NEW_TEXT:
            sys.exit(f"STOP: {row_id} did not take the new text")
        if "menu" in str(parsed.get("textMessage", "")).lower():
            sys.exit(f"STOP: {row_id} still mentions a menu")
    print("\nOK - both rows are menu-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
