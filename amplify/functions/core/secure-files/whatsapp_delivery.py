"""Deliver already-authorized secure files over WhatsApp using the approved Vault template.

Payment initiation deliberately does not live here.  Secure-file purchases use the canonical
commerce/checkout PaymentAttempt path; this module owns only the post-payment file delivery
transport.

Why a Vault link and not the file itself
----------------------------------------
Every paid file is announced with `wecare_default_download`, the one approved WABA1 template
for this: a fixed IMAGE header and URL button 0 `https://wecare.digital/vault/?file={{1}}`,
of which only the file id travels. The customer signs in on that page and downloads through
the durable paid entitlement.

This replaced two transports that could not work reliably. The document-header template the
PDF/image path named (`wd_file_delivery`) is not on WABA1 (live template readback, 2026-10-25),
so Meta refused every such send; and the fallback put a presigned S3 URL, a bearer capability,
into a free-form text that Meta only accepts inside the 24-hour customer-service window. The
template carries no bearer link and is deliverable at any time.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Tuple

import boto3

from lambda_utils import whatsapp_templates

REGION = os.environ.get("AWS_REGION", "us-east-1")

# The `live` alias: the unqualified name runs $LATEST, which an upload reaches before it is
# published and verified.
SENDER_FUNCTION = os.environ.get("WA_SENDER_FUNCTION", "wecare-outbound-whatsapp:live")
#: Meta's OWN phone-number id. `handler.py` derives the customer's WABA stamp from it; it is
#: WRONG for every `phoneNumberId` passed to `wecare-outbound-whatsapp`, which is why
#: `WA_SEND_PHONE_ID` exists beside it.
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1016149501586345")

#: The AWS-style sender id `outbound-whatsapp` requires. `_resolve_meta_phone_id` accepts only
#: an AWS-style id (its map, or a `-direct-<digits>` suffix) and otherwise raises rather than
#: falling back to another WABA, so the bare Meta id above would be refused.
WA_SEND_PHONE_ID = os.environ.get(
    "WA_SEND_PHONE_ID", "phone-number-id-waba1-direct-1016149501586345")

#: The rule outbound's `url_button_component` enforces on the button suffix. Checked here too
#: so a file id that could never be sent is reported as such, not as a sender HTTP error.
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,120}")

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
    """Announce a paid file with the approved Vault download template. Returns (sent, detail).

    The header and button come from `whatsapp_templates.download_send_fields`, the same
    builder paid Vault delivery and the paid-file refresh use, so the three cannot drift.
    """
    file_id = str(file_row.get("fileId") or "")
    if not _FILE_ID.fullmatch(file_id):
        return False, "file id cannot be sent as a Vault link"

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
    # A dry run answers 200 without sending; recording it as delivered would hide a customer
    # who is still owed the file from scripts/reconcile_file_deliveries.py.
    if body.get("status") == "dry_run" or body.get("mode") == "DRY_RUN":
        return False, "sender is in dry-run mode; nothing was sent"
    return True, str(body.get("whatsappMessageId") or body.get("messageId") or "sent")
