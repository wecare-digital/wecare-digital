#!/usr/bin/env python3
"""Read-only audit of one WhatsApp outbound WAMID against Meta Message History.

This tool never sends a WhatsApp message and never changes a delivery claim. It invokes the
internal action on wecare-whatsapp-business-api:live, which maps the WAMID to Meta's Message
History record and then reads its delivery events.

Exit:
  0 Meta has at least one ACCEPTED/SENT/DELIVERED/READ event
  1 history found but no positive delivery event (or not found)
  2 audit could not be completed
"""
from __future__ import annotations

import argparse
import json

import boto3

REGION = "us-east-1"
FUNCTION = "wecare-whatsapp-business-api:live"
DEFAULT_PHONE_ID = "1016149501586345"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wamid", required=True, help="WhatsApp message id returned by Meta")
    parser.add_argument("--phone-id", default=DEFAULT_PHONE_ID,
                        help="Meta phone-number id that sent the message")
    parser.add_argument("--function", default=FUNCTION)
    args = parser.parse_args()

    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=args.function,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "internalAction": "messageHistoryForWamid",
            "phoneId": args.phone_id,
            "whatsappMessageId": args.wamid,
        }).encode("utf-8"),
    )
    raw = response["Payload"].read()
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "error": "UNREADABLE_LAMBDA_RESPONSE"}))
        return 2

    if response.get("FunctionError"):
        print(json.dumps({"ok": False, "error": "LAMBDA_FUNCTION_ERROR"}))
        return 2
    if result.get("error"):
        print(json.dumps({"ok": False, **result}, default=str))
        return 2

    print(json.dumps({"ok": True, **result}, indent=2, default=str))
    return 0 if result.get("metaAcceptedOrDelivered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
