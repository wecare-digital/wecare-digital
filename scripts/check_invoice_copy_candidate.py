#!/usr/bin/env python3
"""Offline, fail-closed review gate for a *new* WhatsApp invoice-receipt template.

This script NEVER calls Meta, AWS, Razorpay, or any sending API. Supply an
operator-exported single-template Meta GET response and the independently
reviewed numeric template ID. It only validates the proposed receipt variant;
the signed-off legacy template and payment order-status transitions are
unchanged. Passing this script is not an authorization to select or send it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

CANDIDATE_NAME = "wecare_invoice_receipt_v2"
CANDIDATE_BODY = (
    "🧾 Your GST invoice is ready. "
    "The invoice image above contains your transaction details."
)
EXPECTED_FOOTER = "WECARE.DIGITAL"
EXPECTED_FLOW_ID = "993862443003108"


def validate(candidate: Any, *, expected_id: str) -> list[str]:
    """Provider shape and exact reviewed copy. No customer data in errors."""
    if not isinstance(candidate, dict):
        return ["provider response must be one template object"]
    issues: list[str] = []
    if not re.fullmatch(r"[1-9][0-9]*", expected_id):
        issues.append("reviewed expected template ID must be a positive numeric ID")
    if str(candidate.get("id") or "") != expected_id:
        issues.append("template ID does not match reviewed provider ID")
    for field, expected in (
        ("name", CANDIDATE_NAME),
        ("language", "en"),
        ("category", "UTILITY"),
        ("status", "APPROVED"),
    ):
        if candidate.get(field) != expected:
            issues.append(f"{field} does not match expected {expected}")
    components = candidate.get("components")
    if not isinstance(components, list) or len(components) != 4:
        return issues + ["expected exactly IMAGE header, BODY, FOOTER, BUTTONS"]
    groups: dict[str, list[dict]] = {}
    for component in components:
        if not isinstance(component, dict):
            issues.append("provider component must be an object")
            continue
        kind = component.get("type")
        groups.setdefault(str(kind), []).append(component)
    if set(groups) != {"HEADER", "BODY", "FOOTER", "BUTTONS"}:
        issues.append("unrecognized or missing template component")
    if any(len(items) != 1 for items in groups.values()):
        issues.append("each component type must occur exactly once")
    header = (groups.get("HEADER") or [{}])[0]
    if header.get("format") != "IMAGE":
        issues.append("invoice receipt must retain an IMAGE header")
    body = (groups.get("BODY") or [{}])[0]
    if body.get("text") != CANDIDATE_BODY:
        issues.append("body differs from the independently reviewed invoice-specific copy")
    footer = (groups.get("FOOTER") or [{}])[0]
    if footer.get("text") != EXPECTED_FOOTER:
        issues.append("footer does not match WECARE.DIGITAL")
    buttons = (groups.get("BUTTONS") or [{}])[0].get("buttons")
    if not isinstance(buttons, list) or len(buttons) != 1:
        issues.append("expected exactly one Leave Review FLOW button")
    else:
        button = buttons[0]
        if not isinstance(button, dict) or (
            button.get("type") != "FLOW"
            or button.get("text") != "Leave Review"
            or str(button.get("flow_id") or "") != EXPECTED_FLOW_ID
            or button.get("flow_action") != "DATA_EXCHANGE"
        ):
            issues.append("Leave Review FLOW button identity or action changed")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True,
                        help="Meta single-template JSON export; no recipient data")
    parser.add_argument("--expected-id", required=True,
                        help="reviewed ID of NEW approved template, not the live legacy ID")
    args = parser.parse_args(argv)
    try:
        candidate = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}), file=sys.stderr)
        return 2
    issues = validate(candidate, expected_id=args.expected_id)
    print(json.dumps({
        "ok": not issues,
        "name": CANDIDATE_NAME,
        "expected_id": args.expected_id,
        "issues": issues,
        "live_payment_rail_modified": False,
        "requires_payment_owner_and_handset_approval": True,
    }, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
