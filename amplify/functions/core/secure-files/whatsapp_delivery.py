"""Deliver an already-paid secure file over WhatsApp with the approved download template.

Payment initiation deliberately does not live here.  Secure-file purchases use the canonical
commerce/checkout PaymentAttempt path; this module owns only the post-payment delivery message.

One approved template, one send shape
-------------------------------------
A paid file is announced the way paid Vault delivery announces it: the approved WABA1 template
`wecare_default_download` (IMAGE header, "Access Vault" URL button
`https://wecare.digital/vault/?file={{1}}`), built by `whatsapp_templates.download_send_fields`
with the file id as the button suffix. The customer opens the Vault deep link and collects the
file through the paid entitlement `confirm_and_deliver` has just established.

This replaced a send of `wd_file_delivery`, a template that was never approved on WABA1, so Meta
refuses every send of it. That send also passed its document header in a `components` key
outbound never reads, and the link fallback put its text in a `message` key outbound never reads
either. A template send also works outside the 24-hour customer-service window, which a free-form
link does not, and puts no short-lived bearer URL in the chat.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple

import boto3

from lambda_utils import whatsapp_templates

REGION = os.environ.get("AWS_REGION", "us-east-1")

# The `live` alias: the unqualified name runs $LATEST, which an upload reaches before it is
# published and verified.
SENDER_FUNCTION = os.environ.get("WA_SENDER_FUNCTION", "wecare-outbound-whatsapp:live")

#: Meta's OWN phone-number id for WABA1. The handler stamps it on delivery records; it is WRONG
#: as the `phoneNumberId` passed to `wecare-outbound-whatsapp`, which is why `WA_SEND_PHONE_ID`
#: exists beside it.
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1016149501586345")

#: The AWS-style sender id `outbound-whatsapp` requires. `_resolve_meta_phone_id` accepts only
#: an AWS-style id (its map, or a `-direct-<digits>` suffix) and refuses a bare Meta id rather
#: than fall back to another WABA.
WA_SEND_PHONE_ID = os.environ.get(
    "WA_SEND_PHONE_ID", "phone-number-id-waba1-direct-1016149501586345")

_lambda = None


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


def _invoke(function_name: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Call another Lambda and return (httpStatus, parsedBody)."""
    response = _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = response["Payload"].read()
    result = json.loads(raw.decode("utf-8")) if raw else {}

    if response.get("FunctionError"):
        return 500, {"error": "invoked function raised"}

    status = int(result.get("statusCode") or 0)
    body = result.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"raw": body[:200]}
    return status, (body if isinstance(body, dict) else {})


def send_vault_link(*, phone: str, file_row: Dict[str, Any]) -> Tuple[bool, str]:
    """Send the approved download template for one paid file. Returns (sent, detail)."""
    file_id = str(file_row.get("fileId") or "")
    if not file_id:
        return False, "file has no id"
    status, body = _invoke(
        SENDER_FUNCTION,
        {
            "body": json.dumps(
                {
                    "recipientPhone": phone,
                    "phoneNumberId": WA_SEND_PHONE_ID,
                    **whatsapp_templates.download_send_fields(file_id),
                }
            )
        },
    )
    if status >= 300:
        return False, f"sender returned HTTP {status}"
    return True, str(body.get("whatsappMessageId") or body.get("messageId") or "sent")
