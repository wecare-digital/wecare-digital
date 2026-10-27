"""Read-only production smoke check for the WhatsApp backend.

This script never sends a customer message. It validates the live Lambda aliases and the bounded
internal operational contracts used by Workspace MCP. A future mutation smoke must be a separate
explicitly gated tool with a QA recipient; do not extend this script to send.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3

REGION = "us-east-1"
EXPECTED = {
    "wecare-inbound-whatsapp": "Active",
    "wecare-outbound-whatsapp": "Active",
    "wecare-whatsapp-business-api": "Active",
    "wecare-service-api": "Active",
    "wecare-workspace-mcp": "Active",
}


def invoke(lamb, function: str, payload: dict) -> dict:
    response = lamb.invoke(
        FunctionName=function,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )
    raw = response["Payload"].read()
    if response.get("FunctionError"):
        raise RuntimeError(f"{function}: FunctionError")
    value = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{function}: non-object response")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    lamb = boto3.client("lambda", region_name=REGION)

    checks = []
    ok = True
    for fn, expected_tracing in EXPECTED.items():
        cfg = lamb.get_function_configuration(FunctionName=fn, Qualifier="live")
        row = {
            "name": fn,
            "version": cfg.get("Version"),
            "status": cfg.get("LastUpdateStatus"),
            "tracing": (cfg.get("TracingConfig") or {}).get("Mode"),
        }
        row["ok"] = row["status"] == "Successful" and row["tracing"] == expected_tracing
        checks.append(row)
        ok &= row["ok"]

    snapshot = invoke(
        lamb,
        "wecare-whatsapp-business-api:live",
        {"internalAction": "workspaceRead", "scope": "snapshot", "limit": 25},
    )
    unknown = invoke(
        lamb,
        "wecare-whatsapp-business-api:live",
        {"internalAction": "workspaceRead", "scope": "unknown_deliveries", "limit": 25},
    )
    orders = invoke(
        lamb,
        "wecare-service-api:live",
        {"internalAction": "workspaceOrders", "limit": 5},
    )

    contracts_ok = (
        snapshot.get("scope") == "snapshot"
        and isinstance(snapshot.get("unknownDeliveries"), dict)
        and unknown.get("scope") == "unknown_deliveries"
        and isinstance(unknown.get("items"), list)
        and isinstance(orders.get("orders"), list)
    )
    ok &= contracts_ok
    print(json.dumps({
        "ok": ok,
        "functions": checks,
        "snapshot": snapshot,
        "unknownDeliveries": {
            "count": len(unknown.get("items") or []),
            "nextCursor": bool(unknown.get("nextCursor")),
        },
        "orders": {"count": len(orders.get("orders") or [])},
        "contractsOk": contracts_ok,
        "mutationFree": True,
    }, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
