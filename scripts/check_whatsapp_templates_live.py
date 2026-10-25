#!/usr/bin/env python3
"""Read-only: compare the template registry with the live WABA1 template list.

`amplify/functions/shared/lambda_utils/whatsapp_templates.py` is the one place the platform names
the templates it sends. Meta is the authority on whether each one is APPROVED. This script reads
the live list through `wecare-whatsapp-business-api:live` `/wa-business/payment-templates/list`,
the same sub_category-bearing readback the send gates trust, and checks every registered
template:

  * it exists on WABA1 and is APPROVED;
  * its category and language match the registry;
  * its sub_category matches when the registry names one (ORDER_STATUS).

It prints template names and verdicts only, never message content or customer data, and writes
nothing. Exit 0 when every registered template matches, 1 on any mismatch, 2 when the live list
cannot be read.

    python scripts/check_whatsapp_templates_live.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))

from lambda_utils import whatsapp_templates  # noqa: E402

REGION = "us-east-1"
WABA_ID = "2094615664435155"
READ_FUNCTION = "wecare-whatsapp-business-api:live"


def live_templates() -> list:
    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=READ_FUNCTION, InvocationType="RequestResponse",
        Payload=json.dumps({"httpMethod": "GET", "path": "/wa-business/payment-templates/list",
                            "queryStringParameters": {"wabaId": WABA_ID}}).encode())
    payload = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError("live template list unavailable")
    body = payload.get("body")
    rows = (json.loads(body) if isinstance(body, str) else body or {}).get("data")
    return rows if isinstance(rows, list) else []


def main() -> int:
    try:
        rows = live_templates()
    except Exception as error:  # noqa: BLE001 - a read failure is its own exit code
        print(f"ERROR could not read the live template list: {type(error).__name__}")
        return 2
    by_name = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            by_name.setdefault(row["name"], []).append(row)

    problems = 0
    for template in whatsapp_templates.ALL:
        candidates = by_name.get(template.name, [])
        live = next((r for r in candidates if r.get("language") == template.language), None)
        issues = []
        if not candidates:
            issues.append("not on WABA1")
        elif live is None:
            issues.append(f"no '{template.language}' language variant")
        else:
            if live.get("status") != "APPROVED":
                issues.append(f"status {live.get('status')}")
            if live.get("category") != template.category:
                issues.append(f"category {live.get('category')} != {template.category}")
            if template.sub_category and live.get("sub_category") != template.sub_category:
                issues.append(f"sub_category {live.get('sub_category')} != {template.sub_category}")
        verdict = "OK  " if not issues else "FAIL"
        role = "automated" if template.automated else "manual"
        print(f"{verdict} {template.name:42} {role:9} " + ("; ".join(issues) if issues else "APPROVED"))
        problems += bool(issues)

    unregistered = sorted(set(by_name) - {t.name for t in whatsapp_templates.ALL})
    if unregistered:
        print("live but not in the registry (informational): " + ", ".join(unregistered))
    print(f"\n{len(whatsapp_templates.ALL) - problems}/{len(whatsapp_templates.ALL)} registered "
          "templates match WABA1")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
