#!/usr/bin/env python3
"""Read-only selective-erasure inventory for staff review.

Usage:
  python scripts/preview_selective_erasure.py --region us-east-1

This command never writes, deletes, archives, unlocks or executes an erasure.
It reads private `retention-hold` tags from ConversationMetaTable, so no
customer ID or phone needs to be embedded in public GitHub code. It prints
aggregate counts only, never the sensitive per-record manifest.

It is NOT a deletion authorization: the financial/data-dependency inventory
is incomplete until the cross-service reviewer supplies exact linkage,
Cognito/identity-claim and S3 object version evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "amplify" / "functions" / "shared"))

from lambda_utils.erasure.selective_preview import (  # noqa: E402
    build_preview, ErasurePreviewError,
)


def _scan(table: Any) -> list[dict]:
    """Read all pages; an incomplete scan refuses the entire preview."""
    items: list[dict] = []
    cursor: dict[str, Any] = {}
    while True:
        page = table.scan(**cursor)
        items.extend(page["Items"])
        if not page.get("LastEvaluatedKey"):
            return items
        cursor = {"ExclusiveStartKey": page["LastEvaluatedKey"]}


def build_live_preview(region: str, prefix: str, required_holds: int = 2) -> dict:
    import boto3  # local to the CLI; the planner is dependency-free

    dynamodb = boto3.resource("dynamodb", region_name=region)

    def read(name: str) -> list[dict]:
        return _scan(dynamodb.Table(prefix + name))

    meta = read("ConversationMetaTable")
    protected = {
        str(row.get("conversationId") or "").strip()
        for row in meta
        if "retention-hold" in (row.get("tags") or [])
    }
    protected.discard("")
    if len(protected) < required_holds:
        raise ErasurePreviewError(
            "Required private retention holds not found; no preview or deletion is valid"
        )

    contacts = read("ContactsTable")
    messages = {
        "MessagesTable": read("MessagesTable"),
        "WhatsAppInboundTable": read("WhatsAppInboundTable"),
        "WhatsAppOutboundTable": read("WhatsAppOutboundTable"),
    }
    financial = {
        "payments": read("PaymentsTable"),
        "payment_attempts": read("PaymentAttemptsTable"),
        "invoices": read("InvoicesTable"),
        "orders": read("OrderTable"),
    }

    preview = build_preview(
        contacts=contacts,
        messages=messages,
        financial=financial,
        protected_contact_ids=protected,
        # This command cannot certify every Cognito, claim, S3 or provider copy.
        dependency_inventory_complete=False,
    )
    return preview.summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only erasure candidate inventory")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--table-prefix", default="stack-wecare-digital-")
    parser.add_argument("--required-holds", type=int, default=2)
    args = parser.parse_args()
    if args.required_holds < 1:
        parser.error("--required-holds must be positive")

    try:
        summary = build_live_preview(
            region=args.region, prefix=args.table_prefix,
            required_holds=args.required_holds)
    except (ErasurePreviewError, Exception) as exc:
        # Do not print a provider exception message that could expose raw PII.
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "readOnly": True, "deleted": 0}), file=sys.stderr)
        return 2

    print(json.dumps({"ok": True, "readOnly": True, **summary},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
