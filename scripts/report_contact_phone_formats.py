#!/usr/bin/env python3
"""List ContactsTable rows whose `phone` is not valid E.164, for staff to fix by hand.

READ-ONLY, AND THAT IS THE DESIGN RATHER THAN A LIMITATION
----------------------------------------------------------
There is no `--apply`, no `--fix`, and no write call of any kind in this file. A script that
rewrites customer phone numbers was considered and deliberately rejected: the stored number is
the identity key (`phone-index` is how a website session, an inbound WhatsApp `wa_id` and the
Cognito username all find one row), uniqueness is enforced on the normalised value, and the
numbers that need fixing are precisely the ones whose country code is UNKNOWN. So a rewrite
would have to guess - and a wrong guess reserves the wrong identity permanently, sends an OTP to
an unrelated subscriber, and cannot be undone by re-running anything. Guessing `+91` for a
ten-digit foreign number is the exact defect `core/contacts` was changed to stop.

A human looking at the CRM row knows which country the customer is in. This script's whole job
is to hand that human a short, actionable list.

WHY ROWS EXIST IN THIS STATE
----------------------------
Until FEAT-005, `core/contacts._create` stored `'+' + normalize_phone(phone)` with no country
inference, so an operator typing `9876543210` produced `+9876543210`. The website then looked up
`+919876543210` and WhatsApp looked up `919876543210`, and neither found the row. New rows cannot
reach this state - the create and update paths now refuse a number with no country code - so this
report covers the backlog only and should trend to zero.

NO FULL PHONE NUMBER IS PRINTED
-------------------------------
Every number is masked to its last four digits. The actionable handle is the contact id, which is
a uuid and not derived from the phone; the last four is enough for a human to match the row
against what they are looking at in the CRM. This output is routinely pasted into a ticket or a
report, which is the whole reason the masking is here and not optional.

Usage
-----
    /Users/wecaredigital/wecare-store/.venv/bin/python scripts/report_contact_phone_formats.py
    ... --json          machine-readable, same masked fields
    ... --include-deleted

Exit code is 0 when every live row is valid E.164, 1 when at least one needs attention, so this
can be a check as well as a report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))

from lambda_utils.identity import customer as customer_identity  # noqa: E402

TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def masked(phone: str) -> str:
    """The last four digits and nothing else.

    Stricter than `lambda_utils.privacy.mask_phone`, which keeps the first three characters so a
    log line stays diagnosable. Here the leading characters are the broken part - a report that
    prints `+98` beside `****3210` has disclosed most of a number on a row whose digits are
    already suspect. Four digits, or `***` when there are not even four.
    """
    digits = [ch for ch in str(phone or "") if ch in "0123456789"]
    if len(digits) < 4:
        return "***"
    return "****" + "".join(digits[-4:])


def diagnose(phone: Any) -> str:
    """Why this value is not storable E.164, in words a human can act on."""
    try:
        normalised = customer_identity.normalize_phone_preserving_country(phone)
    except customer_identity.MissingCountryCode:
        return "no country code: ask the customer which country, then re-save with the dial code"
    except customer_identity.InvalidPhoneNumber as exc:
        return f"not reachable: {exc}"
    if normalised != str(phone):
        # Parseable but not stored in its canonical spelling - separators, a trunk zero, or a
        # `00` prefix. Re-saving the row through the CRM fixes it with no decision required.
        return "parseable but not canonical: re-save the contact to rewrite it"
    return ""


def scan_rows(include_deleted: bool) -> List[Dict[str, Any]]:
    """Every contact row. A scan, because the question is about rows the index cannot select.

    `phone-index` is keyed on the phone, so there is no index that answers "which phones are
    malformed" - the malformed values are the keys. One scan of a table this size is cheaper than
    the conversation about whether the report is complete.
    """
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    rows: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {
        "ProjectionExpression": "#id, #ph, #nm, #del",
        "ExpressionAttributeNames": {"#id": "id", "#ph": "phone", "#nm": "name",
                                     "#del": "deletedAt"},
    }
    while True:
        response = table.scan(**kwargs)
        rows.extend(response.get("Items") or [])
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    if include_deleted:
        return rows
    return [row for row in rows if row.get("deletedAt") is None]


def findings(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for row in rows:
        phone = row.get("phone")
        if not phone:
            # No phone at all is a valid CRM row - `_create` accepts phone OR email - so it is
            # not a finding. Reporting it would bury the rows that need a human.
            continue
        reason = diagnose(phone)
        if not reason:
            continue
        out.append({
            "contactId": str(row.get("id") or ""),
            "name": str(row.get("name") or ""),
            "phoneMasked": masked(phone),
            "digits": str(sum(1 for ch in str(phone) if ch in "0123456789")),
            "hasPlus": "yes" if str(phone).startswith("+") else "no",
            "reason": reason,
        })
    out.sort(key=lambda item: (item["reason"], item["contactId"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--include-deleted", action="store_true",
                        help="include soft-deleted rows (excluded by default)")
    args = parser.parse_args()

    rows = scan_rows(args.include_deleted)
    bad = findings(rows)

    if args.json:
        print(json.dumps({"table": TABLE, "rowsScanned": len(rows),
                          "needsAttention": len(bad), "contacts": bad}, indent=2))
    else:
        print(f"ContactsTable : {TABLE}")
        print(f"rows scanned  : {len(rows)}")
        print(f"not E.164     : {len(bad)}")
        print()
        if bad:
            print(f"{'contactId':38} {'phone':12} {'digits':>6} {'+':>3}  name / reason")
            for item in bad:
                print(f"{item['contactId']:38} {item['phoneMasked']:12} "
                      f"{item['digits']:>6} {item['hasPlus']:>3}  {item['name']}")
                print(f"{'':38} -> {item['reason']}")
        else:
            print("Every live row carries a canonical E.164 phone.")
        print()
        print("Phones are masked to the last four digits. Fix a row by re-saving it in the CRM "
              "with the correct dial code; this script never writes.")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
